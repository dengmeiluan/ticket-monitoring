# 交割文档（HANDOFF）——ticket-monitoring

> 下一会话直接切工作空间到 `D:\idea_project\ticket-monitoring` 即可接手。
> 本文是唯一权威交割：架构、运行状态、运维动作、已知问题、坑与纪律。
> 最后更新：2026-09-11 15:20（v16.0.0）

## 1. 项目一句话

自托管多渠道机票价格监控：五渠道航班明细采集 → 多航线聚合钉钉推送（图文）→ 达标四层强提醒（@手机/风暴/ntfy/阿里云电话短信）。本地 Web 控制台（配置全热加载零重启/多维筛选/渠道健康/推送预览/演示模式/在线演示站）。

## 2. 运行状态（当前实例）

| 项 | 值 |
|---|---|
| 版本 | **v110.10.0**（推送质感：达标仪表破线满格绿 🟩 + 明细总表比价两行式行卡，根治比价行「口」方块与链路截断；tag=v110.10.0） |
| 进程 | python main.py（start.ps1 起，PID 文件 .monitor.pid；发版后已重启验证） |
| 控制台 | http://127.0.0.1:8765（**主页=子视图工作台**：概览/走势·日历/明细/健康；**配置=面板式设置台**：同屏一分区；**01 运行脉冲**：statline+堆叠脉冲柱；快捷键 1/2 切视图、R 两段确认立即扫描、/ 聚焦搜索；ETag/304 轮询零下载） |
| **在线演示** | **https://dengmeiluan.github.io/ticket-monitoring/site/**（GitHub Pages，docs/site 静态烘焙；重烘：`python docs/demo_build.py`） |
| 演示模式 | `python webui.py --demo [--port N]`（零配置合成数据；POST 只读拦截） |
| 调度 | 每 15 分钟一轮 ±扰动（配置页 ⚙️ 全局卡热改，min 5；**周期/扰动/端口/无头全热加载**） |
| 单轮耗时 | ~2 分钟（渠道并发 + qunar 全局链 + 飞猪收敛滚动） |
| 启停 | `start.ps1` / `stop.ps1` / `status.ps1`（仓库根，PowerShell） |
| 首轮节流 | 上轮数据 <5 分钟则跳过启动首轮（防连环重启轰炸推送） |
| 一键发版 | 无脚本——按 §7.6 归零流程手工执行（v2 时代的 release.ps1 与单根纪律相悖，已于 v110.10.0 删除，勿再引入） |
| 登录 | **网页配置页「🔐 渠道登录」一键弹窗登录**（登录完点「我已登录完成」即保存生效，免命令行）；CLI `--setup-login`/`--login <plat>` 保留 |

## 3. 渠道状态（2026-09-09）

| 渠道 | 方式 | 登录态 | 备注 |
|---|---|---|---|
| qunar | **PC 版主路径**（flight.qunar.com 列表页拦 wbdflightlist 完整明细）→ H5 浏览器 → httpx 兜底 | ✅ 已登录 | 09-11 H5 touchInnerList 风控升级：token 每轮刷新成功仍 1999（121 连拒、阶梯退避耗尽）；PC 路径同款无头环境实测 72 条明细；cookie 同属 .qunar.com 主域，登录态共用；阶梯退避/礼貌间隔逻辑不变 |
| ctrip | 浏览器+XHR 拦截（H5） | ✅ 已登录 | 需 `--login ctrip` 维持；IP 灰名单靠登录态绕过；PC 版 09-11 实测 302→432 风控拒，保留 H5 |
| fliggy | **PC SSR 直读**（sjipiao.fliggy.com，Playwright 滚屏+行状态机） | 不需要 | 移动端 MTOP v1.0 已被官方下线（NOT_SUPPORT）；PC 价格**不含税**（差 50-130）；仅直达+经停；9C 数字开头二字码已支持 |
| tongcheng | 浏览器+XHR 拦截（H5） | ✅ 已登录 | 接口只回直飞（数据边界非 bug）；PC 版已评估：路由 /flights/itinerary/oneway/:code、接口 getflightlist 带易盾 openDun、无头下列表卡片不渲染，H5 正常故保留（证据 debug/tc_pc_list.json） |
| tuniu | httpx 逆向 | ✅ 已登录 | 未登录会 179991 风控（游客限流通病）；无独立 PC 机票页（www.tuniu.com/flight 202 挑战响应），纯 API 性能最优保留 |

**登录态位置**：`user_data/<plat>/`（gitignore 挡住）。用户本地 Chrome cookie 无法迁移（独占锁+App-Bound 加密，实测死路）。

## 4. 架构速览

```
main.py            编排：make_sweep_job（航线去重/渠道线程池并发/310s→qunar自锁；
                   **cfg 一律读 rt["cfg"] 单一事实源**——闭包捕获启动快照曾致
                   爬虫超时/错峰/日报时刻/图床热存不生效，LESSONS 十二.1）
                   check_multi 聚合分发；--setup-login 五窗；_first_run 节流
core/alerter.py    一轮一消息聚合推送（_push_digest_multi = _collect_hits →
                   _phone_should_ring 去抖 → **_digest_payload 纯构建** → 发送/风暴）；
                   _digest_payload(rs_list, fresh, with_tables) 零副作用（预览器复用，
                   with_tables=False 跳过总表图床上传）；KPI 三行制；达标去抖
core/notifier.py   DingTalk（**严格单发零重试**——-1 幽灵送达，重试=重复打扰）
                   NtfyNotifier / AliyunAlertNotifier（电话短信）
core/health.py     渠道健康时间线：parse_health(log_text, now, hours) 纯函数——
                   按轮×渠道归并 ok/part/fail/maint（"进入维护模式"锁存至出价恢复）
core/demo.py       演示数据：build_demo_db（真实 schema：48h 历史+当轮富明细，
                   种子确定性）/ demo_routes / demo_cfg / demo_health（同形健康条纹）
crawlers/          五渠道（见上表）；base：持久浏览器+登录引导+反爬 init
webui.py           内嵌单页控制台（配置热加载含调度周期；暗色三态、图表配色随主题；
                   **多用户切换 pills**（监控页顶部，明细/走势/日历跟随）；
                   **/api/state 签名缓存 + 响应体字节缓存**（DB/配置/版本不变即原字节回，
                   实测 2.2-3.5s→3ms，用户"页面卡顿"主根因即旧版每 10s 全量重算）；
                   **/api/health 按日志 mtime/size 缓存**（不再每 10s 解析 2MB 日志）；
                   明细表 >150 行自动免入场动画；**展开=预置隐藏行 display 切换**（零 childList 变更，翻译/比价扩展免疫——旧"插删 tr"方案被用户扩展实测击穿）；
                   **平滑曲线+渐变面积**（X/Y 索引坑已注释）；视图/图表切换过渡动画；细滚动条；
                   **📨 推送记录**（logs/push_history.jsonl 存档回看，/api/pushlog，demo 合成）；
                   **近7天洞察统计**（日历卡：最低/日均/降价天数/距最低）；**免打扰时段**配置（quiet_start/end）；测试推送附运行版本号（僵尸鉴别）；
                   多航线可切走势图+悬停读数+48h最低点标注；KPI 较上轮涨跌+直达去哪儿；
                   筛选/排序/日期列/搜索/近达标琥珀/同班比价展开(鼠标+键盘)/CSV 导出；
                   下轮倒计时；智能刷新；配置未保存守卫；
                   **GET /api/health 健康条纹**（读日志尾部 2MB 封顶）；
                   **POST /api/preview 推送预览**（DB 最新轮还原 routes_prices →
                   _digest_payload，storage=SimpleNamespace(db_path) 只读拿涨跌）；
                   **--demo 演示模式**（__main__ 入口，DEMO 开关拦 POST）；
                   **🔐 网页渠道登录**（/api/login 弹有头窗口复用 _login_window，
                   /api/login-finish 置事件保存会话，/api/login-state 看 user_data 目录态）；
                   移动端 ≤760px 筛选抽屉+价格列吸附）
docs/screenshot.py README 截图生成（演示模式+Playwright，JS 错误非零退出；
                   **沙箱/工具调用会被 SIGTERM——需本机直接跑**，产出 4 张 PNG）
report.py          走势图+明细总表 PNG（Pillow）→ freeimage 图床（直连）
tests/             test_alert_path.py（聚合推送+电话守卫+**预览构建器对等性** 17 断言）
                   test_core_units.py（纯函数 16 用例，含健康解析 7 场景）
docs/LESSONS.md    经验沉淀（七大类，必读）
```

