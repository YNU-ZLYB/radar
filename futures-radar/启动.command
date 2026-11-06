#!/bin/bash
# macOS 用户双击此文件启动
cd "$(dirname "$0")"
chmod +x start.sh 2>/dev/null
exec ./start.sh
