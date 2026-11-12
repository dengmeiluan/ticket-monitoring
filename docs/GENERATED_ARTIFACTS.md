# 生成物与仓库边界（哪些入库、哪些必须留在本地）

> 2026-11-12 处理的一类反复出现的问题：**生成物被 git 跟踪**。它们的共同特征是
> 「跑一次就变」——一旦入库，每次运行都会产生无意义 diff，审阅者分不清哪些是
> 真改动；更糟的是两个人同时跑，会互相覆盖（实测 uitest 结果文件就撞过：
> 一会儿 689/690、一会儿 690/690）。
>
> 本文是唯一口径。`tests/test_generated_artifacts_policy.py` 按它逐条核对。

## 三类，边界清楚

### A. 生成物 —— **不入库**（`.gitignore` 覆盖）

| 路径 | 由谁生成 | 说明 |
|---|---|---|
| `docs/uitest_result.txt` | `python docs/uitest.py` / `tools/test_all.py` | UI 自检结果。**每次运行都变**，且并发跑会互相覆盖 |
| `uitest_*.js` `uitest_*.png` `uitest_v1554_result.json` | `docs/uitest.py` 失败留证 | 调试快照 |
| `.uitest.lock` | `docs/uitest.py` | 单实例锁 |
| `data/`（`prices.db`、`.heartbeat`、`notify/` …） | 运行期状态 | 含真实价格历史，属用户数据，绝不入库 |
| `logs/` `user_data/` `debug/` | 运行期 | 日志、登录态、失败留证 |
| `_scratch/` `dist_package/` `_build*/` `build/` `dist/` | 本地脚本与打包 | 一次性产物 |
| `*.pyc` `__pycache__/` | Python | 字节码 |

**规则**：A 类文件一旦发现被跟踪，就是 bug；门禁会报出具体路径。

### B. 生成物 —— **必须入库**（各有硬理由，逐个列明）

这几项也是"跑出来的"，但**仓库外的人或 CI 需要它**，不committed 就跑不起来。
它们属于"锁文件"性质：内容稳定、可审阅、由脚本重生成。

| 路径 | 生成方式 | 为什么必须入库 |
|---|---|---|
| `docs/site/index.html` | `python docs/demo_build.py` | 它就是 GitHub Pages 发布的静态站本体；不入库就没有在线演示 |
| `docs/screenshots/*.png` | `python docs/screenshot.py`（需先起 `webui.py --demo --port 8799`） | README/Release 引用的截图，缺一张就是坏链（`release_align_check` 会拦） |
| `tests/ci_durations.json` | `tools/ci_shard.py` 的 snapshot（CI 跑完 junit 后合并） | CI 分片按实测耗时均衡；不入库就只能均分，4 片负载差 1.25× 以上 |
| `docs/uitest_profile.json` | `tools/test_all.py --profile`（`UITEST_TRACE=1`） | UI 自检按实测权重切片；`tests/test_parallel_suite.py` 与 `test_r503` 直接读它 |

**规则**：B 类必须在 `git ls-files` 里，且必须能在本文查到「怎么重生成」。
新增 B 类条目要同时改本文与门禁的 allowlist。

### C. 真·源文件（不是生成物，别误删）

`docs/design/*.html`（设计稿）、`docs/assets/*.svg`（banner）、
`tests/fixtures/*`（采集/解析的固定样本）、`native/maps_cloak/config/*.json`（配置）。

## 怎么重生成 B 类

```bash
# 1) 演示站（同时刷新 build stamp）
python docs/demo_build.py

# 2) README 截图（先起演示实例，打完自动退出非零=有 JS 错误）
python webui.py --demo --port 8799 &
python docs/screenshot.py

# 3) CI 分片耗时快照（在 CI 上跑完 junit 后合并；本地补齐用）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --junitxml=_scratch/pytest.xml
python tools/ci_shard.py  # snapshot/plan 入口见 --help

# 4) UI 分片权重
UITEST_TRACE=1 python docs/uitest.py && python tools/test_all.py --profile
```

## 历史

- 2026-11-12：`docs/uitest_result.txt` 从「受跟踪的常态产物」改为 **A 类（不入库）**。
  起因：它是每次运行都变的产物，却因为历史原因留在索引里，导致
  `git status` 长期挂着一个永远脏的文件，也让"这版 UI 到底多少条过"变成靠猜。
  同时补了本文与门禁，避免下一个生成物再悄悄入库。
