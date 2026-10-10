# -*- coding: utf-8 -*-
"""r198 回归：五路调研立案七案（数据 D×1 / WebUI P×3 / 推送 E×2+注）。

D 路（r198 渠道调研 A 路立案 N1）：ctrip aset 层「中转住宿」标签
（tcode=G_XIYZZZS202601）被白名单以「与政策级 nt=10 hotel_free 同义」
为由排除，但 3U8230 行实证该行全部政策无 nt=10 承载——排除依据被
渠道静默扩展证伪，不采则该行跨天中转免费住宿权益永久缺失。归一为
「中转免费住宿」（与 hotel_free 产出同串，去重自洽，零新键）。

P 路（r198 WebUI 审计）：①901+ 粗指针档 .chip 缺 font-size:13px，
1280 粗指针（iPad Pro 横屏）时段挡位 chip 本体 35px 差 1px 不达 36
触控基准（≤900 姊妹块有该声明）；②走势入场动画先全量画满终帧再逐
帧 clip 重绘同内容=零视觉产出（审计探针：强差异数据下动画中段右区
签名恒等于终帧）——动画轮跳过首绘，从旧图/空布左→右揭示；③CSV 无
独立「准点率」列（明细次行有「准点N%·取消N%」，导出面缺准点率——
决策字段进表格先例同轨，就近插位贴取消率）。

E 路（r198 推送审校）：①kpi_tier_txt 真达标态输出「低￥N」无档位
词面（破线态有「·行情」单向消歧，正向档不显名）——补「·真达标」
与「·行情」对称，词面取 TIER_FULL["qual"] 单源；②KPI 行2 降级链
地板档无截断（长航班名合成 49/40 原样吐出，与 _ops_fallbacks 地板
档恒达标律不同轨）——地板档按渲染宽逐字截。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v198_regress.py -q
"""
import json
import re

import pytest


# ==================== D1: ctrip aset「中转住宿」标签归一 ====================

