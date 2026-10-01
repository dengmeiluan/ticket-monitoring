# -*- coding: utf-8 -*-
"""WD 增强候选 EN-1/2/3/5/6/7 + M-1/M-2/M-3 + 推送总表图文件名去重：

EN-1 头部 chrome 税收敛：hdmeta 独占行（flex-basis:100%）从 ≤900 收窄到
≤540——541-900 带 hbtn+pill+hdmeta 同行装得下，header 三行变两行，
吸顶偏移与内容可视区双收益（--hdh 动态单源自动跟随）。
EN-2 日历格保持纯展示（审计建议「格级点击跳明细」经真机证伪后维持
收口）：格键=扫描观察日域（近 14 天窗），FLT.dates 过滤域=明细出发
日域（未来出发窗），两域恒不相交——格级点击恒为空过滤死通道；去
该轮明细的活通道是走势 canvas 点击。无动作元素不加 role=button。
EN-3 resetFlt 附带恢复默认排序：SORT 驻留曾只能靠再点「价格」表头复位
（不可发现）；复位+条件 toast（仅原排序非默认时告知）。
EN-5 541-760 带视图切换器吸顶：复用 761+ 单行横滚形制（4 tab 该带放得下），
top 消费 var(--hdh)。
EN-6 字号半步归并：11.5/12.5/13.5 全站清零（向下归并到邻近整步，
密度不减、折行风险最低）。
EN-7 K线态图例折行：K线专有释义（开/收=桶内首末轮；绿桶=桶内回落）
第二行显示，宽画布单行 ~90 字超读。
M-1 a.numlink 触控热区外扩（28px 高，外扩后达 36px 触控档）。
M-2 文本链接焦点环并入全站 2px 蓝环清单（a.vw/.kpisum a/a.numlink/#foot a）。
M-3 载荷级 stopTimeT 防回流钉补回（webui 载荷两端恒落键）。
wE-EN1 推送总表图文件名航线段去重：同航线多日期 entry 曾拼出
URCSHAURCSHA——names 收集去重保序。
"""
import json
import logging
import types

import webui

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        import inspect
        _SRC = inspect.getsource(webui)
    return _SRC


# ---------------- EN-1 头部 chrome 税收敛 ----------------

def test_en1_hdmeta_full_row_only_le540():
    s = src()
    # ≤540 带：hdmeta 独占行保留（390 物理宽度下限）
    assert '.hdmeta{flex-basis:100%' in s, "≤540 的 hdmeta 独占行声明缺失"
    # 收敛后：max-width:900 块不再有 basis:100%（hdmeta 并入 pill 行）
    i = s.find('@media(max-width:900px){\n  .hdx')
    assert i >= 0, "≤900 的 hdx 折行保底块缺失"
    block = s[i:s.find('}}', i) + 2]
    assert 'flex-basis:100%' not in block, \
        "≤900 块仍含 hdmeta 独占行——541-900 未收敛为两行"


# ---------------- EN-2 日历格保持纯展示（审计建议证伪后的收口钉） ----------------

def test_en2_calcell_pure_display():
    s = src()
    # 死通道保持收口（审计建议经真机证伪后维持）：日历格键=扫描观察
    # 日域（近 14 天），FLT.dates 过滤域=明细出发日域（未来出发窗），
    # 两域恒不相交——格级点击跳明细恒为空过滤；无动作元素不加
    # role=button（假 affordance）
    i = s.find("$('calgrid').innerHTML")
    assert i > 0, "renderCal 输出点缺失"
    cal_seg = s[max(0, i - 600):i]
    assert 'role="button"' not in cal_seg, "日历格不得挂 role=button（纯展示）"
    assert "function jumpCalDate" in s, "走势活通道 jumpCalDate 须保留"


# ---------------- EN-3 resetFlt 恢复默认排序 ----------------

def test_en3_resetflt_resets_sort():
    s = src()
    i = s.find('function resetFlt()')
    assert i >= 0
    body = s[i:s.find('}', s.find('saveUI()', i))]
    assert "SORT={k:'price',dir:1}" in body, "resetFlt 未复位 SORT"
    # 告知只在显式重置入口（跳转类调用方自带 toast，双条堆叠=冗余播报）
    j = s.find('function resetFltUI()')
    assert j >= 0, "缺显式重置入口 resetFltUI"
    ui_body = s[j:s.find('}', s.find('resetFlt()', j))]
    assert 'toast(' in ui_body, "resetFltUI 缺排序告知"
    assert 'onclick="resetFltUI()"' in s, "重置按钮未接 resetFltUI"
    assert '重置筛选与排序' in s, "按钮词面未同步排序副作用"


