# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1064_fail_escalation.py
- tests/test_r1178_err_codes.py
- tests/test_r1185_precise_control_cell.py
- tests/test_r1223_sched_state.py
- tests/test_r1346_tree_snapshot.py
- tests/test_r280_scheduler_relay.py
- tests/test_r282_pool_stable.py
- tests/test_r316_toast_deadzone.py
- tests/test_r322_slim_chain.py
- tests/test_r324_polish.py
- tests/test_r339_bark_ret.py
- tests/test_r339_pulse_gate.py
- tests/test_r339_route_quick.py
- tests/test_r514_stalled_collection_is_not_just_waiting.py
- tests/test_r519_bool_toggle_string_false.py
- tests/test_r654_every_scope_has_a_label.py
- tests/test_r677_emailshot_runs_as_root.py
- tests/test_r805ac_detail_dimension.py
- tests/test_r805au_env_fault_not_channel.py
- tests/test_r919_vendor_api.py
- tests/test_r932_unified_price.py
- tests/test_r942_readonly_props.py
- tests/test_r951_audit_ceiling.py
- tests/test_r953_unknown_not_zero.py
- tests/test_r955_write_marker_unified.py
- tests/test_r960_bootprops_build_id.py
- tests/test_r969_non_attempt_not_a_sample.py
- tests/test_v15122_cabin_guard.py
- tests/test_v295_prov.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.emailshot as emailshot
import core.notifier as N
import core.notifier as _n
import core.pulse as P
import io
import json
import logging
import logging as _lg
import main
import main as M
import os
import pytest
import re
import sqlite3
import sys
import tempfile
import time
import uuid
import zipfile

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from core import err_codes as EC, scheduler as sch, strategy_params as sp, update
from core.alerter import Alerter, _disp_dw
from core.android import bootprops as bp, fingerprint as fp, hardening, stealth as st, vendor
from core.android.fingerprint import PHONE_POOL
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_DIMENSIONS
from core.flightnorm import cabin_clean, cabin_text
from core.models import FlightPrice
from core.pacing import Pacing, parse_pacing
from core.price import CURRENCY_ONLY, is_masked, looks_like_price, parse_price, strip_currency
from core.scheduler import _schedule_next
from core.storage import PriceStorage
from core.yield_stats import INFRA_PATHS, is_non_attempt, is_paced
from datetime import datetime, timedelta
from main import _stable_pool
from types import SimpleNamespace
from unittest import mock


# ---- merged from tests/test_r1064_fail_escalation.py ----

KEY = ("SHA", "BKK", "2026-11-16")


def _pac(floor=120):
    return Pacing({"crawler": {"cadence": {"qunar": floor}}})


def _floor_of(pac, key=KEY):
    """用 0 分钟尝试年龄反推当前生效的 cadence 地板。"""
    pac.note_try("qunar", key, now=time.time() - 1)
    _tier, why = pac.plan_query("qunar", key, 0, days_ahead=10)
    return why


def test_escalates_with_consecutive_failures():
    pac = _pac(120)
    assert "0/120" in _floor_of(pac)
    for _ in range(3):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    assert "0/240" in _floor_of(pac), pac._fail_streak
    for _ in range(3):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    assert "0/480" in _floor_of(pac), pac._fail_streak


def test_success_resets_immediately():
    pac = _pac(120)
    for _ in range(6):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    assert pac._fail_streak.get("qunar") == 6
    pac.observe("qunar", ["ok"], "")
    assert pac._fail_streak.get("qunar") == 0
    assert "0/120" in _floor_of(pac)


def test_soft_reject_does_not_count():
    """软拒是"会话没养熟"，不是渠道坏了，不该升级 cadence。"""
    pac = _pac(120)
    pac.observe("qunar", ["soft_reject"], "软拒 444")
    assert pac._fail_streak.get("qunar", 0) == 0


def test_cap_at_720():
    pac = _pac(600)
    for _ in range(9):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    # 600 × 4 = 2400，但封顶 720
    assert "0/720" in _floor_of(pac), pac._fail_streak


def test_zero_cadence_stays_off():
    """cadence=0 的渠道（如 tongcheng/fliggy）不受升级影响，仍然是 0。"""
    pac = _pac(0)
    for _ in range(6):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    _tier, why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert "渠道节奏" not in why, why


# ---- merged from tests/test_r1178_err_codes.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def test_self_check_is_clean():
    assert EC._self_check() is None, EC._self_check()


def test_every_entry_has_three_actions_and_kind():
    for it in EC.table():
        assert it["kind"] in EC.KINDS, it
        assert len(it["acts"]) == 3, it
        assert it["kind_cn"], it


def test_docs_point_at_real_files():
    """出处必须真的存在——否则"去文档看"就是骗人。"""
    for code, it in EC.ERR_CODES.items():
        doc = it["doc"]
        assert os.path.isfile(os.path.join(ROOT, doc)), \
            "码 %s 的出处不存在：%s" % (code, doc)


def test_recognizes_codes_inside_real_strings():
    """真实的现场串（含前后缀）都要认出来。"""
    cases = [
        ("请点击重试(error:x2VW8)", "x2VW8"),
        ("HTTP 50003 环境存在风险", "50003"),
        ("listFlight 710114/needLogin", "710114"),
        ("userBaseInfo ret=False errcode=22032", "22032"),
        ("HTTP 202 空壳", "202"),
        ("App 被切到 ContainerActivity 白屏", "安全容器"),
    ]
    for raw, want in cases:
        got = EC.explain(raw)
        assert got["code"] == want, (raw, got)


def test_22032_not_confused_with_202():
    """负控：22032 不能被短码 202 抢走。"""
    assert EC.explain("errcode=22032")["code"] == "22032"


def test_unknown_is_honest():
    """负控：没收录的码不许编一个解释出来。"""
    got = EC.explain("some weird error 987654")
    assert got["code"] is None
    assert got["kind"] == "unknown"
    assert len(got["acts"]) == 3
    assert "还没有人翻译过" in got["cn"]


def test_hard_block_is_not_a_retry_challenge():
    """50003 属硬风控：动作里必须出现"冷却/别重试"，不能在教用户连点。"""
    got = EC.explain("50003")
    joined = " ".join(got["acts"])
    assert got["kind"] == "hard_block"
    assert ("冷却" in joined) or ("别再" in joined), joined


# ---- merged from tests/test_r1185_precise_control_cell.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

@pytest.fixture(autouse=True)
def _restore():
    yield
    sp.invalidate()


def _cfg_one_cell_off():
    key = sp.override_key("ctrip", "domestic", "PC")
    return {"crawler": {"strategy_overrides": {
        key: {"path_fallback.enabled": False}}}}


def test_only_that_cell_turns_off():
    sp.set_config(_cfg_one_cell_off())
    p = Pacing()
    assert p._path_enabled("ctrip", "domestic", "PC") is False, "目标格本身没关掉"
    # 邻居一格都不许受影响
    assert p._path_enabled("ctrip", "domestic", "H5") is True, "同渠道另一条通路被误伤"
    assert p._path_enabled("ctrip", "intl", "PC") is True, "同通路另一维度被误伤"
    assert p._path_enabled("fliggy", "domestic", "PC") is True, "另一家渠道被误伤"
    assert p._path_enabled("tongcheng", "domestic", "PC") is True


def test_empty_config_keeps_everything_on():
    """负控：没有覆盖时必须全开（默认启用是行为基线）。"""
    sp.set_config({})
    p = Pacing()
    for plat in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        for path in ("PC", "H5", "H5/API"):
            assert p._path_enabled(plat, "domestic", path) is True, (plat, path)


def test_restore_after_invalidate():
    """把配置撤掉，那一格必须自己恢复——否则"关一格"会变成永久伤。"""
    sp.set_config(_cfg_one_cell_off())
    assert Pacing()._path_enabled("ctrip", "domestic", "PC") is False
    sp.invalidate()
    assert Pacing()._path_enabled("ctrip", "domestic", "PC") is True


def test_override_key_roundtrip_with_slash_path():
    """通路名里带 `/`（真实存在 `H5/API`）也要能拼回去、解回来。"""
    key = sp.override_key("tuniu", "intl", "H5/API")
    assert "/" in key
    assert sp.parse_override_key(key) == ("tuniu", "intl", "H5/API")


# ---- merged from tests/test_r1223_sched_state.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAIN_SRC = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def test_module_state_exists_and_writable():
    assert isinstance(M._SCHED_STATE, dict)
    for k in ("interval_minutes", "jitter_minutes", "backoff_minutes"):
        assert k in M._SCHED_STATE, k
    M._SCHED_STATE["backoff_minutes"] = 7
    assert M._SCHED_STATE["backoff_minutes"] == 7
    M._SCHED_STATE["backoff_minutes"] = 0


def test_accessor_returns_same_object():
    assert M._sched_state_now() is M._SCHED_STATE


def test_backoff_block_no_longer_reads_bare_local():
    i = MAIN_SRC.find("from core.pacing import round_backoff_minutes as _rbm")
    assert i > 0
    seg = MAIN_SRC[i:i + 700]
    assert "_sched_state_now()" in seg, "退避分支没走模块级容器"
    assert "sched_state.get(" not in seg, "仍在读可能未赋值的局部 sched_state"
    assert 'sched_state["backoff_minutes"]' not in seg


def test_round_backoff_is_pure():
    """`round_backoff_minutes` 的语义：**额外**延后分钟数，有界（默认封顶 240）。"""
    from core.pacing import round_backoff_minutes as rb
    assert rb(30, 0, 0) == 0                    # 全绿 → 不延时
    assert rb(30, 1, 0) == 30                   # 1–2 次受阻 → 延后一个间隔
    assert rb(30, 5, 3) == 60                   # ≥3 次受阻 → 延后两个间隔
    assert rb(200, 5, 5) == 240                 # 封顶 240：坏运气不会把监控冻住
    assert rb(0, 5, 5) == 0                     # 间隔为 0 时不延时


# ---- merged from tests/test_r1346_tree_snapshot.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "user_data" / "secret.txt").write_text("不该进快照", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
    (root / "main.py").write_text("V0", encoding="utf-8")
    (root / "webui.py").write_text("W0", encoding="utf-8")
    (root / "core" / "a.py").write_text("A0", encoding="utf-8")
    return root


def test_snapshot_contains_sources_not_userdata(tmp_path):
    root = _proj(tmp_path)
    out = update.snapshot_tree(str(root), tag="t1")
    assert out and os.path.isfile(out), out
    names = set(zipfile.ZipFile(out).namelist())
    assert "main.py" in names and "webui.py" in names and "core/a.py" in names
    assert not any(n.startswith("user_data/") for n in names), names
    assert not any("__pycache__" in n for n in names), names
    assert not any(n.endswith(".pyc") for n in names), names


def test_snapshot_skips_build_outputs(tmp_path):
    """构建产物/安装包不进安全网（本机实测 `_build` 100+MB、根 exe 12MB）。

    不是洁癖：安全网必须**比风险快**。实测未过滤时 12.7GB / >7 分钟，
    过滤后 33MB / 1.5 秒。
    """
    root = _proj(tmp_path)
    (root / "_build").mkdir()
    (root / "_build" / "TicketMonitor.zip").write_bytes(b"x" * 100)
    (root / "build").mkdir()
    (root / "build" / "app.exe").write_bytes(b"x" * 100)
    (root / "TicketMonitor.exe").write_bytes(b"x" * 100)
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("keep", encoding="utf-8")
    out = update.snapshot_tree(str(root), tag="t2")
    names = set(zipfile.ZipFile(out).namelist())
    assert "docs/note.md" in names, names
    assert not any(n.startswith("_build/") for n in names), names
    assert not any(n.startswith("build/") for n in names), names
    assert not any(n.lower().endswith(".exe") for n in names), names
    assert not any(n.lower().endswith(".zip") for n in names), names


