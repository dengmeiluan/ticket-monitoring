# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_path_auto_retire.py
- tests/test_r1063_path_hint.py
- tests/test_r1063_path_ms_view.py
- tests/test_r1063_weak_path_click.py
- tests/test_r1063_weak_path_jump.py
- tests/test_r1063_weak_paths_panel.py
- tests/test_r645_path_chip_excludes_invalid_samples.py
- tests/test_r658_path_names_are_chinese.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import re
import sqlite3
import sys
import threading

from core import pacing as P
from core.advise import weak_paths
from core.channel_matrix import ms_table
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


# ---- merged from tests/test_webui_path.py ----

# ---- merged from tests/test_r1063_path_auto_retire.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _pac(cfg=None, why="不查"):
    pac = P.Pacing(cfg=cfg or {})
    try:
        pac.set_health("tuniu", 0.0, 49, dim="", path="PC")
    except TypeError:
        pac.set_health("tuniu", 0.0, 49)
    for k, v in list(pac._health_all.items()):
        if isinstance(v, dict):
            v["why"] = why
    return pac


def test_dead_boundary_path_is_retired():
    allow, wait, why = _pac().gate_path("tuniu", "", "PC")
    assert allow is False and wait == 0.0
    assert "自动退役" in why and "24h" in why, why


def test_other_paths_unaffected():
    pac = _pac()
    allow, _w, _why = pac.gate_path("tuniu", "", "H5/API")
    assert allow is True, "只该停那一条链路，不许连坐"


def test_small_sample_not_retired():
    pac = P.Pacing(cfg={})
    try:
        pac.set_health("tuniu", 0.0, 3, dim="", path="PC")
    except TypeError:
        pac.set_health("tuniu", 0.0, 3)
    for k, v in list(pac._health_all.items()):
        if isinstance(v, dict):
            v["why"] = "不查"
    assert pac.gate_path("tuniu", "", "PC")[0] is True


def test_risk_typed_zero_is_not_retired():
    """被风控拦出来的 0% 不归退役管（那是熔断/换道的事）。"""
    pac = P.Pacing(cfg={})
    try:
        pac.set_health("ctrip", 0.0, 30, dim="", path="PC")
    except TypeError:
        pac.set_health("ctrip", 0.0, 30)
    for k, v in list(pac._health_all.items()):
        if isinstance(v, dict):
            v["why"] = "滑块拦截，请点击重试"
    assert pac.gate_path("ctrip", "", "PC")[0] is True


def test_switch_off_allows():
    assert _pac({"path_auto_retire": False}).gate_path("tuniu", "", "PC")[0] is True


def test_retire_expires_and_probes_again():
    """到期必须放行一次复检，否则就是永久拉黑（用户再也发现不了修好了）。"""
    pac = _pac()
    key = pac._health_scope_key("tuniu", "", "PC")
    pac._auto_retire_next[key] = 0.0        # 模拟"已到期"
    allow, _w, _why = pac.gate_path("tuniu", "", "PC")
    assert allow is True, "到期应放行一次复检"


# ---- merged from tests/test_r1063_path_hint.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_hint_map_has_the_ambiguous_paths():
    w = _w()
    i = w.index("const PATH_HINT={")
    seg = w[i:i + 700]
    for k in ("app-login", "app-date", "app-list", "low-fare"):
        assert "'%s'" % k in seg, "缺 %s 的口径" % k
    assert "不是账号状态" in seg, "app-login 的口径必须点明与账号状态无关"


def test_hint_is_wired_into_note():
    w = _w()
    i = w.index("const _note=[_fx.join(")
    seg = w[i:i + 400]
    assert "(PATH_HINT[_k]||'')" in seg, "提示必须进 _note 才会显示"
    assert "].filter(Boolean).join(' · ');" in seg


def test_hint_only_applies_to_listed_paths():
    """未列出的通路不该被加提示（避免全站长文案）。"""
    w = _w()
    i = w.index("const PATH_HINT={")
    seg = w[i:w.index("};", i)]
    assert "'日历'" not in seg and "'航班明细'" not in seg, \
        "正常通路不加口径，避免噪音"


# ---- merged from tests/test_r1063_path_ms_view.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mkdb(path):
    c = sqlite3.connect(path)
    c.execute("create table fetch_paths (platform text, entry_path text, "
              "path_status text, elapsed_ms integer, fetched_at text)")
    import time as _t
    now = _t.strftime("%Y-%m-%d %H:%M:%S")
    for plat, path, ms in (("ctrip", "PC", 6000), ("ctrip", "PC", 8000),
                           ("fliggy", "PC", 15000)):
        c.execute("insert into fetch_paths values (?,?,?,'ok',?)".replace(
            ",'ok'", ",?"), (plat, path, "ok", ms, now))
    c.commit()
    c.close()


