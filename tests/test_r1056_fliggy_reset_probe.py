# -*- coding: utf-8 -*-
"""`scripts/fliggy_app_reset.py` 的状态判定：必须真的点一次机票模块。

2026-11-06 实测的误报：`--relaunch` 冷启后落在 `.home.HomeActivity`，
只看 Activity 会报「已恢复」；但拦截发生在**点「机票」宫格之后**
（点进去仍是 `ContainerActivity`）。首页是本地页面，永远能开。
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    p = os.path.join(ROOT, "scripts", "fliggy_app_reset.py")
    spec = importlib.util.spec_from_file_location("fliggy_app_reset", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


HOME_XML = (
    '<hierarchy><node text="酒店" bounds="[100,760][200,810]"/>'
    '<node text="机票" bounds="[360,760][410,810]"/>'
    # 顶部营销 banner 里的「机票」，y1 < 300，必须被排除
    '<node text="机票" bounds="[900,100][1000,150]"/>'
    "</hierarchy>")


class FakeDev:
    def __init__(self, act_after, xml=HOME_XML):
        self._act = ".home.HomeActivity"
        self._after = act_after
        self._xml = xml
        self.taps = []

    def current_activity(self):
        return self._act

    def dump(self):
        return self._xml

    def tap(self, x, y):
        self.taps.append((x, y))
        self._act = self._after
        return True


def test_blocked_when_flight_module_returns_container():
    m = _mod()
    d = FakeDev("com.taobao.trip/com.alibaba.wireless.security.open."
                "middletier.fc.ui.ContainerActivity")
    ok, why = m.flight_module_ok(d, wait_s=0)
    assert ok is False
    assert "仍被拦" in why, why


def test_ok_when_flight_form_reached():
    m = _mod()
    d = FakeDev("com.taobao.trip/.flutter.TripFlutterActivity")
    ok, why = m.flight_module_ok(d, wait_s=0)
    assert ok is True, why


def test_taps_lower_tile_not_banner():
    """必须点下半屏的宫格（y1>=300），不能点顶部营销 banner 里的「机票」。"""
    m = _mod()
    d = FakeDev("com.taobao.trip/.flutter.TripFlutterActivity")
    m.flight_module_ok(d, wait_s=0)
    assert d.taps, "没点任何东西"
    x, y = d.taps[0]
    assert y >= 700, "点到了顶部 banner：%s" % (d.taps,)


def test_home_without_tile_is_not_ok():
    m = _mod()
    d = FakeDev(".home.HomeActivity",
                xml='<hierarchy><node text="酒店" bounds="[0,700][100,800]"/>'
                    "</hierarchy>")
    ok, why = m.flight_module_ok(d, wait_s=0)
    assert ok is False
    assert "找不到" in why, why
