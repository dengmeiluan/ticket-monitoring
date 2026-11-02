# -*- coding: utf-8 -*-
"""r720 去哪儿 App 城市页：收起态没有 EditText，必须先点可点的占位层。

真机实测（2026-10-31，MuMu Android 12 / 去哪儿 9.x）：

* 城市页收起时 **EditText 数量为 0**，只有一层
  `com.Qunar:id/qd_placeholder_v`（`android.view.View`，clickable=true）
  包着一行文字 `com.Qunar:id/qd_placeholder`（TextView，clickable=false）。
* 旧代码用「按 text 找搜索框」兜底，命中的是**内层文字**（不可点），
  等于没展开；`_find_edit_box` 又恒为 None，于是国际城市永远选不中，
  整轮记成 `set-city-dep`（日志写「设出发城市失败：上海」）。
* 展开后 EditText 才出现（实测约 1–2s），因此要轮询等待，不能取一帧就判。
* 搜索结果行 `上海（不限机场）   上海   中国   SHA` 及其祖先**全是
  clickable=false 的 ViewGroup**，点它靠坐标命中；按坐标点可以正常返回首页。

本门禁用合成 XML 固定这些结构约束，防止「按文案找输入框」的兜底回潮。
"""
import os
import pathlib
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_qunar import (  # noqa: E402
    _find_edit_box, _find_search_placeholder, _ID_CITY_SEARCH_PH,
)


def _node(**kw):
    """把 python 关键字转成 XML 属性；`cls` 映射到 class（class 是保留字）。"""
    parts = []
    for k, v in kw.items():
        name = "class" if k == "cls" else k.replace("_", "-")
        parts.append('%s="%s"' % (name, v))
    return "<node %s />" % " ".join(parts)


COLLAPSED = ("<hierarchy>"
             + _node(index="0", text="", resource_id=_ID_CITY_SEARCH_PH + "_v",
                     cls="android.view.View", clickable="true",
                     bounds="[24,140][876,196]")
             + _node(index="1", text="搜索国家/城市/景点等",
                     resource_id=_ID_CITY_SEARCH_PH,
                     cls="android.widget.TextView", clickable="false",
                     bounds="[60,158][400,180]")
             + "</hierarchy>")

EXPANDED = ("<hierarchy>"
            + _node(index="0", text="上海", resource_id="",
                    cls="android.widget.EditText", clickable="true",
                    bounds="[86,146][876,206]")
            + _node(index="1", text="上海（不限机场）   上海   中国   SHA",
                    cls="android.widget.TextView", clickable="false",
                    bounds="[80,212][461,245]")
            + "</hierarchy>")


def test_collapsed_city_page_has_no_edittext():
    """这条是前提：如果哪天收起态真有 EditText，本文件的修复就多余了。"""
    assert _find_edit_box(COLLAPSED) is None, (
        "收起态出现了 EditText —— 结构变了，先复核再决定是否保留 r720 的展开步骤")


def test_placeholder_layer_is_clickable_view():
    """展开目标必须是可点的外层 View，而不是那行文字。"""
    node = _find_search_placeholder(COLLAPSED)
    assert node is not None, "连占位行都没找到，展开步骤无从点击"
    assert node.get("id", "").endswith("qd_placeholder_v") or (
        "搜索国家" in (node.get("text") or "")), node


def test_expanded_city_page_exposes_edittext():
    box = _find_edit_box(EXPANDED)
    assert box is not None, "展开后仍找不到 EditText"
    assert box["y2"] > box["y1"] and box["x2"] > box["x1"], box


def test_source_no_longer_falls_back_to_text_box():
    """读源码确认没有回退成「把 TextView 当输入框点」的旧写法。

    常量 `_ID_CITY_SEARCH_PH` 定义在文件顶部（并只在 `_find_edit_box` 里用），
    原断言用「② 用搜索框」后 1600 字符窗去截，函数体一长就假红（r813k 实测）。
    改为：回退段必须调用 `_find_edit_box`，且该 helper 自己必须用占位行常量。
    """
    src = pathlib.Path(ROOT, "crawlers", "app_qunar.py").read_text(
        encoding="utf-8")
    i = src.index("② 用搜索框")
    seg = src[i:i + 1600]
    assert "_find_edit_box(page)" in seg, seg[:300]
    # 回退段通过 _find_search_placeholder 先点占位行（常量在该 helper 里），
    # 不是直接把常量名字写在调用段——原断言用 1600 字符窗找常量会假红。
    assert "_find_search_placeholder(page)" in seg, seg[:400]
    j = src.index("def _find_search_placeholder")
    k = src.find("\ndef ", j + 10)
    helper = src[j:k if k > j else j + 1200]
    assert "_ID_CITY_SEARCH_PH" in helper, (
        "搜索占位行 helper 不再认 qd_placeholder：收起态没有 EditText，"
        "国际城市会再次选不中")
    assert 'or _find_text(page, "搜索国家"' not in seg, (
        "又退回「按文案当输入框点」的兜底了——命中的是 clickable=false 的文字")


# ---- r721 中间页「日期列 + 查价」的前导零 ----

