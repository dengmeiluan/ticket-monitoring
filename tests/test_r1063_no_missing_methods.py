# -*- coding: utf-8 -*-
"""r1063 T59：把「调用了不存在的方法」变成门禁（这类只在运行时炸）.

这不是多余的：HEAD 上就有一处 —— `crawlers/app_fliggy.py` 调用
`self.reject_far_dates(...)`，而 `AppCrawler` 里没有这个方法 → 飞猪 App
**每次采集在入口就 AttributeError**。只有干净检出才看得见（工作树里有未提交的
定义），所以门禁必须扫**仓库里实际的文件**，而不是只 import 一遍。

判据：遍历 `crawlers/**` 里每个类，收集 `self.<name>(...)` 调用；若 `<name>`
在**本类与继承链**的方法集合里都找不到，就报。放行 dunder。
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "crawlers")


def _classes(files):
    out = {}
    for path in files:
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {n.name for n in node.body
                       if isinstance(n, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))}
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            rec = out.setdefault(node.name, {"methods": set(), "bases": [],
                                             "file": path})
            rec["methods"] |= methods
            rec["bases"] += bases
    return out


def _all_methods(name, classes, seen=None):
    seen = set() if seen is None else seen
    if name in seen or name not in classes:
        return set()
    seen.add(name)
    got = set(classes[name]["methods"])
    for b in classes[name]["bases"]:
        got |= _all_methods(b, classes, seen)
    return got


def _files():
    out = []
    for base, _dirs, names in os.walk(PKG):
        for n in names:
            if n.endswith(".py"):
                out.append(os.path.join(base, n))
    return out


def test_no_missing_self_method_calls():
    files = _files()
    assert files, "没扫到 crawlers/ 下的文件"
    classes = _classes(files)
    bad = []
    for path in files:
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            have = _all_methods(node.name, classes)
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                if not (isinstance(fn, ast.Attribute)
                        and isinstance(fn.value, ast.Name)
                        and fn.value.id == "self"):
                    continue
                if fn.attr in have or fn.attr.startswith("__"):
                    continue
                bad.append("%s:%d %s.%s()"
                           % (os.path.basename(path), sub.lineno, node.name,
                              fn.attr))
    assert not bad, ("这些 self.x() 在本类与继承链里都找不到定义——"
                     "只会在运行时炸，而且往往只走某条分支才炸：\n  "
                     + "\n  ".join(sorted(set(bad))))


def test_far_date_guard_exists_on_the_app_base():
    """飞猪 App 一进门就调 `reject_far_dates`：基类必须有它（HEAD 曾缺失）。"""
    src = io.open(os.path.join(PKG, "app_base.py"), encoding="utf-8").read()
    assert "def reject_far_dates(" in src
    assert "date_horizon_days" in src
    i = src.index("def reject_far_dates(")
    seg = src[i:i + 1200]
    assert "unsupported" in seg, "超视野的日期要记 unsupported，不能记失败"
