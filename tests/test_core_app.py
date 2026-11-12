# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1059_app_cadence.py
- tests/test_r1167_app_state_evidence.py
- tests/test_r1804_app_login_advice.py
- tests/test_r651_app_channel_name.py
- tests/test_r667_every_app_channel_seizes_device.py
- tests/test_r805ag_app_channels_everywhere.py
- tests/test_r805an_app_health_counts.py
- tests/test_r805be_app_screen_swipe.py
- tests/test_r805bp_app_health_login.py
- tests/test_r805cd_app_wizard_labels.py
- tests/test_r813d_app_surface_parity.py
- tests/test_r814a_app_login_status_semantics.py
- tests/test_r921_app_abi_select.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

from support_webui_src import webui_full_src

import io
import json
import logging
import os
import pytest
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from core.alerter import Alerter
from core.android import login_api, vendor
from core.android.bootstrap import STEPS
from core.android.login_api import dispatch
from core.android.login_session import AppLoginRegistry, AppLoginSession
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_CN, plat_cn
from core.pacing import Pacing, _APP_CN, advise, parse_pacing


# ---- merged from tests/test_r1059_app_cadence.py ----

KEY = ("SHA", "PEK", "2026-11-16")


def _pac(floor=180):
    cad = {p: floor for p in APP_CHANNELS}
    return Pacing({"crawler": {"cadence": cad}})


def test_app_channel_skipped_within_cadence():
    now = time.time()
    pac = _pac(180)
    pac.seed_fetch("app_ctrip", KEY, 727.0, at_ts=now - 60 * 60)  # 1 小时前
    tier, why = pac.plan_query("app_ctrip", KEY, 0, days_ahead=10)
    assert tier == "skip", (tier, why)
    assert "渠道节奏" in why, why


def test_app_channel_runs_after_cadence():
    now = time.time()
    pac = _pac(180)
    pac.seed_fetch("app_ctrip", KEY, 727.0, at_ts=now - 181 * 60)
    tier, why = pac.plan_query("app_ctrip", KEY, 0, days_ahead=10)
    assert tier != "skip", (tier, why)


def test_cadence_zero_means_follow_global_ttl():
    now = time.time()
    pac = _pac(0)
    pac.seed_fetch("app_ctrip", KEY, 727.0, at_ts=now - 60 * 60)
    tier, _why = pac.plan_query("app_ctrip", KEY, 0, days_ahead=10)
    assert tier != "skip"


def test_first_run_has_no_baseline_and_runs():
    """没有历史基线时必须跑——cadence 不能把新渠道永久挡在门外。"""
    pac = _pac(180)
    tier, why = pac.plan_query("app_zhixing", KEY, 0, days_ahead=10)
    assert tier != "skip", (tier, why)
    assert "无历史基线" in why


def test_parse_covers_all_app_channels():
    """每个 App 渠道都要有 key：缺 key 会让调度层退化成"无节奏"。"""
    parsed = parse_pacing({"crawler": {"cadence": dict.fromkeys(
        APP_CHANNELS, 180)}})
    for p in APP_CHANNELS:
        assert parsed["cadence"].get(p) == 180, p


def test_yaml_later_key_wins_trap(monkeypatch):
    """回归我 2026-11-06 踩的坑：config.yaml 里若同时出现 `cadence: {}` 和
    一个完整的 cadence 块，YAML 是**后者胜出**——写在前面等于没写。
    这条不测 yaml 行为本身，而是钉住「解析结果必须来自唯一的 cadence 键」。
    """
    import yaml
    doc = "crawler:\n  cadence: {}\n  cadence:\n    app_ctrip: 180\n"
    parsed = parse_pacing(yaml.safe_load(doc))
    assert parsed["cadence"]["app_ctrip"] == 180


# ---- merged from tests/test_r1167_app_state_evidence.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _Sess:
    status = "pending"

    def view(self):
        return {"plat": "app_fliggy", "status": "pending",
                "saved": False, "needs_login": False}


class _Reg:
    def __init__(self, sess=None):
        self._s = sess

    def get(self, plat):
        return self._s


