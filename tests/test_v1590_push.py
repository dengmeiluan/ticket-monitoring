# -*- coding: utf-8 -*-
"""推送层 v1590 批回归（E 路审校 P2×3 落地）：

- P2-3 走势环档位收编 _tier_of 单源：report 走势环内联重演
  「2/1/-1/0」结构是 _tier_of 的第 4 副本（加档必漏家族）——收编后
  环色/线宽/擦边带与日历/价格色/空心判定同源（环段入口 `if th_v:`
  守卫保证 th>0，与 _tier_of 的 th 防御语义等价，行为不变）。
- E-1 ⚠ tofu：明细总表图 agePolicy 徽标「⚠限青年价」的 U+26A0 在
  msyh 无字形，PNG 实渲染 tofu 方框（webui 浏览器端有字形保留 ⚠，
  仅 PNG 端去符——词面自带「限」字醒目）。
- E-2 labels 族入总表图：经济舱售罄/含免费托运/老客专享等决策词
  走 labels 既有键，此前推送图零落位（qunar/tongcheng 托运额走
  baggage 键入图——同图比价行李词面不对等在 labels 槽补齐）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1590_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(_BASE, "report.py"), encoding="utf-8").read()


def test_trend_ring_tier_via_tier_of():
    """P2-3：走势环档位判定走 _tier_of 单源（第 4 副本收编）。"""
    src = _src()
    assert "tier = _tier_of(v, th_v, qual)" in src, \
        "走势环档位未走 _tier_of 单源"
    assert "tier = 2 if qual else 1" not in src, \
        "内联档位重演残留（加档必漏家族）"


def test_age_policy_png_no_warning_sign():
    """E-1：PNG 端 agePolicy 徽标去 ⚠（msyh 无 U+26A0 字形渲染 tofu）；
    词面「限X价」本体保留。"""
    src = _src()
    assert "⚠{f['agePolicy']}" not in src, "PNG 端 ⚠ 残留（tofu 方框）"
    assert "{f['agePolicy']}价" in src, "agePolicy 词面徽标缺失"


def test_labels_slot_in_table_png():
    """E-2：labels 族入总表图次行（售罄/含免费托运/老客专享决策词）。"""
    src = _src()
    assert '("labels", str(f.get("labels") or "").strip())' in src, \
        "labels 槽未入图"


def test_drop_chain_last_tier_drops_labels_age():
    """M-1：超宽极端行 labels/age 入末档丢档链——二者串长恒占槽
    （labels 可 15+ 全角/age 至 10 全角）且不在既有五档 drop 序列，
    五档全败则 plan=None 回退单行整截，恒保组（准点/餐食/托运/
    共享/余票）一并蒸发；末档丢增益词保恒保组，次行仍可决策。"""
    seg = _src().split("丢档/缩档链")[1].split("if plan is None")[0]
    assert '"labels"' in seg, "丢档链末档未含 labels（超宽行恒保组被整截）"
    assert '"age"' in seg, "丢档链末档未含 age"
