# -*- coding: utf-8 -*-
"""r1063 T70：校准途牛 PC 登录/接管窗口的地址。

用户实测：点途牛的 **PC** 登录，弹出来的却是 **H5** 的地址 `https://m.tuniu.com/`。

根因：`webui._probe_takeover_url()` 优先用 `Alerter._build_view_url()`，而它给途牛
返回的是"查看详情"用的 H5 深链（`m.tuniu.com/flight/domestic/new/…`）。
查看详情深链 ≠ 登录入口——两件事被混用了。

校准后口径：
* 途牛 PC = `https://flight.tuniu.com/`
* 途牛 H5 = `https://m.tuniu.com/flight/`
"""
import io
import os

import webui
from core.channel_links import LOGIN_ENTRY, login_entry_url

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
