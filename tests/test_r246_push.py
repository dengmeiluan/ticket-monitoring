# -*- coding: utf-8 -*-
"""r246 推送层三案 + 哨兵词面分档（调研 _scratch/r246_report_push.md /
r246_report_dbobs.md 第 3 段）：

P1 空小节补偿行（推送审校 P2-1）：跨天航线已过日期当轮无明细、仅近
6h 补位时，小节只剩「#### 标题 + 走势图」零解释——告警路径补守宽短注，
与日报路径空小节补偿行（report.py 空小节三出口）能力对称。

P2 总表行达标旗标收口（推送审校 P3-4）：补位行（_stale_h）照打
_tie_any_ok 曾给「真达标绿=可出手」语义指向过期价——达标判定只认
当轮（L1065 fresh 门同律），补位行 _qual 置 False。

P3 运维注词面（推送审校 P3-6）：「无数据」与同图补位行同屏读感矛盾
→「当轮无数据」；「达标判定失效」可读作系统故障、实义=按未标注判
不达标 → 词面单源改写。

S1 哨兵触发文案分档（dbobs 第 3 段 WATCH）：临期退化库存轮（n 浅）
触发「疑似站点改版键名失效」归因误导（真实原因=日期退池）——抽模块
级词面函数按池深分档（难测=设计问题，闭包内联不可单测）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r246_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.alerter as A  # noqa: E402
from core.alerter import Alerter  # noqa: E402
from core.models import Route  # noqa: E402


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
    """best 双空 + top 仅补位行 → 小节补「本轮无当轮明细」短注。"""
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(3140, stale=4.2)])
    pv = a._digest_payload([(_route(), [sec])], with_tables=False,
                           with_charts=False)
    assert "本轮无当轮明细" in pv["desp"], pv["desp"][:600]
    assert "补位" in pv["desp"]


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
    """第 2+ 日期同形态：mini KPI 空 → 短注兜底（不静默）。"""
    a = _mk_alerter()
    s1 = _sec(top_direct=[_row(2100, depDate="2026-10-06")],
              best_direct=_row(2100, depDate="2026-10-06"))
    s1["date"] = "2026-10-06"
    s2 = _sec(top_direct=[_row(3140, stale=4.2)])
    s2["date"] = "2026-10-05"
    pv = a._digest_payload([(_route(dates=["2026-10-05", "2026-10-06"]),
                             [s1, s2])], with_tables=False,
                           with_charts=False)
    assert "本轮无当轮明细" in pv["desp"], pv["desp"][:900]


def test_p1_note_line_width():
    """短注行守 40 半角渲染宽（手机 ≤20 全角律，与 _win_empty 同门）。"""
    from core.alerter import _disp_dw
    a = _mk_alerter()
    sec = _sec(top_direct=[_row(3140, stale=4.2)])
    pv = a._digest_payload([(_route(), [sec])], with_tables=False,
                           with_charts=False)
    note = [ln for ln in pv["desp"].splitlines() if "本轮无当轮明细" in ln]
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
