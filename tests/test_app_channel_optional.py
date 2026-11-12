# -*- coding: utf-8 -*-
"""App 渠道可选性：不启用时不得出现在任何"必须存在"的集合里。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channel_alert, health, health_diag, pacing
from crawlers import APP_CHANNELS, REGISTRY


def test_app_channel_registered():
    assert "app_zhixing" in REGISTRY


def test_app_channels_not_in_browser_platform_lists():
    """浏览器渠道列表保持 5 个——它是"内置渠道"的定义，不是"全部渠道"。"""
    for mod in (health, pacing, health_diag):
        for plat in APP_CHANNELS:
            assert plat not in mod.PLATFORMS, (mod.__name__, plat)


def test_cn_names_cover_app_channels():
    """中文名必须有，否则界面显示裸 id。"""
    for plat in APP_CHANNELS:
        assert plat in health_diag.CN
        assert plat in channel_alert.CN


def test_health_regexes_accept_app_channels():
    """健康解析靠日志行，正则不认就等于整条渠道在时间线里消失。"""
    import re

    line = "[app_zhixing] 开始抓取 SHA->BJS 日期=['2026-10-29']"
    m = health._PLAT.match(line)
    assert m and m.group(1) == "app_zhixing", health._PLAT.pattern

    sent = "[解析哨兵] app_zhixing 最低价 ￥450"
    m2 = health._SENT.match(sent)
    assert m2 and m2.group(1) == "app_zhixing", health._SENT.pattern


def test_health_regexes_still_accept_browser_channels():
    """扩正则不能让老的 5 个失配。"""
    for plat in health.PLATFORMS:
        assert health._PLAT.match(f"[{plat}] 开始抓取 A->B")
        assert health._SENT.match(f"[解析哨兵] {plat} 最低价 ￥100")


def test_pacing_provides_cadence_for_app_channel():
    """节流要能给出 App 渠道的节奏 key，否则调度取值会退化。"""
    rules = pacing.parse_pacing({})
    cad = rules.get("cadence")
    assert isinstance(cad, dict), cad
    for plat in APP_CHANNELS:
        assert plat in cad, sorted(cad)
