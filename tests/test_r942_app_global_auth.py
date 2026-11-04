# -*- coding: utf-8 -*-
"""r942：App 渠道的会话/干预要接进全局面，不能只活在「渠道登录」卡里。

2026-11-04 全链路审计（用户：所有渠道能力要辐射到每个页面）：
  * `channelAuthView()` 只读浏览器 `/api/login-state`，App 会话在
    `/api/app-login/*`；于是健康页「去登录」不亮、导航红点漏报、
    「渠道入口」把已保存的 App 会话画成红灯；
  * 健康行只来自日志里出现过的渠道，已勾选但未扫描的 App 渠道整行消失；
  * 解除/自检/验证端点只认浏览器五家，App 按钮一点就 400「未知渠道」。

这里把四条闭环钉住：App 状态并入全局判据、健康页有完整未扫描行、
App 验证能落到内嵌真机登录、App 自检/解除不再被当未知渠道。
"""
from entry_mon_harness import page, srv, _goto  # noqa: F401


def _open_health(page):
    _goto(page, "#health")
    page.wait_for_timeout(500)


def test_app_session_feeds_global_auth_and_nav_dot(page):
    _open_health(page)
    out = page.evaluate("""async()=>{
      APP_LOGIN_STATE=Object.assign({},APP_LOGIN_STATE,{
        app_zhixing:{saved:true,needs_login:true,status:'expired',detail:'快照已过期'}});
      CHANNEL_STATE=Object.assign({},CHANNEL_STATE,{
        payload:{demo:false,plats:{},slots:{}}});
      const v=channelAuthView('app_zhixing');
      renderHealthLoginAction();renderNavAuthDot();
      const ha=document.getElementById('hauthact');
      const dot=document.getElementById('navAuth');
      return {needs:v.needsLogin,status:v.status,
              haHidden:ha.hidden,haText:ha.textContent,
              haTitle:ha.title,dot:dot.style.display,dotTitle:dot.title};
    }""")
    assert out["needs"] is True and out["status"] == "login_required", out
    assert out["haHidden"] is False, ("健康页「去登录」没有接上 App 会话", out)
    assert "智行" in (out["haText"] + out["haTitle"]), out
    assert out["dot"] != "none" and "智行" in out["dotTitle"], out


def test_health_renders_full_row_for_enabled_unscanned_app(page):
    _open_health(page)
    out = page.evaluate("""async()=>{
      const j=await (await fetch('/api/health',{cache:'no-store'})).json();
      const stats=Object.assign({},j.stats||{});
      delete stats.app_zhixing;
      const enabled=(j.enabled_platforms||[]).slice();
      if(enabled.indexOf('app_zhixing')<0)enabled.push('app_zhixing');
      renderHealth(Object.assign({},j,{stats:stats,enabled_platforms:enabled}));
      const rows=[...document.querySelectorAll('#hbody .hrow')];
      const row=rows.find(r=>/智行\\s*App/.test((r.textContent||'')));
      return row?{text:row.textContent.trim(),
                   icon:!!row.querySelector('img.bic,span.bic'),
                   badge:(row.querySelector('.hbadge')||{}).textContent||'',
                   cells:row.querySelectorAll('.hcells .hc').length}:null;
    }""")
    assert out, "已勾选但未扫描的 App 渠道在健康页整行消失"
    assert out["icon"], ("未扫描行没有官方图标", out)
    assert "未扫描" in out["badge"], out
    assert out["cells"] >= 1, out


def test_app_verify_routes_to_inline_device_login(page):
    _open_health(page)
    opened = page.evaluate("""async()=>{
      const origF=window.fetch,origO=window.appLoginOpen;let got=null;
      window.fetch=async()=>({json:async()=>({ok:false,app_login:true,
        err:'App 渠道没有网页验证窗：请用内嵌真机画面完成登录'})});
      window.appLoginOpen=p=>{got=p};
      try{await verifyNow('app_qunar')}
      finally{window.fetch=origF;window.appLoginOpen=origO}
      return got;
    }""")
    assert opened == "app_qunar", ("App 验证没有落到内嵌真机登录", opened)
    src = _src()
    assert '"app_login": True' in src and "内嵌真机画面" in src, (
        "后端没有把 App 验证路由到内嵌真机登录")


def test_app_is_not_unknown_to_intervention_endpoints():
    src = _src()
    assert "_ALL_PLATS = tuple(PLATFORMS) + tuple(_APP_CHANNELS)" in src, (
        "可干预端点没有从渠道全集派生")
    assert src.count("plat not in _ALL_PLATS") >= 4, (
        "解除/自检/验证/预热仍有端点只认浏览器渠道")
    assert "plat not in PLATFORMS" not in src, (
        "仍有端点把 App 当未知渠道")


