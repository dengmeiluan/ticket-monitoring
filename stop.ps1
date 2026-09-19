# 停止机票监控
$ErrorActionPreference = "SilentlyContinue"

$root = $PSScriptRoot
$pidFile = Join-Path $root ".monitor.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "未找到 PID 文件，可能监控并未启动" -ForegroundColor Yellow
    # 兜底：搜索运行中的 main.py 进程
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*main.py*" }
    if ($procs) {
        Write-Host "发现可能的监控进程:" -ForegroundColor Yellow
        foreach ($p in $procs) {
            Write-Host "  PID=$($p.ProcessId)  CMD=$($p.CommandLine)"
        }
        $ans = Read-Host "全部强制结束？(y/N)"
        if ($ans -eq "y") {
            foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }
            Write-Host "已结束" -ForegroundColor Green
        }
    }
    exit 0
}

$pid_ = Get-Content $pidFile
$proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "正在停止监控 PID=$pid_ ..." -ForegroundColor Cyan
    Stop-Process -Id $pid_ -Force
    Start-Sleep -Milliseconds 500
    Write-Host "已停止" -ForegroundColor Green
} else {
    Write-Host "PID=$pid_ 进程不存在，可能已退出" -ForegroundColor Yellow
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
