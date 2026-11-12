# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_app_backstop.py
- tests/test_r1063_app_check.py
- tests/test_r1063_app_fallback.py
- tests/test_r1063_app_geo.py
- tests/test_r1063_app_horizon_harvest.py
- tests/test_r1063_app_risk_visible.py
- tests/test_r1063_app_slider.py
- tests/test_r1063_app_version_guard.py
- tests/test_r1063_dump_u2_fast.py
- tests/test_r1063_emulator_geo_status.py
- tests/test_r1063_reset_app_api.py
- tests/test_r646_app_login_records_intervention.py
- tests/test_r654_app_intervention_parity.py
- tests/test_r805bo_app_login_expired.py
- tests/test_r942_app_global_auth.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import io as _io
import json
import logging
import os
import pytest
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import yaml

from core import app_check as AC, failover as F, failover as fo
from core.android import appvcode, appversion as av, emulator as em, geo
from core.android.device import AdbDevice
from entry_mon_harness import _goto, page, srv


# ---- merged from tests/test_webui_app.py ----

# ---- merged from tests/test_r1063_app_backstop.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_browser_counterpart_maps_and_rejects():
    assert F.browser_counterpart("app_ctrip") == "ctrip"
    assert F.browser_counterpart("app_fliggy") == "fliggy"
    assert F.browser_counterpart("ctrip") == ""      # 反函数只吃 App 名
    assert F.browser_counterpart("") == ""


def test_retired_target_is_refused(tmp_path, monkeypatch):
    """qunar 已永久停服：反补过去就是往黑洞里扔请求（真机第一炮的反例）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_qunar", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "", why
    assert "停服" in why, why


def test_backstop_uses_injected_fact(tmp_path, monkeypatch):
    """注入 blocked=True 时必须反补（文件里没墙也要认）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_ctrip", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "ctrip", why


def test_no_counterpart_for_zhixing(tmp_path, monkeypatch):
    """智行没有浏览器孪生 → 不反补（避免造一个不存在的目标）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_zhixing", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "", why


def test_running_counterpart_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_ctrip", {}, user_data_dir=str(tmp_path),
                              blocked=True, running=("ctrip",))
    assert app == "", "浏览器通路本轮已在跑，不该再加一次"


def test_budget_and_cooldown(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    # 记满额度后必须拒绝
    for _ in range(8):
        F.note_switch("backstop:app_ctrip", "ctrip",
                      user_data_dir=str(tmp_path))
    app, why = F.plan_backstop("app_ctrip", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "", why


def test_main_wires_both_directions():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "_backstop" in src, "main 没接反补"
    assert "plan_backstop" in src
    assert "_blk_map" in src, "必须用 pacing 真账判定被拦（文件里没墙也会被拦）"


# ---- merged from tests/test_r1063_app_check.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _xml(*texts):
    return "<hierarchy>" + "".join(
        '<node text="%s" />' % t for t in texts) + "</hierarchy>"


def test_classify_logged_in_by_markers():
    r = AC.classify(_xml("会员", "积分", "机票", "酒店"))
    assert r["state"] == "logged_in", r
    assert "会员" in r["in_markers"]


def test_classify_login_page_by_hard_markers():
    r = AC.classify(_xml("手机验证码登录", "请输入手机号", "获取验证码",
                         "账号密码登录"))
    assert r["state"] == "login_page", r
    assert r["hard"], "硬登录标记必须被识别（避免把登录页判成已登录）"


def test_classify_unknown_when_no_markers():
    assert AC.classify(_xml("首页", "搜索"))["state"] == "unknown"


def test_classify_empty():
    assert AC.classify("")["state"] == "empty"


def test_fix_wall_clears_file_and_memo(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    import json
    d = tmp_path / "app_ctrip"
    d.mkdir(parents=True, exist_ok=True)
    (d / "login_wall.json").write_text(
        json.dumps({"until": 9e9, "detail": "需登录"}), encoding="utf-8")
    assert AC.fix_wall(str(tmp_path), "app_ctrip") is True
    assert not (d / "login_wall.json").exists()


def test_snapshot_written_on_login_note():
    """记 login 时要落盘界面快照（否则只能猜是登录墙还是误判）。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    assert "app_login_fail_" in src
    assert "_last_dev" in src, "取不到设备句柄就抓不到 dump"
    i = src.index("app_login_fail_")
    seg = src[max(0, i - 600):i + 400]
    assert "_all[:-6]" in src or "只留最近 6 份" in src, "快照必须有保留上限"


# ---- merged from tests/test_r1063_app_fallback.py ----

@pytest.fixture(autouse=True)
def _clean():
    from core import strategy_params as sp
    sp.invalidate()
    yield
    sp.invalidate()


def test_app_counterpart_is_derived_not_hardcoded():
    """孪生映射从渠道注册表派生：新增第 11 家不需要改这里。"""
    assert fo.app_counterpart("ctrip") == "app_ctrip"
    assert fo.app_counterpart("qunar") == "app_qunar"
    assert fo.app_counterpart("tongcheng") == "app_tongcheng"
    # 途牛没有 App 渠道：如实返回空，不编一个
    assert fo.app_counterpart("tuniu") == ""
    # App 渠道自身没有"孪生的孪生"
    assert fo.app_counterpart("app_ctrip") == ""
    assert fo.app_counterpart("") == ""


