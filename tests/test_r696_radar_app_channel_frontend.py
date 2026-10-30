# -*- coding: utf-8 -*-
"""r696：低价源接上后端后，前端必须也能勾到、能显示中文名。

r695 把 `app_qunar` 接进了特价雷达后端（`core/special_radar.py` 的
`_CHANNELS` 与分发）。前端此前三处写死五家浏览器渠道：

  * 渠道名表只列 5 家 → 「去哪儿 App」勾不到；
  * 配置页「查询渠道」芯片用 `SRX_PLAT_KEYS` → 同上；
  * 结果里 `SRX_PLATS[b.channel]` 取值 → App 渠道显示成裸 id。

**踩过的坑（真实回归）**：渠道名表若在模块顶层**立刻求值**，会撞 TDZ
（`SRX_PLATS` 声明在文件更靠后），整页脚本挂掉、界面停在「加载中…」，
而所有静态断言照样全绿。所以这里除了静态检查，还要真的用浏览器跑一遍。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _src():
    with open(WEBUI, encoding="utf-8") as f:
        return f.read()


def test_names_are_lazy_not_immediately_evaluated():
    """渠道名必须是**惰性**函数，不能在顶层立刻读 SRX_PLATS。"""
    s = _src()
    assert "function srxRadarName(" in s, "缺少惰性取名函数"
    assert "function srxRadarChannelKeys(" in s, "缺少惰性取键函数"
    assert "SRX_RADAR_NAMES=(function(){" not in s, \
        "渠道名表仍在顶层立刻求值（会撞 SRX_PLATS 的 TDZ，整页挂掉）"


def test_name_lookup_covers_app_channels():
    s = _src()
    i = s.index("function srxRadarName(")
    block = s[i:i + 360]
    assert "SRX_PLATS" in block and "APP_PLAT_NAME" in block, \
        "取名函数没有同时读两张表，App 渠道会露裸 id"


def test_config_chips_not_limited_to_browser_keys():
    s = _src()
    i = s.index("<b>查询渠道</b>")
    block = s[i:i + 900]
    assert "srxRadarChannelKeys()" in block, \
        "配置页芯片仍用 SRX_PLAT_KEYS，App 渠道勾不到"
    assert "SRX_PLAT_KEYS.map" not in block


def test_radar_chip_list_only_real_sources():
    """只有真有低价源的 App 渠道才列出来（智行还没接入，不列空开关）。"""
    s = _src()
    i = s.index("var SRX_RADAR_APP_KEYS=")
    block = s[i:i + 80]
    assert "app_qunar" in block, block
    assert "app_zhixing" not in block, \
        "智行低价源未接入，不该出现在可勾选清单里"


def test_no_bare_srx_plats_lookup_left():
    s = _src()
    assert not re.findall(r"SRX_PLATS\[b\.channel\]", s)
    assert not re.findall(r"SRX_RADAR_NAMES", s), \
        "仍有地方引用已删除的 SRX_RADAR_NAMES"


def test_radar_app_channels_known_to_both_tables():
    """后端有的雷达渠道，前端两张来源表都必须能给出名字。"""
    import core.special_radar as sr
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    known = set(BROWSER_CHANNELS) | set(APP_CHANNELS)
    for ch in sr._CHANNELS:
        assert ch in known, "%s 后端有、前端两张表都没有" % ch
