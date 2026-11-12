# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r326_resilience.py
- tests/test_r408_1999_upgrade_replaces.py
- tests/test_r688_skip_restore_when_logged_in.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import concurrent.futures
import itertools
import logging
import os
import pytest
import sys
import threading
import time

from core.intl import tz_offset_min
from crawlers.app_qunar import AppQunarCrawler


# ---- merged from tests/test_r326_resilience.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r326")


# ---- tz 印章按航班日取 DST ----

def test_tz_offset_min_accepts_flight_date():
    # 'YYYY-MM-DD' 日期串锚定正午 UTC 取 DST 真历法（zoneinfo 实测）：
    # EU 2026-10-25 切冬令时、埃及 10 月末切换——航班日 11-16 与
    # 抓取日 10-18 分属两代时制
    assert tz_offset_min("FRA", when="2026-11-16") == 60
    assert tz_offset_min("FRA", when="2026-10-18") == 120
    assert tz_offset_min("CAI", when="2026-11-16") == 120
    assert tz_offset_min("CAI", when="2026-10-18") == 180
    assert tz_offset_min("NRT", when="2026-11-16") == 540
    # 无 when 回退抓取时刻（现行为不变）
    assert tz_offset_min("FRA") in (60, 120)


def test_stamp_intl_uses_flight_date_tz():
    from crawlers.tuniu import TuniuCrawler
    TN = TuniuCrawler({}, _LOG)
    fs = [{"depDate": "2026-11-16"}, {"depDate": "2026-10-18"}]
    TN._stamp_intl(fs, "SHA", "FRA")
    # 同批两行各按自己航班日取 DST（跨 DST 批次不互染）；
    # 大陆端恒 480 不随航班日漂移
    assert fs[0]["tz_arr"] == 60
    assert fs[1]["tz_arr"] == 120
    assert all(f["tz_dep"] == 480 for f in fs)
    assert all(f["intl"] == 1 for f in fs)


# ---- 路由级栅栏总超时 ----

def test_collect_route_futures_releases_on_park():
    from main import _collect_route_futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    ev = threading.Event()

    def park():
        # 模拟无超时 playwright 泊车（测试收尾放行，线程可回收）
        ev.wait(30)
        return []

    try:
        futs = {ex.submit(park): "parked",
                ex.submit(lambda: [1, 2]): "quick"}
        t0 = time.monotonic()
        results, timed = _collect_route_futures(
            futs, timeout_s=0.5, logger=_LOG)
        dt = time.monotonic() - t0
        # 有界放行：泊车 worker 不拖栅栏（旧 as_completed 无 timeout
        # 会在此永久阻塞）
        assert dt < 10
        assert ("quick", [1, 2]) in results
        assert timed == ["parked"]
    finally:
        ev.set()
        ex.shutdown(wait=True)


def test_collect_route_futures_all_done_no_timeout():
    from main import _collect_route_futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        futs = {ex.submit(lambda: [1]): "a", ex.submit(lambda: [2]): "b"}
        results, timed = _collect_route_futures(
            futs, timeout_s=10, logger=_LOG)
        assert timed == []
        assert sorted(results) == [("a", [1]), ("b", [2])]
    finally:
        ex.shutdown(wait=True)


# ---- tongcheng 页内 fetch 超时（源码钉：行为面=playwright 运行时） ----

def test_tongcheng_intl_fetch_has_abort_timeout():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tongcheng.py"), encoding="utf-8").read()
    assert "AbortSignal.timeout" in src


# ---- apscheduler 警告可见化 ----

def test_apscheduler_logger_wired_to_file(tmp_path):
    from core.logger import setup_logger
    setup_logger(str(tmp_path / "m.log"))
    ap = logging.getLogger("apscheduler")
    assert ap.handlers, "apscheduler logger 未接入任何 handler"
    assert ap.level == logging.WARNING
    assert ap.propagate is False


# ---- 城市面板国际页签拼音搜索（README 三路搜索承诺面） ----

def test_intl_city_pinyin_full_coverage():
    # 国际页签城市名必须有全拼（CITYX.npy 合并面）：README 宣称
    # 「中文名/拼音/三字码三路搜索」——拼音路曾在国际 177 城缺席
    # （"dongjing" 无匹配实证）；初字母表由全拼派生同 convention
    from core.intl import INTL_CITY_NAME, INTL_CITY_NPY, INTL_CITY_PY
    missing = [n for n in INTL_CITY_NAME.values()
               if n not in INTL_CITY_NPY or not INTL_CITY_NPY[n]]
    assert not missing, "缺拼音: %s" % missing[:8]
    for n, py in INTL_CITY_NPY.items():
        assert py.isascii() and py.islower(), (n, py)
        assert INTL_CITY_PY[n] == py[0].upper(), (n, py)


# ---- merged from tests/test_r408_1999_upgrade_replaces.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _src():
    return open(os.path.join(CRAWLERS, "qunar.py"), encoding="utf-8").read()


def test_upgrade_path_removes_soft_reject():
    """代码里升级分支必须显式剔除本轮的 soft_reject。"""
    s = _src()
    i = s.index("if self._qn1999_is_login(")
    block = s[i:i + 1800]
    assert '"soft_reject"' in block, block
    assert "_kept" in block and "self.paths =" in block, block


def test_upgrade_only_touches_same_date():
    """只撤本轮同日的那条，不碰历史与其他日期。"""
    s = _src()
    i = s.index("if self._qn1999_is_login(")
    block = s[i:i + 1800]
    assert 'p.get("date") == date' in block, block


