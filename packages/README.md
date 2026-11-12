# packages/ —— 设备侧安装包目录

这个目录里的二进制**不入库**（见 `.gitignore`）。
**完整的地址清单见 [`docs/DEVICE_PACKAGES.md`](../docs/DEVICE_PACKAGES.md)**——
模块包版本、下载地址、大小、SHA256、NDK、MuMu、App 包名都在那张表里，与代码同源。

## 需要放什么

| 文件 | 谁提供 | 说明 |
|---|---|---|
| `NeoZygisk.zip` | **自动下载** | `python scripts/fetch_packages.py` 按钉死版本+SHA256 拉取（v2.4） |
| `Shamiko.zip` | **自动下载** | 同上（v1.2.5） |
| `mumu_cloak.zip` | **自动构建** | `scripts/build_mumu_cloak.py` 用 NDK 编译本项目 native 模块 |
| `apks/*.apk` | **你自备** | 携程 / 飞猪 / 去哪儿 / 同程 / 智行。**仓库不分发第三方 APK** |

## 一键准备

```powershell
python scripts/fetch_packages.py --with-cloak    # 下载 + 构建（不含 APK）
python scripts/setup_device.py --apply --reboot  # 装到设备上并体检
```

`setup_device.py` 会把 `apks/` 里已有的 APK 自动 `pm install -r -g`；
没有就跳过并提示缺哪些 App —— **不会假装装好了**。

## 为什么钉死模块版本

Zygisk 实现与 root 隐藏模块的兼容性很脆：实测 ZygiskNext v1.5.2、
ReZygisk v1.0.0 在 MuMu + Magisk 31.1 上都注入失败，只有 NeoZygisk v2.4 成功。
所以 `fetch_packages.py` 固定版本而不是永远取 latest——避免"昨天能跑、
今天一更新就崩"。换版本请同时改 `PACKAGES` 里的 `url` / `sha256` / `size`
**和** `docs/DEVICE_PACKAGES.md`（有测试钉住两者一致）。
