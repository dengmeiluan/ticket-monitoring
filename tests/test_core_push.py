# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r235_push.py
- tests/test_r238_push.py
- tests/test_r246_push.py
- tests/test_r253_push.py
- tests/test_r260_push.py
- tests/test_r262_push.py
- tests/test_r264_push.py
- tests/test_r273_push.py
- tests/test_r281_push.py
- tests/test_r283_push.py
- tests/test_r302_push.py
- tests/test_r308_push.py
- tests/test_r318_push.py
- tests/test_r321_push.py
- tests/test_r330_push.py
- tests/test_r333_push.py
- tests/test_v15106_push.py
- tests/test_v15111_push.py
- tests/test_v15127_push.py
- tests/test_v15130_push.py
- tests/test_v1563_push.py
- tests/test_v1579_push.py
- tests/test_v162_push.py
- tests/test_v170_push.py
- tests/test_v180_push.py
- tests/test_v186_push.py
- tests/test_v195_push.py
- tests/test_v229_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import core.alerter as A
import core.notifier as N
import core.notifier as _not
import core.notifier as nm
import datetime as dt
import inspect
import json
import logging
import logging as _lg
import math
import os
import pytest
import re
import sys

from core import alerter, alerter as _al, notifier
from core.alerter import Alerter, TIER_FULL, _dedup_tie, _disp_dw, _disp_dw as _dw, _dw as _dw_line, _dw_bold, _fit_line, _l2_fallbacks, _low_txt, _near_txt, _ops_fallbacks, _storm_title, gap_txt, tier_dot
from core.models import FlightPrice, Route, Route as _R
from core.notifier import CompositeNotifier, DingTalkNotifier, EmailNotifier, NtfyNotifier, ServerChanNotifier, WindowsToastNotifier, _alert_body, _append_push_history
from pathlib import Path
from types import SimpleNamespace


# ---- merged from tests/test_r235_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_l2_fallbacks_slash_join_leg_strip():
    """「/」联程名剥首段档：保末段航司+完整时刻+跨天括注。"""
    base = "海南航空 HU7849/春秋9C8845 08:30→01:30(+1天)"
    assert _dw(base) > 40, "前提：联程 base 原样超宽"
    tiers = _l2_fallbacks(base, "", "")
    slash = [t for t in tiers if t.startswith("春秋9C8845")]
    assert slash, "「/」剥首段档不在链上: %s" % (tiers,)
    assert "08:30→01:30(+1天)" in slash[0], "时刻/跨天被截: %s" % (tiers,)
    assert _dw(slash[0]) <= 40
    # 档序：「/」档紧邻地板档之前（地板=逐字截恒末位）
    assert tiers.index(slash[0]) == len(tiers) - 2, tiers


def test_l2_reachable_tiers_keep_arrival_and_cross():
    """行为钉：_fit_line 选取语义=首个 ≤40 档——链的选取结果必须
    保住到达时刻+跨天括注（地板逐字截档只是全超兜底，不参与选取）。"""
    base = "海南航空 HU7849/春秋9C8845 08:30→01:30(+1天)"
    for tiers in (_l2_fallbacks(base, "", ""),
                  _l2_fallbacks(base, "(+1天)", " ｜ 较上轮 ↑￥50")):
        reachable = [t for t in tiers if 0 < _dw(t) <= 40]
        assert reachable, tiers
        picked = reachable[0]
        assert "01:30" in picked, "到达时刻被截: %s ← %s" % (picked, tiers)


def test_l2_fallbacks_mixed_pipe_then_slash():
    """双名+联程混合形态：「｜」档先剥营销名；「｜」档仍超宽时
    「/」档再剥首段联程航司——两档串联皆在链上，链尾地板恒达标。"""
    base = "新海航｜海南航空 HU7849/春秋9C8845 08:30→01:30(+1天)"
    tiers = _l2_fallbacks(base, "", "")
    assert any(t.startswith("海南航空 HU7849/春秋9C8845") for t in tiers), tiers
    assert any(t.startswith("春秋9C8845") for t in tiers), tiers
    assert _dw(tiers[-1]) <= 40


def test_l2_fallbacks_pipe_form_unchanged():
    """回归：「｜」双名形态档序不变（营销名剥档先于「/」档与地板）。"""
    tiers = _l2_fallbacks(
        "新海航｜海南航空 HU7849 07:10→13:45", "(+1天)",
        " ｜ 较上轮 ↑￥50")
    assert any(t.startswith("海南航空") for t in tiers), tiers
    assert not any("较上轮" in t for t in tiers), tiers
    assert _dw(tiers[-1]) <= 40


# ---- merged from tests/test_r238_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_plain_no_double_space_after_tier_transcribe():
    """P2-1 复现钉：KPI 行经 _plain 剥壳+档位转写后不得残留双空格。

    输入形态=真实达标轮 KPI 行（markdown 链接壳 + 🎯 档位点 +
    行内空格）：剥壳坍缩后「🎯 直飞 ￥1710」干净，但转写
    🎯→「真达标 」（尾随空格）与行内空格叠加=「真达标  直飞」。
    """
    desp = "- [**🎯 直飞 ￥1710**](https://example.com/view)　低￥190·10%"
    out = WindowsToastNotifier._plain(desp, 180)
    assert "真达标" in out, out
    assert "  " not in out, "转写后双空格回潮: %r" % (out,)


def test_plain_transcribe_words_multiline_no_double_space():
    """多行混合形态（🎯/🟨 双档行）转写后同样无双空格、无行首空格。"""
    desp = ("- [**🎯 直飞 ￥1710**](https://example.com/a)　线￥1900\n"
            "- [**🟨 中转 ￥2279**](https://example.com/b)　差￥579（34%）")
    out = WindowsToastNotifier._plain(desp, 180)
    assert "真达标" in out and "擦边" in out, out
    for seg in out.split("；"):
        assert "  " not in seg, "双空格残留: %r" % (seg,)
        assert not seg.startswith(" "), "段首空格: %r" % (seg,)


# ---- merged from tests/test_r246_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _mk_alerter():
    class FakeN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            return True
    return Alerter(logging.getLogger("t246"), notifier=FakeN(),
                   storage=None, digest=True)


def _route(**kw):
    d = dict(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
             to_name="上海", dates=["2026-10-05"],
             alert_direct=1900, alert_transfer=1700)
    d.update(kw)
    return Route(**d)


def _row(price, stale=None, **kw):
    f = {"price": price, "name": "南航CZ6981", "code": "CZ6981",
         "depTime": "18:30", "arrTime": "23:40",
         "depDate": "2026-10-05", "arrDate": "2026-10-05",
         "transCity": "", "_platform": "qunar"}
    f.update(kw)
    if stale:
        f["_stale_h"] = stale
    return f


def _sec(top_direct=None, top_transfer=None, best_direct=None,
         best_transfer=None, seen=("qunar",)):
    return {"date": "2026-10-05",
            "top_direct": top_direct or [],
            "top_transfer": top_transfer or [],
            "best_direct": best_direct,
            "best_transfer": best_transfer,
            "best_transfer_mkt": None,
            "seen_plats": list(seen),
            "all_flights": list(top_direct or []) + list(top_transfer or []),
            "xphans": [], "qd": [], "qt": []}


# ---- P1 空小节补偿行 ----

def test_p1_stale_only_section_gets_note():
    """best 双空 + top 仅补位行 → 轻量行出补位价（价格+新鲜度同行，
    r318 防指纹小型化形态：原「⏳ 本轮无当轮明细」注的同等信息密度
    ——补位价行即「无当轮明细」的事实陈述，价格判据保留）。"""
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(3140, stale=4.2)])
    pv = a._digest_payload([(_route(), [sec])], with_tables=False,
                           with_charts=False)
    assert "补位 ￥3140" in pv["desp"], pv["desp"][:600]
    # 新鲜度「4h前」是次要信号：全名行超宽时按档序先剥（十九§9），
    # 价格判据（补位 ￥3140）必须存活——上一断言即其钉面


def test_p1_fresh_rows_no_note():
    """top 有当轮行 → 不出注（正常行情小节，注=噪音）。"""
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(2100)])
    pv = a._digest_payload([(_route(), [sec])], with_tables=False,
                           with_charts=False)
    assert "本轮无当轮明细" not in pv["desp"], pv["desp"][:600]


def test_p1_best_present_no_note():
    """best 在（当轮有最优）→ 不出注（KPI 即解释）。"""
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(2100), _row(3140, stale=4.2)],
               best_direct=_row(2100))
    pv = a._digest_payload([(_route(), [sec])], with_tables=False,
                           with_charts=False)
    assert "本轮无当轮明细" not in pv["desp"], pv["desp"][:600]


def test_p1_second_date_stale_note():
    """第 2+ 日期同形态：补位价行兜底（不静默）——多日期行各自带
    日期短词可辨（r318 轻量形态每日期一行）。"""
    a = _mk_alerter()
    s1 = _sec(top_direct=[_row(2100, depDate="2026-10-06")],
              best_direct=_row(2100, depDate="2026-10-06"))
    s1["date"] = "2026-10-06"
    s2 = _sec(top_direct=[_row(3140, stale=4.2)])
    s2["date"] = "2026-10-05"
    pv = a._digest_payload([(_route(dates=["2026-10-05", "2026-10-06"]),
                             [s1, s2])], with_tables=False,
                           with_charts=False)
    assert "补位 ￥3140" in pv["desp"], pv["desp"][:900]
    assert "10/05" in pv["desp"] and "10/06" in pv["desp"], pv["desp"][:900]


def test_p1_note_line_width():
    """补位价行守 40 半角渲染宽（手机 ≤20 全角律，与 _win_empty 同门）。"""
    from core.alerter import _disp_dw
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(3140, stale=4.2)])
    pv = a._digest_payload([(_route(), [sec])], with_tables=False,
                           with_charts=False)
    note = [ln for ln in pv["desp"].splitlines() if "补位" in ln]
    assert note and _disp_dw(note[0]) <= 40, note


# ---- P2 总表行达标旗标收口 ----

def test_p2_row_qual_stale_excluded():
    """补位行不参达标色（_row_qual 单源）：达标判定只认当轮。"""
    route = _route()
    assert A._row_qual(_row(1700), 1900, route, False) is True
    assert A._row_qual(_row(1700, stale=4.2), 1900, route, False) is False
    assert A._row_qual(_row(2500), 1900, route, False) is False


def test_p2_table_multi_uses_row_qual():
    """_flights_table_md_multi 行组装走 _row_qual 单源（源码钉防
    旁路——组内再回 _tie_any_ok 即回潮）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count("_row_qual(") >= 2, "组装点必须走 _row_qual"


# ---- P3 运维注词面 ----

def test_p3_ops_notes_current_round_wording():
    """「无数据」→「当轮无数据」（与同图补位行同屏不再读感矛盾）。"""
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(2100)], seen=("qunar",))
    notes = a._ops_notes([(_route(), [sec])])
    assert any("当轮无数据：飞猪、携程" in n for n in notes), notes
    assert not any(" 无数据：" in n for n in notes), notes


def test_p3_ops_notes_flag_wording():
    """「达标判定失效」→「按未标注判不达标」（不作系统故障读）。"""
    a = _mk_alerter()
    route = _route(transfer_baggage="direct")
    sec = _sec(top_transfer=[_row(2100, transCity="郑州",
                                  transferBaggage="")])
    notes = a._ops_notes([(route, [sec])])
    assert any("按未标注判不达标" in n for n in notes), notes
    assert not any("达标判定失效" in n for n in notes), notes


# ---- S1 哨兵触发文案分档 ----

def test_s1_sentinel_shallow_pool_wording():
    """池浅（n<30）：词面分档为「临期退化/小池」，不打「站点改版」
    归因（真实原因=日期退池，键死证据弱）。"""
    from main import _sent_hit_text
    txt = _sent_hit_text("qunar", "meal", 2, 22)
    assert "22" in txt and "站点改版" not in txt
    assert "退化" in txt or "小池" in txt


def test_s1_sentinel_deep_pool_wording_kept():
    """池深（n≥30）维持站点改版归因（键死强信号原文案不变）。"""
    from main import _sent_hit_text
    txt = _sent_hit_text("qunar", "cabin", 2, 45)
    assert "站点改版" in txt


def test_s1_sentinel_boundary_n30_deep():
    """边界 n=30 走池深档（≥30 语义含等号，键死强信号归因）。"""
    from main import _sent_hit_text
    txt = _sent_hit_text("qunar", "cabin", 2, 30)
    assert "站点改版" in txt


def test_s1_warn_format_smoke():
    """真执行 _warn 同形 logging 语义冒烟：词面含裸 % 时旧拼串形态
    在 [连续%d日] 分支被 logging 静默吞掉（stderr 噪音、消息不落盘，
    Soldier P1-1 变异实证）——%s 传参形态必须完整落盘。"""
    import io
    import logging
    from main import _sent_hit_text
    buf = io.StringIO()
    lg = logging.getLogger("t246warn")
    lg.propagate = False
    lg.addHandler(logging.StreamHandler(buf))
    lg.setLevel(logging.INFO)
    msg = _sent_hit_text("qunar", "meal", 2, 22)
    lg.info("[解析哨兵][连续%d日] " + "%s", 3, msg)
    assert "池浅" in buf.getvalue(), "新形态未落盘"
    buf.truncate(0)
    buf.seek(0)
    lg.info("[解析哨兵][连续%d日] " + msg, 3)
    assert "池浅" not in buf.getvalue(), \
        "旧拼串形态竟成功落盘=钉失去变异证明力"


def test_p2_row_qual_all_call_sites():
    """_row_qual 全消费点钉（≥3：def + multi + single）：单航线总表
    _flights_table_md 曾旁路回潮补位达标绿（Soldier P1-2 实证）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count("_row_qual(") >= 3, src.count("_row_qual(")
    # 单航线组装点必须走 _row_qual（源码锚防新增旁路）
    assert "_row_qual(g, th, route," in src