def test_apply_makes_tree_snapshot_before_overwrite(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V1")
        zf.writestr("webui.py", "W1")
        zf.writestr("core/a.py", "A1")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty", lambda r: [], raising=False)
    rep = update.apply(str(z), force=True)
    assert rep["ok"] is True, rep
    snaps = [f for f in os.listdir(root / "user_data" / "update" / "treetars")
             if f.endswith(".zip")]
    assert snaps, "升级前没有整树快照"
    p = root / "user_data" / "update" / "treetars" / snaps[0]
    names = zipfile.ZipFile(p).namelist()
    assert "main.py" in names
    # 快照里存的必须是**覆盖前**的内容
    assert zipfile.ZipFile(p).read("main.py") == b"V0"


def test_apply_aborts_when_snapshot_fails(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V1")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty", lambda r: [], raising=False)
    monkeypatch.setattr(update, "snapshot_tree", lambda *a, **k: "")
    rep = update.apply(str(z), force=True)
    assert rep["ok"] is False, rep
    assert "快照失败" in rep["err"], rep
    # 关键：文件一个都没动
    assert (root / "main.py").read_text(encoding="utf-8") == "V0"


def test_prune_keeps_newest_n(tmp_path):
    root = _proj(tmp_path)
    d = root / "user_data" / "update" / "treetars"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        p = d / ("tree_%d.zip" % i)
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    removed = update.prune_tree_snaps(str(root), keep=2)
    left = sorted(os.listdir(d))
    assert len(left) == 2, left
    assert len(removed) == 3, removed
    assert "tree_4.zip" in left, left          # 最新的留下


# ---- merged from tests/test_r280_scheduler_relay.py ----

_TZ = "Asia/Shanghai"


def _mk_sched():
    s = BlockingScheduler(timezone=_TZ)
    s.add_job(lambda: None, trigger=IntervalTrigger(minutes=5),
              id="price_monitor", max_instances=1, coalesce=True,
              next_run_time=None)  # paused——旧形态无人接力即死
    return s


def test_jitter_zero_still_schedules_next():
    """核心复现：jm=0 时也必须排定下次触发（旧实现 job 恒 paused）。"""
    s = _mk_sched()
    nt = _schedule_next(s, {"interval_minutes": 5, "jitter_minutes": 0})
    assert nt is not None, "jm=0 未排定下次触发（死调度）"
    job = s.get_job("price_monitor")
    assert job.next_run_time is not None
    gap = (job.next_run_time - datetime.now(job.next_run_time.tzinfo)
           ).total_seconds()
    assert 240 <= gap <= 301, f"间隔应≈5分钟, 实测 {gap:.0f}s"


def test_jitter_band_honored():
    """jm>0 时接力时刻落在 [iv-jm, iv+jm] 带内。"""
    s = _mk_sched()
    _schedule_next(s, {"interval_minutes": 15, "jitter_minutes": 5})
    job = s.get_job("price_monitor")
    gap = (job.next_run_time - datetime.now(job.next_run_time.tzinfo)
           ).total_seconds()
    assert 595 <= gap <= 1201, f"间隔应∈[10,20]分钟, 实测 {gap:.0f}s"


def test_missing_job_returns_none():
    """job 不存在（未注册）时不抛错、返回 None（防呆与旧 try/except 同义）。"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    s = BlockingScheduler(timezone=_TZ)
    assert _schedule_next(s, {"interval_minutes": 5,
                              "jitter_minutes": 0}) is None


def test_start_without_immediate_scan_schedules_first_run(monkeypatch):
    """关闭启动即扫（含首次空配置）只延后首轮，不能永久暂停监控。"""
    monkeypatch.setattr(BlockingScheduler, "start", lambda self: None)
    monkeypatch.setattr(sch, "SCHED", None)
    calls = []
    sched = sch.run_scheduler(
        lambda: calls.append("scan"),
        {"interval_minutes": 5, "jitter_minutes": 0},
        run_on_start=False)

    assert calls == [], "关闭启动即扫时不应立即采集"
    job = sched.get_job("price_monitor")
    assert job.next_run_time is not None, "首轮必须按周期排定，不能永久暂停"
    gap = (job.next_run_time - datetime.now(job.next_run_time.tzinfo)
           ).total_seconds()
    assert 240 <= gap <= 301, f"首轮应在约5分钟后，实测 {gap:.0f}s"


def test_relay_call_is_unconditional():
    """Soldier Minor-1：wrapped 必须无条件接力——调用点改回参数分支
    （if jm>0）则 _schedule_next 单测仍绿而死调度复发，源码钉锁调用点。"""
    src = open("core/scheduler.py", encoding="utf-8").read()
    assert "_schedule_next(sched, state)" in src, "wrapped 未调用接力"
    assert "if jm > 0" not in src, "接力被参数分支包回（死调度形态复活）"


# ---- merged from tests/test_r282_pool_stable.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _f(flight_no, dpt, art, price, plat, airline="春秋航空"):
    return FlightPrice(platform=plat, from_city="SHA", to_city="HAK",
                       depart_date="2027-01-30", price=price,
                       airline=airline, flight_no=flight_no,
                       depart_time=dpt, arrive_time=art)


# 实录样本：￥1760 同价双班（中转，直挂未标注），价格/合规全同
_TIE = [_f("9C8815", "07:05", "22:00", 1760, "qunar"),
        _f("9C8807", "14:05", "22:00", 1760, "fliggy")]


def test_tie_pair_identity_stable_across_completion_orders():
    # 两渠道完成序互换进池（今轮 fliggy 先、明轮 qunar 先），
    # 排序后身份序恒同——「取首」不再随轮次翻转
    pad = _f("XX111", "01:00", "02:00", 9999, "ctrip", airline="垫行航司")
    a = _stable_pool(list(reversed(_TIE)) + [pad])
    b = _stable_pool(_TIE + [pad])
    assert [f.flight_no for f in a] == [f.flight_no for f in b]
    # 同价对的相对序由身份键定：depart_time 早者恒前（07:05 < 14:05）
    nos = [f.flight_no for f in a]
    assert nos.index("9C8815") < nos.index("9C8807")


def test_sort_key_is_identity_not_price():
    # 价格不进键：价高的早班机仍排前（价格排序归下游口径，
    # 池序只承载同价 tie-break 的确定性）
    pool = [_f("AA001", "20:00", "23:00", 900, "qunar"),
            _f("BB002", "06:00", "09:00", 1500, "ctrip")]
    out = _stable_pool(pool)
    assert out[0].flight_no == "BB002"


def test_default_empty_fields_do_not_raise():
    # dataclass 缺省字段（flight_no/airline 为 "" 的早退残行形态）
    rough = [FlightPrice(platform="qunar", from_city="SHA", to_city="HAK",
                         depart_date="2027-01-30", price=500),
             _f("CC003", "08:00", "11:00", 700, "tuniu")]
    out = _stable_pool(rough)
    # 确定性即可（空身份键按字典序排前；残行由下游守卫过滤）
    assert [f.flight_no for f in out] == ["", "CC003"]


def test_original_list_not_mutated():
    src = list(_TIE)
    _stable_pool(src)
    assert src[0].flight_no == "9C8815"   # 原池序不污染（extend 语义不变）


# ---- merged from tests/test_r316_toast_deadzone.py ----

def _mk_ding(monkeypatch):
    toasts = []
    monkeypatch.setattr(_n, "_channel_streak_toast",
                        lambda lg, ch, body: toasts.append((ch, body)))
    d = _n.DingTalkNotifier("https://oapi.dingtalk.com/robot/send?"
                            "access_token=x", logging.getLogger("t"))
    return d, toasts


def test_streak_due_single_source():
    """8 倍点判定单源：≥8 且 %8==0；7/10/12/15 全 False。"""
    for n, want in ((7, False), (8, True), (10, False), (12, False),
                    (15, False), (16, True), (24, True)):
        assert _n._streak_due(n) is want, n


def test_backoff_skip_rounds_now_reach_toast(monkeypatch):
    """死区复现+修复实效：心跳退避稳态下，跳过轮 streak 递增路径
    落 8 倍点必须弹窗（修复前 120 轮连败 0 弹窗的死区位）。"""
    d, toasts = _mk_ding(monkeypatch)
    d._fail_streak = 6          # 退避起点：6 轮连败已过 HB_BACKOFF_AFTER
    # 纯跳过序列（生产心跳稳态：探测轮放行 send、其余跳过）——
    # 模拟 60 个心跳轮：每 4 轮 1 探（send 失败 streak+1+检查）、
    # 3 轮跳过（streak+1+检查[修复位]）
    for _ in range(60):         # 60 个心跳轮（≈15 小时）
        if d.heartbeat_allow():
            d._fail_streak += 1          # send 失败分支的 streak 推进
            d._streak_check_current()    # send 失败分支尾的检查点
        # 跳过轮的检查点由 heartbeat_allow 内部位移承载（r316 P2-1
        # 修复位）——修复前 due 点落跳过轮即无人检查=死区
    streaks = list(range(7, 67))
    due = [n for n in streaks if _n._streak_due(n)]
    assert due == [8, 16, 24, 32, 40, 48, 56, 64]
    assert len(toasts) == len(due), (toasts, due)
    assert all("钉钉" in ch for ch, _ in toasts)


def test_send_failure_branch_uses_same_gate(monkeypatch):
    """send 失败分支与跳过分支共用 _streak_due 门：8 倍点弹一次、
    非 8 倍点不弹（与旧行为等价，单源防双门漂移）。"""
    d, toasts = _mk_ding(monkeypatch)
    d._fail_streak = 8
    d._streak_check_current()     # 8 落点（send 失败分支形态）
    d._fail_streak = 10
    d._streak_check_current()     # 非倍点
    assert len(toasts) == 1, toasts
    assert "8 轮失败" in toasts[0][1] or "8" in toasts[0][1]


def test_serverchan_skip_branch_same_fix(monkeypatch):
    """ServerChan 同构检查点同批（C1 立案批注）：退避跳过轮落 8 倍
    点同样弹窗。"""
    toasts = []
    monkeypatch.setattr(_n, "_channel_streak_toast",
                        lambda lg, ch, body: toasts.append((ch, body)))
    s = _n.ServerChanNotifier("sckey", logging.getLogger("t"))
    s._fail_streak = 7
    s.heartbeat_allow()           # 跳过轮：streak→8 就地检查
    assert len(toasts) == 1, toasts
    assert "Server酱" in toasts[0][0]


def test_toast_is_not_a_resend(monkeypatch):
    """红线：弹窗路径零网络 send——检查点触发的轮不产生任何额外
    httpx 调用（单发零重试终局裁决不受影响）。"""
    calls = []
    monkeypatch.setattr(_n.httpx, "post",
                        lambda *a, **k: calls.append(a))
    d, toasts = _mk_ding(monkeypatch)
    d._fail_streak = 7
    d.heartbeat_allow()           # 跳过轮→streak 8→弹窗检查
    assert toasts
    assert calls == [], calls     # 零网络调用


# ---- merged from tests/test_r322_slim_chain.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _win_route(frm="上海", to="乌鲁木齐", fc="SHA", tc="URC"):
    """带出发窗航线（dep_win_txt 产出「（19:00后出发）」形态）。"""
    from core.models import Route as _R
    return _R(from_code=fc, to_code=tc, from_name=frm, to_name=to,
              dates=["2026-09-25"], alert_direct=1900, alert_transfer=1700,
              dep_time_min="19:00", dep_time_max="")


def _bd_only_sections(price=1950):
    """bd-only 节（中转池空：best_transfer/best_transfer_mkt 双 None）。"""
    return [{"date": "2026-09-25",
             "best_direct": {"price": price, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"},
             "best_transfer": None, "best_transfer_mkt": None,
             "seen_plats": ["qunar"]}]


def _slim_desp(route, sections):
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    return a._digest_payload([(route, sections)], fresh=False,
                             with_tables=False, with_charts=False)["desp"]


def test_slim_bd_only_windowed_row_keeps_price():
    """案1：bd-only 带窗航线的 slim 行必须保住价格判据。

    现行 `if bt and bd:` 门下剥窗保价档不挂链：head_full
    （> 上海→乌鲁木齐（19:00后出发） 09/25 ｜ 直飞 ￥1950）超 40、
    bare+win 地板零价格——真实账本 9 连轮零价格形态。修后剥窗档
    `> 上海→乌鲁木齐 09/25 ｜ 直飞 ￥1950`（34/40）落位。"""
    desp = _slim_desp(_win_route(), _bd_only_sections())
    rows = [ln for ln in desp.splitlines() if ln.startswith("> 上海→乌鲁木齐")]
    assert rows, desp[:600]
    row = rows[0]
    assert "直飞 ￥1950" in row, "bd-only 带窗行零价格（案1 病灶）：%r" % row
    assert _disp_dw(row) <= 40, "保价行超宽：%r (%.1f)" % (row, _disp_dw(row))
    # 窗词面按档序有意丢弃（r321 M1 备案：同 OD 无窗行靠日期可辨）
    assert "19:00后出发" not in row, row


def test_slim_floor_survives_longest_city_pair():
    """案2：≥11 CJK 城市对下链尾地板恒达标（无窗裸档兜底）。

    阿拉善左旗→塔什库尔干（12 CJK 字 OD）：bare+win 46/40 超、
    全链超宽时 _fit_line 取末档原样=超宽落位。修后链尾补无窗裸档
    `> 阿拉善左旗→塔什库尔干 09/25`（31/40）恒落位。"""
    desp = _slim_desp(
        _win_route("阿拉善左旗", "塔什库尔干", "ALQ", "HQL"),
        _bd_only_sections())
    rows = [ln for ln in desp.splitlines()
            if ln.startswith("> 阿拉善左旗")]
    assert rows, desp[:600]
    row = rows[0]
    assert _disp_dw(row) <= 40, "地板档超宽（案2 破口）：%r (%.1f)" % (
        row, _disp_dw(row))
    assert "阿拉善左旗" in row and "09/25" in row, row


def test_slim_dual_class_windowed_row_unchanged():
    """双类在场路径零回归：bd+bt 带窗 slim 行仍落剥窗保价档
    （r321 M1 既有行为），档序不变。"""
    secs = _bd_only_sections()
    secs[0]["best_transfer_mkt"] = {"price": 2050, "name": "CZ6976转",
                                    "transCity": "郑州",
                                    "_platform": "ctrip"}
    desp = _slim_desp(_win_route(), secs)
    rows = [ln for ln in desp.splitlines() if ln.startswith("> 上海→乌鲁木齐")]
    assert rows, desp[:600]
    row = rows[0]
    assert "直飞 ￥1950" in row, row
    assert _disp_dw(row) <= 40, row


# ---- merged from tests/test_r324_polish.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_demo_daily_covers_oldest_history_day():
    from core.demo import build_demo_db, demo_routes
    from core.storage import PriceStorage
    # 唯一临时文件：曾写死 `r324_demo_span_probe.db`，xdist 多 worker 并行时
    # 两个进程同时建同一个库、或收尾 os.remove 撞上对方仍持有的句柄 →
    # PermissionError [WinError 32]，表现为随机一项红（单跑必绿）。
    # 用唯一文件名而不是 mkstemp：后者会预建空文件，build_demo_db 需要新建。
    path = os.path.join(tempfile.gettempdir(),
                        "r324_demo_span_%d_%s.db" % (os.getpid(), uuid.uuid4().hex[:8]))
    try:
        build_demo_db(path)
        conn = sqlite3.connect(path)
        mn = conn.execute(
            "SELECT min(fetched_at) FROM flight_prices").fetchone()[0]
        conn.close()
        assert mn, "demo 库应有历史明细行"
        oldest_day = str(mn)[:10]                      # YYYY-MM-DD
        mmdd = oldest_day[5:]
        rt = demo_routes()[0]
        st = PriceStorage(path)
        rows = st.daily_series(rt["from"], rt["to"], rt["dates"][0],
                               days=30, th_d=0, kind="d")
        assert rows, "长窗应有日桶"
        assert rows[0]["day"] <= mmdd, (
            f"日桶首桶 {rows[0]['day']} 晚于最老明细日 {mmdd}——"
            "派生循环少刷最旧一日")
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_view_link_title_no_duplicated_qu():
    src = webui_full_src()
    assert src.count('title="在${') >= 3, "三处行内链接出口应统一「在{渠道}查看」"
    assert "去${platCn}查看" not in src, "numlink title 渠道名「去哪儿」与动词叠字"
    assert "去${he(x.plat" not in src and "去${he(f.plat" not in src, (
        "概览/明细行链接 title 同款叠字")


# ---- merged from tests/test_r339_bark_ret.py ----

# ---- ① Bark 通道 ----

def _mk(monkeypatch, code=200):
    log = _lg.getLogger("t")
    bk = N.BarkNotifier(key="testkey123", logger=log)
    calls = []

    def _fake_post(url, **kw):
        calls.append((url, kw))
        return mock.Mock(status_code=200, json=lambda: {"code": code})
    monkeypatch.setattr(N.httpx, "post", _fake_post)
    return bk, calls


def test_bark_send_ok(monkeypatch):
    bk, calls = _mk(monkeypatch)
    assert bk.send("达标", "上海-海口 ￥900") is True
    assert len(calls) == 1
    url, kw = calls[0]
    assert url.endswith("/push")
    body = kw["json"]
    assert body["device_key"] == "testkey123"
    assert body["title"] and "￥900" in body["body"]
    assert kw.get("timeout") and kw.get("trust_env") is False  # 直连律


def test_bark_empty_key_no_call(monkeypatch):
    log = _lg.getLogger("t")
    bk = N.BarkNotifier(key="", logger=log)
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **k: calls.append(u)
                        or mock.Mock(status_code=200))
    assert bk.send("t", "b") is False
    assert calls == []


def test_bark_non200_false(monkeypatch):
    bk, calls = _mk(monkeypatch, code=400)
    assert bk.send("t", "b") is False


def test_bark_body_plain(monkeypatch):
    # 正文转写：图占位/链接还原/markdown 记号剥除（ntfy 同族律）
    bk, calls = _mk(monkeypatch)
    bk.send("t", "![x](https://img) [**直飞 ￥1**](https://a) # > * `z")
    body = calls[0][1]["json"]["body"]
    assert "![x]" not in body and "](https" not in body
    assert "https://a" in body and "直飞 ￥1" in body
    # 记号剥实断言（原恒真式改写：剥后无 markdown 残留字面）
    assert "#" not in body and "*" not in body and "`" not in body


def test_bark_in_urgent_builder():
    log = _lg.getLogger("t")
    outs = N.build_urgent_notifier(
        {"bark": {"enabled": True, "key": "k1"}}, log)
    assert any(isinstance(x, N.BarkNotifier) for x in outs)


def test_bark_absent_not_built():
    assert N.build_urgent_notifier({}, _lg.getLogger("t")) is None \
        or not any(isinstance(x, N.BarkNotifier)
                   for x in (N.build_urgent_notifier(
                       {}, _lg.getLogger("t")) or []))


# ---- ② 返程日期多选 ----

def _rt(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "NRT",
         "to_name": "东京成田", "dates": ["2026-11-16"],
         "alert_direct": 2500}
    d.update(kw)
    return d


def test_ret_dates_legacy_key_merges():
    r = main_rt = __import__("main").build_routes(
        [_rt(ret_date="2026-11-20")])[0]
    assert r.ret_dates == ["2026-11-20"]


def test_ret_dates_list_honored_dedupe():
    r = __import__("main").build_routes([_rt(ret_dates=[
        "2026-11-20", "2026-11-27", "2026-11-20"])])[0]
    assert r.ret_dates == ["2026-11-20", "2026-11-27"]


def test_ret_dates_absent_empty():
    r = __import__("main").build_routes([_rt()])[0]
    assert r.ret_dates == []


# ---- merged from tests/test_r339_pulse_gate.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _fresh(tmp_path, monkeypatch, store_override=None):
    """重定向模块 STORE 到 tmp（防任何分支触达真实生产文件）后新建
    实例；返回 (实例, 账本路径)。"""
    tgt = str(tmp_path / "pulse.json")
    monkeypatch.setattr(P, "STORE", tgt)
    return P.Pulse(store=store_override), (store_override or tgt)


def test_pytest_form_rejects_default_store(tmp_path, monkeypatch):
    """非生产形态进程（pytest）+ 默认路径 → end() 不落盘（合成轮
    不入生产账本）。"""
    p, tgt = _fresh(tmp_path, monkeypatch)
    with mock.patch("core.notifier._prod_ledger_allowed", return_value=False):
        p.begin()
        p.channel("qunar", 70, 8.2)
        p.end()
    assert not os.path.exists(tgt), "合成轮写入默认账本=污染复发"


def test_prod_form_writes(tmp_path, monkeypatch):
    """生产形态（exe/main.py/webui.py 入口）+ 默认路径 → 照写
    （产品语义不丢：生产轮持久化）。"""
    p, tgt = _fresh(tmp_path, monkeypatch)
    with mock.patch("core.notifier._prod_ledger_allowed", return_value=True):
        p.begin()
        p.channel("qunar", 70, 8.2)
        p.end()
    assert os.path.exists(tgt)
    rounds = json.load(open(tgt, encoding="utf-8"))
    assert rounds and rounds[-1]["chans"]["qunar"]["rows"] == 70


def test_explicit_store_always_allowed(tmp_path, monkeypatch):
    """显式注入 store（压测/探针独立账本）→ 资格门不拦（显式重定向
    永远放行，与 push history 契约同）。"""
    alt = str(tmp_path / "alt_pulse.json")
    p, _ = _fresh(tmp_path, monkeypatch, store_override=alt)
    with mock.patch("core.notifier._prod_ledger_allowed", return_value=False):
        p.begin()
        p.channel("ctrip", 5, 1.0)
        p.end()
    assert os.path.exists(alt)
    rounds = json.load(open(alt, encoding="utf-8"))
    assert rounds and rounds[-1]["chans"]["ctrip"]["rows"] == 5


# ---- merged from tests/test_r339_route_quick.py ----

def test_direct_only_zeroes_transfer_alert():
    routes = main.build_routes([
        {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1500,
         "alert_transfer": 1300, "direct_only": True}])
    assert routes[0].alert_transfer == 0
    assert routes[0].alert_direct == 1500


def test_no_flag_keeps_transfer_alert():
    routes = main.build_routes([
        {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1500,
         "alert_transfer": 1300}])
    assert routes[0].alert_transfer == 1300


# ---- 航线级筛选约束（明细已解析字段升格：对齐 OTA 高频筛选面） ----

def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False, "baggage": "免费托运20kg", "planeSize": "大型机"}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "PEK", "to_name": "北京",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


def test_filter_airlines_by_code_and_name():
    from core.alerter import Alerter
    rt = _route(airlines="MU, 春秋")
    assert Alerter._route_filters([_flt()], rt)          # 码命中
    assert Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt)  # 名称片段命中
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)  # 不在白名单
    assert not Alerter._route_filters([_flt(airlineCode="", airline="")], rt)
    # 白名单失败语义：未标注航司的行按不满足（十七§5 保守筛选律）


def test_filter_no_lcc():
    from core.alerter import Alerter
    rt = _route(no_lcc=True)
    assert not Alerter._route_filters([_flt(lcc=True)], rt)
    assert Alerter._route_filters([_flt(lcc=False)], rt)
    assert Alerter._route_filters([_flt()], rt)   # 缺席≠廉航，不剔


def test_filter_min_baggage():
    from core.alerter import Alerter
    rt = _route(min_baggage=15)
    assert Alerter._route_filters([_flt()], rt)              # 20kg ≥ 15
    assert not Alerter._route_filters(
        [_flt(baggage="免费托运10kg")], rt)                    # 不足
    assert not Alerter._route_filters([_flt(baggage="")], rt)  # 未标注按不满足


def test_filter_widebody():
    from core.alerter import Alerter
    rt = _route(widebody_only=True)
    assert Alerter._route_filters([_flt()], rt)               # 大型机
    assert not Alerter._route_filters(
        [_flt(planeSize="中型机")], rt)
    assert not Alerter._route_filters(
        [_flt(planeSize="小型机")], rt)
    assert Alerter._route_filters([_flt(planeSize="")], rt)   # 缺席不剔（fail-open 防整渠道误杀）


def test_build_routes_filter_fields_passthrough():
    rt = _route(airlines="MU,MF", no_lcc=True, min_baggage=20,
                widebody_only=True)
    assert rt.airlines == "MU,MF" and rt.no_lcc is True
    assert rt.min_baggage == 20 and rt.widebody_only is True
    rt0 = _route()
    assert rt0.airlines == "" and rt0.no_lcc is False
    assert rt0.min_baggage == 0 and rt0.widebody_only is False


# ---- merged from tests/test_r514_stalled_collection_is_not_just_waiting.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'%s','BKK','CAN','2026-11-05','H5',?)" % plat,
            (at, status))


def test_stalled_is_true_when_last_sample_predates_the_intervention():
    ps = _ps()
    now = datetime.now()
    iv_at = _fmt(now - timedelta(hours=1))
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy",
                         at=iv_at)
    # 最后一条样本在 26 小时前（早于干预，且已远超 2 小时）
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(hours=26)))
    e = ps.intervention_effect("fliggy", 24)
    assert e["stalled"] is True, \
        "采集停了 26 小时却没标出来：%r" % (e,)
    assert e["stalled_hours"] >= 25, e
    assert e["last_sample_at"], e
    assert e["after"] is None, e


def test_fresh_wait_is_not_reported_as_stalled():
    """干预刚做完、还没轮到采集：正常等待，不能报「采集已停」。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("fliggy", "probe", ok=True, at=_fmt(now))
    # 半小时前刚有样本（早于干预，但远不到停摆阈值）
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(minutes=30)))
    e = ps.intervention_effect("fliggy", 24)
    assert e["stalled"] is False, \
        "刚采集过却被报成停摆：%r" % (e,)
    assert e["stalled_hours"] is None, e