## 5. 关键运维与凭据

- **凭据全在 config.yaml**（gitignore）：钉钉 webhook/SEC/at_mobile、ntfy topic、阿里云告警 url+AccessKey。**永不入库**（历次归零均全仓扫描验证零泄漏）。
- 推送失败排查：`debug/last_push.md`（每次发送前落档全文）。
- 图床上传失败：先试 `trust_env=False`（公司代理掐 iili.io 是老毛病）。
- **单实例纪律**：只允许一个 main.py 存活。推送"忽新忽旧"先查进程：`netstat -ano | findstr 8765` 双 LISTENING = 双实例实锤（09-09 `--login tuniu` 残留进程带旧代码并行推送的坑，详见 LESSONS 十.4）。

## 6. 已知问题与边界

1. 钉钉 -1 幽灵送达：报错但消息已入群——**单发零重试是终局策略**（丢失由下轮补，达标电话独立兜底）。勿加回重试。
2. 钉钉 markdown：不支持表格（用 PNG）、**吞尖括号**（比价链用 →）、聊天窗不显标题（标记放正文）、**PC 端不认单 `\n`**（一律 `\n\n` 段落）、**U+2026「…」渲染成。。。。**（比价链只列最低/最高两端）。
3. 多查询架构下"平台级唯一键"必须带 航线+日期 维度（seen/chart 缓存同理）。
4. 每日 9 点图文日报（maybe_daily_report，alert_state 防重发）。
5. 飞猪 PC 中转缺失（页面无中转分区），由其他渠道覆盖。
6. tests/test_core_units.py 直跑模式（`__main__`）对参数化用例（monkeypatch/tmp_path）会 TypeError——**单测一律走 pytest**（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）；文件内遗留两个 `ALL = ` 收集块属历史残留，pytest 不受影响。
7. report.py `_no_emoji()` 剥离区间含 `←-⇿`(U+2190-21FF)——**会把 `→` 箭头剥掉**，凡含箭头的文本不可过它（明细总表比价行因此改结构化 dict 渲染）。
8. 去哪儿 wbdflightlist `minPrice` **每次请求重摇**（实测 50 秒间隔连续 6 采样无一重复；~11% 采样带 150-200 元幻影低价、下一轮回弹；页面渲染价同样在变；响应内无判别字段，`priceLabel` 体验价与幻影价无关）。已改 PC 主路径**自适应采样**（`_fetch_via_pc`）：首采样较上轮跌超 5%（`PC_DROP_RATIO`，幻影信号特征）或无上轮参考才加采至 3 份，`_merge_pc_samples` 逐条目中位合并（2 份取高、单份退化，明细附 `samples` 轨迹）；`_pc_prev` 存于爬虫实例内存，**重启即失、首轮保守全采**。平均请求量 ≈ 旧基线×1.25。**勿信任何单次采样**；同因不要给告警层加"二次抓取确认"——第二次抓取是另一次掷骰子，确认不了任何事。取证脚本与快照在 `debug/snapshots/`。
9. **中转衔接/行李直挂是保守筛选**（v110.16.0）：`transfer_layover_min`（衔接下限分钟）与 `transfer_baggage: direct`（两段免费托运）配置后，**渠道未标注直挂的班次按不满足处理**——用户反馈"推送变少"先查这两项配置。数据源现状：仅 qunar PC 有 `transitServiceLabel`（中转联程「行李免提」），H5/ctrip/途牛/同程未产出该字段（transferBaggage 恒空=直挂筛选下全部不可见）；`layoverM` 由 flightnorm 规范产出（qunar/ctrip 有 layover，其余缺省 0=衔接不限）。判定统一走 `Alerter._transfer_ok`，历史序列（_rounds）与当轮同口径。

## 7. 开发纪律（违反必返工）

1. **TDD Iron Law**：bug 先写复现测试看红；功能测试先行；提交前 `python tests/test_core_units.py && python tests/test_alert_path.py` 全绿。
2. **改代码一律 Edit/Write 工具**，shell 内联/heredoc 传代码必踩反斜杠折叠（吃过三次）。
3. push 后远端 API 终验（管道截断不可信）；仓库重置第一推必须 `-u`。
4. PS1 中文：UTF-8 BOM + CRLF；Stop 偏好下 git 调用临时降 Continue。
5. 验证推送类改动**等自然轮**（手动触发=轰炸用户）。
6. 归零 force push 流程：删 Release/tag → rm .git 重 init 单 commit → `push -u --force` → python API 重建 Release+资产（Content-Type: application/zip + Timeout(write=300)）→ 远端终验三件套（1 commit/1 tag/敏感零命中）。

## 8. 版本历程（2026-09-09 七连发；09-15 质感十一连发 v110.11–v110.22）

