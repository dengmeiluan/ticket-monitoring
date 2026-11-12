# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r319_proxy.py
- tests/test_r912_yield_tuning_and_pacing.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import crawlers.base as base_mod
import logging
import os
import sys
import threading
import time
import unittest

from contextlib import contextmanager
from core import yield_stats as ys
from core.android import emulator_tuning as tune
from crawlers.base import BaseCrawler, SessionBusyError


# ---- merged from tests/test_r319_proxy.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestProxyPlumbing(unittest.TestCase):
    def test_base_crawler_reads_proxy(self):
        import logging
        from crawlers.base import BaseCrawler
        c = BaseCrawler({"proxy": " http://127.0.0.1:7897 "},
                        logging.getLogger("t"))
        self.assertEqual(c.proxy, "http://127.0.0.1:7897")   # strip
        c2 = BaseCrawler({}, logging.getLogger("t"))
        self.assertEqual(c2.proxy, "")

    def test_browser_launch_passes_proxy(self):
        src = _src("crawlers/base.py")
        self.assertIn('proxy=({"server": fp["proxy"]} if fp["proxy"] else None)',
                      src)

    def test_special_fetchers_accept_proxy(self):
        import inspect
        from crawlers import special as sp
        for fn in (sp.fetch_tuniu_board, sp.fetch_ctrip_calendar,
                   sp.fetch_ctrip_board, sp.fetch_fliggy_board):
            self.assertIn("proxy", inspect.signature(fn).parameters, fn)

    def test_main_wires_proxy_into_discovery(self):
        src = _src("main.py")
        self.assertIn('fetch_tuniu_board(logger, proxy=_proxy)', src)
        self.assertIn('proxy=_proxy)', src)   # ctrip 日历正反向两处
        # 热重载：代理变更清爬虫实例缓存
        self.assertIn("采集代理已切换", src)

    def test_webui_globals_proxy_field(self):
        src = webui_full_src()
        self.assertIn("glbProxy", src)                       # 面板字段
        self.assertIn('_crw["proxy"] = _px', src)            # POST 落键
        self.assertIn('"proxy": str((cfg.get("crawler") or {}).get(',
                      src)                                   # GET 组装
        # 形态校验（Soldier P2#4）：漏 scheme 的手滑输入回直连——
        # httpx 对无 scheme 代理抛 InvalidURL 会让发现层全哑
        self.assertIn('not re.match(r"^https?://[^\\s/]+:\\d+$", _px)',
                      src)
        self.assertIn("采集代理须为 http://主机:端口 形态", src)
        # 发现层 trust_env 恒 False（Soldier P2#3）：系统代理环境变量
        # 一律不吃，出口只由显式 proxy 形参控制
        sp = _src("crawlers/special.py")
        self.assertNotIn("trust_env=not proxy", sp)
        self.assertEqual(sp.count("trust_env=False"), 7)   # 五源 fetcher（新增飞猪/同程/途牛日历）   # 四源 fetcher

    def test_example_config_documents_proxy(self):
        src = _src("config.example.yaml")
        self.assertIn("proxy: http://127.0.0.1:7897", src)
        self.assertIn("国内直落", src)

# ---- __main__ from tests/test_r319_proxy.py ----

if __name__ == "__main__":
    unittest.main()


# ---- merged from tests/test_r912_yield_tuning_and_pacing.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r912")


# ---------------------------------------------------------------------------
# 1. Wilson 与爬取率账本
# ---------------------------------------------------------------------------
def test_wilson_is_conservative_and_tightens_with_samples():
    lo3, _ = ys.wilson(3, 3)
    lo40, _ = ys.wilson(40, 40)
    assert 0.4 < lo3 < 0.6          # 3/3 不许被当成 100%
    assert lo40 > lo3               # 样本多了下界收紧
    assert ys.wilson(0, 0) == (0.0, 1.0)
    lo0, hi0 = ys.wilson(0, 10)
    assert lo0 == 0.0 and hi0 > 0


def test_ledger_note_and_rate(tmp_path):
    led = ys.YieldLedger(str(tmp_path / "y.json"))
    assert led.samples("ctrip") == 0
    led.note("ctrip", "pc-list", True, rows=12)
    led.note("ctrip", "h5-list", False)
    led.note("ctrip", "pc-list", True, rows=8)
    assert led.samples("ctrip") == 3
    assert abs(led.rate("ctrip") - 2 / 3) < 1e-6
    assert abs(led.rate("ctrip", "pc-list") - 1.0) < 1e-6
    rank = led.path_rank("ctrip")
    assert rank[0]["path"] == "pc-list" and rank[0]["n"] == 2


def test_ledger_persists_and_survives_bad_file(tmp_path):
    path = str(tmp_path / "y.json")
    a = ys.YieldLedger(path)
    a.note("qunar", "h5", True, rows=5, now=1000.0)
    b = ys.YieldLedger(path)
    assert b.samples("qunar") == 1 and b.rate("qunar") == 1.0
    open(path, "w", encoding="utf-8").write("{broken")
    c = ys.YieldLedger(path)
    assert c.snapshot() == {}


