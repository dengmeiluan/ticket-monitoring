#!/usr/bin/env bash
# 停止机票监控（Linux / macOS）
# 优先按 .monitor.pid；锁文件丢失时用 pgrep 兜底，但**只杀**命令行含
# 本目录 main.py 的进程，避免误伤机器上其它 Python 任务。
set -euo pipefail
cd "$(dirname "$0")"

PID_FILE=".monitor.pid"
pid=""
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
fi

if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "已停止监控（PID $pid）"
  rm -f "$PID_FILE"
  exit 0
fi

rm -f "$PID_FILE"
self_dir="$(pwd)"
found="$(pgrep -f "$self_dir/main.py" || true)"
if [ -z "$found" ]; then
  echo "没有找到运行中的 main.py（可能未用 start.sh 启动）"
  exit 1
fi

echo "发现可能的监控进程："
echo "$found"
printf "全部结束？(y/N) "
read -r ans
if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
  # shellcheck disable=SC2086
  kill $found 2>/dev/null || true
  sleep 1
  echo "已发送停止信号；仍在运行的进程：$(pgrep -f "$self_dir/main.py" | tr '\n' ' ')"
else
  echo "已取消"
fi
