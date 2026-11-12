# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1072_qunar_gate_noretry.py
- tests/test_r339_qunar_backoff.py
- tests/test_r358_qunar_access.py
- tests/test_r400_qunar_blanket_gate.py
- tests/test_r805as_qunar_city_retap.py
- tests/test_r815a_qunar_native_calendar_lowfare.py
- tests/test_r928_qunar_city_tab.py
- tests/test_r933_qunar_flight_no.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import inspect
import io
import itertools
import logging
import os
import pytest
import sys

from core.channels import CHANNEL_DIMENSIONS, DIMENSION_NOTES, app_alignment_gaps
from core.specials import SPECIAL_CAPABILITY
from crawlers import app_qunar as q
from crawlers.app_qunar_parse import _desc_flight_marks, parse_flight_rows
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r1072_qunar_gate_noretry.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SRC = os.path.join(ROOT, "crawlers", "qunar.py")


def _src():
    return io.open(SRC, encoding="utf-8", errors="replace").read()


def test_gate_cooldown_constant_is_rate_limit_window():
    """冷却要覆盖限流窗口（代码内实测记录≈5 分钟/次），不能是 90 秒。"""
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler.GATE_COOLDOWN_S == 300
    assert QunarCrawler.GATE_COOLDOWN_S >= QunarCrawler._BACKOFF_S[0]


def test_token_gate_is_treated_as_gate_not_retried():
    s = _src()
    assert 'if _gate.get("kind") in ("blanket_gate", "token_gate"):' in s, \
        "门拒分支必须同时覆盖 token_gate（1999 限流）"


def test_old_single_kind_check_is_gone():
    """旧写法（只认 blanket_gate）必须已经不存在，防止回退。"""
    s = _src()
    assert 'if _gate.get("kind") == "blanket_gate":' not in s


def test_gate_branch_sets_cooldown_and_skips_retry():
    s = _src()
    i = s.index('in ("blanket_gate", "token_gate")')
    branch = s[i:i + 1200]
    assert "_cooldown_until" in branch, "门拒分支要给渠道冷却"
    assert "GATE_COOLDOWN_S" in branch
    assert "同轮不再重试" in branch
    assert "return []" in branch, "门拒分支必须直接返回，不进入退避睡眠"


def test_backoff_ladder_unchanged_for_normal_soft_empty():
    """普通软空仍保留阶梯退避（那类确实有救，别一并砍掉）。"""
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler._BACKOFF_S == (90, 180, 300)


# ---- merged from tests/test_r339_qunar_backoff.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture
def q_cls():
    from crawlers.qunar import QunarCrawler
    had = hasattr(QunarCrawler, "login_suspect")
    old = getattr(QunarCrawler, "login_suspect", None)
    old_gap, old_back = QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S
    old_cd, old_done = QunarCrawler._cooldown_until, QunarCrawler._last_done_ts
    QunarCrawler._MIN_GAP_S = 0
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    yield QunarCrawler
    if had:
        QunarCrawler.login_suspect = old
    elif hasattr(QunarCrawler, "login_suspect"):
        delattr(QunarCrawler, "login_suspect")
    QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S = old_gap, old_back
    QunarCrawler._cooldown_until, QunarCrawler._last_done_ts = old_cd, old_done


def test_qunar_suspect_skips_backoff_chain(q_cls, monkeypatch, tmp_path):
    """无认证证据 + login_suspect 在案 → 空结果单次放弃。

    r817 起旧标记会先做会话探测；本用例用隔离空档案保证探测不发起，
    仍守「确定性失效不进 90/180/300 重试链」。
    """
    calls = []

    def _empty(a, b, d):
        calls.append(1)
        return None

    q_cls._auth_probe_at = 0.0
    q_cls._auth_probe_ok = None
    c = q_cls({"user_data_dir": str(tmp_path)}, logging.getLogger("t339"))
    monkeypatch.setattr(c, "_fetch_one", _empty)
    q_cls.login_suspect = True
    q_cls._BACKOFF_S = (0, 0, 0)   # 三档全即时——未砍档则共试 4 次
    assert c.fetch("上海", "海口", ["2027-01-29"]) == []
    assert len(calls) == 1, f"无认证证据仍重试 {len(calls)} 次"
    assert q_cls.login_suspect is True   # 失效证据不清（引导重登）


def test_qunar_suspect_hit_still_clears(q_cls, monkeypatch):
    """砍档不拦自愈路：失效证据在案但本轮出数 → 正常返回并清标记
    （r290 自愈语义不变；退避链能力随复位恢复——限流窗内下轮重新
    全链，砍档面仅限「证据在案的当轮重试」）。"""
    c = q_cls({}, logging.getLogger("t339"))
    flights = [{"code": "CA8573", "name": "国航CA8573", "price": 1750.0,
                "depTime": "15:30", "arrTime": "18:55"}]
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: (1750.0, flights))
    q_cls.login_suspect = True
    out = c.fetch("上海", "海口", ["2027-01-29"])
    assert out and q_cls.login_suspect is False, out


def test_qunar_backoff_config_intact():
    """阶梯退避配置本体不拆（限流形态的退避能力保留面）——砍档门
    只在失效证据在案时旁路，不清配置不设冷却。源码钉形态：类属性
    断言受跨文件测试状态链影响（运行态脆钉），配置本体锁源码字面。"""
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "qunar.py"), encoding="utf-8").read()
    assert "_BACKOFF_S = (90, 180, 300)" in mod


