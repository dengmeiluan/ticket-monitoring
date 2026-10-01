# -*- coding: utf-8 -*-
"""WebUI 精修批钉（WebUI 审计 P2×6 落地；P2-6 K 线窄画布桶宽观察项备案不动）。

P2-1 chhead 触控热区（::after 族收编，19px→36 基准，视觉零变化）。
P2-2 srow 输入 coarse 高度 38px（三处触控清单同步纪律，fbar 同值先例）。
P2-3 ≤760 类别/日期独立列收进航班格 mmeta（390 航班列窄条 ~109px）。
P2-4 xrow 比价链 ≤760 折行（结论句「（可省 ￥N）」曾被 nowrap 藏两屏外）。
P2-5 scroll-padding ≤760 档 136（390 实测 header 134px，118 曾盖 16px）。
P2-7 微排版：图例「（格底）」孤行与配置标题括号计数断行（nowrap 包裹）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v200_webui.py -q
"""
import re


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


class TestChheadTouchTarget:
    """P2-1：chhead 折叠头触控热区外扩（::after 族同 .dx/.hc/.tj 先例）。"""

    def test_hotzone_after_present(self):
        src = _src()
        assert ".chhead[role=" in src, "chhead 触控热区规则缺失"
        m = re.search(r"\.chhead\[role=.?button.?\]\{position:relative\}"
                      r"[^\n]*\n[^\n]*\.chhead\[role=.?button.?\]::after"
                      r"\{content:'';position:absolute;inset:[^}]+\}", src)
        assert m, "chhead 热区需 position:relative + ::after inset 外扩成对"

    def test_after_family_block_updated(self):
        """热区族注释块（::after 外扩）应提及 chhead 收编。"""
        src = _src()
        i = src.index("触控热区扩展")
        seg = src[i:i + 2000]
        assert "chhead" in seg, "触控热区扩展块未收编 chhead（清单漂移）"


class TestSrowInputHeight:
    """P2-2：srow 行内输入 coarse 高度 38px，三处触控清单同步。"""

    def test_three_coarse_blocks(self):
        src = _src()
        n = src.count(".srow .sctl input:not(.switch){height:38px}")
        assert n >= 3, f"srow 输入 38px 应在三处触控块各一份（现 {n}）"


class TestMobileCatDateColumns:
    """P2-3：≤760 类别/日期列收进航班格 mmeta。"""

    def test_th_classes_generated(self):
        src = _src()
        assert "k==='cat'?' catt'" in src and "k==='date'?' datd'" in src, \
            "thead 列头未挂 catt/datd 类"

    def test_td_classes_and_mmeta(self):
        src = _src()
        assert '<td class="catt">' in src, "类别 td 未挂 catt"
        assert '<td class="datd">' in src, "日期 td 未挂 datd"
        m = re.search(r'<div class="mmeta">.*?</div>', src, re.S)
        assert m, "航班格 mmeta 预置容器缺失"
        seg = m.group(0)
        assert "t-t" in seg and "t-d" in seg, "mmeta 缺类别 tag 双态"
        assert "mdat" in seg, "mmeta 缺日期小字"

    def test_css_hide_and_show(self):
        src = _src()
        base = src.index("#ftable .mmeta{display:none}")
        i760 = src.rindex("#ftable .mmeta{display:flex")
        assert base < i760, "mmeta 显示块未置尾（层叠被 display:none 反杀）"
        m = re.search(
            r"#ftable th\.catt,#ftable td\.catt,#ftable th\.datd,"
            r"#ftable td\.datd\{display:none\}", src)
        assert m, "≤760 类别/日期列隐藏规则缺失"


class TestXrowWrapMobile:
    """P2-4：xrow 比价链 ≤760 折行（结论句进首屏）。"""

    def test_wrap_rule_after_nowrap_base(self):
        src = _src()
        m = re.search(
            r"#ftable tr\.xrow:not\(\.tgrow\) td\{white-space:normal", src)
        assert m, "xrow ≤760 折行规则缺失"
        base = src.index("th,td{padding:9px 10px;text-align:left;white-space:nowrap")
        assert base < m.start(), "折行规则须在 nowrap 基础规则之后"

    def test_conclusion_nowrap(self):
        """结论句「（可省 ￥N）/（差…）/（仅一渠道报价）」整体 nowrap——
        折行断点曾把结论腰斩成「￥1)」孤行（决策语义被拆）。"""
        src = _src()
        assert '<span style="white-space:nowrap">（可省 ￥${save}）</span>' in src
        assert 'white-space:nowrap">（差 ￥${save}' in src
        assert '<span style="white-space:nowrap">（仅一渠道报价）</span>' in src

    def test_conclusion_before_chain(self):
        """结论句前置于渠道链（真机 390 实测：colspan td 宽=全表宽，
        white-space:normal 只在链长超过全表宽时才折行——三渠道链
        ~470px < 690px 单行放得下，结论句仍藏视口外 ~200px 须横滚；
        前置后结论句恒贴链头（xrow 已退出首列吸附，链头=滚动零位）。"""
        src = _src()
        m = re.search(r"同班比价.{0,600}?\$\{chain\}", src, re.S)
        assert m, "xrow 模板「同班比价…${chain}」结构不在"
        seg = m.group(0)
        assert '<span style="white-space:nowrap">（' in seg, \
            "结论句须前置于渠道链（同班比价 与 ${chain} 之间）"
        assert "同班比价：" not in seg, "旧序「同班比价：链」残留"


class TestScrollPaddingNarrow:
    """P2-5：≤760 档 scroll-padding 136（390 实测 header 134px）。"""

    def test_narrow_compensation_declared_after_midband(self):
        src = _src()
        # ≤760 中带补偿（动态 hdh+34）之后，≤540 窄档再增强块（+mtabsh）
        # 须置尾盖过（同选择器后者胜）
        i_mid = src.rindex("html{scroll-padding-top:calc(var(--hdh,76px) + 34px)")
        m = re.search(
            r"html\{scroll-padding-top:calc\(var\(--hdh,134px\) \+ var\(--mtabsh\) \+ 4px\)\}",
            src)
        assert m, "≤540 档动态补偿块缺失"
        assert i_mid < m.start(), "窄档补偿块须置尾（同选择器后者胜）"


class TestMicroTypography:
    """P2-7：图例括注孤行与配置标题计数断行（nowrap 包裹）。"""

    def test_cal_legend_nowrap(self):
        src = _src()
        assert src.count('<span style="white-space:nowrap">红=超线（格底）</span>') == 2, \
            "图例「红=超线（格底）」须整体 nowrap（stats 版+空态版两处）"

    def test_cfg_title_count_nowrap(self):
        src = _src()
        assert '<span style="white-space:nowrap">（\'+CFG.length+\' 个用户）</span>' in src, \
            "配置标题计数括号须整体 nowrap"
