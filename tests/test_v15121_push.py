# -*- coding: utf-8 -*-
"""r221 推送层立案（审校 P1×2 + P2×3）。

P1-1 日报两张连续图行无图注：`![走势]` 与 `![明细表]` 相邻零文字，
图例就近律在日报路径打折（主推送同场景有 `#### 📋 明细总表 深绿=…`）。
修法：明细表图行前补 `#### 📋 明细总表 {_TBL_HEAD_TIER}` 单源复用。

P2-5 图片 alt 词面分叉：日报 `![明细表]` vs 主推送 `![明细总表]`，
随 P1-1 一并收口同词。

P2-2 ⏱ 词面两路径分叉：主推送 `> ⏱22:41 …`（无空格）vs 日报
`> ⏱ 10/01 09:09`（带空格），日报并主推送口径。

P1-2 达标轮同航线多日期：达标日期小节不置顶——标题锚 10/06 达标、
正文 10/05（未达标）小节在前，最该看的信息在第二小节。修法：section
按「该日期有 hit」组内稳定排序（日期序不破坏，跨度标注按日期序算）。

P2-4 强提醒通道死链词：hits 行尾 `[打开携程](url)` 进 WinToast
_plain / 阿里云短信 _alert_body 剥壳后成「打开携程」不可点死文字。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15121_push.py
"""
import logging
import re

import pytest


# ==================== P1-1 / P2-5 / P2-2: 日报图注与词面 ====================

_ROUTE = {"from": "SHA", "to": "URC", "from_name": "上海",
          "to_name": "乌鲁木齐", "dates": ["2026-09-25"],
          "alert_direct": 2000, "alert_transfer": 1800,
          "transfer_arrival_max": "02:00"}
_FLIGHTS = [
    {"price": 2690, "transCity": "", "_platform": "qunar"},
    {"price": 2150, "transCity": "郑州", "depTime": "12:05",
     "arrTime": "00:35", "arrDate": "2026-09-26", "_platform": "ctrip"},
]


def _daily_cfg():
    return {"notifier": {"image_host": {"provider": "ghimg"}},
            "users": [{"name": "u", "routes": [_ROUTE],
                       "notifier": {"image_host": {"provider": "ghimg"}}}]}


def _build_daily(monkeypatch):
    import report as rep
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", "2026-09-25"):
                                       "http://x/t.png"})
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: _FLIGHTS)
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_chart", lambda p, c, lg: "http://x/t.png")
    sent = {}

    class FakeN:
        def send(self, title, desp="", **kw):
            sent["desp"] = desp
            return True

    ok = rep.build_and_push(_daily_cfg(), logging.getLogger("t"),
                            FakeN(), user="u")
    assert ok and sent.get("desp")
    return sent["desp"]


class TestDailyTableHeading:
    """P1-1：日报明细表图行前必须有档位图注（图例就近律）；
    P2-5：alt 词面与主推送同词「明细总表」。"""

    def test_heading_before_table_image(self, monkeypatch):
        d = _build_daily(monkeypatch)
        m = re.search(r"#### 📋 明细总表 \S+\n\n!\[明细总表\]\(",
                      d)
        assert m, d[-400:]

    def test_alt_word_unified(self, monkeypatch):
        d = _build_daily(monkeypatch)
        assert "![明细表](" not in d, "alt 词面与主推送分叉"
        assert "![明细总表](http://x/t.png)" in d

    def test_tier_word_from_single_source(self, monkeypatch):
        """图注档位词必须出自 _TBL_HEAD_TIER 单源（勿手抄词面）。"""
        from core.alerter import _TBL_HEAD_TIER
        d = _build_daily(monkeypatch)
        assert f"#### 📋 明细总表 {_TBL_HEAD_TIER}" in d

    def test_timestamp_line_no_space(self, monkeypatch):
        """P2-2：日报 ⏱ 行并主推送口径（⏱ 后不空格）。"""
        d = _build_daily(monkeypatch)
        assert "> ⏱" in d
        assert "> ⏱ " not in d, d[:120]


# ==================== P1-2: 达标日期小节置顶 ====================

