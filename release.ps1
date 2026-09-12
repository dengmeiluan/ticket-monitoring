# 一键发布：回归测试 → 打包 → 组 zip → commit/push → GitHub Release + 上传资产
# 用法：
#   .\release.ps1              自动递增补丁版本（v1.0.0 → v1.0.1）
#   .\release.ps1 v1.1.0       指定版本
param([string]$Version = "")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

# python 解析：候选逐个实测（-c pass 真跑通才算数）——
# 非交互会话 PATH 上的 python 可能是 Store 占位 stub 或失效 shim（假运行非零退出）
$PY = $null
$cands = @("python", "py", "python3") + @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe")
foreach ($cand in $cands) {
    if ($cand -match "WindowsApps") { continue }
    $exe = $cand
    if (-not (Test-Path $cand)) {
        $g = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $g) { continue }
        $exe = $g.Source
    }
    & $exe -c "pass" 2>$null
    if ($LASTEXITCODE -eq 0) { $PY = $exe; break }
}
if (-not $PY) { throw "未找到可用 python——请安装 Python 3 或加入 PATH" }
Write-Host "  python: $PY" -ForegroundColor DarkGray
# 控制台非 UTF-8 时测试打印 emoji/中文会 UnicodeEncodeError 假失败
$env:PYTHONIOENCODING = "utf-8"

# ---------- 1/6 回归测试 ----------
Write-Host "[1/6] 运行警报链路回归测试..." -ForegroundColor Cyan
& $PY tests\test_alert_path.py 2>&1 | Tee-Object -FilePath logs\_release_test.log
if ($LASTEXITCODE -ne 0) { throw "测试未通过（详见 logs\_release_test.log），中止发布" }

# ---------- 2/6 打包 ----------
Write-Host "[2/6] PyInstaller 打包（约 2 分钟）..." -ForegroundColor Cyan
& $PY -m PyInstaller TicketMonitor.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "打包失败" }

# ---------- 3/6 组分发 zip ----------
Write-Host "[3/6] 组装分发包..." -ForegroundColor Cyan
$pkgDir = Join-Path $root "dist_package\机票监控"
if (Test-Path $pkgDir) { Remove-Item $pkgDir -Recurse -Force }
New-Item -ItemType Directory -Path $pkgDir -Force | Out-Null
Copy-Item "dist\TicketMonitor\*" $pkgDir -Recurse

$readme = @"
【机票价格监控】使用说明
================================

一、快速开始
1. 解压整个文件夹到任意位置（勿删 _internal 目录）
2. 双击 TicketMonitor.exe（首次自动下载浏览器内核约 120MB，仅一次）
3. 浏览器打开 http://127.0.0.1:8765 → 切到「⚙️ 配置」页：
   - 航线：城市直接输中文（50 城联想），可加多条，每条独立
     日期 / 直飞心理价 / 中转心理价 / 中转最晚到达 / 出发时段窗口
   - 钉钉机器人：粘贴 Webhook + 加签密钥 + 手机号，
     点「🔔 测试推送」立即验证
   - 可选 ntfy 强提醒：手机装 ntfy App 订阅同名主题，
     达标时系统级弹窗+铃声+穿透免打扰
4. 「💾 保存并生效」即热重载开始监控（无需重启）

二、运行行为
- 默认每 30±5 分钟一轮：去哪儿 + 飞猪 + 同程 + 途牛（免登录），
  携程需登录态：本目录运行 TicketMonitor.exe --login ctrip 扫码一次
- 多条航线聚合为一条钉钉消息：每航线小节（方向+日期）+
  价格走势图 + 明细总表图 + 同班跨渠道比价 + 较上轮涨跌
- 达标：标题变 🚨、@你的手机号、风暴连推、ntfy 强提醒
- 关闭 exe 窗口 = 停止监控；每天 09:00 图文日报

三、修改配置
- 网页「⚙️ 配置」页随时改，保存即热生效（含扫描周期/端口/无头模式，
  端口原地切换零重启）；仅数据库/日志路径需改 config.yaml 后重启
- 或双击「重新配置.bat」重跑命令行向导

四、常见问题
- 推送里「本轮无数据渠道：携程」= 登录态过期，重跑 --login ctrip
- 页面打不开：确认 exe 在运行；端口被占改 config.yaml 的 web.port
"@
$readme | Out-File "$pkgDir\使用说明.txt" -Encoding utf8

$bat = @"
@echo off
chcp 65001 >nul
cd /d %~dp0
TicketMonitor.exe --setup
pause
"@
$bat | Out-File "$pkgDir\重新配置.bat" -Encoding ascii

$zip = Join-Path $root "dist_package\机票监控.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $pkgDir -DestinationPath $zip
Write-Host ("  zip: {0} MB" -f [math]::Round((Get-Item $zip).Length/1MB))

