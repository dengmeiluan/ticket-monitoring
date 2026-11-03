# -*- coding: utf-8 -*-
"""统一策略层：同一份输入必须得到同一个决定，且不许把链路带崩。

钉住的口径：
  * 默认（没有任何账本）→ healthy / 放行 / 1.0×；
  * **短时冷却归熔断器**，策略层只在 human/rotate 档关闸；pause 档只降速；
  * 登录退避**不关闸**（登录墙要如实记 login 并继续跑）；
  * `blocked` 到期后先进 `rehab`（1.5× + 强制预热），成功一次才转正；
  * 产量差只调速度不调开关（真无票与风控无关）；
  * `snapshot()` / `two_way=True` 不推进状态机。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r913_policy_engine.py -q
"""
import json
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.policy import PolicyEngine, ChannelPolicy  # noqa: E402
from core.yield_stats import YieldLedger             # noqa: E402
from core.riskscore import LoginLedger               # noqa: E402
from crawlers.base import BaseCrawler, SessionBusyError  # noqa: E402

_LOG = logging.getLogger("test_r913")


def _eng(tmp_path, plat="", **cfg):
    """策略引擎。``plat`` 传给 profile —— 账本与状态都落 user_data/<plat>/。"""
    cfg.setdefault("user_data_dir", str(tmp_path))
    return PolicyEngine(cfg, repo_root=".", profile=plat)


def _seed_login(tmp_path, plat, streak=3, device_risk=True, now=1000.0):
    """在 ``<tmp>/<plat>/login_ledger.json`` 里造登录连击（真实路径）。"""
    path = os.path.join(str(tmp_path), plat)
    os.makedirs(path, exist_ok=True)
    ll = LoginLedger(os.path.join(path, "login_ledger.json"))
    for i in range(streak):
        ll.note_result(plat, False, device_risk=device_risk, now=now + i)
    return ll


def _seed_yield(tmp_path, plat, pattern, rows=1):
    """``pattern`` 是 bool 序列：True=成功。"""
    path = os.path.join(str(tmp_path), plat)
    os.makedirs(path, exist_ok=True)
    yl = YieldLedger(os.path.join(path, "yield_stats.json"))
    for ok in pattern:
        yl.note(plat, "pc", ok, rows=rows)
    return yl


# ---------------------------------------------------------------------------
# 1. 默认与档位
# ---------------------------------------------------------------------------
def test_default_is_healthy_and_allow(tmp_path):
    pol = _eng(tmp_path, "ctrip").decide("ctrip", now=1000.0)
    assert pol.state == "healthy" and pol.allow is True
    assert pol.pace_factor == 1.0 and pol.need_warmup is False
    assert pol.rotate is False and pol.wait_s(now=1000.0) == 0


def test_slow_level_degrades_but_allows(tmp_path):
    pol = _eng(tmp_path, "ctrip").decide("ctrip", now=1000.0, captcha=True,
                                         login_wall=True)
    assert pol.allow is True                 # 48 分只是 slow 档
    assert pol.state == "degraded"
    assert pol.pace_factor == 2.5
    assert pol.need_warmup is True


def test_pause_level_slows_to_max_but_still_allows(tmp_path):
    e = _eng(tmp_path, "ctrip")
    pol = e.decide("ctrip", now=1000.0, statuses=[429], soft=True,
                   rate_pressure=True, login_wall=True)
    assert pol.score >= 65
    assert pol.allow is True and pol.state == "degraded"
    assert pol.pace_factor == 3.0            # 短时冷却交给熔断器
    assert any("熔断器" in r for r in pol.reasons)
    assert pol.wait_s(now=1000.0) == 0


def test_human_level_blocks_and_persists(tmp_path):
    e = _eng(tmp_path, "ctrip")
    _seed_login(tmp_path, "ctrip", streak=3, now=1000.0)
    pol = e.decide("ctrip", now=1005.0, identity_score=0, stealth_score=0,
                   captcha=True)
    assert pol.score >= 80, pol.score
    assert pol.allow is False and pol.state == "blocked"
    assert pol.wait_s(now=1005.0) >= 1800
    # 状态落盘：下一轮即使不带信号也必须继续停
    pol2 = e.decide("ctrip", now=1100.0)
    assert pol2.allow is False and pol2.state == "blocked"
    # 到期后进 rehab
    pol3 = e.decide("ctrip", now=1005.0 + 3700)
    assert pol3.allow is True and pol3.state == "rehab"
    assert pol3.pace_factor == 1.5 and pol3.need_warmup is True


