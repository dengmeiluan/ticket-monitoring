# App 渠道（智行 / 美团）接入设计

> 日期：2026-10-29
> 状态：待用户评审
> 前置实测：`docs/MOBILE_RUNTIME_VERIFICATION.md`、`docs/MOBILE_ZHIXING_A12_RESULT.md`、`docs/MOBILE_MUMU_ACCEPTANCE.md`

## 1. 目标与边界

把「只经 Android App 暴露数据」的渠道（智行、美团）接入现有监控框架，使它们在**配置、
健康、登录、告警、UI** 五个维度与现有 5 个浏览器渠道**同权**：

- **可选而非必须**：不启用时框架行为与今天完全一致（不 import、不检查设备、不提示）。
- **登录体验对齐 Chrome**：在网页内嵌模拟器实时画面，用户在自己的浏览器里点、输，
  完成后回同一页点「已完成」，与现有 `/api/login` + `/api/login-finish` 同一套心智。
- **首次引导**：新用户下到 exe，若未装 MuMu，出现引导页并可一键静默安装。
- **UI 语言一致**：复用现有令牌与六条语法，不引入第二套皮。

**不做**（YAGNI）：不做多设备并发采集（单实例串行足够）；不内置模拟器二进制进安装包
（照抄 `ensure_chromium` 的按需下载模式）；不做验证码自动破解（沿用人工接管边界）。

## 2. 实测数据（设计依据）

| 项 | 实测值 | 影响 |
| --- | --- | --- |
| `adb exec-out screencap` | **63–91 ms** | 网页画面 ~13fps，够用，不需要 WebRTC 串流 |
| `uiautomator dump` | **75–77 ms** | 元素定位可实时，无需截图识别 |
| 实例冷启动 | **24–36 s** | 引导页/健康面板必须显示"启动中"，不能让用户以为卡死 |
| `adb root` | 可切换（`su` 不存在，但 `adb root` 有效） | 登录态快照可读 `/data/data/<pkg>/` |
| 智行数据目录 | 145 MB（其中 `app_ctripwebapp6` 128 MB 是缓存） | 快照只取 `shared_prefs`+`databases`+`files` ≈ **9 MB** |
| 智行 64 位包 | `cn.suanya.zhixing` 104 MB，`arm64-v8a` | 必须按 ABI 选包，见 `feedback-sample-one-link-is-guessing` |
| 智行未登录 | 日历价可读，单班价遮为 `¥3??` | 未登录只能进**日历族**；明细需登录 |

## 3. 架构

```
core/android/
  runtime.py      AndroidRuntime：发现/启动/停止/健康/设备锁（唯一接触 MuMu/ADB 的地方）
  device.py       Device：screencap / tap / swipe / dump / input / app_start（adb 原语）
  loginstate.py   快照导出/恢复/校验（shared_prefs + databases）
  bootstrap.py    首次引导：检测→下载 MuMu 安装器→静默装→装 APK→体检
crawlers/app_base.py        AppCrawler（新基类，不继承 Playwright 的 BaseCrawler）
crawlers/app_zhixing.py     智行：日历族 + 明细（需登录）
crawlers/app_meituan.py     美团：日历族 + 明细（需登录）
```

**为什么新基类**：现有 `BaseCrawler` 的 `browser()` / `_browser_context()` 全部是 Playwright
实现，App 渠道继承它会把用不上的浏览器路径一起带进来，且容易误调。新基类只保留复用价值的
部分：`path_reset/path_note`（账本）、`safe_fetch` 契约、`FlightPrice` 产出、`login_url()`
的语义（App 渠道返回 App 的登录入口描述而非 URL）。

**设备是单例资源**：一个模拟器实例同一时刻只能被一个采集占用。用
`threading.Lock`（模块级）而不是 `BoundedSemaphore(2)`——现有 `CHANNEL_GATE=2` 对浏览器
合理（多实例），对单个 adb 设备会造成并发踩踏。

## 4. 数据流

### 4.1 采集

```
调度 → get_crawlers() → AppZhixingCrawler.fetch(from,to,dates)
  → runtime.ensure_ready()          # 实例在跑？adb 通？否则启动并等（含超时与"启动中"状态）
  → runtime.device_lock()           # 独占设备
  → loginstate.restore_if_needed()  # 对照快照，过期则跳过并标记 needs_login
  → device.app_start(pkg) → 导航到查询页 → 填起降/日期 → 点查询
  → device.dump() 解析：日历价 / 航班行
  → path_note("app-calendar"|"app-list", "ok"|"empty"|"login"|"timeout", rows)
  → [FlightPrice(...)]
```

**状态诚实**：App 里的「查无航班」「网络异常」「请登录」一律不得记成 `empty`；
沿用 r398–r404 的口径——`login` 进 `PATH_STATUS` 已声明的 `login`，
解析失败记 `timeout`/`blocked`，只有拿到明确的"无结果"文案才记 `empty`。

### 4.2 登录（网页内嵌画面）