def _state(reg, snapshot=None, needs_login=None):
    out, code = login_api.handle_state(reg, "app_fliggy",
                                       None if snapshot is None else (lambda p: snapshot),
                                       None if needs_login is None else (lambda p: needs_login))
    assert code == 200, (out, code)
    return out


def test_no_session_no_snapshot():
    out = _state(_Reg(None), snapshot={"exists": False, "mtime": 0})
    assert out["snapshot_saved"] is False, out
    assert out["live_now"] is False, out
    assert out["saved"] is False, out
    assert out["evidence"] == "无", out


def test_snapshot_only():
    out = _state(_Reg(None), snapshot={"exists": True, "mtime": 1793700048.0})
    assert out["snapshot_saved"] is True and out["saved"] is True, out
    assert out["live_now"] is False, out
    assert out["evidence"] == "快照", out


def test_live_without_snapshot_is_not_saved():
    """关键场景：设备上登着、但没导快照 —— 用户说的"我登了但页面没变"。"""
    out = _state(_Reg(_Sess()), snapshot={"exists": False, "mtime": 0})
    assert out["live_now"] is True, out
    assert out["snapshot_saved"] is False, out
    assert out["saved"] is False, "没有快照就不能报已保存（否则重启即失效）"
    assert out["evidence"] == "设备在线", out


def test_live_and_snapshot():
    out = _state(_Reg(_Sess()), snapshot={"exists": True, "mtime": 1793700048.0})
    assert out["live_now"] is True and out["snapshot_saved"] is True, out
    assert out["evidence"] == "快照", out


def test_legacy_fields_kept():
    out = _state(_Reg(None), snapshot={"exists": True, "mtime": 1793700048.0},
                 needs_login=True)
    for k in ("ok", "session", "needs_login", "saved", "saved_at"):
        assert k in out, "旧字段 %s 被删了，前端会静默坏掉：%s" % (k, out)
    assert out["needs_login"] is True


def test_ui_distinguishes_live_unsaved():
    """界面必须能把「设备上登着但没存快照」单独显示出来。"""
    import io

    w = webui_full_src()
    assert "live_unsaved" in w, "前端没有「设备在线未存快照」这一档"
    assert "设备已登录 · 未存快照" in w, "缺少给人看的中文标签"
    assert "live_now" in w and "snapshot_saved" in w, (
        "前端没有把 live_now / snapshot_saved 从接口读下来")


# ---- merged from tests/test_r1804_app_login_advice.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOW = time.time()
OFF = {"active": False}
CH = {"needs_login": True, "state": "login"}


def _hint(plat):
    return advise(plat, dict(CH), {}, now=NOW, quiet=OFF).get("hint") or ""


def test_app_channel_advice_points_at_the_phone():
    for p, name in (("app_qunar", "去哪儿 App"), ("app_tongcheng", "同程 App"),
                    ("app_zhixing", "智行 App")):
        h = _hint(p)
        assert "手机上打开" in h, (p, h)
        assert "「%s」" % name in h, (p, h)
        assert "验证码需你本人填" in h, (p, h)
        assert "去验证" not in h, "App 渠道仍建议点「去验证」：" + h


def test_web_channel_advice_unchanged():
    h = _hint("ctrip")
    assert "去验证" in h, h
    assert "手机上打开" not in h, h


def test_app_name_map_covers_all_app_channels():
    for p in ("app_ctrip", "app_fliggy", "app_qunar", "app_tongcheng",
              "app_zhixing"):
        assert p in _APP_CN, "缺中文名：" + p


# ---- merged from tests/test_r651_app_channel_name.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_app_channel_has_chinese_name():
    assert Alerter.plat_cn("app_zhixing") == "智行 App"


def test_browser_channels_unchanged():
    assert Alerter.plat_cn("qunar") == "去哪儿"
    assert Alerter.plat_cn("fliggy") == "飞猪"
    assert Alerter.plat_cn("ctrip") == "携程"
    assert Alerter.plat_cn("tongcheng") == "同程"
    assert Alerter.plat_cn("tuniu") == "途牛"


def test_unknown_channel_falls_back_to_id():
    assert Alerter.plat_cn("no_such_plat") == "no_such_plat"


