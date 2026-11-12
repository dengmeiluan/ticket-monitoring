# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_app_path_gate.py
- tests/test_r1063_halt_scope.py
- tests/test_r1063_radar_path_gate.py
- tests/test_r1063_stall_on_path_note.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.special_radar as sr
import datetime as dt
import io
import logging
import os
import pytest
import re
import sys
import tempfile
import time

from contextlib import contextmanager
from core import policy, strategy_params as sp
from core.pacing import PATH_DISABLED, PATH_HALTED, Pacing
from crawlers.app_base import AppCrawler


# ---- merged from tests/test_r1063_app_path_gate.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: App 五家（文件级源码锚点）
_FIVE = ("app_ctrip.py", "app_qunar.py", "app_fliggy.py",
         "app_tongcheng.py", "app_zhixing.py")

#: 每家要问到的**主阶段**。智行没有独立的价格日历入口（日历价走的是
#: 明细页弹层，`_emit_calendar`），所以它只有四个阶段要闸——不是漏做，
#: 是那一家没有这个入口；给它编一个空壳 `calendar()` 才是自欺。
_STAGES = {
    "app_ctrip.py": ("app-login", "app-list", "app-calendar",
                     "往返", "low-fare"),
    "app_qunar.py": ("app-login", "app-list", "app-calendar",
                     "往返", "low-fare"),
    "app_fliggy.py": ("app-login", "app-list", "app-calendar",
                      "往返", "low-fare"),
    "app_tongcheng.py": ("app-login", "app-list", "app-calendar",
                         "往返", "low-fare"),
    "app_zhixing.py": ("app-login", "app-list", "往返", "low-fare"),
}

#: **不许**接闸门的细段：它们属于同一次 App 交互的内部小步，停一段
#: 等于把整条链路停成「什么都采不到」，矩阵对它们记 `na`。
_SUB_STEPS = ("app-city", "app-date", "app-form", "app-search", "app-dump",
              "app-blocker", "app-block", "app-mode", "app-roundtrip",
              "android-runtime", "android-device", "android-ocr",
              "android-u2")


@pytest.fixture(autouse=True)
def _clean_params():
    """`strategy_params` 是模块级单例：用例装的覆盖必须还原，否则会漏给
    同进程里后面的用例（那类「上一个用例的配置还在」的假绿最难查）。"""
    from core import strategy_params as sp
    sp.invalidate()
    yield
    sp.invalidate()


def _src(name):
    return io.open(os.path.join(_ROOT, "crawlers", name),
                   encoding="utf-8").read()


def _disable_scope(key):
    """把某个 `渠道/维度/链路` 上的 path_fallback 关掉（T7 的读点）。"""
    from core import strategy_params as sp
    sp.set_config({"crawler": {
        "rate": {"min_gap_s": 0, "per_minute": 0},
        "strategy_overrides": {key: {"path_fallback.enabled": False}}}})


def _pacing(min_gap_s=0, per_minute=0):
    from core.pacing import Pacing
    return Pacing({"crawler": {"rate": {"min_gap_s": min_gap_s,
                                        "per_minute": per_minute}}})


# ---------------------------------------------------------------- 源码锚点

def test_each_app_crawler_gates_the_main_stages_but_not_the_sub_steps():
    """(0) 五个主阶段逐个问闸门；细段一处都不许问。"""
    for fn in _FIVE:
        body = _src(fn)
        assert "path_gate(" in body, "%s 没问链路闸门" % fn
    for fn, stages in _STAGES.items():
        body = _src(fn)
        for stage in stages:
            assert 'path_gate("%s"' % stage in body, (
                "%s 的「%s」阶段入口没有问链路闸门：用户想停这一个阶段时"
                "无处可停" % (fn, stage))
    for fn in _FIVE:
        body = _src(fn)
        for sub in _SUB_STEPS:
            assert 'path_gate("%s' % sub not in body, (
                "%s 把细段「%s」也接上了闸门：停一段等于停整条链路"
                "（矩阵里这些细段记 na）" % (fn, sub))


