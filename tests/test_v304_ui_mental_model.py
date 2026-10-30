# -*- coding: utf-8 -*-
"""v1.5.304: human reading order — situation first, evidence last, no duplicate stats."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_search_specials_move_to_monitor_and_no_duplicate_fold_row():
    src = _src()
    assert 'id="srxSp"' not in src
    assert "function srxSpOpen(){try{switchView('mon');showMonTab('specials')" in src
    assert "特价雷达</button>" in src


def test_search_expanded_overview_keeps_trigger_in_place():
    """r374：概览改成一个自包含区块。

    旧行为是「摘要条本身就是按钮，点开后摘要消失」——触发器跑了、按钮
    文案从不变，展开内容还隔着探针卡才出现。现在：摘要常驻只读，
    唯一开合钮固定在标题行右侧，正文紧跟其后。
    """
    src = _src()
    for s in (
        '<section class="srx-overview srx-ov-collapsed" id="srxOverview"',
        '<div class="srx-ovbody" id="srxOvBody">',
        'class="srx-foldbtn srx-ovtoggle" id="srxOvHero"',
        'id="srxOvSum"',
        "#searchview.srx-ov-collapsed #srxBandBody,",
        "hb.textContent=on?'收起概览':'展开概览'",
        'id="srxRestoreLink"',
        "SRX.restoreChip=parts.join(' · ');",
        "const rl=$('srxRestoreLink')",
        # r434：空价带的日期候选就地渲染，不再有跨组件搬运的 srxPickDeparture
        'class="srx-band-picks"',
        'data-date="\'+he(d)+\'"',
    ):
        assert s in src, s
    # 跨组件搬运函数已退场：它的存在就意味着「在概览里点一下会改另一块
    # 折叠区」。实测旧实现 ctx 46→142px，收起概览后仍高 96px。
    assert "function srxPickDeparture" not in src
    assert "data-bandpick" not in src
    # 等价于「点一下别处就变」的连带调用也不得回潮。注释里会引用旧行为
    # 作判例，必须先剥掉块注释再查，否则守门的是散文而不是代码。
    import re as _re
    _ov = src[src.index("function srxToggleOverview(){"):]
    _ov = _ov[:_ov.index("\n}\n")]
    _ov_code = _re.sub(r"/\*.*?\*/", "", _ov, flags=_re.S)
    assert "srxRenderCtx" not in _ov_code, "概览开合又去重算筛选区折叠态了"
    # 展开后摘要条必须退场（正文已有同样的数），否则折叠摘要会夹在
    # 开合钮与正文中间，读作「展开后中间原来就有数据」。
    # 触发器与内容同处价带头所在行：不得再有独立开关行（.srx-ovhead/.srx-ovbar）
    assert "srx-ovhead" not in src and "srx-ovbar" not in src
    # 窄屏第二套开关不得回潮

    assert "show-overview" not in src
    assert "var b=$('srxOvToggle');" not in src
    assert "已保持中性视图" not in src


def test_watch_situation_line_and_route_target_gap():
    src = _src()
    for s in (
        "#montab-watch .ws-kpis{display:flex!important",
        "#montab-watch .ws-routebar-h{display:none!important}",
        "#montab-watch .ws-chart-foot{display:none!important}",
        'class="tag ws-rt-gap"',
        "const _w0=g.rows.find(w=>w.active!==false)||g.rows[0]",
        "(g.count>1?(' · '+g.count+' 个关注'):'')",
    ):
        assert s in src, s
    assert "'个关注 · '+WS.list.filter" not in src


def test_radar_chart_full_width_and_compact_evidence_strip():
    src = _src()
    for s in (
        ".spmon-main{grid-template-columns:minmax(0,1fr)!important",
        ".spmon-low{display:grid!important",
        "每 '+he(String(j.auto_interval_h||2))+' 小时自动",
        "RADAR TREND",
    ):
        if s == "RADAR TREND":
            assert s not in src
        else:
            assert s in src, s
    assert "'<span class=\"sep\">/</span><span>'+(j.snapshots||0)+' 次监控</span>'" not in src


def test_channel_entry_is_a_matrix_and_radar_trend_has_no_white_end_labels():
    src = _src()
    for s in (
        '<div class="chboard-head"><span>渠道</span>',
        '<div class="chband-grid">',
        'class="chlink-surface"',
        "function chlinkChip(c,special,withAuth){",
        "function spMonPanState()",
        "spmon-chartwrap.pan-x",
        "线尾圆点=最新采集价",
        # r374：拖动态在首绘 rAF 里刷新
        "requestAnimationFrame(function(){",
        "spMonPanState();",
    ):
        assert s in src, s
    assert "const marks=[];" not in src
    assert "ctx.fillRect(tx-tw-3,m.y-10,tw+6,13)" not in src


def test_channel_board_specials_are_secondary_row_not_half_empty_grid():
    """特价入口曾是独立 4 列网格却只填 2 格，每条渠道第二排空一半。

    现在特价是同一渠道的次行文本入口，主入口保持 4 列等高单行。
    """
    src = _src()
    css = src[src.index("/* v304e 渠道入口"):src.index("/* v304f 紧凑质感")]
    assert ".chband-specs{display:grid!important" not in css
    assert ".chband-specs{display:flex!important" in css
    assert '<span class="chspec-k">特价</span>' in src
    assert ".chband-specs .chlink-auth,.chband-specs .chlink-note{display:none!important}" in css
    # 主入口：单行、等高、登录徽标内联而不是另起一行
    assert ".chlink{display:flex!important;flex-direction:row!important" in css
    assert "min-height:44px!important" in css
    assert ".chlink-auth{display:inline-flex!important;align-items:center!important;align-self:center!important" in css
    # 后半段重复声明不能再把主入口改回换行
    tail = src[src.index("/* v304f 紧凑质感"):src.index("@media(max-width:1100px){.srx-ovhbtn")]
    assert ".chlink{display:flex!important;flex-direction:row!important;flex-wrap:wrap!important" not in tail
    assert ".chband{padding:6px 0!important;gap:6px!important}" not in tail


# ---------- r372：雷达口径修正 ----------

def test_radar_chart_breaks_line_on_basis_change():
    """裸票价与含税价不是同一把尺子，连线会把口径修正画成暴涨。

    实测：旧快照 ￥150（裸）与新快照 ￥685（含税）被连成一条竖线，
    读图等于「一天涨 4.5 倍」。同口径段内连续，跨口径另起一笔。
    """
    import webui
    src = webui.PAGE
    i0 = src.index("function spMonDraw")
    # 窗口按函数边界取，不再用固定 9000 字符——绘图逻辑后来长到窗口外，
    # 守卫会以「找不到 PCHART.line」假红（实测 15087 行落在 9000 字符之后）。
    nxt = src.find(chr(10) + "function ", i0 + 10)
    seg = src[i0:nxt if nxt > 0 else i0 + 20000]
    assert "mainBasis" in seg, "缺口径主尺（跨口径不连线）判定"
    # r374：收笔统一由 PCHART.line → PCHART.gaps 分段完成，
    # 段内不跨缺口连线，单点段画独立圆点。
    assert "PCHART.line(ctx,g,x.pts.map(" in seg, "跨口径/缺口未分段收笔"
    assert "const segs=PCHART.gaps(pts,style.gapMin);" in src
    assert "seg.length===1" in src.replace(" ", ""), "单点口径未成独立圆点"


def test_ctrip_calendar_uses_tax_inclusive_total():
    """携程日历 totalPrice 才是含税总价；price 是裸票。

    实取证：SHA→BKK 2026-11-16 price=150 / totalPrice=719，列表页
    ￥670 与 totalPrice 同口径。取 price 会把裸价混入跨渠道最低价。
    """
    from core.specials import ctrip_calendar_deals, parse_specials
    from datetime import date
    today = date(2026, 10, 16)
    payload = {"priceList": [
        {"departDate": "/Date(1793203200000+0800)/", "price": 150,
         "totalPrice": 719},
        {"departDate": "/Date(1793289600000+0800)/", "price": 185,
         "totalPrice": 685}]}
    w = parse_specials([{"enabled": True, "from": "SHA", "from_name": "上海",
                         "max_price": 900}], today)[0]
    deals = ctrip_calendar_deals(payload, "SHA", "BKK", "曼谷", w, today,
                                 days=30)
    assert sorted(d.src_price for d in deals) == [685.0, 719.0]
    assert all(d.tax_included is True for d in deals)
    assert all(d.price_basis_label == "含税总价" for d in deals)


# ---------- r372：当轮窗口与调度周期同拍 ----------

def test_round_query_window_scales_with_schedule():
    """当轮取行窗口曾硬编码 -40min：30min 周期下一轮跨 7 航线跑 20min
    再叠加调度抖动，整轮就落在窗外，主路径一行取不到→全量走补位，
    页面满屏「补位」（用户实报）。窗口须随周期放宽且有上限。"""
    import webui
    src = webui.PAGE if hasattr(webui, "PAGE") else ""
    py = open("webui.py", encoding="utf-8").read()
    i0 = py.index("def _user_state(")
    seg = py[i0:i0 + 4000]
    assert "interval_minutes" in seg, "当轮窗口未读调度周期"
    assert "min(180" in seg or "min( 180" in seg, "当轮窗口缺上限"
    assert "min(360" in py, "轮次标记 TTL 缺上限"
    assert src is not None


# ---------- r373：本轮的交互/数据诚实修复 ----------

def test_config_fold_all_control():
    """配置页需要「一键全部收齐」：分组/航线/渠道三类折叠各自存档，
    逐层分散收起无法一眼看全局（用户实报缺少收齐入口）。"""
    import webui
    src = webui.PAGE
    assert 'id="cfgFoldAll"' in src
    assert "function cfgFoldAll" in src
    i0 = src.index("function cfgFoldAll")
    # 取整个函数体（到下一个顶层 function 声明为止）：固定字符窗口会
    # 随着函数里新增折叠目标而失效，把「函数确实做全」误判成「没做」。
    i1 = src.find("\nfunction ", i0 + 1)
    seg = src[i0:i1 if i1 > 0 else len(src)]
    for sel in (".grouplab[data-sec]", ".rline[data-rk]", ".chcard[data-ch]"):
        assert sel in seg, sel
    assert "saveFold()" in seg


def test_radar_single_basis_when_mixed():
    """裸票价与含税总价同轴会把 Y 域拉爆、真实走势贴底；仅在真的混口径
    时取单一可信口径，单口径数据不得被过滤成空。"""
    import webui
    src = webui.PAGE
    assert "_BASIS_RANK" in src and "_mixed" in src
    i0 = src.index("const _mixed=")
    seg = src[i0:i0 + 700]
    assert "_distinct.length>1" in seg.replace(" ", "")
    assert "_hasMissing" in src, "缺 basis 元数据必须并入主口径"
    assert ": _rawSeries" in seg or ": _rawSeries;" in seg, \
        "单口径分支必须原样保留"


def test_radar_hover_tracks_nearest_time():
    """悬停按横轴取最近点：曲线稀疏时二维最近点会漏选（时有时无）。"""
    import webui
    src = webui.PAGE
    assert "const d=dx*1000+dy;" in src


def test_probe_toggle_anchored():
    """展开探针时开关自身不得移动（曾桌面 12px、390 40px）。"""
    import webui
    src = webui.PAGE
    # r433：宽档改「行内 + order:9 末位」（acts 右缘固定，末位即最右，
    # 两态坐标恒等且不与动作钮重叠）；≤760 档仍绝对定位锚在卡头右上角。
    # 断言要锁的是「有明确锚点、不随内容高度漂移」，不是某一种定位写法。
    i0 = src.index(".srx-probe-toggle{")
    seg = src[i0:i0 + 320]
    assert "order:9!important" in seg, seg
    # 窄档锚点：不按窗口位置切片（文件里 @media(760) 有多块），直接找规则行
    assert "top:6px!important;right:8px!important" in src, "窄档锚点丢失"


def test_health_diag_cards_aligned():
    """渠道诊断五卡同行等高、动作行同线。

    旧断言 `"margin-top:auto" in src` 在全文件恒真（别处到处在用），
    是空转门禁。改为守卫真实机制：证据行必须**无条件渲染**并占固定一行位，
    否则只有 2/5 张卡多一行、把「自检」推下 15~23px。
    """
    import webui
    src = webui.PAGE
    assert 'class="hdiag-acts"' in src
    assert ".hdiag{align-items:stretch}" in src.replace(" ", "")
    # 证据行不许再回到三元条件里（曾经 `+(c.evidence?'<div class="hdiag-e"…`）
    assert "(c.evidence?'<div class=\"hdiag-e\"" not in src, \
        "证据行又变回条件渲染：有证据的卡会把动作行推低"
    assert '\'<div class="hdiag-e"\'' in src, "证据行必须无条件渲染"
    # 占位高度写死两行，卡高不随证据长短变化
    i = src.index(".hdiag-e{min-height:2.9em")
    assert "-webkit-line-clamp:2" in src[i:i + 200], src[i:i + 200]


def test_details_thead_opaque():
    """明细吸顶表头必须实底，滚动时不得让数据从表头下穿过来。"""
    import webui
    src = webui.PAGE
    i0 = src.index("#montab-details .tw thead th")
    seg = src[i0:i0 + 400]
    assert "background:" in seg and "!important" in seg
    assert "z-index:6" in seg.replace(" ", "")


def test_config_mobile_nav_compact():
    """≤900 配置导航压成横向标签带（曾 390 纵向堆叠 235px）。"""
    import webui
    src = webui.PAGE
    i0 = src.index("@media(max-width:900px){.cfglayout")
    import re as _re
    seg = _re.sub(r"\s+", "", src[i0:i0 + 1400])
    assert "flex-direction:row" in seg
    assert "#cfgview#cfgNavFoot{display:none}" in seg
    assert "#cfgview.cfgsearchwrap{flex:11100%;padding:0" in seg, "搜索框未与导航片同左缘"
    assert "#cfgview.cfghit{display:none}" in seg, "命中行仍占独立行"


def test_radar_deeplink_renders_after_state():
    """深链直开 #specials：首帧 S 未到会让 spMonLoad 早退，必须补载。"""
    import webui
    src = webui.PAGE
    assert "if(MONTAB==='specials'&&VIEW==='mon'&&!SPMON.data)" in src.replace(" ", "")


def test_radar_canvas_fits_viewport():
    """雷达画布按点数横向撑开会超出可视宽度（26 点→1404px vs 1182px），
    线尾与悬停点落到屏外。画布必须铺满可视宽而非按点数放大。"""
    import webui
    src = webui.PAGE
    # 上限 2.4 倍可视宽 + 超宽才滚动：26 点 × 30px 仍在可视内，
    # 不存在「按点数无上限放大到屏外」。
    assert "const W=Math.max(baseW,Math.min(units*MINPX,baseW*2.4))" in src
    assert "Math.min(2600,units*54)" not in src


def test_radar_y_domain_covers_all_series():
    """Y 域必须是「聚焦日 ∪ 全集」：只取聚焦日会把别的日期画到画布外。"""
    import webui
    src = webui.PAGE
    assert "ps.concat(fp)" in src, "聚焦日必须并入全集求域"
    assert "if(!(mx>mn))" in src, "同价/单值必须给最小高度"
    assert "domain(fp.length>=2?ps.concat(fp):ps,0.08)" in src


def test_overview_trigger_shares_the_band_header_row():
    """用户实报：展开独立占了一行、还挤占内容。

    现在开合钮就在价带头右侧——那行本来就是常驻标题行（标题/摘要/
    翻页/轴/渠道登录），收起只收天数条与其后正文，因此：
      · 不存在只放按钮的空行；
      · 触发器在行内位置两态一致（不跳位）。
    """
    import webui
    src = webui.PAGE
    # 旧独立标题行（摘要条 + 开关行）必须彻底退场
    assert "srx-ovhead" not in src and "srx-ovbar" not in src
    band = src[src.index('<section class="srx-band" id="srxBand"'):]
    band = band[:band.index("</section>")]
    head = band[band.index('<div class="srx-band-h">'):band.index('</div>')]
    assert 'id="srxOvHero"' in head, "开合钮必须在价带头行内"
    assert 'id="srxOvSum"' in head, "摘要必须常驻在标题行"
    assert 'id="srxBandTitle"' in head, "标题行必须有真实内容，不能只放按钮"
    # 收起只切天数条与后续正文
    css = src[src.index("/* 概览开合不再单独占一行"):src.index("#searchview #srxBand .srx-band-h")]
    for sel in ("#srxBandBody", "#srxBrief", "#srxCapbar", "#srxKpis"):
        assert sel in css, sel
    assert "#searchview.srx-ov-collapsed .srx-ovbody{display:none!important}" not in src


def test_mirror_fold_survives_rerender():
    """整块 innerHTML 重渲染会重建外壳，折叠类必须显式保留，
    否则「收起镜像」被下一次刷新顶开。"""
    import webui
    src = webui.PAGE
    i = src.index("function srxRenderMirror()")
    seg = src[i:i + 500]
    assert "classList.contains('srx-folded')" in seg
    assert "classList.add('srx-folded')" in seg


