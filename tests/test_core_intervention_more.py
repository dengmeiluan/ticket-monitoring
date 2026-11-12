# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r511_intervention_scope_rate.py
- tests/test_r610_intervention_window_symmetry.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import datetime as dt
import os
import sys
import tempfile

from core.storage import PriceStorage
from datetime import datetime, timedelta


# ---- merged from tests/test_r511_intervention_scope_rate.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _at(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at, pair=("BKK", "CAN")):
    """写一条路径样本。航线可指定（r617）：分域判定按真实航线切片，
    原先这里恒写国际航线，于是「国内自检」窗口里也躺着国际样本——
    在 r617 之前没人发现，因为子表根本不看航线。"""
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,?,?,?,'2026-11-05','H5',?)",
            (at, plat, pair[0], pair[1], status))


def _row_dom(ps, plat, status, at):
    return _row(ps, plat, status, at, pair=("SHA", "PEK"))


def test_scope_breakdown_splits_one_action_into_per_domain_numbers():
    ps = _ps()
    # 国际：3 次，2 次救回；国内：2 次，都救回
    for i, ok in enumerate([True, True, False]):
        at = _at(600 - i * 60)
        ps.save_intervention("ctrip", "probe", ok=True, scope="intl", at=at)
        _row(ps, "ctrip", "ok" if ok else "login", at)
    for i, ok in enumerate([True, True]):
        at = _at(300 - i * 60)
        ps.save_intervention("ctrip", "probe", ok=True, scope="dom", at=at)
        _row_dom(ps, "ctrip", "ok" if ok else "login", at)

    r = ps.intervention_success_rate()
    sc = r["probe"]["scopes"]
    assert sc["intl"]["n"] == 3 and sc["intl"]["healed"] == 2, sc
    assert sc["dom"]["n"] == 2 and sc["dom"]["healed"] == 2, sc
    assert sc["intl"]["rate"] == round(2 / 3, 4), sc
    assert sc["dom"]["rate"] == 1.0, sc
    # 动作级仍是两者的合计（老口径不许变）
    assert r["probe"]["n"] == 5 and r["probe"]["healed"] == 4, r


def test_empty_scope_only_counts_in_the_action_total():
    """空 scope 不得编出一个「全端」桶——那会让读者以为真有一组数据。"""
    ps = _ps()
    ps.save_intervention("tuniu", "reset", ok=True, scope="", at=_at(120))
    _row(ps, "tuniu", "ok", _at(110))
    r = ps.intervention_success_rate()
    assert r["reset"]["n"] == 1, r
    assert r["reset"]["scopes"] == {}, \
        "空 scope 被编成了一个作用域桶：%r" % (r["reset"]["scopes"],)


def test_judged_and_unjudged_split_per_scope_too():
    """判不了也要分域：国际自检没采集样本时，不能说成「国内自检判不了」。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, scope="dom", at=_at(300))
    _row_dom(ps, "ctrip", "ok", _at(290))
    ps.save_intervention("ctrip", "probe", ok=True, scope="intl", at=_at(20))
    r = ps.intervention_success_rate()
    sc = r["probe"]["scopes"]
    assert sc["dom"]["n"] == 1 and sc["dom"]["unjudged"] == 0, sc
    assert sc["intl"]["n"] == 0 and sc["intl"]["unjudged"] == 1, \
        "无样本的国际自检没有被分域记为待判：%r" % (sc,)
    assert r["probe"]["unjudged"] == 1 and r["probe"]["n"] == 1, r


def test_window_still_ends_at_any_manual_intervention():
    """边界不按 scope 拆：国际自检之后的国内自检也要结束前一窗。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, scope="intl", at=_at(200))
    _row(ps, "ctrip", "login", _at(190))     # 国际窗口内的失败
    ps.save_intervention("ctrip", "probe", ok=True, scope="dom", at=_at(100))
    _row_dom(ps, "ctrip", "ok", _at(95))     # 落在国内窗口（国内航线）
    r = ps.intervention_success_rate()
    sc = r["probe"]["scopes"]
    assert sc["intl"]["n"] == 1 and sc["intl"]["unhealed"] == 1, sc
    assert sc["dom"]["n"] == 1 and sc["dom"]["healed"] == 1, sc