def test_default_platform_set_excludes_app_channel():
    """默认全集不能含 App 渠道——否则未启用者每轮收缺勤告警。"""
    assert "app_zhixing" not in Alerter.PLATFORM_CN
    a = Alerter(logging.getLogger("t"))
    assert "app_zhixing" not in a.platforms


def test_no_raw_platform_cn_get_left_in_message_paths():
    """消息路径必须走 plat_cn，直接 .get(p, p) 会漏掉 App 的中文名。"""
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "alerter.py"),
                  encoding="utf-8", newline="").read()
    bad = [ln for ln in src.splitlines()
           if "PLATFORM_CN.get(" in ln and "PLATFORM_CN.get(p)" not in ln]
    assert not bad, "仍有绕过 plat_cn 的取名：%s" % bad[:3]


# ---- merged from tests/test_r667_every_app_channel_seizes_device.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def _isolated_lock(monkeypatch):
    """换成本文件专用锁：同进程若有别的采集线程持着模块锁，这里会真的
    等满 600s（或把 ``take`` 的超时判成失败），隔离后互不影响。"""
    from core.android import runtime as rt_mod
    monkeypatch.setattr(rt_mod, "_DEVICE_LOCK", threading.Lock())
    monkeypatch.setattr(rt_mod, "_LOCK_STATE", {"owner": "", "since": 0.0})
    yield


def _app_channels():
    from core.channels import APP_CHANNELS
    return tuple(APP_CHANNELS)


@pytest.mark.parametrize("plat", _app_channels())
def test_every_app_channel_holds_the_device_lock(plat):
    src = io.open(os.path.join(ROOT, "crawlers", plat + ".py"),
                  encoding="utf-8", newline="").read()
    # 允许带参数（`device_lock(owner=self.name)`，2026-11-04 起用于定位
    # 「谁占着锁」）；不变量仍然是"必须拿独占锁"。
    assert "device_lock(" in src, (
        "%s 的采集没有拿设备独占锁：两个 App 渠道共用一台模拟器时会互相"
        "打断（channel_slot 是按渠道分锁的，挡不住）" % plat)
    # 必须真的把取数段包进锁里，而不是拿到锁对象就丢
    assert re.search(r"with\s+rt\.device_lock\([^)]*\)\s*:", src), (
        "%s 只是提到了 device_lock，但没有把它当上下文管理器包住采集段"
        % plat)


def test_device_lock_is_module_level_singleton():
    """锁必须是模块级单例：每个 runtime 实例一把锁等于没有锁。"""
    from core.android import runtime as rt_mod
    assert hasattr(rt_mod, "_DEVICE_LOCK")
    import threading
    assert isinstance(rt_mod._DEVICE_LOCK, type(threading.Lock()))
    # 两个 runtime 实例拿到的是同一把
    a = rt_mod.AndroidRuntime.__new__(rt_mod.AndroidRuntime)
    b = rt_mod.AndroidRuntime.__new__(rt_mod.AndroidRuntime)
    seen = []

    def take(inst, tag):
        with inst.device_lock(timeout=1):
            seen.append(tag)

    import threading as _t
    t1 = _t.Thread(target=take, args=(a, "a"))
    t1.start()
    t1.join(2)
    t2 = _t.Thread(target=take, args=(b, "b"))
    t2.start()
    t2.join(2)
    assert seen == ["a", "b"], "两个 runtime 实例没有共用同一把设备锁：%s" % seen


# ---- merged from tests/test_r805ag_app_channels_everywhere.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP_NAMES = [CHANNEL_CN[p] for p in APP_CHANNELS]
ALL_COUNT = len(BROWSER_CHANNELS) + len(APP_CHANNELS)




# ---- merged from tests/test_r805an_app_health_counts.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_HEAD = ("2026-11-01 09:00:00 [INFO] ticket-monitor: "
         "===== 开始一轮扫描（1 用户 / 1 航线） =====\n")
_TAIL = ("2026-11-01 09:00:09 [INFO] ticket-monitor: "
         "===== 本轮扫描结束 =====\n")


def _round(log):
    from core.health import parse_health
    out = parse_health(log, hours=2400)
    rounds = out.get("rounds") or []
    assert rounds, "解析不出任何轮次，判据失去锚点"
    return rounds[-1]["plats"]


