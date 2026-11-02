# -*- coding: utf-8 -*-
"""r904：产品代码里不得有重复的字典字面量键。

Python 允许同一个字典字面量重复写键，后者静默覆盖前者，运行时、日志和
接口都只看到最后一条——没有异常、没有告警。r903 已在渠道声明表里抓到
一次（矩阵 ✓ / 悬停说没接）；同样的模式存在于任何数据表里。

判据：扫描 `core/`、`crawlers/` 与顶层运行文件的所有 `.py`，任何字典
字面量的重复键都报红（含值相同的重复——它们不会改变行为，但会让读者
误以为表里只有一条，并给下一次改值留下“改哪一条”的歧义）。

测试文件不扫：替身/样本里允许构造重复键来验证别的行为。
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOP_LEVEL = ("webui.py", "main.py", "report.py", "wizard.py")


def _product_files():
    files = [os.path.join(ROOT, name) for name in TOP_LEVEL
             if os.path.exists(os.path.join(ROOT, name))]
    for folder in ("core", "crawlers"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, folder)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            files.extend(os.path.join(dirpath, name)
                         for name in filenames if name.endswith(".py"))
    return sorted(files)


def _duplicates(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:  # {**spread}
                continue
            try:
                key = ast.literal_eval(key_node)
                hash(key)
            except Exception:
                continue
            if key in seen:
                out.append((key, seen[key], getattr(value_node, "lineno", "?")))
            else:
                seen[key] = getattr(key_node, "lineno", "?")
    return out


def test_no_duplicate_literal_keys_in_product_code():
    files = _product_files()
    assert len(files) >= 60, (
        "只扫到 %d 个产品文件，扫描根可能失效：%s" % (len(files), files[:5]))
    bad = []
    for path in files:
        for key, first, duplicate in _duplicates(path):
            bad.append("%s[%r] 首写行 %s / 覆盖行 %s"
                       % (os.path.relpath(path, ROOT), key, first, duplicate))
    assert not bad, (
        "重复字典键会静默覆盖前值：\n" + "\n".join(bad))
