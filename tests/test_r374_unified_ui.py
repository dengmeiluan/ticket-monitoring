# -*- coding: utf-8 -*-
"""r374 全站统一：走势单内核 + 折叠相邻律 + 配置 chip 兄弟关系。

这些断言都对着**行为契约**，不锁某段 CSS 字面量：
- 走势：三处几何/刻度/断档/最近点只能来自 PCHART 一份实现；
- 折叠：展开体紧跟触发器、触发器不动、真收起；
- 配置：状态 chip 必须是兄弟节点（不得 button-in-button）。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


# ---------- 走势：三处共用一个内核 ----------

def test_single_chart_kernel_exists_and_is_used_by_all_three():
    src = _src()
    for api in ("const PCHART=", "PCHART.frame(", "PCHART.axes(",
                "PCHART.domain(", "PCHART.gaps(", "PCHART.pick(",
                "PCHART.placeTipAxis("):
        assert api in src, api
    # 雷达折线 / 雷达K线 / 关注折线 / 关注K线 都必须落到内核
    assert src.count("PCHART.frame(") >= 4, "四处坐标域必须走内核"
    assert "const PCHART_PAD={L:48,R:16,T:12,B:26,B2:40};" in src


def test_no_chart_reimplements_its_own_tick_step():
    """取整阶梯只允许 PCHART.niceTicks 一份；本地再写一份必然漂移。"""
    src = _src()
    assert "const _niceSet=PCHART.niceTicks(lo,hi,4);" in src
    assert "const _nice=[1,2,5,10].find(m=>m*_mag>=_raw*0.5)*_mag;" not in src
    assert "const ticks=wsNiceTicks(" not in src


def test_no_chart_reimplements_gap_detection():
    """缺口判定只允许 PCHART.gaps 一份：三处阈值不同会出现「这页断、那页连」。"""
    src = _src()
    assert "const segs=PCHART.gaps(pts,style.gapMin);" in src   # 雷达
    assert "const segs=PCHART.gaps(pts,Math.max(36*36e5,span*.18));" in src   # 关注
    assert "BUCKET*60000*1.2).map(seg=>seg.map(o=>o.i))" in src   # 航线
    # 旧的三处各自算中位间隔已移除
    assert "_iv.sort((a,b)=>a-b);\n    const _med=" not in src


def test_radar_hover_single_path_not_duplicated():
    """雷达悬停曾把命中逻辑抄两份（含陈旧尺寸分支），两份必然漂移。"""
    src = _src()
    i0 = src.index("function spMonHover(")
    i1 = src.index("(function(){", i0)
    seg = src[i0:i1]
    assert seg.count("PCHART.pick(") == 1, "命中只能走一条路径"
    assert "const dx=Math.abs(g2.X" not in seg, "陈旧尺寸分支未合并"


def test_radar_tooltip_is_dark_not_white_patch():
    """浅色卡底 tooltip 压在线上就是一块白斑，会把短点盖掉。"""
    src = _src()
    i0 = src.index(".spmon-tip{")
    seg = src[i0:i0 + 260]
    assert "rgba(44,62,80,.93)" in seg, seg
    assert "background:var(--r-surface)" not in seg


def test_radar_canvas_is_really_scrollable_or_fits():
    """可滚宽度不能被 CSS 压回容器宽，否则拖动指令形同虚设。"""
    src = _src()
    assert "const W=Math.max(baseW,Math.min(units*MINPX,baseW*2.4));" in src
    assert "wrap.scrollLeft=wrap.scrollWidth-wrap.clientWidth;" in src
    assert "SPMON.userPan=true" in src, "用户拖动后不得被自动回拉"
    assert "#spMonChart{display:block;width:100%;max-width:100%;height:178px}" not in src


def test_radar_series_colors_have_contrast():
    """非聚焦日期线用 #aab4c0×.55 在白底上近乎消失（读作白色遮挡）。"""
    src = _src()
    assert "alpha:low||sel?1:.7" in src
    assert "alpha:low||sel?1:.55" not in src


# ---------- 折叠：相邻律 / 不动律 / 真收起 ----------

def test_overview_is_one_self_contained_block():
    src = _src()
    i0 = src.index('<section class="srx-overview')
    i1 = src.index("</section><!-- /srxOverview -->")
    seg = src[i0:i1]
    # 触发器与正文同块，且正文紧跟触发器（中间不夹探针卡）
    assert 'id="srxOvHero"' in seg
    # r383：触发器搬进价带头（常驻标题行），不再单独占一行；
    # 正文仍是同一块，触发器在正文内部而非之前。
    assert 'id="srxOvHero"' in seg and 'id="srxOvBody"' in seg
    assert 'id="srxProbe"' not in seg
    for inner in ('id="srxBand"', 'id="srxBrief"', 'id="srxCapbar"', 'id="srxKpis"'):
        assert inner in seg, "%s 必须在概览体内" % inner


def test_mobile_and_desktop_overview_share_one_state():
    """窄屏移动栏「概览」与标题行按钮必须同状态，不得各存一套开关。"""
    src = _src()
    assert "show-overview" not in src
    assert "srx-ov-collapsed" in src
    i0 = src.index("function srxToggleOverview(")
    seg = src[i0:i0 + 700]
    assert "'#srxMobilebar [data-mobile=\"overview\"]'" in seg, "移动栏状态未同步"
    assert "hb.textContent=on?'收起概览':'展开概览'" in seg


def test_fold_trigger_text_matches_action():
    """按钮文案必须反映动作结果，不能永远写着「概览」。"""
    src = _src()
    assert "hb.textContent=on?'收起概览':'展开概览'" in src
    assert "aria-expanded" in src


# ---------- 配置：chip 兄弟关系 ----------

def test_config_status_chips_are_siblings():
    """「全部收齐」曾嵌在「无需重启」内部：点收齐会冒泡打开重启中心。"""
    src = _src()
    i0 = src.index('<span class="cc-chips">')
    i1 = src.index("</span>\n  </span>\n </div>", i0)
    seg = src[i0:i1]
    # 三个 chip 各自闭合，重启 chip 内不得再包收齐
    assert 'id="cfgRestartTxt">无需重启</span></span>' in seg
    assert seg.count('id="cfgFoldAll"') == 1
    nest = seg[seg.index('id="cfgChromeRestart"'):seg.index('id="cfgFoldAll"')]
    assert "<span id=\"cfgRestartTxt\">无需重启</span>" in nest
    assert "cfgFoldAll()" not in nest, "收齐按钮仍嵌在重启 chip 内"


def test_fold_all_covers_three_fold_kinds():
    src = _src()
    i0 = src.index("function cfgFoldAll(")
    # 按函数体截取（曾写死 900 字符，新增一类折叠就会把尾部挤出窗口），
    # 窗口要覆盖到函数结束。
    seg = src[i0:src.index("\nfunction applyFolds(", i0)]
    for sel in (".grouplab[data-sec]", ".rline[data-rk]", ".chcard[data-ch]"):
        assert sel in seg, sel
    assert "saveFold()" in seg


def test_radar_kline_hover_shares_the_same_tooltip_path():
    """K 线悬停必须走与折线同一条 tooltip 定位（PCHART.placeTipAxis），
    且按桶序号反查——类别轴没有连续时间可插值。

    三图浮窗此前四种行为并存：航线钉顶部、关注折线钉顶部但与雷达横向
    方向相反、关注 K 线跟指针、雷达两轴都跟指针（实测同一 fy 下雷达浮窗
    top 63→260 随指针滑动）。统一到 placeTipAxis 后横向跟十字线并翻边、
    纵向恒在顶部带，三图手感一致。"""
    src = _src()
    i0 = src.index("function spMonHover(")
    i1 = src.index("(function(){", i0)
    seg = src[i0:i1]
    assert "if(gg.kline){" in seg, "缺 K 线分支"
    assert "gg.candles" in seg and "开 ¥" in seg and "收 ¥" in seg
    assert seg.count("PCHART.placeTipAxis(") == 2, "折线与 K 线应共用轴向定位"


# ---------- 三处走势必须视觉同构（不只是共用内核） ----------

def test_three_charts_share_visual_architecture():
    """同一产品里三条走势必须长得一样：同一高度、同一双行刻度、同一
    面积填充、同一主系列线宽。只共用坐标算法而各画各的皮，是「内核统一
    但视觉没统一」——正是用户实报「特价雷达和航班走势明显不对」。"""
    src = _src()
    # 1) 高度统一为同一条 clamp（原为 346 自适应 / 200 / 178 三种）
    assert "#montab-watch .ws-chartwrap{height:clamp(240px,max(38vh,28vw),360px)!important;min-height:160px!important}" in src
    assert "#montab-watch #wsChart{height:clamp(240px,max(38vh,28vw),360px)!important}" in src
    assert "#spMonChart{display:block;height:clamp(240px,max(38vh,28vw),360px);cursor:crosshair;outline:none}" in src
    # 2) 两条附属走势都申请双行刻度（时刻 + 日期）
    assert "xKind:'time',band:W>=560?22:6,axisRows:2" in src      # 关注
    assert "xKind:'time',axisRows:2,band:8" in src                # 雷达
    # 3) 雷达主角线要有面积填充（与航线主系列同一语言）
    # 按函数体取，不按固定字数：曾写 +9000，本轮给「数据不足」分支补画布空态后
    # 折线绘制段被推出 9000 字以外，门禁表现为「规则消失」而源码里一直在。
    i0 = src.index("function spMonDraw(")
    i1 = src.index(chr(10) + "function ", i0 + 10)
    seg = src[i0:i1]
    assert "PCHART.area(" in seg, "雷达主角线缺面积填充"
    # 4) 主系列线宽同档 2.2
    assert "width:low||sel?2.2:1.2" in seg


def test_axis_day_label_not_repeated_on_every_tick():
    """双行刻度里日期只在新的一天出现：三个刻度都写 10-26 是噪声。"""
    src = _src()
    i0 = src.index("const _dayOf=t=>")
    seg = src[i0:i0 + 700]
    assert "let _prevDay=''" in seg
    assert "showDay=day!==_prevDay" in seg


def test_no_font_size_below_the_smallest_scale_step():
    """字号阶最小档是 10px（只给数字单位/极小标注）。

    9px 曾是 43 处，读作「字体断层」；26px 主数字与 22px 档并存也是
    同屏两把尺子。两者都不得回潮。16px 是 iOS 输入框防缩放的必要值，
    不属于字号阶，允许保留。7/8px 仅允许出现在固定尺寸的图形徽标内
    （24px 方块/17px 圆点里的单字），因为它们不是可读文本而是图形。
    """
    import re
    src = _src()
    assert "font-size:9px" not in src, "出现 9px 这一错误档"
    assert "font-size:26px" not in src, "主数字出现第二把尺子（应与 22px 同档）"
    # 逐条检查 <10px 的位置：必须带 mark/p 这类图形徽标的上下文
    for m in re.finditer(r"font-size:([1-8])px", src):
        ctx = src[max(0, m.start() - 220):m.start()]
        assert (".mark{" in ctx or ".p{" in ctx or ".mark{" in ctx[-90:]
                or "chlink-auth" in ctx[-90:]), \
            "非图形徽标处出现 %spx 字号：…%s" % (m.group(1), ctx[-90:])


def test_pacing_panel_is_row_structured_not_inline_soup():
    """节流状态曾是 15 段内联 span 拼成一块灰底，字号 10/11/12 混排、
    颜色写死；渠道名/状态/证据/动作挤在同一行无法扫读。

    现在：台账头 + 渠道行（品牌·名称 | 状态胶囊 | 速览 | 动作）+ 量尺
    + 配额轨 + 复发账 + 干预按钮组 + 就地展开的溯源。状态用「色点 +
    文字胶囊」双承载，颜色走令牌不写死 hex。溯源必须可开合，且 10 秒
    自动刷新不得把它抹掉，也不得把键盘焦点丢掉。"""
    src = _src()
    for cls in ('.pace-row', '.pace-row .nm', '.pace .dot',
                '.pace-row .ev', '.pace-row .ac', '.pace-tools', '.pace-detail',
                '.pace-led', '.pace-stats', '.pace-rail', '.pace-rec'):
        assert cls in src, cls
    assert 'class="pace"' in src, "paceBox 容器应挂 .pace 结构类"
    i0 = src.index("async function loadPacing(")
    i1 = src.index("async function showTrace(")
    seg = src[i0:i1]
    assert 'class="pace-row"' in seg, "渠道未按行渲染"
    assert 'class="dot ' in seg, "状态未用色点承载"
    assert "PACE.detail&&!force" in seg, "刷新未保护溯源展开态"
    assert "_paceRestoreFocus()" in seg, "重建未恢复键盘焦点"
    assert "async function paceTrace(" in src, "溯源不可开合"
    assert 'id="paceDetail"' in src
    # 不得再用写死的状态色
    for hexv in ("#1a9e75", "#b07700"):
        assert hexv not in seg, "节流面板仍写死颜色 %s" % hexv


def test_three_charts_share_the_same_pointer_and_keyboard_contract():
    """三处走势的交互契约必须一致：同为 crosshair 光标、都可 Tab 聚焦、
    都能用 ←/→ 逐点读数。此前是 pointer / crosshair / auto 三种光标，
    雷达还完全没有键盘路径（键盘用户读不到走势）。"""
    src = _src()
    assert "#chart{cursor:crosshair}" in src
    assert "#wsChart{display:block;width:100%;height:100%;cursor:crosshair" in src
    assert "#spMonChart{display:block;height:clamp(240px,max(38vh,28vw),360px);cursor:crosshair" in src
    # 三个画布都可聚焦
    assert 'id="chart" tabindex="0"' in src
    assert 'id="wsChart" tabindex="0"' in src
    assert 'id="spMonChart" tabindex="0"' in src
    # 雷达具备键盘读点
    # 锚点用注释块而不是「spMonDraw 后 N 字符」：雷达的键盘绑定注册在
    # spMonDraw 之外的图表事件段，旧窗口能命中纯属巧合——2026-10-29 给
    # 图例加 3 行注释就把 'End' 挤出窗口，功能仍在却报红。
    assert "键盘读点（与航线/关注走势同律）" in src, "雷达键盘读点段落在位"
    i0 = src.index("c.addEventListener('keydown',function(e){\n  if(!SPMON.geo)return;")
    seg = src[i0:i0 + 1200]
    for k in ("'ArrowRight'", "'ArrowLeft'", "'Home'", "'End'"):
        assert k in seg, "雷达键盘缺 %s" % k
    assert "e.preventDefault()" in seg, "雷达键盘读点必须拦住默认滚动"


def test_three_charts_hover_is_coalesced_and_anchored():
    """三处走势的悬停必须：① 合帧 ② 复用底座位图 ③ 浮窗贴容器不乱飘。

    实测旧实现：关注走势 3.22ms/次（每次全量重算+重绘）→ 卡顿不跟手；
    浮窗横跳 left 252→611→1091；雷达浮窗 fixed 与容器坐标混用 →
    滚动时留在原地。现全部改为与航线走势同一条策略。"""
    src = _src()
    # 关注：rAF 合帧 + 位图底座
    assert "let _wsHovRaf=0,_wsHovX=null;" in src
    assert "_wsHovRaf=requestAnimationFrame" in src
    assert "ctx.drawImage(WS._base,0,0)" in src
    assert "function _wsSnapshot(c){" in src
    # 雷达浮窗贴容器（absolute，不是 fixed）
    i0 = src.index(".spmon-tip{")
    assert "position:absolute" in src[i0:i0 + 120]
    # 关注浮窗水平跟十字线、垂直固定
    assert "WS._base=null" in src, "数据变化未清底座缓存"
    # 航线走势（被当作标杆的那张）同样走位图底座：它曾是唯一还在
    # 每帧全量重绘的图（实测 3.2ms/帧，另两图 0.3~0.5ms）
    assert "let _CHBASE=null;" in src
    assert "_CHBASE=_wsSnapshot(c)" in src
    i0 = src.index("const _hovPaint=()=>{")
    seg = src[i0:i0 + 900]
    assert "ctx.drawImage(_CHBASE,0,0)" in seg, "航线走势悬停未复用底座"
    # 三处 mousemove 都必须只调度一次合帧绘制，不得直接调用整图函数
    for hov in ("$('chart').onmousemove", "_wsHovRaf=requestAnimationFrame",
                "_hovRaf=requestAnimationFrame"):
        assert hov in src, hov
    no_repaint = src[src.index("$('chart').onmousemove"):
                     src.index("$('chart').onmouseleave")]
    assert "chart();_hovPaint()" not in no_repaint, "航线走势 mousemove 仍在整图重绘"


