# -*- coding: utf-8 -*-
"""r225 WebUI 两案回归（审计 P2-1/P2-2）：
W1 .stat .ssub 换行放行带 760→900（「用时」尾段 761-900 带截断残余，
同病灶带的原修复只覆盖到 ≤760）；
W2 K线 doji 单点桶实体高下限 1.5→3px（成排短横与达标红虚线撞形，
读图歧义——价格持平桶被误读为第二条阈值线）。

PAGE 为单文件内嵌 SPA，样式/绘图内嵌其中：源码钉 + 真机行为验证
（control-browser canvas 目检）双轨，与既有 vNNN webui 测试同口径。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v225_webui.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page():
    return open("webui.py", encoding="utf-8").read()


def test_ssub_wrap_gate_covers_761_900():
    """W1：换行放行媒体门覆盖 761-900 带。旧 ≤760 门是 391-509 修复
    上提时的同病灶残余带（768 实测 sw143/cw138 截断「用时 Ns」尾段）；
    基类 nowrap+ellipsis 在 >900 保持（宽屏单行形制不回退）。"""
    src = _page()
    assert "@media(max-width:900px){.stat .ssub{white-space:normal}}" in src
    assert "@media(max-width:760px){.stat .ssub{white-space:normal}}" not in src
    # 基类形制仍在（省略号语义 >900 档有效）
    assert ".stat .ssub{font-size:11px" in src
    assert "white-space:nowrap" in src.split(".stat .ssub{")[1][:200]


def test_kline_doji_min_body_height():
    """W2：doji 桶（开=收）实体高下限 3px——1.5px 短横成排后与达标
    红虚线同色同形，远看是第二条阈值线。空心/实心两分支同下限。"""
    src = _page()
    assert src.count("Math.max(3,yB-yT)") == 2, src.count("Math.max(3,yB-yT)")
    assert "Math.max(1.5,yB-yT)" not in src
