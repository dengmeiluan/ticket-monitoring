# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_all_dual_login.py
- tests/test_r1063_clear_wall_api.py
- tests/test_r1063_dual_lane_order.py
- tests/test_r1063_dual_surface_profiles.py
- tests/test_r1063_h5_slot_detail.py
- tests/test_r1063_login_clears_wall.py
- tests/test_r1063_login_dual_surface.py
- tests/test_r1063_login_entry_and_rotate.py
- tests/test_r1063_login_entry_url.py
- tests/test_r1063_login_reprobe.py
- tests/test_r1063_login_requests_interrupt.py
- tests/test_r1063_login_save_from_profile.py
- tests/test_r1063_login_wall_autonote.py
- tests/test_r1063_login_window_size.py
- tests/test_r1063_login_yield.py
- tests/test_r1063_relogin_notice.py
- tests/test_r1063_vendor_login_clears.py
- tests/test_r1063_verify_url_heuristic.py
- tests/test_r1161_login_finish_accepts_stale.py
- tests/test_r1339_login_wait_and_slow_api.py
- tests/test_r290_login_stale.py
- tests/test_r291_login_refresh.py
- tests/test_r338_login_state.py
- tests/test_r412_login_rows_alignment.py
- tests/test_r620_login_reports_only_real_window.py
- tests/test_r676_login_verify_is_real_probe.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import logging
import os
import pytest
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webui

from core.android import align, identity, login_api as LA, rotate
from core.channel_links import LOGIN_ENTRY, login_entry_url
from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER, slot_profile
from crawlers import base as _base
from crawlers.app_ctrip import AppCtripCrawler
from crawlers.base import BaseCrawler
from crawlers.challenge import classify_text


# ---- merged from tests/test_webui_login.py ----

# ---- merged from tests/test_r1063_all_dual_login.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_all_vendors_are_dual_in_the_card_table():
    """四家浏览器渠道的卡片都必须**双端**（PC + H5），且不再写死槽位表。

    r1174 之后口径变了：槽位列表从后端 `slot_order` 派生（`_slotsFor`），
    以前那张 `slots:[by.X,by.X_h5]` 的硬编码表已经删掉——因为后端加了
    `qunar_h5` 时页面少渲染一格（实测 10 格只出 9 格）。所以这里断言
    **机制**而不是字面量：每家都用派生函数，且派生源是后端下发的顺序。
    """
    w = _w()
    for vendor in ("ctrip", "tongcheng", "tuniu", "fliggy"):
        assert "slots:_slotsFor('%s')" % vendor in w, \
            "%s 的卡片没走派生槽位（用户明确要求四家都双端）" % vendor
    # 派生函数必须按后端顺序 + 兼容 plat/slot 两种匹配
    i = w.index("function _slotsFor(v){")
    seg = w[i:i + 240]
    assert "(order||[])" in seg, "派生源不是后端下发的槽位顺序"
    assert "s.plat===v||s.slot===v" in seg, "派生函数没有同时匹配 plat 与 slot"
    # 顺序必须来自接口，不许前端另写一份
    j = w.index("const order=(j&&j.slot_order")
    assert "slot_order" in w[j:j + 160], "order 没有取自后端 slot_order"


def test_dual_modal_is_generic():
    """双端弹窗不许再写死飞猪：要有 LG_DUAL 表与 lgOpenDual(plat)。"""
    w = _w()
    assert "const LG_DUAL={" in w
    assert "function lgOpenDual(plat){" in w
    assert "function lgFliggyModalHTML(){return lgDualModalHTML('fliggy')}" in w
    # 卡片按钮按渠道传参，而不是固定开飞猪
    assert "lgOpenDual('${he(p)}')" in w


def test_h5_slots_report_their_own_state():
    """独立端槽位必须按自己的 profile 算状态（否则假可用）。"""
    w = _w()
    i = w.index("for key in LOGIN_SLOT_ORDER:")
    seg = w[i:i + 900]
    assert 'if key != meta.get("plat"):' in seg, \
        "只有 fliggy_h5 走独立分支的话，其余 _h5 会抄渠道状态（假可用）"


def test_inheritance_is_opt_in():
    src = io.open(os.path.join(ROOT, "core", "login_slots.py"),
                  encoding="utf-8").read()
    assert "login_inherit_pc_session" in src
    i = src.index("login_inherit_pc_session")
    seg = src[max(0, i - 300):i + 300]
    assert "False" in seg, "继承必须默认关闭"


# ---- merged from tests/test_r1063_clear_wall_api.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def _handler_slice(src: str, path: str) -> str:
    """取某个 API handler 的正文（到下一个 elif self.path 为止）。"""
    anchor = 'elif self.path == "%s":' % path
    i = src.index(anchor)
    j = src.find("elif self.path == ", i + len(anchor))
    return src[i:j if j > 0 else i + 4000]


def test_endpoint_exists_and_returns_shape():
    src = _w()
    seg = _handler_slice(src, "/api/channel/clear-wall")
    assert "_clear_login_wall_memo" in seg
    assert '"cleared"' in seg
    assert "下一轮" in seg, "应告诉用户下一步"


def test_reset_app_reuses_the_same_helper():
    src = _w()
    seg = _handler_slice(src, "/api/channel/reset-app")
    assert "_clear_login_wall_memo" in seg, seg[-500:]


def test_clear_wall_is_non_destructive():
    src = _w()
    seg = _handler_slice(src, "/api/channel/clear-wall")
    for bad in ("pm clear", "rm -rf", "shutil.rmtree"):
        assert bad not in seg, "clear-wall 不该做破坏性操作：%s" % bad


# ---- merged from tests/test_r1063_dual_lane_order.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_pc_lane_listed_before_h5_for_all_dual_channels():
    w = _w()
    i = w.index("const LG_DUAL={")
    seg = w[i:w.index("};", i)]
    for plat in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        m = re.search(r"%s:\{[^}]*\}" % plat, seg)
        assert m, "LG_DUAL 缺 %s" % plat
        block = m.group(0)
        ipc = block.find("pc:")
        ih5 = block.find("h5:")
        assert ipc >= 0 and ih5 >= 0, "%s 必须同时有 pc/h5" % plat
        assert ipc < ih5, "%s 的 PC lane 必须排在 H5 之前" % plat


def test_dual_modal_title_says_two_sides():
    w = _w()
    i = w.index("const LG_DUAL={")
    seg = w[i:w.index("};", i)]
    assert seg.count("双端登录") >= 4, "四家的标题都要写清「双端」"
    assert "会话不共享" in seg, "要说明两端会话不共享（否则用户以为登录一次就够）"


# ---- merged from tests/test_r1063_dual_surface_profiles.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_vendor_has_pc_and_h5():
    vendors = {"ctrip", "fliggy", "tongcheng", "tuniu"}
    for v in vendors:
        assert v in LOGIN_SLOTS, "%s 缺 PC 槽位" % v
        assert "%s_h5" % v in LOGIN_SLOTS, "%s 缺 H5 槽位（双端登录）" % v


def test_slot_profiles_are_distinct():
    assert slot_profile("tuniu") == "tuniu"
    assert slot_profile("tuniu_h5") == "tuniu_h5"
    assert slot_profile("ctrip_h5") == "ctrip_h5"
    # 同一厂商两端必须不同 profile，否则又是"一份 cookie 两个标签"
    for v in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        assert slot_profile(v) != slot_profile("%s_h5" % v)


def test_slot_crawler_uses_h5_profile_and_optin_inherit(tmp_path, monkeypatch):
    """r1063 T178：**继承改成配置开关，默认关**。

    为什么关：继承来的只是 PC 域 cookie，H5 域并未登录，却让槽位显示
    「会话有效·明细可用」——假可用，且与"两端要分别登录"直接矛盾。
    """
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "tuniu"
    d.mkdir(parents=True, exist_ok=True)
    (d / "session-state.json").write_text(json.dumps({"cookies": []}),
                                         encoding="utf-8")

    from core.login_slots import slot_crawler
    import logging
    cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    c = slot_crawler("tuniu_h5", cfg, logging.getLogger("t"))
    assert os.path.basename(c.user_data_dir) == "tuniu_h5"
    # 默认**不继承**：H5 端要自己登，否则就是"假可用"
    assert not (tmp_path / "tuniu_h5" / "session-state.json").is_file()
    # 显式打开开关才继承（给"我就想复用 PC 会话"的人留口子）
    c2 = slot_crawler("tuniu_h5",
                      dict(cfg, web={"login_inherit_pc_session": True}),
                      logging.getLogger("t"))
    assert os.path.basename(c2.user_data_dir) == "tuniu_h5"
    assert (tmp_path / "tuniu_h5" / "session-state.json").is_file()


def test_split_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core.login_slots import slot_crawler
    import logging
    c = slot_crawler("tuniu_h5",
                     {"crawler": {"user_data_dir": str(tmp_path)},
                      "web": {"login_split_profiles": False}},
                     logging.getLogger("t"))
    assert (c.profile_name or "") in ("", "tuniu"), \
        "关闭开关后应退回共享 profile"


