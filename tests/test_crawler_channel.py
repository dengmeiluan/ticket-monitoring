# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r613_app_channel_selectable.py
- tests/test_r622_channel_names_match_registry.py
- tests/test_r623_new_channel_sync_points.py
- tests/test_r655_channel_list_single_source.py
- tests/test_r668_new_app_channel_has_a_home_in_every_section.py
- tests/test_r674_app_channel_unified.py
- tests/test_r677_channel_dimension_matrix.py
- tests/test_r813_channel_platform_contract.py
- tests/test_r996_channel_surface_census.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.channel_contract as cc
import crawlers
import inspect
import io
import os
import pytest
import re
import socket
import subprocess
import sys
import time
import urllib.request

from core.channels import APP_BROWSER_PEER, APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_CN, CHANNEL_DIMENSIONS, DIMENSIONS, DIMENSION_SCOPE, app_alignment_gaps, dim_state, unsupported_dims
from crawlers.app_base import AppCrawler
from crawlers.app_qunar import AppQunarCrawler
from crawlers.app_zhixing import AppZhixingCrawler


# ---- merged from tests/test_r613_app_channel_selectable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_app_channel_is_selectable():
    """App 渠道 chip 由 APP_PLAT_NAME 派生（r665 起不再逐个写死）。"""
    w = _w()
    i = w.index("chip pch p-${p}")
    seg = w[i:i + 900]
    assert "APP_PLAT_NAME" in seg and "p-${p}" in seg, (
        "App 渠道 chip 应通过 APP_PLAT_NAME 派生：%s" % seg[:200])
    assert "togPlat(${i},'${p}',this)" in seg, (
        "App 渠道 chip 没有接到 togPlat（点了不会写 platforms）")


def test_app_chip_states_its_dependency():
    """必须点明依赖 Android 总开关，否则用户勾了却不跑，无从判断。"""
    w = _w()
    i = w.index("title=\"真机采集（${APP_PLAT_NAME[p]}）")
    seg = w[i:i + 300]
    assert "Android" in seg and "总开关" in seg, (
        "App 渠道 chip 没说明它依赖 Android 真机通道总开关：%s" % seg[:120])


def test_every_registry_channel_has_a_chip():
    """REGISTRY 里的每个渠道都要能在页面上勾选——这是通用不变式。"""
    import sys
    sys.path.insert(0, ROOT)
    from crawlers import REGISTRY
    w = _w()
    i = w.index("chip pch p-${p}")
    seg = w[i:i + 900]
    # 渠道 chip 有两个来源：`PLATS` 动态表（p-${p}）与
    # `APP_PLAT_NAME` 动态表（同样 p-${p}，App 渠道走这个）。
    # 两张表都是从源码解析出来的真实键，不是写死清单。
    dyn = set()
    k = w.index("const PLATS={")
    for part in w[k:w.index("}", k)].split(","):
        if ":" in part:
            dyn.add(part.split(":", 1)[0].strip().split()[-1].strip("'\""))
    ak = w.index("const APP_PLAT_NAME={")
    body = w[ak:w.index("};", ak)]
    for part in body.split("{", 1)[1].split(","):
        if ":" in part:
            dyn.add(part.split(":", 1)[0].strip().strip("'\""))
    missing = [c for c in REGISTRY
               if c not in dyn and ("p-" + c) not in seg and ("'%s'" % c) not in seg]
    assert not missing, "这些已注册渠道在页面上勾不到：%s" % missing




# ---- merged from tests/test_r622_channel_names_match_registry.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _app_names():
    w = webui_full_src()
    m = re.search(r"const APP_PLAT_NAME=\{(.*?)\};", w, re.S)
    assert m, "找不到 APP_PLAT_NAME 声明"
    return set(re.findall(r"([A-Za-z_][\w]*)\s*:", m.group(1)))


def test_app_name_table_only_lists_real_channels():
    from crawlers import REGISTRY
    named = _app_names()
    assert named, "APP_PLAT_NAME 为空（名字表失去意义）"
    ghost = sorted(named - set(REGISTRY))
    assert not ghost, (
        "名字表里有 REGISTRY 中不存在的渠道（界面会宣称一个跑不起来的渠道）：%s\n"
        "现有 REGISTRY：%s" % (ghost, sorted(REGISTRY)))


def test_registry_app_channels_are_all_named():
    """反过来也要成立：REGISTRY 里的 App 渠道必须有中文名（不能露原始 id）。"""
    from crawlers import REGISTRY
    named = _app_names()
    missing = sorted(k for k in REGISTRY if k.startswith("app_") and k not in named)
    assert not missing, "这些 App 渠道没有中文名（界面会显示原始 id）：%s" % missing


