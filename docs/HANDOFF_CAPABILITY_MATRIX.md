# 交接指导书 · 10 渠道全维度能力一致性（r900–r903 专项）

> 2026-11-02 新增 `app_tongcheng` / `app_ctrip` / `app_fliggy` 三个**额外可选** App 渠道：
> 同程 App 国内单程已冷启连续两次 + 双日期复验（6 行/26.0s/16.8s/23.8s）；
> 另接原生「价格日历」为逐日低价源（2026-11-02 SHA→PEK 14 天 ¥450/350/…/15.8s，
> 雷达 `app-calendar ok`），`calendar/low_fare` 升 y；
> 飞猪 App 固定竖屏 + Windows OCR，国内单程连续两次两条航线跑通（各 4 行，44.8s/48.5s）；
> 连续自动化会触发「访问被拒绝」，采集端记 blocked 停手、需人工恢复；
> 携程 App 修复「选择目的地」城市页判据后，SHA→CAN 连续两次 32/33 行（11-18 ¥480 / 11-19 ¥490），`domestic/detail` 升 y；
> 价格日历 OCR 真机连续两次 61 天（国内 SHA→PEK）且国际档 SHA→NRT
> 连续两次 54/53 天（¥864–1530，11-10 查价；两月视野），`calendar/low_fare/intl` 升 y，国际单程明细 38 条 ¥935 已复验。
> 国际/国内往返均已真机端到端（国际 SHA→NRT 8 条 ¥2146；国内 SHA→PEK
> 5 条 ¥760，返程 14:00→16:30 +¥0），`round_trip=y`；返程栏晚一帧时
> 解析前最多等 10s。
> 不再另立「7 家稳定基线」：10 家状态以 `docs/APP_CHANNELS.md` 与
> `core/channels.py` 为准；当前能力矩阵与 11 轴契约按 **10 家**
> （5 浏览器 + 5 App）统计。
> 同程 App 国际价格日历也已连续两次 SHA→NRT 14 天 ¥882–1495
> （`app-calendar ok`），`intl=y`（国际日历 + 单程明细 6 条 ¥875，实付价取最低）。
> 同程 App 国际往返 2026-11-03 真机打通（上海⇌东京 11-16/19，7 条去程、
> 最低 9C8515 ¥2209 含税总价，返程 9C6218 +¥0；`+¥N` 是加价不相加），
> `round_trip=y`（仅国际）；旧「查询落营销/示例页」结论是首访教学浮层遮挡误判。

> **这份文档写给**：接手继续这项工作的下一个会话。
> **三份交接文档的阅读顺序**：① `docs/HANDOFF_FULL_SESSION.md`（全会话总览，先读）→ ② 本文（能力一致性专项）→ ③ `docs/HANDOFF_GUIDE.md`（发版与文档门禁体系）。
> **本轮（2026-11-03）完整经验书**：`docs/SESSION_EXPERIENCE_GUIDE_2026-11-03.md`（本轮全部目标/期望、CI 并发与多程开口程改动、证据、判据陷阱、操作手册、未完成清单）；与本文冲突时以现场实测为准。
> **与另一份文档的分工**：`docs/HANDOFF_GUIDE.md` 讲**通用**（发版流程、文档门禁体系、操作纪律）；
> 本文讲**本轮这条线**——「10 渠道（5 浏览器 + 5 App）全维度能力一致 + 特色能力可独立识别/聚合 + 后续可拓展」，
> 包括为什么这么改、哪些坑是真的、还剩什么、怎么验证。两份都要读，**本文优先看 §2 的现场核验**。
> **编写时间**：2026-10-31 20:00。文中每个数字都来自实测，但**开工前必须自己再核一遍**。

---

## 0. 一句话现状

10 家渠道（5 浏览器 + 5 App）× 7 个维度的能力矩阵**已从「只活在源码里」变成「界面上一张表」**，
并修掉了「单程价冒充往返价」「同一件事两张表结论相反」「同一键写两遍、后者静默覆盖前值」三类诚实性缺陷。
**2026-11-03 22:51 全量实测**：tracked collect **6493**（0f782f9 基线 6394 + r920 2 / r921 10 / r922 14 / r923 12 / r924 56 / UI shard 5）；本地 clean `8a69a1a` 全量 **6465 passed / 19 skipped / 0 failed**（602.73s，6484 口径），r924 补 9 项定向 76 passed；CI **4 测试片 + 2 UI 片**在 `8a69a1a` **全绿**（test 264/310/206/278s、UI 224/189s、ci-ok success，整轮 6m11s）；本地 clean `90b2154` **6440 passed / 44 skipped / 0 failed**（workers 8，419.64s，6484 口径）；CI 在 `90b2154`（docs HEAD）亦全绿；`0f782f9` 全量 **6375 passed / 19 skipped / 0 failed**（workers 8，608.29s，6394 口径，源码哈希 pin 通过）；CI 同款 4 片并发在 `62888c4`/`47731c9` 上 **6230 passed / 44 skipped / 0 failed**（四片合计 6274，此后新增开口程就绪轮询/链头断点测试 4 项由本次全量覆盖）；CI 已改为 4 runner 分片，`tools/ci_shard.py --stats 4` 自检并集+workflow 一致性，新增文件按 20s 自动进组；矩阵升 y、r958 配置控件与门禁修复均在其内（含 r926 同程 PC 国际往返、r927 途牛 H5 国际往返、r930 多程解析器、r931 矩阵窄档、r932 实际渠道错峰、r933 多程存储层、r934 多程配置/调度隔离、r938 Qunar 假票价守卫、r939 软拒诊断、r941 日桶下限、r942 携程多程解析、r943 轮尾采集/只读 API、r944 配置卡/概览整单卡、r946 来源页可溯源、r947 过期首段不提醒、r951 整单历史 sparkline、r953 CSV 导出、r956 矩阵 ctrip 多程 y/仅 2 段，以及 Release 正文 8 条门禁——采集面/往返范围逐行与矩阵同源）**2026-11-03 19:30 画中画**：App 登录从 520px 弹窗改为近全屏工作台（专注/可拖动浮窗/内联输入/设备 info），共享关闭停轮询；真渲染 1512/390 尺寸与浮窗/专注/输入/tap/swipe、浏览器弹窗 520 隔离、零 pageerror；App 图标独立 `.bic-app` squircle，智行去促销横幅，PiP 标题带 22px 官方图标；UI **670/670**。
能力线 9 文件 **63 passed**（含 r903/r905）、`python -m core.channel_contract --strict` **10 家 × 11 轴无缺口**、
UI **670/670**（2026-11-03 16:50 全量复跑，零 JS 错误；页面 JS 为最终态，此后仅服务端
label/提醒改动由全量 pytest 覆盖；含矩阵 ctrip 多程 ✓ 仅 2 段与 r958 的 9 个配置控件；含 r946 多程来源链接与 r947 过期门；矩阵含携程 App round_trip=国内/国际、同程 App intl=日历/明细、同程 App round_trip=国际；r901 新增 390 档冻结首列 + 900 档无假提示真渲染；含 r905 行内自检按钮，另由 r905 真渲染 + r640 四档行高覆盖）、
`release_align_check.py --local` **25/25 PASS**（2026-11-03 22:57，clean 克隆 `8a69a1a`，tracked 6484 / UI 670）、站点戳 `code:db416c15fca7` = 当前 `webui.py`（2026-11-03 21:24 重烘并随 `0f782f9` 推送）。
**2026-11-03 21:12 在线复核（Release e65cee1 / v1.5.307）**：tag `v1.0` → `e65cee1`
（09:54 由 `ab04c22` 重指，多 4 个提交）；Release 正文源码 `e65cee1`；CI/release-build/Pages
在 `e65cee1` 均 success；ghcr `sha-e65cee1` = `latest` digest `5fb025bb3488…`（**同 digest**），
`sha-ab04c22` 仍可拉取（digest `9b72acb1a6b9…`）但已不对应 Release；公开站点戳
`code:db416c15fca7` 来自更新后的 main（release 树 webui 为 `6c85a00f14c1`）；
**资产缺口**：`e65cee1` 四平台包构建早于 numpy 依赖声明，冻结包内滑块缺口检测
会静默无候选；下一次发版必须按最终 `requirements.txt` 重建四平台包并重算 SHA；
0 open issues / 0 open PRs。Release 正文/资产/tag 已同源。
**发布状态**：Release `v1.0` → `e65cee1`（10 渠道正文，四资产 digest 4/4）；
live 8765 已于 2026-11-03 08:58 切到 `_release_ab04`（`ab04c22` 树，PID 47952，webui sha12
`6c85a00f14c1`，`/api/channel-dims` 10 家）。r933–r935 的源码增量尚未入该树。

