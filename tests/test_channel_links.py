# -*- coding: utf-8 -*-
"""Channel PC/H5 × domestic/intl quick-jump link builder."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cells(result):
    return {(c["plat"], c["surface"], c["scope"]): c
            for c in result["cells"]}


def test_entry_mode_has_all_twenty_cells():
    from core.channel_links import channel_links
    r = channel_links()
    assert r["mode"] == "entry" and r["scope"] == ""
    assert len(r["cells"]) == 20
    c = _cells(r)
    assert set(c) == {(p, s, sc)
                      for p in ("ctrip", "qunar", "fliggy",
                                "tongcheng", "tuniu")
                      for s in ("pc", "h5")
                      for sc in ("domestic", "intl")}
    assert all((x["ok"] and x["url"].startswith("https://"))
               or (not x["ok"] and not x["url"] and x["note"])
               for x in c.values())
    assert "flight.qunar.com/site/" in c[("qunar", "pc", "domestic")]["url"]
    assert "market.m.taobao.com" in c[("fliggy", "h5", "domestic")]["url"]
    # r413：同程 H5 国际此前配的是**国内页** ft/touch/index（实测正文
    # 「国内 国际 往返 特价机票」、默认上海→北京），点国际入口落国内页。
    # 真实国际入口是 tiflight/book1.html（带参会 302 passport 登录）。
    assert "m.ly.com/tiflight/book1.html" in c[("tongcheng", "h5", "intl")]["url"]
    assert "需登录" in c[("tongcheng", "h5", "intl")]["note"]
    # 飞猪 H5 没有国内入口，进入即淘宝登录——文案必须这么说
    assert "淘宝登录" in c[("fliggy", "h5", "domestic")]["note"]
    assert "淘宝登录" in c[("fliggy", "h5", "intl")]["note"]
    assert "flight.tuniu.com/intel" in c[("tuniu", "pc", "intl")]["url"]
    # 固定入口优先落到可输入航线/日期的搜索页，而不是首页。
    assert "/html5/flight/" in c[("ctrip", "h5", "domestic")]["url"]
    assert "/jipiao/" in c[("fliggy", "pc", "domestic")]["url"]
    assert "/jipiao/" in c[("fliggy", "pc", "intl")]["url"]
    assert "/flights/home" in c[("tongcheng", "pc", "domestic")]["url"]
    assert "/ft/touch/index" in c[("tongcheng", "h5", "domestic")]["url"]
    assert "intlFlight/flight/" in c[("tuniu", "h5", "intl")]["url"]
    assert "/h5/flight/" in c[("qunar", "h5", "intl")]["url"]


def test_domestic_route_links_pc_h5_for_each_channel():
    from core.channel_links import channel_links
    r = channel_links("SHA", "PEK", "2026-10-26", "上海", "北京")
    assert r["mode"] == "route" and r["scope"] == "domestic"
    c = _cells(r)
    assert "oneway-sha-pek" in c[("ctrip", "pc", "domestic")]["url"]
    assert "depdate=2026-10-26" in c[("ctrip", "pc", "domestic")]["url"]
    assert "from=inner" in c[("ctrip", "h5", "domestic")]["url"]
    assert "ddate=2026-10-26" in c[("ctrip", "h5", "domestic")]["url"]
    assert "m.flight.qunar.com" in c[("qunar", "h5", "domestic")]["url"]
    assert "sjipiao.fliggy.com" in c[("fliggy", "pc", "domestic")]["url"]
    assert "m.ly.com/ft/touch/book1" in c[("tongcheng", "h5", "domestic")]["url"]
    assert "flight.tuniu.com/domestic/list" in c[("tuniu", "pc", "domestic")]["url"]
    assert "m.tuniu.com/flight/domestic/new" in c[("tuniu", "h5", "domestic")]["url"]
    # 非当前 scope 只给入口，不拿国内航线伪造国际链接。
    assert "其他范围" in c[("ctrip", "pc", "intl")]["note"]


def test_intl_route_links_pc_h5_for_each_channel():
    from core.channel_links import channel_links
    r = channel_links("SHA", "KIX", "2026-10-25", "上海", "大阪")
    assert r["mode"] == "route" and r["scope"] == "intl"
    c = _cells(r)
    assert "oneway-" in c[("ctrip", "pc", "intl")]["url"]
    assert "depdate=2026-10-25" in c[("ctrip", "pc", "intl")]["url"]
    assert "from=outer" in c[("ctrip", "h5", "intl")]["url"]
    assert "touch.qunar.com/ncs/page/interlist" in c[("qunar", "h5", "intl")]["url"]
    assert "sijipiao.fliggy.com/ie" in c[("fliggy", "pc", "intl")]["url"]
    assert "tiflight/book1.html" in c[("tongcheng", "h5", "intl")]["url"]  # 有航线/日期时才走 book1
    assert "m2015/intlFlight" in c[("tuniu", "h5", "intl")]["url"]
    assert "其他范围" in c[("ctrip", "pc", "domestic")]["note"]


def test_qunar_pc_real_site_address_is_kept():
    from core.channel_links import channel_links
    r = channel_links("SHA", "PEK", "2026-10-26", "上海", "北京")
    c = _cells(r)
    for sc in ("domestic", "intl"):
        cell = c[("qunar", "pc", sc)]
        assert cell["ok"] is True
        assert "flight.qunar.com/site" in cell["url"]


def test_special_fare_entries_per_channel():
    from core.channel_links import channel_links
    r = channel_links()
    sp = {(x["plat"], x["surface"]): x for x in r["specials"]}
    assert len(sp) == 10
    assert "fuzzysearch" in sp[("ctrip", "pc")]["url"]
    assert "jipiao" in sp[("fliggy", "pc")]["url"]
    assert "无独立入口" in sp[("fliggy", "pc")]["note"]
    assert "无独立入口" in sp[("fliggy", "h5")]["note"]
    assert "thflight" in sp[("tongcheng", "pc")]["url"]
    assert "cheapflights" in sp[("tongcheng", "h5")]["url"]
    assert "lowFlight" in sp[("qunar", "h5")]["url"]
    assert sp[("tuniu", "pc")]["ok"] is False
    assert sp[("tuniu", "h5")]["ok"] is False
    assert sp[("qunar", "pc")]["ok"] is False


def test_missing_names_and_partial_route_fall_back_to_entry():
    from core.channel_links import channel_links
    r = channel_links("SHA", "PEK", "", "", "")
    assert r["mode"] == "entry" and len(r["cells"]) == 20


def test_channel_login_metadata_separates_session_and_page():
    """全渠道统一「必须登录」；会话(采集端)与页面(入口)两层仍分开。

    2026-10-27 政策：不再有「建议登录」这种模糊档位。凡是标了登录要求的
    入口一律 required；飞猪 PC/H5 因两个域、会话不共享而分别标注。
    """
    from core.channel_links import channel_links
    r = channel_links()
    ch = {x["plat"]: x for x in r["channels"]}
    assert set(ch) == {"ctrip", "qunar", "fliggy", "tongcheng", "tuniu"}
    # 五家全部 required
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert ch[p]["session"] == "required", (p, ch[p]["session"])
        assert "必须登录" in ch[p]["session_label"], (p, ch[p]["session_label"])
    assert "双端登录" in ch["fliggy"]["login_note"]
    assert "会话不共享" in ch["fliggy"]["login_note"]

    c = _cells(r)
    # 飞猪 PC / H5 都要求登录（两个域，各自登录）
    for sfc in ("pc", "h5"):
        assert c[("fliggy", sfc, "domestic")]["login"] == "淘宝账号", sfc
        assert c[("fliggy", sfc, "domestic")]["login_required"] is True, sfc
    # 单槽渠道的 PC 入口同样标出登录要求
    assert c[("ctrip", "pc", "domestic")]["login_required"] is True
    assert c[("tongcheng", "pc", "intl")]["login_required"] is True
    assert c[("tuniu", "pc", "intl")]["login"] == "登录"
    assert c[("tuniu", "pc", "intl")]["login_required"] is True
    assert c[("qunar", "h5", "domestic")]["login"] == "登录后出价"

    sp = {(x["plat"], x["surface"]): x for x in r["specials"]}
    assert sp[("fliggy", "h5")]["login"] == "淘宝账号"
    assert sp[("fliggy", "h5")]["login_required"] is True

def test_channel_board_renderer_replaces_flat_grid():
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    for needle in ("chboard", "chband", "chlink", "chdot",
                   "页面登录", "srxSpecialEntryHTML"):
        assert needle in src, needle
    links_src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "core", "channel_links.py"), encoding="utf-8").read()
    assert "必须登录" in links_src
    # 2026-10-27 起全渠道统一「必须登录」——数据层（SESSION_REQUIREMENT）
    # 不得再出现 suggested 档位；飞猪双域事实改由 note 说明。
    from core.channel_links import SESSION_REQUIREMENT
    for _p, (_lv, _lb) in SESSION_REQUIREMENT.items():
        assert _lv == "required", (_p, _lv)
        assert "必须登录" in _lb, (_p, _lb)
    assert "会话不共享" in links_src
    # 这两条禁的是「用户可见文案」：曾把采集口径写成「采集免登 / 采集必须」
    # 与登录要求打架。注释里出现同字（如「探针与定时采集必须拿到同一份
    # android 段」）不是文案，不能算违规——先剥注释再断言，否则守卫会把
    # 任何一句含该四字的说明判红（r630 实测）。
    import re as _re
    ui = _re.sub(r"/\*.*?\*/", "", src, flags=_re.S)
    ui = _re.sub(r"(?m)^\s*#.*$", "", ui)
    ui = _re.sub(r"(?m)//.*$", "", ui)
    assert "采集免登" not in ui
    assert "采集必须" not in ui
    assert 'class="chlgrid' not in src


def test_endpoint_and_ui_wiring():
    import inspect
    import webui
    src = inspect.getsource(webui._Handler.do_GET)
    assert "/api/channel-links" in src
    assert "channel_links as _chlinks" in src
    page = webui.PAGE
    for needle in ("cfgChannelLinks", "srxChLinks", "srxChLinksLoad",
                   "chboard", "chband", "chlink"):
        assert needle in page, needle