def test_recommend_interval_ladder(tmp_path):
    led = ys.YieldLedger(str(tmp_path / "y.json"))
    # 样本不足：按基准，不判
    for _ in range(3):
        led.note("a", "p", True, rows=1)
    assert led.recommend_interval("a", 30)["factor"] == 1.0
    # 40/40 且下界 > 0.9 → 可以更快
    led2 = ys.YieldLedger(str(tmp_path / "y2.json"))
    for _ in range(40):
        led2.note("b", "p", True, rows=1)
    r = led2.recommend_interval("b", 30)
    assert r["factor"] == 0.8 and r["minutes"] == 24
    # 8/10 → 1.5×
    led3 = ys.YieldLedger(str(tmp_path / "y3.json"))
    for i in range(10):
        led3.note("c", "p", i < 8, rows=1)
    assert led3.recommend_interval("c", 30)["factor"] == 1.5
    # 3/10 → 2.5×（先修因果链）
    led4 = ys.YieldLedger(str(tmp_path / "y4.json"))
    for i in range(10):
        led4.note("d", "p", i < 3, rows=1)
    assert led4.recommend_interval("d", 30)["factor"] == 2.5


def test_dead_hours_only_with_enough_samples(tmp_path):
    led = ys.YieldLedger(str(tmp_path / "y.json"))
    led.note("q", "p", False, now=time.mktime((2026, 11, 3, 3, 0, 0, 0, 1, -1)))
    led.note("q", "p", False, now=time.mktime((2026, 11, 3, 3, 10, 0, 0, 1, -1)))
    led.note("q", "p", False, now=time.mktime((2026, 11, 3, 3, 20, 0, 0, 1, -1)))
    led.note("q", "p", True, now=time.mktime((2026, 11, 3, 9, 0, 0, 0, 1, -1)))
    assert led.dead_hours("q") == [3]


def test_statuses_ok_requires_rows():
    ok, rows, path = ys.statuses_ok([
        {"path": "pc", "status": "ok", "rows": 0},
        {"path": "h5", "status": "login", "rows": 9},
    ])
    assert ok is False and rows == 0
    ok2, rows2, path2 = ys.statuses_ok([
        {"path": "pc", "status": "ok", "rows": 4},
        {"path": "cal", "status": "calendar", "rows": 6},
    ])
    assert ok2 is True and rows2 == 10 and path2 == "cal"


# ---------------------------------------------------------------------------
# 2. 设备调优
# ---------------------------------------------------------------------------
class FakeDev:
    def __init__(self):
        self.settings = {"window_animation_scale": "1",
                         "transition_animation_scale": "1",
                         "animator_duration_scale": "1"}
        self.marker = ""
        self.calls = []

    def _sh(self, *args, timeout=None):
        cmd = " ".join(str(a) for a in args)
        self.calls.append(cmd)
        if "boot_id" in cmd:
            return "boot-1"
        if "/data/local/tmp/tm_tuned_0.ok" in cmd and cmd.startswith("shell cat"):
            return self.marker
        if "/data/local/tmp/tm_tuned_0.ok" in cmd and cmd.startswith("shell sh"):
            # 旧形态（三段 argv `sh -c "echo X > path"`），保留兼容
            self.marker = cmd.split("echo ")[1].split(" >")[0].strip("'")
            return ""
        if "/data/local/tmp/tm_tuned_0.ok" in cmd and cmd.startswith("shell echo"):
            # **现行形态**：`write_remote` 无 push 能力时退回
            # `sh_script(dev, "echo <值> <路径>")`，整条脚本是**单个 argv**，
            # 所以命令串以 `shell echo` 开头而不是 `shell sh`。
            # （三段 argv 会被 adb 拼回去交给设备 shell 重解析而静默写空，
            #   见 §6.39；测试替身必须跟着这个契约走，否则"幂等"永远测不到。）
            self.marker = cmd.split("echo ")[1].split(" >")[0].strip("'")
            return ""
        if cmd.startswith("shell settings get"):
            parts = cmd.split()
            return self.settings.get(parts[-1], "0")
        if cmd.startswith("shell settings put"):
            parts = cmd.split()
            self.settings[parts[-2]] = parts[-1]
            return ""
        return ""


def test_tuning_disables_animations_and_is_idempotent():
    dev = FakeDev()
    cfg = {"android": {"tuning": {"enabled": True}}}
    rep = tune.apply(dev, cfg, _LOG, vm=0)
    assert dev.settings["window_animation_scale"] == "0"
    assert dev.settings["transition_animation_scale"] == "0"
    assert dev.settings["animator_duration_scale"] == "0"
    assert any("svc power stayon" in c for c in dev.calls)
    assert rep["verify"]["ok"] is True and rep["ok"] is True
    n = len(dev.calls)
    rep2 = tune.apply(dev, cfg, _LOG, vm=0)
    assert rep2["skipped"] == "tuned this boot"
    assert len(dev.calls) - n <= 2


