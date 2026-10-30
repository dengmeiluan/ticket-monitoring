# -*- coding: utf-8 -*-
"""r506：干预「判不了」与「没按过」必须能区分。

审计起因（真实库 data/prices.db，2026-10-29 13:3x 实测）：
  - `interventions` 当天有 **92** 条 `relogin`（全部 fliggy）；
  - `fetch_paths` 最后一条样本停在 **10-28 14:34**，当天零条；
  - `intervention_success_rate()` 返回的只有 `probe` / `reset`。

也就是：**今天按了 92 次的重登，在面板上完全不存在**。r484 定的
「窗口内无样本不计入分母」是对的（不能让没采集把成功率压成噪声），
但把整条动作从结果里删掉就过头了——读者无法区分
「这次没人按重登」与「按了很多次、只是还判不了」。

修法：无样本的窗口不再 `continue` 丢弃，而是计入 `unjudged`；
`n`（判得了的样本数）口径不变，`rate` 仍只在 `n>0` 时有值。
前端把两种事实分两句说：判得了的给百分比，判不了的只说次数。
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
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
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
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert 'data["iv_rate"] = _pst.intervention_success_rate()' in w, \
        "接口不再下发干预成功率"
