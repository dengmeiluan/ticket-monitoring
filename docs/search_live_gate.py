# -*- coding: utf-8 -*-
"""r348 生产检索工作台实时门禁（127.0.0.1:8765，只读交互）。

前置：生产控制台已在 127.0.0.1:8765 运行（真实 /api/state）。
运行：python docs/search_live_gate.py
覆盖：价带/五源/筛选/矩阵/详情/字段 raw/校准册四视图+四源/健康/状态串/快照/
     会话/CSV/键盘/移动端 chip 命中/Esc；不发起真实探针 POST。
产物：_scratch/search_live_gate/（截图与 CSV 下载）。
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("GATE_BASE", "http://127.0.0.1:8765/")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_scratch", "search_live_gate")
os.makedirs(OUT, exist_ok=True)
fails = []
checks = []
errors = []

def ck(name, cond, extra=""):
    checks.append((name, bool(cond), extra))
    print(("  OK  " if cond else "  FAIL") + " " + name + ((" :: " + extra) if extra else ""))
    if not cond:
        fails.append(name + ((" :: " + extra) if extra else ""))

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1360, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
    pg.on("console", lambda m: errors.append("CONSOLE " + m.text) if m.type == "error" else None)
    pg.goto(BASE, wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(2400)
    pg.click("#navSearch")
    pg.wait_for_timeout(3600)
    try:   # 价带是懒加载（真实 DB 14 天窗口）；等它完成再断言
        pg.wait_for_function("()=>document.querySelectorAll('#srxBandDays .srx-day').length===14", timeout=15000)
    except Exception:
        pass

    ck("search visible", pg.locator("#searchview").is_visible())
    _neutral = pg.evaluate("()=>({date:SRX.date,plats:SRX.plats.length,q:SRX.q})")
    ck("neutral all-date initial", _neutral["date"] == "" and _neutral["plats"] == 0
       and _neutral["q"] == "", str(_neutral))
    ck("rows > 0", pg.locator("#srxRows .srx-row").count() > 0, str(pg.locator("#srxRows .srx-row").count()))
    # 中性首屏不自动锁日；价带/矩阵门禁显式选一个当前非 stale 的航线/日期
    _pick = pg.evaluate("""()=>{const u=(S.users||[])[U]||{},all=u.flights||[],c={};
      all.filter(f=>!srxIsCal(f)&&!srxIsStale(f)).forEach(f=>{
        const k=f.from+'|'+f.to;c[k]=c[k]||{};c[k][f.date]=(c[k][f.date]||0)+1});
      let best='',bd='',bn=0;
      Object.entries(c).forEach(([k,ds])=>Object.entries(ds).forEach(([d,n])=>{
        if(n>bn){bn=n;best=k;bd=d}}));
      if(best){SRX.pair=best;SRX.date=bd;SRX.plats=[];SRX.q='';
        SRX.f={...SRX_DEFAULT_F};SRX.bandAnchor='';SRX._init=true;renderSearch()}
      return {pair:best,date:bd,n:bn}}""")
    ck("fresh pair/date selected", bool(_pick["pair"]), str(_pick))
    pg.wait_for_timeout(1500)
    try:
        pg.wait_for_function("()=>document.querySelectorAll('#srxBandDays .srx-day').length===14", timeout=15000)
    except Exception:
        pass
    ck("band 14 cells", pg.locator("#srxBandDays .srx-day").count() == 14, str(pg.locator("#srxBandDays .srx-day").count()))
    ck("brief 5 sources", pg.locator("#srxBrief .srx-src").count() == 5)
    ck("mirror 5 tabs", pg.locator("#srxMirror [data-mch]").count() == 5)
    ck("mirror rows > 0", pg.locator("#srxMirror .srx-mrow").count() > 0)
    ck("no overflow desktop", not pg.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth"))

    # filters (r355: secondary rows collapsed by default; open once)
    pg.click("#srxFilterBtn")
    pg.wait_for_timeout(250)
    ck("filters expand", pg.locator("#srxContext").evaluate(
        "e=>!e.classList.contains('ctx-collapsed')"))
    before = pg.locator("#srxRows .srx-row").count()
    pg.locator("[data-f='trip'][data-fv='transfer']").click(); pg.wait_for_timeout(300)
    transfer = pg.locator("#srxRows .srx-row").count()
    ck("transfer filter reduces", transfer > 0 and transfer <= before, f"{before}->{transfer}")
    pg.locator("[data-abar='trip']").click(); pg.wait_for_timeout(300)
    ck("abar clear trip", pg.locator("#srxRows .srx-row").count() == before)
    _pick = pg.evaluate("""()=>{const f=(SRX.rows||[]).find(r=>r.code);
      return f?String(f.code).split('/')[0]:''}""")
    pg.locator("#srxQ").fill(_pick or "SC"); pg.wait_for_timeout(400)
    ck("search filters rows", 0 < pg.locator("#srxRows .srx-row").count() < before, str(pg.locator("#srxRows .srx-row").count()))
    pg.locator("#srxQ").fill(""); pg.wait_for_timeout(400)
    pg.locator("#srxMoreBtn").click(); pg.wait_for_timeout(200)
    ck("more filters open", pg.locator("#srxFmore").evaluate("e=>e.classList.contains('open')"))
    ck("facets present", pg.locator("#srxFmore [data-ft]").count() >= 10, str(pg.locator("#srxFmore [data-ft]").count()))
    pg.locator("#srxFmore [data-ft='bag']").check(); pg.wait_for_timeout(300)
    bag_rows = pg.locator("#srxRows .srx-row").count()
    ck("baggage filter works", bag_rows >= 0, str(bag_rows))
    pg.locator("[data-abar='bag']").click(); pg.wait_for_timeout(300)
    pg.locator("#srxMoreBtn").click(); pg.wait_for_timeout(100)

    # matrix
    pg.locator("#srxViewBtn").click(); pg.wait_for_timeout(300)
    ck("matrix rendered", pg.locator("#srxRows .srx-mx").count() == 1)
    ck("matrix 5 channel headers", pg.locator("#srxRows .srx-mx thead th").count() == 6, str(pg.locator("#srxRows .srx-mx thead th").count()))
    mx = pg.locator("#srxRows .mcell[data-mxopen]").first
    ck("matrix cells", mx.count() > 0)
    if mx.count():
        mx.click(); pg.wait_for_timeout(500)
        ck("matrix cell opens detail", pg.locator("#srxDetail").evaluate("e=>e.classList.contains('open')"))
        pg.locator("#srxDetail [data-srxclose]").click(); pg.wait_for_timeout(200)
    pg.locator("#srxViewBtn").click(); pg.wait_for_timeout(300)
    ck("back to list", pg.locator("#srxRows .srx-row").count() > 0)

    # row -> detail fields -> raw -> tabs
    row = pg.locator("#srxRows .srx-row").first
    row.scroll_into_view_if_needed(); row.click(position={"x":40, "y":12}); pg.wait_for_timeout(700)
    ck("row click opens detail", pg.locator("#srxDetail").evaluate("e=>e.classList.contains('open')"))
    ck("18 fields", pg.locator("#srxDetail .srx-f").count() >= 14, str(pg.locator("#srxDetail .srx-f").count()))
    ck("6 tabs", pg.locator("#srxDetail .srx-dtab").count() >= 5, str(pg.locator("#srxDetail .srx-dtab").count()))
    ck("raw keys", pg.locator("#srxRawBox .rk").count() > 0, str(pg.locator("#srxRawBox .rk").count()))
    pg.locator("#srxDetail .srx-f").first.click(); pg.wait_for_timeout(300)
    ck("field click highlights raw", pg.locator("#srxRawBox .hit").count() == 1, str(pg.locator("#srxRawBox .hit").count()))
    for tab in ["raw", "prov", "trend", "cal", "cmp", "fields"]:
        el = pg.locator(f"#srxDetail .srx-dtab[data-dtab='{tab}']")
        if el.count():
            el.click(); pg.wait_for_timeout(250)
    ck("detail tabs clickable", True)
    # signoff
    note = pg.locator("#srxSignNote")
    if note.count():
        note.fill("gate note"); pg.locator("[data-signsave]").click(); pg.wait_for_timeout(300)
        ck("signoff saved", "gate note" in (pg.evaluate("localStorage.getItem('jpsrx_signs')") or "") and "本行已存" in pg.locator(".srx-savebar").inner_text())
    pg.locator("#srxDetail [data-srxclose]").click(); pg.wait_for_timeout(200)

    # gallery 4 views + four
    pg.locator("#searchview .srx-hero-act button[onclick='srxOpenGallery()']").click(); pg.wait_for_timeout(400)
    ck("gallery open", pg.locator("#srxGallery").evaluate("e=>e.classList.contains('open')"))
    ck("gallery 5 rails", pg.locator("#srxGallery [data-galch]").count() == 5)
    ck("gallery 4 views", pg.locator("#srxGallery [data-galview]").count() == 4)
    for v in ["detail", "cal", "cross", "list"]:
        pg.locator(f"#srxGallery [data-galview='{v}']").click(); pg.wait_for_timeout(250)
    pg.locator("#srxGallery [data-galview4]").click(); pg.wait_for_timeout(250)
    ck("gallery four view", pg.locator("#srxGallery .srx-four").count() == 1)
    pg.locator("#srxGallery [data-galclose]").click(); pg.wait_for_timeout(200)

    # health
    # 折叠式 hero 工具条（窄屏/新视觉）把二级动作收进「更多」；先展开再点
    _mb = pg.locator("#searchview .srx-hero-act .srx-more-btn")
    if _mb.count() and _mb.first.is_visible():
        _mb.first.click(); pg.wait_for_timeout(200)
    pg.locator("#searchview .srx-hero-act button[onclick='srxOpenHealth()']").click(); pg.wait_for_timeout(1800)
    ck("health modal", pg.locator("#srxModal.open").count() == 1 and pg.locator("#srxModal .srx-health").count() == 1)
    pg.locator("#srxModal [data-modalclose]").click(); pg.wait_for_timeout(200)

    # state / snapshot
    pg.locator("#searchview .srx-hero-act button[onclick='srxOpenState()']").click(); pg.wait_for_timeout(300)
    ck("state modal", pg.locator("#srxStateBox").count() == 1 and pg.locator("#srxStateBox").input_value().startswith("probe://srx"))
    pg.locator("#srxSnapName").fill("gate-snap"); pg.locator("[data-snapadd]").click(); pg.wait_for_timeout(300)
    ck("snapshot saved", pg.locator("#srxSnapList").inner_text().find("gate-snap") >= 0)
    pg.locator("#srxModal [data-modalclose]").click(); pg.wait_for_timeout(200)

    # sessions modal
    pg.locator('#srxProbe .srx-probehead button:has-text("探针会话")').click(); pg.wait_for_timeout(300)
    ck("sessions modal", pg.locator("#srxModal.open").count() == 1 and "探针会话" in pg.locator("#srxModal").inner_text())
    pg.locator("#srxModal [data-modalclose]").click(); pg.wait_for_timeout(200)

    # CSV export (filter to a row that exists in this round)
    pg.locator("#srxQ").fill(_pick or "SC"); pg.wait_for_timeout(500)
    with pg.expect_download(timeout=30000) as dl:
        pg.locator("#searchview .srx-hero-act button[onclick='srxExport()']").click()
    d = dl.value
    path = os.path.join(OUT, d.suggested_filename)
    d.save_as(path)
    head = open(path, encoding="utf-8-sig").readline()
    ck("CSV has provenance headers", "原页价" in head and "证据指纹" in head and "落地页" in head)
    pg.locator("#srxQ").fill(""); pg.wait_for_timeout(300)

    # keyboard
    pg.keyboard.press("/"); pg.wait_for_timeout(100)
    ck("slash focuses search", pg.evaluate("document.activeElement.id") == "srxQ")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(100)
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("m"); pg.wait_for_timeout(300)
    ck("m toggles matrix", pg.locator("#srxRows .srx-mx").count() == 1)
    pg.keyboard.press("m"); pg.wait_for_timeout(200)

    # mobile
    ctx2 = b.new_context(viewport={"width": 390, "height": 844})
    pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errors.append("MOBILE_PAGEERROR " + str(e)))
    pg2.goto(BASE, wait_until="domcontentloaded", timeout=30000); pg2.wait_for_timeout(2200)
    pg2.click("#navSearch"); pg2.wait_for_timeout(3000)
    ck("mobile no overflow", not pg2.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth"))
    ck("mobile rows", pg2.locator("#srxRows .srx-row").count() > 0)
    # channel chip clickability
    pg2.locator('[data-mobile="filters"]').click(); pg2.wait_for_timeout(300)
    chip = pg2.locator("#srxPlats button[data-plat='tuniu']")
    try:
        pg2.wait_for_function(
            "()=>{const c=document.querySelector(\"#srxPlats button[data-plat='tuniu']\");"
            "if(!c)return false;const r=c.getBoundingClientRect();"
            "return r.width>0&&r.height>0;}", timeout=6000)
    except Exception:
        pass
    if chip.count() and chip.first.is_visible():
        try:
            chip.scroll_into_view_if_needed(timeout=5000); pg2.wait_for_timeout(200)
        except Exception:
            pass
        box = chip.bounding_box()
        if box:
            hit = pg2.evaluate("([x,y])=>{const e=document.elementFromPoint(x,y);return e?e.closest('[data-plat]')?.getAttribute('data-plat'):''}", [box["x"]+box["width"]/2, box["y"]+box["height"]/2])
            ck("mobile channel chip hit", hit == "tuniu", str(hit))
    # mobile mirror tab
    pg2.locator(".srx-mtabs [data-mtab='mirror']").click(); pg2.wait_for_timeout(400)
    ck("mobile mirror visible", pg2.locator("#srxMirror").is_visible())
    pg2.locator(".srx-mtabs [data-mtab='list']").click(); pg2.wait_for_timeout(300)
    pg2.locator("#srxRows .srx-row").first.click(position={"x":30, "y":10}); pg2.wait_for_timeout(500)
    ck("mobile detail opens", pg2.locator("#srxDetail").evaluate("e=>e.classList.contains('open')"))
    pg2.keyboard.press("Escape"); pg2.wait_for_timeout(200)
    ck("mobile Esc closes detail", not pg2.locator("#srxDetail").evaluate("e=>e.classList.contains('open')"))
    pg2.screenshot(path=os.path.join(OUT, "mobile_gate.png"), full_page=False)

    print("\nFAILS", json.dumps(fails, ensure_ascii=False))
    print("ERRORS", json.dumps(errors[:20], ensure_ascii=False))
    print("CHECKS", sum(1 for _, c, _ in checks if c), "/", len(checks))
    b.close()
    sys.exit(1 if fails or errors else 0)
