# -*- coding: utf-8 -*-
"""r617：「干预成功率的成分」必须真的是那个成分。

`intervention_success_rate()` 的 `scopes` 子表在 r511 上线，目的是回答
「国际自检救回几次、国内自检救回几次」——面板上原样这样展示：

    近 7 天成功率 自检 88%（7/8）（国际 75% · 国内 100%）

但子表的分子分母取自**该渠道全部路径样本**，没有按作用域过滤：

    win = [(ts, st) for ts, st in rows if at <= ts < right]
    sd = d["scopes"].setdefault(scope, _new())
    ...  # 记进 sd 的就是上面这个 win

于是「国际自检」的数字其实是渠道总成功率，与「国内自检」逐字相同。
极端形态最能说明问题：国内全绿、国际全红 → 两个域都报成功，
「国际自检」显示 100%，而国际通路一条都没通过。这正是用户按「选哪一域
自检」时最需要区分的东西，却给了一份复制品。

判据：一次 intl 自检 + 一次 dom 自检，各自窗口里只放对应域的样本，
要求 intl 判为未治好、dom 判为治好。负控：把子表改回「不过滤」即红
（两个域都判治好）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


def _fresh(tmp):
    return PriceStorage(os.path.join(tmp, "prices.db"))


def _add_sample(st, at, plat, frm, to, status):
    with st._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at, platform, from_city, to_city,"
            " depart_date, entry_path, path_status, request_url, http_status,"
            " rows, note, evidence_level, attempt_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (at, plat, frm, to, "2026-11-20", "P1", status, "u", 200,
             1 if status in ("ok", "calendar") else 0, "", "detail",
             at + plat + frm + status))


def test_each_scope_is_judged_on_its_own_samples():
    tmp = tempfile.mkdtemp()
    st = _fresh(tmp)
    plat = "ctrip"
    _add_sample(st, "2026-10-20 10:00:00", plat, "SHA", "PEK", "fail")
    # 国际自检窗口：国际全失败，但同一个窗口里国内有成功。
    # 这正是「拿国内的绿灯给国际背书」的形态——不过滤就会判成治好。
    st.save_intervention(plat, "verify", ok=True, scope="intl",
                         at="2026-10-20 11:00:00")
    for i in range(4):
        _add_sample(st, "2026-10-20 11:%02d:00" % (10 + i),
                    plat, "SHA", "NRT", "fail")
    for i in range(4):
        _add_sample(st, "2026-10-20 11:%02d:00" % (30 + i),
                    plat, "SHA", "PEK", "ok")
    # 国内自检窗口：只有国内样本，全成功
    st.save_intervention(plat, "verify", ok=True, scope="dom",
                         at="2026-10-20 12:00:00")
    for i in range(4):
        _add_sample(st, "2026-10-20 12:%02d:00" % (10 + i),
                    plat, "SHA", "PEK", "ok")

    got = st.intervention_success_rate(hours=24 * 30)
    d = got.get("verify") or {}
    sc = d.get("scopes") or {}
    assert set(sc) == {"intl", "dom"}, "分域子表缺失或串味：%s" % sc

    intl, dom = sc["intl"], sc["dom"]
    assert dom["healed"] == 1 and dom["unhealed"] == 0, (
        "国内自检窗口里 4 条国内样本全成功，应判治好：%s" % dom)
    assert intl["healed"] == 0 and intl["unhealed"] == 1, (
        "国际自检窗口里 8 条样本：国际 4 条全失败、国内 4 条全成功。"
        "按国际域判定应是**未治好**，实得 %s——"
        "子表没按作用域过滤，国内的绿灯给国际背了书" % intl)
    assert intl["rate"] == 0.0 and dom["rate"] == 1.0, (
        "两个域应给出相反的结论，实得 intl=%s / dom=%s"
        % (intl["rate"], dom["rate"]))

    # 动作级口径不切片：两次自检各看渠道全部样本——国际那窗里有国内成功、
    # 国内那窗全成功，所以动作级是 2/2（重登等消费方依赖这个老口径）
    assert d["n"] == 2 and d["healed"] == 2, (
        "动作级口径应保持渠道级（两窗都能见到成功样本 = 2/2）：%s" % d)


def test_scope_judged_unknown_when_that_domain_has_no_samples():
    """该域窗口内一条样本都没有 → 判不了，不是「失败」。"""
    tmp = tempfile.mkdtemp()
    st = _fresh(tmp)
    st.save_intervention("ctrip", "verify", ok=True, scope="intl",
                         at="2026-10-20 11:00:00")
    for i in range(3):
        _add_sample(st, "2026-10-20 11:%02d:00" % (10 + i),
                    "ctrip", "SHA", "PEK", "ok")
    got = st.intervention_success_rate(hours=24 * 30)
    sc = (got.get("verify") or {}).get("scopes") or {}
    assert "intl" in sc, "国际分组整条消失：%s" % sc
    assert sc["intl"]["n"] == 0 and sc["intl"]["unjudged"] == 1, (
        "国际窗内零样本应记 unjudged，不得拿国内的样本冒充：%s" % sc["intl"])
    assert sc["intl"]["rate"] is None, (
        "零样本时 rate 必须是 None（不是 0，也不是 1）：%s" % sc["intl"])


def test_non_domain_scope_keeps_channel_level_numbers():
    """非域名的 scope（重登槽位名等）不做域过滤，仍是渠道级口径。"""
    tmp = tempfile.mkdtemp()
    st = _fresh(tmp)
    st.save_intervention("ctrip", "relogin", ok=True, scope="pc",
                         at="2026-10-20 11:00:00")
    for i in range(3):
        _add_sample(st, "2026-10-20 11:%02d:00" % (10 + i),
                    "ctrip", "SHA", "PEK", "ok")
    _add_sample(st, "2026-10-20 11:30:00", "ctrip", "SHA", "NRT", "fail")
    got = st.intervention_success_rate(hours=24 * 30)
    d = (got.get("relogin") or {})
    sc = d.get("scopes") or {}
    assert sc.get("pc", {}).get("n") == d.get("n") == 1, (
        "非域 scope 应与动作级同口径：scopes=%s / action=%s" % (sc, d))