def test_app_rows_success_counts_as_ok():
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[app_zhixing] 抓取完成，得到 1 条记录\n"
           + "2026-11-01 09:00:06 [INFO] ticket-monitor: "
             "[app_qunar] 抓取完成，得到 3 条记录\n"
           + _TAIL)
    p = _round(log)
    for plat, rows in (("app_zhixing", 1), ("app_qunar", 3)):
        rp = p.get(plat) or {}
        assert rp.get("s") == "ok", (
            "%s 出了 %d 条却判成 %r（App 出数日志没被计入）"
            % (plat, rows, rp.get("s")))
        assert int(rp.get("detail") or 0) >= 1, (
            "%s 的 detail 计数为 0，明细证据丢了：%s" % (plat, rp))


def test_app_zero_rows_is_empty_not_failure():
    """「得到 0 条」是真跑通了、当天没票 —— 记 fail 会误导人重登/换网。"""
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[app_zhixing] 抓取完成，得到 0 条记录\n"
           + _TAIL)
    p = _round(log)
    rp = p.get("app_zhixing") or {}
    assert rp.get("s") == "empty", (
        "「得到 0 条」应记空结果，实测 %r：%s" % (rp.get("s"), rp))
    assert rp.get("note"), "空结果也要有说明，不能留空"


def test_app_navigation_failure_is_not_empty():
    """没完成导航/选城市，不能说成「本轮无票」。"""
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[app_qunar] 设出发城市失败：上海\n"
           + "2026-11-01 09:00:06 [INFO] ticket-monitor: "
             "[app_qunar] 抓取完成，得到 0 条记录\n"
           + _TAIL)
    rp = _round(log).get("app_qunar") or {}
    assert rp.get("s") == "fail", (
        "导航失败应记 fail，实测 %r：%s" % (rp.get("s"), rp))
    assert "导航失败" in str(rp.get("note") or ""), rp


def test_ok_round_does_not_keep_empty_note():
    """同轮既有明细成功又有空结果时，整轮不能写「本轮无票」。

    线上 19:56 qunar：国内 3 条明细 + 国际 3 条空，健康卡却挂
    「本轮无票（得到 0 条）」，把出数轮说成没票。
    """
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[qunar] 2026-11-16 最低价 ￥500（航班明细 10 条：直飞 10）\n"
           + "2026-11-01 09:00:06 [INFO] ticket-monitor: "
             "[qunar] 抓取完成，得到 0 条记录\n"
           + _TAIL)
    rp = _round(log).get("qunar") or {}
    assert rp.get("s") == "ok", rp
    assert "无票" not in str(rp.get("note") or ""), rp


def test_real_log_app_channels_are_not_reported_failed():
    """用生产日志最后一段真跑：App 两家不得被判 fail。

    这条是对「面板说失败、账本说成功」的**直接**回归——只要日志里
    真出现过「抓取完成，得到 N 条」，健康度就不能说它失败。
    """
    path = os.path.join(ROOT, "tests", "fixtures", "monitor_round_app.txt")
    assert os.path.isfile(path), "生产日志摘录缺失：%s" % path
    text = io.open(path, encoding="utf-8", errors="replace").read()
    lines = text.splitlines()
    idx = [i for i, l in enumerate(lines) if "开始一轮扫描" in l]
    assert idx, "摘录里没有轮次标记"
    from core.health import parse_health
    out = parse_health("\n".join(lines[idx[-1]:]), hours=2400)
    rounds = out.get("rounds") or []
    assert rounds, "最后一段日志解析不出轮次"
    plats = rounds[-1]["plats"]
    seg = "\n".join(lines[idx[-1]:])
    for plat in ("app_zhixing", "app_qunar"):
        tag = "[%s] 抓取完成，得到 " % plat
        zero = "[%s] 抓取完成，得到 0 条记录" % plat
        produced = (tag in seg) and (zero not in seg)
        rp = plats.get(plat) or {}
        if produced and rp.get("s") == "fail":
            raise AssertionError(
                "日志里 %s 明确出过数，健康度却判 fail：%s" % (plat, rp))