def test_only_behavior_challenges_trigger_a_switch():
    """图像型（滑块/点选）先自己解，解不动才谈换道——不要一开始就换。"""
    assert fo.is_behavior_block("captcha") is True
    assert fo.is_behavior_block("ip") is True
    assert fo.is_behavior_block("slider") is False
    assert fo.is_behavior_block("click") is False
    assert fo.is_behavior_block("") is False


def test_plan_switch_happy_path(tmp_path):
    app, why = fo.plan_switch("ctrip", "captcha", {},
                             user_data_dir=str(tmp_path))
    assert app == "app_ctrip", why
    assert "行为型" in why


def test_plan_switch_respects_switch_off(tmp_path):
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"app_fallback.enabled": False}}}})
    app, why = fo.plan_switch("ctrip", "captcha", {},
                             user_data_dir=str(tmp_path))
    assert app == "" and "开关已关" in why, why


def test_daily_cap_and_cooldown_prevent_thrashing(tmp_path):
    d = str(tmp_path)
    # 18:13 UTC：+7200s 仍在同一天；旧值 22:13 UTC 在 CI（UTC）会跨日，
    # 每日上限被新一天重置，本机 UTC+8 同一天所以只在 CI 假红。
    now = 1_700_000_000.0 - 4 * 3600
    # ① 默认参数：第一次可以换；换完立刻再问就被冷却挡住（不许 PC→App→PC 横跳）
    app, _ = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d, now=now)
    assert app == "app_ctrip"
    fo.note_switch("ctrip", "app_ctrip", ok=True, user_data_dir=d, now=now)
    app2, why2 = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d,
                                now=now + 60)
    assert app2 == "" and "冷却" in why2, why2

    # ② 每日上限：cap=1、冷却=0 时，用掉一次之后当天不再换。
    #    注意这是**参数层**的读数（`strategy_params.resolve` 优先于 cfg），
    #    所以这里装配置而不是只传 cfg——与面板里改数字是同一条路。
    from core import strategy_params as sp
    sp.set_config({"crawler": {"app_fallback": {"daily_switches": 1,
                                                "cooldown_s": 0},
                               "strategy_overrides": {
                                   "ctrip": {"app_fallback.daily_switches": 1,
                                             "app_fallback.cooldown_s": 0}}}})
    d2 = str(tmp_path / "cap")
    a1, _ = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d2, now=now)
    assert a1 == "app_ctrip"
    fo.note_switch("ctrip", "app_ctrip", ok=True, user_data_dir=d2, now=now)
    a2, why3 = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d2,
                              now=now + 7200)
    assert a2 == "" and "上限" in why3, why3


def test_no_switch_when_app_already_running(tmp_path):
    app, why = fo.plan_switch("ctrip", "captcha", {},
                             user_data_dir=str(tmp_path),
                             running=["ctrip", "app_ctrip"])
    assert app == "" and "已在跑" in why, why


# ---------------- 接线：主循环里真的会起第二波 ----------------

def test_main_actually_runs_a_second_wave():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    assert "from core import failover as _fo" in src, "主循环没接换道模块"
    assert "_blocked[_nm] = _kind0" in src, "没有记录被行为型拦住的渠道"
    assert "plan_switch(" in src and "note_switch(" in src
    # 第二波必须把价格并入本轮，否则"换了也不用"
    assert "all_prices.extend(_pr2 or [])" in src


# ---------------- 提速：预置（本轮就并行，不等整波结束） ----------------

def test_preload_targets_only_behavior_and_returns_mapping(tmp_path):
    scenes = {"ctrip": {"kind": "captcha"}, "qunar": {"kind": "slider"},
              "fliggy": {"kind": ""}}
    got = fo.preload_targets(scenes, {"ctrip", "qunar", "fliggy"}, {},
                             user_data_dir=str(tmp_path))
    assert got == {"ctrip": "app_ctrip"}, got   # 滑块/空都不是行为型


def test_preload_counts_one_switch_per_round_not_per_query(tmp_path):
    """预置按**轮**记一次：按查询数记账会把每日上限瞬间用光。"""
    d = str(tmp_path)
    scenes = {"ctrip": {"kind": "captcha"}}
    got = fo.preload_targets(scenes, {"ctrip"}, {}, user_data_dir=d)
    assert got == {"ctrip": "app_ctrip"}
    led = fo._load(fo.ledger_path(d))
    assert led["ctrip"]["day_used"] == 1, led


def test_preload_respects_daily_cap(tmp_path):
    from core import strategy_params as sp
    sp.set_config({"crawler": {"app_fallback": {"daily_switches": 1,
                                                "cooldown_s": 0}}})
    d = str(tmp_path)
    scenes = {"ctrip": {"kind": "captcha"}}
    assert fo.preload_targets(scenes, {"ctrip"}, {}, user_data_dir=d)
    assert fo.preload_targets(scenes, {"ctrip"}, {}, user_data_dir=d) == {}, \
        "上限用完之后还在预置"


