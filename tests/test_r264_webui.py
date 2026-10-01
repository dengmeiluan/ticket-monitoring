# -*- coding: utf-8 -*-
"""WebUI 三案（波2 WebUI 审计立案 P3×3）：

U1 .switch 悬停反馈：全站可点件悬停零反馈教义下的唯一漏网——
   全部 input hover 规则显式 :not(.switch) 排除，.switch 本体
   无任何 :hover 声明。补 brightness 提亮族（触屏无 hover 零
   副作用；filter 不与 checked 背景/::after 位移属性冲突）。

U2 savebar 实高动态单源 --sbh：配置页垫底（#cfgview
   padding-bottom 88/132px 两带固定校准）与 toast 抬升
   （body:has(.savebar.on) bottom 96/148px 两带固定校准）
   锚定的是「单行 40/双行 112」两个手分校准态——文本缩放
   150% 时双行实高可破 112（LESSONS 二十一§7 同族残留：
   固定值在内容变化处全带错位）。ResizeObserver 跟随折行
   实时写 --sbh，消费点全改 calc；JS 失效 fallback 保各带
   旧校准值零退化（固定覆写块随之退役）。

U3 best brief date 孤儿键：审计假案撤诉（LESSONS 十八§8
   现场复核）——「前端零读取」属实，但服务端顶层 delta 调用
   _delta_vs_prev(bd_brief, ..., (bd_brief or {}).get("date"))
   真实消费该键，非孤儿；v15110/v1559 两颗「必须带且被
   delta 消费」钉当场抓获本次误删，全量红即证据。键维持。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r264_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402  # 触发 PAGE 常量装配

PAGE = webui.PAGE


def test_switch_hover_affordance():
    """源码钉：.switch 悬停反馈声明在场（项目自判教义「真实
    可点件悬停零反馈属缺陷」下的唯一已知零反馈可点件）。"""
    assert ".switch:hover{" in PAGE, (
        ".switch 悬停反馈缺席：全站可点件悬停零反馈教义下的漏网")


def test_savebar_height_dynamic_single_source():
    """源码钉族：--sbh 动态单源三件套——JS 写入点（ResizeObserver
    观察 .savebar）、消费点（cfgview 垫底两带 calc + toast 抬升
    两带 calc）、旧固定校准退役（padding-bottom:88px/132px 固定
    形态与 bottom:96px/148px 固定形态零残留）。"""
    assert "--sbh" in PAGE, "--sbh 变量未落 PAGE"
    assert "querySelector('.savebar')" in PAGE, (
        "ResizeObserver 未观察 .savebar（--sbh 写入点缺席）")
    assert PAGE.count("setProperty('--sbh'") == 1, (
        "--sbh 写入点必须唯一（单源纪律）")
    assert PAGE.count("padding-bottom:calc(var(--sbh") == 2, (
        "cfgview 垫底消费点应为两带 calc（桌面+窄带），实得 %d"
        % PAGE.count("padding-bottom:calc(var(--sbh"))
    assert PAGE.count("body:has(.savebar.on) #toasts{bottom:calc(var(--sbh") == 2, (
        "toast 抬升消费点应为两带 calc（savebar 在场档），实得 %d"
        % PAGE.count("body:has(.savebar.on) #toasts{bottom:calc(var(--sbh"))
    # 旧固定校准退役钉：固定像素形态零残留（含媒体块内覆写）
    assert "padding-bottom:88px" not in PAGE and \
        "padding-bottom:132px" not in PAGE, (
        "cfgview 固定垫底校准残留：动态化后固定覆写块必须退役"
        "（保留=追不完的长尾，LESSONS 二十一§7）")
    assert "body:has(.savebar.on) #toasts{bottom:96px}}" not in PAGE and \
        "body:has(.savebar.on) #toasts{bottom:148px}}" not in PAGE, (
        "toast 固定抬升校准残留（savebar 在场档必须走 --sbh calc）")


def test_best_brief_date_key_still_consumed():
    """假案撤诉备案钉（LESSONS 十八§8）：brief["date"] 由顶层
    delta 调用真实消费（(bd_brief or {}).get("date")），非孤儿键——
    本轮审计曾按「前端零读取」误判为孤儿并误删，两颗「必须带且
    被 delta 消费」防退化钉当场抓获。本钉锁消费点在场，与
    v15110/v1559 钉共同构成三重防误删面。"""
    src = open("webui.py", encoding="utf-8").read()
    assert '"date": (f.get("depDate") or "")}' in src, (
        "best brief date 键缺席：delta 消费依赖该键（孤儿键定性"
        "是假案，勿再误删）")
    assert src.count('.get("date")') >= 2, (
        "delta 消费点（bd/xt brief .get(date)）缺席")
