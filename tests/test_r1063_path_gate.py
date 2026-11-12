# -*- coding: utf-8 -*-
"""r1063 T7：链路闸门 + 按 (渠道, 链路) 记账的令牌桶/熔断键。

三条断言各钉一件事（任何一条变红都意味着「停一条路」会变成「停一家渠道」）：

1. **禁用只对点名的通路生效**：策略里把 `tongcheng/intl/PC` 停用之后，
   同渠道同维度的 `H5` 必须照旧放行——否则用户关掉一条劣化通路，
   等于整家渠道停采（这正是本任务要挡的连坐）。
2. **令牌桶按 (渠道, 链路) 记账**：`ctrip|PC` 刚发过一次，不许把
   `ctrip|H5` 也一起等——两条通路的预算互相独立。
3. **快照仍按渠道聚合**：`snapshot()["channels"][plat]` 是既有界面与既有
   门禁的唯一读法，键里多出 `plat|path` 会当场把面板与门禁一起弄红。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _clean_params():
    """`strategy_params` 是模块级单例：用例装的覆盖必须还原，否则会漏给同
    进程里后面的用例（那类「上一个用例的配置还在」的假绿最难查）。"""
    yield
    from core import strategy_params as sp
    sp.invalidate()


def test_path_gate_denies_only_the_named_path():
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng/intl/PC": {"path_fallback.enabled": False}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    ok, wait, why = pac.gate_path("tongcheng", "intl", "PC")
    assert ok is False and "策略" in why
    ok2, _, _ = pac.gate_path("tongcheng", "intl", "H5")
    assert ok2 is True, "禁用 PC 不许连坐 H5"


def test_per_path_token_bucket_does_not_block_the_other_path():
    from core.pacing import TokenBucket
    tb = TokenBucket(min_gap_s=5, per_minute=0)
    tb.record("ctrip", path="PC")
    assert tb.wait_hint("ctrip", path="PC") > 0
    assert tb.wait_hint("ctrip", path="H5") == 0


def test_snapshot_still_aggregates_per_channel():
    """兼容：快照按渠道聚合，前端与既有门禁不受链路键影响。"""
    from core.pacing import Pacing
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    pac.record("ctrip", path="PC")
    assert "ctrip" in pac.snapshot()["channels"]


# ---------------------------------------------------------------- 复核补充
#
# 下面这批钉的是「T8 一接线就会出事」的四类：链路级的账**清不掉**（面板点了
# 「解除」立刻回红 / 一次链路软拒把整家钉在强制预热上）、渠道路径预算被
# 放大成 N 倍、聚合口径没人钉、以及 `trip` 的两个字符串位置参互相顶掉。

_CH_FIELDS = {"state", "remain_s", "strikes", "reason", "needs_login",
              "needs_warmup", "ok_streak"}


def _breaker(base_s=300):
    from core.pacing import ChannelBreaker
    return ChannelBreaker(base_s=base_s, cap_s=3600)


def test_reset_without_path_clears_every_layer_of_the_channel():
    """面板上只有渠道级「解除」：点了必须真的解除链路级冷却。

    旧行为（只清 `plat` 键）下这里的最后一条断言会红：台账写「已解除」，
    行随即又变回 cooldown，而界面上没有任何带 path 的入口。
    """
    b = _breaker()
    b.trip("ctrip", "ip", now=1000.0, path="PC")
    assert b.allow("ctrip", now=1000.0, path="PC")[0] is False
    b.reset("ctrip")
    assert b.allow("ctrip", now=1000.0, path="PC")[0] is True
    assert b.snapshot(now=1000.0)["ctrip"]["state"] == "ok"


def test_note_warmup_ok_without_path_clears_the_path_flag():
    """一次链路级软拒不许把整家渠道钉在「每轮强制预热」上（r626 同类）。"""
    b = _breaker()
    b.trip("ctrip", "soft", path="PC")
    assert b.snapshot()["ctrip"]["needs_warmup"] is True
    b.note_warmup_ok("ctrip")
    assert b.snapshot()["ctrip"]["needs_warmup"] is False


def test_note_ok_without_path_clears_the_path_cooldown():
    """成功出数是「会话已养熟」的最强证据：链路级的冷却也要清。"""
    b = _breaker()
    b.trip("ctrip", "ip", now=1000.0, path="PC")
    b.note_ok("ctrip", need=1)
    assert b.allow("ctrip", now=1000.0, path="PC")[0] is True
    assert b.snapshot(now=1000.0)["ctrip"]["strikes"] == 0


def test_path_scoped_reset_does_not_touch_the_channel_layer():
    """`path=` 时只清那一层：点名了一条链路，不许顺手免掉整家渠道的冷却。"""
    b = _breaker()
    b.trip("ctrip", "ip", now=1000.0)              # 渠道级冷却
    b.trip("ctrip", "ip", now=1000.0, path="PC")   # 链路级冷却
    b.reset("ctrip", path="PC")
    assert b.allow("ctrip", now=1000.0, path="PC")[0] is False, "渠道级还在"
    assert b.allow("ctrip", now=1000.0, path="H5")[0] is False, "渠道级拦所有链路"
    assert b.snapshot(now=1000.0)["ctrip"]["remain_s"] == 300
    b.reset("ctrip")                               # 渠道级「解除」才全清
    assert b.allow("ctrip", now=1000.0, path="PC")[0] is True


def test_channel_cooldown_blocks_every_path_of_the_channel():
    """`_keys` 的两级语义：渠道级冷却对该渠道每条链路都成立。"""
    b = _breaker()
    b.trip("ctrip", "login", now=1000.0)
    for p in ("PC", "H5", "日历", "H5/API"):
        assert b.allow("ctrip", now=1000.0, path=p)[0] is False, p


def test_path_cooldown_does_not_block_or_inflate_the_channel():
    """反连坐：链路级 trip 只写 `plat|path`，不碰渠道级的账。"""
    b = _breaker()
    b.trip("ctrip", "ip", now=1000.0, path="PC")
    assert b.allow("ctrip", now=1000.0, path="H5")[0] is True, "PC 冷却不许连坐 H5"
    assert b.allow("ctrip", now=1000.0)[0] is True, "渠道层没被这条 trip 碰过"
    assert "ctrip" not in b._st, "链路级 trip 写到了渠道级账上"


def test_channel_snapshot_fields_are_unchanged_by_path_rows():
    """聚合口径：多一条 `ctrip|PC` 不许给渠道行添字段、也不许丢字段。"""
    b = _breaker()
    assert set(b.snapshot(now=1000.0)["ctrip"]) == _CH_FIELDS
    b.trip("ctrip", "ip", now=1000.0, path="PC")
    row = b.snapshot(now=1000.0)["ctrip"]
    assert set(row) == _CH_FIELDS
    assert row["state"] == "cooldown" and row["remain_s"] == 300


def test_channel_per_minute_still_caps_the_whole_channel():
    """`per_minute` 是**渠道**上限：一链路一次闸门不许把它放大成 N 倍。

    旧行为（只查/只记链路桶）下，配 2 次/分钟的渠道会变成 PC 2 + H5 2 + …
    """
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 2}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 2}}})
    pac.record("ctrip", path="PC")
    pac.record("ctrip", path="PC")
    ok, wait, why = pac.gate_path("ctrip", "intl", "H5")
    assert ok is True and wait > 0, "渠道级 per_minute 必须兜住每一条链路"


def test_bucket_snapshot_does_not_double_count_path_records():
    """渠道桶已是总量，聚合时不许再把各链路桶加一遍（会翻倍）。"""
    from core.pacing import TokenBucket
    tb = TokenBucket(min_gap_s=0, per_minute=0)
    tb.record("ctrip", path="PC")
    tb.record("ctrip", path="H5")
    assert tb.snapshot()["ctrip"]["per_min_used"] == 2


def test_path_rate_override_tightens_only_that_path():
    """链路级限速是**叠加**在渠道上限之上的收紧，不是替代。"""
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {
        "rate": {"min_gap_s": 0, "per_minute": 2},
        "strategy_overrides": {"ctrip/intl/H5": {"rate_per_minute.value": 1}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 2}}})
    pac.record("ctrip", path="H5")
    ok_h5, wait_h5, _ = pac.gate_path("ctrip", "intl", "H5")
    ok_pc, wait_pc, _ = pac.gate_path("ctrip", "intl", "PC")
    assert ok_h5 is True and ok_pc is True
    assert wait_h5 > 0, "该链路自己配了 1 次/分钟"
    assert wait_pc == 0, "别的链路一键都没收紧"


# ---------------------------------------------------------------- 落地归因接链路
#
# 下面这批钉的是复核 2026-11-06 第 3 条：`observe()` 从来没有 `path`，`trip()`
# 的唯一调用方也不给——于是 `渠道|链路` 熔断键**一次都没被创建过**，
# `gate_path()` 的熔断腿只看得到渠道键。链路级记账全在，只是没人写。

def test_observe_creates_a_path_scoped_breaker_key():
    """`observe(path=…)` 必须真的建出 `渠道|链路` 键，且不连坐同渠道别的链路。"""
    from core.pacing import Pacing
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    kind, cd = pac.observe("ctrip", ["blocked"], "滑块", path="PC")
    assert kind == "captcha" and cd > 0, (kind, cd)
    assert "ctrip|PC" in pac._breaker._st, "没建链路级熔断键：observe 的 path 没落地"
    assert "ctrip" not in pac._breaker._st, \
        "链路级证据被记到了渠道级账上（会连坐整家）"
    assert pac.allow("ctrip", path="PC")[0] is False
    assert pac.allow("ctrip", path="H5")[0] is True, "PC 的冷却连坐了 H5"


def test_observe_without_path_keeps_the_channel_wide_behaviour():
    """负控：不带 path（证据跨多条链路）时仍是渠道级结论——老行为逐位不变。"""
    from core.pacing import Pacing
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    kind, cd = pac.observe("ctrip", ["blocked"], "滑块")
    assert kind == "captcha" and cd > 0
    assert "ctrip" in pac._breaker._st, "不带 path 时必须落渠道级键"
    assert pac.allow("ctrip", path="H5")[0] is False


def test_success_on_one_path_keeps_the_other_path_cooldown():
    """**A 路的成功不许顺手免掉 B 路的实时冷却**（复核 2026-11-06 第 3 条）。

    语义写死在这里：`path=""` 才表示「这一渠道的全部层级」；点名了链路就只清
    渠道层 + 那一条。`note_ok()` 清渠道层是对的——一次出数就证明整家还活着，
    而读取侧本来就把渠道级冷却算到每条链路上，整家冷却期间发不出成功请求。
    """
    b = _breaker()
    b.trip("ctrip", "ip", now=1000.0, path="PC")
    b.trip("ctrip", "ip", now=1000.0, path="H5")
    assert b.note_ok("ctrip", need=1, path="PC") >= 1
    assert b.allow("ctrip", now=1000.0, path="PC")[0] is True, "自己那层没清"
    assert b.allow("ctrip", now=1000.0, path="H5")[0] is False, \
        "B 路的冷却被 A 路的一次成功免掉了"
    # 渠道级「全清」仍是老语义（面板上那个不带 path 的入口）
    b.note_ok("ctrip", need=1)
    assert b.allow("ctrip", now=1000.0, path="H5")[0] is True


def test_path_success_clears_the_channel_soft_flag():
    """成功=「整家还活着」：渠道层的软拒标记必须清，否则 r626 的粘滞标记回归。"""
    b = _breaker()
    b.trip("ctrip", "soft", path="PC")
    b.mark_cause("ctrip", "soft")            # path="" → 全层（含渠道层）
    assert b.snapshot()["ctrip"]["needs_warmup"] is True
    b.note_ok("ctrip", need=1, path="PC")
    assert b.snapshot()["ctrip"]["needs_warmup"] is False


def test_trip_path_is_keyword_only():
    """`note` 与 `path` 都是字符串：第 6 个位置参数不许被当成 path。

    `trip("ctrip","ip",None,0,"PC")` 这种 5 位置调用里 "PC" 仍然绑 `note`
    （旧签名就这样），但**绝不会**悄悄变成链路键——那会把一条渠道级熔断
    记成一条链路级熔断，反向连坐。
    """
    b = _breaker()
    with pytest.raises(TypeError):
        b.trip("ctrip", "ip", None, 0, "", "PC")      # path 只能写关键字
    b.trip("ctrip", "ip", 1000.0, 0, "PC")            # 第 5 个位置仍是 note
    assert "ctrip|PC" not in b._st, "位置参数被当成了链路"
    assert b._st["ctrip"]["reason"] == "ip"
    from core.pacing import Pacing
    pac = Pacing({})
    with pytest.raises(TypeError):
        pac.trip("ctrip", "ip", None, 0, "", "PC")


def test_unreadable_path_switch_warns_instead_of_silently_enabling():
    """`"flase"` 这种拼错的值：fail-open 可以，但必须留痕。"""
    import warnings
    import core.pacing as P
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/intl/PC": {"path_fallback.enabled": "flase"}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    P._WARNED.clear()
    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always")
        ok, _, _ = pac.gate_path("ctrip", "intl", "PC")
    assert ok is True, "读不懂的值按启用处理（fail-open）"
    assert any("读不懂" in str(w.message) for w in got), \
        "拼错的值不许静默生效：连一行告警都没有，用户会以为已经停了"


# ---------------------------------------------------------------- 波次 2：维度级
#
# 波次 1 把四个老开关（`breaker_switch` / `warmup` / `health_penalty` /
# `policy_gate`）接到了 `strategy_params`，于是**渠道级**覆盖生效了。但
# `_strat_on()` 只有在拿到 `dim` 时才会走到维度/链路层，而它的调用方过去最多
# 给 `plat`（+`path`）—— 于是 `crawler.strategy_overrides` 里
# `渠道/维度` 与 `渠道/维度/链路` 两层的开关**配了不生效**：界面按
# `source=dimension` 渲染成「已按维度停用」，熔断照旧。
#
# 下面这批钉的就是那两层真能落到消费方（`allow` / `gate_path` / `observe`），
# 且**只**影响被点名的那一层。


def test_dimension_override_turns_the_breaker_off_for_that_dimension_only():
    """`飞猪/intl: breaker_switch.enabled=false` → intl 不熔断，domestic 照旧。"""
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy/intl": {"breaker_switch.enabled": False}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    pac.trip("fliggy", "ip")               # 渠道级冷却（真实时钟）
    assert pac.allow("fliggy", dim="intl")[0] is True, \
        "维度级覆盖没到熔断：配了 breaker_switch=false 仍然拦"
    assert pac.allow("fliggy", dim="domestic")[0] is False, \
        "停一个维度的熔断连坐了另一个维度"
    ok, _w, _why = pac.gate_path("fliggy", "intl", "")
    assert ok is True, "闸门的熔断腿也没吃到维度级覆盖"
    ok2, _w2, why2 = pac.gate_path("fliggy", "domestic", "")
    assert ok2 is False and "冷却" in why2, why2
    # 落地归因那条路（main.py 调的就是它）：开关关掉时不返回 kind，
    # 否则界面仍宣称「已熔断」、账本仍写一条自动干预。
    assert pac.observe("fliggy", ["blocked"], "滑块", dim="intl") == ("", 0)
    kind, cd = pac.observe("fliggy", ["blocked"], "滑块", dim="domestic")
    assert kind == "captcha" and cd > 0, (kind, cd)


def test_dimension_override_on_warmup_and_health_penalty():
    """另外两个老开关同样按维度可调（`warmup` / `health_penalty`）。"""
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/intl": {"warmup.enabled": False,
                       "health_penalty.enabled": False}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    assert pac.warmup_on("ctrip", "intl") is False
    assert pac.warmup_on("ctrip", "domestic") is True
    assert pac.health_penalty_on("ctrip", "intl") is False
    assert pac.health_penalty_on("ctrip", "domestic") is True
    # 软拒落在 intl：预热被关掉 → 不置 needs_warmup，只留归因
    kind, cd = pac.observe("ctrip", ["soft_reject"], "软拒", dim="intl")
    assert (kind, cd) == ("soft", 0), (kind, cd)
    assert pac.snapshot()["channels"]["ctrip"]["needs_warmup"] is False


def test_path_override_turns_the_rate_switch_off_for_that_path_only():
    """`同程/intl/H5: rate_min_gap.enabled=false` → H5 不限速，PC 照旧。"""
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {
        "rate": {"min_gap_s": 30, "per_minute": 0},
        "strategy_overrides": {
            "tongcheng/intl/H5": {"rate_min_gap.enabled": False}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 30, "per_minute": 0}}})
    pac.record("tongcheng", path="H5", channel=False)
    pac.record("tongcheng", path="PC", channel=False)
    ok_h5, wait_h5, _ = pac.gate_path("tongcheng", "intl", "H5")
    ok_pc, wait_pc, _why_pc = pac.gate_path("tongcheng", "intl", "PC")
    assert ok_h5 is True and wait_h5 == 0, \
        "链路级 rate_min_gap=false 没生效：这条通路仍在等最小间隔"
    assert ok_pc is True and wait_pc > 0, \
        "关掉 H5 的最小间隔，顺手把 PC 的限速也废了（作用域串了）"


def test_switch_lookup_is_a_public_scoped_function():
    """读法必须是参数层的公开函数：`switch_on(pid, *, plat, dim, path)`。

    `from core.pacing import _strat_on` 这种私有名 import 是把「私有」当装饰，
    而且作用域只能靠位置参数猜。这里钉两件事：公开名在参数层、作用域是
    keyword-only（位置调用会当场 TypeError，不会把「intl」绑成 plat）。
    """
    import core.pacing as P
    from core.strategy_params import switch_on
    from core import strategy_params as sp
    assert not hasattr(P, "_strat_on"), "旧私有名还在：跨模块 import 会继续用它"
    sp.invalidate()
    assert switch_on("breaker_switch.enabled") is True
    assert switch_on("breaker_switch.enabled", plat="fliggy") is True
    with pytest.raises(TypeError):
        switch_on("breaker_switch.enabled", "fliggy")


def test_unreadable_switch_value_warns_once_and_stays_open():
    """作用域化读法的边界没变：读不懂 → fail-open + 留痕（同一个值只喊一次）。"""
    import warnings
    from core.strategy_params import switch_on
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/intl": {"breaker_switch.enabled": "flase"}}}})
    sp._SWITCH_WARNED.clear()
    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always")
        assert switch_on("breaker_switch.enabled", plat="ctrip",
                         dim="intl") is True
        assert switch_on("breaker_switch.enabled", plat="ctrip",
                         dim="intl") is True
    hits = [w for w in got if "读不懂" in str(w.message)]
    assert len(hits) == 1, "坏值告警没有去重：链路闸门会刷爆日志"
    assert "ctrip/intl" in str(hits[0].message), \
        "告警没说清是哪个作用域配错了：%s" % (hits[0].message,)

