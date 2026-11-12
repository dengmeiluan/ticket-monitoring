# packages/apks/ —— 自备的 App 安装包

把 5 个目标 App 的 **APK** 放进这个目录，`python scripts/setup_device.py --apply`
会自动逐个 `pm install -r -g`；没有就跳过并提示还缺哪些 App。

**仓库不分发第三方 APK**（版权与分发合规，且各渠道 APK 频繁更新）。
请从**官方应用商店或官网**获取，再用包名核对：

| 文件名（随意，但建议按时） | 包名 | App |
|---|---|---|
| `ctrip.apk` | `ctrip.android.view` | 携程 |
| `fliggy.apk` | `com.taobao.trip` | 飞猪 |
| `qunar.apk` | `com.Qunar` | 去哪儿 |
| `tongcheng.apk` | `com.tongcheng.android` | 同程 |
| `zhixing.apk` | `cn.suanya.zhixing` | 智行 |

只装你要用的那几家也可以——`setup_device.py` 会如实报告缺哪些，不会假装装齐。

**文件名有实际作用**：`setup_device.py` 按文件名里的关键词（`ctrip` / `fliggy` /
`qunar` / `tongcheng` / `zhixing`，中文名也行）判断这个 APK 属于哪个 App，
**已装的直接跳过**（省掉每次全量重装的等待）。文件名认不出时会照装，但会标注
「未复核包名」。所以建议按上表命名。

> `.apk` 已被 `.gitignore` 忽略，不会误入库。
> 地址与校验和相关说明见 [`docs/DEVICE_PACKAGES.md`](../../docs/DEVICE_PACKAGES.md)。
