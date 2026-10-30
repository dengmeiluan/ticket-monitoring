# -*- coding: utf-8 -*-
"""r420 节流面板：台账头 + 分渠道速览 + 配额轨 + 复发表 + 干预按钮组。

本文件只钉**行为契约**，不锁具体颜色/像素：
- 零样本不得冒充正常（advice=unknown 时不许打「各渠道近 24h 正常」）；
- 10 秒自动刷新重建面板后，键盘焦点必须留在原动作上；
- 动作必须是真按钮（触屏 36px 地板对 <a onclick> 之外的元素同样生效）；
- 覆盖率「没发」渲染成 —，不得渲染成 0%。
"""
import os
import pathlib
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def _pacing_seg():
    src = _src()
    return src[src.index("async function loadPacing("):src.index("async function showTrace(")]


def test_unknown_advice_never_claims_all_normal():
    """实测缺陷：五个渠道全是 advice.state=unknown（近 24h 无样本）时，
    面板却打出「无需操作 · 各渠道近 24h 正常」——零样本冒充正常。"""
    seg = _pacing_seg()
    assert "_unk" in seg, "未收集 unknown 渠道"
    assert "待首轮" in seg, "零样本渠道未被单独说明"
    # 「全绿」那句必须被 unknown 挡住 —— 从门控表达式本身往后取，
    # 不要用固定 260 字符窗口：插一句演示分支就会被挤出去变成假红。
    i = seg.index("无需操作 · 各渠道近 24h 正常")
    gate = seg[max(0, i - 900):i]
    assert "_unk.length" in gate, "全绿结论未排除 unknown"
    assert "_demoAll" in gate, "全绿结论未排除演示数据"


def test_coverage_dash_not_zero_percent():
    """没发出任何请求时覆盖率必须是 —。0% 会被读成「发了全失败」。"""
    seg = _pacing_seg()
    assert "(j.coverage.ratio||0)*100" not in seg
    assert "j.coverage.ratio==null?null" in seg
    assert "_covVal===null?'—'" in seg


def test_rebuild_keeps_keyboard_focus():
    """10s 轮询整块重建面板：停在「溯源/预热」上的键盘用户不得坠回 body。"""
    src = _src()
    assert "function _paceRestoreFocus(" in src
    assert "PACE.focusKey" in src
    seg = _pacing_seg()
    assert "_paceRestoreFocus()" in seg, "重建后未调用焦点恢复"
    # 每个动作都要有稳定键，否则换序/增删后无法找回
    for key in ("data-pk=\"'+k+':trace\"", "data-pk=\"warm:'+p+'\"", "data-pk=\"probe:'+p+'\"",
                "data-pk=\"refresh\""):
        assert key in seg, key


def test_actions_are_real_buttons_with_touch_floor():
    """旧触屏规则只放大 `#paceBox a[onclick]`；本版动作是 button/select，
    36px 触控地板必须同样覆盖，否则手机上仍只有 18px 高。"""
    src = _src()
    seg = _pacing_seg()
    assert "<a href=\"javascript:void(0)\" onclick=\"paceReset(" not in seg, "解除仍是 <a onclick>"
    assert 'class="g"' in seg and "pace-tools" in seg
    assert "#paceBox .pace-row .ac button{min-height:36px}" in src
    assert "#paceBox .pace-tools .g :is(button,a),#paceBox .pace-tools .g select{height:36px}" in src


def test_scope_and_path_readings_stay_separate():
    """分域/分通路（成因）与在用查询率（结果）必须并排各给一份，
    合成一个数会让「100%」掩盖「明细一条没拿到」或某个域全挂。"""
    seg = _pacing_seg()
    assert "scoped('dom','国内')" in seg and "scoped('intl','国际')" in seg
    assert "query_attempts_live" in seg and "query_rate_live" in seg
    assert "retired_paths" in seg and "退役" in seg
    assert "query_detail_ok" in seg and "query_calendar_only" in seg


def test_metric_strip_is_compact_not_full_width_quarters():
    """4 格等分 1200px 时每格 305px、3 字内容漂在空格里（实测）。
    量尺必须按内容收宽，把余下空间留给配额轨。"""
    src = _src()
    i = src.index(".pace-stats{")
    seg = src[i:i + 300]
    assert "width:fit-content" in seg, "量尺仍铺满整行"
    assert "grid-template-columns:repeat(4" not in seg, "量尺仍用 4 等分网格"


def test_all_sizes_within_four_step_scale():
    """节流面板字号只允许 11（标签）/12（正文）/16（量尺数字）三档。"""
    src = _src()
    a = src.index(".pace{display:flex")
    # 必须从节流块之后再找首个断点，否则会撞上文件前段的同名断点、
    # 切出空区间——空区间里没有字号，测试就成了空转。
    b = src.index("@media(max-width:900px){", a)
    assert b > a
    block = src[a:b]
    sizes = {m.group(1) for line in block.splitlines()
             if not line.strip().startswith("/*")
             for m in re.finditer(r"font-size:(\d+)px", line)}
    assert sizes, "节流 CSS 区间内没有取到任何字号，切片有误"
    assert sizes <= {"11", "12", "16"}, "节流面板出现额外字号档：%s" % sorted(sizes)


# ---------- 多维渠道：会话维度 + 两表同序 ----------

def test_health_rows_and_pacing_rows_share_one_order():
    """健康行曾用 Object.keys().sort() 的字母序（携程→飞猪→去哪儿），而
    节流面板按 API key 序（去哪儿→飞猪→携程）。两张表上下相邻却各排
    一套，用户每看一张都要重新找行。两处都必须走 SRX_PLAT_ORDER。"""
    src = _src()
    h = src[src.index("function renderHealth(j)"):src.index("function renderPushChannels")]
    p = src[src.index("async function loadPacing("):src.index("async function showTrace(")]
    for seg, name in ((h, "健康行"), (p, "节流行")):
        assert "SRX_PLAT_ORDER.indexOf" in seg, name + "未复用统一渠道序"
    # 不得回退到裸字母序
    assert "Object.keys(j.stats||{}).sort()" not in src
    # 节流行的渲染顺序必须来自 _order（由 SRX_PLAT_ORDER 排序得出）。
    # 取值类用途（比如统计哪些渠道被自动降频）不受此限。
    assert "const chips=_order.map(" in p, "节流行的渲染顺序未走统一渠道序"


def test_health_card_shows_session_dimension_for_multi_slot_vendor():
    """健康行原本只有「厂商」一个维度：飞猪 PC/H5 是两套独立 cookie，
    H5 掉了照样只显示「飞猪需登录」，看不出核哪一端。多会话厂商必须
    逐端给出状态，且「去登录」要落到具体槽位。"""
    src = _src()
    assert "function healthSlotNote(" in src
    seg = src[src.index("function healthSlotNote("):src.index("function renderHealth(j)")]
    assert "own.length<2" in seg, "单会话厂商应不显示小标"
    assert "surface_label" in seg
    # 健康行要挂上这个维度
    h = src[src.index("function renderHealth(j)"):src.index("function renderPushChannels")]
    assert "healthSlotNote(p)" in h
    assert "_slotHtml" in h
    # 「去登录」优先按槽位判定，且落到槽位 key
    act = src[src.index("function renderHealthLoginAction("):src.index("function srcAccessState(")]
    assert "needSlots" in act and "slots" in act


def test_login_requirement_table_has_no_legacy_tiers():
    """用户明确废弃「建议登录」策略：全渠道必须登录，差异只在会话槽位。
    遗留的 建议/国内需/国际需 分档不得再出现在任何映射表里。"""
    src = _src()
    i = src.index("const LOGIN_NEED")
    seg = src[i:i + 400]
    for legacy in ("建议", "国内需", "国际需"):
        assert legacy not in seg, "登录要求表仍留旧分档：%s" % legacy
    # 五家 + 飞猪 H5 槽位都必须是「必须」
    assert seg.count("必须") >= 6


def test_login_copy_does_not_promise_anonymous_pricing():
    """界面文案也不得再暗示「可以匿名查价」——双端弹窗曾写「飞猪 PC 可
    匿名查价」，与全渠道必须登录的口径冲突。注释里说明「入口可浏览」
    是允许的，所以这里只看用户可见的 HTML 串。"""
    src = _src()
    for m in re.finditer(r"<div class=\"lgmodal-note\">([^<]*)<", src):
        txt = m.group(1)
        for bad in ("可匿名查价", "建议登录", "国内需", "国际需"):
            assert bad not in txt, "弹窗文案仍含旧口径：%s" % txt
    # 双端弹窗必须明确「两端都要登录」
    assert "两端都必须登录" in src