# ---- merged from tests/test_r805be_app_screen_swipe.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Dev:
    size = (900, 1600)

    def __init__(self):
        self.swipes = []
        self.ok = True

    def window_size(self):
        return self.size

    def swipe(self, x1, y1, x2, y2, dur=300):
        self.swipes.append((x1, y1, x2, y2, dur))
        return self.ok


class RT:
    def __init__(self, dev):
        self._d = dev

    def device(self):
        return self._d


def _sess(dev):
    return AppLoginSession("app_qunar", RT(dev), "com.Qunar")


def test_swipe_forwards_and_counts():
    dev = Dev()
    s = _sess(dev)
    assert s.swipe(100, 1200, 100, 400, 250) is True
    assert dev.swipes == [(100, 1200, 100, 400, 250)]
    assert s.view()["swipes"] == 1


def test_swipe_clamps_duration():
    dev = Dev()
    s = _sess(dev)
    s.swipe(0, 0, 10, 10, 5)          # 太短 → 抬到 80
    s.swipe(0, 0, 10, 10, 99999)      # 太长 → 压到 2000
    assert [d for *_, d in dev.swipes] == [80, 2000]


def test_swipe_rejects_out_of_screen():
    dev = Dev()
    s = _sess(dev)
    assert s.swipe(100, 1200, 100, 1700) is False
    assert not dev.swipes
    assert "超出屏幕" in s.detail


def test_api_routes_swipe():
    dev = Dev()
    reg = AppLoginRegistry()
    reg._sessions["app_qunar"] = _sess(dev)     # 直插会话，绕开建会话的设备流程
    res, code = dispatch(reg, "POST", "/api/app-login/swipe", {},
                         {"plat": "app_qunar", "x1": 90, "y1": 1300,
                          "x2": 90, "y2": 500, "dur": 300}, {})
    assert code == 200 and res.get("ok"), res
    assert dev.swipes == [(90, 1300, 90, 500, 300)]


def test_frontend_drag_is_wired_to_swipe():
    src = webui_full_src()
    assert "/api/app-login/swipe" in src, "前端没接到滑动接口"
    assert "appLoginPtrDown" in src and "appLoginPtrUp" in src, "拖动没接线"
    assert "touch-action:none" in src, (
        "命中层缺 touch-action:none：触摸设备上拖动会被浏览器手势吃掉")
    # 拖动结束不能再补一刀 tap（否则滚动后误点）
    assert "APP_DRAG_AT" in src, "拖动后没有抑制补发的 click"

def test_polling_is_adaptive_around_interactions():
    """操作后快取（跟手），静置降频（别跟扫描抢 adb 资源）。"""
    src = webui_full_src()
    assert "function appLoginNextDelay()" in src, "轮询间隔没有自适应"
    assert "appLoginMark()" in src
    assert "setTimeout(()=>appLoginLoop(plat),appLoginNextDelay())" in src, (
        "轮询仍用固定间隔")
    body = src[src.index("function appLoginNextDelay()"):]
    body = body[:body.index("}")]
    assert "120" in body and "700" in body, (
        "自适应间隔缺档位（应为操作后 120ms / 静置 700ms）：%r" % body)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """用完还原 `login_api._LAST_REGISTRY`（r1063 T281）。

    `dispatch()` 会把传入的 registry 记成模块级"当前登录登记表"，供采集侧判断
    "用户正在 App 登录 → 本轮让位"。测试不清理就会把这个状态带给后面的用例：
    后续 App 渠道的 `fetch()` 会被 `early_skip()` 挡掉、直接返回 []（连设备锁
    都不进）。r821 就是这么被弄红的（单跑绿、紧跟本文件跑红）。
    """
    from core.android import login_api as _la
    old = getattr(_la, "_LAST_REGISTRY", None)
    try:
        yield
    finally:
        _la._LAST_REGISTRY = old


# ---- merged from tests/test_r805bp_app_health_login.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_app_login_evidence_becomes_login_card():
    from core.health_diag import classify_round
    cards = classify_round(
        {"app_qunar": {"s": "timeout", "note": "未取到可用结果：set-city-dep"}},
        login={"app_qunar": {"needs_login": True}},
        all_plats=("app_qunar",))
    c = cards[0]
    assert c["kind"] == "login", c
    assert "内嵌画面" in c["action"], (
        "App 渠道的动作必须指向内嵌画面：%r" % c["action"])


