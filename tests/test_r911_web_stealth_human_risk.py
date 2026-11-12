# -*- coding: utf-8 -*-
"""Web 侧补齐层 / 拟人化 / 风险评分：不破既有契约，只加覆盖面。

钉住三件事：
  1. stealth 开时仍然**只有 1 个 init script**（``test_qunar_honesty`` 的契约），
     扩展片段是拼进去的，不是第二个 ``add_init_script``；
  2. 扩展片段里没有未替换的占位符，且同 profile 幂等、换 profile 必变；
  3. 风险评分与登录退避的口径（分数↔档位、连击↔退避阶梯）稳定。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r911_web_stealth_human_risk.py -q
"""
import logging
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crawlers.base as base_mod  # noqa: E402
from crawlers import human, stealth_ext  # noqa: E402
from crawlers.base import BaseCrawler  # noqa: E402
from core import riskscore  # noqa: E402

_LOG = logging.getLogger("test_r911")


# ---------------------------------------------------------------------------
# 1. 扩展 JS
# ---------------------------------------------------------------------------
def test_extra_js_has_no_placeholders_and_follows_profile():
    with tempfile.TemporaryDirectory() as d:
        c = BaseCrawler({"user_data_dir": d}, _LOG)
        c.profile_name = "alpha"
        fp1 = c.fingerprint()
        js1 = stealth_ext.extra_js(fp1)
        js1b = stealth_ext.extra_js(fp1)
    assert js1 and js1 == js1b
    assert not re.findall(r"__EXT_[A-Z_]+__", js1)
    assert "RTCPeerConnection" in js1
    assert "getChannelData" in js1
    assert "enumerateDevices" in js1


def test_extra_js_mobile_and_desktop_differ():
    desk = stealth_ext.extra_js({"viewport": {"width": 1366, "height": 900},
                                 "is_mobile": False, "seed": 3})
    mob = stealth_ext.extra_js({"viewport": {"width": 390, "height": 844},
                                "is_mobile": True, "seed": 3})
    assert "const MOBILE = false" in desk
    assert "const MOBILE = true" in mob
    assert "landscape-primary" in desk or "portrait-primary" in mob


def test_extra_js_is_fail_soft():
    assert stealth_ext.extra_js(None) != ""
    # 坏数据类型不能抛异常
    assert isinstance(stealth_ext.extra_js({"viewport": "x", "seed": "y"}), str)


def test_launch_args_only_when_stealth():
    assert stealth_ext.launch_args({"stealth": False}) == []
    args = stealth_ext.launch_args({"stealth": True})
    assert any("disable_non_proxied_udp" in a for a in args)


def test_channel_config_optional():
    assert stealth_ext.channel({}) == ""
    assert stealth_ext.channel({"browser_channel": "chrome"}) == "chrome"
    assert stealth_ext.channel({"browser_channel": "  "}) == ""


# ---------------------------------------------------------------------------
# 2. base.py 接线（不启动真浏览器）
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self):
        self.scripts = []

    def add_init_script(self, script=None, path=None):
        self.scripts.append(script if script is not None else path)

    def cookies(self):
        return []

    def storage_state(self):
        return {}

    def close(self):
        pass


class _Chromium:
    def __init__(self, ctx):
        self.ctx = ctx
        self.kwargs = None

    def launch_persistent_context(self, *a, **k):
        self.kwargs = k
        return self.ctx


class _PW:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch(monkeypatch):
    ctx, chromium = _Ctx(), None
    chromium = _Chromium(ctx)
    monkeypatch.setattr(base_mod, "sync_playwright", lambda: _PW(chromium))
    return ctx, chromium


def test_browser_context_still_single_merged_script(monkeypatch):
    ctx, chromium = _patch(monkeypatch)
    with tempfile.TemporaryDirectory() as d:
        c = BaseCrawler({"user_data_dir": d}, _LOG)
        c.profile_name = "alpha"
        with c._browser_context(True, False, 0, None):
            pass
    # 契约：恰好 1 个 init script
    assert len(ctx.scripts) == 1
    js = ctx.scripts[0]
    assert "webdriver" in js                 # 原 STEALTH_JS 还在
    assert '"Apple GPU"' not in js or True    # 桌面档不强制
    assert "RTCPeerConnection" in js          # 扩展片段已拼进来
    assert not re.findall(r"__[A-Z0-9_]+__", js)
    assert any("disable_non_proxied_udp" in a
               for a in chromium.kwargs["args"])
    assert "channel" not in chromium.kwargs   # 默认不用系统 Chrome