### 历史记录（2026-11-02 01:52 预发布；数字非当前）
**发布提交前**：README/EN 的跟踪计数要改成 **5885**、UI 自检 **670**（当前 5443/668 是
HEAD 的 tracked 口径；提交后 `release_align_check --local` 读的是新口径）。单根提交彩排
（临时 index，未动真实 index/HEAD）为 1012 文件 / 807 测试文件、无敏感产物，
`webui.py` blob 与站点戳一致（`37569225` / `4564d69bf4cf`）。
**计数门禁修正（r813j）**：`release_align_check.py` 的 `git ls-files` 改用 `-z`
（NUL 分隔、不做 quotePath 转义）——中文测试名 `tests/test_r643_干预覆盖每个可见渠道.py`
原先被包成 `"tests/test_…"`，`startswith("tests/test_")` 把它过滤掉，tracked 计数少 2
（HEAD 真实 **5445**、README 旧值 5443；提交后 **5885**）。彩排树装修复后才应到 25/25。
**发布候选（r813k，2026-11-02 01:52）**：最终 root commit **`6302bde`**（tree **`17b586bc`**，
1012 文件、0 parent），README/EN **5885**、UI **670**、修复后的计数检查器在内；
该树 `release_align_check --local` **25/25 PASS**。候选生成时主工作树与 `17b586bc` 同树
（README/EN 5885/670、检查器已修）；之后仅改了本交接/规格等内部文档（不参与 25/25
公开面检查）。主树 HEAD 仍是旧提交，pre-commit 的计数检查会算 HEAD tracked 5445 而
README 5885（预期）；正式提交以**当前树**为准，提交后重跑 `--local` 复核。
**在线对账网络层修正（r813l）**：本机 Python/OpenSSL 无 CA bundle，api.github.com
校验失败（curl/Schannel 正常）。`gh()` 与 SHA256SUMS 改走 curl（`--config -` 从
stdin 读 token，不关 TLS 校验）；Pages/ghcr 仍用 urllib。实测 tag v1.0 / 5 资产 /
4 行 sums 可读。**发版前预跑**：在线 audit 在冻结前是预期红（工作树 dirty、HEAD
tracked 5449 vs README 5885、HEAD UI 668 vs 670、线上 Release/tag/site/CI/ghcr
不同源）；必须冻结 24a5、重跑 4w、按最终 tracked 重算计数并改 README/EN/UI、
重建候选，提交后复验。
**在线 audit 实测（29/46，2026-11-02 02:01）**：线上正文 intro/version 仍 1.5.306、
Pages 部署 11 个、站点戳 2a326e3c 旧树；**正文 SHA 只与 win64 当前资产一致，
另外 3 个 zip 的 API digest 不在正文**（正文/资产漂移）；source/tag/CI/release-build/ghcr
均不同源；live 8765 1.5.307 通过。SHA256SUMS 资产 URL 经本机代理 502（API 正常）；
下载失败时用 release API 的 `digest` 对正文做明确标注的回退校验。发版须重建正文+四资产、
prune Pages 到 1、重烘站点、CI/release-build 绿、ghcr 新 SHA，再在线对账全绿。
**r813k 门禁**：`tests/test_r813k_release_tooling.py` 3 条——`git_z` 保留中文测试名、
curl 不关 TLS 且 `--config -` 从 stdin 读头、`_digest_fallback` 能检出正文/资产漂移；
连同文档契约 **96 passed**。新增 3 条后发布计数必须在冻结后的全量门禁重算
（预计 tracked **5888** / passed **5872** / UI **670**，以最终 collect 为准），
README/EN/release notes 同步；候选 `6302bde` 需重建。

