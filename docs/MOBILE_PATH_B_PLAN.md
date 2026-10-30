# 路径 B 实施方案：本机 Android 运行时 + adb + uiautomator2

> **2026-10-27 实测更新（见 `docs/MOBILE_RUNTIME_VERIFICATION.md`）**：
> 按「连安装都必须脚本化」的判据复核后，**应用宝引擎已被证伪**（ADB 只能在 GUI 里
> 连点「性能」7 次开启，无命令行开关）；**MuMu 12 的 `/S` 也无效**（跳到安装向导页）；
> **Google AOSP x86_64 镜像虽有 native bridge 框架，但全量扫描 8203MB 未发现任何
> ARM 翻译器实现**（`libndk_translation` / `libhoudini` / `libnb.so` 命中均为 0），
> 因而跑不了 armeabi-only 的智行/美团 APK。
>
> 本文以下内容保留作为「若接受一次人工安装」时的操作手册；是否采用请以验证记录为准。

> 目标：**不用手机常驻**，在本机跑起智行、美团，由 Python 读取机票列表价。
> 本文所有「实测」均为 2026-10-27 本机实测；「未实测」明确标注，不当结论用。

## 0. 为什么 B 是先做的那条（原始判断，已被 §验证记录 修正）

> 下表是**验证前**的判断，保留以示推演过程；实际结论见文首更新与
> `docs/MOBILE_RUNTIME_VERIFICATION.md`。

| 维度 | B（应用宝引擎） | C（MuMu 12） | C'（LDPlayer 9） |
| --- | --- | --- | --- |
| 磁盘（官方） | 「磁盘剩余可用空间 >5G」 | 「安装盘 2G + 系统盘 1.5G」 | 「**最少 36GB** 可用」（推荐 100GB） |
| 内存（官方） | 「>=8G」，且剩余 >3G | 「4G 及以上」 | 「2GB」起（推荐 16GB） |
| CPU（官方） | 「>4 核」 | 未列核数 | x86/x86_64 |
| 与 Hyper-V | 官方两处说法冲突（见下） | 官方称已兼容 | — |
| 商店入口 | 有（Store 里智行条目即腾讯引擎承载） | 需自行下载 | 需自行下载 |
| 是否需管理员 | 未实测 | 官方 FAQ 有「需要管理员权限」条目 | 未实测 |

**Hyper-V 说法冲突（同一官网，两份文档）**：`sj.qq.com/faq/368` 仍写着
「Hyper-V 关闭」，而 `sj.qq.com/faq/2989` 与两篇官方博客说
「应用宝电脑版 3.0.58.0 版本已经全面支持 Hyper-V」「无需关闭 Hyper-V」。
→ 取「较新文档更可信」的读法，但**以本机实装结果为准**，不拿文档当结论。

**磁盘落点差异（重要）**：应用宝会在「此电脑」里挂载一个**虚拟磁盘**（官方 FAQ 有
「腾讯应用宝虚拟磁盘」条目）；社区反馈其上限可达数十 GB，但为按需增长（社区，未自测）。
MuMu 明确区分「安装盘 2G + 系统盘 1.5G」两个位置。若你的 C 盘紧张，这一条比总容量更关键。

本机现状（实测）：Hyper-V 存在、**VBS/HVCI 运行中**（`VirtualizationBasedSecurityStatus=2`、
`CodeIntegrityPolicyEnforcementStatus=2`）、`HypervisorPlatform` 未启用、当前会话**非管理员**。
→ Hyper-V 共存这条**风险已下调**（官方新文档称兼容），但仍需实装验证；
`docs/MOBILE_CHANNEL_OPTIONS.md` §5 仍保留为未验证事项。

## 1. 第 0 步：先做设备体检（已可用）

```bash
python _scratch/spike_mobile/android_bridge.py
```

**当时**（本文写作时本机尚未安装任何 Android 运行时）跑它会诚实输出「未发现设备」；
2026-10-27 已装 MuMu 并起实例，现在跑会直接列出该设备的 CPU/ABI。装完引擎后再跑，
它会告诉你四件决定成败的事：