def test_browser_login_action_still_points_to_window():
    from core.health_diag import classify_round
    cards = classify_round({"qunar": {"s": "timeout", "note": "拦截"}},
                           login={"qunar": {"needs_login": True}},
                           all_plats=("qunar",))
    assert cards[0]["kind"] == "login"
    assert "内嵌" not in cards[0]["action"], cards[0]["action"]


def test_health_decorate_feeds_login_evidence():
    src = webui_full_src()
    i = src.index("def _health_decorate(")
    seg = src[i:i + 3000]
    assert "_app_login_expired" in seg, "健康诊断没接 App 登录证据"
    assert "login=_login_ev" in seg, "classify_round 仍没收到 login 证据"


# ---- merged from tests/test_r805cd_app_wizard_labels.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_apk_step_names_every_registered_app_channel():
    label = dict(STEPS)["apk"]
    for p in APP_CHANNELS:
        cn = plat_cn(p)
        assert cn in label, "引导步骤没写全 App 渠道名：%r（缺 %s）" % (label, cn)
    assert "智行 App" in label and "去哪儿 App" in label, label
    assert label.strip() != "安装智行 App", "仍是写死单渠道的旧文案"


# ---- merged from tests/test_r813d_app_surface_parity.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _src():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port










def test_selfcheck_whitelist_is_diagnosis_not_login():
    s = _src()
    assert "_SELFCHECK_PLATS = tuple(_LOGIN_PLATS) + tuple(_APP_CHANNELS)" in s
    assert "if plat not in _SELFCHECK_PLATS:" in s
    # 旧写法（登录槽位当白名单）不得回潮
    assert "if plat not in _LOGIN_PLATS:\n                    raise ValueError" \
        not in s


def test_batch_selfcheck_does_not_probe_apps_twice():
    s = _src()
    assert "Object.keys(SRX_PLATS).concat(Object.keys(APP_PLAT_NAME))" not in s
    assert ":Object.keys(SRX_PLATS);" in s


def test_log_title_uses_shared_name_table():
    s = _src()
    i = s.index("async function showLog(")
    block = s[i:i + 1400]
    assert "PCN[p]" in block, block[:300]
    assert "'tongcheng':'同程','tuniu':'途牛'}[p]" not in block


def test_radar_flights_and_push_use_single_name_source():
    s = _src()
    assert 'r["platform_cn"] = _plat_cn(r["platform"])' in s
    assert 'pname = Alerter.plat_cn(str(cur.get("platform") or "")) or "渠道"' in s
    for old in ('"tongcheng": "同程", "tuniu": "途牛"}',
                '"fliggy": "飞猪", "tongcheng": "同程"}.get('):
        assert old not in s, old


def test_same_flight_coverage_denominator_is_not_hardcoded_five():
    """同班覆盖分母写死 5：接入两家 App 后会显示「7/5」。"""
    s = _src()
    assert "'/5 渠道'" not in s
    assert "const _nCh=Math.max(1,new Set(all.map(x=>x.platKey)).size);" in s
    assert "ps.size+'/'+_nCh+' 渠道</span>" in s


def test_pacing_effect_is_computed_for_app_channels_too():
    """节流面板「干预成效」不能只算浏览器五家。"""
    s = _src()
    i = s.index("_eff[_p0] = _pst.intervention_effect")
    block = s[max(0, i - 500):i]
    assert "_APP_CHANNELS" in block, block[-300:]
    assert '"qunar", "tongcheng", "tuniu"]' not in block.replace("\n", " ")


def test_lowest_pill_and_login_toast_use_shared_app_names():
    """「全线最低」胶囊与登录 toast 也不许出现裸 App id。

    这两处各留了一张 5 家名字表：胶囊 `PLATCN`（图标已改 srxPlatKey、
    名字没改）和 toast 的 `LOGIN_CN` 链。App 最便宜/点去登录时会把
    `app_qunar` / `app` 直接打到屏上。
    """
    s = _src()
    assert "const PLATCN=" not in s
    assert "platCN(brief.view_plat||brief.plat)" in s
    i = s.index("const _nm=(typeof LOGIN_SLOT_CN")
    toast = s[i:i + 400]
    assert "APP_PLAT_NAME[p]" in toast, (
        "登录 toast 的名称链没有 App 名：%r" % toast[:200])


