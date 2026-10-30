# -*- coding: utf-8 -*-
"""r242 推送层（审校 Minor-1/Minor-3 收口）：

Minor-1：_fmt_flight_line 价格词面裸 f['price']——float 价直达产
「￥12345.0」且 bare 地板档 42/40 超预算，现靠上游两道取整门远程
兜着（alerter 取整门/report 同门）；词面 :.0f 单源自守消除守卫离位
（LESSONS 十九§2：行宽预算的单位是最终渲染整行）。

Minor-3：title 不经 sanitize_desp（r236 收口只覆盖 desp 的双标
残留）——title 载体=route 配置自由文本+数字词面；渠道自由文本
经电话/短信 ay_msg（name/transCity 进 TTS 词面）同样直出。收口：
payload title/心跳 send/旧版 push send + _send_urgent 电话词面。
send() 协议面不动（LESSONS 二十二§2）；消毒是构造形态选择，
与单发零重试铁律无涉。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r242_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw  # noqa: E402


# ---- Minor-1：价格词面单源自守 ----

def test_fmt_flight_line_float_price_wording():
    """float 价直达（上游取整门被绕行的防御纵深）：词面不得出
    「￥12345.0」；正常 int 价词面不变。"""
    f = {"price": 12345.0, "name": "MU8369", "depTime": "08:30",
         "arrTime": "11:20"}
    line = Alerter._fmt_flight_line(f, idx=1)
    assert "￥12345.0" not in line, line
    assert "￥12345" in line, line
    f2 = dict(f, price=900)
    assert "￥900" in Alerter._fmt_flight_line(f2, idx=1)


def test_fmt_flight_line_bare_floor_within_budget():
    """bare 地板档（超长输入强制逐字截后）行宽恒 ≤40：float 价的
    「.0」尾巴曾把地板档撑到 42/40（审校直调实证）。"""
    f = {"price": 12345.0,
         "name": "九元航空AQ1111/长龙航GJ8888超长联程显示名",
         "depTime": "08:30", "arrTime": "11:20",
         "transCity": "郑州", "crossDayDesc": "+1天",
         "stopCitys": "兰州;西宁"}
    line = Alerter._fmt_flight_line(f)
    assert _disp_dw(line) <= 40, (line, _disp_dw(line))
    assert ".0" not in line, line


# ---- Minor-3：title/电话词面消毒 ----

def _route():
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上<海",
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
    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    return Alerter(logging.getLogger("t242"), notifier=FakeN(),
                   storage=None, digest=True, user="t")


def _img_down(a, monkeypatch):
    """图挂兜底形态：表格图渲染失败走文本兜底，确定性不渲染 PNG。"""
    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")


def test_digest_hit_branch_title_sanitized(monkeypatch):
    """达标报告 title 出口：route 配置名是自由文本，与 desp 同律
    （r236 只收了 desp）；消毒后 title 进存档页/主推/urgent 全链。"""
    sent, urgent = [], []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_archive_notify", lambda t, d, **kw: "")
    monkeypatch.setattr(a, "_send_urgent",
                        lambda t, d, hits, launch="": urgent.append((t, d))
                        or True)
    a._push_digest(_route(), _sect(1750, None, name="MU8369"))
    assert sent, "达标轮主推丢失"
    for _t, _d in sent:
        assert "<" not in _t and "＜" not in _t and "…" not in _t, _t
        assert "＜" not in _d, _d[:200]
    assert any("上海" in _t for _t, _d in sent), "消毒不得误伤正常词面"


def test_digest_heartbeat_tail_title_sanitized(monkeypatch):
    """未达标心跳尾出口：title 同律消毒。"""
    sent = []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_heartbeat_gate", lambda: True)
    a._push_digest(_route(), _sect(1950, None))
    assert sent, "心跳简报未发出"
    for _t, _d in sent:
        assert "<" not in _t and "＜" not in _t and "…" not in _t, _t


def test_urgent_aliyun_wording_sanitized(monkeypatch):
    """电话/短信词面：渠道自由文本 name/transCity 直进 TTS 词面，
    构造端同律剥除（音频把尖括号读出来的形态不可接受）。"""
    sent = []
    a = _alerter([])

    class FakeAliyun:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    import core.notifier as _N
    monkeypatch.setattr(_N, "AliyunAlertNotifier", FakeAliyun)
    a.urgent_notifier = [FakeAliyun()]
    r0 = _route()
    f0 = {"name": "MU<8369", "depTime": "08:30", "arrTime": "11:20",
          "price": 1750, "_platform": "qunar", "transCity": "郑<州"}
    hits = [(r0, {"date": "2026-09-25"}, "直飞", f0, 1900)]
    a._send_urgent("T", "D", hits)
    assert sent, "电话通道未触发"
    for _t, _d in sent:
        assert "<" not in _t and "<" not in _d, (_t, _d)
    assert "MU8369" in _d and "郑州" in sent[0][1], "消毒不得误伤正常词面"
