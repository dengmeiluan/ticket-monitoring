# -*- coding: utf-8 -*-
"""r1063 T8：浏览器五家接入链路闸门。

四条断言各钉一件事（任何一条变红，都意味着「停一条路」会变成「停一家渠道」，
或者采集器自己把渠道预算记了两遍）：

1. **五家真的问了闸门**：源码锚点，逐家断言「用这条通路之前先问
   `path_gate(`」；`base.py` 里被停用的通路必须记 `paced`，不许记失败
   （记失败会把整家渠道的熔断拉开）。
2. **被停用的只是那一条路**：同一实例的另一条通路照常放行——否则用户
   关掉一条劣化通路，等于整家渠道停采。
3. **等待必须封顶**（铁律 I6）：`gate_path` 说「还要等 300s」时，
   闸门最多只睡 15s，不许把采集线程钉死在一次等待上。
4. **只记链路桶**（`channel=False`）：渠道级的账 `main.py` 已经为每条
   查询记过一次；采集器再记一次会让 `per_minute` 减半、`min_gap` 翻倍。
5. **旧签名不退回双记**（复核 2026-11-06）：`record` 不吃 `channel=` 时
   宁可**不记**，也不退回带渠道口径的写法。
6. **`paced` 证据带日期**：多日查询要能看出是哪一天被跳的。
7. **私有 `Pacing` 读到对的配置层**：采集器拿到的是 `crawler:` 段，
   递错层＝`min_gap_s 0` 且看不出来。
8. **停用一条路不许吞掉另一条路的行**：行为级用例，`tuniu.fetch` 在
   `H5/API` 被停用时仍要交出 `PC` 已经产出的行（复核 Critical）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
        tests/test_r1063_browser_path_gate.py -q
"""
import io
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.base import BaseCrawler  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 浏览器五家：闸门必须接在每一家的分支入口上
_FIVE = ("fliggy.py", "qunar.py", "ctrip.py", "tongcheng.py", "tuniu.py")


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


# ---------------------------------------------------------------- 源码锚点

def test_each_browser_crawler_consults_the_path_gate_before_using_a_path():
    for fn in _FIVE:
        body = _src(fn)
        assert "path_gate(" in body, "%s 没有问链路闸门" % fn
    base = _src("base.py")
    assert 'path_note(path, "paced"' in base, "被停用的通路没记 paced（会误伤整渠道）"


def test_base_crawler_exposes_the_gate_helper():
    base = _src("base.py")
    assert "def path_gate(self, path" in base, "基类没有 path_gate 包装"
    # 等待必须封顶：源码里要能看见上限被作用到 sleep 上，而不是把 wait_s
    # 直接塞进去（铁律 I6：每处 sleep 都要有累计上限）
    # r1063 T30 起：睡眠值先算进变量（顺手记「在等」），封顶仍在。
    # 判据跟着实现走，但守的东西没变：**每处 sleep 都必须有上限**（铁律 I6）。
    assert "_slp = min(wait, PATH_GATE_SLEEP_CAP_S)" in base, \
        "闸门的等待没有上限（铁律 I6：每处 sleep 都要有上限）"
    assert "time.sleep(_slp)" in base


# ---------------------------------------------------------------- 行为验证

class _FakeCrawler(BaseCrawler):
    """只借用基类的闸门与账本，不建浏览器/资料目录。"""
    name = "tongcheng"


def _fake(pac=None):
    c = object.__new__(_FakeCrawler)
    c.config = {}
    c.logger = logging.getLogger("t_browser_path_gate")
    if pac is not None:
        c._pacing = pac
    c.path_reset()
    return c


def _pacing(min_gap_s=0, per_minute=0):
    from core.pacing import Pacing
    return Pacing({"crawler": {"rate": {"min_gap_s": min_gap_s,
                                        "per_minute": per_minute}}})


def _disable_scope(key):
    """把某个 `渠道/维度/链路` 上的 path_fallback 关掉（T7 的读点）。"""
    from core import strategy_params as sp
    sp.set_config({"crawler": {
        "rate": {"min_gap_s": 0, "per_minute": 0},
        "strategy_overrides": {key: {"path_fallback.enabled": False}}}})


