<!-- 提交前请确认以下三项已完成（详见 CONTRIBUTING.md） -->

## 改了什么 / 为什么

## 验证

- [ ] `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q` 全绿（**必须走 pytest**：直接 `python tests/xxx.py` 会静默跳过带 fixture 的用例，见 CONTRIBUTING.md）
- [ ] `python docs/uitest.py` 全绿（涉 UI 时）
- [ ] 涉推送文案：已比对钉钉 PC + 手机双端排版（或用 👁 预览比对）
- [ ] 涉配置：改动项保存即热生效（无需重启）

## 截图（涉 UI 必附，亮/暗各一张）
