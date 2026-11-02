# -*- coding: utf-8 -*-
"""r511：干预成功率必须能按作用域分开说。

真实库（data/prices.db，2026-10-29 15:00 实测）：

    probe  scope='intl'  7 次
    probe  scope='dom'   2 次

但 `intervention_success_rate()` 只按**动作**聚合，面板给一个合成的
「自检 88%（7/8）」。而节流面板的自检按钮**本来就是按域选的**
（自动 / 国内 / 国际），这个合计数答不出「该点哪一域」——这是
「可区分 / 可指定干预」的直接缺口。

修法：每个动作额外带 `scopes` 子表。三条不可退让的口径：
  1) 动作级字段（n/healed/unhealed/unjudged/rate/reliable）**一字不变**；
  2) 只收非空 scope，不编「全端」桶；
  3) 窗口边界仍按渠道的人工干预序列切，不按 scope 拆——任何一次人工
     干预都会改会话状态，前一窗必须在那一刻结束。
"""
import os
import tempfile
from datetime import datetime, timedelta

from core.storage import PriceStorage

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
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = w.index("const _ivRate=(()=>{")
    seg = w[i:i + 2200]
    assert "d.scopes" in seg, "前端没有读分域子表"
    assert "国内" in seg and "国际" in seg, "分域没有中文词表"
    # 动作级读数仍是「N%（a/b）」，分域只作为附注
    assert "'）'+\"（\"" not in seg
    assert "pace-ivr\" title=" in w, "成功率段没有 title（420 档会被截断）"
    assert "esc(_ivRate[0])" in w, "读数没有转义就拼进了 HTML"
