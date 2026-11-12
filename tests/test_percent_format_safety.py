# -*- coding: utf-8 -*-
"""门禁：被 `%%` 格式化的字符串里夹了非法 `%` ——这类写法运行时**必崩**。

来历（issue #18，作者 ismoss）：`/api/test-email` 的正文常量里写了
「明细与网页 100% 同视觉」，整段又走 `% (ver, now)` 格式化，于是
`ValueError: unsupported format character '同'` ——「测试邮件」按钮 100% 失败，
而这行代码看上去毫无问题。

为什么用 AST 而不是 grep：grep 抓不准"哪些字符串真的会被 %"，
很容易报一堆假阳性（正常的 `"%s" % x` 也会命中），门禁一吵就没人看了。
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALID = set("diouxXeEfFgGcrsa%")
SKIP_DIRS = {".git", "_scratch", "_tools", "_vendor", "_internal", "build",
             "dist", "data", "logs", "user_data", "__pycache__",
             ".pytest_cache", "node_modules", "packages", "native"}


def bad_percent(fmt: str):
    """返回第一个非法 `%` 的 (index, 后续字符)；全合法返回 None。"""
    i, n = 0, len(fmt)
    while i < n:
        if fmt[i] != "%":
            i += 1
            continue
        j = i + 1
        if j >= n:
            return (i, "")
        if fmt[j] == "(":                       # %(name)s
            k = fmt.find(")", j)
            if k < 0:
                return (i, "(")
            j = k + 1
        while j < n and fmt[j] in "-+ #0":      # flags
            j += 1
        while j < n and (fmt[j].isdigit() or fmt[j] == "*"):
            j += 1
        if j < n and fmt[j] == ".":             # precision
            j += 1
            while j < n and (fmt[j].isdigit() or fmt[j] == "*"):
                j += 1
        while j < n and fmt[j] in "hlL":        # length
            j += 1
        if j < n and fmt[j] in VALID:
            i = j + 1
            continue
        return (i, fmt[j] if j < n else "")
    return None


def scan_source(src: str):
    """返回 [(lineno, index, 后续字符, 片段)]：常量字符串 % 格式化的非法 %。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
            continue
        left = node.left
        if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
            continue
        bad = bad_percent(left.value)
        if bad:
            idx, ch = bad
            hits.append((node.lineno, idx, ch,
                         left.value[max(0, idx - 28):idx + 10]))
    return hits


def test_repo_has_no_unsafe_percent_format():
    bad = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(base, f)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            try:
                src = io.open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, idx, ch, seg in scan_source(src):
                bad.append("%s:%d 第 %d 个字符后跟 %r … %s"
                           % (rel, lineno, idx, ch, seg))
    assert not bad, ("这些字符串会被 %% 格式化且夹了非法 %%%%，运行时必抛 ValueError"
                     "（字面 %% 要写成 %%%%）：%s" % bad[:6])


def test_detector_catches_the_issue_18_shape():
    """负控：喂 issue #18 的原写法，必须抓到（门禁不空转）。"""
    src = ('desp = ("... 100% 同视觉 ..."\n'
           '        "> 版本 v%s" % ("1.7.6",))\n')
    hits = scan_source(src)
    assert hits, "检测器漏掉了 issue #18 的形态"
    assert hits[0][2] == "同", hits


def test_detector_accepts_legal_specs():
    """正控：`%s` / `%d` / `%.2f` / `%(name)s` / `%%` 都不许误报。"""
    src = ('a = "%s-%d-%.2f-%(n)s-100%%" % ("x", 1, 2.5, {"n": 3})\n')
    assert scan_source(src) == []