def test_app_base_writes_down_why_the_sub_steps_are_not_gated():
    """细段不闸的理由必须写在源码里，别只活在这个任务的口头约定里。"""
    base = _src("app_base.py")
    assert "细段属单次交互内部" in base, "细段不接闸门的理由没写进源码"
    assert "na" in base, "没有说明矩阵对细段记 na（而不是记成待补的 n）"


def test_app_base_exposes_the_gate_with_the_browser_base_shape():
    """`AppCrawler.path_gate` 必须与 `BaseCrawler` 同形，不是第二套发明。"""
    base = _src("app_base.py")
    assert "def path_gate(self, path" in base, "App 基类没有 path_gate 包装"
    assert 'path_note(path, "paced"' in base, \
        "被停用的阶段没记 paced（会被当成渠道失败）"
    # 等待必须封顶：源码里要能看见上限被作用到 sleep 上（铁律 I6）
    assert "time.sleep(min(wait, PATH_GATE_SLEEP_CAP_S))" in base, \
        "闸门的等待没有上限（铁律 I6：每处 sleep 都要有上限）"
    # 配置层包装只认浏览器基类那一份，别抄第二个
    assert "pacing_cfg_for" in base, \
        "App 侧的 Pacing 没走 pacing_cfg_for：会永远跑在 DEFAULTS 上"


# ---------------------------------------------------------------- 行为验证

class _FakeApp(AppCrawler):
    """只借用基类的闸门与账本，不建设备/资料目录。"""
    name = "app_ctrip"


class _LockedRuntime:
    """只回答「设备锁在谁手里」的假运行时（闸门据此判断是否在锁内）。"""

    def __init__(self, owner: str):
        self.owner = owner

    def lock_state(self):
        return {"owner": self.owner, "since": 0.0}


def _fake(pac=None, locked=False):
    c = object.__new__(_FakeApp)
    c.config = {}
    c.logger = logging.getLogger("t_app_path_gate")
    if pac is not None:
        c._pacing = pac
    c.path_reset()
    if locked:
        c._runtime = _LockedRuntime("app_ctrip")
    return c


def test_disabled_stage_is_skipped_with_paced_evidence():
    """(a) 被策略停用的阶段：返回 False，账本是 `paced`，不是失败。"""
    from core.pacing import PATH_DISABLED
    _disable_scope("app_ctrip/detail/app-list")
    c = _fake(_pacing())
    assert c.path_gate("app-list", "detail") is False
    assert c.paths, "被停用的阶段必须留证，否则面板看不出为什么没数据"
    last = c.paths[-1]
    assert last["path"] == "app-list"
    assert last["status"] == "paced", (
        "记成 %s 会被当成渠道失败而触发整家熔断（连坐）" % last["status"])
    assert PATH_DISABLED in last["detail"], "证据里没说清是「链路被策略停用」"


def test_the_other_stage_of_the_same_instance_still_passes():
    """(b) 停用只对点名的阶段生效，同一实例的其它阶段照常放行。"""
    _disable_scope("app_ctrip/detail/app-list")
    c = _fake(_pacing())
    assert c.path_gate("app-list", "detail") is False
    assert c.path_gate("app-calendar", "calendar") is True, "停列表不许连坐日历"
    assert c.path_gate("往返", "round_trip") is True, "停列表不许连坐往返"
    assert c.path_gate("low-fare", "low_fare") is True, "停列表不许连坐低价"


def test_wait_is_capped_at_fifteen_seconds(monkeypatch):
    """(c1) `wait_s` 上限 15s（铁律 I6：每处 sleep 都要有累计上限）。"""
    import crawlers.app_base as B
    from core import strategy_params as sp
    sp.set_config({"crawler": {"rate": {"min_gap_s": 300, "per_minute": 0}}})
    c = _fake(_pacing(min_gap_s=300))
    slept = []
    monkeypatch.setattr(B.time, "sleep", lambda s: slept.append(s))
    assert c.path_gate("app-list", "detail") is True    # 桶里没记录 → 不等
    assert c.path_gate("app-list", "detail") is True    # 该等 300s，但必须封顶
    assert slept, "闸门必须真的等一次，否则限速形同虚设"
    # 断言「真的被截到 15」，不是「没超过 15」（复核 2026-11-06 同一口径）：
    # 该等 300s、上限 15s → 必须**恰好**睡 15s。
    assert max(slept) == pytest.approx(15.0), (
        "等待没有被截到上限 15s（实际 %r 秒）" % (max(slept),))


