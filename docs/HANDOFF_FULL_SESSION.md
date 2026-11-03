# 机票监控台 · 完整指导书（目标 · 期望 · 实践 · 经验）

> **这份文档是什么**：本会话（2026-10-31，长时间跨域工作）的**完整记录与作业指导**。
> 它不只是"交接"——包含**全部目标、验收标准（什么叫做到了）、已达成的部分、未达成的部分、可复用的方法论**。
> **读者**：接替我继续的下一个会话。读完这份，应能：① 知道要做到什么程度才算完；② 知道现状在哪；③ 知道怎么改才不会破坏已有成果。
> **配套**：
> - `docs/HANDOFF_CAPABILITY_MATRIX.md` —— 10 渠道能力一致性专项（本轮主题）
> - `docs/HANDOFF_GUIDE.md` —— 发版七步与文档门禁体系
> **编写时间**：2026-10-31 20:40。**所有数字均为实测**，并附可复现命令；无法复现的数字不写。
>
> **2026-11-02 更新（v1.5.307 之后）**：v1.5.307 已按规范发布并四端对齐。
> 当前工作树另有**未提交**的 `app_fliggy`（飞猪 App，固定竖屏 + OCR）等改动，
> 渠道宇宙扩到 10 家（5 浏览器 + 5 App）；线上 8765 仍旧码、未启用 app_fliggy。
> 下次发版需按 `HANDOFF_GUIDE` §5 重建四平台包/站点/资产，并先处理飞猪
> 「访问被拒绝」需人工恢复一个边界；app_ctrip 修复城市页判据后已连续两次 32/33 行复验。
> 同程 App 另接原生价格日历，`calendar/low_fare=y`（2026-11-02 真机 14 天
> ¥450/350/…/15.8s，雷达 `app-calendar ok`）；离线演示站已烘焙
> `/api/channel-dims`、完整 `/api/health`（10 张诊断卡）与
> `/api/channel-links`，配置页矩阵/健康卡/渠道入口/特价雷达入口不再显示
> 「加载失败」；公开站不烘本机真实登录槽位。
> 全量 UI 门禁 **670/670**（2026-11-03 00:29 复跑，10 渠道，零 JS 错误）：来源条单行、
> 探针 10 chip 与查询字段同排、诊断卡证据标签不被 48px 行高拉伸、
> 健康卡 ≥900 为 5+5（无整格空洞）。
> 全量非 UI pytest **6083 passed / 22 skipped / 0 failed**（2026-11-02 23:31）：
> 14 条旧门禁已收敛——11 条是 10 渠道/单一源迁移的过期锚点，
> 3 条 Qunar 期望按 r817「无认证证据才催重登」契约改用隔离空档案。
> 携程 App 日历 OCR 解析器 + `calendar()/low_fare()` 已真机端到端：
> SHA→PEK 61 天**连续两次**（11-03..次年 01-02，¥380–420；23:20/23:39，
> OCR 3.7/3.8s，全程 37.3/20.2s，`app-calendar ok`），
> 国际档 SHA→NRT 连续两次 54/53 天（¥864–1530；11-10 查价；两月视野）
> 真机通过，矩阵 `calendar/low_fare/intl=y`，并接特价雷达 `_app_ctrip_deals`；
> 国内/国际往返均已真机端到端（去/返双栏，去程卡价即页脚「往返总价」，
> 国际 SHA→NRT 8 条 ¥2146；国内 SHA→PEK 5 条 ¥760、返程 14:00→16:30
> +¥0），`round_trip=y`；返程栏晚一帧时解析前最多等 10s；
> 解析器按本次截图实测行距（国内 88px / 国际 107px）并对齐被 OCR
> 拆开的金额，国际单程明细 38 条、最低 ¥935 已复验（列表不暴露航班号，不编造）。
> **2026-11-03 01:37 补（r903–r910）**：全量非 UI **6103 passed / 21 skipped /
> 0 failed**（workers 8，内容指纹前后一致）；新增 r903 声明自洽、r904 全仓
> 重复键、r905 route 自检按钮、r906 跨午夜日期、r907 可指导五态契约、
> r908 文档摘要/携程 App 往返口径、r909 320 档 pacing 行高、r910 同程国际
> 往返 API 负结论；能力矩阵截图与静态站已按 10 渠道 + 携程 App 国内/国际
> 往返重烘（当时站戳 `3a7ea543ba18`；当前站戳见下），`release_align_check --local` **25/25**；
> Release 当前 `v1.0` → `e65cee1`（09:54 由 `ab04c22` 重指，正文/四资产/tag 同源）；ghcr `latest` = `sha-e65cee1` digest `5fb025bb3488…`（同 digest），`sha-ab04c22` 单独存在（digest `9b72acb1a6b9…`）；
> Release `v1.0` 当前 → `e65cee1`（首发 `ab04c22`，10 渠道正文，资产 4/4）；live 8765 已于
> 2026-11-03 08:58 切到 `_release_ab04`（PID 47952）。r933–r953 已入库（至 `80c63eb`），
> live 树仍停在 ab04c22；多程采集/配置卡/概览整单卡/来源页/整单历史与日桶下限守卫见
> SPEC r941–r951。
> **2026-11-03 03:30 补（同程 App 国际往返 + 最终树）**：同程 App 国际往返真机接通
> （上海⇌东京 11-16/19，7 条去程、最低 9C8515 ¥2209 含税总价；返程 `+¥N` 为加价），
> `round_trip=y`（仅国际）；`PATH_CN` 补 `app-roundtrip`（r658 门禁曾点红）。
> tracked collect **6214**；全量非 UI **6236 passed / 19 skipped / 0 failed**
> （14:46，workers 8，683.41s，共 6255，含未跟踪并行 WIP 测试）；矩阵升 y、
> r958 配置控件与门禁修复均在其内；UI **670/670**（15:15 全量复跑，零 JS 错误，含矩阵 y 与 9 个新控件）；能力矩阵截图
> `docs/screenshots/console-dims.png` 已按 10 渠道 + RT 状态重烘，
> 静态站同步；`release_align_check --local` **25/25**。
> **2026-11-03 05:18 补（r927 途牛 H5 国际往返）**：`m.tuniu.com/flight/` 往返档
> 真实可搜；HotCity 字典 IATA→数字城码，列表页 token + `queryFlight` 两段
> segment → `productList.avgTotalPrice`。真机 SHA→NRT 11-05/08 **35 条、最低
> ¥3010**（页面「往返 含税」），真实 fetch 1 行 3.8s；只取渠道总价不相加。
> 矩阵 `tuniu.round_trip` 移除「仅国内」scope，国内/国际均 y；新增真实报文夹具
> 与 `test_r927`，定向 8 passed；全量 **6127 passed / 19 skipped / 0 failed**（05:28）。
> **2026-11-03 04:24 补（同程 App 往返端到端）**：`fetch(SHA,NRT,11-17,ret=11-22)`
> 真机 **9 条组合、最低 ¥2420**（GK036 02:20→06:20；返程 MM877 +¥0；
> `retLoaded=true`，20.9s），`tripType=RT`/`backDate`/`totalBasis` 齐全。
> 现网页脚措辞 `已选 02:20- 06:20 捷星航空` 不写「出发」，返程栏还有 ~54px
> 紧凑时刻副本——解析器按宽度排除副本并放宽页脚锁定；返程栏最多等 30s，
> 等不到标 `retLoaded=false`。新增 `tongcheng_roundtrip_live.xml` 夹具。干净 venv 按最终树重建 Windows
> 候选包（`--version=1.5.307`，含 `app_tongcheng`/`app_tongcheng_parse`/`app_ctrip_roundtrip`），
> **61,932,953 bytes / 864 entries**，SHA256 `3c472292102f8a0d45b06bfaef962a350d513359e3d7bba2666891b8a208a8a4`；未上传。**2026-11-03 06:39 复验**：解包根 `TicketMonitor.exe` + `_internal/`、0 敏感文件，`TicketMonitor.exe --version` → `1.5.307`。
> 最终彩排 tree（含本轮全部文档改动）记录在 `_scratch/final_tree.txt`：**1073 文件**，敏感文件 0；
> 两份新 RT 夹具已归一为 LF（App 解析/采集重跑 35 passed）。
> **2026-11-03 03:47 补（r926 同程 PC 国际往返）**：登录档案下 book1 RT 页
> `miflightapi/ts/list` 的 `tp` 为「含税总价」、`lng` 带去/返两段；真机 SHA→HKG
> 11-20/23 **41 条、最低 HX231+HX0234 ¥1463**；SHA→NRT 同轮 **77 条、最低
> 9C8515+GK0035 ¥2393（8.4s）**；真实 `fetch` 均 1 行。只采
> 渠道总价、不相加；匿名跳 passport 记 login。矩阵仍 `y`，移除「仅国内」scope
> （国内 `book1/roundtrips` + 国际 `ts/list` 均有证据）；新增真实报文夹具与
> `test_r926`，定向 **123 passed / 14 skipped**；全量 **6123 passed / 19 skipped / 0 failed**（04:34）。
> extra 行已补 `depTime/arrTime/code/name/intl/totalBasis` 兼容键，`_flights_from_extra`
> 41/41 归一，趋势/告警/明细不再空白；`report._rounds` 临时库集成用例通过（r926 4 passed）。
> **2026-11-03 03:05 补（携程往返/国际明细 + 同程国际日历/明细）**：全量非 UI **6108 passed /
> 20 skipped / 0 failed**（02:59，workers 8，哈希前后一致）；UI **670/670**（03:05，
> 0 JS 错误）。携程 App 国内/国际往返均真机端到端（去/返双栏，去程卡价=页脚
> 「往返总价」，国际 SHA→NRT 8 条 ¥2146；国内 SHA→PEK 5 条 ¥760、返程
> 14:00→16:30 +¥0），`round_trip=y`（国内/国际，scope 与国内前置守卫已移除）；
> 携程 App 国际单程明细真机 38 条、最低 ¥935（列表不暴露航班号，不编造）；
> 同程 App 国际价格日历连续两次 SHA→NRT 14 天 ¥882–1495（`app-calendar ok`），
> `intl=y`（国际日历 + 单程明细 6 条 ¥875，实付价取最低）；往返档真机查询后
> 落到营销/示例页（6 月/廊曼，非本航线），未接且不冒充（同日稍后推翻：国际往返
> 已接通，见下）；国际价格日历 54/53 天 ¥864–1530；
> 日历解析按截图实测行距（88/107px）并拼接被 OCR 拆开的金额；静态站站戳仍
> `3a7ea543ba18`（webui 含 r918 提示后重烘，戳 `b7b27668ea4d`）。
> 发布对齐：干净 HEAD worktree 与当前工作树 `release_align_check --local` 均 **25/25**。
> README 品牌横幅 `docs/assets/banner-zh.svg` / `banner-en.svg` 为**新增未跟踪**
> 资产（1600×420，1024/Chromium 渲染无越界；仅写 10 渠道/7 维度/11 轴与流程，
> 不含虚构价格），下次发版提交必须一并纳入，否则 README 图片会空。
> 同程 App（2026-11-03）：国际价格日历真机连续两次 SHA→NRT 14 天 ¥882–1495
> （`app-calendar ok`，1.7/2.1s），`intl=y`（国际日历 + 单程明细 6 条 ¥875）；
> 国际往返同日打通（上海⇌东京 11-16/19，7 条去程、最低 9C8515 ¥2209 含税总价，
> 返程 9C6218 +¥0；`+¥N` 只为加价、不相加），`round_trip=y`（仅国际）。
> 旧「查询落营销/示例页」是首访教学浮层遮挡误判；开屏活动弹层仍会临时挡住点击，冷启/重进后恢复。
> **2026-11-03 02:40 补（r920 同程 PC 国际往返登录门）**：匿名公开页可选往返/
> 城市/双月日期（SHA→HKG 11-20/11-23），提交后跳 `passport.ly.com` 登录并出腾讯
> 拼图滑块，未登录未绕过；跳转 URL 带 `book1.html?para=SHA*HKG*...*RT*...` 产品参数。
> 结论：国际往返卡点是登录态不是解析，`tongcheng.round_trip` 说明已按此改写，
> 矩阵仍 `y` 且 scope=仅国内；静态站已随说明重烘（webui 未变，戳仍 `b7b27668ea4d`）。
> **2026-11-03 02:42 补（r921 去哪儿 H5 国际往返）**：匿名移动端往返页两栏只
> 显示「成功」占位、底栏「¥0 往返总价」；`touchDoubleInnerList` 虽 HTTP 200，
> 但 `bstatus.code=1999`、`data=null`——风控软拒，不是真 0 元空结果。产品继续
> 显式拒绝国际往返，不落价；`qunar.round_trip` 说明已改写，矩阵仍 `y`（仅国内）。
> 另用产品档案走同一 H5 双列表（上海/东京）仍未解析到往返总价（26s）——该页不是
> 国际往返通路，不把「登录后就能出」写成事实。
> **2026-11-03 05:46 补（r928 去哪儿 H5 国际往返表单复核）**：首页「国际/中国港澳台」
> +「往返」表单（北京→东京 11-04/06）可正常选城并提交，落 `/ncs/page/interlist`；
> 随后 `touchInterList` 仍回 `bstatus.code=1999`、`data=null`，页面写「查询超时，
> 请点击按钮重试」。故 r921 的「该页不是国际往返通路」修正为：**通路存在且可提交，
> 当前被渠道侧软频控拦住（测不出）**；矩阵仍 `qunar.round_trip=y`（仅国内），
> 国际往返待通路恢复再验，不据此判「不支持」。本轮表单探测后该账号可能进入
> 1999 冷却，下一轮采集若遇 1999 按软频控处理，不判能力缺失/登录失效。
> **2026-11-03 06:08 补（r929 携程 PC 多程口径）**：产品指纹下列表页切
> 「多程(含缺口程)」，SHA→TYO 11-20 / TYO→OSA 11-23 提交落
> `/online/list/multi-sha-tyo-tyo-osa?depdate=2026-11-20_2026-11-23&cabin=y_s&adult=1&child=0&infant=0`；
> 「多程超低价」卡两段并排（9C8515 + MM304），价 **¥1298** 明写
> **「多程含税价」**，下方第一程候选也逐条写「¥N 起 · 多程含税价」。
> 携程多程整单总价口径坐实；采集端因单 O-D 模型/多段配置未接，矩阵
> `ctrip.multi_city` = **y（scope 仅 2 段，生产行 ¥1476）**；其余九家仍 `""`；3+ 段/缺口程未验。
> 另对齐 r922 文档口径：`docs/APP_CHANNELS.md` 同程 App「未接」行、装机结论与
> `app_tongcheng.detail` 说明统一为「国内明细已覆盖；国际只走日历」（后由 r923 推翻：
> 国际明细已真机 6 条 ¥875）；r903/r822/docs/EOL **104 passed**、
> `release_align_check --local` **25/25**。
> **2026-11-03 02:56 补（r923 同程 App 国际明细）**：真机 SHA→NRT 11-16 **6 条、
> 最低 ¥875**（7.9s，实付价取最低、保留划线列表价）；`detail=y` 国内/国际均有真机
> 证据。已把 `APP_CHANNELS.md` 装机结论、`core/channels.py` 注释与 detail 说明里
> 残留的「国际明细未接」清掉；当时往返查询仍落到营销/示例页（6 月/廊曼）未接，
> 同日稍后国际往返已接通（上海⇌东京 ¥2209，见上），此句保留为过程结论；
> 多程未接。r922 的「国际只走日历」范围句作废。复验：全量非 UI **6108 passed /
> 20 skipped / 0 failed**（03:08，8w，被测代码指纹前后一致；当时 RT 接入前的树）；
> 定向门禁 **118 + 62 passed**，`release_align_check --local` **25/25**。

