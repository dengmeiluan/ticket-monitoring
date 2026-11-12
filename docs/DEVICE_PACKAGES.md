# 设备侧常规包地址（Android / MuMu / App 渠道）

本文件是**设备侧所有外部依赖的地址清单**，与代码同源维护：
`scripts/fetch_packages.py` 里 `PACKAGES` 的 `url` / `sha256` / `size` 必须与本表一致
（有测试钉住，见 `tests/test_r1071_device_packages_doc.py`）。

## 目录约定

| 路径 | 内容 | 是否入库 |
|---|---|---|
| `packages/` | 设备侧模块包与 APK 的落地目录（`setup_device.py` 默认读这里） | 目录里的 `README.md` 入库；`*.zip` 不入库 |
| `packages/apks/` | 你自备的 App 安装包（`*.apk`） | 不入库 |
| `build/` | 编译产物（`mumu_cloak.zip`、`x86_64.so` 等） | 不入库 |

路径可用参数覆盖：`fetch_packages.py --dest <目录>`、`setup_device.py --packages <目录>`。

## 模块包（自动下载，版本与校验和钉死）

| 文件 | 版本 | 大小 | SHA256 | 下载地址 |
|---|---|---|---|---|
| `NeoZygisk.zip` | v2.4（289-release） | 2401208 | `93a1425c67bb89f58a0dcb9fc823ec93f6472214f221e667a70b67c6a6e061a1` | `https://github.com/JingMatrix/NeoZygisk/releases/download/v2.4/NeoZygisk-v2.4-289-release.zip` |
| `Shamiko.zip` | v1.2.5（414-release） | 6523936 | `308d31b2f52a80e49eb58f46bc4c764a6588a79e4b8d101b44860832023f88b4` | `https://github.com/LSPosed/LSPosed.github.io/releases/download/shamiko-414/Shamiko-v1.2.5-414-release.zip` |

- **NeoZygisk**：Zygisk 实现本身（库在 `lib/<abi>/libzygisk*.so`，注意它**不是**普通 Zygisk 模块）。
  项目页：`https://github.com/JingMatrix/NeoZygisk`
- **Shamiko**：对指定 App 隐藏 root（库在 `zygisk/<abi>.so`）。发布页：`https://github.com/LSPosed/LSPosed.github.io/releases`

> 为什么钉死版本：Zygisk 实现与 root 隐藏模块的兼容性很脆。本会话实测
> **ZygiskNext v1.5.2、ReZygisk v1.0.0 在本机（MuMu + Magisk 31.1）均注入失败**，
> 只有 NeoZygisk v2.4 成功。固定版本可避免"昨天能跑、今天一更新就崩"。
>
> 要换版本：同时改 `PACKAGES` 里的 `url` / `sha256` / `size` **和**本表，然后跑
> `python scripts/fetch_packages.py --force --verify`。

## 自建模块（本地构建，无需下载）

| 文件 | 生成方式 |
|---|---|
| `mumu_cloak.zip` | `python scripts/build_mumu_cloak.py`（源码在 `native/mumu_cloak/`，需 Android NDK） |

## Magisk（需先装，装完才跑 `--apply`）

- 官方发布页：`https://github.com/topjohnwu/Magisk/releases`
- 本机在用的是 **Magisk v31.1**（APK 由 MuMu 的一键安装脚本提供，`Magisk-v31.1.apk`，
  SHA256 `89cefac0a318afa39fb3880c45c87b036c05bc1ebf02a7a715b7f8d7c26ac6e7`）；
  该 APK 的**直链地址本会话未验证过**，只列官方发布页，不臆造具体 URL。
- 安装与踩坑（含"Magisk 只能自己装、MuMu 自带 root 要关"）：见 `docs/DEVICE_IDENTITY_PLAYBOOK.md`。

## Android NDK（只在需要重新编译 `mumu_cloak` 时用）

| 项 | 值 |
|---|---|
| 版本 | r27c |
| 地址 | `https://dl.google.com/android/repository/android-ndk-r27c-windows.zip` |
| 大小 | 745 MB（本会话 `HEAD` 实测 200 OK） |
| 解压后 | 任意位置，用 `python scripts/build_mumu_cloak.py --ndk <NDK 根目录>` 指定 |
| 约定位置 | `D:\tm_local_tools\_tools\android-ndk-r27c`（本机；不随仓库分发） |

也可从 `https://developer.android.com/ndk/downloads` 选其它 r27 版本；
脚本会在常见位置自动探测（`scripts/build_mumu_cloak.py` 的 `CANDIDATE_NDK`）。

## MuMu 模拟器

- 官网：`https://mumu.163.com/`（代码里 `core/android/bootstrap.py` 的 `MUMU_DOWNLOAD_HINT` 同源）
- 要求：MuMu 12 / Android 15 实例、开 VT、磁盘约 15 GB
- 安装后把 MuMu 自带 root 关掉（`root_permission=false`），root 由 Magisk 提供

## App 安装包（**仓库不分发**，请自备）

放进 `packages/apks/`，`setup_device.py --apply` 会自动 `pm install -r -g`。
请从**官方应用商店或官网**获取，并用下面的包名核对装的是不是对的 App：

| 包名 | App |
|---|---|
| `ctrip.android.view` | 携程 |
| `com.taobao.trip` | 飞猪 |
| `com.Qunar` | 去哪儿 |
| `com.tongcheng.android` | 同程 |
| `cn.suanya.zhixing` | 智行 |

> 不提供第三方 APK 直链：一是版权/分发合规，二是各渠道 APK 会随时更新，
> 直链过期反而误导。用包名核对是最稳的做法。

## 怎么核对

```powershell
python scripts/fetch_packages.py --list     # 打印本表里的包：大小 + 地址 + 用途
python scripts/fetch_packages.py --verify   # 校验 packages/ 里已有的包（大小 + SHA256 + 结构）
python scripts/device_hardening.py --check  # 13 项设备体检
```