def test_demo_login_state_also_exposes_six_slots():
    """演示模式的 /api/login-state 曾只返回 plats，没有 slots——登录卡于是
    静默回落成「按厂商一行」，健康卡的会话维度也永不出现。演示环境是
    开源访客的第一眼，不能把飞猪 PC/H5 双端藏掉。"""
    from core.login_slots import LOGIN_SLOT_ORDER, LOGIN_SLOTS
    # 服务端处理代码不在 PAGE（那是 HTML），要读源文件
    src = (pathlib.Path(ROOT) / "webui.py").read_text(encoding="utf-8")
    i = src.index('elif self.path == "/api/login-state":')
    seg = src[i:i + 3000]
    demo = seg.split("\n                else:")[0]
    assert '"slots"' in demo, "demo 分支未返回 slots"
    assert "LOGIN_SLOT_ORDER" in demo, "demo 槽位未按单一顺序表生成"
    assert "LOGIN_SLOTS" in demo, "demo 槽位未复用槽位定义"
    # 定义侧必须是 6 个槽位且飞猪占两个
    assert len(LOGIN_SLOT_ORDER) == 6
    assert sum(1 for k in LOGIN_SLOT_ORDER if LOGIN_SLOTS[k]["plat"] == "fliggy") == 2
    """节流面板搬到健康卡后，参数仍在配置页。原来那句「参数在…里调」
    是死文字，用户要自己翻三层导航。必须是一键直达的分区链接。"""
    src = _src()
    i = src.index('<div class="hpace">')
    seg = src[i:i + 420]
    assert 'class="hlink"' in seg, "参数提示仍是死文字"
    assert "cfgGoThrottle()" in seg
    # 直达函数要切到承载节流控件的面板并聚焦第一个节流控件
    # （r638 起控件在独立的 pacing 分区，之前是 globals）
    fn = src[src.index("function cfgGoThrottle("):src.index("async function health(")]
    assert ("showCfgPanel('pacing')" in fn
            or "showCfgPanel('globals')" in fn), (
        "直达函数没有切到任何配置分区：%r" % fn[:160])
    # 落点必须是节流控件本身（r638 起切分区即可直达，锚点已不需要）
    assert "glbQs" in fn, "没有聚焦到第一个节流控件"


def test_demo_rows_do_not_claim_normal_without_samples():
    """演示模式实测缺陷：五个渠道齐刷刷「正常 —」——破折号在面板里专指
    「近 24h 无样本」，与「正常」并列会被读成「没测到却没报错」；而把合成
    状态写成「正常」等于让访客以为渠道已实测通过。演示下必须是中性的
    「演示」+「无真实样本」，且结论行不得再说「各渠道近 24h 正常」。"""
    src = _src()
    seg = src[src.index("async function loadPacing("):src.index("async function showTrace(")]
    assert "_demoAll" in seg, "未识别「全渠道演示数据」这一形态"
    assert "?'演示':'正常'" in seg, "演示渠道仍标成「正常」"
    # 演示行的证据文案：r496 起由「无真实样本」改为更短的「合成 · 未实测」
    # ——5 行各写一遍「合成样本 · 不参与成功率」会让每行多占 17px 高度
    # （390 档行高 80px）。守的是**意图**：演示行必须自述「这是合成数据」，
    # 不得留空、也不得让读者以为实测通过。
    assert ("ev='合成 · 未实测'" in seg or "'无真实样本'" in seg), \
        "演示行未给出诚实证据（既不是「合成 · 未实测」也不是「无真实样本」）"
    assert "无真实采集样本，跑一轮真实扫描后才可判断" in seg, \
        "演示结论仍可能打出「各渠道近 24h 正常」"
    assert seg.index("const _demoAll=") < seg.index("(_demoAll"), \
        "_demoAll 定义晚于使用（TDZ）"
    assert seg.count("const _demoAll=") == 1, "两份定义会各写一套口径"


def test_empty_evidence_never_falls_back_to_dash():
    """e1 为空时不得直接落「—」：破折号专指「无样本」。有建议文案就用
    作依据——曾出现同一行「正常 —」并存。"""
    src = _src()
    seg = src[src.index("async function loadPacing("):src.index("async function showTrace(")]
    i = seg.index("if(!ev)ev=(v.ok_streak")
    tail = seg[i:i + 1400]
    # r470 起加了 `&&_pthDemo`：只有账本本身也是合成时才允许自述合成，
    # 演示页接真库时这一行有几十次真实采样，再这么说就自相矛盾。
    # r496 起文案缩短为「合成 · 未实测」（避免 5 行重复占高），意图不变。
    assert ("if(!ev&&_demoAll&&_pthDemo)ev='合成 · 未实测'" in tail
            or "if(!ev&&_demoAll&&_pthDemo)ev='无真实样本'" in tail), \
        "演示行未按「账本也是合成」自述"
    assert "adv.state==='ok'&&adv.hint&&!_demoAll" in tail, "有建议文案时未用作依据"
    assert "if(!ev&&adv.state==='ok'&&!_pthDemo){" in tail, \
        "账本为真但 advice 是演示时，ok 行没有事实依据（会落破折号）"


def test_demo_slot_badges_do_not_claim_logged_out():
    """健康卡会话小标在演示模式下曾显示「PC 未登录 / H5 未登录」并染成
    告警色——那是合成会话，不是真实登出，且局部截图会被当成真实故障。
    演示载荷（pay.demo）下只声明「演示」，真实载荷仍逐端给状态。"""
    src = _src()
    i = src.index("function healthSlotNote(")
    seg = src[i:i + 2200]
    assert "if(pay.demo){" in seg, "未区分演示会话"
    demo_part = seg[seg.index("if(pay.demo){"):seg.index("const LBL=")]
    assert "演示" in demo_part
    assert "未登录" not in demo_part, "演示分支仍可输出「未登录」"
    # 演示分支不得带语义色类（hslot bad/ok/warn 只在真实分支出现）
    assert "class=\"hslot " not in demo_part, "演示小标仍挂语义色"
    # 真实分支保留端位状态
    assert "login_required:'需重登'" in seg


def test_row_action_hit_area_does_not_bleed_horizontally():
    """三个动作并排（解除/去验证/溯源）时，行尾按钮的点击热区若左右各外扩
    8px，最右那颗会把整块面板撑出 8px 横向滚动——实测 1440/1024/420
    三档 scrollX 都恰好是 8。热区只纵向扩，横向不外溢。"""
    src = _src()
    i = src.index(".pace-row .ac button::before{")
    rule = src[i:i + 160]
    assert "top:-12px" in rule and "bottom:-12px" in rule, "纵向热区丢失"
    assert "left:-8px" not in rule and "right:-8px" not in rule, \
        "热区仍横向外扩，会把面板撑出横向滚动"


def test_pacing_needs_login_names_the_failing_surface():
    """节流面板原先把飞猪写成笼统的「需登录 · 会话已失效」：PC/H5 是两套
    独立 cookie，只写厂商名用户不知道点哪一端去验证，也会误以为整家挂了。
    多会话 + 某端失效时必须点名那一端；单会话厂商仍走原文案。"""
    src = _src()
    seg = _pacing_seg()
    i = seg.index("else if(v.needs_login||adv.state==='login'){")
    block = seg[i:i + 900]
    assert "CHANNEL_STATE" in block, "未读会话槽位"
    assert "surface_label||x.surface" in block, "未点名失效端"
    assert "_own.length>1" in block, "未区分多会话/单会话"
    # 会话态比节流面板晚到时要自愈重画
    assert "window._paccSlotSig" in src, "会话态到达后节流面板不会重画"


def test_multi_slot_login_action_targets_the_dead_surface():
    """「H5 会话已失效」却给「去验证」按钮时，点开的是厂商级验证窗（PC），
    动作与证据对不上。多会话厂商必须直达失效端登录入口
    （srxGoLogin('fliggy_h5')）；单会话厂商仍用 verifyNow。

    r477：多会话分支不再由运行时 needs_login 独占——账本判来的登录
    （adv.path='H5'）同样要落到该端，否则登完 PC 依然进不去 H5。"""
    seg = _pacing_seg()
    i = seg.index("if(v.needs_login||adv.state==='login'||")
    block = seg[i:i + 2200]
    assert "if(_own2.length>1){" in block, "未区分多会话"
    assert "srxGoLogin" in block, "多会话未直达槽位登录"
    assert "'去登录 '+(_pick.surface_label" in block, "按钮未点名是哪一端"
    # 单会话回落到平台级验证
    assert "verifyNow(" in block


