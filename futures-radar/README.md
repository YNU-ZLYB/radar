# Futures Radar · 郑商所期货资讯研判平台

个人使用的期货信息工作台：围绕郑商所品种采集资讯 → 识别品种/因子 → 多空研判 → 按重要性排序 → 生成每日简报。
当前为 P0 版本，**未配置 DeepSeek Key 时使用免费规则引擎，完整功能可离线运行**。

> 仅用于信息整理与研判辅助，不构成投资建议。

## 1. 快速启动

### 后端（FastAPI + SQLite）

```bash
cd /workspace/futures-radar/backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

首次启动会自动建表并写入：
- 5 个活跃品种：白糖 SR、棉花 CF、甲醇 MA、纯碱 SA、玻璃 FG（其余郑商所品种占位）
- 8 类影响因子与品种-因子权重
- 6 个数据源配置
- 10 条标题带 `【示例】` 的演示资讯

访问：
- 前端（已构建）：http://localhost:8000/
- API 文档：http://localhost:8000/docs

### 前端开发模式（可选）

```bash
cd /workspace/futures-radar/frontend
npm run dev        # http://localhost:5173，/api 自动代理到 8000
npm run build      # 产物 dist/，后端会自动挂载
```

### 一键启动（自己电脑上运行）

- Windows：双击 `启动.bat`
- macOS：双击 `启动.command`
- Linux：`./start.sh`

首次运行会自动创建虚拟环境并安装依赖，随后自动打开浏览器；控制台会同时打印手机/局域网访问地址 `http://电脑IP:8000`。

### 部署成网址（服务器）

服务器安装 Docker 后，在项目根目录执行：

```bash
docker compose up -d --build
```

访问 `http://服务器IP:8000`，数据持久化在 `./data`。配置 DeepSeek Key：在根目录创建 `.env` 写入 `DEEPSEEK_API_KEY=...` 后重新 `docker compose up -d`。

### 手机安装（PWA）

在手机 Chrome / Edge 打开页面 → 菜单「添加到主屏幕 / 安装应用」，即可获得全屏图标入口。注意：Chromium 仅在 HTTPS 或 localhost 下启用完整 PWA 能力；局域网 HTTP 访问时只能添加普通书签快捷方式。

## 2. 接入 DeepSeek（可选）

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 DEEPSEEK_API_KEY
```

重启后端后：
- 顶栏模式变为 `DeepSeek · deepseek-chat`
- 异步 Worker 自动改用 LLM 结构化研判（严格 JSON + evidence 原文校验）
- LLM 失败自动回退规则引擎，不影响页面

未配置 Key 时，异步 Worker 用规则引擎补全精判，页面表现与 LLM 模式一致（仅研判质量不同）。

## 3. 已接入的数据源

| 代码 | 来源 | 级别 | 频率 | 说明 |
|---|---|---|---|---|
| `jin10_flash` | 金十快讯 | C | 60s | 快讯流，规则初筛后入库 |
| `sina_oil` | 新浪 Brent/WTI/INE SC + 外盘 | F | 60s | 盘中报价 + 迷你走势；外盘含 ICE 美棉、CBOT 大豆/豆粕/豆油/玉米/小麦、NYMEX 天然气、COMEX 铜、美元指数 |
| `sina_rss` | 新浪财经滚动 RSS | C | 15min | 粗筛期货/商品关键词 |
| `fred_brent` | FRED Brent 日线 | F | 6h | 历史序列，日频 |
| `czce_announce` | 郑商所公告 | A | 120s | 官网有瑞数反爬，常见 412，失败会写日志 |
| `manual` | 手工录入 | E | — | 兜底，适合粘贴群消息 |

Oman/Dubai 暂无免费实时源，界面标记「待接入」。

## 4. 核心链路

1. 采集落库（URL/正文哈希 + 7 天内标题相似度去重）
2. 品种识别：命中别名，或命中 ≥2 个品种关键词（降低「伊朗」「配额」等泛词误报）
3. 规则快判：方向、强度、因子、事件类型 → 立即入库并通过 SSE 推送
4. 异步精判：LLM（或规则补全）→ 更新评分与排序 → 二次推送
5. 评分：`S = 方向 × 强度 × 置信度 × 来源权重 × 新鲜度 × 新颖度`
6. 展示：多空榜、信息流、详情、品种页、每日简报

### 跨市场传导（`services/linkage.py`）

外盘涨跌幅 × 经验权重 = 国内品种的同向压力，输出 -100~100 的 `signal`：
- 能化（甲醇/PTA/PX/瓶片/短纤/纯碱/玻璃/尿素/烧碱）主要看布伦特、NYMEX 天然气
- 油脂油料（菜油/菜粕/油菜籽）主要看 CBOT 豆油/豆粕/大豆
- 白糖看 ICE 原糖（源缺失时用布伦特弱权重兜底），棉花/棉纱看 ICE 美棉，小麦看 CBOT 小麦
- 卡片显示「外盘 美棉 +0.4% → 传导偏多」；详情抽屉展开各外盘品种权重与贡献值
- DeepSeek 日度研判会收到外盘快照 + 传导明细，由模型自行给出 `linkage_weight`（存入 `factor_weights["外盘传导"]`）

## 5. 主要接口

```
GET  /api/v1/dashboard
GET  /api/v1/varieties            GET /api/v1/varieties/{code}
GET  /api/v1/articles             GET /api/v1/articles/{id}
POST /api/v1/articles/manual      POST /api/v1/articles/{id}/feedback
GET  /api/v1/market/oil           GET  /api/v1/sources
POST /api/v1/tasks/run/{task}     GET  /api/v1/digests
POST /api/v1/digests/generate     GET /api/v1/digests/{date}/markdown
GET  /api/v1/stream               (SSE：article_new / analysis_update / oil_update)
```

## 6. 目录结构

```
futures-radar/
├── backend/
│   ├── app/
│   │   ├── main.py           启动、调度、静态挂载
│   │   ├── models.py         SQLite 模型
│   │   ├── seed.py           品种/因子/来源/示例数据
│   │   ├── collectors/       金十、新浪 RSS、郑商所
│   │   ├── services/         规则、评分、流水线、LLM、行情、简报、Worker
│   │   └── api/routes.py     REST + SSE
│   └── data/radar.db
└── frontend/                 Vue3 + Vite，自定义 CSS
```

## 7. 已知限制（P0）

- 郑商所官网 412：采集器容错并记录失败；后续可用 Playwright 或人工补录
- 免费源存在源端延迟（通常分钟级），平台轮询再加 1–15 分钟
- 无向量聚类/情绪曲线/推送告警，这些在 P1
- 规则模式对语义理解有限，接入 DeepSeek 后精度提升明显
- 示例数据带 `【示例】` 前缀，仅用于演示，可按需在数据库中删除
- ICE 原糖（`hf_SB`）与美元指数（`hf_DX`）暂无可用免费实时源，缺数据时自动跳过
