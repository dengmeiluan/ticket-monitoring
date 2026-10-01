# -*- coding: utf-8 -*-
"""r247 推送回归：_fmt_brief 价格词面浮点收口。

审校立案（r247 推送 P3→本轮收口）：_fmt_brief 全链 8 处
`￥{f['price']}` 裸插值——r242 Minor-1 家族残留（_fmt_flight_line
已 `:.0f` 单源自守，本函数漏收）。float 价直达曾产「￥12345.0」，
地板档实插 10/8 超预算；生产双取整门挡住不可达，但守卫离渲染点
越远越容易漏算（LESSONS 十九§2），词面单源自守同律跟进。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r247_push.py -q
"""
from core.alerter import Alerter, _disp_dw

# v173 同源夹具（int 价形态既有钉不重复），此处只加 float 形态
_F_TRANS = {"price": 2280, "name": "南航CZ6949", "transCity": "兰州",
            "layoverT": "6:45", "depTime": "09:55", "arrTime": "00:25",
            "crossDayDesc": "+1天"}
_F_DIRECT = {"price": 2310, "name": "春秋9C6928", "depTime": "23:05",
             "arrTime": "01:15", "crossDayDesc": "+1天"}


class TestFmtBriefPriceNoFloatArtifact:
    """float 价输入：全部档位价格词面 :.0f 自守，零小数尾渣。"""

    def test_floor_tier_float_price_rounded(self):
        """地板档（budget=6）：float 价产 ￥2281 而非 ￥2280.7
        （旧代码裸插值实锤形态）；宽度随词面收口回落预算内。"""
        brief = Alerter._fmt_brief(dict(_F_TRANS, price=2280.7), budget=6)
        assert brief == "￥2281", repr(brief)
        assert _disp_dw(brief) <= 6 + 1  # ￥+4 数字（1.125 校准）≈5.5

    def test_first_tier_float_price_rounded(self):
        """首档（默认 budget=40）：直飞行价格词面无小数尾渣。"""
        brief = Alerter._fmt_brief(dict(_F_DIRECT, price=2310.4))
        assert "￥2310" in brief
        assert "2310.4" not in brief and "2310.0" not in brief

    def test_transfer_mid_tier_float_price_rounded(self):
        """中转中档（budget=28 落 fallback[1]）：价格词面同收口。"""
        brief = Alerter._fmt_brief(dict(_F_TRANS, price=2280.5), budget=28)
        assert "￥2280" in brief or "￥2281" in brief
        assert "2280.5" not in brief

    def test_int_price_unchanged(self):
        """int 价（生产常态，夹具既有形态）：词面逐字不变。"""
        assert Alerter._fmt_brief(dict(_F_TRANS), budget=6) == "￥2280"


# ---- Soldier P3-3：未达标 title 裸插值家族收口末点 ----

def _route():
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=1900, alert_transfer=1700)


def _sect(direct_price, transfer_price=None, name="MU8369"):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        bd = {"price": direct_price, "name": name,
              "depTime": "19:55", "arrTime": "01:25", "_platform": "qunar"}
        s["best_direct"] = bd
        s["top_direct"] = [bd]
        s["top_transfer"] = []
        s["platform_mins"] = {"qunar": direct_price}
        s["plat_top3"] = {"qunar": [bd]}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
    return [s]


def _alerter(sent):
    import logging as _lg

    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    return Alerter(_lg.getLogger("t247"), notifier=FakeN(),
                   storage=None, digest=True, user="t")


def test_miss_title_float_price_rounded(monkeypatch):
    """未达标 title 价格词面 :.0f 自守（_fmt_brief/_fmt_flight_line
    同族收口末点）：float 价直达曾产「直飞￥1950.7·中转￥1750.3」；
    生产双取整门挡住不可达（纵深防御），int 价词面逐字不变。"""
    sent = []
    a = _alerter(sent)

    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")
    monkeypatch.setattr(a, "_heartbeat_gate", lambda: True)
    a._push_digest(_route(), _sect(1950.7, 1750.3))
    assert sent, "未达标心跳未发出"
    for _t, _d in sent:
        assert "1950.7" not in _t, _t
        assert "1750.3" not in _t, _t
        assert "￥1951" in _t and "￥1750" in _t, _t


def test_miss_title_int_price_unchanged(monkeypatch):
    """int 价（生产常态）：title 词面与旧行为逐字一致（防收口误伤）。"""
    sent = []
    a = _alerter(sent)

    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")
    monkeypatch.setattr(a, "_heartbeat_gate", lambda: True)
    a._push_digest(_route(), _sect(1950, 1750))
    assert sent, "未达标心跳未发出"
    assert any("直飞￥1950·中转￥1750" in _t for _t, _d in sent), \
        [t for t, _ in sent]

