# -*- coding: utf-8 -*-
"""r292 登录轮询视图生命周期源码钉。

P2-1：switchView 进配置视图且停登录分区时必须拉起轮询——lgWatchStart
的启动点只在 showCfgPanel 尾挂，而 switchView('cfg') 停在默认登录分区
（进配置页最常见路径，含 URL 深链）不经过 showCfgPanel，30s 轮询永不
启动，「采集退绿页面自动跟上」在主路径落空。
P3-1：轮询停点收口 lgWatchStop 单源——interval 自灭分支与视图出口同走
一个停点；switchView 切回监控视图必须停表（登录卡注释「切走即停零常
驻」的承诺在视图出口兑现）。
钉面锁唯一行为承载串，窗口锚到块界（下一函数名）防注释增厚假红。
"""
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "webui.py"
src = SRC.read_text(encoding="utf-8")


def _switch_body():
    i = src.index("function switchView")
    j = src.index("async function loadLogin")
    return src[i:j]


def _watch_body():
    i = src.index("function lgWatchStart")
    j = src.index("async function loginStart")
    return src[i:j]


def test_switchview_starts_login_watch_on_cfg_login():
    assert "if(v==='cfg'&&CFGPANEL==='login')lgWatchStart();" in _switch_body(), \
        "switchView 进配置视图停登录分区未拉起登录轮询（P2-1 主路径缺口）"


def test_switchview_stops_login_watch_leaving_cfg():
    assert "lgWatchStop();" in _switch_body(), \
        "switchView 切回监控视图未停登录轮询（跨视图常驻）"


def test_lgwatchstop_single_source():
    assert "function lgWatchStop(){if(LGTIMER){clearInterval(LGTIMER);LGTIMER='';}}" in src, \
        "lgWatchStop 单源停点缺席"
    assert "else lgWatchStop();" in _watch_body(), \
        "interval 自灭分支未走 lgWatchStop 单源（停点分叉）"
