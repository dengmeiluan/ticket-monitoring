# -*- coding: utf-8 -*-
"""r1183：三率必须上页面，且页面上**不许自己算**。

数字来源链：`/api/three-rates` → `core.rates.snapshot()` → `core.baseline.by_path()`
（与 `python -m core.baseline` 同一份 SQL）。任何一环多写一遍算法，页面与报表就会对不上。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_endpoint_exists():
    assert '"/api/three-rates"' in WEBUI
    assert "from core import rates as _rt" in WEBUI


def test_card_exists_and_is_collapsed():
    assert 'id="ratesCard"' in WEBUI
    assert "function loadRates(" in WEBUI and "function toggleRates(" in WEBUI
    i = WEBUI.find('id="ratesBody"')
    assert 'display:none' in WEBUI[i:i + 60], "三率表默认必须收起"


def test_page_does_not_recompute_rates():
    """负控：页面里不许出现自己算爬取率/风险的分母。"""
    i = WEBUI.find("function loadRates(")
    seg = WEBUI[i:i + 2600]
    assert "attempts*" not in seg and "/attempts" not in seg, "页面在自己算爬取率"
    assert "fetch_paths" not in seg, "页面直接查库了（应该只读接口）"
    assert "/api/three-rates" in seg, "页面没有读接口"


def test_no_second_sql_first_class_citizen():
    """`core/rates.py` 不许再写一份 `path_status in ('ok','calendar')` 的字面量。"""
    src = io.open(os.path.join(ROOT, "core", "rates.py"), encoding="utf-8").read()
    assert "baseline.by_path(" in src, "rates 没有复用 baseline.by_path（口径会漂）"
    assert '"ok","calendar"' not in src.replace(" ", ""), "rates 里出现了第二份状态字面量"