def test_using_surface_switches_and_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    (tmp_path / "tuniu_h5").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tuniu_h5" / "session-state.json").write_text("{}",
                                                             encoding="utf-8")
    from crawlers import REGISTRY
    import logging
    c = REGISTRY["tuniu"]({"crawler": {"user_data_dir": str(tmp_path)}},
                          logging.getLogger("t"))
    before = c.session_state_path
    with c.using_surface("h5"):
        inside = c.session_state_path
    after = c.session_state_path
    assert "tuniu_h5" in inside and "tuniu_h5" not in before
    assert after == before, "退出上下文必须恢复原 profile"


def test_using_surface_without_h5_session_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from crawlers import REGISTRY
    import logging
    c = REGISTRY["tuniu"]({"crawler": {"user_data_dir": str(tmp_path)}},
                          logging.getLogger("t"))
    before = c.session_state_path
    with c.using_surface("h5"):
        assert c.session_state_path == before


def test_tuniu_intl_uses_h5_surface():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("def _fetch_intl(")
    seg = src[i:i + 2500]
    assert 'using_surface("h5")' in seg, "途牛国际（H5 面）必须用 H5 槽位会话"


# ---- merged from tests/test_r1063_h5_slot_detail.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

F = webui._surface_detail_ok


def test_h5_rows_with_ok_count_as_detail_ok():
    rows = [{"entry_path": "H5/API", "path_status": "ok", "rows": 12}]
    assert F(rows, "h5") is True


def test_pc_rows_do_not_make_h5_available():
    rows = [{"entry_path": "PC", "path_status": "ok", "rows": 99}]
    assert F(rows, "h5") is False, "PC 出数不能冒充 H5 出数"
    assert F(rows, "PC") is True


def test_timeout_rows_do_not_count():
    rows = [{"entry_path": "H5", "path_status": "timeout", "rows": 0}]
    assert F(rows, "h5") is False


def test_unsupported_rows_do_not_count():
    rows = [{"entry_path": "H5", "path_status": "unsupported", "rows": 0}]
    assert F(rows, "h5") is False, "能力边界不能算明细可用"


def test_unknown_surface_is_false():
    assert F([{"entry_path": "H5", "path_status": "ok"}], "") is False


def test_status_elevation_source_contract():
    """detail_ok 必须能抬 status，但不能盖掉被拦。"""
    w = webui_full_src()
    i = w.index("detail_ok 抬成 available")
    seg = w[i:i + 700]
    cond = 'if detail_ok and status in ("saved", "pending", "page_ok")'
    assert cond in seg, seg[:200]
    assert 'status = "available"' in seg
    # 条件里（代码行，不含注释）不得出现 challenge/login_required
    assert "challenge" not in cond and "login_required" not in cond


# ---- merged from tests/test_r1063_login_clears_wall.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn():
    import webui
    return webui._clear_login_wall_memo


def test_clears_app_login_wall_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "app_ctrip"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "login_wall.json"
    f.write_text(json.dumps({"until": 9e9, "detail": "该日被要求登录"}),
                 encoding="utf-8")
    cleared = _fn()("app_ctrip")
    assert not f.exists(), "登录墙文件没被清掉"
    assert any("app_ctrip" in c for c in cleared), cleared