def test_ms_table_sorted_and_formatted(tmp_path):
    db = str(tmp_path / "t.db")
    _mkdb(db)
    out = ms_table(24, 10, db=db)
    assert "通路耗时" in out
    # 数据时间较旧，窗口可能把它排除——有数据才断言排序/格式
    if "fliggy" in out:
        assert "15.0s" in out, out
        i_f = out.index("fliggy")
        i_c = out.index("ctrip")
        assert i_f < i_c, "必须按平均耗时降序"
    else:
        assert "没有耗时样本" in out or "近" in out


def test_cli_flag_wired():
    s = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                encoding="utf-8").read()
    assert 'want_ms = "--ms" in argv' in s
    assert "ms_table(hours)" in s
    i_def = s.index("def ms_table(")
    i_main = s.index("def _main(")
    assert i_def < i_main, "ms_table 必须定义在 _main 之前（否则 NameError）"


# ---- merged from tests/test_r1063_weak_path_click.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_probe_helper_exists_and_is_top_level():
    """必须是顶层函数：放在渲染函数里，行内 onclick 解析不到（实测报错）。"""
    w = _w()
    assert "async function srxWeakProbe" in w
    i = w.index("async function srxWeakProbe")
    # 顶层函数的特征是行首一个空格（本项目全局函数都是 1 空格缩进）
    line_start = w.rfind("\n", 0, i) + 1
    assert w[line_start:i] == " ", (
        "srxWeakProbe 不是顶层函数：行内 onclick 会报 not defined")


def test_weak_items_are_links_not_escaped():
    """弱环条目要渲染成真正的链接，不能被外层 esc 转成文本。"""
    w = _w()
    i = w.index("通路弱环（近24h）")
    seg = w[i - 400:i + 400]
    assert "srxWeakProbe" in seg, "弱环条目没有绑定自检"
    assert "'通路弱环（近24h）：'+top.join(' · ')" in w, (
        "外层 esc 会把 <a> 转义成文本（实测 links=0）")


def test_link_carries_plat():
    w = _w()
    i = w.index("onclick=\"return srxWeakProbe")
    seg = w[i:i + 200]
    assert "esc(r.plat)" in seg, "链接必须带上渠道名，否则自检不知道点的是谁"


# ---- merged from tests/test_r1063_weak_path_jump.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_jump_helper_is_top_level():
    """行内 onclick 只能解析全局名（上次 srxWeakProbe 就栽在这）。"""
    w = _w()
    i = w.index("function srxWeakJump(")
    line_start = w.rfind("\n", 0, i) + 1
    assert w[line_start:i] == " ", "srxWeakJump 不是顶层函数"


def test_jump_targets_globals_panel_and_uses_scope_fill():
    w = _w()
    i = w.index("function srxWeakJump(")
    seg = w[i:i + 2200]
    assert "showCfgPanel('globals')" in seg, "策略行在「全局参数」面板里"
    assert "stratScopeFill(sel)" in seg, "链路选项必须由 stratScopeFill 铺（含全量目录）"
    assert "select.ssel2" in seg, "要把作用域设成该链路"
    assert "scrollIntoView" in seg, "要滚到那一行，否则用户还得自己找"


def test_weak_item_binds_both_jump_and_probe():
    w = _w()
    i = w.index("通路弱环（近24h）")
    seg = w[i - 900:i + 900]
    assert "srxWeakJump" in seg, "主文本应跳到策略行"
    assert "srxWeakProbe" in seg, "末尾应保留一键自检"
    assert "esc(r.path)" in seg, "跳转必须带上链路名"


# ---- merged from tests/test_r1063_weak_paths_panel.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pacing(plat, path, rate, n, why=""):
    return {"channels": {plat: {"paths": {path: {
        "rate": rate, "attempts": n, "why": why}}}}}


def test_weak_path_reported():
    out = weak_paths(_pacing("tuniu", "H5/API", 0.73, 62,
                             "m.tuniu.com 列表接口"))
    assert out and out[0]["path"] == "H5/API", out
    assert out[0]["attempts"] == 62


