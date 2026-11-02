# -*- coding: utf-8 -*-
"""r286 推送审校落地五案（TDD 先行，审校报告 _scratch/r286_push_report.md）：

P2-1 hits 头行缺「联程名剥档」——「海南航空 HU7849/春秋9C8845」实宽
    45/40 穿过双名档直落地板（head 无航班号=身份净失，KPI 行2 与
    _fmt_flight_line 同族剥档均在、此处漏网）。修法：纯联程形态（无
    「｜」有「/」）补剥「/」后段档保首段（首名+首码 33.25 恒可落位）。
    档序按三十一§5：剥名档（双名形态可达）→ 剥联程档（纯联程可达）→
    地板，无死档。
P2-2 总表图 compare 组日期跨度倒挂——达标置前重排后 c_span 用
    sections[0]/[-1] 原序产出「10/06-10/05」；同函数 d_span 已按日历
    序修正（ds_all），c_span 是同族漏网。修法：c_span 复用同函数上文
    ds_all（排序日期首尾）。
P3-1 日报图挂兜底静态标题恰满 40/40 零缓冲——任何一字追加即窄屏折行
    断点失控（URGENT_FAIL_NOTE 同病先例）。修法：词面减一字得缓冲。
P3-2 钉钉异常分支落账 desp 与「账本=实收形态」纪律不一致——成功分支
    落 text（截断产物）而网络异常分支落 desp 原文，幽灵送达轮三者
    对不上。修法：异常分支同落 text。
P3-3 _digest_payload 对空节 (route, []) 无防御——L1981 IndexError，
    契约只在调用点纪律无实现侧防御。修法：入口 continue 防+注释声明。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r286_push.py -q
"""
import json
import logging
import os
import sys
import datetime as dt

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.alerter import Alerter  # noqa: E402
from core.models import Route, FlightPrice  # noqa: E402


def _fp(price, name, dpt, art, trans="", cross="", plat="qunar",
        dep="2026-10-05"):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else (2 if cross == "+2天" else 0)
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep,
            "arrDate": str(d0 + dt.timedelta(days=days)),
            "transCity": trans, "crossDayDesc": cross,
            "totalDuration": "6时", "_platform": plat}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _mk_alerter():
    class FakeN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            return True
    return Alerter(logging.getLogger("r286"), notifier=FakeN(),
                   storage=None, digest=True, storm_repeat=1, user="演练")


def _one_route_built(a, rows, dep="2026-10-05", th_direct=1900,
                     th_transfer=2600):
    r = Route(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=[dep], alert_direct=th_direct,
              alert_transfer=th_transfer)
    return r, [(r, a._build_sections(r, _ps(rows, "SHA", "URC", dep)))]


# ---------- P2-1: hits 头行联程剥档 ----------

def test_hits_head_codeshare_drops_tail_segment():
    """纯联程形态（无「｜」有「/」）：hits 头行保「首名+首码」剥
    「/」后段（红态=45/40 穿链直落地板，航班号整体消失——head 与
    seg 行均无码，命中行身份仅剩时刻+经停）。"""
    a = _mk_alerter()
    r, built = _one_route_built(a, [
        _fp(2590, "海南航空 HU7849/春秋9C8845", "08:30", "13:50",
            trans="郑州")])
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    assert "海南航空 HU7849" in pv["desp"], "首名+首码未保住（剥档缺席）"
    # head 行（> 🔥 开头）剥「/」后段；后段码仅从 head 剥失——KPI 行2
    # 剥首段档与总表图仍承载全码，seg 行只有时刻/跨天/经停无码
    head = next(ln for ln in pv["desp"].splitlines() if ln.startswith("> 🔥"))
    assert "春秋9C8845" not in head, \
        "「/」后段未剥（整名直落地板=航班号消失）"
    # 头行行宽恒达标（_disp_dw 剥链接量渲染宽）
    from core.alerter import _disp_dw
    assert _disp_dw(head) <= 40, "头行 %0.1f/40 超宽" % _disp_dw(head)


def test_hits_head_dual_name_unchanged():
    """双名形态（有「｜」）：既有剥名档行为零变化（保「金鹏航空
    Y87519」全段，联程档不插入不抢档——混合形态剥名档已保名+码）。"""
    a = _mk_alerter()
    r, built = _one_route_built(a, [
        _fp(2590, "新海航｜金鹏航空 Y87519", "08:30", "13:50",
            trans="郑州")])
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    assert "金鹏航空 Y87519" in pv["desp"], "双名剥名档行为被扰动"


# ---------- P2-2: compare 组日期跨度日历序 ----------

