# -*- coding: utf-8 -*-
"""r1638：停服的渠道（去哪儿 PC）不许再引导「去启用」。

用户原话：「去哪儿 PC 都停服了还勾选干嘛？」
账本最后一条是 `unsupported` + 「网页通路已停服」——勾了也不会采，
所以只有一个正确结论：**网页已停服**，而且卡片不该有任何按钮。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_retired_reason_helper_exists():
    s = _w()
    assert "def _retired_reason(" in s, "没有停服判定"
    assert '"网页已停服"' in s, "停服结论文案缺失"


def test_diag_card_retired_has_no_buttons():
    s = _w()
    i = s.index("if(c.retired){")
    # 只取**这一支**：到下一个分支（if(c.no_plan)）为止。
    j = s.index("if(c.no_plan){", i)
    seg = s[i:j]
    assert 'class="hdiag-acts"></div>' in seg, (
        "停服卡片仍会渲染按钮——勾了也不会采，按钮等于骗人")
    assert "去启用" not in seg, "停服卡片里出现了「去启用」"


def test_pacing_advice_retired_state():
    s = _w()
    assert '"state": "retired"' in s, "节流建议没有 retired 状态"
    assert "adv.state==='retired'" in s, "节流行没有渲染 retired"
    assert "网页已停服" in s


def test_no_plan_not_applied_when_retired():
    s = _w()
    i = s.index("_c2[\"no_plan\"]")
    seg = s[i:i + 220]
    assert "not _rr" in seg, "停服时仍在判「未在清单」——会引导用户去勾选"