def test_main_preloads_before_the_wave():
    """接线钉子：预置必须在 `get_crawlers(plats)` 之前把 App 孪生加进 plats。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    assert "preload_targets(" in src
    i_pre = src.index("preload_targets(")
    i_plats = src.index("for _src0, _app0 in list((_preload or {}).items()):")
    i_get = src.index("_crawlers = get_crawlers(plats)", i_pre)
    assert i_pre < i_plats < i_get, "预置没有在起波之前生效"
    assert 'rt["pacing"].note_failover(' in src, "换道成效没进快照/面板"


# ---- merged from tests/test_r1063_app_geo.py ----

def test_default_coords_are_shanghai_expo():
    pos = geo.coords_from(None)
    assert pos["name"] == "上海浦东世博片区"
    # 世博片区（中华艺术宫一带）——落在上海行政范围内，且不是出厂默认的加州
    assert 30.9 < pos["lat"] < 31.5, pos
    assert 121.2 < pos["lon"] < 121.8, pos


def test_config_can_override_and_disable():
    pos = geo.coords_from({"android": {"geo": {"lat": 31.2, "lon": 121.5,
                                               "name": "自定义"}}})
    assert (pos["lat"], pos["lon"], pos["name"]) == (31.2, 121.5, "自定义")
    assert geo.coords_from({"android": {"geo": {"enabled": False}}}) == {}


def test_bad_coords_fall_back_to_default():
    pos = geo.coords_from({"android": {"geo": {"lat": "abc", "lon": ""}}})
    assert pos["lat"] == geo.SHANGHAI_EXPO["lat"], pos


class _FakeDev:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def sh(self, *args, **kw):
        self.calls.append(" ".join(str(a) for a in args))
        if self.fail:
            raise RuntimeError("adb 挂了")
        return "OK"


def test_fix_sends_lon_lat_order_and_enables_providers():
    """`geo fix` 是**经度在前**（历史顺序），写反了会钉到海里。"""
    dev = _FakeDev()
    rep = geo.fix(dev, {"android": {"geo": {"enabled": True}}})
    assert rep["ok"] is True, rep
    joined = " | ".join(dev.calls)
    assert "geo fix 121.4921 31.1874" in joined, joined
    assert "location_mode 3" in joined, joined


def test_fix_never_blocks_when_adb_fails():
    dev = _FakeDev(fail=True)
    rep = geo.fix(dev, None)
    assert rep["ok"] is False
    assert rep.get("detail")


def test_disabled_means_no_device_traffic():
    dev = _FakeDev()
    rep = geo.fix(dev, {"android": {"geo": {"enabled": False}}})
    assert rep.get("skipped") is True
    assert dev.calls == [], dev.calls


def test_app_base_pins_geo_before_each_query():
    """接线钉子：设备准备流程里必须有 ensure_geo（漏了等于没有定位）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "app_base.py"),
        encoding="utf-8").read()
    assert "def ensure_geo(self, dev)" in src
    assert "self.ensure_geo(dev)" in src
    i = src.index("self._refresh_vendor_props(dev)")
    j = src.index("self.ensure_geo(dev)")
    assert abs(j - i) < 400, "ensure_geo 没挂在设备准备那段里"


def test_example_config_ships_the_geo_block():
    """新装即带（零配置）：示例配置里必须有 android.geo。"""
    import yaml
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "config.example.yaml")
    cfg = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    g = (cfg.get("android") or {}).get("geo") or {}
    assert g.get("enabled") is True, g
    assert g.get("lat") and g.get("lon"), g


# ---- merged from tests/test_r1063_app_horizon_harvest.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_horizon_is_configurable():
    import logging

    from crawlers import REGISTRY
    cls = REGISTRY["app_ctrip"]
    log = logging.getLogger("t")
    assert cls({}, log)._horizon_days() == 62, "默认必须保持既有行为"
    assert cls({"app_date_horizon_days": 120}, log)._horizon_days() == 120
    assert cls({"app_date_horizon_days": 120,
                "app_date_horizon_days_map": {"app_ctrip": 200}},
               log)._horizon_days() == 200, "按渠道优先"
    # 越界值不接受（防手滑写成 0 或天文数字）
    assert cls({"app_date_horizon_days": 0}, log)._horizon_days() == 62


def test_horizon_reject_uses_config():
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    i = src.index("def reject_far_dates")
    seg = src[i:i + 900]
    assert "_horizon_days()" in seg, "守卫必须用可配置视野，不能再用写死的常量"


def test_zhixing_calendar_harvests_whole_window():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert "app_calendar_harvest_all" in src
    assert "app_calendar_harvest_cap" in src
    i = src.index("_extra_days")
    seg = src[i - 600:i + 600]
    assert "另含" in src, "要在 detail 里如实标注非订阅日期"
    # 无价格子不该被算成"收了"
    assert 'price is None' in seg


# ---- merged from tests/test_r1063_app_risk_visible.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mark_login_wall_records_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import degraded as dg
    with dg._LOCK:
        dg._STATE.clear()

    from crawlers import app_base
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    # 结构保证：记账发生在 mark_login_wall 里
    i = src.index("def mark_login_wall")
    seg = src[i:i + 700]
    assert "app_risk_blocked" in seg, seg[:300]
    assert "degraded" in seg


def test_degraded_cap_is_known(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import degraded as dg
    with dg._LOCK:
        dg._STATE.clear()
    dg.note("app_risk_blocked", "app_fliggy", "需登录（119 分钟内不再重试）")
    snap = dg.snapshot()
    assert "app_risk_blocked" in snap
    assert snap["app_risk_blocked"]["n"] == 1


def test_panel_has_label_and_advice():
    w = webui_full_src()
    assert "app_risk_blocked:'App 风控'" in w
    assert "改用同名的浏览器通路" in w


# ---- merged from tests/test_r1063_app_slider.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REAL = (
    '<hierarchy>'
    '<node text="验证码拦截" class="android.webkit.WebView" '
    'bounds="[0,68][1260,2800]"/>'
    '<node text="亲，请拖动下方滑块完成验证" bounds="[334,1451][928,1508]"/>'
    '<node text="通过验证以确保正常访问" bounds="[0,1523][1260,1577]"/>'
    '<node text="滑块" bounds="[203,1644][385,1779]"/>'
    '<node text="向右滑动验证" bounds="[189,1630][1058,1788]"/>'
    '</hierarchy>'
)