> **2026-11-01 r813 增量**：新增 `core/channel_contract.py`——把用户点名的
> 11 条平台质量轴（可配置/可观测/可干预/可见性/可溯源/可识别/可区分/可幂等/
> 语义清晰/可指导/可判断）做成**对真实登记点的求值**，10 家 × 11 轴当前 0 缺口；
> 同时修掉「智行低价雷达入口被旧白名单挡住」——r732 已接入源，但 `_CHANNELS`
> 与前端 `SRX_RADAR_APP_KEYS` 没跟上，请求里的智行被静默丢弃。见 §9b。
> **r813d 再收口**：演示诊断卡丢两家 App、App 卡「自检」报未知渠道、批量自检
> 把 App 跑两遍、轮日志/雷达/推送的 App 裸 id、同班覆盖分母 `/5` 一并修掉；
> `pacing`/`health_diag`/`channel_links`/`crawlers` 的渠道清单改成同一份对象。
> **r813f**：恢复 7 张诊断卡后暴露的定列缺口（900/768 会 3+3+1 落单）已补
> `[data-n="7"]` 列数与卡头/登录行定高，6 档真渲染门禁在 `test_r813d`。
> **r813i**：主动探针 `#srxPlatPick` 原本只有 5 个浏览器 chip（后端早已接受
> 7 家）；补两款 App 的官方图标紧凑 chip（默认不勾、title/aria 点明真机），
> 选择器单行横滚以保住「探针一行」；契约的「可见性」轴新增「主动探针」一面。

---

## 1. 本轮到底改了什么（按价值排序）

### 1.1 【P0】途牛往返「静默串味」——单程价冒充往返总价

**缺陷**：`crawlers/tuniu.py::fetch()` 收到 `ret_date` 时，**只用它跳过 PC/token 路径**，
最终仍按单程采集并返回。`_hoop(fc,tc,date)` 从不带返程日，国际分支自述「RT 语义 v1 未接」，
全程**不记 `TRIP/unsupported`**。后果：勾了往返的航线，途牛返回的是**单程价**，
推送和走势把它当往返总价报警——直接违反「宁缺勿错」。

**修法**（`crawlers/tuniu.py`，与 `ctrip.py` 同律）：`ret_date` 在场即记
`path_note("TRIP","unsupported")`、warning、`return []`，**不发起单程查询**。

**验证**（必须能复现这三行）：
```python
from crawlers.tuniu import TuniuCrawler
c = TuniuCrawler.__new__(TuniuCrawler); c.name='tuniu'; c.paths=[]; c.logger=logging.getLogger('t')
c._fetch_intl=lambda *a,**k: (_ for _ in ()).throw(AssertionError('不该被调用'))
out = c.safe_fetch('SHA','BKK',['2026-11-01'], ret_date='2026-11-05')
# 期望：out == []，paths 里有 ('TRIP','unsupported')
```

**连带**：`core/channels.py` 里 `tuniu.round_trip` 从 `""`（未验证）改成 `"n"`（明确不支持）。
不要改回 `""`——`""` 在界面上显示为「未验证」，会让用户以为「再试试可能行」。
**r769 后续更正**：国内 `listFlight` 两段 segment 的返回价即往返总价，国内已改 `y`
（见 §4 与 `DIMENSION_SCOPE`「仅国内」）；当时判断国际产品结构仍是单段、保持 `n`。
**r927 订正（2026-11-03）**：国际 H5 `queryFlight` 两段 segment 的
`productList.avgTotalPrice` 已实测接通（SHA→NRT 35 条、最低 ¥3010），
`tuniu.round_trip` 已覆盖国内/国际、`DIMENSION_SCOPE` 不再写「仅国内」；
上面 `safe_fetch` 期望的 `('TRIP','unsupported')` 只适用于 r769 当时，
现在应走 `_fetch_intl_rt`。

### 1.2 【P0】low_fare 两张表互相矛盾

**缺陷**：同一件事写了两份、结论相反：
- `core/channels.py::CHANNEL_DIMENSIONS[p]["low_fare"]`（渠道能力矩阵）
- `core/specials.py::SPECIAL_CAPABILITY[p]["sources"]`（特价雷达的真实发现源）

当时的矛盾：携程/同程/途牛矩阵写 `""`，但 `core/special_radar.py` 里
`_ctrip_deals` / `_tongcheng_deals` / `_tuniu_deals` **都是真能出数的源**；
去哪儿矩阵写 `y`，雷达却写 `sources: []`（注释「lowFlight 缓采」）。

**修法**：
1. `core/specials.py` 新增 `SRC_QUNAR = "qunar"`、`SRC_TONGCHENG = "tongcheng"`，
   并加进 `_KNOWN_SOURCES` 与 `_SRC_LABEL`；把这两个渠道的 `sources` 按实现补齐
   （去哪儿＝官方 H5 低价日历自签名；同程＝H5 低价日历 90/180 天窗口）。
2. `core/channels.py` 把 `ctrip / tongcheng / tuniu` 的 `low_fare` 改为 `y`。
3. 新增门禁 `tests/test_r900_low_fare_single_truth.py`（3 条）钉住两表互为镜像。

**边界（别搞错）**：
- 智行 App 的「特价」页**已接入**（r732 真机复核：设城市 + 日期区间 →
  逐天一条最低价，`core/special_radar.py::_app_zhixing_deals`），矩阵
  `low_fare=y`。早期把它记成「目的地低价榜」是认错了入口（把首页
  「省钱攻略」的推荐卡当成了特价档），已更正。
- 门禁要求「没源的渠道必须写明 note」，所以别为了省事把 note 删空。

### 1.3 【P1】能力矩阵搬上界面（对应目标：特色能力可独立识别或聚合）

**缺陷**：`/api/channel-dims` 早就存在且返回完整矩阵 + App 缺口，但**前端 0 处调用**
（全仓 grep 只有测试引用）。用户只能一家家点开猜「这家支不支持往返」。

**修法**（全部在 `webui.py`）：
- 配置页「渠道登录」tab 里、`#sec-chlinks` 之后新增 `#sec-dims`「能力对照」卡。
- JS：`DIM_CN` / `DIM_TIP` / `DIMS_DATA` / `loadChannelDims()` / `renderDimMatrix()` / `dimCell()`。
- 渲染形态：**行＝维度、列＝渠道**，每格三态（`✓` 支持 / `×` 不支持 / `?` 未验证），
  App 列头下标「同源 携程/去哪儿」，卡片下方单列「App 相对浏览器端仍缺：…」。
