# -*- coding: utf-8 -*-
"""r236 推送层（Soldier 审查 P2-1 收口）：

单用户遗留 digest 路径（Alerter._push_digest）两处 send 出口绕过
sanitize_desp 单源——multi 主路径已在 _digest_payload 返回口消毒，
本路径 desp 同嵌爬虫自由文本（航班 name/经停城市），双标。收口后：
- 心跳尾出口（未达标简报）：send 点包裹
- 达标报告出口：desp 在存档前单点消毒，覆盖下游三消费端
  （详情页存档/_send_urgent→短信/主推）

 contamination 向量=爬虫自由文本字段（name 含尖括号的病态形态，
 sanitizer 只保证该形态不出 desp——渠道词表干净属暴露面防御）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r236_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402


def _route(ad=1900, at=1700):
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=ad, alert_transfer=at)


def _sect(direct_price, transfer_price=None, name="MU8369"):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        bd = {"price": direct_price, "name": name,
              "depTime": "19:55", "arrTime": "01:25", "_platform": "qunar"}
        s["best_direct"] = bd
        # top3 池同填（生产 _build_sections 恒填；图挂兜底 _top3_blocks
        # 明细行嵌 name——污染向量真实可达的载体）
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

    import logging as _lg
    return Alerter(_lg.getLogger("t236"), notifier=FakeN(), storage=None,
                   digest=True, user="t")


def _img_down(a, monkeypatch):
    """图挂兜底形态（与 test_push_digest_table_fail_fallback 同款）：
    表格图渲染失败走 _top3_blocks 文本兜底，确定性不渲染 PNG。"""
    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")


BAD = "MU<8369"


def test_digest_hit_branch_desp_sanitized(monkeypatch):
    """达标报告出口：desp 存档前单点消毒——主推与 _send_urgent
    （短信/电话下游）三消费端收到的都是消毒后文本。"""
    sent = []
    urgent = []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_archive_notify", lambda t, d, **kw: "")
    monkeypatch.setattr(a, "_send_urgent",
                        lambda t, d, hits, launch="": urgent.append((t, d))
                        or True)
    a._push_digest(_route(), _sect(1750, None, name=BAD))
    assert sent, "达标轮主推丢失"
    for _t, _d in sent:
        assert "<" not in _d and "＜" not in _d and "…" not in _d, _d[:300]
    for _t, _d in urgent:
        assert "<" not in _d and "＜" not in _d and "…" not in _d, _d[:300]
    assert any("MU8369" in _d for _t, _d in sent), "消毒不得误伤正常词面"


def test_digest_heartbeat_tail_desp_sanitized(monkeypatch):
    """未达标心跳尾出口：send 点包裹消毒（简报 desp 同嵌 name）。"""
    sent = []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_heartbeat_gate", lambda: True)
    a._push_digest(_route(), _sect(1950, None, name=BAD))
    assert sent, "心跳简报未发出"
    for _t, _d in sent:
        assert "<" not in _d and "＜" not in _d and "…" not in _d, _d[:300]