def test_unimplemented_meituan_is_not_advertised():
    """美团 App 解析未接入——在接入前不得出现在名字表里。"""
    assert "app_meituan" not in _app_names(), (
        "美团 App 尚未接入采集器，却已经出现在渠道名表里")
    w = webui_full_src()
    assert "p-app_meituan" not in w, (
        "配置页出现了美团 App 的勾选 chip，但后端没有这个渠道")


# ---- merged from tests/test_r623_new_channel_sync_points.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


def _alt_list(src, anchor):
    """取某个 `re.compile(` 调用里所有 r"..." 片段中的渠道名。

    正则可能跨行书写（`_SENT` 就是两段拼接），所以先把该 compile 调用
    的整段参数取出来（到匹配的右括号），再收集其中所有原始字符串。
    """
    i = src.index(anchor)
    # 从 anchor 起找配对的右括号
    j = src.index("(", i + len(anchor) - 1)
    depth = 0
    k = j
    while k < len(src):
        ch = src[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        k += 1
    body = src[j:k]
    names = set()
    for part in re.findall(r'r"([^"]*)"', body):
        names.update(p for p in re.split(r"[|()\\\[\]^$]+", part)
                     if re.fullmatch(r"[a-z_][a-z0-9_]*", p))
    return names


def test_health_log_regex_covers_every_registered_channel():
    """正则必须**真的**认得出每个已注册渠道的日志行。

    判据从「源码里有没有这个字面量」改成「喂一行日志进去能不能匹配」：
    `core/health.py` 现在由 `core.channels.BROWSER_CHANNELS +
    APP_CHANNELS` 拼出 `_PLAT_ALT`（单一事实源），字面量已不在正则体内。
    再扫 `_PLAT = re.compile(` 里的 r"..." 片段就永远解析不到，
    变成「代码更对了、门禁却红了」的假红（本文件 r665 实况）。
    """
    from crawlers import REGISTRY
    import core.health as health

    missing = []
    for plat in REGISTRY:
        line = "[%s] 最低价 ￥1200" % plat
        if not health._PLAT.match(line):
            missing.append(("_PLAT", plat))
        sent = "[解析哨兵] %s 字段缺失" % plat
        if not health._SENT.match(sent):
            missing.append(("_SENT", plat))
    assert not missing, (
        "这些渠道的日志行解析不出来（健康卡上像「没在跑」）：%s" % missing)


def test_alert_name_table_covers_every_registered_channel():
    """告警文案里的渠道名表必须覆盖每个已注册渠道，且不多出死条目。

    `core/channel_alert.py` 现在是 `from core.channels import CHANNEL_CN as CN`
    （r665 起的单一事实源），文件里没有内联 `CN = {...}`。这里直接导入运行时
    的 `CN` 对账，不再要求源码里存在某个字面量形状。
    """
    from crawlers import REGISTRY
    from core.channel_alert import CN

    missing = sorted(set(REGISTRY) - set(CN))
    assert not missing, (
        "告警名表 CN 漏了这些渠道（告警里会露原始 id）：%s" % missing)
    ghost = sorted(set(CN) - set(REGISTRY))
    assert not ghost, "告警名表里有 REGISTRY 中不存在的渠道：%s" % ghost


# ---- merged from tests/test_r655_channel_list_single_source.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_all_sides_share_one_tuple():
    import crawlers
    from core import channels, health_diag, pacing
    assert crawlers.APP_CHANNELS == channels.APP_CHANNELS
    assert pacing.APP_CHANNELS == channels.APP_CHANNELS
    assert health_diag.APP_CHANNELS == channels.APP_CHANNELS


def test_health_diag_cn_has_every_app_channel():
    """每个 App 渠道都要有中文名，否则界面显示裸 id。"""
    from core import channels, health_diag
    for p in channels.APP_CHANNELS:
        assert health_diag.CN.get(p), "%s 在诊断卡里没有中文名" % p


def test_no_second_hardcoded_app_list():
    """源码里不得再出现第二份写死的 App 渠道元组。"""
    for rel in ("core/pacing.py", "core/health_diag.py"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8",
                      newline="").read()
        assert 'APP_CHANNELS = ("app_zhixing"' not in src, (
            "%s 里又写死了一份渠道清单，加渠道时会漏改" % rel)


def test_channels_module_is_dependency_free():
    """core/channels.py 只放常量：一旦它 import 项目内模块就会重新引入
    core → crawlers → core 的循环。"""
    import re
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8", newline="").read()
    # 只看真正的 import 语句（注释里提到路径是允许的）
    for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M):
        mod = m.group(1)
        assert not mod.startswith("crawlers") and not mod.startswith("core"), (
            "core/channels.py 不应依赖项目内模块：%s" % mod)


def test_browser_and_app_sets_do_not_overlap():
    from core import channels
    assert not (set(channels.BROWSER_CHANNELS) & set(channels.APP_CHANNELS))


