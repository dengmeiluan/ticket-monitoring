# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r484_intervention_success_rate.py
- tests/test_r506_intervention_unjudged.py
- tests/test_r611_intervention_heal_window_capped.py
- tests/test_r612_intervention_write_failure_is_visible.py
- tests/test_r617_intervention_scope_is_scoped.py
- tests/test_r618_intervention_trend_follows_scope.py

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


# ---- merged from tests/test_r484_intervention_success_rate.py ----

def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _at(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'%s','BKK','CAN','2026-11-05','H5',?)" % plat,
            (at, status))


def test_healed_when_output_appears_in_window():
    ps = _ps()
    ps.save_intervention("fliggy", "probe", ok=True, at=_at(120))
    _row(ps, "fliggy", "ok", _at(110))
    r = ps.intervention_success_rate()
    assert r["probe"]["n"] == 1 and r["probe"]["healed"] == 1, r
    assert r["probe"]["rate"] == 1.0


def test_unhealed_when_only_failures_in_window():
    ps = _ps()
    ps.save_intervention("fliggy", "warmup", ok=True, at=_at(120))
    _row(ps, "fliggy", "login", _at(110))
    _row(ps, "fliggy", "error", _at(100))
    r = ps.intervention_success_rate()
    assert r["warmup"]["n"] == 1 and r["warmup"]["unhealed"] == 1, r
    assert r["warmup"]["rate"] == 0.0, "窗口内全是失败必须计为无效"


def test_pending_window_is_excluded_not_counted_as_failure():
    """干预刚做完还没采集：不可判断，不能拉低成功率。

    r506 起这类窗口不再整条消失，而是记进 `unjudged`；**分母口径不变**
    （n 仍为 0、rate 仍为 None），所以这里断言的是「没被算成失败」，
    而不是「不出现在结果里」。
    """
    ps = _ps()
    ps.save_intervention("fliggy", "verify", ok=True, at=_at(2))
    r = ps.intervention_success_rate()
    d = r.get("verify") or {}
    assert d.get("unhealed", 0) == 0, "无样本窗口被算成了失败：%r" % (r,)
    assert d.get("n", 0) == 0, "无样本的窗口被算进了分母：%r" % (r,)
    assert d.get("rate") is None, "无样本却给出比率：%r" % (r,)


def test_window_ends_at_next_manual_intervention():
    """后一次干预之后的成功，不能算到前一次头上。"""
    ps = _ps()
    ps.save_intervention("fliggy", "probe", ok=True, at=_at(120))
    ps.save_intervention("fliggy", "warmup", ok=True, at=_at(60))
    _row(ps, "fliggy", "login", _at(90))  # 落在 probe 的窗口（且是失败）
    _row(ps, "fliggy", "ok", _at(50))     # 落在 warmup 的窗口
    r = ps.intervention_success_rate()
    assert r["probe"]["unhealed"] == 1, r
    assert r["warmup"]["healed"] == 1, r


def test_auto_events_are_excluded():
    ps = _ps()
    ps.save_intervention("fliggy", "auto_trip", ok=False, at=_at(120))
    _row(ps, "fliggy", "ok", _at(110))
    r = ps.intervention_success_rate()
    assert "auto_trip" not in r, "自动事件混进了人工干预成功率：%r" % (r,)


def test_rate_per_action_can_be_compared():
    """同一动作多次：3 次有效 1 次无效 → 75%，不同动作各自独立。"""
    ps = _ps()
    for i, ok in enumerate([True, True, True, False]):
        at = _at(200 - i * 30)
        ps.save_intervention("ctrip", "probe", ok=ok, at=at)
        _row(ps, "ctrip", "ok" if ok else "error", at)
    r = ps.intervention_success_rate()
    assert r["probe"]["n"] == 4 and r["probe"]["healed"] == 3, r
    assert r["probe"]["rate"] == 0.75


# ---------- 可见性：指标必须真的出现在面板上 ----------

