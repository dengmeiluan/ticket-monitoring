# -*- coding: utf-8 -*-
"""r1063 T11：特价雷达的每个真实发现源先问链路闸门，并按源计预算。

四条口径（前三条都是本项目的「静默缺陷」红线）：

1. **链路被策略停用 → 报「被策略停用」**。不许伪装成 0 行/无票（那是把
   「我方没发请求」显示成「这家没低价」，本仓库定义为最严重的静默类缺陷），
   也不许记 `error`（那是「对方拒绝」，处置方向完全不同）。
2. **停一家不许连坐**：给同程停掉低价日历后，携程/飞猪/途牛三个源照跑。
3. **预算耗尽单独成 `timeout` + 「预算耗尽」**，且已采到的行不丢。
4. **`paced`（我方克制）不是 `error`、也不是 `empty`**：T9 的 App 闸门把
   被停用的通路写成 `paced`，雷达原来按「有 note 就是失败」读成 `error`，
   于是停用 App 低价会在特价面板显示「失败」，把人引去查风控。
"""
import datetime as dt
import io
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import core.special_radar as sr
from core import strategy_params as sp
from core.pacing import PATH_DISABLED

TODAY = dt.date.today()
START = TODAY + dt.timedelta(days=3)
END = TODAY + dt.timedelta(days=6)


# ---------------------------------------------------------------- 夹具

@pytest.fixture(autouse=True)
def _fresh_gate(monkeypatch):
    """每个用例一份干净的参数层、闸门实例与源缓存。

    闸门与参数都是模块级单例（进程内共享），跨用例不清就会串味：
    上一个用例记进链路桶的一次外发，会让下一个用例白等一个 `min_gap`。
    """
    sp.invalidate()
    monkeypatch.setattr(sr, "_RADAR_PACING", None, raising=False)
    for cache in (sr._FLIGGY_CACHE, sr._TUNIU_CACHE, sr._TONGCHENG_CACHE,
                  sr._QUNAR_CACHE):
        cache.clear()
    monkeypatch.setattr(sr, "_FLIGGY_COOLDOWN_UNTIL", 0.0, raising=False)
    monkeypatch.setattr(sr, "_QUNAR_COOLDOWN_UNTIL", 0.0, raising=False)
    yield
    sp.invalidate()


class _Clock:
    """假时钟：只替 `special_radar.time`（`time()` / `sleep()`）。

    预算用例不该真的睡——真睡 1 秒既慢又抖（CI 上 `time.time()` 精度、
    调度延迟都会让「刚好超预算」变成「刚好没超」）。这里让每次假外发
    自己把钟往前推，判定完全确定。
    """

    def __init__(self, t=1_000_000.0):
        self.t = float(t)

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)
        return None

    def advance(self, s):
        self.t += float(s)


def _deal(src, d, price):
    return sr.SpecialDeal(src, "SHA", "BJS", d, float(price), link="",
                          to_name="北京", tax_included=True,
                          price_basis="tax_included",
                          price_basis_label="含税总价")


def _install_browser_sources(monkeypatch, clock=None):
    """四个浏览器源的假 fetcher：各回一条该航线的日期价，并数调用次数。"""
    called = {}
    d = START.isoformat()

    def bump(ch):
        called[ch] = called.get(ch, 0) + 1
        if clock is not None:
            clock.advance(0.01)

    def ctrip_calendar(fc, tc, start, logger, proxy=None):
        bump("ctrip")
        return {"fake": "ctrip"}

    def ctrip_calendar_deals(payload, fc, tc, tn, watch, today):
        return [_deal("ctrip", d, 500)]        # `normalize` 认的日历代号

    def fliggy_calendar(fc, tc, leave, logger, proxy=None):
        bump("fliggy")
        return [{"leaveDate": d, "price": 600, "tax": 0}]

    def tuniu_calendar(fc, tc, dep, logger, proxy=None):
        bump("tuniu")
        return [{"date": d, "price": 700}]

    def tongcheng_calendar(fc, fn, tc, tn, anchor, logger, proxy=None):
        bump("tongcheng")
        return [{"date": d, "price": 800}]

    monkeypatch.setattr(sr, "fetch_ctrip_calendar", ctrip_calendar)
    monkeypatch.setattr(sr, "ctrip_calendar_deals", ctrip_calendar_deals)
    monkeypatch.setattr(sr, "fetch_fliggy_calendar", fliggy_calendar)
    monkeypatch.setattr(sr, "fetch_tuniu_calendar", tuniu_calendar)
    monkeypatch.setattr(sr, "fetch_tongcheng_calendar", tongcheng_calendar)
    return called