def test_detects_the_real_fliggy_slider_page():
    assert appvcode.is_slider_page(REAL) is True


def test_normal_page_is_not_a_slider():
    assert appvcode.is_slider_page(
        '<hierarchy><node text="航班列表" bounds="[0,0][10,10]"/></hierarchy>'
    ) is False
    assert appvcode.is_slider_page("") is False


def test_geometry_uses_handle_and_track_ends():
    geo = appvcode.slider_geometry(REAL)
    assert geo is not None
    assert geo["from"][0] < geo["to"][0], geo
    assert geo["distance"] > 400, geo
    # 轨道右端要留一点余量（贴边容易被判"没滑到位/滑过头"）
    assert geo["to"][0] <= 1058, geo


def test_human_path_is_monotonic_with_jitter():
    pts = appvcode.human_path(294, 1712, 1045, steps=40, seed=7)
    xs = [p[0] for p in pts]
    assert len(pts) >= 40
    assert xs == sorted(xs), "轨迹必须单调向右"
    assert pts[-1][0] == 1045, "末点必须精确落到轨道右端"
    # y 轴要有抖动（直线是最容易被判机器的特征之一）
    assert len({p[1] for p in pts}) > 1


def test_reports_platform_error_code_when_blocked():
    """平台自报 error 码要原样带回，才能区分"轨迹被识别"与"位置不对"。"""

    class _Dev:
        def __init__(self):
            self.n = 0

        def dump(self):
            self.n += 1
            if self.n == 1:
                return REAL
            return REAL.replace("向右滑动验证", "请点我重试(error:x2VW8)")

        def u2_swipe_points(self, pts, dur=1.0):
            return True

    rep = appvcode.solve(_Dev(), tries=1)
    assert rep["ok"] is False
    assert "x2VW8" in rep["why"], rep


def test_marks_success_when_page_changes():
    class _Dev:
        def __init__(self):
            self.n = 0

        def dump(self):
            self.n += 1
            if self.n == 1:
                return REAL
            return ('<hierarchy><node text="机票" bounds="[0,0][10,10]"/>'
                    '<node text="航班查询" bounds="[0,0][10,10]"/></hierarchy>')

        def u2_swipe_points(self, pts, dur=1.0):
            return True

    rep = appvcode.solve(_Dev(), tries=2)
    assert rep["ok"] is True and rep["tries"] == 1, rep


def test_never_raises_on_broken_device():
    class _Bad:
        def dump(self):
            raise RuntimeError("boom")

    rep = appvcode.solve(_Bad(), tries=1)
    assert rep["ok"] is False

    class _NoGeo:
        def dump(self):
            return "<hierarchy></hierarchy>"

        def u2_swipe_points(self, pts, dur=1.0):
            return True

    assert appvcode.solve(_NoGeo(), tries=1)["ok"] is False


def test_wired_into_clear_blockers_for_every_app_channel():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "app_base.py"), encoding="utf-8").read()
    assert "appvcode.is_slider_page" in src
    assert 'path_note(\n                    "app-captcha"' in src or \
        '"app-captcha"' in src


# ---- merged from tests/test_r1063_app_version_guard.py ----

class _Dev:
    """假设备：只实现 `_sh("shell", cmd)`（与真实 AdbDevice 同形状）。"""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def _sh(self, *args, timeout=None):
        self.calls.append(" ".join(str(a) for a in args))
        cmd = " ".join(str(a) for a in args)
        for pkg, txt in self.table.items():
            if pkg in cmd:
                return txt
        return ""


def _dumpsys(name, code, upd="2026-11-08 08:54:18"):
    return ("Packages:\n  Package [com.x]:\n"
            "    versionCode=%d minSdk=24 targetSdk=30\n"
            "    versionName=%s\n"
            "    lastUpdateTime=%s\n" % (code, name, upd))


def test_reads_versions_from_dumpsys():
    dev = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.2", 710262),
                "com.taobao.trip": _dumpsys("10.0.10.104", 8100723)})
    got = av.read_versions(dev, ["cn.suanya.zhixing", "com.taobao.trip",
                                 "com.nonexistent"])
    assert got["cn.suanya.zhixing"]["name"] == "10.26.2"
    assert got["cn.suanya.zhixing"]["code"] == 710262
    assert got["cn.suanya.zhixing"]["updated"].startswith("2026-11-08")
    assert "com.nonexistent" not in got, "查不到的包不能凭空记录"
    assert any("dumpsys package" in c for c in dev.calls)


def test_first_run_only_records_a_baseline():
    d = tempfile.mkdtemp()
    dev = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.2", 710262)})
    rep = av.check(dev, ["cn.suanya.zhixing"], root=d,
                   plat_of=lambda p: "app_zhixing")
    assert rep["ok"] and rep["changed"] == {}, "首次记录不算升级"
    assert os.path.exists(av._state_path(d))