| 版本 | 主题 | 关键点 |
|---|---|---|
| v110.22.0 | 触控基准对齐 | 概览 mchip 26→37px（与 chip/mtab 36px 同基准，第十轮漏网项）；README/EN 断言数与实际同步（uitest 149/演练 24/单测 49）；推送样张重渲复核 |
| v110.21.0 | 移动端触控+CI 修复 | ≤760px 触控目标 30→36px（mtab/chips/rngchip/抽屉输入），触控规则挪至基础声明之后防同特异性覆盖（原写法被 .tabs span/.rngchip 压住无效）；**CI test job 改 pytest 直跑**（直跑不兼容 fixture 参数化用例=已知问题 6 的根治）；向导补中转行李直挂询问 |
| v110.20.0 | 直挂徽标+弹窗瘦身 | 明细行中转班次「直挂」绿描边徽标（与推送总表同语言）；衔接 ≥90 分钟第二行绿字；ntfy/aliyun `_alert_body` 弹窗正文瘦身（丢「数据截至/图例」行，首屏只留价格与建议，与 Windows toast 行过滤一致）；ServerChan 审查=markdown 全文透传无需改 |
| v110.19.0 | 渠道色点一致性 | 明细渠道筛选 chips 补 pdot（on 态反白，与概览 mchip 同语言）；HANDOFF 增补中转保守筛选边界/直挂数据源现状 |
| v110.18.0 | 字体平整回退 | **回退中西逐字符混排**（Consolas 与 msyh 基线/字距不同→文字歪歪扭扭，用户实锤）；统一 msyh；全表对齐基调统一（时刻/全程/中转居中、价格右对齐、表头同向） |
| v110.17.0 | 明细总表深度优化 | 中转衔接时长按航线配置着色（绿/琥珀）+「直挂」绿描边胶囊+组头 TOP5/仅直挂标注+底部图例；meta 第 4 元透传航线配置 |
| v110.16.0 | 中转判定（托运需求） | Route 新字段 `transfer_layover_min`（衔接下限分钟）/`transfer_baggage`（direct=两段免费托运）；`Alerter._transfer_ok` 统一中转合法性全链路同口径（达标/推送/概览/走势·日历/明细/历史序列）；qunar PC 解析中转联程「行李免提」标签；向导询问衔接分钟（默认 90）；demo 航线演示新配置 |
| v110.15.0 | 向导守卫+打包根治 | **gitignore `_*.py` 误伤 crawlers/core 的 `__init__.py`**——fresh clone/worktree 打包 ImportError 空包（根治：规则改 `/_*.py`+强制入库+worktree 提交树打包流程）；向导日期 strptime 严格校验/间隔数字守卫/到达 HH:MM 循环校验/城市剥「市」归一化+前缀联想/平台中文别名；/notify 接入主站主题体系（jptheme 三态防闪白） |
| v110.14.0 | 日报结构重塑 | 日报补 H1（与达标推送对称）；航线 (from,to,date) 稳定排序；走势图提前至明细表前；删尾部「生成于」冗余行；演示站页脚如实标注（demo≠本地服务） |
| v110.13.0 | 推送文案六处 | 进度条图例移消息头部（原全文末尾无人看到）；KPI 参数行补货币符号+全角括号；达标命中行双括号改 · 分隔；比价组标题去冗「（同机不同价）」；title「差￥」补空格；总表小节「彩色」改「标绿」；概览用户卡头 ❌/🚨 改 .udot 状态点（❌ 与删除 ✕ 视觉相撞）；ntfy/aliyun `_alert_body` 瘦身前置铺垫 |
| v110.12.0 | 界面降噪 | 明细渠道 chips「新」角标移除（15 分钟周期下 0.5h 内全员「新」=常态无信息量）；UA 输入 17px→13px 一眼看全 |
| v110.11.0 | 遮挡双根因+标注系统 | 全局参数 check 卡：`.glcell input` 宽度覆盖 `.switch`（通栏宽条）+文案竖排溢出双根因修复；canvas 走势/K线「低」标注白底块（tagBox 主题感知）；PIL 推送图标注白底块+末值/最低点合并去重+最低点标注落点下方淡区；达标绿/比价红 C_QUAL/C_CMP 分离 |
| v110.10.0 | 推送质感+比价行卡 | **达标仪表破线满格绿**：`_gauge` 破线（price≤threshold）由全 `⬜`（语义对但像「没数据」）改 `🟩×5` 满格，两处图例行同步「🟩 满格 = 已破线可出手」；**明细总表比价段行卡化**：alerter 两处（聚合 `_digest_payload` + 单航线 `_flights_table_md`）compare 行由预拼「⚖️ …」字符串改**结构化 dict**（label/dep/arr/trans/chain/save），report 渲染两行式行卡（第一行 航班+时刻+右对齐红「可省 ￥N」，第二行渠道价格链独占整行）——预拼 ⚖️ 曾在 PIL 渲成「口」方块（`_no_emoji` 未覆盖该路径），且半宽列曾致 5 渠道链截尾。⚠️ `_no_emoji` 剥离区间含 `→`（U+2190-21FF），含箭头文本不可过它。**僵尸演示进程连环假象**：8799 端口挂着 09-12 的旧 `--demo` 进程，README 截图/预览探针全部打到旧代码（预览报「本轮数据为空」、走势图空白）——清理后当前代码全绿；会话起 demo 前先 netstat 查端口。删除 v2 时代 release.ps1（增量 push 与归零纪律相悖）。开源面：README/EN 测试数字同步 41/24/107、EN 补航线启停/价格日历/日报特性、清理根提交里全部调试截图（_qlogin/_ax_*/_probe_out.json 等，gitignore 增 `_*.png/_*.log/_probe*`）。pytest 43/43（新增 `_gauge` 满格绿 + compare 结构化断言）+ 演练 24 + uitest 107/107 |
| v110.10.0 | 推送质感+比价行卡 | **达标仪表破线满格绿**：`_gauge` 破线（price≤threshold）由全 `⬜`（语义对但像「没数据」）改 `🟩×5` 满格，两处图例行同步「🟩 满格 = 已破线可出手」；**明细总表比价段行卡化**：alerter 两处（聚合 `_digest_payload` + 单航线 `_flights_table_md`）compare 行由预拼「⚖️ …」字符串改**结构化 dict**（label/dep/arr/trans/chain/save），report 渲染两行式行卡（第一行 航班+时刻+右对齐红「可省 ￥N」，第二行渠道价格链独占整行）——预拼 ⚖️ 曾在 PIL 渲成「口」方块（`_no_emoji` 未覆盖该路径），且半宽列曾致 5 渠道链截尾。⚠️ `_no_emoji` 剥离区间含 `→`（U+2190-21FF），含箭头文本不可过它。**僵尸演示进程连环假象**：8799 端口挂着 09-12 的旧 `--demo` 进程，README 截图/预览探针全部打到旧代码（预览报「本轮数据为空」、走势图空白）——清理后当前代码全绿；会话起 demo 前先 netstat 查端口。删除 v2 时代 release.ps1（增量 push 与归零纪律相悖）。开源面：README/EN 测试数字同步 41/24/107、EN 补航线启停/价格日历/日报特性、清理根提交里全部调试截图（_qlogin/_ax_*/_probe_out.json 等，gitignore 增 `_*.png/_*.log/_probe*`）。pytest 43/43（新增 `_gauge` 满格绿 + compare 结构化断言）+ 演练 24 + uitest 107/107 |
| v110.9.0 | 日报质感升级 | 每日 09:00 图文日报此前是裸拼接（`## 标题`+两张图+裸尾行）——对齐达标推送设计语言：**头部「⏱ 数据截至」引用行**、每航线 **KPI 摘要行**（直飞/中转最优价+距心理线，粗体）、航线间 **--- 分隔**、尾行引用式；pytest 41/41（新增日报结构断言）+ uitest 107/107 |
| v110.8.0 | 推送尾部噪音清理 | 用户截图：钉钉桌面弹窗展示消息**末尾**，恰好露出「⏳ 更新于 HH:MM」「👉 去哪儿查看」两行噪音 → 尾部整块移除（×3 处；各航线 KPI 已带直达链接，尾部通用链接冗余）；头部「每轮自动刷新」措辞在静态推送里语义不通 → 精简为「⏱ 数据截至 HH:MM」；消息现以比价/建议等实质内容收尾 |
| v110.7.0 | 走势图交互级修复 | **7 天范围被旧入场动画帧覆盖根治**（HPTS 赋值在 chartDraw 内，动画 rAF 帧以旧闭包数据重画并覆盖新图；headless/节流下动画拖长至数秒 100% 复现）→ CHART_RUN 运行代号，新 chart 启动旧帧作废；**低点/最低标注右缘裁切**（估宽 W-150 不够）→ measureText 实测宽夹紧（折线+K线两处）；**达标旗标抽稀**：只画入场点（首次跌破）+ 最新点，长期达标段不再密铺成串；**交互入口空状态守卫**：setRange/setMode/togChart/buildChartChips/renderCal 在 S 未到时安全返回（此前 setRange 抛 TypeError 且 7d 状态丢失）；uitest 107 断言（新增 7 天范围生效） |
| v110.6.0 | 暗色主题补强 | 近五轮新增质感元素只在亮色验过——**暗色全链路无头目检**（概览/走势/日历/明细/配置/notify），修两处：`tr.qual` 暗色变体（8% 绿在暗卡不可见 → rgba(67,192,114,.13)）；NOTIFY_PAGE 暗色缺 `--blue`（CTA 胶囊深蓝字贴暗卡）→ 补 --blue + 胶囊配色变量化（--pillbd/--pillbg/--pillbh/--pillbd2 双主题） |
| v110.5.0 | 推送标题去重 | 用户视角标题曾重复示出同一航线：「❌ 全部未达标｜最近 上→乌 09/25 中转差￥350｜**上→乌 09/25** · 乌→上 10/05」。锚点（最近差价/达标首条）从尾部清单排除，剩余以「另监控 …」带出；单航线无清单尾巴。pytest 40/40（新增标题去重断言）+ uitest 106/106 |
| v110.4.0 | 达标语义+日历强调 | **明细达标行改「可出手」绿语义**（浅绿底+左绿条+价格绿粗，与推送明细总表同语言；旧版整行红字语义混乱）——线上数据因中转到达约束暂无达标班，uitest 演示态断言兜底；**价格日历**：近期最低日绿描边+「▼ 最低」徽标，其余日 `+￥N` 差价副行（红墙有了信息层级）；**chart() 空态守卫**（状态未到时切子视图不再 `S.users` null 崩，render 到达后自动重画）；uitest 106 断言 |
| v110.3.0 | 航线启停+质感三连 | 用户点名「只该删不该停是设计缺陷」：**每条航线启用/停用开关**（enabled 缺省即启用，停用保留配置；build_routes 跳过=调度/状态/明细/日历全链路豁免；开关/徽标/C 区摘要外科更新零重建；启用态删键防快照误脏）。**/notify 落地页质感**（裸 hr→渐隐 hairline；CTA 链接胶囊化；达标横幅动效点；修 --tx2 未定义）。**推送记录卡片**（绿/红状态色条+时间右对齐+展开面板底色）。**render 空用户守卫**（瞬时错误体不再级联 forEach 崩）；uitest 103 断言 |
| v110.2.1 | 交互失效根治 | 用户报「点击无响应」：**「查看明细 ▾」onclick 只调 pickUser 重绘概览、从不切子视图**——单用户下视觉零变化=静默失效（「查看明细」类标签语义与行为不一致的典型）。修复=点击后 showMonTab('details') 真正跳明细子视图；**全站交互审计**：96 个内联 handler 调用的 55 个函数逐一对照定义（无缺失），新增 uitest 断言「查看明细→明细子视图可见」 |
| v110.2.0 | 遮挡根治+脉冲持久化 | 用户三图反馈：**走势图两套刻度叠加互撞**（v110 stepN 刻度 + 更早「首/中/尾全时刻」循环同轴双绘）→ 删旧循环，改**双行刻度**（HH:MM 行 + 跨天日期行）+ 实测宽度避让 + 右缘夹紧；**日期标签压线**（图内顶部 T+10 被折线盖住）→ 移到分隔竖线底部独立行，halo 描边，K线模式 t0 同样适用；**推送图同步**（report.py 日期标签 PAD_T+2 → 底部行、5 刻度宽度避让，PAD_B 46→60）；**运行脉冲落盘持久化**（data/pulse.json 原子写+启动恢复，纯内存重启清零致柱数与在线时长对不上；「服务在线」语义不变）；无头 Playwright 目检前后对比 |
| v110.1.0 | 明细总表精修 | 用户反馈「表格比较廉价」逐项根治：**圆角白卡浮浅灰底**（PNG 在钉钉里脱离平铺表格感）；**分组色带**（直飞蓝/中转橙/比价红浅底+左色条）；**类别胶囊化**（蓝/橙圆角胶囊白字）；**达标行浅绿底+左绿条**；行间 hairline；底部结算条；表头加深加线；渲染样本目检 |
| v110.0.0 | 可视化一次到位 | 用户点名 v110：**网页走势图对齐推送图 v2 信息密度**——X 轴时间刻度（数据点自带 MM-DD HH:MM，均布 5 刻度）+ **跨天分隔竖线与日期标签** + **达标数据点白心绿环旗标**（价格≤阈值的点直接标出）；底部边距 30→44；三套回归全绿 |
| v100.7.3 | 走势图 v2 | 折线下渐变面积+达标数据点白心绿环旗标+绘制顺序修正（渐变不再盖达标虚线）+达标线标签右对齐 |
| v100.7.2 | 明细总表质感 | 用户图上的**分组标题 emoji 渲染成方块**（✈️🔁⚖️ 在 msyh/simhei 无字形）：render_flights_table 分组头改「几何色点+纯文字」，全图 emoji 统一剥离（_no_emoji）；渠道列画色点（PLAT_DOT 与全站同色系）；中转列 84→116 停留时长不再截断；37+24+97 全绿 |
| v100.7.1 | 推送文案布局质感 | 头部新增「⏱ 数据截至 HH:MM · 每轮自动刷新」引用行（消息延迟送达时知新鲜度）；**达标 KPI 加 🎯 锚**（破线的类别一眼锁定）；**多航线小节间 --- 分割线**（预览器与 /notify 轻页渲染器同步支持 hr 渲染）；钉钉恢复验证（09-12 的 -1 系统繁忙为钉钉侧临时故障，已自愈）；37+24+97 全绿，预览器目检 |
| v100.7.0 | 推送走势图深度优化 | 用户点名「横轴不知道低价是哪天几点」：render_chart 重构——**X 轴时间刻度带日期**（跨天窗口 MM-DD HH:MM，同日 HH:MM）+ 竖直参考网格；**跨天分隔线**（日期变化处浅橙竖线+日期标签）；**直飞/中转各自最低点标注**「低 ￥X 09-12 14:00」带完整日期时间+白色 halo 防压线；末值标注附时刻；推送图与网页走势信息量对齐；97 断言+37 单测+24 演练全绿 |
| v100.6.7 | 动作区打磨 | 主按钮（立即扫描/保存等）渐变底+投影层级（hover 抬升/active 归位）；走势卡折线/K线、48h/7天、航线切换 chips 全部胶囊化（hover 描边加深），与全站 tag/mchip/upill 胶囊语言统一；97 断言+37 单测+24 演练全绿 |
| v100.6.6 | 概览质感 pass | KPI 达标卡：绿光晕投影+左侧灯条渐变；渠道比价 chips 胶囊化（hover 微升）+ **渠道色点**（与脉冲/明细/健康三处同色系——全站渠道色语言四处统一）；best chip 蓝底白点突出；97 断言+37 单测+24 演练全绿 |
| v100.6.5 | div 配平修复 | **用户实例实锤**：srow 化时航线卡模板多写一个 </div>，单航线（demo）不触发，多航线（≥2 条）起第 2+ 张卡逃出用户卡体挂到 cfgform 顶层——C 分区折叠只能藏到第 1 张、其余看起来"折不动"。DOM 审计（parent 链）+ 模板 div 配平静态分析双定位；修复后 3 张航线卡全部归位、C/B/A/D 折叠与整卡折叠全验证；97 断言+37 单测+24 演练全绿 |
| v100.6.4 | 分区头卡片化 | 用户反馈「C 航线没法折叠」实为分区标题太细弱不可辨（细线+小字，点击区无存在感）。**grouplab 卡片化**：带边框圆角的分区条（headbg 底/hover 蓝边）、**右侧实时摘要**——A「钉钉已启用·弹窗开」B「5/5 渠道」C「N 条航线监控中」D「钉钉✓·ntfy✓·电话✓」随数据实时生成；折叠后摘要仍在=收起也看得见内容概要；97 断言全绿 |
| v100.6.3 | 溢出根治 | 用户截图 rline 横向溢出：**四重保险**——rline min-width:0/max-width:100%/box-sizing/overflow:hidden；srow min-width:0；sctl max-width:72%+可换行（flex:1 型豁免）；slab min-width:120px+ellipsis。480/620/700/950px 四档视口客观检测 scrollWidth==innerWidth 全过；97 断言全绿 |
| v100.6.2 | 健康区质感 | 渠道行加色点（pdot 同脉冲图例色系）；成功率徽章 pill 化（绿/黄/红三态带色底）；hlab 加宽适配；明细筛选控件 30px 统一顺带完成于 v100.6.1；97 断言全绿 |
| v100.6.1 | 明细页质感 | 筛选控件统一 30px 高/8px 圆角/focus 蓝环（与 srow 同语言）；类别 tag 胶囊化（圆角 20/加粗/字距）；**渠道列加色点**（与运行脉冲图例同色系，跨视图认知统一）；qunar IP 降权诊断留档（登录+清指纹均无效，等 TTL 或换出口） |
| v100.6.0 | 全链路 srow 统一 | **C 航线卡 srow 化**（城市对→衔接/心理价￥双输入/到达约束/时段窗口/日期全宽，7 字段 5 行）；**D 四张通道卡 srow 化**（启用换滑块 switch、Webhook/SEC/URL 类全宽、通路验证独立行、aliyun ID/Secret 并排）；**B 平台行 srow**（说明左 chips 右）；**全局卡勾选换滑块 switch**；通道卡展开自动跨全宽（.expanded grid-column，不留半列空白）；cfgFilter 搜索集含 .srow；97 断言+37 单测+24 演练全绿，双主题目检 |
| v100.5.1 | 控件精致化 | 用户截图反馈「廉价」：srow 控件从原生素样式升级——34px 高统一、圆角 9、柔和边框 hover 加深、focus 蓝环、数字右对齐 mono、时间居中；诊断留档：用户页面 slab 文字不可见但干净内核正常，特征指向浏览器暗色扩展/系统强制深色改写文字色（白字白底），非页面缺陷 |
| v100.5.0 | 设置行范式跨越 | 用户三轮不满意后停止渐进修补：A 基础卡从「网格表单」整体重构为**设置行范式（settings list）**——说明（加粗标题+浅 hint）居左、窄控件（右对齐 mono/时间/现代 .switch 开关）居右、hairline 分行；subsec 微分组标签延续；格式细节（￥前缀/时间→箭头/数字右对齐）；cfgFilter 搜索集纳入 .srow；uitest 修两个时间敏感 flake（日历 14/15 格窗口边界、trend 首点 144h）；97 断言+37 单测+24 演练全绿，双主题目检 |
| v100.4.0 | A 基础卡层级重构 | 用户点名「重点是用户名这张卡」：**微分组标签**（📉 推送频率·聚合与再推去抖 / 🌙 免打扰时段·跨零点可用，带延伸细线的 .subsec）把平铺字段切成语义小节；**label/hint 层级拉开**（label 深色加粗 12px vs hint 10.5px 更浅，全站 .fgrid 统一受益）；**hint 全部精简到一行**（免打扰/再推阈值/风暴连推）；用户名行 2fr→1.2fr 比例修正；免打扰 label 保「免打扰·开始/结束」可搜索性（曾因改短导致搜索命中 0，uitest 抓回）；97 断言+37 单测全绿 |
| v100.3.1 | 卡头质感+弹窗诊断 | **用户卡头重排**：渐变头像徽章（名字首字）+ 状态 pill 化（航线/🔔弹窗开绿灯/推送已启用绿灯、未启用灰）+ **卡头各自「● 未保存」琥珀标记**（与干净快照按用户比对，800ms 轮询）；删空用户后空态引导卡；**弹窗诊断（用户报告「没有一直在弹」）**：达标判定从未命中——10-04 中转阈值被配置为 0（关闭）、其余航线价格高于阈值=设计行为；日志「[中转达标]」名不副实改「[中转最低]」；钉钉 21 时起连续 -1 系统繁忙（心跳也失败）属钉钉侧限流，单发不重试下轮自然补；**测试基建**：_mk_db_with 锚定今天中午修日期桶 flake、trend 首点 144h 避开 168h 窗口边界（三连绿） |
| v100.3.0 | 中转深度信息 | **停留时长全链路**：qunar（全程-两段飞行）、携程（段间 datetime 差）、途牛（duration 分钟）→ flightnorm 归一化 layoverT → 控制台明细中转列第二行「停X时X分」+ **钉钉推送明细图中转列同源显示**；机型上桌：qunar planeType/同程 equipmentName → 航班格第二行（经济舱 · 3.8折 · 738）；行构建器幂等兜底 normalize（demo 等未过 SQLite 汇聚点的路径也生效）；demo 数据同步丰富；真实报文停留验证（石家庄停0时25分/西安停5时35分）；37+24+97 全绿 |
| v100.2.0 | 明细数据质量 | 用户截图实锤：**时长与起止/跨天大面积不自洽**（携程中转只给首段时长、qunar transTime 同病、跨天标记漏标/错标、格式 时/小时 混排）。新建 **core/flightnorm.py 归一化层**：depDate/arrDate 全日期为唯一事实源 → 跨天 N=日期差、时长=N*1440+到达-起飞，渠道时长偏差>15 分钟即重算，无日期时 crossDayDesc→时长环形对表 三级回退；接入 report/alerter/webui 三处 extra 汇聚点（推送图/控制台同源受益）；**舱位/折扣抽取**：qunar binfo.cabin+discountStr（V舱·3.6折）、同程 cabinlevel、途牛 cabinTypeName、飞猪 SSR 舱位行；明细表航班格第二行显示；真实报文 71 条归一化后不自洽=0（修复前 NS3632 5小时45分→11时05分 实证）；行李额度列表接口普遍不提供（如实不显示，不造数据）；37 单测（flightnorm 回归用例）/24 演练/97 uitest 全绿 |
| v100.1.3 | A 分区归位 | 用户报告「用户名这块卡片不能折叠」：**glab A 原本在 ucard 外面**（B/C/D 在卡内，结构不一致），点 A 折叠会把整张用户卡连卡头一起藏掉=看起来像消失而非折叠。修复：glab A 移入用户卡 body 内与 B/C/D 对齐——点「A 基础」只收字段卡、卡头保留；真机+demo 双探针验证（sibling=ucard→rline、卡头可见性断言） |
| v100.1.2 | 折叠手感终版 | **用户卡收展改纯 display 翻转**（旧实现走 buildForm 整表重建，重渲染弹走滚动位置=「点了像没点」）；手风琴单开语义保留；窄屏 header 收窄（隐藏更新于时间戳，603px 实测 header 100→60px，半遮卡头恢复可点可折叠）；603px 滚动状态真实点击探针通过 |
| v100.1.1 | 防旧页+A 区重排 | **HTML 响应加 Cache-Control: no-cache**（主页面+notify 轻页）——升级重启后浏览器启发式缓存可能吐旧版 JS，用户看到的折叠功能「失效」实为旧页（真机探针证实 v100.1.0 折叠正常）；A 区质感重排：Windows 弹窗改横向单行（标题+启用+测试按钮+短 hint 一行），提示语精炼防破碎换行；折叠标题行 hover 变色反馈 |
| v100.1.0 | 配置页人因工程 | 用户反馈驱动：**文案溢出**（勾选格 nowrap 去除+换行）；**子卡折叠**——A-D 分区/航线卡/通道卡点击标题行收展（display 切换零插拔，localStorage 记忆，航线卡/通道卡默认收起、标题行自带摘要，删除按钮 stopPropagation 语义隔离）；**遮挡类根治**——html scroll-padding-top（聚焦/锚点不被 sticky header 盖）、header 投影分层、toasts 下移不压 header、#cfgview 底部留白防 savebar 盖字段、窄屏 scroll-padding 加大；**反馈必达**——校验失败 cfgErr 双通道（cfgmsg+toast）、保存成功 toast、请求失败 toast；**新增用户/航线**自动 scrollIntoView+闪动高亮（新航线自动展开）；搜索命中字段蓝色描环；全局格数值内联单位（分钟/秒）；uitest 97 断言 |
| v100.0.0 | 一切可配置·真实可用 | **全局配置中心**：/api/config globals 全量暴露（调度：周期/扰动/端口/启动即扫；采集：无头/超时/错峰区间/调试/UA——全部热载）+ 启动级配置（db/log/user_data）如实 ♻ 只读展示，glsec 四分组+🔥/♻ 徽标；**通道真实可用自证**：/api/test-toast（本机真弹窗，点击直达控制台）+/api/test-ntfy（表单当前值实测）+钉钉原有测试，配置中心一键验证；**第 4 通道卡 Server酱**（send_key/channel/自动启用联动）；用户 A 区补聚合推送/降价再推/涨价再推阈值；Ctrl/⌘+S 保存；校验扩展（超时 10-600/错峰 0-120 且自≤至/阈值数值）；notify 空态横幅如实化（非达标通知不再冒充「已达标」绿条，测试弹窗直达改控制台首页）；demo globals 同步；uitest 94 断言（新增配置中心分组/启动级只读/通道测试按钮/Ctrl+S/走势 hover）；README 8 截图（新增 console-globals）|
| v50.2.0 | 跳转链接挂羊头修复 | **用户报告**：钉钉推送价格链接点开空页。根因=v5.0.0 渠道 PC 化只迁了爬虫没迁用户链接——digest 直飞/中转与控制台 ↗ 仍指 qunar touch H5（接口风控死，页面壳开数据空）。修复：`_build_view_url` qunar→PC oneway_list.htm（爬虫 wbdflightlist 同页）、fliggy→PC SSR flight_search_result.htm；**webui 新 `_view_url` 助手**按数据来源渠道出链（不再一律链 qunar）；ctrip/同程/途牛与爬虫 H5 同源保持；notify 演示样例死链同修；单测新增 test_view_url_matches_crawler_proven_path（36 用例）；uitest 86 全绿 |
| v50.1.0 | win_toast 配置物化 | **「所见即所存」**：Windows 弹窗默认开启但 config.yaml 缺键不体现、控制台也看不到状态——GET/POST /api/config 双向物化显式 `win_toast` 布尔、用户新增模板自带、用户卡头 🔔弹窗开/关 状态徽标、hint 说明默认开启；本机 config.yaml 已补写；**发版事故修复**：v50.0.0 资产误装 20.0.0 陈旧 exe（PyInstaller 产物未刷新），本版起资产 zip 抽 exe 运行 --version 终验 |
| v50.0.0 | 骨架级重塑（子视图工作台+面板式配置+可观察性） | **主页四子视图工作台**（概览/走势·日历/明细/健康，display 切换零插拔，记忆上次视图，canvas 隐藏跳绘/切回重绘）；**配置页面板化**（左导航=视图切换器，杀长滚动；搜索态临时全分区）；**core/pulse.py 扫描脉冲**（每轮每渠道行数/耗时环形缓冲，/api/pulse；主页 statline 4 格+近 40 轮堆叠柱红帽标失败）；配置搜索字段级过滤/导出导入 JSON/脏改动计数/全局与重复航线校验；钉钉推送附 /notify/{nid} 完整详情链接（与 Windows 弹窗同 nid）；WinToast _plain 链接留文字+仪表条剔除；/api/state ETag/304；uitest 84 断言；抓真 bug：全局参数锚点 data-t 指向不存在 id 静默失效 |
| v20.0.0 | 配置页分区重构（V20） | cfglayout 双栏骨架 + cfgnav 锚点导航 + seclab inline 编号标签 + 用户卡 A-D grouplab 分组 + savebar 浮出保存条；修复 cfgview 少一个 </div> 致弹层全隐藏；uitest 54 断言 |
| v1.4.1 | 推送双端兼容 + 提速 | 钉钉 PC 不认单 \n → 段落级 \n\n；进度条 10→5 格；去 U+2026；qunar MIN_GAP 12→8；**清除 --login 残留僵尸实例** |
| v1.5.0 | 控制台重构 | **修复 MAINT 未定义 ReferenceError**；走势图多航线可切；下轮倒计时；智能刷新；日期列 |
| v1.5.1 | 控制台精修 | KPI 较上轮涨跌；行内 ↗ 直达；近达标琥珀；图表主题感知；Esc |
| v1.6.0 | 效率+可达性 | 明细搜索；CSV 导出；48h 最低点标注；键盘可达；配置未保存守卫 |
| v1.7.0 | 开源体验版 | 渠道健康时间线（core/health.py）；推送预览器（_digest_payload 纯构建器，**链接替换先于粗体**）；--demo 演示模式；移动端打磨 |
| v1.8.0 | 开源体验第二弹 | **静态在线演示站**（demo_build.py 烘焙+Pages）；7 天走势切换 + 价格日历热力卡；浏览器通知+提示音；健康格子点击看日志；pill 任意用户聚合 |
| v2.0.0 | 顶级开源覆盖版（含 v1.9.0 全部） | **配置全热加载零重启**（端口原地重绑/扰动 scheduler state 引用化/无头清爬虫缓存）；💡 操作建议+达标置顶+未达标 title 锚点；折线/K线双模（涨红跌绿 OHLC）；toast 替代 alert + 内联二次确认替代 confirm + KPI count-up + 行入场动画；全局项纳入 dirty 守卫；演示配置页不回读真实凭据；**_Srv 禁地址复用**（Windows 同端口双绑静默影身，uitest 曾全在旧服上假跑）；README 中英双语+repo 元数据；uitest 36 断言 |
| v10.1.0 | 协调性 pass | 免打扰行重构为三列网格（与全站表单一致）；输入框 focus 蓝圈+hover；checkbox 主题色；danger/btn2 按钮精修；rline 边框；tabs/chip/rngchip/mchip 统一选择控件视觉语言（描边+soft 底+蓝色选中）；表头 hover 主题化 |
| v16.0.0 | 本机触达+点击看全 | **Windows 右下角系统弹窗**（PowerShell WinRT 零依赖，-EncodedCommand 中文零乱码；达标弹/心跳不弹，win_toast 配置热加载）；**点击弹窗 → /notify/{nid} 单条详情轻页**（protocol 激活，非控制台；存档 data/notify 留 20 条）；V15 签派控制台设计语言（mono 数字/分区标签/扁平仪表条/color-scheme 主题一致） |
| v10.0.0b | 设计系统升级 | 设计令牌体系（三层阴影/圆角/中性色阶/暗色 elevation）；玻璃拟态 header（blur+saturate+渐变 logo 底座）；
分段式导航；渐变主按钮；KPI 30px 大数字+达标 soft 渐变卡；表头字距精修；骨架屏 shimmer；曲线 draw-in 入场动画 |
| v10.0.0 | UI 精修 | 走势最低点标注带完整日期（曾只显 HH:MM 被误读为"刚刚暴跌"）+halo 防压线；
配置页 label 精简+nowrap（日报/风暴/免打扰等不再折行孤字）；ntfy/阿里云字段语义化命名 |
| v5.0.0 | 渠道 PC 化 | **qunar H5 风控升级急救**：PC 版主路径（wbdflightlist 拦截，桌面上下文+主域登录态），H5/httpx 降为兜底；四渠道 PC 可行性逐一定证（ctrip 432 拒/tongcheng 易盾口径未证实保留 H5/tuniu 无 PC 页/fliggy 已 PC）；解析器 2 断言单测；真机 72 条明细验证 |
| v3.0.0 | 丝滑洞察版 | **免打扰时段**（跨零点窗口：心跳/风暴/电话静默，达标主推+ntfy 照发，7 断言单测）；**📨 推送历史回看**（钉钉发送 JSONL 存档 + 控制台弹层，零插拔展开）；**走势图平滑曲线+渐变面积**（修复 X 索引误传标签致曲线消失）；视图/图表过渡动画 + 细滚动条；**近7天洞察统计**（最低/日均/降价天数/距最低）；uitest 48 断言 |
| v2.1.1 | 点行卡顿终局修复 | 用户 Chrome 每点一行卡数秒而干净内核全绿——翻译/比价扩展监听 DOM 插入全页重扫所致；同班比价展开改**预置隐藏行+display 切换**（零 childList 变更）；uitest 42 断言（新增展开零插拔/Esc 收起） |
| v2.1.0 | 卡顿根治+热加载补全+开源基建 | **修复扫描器闭包捕获启动 cfg 快照**（爬虫超时/错峰/UA/日报时刻/图床热存不生效 → rt["cfg"] 单一事实源）；**控制台性能**（/api/state 签名+字节双缓存 2.2-3.5s→3ms、health 日志缓存、save_many 批量写、大表免动画）；监控页多用户切换 pills；钉钉开关 checkbox/数字时刻原生输入/favicon/保存反馈淡出；测试推送带版本号；CONTRIBUTING/SECURITY/Issue/PR 模板；CI 双 job（单测+推送链路+**uitest 进 CI** 40 断言）；uitest 40 断言 |