# ---------------- EN-5 541-760 吸顶 ----------------

def test_en5_montabs_sticky_541_760():
    s = src()
    assert '@media(min-width:541px) and (max-width:760px)' in s, \
        "541-760 专用块缺失"
    i = s.find('@media(min-width:541px) and (max-width:760px)')
    block = s[i:s.find('}', s.find('#montabs', i))]
    assert 'position:sticky' in block and 'top:var(--hdh' in block, \
        "541-760 带切换器未吸顶或未消费 --hdh"


# ---------------- EN-6 字号半步归并 ----------------

def test_en6_no_half_step_font_sizes():
    s = src()
    for half in ('font-size:11.5px', 'font-size:12.5px', 'font-size:13.5px'):
        assert half not in s, "字号半步残留：%s" % half


# ---------------- EN-7 K线态图例折行 ----------------

def test_en7_kline_ringnote_breaks_line():
    s = src()
    i = s.find("$('ringNote').innerHTML=CR.mode==='kline'")
    assert i >= 0
    seg = s[i:i + 900]
    assert '<br>' in seg, "K线态图例未折行（专有释义应第二行）"


# ---------------- M-1 numlink 触控热区 ----------------

def test_m1_numlink_hit_area():
    s = src()
    assert 'a.numlink{color:inherit;text-decoration:none;position:relative}' in s, \
        "numlink 缺 relative 锚"
    assert 'a.numlink::after{content' in s, "numlink 缺 ::after 热区外扩"


# ---------------- M-2 焦点环清单 ----------------

def test_m2_text_link_focus_ring():
    s = src()
    for sel in ('a.vw:focus-visible', '.kpisum a:focus-visible',
                'a.numlink:focus-visible', '#foot a:focus-visible',
                '.demoBar a:focus-visible'):
        assert sel in s, "焦点环清单缺 %s" % sel


# ---------------- M-3 载荷级 stopTimeT 恒落键 ----------------

def test_m3_payload_stoptimet_anchor():
    s = src()
    assert s.count('"stopTimeT":') == 2, \
        "webui 载荷两端 stopTimeT 恒落键应各出现 1 次（共 2），防回流"


# ---------------- 锚点补偿全带动态单源 ----------------

def test_anchors_follow_hdh():
    s = src()
    # 深滚跳转落点补偿须消费 --hdh 贴 header 实高（固定像素在倒计时
    # 折行漂移下全带欠账）；固定 hdh+34 档已被三段式实效档按源码序
    # 接替（r262 退役，凡「≤760 补偿未动态化」以三段式在场为准）
    for fixed in ('scroll-padding-top:118px', 'scroll-padding-top:136px',
                  'scroll-padding-top:106px'):
        assert fixed not in s, "锚点补偿固定像素残留：%s" % fixed
    assert 'calc(var(--hdh,54px) + 34px)' in s, "≤900 锚点补偿未动态化"
    assert 'calc(var(--hdh,76px) + 34px)' not in s, \
        "≤760 hdh+34 固定系数档复活（三段式实效档覆盖下的死代码）"
    assert s.count('scroll-padding-top:calc(var(--hdh,134px)'
                   ' + var(--mtabsh) + var(--tabsh,0px) + 4px)') == 2, \
        "≤760/761+ 三段式动态补偿档缺失"


# ---------------- wE-EN1 推送总表图文件名去重 ----------------

