# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r255_webui.py
- tests/test_r275_webui.py
- tests/test_r278_webui.py
- tests/test_r283_webui.py
- tests/test_r316_webui_fc.py
- tests/test_v1590_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import re
import sys


# ---- merged from tests/test_r255_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page():
    return webui_full_src()


class TestRopSwitchTouchFamily:
    def test_rop_switch_extends_in_all_three_blocks(self):
        """P2-1：.rop .switch::before 外扩声明在三个触控媒体块各一
        （≤900/≤600/≤390 族与 .srow/.fbar/.glcell 同格局）——计数钉
        锁「块内同族清单完整」，漏任一块即红。"""
        n = _page().count(
            ".rop .switch::before{content:'';position:absolute;inset:-8px}")
        assert n == 3, f"预期 3 块各 1 处，实际 {n}"

    def test_rop_family_note_updated(self):
        """家族注释槽位清单随 .rop 同轮更新（防清单漂移）。"""
        assert ".srow/.fbar/.glcell/.rop" in _page()


class TestInlineIntentTouchHeight:
    def test_vw_and_tj_vertical_reach_36(self):
        """P3-1：a.vw/.tj 的 ::after 纵向 -11px（inline 盒包含块律，
        -9px 只兑现 34px 不达 36 触控基准）。.tj 横向收 0：富信息行
        route 词组恰在行中心的偶发几何下，横向外扩放大跳走势劫持面
        （行展开主意图落空）——纵向触控基准保留，横向不越出本体词组
        （本体 32.5 在案豁免档）。"""
        src = _page()
        assert (".pvx::after,a.vw::after{content:'';position:absolute;"
                "inset:-11px -8px}") in src
        assert ".tj::after{content:'';position:absolute;inset:-11px 0}" in src

    def test_stale_minus_nine_note_purged(self):
        """a.vw/.tj 家族注释不再宣称 -9px 达标（防注释与实现漂移）。
        注：.chhead/.tg 本体为块级盒，-9px 兑现 37px 达标，不在本钉面。"""
        src = _page()
        assert "-9px -8px / -9px -4px" not in src


class TestErrcodeMinusTwoCoverage:
    def test_errcode_tip_explains_minus_two(self):
        """P3-2 展示层随动：errcode=-2（网络异常轮落账）上线后，
        推送记录的悬停词表必须解释 -2，不能让它落进「其他码见通道
        文档」的泛化档（-2 与 -1 语义相反：-1 可能已送达，-2 必然
        未送达）。"""
        src = _page()
        assert "-2=未收到响应" in src, \
            "errcode 悬停词表缺 -2 语义（网络异常轮落账已上线）"

    def test_demo_sample_covers_minus_two_shape(self):
        """DEMO 合成推送记录含 -2 形态样例（词表改动的活体展示位，
        与既有 -1 幽灵送达样例成对）。"""
        src = _page()
        assert '"errcode": -2' in src, "DEMO 样例缺 errcode=-2 形态"


class TestErrorBodyUpdatedPillSingleSource:
    def test_cold_start_500_updated_blank(self):
        """P3-2：500-JSON 冷启动分支 #updated 置空（与 502-HTML 分支
        同律）——pill 是错误词面唯一承载，#updated 不再复读。"""
        src = _page()
        assert "else{$('updated').textContent='';_markStale('服务异常');}" in src

    def test_fuwu_yichang_updated_literal_purged(self):
        """「（服务异常）」updated 词面全页零残留（冷启动分支清空后
        该字面无合法写点；「服务异常」pill 词面不受本钉约束）。"""
        assert "（服务异常）" not in _page()


# ---- merged from tests/test_r275_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_WEBUI = webui_full_src()


# ---- P3-1：配置搜索收编 ----

def test_p31_dead_danger_selector_retired():
    """死选择器 .ucard>.danger 禁复活（删除钮实际 DOM 多包一层 div，
    子代选择器恒不命中）。"""
    assert _WEBUI.count(".ucard>.danger") == 0, \
        "死选择器 .ucard>.danger 复活"


def test_p31_danger_selector_alive_both_sites():
    """删除钮收编改 .ucard button.danger（后代选择器）：清空复位清单
    与过滤清单两处在案。r281 容器壳收尾扫的 ROWS 口径合法新增第三处
    （动作件命中时宿主容器不得被误隐）——计数钉随合法新写点 +1。"""
    assert _WEBUI.count(".ucard button.danger") == 3, \
        "删除钮收编选择器应恰在 cfgSearchClear+cfgFilter+容器收尾扫三处"