def test_special_deals_name_and_icon_every_source(page):
    _open_health(page)
    out = page.evaluate("""()=>{
      const rows=[
       {src:'tuniucal',plat:'tuniu',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:800,src_price:900,fetched_at:'2026-11-04 10:00:00'},
       {src:'qunar',plat:'qunar',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:810,src_price:900,fetched_at:'2026-11-04 10:00:00'},
       {src:'tongcheng',plat:'tongcheng',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:820,src_price:900,fetched_at:'2026-11-04 10:00:00'},
       {src:'app_qunar',plat:'app_qunar',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:830,src_price:900,fetched_at:'2026-11-04 10:00:00'},
       {src:'app_zhixing',plat:'app_zhixing',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:840,src_price:900,fetched_at:'2026-11-04 10:00:00'},
       {src:'app_ctrip',plat:'app_ctrip',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:850,src_price:900,fetched_at:'2026-11-04 10:00:00'},
       {src:'app_tongcheng',plat:'app_tongcheng',from_city:'上海',to_city:'北京',depart_date:'2026-11-20',price:860,src_price:900,fetched_at:'2026-11-04 10:00:00'}];
      const html=spDealList(rows);const d=document.createElement('div');d.innerHTML=html;
      return {text:d.textContent,icons:d.querySelectorAll('img.bic').length};
    }""")
    for want in ("途牛日历", "去哪儿日历", "同程日历", "去哪儿App低价",
                 "智行特价", "携程App日历", "同程App日历"):
        assert want in out["text"], (want, out["text"])
    for raw in ("tuniucal", "app_qunar", "app_zhixing", "app_ctrip",
                "app_tongcheng"):
        assert raw not in out["text"], ("特价行露出裸 id", raw, out["text"])
    assert out["icons"] >= 7, ("特价行没有逐行官方图标", out)


def test_health_source_block_scoped_to_qunar_web(page):
    _open_health(page)
    out = page.evaluate("""()=>{const b=document.getElementById('srccap');
      return {aria:b.getAttribute('aria-label')||'',
              note:(document.getElementById('scNote')||{}).textContent||''};}""")
    text = out["aria"] + out["note"]
    assert "App 渠道" in text and "真机" in text, out
    assert "App 专属价与自动下单不在采集范围" not in text, (
        "健康页仍写 App 不在采集范围", out)


def test_srx_links_cover_app_with_explicit_no_web_landing():
    """检索页渠道卡必须覆盖 10 家；App 没有网页落地页时要说清原因。"""
    import webui
    j = webui._srx_links("SHA", "PEK", "2030-01-01")
    by = {x["key"]: x for x in j["links"]}
    for p in ("app_zhixing", "app_qunar", "app_fliggy",
              "app_ctrip", "app_tongcheng"):
        assert p in by, ("检索页渠道卡漏了 %s" % p, sorted(by))
        assert by[p].get("app") and not by[p]["url"], by[p]
        assert "真机" in by[p]["note"], by[p]
    assert "App 无网页落地页" in _src(), "前端仍把 App 写成「本态不供落地页」"


def test_channel_order_and_push_names_cover_all_ten():
    src = _src()
    order = ("const SRX_PLAT_ORDER=['ctrip','qunar','fliggy','tongcheng',"
             "'tuniu',\n 'app_zhixing','app_qunar','app_fliggy',"
             "'app_ctrip','app_tongcheng'];")
    assert order in src, "渠道统一顺序没有覆盖全部 10 家"
    assert "Alerter.plat_cn(channel)" in src, (
        "雷达推送仍用裸渠道 id（app_qunar 这类）")
    assert ".concat((u.platforms||[]).map(p=>platCN(p)))" in src, (
        "明细筛选没有覆盖「已勾选但无数据」的渠道")


def test_search_surface_flatness_sweep():
    """检索页所有装饰性抬升阴影收掉；坏掉的 CSS 值不得回归。"""
    src = _src()
    assert "var(--line)ue)" not in src, "检索页 hero 分隔线仍是坏 CSS"
    for needle in (
        "#searchview .srx-hero-act .srx-btn:hover{background:var(--card);"
        "border-color:transparent;color:var(--blue)}",
        "#searchview .srx-band-h .srx-axis button.on{background:"
        "var(--r-surface);color:var(--r-blue)}",
        "#searchview .srx-mirror .srx-mtab.on{background:var(--r-surface);"
        "color:var(--r-blue)}",
    ):
        assert needle in src, ("检索页仍有装饰阴影", needle)


def test_detail_filter_shows_configured_unscanned_channel(page):
    _goto(page)
    out = page.evaluate("""()=>{
      const u=S.users[U];
      u.flights=u.flights.filter(f=>f.plat!=='飞猪 App');
      if(u.platAge)delete u.platAge['飞猪 App'];
      u.platforms=(u.platforms||[]).filter(p=>p!=='app_fliggy').concat(['app_fliggy']);
      buildChips();
      return [...document.querySelectorAll('#platchips .chip')]
        .map(c=>c.textContent.replace(/\\s+/g,' ').trim());
    }""")
    assert any("飞猪 App" in x for x in out), (
        "已勾选但近轮无数据的渠道在筛选 chip 里消失", out)


def test_radar_form_declares_each_channel_capability(page):
    _goto(page)
    page.evaluate("()=>{switchView('mon');showMonTab('specials');"
                  "srxRadarLoadFromUser(true);}")
    page.wait_for_function(
        "()=>{const el=document.getElementById('spRadarCaps');"
        "return el&&/飞猪 App：未接入低价源/.test(el.textContent||'');}",
        timeout=15000)
    text = page.evaluate(
        "()=>document.getElementById('spRadarCaps').textContent")
    assert "飞猪 App：未接入低价源" in text, (
        "雷达勾选区没有如实说明 app_fliggy 无发现源", text)
    for name in ("携程", "去哪儿 App", "智行 App"):
        assert name in text, (name, text)


def _src():
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()