def test_intervention_scope_app_is_split_per_channel():
    """两个 App 的登录干预必须可区分：写渠道 id，不合并成 app。"""
    s = _src()
    assert "app:'智行 App'" not in s
    assert "app_zhixing:'智行 App'" in s
    assert "app_qunar:'去哪儿 App'" in s
    assert "app:'App 登录（旧记录）'" in s
    assert "scope=_plata" in s


# ---- merged from tests/test_r814a_app_login_status_semantics.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Dev:
    def screencap(self):
        return b"\x89PNG-x"

    def window_size(self):
        return (900, 1600)

    def tap(self, x, y):
        return True

    def input_text(self, text):
        return True

    def keyevent(self, key):
        return True


class _Rt:
    def device(self):
        return _Dev()


def _session(timeout_s=900):
    from core.android.login_session import AppLoginSession
    return AppLoginSession("app_zhixing", _Rt(), "cn.suanya.zhixing",
                           timeout_s=timeout_s)


def test_session_view_reports_active():
    v = _session().view()
    assert v["status"] == "pending"
    assert v["active"] is True, "进行中的会话没下发 active，卡片不会说「继续登录」"


def test_finished_session_is_not_active():
    s = _session()
    s.finish(True, "ok")
    v = s.view()
    assert v["active"] is False
    assert v["status"] == "done"


def test_expired_session_view_is_not_active():
    from core.android.login_session import AppLoginRegistry
    s = _session(timeout_s=1)
    s.created_at -= 5
    reg = AppLoginRegistry()
    reg.put(s)
    got = reg.get("app_zhixing")
    v = got.view()
    assert v["status"] == "expired"
    assert v["active"] is False


def test_state_endpoint_reports_expired_status():
    from core.android import login_api
    from core.android.login_session import AppLoginRegistry
    s = _session(timeout_s=1)
    s.created_at -= 5
    reg = AppLoginRegistry()
    reg.put(s)
    obj, code = login_api.handle_state(
        reg, "app_zhixing",
        snapshot_info=lambda p: {"exists": True, "mtime": 123.0},
        needs_login=lambda p: True)
    assert code == 200
    assert obj["session"]["status"] == "expired"
    assert obj["session"]["active"] is False
    assert obj["session"]["saved"] is True






# ---- merged from tests/test_r921_app_abi_select.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r921")

_TABLE = """\
com\\.tencent\\.tmgp\\.dnf    arm64-v8a   # 地下城与勇士
com\\.netease\\.onmyoji      x86_64      # yys
ctrip\\.android\\.view       arm64-v8a   # 携程
com\\.Qunar                  arm64-v8a   # 去哪儿
############################################
.*\\.tmgp\\..*               arm         # 应用宝默认ARM
"""


class FakeDev:
    """假设备：``cat`` 返回表内容，``cp``/``printf`` 记录调用。"""

    def __init__(self, table=_TABLE, has_backup=False):
        self.table = table
        self.has_backup = has_backup
        self.calls = []
        self.appended = ""

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd == "shell cat %s" % vendor.ABI_SELECT:
            return self.table
        if "ls /data/local/tmp/abi-select.orig" in cmd:
            return "/data/local/tmp/abi-select.orig" if self.has_backup else ""
        if cmd.startswith("shell cp -f %s /data" % vendor.ABI_SELECT):
            self.has_backup = True
            return ""
        if "printf" in cmd and ">>" in cmd:
            # 取出单引号里的 payload
            i = cmd.find("'")
            j = cmd.rfind("'")
            self.appended = cmd[i + 1:j].replace("'\\''", "'")
            self.table = self.table + self.appended
            return "TM_OK"
        if "cp -f /data/local/tmp/abi-select.orig" in cmd:
            self.table = _TABLE
            return "TM_OK"
        return ""


