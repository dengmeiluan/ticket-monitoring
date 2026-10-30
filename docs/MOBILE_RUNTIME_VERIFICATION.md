# Android 运行时可行性验证记录（2026-10-27 实测）

> 判据由用户指定：**连安装都必须脚本化**——不能要求使用者（或 AI）去点界面。
> 任何"打开设置 → 连点 7 次 → 勾选"的步骤，一律判该方案不合格。

## 结论速览

| 方案 | 静默安装 | ADB 是否需要点界面 | 能否跑目标 App | 判定 |
| --- | --- | --- | --- | --- |
| 应用宝电脑版（Androws） | 有 GUI 安装向导 | **需要**（连点「性能」7 次） | 未验证（卡在 ADB） | ❌ 不符合判据 |
| **MuMu Android 15 实例** | `/S` 无效，需一次向导 | **不需要**（装完即通） | ✅ **美团（XAPK arm64 分片）+ 智行（cn.suanya.zhixing 64 位包）均跑通** | ✅ **两个渠道都可用** |
| MuMu Android 12 实例 | 同上 | **不需要** | 仅用于绕 32 位包限制 | ⚠️ **已无必要，可删** |
| Google AOSP x86_64 + sdkmanager | 可全脚本 | **不需要**（adb 直连） | ❌ 镜像内无 ARM 翻译器 | ❌ 无法运行本项目两个 App |

> **2026-10-27 最终更正（重要）**：
> ③ 之前「智行只有 32 位包」的结论**是取样错误**——应用宝同一页面有两个 APK 链接，
> 第一个是 `armeabi`（88MB），**第二个是 `arm64-v8a`（104MB，65 个 ELF64 .so）**。
> 装 64 位版后智行在 **Android 15 实例**上 `primaryCpuAbi=arm64-v8a`，
> **无任何 32 位提示**，机票列表完整渲染并可被 uiautomator2 读出
> （日历价 341/342/350/371/374/380/392/437 + 航班号 KN5978/MU5185/HO1253 等）。
> **Android 12 实例已无必要**（那只是为绕 32 位限制而建）。
> 未登录时单班票价被遮为 `¥3??`，仅日历的最低价可读。
> 详见 `docs/MOBILE_ZHIXING_A12_RESULT.md`（已全面改写）。

## 1. 应用宝电脑版：ADB 只能靠点界面开启

实测过程与证据：

- 安装包 `pcyyb__installer.exe` 仅 **6.6 MB**（启动器），实测安装到
  `D:\Program Files\Tencent\Androws`，最终占用 **3.5 GB**（其中 `Image/` 2.1 GB：
  `system.vhd` 1.7 GB + `data.vhd` 267 MB），另有 `%APPDATA%\Tencent\Androws` **141 MB**。
- 引擎版本 `5.10.7600.6676`，自带 `adb.exe`（1.0.41 / 33.0.2）。
- **ADB 默认关闭**：安装后 `adb connect 127.0.0.1:5555` → `10061 目标计算机积极拒绝`。
- 官方开关方式（`sj.qq.com/faq/3878`）：市场界面 → 设置 → 对「性能」**连点 7 次** →
  勾选开发者模式。**没有命令行/注册表/配置文件等价开关**——已核对：
  - `Androws.json` / `Config.json` / `deviceConfig.json` 中无 adb 字段；
  - `%APPDATA%\Tencent\Androws\db\Configs.db` 的 18 条配置项无 debug/adb 键；
  - 引擎走 **vsock** 私协议（`vsock_devices` / `vsock_proxy` 等符号）与 VM 通信。
- 曾观察到 `0.0.0.0:5555` 短暂监听（引擎主进程 `Androws.exe`），但 `adb` 始终
  `offline`，且引擎重启后端口消失 → 该端口非可用的调试通道。

**判定：不合格。** 使用者不可能被要求手动点 7 次。

## 2. MuMu 12：`/S` 不成立

- 官网下载 API：`https://mumu.nie.netease.com/endpoint/dl/win?channel=<ch>` 返回 6.1 MB
  的 **7-Zip SFX 下载器**（`;!@Install@!UTF-8!` 配置块，`Title="nemu-downloader"`），
  不是完整安装包。版本信息取自 `api.mumu.nie.netease.com/endpoint/website/download_version_info`
  （当前 `6.8.8`，engine `NX`）。
- 实测 `MuMu_installer.exe /S`：进程 3 分钟无进展，日志出现
  `StatisticsTool::recordLifeCycle ... ToFastInstallPage` —— **跳到了安装向导页**，
  说明 `/S` 未被识别。随后进程已终止，系统未安装（`Program Files\Netease` 不存在）。