def _radar(channels):
    return sr.build_radar(
        {"user": "t", "from": "SHA", "to": "BJS",
         "start": START.isoformat(), "end": END.isoformat(),
         "channels": list(channels)},
        logging.getLogger("radar_r1063"))


# ---------------------------------------------------------------- Step 1 锚点

def test_radar_sources_ask_the_gate_and_read_a_budget():
    """brief 的源码锚点（四个源逐个断言）+ 预算判据用**真断言**。

    复核（第一轮）指出：原写法 `assert "budget.value" in body` 只命中了源码
    注释里的另一个名字，是恒真的死门禁（写句注释就能骗过）。这里改成断
    「求值入口真的存在、真的能求出值」——注释不再是判据。
    """
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = io.open(os.path.join(root, "core", "special_radar.py"),
                   encoding="utf-8").read()
    for fn in ("_ctrip_deals", "_fliggy_deals", "_tuniu_deals",
               "_tongcheng_deals"):
        seg = body[body.index("def %s(" % fn):][:1200]
        assert "gate_path(" in seg, "%s 没问链路闸门" % fn
    # brief 把它写作 `budget.value`（改名前的叫法），契约登记的真名是
    # `budget.fetch_s`（cfg `android.fetch_budget_s`，默认 540s）。
    assert sr._BUDGET_PID == "budget.fetch_s", sr._BUDGET_PID
    assert sr._BUDGET_PID in sp.PARAMS, sr._BUDGET_PID
    got = sp.resolve(sr._BUDGET_PID, plat="ctrip")
    assert isinstance(got.value, (int, float)) and got.value >= 0, got


# ---------------------------------------------------------------- (a)+(b)

def test_disabled_source_reports_policy_stop_and_others_still_run(monkeypatch):
    """停掉同程的低价日历：同程报「被策略停用」，另外三家照跑（不连坐）。"""
    called = _install_browser_sources(monkeypatch)
    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng/low_fare/日历": {"path_fallback.enabled": False}}}})

    out = _radar(["ctrip", "fliggy", "tuniu", "tongcheng"])
    st = out["sources"]["tongcheng"]

    # (a) 被停用 ≠ 失败 ≠ 没票：单独报「被策略停用」并说清是我方没发
    assert st["status"] == "unsupported", st
    assert PATH_DISABLED in st["reason"], st
    assert "我方" in st["reason"], st
    assert st.get("paced") is True, st
    assert called.get("tongcheng", 0) == 0, "被停用的源不许再外发"

    # (b) 只停那一条：同一次查询里另外三家的源照跑、照出数
    for ch in ("ctrip", "fliggy", "tuniu"):
        s = out["sources"][ch]
        assert s["status"] == "ok", (ch, s)
        assert s["rows"] >= 1, (ch, s)
        assert called.get(ch, 0) >= 1, ch
    assert out["lowest"]["price"] == 500


def test_gate_stop_never_reads_as_empty_or_error(monkeypatch):
    """负控：被停用时状态字必须是 `unsupported`，不许落成 empty/error。"""
    _install_browser_sources(monkeypatch)
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy/low_fare/日历": {"path_fallback.enabled": False}}}})
    rows, st = sr._fliggy_deals(sr.parse_query({
        "from": "SHA", "to": "BJS", "start": START.isoformat(),
        "end": END.isoformat(), "channels": ["fliggy"]}),
        logging.getLogger("radar_r1063"), "")
    assert rows == []
    assert st["status"] not in ("ok", "empty", "error"), st
    assert st["status"] == "unsupported", st
    assert PATH_DISABLED in st["reason"], st


# ---------------------------------------------------------------- (c) 预算

def test_budget_exhausted_cuts_off_and_reports_timeout(monkeypatch):
    """全国榜要连打多个 30 天窗：预算用完就停手，报 `timeout`+「预算耗尽」。"""
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)
    windows = []
    d = START.isoformat()

    def board(fc, fn, start, end, logger, proxy=None):
        windows.append((start, end))
        clock.advance(2.0)          # 一次外发吃掉 2 秒
        return {"fake": "board"}

    monkeypatch.setattr(sr, "fetch_ctrip_board", board)
    monkeypatch.setattr(sr, "deals_from_ctrip_board",
                        lambda payload, watch, today: [_deal("ctripbd", d, 400)])
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"budget.fetch_s": 1}}}})
    assert sr._budget_s("ctrip") == 1, "预算没按渠道覆盖求值"

    q = sr.RadarQuery("t", "SHA", "上海", "", "全国", TODAY,
                      TODAY + dt.timedelta(days=80), ["ctrip"],
                      nationwide=True)
    rows, st = sr._ctrip_deals(q, logging.getLogger("radar_r1063"), "")

    assert st["status"] == "timeout", st
    assert "预算耗尽" in st["reason"], st
    assert len(windows) == 1, "预算用完还去打第二个 30 天窗：%r" % (windows,)
    assert len(rows) == 1, "已采到的行不许在收工时丢掉"


