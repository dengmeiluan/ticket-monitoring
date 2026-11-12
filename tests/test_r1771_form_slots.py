# -*- coding: utf-8 -*-
"""r1771：城市位坐标必须取页面节点中心（分辨率无关），不能靠 y 区间猜。

07:43 账本：`切回机票后仍打不开城市页 · 页面: 机票表单`
——恢复逻辑已把页面切回机票，但「点城市位」那一下点在别处了：
`_form_slot()` 的 y 区间/默认常量换分辨率就漂。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng_parse import (  # noqa: E402
    parse_form, parse_form_slots)

FORM = """<hierarchy>
  <node text="机票查询" bounds="[500,1500][700,1560]" />
  <node text="单程" bounds="[120,700][220,760]" />
  <node text="往返" bounds="[260,700][360,760]" />
  <node text="上海" bounds="[120,1080][320,1140]" />
  <node text="东京" bounds="[900,1080][1100,1140]" />
  <node text="11月16日" bounds="[120,1300][360,1360]" />
</hierarchy>"""


def test_slots_come_from_page_nodes():
    d = parse_form_slots(FORM)
    assert d.get("dep") == (220, 1110), d
    assert d.get("arr") == (1000, 1110), d
    assert d.get("date") == (240, 1330), d


def test_slots_match_parse_form_texts():
    f = parse_form(FORM)
    assert f and f["dep"] == "上海" and f["arr"] == "东京", f
    d = parse_form_slots(FORM)
    assert d, "同一份表单必须也能给出坐标"


def test_non_form_has_no_slots():
    assert parse_form_slots('<hierarchy><node text="火车票" '
                            'bounds="[0,0][10,10]" /></hierarchy>') == {}


def test_crawler_prefers_slots():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "app_tongcheng.py"),
        encoding="utf-8").read()
    assert "parse_form_slots" in src, "爬虫没用页面坐标"
    i = src.index('_slots.get("dep")')
    assert "_form_slot(page" in src[i:i + 200], "兜底没保留"