def test_three_charts_share_tooltip_and_crosshair_metrics():
    """浮窗与十字线是三套度量：关注 11px/6-9、雷达 10px/6-8、航线画在
    canvas 里圆角 6 且死贴顶端不跟手；十字线两图是中性虚线、雷达是淡蓝
    实线。同一种读数动作看起来像三个产品。现统一为：浮窗 12px、padding
    6px 9px、圆角 8、深底白字；十字线中性墨虚线；航线浮窗水平贴十字线
    并翻边避让右缘。"""
    src = _src()
    # DOM 浮窗两种类名必须同度量
    for cls in (".ws-tip{", ".spmon-tip{"):
        i0 = src.index(cls)
        seg = src[i0:i0 + 420]
        assert "font-size:12px" in seg, "%s 字号未统一 12px" % cls
        assert "padding:6px 9px" in seg, "%s 内边距未统一" % cls
        assert "border-radius:8px" in seg, "%s 圆角未统一 8px" % cls
        assert "rgba(44,62,80,.93)" in seg, "%s 底色未统一深底" % cls
    # 雷达十字线：中性虚线（不再是淡蓝实线）
    i0 = src.index(".spmon-cross{")
    seg = src[i0:i0 + 400]
    assert "repeating-linear-gradient" in seg, "雷达十字线未改虚线"
    assert "background:var(--r-blue)" not in seg, "雷达十字线仍是实心蓝线"
    # 航线画布浮窗：不再是自己一套翻边算术，必须取 PCHART.placeAxis
    # 的返回值（另两张 DOM 浮窗经 placeTipAxis 走同一份算术）
    i0 = src.index("const _p=PCHART.placeAxis(c.offsetWidth,c.offsetHeight,w,bh,ax,4);")
    seg = src[i0:i0 + 120]
    assert "const bx=_p.l, by=_p.t;" in seg, "航线浮窗未取共用落位"
    # 只认函数名，不绑死参数列表：后续加了 rightEdge（可视右缘，窄档防溢出）
    # 与 scrollLeft 补偿，绑死签名会让这条守卫因无关演进假红。
    i0 = src.index("placeAxis(boxW,boxH,tw,th,localX,topY")
    seg = src[i0:i0 + 900]
    # 只钳位、不整块翻边：翻边会让浮窗在指针越过阈值时整体跳到另一侧
    # （实测 0.844→0.867 之间 left 999→829，跳 170px＝用户说的「乱飘」）
    # 只认「有右缘钳位」这个意图：实现后来引入 _re（= min(boxW, rightEdge)）
    # 以支持窄档可视右缘，公式从 boxW-tw-8 变成 _re-tw-8，绑死字面量会假红。
    assert re.search(r"Math\.min\(localX\+14,\s*(?:boxW|_re)-tw-8\)", seg),         "共用落位缺右缘钳位"
    assert "localX-tw-14" not in seg, "浮窗又整块翻边了（会瞬跳 170px）"
    i0 = src.index("ctx.roundRect(bx,by,w,bh,8)")
    assert i0 > 0, "航线浮窗圆角未统一 8px"
    # 三图注脚同档 12px（曾 10/12 混排）
    for cls in (".ws-chart-foot{", ".spmon-note{", "#chartcard #ringNote{"):
        i0 = src.index(cls)
        seg = src[i0:i0 + 200]
        assert "font-size:12px" in seg, "%s 注脚字号未统一 12px" % cls


def test_three_charts_share_legend_language():
    """雷达此前根本没有色块图例，只有一句纯文字注脚（「每线=一个出发
    日期 · 红=最低日 · 蓝=选中」），另两图是 `.mon-legend` 色块。同一种
    看图动作三种表达。现三处共用 `.mon-legend`，色块同为 16×3，字号
    同为 12px。"""
    src = _src()
    # 三处都挂 mon-legend（航线静态、关注渲染、雷达渲染）
    assert src.count('class="legend mon-legend"') >= 1
    assert 'class="ws-legend mon-legend"' in src
    assert 'class="legend mon-legend" id="spMonLegend"' in src
    # 雷达有真正的图例渲染函数并输出色块
    i0 = src.index("function spMonRenderLegend(")
    seg = src[i0:src.index(chr(10) + "}", i0)]
    assert "'<span><b style=\"background:'" in seg, "雷达图例未用色块"
    assert "'最低价日'" in seg and "'选中日'" in seg
    # 色块几何单一来源（inline-block 已并入该条规则，见
    # test_radar_legend_covers_every_drawn_series）
    assert ".mon-legend>span>b{display:inline-block;width:16px!important;height:3px!important" in src
    # 字号：三处同为 12（航线曾 13、雷达曾 11）
    i0 = src.index(".mon-legend{display:flex")
    assert "font-size:12px" in src[i0:i0 + 300]
    i0 = src.index("#chartcard .legend{")
    assert "font-size:12px" in src[i0:i0 + 120]
    # 注脚里的读法句必须保留（用户已熟悉的措辞）
    assert "每线=一个出发日期" in src
    assert "线尾圆点=最新采集价" in src


def test_chart_range_switch_drives_filter_and_redraw():
    """时间范围切换必须同时做两件事：① 按所选窗口过滤数据点；
    ② 重绘。只改按钮态不重绘 = 点了没反应；只重绘不过滤 = 换了范围
    图还一样（用户读作「范围切换无效」）。三张图都要成立。"""
    src = _src()
    # 雷达：range → cutoff → 过滤 → spMonDraw
    i0 = src.index("function spMonDraw(")
    seg = src[i0:i0 + 6000]
    assert "SPMON.range*24*3600*1000" in seg, "雷达未按 range 算窗口"
    assert "p.t>=cutoff" in seg, "雷达未按窗口过滤数据点"
    i0 = src.index("function spMonSetRange(")
    assert "spMonDraw(" in src[i0:i0 + 400], "雷达切范围未重绘"
    # 关注：range → 窗口过滤 → wsDrawChart
    i0 = src.index("function wsChartData(")
    seg = src[i0:i0 + 2500]
    assert "WS.range" in seg and ("864e5" in seg or "86400000" in seg), \
        "关注未按 range 算窗口"
    i0 = src.index("function wsSetRange(")
    assert "wsDrawChart(" in src[i0:i0 + 500] or "wsRenderAll(" in src[i0:i0 + 500], \
        "关注切范围未重绘"
    # 航线：range 驱动 TREND_LONG / loadTrend，并重绘 chart()
    i0 = src.index("function setRange(")
    seg = src[i0:i0 + 700]
    assert "chart()" in seg, "航线切范围未重绘"


def test_three_charts_redraw_on_mode_switch():
    """K线/折线切换必须真的重绘画布。三处切换入口不同（setMode /
    data-wsmode / data-spmmode），都必须在切完后调各自的绘制函数，
    否则按钮态变了图没变——用户读作「点了没反应」。"""
    src = _src()
    # 航线 setMode → chart()
    i0 = src.index("function setMode(")
    seg = src[i0:i0 + 500]
    assert "chart()" in seg, "航线切模式未重绘"
    # 关注 wsSetMode → wsDrawChart
    i0 = src.index("function wsSetMode(")
    seg = src[i0:i0 + 600]
    assert "wsDrawChart()" in seg or "wsRenderAll()" in seg, "关注切模式未重绘"
    # 雷达 spMonSetMode → spMonDraw
    i0 = src.index("function spMonSetMode(")
    seg = src[i0:i0 + 500]
    assert "spMonDraw(" in seg, "雷达切模式未重绘"


def test_three_charts_share_range_control_language():
    """时间范围/模式控件曾是三套形制：航线软蓝胶囊、关注「文字+下划线」
    （后写 !important 覆盖把软蓝底换成了白底+投影）、雷达下划线 tab。
    现三处都继承 `.mon-range` 单源：26px 高、圆角 8、11px/600、软蓝选中底、
    零投影。"""
    src = _src()
    # 单一来源规则存在且是软蓝胶囊
    i0 = src.index(".mon-range button,.rngchip{")
    seg = src[i0:i0 + 320]
    assert "height:26px!important" in seg
    assert "border-radius:8px!important" in seg
    assert "font-size:11px!important" in seg
    assert "background:var(--r-blue-soft)!important" in src[i0:i0 + 520]
    # 关注与雷达容器都挂 mon-range
    assert 'id="wsRanges" role="group"' in src and 'mon-range' in src[
        src.index('<div class="ws-ranges mon-range" id="wsRanges"'):][:60]
    assert 'class="spmon-range mon-range" id="spMonRange"' in src
    assert 'class="spmon-mode mon-range" id="spMonMode"' in src
    # 不得再有「白底+投影」或「下划线」的选中态覆盖
    assert "ws-ranges button.on{background:var(--r-surface)!important" not in src
    assert "box-shadow:inset 0 -2px 0 var(--r-blue)!important}" not in src[
        src.index("#montab-watch .ws-ranges"):][:600]
    assert "spmon-tools button.on{color:var(--r-blue);box-shadow:inset 0 -2px 0" not in src


def test_button_radius_uses_token_not_self_invented_values():
    """按钮类圆角必须走 `--r3`。实测踩过：`.srx-mbtn` 同一选择器被声明
    三次（5px / 5px / 7px），最终生效的 7px 与同屏 `.srx-btn` 的 9px
    不一致——同一行的按钮一个圆一个尖。"""
    src = _src()
    i0 = src.index("#searchview .srx-mbtn{")
    seg = src[i0:i0 + 240]
    assert "border-radius:var(--r3)" in seg, seg
    # 最终覆盖也必须是令牌，不能写死像素
    i0 = src.index("#searchview .srx-mbtn{border:0!important")
    seg2 = src[i0:i0 + 160]
    assert "border-radius:var(--r3)!important" in seg2, seg2
    # 同族不得再有写死 5/6/7px 的 mbtn 规则
    assert "srx-mbtn{height:26px;padding:0 9px;border:1px solid var(--line2);border-radius:5px" not in src


def test_radar_day_cell_has_visible_hover():
    """雷达日期格是可点选的 button，但一条 `!important` 规则把背景与
    边框全清了，基础规则里的 hover 背景被吃掉——悬停时毫无变化，
    cursor 是唯一线索。补底边线 hover，与 low/sel 同族。"""
    src = _src()
    i0 = src.index(".spmon-day:hover{border-bottom-color:var(--r-hair-2)!important}")
    assert i0 > 0, "雷达日期格悬停无可见反馈"
    # 清理规则仍在（说明我们是叠加而不是删掉了去围栏设计）
    i1 = src.index(".spmon-day{background:transparent!important")
    assert i1 > 0


def test_modal_action_buttons_join_secondary_family():
    """弹层动作按钮（复制状态串/应用文本框/存当前快照）曾是
    11px/400 描边透明底，而同页次级按钮已是 12px/600 浅面底无边框——
    最该像按钮的位置反而最不像按钮。"""
    src = _src()
    i0 = src.index("#searchview .srx-dacts button{")
    seg = src[i0:i0 + 320]
    assert "font-size:12px" in seg and "font-weight:600" in seg, seg
    assert "border-radius:var(--r3)" in seg
    assert "border:0" in seg and "background:var(--r-surface-2)" in seg


def test_three_charts_crosshair_uses_same_token_and_dash():
    """十字线必须同令牌同节距。雷达曾用 `--r-ink-3` + 4/8 节距，
    另两图是 `--mut` + 3/3：浅色下 5a6c7d vs 647080、深色下 7f92a6
    vs 8b99a9，同屏两条光标深浅不同、虚线段长短也不同。"""
    src = _src()
    assert "cssv('--mut');ctx.globalAlpha=.5;ctx.setLineDash([3,3])" in src
    i0 = src.index(".spmon-cross{")
    seg = src[i0:i0 + 600]
    assert "var(--mut) 0 3px,transparent 3px 6px" in seg, seg
    assert "var(--r-ink-3) 0 4px" not in seg, "雷达十字线仍用另一令牌/节距"


def test_pacing_stat_numbers_share_one_ink_color():
    """指标格里的数字必须同一种主色。空值态曾把整格改成弱色
    （`--r-ink-3`），于是同一行里一个 16px 深字、一个 16px 浅字，
    读作两种不同层级的信息；实际是同一类指标，只是没有样本。"""
    src = _src()
    i0 = src.index(".pace-stat.na b{")
    seg = src[i0:i0 + 120]
    assert "var(--r-ink)" in seg, "空值格未回到主色"
    assert "var(--r-ink-3)" not in seg, "空值格仍整格降级"
    # 正常格也是主色
    i0 = src.index(".pace-stat b{")
    assert "color:var(--r-ink)" in src[i0:i0 + 220]


def test_three_charts_share_tooltip_wrap_width():
    """浮窗换行规则必须一致：都允许折行、都限 270px。雷达曾是
    `white-space:nowrap` + `max-width:100vw`，航线曾用整张画布宽度，
    两者都会把一条读数拉成横贯全屏的长条，而关注浮窗是窄块——
    同一种读数卡三种形状。"""
    src = _src()
    # DOM 两处：限 270 且允许折行
    assert "max-width:270px" in src
    i0 = src.index(".spmon-tip{")
    seg = src[i0:i0 + 420]
    # 只看 CSS 声明段：规则后面紧跟的注释里会提到旧写法，不能算命中
    decl = seg.split("*/")[0] if "*/" in seg[:seg.find("}") + 1] else seg[:seg.find("}") + 1]
    assert "white-space:nowrap" not in decl, "雷达浮窗仍强制单行"
    assert "max-width:min(270px,calc(100vw - 16px))" in seg, seg
    # 航线画布浮窗：可用宽度上限也是 270
    assert "const avail=Math.max(Math.min(c.offsetWidth-8,270),80);" in src


def test_font_weight_scale_is_four_steps():
    """字重必须只有四档 400/500/600/700。

    实测踩过两轮：`650`（51 处，与 600 只差 50）、`800`（8 处，价格数字
    用的第五档）——都属"同一层级编了两个号"，肉眼分不出来，却让
    排版看起来忽轻忽重。"""
    src = _src()
    for bad in ("650", "750", "800", "900"):
        assert "font-weight:" + bad not in src, "%s 字重档复活" % bad
    # 四档都在用，不是被删空
    for w in ("400", "500", "600", "700"):
        assert "font-weight:" + w in src, w


def test_header_jump_links_keep_touch_affordance():
    """「查看明细 ▸ / 走势 ▸」迁到卡头动作区后，四条既有可点性要求
    必须跟着走：hover 下划线、≥36 触控高、::after 命中区外扩、词缀单形
    ▸。旧实现靠内联 padding 撑高，换到 flex 卡头后若照搬会撑高卡头
    或让命中区溢出。"""
    src = _src()
    i0 = src.index(".uhead .uact2 a{")
    seg = src[i0:i0 + 420]
    assert "min-height:36px" in seg
    assert "display:inline-flex" in seg
    assert ".uhead .uact2 a::after{content:'';position:absolute" in src
    assert ".uhead .uact2 a:hover{text-decoration:underline}" in src
    # 词缀单形：查看明细/走势 都只带 ▸
    assert "查看明细 ▸" in src and "走势 ▸" in src
    assert "查看明细 ▾" not in src


def test_health_legend_matches_its_cells():
    """健康时间线的图例必须与它解释的格子同形。格是 6×15 竖条，
    图例却沿用走势图的 18×4 横线——同一个词在图例和图上长得不一样。"""
    src = _src()
    assert 'class="legend hlegend"' in src
    i0 = src.index(".legend.hlegend b{")
    seg = src[i0:i0 + 200]
    assert "width:6px" in seg and "height:15px" in seg, seg
    # 格子本体也是 15px 高
    i0 = src.index(".hc{width:6px;height:15px")
    assert i0 > 0


def test_clear_filter_buttons_join_secondary_family():
    """「清除筛选」两处曾是虚线框（11px / 10px），而同屏次级按钮是
    12px/600 软面底——虚线在扁平语言里只该表示「空位/占位」，不该
    表示可点动作。两处都归入次级按钮族。"""
    src = _src()
    for sel, head in ((".cfgw-reset{", ".cfgw-reset{height:30px"),
                      ("#searchview .srx-wreset{", "#searchview .srx-wreset{height:28px")):
        i0 = src.index(sel)
        seg = src[i0:i0 + 300]
        assert "font-size:12px" in seg, sel
        assert "font-weight:600" in seg, sel
        assert "border-radius:var(--r3)" in seg, sel
        assert "border:0" in seg, sel
        assert "dashed" not in seg, "%s 仍用虚线框" % sel
        assert "background:var(--r-surface-2)" in seg, sel