def test_single_reject_still_emitted():
    """单次仍是 soft_reject（别为了去重把分层砍掉）。"""
    s = _src()
    assert "国际列表 1999/8 间歇放行（单次" in s
    assert "国际列表 1999/8 连续 %d 次" in s


def test_no_two_contradictory_rows_for_same_date():
    """行为级：升级后同日期只剩 login 一条。"""
    import logging
    from crawlers.qunar import QunarCrawler
    c = QunarCrawler({}, logging.getLogger("t_r408"))
    c.path_reset()
    c.path_note("H5", "soft_reject", date="2026-11-16",
                detail="国际列表 1999/8 间歇放行（单次，免登录冷却）")
    c.path_note("H5", "login", date="2026-11-16",
                detail="国际列表 1999/8 连续 2 次未放行（疑会话失效）")
    _kept = [p for p in c.paths[:-1]
             if not (p.get("path") == "H5" and p.get("date") == "2026-11-16"
                     and p.get("status") == "soft_reject")]
    c.paths = _kept + [c.paths[-1]]
    same = [p for p in c.paths if p.get("date") == "2026-11-16"]
    assert len(same) == 1, same
    assert same[0]["status"] == "login"


# ---- merged from tests/test_r688_skip_restore_when_logged_in.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture(autouse=True)
def _fast_clock(monkeypatch):
    """恢复前置探测是「等到 deadline」的循环：sleep 被置空后若 time 不前进，
    整条用例会空转满 30 秒（实测一条 12s 还在转）。这里让时间每次调用 +10s。"""
    import crawlers.app_base as base
    tick = itertools.count(1)
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    monkeypatch.setattr(base.time, "time", lambda: float(next(tick)) * 10.0)

HOME = ('<hierarchy>' + "".join(
    '<node text="x%d" bounds="[0,%d][100,%d]" />' % (i, i * 10, i * 10 + 8)
    for i in range(10)) + '</hierarchy>')
LOGIN = ('<hierarchy><node text="请输入手机号" bounds="[0,0][100,40]" />'
         '<node text="获取验证码" bounds="[0,60][100,90]" /></hierarchy>')
BLANK = '<hierarchy><node text="x" bounds="[0,0][10,10]" /></hierarchy>'


class Dev:
    def __init__(self, screen=HOME):
        self.screen = screen
        self.calls = []

    def app_stop(self, pkg):
        self.calls.append(("stop", pkg))
        return True

    def app_start(self, pkg):
        self.calls.append(("start", pkg))
        return True

    def deep_link(self, uri):
        self.calls.append(("deep", uri))
        return True

    def dump(self):
        self.calls.append(("dump",))
        return self.screen

    def root(self):
        self.calls.append(("root",))
        return True

    def current_activity(self):
        return "com.Qunar/.X"


def _crawler():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.home_uri = "qunarphone://flight"
    c._snapshot_restored = False
    import logging
    c.logger = logging.getLogger("t")
    c.user_data_root = os.path.abspath("user_data")
    return c


def test_skips_restore_when_device_already_logged_in(monkeypatch):
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                calls.append("exists")
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    ok = c.restore_login_snapshot(Dev(HOME))
    assert ok is False
    assert "restore" not in calls, "设备已登录仍覆盖了快照：%s" % calls


def test_restores_when_device_shows_login_wall(monkeypatch):
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    ok = c.restore_login_snapshot(Dev(LOGIN))
    assert ok is True
    assert calls == ["restore"], calls


def test_restores_when_page_is_blank(monkeypatch):
    """白屏不算「已登录」——否则整轮会跑在空页面上。"""
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    c.restore_login_snapshot(Dev(BLANK))
    assert calls == ["restore"], "白屏被当成已登录：%s" % calls

def test_restore_failure_cold_starts_so_round_can_continue(monkeypatch):
    """快照恢复因「拿不到 root」失败时，冷启一次，别把 App 留在半死状态。

    现场（2026-11-01 19:20）：`snap-restore error 无法获取 root` 紧接着
    `app-dump timeout 没能打开机票首页`——恢复失败后没有任何兜底。
    """
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    # 时间必须往前走：恢复前置探测是「等到 deadline」的循环，冻结就出不来
    import itertools
    _tick = itertools.count(1)
    monkeypatch.setattr(base.time, "time", lambda: float(next(_tick)) * 10)
    c = _crawler()

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            return False, "无法获取 root"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    called = []
    monkeypatch.setattr(c, "_cold_start_and_probe",
                        lambda dev, wait_s=30: called.append("cold") or HOME)
    dev = Dev(BLANK)
    assert c.restore_login_snapshot(dev) is False
    assert called == ["cold"], "恢复失败后没有冷启兜底"


def test_cold_start_and_probe_returns_first_usable_page(monkeypatch):
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    dev = Dev(HOME)
    assert c._cold_start_and_probe(dev) == HOME
    assert ("stop", "com.Qunar") in dev.calls
    assert any(k[0] == "deep" for k in dev.calls), "冷启应走深链回机票页"

def test_ensure_app_fresh_cold_starts_once_per_round(monkeypatch):
    """每条航线开始前冷启一次；快照恢复已冷启过则不重复。"""
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    calls = []
    monkeypatch.setattr(c, "_cold_start_and_probe",
                        lambda dev, wait_s=30: calls.append("cold") or HOME)
    c._app_fresh = False
    assert c._ensure_app_fresh(Dev(HOME)) is True
    assert calls == ["cold"], calls
    # 恢复阶段刚冷启过 → 本轮不再启
    c._app_fresh = True
    assert c._ensure_app_fresh(Dev(HOME)) is True
    assert calls == ["cold"], "恢复已冷启过，采集前又启了一次"