def test_clears_service_state_memo(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import service_state as ss
    ss.mark(str(tmp_path), "app_fliggy", "login_wall", "需登录", window_s=600)
    assert ss.until(str(tmp_path), "app_fliggy", "login_wall") > 0
    cleared = _fn()("app_fliggy")
    assert ss.until(str(tmp_path), "app_fliggy", "login_wall") == 0
    # 注意：service_state 的 memo 就是同一个 login_wall.json（两层实为一层），
    # 所以这里只要求"清单里提到该渠道"，不纠结是文件还是 memo。
    assert any("app_fliggy" in c for c in cleared), cleared


def test_noop_when_nothing_to_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    assert _fn()("ctrip") == []


def test_wired_into_login_success_path():
    src = webui_full_src()
    i = src.index("干预入账失败")
    seg = src[i:i + 900]
    assert "_clear_login_wall_memo" in seg, seg[:300]


# ---- merged from tests/test_r1063_login_dual_surface.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUAL = ("ctrip", "fliggy", "tongcheng", "tuniu")


def test_every_browser_channel_has_both_surfaces():
    for plat in DUAL:
        assert plat in LOGIN_SLOT_ORDER, plat
        assert plat + "_h5" in LOGIN_SLOT_ORDER, plat
        pc, h5 = LOGIN_SLOTS[plat], LOGIN_SLOTS[plat + "_h5"]
        assert pc["surface"] == "pc" and h5["surface"] == "h5"
        assert pc["mobile"] is False and h5["mobile"] is True
        # 两端各自的 profile 不同（域不同、cookie 不共享）
        assert pc["profile"] != h5["profile"], plat


def test_pc_slots_never_point_at_mobile_hosts():
    """PC 端弹 H5 地址是这次要修的问题本身。"""
    for key in LOGIN_SLOT_ORDER:
        m = LOGIN_SLOTS[key]
        if (m.get("surface") or "pc") != "pc":
            continue
        url = str(m.get("login_url") or "")
        assert "://m." not in url and "://touch." not in url, (key, url)


def test_h5_slots_are_mobile_hosts():
    for key in LOGIN_SLOT_ORDER:
        m = LOGIN_SLOTS[key]
        if m.get("surface") != "h5":
            continue
        url = str(m.get("login_url") or "")
        assert ("://m." in url) or ("m.taobao.com" in url), (key, url)


def test_login_entry_matches_the_slot_url_per_surface():
    """登录入口与槽位 URL 的**分工**（不是要求处处相等）。

    * 槽位 URL ＝ 用户点「弹窗登录」后要看到的那一页，必须是**能登录的表单**；
    * `login_entry_url()` ＝ 接管/查看窗口打开的地址，可以是该端**业务页**
      （例如途牛 PC 用 `flight.tuniu.com`）。
    途牛是唯一两者不同的一家（T70 用户要求 PC 页；而 PC 页没有登录控件，
    所以槽位仍用 passport）。其余各家两边一致。
    """
    for key in LOGIN_SLOT_ORDER:
        m = LOGIN_SLOTS[key]
        surface = m.get("surface") or "pc"
        got = login_entry_url(m["plat"], surface)
        if m["plat"] == "tuniu" and surface == "pc":
            assert got == "https://flight.tuniu.com/", got
            assert "passport.tuniu.com" in m["login_url"], m["login_url"]
            continue
        assert got == m["login_url"], (key, got, m["login_url"])


def test_qunar_slot_declares_service_closed():
    """去哪儿网页版已正式停服——界面要把事实说清，而不是让人去登一个死站。"""
    q = LOGIN_SLOTS["qunar"]
    assert q.get("service_closed") is True
    assert "停服" in q["surface_label"]


def test_slot_order_lists_pc_before_h5_for_each_channel():
    order = list(LOGIN_SLOT_ORDER)
    for plat in DUAL:
        assert order.index(plat) < order.index(plat + "_h5"), plat


def test_ui_renders_from_the_shared_order():
    """登录卡必须从这张表渲染（否则新增槽位在界面上不出现）。"""
    src = webui_full_src()
    assert "for key in LOGIN_SLOT_ORDER:" in src


# ---- merged from tests/test_r1063_login_entry_and_rotate.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_channel_has_a_login_entry():
    """五家浏览器渠道都必须给得出登录入口（否则弹窗只能退到"查看详情"深链）。"""
    for plat in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        got = login_entry_url(plat, "pc")
        assert got.startswith("https://"), (plat, got)


def test_pc_entry_is_never_a_mobile_host():
    """PC 登录不能弹移动域（用户实测途牛被弹成 m.tuniu.com）。"""
    for plat in ("ctrip", "qunar", "tongcheng", "tuniu"):
        got = login_entry_url(plat, "pc")
        assert "://m." not in got, (plat, got)
        assert "://touch." not in got, (plat, got)


def test_tuniu_and_fliggy_split_by_surface():
    assert login_entry_url("tuniu", "pc") == "https://flight.tuniu.com/"
    assert login_entry_url("tuniu", "h5").startswith("https://m.tuniu.com/")
    assert "m.taobao.com" in login_entry_url("fliggy", "h5")
    assert "m.taobao.com" not in login_entry_url("fliggy", "pc")


def test_login_entry_matches_the_login_slots():
    """入口与登录槽位同源：槽位登记的 URL 必须能被入口取到（不许两套口径）。"""
    for key, meta in LOGIN_SLOTS.items():
        plat = meta.get("plat")
        got = login_entry_url(plat, meta.get("surface") or "pc")
        assert got, key
        if not meta.get("surface"):
            assert got == meta["login_url"], (key, got)


def test_no_graphical_env_is_honest_per_platform(monkeypatch):
    import sys

    import webui

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("TM_FORCE_GUI", raising=False)
    # conftest 的 autouse 桩默认按「有图形环境」跑；本用例验真实平台判据。
    # 桩只在 webui 已加载时保存真身（_real_* 别名）——xdist 下本用例可能是
    # worker 进程内首个触碰 webui 的测试，届时未打桩也没有别名，
    # 模块当前的 _no_graphical_env 就是真身。
    # 真身从源码 AST 取回并 exec（CI 实录：模块属性链上的 ORIG 别名在
    # 极端收集时序下缺失、取到的是 conftest 桩——源码级求值免疫一切桩）。
    import ast as _ast
    _src = open("webui.py", encoding="utf-8").read()
    _fn = next(n for n in _ast.parse(_src).body
               if isinstance(n, _ast.FunctionDef) and n.name == "_no_graphical_env")
    _ns = {"os": os, "sys": sys}
    exec(_ast.get_source_segment(_src, _fn), _ns)
    monkeypatch.setattr(webui, "_no_graphical_env", _ns["_no_graphical_env"])
    # 平台期望：Linux 无 DISPLAY=无头；macOS/Windows 没有 DISPLAY 也是
    # **有**图形环境（#14 的根因）。失败时带环境快照，CI-only 红可一次定位。
    expected = sys.platform.startswith("linux")
    assert webui._no_graphical_env() is expected, (
        "无头判定不诚实：platform=%s DISPLAY=%r WAYLAND_DISPLAY=%r "
        "TM_FORCE_GUI=%r fn=%r → %r（期望 %r）"
        % (sys.platform, os.environ.get("DISPLAY"),
           os.environ.get("WAYLAND_DISPLAY"),
           os.environ.get("TM_FORCE_GUI"),
           getattr(webui, "_NO_GRAPHICAL_ORIG", "缺"),
           webui._no_graphical_env(), expected))
    monkeypatch.setenv("TM_FORCE_GUI", "1")
    assert webui._no_graphical_env() is False


def test_cli_login_fallback_spawns_the_documented_command(monkeypatch):
    """进程内开不出窗口时，必须退回 `--login <plat>`（终端里那条命令）。"""
    import webui

    seen = {}

    class _P:
        def __init__(self, *a, **kw):
            seen["cmd"] = a[0] if a else (kw.get("args") or [])

    monkeypatch.setattr("subprocess.Popen", _P)
    ok, detail = webui._spawn_cli_login("ctrip")
    assert ok is True, detail
    cmd = " ".join(str(x) for x in seen["cmd"])
    assert "--login" in cmd and "ctrip" in cmd, cmd


def test_cli_login_fallback_reports_failure(monkeypatch):
    import webui

    def _boom(*a, **kw):
        raise OSError("nope")

    monkeypatch.setattr("subprocess.Popen", _boom)
    ok, detail = webui._spawn_cli_login("ctrip")
    assert ok is False and "nope" in detail


def test_rotate_plan_is_honest_and_apply_is_opt_in():
    from core.android import rotate

    plan = rotate.plan("user_data")
    assert "identity_file" in plan and plan["steps"]
    assert any("登录态" in x for x in plan["keeps"]), plan
    rep = rotate.rotate("user_data", ["app_ctrip"], apply=False)
    assert rep["ok"] and rep["applied"] is False


def test_rotate_backs_up_and_drops_identity(monkeypatch, tmp_path):
    from core.android import rotate

    ident = tmp_path / "device" / "device_identity.json"
    ident.parent.mkdir(parents=True, exist_ok=True)
    ident.write_text('{"brand": "X"}', encoding="utf-8")

    class _Store:
        path = str(ident)

        def drop(self, vm=0):
            # 真实签名 `drop(vm: int)`：身份按实例索引分槽存
            os.remove(self.path)
            return True

    monkeypatch.setattr(rotate, "_store", lambda *a, **k: _Store())
    monkeypatch.setattr(rotate, "_pkg_of", lambda p: "")
    monkeypatch.setattr(rotate, "_append_log", lambda *a, **k: None)
    rep = rotate.rotate(str(tmp_path), [], apply=True)
    assert rep["ok"] and rep["applied"] is True
    assert rep["identity_backup"] and os.path.exists(rep["identity_backup"]), rep
    assert not ident.exists(), "身份文件应当被 drop（下次采集重建）"


def test_rotate_can_restore_the_backup(monkeypatch, tmp_path):
    from core.android import rotate

    ident = tmp_path / "device" / "device_identity.json"
    ident.parent.mkdir(parents=True, exist_ok=True)
    ident.write_text('{"brand": "X"}', encoding="utf-8")

    class _Store:
        path = str(ident)

        def drop(self, vm=0):
            # 真实签名 `drop(vm: int)`：身份按实例索引分槽存
            os.remove(self.path)
            return True

    monkeypatch.setattr(rotate, "_store", lambda *a, **k: _Store())
    monkeypatch.setattr(rotate, "_pkg_of", lambda p: "")
    monkeypatch.setattr(rotate, "_append_log", lambda *a, **k: None)
    rotate.rotate(str(tmp_path), [], apply=True)
    got = rotate.restore(str(tmp_path))
    assert got["ok"], got
    assert ident.exists() and "X" in ident.read_text(encoding="utf-8")


# ---- merged from tests/test_r1063_login_entry_url.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tuniu_pc_entry_is_the_pc_host():
    assert login_entry_url("tuniu", "pc") == "https://flight.tuniu.com/"
    assert "m.tuniu.com" not in login_entry_url("tuniu", "pc")


def test_tuniu_h5_entry_is_the_mobile_host():
    assert login_entry_url("tuniu", "h5").startswith("https://m.tuniu.com/")


def test_unknown_surface_defaults_to_pc():
    """端不明时给 PC（登录表单在 PC 上最完整，H5 常常只给扫码）。"""
    assert login_entry_url("tuniu", "") == "https://flight.tuniu.com/"
    # 未知端不落到移动域：要么按端覆盖的 pc，要么槽位里那格
    weird = login_entry_url("tuniu", "weird")
    assert "://m." not in weird, weird


def test_other_channels_now_have_login_entries_too():
    """T71 起**全渠道**都有登录入口（用户要求"全部"校准）。

    以前只有途牛登记，其余渠道退回"查看详情"深链——那是数据页，不是登录页。
    现在统一取 `LOGIN_SLOTS` 的 login_url（唯一真源）。
    """
    for plat in ("ctrip", "qunar", "fliggy", "tongcheng"):
        got = login_entry_url(plat, "pc")
        assert got.startswith("https://"), (plat, got)
    # 非浏览器渠道没有登录入口
    assert login_entry_url("app_ctrip", "pc") == ""


def test_takeover_window_url_is_pc_for_tuniu():
    """这条是用户实际会看到的那个地址。"""
    got = webui._probe_takeover_url("tuniu", "SHA", "PEK", "上海", "北京",
                                    "2026-11-20")
    assert got == "https://flight.tuniu.com/", got


def test_takeover_still_falls_back_for_unregistered():
    got = webui._probe_takeover_url("fliggy", "SHA", "PEK", "上海", "北京",
                                    "2026-11-20")
    assert got, "没登记的渠道仍要有可用的兜底地址"


def test_registry_shape_is_two_surfaces():
    for plat, rows in LOGIN_ENTRY.items():
        assert set(rows) <= {"pc", "h5"}, plat
        assert rows.get("pc", "").startswith("https://"), plat


# ---- merged from tests/test_r1063_login_reprobe.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_targets_include_vendor_app_channel(monkeypatch):
    import webui
    calls = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": (calls.append(p) or
                                             {"ok": True, "rows": 1}),
                        raising=False)
    monkeypatch.setattr(webui._State, "cfg", {}, raising=False)
    rep = webui._kick_login_probe("ctrip_h5")
    assert rep["ok"] is True
    assert rep["targets"] == ["ctrip", "app_ctrip"], rep
    time.sleep(0.8)
    assert calls == ["ctrip", "app_ctrip"], calls


def test_respects_config_off(monkeypatch):
    import webui
    calls = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": (calls.append(p) or {"ok": True}),
                        raising=False)
    monkeypatch.setattr(webui._State, "cfg",
                        {"web": {"login_reprobe": False}}, raising=False)
    rep = webui._kick_login_probe("fliggy")
    assert rep["ok"] is False and "关闭" in rep["why"], rep
    time.sleep(0.3)
    assert calls == []


def test_does_not_block(monkeypatch):
    import webui

    def slow(p, scope=""):
        time.sleep(1.5)
        return {"ok": True}

    monkeypatch.setattr(webui._State, "probe_cb", slow, raising=False)
    monkeypatch.setattr(webui._State, "cfg", {}, raising=False)
    t0 = time.time()
    webui._kick_login_probe("ctrip")
    dt = time.time() - t0
    assert dt < 0.5, "登录路径被探针阻塞了：%.2fs" % dt