def test_compare_span_calendar_order():
    """多日期航线达标在后日期（重排后 sections[0]=后日期）：compare
    组头日期跨度按日历序「10/05-10/06」（红态=原序「10/06-10/05」
    倒挂直落总表图组头）。直调 _flights_table_md_multi，monkeypatch
    render/upload 截获 rows（不真渲染不真上传）。"""
    import report as report_mod
    a = _mk_alerter()
    r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
              to_name="上海", dates=["2026-10-05", "2026-10-06"],
              alert_direct=1600, alert_transfer=0)
    hit_a = _fp(1580, "南航CZ6993", "21:15", "23:55", dep="2026-10-06",
                plat="ctrip")
    hit_b = _fp(1650, "南航CZ6993", "21:15", "23:55", dep="2026-10-06",
                plat="qunar")   # 同班跨渠道（_fp_cands 指纹组需 ≥2 渠道）
    other = _fp(1690, "东航MU8370", "09:00", "14:10", dep="2026-10-05")
    s_hit = {"date": "2026-10-06", "pool": [dict(hit_a), dict(hit_b)],
             "top_direct": [dict(hit_a)], "top_transfer": [],
             "best_direct": dict(hit_a), "best_transfer": None}
    s_pre = {"date": "2026-10-05", "pool": [dict(other)],
             "top_direct": [dict(other)], "top_transfer": [],
             "best_direct": dict(other), "best_transfer": None}
    ordered = [s_hit, s_pre]   # 达标置前重排语义（_digest_payload ordered）
    captured = {}

    def fake_render(rows, title, out_png, summary=None, stamp_note="",
                    ops_notes=None):
        captured["rows"] = rows
        return None

    orig_render = report_mod.render_flights_table
    orig_upload = report_mod.upload_chart
    report_mod.render_flights_table = fake_render
    report_mod.upload_chart = lambda *a, **k: "http://127.0.0.1/fake.png"
    try:
        a._flights_table_md_multi([(r, ordered)])
    finally:
        report_mod.render_flights_table = orig_render
        report_mod.upload_chart = orig_upload
    assert "rows" in captured, "总表 rows 未产出（render 未被调？）"
    cmp_labels = [row[2] for row in captured["rows"]
                  if len(row) >= 3 and str(row[2]).startswith("同班比价")]
    assert cmp_labels, "compare 组缺席（候选未分组？）"
    lbl = cmp_labels[0]
    assert "10/05-10/06" in lbl, "组头日期非日历序: %s" % lbl
    assert "10/06-10/05" not in lbl, "组头日期倒挂在场"


# ---------- P3-1: 日报兜底标题零缓冲 ----------

def test_daily_top_fallback_headline_has_headroom():
    """图挂兜底标题不再恰满 40/40（红态=纯 CJK 恰卡线零缓冲，
    任何一字追加即窄屏折行断点失控）；正文行恒 ≤40。"""
    from report import _daily_top_fallback
    from core.alerter import _disp_dw
    row = _fp(1580, "南航CZ6993", "21:15", "23:55")
    row["_qual"] = False
    out = _daily_top_fallback([row], [])
    lines = [ln for ln in out.split("\n\n") if ln.strip()]
    assert lines, "兜底输出为空"
    for ln in lines:
        assert _disp_dw(ln) <= 38, \
            "行 %0.1f/40 仍零缓冲: %s" % (_disp_dw(ln), ln[:40])


# ---------- P3-2: 钉钉异常分支落账实收形态 ----------

def test_dingtalk_exception_ledger_records_sent_text(monkeypatch):
    """网络异常轮（读响应前断连=幽灵送达场景）账本落 text 实收形态
    （红态=落 desp 原文，截断轮三者对不上）。构造超长 desp 触发截断，
    monkeypatch httpx.post 抛异常（不真连），读重定向账本最后一行。"""
    import core.notifier as nm
    ding = nm.DingTalkNotifier("http://127.0.0.1:9/hook",
                               logging.getLogger("r286ding"))
    tail = "TAILMARK_r286_excep_branch"
    desp = "正文 " + "X" * 20000 + tail   # >18000B 触发截断
    monkeypatch.setattr(
        nm.httpx, "post",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ding.send("t", desp, launch="") is False
    path = os.environ.get("PUSH_HISTORY_FILE")
    assert path and os.path.exists(path), "账本重定向缺席"
    lines = [ln for ln in open(path, encoding="utf-8").read().splitlines()
             if ln.strip()]
    rec = json.loads(lines[-1])
    assert rec.get("ch") == "dingtalk" and rec.get("errcode") == -2, rec
    body = rec.get("desp", rec.get("content", ""))
    assert "内容超长已截断" in body, \
        "账本未落截断尾注（非实收 text 形态）"
    assert tail not in body, \
        "账本落的是截断前 desp 原文（记录≠实收）"


# ---------- P3-3: 空节防御 ----------

def test_digest_payload_skips_empty_sections():
    """空节 (route, []) 不再 IndexError（红态=L1981 ds_all[0] 炸）：
    入口防御跳过，产出与无该 entry 等价。"""
    a = _mk_alerter()
    r = Route(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-10-05"],
              alert_direct=1900)
    pv = a._digest_payload([(r, [])], fresh=True, with_tables=False)
    assert set(pv) >= {"title", "desp"}, "空节防御后产出形态缺失"