def test_no_budget_means_no_cutoff(monkeypatch):
    """预算 0 = 不限（与 Android 采集同口径）：不许把「没配」读成「立刻收工」。"""
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)
    d = START.isoformat()
    monkeypatch.setattr(sr, "fetch_tongcheng_calendar",
                        lambda *a, **k: [{"date": d, "price": 800}])
    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng": {"budget.fetch_s": 0}}}})
    assert sr._budget_s("tongcheng") == 0

    rows, st = sr._tongcheng_deals(sr.parse_query({
        "from": "SHA", "to": "BJS", "start": START.isoformat(),
        "end": END.isoformat(), "channels": ["tongcheng"]}),
        logging.getLogger("radar_r1063"), "")
    assert st["status"] == "ok" and len(rows) == 1, st


def _query(ch):
    """本文件统一的雷达条件：SHA→BJS，今天+3..+6（都在各源的可查窗口内）。"""
    return sr.RadarQuery("t", "SHA", "上海", "BJS", "北京", START, END, [ch])


_LOG = logging.getLogger("radar_r1063")


# ---------------------------------------------------------------- (c)-2 回退切点

def test_fliggy_board_fallback_respects_budget(monkeypatch):
    """**回退榜单循环**也要判预算（复核第一轮的 Important）。

    复核者实测：预算 70s，日历 5 窗跑完后回退榜单又外发 4 次
    （t=83/98/113/128），最后返回 `error`（「网络超时…稍后重试」）——
    把「我方预算用完」报成了「对方失败」，而且是在预算早已耗尽之后继续打源。
    所以预算判定必须放在回退循环顶部，且一次榜都不许打。
    """
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)
    board_calls = []

    def calendar(*a, **k):
        clock.advance(80.0)         # 一次外发就把 70s 预算用光
        return None                 # 台账拒绝 → 触发回退榜单

    def board(fc, start, end, logger, proxy=None):
        board_calls.append((start, end))
        clock.advance(15.0)
        return {"fake": "board"}

    monkeypatch.setattr(sr, "fetch_fliggy_calendar", calendar)
    monkeypatch.setattr(sr, "fetch_fliggy_board", board)
    monkeypatch.setattr(sr, "deals_from_fliggy_board",
                        lambda payload, watch, today: [_deal("fliggybd",
                                                             START.isoformat(),
                                                             450)])
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"budget.fetch_s": 70}}}})

    rows, st = sr._fliggy_deals(_query("fliggy"), _LOG, "")

    assert st["status"] == "timeout", st
    assert "预算耗尽" in st["reason"], st
    assert board_calls == [], "预算已用完还打了回退榜单：%r" % (board_calls,)


def test_fliggy_board_fallback_still_runs_within_budget(monkeypatch):
    """负控：预算充足时回退榜单必须照旧跑（别把切点做成「永不回退」）。"""
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)
    board_calls = []

    def board(fc, start, end, logger, proxy=None):
        board_calls.append((start, end))
        clock.advance(3.0)
        return {"fake": "board"}

    monkeypatch.setattr(sr, "fetch_fliggy_calendar", lambda *a, **k: None)
    monkeypatch.setattr(sr, "fetch_fliggy_board", board)
    monkeypatch.setattr(sr, "deals_from_fliggy_board",
                        lambda payload, watch, today: [_deal("fliggybd",
                                                             START.isoformat(),
                                                             450)])

    rows, st = sr._fliggy_deals(_query("fliggy"), _LOG, "")

    assert board_calls, "预算充足却不回退榜单了"
    assert st["status"] == "ok" and len(rows) == 1, st
    assert st.get("fallback") == "board", st


