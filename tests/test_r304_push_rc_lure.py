# -*- coding: utf-8 -*-
"""r304 推送层透传（PUSH 审校 A1 图纸 + Soldier F1 裁决修正；零发送
路径改动）：

P2-1 退改字段（returnFee/changeFee）webui 价格格徽标有（生产 1999 行
在产出）、推送图次行零承载——退改手续费直接影响「买了亏不亏」，推送
读者面与控制台对决策信息的可见性不对等。rc 槽挂恒保组（与 transferTax
「实付差额」同族——比价隐性成本不随丢档蒸发）；词面逐字同 webui
`_rc_txt`（跨语言单源同步律）。

P3-1（lurePrice 专用槽）**撤案**：该词面的正文载体是 labels 槽（爬虫
端组装链 append 进 labels，PNG/title/CSV 通道闭合；lurePrice 数值键
仅驱动 webui 价格格徽标）——「grep lurePrice 键名零引用≠词面不在图」
的形态盲区假案，专用槽曾致同词面双渲染（Soldier F1 实锤），禁复活钉
在案（test_lure_word_carried_by_labels_never_dedicated_slot）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r304_push_rc_lure.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rsrc(name="report.py"):
    return open(os.path.join(_BASE, name), encoding="utf-8").read()


def _flight(**kw):
    f = {"price": 2150, "name": "东航MU8352", "code": "MU8352",
         "depTime": "08:20", "arrTime": "11:35", "_platform": "ctrip"}
    f.update(kw)
    return f


# ---------------------------------------------------------------- _rc_word

def test_rc_word_none_none_empty():
    """双侧缺席（键缺/None）不出词——「无值不落词」，与 webui
    _rc_txt 首门同语义。"""
    from report import _rc_word
    assert _rc_word({}) == ""
    assert _rc_word({"returnFee": None, "changeFee": None}) == ""


def test_rc_word_free_and_priced_forms():
    """0/0→「免费退改」；双侧数值→「退￥N·改￥M」（·连接，与 webui
    join('·') 同字）。"""
    from report import _rc_word
    assert _rc_word({"returnFee": 0, "changeFee": 0}) == "免费退改"
    assert _rc_word({"returnFee": 464, "changeFee": 232}) == "退￥464·改￥232"


def test_rc_word_minus_one_both_and_single_side():
    """-1「不可办理」：双侧同 -1 与 webui one() 逐字同——
    「不可退·不可改」（join 形态，非并读缩写）；单侧 -1 缺另一侧
    →「不可退」（filter(Boolean) 同构：缺席侧不出段）。"""
    from report import _rc_word
    assert _rc_word({"returnFee": -1, "changeFee": -1}) == "不可退·不可改"
    assert _rc_word({"returnFee": -1, "changeFee": None}) == "不可退"
    assert _rc_word({"returnFee": None, "changeFee": -1}) == "不可改"
    assert _rc_word({"returnFee": -1, "changeFee": 100}) == "不可退·改￥100"


# ---------------------------------------------------------------- 槽位注册

def test_rc_slot_registered_in_parts():
    """次行字段清单注册 rc 槽（三端渲染门收口：爬虫键 ↔ webui
    白名单/价格格徽标 ↔ PNG 槽——age/risk 同律先例）。"""
    src = _rsrc()
    assert '("rc", _rc_word(f))' in src, "rc 槽未入次行字段清单"


def test_lure_word_carried_by_labels_never_dedicated_slot():
    """lure 词面（页面价￥N不可购）的正文载体是 labels 槽：爬虫端
    组装链把词面 append 进 labels（ctrip.py `_lure_price_tag`），PNG
    labels 槽/lurePrice 数值键驱动 webui 价格格徽标/CSV 三通道已闭合。
    report.py 端不得再造专用槽或第二词源——同词面双渲染零信息增量
    且重复词面反引「图内价错了」困惑（Soldier F1 实锤：两槽同吃
    绘制 2 次）。禁复活 + labels 承载实效双段断言。"""
    src = _rsrc()
    assert '("lure",' not in src, "lure 专用槽禁复活（labels 已承载同词面）"
    assert "页面价" not in src, "report.py 端不得再造该词面第二源"
    assert '("labels", str(f.get("labels") or "").strip())' in src, \
        "labels 槽承载实效丢失（词面进图的真实载体）"


# ---------------------------------------------------------------- 丢档链

def test_lure_not_in_chain_rc_never_dropped():
    """丢档链语义：rc 恒保组不进任何丢档档位（比价隐性成本语义，
    与 transferTax 同族恒保）；lure 不设专用槽故不入链（若将来以
    任何形式回流须与本钉对账，labels 槽既有丢档语义已覆盖同词面）。"""
    src = _rsrc()
    m = re.search(r"_chain = \(.*?\n\s+for _drop, _ss in _chain:", src, re.S)
    assert m, "_chain 丢档链未找到"
    chain = m.group(0)
    assert (chain.count("True)") + chain.count("False)")) == 6, \
        f"丢档链档位数漂移：{chain.count('True)') + chain.count('False)')}"
    assert re.search(r'"tkrisk",\s*"carryon"', chain), \
        "末档形态漂移（tkrisk 后应直连 carryon）"
    assert '"rc"' not in chain, "rc（恒保组）出现在丢档链"
    assert '"lure"' not in chain, "lure 专用槽残留丢档链"


# ---------------------------------------------------------------- 行为钉

def test_rc_word_rendered_into_png(tmp_path, monkeypatch):
    """真实渲染链行为钉：含 rc 的行渲染 tmp PNG，词条以 12px 次行
    小字真实落画布（捕获 ImageDraw.text 全部绘制串）；lure 词面不经
    report 端（labels 槽承载，fixture 无 labels 词面故不得出现）。"""
    import PIL.ImageDraw as _ID
    from report import render_flights_table as _render

    drawn = []
    _orig = _ID.ImageDraw.text

    def _spy(self, xy, text, **k):
        drawn.append(str(text))
        return _orig(self, xy, text, **k)

    monkeypatch.setattr(_ID.ImageDraw, "text", _spy)
    rows = [("direct", [_flight(returnFee=464, changeFee=232)])]
    out = tmp_path / "t.png"
    _render(rows, "测试", str(out), top_n=5)
    assert out.exists() and out.stat().st_size > 0, "渲染未产出"
    joined = "\n".join(drawn)
    assert "退￥464·改￥232" in joined, "rc 词条未进图"
    assert "页面价" not in joined, "report 端 lure 词面残留"


def test_rc_absent_row_renders_without_word(tmp_path, monkeypatch):
    """无 rc/lure 值的行零词条（空值剔除门）——防「无值也占位」
    反向回归。"""
    import PIL.ImageDraw as _ID
    from report import render_flights_table as _render

    drawn = []
    _orig = _ID.ImageDraw.text

    def _spy(self, xy, text, **k):
        drawn.append(str(text))
        return _orig(self, xy, text, **k)

    monkeypatch.setattr(_ID.ImageDraw, "text", _spy)
    rows = [("direct", [_flight()])]
    out = tmp_path / "t.png"
    _render(rows, "测试", str(out), top_n=5)
    joined = "\n".join(drawn)
    assert "退￥" not in joined and "不可退" not in joined
    assert "页面价" not in joined