def test_p2_text_top_fire_stale_excluded():
    """文本 TOP5 兜底 🔥 同门（我方 Soldier P2-1 姊妹面，双方审查
    交叉互补项）：补位行不带 🔥（与总表图 _row_qual 同律——兜底是
    图挂日唯一载体，🔥=可出手指向过期价同病）；当轮达标行照带
    （直飞+中转双段；单元直调 _top3_blocks，全链构造绕级探不到）。"""
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(1600, stale=4.2, code="ZZ0001"),
                           _row(1650, code="ZZ0002")],
               top_transfer=[_row(1600, stale=4.2, code="ZZ0003",
                                  transCity="郑州"),
                             _row(1650, code="ZZ0004", transCity="郑州")])
    desp = a._top3_blocks(_route(), [sec])
    fire_lines = [ln for ln in desp.splitlines() if "🔥" in ln]
    assert fire_lines, desp[:400]
    assert all("ZZ0001" not in ln and "ZZ0003" not in ln
               for ln in fire_lines), fire_lines
    assert any("ZZ0002" in ln for ln in fire_lines), fire_lines
    assert any("ZZ0004" in ln for ln in fire_lines), fire_lines


def test_p2_propagate_airline_code_conflict_debug(caplog):
    """跨渠道补全 airlineCode 值冲突 DEBUG 留痕（我方 Soldier P2-2：
    fliggy 派生值入 vals 集后 codeshare 分歧面变化——分歧观测先行，
    行为保守跳过不变：冲突组缺值行不补）。"""
    import logging as _lg
    rows = [
        {"code": "ZZ0001", "airlineCode": "ZZ", "_platform": "fliggy"},
        {"code": "ZZ0001", "airlineCode": "MU", "_platform": "tuniu"},
        {"code": "ZZ0001", "_platform": "qunar"},
    ]
    with caplog.at_level(_lg.DEBUG, logger="core.alerter"):
        Alerter._propagate_fields(rows)
    assert any("airlineCode" in r.getMessage() and "ZZ" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in
                                          caplog.records]
    assert not rows[2].get("airlineCode"), rows[2]  # 分歧保守不补


def test_s1_sentinel_call_site_wired():
    """调用点接线源码钉（我方 Soldier P2-3 钉面纠偏版）：<10% 档必须
    走 _sent_hit_text 单源。直钉「def 外全部引用、其前 3 行窗内
    是 _warn 调用」——仅 `in` 判定被 def 行自身满足；调用点回退内联
    手抄词面后引用行归零即红（跨行调用形态：引用行自身不含
    _warn，须按窗判定）。r247 直飞行群分流后合法两处（全行批
    apt/aptc + 直飞行群批 cabin/meal/prate/plane/psize/discount），
    每处都必须挂 _warn——词面单源语义不随批数漂移。"""
    src = open("main.py", encoding="utf-8").read()
    lines = src.splitlines()
    call = [i for i, ln in enumerate(lines)
            if "_sent_hit_text(" in ln and "def " not in ln]
    assert len(call) == 2, call
    for i in call:
        ctx = "\n".join(lines[max(0, i - 3):i + 1])
        assert "_warn" in ctx, ctx


# ---- merged from tests/test_r253_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _fp(price, name, dpt, art, trans="", cross="", plat="ctrip",
        dep="2026-10-04", **extra):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else 0
    f = {"price": price, "name": name, "code": name, "depTime": dpt,
         "arrTime": art, "depDate": dep,
         "arrDate": str(d0 + dt.timedelta(days=days)),
         "transCity": trans, "crossDayDesc": cross,
         "_platform": plat}
    f.update(extra)
    return f


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


class _FakeN:
    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        return True


def _mk():
    log = logging.getLogger("r253probe")
    logging.basicConfig(level=logging.CRITICAL)
    return Alerter(log, notifier=_FakeN(), storage=None, digest=True,
                   at_mobile="", storm_repeat=1, user="演练")


_TR_ROW = {"price": 1650, "name": "川航3U8863", "code": "3U8863",
           "depTime": "17:55", "arrTime": "18:50", "crossDayDesc": "+1天",
           "transCity": "兰州", "stopCity": "庆阳",
           # 生产实证形态（r253 审校 S8：ctrip 中转行同带双键常态）：
           # layoverT 是 normalize 从 layover(int 分钟) 重建的词面，
           # 真源键 layover + layoverSrc="times"（结构化真值，豁免
           # 假衔接判伪守卫）；全程时长必须 > 停留（衔接≥全程作废
           # 守卫）——17:55→次日18:50=24h55 > 22h55
           "layover": 1375, "layoverSrc": "times",
           "stopTimeT": "0:45", "transferBaggage": "direct",
           "_platform": "ctrip"}


class TestViaTxt:
    def test_transfer_row_prefers_trans_city(self):
        """P1-1 主钉：中转行双键同带 →「经兰州」（非「经停庆阳」）。"""
        assert Alerter._via_txt(
            {"transCity": "兰州", "stopCity": "庆阳"}) == "经兰州"

    def test_stopover_row_keeps_stop_word(self):
        """经停行（无 transCity）词面不回归。"""
        assert Alerter._via_txt({"stopCity": "庆阳"}) == "经停庆阳"

    def test_placeholder_and_empty(self):
        """「中转」占位与空行守卫不回归（勿产「经中转」病句）。"""
        assert Alerter._via_txt({"transCity": "中转"}) == ""
        assert Alerter._via_txt({}) == ""
        assert Alerter._via_txt({"transCity": "兰州"}) == "经兰州"


class TestFmtFlightLinePairing:
    # 注：_fmt_flight_line 的中转行词面由 _via_txt 单源保证（上方
    # 单元钉已覆盖）；其明细行长行常态超 40 半角、走 bare 地板档
    # （舍停保码既有档序在案），via/停时先于错配被剥——行级配对钉
    # 无鉴别力，不重复。
    def test_stopover_row_not_mispaired(self):
        """纯经停行（同机号）不被误配中转词（词面正确性在 _via_txt
        单元钉；本钉守消费点无「经兰州」错配）。"""
        line = Alerter._fmt_flight_line(
            {"price": 1500, "name": "南航CZ6981", "code": "CZ6981",
             "depTime": "09:00", "arrTime": "14:10",
             "stopCity": "庆阳", "stopTimeT": "0:45",
             "totalDuration": "6时", "_platform": "qunar"}, idx=2)
        assert "经兰州" not in line, line


