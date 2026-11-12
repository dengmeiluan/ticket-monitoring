# -*- coding: utf-8 -*-
"""r325 国际行推送链集成钉：元素→normalize→推送池的正确性闭环。

- 时区修正穿透：爬虫 naive 渠道时长（双端本地时刻差）进
  _flights_from_extra(normalize) 后被 tz_dep/tz_arr 修正为真时长
  （本钉用 15h 时区差的 PVG→JFK 样本——修正失灵即推送行时长错
  ±15h，这是国际档最贵的静默错误）；
- 免税垫：国际行即使是 fliggy 平台也不加 FLIGGY_TAX_PAD（含税口径）；
- 到达窗泛化：国际 +2 天达 01:00 过线 / 08:00 出线，国内 +2 天行为
  逐字节不变。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_alerter.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import (Alerter, _flights_from_extra,  # noqa: E402
                          _qual_price, FLIGGY_TAX_PAD)


def _intl_row(**over):
    # PVG(+480) 10:00 → JFK(-300 洛杉矶? no 纽约 EDT -240 用 10 月)：
    # 用东行重灾区样本：PVG 10:00 → JFK 15:50 同日本地（EDT -240）
    # naive=350 分；真时长=350-(−240−480)=1070 分（17时50分）
    f = {"intl": 1, "name": "东航MU587", "code": "MU587",
         "depTime": "10:00", "arrTime": "15:50",
         "depDate": "2026-10-17", "arrDate": "2026-10-17",
         "tz_dep": 480, "tz_arr": -240,
         "totalDuration": "17时50分", "price": 6800}
    f.update(over)
    return f


def test_flights_from_extra_corrects_tz_duration():
    rows = _flights_from_extra([_intl_row()], "2026-10-17", "ctrip")
    assert len(rows) == 1
    # naive 渠道值 5时50分=350 被修正为真值 1070（时区差 720 分）
    assert rows[0]["durM"] == 1070
    assert rows[0]["crossDayN"] == 0


def test_qual_price_intl_no_fliggy_pad():
    row = dict(_intl_row(), _platform="fliggy")
    assert _qual_price(row) == 6800.0
    dom = {"price": 6800, "_platform": "fliggy"}
    assert _qual_price(dom) == 6800.0 + FLIGGY_TAX_PAD   # 国内档照旧垫税


def test_arrival_ok_intl_multi_day_window():
    # 国际 +2 天凌晨达：过「次日 02:00 前」语义（到达当地时刻 ≤ deadline）
    f2 = dict(_intl_row(arrTime="01:10", arrDate="2026-10-19"))
    f2.pop("crossDayDesc", None)
    assert Alerter._arrival_ok(f2, "02:00") is True
    f8 = dict(_intl_row(arrTime="08:00", arrDate="2026-10-19"))
    assert Alerter._arrival_ok(f8, "02:00") is False
    # 国内 +2 天到达仍出线（行为逐字节不变锚：仅次日形态放行）
    d = {"depDate": "2026-10-17", "arrDate": "2026-10-19",
         "arrTime": "01:10", "crossDayDesc": "+2天"}
    assert Alerter._arrival_ok(d, "02:00") is False


def test_flights_from_extra_intl_row_survives_pool():
    # 国际行带 transCity 走中转池、无 transCity 走直飞池——键不缺不歧义
    rows = _flights_from_extra(
        [_intl_row(), _intl_row(code="MU587/NH9", transCity="东京",
                                arrDate="2026-10-18", arrTime="18:00",
                                tz_arr=540)],
        "2026-10-17", "ctrip")
    assert len(rows) == 2
    assert not rows[0].get("transCity")
    assert rows[1]["transCity"] == "东京"
    # 东行跨天 +1（NRT +540）：naive 2 天形修正仍由日期差承载
    assert rows[1]["crossDayN"] == 1


_LOG = logging.getLogger("t_intl_alerter")   # noqa: F841 保导入形一致


# ---- R45 _stale_sane 国际时区校正钉 ----

def test_stale_sane_tz_corrected_intl_row():
    """国际行 totalDuration 校验必须做时区校正：SHA→NRT dep 02:20(CST)
    arr 06:20(JST) 时长「3小时」为真值（真elapsed），朴素钟面和
    05:20 对 06:20 误判 60 分钟差拒杀（R45 修复）。"""
    f = {"depTime": "02:20", "arrTime": "06:20",
         "totalDuration": "3小时", "tz_dep": 480, "tz_arr": 540}
    assert Alerter._stale_sane(f) is True
    # 无 tz 键的国际行（日历通道无时刻本就不进此门）：朴素口径不回归
    f2 = {"depTime": "09:30", "arrTime": "12:30", "totalDuration": "3小时"}
    assert Alerter._stale_sane(f2) is True
    # 真错行仍拦（tz 校正后差仍超 10 分钟）
    f3 = {"depTime": "02:20", "arrTime": "08:20",
          "totalDuration": "3小时", "tz_dep": 480, "tz_arr": 540}
    assert Alerter._stale_sane(f3) is False