# ---------- 4/6 版本号 ----------
if (-not $Version) {
    $ErrorActionPreference = "Continue"
    git fetch --tags origin 2>$null | Out-Null
    $last = (git describe --tags --abbrev=0 2>$null | Select-Object -First 1)
    $ErrorActionPreference = "Stop"
    if (-not $last) { $Version = "v1.0.0" }
    else {
        $p = $last.TrimStart('v').Split('.')
        $p[2] = [int]$p[2] + 1
        $Version = 'v' + ($p -join '.')
    }
}
Write-Host "[4/6] 版本号: $Version" -ForegroundColor Cyan

# ---------- 4.5/6 版本号同步进 main.py ----------
$mv='__version__ = "'+$Version+'"'
(& $PY -c "import re;f='main.py';s=open(f,encoding='utf-8').read();open(f,'w',encoding='utf-8',newline='
').write(re.sub(r'__version__ = .*$', r'$mv', s, count=1))" ) 2>$null | Out-Null

# ---------- 5/6 commit + push ----------
$ErrorActionPreference = "Continue"
git add -A
git commit -m "release: $Version" 2>$null | Out-Null
git push origin main
if ($LASTEXITCODE -ne 0) { $ErrorActionPreference = "Stop"; throw "git push 失败" }
$ErrorActionPreference = "Stop"

# ---------- 6/6 GitHub Release ----------
Write-Host "[5/6] 创建 GitHub Release..." -ForegroundColor Cyan
$cred = "protocol=https`nhost=github.com`n`n" | git credential fill
$token = ($cred | Select-String '^password=(.+)$').Matches[0].Groups[1].Value

$notes = @"
### 下载
- ``ticket-monitoring-win64.zip``（Windows x64，约 67MB）：解压双击 ``TicketMonitor.exe``，
  打开 http://127.0.0.1:8765 网页完成配置（钉钉机器人 + 航线/心理价）
- 首次运行自动下载 Chromium 内核（约 120MB，仅一次）
- 携程渠道需登录态：``TicketMonitor.exe --login ctrip`` 扫码一次
- 可选 ntfy 达标强提醒：手机装 ntfy App 订阅配置的主题

### 本版亮点（v2.1.0）
- 🔥 **热加载补全到最后一环**：修复扫描器闭包捕获启动配置快照的问题——采集超时/错峰间隔/UA/调试目录、每日日报时刻、图床配置此前热保存后不生效，现全部即时生效（数据库/日志路径为唯一启动级配置）
- 👥 **多用户切换**：监控页顶部用户 pills，明细/走势/日历一键跟随所选用户
- ⚡ **控制台性能**：/api/state 按数据签名缓存（轮间零重算）、/api/health 按日志签名缓存（不再每 10s 解析 2MB 日志）、SQLite 批量写入
- 🎛 **配置页交互焕新**：钉钉开关改复选框、数字/时刻输入用原生控件、favicon、保存反馈自动淡出、测试推送附运行版本号（僵尸实例一眼鉴别）
- 🧰 **开源基建**：CONTRIBUTING/SECURITY/Issue 模板/PR 模板齐备；CI 升级（单测+推送链路+40 断言 UI 自检双 job）

### 功能
五渠道航班明细（去哪儿/飞猪/携程/同程/途牛）· 多航线聚合推送（一轮一消息）
价格走势图 + 明细总表 + 同班跨渠道比价 · 直飞/中转阈值 + 到达约束 + 出发时段窗口
达标 🚨@手机号 + 风暴连推 + 电话短信 · Web 配置全热加载 · 多用户多钉钉群

在线演示：https://dengmeiluan.github.io/ticket-monitoring/site/
从源码运行见 README。
"@
$bodyObj = @{ tag_name = $Version; target_commitish = "main"; name = $Version; body = $notes }
$body = [System.Text.Encoding]::UTF8.GetBytes(($bodyObj | ConvertTo-Json))
$hdr = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json" }
$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/dengmeiluan/ticket-monitoring/releases" `
    -Method Post -Headers $hdr -Body $body -ContentType "application/json; charset=utf-8"

Write-Host "[6/6] 上传 zip 资产（约 67MB）..." -ForegroundColor Cyan
$zipName = "ticket-monitoring-$Version-win64.zip"
Invoke-RestMethod -Uri "https://uploads.github.com/repos/dengmeiluan/ticket-monitoring/releases/$($rel.id)/assets?name=$zipName" `
    -Method Post -Headers @{ Authorization = "Bearer $token" } `
    -ContentType "application/zip" -InFile $zip | Out-Null

Write-Host ""
Write-Host "✅ 发布完成: $($rel.html_url)" -ForegroundColor Green
