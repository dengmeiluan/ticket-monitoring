# -*- coding: utf-8 -*-
"""r274 WebUI 六案钉面（TDD：goal_r274_webui.md 审计立案，
断言串自源码 repr 逐字节复制）：

W1 NOTIFY 轻页 .foot a 基态去 UA 下划线（r273 P3-2 链接族姊妹
   漏网）：主站四族已收基态 none+hover 显形，轻页页脚链漏收。
W2 明细表衔接小字 lay_min=0 假警示收口——衔接下限=0（不限）时
   「停X」恒挂 .stl.lay 警示橙红=假信号（不存在「未达下限」），
   降级中性 .stl 灰，与 CSV 空串、推送 MUTED 灰三方对齐。
W3 空态阈值图例悬置——history 全空走空态早退时 lgZone/lgThD/lgThT
   三枚色票未清（阈值虚线不画而色票在场，装饰信号领先数据；
   r235 P2-1 收编过 lgDirect/lgTrans 同族，空态档阈值组漏网）。
W4 --green/--stl 补推送侧同值同步律注记（--warn↔C_NEAR 有先例
   注释，这两枚缺失——单端改色即跨端失配）。
W5 routechips 渠道片 ${p} 裸注入收口——innerHTML 文本位与
   onclick 属性内插双漏 he()，from_name 用户自由文本可断链；
   收口 data-r 属性 + dataset 取值（同 jumpRowTrend 形态）。
W6 .uname 字距独立档注释备案（15px 展示性大字距不入 --ls05 族，
   同 h1 品牌对语义）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r274_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402  # 触发 PAGE 常量装配

PAGE = webui.PAGE
NPAGE = webui.NOTIFY_PAGE


def _block(start_anchor, end_anchor):
    m = PAGE.index(start_anchor)
    return PAGE[m:PAGE.index(end_anchor, m + 10)]


# ---------- W1: NOTIFY 页脚链基态 ----------

def test_notify_foot_link_base_none():
    assert "border:none;background:none;text-decoration:none}" in NPAGE, \
        "NOTIFY .foot a 缺基态去下划线（UA 默认 underline 恒在）"
    # hover 显形档保留（基态收口不吞可供性反馈）
    assert ".foot a:hover{background:none;text-decoration:underline}" in NPAGE


# ---------- W2: lay_min=0 衔接小字中性灰 ----------

def test_lay0_row_neutral_class():
    assert ('<div class="${f.layMin>0?(\'stl lay\'+((+f.layoverM||0)>=f.layMin?\' ok\':\'\')):\'stl\'}"'
            in PAGE), "lay_min=0 时衔接小字未降级中性 .stl（假警示橙红恒挂）"
    # 禁复活：旧形态 class 属性无条件落 stl lay
    assert 'class="stl lay${(f.layMin>0&&' not in PAGE, \
        "衔接小字退回无条件 stl lay 形态"


def test_dark_qual_row_lay_ok_exempt_from_muted_lift():
    """暗色 qual 行 .stl 提亮灰 (0,3,2) 恒压 .stl.lay.ok (0,3,0)——
    衔接达标小字是 .ok 语义绿档非中性子行，须豁免（与推送 PNG
    达标行停时 C_QUAL 绿同语言）；真机实锤：demo 暗色 qual 行内
    「停X(ok)」computed 落 #8ba0b4 灰、非 qual 行同款为绿。"""
    assert "html[data-theme=\"dark\"] tr.qual .stl.lay.ok{color:var(--ok-txt)}" \
        in PAGE, "暗色 qual 行衔接达标小字缺提亮灰豁免（绿语义被压灰）"


# ---------- W3: 空态阈值图例隐藏 ----------

def test_empty_state_threshold_legend_hidden():
    body = _block("if(!vals.length||!(K?CD.length+CT.length:hd.length+ht.length)){",
                  "$('chartEmpty').style.display='none';")
    assert "$('lgZone').style.display='none'" in body, \
        "空态早退分支未隐藏 lgZone 色票"
    assert "$('lgThD').style.display='none'" in body, \
        "空态早退分支未隐藏 lgThD 色票"
    assert "$('lgThT').style.display='none'" in body, \
        "空态早退分支未隐藏 lgThT 色票"


# ---------- W4: 跨端同值同步律注记 ----------

def test_cross_channel_sync_notes():
    assert "--green:#0e8345;     /* 与推送图达标绿 C_QUAL 同值（跨端同色同义），改必双端同步（report.py） */" \
        in PAGE, "--green 缺 C_QUAL 同值同步律注记"
    assert "与推送图 LAY_SHORT 同值" in PAGE and "改必双端同步（report.py）" in PAGE, \
        "--stl 缺 LAY_SHORT 同值同步律注记"


# ---------- W5: routechips 注入收口 ----------

def test_routechips_escaped_injection():
    assert '" data-r="${he(p)}" onclick="togRoute(this)">' in PAGE, \
        "routechips 文本位/属性位未过 he() 收口"
    assert "function togRoute(el){const p=el.dataset.r;" in PAGE, \
        "togRoute 未改走 dataset.r 取值"
    # 禁复活：属性内裸内插形态
    assert "togRoute(this,'${p}')" not in PAGE, \
        "routechips onclick 属性退回裸内插"


# ---------- W6: .uname 字距备案 ----------

def test_uname_tracking_annotated():
    assert ".uname{font-size:15px;font-weight:700;letter-spacing:.3px}  /* 人名字距独立档：15px 展示性大字距不入 --ls05 族（同 h1 品牌对语义） */" \
        in PAGE, ".uname 字距独立档缺备案注释"