def test_login_backoff_degrades_not_blocks(tmp_path):
    _seed_login(tmp_path, "qunar", streak=3, now=1000.0)
    pol = _eng(tmp_path, "qunar").decide("qunar", now=1001.0)
    assert pol.allow is True                  # 不许关闸：登录墙要照记照跑
    assert pol.state == "rehab"
    assert pol.pace_factor >= 1.5
    assert any("登录退避" in r for r in pol.reasons)


# ---------------------------------------------------------------------------
# 2. 产量只调速度
# ---------------------------------------------------------------------------
def test_good_yield_allows_faster(tmp_path):
    _seed_yield(tmp_path, "fliggy", [True] * 40, rows=3)
    pol = _eng(tmp_path, "fliggy").decide("fliggy", now=1000.0)
    assert pol.state == "healthy" and pol.allow is True
    assert pol.pace_factor == 0.8
    assert any("可加频" in r for r in pol.reasons)


def test_bad_yield_degrades_without_blocking(tmp_path):
    _seed_yield(tmp_path, "tuniu", [True] * 3 + [False] * 7)
    pol = _eng(tmp_path, "tuniu").decide("tuniu", now=1000.0)
    assert pol.allow is True                 # 真无票/解析失败不等于被封
    assert pol.state == "degraded"
    assert pol.pace_factor >= 1.5
    assert any("因果链" in r for r in pol.reasons)


def test_few_samples_do_not_move_the_needle(tmp_path):
    _seed_yield(tmp_path, "ctrip", [True] + [False] * 2)
    pol = _eng(tmp_path, "ctrip").decide("ctrip", now=1000.0)
    assert pol.state == "healthy" and pol.pace_factor == 1.0
    assert any("不据此调整" in r for r in pol.reasons)


def test_degraded_is_sticky_for_one_round_then_expires(tmp_path):
    """一轮滑块的证据要留到下一轮，但不能永久粘住。"""
    e = _eng(tmp_path, "qunar")
    # 滑块 + 登录墙 = 48 分 → degraded，余温 60min
    e.decide("qunar", now=1000.0, captcha=True, login_wall=True)
    pol = e.decide("qunar", now=1400.0)              # 不带信号，仍在窗口内
    assert pol.state == "degraded" and pol.pace_factor >= 2.5
    assert any("余温" in r for r in pol.reasons)
    later = e.decide("qunar", now=1000.0 + 3700)     # 窗口过期
    assert later.state == "healthy"


# ---------------------------------------------------------------------------
# 3. 只读查询不推进状态机
# ---------------------------------------------------------------------------
def test_two_way_queries_do_not_write_state(tmp_path):
    e = _eng(tmp_path, "ctrip")
    e.decide("ctrip", now=1000.0, identity_score=0, stealth_score=0,
             captcha=True, two_way=True)
    assert not os.path.isfile(os.path.join(str(tmp_path), "ctrip",
                                           "policy_state.json"))
    snap = e.snapshot(plats=["ctrip", "qunar"], now=1000.0)
    assert set(snap) == {"ctrip", "qunar"}
    assert snap["ctrip"]["allow"] is True     # 没喂信号 → 默认放行
    assert not os.path.isfile(os.path.join(str(tmp_path), "ctrip",
                                           "policy_state.json"))


def test_state_file_is_valid_json(tmp_path):
    e = _eng(tmp_path, "ctrip")
    _seed_login(tmp_path, "ctrip", streak=3, now=1000.0)
    e.decide("ctrip", now=1005.0, identity_score=0, stealth_score=0,
             captcha=True)
    with open(os.path.join(str(tmp_path), "ctrip", "policy_state.json"),
              encoding="utf-8") as f:
        d = json.load(f)
    assert d["ctrip"]["state"] == "blocked"
    assert d["ctrip"]["until"] > 1005.0


