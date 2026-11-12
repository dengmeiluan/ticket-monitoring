# v1.7.1 · 2026-11-14 · 修 #16：App 渠道开通脚本的必崩 bug + 开通引导

> 这一版只做一件事：把用户报的「app通道无法开启」修到底，并把「怎么开」写成能照着做的三步。

## 修了什么（issue #16）

`python scripts/setup_device.py` 在「adb 连不上、需要自动拉起模拟器」时**必崩**，
而且崩了两层：

1. `AttributeError: 'Namespace' object has no attribute 'mumu'`
   argparse 从未定义 `--mumu`，代码却用了它；
2. 修掉第 1 层后立刻露出第 2 层：`UnboundLocalError: ... 'time'`
   同一函数末尾有 `import time`，Python 因此把 `time` 当整个函数的局部名，
   而前面的 `time.sleep(5)` 先执行。

两处都在 `scripts/setup_device.py`，已修。

## 新增

- `--mumu`（MuMu 安装目录**或** `MuMuManager.exe` 均可，自动解析到 `nx_main\MuMuManager.exe`）
  与 `--vm`（多开实例序号）——装在非常规目录、多开实例不再是 0 号时不用改代码；
- adb 连不上时打印**四步核对**（实例在跑 / ADB 调试开 / adb 路径 / 端口），不再只说「重启试试」；
- `docs/APP_CHANNELS.md` 新增 **「开启 App 渠道（三步）」**：环境自检 →
  `setup_device.py --apply --reboot --enable-app-channels` → 配置页勾选，附 adb 四卡点与症状对照；
- `core.setup_check` 的提示从「想采就在 users[].platforms 里加上」换成**能直接粘的三条命令**；
- 门禁 `tests/test_local_import_shadowing.py`：AST 全仓扫描「函数内裸 import 遮蔽同名用法」
  （这类写法必然 `UnboundLocalError`）。全仓 1445 个 py 文件扫出 2 处，均已修；
- 门禁 `tests/test_r1886_app_channel_onboarding.py`：钉住引导里的可执行命令、手册小节与 `--mumu/--vm`。

## 其它

- Release 正文的「线上 8765 已完成对账」改为 `{{LIVE_STATUS}}` 占位符：本机控制台停用时不再写假话；
- 测试总数 9011（README 已同步）。