def test_intl_login_reject_no_cooldown_sleep():
    """intl 1999 硬拒不设 30min 冷却（r339 观测轮 2 定谳：cooldown
    sleep 在 worker 线程内同步等 1776s=错峰等待即栅栏内泊车，每查询
    吃满 900s 路由栅栏实录 8 条/日——r330「等待不应在栅栏内」同律）。
    硬拒面由砍退避门+调度承接，源码钉锁断路器词面退场防回潮。"""
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "qunar.py"), encoding="utf-8").read()
    assert "_cooldown_until = _t.time() + 1800" not in mod
    assert "已断路 30 分钟" not in mod


# ---- merged from tests/test_r358_qunar_access.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_qunar_login_is_unified_page_not_retired_pc():
    lg = logging.getLogger("t358lg")
    assert QunarCrawler.LOGIN_URL == (
        "https://user.qunar.com/passport/login.jsp")
    assert QunarCrawler({}, lg).login_url() == QunarCrawler.LOGIN_URL
    assert "flight.qunar.com/site" not in QunarCrawler.LOGIN_URL


def test_qunar_h5_home_and_data_url_are_live_h5():
    assert QunarCrawler.H5_HOME == "https://touch.qunar.com/h5/flight/"
    assert "m.flight.qunar.com/ncs/page/flightlist" in QunarCrawler.URL_TPL
    assert "flight.qunar.com/site" not in QunarCrawler.URL_TPL


def test_qunar_fetch_order_h5_before_pc_revival_probe():
    src = inspect.getsource(QunarCrawler._fetch_one)
    i_h5 = src.find("_fetch_via_browser")
    i_pc = src.find("_fetch_via_pc")
    i_http = src.find("_fetch_via_httpx")
    assert 0 <= i_h5 < i_pc < i_http, src


def test_qunar_skips_retired_pc_probe_by_default(monkeypatch):
    """H5 未命中时不得默认去等 PC 复活（3 采样 × 等待≈72s/日期）；
    PC 探测保留为显式开关，供人工一次性复核。"""
    q = QunarCrawler({}, logging.getLogger("t358pc"))
    assert QunarCrawler.PC_PROBE_ON_MISS is False
    calls = []
    monkeypatch.setattr(q, "_fetch_via_browser", lambda *a: None)
    monkeypatch.setattr(q, "_fetch_via_pc",
                        lambda *a: calls.append("pc"))
    monkeypatch.setattr(q, "_fetch_via_httpx", lambda *a: None)
    assert q._fetch_one("SHA", "HAK", "2027-01-29") is None
    assert calls == []


def test_webui_source_access_board_and_login_note():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    for needle in (
        "来源接入",
        "SOURCE ACCESS",
        "PC 网页已于 2026-10-10 停服",
        "H5 机票查询服务已停服",
        "去哪儿网页版 PC/H5 机票查询均已停服",
        "数据由去哪儿 App 真机采集",
        "scQState",
        "srcAccessState",
        "qunar:'必须'",
        # r608：登录页头部统一为「都必须登录」；旧句
        # 「携程、去哪儿必须登录 · 同程/途牛建议」与 r414 政策冲突，已删。
        # r644 补了智行 App、r650 改写为「五个浏览器渠道 + 智行 App 都必须
        # 登录」——这里只钉政策词，不钉数量。
        "都必须登录（入口页可匿名浏览",
        "携程/去哪儿需本机已建立登录态",
        "channelAuthView(p)",
    ):
        assert needle in src, needle
    assert "flight.qunar.com/site/oneway_list.htm" not in src
    # r996：停服说明只留在来源接入板/该渠道行；登录卡不再重复整段
    # （用户点名「非常冗余和突兀的去哪儿停服说明」）。
    login_block = src[src.index('id="sec-login"'):src.index('id="sec-chlinks"')]
    assert "去哪儿网页版已于" not in login_block
    assert "停服" not in login_block