def test_load_more_button_belongs_to_secondary_family():
    """「加载更多」曾是虚线框 11px/400 + 另一条 !important 把圆角清零，
    而同页 `.srx-btn` 是 12px/600/圆角 9 软面底——同一屏两种次级按钮。
    现归入同一族。"""
    src = _src()
    i0 = src.index("#searchview .srx-more-rows{display:block")
    seg = src[i0:i0 + 420]
    assert "font-size:12px" in seg and "font-weight:600" in seg
    assert "border-radius:var(--r3)" in seg
    assert "border:0" in seg and "dashed" not in seg
    assert "background:var(--r-surface-2)" in seg
    # 那条把圆角清零的 !important 必须消失
    assert "srx-more-rows{background:transparent!important;box-shadow:none!important;border-radius:0!important}" not in src


def test_config_fold_all_covers_user_cards():
    """「全部收齐」曾只覆盖 分区/航线/渠道 三类，漏掉同样走 `_setFold`
    折叠的用户卡头（`toggleUser`）——点了之后仍有一张卡敞着，看起来
    像没生效。现在用户卡也一并收齐，且手风琴状态只同步一次。"""
    src = _src()
    i0 = src.index("function cfgFoldAll(){")
    i1 = src.index("\nfunction applyFolds(", i0)
    seg = src[i0:i1]           # 取整个函数体，不用固定字符窗
    assert ".uhead2[data-u]" in seg, "用户卡头未纳入收齐"
    assert "_setFold(h,[body],true)" in seg
    assert "setOpenUser(-1)" in seg, "手风琴状态未复位"
    # 不得在 forEach 里反复写 localStorage
    assert "_ufold" in seg
    loop = seg[seg.index(".uhead2[data-u]"):seg.index("saveFold();")]
    assert "setOpenUser" not in loop.split("if(_ufold)")[0], \
        "循环体内重复调用 setOpenUser（每次都写 localStorage）"
    # r412：曾只收「当前可见分区」，切到别的 tab 仍各自敞着——用户实报
    # 「各个 tab 展开状态没有办法一键全部收齐」。必须遍历全部分区。
    assert ".find(p=>p.style.display!=='none')" not in seg, \
        "全部收齐又退回「只收当前可见分区」"
    assert "const panels=[...document.querySelectorAll('.cfpanel')]" in seg
    assert "panels.forEach(panel=>{" in seg


def test_three_charts_share_empty_state():
    """空态曾三套：航线 14px、关注 11px、雷达左对齐块且无标题档。
    现统一为居中、标题 13px 深色、说明 12px 弱色。"""
    src = _src()
    i0 = src.index(".chart-empty{")
    seg = src[i0:i0 + 300]
    assert "align-items:center" in seg and "font-size:13px" in seg
    assert "font-size:12px" in src[i0:i0 + 420], "航线说明未统一 12px"
    i0 = src.index(" .ws-empty{")
    seg = src[i0:i0 + 300]
    assert "align-items:center" in seg and "font-size:12px" in seg
    # 13px 深色标题档：不再钉死整串（本轮给 <b> 补显式 600 字重，
    # <b> 默认 bolder 会算成 700，与四档约定不符）。
    assert ".ws-empty b{color:var(--tx);font-size:13px;font-weight:600}" in src
    i0 = src.index(".spmon-empty{display:flex")
    seg = src[i0:i0 + 300]
    assert "align-items:center" in seg and "text-align:center" in seg
    assert "font-size:12px" in seg
    assert ".spmon-empty b{color:var(--r-ink);font-size:13px;font-weight:600}" in src


def test_three_charts_share_summary_typography():
    """汇总条数字/标签曾是两档：雷达 18px/800 + 10px 全大写 + .08em 字距，
    关注 KPI 22px/600 + 12px。中文大写与字距纯属噪声，且同一种「关键数字」
    在两张图里字号不同。现雷达对齐关注档（字重随全站收敛到 600 档）。"""
    src = _src()
    i0 = src.index(".spmon-sum b{")
    seg = src[i0:i0 + 200]
    assert "font-size:22px" in seg and "font-weight:600" in seg, seg
    i0 = src.index(".spmon-sum .k{")
    seg = src[i0:i0 + 200]
    assert "font-size:12px" in seg
    assert "text-transform:none" in seg, "中文标签不应大写化"
    assert "letter-spacing:0" in seg, "中文标签不应加字距"


def test_radar_legend_merges_same_day_entries():
    """最低日与选中日同一天时，图例曾并排画两个同日期色块，读作两条
    不同系列。现合并为一条。"""
    src = _src()
    # 锚点按函数体取（函数签名带 series 参数，钉死 "(){" 会假红）
    i0 = src.index("function spMonRenderLegend(")
    seg = src[i0:src.index(chr(10) + "}", i0)]
    assert "low&&low===sel" in seg, "同日未合并"
    assert "'最低日 · 选中'" in seg


def test_pacing_summary_has_metric_cells():
    """汇总区曾是 4 行同字号同灰度的正文，「实发」与「每分钟上限」看起来
    一样重要。现为指标格（16px 等宽数字 + 11px 标签，发丝竖线分隔）+
    细则行；指标格不得回到纯文本行堆叠。"""
    src = _src()
    for cls in (".pace-stats{", ".pace-stat b{", ".pace-stat span{"):
        assert cls in src, cls
    i0 = src.index("async function loadPacing(")
    i1 = src.index("async function showTrace(")
    seg = src[i0:i1]
    assert 'class="pace-stats"' in seg, "汇总未走指标格结构"
    assert "'本轮覆盖率'" in seg, "覆盖率指标丢失"
    # 指标数字 16px、标签 11px
    i0 = src.index(".pace-stat b{")
    assert "font-size:16px" in src[i0:i0 + 220]
    i0 = src.index(".pace-stat span{")
    assert "font-size:11px" in src[i0:i0 + 120]


def test_pacing_trace_renders_inside_its_own_row():
    """溯源必须紧贴被点的渠道行。旧实现把详情渲染在「预热/自检」工具行
    之后，点第二行却在面板底部很远才出现，读作「点了没反应」；同一行
    右侧的开合钮才是唯一开关，详情内不得再放第二个收起按钮抢焦点。"""
    src = _src()
    i0 = src.index("async function loadPacing(")
    i1 = src.index("async function showTrace(")
    seg = src[i0:i1]
    # 详情块与渠道行在同一个 map 里拼装，因此它必然直接跟在对应行后
    assert "'<div class=\"pace-detail\" id=\"paceDetail\">'" in seg
    assert "}).join('');" in seg
    detail_at = seg.index("class=\"pace-detail\" id=\"paceDetail\"")
    row_at = seg.index("'<div class=\"pace-row\"")
    assert detail_at < row_at, "详情必须先于行尾部拼装（紧跟该行）"
    assert "+pre" in seg, "详情未拼在行后"
    # 详情内不再有第二个收起控件
    tail = seg[detail_at:]
    assert "paceTrace(null)" not in tail.split("}).join('');")[0], \
        "详情块内仍有第二个收起入口"
    # 面板字号只允许 12（正文）/16（量尺数字）两档，外加 11px 的标签；
    # 13px 曾与 14px 只差 1px，属噪声档已合并；14px 与健康卡块标题
    # （11/600）不同族，本版已并入 11px 小节标题，不再单独成档。
    # 按「下一段 section 注释」截取节流面板 CSS 块：曾硬编码某个 media
    # 查询字面量，断点一改就 ValueError（锚点比被测内容脆）。
    _p0 = src.index(".pace{display:flex")
    _nxt = src.find("/* ===== r374 按钮族收口", _p0)
    panel = src[_p0:(_nxt if _nxt > 0 else _p0 + 6000)]
    for line in panel.splitlines():
        sizes = set(re.findall(r"font-size:(\d+)px", line))
        if not sizes:
            continue
        if (".pace-dsub" in line or ".pace-tline.head" in line
                or ".pace-detail .pace-dhint" in line or ".pace-sec" in line
                or ".pace-fact .k" in line or ".pace-legend" in line):
            assert sizes <= {"11", "12"}, line
        elif ".pace-stat b{" in line or ".pace-now b{" in line:
            # 量尺数字走全站既有 KPI 数字档 16px，不另造新阶
            assert sizes <= {"16"}, line
        elif ".pace-stat b i{" in line or ".pace-stat span{" in line:
            # 单位/标签是次要信息，允许 11px
            assert sizes <= {"11"}, line
        else:
            assert sizes <= {"11", "12", "16"}, "节流面板字号未收敛：%s" % line.strip()

# ---------- CSS 语法完整性：选择器不得被脚本吃掉 ----------

def test_no_css_rule_lost_its_selector():
    """规则体不得直接以 `{` 开头，也不得在 `{` 前只留空白。

    曾有批处理脚本按「选择器 + 前瞻」做正则替换，把
    `.ws-previewbar .ws-btn{...}` 改成了 `.ws-previewbar {...}`，
    选择器尾部连同 `,` 一起被吞：样式整体失效，但语法仍是合法 CSS，
    任何「字符串存在性」断言都照绿。这里按规则形状兜底。
    """
    src = _src()
    style = src[src.index("<style>"):src.index("</style>")]
    bad = []
    for no, ln in enumerate(style.splitlines(), 1):
        s = ln.rstrip()
        if not s or s.lstrip().startswith(("@", "/*", "*")) or "{" not in s:
            continue
        pre = s[:s.rfind("{")]
        if pre and pre[-1] in " \t":
            bad.append((no, s.strip()[:70]))
    assert not bad, "CSS 规则选择器尾部被吞：%s" % bad[:5]


def test_config_field_groups_share_the_same_left_edge():
    """配置页同卡内两组字段的标签列必须同左缘。

    `.cfgfieldset` 曾带着 `padding:14px 16px` 与 14px 圆角、与主卡同底色，
    同一张卡里「推送行为」组标签落在 349、「官方特价机票」组落在 365
    （1440 实测）。用户反复报的「配置页表头和内容不对齐」就是这 16px。
    """
    src = _src()
    i = src.index("#cfgview .cfgfieldset{")
    seg = src[i:i + 260]
    assert "background:transparent!important" in seg, "分组又画了独立表面（卡中卡）"
    assert "padding:0!important" in seg, "分组又起了横向内边距，标签列会错位"
    assert "border-radius:0!important" in seg


def test_three_charts_share_one_crosshair_dash():
    """三图十字线必须同色同节距：曾经航线 4/4、关注 3/3、雷达 CSS 3/3，
    同屏两图光标疏密不同，读作两套系统。"""
    src = _src()
    assert src.count("ctx.setLineDash([3,3])") >= 3, "画布十字线节距未统一 3/3"
    # 十字线不得再用 4/4（4/4 还用于目标线：两者节距刻意不同，按行区分）
    for line in src.splitlines():
        if "HPTS.T" in line or "info.T)" in line:
            assert "setLineDash([4,4])" not in line, line.strip()
    # 雷达 DOM 十字线与画布同节距
    i = src.index(".spmon-cross{")
    seg = src[i:i + 700]
    assert "var(--mut) 0 3px,transparent 3px 6px" in seg, "雷达十字线节距未统一 3/3"


def test_pacing_panel_has_its_own_surface_layer():
    """节流面板必须自成一档软面：内部块全透明时，整段读作一段长文。

    用户原话「节流面板一点质感都没有」。实测修复前 `#paceBox` 与
    同页所有子块背景都是 rgba(0,0,0,0)，只有量尺格子是白片；
    加软面后层次为「主卡(白) → 面板(--r-surface-2) → 指标格(白)」。
    """
    src = _src()
    i = src.index(".pace{display:flex")
    seg = src[i:i + 400]
    assert "background:var(--r-surface-2)" in seg, "节流面板又变透明了"
    assert "border-radius:var(--r2)" in seg
    assert "padding:12px 14px" in seg


def test_three_chart_canvases_share_one_focus_ring():
    """三图画布的键盘焦点环必须同形（inset 2px）。

    实测：航线走了全站按钮那条外扩环、关注是 inset、雷达根本没有任何
    焦点环（Tab 到画布后看不出焦点在哪）。画布贴边，外扩环会被相邻卡裁掉，
    所以画布单独成组用 inset，不与按钮共用。
    """
    src = _src()
    assert ("#chart:focus-visible,#wsChart:focus-visible,#spMonChart:focus-visible{"
            in src), "三图画布未共用一条焦点环"
    i = src.index("#chart:focus-visible,#wsChart:focus-visible,#spMonChart:focus-visible{")
    seg = src[i:i + 220]
    assert "inset 0 0 0 2px var(--blue)" in seg, "画布焦点环不是 inset"
    # 每一处针对 #chart 的焦点环都必须是 inset（基础层与扁平层各一条）
    for idx, line in enumerate(src.splitlines()):
        if "#chart:focus-visible" in line and "kpi.clk:focus-visible" in line:
            nxt = src.splitlines()[idx:idx + 4]
            joined = "\n".join(nxt)
            assert "inset 0 0 0 2px var(--blue)" in joined, (
                "第 %d 行的 #chart 焦点环不是 inset：%s" % (idx + 1, line.strip()))


def test_modal_focus_handoff_is_keyboard_only():
    """弹层只在键盘操作时把焦点移给关闭钮。

    程序化 `el.focus()` 在 Chrome 里同样命中 `:focus-visible`，于是
    鼠标打开「推送记录」时关闭钮全程亮一圈蓝环（实测 box-shadow
    `0 0 0 2px rgb(11,98,214)` 直到关闭），读作「莫名其妙的方块」。
    """
    src = _src()
    assert "addEventListener('keydown',e=>{_LASTKBD=true;},true)" in src
    assert "addEventListener('pointerdown',e=>{_LASTKBD=false;},true)" in src
    i = src.index("const _fv=()=>{if(!_m.classList.contains('on'))return;")
    seg = src[i:i + 420]
    assert "if(!_LASTKBD)return;" in seg, "鼠标打开时仍会抢焦点"
    assert "$('pvClose')" in seg, "键盘打开时未移交焦点"


def test_radar_crosshair_follows_pointer_not_the_sample():
    """雷达折线十字线必须跟指针 x，不能吸附到采样点。

    雷达一个出发日一天只有几次采集，吸附时十字线整段停在同一个 x：
    实测指针 25/45/65/85% 四处，十字线恒为 48/626/626/1204（三个采样点），
    而航线图是精确跟随。用户读作「特价雷达悬浮不跟手」。
    读数仍取最近实测点（这是对的），只有光标位置要连续。
    """
    src = _src()
    i = src.index("const best=PCHART.pick(gg,gg.series,mx,my);")
    seg = src[i:i + 700]
    assert "cross.style.left=Math.round(c.offsetLeft+mx)" in seg, \
        "雷达折线十字线又吸附到采样点了"
    assert "cross.style.left=Math.round(c.offsetLeft+gg.X(p.t))" not in seg


def test_pacing_section_label_never_wraps_vertically():
    """节流小节名必须是不可压缩的实体盒。

    裸文本节点在 flex 里会被 `.pace-sub` 挤成两字宽：390 实测「逐渠道」
    断成「逐渠 / 道」两行（高 33px、副标题只剩 148px）。名字包 `<b>`
    并 `flex:none;white-space:nowrap`，副标题让位换行。
    """
    src = _src()
    for label in ("逐渠道", "反复出现"):
        assert '<div class="pace-sec"><b>%s</b>' % label in src, \
            "「%s」又变回裸文本节点（窄屏会断成竖排）" % label
    i = src.index(".pace-sec>")
    seg = src[i:i + 200]
    assert "flex:none;white-space:nowrap" in seg, "小节名缺 nowrap"
    # 副标题必须能自己收缩，否则会把名字挤扁
    j = src.index(".pace-sec .pace-sub{")
    assert "min-width:0" in src[j:j + 200], "副标题缺 min-width:0"


def test_link_shaped_buttons_keep_a_hover_signal():
    """文字链接形态的按钮必须有 hover 下划线。

    登录行按钮被做成「无边框无底色」的文字链接（`#loginRows .lgcard .btn2`
    覆盖成透明底 + 蓝字），但只有 :focus-visible 给了下划线，缺 hover。
    实测 hover 前后 backgroundColor/borderColor/color/box-shadow/transform/
    filter/opacity/textDecoration 八项零变化 —— 读作「这个按钮点不动」。
    """
    src = _src()
    assert "#loginRows .lgcard .btn2:hover{" in src, "链接形态按钮缺 hover 信号"
    i = src.index("#loginRows .lgcard .btn2:hover{")
    seg = src[i:i + 260]
    assert "text-decoration:underline!important" in seg, "hover 不是下划线信号"
    assert "text-underline-offset:3px" in seg, "下划线偏移应与 focus 态同档"