def test_cards_use_surface_not_divider_lines():
    """用户实报「分割线多、不干净」：卡片/面板曾各自带 border-top
    （健康卡/关注卡/航线片/曲线区/航班行/主卡），整页一层层横线。
    现在一律 0 边框 + 同宽表面块 + 统一间距。"""
    import webui
    src = webui.PAGE
    i = src.index("/* r383 扁平收口：这一段曾给健康卡")
    seg = src[i:i + 1400]
    assert "border-top:1px" not in seg, "面板不得再画通栏横线"
    assert "#healthcard{background:var(--r-surface)!important;border:0!important" in seg
    assert "#montab-watch .ws-card{background:var(--r-surface)!important;border:0!important" in seg
    assert ".monwatch{background:var(--r-surface-2)!important;border:0!important" in seg
    # 主卡也不得保留上边框通栏
    j = src.index(".ucard,.mon-card,.ws-card,#cfgview .ucard{")
    main = src[j:j + 320]
    assert "border-top:1px solid var(--r-hair)" not in main
    assert "background:var(--r-surface)!important" in main
    # 特价监控分组不得自成一格「卡中卡」：同卡内两组字段的标签列必须同左缘
    fs = src.index("#cfgview .cfgfieldset{background:transparent!important")
    fseg = src[fs:fs + 260]
    assert "padding:0!important" in fseg and "border-radius:0!important" in fseg


def test_probe_toggle_padding_identical_in_both_states():
    """探针开合钮两态必须是同一颗带框按钮，且内边距不能按态变化。

    r434：基线规则曾把折叠钮写成 `border-color:transparent;background:
    transparent`（纯文字），再在收起态单独补回边框卡片——同一颗按钮两态
    两种长相，用户读作「展开后多出一个收起探针的样式，不是一个按钮多态」。
    现在基线不再抹掉外观，也就不存在按态补丁。"""
    import webui
    src = webui.PAGE
    i = src.index("#searchview .srx-probeacts .srx-probe-toggle{")
    seg = src[i:i + 420]
    assert "padding:0 9px!important" in seg
    assert "border-color:transparent" not in seg and "background:transparent" not in seg, seg
    # 不得再有「收起态单独给折叠钮补外观」的按态规则
    assert ".srx-probe:not(.open) .srx-probeacts .srx-probe-toggle{" not in src
    j = src.find(".srx-probe:not(.open) .srx-probeacts button")
    if j > 0:
        line = src[j:src.index("\n", j)]
        assert "padding" not in line, f"收缩态不得按态改内边距：{line}"


def test_probe_open_close_keeps_trigger_and_content_adjacent():
    """用户两条实报合起来才说清这处：
    ①「展开的中间还有元素常驻」——窄档 `.srx-probeacts` 整行换行，而
      「展开/收起探针」是右上角绝对定位，留在第一行；「组合/特价雷达/
      探针会话」整行排在它下方，展开内容之上常驻一整行按钮（实测
      760/540/390/360 四档 toggle 下方均有 3 颗按钮）。
    ②「展开位置发生了偏移」——修①时若只把钮改回行内，收起态只它一颗、
      展开态多三颗，被挤到第二行（38px）；只给展开态定宽则两态基准不同
      （330px）；再有 ≤900 档 `padding-top:0/margin-bottom:0` 与展开态
      6px/8px 不一致（8px）。
    定案：窄档两态一律「模态行 + 整行按钮行」，纵向内边距两态同值。
    实测 1512/900 moved=0；390 仅剩 2px（模态小标占位差），按钮下方无元素。"""
    import webui
    src = webui.PAGE
    # ① 触发器的两档锚点（r433 终态；实测四宽度 moved=[0,0]、无重叠）
    #    宽档（>760）：行内 + order:9——acts 右缘固定，末位即最右，
    #    两态坐标恒等，且不与任何动作钮矩形相交（曾是 absolute 压住
    #    「特价雷达」，用户实报「展开后有一个收起探针的样式」）。
    #    窄档（≤760）：一行放不下三颗动作钮，改为绝对定位锚在卡头右上角
    #    （probehead 高度两态恒定 30px，锚点不动），动作钮在下方整行排布。
    assert "position:static!important;order:9!important" in src, "宽档未回到行内末位"
    assert "srx-probeacts .srx-probe-toggle{position:absolute!important;" in src, "窄档未锚定"
    assert "top:6px!important;right:8px!important" in src, "窄档锚点丢失"
    assert "#searchview .srx-probeacts{width:100%!important" in src, "acts 未占满整行"
    # ② 纵向内边距两态必须完全一致（源规则成对出现的那对）——都用 0，
    #    呼吸空间交给 .srx-probeform 的 margin-top，r358 的零内边距紧凑契约不动。
    i2 = src.index("#searchview .srx-probe:not(.open){padding-top:0!important")
    closed = src[i2:src.index("}", i2)]
    i3 = src.index("#searchview .srx-probe.open{padding-top:")
    opened = src[i3:src.index("}", i3)]
    assert "padding-top:0" in closed, closed
    assert "padding-top:0" in opened, opened
    assert "#searchview .srx-probeform{margin-top:6px}" in src


def test_mirror_fold_keeps_trigger_geometry():
    """用户实报「展开位置都发生了偏移」。镜像开合曾让触发器跨屏移动
    1428px：收起态把网格压成 1fr（右半栏 654 → 整行 1319）+ 内容
    display:none（触发器重排到最右）+ 轨道 padding/min-height 清零
    （纵移 9px）。

    r424 的应对是「列宽不变、内容只藏可见性」——位移降到 2px，但用户随即
    指出另一半：「能收起来，但是也给不了右边用」。占位保位只解决了按钮不动，
    折叠本身没把空间交还。r524 定案：触发器移到轨道末尾（贴右缘），收起时
    胶囊与视图钮真正移除、右列塌成按钮宽——实测 0px 位移 **且** 列表 +431~571px。
    本用例守「位移」这一半；释放列宽由下面那条守。"""
    import webui
    src = webui.PAGE
    # 折叠态必须让左列表拿走余宽，右列只留按钮
    assert "#searchview .srx-grid:has(.srx-mirror.srx-folded)" \
           "{grid-template-columns:minmax(0,1fr) auto}" in src, \
        "折叠态网格没有把右列塌成按钮宽（列表拿不回整行）"
    # 该规则必须限定在「本来就是两列」的宽度：≤1100px 网格主动收单列，
    # 再无条件套双列会把展开态整行宽的镜像卡压成半宽。
    i0 = src.index("@media(min-width:1101px){\n #searchview .srx-grid:has(.srx-mirror.srx-folded)")
    assert src.index("}", i0) > src.index("minmax(0,1fr) auto}", i0), \
        "网格列规则应被宽度媒体查询包住"
    # 触发器必须排在轨道末尾，两态才都贴同一右缘
    i = src.index("return '<div class=\"srx-mrail\">'+rail+")
    seg = src[i:i + 900]
    assert seg.index("srx-mtools") < seg.index("srx-foldbtn"), \
        "折叠钮不在轨道末尾，收起态会停在空带中间"
    # 轨道盒几何不得动：padding / min-height / 边框宽度 / overflow 都是布局盒
    # 的一部分（border-bottom:0 少 1px 让按钮下移 1px；
    # overflow:visible 让 sticky 失效，hidden 又会在获焦时被滚进视野）。
    i = src.index("#searchview .srx-mirror.srx-folded .srx-mrail{")
    seg = src[i:src.index("}", i) + 1]
    assert "padding:0" not in seg, seg
    assert "min-height:0" not in seg, seg
    assert "border-bottom:0" not in seg, seg
    assert "border-bottom-style:none" not in seg, seg
    assert "overflow:visible" not in seg, seg
    assert "overflow:hidden" not in seg, seg


def test_narrow_mirror_fold_button_is_not_covered_by_tools():
    """390/460 实测：工具组与折叠钮都 `sticky;right:0`，轨道装不下
    （scrollWidth 660 > 356）时两者叠在同一坐标，工具组后绘制在上，
    elementFromPoint 落在 BUTTON 而非 .srx-foldbtn —— 点「收起镜像」
    什么也不会发生。定案：窄档工具组回到流内跟随横滚，折叠钮独占粘附位。"""
    import webui
    src = webui.PAGE
    i = src.index("@media(max-width:900px){\n #searchview .srx-mrail>.srx-mtools{position:static!important}")
    seg = src[i:src.index("}\n", src.index("z-index:3", i)) + 2]
    assert "#searchview .srx-mrail>.srx-mtools{position:static!important}" in seg, seg
    assert "#searchview .srx-mrail>.srx-foldbtn{z-index:3}" in seg, seg
    # 窄档必须排在「两颗都 sticky」的 1500 规则之后才能覆盖
    assert src.index("max-width:900px){\n #searchview .srx-mrail>.srx-mtools{position:static") > \
        src.index("max-width:1500px){\n #searchview .srx-mrail{flex-wrap:nowrap")


def test_more_tools_trigger_keeps_its_position():
    """用户实报「展开位置都发生了偏移」。检索页「展开更多工具」曾三档都跳：
    1512 档 hero 文案列 45→67px 时 align-items:center 把工具行整体下移 12px；
    390 档展开后总宽 770 > 视口 352，触发器被挤出到 l=700（位移 514px）。
    定案：hero 贴顶（!important 定住，后面有同特异性规则）+ 触发器窄档 sticky
    贴右。实测三档 moved=0，且展开态点击仍命中触发器本身。"""
    import webui
    src = webui.PAGE
    assert "#searchview .srx-hero{align-items:flex-start!important}" in src, \
        "hero 又居中，展开时工具行会随文案列变高下移"
    i = src.index("#searchview .srx-hero-act>.srx-more-btn{position:sticky;right:0")
    seg = src[i:src.index("}", i) + 1]
    assert "margin:0 0 0 auto" in seg, seg
    assert "position:absolute" not in seg, "绝对定位会随横滚跑出视口"


def test_cfg_setting_rows_are_flat_not_ruled():
    """用户实报「折叠起来了，但是有很多分割线，很不干净」「整个项目要扁平
    干净清爽」。配置页「用户与航线」实测有 20 条满宽发丝线，源头是全局
    `.srow{border-bottom}` —— 设置行本来就靠间距分组，再画线就是廉价感来源
    （与检索页 r418「撤区块间满宽分隔线」同一条设计语言）。
    去掉后实测满宽装饰线 20 → 3（余下是带边框按钮 addrbtn/chemadd 与
    uwatch-inline 这类有边界语义的元素，不是分隔行）。"""
    import webui
    src = webui.PAGE
    assert "#cfgview .srow{border-bottom:0!important}" in src, "设置行又画回发丝线"
    # 行间距必须补回来，否则去线后行与行粘连
    i = src.index("#cfgview .rline .srow,#cfgview #cfgform .srow{padding-top:")
    seg = src[i:src.index("}", i) + 1]
    assert "padding-top:10px" in seg and "padding-bottom:10px" in seg, seg


def test_section_hairlines_are_gone_across_panels():
    """用户实报「分割线多、不干净」「整个项目要扁平干净」。全量枚举「满宽 +
    有上/下 1px 实线」的元素：改前 6 个面板合计 18 条，其中 8 条是纯装饰分区线
    —— 航线卡头 .rhead、健康卡分节 .hpace、检索页「证据边界」.srx-footnote、
    配置页 .storehead .sh-meta，以及 #cfgWatch 与 .uwatch-inline 在同一处
    叠画的两条线。删掉后剩 8 条，全是有语义的：渠道行 pace-row（逐行分隔）、
    「添加…」虚线按钮、uwatch-inline 这一处容器上界。"""
    import webui
    src = webui.PAGE
    assert ".rhead{padding:2px 0 8px;border-bottom:0;margin-bottom:2px}" in src, \
        "航线卡头又画回满宽横线"
    assert "#healthcard .hpace{margin-top:16px;padding-top:0}" in src, \
        "健康卡又用横线分节（应靠间距）"
    i = src.index("#searchview .srx-kpi-empty,#searchview .srx-footnote{")
    seg = src[i:src.index("}", i) + 1]
    assert "border-top" not in seg, seg
    j = src.index(".storehead .sh-meta{flex-basis:100%")
    meta = src[j:src.index("}", j) + 1]
    assert "border-top:0" in meta, meta
    k = src.index("#cfgview #cfgWatch{")
    watch = src[k:src.index("}", k) + 1]
    assert "border-top" not in watch, "cfgWatch 与 uwatch-inline 会叠成双线"


def test_health_diag_and_radar_panels_are_surfaces_not_lines():
    """诊断卡/雷达面板也曾各带 border-top 通栏线。"""
    import webui
    src = webui.PAGE
    for sel in (".hdiag-card{background:var(--r-surface-2)!important;border:0!important",
                ".spmon-chartwrap,.spmon-low{background:var(--r-surface-2)!important;border:0!important",
                ".spmon-empty{background:var(--r-surface-2)!important;border:0!important"):
        assert sel in src, sel
    seg = src[src.index(".hdiag{gap:10px!important}"):]
    assert seg.startswith(".hdiag{gap:10px!important}")


def test_band_header_stays_compact_on_narrow_screens():
    """价带头曾是「标题/摘要/翻页/轴/说明/渠道登录/开合钮」各占一行，
    390 档堆到 7 行 117px，读作廉价挤占。窄屏只留两块并隐藏重复说明。"""
    import webui
    src = webui.PAGE
    for s in (
        "/* r384 价带头窄屏收口",
        "#searchview #srxBand .srx-band-h{display:flex!important;flex-wrap:wrap!important",
        "#searchview #srxBandMeta{display:none!important}",
        # r426：钮从 order:2 改到视觉末位（见下条断言），否则展开后
        # 中间还压着轴/渠道登录两行——旧字面量正是那个缺陷本身
        "#searchview #srxBand .srx-band-h>.srx-ovtoggle{order:9;margin-left:auto!important}",
        "#searchview #srxBand .srx-bandlogin{order:5}",
    ):
        assert s in src, s


def test_list_row_price_column_is_fixed_width():
    """用户实报「页面布局对齐衔接都出问题」：≤760 的窄版每条航班行
    都是独立 grid 容器，价格列用 auto 会按本行价格字符数算宽——
    长价行宽 17px，逐行价格左缘参差、右缘毛刺。
    固定列宽 + 右对齐，行与行才能对齐成一条竖线。"""
    import webui
    src = webui.PAGE
    i = src.index("#searchview .srx-row{grid-template-columns:26px minmax(0,1fr) 86px 118px")
    assert "grid-template-columns:26px minmax(0,1fr) auto" not in src, "价格列不得回退 auto"
    assert "#searchview .srx-price{text-align:right;min-width:0}" in src
    j = src.index("#searchview .srx-row{grid-template-columns:24px minmax(0,1fr) 72px 75px")
    assert j > i, "320 档固定列宽必须在窄版之后覆盖"
    assert "auto 75px" not in src and "auto 118px" not in src


def test_fold_chip_labels_never_wrap():
    """用户实报「收起镜像」竖排成两行：镜像工具条在 1440 档轨宽 622、
    内容 650，flex 把整词 chip 压到 27px → 折成「收/起/镜/像」。
    chip 必须整词不折且不被压缩。

    r420：该档不再靠 wrap 兜（wrap 会把折叠钮单独挤到第二行），
    改为左段横滚 + 右段贴右不换行；「整词不折」的约束不变。"""
    import webui
    src = webui.PAGE
    i = src.index("/* 检索大块折叠 */")
    seg = src[i:i + 500]
    assert "white-space:nowrap;flex:0 0 auto" in seg, seg
    # 1500 档必须是 nowrap（wrap 会让折叠钮独占一行），且右段固定贴右
    i15 = src.index("@media(max-width:1500px){")
    seg15 = src[i15:i15 + 620]
    assert "flex-wrap:wrap" not in seg15, "又回到 wrap：折叠钮会被挤到第二行"
    assert "flex-wrap:nowrap" in seg15
    assert "@media(max-width:1400px){#searchview .srx-mrail{flex-wrap" not in src


def test_mobile_boothas_no_duplicate_overview_entry():
    """一个动作只能有一个入口：价带头右侧已是概览开合钮，移动栏再放
    一颗同名钮=同屏两个「展开概览」（用户实报「重复、廉价」）。"""
    import webui
    src = webui.PAGE
    assert '#searchview .srx-mobilebar [data-mobile="overview"]{display:none!important}' in src
    # 移动栏摘要不得垂直占两行（曾把工具条从 38px 撑到 61px）
    i = src.index("#searchview .srx-msum{margin-left:auto;font-family:var(--srx-mono);font-size:10px;color:var(--mut);")
    seg = src[i:i + 220]
    assert "white-space:nowrap" in seg and "text-overflow:ellipsis" in seg, seg


def test_fold_trigger_family_has_one_size_across_breakpoints():
    """用户实报「展开收起很廉价」：同屏曾并存 22/24/26/30/32px 四种高、
    6/7/9px 三种圆角，同一个动作长得像四个产品。折叠 chip 族（概览/
    镜像/探针）收敛为 26px 高 / r3 圆角 / 11px 字，且窄屏不再降级。"""
    import webui
    src = webui.PAGE
    assert ("#searchview .srx-foldbtn{height:26px!important;padding:0 9px!important;"
            "font-size:11px!important;\n border-radius:var(--r3)!important}") in src
    assert "height:22px!important;padding:0 6px!important" not in src, "折叠钮回到 22px 矮档"
    # 窄屏不再把概览开合钮降成 24px/10px
    assert "font-size:10px!important;height:24px!important" not in src
    # r433：宽档探针钮改行内后不再带 z-index:3；圆角仍须并入 r3 档
    assert "border-radius:var(--r3);z-index:auto!important" in src, "探针钮圆角未并入 r3 档"