# ---- merged from tests/test_r400_qunar_blanket_gate.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    """普通无名空（认证在线）仍退避重试一次（别把修复做过头）。

    无认证 Cookie 的空结果是另一条路：r817 起直接按需登录处理，
    不再白打一次请求（见 test_r817_...::test_no_auth_cookie_prompts_login）。
    """
    c = _c()
    QunarCrawler.login_suspect = False
    QunarCrawler._cooldown_until = 0.0
    c._MIN_GAP_S = 0
    c._read_session_state = lambda: {
        "cookies": [{"name": "_q", "value": "user", "expires": -1}]}
    c._probe_session_alive = lambda: True
    calls = {"n": 0}

    def _inner(fc, tc, dates):
        calls["n"] += 1
        return []

    c._fetch_inner = _inner
    c._BACKOFF_S = (0,)
    try:
        c.fetch("SHA", "HAK", ["2026-11-16"])
        assert calls["n"] >= 2, "普通空结果应至少重试一次，实际 %d" % calls["n"]
    finally:
        QunarCrawler.login_suspect = False
        QunarCrawler._cooldown_until = 0.0


# ---- merged from tests/test_r805as_qunar_city_retap.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEP = "com.Qunar:id/atom_flight_tv_dep_city"


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """这些用例只用替身设备，等帧一律不真等（否则一条要 14 秒）。"""
    import crawlers.app_qunar as mq
    monkeypatch.setattr(mq, "_sleep", lambda s: None)
    monkeypatch.setattr(mq.time, "sleep", lambda s: None)
    # 重拍按时间间隔判（首页有动图，不能比整页快照）；用例里把间隔压到 0
    monkeypatch.setattr(mq, "_CITY_RETAP_GAP_S", 0.0)


def _n(rid, text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="%s" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, rid, x1, y1, x2, y2))


def _home(city):
    return ('<hierarchy>'
            + _n(DEP, city, 60, 320, 300, 380)
            + _n("", "搜索", 60, 900, 700, 980)
            + '</hierarchy>')


class Dev:
    """替身：第 N 次点城市位时把城市「设成」目标（模拟城市页选中后回首页）。"""

    def __init__(self, ok_on_tap=None):
        self.taps = []
        self.ok_on_tap = ok_on_tap      # None = 点了也没成
        self.city = "北京"
        self.dep_taps = 0

    def dump(self):
        return _home(self.city)

    def tap(self, x, y):
        self.taps.append((x, y))
        if 320 <= y <= 380:
            self.dep_taps += 1
            if self.ok_on_tap is not None and self.dep_taps >= self.ok_on_tap:
                self.city = "上海"
        return True

    def input_text(self, s):
        return True

    def keyevent(self, k):
        return True


def _crawler():
    from crawlers.app_qunar import AppQunarCrawler
    return AppQunarCrawler.__new__(AppQunarCrawler)   # 不需要配置/日志


def test_retaps_when_first_tap_did_not_register():
    """第一次点不中、第二次点中 → 必须重试并成功。"""
    dev = Dev(ok_on_tap=2)
    assert _crawler()._set_city(dev, _home("北京"), "上海", side="dep") is True
    assert dev.city == "上海", "城市没真的设成上海"
    assert dev.dep_taps == 2, (
        "城市位被点了 %d 次；首次点不中时必须重试一次" % dev.dep_taps)


def test_fails_fast_instead_of_spinning_to_deadline():
    """永远点不开 → 重试 3 次后立刻失败，不许空转到 30 秒。"""
    dev = Dev(ok_on_tap=None)
    assert _crawler()._set_city(dev, _home("北京"), "上海", side="dep") is False
    assert dev.dep_taps == 3, (
        "应为「首次 + 2 次重试」共 3 次，实际 %d 次" % dev.dep_taps)


def test_returns_true_when_city_already_target():
    """首页城市已是目标时直接成功，不点也不等。"""
    dev = Dev(ok_on_tap=1)
    assert _crawler()._set_city(dev, _home("上海"), "上海", side="dep") is True
    assert not dev.taps, "已经是目标城市却还去点：%s" % dev.taps


def test_accepts_airport_suffix_text():
    """城市位显示「上海虹桥」也该算已设成上海（不是只有精确相等）。"""
    dev = Dev(ok_on_tap=1)
    xml = ('<hierarchy>' + _n(DEP, "上海虹桥", 60, 320, 300, 380)
           + '</hierarchy>')
    assert _crawler()._set_city(dev, xml, "上海", side="dep") is True
    assert not dev.taps, "带机场后缀时被当成「没设成」又去点了：%s" % dev.taps


def test_failure_writes_a_screen_snapshot(tmp_path, monkeypatch):
    """失败时必须有「现场」：账本只写 set-city-dep，看不出卡在哪一屏。

    重试上线后生产仍有 `set-city-dep`（2026-11-01 17:31 SHA→BKK）。没有
    现场快照就只能继续猜「是不是又点空了」——这里把失败当刻的屏幕节点
    落盘，下一次失败可直接看到当时首页上有什么。
    """
    import crawlers.app_qunar as m

    _tick = itertools.count(1)

    class _T:
        @staticmethod
        def sleep(_s):
            return None

        @staticmethod
        def time():
            # 必须**递增**：新实现点完会轮询 6 秒等城市页，时间冻结就永远出不来
            return float(next(_tick))

        strftime = staticmethod(lambda fmt: "20261101_000000")

    monkeypatch.setattr(m, "time", _T)
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path / "scene"))
    dev = Dev(ok_on_tap=None)
    assert m.AppQunarCrawler.__new__(m.AppQunarCrawler)._set_city(
        dev, _home("北京"), "上海", side="dep") is False
    got = sorted((tmp_path / "scene").glob("qunar_app_*_setcity-dep.txt"))
    assert got, "失败时没有落现场快照，事后无从定位"
    body = got[0].read_text(encoding="utf-8")
    assert "北京" in body and "搜索" in body, (
        "现场快照缺屏幕关键文案：%r" % body[:160])


class BrokenHomeDev(Dev):
    """首页「形似而神不似」：日期行/搜索都在，城市控件却没有 id。

    现场实证（debug/scene/qunar_app_20261101_181820_setcity-noid-arr.txt）：
    这一屏的城市行只剩 content-desc、resource-id 整片退化成 "arg"，顶部还
    挂着上一轮的路由头——`_is_flight_home` 照样判「就是首页」，退栈救不回。
    """

    def __init__(self, recover=True):
        super().__init__(ok_on_tap=None)
        self.phase = 0
        self.stopped = 0
        self.started = 0
        self.recover = recover

    def dump(self):
        if self.phase == 0 or not self.recover:
            return ('<hierarchy>'
                    '<node text="2月14日" bounds="[60,500][300,560]" />'
                    '<node text="机票查询" bounds="[42,724][858,799]" />'
                    '</hierarchy>')
        return _home("上海")

    def app_stop(self, pkg):
        self.stopped += 1

    def app_start(self, pkg):
        self.started += 1
        self.phase = 1

    def deep_link(self, uri):
        return True


def test_broken_home_triggers_one_hard_reset(monkeypatch):
    """残缺首页 → 杀进程重建一次，重建后能认城市位就算成功。"""
    import crawlers.app_qunar as m
    monkeypatch.setattr(m, "_sleep", lambda s: None)
    dev = BrokenHomeDev(recover=True)
    c = m.AppQunarCrawler.__new__(m.AppQunarCrawler)
    c._home_hard_reset = False          # fetch() 每轮会这样置位
    assert c._set_city(dev, dev.dump(), "上海", side="dep") is True
    assert (dev.stopped, dev.started) == (1, 1), (
        "残缺首页应重启一次（实际 stop=%d start=%d）" % (dev.stopped, dev.started))


def test_hard_reset_happens_at_most_once_per_round(monkeypatch):
    """重建后仍认不到 → 直接失败，不许每步都重启 App。"""
    import crawlers.app_qunar as m
    monkeypatch.setattr(m, "_sleep", lambda s: None)
    dev = BrokenHomeDev(recover=False)
    c = m.AppQunarCrawler.__new__(m.AppQunarCrawler)
    c._home_hard_reset = False
    assert c._set_city(dev, dev.dump(), "上海", side="dep") is False
    assert dev.stopped == 1, "同一轮内被重启了 %d 次" % dev.stopped
    assert c._set_city(dev, dev.dump(), "上海", side="arr") is False
    assert dev.stopped == 1, "第二次进入又重启了 App"


class SlowCityDev(Dev):
    """点城市位后先是转场帧，之后才出现城市页（横屏实测 >2s）。

    旧逻辑第二拍会落到**已打开的城市页**列表上（现场 2026-11-01 18:30
    的 1600×900 横屏就是这样把状态搅乱、最后停在首页记 set-city-dep）。
    """

    def __init__(self):
        super().__init__(ok_on_tap=None)
        self.phase = "home"
        self.frames = 0
        self.mis_taps = 0       # 落到城市页上的点击次数（旧逻辑会 >0）

    def dump(self):
        if self.phase == "transition":
            self.frames += 1
            if self.frames >= 2:
                self.phase = "city"
        if self.phase == "home":
            return _home(self.city)
        if self.phase == "city":
            return ('<hierarchy>'
                    + _n("com.Qunar:id/city_suggest_view", "", 0, 0, 4, 4)
                    + _n("", "上海（不限机场）", 60, 600, 700, 660)
                    + '</hierarchy>')
        return '<hierarchy><node text="加载中" bounds="[0,0][10,10]" /></hierarchy>'

    def tap(self, x, y):
        if self.phase == "city":
            if 600 <= y <= 660:
                self.city = "上海"
                self.phase = "home"
            else:
                self.mis_taps += 1
            return True
        if self.phase == "home":
            self.phase = "transition"
        return True


def test_waits_for_transition_instead_of_retapping_into_city_page():
    dev = SlowCityDev()
    c = _crawler()
    assert c._set_city(dev, _home("北京"), "上海", side="dep") is True
    assert dev.mis_taps == 0, (
        "城市页已经打开还继续点（%d 次），会点到列表/返回把状态搅乱"
        % dev.mis_taps)


def test_pick_date_failure_also_saves_scene():
    """选日失败（第二大超时来源）同样要留现场。"""
    import io
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "crawlers", "app_qunar.py")
    src = io.open(p, encoding="utf-8").read()
    for tag in ('_save_fail_scene("pickdate-open"',
                '_save_fail_scene("pickdate-cell"'):
        assert tag in src, "选日失败没有落现场快照：%s" % tag

class EmptyFrameDev(Dev):
    """选完出发城市后先给几帧空页（转场），再看得到首页。"""

    def __init__(self):
        super().__init__(ok_on_tap=None)
        self.empty = 0
        self.city = "上海"      # 出发城市已设好；这里测到达城市

    def dump(self):
        if self.empty < 2:
            self.empty += 1
            return ""
        return ('<hierarchy>'
                + _n("com.Qunar:id/atom_flight_tv_arr_city", "曼谷",
                     700, 330, 852, 389)
                + '</hierarchy>')


def test_empty_frame_after_city_pick_is_waited_not_failed():
    dev = EmptyFrameDev()
    c = _crawler()
    assert c._set_city(dev, "", "曼谷", side="arr") is True, (
        "选完出发城市后的空帧被当成「没有城市控件」，整轮 set-city-arr")

def test_ineffective_tap_saves_a_screenshot(tmp_path, monkeypatch):
    """「点了没反应」时要留一张屏（浮层/输入法不进无障碍树，视图树看不出来）。"""
    png = bytes([137]) + b"PNG-fake"

    class ShotDev(Dev):
        def __init__(self):
            super().__init__(ok_on_tap=None)
            self.shots = 0

        def screencap(self):
            self.shots += 1
            return png

    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path / "scene"))
    dev = ShotDev()
    assert _crawler()._set_city(dev, _home("北京"), "上海", side="dep") is False
    got = list((tmp_path / "scene").glob("qunar_app_*tap1-dep.png"))
    assert got, "第一次点不动时没有留屏幕截图"
    assert got[0].read_bytes() == png
    assert dev.shots, "screencap 没被调用"

class HiddenMarkDev(Dev):
    """首页视图树里就带隐藏的 city_suggest_view（预加载）——只看 id 会把首页判成城市页。"""

    def __init__(self):
        super().__init__(ok_on_tap=None)
        self.phase = "home"
        self.dep_taps = 0

    def dump(self):
        if self.phase == "home":
            return (_home(self.city).replace(
                        "</hierarchy>",
                        _n("com.Qunar:id/city_suggest_view", "", 0, 0, 2, 2)
                        + "</hierarchy>"))
        return ('<hierarchy>'
                + _n("com.Qunar:id/city_suggest_view", "", 0, 0, 4, 4)
                + _n("", "上海（不限机场）", 60, 600, 700, 660)
                + '</hierarchy>')

    def tap(self, x, y):
        if self.phase == "city":
            if 600 <= y <= 660:
                self.city = "上海"
                self.phase = "home"
            return True
        self.dep_taps += 1
        if self.dep_taps >= 2:
            self.phase = "city"
        return True


def test_hidden_city_mark_on_home_does_not_block_retap():
    """首页自带隐藏 city_suggest_view 时，也必须能识别「城市页没开」并重拍。"""
    dev = HiddenMarkDev()
    assert _crawler()._set_city(dev, dev.dump(), "上海", side="dep") is True
    assert dev.dep_taps == 2, (
        "首页的隐藏 mark 把「没打开」判成了「已打开」，没有重拍（实际 %d 次）"
        % dev.dep_taps)

def test_login_wall_is_reported_as_login_not_set_city():
    """会话过期时首页被登录页顶掉：必须记 login，不能记 set-city-dep。

    现场实证（2026-11-01 21:28）：快照恢复已报「快照已失效（仍停在登录墙）」，
    账本却仍记 set-city-dep——把「该去重登」误导成「选择器坏了」。
    """
    wall = ('<hierarchy><node text="请输入手机号" bounds="[0,0][100,40]" />'
            '<node text="获取验证码" bounds="[0,60][100,90]" /></hierarchy>')
    dev = Dev(ok_on_tap=None)
    c = _crawler()
    c.paths = []
    c.login_suspect = False

    def _note(kind, status="", **kw):
        c.paths.append({"path": kind, "status": status})

    c.path_note = _note
    assert c._set_city(dev, wall, "上海", side="dep") is False
    assert c.login_suspect is True, "登录墙没被识别成登录态"
    assert any(p["path"] == "app-login" and p["status"] == "login"
               for p in c.paths), "没有记 app-login/login"
    assert not dev.taps, "登录墙上还去点城市位"


CITY_MARK = "com.Qunar:id/city_suggest_view"
DEALS_ROWS = [_n("", "国内", 106, 327, 146, 355),
              _n("", "国际", 268, 327, 308, 355),
              _n("", "往返", 430, 327, 470, 355)]


def _city_page(search_expanded=False, extra_rows=()):
    """城市页替身：停在国际档，目标城市只在搜索框里能选到。"""
    rows = [
        '<node text="" resource-id="%s" class="android.widget.FrameLayout"'
        ' bounds="[0,0][900,1600]" />' % CITY_MARK,
        # 页面最顶部整条（收起态的 qd_placeholder_v）：点它的中心等于点返回
        '<node text="" resource-id="com.Qunar:id/qd_placeholder_v"'
        ' class="android.widget.FrameLayout" bounds="[0,0][900,110]" />',
        _n("", "国内/港澳台", 40, 240, 300, 280),
        _n("", "国际", 600, 240, 700, 280),
        _n("", "热门城市", 20, 400, 400, 430),
        _n("", "东京", 40, 440, 120, 480),
    ]
    rows.extend(extra_rows)
    if search_expanded:
        rows.append('<node class="android.widget.EditText"'
                    ' bounds="[40,150][860,200]" />')
    rows.append(_n("", "搜索国家/城市/景点等", 40, 150, 860, 200))
    return "<hierarchy>" + "".join(rows) + "</hierarchy>"


class SearchDev:
    """替身：城市页停在国际档；「伦敦」只能经搜索框选中。

    `landing` 控制点中搜索结果后落在哪：home（正常）/ deals（特价页，
    实测 22:08 的失败现场）。
    """

    def __init__(self, landing="home"):
        self.city = "北京"
        self.page = "home"
        self.expanded = False
        self.tab_taps = []
        self.typed = ""
        self.landing = landing
        self.taps = []

    def dump(self):
        if self.page == "home":
            return _home(self.city)
        if self.page == "deals":
            return ("<hierarchy>"
                    + '<node text="" resource-id="%s"'
                    ' class="android.widget.FrameLayout"'
                    ' bounds="[0,0][900,1600]" />' % CITY_MARK
                    + "".join(DEALS_ROWS) + "</hierarchy>")
        rows = []
        if self.expanded:
            rows.append(_n("", "伦敦（不限机场）", 60, 520, 700, 560))
        return _city_page(self.expanded, rows)

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.page == "home":
            if 320 <= y <= 380:
                self.page = "city"
            return True
        if self.page != "city":
            return True
        if 240 <= y <= 280:                  # 档位行：不该被点
            self.tab_taps.append(x)
            return True
        if 150 <= y <= 200:                  # 搜索占位行/输入框
            self.expanded = True
            return True
        if 520 <= y <= 560:                  # 搜索结果
            self.page = self.landing
            if self.landing == "home":
                self.city = "伦敦"
        return True

    def input_text(self, s):
        self.typed = s
        return True

    def keyevent(self, k):
        return True


def test_intl_city_is_selected_through_search_without_touching_tabs():
    """国际城市走搜索框；**不点「国内/国际」档位**。

    真机探针（2026-11-01 22:22，空载 dump≈2.2s）：点搜索占位行 → 输入
    「伦敦」→ 点「伦敦（不限机场）」→ 回首页且到达城市位变伦敦，全程 43s，
    不需要碰档位按钮。
    """
    dev = SearchDev()
    assert _crawler()._set_city(dev, _home("北京"), "伦敦", side="dep") is True
    assert dev.city == "伦敦"
    assert dev.typed == "伦敦", "没走搜索框"
    assert not dev.tab_taps, "又去点「国内/国际」档位了：%s" % dev.tab_taps


def test_leaving_city_to_the_deals_page_is_not_success():
    """点城市行落到特价页 ≠ 选上了：城市没变必须判失败。

    实测 22:08 的失败现场就是特价页（国内/国际/往返 页签 + 搜索）——原实现
    只要「离开了城市页」就返回 True，会把旧城市当成功，整轮搜错航线。
    """
    dev = SearchDev(landing="deals")
    assert _crawler()._set_city(dev, _home("北京"), "伦敦", side="dep") is False
    assert dev.city == "北京"


def test_city_page_judgement_requires_city_page_controls():
    """特价页也预加载 city_suggest_view：城市页判据必须要求自己的控件在场。

    它没有搜索占位行/输入框/热门城市/历史选择——只靠「有 mark 且没有
    城市位」会把它当城市页，然后在里面找城市行白等到超时（22:08 现场）。
    """
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "_find_search_placeholder(page) is not None" in src
    assert "_find_text(page, _CITY_HISTORY_MARK) is not None" in src


def test_set_city_no_longer_switches_city_tabs():
    """回归门禁：档位切换已删除——点它会把整页换掉，而搜索在任何档位都能用。"""
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "want_tab" not in src, "又在城市页切档了"
    assert '_find_text(page, "国际")' not in src, "又在按文案找「国际」档位"
    assert "_find_text(page, want_tab)" not in src


def test_search_expand_taps_the_placeholder_row_not_the_top_strip():
    """展开搜索要点**搜索行**（`qd_placeholder`），不能点 `qd_placeholder_v`。

    `qd_placeholder_v` 是页面最顶部整条（实测 bounds 0,0,1600,110）——
    点它中心等于点返回/状态栏。22:28 真机轨迹 `city,home,city,home,city`
    就是每次展开都把自己点回首页；探针里点搜索行（190,209）则一次成功。
    """
    dev = SearchDev()
    assert _crawler()._set_city(dev, _home("北京"), "伦敦", side="dep") is True
    assert dev.taps, "一次都没点"
    top = [t for t in dev.taps if t[1] <= 120]
    assert not top, "点到了页面顶部整条（等于点返回）：%s" % top


# ---- merged from tests/test_r815a_qunar_native_calendar_lowfare.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def test_matrix_marks_qunar_app_calendar_and_low_fare_as_verified():
    dims = CHANNEL_DIMENSIONS["app_qunar"]
    assert dims["calendar"] == "y", dims
    assert dims["low_fare"] == "y", dims
    # 2026-11-03：ctrip PC 多程 2 段升 y 后，App 端仅剩 multi_city 缺口。
    assert app_alignment_gaps("app_qunar") == ("multi_city",), \
        app_alignment_gaps("app_qunar")


def test_full_calendar_parses_day_cell_subtrees():
    """整月日格：date 在 content-desc，价格在子树，不依赖坏掉的 bounds。"""
    from crawlers.app_qunar_lowfare import parse_full_calendar
    xml = (
        '<hierarchy>'
        '<node content-desc="q_flight_calendarDayItem#2026-11-10">'
        '<node text="¥498"/><node text="10"/></node>'
        '<node content-desc="q_flight_calendarDayItem#2026-11-11">'
        '<node text="¥500"/><node text="11"/></node>'
        '<node content-desc="q_flight_calendarDayItem#2026-11-12">'
        '<node text="12"/></node>'   # 无价：跳过，不给 0
        '</hierarchy>')
    rows = parse_full_calendar(xml)
    assert rows == [{"date": "2026-11-10", "price": 498},
                    {"date": "2026-11-11", "price": 500}], rows


def test_notes_carry_the_native_page_evidence():
    low = DIMENSION_NOTES[("app_qunar", "low_fare")]
    cal = DIMENSION_NOTES[("app_qunar", "calendar")]
    assert "QReactNativeActivity1" in low, low
    assert "14 天" in low and "¥408" in low, low
    assert "日历" in cal and "整月" in cal, cal
    assert "2026-12" in cal and "60 天" in cal, cal


def test_radar_source_is_restored():
    entry = SPECIAL_CAPABILITY["app_qunar"]
    assert entry.get("sources") == ["app_qunar"], entry
    assert "低价" in entry.get("note", ""), entry


def test_low_fare_writes_a_separate_calendar_path():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.index("def _low_fare_locked(")
    body = src[i:src.index("def _hard_reset_home(", i)]
    assert '"日历", "calendar"' in body, (
        "low_fare 成功后没有写独立日历证据，calendar=y 会失去账本支撑")
    assert "parse_full_calendar" in body, (
        "日历证据不是整月解析，而是日期带冒充？")
    assert 'path_note("low-fare", "ok"' in body, body[:200]
    assert "is_h5_low_fare_activity" in body, (
        "H5 WebView 异常转场兜底被删：遇到 H5 会误记 timeout")


def test_terminal_legend_distinguishes_product_from_collection():
    src = webui_full_src()
    assert "已实现 · 当前风控/设备/IP/账号受限" in src, (
        "矩阵图例没有区分「已实现但当前受限」与「采集端未实现」")
    assert "采集端未实现" in src and "渠道停服" in src, src[:200]


# ---- merged from tests/test_r928_qunar_city_tab.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. 国际/国内判定
# ---------------------------------------------------------------------------
def test_domestic_cities_are_not_intl():
    for c in ("海口", "上海", "北京", "成都"):
        assert q._looks_intl_city(c) is False, c


def test_foreign_cities_are_intl():
    for c in ("伦敦", "东京", "曼谷", "新加坡"):
        assert q._looks_intl_city(c) is True, c


def test_airport_code_normalized():
    """机场码要先归一成城市再判（NRT/PEK 这类）。"""
    assert q._looks_intl_city("NRT") is True          # 成田 = 国际
    assert q._looks_intl_city("PEK") is False         # 首都 = 国内


def test_empty_city_is_not_intl():
    assert q._looks_intl_city("") is False
    assert q._looks_intl_city(None) is False


# ---------------------------------------------------------------------------
# 2. 档位按钮查找
# ---------------------------------------------------------------------------
_TABS = ('<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
         'text="国内/港澳台" bounds="[180,257][310,292]" />'
         '<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
         'text="国际" bounds="[671,257][719,292]" />')


def test_find_city_tab():
    assert q._find_city_tab(_TABS, "国内") is not None
    assert q._find_city_tab(_TABS, "国际") is not None
    assert q._find_city_tab(_TABS, "欧洲") is None
    assert q._find_city_tab("", "国内") is None


# ---------------------------------------------------------------------------
# 3. 选中态（两种表达都要认）
# ---------------------------------------------------------------------------
def test_tab_selected_by_attribute():
    xml = ('<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
           'text="国内/港澳台" selected="true" bounds="[180,257][310,292]" />'
           + _TABS)
    assert q._tab_is_selected(xml, "国内") is True
    assert q._tab_is_selected(xml, "国际") is False


def test_tab_selected_by_underline():
    """真机上 `_nodes()` 会丢掉 selected 属性，只剩下划线可判。"""
    xml = (_TABS + '<node resource-id="com.Qunar:id/atom_flight_tab_item_line" '
           'bounds="[677,296][713,301]" />')
    assert q._tab_is_selected(xml, "国际") is True
    assert q._tab_is_selected(xml, "国内") is False


def test_tab_selected_false_when_no_marker():
    assert q._tab_is_selected(_TABS, "国内") is False
    assert q._tab_is_selected("", "国内") is False


# ---------------------------------------------------------------------------
# 4. 自愈逻辑存在且只做一次（源码钉）
# ---------------------------------------------------------------------------
def test_self_heal_is_conditional_and_once():
    """必须是"有条件 + 只一次"，不能退回无条件点档位（那已被证有害）。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    # 条件：输入过但没结果
    assert "hit is None and typed and not _tab_tried" in src
    # 只做一次
    assert "_tab_tried = False" in src
    assert "_tab_tried = True" in src
    # 切完允许重新输入
    assert "typed = False" in src