# ---------------------------------------------------------------------------
# 1. 读：第一列是正则，不是裸包名
# ---------------------------------------------------------------------------
def test_read_parses_escaped_patterns():
    cur = vendor.read_abi_select(FakeDev())
    assert cur["exists"] is True
    assert cur["apps"]["ctrip.android.view"] == "arm64-v8a"
    assert cur["apps"]["com.Qunar"] == "arm64-v8a"
    # 不在票务表里的包不该被收进来
    assert "com.tencent.tmgp.dnf" not in cur["apps"]


def test_read_missing_table_is_soft():
    cur = vendor.read_abi_select(FakeDev(table=""))
    assert cur["exists"] is False and cur["apps"] == {}


def test_read_ignores_comment_and_wildcard_lines():
    cur = vendor.read_abi_select(FakeDev())
    # 通配行 .*\.tmgp\..* 不是我们的包
    assert all("tmgp" not in p for p in cur["apps"])


# ---------------------------------------------------------------------------
# 2. 写：幂等 + 备份 + 只加缺的
# ---------------------------------------------------------------------------
def test_set_app_abi_adds_missing_and_backs_up():
    dev = FakeDev()
    rep = vendor.set_app_abi(dev)
    assert rep["ok"] is True
    assert set(rep["added"]) == {"com.taobao.trip", "com.tongcheng.android",
                                 "cn.suanya.zhixing"}
    assert rep["present"] == ["ctrip.android.view", "com.Qunar"]
    assert rep["restart_required"] is True
    assert "arm64-v8a" in dev.appended
    assert "com\\.taobao\\.trip" in dev.appended
    # 备份动作发生过
    assert any("cp -f %s" % vendor.ABI_SELECT in c for c in dev.calls)


def test_set_app_abi_is_idempotent():
    dev = FakeDev()
    vendor.set_app_abi(dev)
    before = dev.table
    rep2 = vendor.set_app_abi(dev)
    assert rep2["ok"] is True and rep2["added"] == []
    assert rep2["restart_required"] is False      # 没变就不用重启
    assert dev.table == before                    # 没重复追加


def test_set_app_abi_custom_abi():
    dev = FakeDev()
    rep = vendor.set_app_abi(dev, apps={"com.Qunar": r"com\.Qunar"},
                             abi="armeabi-v7a")
    assert rep["added"] == []                     # 已在表里
    # 自定义包：能写进去（read_abi_select 只回读票务包，所以按 payload 断言）
    rep2 = vendor.set_app_abi(dev, apps={"com.new.app": r"com\.new\.app"},
                              abi="armeabi-v7a")
    assert "com\\.new\\.app" in dev.appended
    assert "armeabi-v7a" in dev.appended
    # read_abi_select 的职责是"票务包现状"，不含自定义包 —— 这是刻意的窄口径
    assert "com.new.app" not in vendor.read_abi_select(dev)["apps"]


def test_set_app_abi_reports_missing_table():
    dev = FakeDev(table="")
    rep = vendor.set_app_abi(dev)
    assert rep["ok"] is False and "abi-select" in rep["error"]


# ---------------------------------------------------------------------------
# 3. 回滚
# ---------------------------------------------------------------------------
def test_revert_restores_backup():
    dev = FakeDev()
    vendor.set_app_abi(dev)                       # 追加并产生备份
    assert "com\\.taobao\\.trip" in dev.table
    rep = vendor.revert_app_abi(dev)
    assert rep["ok"] is True
    assert "com\\.taobao\\.trip" not in dev.table  # 回到原表
    assert dev.table == _TABLE


def test_revert_without_backup_is_reported():
    rep = vendor.revert_app_abi(FakeDev(has_backup=False))
    assert rep["ok"] is False and "没有备份" in rep["error"]


# ---------------------------------------------------------------------------
# 4. 票务包清单
# ---------------------------------------------------------------------------
def test_ticket_apps_cover_five_channels():
    assert set(vendor.TICKET_APPS) == {
        "ctrip.android.view", "com.taobao.trip", "com.Qunar",
        "com.tongcheng.android", "cn.suanya.zhixing"}
    for pat in vendor.TICKET_APPS.values():
        assert r"\." in pat, pat                  # 必须是转义形式