---

# 第一部分 · 目标与期望（什么是"做到了"）

## 1.1 用户的原始目标（**目标归纳，非逐字原话**，共 12 条）

> ⚠ **引用性质**：下面这 12 条是本会话**跨多轮对话的目标归纳**——按主题合并、去掉了口语重复、
> 并补上了「做到什么程度算完成」的验收口径。它**不是用户逐字说过的话**，
> 不要当作可直接引用的原话，也不要据此推断用户的措辞偏好。
> 需要引用时用「用户的目标是……」这种转述口吻。
>
> 想看去掉归纳后的原始诉求样例，见 `docs/UI_UNIFICATION_PLAYBOOK.md` §0.0.1（那里也明确标注了「整理版」）。
>
> 这些是**需求**，不是建议。验收时逐条对照。

| # | 目标 | 什么叫做到了（可验证） |
|---|---|---|
| 1 | **统一登录**：所有厂商 + 渠道都必须登录；cookie 不共享的独立登录；**抛弃"建议登录"** | 6 个浏览器槽位 `requirement` 全为「必须登录」；飞猪 PC/H5 分开；无任何用户可见的"建议登录/可匿名"字样 |
| 2 | **节流板块**搬出「全局参数」 | 节流是独立分区（`#paceBox`），不在全局参数卡里 |
| 3 | **多渠道可区分**：渠道健康不能只有厂商一维 | 健康按 domain/path/session 分域；未扫描渠道如实标"未扫描" |
| 4 | **节流面板 UI 质感/排版/交互**重点重构 | 有像素级验收：无裁切、无错位、同行同源、口径一致 |
| 5 | **最高原则**：提升渠道成功率与干预成功率的操作设计成 *可配置/可自动化/可观察/可判断/可溯源/可识别/可统一/可开启/可关闭/可选择/可指定/可幂等/可准确/可对齐/可验证/可区分/可定位/可唯一/可手动干预*，**干预要及时、要能生效** | 每个 `advice.action` 在界面有落点；干预前后**同窗口等长**统计；治好判定**封顶**；写失败留痕 |
| 6 | **进程级安全/健壮/高可用**，且可见/可观测/可干预 | CSRF 闸门覆盖所有写接口；进程自重启有锁序；异常不静默吞 |
| 7 | **配置页不允许任何无法配置的项**；需重启就走重启；能热更新就热更新 | `test_r601`（全部键可达）+ `test_r634`（节流键可配）绿 |
| 8 | 解决 **GitHub issue（含评论）+ 小红书帖子**的问题，并避免同类再出现 | #8/#10/#11/#12 已处置并有测试；小红书"登录配好但全红"→ `stalled` 态 |
| 9 | 解决**所有 PR**；功能合并是主要目的；**每位贡献者进 Contributors** | PR 能力已独立重写+测试；贡献者以 **author** 身份提交（noreply 邮箱） |
| 10 | **发版规范**：commit 一次 / commit 消息初版 / Release 初版 / package 一版 / deployment 一版 / README 初版完整 / 演示站初版完整 | 见 `docs/HANDOFF_GUIDE.md` §5 七步；Release 名称恒定，版本只在正文 |
| 11 | 测试**不得含本机独有信息**（工作目录、绝对路径） | `test_tests_carry_no_machine_specific_paths` 绿；字体探测平台中立 |
| 12 | **7 渠道全维度能力一致，特色能力可独立识别或聚合，后续可拓展** | 7×7 矩阵每格有代码证据；界面有「能力对照」卡；新增渠道/维度有 checklist |