class TestHitsLinePairing:
    def test_hits_transfer_row_pairs_correctly(self, monkeypatch):
        """达标 hits 行端到端：「经兰州 停22:55」且全 desp 无错配词。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_arrival_max="23:59")
        row = dict(_TR_ROW)
        row["price"] = 1600  # 达标（≤1700，直挂标注在场）
        p = _ps([row], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        desp = pv["desp"]
        assert "经兰州 停22:55" in desp, desp[:600]
        assert "经停庆阳 停" not in desp, desp[:600]


class TestTitleAnchorMktBreak:
    def test_market_break_solo_round_gets_anchor(self, monkeypatch):
        """P2-1：行情破线独占轮（直挂约束未达标）标题挂「低￥N」锚。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct", transfer_arrival_max="23:59")
        # 独占轮：无直飞行（best_direct=None）、中转行情破线（1650<
        # 1700）但无直挂标注不进 hits——旧行为两锚分支全跳过塌缩为
        # 「❌ 全部未达标｜清单」裸标题
        p = _ps([
            _fp(1650, "川航3U8863", "17:55", "18:50", trans="兰州",
                cross="+1天", layover=1375, layoverSrc="times"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        title = pv["title"]
        assert "低￥50" in title, title
        assert "❌ 全部未达标" in title, title

    def test_overline_anchor_priority_unchanged(self, monkeypatch):
        """超线锚优先（既有行为零回归）：超线与破线并存时挂超线锚。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct")
        p = _ps([
            _fp(1650, "川航3U8863", "17:55", "18:50", trans="兰州",
                cross="+1天", layover=1375, layoverSrc="times"),   # 破线、无直挂标注→不达标
            _fp(1620, "东航MU8370", "09:00", "14:10", plat="qunar"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        title = pv["title"]
        # 直飞差￥20 锚在场且优先（既有行为）；破线锚不与之争
        assert "差￥20" in title, title


class TestHitsHeadDualName:
    def test_dual_name_demotes_to_short(self, monkeypatch):
        """P3-1：双名超宽 → 剥营销名档保「金鹏航空 Y87519」。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700)
        p = _ps([_fp(1450, "新海航｜金鹏航空 Y87519", "09:05", "13:55",
                     plat="qunar")], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        desp = pv["desp"]
        m = re.search(r"> 🔥 \*\*直飞 ￥1450\*\*[^\n]*", desp)
        assert m, f"hits head 缺席: {desp[:400]}"
        head = m.group(0)
        assert "金鹏航空 Y87519" in head, head


class TestKpiL3TokenFloor:
    def test_l3_floor_no_half_token(self, monkeypatch):
        """P3-2：病理长 transCity 地板截不留半截 token（「停2:」）。

        夹具必须 transfer_arrival_max="23:59"（Soldier P1-2）：缺省
        02:00 到达约束把 18:50(+1天) 中转行判出局、行3 根本不渲染，
        半截断言对空 desp 恒真=修复无行为锁（变异不红）。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct", transfer_arrival_max="23:59")
        # 15 全角城市：经(2)+30+空格(1)=33 半角处，「停2:」token 恰
        # 装下而完整「停2:05」溢出（_dw_raw 数字 1.125 校准宽下累计
        # 到「停2」即破预算）——旧行为在此截出「停2:」半截
        long_city = "乌鲁木齐地窝堡国际机场中转楼站"
        p = _ps([
            _fp(1650, "川航3U8863", "17:55", "18:50", trans=long_city,
                cross="+1天", layover=125, layoverSrc="times",
                transferBaggage="direct"),
            _fp(1620, "东航MU8370", "09:00", "14:10", plat="qunar"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        # 前置断言：中转行真在场（best_transfer 非空）——行3 真渲染
        # 才有锁行为可言（真空通过防线）
        assert sections and sections[0].get("best_transfer") is not None, \
            "夹具失效：中转行被判出局，行3 不渲染（Soldier P1-2 同型）"
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        desp = pv["desp"]
        # 行3 真渲染锚：病理城市前缀在场（「经…」token 装载起点）
        assert f"经{long_city[:6]}" in desp, desp[:600]
        # 「停」token 若在，冒号后必须恰两位分钟（无半截）
        assert not re.search(r"停\d{1,2}:(?!\d{2})", desp), \
            f"半截 token 残留: {[l for l in desp.splitlines() if '停' in l][:3]}"


class TestPlaceholderTransRowPairing:
    def test_placeholder_trans_uses_stop_pairing(self):
        """P2-2 占位洞：transCity=「中转」占位 + stopCity 有值 →
        词面「经停庆阳」、停留取 stopTimeT（不再错配 layoverT）。"""
        f = {"transCity": "中转", "stopCity": "庆阳",
             "layoverT": "22:55", "stopTimeT": "0:45"}
        assert Alerter._trans_city(f) == ""
        assert Alerter._via_txt(f) == "经停庆阳"
        # 消费点配对口径（hits seg 同门）
        lay = str((f.get("layoverT") if Alerter._trans_city(f)
                   else f.get("stopTimeT")) or "").strip()
        assert lay == "0:45"


class TestTitleAnchorMultiBreak:
    def test_deepest_break_wins(self, monkeypatch):
        """P1-1：多破线候选挂 |gap| 最大的（价最低=最有希望）——
        比较符与原始负 gap 比较恒真曾退化成「最后扫到的赢」。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct", transfer_arrival_max="23:59")
        # 两条破线中转：￥1500（低￥200）先入组、￥1650（低￥50）后入
        # ——扫到序的「最后赢」会错挂低￥50
        p = _ps([
            _fp(1500, "川航3U8863", "17:55", "18:50", trans="兰州",
                cross="+1天", layover=125, layoverSrc="times"),
            _fp(1650, "南航CZ6976", "12:05", "23:50", trans="郑州",
                cross="+1天", layover=200, layoverSrc="times"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True,
                               with_tables=True)
        title = pv["title"]
        assert "低￥200" in title, title
        assert "低￥50" not in title, title


# ---- merged from tests/test_r260_push.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_HEAD = "📍 10/06　"


def _trig(label, price, th):
    """按真实单源构造超宽段（tier_dot 点后带尾空格——手抄词面漏
    空格即 _disp_dw=40 不触发，测试假绿；直调单源防词面漂移）。"""
    diff = price - th
    seg = (f"{_al.tier_dot(False, diff, th)}{label} ￥{price} "
           f"{_al.gap_txt(price, th, False)}{_al._MKT_NOTE}")   # r302 换词随单源
    assert _al._disp_dw(_HEAD + seg) > 40, f"样本不触发: {seg!r}"
    return seg


# 网格实证的现实超宽形态（🟩×低￥N·行情，head+seg=41 恰超线）
_TRIGGERS = [_trig(lb, p, th)
             for lb in ("直飞", "中转")
             for p, th in ((1234, 19000), (2280, 19000), (12345, 19000))]


@pytest.mark.parametrize("seg", _TRIGGERS)
def test_mini_split_dennote_before_truncation(seg):
    """结果级锁：单段超宽输出差额词完整在场+短注缺席+预算内
    （去注档承载该形态；若降级链档序回退使截断先吃，金额完整性与
    预算断言同样收口）。"""
    out = _al._mini_split(_HEAD, [seg])
    body = out.strip()
    assert body, "地板档恒落位：行内容不得净失"
    assert _al._disp_dw(body) <= 40, body
    gap = re.search(r"[低差]￥\d+", seg).group(0)
    assert gap in body, f"差额词 {gap} 必须完整在场，got {body!r}"
    assert _al._MKT_NOTE not in body  # 去注档已丢短注（r302 换词随单源）
    for amt in re.findall(r"￥(\d+)", body):
        assert amt in set(re.findall(r"￥(\d+)", seg)), \
            f"半截金额 ￥{amt} in {body!r}"


def test_trunc_tokens_token_boundary_greedy():
    """_trunc_tokens 单源语义钉：截点落 token 中部回退 token 起点
    （整 token 丢弃）、首 token 超预算逐字截保前缀（恒落位律）、
    全角分隔形态。"""
    assert _al._trunc_tokens("AA BBBB CC", 6) == "AA"      # BBBB 整删
    assert _al._trunc_tokens("AA BBBB CC", 8) == "AA BBBB"
    assert _al._trunc_tokens("BBBBBB CC", 4) == "BBBB"   # 首token逐字截
    assert _al._trunc_tokens("AA　BB", 5, sep="　") == "AA"


def test_mini_split_floor_tokens_whole_or_absent():
    """mini 地板 token 语义（函数级直调——现实域数学不可达，构造
    超预算形态验证）：非首 token 要么完整要么缺席，金额不截半。"""
    seg = "🎯 直飞 ￥12345 低￥6655"
    # 压缩 head 预算到金额必截带：head 用病理长词面吃满预算
    head = "📍 " + "长" * 12 + "　"
    out = _al._mini_split(head, [seg])
    body = out.strip()
    assert _al._disp_dw(body) <= 40, body
    whole = set(re.findall(r"￥(\d+)", seg))
    for amt in re.findall(r"￥(\d+)", body):
        assert amt in whole, f"半截金额 ￥{amt} in {body!r}"


@pytest.mark.parametrize("seg", _TRIGGERS)
def test_mini_split_floor_amount_whole(seg):
    """输出中出现的 ￥金额必须是输入段的完整金额——「￥190」半截
    金额会被读成错误值（决策级信息损坏）。"""
    out = _al._mini_split(_HEAD, [seg])
    body = out.strip()
    whole = set(re.findall(r"￥(\d+)", seg))
    for amt in re.findall(r"￥(\d+)", body):
        assert amt in whole, f"半截金额 ￥{amt} in {body!r}"


# ---- merged from tests/test_r262_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_mkt_note_literal_zero_residual():
    """源码钉：星注带引号字面量零残留——三处消费点全部走
    _MKT_NOTE 单源（裸字面量残留计数钉，count==0 即只剩定义式
    "·" + _MKT_SHORT）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert '"*行情"' not in src, (
        "「*行情」短注字面量残留：产出与剥段消费必须同出 _MKT_NOTE 单源"
        "（词面改版日剥段档静默失效族，LESSONS 十六§3b）")
    assert src.count("_MKT_NOTE") >= 4, (
        "_MKT_NOTE 定义+消费点不足（期望定义 1 处+消费 ≥3 处）")


def test_mini_split_strip_follows_mkt_note_constant(monkeypatch):
    """行为钉：剥段消费与 _MKT_NOTE 同源——常量改版（模拟词面改版日）
    后 _mini_split 去短注档剥掉的是新词面，不残留。旧形态（字面量
    手抄）下 monkeypatch 不生效，「*促」残留进输出。"""
    monkeypatch.setattr(A, "_MKT_NOTE", "*促")
    # 样本按真实计宽函数网格探找（手算不当作依据）：原样超宽、剥新
    # 词面达标，两段各自 head+seg ≤40——坏形态走拆行档时 seg_b 完整
    # 保留，「*促」不会被地板截吃掉（防截断假绿）；具体宽度以自证
    # 断言为准，注释不锚数字
    seg_a = "甲" * 10
    seg_b = "🟩直飞￥1200" + A._MKT_NOTE
    head = "D2"
    line = head + " ｜ ".join([seg_a, seg_b])
    no_note = head + " ｜ ".join(
        [seg_a, seg_b.replace(A._MKT_NOTE, "")])
    assert A._disp_dw(line) > 40, "样本未进降级面（原样须超宽）"
    assert A._disp_dw(no_note) <= 40, "样本未卡「去短注档」（剥注后须达标）"
    assert A._disp_dw(head + seg_a) <= 40 and A._disp_dw(head + seg_b) <= 40
    out = A._mini_split(head, [seg_a, seg_b])
    assert "*促" not in out, (
        "去短注档未跟随 _MKT_NOTE 常量：剥段消费与产出词面分叉"
        "（触发档显形族：该行超宽时短注剥不掉，随拆行/截断路径烂尾）")


def test_mkt_note_family_cross_module_single_source():
    """Soldier Major-1 收口钉：「（行情价）」与「*行情」两词面的跨模块
    手抄收编——产出（alerter 降级链 / report 日报 KPI 尾注）与剥注
    消费（notifier _MKT_NOTE_DUPS，ntfy/短信/TTS 纯文本通道转写前
    共用）同出 alerter 投影单源；跨模块手抄在词面改版日静默分叉
    （剥注表失配=纯文本通道残留营销注，且钉旧字面量的测试不会红）。
    收编是引用改写：四元组值面逐字节不变（行为零差由全量回归背书）。"""
    a_src = open("core/alerter.py", encoding="utf-8").read()
    n_src = open("core/notifier.py", encoding="utf-8").read()
    r_src = open("report.py", encoding="utf-8").read()
    for tag, src in (("alerter", a_src), ("notifier", n_src), ("report", r_src)):
        assert '"（行情价）"' not in src, (
            "%s 手抄「（行情价）」字面量残留：须走 _MKT_NOTE_PAREN 单源" % tag)
    assert '"*行情"' not in n_src, (
        "notifier 剥注表手抄星注残留：须引用 alerter._MKT_NOTE")
    import core.alerter as A2
    import core.notifier as N
    assert A2._MKT_NOTE_PAREN == "（行情价）"
    # r302 P3：星注分隔符 * → ·（非强调字符），剥注表值面随单源
    assert N._MKT_NOTE_DUPS == ("（行情价）", A2._MKT_NOTE,
                                "行情价", "行情破线"), (
        "_MKT_NOTE_DUPS 值面漂移：收编须引用 alerter._MKT_NOTE 投影")


# ---- merged from tests/test_r264_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_l3_note_literal_single_source():
    """源码钉：带 ASCII 双引号的「行情价」字面量在 alerter 源内
    只剩 _TIER_TABLE 转写词列定义一处（count==1）；行3 注赋值
    形态必须是 TIER_TRANSCRIBE 投影（运行时求值，词面改版日
    monkeypatch/改表自动跟随——裸字面量则两处分叉）。注释与
    中文引号「」形态不进计数（LESSONS 二十§10：计数钉锁声明
    枚举，注释不是声明）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count('"行情价"') == 0, (
        "「行情价」裸字面量残留：行3 注必须消费 "
        "TIER_TRANSCRIBE[\"mkt\"].strip() 投影，与转写表同源"
        "（词面改版日叠词静默复发族）")
    assert src.count('"行情价 "') == 1, (
        "转写表 mkt 行定义缺席或漂移（带尾空格的词面恰定义一处）")
    assert 'l3_note = TIER_TRANSCRIBE["mkt"].strip()' in src, (
        "行3 注赋值未走 TIER_TRANSCRIBE 投影（与 _MKT_NOTE_PAREN "
        "同形态的单源引用）")


def test_mkt_note_paren_derived_from_transcribe():
    """行为钉（Soldier P2-1 改写）：_MKT_NOTE_PAREN 是 import 期
    绑定的模块常量，锁「常量由转写表投影派生」的等式——改表词面
    而忘改派生式（或退化为裸字面量手抄）时本钉红。l3_note 本体
    深埋嵌套函数无独立入口（直调不可达），其单源性由源码钉
    （前一颗锁赋值形态）承担——此处不重复锁不可达面。"""
    assert A._MKT_NOTE_PAREN == "（" + A.TIER_TRANSCRIBE["mkt"].strip() + "）", (
        "_MKT_NOTE_PAREN 与转写表投影分叉：常量必须由 "
        "TIER_TRANSCRIBE[\"mkt\"].strip() 派生（词面改版日只改表）")


def test_trend_ring_note_red_dash_entry():
    """源码钉：走势图点环分档小注循环内补「红虚线」词条——
    直飞达标虚线（C_TH）与 ▼红回落（C_CMP）同值同图两义，
    小注是图面唯一解码位。词条必须与点环注同一循环产出
    （分散第二绘制点=两处维护面），计数==1 且落在
    「=TIER_FULL['fall']」行之后的同一语句切片内。"""
    src = open("report.py", encoding="utf-8").read()
    assert src.count("红虚线") == 1, (
        "「红虚线」词条缺席或分散：达标虚线两义解码必须收在"
        "点环小注单循环内")
    fall_i = src.index("={TIER_FULL['fall']}")
    seg = src[fall_i:fall_i + 300]
    assert "红虚线" in seg, (
        "「红虚线」词条未落在点环小注循环内（散落第二绘制点）")


# ---- merged from tests/test_r273_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _mk_route(ad=1900, at=1700):
    return Route(from_code="SHA", to_code="URC", from_name="上海",
                 to_name="乌鲁木齐", dates=["2026-09-25"],
                 alert_direct=ad, alert_transfer=at)


def _mk_secs(direct_price, transfer_price=None, **tk):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        s["best_direct"] = {"price": direct_price, "name": "MU8369",
                            "depTime": "19:55", "arrTime": "01:25",
                            "_platform": "qunar"}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
        s["best_transfer"].update(tk)
    return [s]


def _desp_lines(secs, route=None):
    a = Alerter(_lg.getLogger("t273p"), storage=None)
    p = a._digest_payload([(route or _mk_route(), secs)],
                          fresh=False, with_tables=False)
    return [ln for ln in p["desp"].split("\n") if ln.strip()]


# ---------- P1: 孤「经济舱」行3 段 ----------

def test_kpi_l3_lone_default_cabin_omitted():
    secs = _mk_secs(1701)
    secs[0]["best_direct"]["cabin"] = "Y"          # 单字母默认档 → 裸「经济舱」
    lines = _desp_lines(secs)
    assert not any("经济舱" in ln for ln in lines), (
        f"直飞行默认舱位不应独占行3 引用段: {lines}")


def test_kpi_l3_nondefault_cabin_kept():
    secs = _mk_secs(1701)
    secs[0]["best_direct"]["cabin"] = "超级经济舱"   # 非默认=异常态警示必留
    lines = _desp_lines(secs)
    assert any("超级经济舱" in ln for ln in lines), lines


def test_kpi_l3_cabin_paren_form_kept():
    secs = _mk_secs(1701)
    secs[0]["best_direct"]["cabin"] = "经济舱(Y)"   # 括注形态含退改等级信息
    lines = _desp_lines(secs)
    assert any("经济舱(Y)" in ln for ln in lines), lines


def test_kpi_l3_transfer_multi_token_unchanged():
    secs = _mk_secs(None, 1660, cabin="Y")
    lines = _desp_lines(secs)
    assert any(ln.startswith("> ") and "经济舱" in ln for ln in lines), (
        f"中转行行3 多 token 不动: {lines}")


# ---------- P2: 建议行贴法两制 ----------

def _suggest(route, s):
    return Alerter(_lg.getLogger("t273p"), storage=None)._suggest_line(route, s)


def test_suggest_mkt_branch_space():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1750, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1660, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r == "中转 行情低￥40，蹲守", r


def test_suggest_exact_line_branch_space():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1750, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1700, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r.startswith("中转 行情破线"), r


def test_suggest_near_branch_space():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1750, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1730, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r.startswith("中转 擦边"), r


def test_suggest_qual_branch_space_unchanged():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1660, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1660, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r.startswith("中转 真达标 "), r


# ---------- P3/P4: 日报路径源码钉（闭包内函数，行为驱动需整链 DB 夹具） ----------

def _report_src():
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "report.py"),
            encoding="utf-8") as fh:
        return fh.read()


def test_daily_kpi_noline_reference_fallback_tier():
    src = _report_src()
    old = 'fallbacks=[base + "（未设线）"])'
    assert old not in src, "未设线分支仍是单档降级（参照静默丢）"
    # 参照词分支内绑一次（v225 计数钉语义：每分支求值一次），
    # fallback 链 = 全形 → 保参照丢标注（33/40 量测可落位）→ 保标注丢参照
    # （r308 E-P2-1：调用点随粗字模投影守卫补 bold 形参，链形态不变）
    bind = "_p7n = _p7_note(False)"
    chain = 'fallbacks=[base + _p7n, base + "（未设线）"],\n                                 bold=_bold)'
    assert bind in src and chain in src, "未设线分支缺「保参照丢标注」中档"


def test_daily_empty_pool_p7_quad_newline_fixed():
    src = _report_src()
    assert src.count('(_p7_quote_line() or "\\n\\n")') == 2, (
        "空池两调用点应改 or 表达式：p7 非空消四连、p7 空保持单空段")
    assert '+ "\\n\\n" + _p7_quote_line()' not in src, (
        "旧拼接形态（恒前导空段+尾空段）禁复活")


# ---- merged from tests/test_r281_push.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _pick(base, cross, d=""):
    tiers = _l2_fallbacks(base, cross, d)
    return _fit_line(base + cross + d, fallbacks=tiers)


# ---------- 病理域：时刻/跨天必在场（修法 B 新行为） ----------

PATHO_CASES = [
    # (航班名, 跨天括注)——r281_push_probe_l2fix 网格的翻车形态
    ("新海航｜海南航空 HU7849（大机型宽体直飞航班）", "(+1天)"),  # 双名+括注
    ("海南航空HU7849（宽体直飞航班机型展示）", "(+1天)"),         # 单名+括注
    ("大美新疆航旅｜海南航空HU7849宽体直飞", "(+1天)"),           # 超长营销名
    ("海南航空HU7849（宽体直飞", "(+1天)"),                       # 未闭合括注
    ("新海航｜海南航空HU7849（经停武汉）", "(+1天)"),             # 语义括注
]


@pytest.mark.parametrize("name,cross", PATHO_CASES)
def test_l2_floor_keeps_tail_times(name, cross):
    base = "%s 21:10→02:35" % name
    picked = _pick(base, cross, d=" 较上轮 ↓100")
    w = _disp_dw(picked)
    assert w <= 40, "地板档恒达标律破：%r w=%d" % (picked, w)
    assert "21:10" in picked and "02:35" in picked, (
        "病理名形态地板档吃掉时刻（%r）——时刻/跨天是决策级辨识信息，"
        "宁可剥名字段不可逐字截吃掉" % picked)
    assert cross in picked, (
        "地板档 cross 恒缺席（既有次生丢失未随修法 B 修复）：%r" % picked)


# ---------- 现实域零漂移：剥名档承接，地板不可达 ----------

REAL_CASES = [
    "南航CZ6976",
    "新海航｜天津航空HU7849",
    "新海航｜乌鲁木齐航空UQ3599",       # 生产最宽双名 27 半角
    "海南航空 HU7849/春秋9C8845",       # 联程名
]


@pytest.mark.parametrize("name", REAL_CASES)
def test_l2_real_domain_no_regression(name):
    cross = "(+1天)"
    base = "%s 21:10→02:35" % name
    picked = _pick(base, cross, d=" 较上轮 ↓100")
    w = _disp_dw(picked)
    assert w <= 40, "%r w=%d" % (picked, w)
    assert "21:10" in picked and "02:35" in picked
    assert cross in picked
    # 剥名档承接（现实域不走保尾地板）：航班号完整在场
    import re
    assert re.search(r"[A-Z0-9]{2}\d{3,4}", picked), (
        "现实域航班号丢失（%r）——现实形态应落剥名档非地板" % picked)


# ---- merged from tests/test_r283_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _mk_desp(fill_len=1100):
    """真实 digest 形态：KPI 头（含建议出手）+ 填充节 + 尾部 hits。"""
    fill = ("#### 10/28 周二\n\n> 10/28 最低 ￥1980（线￥1900）"
            "超线 4.2%\n\n") * (fill_len // 60 + 1)
    return (
        "#### 🎯 上海→乌鲁木齐 真达标 ￥1760（线￥1900）距线-7.4%，"
        "建议出手\n\n"
        "> 10/27 周一 最低 ￥1760 ｜ 🟩行情破线\n\n"
        + fill
        + "> 🔥 **真达标 ￥1701** 海航HU7815\n\n"
        + "> 21:10→02:35(+1天)\n\n"
        + "> 乌→上 10/27 · 去哪儿 · 低价￥63 · "
          "[打开去哪儿](https://flight.qunar.com/view/xyz)\n\n"
        + "@138****1234\n")


def _send_capture(monkeypatch, desp, budget_note=True):
    captured = {}

    class _R:
        status_code = 200
        text = ""

    def _fake_post(url, json=None, **kw):
        captured.update(json or {})
        return _R()

    monkeypatch.setattr(_not.httpx, "post", _fake_post)
    n = _not.NtfyNotifier("topic-r283", logging.getLogger("r283"))
    n.send("达标警报", desp)
    return captured.get("message") or ""


# ---- P1-1 ntfy 命中行前置 ----

def test_ntfy_hits_frontloaded_in_budget(monkeypatch):
    """长 desp（超 600 截断线）的 kept body 必含「命中」行与「打开」
    直达链接词面——命中块前置后 600 预算内必达，线性尾序恒截翻案。"""
    body = _send_capture(monkeypatch, _mk_desp())
    assert "￥1701" in body, body
    assert "打开去哪儿" in body, body
    assert "已截断" in body, "长 desp 应保留截断留痕"


def test_ntfy_no_hits_desp_unchanged(monkeypatch):
    """无命中块的 desp 零变形：重排只动命中块，其余小节原序保留。"""
    short = ("#### 🎯 上海→乌鲁木齐 真达标 ￥1760（线￥1900）"
             "距线-7.4%，建议出手\n\n> 10/27 最低 ￥1760\n")
    body = _send_capture(monkeypatch, short)
    assert "建议出手" in body, body
    assert "已截断" not in body, body
    assert body.index("真达标") < body.index("10/27"), body


# ---- P2-1 图挂兜底 🔥 行保码剥跨天括注终档 ----

class TestFmtFlightLineMarkKeepCode:
    """带 mark 行（🔥 可出手行）「保码剥 cross」终档：告警 desp
    的 hits 区 seg 行已单独承载时刻+跨天（hit_rows 源自 hits 全集），
    head 地板档在 40 预算下按行结构分工——跨天班五行中两行无航班号
    （读者知价不知班）翻案；keep_cross=True（report 日报兜底语境，
    无 hits 段承载）维持旧档序防「当日达误判」回潮。
    r285 审校 P2-1：启用域收口到「该行 ∈ hits」（in_hits 形参，
    TOP5 次优 🔥 行无第二承载位必须保跨天）——本类钉面随域加参
    in_hits=True（原语义=命中行语义）；非命中域的钉在 r285。"""

    def _line(self, alerter, mark, name, dep, arr, cross, **kw):
        f = {"name": name, "code": "HU7815", "price": 1701,
             "depTime": dep, "arrTime": arr,
             "crossDayDesc": cross, "_platform": "qunar"}
        return alerter._fmt_flight_line(f, mark=mark, **kw)

    @pytest.fixture
    def alerter(self):
        from core.alerter import Alerter
        return Alerter(logging.getLogger("r283"), storage=None)

    def test_mark_row_keeps_code_drops_cross(self, alerter):
        """🔥 行（∈hits）：航班号完整在场、跨天括注让位（seg 行承载）。"""
        ln = self._line(alerter, "🔥", "海航｜海南航空HU7815",
                        "21:10", "02:35", "+1天", in_hits=True)
        assert "HU7815" in ln, ln
        assert "￥1701" in ln, ln
        assert "21:10" in ln, ln
        assert "+1天" not in ln, ln

    def test_plain_top_row_keeps_cross_semantics(self, alerter):
        """无 mark 行档序不变：跨天括注优先于码（无 seg 行承载跨天，
        防当日达误判）。"""
        ln = self._line(alerter, "", "海航｜海南航空HU7815",
                        "21:10", "02:35", "+1天")
        assert "+1天" in ln, ln

    def test_keep_cross_daily_digest_semantics(self, alerter):
        """keep_cross=True（report 日报兜底语境）：跨天恒保到地板
        （该消息无 hits 段，剥掉=误判当日达回潮——Soldier M-1）。"""
        ln = self._line(alerter, "🔥", "海航｜海南航空HU7815",
                        "21:10", "02:35", "+1天", keep_cross=True)
        assert "+1天" in ln, ln


# ---- P3-1 ops 注地板档悬垂分隔符 ----

def test_ops_fallbacks_floor_no_dangling_separator():
    """无冒号长注地板档截点落在「·」上时剥尾分隔符：产出
    「…标注缺失·(截)」读作未完列举——「·」是并列连接件不是信息。"""
    from core.alerter import _ops_fallbacks
    n = "上→乌 10/27 中转直挂标注缺失·按未标注判不达标"
    floor = _ops_fallbacks(n)[-1]
    assert floor.endswith("(截)"), floor
    body = floor[:-len("(截)")]
    assert not body.rstrip().endswith(("·", "、", "：", ":")), floor


# ---- P3-2 webui 预览注与 @ 段粘连 ----
# （钉面随 r285 审校 P3-4 迁址：预览注改走 _append_before_at @ 前插
#  单源，前导段落分隔由该单源承担——锁定新形态的钉在
#  tests/test_r285_push.py::test_preview_note_before_at_segment，
#  旧「直拼+前导 \n\n」形态随改写一并禁复活。）


# ---- P3-3 邮件横幅口径词（消「真达标/已达标」一邮两词面）----

def test_email_banner_uses_scale_word_not_tier_word():
    """🚨/🎯 横幅主字=口径词「达标 · 可出手」：desp 正文头档位词
    「已达标——可出手」同屏并存时「真达标/已达标」两词一信。"""
    from core.notifier import _banner_html
    html = _banner_html("🚨 上海→乌鲁木齐 真达标 ￥1760")
    assert "达标 · 可出手" in html, html
    assert "真达标" not in html, html


# ---- P3-4 @ 段恒为消息末行 ----

def test_append_before_at_keeps_at_last():
    """详情链接/失败注插入尾部 @ 段之前：@ 是「谁被点名」的触达
    载体（atMobiles 高亮恒在最后一条消息段）。"""
    from core.alerter import _append_before_at
    desp = "正文\n\n@138****1234 "
    out = _append_before_at(desp, "[📲 完整详情](https://x.y)")
    assert out.index("完整详情") < out.index("@138"), out
    assert out.rstrip().endswith("@138****1234") or \
        "@138****1234" in out[out.index("@138"):], out


def test_append_before_at_without_at_tail():
    """无 @ 段尾部直拼（非达标轮 at_mobiles=None 路径零变形）。"""
    from core.alerter import _append_before_at
    desp = "正文段落"
    out = _append_before_at(desp, "注")
    assert out == "正文段落\n\n注", repr(out)


# ---- merged from tests/test_r302_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------- P3：星注换「·行情」 ----------

def test_mkt_note_is_middle_dot_word():
    """常量钉：星注定义式退役（裸 * 强调字符禁复活），新词面=·+行情。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert '"*" + _MKT_SHORT' not in src, (
        "星注定义式复活：裸 * 是钉钉 markdown 强调标记字符（跨段双星"
        "结构可达面），短注分隔符必须用非强调字符")
    assert A._MKT_NOTE == "·" + A._MKT_SHORT, (
        "_MKT_NOTE 词面漂移：预期「·行情」（· 计宽与 * 同 1 半角，"
        "降级链档位边界零移动）")


def test_mkt_note_width_neutral():
    """宽度中性钉：· 与 * 同按 1 半角计——换词不得移动降级链档位
    （r260 网格形态的边界样本须保持原档位判定）。"""
    assert A._dw("·") == A._dw("*") == 1, (
        "分隔符计宽漂移：· 须与 * 同按 1 半角（审校 S2/S7 网格，"
        "降级链档位边界零移动的前提）")
    assert A._dw(A._MKT_NOTE) == 5, "·行情 应=1+4（行情两全角）半角"


def test_mini_split_strips_middle_dot_note():
    """行为钉：去注档剥掉新词面干净——剥段消费与产出同出单源
    （_mini_split 消费 _MKT_NOTE，常量改版自动跟随；此钉锁真实常量
    形态的端到端产物，与 r262 的 monkeypatch 形态钉互补）。"""
    # r260 已验证的单段形态：head+seg 原样超宽、剥注后达标（恰走
    # 去注档；双段样本剥注仍超会正确走拆行档——词面保留非分叉）
    head = "📍 10/06　"
    seg = (A.tier_dot(False, -655, 19000) + "直飞 ￥12345 低￥6655"
           + A._MKT_NOTE)
    assert A._disp_dw(head + seg) > 40, "样本未进降级面"
    assert A._disp_dw(head + seg.replace(A._MKT_NOTE, "")) <= 40, \
        "样本未卡「去短注档」（剥注后须达标）"
    out = A._mini_split(head, [seg])
    assert A._MKT_NOTE not in out, "去注档未剥新词面（剥段与产出分叉）"
    assert "*" not in out, "产物残留裸 *（强调字符零容忍）"
    assert "￥6655" in out, "差额词必须完整在场"


def test_transcribe_strip_table_follows():
    """跨模块钉：notifier 剥注表对「·行情」剥注干净（ntfy/短信/TTS
    转写前消费链自动跟随单源，无 * 残留）。"""
    import core.notifier as N
    from core.notifier import _MKT_NOTE_DUPS
    seg = "🎯 直飞 ￥1701 低￥199" + A._MKT_NOTE
    out = seg
    for note in _MKT_NOTE_DUPS:
        out = out.replace(note, "")
    assert A._MKT_NOTE not in out, "剥注表未跟随新词面"
    assert "*" not in out and "·行情" not in out


# ---------- P2-1：_top3_blocks 组头守卫走加粗投影 ----------

def test_top3_head_guard_uses_bold_projection():
    """源码钉：组头降档判定与 _section_title 同律（_dw_bold 判例），
    旧 _disp_dw 形态禁复活。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert "if _disp_dw(head) > 40:" not in src, (
        "组头守卫未走加粗投影：#### 标题按加粗字模渲染，_disp_dw 低估"
        "数字密集标题 11% 膨胀（39 判过实超 41.08 泄漏窗）")
    assert "if math.ceil(_dw_bold(head)) > 40:" in src, \
        "组头守卫未收口 _dw_bold 判例律"


def test_bold_projection_gap_sample_in_leak_window():
    """自证钉：泄漏窗样本「旧模型判过、新模型判拦」——证明两模型
    在该形态上有可分辨输出，测试具备捕获力（守卫对齐后该形态降档）。"""
    head = "#### ✈️ 直飞最优TOP5（线￥1900） · 9/9"
    assert A._disp_dw(head) <= 40, "样本须落旧模型判过带"
    assert math.ceil(A._dw_bold(head)) > 40, "样本须落新模型拦截带"


# ---- merged from tests/test_r308_push.py ----

# 审校工单恰卡实锤样本（_disp_dw=40 旧模型放行、粗字模投影 41.31）
_BOLD_SAMPLE = ("[**直飞 ￥2400**](https://q.example/a)"
                "　线￥1900　差￥500（26%）")
_BOLD_SAMPLE_FB = "[**直飞 ￥2400**](https://q.example/a)　线￥1900　差￥500"


def test_bold_projection_reveals_exact_fit_overflow():
    """粗字模投影揭穿恰卡放行：_disp_dw 旧模型 40 放行（缺陷前提），
    bold 投影 ceil 后 42 超红线——膨胀只来自 ASCII 段（CJK/全角不膨胀）。"""
    assert _disp_dw(_BOLD_SAMPLE) == 40
    assert _disp_dw(_BOLD_SAMPLE, bold=True) > 40


def test_fit_line_bold_param_downgrades_exact_fit_row():
    """行为级：恰卡加粗行 bold=True 选档时落 fallback（丢尾注档），
    bold 缺省 False 维持旧行为放行（非加粗行零回归）。"""
    assert _fit_line(_BOLD_SAMPLE, fallbacks=[_BOLD_SAMPLE_FB],
                     bold=True) == _BOLD_SAMPLE_FB
    assert _fit_line(_BOLD_SAMPLE,
                     fallbacks=[_BOLD_SAMPLE_FB]) == _BOLD_SAMPLE


def test_bold_projection_cjk_only_row_unchanged():
    """纯 CJK 加粗行投影恒等（粗字模只膨胀 ASCII advance，CJK 方块字
    两权重恒等）——纯中文行不因 bold 判定被白白降档（_dw_bold 判例的
    同族保证）。注：半角空格属 ASCII，粗字模下同样膨胀（真实渲染
    语义），纯 CJK 样本不含空格。"""
    cjk_bold = "[**直飞低价蹲守提醒**](https://q.example/a)"
    assert _disp_dw(cjk_bold, bold=True) == _disp_dw(cjk_bold)


def test_kpi_block_bold_row_uses_projection():
    """端到端：KPI 行1 加粗形态（链接壳+全角空格分隔）的恰卡样本
    经守卫选档时按粗字模投影降档——构造恰卡 40 形态（无 emoji 点，
    与 _BOLD_SAMPLE 同构的 KPI 链接壳形态）断言降档含守卫后的完整行。"""
    s = ("[**直飞 ￥2400**](https://q.example/flights?a=1)"
         "　线￥1900　差￥500（26%）")
    plain_w = _disp_dw(s)
    bold_w = _disp_dw(s, bold=True)
    assert plain_w <= 40 < bold_w  # 恰卡带：旧模型放行、投影揭穿
    fb = "[**直飞 ￥2400**](https://q.example/flights?a=1)　线￥1900　差￥500"
    assert _fit_line(s, fallbacks=[fb], bold=True) == fb


def test_bold_factor_in_valid_band():
    """膨胀因子在实测带内（1.05-1.15 夹取档）——投影不是恒等伪装。"""
    from core.alerter import _TITLE_BOLD_ASCII
    assert 1.05 <= _TITLE_BOLD_ASCII <= 1.15
    assert math.isclose(
        _disp_dw("￥2400", bold=True) / max(1, _disp_dw("￥2400")),
        1.0, abs_tol=0.5)  # 短串不炸


# ---- merged from tests/test_r318_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_jump_word_bare_platform_name():
    """源码钉：链接词=渠道名裸词（multi+legacy 两处同批）；「打开」
    前缀形态禁复活。"""
    src = Path(os.path.join(_ROOT, "core", "alerter.py")).read_text(
        encoding="utf-8")
    assert "jump = f\"[{plat_cn}]({_jump_url})\"" in src, "multi 版链接词漂移"
    assert "jump = f\"[{plat_cn}]({_jump})\"" in src, "legacy 版链接词漂移"
    assert "[打开{plat_cn}]" not in src, "「打开」前缀形态回潮"


def test_five_digit_spread_keeps_jump_link():
    """行为复算钉：5 位差额最坏形态（rd 全形+5 位线 low）下，剥名
    保链档必须真实落位（修前 41/40 恰超被跳档、链接缺席）。"""
    rd = "SHA→URC 10/16"
    low = "低￥97889"
    jump = "[去哪儿](https://flight.qunar.com/view/xyz)"
    tail = _fit_line(
        f"> {rd} · 去哪儿 · {low} · {jump}",
        fallbacks=[f"> {rd} · {low} · {jump}",
                   f"> {rd} · 去哪儿 · {low}",
                   f"> {rd} · {low}"])
    assert "](http" in tail, tail   # 链接动作件在场
    assert _disp_dw(tail) <= 40, (tail, _disp_dw(tail))


# ---- merged from tests/test_r321_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r321pf")


def _route_win():
    """窗口头路线夹具：上海→海口 19:00 后出发（实发 M1 同构）。"""
    return _R(from_code="HAK", to_code="SHA", from_name="上海",
              to_name="海口", dates=["2027-01-29"],
              alert_direct=1900, alert_transfer=1700,
              dep_time_min="19:00", dep_time_max="")


def _sec_dual():
    """双类在场：直飞+中转行情最优（均超线→未达标→slim 路径）。"""
    return [{"date": "2027-01-29",
             "best_direct": {"price": 1950, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar", "_stale_h": 4.2},
             "best_transfer": None,
             "best_transfer_mkt": {"price": 1780, "name": "CZ6976转",
                                   "depTime": "12:05", "arrTime": "23:50",
                                   "transCity": "郑州",
                                   "_platform": "ctrip"},
             "seen_plats": ["qunar", "ctrip"]}]


def test_heartbeat_slim_win_head_price_survives():
    """M1：窗口头路线 slim 轮价格判据必须存活（剥窗档）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    p = a._digest_payload([(_route_win(), _sec_dual())],
                          fresh=False, with_tables=False)
    body = [ln for ln in p["desp"].splitlines()
            if ln.startswith(">") and "上海→海口" in ln]
    assert body, p["desp"][:400]
    ln = body[0]
    assert "￥" in ln, f"窗口头路线价格判据全灭（裸身份行）: {ln!r}"
    assert _disp_dw(ln) <= 40, f"摘要行超宽: {ln!r}"
    # 剥窗后日期仍在（同 OD 无窗行的辨识信息）
    assert "01/29" in ln, f"日期被剥（辨识信息丢失）: {ln!r}"
    # 触发前提自检：带窗+价形态在旧链中间档下确实超线
    # （50/40 数学不可达=本案成立条件，夹具漂移时此钉先红）
    assert _disp_dw(f"> 上海→海口（19:00后出发） 01/29 ｜ 直飞 ￥1950") > 40, \
        "夹具已不触发（窗口头变窄？样本需随形态演进重选）"


def test_heartbeat_slim_win_head_floor_semantics():
    """地板语义双面：真实城市名域（≤4 字/名）剥窗档恒可达（带价
    落位）；病理长名全链超线时 _fit_line 全超取末档=带窗裸身份
    （地板档形态不变；宽度在病理配置域可超——十九§15 地板档自身
    超预算=备案形态，恒达标律约束现实可达域）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    # 真实域：城市对（2+4 全角，剥窗带价实测 ≈37/40 落位带——
    # 4+4 组合实测 41/40 恰卡出带，样本按真实计宽网格选形）
    r = _R(from_code="LXA", to_code="DSN", from_name="拉萨",
           to_name="鄂尔多斯", dates=["2027-01-29"],
           alert_direct=1900, alert_transfer=1700,
           dep_time_min="19:00", dep_time_max="")
    p = a._digest_payload([(r, _sec_dual())],
                          fresh=False, with_tables=False)
    body = [ln for ln in p["desp"].splitlines()
            if ln.startswith(">") and "拉萨→鄂尔多斯" in ln]
    assert body, p["desp"][:400]
    ln = body[0]
    assert "￥" in ln and _disp_dw(ln) <= 40, \
        f"真实域剥窗档未落位（价格判据丢失）: {ln!r}"
    assert "（19:00后出发）" not in ln, \
        f"真实域应走剥窗档（窗口头先丢）: {ln!r}"
    # 病理域：配置自由文本超长名 → 全链超线 → 末档带窗裸身份
    r2 = _R(from_code="URC", to_code="SHA",
            from_name="乌鲁木齐地窝堡国际机场", to_name="鄂尔多斯伊金霍洛",
            dates=["2027-01-29"], alert_direct=1900, alert_transfer=1700,
            dep_time_min="19:00", dep_time_max="")
    p2 = a._digest_payload([(r2, _sec_dual())],
                           fresh=False, with_tables=False)
    body2 = [ln for ln in p2["desp"].splitlines()
             if ln.startswith(">") and "地窝堡" in ln]
    assert body2, p2["desp"][:400]
    ln2 = body2[0]
    # c330 审校 C1 再改写：链中截名保价档（_bare_price_line）在该域
    # 可达并先于 bare 被选中——截名机制（_clip_dw 浮点逐字截+剥未配
    # 对「（」）前移一步保价格判据（十九§9「价格判据最后丢」；r321/
    # r322 两轮修复间的名域残留空档）。裸身份地板档仍在链尾兜底
    # （head 全舍+预算 <2 的病理形态），选中档=截名+日期+直飞价
    assert ln2 == "> 乌鲁木齐地窝堡 01/29 ｜ 直飞 ￥1950", \
        f"病理域应走截名保价档（价格判据存活）: {ln2!r}"
    assert _disp_dw(ln2) <= 40, f"截名保价档守宽: {ln2!r}"
    assert _disp_dw(ln2) <= _disp_dw(
        "> 乌鲁木齐地窝堡国际机场→鄂尔多斯伊金霍洛（19:00后出发） 01/29"), \
        f"剥窗地板档不得长于带窗形态: {ln2!r}"


def test_source_pin_win_bare_tier():
    """源码钉：剥窗保价档在案（防四档链回退三档）。r322 起挂载面
    从双类域扩至 bd-only（`if bd and dw:` 门），钉锁 f-string 产出
    字面本体（append 调用换行形态不参与）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "alerter.py"),
        encoding="utf-8").read()
    assert 'f"> {head[:-len(dw)]} {d_short} ｜ {bits[0]}"' in src, (
        "剥窗保价档缺失（M1 复活：窗口头路线价格判据恒灭）")


def test_source_pin_heartbeat_style_wiring():
    """源码钉（Soldier Major-1 收口）：heartbeat_style 配置→构造接线
    在案——消费层三态语义完备，缺的是 main 构造一根线（配置 full/
    auto 将静默无效果=文档承诺不存在的可配置性）；示例键层级与生产
    config 一致（notifier 顶层，与 dingtalk 平级）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert 'heartbeat_style=str((ncfg or {}).get("heartbeat_style")' in src, (
        "heartbeat_style 配置线缺失（示例键=死键文档）")
    ex = open(os.path.join(root, "config.example.yaml"),
              encoding="utf-8").read()
    assert re.search(r"^    # heartbeat_style", ex, re.M), (
        "example 的 heartbeat_style 必须在 notifier 顶层（4 空格，"
        "与 dingtalk 平级；段内嵌套=层级错位接线也读不到）")


# ---- merged from tests/test_r330_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ────────────────── C1：截名保价档 ──────────────────

def test_c1_bare_price_line_longname_keeps_price():
    """长名域（乌鲁木齐→阿拉善左旗）：截名保价档 ≤40 且 ￥ 在场
    （旧链此域唯一可达的合规档是 bare 身份行，零价格）。"""
    from core.alerter import _bare_price_line
    line = _bare_price_line("乌鲁木齐→阿拉善左旗", "09/25", "直飞 ￥2451")
    assert "￥2451" in line, "价格判据不得蒸发：" + line
    assert _disp_dw(line) <= 40, line


def test_c1_bare_price_line_shortname_verbatim():
    """短名域零回归：head 预算内整名原样（与剥窗档产出同构）。"""
    from core.alerter import _bare_price_line
    line = _bare_price_line("上海→海口", "01/29", "直飞 ￥2000")
    assert line == "> 上海→海口 01/29 ｜ 直飞 ￥2000", line


def test_c1_slim_digest_longname_price_survives():
    """全链锚：slim 心跳降级链在长名域选中的行含价格（_fit_line 首
    合规选档语义下，截名保价档必须排在 bare 之前才可达）。"""
    from core.alerter import Alerter
    from core.models import Route

    class _NL:
        def warning(self, *a, **k):
            pass

        def info(self, *a, **k):
            pass

    al = Alerter(_NL(), storage=None, heartbeat_style="slim")
    route = Route(from_name="乌鲁木齐", to_name="阿拉善左旗",
                  from_code="URC", to_code="ALAA", dates=["2026-09-25"],
                  alert_direct=2500, alert_transfer=0)
    sec = {"date": "2026-09-25",
           "best_direct": {"price": 2451.0, "_stale_h": None},
           "best_transfer_mkt": None, "best_transfer": None}
    rs = [(route, [sec])]
    payload = al._digest_payload(rs, fresh=True, slim=True)
    body = payload["desp"].replace("\n", " ")
    assert "￥2451" in body, "slim 心跳长名域整行零价格（C1 病灶）：" + body[:300]


# ────────────────── C2：运维注冒号族地板档 ──────────────────

def test_c2_ops_colon_floor_keeps_payload():
    """冒号族地板档载荷优先：渠道+价格判据在场且 ≤40（旧地板产出
    「(截)」空载句）。"""
    fbs = _ops_fallbacks("乌→上 10/04 孤低价拦截×1：飞猪￥700")
    floor = fbs[-1]
    assert "飞猪￥700" in floor, "载荷（渠道￥价）不得全灭：" + floor
    assert _disp_dw(floor) <= 40, floor


def test_c2_ops_no_colon_family_unchanged():
    """无冒号族零回归：地板档仍走原「40−前缀−标记」逐字截。"""
    fbs = _ops_fallbacks("乌→上 10/04 直挂标注缺失·途牛")
    floor = fbs[-1]
    assert floor.endswith("(截)"), floor
    assert "直挂标注缺失" in floor, floor
    assert _disp_dw(floor) <= 40, floor


# ────────────────── C3：hits 头混合形态 ──────────────────

def test_c3_mixed_dualname_codeshare_keeps_code():
    """混合形态（双名+联程）剥名档超宽时，首名+首码档可达且被选中
    （航班号不整体消失）。走真实渲染入口 _hit_head_fbs + _fit_line。"""
    from core.alerter import _fit_line, _hit_head_fbs
    base = "> 🔥 **直飞 ￥46800**"
    nm = "新海航｜金鹏航空Y87519/海南航空HU7849"
    head = _fit_line(f"{base} {nm}", fallbacks=_hit_head_fbs(base, nm),
                     limit=39)
    assert "Y87519" in head or "HU7849" in head, \
        "航班号整体消失（C3 病灶）：" + head
    assert _disp_dw(head) <= 39, head


def test_c3_pure_codeshare_and_dualname_unchanged():
    """纯联程与纯双名形态零回归（else 分支与剥名档原样）。"""
    from core.alerter import _hit_head_fbs
    base = "> 🔥 **直飞 ￥800**"
    # 纯联程：保「/」前段
    fbs = _hit_head_fbs(base, "海南航空 HU7849/春秋9C8845")
    assert fbs[0] == f"{base} 海南航空 HU7849", fbs
    # 纯双名：保「｜」后段，无「/」不加档
    fbs2 = _hit_head_fbs(base, "新海航｜金鹏航空 Y87519")
    assert fbs2 == [f"{base} 金鹏航空 Y87519", base], fbs2


# ────────────────── C4：特价快讯币符与守卫 ──────────────────

def test_c4_special_push_fullwidth_and_guard():
    """特价快讯：币符统一全角 ￥（安全集在册）；附加段（折扣+航司）
    超宽剥尾保价判据。"""
    from core.specials import SpecialDeal, build_special_push
    from core.models import Route  # noqa: F401（占位防 import 顺序误删）
    watch = Route(from_name="上海", to_name="", from_code="SHA",
                  to_code="URC", dates=["2026-11-01"], alert_direct=0,
                  alert_transfer=0)
    d = SpecialDeal(src="tuniu", from_code="SHA", to_code="URC",
                    date="2026-11-01", src_price=480.0,
                    discount="2.1折｜含20kg托运｜免费退改｜选座",
                    airline="中国联合航空 KN5977 波音738")
    title, desp = build_special_push(watch, [(d, 450.0)])
    assert "¥" not in desp, "半角 ¥ 是全库唯一币符分叉（安全集外）"
    assert "￥450" in desp, desp
    for blk in desp.split("\n\n"):
        for ln in blk.split("\n"):
            if ln.startswith("￥"):
                assert _disp_dw(ln) <= 40, "价格行须守宽：" + ln


# ────────────────── C5：风暴标题 token 边界 ──────────────────

def test_c5_storm_title_no_half_date_token():
    """保尾切法的切点不得落在日期 token 中段（「11/等7条」悬垂）。"""
    import re
    t = ("🚨 达标！上→巴 11/16 直飞￥2306｜另监控 "
         "乌→上 10/16 · 乌→上 11/16 · 乌→沪 12/01 等3条")
    out = _storm_title(3, 3, t)
    assert out.endswith("等3条"), out
    assert not re.search(r"\d{1,2}/等", out), "半截日期悬垂：" + out


# ---- merged from tests/test_r333_push.py ----

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

def _cal_row(**over):
    """生产日历最低价行真实形态（webui /api/state best 直飞=日历最低价
    实锤；dep/arr 空、无 code、stopover/transCity 全缺省）。"""
    row = {"_platform": "fliggy", "price": 2765, "name": "日历最低价",
           "code": "", "depTime": "", "arrTime": "", "date": "2026-11-16"}
    row.update(over)
    return row


def test_fmt_flight_line_calendar_row_no_arrow_skeleton():
    line = Alerter._fmt_flight_line(dict(_cal_row()), idx=1)
    assert "→" not in line, "悬垂箭头假骨架：" + line
    assert "当日达" not in line, "假到达时刻尾注：" + line
    assert "￥2765" in line and "日历最低价" in line, \
        "价格+名字判据保留：" + line


def test_fmt_brief_calendar_row_no_arrow_skeleton():
    brief = Alerter._fmt_brief(dict(_cal_row()), budget=40)
    assert "→" not in brief, "悬垂箭头假骨架：" + brief
    assert "当日达" not in brief, "假到达时刻尾注：" + brief
    assert "￥2765" in brief, "价格判据保留：" + brief


def test_fmt_brief_calendar_transfer_row_no_arrow_skeleton():
    """无时刻行的中转分支守卫（transCity 在场走 _trans_city 单源中转
    分支；直飞分支由上两钉覆盖）——时刻档整段缺席后仍须落名字档/
    地板价档，不产「→」。"""
    brief = Alerter._fmt_brief(
        dict(_cal_row(_platform="qunar", price=12345,
                      transCity="郑州")), budget=40)
    assert "→" not in brief, brief
    assert "当日达" not in brief, brief
    assert "￥12345" in brief, brief


def test_fmt_flight_line_timed_row_unchanged():
    """有时刻行骨架不变（防误杀回归）：时刻对照旧在产物（_fmt_flight_line
    常态价带本就超宽剥「当日达」尾注=既有降级设计，不锁尾注锁骨架；
    _fmt_brief 行短，尾注在 full 档存活一并锁）。"""
    row = dict(_cal_row(code="HO1108", name="HO1108", price=276,
                        depTime="08:30", arrTime="11:20"))
    line = Alerter._fmt_flight_line(dict(row), idx=1)
    assert "08:30→11:20" in line, line
    brief = Alerter._fmt_brief(dict(row), budget=40)
    assert "08:30→11:20" in brief and "当日达" in brief, brief


def test_fmt_brief_calendar_worst_width_stays_clean():
    """最坏形态（5 位价宽恰卡预算零降级）仍不含假词面——守卫缺席
    时降级链救不了它（审校实证形态）。"""
    brief = Alerter._fmt_brief(
        dict(_cal_row(price=12345, name="日历最低价")), budget=40)
    assert "→" not in brief and "当日达" not in brief, brief
    assert "￥12345" in brief, brief


# ---- merged from tests/test_v15106_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_push_history_probe_redirect(tmp_path, monkeypatch):
    """PUSH_HISTORY_FILE 指向独立文件：记录落独立账本、主账本不产生。"""
    probe = tmp_path / "probe.jsonl"
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(probe))
    # 默认账本路径按 CWD 解析（logs/push_history.jsonl）；不切 CWD 时
    # 「主账本不产生」断言恒真（默认写根本不会落进 tmp_path）——切到
    # tmp_path 后，若重定向回归失效，默认写会落 tmp_path/logs，该断言
    # 才具备一跑即红的判别力
    monkeypatch.chdir(tmp_path)
    _append_push_history("t", "d", True, ch="probe")
    assert probe.exists()
    rec = json.loads(probe.read_text(encoding="utf-8").splitlines()[0])
    assert rec["ch"] == "probe"
    assert not (tmp_path / "logs" / "push_history.jsonl").exists()


def test_push_history_default_path_unchanged(tmp_path, monkeypatch):
    """生产形态入口（main.py）不设环境变量：默认 logs/push_history.jsonl
    行为不变（r235 写入门后 argv 需模拟生产形态；门本身另钉）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PUSH_HISTORY_FILE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py"])
    _append_push_history("t", "d", True, ch="dingtalk")
    rec = json.loads(
        (tmp_path / "logs" / "push_history.jsonl")
        .read_text(encoding="utf-8").splitlines()[0])
    assert rec["ch"] == "dingtalk"


# ---- merged from tests/test_v15111_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rsrc():
    return open(os.path.join(_BASE, "report.py"), encoding="utf-8").read()


def test_risk_slot_in_table_png():
    """ctrip 高风险政策透明标记入总表图决策次行（三端协议渲染门
    收口：爬虫键 ↔ webui 白名单/价格格徽标 ↔ PNG 槽——agePolicy
    同族「能不能买/买了有何风险」决策词三处全落，缺 PNG 槽=推送图
    面缺失该信号、图内信息容量低于被撤文本版）。PNG 端无 ⚠：
    U+26A0 在 msyh 无字形渲染 tofu 方框（E-1 同律），词面自带
    「高风险」醒目字。"""
    src = _rsrc()
    assert '("risk", str(f.get("riskPolicy") or "").strip())' in src, \
        "riskPolicy 未入总表图次行（三端渲染门缺角）"
    assert "⚠{f['riskPolicy']}" not in src, "PNG 端 ⚠ 残留（tofu 方框）"


def test_drop_chain_last_tier_drops_risk():
    """超宽极端行 risk 入末档丢档链：与 labels/age 同族增益词
    （「高风险政策」5 全角恒占槽），五档全败的极端超宽行若不入链
    则直接回退单行整截、恒保组（准点/餐食/托运/共享/余票）一并
    蒸发——丢增益词保恒保组，次行仍可决策。"""
    src = _rsrc()
    # 正则容忍元组换行/空白变化（源码串钉的格式化敏感面）；
    # tkrisk（「临近起飞需确认值机」8 全角）与 age/risk 同族增益词，
    # r248 随槽位扩员入末档丢档链
    assert re.search(
        r'"labels",\s*"age",\s*"risk",\s*"tkrisk",\s*"carryon', src), \
        "丢档链末档未含 risk/tkrisk（超宽行恒保组被整截）"


def test_alert_body_filters_at_mobile():
    """强提醒正文（电话/短信/ntfy）滤 @手机号 行：TTS 不读 12 位数字，
    900 字额度不被占；价格主判据行保留。"""
    from core.notifier import _alert_body
    desp = ("#### 🚨 达标！上→乌 10/06 直飞 ￥1264\n\n"
            "直飞 **￥1264**　线￥1900　差￥636\n\n"
            "@13800138000 ")
    body = _alert_body(desp)
    assert "13800138000" not in body, body
    assert "￥1264" in body, body


def test_wintoast_plain_filters_at_mobile():
    """Windows 弹窗第二行同样滤 @手机号 行（尾行噪音）。"""
    from core.notifier import WindowsToastNotifier as W
    p = W._plain("🚨 达标！上→乌 10/06\n\n直飞 **￥1264**\n\n@13800138000 ",
                 200)
    assert "13800138000" not in p, p
    assert "￥1264" in p, p


def test_ops_note_fliggy_not_maintaining():
    """fliggy round-miss 无数据：词面=「飞猪」不带「(维护中)」括注——
    PC SSR 复活后维护态语义已失真（限流单轮缺失=下轮自然回）。"""
    from core.alerter import Alerter
    al = Alerter(logging.getLogger("t15111"))
    route = SimpleNamespace(from_name="上海", to_name="乌鲁木齐")
    rs = [(route, [{"date": "2026-10-06",
                    "seen_plats": ["ctrip", "qunar", "tuniu",
                                   "tongcheng"]}])]
    notes = al._ops_notes(rs)
    assert notes and "飞猪" in notes[0], notes
    assert "维护中" not in notes[0], notes


def test_ops_note_mixed_keeps_others_plain():
    """其他渠道名照常直出（括注删除不得伤及词表主体）。"""
    from core.alerter import Alerter
    al = Alerter(logging.getLogger("t15111"),
                 platforms=["ctrip", "qunar", "tuniu", "tongcheng",
                            "fliggy"])
    route = SimpleNamespace(from_name="上海", to_name="乌鲁木齐")
    rs = [(route, [{"date": "2026-10-06", "seen_plats": []}])]
    notes = al._ops_notes(rs)
    assert notes, notes
    for p in ("携程", "去哪儿", "途牛", "同程", "飞猪"):
        assert p in notes[0], (p, notes)
    assert "维护中" not in notes[0], notes


# ---- merged from tests/test_v15127_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tier_dot_tier_ladder():
    # 四档梯度同向：🎯=达标口径、🟩=行情破线（含恰达线 diff==0）、
    # 🟨=擦边（≤NEAR_RATIO）、超线默认态不加点
    assert tier_dot(True, -100, 2000) == "🎯 "
    assert tier_dot(True, 600, 2000) == "🎯 "     # qual 判定优先于 diff
    assert tier_dot(False, -100, 2000) == "🟩 "
    assert tier_dot(False, 0, 2000) == "🟩 "      # 恰达线非达标=行情档
    assert tier_dot(False, 60, 2000) == "🟨 "     # 3% 擦边
    assert tier_dot(False, 600, 2000) == ""       # 30% 超线不加点


def test_tier_dot_zero_threshold_safe():
    # th=0（未设线）：只认 qual，不做除法
    assert tier_dot(True, -100, 0) == "🎯 "
    assert tier_dot(False, -100, 0) == ""


def test_tier_dot_literal_purge():
    # 手抄字面串归零：带尾空格的档位 emoji 字面在两文件源码中只剩
    # _TIER_TABLE 定义（无尾空格）——全部消费点走 TIER_EMOJI 投影
    for rel in ("core/alerter.py", "report.py"):
        src = open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        for ch in ("🎯", "🟩", "🟨"):
            hits = re.findall('"%s "|\'%s \'' % (ch, ch), src)
            assert hits == [], "%s 残留手抄 %s" % (rel, ch)


def test_report_kpi_mark_via_projection():
    # report._kpi 的加粗判定同步单源：不再比较 emoji 字面
    src = open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()
    assert 'mark == "🎯 "' not in src
    assert 'TIER_EMOJI["qual"] + " "' in src


def test_preview_placeholder_line_width():
    # P3-8：预览占位注整行（含 "> " 前缀）≤40 半角（20 全角）。
    # r283 P3-2：预览注自带前导段落分隔；r285 审校 P3-4：改走
    # _append_before_at @ 前插单源（段界由单源承担），词面与行宽语义不变
    src = webui_full_src()
    m = re.search(r'_append_before_at\(\s*p\["desp"\],\s*"> （(预览态[^）]*)）',
                  src)
    assert m, "预览占位注词面不在场（或未走 @ 前插单源）"
    line = "> （" + m.group(1) + "）"
    assert _dw_line(line) <= 40, "占位注整行 %s 宽=%d" % (
        line, _dw_line(line))
    # 旧超宽词面退场
    assert "实发在此位置附整表 PNG" not in src


# ---- merged from tests/test_v15130_push.py ----

def test_near_txt_prefix_on_tier_projection():
    body = inspect.getsource(_near_txt)
    assert 'TIER_FULL["near"]' in body, \
        "_near_txt 擦边前缀未挂 TIER_FULL 投影（档位词改版日漂离图例）"


def test_near_txt_output_shape_unchanged():
    """投影重构不动输出：边界契约（≤0.5 显式含界）与普通档词面维持。"""
    assert _near_txt(0.0021) == TIER_FULL["near"] + "不足1%"
    assert _near_txt(0.005) == TIER_FULL["near"] + "不足1%"
    assert _near_txt(0.006) == TIER_FULL["near"] + "1%"
    assert _near_txt(0.09) == TIER_FULL["near"] + "9%"


# ---- merged from tests/test_v1563_push.py ----

def test_all_member_send_accept_launch():
    for cls in (DingTalkNotifier, ServerChanNotifier, EmailNotifier,
                NtfyNotifier, WindowsToastNotifier, CompositeNotifier):
        params = inspect.signature(cls.send).parameters
        assert "launch" in params, f"{cls.__name__}.send 缺 launch 形参"


# ---- 横幅词表对齐真实 title（push_history 941 条实发词表） ----------

def test_banner_real_title_prefixes():
    from core.notifier import _banner_html
    real = (("🚨 达标！上→乌 10/05 真达标￥1850", "真达标"),
            ("🔔 持续达标·上→乌 10/05 真达标￥1850", "持续达标"),
            ("❌ 全部未达标｜最近 上→乌 10/05 直飞差￥400", "未达标"),
            # ↩️ 横幅词面=「回落出线」（r235 推送 P2-2 与标题/正文头
            # 同语言；旧断言「达标回落」锁定的正是当轮修掉的一邮两词面）
            ("↩️ 回落出线｜最近 上→乌 10/05", "回落出线"))
    for t, word in real:
        h = _banner_html(t)
        assert "#eef4fc" not in h, f"{t} 落默认蓝横幅（色识态失效）"
        assert word in h
    # 🎯🟩🟨🟨 档位键维持（desp 场景），词面挂 TIER_FULL 投影
    assert "行情破线" in _banner_html("🟩 机票监控｜x")


# ---- 降级轻壳 desp 单渲染 ----------

def test_shell_degraded_renders_desp_once():
    from core.notifier import _email_shell_html
    desp = "#### 状态唯一头\n\n正文标记XYZ\n\n- 条目一"
    h = _email_shell_html("❌ 机票监控｜t", desp, with_snapshot=False)
    assert h.count("状态唯一头") == 1
    assert h.count("XYZ") == 1
    assert h.count("自动推送") == 1   # 页脚不重复
    assert "快照生成失败" in h


# ---- Email 通道落盘 push_history ----------

def test_email_writes_push_history(tmp_path, monkeypatch):
    import json as _j
    import logging
    import core.notifier as cn
    monkeypatch.chdir(tmp_path)

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def sendmail(self, *a):
            pass

    monkeypatch.setattr(cn.smtplib, "SMTP_SSL", _FakeSMTP)
    n = EmailNotifier("smtp.163.com", 465, "a@163.com", "pw",
                      "b@163.com", logging.getLogger("t"))
    assert n.send("标题", "内容") is True
    # 落账读 conftest autouse 重定向路径（写读同源；曾读 chdir 默认
    # logs/ 路径与自律重定向错位 FileNotFoundError）
    rec = _j.loads(open(os.environ["PUSH_HISTORY_FILE"],
                        encoding="utf-8").read().strip().splitlines()[-1])
    assert rec["ch"] == "email" and rec["ok"] is True


# ---- 邮件 Date/Message-ID 头 ----------

def test_email_date_msgid_headers():
    import logging
    n = EmailNotifier("smtp.163.com", 465, "a@163.com", "pw",
                      "b@163.com", logging.getLogger("t"))
    msg = n._build_msg("t", "d")
    assert msg["Date"] and msg["Message-ID"]
    assert "163.com" in msg["Message-ID"]


# ---- 有序列表正则不吞「N.数字」 ----------

def test_md_ol_regex_not_eat_decimal():
    from core.notifier import _md_to_html
    h = _md_to_html("3.9折 限时")
    assert "<ol" not in h and "3.9折" in h
    h2 = _md_to_html("1. 行李直达")
    assert "<ol" in h2 and "<li>行李直达</li>" in h2


# ---- Composite 成员异常计入连败 ----------

def test_composite_counts_member_exception_streak():
    import logging

    class Boom:
        def __init__(self):
            self._fail_streak = 3

        def send(self, *a, **k):
            raise RuntimeError("x")

    class OkCh:
        def __init__(self):
            self._fail_streak = 0

        def send(self, *a, **k):
            return True

    boom, okch = Boom(), OkCh()
    c = CompositeNotifier([boom, okch], logging.getLogger("t"))
    assert c.send("t", "d") is True          # 邮件成功聚合仍 True
    assert boom._fail_streak == 4            # 异常路径计入连败（可弹窗）


# ---- emailshot 空配置态排除（源钉） ----------

def test_emailshot_wait_excludes_unconfigured():
    src = open("core/emailshot.py", encoding="utf-8").read()
    assert "未配置" in src


# ---- M-2 邮件按钮 launch 回环过滤（源钉） ----------

def test_alerter_send_launch_loopback_filtered():
    import re
    src = open("core/alerter.py", encoding="utf-8").read()
    n = len(re.findall(
        r"launch=\(launch if self\._launch_public\(\) else \"\"\)", src))
    assert n >= 2, \
        f"alerter launch 过滤点仅 {n} 处（应 ≥2：聚合主路径+报告推送）"
    assert not re.search(r"notifier\.send\([^)]*launch=launch\)", src, re.S), \
        "notifier.send 存在裸 launch=launch 透传（回环死链回潮）"


# ---- 挂账① 「另监控 等 N 条」预算拼接 ----------

def test_rest_seg_budget():
    from core.alerter import _rest_seg
    base = "❌ 全部未达标｜最近 上→乌 10/05 直飞差￥400"
    out = _rest_seg(base, ["上→乌 10/06"] * 5)
    assert len(out) <= 60 and out.startswith(base)
    assert "另监控" in out and "等" in out and "条" in out
    out2 = _rest_seg(base, ["乌→上 10/06"])
    assert out2.endswith("｜另监控 乌→上 10/06") and "等" not in out2
    assert _rest_seg(base, []) == base


# ---- merged from tests/test_v1579_push.py ----

def test_gap_txt_tier_projection():
    """①恰达线词面=投影非字面。"""
    assert gap_txt(1900, 1900, True) == TIER_FULL["qual"]
    assert gap_txt(1900, 1900, False) == TIER_FULL["mkt"]
    assert "TIER_FULL" in inspect.getsource(A.gap_txt), \
        "gap_txt 恰达线词面仍为字面直写（改 _TIER_TABLE 必漏此处）"


def test_alert_body_strips_warning_sign():
    """②行中 ⚠️ 剥净（含 VS16 合成符与裸符），TTS/短信不读「警告符号」。"""
    desp = ("直飞达标 低￥120，建议出手\n\n"
            "比价离群 ⚠️口径差异 已标注\n\n"
            "- 渠道 最低 ￥880")
    assert "⚠" not in _alert_body(desp)


def test_dingtalk_history_has_channel(tmp_path, monkeypatch):
    """③钉钉落史带 ch="dingtalk" 且收口到 _append_push_history 单源。"""
    monkeypatch.chdir(tmp_path)
    _append_push_history("t", "d", True, ch="dingtalk")
    # 读 conftest autouse 重定向路径（写读同源）
    with open(os.environ["PUSH_HISTORY_FILE"], encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert rec["ch"] == "dingtalk"
    src = open(N.__file__, encoding="utf-8").read()
    assert ('_append_push_history(title, text, ok, ch="dingtalk"') in src, \
        "钉钉落史应落 text（实收形态：截断轮存截断后文本与群内一致）"
    assert '"ok": ok, "title": title, "desp": desp}' not in src, \
        "钉钉内联落史块应删除（无 ch 字段的旧形态）"


# ---- merged from tests/test_v162_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ALERTER = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "core", "alerter.py")
_REPORT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "report.py")
_NOTIFIER = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "core", "notifier.py")


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ----：总表图 _plan_sub 缩共享产出错误航班号（数字头二字码被
# 吞首位：9C8845→C8845，3U/8L 同病）——错误值违反宁缺勿错 ----

def test_plan_sub_share_short_digit_head_code():
    src = _src(_REPORT)
    # 旧正则不得回潮（[A-Z] 开头吞掉 9C/3U/8L 的数字头）
    assert '([A-Z][A-Z0-9]*\\d{3,4})$' not in src
    assert '([A-Z0-9]{2}\\d{3,4})$' in src
    # 同式功能钉：数字头二字码/常规二字码全还原
    pat = re.compile(r"([A-Z0-9]{2}\d{3,4})$")
    for full, want in (("共享·春秋航空9C8845", "9C8845"),
                       ("共享·四川航空3U8845", "3U8845"),
                       ("共享·祥鹏航空8L9888", "8L9888"),
                       ("共享·吉祥航空HO1108", "HO1108"),
                       ("共享·南方航空CZ6798", "CZ6798")):
        m = pat.search(full)
        assert m and m.group(1) == want, full


# ----：ops_notes 文本回退行「> ⚠️ 」前缀未入 _fit_line 量纲
# （重放实测 41 半角超宽行， 同病漏网）----

def test_ops_notes_fallback_prefix_in_quantity():
    src = _src(_ALERTER)
    assert '"> ⚠️ " + _fit_line(' not in src


# ----：持续达标标题与航线缩写粘连（生产实发
# 「🔔 持续达标上→乌 09/25」扫读歧义）----

def test_sticky_title_separator():
    src = _src(_ALERTER)
    assert '"🔔 持续达标·"' in src
    assert 'else "🔔 持续达标"' not in src


# ----：标题 60 半角硬截断曾静默丢尾（push_history 62 字符
# 实发实证）——超限「另监控」段整段降级 ----

def test_title_overflow_drops_other_monitor_segment():
    src = _src(_ALERTER)
    assert 'split("｜另监控 ")' in src


# ----：_alert_body 装饰剥离清单补 🔔/📲/👉（达标主路径
# 直达 TTS/短信；💰/⚖️ 图挂兜底路径可达）----

def test_alert_body_strips_missing_decorations():
    body = _alert_body("#### 🔔 持续达标（电话已提醒过）\n\n"
                       "[📲 完整详情（点击直达）](x)\n\n"
                       "[👉 在去哪儿查看详情](y)\n\n💰⚖️")
    for e in ("🔔", "📲", "👉", "💰", "⚖️"):
        assert e not in body, e
    # 档位转写词不受影响（勿动已转写的 🎯🟩🟨🔥）
    assert "持续达标（电话已提醒过）" in body


# ----：日报缺图对账行「> 」前缀未入量纲（同家族）----

def test_daily_noline_prefix_in_quantity():
    src = _src(_REPORT)
    assert '"> " + _fit_line(' not in src


# ----：钉钉 desp 尾空段收口（图片行后「\n\n」尾随空段全量
# 存在，零信息损失仅末尾留白）。只剥换行：@手机号 段尾随空格是
# @ 高亮组成部分不可吞（推送审校 P1-1 修正 rstrip() 副作用回退）----

def test_dingtalk_desp_trailing_blank_stripped():
    src = _src(_NOTIFIER)
    assert '(desp or title or "").rstrip("\\n")' in src


# ---- merged from tests/test_v170_push.py ----

# ---- _fmt_brief 降级链 ----------

def test_brief_mid_tier_keeps_times_normal_row():
    """常规行（东航短名）中档须携双时刻且 ≤40——修复前恒 41 落末档。"""
    f = {"price": 990, "name": "东航 MU5801", "depTime": "08:00",
         "arrTime": "12:30", "transCity": "西安", "layoverT": "2:15"}
    line = Alerter._fmt_brief(f)
    mid = "￥990 中转东航 MU5801 08:00→12:30"
    assert _disp_dw(mid) <= 40
    assert line == mid, "中档时刻仍死: %r" % line


def test_brief_direct_mid_tier_strips_daynote():
    """直飞分支中档剥「当日达」尾注：短名行入选，长名行安全落末档。"""
    f = {"price": 990, "name": "东航 MU5801", "depTime": "08:00",
         "arrTime": "12:30", "stopover": False}
    assert Alerter._fmt_brief(f) == "￥990 直飞东航 MU5801 08:00→12:30"
    long_f = dict(f, name="中国联合航空 KN5901", price=9900)
    out = Alerter._fmt_brief(long_f)
    assert _disp_dw(out) <= 40 and "12:30" not in out, \
        "长名行应落末档保价与航司: %r" % out


# ---- ops 回退降级链（_ops_fallbacks 真执行级） ----------

def test_ops_multi_channel_keeps_head():
    """生产形态「无数据：」短名渠道在首（platforms 顺序去哪儿常态靠前）：
    降级档保首渠道名（原冒号后清零）。"""
    n = "上→乌 09/25 无数据：去哪儿、飞猪(维护中)、携程"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40
    assert "去哪儿" in out, "首渠道名被清零: %r" % out


def test_ops_fliggy_note_first_falls_to_first_channel_tier():
    """「飞猪(维护中)」12 半角在首：k 档(带截)超预算落首渠道让位档
    （r220 校准补：渠道名优先于截标记，(截) 缺席由控制台对账兜底）——
    词面全保不塌地板。"""
    n = "上→乌 09/25 无数据：飞猪(维护中)、去哪儿"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40 and "无数据：" in out \
        and "飞猪(维护中)" in out


def test_ops_no_colon_keeps_head18_floor():
    """M1 地板：无冒号形态（直挂标注缺失）末档截前 18 字符，
    路由/日期/事由保留——修复前该形态曾塌「> ⚠️ （截）」全灭。"""
    n = "北→上 09/22 中转直挂标注缺失·达标判定失效"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40
    assert "北→上" in out and "中转直挂标注缺失" in out, \
        "无冒号地板退化: %r" % out


def test_ops_isolated_lowprice_floor():
    """生产形态「孤低价拦截×N：」（head 26 半角）：渠道名超预算塌前缀
    地板（与旧版同地板），词面前缀+留痕保，渠道全量对账循控制台。"""
    n = "上→乌 09/25 孤低价拦截×3：飞猪￥9900、去哪儿￥9500"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40
    assert "孤低价拦截×3：" in out and "(截)" in out


def test_ops_all_missing_no_degrade():
    """「本轮全渠道无数据」28 半角：不超宽原样入选零损失。"""
    n = "上→乌 本轮全渠道无数据"
    assert _disp_dw("> ⚠️ " + n) <= 40
    assert _fit_line("> ⚠️ " + n,
                     fallbacks=_ops_fallbacks(n)) == "> ⚠️ " + n


# ---- merged from tests/test_v180_push.py ----

# ---- P2-2 _dedup_tie 键归一：name 尾航班号参与键 ----

def _tie_row(code, name, plat):
    return {"code": code, "name": name, "depTime": "14:00",
            "arrTime": "00:40", "transCity": "郑州",
            "crossDayDesc": "+1天", "stopover": 0, "price": 2310.0,
            "_platform": plat}


def test_dedup_tie_name_tail_code_merges():
    """一端 code 缺失回退 name、另一端 code=HU7849 → 渠道写法差
    曾不合并（生产图双行占 TOP5 双槽）；name 尾航班号归一后合并。"""
    rows = [_tie_row("", "新海航｜天津航空HU7849", "qunar"),
            _tie_row("HU7849", "海南航空", "ctrip")]
    out = _dedup_tie(rows)
    assert len(out) == 1 and out[0]["_tie_n"] == 2


def test_dedup_tie_different_flight_not_merged():
    """真不同班（尾号不同）不合并——归一只放行写法差，不吞差异。"""
    rows = [_tie_row("", "新海航｜天津航空HU7849", "qunar"),
            _tie_row("HU7850", "海南航空", "ctrip")]
    assert len(_dedup_tie(rows)) == 2


def test_dedup_tie_price_diff_not_merged():
    """同班不同价（价差即比价信息）不合并。"""
    a = _tie_row("", "新海航｜天津航空HU7849", "qunar")
    b = _tie_row("HU7849", "海南航空", "ctrip")
    b["price"] = 2315.0
    assert len(_dedup_tie([a, b])) == 2


# ---- P2-5 (税前) 全角化（潜伏词面，pad 旋钮开启即混入） ----

def test_low_txt_fullwidth_paren(monkeypatch):
    import core.alerter as _al
    monkeypatch.setattr(_al, "FLIGGY_TAX_PAD", 100)
    out = _low_txt(1500, 1600, "fliggy")
    assert "（税前）" in out and "(税前)" not in out


# ---- P2-6 建议行档位词粘连「直飞真达标」 ----

def test_suggest_line_tier_separator():
    al = Alerter.__new__(Alerter)
    rt = Route("URC", "乌鲁木齐", "SHA", "上海", ["2026-10-05"],
               alert_direct=1600, alert_transfer=1700)
    bd = {"price": 1526.0, "name": "南航CZ6975", "depTime": "08:00",
          "arrTime": "12:20", "_platform": "ctrip", "transCity": ""}
    s = {"date": "2026-10-05", "best_direct": bd, "best_transfer": None,
         "best_transfer_mkt": None, "all_flights": [bd]}
    r = al._suggest_line(rt, s)
    assert ("直飞 真达标" in r) or ("直飞·真达标" in r), \
        "建议行 label 与档位词粘连（直飞真达标连读）"


# ---- P2-7 恰达线 0% 括注观感矛盾 ----

def test_kpi_pct_below_1pct_omitted():
    """<1% 的 pct 括注省略（「低￥5（0%）」数字真实但并排读像矛盾；
    与 _delta_txt/<1% 横盘省略同哲学）。守卫已收口进
    _kpi_pct_suffix 单源（r263 对齐，擦边带词面同源）——钉面双段：
    内联旁路形态禁复活 + 单源门控在场。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count("and _p >= 1") + src.count("and _pt >= 1") == 0, (
        "KPI pct 内联 <1% 门控复活（须走 _kpi_pct_suffix 单源）")
    assert "return f\"{_pct_int(p)}%\" if p >= 1 else \"\"" in src, (
        "_kpi_pct_suffix 单源缺 <1% 省略门控")


# ---- P2-4 「直挂未标注」仅在直挂筛选航线出（假警示） ----

class TestDigestBudget:
    """P1-1 字节预算降级（真执行级，with_tables=False 预览同路径）。"""

    @staticmethod
    def _al():
        al = Alerter.__new__(Alerter)
        al.platforms = ["ctrip", "qunar"]
        al.at_mobile = "13800138000"
        al.round_charts = {}
        al.storage = None
        return al

    @staticmethod
    def _flight(price, plat="ctrip", trans=False):
        f = {"price": float(price), "name": "南航CZ6975",
             "code": "CZ6975", "depTime": "08:00", "arrTime": "12:20",
             "_platform": plat, "transCity": "", "crossDayDesc": "",
             "stopover": 0, "transferBaggage": "", "stopCity": ""}
        if trans:
            f.update({"transCity": "郑州", "arrTime": "00:40",
                      "crossDayDesc": "+1天", "layoverT": "2:15"})
        return f

    def _rs_list(self, n=24, hit_first=True):
        """n 条航线（首条达标、其余超线）；直挂筛选未配置。"""
        out = []
        for i in range(n):
            rt = Route(f"U{i:02d}", f"城市{i}", f"S{i:02d}", f"目的{i}",
                       ["2026-10-05"], alert_direct=1600,
                       alert_transfer=1700)
            bd = self._flight(1500 if (hit_first and i == 0) else 2410)
            bt = self._flight(1520 if (hit_first and i == 0) else 2470,
                              trans=True)
            sec = {"date": "2026-10-05", "best_direct": bd,
                   "best_transfer": bt, "best_transfer_mkt": bt,
                   "all_flights": [bd, bt], "seen_plats": ["ctrip"],
                   "xphans": [], "top_transfer": [bt]}
            out.append((rt, [sec]))
        return out

    def test_desp_within_dingtalk_budget(self):
        """24 航线 desp 字节数收敛到钉钉 18000B 硬限内（留 notifier
        截断缓冲）。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        size = len(p["desp"].encode("utf-8"))
        assert size <= 17500, f"desp {size}B 仍超预算（截断丢总表/@段）"

    def test_demotion_note_and_mini_rows(self):
        """降级发生时：说明行在场 + 非达标航线出 📍 mini 行。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        # 词面 v181 起压缩 ≤40 半角（原「部分航线仅列关键价（明细见
        # 总表）」47 半角超手机行宽红线，P1-1 修复）
        assert "仅列关键价" in p["desp"], "降级说明行缺失"
        assert "📍" in p["desp"], "非达标航线 mini 行缺失"

    def test_hit_route_full_block_kept(self):
        """达标航线小节恒全量（🎯 档加粗价格在场），永不降级。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        assert "￥1500" in p["desp"] and "城市0" in p["desp"], \
            "达标航线 KPI 被误降级"

    def test_at_mobiles_tail_kept(self):
        """@手机号段恒在 desp 尾部（截断高危段先落位）。"""
        p = self._al()._digest_payload(self._rs_list(24), with_tables=False,
                                       with_charts=False)
        assert p["at_mobiles"] == ["13800138000"]
        assert "@13800138000" in p["desp"][-400:], "@段未保尾部"

    def test_small_payload_untouched(self):
        """3 航线常规形态不触发降级（无说明行，KPI 全量）。"""
        p = self._al()._digest_payload(self._rs_list(3), with_tables=False,
                                       with_charts=False)
        assert "部分航线仅列关键价" not in p["desp"], "常规形态误降级"
        assert p["desp"].count("￥2410") >= 2, "常规形态 KPI 缺失"

    def test_direct_note_not_on_unfiltered_route(self):
        """「直挂未标注」仅在 transfer_baggage=direct 航线出——
        未配置直挂筛选时它是中性信息却长着警示脸（假警示）。"""
        p = self._al()._digest_payload(self._rs_list(3), with_tables=False,
                                       with_charts=False)
        assert "直挂未标注" not in p["desp"], \
            "未配置直挂筛选的航线出「直挂未标注」假警示"


# ---- report.py 源码钉：图内词面单源与新字段承载 ----

def test_tbl_ring_legend_unified():
    """P2-1 环注形状词与表图图例统一「描绿」（「细绿」是旁路词面，
    跨图扫读需两次翻译）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "细绿" not in src, "「细绿」旁路词面残留"
    assert "○描绿" in src, "环注描绿词面缺失"


def test_agepolicy_and_transfertax_in_png():
    """决策字段进总表图（webui 有、图无）：agePolicy 词面「限青年价」
    （PNG 端无 ⚠——U+26A0 在 msyh 无字形渲染 tofu，webui 浏览器端
    保留 ⚠）；transferTax 进次行槽。"""
    src = open("report.py", encoding="utf-8").read()
    assert "agePolicy" in src, "agePolicy 未进总表图"
    assert "⚠" not in src.split('("age"')[1][:120], \
        "PNG 端 agePolicy 词面带 ⚠（msyh 无字形渲染 tofu）"
    assert "transferTax" in src, "transferTax 未进总表图"


def test_ops_suffix_measured():
    """P2-9 ops「等N条」尾注过量宽度量（直接尾拼在 _fit_text 截断时
    最先丢，对账留痕失效）。"""
    src = open("report.py", encoding="utf-8").read()
    assert '_ops_lines[-1] += f" 等{len(_rest)}条"' not in src, \
        "ops 尾注仍直接尾拼（不度量）"


def test_notifier_truncate_note_semantics():
    """P1-1 配套：截断尾注点明丢失面（泛化「已截断」不说丢了什么）。"""
    src = open("core/notifier.py", encoding="utf-8").read()
    # v185 审校补 @提醒段：@高亮结构性垫底，被切即触达蒸发
    assert "尾部明细总表/@提醒/对账段未收入" in src, "截断尾注缺丢失面语义"


# ---- merged from tests/test_v186_push.py ----

class _FakeResp:
    def __init__(self):
        self.text = '{"errcode":0,"errmsg":"ok"}'

    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    """捕获 payload 的 httpx.post 替身（零网络）。"""

    def __call__(self, url, **kw):
        self.url = url
        self.payload = kw.get("json")
        return _FakeResp()


class TestTruncateFinalGuard:
    def _mk(self):
        n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
        n.logger = logging.getLogger("t")
        n.last_errcode = None
        n._fail_streak = 0
        n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
        return n

    def test_truncated_body_never_exceeds_18000(self, monkeypatch, tmp_path):
        # 19000B 纯 ASCII（无 ![ 无 \n\n）→ img/edge 切点全不触发，
        # 修前产物=17900+尾注 108B=18008B 超限
        monkeypatch.chdir(tmp_path)   # send() 向 CWD 落 debug/last_push.md
        cap = _CapturePost()
        monkeypatch.setattr(nm.httpx, "post", cap)
        n = self._mk()
        desp = "a" * 19000
        n.send("t", desp)
        txt = cap.payload["markdown"]["text"]
        assert len(txt.encode("utf-8")) <= 18000, \
            f"截断产物 {len(txt.encode('utf-8'))}B 超钉钉 18000B 上限"
        assert "已截断" in txt, "尾注丢失面说明未落位"

    def test_truncate_with_link_keeps_note_and_limit(self, monkeypatch, tmp_path):
        # 双图链：尾部图链被 img 切点切掉（防死链，既有语义），
        # 前部图链保留；终验不改变形态，仅保证字节闭合
        monkeypatch.chdir(tmp_path)   # send() 向 CWD 落 debug/last_push.md
        cap = _CapturePost()
        monkeypatch.setattr(nm.httpx, "post", cap)
        n = self._mk()
        desp = ("x" * 8000 + "\n\n![走势](https://a.com/x.png)\n\n"
                + "y" * 8000 + "\n\n![走势](https://b.com/t.png)\n\n"
                + "z" * 2500)
        n.send("t", desp)
        txt = cap.payload["markdown"]["text"]
        assert len(txt.encode("utf-8")) <= 18000
        assert "](https://a.com/x.png)" in txt, "在位图链被误切"


# ---- merged from tests/test_v195_push.py ----

_MISSING = object()


class _ChFake:
    """通道 fake：send 返回预设结果，可选透传 last_errcode（形同
    DingTalkNotifier：成功 0 / 幽灵 -1 / 网络异常显式清 None）。"""

    def __init__(self, ok, errcode=_MISSING):
        self.ok = ok
        self.errcode = errcode

    def send(self, title, desp="", at_mobiles=None, is_at_all=False,
             launch=""):
        if self.errcode is not _MISSING:
            self.last_errcode = self.errcode
        return self.ok


def _comp(members):
    return CompositeNotifier(members, logging.getLogger("t"))


def test_composite_errcode_ghost_minus_one_passthrough():
    """钉钉 -1 幽灵 + 邮箱同轮失败（全通道 False）→ errcode=-1
    透传到 Composite，日报落账守卫可见。"""
    comp = _comp([_ChFake(False, errcode=-1), _ChFake(False)])
    assert comp.send("t", "d") is False
    assert comp.last_errcode == -1


def test_composite_errcode_success_zero():
    """钉钉成功 → 透传 0（非 -1，日报正常路径零影响）。"""
    comp = _comp([_ChFake(True, errcode=0), _ChFake(True)])
    assert comp.send("t", "d") is True
    assert comp.last_errcode == 0


def test_composite_errcode_absent_members_stays_none():
    """成员无 last_errcode 属性（邮件/ntfy 族）→ Composite 恒 None，
    getattr 消费点零 AttributeError。"""
    comp = _comp([_ChFake(False), _ChFake(False)])
    assert comp.send("t", "d") is False
    assert getattr(comp, "last_errcode", "missing") is None


def test_composite_errcode_cleared_per_round():
    """每轮先清：上轮 -1 残留不跨轮（钉钉网络异常路径成员自己清
    None——残留 -1 会把当日日报静默吞掉）。"""
    comp = _comp([_ChFake(False, errcode=-1), _ChFake(False)])
    comp.send("t", "d")
    assert comp.last_errcode == -1
    comp.members = [_ChFake(False, errcode=None), _ChFake(False)]
    comp.send("t", "d2")
    assert comp.last_errcode is None, "上轮 -1 残留跨轮（幽灵守卫误触发）"


def test_composite_member_raise_stale_errcode_not_picked():
    """成员 send 半途抛异常（Soldier P2-1）：异常=本轮 errcode 语义
    不可信，成员上轮残留 -1 不得被透传拾取——否则日报被误按
    「幽灵送达已推」落账，当日日报静默丢。"""
    class _Raiser:
        last_errcode = -1   # 上轮残留（类属性形态即实例可见）

        def send(self, *a, **kw):
            raise RuntimeError("boom")

    r = _Raiser()
    comp = _comp([r, _ChFake(False)])
    comp.send("t", "d")
    assert comp.last_errcode is None, "异常成员残留 -1 被拾取（守卫反噬）"
    # 实例视角断言（异常路径清的是实例属性，遮蔽类属性残留）
    assert getattr(r, "last_errcode") is None, "异常成员自身留痕未清"


# ---- merged from tests/test_v229_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_legend_line_default_projection():
    """现行档位 emoji 下图例行识别为图例（基线行为不变）。"""
    legend = "> ⏱22:47 🎯真达标 🟩破线 🟨擦边 超线"
    assert notifier._is_legend_line(legend)


def test_legend_line_follows_tier_emoji_projection(monkeypatch):
    """档位 emoji 投影改版（🎯🟩🟨→✅🟧🟡）：图例识别跟随投影，
    不锚死字面量（单源律，与 _EMOJI_TIER_WORDS 同源）。"""
    legend = "> ⏱22:47 ✅真达标 🟧破线 🟡擦边 超线"
    monkeypatch.setattr(
        notifier, "TIER_EMOJI",
        {**notifier.TIER_EMOJI, "qual": "✅", "mkt": "🟧", "near": "🟡"})
    assert notifier._is_legend_line(legend), (
        "投影改版后图例识别应跟随 TIER_EMOJI，字面量锚死即漏剥")


def test_legend_line_projection_counts_not_single_dot(monkeypatch):
    """正文行至多 1 个档位点的语义不变：投影改版后单点行不误判
    图例（KPI 行点前置 1 个的豁免面跟投影走）。"""
    kpi = "📍 10-06　✅ 直飞 ￥1760 破线"
    monkeypatch.setattr(
        notifier, "TIER_EMOJI",
        {**notifier.TIER_EMOJI, "qual": "✅", "mkt": "🟧", "near": "🟡"})
    assert not notifier._is_legend_line(kpi)
