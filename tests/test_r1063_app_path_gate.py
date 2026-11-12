# -*- coding: utf-8 -*-
"""r1063 T9：App 五家接入链路闸门。

五条断言各钉一件事（任何一条变红，都意味着「停一个阶段」会变成「停一家
渠道」，或者闸门把等待睡在了设备锁里）：

1. **只闸五个主阶段**：逐家断言 `app-login` / `app-list` / `app-calendar` /
   `往返` / `low-fare` 的入口都问了 `path_gate(`；而同一次交互**内部**的
   细段（`app-city*` / `app-date` / `app-form` / `app-search` / `app-dump` /
   `app-blocker` / `android-*`）一处都不许问——停细段等于停整条链路，
   矩阵对它们记 `na`，理由写在 `app_base.py` 里。
2. **被停用的阶段返回 False 且记 `paced`**，不许记失败：记失败会把整家
   渠道的熔断拉开（正是本闸门要挡的连坐）。
3. **停用只对点名的阶段生效**：同一实例的其它阶段照常放行。
4. **等待封顶 15s，且**绝不在持有设备锁时睡**（App 设备串行独占，闸门
   在锁里睡会让排队等锁的其它 App 渠道全体陪跑）。
5. **只记链路桶**（`channel=False`）：渠道桶的账 `main.py` 已经记过。

另有一条行为级用例（接线的负控）：被停用的列表阶段必须**连设备锁都不拿**、
一条失败都不记；放行时整条链路照旧跑。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
        tests/test_r1063_app_path_gate.py -q
"""
import io
import logging
import os
import sys
import tempfile
from contextlib import contextmanager

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402

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
