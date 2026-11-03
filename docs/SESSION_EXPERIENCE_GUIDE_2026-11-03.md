# 机票监控台 · 2026-11-03 长会话完整经验与交接指导书

> **读者对象**：接手继续本项目的下一个会话（AI 或人类协作者）。
> **快照时间**：2026-11-03 17:40（Asia/Shanghai）。所有数字、进程、端口、分支都会漂移，开工前必须按 §6.1 重新核验。
> **文档性质**：这不是单一交接清单，而是本轮长会话的**完整目标、期望、已落地改动、真实现场、判据陷阱、操作手册、未完成事项与红线**。先读 §0–§2，再按 §6.1 开工。
> **权威关系（冲突时按此顺序，现场优先）**：
> 1. 现场实测（`git`、进程、API、浏览器、测试）；
> 2. `docs/EXECUTION_SPEC_LATEST.md` §1.0 当前状态；
> 3. `docs/HANDOFF_CAPABILITY_MATRIX.md` §0 一句话现状；
> 4. **本文件**（2026-11-03 本轮完整经验）；
> 5. `docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md`（上一轮经验书，当前工作树中可能尚未提交）；
> 6. `docs/HANDOFF_FULL_SESSION.md`、`docs/HANDOFF_GUIDE.md` 与 §12 历史台账（历史背景，不代表现状）。

---

## 0. 30 秒速览

- 项目：自托管的多渠道机票价格监控台（Python 单文件 SPA + SQLite + Playwright/App 采集 + 钉钉推送）。
- 本轮目标：继续推进历史会话（目标中列出 7 个会话 ID，历史叙述常称“六条会话线”，以实际列表为准）未完成/可做得更好的工作；核心是 **10 渠道（5 浏览器 + 5 App）× 7 维度 × 11 平台能力轴** 的统一、可配置、可观测、可干预、可溯源、可判断，以及页面产品化、文档/发布维护和 CI 效率。
- 本轮新增交付：
  1. **CI 全量测试 4 台 runner 分片并发**（按历史耗时快照均分）+ 分片并集/ workflow 一致性自检 + `ci-ok` 聚合 + 超时；本地同构 4 片验证通过。
  2. **携程 2 段缺口程（open-jaw）接通**：真实页面整单 ¥2184（复跑 ¥2183），只取页面「多程含税价」，不把两段单程相加；慢页以总价标签为就绪锚轮询。
  3. **多程链头断点统一**：配置卡、概览、CSV、整单提醒全部显示 `SHA→TYO / OSA→SHA`，不再画成假闭环 `SHA→TYO→SHA`。
  4. 文档/测试口径同步：tracked collect **6278**；clean HEAD 全量非 UI **6234 passed / 44 skipped / 0 failed**；UI **670/670**。
- 当前不能宣称完成：并行会话仍有 **26 个未提交/未跟踪文件**且正在跑测试；静态站戳已过期；发布/推送/tag/Release/Pages/镜像/live 切换**未获授权、未执行**；飞猪按要求暂停；多程仍仅携程 2 段（3+ 段无组合卡，其余九家未接）。
- 当前分支：`feat/multicity`；HEAD `4fcdcfb`。用户明确要求**在主分支/主工作树开发，不要切 worktree**；本轮所有新提交都在该分支，未合并/未推送 `main`。

---

## 1. 用户目标、期望与边界

### 1.1 用户给本轮的目标（按语义整理；技能名是方法目标，不是原话）

用户把目标中列出的 7 个会话 ID 放在同一个目标下（历史叙述里常称“六条会话线”），要求“把这六个会话目标未完成以及或者可以做到更好的继续推进”。核心范围：

1. **10 渠道能力矩阵**：5 个浏览器渠道（携程 / 去哪儿 / 飞猪 / 同程 / 途牛）+ 5 个 App 渠道（智行 App / 去哪儿 App / 飞猪 App / 携程 App / 同程 App）。
2. **7 个能力维度**：国内 / 国际 / 日历 / 明细 / 往返 / 多程 / 低价机票。
3. **11 个平台能力轴**：可配置、可观测、可干预、可见性、可溯源、可识别、可区分、可幂等、语义清晰、可指导、可判断。
4. **统一设计**：样式统一、能力统一、约束统一、调度统一、策略统一、聚合分类统一，并为后续新增渠道建立统一接线方式（单一声明源、契约门禁、派生 UI）。
5. **页面产品化**：微信扁平化布局与交互体验；信息诚实（空/失败/未验证/不支持要分清）；按钮与文案可指导下一步。
6. **GitHub 维护体验**：代码、文档、README、tag、四平台安装包、部署包、ghcr 镜像按“初版（滚动更新）”方式维护；Release 正文/资产/站点/CI 同源。
7. **继续扫荡各个角落**：读 `docs/` 下多会话交割文档与会话历史；发现并修复真实缺陷；做到极致。
8. **CI 效率**：把 CI 改成并发，提升测试效率（本轮的明确新增要求）。
9. **开发位置**：就在主分支/主工作树开发，不要切 worktree（本轮的明确新增要求）。

**明确约束（用户给出）**：
- **飞猪暂时账号被风控，先不验证飞猪**。不要为了“补齐矩阵”去探测飞猪；飞猪 App 也保持暂停。
- 不做绕过登录/验证码/滑块/人脸的动作；不把“绕过检测”当作能力目标。
- 不把两段单程价相加冒充往返/多程总价；只取渠道页面自报的整单总价。
- 未经明确授权：不推送、不改 tag、不发 Release、不切 live、不改共享状态。

### 1.2 本次会话新增/明确的期望

- **CI 并发必须真的减少墙钟，而不是只把命令改花**：分片并集必须等于全部测试文件；新增测试文件不能漏跑；分片数与 workflow 不能漂移。
- **验证要有证据**：真实命令输出、JUnit 摘要、浏览器渲染、真实渠道页面、源码哈希 pin；不能只凭源码里有某行字。
- **数字要带口径**：README 的测试数是“已跟踪口径”；工作树/未跟踪测试不算；UI 数是 `docs/uitest_result.txt` 的已提交结果；站点戳是 `sha256(webui.py)[:12]`，不是 commit SHA。
- **语义清晰**：同一件事在不同表面（配置卡/概览/CSV/提醒/矩阵说明）必须同构；本次专门修了“开口程链头假闭环”。
- **不覆盖并行会话**：另一个会话正在做的 App 隐身/ABI/滑块/策略引擎属于它；不要提交、覆盖或“顺手整理”它的未跟踪文件。
- **门禁独占串行**：同一台机器不要同时跑两轮全量门禁；并发编辑会让结果作废。
- **用户审美**：紧凑控制台 + 微信扁平化；同一列文案同构；间距/字号有尺度；像素/渲染证据；README/品牌叙事也要完整、真实，不伪造演示。

### 1.3 方法目标标签（重要：不是用户原话）

用户在目标里点名了 `using-superpowers`、`multi-agent-workflow`、`Frontend Design`。它们应理解为**方法与能力目标**，不是用户的逐字措辞，也不是必须机械调用的口令：

- `using-superpowers` → 先查适用技能/流程；bug 先复现再修；TDD；完成前做验证；不要凭意图宣布成功。
- `multi-agent-workflow` → 复杂任务拆分、并行验证、独立审查；但共享文件/共享状态仍要串行与归属清晰。
- `Frontend Design` → 页面要有明确视觉方向、统一尺度、真实渲染与像素证据；不是套模板。

写文档/汇报时不要把这三个词伪装成用户引语；它们是目标标签。

### 1.4 红线与不可做（违反即失败）

1. **飞猪不验证**：不探测、不启用、不重登、不换代理/指纹去试；何时恢复由用户决定。
2. **不绕过**：登录、验证码、滑块、人脸、风控页都不做绕过；只做稳定自洽身份与人工接管。
3. **不编造价格/能力**：矩阵 `y/n/""` 必须有证据；未实现就是 `""`；不支持就是 `n`；禁止用单程价相加或“均价”冒充整单总价。
4. **无授权不发布**：不 push、不打 tag、不发 Release、不部署 Pages、不切 live、不推 ghcr，除非用户明确授权。
5. **不覆盖并行工作**：不使用 `git add -A`/`git add .`；不整文件暂存 `webui.py`；不 `git checkout webui.py`；不 `git stash` 别人的改动。
6. **不切 worktree**：用户明确要求主分支/主工作树开发；不要新建 worktree、不要 `git checkout` 到隔离 worktree 开发。
7. **门禁串行**：并行跑全量会让 free-port、demo 库、源码哈希 pin 互污染；红了先分清“值变了/设计坏了/并发假红”。
8. **不造假/不粉饰**：空态、失败、未验证、测不出必须如实显示；不能把“没拿到”记成 `empty`；不能把“没接”写成“渠道没有”。
9. **编码/EOL**：Windows GBK 下 `print` emoji 会崩；测试/脚本要 `PYTHONIOENCODING=utf-8` 或 `reconfigure(errors="replace")`；追加文本只产裸 LF，混 EOL 是 bug。
10. **共享进程安全**：不杀陌生进程；重启 live 前看 PID/启动时间/工作目录；不在采集轮次中抢设备/重启。

