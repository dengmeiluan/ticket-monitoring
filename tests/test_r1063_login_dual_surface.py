# -*- coding: utf-8 -*-
"""r1063 T82：**统一设计**——每家浏览器渠道双端固定登录（PC / H5 各一格）。

用户的诉求与现场：
* 「途牛和同程的弹窗登录现在默认全部到 H5 页面了，原来不是 PC 吗」——
  PC 端却弹 H5 地址，读作"弹错端"；
* 「要不然就跟飞猪一样，做双端固定登录，携程也是，统一设计算了」；
* 「去哪儿 H5 和 PC 均已正式停服」。

于是统一成 9 格（8 个在用的端 + 1 个停服说明位）：

| 槽位 | 端 | 登录入口 |
|---|---|---|
| ctrip | PC | passport.ctrip.com/user/login |
| ctrip_h5 | H5 | m.ctrip.com |
| fliggy | PC | www.fliggy.com |
| fliggy_h5 | H5 | market.m.taobao.com/… |
| tongcheng | PC | www.ly.com |
| tongcheng_h5 | H5 | m.ly.com |
| tuniu | PC | flight.tuniu.com |
| tuniu_h5 | H5 | m.tuniu.com/flight |
| qunar | 全端·已停服 | （停服说明位，数据走 app_qunar）|
"""
import io
import os

from core.channel_links import login_entry_url
from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER

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
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "for key in LOGIN_SLOT_ORDER:" in src