def test_gate_never_sleeps_while_the_device_lock_is_held(monkeypatch, caplog):
    """(c2) 持有设备锁时**不睡**：设备串行独占，闸门一睡别人全陪跑。

    接线上的主措施是「在拿锁之前问」（五家的 `fetch`/`calendar`/`low_fare`
    都这么写）；这条用例钉的是**兜底**：万一将来有人在锁里问，闸门也不许
    把采集线程钉在等待上——宁可这一轮少等，也不占着设备睡。
    """
    import crawlers.app_base as B
    from core import strategy_params as sp
    sp.set_config({"crawler": {"rate": {"min_gap_s": 300, "per_minute": 0}}})
    c = _fake(_pacing(min_gap_s=300), locked=True)
    slept = []
    monkeypatch.setattr(B.time, "sleep", lambda s: slept.append(s))
    assert c.path_gate("app-list", "detail") is True
    with caplog.at_level(logging.WARNING):
        assert c.path_gate("app-list", "detail") is True
    assert slept == [], "持有设备锁时睡了 %r 秒：排队等锁的渠道全体陪跑" % (slept,)
    assert any("设备锁" in r.getMessage() for r in caplog.records), \
        "在锁内跳过等待必须留痕，否则限速被静默关掉"


def test_gate_sleeps_once_the_lock_is_not_held(monkeypatch):
    """(c3) 负控：锁不在手里时照常（封顶地）等，别把限速整段关掉。"""
    import crawlers.app_base as B
    from core import strategy_params as sp
    sp.set_config({"crawler": {"rate": {"min_gap_s": 300, "per_minute": 0}}})
    c = _fake(_pacing(min_gap_s=300))          # 没有运行时 → 视为没持锁
    slept = []
    monkeypatch.setattr(B.time, "sleep", lambda s: slept.append(s))
    assert c.path_gate("app-list", "detail") is True
    assert c.path_gate("app-list", "detail") is True
    assert max(slept) == pytest.approx(15.0)


def test_crawler_records_the_path_bucket_only():
    """(d) 只记链路桶：渠道桶的账归 `main.py`，重复记会翻倍。"""
    pac = _pacing()
    pac.record("app_ctrip")                # main.py 已为这条查询记过渠道级
    c = _fake(pac)
    assert c.path_gate("app-list", "detail") is True
    win = pac._bucket._win
    assert len(list(win.get("app_ctrip") or ())) == 1, \
        "渠道桶被记了两次：per_minute 会减半、min_gap 会翻"
    assert len(list(win.get("app_ctrip|app-list") or ())) == 1, "链路桶没记上"


def test_old_record_signature_records_nothing_instead_of_double_counting():
    """(e) `record` 不吃 `channel=` 时**不记**，不退回带渠道口径的写法。"""

    class _OldSignaturePacing:
        def __init__(self):
            self.calls = []

        def gate_path(self, plat, dim="", path=""):
            return True, 0.0, ""

        def record(self, plat, now=None, *, path=""):
            self.calls.append((plat, path))

    pac = _OldSignaturePacing()
    c = _fake(pac)
    assert c.path_gate("app-list", "detail") is True, \
        "闸门不能因为记账签名变红就停采"
    assert pac.calls == [], (
        "旧签名下退回 `record(plat, path=path)`：渠道桶与链路桶各记一次，"
        "per_minute 当场减半、min_gap 当场翻倍——宁可这条链路少记一次账")


# ------------------------------------------------- 行为级：接线是否真的生效

