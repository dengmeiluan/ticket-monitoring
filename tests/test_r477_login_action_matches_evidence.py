# -*- coding: utf-8 -*-
"""r477：登录按钮必须落到「证据指向的那一端」，否则用户登错窗口。

实测链：path_stats 判出飞猪「国际 H5」近 24h 被登录墙拦 13/17 次、
0 出数 → advise 返回 state=login/hint=「国际 H5 …」。而面板的按钮行
只看 `v.needs_login`（运行时熔断标记）来选槽位：账本判来的登录没有这个
标记，于是落到 else 分支，按钮写「去验证」，点开的是**厂商级**验证
窗口——飞猪是 PC profile。用户照着提示把 PC 重登了一遍，H5 依旧被拦，
出数率为 0 不变，下次刷新还是同一句「需登录」。

三条契约：
  1) advise 的登录判定要回传证据（scope/path），否则前端无从选端；
  2) 前端多会话分支只要拿到路径证据就选该端，不要求 needs_login；
  3) 没有证据时才用运行时坏槽位/首个槽位兜底，且按钮文案写清是哪一端。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_advise_login_carries_surface_evidence():
    from core.pacing import advise
    node = {
        "query_attempts": 17, "query_ok": 0,
        "scopes": {"intl": {"paths": {
            "H5": {"attempts": 17, "login": 13, "ok": 0, "calendar": 0,
                   "empty": 0, "unsupported": 0},
        }}},
    }
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert got["state"] == "login", got
    assert got.get("path") == "H5", "登录判定未回传通路证据：%r" % (got,)
    assert got.get("scope") == "intl"
    assert "H5" in got["hint"]


def test_route_level_login_stays_non_relogin():
    """同一通路其他航线正常出数时不催重登（既有判据不许被本次改动带偏）。"""
    from core.pacing import advise
    node = {
        "query_attempts": 72, "query_ok": 30,
        "scopes": {"intl": {"paths": {
            "H5": {"attempts": 72, "login": 40, "ok": 30, "calendar": 2,
                   "empty": 0, "unsupported": 0},
        }}},
    }
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert got["state"] != "login"
    assert "别急着重登" in got["hint"]


def test_multi_slot_vendor_picks_slot_from_path_evidence():
    """账本判来的登录（无 needs_login）也必须按 adv.path 选端。"""
    w = _w()
    i = w.index("if(_own2.length>1){")
    seg = w[i:w.index("const _open=PACE.detail===k;", i)]
    assert "adv.path" in seg, "多会话分支未读路径证据"
    assert "surface_label" in seg, "按钮未写出是哪一端"
    # 分支不能再被 needs_login 独占门控
    assert "if(_own2.length>1&&v.needs_login)" not in w, \
        "多会话分支仍只在运行时 needs_login 时生效"
    # 兜底仍保留：没有路径证据时用坏槽位
    assert "_bad2" in seg, "缺坏槽位兜底"
    assert "verifyNow(" in seg, "单会话/无槽位时仍要有验证入口"


def test_no_evidence_falls_back_to_vendor_window_not_guessed_end():
    """运行时 needs_login 且两端都「已存待验」时，不得断言是哪一端。

    渲染实测：该载荷下按钮曾写成「去登录 PC」（取首个槽位），而真正被
    拦的是 H5 那份 profile——用户的会话明明没坏，却被指去登另一端。
    无证据时退回厂商级验证窗口（那里打开的就是采集同一份 profile）。
    """
    w = _w()
    i = w.index("if(_own2.length>1){")
    seg = w[i:w.index("const _open=PACE.detail===k;", i)]
    assert "_bad2[0]||null" in seg, "无证据时仍会猜首个槽位"
    assert "_own2[0].key" not in seg, "仍在无证据时落到首个槽位"


def test_top_entry_also_targets_the_evidenced_surface():
    """顶部「去登录」与行内按钮必须同源选端。

    实测隐患：账本说飞猪「国际 H5」被拦，行内已改成「去登录 H5」，但顶部
    `#hauthact` 仍写 dataset.p=<厂商>，点开落到飞猪 PC 登录行——同一屏两个
    「去登录」指向不同端。
    """
    w = _w()
    i = w.index("function healthLoginNudge(")
    seg = w[i:w.index("function healthSlotNote(", i)]
    assert "adv.path" in seg, "顶部入口未读路径证据"
    assert "ha.dataset.p=_keys[0]" in seg, "顶部入口未按证据落到槽位"
