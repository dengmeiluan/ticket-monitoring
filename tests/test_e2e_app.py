# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r614_app_channel_name_in_cards.py
- tests/test_r653_app_has_no_proxy_control_but_says_why.py
- tests/test_r730_app_login_controls.py
- tests/test_r805am_app_filter_works.py
- tests/test_r805ap_app_screen_switch.py
- tests/test_r918_app_android_visible_hint.py
- tests/test_r941_app_chip_quality.py

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
import socket
import subprocess
import sys
import time
import urllib.request

from entry_mon_harness import _goto, page, srv


# ---- merged from tests/test_r614_app_channel_name_in_cards.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_both_cn_tables_merge_app_plat_name():
    w = _w()
    assert w.count("Object.assign({") >= 2
    assert "'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程'" in w
    # 两张表都必须并入 APP_PLAT_NAME（只并一张，另一张仍显示原始 id）
    # 至少 2 处（健康卡 + 节流面板）。r615 又并了第三张（PCN），
    # 所以这里写 >= 而非 ==（写死数量会在新增名表时假红）。
    assert w.count("(typeof APP_PLAT_NAME!=='undefined')?APP_PLAT_NAME:{}") >= 2, (
        "健康卡与节流面板的名字表没有都并入 APP_PLAT_NAME（实际 %d 处）"
        % w.count("(typeof APP_PLAT_NAME!=='undefined')?APP_PLAT_NAME:{}"))


def test_app_plat_name_is_the_single_source():
    w = _w()
    i = w.index("const APP_PLAT_NAME=")
    seg = w[i:i + 120]
    assert "app_zhixing" in seg and "智行" in seg, seg




# ---- merged from tests/test_r653_app_has_no_proxy_control_but_says_why.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BROWSER = {"qunar", "fliggy", "ctrip", "tongcheng", "tuniu"}








# ---- merged from tests/test_r730_app_login_controls.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return webui_full_src()


def test_modal_has_back_and_home_buttons():
    src = _src()
    assert "onclick=\"appLoginKey(\\'KEYCODE_BACK\\')\"" in src, (
        "内嵌登录没有「返回」按钮：App 停在子页时只能关窗重来")
    assert "onclick=\"appLoginKey(\\'KEYCODE_HOME\\')\"" in src, (
        "内嵌登录没有「桌面」按钮")


def test_modal_renders_channel_switch_bar():
    src = _src()
    assert "function appLoginSwitchHTML(" in src
    assert "function appLoginSwitch(" in src
    assert "appLoginSwitchHTML(plat)" in src, (
        "切换条没有被插进弹窗 HTML")


def test_switch_reopens_modal_for_target_plaform():
    """切渠道必须重开弹窗（标题/画面/选中态一起换），并先停帧轮询。"""
    src = _src()
    i = src.index("function appLoginSwitch(")
    body = src[i:i + 420]
    assert "appLoginStop()" in body, "切渠道前没停掉上一家的帧轮询"
    assert "appLoginOpen(plat)" in body, "切渠道没有重开弹窗"


def test_switch_bar_lists_every_app_channel():
    """切换项不能写死两家——从 APP_PLAT_NAME 派生，新增 App 自动出现。"""
    src = _src()
    i = src.index("function appLoginSwitchHTML(")
    body = src[i:i + 700]
    assert "APP_PLAT_NAME" in body, "切换项写死了渠道名，新增 App 不会出现"
    assert "Object.keys(M)" in body




# ---- merged from tests/test_r805am_app_filter_works.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)




# ---- merged from tests/test_r805ap_app_screen_switch.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)




# ---- merged from tests/test_r918_app_android_visible_hint.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)




# ---- merged from tests/test_r941_app_chip_quality.py ----

def _open_search(page):
    _goto(page, "#search")
    page.evaluate(
        "()=>{const p=document.getElementById('srxProbe');"
        "if(p)p.classList.add('open');"
        "const d=document.getElementById('srxPlatDD');if(d)d.open=true;}")
    page.wait_for_selector(
        '#srxPlatPick .srx-pchip-ic[data-p="app_zhixing"] img.bic',
        timeout=15000)
    page.wait_for_timeout(300)