def test_bold_runs_never_exceed_the_four_step_scale():
    """`<b>` 必须显式声明 font-weight，否则默认 bolder 会把 600 算成 900。

    实测：节流小节名、关注台路由价格（¥1381/¥1489）、图例航班号（MU541）
    在父级 600 上全部渲染成 **font-weight:900**，超出全站四档
    （400/500/600/700）——用户说的「连字体都阶段了」。
    凡是靠 `<b>`/`<strong>` 承载数字或标签的规则，都要写死 600。
    """
    src = _src()
    for needle in (".pace-sec>b{flex:none;white-space:nowrap;font-weight:600}",
                   ".ws-rt-bot b{font-family:var(--num);font-size:13px;font-weight:600;",
                   ".ws-lg b{font-family:var(--num);font-size:10px;font-weight:600;"):
        assert needle in src, needle
    # 四档之外不允许出现字重声明
    for bad in ("font-weight:900", "font-weight:800", "font-weight:650", "font-weight:550"):
        assert bad not in src, "出现超四档字重：%s" % bad


def test_one_number_tier_for_every_amount_in_the_ui():
    """金额只有一个字号族：大数字 22、次数字 18、密集行值 16。

    2026-10-29 实测（1440/390/320 三档渲染读数）此前同一语义「当前价」
    同时出现 15/17/19/20/24 五种字号：
    `.kpi .num` 24、`.ws-kpi .v b` 20、`.srx-price b` 19、`.ss-price` 19、
    `td.price` 15、`.spmon-lowdate b` 20。用户说的「字体都阶段了」即此。
    本门禁把三个令牌钉死，并禁止消费点绕开令牌写裸 px。
    """
    src = _src()
    lg = re.search(r"--price-lg:(\d+)px", src)
    md = re.search(r"--price-md:(\d+)px", src)
    sm = re.search(r"--price-sm:(\d+)px", src)
    assert lg and md and sm, "价格三档令牌必须有单源声明"
    assert (int(lg.group(1)), int(md.group(1)), int(sm.group(1))) == (22, 18, 16), (
        "价格三档应为 22/18/16，实测 %s/%s/%s" % (lg.group(1), md.group(1), sm.group(1)))
    # 主数字消费点必须走令牌，不再写死 clamp 或裸 px
    assert ".kpi .num{font-family:var(--num);font-size:var(--price-lg)" in src, \
        "首屏 KPI 主数字未走 --price-lg"
    assert ".ss-price{font-size:var(--price-md)" in src, "航线价格戳未走 --price-md"
    assert "clamp(24px,2.4vw,31px)" not in src, "KPI 主数字不得再用 clamp 造第四档字号"


def test_watch_panel_is_not_height_clamped():
    """tabpanel 只承载排版，尺寸由内容决定。

    `#montab-watch{height:26px}` 曾把 1625px 高的面板压成 26px：卡片照常
    溢出绘制，页脚却按 26px 排位，实测页脚浮在「关注航班」卡头之上
    （390 档页脚 y=394、面板内容 1625px）。同类钉死高度一律不许回到面板上。
    """
    src = _src()
    # 扫全部样式块：反例实际落在第二块（旧值在块 1 只做字号），只看第一块会漏。
    # 只认「面板元素本身」——`#montab-watch .ws-previewbar{height:30px}` 这类
    # 后代规则是合法控件高度，`{` 前必须没有选择器延续（无空格）。
    # 注释里引述反例不算。
    bad = []
    in_comment = False
    for block in re.findall(r"<style[^>]*>(.*?)</style>", src, re.S):
        for line in block.splitlines():
            s = line.strip()
            if in_comment:
                if "*/" in s:
                    in_comment = False
                continue
            if s.startswith("/*"):
                if "*/" not in s:
                    in_comment = True
                continue
            if re.match(r"#montab-[a-z]+\{[^}]*height:", s):
                bad.append(s[:70])
    assert not bad, "tabpanel 被钉死高度：%s" % bad[:3]


def test_overview_price_stamp_is_not_swallowed_by_label_tier():
    """概览关注行的价格戳必须留在金额档，不能被同容器小字规则吃掉。

    `.monwatch-main span{font-size:11px}` 是为状态/说明准备的，但
    `.ss-price` 也是 span 后代，实测被一起压到 11px（¥1381 只有 32px 宽），
    而同一个价格戳在关注焦点卡里是 18px —— 同语义两档字号。
    """
    src = _src()
    assert ".monwatch-main .ss-price{font-size:var(--price-md)" in src, \
        "概览卡价格戳未单独回到金额档，会被 .monwatch-main span 的 11px 吃掉"
    assert ".monwatch-main span{font-size:11px" in src, \
        "同容器状态/说明仍应是 11px 小字档"


def test_three_charts_share_one_legend_and_note_grammar():
    """三图图例同一套：同缝宽、说明不塞进图例、说明用同一个类。

    2026-10-29 实测（1440/390 双档）此前三图图例各自一套：
    - 缝宽：航线图 16px（`#chartcard .legend` 是 ID 选择器 (1,1,0)，
      压过 `.mon-legend` 的 (0,1,0)），另两图 12px；
    - 说明：#ringNote 写在 `.mon-legend` 内并 `flex-basis:100%`，把图例
      盒子从 27px 撑到 64px（390 档 134px），另两图图例恒 27px；
    - 类名：雷达用 `.spmon-note`、航线用裸 `.muted`、关注无可见说明。
    用户说的「三大走势图明显不对」首先是这类同一位置两套排版。
    """
    src = _src()
    # 缝宽：ID 选择器那处不得再写回 16px
    assert "#chartcard .legend{font-size:12px;gap:12px" in src, \
        "航线图例缝必须与另两图同档 12px（ID 选择器会压过 .mon-legend）"
    assert ".mon-legend{display:flex;gap:12px" in src, "三图共用图例缝必须是 12px"
    # 说明不得再写进图例容器
    assert 'class="chart-note" id="ringNote"' in src, "航线说明必须是图例之外的同名脚注"
    assert 'flex-basis:100%;font-size:11px;margin-top:2px' not in src, \
        "说明不得再用 flex-basis:100% 塞进图例"
    # 同一个脚注类，同一套字形
    assert 'class="spmon-note chart-note"' in src, "雷达说明必须并入 .chart-note"
    seg = src[src.index(".chart-note{"):]
    seg = seg[:seg.index("}") + 1]
    assert "font-size:12px" in seg and "margin-top:6px" in seg and "line-height:1.5" in seg, \
        "脚注字形必须与另两图同档：12px / margin-top 6px / line-height 1.5"


def test_chart_empty_state_shares_the_same_line_height():
    """三图空态同一行高：`.chart-empty` 曾缺 line-height，另两处是 1.6。"""
    src = _src()
    i = src.index(".chart-empty{")
    seg = src[i:src.index("}", i) + 1]
    assert "line-height:1.6" in seg, "航线空态行高必须与 .ws-empty/.spmon-empty 同为 1.6"


def test_three_range_controls_share_one_chip_gap():
    """三图档位/模式切换控件是同一个控件：组内缝必须同档。

    2026-10-29 实测：同样的 chip（11px/600、8px 圆角、26px 高），航线图
    用 `.mdgrp{gap:normal}` → 相邻 chip 实测间距 **0px**（连体按钮），
    关注/雷达用 `.mon-range{gap:2px}`（分段按钮）——同一种切换动作两种形态。
    """
    src = _src()
    assert ".mdgrp{display:inline-flex;align-items:center;white-space:nowrap;gap:2px}" in src, \
        "航线图档位组必须与另两图同缝 2px"
    assert "gap:2px" in src[src.index(".mon-range{"):src.index(".mon-range{") + 120], \
        "另两图的 .mon-range 缝宽是这条契约的另一半"


def test_kline_tooltip_uses_the_shared_placement_not_a_flip():
    """浮窗落位只有一份算术：K 线分支不得自带左右翻边。

    2026-10-29 实测：`wsKlineHover` 里 `if(left+tw>wrap.width-6) left=px-tw-12`
    让浮窗越过阈值后整块从右侧跳到左侧——75%→85% 时 left 1028→807
    （倒退 221px），而同一时刻折线分支是 1010→1127 单调递增。K线浮窗
    体宽 270（折线 158），越界更早、跳得更频繁，即用户说的「悬浮窗乱飘」。
    """
    src = _src()
    i = src.index("function wsKlineHover(")
    seg = src[i:src.index("\nfunction wsSetMode(", i)]
    assert "PCHART.placeTipAxis(" in seg, "K线浮窗必须走三图共用落位"
    # 只扫代码行：注释里会引述这条旧实现当反例，按整段子串匹配会把
    # 注释一起判红（与本文件 tabpanel 门禁同一坑）。
    code = []
    in_block = False
    for line in seg.splitlines():
        s = line.strip()
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if s.startswith("//"):
            continue
        code.append(s)
    body = "\n".join(code)
    assert "left=px-tw-12" not in body, "K线浮窗不得自带左右翻边（会整块跳）"
    assert "tip.style.left=" not in body, "K线浮窗不得自行写 left（绕开 placeAxis）"


def test_all_three_charts_expose_hover_readings_to_screen_readers():
    """三图读数都要能被读屏拿到。

    DOM 浮窗天然可达（#wsTip 有 role=status aria-live）；但航线是画布内绘、
    雷达的浮窗带 aria-hidden="true"——两者悬停时读屏读不到任何数字。修法：
    雷达去掉 aria-hidden 改同款 live region；航线补 sr-only live region，
    并把同一条读数同步写进去（离开时清空，防残留）。
    """
    src = _src()
    assert 'id="spMonTip" class="spmon-tip" role="status" aria-live="polite"' in src, \
        "雷达浮窗必须是 live region（aria-hidden 曾让读屏读不到）"
    assert 'id="trendTipLive" role="status" aria-live="polite"' in src, \
        "航线画布内绘浮窗需要 sr-only live region"
    assert "$('trendTipLive')" in src and "_lv.textContent=_t" in src, \
        "航线读数必须同步进 live region"
    assert "const _lv=$('trendTipLive');if(_lv)_lv.textContent=''" in src, \
        "航线离开画布时必须清空 live region（防残留旧读数）"


def test_three_chart_empty_states_share_one_structure():
    """三图空态同一结构：`<b>标题 13px/600</b>` + `<span>说明 12px</span>`，缝 6px。

    2026-10-29 实测：关注是两段式，航线「加载中」那句是**单段纯文本**、
    没有标题层；三处标题的 `<b>` 都没有显式 font-weight，浏览器默认
    `bolder` 在父级 400 上算成 **700**（与「标题 600、最强 700」的四档约定不符）。
    """
    src = _src()
    assert ".chart-empty b{font-size:13px;font-weight:600;color:var(--tx)}" in src
    assert ".ws-empty b{color:var(--tx);font-size:13px;font-weight:600}" in src
    assert ".spmon-empty b{color:var(--r-ink);font-size:13px;font-weight:600}" in src
    # 航线「加载中」必须是两段式，不能再是一整句纯文本
    assert "'<b>正在加载 '+TREND_LAB[CR.range]+' 走势…</b><span>" in src, \
        "航线加载态必须是 <b>标题 + <span>说明 两段式"
    assert "'<b>暂无走势数据</b><span>" in src, "航线空态标题必须是 <b>"


def test_trace_detail_reads_like_a_section_not_a_repeat():
    """溯源展开块三条版面契约。

    2026-10-29 实测（1440/390）：
    1. 标题写「携程 · 最近尝试与干预」，而行内「携程」就在上方 2px ——
       390 档三行内渠道名出现两次，读作重复；
    2. 表头「入口/动作」走数据行的 `--r-ink-2`（判读主列更重），同一条
       规则也命中表头，一排表头出现两种颜色（ink-3 与 ink-2 并存）；
    3. 窄档表头 `display:none`，内容直接接在小标题后，间距实测 0px。
    """
    src = _src()
    assert "'<div class=\"pace-dh\"><b>最近尝试与干预</b>" in src, \
        "溯源标题不得重复渠道名（行内已有）"
    assert ".pace-tline.head .p,.pace-tline.head .t,.pace-tline.head .st,.pace-tline.head .n{color:var(--r-ink-3)}" in src, \
        "表头各列必须同一档弱色"
    i = src.index(".pace-dsub{display:flex")
    seg = src[i:src.index("}", i) + 1]
    assert "margin:8px 0 6px" in seg, "小标题到内容留 6px（窄档无表头时不能贴死）"


def test_pacing_does_not_repeat_the_same_sentence_on_every_row():
    """演示模式的全渠道同一句证据只写一次，不逐行重复。

    2026-10-29 实测：结论行已写「演示数据 · 无真实采集样本…」，而 5 个渠道
    行又各写一遍「无真实样本」+「合成样本 · 不参与成功率」——同一句话占 10 行。
    390 档行高因此 80px（内容只有一行），面板高 961px。
    信息不丢：结论行承担「合成 / 未实测」，行内 e1 给短标记，不落「—」
    （破折号在本面板专指零样本）。
    """
    src = _src()
    assert "if(!ev&&_demoAll&&_pthDemo)ev='无真实样本';" not in src, \
        "行内不再逐行写「无真实样本」（结论行已交代）"
    assert "if(!ev&&_demoAll&&_pthDemo)ev='合成 · 未实测';" in src, \
        "演示行 e1 需要短标记，不能落到破折号（那专指零样本）"
    # _qbit 那句必须保留：这半栏是「量到了什么」，演示数字与实测读数
    # 长得一样，不写就会被当成真实百分比引用（r425 门禁守同一件事）。
    # 去重只针对 e1 的「无真实样本」。
    i = src.index("const _qbit=_maskSynth")
    seg = src[i:i + 260]
    assert "合成样本 · 不参与成功率" in seg, "_qbit 必须保留「不参与成功率」定性说明"


def test_pacing_ledger_readout_and_section_headers_stay_single_line():
    """台账读数与四个小节标题必须单行。

    2026-10-29 实测（390/320）：
    - `.pace-now` 纵排时左侧四个 fact 挤到 267px，右侧只剩 54px，
      「0/0」与「实发 / 计划」各占一行（36px），台账头 78px；
    - 「逐渠道」副标题被「刷新 · 时间」挤到 152px、折成两行（33px），
      而同组另三处都是单行 17px；
    - 「干预」是裸文本节点（没包 `<b>`），被 flex 压成竖排，320 档该行 33px。
    """
    src = _src()
    i = src.index(".pace-now{display:flex")
    seg = src[i:src.index("}", i) + 1]
    assert "align-items:baseline" in seg and "white-space:nowrap" in seg, \
        "台账读数必须横排单行"
    i = src.index(".pace-sec .pace-sub{")
    seg = src[i:src.index("}", i) + 1]
    # 剥注释再断言：这段里带着说明注释，注释文本同样含 nowrap 字样，
    # 不剥的话删掉真实声明门禁仍绿（本文件 tabpanel 门禁踩过同一坑）。
    seg_code = re.sub(r"/\*.*?\*/", "", seg, flags=re.S)
    assert "white-space:nowrap" in seg_code and "text-overflow:ellipsis" in seg_code, \
        "小节副标题必须单行截断（全文进 title）"
    assert '<div class="pace-sec"><b>干预</b>' in src, \
        "「干预」必须包 <b>，裸文本会被 flex 压成竖排"


def test_pacing_metric_cells_use_hairlines_not_nested_cards():
    """指标格不得自成一张带边的白卡（卡中卡）。

    2026-10-29 实测：面板底是 `--r-surface-2` 浅灰，而 `.pace-stat` 是
    `--r-surface` 纯白 + `box-shadow: 0 0 0 1px var(--r-hair)` —— 在浅灰面板
    里又嵌了一张带描边的白卡，同时违反「无卡中卡」与「无装饰性描边」。
    本文件 `test_pacing_summary_has_metric_cells` 的注释写的就是
    「发丝竖线分隔」，实现与它不符。
    窄档 2 列时第 3 格是第二行首格，`first-child` 管不到，需按行去掉竖线。
    """
    src = _src()
    # 锚点只用选择器名，不绑死后面的第一句声明：否则有人加一条 padding
    # 就让门禁抛 ValueError（不是红灯，是崩），比不设门禁更糟。
    i = src.index(".pace-stat{")
    seg = src[i:src.index("}", src.index(":first-child", i)) + 1]
    seg_code = re.sub(r"/\*.*?\*/", "", seg, flags=re.S)
    assert "background:var(--r-surface)" not in seg_code, "指标格不得自带白底"
    assert "box-shadow" not in seg_code, "指标格不得自带描边"
    assert "border-left:1px solid var(--r-hair)" in seg_code, "指标格之间用发丝竖线"
    assert ".pace-stat:first-child{border-left:0}" in src, "首格无竖线"
    assert ".pace-stat:nth-child(odd){border-left:0}" in src, "窄档 2 列时每行首格无竖线"