```
POST /api/app-login  {plat:"zhixing"}            → 建会话（Content-Type: application/json，同源校验）
  → 后台线程：runtime.ensure_ready() → app_start → 停在登录页
  → 注册到 registry，status="pending"
GET  /api/app-login/frame?plat=zhixing           → PNG（screencap，63–91ms）
POST /api/app-login/tap   {plat, x, y}           → device.tap(x,y)      # 坐标按原图尺寸，服务端按实际分辨率换算
POST /api/app-login/input {plat, text}           → device.text(text)    # 焦点已在 App 内，走 input text
POST /api/app-login/key   {plat, key}            → device.key(key)
POST /api/app-login/finish{plat}                 → 快照导出 + 注入"已登录"校验 + 关闭会话
```

前端：登录卡展开后是 `<img>` + 一个透明点击层；`setInterval` 250ms 拉帧（≈4fps 足够看清），
点击立即回传。帧请求带 `If-None-Match`（内容哈希），无变化返回 304，避免无谓带宽。

**"丝滑"的判据**（对齐 Chrome 登录）：
- 用户**不离开浏览器**即可完成全部操作；
- 输入验证码时画面延迟 < 400ms（250ms 轮询 + 63ms 截屏）；
- 完成登录后 2 秒内登录卡变「已登录 · 刚刚」，无需手动刷新；
- 任何一步失败都有明确文案 + 重试入口，不停在"加载中"。

### 4.3 登录态快照

- 导出：`adb root` → `tar` 打包 `shared_prefs/ + databases/ + files/`（排除缓存）→ 落到
  `user_data/<profile>/android_snapshot_<plat>.tar.gz`（约 9 MB）。
- 恢复：`app_stop` → 解包 → `app_start`。
- 校验：app 启动后 dump 首页，出现"我的/个人中心"且不含"登录/立即登录"即视为有效。
- 手动导入导出：配置页登录卡提供「导出登录态 / 导入登录态」，文件落地由用户选择。

**安全**：快照等同 cookies，不做任何上传；文件权限沿用现有 `user_data` 目录策略；
UI 上明确写「此文件等同账号凭证，请勿分享」。

## 5. 配置（全部可选）

`config.yaml` 新增顶层 `android:` 段（**缺省即不启用**）：

```yaml
android:
  enabled: false            # 总开关；false 时下面全部不生效
  provider: mumu            # 目前仅 mumu
  install_dir: ""           # 空=自动探测 D:\Program Files\Netease\MuMu
  vm_index: 0
  boot_timeout_s: 120       # 冷启动实测 24–36s
  action_timeout_s: 60
  snapshot: true            # 是否导出登录态
  devices:                  # 预留，当前只用第一台
    - serial: "auto"
```

渠道侧：

```yaml
users:
  - platforms: [qunar, fliggy, ctrip, app_zhixing, app_meituan]   # 新增两个 id
```

**取舍**：渠道 id 用 `app_zhixing` / `app_meituan` 而非 `zhixing`，避免与未来可能的
Web 版智行混淆，也让 UI 能一眼区分"App 渠道"。

## 6. UI（复用现有语言）

### 6.1 配置页 · 新增「App 渠道」分组卡

- 位置：配置页「渠道与登录」之后，同卡片语法（`.ucard`，不套卡）。
- 行结构（遵守"行式信息结构"）：左 = 渠道名 13px/600，中 = 状态 12px `--mut`，右 = 动作文本按钮。
- 状态取值与现有登录卡同一套枚举：`未启用 / 未安装 / 启动中 / 就绪 / 需登录 / 已登录`。
- 卡头动作：`检测环境`（重新探测设备）。行级动作：`安装模拟器`（未安装时）/ `登录`（需登录时）。

### 6.2 登录卡内嵌画面

- 容器宽 = 卡内容宽，高按 9:16 上限 480px，`background: var(--headbg)`。
- 画面用 `object-fit: contain`，避免拉伸；点击层做坐标换算。
- 底部一行 `< 480px` 时改为「在模拟器窗口登录」降级按钮（不新增折叠层级）。

### 6.3 首次引导（onboarding）

- 触发：启动时 `android.enabled=true` 但运行时不存在 → 主视图顶部出现一条引导
  （复用 `.hero` 空态语法，不新造组件）：
  「App 渠道需要 Android 运行时 · 检测到你还没装 MuMu · 约 7 GB」+ `安装并继续`。
- 点击后进入**进度态**（不是弹窗）：分阶段展示 `下载安装器 → 安装 MuMu → 启动实例 →
  安装 App → 完成`，每阶段有真实进度来源（`MuMuManager info` / 文件大小）。
- 全程可取消；失败给出原因与「重试」；已完成阶段不重复执行（幂等）。
- **不启用 android 的用户永远看不到这块**。

### 6.4 品牌图标

新增 `--c-zhixing` / `--c-meituan` 令牌 + `SRX_BRAND_IMG` 两个图标，
否则 `srxPlatIcon()` 会退化成字母块（现有 fallback 行为）。

## 7. 健康 / 账本 / 告警对齐

