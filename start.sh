#!/usr/bin/env bash
# 后台启动机票监控（Linux / macOS）
# 与 Windows 的 start.ps1 对称：写 .monitor.pid、日志落 logs/。
# 用法：bash start.sh            停止：bash stop.sh
set -euo pipefail
cd "$(dirname "$0")"

PID_FILE=".monitor.pid"
LOG_FILE="logs/monitor.out.log"

# 已经在跑就不再起第二份（单实例锁之外再加一层可读提示）
if [ -f "$PID_FILE" ]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    echo "监控已在运行，PID = $old"
    echo "如需重启，请先执行: bash stop.sh"
    exit 1
  fi
  rm -f "$PID_FILE"
fi

mkdir -p logs
PY="python3"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
PYTHONIOENCODING=utf-8 nohup "$PY" main.py >"$LOG_FILE" 2>"$LOG_FILE.err" &
echo $! >"$PID_FILE"

echo "===== 机票监控已启动 ====="
echo "PID:      $(cat "$PID_FILE")"
echo "标准输出: $LOG_FILE"
echo "错误输出: $LOG_FILE.err"
echo "应用日志: $PWD/logs/monitor.log"
echo ""
echo "查看实时日志:  tail -f '$PWD/logs/monitor.log'"
echo "停止监控:      bash stop.sh"