def test_every_bold_run_declares_an_explicit_weight():
    """承载数字/标签的 `<b>` 必须显式写 font-weight，否则默认 bolder→900。

    浏览器对 `<b>` 的默认 `font-weight:bolder` 是相对计算：父级 600 → **900**，
    直接冲出全站四档（400/500/600/700）。2026-10-29 全站普查（渲染值，8 视图）
    实测只剩特价日历的日期格价格 `button.spmon-day>b.p` 是 900（7 处），
    补 600 后全站 4017 个文本元素字重 100% 落在四档。
    同类历史案例：`.pace-sec>b`、`.ws-rt-bot b`、`.ws-lg b`、三图空态标题。
    """
    src = _src()
    assert ".spmon-day .p{font-family:var(--num);font-size:16px;line-height:1.1;font-weight:600}" in src, \
        "特价日历价格格必须显式 600（<b> 默认 bolder 会算成 900）"
    # 已修的同类位置不得回退：只查「该选择器块内是否声明了 600」，
    # 不绑死整串——这些块尾部还会追加 color/letter-spacing，整串匹配
    # 会因无关改动而假红（本轮实测踩过一次）。
    for sel in (".pace-sec>b", ".ws-rt-bot b", ".ws-lg b", ".chart-empty b"):
        i = src.index(sel + "{")
        block = src[i:src.index("}", i) + 1]
        assert "font-weight:600" in block, " 承载数字的 <b> 缺显式 600：%s" % sel
    # 四档之外不允许出现字重声明
    for bad in ("font-weight:900", "font-weight:800", "font-weight:650", "font-weight:550"):
        assert bad not in src, "出现超四档字重：%s" % bad


def test_table_cell_padding_lands_on_the_spacing_scale():
    """表格单元格内边距必须落在 4/6/8/12/16/24 间距阶上。

    全站间距普查（1440 渲染值，8 视图）里 `th,td` 曾是单一最大偏离源：
    `padding:7px 10px` 两值都不在阶上，825 个 td × 4 边 ≈ 全部偏离值的 60%。
    改 8px 12px 后偏离占比 13.0% → 4.1%。

    口径：只读这条基础规则本身。≤900 的卡片布局由
    `#ftable tbody tr[data-k]>td{padding:0}` 接管，紧凑档另有 6px 8px，
    两者都是阶上值，不必在此重复断言。
    """
    src = _src()
    scale = {0, 4, 6, 8, 12, 16, 24}
    i = src.index("th,td{padding:")
    block = re.sub(r"/\*.*?\*/", "", src[i:src.index("}", i) + 1], flags=re.S)
    m = re.search(r"padding:([^;}]+)", block)
    assert m, "th,td 必须有 padding 声明"
    vals = [v for v in m.group(1).split() if v.endswith("px")]
    nums = {float(v[:-2]) for v in vals}
    assert nums <= scale, "单元格内边距出现阶外值：%s（阶：4/6/8/12/16/24）" % sorted(nums - scale)
    # 紧凑档必须与舒适档保持可辨的档差，否则密度切换在表格上失去意义
    tight = src[src.index("html[data-density=\"compact\"] th,"):]
    tight = tight[:tight.index("}") + 1]
    assert "padding:6px 8px" in tight, "紧凑档单元格内边距应保持 6px 8px"


def test_stylesheet_has_no_orphan_declaration_blocks():
    """样式表里不允许出现「孤立声明块」——`}` 后直接跟 `{`，选择器被吞掉。

    2026-10-29 实测：`.ws-chart-h{padding-top:9px}{height:25px;...}` 这条
    丢了 `.ws-ranges button` 选择器（HEAD 是正确的），浏览器整条规则作废，
    走势图档位按钮在 600px 以下悄悄失去尺寸——源码里看不出任何异常，
    只有渲染值对不上。这类损坏不会抛错、不会红任何已有门禁。
    """
    src = _src()
    styles = re.findall(r"<style[^>]*>(.*?)</style>", src, flags=re.S)
    assert styles, "页面必须包含样式块"
    for bi, css in enumerate(styles):
        nocmt = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        assert nocmt.count("{") == nocmt.count("}"), "样式块 %d 花括号不平衡" % bi
        orphan = re.search(r"\}\s*\{", nocmt)
        assert not orphan, (
            "样式块 %d 存在孤立声明块（选择器丢失）：...%s..."
            % (bi, nocmt[max(0, orphan.start() - 100):orphan.end() + 40].replace("\n", " ")))
        empty = re.search(r"@media[^{]*\{\s*\}", nocmt)
        assert not empty, "样式块 %d 存在空媒体查询：%s" % (bi, empty.group(0)[:60])


def test_small_status_pills_share_one_side_padding():
    """≤21px 的状态小胶囊族必须共用同一横向内边距。

    2026-10-29 实测：`.chsess` / `.ws-state` 是 6px，`.monwatch-state` /
    `.hslot` / `.hdiag-st` / `.srx-b` 是 7px，`.glip` 是 8px，
    `.lgtag` / `.chlink-auth` 是 5px —— 七种「pill 圆角 + 1px 描边 + ≤21px 高」
    的小状态标出现四种横向内边距，同屏读作四个不同控件。
    本轮统一到 6px（全族众数，且在 4/6/8 阶上）；1440/900/390 实测
    统一后高度不变、无裁切、无横向溢出。
    """
    src = _src()
    members = {
        ".monwatch-state": "height:21px",
        "html #healthcard .hslot": "height:18px",
        ".hdiag-st": "padding:1px",
        "#searchview .srx-b{font-size:11px": "height:20px",
        ".pace-row .glip": "height:20px",
        ".lgtag": "line-height:16px",
    }
    # 每个成员：在它自己的块里找到 padding 声明并比对横向值
    checks = [
        (".monwatch-state{", "0 6px"),
        ("#healthcard .hslot{", "0 6px"),
        (".hdiag-st{", "1px 6px"),
        (".pace-row .glip{display:inline-flex", "0 6px"),
        (".lgtag{", "0 6px"),
        (".chsess{", "0 6px"),
        (".ws-state{", "0 6px"),
    ]
    for sel, want in checks:
        try:
            i = src.index(sel)
        except ValueError:
            raise AssertionError("状态胶囊成员缺失：%s" % sel)
        block = re.sub(r"/\*.*?\*/", "", src[i:src.index("}", i) + 1], flags=re.S)
        m = re.search(r"padding:([^;}]+)", block)
        assert m, "%s 必须有 padding" % sel
        assert m.group(1).strip().startswith(want), \
            "%s 横向内边距应为 %s，实为 %s" % (sel, want, m.group(1).strip())
    # srx-b 的生效规则（后出现的那条）也要是 6px
    tail = src[src.index("#searchview .srx-b{font-size:11px;height:20px"):]
    head = re.sub(r"/\*.*?\*/", "", tail[:tail.index("}") + 1], flags=re.S)
    assert "padding:0 6px" in head, "srx-b 生效档应为 0 6px"
    # 三处 chrome tag 与基础 .tag 同一横向内边距 8px。
    # 锚点必须带行首前缀：裸 `.tag{` 会先命中 `.ws-rt-bot .tag{`（源码里更靠前）。
    tag_targets = (("\n .tag{", "基础 .tag"),
                   (".ws-rt-bot .tag{", "关注行内 tag"),
                   ("#searchview .srx-mchrome .tag{", "搜索 chrome tag"))
    for sel, label in tag_targets:
        i = src.index(sel)
        block = re.sub(r"/\*.*?\*/", "", src[i:src.index("}", i) + 1], flags=re.S)
        m = re.search(r"padding:([^;}]+)", block)
        assert m, "%s 必须有 padding" % sel
        # 简写里 `0 8px` 的首个分量不带单位，不能用「第二个 px 值」定位横向——
        # 取最后一个 px 分量才是横向值（`3px 8px` 与 `0 8px` 都成立）。
        vals = [v for v in m.group(1).split() if v.endswith("px")]
        assert vals and vals[-1] == "8px", \
            "%s 横向内边距应为 8px，实为 %s" % (sel, m.group(1).strip())


def test_tooltip_clamps_on_measured_width_not_a_stale_one():
    """浮窗落位必须按「测量后的最终宽度」钳位，不能用可能过期的 offsetWidth。

    实测（2026-10-29）：关注图浮窗内容在 158↔169px 之间交替，某一帧
    `offsetWidth` 读到 166，而最终渲染 169 —— 按 166 夹右缘会让右沿多出 3px。
    这类误差在多图共用同一份落位算术时最难查：公式对，只是入参过期。
    """
    src = _src()
    i = src.index("placeTipAxis(host,tip,cx,topY){")
    block = re.sub(r"/\*.*?\*/", "", src[i:src.index("tip.style.top", i) + 40], flags=re.S)
    assert "const tw=" in block, "placeTipAxis 必须先取宽度"
    # 只读 offsetWidth 会拿到过期值；必须叠加一次强制重排后的测量
    assert "getBoundingClientRect().width" in block, \
        "钳位宽度必须包含 getBoundingClientRect().width（强制同步重排后的最终宽度）"
    # 只认「走共用 placeAxis」这个意图，不绑死参数串：
    # 后来补横向滚动补偿（host.scrollLeft / scrollWidth）时改过入参，
    # 绑死整串会让「三图同一份算术」这条守卫因无关改动而假红。
    assert "PCHART.placeAxis(" in block, \
        "落位必须走共用的 placeAxis（三图同一份算术）"


def test_kline_requires_at_least_two_days_before_drawing():
    """日 K 少于 2 天时不得渲染蜡烛图，必须给空态说明。

    实测（2026-10-29）：雷达演示数据 21 个采集点全落在同一天，按日聚合后
    只有 1 根蜡烛——1220px 宽的画布上只出现一根细柱、两侧全空，读作
    「图表坏了」；同时 24 个指针位置给出同一个开收高低，悬停完全无效。
    数据没缺，缺的是第二天。此时应如实说明，而不是画一个看着像图表的空画布。
    """
    src = _src()
    i = src.index("if(SPMON.mode==='kline'){")
    block = src[i:src.index("const kd=PCHART.domain", i)]
    code = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    assert "candles.length<2" in code, "雷达 K 线缺「至少 2 天」守卫"
    assert "至少 2 天" in block, "空态文案要写明需要至少 2 天"
    # 空态必须是覆盖画布的居中块，不能只写脚注：实测只写脚注时 1220px×360px
    # 的画布只剩底部一行小字，比原来那根孤立蜡烛更像「页面坏了」。
    assert "getElementById('spMonKEmpty')" in code,         "K 线不足 2 天时要有居中空态节点（按 id 取用）"
    # 空态必须真的居中覆盖：只塞一行文字到滚动容器会沉到画布底部
    # 判意图（覆盖在画布上、跟随可视区）而不是钉实现：原钉 `position:absolute`，
    # 而 absolute 在 `overflow-x:auto` 的容器里会跟着内容横向滚出可视区——
    # 实测 320 档空态左缘 -9px（容器左缘 30、scrollLeft 39）。现用 sticky，
    # 横向滚到最右仍停在可视区且保持居中（实测 scrollLeft 0→39，空态 l/r 恒 30/311）。
    k = src.index(".spmon-kempty{")
    blk = src[k:src.index("}", k) + 1]
    # 必须绝对定位覆盖画布：sticky 在 flex 列里会落到画布**下方**
    # （实测 y=898 而画布底 874，变成多出一块灰板）。
    assert "position:absolute" in blk, "空态须绝对定位覆盖画布：%s" % blk[:120]
    assert "justify-content:center" in blk, "空态须水平居中"
    # 横向滚动补偿走共用落位函数（left 是内容坐标，滚动后会滑出可视区：
    # 320 档 scrollLeft=39 时实测左缘 -9px）。
    assert "function spMonPlaceEmpty(" in src, "缺空态落位函数"
    assert src.count("spMonPlaceEmpty(") >= 3, "两条空态分支都要走同一处算术"
    assert "(wrap.scrollLeft||0)+'px'" in src, "落位必须按 scrollLeft 补偿"
    # 同一屏不得重复同一句话：脚注与空态写同一句会被读两遍
    assert "if(note)note.textContent=''" in code, "空态已说明时脚注必须清空，避免同屏重复"
    # 关注图同一守卫
    j = src.index("function wsDrawKline")
    seg = src[j:j + 1400]
    assert "n<2" in re.sub(r"/\*.*?\*/", "", seg, flags=re.S), "关注图 K 线缺「至少 2 天」守卫"
    assert "至少 2 天" in seg, "关注图 K 线空态文案要写明需要至少 2 天"


def test_channel_icon_borders_are_one_depth():
    """两类渠道图标的单圈描边必须同深，否则同一行里一浅一深。

    2026-10-29 实测：`.bic-ota`（方形，透明底落在白卡上）用 .10、
    `.bic-air`（圆形，自带近白径向底）用 .13，深色主题 .16/.18。
    按 alpha 合成后与白底的亮度差是 23.1 vs 34.3——圆形 logo 明显更黑，
    读作「一个有边、一个没边」。统一 .12（深色 .17）：27.7 / 32.1，差 <5。
    注意真正生效的是后面带 `!important` 的性能覆盖层（只留单圈描边），
    改基类而不改它等于没改。
    """
    src = _src()
    m = re.search(r"\.bic-ota\{box-shadow:0 0 0 1px rgba\(15,23,42,\.(\d+)\)!important\}", src)
    assert m, "找不到 .bic-ota 的生效描边层"
    a_ota = m.group(1)
    m = re.search(r"\.bic-air\{box-shadow:0 0 0 1px rgba\(15,23,42,\.(\d+)\)!important\}", src)
    assert m, "找不到 .bic-air 的生效描边层"
    assert m.group(1) == a_ota, "两类渠道图标描边不同深：.ota=.%s vs .air=.%s" % (a_ota, m.group(1))
    # 深色主题同样
    d1 = re.search(r'html\[data-theme="dark"\] \.bic-ota\{box-shadow:0 0 0 1px rgba\(255,255,255,\.(\d+)\)!important\}', src)
    d2 = re.search(r'html\[data-theme="dark"\] \.bic-air\{box-shadow:0 0 0 1px rgba\(255,255,255,\.(\d+)\)!important\}', src)
    assert d1 and d2, "深色主题的图标描边层缺失"
    assert d1.group(1) == d2.group(1), "深色主题两类图标描边不同深"


def test_inline_channel_links_have_a_touch_sized_hit_area():
    """配置页里被降级为行内文字的渠道链接，热区要补到 36px。

    实测（2026-10-29，1440）：`.chband-specs .chlink` 被这段覆盖改成行内文字
    （`min-height:0!important;padding:0!important`），盒高只剩 15px，
    `elementFromPoint` 逐点探测可点范围上下各仅 8px/7px（共 16px）——
    远低于 36px 触屏地板。外观不该改，用伪元素补热区：
    实测补后 36px（上 18 / 下 17），盒高仍 15px，视觉零变化。
    """
    src = _src()
    i = src.index(".chband-specs .chlink{position:relative}")
    blk = src[i:i + 260]
    assert ".chband-specs .chlink::before" in blk, "行内渠道链接缺热区伪元素"
    code = re.sub(r"/\*.*?\*/", "", blk, flags=re.S)
    assert "height:36px" in code, "热区高度应为 36px（触屏地板）"
    assert "translateY(-50%)" in code, "热区要以链接中线为中心上下各伸展，避免只向上扩"
    # 不得靠加 padding/min-height 改外观：这段是「降级成行内文字」的设计
    seg = src[src.index(".chband-specs .chlink{"):]
    seg = re.sub(r"/\*.*?\*/", "", seg[:seg.index("}") + 1], flags=re.S)
    assert "min-height:0!important" in seg, "行内链接应保持 min-height:0（外观不变）"