def test_wired_into_login_success():
    src = webui_full_src()
    i = src.index("已清登录墙记忆")
    seg = src[i:i + 500]
    assert "_kick_login_probe" in seg, seg[:300]


# ---- merged from tests/test_r1063_login_requests_interrupt.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui_full_src()


def test_app_login_create_requests_interrupt():
    s = _src()
    i = s.index('_la.dispatch(_app_login_registry(), "POST", _u.path')
    seg = s[i:i + 1200]
    assert "叫停本轮为登录让路" in seg, "开会话没有请求叫停本轮"
    assert "_itr.request(by=\"app-login\")" in seg
    # 只对建会话那一步
    assert '_u.path.rstrip("/") == "/api/app-login"' in seg, \
        "必须只在建会话时请求，别让每次点击都写标记"
    assert "_r[0].get(\"ok\")" in seg, "只有会话建成功才叫停"


def test_interrupt_ttl_is_short_enough_for_login():
    """中止请求的 TTL 要够长（覆盖建会话→设备空出），但别无限。"""
    from core import interrupt as IT
    assert 300 <= IT.TTL_S <= 1800, IT.TTL_S


# ---- merged from tests/test_r1063_login_save_from_profile.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_finish_login_saves_from_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "tuniu"
    d.mkdir(parents=True, exist_ok=True)
    (d / "session-state.json").write_text(
        json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

    import webui
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    webui._State.login_sessions.clear()
    calls = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": (calls.append(p) or {"ok": True}),
                        raising=False)

    rep = webui._finish_login("tuniu", "tuniu")
    assert rep["ok"] is True, rep
    assert rep.get("saved") is True
    assert rep.get("profile_already_logged_in") is True
    time.sleep(0.5)
    assert calls and calls[0] == "tuniu", calls


def test_finish_login_without_profile_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    import webui
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    webui._State.login_sessions.clear()
    rep = webui._finish_login("tuniu", "tuniu")
    assert rep["ok"] is False
    assert "没有进行中的登录窗口" in rep["err"]
    assert "关窗" in (rep.get("hint") or ""), rep


def test_stale_profile_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "tuniu"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "session-state.json"
    f.write_text("{}", encoding="utf-8")
    old = time.time() - 24 * 3600
    os.utime(f, (old, old))

    import webui
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    webui._State.login_sessions.clear()
    rep = webui._finish_login("tuniu", "tuniu")
    assert rep["ok"] is False, "超过 6 小时的旧会话不该被当成刚登录"


# ---- merged from tests/test_r1063_login_wall_autonote.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _crawler(tmp=None):
    return AppCtripCrawler({"user_data_dir": tmp or tempfile.mkdtemp(),
                            "android": {}}, logging.getLogger("t85"))


def test_login_note_marks_wall_automatically():
    """记一条 login 账，就该等于"这家要登录"——置状态 + 落记忆。"""
    c = _crawler()
    assert c.login_suspect is False
    assert c.login_wall_until() == 0.0
    c.path_note("航班明细", "login", detail="该日被要求登录")
    assert c.login_suspect is True
    assert c.login_wall_until() > 0, "登录墙记忆必须落盘"


def test_non_login_status_does_not_mark():
    c = _crawler()
    c.path_note("航班明细", "timeout", detail="没打开")
    assert c.login_suspect is False
    assert c.login_wall_until() == 0.0


def test_login_memo_makes_fetch_free():
    c = _crawler()
    c.path_note("航班明细", "login", detail="窗内测")
    import time
    t0 = time.time()
    rows = c.fetch("SHA", "PEK", ["2026-11-16"])
    assert rows == []
    assert time.time() - t0 < 3, "登录墙窗口内不该再跑（真机实测 20 秒）"


def test_ctrip_rechecks_login_wall_when_rows_empty():
    """竞态补丁：空结果前必须再查一次登录墙，别把"要登录"记成"无航班"。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_ctrip.py"),
                  encoding="utf-8").read()
    i = src.index("_collect_rows(dev, page)")
    seg = src[i:i + 900]
    assert "再查一次登录墙" in seg
    assert 'note_date(date, [], "login"' in seg
    # 二次检查必须发生在记 timeout 之前
    assert seg.index('"login"') < seg.index("列表已打开但无可解析航班")


# ---- merged from tests/test_r1063_login_window_size.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _F(BaseCrawler):
    package = "x"

    def __init__(self, cfg, mobile):
        self.config = cfg
        self.use_mobile = mobile

    def login_url(self):
        return "https://x/"


def test_pc_default():
    assert _F({}, False).login_window_size() == (1280, 900)


def test_h5_default_is_phone_shaped():
    w, h = _F({}, True).login_window_size()
    assert w < h, "H5 窗口要给手机比例，否则控件点不准"
    assert (w, h) == (480, 880)


def test_config_override_both_surfaces():
    assert _F({"web": {"login_window": {"w": 1500, "h": 950}}},
              False).login_window_size() == (1500, 950)
    assert _F({"web": {"login_window_h5": {"w": 420, "h": 900}}},
              True).login_window_size() == (420, 900)


def test_bad_or_tiny_config_falls_back():
    assert _F({"web": {"login_window": {"w": "abc"}}},
              False).login_window_size() == (1280, 900)
    assert _F({"web": {"login_window": {"w": 200, "h": 300}}},
              False).login_window_size() == (1280, 900)


def test_launch_args_use_the_method():
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    i = src.index("--window-size")
    assert "login_window_size()" in src[max(0, i - 400):i], \
        "launch_args 必须用 login_window_size()，别再写死尺寸"

class _S(BaseCrawler):
    package = "x"
    use_mobile = True          # 采集走 m 站（ctrip/tuniu 就是这种）

    def __init__(self, surface=None, cfg=None):
        self.config = cfg or {}
        if surface is not None:
            self.login_surface = surface

    def login_url(self):
        return "https://x/"


def test_surface_wins_over_use_mobile():
    """`use_mobile=True` 是**采集**口径；PC 槽位仍要桌面尺寸。

    现场（用户截图）：携程 PC 登录窗是 480×880，passport 桌面页被裁 →
    "排版有问题"。根因就是拿 use_mobile 判端。
    """
    assert _S("pc").login_window_size() == (1280, 900)
    assert _S("h5").login_window_size() == (480, 880)


def test_falls_back_to_use_mobile_without_surface():
    assert _S(None).login_window_size() == (480, 880)   # use_mobile=True
    f = _S(None)
    f.use_mobile = False
    assert f.login_window_size() == (1280, 900)


def test_slot_crawler_stamps_surface():
    """`slot_crawler()` 必须把槽位的端写进 crawler.login_surface。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "login_slots.py"),
        encoding="utf-8").read()
    assert "crawler.login_surface" in src


# ---- merged from tests/test_r1063_login_yield.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Sess:
    def __init__(self, alive):
        self._alive = alive

    def alive(self):
        return self._alive


class _Reg:
    def __init__(self, mapping):
        self._m = mapping

    def plats(self):
        return list(self._m)

    def get(self, plat):
        return self._m.get(plat)


def test_active_plat_reports_live_session():
    LA.set_registry(_Reg({"app_ctrip": _Sess(True)}))
    assert LA.active_plat() == "app_ctrip"


def test_active_plat_ignores_dead_and_empty():
    LA.set_registry(_Reg({"app_ctrip": _Sess(False)}))
    assert LA.active_plat() == ""
    LA.set_registry(_Reg({}))
    assert LA.active_plat() == ""


def test_no_registry_is_safe():
    LA.set_registry(None)
    assert LA.active_plat() == ""


