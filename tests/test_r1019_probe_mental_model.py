# -*- coding: utf-8 -*-
"""r1019：探针开合钮必须属于它控制的探针（在探针上方、同源多态文案），
不能在收起后留一条控制上一块的常驻条。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_probe_toggle_sits_above_and_controls_the_probe():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    probe = src.index('<section class="srx-probe open" id="srxProbe"')
    # 触发器在探针之前的 hero 工具行里
    btn = src.index('id="srxProbeTool"')
    assert btn < probe
    assert 'aria-controls="srxProbe"' in src[btn:probe]
    # 两态同源文案：主动探针 / 收起探针
    assert ("const t=pt.querySelector('.srx-ptxt');"
            "if(t)t.textContent=on?'收起探针':'主动探针';") in src
    # 收起态不渲染表单与状态，卡片整体不占位（实测高度 0）
    assert "#searchview .srx-probe:not(.open) .srx-probeform" in src
    assert "#searchview .srx-probe:not(.open) .srx-probestatus" in src