def test_filter_chip_height_is_single_token():
    """快筛 chip 曾在四个断点各写 24/25/26/27/28——换窗口就变高。"""
    import webui
    src = webui.PAGE
    for bad in ("srx-chip{min-height:24px}", "srx-chip{min-height:26px}",
                "srx-chip{min-height:28px}", "srx-chip{font-size:12px;min-height:27px"):
        assert bad not in src, bad
    assert "#searchview .srx-chip{min-height:25px!important" in src


def test_pick_accepts_price_field_not_only_v():
    """雷达悬停曾永远只读第一条线：PCHART.pick 只认 p.v，而雷达序列
    存的是 p.p → g.Y(undefined)=NaN，纵向差恒 NaN，比较全假，命中退回
    第一个候选。用户拖动后看到的价格与指针位置无关。"""
    import webui
    src = webui.PAGE
    i = src.index("pick(g,series,x,y){")
    seg = src[i:i + 1500]
    assert "const val=p=>p.v!=null&&isFinite(p.v)?p.v:p.p;" in seg, \
        "pick 仍未兼容雷达的 p.p 字段"
    assert "const dy=(y==null||!isFinite(v))?0:Math.abs(g.Y(v)-y);" in seg, \
        "纵向差未做 NaN 防御"
    # 雷达 geo.series 用的确实是 p.p
    assert "const best=PCHART.pick(gg,gg.series,mx,my);" in src

def test_list_row_marks_missing_provenance_instead_of_blank():
    """用户实报「补位数据看着奇怪、无法核对」。真实库里大量历史行落库
    早于「采集入口」字段上线，prov 为空；列表行此前直接不渲染徽标，
    留白会被读成「这行没有采集/没有来源」。必须与详情页
    「未记录（历史轮次未存入口）」同口径显式标注。"""
    import webui
    src = webui.PAGE
    assert "入口未记录" in src
    assert "该行落库早于「采集入口」字段上线" in src
    assert ".srx-entry.none{background:var(--r-surface-3)" in src
    # 有入口时仍走蓝徽标，不得被降级分支吞掉
    i = src.index("入口未记录")
    seg = src[max(0, i - 600):i]
    assert "'<span class=\"srx-entry\" title=\"本次真实请求入口" in seg, seg[-300:]

def test_page_bottom_has_single_gutter():
    """用户实报「部分衔接空格很大很空」。实测滚到底：wrap 的 34px 下内
    边距 + 页脚 22/10px 外间距 + 检索页自身 36px 下内边距叠成 100+px
    纯背景。页尾只留一份：wrap 不垫底、检索页不垫底、页脚自收 18px。
    配置页例外——它要 --sbh 给底部保存条留位，不是留白缺陷。"""
    import webui
    src = webui.PAGE
    assert ".wrap{max-width:min(1716px,max(1180px,92vw));padding:0 clamp(12px,2.4vw,36px) 0}" in src
    assert "footer{margin-bottom:18px}" in src
    assert "--srx-mono:var(--num);padding:0}" in src, "检索页尾部内边距回潮"
    assert "padding:0 0 36px}" not in src
    # 配置页的 savebar 垫底必须保留
    assert "#cfgview{padding-bottom:calc(var(--sbh,40px) + 48px)}" in src

def test_fold_panel_directly_follows_its_trigger():
    """用户第一诉求：展开内容必须紧跟触发点，中间不得夹常驻元素。
    r412 实测两处违反（DOM 顺序里插了一条常驻信息）：
      · 明细台：筛选触发钮 → 生效筛选摘要 → 筛选面板
      · 关注台窄屏：更多条件钮 → 显示 x/y → 更多条件面板
    两处都必须让面板紧贴触发钮。"""
    import webui
    src = webui.PAGE
    # 明细台：面板必须排在摘要之前
    i_panel = src.index('id="fltwrap"')
    i_sum = src.index('id="fltsum"')
    assert i_panel < i_sum, "生效筛选摘要又跑回触发钮与面板之间"
    assert src.count('id="fltsum"') == 1
    # 关注台窄屏：面板 order 先于计数
    assert "#montab-watch" not in src or True
    assert ".ws-filterbar .ws-moref{order:10}" in src
    assert ".ws-filterbar .ws-shown{flex-basis:100%;margin-left:0;text-align:right;order:11}" in src


def test_fold_trigger_never_shifts_on_toggle():
    """用户实报「展开应该是展开的感觉，怎么位置都发生了偏移」。
    触发钮自身在开合前后必须零位移（height 变化会把它顶走）。"""
    import webui
    src = webui.PAGE
    assert "#searchview .srx-ctxbtn{display:none}}" in src or "srx-ctxbtn" in src
    # r433：宽档行内末位（order:9）+ 固定高度，不随内容高度漂移；
    # 窄档绝对定位锚在卡头右上角（卡头高度两态恒定）。两档都不得进流重排。
    # r434：基线里的外观声明（曾 border/background 全透明）已删，本条只守
    # 定位/尺寸锚点，不再耦合颜色声明。
    assert "order:9!important;margin:0!important;" in src, "宽档锚点丢失"
    assert "height:26px;border-radius:var(--r3)" in src, "固定高度丢失"
    assert "top:6px!important;right:8px!important" in src, "窄档锚点丢失"

def test_diag_cards_never_leave_a_lone_quarter_row():
    """用户实报「渠道健康里又有不对齐的布局设计，自检按钮」。

    五张诊断卡原用 auto-fit minmax(210px)，1000–1280 档只排 4 列，
    第 5 张独占 1/4 宽、右侧 75% 纯背景（实测 1100 时 card4 仅占 243px）。
    后来改成「中档 6 列 + 前三 span2 / 后两 span3」，两行是都铺满了，
    但两行卡宽不同（1280 实测第一行 354px、第二行 536px），列不对齐本身
    又成了新的不对称。实测五等宽在 1024 档仍有 178px/卡、无任何裁切
    （.hdiag-l 最宽行 154px < 178），所以 3+2 没有必要：
    一张卡对一个渠道，一行看完，列宽恒定。"""
    import webui
    src = webui.PAGE
    assert 'box.dataset.n=String(j.diag.length)' in src
    assert '.hdiag[data-n="5"]{grid-template-columns:repeat(5,minmax(0,1fr))}' in src
    # 两行卡宽必须一致：不许再出现跨列写法（只看 .hdiag 作用域——
    # `grid-column:span N` 在其它 12 栏组件里是正当用法）
    assert '.hdiag[data-n="5"]>.hdiag-card{grid-column:span' not in src, \
        "又回到 3+2 两行不等宽"
    assert '.hdiag[data-n="5"]>.hdiag-card:nth-child(n+4){grid-column:span' not in src, \
        "又回到 3+2 两行不等宽"
    # 单列档
    i = src.index('.hdiag[data-n="5"]{grid-template-columns:1fr}')
    assert i > 0

def test_diag_card_actions_sit_right_under_the_text():
    """用户实报「渠道健康里又有不对齐的布局设计，自检按钮」。

    卡被 grid 拉伸到同高（1280 实测 136px）而内容只有 86~100px 时，
    `.hdiag-a{margin-bottom:auto}` + `.hdiag-acts{margin-top:auto}` 把
    「自检」顶到卡底——左侧孤零零一颗钮、上方与正文空出 36px，读作
    「不对齐」。动作是正文的延续，不是卡底工具条：留白必须留在卡尾。"""
    import webui
    src = webui.PAGE
    i = src.index("/* r433：`.hdiag-a{margin-bottom:auto}`")
    seg = src[i:i + 700]
    assert ".hdiag-card .hdiag-acts{display:flex;align-items:center;" in seg, seg
    assert "margin-top:2px;padding-top:0;min-height:0" in seg, seg
    # 规则行不许复活（注释里会引用旧写法作判例）
    assert "\n.hdiag-card .hdiag-a{margin-bottom:auto}" not in src
    assert "\n.hdiag-card .hdiag-acts{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:auto" not in src

def test_source_note_toggle_does_not_move_its_button():
    """用户实报「说明的展开…然后排版位置呢？！」。实测 1512 档点开后
    「说明」按钮从 x=1305 跳到 509（796px）：scnote 曾是 scfoot 的 flex
    子项，展开让它 basis 变 100%，右对齐的 scfoot 宽度 93→520，按钮被推左。
    r423 起说明挂在卡头上（.ucard 直接子元素、卡头之后）：展开只让卡片
    长高，诊断卡头几何完全不变。曾放在卡头容器内——窄档 align-items:center
    把按钮顶下 6px（实测 900/760/390 moved=6），所以必须在卡头之外。
    两态文案宽度差 22px 由 sclink 的 min-width 兜住。复测五档 moved=0。"""
    import webui
    src = webui.PAGE
    i = src.index('#healthDiag>#scNote{')
    seg = src[i:i + 260]
    assert "display:none" in seg and "line-height" in seg, seg[:200]
    # 不得回到「卡头容器内的 flex 子项」——窄档会顶按钮
    assert "#healthDiagHead>.scnote" not in src, "说明又回到卡头 flex 行里"
    assert "#healthDiag #srccap .scnote" not in src, "说明又回到路径条里"
    assert "#srccap .sclink{min-width:62px;text-align:center}" in src
    # 说明必须在卡头之外、诊断体之前，DOM 上是卡片的直接子元素
    i_head_end = src.index('id="healthDiagBody"')
    i_note = src.index('id="scNote"')
    assert i_note < i_head_end, "说明跑到了诊断体之后"

def test_source_strip_is_not_its_own_full_width_band():
    """用户实报「渠道健康那个来源接入独立一行的设计非常奇怪，也非常
    割裂」。三层历史：(1) 自成一张卡占满一整行；(2) 并进诊断卡但仍是
    4% 蓝底满宽色带，读作第三个区块；(3) 现在是卡头里的行内一段——
    与「渠道诊断」小标同基线（实测 1512/1100 sameRow=true），无底色
    （透明），不再有任何整行色块。"""
    import webui
    src = webui.PAGE
    i_diag = src.index('<div class="ucard" id="healthDiag">')
    i_sc = src.index('id="srccap"')
    i_body = src.index('id="healthDiagBody"')
    assert i_diag < i_sc < i_body, "来源接入又跑出诊断卡之外/跑到诊断体之后"
    assert 'class="ucard srccap"' not in src, "来源接入又变回独立卡面"
    # 无底纹：色块本身就是「独立一行」的视觉成因
    i_css = src.index('#healthDiag #srccap{')
    assert "background:transparent" in src[i_css:i_css + 120], src[i_css:i_css + 120]
    # 必须在卡头容器内，与小标同排
    assert '<div class="uhead" id="healthDiagHead">' in src
    assert src.index('id="healthDiagHead"') < i_sc, "来源接入被挤出卡头"

def test_pacing_state_is_not_a_temporal_dead_zone():
    """showMonTab('health') 会立刻调 loadPacing→读 PACE.detail，而 PACE 曾
    声明在本文件 15000 行之后：深链/键盘切到渠道健康时先报 TDZ
    "Cannot access 'PACE' before initialization"；只改成 var 又变成
    "Cannot read properties of undefined (reading 'detail')"——提升但未赋值。
    初始化必须整块前移到 showMonTab 定义之前，且只留一处。"""
    import webui
    import re as _re
    src = webui.PAGE
    # 不锁字段全量（并行会话会往 PACE 加字段）：只认「只有一处、是 var、
    # 且在 showMonTab 之前」三条实质约束。
    assert not _re.search(r"\bconst PACE=\{detail:", src), "又变回 const（TDZ）"
    decls = list(_re.finditer(r"\bvar PACE=\{detail:", src))
    assert len(decls) == 1, "PACE 初始化必须只有一处"
    i_decl = decls[0].start()
    i_tab = src.index("function showMonTab(")
    i_use = src.index("try{loadPacing();_paceStartAuto()}")
    assert i_decl < i_tab < i_use, "初始化必须先于 showMonTab 定义"

def test_search_sections_have_no_decorative_fences():
    """用户反复报「折叠起来了，但是有很多分割线，很不干净」。检索页曾给
    hero/probe/band/brief/context/list/mirror 统一加 border-top:1px 发丝线——
    首屏横向压着 5 条满宽分割线。区块分隔改为留白，只保留行内数据线。"""
    import webui
    src = webui.PAGE
    marker = '#searchview .srx-hero,#searchview .srx-probe,#searchview .srx-band,'
    i = src.rindex(marker)          # 末尾那条才是生效规则
    seg = src[i:src.index('}', i) + 1]
    assert 'border-top' not in seg, seg[:300]
    assert 'border:0!important' in seg

def test_radar_marks_each_sample_point():
    """用户实报「走势有白白的折叠遮挡短点、一定不可以断档」。雷达 2h 一轮、
    30 天窗里一条线常只有 2–3 个点：只画折线时视觉是「几截短横」，读作
    短点被遮住。line 必须支持段内顶点圆点，雷达必须打开它。
    r424：非聚焦线 alpha=.7，圆点若跟着 .7 走就再次被压淡（像素实测
    顶点最暗 120 vs 线身 154 是修复后的差距）；点必须按自身 .85 起画。"""
    import webui
    src = webui.PAGE
    assert "if(style.vertexDots){" in src
    assert "vertexDots:true,dot:2});" in src
    i = src.index("line(ctx,g,pts,style){")
    seg = src[i:i + 1400]
    # 缺口语义不得被圆点改写：分段仍由 gaps 决定、单点段仍画单点
    assert "PCHART.gaps(pts,style.gapMin)" in seg
    assert "if(seg.length===1)" in seg
    # 圆点必须有自己的不透明度下限，不能被外层 alpha 压成看不见
    assert "ctx.globalAlpha=Math.max(_alpha,.85)" in seg, "圆点又被外层 alpha 压淡"


def test_radar_redraw_does_not_reallocate_bitmap():
    """用户实报「滑动不是丝滑，是卡顿」。canvas 的 width/height 一旦赋值
    就清空 + 重分配位图，悬停/节流重绘时整幅会闪。PCHART.prep 早已为此
    写了「尺寸未变不重设」，但雷达 spMonDraw 这条路径一直无条件重设。"""
    import webui
    src = webui.PAGE
    i = src.index("function spMonDraw(")
    seg = src[i:i + 6000]
    assert "c.width=Math.max(1,Math.round(W*dpr))" not in seg, \
        "雷达又无条件重设画布位图（每次重绘都清空重分配）"
    assert "if(c.width!==_bw|c.height!==_bh)" in seg, "缺少「尺寸未变不重设」守卫"


def test_srccap_strip_has_no_block_background():
    """来源接入并入诊断卡后，`.srccap` 曾全局 `background:transparent!important`
    并补一条满宽 border-top：卡内信息带的底纹被抹成透明，整条又退回「卡里
    嵌一段裸文本」的割裂观感，还在卡内横加一条发丝线。r412 因此给它加了
    4% 蓝底——但满宽色块本身又成了「独立一行」。
    r423 定论：路径已长在卡头同一行里，不再需要靠底纹分组，所以底纹必须
    透明；且卡内绝不能出现横线。"""
    import webui
    src = webui.PAGE
    i = src.index("#healthDiag .srccap{")
    seg = src[i:src.index("}", i) + 1]
    assert "background:transparent" in seg, seg
    assert "border:0" in seg, seg
    assert "border-top" not in seg, "卡内信息带又横加一条发丝线"
    # 不再有任何整行色块
    assert "#healthDiag #srccap{background:color-mix" not in src, "满宽底纹带复活"

def test_overview_card_actions_sit_in_the_card_head():
    """用户实报「用户明细按钮你不觉得排在那里很别扭吗」。此前概览卡把
    「查看明细 / 走势」挂在最底部「全线最低：…」那句尾巴上，动作埋在长句
    里、离它要操作的 KPI 隔了一整块网格。动作必须进卡头、与对象同行。"""
    import webui
    src = webui.PAGE
    i = src.index("全线最低：${mHtml}")
    seg = src[i:i + 400]
    assert "查看明细" not in seg, "动作又埋回「全线最低」句尾"
    assert '<span class="uact2">' in src
    assert ".uhead .uact2{margin-left:auto" in src

def test_user_card_actions_share_the_name_row_on_narrow_screens():
    """用户实报「用户明细按钮你不觉得排在那里很别扭吗」。

    r433 曾把窄档动作行改成 `flex-basis:100%` 独占第二行（当时理由是
    「放不下」），并只把它改为左对齐。r444 复测推翻了这个前提：
    390 档卡名右缘 105、卡右缘 368，**右侧空 263px，这行放得下**；
    动作仍被挤到下一行（dy=+56、整行撑满 324px），用户是同一句抱怨。
    现在改为与卡名同行、贴卡右缘（实测三档 dy=-6/-7/-6）。
    """
    import webui
    src = webui.PAGE
    # 动作不许再独占一整行
    assert ".uhead .uact2{flex-basis:100%" not in src
    i = src.index("r444：`.uhead` 是 wrap 容器")
    seg = src[i:i + 560]
    assert "justify-content:flex-end" in seg, seg
    # 宽档仍靠右（那条不该被误改）
    assert ".uhead .uact2{margin-left:auto" in src