def test_early_skip_yields_to_other_channel_login(tmp_path, monkeypatch):
    """别的渠道在登录 → 本渠道本轮让位（记 paced，不是失败）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    LA.set_registry(_Reg({"app_fliggy": _Sess(True)}))
    from crawlers.app_ctrip import AppCtripCrawler
    import logging
    c = AppCtripCrawler({"crawler": {"user_data_dir": str(tmp_path)}},
                        logging.getLogger("t"))
    monkeypatch.setattr(c, "user_data_root", str(tmp_path), raising=False)
    notes = []
    monkeypatch.setattr(c, "path_note",
                        lambda path, status, **k: notes.append((path, status)),
                        raising=False)
    assert c.early_skip(["2026-11-16"]) is True
    # 让位必须记 `paced`（我方主动不发请求），不能记失败——否则爬取率被冤枉
    assert notes and notes[0][1] == "paced", notes


def test_own_channel_login_does_not_yield():
    """自己正在登录 ≠ 让位（那是要采的渠道）。"""
    LA.set_registry(_Reg({"app_ctrip": _Sess(True)}))
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    i = src.index("用户正在 App 登录")
    seg = src[max(0, i - 300):i + 200]
    assert "_who != self.name" in seg, "必须排除自己，否则登录期间永远不采"


# ---- merged from tests/test_r1063_relogin_notice.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_lists_only_subscribed_app_channels():
    cfg = {"users": [{"platforms": ["fliggy", "app_zhixing", "app_qunar",
                                    "tongcheng"]}]}
    got = identity.apps_need_relogin(cfg)
    assert got == ["app_zhixing", "app_qunar"], got


def test_empty_config_is_safe():
    assert identity.apps_need_relogin({"users": []}) == []
    assert identity.apps_need_relogin({}) == []      # 读不到就空，不抛


def test_rotate_dry_run_includes_notice(monkeypatch):
    # 干净检出里没有 config.yaml（被 gitignore），订阅名单为空 →
    # 这里把清单固定下来，测的是"有清单就一定要提示"这条契约。
    monkeypatch.setattr(identity, "apps_need_relogin",
                        lambda cfg=None: ["app_zhixing", "app_ctrip"])
    rep = rotate.rotate("user_data", [], apply=False)
    assert rep["ok"] is True
    assert rep.get("relogin_required") == ["app_zhixing", "app_ctrip"], rep
    assert "重新登录" in (rep.get("notice") or ""), rep


def test_align_dry_run_includes_notice():
    rep = align.apply(None, None, write=False)
    if rep.get("pick"):
        assert rep.get("relogin_required"), rep
        assert "重新登录" in (rep.get("notice") or ""), rep


def test_docs_mention_the_ordering_discipline():
    """手册里要有"换身份 → 必须重登所有 App"这条纪律。"""
    if not os.path.exists(os.path.join(ROOT, "docs", "CAPABILITY_AND_UNBLOCK.md")):
        pytest.skip("CAPABILITY_AND_UNBLOCK 已删（W2b 文档工程），本门禁失去检查对象")
    doc = io.open(os.path.join(ROOT, "docs", "CAPABILITY_AND_UNBLOCK.md"),
                  encoding="utf-8").read()
    assert "重登" in doc or "重新登录" in doc


# ---- merged from tests/test_r1063_vendor_login_clears.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn():
    import webui
    return webui._clear_login_wall_memo


def _pin_root(tmp_path, monkeypatch):
    """把"根目录"钉到 tmp_path（三处来源全对齐）。

    必须钉 `_ud_root_runtime()`：`_effective_crawler_config()` 会用它覆盖
    `user_data_dir`，而它是**启动时缓存**的——只设环境变量对已启动实例无效。
    这也是"单独跑绿、批量跑红"的真因。
    """
    import webui
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(webui, "_ud_root_runtime", lambda: str(tmp_path),
                        raising=False)
    monkeypatch.setattr(
        webui._State, "cfg",
        {"crawler": {"user_data_dir": str(tmp_path)}}, raising=False)
    webui._State.login_sessions.clear()
    return webui


def test_ctrip_login_clears_app_ctrip(tmp_path, monkeypatch):
    _pin_root(tmp_path, monkeypatch)
    for plat in ("ctrip", "app_ctrip"):
        d = tmp_path / plat
        d.mkdir(parents=True, exist_ok=True)
        (d / "login_wall.json").write_text(
            json.dumps({"until": 9e9, "detail": "该日被要求登录"}),
            encoding="utf-8")

    cleared = _fn()("ctrip")
    assert not (tmp_path / "ctrip" / "login_wall.json").exists()
    assert not (tmp_path / "app_ctrip" / "login_wall.json").exists(), \
        "同厂商 App 渠道的墙没被清：%r" % (cleared,)
    assert any("app_ctrip" in c for c in cleared), cleared


def test_fliggy_login_clears_app_gone_memo(tmp_path, monkeypatch):
    _pin_root(tmp_path, monkeypatch)
    from core import service_state as ss
    ss.mark(str(tmp_path), "app_fliggy", "app_gone", "自行退出", window_s=7200)
    assert ss.until(str(tmp_path), "app_fliggy", "app_gone") > 0

    _fn()("fliggy_h5")
    assert ss.until(str(tmp_path), "app_fliggy", "app_gone") == 0, \
        "登录后 App 自杀熔断也该被清掉"


def test_unknown_vendor_only_clears_itself(tmp_path, monkeypatch):
    _pin_root(tmp_path, monkeypatch)
    d = tmp_path / "some_new_vendor"
    d.mkdir(parents=True, exist_ok=True)
    (d / "login_wall.json").write_text("{}", encoding="utf-8")
    cleared = _fn()("some_new_vendor")
    assert any("some_new_vendor" in c for c in cleared), cleared


def test_vendor_map_covers_all_slots():
    import webui
    needed = {"ctrip", "fliggy", "tongcheng", "tuniu", "qunar"}
    assert needed <= set(webui.VENDOR_APP_PLATS), webui.VENDOR_APP_PLATS


# ---- merged from tests/test_r1063_verify_url_heuristic.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGIN_URL = "https://passport.tuniu.com/login"


def test_login_url_alone_no_longer_forces_login():
    """已登录页面 + 登录页 URL → 旧逻辑必判需登录；新逻辑必须放行。"""
    body = "我的订单 退出登录 会员中心 钱包"
    old = classify_text(body, LOGIN_URL)
    assert old is not None and old.status == "login", (
        "旧行为应命中 URL 启发式（用于证明这个 bug 真实存在）")
    new = classify_text(body, LOGIN_URL, ignore_url=True)
    assert new is None, "已登录页面不该被判成登录墙（issue #15 的核心）"


def test_unlogged_page_still_detected():
    """忽略 URL 后，**正文**仍要能认出登录页。"""
    sig = classify_text("请输入手机号 手机号登录 账号密码登录", LOGIN_URL,
                        ignore_url=True)
    assert sig is not None and sig.status == "login", sig


def test_default_behaviour_unchanged_for_collection():
    """采集侧默认仍看 URL（登录页 = 需要登录），不要被这次改动带走。"""
    sig = classify_text("机票 酒店 火车票", LOGIN_URL)
    assert sig is not None and sig.status == "login"


def test_verify_calls_with_ignore_url():
    w = webui_full_src()
    assert "classify_text(body, page_url, ignore_url=True)" in w, \
        "槽位核验必须忽略 URL 启发式，否则永远判需登录"


# ---- merged from tests/test_r1161_login_finish_accepts_stale.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _mk_profile(tmp_path, slot, age_h):
    d = tmp_path / slot
    d.mkdir(parents=True, exist_ok=True)
    f = d / "session-state.json"
    f.write_text('{"cookies":[]}', encoding="utf-8")
    t = time.time() - age_h * 3600.0
    os.utime(f, (t, t))
    return f


def _call(tmp_path, monkeypatch, plat, slot):
    import webui
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)}}, raising=False)
    monkeypatch.setattr(webui._State, "login_sessions", {}, raising=False)
    verified = []
    monkeypatch.setattr(webui, "_verify_login_slot",
                        lambda k: verified.append(k) or {"ok": True},
                        raising=False)
    probed = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": probed.append(p) or {"ok": True},
                        raising=False)
    return webui._finish_login(plat, slot), verified, probed


def test_stale_h5_session_is_explained_and_auto_verified(tmp_path, monkeypatch):
    """7 小时前的 H5 会话：不能假装刚登录，但必须说清原因并自动核验。"""
    _mk_profile(tmp_path, "tuniu_h5", 7)
    r, verified, _ = _call(tmp_path, monkeypatch, "tuniu", "tuniu_h5")
    assert r.get("ok") is False, "陈旧会话不许冒充新登录：" + str(r)
    assert r.get("stale") is True, r
    assert 6.5 <= float(r.get("age_h") or 0) <= 7.5, r
    assert "小时未更新" in (r.get("err") or ""), "必须把『多久没更新』说出来：" + str(r)
    assert "没有会话文件" not in (r.get("err") or ""), (
        "文件明明在，不能再说没有会话文件：" + str(r))
    time.sleep(0.2)
    assert verified == ["tuniu_h5"], "陈旧 H5 会话必须自动发起页面核验：%s" % verified
    assert r.get("verifying") is True, r


def test_stale_pc_session_uses_probe_not_page_verify(tmp_path, monkeypatch):
    """PC 槽位走真查询自检（probe），不打开登录页（会误判成需登录）。"""
    _mk_profile(tmp_path, "tuniu", 8)
    r, verified, probed = _call(tmp_path, monkeypatch, "tuniu", "tuniu")
    assert r.get("ok") is False and r.get("stale") is True, r
    assert r.get("verifying") is False, r
    time.sleep(0.2)
    assert verified == [], "PC 槽位不该走页面核验：%s" % verified
    assert probed and probed[0] == "tuniu", probed


def test_fresh_session_still_saves(tmp_path, monkeypatch):
    _mk_profile(tmp_path, "tuniu_h5", 0.2)
    r, _, _ = _call(tmp_path, monkeypatch, "tuniu", "tuniu_h5")
    assert r.get("ok") is True and r.get("saved") is True, r
    assert r.get("stale") is False, r


def test_no_file_is_honest_and_actionable(tmp_path, monkeypatch):
    """负控：真没登过时，文案必须既承认"还没有记录"，又保住 r1063 的"关窗即保存"。"""
    r, verified, _ = _call(tmp_path, monkeypatch, "tuniu", "tuniu_h5")
    assert r.get("ok") is False, r
    assert "还没有任何登录记录" in (r.get("err") or ""), r
    assert "没有进行中的登录窗口" in (r.get("err") or ""), r
    assert "关窗" in (r.get("hint") or ""), r
    assert verified == [], "没有会话文件时不该发起核验"


# ---- merged from tests/test_r1339_login_wait_and_slow_api.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_login_placeholder_explains_and_counts():
    i = SRC.find('<div id="loginRows">')
    assert i > 0, "找不到登录卡占位"
    seg = SRC[i:i + 260]
    assert "正在读取登录状态" in seg, seg
    assert "lgwait" in seg, "占位没有可计数的节点"
    assert "本机设备依次探测中" in seg, "没说明在等什么"


def test_wait_counter_ticks_every_second():
    i = SRC.find("#loginRows .lgwait")
    assert i > 0, "找不到计数逻辑"
    seg = SRC[max(0, i - 400):i + 400]
    assert "setInterval" in seg and "已等待" in seg, seg


def test_slow_get_is_logged():
    assert "def _do_GET_impl(self):" in SRC, "do_GET 没有被包一层计时"
    i = SRC.find("def do_GET(self):")
    seg = SRC[i:i + 900]
    assert "time.time()" in seg and "> 2.0" in seg, seg
    assert "[api] GET %s 耗时" in seg, "日志文案缺失"


def test_slow_logging_cannot_break_response():
    """负控：记账在 finally 里且自身包裹 try——绝不能让"记日志"把响应打断。

    r1392：改用 `inspect.getsource` 取**方法体全文**再断言三件事，不再按
    字符窗口切片——do_GET 里加了一层「替身 handler 回退」后偏移就变了，
    窗口切片的断言会假红（CI 实测）。
    """
    import inspect
    import webui
    src = inspect.getsource(webui._Handler.do_GET)
    assert "finally:" in src, "计时不在 finally 里，异常路径会丢日志"
    assert "[api] GET %s 耗时" in src, "日志文案缺失"
    # 日志调用必须被 try/except 包住（否则日志异常会打断响应）
    i = src.index("[api] GET %s 耗时")
    tail = src[i:]
    assert "except Exception" in tail, "日志调用没有自保"


# ---- merged from tests/test_r290_login_stale.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture
def q_cls():
    from crawlers.qunar import QunarCrawler
    had = hasattr(QunarCrawler, "login_suspect")
    old = getattr(QunarCrawler, "login_suspect", None)
    old_gap, old_back = QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S
    old_cd, old_done = QunarCrawler._cooldown_until, QunarCrawler._last_done_ts
    QunarCrawler._MIN_GAP_S = 0
    # (0,)：一轮零秒重试——() 会在置标记分支之前走「耗尽」短路，置标记
    # 路径不可达（测试构造须让生产分支真实可达，十九§16 死档判据投影）
    QunarCrawler._BACKOFF_S = (0,)
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    yield QunarCrawler
    if had:
        QunarCrawler.login_suspect = old
    elif hasattr(QunarCrawler, "login_suspect"):
        delattr(QunarCrawler, "login_suspect")
    QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S = old_gap, old_back
    QunarCrawler._cooldown_until, QunarCrawler._last_done_ts = old_cd, old_done


def test_qunar_sets_suspect_on_server_reject(q_cls, monkeypatch, tmp_path):
    """无认证 Cookie 证据 + 三路径空结果 → 置 login_suspect。

    r817 起「认证 Cookie 在场且探测在线」改判软空、不催重登；本用例
    用隔离空档案验证「确实没有登录证据」时仍会置失效标记。
    """
    q_cls._auth_probe_at = 0.0
    q_cls._auth_probe_ok = None
    c = q_cls({"user_data_dir": str(tmp_path)}, logging.getLogger("t290"))
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: None)
    q_cls._BACKOFF_S = (0,)
    assert c.fetch("上海", "海口", ["2027-01-29"]) == []
    assert q_cls.login_suspect is True


def test_qunar_clears_suspect_on_hit(q_cls, monkeypatch):
    """任一路径重新拿到数据即清标记（恢复自愈），卡片退回「已有登录态」。"""
    q_cls.login_suspect = True
    c = q_cls({}, logging.getLogger("t290"))
    flights = [{"code": "CA8573", "name": "国航CA8573", "price": 1750.0,
                "depTime": "15:30", "arrTime": "18:55"}]
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: (1750.0, flights))
    rows = c.fetch("上海", "海口", ["2027-01-29"])
    assert rows
    assert q_cls.login_suspect is False


def test_login_state_view_carries_stale(q_cls, tmp_path, monkeypatch):
    """_login_state_view 上浮 stale 字段并随类属性联动；saved 语义不变
    （本地档案在场）。档案目录用 tmp_path 构造（离线可跑，不依赖生产
    user_data）。"""
    import webui
    (tmp_path / "qunar").mkdir()
    (tmp_path / "qunar" / "marker").write_text("x", encoding="utf-8")
    # 直接注入配置解析结果：_State.cfg/boot_cfg 是进程级全局，同 worker
    # 前序用例遗留的后台线程会在断言窗口内重载它（CI xdist 实测
    # saved=False）。这里只钉 _login_state_view 对 user_data_dir 的语义。
    monkeypatch.setattr(webui, "_effective_crawler_config",
                        lambda: {"user_data_dir": str(tmp_path)})
    try:
        q_cls.login_suspect = False
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["saved"] is True
        assert v["plats"]["qunar"]["stale"] is False
        q_cls.login_suspect = True
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["saved"] is True
        assert v["plats"]["qunar"]["stale"] is True
    finally:
        q_cls.login_suspect = False


def test_login_stale_wording_in_page(q_cls):
    """前端三态词面源码钉：失效档词面在 PAGE；「已有登录态」词面保留
    （无失效证据时不变——档案在且无失效证据仍显示登录态）。"""
    import webui
    src = webui_full_src()
    assert "会话需重新登录" in src, "失效档词面缺席"
    assert "已有登录态" in src, "常态档词面被误删"


# ---- merged from tests/test_r291_login_refresh.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_finish_login_clears_backoff():
    """「我已登录完成」清该渠道退避冷却：用户主动登录=明确的重试意图，
    退避残留（最长 300s）会让下轮验证拖几十分钟——保存会话即清，
    下一轮调度立即用新会话验证。同时置 pending 验证窗（词面过渡档
    的数据源——置标记行为必须走真实 _finish_login 锁定）。"""
    import time
    import webui
    from crawlers import REGISTRY
    q = REGISTRY["qunar"]
    old_cd = getattr(q, "_cooldown_until", None)
    old_pending = dict(getattr(webui._State, "login_pending", {}))
    webui._State.login_sessions["qunar"] = {"evt": threading.Event()}
    try:
        q._cooldown_until = 12345.0
        r = webui._finish_login("qunar")
        assert r["ok"] is True
        assert q._cooldown_until == 0, (
            "登录完成后退避冷却未清——下轮验证被退避残留拖慢")
        assert "qunar" not in webui._State.login_pending, (
            "finish 仅确认保存请求；pending 必须等 worker 真正落盘后置位")
    finally:
        webui._State.login_sessions.pop("qunar", None)
        if old_cd is not None:
            q._cooldown_until = old_cd
        webui._State.login_pending = old_pending


def test_finish_login_unknown_platform_no_side_effect():
    """无进行中登录窗口时返回 err 且不动冷却（副作用零外溢）。"""
    import webui
    from crawlers import REGISTRY
    q = REGISTRY["qunar"]
    old_cd = getattr(q, "_cooldown_until", None)
    try:
        q._cooldown_until = 777.0
        r = webui._finish_login("qunar")
        assert r["ok"] is False
        assert q._cooldown_until == 777.0
    finally:
        if old_cd is not None:
            q._cooldown_until = old_cd


def test_login_polling_in_page():
    """前端自动刷新源码钉：登录分区周期轮询器（lgWatchStart 定义+挂接
    双段在场）+ 内容签名防抖判定行（状态无变化不重绘）。钉面锁唯一
    行为承载串——setInterval 在 PAGE 有其他消费点（主轮询），锁泛名
    是恒真式（十八§11 心理变异判据）。"""
    import webui
    src = webui_full_src()
    assert "function lgWatchStart" in src, "轮询器定义缺席"
    assert "loadLogin(null,true);lgWatchStart();" in src, \
        "轮询挂接缺席（进分区即拉+启动）"
    assert "if(!force&&sig===LGSIG)" in src, \
        "内容签名防抖判定缺席（轮询重绘会打断点按）"


def test_finish_login_toast_wording():
    """toast 不得承诺未保证的分钟数：调度周期可配，只承诺「下一轮
    采集验证后自动更新（无需重启）」；检索页登录态另行即时同步。

    r-登录体验：保存是后台异步收尾，前端只能确认「请求已受理」。
    原文案一律写「✅ 会话已保存」，后台判定失败时就是假成功（用户以为
    登好了，卡片随后又跳回「需登录」）。改为中性口径「已提交保存，
    正在校验会话（卡片状态会自动更新）」，真实结果由卡片状态呈现；
    仍然只承诺「自动更新」，不承诺具体分钟数。
    """
    import webui
    src = webui_full_src()
    # 收紧：既然已经改成中性口径，就不许再写「✅ 会话已保存」这种假成功
    assert "已提交保存，正在校验会话（卡片状态会自动更新）" in src, \
        "登录完成 toast 没改成中性口径（假成功）"
    assert "下一轮采集（≤5 分钟）" not in src, "未保证的分钟数不得承诺"
    assert "SRX_LOGIN_T=0;SCAT=0;" in src, "finish 后未触发检索页登录态同步"


def test_finish_login_sets_pending_window():
    """「我已登录完成」置 pending 验证窗（10 分钟）：刚点完登录的卡片
    不得再说「会话可能失效，建议重登」——刚登完就被建议重登是词面
    自相矛盾（用户实测立案）；窗内 stale 仍在场（不退绿=未验证不假绿），
    前端以「验证中」过渡词面呈现。窗过后标记未清则回到「建议重登」
    （验证确实失败，重登建议重新成立）。"""
    import time
    import webui
    from crawlers import REGISTRY
    q = REGISTRY["qunar"]
    old = getattr(q, "login_suspect", None)
    old_pending = dict(getattr(webui._State, "login_pending", {}))
    try:
        q.login_suspect = True
        webui._State.login_pending["qunar"] = time.time() - 1
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["stale"] is True, "窗内未验证不假绿"
        assert v["plats"]["qunar"]["pending"] is True, "pending 窗缺席"
        webui._State.login_pending["qunar"] = time.time() - 700
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["pending"] is False, "窗过期仍 pending"
    finally:
        if old is not None:
            q.login_suspect = old
        webui._State.login_pending = old_pending


def test_newer_login_rejection_ends_pending_window(monkeypatch):
    """点「登录完成」后只有**新的**明确拒绝才能结束待验证窗；旧拒绝
    证据不得把刚点的登录瞬间打回「建议重登」。"""
    import time
    from datetime import datetime
    import webui
    old_pending = dict(webui._State.login_pending)
    try:
        webui._State.login_pending["qunar"] = time.time() - 30
        monkeypatch.setattr(
            webui, "_health_state",
            lambda hours: {"evidence": {"qunar": {"domestic": {
                "auth_at": datetime.now().isoformat(timespec="seconds"),
                "detail_at": "", "auth_reason": "需登录"}}}})
        monkeypatch.setattr(webui, "_PROBE_AUTH", {})
        monkeypatch.setattr(webui._State, "login_sessions", {})
        v = webui._login_state_view()["plats"]["qunar"]
        assert v["pending"] is False, "新拒绝应结束待验证窗"
        assert v["status"] == "login_required"
    finally:
        webui._State.login_pending = old_pending


def test_login_pending_wording_in_page():
    """前端过渡词面钉：pending 窗内显示「验证中」不再说「建议重登」；
    登录窗口开着（active）时词面优先「登录中…」——登录中却说「建议
    重登」同为自相矛盾形态。"""
    import webui
    src = webui_full_src()
    assert "下轮采集验证中" in src, "pending 过渡词面缺席"
    assert "会话需重新登录" in src, "常态失效词面被误删"


# ---- merged from tests/test_r338_login_state.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PLAT = "qunar"


def _fresh_suspect():
    from crawlers.qunar import QunarCrawler
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    # 剥退避表（(0,) 零秒）：mock 路径的任何意外异常会被 fetch 外壳
    # 吞掉落进退避循环——真实 _BACKOFF_S 会让测试真睡 570 秒（挂起
    # 形态实录）；r290 fixture 同款纪律
    QunarCrawler._BACKOFF_S = (0,)
    QunarCrawler.login_suspect = True
    return QunarCrawler


def _fp(**kw):
    """FlightPrice 构造（_fetch_inner 真实返回元素是 dataclass 非
    dict——mock 必须尊重公共契约，dict 形态会让 .get 形态的缺陷判据
    在测试里假活、生产 AttributeError）。"""
    from core.models import FlightPrice
    base = dict(platform="qunar", from_city="SHA", to_city="PEK",
                depart_date="2026-11-16", price=500.0)
    base.update(kw)
    return FlightPrice(**base)


# ---------- 缺陷 1：login_suspect 复位判据 ----------

def test_calendar_only_rows_keep_suspect(monkeypatch):
    """纯日历行出数（无 flight_no/depart_time）不清会话失效证据。"""
    cls = _fresh_suspect()
    crawler = cls({}, logging.getLogger("t"))
    monkeypatch.setattr(crawler, "_fetch_inner", lambda f, t, d: [_fp()])
    res = crawler.fetch("SHA", "PEK", ["2026-11-16"])
    assert res, "日历行应照常出数（复位判据收窄不改变出数行为）"
    assert cls.login_suspect is True, (
        "纯日历行不证会话有效——失效证据必须保留（否则 UI 卡片"
        "在明细会话已死时仍显示「已有登录态」）")


def test_detail_rows_clear_suspect(monkeypatch):
    """明细行出数（flight_no 在场）照常清证据退「已有登录态」。"""
    cls = _fresh_suspect()
    crawler = cls({}, logging.getLogger("t"))
    monkeypatch.setattr(
        crawler, "_fetch_inner",
        lambda f, t, d: [_fp(flight_no="MU1234", depart_time="08:00")])
    res = crawler.fetch("SHA", "PEK", ["2026-11-16"])
    assert res
    assert cls.login_suspect is False


def test_mixed_rows_clear_suspect(monkeypatch):
    """混合行（日历+明细）按明细在场清证据（会话确证有效）。"""
    cls = _fresh_suspect()
    crawler = cls({}, logging.getLogger("t"))
    monkeypatch.setattr(
        crawler, "_fetch_inner",
        lambda f, t, d: [_fp(), _fp(flight_no="MU1234", depart_time="08:00")])
    crawler.fetch("SHA", "PEK", ["2026-11-16"])
    assert cls.login_suspect is False


# ---------- 缺陷 2：pending 窗防重入 ----------

def test_start_login_rejected_within_pending_window(monkeypatch):
    """会话刚保存（pending 窗内）再点弹窗登录被拒（防第二窗口）。"""
    import webui
    from crawlers import REGISTRY
    # 防真弹窗：_login_window 类级 no-op（RED 态 _start_login 仍会起
    # 线程——不 patch 会真开 Playwright 有头窗口）
    monkeypatch.setattr(REGISTRY[_PLAT], "_login_window",
                        lambda self, evt, *args, **kwargs: None)
    # 本机真实 monitor.log 会带回「需登录」证据：pending 闸门只拦
    # 「没有新拒绝」的槽位，证据在场时放行是设计行为。断言要钉的是
    # 闸门本身，先把外部证据隔离掉（否则本机有真实数据就必然假红）。
    monkeypatch.setattr(webui, "_health_state",
                        lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    webui._State.login_errors.clear()
    webui._State.login_sessions.pop(_PLAT, None)
    webui._State.login_pending[_PLAT] = time.time()
    try:
        r = webui._start_login(_PLAT)
        assert r.get("ok") is False, (
            "pending 验证窗内拒绝新弹窗——刚保存的会话在 10 分钟窗内"
            "待下轮采集验证，重复弹窗把卡片拉回「登录中」吞掉用户成果")
        assert _PLAT not in webui._State.login_sessions
    finally:
        webui._State.login_pending.pop(_PLAT, None)
        webui._State.login_sessions.pop(_PLAT, None)
        # 登录线程失败会把摘要写进全局 login_errors，串到后续用例的
        # 「保存失败」状态上（r368 曾因此假红）——本用例不验该字段。
        webui._State.login_errors.pop(_PLAT, None)
        webui._PROBE_AUTH.clear()


# ---- merged from tests/test_r412_login_rows_alignment.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def server():
    import webui
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(1.2)
    yield port
    srv.shutdown()








def test_dual_slot_sub_date_line_never_wraps():
    """飞猪双槽的说明必须单行——它是「五行等高」的根因，单独守一道。

    900 档实测（r543）：双槽只有 157px 宽，「必须登录 · 已保存 ·
    会话待验证」折成两行 33px，把飞猪行撑到 69px，同页其余四行 52px。
    上面那条几何守卫会在真跑浏览器时抓到，这条只守 CSS 意图，跑得快、
    失败信息直指原因（是"说明折行"而不是"某行莫名高了"）。
    """
    import webui
    src = webui.PAGE
    i = src.index("#loginRows .lgslots:has(.lgslot+.lgslot){grid-template-columns:auto auto")
    seg = src[i:i + 900]
    assert "#loginRows .lgslots:has(.lgslot+.lgslot) .lgsub{" in seg, seg
    rule = seg[seg.index("#loginRows .lgslots:has(.lgslot+.lgslot) .lgsub{"):]
    rule = rule[:rule.index("}") + 1]
    assert "white-space:nowrap!important" in rule, rule
    assert "text-overflow:ellipsis!important" in rule, rule






# ---- merged from tests/test_r620_login_reports_only_real_window.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _BoomCrawler:
    """模拟 Playwright 起不来（缺内核 / 显示不可用）。"""

    name = "ctrip"
    _cooldown_until = 0

    def _login_window(self, done_evt, idx=0, timeout_s=0, ready_evt=None):
        raise RuntimeError("Executable doesn't exist at chromium-1234")


class _OkCrawler:
    """窗口真的开了：置位 ready 后等 done。"""

    name = "ctrip"
    _cooldown_until = 0

    def _login_window(self, done_evt, idx=0, timeout_s=0, ready_evt=None):
        if ready_evt is not None:
            ready_evt.set()
        while not done_evt.is_set():
            time.sleep(0.05)
        return True


@pytest.fixture(autouse=True)
def _pretend_graphical(monkeypatch):
    """这些用例测的是「窗口能不能真的开」这件事，与运行机有没有 X 无关。

    CI 是 Linux 且无 DISPLAY，`_no_graphical_env()` 恒 True——不隔离的话
    /api/login 一律走 no_gui 短路，窗口逻辑一条都测不到（本地 Windows
    永远复现不出来，CI 上 4 条全红）。
    """
    monkeypatch.setattr(webui, "_no_graphical_env", lambda: False)


def _slot():
    from core.login_slots import LOGIN_SLOTS
    for k, m in LOGIN_SLOTS.items():
        return k, m["plat"]
    raise AssertionError("没有登录槽位")


def _reset(key):
    for d in (webui._State.login_errors, webui._State.login_sessions,
              webui._State.login_pending):
        d.pop(key, None)


def _patch(monkeypatch, factory):
    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key_arg, cfg=None, logger=None: factory())


def _drain(key, timeout=8):
    """收尾：让登录线程退出，别把渠道锁留给下一个用例。"""
    sess = webui._State.login_sessions.get(key)
    if sess:
        sess["evt"].set()
        sess["done"].wait(timeout)
    _reset(key)


def test_window_open_failure_is_reported_not_swallowed(monkeypatch):
    key, plat = _slot()
    _patch(monkeypatch, lambda: _BoomCrawler())
    _reset(key)
    t0 = time.time()
    r = webui._start_login(plat, key)
    dt = time.time() - t0
    # 先断言状态，再清理（_drain 会抹掉 login_errors）
    try:
        assert r.get("ok") is False, (
            "窗口根本没开成，接口却回报成功：%r" % (r,))
        assert r.get("kind") == "window_failed", (
            "失败没有归类为 window_failed（前端无法给专属提示）：%r" % (r,))
        assert r.get("err"), "失败没有给出原因"
        assert "chromium-1234" in r["err"], (
            "原因没传到点击者（只给了笼统一句）：%r" % (r,))
        assert dt < 30, "失败应在就绪等待内立刻返回，实际等了 %.1fs" % dt
        assert key not in webui._State.login_sessions, (
            "失败后会话没清掉——用户会被「窗口已打开」永久挡住")
        assert key in webui._State.login_errors, "失败原因没落到状态里"
        assert "chromium-1234" in webui._State.login_errors[key], (
            "落到状态里的原因不具体：%r" % webui._State.login_errors[key])
    finally:
        _drain(key)


def test_log_does_not_claim_window_opened_before_it_did(monkeypatch):
    """日志时序：先失败时不得留下「已弹出」的成功句（#10 的同期症状）。"""
    key, plat = _slot()
    _patch(monkeypatch, lambda: _BoomCrawler())
    _reset(key)
    import logging

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, rec):
            self.lines.append(rec.getMessage())

    cap = _Cap()
    webui._State.logger.addHandler(cap)
    try:
        webui._start_login(plat, key)
        time.sleep(0.3)
    finally:
        webui._State.logger.removeHandler(cap)
        _drain(key)
    opened = [m for m in cap.lines if "已弹出" in m]
    assert not opened, "窗口没开成却记下了「已弹出」：%r" % opened
    assert any("未能打开" in m for m in cap.lines), (
        "失败没有留下可查的日志：%r" % cap.lines)


