# 升级与更新（2026-11-09 起内置）

> 结论先说：**升级不需要卸载重装**。三条命令，`user_data/ data/ logs/ debug/`
> 和 **`config.yaml` 一律不会被覆盖**（升级不碰你的航线、心理线、钉钉配置与登录态）。

## 一、检查有没有新版本

```bash
python -m core.update --check          # 默认就查（结果缓存 6 小时）
python -m core.update --check --force  # 忽略缓存强制查
```

面板也会提示：有更新时「渠道健康」页顶部多一行
`✦ 有新构建 vX.Y.Z（原因）· 升级：…`，点它打开 GitHub 发布页。

Web 接口（只读）：

```
GET /api/update/check
→ {"ok":true, "local":"1.6.0", "latest":"v1.6.0", "has_update":false,
   "reason":"已是最新", "commit_source":"git"}
```

## 二、下载与升级

```bash
python -m core.update --download   # 下 zip 到 user_data/update/<tag>.zip（不动现有文件）
python -m core.update --apply      # 解包 → 备份 → 覆盖；失败自动回滚
# 然后重启程序
```

`--apply` 的行为（写死在代码里，请勿"优化"掉）：

1. 只接受官方发布包（仓库 `dengmeiluan/ticket-monitoring`）；
2. **覆盖前先备份**到 `user_data/update/backup_<时间>/`，备份失败就中止；
3. 覆盖时**跳过** `user_data/ data/ logs/ debug/ config.yaml`；
4. 任何异常 → **自动回滚**并把备份路径写进返回值；
5. 完成后必须**重启进程**（Python 无法安全热替换已加载的模块）。

> 诚实说明：这里的"热更新"= **文件换好 + 一次重启**，不是不断电升级。
> 想要真·不停机需要双进程/B 目录切换，本项目不做（会引入状态双写风险）。

## 三、版本号是怎么回事（容易被误读）

本仓库是**滚动发布**：Release 的 `tag_name` 恒定是 `v1.0`，**真实版本与源码写在
Release 正文里**：

```
当前版本：1.6.0 · 源码 <当前 root commit> · <发布日期>（以 Release 正文为准）
```

所以 `core.update` 的判断规则是：

| 情形 | 判定 |
|---|---|
| 正文版本 > 本机 `__version__` | 有新版本 |
| 版本相同，且本机是**打包安装**（无 `.git`，靠 `BUILD_COMMIT`）且源码不同 | **有新构建**（滚动发布正常形态） |
| 版本相同，本机是**开发树**（有 `.git`） | 已是最新（开发树 HEAD 领先发布是常态，不按提交比） |

## 四、常见问题

**Q：更新会不会丢我的登录态？**
不会。登录态在 `user_data/<slot>/`，升级跳过该目录。

**Q：更新会不会改我的 config.yaml？**
不会。它在跳过列表里；要改请手动合并。

**Q：`--apply` 中途断电怎么办？**
备份在 `user_data/update/backup_<时间>/`，把它们按相对路径拷回项目目录即可恢复。