## 1.2 隐含期望（用户没说但反复以"打回"表达）

- **数据诚实 > 功能多**：宁可显示"—"或"不支持"，也不许编造。
- **状态清晰、语义清晰**：同一个数字在不同面板必须同源，做不到就标口径词。
- **可见性**：用户等待/需要操作时必须看得见"进行中"，不能只是幂等拒绝。
- **可对齐**：两态（展开/收起）同坐标；同列同高；左右缘成线。
- **不许跳过**：测试红就是红，不许 skip 掉或删断言来变绿。

## 1.3 两条不可违反的底线

| 底线 | 含义 | 反例（真实发生过） |
|---|---|---|
| **不伪造数据** | 拿不到就记 `error`/`soft_reject`/`unsupported`；`empty` 必须有无票证据 | 途牛收到 `ret_date` 静默按单程采集 → 单程价被当往返总价（**本轮已修**） |
| **演示站 = 合成数据** | 绝不标"正常"；DEMO 徽标必须可见 | 演示页曾显示"全部正常" |

---

# 第二部分 · 验收标准（Definition of Done）

## 2.1 单条改动

- [ ] 有**最小复现**（脚本或一行命令），先证明它现在确实错。
- [ ] 定位到**根因**，不是症状。
- [ ] 改的是**实现**，不是门禁。
- [ ] 有**门禁**，且做过**负控**（撤掉修复 → 红；恢复 → 绿）。
- [ ] 单点门禁 → 相关文件 → 全量（存 `md5sum` 前后一致）。
- [ ] UI 改动**截图亲眼看**。

