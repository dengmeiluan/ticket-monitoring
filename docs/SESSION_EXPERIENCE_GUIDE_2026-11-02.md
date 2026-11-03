# 机票监控台 · 2026-11-02 长会话完整经验指导书

> **读者对象**：接手继续本项目的下一个会话（AI 或人类协作者）。
> **文档性质**：这不是普通交接清单，而是本次长会话的**完整经验书**——目标、期望、已落地改动、当前真实状态、判据陷阱、操作手册、未完成事项与不能做的事，全部写在这里。
> **快照时间**：2026-11-02 21:10（Asia/Shanghai）。所有数字/进程/端口都会漂移；开工前必须按 §6.1 重新实测。
> **权威关系**：
> - `docs/HANDOFF_FULL_SESSION.md`：项目总纲、12 项原始目标与验收标准（2026-11-02 已更新，仍是最完整的目标来源）。
> - `docs/HANDOFF_GUIDE.md`：发版七步、文档门禁、通用操作纪律。
> - `docs/SESSION_EXPERIENCE_GUIDE.md`：r794–r812b 的上一版经验书；其「当前状态」段已过期，只保留历史背景。
> - **本文**：2026-11-02 续作（r794–r819+）的完整经验 + 当前状态 + 继续方法。
>
> **引用性质说明**：用户目标在本文中一律用「用户的目标是……」的转述口吻；带「」的短句只有在明确标注时才视为原话。`using-superpowers`、`multi-agent-workflow`、`Frontend Design` 是**用户给本轮定的方法/能力目标标签**，不是逐字原话，不要当成用户措辞偏好。
>
> **使用方式**：先读 §0–§1，再按 §6.1 开工；涉及判据/red 项查 §4/§7；涉及 App/发布查 §5/§8；不要跳过 §10 的开工/收工检查。

---

## 目录

