# -*- coding: utf-8 -*-
"""r484：干预成功率——按动作回答「按哪个钮真的有用」。

原始需求明确要求「干预成功率」。此前系统只有 `intervention_effect`
（最近一次干预的前后对比），答不了「这类干预一共做过 N 次，几次真把
渠道救回来了」——而这正是决定优先按哪个钮的依据。

判据边界（每条都要钉）：
  1) 窗口内出现 ok/calendar → 有效；
  2) 窗口内只有失败样本 → 无效（不能跟「还没采集」混为一谈）；
  3) 窗口内一条样本都没有 → **不计入分母**（还没采集，不是失败）；
  4) 同一渠道的窗口以「下一次人工干预」为右边界（不含）；
  5) auto_* 自动事件不进统计（它们不是人的操作选择）。
"""
import os
import tempfile
from datetime import datetime, timedelta

from core.storage import PriceStorage


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
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
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
    w = _io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert "d.reliable?" in w, "前端未使用后端可靠性标记"
    assert "d.n>=3" not in w, "前端仍在自己写可靠性阈值（会与后端漂移）"