class TestHitSectionFirst:
    """同航线多日期：达标日期 section 排前（组内稳定排序）。"""

    def _two_date_payload(self):
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route as _R
        a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
        r = _R(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
               alert_direct=1900, alert_transfer=1700)

        def _sec(date, direct_price):
            return {"date": date, "best_direct": None,
                    "best_transfer": None, "seen_plats": ["qunar"],
                    "best_direct": {"price": direct_price,
                                    "name": "MU8369",
                                    "depTime": "19:55",
                                    "arrTime": "01:25",
                                    "_platform": "qunar"}
                    if direct_price else None}

        # 列表序：10/05（1950 未达标）在前、10/06（1800 达标）在后
        return a._digest_payload(
            [(r, [_sec("2026-10-05", 1950), _sec("2026-10-06", 1800)])],
            fresh=True, with_tables=False)

    def test_hit_date_section_before_non_hit(self):
        p = self._two_date_payload()
        d = p["desp"]
        # 达标日期 10/06 得完整 KPI（￥1800 带 🎯），未达标 10/05
        # 降 mini 行（￥1950）——达标信息须在前
        i_hit = d.find("￥1800")
        i_plain = d.find("￥1950")
        assert i_hit != -1 and i_plain != -1
        assert i_hit < i_plain, "达标日期小节应排在未达标日期之前"
        assert "📍 10/05" in d, "未达标日期保留 mini 行不丢覆盖"

    def test_date_span_keeps_calendar_order(self):
        """小节标题日期跨度按日历序（重排后不得出现 10/06-10/05）。"""
        p = self._two_date_payload()
        assert "10/06-10/05" not in p["desp"]
        assert "10/05-10/06" in p["desp"]

    def test_stable_when_no_hits(self):
        """无达标轮：日期序原样（稳定排序零扰动）。"""
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route as _R
        a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
        r = _R(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
               alert_direct=1000, alert_transfer=900)

        def _sec(date):
            return {"date": date, "best_direct": {"price": 1950,
                    "name": "MU8369", "depTime": "19:55",
                    "arrTime": "01:25", "_platform": "qunar"},
                    "best_transfer": None, "seen_plats": ["qunar"]}

        p = a._digest_payload(
            [(r, [_sec("2026-10-05"), _sec("2026-10-06")])],
            fresh=False, with_tables=False)
        d = p["desp"]
        assert d.find("10/05") < d.find("10/06")


# ==================== P2-4: 强提醒通道死链词 ====================

_DESP_TAIL = ("> 🎯直飞 ￥1540　线￥1700　已达标\n\n"
              "> 乌→上 10/06 · 携程 · 低￥160 · "
              "[打开携程](https://flights.ctrip.com/x)")

class TestDeadJumpWord:
    """[打开XX](url) 进纯文本通道剥壳后是死文字，按动词前缀整段剥。"""

    def test_plaintoast_strips_jump_word(self):
        from core.notifier import WindowsToastNotifier as W
        out = W._plain(_DESP_TAIL, 500)
        assert "打开" not in out, out
        assert "低￥160" in out, "有效信息不得陪剥"

    def test_alert_body_strips_jump_word(self, monkeypatch):
        """短信路径：剥点在 AliyunAlertNotifier.send 内联层（ntfy 同吃
        _alert_body 但还原 URL 可点，剥离不得上移到共享层）。"""
        from unittest import mock
        import json as _json
        import core.notifier as N
        calls = []

        def _fake_post(url, **kw):
            calls.append(kw)
            return mock.Mock(status_code=200)

        monkeypatch.setattr(N.httpx, "post", _fake_post)
        ay = N.AliyunAlertNotifier(url="http://mock", user="u",
                                   password="p",
                                   logger=logging.getLogger("t"))
        assert ay.send("达标提醒", _DESP_TAIL) is True
        body = _json.loads(calls[0]["content"])["message"]
        assert "打开" not in body, body
        assert "低￥160" in body, body

    def test_link_without_open_verb_untouched(self):
        """非「打开」前缀链接（🔍 打开渠道查现价 以 emoji 打头、
        → 打开XX查价）不受整段剥影响（逐字面回归）。"""
        from core.notifier import WindowsToastNotifier as W
        out = W._plain("[🔍 打开渠道查现价](https://x)\n\n"
                       "[→ 打开同程查价](https://y)", 500)
        # 两者有既有 skip/查询语义兜底，但不得被新剥除改形成半截
        assert "https://" not in out
        assert "](http" not in out

    def test_only_jump_link_line_dropped(self):
        """整行只剩打开链接 → 行消失不留残段。"""
        from core.notifier import WindowsToastNotifier as W
        out = W._plain("正文行\n\n[打开携程](https://x)\n\n尾行", 500)
        assert "打开" not in out and "正文行" in out and "尾行" in out