# ---- merged from tests/test_r668_new_app_channel_has_a_home_in_every_section.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)














# ---- merged from tests/test_r674_app_channel_unified.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _qunar():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.paths = []
    c.login_suspect = False
    c.logger = _Log()
    return c


def _zhixing():
    c = AppZhixingCrawler.__new__(AppZhixingCrawler)
    c.name = "app_zhixing"
    c.paths = []
    c.logger = _Log()
    return c


# ---------- 一、全渠道统一：能力都在基类 ----------
def test_route_memory_lives_in_base_for_all_app_channels():
    for cls in (AppQunarCrawler, AppZhixingCrawler):
        assert issubclass(cls, AppCrawler)
        # 两个渠道都从基类继承同一份判据，不再各自实现
        assert cls._route_unchanged is AppCrawler._route_unchanged, cls
        assert cls._city_name is AppCrawler._city_name, cls
        assert cls.note_date is AppCrawler.note_date, cls


def test_city_name_is_single_source():
    """三字码 → 中文城市名：两个渠道必须给同一个答案。"""
    for code, want in (("SHA", "上海"), ("PEK", "北京"), ("CAN", "广州"),
                       ("CTU", "成都")):
        assert AppQunarCrawler._city_name(code) == want, code
        assert AppZhixingCrawler._city_name(code) == want, code


def test_unknown_city_code_passes_through():
    """查不到就原样传下去——宁可显式失败，不要瞎猜一个城市。"""
    assert AppCrawler._city_name("ZZZ") == "ZZZ"
    assert AppCrawler._city_name("") == ""


def test_qunar_no_longer_has_private_alias_table():
    """去哪儿不得再维护第二套城市别名表。"""
    import crawlers.app_qunar as M
    assert not hasattr(M, "_CITY_ALIAS"), "去哪儿又抄了一份城市别名表"


# ---------- 二、逐日期记账单源 ----------
def test_note_date_semantics_are_one_source():
    c = _qunar()
    c.note_date("2026-11-01", [{"price": 1}], "ok")
    c.note_date("2026-11-02", [], "empty")             # 确认无航班
    c.note_date("2026-11-03", [], "no-list-page")      # 没采到
    c.note_date("2026-11-04", [], "pick-date-failed")
    got = [(p["date"], p["status"]) for p in c.paths]
    assert got == [("2026-11-01", "ok"), ("2026-11-02", "empty"),
                   ("2026-11-03", "timeout"), ("2026-11-04", "timeout")], got
    # 通路名与智行/浏览器一致
    assert {p["path"] for p in c.paths} == {"航班明细"}


def test_empty_still_requires_reason():
    """只有 reason=="empty" 才记 empty；其它原因一律 timeout。"""
    c = _qunar()
    for why in ("no-home", "set-city-dep", "no-search-button",
                "", "exception:TimeoutError"):
        c.note_date("2026-11-0" + str(len(c.paths) + 1), [], why)
    assert all(p["status"] == "timeout" for p in c.paths), c.paths


# ---------- 三、去哪儿多日期 ----------
def test_multi_date_records_one_row_per_date():
    """两个日期各记一条账，日期不串。"""
    c = _qunar()
    calls = []

    def fake_one(dev, fn, tn, target, fc="", tc=""):
        calls.append(target)
        rows = [{"flight_no": "CA100", "depart_time": "08:00",
                 "arrive_time": "10:00", "price": 300}]
        return c._to_prices(rows, target, "BJS", "SHA"), "ok"

    c._open_flight_home = lambda dev: True
    c._ensure_home = lambda dev: "<x/>"
    c._one_date = fake_one
    out = c._fetch_locked(_Dev(), "BJS", "SHA", ["2026-11-01", "2026-11-02"])
    assert calls == ["2026-11-01", "2026-11-02"], calls
    assert [o.depart_date for o in out] == ["2026-11-01", "2026-11-02"]
    assert [(p["date"], p["status"]) for p in c.paths] == [
        ("2026-11-01", "ok"), ("2026-11-02", "ok")]


def test_multi_date_failure_is_isolated():
    """一个日期失败，另一个照常产出；失败日不记 empty。"""
    c = _qunar()

    def fake_one(dev, fn, tn, target, fc="", tc=""):
        if target == "2026-11-02":
            return [], "pick-date-failed"
        rows = [{"flight_no": "CA100", "depart_time": "08:00",
                 "arrive_time": "10:00", "price": 300}]
        return c._to_prices(rows, target, "BJS", "SHA"), "ok"

    c._open_flight_home = lambda dev: True
    c._ensure_home = lambda dev: "<x/>"
    c._one_date = fake_one
    out = c._fetch_locked(_Dev(), "BJS", "SHA", ["2026-11-01", "2026-11-02"])
    assert [o.depart_date for o in out] == ["2026-11-01"]
    st = {p["date"]: p["status"] for p in c.paths}
    assert st == {"2026-11-01": "ok", "2026-11-02": "timeout"}, st