def test_p31_add_route_btn_covered_both_sites():
    """「➕ 添加航线」钮收编：模板侧专类 + 两处清单按类收编（按钮
    实为 ucard 孙级——折叠包裹层内，子代选择器恒不命中与删除钮
    同族病；类与清单两段互锁，任一侧漂移即红）。"""
    assert 'class="btn2 addrbtn"' in _WEBUI, "添加航线钮缺专类"
    assert _WEBUI.count("#cfgview .addrbtn") == 2, \
        "添加航线钮收编应恰在 cfgSearchClear+cfgFilter 两处"


def test_p31_zero_hit_orphan_heads_hidden():
    """0 命中档孤儿头隐藏：结构头（分区/用户卡/静态卡头/全局
    subsec）按命中数显隐（n?'':'none'），搜索清空路径同清单复位
    （清空复位清单与过滤清单同步纪律）。"""
    assert _WEBUI.count("#cfgview .grouplab,#cfgview .uhead2,"
                        "#cfgview .uhead,#cfgview .subsec") == 2, \
        "孤儿头显隐联合选择器应恰在清空+过滤两处"


# ---- P3-2：#montabs 降 button 形态 ----

def test_p32_montabs_tablist_retired():
    """tablist 形制退役（禁复活）：#montabs 不再设 role=tablist，
    .mtab 不再挂 role=tab/tab↔tabpanel 关联/aria-selected（fltBtn 的
    button 语境 aria-controls 合法在案，不在此列）。"""
    assert "setAttribute('role','tablist')" not in _WEBUI, \
        "tablist 形制复活"
    assert "setAttribute('role','tab')" not in _WEBUI, \
        "tab 角色复活"
    assert "setAttribute('aria-controls','montab-'" not in _WEBUI, \
        "tab↔tabpanel 关联复活"
    # 合法 aria-selected：日期模式条 1 + 检索台移动 tab 2 + 城市联想选中项 2
    # + 城市面板国内/国际真 tab 1 = 6。montabs 本身仍禁（上方 role 断言）。
    assert _WEBUI.count("setAttribute('aria-selected'") == 6, \
        "aria-selected 使用点变化：核对是否误挂回 tablist"
    assert "setDateMode" in _WEBUI


def test_p32_mtab_pressed_semantics_alive():
    """实效档在场：.mtab 走 aria-pressed 播报（#tabs 同律，mkact 已
    赋 role=button），面板可访问名回写保留。"""
    import re
    assert re.search(
        r"querySelectorAll\('\.mtab'\)\.forEach\(x=>\s*"
        r"x\.setAttribute\('aria-pressed'", _WEBUI), \
        ".mtab aria-pressed 回写缺席"
    assert "PNAME" in _WEBUI, "面板可访问名映射缺席"


def test_p32_roving_tabindex_retired():
    """roving tabIndex 随 tablist 形制退役（button 形态下全员可 Tab）：
    tabAria 的 .mtab 块状循环（roving 载体）不复活。"""
    assert "document.querySelectorAll('.mtab').forEach(x=>{" not in _WEBUI, \
        "tabAria .mtab 块状循环复活（roving tabIndex 载体）"


# ---- merged from tests/test_r278_webui.py ----

def test_kpi_fb_minheight_uniform():
    src = webui_full_src()
    assert (".kpi .fb{color:var(--tx2);font-size:12px;"
            "margin-top:2px;min-height:19px}") in src.replace("\n", ""), \
        "KPI 卡 .fb 行未挂 min-height:19px（跨日期组 3px 节奏差）"


# ---- merged from tests/test_r283_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = webui_full_src()


def test_fltlegend_element_in_drawer():
    """抽屉内图例元素在场（r352 移到预设行后，窄屏更早可达），词面与
    宽档常驻图例同语言（四方同语言律）。"""
    m = re.search(r'<div class="frow flgrow"><span class="muted" '
                  r'id="fltlegend">([^<]+)</span>', _SRC)
    assert m, "抽屉图例补位行不在场"
    assert "深绿=真达标" in m.group(1) and "描绿=行情破线" in m.group(1) \
        and "琥珀=擦边" in m.group(1), m.group(1)


def test_fltlegend_hidden_by_default():
    """补位行基础 display:none（行级开关）：宽档已有 .tabs 常驻图例，
    抽屉图例行不重复显示、不占 .frow+.frow 空缝。"""
    assert re.search(r'\.flgrow\{display:none\}', _SRC), \
        "缺补位行基础隐藏规则——宽档将双份图例/空行缝"


def test_fltlegend_visible_in_narrow_bands():
    """≤760 两带媒体块内各有一条行级放行规则（图例隐藏的带=触屏
    真空带，抽屉补位与隐藏规则同块同域）。"""
    n = len(re.findall(r'\.flgrow\{display:flex\}', _SRC))
    assert n == 2, f"窄带放行规则 {n} 条（预期 2：≤760 与 ≤540 两带）"


# ---- merged from tests/test_r316_webui_fc.py ----

_SRC = webui_full_src()


