# -*- coding: utf-8 -*-
"""用户内特价雷达 UI：条件、日历、最低价明细入口。"""
import webui


def test_radar_card_and_config_are_user_scoped():
    src = webui.PAGE
    for needle in ("id=\"spRadarCard\"", "id=\"spRadarFrom\"", "id=\"spRadarTo\"",
                   "id=\"spRadarStart\"", "id=\"spRadarEnd\"", "id=\"spRadarChannels\"",
                   "srxRadarRun", "srxRadarLoadFromUser", "srxRadarDetail",
                   "setRadarCh", "data-rad=\"start\""):
        assert needle in src, needle
    assert "glab('D','关注航班'" in src
    assert "glab('E','特价雷达'" in src
    assert 'data-p="watch"' not in src, "全局关注航班导航应已移入用户卡"
    # 监控态 S.users 不含配置扩展键：雷达条件必须回 /api/config 读用户卡
    assert "function srxRadarCfgUser(name)" in src
    assert "fetch('/api/config',{cache:'no-store'})" in src
    # 就地配置：关注航班在用户卡内开抽屉，雷达从关注航线选择并内联查价
    assert 'id="uwatch-' in src
    assert 'id="cfgWatchPark"' in src
    assert "function radarCfgRun(i,btn)" in src
    assert "function radarCfgLoadLinks(i)" in src
    assert "官方特价频道" in src
    assert "关注航线" in src
    assert "srxPlatIcon(p)" in src


def test_radar_lowest_jumps_to_real_probe():
    src = webui.PAGE
    assert "srxTaskStart({from:q.from,to:to,date:date,plats:plats})" in src
    assert "日历/榜单价只作发现" in src