## 2.2 一轮功能（如本轮的"7 渠道能力一致性"）

- [ ] 每条需求能指到**文件:行**或**门禁文件**。
- [ ] 数据类声明（`y`/`n`/`""`）**每一格都有代码证据**。
- [ ] 界面能**独立识别**或**聚合呈现**（不是只在源码里）。
- [ ] 用户可见文案**不写死数量**。
- [ ] 有对应的 HANDOFF 文档片段。

## 2.3 发版

- [ ] 全量 `pytest` 全绿（含并发跑）。
- [ ] `docs/uitest.py` 668/668。
- [ ] 四个平台包在**发布 SHA** 上重建、`--version` 正确、SHA256 一致。
- [ ] Release 名称恒定、版本只在正文、四资产 + SHA256SUMS。
- [ ] 演示站按已发布树重烘，`code:` 戳 = 该 SHA 的 `webui.py` 前 12 位。
- [ ] `python docs/release_align_check.py` 到 PASS。
- [ ] Contributors 列表包含每位贡献者。

---

# 第三部分 · 现状（2026-10-31 20:40 实测）

## 3.1 代码与产物

| 项 | 值 |
|---|---|
| 源码版本 | **v1.5.307**（`main.py:17`） |
| `webui.py` 规模 | 34033 行；md5 前 32 位 `869b31b3ba1a97225a5a5897945ac65e` |
| 远程发布 | 仍停 **v1.5.306**（提交 `5cff7f5`） |
| 工作区 | **81 项未提交**（含 19 个新测试文件） |
| 测试总量 | **5467 条**收集 |
| 全量耗时 | 25–37 分钟 |

## 3.2 测试状态

- **能力线门禁：54 passed**（r677/r683/r674/r700/r701/r900/r901/r902，8 文件 41.6 秒）
- **全量最近一次：5403 passed / 20 failed**，我已修 16 条（多为旧断言过期），**剩 4 条属并行会话未收口**：

| 测试 | 根因（已核实） |
|---|---|
| `test_r366_source_strip::test_source_access_is_compact_strip_not_three_tall_cards` | 断言 `#healthDiag>#scNote{display:none`；并行会话已把 `#scNote` 挪进来源卡（r873） |
| `test_r536b_note_sits_under_trigger` ×2 | 说明浮层定位规则被重排 |
| `test_v1555_webui::test_body_open_div_single_ternary` | 断言内联 `padding:4px 16px 14px`；已收进类 `.ucbody`（r872） |

> **当前不可发版。**

## 3.3 7×7 能力矩阵现状（+ 3 个可选 App 行，可直接对照）

```
dims: ('domestic','intl','calendar','detail','round_trip','multi_city','low_fare')

ctrip        domestic=y intl=y calendar=y detail=y round_trip=y  multi_city=y low_fare=y
qunar        domestic=y intl=y calendar=y detail=y round_trip=y  multi_city="" low_fare=y
fliggy       domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
tongcheng    domestic=y intl=y calendar=y detail=y round_trip=y  multi_city="" low_fare=y
tuniu        domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
app_zhixing  domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
app_qunar    domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
app_fliggy  domestic=y intl="" calendar="" detail=y round_trip="" multi_city="" low_fare=""
app_ctrip    domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
app_tongcheng domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y

App 缺口：app_zhixing=(multi_city)   app_qunar=(multi_city)   app_fliggy=(intl,calendar,round_trip,multi_city,low_fare)   app_ctrip=(multi_city)   app_tongcheng=(multi_city)
```

**稳定基线 7 家**：浏览器 5（携程/去哪儿/飞猪/同程/途牛）+ App 2（**智行 App / 去哪儿 App**）。
另有**验证中、不计入 7 家稳定基线**的三个可选 App 渠道：`app_fliggy`（飞猪 App，固定竖屏 + OCR，国内单程连续两次两条航线跑通；
连续自动化会触发 access denied，采集端 blocked 停手、需人工恢复）、`app_ctrip`（携程 App，修复城市页判据后连续两次 32/33 行）、
`app_tongcheng`（同程 App，2026-11-02 冷启后连续两次 + 双日期均真机跑通，待下次统一重启启用）。
矩阵行保留在下方，缺口如实列。
> ⚠️ **美团 App 不存在**——评估过，因"点机票即触发风控/人脸"挂起未接入。别当成第三个 App 渠道。

---

# 第四部分 · 已达成（按目标逐条）

## 4.1 目标 1 · 登录统一 —— 已达成

- **6 个浏览器槽位**（`core/login_slots.py::LOGIN_SLOTS`）：`ctrip / qunar / fliggy / fliggy_h5 / tongcheng / tuniu`，每个 `requirement: '必须登录'`。
- **App 渠道**（智行 / 去哪儿 / 飞猪 / 携程 / 同程）走真机内嵌画面
  （`/api/app-login/*` → `core/android/login_api.py::dispatch`），同为"必须登录"；
  快照/设备/运行时在 `core/android/{snapshot,device,runtime,mumu}.py`。
- 飞猪 **PC/H5 是两个域**（fliggy.com / taobao.com），会话不共享 → 两槽位。
- 登录入口**按实测重选**：`www.tuniu.com` 在移动指纹下是 WAF 页、`www.ctrip.com` 是 App 式首页 → 改 passport 页；**爬虫与登录卡读同一常量**（`TUNIU_LOGIN_URL` / `CTRIP_LOGIN_URL`）。
- 每槽位可「立即核验」：`/api/channel/probe` 跑**真实查询**——出数记可用；被登录墙/人机验证拦记**拒绝证据**；0 条且无拦截证据只说"本次无数据"，**不判会话失效**。
- 无图形环境（Docker）预检：`_no_graphical_env()` 单源，同步返回 `kind=no_gui` + 可执行指引。

