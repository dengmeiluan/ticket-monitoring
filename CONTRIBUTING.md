# 贡献指南

感谢关注 ticket-monitoring！这是一个克制而专注的项目：**自托管、零外部服务依赖、单文件内嵌控制台**。提交贡献前请先读完本页，能省掉一轮返工。

## 环境准备

```bash
git clone https://github.com/dengmeiluan/ticket-monitoring.git
cd ticket-monitoring
pip install -r requirements.txt
playwright install chromium
python webui.py --demo   # 零配置跑通控制台
```

要求：Python **3.10+**，Windows（打包发行面向 Windows；Linux 跑测试/控制台亦可）。

> 为什么不是 3.9：代码里有 `x: float | None` 这类 PEP 604 注解（`core/radar_alerts.py:25`、
> `crawlers/ctrip.py:1010`、`crawlers/tongcheng.py:1051`），而 dataclass 字段注解在**运行时**求值，
> 3.9 会直接抛 `TypeError`。CI 与打包统一用 3.11。

## 提交前必须全绿

```bash
python tools/test_all.py                     # 并发全量（默认）：语法检查 + pytest（xdist 按文件）+ UI 自检（按 profile 分片）同跑
python tools/test_all.py --workers 12        # 物理核多时调大；每个 worker 会自起 demo + Chromium
python tools/test_all.py --ui-shards 1       # UI 自检退回单进程（排查分片状态/对照时用）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q   # 串行口径（CI 同款：排查并发干扰/单进程复现时用）
PYTHONIOENCODING=utf-8 python docs/uitest.py   # 单跑全功能 UI 自检（Playwright，任何 JS 报错即失败）
python -m py_compile main.py webui.py report.py wizard.py core/*.py crawlers/*.py
```

> **并发全量依赖 pytest-xdist**：pip install pytest-xdist。装不进系统 site-packages（无管理员权限）时，
> 跑一次 python tools/test_all.py --bootstrap-deps，会把 xdist 装到仓库内 _scratch/testdeps/（已 gitignore），
> 之后自动复用。并发只改变「在哪个进程跑」，不改用例集合：整文件分配靠 --dist loadfile，模块级 fixture 与跨类状态不拆 worker。
> 跑测前后脚本比对源码哈希——期间别处改写了 webui.py 等源码会以退出码 3 作废本次结果（并行会话假红/假绿的根治）。
> 同一台机器**不要同时跑两轮门禁**：两轮会抢 CPU（8 worker 实测被拖到 12 worker 更慢），
> 并且共用 docs/uitest_result.txt 与 profile 重算。不同分支的验证排队跑。

> **`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 不是可选项**（Windows 实测）：本机第三方 pytest 插件（如 `langsmith`）
> 依赖不全时，pytest 在**加载插件阶段**就崩（`ModuleNotFoundError: No module named 'requests_toolbelt'`），一行用例都跑不到。
> 单测里有少量用例带 pytest fixture（monkeypatch/tmp_path），直接 `python tests/test_core_units.py` 直跑会静默跳过它们——一律走 pytest 才是完整口径（CI 同此命令）。
>
> **`PYTHONIOENCODING=utf-8` 对这两条命令都不是硬要求**（2026-10-27 逐一实测）：
> - pytest 在 GBK 控制台下会把 `❌` 转义成 `\u274c` 照常输出，不崩；
> - `docs/uitest.py` 在 `main()` 开头就 `sys.stdout.reconfigure(errors="replace")`，打不出的 `✓/✗` 落成 `?`，判定不受影响
>   （脚本第 60 行的注释记着这件事的来历）。
>
> 上面仍带着它，是因为 **CI 打包步骤与 `docs/release_align_check.py` 都设了这个变量**——本地照带才能复现它们的结果；
> 而**自己新写的脚本**直接 `print("✅ …")` 才会抛 `UnicodeEncodeError: 'gbk' codec can't encode character`（实测），
> 写这类脚本时抄 CI 的写法：`sys.stdout.reconfigure(errors="replace")`，或运行时带 `PYTHONIOENCODING=utf-8`。

## TDD 纪律（Iron Law）

- **bug 先写复现测试，看它红，再修到绿**——没有复现测试的修复不接受。
- 新功能测试先行；重构前后测试必须同绿。
- 测试要离线可跑（不依赖网络/真实渠道/真实 webhook）。

## 代码约定

- 改代码一律用编辑器/工具直改文件，**不要经 shell 内联/heredoc 传代码**（反斜杠折叠坑，见 LESSONS 三.1）。
- 控制台是 `webui.py` 里的单文件内嵌 SPA（`PAGE` 字符串），无构建链、无外部 CDN——保持这个形态。内嵌 JS 里需要控制字符时用 `String.fromCharCode(10)`，**不要写 `\n` 转义**。
- 钉钉推送文案有三条实锤红线（LESSONS 八）：不用表格、不吞尖括号、PC 端不认单 `\n`（段落级 `\n\n`）、不用 U+2026「…」。
- 适配渠道时遵循现有 crawlers 结构：`safe_fetch` 统一入口，异常自吞并记日志，健康时间线靠日志关键字归并。
- 文本文件不得混用 CRLF/LF（混合 EOL 是 bug，会让 `git diff` 静默失真）。批量改写文档前先 `git ls-files --eol <file>` 确认原形态，写出时跟着走；`tests/test_eol_consistency.py` 会拦住混排。
- 配置改动必须热加载：扫描期读 `rt["cfg"]`（单一事实源），不要让闭包捕获启动快照。

## 提交规范

- 一个 PR 一件事，commit message 用一行中文说清「改了什么、为什么」。
- 涉及 UI 的改动请附截图（亮/暗各一张），并跑过 `docs/uitest.py`。
- 涉及推送文案的改动：等自然轮验证，不要手动触发轰炸订阅者。

## 发布（维护者）

发布由维护者按仓库既定流程执行：回归测试全绿 → 敏感信息扫描 → `git worktree` 干净提交树 PyInstaller 打包（抽 exe 实跑 `--version` 验内嵌版本）→ 归零单根提交 + tag → GitHub Release + 资产上传 → 远端终验（1 commit / 1 tag / 敏感零命中）。贡献者无需关心本节，PR 合入后由维护者随下一版发布。
