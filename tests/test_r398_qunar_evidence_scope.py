# -*- coding: utf-8 -*-
"""r398：qunar 的「无票」证据不能跨界污染别的路径/别的日期。

两处真实泄漏，都会把「该重登」说成「真无票」（或反过来）：

1. `_last_no_result` 只在 fetch() 开头清一次，**不按日期清**。上一个
   日期确认「没有符合条件的航班」后，本日期什么都没拿到会被染成
   empty —— 一个真登录墙被说成无票。
2. httpx（API）路径从不认「明确无票」措辞，也不在自己发请求前清标志。
   实测库里有 18 行 `API/login` 却写着「原站返回无符合条件的航班」：
   H5 的判定漏到了 API 头上，而 API 自己的 1999 无票信号没人认。

empty=真无票（无需操作），login=该重登（需人工）——两者搞反，用户要么
被推去重登一个没坏的会话，要么真无票被当成故障反复排查。
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


def _crawler():
    c = QunarCrawler({}, logging.getLogger("t_r398"))
    c.path_reset()
    c._last_challenge = None
    return c


def _status(c, path):
    return [p["status"] for p in c.paths if p["path"] == path]


def test_no_result_does_not_leak_across_dates():
    """上一日期的 no-result 不得把本日期染成 empty。"""
    c = _crawler()
    c._last_no_result = True                    # 上一日期遗留
    QunarCrawler.login_suspect = True           # 会话确实失效
    c._fetch_via_browser = lambda *a, **k: None
    c._fetch_one("SHA", "BKK", "2026-11-16")
    assert _status(c, "H5") == ["login"], c.paths
    QunarCrawler.login_suspect = False


def test_true_no_result_still_empty():
    """本日期真的明确无票时，仍然必须是 empty（别把修复做过头）。"""
    c = _crawler()

    def _br(*a, **k):
        c._last_no_result = True
        return None

    c._fetch_via_browser = _br
    c._fetch_one("SHA", "BKK", "2026-11-17")
    assert _status(c, "H5") == ["empty"], c.paths


def test_no_result_text_is_recognized_on_api_body():
    """API 的 1999+明确措辞必须被认成无票，而不是"没有明细"。"""
    body = json.dumps({
        "bstatus": {"code": 1999, "status": 1999,
                    "msg": "没有查询到符合条件的航班"},
        "code": -1, "data": None,
        "msg": "没有查询到符合条件的航班", "ret": False,
    }, ensure_ascii=False)
    c = _crawler()
    assert c._no_result_text(body) is True
    # 不能把普通软拒/空壳误认成无票
    assert c._no_result_text(json.dumps({"ret": False, "msg": "系统繁忙"})) is False


def test_api_does_not_inherit_h5_verdict():
    """H5 判完无票后，API 必须自己重新判，不能继承。"""
    c = _crawler()
    c._last_no_result = True          # H5 刚判完
    seen = []

    def _httpx(fc, tc, d):
        # 记录进入 API 时标志是否已被清
        seen.append(bool(getattr(c, "_last_no_result", False)))
        c.last_soft_reject = {"kind": "token_gate", "note": "门拒"}
        return None

    c._fetch_via_browser = lambda *a, **k: None
    c._fetch_via_httpx = _httpx
    c._fetch_one("SHA", "BKK", "2026-11-16")
    assert seen == [False], "API 起点必须已清标志，实际=%r" % seen
    # 不继承 H5 的 empty，也不冒充 login
    assert _status(c, "API") == ["soft_reject"], c.paths


def test_blanket_1999_is_soft_not_empty():
    """httpx 的 1999「没有航班」是门拒文案，不得记 empty。

    实证：同一 token 连打四条已知有票的航线（SHA→BKK 别处采到 ¥662、
    SHA→HAK、HAK→SHA、SHA→NRT），四条回应一字不差都是
    code=-1 +「没有查询到符合条件的航班」+ data=null。
    真无票不会恰好四条全无、还与已采到的价矛盾。
    把它记成 empty = 谎报「真无票」，比记错登录更违反数据诚实。
    """
    import core.net as _net  # noqa: F401

    class _Resp:
        status_code = 200
        headers = {}
        text = json.dumps({
            "bstatus": {"code": 1999, "msg": "没有查询到符合条件的航班"},
            "code": -1, "data": None,
            "msg": "没有查询到符合条件的航班", "ret": False,
        }, ensure_ascii=False)

    c = _crawler()
    c._load_token = lambda: {"headers": {}, "body_template": {},
                             "cookies": {}, "updated_at": 0}
    c.last_soft_reject = {}
    import core.net
    _orig = core.net.post
    core.net.post = lambda *a, **k: _Resp()
    try:
        out = c._fetch_via_httpx("SHA", "BKK", "2026-11-16")
    finally:
        core.net.post = _orig
    assert out is None
    assert c.last_soft_reject.get("kind") == "token_gate", c.last_soft_reject
    assert getattr(c, "_last_no_result", False) is False, \
        "门拒文案不得被当成真无票"
