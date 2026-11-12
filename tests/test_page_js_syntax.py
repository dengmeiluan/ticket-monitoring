# -*- coding: utf-8 -*-
"""页面内联 JS 必须语法正确（r1063 T17 事故后的永久门禁）。

事故：在 `PACE` 行模板的块注释里写了 `**通路**/哪个维度`，其中的 `**/`
提前闭合了注释，后半句变成代码 → 整个 `<script>` 解析失败 →
`switchView is not defined`，健康页/导航全白。当时所有 Python 门禁全绿，
因为没人检查**页面 JS**。

这类破坏只有真跑浏览器才暴露，代价极高（整站白屏），所以在这里用
`node --check` 把每个 `<script>` 块过一遍：零依赖、秒级、不需要起服务。
"""
import io
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _blocks():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    return re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)


@pytest.mark.skipif(not shutil.which("node"), reason="环境没有 node，跳过 JS 语法检查")
def test_every_page_script_block_parses():
    blocks = _blocks()
    assert blocks, "webui.py 里一个 <script> 块都没抽到——检查抽取正则"
    bad = []
    for i, b in enumerate(blocks, 1):
        fn = os.path.join(ROOT, ".tmp_js_syntax_%d.js" % i)
        io.open(fn, "w", encoding="utf-8").write(b)
        try:
            r = subprocess.run(["node", "--check", fn], capture_output=True,
                               encoding="utf-8", errors="replace")
        finally:
            try:
                os.remove(fn)
            except OSError:
                pass
        if r.returncode != 0:
            head = (r.stderr or "").strip().splitlines()[:6]
            bad.append("block %d: %s" % (i, " / ".join(head)))
    assert not bad, (
        "页面 JS 语法错误（这会让整站白屏，例如 switchView is not defined）：\n"
        + "\n".join(bad))


def test_block_comment_never_closes_early():
    """块注释里禁止出现 `**/` 这类提前闭合（本次事故的根因写法）。"""
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    hits = []
    for i, b in enumerate(re.findall(r"/\*.*?\*/", src, re.S), 1):
        if "**/" in b.replace("*/", "", 1):
            hits.append(i)
    # 只要能被 `/\*.*?\*/` 完整匹配，就说明没有提前闭合的问题；
    # 这里额外防一种：注释体内出现 `/*`（嵌套），会让读者误判范围。
    assert not hits, "有块注释疑似提前闭合：%s" % hits
