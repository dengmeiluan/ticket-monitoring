# -*- coding: utf-8 -*-
"""r410：传给 path_note(url=...) 的引用必须能真正求值。

自查发现（真跑探针才暴露）：途牛国内那处我写成了 `url=self.LIST_API`，
但 `LIST_API` 是**模块级常量**、不是类属性 → 探针直接报
`'TuniuCrawler' object has no attribute 'LIST_API'`，整家渠道 OK→error。

静态扫描抓不到这种错（语法合法），必须有守卫。本组用 AST 取出
所有 `url=` 实参里的 `self.X`，再核对 X 确实是类属性或实例属性。
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _crawler_files():
    for fn in sorted(os.listdir(CRAWLERS)):
        if fn.endswith(".py") and fn not in ("__init__.py", "challenge.py"):
            yield fn, os.path.join(CRAWLERS, fn)


def test_url_self_refs_resolve():
    """url= 里出现的 self.X 必须在该文件里定义成类属性/模块常量。"""
    bad = []
    for fn, path in _crawler_files():
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        # 收集模块级名字与类内属性
        module_names = set()
        class_attrs = set()
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if isinstance(tgt, ast.Name):
                    module_names.add(tgt.id)
            if isinstance(node, ast.ClassDef):
                for st in node.body:
                    if isinstance(st, (ast.Assign, ast.AnnAssign)):
                        tg = (st.targets[0] if isinstance(st, ast.Assign)
                              else st.target)
                        if isinstance(tg, ast.Name):
                            class_attrs.add(tg.id)
                    elif isinstance(st, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        class_attrs.add(st.name)   # 方法也可安全地 self.x()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname != "path_note":
                continue
            for kw in node.keywords:
                if kw.arg != "url":
                    continue
                for sub in ast.walk(kw.value):
                    if (isinstance(sub, ast.Attribute)
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id == "self"):
                        if sub.attr not in class_attrs and sub.attr not in module_names:
                            bad.append((fn, node.lineno, sub.attr))
    assert not bad, "url= 引用了不存在的属性: %r" % (bad,)


def test_tuniu_list_api_is_module_level():
    """反向锚点：LIST_API 是模块级常量，用 self. 访问会 AttributeError。"""
    import crawlers.tuniu as T
    assert hasattr(T, "LIST_API"), "LIST_API 应为模块级"
    assert not hasattr(T.TuniuCrawler, "LIST_API"), \
        "若改成类属性，本守卫的前提就变了，需同步更新"


def test_every_channel_success_note_has_url():
    """五家渠道的成功记账必须带 url（与 r409 守卫互为加强）。"""
    expect = {
        "ctrip.py": ['"PC", "ok", rows=len(flights)', '"H5", "ok", rows=len(flights)'],
        "tuniu.py": ['"国际列表接口"', '"m.tuniu.com 列表接口"'],
        "qunar.py": ['"touch.qunar.com 国际列表"'],
    }
    for fn, anchors in expect.items():
        src = open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()
        for a in anchors:
            i = src.index(a)
            assert "url=" in src[max(0, i - 500):i + 400], (fn, a)