def test_diag_card_names_dead_surface_and_targets_it():
    """诊断卡原先是纯厂商维度：飞猪 PC 正常、H5 失效时只写「登录态失效」
    +「打开登录」，点开的是厂商入口，用户会去核错那一端。多会话厂商必须
    标出失效端并把按钮指向该端槽位。"""
    src = (pathlib.Path(ROOT) / "webui.py").read_text(encoding="utf-8")
    # 后端：_attach_diag_slots 给卡片补 slots / dead_surfaces / slot_action
    i = src.index("def _attach_diag_slots(")
    j = src.index("\ndef ", i + 10)
    seg = src[i:j]
    assert "_login_state_view()" in seg, "未取会话槽位"
    assert '"dead_surfaces"' in seg and '"slot_action"' in seg
    assert "len(_own) < 2" in seg, "单会话厂商不应挂这一维"
    # 前端：结论并入端名、按钮指向槽位
    j = src.index("const _dead=(c.dead_surfaces||[])")
    # 窗口不写死长度：卡片渲染块会随注释/按钮增减而变长，
    # 固定 900 字符会在插了说明之后把后半截切掉（实测踩过）。
    ui = src[j:src.index("}).join('');", j)]
    assert "_surfTxt+c.label" in ui, "诊断结论未并入失效端"
    assert "c.slot_action||c.plat" in ui, "按钮未指向槽位"
    assert "打开登录 '+_dead[0]" in ui


def test_demo_health_payload_stays_on_the_light_path():
    """r430 踩过的坑：把演示 /api/health 接进 _health_decorate 会打开
    PriceStorage 连接，接口从 0.03s 挂到 25s+，页面 networkidle 永不达成，
    整批 UI 用例连锁超时（34 个 error）。演示只能走 _attach_diag_slots
    这条只读 /api/login-state 的轻路径。"""
    src = (pathlib.Path(ROOT) / "webui.py").read_text(encoding="utf-8")
    i = src.index('elif self.path == "/api/health":')
    seg = src[i:i + 1400]
    demo = seg.split("\n                else:", 1)[0]
    assert "_attach_diag_slots(out)" in demo, "演示分支未补会话维度"
    # 只判「有没有真的调用」：注释里提到函数名不算走重路径
    assert "_health_decorate(" not in demo, \
        "演示分支又走重路径（会打开 PriceStorage）"
    # 两条路径共用同一份附加逻辑，避免二次分叉
    assert "def _attach_diag_slots(" in src
    # 按**函数体边界**取，不按固定字数：曾写 `+900`，r538 给 _health_decorate
    # 补了 7 行演示态说明注释后调用点被推到 900 字以外，门禁表现为「调用消失」，
    # 而源码里调用一直在。钉「函数体内有调用」，不钉它离函数头多少字。
    i0 = src.index("def _health_decorate(")
    i1 = src.index("\ndef ", i0 + 10)
    deco = src[i0:i1]
    assert "_attach_diag_slots(out)" in deco


def test_login_state_keeps_injectable_seam_and_avoids_recursion():
    """_login_state_view 必须仍走 _health_state（测试与上层都靠它注入证据）；
    但 _health_decorate → _attach_diag_slots → _login_state_view 再调
    _health_state 会无限递归（曾把 /api/health 挂到 25s+、34 个 UI 用例连锁
    超时）。用 _IN_HEALTH_DECORATE 重入标志分流：正常路径保持注入点，
    重入时才改走直接解析日志。"""
    src = (pathlib.Path(ROOT) / "webui.py").read_text(encoding="utf-8")
    assert "_IN_HEALTH_DECORATE = False" in src, "缺少重入标志"
    i = src.index("def _login_state_view()")
    body = src[i:src.index("\ndef ", i + 10)]
    assert "if _IN_HEALTH_DECORATE:" in body, "未按重入分流"
    assert "_health_state(24).get(\"evidence\"" in body, "正常路径丢了注入点"
    # 两处调用点都要置位/复位
    deco = src[src.index("def _health_decorate("):]
    deco = deco[:deco.index("\ndef ")]
    assert "_IN_HEALTH_DECORATE = True" in deco
    assert "_IN_HEALTH_DECORATE = _prev" in deco, "未复位，后续请求会误走日志分支"


def test_recurrence_note_stays_single_line_with_full_text_in_title():
    """复发备注的高度必须有上限，全文也必须可拿到。

    r420 的教训：窄屏放开成 white-space:normal 后，一条 200 字备注撑成
    3 行、5 条记录吃掉 680px（360 档行高 136px）。
    r454 的补充：但一律 nowrap 又把**真实**备注切掉了——「国际列表
    1999/8 连续 7 次未放行（疑会话失效）」320 档实测只露 226/323px、
    360 档丢 157px，而这句正是判断「要不要人工介入」的依据。
    现在的取舍：宽屏单行、窄屏最多两行（line-clamp），并保留 title 全文。
    """
    src = _src()
    # 高度有上限：窄屏不再是无约束的 normal 换行
    assert ".pace-rec .what .h{white-space:normal;overflow-wrap:anywhere;" in src, \
        "窄屏备注未走「限两行」实现"
    assert "-webkit-line-clamp:2" in src, "窄屏备注没有行数上限"
    # 宽屏仍单行
    assert ".pace-rec .what .h{display:block" in src and "nowrap" in src, \
        "宽屏复发备注不再是单行"
    seg = _pacing_seg()
    i = seg.index("const _tailTxt=")
    block = seg[i:i + 900]
    assert 'class="h" title="' in block, "截断后未给 title，全文丢失"
    assert "esc(_tailTxt" in block