def test_tuniu_board_fallback_respects_budget(monkeypatch):
    """途牛回退榜单是第二个外发点：预算用完就不许再打（同样不许报成失败）。"""
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)
    board_calls = []

    def calendar(*a, **k):
        clock.advance(80.0)
        return None

    def board(*a, **k):
        board_calls.append(1)
        return {"fake": True}

    monkeypatch.setattr(sr, "fetch_tuniu_calendar", calendar)
    monkeypatch.setattr(sr, "fetch_tuniu_board", board)
    sp.set_config({"crawler": {"strategy_overrides": {
        "tuniu": {"budget.fetch_s": 70}}}})

    rows, st = sr._tuniu_deals(_query("tuniu"), _LOG, "")

    assert st["status"] == "timeout", st
    assert "预算耗尽" in st["reason"], st
    assert board_calls == [], "预算已用完还打了途牛榜单"


def test_tongcheng_over_budget_is_timeout_not_error(monkeypatch):
    """同程只有一个外发点：**事后**判定，超预算报 `timeout`，不许报成对方失败。"""
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)

    def calendar(*a, **k):
        clock.advance(80.0)
        return None

    monkeypatch.setattr(sr, "fetch_tongcheng_calendar", calendar)
    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng": {"budget.fetch_s": 70}}}})

    rows, st = sr._tongcheng_deals(_query("tongcheng"), _LOG, "")

    assert rows == []
    assert st["status"] == "timeout", st
    assert "预算耗尽" in st["reason"], st


def test_tongcheng_failure_without_budget_hit_stays_error(monkeypatch):
    """负控：预算没超时，同一次失败仍然是 `error`（对方拒绝），不许被吞成 timeout。"""
    clock = _Clock()
    monkeypatch.setattr(sr, "time", clock, raising=False)

    def calendar(*a, **k):
        clock.advance(3.0)
        return None

    monkeypatch.setattr(sr, "fetch_tongcheng_calendar", calendar)

    rows, st = sr._tongcheng_deals(_query("tongcheng"), _LOG, "")

    assert rows == []
    assert st["status"] == "error", st


# ---------------------------------------------------------------- 状态文案
#
# 复核 2026-11-06 第 4 条：`core/special_radar.py` 会发出 `timeout`，而前端
# `SRX_RADAR_ST` 里没有这一格；两处渲染写的是 `SRX_RADAR_ST[s.status]||s.status`，
# 于是屏幕上直接出现裸英文码 `timeout`。这一批钉住「雷达发出的每个状态码都有
# 中文文案」，并且**逐码从源码里取**（不是手抄一份清单——手抄的清单最先过期）。