def test_payload_and_panel_expose_the_rate():
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = webui_full_src()
    # 后端：/api/pacing 载荷必须带上
    assert 'data["iv_rate"] = _pst.intervention_success_rate()' in w, \
        "接口未下发干预成功率"
    # 前端：干预小节必须展示，且样本不足时不报百分比
    i = w.index("const _ivRate=(()=>{")
    # 窗口到下一个 const 声明为止，而不是写死字符数：r511 加了分域拆分后
    # 函数体变长，写死的 900 会把「近 7 天成功率」这种靠后的口径句挤出窗口，
    # 让「必须标注 7 天口径」这条守卫假红。
    j = w.index("const _t=_paceSnapAt", i)
    seg = w[i:j]
    assert "样本不足" in seg, "样本不足时仍给出百分比"
    # r486：可靠性阈值只由后端给（d.reliable），前端不得再写一份
    assert "d.reliable?" in seg, "未按后端可靠性标记分流"
    assert "d.n>=3" not in seg, "前端仍自己写可靠性阈值"
    assert "近 7 天成功率" in seg, "未标明统计口径（7 天）"
    # 挂载方式不再绑死 DOM 形状（r506 起分成成功率/待判两个节点）
    assert "+(_ivRate[0]?" in w, "干预小节未挂上成功率读数"


def test_reliability_flag_comes_from_the_backend():
    """n=1 的 1.0 与 n=12 的 1.0 不是一回事，API 必须自带可靠性标记。

    实测真实库：`reset` 只有 1 次样本却吐出 rate=1.0。面板会写「样本不足」，
    但任何直接消费 API 的脚本/推送都会把这个 1.0 当真。可靠性判据只能有
    一处（后端），前端不得再自己写一遍 n>=3。
    """
    ps = _ps()
    ps.save_intervention("ctrip", "reset", ok=True, at=_at(120))
    _row(ps, "ctrip", "ok", _at(110))
    r = ps.intervention_success_rate()
    assert r["reset"]["reliable"] is False, "单样本被标成可靠：%r" % (r,)

    ps2 = _ps()
    for i in range(3):
        at = _at(200 - i * 30)
        ps2.save_intervention("ctrip", "probe", ok=True, at=at)
        _row(ps2, "ctrip", "ok", at)
    r2 = ps2.intervention_success_rate()
    assert r2["probe"]["reliable"] is True, r2

    import io as _io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = webui_full_src()
    assert "d.reliable?" in w, "前端未使用后端可靠性标记"
    assert "d.n>=3" not in w, "前端仍在自己写可靠性阈值（会与后端漂移）"


# ---- merged from tests/test_r506_intervention_unjudged.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _at(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'%s','BKK','CAN','2026-11-05','H5',?)" % plat,
            (at, status))


def test_unjudged_window_is_reported_not_dropped():
    """没有任何采集样本的动作必须仍然出现，并标明是「判不了」。"""
    ps = _ps()
    ps.save_intervention("fliggy", "relogin", ok=True, at=_at(30))
    r = ps.intervention_success_rate()
    assert "relogin" in r, \
        "重登被整条丢掉了——「没按过」与「判不了」无法区分：%r" % (r,)
    d = r["relogin"]
    assert d["unjudged"] == 1, "未记录「判不了」的窗口：%r" % (d,)
    assert d["n"] == 0, "判不了的窗口被算进了分母：%r" % (d,)
    assert d["rate"] is None, "无样本却给出比率：%r" % (d,)
    assert d["reliable"] is False, "无样本被标成可靠：%r" % (d,)


