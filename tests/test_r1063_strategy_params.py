# -*- coding: utf-8 -*-
"""r1063：参数三级继承、来源标注、粒度独立、钳制回写。"""
import pytest

from core import strategy_params as sp


@pytest.fixture(autouse=True)
def _cfg():
    sp.set_config({"schedule": {"fast_ttl_min": 30},
                   "crawler": {"rate": {"per_minute": 0},
                               "policy": {"pace": {"watch": 2.0}},
                               "strategy_overrides": {
                                   "fliggy": {"rate_per_minute.value": 9},
                                   "tongcheng/intl/PC":
                                       {"rate_per_minute.value": 3}}}})
    yield
    sp.invalidate()


def test_default_when_nothing_configured():
    # 本用例的前提是「什么都没配」，而 autouse 夹具给每个用例都塞了 cfg，
    # 所以先回到默认态（否则它与 test_global_beats_default 会对**同一状态**
    # 断言两个不同的值：15/default vs 30/global）。
    sp.invalidate()
    got = sp.resolve("ttl_tier.fast")
    assert (got.value, got.source) == (15, "default")


def test_global_beats_default():
    got = sp.resolve("ttl_tier.fast")
    assert got.value == 30 and got.source == "global"


def test_channel_override_beats_global():
    assert sp.resolve("rate_per_minute.value", plat="fliggy").value == 9
    assert sp.resolve("rate_per_minute.value", plat="ctrip").source == "global"


def test_path_override_beats_channel_override():
    got = sp.resolve("rate_per_minute.value", plat="tongcheng",
                     dim="intl", path="PC")
    assert (got.value, got.source) == (3, "path")
    # 只给渠道、不给维度时落在渠道（已配的渠道覆盖）
    assert sp.resolve("rate_per_minute.value",
                      plat="tongcheng").source == "global"


def test_override_key_rejects_unknown_segments():
    with pytest.raises(ValueError):
        sp.parse_override_key("nosuchchan/intl/PC")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/nosuchdim/PC")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/nosuchpath")


def test_non_dict_override_block_is_rejected():
    """整块覆盖写成非字典 → 装载即报错（不许「配了不生效」）。

    复核指出的真实缺陷：`strategy_overrides: [...]` 曾能被静默接受，
    装载不报错、求值全走默认值——用户以为配了，实际什么都没发生。
    """
    for bad in ([], ["fliggy"], "fliggy", 5, True):
        with pytest.raises(ValueError):
            sp.set_config({"crawler": {"strategy_overrides": bad}})
    # 空字典是合法的「没有覆盖」，不能被当成错误
    sp.set_config({"crawler": {"strategy_overrides": {}}})
    assert sp.resolve("rate_per_minute.value", plat="fliggy").source == "default"


def test_bad_load_does_not_pollute_previous_config():
    """坏装载必须在**替换之前**被挡住：上一份好配置仍原样生效。

    复核指出：`test_non_dict_override_block_is_rejected` 的注释声称验这件事，
    但它先装载坏配置（抛错）再装载空字典、断言的是 `default`——两种情形都成立，
    等于没验「旧配置有没有被搞坏」。这里补真断言：好配置 → 装载失败 → 好值还在。
    """
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"rate_per_minute.value": 9}}}})
    assert sp.resolve("rate_per_minute.value", plat="fliggy").value == 9
    with pytest.raises(ValueError):
        sp.set_config({"crawler": {"strategy_overrides": ["fliggy"]}})
    got = sp.resolve("rate_per_minute.value", plat="fliggy")
    assert (got.value, got.source) == (9, "channel"), (
        "装载失败之后旧配置被污染了：%r/%r" % (got.value, got.source))


def test_override_key_roundtrips_paths_containing_slash():
    """真实通路 id 里有 "/"（`H5/API`）：分隔符最多切两刀，段三允许含 "/"。

    复核裁决：`key.split("/", 2)`——plat/dim 永不含 "/"，段三可以含。
    `override_key` 与 `parse_override_key` 必须互为逆运算。
    """
    for plat, dim, path in (("ctrip", "intl", "H5/API"),
                            ("fliggy", "domestic", "PC"),
                            ("app_zhixing", "domestic", "app-city-%s"),
                            ("app_qunar", "domestic", "app-city-bjs")):
        key = sp.override_key(plat, dim, path)
        assert sp.parse_override_key(key) == (plat, dim, path), key
    assert sp.override_key("ctrip", "intl", "H5/API") == "ctrip/intl/H5/API"
    # 含 "/" 不等于免检：未知段照样抛
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/H5/API2")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/nosuch/path")
    # 端到端：段三带 "/" 的链路覆盖真的能生效
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/intl/H5/API": {"rate_per_minute.value": 4}}}})
    got = sp.resolve("rate_per_minute.value", plat="ctrip",
                     dim="intl", path="H5/API")
    assert (got.value, got.source) == (4, "path")


