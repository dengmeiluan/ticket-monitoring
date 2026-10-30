# MuMu 路线验收结果（2026-10-27 实测）

> 前提：接受**一次人工安装**（MuMu 安装向导），之后全部由脚本驱动。
> 判据不变：装完之后不允许再要求任何人工点击。

## 结论

| 项 | 结果 |
| --- | --- |
| MuMu 安装 | 一次人工向导完成，装到 `D:\Program Files\Netease\MuMu`；**装完并建实例、再装两个 App 后实测 9.3 GB**（安装器本体约 3.6 GB，实例镜像再占约一倍） |
| 引擎与 Hyper-V 共存 | ✅ `hyperv_enabled: true`，实例正常运行（VBS/HVCI 开启下） |
| adb 免人工 | ✅ **装完即通**：`adb connect 127.0.0.1:16384` → `device`，全程未点任何界面 |
| 实例控制可脚本 | ✅ `MuMuManager.exe control -v 0 launch/shutdown`、`info -v 0`、`setting -v 0` |
| **美团** | ✅ **装成功并启动**（arm64 分片，见下） |
| **智行** | ⚠️ 当次未装成（当时取的包只有 32 位 armeabi，实例无 `armeabi`）——**该结论已被同日 `MOBILE_ZHIXING_A12_RESULT.md` 推翻**：应用宝同页第二个链接是 `arm64-v8a`（104.0 MB），装对即可 |

## 1. 关键实测数据

实例（`MuMuManager.exe info -v 0`）：

```
android_version = 15.0      adb 127.0.0.1:16384
is_android_started = true   hyperv_enabled = true
player_state = start_finished
```

ABI（`getprop`）：

| 属性 | 值 |
| --- | --- |
| `ro.product.cpu.abilist` | `x86_64,arm64-v8a,x86` |
| `ro.product.cpu.abilist32` | **`x86`**（无 32 位 ARM） |
| `ro.dalvik.vm.native.bridge` | **`libnb.so`**（ARM 翻译器真实存在） |
| `ro.build.version.sdk` | 35 |

**即：MuMu 有 ARM 翻译，但只翻 64 位 ARM；32 位 armeabi 不支持。**

## 2. 为什么美团能装、智行当时装不上（**智行部分已被推翻**）

| 渠道 | APK 形态 | 结果 |
| --- | --- | --- |
| 美团 12.63.474 | XAPK：`base` + **`config.arm64_v8a.apk`** | ✅ `install-multiple` → Success |
| 智行 10.26.0 | 单一 APK，`lib/` 仅 `armeabi` | ❌ `INSTALL_FAILED_NO_MATCHING_ABIS (res=-113)` |

> **上表是当次（2026-10-27 早些时候）抽样到的包**；结论「智行装不上」**已被同日
> `MOBILE_ZHIXING_A12_RESULT.md` 推翻**：应用宝同页第二个链接是 `arm64-v8a`（104.0 MB），
> 装对即可，列表可读。这里保留的是"为什么会失败"的机制解释（实例无 `armeabi` 翻译），
> 不是"智行无法使用"的结论。

安装命令（可复现）：

```bash
adb -s 127.0.0.1:16384 install-multiple -r \
  com.sankuai.meituan.apk config.arm64_v8a.apk config.xxhdpi.apk config.zh.apk
```

美团启动后前台 Activity 实测：

```
com.sankuai.meituan/com.meituan.android.pt.homepage.activity.MainActivity
```

`uiautomator dump` 能读出真实 UI（首屏是权限弹窗：`温馨提示 / 同意 / 不同意`），
说明 uiautomator2 可以接管。

## 3. 可复现脚本

`_scratch/spike_mobile/mumu_drive.py`（已跑通）：

```bash
python _scratch/spike_mobile/mumu_drive.py --check              # 实例/ABI/装机状态
python _scratch/spike_mobile/mumu_drive.py --install-meituan    # 装 arm64 分片
python _scratch/spike_mobile/mumu_drive.py --open com.sankuai.meituan
```

`--check` 实测输出：

```
android=15.0 started=True adb=127.0.0.1:16384 hyperv=True
ro.product.cpu.abilist     = x86_64,arm64-v8a,x86
ro.product.cpu.abilist32   = x86
ro.dalvik.vm.native.bridge = libnb.so
美团   com.sankuai.meituan    已安装
智行   com.yipiao             未安装
```

## 4. 仍未解决的问题

1. **（已过时，见文末更正）当次以为「智行没有 arm64 版本」**：当时应用宝首屏第一个链接与 APKPure 都只提供 `armeabi`。
   → **该前提当日即被推翻**：应用宝同页第二个链接是 `arm64-v8a`（104.0 MB，见
   `MOBILE_ZHIXING_A12_RESULT.md`）。所以下面这段「需要 32 位模拟器」的排查**不再是缺口**，
   保留仅为记录当时的排查路径。原文如下：
   要跑智行，需要「支持 32 位 ARM 的模拟器」。MuMu 需装 **Android 12 引擎**才有
   32 位支持的可能，而 `MuMuManager main engine install -ver 12` 持续返回
   `-201 player not running`（主程序在跑、实例在跑都已试过）。目前只能靠 GUI 里
   手动装 Android 12 引擎——这一步仍属「一次性人工」，尚未验证 Android 12 实例的
   `abilist32` 是否含 `armeabi`。
2. **美团首屏是权限弹窗**，需要一次性点「同意」（可在脚本里点一次并记忆状态，
   不属于每次采集的人工负担）。
3. 美团 App 内机票入口是否强制登录，未验证。
4. 单次查询耗时、连续运行的稳定性、UI 改版风险，均未验证。

## 5. 对第三方框架（u-wlkjyy/mumu-python-api）的评估

- 它是对 `MuMuManager.exe` 的 Python `subprocess` 封装（111 stars，2026-03 仍在更新，
  **仓库无 LICENSE**），提供 `power.start/shutdown`、`app.install`、`window.hidden`、
  `screen.screenshot`、`permission.root` 等便利方法，并自动发现
  `D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe`。
- **它不改变 ABI 事实**：智行能不能装取决于模拟器引擎，与封装层无关。
- 可用之处：省掉路径发现与命令拼装。风险：无许可证（不能直接并入分发物），
  且封装层会领先于官方 CLI 演进。建议**自己按需封装**（`mumu_drive.py` 已示范），
  而不是引入该依赖。

## 6. 一句话总结

**MuMu 这条路「装完之后全自动」成立：adb 免点界面、实例可命令行控制、美团已实测跑通。
智行当时被判为「只有 32 位包」，但**当日已被推翻**——装 `arm64-v8a` 包（104.0 MB）即可跑通，
详见 `MOBILE_ZHIXING_A12_RESULT.md`。**