# ---------------------------------------------------------------------------
# 5. **真实失败现场**回归（debug/scene/qunar_app_*_setcity-timeout-arr.txt）
# ---------------------------------------------------------------------------
_REAL_SCENE = (
    '<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
    'text="国内/港澳台" bounds="[180,257][310,292]" />'
    '<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
    'text="国际" bounds="[671,257][719,292]" />'
    '<node resource-id="com.Qunar:id/atom_flight_tab_item_line" '
    'bounds="[677,296][713,301]" />'
    '<node resource-id="com.Qunar:id/qd_city_rlTab2" '
    'bounds="[0,310][900,1600]" />'
)


def test_real_scene_was_on_intl_tab():
    """2026-11-02 19:02 真实现场：下划线在「国际」下 → 当时停在国际档。

    而那一轮要选的是「海口」（国内城市）——所以必然超时。
    这条用例就是事故现场本身，防止判据以后再漂。
    """
    assert q._tab_is_selected(_REAL_SCENE, "国际") is True
    assert q._tab_is_selected(_REAL_SCENE, "国内") is False
    assert q._looks_intl_city("海口") is False     # 目标是国内城市
    # → 修复动作：切到国内档
    assert q._find_city_tab(_REAL_SCENE, "国内") is not None


def test_real_scene_domestic_target_mismatch():
    """判定组合：目标国内 + 当前国际 → 必须触发一次切档。"""
    want = q._TAB_INTL if q._looks_intl_city("海口") else q._TAB_DOMESTIC
    assert want == q._TAB_DOMESTIC
    assert q._tab_is_selected(_REAL_SCENE, want) is False   # 不在目标档 → 要切