| 面 | 要做的事 |
| --- | --- |
| `core/health.py` | `PLATFORMS` + 两个正则加入 `app_zhixing`/`app_meituan`，否则日志行被静默丢弃 |
| `core/pacing.py` | `PLATFORMS` 加入；`cadence` 为 App 渠道单独给（受设备串行约束，默认更宽） |
| `core/special_radar.py` | `_CHANNELS` + 分支；App 渠道暂返回 `not_connected` 并给明确原因，不假报 |
| `core/channel_links.py` | `ENTRY` 新增 `("app","domestic")` surface，避免 KeyError；链接可直接用 `sdp.suanya.com` 深链 |
| `core/login_slots.py` | 新增两个 slot，`slot_crawler()` 增加 app 分支（不返回 Playwright crawler） |
| `core/channel_alert.py` | `CN` 名称 |
| 设备健康 | 新增一条「Android 运行时」健康行：实例状态 / adb / 最近一次 `adb` 错误 |

## 8. 测试计划（TDD，先红后绿）
> 下列文件名是**计划名**：落地时按实际实现拆分/改名，未创建者已在行内标注，
> 照抄命令前先 `ls tests/` 核对。已落地：`test_app_zhixing_parse.py`、
> `test_app_zhixing_calendar.py`、`test_app_zhixing_crawler.py`、
> `test_app_blocker_flow.py`、`test_app_snapshot.py`、`test_app_login_api.py`。

1. `tests/test_app_runtime.py` — 计划未创建；用假 `MuMuManager`/`adb`（subprocess 打桩）验证：
   未启用时不调用任何外部进程；启用且设备缺失时返回明确 `not_installed`；启动超时路径。
2. `tests/test_app_zhixing_parse.py` — 用真实 dump 快照（脱敏后存 `tests/fixtures/`）验证：
   日历价解析、航班行解析、`¥3??` 被识别为 masked 而非价格 0、门拒文案不记为 empty。
3. `tests/test_app_meituan_parse.py` — 计划未创建（美团解析未接入）。
4. `tests/test_app_login_state.py` — 计划未创建；快照导出/恢复幂等；快照缺失时不阻塞采集，标 `needs_login`。
5. `tests/test_android_config.py` — `android:` 缺省不启用；启用后新增 key 全部有控件+回读
   （满足 `test_r523_no_unconfigurable_keys`）。
6. 既有门禁同步：`test_channel_links`（格数）、`test_login_slots`（顺序）、
   `test_channel_ui_status`（卡数）、`test_docs_code_contract`（渠道数/文档）——
   **这些改成"按配置实际启用数计算"，而不是死写 5**，否则渠道可选这件事在门禁层面就自相矛盾。

## 9. 发布与首次体验

- `requirements.txt` 新增 `uiautomator2`、`adbutils`（**import 守卫**，未启用零开销）。
- `TicketMonitor.spec`：不打包模拟器；`collect_all` 仅对 adbutils 的 adb 二进制做必要处理。
- 复用 `ensure_chromium` 模式：`main.py` 增 `ensure_android_runtime()`，启动时**按需**检查；
  CLI 增 `--install-emulator`。
- 文档：README 增「App 渠道（可选）」一节，明确 7 GB 体积、Windows-only、需 VT；
  `docs/` 增 `APP_CHANNELS.md` 操作手册（含卸载、迁移、快照说明）。
- 发布门禁照旧：版本号/资产/Pages 对齐、EOL 纯净（新文件纯 LF）。

## 10. 风险与对策

| 风险 | 对策 |
| --- | --- |
| MuMu 静默安装需管理员 | 引导页明确提示"需要一次管理员确认"，失败给手动安装说明 |
| App UI 改版导致定位失效 | 定位全部走"文案锚点 + 结构"，不写死坐标；失效时 `path_note` 记 `blocked` 并给醒目健康提示 |
| 单设备串行拖慢整轮 | App 渠道默认 cadence 放宽；与浏览器渠道并行（不同资源） |
| 智行未登录只有日历价 | 明确标 `日历族`，不冒充明细；UI 显示「未登录 · 仅日历价」 |
| Hyper-V 冲突 | 已实测 MuMu 与 Hyper-V/VBS 共存（`hyperv_enabled: true`） |
| 快照泄露风险 | 不外传、权限收紧、UI 明示等同凭证 |

## 11. 分阶段交付

| 阶段 | 内容 | 可验证结果 |
| --- | --- | --- |
| **P1** | `core/android/` 运行时 + 设备原语 + 智行采集（未登录日历族） | 真实跑一轮，落库日历价 |
| **P2** | AppCrawler 接入框架：REGISTRY/健康/账本/配置项/UI 状态行 | 配置页可开关，健康可见，不启用无副作用 |
| **P3** | 网页内嵌登录画面 + 快照导入导出 | 不离开浏览器完成智行登录 → 明细价可采 |
| **P4** | 美团渠道（同构复用 P1–P3） | 两渠道并行 |
| **P5** | 首次引导 + 安装器下载 + 文档 + 发布 | 干净机器从零跑通 |

每个阶段结束跑一次全量门禁，红灯必须解释清楚是"值变了"还是"设计坏了"。