### 1.5 用户审美/交互偏好（供后续 UI 轮）

- 紧凑控制台 + 微信扁平：少卡片套卡片、少无意义留白；分区清晰；操作在折叠行/卡头，不埋在滚动末尾。
- “统一”= 同一外观 **且** 同一交互；同列文案同构；空态给下一步动作；错误不道歉、说清原因与修法。
- 数字/金额/状态要有口径词；“—/0/空”三态不能混；未验证不要画成支持。
- 视觉验证要真实像素/渲染/命中测试/最坏内容；不能只跑静态正则。
- README/品牌叙事要完整、真实截图/SVG，不伪造演示；初版 Release 正文是完整产品介绍，不是 changelog。

---

## 2. 当前权威状态（2026-11-03 17:40）

### 2.1 代码 / 分支 / 工作树

> **2026-11-03 20:22 状态更新（优先于本节旧快照）**：HEAD `c985ce0`（main），
> 工作树仅并行文档 WIP；tracked collect **6370**；clean HEAD `bc96947` 全量非 UI
> **6326 passed / 44 skipped / 0 failed**（409.47s）；UI **670/670**；
> 站点戳 `db416c15fca7` 已按当前 webui 重烘（2026-11-03 21:24）；PiP 工作台与 App 图标质感已落地；
> `release_align_check --local` **25/25 PASS**。

- 分支：`feat/multicity`（不是 `main`）。
- HEAD：`4fcdcfb docs: 历史多程记录补缺口程实测订正痕迹`。
- **工作树不干净**：`git status --short` 共 **26** 项，全部属于并行会话的 App 隐身/ABI/滑块/策略 WIP（见 §2.6）。本轮自己的文件均已提交。
- 本轮新增提交（从旧到新）：
  `67a6ff1` → `7e4f386` → `62888c4` → `47731c9` → `faa26f3` → `7d2793b` → `90b89ac` → `5d1e108` → `a33e1f5` → `b0519cd` → `aefbdcc` → `61b8b61` → `506829d` → `4f00add` → `d5d9071` → `bae8a37` → `4fcdcfb`。
- 用户要求“不切 worktree”；本轮后期使用了一个 `_scratch` 下的**干净验证副本（git clone，不是 worktree）**跑最终门禁。不要把它当开发树，也不要在其中提交。
- 之前遗留的 `_gate_r963/_gate_r964/_gate_r965` 是验证用 detached worktree（用户新要求之前创建）；不要继续使用/新建，证据已提取，可按需清理。

### 2.2 门禁 / 测试（当前权威数字）

- **tracked collect = 6278**（用 `git ls-files tests` + `pytest --collect-only` 实测，2026-11-03 17:xx）。
- **clean HEAD `d5d9071` 全量非 UI**：**6234 passed / 44 skipped / 0 failed**，6278 项，workers 8，412.05s；语法检查 ok；源码哈希 pin 通过。
  - 原始 run dir：`_scratch/_gate_clone_4f00add/_scratch/test_run/20261103-170927-84652/`（验证副本；可清理，数字以本文件/SPEC 为准）。
  - `d5d9071` 之后只有 `bae8a37`（文档 + CI 快照）与 `4fcdcfb`（文档）两个 **docs-only** 提交，产品代码未变，故门禁对当前产品代码仍成立。
- **UI 自检**：**670/670，零 JS 错误**，2026-11-03 16:50 全量复跑（主工作树，结果文件 `_scratch/ui_openjaw_result.txt`）。此后 `webui.py` 只有服务端 label/提醒的 Python 改动，页面 JS 未变；服务端改动由全量 pytest 覆盖。
- 本轮定向验证（均通过）：
  - Ctrip/multicity 12 个文件 **78 passed**；
  - 多程 UI/静态/真实浏览器 **10 passed**；
  - 提醒/API/正文/文档契约 **44 passed**；
  - 渲染矩阵 + note 契约 **15 passed**；
  - 文档契约 19 passed；
  - 真实探测 2 次成功（¥2184 / ¥2183），中间一次 `saved=0`（见 §7.1）。

### 2.3 CI 状态

- `.github/workflows/ci.yml`：
  - 顶层 `concurrency` 按 ref 取消旧跑（`cancel-in-progress: true`）。
  - `test` 为 **4 组 matrix**（group 0–3），每片用 `tools/ci_shard.py --print 4 ${{ matrix.group }}` 选文件，片内 `pytest -n 4 -p xdist.plugin --dist loadfile`。
  - 跑测前 `python tools/ci_shard.py --stats 4`：校验并集=全部 `tests/test_*.py`，并校验 workflow 的 matrix 组数、选片命令、`--dist loadfile`、`ci-ok`、取消旧跑、独立 UI 岗。
  - `test/uitest` 各 `timeout-minutes: 45`；`ci-ok` 聚合 `needs: [test, uitest]`。
  - `pip`/Playwright 缓存保留；`fetch-depth: 0` + 补拉 tag；Chromium + Noto CJK 安装保留。
- `tools/ci_shard.py`：`--snapshot <junit>` 从全量 JUnit 生成按文件耗时快照；`--stats N` 统计并自检；`--print N K` 给 shell 选片。
- `tests/ci_durations.json`：已按 `90b2154` clean gate JUnit 重算；快照覆盖 **870/870** 个测试文件（合计 2935.1s），四片 217/217/218/218 文件。LPT 权重 = 文件测试耗时 + **1.0s/文件导入开销**：只按纯耗时均分曾把第 2 片堆到 341 个文件，墙钟比别的片多 ~100s；计开销后权重 max/min **1.00**。
- **最终绿（真实 GitHub，4+2 片）**：`41657991817`（`8a69a1a`）test 4 片 **264/310/206/278s**、UI 2 片 **224/189s**、`ci-ok` success，整轮 **6m11s**；`tools/ci_shard.py` 的 +1s/文件权重把四片文件数拉平（216–218），UI 分段（0–24 / 25–49）把 UI 从 367s 降到 224s。当前关键路径是测试片（max 310s）。前一轮 `41653462306`（`de44d464`）4+2 片同样全绿（test 284/358/240/282s、UI 234/185s）。
- 实测参考：旧 CI `test` 单 job `-n 4` 约 **11 分 31 秒**（2026-11-03 01:40:09→01:51:40）；UI job 约 **6 分 05 秒**。4 片真实 GitHub 首跑（`bc96947`，2026-11-03 13:11Z 起）：shard 1/3 绿（249s/283s）、shard 0/2 红（214s/233s），UI 381s——test lane 墙钟已从 11 分半降到 **约 5 分钟**；红的根因与切片无关，见下条。
- **本地绿 / CI 红的环境差异（已实证）**：`crawlers/slider.py` 用可选 `import numpy`，本地全局环境有 numpy，CI 只装 `requirements.txt` 而当时未声明 numpy → `find_gap()` 恒返回空候选，r914/r916 四条同时红。修复=把 `numpy>=1.26` 写进 `requirements.txt`（CI、release-build、Docker 同一来源），并给缺依赖加一次性告警 + 负控（屏蔽 numpy 时仍红、装上才绿），不把测试改成 skip。
- 分片串行排障口径：先看失败片日志的 `FAILED` 行，再判断是本片代码问题还是并行 WIP 的跨片问题；本次第二红（`android.vendor.apply` 无 UI 落点 + 加固 ok 被只读探测拖红）就是并行提交引入、与 numpy 无关。
- 第三红（`b345486`）：`test_swr_returns_stale_immediately` 在 CI 慢机假红——SWR 分支触发的后台重建线程先在断言前发布新 payload，`out == {"v":"stale"}` 变成新状态。产品语义没问题，修测试：当测里把 `_state_rebuild_async` 换成记录器，分别断言「立即回旧值」和「确实排了重建」，线程本身由 `test_async_build_does_not_hold_lock` 真跑覆盖。教训：断言不要依赖不可控线程调度。
- **UI 岗已切 2 片（0–24 / 25–49）**：`docs/uitest.py` 的 `UITEST_SECTIONS` 可直接分片，但段间有状态依赖——冷跑 25–49 时 r299 的 computed 断言拿不到渠道 chip、r358 健康格 6s 超时。修法：r299 段先 `switchView('cfg')` 并等 `.chip.pch.on` ≥2 再取 computed；r358 健康格等待 6s→12s。两半分别本地 **473/473** 与 **197/197** 全绿；`tools/ui_shard.py` 从源码 `_want(N)` 派生段号、`--stats 2` 校验并集与 workflow，CI `uitest` matrix [0,1]。

