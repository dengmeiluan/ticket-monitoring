# -*- coding: utf-8 -*-
"""v1.5.302: compact console layout, unified chart hover, idempotent filters."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_radar_hover_tracks_nearest_time_across_plot_width():
    src = _src()
    for s in (
        'id="spMonCross"',
        ".spmon-cross{position:absolute",
        "if(mx<gg.padL||mx>gg.W-gg.padR||my<gg.padT||my>gg.H-gg.padB)",
        # r373：命中按横轴取最近点（X 主键、Y 次键），
        # 二维最近点在曲线稀疏/鼠标离点较远时会漏选；r374 收敛进 PCHART.pick。
        "const d=dx*1000+dy;",
        "const x=$('spMonCross');if(x)x.style.display='none'",
    ):
        assert s in src, s
    assert "d<=441" not in src
    # 十字线左缘＝画布偏移 + 绘图内 x，且两条分支（K 线桶 / 折线）都必须
    # 跟变量而不是常量。变量名随实现变化过（gx → x0/mx），所以这里断
    # 言结构而非名字；负控实测：改成 `cross.style.left='626px'` 必须变红
    # （曾用前缀断言 `offsetLeft+`，常量写法照样通过 → 空转）。
    import re as _re
    _lhs = _re.findall(r"cross\.style\.left=Math\.round\(c\.offsetLeft\+([A-Za-z_$][\w$]*)\)", src)
    assert len(_lhs) >= 2, "十字线定位分支少于 2 处（K 线/折线）：%r" % (_lhs,)
    assert "cross.style.left='" not in src, "十字线位置被写成了常量"


def test_search_kpi_facet_and_date_filters_are_idempotent():
    src = _src()
    for s in (
        "const on=!SRX.f.onlyQual;",
        "SRX.f.missing=!SRX.f.missing",
        "const same=Array.isArray(cur)?false:(String(cur)===''?false:String(cur)===String(v));",
        "SRX.date=(dv&&SRX.date===dv)?'':dv;",
        "SRX.f[k]=Array.isArray(SRX_DEFAULT_F[k])?[]:(typeof SRX_DEFAULT_F[k]==='boolean'?false:'')",
        "background:var(--r-blue-soft)!important;box-shadow:inset 0 -2px 0 var(--r-blue)!important",
    ):
        assert s in src, s


def test_search_header_is_compact_and_source_strip_is_a_table():
    src = _src()
    for s in (
        '<div class="srx-hero-copy" id="srxHeroCopy">',
        "let po='0';try{po=localStorage.getItem('jpsrx_probeopen2')||'0'}",
        "#searchview .srx-capbar{display:flex!important;background:transparent!important;border:0!important;",
        "#searchview .srx-probe:not(.open) .srx-probeacts>*:not(.srx-probe-toggle){display:none!important}",
        "#searchview .srx-kpi{display:inline-flex!important",
        "#searchview .srx-src+.srx-src{border-left:1px solid var(--r-hair)!important",
        "grid-auto-flow:column!important",
        "#searchview .srx-src-a{display:none!important}",
    ):
        assert s in src, s


def test_watch_uses_the_same_compact_summary_and_no_duplicate_routewatch():
    src = _src()
    for s in (
        "#montab-watch .ws-kpi{flex:1 1 0!important",
        "#montab-watch .ws-kpi .f{display:none!important}",
        "#montab-watch .ws-routewatch{display:none!important}",
        # r374：三处走势画布统一 240（原独立 200/178，同一产品三种高度）
        "#montab-watch .ws-chartwrap{height:clamp(240px,max(38vh,28vw),360px)!important;min-height:160px!important}",
        "#montab-watch .ws-route{min-height:44px!important",
    ):
        assert s in src, s


def test_search_overview_summary_bar_is_desktop_only_and_collapsible():
    """r374：概览收成「标题行摘要 + 唯一开合钮 + 正文」一个区块。

    窄屏不再用 show-overview 第二套开关（两套状态必然漂移），
    移动栏「概览」改为调同一个 srxToggleOverview，正文由
    srx-ov-collapsed 单点控制显隐。
    """
    src = _src()
    for s in (
        'id="srxOvSum"',
        'id="srxOvHero"',
        "function srxRenderOv()",
        "function srxToggleOverview()",
        # r433：概览开合只管自己。原先这里还写 localStorage 记「上次是否收起」，
        # 但全仓没有任何读取方（每次加载都从默认态起），是一次空写入；
        # 更关键的是同函数里还调 srxRenderCtx()，开合概览会连带重算下方
        # 筛选区的折叠态——保留这条断言守的是「互不越权」而不是持久化。
        "const on=v.classList.contains('srx-ov-collapsed')",
        # r383：开合只收「价带天数条 + 其后正文」，标题行常驻
        "#searchview.srx-ov-collapsed #srxBandBody,",
        "hb.textContent=on?'收起概览':'展开概览'",
        "#searchview #srxOvSum{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis",
    ):
        assert s in src, s
    # 第二套窄屏开关必须彻底退场
    assert "show-overview" not in src


def test_mobile_search_toolbar_is_one_scrollable_row_not_a_two_column_grid():
    src = _src()
    for s in (
        "@media(max-width:560px){\n #searchview .srx-hero{padding:2px 2px 4px!important",
        "#searchview .srx-hero-act{display:flex!important;grid-template-columns:none!important;flex-wrap:nowrap!important",
        "#searchview .srx-hero-act:not(.open) .srx-btn[data-sec].srx-keep{display:none!important}",
        "#searchview .srx-hero-act.open .srx-btn.srx-keep[data-sec]{display:inline-flex!important}",
        "@media(max-width:360px){",
    ):
        assert s in src, s


def test_mobile_watch_gives_first_screen_to_the_chart_and_empty_filter_bar_stays_hidden():
    src = _src()
    for s in (
        "#montab-watch .ws-sub{display:none!important}",
        "#montab-watch .ws-routebar-h{display:none!important}",
        "#montab-watch .ws-chart-foot{display:none!important}",
        "if(!head&&!chips){el.innerHTML='';return}",
    ):
        assert s in src, s


def test_narrow_watch_kpi_values_never_wrap():
    """320 档四格 KPI 值必须单行：守 nowrap、单位不参与收缩、字号低于桌面三条。

    原断言把 15px 写死；字号阶统一后该档随七阶走 16px。
    nowrap 只写容器还不够——单位 `<span>` 是 flex 子项，被压窄后在内部
    折行（实测 320 档「3.5 /」+「5」两行、单元格 18→30px），所以
    `flex:none` 也是本契约的一部分。
    """
    import re
    src = _src()
    m = re.search(r"#montab-watch \.ws-kpi \.v\{font-size:(\d+)px!important;white-space:nowrap!important\}", src)
    assert m, "320 档关注 KPI 值缺 nowrap 单行钉"
    assert int(m.group(1)) < 18, "320 档 KPI 字号 %spx 未小于桌面 18px，四格会挤行" % m.group(1)
    assert "#montab-watch .ws-kpi .v span{flex:none!important}" in src, \
        "320 档 KPI 单位必须 flex:none，否则「3.5 / 5」仍折成两行"