- 挂载点：`loadChannelState` 尾部，`if(typeof loadChannelDims==='function'&&$('cfgDimMatrix')&&!DIMS_DATA)`。
- 样式：`.dimtbl` / `.dimwrap` / `.cell.y|n|u` / `.dimlegend` / `.dimgap`（在 `.lgcard .btn2` 之后）。

**踩过的坑（务必别重犯）**：
1. **前端没有 `CHANNEL_CN`**——那是后端表。渠道中文名用接口返回的 `c.name`。
   我第一版写了 `CHANNEL_CN?.[plat]`，直接在页面上抛 `CHANNEL_CN is not defined`。
2. **`<th>` 会继承全局表格样式**（灰底 + 内衬），实拍里维度列带着一整块灰带、
   右缘比数据列多出一截，读作「两套表格拼在一起」。必须
   `.dimtbl th{background:transparent!important;box-shadow:none!important;border-left:0;border-right:0;border-top:0}`。
3. 图标 id 只有 `i-rows` 等有限几个，**没有 `i-grid`**——用了不存在的 id 会静默空白。

**验证**：`tests/test_r901_capability_matrix_rendered.py`（5 条，真渲染：
列数=注册渠道数、行数=维度数、每格是三态之一、无 pageerror、窄档不裁字）。
截图：`docs/screenshots/console-dims.png`（README 已引用）。

### 1.4 【P1】「拓展即漏」的三类硬伤

| 缺陷 | 症状 | 修法 |
|---|---|---|
| `SRX_PLAT_ORDER.filter(...)` 当**过滤集** | App 渠道的探针结果/实时进度**永不显示**（表里只有 5 家浏览器） | 集合改为 `Object.keys(channels)`，顺序仍按 `SRX_PLAT_ORDER.indexOf` 排（未知渠道排 99） |
| 渠道覆盖分母写死 `/5` | 7 家时出现 `7/5` 超界读数 | 分母改为 `SRX.plats.length`（至少 1） |
| 文案写死「五渠道/五平台/四渠道」 | 「查五渠道明细」「正在发起五渠道采集」「其余四渠道」与实际不符 | 改「所选渠道 / 全部渠道 / 各渠道」或按实际数量动态拼 |

**门禁**：`tests/test_r902_no_hardcoded_channel_count.py`（3 条）。
它会**先剥注释**再扫（历史注释里写「五渠道」是记录当时事实，不影响界面）。
**注意「四源」不在此列**——它是一个**视图名**（four 视图把四种来源形态并排），
不是渠道数量；我一度把它扫进来，立刻造成与渠道数无关的假红。

### 1.5 多程：如实标「有入口、仅携程 PC 已接采集」

去哪儿 App 首页原生有「单程/往返/多程」三档（`crawlers/app_qunar.py`
`_ID_SINGLE_RT_SWITCH` 附近），但 App 采集链路只实现了单程 + 往返。
**浏览器端 ctrip PC 2 段已生产验证 → `multi_city=y`（scope=\"仅 2 段\"）；
缺口程 2 段也已实测整单 ¥2184（9C8515+MM079，页面「多程含税价」；
慢页以总价标签为就绪锚轮询；配置卡/概览/CSV/提醒标题按断点显示 `SHA→TYO / OSA→SHA`）；
App 与其余浏览器仍 `""`（产品有入口、采集未接）**，不写 `n`（n 只留给
渠道真没有的能力/停服）。`DIM_TIP.multi_city` 写明「App 有入口，采集未接」。

### 1.6 多程要接，先做数据模型（数据层/携程采集已落地；配置/结果/推送未接）

2026-11-03 真机补充：**渠道侧确实有多程结果面**——去哪儿 App 两段多程
「选择航班」双栏（第一程/第二程，列项标「优惠前含税均价」+ 第二程加价），
同程 App 多程查询只落第一段单程列表。但本产品的 `Route`/`FlightPrice` 是
**单 O-D** 模型，存储/推送/走势/明细都按 `(platform, from, to, date)` 组织，
多段行程没有落库形状。因此多程不是「再写一个 parser」，按依赖顺序至少：

1. **行程形状**：`Route` 增加 `segments=[{from,to,date},…]`（2–4 段）并由它
   派生多程态；行级 `extra` 写 `tripType="MC"`、`legs=[{flight_no,from,to,
   date,dep,arr}]`、`totalBasis="page_multicity_total"`。只有渠道页面自报的
   **整单总价**能进 `price`；各段相加一律禁止。
2. **存储**：不能把多段塞进单 O-D 的 `flight_daily` 主键。新增
   `itinerary_daily`（platform, route_id, segments_key, depart_date,
   total_price, legs_json）或给 `flight_daily` 加 `leg_index`；推送/走势只按
   `total_price` 同比，明细按 `legs_json` 展开。
3. **采集契约**：`supports_multi_city=True` + `fetch_multi(segments)`；段选择
   /第二程加价单独存；等不到整单总价标 `totalLoaded=false`，不落价；营销/示例
   页不落价。
4. **界面**：矩阵 `multi_city` 格解锁前，先有多程结果面（每段时刻 + 一条
   总价 + 溯源每段），不把单段价混进单程列表；hover 写「多程总价」口径。
5. **门禁**：真实夹具 + `tripType="MC"`/legs 断言 + 单程/往返不得带 MC 标记；
   口径文字进矩阵说明（r780/r805ae 同款思路）。

