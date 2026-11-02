# -*- coding: utf-8 -*-
"""r736 飞猪国内「往返」实际跑的是单程列表页 —— 单程价冒充往返总价。

用户要求「五渠道 PC 和 H5 都要重点检查」。逐端面实跑发现：

    fliggy   rows=1  ¥497  HO1257  通路 PC  detail=sjipiao.fliggy.com SSR 列表

¥497 是上海→北京的单程水平，extra 里没有任何返程字段，而矩阵写
`fliggy.round_trip = "y"`。

代码证据：`FliggyCrawler.fetch` 的主循环是 `self._fetch_pc(fc, tc, date)`
—— **ret_date 根本没传进去**；它只在「PC 一条都没拿到」时才传给
`_h5_fallback`。而 H5 那条已按 r735 改成显式 unsupported。

也就是说：飞猪的往返能力**只存在于低价日历**（`_calendar_params` 的
`tripType=1 + backDate`），列表页并不支持；`fetch` 却把列表页的单程价
当成往返结果返回。

判据（与 ctrip / tuniu / fliggy_h5 同律）：
  * 传 ret_date 时不得返回「无返程证据」的行；
  * 「无返程证据」= extra 里没有 backDate/retDate/retCode/retTripType；
  * 拿不到真往返就显式 unsupported 落账，返回空。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                   encoding="utf-8").read()


def _fetch_body():
    src = _src()
    i = src.index("    def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_domestic_round_trip_bails_out_before_the_list_loop():
    """守卫：国内往返必须在进入单程列表循环**之前**就显式退出。

    国内列表页只有单程，继续往下走必然把单程价当往返返回（r736 实测
    ¥497）。所以 fetch 里 ret_date 的判断要出现在 `for date in dates`
    之前，且落 unsupported。
    """
    body = _fetch_body()
    i_guard = body.find("国内往返暂不支持")
    i_loop = body.find("for date in dates")
    assert i_guard > 0, "fetch 里没有国内往返的显式处置"
    assert i_loop > 0, "找不到单程列表循环"
    assert i_guard < i_loop, (
        "国内往返判断出现在单程循环之后——单程价已经先算出来了")
    assert "unsupported" in body[i_guard - 400:i_guard + 200], (
        "国内往返没有落 unsupported")


def test_round_trip_without_return_evidence_is_not_returned():
    """行为：假的「往返」行（无返程证据）不能当结果返回。"""
    import logging
    from crawlers.fliggy import FliggyCrawler

    inst = FliggyCrawler({"user_data_dir": "user_data"},
                         logging.getLogger("t"))

    # 模拟 PC 拿到一条纯单程行（无返程字段）
    def _fake_pc(fc, tc, date, ret_date="", **_):
        return [{"price": 497, "code": "HO1257", "name": "吉祥",
                 "depTime": "08:25", "arrTime": "10:50"}]

    inst._fetch_pc = _fake_pc            # type: ignore
    inst._sleep = lambda *a, **k: None   # 不真睡
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"], ret_date="2026-11-24")
    assert rows == [], (
        "没有返程证据的单程行被当成往返结果返回了：%s"
        % [getattr(r, "price", r) for r in rows])


def test_oneway_still_returns(monkeypatch):
    """负控：不传 ret_date 时照常返回单程（别把单程也拦掉）。"""
    import logging
    from crawlers.fliggy import FliggyCrawler

    inst = FliggyCrawler({"user_data_dir": "user_data"},
                         logging.getLogger("t"))
    inst._fetch_pc = lambda fc, tc, date, ret_date="", **_: [
        {"price": 497, "code": "HO1257", "name": "吉祥",
         "depTime": "08:25", "arrTime": "10:50"}]
    inst._sleep = lambda *a, **k: None
    inst.path_note = lambda *a, **k: None
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"])
    assert len(rows) == 1 and rows[0].price == 497, rows


def test_international_round_trip_still_goes_through_the_calendar():
    """正控：国际往返不被国内那条闸门拦掉（飞猪真往返在国际日历里）。

    国际走 `cheapestCalendar`（tripType=1 + backDate），与国内列表页是两条
    路。这里只钉住「国内闸门不误伤国际」，不假装国际一定出数。
    """
    import logging
    from crawlers.fliggy import FliggyCrawler

    inst = FliggyCrawler({"user_data_dir": "user_data"},
                         logging.getLogger("t"))
    seen = {}

    def _fake_intl(fc, tc, dates, ret_date=""):
        seen["fc"], seen["tc"] = fc, tc
        seen["ret"] = ret_date
        return []

    inst._fetch_intl = _fake_intl        # type: ignore
    inst.fetch("SHA", "NRT", ["2026-11-20"], ret_date="2026-11-24")
    assert seen.get("fc") == "SHA", (
        "国际往返被国内闸门拦掉了，没走到 _fetch_intl：%s" % (seen,))
    assert seen.get("ret") == "2026-11-24", seen
