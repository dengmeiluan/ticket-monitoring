# -*- coding: utf-8 -*-
"""r1734：`docs/HEALTH_STATES.md` 与代码不许漂。

这份文档是「某家渠道为什么不动 → 三个面各说什么」的单一真源。
本轮之前这类知识只散在 commit 里，改一处忘了另一处就会自相矛盾
（停手/停服/未在清单/冷却中/静默/零出数 六个状态都是这么补出来的）。
本门禁只做一件事：文档提到的每个状态词，代码里必须真有对应实现；
反过来，代码里新增状态也必须先在文档里登记。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 六个状态 → 代码里必须能找到的实现锚点
ANCHORS = {
    "停手": ("halt", "停手"),
    "停服": ("retired", "网页已停服"),
    "未在清单": ("disabled", "未在清单"),
    "冷却中": ("cooldown", "冷却中"),
    "夜间静默": ("quiet", "夜间静默中"),
    "零出数": ("no_ok", "全失败"),
}


def _doc():
    return io.open(os.path.join(ROOT, "docs", "HEALTH_STATES.md"),
                   encoding="utf-8").read()


def _webui():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_doc_lists_all_states():
    doc = _doc()
    for name in ANCHORS:
        assert name in doc, "文档漏了状态：%s" % name


def test_code_implements_each_state():
    w = _webui()
    missing = []
    for name, (code_kw, ui_kw) in ANCHORS.items():
        if code_kw not in w or ui_kw not in w:
            missing.append("%s（需要 %r / %r）" % (name, code_kw, ui_kw))
    assert not missing, "文档写了但代码没有：%s" % missing


def test_doc_rules_present():
    doc = _doc()
    for rule in ("状态先于动作", "建议必须有按钮", "口径不许冒充"):
        assert rule in doc, "文档缺规矩：%s" % rule
