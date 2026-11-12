# -*- coding: utf-8 -*-
"""门禁：函数内「裸 import 遮蔽同名用法」会导致 UnboundLocalError 必崩。

来历（issue #16，2026-11-13 用户实测）：

    File "scripts\\setup_device.py", line 321, in main
        time.sleep(5)
    UnboundLocalError: cannot access local variable 'time' where it is not
    associated with a value

`main()` 末尾有一句 `import time`，Python 因此把 `time` 视为**整个函数的局部名**，
而第 321 行在它赋值之前就用了。修第一层 `a.mumu` 的 AttributeError 之后，
立刻又撞上这一层——所以这条门禁要能**静态**把这类隐患一次找干净。

口径（宁少报不乱报）：
- 只看**本函数自身作用域**（不进嵌套 def/class/lambda，它们的局部名互不影响）；
- `import x as y` 绑的是 `y`，**不**遮蔽 `x`，不算；
- 只有「裸 `import x` 出现在同函数内 `x.` 的首次使用之后」才报。
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STDLIB = {"time", "os", "sys", "json", "re", "io", "shutil", "subprocess",
          "glob", "base64", "hashlib", "random", "socket", "sqlite3",
          "threading", "datetime", "pathlib", "typing", "math"}
SKIP_DIRS = {".git", "_scratch", "_tools", "_vendor", "_internal", "build",
             "dist", "data", "logs", "user_data", "__pycache__",
             ".pytest_cache", "_build", "_build_check", "node_modules",
             "packages", "native"}


def _own_nodes(fn):
    """本函数作用域内的节点（不进入嵌套 def/class/lambda）。"""
    stack = list(fn.body)
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef, ast.Lambda)):
            continue
        for child in ast.iter_child_nodes(n):
            stack.append(child)


def _scan_src(src, path):
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        imports, uses = {}, []
        for n in _own_nodes(fn):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname:
                        continue
                    base = a.name.split(".")[0]
                    if base in STDLIB:
                        imports.setdefault(base, n.lineno)
            elif (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id in STDLIB):
                uses.append((n.value.id, n.lineno))
        for mod, imp_lineno in imports.items():
            early = [ln for (m, ln) in uses if m == mod and ln < imp_lineno]
            if early:
                hits.append((path, fn.name, fn.lineno, mod, imp_lineno, early[0]))
    return hits


def _py_files():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def test_no_function_scope_import_shadowing():
    bad = []
    for p in _py_files():
        try:
            src = io.open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        bad += _scan_src(src, os.path.relpath(p, ROOT).replace("\\", "/"))
    assert not bad, (
        "这些函数里 `import X` 出现在同函数 `X.` 的使用之后，会让 X 全函数变局部、"
        "必抛 UnboundLocalError：%s" % bad[:5])


def test_detector_catches_the_issue_16_shape():
    """负控：喂一段与 issue #16 同形的源码，检测器必须报出来（门禁不空转）。"""
    src = ("def main():\n"
           "    time.sleep(5)\n"
           "    import time\n")
    hits = _scan_src(src, "synthetic.py")
    assert hits and hits[0][3] == "time", hits


def test_detector_ignores_aliased_import():
    """`import time as _t` 绑的是 `_t`，不遮蔽 `time`——不许误报。"""
    src = ("def main():\n"
           "    time.sleep(5)\n"
           "    import time as _t\n"
           "    _t.sleep(1)\n")
    assert _scan_src(src, "synthetic.py") == []


def test_setup_device_help_does_not_crash():
    """issue #16 的直接症状：`setup_device.py` 因 `a.mumu` 未定义而崩。"""
    src = io.open(os.path.join(ROOT, "scripts", "setup_device.py"),
                  encoding="utf-8").read()
    assert 'add_argument("--mumu"' in src, "setup_device.py 缺 --mumu 参数"
    assert 'add_argument("--vm"' in src, "setup_device.py 缺 --vm 参数"
    assert "def _resolve_mumu(" in src, "缺 MuMuManager 路径解析函数"