def test_template_path_must_be_consumed_whole():
    """`app-city-*` 类模板通路：模板前缀必须吃掉**整段**，不许再带 `/`。

    复核指出的洞：`ctrip/domestic/app-city-bjs/x` 走前缀匹配能装载，但求值时
    永远命不中 `PATH_CN` 里的任何通路名——装载成功、永不生效，正是本项目定义
    为最糟的「配了不生效」。字面量键（`H5/API`）不受影响，它自己就含 `/`。
    """
    assert sp.parse_override_key("ctrip/domestic/app-city-bjs") == \
        ("ctrip", "domestic", "app-city-bjs")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/domestic/app-city-bjs/x")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/domestic/app-city-%s/x")
    # 判据本身也钉一下（装载与求值必须同一口径）
    assert sp._path_ok("app-city-bjs") is True
    assert sp._path_ok("app-city-bjs/x") is False
    assert sp._path_ok("H5/API") is True
    assert sp._path_ok("ctrip/intl/H5/API") is False


def test_clamp_returns_note_so_ui_can_write_back():
    v, note = sp.clamp("ttl_tier.fast", 99999)
    assert v == 1440 and note


def test_container_kinds_are_map_and_list_and_pass_through():
    """容器键的 `kind` 必须如实：两个映射 + 一个列表。

    T12 照 `Param.kind` 画控件——把 `{渠道: 分钟}` 登记成 `int`，界面就会画一个
    数字框，填进去的东西谁也不读，正是本项目头号缺陷「配了不生效」。同时
    `resolve`/`clamp` 对容器值必须**原样透传**：不转类型、不夹取、不重写。
    """
    from core.strategy_contract import KINDS
    assert ("map" in KINDS) and ("list" in KINDS)
    assert sp.PARAMS["cadence.per_plat"].kind == "map"
    assert sp.PARAMS["proxy_route.map"].kind == "map"
    assert sp.PARAMS["warmup.platforms"].kind == "list"

    raw = {"crawler": {"cadence": {"ctrip": 30},
                       "proxy_map": {"ctrip": "socks5://127.0.0.1:1080"},
                       "warmup": {"platforms": ["ctrip", "qunar"]}}}
    sp.set_config(raw)
    assert sp.resolve("cadence.per_plat").value == {"ctrip": 30}
    assert sp.resolve("proxy_route.map").value == \
        {"ctrip": "socks5://127.0.0.1:1080"}
    assert sp.resolve("warmup.platforms").value == ["ctrip", "qunar"]

    for pid, val in (("cadence.per_plat", {"fliggy": 15}),
                     ("proxy_route.map", {"fliggy": "http://127.0.0.1:9"}),
                     ("warmup.platforms", ["tuniu"])):
        got, note = sp.clamp(pid, val)
        assert (got, note) == (val, ""), pid


# 模块级可写状态白名单：除了 cfg 单例与**声明索引**，这里不该有第二处状态。
# 声明索引只装 `core/strategy_contract.py` 里不可变的 `Param`，从不装求值结果。
_WRITABLE = frozenset({
    "_CFG",          # 唯一的状态：当前装入的配置（引用语义 = 热生效）
    "PARAMS",        # 声明索引（pid → Param），不装值
    "DUP_PIDS",      # 重复 pid 名单（导入期算一次）
    "_MISSING",      # 取值哨兵
    "_TRUE", "_FALSE",   # 真假字面量表
    "OVERRIDE_CFG", "SOURCES", "PLATS", "Resolved",
    # r1063 波次 2 起：`switch_on()` 的「同一次坏值只告警一次」去重集合。
    # 它只装 `(pid, repr(值))` 这类**已告警过**的键，从不装求值结果，
    # 因此不构成第二处参数状态；下面三条断言仍然保证它不缓存值。
    "TRUE_WORDS", "FALSE_WORDS", "_SWITCH_WARNED",
})


def test_hot_singleton_carries_no_second_writable_state():
    """热链路的硬约束：参数只在提供者里现算，模块级没有第二处可写状态。

    旧版这条断言 `core/policy.py` 里不含 `self._pace =` / `self._block_s =`
    ——两个标识符**根本不存在**，用例恒真（复核实测：policy.py:108 的真实
    风险形态是 `self.pace_factor = …`，扫不到）。改成行为型断言：
    """
    import types

    # ① 行为：同一进程两次 set_config 立刻生效——不重建、不 invalidate
    sp.set_config({"schedule": {"fast_ttl_min": 40}})
    assert sp.resolve("ttl_tier.fast").value == 40
    sp.set_config({"schedule": {"fast_ttl_min": 7}})
    assert sp.resolve("ttl_tier.fast").value == 7

    # ② 求值结果是不可变值对象（没人能往实例上挂缓存）
    assert issubclass(sp.Resolved, tuple)
    assert sp.Resolved._fields == ("value", "source", "pid")

    # ③ 模块级名字集合：白名单之外不许出现可写容器/对象
    extra = []
    for name, obj in vars(sp).items():
        if name.startswith("__") or name in _WRITABLE:
            continue
        if isinstance(obj, (types.FunctionType, types.ModuleType, type)):
            continue                      # 函数/模块/类：引用，不是状态
        if isinstance(obj, (str, int, float, bool, tuple, frozenset,
                            type(None))):
            continue                      # 不可变字面量/常量
        if type(obj).__module__ in ("typing", "__future__"):
            continue                      # typing 构造子 / `annotations` 标志
        extra.append(name)
    assert not extra, "模块里出现了白名单外的模块级状态：%s" % extra
