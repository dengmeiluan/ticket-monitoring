# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1045_fliggy_cal_day_ocr.py
- tests/test_r1054_fliggy_rt_footer_real.py
- tests/test_r735_fliggy_h5_round_trip.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import os
import pytest
import sys

from crawlers.app_fliggy import _cal_day_xy_by_ocr
from crawlers.app_fliggy_parse import parse_round_trip_footer
from crawlers.fliggy_h5 import FliggyH5Crawler


# ---- merged from tests/test_r1045_fliggy_cal_day_ocr.py ----

_MONTHS = [(2026, 11, 697.0), (2026, 12, 1830.0)]
_COLS = (83, 255, 426, 598, 769, 940, 1112)


def _w(t, x, y, ww=40, hh=40):
    return {"t": t, "x": x, "y": y, "w": ww, "h": hh}


def _row(days, y, cols=_COLS):
    return [_w(str(d), x, y) for d, x in zip(days, cols)]


def _nov():
    return (_row((22, 23, 24, 25, 26, 27, 28), 1458)
            + [_w("29", 83, 1660), _w("30", 255, 1660)])


def test_finds_day_by_number():
    xy = _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 23, _MONTHS)
    assert xy is not None
    # 23 号在 x=255 那一列，中心 = 255 + 40/2
    assert xy[0] == 275
    assert 1458 <= xy[1] <= 1498


def test_finds_last_row_day():
    xy = _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 29, _MONTHS)
    assert xy is not None
    assert 1660 <= xy[1] <= 1700


def test_missing_day_returns_none():
    assert _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 15, _MONTHS) is None


def test_day_outside_month_band_is_ignored():
    """12 月的日号不能被当成 11 月的（区间按表头切）。"""
    words = _nov() + _row((1, 2, 3, 4, 5, 6, 7), 2390)
    # 11 月区间里不存在 3 号 → 必须 None，不能跨月误取
    assert _cal_day_xy_by_ocr(None, words, 2026, 11, 3, _MONTHS) is None
    # 12 月区间里 3 号存在
    assert _cal_day_xy_by_ocr(None, words, 2026, 12, 3, _MONTHS) is not None


def test_three_digit_price_is_not_a_day():
    """价格（如 820）不能当日号用——只接受 ≤2 位、1..31。"""
    words = [_w("820", 83, 1458), _w("950", 255, 1458),
             _w("700", 426, 1458), _w("680", 598, 1458),
             _w("21", 769, 1458)]
    # 820/950/700/680 都被排除，只剩 21 一个，行内不足 4 个 → 不应命中 820
    assert _cal_day_xy_by_ocr(None, words, 2026, 11, 21, _MONTHS) is not None
    xy = _cal_day_xy_by_ocr(None, words, 2026, 11, 21, _MONTHS)
    assert 769 <= xy[0] <= 809


def test_no_months_returns_none():
    assert _cal_day_xy_by_ocr(None, _nov(), 2026, 11, 23, []) is None


# ---- merged from tests/test_r1054_fliggy_rt_footer_real.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "fliggy_rt_calendar_words.json")


def _words():
    return json.loads(io.open(FIX, encoding="utf-8").read())


def test_reads_both_dates_and_total_from_real_screenshot():
    got = parse_round_trip_footer(_words())
    assert got["dep"] == (11, 16), got
    assert got["ret"] == (11, 19), got
    assert got["total"] == 747.0, got


def test_confirm_button_row_does_not_mask_footer():
    """把「确定」按钮那一行单独喂进去，必须读不到日期（证明它确实没这些词）。"""
    words = _words()
    lowest = max(w["y"] for w in words)
    only_bottom = [w for w in words if abs(w["y"] - lowest) <= 18]
    got = parse_round_trip_footer(only_bottom)
    assert got["dep"] is None and got["ret"] is None


# ---- merged from tests/test_r735_fliggy_h5_round_trip.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _src():
    return io.open(os.path.join(ROOT, "crawlers", "fliggy_h5.py"),
                   encoding="utf-8").read()


def _body_of_fetch():
    src = _src()
    i = src.index("def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_fetch_body_does_not_ignore_ret_date():
    """守卫：函数体里必须出现 ret_date 的显式处置（不能只写在签名上）。"""
    body = _body_of_fetch()
    assert "ret_date" in body.split(":", 1)[1], (
        "FliggyH5Crawler.fetch 的签名收了 ret_date，函数体却没用——"
        "传返程日会被静默当成单程，单程价冒充往返总价")


def test_round_trip_is_recorded_as_unsupported(tmp_path, monkeypatch):
    """行为：传 ret_date → 不查单程、落 unsupported、返回空。"""
    inst = FliggyH5Crawler({"user_data_dir": str(tmp_path)},
                         __import__("logging").getLogger("t"))
    called = []

    def _boom(*a, **k):
        called.append(a)
        raise AssertionError("不该发起单程查询")

    monkeypatch.setattr(inst, "_fetch_one", _boom)
    # 会话文件不存在也要先走到 ret_date 判断（否则测不到守卫）
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"], ret_date="2026-11-24")
    assert rows == [], rows
    assert called == [], "往返请求仍然发起了单程查询"
    st = [p for p in (inst.paths or []) if p.get("status") == "unsupported"]
    assert st, "没有把「往返不支持」落账：%s" % (inst.paths,)
    assert "往返" in str(st[0].get("detail") or "")


def test_oneway_still_works(tmp_path, monkeypatch):
    """负控：不传 ret_date 时照常按单程走（别把单程也拦掉）。"""
    inst = FliggyH5Crawler({"user_data_dir": str(tmp_path)},
                         __import__("logging").getLogger("t"))
    seen = []

    def _fake(fc, tc, date):
        seen.append(date)
        return []

    monkeypatch.setattr(inst, "_fetch_one", _fake)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    inst.fetch("SHA", "BJS", ["2026-11-20"])
    assert seen == ["2026-11-20"], seen
