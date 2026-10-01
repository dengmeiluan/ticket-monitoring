# -*- coding: utf-8 -*-
"""r254 WebUI 四案（审计报告 r254_webui_audit.md 收编）：

W1 吸顶条右端用户切换 chip（P2-1）——多用户入口只驻留页顶 opscard，
深滚明细/走势后切换须长滚回顶；montabs 两级吸顶的第二级右端加紧凑
chip（复用 pickUser 单源 + userPills 同拍同步），深滚自救零长滚。

W2 脉冲柱跳转带状态落地（P2-2）——柱点击原为「跳到区域」非「跳到
目标」：落地健康 tab 顶后对应轮次可能挤出 96 格窗口视野。改带
gotoPulseHealth(ts,fails)：失败渠道 .hrow 临时辉光（class 切换零
childList 变更，扩展免疫）+ 该轮时间片横滚居中定位。

W4 桌面窄窗 fine-pointer .hcells 横滚无滚轮通道（P3-3）——
overflow-x:auto 容器在无Shift惯例的桌面窄窗只能拖滚动条；容器级
wheel 转写（target 在横滚容器内且可滚时 deltaY→scrollLeft，无竖滚
空间冲突）补齐滚轮通道。

W5 预览推送 ~27s 慢路径静默 busy（P3-4）——previewPush 长请求期
间按钮无反馈可重复点；busy 词面 + disabled 同 api() 守卫族。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r254_webui.py
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- W1: montabs 右端用户切换 chip ----------

def test_w1_mtabuser_chip_present():
    src = _page_src()
    assert 'id="mtabUser"' in src, "montabs 右端缺用户切换 chip 元素"
    assert "function mtabUserNext" in src, "缺循环切换函数"
    assert "pickUser((U+1)" in src or "pickUser((U + 1)" in src, \
        "循环切换必须复用 pickUser 单源（选中态与 userPills 同拍）"


def test_w1_mtabuser_sync_with_userpills():
    """chip 与 userPills 同拍同步：多用户显示+名字刷新，单用户隐藏。"""
    src = _page_src()
    i0 = src.index("mtabUserSync()")
    seg = src[max(0, i0 - 1200):i0 + 1200]
    assert "mtabUserSync" in src, "缺同步函数调用"
    assert "us.length<2" in seg or "us.length < 2" in seg or \
        "length>1" in seg.replace(" ", ""), "同步必须按用户数切换显隐"


def test_w1_mtabuser_touch_floor():
    """触控 36px 地板族（十四§4）：uchip 声明在触控增强媒体块内。"""
    src = _page_src()
    assert ".tabs .uchip" in src or "#montabs .uchip" in src, \
        "uchip 缺触控地板声明"


# ---------- W2: 脉冲柱带状态落地 ----------

def test_w2_pulse_goto_has_target():
    src = _page_src()
    assert "gotoPulseHealth(" in src, "脉冲柱缺带态落地入口"
    # 旧「裸跳区域」形态退役：柱模板不得再直连 gotoMonTab('health')
    for m in (_src_iter(src, "onclick=\"gotoMonTab('health')\"")):
        pytest.fail(f"柱仍裸跳健康 tab（无定向）: 位置 {m}")
    assert "gotoMonTab('health')" in src, "健康 tab 本体入口仍需保留"


def _src_iter(src, needle):
    out = []
    i = 0
    while True:
        i = src.find(needle, i)
        if i < 0:
            return out
        out.append(i)
        i += 1


def test_w2_hflash_class_and_glow():
    src = _page_src()
    assert "hflash" in src, "缺失败渠道辉光类"
    assert "scrollLeft" in src[_src_iter(src, "function gotoPulseHealth")[0]:
                               _src_iter(src, "function gotoPulseHealth")[0] + 1600], \
        "带态落地须横滚定位该轮时间片"


# ---------- W4: .hcells 桌面滚轮通道 ----------

def test_w4_hcells_wheel_channel():
    src = _page_src()
    assert "hcellsWheel" in src or ("wheel" in src and ".hcells" in src), \
        "缺 .hcells 滚轮转写通道"


# ---------- W6: 矮窗 canvas 比例档（审计 P3-6） ----------

def test_w6_short_viewport_canvas_tier():
    """矮窗（max-height:600px）桌面带 canvas 收一档：r236 取大语义下
    宽短窗 28vw 主导（1280×540 → 358px，占视口 66%），基础档下限
    240px 也远超矮窗预算——置尾媒体块 clamp(200px,34vh,280px)，
    层叠序须胜过基础档（L267）与 ≥1920 档（42vh）。uitest 视口高
    全 ≥844 不触发，行为面零扰动（源码钉锁结构事实）。"""
    src = _page_src()
    i0 = src.index("@media(max-height:600px) and (min-width:761px)")
    assert "canvas{height:clamp(200px,34vh,280px)}" in src[i0:i0 + 200], \
        "矮窗档缺 clamp 声明"
    assert i0 > src.index("height:clamp(240px,max(38vh,28vw),360px)"), \
        "矮窗档必须置尾于基础档后（层叠序，LESSONS 二十一§1）"
    assert i0 > src.index("clamp(280px,42vh,460px)"), \
        "矮窗档必须置尾于 ≥1920 档后（矮窗优先级正确）"


# ---------- W5: previewPush busy 反馈 ----------

def test_w5_preview_busy_feedback():
    src = _page_src()
    i0 = src.index("async function previewPush")
    body = src[i0:src.index("\nasync function", i0 + 10)] \
        if "\nasync function" in src[i0 + 10:] else src[i0:i0 + 3000]
    assert "pvBtn" in body, "预览函数未挂 busy 反馈面（按钮原地）"
    assert "disabled" in body or "busy" in body, "慢路径缺 busy/disabled 反馈"
