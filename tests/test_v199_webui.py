# -*- coding: utf-8 -*-
"""r199 WebUI 层钉（D 路审计 P1×1 + P2×7；P2-8 观察项备案不动）。

P1-1 走势「低」标注互避：候选表近点三行+顶部两行（全叠情形错行
出口）+互叠判定横向外扩 6px 兼收同带贴邻——1920 档双系列最低点
水平邻近时后绘盒曾盖住先绘标注的「低」前缀（实证裁片在案）。
P2-1 761-900 带 scroll-padding 118（header 折行 109px 曾遮锚点 37px）。
P2-2 setFltOpen 单源：togFlt/Esc//` 三口共用（旁路直改 .open 曾漏
aria-expanded 回写）。
P2-3 配置页双控件行全量挂 aria-label（一行一输入假设曾漏第二枚）。
P2-4 #tabs/#cfgnav aria-pressed（button 形态按态播报），tabAria 尾随
兜初始态 + 两切换点各补一拍。
P2-5 #montab-details 先于 #montab-health（display 翻转架构键盘 Tab
序按 DOM，曾与视觉 tab 序相反）。
P2-6 明细行首行 0 余 -1 + ↑/↓ 族移动（数百行逐格 Tab 穿越负担）。
P2-7 ≤760 价格格 .pretax 折行（390 档吸附首列曾占可见表宽 53%）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v199_webui.py -q
"""
import re


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


class TestMarkMinEscapeRows:
    """P1-1：标注互避算法候选表含错行出口，横向判定外扩。"""

    def test_escape_rows_present(self):
        src = _src()
        m = re.search(r"const markMin=\(pts,color,bandY\)=>\{.*?"
                      r"markMin\(HPTS\.d[^\n]*\);", src, re.S)
        assert m, "markMin 函数锚丢失（应带 bandY 专属带参）"
        seg = m.group(0)
        assert "for(const dy of [-10,16,42])" in seg, "近点行缺第三档错行出口"
        assert "cands.push([x+dx,bandY])" in seg, "顶带候选未改专属带形态"
        assert ",T+12);" in seg and ",T+44);" in seg, "双系列异带实参缺"

    def test_overlap_margin_expanded(self):
        src = _src()
        assert "!(cx+tagW+6<b[0]||b[2]<cx-6||cy+4<b[1]||b[3]<cy-12)" in src, \
            "互叠判定未横向外扩 6px（同带贴邻漏罚）"

    def test_clamp_bottom_is_plot_bottom(self):
        """钳位下界=H-B-6（B 是底边距非底坐标——旧 B-6 在高画布把
        全部候选钳进顶部 20px 窄带=同带互叠真根因）。"""
        src = _src()
        assert "const cy=Math.min(Math.max(c[1],T+12),H-B-6);" in src, \
            "标注 y 钳位仍用 B-6（边距当坐标）"


class TestScrollPaddingMidBand:
    """P2-1：761-900 带锚点滚动补偿。"""

    def test_900_band_declared_after_base(self):
        src = _src()
        base = src.index("html{scroll-padding-top:72px")
        i900 = src.rindex(
            "@media(max-width:900px){html{scroll-padding-top:"
            "calc(var(--hdh,54px) + 34px)}}")
        assert base < i900, "≤900 补偿块未置尾（层叠被基础块反杀）"


class TestSetFltOpenSingleSource:
    """P2-2：抽屉开合三口单源。"""

    def test_helper_and_three_callers(self):
        src = _src()
        assert "function setFltOpen(open){" in src
        m = re.search(r"function togFlt\(\)\{[^}]*setFltOpen\(", src, re.S)
        assert m, "togFlt 未走 setFltOpen"
        assert "if(fb){setFltOpen(false);return;}" in src, "Esc 旁路未收口"
        assert "getComputedStyle(fb).display==='none')setFltOpen(true)" in src, \
            "`/` 旁路未收口"
        # 旁路直改 .fbar 开合清零：抽屉开合只经 setFltOpen 的
        # toggle('open',open) 单源（fb 语境的 add/remove 直改必红；
        # .chev 折叠组件同名类不在此守卫面）
        scripts = "".join(re.findall(r"<script>(.*?)</script>", src, re.S))
        assert "fb.classList.add('open')" not in scripts, \
            "旁路直改 .fbar 开合残留（绕过 setFltOpen 单源）"
        assert "fb.classList.remove('open')" not in scripts, \
            "旁路直改 .fbar 开合残留（绕过 setFltOpen 单源）"
        assert "classList.toggle('open',open)" in src


class TestCfgMultiControlAria:
    """P2-3：配置页行内全量控件挂 aria-label。"""

    def test_query_selector_all_with_suffix(self):
        src = _src()
        m = re.search(r"querySelectorAll\('\.srow,\.glcell'\)\.forEach"
                      r"\(r=>\{.*?inps\.forEach", src, re.S)
        assert m, "配置行 aria 后处理未改全量控件形态"
        assert "querySelectorAll('input,select')" in src, "仍取单控件"
        assert "inps.length>1?' '+(i+1):''" in src, "多控件缺序号后缀"


class TestTabsCfgnavAriaPressed:
    """P2-4：#tabs/#cfgnav 选中态 aria-pressed。"""

    def test_sync_in_tabaria_and_switch_points(self):
        src = _src()
        seg = src[src.index("function tabAria()"):src.index("/* 选择器说明")]
        assert "aria-pressed" in seg, "tabAria 缺 pressed 尾随同步"
        i = src.index("$('tabs').onclick")
        assert "saveUI();table();tabAria();}" in src[i:i + 300], \
            "#tabs 切换点缺一拍"
        m = re.search(r"function showCfgPanel\(id,silent\)\{.*?aria-pressed",
                      src, re.S)
        assert m, "cfgnav 切换点缺一拍"


class TestMonTabDomOrder:
    """P2-5：明细块先于健康块（键盘 Tab 序=DOM 序对齐视觉 tab 序）。"""

    def test_details_before_health(self):
        src = _src()
        assert src.index('<div id="montab-details"') < \
            src.index('<div id="montab-health"'), \
            "montab 块序未对齐（details 应在前）"


class TestDetailRowRoving:
    """P2-6：明细行首行 0 余 -1 + ↑/↓ 族移动。"""

    def test_row_tabindex_and_arrow_handler(self):
        src = _src()
        assert 'tabindex="${i===0?0:-1}"' in src, "行 tabindex 未改族形态"
        assert "else if(event.key==='ArrowDown'||event.key==='ArrowUp')" \
            in src, "行键盘缺 ↑/↓ 分支"
        assert "_rowRoving(event,this)" in src

    def test_row_roving_helper_scoped(self):
        src = _src()
        m = re.search(r"function _rowRoving\(e,el\)\{.*?\}", src, re.S)
        assert m, "_rowRoving helper 缺失"
        assert "tr[data-k]" in m.group(0), "选择器未限定数据行" \
            "（xrow/tgrow 无 data-k 天然排除）"


class TestPretaxWrapMobile:
    """P2-7：≤760 价格格退改徽标折行。"""

    def test_media_rule_present(self):
        src = _src()
        base = src.index("html{scroll-padding-top:72px")
        i = src.index("#ftable td.price .pretax{display:block;font-size:10px}")
        assert i > base, "≤760 折行规则未置尾（层叠风险）"
        seg = src[src.rindex("@media(max-width:760px)", 0, i):i]
        assert "max-width:760px" in seg