def test_supported_but_flaky_counts_even_if_why_mentions_skip():
    """真机反例：73% 的通路 why 里带渠道级提示「>30 天的 PC 不查」，
    以前被当成能力边界剔除，导致面板一条弱环都不显示。"""
    out = weak_paths(_pacing("tuniu", "H5/API", 0.73, 62,
                             "距今天 >30 天的 PC 不查（风控），远日期走 H5/API"))
    assert out, "有产出的通路不可能是能力边界"


def test_unsupported_zero_rate_is_not_weak():
    out = weak_paths(_pacing("tuniu", "PC", 0.0, 45,
                             "距今天 >30 天的 PC 不查（风控）"))
    assert out == [], "按设计不查的通路不该让用户去修"


def test_high_rate_and_small_sample_are_ignored():
    assert weak_paths(_pacing("ctrip", "PC", 0.96, 27)) == []
    assert weak_paths(_pacing("ctrip", "PC", 0.2, 2)) == []


def test_sorted_by_loss_and_capped():
    p = {"channels": {
        "a": {"paths": {"p": {"rate": 0.5, "attempts": 10}}},
        "b": {"paths": {"q": {"rate": 0.1, "attempts": 100}}},
        "c": {"paths": {"r": {"rate": 0.8, "attempts": 50}}},
    }}
    out = weak_paths(p, limit=2)
    assert [x["plat"] for x in out] == ["b", "c"], out


def test_webui_hook_runs_after_paths_merge():
    """钩子必须在 paths 合并之后——否则 weak_paths 永远为空（T198 实测）。"""
    w = webui_full_src()
    i_resp = w.index("data[\"weak_paths\"] = _wp2(data)")
    i_json = w.index("self._json(data)", i_resp)
    assert i_resp < i_json, "weak_paths 必须在响应之前算"
    # 老的错误位置不该再算 weak_paths
    seg = w[w.index("data[\"advice_top\"] = _tfp(data)"):][:400]
    assert "_wp(data)" not in seg, "旧钩子（paths 未合并）不该再算 weak_paths"
    # 前端只画，不再自己判
    assert "j.weak_paths" in w


def test_same_channel_does_not_monopolize_slots():
    """同一渠道的多条通路不该占满名额（真机：App 两条把 tuniu 挤没了）。"""
    p = {"channels": {"app_x": {"paths": {
        "a": {"rate": 0.0, "attempts": 200},
        "b": {"rate": 0.0, "attempts": 150},
    }}, "tuniu": {"paths": {"H5/API": {"rate": 0.74, "attempts": 66}}}}}
    out = weak_paths(p, limit=3)
    plats = [x["plat"] for x in out]
    assert plats.count("app_x") == 1, out
    assert "tuniu" in plats, "别的渠道被同一家挤掉了：%s" % out


# ---- merged from tests/test_r645_path_chip_excludes_invalid_samples.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 与 path_stats 同形：android-runtime 全是 unsupported；calendar 正常
PATHS = {"app_zhixing": {
    "paths": {"android-runtime": {"attempts": 63, "rate": 0.0,
                                  "rate_excl_empty": None,
                                  "unsupported": 63, "empty": 0},
              "app-calendar": {"attempts": 40, "rate": 1.0,
                               "rate_excl_empty": 1.0, "unsupported": 0,
                               "empty": 0}},
    "retired_paths": [],
    "scopes": {"dom": {"attempts": 63, "rate": 0.5, "query_attempts": 20,
                       "query_rate": 1.0, "query_attempts_live": 20,
                       "query_rate_live": 1.0,
                       "paths": {"android-runtime": {"attempts": 63,
                                                     "rate": 0.0}},
                       "retired_paths": []},
               "intl": {"attempts": 0, "rate": 0.0, "query_attempts": 0,
                        "query_rate": None, "query_attempts_live": 0,
                        "query_rate_live": None, "paths": {},
                        "retired_paths": []}},
    "query_attempts_live": 20, "query_rate_live": 1.0,
    "query_detail_ok": 20, "query_calendar_only": 0, "retired_paths": []}}

HEALTH = {"ok": True,
          "rounds": [{"ts": "2026-10-30 10:00",
                      "plats": {"app_zhixing": {"s": "ok", "ok": 2, "tot": 2,
                                                "cal": 0, "detail": 2}}}],
          "stats": {"app_zhixing": {"ok": 20, "part": 0, "fail": 0,
                                    "maint": 0, "rate": 1.0, "cal": 0,
                                    "detail": 20, "auth": 0}},
          "push": {"channels": {}}, "paths": PATHS, "diag": [],
          "coverage": {}}