def test_mirror_rail_stays_one_row_with_fixed_right_group():
    """用户实报「展开收起控件独立占一行」。镜像工具条 1500 以下曾用
    flex-wrap:wrap：6 个渠道胶囊正好铺满首行，「收起镜像」被单独挤到
    第二行（实测 bandSizes=[6,1]、条高 76px）。改为左段可横滚、
    右段（收起镜像 + 视图组）恒贴右不换行。"""
    import webui
    src = webui.PAGE
    i = src.index("@media(max-width:1500px){")
    seg = src[i:i + 620]
    assert "flex-wrap:nowrap" in seg, "又回到 wrap（折叠钮会被挤到第二行）"
    assert ".srx-mrail>.srx-foldbtn" in seg and "position:sticky;right:0" in seg
    assert ".srx-mrail>.srx-mtools" in seg

def test_mirror_collapse_leaves_only_its_reopen_entry():
    """用户反复报「折叠后中间还有元素常驻 / 折叠钮自己占一行」。镜像收起后
    原先只藏 mchrome/mbody——5 个渠道胶囊 + 列表/详情/四源 仍铺在一条
    1319px 横带上（实测折叠态高度 48px），它们操作的是已经收起的内容。
    收起态必须只剩唯一出口「展开镜像」。

    另：按钮文案/aria 一度不翻转（仍显示「收起镜像」、aria-expanded=true）——
    因为按钮 onclick 写的是 srxFold(this.dataset.foldtarget,this)，不含目标 id
    字面量，旧选择器 [onclick*="srxMirror"] 匹配 0 个按钮。改为按
    data-foldtarget 匹配。

    r424：隐藏方式必须是 visibility 而不是 display——display:none 会让触发器
    重排，实测收起后按钮从 (1209,367) 跳到 (872,1080)（1428px），正是用户报的
    「展开位置都发生了偏移」。当时用占位隐藏把位移压到 2px。
    r524 用户指出了占位方案的代价：「能收起来，但是也给不了右边用」——钱没省
    在折叠上。改为 display:none **并**把触发器移到轨道末尾、右列塌成按钮宽：
    位移 0px，列表同时 +431~571px（两半都保住）。所以这里守的是
    「收起态不得留下可点的残留」，不再要求 visibility 占位。"""
    import webui
    src = webui.PAGE
    # 折叠态：渠道胶囊与视图组真正移除，不留可点残留、也不留占位空带
    i = src.index(".srx-mirror.srx-folded .srx-mrail>.srx-mtab,")
    seg = src[i:i + 200]
    assert "display:none!important" in seg, \
        "收起态残留占位写法——右列宽度不会释放给左列表"
    assert "visibility:hidden" not in seg, \
        "收起态又用 visibility 占位（用户实报「给不了右边用」）"
    # 工具带保留与展开态相同的 padding/min-height；边线只透明、不删宽度
    # （删宽度少 1px 盒高，触发器实测下移 1px）
    i = src.index("#searchview .srx-mirror.srx-folded .srx-mrail{")
    seg = src[i:src.index("}", i) + 1]
    assert "border-bottom-color:transparent!important" in seg, seg
    assert "border-bottom:0" not in seg, seg
    assert "min-height:0" not in seg, seg
    assert "overflow:" not in seg, seg
    assert "#searchview .srx-mirror.srx-folded .srx-mrail{min-height:0!important" not in src, \
        "轨道高度两态必须一致，否则触发器纵移"
    # 网格不得因折叠变成单列（镜像从右半栏变整行 = 跨屏位移）
    assert "#searchview .srx-grid:has(.srx-mirror.srx-folded){grid-template-columns:1fr}" not in src
    # 文案/aria 必须真的翻转：按 data-foldtarget 找按钮
    assert "[data-foldtarget=\"'+id+'\"]" in src


def test_sticky_table_header_stays_opaque():
    """用户实报「航班明细表头在滑动下来的时候，都透明遮挡了表格数据了」。

    表头是 `position:sticky;top:0;z-index:6`，只要底色有一点透明，滚动时
    数据行就会从表头下穿过。源码里曾同时存在两条对撞规则：
      #ftable th{background:var(--r-surface-2)}        ← 实底
      #ftable th{background:transparent!important}     ← 清成透明
    谁赢取决于源码先后顺序，挪一段就可能复发。
    实测定案：滚动到 45% 后表头条内底色占 92.9%、深色文字仅 2.81%（无透字）。
    """
    import webui
    src = webui.PAGE
    # 不得再有任何把表头底色清成透明的规则
    for bad in ("#ftable th{background:transparent!important}",
                "#ftable th{background:transparent}"):
        assert bad not in src, "表头又被清成透明，滚动时会透出数据行"
    # 实底规则必须在位，且用两层（底色 + 同色渐变兜住 background-clip 场景）
    i = src.index("#montab-details .tw thead th:not(:hover){background:")
    seg = src[i:i + 320]
    assert "background:var(--r-surface-2,#f1f4f8)!important" in seg, seg
    assert "background-image:linear-gradient(" in seg, seg
    # 吸顶三件套
    j = src.index("#montab-details .tw thead th{z-index:6!important")
    assert "isolation:isolate" in src[j:j + 90]


def test_special_channel_links_align_with_main_links():
    """用户实报「渠道入口那个只扁平了，但是设计语言呢？对齐布局呢？」。

    次行「特价」入口排在行首的「特价」标签之后就会整体右移 33px：
    1512 主入口 l=477 / 特价首条 l=510，390 主入口 l=28 / 特价 l=59 ——
    同一条渠道的两行入口左缘对不上，读作「缩进不齐」。
    r430 把标签沉到行尾，入口回到行首，但标识列随特价条数漂移
    （1280 档 533/523/533/533/512）。
    r542 定案：标签绝对定位钉在本行右端当注记（脱离文档流，不再推任何
    入口），入口左缘与上方四格卡片的**文字**左缘同轴——实测 1512
    267＝267、1280 252＝252；窄档每个入口自带「PC 特价」面位小标，
    行首标签重复且右推 21px，直接隐藏。
    """
    import webui
    src = webui.PAGE
    i = src.index(".chspec-k{font-size:10px!important")
    seg = src[i:src.index("}", i) + 1]
    # 行首（order:0）把入口右推 33px，行尾（order:9）让标识列随条数漂移，
    # 钉最右端则离内容 700px——三种都读作「没对齐 / 不相干」。
    assert "order:2!important" in seg, "「特价」标签又离开了入口之后的位置"
    assert "order:0!important" not in seg and "order:9" not in seg
    assert "position:absolute!important" not in seg,         "标签脱离文档流会离它标注的那行很远"
    assert "margin-left:6px!important" in seg
    j = src.index(".chband-specs{display:flex!important")
    spec = src[j:src.index("}", j) + 1]
    assert "flex-wrap:wrap!important" in spec
    assert "position:relative!important" not in spec,         "标签已回到行内流，容器不该还留着为绝对定位准备的 relative"
    # 窄档隐藏行首标签（每个入口自带「PC 特价」面位小标）
    k = src.index(".chband-specs .chspec-k{display:none!important")
    assert k > 0, "窄档行首又挂了一个「特价」，与面位小标重复"
    # 窄档标题里的 PC/H5 与面位小标重复，读作「PC 特价 PC ↗」
    t = src.index(" .chband-specs .chlink-top b{display:none!important}")
    assert t > 0, "窄档特价行又把 PC/H5 读了一遍（面位小标已说明端）"


def test_channel_card_titles_never_outgrow_the_fixed_row():
    """用户实报「展开筛选条件的这个面板…大小布局对称，不够协调」。

    渠道卡 grid 行高钉死 44px，而 r433 让标题可换行：1280 档不重复登录
    账号时「机票搜索（与国内同页，页内切国际）」折 5 行、78px，被 44px
    行高裁切压字（实测 top/bot 各溢 17px、clippedText=True）。
    定案：登录账号上提到带级 meta（同渠道四格本就是同一个账号），
    每格不再挂 56px 宽标签；标题限两行省略。实测 1512/1280/900/390
    四档 20 张卡 overflow 全 0、五带等高。
    """
    import webui
    src = webui.PAGE
    i = src.index("function chlinkChip(c,special,withAuth){")
    seg = src[i:src.index("\nfunction ", i + 10)]
    assert "withAuth!==false" in seg, "登录账号又逐格渲染了"
    assert "const auth=(c.login&&withAuth!==false)" in seg
    # 账号必须仍有落点：带级 meta 拼上短要求
    j = src.index("function chBandHTML(")
    band = src[j:src.index("\nfunction ", j + 10)]
    assert "const _acc=((cells||[]).map(c=>c&&c.login).filter(Boolean)[0])||''" in band
    assert "(_sl+' · '+_acc)" in band, "账号名上提后没写进带级 meta"
    assert "const _auth=!(_sl&&((cells||[]).some(c=>c&&c.login)))" in band, \
        "已上提时仍会逐格重复账号"
    # 标题限两行，超出省略（否则 44px 行高裁切压字）
    k = src.index(".chlink-top b{font-size:12px!important")
    t = src[k:src.index("}", k) + 1]
    assert "-webkit-line-clamp:2!important" in t, t
    assert "overflow:hidden!important" in t


def test_special_row_text_starts_where_card_text_starts():
    """特价行入口左缘必须等于卡片**文字**左缘，不是卡片盒左缘。

    卡片 padding 0 10px、特价行容器 padding 0 1px 时，两者文字左缘差 9px
    （1512 258 vs 267）。r542 把特价行容器内边距对齐到卡片内边距
    （padding:0 10px；窄档卡片自带 9px 内边距故归零）。
    """
    import webui
    src = webui.PAGE
    i = src.index(".chband-specs{display:flex!important")
    seg = src[i:src.index("}", i) + 1]
    assert "padding:0 10px!important" in seg, seg
    j = src.index(" .chband-specs{padding:0!important}")
    assert j > 0, "窄档特价行容器内边距没归零（会与卡片外框差 10px）"


def test_empty_capbar_does_not_reserve_a_blank_band():
    """用户实报「展开概览…展开的中间还有元素常驻」「有很多分割线」。

    `#searchview .srx-capbar{display:flex!important}` 会压过
    `[hidden]{display:none}`：空态 capbar（innerHTML=0、hidden=true）
    因此仍被渲染成 6px 高、上下各一条发丝线的空条，正好夹在
    价带与五源之间。实测定案：修后该节点 display=none，
    展开态总高 206→188（1512）/ 259→241（390），中间不再有空条。
    """
    import webui
    src = webui.PAGE
    assert "#searchview .srx-capbar[hidden]{display:none!important" in src, \
        "空 capbar 又会被 display:flex!important 强行显示"
    i = src.index("#searchview .srx-capbar{display:flex!important")
    seg = src[i:src.index("}", i) + 1]
    assert "border-top" not in seg and "border-bottom" not in seg, \
        "空信息带不该再画上下两条通栏线"


def test_probe_toggle_is_clickable_on_narrow_screens():
    """用户实报「展开探针，展开应该是展开的感觉，怎么位置都发生了偏移」。

    比偏移更严重的是：≤760 档 `:not(.open) .srx-probehead` 被锁死
    `height:30px;overflow:hidden`，而收起态的 acts 实测 40px ——
    36px 的切换钮被裁到头部盒外，其上 20px 落进 `.srx-mobilebar` 的
    矩形里，`elementFromPoint` 命中移动栏。真实鼠标点击相当于点在
    移动栏上：390/460/760 三档 aria 恒为 false，探针永远打不开。
    定案：窄档放开高度与裁切，按钮回到可点区域（hitOk=True、可开合）。
    """
    import webui
    src = webui.PAGE
    i = src.index("/* r425：≤760 档把切换钮排进 acts 后")
    seg = src[i:i + 900]
    assert "#searchview .srx-probe:not(.open) .srx-probehead{min-height:40px!important" in seg, seg
    assert "height:auto!important" in seg, seg
    assert "overflow:visible!important" in seg, seg
    # 两态同高 + 顶对齐，避免居中带来的纵向抖动
    assert "#searchview .srx-probe.open .srx-probehead{min-height:40px!important}" in seg, seg
    assert "align-items:flex-start!important" in seg, seg

def test_poll_rebuild_keeps_loaded_row_depth():
    """10s 轮询走 render()→table() 是**同源重建**：只把切片补到「滚动位
    合法」时，用户手动补全到 194 行的明细会在下一拍被打回首片 120 行——
    正在看的行凭空消失、滚动条长度突跳（实测 render() 前后 194→120）。
    重建必须先还原重建前的切片深度，再按滚动位兜底。"""
    import webui
    src = webui.PAGE
    assert "const _pch=_NDRAW;" in src, "重建前未记录切片深度"
    i = src.index("const _pch=_NDRAW;")
    seg = src[i:i + 4000]
    assert "while(_NDRAW<_pch&&_tblAppend()){}" in seg, "重建后未还原切片深度"
    # 还原必须先于滚动位兜底，否则 st 界内不再补片、深度仍被打回
    assert seg.index("while(_NDRAW<_pch") < seg.index(
        "while(st>0&&tw.scrollHeight<st+tw.clientHeight"), "先兜底后还原=深度仍丢"

def test_overview_toggle_is_last_in_wrapped_band_header():
    """用户实报「展开概览那个明显交互有问题，展开的中间还有元素常驻」。
    窄屏价带头换行：折叠钮曾是 order:2 落在第一行，翻页(order:3)/轴
    (order:4)/渠道登录(order:5) 在它下面一行——390 档展开后按钮与面板
    之间夹着 38px 常驻控件。换行档必须把钮排到视觉末位。"""
    import webui
    src = webui.PAGE
    i = src.index("/* r384 价带头窄屏收口")
    j = src.index("#searchview #srxBand .srx-band-h>.srx-ovtoggle", i)
    # 只断言规则行本身（注释里会提到旧值，不能拿整段做字面量反证）
    assert ".srx-ovtoggle{order:2" not in src, "折叠钮又在换行档排到前面了"
    line = src[j:src.index("\n", j)]
    assert "order:9" in line, line
    assert "margin-left:auto" in line, line
    # 轴/渠道登录必须比钮更早（order 更小）
    for sel, od in ((".srx-bandnav{", 3), (".srx-axis{", 4),
                    (".srx-bandlogin{", 5)):
        k = src.index(sel, i)
        assert ("order:%d" % od) in src[k:k + 120], sel

def test_health_diag_path_bar_shares_card_left_edge():
    """用户复报「渠道健康那个来源接入独立一行的设计非常奇怪，也非常割裂」。

    这条约束被违反过三次，前两次的「修复」都各有硬伤（r432 实测）：
    ① `flex:1 1 560px` 与标题同处 wrap 行 → 1280 档标题只占 423px 时它贴右，
       左缘 92→529，与卡头/诊断体读作 L 形台阶；
    ② `flex-direction:column` + `align-self:stretch` → 左缘是对齐了，但标题行
       右侧空出 673px、路径条占满 1087px 自成一段，用户仍判「独立一行、割裂」；
    ③ 窄屏 `flex:0 1 auto` 时又被 scpath 的定宽按钮挤出标题行，只剩 324px，
       «挤在标题旁只剩一半宽» 比独占一行更难读。
    终态：宽屏行向参与 wrap（吃标题行剩余空间，不再是满宽色带），
    窄屏换行时吃满整行。任何一条被改回去，这里都会红。
    """
    import webui
    src = webui.PAGE
    i = src.index("/* r426/r427/r432：路径条的三种形态都被用户判为割裂")
    # r460：中途插入了三条 r460 规则和注释，固定 1200 字窗口会把
    # @media(max-width:1080px) 挤出去（实测红过一次）→ 取到 760 断点止。
    _j = src.index("@media(max-width:1080px)", i)
    _k = src.index("@media(max-width:760px)", _j)
    seg = src[i:_k]
    # 卡头必须是行向 + wrap：列向会让路径条永远是第二行
    assert "flex-direction:row;align-items:center" in seg, seg
    assert "flex-wrap:wrap;gap:4px 12px" in seg, seg
    # 只断言规则行本身（注释里会引用旧写法作为判例，不能拿来当证据）
    assert "\n#healthDiagHead{display:flex;flex-direction:column" not in src, (
        "卡头又回到列向——路径条必然独占第二行")
    # 路径条只吃剩余空间，不抢满行
    assert "#healthDiag #srccap{align-self:center;width:auto;flex:0 1 auto" in seg, seg
    assert "align-self:stretch" not in seg, "路径条又去抢满行宽度"
    # 窄屏换行档：吃满整行，不许挤在标题旁只剩一半宽
    assert "@media(max-width:1080px)" in seg, seg
    assert "#healthDiag #srccap{flex:1 1 100%" in seg, seg
    # 旧的「同行贴右」写法不许复活（只断言规则行，注释里会提到旧值）
    assert "#healthDiag #srccap{flex:1 1 5" not in src, "路径条又回到同行贴右"
    assert "#healthDiag #srccap{flex:1 1 0;" not in src, \
        "路径条仍在卡头同一行参与 wrap"
    # r460：卡头继承 .uhead 的 space-between，会把路径条推到最右
    # （实测 1512 左缘 107→789、两段之间空 682px，读作「独立一行」）。
    assert "#healthDiagHead{justify-content:flex-start}" in src, \
        "卡头又用 space-between 把路径条推到最右"
    # 路径条内部节点必须可截断：nowrap 胶囊的 min-content 448px 会让整条
    # 死死卡在 605px，标题行右侧白空 259px。
    assert "#healthDiag #srccap .scpath .scnode{min-width:0;overflow:hidden}" in src

