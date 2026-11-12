#!/usr/bin/env bash
# 一键装机（Linux / macOS）：检查 Python → 建 .venv → 装依赖 → 装浏览器内核 → 自检补齐
# 用法：bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"

echo "===== 机票监控 · 一键装机 ====="

echo
echo "[1/5] 检查 Python 版本（需要 3.11+）"
"$PY" - <<'PY'
import sys
assert sys.version_info[:2] >= (3, 11), "需要 Python 3.11+，当前 %s" % sys.version
print("OK", sys.version.split()[0])
PY

echo
echo "[2/5] 创建虚拟环境 $VENV（已存在则复用，不污染系统 Python）"
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

echo
echo "[3/5] 安装 Python 依赖"
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install -r requirements.txt

echo
echo "[4/5] 安装浏览器内核（约 100–200MB，只需一次）"
"$VPY" -m playwright install chromium

echo
echo "[5/5] 自检并补齐（缺配置会从示例生成，缺目录会建）"
"$VPY" -m core.setup_check --fix

echo
echo "===== 装好了 ====="
echo "启用环境：  source $VENV/bin/activate"
echo "前台运行：  python main.py"
echo "后台运行：  bash start.sh   （停止：bash stop.sh）"
echo "打开界面：  运行后终端会打印 http://127.0.0.1:端口"
echo "环境体检：  python -m core.setup_check"
echo "App 渠道（可选）：仅 Windows + MuMu 支持；macOS/Linux 本机不适用，README「Android 模拟器」有完整前提。"