def test_every_focusable_control_has_a_visible_focus_ring():
    """可交互元素聚焦后必须可见，且焦点环用同一个蓝（微信级扁平交互的底线）。

    2026-10-29 实测：真实键盘 Tab 遍历健康面板 22 个可交互元素，
    **焦点不可见 0%**，焦点环统一为 `rgb(11,98,214) 0 0 0 2px`（`--blue`，2px）。
    同轮发现节流面板 4 处焦点环用 `--r-blue`（另一套蓝，通道差 15、对比度差 2.4%），
    与其余 35 处不一致，已统一到 `--blue`（`--blue`:`--r-blue` 从 35:6 → 40:0）。

    测量陷阱：用 `el.focus()` 程序化聚焦测不出东西——它不触发 `:focus-visible`，
    会误报 45%「无焦点指示」。**必须用真实键盘 Tab**。

    合法例外（都不算「焦点不可见」）：
    - `outline:2px solid Highlight`：跟随系统高对比度主题，无障碍正确做法；
    - `outline:none` + `text-decoration:underline`：登录卡按钮的替代指示；
    - `outline:none` + 文字变色（`color:var(--red)`）：危险动作的替代指示；
    - `box-shadow:... , 0 0 0 4px var(--card)`：双环里的外圈白边，不是主环色。
    """
    src = _src()
    blues = set()
    idx = 0
    while True:
        i = src.find(":focus-visible", idx)
        if i < 0:
            break
        j = src.find("{", i)
        k = src.find("}", j)
        if j < 0 or k < 0 or k - j > 400:
            idx = i + 1
            continue
        code = re.sub(r"/\*.*?\*/", "", src[j + 1:k], flags=re.S)
        idx = k
        if "outline:none" in code:
            # 关掉 outline 的块必须给替代指示（阴影 / 下划线 / 文字变色）
            assert ("box-shadow" in code or "text-decoration" in code
                    or "color:var(--red)" in code),                 "focus-visible 关掉 outline 却没给替代指示：%s" % code[:80]
            continue
        if "solid Highlight" in code:
            continue          # 系统高对比度色，合法
        draws = ("outline:2px solid" in code or "0 0 0 2px" in code
                 or "inset 0 0 0 2px" in code)
        if not draws:
            continue
        # 取块内全部令牌：双环写法 `inset 0 0 0 2px var(--blue),0 0 0 4px var(--card)`
        # 里第一个 var() 之后还有外圈白边，只取第一个会误判成 var(--card)。
        toks = set(re.findall(r"var\(--[a-z0-9-]+\)", code))
        assert toks, "焦点环没有用颜色令牌：%s" % code[:80]
        assert toks & {"var(--blue)", "var(--red)"},             "焦点环未使用统一蓝（--blue / 危险动作 --red）：%s" % code[:80]
        blues |= (toks & {"var(--blue)", "var(--red)"})
    assert blues, "未找到任何绘制焦点环的 focus-visible 声明"
    assert blues <= {"var(--blue)", "var(--red)"},         "焦点环颜色应统一为 --blue，实为 %s" % sorted(blues)


def test_current_price_marker_is_the_same_size_in_all_charts():
    """「当前价」末点标记三图必须同尺寸。

    2026-10-29 实测：关注折线非聚焦用 r=2.4（直径 4.8px），雷达折线与
    关注 K 线都是 r=3.2（6.4px）——**面积差 78%**，同一个语义的标记在
    关注图明显小一圈，是用户所说「其他走势图看着不对」的来源之一。
    已统一 3.2（聚焦仍放大到 3.5）。

    注意不要与 `PCHART.line(...dot:1.6)` 混淆：那是**孤点**半径（只有单个
    采样点的段），语义不同，1.6 与顶点 1.7 并存不是缺陷。
    """
    src = _src()
    radii = {}

    def grab(fn, pat):
        i = src.find("function " + fn)
        assert i > 0, "找不到绘制函数 %s" % fn
        j = src.find("\nfunction ", i + 12)
        body = src[i:j if j > 0 else len(src)]
        m = re.search(pat, body)
        assert m, "%s 里找不到末点绘制" % fn
        return m

    m = grab("wsDrawChart", r"arc\(X\(lastP\.t\),Y\(lastP\.v\),(.{0,40}?),0,Math\.PI\*2\)")
    radii["关注折线"] = m.group(1)
    m = grab("wsDrawKline", r"arc\(xAt\(n-1\),Y\(last\.c\),([0-9.]+)")
    radii["关注K线"] = m.group(1)
    m = grab("spMonDraw", r"arc\(gx\(last\.t\),gy\(last\.p\),([0-9.]+)")
    radii["雷达"] = m.group(1)

    # 关注折线是 `focused?3.5:3.2` 形式，取非聚焦分支
    flat = {}
    for k, v in radii.items():
        if "?" in v:
            flat[k] = v.split(":")[-1].strip()
        else:
            flat[k] = v.strip()
    assert set(flat.values()) == {"3.2"}, "末点标记半径不一致：%s" % flat
    # 聚焦态放大值也必须一致（只有关注折线有聚焦分支）
    assert "focused?3.5:3.2" in src, "关注折线聚焦态应为 3.5"


def test_canvas_font_restore_matches_the_initial_font():
    """画布内 ctx.font 的「恢复值」必须与初始值同源，否则整张图字体漂移。

    2026-10-29 实测：`chartDraw` 初始写 `'11px ' + --num`（等宽数字字体），
    但最低价标签画完后恢复成 `'11px sans-serif'`（比例字体）——
    **这之后同一张画布上所有文字的字体都退化了**，上下部分字体不一致、
    数字宽度跳动，用户读作「字体都阶段了」。两处（折线 / K 线各一）已改为同源。

    判据：源码里不得出现 `ctx.font='11px sans-serif'` 这类「恢复成另一套字体」的写法
    （注释里引述旧值不算——先剥注释）。
    """
    src = _src()
    nocmt = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    nocmt = re.sub(r"^\s*//.*$", "", nocmt, flags=re.M)
    bad = re.findall(r"ctx\.font\s*=\s*'[^']*sans-serif['\"]", nocmt)
    assert not bad, "画布字体恢复写成 sans-serif（应为 '11px '+(cssv('--num')||…))：%s" % bad[:3]
    # 初始值与恢复值都要走 --num
    i = nocmt.find("const chartDraw=()=>{")
    assert i > 0, "找不到 chartDraw"
    head = nocmt[i:i + 400]
    assert "cssv('--num')" in head, "chartDraw 初始字体应走 --num 令牌"
    assert nocmt.count("ctx.font='11px '+(cssv('--num')||'sans-serif');") >= 2, \
        "两处最低价标签画完后的字体恢复应走 --num"


def test_calendar_cells_let_text_inherit_the_computed_color():
    """价格日历的日期/价格/差价必须继承格子的 color，不能写死灰或深墨。

    2026-10-29 实测（1440，8 视图，AA 普查）：
    - `.cd`/`.cx` 写死 `--r-ink-3`（灰），而低价日格子底是 `rgba(194,42,46,.51)`
      红 tint → 灰字压红底 **2.09:1**（AA 需 4.5），亮色主题 30 处不达标；
    - `.cp` 写死 `--r-ink`（深墨），而达标绿底格子 **3.7:1**。
    格子 color 是 JS 按 tint 精确算的（见 calgrid 渲染处注释），写死任何一档都会破坏它。

    另一条必须守的：`.cp.near`（擦边价）只能靠**同等特异度**的 ID 选择器覆盖，
    否则 `.calcell .cp.near{--warn-deep}`（注释注明双主题 4.66/4.72 过 AA）
    会被 `#calcard .calcell .cp` 整条压掉——实测 3 个擦边格确实被压成深墨。
    修后亮色 33 → **0** 处。
    """
    src = _src()
    for cls in ("cd", "cp", "cx"):
        m = re.search(r"#calcard \.calcell \.%s\{([^}]*)\}" % cls, src)
        assert m, "找不到 #calcard .calcell .%s 规则" % cls
        assert "color:inherit" in m.group(1), \
            ".%s 应继承格子 color（写死会破坏 JS 按 tint 算好的对比度）：%s" % (cls, m.group(1)[:60])
    assert "#calcard .calcell .cp.near{color:var(--warn-deep)}" in src, \
        "擦边价的 .near 必须用同等特异度声明，否则被 ID 选择器压掉"


def test_dark_theme_muted_text_clears_aa():
    """深色主题的 `--mut` 必须能对面板底色过 AA 4.5:1。

    2026-10-29 实测：`--mut:#7f92a6` 压在深色面板底（`#1a212a` / `#1f2b3c`）上
    只有 **4.37~4.47:1**，差一点点不过 AA——深色主题 28 处不达标（10~12px 的
    「行李未标」「时刻」「直飞」这类次级文字）。提亮 5 个色阶到 `#8497ab`
    （4.65 / 4.76）后深色不达标 **0 处**，亮色本来就 0 处。

    注意：PAGE 里深色 `--mut` 只有 `html[data-theme="dark"]` 一处；
    `webui.py` 文件里另有两处同值定义在 PAGE 之外（服务端/独立样式拷贝），
    改动时要一起改，否则不同入口取到不同值。
    """
    src = _src()
    i = src.index('html[data-theme="dark"]{')
    blk = src[i:i + 400]
    m = re.search(r"--mut:(#[0-9a-f]{6})", blk)
    assert m, "深色主题定义里找不到 --mut"
    assert m.group(1) == "#8497ab",         "深色 --mut 应为 #8497ab（对面板底 4.65/4.76 过 AA），实为 %s" % m.group(1)
    # 文件里所有深色 --mut 必须同值（不同入口不能取到不同值）
    import io as _io
    raw = _io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8", newline="").read()
    vals = set(re.findall(r"--mut:(#[0-9a-f]{6});--line:#1e2a3a", raw))
    assert vals == {"#8497ab"}, "深色 --mut 多处定义不同值：%s" % sorted(vals)


def test_clickable_status_pill_has_hover_feedback():
    """可点的状态胶囊（role=button）悬停必须有可见反馈，且 hover 态仍过 AA。

    2026-10-29 实测：`.pill.ok`「有人已达标」是 `role=button` + onclick +
    cursor:pointer 的真实可点元素，但 `.pill:hover{filter:none;background:…!important}`
    与 `.pill.ok{background:var(--okbg)!important}` **同为 (0,2,0)、后者更靠后**，
    把 hover 的灰底整条压掉——三个视图里悬停零变化。

    修法：补一条同特异度、更靠后的 `.pill.ok:hover`，**保持语义绿**（不改成中性灰），
    只把底色压深 12%。压 18% 会让 hover 态掉到 4.35:1 欠 AA，12% 为 4.75:1。
    """
    src = _src()
    i = src.find(".pill.ok{background:var(--okbg)!important")
    assert i > 0, "找不到 .pill.ok 的生效底规则"
    tail = src[i:]
    j = tail.find(".pill.ok:hover{")
    assert j > 0, "可点的状态胶囊没有 hover 反馈（会被 .pill.ok 的 !important 压掉）"
    blk = tail[j:tail.find("}", j) + 1]
    assert "background:" in blk and "color:var(--ok-txt)" in blk, \
        "hover 必须保留语义绿字色，不能退化成中性灰：%s" % blk[:90]
    m = re.search(r"var\(--okbg\)\s*(\d+)%", blk)
    assert m, "hover 底色应由 --okbg 与 --ok-txt 混合得到"
    pct = int(m.group(1))
    assert pct >= 85, \
        "hover 混合比例过深（--okbg %d%%）：压到 82%% 时对比度 4.35:1 欠 AA" % pct


def test_tooltip_placement_compensates_horizontal_scroll():
    """浮窗落位必须补偿容器的横向滚动偏移，否则窄档贴边会被裁掉。

    2026-10-29 实测（320）：雷达容器 `scrollWidth 320 / clientWidth 281`、
    **scrollLeft=39**。`left` 相对的是滚动内容起点，而 `cx-r.left` 量的是
    可视区偏移，两者差一个 scrollLeft——浮窗贴左时 left=26，容器可视左缘
    在 30，**被裁掉 4px**，读作「悬浮窗飘出图外」。右缘钳位同理要用
    scrollWidth（内容总宽）而不是 r.width（可视宽），否则滚到中段时
    浮窗永远贴不到最右端。修后 320/390 溢出 0 次、1440/768 无回退。
    """
    src = _src()
    i = src.index("placeTipAxis(host,tip,cx,topY){")
    blk = src[i:src.index("tip.style.top", i) + 40]
    code = re.sub(r"/\*.*?\*/", "", blk, flags=re.S)
    assert "host.scrollLeft" in code, "落位未补偿容器横向滚动偏移"
    assert "host.scrollWidth" in code, "右缘钳位应使用 scrollWidth（内容总宽）而非可视宽"
    assert "PCHART.placeAxis(" in code, "落位必须走共用的 placeAxis"


def test_every_pacing_section_title_carries_the_same_weight():
    """节流面板的每个小节标题都必须是 `<b>`（600 档），不能某个分支漏加。

    2026-10-29 实测（1440）：四个小节里「本轮节流」的标题没包 `<b>`，
    只有 400——而同组「逐渠道 / 反复出现 / 干预」都是 600，同一列标题里
    混进一个细体，读作「这一节不是标题」。另外「反复出现」在
    **有重复**与**无重复**两个分支里写法不一致（有重复那支也漏了 `<b>`），
    同一标题会随数据状态在两个字重间跳。

    判据：源码里每个 `class="pace-sec"` 后面必须紧跟 `<b>` 或 `<span class="pace-sub"`；
    实测四个标题（逐渠道 / 本轮节流 / 反复出现 / 干预）字重全部 600、字号 11px。
    """
    src = _src()
    bad = []
    for m in re.finditer(r'class="pace-sec"[^>]*>', src):
        after = src[m.end():m.end() + 60]
        if after.startswith("<b>") or after.startswith('<span class="pace-sub"'):
            continue
        bad.append(after[:40])
    assert not bad, "节流小节标题未包 <b>（会渲染成 400 细体）：%s" % bad
    # 四个标题都必须存在且带 <b>
    for t in ("逐渠道", "本轮节流", "反复出现", "干预"):
        assert "<b>%s</b>" % t in src, "小节标题「%s」缺少 <b> 包裹" % t


def test_visible_numeric_columns_use_tabular_mono():
    """数字列必须用等宽数字字体 + tabular-nums（纵向对齐）。

    2026-10-29 实测（1440，5 视图）：531 个「整格是数字」的单元格分 11 组，
    10 组是 `Cascadia Mono` + `tabular-nums`；唯一例外在雷达 `#spMonTable`
    ——它位于 `.sr-only`（读屏专用隐藏表），不可见，不算缺陷。

    判据只认「存在 tabular-nums 与 --num 令牌的单源定义」：
    **不要按选择器全等去找某个格子的字体声明**——`#ftable td.price` 自身只写
    `font-size`/`color`，等宽是从别的规则链继承来的，实测渲染色正确。
    """
    src = _src()
    assert "font-variant-numeric:tabular-nums" in src, "数字列缺少 tabular-nums"
    assert "--num:" in src, "缺少等宽数字字体令牌 --num"
    # 关键数字载体必须显式走 --num（这三处是实测确认的单源定义）
    for sel in (".ws-rc .v b", ".pace-stat b", ".calcell .cp"):
        i = src.find(sel + "{")
        assert i > 0, "找不到 %s" % sel
        blk = src[i:src.find("}", i) + 1]
        assert "var(--num)" in blk, "%s 未走 --num 令牌：%s" % (sel, blk[:70])


def test_all_three_tooltips_cap_their_width_and_shrink_to_fit():
    """三个浮窗都要「按内容收缩 + 限宽 270」，缺一样就会被压窄或拉成全屏长条。

    2026-10-29 实测：`.ws-tip` 与 `.spmon-tip` 都写了
    `width:max-content; max-width:270px`（雷达那版还叠了 `min(270px, calc(100vw-16px))`）；
    趋势图是画布内绘，用 `avail=Math.max(Math.min(c.offsetWidth-8,270),80)` 限同一档宽度。

    **`width:max-content` 是必需的防御**：`position:absolute` 的浮窗贴右缘时，
    若只给 `max-width` 不给 `max-content`，浏览器会按「可用宽」压缩它，
    实测出现过 **53×158** 这种被压扁的浮窗（r524）。
    """
    src = _src()
    for sel in (".ws-tip{", ".spmon-tip{"):
        i = src.find(sel)
        assert i > 0, "找不到 %s" % sel
        blk = src[i:src.find("}", i) + 1]
        assert "width:max-content" in blk, "%s 缺少 width:max-content（贴右缘会被压窄）" % sel
        assert "270px" in blk, "%s 未限制 270px 宽" % sel
    # 趋势图（画布内绘）用同一档 270 限宽
    assert "Math.min(c.offsetWidth-8,270)" in src, "航线画布浮窗未按 270px 限宽"