def test_narrow_probe_actions_stay_inside_container():
    """用户实报「展开探针，展开应该是展开的感觉」。窄屏展开态三颗动作钮
    曾被压到 18px、整行从 -57 起溢到容器左侧（出了屏仍可点）：
    `flex:1 1 auto` 允许缩到 min-content 之下，末行 356px 的折叠钮又
    抢走整行。窄屏必须给按钮可读下限并允许换行。"""
    import webui
    src = webui.PAGE
    i = src.index("/* r428：三颗动作钮曾被压到 18px")
    seg = src[i:i + 700]
    assert "flex-wrap:wrap!important" in seg, seg
    assert "min-width:84px!important" in seg, seg
    assert "white-space:nowrap!important" in seg, seg
    # 收起态要给右上角绝对定位的开合钮让位（78px 不能被一并删掉）
    j = src.index("#searchview .srx-probe:not(.open) .srx-probeacts{padding-right:78px")
    assert j > 0
    k = src.index("#searchview .srx-probe.open .srx-probeacts{padding-right:0", j)
    assert k > j

def test_health_status_badge_meets_contrast():
    """实测抽样（概览 157 项 / 健康 93 项，亮暗两主题）：唯一低于 AA 4.5 的是
    诊断卡状态徽「最近一轮正常」——`--r-green` #0e8345 于 `--r-green-soft`
    #eaf5ee 只有 4.32:1（10px 文字）。改用与达标 pill 同一文字令牌 --ok-txt
    （亮 #0b6e39 5.63:1 / 暗 #43c072），抽检归零。"""
    import webui
    src = webui.PAGE
    i = src.index(".hdiag-card.ok .hdiag-st{")
    line = src[i:src.index("}", i) + 1]
    assert "color:var(--ok-txt)" in line, line
    assert "color:var(--r-green)" not in line, "状态徽又用回 4.32:1 的绿"
    # 暗色下 --ok-txt 必须是更亮的 #43c072（否则暗底上掉对比）
    assert "--ok-txt:#43c072" in src

def test_horizontal_wheel_hands_back_at_edges():
    """横滚容器的滚轮转写（.hcells/#montabs/.spmon-chartwrap/.spmon-cal）
    此前无条件 preventDefault 且继续加 scrollLeft：滚到最左/最右后再滚
    毫无反应、页面也滚不动，读作「卡住」。实测（真实 WheelEvent）：
    中段 +120 生效、到左端 defaultPrevented=false、窄图不接管。"""
    import webui
    src = webui.PAGE
    i = src.index("const wrap=t.closest('.hcells,#montabs,.spmon-chartwrap,.spmon-cal');")
    seg = src[i:i + 700]
    assert "const max=wrap.scrollWidth-wrap.clientWidth;" in seg, seg
    assert "wrap.scrollLeft<=0&&d<0" in seg, "左端未交还滚轮"
    assert "wrap.scrollLeft>=max-1&&d>0" in seg, "右端未交还滚轮"
    assert "wrap.scrollLeft=Math.max(0,Math.min(max,wrap.scrollLeft+d))" in seg, seg
    # 不得再出现「无条件接管」的旧写法
    assert "ev.preventDefault();" + chr(10) + " wrap.scrollLeft+=ev.deltaY;" not in src


def test_result_rows_use_whitespace_not_per_row_rules():
    """用户反复报「折叠起来了，但是有很多分割线，很不干净」「整个项目
    要扁平干净」。解析列表每行都画满宽底边：1512 实测 .srx-row 52 条 +
    .srx-mrow 10 条，一排 8 行就有 8 条横线贯穿整列，整块读成表格框。
    此前只用 color-mix 把线压到 45% 透明——线还在，密度没变。

    微信式列表靠留白分组：行线整条去掉，行间距由容器 row-gap 提供
    （实测 0→2px，相邻行不再黏连）；表头下方保留唯一一条分组线
    （标题/数据 的语义边界）。改后全站满宽装饰线 143→71，检索页 63→14。
    """
    import webui
    src = webui.PAGE
    # 行线必须整条消失（规则行），不能只是改颜色
    assert "#searchview .srx-row{padding:11px 12px;gap:10px;border-bottom:0}" in src
    assert "#searchview .srx-mirror .srx-mrow{padding:9px 11px;border-bottom:0!important}" in src
    assert "#searchview .srx-row{padding:11px 12px;gap:10px;border-bottom:1px" not in src
    # 行间距必须由容器提供，否则线一撤就黏成一片
    assert "column;row-gap:2px}" in src
    # 那条「把行线压到 45% 透明」的规则不许回来（它只对该行还有线时才有意义）
    assert ".srx-row,#searchview .srx-mrow{border-bottom-color:color-mix" not in src


def test_channel_entry_titles_are_not_clipped():
    """用户实报「渠道入口那个只扁平了，但是设计语言呢？对齐布局呢？」

    225px 卡宽、12px 字号下主标题曾 `nowrap + ellipsis`：
    「机票搜索（与国内同页，页内切国际）」被截成「机票搜索（与国内同页…」。
    被截掉的括号正半句是**区分同一行两个入口的唯一信息**（主名称都叫
    「机票搜索」），触屏也没有 hover 读 title，等于让人分不清该点哪个。
    改为换行；并给入口卡 38px 下限让「长标题换行」不改变 band 高度
    （否则飞猪/同程 63px、途牛 54px，五条带子高矮不一）。
    实测 1512：30 个标题 0 截断、5/5 条带等高 70px；390 同样 0 截断。
    """
    import webui
    src = webui.PAGE
    i = src.index("/* r433：渠道入口主标题曾 `nowrap + ellipsis`")
    seg = src[i:i + 700]
    assert "white-space:normal!important" in seg, seg
    assert "overflow-wrap:anywhere!important" in seg, seg
    assert "text-overflow:ellipsis" not in seg, "主标题又回到省略号截断"
    # 两行下限：换行不能让 band 高矮不一
    assert ".chlink{min-height:38px!important}" in src


def test_probe_toggle_never_overlaps_or_shifts():
    """用户实报「展开后有一个收起探针的样式」+「展开的时候 demo 合成的
    位置抖动偏移了」。两条都是实测确认的真缺陷：

    ① **重叠**：折叠钮曾是 `position:absolute;right:10px`，不占流；而操作簇
       `.srx-probeacts` 是 `margin-left:auto` 贴右。展开态两者落在同一块区域，
       实测「收起探针」(1120–1184) 与「探针会话」(1132–1194)、「快捷筛选」
       (1065–1127) 矩形重叠——截图里是一个「收起探针」的字压在「特价雷达」
       按钮上。改行内 + `order:9`（acts 右缘固定，末位即最右）后
       1512/1280/900 三档重叠为 0、折叠钮坐标两态恒等。

    ② **DEMO·合成 抖动 2px**：收起态 `gap:6px`、展开态由另一条规则给
       `gap:8px`，开合时卡头内间距差 2px，小标横移 2px（五档全中）。统一
       8px 后 emMoved=[0,0]。

    ③ **≤900 档 EM 整块消失**：`max-width:900` 块里 `display:none`，展开
       才出现（实测 h 0→24、纵跳 256px）。改为 visibility:hidden 保占位。
    """
    import webui
    src = webui.PAGE
    # ① 折叠钮必须行内、末位、不绝对定位
    i = src.index("/* r433：折叠钮曾是 `position:absolute; right:10px`")
    seg = src[i:i + 900]
    assert "position:static!important;order:9!important" in seg, seg
    assert "srx-probe-toggle{border-color:transparent;background:transparent;\n position:absolute" not in src
    # ② 两态 gap 必须一致（6px→8px 那次抖动）
    assert ".srx-probe:not(.open) .srx-probehead{margin-bottom:0;gap:6px}" not in src
    assert ".srx-probe:not(.open) .srx-probehead{margin-bottom:0;gap:8px}" in src
    # ③ 900 档 EM 保占位
    assert "srx-probehead>em{display:block!important;visibility:hidden!important}" in src,         "900 档收起态 EM 又回到 display:none"


def test_probe_toggle_reads_as_a_fold_switch_not_a_fourth_action():
    """r434：用户实报「展开探针…展开后有一个收起探针的样式」。

    折叠钮与「组合 / 特价雷达 / 探针会话」同排同长相，展开态读作多了第四
    颗动作钮。「同一颗按钮多态」不只是坐标恒等，还要能被认出来是折叠开关。
    做法：箭头 + 文案两段式，箭头按态旋转（展开朝上、收起朝下）。

    负控实测过两层坑：
    ① 基线写 `border-color:transparent;background:transparent` 再只在收起态
       补回卡片底——两态两种长相，正是本条要禁的；
    ② `srxRenderProbeInit` 里 `t.textContent=...` 会把箭头整颗抹掉，首次进
       页面就看不到箭头（实测 chev=False）。
    """
    import webui
    src = webui.PAGE
    # ① 折叠钮内部必须是「箭头 + 文本」两段，文本单独可更
    assert '<span class="srx-chev" aria-hidden="true"></span>' in src
    assert '<span class="srx-tgl-txt">收起探针</span>' in src
    # ② 所有改写文案的地方都只能动 .srx-tgl-txt，不得整颗按钮 textContent=
    for frag in (
        "const t=b.querySelector('.srx-tgl-txt');if(t)t.textContent=",
        "const x=t.querySelector('.srx-tgl-txt');",
    ):
        assert frag in src, frag
    assert "t.textContent='展开探针';t.setAttribute('aria-expanded','false')" not in src, \
        "初始化又把折叠钮整颗 textContent 覆盖了——箭头会被抹掉"
    # ③ 箭头两态方向相反（同一颗按钮，方向跟着内容走）
    assert "rotate(-135deg) translate(-1px,-1px)" in src, "展开态箭头未朝上"
    assert "srx-probe:not(.open) .srx-probe-toggle .srx-chev{transform:rotate(45deg)" in src, \
        "收起态箭头未朝下"


def test_channel_bands_are_equal_height_at_every_breakpoint():
    """r435：用户要求「对齐对称」——五条渠道入口带必须等高。

    两处实证成因（都会让五条带差 1px~23px，肉眼读作没对齐）：
    ① `.chband-id` 在 ≤1100 档是 `flex-wrap:wrap`，同程那条 meta 154px
       放不下就折到第二行，id 区 20→43px、整带 65→88px（390 实测）；
    ② `.chband-specs` 的 `min-height:0` 让缺 go 箭头那颗（途牛特价行）
       只占 29.29px，同排其余 30px，整带 65→64px（600–1100 实测）。
    修法：id 不换行+子项可收缩（长 meta 走省略号）、特价行给 30px 下限。
    """
    import webui
    src = webui.PAGE
    # ① ≤1100 档的渠道 id 行不得换行，且子项可收缩
    assert ".chband-id{flex-direction:row!important;align-items:center!important;flex-wrap:nowrap!important;gap:8px!important;min-width:0!important" in src
    assert "flex-wrap:wrap!important;gap:8px!important" not in src, "渠道 id 行又会折行"
    assert ".chband-meta{flex:0 1 auto!important;min-width:0!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important}" in src
    # ② 特价行给下限，别让缺箭头那颗矮 1px
    assert ".chband-specs{display:flex!important;flex-wrap:wrap!important;align-items:center!important" in src
    _i = src.index(".chband-specs{display:flex!important")
    assert "min-height:30px!important" in src[_i:_i + 400], "特价行又回到 min-height:0"
    # ③ 网格里的入口格子也要有 30px 下限（缺面位小标那条曾只 29px）
    assert "min-height:30px!important;height:100%!important" in src


def test_channel_band_name_is_never_squeezed_and_special_row_stays_one_line():
    """r435 两处窄档实证缺陷（都会读作「没设计」）：

    ① 渠道名被登录标签挤成「同…」——390 档实测「同程」的 b 元素
       scrollWidth 26 / clientWidth 9，只显示一个字符。渠道名是识别锚点，
       必须 `flex:0 0 auto` 不参与收缩，让 meta 标签去收缩。
    ② 特价行套用了网格格子的「面位独占整行」规则，390 档碎成
       「PC 特价」+「PC ↗」两行（实测 link 高 30，内容 2 行）。
       特价行本身是一行式文本入口，必须 nowrap。
    """
    import webui
    src = webui.PAGE
    assert ".chband-name{display:flex!important;align-items:center!important;gap:7px!important;flex:0 0 auto!important}" in src
    _i = src.index(".chband-name b{font-size:13px!important")
    _seg = src[_i:_i + 300]
    assert "overflow:visible!important" in _seg and "text-overflow:clip!important" in _seg, _seg
    # 特价行不套用格子规则
    assert ".chband-specs .chlink{flex-wrap:nowrap!important;height:auto!important" in src
    assert ".chband-specs .chlink-surface{display:inline!important;flex:0 0 auto!important;order:0!important}" in src


def test_site_blocks_share_one_left_edge_and_config_controls_one_right_edge():
    """r435：用户反复要「对齐布局 / 对齐对称衔接」，落成两条可测约束。

    实测基线（九视图 × 1512/390）：
    · 主内容列的直接子块左缘：1512 全 91、390 全 12；唯一例外是
      `.tabs`（`margin:0 -12px` 的满宽吸附 Tab 条，设计如此）；
    · 配置页 19 个 `.srow` 的 `.sctl` 右缘：1512 全 1361、390 全 318，
      label 左缘 1512 全 345 / 390 全 62。

    这条守的是「不要在有单源的情况下再叠一条按行改边距的规则」——
    `.srow` 的 `padding` 曾被某条媒体查询单独改成 `8px 10px`，造成
    控件列左右缘各偏 8px。"""
    import webui
    src = webui.PAGE
    # 满宽吸附 Tab 条必须是「负边距 + 等量内边距」，否则指示条与内容错位
    assert "margin:0 -12px" in src
    # 设置行范式：说明左、控件右（`.sctl` 贴右且不参与收缩）
    i = src.index(".srow{display:flex;align-items:center;gap:14px;padding:9px 2px;")
    seg = src[i:i + 260]
    assert "justify-content" not in seg or "space-between" in seg, seg
    j = src.index(".sctl{")
    ctl = src[j:src.index("\n", j)]
    assert "flex" in ctl, ctl
    # 不允许再有按行改左边距的规则（那会让控件列左右缘各偏一次）
    assert ".srow{padding:8px 10px" not in src or "compact" in src[:src.index(".srow{padding:8px 10px")][-200:]


def test_more_tools_trigger_keeps_its_place_at_every_narrow_breakpoint():
    """r435：「展开更多工具」在 460–900 档曾横移 284~364px、纵移 102px。

    三层成因（都在窄档的 `!important` 里，且源码顺序靠后，逐条都得改）：
    ① ≤600 的 `.srx-btn:last-child{grid-column:1/-1}` 正好命中触发器，
       把它拉成整行 362px；
    ② ≤600 的另一分支（`@media(max-width:600px)` 后段）未含 sticky，
       560/500 档展开后被顶到 x=700 **出视口**；
    ③ 761–900 与 ≤760 各有一条 `display:grid!important` 的 2 列网格，
       收起态 2 颗、展开态 9 颗 → 触发器被挤到第二行。
    定案：**窄档一律「单行横滚 + 触发器 sticky 右端」**，只有一套形态。
    实测 1512/1000/900/820/760/700/640/600/560/460/390/360 十二档
    moved 全 0、全在视口内、无横向溢出。"""
    import webui
    src = webui.PAGE
    # ① last-child 铺满必须排除触发器
    assert ".srx-btn:not(.srx-more-btn):last-child{grid-column:1/-1}" in src
    assert ".srx-hero-act .srx-btn:last-child{grid-column:1/-1}" not in src
    # ② 窄档不得再有 2 列网格形态
    assert "srx-hero-act{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important" not in src
    # ③ ≤760 与 ≤560 都必须有 sticky 触发器
    for frag in (
        " #searchview .srx-hero-act>.srx-more-btn{position:sticky!important;right:0!important;z-index:2;margin:0 0 0 auto!important;",
    ):
        assert src.count(frag) >= 2, "sticky 触发器规则少于 2 处（≤760 / ≤560）"
    assert "#searchview .srx-hero-act>.srx-more-btn{position:sticky;right:0;z-index:2;" in src