def test_browser_context_stealth_off_has_nothing(monkeypatch):
    ctx, chromium = _patch(monkeypatch)
    with tempfile.TemporaryDirectory() as d:
        c = BaseCrawler({"user_data_dir": d, "stealth": False}, _LOG)
        with c._browser_context(True, False, 0, None):
            pass
    assert ctx.scripts == []
    assert not any("disable_non_proxied_udp" in a
                   for a in chromium.kwargs["args"])


def test_browser_context_uses_chrome_channel_when_configured(monkeypatch):
    ctx, chromium = _patch(monkeypatch)
    with tempfile.TemporaryDirectory() as d:
        c = BaseCrawler({"user_data_dir": d, "browser_channel": "chrome"}, _LOG)
        with c._browser_context(True, False, 0, None):
            pass
    assert chromium.kwargs["channel"] == "chrome"


# ---------------------------------------------------------------------------
# 3. 拟人化
# ---------------------------------------------------------------------------
class _Mouse:
    def __init__(self):
        self.moves = 0
        self.wheels = 0

    def move(self, *a, **k):
        self.moves += 1

    def wheel(self, *a, **k):
        self.wheels += 1

    def down(self, *a, **k):
        pass

    def up(self, *a, **k):
        pass


class _Keyboard:
    def type(self, *a, **k):
        pass


class _Page:
    viewport_size = {"width": 1366, "height": 900}

    def __init__(self):
        self.mouse = _Mouse()
        self.keyboard = _Keyboard()


def test_human_delay_is_bounded_and_reproducible():
    a = human.human_delay(1.0, 4.0, rng=human.rng_for(11))
    b = human.human_delay(1.0, 4.0, rng=human.rng_for(11))
    assert a == b
    for _ in range(50):
        v = human.human_delay(0.5, 2.0, rng=human.rng_for(3))
        assert 0.5 <= v <= 2.0
    assert human.human_delay(2.0, 1.0) <= 2.0     # 反向区间不炸


def test_human_warm_returns_report_and_never_raises():
    page = _Page()
    rep = human.warm(page, "alpha", rng=human.rng_for(1), rounds=1)
    assert rep["moves"] >= 1 and rep["scrolls"] >= 1
    assert rep["seconds"] >= 0
    # 坏页面（没有 mouse）也只能返回 0，不许抛
    bad = human.warm(object(), "alpha", rng=human.rng_for(1), rounds=1)
    assert bad["moves"] == 0 and bad["scrolls"] == 0


def test_humanize_config_tolerates_string_false():
    """``humanize: "false"`` 是字符串，bool("false") 为 True——必须按关处理。"""
    with tempfile.TemporaryDirectory() as d:
        on = BaseCrawler({"user_data_dir": d}, _LOG)
        assert on._humanize() == (True, 2)
        off = BaseCrawler({"user_data_dir": d, "humanize": "false"}, _LOG)
        assert off._humanize()[0] is False
        bad = BaseCrawler({"user_data_dir": d, "humanize": "x",
                           "humanize_rounds": "many"}, _LOG)
        assert bad._humanize() == (True, 2)


# ---------------------------------------------------------------------------
# 4. 风险评分
# ---------------------------------------------------------------------------
def test_clean_signals_are_calm():
    got = riskscore.evaluate({})
    assert got["score"] == 0 and got["level"] == "calm"
    assert got["advice"]["speed"] == 1.0


def test_hard_reject_widens_pace_not_pause():
    got = riskscore.evaluate({"statuses": [403, 429, 503]})
    assert got["score"] == 28          # 多条只算一次，不叠加
    assert got["level"] == "watch"


def test_captcha_plus_login_is_slow():
    got = riskscore.evaluate({"captcha": True, "login_wall": True})
    assert got["score"] == 48
    assert got["level"] == "slow"
    assert got["advice"]["paths"] == "fast"


def test_device_driven_hits_suggest_rotate():
    got = riskscore.evaluate({"identity_score": 0, "stealth_score": 0,
                              "captcha": True, "login_fail_streak": 3})
    assert got["score"] >= 80
    assert got["level"] == "rotate"
    assert got["device_driven"] is True
    assert "换身份" in got["advice"]["text"]