class TestCtripTransferHotelTag:
    """aset 层「中转住宿」入 labels 白名单并归一「中转免费住宿」：
    与政策级 nt=10 双现行时去重单串（labels 是 ·join 单串）。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _item(aset_tags=None, policy_notes=None):
        """policy_notes：fnotelst 注释列表（nt=10 词面走这里）。"""
        item = {"mutilstn": [{"basinfo": {"flgno": "3U8230"},
                              "dateinfo": {"ddate": "2026-10-06 08:00:00",
                                           "adate": "2026-10-06 14:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 2050, "quantity": 1,
                                "classinfor": [
                                    {"cgrd": 0, "prate": 100, "meal": ""}]}]}
        if policy_notes:
            item["policyinfo"][0]["fnotelst"] = [
                {"notetype": 10, "notecnt": n} for n in policy_notes]
        if aset_tags:
            item["aset"] = [{"tagarea": [
                {"tcode": tc, "tagcnt": c} for tc, c in aset_tags]}]
        return item

    def test_aset_hotel_tag_normalized(self):
        """该行全部政策无 nt=10 承载（3U8230 生产实证），aset 词是
        唯一载体——归一为「中转免费住宿」入 labels。"""
        rows = self._parse(self._item(
            aset_tags=[("G_XIYZZZS202601", "中转住宿")]))
        assert rows, "夹具应产出航班行"
        assert "中转免费住宿" in (rows[0].get("labels") or ""), \
            f"aset「中转住宿」被排除，权益词永久缺失：{rows[0].get('labels')!r}"

    def test_dual_carrier_dedup(self):
        """政策级 nt=10 与 aset 词双现行：labels 单串只出现一次。"""
        rows = self._parse(self._item(
            aset_tags=[("G_XIYZZZS202601", "中转住宿")],
            policy_notes=["中转免费住宿"]))
        assert rows
        assert (rows[0].get("labels") or "").count("中转免费住宿") == 1

    def test_non_transfer_benefit_unaffected(self):
        """既有 nt=10 路径不回退：无 aset 词时照常落词。"""
        rows = self._parse(self._item(policy_notes=["中转免费住宿"]))
        assert rows
        assert "中转免费住宿" in (rows[0].get("labels") or "")


# ==================== P1: 901+ 粗指针档 chip 触控基准 ====================

class TestCoarseChipTouchBaseline:
    """>900px 粗指针块 .chip 补 font-size:13px（与 ≤900 姊妹块同值）：
    该档 chip 本体 35px 差 1px 不达 36 触控基准。钉锁级联实际胜者——
    规则必须落在 901+ 块内（媒体块无「更严条件更后胜」，块内声明即
    该档胜者），且其后再无同选择器 font-size 覆写。"""

    def _src(self):
        import webui
        with open(webui.__file__, encoding="utf-8") as f:
            return f.read()

    def test_chip_fontsize_in_901_coarse_block(self):
        src = self._src()
        m = re.search(
            r"@media\(pointer:coarse\) and \(min-width:901px\)\{.*?"
            r"\.chip,\.mchip,\.rngchip\{padding:9px 14px;font-size:13px\}",
            src, re.S)
        assert m, "901+ 粗指针块 .chip 缺 font-size:13px（35px<36 基准）"

    def test_no_later_chip_fontsize_override(self):
        """置尾纪律反杀面：901+ 块之后不得再有「1280 粗指针上下文
        可适用」的 .chip font-size 覆写——窄屏块（条件含 max-width，
        1280 不适用）合法豁免，无宽度上界或 coarse 块内覆写即反杀。"""
        src = self._src()
        m = re.search(
            r"@media\(pointer:coarse\) and \(min-width:901px\)\{.*?"
            r"\.chip,\.mchip,\.rngchip\{padding:9px 14px;font-size:13px\}",
            src, re.S)
        assert m, "前置钉失守"
        tail = src[m.end():]
        for mm in re.finditer(r"\.chip[,{][^}]*font-size", tail):
            ctx = tail[:mm.start()]
            i_media = ctx.rfind("@media(")
            cond = ctx[i_media:ctx.find("{", i_media)] if i_media >= 0 else ""
            assert "max-width" in cond, \
                "901+ 块之后存在 1280 粗指针可适用的 .chip font-size 覆写" \
                f"（层叠反杀）：{cond!r}"

    def test_rngchip_fontsize_in_all_touch_blocks(self):
        """三触控块（≤900 粗指针/901+ 粗指针/≤760 触控）.rngchip 同值
        补 font-size:13px：基础 12px 时段挡位本体 ~35px 差 1px 不达
        36 触控基准——只补一档则「同值补档」注释失准（姊妹块缺陷类
        一次清完，防下轮再审计同案）。"""
        src = self._src()
        n = src.count(".rngchip{padding:9px 14px;font-size:13px}")
        assert n >= 3, f"三触控块 .rngchip 须同值 13px，实得 {n} 处"


# ==================== P2: 走势入场动画可见性 ====================

class TestChartAnimReveal:
    """入场动画轮跳过首绘：先全量画满终帧再逐帧 clip 重绘同内容=
    零视觉产出。守卫钉：动画分支前不得有无条件 chartDraw() 首绘。"""

    def _src(self):
        import webui
        with open(webui.__file__, encoding="utf-8") as f:
            return f.read()

    def test_anim_path_skips_initial_full_draw(self):
        src = self._src()
        i = src.index("const _anim=CHART_ANIM&&!RM;")
        seg = src[i:i + 200]
        assert "if(!_anim)chartDraw();" in seg, \
            "动画轮未跳过首绘（全量终帧先画满，clip 逐帧重绘零视觉产出）"
        assert seg.index("if(!_anim)chartDraw();") < seg.index("if(_anim){"), \
            "直绘守卫必须位于动画分支之前（顺序即语义）"

    def test_non_anim_path_still_direct_draw(self):
        """RM/非动画路径保持直绘（终帧立即可见，r197 死区钉前提）。"""
        src = self._src()
        assert re.search(r"if\(!_anim\)chartDraw\(\);", src), \
            "直绘守卫缺失"


# ==================== P3: CSV 准点率列 ====================

class TestCsvOntimeColumn:
    """CSV 增「准点率」列：决策字段（准点率影响购买决策）进导出面，
    就近插位贴「取消率」（UI 明细次行同款「准点N%·取消N%」并提）。"""

    def _page(self):
        import webui
        with open(webui.__file__, encoding="utf-8") as f:
            return f.read()

    def test_head_has_ontime_next_to_cancel(self):
        m = re.search(r"const head=\[(.*?)\];", self._page(), re.S)
        assert m, "CSV 列头锚点丢失"
        head = m.group(1)
        assert head.count(",") + 1 == 45, \
            f"列数锚应随批内增列保持同步（r269 往返推荐=45）：{head.count(',') + 1}"
        assert "'准点率'" in head
        assert head.index("'准点率'") < head.index("'取消率'"), \
            "准点率应就近插位贴取消率（次行并提同序）"

    def test_row_value_form(self):
        page = self._page()
        assert "(f.prate?f.prate+'%':'')" in page, \
            "CSV 行值缺准点率取值（与明细次行同形：有值出 N%）"


# ==================== E1: kpi_tier_txt 真达标档显名 ====================

class TestKpiTierQualNamed:
    """真达标态补「·真达标」（与破线态「·行情」对称）：PNG summary
    脱离消息上下文时正向档不显名、靠「无·行情注」单向消歧。词面取
    TIER_FULL 单源；恰达线 gap_txt 已出完整词面不双挂。"""

    def test_qual_state_named(self):
        from core.alerter import kpi_tier_txt
        t = kpi_tier_txt("直飞", 100, 200, True)
        assert t == "直飞 ￥100 低￥100·真达标", \
            f"真达标态无档位词面：{t!r}"

    def test_brk_unqualified_note_unchanged(self):
        from core.alerter import kpi_tier_txt
        assert kpi_tier_txt("直飞", 100, 200, False) == \
            "直飞 ￥100 低￥100·行情"

    def test_exact_line_not_double_tagged(self):
        from core.alerter import kpi_tier_txt
        t = kpi_tier_txt("直飞", 200, 200, True)
        assert t == "直飞 ￥200 真达标", f"恰达线不双挂：{t!r}"
        assert t.count("真达标") == 1

    def test_over_and_near_unchanged(self):
        from core.alerter import kpi_tier_txt
        assert kpi_tier_txt("直飞", 300, 200, False) == \
            "直飞 ￥300 差￥100"
        t = kpi_tier_txt("直飞", 210, 200, False)
        assert t.startswith("直飞 ￥210 擦边") and "真达标" not in t


# ==================== E2: KPI 行2 地板档截断 ====================

class TestL2FloorTruncation:
    """行2 降级链地板档恒达标：超预算时保尾截头（r281 P2-1 修法 B，
    真实计宽网格选形：时刻/跨天锚定行尾=决策级辨识信息，头部名段
    让位；旧「保头截尾」曾把到达时刻截成半截甚至整段消失）。"""

    def test_floor_truncated_to_budget(self):
        from core.alerter import _l2_fallbacks, _disp_dw
        base = "中国联合航空 KN9999 超长航司名超长航司名超长航司名"
        assert _disp_dw(base) > 40, "夹具应超预算"
        fbs = _l2_fallbacks(base, "+1天", "↑5%")
        assert _disp_dw(fbs[-1]) <= 40, \
            f"地板档超宽原样吐（{ _disp_dw(fbs[-1]) }/40）"

    def test_floor_keeps_identity_head(self):
        # 旧钉锁「保头」（base.startswith(floor)）——修法 B 后地板
        # 改保尾（尾部锚定 cross+时刻域，头部名段让位），钉随模型
        # 改写：地板恒为 base+cross 的尾缀且预算内（恒达标律不变）
        from core.alerter import _l2_fallbacks, _disp_dw
        base = "中国联合航空 KN9999 超长航司名超长航司名超长航司名"
        fbs = _l2_fallbacks(base, "", "")
        assert fbs[-1], "地板档缺失"
        assert _disp_dw(fbs[-1]) <= 40, "地板档超预算"
        assert base.endswith(fbs[-1]), (
            "地板档应为 base 尾缀（保尾截头，尾部决策信息锚定）")

    def test_normal_input_order_unchanged(self):
        """档序语义不回退：跨天档先于地板档（涨跌档=恒宽死档已按
        档序律删除，LESSONS 十九§9：辨识信息先于次要信号被丢）。
        r281 修法 B 后 cross 真入地板链：短输入下地板=base+cross
        整串（预算内恒达标），地板档不再缺席 cross。"""
        from core.alerter import _l2_fallbacks
        fb = _l2_fallbacks("MU 08:00→11:00", "+1天", "↑5%")
        assert fb[0] == "MU 08:00→11:00+1天", "跨天档不在首位"
        assert fb[-1].endswith("+1天"), "地板档 cross 缺席（次生丢失）"
        assert fb[-1] == "MU 08:00→11:00+1天", (
            "短输入下地板=整串（预算内恒达标）")