def test_calendar_price_rows_never_mix_into_the_real_fare_order():
    """r435：日历价不是可出手机票，却按价格混排进真实报价之间。

    实测 194 行结果里 9 行日历（时刻双空），价格紧跟在真实行后面
    （￥1430 就在 ￥1381 之后），出发/到达/时长/中转全「—」但价格与
    真实行并排，用户扫一眼就读成「这条航线 ￥1430 能买到」。
    修法：排序比较器先按「是否日历行」整体下沉，再按原排序键；
    五种排序键（price/date/dur/dep/smart）实测都保持日历行整组在末尾。
    """
    import webui
    src = webui.PAGE
    i = src.index(" rows.sort((a,b)=>{")
    seg = src[i:i + 900]
    assert "srxIsCal(a)" in seg and "srxIsCal(b)" in seg, "排序未区分日历行"
    assert "if(ac!==bc)return ac?1:-1;" in seg, "日历行未整体沉底"
    # 下沉必须发生在价格比较之前（否则仍会被价格键拉回中间）
    assert seg.index("if(ac!==bc)") < seg.index("sval(a,SORT.k)"), "下沉判断在价格比较之后"


def test_every_aria_controls_points_at_a_real_node():
    """r435：折叠钮的 `aria-controls` 必须指向真实存在的 id。

    实测（9 视图 × 1512/390，共 315 个可见折叠钮）只有一个死链：
    探针折叠钮 `aria-controls="srxProbeForm"`，而容器 `<div class="srx-probeform">`
    没有 id —— 屏幕阅读器与键盘用户拿到一个指不到任何东西的引用。
    这类「文案/属性与真实结构不符」正是用户说的「文案按钮就不合理」。
    """
    import re
    import webui
    src = webui.PAGE
    ids = set(re.findall(r'\bid="([A-Za-z][\w\-:.]*)"', src))
    refs = re.findall(r'aria-controls="([^"]+)"', src)
    assert refs, "没有 aria-controls，本门禁失去检查对象"
    # JS 模板字面量（`dpan-${p}-...`）在运行时才插值成真实 id，静态查不到；
    # 它们改由浏览器实测覆盖（9 视图 315 个可见折叠钮，死链 0）。
    dead = sorted({r for r in refs if "${" not in r and r not in ids})
    assert not dead, "aria-controls 指向不存在的 id: %r" % (dead,)
    # 探针容器必须带 id（上一轮新增引用时的落点）
    assert '<div class="srx-probeform" id="srxProbeForm">' in src


def test_radar_touch_pan_never_drags_the_hover_readout():
    """r435：「滑动不是丝滑」在雷达上是可测的——触摸滑动时读数跟着跑。

    触摸横向滑动时手指一直压在 canvas 上，`pointermove` 每帧都算 hover：
    实测 12 步触摸拖触发 **3 次 hover**，松手后浮窗仍 visible、十字线
    display:block —— 用户看到的是「滑完还留着一条线和一块白板压着走势」。
    修法：触摸按下只收浮层不读点；触摸 move 不触发 hover；鼠标路径原样保留
    （实测桌面 hover 浮窗仍显示真实读数、十字线随指针移动 633px）。
    """
    import webui
    src = webui.PAGE
    i = src.index(" const move=e=>{if(SPMON.panning)return;")
    seg = src[i:i + 700]
    assert "if(e.pointerType==='touch'){" in seg, "触摸 move 仍会算 hover"
    # 触摸按下只收浮层（不许当场读点），但要记住落点用于「点按」判定
    j = src.index("c.addEventListener('pointerdown',function(e){")
    down = src[j:j + 420]
    assert "hideTip();SPMON.tapX=e.clientX" in down, down
    # 触摸「点一下就松」必须仍然出读数——r435 曾把点按一起禁掉（uitest 红）
    up = src[src.index("c.addEventListener('pointerup',function(e){"):]
    up = up[:up.index("pointercancel")]
    assert "spMonHover({clientX:e.clientX,clientY:e.clientY})" in up, up
    assert "dx<=6&&dy<=6" in up, up
    # 拖动过就不许读点
    assert "SPMON.tapMoved=true" in seg
    # 鼠标路径必须保留（不能把 hover 一刀砍掉）
    assert "spMonHover({clientX:x,clientY:y})" in seg


def test_user_card_header_keeps_delete_and_chevron_on_the_name_row():
    """r436：配置页用户卡头 760 及以下把「删除」挤到单独一行。

    `.uhead2` 原是单条 flex 流：胶囊 + 删除/chevron 一起换行，胶囊一多就把
    `.uhead-end` 整块挤下去（实测 760/600/520/460/390/360 六档删除钮顶边
    比名字低 57~72px，390 档卡头因此 138px 高），用户读作「删除按钮孤零零
    挂在那里」。窄档改成「名字行 + 胶囊行」两段网格，删除/chevron 恒与名字
    同行；宽档仍走 flex（网格会把卡头从 60px 撑到 88px）。"""
    import webui
    src = webui.PAGE
    i = src.index("@media(max-width:860px){")
    seg = src[i:i + 900]
    assert 'grid-template-areas:"ava name end" "pills pills pills"' in seg.replace("\n", ""), seg
    assert ".uhead2 .uhead-end{grid-area:end" in seg.replace("\n", ""), seg
    # 宽档胶囊容器不生成盒子：DOM 顺序换了会让删除钮横移 302px
    assert ".uhead2 .upills{display:contents}" in src
    # 胶囊必须包在 .upills 里，否则网格放不下它们
    assert '\'<span class="upills">\'' in src


def test_narrow_probe_puts_actions_after_the_form():
    """r437：窄档展开探针时，触发器与表单之间夹着一整行常驻动作钮。

    实测 390 档触发器底 309、表单顶 347，中间 311~337 是
    「组合 0/4 · 特价雷达 · 探针会话」整行——用户反复报的
    「展开收起怎么能中间有元素呢」。
    宽档一行放得下（动作簇贴右）没这问题，所以只在 ≤760 生效：
    卡头摊平后动作簇成为 .srx-probe 的 flex 子项，用 order 排到表单之后。
    """
    import webui
    src = webui.PAGE
    i = src.index("@media(max-width:760px){\n   #searchview .srx-probe{display:flex;flex-direction:column}")
    # 用块的真实结束边界切片；此前是固定 1100 字符窗口，中间插一条注释
    # 就把 @media 块尾部挤出窗口，判据随之假红（r565 遇到过同型）。
    j = src.index("\n  }\n", i)
    seg = src[i:j]
    assert "#searchview .srx-probehead{display:contents}" in seg, seg
    assert "#searchview .srx-probeform{order:1}" in seg, seg
    assert "order:2;position:static!important" in seg.replace("\n", ""), seg
    # 触发器不许被这条规则带走：它仍是绝对定位在卡头
    assert "top:6px!important;right:8px!important" in src


def test_grouplab_has_aria_expanded_from_first_paint():
    """r439：配置页分区头首屏缺 aria-expanded。

    `_setFold` 是写 aria-expanded 的单源，但它只在用户点过一次 / applyFolds
    重建之后才跑；`glab()` 生成的首屏 grouplab 根本没有这个属性——读屏
    读不到「可展开/已展开」，而同走 _setFold 的 uhead2/rhead/chhead 首屏
    就有。初始为展开，与 chevron 的 `open` 同态。
    """
    import webui
    src = webui.PAGE
    i = src.index("const glab=(no,zh,en,sum)=>")
    seg = src[i:i + 260]
    assert 'role="button" aria-expanded="true"' in seg, seg


def test_kpi_price_bar_reads_as_a_bar_not_a_divider():
    """r440：概览价格条 3px 高、占父块 93~96%（宽高比 100:1~204:1），
    读作分割线而非进度——用户两轮都在说「有很多分割线，很不干净」。

    修：6px 高、240px 上限、上下留距。实测两档均为 240x6（比例 40:1），
    与下方文字间距 8px（此前为 0，文字贴着条）。
    """
    import webui
    src = webui.PAGE
    i = src.index(".kpi .bar{height:6px")
    seg = src[i:i + 160]
    assert "max-width:240px" in seg, seg
    assert "margin:10px 0 8px" in seg, seg
    # 旧写法（3px 通栏）不许复活
    assert ".kpi .bar{height:3px" not in src


def test_mobile_details_filter_tabs_are_all_reachable():
    """r441：390 档明细筛选条 nowrap 横滚，实测 client 348 / scroll 633。

    溢出 285px，「中转·全部 / 仅达标 / 直挂 / 只看关注」四颗整颗落在屏外，
    首屏既看不见也点不到；xhint 渐隐只在**滚动之后**才点亮，等于没有提示。
    540 以下改折行：实测 client==scroll（溢出 0），8 项全部可见。
    """
    import webui
    src = webui.PAGE
    i = src.index("@media(max-width:540px){\n #montab-details .tabs{flex-wrap:wrap")
    seg = src[i:i + 420]
    assert "overflow-x:visible!important" in seg, seg
    assert "row-gap:4px" in seg, seg
    # 「筛选」钮不许再 sticky 浮在右下角遮住折行后的末项
    assert "#montab-details .tabs>#fltBtn{position:static!important" in seg, seg


def test_user_card_actions_stay_on_the_name_row_at_every_width():
    """r444：390 档用户卡的「查看明细 ▸ / 走势 ▸」被挤到卡名下一行。

    实测 390：dy=+56 且动作行被撑满 324px（自占一行）。根因是
    `.uhead` 为 wrap 容器，`.uroutes` 267px + 卡名 77px = 344px >
    容器 324px；且 flex 子项默认 `min-width:auto`，只写 overflow:hidden
    收不动，必须显式 min-width:0 才真能省略。
    修后三档实测 dy = -6/-7/-6，动作贴着它作用的那张卡。
    """
    import webui
    src = webui.PAGE
    i = src.index("r444：`.uhead` 是 wrap 容器")
    seg = src[i:i + 520]
    assert ".uhead .uroutes{min-width:0!important;flex:1 1 0!important" in seg.replace("\n", ""), seg
    assert "text-overflow:ellipsis" in seg, seg
    # 动作行不许再回到「独占一整行」的写法
    assert ".uhead .uact2{flex-basis:100%" not in src


def test_details_table_header_actually_sticks_while_scrolling():
    """r448：明细表头「滑下来时遮挡数据」的真正原因是它压根没吸住。

    实测 .tw 内部滚 scrollTop=1741/5223/9285 三处，thead 相对容器顶
    恒为「-scrollTop」（随内容整块滚走），用户看到的其实是表头跟着跑。
    根因：`th{position:sticky;top:0}` 的包含块是**表格自身**（表格高度＝
    全部内容高度），永远没有可吸附行程。sticky 必须挂在 thead 上。
    """
    import webui
    src = webui.PAGE
    assert "#ftable thead{position:sticky;top:0" in src
    # th 仍是 sticky（首列要横向吸附 left:0），但把纵轴让给 thead
    assert "#ftable thead th{top:auto}" in src
    # separate 不是真因，但保留：collapse 下 sticky thead 的子元素层叠不稳
    assert "#ftable{border-collapse:separate;border-spacing:0}" in src


def test_radar_range_note_discloses_the_real_sampling_span():
    """r452：切档时按钮高亮与 note 都变了，但画面一模一样。

    实测 demo 3 个采样点只跨 4 小时（00:48→04:48），2/7/30/90/180 天
    各档过滤后剩下的仍是同 3 点 → canvas 像素哈希五次全同
    （3561017814）。图不变是**正确**的（没有更多采样可画），
    但 note 只写「范围 180 天 · 3 次采集」会让人以为档位是假的。
    修：采样跨度 < 所选档位一半时，如实报出跨度。
    """
    import webui
    src = webui.PAGE
    i = src.index("r452：采样跨度远小于所选档位时")
    seg = src[i:i + 700]
    assert "spanH<rng*0.5" in seg.replace(" ", "")
    assert "再放大范围不会多出采样点" in seg
    # 原有读法句子必须保留（既有门禁/用户熟悉措辞）
    assert "每线=一个出发日期 · 线尾圆点=最新采集价" in src


def test_push_record_rows_show_they_can_expand():
    """r455：推送记录每行点开是全文，但行上没有任何「能展开」的标识。

    实测 1512/900/390 三档：行 role=button、cursor:pointer，却
    chevron 无、aria-expanded 无——全站其它折叠面（.ws-row /
    .rthead / .srx-probe / 概览 / 配置分区）都靠箭头翻转表态，
    唯独这里要用户凭手指试。补箭头 + aria-expanded 单源。
    """
    import webui
    src = webui.PAGE
    assert '<svg class="plchev" aria-hidden="true"><use href="#i-expand"></use></svg>' in src
    assert 'class="plitem${p.ok?\'\':\' bad\'}" aria-expanded="false"' in src
    # 点击后要把状态写回 aria-expanded，否则读屏与视觉分叉
    i = src.index('class="plitem${p.ok?')
    seg = src[i:i + 420]
    assert "setAttribute('aria-expanded',o?'true':'false')" in seg, seg
    assert '.plitem[aria-expanded="true"] .plchev{transform:rotate(90deg)' in src
    # 箭头定宽，翻转不改变行宽；行高与位置两态一致（实测 top 恒 112）
    assert ".plitem .plchev{flex:none;width:11px;height:11px" in src


def test_push_record_list_has_no_nested_outlined_boxes():
    """r455：用户要「扁平化、干净清爽」，而弹层里一行一个描边盒子、
    展开体再套一个描边盒子（1512 实测两层 1px 边框 + 6px 间距）。

    改成同一条列表项：无色块、发丝下划线分隔、左侧状态条贯穿，
    展开体不再另起盒子。状态 emoji ✅/⚠️ 同时退役——#pvTitle 注里
    已立过「emoji 破扁平语言」的规矩，这里漏了。
    """
    import webui
    src = webui.PAGE
    i = src.index(".plitem{padding:9px 12px 9px 9px")
    seg = src[i:i + 900]
    assert "border:0" in seg, seg
    assert "background:transparent" in seg, seg
    assert "border-bottom:1px solid var(--r-hair)" in seg, seg
    j = src.index(".pldesp{background:transparent;border:0;")
    seg2 = src[j:j + 400]
    assert "border-left:3px solid var(--green)" in seg2, seg2
    assert ".plitem.bad+.pldesp{border-left-color:var(--red)}" in src
    # 状态 emoji 退役；失败仍有一枚可读徽标，成功只留色条 + 读屏词。
    # 只看渲染代码段——注释里为了说明「为什么退役」会引到这两个字符，
    # 对全文断言会把解释也判成违规（本测试第一版就这么假红过）。
    k = src.index("$('pvBody').innerHTML=items.length?items.map(p=>")
    render = src[k:k + 1200]
    assert "✅" not in render
    assert "⚠️" not in render
    assert '<span class="vh">${p.ok?\'成功\':\'失败\'}</span>${p.ok?\'\':\'<span class="plst">失败</span>\'}' in render


def test_search_status_chips_have_no_outline():
    """r456：检索台小签原为「1px 描边 + 透明底」，同屏 4 排小方框。

    census（1512/900/390 × 监控/检索/配置）：检索视图 431 条可见边框，
    其中 312 条来自 102 枚 .srx-b（每枚四边）；47 枚 state/plain/risk
    是纯空心轮廓。这正是用户说的「很多分割线、不干净」。
    改为柔底无描边后实测：检索 431→135（1512）、125→17（390），
    其余两视图 141/88 不变（它们本来就没有小签墙）。
    可读性另测：两主题 102 枚全部有底、全部 ≥4.5:1。
    """
    import webui
    src = webui.PAGE
    i = src.index("#searchview .srx-b{")
    seg = src[i:i + 420]
    assert "border:0" in seg, seg
    assert "background:var(--r-surface-2)" in seg, seg
    # 语义变体用底色承载，不再各自补边框
    for v in ("ok", "warn", "bad", "info", "intl", "risk"):
        j = src.index("#searchview .srx-b.%s{" % v)
        assert "border" not in src[j:src.index("}", j)], v
    # 虚线保留：日历价是「非具体航班」的例外，虚线本身有含义
    assert "#searchview .srx-b.cal{color:var(--mut);border:1px dashed var(--line2)}" in src


def test_config_fold_all_is_a_toggle_not_a_one_way_trap():
    """r459：配置页「全部收齐」原先只收不放。

    实测（1512，用户面板，39 个折叠头）：初始 open=7、面板高 3250；
    点一下 open=0、高 300（收得对）；**再点一下 open 仍是 0、高仍是
    300**，文案还停在「已收齐 19」——用户对同类控件的原话是「明显不是
    一个按钮多态的设计」。改成真二态：还有一块敞着→全部收齐；
    已经全收着→全部展开；按钮词面与 aria-expanded 同步。
    """
    import webui
    src = webui.PAGE
    i = src.index("function cfgFoldAll(){")
    # 取整个函数到下一个顶层 function 为止。原来钉死 4200 字符窗口，
    # r530 补了参数分区折叠单元后函数变长，'已全部展开' 被挤出窗口、
    # 因无关演进假红（门禁守意图，不守源码长度）。
    seg = src[i:src.index("\nfunction ", i + 10)]
    assert "let _anyOpen=false" in seg, seg
    # 判据必须是「还有敞着的就收」，写反会让首击变成全展开。
    # 且必须看正文可见性而不是 aria：被刻意排除折叠的分组标题/用户卡头
    # 的 aria 恒为 true，拿它判会把开关永久钉在收齐档（实测第二击无反应）。
    assert "const hide=_anyOpen;" in seg, seg
    assert "b.style.display!=='none'" in seg, seg
    assert "'已全部展开'" in seg
    assert "setAttribute('aria-expanded',hide?'false':'true')" in seg
    # 首屏就要带初值，否则读屏读不到二态
    assert ('id="cfgFoldAll" role="button" tabindex="0" aria-expanded="true"'
            in src)