def test_threshold_boundary_is_two_hours():
    """2 小时是阈值：刚过线算停摆，线内不算——两侧都要钉，否则阈值会被改歪。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("fliggy", "probe", ok=True, at=_fmt(now))
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(hours=1, minutes=50)))
    assert ps.intervention_effect("fliggy", 24)["stalled"] is False, \
        "1h50m 没到阈值就被判停摆"

    ps2 = _ps()
    ps2.save_intervention("fliggy", "probe", ok=True, at=_fmt(now))
    _row(ps2, "fliggy", "ok", _fmt(now - timedelta(hours=2, minutes=20)))
    assert ps2.intervention_effect("fliggy", 24)["stalled"] is True, \
        "2h20m 已超阈值却没判停摆"


def test_samples_after_the_intervention_are_never_stalled():
    """干预后已经有样本：即使该渠道很久没再采，也不算「这次干预没被验证」。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("ctrip", "probe", ok=True,
                         at=_fmt(now - timedelta(hours=30)))
    _row(ps, "ctrip", "ok", _fmt(now - timedelta(hours=29)))  # 干预后
    e = ps.intervention_effect("ctrip", 72)
    assert e["after_n"] == 1, e
    assert e["stalled"] is False, \
        "干预后已有样本，却仍报采集停摆：%r" % (e,)


