# -*- coding: utf-8 -*-
"""v1.5.81 推送层回归：desp 字节预算降级链两 P1 修复。

- P1-1 降级说明行压缩 ≤40 半角（原 47 半角直拼超手机行宽红线——
  守卫链设计律：这行的完整渲染形态谁负责 ≤40）
- P1-2 mini 地板档字节纳入预算累加（mini 落位前判 used+mb≤budget，
  防 24 航线场景 mini 总量顶穿 17900B 切点把尾部明细总表/@段切掉；
  mini 放不下时让位——@段与总表图是更高优先级载体，说明行已概括
  丢失面语义，钉钉硬限下「恒落位」让位于总字节闭合）

纯构建演练：_digest_payload 不发送；upload/render 全 mock，tmp 隔离。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v181_push.py -q
"""
import logging
import os
import sys
import unittest.mock as mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw  # noqa: E402
from core.models import Route  # noqa: E402
import report  # noqa: E402

FAKE_URL = "https://example.invalid/x.png"


def _mk_route(i):
    return Route(from_code=f"AX{i:02d}", from_name="乌鲁木齐",
                 to_code=f"BY{i:02d}", to_name="上海",
                 dates=["2026-10-09"],
                 alert_direct=1900, alert_transfer=1700)


def _mk_section(route, price_d=2400, price_t=2250):
    f0 = {"price": price_d, "name": "南航CZ6976", "code": "CZ6976",
          "depTime": "08:20", "arrTime": "13:40", "transCity": "",
          "depDate": "2026-10-09", "arrDate": "2026-10-09",
          "totalDuration": "5时20分", "cabin": "经济舱"}
    ft = dict(f0, price=price_t, transCity="郑州", layoverT="2:55",
              layoverM=175, transferBaggage="direct", arrTime="23:50",
              name="海航HU7849", code="HU7849")
    return {"date": "2026-10-09",
            "top_direct": [f0], "top_transfer": [ft],
            "best_direct": f0, "best_transfer": ft,
            "best_transfer_mkt": ft,
            "n_direct": 8, "n_transfer_ok": 2,
            "platform_mins": {"qunar": price_d, "ctrip": price_d + 10},
            "plat_top3": {"qunar": [f0],
                          "ctrip": [dict(f0, price=price_d + 10)]},
            "src_platform": "qunar", "pool": [f0, ft],
            "all_flights": [f0, ft],
            "seen_plats": ["qunar", "ctrip"], "xphans": []}


def _build_rs(n, n_dates=1):
    rs = []
    for i in range(n):
        r = _mk_route(i)
        secs = []
        for d in range(n_dates):
            s = _mk_section(r, price_d=2400 + i, price_t=2250 + i)
            s["date"] = f"2026-10-{9 + d:02d}"
            for f in [s["best_direct"], s["best_transfer"],
                      *s["top_direct"], *s["top_transfer"]]:
                f["depDate"] = s["date"]
                f["arrDate"] = s["date"]
            secs.append(s)
        r.dates = [s["date"] for s in secs]
        rs.append((r, secs))
    return rs


def _payload(rs, with_tables=False, charts=False):
    log = logging.getLogger("t181")
    log.disabled = True
    al = Alerter(log, digest=True, at_mobile="13800138000")
    with mock.patch.object(report, "upload_chart",
                           (lambda *a, **k: FAKE_URL)), \
         mock.patch.object(report, "recent_platform_flights",
                           lambda *a, **k: {}):
        return al._digest_payload(rs, with_tables=with_tables,
                                  with_charts=charts)


# ---- P1-1 降级说明行行宽 ----

def test_demoted_note_line_within_40(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(24))
    lines = [ln for ln in p["desp"].split("\n") if "航线较多" in ln]
    assert lines, "降级说明行未出现（场景应触发 demoted）"
    for ln in lines:
        w = _disp_dw(ln)
        assert w <= 40, f"说明行 {w} 半角超手机行宽红线: {ln}"


# ---- P1-2 mini 字节入预算：总字节闭合 + 尾部段不被顶掉 ----

def test_bytes_closed_with_tables(tmp_path, monkeypatch):
    """场景 F（24 航线未达标带图）：总字节 ≤17900 切点、明细总表段
    恒在场（降级目标不被自身地板档顶掉）。"""
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(24), with_tables=True, charts=True)
    desp = p["desp"]
    assert len(desp.encode("utf-8")) <= 17900, \
        f"desp {len(desp.encode('utf-8'))}B 顶穿 notifier 切点"
    assert "明细总表" in desp, "尾部明细总表段被顶掉"


def test_bytes_closed_with_hits_at_tail(tmp_path, monkeypatch):
    """场景 C（1 达标 + 29 未达标带图）：hits 在场 → @段恒落 desp 尾
    且总字节闭合（@段是电话触达载体，最不该被尾部截断）。"""
    monkeypatch.chdir(tmp_path)
    # 构造 1 个达标航线（价 1500 < 阈值 1900/1700），其余 29 未达标
    rs = _build_rs(1) + _build_rs(29)
    for _r, secs in rs[:1]:
        for s in secs:
            s["best_direct"] = dict(s["best_direct"], price=1500)
            s["best_transfer"] = dict(s["best_transfer"], price=1500)
    p = _payload(rs, with_tables=True, charts=True)
    desp = p["desp"]
    assert len(desp.encode("utf-8")) <= 17900, \
        f"desp {len(desp.encode('utf-8'))}B 顶穿 notifier 切点"
    assert desp.endswith("@13800138000 "), "@段未落 desp 尾"
    assert "明细总表" in desp, "尾部明细总表段被顶掉"


def test_bytes_closed_mini_pressure(tmp_path, monkeypatch):
    """场景 B（8 航线×3 日期，24 个 📍 mini 纯文本）：预算闭合。"""
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(8, n_dates=3))
    assert len(p["desp"].encode("utf-8")) <= 17900


def test_normal_scale_payload_intact(tmp_path, monkeypatch):
    """生产规模（2 航线带图）零降级回归：desp 结构不变、mini 不出现。"""
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(2), with_tables=True, charts=True)
    desp = p["desp"]
    assert "📍" not in desp, "生产规模不应触发 mini 降级"
    assert "明细总表" in desp