class _FakeRuntime:
    """够 ctrip 的 `fetch()` 跑起来的假运行时（不碰 adb）。"""

    def __init__(self):
        self.lock_uses = 0

    def ensure_ready(self):
        return True, ""

    def device(self):
        return object()

    @contextmanager
    def device_lock(self, timeout=600.0, owner=""):
        self.lock_uses += 1
        yield

    def lock_state(self):
        return {"owner": "" if not self.lock_uses else "app_ctrip",
                "since": 0.0}


def _ctrip():
    from unittest import mock as _m
    from crawlers.app_ctrip import AppCtripCrawler
    c = AppCtripCrawler({"user_data_dir": tempfile.mkdtemp()},
                        logging.getLogger("t_app_path_gate"))
    rt = _FakeRuntime()
    c._runtime = rt
    # 用例里的日期与「今天」无关：把视野放到足够远，判据只验闸门接线
    c.date_horizon_days = 36500
    c.prepare_device = lambda dev: None
    c._ensure_app_fresh = lambda dev: True
    c._ensure_form = _m.MagicMock(return_value="<hierarchy/>")
    c._set_one_way_mode = lambda dev: True
    c._set_route = lambda dev, a, b: True
    c._one_date = _m.MagicMock(return_value=None)
    c._pacing = _pacing()
    return c, rt


def test_disabled_stage_returns_empty_without_taking_the_device_lock():
    """被停用的阶段：**连设备锁都不拿**，一条失败都不记。

    这条钉的是复核最可能放过的形态：闸门接在锁里、或接在 `_ensure_form`
    之后——账本上确实写着 `paced`，但设备已经被占用、App 已经被点开，
    用户「停掉一个阶段」反而更费时间。
    """
    _disable_scope("app_ctrip/detail/app-list")
    c, rt = _ctrip()
    assert c.fetch("SHA", "BJS", ["2026-11-20"]) == []
    assert rt.lock_uses == 0, "被停用的阶段仍去拿设备锁：白占一台串行设备"
    assert c._ensure_form.call_count == 0, "被停用的阶段仍去动 App"
    assert [p["status"] for p in c.paths if p["path"] == "app-list"] == ["paced"]
    assert not [p for p in c.paths if p["status"] in ("timeout", "error")], (
        "把「按策略停用」记成失败：整家渠道的熔断被拉开（连坐）")


def test_enabled_stage_still_runs_the_whole_chain():
    """负控：闸门放行时行为一字不变（拿锁、进表单、逐日查）。"""
    c, rt = _ctrip()
    assert c.fetch("SHA", "BJS", ["2026-11-20"]) == []
    assert rt.lock_uses == 1, "闸门放行却漏了设备锁"
    assert c._ensure_form.call_count == 1
    assert c._one_date.call_count == 1, "放行时逐日查询没跑"
    assert not [p for p in c.paths if p["status"] == "paced"]


# ------------------------------------------- 复核修复（r1063 T9 二轮）
#
# 以下四组钉复核提出的三件事：①去哪儿「停 low-fare 连坐 app-calendar」的
# 静默绑架；②「闸门必须在设备锁之前」不能只有 ctrip 一条用例兜着；
# ③`_pacing_ctx` 构造失败后的告警风暴与丢失的刷新边界说明。

def _qunar():
    """够 `app_qunar.calendar()` 跑起来的假实现（不碰 adb）。"""
    from crawlers.app_qunar import AppQunarCrawler
    c = AppQunarCrawler({"user_data_dir": tempfile.mkdtemp()},
                        logging.getLogger("t_app_path_gate"))
    c._runtime = _FakeRuntime()
    c.prepare_device = lambda dev: None

    def _fake_locked(dev, from_city, to_city, days):
        # 真机里 `_low_fare_locked` 会把日历日格写进 `_calendar_rows`
        rows = [{"date": "2026-11-20", "price": 410},
                {"date": "2026-11-21", "price": 358}]
        c._calendar_rows = list(rows)
        return [dict(r) for r in rows]

    c._low_fare_locked = _fake_locked
    c._pacing = _pacing()
    return c