def test_ready_window_still_reports_success(monkeypatch):
    """真开成时行为不变：仍返回 ok + plat/slot（回归护栏）。"""
    key, plat = _slot()
    _patch(monkeypatch, lambda: _OkCrawler())
    _reset(key)
    r = webui._start_login(plat, key)
    try:
        assert r.get("ok") is True, r
        assert r.get("slot") == key and r.get("plat"), r
    finally:
        _drain(key)


def test_busy_channel_waits_but_is_bounded(monkeypatch):
    """采集正占着渠道锁时：用户在排队——仍要能开成，且不无限等。

    这里用「另一个线程先持锁、0.5s 后放开」来模拟采集收尾。
    """
    key, plat = _slot()
    _patch(monkeypatch, lambda: _OkCrawler())
    _reset(key)
    lock = _base.platform_lock(str(plat))
    holder = threading.Thread(target=lambda: (lock.acquire(), time.sleep(0.5),
                                              lock.release()), daemon=True)
    holder.start()
    time.sleep(0.05)
    r = webui._start_login(plat, key)
    holder.join(5)
    _drain(key)
    assert r.get("ok") is True, (
        "等锁后应当照常开窗，实际：%r" % (r,))


def test_no_gui_kind_is_still_returned_on_posix_headless(monkeypatch):
    """原有 no_gui 判据不许被这次改动挤掉（Windows/macOS 不受影响）。"""
    key, plat = _slot()
    # 只替换单源判据：从前 patch 的是进程级 `os.environ.get`，
    # monkeypatch 复原时会把补丁泄漏给同进程其它用例——实测让
    # `_bind_host` 读到被替换的 get，容器监听地址门禁在 CI 上假红。
    monkeypatch.setattr(webui, "_no_graphical_env", lambda: True)
    _reset(key)
    r = webui._start_login(plat, key)
    assert r.get("ok") is False and r.get("kind") == "no_gui", r