### 2.4 多程（能力矩阵当前口径）

- `ctrip.multi_city = "y"`，`DIMENSION_SCOPE = "仅 2 段"`，矩阵说明已写入“缺口程 2 段已实测 ¥2184”。
- 2 段点对点生产行：¥1476（IJ004 + MM304，2026-11-03 早先实测）。
- 2 段缺口程：SHA→TYO 11-20 / OSA→SHA 11-26，页面自报 **¥2184**；复跑 **¥2183**；legs 9C8515 + MM079；`tripType=MC`、`totalBasis=page_multicity_total`、`prov` 来源 URL 落库；临时库 `itinerary_daily` 1 行 + `history` 2 点（两次成功）。
- **3+ 段**：实测无「多程超低价」组合卡，解析器记 empty；UI 配置卡保留“3+ 段当前未接通”警告；不把 3+ 写成支持。
- 其余九家 `multi_city` 仍为 `""`（产品有入口、采集端未接）；`channel_contract --strict` 仍是 **10 家 × 11 轴无缺口**（这里的“无缺口”指 11 轴登记完整，不代表多程都实现）。
- 关键代码：
  - `crawlers/ctrip.py::_multi_text_with_total`（就绪轮询，最多 +12s，500ms 步进）；
  - `crawlers/ctrip.py::fetch_multi`（只取页面总价，legs 仅进 extra）；
  - `crawlers/ctrip_multicity.py`（URL/解析器，要求「多程超低价」+「多程含税价」）；
  - `webui.py::_mc_chain_label`（服务端链头断点）、`_mcChain/_mcNames`（页面 JS 链头断点）；
  - `webui.py::_multicity_alert_round`（提醒标题用 `_mc_chain_label`）；
  - `core/storage.py::save_itinerary` / `itinerary_history`；`main.py::collect_multicity`。

### 2.5 live / Release / 站点

- live 8765：PID **47952**，启动于 **2026-11-03 08:58:06**，命令行 `python main.py --restart-delay 3`；按既有记录运行 `_release_ab04`（HEAD `e65cee1`）。
- live `/api/health`（只读实测）：`enabled_platforms` = **6**：`qunar, tongcheng, tuniu, ctrip, app_zhixing, app_qunar`；**不含 fliggy**（好）；`diag` = 7 张，含 `fliggy` 是历史日志卡，不等于在采集。
- Release/版本口径：文档记录 Release `v1.0` → `ab04c22`（v1.5.307），但**本地 tag `v1.0` 解析为 `e65cee1`**，`_release_ab04` 工作树 HEAD 也是 `e65cee1`。这是本轮发现的**待复核不一致**：发版前必须用 GitHub API/`git ls-remote --tags` 核线上 tag/Release 目标，不要以本地 tag 或正文单方断言“同源”。
- 静态站：`docs/site/index.html` 当前戳 `code:f312a1cee43b`（15:56 重烘）；当前 `webui.py` SHA256[:12] = **`3f62d44eb1fe`**，**站点已过期**。发布前必须重烘并重跑对账；当前主树的 `docs/site/index.html` 还有并行会话未提交改动，不要直接覆盖。
- 未推送、未打新 tag、未发新 Release、未部署 Pages、未切 live、未推 ghcr；这些都需要用户明确授权。

### 2.6 并行会话 WIP（不要碰）

截至快照，工作树有 26 项未提交/未跟踪，典型包括：

- `core/android/abi_canary.py`、`display.py`、`hardening.py`（新增，未跟踪）；
- `core/policy.py`、`crawlers/slider.py`（新增，未跟踪）；
- `core/android/device.py`、`emulator_tuning.py`、`fingerprint.py`、`runtime.py`、`stealth.py`；
- `crawlers/app_base.py`、`base.py`、`challenge.py`；
- `config.example.yaml`、`CONTRIBUTING.md`（并行会话对 CI 文档的进一步改写）、`docs/DEVICE_IDENTITY_PLAYBOOK.md`、`docs/YIELD_AND_SESSION_STRATEGY.md`、`docs/site/index.html`、`docs/uitest_result.txt`；
- `tests/test_p0_challenge_detection.py`、`test_p1_challenge_takeover.py`、`test_r910_device_identity_stealth.py`；
- 未跟踪测试 `tests/test_r913_policy_engine.py`、`test_r914_slider_solver.py`、`test_r915_android_hardening.py`；
- 未跟踪经验书 `docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md`。

这些不是本轮工作；不要提交、不要覆盖、不要替它“整理”。等它提交后再对最终树跑门禁。

### 2.7 一句话结论

**本轮新增工作（CI 并发、开口程、链头统一、文档/口径）已完成并验证；但整个项目目标尚未全部完成**：并行 WIP 未冻结、站点未重烘、发布链路未授权执行、剩余能力边界仍需按证据推进。

---

## 3. 本次会话做了什么（按工作流）

### 3.1 CI 并发（核心新增要求）

**问题**：CI 原来单 job `pytest -n 4` 约 11 分半；UI 自检单进程约 6 分钟。用户要求“CI 能不能改成并发”。

**落地**：

1. `test` job 改为 4 组 matrix，每组一台 runner；每片用历史耗时快照贪心均分文件。
2. 新增 `tools/ci_shard.py`：
   - `snapshot()`：从全量 JUnit 按 `classname` 归一到测试文件，聚合秒数；未知/新文件默认 20s；
   - `plan()`：LPT 贪心（长耗时先放，进当前负载最小的一组），确定性排序；
   - `print()`：输出第 K 组相对路径，直接给 pytest；
   - `stats()`：打印组文件数/耗时/均衡度，校验并集=全集、无重复、无遗漏；
   - `check_workflow()`：校验 workflow 的矩阵组数、`--print N`、`--dist loadfile`、`ci-ok`、取消旧跑、独立 UI 岗。
3. `ci-ok`：稳定聚合检查（`needs: [test, uitest]`），分片 job 名变化不影响外部只认一个绿结论。
4. `test/uitest` 各 45 分钟超时；保留 pip/Playwright 缓存、tag 补拉、Chromium/CJK 字体安装。
5. 修掉分片暴露的测试竞态：
   - `test_r290_login_stale`：全局 `_State.cfg/boot_cfg` 会被同 worker 前序用例的后台线程重载；改为注入 `_effective_crawler_config` 结果，只钉 `_login_state_view` 语义。
   - `test_r793_surface_axis`：冻结树里账本可能刚建空文件、表还没 create；把 `no such table` 也纳入 `sqlite3.DatabaseError` 环境守卫，skip 并给原因，不记产品红。
   - 文档 CLI 契约：`--dist/--stats/--snapshot` 属于 pytest/仓库工具，不是产品 CLI；契约放行 `pytest` 与 `tools/*.py` span，并做了“注入 `--definitely-not-a-flag` 必须红”的负控。
6. 验证：
   - 4 片同构并发（本机 `-n 3`，竞争下）四片合计 **6230 passed / 44 skipped / 0 failed**（6274；`62888c4` 的 0/1/3 片 + `47731c9` 的第 2 片；两提交只差 r793 测试守卫）；
   - 之后新增 4 个测试（轮询、JS 链头、服务端 label、提醒标题），由 clean HEAD 全量门禁覆盖为 **6234/44/0（6278）**；
   - `tests/ci_durations.json` 按 clean JUnit 刷新：854/854、四组 1.00 均衡。

**真实 GitHub 验证（2026-11-03，已补）**：
- `41633762684`（`bc96947`）：shard 1/3 success，shard 0/2 failure；失败仅 r914/r916 滑块四条，根因 CI 缺 numpy（本地全局有，掩盖了）。
- `41642117895`（`03a46e6`）：numpy 修复后 shard 0/1/3 success，shard 2 failure；失败为并行提交的 `android.vendor.apply` 无配置页落点 + `test_harden_runs_steps_in_fixed_order` 的 ok 语义，与 numpy 无关。
- 修复：requirements 声明 numpy + 缺依赖告警；配置页补 `glbVendorApply` 控件、保存时与文件已有 `android.vendor` 键合并；加固的只读 vendor 探测不再拖红整套 ok；补真渲染“点击写回 GLB”断言与静态合并断言。受影响 72 + 1 项本地绿后推送 `8c3e4b5`。
- `41644097180`（`0f782f9`）：**test 4 片 + UI + ci-ok 全绿**，各片 242/225/341/244s、UI 367s，整轮 6m14s；numpy 与 vendor 两处修复均已进入该树。
- `41657991817`（`8a69a1a`）：**4 测试片 + 2 UI 片 + ci-ok 全绿**（test 264/310/206/278s、UI 224/189s），整轮 6m11s；captcha 配置页落点与站点重烘 `db416c15fca7` 均在此树。
- `41659506855`（`90b2154`，docs-only HEAD）：**4+2 片 + ci-ok 全绿**；同树干净克隆全量 **6440 passed / 44 skipped / 0 failed**（419.64s，6484 项），`release_align_check --local` **25/25 PASS**。快照已按这份 JUnit 刷新为 870/870。

