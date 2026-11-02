# -*- coding: utf-8 -*-
"""r618：干预后的「每 30 分钟」小趋势也必须按这次干预的域切片。

`intervention_effect()` 已经在 r512 给了 `scope_before/scope_after`，
面板正因为「国内正常、国际全挂时渠道级前后都接近 1.0」而加它。
但同一条面板上的 `trend`（“干预后每 30 分钟：100% · 0% · …”）与
`regressed`（“最近回落”）仍取**该渠道全部样本**。

于是读者会看到自相矛盾的两句：

    干预后对比：前 24h 82%（11） → 100%（6）
    本次干预针对：国际域 前 24h 0%（4） → 0%（4）
    干预后每 30 分钟：100% · 100% · 100%      ← 这些是国内的绿灯

「本次干预针对国际」下面挂着国内的趋势，`regressed` 也会被国内的
好坏带偏：国际一直全红时，只要国内某个窗口回落，就标「最近回落」；
反过来国内一直很好，国际刚崩，也不会标。

判据：国际域干预后，国内全绿、国际随后全红 → trend 必须反映国际
（末尾 0），`regressed` 必须为真。负控：trend 改回渠道级即红。
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


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
    w = io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    i = w.index("干预后每 30 分钟")
    seg = w[max(0, i - 700):i + 300]
    assert "_trScope" in seg, "趋势行没有域标签变量：%s" % seg[-260:]
    assert "'渠道'" in seg, "非域干预时趋势行缺少「渠道」口径词：%s" % seg[-260:]