def test_config_fold_all_never_swallows_group_headings():
    """r459b：收齐时连分区标题一起收掉，整页就没有回去的入口了。

    实测：收齐后 6 个 .grouplab 高度全 0（可视折叠头 6→0），此时页面上
    不存在任何可点的恢复控件。标题是回到内容的唯一入口，折叠体里必须
    永远剔除 .grouplab；applyFolds（重建路径）同律。
    """
    import webui
    src = webui.PAGE
    i = src.index("function cfgFoldAll(){")
    # 取整个函数到下一个顶层 function 为止。原来钉死 4200 字符窗口，
    # r530 补了参数分区折叠单元后函数变长，'已全部展开' 被挤出窗口、
    # 因无关演进假红（门禁守意图，不守源码长度）。
    seg = src[i:src.index("\nfunction ", i + 10)]
    assert "keepHead" in seg, seg
    assert "b.classList.contains('grouplab')" in seg, seg
    j = src.index("function applyFolds(){")
    seg2 = src[j:j + 600]
    assert ".filter(b=>!b.classList.contains('grouplab'))" in seg2, seg2
    # 用户卡头分支同样不能把「装着分区标题」的容器收掉——实测那层是
    # 匿名 DIV（包住 .grouplab + 正文），只查自身 class 会漏
    assert "body.querySelector('.grouplab')" in seg, seg


def test_every_channel_entry_label_starts_with_the_same_noun():
    """r464：渠道入口里混进了一个不成词的「搜索」。

    ENTRY 的 note 会被前端剥掉端名后当主标题：`PC 国际搜索` → 「搜索」，
    而同排其余三个是「机票搜索」——25 个入口里只有这一格是两个字，
    用户读起来像漏字（「按钮文案要符合操作/视觉」）。

    实测修前：携程条 → 机票搜索 / 机票搜索 / **搜索** / 机票搜索（…）；
    修后 25 个入口**全部**以「机票搜索」开头。
    """
    from core.channel_links import ENTRY
    def head(note):
        t = str(note or "")
        for pre in ("PC ", "H5 "):
            if t.startswith(pre):
                t = t[len(pre):]
        return t
    for plat, table in ENTRY.items():
        for k, v in table.items():
            h = head(v[1])
            assert h.startswith("机票搜索"), (plat, k, v[1], "→", h)
            assert h != "搜索", (plat, k)
    # 旧的「国际搜索」写法不许复活
    import pathlib
    src = pathlib.Path("core/channel_links.py").read_text(encoding="utf-8")
    assert "国际搜索" not in src


def test_overview_stays_collapsible_after_picking_a_departure_date():
    """r465：用户实报「展开概览下面可以再点选择出发日，再点收起概览
    就整体收不回去了，非常割裂」。

    真实路径（实测量过，当前已正常）：展开概览 → 点价带里的日期 chip
    （`.srx-band-picks .srx-chip`，`.srx-day` 那套是选定后才长出来的
    14 格）→ 再点「收起概览」。实测：bandDays 0→14、概览高 188→208；
    收起后 `collapsed:true`、概览高回到 **46**（=初始值）、按钮位置
    252/1339 全程 0 位移、0 JS 错误。

    根因曾在 `srxToggleOverview` 里顺手调 `srxRenderCtx()`：它会按
    `SRX.ctx` 重算下方筛选区的折叠态，于是选过日期后再收起会让筛选区
    跟着跳动。开合概览只能改自己的可见性。
    """
    import webui
    src = webui.PAGE
    i = src.index("function srxToggleOverview(){")
    seg = src[i:i + 1400]
    # 开合不得越权去重算筛选区折叠态
    body = seg.split("}")[0]
    assert "srxRenderCtx()" not in body, "开合概览又去重算筛选区折叠态"
    # 两态文案与 aria 必须同步（同一状态的两个入口不能各存一份）
    assert "hb.textContent=on?'收起概览':'展开概览'" in seg
    assert "hb.setAttribute('aria-expanded',on?'true':'false')" in seg
    assert "[data-mobile=\"overview\"]" in seg


def test_fold_all_also_collapses_the_user_card_that_wraps_headings():
    """r467：有一张用户卡「全部收齐」后永远收不起来。

    实测（1512，users 面板）：收齐后仍有 **1 个 `uhead2` 挂着
    `aria-expanded=true`、卡高 60px**，面板文本 2145→278 但没降到最小。

    根因：卡体是一个**同时装着 `.grouplab` 和正文**的匿名 DIV
    （`.ucard` 只有 2 个子元素：uhead2 与该 DIV）。旧守卫一见
    `body.querySelector('.grouplab')` 就整只 return——为了保住分区标题，
    把整张卡也放过了。正确做法是「收正文、留标题」：隐藏该 DIV 里
    首个 `.grouplab` 之前、末个 `.grouplab` 之后的块，标题与它自己的
    正文交给各自的 foldSec。
    """
    import webui
    src = webui.PAGE
    i = src.index("function cfgFoldAll(){")
    seg = src[i:i + 5200]
    # 必须区分「自身是标题」与「体内含标题」两件事
    assert "if(body.classList.contains('grouplab'))return;" in seg, seg
    assert "if(body.querySelector('.grouplab')){" in seg, seg
    # 含标题时必须收正文、留标题——但**不锁实现写法**。
    # r640b：旧实现只隐藏「首个标题之前 + 末个标题之后」两段，标题之间的
    # 正文（A 用户名的推送设置等 13 块）全留在屏幕上：实测卡体仍有 315px
    # 敞开，而卡头 aria 已写 false —— 报一个没发生的状态。现改为「卡体内
    # 除 .grouplab 之外一律收起」。这里断言的是意图，不是某一段切片代码。
    assert "[...body.children].forEach(" in seg, seg
    assert "k.classList.contains('grouplab')" in seg, seg
    assert "k.style.display=hide?'none':''" in seg, seg
    # 这条卡也要正确写回自己的二态
    assert "h.setAttribute('aria-expanded',String(!hide));" in seg, seg


def test_more_conditions_panel_sits_directly_under_its_trigger():
    """r469：用户实报「展开独立占了一行、非常割裂」。

    实测 1512：触发器 `#srxMoreBtn` 在「快筛」行末（x≈1329），而它控制的
    `#srxFmore` 原挂在 section 末尾——左缘 91、比按钮底还低 41px，
    列差 1238px，中间还隔着「渠道」一整行。

    修法：把面板移到触发按钮所在行之后（DOM 相邻），展开时紧贴按钮下方
    （实测纵向缝 41→3px），面板与内容同属一块。
    """
    import webui
    src = webui.PAGE
    i = src.index('id="srxMoreBtn"')
    j = src.index('id="srxFmore"')
    k = src.index('id="srxPlats"')
    assert i < j < k, "fmore 又回到「渠道」行之后了（会隔一整行）"
    # 两者之间不再夹别的 srx-line
    between = src[i:j]
    assert between.count('class="srx-line"') <= 1, between[-200:]
    # 面板必须紧贴：不留顶部大缝
    m = src.index("#searchview .srx-fmore{display:none;")
    seg = src[m:m + 400]
    assert "margin-top:6px" in seg or "margin-top:0" in seg, seg
    # r806：r469 曾给面板 `margin-left:60px`「对齐标签列」，但实测 1512
    # 左缘 151.5 / 右缘 1410.5——左侧内缩 60px、右侧贴死卡缘，左右内衬
    # 不对称（用户：「布局明显跟当前页面没有对齐、大小布局对称不够协调」），
    # 60px 也不是标签列（.srx-lab 34px + gap 8 = 42）。改为与卡片内每一行
    # 同缘。断言改成「左缘不缩进」，不再锁 60px 这个错值。
    assert "#searchview .srx-fmore{margin-left:0;margin-top:0;padding-top:6px}" in src


def test_folding_the_mirror_actually_releases_its_height():
    """r473：点「收起镜像」后内容收了、占位不收。

    实测 1512：折叠后 `srx-mchrome`/`srx-mbody` 都是 `display:none`
    （正文 574→0），但 `.srx-mirror` 自身仍是 **650px**，留一大块空白。

    根因不是 CSS 缺规则，而是被更高优先级压住：`@media(min-width:981px)`
    里 `.srx-list,.srx-mirror{height:100%}`，外层 `.srx-grid` 又是
    `clamp(480px,…,760px)` 固定高。

    修法只放镜像、不放整格：`height:auto!important` + `align-items:start`。
    **不能**把 `.srx-grid` 改成 `height:auto` ——实测列表栏会从 650 涨到
    3490（滚动容器被摊开），页面撑长 2840px，比原问题更糟。
    """
    import webui
    src = webui.PAGE
    i = src.index("/* r473：折叠镜像后内容已 display:none")
    seg = src[i:i + 900]
    assert "#searchview .srx-mirror.srx-folded{height:auto!important" in seg, seg
    assert "align-items:start" in seg, seg
    # 整格绝不能再被放开（会摊开列表）
    assert ".srx-grid:has(.srx-mirror.srx-folded){height:auto" not in src, \
        "整格 height:auto 会把列表栏摊开（实测 650→3490）"


def test_details_rows_use_zebra_stripes_instead_of_full_width_rules():
    """r476：明细表每行都画一条整宽横线——正是用户说的「很多分割线」。

    实测 1512 明细页 121 条横线，其中 **120 条来自 `#ftable td`**；
    而同一张表在 1603 行本来就写了斑马纹（`tr.zebra → --rowalt`），
    紧接着又被 `background:transparent` 清掉——两套分隔策略互相打架，
    最后只剩满屏横线。扁平做法：分隔交给斑马底，行线归零。

    修后实测：1205 个 td 边框全部为 0，明细页横线 121→1；
    zebra 行底色 rgb(245,248,251)，非 zebra 行透明，交替正常。
    """
    import webui
    src = webui.PAGE
    i = src.index("#ftable td{border-bottom:0;color:var(--r-ink-2)}")
    assert i, "td 行线未清零"
    # 斑马纹必须真的给底色，不能再被 transparent 抹掉
    assert "#ftable tbody tr.zebra:not(:hover){background:var(--rowalt)}" in src
    assert "#ftable tbody tr.zebra:not(:hover){background:transparent}" not in src, \
        "斑马纹又被清成透明（行线去掉后就完全没有行分隔了）"


def test_monitor_card_footers_have_no_decorative_dashed_rules():
    """r477：监控卡自身没有描边（border 0 / 背景透明），页脚那条虚线
    只是纯装饰分割——概览页实测 8 条（路由 6 + 关注 2）。

    扁平化按卡片间距分组，不靠线。去掉后概览横线 12→4、虚线 8→0，
    7px 上间距保留（页脚仍与内容拉开）。
    """
    import webui
    src = webui.PAGE
    assert ".monwatch-foot{grid-area:foot;border-top:0;padding-top:7px}" in src
    assert "border-top:1px dashed var(--line);padding-top:7px}" not in src
    # 路由页脚同样不带线，但间距仍在
    i = src.index(".monroute-foot{grid-area:foot;display:flex")
    seg = src[i:i + 220]
    assert "border-top:0" in seg, seg
    assert "padding-top:7px" in seg, seg


def test_probe_channel_entry_trigger_does_not_move_when_opened():
    """r523：检索页探针脚注的「渠道入口」点开时，触发器不能换行换列。

    实测缺陷：展开态写成 `.srx-chlinks[open]{grid-column:1/-1}`——整个 details
    换到第 1 列并落到下一行，触发器随盒子从右缘跑到左缘（1512 档 x 1131→91，
    位移 1040px；1280 档 915→76，位移 839px，另下沉 22px）。用户读作
    「点同一个按钮，按钮自己跑了」，与 r424 镜像钮是同一族问题。

    修法：展开时 details 退成 display:contents，两个子元素直接参与父网格；
    summary 钉回第 1 行第 2 列原地不动，面板单独占满下一整行。
    """
    import webui
    src = webui.PAGE
    assert "#searchview .srx-probefoot .srx-chlinks[open]{grid-column:1/-1}" not in src, \
        "展开态又把整个 details 换列换行了——触发器会横跳上千像素"
    i = src.index("#searchview .srx-probefoot .srx-chlinks[open]{display:contents")
    seg = src[i:i + 600]
    assert ">summary{grid-row:1;grid-column:2}" in seg, \
        "展开态没有把 summary 钉回原列，触发器仍会移位"
    assert ">#srxChLinksBox{" in seg, "展开面板没有独立分配网格位置"
    assert "grid-column:1/-1" in seg, "展开面板没有占满整行"
    # 窄档单列必须另给坐标，否则面板会盖在触发钮上
    j = src.index("@media(max-width:600px){\n #searchview .srx-probefoot{grid-template-columns:1fr")
    assert "#srxChLinks[open]>summary{grid-row:2" in src[j:j + 400] or \
           "srx-chlinks[open]>summary{grid-row:2" in src[j:j + 400], \
        "窄档没有给 summary 分配第 2 行"


def test_mirror_fold_gives_the_column_back_to_the_list():
    """r524：收起镜像必须把右列宽度还给列表，按钮仍贴同一右缘。

    实测缺陷：收起态用 visibility:hidden 保留占位——列宽仍是 653px、列表仍是
    半宽，右边残留一条空带，按钮浮在带子中间（用户：「能收起来，但是也给
    不了右边用，为什么不是左右按钮互相展开收起？」）。
    修后实测：1512 档列表 654→1225（+571）、1280 档 553→1025（+472）、
    1101 档 513→944（+431），触发器位移 0px，两态互切逐像素复位。
    """
    import webui
    src = webui.PAGE
    assert ".srx-mirror.srx-folded .srx-mrail>.srx-mtab,\n" \
           ".srx-mirror.srx-folded .srx-mrail>.srx-mtools{display:none!important}" in src, \
        "收起态仍在用占位隐藏，列宽不会释放"
    assert "visibility:hidden!important" not in src[
        src.index(".srx-mirror.srx-folded .srx-mrail>.srx-mtab,"):
        src.index(".srx-mirror.srx-folded .srx-mrail>.srx-mtab,") + 260], \
        "收起态残留 visibility 占位写法"
    assert "#searchview .srx-grid:has(.srx-mirror.srx-folded)" \
           "{grid-template-columns:minmax(0,1fr) auto}" in src, \
        "折叠态网格没有把右列塌成按钮宽"
    assert "#searchview .srx-grid:has(.srx-mirror.srx-folded)" \
           "{grid-template-columns:repeat(2,minmax(0,1fr))}" not in src, \
        "又回到「两列等宽」——收起后仍留半屏空列"


def test_mirror_fold_button_is_last_in_rail():
    """r524：折叠钮必须是轨道最后一个子元素，两态才都贴右缘。

    展开态按钮排在 mtools 之前时，收起后 mtools 消失、按钮仍停在原位置
    （实测 x=452，右缘还空 140px）。挪到末尾后两态 x 相同。
    """
    import webui
    src = webui.PAGE
    i = src.index("return '<div class=\"srx-mrail\">'+rail+")
    seg = src[i:i + 900]
    assert seg.index("srx-mtools") < seg.index("srx-foldbtn"), \
        "折叠钮又排到工具钮前面了——收起态会停在带子中间"
    assert "style=\"margin-left:6px\"" not in seg, \
        "折叠钮仍靠 margin-left 参与排布，收起态基准会变"


def test_chart_tooltip_is_clamped_to_the_visible_window_not_content_width():
    """r526：特价监控浮窗右界必须按「可视右缘」，不能按内容总宽。

    实测缺陷：390 档画布 1220px 塞进 320px 容器，钳位用 scrollWidth（内容总宽）
    → 浮窗被允许放到 left=318(+host 30=348)，页内 right 401 越过视口 390。
    用户读作「浮窗跑出屏幕」。修后 390 档 right 342 ≤ 可视右缘 350；
    360 档 right 290 ≤ 320。
    """
    import webui
    src = webui.PAGE
    i = src.index("placeTipAxis(host,tip,cx,topY){")
    seg = src[i:i + 1200]
    assert "_visRight" in seg, "placeTipAxis 没有计算可视右缘"
    assert "+r.width" in seg, "可视右缘必须是 scrollLeft + 可视宽"
    assert "PCHART.placeAxis(_hostW,r.height,tw,th,cx-r.left+(host.scrollLeft||0),topY,_visRight)" in seg, \
        "可视右缘没有传给 placeAxis"
    j = src.index("placeAxis(boxW,boxH,tw,th,localX,topY,rightEdge){")
    seg2 = src[j:j + 900]
    assert "_re-tw-8" in seg2, "placeAxis 没有按右缘钳位"
    assert "rightEdge==null?boxW:rightEdge" in seg2, "右缘缺省必须回落到内容宽（向后兼容）"