def test_route_unchanged_skips_setting_cities():
    """航线未变时不得重复设城市（多日期下每日期省 ~20s）。"""
    c = _qunar()
    set_calls = []

    c._ensure_home = lambda dev: "<home/>"
    c.read_route = lambda dev: ("北京", "上海")
    c._set_city = lambda dev, xml, city, side, **kw: set_calls.append(city) or True
    c._pick_date = lambda dev, xml, target: True
    c._search_and_parse = lambda dev, target, fc="", tc="": ([], "empty")

    c._one_date(_Dev(), "北京", "上海", "2026-11-01", "BJS", "SHA")
    assert set_calls == [], "航线已对却还在重设城市：%s" % set_calls


def test_route_changed_sets_both_cities():
    """航线变了要按顺序重设出发+到达。"""
    c = _qunar()
    set_calls = []

    c._ensure_home = lambda dev: "<home/>"
    c.read_route = lambda dev: ("北京", "上海")      # 屏幕上是旧航线
    c._set_city = lambda dev, xml, city, side, **kw: set_calls.append((side, city)) or True
    c._pick_date = lambda dev, xml, target: True
    c._search_and_parse = lambda dev, target, fc="", tc="": ([], "empty")

    c._one_date(_Dev(), "北京", "广州", "2026-11-01", "BJS", "CAN")
    assert set_calls == [("dep", "北京"), ("arr", "广州")], set_calls


def test_pick_date_failure_does_not_search():
    """选日失败时绝不能搜——否则会把上一个日期的价记到目标日期名下。"""
    c = _qunar()
    searched = []

    c._ensure_home = lambda dev: "<home/>"
    c.read_route = lambda dev: ("北京", "上海")
    c._set_city = lambda dev, xml, city, side, **kw: True
    c._pick_date = lambda dev, xml, target: False
    c._search_and_parse = lambda dev, target, fc="", tc="": (
        searched.append(target) or ([], "ok"))

    got, why = c._one_date(_Dev(), "北京", "上海", "2026-11-02", "BJS", "SHA")
    assert got == []
    assert why == "pick-date-failed", why
    assert searched == [], "选日失败却仍然搜了：%s" % searched


def test_read_route_reads_home_city_fields():
    """read_route 从首页城市控件取事实，不在首页返回 None。"""
    c = _qunar()

    class D:
        def __init__(self, xml):
            self._xml = xml

        def dump(self, retries=2):
            return self._xml

    home = ('<hierarchy><node resource-id="com.Qunar:id/atom_flight_search_panel_view"'
            ' bounds="[0,397][1600,826]" />'
            '<node text="北京" resource-id="com.Qunar:id/atom_flight_tv_dep_city"'
            ' bounds="[48,487][120,540]" />'
            '<node text="上海" resource-id="com.Qunar:id/atom_flight_tv_arr_city"'
            ' bounds="[1480,487][1552,540]" /></hierarchy>')
    assert c.read_route(D(home)) == ("北京", "上海")
    assert c.read_route(D("<hierarchy></hierarchy>")) is None


class _Dev:
    """最小设备替身：dump + swipe（滚动是链路的一部分，必须能记录）。"""

    def __init__(self):
        self.swipes = []

    def dump(self, retries=2):
        return '<hierarchy><node text="x" bounds="[0,0][1,1]" /></hierarchy>'

    def swipe(self, x1, y1, x2, y2, dur=400):
        self.swipes.append((x1, y1, x2, y2))
        return True

    def tap(self, x, y):
        return True


# ---------- 四、与 PC/H5 对齐：不支持的维度要显式落账 ----------
def test_round_trip_is_explicit_unsupported():
    """**不支持**往返的渠道必须显式记 unsupported 并返回空。

    静默忽略 ret_date 会把单程价当成往返总价，推送/走势据此报警——
    浏览器渠道（qunar TRIP）就是显式 unsupported 的口径，App 必须同款。

    2026-10-31：两个 App 渠道都已在真机上跑通往返（智行去/返双列、
    去哪儿左右两列 + 页脚总额），所以这条断言改用**临时关掉能力**的
    合成渠道来验闸门本体——否则「两家都支持」会让这条守卫无对象可测
    （看着全绿，实则是空转）。
    """
    for cls in (AppQunarCrawler, AppZhixingCrawler):
        c = cls.__new__(cls)
        c.name = getattr(cls, "name", "app")
        c.paths = []
        c.logger = _Log()
        c.last_error = ""
        c.supports_round_trip = False          # 合成：这家「还没做往返」
        called = []
        c.fetch = lambda *a, **k: called.append(1) or []
        out = c.safe_fetch("SHA", "CAN", ["2026-11-01"], ret_date="2026-11-05")
        assert out == []
        assert called == [], "不支持往返却仍发起了单程查询：%s" % cls
        st = [(p["path"], p["status"]) for p in c.paths]
        assert ("TRIP", "unsupported") in st, st