## 4.2 目标 2 + 4 · 节流面板 —— 已达成

- 独立分区 `#paceBox`，不再挂在全局参数里。
- 口径统一：同一账本两处渲染必须分类同套；同行数字同源，做不到就标口径词。
- **可干预性**：`/api/pacing`（读）、`/api/pacing/reset`（解除冷却）、`/api/channel/{probe,verify,warmup}`、`/api/challenge/{open,verify,skip}`、`/api/login-verify`、`/api/probe/{start,cancel,search}`。
- 干预统计纪律：前后**同窗口等长**；治好判定**封顶**（无界窗口会让远期偶然成功冒充生效）；写失败**留痕**。

## 4.3 目标 3 · 多渠道可区分 —— 已达成

- 渠道健康按 **domain / path / session** 分域（`scopes`）。
- 未扫描渠道如实显示"未扫描"，不写"正常"。
- `0%` 必须有有效分母（`rate_excl_empty`）；`null` ≠ 字段缺失；`—` 只表示无样本。
- 徽标色必须等于文字义。

## 4.4 目标 5 + 6 · 可干预性与进程安全 —— 已达成

- CSRF 闸门放在 `_do_POST` 开头（新增写接口自动继承）。
- 进程自重启有锁序（旧进程先退出释放锁，新实例延迟抢锁）。
- 异常不静默：写失败、渲染失败都留可 grep 的痕迹。

## 4.5 目标 11 · 测试可移植 —— 已达成

| 问题 | 根因 | 修法 |
|---|---|---|
| CI 渲染像素断言红/假绿 | `has_cjk_font()` 接受 DejaVu 回退（无汉字） | 改为真检查字形 `getmask("中").getbbox()` |
| CI 无中文字体 | 环境缺失 | CI 装 `fonts-noto-cjk` |
| 登录窗口用例只在 CI 红 | `_no_graphical_env()` 在 Linux 恒 True | conftest autouse `_pretend_graphical` |
| `test_r675` 全量红单跑绿 | r671/r672 替身 `webui._bind_host` 不还原 | 夹具 teardown 还原（含异常路径） |
| `test_r652` 平台路径 | 写死 `D:\other\a.db` | `os.path.join(os.sep, ...)` |
| 新测试绑固定端口 | 并发冲突 | `_free_port()` |

## 4.6 目标 8 + 9 · GitHub / PR —— 已达成（部分）

- #8 ghcr 镜像：工作流加 `push_image` 开关、`docker/login-action`、双标签推送；compose 拉取优先。
- #10 无图形环境：返回 `no_gui` + 指引，不再谎报"已弹出"。
- #11 启动失败不可见：文档键名 `network.*` → `web.*`（曾静默失效）。
- #12 明细台分类标签渲染成 SVG 源码：已修。
- 小红书"登录配好但全红"→ 新增 `stalled` 态（跨窗口看最后样本，>6h 判"停了"）。
- PR：能力独立重写 + 测试 + `Co-authored-by`；**贡献者以 author 身份提交**。
- 推送：`git push` 会超时（`.git` 1.2 GB），用 `_scratch/api_push.py`（Git Data API）。

## 4.7 目标 12 · 7 渠道能力一致性 —— 本轮核心，已达成 5 项

### ①【P0 诚实性】途牛往返"静默串味"
- **缺陷**：`crawlers/tuniu.py::fetch()` 收到 `ret_date` 只用来跳过 PC/token 路径，最终**仍按单程采集并返回**；`_hoop()` 从不带返程日；全程不记 `TRIP/unsupported`。
- **后果**：勾了往返的航线，途牛返回**单程价**，被推送/走势当往返总价。
- **修法**：与 `ctrip.py` 同律——`path_note("TRIP","unsupported")` + warning + `return []`，**不发起单程查询**。
- **验证**：`safe_fetch(..., ret_date=...)` → `[]`，`paths` 含 `('TRIP','unsupported')`，且 `_fetch_intl` 未被调用。
- **连带**：矩阵 `tuniu.round_trip` 由 `""` 改 `"n"`。

### ②【P0】low_fare 两张表互相矛盾
- **缺陷**：`CHANNEL_DIMENSIONS.low_fare` ⇄ `SPECIAL_CAPABILITY.sources` 给出相反答案（雷达里 `_ctrip_deals`/`_tongcheng_deals`/`_tuniu_deals`/`_qunar_deals` 都是真源，矩阵却写 `""`；去哪儿矩阵 `y` 而雷达 `sources: []`）。
- **修法**：新增 `SRC_QUNAR`/`SRC_TONGCHENG` 常量并补齐源；矩阵对齐为 `y`。
- **门禁**：`tests/test_r900_low_fare_single_truth.py`（3 条）钉住两表互为镜像。
- **边界**：智行 App「特价」的旧结论「按目的地、非按日期、空源」**已被 r732 真机复核推翻**——那是把首页「省钱攻略」推荐卡当成了特价档；真实入口是「特价」页签 → 设航线 + 日期区间 → 逐天最低价，已接入 `SPECIAL_CAPABILITY`（`sources` 非空）并进雷达分发。

### ③【P1】能力矩阵上屏
- **缺陷**：`/api/channel-dims` 早存在，**前端 0 处调用**。
- **修法**：配置页「渠道登录」tab 新增 `#sec-dims`「能力对照」卡：行=维度、列=渠道、三态 `✓/×/?`，App 列头标"同源 X"，底部单列 App 缺口。
- **门禁**：`tests/test_r901_capability_matrix_rendered.py`（5 条真渲染）。
- **截图**：`docs/screenshots/console-dims.png`（已进 README）。

### ④【P1】拓展即漏三修
| 缺陷 | 修法 |
|---|---|
| `SRX_PLAT_ORDER.filter(...)` 当过滤集 → App 结果永不显示 | 集合用 `Object.keys(channels)`，顺序用 `SRX_PLAT_ORDER.indexOf`（未知排 99） |
| 渠道覆盖分母写死 `/5` → 7/5 超界 | 用 `SRX.plats.length` |
| 文案「五渠道/五平台/四渠道」 | 改"所选渠道/全部渠道/各渠道"或按数量动态拼 |

- **门禁**：`tests/test_r902_no_hardcoded_channel_count.py`（3 条，剥注释后只扫用户可见文案）。

### ⑤ 多程如实标注
- 去哪儿 App 有「单程/往返/多程」三档入口，但采集未接 → 矩阵维持 `n`，`DIM_TIP` 写明"App 有入口，采集未接"。