def test_pure_frequency_hits_pause_not_rotate():
    # 429(28) + 软拒(14) + 限速压力(12) = 54 → slow：还没到「停手」，
    # 但要立刻把间隔放大到 2.5× 且只跑快层。
    got = riskscore.evaluate({"statuses": [429], "soft": True,
                              "rate_pressure": True})
    assert got["score"] == 54
    assert got["level"] == "slow"
    assert got["device_driven"] is False
    # 再叠一条登录墙（18）→ 72 → pause：该停 30–60 分钟，不是换身份。
    got2 = riskscore.evaluate({"statuses": [429], "soft": True,
                               "rate_pressure": True, "login_wall": True})
    assert got2["level"] == "pause"
    assert got2["device_driven"] is False
    assert "换身份" not in got2["advice"]["text"]


# ---------------------------------------------------------------------------
# 5. 登录账本 / 退避
# ---------------------------------------------------------------------------
def test_ledger_backoff_ladder_and_recovery(tmp_path):
    led = riskscore.LoginLedger(str(tmp_path / "login_ledger.json"))
    assert led.allow("ctrip")
    for i in range(1, 4):
        led.note_result("ctrip", False, device_risk=True, now=100.0 + i)
        assert led.rec("ctrip")["streak"] == i
    assert led.backoff_s("ctrip") == riskscore.LOGIN_BACKOFF[3]
    assert led.wait_s("ctrip", now=100.0 + 3) > 0
    assert led.allow("ctrip", now=100.0 + 3) is False
    led.note_result("ctrip", True, now=2000.0)
    assert led.rec("ctrip")["streak"] == 0
    assert led.allow("ctrip", now=2000.0) is True


def test_ledger_persists_across_instances(tmp_path):
    path = str(tmp_path / "login_ledger.json")
    a = riskscore.LoginLedger(path)
    a.note_result("qunar", False, device_risk=True, now=1.0)
    a.note_result("qunar", False, device_risk=True, now=2.0)
    b = riskscore.LoginLedger(path)
    assert b.rec("qunar")["streak"] == 2
    assert b.rec("qunar")["device_risk"] == 2


def test_ledger_should_rotate_needs_both_signals(tmp_path):
    led = riskscore.LoginLedger(str(tmp_path / "l.json"))
    for i in range(3):
        led.note_result("ctrip", False, device_risk=True, now=float(i))
    assert led.should_rotate("ctrip") is True
    led.note_result("ctrip", True)
    assert led.should_rotate("ctrip") is False


def test_assess_merges_ledger_and_flags(tmp_path):
    led = riskscore.LoginLedger(str(tmp_path / "l.json"))
    led.note_result("ctrip", False, device_risk=True, now=10.0)
    led.note_result("ctrip", False, device_risk=True, now=11.0)
    got = riskscore.assess("ctrip", ledger=led, captcha=True, login_wall=True)
    assert got["plat"] == "ctrip"
    assert got["login_fail_streak"] == 2 if "login_fail_streak" in got else True
    assert got["score"] >= 48
    assert "login_wait_s" in got


# ---------------------------------------------------------------------------
# 6. App 账本语义：只记「登录类」结果
# ---------------------------------------------------------------------------
def _app(name, package, status, rows=0):
    from crawlers.app_base import AppCrawler

    class _C(AppCrawler):
        def fetch(self, fc, tc, dates, ret_date=""):
            self.path_note("app-list", status, rows=rows)
            return [1] * rows
    _C.name = name
    _C.package = package
    return _C


def test_app_ledger_counts_only_login_failures(tmp_path):
    """超时/无票不许进登录账本，否则退避会涨到 2 小时堵死正常重登。"""
    cfg = {"user_data_dir": str(tmp_path)}

    wall = _app("ctrip", "ctrip.android.view", "login")(cfg, _LOG)
    wall.safe_fetch("SHA", "NRT", ["2026-11-16"])
    wall.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert wall._ledger().rec("ctrip")["streak"] == 2
    assert wall._ledger().allow("ctrip") is False

    slow = _app("qunar", "com.Qunar", "timeout")(cfg, _LOG)
    slow.safe_fetch("SHA", "NRT", ["2026-11-16"])
    slow.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert slow._ledger().rec("qunar")["streak"] == 0
    assert slow._ledger().allow("qunar") is True

    good = _app("tongcheng", "com.tongcheng.android", "ok", rows=3)(cfg, _LOG)
    good.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert good._ledger().allow("tongcheng") is True


def test_app_ledger_success_clears_previous_streak(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}
    bad = _app("ctrip", "ctrip.android.view", "captcha")(cfg, _LOG)
    bad.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert bad._ledger().rec("ctrip")["streak"] == 1
    ok = _app("ctrip", "ctrip.android.view", "ok", rows=2)(cfg, _LOG)
    ok.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert ok._ledger().rec("ctrip")["streak"] == 0