def test_unjudged_does_not_move_the_rate():
    """混入判不了的窗口，不能让已判样本的成功率漂移。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, at=_at(300))
    _row(ps, "ctrip", "ok", _at(290))
    ps.save_intervention("fliggy", "relogin", ok=True, at=_at(30))
    r = ps.intervention_success_rate()
    assert r["probe"]["n"] == 1 and r["probe"]["rate"] == 1.0, r
    assert r["relogin"]["n"] == 0 and r["relogin"]["rate"] is None, r


def test_judged_and_unjudged_coexist_on_one_action():
    """同一动作：早先的窗口判得了，最近一次还没采集 → 两数各自独立。"""
    ps = _ps()
    ps.save_intervention("fliggy", "relogin", ok=True, at=_at(300))
    _row(ps, "fliggy", "ok", _at(290))
    ps.save_intervention("fliggy", "relogin", ok=True, at=_at(10))
    r = ps.intervention_success_rate()
    d = r["relogin"]
    assert d["n"] == 1 and d["healed"] == 1, \
        "后一次无样本的窗口污染了前一次：%r" % (d,)
    assert d["unjudged"] == 1, "最近那次没被记为待判：%r" % (d,)
    assert d["rate"] == 1.0


def test_frontend_says_pending_in_its_own_clause():
    """前端不得把「待判」混进「成功率」那一句里。

    混写会读成「成功率里含 92 次待判」。判得了的百分比与判不了的次数
    必须是两个独立从句。
    """
    import io
    w = webui_full_src()
    i = w.index("const _ivRate=(()=>{")
    seg = w[i:i + 1600]
    assert "unjudged" in seg, "前端没有读待判字段"
    # 两段各自成句，且成功率那句只在有判得了的样本时出现
    assert "近 7 天成功率 " in seg, "成功率从句缺失"
    assert "待判（窗口内无采集样本）" in seg, "待判从句缺失"
    assert "parts.length?(" in seg, "没有判得了的样本时仍会输出空的成功率从句"
    # 待判不得被算成有效/无效
    assert "d.healed" in seg and "_iv[k].n>0" in seg, \
        "未按「是否有判得了的样本」分流"
    # 两段必须落到两个独立节点（拼在一个 span 里会被读成一句话）
    assert "pace-ivr" in w and "pace-ivp" in w, "两段读数没有各自成节点"


def test_pacing_payload_shape_is_unchanged_for_consumers():
    """/api/pacing 仍下发同一份结构；只是每项多了 unjudged 字段。"""
    import io
    w = webui_full_src()
    assert 'data["iv_rate"] = _pst.intervention_success_rate()' in w, \
        "接口不再下发干预成功率"


# ---- merged from tests/test_r611_intervention_heal_window_capped.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fixture(*, fail_after=10, later_ok=True, days_later=20):
    """造一次 10 天前的干预：之后 N 小时全失败，远期（days_later）偶然成功。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "sr.db")
    st = PriceStorage(db)
    now = dt.datetime.now().replace(microsecond=0)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    t0 = now - dt.timedelta(days=10)
    with st._conn() as c:
        c.execute("UPDATE interventions SET at=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"),))
        rows = [("fail", t0 + dt.timedelta(hours=i + 1))
                for i in range(fail_after)]
        if later_ok:
            rows.append(("ok", now - dt.timedelta(days=days_later)))
        for s, at in rows:
            c.execute(
                "INSERT INTO fetch_paths(platform,entry_path,path_status,"
                "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
                ("ctrip", "PC", s, "SHA", "BJS", "2026-11-01",
                 at.strftime("%Y-%m-%d %H:%M:%S")))
    return st


def test_far_future_success_does_not_heal_the_intervention():
    """干预后 24h 全失败 → 不能因为在 20 天后偶然成功就记 healed。"""
    st = _fixture(fail_after=10, later_ok=True, days_later=20)
    d = st.intervention_success_rate(hours=24).get("warmup") or {}
    assert d.get("healed") != 1, (
        "远期偶然成功被当成干预生效（healed=%r, rate=%r）"
        % (d.get("healed"), d.get("rate")))