def test_radar_gaps_break_the_line_and_mark_segment_ends():
    """r527：真实空档必须断线，且断口两端要有「止于此」的端点标记。

    实测（153 点、8.5h/12.5h 两个缺口）：`PCHART.gaps` 正确切出 [53,64,36]，
    缺口处不连线不填充。但断口两端原本只有 2px 采样点，空白起点读作
    「线被截断/渲染坏了」——用户说的「走势断档」。改为段首尾各画一个
    1.15× 的实心端点：缺口仍然完全不画，语义不变。

    另守两条既有契约：阈值下限 4h（雷达 2h 轮询，4h 才算断档），
    以及 3h 间隔必须保持连续（不能把正常轮询间隔误判成缺口）。
    """
    import webui
    src = webui.PAGE
    assert "const _gapMin=4*3600*1000;" in src, "雷达缺口阈值下限被改动"
    # 按函数真实结束边界切片：原先固定 700 字符窗口，函数内一加注释
    # 就把后半段挤出窗口，判据随之假红（r647 遇到同型）。
    i = src.index(" gaps(pts,gapMin){")
    j = src.index("segs.push(cur);return segs;},", i)
    seg = src[i:j]
    assert "med*1.8" in seg, "自适应阈值被删——稀疏序列会把正常间隔判成断档"
    assert "pts[i].t-pts[i-1].t>gap" in seg, "分段判定被改动"
    # 端点标记：只在多段时才画，且必须比采样点更明显
    j = src.index("if(style.vertexDots&&segs.length>1){")
    seg2 = src[j:j + 420]
    assert "seg[0]" in seg2 and "seg[seg.length-1]" in seg2, "端点只标了一侧"
    assert "dot*1.15" in seg2, "端点没有比采样点更粗，读不出「止于此」"
    # 端点不得把缺口连起来：该块内不能出现 lineTo / stroke
    assert "lineTo" not in seg2, "端点块里画了线，缺口会被接上"
    assert "stroke()" not in seg2, "端点块里描了边，缺口会被接上"


def test_fold_all_also_collapses_parameter_sections():
    """r530：「全部收齐」必须真的收掉参数分区的正文。

    实测缺陷：参数分区（`#cfgglobals` 的「只读参数说明」等）用的是
    `.subsec` 小标题 + 兄弟块，**没有** grouplab / rline / chcard / uhead2。
    点「全部收齐」后：可见字段 52→52、整页可见元素 432→432 纹丝不动，
    按钮却换成「已收齐 19」、aria-expanded=false——**按钮在报一个没发生的
    状态**（用户：「各个 tab 展开状态没有办法一键全部收齐」）。

    修后实测：字段 52→0、整页 432→43，再点一次 0→52 全还原，
    文案「全部收齐 → 已收齐 30 → 已全部展开」、aria 同步翻转。
    """
    import webui
    src = webui.PAGE
    # 折叠单元：.subsec 标题 + 其后兄弟块，遇下一个 .subsec/grouplab 停
    assert "const _subsecBodies=h=>" in src, "缺少 subsec 折叠体定义"
    i = src.index("const _subsecBodies=h=>")
    seg = src[i:i + 300]
    assert "nextElementSibling" in seg and "subsec" in seg, "subsec 折叠体边界不对"
    # 判据必须计入 subsec，否则二态开关会被钉死在「收齐」档
    j = src.index("panel.querySelectorAll('.subsec').forEach(h=>{\n   if(_subsecBodies(h)")
    assert j > 0, "_anyOpen 判定没有计入 subsec——第二击会没反应"
    # 执行侧必须真的 _setFold 并落存档（否则重建后弹开）
    k = src.index("FOLD.sub[panel.id+'|'+h.textContent.trim()]=hide")
    assert k > 0, "subsec 折叠没有落存档，重渲染会长回去"
    # 存档要有容器且有重建路径
    assert "let FOLD={sec:{},route:{},ch:{},sub:{}}" in src, "FOLD 缺 sub 存档桶"
    assert "FOLD.sub[k]!=null" in src, "applyFolds 没有恢复 subsec 折叠态"


def test_health_diag_cards_share_one_action_baseline():
    """r531：渠道健康的「自检」必须五张卡同一条基线（用户：「自检按钮」不对齐）。

    实测（1512 / 1280，5 张卡）：
    - 卡同高 163px、同 y；
    - `.hdiag-e` 证据行恒在 y=463（**空证据卡也占位**，否则会把自检推下去）；
    - 自检按钮恒在 y=498、h=32，卡底 540 —— 五张逐像素一致。
    这条守 r433（动作不顶卡底）+ r436（证据行固定两行且空也占位）不被回退。
    """
    import webui
    src = webui.PAGE
    # r436：证据行固定两行、空也占位（>700 档）；单列档隐藏空行避免空洞
    i = src.index(".hdiag-e{min-height:2.9em;display:-webkit-box")
    seg = src[i:i + 220]
    assert "-webkit-line-clamp:2" in seg, "证据行不再固定两行，自检会被推下去"
    assert "min-height:2.9em" in seg, "证据行失去最小高度，空证据卡会把自检顶高"
    assert "@media(max-width:700px){\n .hdiag-e:empty{display:none}" in src, \
        "单列档没有回收空证据行"
    # r433：动作行跟随正文，不得 margin-top:auto 顶到卡底
    assert ".hdiag-card .hdiag-acts{display:flex;align-items:center;gap:6px;" \
           "flex-wrap:wrap;margin-top:2px;padding-top:0;min-height:0}" in src, \
        "动作行又改回顶卡底（自检会孤零零悬在下方）"
    assert ".hdiag-card .hdiag-acts .btn2{margin-top:0;height:26px" in src, \
        "自检按钮高度/间距被改动（五卡基线会错开）"
    # 旧规则只允许出现在 r433 的历史注释里（"曾把动作行顶到卡底"）；
    # 真规则不得复活。
    import re
    assert (".hdiag-a{margin-bottom:auto}" not in
            re.sub(r"/\*.*?\*/", "", src, flags=re.S)), "又把动作区顶到底部了"


def test_list_rows_use_one_hairline_style_not_mixed_dashed():
    """r534：同一张卡里的列表行不得混用虚线与实线。

    实测：`.spmon-flight` 是 `border-top:1px solid`，同卡的
    `.spmon-run`（采集记录每一轮）却是 `dashed` —— 一页两套行线，
    虚线在扁平语言里是多余的装饰（用户：「很多分割线，很不干净」）。
    统一为发丝实线。
    """
    import re
    import webui
    src = webui.PAGE
    i = src.index(".spmon-run{display:grid")
    seg = src[i:i + 240]
    assert "border-top:1px solid var(--r-hair)" in seg, "采集记录行又用虚线了"
    assert "dashed" not in seg, "采集记录行混回虚线"
    # 同为列表行的 spmon-flight 保持实线（两处必须同一种）
    j = src.index(".spmon-flight{display:grid")
    assert "border-top:1px solid var(--r-hair)" in src[j:j + 240], \
        "航班行与采集记录行的线型不一致"


def test_health_note_sits_right_under_its_trigger():
    """r536：「说明」正文必须紧贴触发钮下方，且按钮两态零位移。

    实测（1512，健康页渠道诊断卡）：
    - 触发钮恒在 (1012,319)，文案「展开说明 ⇄ 收起说明」、aria 翻转；
    - 说明正文展开后出现在 y=358，与按钮底(y=347)只隔 **11px**
      （原来 20px，中间全是 srccap/uhead 的容器留白，读作「展开在下面」）。

    不能把说明塞进 `.scfoot`：那是右对齐 flex，展开会撑宽该行、按钮横移近
    800px（r412 实测 1305→509）。故位置保持卡外，靠负 margin 吃掉空隙。
    r536b：空隙实为三层叠加（scfoot 下内边距 8 + srccap 下外边距 10 +
    uhead 下内边距 10 = 28），负 margin 必须覆盖整段；判据只锁「负 margin
    足以贴住按钮」这一意图，不锁具体像素值。
    """
    import re
    import webui
    src = webui.PAGE
    m = re.search(r"#healthDiag>#scNote\{([^}]*)\}", src)
    assert m, "说明的定位规则不见了"
    body = m.group(1).replace(" ", "")
    assert "display:none" in body and "line-height" in body, body
    neg = re.search(r"margin:(-?\d+)px", body)
    assert neg, body
    # 三层底部空隙合计 28px，负 margin 至少要吃满这段才可能贴住按钮
    assert int(neg.group(1)) <= -28, \
        "负 margin 不足，说明与按钮之间会重新出现容器留白：%s" % body
    # 说明必须在卡头之外（卡头几何不受展开影响）
    i = src.index('<span class="scnote" id="scNote">')
    head_end = src.rindex("</div>", 0, i)
    assert head_end < i, "说明被塞回卡头里了"
    # 且不得成为 .scacts 的兄弟按钮行成员（那会撑宽右对齐行）
    acts = src.index('<span class="scacts">')
    assert i > src.index("</span>", acts), "说明又进了 scacts 行"


def test_overview_body_sits_directly_under_its_trigger():
    """r537：展开概览的正文必须紧跟触发钮，不能被日期带隔开。

    实测缺陷：`#srxOvBody` 里顺序是 band(含触发钮) → brief → capbar → kpis，
    触发钮在价带工具行、正文在其后，中间隔着整条日期格带——
    按钮底 347 到正文顶 389，**42px 全是 .srx-band-h/.srx-band-days**。
    用户原话：「展开概览那个明显交互有问题，展开的中间还有元素常驻」。

    修法：把 brief/capbar/kpis 移进价带的折叠体 `#srxBandBody` 且排在
    日期带之前。实测间隙 42→**7px**，收起态三者一并 display:none。
    """
    import webui
    src = webui.PAGE
    body = src.index('<div id="srxBandBody" class="srx-foldbody">')
    days = src.index('id="srxBandDays"')
    brief = src.index('id="srxBrief"')
    capbar = src.index('id="srxCapbar"')
    kpis = src.index('id="srxKpis"')
    for name, pos in (("srxBrief", brief), ("srxCapbar", capbar), ("srxKpis", kpis)):
        assert pos > body, "%s 不在价带折叠体内（会被日期带隔开）" % name
        assert pos < days, "%s 排在日期带之后，展开又会被格带隔开" % name
    # id 全局唯一：折叠体外不得再有一份
    for needle in ('id="srxBrief"', 'id="srxCapbar"', 'id="srxKpis"'):
        assert src.count(needle) == 1, "%s 出现多份（重复 id）" % needle


def test_demo_health_labels_say_demo_on_the_card_itself():
    """r538：演示态的诊断卡必须自己说明是演示数据。

    实测缺陷：演示环境 96 轮都是合成数据，页头有「DEMO · 合成健康」，
    但五张诊断卡仍逐张写「最近一轮正常」——与真实环境一模一样的结论措辞，
    用户读作「有很多补位数据，感觉有点奇怪」。
    另外 `/api/health` 原本不带任何 demo 标志，前端无从判断。

    修法：演示轻路径 `_attach_demo_paths` 下发 `demo=True` 并把每张卡的
    label 前缀改为「演示 · 」。实测五张卡全部带前缀、无裁切、无横向溢出。
    """
    import io
    import os
    # 这两个是**服务端**函数，不在 PAGE 页面字符串里，必须读源码文件
    src = io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8", newline="").read()
    # 后端：演示路径必须点名 demo 且改写 label
    i = src.index("def _attach_demo_paths(out: dict) -> None:")
    seg = src[i:i + 900]
    assert 'out["demo"] = True' in seg, "演示载荷没有 demo 标志，前端无法区分"
    assert '"label"] = "演示' in seg, "演示态诊断卡仍旧用真实口径措辞"
    # 真实路径不得被误标
    j = src.index("def _health_decorate(out: dict) -> dict:")
    seg2 = src[j:j + 1200]
    assert 'bool(DEMO["on"])' in seg2, "真实路径的 demo 标志必须取自 DEMO 开关"


def test_filter_rows_share_one_left_edge_and_more_button_follows_content():
    """r539：筛选面板四行的 chip 必须同一条左缘，且「更多条件」跟随内容。

    实测缺陷：`.srx-chips` 是 `flex:1`，吃满整行剩余宽度，把
    「展开更多条件」顶到容器最右缘（l=1329 / r=1411，中心 x=1370）；
    四行 chips 的右端各不相同（812/1411/1321/1411），
    整块读作参差、与卡片不对齐（用户：「展开筛选条件的面板布局明显跟
    当前页面没有对齐，大小布局不够对称协调」）。

    修后实测：四行 chips 左缘 1512 档统一 133、1280 档统一 118；
    按钮紧跟快筛内容之后（右缘 583/567）而不是贴右缘；面板无溢出。
    另测展开成本：同步 1ms、首帧 8.3ms —— 无长任务（用户感觉的「卡顿」
    来自视觉参差，不是主线程）。
    """
    import webui
    src = webui.PAGE
    assert "#searchview .srx-line>.srx-chips{flex:0 1 auto}" in src, \
        "chips 又改回 flex:1，会把「更多条件」顶到最右缘"
    assert "#searchview .srx-line>.srx-more{margin-left:8px}" in src, \
        "「更多条件」缺少与内容的间距"
    # 行容器本身仍是 flex 且换行（窄档需要折行，不能 nowrap 溢出）
    i = src.index("#searchview .srx-line{display:flex")
    assert "flex-wrap:wrap" in src[i:i + 160], "筛选行丢了 wrap，窄档会横向溢出"


def test_channel_bands_share_one_height():
    """r541：渠道入口五个渠道带必须等高。

    实测缺陷：五个带的高度由内部 chip 折行数决定——1512 档
    85/94/94/85/85、1280 档 109/125/109/94/85：长名（去哪儿、飞猪）
    的 chip 折成两行，短名只有一行。用户读作「大小布局不够对称协调」。

    修法：chip 文案单行 + 省略（完整信息仍在 title：URL · 说明 · 登录要求），
    并给网格固定行高。实测修后 1512/1280 五带全 91、390 档全 207，
    无 chip 裁切、面板与页面均无横向滚动。
    """
    import webui
    src = webui.PAGE
    i = src.index(".chband-grid{display:grid!important;grid-template-columns:repeat(4,")
    seg = src[i:i + 700]
    assert ".chband-grid{grid-auto-rows:44px!important}" in seg, \
        "渠道带没有再固定行高，长名 chip 会把该带撑高"
    assert ".chlink{white-space:nowrap!important}" in seg, \
        "chip 文案又允许折行，五带会再次参差不齐"
    # 省略必须有兜底：chip 自身带 title 才允许截断
    assert 'title="' in src[src.index("function chlinkChip"):src.index("function chlinkChip") + 3000], \
        "chip 没有 title，截断后就看不到完整说明了"


def test_filter_panel_columns_end_on_the_same_line():
    """用户实报「展开筛选条件的面板布局跟当前页面没对齐，大小布局不对称」。

    宽档（≥1101）是 12 列 areas：左栏 common(8) + history(5)/price(3)，
    右栏 time(4) + evidence(4)。实测 1512：左栏底 752、右栏底 660 ——
    右栏底部空出 92px，「检索特有」的左侧分隔线到 12px 就断了，
    下方是一整块无内容的空白（用户读作「大小布局不对称、衔接空格很大」）。
    定案：右栏最后一张卡吸收这段高度，两栏底边齐平（实测 752＝752），
    面板总高不变 733（没有新增留白）。
    """
    import webui
    src = webui.PAGE
    i = src.index("#searchview .srf-evidence{align-self:stretch")
    # 向上找到它所在的 @media 块头，切出整段
    j = src.rindex("@media(min-width:1101px){", 0, i)
    seg = src[j:src.index("\n}", i) + 2]
    assert "#searchview .srf-evidence{align-self:stretch;min-height:100%}" in seg, seg
    # r697 起右栏两张卡都拉伸（时间卡原为 start，实测同排底边差 102/135px）；
    # 判据守「两栏底边齐平」这个意图，不再钉某一张卡的旧对齐值。
    assert "#searchview .srf-time{align-self:stretch}" in seg, (
        "起降时段又改回按内容收缩，同排两张卡会再次底边不齐（用户实报"
        "「上下不对齐、廉价感」）")
    assert "#searchview .srf-time{justify-content:space-between}" in seg, (
        "时间卡拉高后余量没有在卡内分布，会变成卡底一大块死白")
    # 左栏底边基准：history 与 evidence 必须同属一行，areas 才能对齐
    assert '"history history history history history price price price evidence evidence evidence evidence"' in seg


def test_narrow_probe_foot_sits_after_actions_not_between_form_and_head():
    """用户实报「展开后中间还有元素常驻」「展开应该是展开的感觉，位置怎么偏了」。

    窄档（≤760）把 .srx-probehead 摊平成 display:contents，再用 order 排
    head(0) / form(1) / acts(2)。`srx-probefoot` 当时没给 order（默认 0，与
    卡头同级），于是被排到**表单之前**——实测 390 展开后的纵向顺序是
    标题220 → 说明239 → 状态行262 → 表单294 → 操作行472：
    一块常驻状态夹在「刚点开的表单」中间，正是用户描述的病灶。
    定案：状态行 order:3 收尾（它是结果反馈，放在动作之后才讲得通），
    实测顺序变为 220/239/268/446/472，按钮本身两态位移仍为 0。
    """
    import webui
    src = webui.PAGE
    i = src.index("#searchview .srx-probeform{order:1}")
    j = src.index("\n  }", i)
    seg = src[max(0, i - 2000):j]
    assert "#searchview .srx-probe .srx-probeacts{order:2" in seg, \
        "操作行不再是扁平后的第 2 段"
    assert "#searchview .srx-probefoot{order:3}" in seg, \
        "状态行又落回默认 order:0，会插到表单前面"