def test_pacing_panel_text_shares_one_line_height_tier():
    """节流面板内的文字行高只能有一档（1.5），不能混进 1.7。

    2026-10-29 实测：面板内 `.nm`/`.e1` 是 18px（1.5×12）、`.glip`/`.e2` 是 16.5px（1.5×11），
    唯独 `.pace-kv` 用 `line-height:1.7`（11px→**18.7px**）——同一面板三档行高，
    多出的 2.2px 还把「量尺图例 → 这一段」的视觉间距顶成 **9px**（阶上应为 8）。
    改 1.5 后该间距回到 8。

    注：`.pace-kv → .pace-sec` 用 Range 量仍是 13，但 `marginTop` 与 `boxGap`
    都是 12——那 1px 是 16.5 行高在 11px 字号下的亚像素舍入，不是真实间距。
    """
    src = _src()
    i = src.find(".pace-kv{")
    assert i > 0, "找不到 .pace-kv"
    blk = src[i:src.find("}", i) + 1]
    assert "line-height:1.5" in blk, \
        "节流面板行高应统一 1.5 档（1.7 会与同面板另两档混排）：%s" % blk[:80]


def test_pacing_subtitles_truncate_instead_of_wrapping():
    """节流面板的小节副标题：单行截断 + 全文进 title，不得折行。

    2026-10-29 实测（320/390/768/1440 四档，78 个文本块）：
    - 无「行数 ≥4」的块，无横向溢出容器（唯一 scrollWidth>clientWidth 的是
      `.pace-sub` 自身，那正是**省略号生效**的证据，不是溢出）；
    - `.pace-sub` 在 320 档只剩 78px（内容 175px），靠 `title` 兜底全文。

    为什么必须截断而不是折行：同组四个小节标题里若只有一行折成两行，
    行高从 17px 跳到 33px，读作「排版坏了」（390 实测过）。
    """
    src = _src()
    i = src.find(".pace-sec .pace-sub{")
    assert i > 0, "找不到 .pace-sub 规则"
    blk = src[i:src.find("}", i) + 1]
    code = re.sub(r"/\*.*?\*/", "", blk, flags=re.S)
    assert "white-space:nowrap" in code, "副标题不得折行"
    assert "text-overflow:ellipsis" in code, "副标题应省略号截断"
    assert "overflow:hidden" in code, "截断需要 overflow:hidden 才生效"
    assert "flex:1 1 auto" in code, "副标题应可收缩，否则会把整行撑开"
    # 截断必须配 title 兜底，否则信息真丢了
    assert 'class="pace-sub" title=' in src, "被截断的副标题必须带 title 全文"


def test_icon_stroke_widths_follow_the_three_tiers():
    """SVG 图标描边只有三档语义：动作图标 1.8 / 品牌图形 1.7 / 航线剪影 1。

    2026-10-29 实测（1440，6 视图，590 个可见 svg）：
    - **1.8px × 450**：`.ic` 一族（动作/导航/按钮图标）；
    - **1px × 135**：`bic-plane` 航司/机型**品牌剪影**（127 个，带完整 `--pl-a..--pl-e` 配色）
      与 `monroute-svg`/`monwatch-svg` 航线示意；
    - **1.7px × 3**：`.logo .ic`（品牌 logo，尺寸更大 17px，描边相应更细）。

    这三档不是漂移：图形越大描边越细（视觉重量恒定），品牌剪影本来就不该像线条图标。
    判据只钉「不得再冒出第四档」，不合并这三档。
    """
    src = _src()
    base = src.find(".ic{")
    assert base > 0, "找不到 .ic 基础规则"
    blk = src[base:src.find("}", base) + 1]
    assert "stroke-width:1.8" in blk, ".ic 基础描边应为 1.8"
    for bad in ("stroke-width:1.2", "stroke-width:1.5", "stroke-width:2.2", "stroke-width:1.6"):
        assert bad not in src, "出现第四档图标描边：%s" % bad


def test_color_legend_grammar_is_shared_across_charts():
    """三图的「配色图例」共用一套语法：12px / 色块 16×3 / 缝 12px / 上内边 8。

    2026-10-29 实测（320/390/768/1440 四档）：三图图例的 CSS 口径完全一致
    （fs 12px、columnGap 12px、padding-top 8px、色块 16×3 圆角 2）。

    **但高度不要求相等**：关注图 `#wsLegend` 是 48px、另两图 27px——因为关注图的
    第一个子元素 `.ws-lg-lab` 是「航线内 N 班 · 点击切换」的说明、第二个是
    **40px 高的可点选按钮**（在多条关注航班间切换），语义上它是「选择器 + 图例」
    的复合体，不是纯配色图例。把三者钉成等高会逼着要么删掉切换能力、要么给
    另两图塞无意义的高度。
    """
    src = _src()
    # 锚点要带行首与首条声明：裸 `.mon-legend{` 会先命中注释里引述的旧规则
    # （`.mon-legend{gap:12px}`），那段没有 font-size，会假红。
    i = src.find(".mon-legend{display:flex;")
    assert i > 0, "找不到 .mon-legend 共用图例规则"
    blk = src[i:src.find("}", i) + 1]
    for token in ("font-size:12px", "gap:12px", "padding:8px 2px 0"):
        assert token in blk, "共用图例缺 %s：%s" % (token, blk[:90])
    assert "width:16px!important;height:3px!important" in src, "图例色块应为 16×3"


def test_every_x_axis_generator_thins_its_labels():
    """四处 X 轴刻度生成都必须是「有上限/抽稀」的，不能全量输出。

    2026-10-29 实测四个生成器策略不一致：
    - 趋势折线 `length:nTick+1`（固定条数）；
    - 关注 K 线 `Math.ceil(n/(W<560?4:8))`（按宽度抽稀）；
    - 雷达折线 `[0,1,2,3]`（固定 4 条）；
    - **雷达 K 线曾是 `xTicks:candles.map(...)` 全量输出** —— 20 个交易日就有
      20 个「MM-DD」挤在轴带上，必然重叠、读不出日期。

    已统一为与关注 K 线同一套抽稀（`_n/(kg.pw<560?4:8)`，首尾必留）。
    判据只钉「不得再出现全量 map + 抽稀式必须存在」，不锁具体公式。
    """
    src = _src()
    assert "xTicks:candles.map((c,i)=>" not in src, \
        "雷达 K 线又退回全量输出刻度（交易日一多就重叠）"
    assert "Math.ceil(_n/(kg.pw<560?4:8))" in src, "雷达 K 线刻度缺抽稀"
    assert "Math.ceil(n/(W<560?4:8))" in src, "关注 K 线刻度缺抽稀"
    assert "length:nTick+1" in src, "趋势折线刻度缺固定条数上限"


def test_radar_chart_host_keeps_zero_horizontal_padding():
    """雷达画布容器必须保持横向 0 内边距——这不是漏改，是定宽画布的需求。

    2026-10-29 实测：三图画布在容器内的缩进是 趋势 10 / 关注 10 / **雷达 0**。
    看着像不一致，但雷达的画布宽度由 `c.style.width = W`（含横向滚动逻辑）
    **精确设定**，若容器再加 10px 横向 padding，`scrollWidth` 会从 1220→**1240**
    （390 档 320→**340**），凭空多出 20px 横向滚动条。
    趋势图画布宽度取 `c.offsetWidth`，天然吃掉 padding，所以它保留 10px 没问题。

    判据：不得给 `.spmon-chartwrap` 加横向 padding。
    """
    src = _src()
    i = src.find(".spmon-chartwrap{border:0!important;background:transparent!important;")
    assert i > 0, "找不到雷达容器覆盖规则"
    blk = src[i:src.find("}", i) + 1]
    assert "padding:4px 0 0!important" in blk, \
        "雷达容器横向内边距必须为 0（画布定宽，加 padding 会多出 20px 横向滚动）：%s" % blk[:90]


def test_three_charts_all_collapse_their_tooltip_after_touch():
    """三图在真实触摸下都必须能出读数、且最终收起（不许有残留浮窗）。

    2026-10-29 用 CDP 真实触摸事件实测（390 与 1440）：
    - 三次点按三个不同位置 → 三图都是 3/3 不同读数（点按读数是通的）；
    - 点到画布外 → 趋势/关注**立即**收起；雷达因 `pointerleave` 对触摸直接
      return（避免拖动时浮窗闪没），改由 `setTimeout(hideTip, 2600)` 收——
      实测 +0.5s/+2.0s 仍在、**+3.5s 已清空**。

    所以「雷达点外面没立刻消失」不是缺陷，是刻意的触摸保留；但不能没有兜底，
    否则会留一个永久残留的浮窗。判据要两条都在：立即收起的两图 + 有定时兜底的一图。
    """
    src = _src()
    # 雷达：触摸 pointerleave 直接 return 时，必须有定时器兜底
    i = src.find("c.addEventListener('pointerleave'")
    assert i > 0, "找不到雷达 pointerleave 处理"
    seg = src[i:i + 200]
    assert "pointerType==='touch'" in seg and "return" in seg, \
        "雷达触摸 pointerleave 应保留浮窗（拖动时不闪没）"
    assert "setTimeout(hideTip" in src, "雷达触摸必须有定时兜底收起，否则残留浮窗"
    # 趋势 / 关注：touchstart 映射到 hover，且存在清线路径
    assert "addEventListener('touchstart',_tchHover" in src, "趋势图缺触摸映射"
    assert "addEventListener('touchstart'" in src and "WS.pinned=true" in src, \
        "关注图缺触摸映射"


def test_every_chart_marks_the_hovered_point():
    """悬停读数时，被读到的那一点必须在画布上有记号，且三图同一个记号。

    2026-10-29 实测三图落点写法三种：
    - 航线：`arc(...,4.5,0,7)` 纯实心（无光圈，落在线上时与线糊成一段）；
    - 关注：`arc(...,3.2,...,Math.PI*2)` 实心 + 1.5px 卡色光圈；
    - **雷达：一个都不画** —— 悬停只有一条 DOM 十字线，数据点上没有任何
      变化。指针在移、图上没有东西跟着移，正是用户说的「雷达悬停不跟手」。

    现在统一走 `PCHART.hoverDot`（实心 4 + 1.5px 卡色光圈），三条折线路径
    都必须调用它；且不得再出现各自手写的落点 arc。
    """
    src = _src()
    assert "hoverDot(ctx,x,y,color){" in src, "缺共用的悬停落点绘制"
    blk = src[src.index("hoverDot(ctx,x,y,color){"):]
    blk = blk[:blk.index("ctx.restore();},") + 12]
    # 实心 4px + 卡色 1.5px 光圈：光圈是关键，纯实心落在同色线上会消失
    assert "arc(x,y,4,0,7)" in blk, blk
    assert "lineWidth=1.5" in blk and "cssv('--card')" in blk, blk
    # 三处折线路径都调用（航线 pd/pt、关注折线、雷达折线）
    assert src.count("PCHART.hoverDot(") >= 4, \
        "三图折线都要画落点，实测调用 %d 处" % src.count("PCHART.hoverDot(")
    # 不得再手写各图自己的落点半径
    for legacy in ("ctx.arc(pd[0],pd[1],4.5,0,7)",
                   "ctx.arc(pt[0],pt[1],4.5,0,7)",
                   "ctx.arc(info.X(best.t),info.Y(best.v),3.2,0,Math.PI*2)"):
        assert legacy not in src, "残留各图自写落点：%s" % legacy


def test_radar_hover_restores_its_base_bitmap():
    """雷达悬停要有一张底图：只贴图 + 一个落点，不重绘整幅。

    没有底图时只有两种结局——画布纹丝不动（无落点，读作不跟手），或每次
    移动都全量重绘 1220px 画布（读作卡顿）。另有第三个坑：收起浮窗时若不
    还原，落点会留在画布上，读作「停在了别的日期」。
    """
    src = _src()
    # 折线分支画完必须拍快照（K 线分支同样拍）
    assert src.count("SPMON.base=spMonSnapshot(c);") >= 2, \
        "折线与 K 线画完都要拍底图"
    assert "function spMonSnapshot(c){" in src, "缺雷达快照函数"
    # 数据变化时先作废旧快照，避免把上一份折线贴回来
    i = src.index("function spMonDraw(dateSeries,selDate,lowDate){")
    head = src[i:i + 900]
    assert "SPMON.base=null;" in head, "重绘前未作废旧底图"
    # 悬停时先贴底图再画落点；收起时还原
    i = src.index("const best=PCHART.pick(gg,gg.series,mx,my);")
    seg = src[i:i + 900]
    assert "spMonRestore();" in seg, "悬停未先贴回底图（会叠出上一帧残影）"
    assert "const hideTip=function(){" in src
    i = src.index("const hideTip=function(){")
    assert "spMonRestore()" in src[i:i + 220], "收起浮窗未还原底图（残留落点）"


def test_radar_tooltip_uses_the_shared_row_grammar():
    """雷达读数浮窗与关注走势同一套行文法，不再是两行自由文本。

    2026-10-29 实测（1440/390 同位置悬停）：
    - 关注：`<div class="tm">时刻</div>` + `<div class="tr">图标|色点|名称|价格</div>`
      + `<div class="tm">渠道 · 目标</div>`，3 行、高 69px、带 2 个品牌图标；
    - 雷达（改前）：`<b>日期</b> · ¥价<br>时刻 · 渠道 · 口径`——2 行、高 49px、
      **0 个图标**，而点位上的 `ch` 就是真实平台键（实测 ctrip/fliggy/tongcheng
      都有官方图标可用）。

    同一种读数卡在同屏并排出现两种形状，是用户说「雷达明显不对」的一部分。
    判据：雷达浮窗必须用 .tm/.tr 行文法，且渠道有图标就直接画。
    """
    src = _src()
    i = src.index("const best=PCHART.pick(gg,gg.series,mx,my);")
    seg = src[i:i + 2200]
    assert 'class="tm"' in seg, "雷达浮窗缺时刻行"
    assert 'class="tr"' in seg, "雷达浮窗缺图标·名称·价格行"
    assert "srxPlatIcon(p.ch)" in seg, "雷达浮窗渠道必须用官方图标（值就是平台键）"
    assert "'<br>'" not in seg, "雷达浮窗不得回到 <br> 自由文本"
    # 样式必须同构：.spmon-tip 作用域内补齐与 .ws-tip 同名的 .tm/.tr
    for sel in (".spmon-tip .tm{", ".spmon-tip .tr{", ".spmon-tip .tr b{"):
        assert sel in src, sel


def test_pacing_panel_same_font_size_has_one_line_height():
    """同一个字号在节流面板里只能有一个行高——否则读作「字体分档了」。

    2026-10-29 实测（1440 与 390 完全同结果，78 个文字节点）：
    改前 6 个组合里有两处同字号双行高：
    - 12px：按钮默认 `line-height:normal`（13 个按钮）× 正文 18px；
    - 11px：`.pace-now b i` / `.pace-stat b i` 继承 16px 父级的 1.2 比例
      算成 **13.2px**，而面板其余 11px 文本是 **16.5px**。
    两处都只改行高、不动盒高（按钮 height 已钉死 22/28px），实测节流面板
    总高 591→591、行高 44→44、按钮尺寸与横向溢出均零变化。

    判据：所有 `font-size:Npx` 的字号在面板内只能配套一种行高；
    三条规则必须把行高写成与同档一致的绝对值。
    """
    src = _src()
    for sel, want in ((".pace-sec :is(a,button){", "line-height:18px"),
                      (".pace-tools .g :is(button,a){", "line-height:18px"),
                      (".pace-now b i{", "line-height:16.5px"),
                      (".pace-stat b i{", "line-height:16.5px")):
        i = src.find(sel)
        assert i > 0, "找不到 %s" % sel
        blk = src[i:src.find("}", i) + 1]
        assert want in blk, "%s 缺 %s：%s" % (sel, want, blk[:110])


def test_no_non_token_control_radius_remains():
    """控件圆角只能是令牌档；7px 是全站最后一个越档值。

    2026-10-29 全站普查（6 个视图 × 1440 渲染）：唯一非令牌的**控件**圆角是
    `#srccap .scbtn` 的 7px——而同一条来源条上的 `.sclink`（同样 28px 高）
    是 6px，全站其余 28px 控件（`.ws-lg`、`.scbtn` 基类）也都是 6px。

    允许留下的非令牌值都是**按尺寸等比缩放**的（`.bic-ota` / `.bic-air` 的
    `calc(var(--bic)*.26/.273)` 渲染出 3.38~7.02px），以及令牌本身
    （`--r2:11px`）与 `kbd` 的键帽档——判据要看比例与角色，不是绝对值。
    """
    src = _src()
    assert "border-radius:7px" in src  # 仍有按比例缩放引用以外的？逐条核对
    # 控件（28px 高、实心/描边按钮）不得再用 7px
    i = src.find("#srccap .scbtn{")
    assert i > 0, "找不到来源条按钮规则"
    blk = src[i:src.find("}", i) + 1]
    assert "border-radius:6px" in blk, blk[:110]