def test_we_en1_table_png_route_dedup(tmp_path, monkeypatch):
    import core.alerter as al
    from core.alerter import Alerter
    import report

    captured = {}

    def fake_render(rows, title, out_path, **kw):
        captured['png'] = str(out_path)
        return str(out_path)

    def fake_upload(p, *a, **k):
        return 'https://img.test/' + str(p).replace('\\', '/').split('/')[-1]

    monkeypatch.setattr(report, 'render_flights_table', fake_render)
    monkeypatch.setattr(report, 'upload_chart', fake_upload)
    monkeypatch.setattr(report, 'upload_ghimg', fake_upload, raising=False)

    lg = logging.getLogger('t_v15116')
    a = Alerter(lg, storage=None)
    a.image_host = None

    def route(label='乌鲁木齐→上海'):
        return types.SimpleNamespace(
            label=label, from_code='URC', to_code='SHA',
            from_name='乌鲁木齐', to_name='上海',
            alert_direct=1900, alert_transfer=1700,
            transfer_arrival_max=None, transfer_layover_min=None)

    r = route()
    sec = lambda d: {"date": d, "top_direct": [], "top_transfer": []}
    # 生产「逐日期独立 entry」形态：同航线两个 entry（不同日期）
    rs_list = [(r, [sec('2026-10-05')]), (r, [sec('2026-10-06')])]
    a._flights_table_md_multi(rs_list, ops_notes=[])
    png = captured.get('png', '')
    assert png, "总表图未渲染"
    assert png.count('URCSHA') == 1, \
        "文件名航线段重复（同 OD 应去重保序）：%s" % png


# ---------------- M-4 cfgnav sticky 并入 --hdh 动态单源 ----------------

def test_m4_cfgnav_sticky_tracks_hdh():
    s = src()
    # sticky top 与 max-height 同 rule 双声明均消费 var(--hdh)：header
    # 实高变化（倒计时折行/密度切换）时配置页导航与监控页吸顶家族
    # 同源跟随；fallback 54+4=58 与 54+16=70 精确等值旧固定值
    # （JS 失效零退化）
    assert '.cfgnav{position:sticky;top:calc(var(--hdh,54px) + 4px)' in s, \
        "cfgnav sticky top 未并入 --hdh 动态单源"
    assert 'max-height:calc(100vh - var(--hdh,54px) - 16px)' in s, \
        "cfgnav max-height 未随 header 实高联动"
    assert 'top:58px' not in s, "固定 top:58px 残留（防回流）"


# ---------------- P1-1 空配置 × 非概览子栏自愈 + 守卫缺口 ----------------

def test_p11_empty_users_selfheal_overview():
    s = src()
    # render() 空分支切回概览（hero 教学卡在概览 pane 内，非概览子栏
    # 停留时删光用户曾被埋葬成空白死区，jpmontab 持久化使刷新也不自
    # 救）；silent 形态防入场动画与 hash 写副作用
    i = s.find('if(!s.users||!s.users.length){')
    assert i >= 0, "render 空分支缺失"
    seg = s[i:i + 400]
    assert "showMonTab('overview',true)" in seg, \
        "render 空分支未切回概览（hero 埋葬死区）"
    # chart()/table() 守卫对空数组收紧（[] 为真值放行 → curRoute 读
    # S.users[U] 的 routesArr 抛 TypeError pageerror）
    for fn in ('function table(){', 'function chart(){'):
        i = s.find(fn)
        assert i >= 0, "%s 缺失" % fn
        head = s[i:i + 80]
        assert '!S.users.length)return' in head, \
            "%s 守卫未收紧到 length（空数组放行崩溃）" % fn


# ---------------- P2-1 541-760 带明细跟页滚（吸顶可达结构前提） ----------------