def test_upgrade_is_detected_and_recorded():
    d = tempfile.mkdtemp()
    old = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.1", 710261)})
    av.check(old, ["cn.suanya.zhixing"], root=d)
    new = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.2", 710262)})
    rep = av.check(new, ["cn.suanya.zhixing"], root=d,
                   plat_of=lambda p: "app_zhixing")
    assert list(rep["changed"]) == ["cn.suanya.zhixing"], rep
    ch = rep["changed"]["cn.suanya.zhixing"]
    assert ch["old"]["name"] == "10.26.1" and ch["new"]["name"] == "10.26.2"
    from core import degraded as dg
    snap = dg.snapshot()
    assert "app_upgrade" in snap, snap
    assert "10.26.1 → 10.26.2" in snap["app_upgrade"]["last"]
    dg.reset()


def test_layout_risk_needs_two_consecutive_bad_rounds():
    d = tempfile.mkdtemp()
    assert av.note_layout_risk("app_zhixing", rows=0, path="unknown",
                               root=d) is False
    assert av.note_layout_risk("app_zhixing", rows=0, path="unknown",
                               root=d) is True
    from core import degraded as dg
    assert "app_layout" in dg.snapshot()
    dg.reset()


def test_layout_risk_clears_when_data_comes_back():
    d = tempfile.mkdtemp()
    av.note_layout_risk("app_zhixing", rows=0, path="unknown", root=d)
    av.note_layout_risk("app_zhixing", rows=3, path="航班明细", root=d)
    # 计数应被清零：再来一次"坏轮"只是第 1 次
    assert av.note_layout_risk("app_zhixing", rows=0, path="unknown",
                               root=d) is False


def test_broken_state_file_never_raises():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "device"), exist_ok=True)
    with open(av._state_path(d), "w", encoding="utf-8") as f:
        f.write("{ 不是 json")
    dev = _Dev({"com.x": _dumpsys("1.0", 1)})
    rep = av.check(dev, ["com.x"], root=d)
    assert rep["ok"], rep
    with open(av._state_path(d), encoding="utf-8") as f:
        json.load(f)                    # 已被重写成合法 JSON


def test_main_and_setup_are_wired():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
    setup = io.open(os.path.join(root, "core", "setup_check.py"),
                    encoding="utf-8").read()
    assert "appversion" in main and "note_layout_risk" in main
    assert "AndroidRuntime" in setup, "自检必须走真实设备层（别再误报没连到设备）"
    assert "launch_emulator" in setup and "restart_emulator" in setup


def test_emulator_module_exposes_lifecycle():
    from core.android import emulator as em
    for fn in ("status", "ensure_running", "restart"):
        assert callable(getattr(em, fn, None)), fn

_UI_OK = ('<hierarchy><node text="机票"/><node text="出发"/><node text="到达"/>'
          '<node text="搜索"/><node text="往返"/><node text="国内"/>'
          '<node text="国际"/></hierarchy>')
_UI_BAD = ('<hierarchy><node text="酒店"/><node text="火车票"/>'
           '<node text="我的"/></hierarchy>')


def test_probe_anchors_reports_hit_rate():
    """升级后"界面还认不认得"要能量出来（真机：智行 10.26.2 命中 7/7）。"""
    ok = av.probe_anchors(None, "app_zhixing", xml=_UI_OK)
    assert ok["rate"] == 1.0 and ok["missing"] == [], ok
    bad = av.probe_anchors(None, "app_zhixing", xml=_UI_BAD)
    assert bad["rate"] < 0.6 and bad["missing"], bad
    from core import degraded as dg
    assert "app_layout" in dg.snapshot(), "命中率太低要记疑似改版"
    dg.reset()


def test_probe_anchors_handles_empty_tree():
    rep = av.probe_anchors(None, "app_zhixing", xml="")
    assert rep["ok"] is False and "UI" in str(rep.get("why") or "")


def test_probe_uses_content_desc_too():
    xml = ('<hierarchy><node content-desc="机票"/><node content-desc="出发"/>'
           '<node content-desc="到达"/><node content-desc="搜索"/>'
           '<node content-desc="往返"/><node content-desc="国内"/>'
           '<node content-desc="国际"/></hierarchy>')
    assert av.probe_anchors(None, "app_zhixing", xml=xml)["rate"] == 1.0


# ---- merged from tests/test_r1063_dump_u2_fast.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _dev(**kw):
    d = object.__new__(AdbDevice)
    d.adb_path = ""
    d.serial = "1.2.3.4:5555"
    d.timeout = 5
    d.last_error = ""
    d._u2_conn = None
    d._u2_first = True
    d._prefer_u2 = False
    d.calls = []
    d._sh = lambda *a, **_k: (d.calls.append(a), "")[1]
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_dump_prefers_u2_and_reuses_connection():
    d = _dev()
    connects = []
    xml = "<hierarchy><node text=\"x\"/></hierarchy>"

    class _Conn:
        def dump_hierarchy(self):
            return xml

    def _fake_u2_device():
        if d._u2_conn is None:
            connects.append(1)
            d._u2_conn = _Conn()
        return d._u2_conn

    d._u2_device = _fake_u2_device
    assert d.dump() == xml
    assert d.dump() == xml
    assert d.dump() == xml
    assert len(connects) == 1, "连接必须复用（实测省下的正是连接开销）"
    assert not d.calls, "u2 可用时不该再去跑 CLI"


def test_falls_back_to_cli_when_u2_unavailable():
    d = _dev()
    d.dump_u2 = lambda: ""
    d.dump()
    assert any("uiautomator" in " ".join(a) for a in d.calls), d.calls
    assert d._u2_first is False, "u2 不可用后本会话不再每轮白试"


