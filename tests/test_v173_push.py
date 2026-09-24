# -*- coding: utf-8 -*-
"""推送回归：_fmt_brief 跨天注 × budget 形态钉。

 审校立案 P2×1（tests 侧，不改生产码）——test_v172_push 三夹具
均无 crossDayDesc 键，「跨天注 × budget 扣减」形态零覆盖：跨天行首档
带「（+1天达）」注比现有夹具宽 7 半角，是消费点预算压力最大形态
（行宽回归同点位，v173 补形态缺口）。

档序实测校准（_disp_dw 口径，生产可达形态）：
  首档「￥2280 中转南航CZ6949 兰州 停6:45 09:55→00:25（+1天达）」≈56 超 40；
  中档剥注「￥2280 中转南航CZ6949 09:55→00:25」w=34；
  fallback[1]「￥2280 中转南航CZ6949」w=21；
  地板档「￥2280」w=6。
 备案 m2「末档仍带注」语义随 地板档更新：末档无
arrive 组件=跨天注整体消失，定性设计内（无时刻组件即无误导），
本文件 test_floor_tier_price_only 将该契约钉死。

钉（全执行级）：
1. 消费点整行——中转/直飞跨天 × budget=40-_dw(pre)，整行 ≤40；
2. 档序——budget=35 剥注中档入选（含 →00:25 不含（+1天达））；
3. 紧预算——budget=28 落 fallback[1]（无注无时刻、保类型+价格）；
4. 地板律——budget=6 输出 == ￥价格 且 _disp_dw == 6（两夹具，
   钉死 max(6,…) 地板 × ￥价格 地板档契约防单方回潮）；
5. 默认预算向后兼容（跨天形态，brief 本体 ≤40 且中档入选）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v173_push.py -q
"""
from core.alerter import Alerter, _disp_dw, _dw

_PRE = "- 携程 最低 "  # _dw=12：消费点前缀（v172 同源形态）
# 中转跨天（flightnorm 归一化词面 crossDayDesc="+1天"）
_F_TRANS_CROSS = {"price": 2280, "name": "南航CZ6949", "transCity": "兰州",
                  "layoverT": "6:45", "depTime": "09:55", "arrTime": "00:25",
                  "crossDayDesc": "+1天"}
# 直飞跨天窄窗（arrTime 落 00:xx 次日凌晨）
_F_DIRECT_CROSS = {"price": 2310, "name": "春秋9C6928", "depTime": "23:05",
                   "arrTime": "01:15", "crossDayDesc": "+1天"}


class TestFmtBriefCrossBudgetV173:
    """跨天注 × budget：首档带注最宽形态下整行/档序/地板全链钉。"""

    def test_trans_cross_prefix_budget_full_line_within_40(self):
        pre = _PRE
        brief = Alerter._fmt_brief(_F_TRANS_CROSS, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_direct_cross_prefix_budget_full_line_within_40(self):
        pre = _PRE
        brief = Alerter._fmt_brief(_F_DIRECT_CROSS, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_cross_note_stripped_at_mid_tier(self):
        """budget=35：首档带注（≈48+）被挤掉，剥注中档（w=34）入选——
        跨天注不进文本但时刻保留（剥注档序不变）。"""
        brief = Alerter._fmt_brief(_F_TRANS_CROSS, budget=35)
        assert "→00:25" in brief
        assert "（+1天达）" not in brief
        assert _disp_dw(brief) <= 35

    def test_tight_budget_drops_time_keeps_type_and_price(self):
        """budget=28：中档（w=34）也超，落 fallback[1]——无注无时刻，
        保「类型+价格」核心判据。"""
        brief = Alerter._fmt_brief(_F_TRANS_CROSS, budget=28)
        assert "+1天" not in brief and "→00:25" not in brief
        assert "￥2280" in brief and "中转" in brief
        assert _disp_dw(brief) <= 28

    def test_floor_tier_price_only(self):
        """地板律执行级：budget=6（消费点 max(6,…) 地板）时输出恒
        「￥价格」——钉死「max 地板 × ￥价格 地板档」契约对
        （引入， m2 备案语义以此为准：末档无
        arrive 组件=跨天注整体消失，设计内）。"""
        for f in (_F_TRANS_CROSS, _F_DIRECT_CROSS):
            brief = Alerter._fmt_brief(f, budget=6)
            assert brief == f"￥{f['price']}", repr(brief)
            assert _disp_dw(brief) == 6

    def test_default_budget_backward_compatible_cross(self):
        """不带 budget（=40）：跨天形态 brief 本体 ≤40 且中档入选。"""
        brief = Alerter._fmt_brief(_F_TRANS_CROSS)
        assert _disp_dw(brief) <= 40
        assert "→00:25" in brief and "（+1天达）" not in brief