def test_disabling_low_fare_does_not_kill_the_qunar_calendar():
    """停「低价」只停特价发现源：`app-calendar` 必须照跑。

    `calendar()` 与 `low_fare()` 共用同一次设备交互（同一个低价页），但
    是**两条通路**。原实现里 `calendar()` 直接穿 `low_fare()` 的闸门，
    于是停 low-fare 会把日历一起清空、且一条 `app-calendar` 证据都不留
    ——用户「停掉一个发现源」，结果连日历维度都没了（连坐）。
    """
    _disable_scope("app_qunar/low_fare/low-fare")
    c = _qunar()
    rows = c.calendar("BJS", "SHA")
    assert rows, "停掉 low-fare 把 app-calendar 一起清空了（连坐）"
    assert not [p for p in c.paths if p["path"] == "low-fare"], (
        "日历通路不该再留下 low-fare 的账：它压根没走那一档闸门")


def test_disabling_the_qunar_calendar_stage_is_recorded_as_paced():
    """停「日历」要留下 `app-calendar` 的 paced 证据，且连设备都不碰。"""
    _disable_scope("app_qunar/calendar/app-calendar")
    c = _qunar()
    assert c.calendar("BJS", "SHA") == []
    assert c._runtime.lock_uses == 0, "被停用的日历仍去拿设备锁"
    assert [p["status"] for p in c.paths
            if p["path"] == "app-calendar"] == ["paced"]


def _lock_blocks(src):
    """`with rt.device_lock(...)` 块的 (起始行, 结束行)，1-based、含首行。

    块的边界按缩进推：同 `with` 之后，第一行缩进 <= `with` 缩进的非空行
    就是块外。故意不引 AST——要钉的就是**源码顺序**这个事实，用 AST
    反而看不见"只是写在了同一行/同一块里"。
    """
    lines = src.splitlines()
    blocks = []
    for i, line in enumerate(lines):
        s = line.lstrip()
        if not (s.startswith("with ") and "device_lock(" in s):
            continue
        indent = len(line) - len(s)
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                break
            j += 1
        blocks.append((i + 1, j))
    return blocks


def test_every_gate_is_asked_before_the_device_lock_is_taken():
    """**24 处**闸门逐一钉在锁外，不是只靠 ctrip 那一条行为用例。

    App 渠道的设备是串行独占的：闸门一问就可能要等（封顶 15s），在
    `with rt.device_lock(...)` **里面**等，等于让排队等锁的其它 App 渠道
    替我们睡；而且 `set_deadline(预算)` 是拿锁时 arm 的，锁内等待还会吃
    采集预算。这条用例按源码形状把整份文件扫一遍，将来谁把闸门挪进锁里
    就会立刻变红（`test_gate_never_sleeps_while_the_device_lock_is_held`
    只是兜底，不能替代"写在锁外"）。
    """
    total = 0
    for fn in _FIVE:
        src = _src(fn)
        blocks = _lock_blocks(src)
        assert blocks, "%s 里一个 device_lock 都没找到：守卫本身失效了" % fn
        gates = 0
        for ln, line in enumerate(src.splitlines(), 1):
            if "path_gate(" not in line:
                continue
            gates += 1
            inside = [b for b in blocks if b[0] <= ln <= b[1]]
            assert not inside, (
                "%s:%d 的闸门落在设备锁里（%r）：闸门要等时会把排队等锁的"
                "其它 App 渠道一起钉住" % (fn, ln, line.strip()))
        assert gates, "%s 一处闸门都没有" % fn
        total += gates
    assert total == 24, (
        "闸门调用点数量变了（现在 %d，应为 24 = 五家阶段入口总数）："
        "增减阶段时请同步这条用例与 _STAGES" % total)