def test_stalled_is_per_channel_not_global():
    """单渠道停摆不得牵连其它渠道。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("fliggy", "relogin", ok=True, at=_fmt(now))
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(hours=30)))
    ps.save_intervention("qunar", "probe", ok=True, at=_fmt(now))
    _row(ps, "qunar", "ok", _fmt(now - timedelta(hours=1)))
    assert ps.intervention_effect("fliggy", 24)["stalled"] is True
    assert ps.intervention_effect("qunar", 24)["stalled"] is False


def test_the_two_no_sample_states_read_differently_in_the_panel():
    """面板上两种状态必须是两句话，且停摆那句要点明时长与最后样本。"""
    import io
    w = webui_full_src()
    assert "采集已停" in w, "面板没有区分「采集停了」"
    assert "这次干预还没被验证" in w, "停摆状态没有说明干预未经证实"
    assert w.count("干预后还没有新样本") >= 1, \
        "「正常等待」那句被删掉了（两种状态要并存）"
    # 两处追溯面板都要有
    assert w.count("eff.stalled") >= 2, \
        "只有一处面板区分了停摆：%d" % w.count("eff.stalled")


# ---- merged from tests/test_r519_bool_toggle_string_false.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _cfg(v):
    return parse_pacing({"crawler": {"health_penalty_enabled": v}})


def test_string_false_words_turn_the_switch_off():
    for v in ("false", "FALSE", " False ", "no", "off", "0", ""):
        assert _cfg(v)["health_penalty_enabled"] is False, \
            "YAML 写成 %r 时开关仍是开的（bool(str) 恒真）" % (v,)


def test_string_true_words_keep_it_on():
    for v in ("true", "TRUE", "yes", "on", "1"):
        assert _cfg(v)["health_penalty_enabled"] is True, v


def test_real_booleans_unchanged():
    assert _cfg(True)["health_penalty_enabled"] is True
    assert _cfg(False)["health_penalty_enabled"] is False
    assert _cfg(0)["health_penalty_enabled"] is False
    assert _cfg(1)["health_penalty_enabled"] is True
    # 缺省仍取 DEFAULTS
    assert parse_pacing({})["health_penalty_enabled"] is True


def test_string_false_actually_disables_the_penalty():
    """行为级：关掉后不得再降频（这是「可开启可关闭」的实质）。"""
    for v in (False, "false"):
        p = Pacing({"crawler": {"health_penalty_enabled": v}})
        p.set_health("qunar", 0.1, 10)
        h = p._health.get("qunar") or {}
        assert h.get("penalty") == 1.0, \
            "cfg=%r 时仍在按成功率降频：%r" % (v, h)
        assert h.get("disabled") is True, h
    # 开启时必须真的降频（不能为了修关闭把功能关掉）
    p2 = Pacing({"crawler": {"health_penalty_enabled": True,
                             "health_min_samples": 5,
                             "health_ok_ratio": 0.7,
                             "health_slow_ratio": 0.4,
                             "health_slowest_factor": 3.0}})
    p2.set_health("qunar", 0.1, 10)
    assert (p2._health.get("qunar") or {}).get("penalty") == 3.0, \
        "开启时不再降频（把功能关掉了）：%r" % (p2._health.get("qunar"),)


def test_all_three_toggles_share_the_same_string_handling():
    """三个开关走同一个解析函数（r520）：只修一个会留下同类缺口。

    实测 `breaker.enabled` / `warmup.enabled` 原先也是 `bool(...)`，
    同样会把 `"false"` 当 True。
    """
    cases = [
        ("breaker_enabled", {"crawler": {"breaker": {"enabled": "false"}}}),
        ("warmup_enabled", {"crawler": {"warmup": {"enabled": "false"}}}),
        ("health_penalty_enabled",
         {"crawler": {"health_penalty_enabled": "false"}}),
    ]
    for key, cfg in cases:
        assert parse_pacing(cfg)[key] is False, \
            "%s 的 \"false\" 仍被当成开启" % key
        # 缺省/None 必须回到 DEFAULTS，不能被 _flag 误判成关闭
    assert parse_pacing({})["breaker_enabled"] is True
    assert parse_pacing({})["warmup_enabled"] is True
    assert parse_pacing({})["health_penalty_enabled"] is True


def test_flag_helper_is_single_source():
    """三处必须调用同一个 `_flag`，不允许再各写一份。"""
    import inspect
    from core import pacing as _p
    src = inspect.getsource(_p.parse_pacing)
    assert src.count("_flag(") == 3, \
        "应有三处走 _flag，实际 %d 处" % src.count("_flag(")
    assert "bool(brk.get(" not in src and "bool(warm.get(" not in src, \
        "仍有地方用 bool() 直接转配置值"
    assert callable(_p._flag)


# ---- merged from tests/test_r654_every_scope_has_a_label.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_every_scope_written_to_the_ledger_has_a_chinese_label():
    w = _w()
    i = w.index("const _ivScope={")
    seg = w[i:w.index("};", i)]
    # 先按逗号切项再取键名：直接 findall 时 `fliggy:` 会先吃掉
    # `fliggy_h5:` 的前缀（非重叠匹配），带下划线的 key 永远读不到。
    labels = set()
    for item in seg.split(","):
        # 贪婪取到冒号前为止：`fliggy_h5:` 必须整体作为一个 key，
        # 而 [a-z_]+ 会先试着只吃 fliggy、发现后面不是冒号就整项放弃。
        m = re.match(r"\s*([a-z0-9_]+)\s*:", item)
        if m:
            labels.add(m.group(1))

    # 所有 save_intervention(..., scope=<literal>) 的落库取值
    scopes = set()
    for m in re.finditer(r'save_intervention\((?:[^()]|\([^()]*\))*?\)', w):
        call = m.group(0)
        for sm in re.finditer(r'scope\s*=\s*"([a-z_]+)"', call):
            scopes.add(sm.group(1))
        for sm in re.finditer(r'scope\s*=\s*str\(([^)]*)\)', call):
            # scope=str(key) / scope=str(scene.get("kind") or "")
            scopes.add("<dynamic>")
    # 动态 scope 的实际取值来自登录槽位 key（ctrip/qunar/fliggy/fliggy_h5/...）
    # 与 App 渠道 id（r813d 起 App 登录按渠道记 scope，不再合并成 app）
    from core.channels import APP_CHANNELS
    from core.login_slots import LOGIN_SLOTS
    scopes |= set(LOGIN_SLOTS.keys()) | set(APP_CHANNELS)
    # 动作级（空 scope）不计
    scopes.discard("")

    missing = sorted(s for s in scopes
                     if s != "<dynamic>" and s not in labels)
    assert not missing, (
        "这些 scope 值没有中文标签，面板会直接打出原始 id：%s（已有：%s）"
        % (missing, sorted(labels)))


def test_app_scope_reads_as_the_channel_name_not_raw_id():
    """两个 App 的干预 scope 必须各显示各的名字。

    r813d 前 App 登录统一写 scope="app"，面板把合并后的成功率标成
    「智行 App」——去哪儿 App 的重登统计被算在智行名下，既错又不可区分。
    现在写入按渠道 id；历史 scope=app 保留中性标签「旧记录」。
    """
    w = _w()
    i = w.index("const _ivScope={")
    seg = w[i:w.index("};", i)]
    assert "app_zhixing:'智行 App'" in seg, seg
    assert "app_qunar:'去哪儿 App'" in seg, seg
    assert "app:'App 登录（旧记录）'" in seg, seg
    assert "app:'智行 App'" not in seg, "合并的 app scope 不能再冒充智行"
    # 写入侧：登录成功后按渠道记 scope，而不是共享的 "app"
    assert "scope=_plata" in w
    assert 'save_intervention(\n                                _plata, "relogin", ok=True, scope="app"' not in w


# ---- merged from tests/test_r677_emailshot_runs_as_root.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _FakePage:
    def __init__(self):
        self.waits = []

    def goto(self, *a, **kw):
        return None

    def wait_for_function(self, *a, **kw):
        return None

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def screenshot(self, **kw):
        return b"\x89PNG\r\n\x1a\nfake"


class _FakeBrowser:
    def __init__(self, sink):
        self.sink = sink

    def new_page(self, **kw):
        self.sink["page_kw"] = kw
        return _FakePage()

    def close(self):
        self.sink["closed"] = True


class _FakeChromium:
    def __init__(self, sink):
        self.sink = sink

    def launch(self, **kw):
        self.sink["launch"] = kw
        return _FakeBrowser(self.sink)


class _FakePW:
    def __init__(self, sink):
        self.sink = sink
        self.chromium = _FakeChromium(sink)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, *a):
        self.lines.append(("info", a))

    def warning(self, *a):
        self.lines.append(("warning", a))








# ---- merged from tests/test_r805ac_detail_dimension.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def test_every_channel_declares_detail():
    """七家的 detail 都必须是 y：每一家账本里都有航班级明细。

    反向守卫：若哪天某家真的只剩日历（无时刻无航班号），这条会红，
    提醒把它降级——但现在没有这种情况。
    """
    # 2026-11-02 携程 App 修复「选择目的地」城市页判据后已连续两次 32/33
    # 行复验，现已写 y；保留集合给将来新增但尚未复验的可选渠道。
    unverified = set()
    for p in tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS):
        if p == "qunar":
            # 去哪儿网页版 PC/H5 均已停服：detail=n 是整条通路退役，
            # 不是「只剩日历」；数据走 app_qunar。
            assert CHANNEL_DIMENSIONS[p].get("detail") == "n"
            continue
        if p in unverified:
            assert CHANNEL_DIMENSIONS[p].get("detail") != "y", (
                "%s 已有连续复验后应移除 unverified 名单" % p)
            continue
        assert CHANNEL_DIMENSIONS[p].get("detail") == "y", (
            "%s 的 detail 不是 y（当前 %r）——账本里它有真实航班级明细"
            % (p, CHANNEL_DIMENSIONS[p].get("detail")))


def test_calendar_rows_are_not_counted_as_detail_defect():
    """日历行（name=日历最低价 / depTime 空）不算「明细缺失」。

    判据落在**构造器**上：日历元素必须显式标成日历产物，这样「无时刻
    无航班号」是可以解释的，而不是被读成解析失败。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert '"name": "日历最低价"' in src, (
        "日历元素的 name 标记没了：无时刻的行会被误判成解析漏项")
    fl = io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                 encoding="utf-8").read()
    assert '"日历最低价"' in fl, "fliggy 的日历标记没了"