def test_channel_declares_round_trip_support_flag():
    """能力是**声明式**的：基类默认 False，支持往返的渠道改一处即可。

    2026-10-31 真机：智行（去/返双列）与去哪儿（左右两列 + 页脚总额）
    都跑通了往返，两个 App 渠道各自把类属性改成 True；基类仍默认 False，
    新增 App 渠道不显式声明就不支持。
    """
    assert AppCrawler.supports_round_trip is False
    assert AppQunarCrawler.supports_round_trip is True
    assert AppZhixingCrawler.supports_round_trip is True


def test_supported_round_trip_channel_is_not_blocked():
    """声明支持的渠道不得被这道闸门拦下。"""
    c = _qunar()
    c.last_error = ""
    c.supports_round_trip = True
    hit = []
    c.fetch = lambda *a, **k: hit.append(k.get("ret_date")) or []
    c.safe_fetch("SHA", "CAN", ["2026-11-01"], ret_date="2026-11-05")
    assert hit == ["2026-11-05"], hit


# ---- merged from tests/test_r677_channel_dimension_matrix.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_every_registered_channel_has_every_dimension():
    """注册了渠道就必须对每个维度表态——缺项就是没人想过。"""
    missing = []
    for plat in crawlers.REGISTRY:
        row = CHANNEL_DIMENSIONS.get(plat)
        if row is None:
            missing.append((plat, "整行缺失"))
            continue
        for d in DIMENSIONS:
            if d not in row:
                missing.append((plat, d))
            elif row[d] not in ("y", "n", ""):
                missing.append((plat, d, "非法取值 %r" % row[d]))
    assert not missing, "渠道维度矩阵有缺项：%s" % missing[:8]


def test_dimension_states_are_only_three_values():
    for plat, row in CHANNEL_DIMENSIONS.items():
        for d, v in row.items():
            assert v in ("y", "n", ""), (plat, d, v)


def test_app_channels_declare_browser_peer():
    """没有基准就没法谈「对齐」。"""
    for p in APP_CHANNELS:
        assert p in APP_BROWSER_PEER, "%s 没声明对齐基准" % p
        assert APP_BROWSER_PEER[p] in BROWSER_CHANNELS, APP_BROWSER_PEER[p]


def test_round_trip_declared_unsupported_matches_code():
    """声明 `n` 的维度，代码里必须真的有不支持分支。

    反向也成立：基类默认 `supports_round_trip=False`，声明 y 却走默认值
    就是**声明与行为打架**——用户会看到「支持」却永远拿不到数据。
    """
    for plat in APP_CHANNELS:
        if dim_state(plat, "round_trip") == "n":
            cls = crawlers.REGISTRY[plat]
            assert getattr(cls, "supports_round_trip", False) is False, \
                "%s 声明不支持往返，但类属性说支持" % plat
        elif dim_state(plat, "round_trip") == "y":
            cls = crawlers.REGISTRY[plat]
            assert getattr(cls, "supports_round_trip", False) is True, \
                "%s 声明支持往返，但类属性仍是默认 False（会静默 unsupported）" % plat
    # 基类这道闸门本身要在（声明式能力的执行点）
    from crawlers.app_base import AppCrawler
    src = inspect.getsource(AppCrawler.safe_fetch)
    assert "supports_round_trip" in src, src[:300]


def test_unsupported_dims_is_derived_not_handwritten():
    """明确不支持的维度是**推导**出来的，不是手写清单。"""
    # 两家 App 的往返都已真机跑通（2026-10-31），不再是 unsupported
    assert "round_trip" not in unsupported_dims("app_qunar"), \
        unsupported_dims("app_qunar")
    assert "round_trip" not in unsupported_dims("app_zhixing"), \
        unsupported_dims("app_zhixing")
    # 去哪儿网页版 PC/H5 已停服（2026-11）：整行 n 是「停服」而非
    # 「渠道没有」，矩阵会画「停」并用说明讲清数据走 app_qunar。
    assert set(unsupported_dims("qunar")) == {
        "domestic", "intl", "calendar", "detail",
        "round_trip", "multi_city", "low_fare"}
    assert "multi_city" not in unsupported_dims("app_qunar")
    assert "multi_city" not in unsupported_dims("app_zhixing")


