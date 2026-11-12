# 一键装机（Windows）：检查 Python → 建 .venv → 装依赖 → 装浏览器内核 → 自检补齐
# 用法：powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Venv = Join-Path $PSScriptRoot ".venv"
$VPy = Join-Path $Venv "Scripts\python.exe"

Write-Host "===== 机票监控 · 一键装机 =====" -ForegroundColor Cyan

Write-Host "`n[1/5] 检查 Python 版本（需要 3.11+）" -ForegroundColor Yellow
python -c "import sys; assert sys.version_info[:2] >= (3, 11), '需要 Python 3.11+，当前 %s' % sys.version; print('OK', sys.version.split()[0])"

Write-Host "`n[2/5] 创建虚拟环境 .venv（已存在则复用，不污染系统 Python）" -ForegroundColor Yellow
if (-not (Test-Path $VPy)) {
    python -m venv $Venv
}

Write-Host "`n[3/5] 安装 Python 依赖" -ForegroundColor Yellow
& $VPy -m pip install --upgrade pip
& $VPy -m pip install -r requirements.txt

Write-Host "`n[4/5] 安装浏览器内核（约 100–200MB，只需一次）" -ForegroundColor Yellow
& $VPy -m playwright install chromium

Write-Host "`n[5/5] 自检并补齐（缺配置会从示例生成，缺目录会建）" -ForegroundColor Yellow
& $VPy -m core.setup_check --fix

Write-Host "`n===== 装好了 =====" -ForegroundColor Green
Write-Host "启用环境：  .\.venv\Scripts\Activate.ps1"
Write-Host "前台运行：  python main.py"
Write-Host "后台运行：  .\start.ps1   （停止：.\stop.ps1）"
Write-Host "打开界面：  运行后终端会打印 http://127.0.0.1:端口"
Write-Host "环境体检：  python -m core.setup_check"
Write-Host "App 渠道（可选，仅 Windows + MuMu）：按 README「Android 模拟器」三段体检；先 python -m core.setup_check"