def test_name_falls_back_to_flight_no_is_intentional():
    """`name = airline or flight_no` 是有意兜底，别当造假去删。

    真机/账本：国际页有时只给航班号不给航司名。留空会让列表显示空白，
    拿航班号占位至少能定位到班次；下游判班次用 depTime+arrTime。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert 'airline or flight_no' in src, (
        "航司名兜底被删了：国际页缺航司名时 name 会变成空串")
    assert "编一个假航班号才是缺陷" in src or "国际页没有航班号" in src, (
        "兜底决策的注释被删了：后人不清楚这是有意的，会误删")


# ---- merged from tests/test_r805au_env_fault_not_channel.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _one(note, s="error"):
    from core.health_diag import classify_round
    cards = classify_round({"fliggy": {"s": s, "ok": 0, "tot": 0,
                                       "note": note, "detail": 0, "cal": 0}},
                           all_plats=("fliggy",))
    assert cards, "分类器没产出卡片"
    return cards[0]


def test_proxy_failure_is_environment_not_channel():
    note = ("Page.goto: net::ERR_PROXY_CONNECTION_FAILED at "
            "https://market.m.taobao.com/app/trip/rx-traffic-search/pages/index")
    c = _one(note)
    assert c["kind"] == "env", (
        "代理故障被归成 %r —— 会把本机问题指成渠道问题：%s"
        % (c["kind"], c))
    assert "本机" in c["label"], "标签里要写明是本机问题：%r" % c["label"]
    assert "不是该渠道" in c["action"], (
        "动作要明确「不是该渠道的问题」，否则用户会去换渠道/重登：%r"
        % c["action"])


def test_other_environment_faults_also_env():
    for note in ("net::ERR_NAME_NOT_RESOLVED",
                 "net::ERR_INTERNET_DISCONNECTED",
                 "TargetClosedError: Target page, context or browser "
                 "has been closed"):
        c = _one(note)
        assert c["kind"] == "env", "%r 没被判成环境故障：%s" % (note, c)


def test_rate_limit_and_risk_wall_are_not_swallowed():
    """反例：真正的限流/风控不能被「环境故障」这条吃掉。"""
    for note in ("H5 限流（mtop RGV587，冷却后自愈）",
                 "命中风控", "403 限流"):
        c = _one(note)
        assert c["kind"] != "env", (
            "把限流/风控误判成本机故障会让人不去等冷却：%r -> %s"
            % (note, c["kind"]))


def test_env_card_has_status_chip_style():
    src = webui_full_src()
    assert ".hdiag-card.env .hdiag-st" in src, (
        "新 kind 没有状态胶囊配色，卡片会看起来像坏了（胶囊透明）")


# ---- merged from tests/test_r919_vendor_api.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r919")


class FakeMgr:
    """假 MuMuManager：``setting`` 读写内存字典，可选拒绝某些键。"""

    def __init__(self, values=None, available=True, reject=()):
        self.values = dict(values or {})
        self._available = available
        self.reject = set(reject)
        self.writes = []

    def available(self):
        return self._available

    def _vm(self, vm):
        return 0

    def setting(self, key, value=None, vm=None):
        if value is None:
            return self.values.get(key)
        self.writes.append((key, value))
        if key in self.reject:
            return None
        self.values[key] = str(value)
        return "{}"

    def _call_json(self, args, timeout=None):
        return dict(self.values)


_BASE = {
    "phone_brand": "Samsung",
    "phone_model": "Galaxy A52 5G",
    "phone_miit": "SM-A5260",
    "resolution_width": "1600.000000",
    "resolution_height": "900.000000",
    "resolution_dpi": "240.000000",
    "system_disk_readonly": "true",
    "root_permission": "true",
    "performance_cpu": "4",
    "net_bridge.enabled": "false",
}


# ---------------------------------------------------------------------------
# 1. 读
# ---------------------------------------------------------------------------
def test_read_returns_all_settings():
    got = vendor.read(FakeMgr(_BASE))
    assert got["phone_miit"] == "SM-A5260"
    assert got["system_disk_readonly"] == "true"


def test_read_unavailable_is_empty():
    assert vendor.read(FakeMgr(_BASE, available=False)) == {}


def test_get_returns_value():
    assert vendor.get("phone_brand", FakeMgr(_BASE)) == "Samsung"


# ---------------------------------------------------------------------------
# 2. 写 + 白名单 + 读回校验
# ---------------------------------------------------------------------------
def test_apply_writes_whitelisted_keys_and_verifies():
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, phone_brand="Xiaomi", phone_miit="2201123C")
    assert rep["ok"] is True
    assert rep["applied"] == {"phone_brand": "Xiaomi", "phone_miit": "2201123C"}
    assert all(v["ok"] for v in rep["verify"].values())
    assert rep["restart_required"] is False


def test_apply_rejects_performance_and_network_keys():
    """性能/网络键改错会让采集变慢或断网——必须拒。"""
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, performance_cpu=16, **{"net_bridge.enabled": "true"})
    assert rep["applied"] == {}
    assert set(rep["rejected"]) == {"performance_cpu", "net_bridge.enabled"}
    assert mgr.writes == []           # 一个都没真写


def test_apply_numeric_readback_tolerates_decimals():
    """读回是 1600.000000，写的是 1600 —— 要按数值判等。"""
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, resolution_width=1080, resolution_height=1920)
    assert rep["verify"]["resolution_width"]["ok"] is True
    assert rep["verify"]["resolution_height"]["ok"] is True
    assert rep["ok"] is True


def test_apply_marks_restart_required_for_system_disk():
    mgr = FakeMgr(_BASE)
    rep = vendor.apply(mgr, system_disk_readonly="false")
    assert rep["applied"]["system_disk_readonly"] == "false"
    assert rep["restart_required"] is True


def test_apply_reports_write_failure():
    mgr = FakeMgr(_BASE, reject={"phone_model"})
    rep = vendor.apply(mgr, phone_model="X99")
    assert rep["ok"] is False
    assert rep["verify"]["phone_model"]["ok"] is False


def test_apply_unavailable_manager():
    rep = vendor.apply(FakeMgr(_BASE, available=False), phone_brand="X")
    assert rep["ok"] is False and "不可用" in rep["error"]


# ---------------------------------------------------------------------------
# 3. 组合入口
# ---------------------------------------------------------------------------
def test_spoof_device_sets_three_coherent_keys():
    mgr = FakeMgr(_BASE)
    rep = vendor.spoof_device(mgr, brand="Redmi", model="Redmi K50",
                              miit="2201123C", imei="860000000000001")
    assert rep["ok"] is True
    assert mgr.values["phone_brand"] == "Redmi"
    assert mgr.values["phone_model"] == "Redmi K50"
    assert mgr.values["phone_miit"] == "2201123C"


def test_spoof_screen_sets_resolution_and_dpi():
    mgr = FakeMgr(_BASE)
    rep = vendor.spoof_screen(mgr, width=1080, height=1920, dpi=440)
    assert rep["ok"] is True
    assert float(mgr.values["resolution_width"]) == 1080.0
    assert float(mgr.values["resolution_dpi"]) == 440.0


def test_unlock_system_disk_never_restarts_by_default():
    mgr = FakeMgr(_BASE)
    rep = vendor.unlock_system_disk(mgr)
    assert rep["applied"]["system_disk_readonly"] == "false"
    assert rep["restarted"] is False      # 默认绝不替你重启


# ---------------------------------------------------------------------------
# 4. hardening 的 vendor 段：默认只读
# ---------------------------------------------------------------------------
def test_harden_vendor_step_is_read_only_by_default(monkeypatch):
    mgr = FakeMgr(_BASE)
    monkeypatch.setattr(hardening, "vendor_mod", vendor, raising=False)
    import core.android.config as cfgmod
    import core.android.mumu as mumumod
    monkeypatch.setattr(cfgmod, "resolve_install_dir", lambda c: "X")
    monkeypatch.setattr(cfgmod, "normalize", lambda raw: cfgmod.AndroidConfig())
    monkeypatch.setattr(mumumod, "MuMuManager",
                        lambda **kw: mgr)
    rep = hardening._vendor_step({"android": {}}, _LOG, vm=0)
    assert rep["available"] is True
    assert "只读" in rep.get("skipped", "")
    assert mgr.writes == []               # 一个键都没写
    assert rep["current"]["phone_miit"] == "SM-A5260"


def test_harden_vendor_step_writes_when_configured(monkeypatch):
    mgr = FakeMgr(_BASE)
    monkeypatch.setattr(hardening, "vendor_mod", vendor, raising=False)
    import core.android.config as cfgmod
    import core.android.mumu as mumumod
    monkeypatch.setattr(cfgmod, "resolve_install_dir", lambda c: "X")
    monkeypatch.setattr(cfgmod, "normalize", lambda raw: cfgmod.AndroidConfig())
    monkeypatch.setattr(mumumod, "MuMuManager", lambda **kw: mgr)
    cfg = {"android": {"vendor": {"apply": True, "brand": "Redmi",
                                  "model": "Redmi K50"}}}
    rep = hardening._vendor_step(cfg, _LOG, vm=0)
    assert rep["apply"]["ok"] is True
    assert mgr.values["phone_brand"] == "Redmi"


# ---- merged from tests/test_r932_unified_price.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. 正常形态
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    ("¥5711", 5711),
    ("￥5711", 5711),
    ("5711", 5711),
    ("¥ 680", 680),
    ("￥1,234", 1234),
    ("1，234", 1234),          # 全角逗号
    ("$999", 999),
    ("99.5", 99.5),
    ("  3305  ", 3305),
])
def test_parse_price_normal(text, want):
    assert parse_price(text) == want


# ---------------------------------------------------------------------------
# 2. 必须拒绝的（绝不给 0）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "", "   ", "¥", "￥", "$",
    "4??", "4？?", "??",                      # 遮罩
    "7",                                      # 1 位：不是票价
    "123456",                                 # 6 位：不是票价
    "已减70",                                  # 优惠标签整串
    "abc", "¥abc",
])
def test_parse_price_rejects(text):
    v = parse_price(text)
    assert v is None, (text, v)


def test_zero_is_not_a_price():
    """`¥0` 不是合法票价——0 会让"降价提醒"误触发。"""
    assert parse_price("¥0") is None
    assert parse_price("0") is None


# ---------------------------------------------------------------------------
# 3. 遮罩识别（与价格解析分开，便于上层单独判断）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    ("4??", True), ("4？?", True), ("??", True),
    ("¥450", False), ("450", False), ("", False),
])
def test_is_masked(text, want):
    assert is_masked(text) is want


# ---------------------------------------------------------------------------
# 4. 辅助函数
# ---------------------------------------------------------------------------
def test_strip_currency():
    assert strip_currency("¥ 1,234") == "1234"
    assert strip_currency("￥5711") == "5711"
    assert strip_currency("") == ""


def test_currency_only_tuple():
    for ch in CURRENCY_ONLY:
        assert parse_price(ch) is None


def test_looks_like_price():
    assert looks_like_price("¥5711") is True
    assert looks_like_price("4??") is False


# ---------------------------------------------------------------------------
# 5. 解析器已统一（源码钉：不许再各写一套）
# ---------------------------------------------------------------------------
def test_qunar_uses_unified_price():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar_parse.py"),
                  encoding="utf-8").read()
    assert "core.price" in src, "qunar 解析器没用统一价格实现"
    # 不允许再出现"自己剥符号再 fullmatch 位数"的老写法
    assert not any(
        ("re.sub(r\"[¥" in ln and "ItemPrice" in ln)
        for ln in src.splitlines())


# ---- merged from tests/test_r942_readonly_props.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class FakeDev:
    """够 hide() 跑起来的假设备：root 可用、无 Magisk、给定 props。"""

    def __init__(self, props):
        self.props = dict(props)
        self.scripts = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if "pm list packages" in cmd:
            return ""
        if "magisk" in cmd:
            return ""
        if "input keyevent" in cmd:
            return ""
        if "test -e" in cmd:
            return "TM_NO"
        return ""


def _run_hide(monkeypatch, props):
    d = FakeDev(props)
    monkeypatch.setattr(st, "_root", lambda dev: True)
    monkeypatch.setattr(st, "_magisk", lambda dev: "")
    captured = {}

    def _as_root(dev, script, timeout=None):
        captured["script"] = script
        return ""
    monkeypatch.setattr(st, "as_root", _as_root)
    rep = st.hide(d, packages=["ctrip"], config={})
    return rep, captured.get("script", "")


# ---------------------------------------------------------------------------
# 1. 核心：ro.* 不进清理脚本（别再假成功）
# ---------------------------------------------------------------------------
def test_ro_props_not_put_in_clear_script(monkeypatch):
    rep, script = _run_hide(monkeypatch, {
        "ro.nemu": "1",
        "ro.build.version.nemux": "true",
        "nemud.fps_limit": "60",
    })
    assert "ro.nemu" not in script, "ro.nemu 仍在清理脚本里（会假成功）"
    assert "ro.build.version.nemux" not in script, "nemux 仍在清理脚本里"
    # 可写键仍然要清
    assert "nemud.fps_limit" in script, "可写键 nemed.* 没被清"


def test_readonly_props_reported_explicitly(monkeypatch):
    rep, _ = _run_hide(monkeypatch, {
        "ro.nemu": "1",
        "ro.build.version.nemux": "true",
    })
    acts = rep.get("actions") or []
    ro_act = [a for a in acts if str(a.get("cmd", "")).startswith(
        "props-readonly:")]
    assert ro_act, "没有 props-readonly 这一条（会让人以为清干净了）"
    why = str(ro_act[0].get("why") or "")
    assert "ro.nemu" in why, "why 里没点名 ro.nemu"
    assert "Magisk" in why, "why 里没说明根治手段"


def test_no_false_cleared_count(monkeypatch):
    """`cleared` 数字不许把 ro.* 算进去。"""
    rep, _ = _run_hide(monkeypatch, {"ro.nemu": "1", "nemud.x": "1"})
    acts = rep.get("actions") or []
    for a in acts:
        c = str(a.get("cmd") or "")
        if c.startswith("props:"):
            # 只应有 1 条 cleared（nemud.x），不是 2
            assert "2 cleared" not in c, "cleared 计数把 ro.* 也算进去了：%s" % c
            break
    else:
        raise AssertionError("没找到 props 动作")


# ---------------------------------------------------------------------------
# 2. 有 Magisk 时走 resetprop --delete（re 键一起消掉）
# ---------------------------------------------------------------------------
def test_with_magisk_uses_resetprop(monkeypatch):
    """有 Magisk 时 ro.nemu 必须走 resetprop --delete（而不是 setprop 空串）。

    `as_root` 会被调用多次（denylist 探测、magisk sqlite 探测、清理脚本…），
    所以要**收集全部调用**再找清理那一条。
    """
    d = FakeDev({"ro.nemu": "1"})
    monkeypatch.setattr(st, "_root", lambda dev: True)
    monkeypatch.setattr(st, "_magisk", lambda dev: "resetprop")
    scripts = []

    def _as_root(dev, script, timeout=None):
        scripts.append(script)
        return ""
    monkeypatch.setattr(st, "as_root", _as_root)
    st.hide(d, packages=["ctrip"], config={})
    joined = chr(10).join(scripts)
    assert "ro.nemu" in joined, "有 Magisk 时 ro.nemu 没进任何脚本"
    # 找到含 ro.nemu 的那一段，确认是 --delete 而不是 setprop ''
    seg = [x for x in scripts if "ro.nemu" in x][0]
    assert "--delete" in seg, "ro.nemu 没用 resetprop --delete：%s" % seg[:120]


# ---------------------------------------------------------------------------
# 3. 源码钉
# ---------------------------------------------------------------------------
def test_source_handles_readonly_branch():
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    assert "props-readonly" in src, "没有 readonly 分支"
    assert 'key.startswith("ro.")' in src, "没有 ro.* 判定"
    assert "假成功" in src or ("返回 0" in src and "值不变" in src), \
        "没记录这个坑（下次又会写成假成功）"


# ---- merged from tests/test_r951_audit_ceiling.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _audit_for(props_map):
    class _D:
        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            if cmd.strip() == "shell getprop":
                return "\n".join("[%s]: [%s]" % (k, v)
                                 for k, v in props_map.items())
            if cmd.startswith("shell getprop "):
                return props_map.get(cmd.split(" ", 2)[2], "")
            if "test -e" in cmd:
                return "TM_NO"
            return ""
    return fp.audit(_D())


# ---------------------------------------------------------------------------
# 1. 不可清除项：仍然扣分（不粉饰），但 fix 必须指向安全手段
# ---------------------------------------------------------------------------
def test_unfixable_still_counts_as_leak():
    a = _audit_for({"ro.product.cpu.abi": "x86_64",
                    "ro.product.cpu.abilist": "x86_64,arm64-v8a,x86",
                    "ro.product.model": "V2405A", "ro.product.brand": "vivo"})
    abi = [x for x in a["leaks"] if "cpu.abi" in str(x.get("key"))]
    assert abi, "全局 ABI 泄漏仍应计入（不能抹成 0 分）"
    assert a["score"] < 100, a["score"]


def test_fix_no_longer_suggests_global_rewrite():
    """`fix: identity` 会引导人去改全局架构 → 系统起不来。"""
    a = _audit_for({"ro.product.cpu.abi": "x86_64",
                    "ro.product.cpu.abilist": "x86_64",
                    "ro.product.model": "V2405A", "ro.product.brand": "vivo"})
    for x in a["leaks"]:
        if x.get("unfixable"):
            assert x.get("fix") != "identity", x
            assert "abi-select" in x.get("fix", "") or "包级" in x.get("fix", ""), x


def test_ceiling_reported_and_explained():
    a = _audit_for({"ro.product.cpu.abi": "x86_64",
                    "ro.product.cpu.abilist": "x86_64",
                    "ro.product.model": "V2405A", "ro.product.brand": "vivo"})
    assert a.get("unfixable") == 2, a.get("unfixable")
    # ceiling = 把所有**可修**的清掉之后的分数 = 100 - 6*不可修数
    assert a.get("score_ceiling") == 100 - 6 * a["unfixable"], a.get("score_ceiling")
    # score 永远 <= ceiling；低于它就是"还有能修的没修"
    assert a["score"] <= a["score_ceiling"], (a["score"], a["score_ceiling"])
    note = a.get("score_note") or ""
    assert "上限" in note and "真实架构" in note, note
    if a.get("fixable_left"):
        assert "可修未修" in note, note


def test_clean_device_has_no_ceiling_note():
    a = _audit_for({"ro.product.model": "V2405A", "ro.product.brand": "vivo",
                    "ro.product.cpu.abi": "arm64-v8a",
                    "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a"})
    assert a.get("unfixable") == 0
    assert a.get("score_note") == ""


# ---------------------------------------------------------------------------
# 2. 档案同步：必须复用已读的 props，且在 fast path 之后
# ---------------------------------------------------------------------------
def test_profile_sync_reuses_props():
    """档案同步若在 fast path 之前，每次"本 boot 已应用"都要多一次 getprop。"""
    src = io.open(os.path.join(ROOT, "core", "android", "fingerprint.py"),
                  encoding="utf-8").read()
    i_fast = src.find('marker == "%s %s" % (ident.ident_id, boot)')
    i_sync = src.find("既有身份也要跟官方对齐")
    i_plain = src.find("plain = props_of(dev)")
    assert 0 < i_fast < i_sync, "档案同步必须放在 fast path 判定之后"
    assert i_plain < i_sync, "同步应在 props 读好之后"
    # 同步块里不许再自己读一次 props
    blk = src[i_sync:i_sync + 3500]
    assert "props_of(dev)" not in blk, "同步块重复读 props（多花一条完整 getprop）"


# ---- merged from tests/test_r953_unknown_not_zero.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class _NoDevice:
    """什么都读不到的设备（采集进行中端口被占用的真实形态）。"""

    def _sh(self, *a, timeout=None):
        return ""


class _Offline(_NoDevice):
    def sh(self, *a, timeout=None):
        return ""


# ---------------------------------------------------------------------------
# 1. detect：读不到 = 未知，不是 0 分
# ---------------------------------------------------------------------------
def test_detect_unknown_not_zero():
    r = st.detect(_Offline())
    assert r.get("score") is None, "读不到设备不许报 0 分（0 分=检测到 13 条以上）"
    assert r.get("error"), "要留下读不到的证据"
    assert r.get("root") == [] and r.get("emulator") == []


def test_audit_unknown_not_phantom_leaks():
    r = fp.audit(_Offline())
    assert r.get("score") is None, "audit 读不到时不许算分"
    assert r.get("leaks") == [], \
        "props 为空时空 needle 会全部命中，必须提前返回"


# ---------------------------------------------------------------------------
# 2. 渲染：必须说"未知"，不能印成数字
# ---------------------------------------------------------------------------
def test_fmt_audit_score_unknown():
    assert "未知" in fp._fmt_audit_score({"score": None})
    assert "0 分" not in fp._fmt_audit_score({"score": None})


def test_fmt_audit_score_int():
    out = fp._fmt_audit_score({"score": 88, "score_note": "已到上限（x）"})
    assert "88 分" in out and "已到上限" in out, out
    # 不许出现嵌套括号（note 自己带括号时不能再套一层）
    assert "（已到上限（" not in out, out


def test_prepare_log_does_not_print_zero():
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    i = src.find("root/模拟器隐藏")
    seg = src[max(0, i - 200):i + 500]
    assert "自检 %d 分" not in seg, "日志还在用 %d 印分数（None 会崩或假报 0）"
    assert "未知" in seg, "日志没区分未知"


# ---------------------------------------------------------------------------
# 3. 下游不许把"未知"当风险
# ---------------------------------------------------------------------------
def test_riskscore_skips_unknown():
    src = io.open(os.path.join(ROOT, "core", "riskscore.py"),
                  encoding="utf-8").read()
    i = src.find("identity_score")
    seg = src[max(0, i - 400):i + 600]
    assert "is None" in seg, "riskscore 没跳过未知分数"


def test_app_base_filters_non_numeric_score():
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    assert "isinstance(ip.get(\"score\"), (int, float))" in src \
        or "isinstance(ip.get(" in src, "app_base 没过滤 None 分数"


# ---- merged from tests/test_r955_write_marker_unified.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _src(name: str) -> str:
    return io.open(os.path.join(ROOT, "core", "android", name),
                   encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. `write_remote` 统一 helper 存在
# ---------------------------------------------------------------------------
def test_write_remote_exists():
    assert hasattr(fp, "write_remote"), "没有统一的 write_remote"


def test_write_remote_signature():
    """签名：`write_remote(dev, path, text, *, timeout=None) -> bool`。"""
    import inspect
    sig = inspect.signature(fp.write_remote)
    params = list(sig.parameters.keys())
    assert params[:3] == ["dev", "path", "text"], params
    assert "timeout" in params, "不许丢失超时控制"


# ---------------------------------------------------------------------------
# 2. 3 个调用点都改成 write_remote
# ---------------------------------------------------------------------------
def test_stealth_marker_uses_write_remote():
    s = _src("stealth.py")
    assert "from .fingerprint import write_remote" in s, "stealth 没导入 write_remote"
    # 整个 prepare() 函数体里不许再出现 `echo ... > 标记` 这种写法
    # （标记写入发生在 hide() **之后**，所以窗口要盖到函数结尾）
    i = s.find("def prepare(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j if j > 0 else len(s)]
    assert "write_remote(" in body, "stealth 的 boot 标记没走 write_remote"
    assert 'echo %s > %s' not in body, \
        "prepare 里还在用 `sh -c \"echo X > path\"`（Windows 上静默失败）"


def test_emulator_tuning_marker_uses_write_remote():
    s = _src("emulator_tuning.py")
    assert "from .fingerprint import write_remote" in s
    # 找 boot 标记写入那段
    i = s.find("def ensure(")
    if i < 0:
        i = 0
    seg = s[i:]
    j = seg.find("_mark_path(vm)")
    if j > 0:
        # 标记写入附近 100 字内要有 write_remote
        nearby = seg[j:j + 200]
        assert "write_remote(" in nearby or "echo" not in nearby, \
            "emulator_tuning marker 还在用 echo >"


def test_fingerprint_marker_uses_write_remote():
    s = _src("fingerprint.py")
    i = s.find("def write_marker(")
    assert i > 0
    j = s.find("\ndef ", i + 10)
    body = s[i:j]
    assert "write_remote(" in body, "身份 marker 还在用 echo >"


# ---------------------------------------------------------------------------
# 3. fast path 仍要跑 refresh
# ---------------------------------------------------------------------------
def test_fast_path_still_refreshes_props():
    """本 boot 已 hide 过，但仍需重清厂商 props（nemuinit 会写回）。"""
    s = _src("stealth.py")
    i = s.find('if not force and boot and cur == boot:')
    assert i > 0
    seg = s[i:i + 700]
    assert "refresh(" in seg, \
        "fast path 直接 return（nemuinit 写回后没人管了）"


def test_hide_full_path_not_run_every_round():
    """确认 boot marker 机制生效：第二次 prepare 应返回 skipped。"""
    # 这个由真机实测确认（见文档里的例子），代码层面钉 fast path 分支存在
    s = _src("stealth.py")
    assert "done this boot" in s


# ---- merged from tests/test_r960_bootprops_build_id.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SYS_PROP = "\n".join([
    "ro.build.id=V417IR",
    "ro.build.display.id=V417IR release-keys",
    "ro.system.build.id=V417IR",
    "ro.system_ext.build.id=V417IR",
    "# ro.product.build.id=V417IR  (注释行不许被改)",
    "ro.product.system.brand=mumu_win",
    "ro.system.product.cpu.abilist=x86_64,arm64-v8a",
    "ro.system.build.fingerprint=mumu_win/mumu_win_x86_64/"
    "mumu_win_x86_64:15/V417IR/1171:user/release-keys",
    "dalvik.vm.isa.x86_64.variant=x86_64",
    "",
]) + "\n"
PRODUCT_PROP = "ro.product.build.id=V417IR\nro.product.brand=mumu_win\n"
VENDOR_PROP = "ro.vendor.build.id=V417IR\n"
ODM_PROP = "ro.odm.build.id=V417IR\n"


class _Dev:
    """内存文件系统 + 可控写入失败。"""

    def __init__(self, model="V2405A", writable=True, empty_files=()):
        self.files = {
            "/system/build.prop": SYS_PROP,
            "/system/system_ext/etc/build.prop": SYS_PROP,
            "/product/etc/build.prop": PRODUCT_PROP,
            "/vendor/build.prop": VENDOR_PROP,
            "/odm/etc/build.prop": ODM_PROP,
        }
        for p in empty_files:
            self.files[p] = ""          # 模拟"读不到"
        self.props = {"ro.product.model": model,
                      "ro.build.fingerprint":
                          "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys"}
        self.writable = writable
        self.pushed = []
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        if toks[:2] == ["shell", "getprop"] and len(toks) == 2:
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if toks[:2] == ["shell", "cat"] and len(toks) >= 3:
            return self.files.get(toks[2], "")
        if toks[:2] == ["shell", "ls"]:
            args = toks[2:]
            # `ls -d <path>`（存在性检查）与 `ls <path>` 都要能答
            p = args[1] if (args and args[0] == "-d") else (
                args[0] if args else "")
            return p if p in self.files else ""
        if toks[:2] == ["shell", "cp"]:
            _src, dst = toks[3], toks[4]
            if _src in self.files:
                self.files[dst] = self.files[_src]
            return ""
        if toks[:2] == ["shell", "mount"]:
            return ""
        return ""

    def push(self, local, remote):
        if not self.writable:
            return False
        with open(local, encoding="utf-8") as f:
            self.files[remote] = f.read()
        self.pushed.append(remote)
        return True


def _pool_entry(model="V2405A"):
    for p in PHONE_POOL:
        if p.get("model") == model:
            return p
    raise AssertionError("池里没有 %s（机型池被改了？本测试的前提失效）" % model)


# ---------------------------------------------------------------------------
# 1. 取值来自既有机型池，且只有 build.id 一族会被改
# ---------------------------------------------------------------------------
def test_resolve_and_desired_come_from_pool():
    prof = bp.resolve({"ro.product.model": "V2405A"})
    assert prof is _pool_entry(), "取值来源不是 PHONE_POOL（两处定义迟早漂移）"
    want = bp.desired(prof)
    assert want["ro.build.id"] == prof["build_id"]
    assert want["ro.build.display.id"] == "%s release-keys" % prof["build_id"]
    # 绝不该出现 abi / hardware / fingerprint 这类键
    assert not [k for k in want if "abi" in k or "hardware" in k
                or "fingerprint" in k], want


def test_plan_only_touches_allowlisted_keys():
    d = _Dev()
    pl = bp.plan(d)
    assert pl["profile_found"] is True
    todo = pl["files"]["/system/build.prop"]
    keys = {k for k, _o, _n in todo}
    assert keys <= set(bp.KEY_FIELDS) | {bp.DISPLAY_KEY}, keys
    # 反例：这些键在文件里也是 mumu/V417IR，但**不许**被顺手改掉
    for guarded in ("ro.system.product.cpu.abilist",
                    "dalvik.vm.isa.x86_64.variant",
                    "ro.product.system.brand",
                    "ro.system.build.fingerprint"):
        assert guarded not in keys, "白名单漏了，把运行期依赖也圈进来了"


def test_plan_skips_comment_lines():
    d = _Dev()
    pl = bp.plan(d)
    keys = {k for k, _o, _n in pl["files"]["/system/build.prop"]}
    assert "ro.product.build.id" not in keys, "注释行里的键不该进计划"


# ---------------------------------------------------------------------------
# 2. 写入：改对的东西、保住无关内容、可回滚
# ---------------------------------------------------------------------------
def test_apply_rewrites_ids_and_keeps_everything_else():
    d = _Dev()
    prof = _pool_entry()
    rep = bp.apply(d)
    assert rep["ok"] is True and rep["restart_required"] is True, rep
    assert rep["verified"] is True
    body = d.files["/system/build.prop"]
    assert "ro.build.id=%s" % prof["build_id"] in body
    assert "ro.build.display.id=%s release-keys" % prof["build_id"] in body
    # 未动的行必须原样在（尤其 abilist / dalvik / 注释行）
    assert "ro.system.product.cpu.abilist=x86_64,arm64-v8a" in body
    assert "dalvik.vm.isa.x86_64.variant=x86_64" in body
    assert "# ro.product.build.id=V417IR  (注释行不许被改)" in body
    assert len(body.rstrip("\n").splitlines()) == \
        len(SYS_PROP.rstrip("\n").splitlines()), "行数变了（结构被动过）"


def test_apply_backs_up_once_and_is_idempotent():
    d = _Dev()
    first = bp.apply(d)
    assert first["changed"] > 0 and first["backups"], first
    second = bp.apply(d)
    assert second["changed"] == 0, "第二次还在改 → 不幂等"
    assert second["restart_required"] is False, "无事可做却要求重启"
    # 关键：已有备份不能被"改后的版本"覆盖，否则回滚点就没了。
    # 备份路径用 `bp._bak_path()` 取，别在测试里重述命名规则（我第一版
    # 硬编码成 "_system_build.prop…" 猜错了前缀，白挂一条测试）。
    assert d.files[bp._bak_path("/system/build.prop")] == SYS_PROP
    assert len(second["backups"]) == 0


def test_each_partition_gets_its_own_backup():
    """五个文件 basename 全是 `build.prop` —— 共用一个备份名会出大事：

    * 除第一个之外的分区**没有回滚点**（`ls` 已非空 → 跳过备份）；
    * `restore()` 会把 /system 的原件灌进 /product、/vendor、/odm
      → 那是把设备写坏，不是回滚。
    """
    d = _Dev()
    rep = bp.apply(d)
    assert len(set(rep["backups"])) == len(rep["backups"]) == 5, rep["backups"]
    for p in bp.BUILD_PROPS:
        bak = bp._bak_path(p)
        assert bak in rep["backups"], (p, bak)
        assert d.files[bak] == {
            "/system/build.prop": SYS_PROP,
            "/system/system_ext/etc/build.prop": SYS_PROP,
            "/product/etc/build.prop": PRODUCT_PROP,
            "/vendor/build.prop": VENDOR_PROP,
            "/odm/etc/build.prop": ODM_PROP,
        }[p], "备份内容串了"


def test_apply_refuses_when_model_not_in_pool():
    d = _Dev(model="ZZZ-999")
    rep = bp.apply(d)
    assert rep["ok"] is False and rep["changed"] == 0, rep
    assert "不在 PHONE_POOL" in rep["skipped"]
    assert d.pushed == [], "机型认不出来还硬写 = 凭猜塞 build 号"


def test_apply_never_writes_empty_content():
    """文件存在但内容为空 → 必须跳过写入**并让报告带伤**。

    两件事都要成立，缺一都是骗人：
    * 不 push 空内容（那会把设备写坏）；
    * 不能因为"没有可改项"就返回 ok=True —— 那里的 `V417IR` 还在，
      App 依然读得到，这是**部分完成**，不是完成。
    """
    d = _Dev(empty_files=("/vendor/build.prop",))
    rep = bp.apply(d)
    assert "/vendor/build.prop" not in d.pushed, "空内容被 push 上去了"
    assert any("读不到内容" in x for x in rep["failed"]), rep["failed"]
    assert rep["ok"] is False and rep["verified"] is False, rep
    # 其它分区仍应正常完成（一处失败不该拖垮整件事）
    assert "/system/build.prop" in rep["files"]


def test_apply_reports_readonly_partition_honestly():
    """只读分区：push 一直失败 → 绝不能报"全改好了"。"""
    d = _Dev(writable=False)
    rep = bp.apply(d)
    assert rep["ok"] is False and rep["changed"] == 0, rep
    assert rep["verified"] is False
    assert any("只读" in x or "写入失败" in x for x in rep["failed"]), rep["failed"]
    assert rep["restart_required"] is False, "什么都没写成，不该要求重启"


def test_apply_respects_config_off():
    d = _Dev()
    rep = bp.apply(d, config={"android": {"boot_props": {"enabled": False}}})
    assert rep["skipped"] == "config 关闭" and d.pushed == []


# ---------------------------------------------------------------------------
# 3. 回滚
# ---------------------------------------------------------------------------
def test_restore_brings_original_back():
    d = _Dev()
    bp.apply(d)
    assert "ro.build.id=V417IR" not in d.files["/system/build.prop"]
    rep = bp.restore(d)
    assert rep["ok"] is True and "/system/build.prop" in rep["restored"], rep
    assert d.files["/system/build.prop"] == SYS_PROP


def test_offline_device_does_not_crash():
    assert bp.apply(_Dev(model=""))["ok"] is False


# ---- merged from tests/test_r969_non_attempt_not_a_sample.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _p(path, status, rows=0):
    return {"path": path, "status": status, "rows": rows}


# ---------------------------------------------------------------------------
# 1. 不算样本的轮次
# ---------------------------------------------------------------------------
def test_only_infra_restore_is_not_a_sample():
    """只有快照恢复：说明的是设备状态，不是站点反应。"""
    assert is_non_attempt([_p("snap-restore", "error")]) is True
    assert is_non_attempt([_p("snap-restore", "ok", rows=0)]) is True


def test_unsupported_route_is_not_a_sample():
    """android-runtime/unsupported = 本渠道不支持该通路，**根本没尝试**。"""
    assert is_non_attempt([_p("android-runtime", "unsupported")]) is True


def test_paced_is_not_a_sample():
    """我方主动让位（配额/节流）：既不是成功也不是失败。"""
    assert is_non_attempt([_p("app-list", "paced")]) is True
    assert is_paced([_p("app-list", "paced")]) is True


def test_infra_plus_unsupported_is_not_a_sample():
    assert is_non_attempt([_p("snap-restore", "error"),
                           _p("android-runtime", "unsupported")]) is True


# ---------------------------------------------------------------------------
# 2. 真实样本（**不许**借这个口子把真失败洗白）
# ---------------------------------------------------------------------------
def test_login_wall_is_a_real_sample():
    assert is_non_attempt([_p("app-login", "login")]) is False


def test_timeout_is_a_real_sample():
    assert is_non_attempt([_p("app-list", "timeout")]) is False


def test_empty_listing_is_a_real_sample():
    assert is_non_attempt([_p("app-list", "empty")]) is False


def test_success_is_a_real_sample():
    assert is_non_attempt([_p("app-calendar", "ok", rows=40)]) is False


def test_mixed_with_real_attempt_is_a_sample():
    """只要有一条真打站点，这轮就是样本（哪怕另一条是基础设施）。"""
    assert is_non_attempt([_p("snap-restore", "error"),
                           _p("app-calendar", "empty")]) is False


def test_no_paths_is_not_non_attempt():
    """没有通路记录时**不**判成"非采集轮"（那是未知，不是结论）。"""
    assert is_non_attempt([]) is False
    assert is_non_attempt(None) is False


# ---------------------------------------------------------------------------
# 3. 边界：白名单必须窄
# ---------------------------------------------------------------------------
def test_infra_list_stays_narrow():
    """基础设施白名单只能装"永远不出行"的通路。

    一旦把 `app-list` / `app-calendar` 这类真数据通路塞进来，
    真实失败就会被静默排除，成功率虚高——那比低估更危险。
    """
    for bad in ("app-list", "app-calendar", "app-detail", "h5", "pc"):
        assert bad not in INFRA_PATHS, "%s 是真数据通路，不能算基础设施" % bad
    assert "snap-restore" in INFRA_PATHS
    assert "android-runtime" in INFRA_PATHS


# ---- merged from tests/test_v15122_cabin_guard.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _mis(price=2615, biz=7800, cabin="公务舱"):
    return {"cabin": cabin, "price": price, "bizPrice": biz}


def test_cabin_clean_drops_mislabeled_high_cabin():
    # 串舱硬证：高档标签 + 行价低于公务参考价 → 标签置空（宁缺勿错）
    assert cabin_clean(_mis()) == ""


def test_cabin_clean_keeps_true_business_selection():
    # 真公务选中（r222 修复后唯一合法形态）：price==bizPrice 原样保留
    assert cabin_clean(_mis(price=7800)) == "公务舱"
    assert cabin_clean(_mis(price=7801)) == "公务舱"


def test_cabin_clean_keeps_without_bizprice():
    # 无 bizPrice 行不可内证：维持原值（守卫不越权）
    assert cabin_clean({"cabin": "公务舱", "price": 2615}) == "公务舱"
    assert cabin_clean({"cabin": "头等舱"}) == "头等舱"


def test_cabin_clean_passes_economy_and_odd_words():
    # 只查高档舱词；经济舱/空值/怪码不受影响
    assert cabin_clean(_mis(cabin="经济舱")) == "经济舱"
    assert cabin_clean(_mis(cabin="超级经济舱")) == "超级经济舱"
    assert cabin_clean({"cabin": "", "price": 1, "bizPrice": 2}) == ""


def test_cabin_text_uses_guard():
    # webui 舱位描述集成：串舱行不出「公务舱」词面
    f = _mis()
    f["plane"] = "空客320"
    assert "公务舱" not in cabin_text(f)
    assert "空客320" in cabin_text(f)
    f2 = _mis(price=7800)
    f2["plane"] = "空客320"
    assert "公务舱" in cabin_text(f2)


def test_outlier_not_triggered_by_mislabeled_cabin():
    # 比价组离群判定：串舱行不再制造「跨舱位」假离群
    fs = [{"cabin": "经济舱", "price": 2600},
          {"cabin": "经济舱", "price": 2610},
          {"cabin": "公务舱", "price": 2615, "bizPrice": 7800}]
    assert Alerter._outlier(fs) is False
    # 真跨舱位（价差 2×+）仍判离群：守卫不豁免真实信号
    fs2 = [{"cabin": "经济舱", "price": 2600},
           {"cabin": "公务舱", "price": 7800}]
    assert Alerter._outlier(fs2) is True


def test_cabin_clean_covers_letter_codes():
    # r222 推送审校 P0：qunar 单字母高档码（_cabin_cn 映射在查纯域
    # 之后曾整体绕过守卫）——￥2416 经济舱行实推成「头等舱」，48h
    # 冻结库 1,456 条字母码 85.7% 价位矛盾。守卫查映射后的语义类。
    assert cabin_clean({"cabin": "F", "price": 2416, "bizPrice": 5200}) == ""
    assert cabin_clean({"cabin": "A", "price": 2416, "bizPrice": 5200}) == ""
    assert cabin_clean({"cabin": "C", "price": 2600, "bizPrice": 7800}) == ""
    assert cabin_clean({"cabin": "J", "price": 2600, "bizPrice": 7800}) == ""
    # 真高档选中（字母码行 price==bizPrice）：原码保留（显示层再映射）
    assert cabin_clean({"cabin": "J", "price": 5200, "bizPrice": 5200}) == "J"
    assert cabin_clean({"cabin": "F", "price": 9900, "bizPrice": 5200}) == "F"
    # 经济舱族字母码不查
    assert cabin_clean({"cabin": "Y", "price": 100, "bizPrice": 9900}) == "Y"
    assert cabin_clean({"cabin": "M", "price": 100, "bizPrice": 9900}) == "M"
    # 无 bizPrice 字母码行不可内证：维持原值
    assert cabin_clean({"cabin": "F", "price": 2416}) == "F"


def test_cabin_class_single_source():
    # 大类映射上收 flightnorm 单源：alerter._cabin_cn 变委托同函数
    from core.alerter import _cabin_cn
    from core.flightnorm import cabin_class
    assert _cabin_cn is cabin_class
    assert cabin_class("F") == "头等舱"
    assert cabin_class("Y") == "经济舱"
    assert cabin_class("经济舱") == "经济舱"
    assert cabin_class("超级经济舱") == "超级经济舱"
    assert cabin_class("42") == ""          # 怪码宁缺勿错
    assert cabin_class("") == ""


# ---- merged from tests/test_v295_prov.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_fetch_path_and_prov_round_trip(tmp_path):
    st = PriceStorage(str(tmp_path / "p.db"))
    pid = st.save_fetch_path("ctrip", "SHA", "BJS", "2026-11-10",
                             "PC", "ok", rows=12)
    fp = FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500,
                     prov=json.dumps({"entryPath": "PC", "pathId": pid,
                                      "pathStatus": "ok",
                                      "evidenceLevel": "path",
                                      "kind": "detail"}))
    st.save(fp)
    row = st.last_lowest("SHA", "BJS", "2026-11-10")
    assert json.loads(row["prov"])["entryPath"] == "PC"
    paths = st.fetch_paths("SHA", "BJS", "2026-11-10")
    assert paths[0]["entry_path"] == "PC"
    assert paths[0]["evidence_level"] == "path"


def test_flight_price_prov_defaults_empty():
    assert FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500).prov == ""


def test_scan_source_pins_path_level_evidence():
    with open(main.__file__, encoding="utf-8") as f:
        src = f.read()
    for s in ('"entryPath"', '"pathStatus"', '"evidenceLevel": "path"',
              "storage.save_fetch_path", "p.prov = prov"):
        assert s in src, s