# ---- merged from tests/test_r933_qunar_flight_no.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _card(dep, price, y, arr="18:55", desc_round=None, code_text=""):
    """一张卡片：时刻 + 到达 + 价格（+ 可选的中转航班号 desc 节点）。"""
    parts = [
        '<node text="%s" content-desc="flight_search_rn|'
        'QunarFlightInterRoundMixList|ItemDepTime" '
        'bounds="[18,%d][80,%d]" />' % (dep, y, y + 33),
        '<node text="%s" content-desc="flight_search_rn|'
        'QunarFlightInterRoundMixList|ItemArrTime" '
        'bounds="[301,%d][366,%d]" />' % (arr, y, y + 33),
        '<node text="%s" content-desc="flight_search_rn|'
        'QunarFlightInterRoundMixList|ItemPrice" '
        'bounds="[662,%d][723,%d]" />' % (price, y, y + 33),
    ]
    if code_text:
        parts.append('<node text="%s" bounds="[36,%d][104,%d]" />'
                     % (code_text, y + 74, y + 97))
    if desc_round:
        parts.append('<node text="" content-desc="flight_search_rn|'
                     'QunarFlightInterList|FlightsRound_%s" '
                     'bounds="[0,%d][741,%d]" />' % (desc_round, y + 85,
                                                     y + 130))
    return "".join(parts)