---

# 第五部分 · 未达成 / 待办（P0→P3）

## P0 · 让树稳定并跑全量（阻塞发版）

```bash
# 等并行会话停手：连看两次 mtime 相同且 ≥5 分钟
python -c "import os,time;print(time.strftime('%H:%M:%S',time.localtime(os.path.getmtime('webui.py'))))"
md5sum webui.py | cut -c1-32 | tee _scratch/_h1.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONIOENCODING=utf-8 \
  python -m pytest tests -q -p no:cacheprovider > _scratch/_full.log 2>&1
md5sum webui.py | cut -c1-32 | diff - _scratch/_h1.txt && echo HASH-STABLE
```
- 全绿 → P1。
- 剩 4 条 → **按新意图改门禁**（不是回退实现）：
  - `test_r366`：改成守"收起态说明不可见"的行为。
  - `test_r536b`：先量实际几何，再决定改断言还是改实现。
  - `test_v1555`：把"内联 padding"改成守"卡体左右内衬 16px"。

## P1 · 发版 v1.5.307（严格按 `docs/HANDOFF_GUIDE.md` §5）

1. 单次「初版」提交；`Co-authored-by` + **贡献者以 author 身份**的提交。
2. 推送用 `_scratch/api_push.py`。
3. 用**推送后的 SHA** 触发 `release-build.yml`（`workflow_dispatch` + `push_image`）。
4. 四平台包校验：根布局、无 `config/data/logs/user_data/ghtoken`、`--version`、SHA256。
5. Release **名称恒定**「机票监控台 · 初版（滚动更新）」，版本只在正文。
6. 演示站按**已发布树**重烘；`code:` 戳 = 该 SHA 的 `webui.py` 前 12 位。
7. `python docs/release_align_check.py` 到 PASS。

## P2 · 能力线剩余缺口

| 优先级 | 项 | 判定方法 |
|---|---|---|
| **已补齐** | `app_qunar.calendar/low_fare` | 2026-11-02 真机、已登录：低价机票落原生 RN 页（QReactNativeActivity1），low_fare 41.2s 出 14 天；整月日历也带逐日价。已改 y，并写 `path_note("日历","calendar")`。 |
| 中 | 浏览器往返：携程 PC（国内/国际）、去哪儿 touch（仅国内）、同程（国内 + 登录后 PC 国际 `ts/list`）、途牛（国内 `listFlight` + 国际 H5 `queryFlight` `avgTotalPrice`，SHA→NRT 35 条 ¥3010）。去哪儿国际仍待通路恢复（表单可提交，`touchInterList` 1999 软频控）；飞猪仅国际、去哪儿仅国内 | 绝不能两段单程相加 |
| 中 | `multi_city` 全 ""；携程 PC 已有 `fetch_multi` + 轮尾采集 + 只读 `/api/multicity`，缺配置入口/结果面/推送 | 其余渠道仍缺整条链路；矩阵解锁前先做结果面与配置入口 |
| 低 | 能力对照卡 320 档 | 目前只验了 430/900/1512 |

## P3 · 收尾

- 发版前跑 `release_align_check --local`；README/EN 的 tracked 计数必须与干净树实收一致，未跟踪测试不得计入。
- `docs/HANDOFF_GUIDE.md` §0「当前差距」段已过期，发版后更新。
- 清理 `_scratch/` 中间产物（不进仓库）。

---

# 第六部分 · 必须守护的不变式（9 条）

1. **`y` 必须有代码证据**；`""` = 未验证（界面灰化），**绝不等于支持**。
2. **`n` 必须有显式不支持分支**（`path_note(..., "unsupported")` + 不发起真实查询）。静默忽略参数 = 假数据。
3. **low_fare 两表互为镜像**（`CHANNEL_DIMENSIONS` ⇄ `SPECIAL_CAPABILITY`）→ `test_r900`。
4. **App 对齐基准 = 「任一浏览器渠道已具备该维度」**，不是某一家友商（按单家判会自证：携程自己 `round_trip` 未验证）。
5. **用户可见文案不得写死渠道/源数量** → `test_r902`（注释不算）。
6. **渠道集合由数据决定，顺序才用固定表**。
7. **每个已注册渠道 × 每个维度都要有声明** → `test_r677`。
8. **配置页不得有"看不见的配置"**；需重启的要说清；能热更新就热更新。
9. **测试不得含本机路径**。

---

# 第七部分 · 经验（本会话真实踩过，按杀伤力排序）

## 7.1 【最坑】门禁锁住的是「旧的正确形态」

我按新意图改实现后旧断言立刻红。典型：
- `test_v284` 断言 `SRX_PLAT_ORDER.filter(p=>(lg.channels||{})[p])`——那正是我要修的缺陷写法。
- `test_channel_links` 断言 `set(ch) == {五家}`——App 接入后必红。
- `test_v15273` 断言"五渠道合成演示行"——我改成"全部渠道合成演示行"。

**定式**：先判断断言守的是**行为意图**还是**源码写法**。
- 守写法 → 改成守意图（**更严不更松**：`>=5` → "浏览器五家必须在 + 注册表全覆盖"）。
- 若旧断言锁的正是本轮要修的缺陷 → 改写断言 + 补「缺陷字面值不得回潮」的反向断言。

## 7.2 「值变了」≠「设计坏了」，但也不能借机放宽守卫

我曾把"渠道集合恰好 5 家"放宽成 `>= 5`——那是**放弃守卫**（任何回归都绿）。正确：意图不变、度量换、并加强。

## 7.3 【最高频】并行会话随时改同一批文件

实测：一个跑测周期内 `webui.py` 被改 **6 次以上**，结论多次作废。

**铁律**：
- 跑长门禁前后各存 `md5sum`；不一致 → **结论作废重跑**。
- **绝不** `git checkout -- webui.py`（历史实测丢过别人 86 行）。
- **绝不** `git add webui.py`（会吞掉别人上千行）；只按 hunk `git apply --cached`。
- 单跑失败项：通过 → 并发/时序假失败；仍红 → 再看断言。

## 7.4 判据本身要先被证明有效

- `test_r516` 断言"26 小时前样本判 stalled"——库被刷新成 55 分钟后就红，而 `advise()` 门槛是 **6 小时**，实现正确。**改法：从库里读实际年龄再分流**。
- 幽灵令牌门禁只认 CSS 声明，漏了 JS `setProperty('--hdh', …)`。**改法：JS 设置也计入**。
- `test_r902` 我一度把「四源」扫进来——它是**视图名**（four 视图），立刻假红。**改法：排除并写明理由**。

→ **定式：任何否定式/存在式断言，先喂一个已知会失败/会通过的样本，证明它真能分辨。**

