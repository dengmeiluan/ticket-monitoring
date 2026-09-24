# -*- coding: utf-8 -*-
"""推送回归（真执行级，同 test_v170/v171_push.py 模式）。

 重放立案 P1×1——图挂兜底轮「渠道最低」行整行超宽：
_channel_market_lines tops 分支拼行「- {渠道} 最低 {brief}」时只对
brief 本体套 _fit_line(40)，前缀「- 携程 最低 」（_dw=12）不进预算，
整行恒 44-48 超宽（09-22 11:14 图挂兜底轮真实违例 20/2546 行全此根因，
L2 定律=钉钉手机 ≤20 全角折行断点不受控）——同函数 else 分支
  已把前缀并入守卫，tops 分支漏网。修法=_fmt_brief 增
budget 参数（默认 40 向后兼容），消费点扣前缀宽传入；超预算逐级落档
保「渠道+价格+类型+航班号」核心判据（同哲学）。

另 L8（日报 ⏱ 时间注行带日期）两轮连抓（v171/v172 重放各 2 条）定性
=检测器口径备案、不改生产码：「⏱ 去日期」定律动机是图例行 40 半角
预算塞不下档位词条（基座压缩留缓冲在案）；日报时间注行无
词条 ≈30 半角，MM/DD=跨天辨识信息，去之丢信息零宽度收益。

钉：
1. 执行级——_fmt_brief(budget=…) 短/长渠道名 × 中转/直飞全形态，
   前缀+brief 整行 _disp_dw ≤40；默认参数向后兼容。
2. 执行级——_channel_market_lines 真调（Alerter.__new__ 免 init），
   plat_top3+platform_mins 混合 section 产出每一行 ≤40 且价格在行。
3. 源码钉——_fmt_brief 签名含 budget、消费点按前缀扣预算。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v172_push.py -q
"""
from core.alerter import Alerter, _disp_dw, _dw

_PRE_FIX = "- 携程 最低 "          # _dw=12：短渠道名前缀
# 超界探索形态：非生产渠道名（PLATFORM_CN 最长「去哪儿」
# pre=14），比生产更紧 2 半角的边界，方向保守不掩盖生产问题
_PRE_LONG = "- 乌鲁木齐 最低 "      # _dw=16：长渠道名前缀（预算更紧的形态）
_F_TRANS = {"price": 2270, "name": "山东SC8714", "depTime": "07:25",
            "arrTime": "19:15", "transCity": "山东", "layoverT": "2:15"}
_F_TRANS_LONG = {"price": 2315, "name": "新海航｜乌鲁木齐航空UQ2509",
                 "depTime": "06:55", "arrTime": "14:55",
                 "transCity": "乌鲁木齐"}
_F_DIRECT = {"price": 2310, "name": "春秋9C6928",
             "depTime": "19:05", "arrTime": "23:55"}


class TestFmtBriefBudgetV172:
    """_fmt_brief budget 参数：前缀进预算后整行不破 40。"""

    def test_trans_short_prefix_full_line_within_40(self):
        pre = _PRE_FIX
        brief = Alerter._fmt_brief(_F_TRANS, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_trans_long_name_long_prefix_within_40(self):
        pre = _PRE_LONG
        brief = Alerter._fmt_brief(_F_TRANS_LONG, budget=40 - _dw(pre))
        line = pre + brief
        assert _disp_dw(line) <= 40
        assert "￥2315" in line  # 地板档保价格核心判据（超长名让位）

    def test_direct_short_prefix_full_line_within_40(self):
        pre = _PRE_FIX
        brief = Alerter._fmt_brief(_F_DIRECT, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_default_budget_backward_compatible(self):
        """不带 budget 时行为=旧守卫（40 预算，brief 本体达标形态不变）。"""
        assert _disp_dw(Alerter._fmt_brief(_F_DIRECT)) <= 40
        # 无前缀场景（预算 40）中档时刻形态仍在：短名直飞本体 34 ≤40
        assert "19:05→23:55" in Alerter._fmt_brief(_F_DIRECT)


class TestChannelMarketLinesV172:
    """消费点整行守卫：_channel_market_lines 产出行全 ≤40。"""

    @staticmethod
    def _sections():
        return [{
            # tuniu 有全线价无合格明细（else 直出分支），其余走 tops 分支
            "plat_top3": {"ctrip": [dict(_F_TRANS)],
                          "qunar": [dict(_F_TRANS_LONG)],
                          "tongcheng": [dict(_F_DIRECT)]},
            "platform_mins": {"ctrip": 2270.0, "qunar": 2315.0,
                              "tongcheng": 2310.0, "tuniu": 2400.0},
            "seen_plats": ["ctrip", "qunar", "tongcheng", "tuniu"],
        }]

    def test_all_lines_within_40(self):
        al = Alerter.__new__(Alerter)  # 免 init：方法只消费类属性
        desp = al._channel_market_lines(self._sections())
        for ln in desp.split("\n"):
            if ln.startswith("- ") and "最低" in ln:
                assert _disp_dw(ln) <= 40, f"超宽行: w={_disp_dw(ln)} {ln}"

    def test_price_and_flight_kept_on_fallback(self):
        al = Alerter.__new__(Alerter)
        desp = al._channel_market_lines(self._sections())
        # 价格核心判据三渠道恒在；短名航班号预算内保留，
        # 超长名（UQ2509 行）落地板档让位价格
        assert "￥2270" in desp and "SC8714" in desp
        assert "￥2315" in desp
        assert "￥2310" in desp and "9C6928" in desp


class TestSourceV172Push:
    """源码钉：budget 形态在位防回潮。"""

    def test_fmt_brief_signature_has_budget(self):
        import inspect
        sig = inspect.signature(Alerter._fmt_brief)
        assert "budget" in sig.parameters, \
            "_fmt_brief 缺 budget 参数（前缀超宽案回潮）"
        assert sig.parameters["budget"].default == 40

    def test_consumer_passes_prefix_deducted_budget(self):
        import core.alerter as _m
        with open(_m.__file__, encoding="utf-8") as f:
            src = f.read()
        assert "budget=max(6, 40 - _dw(pre))" in src, \
            "_channel_market_lines tops 分支未按前缀扣预算（整行恒超宽回潮；" \
            "max(6,…) 地板防御：未知长平台键预算不为负）"
