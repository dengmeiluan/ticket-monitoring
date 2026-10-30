# 移动端渠道（智行 / 美团）在「无手机常驻」前提下的可实施方案

> **这一组共 5 份文档，按用途分工**（2026-10-27）：
>
> | 文档 | 回答什么 |
> | --- | --- |
> | **本文** `MOBILE_CHANNEL_OPTIONS.md` | 总览：先纠正前提（缺的是渠道不是端），给出可行性与代价 |
> | `MOBILE_PATH_B_PLAN.md` | 路径 B 实施方案：比选各 Android 运行时（应用宝引擎/MuMu/LDPlayer）的磁盘/内存/共存 |
> | `MOBILE_RUNTIME_VERIFICATION.md` | 运行时验证：各方案「能否脚本化」的实测判据与目前仍成立的选择 |
> | `MOBILE_MUMU_ACCEPTANCE.md` | MuMu 验收：**安装一次人工 → 之后全自动**（`adb connect` 免点界面、美团跑通） |
> | `MOBILE_ZHIXING_A12_RESULT.md` | 智行最终结论：**有 64 位包**、装对后列表可读（推翻前两版） |
>
> 易混点：`/S` **静默安装**不成立（MuMu 实测跳到向导页），但**装完之后**的
> `launch / app install / adb shell` 全可脚本——两个阶段别混为一谈。

> 结论与代价均为 **2026-10-27 本机实测**，逐条标注「实测 / 官方文档 / 未实测」。
> 本文只给**可行性与代价**，取舍留给使用者。

## 0. 先纠正一个前提：缺的不是「移动端」

本项目五个渠道的 H5 就是移动 Web：`crawlers/base.py` 的 `_viewport()` 用 390×844、
`MOBILE_UA` 为 iPhone Safari、`fingerprint()` 打开 `is_mobile/has_touch`，飞猪 H5
还有独立登录槽位（`core/login_slots.py`）。所以「PC/H5 都支持，但缺移动端」这个描述
不成立——**真正缺的是「没有 Web 面、只经 App 暴露数据」的两个渠道：智行、美团。**

判断一个新渠道该走哪条路，第一步永远是「它有没有 Web 面」，第二步才是「用哪种端」。

## 1. 实测事实（决定所有方案是否成立）

### 1.1 智行 = 携程系 App，Web 面不存在

| 探测 | 结果 |
| --- | --- |
| `zhixing.com` / `zx12306.com` | `ERR_CONNECTION_CLOSED`（实测） |
| `flight.suanya.com` / `air.suanya.com` | 连接中断（实测） |
| `m.suanya.com` | 存活，但只有火车票；`/webapp/flight` 404（实测） |
| App 包体 | `com.yipiao` 10.26.0（应用宝官方源）83.6 MB，**`lib/` 只有 `armeabi`**（实测，51 个 .so / 43.5 MB 解压） |
| App 技术栈 | React Native（CRN）：`libhermes.so`、页面全是 `rn_taro_flight_*` 的 `_crn_config`（实测） |
| App 后端 | dex 内主机名指向 `m.ctrip.com/restapi`、`gateway.m.ctrip.com`（实测） |
| 直连尝试 | `/restapi/soa2/19913/json/flightListSearch` → `403 code 11010 Operation Forbidden`；其它 soa2 路径 404（实测） |

即：智行的机票数据只走 App，且请求带携程 SOA 网关的鉴权/签名，
**没有「在 PC 浏览器里换个 UA 就能拿」的入口**。

### 1.2 美团 = 有 H5，但只有「日历」这一半活着