## 7.5 进程被自己杀掉：`/api/restart` 会 `os._exit(0)`

`test_r672` 端点普查真打 `/api/restart` → spawn + `threading.Timer(1, os._exit(0))` → **整个 pytest 在 61% 处静默死亡**（日志只剩一个 `F`，无 traceback）。
**修法**：排除该端点的同源真打，但**断言它仍在清单里**（防"连缺陷一起排除"）。

## 7.6 无 body 的 POST 被 415 打哑

`fetch(path,{method:'POST'})` 不带 body 时浏览器自动补 `text/plain`；13 个写端点各自抄了"不是 JSON 就 415" → 一批按钮点不动。
**修法**：判据收成单源 `_json_body_ok()`（只有 `Content-Length>0` 才要求 JSON）。
**注意**：跨站防护仍由 Origin 闸门承担，**不要**因为放宽 Content-Type 就把 CSRF 也放宽。

## 7.7 UI 必须亲眼看，别只信断言

能力矩阵第一版：功能全对、几何全对、**视觉是错的**——`<th>` 继承全局表格样式，维度列带一整块灰带、右缘多出一截。
→ **凡 UI 改动，必须截图亲眼看**；而且要看到"最丑的那一档"（窄屏/空态/超长文本）。

## 7.8 全局替换会漏，门禁会抓到你

我改了一批「五渠道」，`test_r902` 立刻抓出**我漏掉的 2 处**（校准册标题、meta description）。
→ 不要因为"我刚改过了"就跳过门禁；**它存在的意义就是抓这个**。

## 7.9 文档里的数字会过期，写的时候就要能自证

`docs/HANDOFF_GUIDE.md` 曾把 App 渠道写成"智行、美团"——**错**。我写本文时逐条核对，初稿把门禁数写成 27（实测 54），已改。
→ **写进文档的每个数字，都要有一条可执行命令能复现它**。

## 7.10 会话很长，上下文会被压缩

靠三样东西续命：① 代码注释（写"为什么"）；② 门禁（把结论钉成可执行断言）；③ 交接文档。
→ **不要**把关键结论只留在对话里。

---

# 第八部分 · 工作方法（照做）

## 8.1 改一个缺陷的标准流程

1. **先复现**（最小脚本，确认现在确实失败）。
2. **定位根因**（例：途牛往返不是"没返回数据"，是"返回了错的数据"）。
3. **改实现**（不是改门禁）。
4. **补门禁 + 做负控**（撤掉修复→红；恢复→绿）。
   - 负控常见假 NO-FIRE：变异没打中守卫真读的对象、断言恒真、探针与门禁不同服务模式。
5. **单点 → 相关文件 → 全量**（存哈希）。
6. **UI 改动额外截图**。

## 8.2 遇到红灯的判断树

```
红灯
├─ 单跑该文件 → 通过？
│   ├─ 是 → 并发/时序假失败（并行会话改文件、端口冲突、共享夹具被覆写）
│   │        → 存哈希重跑；确认后才写"通过"
│   └─ 否 → 看断言守的是什么
│            ├─ 源码字面量（旧实现写法）        → 改成守意图
│            ├─ 行为意图，实现确实坏了           → 改实现
│            └─ 行为意图，且是"用户裁决的取舍"   → 改方案或改度量，不动产品
└─ 整片 0 test / Failed Suites → 你的编辑坏了文件（标签闭合/花括号配对），别读断言
```

## 8.3 多会话协作

- **冻结才发版**：连看两次 mtime 相同 ≥5 分钟。
- **只提交自己的 hunk**；提交前核 `git diff --cached --stat`。
- **公共资源**：不杀别人进程（先看 CreationDate + 命令行）；不写别人正打开的 sqlite；写配置的探针**必须用临时副本**。

## 8.4 写门禁的硬要求

- 守**行为**不守**实现**；能渲染就渲染。
- **剥注释**再扫（`re.sub(r"/\*.*?\*/", "", src, flags=re.S)`）。
- **别用字符窗口当锚**，用结构边界（`src.index("\nfunction ", i)`、下一个 `elif self.path ==`）。
- 有下限断言（"至少扫到 N 个对象"），防止判据空转。
- 新门禁必须登记进 `docs/EXECUTION_SPEC_LATEST.md`。

---

# 第九部分 · 关键文件速查

| 文件 | 作用 |
|---|---|
| `webui.py` | 单文件服务端 + 整个前端（`PAGE`）。**并行热区，改前看 mtime** |
| `core/channels.py` | 渠道单源：`BROWSER_CHANNELS`/`APP_CHANNELS`/`CHANNEL_CN`/`CHANNEL_DIMENSIONS`/`DIMENSIONS`/`PATH_CN`/`APP_BROWSER_PEER`/`browser_supported`/`app_alignment_gaps` |
| `core/specials.py` | 特价发现源：`SPECIAL_CAPABILITY`、`SRC_*` |
| `core/special_radar.py` | 雷达取数：`_ctrip_deals`/`_tuniu_deals`/`_tongcheng_deals`/`_qunar_deals`/`_app_qunar_deals` |
| `core/login_slots.py` | 6 浏览器槽位 + App 槽位、`TUNIU_LOGIN_URL`/`CTRIP_LOGIN_URL` |
| `core/pacing.py` | 节流/健康建议 `advise()`（`stalled` 门槛 6h） |
| `crawlers/app_base.py` | App 基类（`supports_round_trip` 闸门、`prepare_device`、`path_note`） |
| `core/android/` | App 渠道基础设施：`login_api.py`（`/api/app-login/*` 分发）、`login_session.py`、`snapshot.py`、`device.py`、`runtime.py`、`mumu.py` |
| `tests/conftest.py` | 全局隔离（推送账本/报告状态/探针证据/代理/`_pretend_graphical`） |
| `tests/font_probe.py` | `has_cjk_font()` 真检查汉字字形 |
| `docs/EXECUTION_SPEC_LATEST.md` | 执行规范（**新门禁必须登记**） |
| `docs/HANDOFF_CAPABILITY_MATRIX.md` | 能力一致性专项 |
| `docs/HANDOFF_GUIDE.md` | 发版七步与文档门禁体系 |
| `docs/release_align_check.py` | 发版对齐自检 |
| `docs/demo_build.py` | 演示站烘焙 |
| `docs/uitest.py` | 668 条 UI 自检 |
| `_scratch/api_push.py` | Git Data API 推送 |

**API 端点全表**（改 HTTP 处理时对照）：
`/api/{state,config,health,pulse,run,preview,push,pushlog,restart,open-folder,login,login-finish,login-state,login-verify,app-login*,challenge/{open,verify,skip},channel/{probe,verify,warmup,selfcheck,dims},pacing,pacing/reset,probe/{start,cancel,search},special-radar,specials,srx/watch,test-{push,bark,email,imghost,ntfy,toast}}`

