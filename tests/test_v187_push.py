# -*- coding: utf-8 -*-
"""v1.5.87 推送钉（推送审校 P2-1/P3-1/P3-3/P3-7 落地钉）。

- P2-1 降级说明行：`> ⚠️ 航线较多…` 直拼 55/40 超宽（全 desp 唯一
  没走 _fit_line 的引用行，多航线+命中降级场景必现）——提取
  _demote_note 三档降级链，地板档保「明细见总表」对账语义
- P3-1 小节标题本体宽度守卫：dep_win 曾有下沉机制但标题本体
  （长自定义城市名+日期跨度）无守卫——提取 _section_title，本体
  超宽时日期段与时段段同款下沉
- P3-3 明细总表 PNG 图例补正面衔接词条：衔接达标绿「停4:50」曾只有
  反面「橙红=衔接不足」词条，正面绿无解码可误读为价格达标色
- P3-7 _channel_ops_lines 地板档 names[:20]+（截）=44/40 数学超宽
  （5 渠道实况不可达，但地板档自身须 ≤40——守卫链尾地板档纪律）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v187_push.py -q
"""

from core.alerter import _demote_note, _dw, Alerter


class TestDemoteNote:
    """P2-1：降级说明行三档降级链。"""

    def test_dual_clause_demoted_fits_40(self):
        """双词条形态（demoted+hit_demoted）：55/40 超宽降级到等义
        压缩档（39/40），hit 丢失面语义不丢（只丢「判据」二字）。"""
        out = _demote_note(True, True)
        assert _dw(out) <= 40, f"降级说明行仍超宽：{_dw(out)} 半角"
        assert "命中行仅价格" in out, "降级丢 hit 丢失面语义"

    def test_single_clause_kept_intact(self):
        """单词条形态（仅 sec 降级）：37/40 合格保持全形态。"""
        out = _demote_note(True, False)
        assert out == "> ⚠️ 航线较多，仅列关键价，明细见总表"
        assert _dw(out) <= 40

    def test_floor_keeps_reconcile_semantics(self):
        """地板档恒含「明细见总表」对账语义（信息按重要性从前往后丢）。"""
        for a in (True, False):
            for b in (True, False):
                out = _demote_note(a, b)
                assert "明细见总表" in out, f"地板档丢对账语义：{out!r}"


class TestSectionTitle:
    """P3-1：小节标题本体宽度守卫。"""

    @staticmethod
    def _title(fn, tn, span, win):
        return Alerter._section_title(fn, tn, span, win)

    def test_normal_shape_unchanged(self):
        """常态（乌鲁木齐→上海 单日期+无时段窗）：与旧拼接逐字一致。"""
        out = self._title("乌鲁木齐", "上海", "10/05", "")
        assert out == "#### ✈️ 乌鲁木齐→上海 10/05\n\n"

    def test_dep_win_inline_and_sunk(self):
        """时段窗：整行 ≤40 时内联；超宽时下沉引用行（旧两分支保持）。"""
        out = self._title("乌鲁木齐", "上海", "10/05", "（8后出发）")
        assert out.startswith("#### ✈️ 乌鲁木齐→上海 10/05（8后出发）\n\n")
        long_win = "（20后–次日02前出发）"
        out2 = self._title("乌鲁木齐", "上海", "10/05", long_win)
        assert out2 == (f"#### ✈️ 乌鲁木齐→上海 10/05\n\n> {long_win}\n\n")

    def test_overlong_city_sinks_date_span(self):
        """标题本体超宽（长自定义城市名）：日期段下沉、标题行 ≤40。
        （样本 5 字名：本体 30 可保、本体+日期 42 破 40——下沉日期
        后达标；更极端的城市名自身超出标题承载，不属日期下沉面。）"""
        out = self._title("超长出发名", "超长到达名",
                          "10/05-10/06", "")
        assert _dw(out.split("\n\n")[0]) <= 40, \
            f"标题行超宽：{_dw(out.splitlines()[0])} 半角"
        assert "10/05-10/06" in out, "日期段未保留（下沉丢失）"
        assert "> 10/05-10/06" in out, "日期段未下沉到引用行"

    def test_overlong_city_with_dep_win_merges_sunk_line(self):
        """本体超宽+时段窗同现：日期与时段合并同一条下沉引用行。"""
        out = self._title("超长出发名", "超长到达名",
                          "10/05", "（8后出发）")
        assert out.count("\n\n> ") == 1, "下沉引用行未合并（多段散落）"
        assert "10/05" in out and "（8后出发）" in out


class TestLegendAndOpsPins:
    """P3-3 图例正面衔接词条 + P3-7 ops 地板档。"""

    @staticmethod
    def _src(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_tbl_legend_green_layover_entry(self):
        """PNG 总表图例首行补「绿停时=衔接达标」正面词条。"""
        src = self._src("report.py")
        assert "绿停时=衔接达标" in src, \
            "总表图例缺衔接达标正面词条（正面绿无解码可误读为价格色）"

    def test_ops_floor_clamped_to_17(self):
        """ops 地板档 names[:17]+（截）=40/40 恰满（全角括号 _dw 实值
        6 半角，[:18] 形态 42/40 超；地板档自身须恒 ≤40）。"""
        src = self._src("core/alerter.py")
        assert 'names[:17] + "（截）"' in src, \
            "ops 地板档未收口 17 字符（42/40 超宽形态残留）"
