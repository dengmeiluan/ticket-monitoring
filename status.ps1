# 查看监控状态
$ErrorActionPreference = "SilentlyContinue"

$root = $PSScriptRoot
$pidFile = Join-Path $root ".monitor.pid"

if (Test-Path $pidFile) {
    $pid_ = Get-Content $pidFile
    $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "监控运行中" -ForegroundColor Green
        Write-Host "  PID:      $pid_"
        Write-Host "  启动时间: $($proc.StartTime)"
        Write-Host "  运行时长: $((Get-Date) - $proc.StartTime)"
        Write-Host "  内存占用: $([math]::Round($proc.WorkingSet64/1MB,1)) MB"
    } else {
        Write-Host "PID 文件存在但进程已退出（异常结束）" -ForegroundColor Yellow
    }
} else {
    Write-Host "监控未启动" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "--- 最近 20 行日志 ---"
$log = Join-Path $root "logs\monitor.log"
if (Test-Path $log) {
    Get-Content $log -Tail 20 -Encoding utf8
} else {
    Write-Host "(无日志)" -ForegroundColor DarkGray
}

# --- Android 设备状态（仅当配置里启用了 App 渠道时检查）---
$cfgFile = Join-Path $root "config.yaml"
if (Test-Path $cfgFile) {
    $cfgText = Get-Content $cfgFile -Raw -Encoding utf8
    if ($cfgText -match "app_(zhixing|qunar|fliggy|ctrip|tongcheng)") {
        Write-Host ""
        Write-Host "--- Android 设备 ---"
        $py = Join-Path $root ".venv\Scripts\python.exe"
        if (-not (Test-Path $py)) { $py = "python" }
        try {
            & $py (Join-Path $root "main.py") --app-status
        } catch {
            Write-Host "  (设备状态查询失败；可运行 python scripts/setup_device.py 体检)" -ForegroundColor DarkGray
        }
    }
}