def test_real_login_state_store_drives_slot_dimension(tmp_path, monkeypatch):
    """真实路径（非前端 fixture）必须能长出会话维度：往 _SLOT_VERIFY 写入
    H5 登录拒绝后，_login_state_view 的 H5 槽位 needs_login=True，
    _attach_diag_slots 应给出 dead_surfaces=['H5'] / slot_action='fliggy_h5'。
    只测前端注入会掩盖后端没接线。"""
    import logging
    import webui

    root = tmp_path
    monkeypatch.setattr(webui._State, "cfg", {
        "crawler": {"user_data_dir": str(root)},
        "output": {"db_path": str(root / "p.db"),
                   "log_path": str(root / "monitor.log")}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {}, raising=False)
    monkeypatch.setattr(webui._State, "logger", logging.getLogger("r420-slot"))
    (root / "monitor.log").write_text("", encoding="utf-8")
    for prof in ("fliggy", "fliggy_h5"):
        d = root / prof
        d.mkdir(parents=True, exist_ok=True)
        (d / "session-state.json").write_text("{}", encoding="utf-8")

    with webui._SLOT_VERIFY_LOCK:
        webui._SLOT_VERIFY["fliggy_h5"] = {
            "status": "login_required", "at": "2026-10-27 21:10"}
    try:
        slots = webui._login_state_view()["slots"]
        assert slots["fliggy"]["needs_login"] is False
        assert slots["fliggy_h5"]["needs_login"] is True
        assert slots["fliggy_h5"]["surface_label"] == "H5"

        out = {"diag": [{"plat": "fliggy", "needs_login": True}]}
        webui._attach_diag_slots(out)
        c = out["diag"][0]
        assert c["dead_surfaces"] == ["H5"]
        assert c["slot_action"] == "fliggy_h5"
    finally:
        with webui._SLOT_VERIFY_LOCK:
            webui._SLOT_VERIFY.pop("fliggy_h5", None)


def test_every_non_ok_state_explains_itself_not_dash():
    """e1 落成破折号时，同一行右侧还挂着分域/查询率百分比，读作
    「无数据 + 一堆百分比」自相矛盾（实测同程行「— 国内 100% · 国际 74%…」）。
    破折号只留给真无样本；其余每个非 ok 状态都必须自述依据。"""
    seg = _pacing_seg()
    for state, needle in (
            ("path_degraded", "端成功率偏低"),
            ("soft_reject", "上轮被风控软拒"),
            ("recovering", "已恢复出数"),
            ("calendar_only", "只拿到日历价"),
            ("stale", "最近成功"),
            ("degraded", "查询成功率偏低"),
            ("unknown", "近 24h 无样本")):
        i = seg.index("adv.state==='%s'" % state)
        nxt = seg.find("adv.state==='", i + 10)
        block = seg[i:nxt if nxt > 0 else i + 500]
        assert needle in block, "%s 未自述依据" % state
    # 路径劣化不得把百分比再复述一遍（右半已有）
    i = seg.index("adv.state==='path_degraded'")
    block = seg[i:i + 1200]
    assert "Math.round((parseFloat(s1.rate)||0)*100)" not in block


def test_demo_health_exposes_path_dimension_without_fake_zero():
    """演示 /api/health 只返回 rounds/stats/push/diag，没有 paths —— 分域与
    分通路小标在演示里从不出现，「健康只有厂商一个数」在演示环境尤其明显。
    补维度只能从轮次已有字段聚合，且**失败轮不能算作一条通路**，否则会造出
    「无出数 0%」这种假通路（0% 又被读成该通路全失败）。"""
    src = (pathlib.Path(ROOT) / "webui.py").read_text(encoding="utf-8")
    i = src.index('elif self.path == "/api/health":')
    demo = src[i:i + 1400].split("\n                else:", 1)[0]
    assert "_attach_demo_paths(out)" in demo, "演示未补分通路维度"
    # 只判有没有真的调用：注释里说明函数名不算走重路径
    assert "_health_decorate(" not in demo, "演示又走重路径"

    fn = src[src.index("def _attach_demo_paths("):]
    fn = fn[:fn.index("\ndef ")]
    # 失败轮要计入分母（见 test_demo_path_rate_shares_badge_denominator），
    # 但绝不能臆造出一条叫「无出数」的通路——那会显示成「无出数 0%」。
    assert '"无出数"' not in fn, "仍在造「无出数」假通路"

    # 负控：纯失败、且此前没有任何出数形态 → 不产出该渠道的通路
    import webui
    out = {"rounds": [{"plats": {"ctrip": {"s": "fail", "detail": 0, "cal": 0}}}]}
    webui._attach_demo_paths(out)
    assert not out.get("paths"), "无任何出数形态时不应产出通路维度"
    out2 = {"rounds": [{"plats": {"ctrip": {"s": "ok", "detail": 3, "cal": 0}}}]}
    webui._attach_demo_paths(out2)
    assert out2["paths"]["ctrip"]["paths"]["明细"]["attempts"] == 1


def test_demo_path_rate_shares_badge_denominator():
    """徽标与分通路小标必须同分母，否则同一行出现「93% … 明细 100%」两个
    数字打架（用户反复报的老问题）。两条约束：
    1) 失败轮要计入该渠道的通路尝试（否则通路分母只剩成功轮 → 恒 100%）
    2) 维护轮既不算成功也不算失败（否则查询率被拉低到 15% 而通路仍 100%）"""
    import webui
    rounds = []
    for i in range(10):
        ok = i < 7
        rounds.append({"plats": {"ctrip": {"s": "ok" if ok else "fail",
                                           "detail": 3 if ok else 0, "cal": 0}}})
    out = {"rounds": rounds}
    webui._attach_demo_paths(out)
    node = out["paths"]["ctrip"]
    path = node["paths"]["明细"]
    assert path["attempts"] == 10, "失败轮未计入通路分母"
    assert path["ok"] == 7
    assert node["query_rate"] == path["rate"], "徽标口径与通路口径不一致"

    # 维护轮不进分母
    out2 = {"rounds": [{"plats": {"fliggy": {"s": "maint", "detail": 0, "cal": 0}}},
                       {"plats": {"fliggy": {"s": "ok", "detail": 0, "cal": 3}}}]}
    webui._attach_demo_paths(out2)
    n2 = out2["paths"]["fliggy"]
    assert n2["query_attempts"] == 1, "维护轮被算进查询分母"
    assert n2["query_rate"] == 1.0

def test_demo_paths_and_health_share_one_aggregation():
    """健康卡与节流面板必须读同一份分通路账。

    演示的 /api/paths 曾恒返回 platforms={}，于是同一页上健康卡写着
    「明细 97%」而节流面板写「按轮判定 · 明细 0 / 日历 0」——两个面板
    对同一渠道给出互相否定的结论。现在两条接口共用 _demo_paths_from_rounds。
    """
    import webui
    src_py = open("webui.py", encoding="utf-8").read()
    i = src_py.index("def _paths_payload(")
    seg = src_py[i:src_py.index("def _exit_check(", i)]
    demo_seg = seg[seg.index("if demo:"):seg.index("\n    try:", seg.index("if demo:"))]
    assert "_demo_paths_from_rounds(" in demo_seg, \
        "演示 /api/paths 未复用健康卡的聚合函数"
    assert '"platforms": {}' not in demo_seg, \
        "演示 /api/paths 又返回空 platforms（面板会退回「按轮判定」）"

    # 同一批轮次 → 两份载荷的分通路账逐字相同
    from core.demo import demo_health
    rounds = (demo_health() or {}).get("rounds") or []
    direct = webui._demo_paths_from_rounds(rounds)
    via_health = {}
    webui._attach_demo_paths({"rounds": rounds, "__x": via_health})
    assert webui._paths_payload(24, demo=True)["platforms"] == direct
    assert direct and set(direct) == {"qunar", "ctrip", "fliggy",
                                      "tongcheng", "tuniu"}


def test_demo_path_exposes_query_level_detail_calendar_split():
    """节流行右半写「查询 93% · 明细 93 / 日历 0」。

    演示聚合曾只给 query_attempts/query_rate，缺 query_detail_ok /
    query_calendar_only，前端于是渲染成「查询 93% · 明细 0 / 日历 0」：
    同一个 93% 旁边摆着 0，读起来像「一条明细都没拿到」。生产
    path_stats 是同名同义的字段，演示必须补齐。
    """
    import webui
    rounds = []
    for i in range(10):
        if i < 6:
            rounds.append({"plats": {"ctrip": {"s": "ok", "detail": 3, "cal": 0}}})
        elif i < 8:
            rounds.append({"plats": {"ctrip": {"s": "ok", "detail": 0, "cal": 2}}})
        else:
            rounds.append({"plats": {"ctrip": {"s": "maint", "detail": 0, "cal": 0}}})
    node = webui._demo_paths_from_rounds(rounds)["ctrip"]
    assert node["query_attempts"] == 8, "维护轮混进了查询分母"
    assert node["query_detail_ok"] == 6
    assert node["query_calendar_only"] == 2
    assert node["query_ok"] == 8
    assert node["query_detail_ok"] + node["query_calendar_only"] <= node["query_ok"]

    src = open("webui.py", encoding="utf-8").read()
    assert "query_detail_ok" in src and "query_calendar_only" in src


def test_calendar_path_label_is_not_doubled():
    """通路名本身已含「日历」，后面不能再拼一次「日历N」。

    实测渲染成「日历14 · 查询 100% · 明细 0 / 日历 14」，同一行两次
    说「日历」；台数改用 ×N 承接，通路名只出现一次。
    """
    src = open("webui.py", encoding="utf-8").read()
    assert "'日历'+cal" not in src, "通路名与台数重复拼「日历」"
    # r659 起通路名统一走 pathCN()，锚点跟着改；守的仍是「台数以 ×N 出现」
    i = src.index("pws.push(pathCN(pp)+' '")
    seg = src[i:i + 120]
    assert "'×'+cal" in seg, "日历通路台数未改成 ×N 形态"

def test_metric_strip_gutters_are_not_a_background_fill():
    """量尺的 1px 分隔不能靠容器底色透出。

    容器 `background:var(--r-hair)` + `flex-wrap` 时，首行没排满的
    那段空白也继承了底色——420/360 档实测是一块 354×54 的灰砖，
    看着像第 5 个空格子。

    r473e 起分隔改为**格子自绘 `border-left` 发丝竖线**（首格不带），
    而不是 box-shadow 描边——竖线更贴近表格式语言，也不会在格子间形成
    「白底 + 一圈边」的卡中卡。守的是**意图**：容器不得用底色透缝、
    格子必须自己画出分隔、且首格不画。
    """
    src = open("webui.py", encoding="utf-8").read()
    i = src.index(".pace-stats{")
    seg = src[i:i + 260]
    assert "background:transparent" in seg, "量尺容器仍用底色透缝（窄屏会露灰砖）"
    assert "background:var(--r-hair)" not in seg
    j = src.index(".pace-stat{")
    cell = src[j:j + 320]
    assert ("border-left:1px solid var(--r-hair)" in cell
            or "box-shadow:0 0 0 1px var(--r-hair)" in cell), \
        "格子未自绘分隔（既无发丝竖线也无描边）"
    # 首格不能带竖线，否则最左侧多一条「像是被切了一刀」的边
    assert ".pace-stat:first-child{border-left:0}" in src or \
        ".pace-stat:first-child" in src, "首格未去掉竖线"


def test_metric_strip_wraps_two_by_two_only_on_phones():
    """4 格 96px 在 420/360 只能排 3 格，剩 1 格掉第二行（实测 3+1）。
    480 以下改等分 2×2；480 以上必须仍是按内容收宽的紧凑条——
    768 档若也走两列会被拉成 351px，等于退回「3 字内容漂在大格子里」。"""
    src = open("webui.py", encoding="utf-8").read()
    i = src.index("@media(max-width:480px){")
    seg = src[i:i + 460]
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in seg, \
        "窄屏量尺未改 2×2"
    assert ".pace-stat{min-width:0" in seg, "2×2 格仍带 min-width，会撑破列"

    # 负控：900 断点区间里 .pace-stats 不得也用 2×2（否则 768 档被拉宽）。
    # 只看 .pace-stats 自身规则——区间里别处的 repeat(2,…) 与本面板无关。
    a = src.index("@media(max-width:900px){")
    b = src.index("@media(max-width:480px){", a)
    mid = src[a:b]
    assert ".pace-stats{display:grid" not in mid, \
        "900 断点里 .pace-stats 也走 2×2，768 档格子会被拉成 351px"
    assert ".pace-stats" not in mid or "repeat(2,minmax(0,1fr))" not in \
        mid.split(".pace-stats")[1][:200], "900 断点里 .pace-stats 被改成两列"

def test_scope_rate_shares_query_basis_with_the_right_half():
    """同一行里分域与查询率必须能互相核对。

    去哪儿真实数据（24h）：国内查询 39/39=100%、国际 24/38=63%、
    合计 63/77=82%。旧实现分域读 `attempts/rate`（尝试级 95%/62%），
    于是渲染成「国内 95% · 国际 62% · 查询 82%」——三个数没有一个对得上，
    用户没法判断哪一端真的坏了。分域改读 query_rate_live（与徽标同源）。
    """
    src = open("webui.py", encoding="utf-8").read()
    i = src.index("const scoped=(name,label)=>{")
    seg = src[i:i + 520]
    assert "query_rate_live" in seg, "节流分域未用查询口径（与查询率不可核对）"
    assert "query_attempts_live" in seg, "节流分域分母未用查询口径"
    assert "s1.rate" not in seg, "节流分域仍在读尝试级 rate"

    # 健康卡的分域小标同理：读 scopes 节点的 rate 会与徽标口径打架
    j = src.index("for(const _k of ['domestic','international']){")
    hseg = src[j:j + 620]
    assert "query_rate_live" in hseg, "健康卡分域小标未用查询口径"
    assert "_q.rate" not in hseg, "健康卡分域小标仍在读尝试级 rate"

    # 负控：查询口径存在时不得回落到尝试级
    import re
    assert re.search(r"query_attempts_live[^\n]*query_attempts", seg), \
        "节流分域未按 live 优先 / 原口径回落"


def test_scope_numbers_reconcile_with_total():
    """把真实口径的三段数代进去，分域能加总回查询率（防止再退回混口径）。"""
    dom_q, dom_a = 39, 39      # 国内：查询成功/尝试
    intl_q, intl_a = 24, 38    # 国际
    total_q, total_a = 63, 77  # 徽标/查询率同源
    assert dom_q + intl_q == total_q
    assert dom_a + intl_a == total_a
    assert round(total_q / total_a * 100) == 82
    assert round(dom_q / dom_a * 100) == 100
    assert round(intl_q / intl_a * 100) == 63

def test_dead_surface_is_named_for_multi_slot_vendor():
    """飞猪 PC/H5 双槽时，「飞猪需登录」会吞掉「是哪一端掉了」。

    真的跑 _attach_diag_slots（只替 _login_state_view），要求：
    1) 多槽厂商产出 dead_surfaces 且只点名失效那一端；
    2) slot_action 直达该端槽位（不能默认指向厂商级窗口）；
    3) 单槽厂商不产出 dead_surfaces（否则每行都多一段噪声）。
    """
    import webui
    ls = {"slots": {
        "fliggy": {"plat": "fliggy", "surface": "PC", "needs_login": False,
                   "status": "active"},
        "fliggy_h5": {"plat": "fliggy", "surface": "H5", "needs_login": True,
                      "status": "login_required"},
        "ctrip": {"plat": "ctrip", "surface": "PC", "needs_login": True,
                  "status": "login_required"},
    }}
    orig = webui._login_state_view
    webui._login_state_view = lambda *a, **k: ls
    try:
        out = {"diag": [{"plat": "fliggy", "kind": "login", "label": "登录态失效"},
                        {"plat": "ctrip", "kind": "login", "label": "登录态失效"}]}
        webui._attach_diag_slots(out)
    finally:
        webui._login_state_view = orig

    fg, ct = out["diag"]
    assert fg.get("dead_surfaces") == ["H5"], "未点名失效端：%r" % fg.get("dead_surfaces")
    assert fg.get("slot_action") == "fliggy_h5", "未指向失效槽位：%r" % fg.get("slot_action")
    assert "dead_surfaces" not in ct, "单槽厂商不该有 dead_surfaces"
    assert "slot_action" not in ct
    assert len(fg.get("slots") or []) == 2

    # 前端：结论把端名并进 label，按钮写「打开登录 H5」并指向该槽位
    src = open("webui.py", encoding="utf-8").read()
    i = src.index("const _dead=(c.dead_surfaces||[])")
    seg = src[i:src.index("}).join('');", i)]
    assert "_surfTxt+c.label" in seg, "诊断结论未把失效端并进标签"
    assert "c.slot_action||c.plat" in seg, "按钮目标未优先取 slot_action"
    assert "'打开登录 '+_dead[0]" in seg, "按钮未点名该端"

def test_multi_slot_login_button_onclick_points_at_the_slot():
    """既有契约只查了按钮**文案**「去登录 H5」，没查它真的跳到哪。

    文案对、目标错是最隐蔽的一类：按钮写着 H5，onclick 仍传厂商级
    key，点开的是 PC 窗。这里钉死 onclick 实参必须是选中的那一端
    （r477：路径证据优先，其次失效槽位）。
    """
    seg = _pacing_seg()
    i = seg.index("if(_own2.length>1){")
    block = seg[i:i + 1200]
    # 源码里 onclick 跨行拼接：onclick="srxGoLogin(\'' 换行 +_slot+'\')"
    assert 'onclick="srxGoLogin(\\\'' in block, \
        "多槽位按钮的 onclick 未走 srxGoLogin"
    assert "+_slot+" in block, \
        "多槽位按钮未把 _slot 作为 onclick 实参"
    assert "const _bad2=_own2.filter(" in block, \
        "缺「失效那一端」的兜底候选"
    assert "_byPath||(v.needs_login?(_bad2[0]||null):null)" in block, \
        "未按「路径证据 → 失效槽位」的顺序选端"


def test_retired_path_is_marked_not_silently_dropped():
    """退役通路必须留在行内并标「退役」。

    同程把国际从「日历」换成「窗历」后，旧通路恒失败但仍在 24h 窗口里。
    静默丢掉会让读者以为那条路从没存在过，也看不出「换过路」。
    合约：退役通路 push 成「<名> 退役」，且不得再当成在用通路算一次成功率。
    """
    seg = _pacing_seg()
    # r659：通路名走 pathCN()，锚点跟着改；守的仍是「退役留在行内并标退役」
    assert "dead.forEach(pp=>pws.push(pathCN(pp)+' 退役'))" in seg, \
        "退役通路未在速览里标出"
    i = seg.index("Object.keys(pw).forEach(pp=>{")
    block = seg[i:i + 260]
    assert "dead.indexOf(pp)>=0" in block, \
        "退役通路仍被当成在用通路算成功率（同一通路出现两次）"

def test_demo_masks_synthetic_percentages_but_real_path_keeps_them():
    """演示态与真实态必须走不同分支，且都不能退化成「只有厂商一个数」。

    背景：`--demo` 的百分比是按合成轮次迭代算的，读起来与真实实测一模一样，
    用户实报「很多都是补位数据」。于是演示侧 `pathTxt`/`_qbit` 都置空，
    只写「合成样本 · 不参与成功率」。
    风险：这个屏蔽很容易顺手写宽，把**真实实例**的分域/分通路一起抹掉——
    那就回到了「渠道健康只有厂商单一维」这个原始问题。所以两侧各钉一条。
    """
    src = open("webui.py", encoding="utf-8").read()
    # 演示侧：两半都要被「合成样本」判据拦掉（r466 起判据是 _maskSynth，
    # 因为只看 advice 会把真账本一起遮掉）
    i = src.index("const pathTxt=")
    assert "_maskSynth?'':" in src[i - 20:i + 120], \
        "演示态未屏蔽合成通路串"
    j = src.index("const _qbit=")
    seg = src[j:j + 400]
    assert "_maskSynth" in seg, "演示态未屏蔽合成查询率"
    # 演示态不得给出**可被引用的合成读数**。r496 起 `_qbit` 直接置空，
    # 由行内证据（`合成 · 未实测`）与结论行承担「这是合成样本」的说明——
    # 5 行各写一遍「合成样本 · 不参与成功率」会让每行多占 17px。
    # 守意图：必须是空串或自述合成，二者之一；绝不能落回真实百分比分支。
    assert "?('')" in seg or "合成样本" in seg, \
        "演示态既未置空、也未说明样本性质（会给出可被引用的合成读数）"

    # 真实侧：分域仍用查询口径、分通路仍逐条给率
    k = src.index("const scoped=(name,label)=>{")
    sseg = src[k:k + 520]
    assert "query_rate_live" in sseg and "s1.rate" not in sseg, \
        "真实态分域口径跑偏（不再是查询口径）"
    # 同名循环在文件里有多处（诊断降级那段也有 Object.keys(pw).forEach），
    # 必须从 pws 收集处取，否则取样落到别的循环上、断言恒真/恒假。
    m = src.index("const pws=[];")
    assert "_rate(w.rate)" in src[m:m + 420], "真实态分通路未给逐通路成功率"
    assert "'×'+cal" in src[m:m + 420], "日历通路台数未用 ×N 承接"

def test_warmup_row_lists_every_channel_instead_of_hiding_unsupported():
    """预热只对声明了 warmup_url 的渠道生效（当前 qunar/fliggy/tuniu）。

    旧实现直接 `.map(WARM)`，把 ctrip / tongcheng 从按钮行里删掉——用户
    看到「预热 3 个 / 自检 5 个」，会以为面板漏渲染，或者以为这两家连
    入口都没有。这正是「多渠道状态区分没做好」的典型：不可用也是一种
    状态，必须显式呈现，而不是消失。
    """
    src = open("webui.py", encoding="utf-8").read()
    i = src.index("const WARM=")
    seg = src[i:i + 900]
    assert "PROBE.map(" in seg, "预热行未遍历全部渠道（仍只渲染可预热的那几家）"
    assert "disabled" in seg and 'aria-disabled="true"' in seg, \
        "无预热入口的渠道未标不可用"
    assert "未配置预热入口" in seg, "不可用原因未写明（只剩一个灰按钮）"
    # 不可用按钮不得挂 onclick（否则点了没反应）。只取该按钮自身那一段，
    # 不能按固定长度往后截——会吃到后面「全部」按钮的 onclick。
    a = seg.index(':(\'<button type="button" class="na"')
    b = seg.index("</button>')", a)
    assert "onclick" not in seg[a:b], "不可用按钮仍绑了 onclick"


def test_warm_all_uses_the_same_cfg_list_as_buttons():
    """「全部」不能写死三家，否则配置改了以后与逐个按钮覆盖面不一致。"""
    src = open("webui.py", encoding="utf-8").read()
    i = src.index("async function warmAll(){")
    seg = src[i:i + 620]
    assert "PACE_CFG" in seg, "warmAll 未读配置里的预热清单"
    assert "['qunar','fliggy','tuniu']" not in seg, "warmAll 仍写死三家"
    # PACE_CFG 要有声明与赋值，否则运行期 ReferenceError
    assert "let PACE_CFG" in src, "PACE_CFG 未声明"
    assert "PACE_CFG=cf" in src, "PACE_CFG 未在 loadPacing 里赋值"

def test_recurrence_note_clamps_to_two_lines_on_narrow():
    """复发备注要「读得到结论」，又不能把面板撑高。

    两次踩坑：一开始窄屏 200 字备注撑成 3 行，5 条吃掉 680px；
    改成一律 nowrap 后，真实备注被切——实测「国际列表 1999/8 连续 7 次
    未放行（疑会话失效）」在 420 档只露出 226/323px（丢 97px）、360 档丢
    157px，而这句正是判断「要不要人工介入」的依据。
    正解：窄屏 -webkit-line-clamp:2，最坏高度钉死两行；宽屏维持单行。
    """
    src = open("webui.py", encoding="utf-8").read()
    i = src.index(".pace-rec .what .h{white-space:normal")
    seg = src[i:i + 320]
    assert "-webkit-line-clamp:2" in seg, "复现备注未限制为两行"
    assert "overflow:hidden" in seg
    assert "overflow-wrap:anywhere" in seg, "长串英文/URL 会撑破容器"
    # 宽屏仍应单行（不然一行两行的观感不一致）
    j = src.index(".pace-rec .what .h{display:block")
    wide = src[j:j + 220]
    assert "nowrap" in wide, "宽屏复发备注不再是单行"

    # 回归旧坑的负控：不得再出现「一律 nowrap」的窄屏覆盖
    a = src.index("@media(max-width:900px){")
    b = src.index("@media(max-width:480px){", a)
    assert ".pace-rec .what .h{white-space:nowrap}" not in src[a:b], \
        "窄屏又退回一律 nowrap（真实备注会被切掉）"

def test_css_rules_are_syntactically_valid():
    """CSS 少一个括号/选择器，浏览器会静默丢弃其后所有规则。

    实测事故：`:is(.btn2,{...}`（第二个选择器缺失）出现在样式表中段，
    其后整张表的 125 条 `.pace*` 规则全部未被解析——节流面板从「台账」
    退化成裸文字 + 蓝色实心按钮，而 pytest 全绿、UI 用例也全绿
    （用例只查 DOM 结构与文本，查不出 CSS 没生效）。
    这里做最小词法检查：括号配平 + 不得出现 `,{` 这种空选择器。
    """
    import re
    src = _src()
    css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", src, re.S))
    assert css, "没抓到内联样式表"
    # 去掉注释再数括号
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert body.count("{") == body.count("}"), \
        "CSS 大括号不配平（%d { vs %d }）" % (body.count("{"), body.count("}"))
    # 空选择器：`:is(.a,{`、`,,`、`{,`
    assert not re.search(r",\s*\{", body), "存在空选择器（如 :is(.a,{）"
    # 每条规则至少有一个字符的选择器
    for m in re.finditer(r"(^|\})\s*([^{}@/]+?)\s*\{", body):
        sel = m.group(2).strip()
        if sel.startswith("@"):
            continue
        assert sel, "存在空选择器规则"


def test_pacing_stylesheet_actually_applies():
    """把「规则是否被浏览器采纳」也钉进契约。

    源码里有 `.pace-row .ac button{...}` 不代表它生效：前面任何一条语法
    错误都会让它被丢弃。所以这里断言节流面板的关键选择器在样式表里
    真实可见（用静态切片近似 CSSOM，规则必须成对出现在同一张表里）。
    """
    import re
    src = _src()
    for sel in (".pace-row .ac button{", ".pace-row .ac{",
                ".pace-stats{", ".pace-rec{"):
        assert sel in src, "节流关键规则缺失：" + sel
    # 坏写法必须绝迹（就是它把后面全吞了）
    assert ":is(.btn2,{" not in src, \
        "又出现 :is(.btn2,{ 这种空选择器（会吞掉其后的全部 CSS）"

def test_intervention_effect_is_surfaced_on_the_row():
    """最高准则：界面要帮用户做「能提高成功率」的操作。

    唯一能回答「按哪个钮有用」的证据是「上次同类干预带来了什么」——
    同程实测 44%→100%（121 次样本）、去哪儿 44%→71%。这段原本只在点开
    「溯源」后才看得到，等于把决策依据藏在二级页。现在前置到行内。
    约束：
    1) 只在两侧都有真实样本、且变化 ≥5pp 时出现（否则噪音当成效）；
    2) 回落也要说，并提示「先别急着重按」；
    3) 必须带样本数，避免拿 2 次采样当结论。
    """
    seg = _pacing_seg()
    assert "const EFF=j.effect||{}" in seg, "未取干预成效"
    i = seg.index("const _ef2=EFF[k]")
    block = seg[i:i + 900]
    assert "_ef2.has" in block and "_ef2.before!=null" in block and "_ef2.after!=null" in block, \
        "未校验两侧都有样本"
    assert "Math.abs(_ef2.after-_ef2.before)>=0.05" in block, "未设最小变化幅度"
    assert "上次" in block and "%→" in block, "未写出「上次X a%→b%」"
    assert "回落" in block, "回落情形未提示"
    assert "_ef2.after_n" in block, "未带样本数"

    # 动作名要翻成人话，不能直接把 probe/warmup 抛给用户
    assert "probe:'自检'" in block and "warmup:'预热'" in block, "动作名未本地化"

def test_config_view_is_not_pinned_to_control_height():
    """`#cfgview` 是整页容器，不能被写成 30px 的小控件。

    实测事故：`#cfgview{…height:30px;padding:0 10px}`（选择器被截断，
    原本是某个 30px 输入/按钮的样式）落到容器上后——
      · #cfgview 实测高度 30px，而子内容 945px（内容溢出容器）
      · .wrap 因此只有 210px 高，sticky 约束盒塌陷
      · header 一滚就走（top=-248），cfgnav 吸顶 gap 变成 252px
    容器高度必须由内容撑开；sticky 的一切偏移都建立在这个前提上。
    """
    src = _src()
    import re
    # 先剥注释：修复说明里会引用坏写法原文（`#cfgview{…height:30px}`），
    # 不剥会把注释当成真规则，恒红。
    css = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    # 逐条扫「选择器集合以 #cfgview 结尾」的规则。用 find/index 而不是
    # 大范围正则——CSS 是超长单行文本，`[^{}]*#cfgview` 会回溯到卡死。
    pos = 0
    while True:
        i = css.find("#cfgview", pos)
        if i < 0:
            break
        pos = i + 8
        # 找到这条规则的 { 与 }，且选择器里不能夹着 { （说明 #cfgview 在子选择器位）
        ob = css.find("{", i)
        if ob < 0:
            break
        prev_ob = css.rfind("{", 0, i)
        prev_cb = css.rfind("}", 0, i)
        if prev_ob > prev_cb:
            continue          # #cfgview 位于某规则体内 → 是子选择器，跳过
        cb = css.find("}", ob)
        if cb < 0:
            break
        sel = css[max(prev_cb + 1, 0):ob].strip()
        if not sel.endswith("#cfgview") and sel != "#cfgview":
            continue          # 形如 `#cfgview .cw-item` → 不是容器自身
        body = css[ob + 1:cb]
        assert "height:" not in body.replace("min-height:", "").replace(
            "max-height:", ""), \
            "容器 #cfgview 被写死高度：%r" % body[:90]
        assert "padding:0 10px" not in body, "#cfgview 被当成小控件设置内边距"

def test_path_degraded_names_the_worst_path_with_samples():
    """只说「国际端偏低」等于没说：用户不知道是哪条路、差多少、该不该管。

    真实数据（去哪儿 24h）：国际 H5 只有 25%（32 次），而同渠道国内 H5
    是 80%（15 次）——同一通路在两个域表现天差地别。这条必须点名到
    「域 + 通路 + 有效率 + 样本数」，否则用户既做不出判断，也无从干预。
    样本门槛 5：32 次的 25% 和 3 次的 25% 完全不是一回事。
    """
    seg = _pacing_seg()
    i = seg.index("else if(adv.state==='path_degraded')")
    # 按**分支边界**截块，不用固定字符数：r635 在这段里补了口径说明与
    # 重试分支，2200 字符窗口够不到后面的通路下钻，会误判成「未下钻」。
    nxt = seg.find("else if(adv.state==='", i + 10)
    block = seg[i:nxt if nxt > 0 else i + 4000]
    assert "s1.paths" in block, "未下钻到分域内的通路"
    assert "n>=5" in block, "未设样本门槛（3 次也当成劣化）"
    assert "0.6" in block, "未设劣化阈值"
    assert "'国内':'国际'" in block, "未标明是哪个域"
    # 样本数不再挂在 e1 上（r640 起 e1 只点名「哪条路」，百分比与次数由
    # 右半 pws / 行 title 承担），但**行内仍必须能看到次数**。
    src = _src()
    assert "（'+n+' 次" in src or "（'+n+' 次）" in src or         "'（'+n+' 次" in src or "+' 次'" in src or "' 次'" in src, (
        "通路小标/速览里看不到样本数")

def test_intervention_buttons_are_idempotent_and_recover():
    """连点「预热」会串行真打多次首页。

    `channel_slot` 是**互斥锁不是去重**：实测连点 3 次 → 3 个
    /api/channel/warmup 请求。自检更贵（10–60 秒），连点会叠风控、烧预算，
    反而把成功率打低。契约：
      1) 在途时同名干预直接忽略（PACE_BUSY 键 warm:<p> / probe:<p>）；
      2) 完成后必须把按钮 disabled 复位——只清在途表不解锁，按钮会永久灰着
         （实测完成后 disabled 仍为 true），想再预热得等面板重建。
    """
    src = _src()
    assert "const PACE_BUSY={}" in src, "缺少在途干预表"
    for fn, key in (("async function warmNow(p){", "'warm:'+p"),
                    ("async function probeNow(p){", "'probe:'+p")):
        i = src.index(fn)
        head = src[i:i + 520]
        assert ("if(PACE_BUSY[" + key + "])return;") in head, fn + " 未防重复"
        assert ("PACE_BUSY[" + key + "]=1;") in head
        assert "disabled=true" in head, fn + " 未禁用按钮"
        tail = src[i:i + 2600]
        assert "delete PACE_BUSY[" + key + "]" in tail, fn + " 未释放"
        assert "disabled=false" in tail, fn + " 完成后未恢复按钮（会永久灰着）"

    # 整批同样要防重
    j = src.index("async function warmAll(){")
    assert "if(PACE_BUSY['warm:all'])return;" in src[j:j + 600]
    assert "delete PACE_BUSY['warm:all']" in src[j:j + 1400]
    k = src.index("async function probeAll(){")
    assert "if(PACE_BUSY['probe:all'])return;" in src[k:k + 700]
    assert "delete PACE_BUSY['probe:all']" in src[k:k + 1400]

def test_health_penalty_can_be_switched_off():
    """熔断有 breaker_enabled、预热有 warmup_enabled，自动降频却没有开关。

    降频会把 TTL 拉长 3 倍，遇到「宁可多打也不接受变慢」的场景（例如临近
    起飞、必须刷到最新价）用户完全没法关，只能用改配置文件的野办法。
    契约：开关存在、能在配置页切换、关掉后 penalty 恒 1 但仍记录 rate
    （界面要显示成功率），且节流台账头要写「已关闭」而不是「无」——
    「无」会被读成「当前没有渠道被降频」，让人以为保护还在。
    """
    import core.pacing as P_
    assert "health_penalty_enabled" in P_.DEFAULTS, "缺默认开关"
    # 缺省开
    assert P_.parse_pacing({})["health_penalty_enabled"] is True
    assert P_.parse_pacing(
        {"crawler": {"health_penalty_enabled": False}})[
        "health_penalty_enabled"] is False

    on, off = P_.Pacing({}), P_.Pacing(
        {"crawler": {"health_penalty_enabled": False}})
    on.set_health("qunar", 0.25, 40)
    off.set_health("qunar", 0.25, 40)
    assert on._health["qunar"]["penalty"] == 3.0, "开启时未降频"
    assert off._health["qunar"]["penalty"] == 1.0, "关闭后仍在降频"
    assert off._health["qunar"]["rate"] == 0.25, "关闭后丢了成功率记录（界面要显示）"

    src = _src()
    assert "glbHpen" in src, "配置页缺开关控件"
    assert "GLB.health_penalty_enabled=this.checked" in src, "开关未绑定"
    # 回读/写回在服务端 Python 里，PAGE 不含，必须读源文件
    import pathlib
    _raw = pathlib.Path(ROOT, "webui.py").read_text(encoding="utf-8")
    assert '"health_penalty_enabled": bool(' in _raw, "未回读配置"
    assert '_crw["health_penalty_enabled"]' in _raw, "未写回配置"
    i = src.index("if(cf.health_penalty_enabled===false)")
    assert "已关闭" in src[i:i + 220], "关闭时未在台账头说明"

def test_diag_card_offers_probe_button_when_it_advises_probe():
    """卡片写「需真实明细请发起探针」，却只有「自检」一个按钮。

    「自检」走 `/api/channel/selfcheck`，只查登录态与卡片判定，**不跑真实
    查询**；真要拿到明细得走 `/api/channel/probe`。用户读完建议找不到
    对应动作，等于「可判断但不可干预」。
    契约：动作文案提到「探针」时，卡片必须多给一个「发起探针」按钮，
    且它调的是真探针（复用 probeNow，带幂等）。
    """
    src = _src()
    # 用 ASCII 锚点：本机 pytest 进程对源码里的中文字面量比较不稳定
    # （实测同一段内容 "  in PAGE" 在独立脚本里为 True、在整文件跑时失败），
    # 所以只锚结构，不依赖中文匹配。
    assert "const probe=(String(c.action||" in src, "未按动作文案决定是否给探针按钮"
    assert "diagProbe(" in src, "未接点击处理"
    assert "btn+probe+self" in src, "探针按钮未挂进动作区"
    assert "data-diagprobe=" in src, "探针按钮缺少定位属性"
    i = src.index("async function diagProbe(p){")
    seg = src[i:i + 260]
    assert "await probeNow(p)" in seg, "未复用真探针（会绕过幂等与结果展示）"
    assert "renderHealthDiag()" in seg, "探针后未刷新卡片结论"

def test_demo_mask_follows_server_flag_not_advice_alone():
    """同一页两个面板必须能对上数。

    演示站 advice 全是「演示数据」，但 `/api/paths` 可能给真库（运维把演示页
    接到真库时）。旧实现只看 advice 就判定「该遮」，于是真账也被遮成
    「合成样本 · 不参与成功率」——实测去哪儿国际 H5 真实 0/24、查询率 11%，
    健康卡显示 11%，节流面板却写「不参与成功率」，两个数打架，
    用户无法判断 11% 到底是真问题还是演示噪音。
    判据：遮不遮由服务端 `demo` 标记决定，不靠 paths 的形状去猜。
    """
    seg = _pacing_seg()
    assert "_pthDemo=!!_pj.demo" in seg, "未读取服务端 demo 标记"
    i = seg.index("const _maskSynth=")
    assert "_demoAll&&_pthDemo" in seg[i:i + 60], \
        "遮蔽条件不再同时要求「advice 是演示」且「账本也是合成」"
    # 两处遮蔽点都要换成 _maskSynth
    assert "const pathTxt=_maskSynth?'':" in seg, "通路串未改用新判据"
    assert "const _qbit=_maskSynth" in seg, "查询率未改用新判据"
    # 状态胶囊仍应按 advice 判「演示」，不能因为账本真就把状态也说成正常
    assert "_demoAll&&v.state==='ok'" in seg, "状态胶囊的演示判定被误改"

def test_ledger_login_wall_becomes_actionable_relogin():
    """被登录墙反复拦住时，「观察一轮」是错建议。

    真实数据：去哪儿国际 H5 24h 内 18/23 次 login、0 成功，而国内 H5 全绿。
    旧实现只看运行时熔断（`ch["needs_login"]`），从不读账本里的 login 计数，
    于是 advise 给出 `degraded / wait / 观察一轮`——用户白等 9 小时，
    而真正能救成功率的动作（重存会话）从头到尾没被提示。
    """
    from core.pacing import advise
    node = {"scopes": {"dom": {"paths": {"H5": {
        "attempts": 3, "login": 0, "empty": 3, "rate": 0.0,
        "last_at": "2026-10-28 10:00:00"}}},
        "intl": {"paths": {"H5": {
            "attempts": 23, "login": 18, "empty": 0, "rate": 0.0,
            "rate_excl_empty": 0.0,
            "last_at": "2026-10-28 10:00:00"}}}},
        "paths": {"H5": {"attempts": 26, "rate": 0.115}},
        "query_attempts": 26, "query_rate": 0.115}
    a = advise("qunar", paths={}, node=node,
               now=__import__("time").mktime(
                   (2026, 10, 28, 12, 0, 0, 0, 0, -1)))
    assert a["state"] == "login", a
    assert a["action"] == "relogin", a
    assert a["severity"] == "act", a
    assert "18/23" in a["hint"] or "18/26" in a["hint"], a["hint"]
    assert "仅 0 次" in a["hint"] or "仅" in a["hint"], a["hint"]

    # 负控 2：登录拦截占多数，但同一通路其他航线仍在出数 → 会话是好的，
    # 不得让用户去重登（重登解决不了航线级拦截）。
    node3 = {"scopes": {"intl": {"paths": {"H5": {
        "attempts": 50, "login": 30, "ok": 18, "calendar": 0,
        "rate": 0.36, "rate_excl_empty": 0.36,
        "last_at": "2026-10-28 10:00:00"}}}},
        "paths": {"H5": {"attempts": 50, "rate": 0.36}},
        "query_attempts": 50, "query_rate": 0.36}
    a3 = advise("qunar", paths={}, node=node3,
                now=__import__("time").mktime(
                    (2026, 10, 28, 12, 0, 0, 0, 0, -1)))
    assert a3["state"] != "login", a3
    assert a3["action"] != "relogin", a3
    assert "别急着重登" in a3["hint"], a3["hint"]

    # 负控：login 占比不高时不得误报（国内 3 次 empty 不该说登录）
    node2 = {"scopes": {"dom": {"paths": {"H5": {
        "attempts": 30, "login": 2, "rate": 0.9, "rate_excl_empty": 0.9,
        "last_at": "2026-10-28 10:00:00"}}}},
        "paths": {"H5": {"attempts": 30, "rate": 0.9}},
        "query_attempts": 30, "query_rate": 0.9}
    a2 = advise("qunar", paths={}, node=node2,
                now=__import__("time").mktime(
                    (2026, 10, 28, 12, 0, 0, 0, 0, -1)))
    assert a2["state"] != "login", a2


def test_login_advice_reaches_the_pacing_row():
    """后端判对但界面落「正常」时，用户仍然没有动作可做。

    实测链路断点：advise 返回 login/relogin/act，节流行却不认
    `adv.state==='login'`（只认运行时 `v.needs_login`），于是打出
    「正常 —」且没有登录按钮。契约：状态分支与按钮条件都要含 adv 判定，
    并把后端 hint 里的量化证据（18/23）带进证据列。
    """
    seg = _pacing_seg()
    assert "else if(v.needs_login||adv.state==='login')" in seg, \
        "状态分支未认账本级登录"
    assert "if(v.needs_login||adv.state==='login'||" in seg, \
        "按钮条件未认账本级登录"
    assert "String(adv.hint).split(/[—；]/)[0]" in seg, \
        "未把量化证据带进证据列"

def test_ok_row_never_claims_no_samples_when_ledger_is_real():
    """演示页接真库时，ok 行不能说「无真实样本」，也不能落破折号。

    实测同程 24h 有 45 次真实采样、H5 明细 9 条，界面却写「无真实样本」；
    改成干净兜底后又整行落「—」——而 — 在本面板专指「无样本」，
    与同一行右侧「查询 100% · 明细 9 / 日历 36」直接打架。
    现规则：账本为真时，ok 行用账本事实自述「实测 N 次、出数 M 条」，
    且出数明显少于尝试时要把差额说出来（去哪儿 24 次只出 3 条 =
    87% 未出数，只写「出数 3 条」会被读成基本正常）。
    """
    seg = _pacing_seg()
    assert "if(!ev&&_demoAll&&_pthDemo)ev=" in seg,         "「无真实样本」未加账本来源限定"
    i = seg.index("if(!ev&&adv.state==='ok'&&!_pthDemo){")
    # 窗口按语句结尾截，不写死长度（注释一长就会把代码挤出窗口，实测踩过）
    block = seg[i:seg.index("\n   }", i) + 6]
    assert "'近 24h 实测 '" in block, "ok 行未用账本事实自述"
    assert "_qo*4<_qa*3" in block, "未在出数明显偏少时说明差额"
    assert "% 未出数" in block

def test_stale_row_explains_how_long_and_names_right_half_basis():
    """「数据陈旧」旁边写着「查询 100%」，读者无法理解。

    实测四家渠道同时显示「数据陈旧 | 最近成功 10-28 14:34」，右半却是
    「查询 100% · 明细 65 / 日历 0 · 65 次」——左边说陈旧、右边说满分。
    时间戳本身不算错，但读者算不出「停了多久」，也不知道右半是停更前的
    历史统计。现改为「已停 7 小时 23 分（右侧为停更前的历史口径）」。
    """
    seg = _pacing_seg()
    i = seg.index("else if(adv.state==='stale')")
    block = seg[i:i + 900]
    assert "_minsAgo(node.last_ok_at)" in block, "未计算停更时长"
    assert "已停 " in block, "未把停更时长说出来"
    assert "右侧为停更前的历史口径" in block, "未说明右半是历史口径"
    # 解析失败要回落原始时间戳，不能臆造时长
    assert "String(node.last_ok_at).slice(5,16)" in block

    # _minsAgo 定义在 loadPacing 之前，不在 _pacing_seg 的切片里，全文查
    _full = _src()
    j = _full.index("function _minsAgo(ts){")
    fn = _full[j:j + 460]
    assert "return null" in fn, "解析失败未返回 null"
    assert "Date.now()-t" in fn

def test_every_non_ok_state_self_describes():
    """每个非 ok 状态都要自述「为什么」，且兜底不能凭空断言。

    逐个状态实测：cooldown/soft_reject/recovering/calendar_only/degraded/
    unknown/path_degraded/verify_fail 都必须给出证据列文本，不能落「—」
    （— 在本面板专指「无样本」）。
    path_degraded 的兜底尤其要注意：走到兜底说明账本里**没有可用通路样本**，
    此时写「存在低成功率通路」是凭空断言；应说「暂无通路账，先跑一轮再判断」。
    """
    seg = _pacing_seg()
    labels = ["冷却 ", "需登录", "路径劣化", "软拒待预热", "恢复中",
              "仅有日历", "数据陈旧", "成功率低", "待首轮"]
    for lab in labels:
        assert ("lab='" + lab + "'") in seg or ("lab='" + lab.rstrip() + "'") in seg,             "状态标签缺失：" + lab
    assert "'存在低成功率通路'" not in seg,         "path_degraded 兜底仍在凭空断言存在坏路"
    assert "暂无通路账" in seg, "账本缺失时未如实说明"
