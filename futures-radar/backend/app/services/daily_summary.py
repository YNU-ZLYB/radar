"""品种日度汇总研判：每天一次调 DeepSeek，把该品种近 N 天资讯综合判断。

产出：
  - direction / sentiment_llm / confidence / horizon
  - factor_weights（LLM 自己评估各因子权重，覆盖静态权重做"专家修正"）
  - summary（一句话，Dashboard 卡片下方展示）
  - reasoning / evidence / article_count
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import desc, select

from ..config import settings
from ..db import SessionLocal
from ..models import Analysis, DailySummary, RawDoc, Score, Variety, VarietyQuote, utc_now
from .linkage import compute_linkage
from .market import foreign_latest

CST = ZoneInfo("Asia/Shanghai")
FACTOR_NAMES = ["供给", "需求", "库存", "成本", "政策", "天气", "宏观", "资金/结构"]

SYSTEM_PROMPT = """你是一名专注中国期货市场（郑商所品种）的资深研究员。
现在需要你对某一品种过去几天的资讯进行"汇总研判"，给出综合结论。

要求：
1. 只依据提供的资讯列表、今日盘面、外盘行情与传导关系，不得编造其他外部数据。
2. 给 direction（bullish/bearish/neutral）和 sentiment_llm（-100~100 情绪分数，可小数）。
3. 给 factor_weights：一个对象，只含供给/需求/库存/成本/政策/天气/宏观/资金/结构 这 8 个因子的相对权重（0-100，整数）。
4. summary：一句话结论，40 字以内，用于卡片下方直接展示。
5. evidence：从资讯标题里挑最多 3 个最关键的标题（原样截取）。
6. horizon：intraday / short / medium / long。
7. confidence：0-1。
8. 会附上【外盘传导】：外盘期货品种的涨跌幅及经验传导权重，以及按权重算出的同向压力。
   请把外盘纳入判断：资讯与外盘同向时提高置信度，冲突时降低置信度并在 reasoning 说明。
   不得编造外盘数据，只能引用给出的数字。
9. 地缘政治是能化品种（甲醇/PTA/PX/瓶片/短纤/纯碱/玻璃/尿素/烧碱）的首要变量之一：
   中东局势、霍尔木兹海峡、OPEC+ 政策、制裁/禁运、关税、俄乌、红海等事件，应按
   「原油/天然气成本 → 运费 → 供给」链条评估，因子权重上宏观/成本应显著高于一般供需消息；
   同时区分「持续升级」与「一次性冲击」，一次性冲击要打折。
10. 盘面约束：今日主力涨跌幅绝对值 ≥3% 时，结论方向必须与盘面一致；若资讯逻辑相反，
    在 reasoning 中写明「盘面主导/利空已充分计价」，并降低 confidence。
    涨跌幅 1.5%~3% 时，盘面应占较高权重；<1.5% 时以资讯为主。
11. linkage_weight：0-1，你认为外盘传导在本次结论中应占的权重（无传导关系填 0）。
12. 输出严格 JSON，不要 Markdown，不要额外说明。

JSON 结构：
{
  "direction": "bullish",
  "sentiment_llm": 35.5,
  "factor_weights": {"供给": 80, "需求": 20, "库存": 0, "成本": 0, "政策": 0, "天气": 0, "宏观": 0, "资金/结构": 0},
  "primary_factor": "供给",
  "summary": "巴西增产+国内库存累积，短期白糖承压",
  "reasoning": "近 7 天资讯显示…",
  "evidence": ["巴西中南部糖产量同比增加 8%", "广西部分糖厂开榨推迟"],
  "horizon": "short",
  "confidence": 0.75,
  "linkage_weight": 0.3
}"""


def _foreign_text(foreign: dict[str, dict]) -> str:
    if not foreign:
        return "暂无外盘报价（可能处于休市或数据源未更新）"
    return "、".join(
        f"{v['name']} {v['change_pct']:+.2f}%" for v in foreign.values()
    )


def _linkage_text(linkage: dict | None) -> str:
    if not linkage:
        return "该品种无外盘传导映射"
    parts = [
        f"{c['name']} {c['change_pct']:+.2f}% × 权重{c['weight']:.2f} → 贡献 {c['impact']:+.2f}"
        for c in linkage["contributors"]
    ]
    label = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}[linkage["direction"]]
    return (
        f"{'；'.join(parts)}\n"
        f"按权重合计：传导信号 {linkage['signal']:+.1f}（{label}）"
    )


def _build_user_prompt(variety: Variety, titles: list[str], analyses: list[Analysis],
                       linkage: dict | None = None,
                       foreign: dict[str, dict] | None = None,
                       quote: VarietyQuote | None = None) -> str:
    factors_desc = "、".join(
        f"{vf.factor.name} 权重{vf.weight:.1f}" for vf in variety.factors
    ) if variety.factors else "默认"
    rows = []
    for idx, (t, a) in enumerate(zip(titles, analyses), 1):
        rows.append(f"{idx}. 【{a.factor or '—'}】dir={a.direction or '—'} strength={a.strength or '—'} conf={a.confidence or '—'} | {t}")
    body = "\n".join(rows)
    if quote and quote.price > 0:
        quote_desc = (
            f"主力连续 {quote.price:.2f}，较昨结算 {quote.change_pct:+.2f}%，"
            f"持仓 {int(quote.open_interest or 0)} 手，成交 {int(quote.volume or 0)} 手"
        )
    else:
        quote_desc = "暂无盘面数据"
    return f"""【品种】{variety.code} {variety.name}