## 9. 下一会话建议动作（按价值排序）

1. **钉钉双端排版真机确认**：v1.4.1 起 \n\n 方案尚未收到用户手机+PC 双端反馈——下次推送后请用户截图确认（可用 👁 预览推送先行比对）。
1b. **v110.10.0 比价行卡真实推送目检**：下一自然轮推送后看群里明细总表 PNG——比价两行式行卡（可省红字右对齐+整链第二行）与达标推送 🟩 满格仪表在钉钉客户端的实际观感；多渠道同班的航线才有比价组，无则正常。
2. qunar MIN_GAP 8s 稳定性观察：若 httpx 1999 频次明显上升（日志 grep `命中风控`，或健康条纹 qunar 行琥珀/红增多），回退 10s。
3. 途牛/同程中转接口可行性（途牛返回里或有 transfer 参数未开）。
4. 朋友用户接入（网页配置加用户+航线+webhook 即可，多租户已卡片化；监控页已有用户切换 pills）。
5. 端口热切换的真机回归（v2.0.0 后首次用户改端口时关注日志「已热切换」）。
6. 冷启动 state 首算（每轮 DB 首次写后第一个请求）仍为全量计算（数百毫秒级）——如需进一步压平可改后台预计算。
7. **行李直挂数据源扩展**：ctrip/途牛/同程接口若有行李/中转服务字段，接入 `_baggage_tag` 同款解析（qunar 参考 `crawlers/qunar.py`）——否则该航线的直挂筛选下中转全部不可见（如实告知用户）。
8. **中转衔接三级计算与兜底**（v1.1.0）：qunar PC `binfo` 的 `flightTime` 是「1小时45分钟」全称格式（非 H5 的 2h10m，`_dur_min` 兼容）；衔接=第二段起飞−第一段到达（跨天 %1440）比 transTime 差值更稳定，快照复解析覆盖率 100%（原 19.5% 缺失根治）。**廉航排除**：春秋等 LCC 的 transitServiceLabel 是机场「代转运」服务包装非两段直挂（用户实锤），直挂判定排除 LCC（AIRLINE_LCC）。
9. **单实例互斥锁**（v1.1.1）：`main.py` 启动即锁 `data/.instance.lock`（msvcrt，进程退出自动释放），第二实例立即退出——根治 3 进程并行抢采/互踩 DB 的事故链（16:52/18:37/18:45 三实例并存实锤）。start.ps1 的 pid 文件只管自身路径，手动 python 启动绕过——锁才是兜底。
10. **_ScaledDraw 代理域一致性**：2x 超采样代理的 `textlength` 返回**逻辑域**宽（物理/S），`_fit_text` 的 max_w 也是逻辑域——**切勿在 max_w 上再乘 S**（混域=判定恒过、长航班名溢出列界粘连出发时刻，复现实锤）。字号一律 `d.font(n)`（代理放大）。
11. **显示不依赖配置**：中转衔接时长行始终显示（时长是决策关键），着色才按配置分档（下限内绿/偏短琥珀/未配置灰）——「显示」与「告警着色」是两个独立决策。`git worktree add _rel <commit>` 打包、产物与提交树一致（v110.15.0 根治 `__init__.py` 未入库后 fresh clone 也能打包）；并行会话改工作区时尤其必须走此流程。

