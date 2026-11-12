# -*- coding: utf-8 -*-
"""推送审校落地钉：曲线吞环（P1-1）/ direct 空态词面（P2-1）/ 日报兜底图例（P2-2）。

P1-1：走势图「最低点让位」分支白描边 width=3 在小半径椭圆上外扩 ≈r9
物理，把底下 r5 档位环外缘吃得只剩 1 物理px、LANCZOS 缩回后归零——
恒档达标轮（环降密后唯一环点=首点，而达标价通常即最低价）必现吞环，
图例「●深绿=真达标」有例无点（生产实锤达标轮全图体区 C_QUAL 仅
4 像素）。修复：让位缩径 r1 蓝心复合（白描边外扩吞环根除）。

P2-1：明细总表 direct 组空态共用 _transfer_empty_note 中转归因词面，
「直飞最优」组头下印「该轮渠道未回中转班次」——空态词面按 kind 分派。

P2-2：日报图挂失败兜底分支的 emoji 档位 KPI（🎯/🟩）整条消息零图例
解释位（digest 侧 _legend_line 常驻托底，能力不对称）——兜底分支补
单源图例行。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r315_push.py -q
"""
import os

import report as _rep

_C_QUAL = _rep.C_QUAL          # (14, 131, 69) 达标绿
_BODY_Y0, _BODY_Y1 = 64, 400   # 图体区（顶部小注 <64、底部小注 >400 排除）


def _count_qual(path):
    """图体区达标绿像素计数（RGB 距离 ≤30 容差，抗 LANCZOS 扩散）。"""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    n = 0
    for y in range(_BODY_Y0, min(_BODY_Y1, h)):
        for x in range(w):
            r, g, b = px[x, y]
            if abs(r - _C_QUAL[0]) <= 30 and abs(g - _C_QUAL[1]) <= 30 \
                    and abs(b - _C_QUAL[2]) <= 30:
                n += 1
    return n


def _render(vals, qd, name, tmp_path):
    from datetime import datetime, timedelta
    t0 = datetime(2026, 10, 10, 8, 0, 0)
    ser = [(t0 + timedelta(minutes=30 * i), vals[i], None, qd[i], False)
           for i in range(len(vals))]
    out = str(tmp_path / name)
    _rep.render_chart(ser, "吞环对照", thresholds=(1800.0, 0.0), out_path=out)
    assert os.path.isfile(out)
    return out


def test_tier_ring_survives_minpoint_overlay(tmp_path):
    """恒档达标轮首点=最低点=环点形态：首环不得被最低点让位白描边
    吞没。对照法自校准——病灶图 A（最低点=首点=环点，首环被吞）与
    健康图 B（最低点在中间非环点，首末两环完整）同阈值同渲染管线，
    两图唯一差异=首环存亡；缺陷态 A 显著小于 B，修复后 A≈B。"""
    # A：递增恒达标（全部 <1800），首点 1749=最低价 → 首点=唯一入场
    # 环点+最低点（达标价通常即最低价的必现形态）
    vals_a = [1749, 1755, 1761, 1767, 1773, 1779, 1785, 1791, 1797]
    qa = [True] * 9
    # B：恒达标，最低点 1700 落中间 idx3（非环点，走常规大点分支，
    # 距首末环远不波及）
    vals_b = [1790, 1793, 1796, 1700, 1775, 1778, 1781, 1784, 1787]
    qb = [True] * 9
    green_a = _count_qual(_render(vals_a, qa, "ring_min_first.png", tmp_path))
    green_b = _count_qual(_render(vals_b, qb, "ring_min_mid.png", tmp_path))
    assert green_b >= 12, f"健康对照环基线不成立：B={green_b}"
    assert green_a >= green_b * 0.8, (
        f"达标轮首环被最低点让位白描边吞没：A={green_a} < B={green_b}×0.8")


# ---- P2-1 direct 组空态词面 ----------

def test_direct_group_empty_note_not_transfer_wording():
    """空态词面按 kind 分派单源：direct 组空态说「未回直飞班次」，
    不复用中转归因词面——「直飞最优」组头下印「未回中转班次」是词面
    与组语义颠倒（日报 directs 空+mkt 非空形态生产可达）。"""
    note = _rep._group_empty_note("direct", 0, None)
    assert "中转" not in note
    assert "直飞" in note


def test_direct_group_empty_note_skips_transfer_constraints():
    """direct 组即使带 meta（衔接下限/到达约束）也不拼中转判据段——
    「衔接≥N 分钟·02:00 前到达」对直飞组是错位约束词面。"""
    note = _rep._group_empty_note("direct", 90, "02:00")
    assert "衔接" not in note and "到达" not in note
    assert "直飞" in note


def test_transfer_group_empty_note_unchanged():
    """transfer 组空态三档词面原样（r271 单源钉语义不丢）：双约束
    缺省归因渠道未回中转班次、带约束拼约束段。"""
    assert "中转" in _rep._group_empty_note("transfer", 0, None)
    note = _rep._group_empty_note("transfer", 90, "02:00")
    assert "衔接≥90 分钟" in note and "02:00 前到达" in note


def test_empty_note_dispatch_wired_in_table_render():
    """源码钉：明细总表空态分支经 kind 分派单源取词——共用
    _transfer_empty_note 直调（无 kind 门）的旧形态不得复活。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "_group_empty_note(kind, lay_min, meta.get(\"arrival_max\"))" in src


# ---- P2-2 日报兜底分支图例（RED 先行）----------

def test_daily_fallback_keeps_tier_legend():
    """日报图挂失败兜底分支的 emoji 档位 KPI 必须带图例解释位（复用
    digest 侧 _legend_line 单源，勿另写第二份图例词面）——图例已撤入
    图的常态下，兜底轮 🎯/🟩 整条消息零解释是「可出手/未必可出手」
    决策级失语（能力对称三十§3：digest 常驻托底、日报缺位）。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    # 锚=调用点字面（图例行紧贴 _kpi_fallback 的段落拼接形态），
    # 两路兜底（上传失败/生成失败）各一；不锁「def 到调用点」的字符
    # 窗口——两定义点间合法增厚（嵌套兜底函数族）会把窗口撑爆假红
    # （窗口钉判例：窗口是实现细节，锚结构才是钉面）；锚不含行首缩进
    # （两分支嵌套深度不同，带缩进锚必假红）
    assert src.count('Alerter._legend_line() + "\\n\\n"') == 2