**边界**：
- 分片快照是历史耗时，测试结构大改后需重建；新增文件按 20s 兜底。
- 并行会话持续推送时，CI HEAD 会移动；必须以最新 run 的 head_sha 为准，不能拿旧 run 的绿/红冒充当前树。

### 3.2 携程 2 段缺口程（open-jaw）

**背景**：矩阵此前已 `ctrip.multi_city=y`，scope “仅 2 段”；3+ 段实测无组合卡；文档写“缺口程未验”。

**真实探测（2026-11-03 16:41）**：
- 使用 Ctrip profile 副本 + 临时库，不碰 live 会话/库；
- 段：SHA→TYO 2026-11-20 / OSA→SHA 2026-11-26；
- URL：`https://flights.ctrip.com/online/list/multi-sha-tyo-osa-sha?depdate=2026-11-20_2026-11-26&cabin=y_s&adult=1&child=0&infant=0`；
- 页面「多程超低价」组合卡 + 「多程含税价」**¥2184**；legs 9C8515（SHA→TYO 21:10→01:05）+ MM079（OSA→SHA 22:25→00:20）；`tripType=MC`、`totalBasis=page_multicity_total`、`prov{path,url,totalBasis}`；
- 复跑 17:08 成功 **¥2183**；临时库 history 2 点；
- 中间有一次 `saved=0`（未等到总价），随后重跑成功——说明页面存在慢/空抖动（见 §7.1）。

**代码改进**：
- `fetch_multi` 原固定等 9s，慢页会假空；新增 `_multi_text_with_total(page, text, extra_s=12.0, step_ms=500)`：以「多程含税价」为就绪锚，最多再等 12s，出现即走；被拦页没有该标签，最多多等这一段。
- 新增边界测试：总价出现即停；始终没有总价时受 deadline 约束返回最后一次文本，不死等。
- 矩阵 scope 仍保持 **“仅 2 段”**（含缺口程），没有升级成“全段支持”。

**链头断点（同批发现并修）**：
- 旧拼法把开口程 `SHA→TYO / OSA→SHA` 写成 `SHA→TYO→SHA`，读起来像从东京返程；
- 修了 4 个消费者：
  1. 配置卡 JS `_mcChain/_mcNames`（`webui.py`，约 19418 行）；
  2. 概览卡/CSV 的服务端 `mc_routes.label`（`webui.py::_mc_chain_label`，约 537 行）；
  3. 整单提醒标题（`_multicity_alert_round`，约 30700 行）；
  4. 相关测试：真浏览器求值、服务端 helper、提醒消费端。
- 输出规则：连贯段保持 `SHA→TYO→OSA`；段间断点用 ` / `，例如 `SHA→TYO / OSA→SHA`。

### 3.3 文档/口径同步

- README/README_EN：补 CI 4 片说明；多程行补“2 段缺口程实测 ¥2184”；跟踪测试数 **6278**。
- SPEC/HANDOFF：clean HEAD 全量门禁 **6234/44/0**、UI 16:50 670/670、CI 分片口径、开口程证据与链头断点、站点戳过期提醒、历史“缺口程未验”补订正痕迹。
- RELEASE_BODY：多程口径改为“缺口程 2 段已实测 ¥2184；3+ 段未验”，并加正文门禁断言“缺口程 2 段已实测”。
- RELEASE_PROCESS：发布验收从“诊断卡 7 家/探针 7 chip”改为 **10 张/10 chip**（实测 `/api/health` diag=10、`/api/channel-dims` channels=10）。
- CONTRIBUTING：补 CI 分片说明与快照重建命令；并行会话又对这段做了进一步改写（工作树未提交，不要覆盖）。

### 3.4 验证证据（摘要）

| 验证 | 命令/方式 | 结果 |
|---|---|---|
| 语法 | `tools/test_all.py` 的 compile 目标 | ok |
| 全量非 UI | clean clone at `d5d9071`，`python tools/test_all.py --no-ui --workers 8` | **6234 passed / 44 skipped / 0 failed**（6278，412.05s） |
| UI | `python docs/uitest.py`（独立端口/临时结果） | **670/670，零 JS** |
| tracked count | `git ls-files -z tests` + `pytest --collect-only` | **6278** |
| 4 片同构 | 0/1/3 片 + 第 2 片 | 6230/44/0（6274，之后 +4 测试） |
| 开口程 | profile 副本 + 临时库 | ¥2184 / ¥2183，saved=1，history 2 |
| 链头 | 真浏览器 `page.evaluate("_mcChain")` + 服务端 helper + 提醒 | `SHA→TYO / OSA→SHA` |
| 负控 | 假 CLI flag / 空账本 / n=3/5 分片 / 去掉 UI 岗 | 均按预期报错或 skip |

### 3.5 本轮没有做的事

- 没有推送/打 tag/发 Release/Pages/ghcr/切 live（未授权）。
- 没有重烘静态站（并行会话持有 site 未提交改动；当前戳已过期）。
- 没有提交/覆盖并行会话的 App 隐身/ABI/滑块/策略 WIP。
- 没有验证飞猪（按用户要求）。
- 没有实现其余九家多程、3+ 段多程、去哪儿国际往返（软限流测不出）等能力。
- 没有在真实 GitHub CI 上验证新 4 片（未推送）。

---

### 3.6 追加：App 画中画工作台（2026-11-03 19:30）

用户追加要求：现弹窗太小，完全没达到模拟器本身唤起的体验；允许新增设备 API。
本轮把 App 登录从 520px 弹窗改成：

- **近全屏工作台**：`#lgModal[data-kind="app"]` 为
  `min(1180px,96vw) × min(92dvh,1000px)`；左侧设备按 9:16 顶满、右侧
  280px 控制轨；窄档（<900px）上下布局，390 无横向溢出。
- **专注模式**：隐藏控制轨，设备进一步顶满；Esc 先退出专注，再按一次关闭。
- **可拖动浮窗**：同一块画面移入浮窗继续轮询，可放大/关闭；浮窗期间释放
  页面滚动，恢复后重新锁定；位置限制在视口并记忆到 localStorage。
- **交互**：内联文字输入（保留 prompt 后备）、返回/桌面/最近/退格、长按
  （同坐标 swipe）、桌面滚轮=画面滑动；设备区仍只负责 tap/swipe。
- **设备状态**：新增只读 `GET /api/app-login/info?plat=`，返回分辨率/
  前台 App/会话统计；状态栏显示 `900×1600` 与前台包名。
- **共享弹窗修复**：遮罩/Esc 走 `lgCloseModal()` 时按 `data-kind=app`
  路由到 `appLoginClose()`，不再只藏窗继续轮询。
- **App 图标质感**：App 渠道叠 `.bic-app`（squircle/顶高光/底收影），
  浏览器方标仍 `.bic-ota`；智行旧图底部「酒店真低价」促销条已去除，保留
  官方「智行」字标重组成 256×256 蓝底方标；PiP/浮窗标题带 22px 图标。
  像素门禁 `test_app_zhixing_icon_has_no_promo_banner` 防止促销条回潮。

验证：Playwright 真渲染覆盖 1512/390 尺寸、专注进出、浮窗拖拽/恢复、
浏览器登录弹窗仍 520px、内联输入、tap/swipe、零 pageerror；现有
r729/r730/r805ap/r805be/r814b/app_login_api/session 全绿（65 passed）；
UI **670/670**。截图证据 `_scratch/pip_workspace_1512.png`、
`pip_focus_1512.png`、`pip_float_1512.png`、`pip_workspace_390.png`
（若已清理则按门禁重跑）。

## 4. 证据台账（便于复核，不要当现状）

### 4.1 本轮提交

