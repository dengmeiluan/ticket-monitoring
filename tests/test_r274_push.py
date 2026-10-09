# -*- coding: utf-8 -*-
"""r274 推送面 P-A 案钉面（TDD：goal_r274_push.md 审校候选 A 三面并案）：

A1 LAY_SHORT 跨端同值——report.py LAY_SHORT 与 webui.py --stl 恢复
   同值 (168,76,21)：webui 端已完成 AA 换值（对 card 5.66/斑马 5.34/
   达标行底 5.25 全过 4.5）而 report 端停在与擦边琥珀分色时的旧值，
   「两处同值同注释纪律」的注释承诺与实现脱钩。跨端对账钉直接解析
   webui PAGE 的 --stl 值与 DESIGN.LAY_SHORT 互证，防单端改色。
A2 总表图例首行衔接词条按「表内数据可达性」条件化——数据流双滤网
   （告警链 top_transfers 与日报链 _split_market_pool 均要求
   layoverM ≥ lay_min 才入池）使 LAY_SHORT 着色在推送 PNG 不可达，
   「橙红=衔接不足」词条解释图面上不存在的颜色；词条只解释图上
   真实存在的颜色（图例-数据一致性）：
   - lay_min=0：停时恒中性灰（无警示语义），词条给灰态解码；
   - lay_min>0 且表内全部中转行过衔接滤网：只挂绿词条；
   - lay_min>0 且短衔接行在场（防御位被激活）：双词条全形态。
A3 LAY_SHORT 着色分支保留为防御位——上游滤网若放宽即回归，不改
   判定逻辑（禁删除钉）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r274_push.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402  # --stl 跨端对账锚
import report  # noqa: E402

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "report.py"), encoding="utf-8").read()


# ---------- A1: LAY_SHORT 跨端同值 ----------

def test_lay_short_matches_webui_stl():
    m = re.search(r"--stl:#([0-9a-fA-F]{6})", webui.PAGE)
    assert m, "webui PAGE 找不到 --stl 令牌"
    stl = tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    assert report.DESIGN.LAY_SHORT == (168, 76, 21), \
        "LAY_SHORT 未对齐 webui 已 AA 量测值 (168,76,21)"
    assert report.DESIGN.LAY_SHORT == stl, \
        f"report LAY_SHORT {report.DESIGN.LAY_SHORT} 与 webui --stl {stl} 跨端失值"


# ---------- A2: 图例衔接词条条件化 ----------

def test_layover_legend_word_conditional():
    w = report._layover_legend_word
    # lay_min=0：灰态解码（停时恒 MUTED 灰，两色词条均不可现）
    assert w([], 0) == "停时=衔接时长（未设下限）"
    assert w([("transfer", [{"layoverM": 120}])], 0) == "停时=衔接时长（未设下限）"
    # lay_min>0 且表内全部中转行过衔接滤网：只挂绿词条
    assert w([("transfer", [{"layoverM": 90}, {"layoverM": 300}])], 90) \
        == "绿停时=衔接达标"
    # 直飞组/compare 组不参与判定
    assert w([("direct", [{"price": 1000}]), ("compare", ["旧式串", {"a": 1}])], 90) \
        == "绿停时=衔接达标"
    # 短衔接行在场（防御位激活）：双词条全形态
    assert w([("transfer", [{"layoverM": 90}, {"layoverM": 30}])], 90) \
        == "橙红=衔接不足 · 绿停时=衔接达标"
    # layoverM 缺席按 0 计（缺键行视作最保守）
    assert w([("transfer", [{}])], 90) == "橙红=衔接不足 · 绿停时=衔接达标"


def test_layover_legend_wired():
    assert "_layover_legend_word(rows, lay_min)" in SRC, \
        "总表图例首行未接线条件化词条函数"


# ---------- A3: LAY_SHORT 着色防御位保留 ----------

def test_lay_short_branch_preserved():
    assert ("(C_QUAL if (f.get(\"layoverM\") or 0) >= lay_min\n"
            "                      else DESIGN.LAY_SHORT) if lay_min > 0 else DESIGN.MUTED") \
        in SRC, "LAY_SHORT 着色防御位被移除（上游滤网放宽时无警示着色）"