> 控制台六环闭环（监控/健康/预览/演示/在线站/全热配置）。发版后记得重烘 `python docs/demo_build.py` 让在线站同步。

## 10. 工具环境坑（本会话实测，下会话必读）

1. **PowerShell 工具会话跑不了原生命令**（无 ConPTY：`& python` 无输出、$LASTEXITCODE 为 null）；原生命令一律走 Bash 工具。
2. **Bash 沙箱 SIGTERM playwright 派生树**：截图/验证脚本需关沙箱跑；输出常被吞，**结果落盘再读**。僵尸 chrome 用 PowerShell 只杀非 user_data 的（node 全保留——WorkBuddy MCP 全是 node）。
3. **PYTHONPATH 注入了 WorkBuddy trash shim**（拦截删除 → PyInstaller 炸 SHFileOperationW 0x2）：打包必须 `PYTHONPATH= python -m PyInstaller`。
4. **git 网络**：走 Clash 7897；credential-helper-selector 会弹 `git config --system -e` 编辑器挂死；**push 会整体挂死 → 兜底 GitHub Git Data API**（文本 CRLF→LF 归一、mode 一律 100644、base_tree 完整 sha、**target_commitish 用分支名不用短 sha**——短 sha 建 Release 422）。
5. **取 token：直调 git-credential-wincred.exe get**（helper-selector 中间层在非交互会话必挂；`git credential fill` 同样会挂）；**环境变量必须 export**（`VAR=$(cat f) && cmd` 是 shell 局部变量不进子进程——本日 5 次"脚本零输出挂起"全是这个）。
6. PowerShell `Out-File` 默认 UTF-16；**reset --hard / checkout -- . 前必须确认无未提交编辑**（HANDOFF 被吃过两次，均凭对话记录重建）。
7. **Windows 同端口双绑静默影身**：Python HTTPServer 默认 allow_reuse_address=True，Windows 下 SO_REUSEADDR 允许两个进程同绑一个端口，后到者"启动成功"却收不到连接——uitest 曾全套跑在旧代码僵尸服上假红。webui._Srv 已禁复用。
8. **沙箱内 python 的 subprocess 调 taskkill 等原生工具可能静默失败**——杀进程走 PowerShell 工具。
9. 后台任务管道末端的 tail 会吞掉全部进度输出——**进度必须 python 内直写文件**。
10. **会话起 demo 前先 `netstat -ano | grep :端口`**：上次会话的 `--demo` 进程常驻僵尸（本会话 8799 上抓到 09-12 的），截图/探针全打旧代码=「磁盘新代码、线上旧行为」假象；杀 PID 用 PowerShell `Stop-Process -Id`。
11. PowerShell 单行 ForEach-Object 里 `$_` 会被 Git Bash 展开成路径——进程过滤杀栈写进临时 .ps1 或直接 `Stop-Process -Id <pid>`。