# ---------------------------------------------------------------------------
# 1. desc 航班号提取
# ---------------------------------------------------------------------------
def test_desc_marks_direct_single_leg():
    xml = _card("15:40", "¥5031", 366, desc_round="MU3686|SHA-BKK|2026-11-16")
    marks = _desc_flight_marks(xml)
    assert len(marks) == 1
    assert marks[0][0] == "MU3686"


def test_desc_marks_transfer_two_legs_joined():
    """真中转：两段用 `+` 连起来，单程号会含糊"这到底是哪班"。"""
    xml = _card("20:55", "¥5711", 366,
                desc_round="OD617|PVG-KUL|2026-11-16/OD528|KUL-DMK|2026-11-16")
    marks = _desc_flight_marks(xml)
    assert marks and marks[0][0] == "OD617+OD528", marks


def test_desc_marks_ignores_non_flight_desc():
    xml = ('<node text="¥5711" content-desc="flight_search_rn'
           '|QunarFlightInterRoundMixList|ItemPrice" '
           'bounds="[662,366][723,399]" />')
    assert _desc_flight_marks(xml) == []


# ---------------------------------------------------------------------------
# 2. 纯数字不能当航班号（核心 bug）
# ---------------------------------------------------------------------------
def test_numeric_price_is_not_flight_no():
    """`11022` 是价格，不是「航班 11+022」。"""
    xml = _card("15:30", "¥11022", 366)
    rows = parse_flight_rows(xml)
    assert len(rows) == 1
    assert rows[0]["flight_no"] == "", rows[0]
    assert rows[0]["price"] == 11022