def _radar_status_codes():
    """`core/special_radar.py` 里 `_status(...)` 的第一个实参出现的全部状态码。"""
    import ast
    import re as _re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "special_radar.py"),
                  encoding="utf-8").read()
    tree = ast.parse(src)
    codes = set()

    def _collect(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _re.fullmatch(r"[a-z][a-z_]*", node.value):
                codes.add(node.value)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_status"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        _collect(first)
        if isinstance(first, ast.IfExp):        # `"ok" if rows else "empty"`
            _collect(first.body)
            _collect(first.orelse)
    return codes


def _radar_label_table():
    """`webui.py` 的 `SRX_RADAR_ST={…}` → {状态码: 中文文案}。"""
    import re as _re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    web = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    m = _re.search(r"SRX_RADAR_ST=\{([^}]*)\}", web)
    assert m, "webui.py 里找不到雷达状态文案表 SRX_RADAR_ST"
    return dict(_re.findall(r"""([a-z][a-z_]*)\s*:\s*['"]([^'"]*)['"]""",
                            m.group(1)))


def test_every_radar_status_code_has_a_chinese_label():
    """每个会出现在雷达面板上的状态码都必须有中文文案（不许漏裸英文码）。"""
    codes = _radar_status_codes()
    assert codes, "一个状态码都没扫到：判据失去锚点"
    assert "timeout" in codes, "预算耗尽那条不再发 timeout 了？判据要跟着改"
    labels = _radar_label_table()
    missing = sorted(c for c in codes if c not in labels)
    assert not missing, "这些状态码没有中文文案，界面会显示裸英文码：%s" % missing
    for code in codes:
        assert labels[code].strip(), "%s 的文案是空的" % code
        assert not re.search(r"[A-Za-z]", labels[code]), \
            "%s 的文案里还有英文：%s" % (code, labels[code])


def test_timeout_is_labelled_as_budget_exhausted_not_a_silent_failure():
    """`timeout` 是**我方预算耗尽**，文案必须这么说（不是「对方超时/失败」）。"""
    labels = _radar_label_table()
    assert labels["timeout"] == "预算耗尽", labels["timeout"]
    # 与后端那句理由同源：`_budget_reject()` 的 why 里也写着「预算耗尽」
    q = sr.RadarQuery("t", "SHA", "上海", "BJS", "北京", TODAY, END, ["ctrip"])
    rows, st = sr._budget_reject("ctrip", [], 30)
    assert st["status"] == "timeout" and "预算耗尽" in st["reason"], st

def test_cache_hit_under_stopped_link_is_flagged(monkeypatch):
    """链路刚被停用、本轮命中缓存：旧数据照给，但必须说明「已被停用 + 缓存复用」。

    否则面板会把一条 180 秒前的旧数据读成「这条链路还在跑」——停用看起来
    没生效。命中缓存**不许**动链路桶记账、也不许睡（这一轮没有任何外发）。
    """
    calls = []
    d = START.isoformat()

    def calendar(*a, **k):
        calls.append(1)
        return [{"date": d, "price": 800}]

    monkeypatch.setattr(sr, "fetch_tongcheng_calendar", calendar)
    q = _query("tongcheng")
    rows, st = sr._tongcheng_deals(q, _LOG, "")
    assert st["status"] == "ok" and len(rows) == 1, st
    assert len(calls) == 1, st

    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng/low_fare/日历": {"path_fallback.enabled": False}}}})
    rows2, st2 = sr._tongcheng_deals(q, _LOG, "")

    assert len(rows2) == 1, st2
    assert st2.get("cache_hit") is True, st2
    assert len(calls) == 1, "命中缓存还去外发了"
    assert PATH_DISABLED in st2["reason"], st2
    assert "缓存复用" in st2["reason"], st2
    assert st2.get("stopped_now") is True, st2


# ---------------------------------------------------------------- 第五个源

def test_qunar_source_asks_the_gate(monkeypatch):
    """去哪儿低价页是雷达第五个真外发的浏览器源：停用后同样不许再打。"""
    calls = []
    import crawlers.qunar as qmod
    monkeypatch.setattr(qmod.QunarCrawler, "fetch_low_price_calendar",
                        lambda *a, **k: calls.append(1))
    sp.set_config({"crawler": {"strategy_overrides": {
        "qunar/low_fare/日历": {"path_fallback.enabled": False}}}})

    rows, st = sr._qunar_deals(_query("qunar"), _LOG, "")

    assert rows == [], st
    assert st["status"] == "unsupported", st
    assert PATH_DISABLED in st["reason"], st
    assert st.get("paced") is True, st
    assert calls == [], "被停用还去开页面打去哪儿低价页"


# ---------------------------------------------------------------- (d) paced

_PACED = {"path": "low-fare", "status": "paced",
          "detail": "链路被策略停用：%s 的 low-fare 被 path_fallback.enabled=false 停用"}


@pytest.mark.parametrize("fn, mod, cls, ch", [
    ("_app_qunar_deals", "crawlers.app_qunar", "AppQunarCrawler", "app_qunar"),
    ("_app_ctrip_deals", "crawlers.app_ctrip", "AppCtripCrawler", "app_ctrip"),
    ("_app_tongcheng_deals", "crawlers.app_tongcheng",
     "AppTongchengCrawler", "app_tongcheng"),
    ("_app_zhixing_deals", "crawlers.app_zhixing", "AppZhixingCrawler",
     "app_zhixing"),
])
def test_paced_low_fare_is_not_an_error(monkeypatch, fn, mod, cls, ch):
    """`paced` = 我方按策略克制，不许读成 error（对方拒绝）或 empty（无票）。"""

    class Fake:
        paths = [dict(_PACED, detail=_PACED["detail"] % ch)]

        def low_fare(self, *a, **k):
            return []

    module = __import__(mod, fromlist=[cls])
    monkeypatch.setattr(module, cls, lambda *a, **k: Fake())
    rows, st = getattr(sr, fn)(_query(ch), None)

    assert rows == [], st
    assert st["status"] != "error", (fn, st)
    assert st["status"] != "empty", (fn, st)
    assert st["status"] == "unsupported", (fn, st)
    assert st.get("paced") is True, (fn, st)
    assert PATH_DISABLED in st["reason"], (fn, st)
    # 复核（第一轮）要求：理由句里要带渠道与链路，面板才定位得到是哪条。
    assert ch in st["reason"], (fn, st)
    assert st.get("plat") == ch, (fn, st)
    assert st.get("path") == "low-fare", (fn, st)
