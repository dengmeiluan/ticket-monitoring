# -*- coding: utf-8 -*-
"""r400：qunar 的「当前搜索无航线」是通道级门拒，不是"真没航班"。

实测（2026-10-27 08:0x，同一会话连打四条航线，浏览器 H5 与 httpx 各一遍）：

```
SHA→BKK   ret=false code=3  msg="当前搜索无航线，请更换城市重新搜索"
SHA→HKG   ret=false code=3  同上（换「香港」「中国香港」两种城市名都一样）
SHA→NRT   ret=false code=3  同上
SHA→TYO   ret=false code=3  同上
```

SHA→BKK 在 2 小时前刚从**同一渠道**采到 ¥662（9C7293），却有同样的回应。
真"查了没票"不会四条全无、更不会与刚采到的价矛盾 —— 这是通道级门拒。

若不识别，它会落进 `login_suspect ? login : empty` 的 else 分支被记成
empty，即向读者宣告「今天确实没有航班」并停止关注。按 soft_reject
（门拒、预热可解、可自愈）记录才是事实。

另：H5 完全没拿到东西（无响应、空正文、无风控/无票证据）此前也记 empty；
改为 error——「没证据」不能用来支撑「无票」这个结论。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

GATE = ('{"ret":false,"msg":"当前搜索无航线，请更换城市重新搜索",'
        '"code":3,"data":"x"}')


def _c():
    c = QunarCrawler({}, logging.getLogger("t_r400"))
    c.path_reset()
    c._last_challenge = None
    return c


def test_blanket_gate_recognized():
    assert QunarCrawler._blanket_gate_text(GATE) == "当前搜索无航线，请更换城市重新搜索"


def test_ordinary_no_result_is_not_blanket_gate():
    """真正的"没有符合条件的航班"（1999 措辞）不能被当成门拒。"""
    body = ('{"bstatus":{"code":1999,"msg":"没有查询到符合条件的航班"},'
            '"code":-1,"data":null,"msg":"没有查询到符合条件的航班","ret":false}')
    assert QunarCrawler._blanket_gate_text(body) == ""


def test_gate_is_not_treated_as_empty():
    """门拒不得被 _no_result_text 认成"真无票"。"""
    c = _c()
    assert c._no_result_text(GATE) is False


def test_h5_gate_records_soft_reject():
    c = _c()

    def _browser(*a, **k):
        # 证据由浏览器路径在调用内产生（_fetch_one 起点会清空旧证据）
        c.last_soft_reject = {"kind": "blanket_gate",
                              "note": "当前搜索无航线，请更换城市重新搜索"}
        return None

    c._fetch_via_browser = _browser
    c._fetch_via_httpx = lambda *a, **k: None
    c._fetch_one("SHA", "HKG", "2026-11-16")
    st = {p["path"]: p["status"] for p in c.paths}
    assert st.get("H5") == "soft_reject", c.paths


def test_soft_evidence_reset_between_paths():
    """H5 的门拒证据不得漏到 API（r398 同类泄漏的守卫）。"""
    c = _c()
    seen = []

    def _httpx(fc, tc, d):
        seen.append(bool(getattr(c, "last_soft_reject", None)))
        c.last_soft_reject = {"kind": "blanket_gate", "note": "gate"}
        return None

    c._fetch_via_browser = lambda *a, **k: None
    c.last_soft_reject = {"kind": "blanket_gate", "note": "H5 gate"}
    c._fetch_via_httpx = _httpx
    c._fetch_one("SHA", "HKG", "2026-11-16")
    assert seen == [False], "API 起点必须已清 H5 的门拒证据，实际=%r" % seen


def test_no_evidence_is_error_not_empty():
    """H5 什么都没拿回来时按 error 记，不宣称无票。"""
    c = _c()

    def _browser(*a, **k):
        c._last_no_evidence = True
        return None

    c._fetch_via_browser = _browser
    c._fetch_via_httpx = lambda *a, **k: None
    QunarCrawler.login_suspect = False
    try:
        c._fetch_one("SHA", "HKG", "2026-11-16")
        st = {p["path"]: p["status"] for p in c.paths}
        assert st.get("H5") == "error", c.paths
    finally:
        QunarCrawler.login_suspect = False


# ── r401：有行无价不得抛 min() 空序列 ──────────────────────────────────

def test_priceless_rows_do_not_crash():
    """有明细行但全部无价格时，`min(prices)` 曾抛 ValueError。

    实测 2026-10-27 09:30 两条 SHA→HAK 就落在这个洞里：H5 记 empty、
    API 记「ok 但 0 行、note 却是无票文案」——账本自相矛盾，读者无法
    判断是没票、被拦、还是解析挂了。
    """
    import core.net
    import types

    c = _c()
    c._load_token = lambda: {"headers": {}, "body_template": {}, "cookies": {}}
    c._parse_response_flights = lambda t: [{"code": "MU5101", "price": 0},
                                           {"code": "MU5102"}]

    class _R:
        status_code = 200
        headers = {}
        text = '{"ret":true,"data":"x"}'

    _orig = core.net.post
    core.net.post = lambda *a, **k: _R()
    try:
        out = c._fetch_via_httpx("SHA", "HAK", "2027-01-29")
    finally:
        core.net.post = _orig
    assert out is None, out
    assert c.last_soft_reject.get("kind") == "no_price", c.last_soft_reject


def test_ok_status_always_has_rows():
    """不变式：状态记 ok 时 rows 必须 >0（0 行的 ok 是自相矛盾）。"""
    c = _c()

    def _httpx(*a, **k):
        c.last_soft_reject = {"kind": "no_price", "note": "有行无价"}
        return None

    c._fetch_via_browser = lambda *a, **k: None
    c._fetch_via_httpx = _httpx
    c._fetch_one("SHA", "HAK", "2027-01-29")
    for p in c.paths:
        # 核心不变式：没有拿到数据就不能记 ok
        if p["status"] == "ok":
            assert p["rows"] > 0, p
        # 且实现路径上"有行无价"要自述其因，不能落回无票/登录话术
        assert "无符合条件的航班" not in p["detail"] or p["status"] == "empty", p


# ── r404：门拒不得误触发退避重试与"会话失效" ───────────────────────────

def test_blanket_gate_skips_backoff_retry():
    """整体门拒时同轮不再阶梯退避连打（重试注定同果，白打请求）。"""
    c = _c()
    QunarCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0
    calls = {"n": 0}

    def _inner(fc, tc, dates):
        calls["n"] += 1
        c.last_soft_reject = {"kind": "blanket_gate", "note": "当前搜索无航线"}
        return []

    c._fetch_inner = _inner
    try:
        res = c.fetch("SHA", "HKG", ["2026-11-16"])
        assert res == []
        assert calls["n"] == 1, "门拒后不应再退避重试，实际 %d 次" % calls["n"]
    finally:
        QunarCrawler.login_suspect = False
        QunarCrawler._cooldown_until = 0.0


def test_blanket_gate_does_not_flag_session_invalid():
    """门拒不是会话失效——否则界面会催人重登一个完好的会话。"""
    c = _c()
    QunarCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0

    def _inner(fc, tc, dates):
        c.last_soft_reject = {"kind": "blanket_gate", "note": "当前搜索无航线"}
        return []

    c._fetch_inner = _inner
    try:
        c.fetch("SHA", "HKG", ["2026-11-16"])
        assert QunarCrawler.login_suspect is False, "门拒不得置 login_suspect"
    finally:
        QunarCrawler.login_suspect = False
        QunarCrawler._cooldown_until = 0.0


def test_ordinary_empty_still_retries():
    """普通无名空仍按原逻辑退避一次（别把修复做过头）。"""
    c = _c()
    QunarCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0
    c._MIN_GAP_S = 0
    calls = {"n": 0}

    def _inner(fc, tc, dates):
        calls["n"] += 1
        if calls["n"] >= 2:
            QunarCrawler.login_suspect = True   # 第二轮起走"跳过"分支
        return []

    c._fetch_inner = _inner
    c._BACKOFF_S = (0,)
    try:
        c.fetch("SHA", "HAK", ["2026-11-16"])
        assert calls["n"] >= 2, "普通空结果应至少重试一次，实际 %d" % calls["n"]
    finally:
        QunarCrawler.login_suspect = False
        QunarCrawler._cooldown_until = 0.0
