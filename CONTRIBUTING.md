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

要求：Python 3.9+，Windows（打包发行面向 Windows；Linux 跑测试/控制台亦可）。

## 提交前必须全绿

```bash
python tests/test_core_units.py   # 纯函数单测
python tests/test_alert_path.py   # 推送链路离线演练
python docs/uitest.py             # 全功能 UI 自检（Playwright，任何 JS 报错即失败）
python -m py_compile main.py webui.py report.py wizard.py core/*.py crawlers/*.py
```

## TDD 纪律（Iron Law）

- **bug 先写复现测试，看它红，再修到绿**——没有复现测试的修复不接受。
- 新功能测试先行；重构前后测试必须同绿。
- 测试要离线可跑（不依赖网络/真实渠道/真实 webhook）。

## 代码约定

- 改代码一律用编辑器/工具直改文件，**不要经 shell 内联/heredoc 传代码**（反斜杠折叠坑，见 LESSONS 三.1）。
- 控制台是 `webui.py` 里的单文件内嵌 SPA（`PAGE` 字符串），无构建链、无外部 CDN——保持这个形态。内嵌 JS 里需要控制字符时用 `String.fromCharCode(10)`，**不要写 `\n` 转义**。
- 钉钉推送文案有三条实锤红线（LESSONS 八）：不用表格、不吞尖括号、PC 端不认单 `\n`（段落级 `\n\n`）、不用 U+2026「…」。
- 适配渠道时遵循现有 crawlers 结构：`safe_fetch` 统一入口，异常自吞并记日志，健康时间线靠日志关键字归并。
- 配置改动必须热加载：扫描期读 `rt["cfg"]`（单一事实源），不要让闭包捕获启动快照。

## 提交规范

- 一个 PR 一件事，commit message 用一行中文说清「改了什么、为什么」。
- 涉及 UI 的改动请附截图（亮/暗各一张），并跑过 `docs/uitest.py`。
- 涉及推送文案的改动：等自然轮验证，不要手动触发轰炸订阅者。

## 发布（维护者）

流程见 `release.ps1` 与 `HANDOFF.md` §7：回归测试 → 敏感信息扫描 → 打包 zip → 归零单根提交 + tag → GitHub Release + 资产上传 → 远端三件套终验（1 commit / 1 tag / 敏感零命中）。