def test_scope_subtable_never_widens_the_action_denominator():
    """分域是拆分视图，不是新增样本：分域的**样本总数**不得超过动作级。

    r617 起分域按真实航线切片（原来只是把渠道级的 win 抄一份），
    所以「没有该域样本」的干预会落到 unjudged 而不是 n：分域 n 之和
    ≤ 动作级 n 才是正确关系；相等只在每次干预窗口里都恰好有该域样本时成立。
    不变量要的是「拆分不放大」，不是「必须刚好相等」。
    """
    ps = _ps()
    for scope, oks in (("intl", [True, False]), ("dom", [True])):
        for i, ok in enumerate(oks):
            at = _at(500 - i * 100)
            ps.save_intervention("ctrip", "probe", ok=True, scope=scope, at=at)
            (_row_dom if scope == "dom" else _row)(
                ps, "ctrip", "ok" if ok else "error", at)
    ps.save_intervention("ctrip", "warmup", ok=True, scope="", at=_at(50))
    _row(ps, "ctrip", "ok", _at(40))
    r = ps.intervention_success_rate()
    d = r["probe"]
    sc = d["scopes"]
    assert sum(v["n"] for v in sc.values()) <= d["n"], \
        "分域把样本放大了（之和大于动作级 n）：%r" % (d,)
    assert sum(v["healed"] for v in sc.values()) <= d["healed"], d
    # 该花的样本一条都不能少：每次干预要么判了、要么记为待判
    for k, v in sc.items():
        assert v["n"] + v["unjudged"] >= 1, "分域 %s 整条丢了：%r" % (k, v)
    assert (ps.intervention_success_rate()["probe"]["n"]
            == d["n"]), "动作级口径被分域影响了"


def test_panel_renders_the_breakdown_and_keeps_it_reachable_when_truncated():
    """面板要真渲染分域，且截断时全文仍可达（title）。"""
    import io
    w = webui_full_src()
    i = w.index("const _ivRate=(()=>{")
    seg = w[i:i + 2200]
    assert "d.scopes" in seg, "前端没有读分域子表"
    assert "国内" in seg and "国际" in seg, "分域没有中文词表"
    # 动作级读数仍是「N%（a/b）」，分域只作为附注
    assert "'）'+\"（\"" not in seg
    assert "pace-ivr\" title=" in w, "成功率段没有 title（420 档会被截断）"
    assert "esc(_ivRate[0])" in w, "读数没有转义就拼进了 HTML"


# ---- merged from tests/test_r610_intervention_window_symmetry.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fixture(before_ok, after_ok, later_ok, days_later=8):
    """造一份干预前后数据：T0 为干预时刻（10 天前）。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "iv.db")
    st = PriceStorage(db)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    now = dt.datetime.now().replace(microsecond=0)
    t0 = now - dt.timedelta(days=10)
    with st._conn() as c:
        c.execute("UPDATE interventions SET at=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"),))
        rows = []
        for i in range(10):
            rows.append(("ok" if i < before_ok else "fail",
                         (t0 - dt.timedelta(hours=i + 1))))
        for i in range(10):
            rows.append(("ok" if i < after_ok else "fail",
                         (t0 + dt.timedelta(hours=i + 1))))
        span = max(1, days_later)
        for i in range(30):
            rows.append(("ok" if i < later_ok else "fail",
                         (t0 + dt.timedelta(days=2 + i % span))))
        for s, at in rows:
            c.execute(
                "INSERT INTO fetch_paths(platform,entry_path,path_status,"
                "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
                ("ctrip", "PC", s, "SHA", "BJS", "2026-11-01",
                 at.strftime("%Y-%m-%d %H:%M:%S")))
    return st


def test_after_is_bounded_by_the_same_window():
    """干预后 24h 全成功、之后持续恶化 → after 必须仍是 1.0，不是被稀释的低值。"""
    st = _fixture(before_ok=0, after_ok=10, later_ok=0)
    e = st.intervention_effect("ctrip", hours=24)
    assert e["after_n"] <= 20, (
        "干预后统计越过了同窗口（%d 条样本），会被远期恶化稀释" % e["after_n"])
    assert e["after"] == 1.0, "干预后 24h 实际全成功，却被算成 %r" % e["after"]
    assert e["before"] == 0.0


def test_window_is_symmetric_in_sample_count():
    """两段窗口等长时，样本量应当同量级（不是一边 10 一边 100）。"""
    st = _fixture(before_ok=0, after_ok=10, later_ok=0)
    e = st.intervention_effect("ctrip", hours=24)
    assert abs(e["after_n"] - e["before_n"]) <= 5, (
        "before=%d 条 / after=%d 条：窗口不等长，两个百分比不可比"
        % (e["before_n"], e["after_n"]))


def test_regression_is_still_reported():
    """收紧 after 窗口后，「先好后坏」仍必须能被判出来（trend/regressed 不受影响）。"""
    from core.pacing import effect_verdict
    st = _fixture(before_ok=0, after_ok=10, later_ok=0)
    v = effect_verdict(st.intervention_effect("ctrip", hours=24))
    assert v[0] == "regressed", (
        "干预后回落没有被判出来（收紧窗口不该影响回落观测）：%r" % (v,))


def test_real_improvement_is_reported():
    from core.pacing import effect_verdict
    st = _fixture(before_ok=0, after_ok=10, later_ok=30)
    v = effect_verdict(st.intervention_effect("ctrip", hours=24))
    assert v[0] == "improved", v


def test_genuinely_ineffective_intervention_is_reported():
    from core.pacing import effect_verdict
    st = _fixture(before_ok=0, after_ok=0, later_ok=0)
    v = effect_verdict(st.intervention_effect("ctrip", hours=24))
    assert v[0] == "no_effect", v