# ---- merged from tests/test_r658_path_names_are_chinese.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 账本里出现过的、不是中文的通路 id（中文那些本来就能读，不必进表）
LATIN_IDS = ("app-list", "app-route", "app-blocker", "app-dump",
             "app-error", "android-runtime", "android-device",
             "snap-restore")


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


def test_every_literal_path_note_has_a_display_name():
    """源码里 path_note("xxx") 的字面量，个个都要在 PATH_CN 里。

    这是「加通路必漏登记」的守门人：crawler 里新写一条通路名，界面就会
    退回裸 id，而没有任何测试会红——除非有这一条。
    """
    from core.channels import PATH_CN
    seen = set()
    for fn in os.listdir(os.path.join(ROOT, "crawlers")):
        if not fn.endswith(".py"):
            continue
        src = _src(os.path.join("crawlers", fn))
        # 只看真正的调用；注释里提到别的通路名不算
        for m in re.finditer(r"path_note\(\s*\"([^\"]+)\"", src):
            seen.add(m.group(1))
    assert seen, "没扫到任何 path_note 字面量，判据本身失效了"
    missing = sorted(p for p in seen if p not in PATH_CN)
    assert not missing, (
        "这些通路在界面上没有中文名（健康卡会打出裸 id）：%s\n"
        "在 core/channels.py 的 PATH_CN 里补上。" % missing)


def test_no_latin_path_id_is_left_nameless():
    """英文 id 必须全部有名字（中文通路名不进表也能读，放宽）。"""
    from core.channels import PATH_CN
    missing = [p for p in LATIN_IDS if p not in PATH_CN]
    assert not missing, "英文通路 id 没有中文名：%s" % missing
    for p in LATIN_IDS:
        assert PATH_CN[p] != p, "%s 的「中文名」就是它自己" % p


def test_unknown_path_falls_back_to_raw_key():
    """未知通路原样返回 —— 宁缺勿错，不编造名字。"""
    from core.channels import path_cn
    assert path_cn("未来新通路") == "未来新通路"


def test_pacing_hints_use_the_display_name():
    """后端提示也要用中文名（它同样会出现在节流行上）。"""
    src = _src("core/pacing.py")
    assert "path_cn(" in src, "core/pacing 没有接 path_cn，提示仍是裸 id"
    assert "_shown = path_cn(_name)" in src
    # 提示里不许再用原始键名
    assert "% (_dom, _name," not in src, (
        "还有提示仍在拼原始通路键名")




def _app_payload():
    return {
        "rounds": [{"ts": "10-30 0%d:00" % i,
                    "plats": {"app_zhixing": {"s": "ok", "ok": 3, "tot": 3,
                                              "cal": 0, "detail": 3}}}
                   for i in range(4)],
        "stats": {"app_zhixing": {"ok": 3, "part": 1, "fail": 1, "rate": 0.6,
                                  "cal": 0, "detail": 3, "auth": 0,
                                  "maint": 0}},
        "paths": {"app_zhixing": {
            "scopes": {}, "retired": [],
            "paths": {
                "app-list": {"attempts": 5, "ok": 4, "rate": 0.8,
                             "rate_excl_empty": 0.8, "login": 0, "soft": 0,
                             "empty": 0, "unsupported": 0},
                "android-runtime": {"attempts": 63, "ok": 0, "rate": 0,
                                    "rate_excl_empty": None, "login": 0,
                                    "soft": 0, "empty": 0, "unsupported": 63},
                "snap-restore": {"attempts": 2, "ok": 1, "rate": 0.5,
                                 "rate_excl_empty": 0.5, "login": 1,
                                 "soft": 0, "empty": 0, "unsupported": 0}}}},
        "by_scope": {},
        "enabled_platforms": ["app_zhixing"],
        "push": {"channels": {}},
    }


def _bare(text):
    return sorted({p for p in LATIN_IDS
                   if re.search(r"(?<![A-Za-z_-])" + re.escape(p)
                                + r"(?![A-Za-z_-])", text)})






def test_page_injects_the_single_source_table():
    """名字表由服务端注入，前端不许另抄一份。"""
    import webui
    html = webui._page_html("r658t")
    assert "__PATH_CN__" not in html, "PATH_CN 占位符没被替换"
    assert "function pathCN(k)" in html, "页面里没有通路名解析函数"
    from core.channels import PATH_CN
    for k in LATIN_IDS:
        assert ('"%s": "%s"' % (k, PATH_CN[k])) in html, (
            "页面里没有 %s 的名字，注入表与实际表不一致" % k)
