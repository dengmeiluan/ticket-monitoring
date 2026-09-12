# 启动机票监控（后台运行）
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$pidFile = Join-Path $root ".monitor.pid"
$logFile = Join-Path $root "logs\monitor.out.log"

# 检查是否已在运行
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($oldPid) {
        $proc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -like "python*") {
            Write-Host "监控已在运行，PID = $oldPid" -ForegroundColor Yellow
            Write-Host "如需重启，请先执行: .\stop.ps1"
            exit 1
        }
    }
    Remove-Item $pidFile -Force
}

# 确保日志目录存在
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# 后台启动 python main.py（无窗口）
$env:PYTHONIOENCODING = "utf-8"
$proc = Start-Process -FilePath "python" `
    -ArgumentList "main.py" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError "$logFile.err" `
    -PassThru

$proc.Id | Out-File -FilePath $pidFile -Encoding ascii

Write-Host "===== 机票监控已启动 =====" -ForegroundColor Green
Write-Host "PID:      $($proc.Id)"
Write-Host "标准输出: $logFile"
Write-Host "错误输出: $logFile.err"
Write-Host "应用日志: $root\logs\monitor.log"
Write-Host ""
Write-Host "查看实时日志:  Get-Content '$root\logs\monitor.log' -Wait -Tail 30"
Write-Host "停止监控:      .\stop.ps1"
