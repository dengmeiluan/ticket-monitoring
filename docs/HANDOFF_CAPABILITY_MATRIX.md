# 交接指导书 · 7 渠道全维度能力一致性（r900–r902 专项）

> **这份文档写给**：接手继续这项工作的下一个会话。
> **三份交接文档的阅读顺序**：① `docs/HANDOFF_FULL_SESSION.md`（全会话总览，先读）→ ② 本文（能力一致性专项）→ ③ `docs/HANDOFF_GUIDE.md`（发版与文档门禁体系）。
> **与另一份文档的分工**：`docs/HANDOFF_GUIDE.md` 讲**通用**（发版流程、文档门禁体系、操作纪律）；
> 本文讲**本轮这条线**——「7 渠道全维度能力一致 + 特色能力可独立识别/聚合 + 后续可拓展」，
> 包括为什么这么改、哪些坑是真的、还剩什么、怎么验证。两份都要读，**本文优先看 §2 的现场核验**。
> **编写时间**：2026-10-31 20:00。文中每个数字都来自实测，但**开工前必须自己再核一遍**。

---

## 0. 一句话现状

7 家渠道（5 浏览器 + 2 App）× 7 个维度的能力矩阵**已从「只活在源码里」变成「界面上一张表」**，
并修掉了一处「单程价冒充往返价」的诚实性缺陷、一处「同一件事两张表结论相反」的漂移。
**2026-11-02 01:33 本地已全绿**：全量 pytest **5869 passed / 16 skipped / 0 failed**、
UI **670/670**、站点戳 `1.5.307 code:4564d69bf4cf`、`release_align_check --local` **25/25**；
live 8765 已重启加载 r813g；真实账本上途牛 PC 的滑块在 01:33 显示为 `challenge`，
随后打开验证窗口转为 `active`（状态流转符合设计）。
**在线 tag/正文/Pages 仍不同源**（tag `02766a3` vs 发布源 `5cff7f5`、线上站点戳旧树；
该 SHA 的 CI 21 failed），在线发布待用户明确授权。
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
> 语义清晰/可指导/可判断）做成**对真实登记点的求值**，7 家 × 11 轴当前 0 缺口；
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
（见 §4 与 `DIMENSION_SCOPE`「仅国内」）；国际产品结构仍是单段，保持 `n`。

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

### 1.5 多程：如实标「有入口、采集未接」

去哪儿 App 首页原生有「单程/往返/多程」三档（`crawlers/app_qunar.py`
`_ID_SINGLE_RT_SWITCH` 附近），但采集链路只实现了单程 + 往返。
**矩阵记 `multi_city=""`（产品有入口、采集未接 = 未验证）**，不再写 `n`
（n 只留给渠道真没有的能力/停服）。
`DIM_TIP.multi_city` 写明「App 有入口，采集未接」。

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
**当前应看到的矩阵（7×7）**：
```
ctrip        domestic=y intl=y calendar=y detail=y round_trip=y  multi_city="" low_fare=y
qunar        domestic=y intl=y calendar=y detail=y round_trip=y  multi_city="" low_fare=y
fliggy       domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
tongcheng    domestic=y intl=y calendar=y detail=y round_trip=y  multi_city="" low_fare=y
tuniu        domestic=y intl=y calendar=n detail=y round_trip=y multi_city="" low_fare=y
app_zhixing  domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
app_qunar    domestic=y intl=y calendar=y detail=y round_trip=y multi_city="" low_fare=y
gaps: app_zhixing=()   app_qunar=()
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

---

## 4. 三条业务线的现状与「事实边界的正确写法」

| 能力 | 谁支持 | 正确表述 | 不要写成 |
|---|---|---|---|
| 往返 | 携程（国内/国际）/ 去哪儿网页（仅国内）/ 飞猪（仅国际）/ 同程（仅国内）/ 途牛（仅国内）/ 智行 App / 去哪儿 App（仅国内） | 携程取页面自算总价（国际「往返含税价」¥2404 起 / 国内「往返总价」¥1002 起，2026-11-02 真跑）；去哪儿 touch 去程卡「往返总价」（BJS→SHA ¥808 起，71 条；返程「补 ¥N」不混入）；同程国内走 `book1/roundtrips` 的 atp 组合总价（2026-11-02 真报文 210/210），国际仍需页面两步流；飞猪的 y 只在国际低价日历（国内列表页只有单程），途牛的 y 只在国内容量接口，去哪儿 App 的 y 只在国内（国际档设了返程日仍出单程列表，2026-11-01 实测） | 「五家都支持且已实现」「同程国际也已往返」「途牛不支持往返」「携程/去哪儿网页只支持单程」「去哪儿 App 国际也能往返」或「App 都不支持」 |
| 低价机票 | 携程 / 去哪儿 / 飞猪 / 同程 / 途牛 / 智行 App / 去哪儿 App | 七家都有发现源（`SPECIAL_CAPABILITY`）；两个 App 都是「设航线 + 日期窗 → 逐天一条最低价」，页面未标口径 → 标「口径未标注」，不假设含税 | 「智行没有特价入口」（它有）或「智行特价是目的地榜」（认错入口，已更正） |
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
  -q -p no:cacheprovider
```
**当前实测：54 passed**（2026-10-31 20:05，8 个文件）。若这里红了，先修这里。

**B. 界面真渲染（不要只看源码字符串）**
```bash
python webui.py --demo --port 8858
# 浏览器打开 http://127.0.0.1:8858/#cfg → 「渠道登录」tab → 滚到「能力对照」
```
必须满足：7 列、7 行、无 JS 报错、三态都有出现、底部缺口行有内容。
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
| 可指导 | `pacing.advise()` 对登录失效/冷却/无样本三态都给出动作 + 中文说明，动作在界面有中文落点 |
| 可判断 | `tests/` 里至少一个门禁文件引用该渠道 id（声明不是无人守的） |

**用法**

```bash
python -m core.channel_contract            # 7 行 × 11 列，全绿应显示「无缺口」
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