def test_disabled_path_is_skipped_with_paced_evidence():
    """(a) 被策略停用的通路：返回 False，账本是 `paced`，不是失败。"""
    from core.pacing import PATH_DISABLED
    _disable_scope("tongcheng/intl/PC")
    c = _fake(_pacing())
    assert c.path_gate("PC", "intl") is False
    assert c.paths, "被停用的通路必须留证，否则面板看不出为什么没数据"
    last = c.paths[-1]
    assert last["path"] == "PC"
    assert last["status"] == "paced", \
        "记成 %s 会被当成渠道失败而触发熔断（连坐）" % last["status"]
    assert PATH_DISABLED in last["detail"], "证据里没说清是「链路被策略停用」"


def test_the_other_path_of_the_same_crawler_still_passes():
    """(b) 停用只对点名的通路生效，同一实例的另一条通路照常放行。"""
    _disable_scope("tongcheng/intl/PC")
    c = _fake(_pacing())
    assert c.path_gate("PC", "intl") is False
    assert c.path_gate("H5", "intl") is True, "禁用 PC 不许连坐 H5"
    assert c.path_gate("日历", "intl") is True, "禁用 PC 不许连坐日历"


def test_wait_is_capped_at_fifteen_seconds(monkeypatch):
    """(c) `wait_s` 上限 15s：铁律 I6，每处 sleep 都要有累计上限。"""
    import crawlers.base as B
    from core import strategy_params as sp
    sp.set_config({"crawler": {"rate": {"min_gap_s": 300, "per_minute": 0}}})
    c = _fake(_pacing(min_gap_s=300))
    slept = []
    monkeypatch.setattr(B.time, "sleep", lambda s: slept.append(s))
    assert c.path_gate("PC", "intl") is True          # 桶里还没有记录 → 不等
    assert c.path_gate("PC", "intl") is True          # 该等 300s，但必须封顶
    assert slept, "闸门必须真的等一次，否则限速形同虚设"
    # 断言「真的被截到 15」，不是「没超过 15」（复核 2026-11-06）：
    # `<= 15` 对 `sleep(0.01)` 也成立，那样闸门只要睡一下就算过。
    # 该等 300s、上限 15s → 必须**恰好**睡 15s。
    assert max(slept) == pytest.approx(15.0), \
        "等待没有被截到上限 15s（实际 %r 秒）" % (max(slept),)


def test_crawler_records_the_path_bucket_only():
    """(d) 采集器只记链路桶：渠道桶的账归 `main.py`，重复记会翻倍。"""
    pac = _pacing()
    pac.record("tongcheng")               # main.py 已经为这条查询记过渠道级
    c = _fake(pac)
    assert c.path_gate("PC", "intl") is True
    win = pac._bucket._win
    assert len(list(win.get("tongcheng") or ())) == 1, \
        "渠道桶被记了两次：per_minute 会减半、min_gap 会翻倍"
    assert len(list(win.get("tongcheng|PC") or ())) == 1, "链路桶没记上"


def test_record_channel_false_writes_only_the_path_bucket():
    """`Pacing.record(..., channel=False)` 是 T8 的裁决，不是可选优化。"""
    from core.pacing import TokenBucket
    tb = TokenBucket(min_gap_s=0, per_minute=0)
    tb.record("ctrip", path="PC", channel=False)
    assert "ctrip" not in tb._win, "channel=False 还写了渠道桶"
    assert "ctrip|PC" in tb._win
    assert tb.snapshot()["ctrip"]["per_min_used"] == 1


def test_record_default_still_writes_the_channel_bucket():
    """默认 `channel=True` 保持今天的行为：既有调用方一行都不用改。"""
    from core.pacing import TokenBucket
    tb = TokenBucket(min_gap_s=0, per_minute=0)
    tb.record("ctrip", path="PC")
    assert "ctrip" in tb._win and "ctrip|PC" in tb._win
    assert tb.snapshot()["ctrip"]["per_min_used"] == 1, "渠道桶已是总量，不许再加一遍"


# ------------------------------------------------ 复核 2026-11-06 追加的钉子

