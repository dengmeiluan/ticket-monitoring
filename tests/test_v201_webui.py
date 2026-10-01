# -*- coding: utf-8 -*-
"""WebUI 落地三案源码钉（审计 Minor×3）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from webui import PAGE


def test_v201_demo_foot_neutral():
    # demo 页脚语境中立（M-1）：「在线演示 · 静态合成数据」只对烘焙
    # 静态站为实——本地 --demo 是活服务进程（live HTTP+/api/state），
    # 双语境共用 s.demo 无区分位，统一改语境中立词面（双态皆实）。
    assert "演示模式 · 合成数据" in PAGE
    assert "在线演示 · 静态合成数据" not in PAGE


def test_v201_1920_kpi_widen():
    # ≥1920 档 .grid/.kpisum 放宽 1440（M-2）：--kpiw 1168 在 wrap
    # 1716 下卡内右侧 474px 空腔被放大（1440/1680 档同病灶仅 78px
    # 不可感）；每卡 ~703px 仍在可读带（815px 才入宽扁区），空腔
    # 收敛至 202。层叠律：放宽声明必须晚于 600 块 .grid 限宽声明
    # （同特异性后者胜，媒体块无「更严更后胜」——放前面会被无声盖回）。
    w600 = PAGE.index(".grid{grid-template-columns:repeat(2,minmax(0,1fr))")
    w1920 = PAGE.index(".grid,.kpisum{max-width:min(1440px,100%)}")
    assert w1920 > w600
    # 1920 块内脉冲侧全宽解锁仍在（statline 跟卡全宽不回缩）
    assert ".statline,#pulseLegend,.pulsewrap{max-width:none}" in PAGE


def test_v201_kline_narrow_offset():
    # K 线双系列偏移下限（M-3）：cw 触底 4px 时 ±0.62cw=±2.5px 偏移
    # 让两系列中心距 5px<目视分辨并成单列（390 档实测）；下限 4px
    # 保中心距 8px——仍 <pitch（桶序不交错）且环标互叠显著缓解。
    assert "Math.max(cw*0.62,4)" in PAGE
    # 系列偏移是单源 koff：蜡烛/环标/低标锚/避让计数全部消费点
    # 随 koff 迁移，裸 cw*0.62 只允许出现在 koff 定义行——
    # 半迁移会让窄档环标偏离所属蜡烛中心（同族漏迁判例）
    assert PAGE.count("cw*0.62") == 1, \
        "存在未随 koff 迁移的裸 cw*0.62 消费点（半迁移）"


def test_v201_near_hit_and_ghost_guard():
    # 触控横向热区近邻映射（审计 P2-1）：coarse 指针下容器捕获阶段
    # 按「点击 x 到动作格本体矩形的距离」最近邻重判命中——缝死区与
    # 邻格 ::after 吃缝的 off-by-one 一并收掉；双容器（健康格/脉冲
    # 柱）都挂载，桌面鼠标路径不经 coarse 分支零变化。
    assert "_nearHit('hbody','.hc')" in PAGE
    assert "_nearHit('pulsebars','.pbar')" in PAGE
    assert "matchMedia('(pointer:coarse)').matches" in PAGE
    # 幽灵坐标轴守卫（审计 P2-2）：阈值并入量纲源后 vals 恒非空，
    # 真实数据点为零时必须走空态文案（阈值不构成画图理由）
    assert ("if(!vals.length||!(K?CD.length+CT.length:hd.length+ht.length))"
            in PAGE)
    # 未扫描格光标语言跟动作语言（M-1）：none 格无点击动作，无假手型
    assert ".hc.none{cursor:default}" in PAGE