1. `ro.product.cpu.abilist` —— 引擎到底支不支持 **32 位 ARM**；
2. 两个包是否已安装；
3. `--install` 时若报 `INSTALL_FAILED_NO_MATCHING_ABIS`，说明该引擎不吃 `armeabi`；
4. `--dump` 能否拿到 UI 层级（这决定能不能做元素定位）。

## 2. 为什么 ABI 是这条路的第一道门（实测）

两个 App 的 APK 我逐字节验过：

| 包 | 版本 | `lib/` 目录 | ELF class | e_machine | e_flags |
| --- | --- | --- | --- | --- | --- |
| `com.yipiao` | 10.26.0 | **只有 `armeabi`**（51 个 .so） | 32 位 | 40 = EM_ARM | `0x05000000`（EABI v5 软浮点） |
| `com.sankuai.meituan` | 12.67.402 | **只有 `armeabi`**（71 个 .so） | 32 位 | 40 = EM_ARM | 同上 |

- 全包扫描：**没有任何 `lib/x86` / `lib/x86_64`**；
  `assets/` 里的 `libwbsafeedit_64`、`libwbsafeedit_x86_64` 是微博 SDK 的分享桩，不是 App ABI。
- 结论：引擎必须能把 **32 位 ARMv5** 翻成 x86。32 位 ARM 支持弱于 arm64 的引擎会直接装不上
  （`INSTALL_FAILED_NO_MATCHING_ABIS`）或首次调用 native 就崩。
- 另一个好消息（实测）：`uiautomator2` 的 agent 包 `app-uiautomator.apk` **不含任何 .so**，
  纯 Java 实现，所以**自动化层不受 ABI 影响**——门只在 App 本身。

## 3. 第 1 步：装引擎并打开 ADB

### 3.1 选一个引擎

- **应用宝电脑版（Androws）**：adb 端点 `127.0.0.1:5555`（社区文档，未自测）。
  官方 FAQ：从 PCYYB `5.10.27.10` 起 **ADB 默认关闭**，开启方式为
  「市场界面 → 设置 → 对『性能』连点 7 次 → 勾选开启开发者模式 → 保存」，
  一次开启后**卸载前永久生效**（官方）。
  引擎装在 `...\Tencent\Androws\Application\<版本>\`，该目录下有 `adb.exe`（社区文档，未自测）。
- **MuMu 12**：adb 端点实例 0 = `127.0.0.1:16384`（每实例 +32；5.0 起改为 5555/+2）。
  支持 ABI `armeabi-v7a / arm64-v8a / x86 / x86_64`（官方开发者须知名单），
  可用 `/data/system/etc/mumu-configs/abi-select-android12.config` 强制某包走 `armeabi-v7a`（官方）。

### 3.2 开 ADB 后立即体检

```bash
# 应用宝
adb connect 127.0.0.1:5555
# MuMu 12（实例0；端口以「设备诊断」显示为准）
adb connect 127.0.0.1:16384

python _scratch/spike_mobile/android_bridge.py --install
```

`--install` 会用 `adb install -r` 装本仓 `_scratch/mobile_paths/apk/` 里已下的两个官方包
（`com.yipiao_10.26.0_yyb.apk`、`com.sankuai.meituan_12.67.402_yyb.apk`）。

> 应用宝可能有自己的安装校验；社区做法是通过它内置的文件管理器/MT 管理器侧载，
> 或用 `adb install`。若 A 失败再走 B，不要反过来（社区文档，未自测）。

## 4. 第 2 步：让 uiautomator2 接管

```bash
python -m uiautomator2 init          # 往设备推 atx-agent
```

```python
import uiautomator2 as u2
d = u2.connect("127.0.0.1:5555")     # 应用宝；MuMu 用 16384
print(d.window_size(), d.info)
```

`u2.connect(serial)` 的签名与能力已在本机核实（v3.7.0 `connect(serial=None, *, port=9008)`，
`Device` 具备 `app_start / dump_hierarchy / screenshot / xpath / window_size`）。

## 5. 第 3 步：一次「查询 → 读价」的骨架

骨架已落盘：`_scratch/spike_mobile/android_flight_probe.py`。

```bash
python _scratch/spike_mobile/android_flight_probe.py --serial 127.0.0.1:5555 \
       --pkg com.yipiao --from SHA --to HAK --date 2026-11-16