def test_forced_colors_media_block_covers_on_family():
    """forced-colors 块在场且覆盖选中态家族（mtab/tabs/mainnav/cnav/
    rngchip/chip 六族）；块内断言锚 outline+CanvasText（系统配色
    令牌——写死色值在 forced-colors 下被二次覆盖）。"""
    assert "forced-colors: active" in _SRC or "forced-colors:active" in _SRC
    # 块体：从 media 开头到下一个 } 前须含六族选择器与 outline 声明
    i = _SRC.find("forced-colors")
    assert i > 0
    body = _SRC[i:_SRC.find("}", _SRC.find("CanvasText", i))]
    for sel in (".mtab.on", "#tabs span.on", "#mainnav span.on",
                ".cnav.on", ".rngchip.on", ".chip.on"):
        assert sel in body, (sel, body[:200])
    assert "outline" in body and "CanvasText" in body


def test_filter_chip_toggles_write_aria_pressed():
    """筛选片四处切换点（togDate/togRoute/togChip/togPlat）回写
    aria-pressed——程序态与视觉态同拍，读屏可辨当前筛选档。"""
    for fn in ("function togDate(", "function togRoute(",
               "function togChip(", "function togPlat("):
        i = _SRC.find(fn)
        assert i > 0, fn
        body = _SRC[i:_SRC.find("\nfunction ", i + 4)]
        assert "aria-pressed" in body, fn


def test_filter_chip_templates_carry_initial_aria():
    """重建模板（buildDateChips/buildRouteChips/buildChips 的 chip
    串）带 aria-pressed 初始态——10s 轮询重建曾只翻类丢程序态
    （多入口共享件静态初始值是假单源，LESSONS 二十§1）。"""
    for anchor in ("box.innerHTML='<span class=\"chiplab\">日期：</span>'",
                   "box.innerHTML='<span class=\"chiplab\">航线：</span>'"):
        i = _SRC.find(anchor)
        assert i > 0, anchor
        tail = _SRC[i:i + 400]
        assert "aria-pressed" in tail, anchor
    # 渠道片模板（buildChips 内 chip 串）
    i = _SRC.find("const b=badge(p);")
    assert i > 0
    tail = _SRC[i:i + 400]
    assert "aria-pressed" in tail, tail[:200]


# ---- merged from tests/test_v1590_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui_full_src()


def test_savebar_toggle_before_view_early_return():
    """P1-1：savebar toggle 必须在 800ms 巡检的视图早退之前——
    cfg 弄脏切监控后浮条回收（泄漏钉；锚定 dirty 巡检段内顺序，
    全文件首个同款早退在别的函数属正常）。"""
    src = _src()
    seg = src.find("setInterval(()=>{\n  const dirty=cfgIsDirty()")
    assert seg != -1, "dirty 巡检段缺失"
    i_sb = src.find("const sb=$('savebar')", seg)
    i_ret = src.find("if(VIEW!=='cfg')return;", seg)
    assert i_sb != -1 and i_ret != -1, "savebar 巡检段缺失"
    assert i_sb < i_ret, "savebar toggle 仍在视图早退之后（浮条泄漏回归）"


def test_dark_qual_stl_contrast_lift():
    """P2-1：暗色 qual 行内 .stl 子行提亮单点规则在场（4.48→≥4.5）；
    r227 同底 .stoptag 同病成对收编同一条规则（行为钉 uitest
    「暗色 qual 行 stoptag 提亮」在守）。"""
    assert ('html[data-theme="dark"] tr.qual .stl,\n'
            ' html[data-theme="dark"] tr.qual .stoptag{color:#8ba0b4}'
            ) in _src()


def test_hc_touch_target_36px():
    """P2-2：.hc 热区纵向 -11px（35→37px 过触控基准；横向 -1px 防串格）。"""
    assert ".hc::after{content:'';position:absolute;inset:-11px -1px}" in _src()


def test_header_switches_screen_reader_state():
    """P2-3：三开关回设点各补读屏播态（ntBtn/denBtn 布尔 pressed、
    themeBtn 三态用 aria-label 带当前态名）。"""
    src = _src()
    assert "aria-pressed" in src
    assert "setAttribute('aria-pressed',NT.on?'true':'false')" in src, \
        "ntBtn 缺 aria-pressed 回设"
    assert "setAttribute('aria-label'" in src and "跟随系统" in src, \
        "themeBtn 缺带态 aria-label 回设"
    assert "setAttribute('aria-pressed',d==='compact'?'true':'false')" in src, \
        "denBtn 缺 aria-pressed 回设"


def test_age_policy_title_eligibility_wording():
    """agePolicy title 扩「资格受限」语义（会员/年龄合并词面同格）。"""
    src = _src()
    assert "资格受限专享价" in src, "title 未扩资格受限语义"
    assert "年龄受限专享价" not in src, "旧「年龄受限」词面残留"