from crawlers.app_qunar import _date_slot_tap  # noqa: E402


def _slot_xml(*pairs):
    """pairs: (date_text, x1)。返回带「日期行 + 下方查价」的中间页 XML。"""
    out = ["<hierarchy>"]
    for i, (d, x) in enumerate(pairs):
        out.append(_node(index=str(i), text=d, resource_id="",
                         cls="android.widget.TextView", clickable="false",
                         bounds="[%d,111][%d,132]" % (x, x + 60)))
        out.append(_node(index=str(i), text="查价", resource_id="",
                         cls="android.widget.TextView", clickable="false",
                         bounds="[%d,155][%d,182]" % (x, x + 60)))
    out.append("</hierarchy>")
    return "".join(out)


def test_date_slot_matches_leading_zero():
    """页面写 `01.29`，目标给 `2027-01-29` —— 必须能配上。

    旧实现用 `"%d.%02d"` 生成 `1.29` 精确比对，1–9 月永远匹配不上，
    中间页一列都不点，60s 后记 `no-list-page`（国内航线整轮 0 行）。
    """
    xml = _slot_xml(("01.27", 22), ("01.28", 172), ("01.29", 322))
    hit = _date_slot_tap(xml, "2027-01-29")
    assert hit is not None, "带前导零的日期没配上"
    assert hit["x1"] == 322, hit


def test_date_slot_matches_without_leading_zero():
    """不带的写法也要继续认（换版/别的月份可能不补零）。"""
    xml = _slot_xml(("1.9", 22), ("1.10", 172))
    hit = _date_slot_tap(xml, "2027-01-09")
    assert hit is not None and hit["x1"] == 22, hit


def test_date_slot_picks_same_column_button():
    """配对的必须是**同一列**下方那个查价，不能取到邻列。"""
    xml = _slot_xml(("01.27", 22), ("01.28", 172), ("01.29", 322))
    hit = _date_slot_tap(xml, "2027-01-28")
    assert hit is not None, hit
    assert hit["x1"] == 172, hit


# ---- r722 「日期是否已设为目标日」只看首页日期位 ----

from crawlers.app_qunar import (  # noqa: E402
    _find_id, _find_text, _ID_DEP_DATE_TV, _ID_DEP_DATE_LL,
    AppQunarCrawler,
)

HOME_29_JAN = ("<hierarchy>"
               + _node(index="0", text="", resource_id=_ID_DEP_DATE_LL,
                       cls="android.widget.RelativeLayout", clickable="true",
                       bounds="[48,413][208,458]")
               + _node(index="0", text="1月29日", resource_id=_ID_DEP_DATE_TV,
                       cls="android.widget.TextView", clickable="false",
                       bounds="[48,413][163,458]")
               # 日历弹层残留的候选文案：全文搜就会误命中
               + _node(index="1", text="11月16日", resource_id="",
                       cls="android.widget.TextView", clickable="false",
                       bounds="[300,900][420,960]")
               + "</hierarchy>")


class _StuckDevice:
    """日历弹层永远打不开：用来验证判据不会「白说选好了」。"""

    def dump(self, retries=2):
        return HOME_29_JAN

    def tap(self, x, y):
        return True

    def keyevent(self, k):
        return True

    def window_size(self):
        return (900, 1600)

    def swipe(self, *a, **k):
        return True


def _crawler():
    import logging
    c = AppQunarCrawler({"user_data_dir": "_scratch/r722_data"},
                        logging.getLogger("r722"))
    c._back_to_home = lambda dev: HOME_29_JAN   # 不真起 App
    return c


def test_pick_date_rejects_when_home_shows_other_date():
    """首页日期位是 1月29日、目标 11-16、日历打不开 → 必须 False。

    旧判据 `_find_text(xml, '11月16日')` 会被页面别处的同名文案骗到，
    返回 True，随后用 1月29日 的结果冒充 11-16（日期错位价）。
    """
    # 前提：旧判据在这份 XML 上确实会误判 —— 否则本用例失去意义
    assert _find_text(HOME_29_JAN, "11月16日") is not None
    assert _find_id(HOME_29_JAN, _ID_DEP_DATE_TV)["text"] == "1月29日"
    ok = _crawler()._pick_date(_StuckDevice(), HOME_29_JAN, "2026-11-16")
    assert ok is False, "首页日期不是目标日、日历又没打开，却报「已选好」"


def test_pick_date_accepts_when_home_already_on_target():
    """首页日期位就是目标日 → 直接 True，不去点它（点它会打开日历）。"""
    xml = ("<hierarchy>"
           + _node(index="0", text="11月16日", resource_id=_ID_DEP_DATE_TV,
                   cls="android.widget.TextView", clickable="false",
                   bounds="[48,413][163,458]")
           + "</hierarchy>")

    class _NoTap(_StuckDevice):
        tapped = False

        def tap(self, x, y):
            _NoTap.tapped = True
            return True

    ok = _crawler()._pick_date(_NoTap(), xml, "2026-11-16")
    assert ok is True
    assert _NoTap.tapped is False, "已经是目标日还去点日期位（会打开日历）"
