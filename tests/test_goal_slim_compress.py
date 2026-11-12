# -*- coding: utf-8 -*-
"""goal 轮 slim 链双价超宽域：死档判据归档钉。

审校建议（补「双裸价压缩档」保中转行情判据）经真实计宽演算证伪为
数学死档：双价并存的压缩词面下限 17 半角恒 > keep-direct 单价段
11 半角——keep-direct 超宽的域压缩档必超，无可达域（卅一§5：插入
档前先演算既有档合规性；三§46：变异不红的直落钉=死档信号）。

归档两面：
- 行为钉：双价超宽域（8 CJK 对）落 keep-direct 或 bare、恒达标律
  不破——中转价文本侧缺席=数学边界，总表图承接（审校备案）；
- 禁复活钉：压缩词面不得回链（死档论证在 alerter slim 链注释，
  词面字面零残留计数）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_goal_slim_compress.py -q
"""
import logging as _lg
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw  # noqa: E402
from core.models import Route as _R  # noqa: E402


def _dual_sections():
    return [{"date": "2026-09-25",
             "best_direct": {"price": 1950, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"},
             "best_transfer": None,
             "best_transfer_mkt": {"price": 2050, "name": "CZ6976转",
                                   "transCity": "郑州",
                                   "_platform": "ctrip"},
             "seen_plats": ["qunar", "ctrip"]}]


def _slim_desp(route):
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    return a._digest_payload([(route, _dual_sections())], fresh=False,
                             with_tables=False, with_charts=False)["desp"]


def test_slim_dual_price_overwide_domain_lands_within_budget():
    """双价超宽域（8 CJK 对）：keep-direct 41/40 超 → 链落 bare，
    行宽恒达标；上档合规域（短 OD）价格判据照常存活（零回归）。"""
    route = _R(from_code="HHC", to_code="BNM", from_name="呼和浩特",
               to_name="西双版纳", dates=["2026-09-25"],
               alert_direct=1900, alert_transfer=1700)
    desp = _slim_desp(route)
    rows = [ln for ln in desp.splitlines() if ln.startswith("> 呼和浩特")]
    assert rows, desp[:600]
    assert _disp_dw(rows[0]) <= 40, rows[0]
    # 短 OD（2 CJK 对）域 keep-direct 合规：价格判据存活零回归
    route2 = _R(from_code="SHA", to_code="HAK", from_name="上海",
                to_name="海口", dates=["2026-09-25"],
                alert_direct=1900, alert_transfer=1700)
    desp2 = _slim_desp(route2)
    rows2 = [ln for ln in desp2.splitlines() if ln.startswith("> 上海")]
    assert rows2 and "直飞 ￥1950" in rows2[0], rows2


def test_slim_dual_price_compress_facet_banned_from_chain():
    """禁复活：双价压缩词面不得回链（死档论证在案）。词面字面在
    alerter 源码零残留（注释指代式措辞，计数钉口径=整文件字符流）。"""
    src_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "alerter.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "直￥" not in src, (
        "双价压缩词面回链（死档：无可达域，论证见 alerter slim 链注释）")


def test_slim_floor_survives_longest_city_pair():
    """12 CJK 城市对（压缩档不可达域）：链落地板档，恒达标律不破。"""
    route = _R(from_code="ALQ", to_code="HQL", from_name="阿拉善左旗",
               to_name="塔什库尔干", dates=["2026-09-25"],
               alert_direct=1900, alert_transfer=1700)
    desp = _slim_desp(route)
    rows = [ln for ln in desp.splitlines() if ln.startswith("> 阿拉善左旗")]
    assert rows, desp[:600]
    row = rows[0]
    assert _disp_dw(row) <= 40, "地板档超宽：%r (%.1f)" % (
        row, _disp_dw(row))
