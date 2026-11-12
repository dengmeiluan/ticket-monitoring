# -*- coding: utf-8 -*-
"""r1063 T45：App 定位固定在上海浦东世博片区。

风控最便宜的一条矛盾是「**IP 在 A 地、时区在 B 地、GPS 在 C 地**」。本仓早就有
`crawler.geo`（时区/语言）与出口 IP 对齐，但 **App 通路的 GPS 从没设过**——Android
模拟器出厂定位是加州山景城（Google 总部），一家上海出发的机票 App 读到设备在
加州，比 UA 写得花不花哨危险得多。

做法：`adb emu geo fix <经度> <纬度> <海拔>`（所有 Android 模拟器通用）
+ `settings put secure location_mode 3`；两步幂等，每次开查前重打一遍
（模拟器重启会复位）。**失败绝不阻断采集。**
"""
import io
import os

from core.android import geo


def test_default_coords_are_shanghai_expo():
    pos = geo.coords_from(None)
    assert pos["name"] == "上海浦东世博片区"
    # 世博片区（中华艺术宫一带）——落在上海行政范围内，且不是出厂默认的加州
    assert 30.9 < pos["lat"] < 31.5, pos
    assert 121.2 < pos["lon"] < 121.8, pos


def test_config_can_override_and_disable():
    pos = geo.coords_from({"android": {"geo": {"lat": 31.2, "lon": 121.5,
                                               "name": "自定义"}}})
    assert (pos["lat"], pos["lon"], pos["name"]) == (31.2, 121.5, "自定义")
    assert geo.coords_from({"android": {"geo": {"enabled": False}}}) == {}


def test_bad_coords_fall_back_to_default():
    pos = geo.coords_from({"android": {"geo": {"lat": "abc", "lon": ""}}})
    assert pos["lat"] == geo.SHANGHAI_EXPO["lat"], pos


class _FakeDev:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def sh(self, *args, **kw):
        self.calls.append(" ".join(str(a) for a in args))
        if self.fail:
            raise RuntimeError("adb 挂了")
        return "OK"


def test_fix_sends_lon_lat_order_and_enables_providers():
    """`geo fix` 是**经度在前**（历史顺序），写反了会钉到海里。"""
    dev = _FakeDev()
    rep = geo.fix(dev, {"android": {"geo": {"enabled": True}}})
    assert rep["ok"] is True, rep
    joined = " | ".join(dev.calls)
    assert "geo fix 121.4921 31.1874" in joined, joined
    assert "location_mode 3" in joined, joined


def test_fix_never_blocks_when_adb_fails():
    dev = _FakeDev(fail=True)
    rep = geo.fix(dev, None)
    assert rep["ok"] is False
    assert rep.get("detail")


def test_disabled_means_no_device_traffic():
    dev = _FakeDev()
    rep = geo.fix(dev, {"android": {"geo": {"enabled": False}}})
    assert rep.get("skipped") is True
    assert dev.calls == [], dev.calls


def test_app_base_pins_geo_before_each_query():
    """接线钉子：设备准备流程里必须有 ensure_geo（漏了等于没有定位）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "app_base.py"),
        encoding="utf-8").read()
    assert "def ensure_geo(self, dev)" in src
    assert "self.ensure_geo(dev)" in src
    i = src.index("self._refresh_vendor_props(dev)")
    j = src.index("self.ensure_geo(dev)")
    assert abs(j - i) < 400, "ensure_geo 没挂在设备准备那段里"


def test_example_config_ships_the_geo_block():
    """新装即带（零配置）：示例配置里必须有 android.geo。"""
    import yaml
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "config.example.yaml")
    cfg = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    g = (cfg.get("android") or {}).get("geo") or {}
    assert g.get("enabled") is True, g
    assert g.get("lat") and g.get("lon"), g