```

它做四件事，每件都留证据：
1. 启动 App 并等首页（`app_start`）；
2. 打印当前 Activity 与 UI 层级，用来找「机票」入口；
3. 截图落盘（坐标定位靠它，不靠猜）；
4. **不做**任何猜测式点击——找不到控件就明确报「未定位到」，绝不伪造价格。

## 6. 第 4 步：接进项目（只有在 §3–§5 全绿之后才做）

新增 `crawlers/<name>.py`，实现与现有 5 渠道相同的契约：

```python
class XxxCrawler(BaseCrawler):
    def fetch(self, from_city, to_city, dates, ret_date="") -> list[FlightPrice]: ...
    def login_url(self) -> str: ...
```

要点：

- **不继承浏览器路径**：`browser()` 走 Playwright，这条路用 adb，别混。可照 `crawlers/tuniu.py`
  的「纯 httpx、不用 browser」先例；这里改成「纯 adb，不用 browser」。
- **探针要接项目既有账本**：`path_reset()/path_note()`（`crawlers/base.py:225/230`）记录
  「入口/路径级证据」，否则 UI 里看不到这条通路为什么成功/失败。
- **诚实状态**：App 里的「查不到航班」「网络异常」弹窗**不是**「无票」证据（对应 r398–r404
  的整改口径）——必须区分 `门拒 / 解析失败 / 真空结果`。
- **注册点**（照现有 5 渠道，全部是硬编码元组）：
  `crawlers/__init__.py:9` REGISTRY、`core/pacing.py:27` PLATFORMS、`core/health.py:17`、
  `core/channel_links.py:13` PLATS + `:57` ENTRY、`core/special_radar.py:38`、
  `webui.py` 多处 `PLATS/_LOGIN_PLATS/_WATCH_PLATS`、
  `tests/test_channel_links.py:14`（断言恰好 20 格，加渠道必红，需同改）。
- **依赖体积**（实测本机）：`uiautomator2` 6.2 MB + `adbutils` 6.8 MB = **13 MB**（比此前估的 +24MB 更小，
  因为不再单独打包 platform-tools——`adbutils` 自带 6.33 MB 的 `adb.exe`）。
  按 `ensure_chromium` 的模式做成**按需**（只有启用该渠道才 import），引擎本身不入包。

## 7. 无人值守要额外解决的三件事

1. **引擎必须常驻**：30 分钟一轮的调度要求引擎在扫描时刻在线。需把「引擎是否在线」
   做成一等状态（而不是等 fetch 超时）。
2. **解锁与前台**：模拟器锁屏/切后台会导致 UI 树为空。每轮开始要有
   `wake`/`app_start` 的幂等前置。
3. **缓存陈旧**：App 会缓存上次查询结果。必须校验结果里的日期/航线与本次请求一致，
   否则会把缓存当实时价（这属于项目里最忌讳的「账本说错状态」）。

## 8. 验收标准（B 算不算做成）

- [ ] `android_bridge.py` 能列出设备，且 `abilist` 含 32 位 ARM；
- [ ] 两个包 `pm list packages` 可见，且 `--install` 报 Success；
- [ ] `u2.connect(...)` 成功，`dump_hierarchy()` 返回非空；
- [ ] 手工在模拟器里完成一次「SHA→HAK→某日」查询，能看到真实航班列表（截图留证）；
- [ ] 骨架脚本能读到 ≥1 条含航班号的记录，且日期与请求一致；
- [ ] 单次耗时实测记录（预期分钟级）；
- [ ] 连续跑 3 轮不崩，第 3 轮结果与第 1 轮不是同一份缓存。

## 9. 明确的止损点

出现以下任一情况，就该停而不是继续加参数/加等待：
- 引擎装不上或 `abilist` 没有 32 位 ARM → 换 C（MuMu）或 D（云手机）；
- 能装能连，但机票页需要登录且登录有强风控 → 回到 `docs/CAPTCHA_SOLUTION.md` 的人工接管边界，不做破解；
- UI 每次都变、元素定位靠坐标硬编码 → 维护成本高于收益时改用 D 的固定镜像，或放弃该渠道。
