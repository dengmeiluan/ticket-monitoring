# -*- coding: utf-8 -*-
"""r282 tuniu 准点率占位档扩守卫：恒「20」之外新增「50」「56」。

渠道侧变更实录：占位形态不是静止的——10-10 会话恢复后上游把
未上线准点数据的航班默认填充从「20%」换为低档带「50%/56%」
（航班级恒挂：50 档 101 次采样仅 2 个航班、56 档亦 2 个，跨全窗
恒定；伴随矛盾：50 档 avgDelay 恒 9 分钟——9min 平均延误与 50%
准点率语义互斥，56 档 avgDelay 全缺；同指纹对照：ctrip 全 100；
历史值域：10-04~07 健康带 70-100 无此二值，挡它零误杀）。
「不在历史真值域」是占位守卫的零误杀硬证据；63 档 avgDelay
25/36 有分布、ctrip=90 渠道间正常差——真值维持不挡。
渠道值域恢复多值（50/56 带 avgDelay 背离消除）即撤守卫。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r282_tuniu_prate.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler, _prate


def test_placeholder_new_tiers_empty():
    # 新占位档 50/56 置空（旧守卫只挡 20 时穿透入库）
    assert _prate("50") == ""
    assert _prate("56") == ""
    assert _prate("50%") == ""
    assert _prate("56.0") == ""


def test_legacy_placeholder_still_empty():
    assert _prate("20") == ""
    assert _prate("20.0") == ""
    assert _prate("") == ""
    assert _prate(None) == ""


def test_real_value_band_untouched():
    # 真值带不误杀：63 档（avgDelay 有分布）与健康带全保留
    for v in ("63", "73", "86", "90", "93", "96", "100"):
        assert _prate(v) == v, v


def test_offers_to_flights_drops_new_placeholder_key():
    # 生产构造基座（同 test_v15104_fields._TUINU_OFFER 形态——
    # 缺必需键的 offer 会被上游守卫整行丢弃，断言对空输出恒真）
    o = {"airline": "东航", "flight_no": "MU137",
         "depart_time": "14:40", "arrive_time": "19:10",
         "price": 1750, "dep_date": "2027-02-13",
         "arr_date": "2027-02-13", "flight_time": 270,
         "cabin": "经济舱", "layover": "", "stopPoints": [],
         "onTimeRate": "50"}
    fs = TuniuCrawler._offers_to_flights([o])
    assert fs and "prate" not in fs[0]