def test_pacing_trace_detail_rows_keep_their_grid_at_every_width():
    """溯源数据行在四档宽度都必须是同一套列网格，且不得横向溢出。

    2026-10-29 用真实形状的记录实测（注入 fetched_at/path_status/
    request_url/note 三行，320/390/768/1440）：
    - 四个字段 + URL 行的左缘在**同一档内逐行完全一致**（无错列）；
    - 详情右缘从未越过节流面板右缘（overflow=false），文档级也无横向滚动；
    - 窄档（≤某断点）表头 `display:none`、数据行改「时间/状态 + 入口 + 证据」
      三行堆叠，这是刻意设计——表头隐藏后字段名靠行内自明，不是塌陷。

    判据只钉结构契约：四列网格在宽档存在、窄档有显式的两列堆叠规则、
    表头隐藏是**显式声明**而不是被压成 0 宽。
    """
    src = _src()
    i = src.find(".pace-tline{display:grid;grid-template-columns:86px 64px 52px")
    assert i > 0, "找不到溯源行的四列网格"
    assert ".pace-tline.head{display:none}" in src, "窄档表头应为显式隐藏"
    assert 'grid-template-areas:"t st" "p p" "n n"' in src, "窄档应显式声明两列堆叠"


def test_radar_legend_covers_every_drawn_series():
    """雷达图例必须解释图上画的每一条线，且色块与文字同一行。

    2026-10-29 实测：画布 7 条线（1 红最低日 + 6 条灰「其他出发日」），
    图例只有「最低日 · 选中 11-14」**一条**——六条灰线在图上没有任何解释，
    而航线图例是「几条线几条图例」。同一张图例,两种完整度。

    另两处同批修的：`.mon-legend>span>b` 缺 `display:inline-block`，色块以
    block 独占一行（实测色块 y 与文字 y 差 10px）；文案里 `'... 选中 ' + ' 11-14'`
    拼出两个空格。

    判据：图例渲染接受 series 参数、灰线有计数条目、色块是 inline-block。
    """
    src = _src()
    i = src.index("function spMonRenderLegend(")
    seg = src[i:i + 1400]
    assert "spMonRenderLegend(series)" in src, "图例未接收 series（数不出其他日期）"
    assert "'其他出发日 '" in seg, "图例未解释灰色系列"
    assert "_others=(series||[]).filter(" in seg, seg[:160]
    # 色块行内化（否则独占一行）
    i = src.index(".mon-legend>span>b{")
    blk = src[i:src.find("}", i) + 1]
    assert "display:inline-block" in blk and "margin-right:5px" in blk, blk
    # 不得再拼出双空格
    assert "'最低日 · 选中 '+" not in src, "图例文案又出现双空格"


def test_small_card_head_buttons_actually_render_at_declared_height():
    """卡头动作按钮声明 26px 就必须真的渲染 26px。

    2026-10-29 实测：`.hdiag-card .hdiag-acts .btn2{height:26px}` 自 r433 起
    **从未生效**——基础 `.btn2` 声明在更靠后的扁平层（`height:32px;
    min-height:32px`），同优先级按声明顺序后者胜；而 `min-height` 还会把
    height 顶回去（实测连内联 `height:26px!important` 都压不回 26px，
    因为 min-height 仍在）。结果是「渠道健康卡里每个自检钮都比设计高 6px」，
    卡片总高 163.3px。补 min-height 后实测 26px、卡片 157.3px、文本不裁切。

    判据：该规则同时写 height 与 min-height，且两者同值。
    """
    src = _src()
    i = src.find(".hdiag-card .hdiag-acts .btn2{")
    assert i > 0, "找不到卡头动作按钮规则"
    blk = src[i:src.find("}", i) + 1]
    assert "height:26px" in blk, blk[:130]
    assert "min-height:26px" in blk, \
        "只写 height 会被更靠后的 .btn2{min-height:32px} 顶回去（实测无效果）：%s" % blk[:130]


def test_rail_segments_and_legend_swatches_share_colors():
    """配额轨三段与图例方块必须是同一组颜色，且三段彼此可区分。

    2026-10-29 实测两个缺陷：
    1) 慢档段用 `color-mix(--r-blue 40%, --r-surface-3)` 得到**浅蓝**——
       整条轨读成「一段深蓝 + 一段浅蓝」，而图例写着三档（快档/慢档/
       TTL 内跳过）。三种不同语义（已发出 / 拉长间隔后发出 / 被跳过）
       只用同一色相的深浅表达，中间那段看不出是「被降频」。
    2) 颜色写了两份：改 `.pace-rail .rs` 后，`.pace-legend .rs` 仍是旧值，
       实测轨道琥珀、图例浅蓝——同一条轨两个颜色。

    判据：两处 `.rs` 都用 `--r-amber`；三段背景各不相同（色相区分）。
    """
    src = _src()
    rail = src[src.index(".pace-rail .rf{"):]
    rail = rail[:rail.index("}") + 1]
    assert "var(--r-blue)" in rail
    i = src.index(".pace-rail .rs{")
    assert "var(--r-amber)" in src[i:src.find("}", i) + 1], "慢档段应为琥珀（受限），不是浅蓝"
    i = src.index(".pace-legend .rs{")
    assert "var(--r-amber)" in src[i:src.find("}", i) + 1], \
        "图例方块必须与轨道同色（两处各写一份，改一处会漂移）"
    assert "color-mix(in srgb,var(--r-blue) 40%" not in src, "浅蓝慢档残留"


def test_tool_groups_are_separated_only_when_on_one_row():
    """底部两组干预按钮同排时必须有可见分隔，换行后必须去掉。

    2026-10-29 实测：13 个同款灰底按钮只靠 18px 间隙隔开，
    「预热 去哪儿 飞猪 携程 同程 途牛 全部 自检 自动 去哪儿 …」读成一串，
    中间那段重复的渠道名会被当成「同一组东西列了两遍」。

    修法用发丝竖线分栏（与 `.pace-stat` 的竖直发丝同一语言）。但竖线只在
    两组**同行**时有意义：折行后它挂在第二组左缘、比第一组左缘缩进 18px，
    读作「这一组莫名缩进一格」。折行由 flex-wrap 决定，宽度阈值量不出
    （900 档仍同行、768 才折），所以用容器查询按面板实宽判。
    实测 1440/1024/900 同行有竖线、768/390/320 折行无竖线。
    """
    src = _src()
    i = src.find(".pace-tools .g+.g{")
    assert i > 0, "缺分组竖线规则"
    blk = src[i:src.find("}", i) + 1]
    assert "border-left:1px solid var(--r-hair)" in blk, blk
    assert "padding-left:18px" in blk, blk
    # 容器查询关掉它（媒体查询按视口宽度判不准）
    j = src.find("@container (max-width: 780px){")
    assert j > 0, "缺容器查询：折行后必须去掉竖线与缩进"
    seg = src[j:j + 160]
    assert "border-left:0" in seg and "padding-left:0" in seg, seg
    assert "container-type:inline-size" in src


def test_all_three_charts_show_a_centered_empty_state():
    """三张图在「数据不够画线」时都要在**画布上**给出居中空态。

    2026-10-29 实测：航线 `.chart-empty`、关注 `.ws-empty` 都有居中空态框；
    **雷达折线分支只写一句脚注就 return**，210~360px 画布整块留白，读作
    「图画坏了」。现在雷达复用 K 线那条覆盖层（`.spmon-kempty`，sticky，
    不撑开横向滚动容器）。

    三处排版同档：正文 12px / 行高 1.6 / 标题 13px/600。实测 `.spmon-empty`
    曾缺 `line-height`（只有它没写），`.chart-empty` 正文是 13px（比自己的
    子元素标题还小一级）。
    """
    src = _src()
    # 雷达数据不足分支必须在画布上出空态，而不是只写脚注
    i = src.index("if(times.length<2||all.length<2){")
    seg = src[i:i + 1100]
    assert "spMonKEmpty" in seg, "雷达数据不足分支未在画布上给空态"
    assert "'<b>当前范围只有 '" in seg, seg[:200]
    # 折线成功路径要收掉空态，否则切模式留残影
    j = src.index("const y0y1=PCHART.domain(")
    before = src[j - 400:j]
    assert "spMonKEmpty" in before and "display='none'" in before, \
        "折线成功路径未隐藏上一条分支的空态覆盖层"
    # 三处空态排版同档。锚点要带首条声明：裸 `.spmon-empty{` 会先命中别处的
    # 单条 override（`.spmon.is-empty #spMonCal>.spmon-empty{width:100%…}`）。
    for sel, need in ((".chart-empty{position:absolute", "line-height:1.6"),
                      (".spmon-empty{display:flex", "line-height:1.6"),
                      (".ws-empty{", "line-height:1.6")):
        k = src.find(sel)
        assert k > 0, sel
        blk = src[k:src.find("}", k) + 1]
        assert need in blk, "%s 缺 %s：%s" % (sel, need, blk[:120])


def test_three_charts_share_a_loading_state():
    """三图首帧都要有加载态，且结构一致：`<b>标题</b><span>说明</span>`。

    2026-10-29 实测：航线是裸文本「数据加载中…」（无标题档、无说明），
    关注是「正在读取关注清单 + 说明」两段，**雷达首帧什么都没有**——
    同一块区域三种起始表现，雷达还会先闪一下空画布。

    现三处统一为「正在读取…」标题 + 「只画真实采集点，未采日期不补点」说明。
    雷达的静态占位挂在 K 线空态那个覆盖层上，`spMonDraw` 入口统一收掉，
    各分支再决定要不要重新显示空态（保证提前 return 的路径也不留加载态）。
    """
    src = _src()

    def seg_after(marker, n=200):
        i = src.index(marker)
        return src[i:i + n]

    assert "<b>正在读取走势</b><span>只画真实采集点" in seg_after('id="chartEmpty"'), \
        "航线加载态缺标题/说明结构"
    assert "<b>正在读取监控记录</b><span>只画真实采集点" in seg_after('id="spMonKEmpty"'), \
        "雷达缺首帧加载态"
    assert "<b>正在读取关注清单</b><span>" in seg_after('id="wsChartEmpty"'), \
        "关注加载态结构变了"
    # 雷达占位必须初始可见（CSS 里是 display:none），并在绘制入口统一收掉
    # 属性顺序：`style` 写在 `id` **之前**，窗口要往后开
    i = src.index('id="spMonKEmpty"')
    assert 'style="display:flex"' in src[i:i + 80], "雷达加载态初始不可见等于没有"
    i = src.index("function spMonDraw(dateSeries,selDate,lowDate){")
    head = src[i:i + 500]
    assert "spMonKEmpty" in head and "display='none'" in head, \
        "绘制入口未统一收掉加载态（提前 return 的分支会留占位）"


def test_success_green_on_green_tint_uses_the_deep_token():
    """绿字压绿底必须用加深档 `--ok-txt`，不能用 `--r-green`。

    2026-10-29 全站 6 视图 × 2 主题对比度普查（`_scratch/audit_contrast_site.py`）：
    `.spmon-run .st.ok{color:var(--r-green)}` 压在 `--r-green-soft` 上实测
    **4.32:1**，AA 小字需 4.5。全站早有为此准备的 `--ok-txt`
    （令牌注释：「--green 对 okbg 4.28:1 欠 AA → 5.63:1」），只是这一处没用。
    改后全站不足项归零。

    注意普查脚本本身要认 `color(srgb …)`——`color-mix` 的结果 Chromium 报成
    该语法，只认 `rgb()` 会把深蓝底当作无背景，白字被误判成 1.11。
    """
    src = _src()
    i = src.find(".spmon-run .st.ok{")
    assert i > 0, "找不到运行状态 ok 胶囊"
    blk = src[i:src.find("}", i) + 1]
    assert "var(--ok-txt)" in blk, "绿字压绿底必须用加深档 --ok-txt：%s" % blk
    assert "var(--r-green)" not in blk, "回退到浅绿会掉到 4.32:1"


def test_search_view_keyboard_focus_is_visible():
    """搜索页每个可聚焦元素都要有键盘焦点环。

    2026-10-29 用真实 Tab 走查（`_scratch/audit_focus_ring.py`）：健康 31 个、
    配置 28 个可聚焦元素全都可见焦点环，**搜索页 36 个里有 9 个没有**——
    出发日/采集日 tab、`.srx-bandlogin`、`.srx-chip`、`.srx-more-rows`、`.srx-mtab`。
    键盘用户完全跟丢焦点。

    根因两层：这些 `.srx-*` 规则自带 `outline:none`（3px 宽度但 style:none），
    而扁平化的 `.srx-chip{box-shadow:none}` 又会把补上的 inset 环一并清掉
    （实测 matches(':focus-visible')=true 但 box-shadow=none）。

    注意探针本身两个坑：程序化 `focus()` 不触发 `:focus-visible`（必须真按 Tab），
    以及 inset 下划线 `0 -2px` 是选中指示、不算焦点环，但 `inset 0 0 0 2px`
    才是全站正规环——不能见 inset 就否。
    """
    src = _src()
    i = src.find('#searchview :is(button,a,[role="button"],summary,[tabindex]):focus-visible{')
    assert i > 0, "搜索页缺统一焦点环规则"
    blk = src[i:src.find("}", i) + 1]
    assert "inset 0 0 0 2px var(--blue)!important" in blk, \
        "焦点环必须带 !important（同权重 box-shadow:none 会清掉它）：%s" % blk[:120]


def test_small_controls_get_a_touch_sized_hit_area_on_coarse_pointers():
    """触摸档下小控件的命中区要够大，桌面观感不能变。

    2026-10-29 逐元素命中测试（390 档 coarse）：三图档位 `.rngchip` 26px、
    `.cnav`/`.cc-chip` 32px、`.lgact .btn2` 32px、`#srccap .scbtn` 32px、
    `.pvx` 28px 的有效热区都只有自身盒高（上下各扩 0px）。

    只加伪元素不够：实测 `.rngchip` 上方 6px 命中 `DIV.uhead`、下方 3px
    命中隔壁 chip——热区被邻居抢走。所以触摸档把盒高本身提到 32px，
    伪元素再补到 36px。实测桌面 fine 仍是 26px（`@media(pointer:coarse)`
    不命中），触摸档 32px，两档都无横向溢出。
    """
    src = _src()
    i = src.find(".rngchip,.cnav,.cc-chip,.lgact .btn2,.pvx,#srccap .scbtn,")
    assert i > 0, "缺触摸档小控件尺寸规则"
    blk = src[i:i + 700]
    assert "min-height:32px" in blk, blk[:160]
    assert "height:36px" in blk, "伪元素要把热区补到 36px"
    assert "transform:translateY(-50%)" in blk, "伪元素须纵向居中，避免顶偏"
    # 必须只在 coarse 下生效（桌面 26px 观感不能变）
    j = src.rfind("@media(pointer:coarse){", 0, i)
    assert j > 0 and i - j < 400, "该规则必须包在 @media(pointer:coarse) 里"


def test_card_spacing_has_no_double_gap():
    """卡片间距不能「容器 gap + 自身 margin」叠加成双份。

    2026-10-29 实测关注台：父容器 `.wstudio` 是 `flex; gap:10px`，
    而相邻兄弟规则 `#monview .ws-card+.ws-card{margin-top:10px!important}`
    又加了一份 —— 同一容器里**第一段 10px、之后每段 20px**，同一种卡片两种
    间距，且 20px 不在 4/6/8/12/16/24 阶上（全站普查只此一处越阶）。

    修法：间距由容器 gap 单源提供，`.wstudio` 内的卡片 margin 归零
    （与 `.mon-card{margin:0 0 14px}` 的归零同律）。修后全站卡片间距
    只有 8px 与 10px 两档，各自内部一致。
    """
    src = _src()
    # 相邻兄弟规则不得再把 ws-card 算进去（它已在 gap 容器里）
    i = src.find("#monview .ucard+#ucard,#monview .ucard+.ucard,")
    assert i > 0, "找不到相邻卡片间距规则"
    blk = src[i:src.find("}", i) + 1]
    assert ".ws-card+" not in blk, "ws-card 已在 .wstudio 的 gap 里，再加 margin 会双份：%s" % blk[:160]
    # 必须显式抵消
    j = src.find("#monview .wstudio>.ws-card{margin-top:0!important}")
    assert j > 0, "缺 .wstudio 内卡片 margin 归零规则"