class _OldSignaturePacing:
    """只实现旧签名 `record(plat, *, path="")` 的节流上下文（不吃 `channel=`）。

    存在的理由：闸门如果为了「兼容旧签名」退回 `record(plat, path=path)`，
    那条调用走的是 `channel=True` ——正好把本任务要防的「同一请求记两遍」
    重新打开（`per_minute` 减半、`min_gap` 翻倍）。
    """

    def __init__(self):
        self.calls = []

    def gate_path(self, plat, dim="", path=""):
        return True, 0.0, ""

    def record(self, plat, now=None, *, path=""):
        self.calls.append((plat, path))
        return None


def test_old_record_signature_records_nothing_instead_of_double_counting():
    """(e) 旧签名下**不记账**：退回带渠道口径的记账＝重开双记陷阱。"""
    pac = _OldSignaturePacing()
    c = _fake(pac)
    assert c.path_gate("PC", "intl") is True, "闸门不能因为记账签名变红就停采"
    assert pac.calls == [], (
        "旧签名下退回 `record(plat, path=path)`：渠道桶与链路桶各记一次，"
        "per_minute 当场减半、min_gap 当场翻倍——宁可这条链路少记一次账")


def test_paced_evidence_carries_the_date_when_the_caller_knows_it():
    """(f) 知道日期的调用点要能看出「是哪天被跳」的（qunar 账本同款）。"""
    _disable_scope("tongcheng/domestic/H5/API")
    c = _fake(_pacing())
    assert c.path_gate("H5/API", "domestic", date="2026-11-20") is False
    assert c.paths[-1]["status"] == "paced"
    assert c.paths[-1]["date"] == "2026-11-20", (
        "paced 证据没带日期：多日查询看不出是哪一天被跳")


def test_private_pacing_is_built_from_the_crawler_rate_layer():
    """(g) 采集器拿到的 config 是 `crawler:` 段，递错了层＝配了不生效。

    `parse_pacing` 读 `cfg["crawler"]["rate"] / ["breaker"]`
    （`core/pacing.py:182-185`），而 `main.py:1910` 递给采集器的是
    `dict(_full["crawler"])`。直接 `Pacing(self.config)` 会让这份私有实例
    永远跑在 `DEFAULTS` 上（`min_gap_s 0` / `per_minute 0`）。
    """
    c = _fake()
    c.config = {"rate": {"min_gap_s": 7.5, "per_minute": 11}}
    pac = c._pacing_ctx()
    assert pac.cfg["min_gap_s"] == 7.5, "私有 Pacing 没读到 crawler.rate"
    assert pac.cfg["per_minute"] == 11, "私有 Pacing 没读到 crawler.rate"


def test_private_pacing_also_accepts_a_whole_config_document():
    """整份 cfg（含 `crawler:` 段）传进来时不许再套一层（否则还是 DEFAULTS）。"""
    c = _fake()
    c.config = {"crawler": {"rate": {"min_gap_s": 4.5, "per_minute": 6}},
                "schedule": {"interval_minutes": 25}}
    pac = c._pacing_ctx()
    assert pac.cfg["min_gap_s"] == 4.5
    assert pac.cfg["per_minute"] == 6


# ------------------------------------------------- 复核 Critical：行为级用例

def _tuniu():
    """真 `TuniuCrawler` + 真 `path_gate`（只把网络与睡眠换掉）。"""
    from unittest import mock

    from crawlers.tuniu import TuniuCrawler
    c = TuniuCrawler({}, mock.MagicMock())
    c.config = {}
    c._sleep = lambda *a, **k: None
    c._pacing = _pacing()           # 注入节流上下文：真的走 path_gate
    return c


_PC_ROW = {"price": 410.0, "code": "MU5186", "name": "东航",
           "depTime": "07:30", "arrTime": "09:45"}