# ---- merged from tests/test_r676_login_verify_is_real_probe.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ---------------- ② 真服务：证据写入 ----------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live():
    import webui
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="r676_")
    cfg_path = os.path.join(tmp, "c.yaml")
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg_path)
    webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                    job=None, report_push=None, config_path=cfg_path)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            op.open(base + "/api/state", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    yield base, op, webui
    webui._State.probe_cb = None


def _probe(base, op, plat="ctrip"):
    req = urllib.request.Request(
        base + "/api/channel/probe", method="POST",
        data=json.dumps({"platform": plat}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with op.open(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _install_fake(webui, out):
    webui._State.probe_cb = lambda plat, **kw: dict(out, platform=plat)


def _auth(webui, plat, key):
    return dict((webui._PROBE_AUTH.get(plat) or {}).get("dom") or {}).get(key)


def test_probe_with_rows_writes_detail_evidence(live):
    base, op, webui = live
    webui._PROBE_AUTH.pop("ctrip", None)
    _install_fake(webui, {
        "ok": True, "rows": 7, "query": ["SHA", "NRT", "2026-11-20"],
        "scope": "dom",
        "paths": [{"path": "H5", "status": "ok", "rows": 7}]})
    j = _probe(base, op)
    assert j.get("ok") and j.get("rows") == 7
    assert _auth(webui, "ctrip", "detail_count") == 7, \
        "自检出数没有写进登录态证据（登录卡不会变）"
    assert _auth(webui, "ctrip", "from") == "SHA"


def test_probe_login_wall_writes_reject_evidence(live):
    base, op, webui = live
    webui._PROBE_AUTH.pop("ctrip", None)
    _install_fake(webui, {
        "ok": True, "rows": 0, "query": ["SHA", "URC", "2026-11-21"],
        "scope": "dom",
        "paths": [{"path": "H5", "status": "login", "rows": 0},
                  {"path": "PC", "status": "empty", "rows": 0}]})
    _probe(base, op)
    assert _auth(webui, "ctrip", "auth_reason") == "登录墙", \
        "被登录墙拦却不落拒绝证据，卡片会停在「已保存」"
    assert _auth(webui, "ctrip", "auth_path") == "H5"


def test_probe_empty_without_wall_writes_nothing(live):
    base, op, webui = live
    webui._PROBE_AUTH.pop("ctrip", None)
    _install_fake(webui, {
        "ok": True, "rows": 0, "query": ["SHA", "URC", "2026-11-22"],
        "scope": "dom",
        "paths": [{"path": "H5", "status": "empty", "rows": 0}]})
    _probe(base, op)
    assert not (webui._PROBE_AUTH.get("ctrip") or {}).get("dom"), \
        "0 条且无拦截证据时不得下任何登录结论（无票≠会话失效）"


# ---------------- ① 真渲染：按钮与请求 ----------------