| Commit | 主题 | 关键内容 |
|---|---|---|
| `67a6ff1` | fix: 会话锁等待补范围校验 | `glbWait` 0–120 范围 |
| `7e4f386` | ci: 全量测试 4 片并发 + 分片覆盖门禁 | matrix、ci_shard、ci-ok、timeouts、r290 修复 |
| `62888c4` | test: 文档 CLI 契约放行 pytest 与 tools 参数 | CLI 契约作用域 + 负控 |
| `47731c9` | test: 账本在并行重建时跳过而不是记产品红 | r793 空表守卫 |
| `faa26f3` | docs: 回写 4 片并发门禁结果与 CI 分片口径 | SPEC/HANDOFF |
| `7d2793b` | docs: 串行回退说明与 CI 分片口径对齐 | RELEASE_PROCESS |
| `90b89ac` | docs: README/EN 补 CI 4 片并发与并集自检说明 | README/EN |
| `5d1e108` | ci: 分片工具自检 workflow 片数一致 | check_workflow + 负控 |
| `a33e1f5` | docs: 发布验收口径改为 10 诊断卡/10 探针 chip | 实测 10/10 |
| `b0519cd` | ci: 分片自检同时守住 UI 独立泳道 | uitest 岗守卫 |
| `aefbdcc` | feat: 携程多程缺口程 2 段接通 + 慢页就绪轮询 | probe + poll + README/正文/矩阵 |
| `61b8b61` | fix: 开口程链头按断点显示，不画成假闭环 | 配置卡 JS + 真浏览器测试 |
| `506829d` | fix: 概览/CSV 多程链头也按断点断开 | `_mc_chain_label` + API 测试 |
| `4f00add` | fix: 多程整单提醒标题也按断点断开 | 提醒标题 + 消费端测试 |
| `d5d9071` | docs: 站点戳标为过期，最终树需重烘再对账 | 站点戳说明 |
| `bae8a37` | docs: 全量门禁 6234/44/0 + CI 分片快照刷新 | SPEC/HANDOFF + ci_durations |
| `4fcdcfb` | docs: 历史多程记录补缺口程实测订正痕迹 | 历史记录订正 |

### 4.2 关键数字

- 全量：**6234 passed / 44 skipped / 0 failed**；总 **6278**；412.05s；workers 8；clean HEAD `d5d9071`。
- UI：**670/670**；零 JS；16:50。
- tracked collect：**6278**（README/EN/SPEC/HANDOFF 同步）。
- CI 快照：clean 树 **854/854**，四组 **1.00**，总 ~2963s；脏树会显示 857 个（含并行未跟踪测试）。
- 4 片同构：**6230 / 44 / 0**（6274；`62888c4` + `47731c9` 第 2 片）；新增 4 项后由 clean 全量覆盖。
- Ctrip 多程：点对点 **¥1476**；缺口程 **¥2184 / ¥2183**；3+ 段无组合卡。
- live：PID 47952（08:58 启动）；`enabled_platforms` 6 家（无 fliggy）；`diag` 7 张（含历史 fliggy）。
- 站点：site `f312a1cee43b` vs webui `3f62d44eb1fe` → **过期**。

### 4.3 关键命令与输出（可复现）

```bash
# 全量门禁（主工作树；不要在并行门禁运行时跑）
python tools/test_all.py --no-ui --workers 8

# 串行回退（与 CI 同一测试集合）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q

# UI 自检（独立端口/临时结果，避免覆盖并行会话结果）
python docs/uitest.py

# CI 分片
python tools/ci_shard.py --stats 4
python tools/ci_shard.py --print 4 0
python tools/ci_shard.py --snapshot _scratch/<run>/pytest.xml

# 已跟踪测试计数（README 口径）
# 用 git ls-files -z tests，过滤 tests/test_*.py，再 pytest --collect-only
```

**干净验证副本（不是 worktree，仅验证）**：

```bash
git clone --shared --no-checkout . _scratch/_gate_clone_<sha>
cd _scratch/_gate_clone_<sha>
git checkout -q <sha>
mkdir -p _scratch && cp -r ../../_scratch/testdeps _scratch/
python tools/test_all.py --no-ui --workers 8
```

注意：副本只用于验证；不要在里面开发/提交；不要把它变成日常开发树。

---

## 5. 领域知识（继续任务必须知道）

### 5.1 渠道 / 矩阵单一源

- 唯一声明源：`core/channels.py`（10 渠道、7 维度、11 轴、`DIMENSION_SCOPE`、`DIMENSION_NOTES`、`CHANNEL_SURFACES`）。
- 契约：`python -m core.channel_contract --strict`，当前 **10 家 × 11 轴无缺口**（登记完整，不等于每家每个能力都实现）。
- 矩阵 UI：设置页能力矩阵；App 行与浏览器行同表；`scope` 是短标签（如 `仅 2 段`、`仅国际`），`note` 是悬停长说明；`y/n/""` 三态必须如实。
- 新增渠道/维度：先改 `core/channels.py`，再跑 contract、`test_r903/r904/r905`、端面矩阵/演示/图标/导出/健康/pacing 派生门禁；不要写死渠道数量，测试宇宙从 `APP_CHANNELS`/`SRX_PLATS` 派生。
- App 5 家：`app_zhixing`、`app_qunar`、`app_fliggy`、`app_ctrip`、`app_tongcheng`；飞猪 App 暂停；App 通道默认关闭/需真机；矩阵中多程 App 缺口为 `multi_city`。

### 5.2 多程数据模型与页面

- 配置：`Route.segments`（2–4 段，from/to 三字码 + 日期）；`_normalize_mc_users` 归一，派生 `from/to/dates/from_name/to_name`；保存前拒绝非法段。
- 存储：`itinerary_daily`（最新一行）+ `itinerary_history`（append-only，按秒去重，90 天）；`segments_key` 是唯一键；`extra` 含 `tripType=MC`、`legs`（不含价格）、`prov{path,url,totalBasis}`。
- 采集：`main.collect_multicity` 按 `segments_key` 去重，只 Ctrip，首段过期跳过，页面总价落库；只采渠道自报总价，**绝不两段相加**。
- 读取：`/api/multicity`（`mode=ro`，库/表缺失诚实空态，GET 不建库）；概览整单卡、来源链接、sparkline（≥2 点）、CSV 导出、整单提醒。
- Ctrip 多程 URL/解析：`multi-<from>-<to>-<from2>-<to2>`，`depdate=d1_d2`；解析器要求组合卡「多程超低价」+「多程含税价」；3+ 段没有组合卡；开口程 2 段可用。
- 慢页：组合卡异步渲染；固定等待会假空；以「多程含税价」为就绪锚轮询；被拦页没有该标签，不能把无标签当有结果。
- 链头：连贯段 `A→B→C`；段间断点 `A→B / C→D`；所有消费者（配置卡/概览/CSV/提醒）必须同构。

### 5.3 CI 细节