def test_immediate_success_still_counts():
    """真在窗口内恢复的仍必须算 healed——收紧窗口不能把好的也判没。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "ok.db")
    st = PriceStorage(db)
    now = dt.datetime.now().replace(microsecond=0)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    t0 = now - dt.timedelta(hours=3)
    with st._conn() as c:
        c.execute("UPDATE interventions SET at=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"),))
        c.execute(
            "INSERT INTO fetch_paths(platform,entry_path,path_status,"
            "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
            ("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-01",
             (t0 + dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")))
    d = st.intervention_success_rate(hours=24).get("warmup") or {}
    assert d.get("healed") == 1 and d.get("n") == 1, d


def test_next_intervention_still_closes_the_window():
    """有下一次人工干预时，窗口仍须在那一刻结束（不能被 N 小时拉长）。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "nxt.db")
    st = PriceStorage(db)
    now = dt.datetime.now().replace(microsecond=0)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    st.save_intervention("ctrip", "verify", before="fail", after="")
    with st._conn() as c:
        marks = list(c.execute(
            "SELECT id, at FROM interventions ORDER BY id").fetchall())
        t0 = now - dt.timedelta(hours=6)
        t1 = now - dt.timedelta(hours=2)
        c.execute("UPDATE interventions SET at=? WHERE id=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"), marks[0]["id"]))
        c.execute("UPDATE interventions SET at=? WHERE id=?",
                  (t1.strftime("%Y-%m-%d %H:%M:%S"), marks[1]["id"]))
        # 成功时刻在两次干预之间 → 属于第一次干预；在第二次之后再说
        c.execute(
            "INSERT INTO fetch_paths(platform,entry_path,path_status,"
            "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
            ("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-01",
             (t0 + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
        c.execute(
            "INSERT INTO fetch_paths(platform,entry_path,path_status,"
            "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
            ("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-01",
             (t1 + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
    r = st.intervention_success_rate(hours=24)
    assert (r.get("warmup") or {}).get("healed") == 1, r
    assert (r.get("verify") or {}).get("healed") == 1, r


# ---- merged from tests/test_r612_intervention_write_failure_is_visible.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _storage():
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "iv.db")
    return PriceStorage(db), db


def test_successful_write_returns_true():
    st, _ = _storage()
    assert st.save_intervention("ctrip", "warmup") is True


def test_failed_write_logs_and_still_raises(caplog):
    """失败必须 ① 留日志 ② 仍抛异常（调用方的 try/except 语义不变）。"""
    import logging
    st, db = _storage()
    st.save_intervention("ctrip", "warmup")
    os.chmod(db, 0o444)
    raised = False
    with caplog.at_level(logging.WARNING):
        try:
            st.save_intervention("ctrip", "verify")
        except Exception:
            raised = True
    assert raised, "写入失败没有抛出——调用方的 try/except 语义被改了"
    txt = "\n".join(r.message for r in caplog.records
                    if hasattr(r, "message"))
    if not txt:  # 某些环境 caplog 抓不到子 logger，退回看 getMessage
        txt = "\n".join(r.getMessage() for r in caplog.records)
    assert "写入失败" in txt and "溯源" in txt, (
        "写入失败没有留下可检索的告警：%r" % txt)


def test_rollback_does_not_leave_partial_rows():
    """失败后不得留下半条记录（溯源里不能出现「有干预无内容」的行）。"""
    st, db = _storage()
    st.save_intervention("ctrip", "warmup")
    before = len(st.interventions(platform="ctrip", limit=50))
    os.chmod(db, 0o444)
    try:
        st.save_intervention("ctrip", "verify")
    except Exception:
        pass
    after = len(st.interventions(platform="ctrip", limit=50))
    assert after == before, "写入失败却留下了记录：%d -> %d" % (before, after)


# ---- merged from tests/test_r617_intervention_scope_is_scoped.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def _ago(minutes):
    """相对「现在」的时间戳：手写固定日期会在 30 天窗口滑过去之后假红。"""
    from datetime import datetime as _dt, timedelta as _td
    return (_dt.now() - _td(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def test_each_scope_is_judged_on_its_own_samples():
    tmp = tempfile.mkdtemp()
    st = _fresh(tmp)
    plat = "ctrip"
    _add_sample(st, _ago(240), plat, "SHA", "PEK", "fail")
    # 国际自检窗口：国际全失败，但同一个窗口里国内有成功。
    # 这正是「拿国内的绿灯给国际背书」的形态——不过滤就会判成治好。
    st.save_intervention(plat, "verify", ok=True, scope="intl",
                         at=_ago(230))
    for i in range(4):
        _add_sample(st, _ago(220 - i),
                    plat, "SHA", "NRT", "fail")
    for i in range(4):
        _add_sample(st, _ago(200 - i),
                    plat, "SHA", "PEK", "ok")
    # 国内自检窗口：只有国内样本，全成功
    st.save_intervention(plat, "verify", ok=True, scope="dom",
                         at=_ago(180))
    for i in range(4):
        _add_sample(st, _ago(170 - i),
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
                         at=_ago(30))
    for i in range(3):
        _add_sample(st, _ago(20 - i),
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
                         at=_ago(30))
    for i in range(3):
        _add_sample(st, _ago(20 - i),
                    "ctrip", "SHA", "PEK", "ok")
    _add_sample(st, _ago(15), "ctrip", "SHA", "NRT", "fail")
    got = st.intervention_success_rate(hours=24 * 30)
    d = (got.get("relogin") or {})
    sc = d.get("scopes") or {}
    assert sc.get("pc", {}).get("n") == d.get("n") == 1, (
        "非域 scope 应与动作级同口径：scopes=%s / action=%s" % (sc, d))


# ---- merged from tests/test_r618_intervention_trend_follows_scope.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _at(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _add(st, at, plat, pair, status):
    with st._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at, platform, from_city, to_city,"
            " depart_date, entry_path, path_status) "
            "VALUES (?,?,?,?,'2026-11-20','P1',?)",
            (at, plat, pair[0], pair[1], status))


def test_trend_follows_the_intervention_domain():
    tmp = tempfile.mkdtemp()
    st = PriceStorage(os.path.join(tmp, "t.db"))
    plat = "ctrip"
    # 基线：干预前国际也不通
    _add(st, _at(28 * 60), plat, ("SHA", "NRT"), "login")
    st.save_intervention(plat, "verify", ok=True, scope="intl",
                         at=_at(60))
    # 干预后的窗口：国内一律成功，国际一律失败
    for m in (50, 20, 5):
        _add(st, _at(m), plat, ("SHA", "PEK"), "ok")
        _add(st, _at(m - 1), plat, ("SHA", "NRT"), "login")

    eff = st.intervention_effect(plat, hours=24)
    assert eff.get("has"), eff
    assert eff.get("scope") == "intl", (
        "这次干预是国际域，接口却没标 scope：%s" % eff)

    tr = [t for t in (eff.get("trend") or []) if t.get("rate") is not None]
    assert tr, "没有趋势数据：%s" % eff.get("trend")
    assert tr[-1]["rate"] == 0.0, (
        "国际域干预后的趋势末段应反映国际（0），实得 %s——"
        "trend 取的是渠道全部样本，国内的成功盖住了国际的全红"
        % [t["rate"] for t in tr])
    # 国际从头到尾没好过 = 「干预无效」，不是「先好后坏」
    assert eff.get("regressed") is False, (
        "国际一次都没通过时不应判「最近回落」（那是先好后坏的词）：%s" % eff)

    # 渠道级前后对比不受影响（老口径）
    assert eff.get("after_n", 0) >= 6, (
        "渠道级 after 仍应统计全部样本：%s" % eff)


def test_regressed_is_judged_on_the_intervention_domain():
    """该域先好后坏 → 判回落；渠道级同期一直有国内的绿灯，不得把它盖掉。"""
    tmp = tempfile.mkdtemp()
    st = PriceStorage(os.path.join(tmp, "t.db"))
    plat = "ctrip"
    _add(st, _at(28 * 60), plat, ("SHA", "NRT"), "login")
    st.save_intervention(plat, "verify", ok=True, scope="intl", at=_at(60))
    # 干预后三段互不重叠的 30 分钟桶：通、通、断（国内全程成功）
    for m, ok in ((55, True), (35, True), (12, False)):
        _add(st, _at(m), plat, ("SHA", "PEK"), "ok")
        _add(st, _at(m - 1), plat, ("SHA", "NRT"),
             "ok" if ok else "login")

    eff = st.intervention_effect(plat, hours=24)
    tr = [t for t in (eff.get("trend") or []) if t.get("rate") is not None]
    assert tr and tr[-1]["rate"] == 0.0, (
        "末窗国际全失败，趋势末段应为 0：%s" % [t["rate"] for t in tr])
    assert any(t["rate"] == 1.0 for t in tr[:-1]), (
        "前两窗国际是通的，趋势里该有 1.0：%s" % [t["rate"] for t in tr])
    assert eff.get("regressed") is True, (
        "国际先通后断，应判「最近回落」：%s" % eff)


def test_channel_level_trend_stays_when_scope_is_not_a_domain():
    """非域名 scope（重登槽位等）不改趋势口径。"""
    tmp = tempfile.mkdtemp()
    st = PriceStorage(os.path.join(tmp, "t.db"))
    st.save_intervention("ctrip", "relogin", ok=True, scope="pc",
                         at=_at(60))
    for m in (50, 20):
        _add(st, _at(m), "ctrip", ("SHA", "PEK"), "ok")
        _add(st, _at(m - 1), "ctrip", ("SHA", "NRT"), "login")
    eff = st.intervention_effect("ctrip", hours=24)
    tr = [t for t in (eff.get("trend") or []) if t.get("rate") is not None]
    assert tr, eff
    assert tr[-1]["rate"] == 0.5, (
        "非域 scope 的趋势应按渠道级（1 成 1 败 = 0.5）：%s"
        % [t["rate"] for t in tr])


def test_trend_line_says_which_scope_it_counts():
    """界面必须写明这条趋势是哪个域的——否则仍会被读成渠道级。"""
    import io
    w = webui_full_src()
    i = w.index("干预后每 30 分钟")
    seg = w[max(0, i - 700):i + 300]
    assert "_trScope" in seg, "趋势行没有域标签变量：%s" % seg[-260:]
    assert "'渠道'" in seg, "非域干预时趋势行缺少「渠道」口径词：%s" % seg[-260:]
