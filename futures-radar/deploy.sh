#!/bin/bash
# 期货雷达 · 云服务器一键部署
# 用法：sudo bash deploy.sh
set -e

echo "============================================"
echo "  期货雷达 · 一键部署"
echo "============================================"

# 1. 安装 Docker（如果没有）
if ! command -v docker >/dev/null 2>&1; then
  echo "[1/5] 安装 Docker..."
  if command -v apt >/dev/null 2>&1; then
    apt update -qq
    apt install -y -qq docker.io docker-compose-plugin >/dev/null 2>&1 || {
      echo "apt 安装失败，尝试官方脚本..."
      curl -fsSL https://get.docker.com | sh
    }
  elif command -v yum >/dev/null 2>&1; then
    yum install -y docker docker-compose-plugin >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh
  else
    curl -fsSL https://get.docker.com | sh
  fi
  systemctl enable docker >/dev/null 2>&1
  systemctl start docker >/dev/null 2>&1
else
  echo "[1/5] Docker 已安装"
fi

# 2. 检查 docker compose
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "安装 docker-compose-plugin..."
  apt install -y docker-compose-plugin >/dev/null 2>&1 || true
  DC="docker compose"
fi

cd "$(dirname "$0")"

# 3. 读取 DeepSeek Key
if [ ! -f .env ]; then
  if [ -f backend/.env ]; then
    cp backend/.env .env
  else
    echo "DEEPSEEK_API_KEY=" > .env
  fi
fi
set -a; . ./.env 2>/dev/null || true; set +a

if [ -z "$DEEPSEEK_API_KEY" ]; then
  echo
  echo "[提示] 未检测到 DeepSeek Key，将运行免费规则模式。"
  echo "       如需大模型研判：编辑 .env 填 DEEPSEEK_API_KEY=sk-xxx 后重跑本脚本。"
fi

# 4. 开放防火墙 80 端口
echo "[4/5] 配置防火墙..."
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp >/dev/null 2>&1 || true
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=80/tcp >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi

# 5. 构建并启动
echo "[5/5] 构建镜像（首次约 3-5 分钟）..."
$DC build --quiet
$DC up -d

# 等待健康
echo
echo "等待服务启动..."
for i in $(seq 1 30); do
  sleep 2
  if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/health 2>/dev/null | grep -q 200; then
    break
  fi
done

PUBIP=$(curl -s --max-time 3 https://api.ipify.org 2>/dev/null || curl -s --max-time 3 http://ip.sb 2>/dev/null || echo "")

echo
echo "============================================"
echo "  部署完成"
echo "============================================"
echo
if [ -n "$PUBIP" ]; then
  echo "  访问地址:  http://${PUBIP}/"
else
  echo "  访问地址:  http://<你的服务器公网IP>/"
fi
echo
echo "  手机添加桌面："
echo "  1) 手机浏览器打开上面地址"
echo "  2) 菜单里选「添加到主屏幕」"
echo
echo "  常用命令:"
echo "   查看日志:  $DC logs -f"
echo "   重启服务:  $DC restart"
echo "   停止服务:  $DC down"
echo "   更新代码:  $DC up -d --build"
echo
echo "  注意：云厂商安全组需放行 80 端口（在控制台里设置）"
echo "============================================"