- 它的可脚本化优势在**运行时**：`MuMuManager.exe` 提供 `control -v 0 launch|shutdown|
  hide_window`、`control -v 0 app install -apk x.apk`、`adb -v 0 -c "shell ..."`、
  `info -v 0`（含 `adb_port` / `is_android_started`）。

**判定：安装环节不满足静默判据**，但运行/控制环节是全部方案里最可脚本化的。

## 3. Google 官方模拟器：静默没问题，但跑不了这两个 App

这条曾被认为最有希望（全命令行 + 无需点界面），实测被否证：

- `sdkmanager` 仓库里确有 x86_64 镜像，例如
  `system-images;android-33;google_apis;x86_64`（**1629 MB**）、
  `...;google_apis_playstore;x86_64`（1593 MB）、`...;default;x86_64`（662 MB）。
- 下载 `x86_64-33_r17.zip`（1.70 GB）后解包：`system.img` **8203 MB**。
- **全量扫描 8203 MB**（不是抽样，扫完全部）：

  | 关键词 | 命中 |
  | --- | --- |
  | `libndk_translation` | **0** |
  | `libndk_translation.so` | **0** |
  | `libhoudini` | **0** |
  | `libnb.so` | **0** |
  | `ndk_translation` | **0** |
  | `ro.dalvik.vm.native.bridge` | 4（仅配置项，指向外部库） |
  | `arm64-v8a` | 16（目录名字符串，不是可执行翻译器） |

  即：镜像里有 **native bridge 的配置框架**，但**没有任何 ARM 翻译器实现**。
  这与 Google 官方说明一致：ARM 转译只在部分 Google APIs/Play 镜像、且需其专用组件，
  AOSP 默认镜像不含。
- 本项目两个 App 的 APK 都是 **armeabi（32 位 ARM，EABI5）only**，实测 `lib/` 只有
  `armeabi`，无 `x86`/`x86_64` → 在这种镜像上必然 `INSTALL_FAILED_NO_MATCHING_ABIS`。

**判定：不合格。** 静默是真的，但跑不了目标 App。

## 4. 由此得到的分层判据（可写进框架文档）

1. **APK 的 ABI 是第一道门**：先查 `lib/` 里有没有 `x86_64`/`x86`；只有 `armeabi` 就
   必须依赖 ARM 翻译。
2. **"支持 ARM 翻译"不能只看文档**：要看镜像里有没有 `libndk_translation.so` /
   `libnb.so` 等具体实现文件（本项目实测证明：官方 x86_64 镜像有框架无实现）。
3. **"能开 ADB"必须是可脚本的**：等价判据是「重启后无人工干预仍能 `adb connect` 成功」。
   应用宝在这个判据上直接出局。
4. **安装环节的静默性要单独验**：`/S`、`-Silent`、`/quiet` 不能假设有效——MuMu 实测无效。

## 5. 目前仍然成立的选择

- **A（美团日历，纯 HTTP）**：零设备、零安装、已跑通。限制：仅国内、仅 61 天窗口、只有最低价。
- **C（MuMu 12）**：安装要一次人工（不合格于本次判据），但**安装之后**的
  `launch / app install / adb shell` 全部可脚本，是剩余方案里最接近"全自动"的。
- **D/E（云手机）**：adb 与实例生命周期都有官方 API，本地零安装；
  代价是租金（阿里云约 ¥65/月起）与合规风险。**这是唯一同时满足「本地零安装 + 可脚本」的路线。**

## 6. 一次性探针（可删）

- `_scratch/spike_mobile/check_sysimg.py`：解析 SDK 镜像仓库、列 ABI 与体积。
- `_scratch/spike_mobile/check_aosp_images.py`：早期版本（仓库结构不同，已被上者取代）。
- `_scratch/spike_mobile/find_yyb_installer.py`：从应用宝下载页挖安装包直链。
- `_scratch/spike_mobile/find_mumu_installer_pw.py`：抓 MuMu 下载 API。
- `_scratch/spike_mobile/android_bridge.py` / `android_flight_probe.py`：设备体检与采集骨架。
- `_scratch/mobile_paths/apk/`：ABI 取证用的安装包样本（2026-10-27 实测目录合计约 **768 MB**，含解包子目录）。当前留有的是**美团**（`.xapk` 170 MB + `_yyb.apk` 99 MB 及 arm64 分片）与**携程 yipiao**（80 + 79 MB）；**智行两个样本已不在目录里**，其 88.5/104.0 MB 与 ABI 结论见 `docs/MOBILE_ZHIXING_A12_RESULT.md`（需复现时按该文的两个下载链接重取）。