def test_p21_band_541_760_tw_release():
    s = src()
    i = s.find('@media(min-width:541px) and (max-width:760px)')
    assert i >= 0, "541-760 专用块缺失"
    block = s[i:s.find('}}', i) + 2]
    assert '.tw{max-height:none}' in block, \
        "541-760 带未放开 .tw 内滚（montabs 吸顶触发点永超页面最大滚动=死代码）"
    # 内滚路径宽度族同步 540→760：.tw 侧监听门 / End 跳底 / 重建滚动
    # 位 / 抽屉拉升门四处 <=760 + window 侧续载门一处 >760（r241 起
    # 吸顶筛选条为 ≤760 全带形制，抽屉拉升门原「锚 ≤540 独有吸顶条」
    # 的例外前提消失，随族扩带）；r248 起明细空态指路随族 +1
    # （≤760「重置筛选」按钮在默认收起的筛选抽屉内，词面须给抽屉语境）
    assert s.count('window.innerWidth<=760') == 5, \
        "窄档宽度族门应恰 5 处消费 <=760"
    assert s.count('window.innerWidth>760') == 1, \
        "window 侧续载门应恰 1 处消费 >760"
    assert 'window.innerWidth>540)' not in s, \
        "window 侧续载门残留 540 键（541-760 续载死路）"
    assert 'window.innerWidth<=540' not in s, \
        "≤540 键应清零（抽屉拉升门已随族扩带，例外前提消失）"
    # 带内锚点补偿须含吸顶切换器高度（跳转落点不被 montabs 盖回）——
    # 设计意图由 ≤760 合并块尾三段式实效档承载（hdh+--mtabsh+--tabsh+4，
    # 源码序覆盖带内全部档）；旧固定 hdh+40px 注记档已退役（r262），
    # 固定档复活=死代码回归（被源码序覆盖，任何视口不可达）
    assert 'scroll-padding-top:calc(var(--hdh,76px) + 40px)' not in s, \
        "541-760 旧固定补偿档复活（死代码回归）"
    assert s.count('scroll-padding-top:calc(var(--hdh,134px) + var(--mtabsh)'
                   ' + var(--tabsh,0px) + 4px)') == 2, \
        "三段式实效补偿档（≤760/761+）缺失，吸顶三件补偿断链"


# ---------------- P2-2 触控三块 nav span 36px 地板 ----------------

def test_p22_nav_span_touch_floor():
    s = src()
    # 三个触控块（≥901 粗指针 / ≤900 粗指针 / ≤760 任意指针）同步：
    # nav span 仅 padding 增强时视高 ~35px 差 1px 触控地板；inline
    # 元素 min-height 不生效，须 flex 化垂直居中
    assert s.count('nav span{min-height:36px;display:inline-flex;'
                   'align-items:center}') == 3, \
        "触控三块 nav span 36px 地板应恰 3 处"


# ---------------- P2-3 demoBar 链接焦点环入全站清单 ----------------

def test_p23_demobar_focus_ring():
    s = src()
    assert '.demoBar a:focus-visible' in s, \
        "demoBar 下载链接未入全站 2px 蓝环清单（UA 默认 1px 黑脱队）"


# ---------------- 推送审校 P2-1/2/3 ----------------

def test_push_p21_png_plat_tag_tie():
    # PNG 总表图渠道列补「·同价×N」（文本版 plat_full 有、图版曾有
    # ——exact-tie 多渠道行在图主路径只显单渠道=比价信息丢失；
    # 词面与文本版逐字同语言；tie 段殿前、stale 段殿后（超宽截断
    # 只吃 stale 尾，N 计数恒保）
    from report import _plat_tag
    cn = {"tongcheng": "同程", "qunar": "去哪儿"}
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 3}, cn) == \
        "同程·同价×3"
    assert _plat_tag({"_platform": "qunar"}, cn) == "去哪儿"
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 2,
                      "_stale_h": 1.0}, cn) == "同程·同价×2·1h前"


def test_push_p22_storm_body_marker():
    # 风暴第 N 条正文首行带序号（钉钉聊天窗口不显示标题——重发标记
    # 只进标题=用户不可见，LESSONS 二.1/八.2 自家定律；词面与标题
    # _storm_title 逐字同语言）
    from core.alerter import _storm_desp, _storm_title
    d = _storm_desp(2, 3, "正文")
    assert d == "📞 达标提醒 2/3\n\n正文", "风暴正文首行缺序号标记"
    assert d.splitlines()[0] in _storm_title(2, 3, "T"), \
        "正文首行词面与标题不同语言"


def test_push_p23_digest_storm_gate():
    # 死路径 _push_digest 风暴触发与 multi 主路径同门：sent+hits+
    # fresh_hits 才连推、免打扰时段跳过（无门状态复活即持续达标轮
    # 15 分钟 3 连推的休眠隐患）
    import inspect
    import core.alerter as al
    body = inspect.getsource(al.Alerter._push_digest)
    assert "fresh_hits" in body, "_push_digest 无 fresh_hits 去抖"
    assert "_in_quiet" in body, "_push_digest 风暴无免打扰门"
    gate = "if sent and hits and fresh_hits and self.storm_repeat > 1:"
    assert inspect.getsource(al.Alerter).count(gate) == 2, \
        "风暴三重门应恰两处（multi 主路径+digest 死路径同形）"