# ---------------------------------------------------------------------------
# 4. 接线：闸门 + 关闸轮次不入账
# ---------------------------------------------------------------------------
def _mk(name, runner, cfg):
    class _C(BaseCrawler):
        def fetch(self, fc, tc, dates, ret_date=""):
            return runner(self)
    _C.name = name
    return _C(cfg, _LOG)


def test_gate_blocks_when_state_file_says_blocked(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}
    called = []
    c = _mk("ctrip", lambda s: called.append(1) or [], cfg)
    eng = c._policy()
    _seed_login(tmp_path, "ctrip", streak=3, now=time.time())
    pol = eng.decide("ctrip", now=time.time(), identity_score=0,
                     stealth_score=0, captcha=True)
    assert pol.allow is False
    out = c.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert out == [] and called == []          # fetch 根本没被调用
    assert c.policy_blocked is True
    assert c.last_policy["state"] == "blocked"
    # 关闸轮次不计入爬取率
    assert c._yield_ledger().samples("ctrip") == 0


def test_gate_allows_healthy_channel(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}
    called = []

    def _run(s):
        called.append(1)
        s.path_note("pc", "ok", rows=2)
        return [1, 2]
    c = _mk("ctrip", _run, cfg)
    assert c.safe_fetch("SHA", "NRT", ["2026-11-16"]) == [1, 2]
    assert called == [1] and c.policy_blocked is False
    assert c._yield_ledger().samples("ctrip") == 1


def test_round_feedback_persists_degraded(tmp_path):
    """本轮发生滑块 → 下一轮即使没信号也按降档走（余温窗口内）。"""
    cfg = {"user_data_dir": str(tmp_path)}

    def _run(s):
        s.path_note("pc", "blocked", detail="滑块验证")
        return []
    c = _mk("qunar", _run, cfg)
    c.safe_fetch("SHA", "NRT", ["2026-11-16"])
    with open(os.path.join(str(tmp_path), "qunar", "policy_state.json"),
              encoding="utf-8") as f:
        assert json.load(f)["qunar"]["state"] in ("degraded", "watch")
    pol = c._policy_now(two_way=True)
    assert pol.pace_factor >= 1.5


def test_sleep_scales_with_policy(tmp_path, monkeypatch):
    import crawlers.base as base_mod
    cfg = {"user_data_dir": str(tmp_path), "delay_min": 1, "delay_max": 2}
    c = _mk("ctrip", lambda s: [], cfg)
    seen = []
    monkeypatch.setattr(base_mod.time, "sleep", lambda v: seen.append(v))
    c._sleep()
    assert 1.0 <= seen[-1] <= 2.0                 # healthy → 原区间
    c._policy_cache = (time.time(), ChannelPolicy("ctrip", "degraded",
                                                  True, 0, 2.5))
    for _ in range(20):
        c._sleep()
    assert all(1.0 <= v <= 5.0 for v in seen[1:])  # 上限被放大
    assert max(seen[1:]) > 2.0


def test_policy_gate_switch_disables_blocking(tmp_path):
    """``policy_gate: false`` 要一键回到旧行为，但账本照记。"""
    cfg = {"user_data_dir": str(tmp_path), "policy_gate": "false"}
    called = []

    def _run(s):
        called.append(1)
        s.path_note("pc", "ok", rows=1)
        return [1]
    c = _mk("ctrip", _run, cfg)
    eng = c._policy()
    _seed_login(tmp_path, "ctrip", streak=3, now=time.time())
    eng.decide("ctrip", now=time.time(), identity_score=0, stealth_score=0,
               captcha=True)
    assert c.safe_fetch("SHA", "NRT", ["2026-11-16"]) == [1]
    assert called == [1] and c.policy_blocked is False
    assert c._yield_ledger().samples("ctrip") == 1      # 度量不受开关影响


def test_busy_still_wins_over_policy(tmp_path):
    """抢锁失败仍是 busy：不写账本、不改策略状态。"""
    cfg = {"user_data_dir": str(tmp_path)}

    def _busy(s):
        raise SessionBusyError("busy")
    c = _mk("ctrip", _busy, cfg)
    assert c.safe_fetch("SHA", "NRT", ["2026-11-16"]) == []
    assert c.last_busy is True
    assert c._yield_ledger().samples("ctrip") == 0
    assert not os.path.isfile(os.path.join(str(tmp_path), "ctrip",
                                           "policy_state.json"))