**口径已坐实第一家（2026-11-03 05:47/06:21 订正）**：去哪儿 App 两程页脚明确
「**两程含税总价**」——左列第一程价是**默认第二程（+¥0）组合的整单基准总价**
（¥5069，换 +¥150 的第二程后左列**不变**）；页脚 CountUpPrice 才是**当前选择
组合总价**（+¥150 后 ¥5219；另有 +¥270/+¥1820 档）；第二程 `+¥N` 只存加价、
不落票价。第二程确为海口→东京（羽田/成田，经上海中转；资源 id `HAK-SHA`
只是中转第一段，此前误读为目的地）。同程 App 多程查询仍只出第一段。
**唯一阻塞是本产品的单 O-D 模型/配置**，3+ 段流程未验；矩阵保持 `""`。
解析器已落地 `crawlers/app_qunar_multi.py`（两程；基准价/页脚总价/+¥加价；
真实夹具 + 6 tests），但**未接 fetch/配置/UI**。
**2026-11-03 08:30 数据层落地**：`core/multicity.py`（2–4 段归一、
`segments_key`、MC extra，legs 禁止价格字段）+ `PriceStorage.itinerary_daily`
（platform/route_id/segments_key/depart_date 主键 + total_price + legs_json）
+ `save_itinerary`/`itineraries`（legs 必须与 segments 逐段 from/to/date
一致），11 tests。**2026-11-03 09:00 配置形状**：`Route.segments` 已接，
`build_routes` 由 segments 派生首/末段与日期；`route_query_registry` 把多程
航线单列跳过，**绝不进入单程调度**（日志留痕）。**2026-11-03 10:07–10:11
采集/只读面**：`CtripCrawler.fetch_multi`（真实夹具 ¥1298 整单总价）+ 轮尾
`collect_multicity`（按 `segments_key` 去重、首段过期跳过、只落渠道整单总价）
+ `GET /api/multicity`（真库 `mode=ro`，库/表缺失诚实空态，GET 不建库建表）
已落地；r944 补齐配置卡（2–4 段）与概览整单卡（总价/整单线/未采集原因，
不画空走势），r945 接整单提醒（去抖/回到线上方清 0/跌幅补推，通知未接受不
写状态）、兼容 dict 航线并按用户勾选过滤采集/提醒；r946 又把渠道结果页 URL
存进 `extra.prov` 并在概览给「来源」链接（仅 http(s)，旧行无链接）；r947 又让
提醒跳过首段已过期行程（跨夜新鲜行不误推）；r951 合入 `itinerary_history`
（90 天、按秒去重、只读真实落库点）与概览 sparkline（≥2 点才画，单点/空不补图）；
r954 已有 2 段生产整单行（¥1476），矩阵 **ctrip=y（仅 2 段）**；3+ 段实测
无组合卡、未接通，缺口程未验（后于 16:41 实测 ¥2184，见 §0）。

**2026-11-03 06:08 携程 PC 多程实测（第二条口径坐实）**：用受信 profile 在
`flights.ctrip.com` 列表页切「多程(含缺口程)」，两段 SHA→TYO 11-20 /
TYO→OSA 11-23 提交后落到
`/online/list/multi-sha-tyo-tyo-osa?depdate=2026-11-20_2026-11-23&cabin=y_s&adult=1&child=0&infant=0`。
「多程超低价」组合卡同时列两段（9C8515 + MM304），右侧价 **¥1298** 明写
**「多程含税价」**；下方第一程候选同样逐条写「¥1298 起…¥1869 起 · 多程含税价」。
即携程多程页面自报整单总价，不需要两段相加。采集端已接 `fetch_multi`
（r942/r943，只采页面整单总价）；配置卡/概览整单卡/整单提醒/历史走势已接
（r944/r951），CSV 导出已在 r953 接通；已有 2 段生产整单行（2026-11-03 12:52
¥1476，IJ004 + MM304）；3 段实测结果页无「多程超低价」组合卡，解析器 empty，
3+ 段未接通、缺口程（open-jaw）未验，矩阵 **ctrip=y（仅 2 段）**。

---

## 2. 开工第一件事：核验现场（不要跳过）

```bash
cd D:\idea_project\ticket-monitoring
date; md5sum webui.py | cut -c1-32
python -c "import os,time;[print(time.strftime('%H:%M:%S',time.localtime(os.path.getmtime(p))),p) for p in ('webui.py','core/channels.py','crawlers/tuniu.py')]"
PYTHONIOENCODING=utf-8 python -c "
import sys;sys.path.insert(0,'.')
from core.channels import CHANNEL_DIMENSIONS as M, DIMENSIONS as D, app_alignment_gaps
for p,row in M.items(): print('%-13s'%p,' '.join('%s=%s'%(d[:4],repr(row[d])) for d in D))
print('gaps zhixing:',app_alignment_gaps('app_zhixing'),' qunar:',app_alignment_gaps('app_qunar'))
"
```
**当前应看到的矩阵（10 渠道：5 浏览器 + 5 App；7 个维度 × 10 列）**：
```
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
gaps: app_zhixing=(multi_city)   app_qunar=(multi_city)   app_fliggy=(intl,calendar,round_trip,multi_city,low_fare)   app_ctrip=(multi_city)   app_tongcheng=(multi_city)
```
矩阵变了 → 先查是谁改的、为什么，**不要直接改门禁迁就**（见 §7.2）。

---

## 3. 不变式（改了就会破坏本轮成果）

1. **`y` 必须有代码证据**：声明 `y` 就要有一条真能工作的通路；没验证过的留 `""`，
   `""` 表示**产品支持但本仓库采集端未实现或当前风控未出数**，绝不等于支持
   （界面渲染成「未验证」，灰化）。
2. **`n` 必须有显式不支持分支**：至少 `path_note("<路径>","unsupported")` + 不发起真实查询。
   静默忽略参数 = 假数据，是本项目最严重的缺陷类型。
3. **low_fare 两张表必须互为镜像**（`CHANNEL_DIMENSIONS` ⇄ `SPECIAL_CAPABILITY`），
   由 `test_r900` 守。
4. **App 对齐基准是「任一浏览器渠道已具备该维度」**，不是「某一家同源友商」。
   按单家判会自证：携程自己 `round_trip` 未验证，于是「智行↔携程」永远算不出
   往返缺口。实现是 `core/channels.py::browser_supported()` +
   `app_alignment_gaps()`。
5. **用户可见文案不得写死渠道/源的数量**，由 `test_r902` 守（注释不算）。
6. **渠道集合要由数据决定，顺序才用固定表**。反例：`SRX_PLAT_ORDER.filter(...)`。
7. **声明字典不得有重复键，说明不得与值矛盾**：Python 字面量允许重复键且后者
   静默覆盖，运行时与载荷只看到最后一条。`app_ctrip.low_fare` 曾因此出现
   「矩阵 ✓ / 悬停说没接」。由 `test_r903` 守（AST 重复键 + 非 y 必解释 +
   scope 只挂 y + y 格不得自称未接 + 载荷逐格同文）。
8. **建议里承诺的按钮必须真的存在**：`advise()` 的 hint 写「可点『自检』」
   时，行内必须有自检按钮。`path_degraded/route` 曾被漏掉（只认 probe）。
   由 `test_r905` 守（行为复现 + hint/action 覆盖 + 真渲染按钮）。