def test_u2_connection_is_dropped_on_error():
    d = _dev()

    class _Boom:
        def dump_hierarchy(self):
            raise RuntimeError("agent 挂了")

    d._u2_conn = _Boom()
    d._u2_device = lambda: d._u2_conn
    assert d.dump_u2() == ""
    assert d._u2_conn is None, "坏连接必须丢掉，下一轮重建"
    assert "u2 dump" in d.last_error


def test_u2_dump_rejects_non_hierarchy():
    d = _dev()

    class _Junk:
        def dump_hierarchy(self):
            return "not xml"

    d._u2_conn = _Junk()
    d._u2_device = lambda: d._u2_conn
    assert d.dump_u2() == ""


def test_source_keeps_cli_path_intact():
    """CLI 老路径必须一字不动地留着（u2 在不支持的设备上要能兜住）。"""
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "core", "android", "device.py"), encoding="utf-8").read()
    assert "uiautomator\", \"dump\"" in src
    assert "_u2_first" in src and "_u2_conn" in src


# ---- merged from tests/test_r1063_emulator_geo_status.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeMgr:
    def __init__(self, *, running=True, available=True, launch_ok=True):
        self.running = running
        self._available = available
        self.launch_ok = launch_ok
        self.calls = []
        self.adb_path = "adb-fake"
        self.manager_path = "fake.exe"

    def available(self):
        return self._available

    def info(self, vm=None):
        return {"is_android_started": self.running,
                "is_process_started": self.running,
                "player_state": "start_finished" if self.running else "closed",
                "adb_host_ip": "127.0.0.1", "adb_port": 16384,
                "android_version": "15.0", "pid": 1}

    def adb_serial(self, vm=None):
        return "127.0.0.1:16384"

    def launch(self, vm=None):
        self.calls.append("launch")
        self.running = self.launch_ok
        return self.launch_ok

    def shutdown(self, vm=None):
        self.calls.append("shutdown")
        return True

    def restart(self, vm=None):
        self.calls.append("restart")
        return True


@pytest.fixture()
def fake(monkeypatch):
    mgr = _FakeMgr(running=True)
    monkeypatch.setattr(em, "_mgr", lambda cfg=None, **kw: mgr)
    monkeypatch.setattr(em, "_adb_visible", lambda *a, **kw: True)
    return mgr


def test_status_reads_the_real_fields(fake):
    st = em.status({"android": {}})
    assert st["available"] and st["running"] and st["state"] == "start_finished"
    assert st["adb"] == "127.0.0.1:16384" and st["adb_path"] == "adb-fake"


def test_ensure_running_is_a_noop_when_already_up(fake):
    rep = em.ensure_running({"android": {}}, wait_s=1)
    assert rep["ok"] and rep["launched"] is False
    assert "launch" not in fake.calls, "已经在跑就不许再发启动指令"


def test_ensure_running_launches_when_down(monkeypatch, fake):
    fake.running = False
    rep = em.ensure_running({"android": {}}, wait_s=5, poll_s=0.01)
    assert rep["ok"] and rep["launched"] is True, rep
    assert "launch" in fake.calls


def test_restart_calls_restart_and_waits(fake):
    rep = em.restart({"android": {}}, wait_s=5)
    assert rep["ok"] and rep.get("restarted") is True
    assert "restart" in fake.calls


def test_unavailable_manager_is_reported_not_swallowed(monkeypatch):
    mgr = _FakeMgr(available=False)
    monkeypatch.setattr(em, "_mgr", lambda cfg=None, **kw: mgr)
    st = em.status({"android": {}})
    assert st["available"] is False
    assert "MuMuManager" in str(st.get("why") or "")
    rep = em.ensure_running({"android": {}}, wait_s=1)
    assert rep["ok"] is False and rep["why"]


def test_setup_check_actions_are_safe_listed():
    from core import setup_check as sc
    for act in ("launch_emulator", "restart_emulator"):
        assert act in sc.SAFE_ACTIONS, act


class _GeoDev:
    def __init__(self, mode="3", prov="+gps,+network", last="last location=null"):
        self.mode, self.prov, self.last = mode, prov, last
        self.calls = []

    def _sh(self, *args, timeout=None):
        cmd = " ".join(str(a) for a in args)
        self.calls.append(cmd)
        if "location_mode" in cmd:
            return self.mode
        if "providers_allowed" in cmd:
            return self.prov
        if "dumpsys location" in cmd:
            return self.last
        return "OK"


def test_geo_status_distinguishes_never_requested_from_not_set():
    st = geo.status(_GeoDev(), {"android": {"geo": {"enabled": True}}})
    assert st["mode"] == "3" and "gps" in st["providers"]
    assert st["verdict"] == "未请求过（正常）"
    assert st["ok"] is True, "没有应用请求过定位 == 正常，不是失败"


def test_geo_status_flags_a_really_off_provider():
    st = geo.status(_GeoDev(mode="0", prov=""), {"android": {}})
    assert st["verdict"] == "无法确认"
    assert st["ok"] is False


def test_geo_status_sees_a_real_fix():
    st = geo.status(_GeoDev(last="last location=Location[gps 31.187400,121.492100]"),
                    {"android": {}})
    assert st["verdict"] == "已设置" and st["ok"] is True


# ---- merged from tests/test_r1063_reset_app_api.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()

START = 'elif self.path == "/api/channel/reset-app":'


def _seg():
    i = SRC.index(START)
    j = SRC.index('elif self.path == "/api/push":', i)
    return SRC[i:j]


def test_route_exists_and_before_push():
    assert START in SRC
    assert SRC.index(START) < SRC.index('elif self.path == "/api/push":')