def test_tuning_can_be_disabled():
    dev = FakeDev()
    rep = tune.apply(dev, {"android": {"tuning": {"enabled": False}}}, _LOG)
    assert rep["skipped"] == "tuning disabled" and dev.calls == []


# ---------------------------------------------------------------------------
# 3. 会话等待 / 地理一致 / 停顿形状
# ---------------------------------------------------------------------------
def _crawler(tmp_path, **cfg):
    c = BaseCrawler({"user_data_dir": str(tmp_path), **cfg}, _LOG)
    return c


def _null_ctx():
    @contextmanager
    def _cm(*a, **k):
        yield None
    return _cm


def test_profile_wait_zero_keeps_immediate_busy(tmp_path, monkeypatch):
    c = _crawler(tmp_path)
    monkeypatch.setattr(c, "_browser_context", _null_ctx())
    path = os.path.normcase(os.path.realpath(c.user_data_dir))
    lock = base_mod._PROFILE_LOCKS.setdefault(path, threading.Lock())
    assert lock.acquire(blocking=False)
    try:
        t0 = time.time()
        try:
            with c.browser():
                pass
            raise AssertionError("should be busy")
        except SessionBusyError:
            pass
        assert time.time() - t0 < 1.0        # 默认不等
    finally:
        lock.release()


def test_profile_wait_acquires_when_released(tmp_path, monkeypatch):
    c = _crawler(tmp_path, profile_wait_s=5)
    monkeypatch.setattr(c, "_browser_context", _null_ctx())
    path = os.path.normcase(os.path.realpath(c.user_data_dir))
    lock = base_mod._PROFILE_LOCKS.setdefault(path, threading.Lock())
    assert lock.acquire(blocking=False)

    def _release():
        time.sleep(0.25)
        lock.release()
    threading.Thread(target=_release, daemon=True).start()
    with c.browser():                       # 等到锁就继续，不抛 busy
        pass


def test_geo_default_and_override(tmp_path):
    d = _crawler(tmp_path)
    assert d._geo() == ("zh-CN", "Asia/Shanghai")
    assert d.fingerprint()["locale"] == "zh-CN"
    assert d.fingerprint()["timezone"] == "Asia/Shanghai"
    g = _crawler(tmp_path, geo={"locale": "en-US", "timezone": "America/New_York"})
    fp = g.fingerprint()
    assert fp["locale"] == "en-US" and fp["timezone"] == "America/New_York"
    assert set(fp) == {"ua", "viewport", "locale", "timezone", "is_mobile",
                       "has_touch", "proxy", "stealth", "seed"}
    bad = _crawler(tmp_path, geo={"timezone": "Not/AZone"})
    assert bad._geo()[1] == "Asia/Shanghai"     # 非法时区不炸，退回默认


def test_sleep_uses_lognormal_but_stays_in_range(tmp_path, monkeypatch):
    c = _crawler(tmp_path, delay_min=1, delay_max=2)
    seen = []
    monkeypatch.setattr(base_mod.time, "sleep", lambda v: seen.append(v))
    for _ in range(30):
        c._sleep()
    assert len(seen) == 30
    assert all(1.0 <= v <= 2.0 for v in seen)
    assert len(set(round(v, 3) for v in seen)) > 5      # 不是固定值


# ---------------------------------------------------------------------------
# 4. 接线：成功率入账，busy 不入账
# ---------------------------------------------------------------------------
def _mk(name, runner):
    class _C(BaseCrawler):
        def fetch(self, fc, tc, dates, ret_date=""):
            return runner(self)
    _C.name = name
    return _C


def test_safe_fetch_notes_yield_but_not_busy(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}

    ok = _mk("ctrip", lambda s: (s.path_note("pc-list", "ok", rows=7) or [1, 2]))(cfg, _LOG)
    ok.safe_fetch("SHA", "NRT", ["2026-11-16"])
    led = ok._yield_ledger()
    assert led.samples("ctrip") == 1 and led.rate("ctrip") == 1.0
    assert led.snapshot()["ctrip"]["rows"] == 7

    def _busy(s):
        raise SessionBusyError("busy")
    b = _mk("qunar", _busy)(cfg, _LOG)
    b.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert b.last_busy is True
    assert b._yield_ledger().samples("qunar") == 0      # 自家冲突不罚渠道

    def _boom(s):
        s.path_note("h5", "blocked")
        raise RuntimeError("x")
    f = _mk("tuniu", _boom)(cfg, _LOG)
    f.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert f._yield_ledger().samples("tuniu") == 1
    assert f._yield_ledger().rate("tuniu") == 0.0
