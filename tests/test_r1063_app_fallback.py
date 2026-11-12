# -*- coding: utf-8 -*-
"""r1063 T22：换跑道（`app_fallback`）——被行为型强风控拦住时改走 App 通路。

为什么这是「提高爬取率」而不是「硬解验证码」：行为型挑战（极验 v4/天御/
reCAPTCHA/人脸）判的是行为分布与环境指纹，通用开源方案拿不到稳定通过；
但同一家渠道的 App 通路是另一套会话与指纹，往往还没被拦。所以这里的动作是
**换跑道**，不是绕过风控。

边界：每日上限 + 冷却，禁止来回横跳（PC 被拦 → App 被拦 → PC 再试只会把
两条路的分一起打低）。
"""
import io
import os

import pytest

from core import failover as fo


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