def test_gate_construction_failure_warns_once_and_keeps_passing(monkeypatch,
                                                               caplog):
    """`Pacing` 构造不出来时：只告警**一次**，且每次闸门都放行。

    原实现把失败存成 `None`，下一处闸门又见到 `None` → 又重建 → 又告警：
    一次 `fetch()`（登录/列表两段）就能刷 2–3 条同样的 warning，日志里
    看起来像"闸门反反复复坏掉"。构造失败是环境级事实，一次说清就够。
    """
    import core.pacing as P

    class _BoomPacing:
        def __init__(self, cfg=None, clock=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(P, "Pacing", _BoomPacing)
    c = _fake()                       # 故意不注入 `_pacing`
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert c.path_gate("app-list", "detail") is True, \
                "闸门构造不出来时必须放行（否则整家渠道停采）"
    hits = [r for r in caplog.records if "链路闸门不可用" in r.getMessage()]
    assert len(hits) == 1, "构造失败要只告警一次，实际 %d 次" % len(hits)
    assert not c.paths, "放行时不该凭空留证据"


def test_app_pacing_ctx_documents_the_refresh_boundary():
    """App 侧那份 `_pacing_ctx` 必须写清「私有实例不会跟着热重载刷新」。

    浏览器侧（`crawlers/base.py:608-614`）写了这一段边界；App 侧是同一份
    构造逻辑的副本，把这句丢了，下一个人会以为改 `crawler.rate` 能热生效。
    """
    body = _src("app_base.py")
    i = body.index("def _pacing_ctx")
    seg = body[i:body.index("def _device_lock_held", i)]
    for word in ("refresh", "clear_crawlers", "参数层"):
        assert word in seg, (
            "_pacing_ctx 的 docstring 丢了刷新边界说明（缺 %r）：私有实例"
            "不会随热重载 refresh()，配置只在采集器实例重建时重读，速率主要"
            "由参数层决定" % word)


# ---- merged from tests/test_r1063_halt_scope.py ----

@pytest.fixture()
def prof():
    return tempfile.mkdtemp()


# ---------------- 键与查找 ----------------

def test_halt_key_shapes_stay_backward_compatible():
    assert policy.halt_key("ctrip") == "ctrip"                  # 渠道级不变
    assert policy.halt_key("ctrip", "") == "ctrip"
    assert policy.halt_key("ctrip", "intl") == "ctrip/intl"
    assert policy.halt_key("ctrip", "detail/H5/API") == "ctrip/detail/H5/API"
    assert policy.halt_key("ctrip", "/intl/") == "ctrip/intl"


def test_halt_for_prefers_path_then_dim_then_channel():
    halts = {
        "ctrip": {"until": time.time() + 600},
        "ctrip/intl": {"until": time.time() + 600},
        "ctrip/intl/H5": {"until": time.time() + 600},
    }
    k, _ = policy.halt_for(halts, "ctrip", "intl", "H5")
    assert k == "ctrip/intl/H5"
    k, _ = policy.halt_for(halts, "ctrip", "intl", "PC")
    assert k == "ctrip/intl"          # 链路没命中 → 维度
    k, _ = policy.halt_for(halts, "ctrip", "domestic", "PC")
    assert k == "ctrip"               # 维度没命中 → 渠道
    k, _ = policy.halt_for(halts, "qunar", "domestic", "PC")
    assert k == ""                    # 完全没停手


def test_expired_halt_is_not_a_halt():
    halts = {"ctrip": {"until": time.time() - 1}}
    assert policy.halt_for(halts, "ctrip") == ("", {})


# ---------------- 写盘与撤销 ----------------

def test_set_and_clear_halt_by_scope(prof):
    rec = policy.set_halt(prof, "ctrip", 15, note="手停 H5", scope="detail/H5/API")
    assert rec is not False, "写盘失败被当成成功"
    assert "ctrip/detail/H5/API" in rec
    # 记录形状仍是 `{until, note}`（既有契约），作用域由**键**表达
    assert set(rec["ctrip/detail/H5/API"]) == {"until", "note"}
    # 渠道级不受影响
    assert policy.halt_for(policy.read_halt(prof), "ctrip", "detail", "PC") == ("", {})
    assert policy.clear_halt(prof, "ctrip", scope="detail/H5/API") is True
    assert "ctrip/detail/H5/API" not in policy.read_halt(prof)


def test_channel_level_halt_still_writes_plain_key(prof):
    rec = policy.set_halt(prof, "ctrip", 15)
    assert "ctrip" in rec and all("/" not in k for k in rec), rec


# ---------------- 决策面：只停那一条 ----------------

def _pac(prof):
    pac = Pacing({})
    halts = policy.read_halt(prof)
    pac.set_halt_reader(lambda p, d, pa: policy.halt_for(halts, p, d, pa))
    return pac


def test_path_halt_blocks_only_that_link(prof):
    policy.set_halt(prof, "ctrip", 15, scope="detail/H5/API")
    pac = _pac(prof)
    allow, wait, why = pac.gate_path("ctrip", "detail", "H5/API")
    assert allow is False and PATH_HALTED in why, why
    allow2, _w2, _y2 = pac.gate_path("ctrip", "detail", "PC")
    assert allow2 is True, "同维度另一条链路被连坐"


def test_dimension_halt_blocks_all_links_of_that_dimension(prof):
    policy.set_halt(prof, "ctrip", 15, scope="intl")
    pac = _pac(prof)
    assert pac.gate_path("ctrip", "intl", "H5")[0] is False
    assert pac.gate_path("ctrip", "intl", "PC")[0] is False
    assert pac.gate_path("ctrip", "domestic", "PC")[0] is True


def test_no_reader_means_no_halt(prof):
    """没注入读点的实例照常放行（单测/离线路径不能被停手逻辑拖死）。"""
    policy.set_halt(prof, "ctrip", 15)
    pac = Pacing({})
    assert pac.gate_path("ctrip", "detail", "PC")[0] is True


def test_expired_halt_unblocks(prof):
    policy.set_halt(prof, "ctrip", 1, scope="detail/PC")
    path = policy.halt_path(prof)
    import json
    d = json.load(open(path, encoding="utf-8"))
    d["ctrip/detail/PC"]["until"] = time.time() - 5
    json.dump(d, open(path, "w", encoding="utf-8"))
    policy._HALT_CACHE.pop(path, None)
    pac = _pac(prof)
    assert pac.gate_path("ctrip", "detail", "PC")[0] is True


# ---------------- 接口面：/api/strategy/halt|resume 认 scope ----------------

def test_halt_api_accepts_scope_and_rejects_unknown_dimension(tmp_path,
                                                             monkeypatch):
    import webui

    base = str(tmp_path / "profile")
    os.makedirs(base, exist_ok=True)

    class _Eng:
        base_dir = base

    monkeypatch.setattr(webui, "_policy_engine", lambda plat="": _Eng(),
                        raising=False)
    monkeypatch.setattr(webui, "_strategy_ledger",
                        lambda *a, **k: True, raising=False)
    monkeypatch.setattr(webui, "_ledger_tail",
                        lambda out, ok, act: out, raising=False)

    code, out = webui._strategy_halt_api(
        {"plat": "ctrip", "minutes": 15, "scope": "detail/H5/API"})
    assert code == 200 and out.get("ok") is True, out
    assert out.get("scope") == "detail/H5/API"
    assert out.get("key") == "ctrip/detail/H5/API"
    assert out.get("until", 0) > time.time()
    halts = policy.read_halt(base)
    assert "ctrip/detail/H5/API" in halts

    # 拼错的维度：必须 400，不许写一条查不到的停手
    code2, out2 = webui._strategy_halt_api(
        {"plat": "ctrip", "minutes": 15, "scope": "detailx/H5"})
    assert code2 == 400 and "未知维度" in out2.get("err", ""), out2
    assert list(policy.read_halt(base)) == ["ctrip/detail/H5/API"]

    # 恢复同一个作用域
    code3, out3 = webui._strategy_resume_api(
        {"plat": "ctrip", "scope": "detail/H5/API"})
    assert code3 == 200 and out3.get("cleared") is True, out3
    assert "ctrip/detail/H5/API" not in policy.read_halt(base)


def test_halt_api_channel_level_unchanged(tmp_path, monkeypatch):
    """渠道级仍写裸渠道键（历史文件与既有门禁的形状不许变）。"""
    import webui

    base = str(tmp_path / "p2")
    os.makedirs(base, exist_ok=True)

    class _Eng:
        base_dir = base

    monkeypatch.setattr(webui, "_policy_engine", lambda plat="": _Eng(),
                        raising=False)
    monkeypatch.setattr(webui, "_strategy_ledger",
                        lambda *a, **k: True, raising=False)
    monkeypatch.setattr(webui, "_ledger_tail",
                        lambda out, ok, act: out, raising=False)
    code, out = webui._strategy_halt_api({"plat": "ctrip", "minutes": 15})
    assert code == 200 and out.get("key") == "ctrip", out
    assert "ctrip" in policy.read_halt(base)


def test_profile_of_is_single_source():
    """`webui._profile_of` 必须与 `core.policy.profile_of` 同源（不各写一份）。"""
    import io
    import webui

    src = webui_full_src()
    seg = src[src.index("def _profile_of(plat):"):]
    seg = seg[:1200]
    assert "profile_of" in seg and "core.policy" in seg, seg[:200]
    assert webui._profile_of("fliggy") == policy.profile_of("fliggy")


def test_panel_can_stop_a_single_link():
    """面板必须能只停一条链路（否则「链路级停手」只有接口、没有可视化）。"""
    import io

    src = webui_full_src()
    # 作用域下拉存在，且选项由快照现填（不写死维度名）
    assert "function stratScopeFill(" in src
    assert "select.ssel2" in src or "ssel ssel2" in src
    assert "渠道整家" in src
    # 停手请求带 scope
    assert "scope:scope" in src, "stratHalt 没把作用域发给接口"
    # 作用域级停手在停手表里可见（否则用户看不见自己停过哪条）
    assert 'out["halt_scopes"]' in src
    assert "STRATPAY.halt_scopes" in src


# ---- merged from tests/test_r1063_radar_path_gate.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    web = webui_full_src()
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


# ---- merged from tests/test_r1063_stall_on_path_note.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _crawler(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from crawlers.app_ctrip import AppCtripCrawler
    c = AppCtripCrawler({"crawler": {"user_data_dir": str(tmp_path)}},
                        logging.getLogger("t"))
    monkeypatch.setattr(c, "user_data_root", str(tmp_path), raising=False)
    return c


def test_three_timeouts_trip_the_breaker(tmp_path, monkeypatch):
    from core import service_state as ss
    c = _crawler(tmp_path, monkeypatch)
    for _ in range(c.APP_STALL_STREAK):
        c.path_note("app-date", "timeout",
                    detail="点日历后未回到表单/日期未变")
    left = ss.until(str(tmp_path), c.name, "app_stall") - time.time()
    assert left > 600, "连续超时没有写出熔断（%r）" % left
    assert "连续" in ss.detail(str(tmp_path), c.name, "app_stall")


def test_success_resets_streak(tmp_path, monkeypatch):
    c = _crawler(tmp_path, monkeypatch)
    c.path_note("app-date", "timeout", detail="x")
    c.path_note("app-date", "timeout", detail="x")
    assert getattr(c, "_timeout_streak", 0) == 2
    c.path_note("航班明细", "ok", rows=1)
    assert getattr(c, "_timeout_streak", 0) == 0


def test_below_threshold_does_not_trip(tmp_path, monkeypatch):
    from core import service_state as ss
    c = _crawler(tmp_path, monkeypatch)
    for _ in range(c.APP_STALL_STREAK - 1):
        c.path_note("app-date", "timeout", detail="x")
    assert ss.until(str(tmp_path), c.name, "app_stall") == 0, \
        "没到阈值不该熔断（把偶发当熔断会让渠道白停）"