def test_alignment_gaps_are_enumerable_not_vague():
    """缺口必须是可枚举的清单，能直接当待办用。

    基准是「**任一**浏览器渠道已具备该维度」（用户原话：PC/H5 渠道拥有的
    能力 App 都要对齐有），不是「某一家同源友商有」——按单个同行判会
    自证：携程自己 round_trip 未验证，于是「智行 ↔ 携程」永远算不出往返
    缺口，而网页端飞猪/同程明明支持。as of 2026-11-02 晚：智行与去哪儿
    App 国内/国际/日历/明细/往返/低价机票**全部落地**；2026-11-03 ctrip PC
    多程 2 段升 y 后，App 端未接多程，缺口清单应**精确为** `("multi_city",)`。
    """
    assert app_alignment_gaps("app_qunar") == ("multi_city",), (
        "去哪儿 App 仅剩多程缺口：%r" % (app_alignment_gaps("app_qunar"),))
    assert app_alignment_gaps("app_zhixing") == ("multi_city",)
    # 缺口是空集合时，上面的 all(...) 会恒真——所以下面另造一个非空场景
    # 验证函数真的会报缺口（见 try 块），这里就不再写恒真式。
    # 函数本身不能因为「都对齐了」就退化成恒空：造一个「基准有、App 无」
    # 的临时场景，它必须把那一维报出来（否则这层门禁就成了摆设）。
    from core.channels import APP_BROWSER_PEER, CHANNEL_DIMENSIONS
    # 造「浏览器端有、App 没有」的临时场景：浏览器 qunar 的 low_fare 置 y，
    # app_qunar 置 ""（未验证），缺口必须出现；finally 里还原**保存值**。
    saved = {p2: (CHANNEL_DIMENSIONS[p2] or {}).get("low_fare", "")
             for p2 in CHANNEL_DIMENSIONS}
    try:
        CHANNEL_DIMENSIONS["qunar"]["low_fare"] = "y"
        CHANNEL_DIMENSIONS["app_qunar"]["low_fare"] = ""
        gaps = app_alignment_gaps("app_qunar")
        assert "low_fare" in gaps, gaps
    finally:
        for p2, val in saved.items():
            CHANNEL_DIMENSIONS[p2]["low_fare"] = val
    assert APP_BROWSER_PEER["app_qunar"] == "qunar"


def test_app_is_allowed_to_exceed_peer():
    """App 比浏览器端**多**出来的能力不算缺口（用户明确说 App 信息更全）。

    判据方向：缺口只来自「浏览器端有 y、App 不是 y」，App 为 y 而浏览器
    端没有的维度绝不能出现在缺口里（否则「更全」反被判成待办）。
    """
    from core.channels import CHANNEL_DIMENSIONS as M
    peer_union = {d for p in BROWSER_CHANNELS for d in DIMENSIONS
                  if (M.get(p) or {}).get(d) == "y"}
    for plat in APP_CHANNELS:
        gaps = app_alignment_gaps(plat)
        assert set(gaps) <= peer_union, (
            "%s 的缺口里出现了浏览器端并不具备的维度：%s" % (plat, gaps))
        extra = {d for d in DIMENSIONS
                 if dim_state(plat, d) == "y" and d not in peer_union}
        assert not (extra & set(gaps)), (
            "%s 比浏览器端多出来的能力被算成了缺口：%s" % (plat, extra))


def test_unknown_dimension_is_not_treated_as_supported():
    """未验证（`""`）绝不能被读成「支持」。

    注意别把**已接入**的维度写死成 `""` 来守这条：r732 把智行「特价」
    接入后（真机确认它也是逐天报价），原来那句
    `dim_state("app_zhixing","low_fare") == ""` 就变成了「守旧事实」，
    红灯只说明接入成功而不是判据坏了。这里改用**真正没接过**的东西：
    不存在的渠道 / 不存在的维度，必须一律返回 `""`。
    """
    assert dim_state("app_zhixing", "low_fare") == "y", (
        "智行「特价」已按 low_fare 接入（r732）；若退回未接入请同步改这里")
    assert dim_state("no_such_plat", "domestic") == ""
    assert dim_state("app_qunar", "no_such_dim") == ""
    assert dim_state("ctrip", "no_such_dim") == ""


# ---------- 恢复快照的两种失败要分得开 ----------
def test_login_wall_detection_is_per_channel():
    """各渠道登录墙形态不同：去哪儿是手机号表单，智行是「立即登录」文案。"""
    from crawlers.app_qunar import AppQunarCrawler
    from crawlers.app_zhixing import AppZhixingCrawler

    qunar_wall = ('<hierarchy><node text="请输入手机号" bounds="[0,0][1,1]" />'
                  '</hierarchy>')
    zx_wall = ('<hierarchy><node text="立即登录" bounds="[0,0][1,1]" />'
               '</hierarchy>')
    home = ('<hierarchy><node text="单程" bounds="[0,0][1,1]" />'
            '<node text="搜索" bounds="[0,0][1,1]" /></hierarchy>')

    q = AppQunarCrawler.__new__(AppQunarCrawler)
    z = AppZhixingCrawler.__new__(AppZhixingCrawler)
    assert q.is_login_wall(qunar_wall) is True
    assert q.is_login_wall(home) is False
    assert z.is_login_wall(zx_wall) is True