| 探测 | 结果 |
| --- | --- |
| `getLowPriceCalendar` | **可用**，`apicode=10000`，返回 61 天 `{date, price?, icon?}`（实测） |
| `_token` | **不是必需**。去掉 token 甚至伪造 `_token=abc` 都返回同样数据（实测，纠正了此前笔记） |
| 覆盖范围 | 只 61 天固定窗口：`startdate` 参数被服务端忽略，永远从**今天**起算到 +60 天（实测：填 2027-03-01 仍返回 10-27~12-26） |
| 航线范围 | **只国内**。PEK-SHA / SHA-CAN / SHA-HAK / HAK-SHA 均有价；**SHA-NRT / SHA-BKK / SHA-SIN / SHA-HKG 全 61 天空**（实测） |
| 机场码 vs 城市码 | 必须机场三字码；`BJS-SHA` 全空（实测） |
| 列表接口 | `getflightwiththreecode` 恒回 `{"msg":"paramError"} apicode=10006`，带 H5 Referer/完整参数亦同（实测，**别再枚举参数**） |
| PC 页面 | `meituan.com/flight/` → 301 回首页；`/jipiao` → 308 回 `/jipiao`（实测） |
| 国际日历入口 | 无（`intl-flight` / `flight-intl` 主机不解析） |
| 背包 | `com.sankuai.meituan` 12.67.402，103.6 MB，**`lib/` 只有 `armeabi`**；XAPK 版仅拆出 `arm64-v8a`（实测） |

价格稳定性：同一航线连续两次请求结果一致（实测），但**口径（含税/裸价）尚未与本项目
其它渠道同航班对账** —— 按项目规矩（LESSONS §6），未对账前不得当含税价落库。

### 1.3 两个 App 都是 ARM-only，这条路只能靠「翻译层」

