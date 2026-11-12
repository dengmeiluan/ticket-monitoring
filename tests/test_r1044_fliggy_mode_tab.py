# -*- coding: utf-8 -*-
"""飞猪表单档位（单程/往返/多程）定位。

坐标取自 2026-11-05 真机 OCR 实测：三档在同一行 y≈576，
`单`x=189 `程`x=238 `往`x=581 `返`x=631 `多`x=976 `程`x=1024。
「单程」和「多程」**共用同一个「程」字**，所以定位必须按字符区间映射，
不能简单地"取包含程字的最左/最右词块"。
"""
from crawlers.app_fliggy import _mode_tap_xy


def _w(t, x, y=576, ww=44, hh=44):
    return {"t": t, "x": x, "y": y, "w": ww, "h": hh}


_TABS = [_w("单", 189), _w("程", 238),
         _w("往", 581), _w("返", 631),
         _w("多", 976), _w("程", 1024)]


def test_one_way_hits_dan_cheng():
    xy = _mode_tap_xy(_TABS, "单程")
    assert xy is not None
    # x 落在 单..程 两字之间（189..282）
    assert 189 <= xy[0] <= 282


def test_round_trip_hits_wang_fan():
    xy = _mode_tap_xy(_TABS, "往返")
    assert xy is not None
    assert 581 <= xy[0] <= 675


def test_multi_city_hits_duo_cheng():
    xy = _mode_tap_xy(_TABS, "多程")
    assert xy is not None
    assert 976 <= xy[0] <= 1068


def test_y_is_in_tab_row():
    assert _mode_tap_xy(_TABS, "往返")[1] == 598


def test_missing_label_returns_none():
    assert _mode_tap_xy(_TABS, "国际") is None


def test_out_of_band_words_ignored():
    """y 不在 400..800 的同名字不属于档位行（例如正文里的「单程」）。"""
    words = [_w("单", 100, y=1200), _w("程", 150, y=1200)]
    assert _mode_tap_xy(words, "单程") is None


def test_empty_words_returns_none():
    assert _mode_tap_xy([], "单程") is None