---

# 第十部分 · 验证清单

```bash
# A. 能力线（改渠道/能力/文案时）—— 当前 54 passed
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONIOENCODING=utf-8 python -m pytest \
  tests/test_r677_channel_dimension_matrix.py tests/test_r683_channel_dims_surface.py \
  tests/test_r674_app_channel_unified.py tests/test_r700_zhixing_round_trip.py \
  tests/test_r701_qunar_round_trip.py tests/test_r900_low_fare_single_truth.py \
  tests/test_r901_capability_matrix_rendered.py tests/test_r902_no_hardcoded_channel_count.py \
  -q -p no:cacheprovider

# B. 安全闸门（改 HTTP 处理时）
python -m pytest tests/test_r671_writes_reject_cross_site.py \
  tests/test_r672_no_write_endpoint_blocked_by_our_guard.py -q

# C. 配置可配性（改配置项时）
python -m pytest tests/test_r601_every_config_key_reachable.py \
  tests/test_r634_every_pacing_key_configurable.py -q

# D. UI 真渲染（任何界面改动）—— 期望 668/668
python docs/uitest.py

# E. 并发全量（发版前）
python tools/test_all.py --workers 8
```

**每次都要做**：① 存 `md5sum webui.py`；② 看是否有新红灯属于我；③ UI 改动截图。

---

# 第十部分之二 · 贯穿全程的方法论（最可复用的部分）

## M.1 数据诚实优先

**任何"结论"都要先问：证据是什么？分母是什么？口径是什么？**

| 错误类型 | 实例 | 正确做法 |
|---|---|---|
| 把失败包装成业务结论 | 请求失败 → 记「无票」 | 必须记 `error`，保留现场 |
| 门拒当会话失效 | 444 → 提示重新登录 | `soft_reject`，不触发退避 |
| `—` 混作「没有」 | 无样本显示 0% | `—` = 无样本；0% 要有分母 |
| 合成数据标成正常 | demo 显示「正常」 | 必须标注「演示」且不染色 |
| 谎报成功 | 起线程即回"已弹出" | 到达可观测状态才算成功 |

## M.2 判据先行，再谈实现

写门禁 / 写测试前，先回答：**这个判据能抓到真实缺陷吗？**

- 门禁 **必须做负控**（注入错误 → 必须变红 → 还原）
- 负控不红时，先怀疑 5 件事：字符串多处出现 / 大小写 / 读错行 / 散文 vs 表格行 / 打错文件
- **「找不到要检查的东西」必须报错**，不能当成绿灯

```python
import hashlib, os, pathlib, subprocess, sys
p = pathlib.Path("docs/XXX.md")
orig = p.read_bytes(); d = hashlib.md5(orig).hexdigest()
tmp = p.with_name(p.name + ".mut")
tmp.write_bytes(orig.replace(b"OLD", b"NEW")); os.replace(tmp, p)
try:
    r = subprocess.run([sys.executable,"-m","pytest","-q","-p","no:langsmith_plugin",
                        "tests/test_docs_code_contract.py::test_xxx"], capture_output=True)
    print("RED" if r.returncode == 1 else "NO-FIRE")
finally:
    tmp2 = p.with_name(p.name + ".bak"); tmp2.write_bytes(orig); os.replace(tmp2, p)
assert hashlib.md5(p.read_bytes()).hexdigest() == d, "还原失败！"
```

## M.3 并行会话是环境事实，不是异常

- `webui.py` 可能 45 秒内被改 3 次
- **绝不** 整份暂存 `webui.py`（会吞掉别人的未提交改动，实测丢过 1147 行）
- **绝不** 对它用 `git checkout/restore`（不可恢复，丢过 86 行）
- 发版前必须确认静默 ≥3 分钟

## M.4 组件会消失，文档会滞后

- 文档描述的 UI 组件可能已经不存在（如「控制台路径行」）
- 门禁可能**钉死一个已消失的组件**（硬要求某句必须存在）
- **改一处必须全文 grep 同一概念**

## M.5 数字要么带口径，要么换成形态

- 反例：「825 条 / 93.7%」没写统计范围 → 换口径就是另一组数
- 反例：途牛「286 行」天天变 → 改用 `count(*) == count(distinct fetched_at)`
- 数字比较要**带容差**（并行会话持续微调）

## M.6 用户会否决方案形态

用户会直接说「这个形态不行」，此时**不要辩解，改形态**。
案例：「节流面板放全局参数格格不入」→ 搬进健康卡；「关注航线走势这名字不对」→ 改叫「航线走势」；「搜索不该全文搜」→ 只搜指定字段。

---

# 第十部分之三 · 与用户协作的规矩

| 规矩 | 说明 |
|---|---|
| **先给证据，再下结论** | 「我认为修好了」不算；要 `命令 + 输出 + 行号` |
| **不夸大完成度** | 部分完成就说「部分完成」，列出缺什么 |
| **方案形态被否就改形态** | 不要辩解"这样也合理" |
| **不许把当次快照当现状** | 文档里的数字必须带时间戳/口径 |
| **发版前必须问** | 历史重写、强推、移动 tag 都要显式授权 |
| **不确定就问，不要猜** | 例如"删这行会不会破坏别的"——先 grep 再说 |
| **交接要能自证** | 每份交接文档都要能被门禁检验 |

### 本会话中被否定过的做法（**推论，非用户逐字否决**）

> ⚠ 下面几条是**我从反馈里归纳出的规律**，不是用户逐字说过的"否决"。
> 它们成立是因为每次这么做都被打回，但我没有原句可引。

- 「建议登录」这种模糊策略 → 每次都要求改成 required 或 not required
- 把节流面板放在「配置 · 全局参数」→ 被指"格格不入"后搬进健康卡
- 在 README 加 Contributors 章节 → 与 GitHub 自带能力重复
- 用「供给重合 / 项目底线」否决渠道评估 → 应只给技术可行性与实测代价
- 拿旧的「已放弃」当现在的结论 → 状态会变，旧结论不可当现状

---

# 第十一部分 · 总纲

> **这个项目最贵的资产不是功能，是「它说的话可以信」。**
> 任何让这句话不成立的改动——静默吞掉参数、把未验证写成支持、
> 在文案里写死数量、为了让门禁变绿而放宽断言——都比少一个功能严重。
>
> 你接手时：先花 10 分钟核验现场（§3.3 的矩阵 + §3.2 的红灯），再动手。
> 你的第一件正事不是写新功能，而是**让这棵树重新变绿并把它发出去**。