| 运行环境 | 能否跑 armeabi APK | 依据 |
| --- | --- | --- |
| Google AOSP/Play x86_64 模拟器 | **不能**（AOSP 无 ARM 转译） | 官方博客：转译只在 Google APIs / Play 镜像提供，且仅限开发调试（[官方](https://android-developers.googleblog.com/2020/03/run-arm-apps-on-android-emulator.html)） |
| MuMu 12 / LDPlayer / BlueStacks 5 | 可以（自带 ARM→x86 翻译） | 官方技术手册称 arm 代码运行时翻译为 x86（[MuMu](https://developer.taptap.cn/docs/pc-store/sim-intro/sim-tech-manual/)） |
| 应用宝「移动应用引擎」(Androws) | 可以（Intel Bridge + Celadon，Android 13） | 微软商店的「智行火车票」条目就是 **`Installer.Type=TencentAndroid`、`Id=com.yipiao`**，即 APK 由该引擎承载（实测 Store API） |
| 阿里云无影云手机 / 华为云 CPH | 可以（ARM 服务器，原生 arm64） | 官方 adb 文档（见 §2 路径 D/E） |
| WSA | 不可用 | 2025-03-05 停止支持、2025-07 从商店移除（官方） |

## 2. 可实施路径总表（全部 PC 侧，无需手机）

| # | 路径 | 覆盖渠道 | 拿到什么粒度 | 增量体积 | 常驻/无人值守 | 实测状态 |
| --- | --- | --- | --- | --- | --- | --- |
| **A** | 美团日历纯 HTTP | 美团（国内、61 天内） | **仅每日最低价**，无航班号/时刻 | **0**（现有 httpx） | 完全 | ✅ **已跑通** |
| **B** | 应用宝引擎 / Androws 跑 APK + adb + uiautomator2 | 智行、美团 | UI 上能读到的全部 | 引擎数 GB + 5GB 盘 | 需引擎常驻 | ⚠️ 未实测（本机未装） |
| **C** | MuMu 12 模拟器 + adb | 美团 ✅、智行 ✅（装 64 位包） | 同上 | 实例装完实测 **9.3 GB**（两个 App 都装好后） | 需模拟器常驻 | ✅ **MuMu 12 已实测**（`adb connect 127.0.0.1:16384` 免点界面，见 `MOBILE_MUMU_ACCEPTANCE.md`）；LDPlayer 9 **未实测** |
| **D** | 阿里云无影云手机（adb 5555） | 智行、美团 | 同上 | **0 本地** | 云端常驻 | ⚠️ 未实测（有官方 adb 文档） |
| **E** | 华为云 CPH（adb + Airtest 官方最佳实践） | 智行、美团 | 同上 | 0 本地 | 云端常驻 | ⚠️ 未实测（整机租用） |
| **F** | 反编译 RN bundle 直连携程 SOA | 智行 | 明细 | 0 | 完全 | ❌ 403 已否证（签名/风控） |
| **G** | 微信 PC 小程序 | 智行/美团小程序 | — | 0 | 不可靠 | ❌ 无公开自动化入口 |

> **C 行的两次结论更正**（避免互相矛盾）：①MuMu 12 已从「未实测」变为**已实测通过**
> （2026-10-27，见 `MOBILE_MUMU_ACCEPTANCE.md`）；②`MOBILE_MUMU_ACCEPTANCE.md` 里写
> 「智行装不上（只有 32 位 armeabi）」是**当次未找到 64 位包**的旧结论——同日的
> `MOBILE_ZHIXING_A12_RESULT.md` 已推翻：应用宝同页第二个链接就是 `arm64-v8a`（104.0 MB），
> 装对即可。以 `MOBILE_ZHIXING_A12_RESULT.md` 为准。

### 路径 A：美团日历（唯一「立刻可做」的一条）

已落成可跑脚本：`_scratch/spike_mobile/meituan_calendar_http.py`
（纯 `httpx`，无浏览器、无 token、无登录；`python ... SHA HAK --start 2026-11-16`）。

- 接入成本：一个 httpx crawler（照 `crawlers/tuniu.py` 的纯 httpx 骨架），不需要
  `ensure_chromium`、不需要 adb、不需要设备。
- **硬限制（必须先接受，否则不要做）**：
  1. 只有每日最低价 → 属于项目里的「日历族」通路（`core/models.py` 的
     `CAL_PATH_FAMILY`），只能进日历/窗历视角，**不能进明细、不能比航班号**；
  2. 只有国内 + 只有今天起 61 天 → 当前 `config.yaml` 的 6 条航线
     （SHA-NRT / SHA-BKK / SHA-SIN / SHA-LHR / SHA-HAK / HAK-SHA）中**只有 2 条国内线**，
     且日期（2026-11-16 / 2027-01-29 / 2027-02-14）**全部落在 61 天窗口外**
     （实测：换 `startdate` 无效）→ **对现有配置的实际增量几乎为零**；
  3. 计价口径未对账 → 接入时要么先与携程/同程同航班对账，要么在 `price` 旁标注
     「口径未证实」，不得与含税渠道直接比价。
- 落地要动的注册点（照现有 5 渠道）：
  `crawlers/__init__.py:9` REGISTRY、`core/pacing.py:27` PLATFORMS、
  `core/health.py:17`、`core/channel_links.py:13` PLATS + `:57` ENTRY、
  `core/special_radar.py:38`、`webui.py` 的 `PLATS/SRX_PLATS/_LOGIN_PLATS/_WATCH_PLATS`，
  以及 `tests/test_channel_links.py:14`（断言恰好 20 格，加渠道必红，需同改）。

### 路径 B/C：本机 Android 运行时 + adb（无需手机，但要常驻一个引擎）

**关键优点：adb 接口对真机/模拟器/容器完全一致**，所以 B、C、D、E 的上层代码是同一份
（uiautomator2 / Appium），只换连接地址。

- adb 本体：`adbutils` 已随依赖装好自带 `adb.exe`（**6.33 MB，v36.0.0**），
  且**非管理员即可启动**（实测：`adb start-server` 成功、`adb devices` 正常返回空列表）。
- 应用宝引擎：微软商店的智行条目实际就是 APK + 腾讯引擎（Store API 实测
  `Installer.Type=TencentAndroid`、`com.yipiao`）；adb 端口为 `127.0.0.1:5555`
  （社区文档 MAA，未自测），**但 5.10.27.10 起 adb 默认关闭**，
  需在设置里连点性能 7 次开开发者模式（官方 FAQ）。
- MuMu 12：单实例 adb `16384`（+32/实例），`MuMuManager.exe control -v 0 launch|shutdown|hide_window`
  可脚本化；官方称已兼容 Hyper-V/VBS（官方）；安装常需管理员（官方 FAQ）。
- 本机实测到的限制：`HypervisorPlatform` 功能**未启用**（`InstallState=2`），
  当前为「Hyper-V 已存在 + VBS 开启」的形态；且当前会话**非管理员**，
  无法启用 WHPX。→ 选 B/C 时，要么用应用宝引擎（免管理员、免镜像），
  要么需要一次管理员操作来装模拟器。
- 代价（估算，未实测）：单次查询 15–45s → 分钟级；App 改版即失效；
  扫描调度要求「在扫描时刻设备在线」，即引擎必须常驻后台。

### 路径 D/E：云手机（本地零常驻，代价是租金与合规）

| 供应商 | adb / API | 装任意 APK | 费用（官方） | 备注 |
| --- | --- | --- | --- | --- |
| 阿里云无影 | **有**：TCP 5555 + 密钥，`StartInstanceAdb` / `RunCommand` / `SendFile` | 控制台上传或 adb | ¥65/月（2c4G），按量 4 小时粒度，**关机仍计费**；开 ADB 需标准网络 ≈ +¥20/Mbps/月 | 最适合脚本化 |
| 华为云 CPH | 有：监听 IP:端口 + `InstallApk`/`RunShellCommand` | 是 | 整机租用、无按量 | 官方最佳实践即 Airtest over adb；无 root |
| 腾讯云 CVP | 有，但**不开放公网 IP**，需商务 | 是 | ¥265/卡/月起 | 要求企业实名，不建议个人 |
| 火山引擎 ACEP | adb 需申请开通，链接 24h | 是 | 未公开 | — |
| 百度 BAC | **不支持 adb** | 仅控制台 | — | 直接排除 |
| 红手指/雷电云 | 仅靠 PC 客户端做 localhost 转发 | 是 | ¥34–38/月 | 客户端必须常驻，反而不如 D |

D/E 的真实风险：这类 App 的风控会识别云手机/模拟器环境（机型、传感器、GPU 一致性），
且自动化本身可能违反智行/美团自己的用户协议——云厂商的条款不为其背书。

### 路径 F：直连 API（已否证，只留记录）

dex 里 `flightsignature`、`setSoa_sign`、`hmacSha` 等字符串表明请求带签名；
实测 `/restapi/soa2/19913/json/flightListSearch` 回 `403 / 11010 Operation Forbidden`。
**不要再花时间枚举 soa2 路径**——这与美团参数枚举是同一类死路。

### 路径 G：微信 PC 小程序（不建议）

Windows 微信 4.x 可以打开并固定小程序（官方 PC 小程序接入指南），但
`miniprogram-automator` 只能驱动**自己的开发者工具项目**，已发布小程序的调试要靠
社区 hook（版本一更新即失效）；且并非所有小程序适配 PC。没有稳定自动化面。

## 3. 推荐顺序（按「代价/收益」）

1. **先做 A（美团日历）**，但只在你确实要国内、且愿意接受「只有最低价 + 61 天窗口」时做；
   同时它能在 PC 上零设备跑通，可作为「移动端数据可达」的最小证明。
2. **若必须要智行**：先用 **B（应用宝引擎）** 做一次性 POI 验证——
   它免镜像、adb 5555 现成（是否需管理员未实测），验证「能否登录、能否看到机票列表、一次查询多久」。
   体验不达标再考虑 **C（MuMu）** 或 **D（阿里云云手机）**。
3. **F/G 不要投入**；E 只在有长期云端预算时考虑。

## 4. 无论走哪条路，都必须遵守的项目既有约束

- **empty 必须有明确无票证据**：智行/美团 UI 上的「查无航班」「稍后重试」「门拒文案」
  一律不能记成真无票（对应最近 r398–r404 的整改）。
- **口径未对账不得对比价**：美团日历价的含税性未证实。
- **日历族不能冒充明细族**：只有价、无航班号/时刻的，归 `日历/窗历` 通路。
- **不绕过验证码**：`docs/CAPTCHA_SOLUTION.md` 的人工接管边界对 App 同样适用
  （App 里出现滑块/登录墙时，只能人工接管，不做自动破解）。

## 5. 本文未验证的事项（不要当结论用）

- 应用宝引擎 / MuMu 在本机的真实启动耗时、内存占用、能否长期无人值守（**均未安装实测**）。
- 智行 App 在未登录状态下能否看到国内机票列表价。
- 美团 App 内机票入口是否强制登录（H5 侧已知弱）。
- 美团日历 `price` 是含税还是裸价。
- 云手机对这两个 App 的风控实际拦截率。

## 6. 一次性探针（可删）

- `_scratch/spike_mobile/meituan_calendar.py`：Playwright 版，抓页面自身发出的请求。
- `_scratch/spike_mobile/meituan_calendar_http.py`：纯 httpx 版（推荐，无浏览器）。
- `_scratch/mobile_paths/apk/`：四个 APK/XAPK 样本（约 448 MB），仅用于 ABI 取证，可删。