def test_expired_snapshot_is_reported_not_silent():
    """恢复了快照却仍在登录墙 → 账本要写「快照已失效」，别只留一句 login。

    这跟「恢复失败」是两件事：前者该重新登录，后者该查文件。
    """
    import inspect
    from crawlers.app_base import AppCrawler
    src = inspect.getsource(AppCrawler.restore_login_snapshot)
    assert "is_login_wall" in src, "恢复流程没校验登录墙"
    assert "快照已失效" in src, "失效快照没有可读结论"


# ---------- 声明必须有代码证据（防"看起来应该支持"） ----------
def test_multi_city_y_only_for_verified_ctrip_two_segments():
    """只有 ctrip PC 2 段可声明 y，且必须带「仅 2 段」scope。

    2026-11-03 生产行 ¥1476（IJ004+MM304）证明 2 段整单链路可用；
    3+ 段实测无组合卡、缺口程未验。其余渠道仍未接，不得声明 y。
    """
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for plat in BROWSER_CHANNELS + APP_CHANNELS:
        if plat == "ctrip":
            assert dim_state(plat, "multi_city") == "y", \
                "ctrip 已有 2 段生产整单行，矩阵却未声明 y"
            assert DIMENSION_SCOPE.get((plat, "multi_city")) == "仅 2 段", \
                "ctrip 多程只验证 2 段，scope 必须写明"
        else:
            assert dim_state(plat, "multi_city") != "y", \
                "%s 声明支持多程，但代码里没有实现" % plat
    ctrip = io.open(os.path.join(root, "crawlers", "ctrip.py"),
                    encoding="utf-8", newline="").read()
    assert "def fetch_multi(" in ctrip, "ctrip 声明 y 但没有 fetch_multi"
    for f in ("qunar.py", "fliggy.py", "tongcheng.py", "tuniu.py"):
        src = io.open(os.path.join(root, "crawlers", f),
                      encoding="utf-8", newline="").read()
        assert "multi_city" not in src and "多程查询" not in src, f