def test_real_airline_codes_still_work():
    """`3U8889` / `9C7293` 这类"数字开头"的真实航司码不能被误伤。"""
    for code in ("3U8889", "9C7293", "HO1234", "CZ8757"):
        xml = _card("08:00", "¥680", 366, code_text="川航" + code)
        rows = parse_flight_rows(xml)
        assert rows and rows[0]["flight_no"] == code, (code, rows)


# ---------------------------------------------------------------------------
# 3. 卡片内 code 为空时用 desc 兜底
# ---------------------------------------------------------------------------
def test_transfer_row_gets_code_from_desc():
    xml = _card("20:55", "¥5711", 366,
                desc_round="OD617|PVG-KUL|2026-11-16/OD528|KUL-DMK|2026-11-16")
    rows = parse_flight_rows(xml)
    assert len(rows) == 1
    assert rows[0]["flight_no"] == "OD617+OD528", rows


def test_text_code_wins_over_desc():
    """text 里有航班号时优先用它（desc 只是兜底）。"""
    xml = _card("15:40", "¥5031", 366, code_text="东航MU3686",
                desc_round="MU3686|SHA-BKK|2026-11-16")
    rows = parse_flight_rows(xml)
    assert rows[0]["flight_no"] == "MU3686"


# ---------------------------------------------------------------------------
# 4. 真实现场回归：7 行全部有航司码，且都不是纯数字
# ---------------------------------------------------------------------------
def test_real_scene_all_rows_have_airline_code():
    """2026-11-04 10:49 真实 SHA→HAK 现场：7 行，每行都有航司码。

    修前：`flight_no` 全空，甚至有一行是 `11022`（价格被当航班号）。
    """
    codes = ["MU3686", "MU3748", "CZ8757", "CZ3516", "CZ6686", "CZ6766",
             "CA8573"]
    prices = ["¥5031", "¥5031", "¥6591", "¥6591", "¥6591", "¥6591", "¥11022"]
    xml = "".join(
        _card("%02d:00" % (6 + i), p, 366 + i * 139,
              desc_round="%s|SHA-BKK|2026-11-16" % c)
        for i, (c, p) in enumerate(zip(codes, prices)))
    rows = parse_flight_rows(xml)
    assert len(rows) == 7
    got = [r["flight_no"] for r in rows]
    assert got == codes, got
    # 一行都不许是纯数字
    for c in got:
        assert not c.isdigit(), c


@pytest.mark.parametrize("bad", ["11022", "4999", "5711"])
def test_pure_digits_never_match(bad):
    from crawlers.app_qunar_parse import _FLIGHT_RE
    assert _FLIGHT_RE.search(bad) is None, bad
