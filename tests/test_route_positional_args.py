# -*- coding: utf-8 -*-
"""门禁：`Route(...)` 的位置参数不得超过前 5 个。

为什么：#20 给 `Route` 插了一个字段 `alert_direct_bag`，位置正好在
`alert_direct` 与 `alert_transfer` **中间**。dataclass 按声明顺序绑定位置参数，
所以任何 `Route(a, b, c, d, e, 300, 200)` 这类写法都会在插入字段后**静默错位**
——不报错，只是阈值跑到别的字段上（这类 bug 极难查）。

现状：生产代码（main.py）全部用关键字构造，测试里有 8 处按 5 个位置参数构造，
都在 `dates` 之前，安全。这条门禁保证将来不会有人再往前 5 个之后按位置传。
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_POSITIONAL = 5          # from_code, from_name, to_code, to_name, dates
SKIP_DIRS = {".git", "_scratch", "_tools", "_vendor", "_internal", "build",
             "dist", "data", "logs", "user_data", "__pycache__",
             ".pytest_cache", "node_modules", "packages", "native"}


def _route_calls(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Route"):
            yield node


def test_no_route_call_with_too_many_positional_args():
    bad = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(base, f)
            try:
                import io
                tree = ast.parse(io.open(p, encoding="utf-8").read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for call in _route_calls(tree):
                if len(call.args) > MAX_POSITIONAL:
                    rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                    bad.append("%s:%d 传了 %d 个位置参数"
                               % (rel, call.lineno, len(call.args)))
    assert not bad, (
        "Route 的字段会随版本插入/重排，超过 %d 个位置参数就会静默错位；"
        "请改用关键字：%s" % (MAX_POSITIONAL, bad[:5]))


def test_first_five_fields_are_stable():
    """前 5 个位置参数必须是身份字段（这是允许按位置传的唯一区间）。"""
    import sys
    sys.path.insert(0, ROOT)
    from core.models import Route
    import dataclasses
    names = [f.name for f in dataclasses.fields(Route)]
    assert names[:5] == ["from_code", "from_name", "to_code", "to_name",
                         "dates"], "Route 前 5 个字段变了：%s" % names[:5]


def test_detector_flags_positional_overflow():
    """负控：喂一个超限调用，检测器必须抓到（门禁不空转）。"""
    tree = ast.parse("Route('SHA', '上海', 'URC', '乌鲁木齐', ['2026-01-01'],"
                     " 300, 200, 180)\n")
    calls = list(_route_calls(tree))
    assert calls and len(calls[0].args) > MAX_POSITIONAL
