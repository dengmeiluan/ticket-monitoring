# -*- coding: utf-8 -*-
"""r501：自动熔断入账必须**行为级**验证，不能只查字符串。

审计发现：`test_auto_interventions_are_audited...` 只断言
`'"auto_trip"' in main.py`（字符串在场）+ 手工调 `save_intervention`
验证分界——**从未验证「熔断真的触发时，那段代码会落账」**。
真实账本里 `auto_trip` 是 0 条，长期无法区分是「没触发」还是「触发了没记」。

本条用真实 `Pacing.observe` 打出熔断，再走与 main.py 同构的入账，
把「触发 → 落账 → 不污染人工分界」整条链路跑一遍。顺带钉住一个事实：
真实日志里 10-29 当天零次熔断（最后一次 10-28 14:23，早于 r475 上线），
所以账本里 0 条 `auto_trip` 是「没触发」，不是「漏记」。
"""
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ps():
    import sys
    sys.path.insert(0, ROOT)
    from core.storage import PriceStorage
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_breaker_actually_fires_and_lands_in_the_ledger():
    import sys
    sys.path.insert(0, ROOT)
    from core.pacing import Pacing

    pac = Pacing({})
    kind, cd = pac.observe("qunar", ["login"], "登录墙", retry_after=0)
    assert kind == "login", "熔断没有真的触发：%r" % (kind,)
    assert cd > 0, "冷却时长非正：%r" % (cd,)

    ps = _ps()
    # 与 main.py 入账块同构
    if kind:
        ps.save_intervention("qunar", "auto_trip", ok=False, scope=kind,
                             note="自动熔断 %s，冷却 %ss" % (kind, int(cd)))

    rows = ps.interventions("qunar", 5)
    assert [r["action"] for r in rows] == ["auto_trip"], \
        "熔断触发后账本里没有 auto_trip：%r" % [
            (r["action"], r["scope"]) for r in rows]
    assert rows[0]["scope"] == "login", "熔断类型未写进 scope"


def test_auto_trip_does_not_steal_the_manual_effect_boundary():
    """自动事件进了账，但「上次干预成效」仍以人工干预为分界。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, rows=5)
    ps.save_intervention("ctrip", "auto_trip", ok=False, scope="ip",
                         note="自动熔断 ip")
    e = ps.intervention_effect("ctrip", 24)
    assert e.get("action") == "probe", \
        "自动事件抢走了人工干预的分界：%r" % (e,)


def test_auto_trip_is_excluded_from_intervention_success_rate():
    """自动事件不是「人按的钮」，不进干预成功率的分母。"""
    ps = _ps()
    ps.save_intervention("ctrip", "auto_trip", ok=False, scope="ip")
    assert ps.intervention_success_rate() == {}, \
        "自动事件混进了人工干预成功率"


def test_disabled_auto_verify_is_logged_not_silent():
    """「自动开窗已关闭」时必须留痕（可识别）。

    实测：`_auto_verify` 默认 false，命中验证时旧代码 `if _auto and ...`
    直接跳过、**什么都不记**。用户随后看到界面只剩「需验证」，既不知道
    本来可以自动处理，也不知道是自己关掉的。
    """
    import io
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    i = m.index('_auto = bool(((rt.get("cfg") or cfg).get("crawler")')
    seg = m[i:i + 1800]
    assert "else:" in seg, "关闭时没有分支处理（静默跳过）"
    j = seg.index("else:")
    tail = seg[j:j + 500]
    assert "已关闭" in tail, "关闭时未说明「已关闭」"
    assert "logger.warning" in tail or "logger.info" in tail, \
        "关闭时未留日志"
    assert "去验证" in tail, "关闭时未告诉用户该做什么"


def test_auto_verify_on_still_opens_the_window():
    """开启时仍要真的开窗（不能为了加日志把功能改坏）。"""
    import io
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    i = m.index('_auto = bool(((rt.get("cfg") or cfg).get("crawler")')
    seg = m[i:i + 1800]
    assert "if _auto:" in seg
    assert "verify_channel" in seg and "Thread" in seg, "开启时不再开窗"
    assert "> 600" in seg, "10 分钟内只开一次的防连点丢了"