---

## 4. 三条业务线的现状与「事实边界的正确写法」

| 能力 | 谁支持 | 正确表述 | 不要写成 |
|---|---|---|---|
| 往返 | 携程（国内/国际）/ 去哪儿网页（仅国内）/ 飞猪（仅国际）/ 同程（国内/国际）/ 途牛（国内/国际）/ 智行 App / 去哪儿 App（仅国内）/ 携程 App（国内/国际：去程卡价即页脚「往返总价」，返程小卡差价不相加；国际 ¥2146、国内 ¥760）/ 同程 App（仅国际：去程行「含税总价」即往返总价，上海⇌东京 7 条、最低 ¥2209；端到端 11-17/22 9 条 ¥2420、返程 MM877 +¥0） | 携程取页面自算总价（国际「往返含税价」¥2404 起 / 国内「往返总价」¥1002 起，2026-11-02 真跑）；去哪儿 touch 去程卡「往返总价」（BJS→SHA ¥808 起，71 条；返程「补 ¥N」不混入），国际匿名 `touchDoubleInnerList` 返回 1999 软拒（2026-11-03），带档案表单（国际+往返）落 `touchInterList` 仍 1999、页面「查询超时」（测不出，非不支持）；同程国内走 `book1/roundtrips` 的 atp 组合总价（2026-11-02 真报文 210/210）；国际登录后 PC RT 页 `ts/list` 的 `tp` 含税总价（2026-11-03 SHA→HKG 41 条、最低 ¥1463；SHA→NRT 77 条、最低 ¥2393），匿名才跳 passport；飞猪的 y 只在国际低价日历（国内列表页只有单程），途牛国内 `listFlight` 两段、国际 H5 `queryFlight` 两段 `productList.avgTotalPrice`（2026-11-03 SHA→NRT 35 条、最低 ¥3010），都只采渠道总价；去哪儿 App 的 y 只在国内（国际档设了返程日仍出单程列表，2026-11-01 实测）；同程 App 的 y 只在国际（去程行含税总价=往返总价，返程 `+¥N` 是加价不相加；2026-11-03 真机上海⇌东京 11-16/19 7 条、最低 9C8515 ¥2209；端到端 fetch 11-17/22 9 条、最低 ¥2420，返程 MM877 +¥0，retLoaded=true） | 「五家都支持且已实现」「同程国际免登录也能出」「途牛不支持往返」「携程/去哪儿网页只支持单程」「去哪儿 App 国际也能往返」或「App 都不支持」 |
| 低价机票 | 携程 / 去哪儿 / 飞猪 / 同程 / 途牛 / 智行 App / 去哪儿 App / 携程 App / 同程 App（9/10；飞猪 App 未接） | 九家有发现源（`SPECIAL_CAPABILITY`）；App 都是「设航线 + 日期窗 → 逐天一条最低价」，页面未标口径 → 标「口径未标注」，不假设含税；携程 App 用价格日历作源、同程 App 用原生价格弹层，均为同一数据面 | 「智行没有特价入口」（它有）、「智行特价是目的地榜」（认错入口，已更正）或「只有七家有低价源」（漏了携程/同程 App） |
| 多程 | 无 | 采集未实现；去哪儿 App 有入口但未接 | 「所有渠道客观不支持」（App 有入口） |

---

## 5. 怎么验证你做的事（可信判据）

**A. 单点门禁（最快，改完就跑）**
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONIOENCODING=utf-8 python -m pytest \
  tests/test_r677_channel_dimension_matrix.py tests/test_r683_channel_dims_surface.py \
  tests/test_r674_app_channel_unified.py tests/test_r700_zhixing_round_trip.py \
  tests/test_r701_qunar_round_trip.py tests/test_r900_low_fare_single_truth.py \
  tests/test_r901_capability_matrix_rendered.py tests/test_r902_no_hardcoded_channel_count.py \
  tests/test_r903_dimension_note_contract.py \
  -q -p no:cacheprovider
```
**当前实测：63 passed**（2026-11-02 23:39，9 个文件，10 渠道）。若这里红了，先修这里。

**B. 界面真渲染（不要只看源码字符串）**
```bash
python webui.py --demo --port 8858
# 浏览器打开 http://127.0.0.1:8858/#cfg → 「渠道登录」tab → 滚到「能力对照」
```
必须满足：10 个渠道列 × 7 个维度行、无 JS 报错、三态都有出现、底部缺口行有内容。
`test_r901` 就是把这一套自动化了。

**C. 全量（约 25–31 分钟）**
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONIOENCODING=utf-8 python -m pytest tests -q -p no:cacheprovider > _scratch/_full.log 2>&1
```
**跑前跑后各存一次 `md5sum webui.py`**——并行会话改了文件，结论作废（见 §7.3）。

---

## 6. 当前红灯（**已确认不属本轮**，别乱修）

以下 4 条在 2026-10-31 20:00 仍红，根因是**并行会话的 r872 改动尚未同步门禁**，
不是渠道能力线的问题：

| 测试 | 根因 |
|---|---|
| `test_r366_source_strip` | 断言 `#healthDiag>#scNote{display:none`，并行会话把 `#scNote` 挪进了来源卡（r873） |
| `test_r536b_note_sits_under_trigger` ×2 | 说明浮层定位规则被重排 |
| `test_v1555_webui::test_body_open_div_single_ternary` | 断言内联 `padding:4px 16px 14px`，已收进类 `.ucbody`（r872） |

**处置原则**：先 `git blame`/看 mtime 确认归属；属并行会话就**等它们收口**，
或按「新意图改写门禁」而不是把实现改回去（§7.2）。**不要**为了让全绿而回退 r872。

---

## 7. 教训（这一轮真实踩过的，按杀伤力排序）

### 7.1 门禁抓到的是「旧的正确形态」
`test_r671`/`test_r672`/`test_v284`/`test_v15273`/`test_channel_links` 都曾因为
**我按新意图改了实现、却留着旧字面量断言**而变红。
判定方法：看断言守的是**行为意图**还是**源码写法**。守字面量的，改成守意图（见 7.2）。