- [0. 30 秒速览](#0-30-秒速览)
- [1. 用户目标与期望（完整范围）](#1-用户目标与期望完整范围)
- [2. 当前权威状态（2026-11-02 21:10）](#2-当前权威状态2026-11-02-2110)
- [3. 已落地改动与证据](#3-已落地改动与证据)
- [4. 当前未完成、已知风险与红线](#4-当前未完成已知风险与红线)
- [5. 领域知识：渠道、文案、App、指纹](#5-领域知识渠道文案app指纹)
- [6. 操作手册（下一会话照做）](#6-操作手册下一会话照做)
- [7. 经验教训（按杀伤力排序）](#7-经验教训按杀伤力排序)
- [8. 下一步优先级与验收标准](#8-下一步优先级与验收标准)
- [9. 关键文件索引](#9-关键文件索引)
- [10. 开工/收工检查清单](#10-开工收工检查清单)
- [附录 A：四个会话线与目标映射](#附录-a四个会话线与目标映射)
- [附录 B：当前进程、路径、命令](#附录-b当前进程路径命令)
- [附录 C：途牛 App 安装包 / 架构 / 市场核查](#附录-c途牛-app-安装包--架构--市场核查2026-11-02-补充)
- [附录 D：发布 / issue / 测试口径补充](#附录-d发布--issue--测试口径补充)
- [附录 E：本轮用户最后确认的决策](#附录-e本轮用户最后确认的决策)
- [附录 F：本指导书覆盖清单](#附录-f本指导书覆盖清单)

---

## 0. 30 秒速览

**一句话现状**：源码发布基线是 v1.5.307 / `0d4b058`；主工作树有 108 项未提交改动（21 项未跟踪），新增了 5 个 App 渠道模块和 `profile_headers`，但**尚未发版**；8765 实际运行的是另一棵发布树 `D:\idea_project\_release_final_72d`（只含 2 个 App 渠道），**主树改动不会自动出现在 8765**。飞猪已被识别，**主树和 live 配置都已暂停飞猪采集**（含 warmup）；不要恢复。

当前关键事实（21:10 快照）：

- 主树 `APP_CHANNELS`：`app_zhixing, app_qunar, app_fliggy, app_ctrip, app_tongcheng`（10 渠道宇宙：5 浏览器 + 5 App）。
- live 8765 的 `_release_final_72d`：`APP_CHANNELS` 仍是 `app_zhixing, app_qunar`；新 App 模块不在 live 树里。
- 8765 PID `33800`，cwd `D:\idea_project\_release_final_72d`，下次抓取计划 21:15 左右；`/api/health.enabled_platforms` = `qunar, tongcheng, tuniu, ctrip, app_zhixing, app_qunar`（**没有 fliggy**）。
- 主树/live 的 `config.yaml`：用户 `platforms` 和 `crawler.warmup.platforms` 都已移除 `fliggy`；飞猪浏览器采集/预热停止。
- 主树新增但**未跟踪**：`crawlers/app_ctrip.py`、`app_ctrip_parse.py`、`app_tongcheng.py`、`app_tongcheng_parse.py`、`app_fliggy.py`、`app_fliggy_parse.py`、`core/android/ocr.py` 及对应测试；这些是并行会话/上一轮落下的 WIP，**不要覆盖，先审查/验证**。
- 主树近期测试：App + header + fingerprint 组合 **88 passed**；链接/文案回归 **177 passed**；`test_qunar_honesty + test_r394` 仍有 **1 红 / 25 绿**，红项是并行会话的 Qunar 登录探测语义漂移（见 §4）。
- 当前不能宣称「全量绿」或「可发版」：没有跑全量，工作树脏，live 与主树分叉。

---

## 1. 用户目标与期望（完整范围）

### 1.1 四条会话线的共同目标

用户最初把四个会话 ID（`b44d19e3…`、`3f298749…`、`254eb2bc…`、`24a5d7af…`）放在同一个目标下：把这四个会话**未完成或可做得更好的地方继续推进**。共同目标不是单一 UI 修补，而是：

1. **7 渠道平台能力矩阵 + N 维统一**：可配置、可观测、可干预、可见性、可溯源、可识别、可区分、可幂等、语义清晰、可指导、可判断。
2. **全项目覆盖**：不只首页/检索页，健康、配置、探针、登录、推送、导出、演示站、文档都要对齐。
3. **后续加渠道的统一设计**：新增浏览器/App 渠道时，注册、矩阵、UI、门禁、文档、登录、演示数据、图标/配色、导出等要有单一来源和清单，不能各写一份。
4. **页面产品化 + 微信扁平化**：紧凑控制台、干净表面、发丝线、同列同构、无无意义留白、展开/收起同坐标。
5. **GitHub 初版式维护**：代码/文档/说明/tag/包/部署包/镜像/Release 都以「初版完整信息」维护。
6. **关闭所有 issue**，并避免同类问题复发。
7. **Release 描述必须是初版完整产品介绍**，不是 changelog；贡献者按 author 身份署名（空提交不计）。
8. **App 渠道**：飞猪、携程、同程、途牛 App；先安装让用户登录；需要人脸识别的渠道先搁置。
9. **风控边界**：不绕过验证码/人脸/风控；渠道被识别就停止/降级；不伪造数据。
10. **具体渠道事实**：途牛 PC 有软风控，不查太远日期；途牛 H5 国际与国内同页，在城市选择弹窗里切「出境·中国港澳台」/「国际多程」；飞猪被识别后先停采集。

**11 条质量轴的验收含义**（统一语言，避免各页面各写一套）：

- **可配置**：每个渠道/维度/阈值有配置入口或明确的只读边界；保存后能读回。
- **可观测**：账本/健康/诊断能看到每次尝试的路径、状态、行数、时间、证据。
- **可干预**：每个 `advice.action` 在界面有落点；干预前后同窗口可比、治好判定封顶。
- **可见性**：等待/需人操作/被拦/失败/空都有可见状态；不能只做幂等拒绝。
- **可溯源**：明细能回到真实 URL/接口/响应证据；不拿别的端或历史样本冒充。
- **可识别**：渠道 id、中文名、图标、颜色、端面标签唯一可认；不露裸 id。
- **可区分**：渠道/端/域/路径/会话维度分开计数；同数字必须同口径。
- **可幂等**：重复点击/重复扫描/重试不产生重复记录或副作用；幂等要能看见。
- **语义清晰**：同一个词只表达一件事；`empty/login/blocked/unsupported` 不混用。
- **可指导**：失败/空/被拦都给出下一步可执行动作，不只报错。
- **可判断**：用户能根据界面/账本判断「有没有票、哪条通路、是否该重登、是否被风控」。

> 12 项原始目标的完整表格（登录统一、节流独立、多渠道可区分、干预闭环、进程安全、配置全可达、GitHub issue/PR、发版规范、测试可移植、7 渠道能力一致等）见 `docs/HANDOFF_FULL_SESSION.md` §1.1。**不要只读本文的摘要就开工**；该文件仍是目标与验收的最高来源。

**12 项目标的速查（归纳，非逐字原话；状态不是「已完成」的证明）**：

| # | 目标 | 当前可核对的证据/缺口（21:10 快照） |
|---|---|---|
| 1 | 登录统一：所有厂商+渠道必须登录；飞猪 PC/H5 分开；无「建议登录」 | 既有发布基线已按政策；新 App 渠道的登录卡/配置未在 live 验证，启用前必须补 |
| 2 | 节流板块独立，不塞在全局参数里 | 既有 `#paceBox` 基线；本轮未重跑 UI |
| 3 | 多渠道可区分：健康按 domain/path/session 分域，未扫描如实标 | 既有健康卡/矩阵；新增 3 个 App 渠道需补健康/未扫描行 |
| 4 | 节流面板 UI 质感/排版/交互 | 既有像素基线；本轮文案/布局改动要重新截图验收 |
| 5 | 干预闭环：advice.action 每个值有落点；前后同窗口、治好封顶、写失败留痕 | 既有实现；新增渠道/新动作需补落点与测试 |
| 6 | 进程级安全/健壮：CSRF、重启锁序、异常不静默 | 既有 `/api/restart`/CSRF；本轮用 restart 验证 live |
| 7 | 配置项全部可达/可配；热更新或重启路径明确 | `test_r601`/`test_r634` 既有；App 渠道配置 chip/新键需补 |
| 8 | GitHub issue/评论/小红书问题关闭并防复发 | 上一轮确认 0 open；**本轮未重新核对**，开工用 gh/curl 复查 |
| 9 | 所有 PR/贡献者以 author 身份进 Contributors（空提交不计） | 既有发布已处理；本轮未发版，不新增 Contributor 声明 |
| 10 | 发版规范：commit/Release/package/deployment/README/演示站初版完整 | 基线 v1.5.307 已发布；本轮树脏，**未发版**，不得宣称完成 |
| 11 | 测试不得含本机独有信息 | 既有门禁；新增 App/header 测试也要检查 |
| 12 | 7 渠道全维度能力一致、特色能力可独立识别/聚合、后续可拓展 | 主树已扩到 10 渠道（5 浏览器+5 App），但 3 个 App 模块未跟踪、未启用；live 仍是 7 渠道旧树 |

> 上表是「用户要什么」的索引，不是「已经做到」的清单。凡状态写「既有」的，下一会话仍要按 `HANDOFF_FULL_SESSION.md` 的验收口径重跑/复查；凡写「缺口」的，必须先补证据再声称完成。

### 1.2 本轮（2026-11-02）新增/加强的期望

- **文案统一**：渠道入口按列/行为统一，不能同一列出现「机票搜索（国际）」「国际·官网」「与国内同页」三种写法。用户要求统一渠道入口文案（转述）。
- **飞猪被爬虫识别**：先配置停止飞猪爬取；不要继续试探、不要换代理/指纹硬闯。
- **App 渠道推进**：飞猪已登录；携程/同程/途牛安装后让用户登录；途牛 App 在 MuMu 上原生崩溃，保留 H5；人脸渠道搁置。
- **指纹自洽 + header 自洽**：桌面/移动两档不能串味；`sec-ch-ua`、UA、locale、`userAgentData`、屏幕/触摸等内部一致；header 要按 profile 稳定，不是随机化。
- **页面/发布体验**：8765 是用户实际查看的控制台；修完要能在 8765 看到，不能只在主树/测试里绿。

### 1.3 方法与设计目标（不是逐字原话）

用户把 `using-superpowers`、`multi-agent-workflow`、`Frontend Design` 作为本轮的**方法/能力目标标签**，意思是：

- **Superpowers**：先调查根因、先写判据/测试、再实现；不猜、不跳步、不伪造完成。
- **Multi-agent workflow**：独立任务可并行，但并行会话共享同一工作树/设备/8765 时必须协调，避免互相覆盖。
- **Frontend Design**：产品级视觉/交互，不是「能显示」；微信式扁平、紧凑、同列同构、像素证明。

**不要**在文档或对用户汇报中把这三项写成「用户原话」；它们是目标归纳。

### 1.4 用户底线（违反即失败）

- 不伪造航班/价格/截图/进度；`empty` 必须有无票证据；拿不到记 `login/blocked/timeout/unsupported`。
- 不绕过验证码、滑块、人脸、风控；被识别就停止/降级，不做对抗升级。
- 不整份 `git add webui.py` / `git checkout webui.py`；并行会话下只能按 hunk 处理。
- 未经明确授权不 push/tag/Release/改 Pages；发版前全量门禁、UI 668、四平台包、站点、资产、Contributors 全对齐。
- 不用旧结论当现状；所有数字/进程/文件都要重新实测。
- 不用「演示绿」冒充「生产绿」；不用「代码写了」冒充「进程在跑」。

### 1.5 用户审美/交互偏好（转述，供 Frontend Design 目标使用）

- **微信式扁平**：画布/表面/发丝线三层；不靠阴影/重描边堆层级；卡片中卡、裸 header 白横带这类泄漏要消掉。
- **紧凑但有质感**：无意义留白要收回；间距/字号用统一刻度；数字等宽、时刻固定列宽。
- **同列同构**：同列文案同句式，长句不塞半格导致单格换行；同列/同卡等高对齐；展开前后不跳。
- **展开/收起是同一动作的两态**：触发器同坐标、折叠后真正把空间还给邻居，不留常驻夹层；折叠段也别留标题条。
- **动作按操作心智放**：删除/收起/展开等动作放卡头/折叠行，不埋到滚动底部；等待/需人操作要有可见「进行中」并换掉按钮。
- **配置就地**：能就地改的不跳抽屉；默认值不能冒充真值（如输入框预填 `*` 会粘住语义）。
- **像素/真渲染证明**：截图、Computed、Range、命中测试；不以源码声明或 CSS 存在为证。
- **不预置渠道限制**：渠道评估只给技术可行性与实测代价，不拿「供给重合/项目底线/旧已放弃」当前提；用户用自己的账号监控自己的行程是合法使用，不要称为「绕过」。
- **数据诚实**：宁可 `—`/「不支持」/「未验证」，不编造；演示数据不能标「正常」；`0%` 必须有有效分母。

---

## 2. 当前权威状态（2026-11-02 21:10）

### 2.1 代码/发布/工作树

| 项 | 当前值 | 备注 |
|---|---|---|
| 源码 HEAD | `0d4b058` | 已发布 v1.5.307 的收尾提交；本轮未发新版 |
| 主工作树 | 108 项变更、21 项未跟踪 | 含多个并行会话 WIP；不可直接发版 |
| 发布基线 | v1.5.307 / `0d4b058` | Release/资产/tag/Pages/live 的既有基线；本轮没有新 Release |
| live 8765 cwd | `D:\idea_project\_release_final_72d` | **不是主树**；只含旧代码（2 个 App 渠道） |
| live PID | `33800`（21:10 快照） | 启动 20:52；下次抓取 21:15 左右 |
| 主树配置 | `D:\idea_project\ticket-monitoring\config.yaml` | 飞猪已从用户 platforms + warmup 移除 |
| live 配置 | `D:\idea_project\_release_final_72d\config.yaml` | 同样暂停飞猪 |
| live 已启用渠道 | `qunar, tongcheng, tuniu, ctrip, app_zhixing, app_qunar` | `/api/health.enabled_platforms`；**无 fliggy** |
| 主树 App 渠道 | 5 个：智行/去哪儿/飞猪/携程/同程 App | 新 3 个模块未跟踪、未加入配置 |
| live App 渠道 | 2 个：智行/去哪儿 App | 新模块不在 live 树 |

### 2.2 测试状态（只代表本次抽跑，不等于全量）

| 命令/范围 | 结果 | 说明 |
|---|---|---|
| App + header + fingerprint 抽跑（11 个文件） | **88 passed** | 含 `app_ctrip/tongcheng/fliggy` 解析与 crawler 测试、`test_android_ocr`、`test_stealth_header_coherence`、`test_stealth_fingerprint_coherence`、`r816/r817` |
| 链接/文案回归（6 个文件） | **177 passed** | `test_channel_links`、`test_v304_ui_mental_model`、`test_goal_fields`、`test_special_links`、`test_r319_special_discovery`、`test_tt_honesty` |
| `tests/test_qunar_honesty.py tests/test_r394_concurrency_fingerprint.py` | **1 failed / 25 passed** | 红项：`test_empty_without_evidence_keeps_login_suspect_semantics`；根因是并行会话的 Qunar 登录探测语义漂移，见 §4 |
| 全量 pytest / UI 668 / 发版七步 | **未跑** | 不能宣称可发版 |

> **测试数字口径警告**：21:09–21:10 并行会话另有一组独立复跑（App 8 文件 52 passed；链接/矩阵/指纹 6 文件 44 passed；stealth 2 文件 14 passed；`test_qunar_honesty` 1 failed/17 passed），见附录 D。本文 §2.2 的 88/177 是另一组文件集合；两组不要相加，报数必须带「命令 + 文件集合 + 时间」。同一个测试在不同窗口红绿变化时，先查并行改写，不要用旧数字下结论。另：§2.2 的「1 failed / 25 passed」是 `qunar_honesty + r394` 合并跑；附录 D 的「1 failed / 17 passed」是仅 `qunar_honesty` 文件跑；两者不是同一集合，不能直接对比。

### 2.3 当前进程/设备

- 8765：`python main.py --restart-delay 3`，cwd `_release_final_72d`；健康接口无 fliggy。
- MuMu：`127.0.0.1:16384`；App 采集与 8765 监控共用同一台设备；监控每约 30 分钟占用一次。
- 下一轮 21:15 左右：先看 `_release_final_72d/logs/monitor.log` 的「下次抓取计划」与当前焦点，**不要在扫描中抢前台/重启**。
- 飞猪：浏览器采集已停；App 飞猪模块存在但未启用；用户已明确「被识别，先停」。

### 2.4 本次长会话的阶段脉络（为什么会有这些改动）

- **r794–r812b（上一版经验书）**：整站 UI/交互整改——微信式扁平、折叠/展开同坐标、筛选面板对齐、健康卡/节流区/配置页排版、同列同构、像素验收；详见 `docs/SESSION_EXPERIENCE_GUIDE.md`（历史）。
- **v1.5.307 发版**：单根初始提交、Release 初版完整正文、四平台包/站点/资产/Contributors/Pages/live 对齐；HEAD `0d4b058`。本轮没有新版发布。
- **App 渠道 P1–P5**：智行 App、去哪儿 App 真机跑通；随后接入同程 App、飞猪 App（竖屏+OCR）、携程 App（RN 列表）；矩阵从 7 渠道扩到 10 渠道（5 浏览器+5 App），但飞猪 App 在连续自动化后 access denied，需人工恢复。
- **2026-11-02 用户实测**：途牛/去哪儿/同程 PC 重新登录；途牛 PC 对远期易软风控 → 本轮加 30 天 PC 上限；途牛 H5 国际与国内同页，入口必须落查询页并在城市弹窗切国际；用户要求推进飞猪/携程/同程/途牛 App，人脸渠道搁置。
- **App 装机/登录**：飞猪已登录；携程/同程/途牛安装 arm64 包并拉起登录页；途牛 App 在 MuMu 原生崩溃（`libtuniudns.so`），只能 H5；飞猪随后被爬虫识别，用户要求先停采集。
- **本轮文案/8765**：渠道入口按列统一；飞猪 PC 国际改独立国际页；主树与 live 树同步，8765 重启 + Ctrl+F5 验证。
- **本轮指纹/header**：`STEALTH_JS` 桌面/移动自洽 + `profile_headers` httpx 单源；浏览器线头（`HeadlessChrome`/移动 CH）仍有边界，后续单独处理。

---

## 3. 已落地改动与证据

### 3.1 渠道入口文案统一（2026-11-02）

用户先指出途牛 H5 国际地址错误，后又指出渠道入口 PC 国际一列文案不统一（「国际」「国际·官网」「与国内同页」三种）。最终定为：

| 列 | 统一文案（入口模式） | 说明 |
|---|---|---|
| PC 国内 | `PC 机票搜索` | 五家统一 |
| H5 国内 | `H5 机票搜索` | 五家统一；登录要求由左侧 meta 表达，不再夹带「进入即淘宝登录」 |
| PC 国际 | `PC 机票搜索（国际）` | 五家统一；飞猪改为独立国际页；去哪儿 PC 仍是站内 tab，但列文案统一，不逐格展开 |
| H5 国际 | `H5 机票搜索（与国内同页，页内切国际）` | 五家统一；登录 meta 另列 |

关键事实：

- 途牛 H5 国际 = 国内同一页 `https://m.tuniu.com/flight/`；进入后在「选择城市」弹窗切「出境·中国港澳台」/「国际多程」。**不是** `m2015/intlFlight`；m2015 `/list` 只是采集数据路径。
- 飞猪 PC 国际改用独立国际页 `https://sijipiao.fliggy.com/ie/flight_search.htm`（实测 200，有出发/到达/搜索表单），不再复用国内 `/jipiao/`。
- 去哪儿 PC 国际没有独立 URL，只有站内 tab（`#js_inter_tab`）；按用户要求列文案统一为「国际」，但链接仍是官方站 `https://flight.qunar.com/site/`，页内切换。
- 去哪儿 PC 国内去掉了「官网」后缀；飞猪 H5 去掉了「进入即淘宝登录」；登录要求仍由渠道 meta「必须登录 · 账号」承担。
- 代码常量在 `core/channel_links.py`：`NOTE_PC_SEARCH / NOTE_H5_SEARCH / NOTE_PC_INTL / NOTE_PC_INTL_SAME / NOTE_H5_INTL_SAME`；新增门禁 `test_entry_notes_are_uniform_per_column_and_behavior`。
- 主树和 live 树的 `core/channel_links.py` 都已同步；8765 已重启并实测 API/DOM/截图一致；主树相关回归 177 passed。
- 证据：`_scratch/live_entry_board_final.png`（live 最终板）、`_scratch/live_tuniu_row.png`（途牛行）。

### 3.2 途牛 PC 远期日期限制

- `crawlers/tuniu.py` 新增 `PC_MAX_AHEAD_DAYS = 30`、`_split_pc_dates()`；超过 30 天的日期不查 PC，改走 H5/API，并写 `path_note("PC", "unsupported", ...)`。
- 目的：途牛 PC 对远期日期易触发软风控（用户实测）；H5/API 仍可用。
- 测试：`tests/test_tuniu_pc_far_date_cap.py`。
- 不要在未验证的情况下把 PC 远期查询加回来；H5/API 是当前可信出数通路。

### 3.3 指纹自洽与 header 单源

**已落地（主树）**：

- `crawlers/base.py` 的 `STEALTH_JS` 已扩展：`navigator.vendor`、`maxTouchPoints`、`screen.*`、`devicePixelRatio`、`userAgentData`、`plugins/mimeTypes`；移动档删除 `window.chrome`、`navigator.userAgentData`、`navigator.deviceMemory`；桌面 GPU 由 seed 选，移动 GL 固定 Apple。
- `stealth_replacements(fp)` 是占位符唯一替换源；`tests/test_stealth_fingerprint_coherence.py` 用真实 Chromium 断言两档不自相矛盾、同 profile 幂等、不同 profile 不同、无残留 `__XXX__`。
- `profile_headers(fp, extra)` 是 **httpx 侧**的 header 单源：桌面 `sec-ch-ua*` 与 UA Chrome 大版本一致；移动档不带 `sec-ch-ua*`；Accept-Language 由 locale 派生；身份类 header 不允许 `extra` 覆盖。
- `profile_headers` 已用于 `crawlers/qunar.py`、`tongcheng.py`、`tuniu.py`、`fliggy.py`、`special.py` 的 httpx 请求；对应测试 `tests/test_stealth_header_coherence.py`。
- 本次抽跑 88 passed 覆盖上述。

> **归属**：`STEALTH_JS`/指纹自洽与 `test_stealth_fingerprint_coherence.py` 是本会话落地；`profile_headers`/`test_stealth_header_coherence.py` 与 httpx 调用点是并行会话落地，本会话只审查和实测。两者都在当前树，但不是同一会话产物；改动前先看 `git status`/mtime，不要整份覆盖。

**仍存在的边界（不要误报为已修）**：

- **浏览器上下文没有套 `profile_headers`**：`crawlers/base.py::_browser_context` 没有传 `extra_http_headers`。实测 headless Chromium 的线头仍然是：
  - 桌面 `sec-ch-ua` 含 `HeadlessChrome` 品牌（版本虽与 UA 大版本一致，但品牌暴露自动化）；
  - 移动 iPhone Safari UA 仍发送整套 `sec-ch-ua*`（Chromium 引擎行为）；
  - Accept-Language 实际是 `zh-CN`（Playwright locale），用 extra header、CDP、`--accept-lang` 都改不动；
  - header 顺序是 Chromium 固定顺序，无法按 profile 重排，也不建议追这条。
- 可行的后续：
  - 桌面：在 `_browser_context` 用 `extra_http_headers` 注入 `profile_headers` 的桌面身份头（实测能覆盖 `sec-ch-ua`，顺序不变），并用本地回显服务验证；注意它会覆盖 Chromium 自动 client hints，必须与 `navigator.userAgentData` 同源。
  - 移动：Chromium 无法干净去掉 client hints；试过 `--disable-features=UserAgentClientHint/ClientHints`、空值覆盖、route strip 都失败。要真 Safari 线头只能换 WebKit 引擎或代理，成本和兼容性另算；不要用「改成 Chrome 品牌」掩盖。
  - 在未完成前，文档/汇报必须写「httpx 已自洽；浏览器线头仍有边界」，不能说「指纹/header 全修好」。

### 3.4 App 渠道（当前主树状态）

- `core/channels.py` 的 `APP_CHANNELS` 已扩到 5 个：`app_zhixing, app_qunar, app_fliggy, app_ctrip, app_tongcheng`；中文名、peer、矩阵注释已补。
- 新模块（**未跟踪 WIP**）：
  - `crawlers/app_ctrip.py` + `app_ctrip_parse.py`；携程 App 国内/国际单程列表未登录可出完整明细；列表卡片 `第XXX航班…` / 国际 `第N条航班…` 的 `content-desc` 给出时刻/机场/航司/价格（国际列表不暴露航班号）；日历日格自绘，后续改用截图 + Windows OCR 读出逐日价（国内 61 天 / 国际 54 天，行距按截图实测 88/107px）；矩阵 domestic/detail/calendar/low_fare/intl=y，round_trip=y（国内/国际：去程卡价=页脚往返总价），多程未接。
  - `crawlers/app_tongcheng.py` + `app_tongcheng_parse.py`；原生表单/城市/日历 + WebView 结果页；CLI dump 卡 idle，使用 uiautomator2 回退；矩阵 domestic/detail/calendar/low_fare/intl=y（国际日历 + 单程明细 6 条 ¥875），round_trip=y（仅国际：上海⇌东京 11-16/19，7 条去程最低 ¥2209，去程行含税总价=往返总价；国内往返查询落单程去程列表、无往返总价，未接），多程未接。
  - `crawlers/app_fliggy.py` + `app_fliggy_parse.py` + `core/android/ocr.py`；Flutter 画布 + Windows OCR；只做国内单程，只验证当月（次月/更远未验证，显式 unsupported）；连续自动化触发 access denied 后 `blocked`，需人工恢复。**用户已说飞猪被识别，app_fliggy 也不要启用。**
- 新测试（未跟踪）：`test_app_ctrip_*`, `test_app_tongcheng_*`, `test_app_fliggy_*`, `test_android_ocr.py`；本次抽跑 88 passed。另有 `test_r816/r817/r818/r819` 等并行会话测试。
- **这些模块没有写进主树/live 的 config**：`users.platforms` 仍只有 `app_zhixing, app_qunar`；即注册了但不会调度。live 树也没有这些模块。
- 设备事实：MuMu `abilist32=x86`、`abilist64=x86_64,arm64-v8a`；只有 arm64 包能装。MyApp 桌面静态链是 armeabi；Android UA 页 `/sjy.00022/` 才是 arm64；用尾部 ZIP 中央目录验 ABI。途牛 App 原生崩溃 `libtuniudns.so`，不在 APP_CHANNELS；途牛只走 H5。

### 3.5 飞猪暂停

- 用户目标（转述）：飞猪已被爬虫识别，先配置停止飞猪的爬取。
- 已做：
  - 主树和 live 的 `config.yaml`：`users[0].platforms` 移除 `fliggy`；`crawler.warmup.platforms` 移除 `fliggy`（预热也会请求飞猪，不能只关主采集）。
  - live 8765 已通过 `/api/restart` 重启；`/api/health.enabled_platforms` 无 fliggy；配置页 `CFG[0].platforms` 无 fliggy；warmup 只剩 qunar/tuniu。
  - 飞猪历史数据、登录档案、手动入口保留；不要删除 `user_data` 里的飞猪凭证。
- 不要：在未获用户明确恢复指令前，把 fliggy 加回 `platforms`/`warmup`，或启用 `app_fliggy`，或手动跑飞猪探针/雷达。用户已明确被识别，继续请求只会加重风控。

---

## 4. 当前未完成、已知风险与红线

### 4.1 并行会话的 Qunar 测试红（必须如实交接）

- 红项：`tests/test_qunar_honesty.py::test_empty_without_evidence_keeps_login_suspect_semantics`。
- 现象：测试期望空结果后 `login_suspect is True`；实际 25 passed / 1 failed。
- 根因归属：并行会话在 `crawlers/qunar.py` 新增 `userBaseInfo` 登录态探测；空结果且探测在线时把 `login_suspect` 置 False（约 `crawlers/qunar.py:588-618`），而 `tests/test_qunar_honesty.py:150-154` 仍断言 True。该路径不进入浏览器指纹/注入，**不是本轮指纹改动导致**。
- 处理纪律：不要为了让门禁变绿去改测试期望；先与并行会话确认语义（是「软空/限流」还是「会话失效」），用证据决定是代码还是测试需要更新。可以单跑其余用例证明其它绿。

### 4.2 主树/live 分叉

- 8765 跑 `_release_final_72d`，不是主树；主树新增的 App 渠道/模块/文案不一定在 live。
- 已有先例：主树已修途牛 H5 文案，8765 仍旧；排查后发现 live 树 `core/channel_links.py` 是 10:16 的旧文件；同步 live 树 + `/api/restart` + Ctrl+F5 后才生效。
- 规则：
  - 用户看 8765 时，先查进程 cwd/启动时间/文件 mtime，再判断「没改对」还是「没加载」。
  - 主树改动后若要让 8765 看到，必须同步 live 树或走发布流程；不能只改主树就说已上线。
  - 8765 重启后，已打开的 SPA 页面不会自动刷新；要 Ctrl+F5。
  - 不要在扫描进行中重启/抢设备；先看 `monitor.log` 的「下次抓取计划」和当前前台包。

### 4.3 全量门禁/发版未完成

- 当前只跑了定向测试；没有全量 pytest、没有 UI 668、没有四平台包/站点/资产/Release 重建。
- 工作树 108 项变更/21 项未跟踪，包含并行会话/未审查 WIP；**不能发版、不能宣称全绿**。
- 发布基线仍是 v1.5.307 / `0d4b058`；新改动未进入 Release/tag/Pages/镜像。

### 4.4 App 渠道的未验证面

- 新 App 模块测试绿，但只代表纯函数/模拟/部分真机记录；**没有写入 config、没有在 live 运行、没有新真机复验**。
- 携程/同程 App 登录态未在当前快照重新验证；开启前先看设备/登录卡，不要假设。
- 飞猪 App 被识别/access denied；不要启用。
- 途牛 App 原生崩溃；不要浪费轮次尝试 x86/armeabi 安装；H5 是当前通路。
- App 采集与 8765 共用设备；监控每 30 分钟一轮，抢前台会让 app_qunar/app_zhixing 记 0（真实发生过）。动手前看 log 和下轮时间。

### 4.5 飞猪恢复是用户决策

- 飞猪被识别是外部风控事实；何时恢复、是否换账号/设备/网络，必须由用户决定。
- 不要用「换个代理/指纹再试」作为默认下一步；本项目的边界是稳定自洽身份，不是绕过检测。

---

## 5. 领域知识：渠道、文案、App、指纹

### 5.1 渠道宇宙与矩阵

- 浏览器渠道：`ctrip, fliggy, qunar, tongcheng, tuniu`。
- App 渠道（主树）：`app_zhixing, app_qunar, app_fliggy, app_ctrip, app_tongcheng`。
- 矩阵维度：`domestic, intl, calendar, detail, round_trip, multi_city, low_fare`；另有 11 条质量轴/端面/契约测试（见 `core/channel_contract.py`、`tests/test_r677_channel_dimension_matrix.py`）。
- 取值语义：`y` 有真机/真请求证据；`n` 明确不支持/停服；`""` 未验证（不得当支持）。
- App 渠道新增必改点：`core/channels.py`（APP_CHANNELS/CHANNEL_CN/DIMENSIONS/PEER/DIMENSION_NOTES）、`crawlers/__init__.py` REGISTRY、`config` chip、登录卡、图标/配色、演示派生、health/pacing 正则、导出/CSV、测试宇宙派生（别写死 7/2/8）。

### 5.2 文案约定（本轮定稿）

- 入口模式按列统一：PC 国内/H5 国内 `机票搜索`；PC 国际 `机票搜索（国际）`；H5 国际 `机票搜索（与国内同页，页内切国际）`。
- 登录要求写在渠道左侧 meta（`必须登录 · 账号`），不要塞进入口文案；否则同列文案会被拉长、折行、破坏卡片等高。
- 同页/独立页必须用真实浏览器验证，不要凭 URL 形状猜：
  - 途牛 H5 国际与国内同页，城市弹窗切「出境·中国港澳台」；
  - 飞猪 PC 国际有独立 `sijipiao` 页；去哪儿 PC 国际只有站内 tab；
  - 同程 H5 国际同页；去哪儿 H5 国际同页。
- 代码常量与门禁：`core/channel_links.py` 的 `NOTE_*` + `test_entry_notes_are_uniform_per_column_and_behavior`。新增渠道必须复用这些常量/规则，不要各写一套。

### 5.3 App 采集知识

- **ABI**：MuMu 32 位只支持 x86，不支持 armeabi；应用宝桌面静态链常是 armeabi，Android UA 页 `/sjy.00022/` 才是 arm64。判断远端 APK ABI：取尾部 2MB 读 ZIP 中央目录，不要整包下载后才试装；`INSTALL_FAILED_NO_MATCHING_ABIS` 就是包不对。
- **飞猪 App**：Flutter 画布，uiautomator 读不到；Windows OCR 是现有方案；竖屏锁定；只验证当月（次月/更远未验证，显式 unsupported）；连续自动化触发 access denied 后 `blocked`，需人工恢复。**当前暂停。**
- **携程 App**：表单可显式拉起 `CtripPlantHomeActivity`；城市页支持中文搜索；国内列表未登录可出完整明细；RN 卡片 `第XXX航班…` 字段语义完整；日历日格自绘、`uiautomator` 读不到，截图 + Windows OCR 可读逐日价（后续已接入）。
- **同程 App**：Flutter 原生表单 + WebView 结果；CLI dump 卡 idle，用 uiautomator2 回退；结果页可能有「出行提醒」公告，由 `app_blockers` 识别点掉；状态漂移后城市位可能打不开，生产启用前先单跑复验。
- **途牛 App**：当前 MuMu 上 `libtuniudns.so` 原生崩溃；不要自动化登录/采集；H5 是可用面。
- **设备纪律**：单设备串行；先验前台包；广告/验证码/人脸分流；`ad` 自动关、`captcha/face` 停下等人；看不懂别记 `blocked`（会熔断 300s）；登录快照不含动态 so；恢复快照不等于已登录。

### 5.4 指纹/header 的真实边界

- `STEALTH_JS`：当前桌面/移动两档内部自洽（vendor/platform/触摸/屏幕/DPR/UAD/插件/GL），同 profile 幂等；测试用真实 Chromium 验值。
- `profile_headers`：**httpx 侧**单源；桌面 CH 版本对齐 UA；移动无 CH；Accept-Language 派生；身份键不可被 extra 覆盖。
- **浏览器侧未接 profile_headers**：`_browser_context` 没有 extra headers；headless 实测桌面 `sec-ch-ua` 带 `HeadlessChrome`，移动 Safari UA 仍发 CH；Accept-Language 是 `zh-CN`；header 顺序固定。不要把 httpx 的绿当成浏览器线头已修。
- 若继续这条线：先做桌面 `extra_http_headers` 单点，再用本地回显验证（不要只看代码）；移动端不要承诺能去掉 CH，除非换 WebKit/代理并经用户同意。

---

## 6. 操作手册（下一会话照做）

### 6.1 开工检查（必须先做）

```bash
cd /d/idea_project/ticket-monitoring
date '+%F %T'
git status --short | head -60
git log --oneline -3
# 8765 实际进程/代码树
pid=$(netstat -ano | awk '/127.0.0.1:8765/ && /LISTENING/ {print $5; exit}')
python - <<EOF
import psutil, time
p = psutil.Process($pid)
print(p.pid, time.strftime('%F %T', time.localtime(p.create_time())), p.cwd(), p.cmdline())
EOF
curl -s --noproxy '*' http://127.0.0.1:8765/api/health \
  | python -c "import sys,json;print(json.load(sys.stdin).get('enabled_platforms'))"
tail -8 /d/idea_project/_release_final_72d/logs/monitor.log
grep -n "fliggy" -A3 -B3 config.yaml /d/idea_project/_release_final_72d/config.yaml
```

确认：飞猪仍在暂停；8765 与主树是否同一份代码；下一轮扫描时间；是否有并行会话正在写（文件 mtime/未跟踪模块）。

### 6.2 live 8765 / 主树 / 发布树

- 8765 只认它 cwd 里的 `main.py`/`config.yaml`/`core`；主树改动不会自动生效。
- 要让 8765 看到主树改动：
  1) 只同步必要的 hunk/文件到 live 树（不要整包覆盖 live 的并行 WIP）；
  2) 校验 live 树 Python 导入/关键函数输出；
  3) `curl -s -X POST http://127.0.0.1:8765/api/restart`；
  4) 轮询新 PID，确认 `/api/health.enabled_platforms`；
  5) 浏览器 **Ctrl+F5**（SPA 不会自动刷新）。
- 不要在扫描进行中重启；先看 `[下次抓取计划]`。
- 发布仍需走 `docs/HANDOFF_GUIDE.md` 七步；当前脏树不可发版。

### 6.3 飞猪暂停/恢复

**暂停（已完成，复核用）**：

- 主树/live 的 `users[0].platforms` 去掉 `fliggy`；
- `crawler.warmup.platforms` 去掉 `fliggy`；
- 重启 8765；确认 `/api/health.enabled_platforms` 无 fliggy；`CFG[0].platforms` 无 fliggy；warmup 只剩 qunar/tuniu；
- 不要动飞猪的登录快照/历史数据；不要跑飞猪探针/雷达。

**恢复（仅当用户明确要求）**：

- 把 `fliggy` 加回 `users[].platforms` 和 `crawler.warmup.platforms`；
- 重启/热加载；
- 先单跑一次飞猪（不要全量并发），观察是否仍 access denied；被识别就再次停；
- 绝不用换代理/换指纹/绕过验证来「恢复」。

### 6.4 测试命令

```bash
cd /d/idea_project/ticket-monitoring
PYTHONPATH=_scratch/testdeps PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest tests/test_channel_links.py tests/test_v304_ui_mental_model.py \
  tests/test_goal_fields.py tests/test_special_links.py \
  tests/test_r319_special_discovery.py tests/test_tt_honesty.py -q
# 当前 177 passed

PYTHONPATH=_scratch/testdeps PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest tests/test_app_ctrip_parse.py tests/test_app_ctrip_crawler.py \
  tests/test_app_tongcheng_parse.py tests/test_app_tongcheng_crawler.py \
  tests/test_app_fliggy_parse.py tests/test_app_fliggy_crawler.py \
  tests/test_android_ocr.py tests/test_stealth_header_coherence.py \
  tests/test_stealth_fingerprint_coherence.py tests/test_r816_session_auth_markers.py \
  tests/test_r817_qunar_empty_auth_probe.py -q
# 当前 88 passed

# 已知 1 红（并行 Qunar 漂移，勿改测试迎合）：
PYTHONPATH=_scratch/testdeps PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest tests/test_qunar_honesty.py tests/test_r394_concurrency_fingerprint.py -q
```

注意：

- `pytest` 插件自动加载会导致 langsmith/requests_toolbelt 报错；必须 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，必要时 `PYTHONPATH=_scratch/testdeps`。
- 跑门禁前后 pin 关键文件 md5；并行会话可能在你跑的时候改文件。
- UI 测试必须真渲染；不要只信源码断言。

### 6.5 App 真机

```bash
ADB="/d/Program Files/Netease/MuMu/nx_main/adb.exe"
MSYS_NO_PATHCONV=1 "$ADB" devices
MSYS_NO_PATHCONV=1 "$ADB" shell pm list packages | grep -E 'ctrip|tongcheng|taobao.trip|tuniu|Qunar'
MSYS_NO_PATHCONV=1 "$ADB" shell "dumpsys window | grep mCurrentFocus"
```

- 安装前验 ABI（尾部 ZIP 中央目录）；MuMu 只接受 arm64。
- 先看 `_release_final_72d/logs/monitor.log` 的下轮时间与当前前台；不要在扫描中抢设备。
- 登录由用户完成；`captcha/face` 停手；`ad` 可自动关；不绕过。
- 途牛 App 原生崩溃，不要装 armeabi/32 位；H5 是可用面。
- 飞猪 App 当前暂停；不要启用。

### 6.6 关键证据

- 主树/live 文案与 8765：`_scratch/live_entry_board_final.png`、`_scratch/live_tuniu_row.png`。
- 携程列表/表单/日历 dump：`_scratch/ctrip_list_1116.xml`、`ctrip_flight_form.xml`、`ctrip_calendar.xml`（若 scratch 被清理，按 §6.5 重取）。
- 指纹/header 实测：本会话用本地 HTTP 回显 + Playwright 验证；命令见 §5.4；不要依赖旧截图。

---

## 7. 经验教训（按杀伤力排序）

### 7.1 live 可能跑另一棵树（最高频）

先查进程 cwd/启动时间/文件 mtime，再判断「代码没改对」还是「live 没加载」。本次途牛 H5 文案在 8765 看起来「没改」，实际是 live `_release_final_72d` 里 10:16 的旧 `channel_links.py`；主树 17:19 已改。修复过程：比对两棵树 → 只同步相关 hunk → live 树 Python 校验 → `/api/restart` → Ctrl+F5 → API/DOM/截图三重验证。**不要把主树的绿当成 live 的绿。**

### 7.2 `/api/state.platforms` 可能是历史展示，不是配置

`/api/state` 的 `users[].platforms` 在停飞猪后仍显示 fliggy；真正判断启用渠道要看 `/api/health.enabled_platforms` 和 `CFG[0].platforms`。只看 state 会误以为停飞猪失败。**排查配置生效要查正确的消费者/接口。**

### 7.3 SPA 重启后必须硬刷新

8765 重启不会刷新已打开页面；旧 DOM 会继续显示旧链接/旧文案。用户说「地址还不对」时，先确认页面是否 Ctrl+F5 过，再查 API/DOM。**不要用旧 tab 的截图判定未生效。**

### 7.4 同页 ≠ 独立 URL；文案要按列/行为统一

- 途牛 H5 国际与国内同页，m2015 `/list` 只是采集数据路径；用户入口必须 `https://m.tuniu.com/flight/`。
- 飞猪 PC 国际有独立 `sijipiao` 页；去哪儿 PC 国际只有站内 tab；同程 H5 同页。
- 文案统一规则：同列同句；登录要求单独放 meta；不要「官网」「进入即淘宝登录」等变体；长句会折行破坏四列对齐。
- 判据要用真实浏览器打开并看落地页/弹窗，不要凭 URL 形状。

### 7.5 App ABI/引擎是硬边界

MuMu 只支持 x86/arm64；MyApp 桌面静态链 armeabi，Android UA `/sjy.00022/` 才 arm64。整包 100MB+ 下载慢，先用尾部 2MB ZIP 中央目录验 ABI 再下载。途牛 App 在 MuMu 上 `libtuniudns.so` 原生崩溃；不要用 x86/armeabi 反复试。飞猪 Flutter 画布要 OCR；access denied 是风控，停手等人工恢复。

### 7.6 飞猪被识别后停，不要升级对抗

用户明确「飞猪已经被爬虫识别，先配置停止飞猪的爬取」。正确做法：从用户 `platforms` 和 warmup 两处移除，重启，验证健康接口，保留历史/登录档案；不要换代理/指纹/账号硬闯，不要把「停了」说成「修好了」。恢复必须用户明确要求。

### 7.7 浏览器 header ≠ httpx header

`profile_headers` 目前只服务 httpx；浏览器 `_browser_context` 没有 extra headers。实测浏览器线头仍带 `HeadlessChrome`，移动 Safari UA 仍发 CH；Accept-Language/header 顺序也不可随意改。不要把 httpx 测试的 88 passed 说成浏览器指纹已全修。桌面可用 `extra_http_headers` 覆盖 CH；移动只能 WebKit/代理，成本高，先与用户确认。

### 7.8 并行会话是环境事实

- 本树同时有多个会话在写：`crawlers/qunar.py`、`base.py`、`webui.py`、docs、未跟踪 App 模块。
- 不要整份 `git add webui.py` / `git checkout webui.py`；会吞掉别人未提交的 86 行/1147 行。
- 不要覆盖未跟踪的 App 模块/测试；先审查、跑测试、确认归属。
- 红项先分清「值变了」还是「设计坏了」；`test_empty_without_evidence...` 是并行 Qunar 语义漂移，不是指纹改动。
- 跑门禁前后 pin md5；并行改动会让「同一个测试」时红时绿。

### 7.9 数据诚实 > 功能多

`empty` 必须有无票证据；`login/blocked/timeout/unsupported` 各有语义；失败不能静默为 0 行；App 的 `ad/captcha/face` 要分流；演示数据不能标「正常」；能力矩阵 `""` 不得当 `y`。用户对「账本说谎」极其敏感。

### 7.10 UI 改动要截图/像素证明

- 同列文案同构、同列等高、无截断/无溢出；不要用长句塞半格。
- 折叠/展开同坐标、折叠后不留常驻夹层；负 margin 在 overflow:hidden 会裁字。
- `Range` 会含被裁剪文字；判换行用行盒数，判压图标用盒子右缘−内衬/命中测试。
- 最终以 8765 真渲染 + 截图为准，不以源码/CSS 声明为准。

### 7.11 发版纪律

- Release 正文必须是初版完整产品介绍（intro + 版本 + 源码 SHA + 资产 SHA256 + Contributors），不是 changelog；Contributors 只认 author 身份的非空提交。
- 全量 pytest、UI 668、四平台包、站点 code 戳、资产 SHA256SUMS、release_align_check 全通过才发；当前树脏，不能发。
- GitHub 侧还要覆盖：tag、部署包、ghcr 镜像（推送开关/首次 public）、Pages/演示站、SHA256SUMS、Release 资产；本轮没有新版发布，不能把这些算作已完成。
- 未获授权不 push/tag/Release/改 Pages。

### 7.12 工程小坑（本会话/历史反复出现）

- Windows Git Bash：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`；GBK 打印 emoji 会崩；PowerShell 内联 `$_` 会被 bash 吃；用 `.ps1`。
- 文本工具会归一 EOL；混合 EOL 是 bug；`grep -c $'\r'` 在 Git Bash 不可靠，按字节数三种计数。
- 不用 heredoc 写含转义的内容；用 Write/Edit，写后按字节核。
- 进程重启：`/api/restart` 会 `os._exit`；无 body POST 不要被 415 误判；CSRF 只拦跨源 Origin。
- 端口/进程会漂移；每轮重新查 PID/netstat。

---

## 8. 下一步优先级与验收标准

### P0（先做，否则会加重风险）

1. **保持飞猪暂停**：确认主树/live `platforms`、warmup 无 fliggy；8765 health 无 fliggy；不启用 app_fliggy；恢复必须用户明确要求。
2. **确认 8765 下一轮不含飞猪**：看 21:15 左右 log/健康接口；如果发现 fliggy 请求，立即停并查 live 配置。
3. **审查并行 App WIP，不覆盖**：`git status`、模块/测试 mtime、88 passed；确认 `app_ctrip/tongcheng/fliggy` 是否要进入本轮；Fliggy 不启用。
4. **处理 Qunar 红项**：与并行会话确认语义；不改测试迎合；必要时修 `qunar.py` 的软空/失效判定并用证据（userBaseInfo 探测、行数、请求证据）。
5. **主树/live 同步规则**：不要让用户再次看到「主树改了、8765 没改」；同步后必须 API/DOM/Ctrl+F5 验证。

### P1（产能主任务）

6. **App 渠道 Ctrip/Tongcheng**：确认登录态/设备；评审新模块；真机单跑（避开 21:15 扫描）；矩阵/UI/配置/文档/测试收口；未验证维度保持 `""`，不要升 y。
7. **App 渠道启用**：把 `app_ctrip`/`app_tongcheng` 写入 config 前，先小步验证；不要与浏览器扫描抢设备；飞猪不启用；途牛 App 不做。
8. **浏览器 header 后续**：桌面 `extra_http_headers` 单点 + 回显验证；移动边界如实记录；不经用户同意不做 WebKit/代理大改。
9. **四会话矩阵/契约收口**：新 App 渠道加入后，检查 `test_r677`/`test_r683`/端面矩阵/演示派生/图标/导出/健康/pacing，确保单一来源。

### P2（产品化/发布）

10. **页面产品化/微信扁平**：按用户审美继续扫，但先保证不改坏已定稿的文案/布局；UI 真渲染 + 截图。
11. **GitHub/Release**：等全量绿、工作树稳定、用户授权后，按 HANDOFF_GUIDE 七步重建 tag/包/站点/资产/Release；初版完整描述；Contributors。
12. **文档同步**：README/README_EN/HANDOFF/ACCEPTANCE_MATRIX/APP_CHANNELS 与本轮代码一致；文档数字带口径，不写死渠道数。

### 验收标准（做任何一条都按这个）

- 有最小复现/证据；根因明确；改实现不改门禁。
- 正控 + 负控；定向测试绿；相关回归绿；必要时真机/真浏览器/8765 渲染。
- 数据声明 `y/n/""` 有代码或真机证据；界面能识别/聚合；文案同列同构。
- live 若涉及：同步 live 树 + 重启 + API/DOM/截图 + Ctrl+F5。
- 不造假、不绕过、不覆盖并行 WIP、不无授权发版。

---

## 9. 关键文件索引

**渠道/矩阵**
- `core/channels.py`：`BROWSER_CHANNELS`、`APP_CHANNELS`、`CHANNEL_CN`、`CHANNEL_DIMENSIONS`、`DIMENSION_NOTES`、`APP_BROWSER_PEER`。
- `crawlers/__init__.py`：`REGISTRY`（含 app_ctrip/app_tongcheng/app_fliggy）。
- `core/channel_contract.py`、`tests/test_r677_channel_dimension_matrix.py`、`tests/test_r683_channel_dims_surface.py`：矩阵/端面契约。
- `docs/HANDOFF_CAPABILITY_MATRIX.md`、`docs/ACCEPTANCE_MATRIX.md`：能力/验收文档。

**入口文案**
- `core/channel_links.py`：`NOTE_*` 常量、`ENTRY`、`_route_url`。
- `tests/test_channel_links.py`：`test_entry_notes_are_uniform_per_column_and_behavior` 等。
- live 副本：`D:\idea_project\_release_final_72d\core\channel_links.py`。

**App**
- `crawlers/app_ctrip.py` / `app_ctrip_parse.py`；`app_tongcheng.py` / `app_tongcheng_parse.py`；`app_fliggy.py` / `app_fliggy_parse.py`；`core/android/ocr.py`。
- `tests/test_app_ctrip_*`、`test_app_tongcheng_*`、`test_app_fliggy_*`、`test_android_ocr.py`。
- `crawlers/app_base.py`、`app_blockers.py`、`core/android/`：设备/登录/快照/拦路物。
- `docs/APP_CHANNELS.md`、`docs/MOBILE_*.md`：App 渠道设计与验收。

**指纹/header**
- `crawlers/base.py`：`STEALTH_JS`、`stealth_replacements`、`profile_headers`、`_browser_context`、`fingerprint`。
- `crawlers/qunar.py`、`tongcheng.py`、`tuniu.py`、`fliggy.py`、`special.py`：`profile_headers` 调用点（httpx）。
- `tests/test_stealth_fingerprint_coherence.py`、`tests/test_stealth_header_coherence.py`、`tests/test_r394_concurrency_fingerprint.py`。

**配置/运行**
- `config.yaml`（主树） / `D:\idea_project\_release_final_72d\config.yaml`（live）：users platforms、warmup。
- `main.py`：`load_config`、`build_users`、`reload_config`、`/api/restart`。
- `webui.py`：`/api/channel-links`、`/api/health`、`/api/state`、`srxChLinksLoad`。
- `logs/monitor.log`（live 树）：扫描/下次计划/渠道状态。

**文档/发布**
- `docs/HANDOFF_FULL_SESSION.md`：12 项目标与验收标准（最完整）。
- `docs/HANDOFF_GUIDE.md`：发版七步/文档门禁。
- `docs/SESSION_EXPERIENCE_GUIDE.md`：上一版 r794–r812b 经验（历史）。
- `docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md`：本文。
- `docs/INTL_DESIGN.md`：途牛/国际设计；注意 m2015 只是采集面。
- `docs/LESSONS.md`：更长的历史教训库。

---

## 10. 开工/收工检查清单

### 开工前

- [ ] 读本文 §0–§2；再读 `HANDOFF_FULL_SESSION.md` §1.1 的 12 项目标。
- [ ] `git status --short`、`git log -1`；确认工作树/HEAD 是否漂移。
- [ ] 查 8765 PID/cwd/启动时间/health；确认是否 live 树。
- [ ] 查 Fliggy 仍在暂停；不要恢复。
- [ ] 查监控下一轮时间；避免抢设备。
- [ ] 查并行会话 mtime/未跟踪文件；不要覆盖。
- [ ] 确定本轮只做哪个 P0/P1；写清验收判据。

### 收工前

- [ ] 改动只按 hunk；没有整份覆盖/暂存别人的文件。
- [ ] 定向测试 + 相关回归绿；红项归属写清。
- [ ] 若涉及 8765：同步 live、重启、health/API/DOM/截图 + Ctrl+F5。
- [ ] 若涉及 App：真机证据/ABI/登录/前台包/不抢监控。
- [ ] 若涉及文案/UI：同列同构、截图、无裁切/溢出。
- [ ] 数据声明 `y/n/""` 有证据；没有把未验证写成支持。
- [ ] 不造假、不绕过、不无授权发版；飞猪仍停。
- [ ] 文档/交接更新到本文或对应 HANDOFF；不把旧数字当现状。

---

## 附录 A：四个会话线与目标映射

用户给的四条会话线：

- `b44d19e3-be11-4dc8-9c32-f165d34050dd`
- `3f298749-4eb2-4659-91a3-ded8de09b2b`
- `254eb2bc-871d-47b0-bba8-07793a2c605a`
- `24a5d7af-6537-420e-bfb3-f640e401e047`

它们在本项目中共享同一套目标：7 渠道/10 渠道矩阵、11 条质量轴、全项目覆盖、后续渠道统一设计、页面产品化/微信扁平、GitHub 初版维护、issue 关闭、Release 初版描述、App 渠道与风控边界。**不要声称四条会话的每个子任务都已完成**；本文 §2 是当前证据，§8 是剩余任务。

用户在本轮最后的具体目标（转述）：

- 途牛 PC 远期不查（30 天）；H5 可用；途牛 H5 国际与国内同页，城市弹窗切国际。
- 推进飞猪/携程/同程/途牛 App；先安装让用户登录；人脸渠道搁置。
- 飞猪被爬虫识别，先配置停止飞猪爬取。
- 渠道入口同列文案统一。
- 指纹/header 要 per-profile 稳定自洽（不是随机化）；当前树已落地 JS/httpx 侧（其中 header 为并行会话产物），浏览器线头仍有边界；后续先桌面 `extra_http_headers` 单点验证，移动端不要承诺能去掉 CH。

`using-superpowers`、`multi-agent-workflow`、`Frontend Design`：方法/能力目标标签，不是用户逐字原话；按 §1.3 理解。

---

## 附录 B：当前进程、路径、命令

**路径**

- 主树：`D:\idea_project\ticket-monitoring`
- live 树：`D:\idea_project\_release_final_72d`
- 主 config：`D:\idea_project\ticket-monitoring\config.yaml`
- live config：`D:\idea_project\_release_final_72d\config.yaml`
- live log：`D:\idea_project\_release_final_72d\logs\monitor.log`
- MuMu adb：`D:\Program Files\Netease\MuMu\nx_main\adb.exe`
- 设备：`127.0.0.1:16384`（SM-A5260 / Android 15 / x86_64 + arm64-v8a）

**命令**

```bash
# 8765 PID / cwd
pid=$(netstat -ano | awk '/127.0.0.1:8765/ && /LISTENING/ {print $5; exit}')
python - <<EOF
import psutil,time
p=psutil.Process($pid); print(p.pid,time.localtime(p.create_time()),p.cwd(),p.cmdline())
EOF

# 健康接口（真正启用渠道）
curl -s --noproxy '*' http://127.0.0.1:8765/api/health | python -m json.tool | head

# 重启（只有需要 reload 配置/代码时）
curl -s -X POST http://127.0.0.1:8765/api/restart

# 配置 YAML 校验
python - <<'EOF'
import yaml
d=yaml.safe_load(open('config.yaml',encoding='utf-8'))
print(d['users'][0]['platforms'], d['crawler']['warmup']['platforms'])
EOF

# 测试
PYTHONPATH=_scratch/testdeps PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest tests/test_channel_links.py -q
```

**当前快照（21:10，供对照；开工必须重测）**

- 8765 PID `33800`，cwd `_release_final_72d`，启动 20:52，下次抓取约 21:15。
- `enabled_platforms`：`qunar, tongcheng, tuniu, ctrip, app_zhixing, app_qunar`。
- 主树 HEAD `0d4b058`；108 uncommitted / 21 untracked。
- 飞猪：主树+live config 均已从 platforms/warmup 移除。

---

**最后一句**：这不是「把旧任务重做一遍」的指令。先读目标、再核现状、只做 P0/P1 中用户已授权且证据充分的部分；不确定就停下来问用户，不要用猜的。飞猪暂停是用户明确要求，恢复必须用户明确说。

---

## 附录 C：途牛 App 安装包 / 架构 / 市场核查（2026-11-02 补充）

> **来源说明**：附录 C–E 是并行会话在 2026-11-02 21:09–21:12 补入的现场记录（包/ABI/市场/最后决策）。本会话没有逐项重新实测；使用前按 §6 复核，尤其包版本、ABI、市场可用性与测试数字。若用户最新原话与本节冲突，以用户最新原话为准。

> 本节记录本轮对「途牛 App 到底能不能装/能不能跑」的完整取证，避免下一会话重复找包或把「安装成功」误写成「可用」。结论：包存在且已安装，**当前 MuMu 环境不能运行**。

### C.1 已安装/已尝试的包

| 包/版本 | 来源 | 结果 |
| --- | --- | --- |
| `com.tuniu.app.ui` 11.72.1（arm64） | 应用宝 Android UA 页 `/sjy.00022/...` | 安装成功；启动约 3s 后 `APP CRASH(NATIVE)`，栈在 `libtuniudns.so` |
| 11.60.0（arm64） | 豌豆荚历史版本 | 安装成功；同一 native 栈/偏移崩溃 |
| 9.36.0（armeabi-v7a） | 豌豆荚历史版本 | 可下载，但本机 ABI 不支持；`adb install --abi armeabi-v7a` → `ABI armeabi-v7a not supported on this device` |
| 11.49.0 / 11.40.0 / 11.27.0 / 11.12.0 / 10.35.0 | 豌豆荚中心目录抽查 | 均含 `libtuniudns.so`；均只有 arm64/armeabi，无 x86_64 |
| 官方 CDN `images.tuniucdn.com/android/p-17608/tuniu.apk` | 途牛官方下载页 | 官方只给这一个包；不是另一种架构 |
| APKPure / PGYER / 小米 | 其他市场 | APKPure 安全验证拦截；PGYER 地域限制；小米页无直接包。分发的是同一官方包，没有 x86_64 变体 |

### C.2 架构判据（为什么不是“缺安装包”）

- MuMu 6.0 / Android 15：`abilist = x86_64, arm64-v8a, x86`；`abilist32 = x86`（**无 armeabi-v7a**）。
- 系统只有 64 位 `/system/lib64/libhoudini.so`；没有 32 位 Houdini；`adb install --abi armeabi-v7a` 明确拒绝。
- MuMu 6.0 的 Android 12/15 引擎都是 **x64 镜像**；`nx_device/12.0` 当前为空，可下载但不是 ARM 原生镜像。官方帮助明确 `32-bit ARM (ARM32) apps are not supported`。
- 11.72.1/11.60.0 是 arm64 包，走 ARM64 转译；崩溃发生在 `libtuniudns.so`，不是登录/人脸/普通风控。11.60 与 11.72 的崩溃偏移一致，说明不是“版本太新”单一因素。
- 9.x 只有 armeabi-v7a，且用户已明确不再追太久远版本；即使装上也没有 32 位转译层。

### C.3 结论与边界

1. **当前 MuMu 环境：途牛 App 不支持**。不要把“安装成功”写成“可用”，不要把“页面能打开”当成“能采集”。
2. **途牛继续走 H5/API**：H5 国际与国内同页；PC 只查 30 天内，远日期交 H5/API；这是当前已验证通路。
3. 如果用户再次要求继续折腾：
   - 只允许**独立** Android 12 实例或真 ARM 手机实测；不动 live 实例 0，不改系统属性/转译层/root。
   - 先记录包来源/版本/ABI/启动栈；失败后清理自建实例。
   - 不再尝试 9.x/10.x 等太久版本（用户已明确）。
4. 对外表述：**“途牛 App 在当前 MuMu 6.0 / Android 15 环境确认不支持（原生库转译崩溃）；包已找到并安装，H5/API 仍可用。”** 这句话同时回答“是否缺包”和“是否支持”，不要含糊。

### C.4 当前设备上的最终状态

- 已恢复最新 `11.72.1`（不是 9.x），它仍会在启动时崩溃；不要用它登录/采集。
- 已安装飞猪 10.0.10.104、携程 8.97.0、同程 11.5.2；详见 §3.4/§5.3。
- 设备与 8765 共用；任何 App 实验前先看 `monitor.log` 的下一轮扫描与前台包。

---

## 附录 D：发布 / issue / 测试口径补充

- 已发布基线：`HEAD 0d4b058`、`v1.5.307`；tag/Release 名称以远端核对为准（本地 HEAD 处可见 `v1.0`）；上一轮 Release 正文/四平台资产/Pages/live 已核对。**本轮没有新 Release**，当前工作树不能直接发布。
- GitHub issues：上一轮已实现并关闭 #8–#11，当前应 0 open；下一会话用 `gh issue list`/API 复核，不要只引用本文。
- 测试口径（两次独立抽跑，不要相加）：
  - 主指南 §2.2：App+header+fingerprint 88 passed；链接/文案 177 passed（文件集合见 §6.4）。
  - 并行会话补充复跑（21:09–21:10）：App 8 文件 52 passed；链接/矩阵/指纹 6 文件 44 passed；stealth 2 文件 14 passed；`test_qunar_honesty` 1 failed/17 passed。
  - 两组文件集合/时间不同；报数必须带「命令 + 文件集合 + 时间」。红项归属见 §4.1。
- 全量 pytest/UI 668/四平台包/站点戳/资产/Release 尚未在本轮冻结树完成；**不能宣称全量绿或可发版**。

---

## 附录 E：本轮用户最后确认的决策

- 途牛 App：确认当前 MuMu 不支持就明确说不支持；不再追太久版本；包已找到并安装，问题在运行环境。
- MuMu 其他镜像：可以下载 Android 12，但仍是 x64；官方明确 ARM32 不支持；Android 12 未实测，不保证 64 位转译能过 `libtuniudns.so`。只有用户明确要求才建独立实例/真机实验。
- 飞猪：用户已明确被爬虫识别，暂停采集；恢复必须用户明确指令；不要启用 `app_fliggy`。
- 发版：本轮未授权新发版；任何 push/tag/Release/Pages/ghcr 变更必须重新全量验收并获明确授权。

---

## 附录 F：本指导书覆盖清单

本文件对用户本次要求的覆盖关系如下，下一会话可按此索引快速定位：

| 用户要求/目标 | 本文件位置 |
| --- | --- |
| 四个源会话的共同目标（未完成项继续推进） | §1.1、附录 A |
| 7/10 渠道平台能力矩阵与三态语义 | §1.1、§5.1、附录 A |
| 11 个质量轴（可配置/可观测/可干预/可见性/可溯源/可识别/可区分/可幂等/语义清晰/可指导/可判断） | §1.1 第 1 条、§5、§7 |
| 全项目覆盖、后续加渠道统一设计 | §1.1、§4.4、§5.3、§8 |
| 页面产品化、微信扁平化布局/交互 | §1.1、§1.2、§1.3、§7.10；细节见 `docs/SESSION_EXPERIENCE_GUIDE.md` |
| GitHub 代码/文档/tag/包/镜像/初版式 Release | §1.1、§7.11、附录 D |
| 关闭所有 issue | §1.1、附录 D |
| 途牛/Qunar/同程 PC 重新登录、途牛软风控、远日期限制 | §1.2、§3.2、§5.3、附录 E |
| 途牛 H5 国际与国内同页（用户纠正） | §1.2、§3.1、§3.2、附录 E |
| 飞猪/携程/同程/途牛 App 安装、登录、人脸渠道搁置 | §1.2、§3.4、§5.3、附录 B/C |
| 途牛 App 安装包/市场/架构/不支持结论 | 附录 C、附录 E |
| 指纹/HTTP 头 per-profile 稳定自洽（不随机化） | §1.2、§3.3、§5.4、§7.7 |
| 测试/证据/门禁/已知红项 | §2.2、§4.1、附录 D |
| 并行会话、主树/live 分叉、发版纪律 | §2、§4、§6、§7 |
| 下一会话怎么继续（顺序/命令/完成定义） | §6、§8、§10 |
| 用户最后决策与不要做的事 | 附录 E、§1.4、§8 |

> 如果用户要求“把整份指导书发在聊天里”，优先级是：先保证文件完整（本文件），再贴目录/摘要；不要把 700+ 行截断成半份。若文件被并行会话再次改动，先 `git status`/`mtime` 对比，再以最新内容为准。
