# -*- coding: utf-8 -*-
"""r1063 T290：守卫 —— 全库禁止 `x.lstrip("./")` 这类"剥点号"的归一化。

今晚这条写了三次同类错误（都静默失效，防护形同虚设）：

* `core/update.py::_skip` —— `.git/config` 被剥成 `git/config`，升级会覆盖用户仓库；
* `tools/verify_release_assets.py::_forbidden` —— `.env`/`.git/` 剥成 `env`/`git/`，
  发布包里带密钥或仓库历史也不报错。

`str.lstrip("./")` 会剥掉开头**所有** `.` 与 `/`，所以任何"保护以点开关的隐藏
文件/目录"的逻辑都会静默失效。

本门禁用 **AST** 扫真实代码（注释与 docstring 里的说明不算），
一旦有人再写就红。正确写法：
```python
while rel.startswith("./"): rel = rel[2:]
rel = rel.lstrip("/")      # 只剥斜杠，不剥点
```
"""
import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("core/*.py", "crawlers/*.py", "tools/*.py", "scripts/*.py",
        "*.py")


def _strip_calls(tree):
    """产出 (行号, 参数字符串)：所有 `.lstrip(...)` / `.strip(...)` 调用。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute):
            continue
        if fn.attr not in ("lstrip", "strip", "rstrip"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield node.lineno, fn.attr, arg.value


def test_no_dot_stripping_normalisation():
    bad = []
    for pat in SCAN:
        for path in glob.glob(os.path.join(ROOT, pat)):
            if os.sep + "_scratch" + os.sep in path:
                continue
            try:
                src = open(path, encoding="utf-8").read()
                tree = ast.parse(src)
            except Exception:
                continue
            for lineno, meth, chars in _strip_calls(tree):
                # 危险特征：参数里含 "./" 或以 "." 开头（会剥掉 .git/.env 的点）
                if "./" in chars or (chars.startswith(".") and "/" in chars):
                    bad.append("%s:%d  .%s(%r)"
                               % (os.path.relpath(path, ROOT), lineno,
                                  meth, chars))
    assert not bad, ("禁止用 lstrip/strip 剥 './'（会静默破坏 .git/.env 等保护）；"
                     "改用 while startswith('./') 循环：\n  " + "\n  ".join(bad))


def test_guard_detects_the_pattern():
    """负控：守卫自己必须能识别这种写法（否则门禁是摆设）。"""
    src = ("import os\n"
           "def f(p):\n"
           "    return p.lstrip('./')\n")
    found = list(_strip_calls(ast.parse(src)))
    assert found and found[0][2] == "./", found
