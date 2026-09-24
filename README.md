# ✈️ ticket-monitoring 机票监控

> 自托管的多渠道机票价格监控：五平台明细采集 → 钉钉图文推送 → 达标四层强提醒。
> 数据留在本机，配置全在网页，开源免费。

[![在线演示](https://img.shields.io/badge/🎪_在线演示-点开即玩-brightgreen)](https://dengmeiluan.github.io/ticket-monitoring/site/)
[![Release](https://img.shields.io/github/v/release/dengmeiluan/ticket-monitoring)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![CI](https://github.com/dengmeiluan/ticket-monitoring/actions/workflows/ci.yml/badge.svg)](https://github.com/dengmeiluan/ticket-monitoring/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](https://github.com/dengmeiluan/ticket-monitoring/releases)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**[🎪 点开即玩的在线演示](https://dengmeiluan.github.io/ticket-monitoring/site/)** · [English README](README_EN.md) · [下载 Windows 发行包](https://github.com/dengmeiluan/ticket-monitoring/releases)

```
❌ 全部未达标｜最近 上→乌 09/25 直飞差￥120
├─ #### ✈️ 上海→乌鲁木齐 09/25
│    > ⏱ 16:12 🎯真达标 🟩破线 🟨擦边 超线
│    直飞 **￥2470**　线￥1900　差￥570（30%）
│    东航MU5678 12:30→17:05
│    > 经西安 停2:15 ｜ 经济舱
│    🟦🟦🟦⬜⬜
│    > 💡 直飞超线 30%，继续观望
│    > 📉 近7天 直飞 ↓8% ｜ 中转 ↓3%
│    [价格走势折线图：●深绿=真达标 ○细绿=行情破线 ○琥珀=擦边 ▼红=达标回落]
├─ #### ✈️ 乌鲁木齐→上海 10/04（17:00 后出发）
│    （第二航线起依次同构：KPI 语义三行 + 趋势 + 建议）
└─ [多航线合并明细总表：价格标绿=达标 · 同班跨渠道比价（整链不截断）]
```

> 文案全行经手机行宽估宽守卫（≤20 全角，超宽逐级降级恒保价格/航班/判据）；
> 标题全 `####` 档、语义点分档主次分明（🎯真达标 🟩破线 🟨擦边，超线为默认态
> 不占语义点）；达标明细行附「打开渠道」一键跳转。达标时：标题变 🚨、
> 群里 @你的手机号、风暴连推、（可选）ntfy 手机弹窗+铃声穿透免打扰、
> （可选）阿里云电话/短信。

## 控制台一览

飞行签派风格的控制台设计语言：数字即主角（mono 等宽）、分区编号标签、hairline 分区。
主页是**子视图工作台**（概览 / 走势·日历 / 航班明细 / 渠道健康，一屏一会话），
配置页是**面板式设置台**（左侧分区切换，同屏只显一个分区，没有长滚动）。

![概览工作台（亮色）](docs/screenshots/console-light.png)

![走势与日历（暗色）](docs/screenshots/console-dark.png)

![面板式配置台](docs/screenshots/console-config.png)

![全局配置中心](docs/screenshots/console-globals.png)

<details>
<summary>更多截图：航班明细 / K线 / 推送预览 / 移动端</summary>

![航班明细](docs/screenshots/console-details.png)

![K线走势](docs/screenshots/console-kline.png)

![推送预览](docs/screenshots/console-preview.png)

<img src="docs/screenshots/console-mobile.png" width="380" alt="移动端">

</details>

### 键盘快捷键

| 键 | 作用 |
|---|---|
| `1` / `2` | 监控台 / 配置台 切换 |
| `3` / `4` / `5` / `6` | 直达 概览 / 走势 / 明细 / 健康 子视图 |
| `Ctrl/⌘ + S` | 配置页保存并热生效 |
| `R` | 立即扫描一轮（3 秒内再按一次确认，防手滑） |
| `/` | 聚焦明细搜索框 |
| `Esc` | 关闭弹层 / 收起同班比价展开行 |

## 特性矩阵

| 能力 | 说明 |
|---|---|
| 五渠道明细 | 去哪儿/飞猪/携程/同程/途牛，统一 schema（价格/航班号/时刻/中转/跨天/时长）；**逐渠道以 PC 版为准**（qunar PC 主路径+H5 兜底、飞猪 PC 直读），httpx 直连渠道零浏览器开销 |
| 多租户 | 多用户各自航线/阈值/钉钉群；同航线去重采集、查询错峰防限流 |
| 达标判定 | 直飞/中转独立阈值；中转须满足到达约束；出发时段窗口；只认当轮实时数据 |
| 聚合推送 | 多航线一轮一消息；**达标航线小节自动置顶**；**KPI 语义三行制**（价格加粗直达链接 / 航班正文 / 决策字段引用辅档）+ **语义点分档**（🎯真达标 🟩破线 🟨擦边，超线为默认态不占点）+ **💡 操作建议** + **📉 7 天趋势**；全行手机行宽估宽守卫（超宽逐级降级，恒保价格/航班/判据）；达标明细行「打开渠道」一键跳转；通道故障自动在文末警示（告警系统自身的故障必须被看见） |
| 同班比价 | 同一航班各渠道最低价并排，按「最大可省」排序 |
| 强提醒 | 钉钉 @手机号 + 风暴连推 + **Windows 右下角弹窗（点击看单条全量详情）** + ntfy 弹窗铃声 + 阿里云电话短信；2h/再降￥50 去抖 |
| **多日期监控** | 一条航线可盯多个出发日期（配置页日期片：直输 `10-08` 自动补年 / 回车 / 📅 日历），各日期独立采集、独立推送小节、独立走势与日历；**航线快速复制**一键克隆全部配置（新航线默认停用，改城市对再启用） |
| **出发时段挡位** | 不限/凌晨/上午/下午/晚间五挡一点即填，也可手输精确窗口；与明细页筛选同一套挡位语义 |
| 走势图 | 平滑曲线+渐变面积/**K线双模**（涨红跌绿、OHLC 悬停）；48h/7 天范围；最低点「哪天几点」标注；**达标点环四档**（●深绿=真达标 / ○细绿=行情破线 / ○琥珀=擦边 / ▼红=达标回落）与推送文案语义档、明细表 🔥、日历色面四方同语言；**点击数据点（或聚焦后按 Enter）直达该轮航线明细**——自动锁定航线与出发日期，与明细行 📈、日历格点击构成页内跳转图谱闭环 |
| 价格日历 | 近 14 天逐日直飞最低热力卡（**最低日绿框「▼ 最低」徽标，其余日 +￥差价副行**）+ **近 7 天洞察**（最低/日均/降价天数/距最低幅度） |
| 免打扰时段 | 跨零点窗口（如 23:00–07:00）：时段内省略行情心跳/风暴连推/电话短信，**达标主推与 ntfy 照发** |
| 推送历史 | 📨 每次发送自动存档（含成功/失败），控制台随时回看，可展开钉钉近似渲染全文 |
| 渠道健康 | 近 24h 逐轮成功/降级/失败/维护条纹 + 成功率，**点击格子看该轮日志** |
| **运行脉冲** | 每轮每渠道行数/耗时环形缓冲（**落盘持久化，重启不丢**）：概览条 4 格 mono 大数字 + 近 40 轮**堆叠脉冲柱**（红帽=有渠道失败），采集是否健康一眼可辨 |
| **子视图工作台** | 主页四个子视图（概览/走势·日历/明细/健康）一屏一会话，记忆上次所在视图；切换零 DOM 插拔（翻译/比价扩展免疫） |
| **中转衔接与行李直挂** | 每条航线可配**中转最短衔接分钟**（需托运建议 ≥90）与**仅认两段含免费托运的直挂班次**：不合规中转全链路豁免（达标/推送/概览/走势·日历/明细），明细页「🧳 直挂」视图一键只看直挂班次；推送总表衔接时长着色+「直挂」徽标 |
| **航线启停** | 每条航线一个启用/停用开关：停用保留全部配置（心理线/日期），调度/推送/明细全链路豁免，随时一键恢复——**暂停监控不再靠删除** |
| **面板式配置台** | 配置页左侧分区切换（渠道登录/用户与航线/全局参数），同屏只显一个分区，**告别长滚动** |
| **设置行范式** | 字段「说明居左、控件居右」的设置行布局，hairline 分行；分区头卡片化带**实时摘要**（钉钉状态/渠道数/航线数），折叠后摘要仍可读；达标行浅绿高亮 |
| **可视化对齐** | 网页走势与推送图表同一信息密度：X 轴日期时间刻度、跨天分隔线、**达标数据点旗标**、最低点标注；推送图浮动标签**矩形级相互避让**（白底块隔开，实测密集窗不叠字）；推送明细总表圆角白卡+分组色带+类别胶囊+**比价两行式行卡（整链零截断）** |
| **全局配置中心** | 调度（周期/扰动/端口/启动即扫）· 采集（无头/超时/错峰区间/调试/UA）**全量热载**；启动级配置（数据库/日志/浏览器资料）如实标注 ♻ 只读；每个通道一个「测试」按钮：钉钉/ntfy 用表单当前值实测，**Windows 弹窗一键真发** |
| **配置搜索/导入导出** | 🔍 字段级搜索（跨分区命中过滤）；📤 导出 / 📥 导入配置 JSON（含凭据本机自管）；保存前**脏改动计数** + 端口/日期/重复航线/超时校验；`Ctrl/⌘+S` 保存 |
| 推送预览 | 👁 本地渲染钉钉消息近似效果，改格式不用等自然轮 |
| 浏览器通知 | 🔔 达标桌面通知 + 提示音（按价去重） |
| **Windows 弹窗** | 达标右下角系统弹窗+提示音，**点击直达单条详情页**（/notify/{nid}，不必打开控制台）；钉钉推送同链路附「📲 完整详情」链接 |
| 明细表 | 筛选/排序/日期列/搜索/**达标行浅绿底+绿条**/擦边琥珀/同班比价展开/CSV 导出/每行直达下单页；**行尾 📈 一键跳该航线走势**（与 ↗ 外链成对，自动锚定航线与日期，页内跳转图谱双向闭环） |
| **配置全热加载** | 航线/阈值/推送/扫描周期/扰动/**端口原地切换**/无头模式/采集超时/错峰间隔/日报时刻/图床——保存即生效，**零重启** |
| 网页登录 | 🔐 配置页一键弹出各渠道登录窗口，点「我已登录完成」保存会话即生效，**免命令行** |
| 演示模式 | `python webui.py --demo` 零配置体验；在线演示站 = 静态烘焙同源页面 |
| 数据窗口 | 自动清理 14 天前明细；走势图回看 48h/7 天 |
| 可靠性 | 调度互斥锁、钉钉 -1 单发零重试、渠道失败可见、启动首轮节流；**用户跳转链接与爬虫主路径同源 CI 门禁**（渠道改版即测试红，杜绝点开死页）；**图挂文本兜底**（截图上传失败时 TOP5 明细自动承载全量信息，同价多渠道合并一行带渠道计数，信息不随图消失） |

## 快速开始（免装 Python）

1. 到 [Releases](https://github.com/dengmeiluan/ticket-monitoring/releases) 下载 `ticket-monitoring-win64.zip`（约 68MB）
2. 解压到任意目录，运行 `TicketMonitor\TicketMonitor.exe`
3. 浏览器打开 `http://127.0.0.1:8765` → ⚙️ 配置：
   - 航线（城市中文输入，50 城自动联想；可配多条，每条独立阈值/日期/出发时段）
   - 直飞心理价 / 中转心理价 / 中转最晚到达时刻
   - 钉钉机器人 Webhook + 加签密钥（[创建方法](#钉钉机器人配置)），点「🔔 测试推送」即验
4. 保存即热重载生效，监控开始

> 携程渠道需要登录态：控制台「⚙️ 配置 → 🔐 渠道登录」一键弹窗登录保存（或 `TicketMonitor.exe --login ctrip`）；其余四渠道开箱即用。

## 从源码运行

```bash
git clone https://github.com/dengmeiluan/ticket-monitoring.git
cd ticket-monitoring
pip install -r requirements.txt
playwright install chromium
python main.py            # 无 config.yaml 时生成空骨架并引导网页配置
```

本地控制台同样在 `http://127.0.0.1:8765`；偏好命令行问答式配置可跑中文向导 `python main.py --setup`；零配置体验演示数据：`python webui.py --demo`。

## 架构

```
main.py            编排：航线去重 → 渠道线程池并发采集 → 多用户聚合分发 → 四层强提醒
crawlers/          五渠道：qunar(浏览器DOM兜底) / ctrip / tongcheng(XHR拦截)
                   / fliggy(PC SSR直读) / tuniu(httpx逆向)
core/alerter.py    一轮一消息聚合推送；_digest_payload 纯构建器（控制台预览复用）
core/pulse.py      扫描脉冲记录器：每轮每渠道 行数/耗时 环形缓冲 → /api/pulse
core/health.py     渠道健康时间线（monitor.log 解析，维护态锁存）
core/demo.py       演示数据（真实 schema 临时库，确定性种子）
webui.py           内嵌单页控制台（纯标准库；子视图工作台+面板式配置；配置全热加载）
report.py          走势图/明细总表 PNG（Pillow）→ 图床
docs/              uitest 全功能自检 / screenshot 截图 / demo_build 静态站烘焙 / LESSONS
```

## 钉钉机器人配置

1. 钉钉群 → 群设置 → 智能群助手 → 添加机器人 → **自定义**（Webhook 接入）
2. 安全设置选 **加签**，复制密钥（SEC 开头）
3. 复制 Webhook 地址，填入配置页对应输入框，点「🔔 测试推送」验证

## 配置说明

全部配置在网页 ⚙️ 配置页完成，**保存即热生效（零重启）**：航线/阈值/出发时段、钉钉/Server酱微信/ntfy/阿里云通知/邮件（163/QQ 免费邮箱授权码，整页截图+推送图表全内嵌正文——收件端零外链加载，可配多通道与钉钉并联）、扫描周期与扰动、控制台端口（原地切换）、无头浏览器、采集超时/错峰间隔、每日日报时刻、图床。`config.yaml` 只是落盘格式；仅数据库/日志路径为启动级（见 `config.example.yaml`）。

## 常驻运行

仓库根自带三个 PowerShell 脚本：

```powershell
.\start.ps1    # 后台启动监控（PID 落 .monitor.pid，日志在 logs/）
.\status.ps1   # 查看进程/端口/最近一轮状态
.\stop.ps1     # 停止监控
```

开机自启：任务计划程序 → 创建基本任务 → 触发器选「登录时」→ 操作选启动 `start.ps1`（或 `schtasks /create /tn TicketMonitor /sc onlogon /tr "powershell -File D:\path\start.ps1"`）。

## 打包可执行文件

```bash
pip install pyinstaller
pyinstaller TicketMonitor.spec --noconfirm
# dist/TicketMonitor/ 即完整分发包（含 Playwright 运行时）
```

## 开发

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q   # 全量 868 项：五渠道解析单测（含占位守卫/透传透镜/聚合守卫等防呆钉）+ 推送链路演练 + 链接同源门禁 + 曲线-列表一致性 + 版本门禁
python docs/uitest.py             # 全功能 UI 自检（242 断言，自动拉起演示控制台，零 JS 错硬门禁）
python docs/screenshot.py         # README 截图再生成（先起演示服：python webui.py --demo --port 8799）
python docs/demo_build.py         # 重烘在线演示站（docs/site）
```

踩坑与解法沉淀见 [docs/LESSONS.md](docs/LESSONS.md)；提交贡献前请读 [CONTRIBUTING.md](CONTRIBUTING.md)（TDD 纪律与发版流程）。安全相关问题请走 [SECURITY.md](SECURITY.md) 的私密通道。

## FAQ

**Q：页面一直开着会很耗吗？**
A：轮询带签名缓存 + ETag/304——数据没变时服务端零重算、浏览器零下载；页面隐藏自动暂停轮询，切回立即补一次。

**Q：推送报 -1「系统繁忙」？**
A：钉钉网关的"幽灵送达"——报错但消息常已入群。策略为单发零重试，丢失由下轮心跳自然补（达标场景电话通道独立兜底）。

**Q：飞猪价格为什么比别家低几十到一百？**
A：飞猪 PC 端展示的是不含税裸价，其余渠道为含税价，属数据口径差异。系统对飞猪报价 **+100 元税垫后**参与达标判定（展示价不动，推送/明细标「税前」）——所以「飞猪价低于心理线却没达标」是正常口径，不是漏报。

**Q：想用中文问答生成第一份配置？**
A：`python main.py --setup`（发行包 `TicketMonitor.exe --setup`）。无 config.yaml 时直接启动会生成空骨架并引导到网页配置页，网页与向导二选一。

**Q：携程提示「本轮无数据渠道」？**
A：登录态过期，重跑一次 `--login ctrip` 扫码即可。

**Q：改配置要重启吗？**
A：不用。航线/阈值/通知/扫描周期/扰动/端口/无头/超时/错峰/日报时刻/图床全部保存即热生效；仅数据库/日志路径是启动级配置。

**Q：会泄露我的配置吗？**
A：凭据只存本机 `config.yaml`（gitignore 拦截）；演示模式/在线站均为合成数据，配置页不回读真实凭据。

## License

Apache-2.0（见 [LICENSE](LICENSE)）。仅供个人学习研究，请遵守各平台服务条款。