- 本地门禁：`tools/test_all.py`（并发：语法 + pytest xdist + UI 分片）；串行回退 `pytest tests/ -q`；`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 必须带，避免本机第三方插件加载崩溃。
- CI：`test` matrix 4 组；`uitest` 独立 job；`ci-ok` 聚合；`concurrency` 取消旧跑；`fetch-depth: 0` + tag 补拉（版本门禁依赖 tag）；Chromium 缓存；Noto CJK 字体（报告/表格度量）。
- 分片工具：耗时快照来自全量 JUnit；`--stats N` 同时校验 workflow；`--print N K` 输出文件列表；新文件默认 20s；快照偏了会均衡变差，测试结构大改后重建。
- 真实 CI 计时：旧 -n 4 约 11.5 分钟；新 4 片预期 6–8 分钟（估计，需真实推送验证）；UI 约 6 分钟。

### 5.4 发布 / 站点 / live

- Release 正文 canonical：`docs/RELEASE_BODY.md`（完整产品介绍 + 占位符；不是 changelog）。
- 四资产：Windows/Linux/macOS arm64/macOS x64 zip + `SHA256SUMS.txt`；Release 正文/资产/CI/Pages 同源。
- 站点戳 = **sha256(webui.py)[:12]**，不是 commit SHA；webui 一改即过期；发布前 `python docs/demo_build.py` 重烘，再 `python docs/release_align_check.py --local`（目标 25/25；本轮尚未在最终树跑）。
- live 8765：先查进程启动时间 vs webui mtime、cwd；主树改动不等于 live 生效；重启/切树/切端口都要授权；SPA 需 Ctrl+F5。
- 当前线上/本地 Release 口径有 **ab04c22 vs e65cee1** 的待复核差异（§2.5）；发版前用 API 核 tag/Release 目标、四资产 digest、Pages、ghcr digest，不要单方断言。
- 发布七步、回滚见 `docs/HANDOFF_GUIDE.md` / `docs/RELEASE_PROCESS.md` / `docs/LIVE_PROMOTION_RUNBOOK.md`。

### 5.5 App / 并行 WIP

- 并行会话正在做：设备指纹/隐身、ABI 校验、显示/加固、滑块、策略引擎、挑战检测增强等；新增模块见 §2.6。
- 不要启用飞猪 App；途牛 App 在 MuMu 6.0 不支持（H5 是通路）；App 采集与 live 共用设备，抢前台会让 qunar/zhixing 记 0；动手前看 monitor.log 与设备占用。
- App 渠道状态必须按“入口/日历/明细/往返”分面，`y/n/""` 只有真机/账本证据才能升；不能把“产品有入口”写成“采集已接”。

### 5.6 测试隔离 / 编码 / 主机

- xdist `--dist loadfile`；同文件用例共享进程，全局 `_State.cfg/boot_cfg`、demo 端口、默认 DB 都可能被前序用例污染。
- 冻结树/空库场景：账本可能刚建空文件、表未 create；环境竞态应 skip 并给原因，不要记产品红。
- 门禁前后源码哈希 pin；期间被并行改写则整轮作废。
- Windows：GBK print emoji 崩；`PYTHONIOENCODING=utf-8` 或 `reconfigure(errors="replace")`；测试/脚本有兜底不代表可以直接 print 生僻字。
- EOL：追加只产裸 LF；混 EOL 是 bug；用字节核对，不要用 `git diff` 猜。
- 共享进程：不要杀陌生进程；先看 CreationDate/CommandLine；只清自己的挂死 pytest。

---

## 6. 操作手册（下一会话照做）

### 6.1 开工检查（先做，不要先改代码）

1. 读顺序：本文件 §0–§2 → `docs/EXECUTION_SPEC_LATEST.md` §1.0 → `docs/HANDOFF_CAPABILITY_MATRIX.md` §0 → 上一轮 `SESSION_EXPERIENCE_GUIDE_2026-11-02.md`（若在）→ `docs/HANDOFF_GUIDE.md` / `RELEASE_PROCESS.md`。
2. `git branch --show-current`、`git log -5`、`git status --short`；确认是否仍有并行 WIP、HEAD 是否变化。
3. 查活跃进程：`pytest` / `docs/uitest.py` / demo 服；有全量门禁在跑时**不要开第二轮**。
4. 查 live：8765 进程 PID/启动时间/命令行；`/api/health` 的 `enabled_platforms` 与 `diag`；飞猪是否被意外启用。
5. 查数字：`git ls-files -z tests` + `pytest --collect-only` 得 tracked count；对比 README/SPEC；不要拿脏树全量数字当发布口径。
6. 查站点戳：`sha256(webui.py)[:12]` vs `docs/site/index.html` 的 `code:`；确认是否过期。
7. 查 Release/tag/线上状态（只读）：GitHub API/ Releases/ Pages/ ghcr；不要假定本地 tag 等于线上。
8. 决定本轮做哪一项，按 §8 优先级；一次只打一个高价值面。

### 6.2 本地全量门禁

```bash
python tools/test_all.py --no-ui --workers 8     # 全量非 UI；源码哈希 pin
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q   # 串行回退
python docs/uitest.py                            # UI 全量；独立端口/结果文件
```

- 之前先确认没有并行门禁在跑；跑前记录 `webui.py/main.py/core/channels.py` 哈希，跑后比对。
- 只有带 `passed/skipped/failed` 摘要的完整跑才算绿证；JUnit 0 failure/error 但 orchestrator exit 1 时，先解析 JUnit 排除 teardown 噪音。
- 失败先分流：单跑通过 → 并发/时序假红；仍失败 → 真问题，修实现不改门禁。
- 工作树有并行 WIP 时，优先用 `_scratch` 干净 clone 验证 **已提交 HEAD**；不要在 clone 里提交/开发，也不要切 worktree。

### 6.3 CI 分片

```bash
python tools/ci_shard.py --stats 4
python tools/ci_shard.py --print 4 2 | tr ' ' '\n' | head
python tools/ci_shard.py --snapshot _scratch/test_run/<ts>/pytest.xml
```

- `--stats 4` 同时校验 workflow：矩阵 4 组、`--print 4`、loadfile、`ci-ok`、取消旧跑、独立 UI 岗；任一漂移应红。
- 新增测试文件不在快照里也会按 20s 进组；不要在测试结构大改后继续用旧快照而不重建。
- 真实 CI 成功后，在 GitHub 上看 4 个 `test (0..3)` + `uitest` + `ci-ok` 的耗时与缓存命中；失败摘要按每片 `pytest.log` 的 `FAILED/ERROR` 抓。

### 6.4 真实渠道探测（只读、临时态）

- **飞猪禁止探测**；Ctrip 可用受信 profile 副本。
- 模板：`_scratch/live_mc_openjaw.py`（若还在）：
  - 复制 `user_data/ctrip` 到临时 `user_data/ctrip`，删 `Singleton*`；
  - `CtripCrawler({"user_data_dir": 临时根, "headless": True, ...})`；
  - `PriceStorage(临时 db)` + `main.collect_multicity`；
  - 打印 URL/价格/legs/prov；不写 live。
- 价格口径：只读页面自报「多程含税价」；不要两段相加；价格是实时值，示例会变（¥2184→¥2183）。
- 慢页：组合卡异步；固定 9s 不够；等「多程含税价」最多 +12s；被拦/空页与“没有组合卡”要分开。
- 证据：保存页面文本/截图/URL；若文本只有排序标签「多程超低价」而没有「多程含税价」，不能判定有整单。
- 一次 `saved=0` 不要立刻改判不支持：先看日志/正文/是否慢页；重跑一次；把抖动写进边界。

### 6.5 UI / 站点 / 对账

```bash
# UI（独立端口 + 临时结果，避免覆盖并行结果）
UITEST_PORT=<free> UITEST_RESULT=_scratch/ui_<tag>.txt PYTHONIOENCODING=utf-8 python docs/uitest.py

# 站点重烘（先确认没有并行改 site；会改 docs/site/index.html）
python webui.py --demo --port 8799      # 另一个终端
python docs/demo_build.py