### 7.2 「值变了」≠「设计坏了」
- 我曾经把「渠道集合恰好 5 家」的断言直接放宽成 `>= 5`——那是**放弃守卫**。
  正确做法：改成「浏览器五家必须在 + 注册表全覆盖」，**意图更严**而非更松。
- 反过来，当旧断言锁的正是**本轮要修的缺陷**时（例如要求两态标题行等高，
  而那正是「展开中间夹元素」的成因），应改写断言 + 补一条「缺陷字面值不得回潮」的反向断言。

### 7.3 并行会话会随时改同一批文件（本仓库常态化）
**必须**：
- 跑长门禁前存 `md5sum webui.py`，跑完再存；不一致 → 结论作废重跑。
- **绝不** `git checkout -- webui.py`（会抹掉别人未提交的整份改动，历史实测丢过 86 行）。
- **绝不** `git add webui.py`（会把别人的上千行一起吞进你的提交）。
- 单跑失败项：通过 → 并发/时序假失败；失败 → 再看断言。

### 7.4 先证明判据本身有效
- `test_r516` 曾断言「26 小时前的样本判 stalled」——库里样本被刷新成 55 分钟后就红，
  而 `advise()` 的 `stalled` 门槛是 **6 小时**，实现完全正确。
  改法：**从库里读实际年龄再分流**，未达门槛就 skip 并说明。
- `test_docs_code_contract` 的幽灵令牌门禁只认 CSS 声明，漏了 JS
  `setProperty('--hdh', …)` 写在根元素上的令牌。改法：把 JS 设置也计入 `defined`。

### 7.5 截图/渲染要人工看一眼
能力矩阵第一版「功能全对、视觉错」——`<th>` 继承灰底形成两条带。
自动门禁只验了几何与文本，**没验观感**。凡是 UI 改动，**必须截图亲眼看**。

### 7.6 全局「五」的清洁度检查要做全
我改了一批「五渠道」，门禁立刻抓出**我漏掉的 2 处**（校准册标题、meta description）。
**这正是门禁的价值**：不要因为「我刚改过了」就跳过它。

---

## 8. 下一步（按优先级）

### P0 · 等树稳定，跑全量
并行会话停止写 `webui.py` 后（连看 2 次 mtime 相同 ≥ 5 分钟），跑 §5C。
- 全绿 → 进 P1。
- 仍红 → 按 §6 判归属；属 r872 区域的，**接手把那些门禁按新意图改**（不是回退实现）。

### P1 · 发版（严格按 `docs/HANDOFF_GUIDE.md` §5，别自创）
本轮要发的是 **v1.5.307**（`main.py` 已改、`docs/release-notes-v1.5.307.md` 已写、
`docs/EXECUTION_SPEC_LATEST.md` 已升）。要点：
- 单次「初版」提交 + 贡献者署名（`Co-authored-by` + 对方的 noreply 作者提交）；
- 四个平台包按**推送后的 SHA** 重建，校验 `--version` 与 SHA256；
- Release 名称恒为「机票监控台 · 初版（滚动更新）」，版本只写在正文；
- 演示站按**已发布树**重烘（`python docs/demo_build.py`），戳里的 `code:` 必须等于该 SHA 的 `webui.py`；
- 最后跑 `python docs/release_align_check.py` 到 PASS。

### P2 · 能力线剩余缺口（按可行性和价值排序）
1. ~~**`app_qunar.calendar`**：矩阵写 `y`，但全文件无 `path_note("日历")`，月网格只用于选日。~~
   **已定谳（r805aw）**：App 有日历页，但采集只把它当「选日」用、从不单独落日历价
   （账本全历史只有 `航班明细` 一种 entry_path）→ 声明改 `n` + `DIMENSION_NOTES`
   悬停说明；矩阵、缺口清单与本文档已同步。
2. ~~**`ctrip.round_trip`**：`URL_TPL` 写死 `tripType=ONE_WAY`，改参即可尝试往返。~~
   **已定谳（r815i/r815j 2026-11-02）**：携程 PC `online/list/round-…&containstax=1`
   直出产品往返总价（国际「往返含税价」¥2404 起 / 国内「往返总价」¥1002 起）；
   去哪儿 touch 往返页去程卡直出「往返总价 ¥N 起」（北京→上海 71 条 ¥808 起）。
   两者都只采产品总价、不做两段单程相加；矩阵均已改 **y**（去哪儿 scope 仅国内）。
3. **`multi_city`**：App 去哪儿有入口，但要做「选多段 → 逐段出价 → 合并口径」整条链路，
   属独立特性，不要顺手把矩阵改 `y`。
4. **新增渠道 checklist**：见 §9，硬编码点已枚举，后续接渠道时照单核对。

### P3 · 界面细节
- 能力对照卡 320 档已补门禁（`test_r901` 参数化到 320：内滚 620px、文档宽 310<320、表头零裁字）。
- 「能力对照」是否需要提供筛选（只看有缺口的）。

---

## 9. 新增渠道 / 新增维度时的改动清单（已枚举，防漏）

> **先跑契约，再看这张表**：
> `python -m core.channel_contract --strict`（缺口会点名渠道 + 轴 + 缺哪张表）
> 与 `tests/test_r813_channel_platform_contract.py`。下面的清单解释**为什么**
> 有这些登记点；契约负责在漏接时立刻报红，不需要人逐条对照。

**新增渠道**（★＝硬编码，必须手改，容易漏）：
| 改动点 | 位置 |
|---|---|
| 注册 crawler 类 + REGISTRY | `crawlers/__init__.py` |
| ★ 渠道清单（与 REGISTRY **另抄一份**） | `core/channels.py::BROWSER_CHANNELS` / `APP_CHANNELS` |
| 中文名 | `core/channels.py::CHANNEL_CN` |
| ★ 能力矩阵整行 | `core/channels.py::CHANNEL_DIMENSIONS`（r677 会拦未表态） |
| App 同源 | `core/channels.py::APP_BROWSER_PEER` |
| 登录槽位 | `core/login_slots.py::LOGIN_SLOTS` |
| ★ 节拍白名单 | `core/pacing.py::PLATFORMS` |
| ★ 诊断卡基底 | `core/health_diag.py::PLATFORMS` |
| ★ 入口链接格 | `core/channel_links.py` |
| ★ 告警中文名 | `core/alerter.py::PLATFORM_CN` |
| ★ 雷达白名单 | `core/special_radar.py::_CHANNELS` + `core/specials.py::SPECIAL_CAPABILITY` |
| ★ 演示数据 | `core/demo.py::_PLATS` |
| ★ 前端渠道表（4 份副本） | `webui.py`：`SRX_PLATS` / `APP_PLAT_NAME` / `LOGIN_CN` / `PLATS` |
| ★ 图标 | `webui.py::SRX_BRAND_IMG`（r715 有门禁） |