【品种专属因子权重（静态）】{factors_desc}
【今日盘面】{quote_desc}
【外盘行情】{_foreign_text(foreign or {})}
【外盘传导（经验权重）】
{_linkage_text(linkage)}

【资讯列表（近 {len(titles)} 条）】
{body}

请综合以上资讯与外盘传导，输出汇总研判 JSON。"""


async def _call_llm(system: str, user: str) -> tuple[dict, int, str]:
    """返回 (parsed_json, latency_ms, model)。未配置 key 或失败时抛异常。"""
    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    started = time.perf_counter()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 1400,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers=headers, json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    parsed = json.loads(raw)
    latency = int((time.perf_counter() - started) * 1000)
    return parsed, latency, data.get("model", settings.deepseek_model)


def _norm_summary(text: str, max_len: int = 80) -> str:
    text = (text or "").strip()
    if len(text) > max_len:
        text = text[:max_len - 1] + "…"
    return text


def _parse_safe(parsed: dict) -> dict:
    """把 LLM 返回的 JSON 规整成 DailySummary 字段能吃的结构。"""
    direction = parsed.get("direction", "neutral")
    if direction not in ("bullish", "bearish", "neutral"):
        direction = "neutral"
    try:
        sentiment_llm = float(parsed.get("sentiment_llm", 0))
        sentiment_llm = max(-100.0, min(100.0, sentiment_llm))
    except (TypeError, ValueError):
        sentiment_llm = 0.0
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    horizon = parsed.get("horizon", "short")
    if horizon not in ("intraday", "short", "medium", "long"):
        horizon = "short"
    factor_weights = {}
    for fname in FACTOR_NAMES:
        try:
            v = int(parsed.get("factor_weights", {}).get(fname, 0))
            factor_weights[fname] = max(0, min(100, v))
        except (TypeError, ValueError):
            factor_weights[fname] = 0
    # 只保留 >0 的
    factor_weights = {k: v for k, v in factor_weights.items() if v > 0}
    # AI 自己给出的外盘传导权重，持久化成一个伪因子，供前端展示
    try:
        linkage_weight = max(0.0, min(1.0, float(parsed.get("linkage_weight", 0))))
    except (TypeError, ValueError):
        linkage_weight = 0.0
    if linkage_weight > 0:
        factor_weights["外盘传导"] = round(linkage_weight * 100)
    evidence = []
    for t in parsed.get("evidence", [])[:3]:
        if isinstance(t, str) and t.strip():
            evidence.append(t.strip()[:120])
    return {
        "direction": direction,
        "sentiment_llm": round(sentiment_llm, 1),
        "confidence": round(confidence, 2),
        "horizon": horizon,
        "primary_factor": str(parsed.get("primary_factor", ""))[:32],
        "factor_weights": factor_weights,
        "summary": _norm_summary(str(parsed.get("summary", "")), 80),
        "reasoning": _norm_summary(str(parsed.get("reasoning", "")), 300),
        "evidence": evidence,
    }


def _apply_market_anchor(norm: dict, q: VarietyQuote | None,
                         linkage: dict | None = None) -> dict:
    """把当日盘面动量并入结论。

    大幅波动时提高盘面权重，避免资讯研判与当日行情明显相反：
      |涨跌| ≥3%   → 盘面 55%
      1.5%~3%     → 盘面 40%
      1%~1.5%     → 盘面 25%
      <1%         → 不干预，以资讯为主
    盘面情绪按 15 倍线性映射（5% 即接近极值）。
    """
    if not q or q.price <= 0:
        return norm
    pct = float(q.change_pct or 0.0)
    if abs(pct) < 1.0:
        return norm
    if abs(pct) >= 3.0:
        weight = 0.55
    elif abs(pct) >= 1.5:
        weight = 0.40
    else:
        weight = 0.25
    quote_sent = max(-100.0, min(100.0, pct * 15))
    base = float(norm.get("sentiment_llm") or 0.0)
    sent = round(max(-100.0, min(100.0, base * (1 - weight) + quote_sent * weight)), 1)
    old_dir = norm.get("direction")
    direction = "bullish" if sent > 12 else ("bearish" if sent < -12 else "neutral")

    summary = norm.get("summary") or ""
    tag = f"（今日盘面 {pct:+.2f}%）"
    if "今日盘面" not in summary:
        summary = f"{summary}{tag}"
    norm["summary"] = _norm_summary(summary, 100)

    reasoning = norm.get("reasoning") or ""
    note = f"叠加当日主力 {pct:+.2f}%，盘面权重 {int(weight * 100)}%。"
    if "盘面权重" not in reasoning:
        reasoning = (reasoning + note).strip()
    norm["reasoning"] = _norm_summary(reasoning, 300)

    weights = {k: v for k, v in (norm.get("factor_weights") or {}).items() if v}
    scaled = {k: round(v * (1 - weight)) for k, v in weights.items()}
    scaled = {k: v for k, v in scaled.items() if v > 0}
    scaled["盘面动量"] = round(weight * 100)
    norm["factor_weights"] = scaled

    conf = float(norm.get("confidence") or 0.5)
    if direction == old_dir:
        conf = min(1.0, conf + 0.08)
    else:
        conf = max(0.2, conf - 0.08)
    norm["confidence"] = round(conf, 2)
    norm["direction"] = direction
    norm["sentiment_llm"] = sent
    return norm


NO_DATA_SUMMARY = "暂无相关资讯，维持观望"


def _upsert(db, code: str, norm: dict, model: str, status: str, latency: int,
            err: str, article_count: int) -> DailySummary:
    local_date = date.today()
    row = db.execute(
        select(DailySummary).where(
            DailySummary.variety_code == code, DailySummary.date == local_date.isoformat()
        )
    ).scalar_one_or_none()
    if row is None:
        row = DailySummary(
            variety_code=code, date=local_date.isoformat(), model=model,
            status=status, article_count=article_count, latency_ms=latency, error=err,
            **norm,
        )
        db.add(row)
    else:
        row.model = model
        row.status = status
        row.article_count = article_count
        row.latency_ms = latency
        row.error = err
        row.created_at = utc_now()  # 复用为「最近研判时间」
        for k, v in norm.items():
            setattr(row, k, v)
    db.commit()
    return row


def _no_data_norm(days: int) -> dict:
    return {
        "direction": "neutral", "sentiment_llm": 0.0, "confidence": 0.15,
        "horizon": "short", "primary_factor": "",
        "factor_weights": {},
        "summary": NO_DATA_SUMMARY,
        "reasoning": f"近 {days} 天未采集到该品种相关资讯，按无信号处理。",
        "evidence": [],
    }


def _quote_norm(q: VarietyQuote, linkage: dict | None = None) -> dict:
    """无资讯时用主力合约涨跌 + 外盘传导给出可解释的方向，避免卡片空白。"""
    pct = q.change_pct or 0.0
    quote_sent = max(-100.0, min(100.0, pct * 20))
    sentiment = quote_sent
    factor_weights = {"资金/结构": 100}
    extra = ""
    if linkage:
        # 无资讯时外盘权重给 40%，盘面 60%
        sentiment = quote_sent * 0.6 + linkage["signal"] * 0.4
        sentiment = round(max(-100.0, min(100.0, sentiment)), 1)
        factor_weights = {"资金/结构": 60, "外盘传导": 40}
        extra = f"；外盘传导 {linkage['signal']:+.1f}（{linkage['summary']}）"
    else:
        sentiment = round(quote_sent, 1)
    direction = ("bullish" if sentiment > 12 else "bearish" if sentiment < -12
                 else "neutral")
    label = {"bullish": "偏多", "bearish": "偏空", "neutral": "震荡"}[direction]
    factor = "外盘传导" if linkage and abs(linkage["signal"]) > abs(quote_sent) else "资金/结构"
    return {
        "direction": direction,
        "sentiment_llm": sentiment,
        "confidence": 0.35,
        "horizon": "short",
        "primary_factor": factor,
        "factor_weights": factor_weights,
        "summary": f"无新增资讯，跟随盘面{label}（{pct:+.2f}%）" + (
            f"，外盘{linkage['summary'].split('→')[-1].strip()}" if linkage else ""),
        "reasoning": (f"该品种近期无相关资讯，依据主力连续合约最新 {q.price:.0f}"
                      f"（较昨结算 {pct:+.2f}%）。{extra}"),
        "evidence": [],
    }


async def summarize_variety(code: str, days: int = 7) -> DailySummary | None:
    """对单个品种做一次日度汇总研判，upsert 到 DailySummary。

    无相关资讯时也会写入一条 neutral 占位，保证 22 个品种全部有研判。
    """
    with SessionLocal() as db:
        variety = db.execute(select(Variety).where(Variety.code == code, Variety.is_active.is_(True))).scalar_one_or_none()
        if variety is None:
            return None
        # 外盘快照 + 该品种的传导结论（休市/源缺失时 linkage 可能为 None）
        foreign = foreign_latest(db)
        linkage = compute_linkage(code, foreign)
        q = db.execute(
            select(VarietyQuote).where(VarietyQuote.variety_code == code)
        ).scalars().first()
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        docs = db.execute(
            select(RawDoc).join(Score, Score.doc_id == RawDoc.id)
            .where(Score.variety_code == code, RawDoc.first_seen_at >= cutoff)
            .order_by(desc(Score.importance))
            .limit(40)
        ).scalars().all()
        if not docs:
            if q and q.price > 0:
                return _upsert(db, code, _quote_norm(q, linkage), "quote-only", "ok", 0, "", 0)
            return _upsert(db, code, _no_data_norm(days), "no-data", "ok", 0, "", 0)
        titles = []
        analyses = []
        for d in docs:
            a = db.execute(select(Analysis).where(Analysis.doc_id == d.id)).scalars().first()
            if a:
                titles.append(d.title)
                analyses.append(a)
        if not analyses:
            if q and q.price > 0:
                return _upsert(db, code, _quote_norm(q, linkage), "quote-only", "ok", 0, "", 0)
            return _upsert(db, code, _no_data_norm(days), "no-data", "ok", 0, "", 0)
        # 尝试 LLM 汇总（附外盘行情与传导关系，让 AI 自己分配传导权重）
        try:
            parsed, latency, model = await _call_llm(
                SYSTEM_PROMPT,
                _build_user_prompt(variety, titles, analyses, linkage, foreign, q),
            )
            norm = _parse_safe(parsed)
            status = "ok"
            err = ""
        except Exception as exc:  # noqa: BLE001
            # 回退：基于现有 Score 做规则汇总
            scores = db.execute(
                select(Score).where(Score.variety_code == code, Score.doc_id.in_([d.id for d in docs]))
            ).scalars().all()
            num = sum(s.score * s.importance for s in scores)
            den = sum(s.importance for s in scores)
            sent = (num / den * 100) if den else 0.0
            sent = round(max(-100.0, min(100.0, sent)), 1)
            # LLM 不可用时，用经验权重把外盘传导按 30% 并入
            if linkage:
                sent = round(max(-100.0, min(100.0, sent * 0.7 + linkage["signal"] * 0.3)), 1)
            bull = sum(1 for s in scores if s.direction == "bullish")
            bear = sum(1 for s in scores if s.direction == "bearish")
            factor_counts: dict[str, float] = {}
            for s in scores:
                w = abs(s.score)
                if w and s.factor:
                    factor_counts[s.factor] = factor_counts.get(s.factor, 0) + w
            norm = {
                "direction": "bullish" if sent > 15 else ("bearish" if sent < -15 else "neutral"),
                "sentiment_llm": sent,
                "confidence": round(min(1.0, 0.3 + len(scores) * 0.05), 2),
                "horizon": "short",
                "primary_factor": max(factor_counts, key=factor_counts.get) if factor_counts else "",
                "factor_weights": {k: round(v / max(factor_counts.values()) * 100) for k, v in factor_counts.items()} if factor_counts else {},
                "summary": f"规则汇总：近{days}天 bull {bull} / bear {bear}，情绪 {sent:+.1f}%",
                "reasoning": "",
                "evidence": [],
            }
            latency = 0
            model = "rule-fallback"
            status = "ok"
            err = str(exc)[:200]

        # 盘面动量校验：大幅波动时提高盘面权重，保证研判不与当日行情明显相反
        norm = _apply_market_anchor(norm, q, linkage)
        # upsert
        return _upsert(db, code, norm, model, status, latency, err, len(analyses))


async def refresh_quote_summaries(days: int = 7) -> int:
    """只刷新「近期无资讯」品种的盘面研判，不调用 LLM。"""
    with SessionLocal() as db:
        codes = [c for (c,) in db.execute(select(Variety.code).where(Variety.is_active.is_(True))).all()]
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    updated = 0
    for code in codes:
        with SessionLocal() as db:
            has_doc = db.execute(
                select(Score.id).join(RawDoc, Score.doc_id == RawDoc.id)
                .where(Score.variety_code == code, RawDoc.first_seen_at >= cutoff).limit(1)
            ).first()
        if has_doc:
            continue
        if await summarize_variety(code, days=days):
            updated += 1
    return updated


def _is_trading_time(now_cst: datetime) -> bool:
    if now_cst.weekday() >= 5:
        return False
    hm = now_cst.hour * 60 + now_cst.minute
    return (9 * 60 <= hm <= 11 * 60 + 30) or (13 * 60 + 30 <= hm <= 15 * 60) or (21 * 60 <= hm <= 23 * 60)


async def refresh_movers(threshold: float = 3.0, stale_min: int = 120, limit: int = 6) -> list[str]:
    """盘中大幅波动品种的研判刷新。

    只对 |涨跌| ≥ threshold 且结论已超过 stale_min 分钟的品种重跑 LLM，
    保证地缘/原油等突发冲击当天就反映到卡片上，同时控制调用成本。
    """
    now_cst = datetime.now(CST)
    if not _is_trading_time(now_cst):
        return []
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    candidates: list[tuple[float, str]] = []
    with SessionLocal() as db:
        quotes = db.execute(
            select(VarietyQuote).where(VarietyQuote.price > 0)
        ).scalars().all()
        for q in quotes:
            if abs(q.change_pct or 0.0) < threshold:
                continue
            ds = db.execute(
                select(DailySummary).where(DailySummary.variety_code == q.variety_code)
                .order_by(desc(DailySummary.created_at)).limit(1)
            ).scalar_one_or_none()
            if ds and ds.created_at and (now_utc - ds.created_at) < timedelta(minutes=stale_min):
                continue
            candidates.append((abs(q.change_pct or 0.0), q.variety_code))
    candidates.sort(reverse=True)
    codes = [code for _, code in candidates[:limit]]
    done: list[str] = []
    for code in codes:
        try:
            r = await summarize_variety(code)
            if r:
                done.append(code)
                print(f"[mover] {code} 刷新 {r.direction} {r.sentiment_llm:+.1f}")
        except Exception as exc:  # noqa: BLE001
            print(f"[mover] {code} 刷新失败：{exc}")
    return done


async def summarize_all_active(days: int = 7) -> list[str]:
    """对所有活跃品种跑一次汇总。失败不阻塞下一个。"""
    with SessionLocal() as db:
        codes = [c for (c,) in db.execute(select(Variety.code).where(Variety.is_active.is_(True))).all()]
    results = []
    for code in codes:
        try:
            r = await summarize_variety(code, days=days)
            if r:
                results.append(code)
                print(f"[daily-summary] {code} {r.direction} sent={r.sentiment_llm:+.1f}% n={r.article_count}")
            else:
                print(f"[daily-summary] {code} 跳过（无资讯）")
        except Exception as exc:  # noqa: BLE001
            print(f"[daily-summary] {code} 失败：{exc}")
    return results


def get_latest_summary(code: str) -> DailySummary | None:
    """取某品种最近一次（不论哪一天）的汇总，供 Dashboard 卡片展示。"""
    with SessionLocal() as db:
        return db.execute(
            select(DailySummary).where(DailySummary.variety_code == code)
            .order_by(desc(DailySummary.created_at)).limit(1)
        ).scalar_one_or_none()