# 发布对账（本地，目标 25/25；工作树必须干净）
python docs/release_align_check.py --local
```

- 站点戳必须等于当前 `webui.py` SHA256[:12]；改 webui 后不重烘，`release_align_check` 会红。
- `docs/uitest_result.txt` 是受跟踪发布产物；重跑 UI 后如需发布，提交结果并同步 README 的 UI 断言数；并行会话可能也在改它，按 hunk/归属处理。
- 截图/README 引用/资产 digest/四平台包都要在同一发布树核；不要用旧包冒充新构建。

### 6.6 发布（只有用户明确授权才做）

1. 冻结并行写入；确认 `git status` 干净或只剩已归属改动；不覆盖 WIP。
2. 最终树全量门禁 + UI + tracked count + `release_align_check --local` 25/25。
3. 重烘站点，提交所有发布产物（README/正文/资产/结果）。
4. 按 `docs/HANDOFF_GUIDE.md` / `RELEASE_PROCESS.md` 七步：tag（实际构建 SHA）、push、release-build 四平台、四资产 + SHA256SUMS、Release 正文（完整初版介绍 + Contributors）、Pages 部署 1 个、ghcr 新 SHA、live 切树/重启/回滚。
5. 在线对账：Release 名称/正文版本/源码 SHA/四资产 digest/CI/Pages/ghcr/live；不要只核本地。
6. 无授权时，任何一步都不做。

### 6.7 并行会话协作

- 不要 `git add -A`/`git add .`；只按明确路径 stage。
- 不要整文件 stage `webui.py`；并行改动时按 hunk `git apply --cached`，并核对 md5。
- 绝不 `git checkout -- webui.py`（会抹掉并行未提交改动）；需要回退只回退自己的 hunk。
- 提交前 `git status` + `git diff --cached` 核对；HEAD 可能被并行会话推走，提交后确认自己的提交仍在。
- 并行会话提交后，重新冻结/重跑最终树门禁；不要把旧绿证挂到新 HEAD。

### 6.8 故障排查速查

| 现象 | 先查 | 处理 |
|---|---|---|
| 全量红但单跑绿 | 前序用例污染/端口/全局 cfg/DB | 分流；修隔离或等门禁独占 |
| `no such table` | 空库/建表中 | 环境竞态 skip（见 r793） |
| 开口程/多程 saved=0 | 页面是慢/空/被拦？ | 看正文/截图；等总价锚；重跑一次；不要改判支持 |
| 链头显示 `A→B→A` | 是否开口程/段间断点 | 用 `_mc_chain_label`/`_mcChain`，不要 naive join |
| README 数字不匹配 | 是否含未跟踪测试/口径 | `git ls-files -z` + collect；更新 tracked 口径 |
| 站点戳红 | webui 是否改过 | 重烘 demo_build 后 align |
| CI 片数不一致 | matrix/`--print`/stats | `--stats 4` 的 workflow 自检会点名 |
| 疑似 live 没改 | 进程启动时间/cwd/mtime | 同步树/重启需授权；SPA Ctrl+F5 |
| GBK 崩 | print emoji/中文子进程 | UTF-8/reconfigure；不要重跑整轮门禁 |
| 并行提交冲突 | `git status`/HEAD/暂存区 | 只 stage 自己的路径/hunk；不覆盖 |

---

## 7. 本次经验与判据陷阱（按杀伤力排序）

### 7.1 固定等待会把“慢页”误判成“没有能力”

- 现象：Ctrip 多程固定等 9s，首跑 `saved=0`，控制器日志“结果页没有组合卡”；补证据时 12s 的正文里明明有「多程超低价」+「多程含税价 ¥2184」。
- 根因：组合卡异步渲染；不同轮次加载时间不同。
- 修法：以**总价标签**「多程含税价」为就绪锚轮询（最多 +12s），出现即解析；被拦页没有该标签，最多多等这一段。
- 教训：能力结论不能建立在一次固定等待上；先看页面正文/截图，再判定“没有”。
- 仍未完全消除：复跑有一次 `saved=0`，随后成功；页面慢/空抖动存在。下一轮可评估是否延长窗口/重试一次，但不要无限等待或伪造数据。

### 7.2 「多程超低价」这几个字可能只是排序标签

- 开口程截图里，“多程超低价”既是组合卡标题，也可能是排序控件文本。
- 判定必须同时看到**总价行 `¥N` + 「多程含税价」**；仅字符串存在不算有整单。
- 解析器要求 `lines.index("多程超低价")` 后 120 行内出现价格 + 含税标签；证据抓取要看上下文。

### 7.3 链头是一个“多消费者”契约，不能只修一处

- 同一链头出现在：配置卡 JS、概览卡/CSV 服务端 `mc_routes.label`、提醒标题。
- 旧实现三处各自 naive join，开口程全部假闭环。
- 修法：先枚举所有消费点（`rg "→"`/`label`/`chain`），统一 helper（服务端 `_mc_chain_label`、JS `_mcChain/_mcNames`），再逐个消费端加测试。
- 测试：真浏览器求值（配置卡）、服务端 helper（概览/CSV）、提醒消费端（标题/总价/legs）。

### 7.4 分片并发会把隐藏的测试隔离缺陷打出来

- r290：`_State.cfg/boot_cfg` 全局被后台线程重载；测试改全局后断言 `saved` 失败。
- r793：另一用例刚建空 DB、表未 create；只包 `connect` 的守卫接不住查询期 `no such table`。
- 修法：测试注入配置解析结果；把查询也纳入 `DatabaseError` 环境守卫，skip 并给原因。
- 负控：假 CLI 参数、空账本、n=3/5 分片、去掉 UI 岗都必须按预期红。
- 教训：分片不是“只是换个进程”；它暴露顺序/全局/环境竞态，修的是隔离，不是放宽断言。

### 7.5 文档契约会误判工具参数

- `CONTRIBUTING` 里写 `pytest --dist loadfile`、`tools/ci_shard.py --stats/--snapshot`，被“文档 CLI 参数必须是产品 argparse”契约当成产品假参数。
- 修法：契约放行 `pytest` 与 `tools/*.py` span；产品命令仍检查。
- 负控：在 CONTRIBUTING 注入 `python main.py --definitely-not-a-flag` 必须红；移除后必须绿。
- 教训：改门禁作用域要有负控；不要用“删文档反引号”绕过。

### 7.6 计数口径

- README 的数 = **已跟踪测试收集数**（`git ls-files -z tests` + `pytest --collect-only`），不是脏树全量。
- 本轮从 6274→6275→6276→6277→6278，都是新增测试带来的；每次同步 README/EN/SPEC/HANDOFF。
- 实测命令输出 `6278 tests collected in 81.21s`；与 clean 全量 6234+44=6278 对齐。
- 教训：数字变化必须带口径；不要拿工作树全量（含并行未跟踪测试）写 README。

### 7.7 站点戳与发布口径

- 站点戳 = `sha256(webui.py)[:12]`，不是 commit；webui 改一行就过期。
- 本轮 webui 从 `f312a1cee43b`→`3f62d44eb1fe`，site 仍 `f312a1cee43b`；SPEC 已标注过期。
- 发布前必须重烘并跑 align；不要在过期站点上宣称“站点同源”。

### 7.8 live / diag / enabled / Release 的四种“看起来一样”

- `enabled_platforms` = 实际参与调度的渠道；live 当前 6 家（无 fliggy）。
- `diag` = 健康卡显示的历史渠道集合（含 fliggy 历史卡），不等于在采集。
- live 工作树可能不是主树；进程启动时间/mtime/cwd 先查。
- 本地 tag `v1.0=e65cee1` 与文档记录的 Release `ab04c22` 不一致；发版前用 API 核，不要以本地 tag 断言线上。
- 教训：状态词相同≠语义相同；按归属翻译（同 pending 在 App 会话/浏览器槽位含义不同）。

### 7.9 并行会话与门禁纪律

- 本轮多次遇到并行会话连续跑门禁/改文件；门禁结果会被源码哈希 pin 作废。
- 规则：门禁独占串行；跑前/跑后哈希；不要杀陌生进程；不要覆盖 WIP；提交只按自己的路径/hunk。
- 用户明确“不要切 worktree”：本轮后期改用 `_scratch` 干净 clone 验证 HEAD；clone 只验证，不开发。
- 当前实际分支是 `feat/multicity`，不是 `main`；若用户意指 branch main，先确认再合并/切换，不要擅自 push/merge。

### 7.10 诚实性

- 空/失败/未验证/不支持要分开；空结果不等于登录失效；HTTP 200 也可能是门拒；限流不等于验证墙。
- 价格：只取渠道页面自报总价；demo/mock 不得标“正常”；`—` 是无样本；0% 要有分母。
- 发布：没有真实 CI/资产 digest/Pages/ghcr 证据，不要写“已发布/同源”。

---

## 8. 未完成与优先级（下一会话的路线图）

### P0（先把最终树变绿、可发布）

1. **等并行会话提交 WIP**：26 项 App/stealth/ABI/滑块/策略改动；等它 commit 后重新看 HEAD/status。
2. **最终树全量门禁**：主工作树或干净 clone（不切 worktree）跑 `tools/test_all.py --no-ui --workers 8`；UI `docs/uitest.py`；tracked count；源码 hash pin。
3. **重烘静态站**：`python docs/demo_build.py`（先确认 site 无并行未提交冲突）；站点戳=当前 webui。
4. **发布对账**：`python docs/release_align_check.py --local` 目标 25/25；修 README/截图/结果/资产口径。
5. **复核 Release/tag/live 口径**：GitHub API 核 v1.0 目标/四资产 digest/Pages/ghcr；解决 ab04c22 vs e65cee1 的差异。
6. **无授权不发布**：以上只准备，不 push/tag/Release/Pages/ghcr/live。

### P1（能力继续推进，按证据）

7. 多程：3+ 段无组合卡（验证过，不要硬做）；其余九家未接；开口程已验；如要扩展，先数据模型/采集/配置/概览/提醒/CSV 全链路。
8. 国际往返：去哪儿国际往返仍软限流/测不出；同程/途牛/飞猪/携程等按矩阵范围；不要用单程价补。
9. App 渠道：等并行会话收口；飞猪不启用；途牛 App 不做；真机状态/账本/矩阵三对账。
10. 矩阵/契约：新渠道/新维度按 `core/channels.py` + contract + r903/r904/r905 派生；不要写死渠道数。
11. 产品化/UI：按用户审美继续扫，但先保证已有 670/670 与真实渲染；像素/命中/最窄档证据。
12. CI：真实推送后核 4 片/缓存/`ci-ok` 耗时；测试结构大改后重建耗时快照。

### 验收标准（任何一条都按此）

- 有最小复现/证据；根因明确；改实现不改门禁；正控+负控；定向+相关回归；必要时真浏览器/真机/live 渲染。
- 数据声明 `y/n/""` 有代码或真机/账本证据；界面能识别/聚合；文案同列同构。
- 数字带口径；状态三态分明；空态可指导；失败可判断。
- 不造假、不绕过、不覆盖并行 WIP、不无授权发版、不切 worktree。

---

## 9. 文件 / 符号 / 命令索引

### 9.1 关键文件

| 文件 | 作用 |
|---|---|
| `core/channels.py` | 10 渠道 × 7 维度 × 11 轴唯一声明源；`DIMENSION_SCOPE/NOTES` |
| `core/channel_contract.py` | 契约门禁（`--strict`） |
| `core/multicity.py` | 段归一/URL/`segments_key`/`build_mc_extra` |
| `crawlers/ctrip.py` | Ctrip 单程/RT/多程采集；`fetch_multi`、`_multi_text_with_total` |
| `crawlers/ctrip_multicity.py` | 多程 URL/解析器 |
| `crawlers/base.py` | `channel_slot`、浏览器/指纹/会话基座 |
| `main.py` | 调度、`collect_multicity`、轮次 |
| `webui.py` | 单文件 SPA + HTTP API；`_mc_chain_label`、`_mcChain/_mcNames`、`_multicity_payload`、`_multicity_alert_round`、`mcCardHTML`、`monMCCard` |
| `core/storage.py` | `save_itinerary`、`itinerary_history`、日桶/聚合 |
| `.github/workflows/ci.yml` | CI 4 片 matrix + UI + `ci-ok` |
| `tools/ci_shard.py` | 分片快照/规划/打印/workflow 自检 |
| `tests/ci_durations.json` | 分片耗时快照 |
| `tools/test_all.py` | 本地并发门禁（语法 + pytest + UI 分片 + 哈希 pin） |
| `docs/uitest.py` | 全功能 UI 自检（670 断言） |
| `docs/demo_build.py` | 静态演示站烘焙 |
| `docs/release_align_check.py` | 发布对账（`--local` 25 项） |
| `docs/RELEASE_BODY.md` | Release 正文 canonical 模板 |
| `docs/EXECUTION_SPEC_LATEST.md` | 完整执行口径（§1.0 当前状态；§12 历史） |
| `docs/HANDOFF_CAPABILITY_MATRIX.md` | 矩阵交接/现场核验 |
| `docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md` | 上一轮完整经验书（工作树未提交时以文件为准） |
| `docs/SESSION_EXPERIENCE_GUIDE_2026-11-03.md` | **本文件** |

### 9.2 API / 页面面

- `/api/health`：`enabled_platforms`、`diag`、`stats`、`paths`。
- `/api/channel-dims`：10 渠道、dims/surfaces/notes/scopes。
- `/api/multicity`：只读整单（`route_id/segments_key/limit/history`；库/表缺失诚实空态）。
- `/api/config`：读写配置（保存有 CSRF/来源闸门；多程归一）。
- 多程面：配置卡（`mcCardHTML`）、概览整单卡（`monMCCard`）、CSV（`mcCsvRows/mcExport`）、提醒（`_multicity_alert_round`）。
- 健康/诊断/探针/矩阵/登录卡：共用 `SRX_PLATS`/`APP_CHANNELS` 派生，不要写死数量。

### 9.3 10 条最重要的命令

```bash
git status --short && git log -5 --oneline
python -m core.channel_contract --strict
python tools/test_all.py --no-ui --workers 8
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
python docs/uitest.py
python tools/ci_shard.py --stats 4
python tools/ci_shard.py --print 4 0
python tools/ci_shard.py --snapshot _scratch/test_run/<ts>/pytest.xml
python docs/demo_build.py
python docs/release_align_check.py --local
```

---

## 附录 A：用户目标原文（按语义分段；技能名是目标标签）

> 以下为主目标段的语义整理，保留关键限定；`using-superpowers` / `multi-agent-workflow` / `Frontend Design` 是用户给本轮的方法/能力目标标签，不是逐字原话，不要在引用中伪装成用户措辞。
>
> “把这六个会话目标未完成以及或者可以做到更好的继续推进，核心 10 渠道 5pc+5app 平台能力矩阵策略 N 多维度统一加强对齐（飞猪暂时账号被风控了，先不验证飞猪了）尤其是可配置可观测可干预可见性可溯源可识别可区分可幂等语义清晰可指导可判断等等和全项目覆盖以及后续加渠道的统一设计，样式统一，能力统一，约束统一，调度统一，策略统一，能力统一，聚合分类等等，页面产品化，微信扁平化布局交互体验，github 的代码文档说明 tag 包部署包镜像初版式维护体验！继续扫荡各个角落！看 doc 下的多会话交割文档以及会话历史！做到极致。包括 CI 能不能改成并发，提升测试效率。就在主分支上开发，不要切 worktree。”
>
> 目标中列出的 7 个会话 ID（历史叙述里常称“六条会话线”，以实际列表为准）：
> `b44d19e3-be11-4dc8-9c32-f165d34050dd`、`3f298749-4eb2-4659-91a3-ded8de09b2b`、
> `254eb2bc-871d-47b0-bba8-07793a2c605a`、`24a5d7af-6537-420e-bfb3-f640e401e047`、
> `19b6bd89-99a6-48d0-a914-beab3ba2b2a7`、`6892c569-2a74-45ce-9097-680392e9dde5`、
> `e25668d6-7f49-495c-a0b9-2551849c1fd5`。

**语义拆解**：10 渠道 = 5 浏览器 + 5 App；能力矩阵 = 7 维度 × 11 轴；统一 = 样式/能力/约束/调度/策略/聚合 + 后续渠道接线；产品化 = 微信扁平 + 可指导/可判断；GitHub = 代码/文档/tag/四平台包/部署包/镜像的初版滚动维护；方法 = 先复现/TDD/验证/并行审查/真实渲染；边界 = 飞猪暂停、不绕过、只采渠道总价、无授权不发布。

## 附录 B：本轮提交（按时间）

见 §4.1。补充早期基础提交：`1dba69e`（Playwright 缓存）、`3cce803`（多程 2 段矩阵 + 身份/风险评估）、`44e63c2`（yield/模拟器调优模块）、`67a6ff1`（glbWait 范围）。本轮后续全部提交均在 `feat/multicity`，未推送。

## 附录 C：快照数字（会漂移）

- 时间：2026-11-03 17:40 +0800。
- 分支/HEAD：`feat/multicity` / `4fcdcfb`。
- 工作树：26 项未提交/未跟踪（并行 WIP）。
- tracked collect：6278。
- 全量：6234 passed / 44 skipped / 0 failed；412.05s；workers 8；clean HEAD d5d9071。
- UI：670/670；零 JS；16:50。
- CI 快照：854/854；四组 1.00；~2963s。
- 多程：点对点 ¥1476；缺口程 ¥2184/¥2183；3+ 无组合卡；其余九家 `""`。
- live：PID 47952（08:58 启动）；enabled 6（无 fliggy）；diag 7（含历史 fliggy）。
- 站点：site `f312a1cee43b` vs webui `3f62d44eb1fe`（过期）。
- Release：文档记录 v1.0→ab04c22（v1.5.307）；本地 tag v1.0=e65cee1；待 API 复核。

## 附录 D：需要用户决策的问题

1. **发布授权**：是否授权推送/打 tag/发 Release/Pages/ghcr/切 live？授权范围（只推 main？是否重建资产/镜像？是否切 live？）。
2. **分支语义**：“主分支”是否指 `main`？当前所有新提交在 `feat/multicity`；是否要合并/切换到 main，何时？
3. **并行会话**：它的 App/stealth/ABI/滑块/策略 WIP 是否纳入本轮发布？等它提交还是先冻结？
4. **飞猪**：继续保持暂停（默认）；恢复必须用户明确要求。
5. **多程边界**：3+ 段无组合卡、其余九家未接，是否接受“仅携程 2 段（含缺口程）”作为当前发布口径？
6. **站点/发布节奏**：是否现在重烘站点并准备发布，还是等并行 WIP 收口？

## 附录 E：禁做清单（贴墙）

- 不探测/启用飞猪；不绕过登录/验证码/滑块/人脸。
- 不把单程价相加当往返/多程总价；不编造矩阵 `y`。
- 不无授权 push/tag/Release/Pages/ghcr/live。
- 不切 worktree 开发；不在 clone 里提交。
- 不 `git add -A`/`git add .`；不整文件暂存 `webui.py`；不 `git checkout webui.py`；不覆盖并行 WIP。
- 不在另一轮全量门禁运行时开第二轮；不杀陌生进程。
- 不把脏树/未跟踪测试数字写进 README 发布口径。
- 不把 demo/mock 标“正常”；不把“没拿到/没解析出/门拒”记成 `empty`。
- 不在 GBK 下直接 print emoji；追加文本只产裸 LF。
- 不把站点戳当 commit SHA；webui 改动后必须重烘。

## 附录 F：下一会话 10 步开工

1. 读本文件 §0–§2。
2. 读 `EXECUTION_SPEC_LATEST.md` §1.0 与 `HANDOFF_CAPABILITY_MATRIX.md` §0。
3. `git status --short`、`git log -5`、查并行 pytest。
4. 查 live 8765 PID/health；确认无 fliggy 扫描。
5. 查 tracked count vs README；查站点戳。
6. 等并行 WIP 提交（或明确冻结范围）。
7. 在最终树跑全量 + UI；记录哈希/run dir。
8. 重烘站点；跑 `release_align_check --local` 25/25。
9. 复核 Release/tag/资产/Pages/ghcr；需要授权就问。
10. 按 §8 继续能力/产品化；一次只打一个高价值面。