def test_disabled_h5_api_still_returns_the_rows_pc_already_produced():
    """(h) 停用 `H5/API` 不许把**已经拿到**的 PC 行一起扔掉。

    复核 2026-11-06 Critical：闸门原先加在 `for date in (...)` 的循环头上，
    而那个循环同时是 `pc_map` 被发布进 `results` 的唯一位置——`_h5_ok=False`
    时循环一次都不跑，账本记着 `PC/ok`、`fetch()` 却返回 `[]`。
    「账本说 PC 出数了、结果什么都没返回」是最难查的一类。
    """
    from unittest import mock
    d_pc, d_h5 = "2026-11-20", "2026-11-21"
    c = _tuniu()
    c._fetch_pc_dom = lambda *a, **k: {d_pc: [dict(_PC_ROW)]}
    c._saved_page_token = lambda *a, **k: "tok"
    c._hoop = mock.MagicMock(return_value=None)
    _disable_scope("tuniu/domestic/H5/API")

    rows = c.fetch("上海", "北京", [d_pc, d_h5])

    assert [r.depart_date for r in rows] == [d_pc], (
        "被停用的 H5/API 把 PC 已出的行一起吞了：%r"
        % [(r.depart_date, r.price) for r in rows])
    assert rows[0].price == 410.0
    assert c._hoop.call_count == 0, "闸门停的是 H5/API，却仍去打了接口"


def test_enabled_h5_api_still_takes_over_the_dates_pc_missed():
    """负控：闸门放行时行为一字不变（PC 命中日不重复打接口，缺日仍走 H5）。"""
    from unittest import mock
    d_pc, d_h5 = "2026-11-20", "2026-11-21"
    c = _tuniu()
    c._fetch_pc_dom = lambda *a, **k: {d_pc: [dict(_PC_ROW)]}
    c._saved_page_token = lambda *a, **k: "tok"
    c._hoop = mock.MagicMock(return_value=None)

    rows = c.fetch("上海", "北京", [d_pc, d_h5])

    assert [r.depart_date for r in rows] == [d_pc]
    assert c._hoop.call_count == 1, (
        "PC 已出数的日期又被接口打了一遍，或缺日的日期没走 H5：%d 次"
        % c._hoop.call_count)


def _disable_scopes(*keys):
    """一次写多条停用项。

    `_disable_scope` 走 `strategy_params.set_config`，**整体替换**
    `strategy_overrides`——连调两次会把前一条冲掉（本轮踩到：先停 H5 再停
    周历，结果 H5 又开了浏览器）。
    """
    from core import strategy_params as sp
    sp.set_config({"crawler": {
        "rate": {"min_gap_s": 0, "per_minute": 0},
        "strategy_overrides": {k: {"path_fallback.enabled": False}
                               for k in keys}}})


def _reset_overrides():
    """策略覆盖是全局状态，用例之间必须复位。"""
    from core import strategy_params as sp
    sp.set_config({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0},
                               "strategy_overrides": {}}})


def test_disabled_h5_path_does_not_even_open_a_browser():
    """(i) 被闸掉的 H5 不许白占一个 `CHANNEL_GATE` 浏览器名额（ctrip）。

    全局同时只放 `CHANNEL_GATE` 个渠道浏览器；闸门判在 `with self.browser()`
    **之前**，所以被停用的通路连上下文都不进——否则一个被用户关掉的通路
    会让别的渠道干等。

    r1063 T153：`PC·周历` 是**独立通路**，它有**自己的**闸门。所以这条用例
    要同时停掉周历，否则"周历兜底"会合法地开一个浏览器（见下一条用例）。
    """
    from unittest import mock

    from crawlers.ctrip import CtripCrawler
    c = CtripCrawler({}, mock.MagicMock())
    c.config = {}
    c._sleep = lambda *a, **k: None
    c._pacing = _pacing()
    c.browser = mock.MagicMock(
        side_effect=AssertionError("被链路闸门停用的 H5 仍开了浏览器"))
    c._fetch_intl_list = mock.MagicMock(return_value=[])
    _reset_overrides()
    _disable_scopes("ctrip/domestic/H5", "ctrip/domestic/PC·周历")

    rows = c.fetch("上海", "北京", ["2026-11-20"])

    assert rows == []
    assert c.browser.call_count == 0, "被闸掉的通路开了浏览器"
    assert c._fetch_intl_list.called, "H5 被跳过时 PC 列表补采必须照跑"