**新增维度**：`DIMENSIONS` 加项 + 每行补值（r677 拦截）；同时**必须**：
① 在 `webui.py::DIM_CN` / `DIM_TIP` 加中文名与解释（否则界面显示裸 id）；
② 若它是「声明式能力」，需要像 `supports_round_trip` 一样有个**执行点**，
   否则新维度只是一行字、不改变行为。

**新增/扩展往返能力**（r924 同程 App 接入时踩过的点，接下一家照此核对）：
1. **执行点**：`supports_round_trip=True` 只解除 `safe_fetch` 的拦截；
   `fetch(..., ret_date=...)` 必须真的分支到往返流程，绝不能在单程页
   静默丢掉 `ret_date`（那会把单程价当往返价）。单程请求也要先清掉上轮
   留存的返程日，否则会落双栏页。
2. **价格口径**：`price` 必须是渠道页面自己报出的**往返总价**（页脚
   「已选…·¥Z」/去程行「含税总价」/去程卡「往返总价」）。返程栏的
   `+¥N`、`补 ¥N` 是加价，**不相加、不当票价**；两段单程相加一律禁止。
3. **行级可区分**：`extra` 每条写 `tripType="RT"` + `backDate`，并写
   `totalBasis`（如 `page_roundtrip_total`）；单程行不得带 RT 标记。
   r780 门禁管「声明 y 的渠道源码里真有标记 + 单程不泛化」。
4. **覆盖范围**：只验证一端时，矩阵仍写 `y`，但必须在
   `DIMENSION_SCOPE[(plat,"round_trip")]` 标「仅国际/仅国内」，且
   `DIMENSION_NOTES` 的长说明写出同一范围；r805ae 会核对短标签与长说明。
5. **证据**：用**真实结果页夹具**跑解析 + 一条离线全链用例（结果页 →
   `FlightPrice`），再加真机/真请求分步实测（切档/日期/查询/页脚）。
   营销页或示例数据不落价，旧结论被推翻时在文档里保留「过程结论」。
6. **界面**：矩阵/能力说明要出现范围短标签；截图按最终值重烘
   （`docs/screenshots/console-dims.png`），静态站同步重烘。

---

## 9b. 平台质量契约（r813）：11 条轴怎么被自动验收

`docs/HANDOFF_CAPABILITY_MATRIX.md` 的矩阵回答「能采什么」；`core/channel_contract.py`
回答「在整条产品链路里是不是一等公民」。每一格都读**真实登记点**，不是第二份声明：

| 轴 | 判据（读哪里） |
|---|---|
| 可配置 | `crawlers.REGISTRY` + `core.pacing` 节奏表 + 前端渠道表（`SRX_PLATS`∪`APP_PLAT_NAME`） |
| 可观测 | `core.health.PLATFORMS` 与 `core.health_diag` 的渠道集合都必须认得它 |
| 可干预 | 浏览器：`core.login_slots.LOGIN_SLOTS`；App：`core/android/login_api.py` + `/api/app-login` |
| 可见性 | 健康卡 / 诊断卡 / 特价雷达 / 能力声明 / 入口板 / 告警名 / 演示站 / 前端渠道表 八面齐全 |
| 可溯源 | 该渠道 crawler（含父类）的 `path_note(` 调用数 + `PATH_CN` 非空 |
| 可识别 | `CHANNEL_CN` 有中文名且不重复 + `SRX_BRAND_IMG` 有官方图标 |
| 可区分 | 浏览器：`CHANNEL_SURFACES` 两端分列且各有 `SURFACE_NOTES`；App：无端面 + `APP_BROWSER_PEER` |
| 可幂等 | `flight_daily` 主键含 `platform` 且 `INSERT OR REPLACE`（跨渠道不互相覆盖） |
| 语义清晰 | 三态取值合法；有 `n` 维度必须在 crawler 里有 `unsupported` 分支；端面/范围有说明 |
| 可指导 | `pacing.advise()` 契约覆盖**五态**（登录失效/冷却/无样本/路径劣化/成功率低），每态都给出动作 + 中文说明，动作在界面有中文落点；hint 承诺「自检」的 action（probe/route）必须在行内真渲染自检按钮（`test_r905`） |
| 可判断 | `tests/` 里至少一个门禁文件引用该渠道 id（声明不是无人守的） |

**用法**

```bash
python -m core.channel_contract            # 10 行 × 11 列，全绿应显示「无缺口」
python -m core.channel_contract --strict   # 有缺口退出码 1（已接进 CI，见 ci.yml）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r813_channel_platform_contract.py \
  tests/test_r813g_block_not_masked_by_other_surface.py \
  tests/test_r813b_radar_zhixing_rendered.py -q
```

`test_r813b` 是真浏览器往返：切到「用户与航线」面板后 7 个 chip 可见，勾选智行
点「查低价」，请求体必须含 `app_zhixing`；取消勾选后必须不含（负控）。

**它已经抓到的真实缺陷（r813）**：`core/special_radar.py::_CHANNELS` 手抄白名单
只有 6 家，漏了已接入发现源的 `app_zhixing`；`parse_query()` 会把请求里的智行
**静默过滤掉**（界面上勾得到、实际不算）。修法是把白名单改为由
`SPECIAL_CAPABILITY` 中「有 sources」的渠道派生，前端 `SRX_RADAR_APP_KEYS`
同步，`test_r709` 改为守「有源 ⇔ 可查询」双向镜像。

**负控（判据不是恒真）**：幽灵渠道、删中文名、把智行踢出雷达、建议无中文说明、
把维度写成非法三态，五种注入都必须让对应格变红——见 `test_r813` 的五个负控用例。

## 10. 一句话提醒

> **这一轮的价值不在「矩阵多了一列」，而在「界面终于敢说自己支持什么、不支持什么」。**
> 任何让这句话变得不成立的改动——静默吞参数、把未验证写成支持、
> 文案里写死数量——都比少一个功能更严重。