def test_browser_round_trip_y_or_explicit_intl_gap():
    """浏览器渠道国内往返已全部接通；国际未验证的必须有显式分支。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert dim_state("ctrip", "round_trip") == "y"
    assert dim_state("qunar", "round_trip") == "n", "去哪儿网页版已停服"
    qsrc = io.open(os.path.join(root, "crawlers", "qunar.py"),
                   encoding="utf-8", newline="").read()
    assert "国际往返暂不支持" in qsrc, \
        "qunar 国际往返未验证，必须在源码里显式拒绝"
    csrc = io.open(os.path.join(root, "crawlers", "ctrip.py"),
                   encoding="utf-8", newline="").read()
    assert "_fetch_rt" in csrc and "containstax=1" in csrc


# ---- merged from tests/test_r813_channel_platform_contract.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ALL = tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)


def test_axes_cover_every_requested_quality():
    """用户点名的 11 条一条不少，顺序稳定（文档/报告都按这个顺序读）。"""
    assert cc.AXIS_IDS == (
        "configurable", "observable", "intervenable", "visible",
        "traceable", "identifiable", "distinguishable", "idempotent",
        "semantics", "actionable", "judgeable",
    )
    assert len(set(cc.AXIS_CN.values())) == len(cc.AXIS_IDS), "中文名必须唯一"


def test_every_registered_channel_has_every_axis():
    matrix = cc.audit_all()
    assert set(matrix) == set(ALL)
    for plat, row in matrix.items():
        assert set(row) == set(cc.AXIS_IDS), plat
        for axis, cell in row.items():
            assert cell.state in (cc.Y, cc.N, cc.NA), (plat, axis, cell.state)
            assert cell.detail, (plat, axis)


def test_current_wiring_has_no_gap():
    """新增渠道时最先红的就是这条：报告会点名缺哪一格、看哪里。"""
    g = cc.gaps()
    assert not g, "渠道平台契约出现缺口：\n" + cc.render_text()


def test_report_is_human_readable():
    text = cc.render_text()
    for plat in ALL:
        assert plat in text
    for cn in cc.AXIS_CN.values():
        assert cn[:4] in text, cn
    assert "缺口" in text or "无缺口" in text


def test_ghost_channel_is_reported_not_silently_green():
    """负控①：未登记渠道不能因为「函数不抛异常」就算通过。"""
    row = cc.audit("ghost_app")
    red = [a for a, c in row.items() if c.state == cc.N]
    assert set(red) >= {"configurable", "observable", "intervenable",
                        "visible", "traceable", "identifiable",
                        "distinguishable", "idempotent", "semantics",
                        "judgeable"}, red
    assert "ghost_app" in cc.render_text({"ghost_app": row})


def test_missing_chinese_name_is_a_gap(monkeypatch):
    """负控②：删掉中文名，可识别格必须红（而不是兜底成裸 id 也算过）。"""
    monkeypatch.delitem(CHANNEL_CN, "app_qunar")
    matrix = cc.audit_all()
    cell = matrix["app_qunar"]["identifiable"]
    assert cell.state == cc.N, cell
    assert "中文名" in cell.detail


def test_channel_hidden_from_radar_is_a_gap(monkeypatch):
    """负控③：把智行踢出雷达白名单（本次修的真实缺陷），可见性格必须红。"""
    import core.special_radar as radar
    monkeypatch.setattr(
        radar, "_CHANNELS",
        tuple(p for p in radar._CHANNELS if p != "app_zhixing"))
    matrix = cc.audit_all()
    cell = matrix["app_zhixing"]["visible"]
    assert cell.state == cc.N, cell
    assert "特价雷达" in cell.detail


def test_advice_without_landing_is_a_gap(monkeypatch):
    """负控④：建议只有英文动作、没有中文说明 → 可指导格必须红。"""
    import core.pacing as pacing
    monkeypatch.setattr(
        pacing, "advise",
        lambda *a, **k: {"state": "login", "action": "relogin",
                         "hint": "", "severity": "act"})
    matrix = cc.audit_all()
    cell = matrix["ctrip"]["actionable"]
    assert cell.state == cc.N, cell


def test_semantics_rejects_illegal_tristate(monkeypatch):
    """负控⑤：把某维改成 y/n/"" 之外的值 → 语义清晰格必须红。"""
    import core.channels as ch
    row = dict(ch.CHANNEL_DIMENSIONS["tuniu"])
    row["calendar"] = "yes"
    matrix = dict(ch.CHANNEL_DIMENSIONS)
    matrix["tuniu"] = row
    monkeypatch.setattr(ch, "CHANNEL_DIMENSIONS", matrix)
    cells = cc.audit_all()
    assert cells["tuniu"]["semantics"].state == cc.N


def test_browser_platform_lists_are_aliases_not_copies():
    """浏览器渠道清单只能有一个对象：节奏/诊断/入口板不得再手抄一份。

    r813 前这三处各写一份 `("ctrip","qunar","fliggy","tongcheng","tuniu")`；
    加渠道时漏改任意一处，就出现「能采但不在节流表/诊断卡/入口板」。
    用 `is` 而不是 `==`：相等的副本同样会在下次加渠道时漂移。
    """
    import core.channel_links as links
    import core.health_diag as diag
    import core.pacing as pacing
    from core.channels import BROWSER_CHANNELS
    assert pacing.PLATFORMS is BROWSER_CHANNELS
    assert diag.PLATFORMS is BROWSER_CHANNELS
    assert links.PLATS is BROWSER_CHANNELS


def test_crawler_app_channels_is_the_same_object():
    """`crawlers.APP_CHANNELS` 必须是 core 那份本身，不能是副本。

    bootstrap（设备引导）读的是 crawlers 这份；新增 App 渠道只改 core 时，
    副本会让新渠道「能采但设备引导永远不认」。
    """
    import crawlers
    from core.channels import APP_CHANNELS
    assert crawlers.APP_CHANNELS is APP_CHANNELS


def test_probe_picker_is_counted_as_a_visible_surface():
    """检索页的主动探针也是渠道可见面：后端收 7 家，picker 不能只给 5 个。"""
    matrix = cc.audit_all()
    for p in ALL:
        cell = matrix[p]["visible"]
        assert cell.state == cc.Y, (p, cell)
        assert "主动探针" in cell.detail, (p, cell.detail)
    # 负控：picker 缺一款 App 时 helper 必须报出来
    ok, detail = cc._probe_picker_covers(
        '<div id="srxPlatPick"><label data-p="ctrip"></label></div>',
        ("ctrip", "app_qunar"))
    assert not ok and "app_qunar" in detail, (ok, detail)


def test_strict_mode_fails_on_gap(monkeypatch, capsys):
    """CLI 的 --strict 必须把缺口变成非零退出码（发版前可串进流程）。"""
    monkeypatch.setattr(sys, "argv", ["channel_contract", "--strict"])
    monkeypatch.setattr(cc, "gaps", lambda *a, **k: [("ctrip", "visible", "x")])
    assert cc.main() == 1
    out = capsys.readouterr().out
    assert "缺口 1 处" in out or "[可配置] ctrip" in out, out


# ---- merged from tests/test_r996_channel_surface_census.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)