def test_three_guards_in_order():
    seg = _seg()
    i_unknown = seg.index('"未知渠道"')
    i_apponly = seg.index("_APP_CHANNELS")
    i_confirm = seg.index('need_confirm')
    assert i_unknown < i_apponly < i_confirm, "闸门顺序必须由粗到细"


def test_confirm_is_required_and_explained():
    seg = _seg()
    assert 'body.get("confirm")' in seg
    assert "破坏性操作" in seg and "登录态" in seg


def test_clears_login_wall_memo_after_success():
    """清完数据必须清登录墙记忆，否则窗口内不会重试，看起来像"清了没用"。

    r1063 T131 起统一走 `_clear_login_wall_memo()`（连 `app_gone` 熔断一起清），
    所以这里断言"调用该函数"而不是断言内联的 service_state 调用——
    实现细节变了，但**契约没变**（成功清数据后必须清墙）。
    """
    seg = _seg()
    assert "_clear_login_wall_memo" in seg, \
        "清完 App 数据后必须清登录墙记忆（T131 起统一走该函数）"


def test_only_app_channels_allowed():
    seg = _seg()
    assert 'plat not in _APP_CHANNELS' in seg
    assert "只有 App 渠道" in seg


def test_uses_pm_clear_with_package_from_registry():
    seg = _seg()
    assert '"pm", "clear"' in seg or '"pm",' in seg
    assert 'getattr(_REG.get(plat), "package"' in seg


