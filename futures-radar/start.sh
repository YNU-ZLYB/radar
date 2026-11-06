#!/bin/bash
set -e
cd "$(dirname "$0")/backend" || exit 1

echo "============================================"
echo " 期货雷达 · 郑商所资讯研判平台"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 没有检测到 python3，请先安装 Python 3.10 或更高版本。"
  read -r -p "按回车退出..."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "[1/4] 首次运行，创建运行环境..."
  python3 -m venv .venv
fi

echo "[2/4] 检查依赖..."
.venv/bin/python -m pip install -q -r requirements.txt || { echo "[错误] 依赖安装失败"; read -r -p "按回车退出..."; exit 1; }

# 下载 cloudflared（如果没有）
CF_BIN="$(dirname "$0")/cloudflared"
if [ ! -f "$CF_BIN" ]; then
  echo "[3/4] 下载 Cloudflare Tunnel（公网访问，手机随时可用）..."
  OS=$(uname -s)
  ARCH=$(uname -m)
  case "$OS-$ARCH" in
    Darwin-x86_64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64" ;;
    Darwin-arm64)   CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64" ;;
    Linux-x86_64)   CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    Linux-aarch64)  CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    *) echo "[提示] 未知系统 $OS-$ARCH，跳过公网隧道。仅本机/局域网可用。" ;;
  esac
  if [ -n "$CF_URL" ]; then
    curl -sL --max-time 120 -o "$CF_BIN" "$CF_URL" && chmod +x "$CF_BIN" && echo "  cloudflared 下载完成" || echo "  下载失败，跳过公网隧道"
  fi
else
  echo "[3/4] cloudflared 已就绪"
fi

echo "[4/4] 启动服务..."
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/radar.log 2>&1 &
BACK_PID=$!
sleep 5

if ! kill -0 $BACK_PID 2>/dev/null; then
  echo "[错误] 后端启动失败，日志："
  tail -20 /tmp/radar.log
  read -r -p "按回车退出..."
  exit 1
fi

# 打开浏览器
if command -v open >/dev/null 2>&1; then
  (open http://127.0.0.1:8000 >/dev/null 2>&1 &)
elif command -v xdg-open >/dev/null 2>&1; then
  (xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 &)
fi

echo
echo "============================================"
echo "  期货雷达已启动"
echo "============================================"
echo
echo "  本机访问:  http://127.0.0.1:8000"

# 尝试局域网 IP（用 hostname -I 或 ifconfig）
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$LAN_IP" ]; then
  LAN_IP=$(ifconfig 2>/dev/null | grep "inet " | grep -v 127 | awk '{print $2}' | head -1)
fi
if [ -n "$LAN_IP" ]; then
  echo "  手机/Wi-Fi: http://${LAN_IP}:8000"
fi

# 启动 cloudflared tunnel（后台，15 秒后打印公网地址）
if [ -x "$CF_BIN" ]; then
  echo
  echo "--- 正在启动公网隧道（首次 10-20 秒） ---"
  "$CF_BIN" tunnel --url http://127.0.0.1:8000 --no-autoupdate > /tmp/cf.log 2>&1 &
  CF_PID=$!
  # 最多等 25 秒，轮询 hostname
  for i in $(seq 1 25); do
    sleep 1
    HOSTNAME=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" /tmp/cf.log 2>/dev/null | head -1)
    if [ -n "$HOSTNAME" ]; then
      echo "  手机/外网公网: $HOSTNAME"
      echo "  （此地址在本进程存活期间有效，重启会变）"
      break
    fi
  done
  if [ -z "$HOSTNAME" ]; then
    echo "  公网隧道启动超时。本机/局域网仍可用。"
  fi
fi

echo
echo "============================================"
echo "  关闭服务：关闭此终端或 Ctrl+C"
echo "  后端日志：tail -f /tmp/radar.log"
echo "  隧道日志：tail -f /tmp/cf.log"
echo "============================================"

# 等待后端退出，用户 Ctrl+C 时清理 cloudflared
trap "echo; echo '正在关闭...'; kill $BACK_PID $CF_PID 2>/dev/null; wait 2>/dev/null; echo '已关闭。'; exit 0" SIGINT SIGTERM

wait $BACK_PID