# ---- merged from tests/test_r646_app_login_records_intervention.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_app_login_finish_writes_a_relogin_intervention():
    import webui
    from core.storage import PriceStorage

    tmp = tempfile.mkdtemp(prefix="r646t_")
    cfg = os.path.join(tmp, "config.yaml")
    base = {"users": [], "web": {"port": 0, "host": "127.0.0.1"},
            "schedule": {"interval_minutes": 30},
            "output": {"db_path": os.path.join(tmp, "prices.db")}}
    _io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump(base, allow_unicode=True))

    st = webui._State
    st.cfg = dict(base)
    st.boot_cfg = dict(base)
    st.users = []
    st.alerters = []
    st.job = None
    st.report_push = None
    st.reload_cb = None
    st.config_path = cfg
    st.version = "r646"
    st.login_saved_cb = None
    st.logger = logging.getLogger("r646t")
    st.app_login = None
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False

    class _FakeSess:
        status = "pending"

        def finish(self, ok, msg):
            self.status = "done"

    class _FakeReg:
        def __init__(self):
            self.s = _FakeSess()

        def get(self, plat):
            return self.s

        def drop(self, plat):
            pass

    reg = _FakeReg()
    old_reg = webui._app_login_registry
    old_ctx = webui._app_login_ctx
    webui._app_login_registry = lambda: reg
    webui._app_login_ctx = lambda: {
        "packages": {"app_zhixing": "cn.suanya.zhixing"},
        "runtime_factory": lambda: None, "verify": None, "snapshot": None}

    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/app-login/finish" % port,
            data=json.dumps({"plat": "app_zhixing"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
                body = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            code = e.code
            body = json.loads(e.read().decode())
        assert code == 200 and body.get("ok"), (
            "App 登录完成接口没有成功：%s %s" % (code, body))

        rows = PriceStorage(base["output"]["db_path"]).interventions(
            "app_zhixing", 5)
        acts = [(r.get("action"), r.get("scope")) for r in rows]
        # r813d：scope 按渠道记（app_zhixing / app_qunar），不再合并成 app。
        # 两个 App 的重登成功率必须可区分，否则去哪儿 App 会被标成智行。
        assert ("relogin", "app_zhixing") in acts, (
            "App 登录成功后没有入干预账（不可溯源、干预成功率算不到）：%s"
            % acts)
        assert ("relogin", "app") not in acts, (
            "App 登录又退回共享 scope=app：两个 App 的干预成功率会被合并：%s"
            % acts)
    finally:
        srv.shutdown()
        srv.server_close()
        webui._app_login_registry = old_reg
        webui._app_login_ctx = old_ctx
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)


# ---- merged from tests/test_r654_app_intervention_parity.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_diag_platforms_includes_enabled_app_channel():
    """用户启用了 App 渠道时，诊断卡要覆盖它（才有自检入口）。"""
    import webui
    got = webui._diag_platforms(["app_zhixing"])
    assert "app_zhixing" in got, got
    # 默认 5 家仍在
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert p in got, got


def test_diag_platforms_excludes_unconfigured_app_channel():
    """没启用 App 渠道时不能多出一张「本轮未扫描」的空卡。"""
    import webui
    got = webui._diag_platforms([])
    assert "app_zhixing" not in got, got


def test_cadence_ui_covers_app_channel():
    """节流面板的「最小间隔」要能为 App 渠道生成控件。"""
    w = _w()
    i = w.index("glbCad_")
    seg = w[i - 200:i + 1200]
    assert "APP_PLAT_NAME" in seg, "节流面板仍是写死 5 家，App 配不到节奏"
    assert "'glbCad_'+p" in seg, seg[:200]


def test_cadence_save_accepts_app_channel():
    """保存侧白名单必须含 App 渠道，否则界面上填了会被静默丢弃。

    实测踩过：界面已经为「智行 App」生成了节奏控件，但保存循环只放行
    5 家浏览器渠道——用户填 45 分钟、保存后仍是 0，且不报任何错。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    w = _w()
    i = w.index("_cad_ok")
    seg = w[i - 400:i + 400]
    assert "APP_CHANNELS" in seg, "保存侧白名单没接 App 渠道"
    assert "BROWSER_CHANNELS" in seg, seg[:200]
    # 与清单同源（不是又抄一份字面量）
    assert "from core.channels import" in seg or "core.channels" in seg
    assert set(APP_CHANNELS) and set(BROWSER_CHANNELS)


# ---- merged from tests/test_r805bo_app_login_expired.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _db(tmp_path, rows):
    p = tmp_path / "prices.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE fetch_paths (platform TEXT, entry_path TEXT,"
              " path_status TEXT, rows INTEGER, note TEXT, fetched_at TEXT)")
    for i, (st, n, note) in enumerate(rows):
        c.execute("INSERT INTO fetch_paths VALUES (?,?,?,?,?,datetime('now'))",
                  ("app_qunar", "航班明细", st, n, note))
    c.commit()
    c.close()
    return str(p)


def _call(monkeypatch, db):
    import webui
    monkeypatch.setattr(webui._State, "cfg", {"output": {"db_path": db}})
    return webui._app_login_expired("app_qunar")


def test_login_evidence_marks_expired(monkeypatch, tmp_path):
    db = _db(tmp_path, [("timeout", 0, "set-city-dep"),
                        ("login", 0, "需要手机号登录")])
    assert _call(monkeypatch, db) is True


def test_snapshot_invalid_note_marks_expired(monkeypatch, tmp_path):
    db = _db(tmp_path, [("ok", 0,
                         "登录态恢复（非取数）：已恢复快照；快照已失效（仍停在登录墙，需重新登录）")])
    assert _call(monkeypatch, db) is True


def test_recent_rows_mean_available(monkeypatch, tmp_path):
    db = _db(tmp_path, [("ok", 3, "3 条真实航班/时刻/价格"),
                        ("login", 0, "旧的登录墙")])
    assert _call(monkeypatch, db) is False


def test_empty_ledger_is_not_flagged(monkeypatch, tmp_path):
    db = _db(tmp_path, [])
    assert _call(monkeypatch, db) is False


def test_api_and_card_carry_needs_login():
    api = io.open(os.path.join(ROOT, "core", "android", "login_api.py"),
                  encoding="utf-8").read()
    assert '"needs_login"' in api, "接口没下发 needs_login"
    ui = webui_full_src()
    assert '"needs_login": _needs_login' in ui, "ctx 没把账本证据接进去"
    assert "needs_login:!!a.needs_login" in ui, "App 槽位没带 needs_login"
    assert "s.needs_login?'login_required'" in ui, (
        "卡片没有把 needs_login 翻成「需登录」")


# ---- merged from tests/test_r942_app_global_auth.py ----

def _open_health(page):
    _goto(page, "#health")
    page.wait_for_timeout(500)








def test_app_is_not_unknown_to_intervention_endpoints():
    src = _src()
    assert "_ALL_PLATS = tuple(PLATFORMS) + tuple(_APP_CHANNELS)" in src, (
        "可干预端点没有从渠道全集派生")
    assert src.count("plat not in _ALL_PLATS") >= 4, (
        "解除/自检/验证/预热仍有端点只认浏览器渠道")
    assert "plat not in PLATFORMS" not in src, (
        "仍有端点把 App 当未知渠道")






def test_srx_links_cover_app_with_explicit_no_web_landing():
    """检索页渠道卡必须覆盖 10 家；App 没有网页落地页时要说清原因。"""
    import webui
    j = webui._srx_links("SHA", "PEK", "2030-01-01")
    by = {x["key"]: x for x in j["links"]}
    for p in ("app_zhixing", "app_qunar", "app_fliggy",
              "app_ctrip", "app_tongcheng"):
        assert p in by, ("检索页渠道卡漏了 %s" % p, sorted(by))
        assert by[p].get("app") and not by[p]["url"], by[p]
        assert "真机" in by[p]["note"], by[p]
    assert "App 无网页落地页" in _src(), "前端仍把 App 写成「本态不供落地页」"


def test_channel_order_and_push_names_cover_all_ten():
    src = _src()
    order = ("const SRX_PLAT_ORDER=['ctrip','qunar','fliggy','tongcheng',"
             "'tuniu',\n 'app_zhixing','app_qunar','app_fliggy',"
             "'app_ctrip','app_tongcheng'];")
    assert order in src, "渠道统一顺序没有覆盖全部 10 家"
    assert "Alerter.plat_cn(channel)" in src, (
        "雷达推送仍用裸渠道 id（app_qunar 这类）")
    assert ".concat((u.platforms||[]).map(p=>platCN(p)))" in src, (
        "明细筛选没有覆盖「已勾选但无数据」的渠道")


def test_search_surface_flatness_sweep():
    """检索页所有装饰性抬升阴影收掉；坏掉的 CSS 值不得回归。"""
    src = _src()
    assert "var(--line)ue)" not in src, "检索页 hero 分隔线仍是坏 CSS"
    for needle in (
        "#searchview .srx-hero-act .srx-btn:hover{background:var(--card);"
        "border-color:transparent;color:var(--blue)}",
        "#searchview .srx-band-h .srx-axis button.on{background:"
        "var(--r-surface);color:var(--r-blue)}",
        "#searchview .srx-mirror .srx-mtab.on{background:var(--r-surface);"
        "color:var(--r-blue)}",
    ):
        assert needle in src, ("检索页仍有装饰阴影", needle)






def _src():
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return webui_full_src()
