# -*- coding: utf-8 -*-
"""r324 监控面+弹层「入口全链路」回归套件（C9 教训注入版）。

背景：用户连击三次同族交互 bug，C9=城市面板点选从未把选择写进模型
（pick 在置空 _cpEl 之后才派发 change，TypeError 被吞），475 颗既有钉
全绿的原因=所有测试绕过真实入口件。本套件对监控页每个用户可达交互
入口用【真实 UI 路径】驱动（locator 真实 click/fill/keyboard.press；
禁止 evaluate 直调渲染/状态函数代替入口交互），每用例三面断言：
  ① 状态/数据面已写（S/FLT/SORT/EXP/TGOPEN/CHR 等，或服务端 GET 效果）；
  ② UI 投影面已随（渲染结果）；
  ③ 零 console error（pageerror+console 收集器每用例独立挂，零带入）。

覆盖入口（对照 _scratch/r324_monsync_audit.md §一/二 写点×投影面）：
  概览    kpisum 明细/走势链、mchip 跳明细预置渠道、KPI numlink/整卡
          外链窗（route 拦截+popup）、ovAlert 哨态；
  走势    航线片 togChart（chartTitle/calTitle 同拍=F1 回归面）、范围/
          模式片、图例、canvas hover 十字线（HPTS 状态）+点击跳明细锁日期；
  明细    表头排序（SORT+aria-sort+箭头+srtchip 三面）、类别 tabs、
          行展开比价（EXP+xrow）、改期胶囊（TGOPEN+tgrow+互斥）、
          日期/航线/渠道/航司/舱位/机场双 chips、时段窗、价格/搜索/
          补位开关、余票/限购开关、更多筛选八维（时长/准点/机龄/托运/
          餐食/廉航；经停/共享/跨天/儿童=自适应显隐钉）、CSV 导出
          （download 事件）、滚动切片完整性、首列吸附；
  健康    健康格→渠道轮日志弹层、推送通道行、脉冲柱→gotoPulseHealth
          （辉光+横滚居中）；
  弹层    推送预览（/api/preview 真 POST，Esc 关+焦点归还+Tab 圈闭）、
          推送记录（条目展开）、立即扫描按钮双拍/R 快捷键双拍的 demo
          403 只读门失败分支 toast 词面钉（绝不触发真实副作用）、配置页
          登录卡面板开合（绝不点击「弹窗登录」——loginStart 会弹真窗）；
  全局    主题三态循环+localStorage 持久+重载保持、快捷键 1/2/3-6///R/
          Esc 级联、URL 深链（#tab/uN 启动恢复+hashchange 活页消费+
          越界守卫）、单用户 pills 隐藏钉、页脚 GitHub rel；
  空态    停用全部航线空态引导词面（route 拦截 /api/state 构造 suspended
          载荷=网络入口全链，不 POST、不改服务端）。

RED（真实 bug，只报告不改生产代码）：
  RED-1 resetFlt 漏清机场筛选族 FLT.depA/FLT.arrA（webui.py ~2732 重置
        清单缺两族；updFltN ~4512 也不计数）——点机场 chip 后点
        「重置筛选与排序」：chip 仍 .on、FLT.depA 残留、结果集仍被过滤、
        fltN 角标恒隐藏。钉以 xfail(strict) 在案，主修复转正。

安全纪律：demo 全部 POST 被 403 只读门拦截（/api/preview 豁免、无副
作用）；本套件不点击「弹窗登录/我已登录完成/测试推送」等生产写钮。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_entry_mon.py -q
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    import subprocess
    import tempfile
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    import tempfile as _tf
    priv_tmp = _tf.mkdtemp(prefix="r324en_")
    render_tmp = _tf.mkdtemp(prefix="r324en_render_")
    env = dict(os.environ, TEMP=priv_tmp, TMP=priv_tmp,
               TMPDIR=priv_tmp, TM_RENDER_DIR=render_tmp)
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        if _wait_up(proc):
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture()
def page(srv):
    """每用例独立 context（localStorage 天然隔离）+ 独立错误收集器。

    403 (Forbidden) 豁免=demo 只读门的**预期失败分支**（立即扫描/R
    快捷键用例故意触发），uitest.py 同款豁免口径。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  accept_downloads=True)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(
            "pageerror: " + (getattr(e, "stack", None) or str(e))[:300]))
        pg.on("console", lambda m: errs.append("console: " + m.text[:300])
              if m.type == "error" and "403 (Forbidden)" not in m.text
              else None)
        pg._r324_errs = errs
        yield pg
        assert not errs, "零 console error 被破坏: %r" % errs[:5]
        browser.close()


# ---------- 通用助手（全部经由真实入口，evaluate 只作断言/前置导航） ----------

def _goto(page, fragment=""):
    page.goto(BASE + "/" + fragment, wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(500)


def _mtab(page, t):
    """真实点击顶部分栏切换器。"""
    page.locator(".mtab[data-t='%s']" % t).click()
    page.wait_for_timeout(350)


def _details(page):
    _mtab(page, "details")
    # Filters are collapsed by default now; open the drawer for filter tests.
    page.evaluate("()=>{const fb=document.querySelector('.fbar');"
                  "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
    page.wait_for_timeout(200)


def _toasts(page):
    return page.evaluate(
        "[...document.querySelectorAll('#toasts .toast')].map(t=>t.textContent)")


def _toast_last(page):
    ts = _toasts(page)
    return ts[-1] if ts else ""


def _fcnt(page):
    """(可见报价, 全部报价)——r345 KPI 第二段改为唯一班次；测试语义
    一直是「行/报价数」，总数直接从模型取，避免拿 69 班比 194 报价。"""
    import re
    m = re.search(r"：(\d+) 条报价", page.evaluate(
        "document.getElementById('fcnt').textContent") or "")
    total = page.evaluate(
        "(S&&S.users&&S.users[U]&&S.users[U].flights)?"
        "S.users[U].flights.length:0")
    return (int(m.group(1)), int(total)) if m else (None, None)


def _flt(page):
    """状态面快照（断言用，不作交互）。"""
    return page.evaluate("""(() => ({
      plats: [...FLT.plats], routes: [...FLT.routes], dates: [...FLT.dates],
      dep: FLT.dep, arr: FLT.arr, airlines: [...FLT.airlines],
      ps: [...FLT.ps], cabins: [...FLT.cabins], depA: [...FLT.depA],
      arrA: [...FLT.arrA], pmin: FLT.pmin, pmax: FLT.pmax, q: FLT.q,
      no: FLT.no, few: FLT.few, nostop: FLT.nostop, noshare: FLT.noshare,
      safe: FLT.safe, laymin: FLT.laymin, laymax: FLT.laymax,
      durmin: FLT.durmin, durmax: FLT.durmax, prate: FLT.prate,
      age: FLT.age, bag: FLT.bag, meal: FLT.meal, nolcc: FLT.nolcc,
      cross: FLT.cross, child: FLT.child}))()""")


_SNAP_UI = """(() => ({
  sort: JSON.parse(JSON.stringify(SORT)), f: F, u: U, exp: EXP, tg: TGOPEN,
  chr: JSON.parse(JSON.stringify(CHR)), theme: localStorage.getItem('jptheme'),
  flt: %s}))()""" % """{plats:[...FLT.plats],routes:[...FLT.routes],dates:[...FLT.dates],
   dep:FLT.dep,arr:FLT.arr,airlines:[...FLT.airlines],ps:[...FLT.ps],
   cabins:[...FLT.cabins],depA:[...FLT.depA],arrA:[...FLT.arrA],
   pmin:FLT.pmin||0,pmax:FLT.pmax||0,q:FLT.q||'',no:!!FLT.no,few:!!FLT.few,
   nostop:!!FLT.nostop,noshare:!!FLT.noshare,safe:!!FLT.safe,
   laymin:FLT.laymin||0,laymax:FLT.laymax||0,durmin:FLT.durmin||0,
   durmax:FLT.durmax||0,prate:FLT.prate||0,age:FLT.age||0,bag:!!FLT.bag,
   meal:!!FLT.meal,nolcc:!!FLT.nolcc,cross:!!FLT.cross,child:!!FLT.child,
   init:!!FLT._platsInit}"""

_RESTORE_UI = """((s) => {
  SORT = s.sort; F = s.f; EXP = s.exp; TGOPEN = s.tg; CHR = s.chr; U = s.u;
  const q = s.flt;
  FLT.plats = new Set(q.plats); FLT.routes = new Set(q.routes);
  FLT.dates = new Set(q.dates); FLT.dep = q.dep; FLT.arr = q.arr;
  FLT.airlines = new Set(q.airlines); FLT.ps = new Set(q.ps);
  FLT.cabins = new Set(q.cabins); FLT.depA = new Set(q.depA);
  FLT.arrA = new Set(q.arrA);
  FLT.pmin = q.pmin; FLT.pmax = q.pmax; FLT.q = q.q; FLT.no = q.no;
  FLT.few = q.few; FLT.nostop = q.nostop; FLT.noshare = q.noshare;
  FLT.safe = q.safe; FLT.laymin = q.laymin; FLT.laymax = q.laymax;
  FLT.durmin = q.durmin; FLT.durmax = q.durmax; FLT.prate = q.prate;
  FLT.age = q.age; FLT.bag = q.bag; FLT.meal = q.meal;
  FLT.nolcc = q.nolcc; FLT.cross = q.cross; FLT.child = q.child;
  FLT._platsInit = q.init;
  if (s.theme == null) { try { localStorage.removeItem('jptheme'); } catch (e) {} }
  else { try { localStorage.setItem('jptheme', s.theme); } catch (e) {} }
  applyTheme();
  if (MONTAB === 'details') table();
})"""


def _restore(page, snap):
    page.evaluate(_RESTORE_UI, snap)


# ================= §一 概览 =================

def test_ov01_kpisum_details_link(page):
    """kpisum「查看明细 ▸」：真实点击 → 明细子栏 pane 显示。"""
    _goto(page)
    link = page.locator("#users .kpisum a", has_text="查看明细").first
    assert link.count() >= 1
    link.click()
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "details"
    assert page.is_visible("#montab-details")
    assert page.evaluate("location.hash").startswith("#details")


def test_ov02_kpisum_trend_link(page):
    """kpisum「走势 ▸」：真实点击 → 走势子栏（jumpRowTrend('') 空路由
    =当前视图，不写 st.i——chartTitle 保持首航线）。"""
    _goto(page)
    t0 = page.evaluate("document.getElementById('chartTitle').textContent")
    link = page.locator("#users .kpisum a", has_text="走势").first
    link.click()
    page.wait_for_timeout(600)
    assert page.evaluate("MONTAB") == "trend"
    assert page.is_visible("#chartcard")
    t1 = page.evaluate("document.getElementById('chartTitle').textContent")
    assert t0.split("·")[0] == t1.split("·")[0], (t0, t1)   # 航线不换


def test_ov03_mchip_jump_details_prefilter(page):
    """渠道片 mchip：真实点击 → 明细子栏 + FLT.plats 预置该渠道 +
    platchips 亮片 + 结果集收缩 + 教学 toast（含重置告知）。"""
    _goto(page)
    name = page.evaluate(
        "document.querySelector('.mchip').textContent.trim().split(/\\s+/)[0]")
    page.locator(".mchip").first.click()
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "details"
    flt = _flt(page)
    assert flt["plats"] == [name], flt
    on = page.evaluate(
        "[...document.querySelectorAll('#platchips .chip')]"
        ".filter(c=>c.classList.contains('on')).map(c=>c.dataset.p)")
    assert on == [name], on
    shown, total = _fcnt(page)
    assert 0 < shown < total, (shown, total)
    assert ("仅看 %s 明细" % name) in _toast_last(page), _toasts(page)


def test_ov04_kpi_numlink_popup_blocked(page, ):
    """KPI numlink：真实点击 → 新窗（外链 route 拦截下 popup 仍真实
    创建）；锚 target=_blank + rel=noopener + href=data-href 一致。"""
    _goto(page)
    ctx = page.context
    ctx.route("**/*", lambda r: r.abort()
              if r.request.url.startswith("http")
              and "127.0.0.1" not in r.request.url else r.continue_())
    a = page.locator("a.numlink").first
    href = a.get_attribute("href")
    data_href = page.evaluate(
        "document.querySelector('a.numlink').closest('.kpi').dataset.href")
    assert href == data_href   # 卡 href 与整卡 data-href 同一目标
    assert a.get_attribute("target") == "_blank"
    assert "noopener" in (a.get_attribute("rel") or "")
    with page.expect_popup(timeout=5000) as pop:
        a.click()
    pp = pop.value
    assert pp != page   # 真实新开一窗（外站被拦截故停在错误页）
    pp.close()
    ctx.unroute("**/*")


def test_ov05_kpi_card_click_popup(page):
    """KPI 整卡（.kpi.clk）：真实点击卡面非锚区 → window.open(data-href)
    真实弹窗；无链接卡不带 clk（不可点卡零假 affordance）。"""
    _goto(page)
    n_clk = page.evaluate("document.querySelectorAll('.kpi.clk').length")
    n_kpi = page.evaluate("document.querySelectorAll('#users .kpi').length")
    assert n_clk >= 1
    assert n_clk <= n_kpi
    ctx = page.context
    ctx.route("**/*", lambda r: r.abort()
              if r.request.url.startswith("http")
              and "127.0.0.1" not in r.request.url else r.continue_())
    card = page.locator(".kpi.clk").first
    want = card.get_attribute("data-href")
    with page.expect_popup(timeout=5000) as pop:
        card.locator(".lab").click()   # 非锚区（锚点自带跳过守卫）
    pp = pop.value
    assert pp != page
    pp.close()
    ctx.unroute("**/*")


def test_ov06_ovalert_sentinel_state(page):
    """ovAlert 哨：demo 推送连败在场 → 红帽可见 + aria/title 词面
    （哨是显隐投影件无点击动作——audit W27 双源合成）。"""
    _goto(page)
    assert page.evaluate(
        "document.getElementById('ovAlert').style.display") == ""
    assert page.get_attribute("#ovAlert", "aria-label") == \
        "采集或推送通道有异常，详情见渠道健康"
    assert "渠道健康" in page.get_attribute("#ovAlert", "title")


# ================= §二 走势·日历 =================

def test_tr01_chart_chip_switch_route(page):
    """走势航线片 togChart：真实点击第 2 片 → CHR.i 写入 + 片高亮 +
    chartTitle 与 calTitle 同拍同航线（F1 劈叉回归面）+ 日历格在场。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    chips = page.locator("#chartRoutes .chip")
    assert chips.count() >= 2
    want = chips.nth(1).text_content().strip()
    chips.nth(1).click()
    page.wait_for_timeout(500)
    chr_st = page.evaluate("JSON.stringify(CHR)")
    assert '"i":1' in chr_st, chr_st
    on_idx = page.evaluate(
        "[...document.querySelectorAll('#chartRoutes .chip')]"
        ".findIndex(c=>c.classList.contains('on'))")
    assert on_idx == 1, on_idx
    title = page.evaluate("document.getElementById('chartTitle').textContent")
    cal = page.evaluate("document.getElementById('calTitle').textContent")
    assert want in title, (want, title)
    assert cal == title.split("·", 1)[1].strip(), (cal, title)   # F1：日历随拍
    assert page.evaluate(
        "document.querySelectorAll('#calgrid .calcell').length") > 0


def test_tr02_range_chip(page):
    """范围片 setRange：真实点击 7 天 → CHR.r + 片高亮 + 标题 7 天 +
    aria-pressed 播报（r257 P3-2）。"""
    _goto(page)
    _mtab(page, "trend")
    page.locator("#rng7d").click()
    page.wait_for_timeout(600)
    assert page.evaluate("JSON.stringify(CHR)").find('"r":"7d"') >= 0
    assert page.evaluate("document.getElementById('rng7d').classList"
                         ".contains('on')")
    assert "7天" in page.evaluate(
        "document.getElementById('chartTitle').textContent")
    assert page.get_attribute("#rng7d", "aria-pressed") == "true"


def test_tr03_mode_chip_kline_legend(page):
    """模式片 setMode：K线 → CHR.m + 折线色票隐藏（图例-数据一致）+
    ringNote K线专有词面；切回折线恢复。"""
    _goto(page)
    _mtab(page, "trend")
    page.locator("#mdK").click()
    page.wait_for_timeout(500)
    assert page.evaluate("JSON.stringify(CHR)").find('"m":"kline"') >= 0
    assert page.evaluate(
        "document.getElementById('mdK').classList.contains('on')")
    assert page.evaluate(
        "document.getElementById('lgDirect').style.display") == "none"
    assert "K线" in page.evaluate(
        "document.getElementById('ringNote').textContent")
    page.locator("#mdLine").click()
    page.wait_for_timeout(400)
    assert page.evaluate(
        "document.getElementById('lgDirect').style.display") == ""


def test_tr04_canvas_hover_crosshair(page):
    """canvas hover 十字线（真实鼠标路径）：HPTS 读数状态写入（DOM 快照
    看不到的 canvas 交互，状态面+无错双断言）。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    box = page.locator("#chart").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5,
                    box["y"] + box["height"] * 0.5)
    page.wait_for_timeout(300)
    assert page.evaluate("!!HPTS")


def test_tr05_canvas_click_jump_details_lock_date(page):
    """canvas 点击 → 该轮明细（jumpTrendDetail→jumpCalDate 全链）：
    MONTAB 切明细 + FLT.dates/routes 双锁 + 重置告知 toast +
    焦点交接明细 tab。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    want_date = page.evaluate("curRoute().r.date")
    want_route = page.evaluate(
        "(curRoute().r.label||'').replace(/\\s+\\d{2}\\/\\d{2}\\s*$/,'')")
    box = page.locator("#chart").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.5,
                     box["y"] + box["height"] * 0.5)
    page.wait_for_timeout(500)
    assert page.evaluate("MONTAB") == "details"
    flt = _flt(page)
    assert flt["dates"] == [want_date], (flt["dates"], want_date)
    assert flt["routes"] == [want_route], (flt["routes"], want_route)
    assert "已重置现有筛选，仅看该日期明细" in _toasts(page)
    assert page.evaluate(
        "document.activeElement && document.activeElement.dataset.t") == \
        "details"


def test_tr06_calendar_projection(page):
    """价格日历投影：calTitle 与走势航线一致 + 7 天洞察统计词面 +
    格数 14-15（demo 双周窗）；日历格纯展示（audit 撤案 #5 在案，
    无假 affordance——无 role=button）。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    title = page.evaluate("document.getElementById('chartTitle').textContent")
    cal = page.evaluate("document.getElementById('calTitle').textContent")
    assert cal and cal in title, (cal, title)
    stats = page.evaluate("document.getElementById('calStats').textContent")
    assert "近7天最低" in stats and "日均" in stats, stats
    n = page.evaluate("document.querySelectorAll('#calgrid .calcell').length")
    assert n in (14, 15), n
    assert page.evaluate(
        "!!document.querySelector('#calgrid .calcell[role=\\'button\\']')") \
        is False


# ================= §三 明细 =================

def test_dt01_sort_header_three_face(page):
    """排序表头：真实点击价格表头 → SORT.dir 翻转 + aria-sort + 箭头
    + 行序真变（数据面）；日期表头 → srtchip 三件套同拍（r247 W2）。"""
    _goto(page)
    _details(page)
    first0 = page.evaluate(
        "document.querySelector('#ftable tbody tr[data-k] td')"
        ".textContent.replace(/[^0-9]/g,'')")
    page.locator("th.srt[data-k='price']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("JSON.stringify(SORT)") == '{"k":"price","dir":-1}'
    th = page.locator("th.srt[data-k='price']")
    assert th.get_attribute("aria-sort") == "descending"
    assert "▼" in th.text_content()
    first1 = page.evaluate(
        "document.querySelector('#ftable tbody tr[data-k] td')"
        ".textContent.replace(/[^0-9]/g,'')")
    assert int(first1) >= int(first0), (first0, first1)   # 行序真翻
    page.locator("th.srt[data-k='date']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("SORT.k") == "date"
    chip = page.evaluate(
        "(() => {const c = document.querySelector('.srtchip');"
        "return [c.classList.contains('on'), c.getAttribute('aria-pressed'),"
        "c.dataset.dir];})()")
    assert chip == [True, "true", "asc"], chip
    page.locator("#fltwrap button[onclick*='resetFltUI']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("JSON.stringify(SORT)") == '{"k":"price","dir":1}'
    assert "已恢复默认排序" in _toasts(page)


def test_dt02_category_tabs(page):
    """类别 tabs（#tabs 委托点击）：仅达标 → F='q' + 高亮 + aria-pressed
    + 结果集全达标（🔥 行数=行数）；全部回位。"""
    _goto(page)
    _details(page)
    page.locator("#tabs span[data-f='q']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("F") == "q"
    assert page.evaluate(
        "document.querySelector('#tabs span[data-f=\\'q\\']')"
        ".classList.contains('on')")
    assert page.get_attribute("#tabs span[data-f='q']", "aria-pressed") == \
        "true"
    rows, fires = page.evaluate(
        "[document.querySelectorAll('#ftable tbody tr[data-k]').length,"
        "document.querySelectorAll('#ftable tbody tr[data-k] .fire').length]")
    assert rows > 0 and rows == fires, (rows, fires)
    page.locator("#tabs span[data-f='all']").click()
    page.wait_for_timeout(200)
    assert page.evaluate("F") == "all"


def test_dt03_row_expand_compare_chain(page):
    """行展开 togRow：点击行价格格（避开行内 stopPropagation 子件）→
    EXP 写入 + 同班比价 xrow 显示（跳过夹层 tgrow 找真身）+ aria；
    再点收起 EXP 回 null。"""
    _goto(page)
    _details(page)
    row = page.locator("#ftable tbody tr[data-k]").first
    row.locator("td.price").click()
    page.wait_for_timeout(250)
    assert page.evaluate("EXP !== null && EXP !== undefined")
    xr = page.evaluate(
        "(() => {const r = document.querySelector("
        "'#ftable tr[aria-expanded=\\'true\\']');"
        "let n = r && r.nextElementSibling;"
        "while (n && n.classList.contains('tgrow')) n = n.nextElementSibling;"
        "return n && n.classList.contains('xrow') ? "
        "{shown: n.style.display !== 'none',"
        "head: n.textContent.slice(0, 12)} : null;})()")
    assert xr and xr["shown"], xr
    assert "同班比价" in xr["head"]
    assert page.get_attribute("#ftable tr[aria-expanded='true']",
                              "aria-expanded") == "true"
    row.locator("td.price").click()
    page.wait_for_timeout(250)
    assert page.evaluate("JSON.stringify(EXP)") == "null"


def test_dt04_tg_capsule_and_mutex(page):
    """改期胶囊 togGo：点击 → TGOPEN 写入 + tgrow 微图（15 柱+轴(出发)）
    + 胶囊 aria；与比价互斥（开比价收改期）；Esc 收比价。"""
    _goto(page)
    _details(page)
    row = page.locator("#ftable tbody tr[data-k]:has(.tg)").first
    assert row.count() == 1   # demo 每航线唯一改期胶囊行，首片恰在场
    row.locator(".tg").click()
    page.wait_for_timeout(250)
    assert page.evaluate("TGOPEN !== null && TGOPEN !== undefined")
    tg = page.evaluate(
        "(() => {const cap = document.querySelector('#ftable .tg');"
        "const n = cap.closest('tr').nextElementSibling;"
        "return n.classList.contains('tgrow') ? "
        "{shown: n.style.display !== 'none',"
        "bars: n.querySelectorAll('.tgb').length,"
        "axis: n.querySelector('.tgaxis').textContent} : null;})()")
    assert tg and tg["shown"] and tg["bars"] == 15, tg
    assert "(出发)" in tg["axis"], tg
    assert page.get_attribute("#ftable .tg", "aria-expanded") == "true"
    row.locator("td.price").click()   # 开比价 → 互斥收改期
    page.wait_for_timeout(250)
    assert page.evaluate("EXP !== null")
    assert page.evaluate("JSON.stringify(TGOPEN)") == "null"
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.evaluate("JSON.stringify(EXP)") == "null"


def test_dt05_chip_families_date_route_plat(page):
    """日期/航线/渠道三片族：真实点击 → FLT 集合写入 + 片高亮 + fcnt
    收缩 + fltN 角标亮 1；重置回位（角标隐藏）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[1]
        for sel, key in [("#datechips .chip[data-d]", "dates"),
                         ("#routechips .chip[data-r]", "routes"),
                         ("#platchips .chip[data-p]", "plats")]:
            loc = page.locator(sel).first
            loc.click()
            page.wait_for_timeout(300)
            flt = _flt(page)
            assert len(flt[key]) == 1, (key, flt)
            assert loc.get_attribute("aria-pressed") == "true"
            shown, _t = _fcnt(page)
            assert 0 < shown < total, (key, shown, total)
            assert page.evaluate(
                "document.getElementById('fltN').style.display") == ""
            assert page.inner_text("#fltN") == "1"
            loc.click()   # 再点取消（空集=全部）
            page.wait_for_timeout(250)
        page.locator("#fltwrap button[onclick*='resetFltUI']").click()
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('fltN').style.display") == "none"
    finally:
        _restore(page, snap)


def test_dt06_window_price_search_nostale(page):
    """时段窗/价格上下限/搜索/补位开关：wdep 上午片 → FLT.dep 分钟窗 +
    行出发全落窗内；fpmax fill → FLT.pmax + 收缩；fq fill → FLT.q +
    行名全含关键词；fnostale check → FLT.no（demo 零补位行，计数不变）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        page.locator("#wdep .schip[data-w='06:00|12:00']").click()
        page.wait_for_timeout(300)
        assert _flt(page)["dep"] == ["06:00", "12:00"]
        deps = page.evaluate(
            "[...document.querySelectorAll('#ftable tbody tr[data-k]')]"
            ".map(r=>r.querySelectorAll('td')[4].textContent)")
        assert deps and all("06:00" <= d < "12:00" for d in deps), deps
        page.locator("#wdep .schip[data-w='']").click()   # 回「不限」
        page.wait_for_timeout(250)
        total = _fcnt(page)[0]
        page.locator("#fpmax").fill("1600")
        page.wait_for_timeout(600)
        assert _flt(page)["pmax"] == 1600
        shown, _t = _fcnt(page)
        assert 0 < shown < total, (shown, total)   # 中转低价档在场、直飞高价档出局
        page.locator("#fpmax").fill("")
        page.wait_for_timeout(500)
        page.locator("#fq").fill("CZ")
        page.wait_for_timeout(600)
        assert _flt(page)["q"] == "CZ"
        names = page.evaluate(
            "[...document.querySelectorAll('#ftable tbody tr[data-k]')]"
            ".map(r=>r.querySelectorAll('td')[3].textContent)")
        assert names and all("CZ" in n for n in names), names[:5]
        page.locator("#fq").fill("")
        page.wait_for_timeout(500)
        before = _fcnt(page)[0]
        page.locator("#fnostale").check()
        page.wait_for_timeout(400)
        assert _flt(page)["no"] is True
        assert _fcnt(page)[0] == before   # demo 零补位行：计数不增不减
        page.locator("#fnostale").uncheck()
        page.wait_for_timeout(300)
    finally:
        _restore(page, snap)


def test_dt07_attr_chips_airline_cabin_airports(page):
    """属性片族 togSet：航司/舱位/出发机场/到达机场 chips → FLT 集合
    写入 + 片高亮 + 结果集随行；机型组=自适应显隐（demo planeSize 单值
    → 整组隐藏，r320 R2 克制律）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[0]
        for sel, key in [("#alchips .chip", "airlines"),
                         ("#cabchips .chip", "cabins"),
                         ("#depchips .chip", "depA"),
                         ("#archips .chip", "arrA")]:
            loc = page.locator(sel).first
            loc.click()
            page.wait_for_timeout(300)
            flt = _flt(page)
            assert len(flt[key]) == 1, (key, flt)
            assert "true" == loc.get_attribute("aria-pressed")
            assert _fcnt(page)[0] <= total
            loc.click()
            page.wait_for_timeout(250)
        ps_disp = page.evaluate(
            "(() => {const w = document.querySelector("
            "'#fltwrap [data-flt=\"ps\"]');"
            "return w ? w.style.display : 'missing';})()")
        ps_vals = page.evaluate(
            "[...new Set(S.users[U].flights.map(f=>f.planeSize).filter(Boolean))]")
        if len(ps_vals) < 2:
            assert ps_disp == "none", (ps_disp, ps_vals)
    finally:
        _restore(page, snap)


def test_dt08_switch_few_safe_adaptive_hidden(page):
    """余票紧张/隐藏限购开关（demo 在场维度）：check → FLT 写入 + 收缩；
    经停/共享组=自适应显隐（demo 零 stop/share 行 → 整组隐藏）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[0]
        page.locator("#ffew").check()
        page.wait_for_timeout(400)
        assert _flt(page)["few"] is True
        assert 0 < _fcnt(page)[0] < total
        page.locator("#ffew").uncheck()
        page.wait_for_timeout(300)
        page.locator("#fsafe").check()
        page.wait_for_timeout(400)
        assert _flt(page)["safe"] is True
        assert _fcnt(page)[0] < total
        page.locator("#fsafe").uncheck()
        page.wait_for_timeout(300)
        for grp in ("nostop", "noshare"):
            has = page.evaluate(
                "S.users[U].flights.some(f=>f.%s)" % ("stop" if grp == "nostop"
                                                      else "shareCarrier"))
            disp = page.evaluate(
                "(() => {const w = document.querySelector("
                "'#fltwrap [data-flt=\"%s\"]');"
                "return w ? w.style.display : 'missing';})()" % grp)
            if not has:
                assert disp == "none", (grp, disp)
    finally:
        _restore(page, snap)


def test_dt09_moreflt_eight_dims(page):
    """更多筛选八维：真实展开（aria+箭头词）→ 时长上限/准点率/机龄三
    数值框 fill + 托运/餐食/廉航三开关 check → FLT 写入 + 结果集随行 +
    morefltN 角标=生效数；经停/共享/跨天/儿童=自适应显隐（demo 零值）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[0]
        page.locator("#morefltBtn").click()
        page.wait_for_timeout(250)
        assert page.evaluate(
            "document.getElementById('moreflt').style.display") == ""
        assert page.get_attribute("#morefltBtn", "aria-expanded") == "true"
        page.locator("#fdurmax").fill("400")
        page.wait_for_timeout(600)
        assert _flt(page)["durmax"] == 400
        mid = _fcnt(page)[0]
        assert 0 < mid < total
        assert page.evaluate(
            "[...document.querySelectorAll('#ftable tbody tr[data-k] .tag')]"
            ".every(t=>t.textContent !== '中转')")
        page.locator("#fprate").fill("87")
        page.wait_for_timeout(600)
        assert _flt(page)["prate"] == 87
        prat = _fcnt(page)[0]
        assert 0 < prat < mid   # demo 仅 ctrip 首行 prate='87'
        page.locator("#fage").fill("7")
        page.wait_for_timeout(600)
        assert _flt(page)["age"] == 7
        assert 0 < _fcnt(page)[0] <= prat
        for cid, key in [("fbag", "bag"), ("fmeal", "meal"),
                         ("fnolcc", "nolcc")]:
            page.locator("#" + cid).check()
            page.wait_for_timeout(400)
            assert _flt(page)[key] is True
            page.locator("#" + cid).uncheck()
            page.wait_for_timeout(300)
        badge = page.evaluate(
            "(() => {const b = document.getElementById('morefltN');"
            "return [b.style.display, b.textContent];})()")
        assert badge[0] == "" and badge[1] == "3", badge   # 时长/准点/机龄
        for grp, probe in [("cross", "Number(f.crossDayN)>0"),
                           ("child", "f.childPrice!=null")]:
            has = page.evaluate("S.users[U].flights.some(f=>%s)" % probe)
            disp = page.evaluate(
                "(() => {const l = document.getElementById("
                "{'cross':'fcross','child':'fchild'}['%s']);"
                "return l ? l.closest('.flab').style.display : 'missing';"
                "})()" % grp)
            if not has:
                assert disp == "none", (grp, disp)
        page.locator("#fltwrap button[onclick*='resetFltUI']").click()
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('morefltN').style.display") == "none"
    finally:
        _restore(page, snap)


# r324 DT-10 已修复转正（resetFlt 补 depA/arrA 复位 + updFltN 入册计数）：
# 原 RED-1 xfail(strict) 在修复落地当日 XPASS，摘标记转常态回归钉。
def test_dt10_red_reset_must_clear_airport_filters(page):
    """RED-1 钉：机场 chip 点亮 → 重置筛选与排序 → FLT.depA/arrA 必须清
    空 + 片熄灭 + 结果集复位。当前实现三面全劈叉。"""
    _goto(page)
    _details(page)
    page.locator("#depchips .chip").first.click()
    page.wait_for_timeout(300)
    assert _flt(page)["depA"], "前置：depA 已写"
    assert _fcnt(page)[0] < _fcnt(page)[1]
    page.locator("#fltwrap button[onclick*='resetFltUI']").click()
    page.wait_for_timeout(400)
    flt = _flt(page)
    assert flt["depA"] == [] and flt["arrA"] == [], flt
    assert page.evaluate(
        "document.querySelector('#depchips .chip')"
        ".classList.contains('on')") is False
    assert _fcnt(page)[0] == _fcnt(page)[1]


def test_dt11_csv_export_download(page):
    """CSV 导出：真实点击 → download 事件（文件名 flights_YYYYMMDD_HHMM
    .csv）+ 表头首列「价格」+ 成功 toast 行数与 fcnt 一致。"""
    import re
    _goto(page)
    _details(page)
    shown, _t = _fcnt(page)
    with page.expect_download(timeout=8000) as dl:
        page.locator("#fltwrap button[onclick*='expCsv']").click()
    d = dl.value
    assert re.match(r"flights_\d{8}_\d{4}\.csv$", d.suggested_filename), \
        d.suggested_filename
    path = d.path()
    with open(path, encoding="utf-8-sig") as fh:
        head = fh.readline().strip()
    assert head.startswith('"价格"'), head[:40]
    assert ("📤 已导出 %d 行 CSV" % shown) in _toasts(page), _toasts(page)


def test_dt12_scroll_chunk_integrity(page):
    """滚动续载完整性：真实滚轮滚底 → 续载补全至全量（DOM 行数=
    fcnt=_ROWS.length）、已渲片数覆盖全量（片数随数据面走——demo
    115 班单片形态已成 185 班两片，硬编码 NDRAW=1 在扩容当日即红），
    零错（完整性=不丢行不报错）。"""
    _goto(page)
    _details(page)
    shown, _t = _fcnt(page)
    page.locator("#tablecard .tw").hover()
    page.mouse.wheel(0, 20000)   # 真实滚轮路径滚到底
    page.wait_for_timeout(400)
    n = page.evaluate(
        "document.querySelectorAll('#ftable tbody tr[data-k]').length")
    assert n == shown == page.evaluate("_ROWS.length"), (n, shown)
    assert page.evaluate("_NDRAW * _CHUNK") >= page.evaluate(
        "_ROWS.length"), (page.evaluate("_NDRAW"),
                          page.evaluate("_ROWS.length"))


def test_dt13_sticky_first_column(page):
    """首列吸附：价格格/表头 position:sticky + left:0 + z-index 在场
    （投影面钉；1440 无横滚溢出，滚动路径由 390 档钉组覆盖）。"""
    _goto(page)
    _details(page)
    st = page.evaluate(
        "(() => {const th = document.querySelector('#ftable th');"
        "const td = document.querySelector('#ftable td');"
        "const a = getComputedStyle(th), b = getComputedStyle(td);"
        "return [a.position, a.left !== 'auto', a.zIndex !== 'auto',"
        "b.position];})()")
    assert st[0] == "sticky" and st[3] == "sticky", st
    assert st[1] and st[2], st


# ================= §四 健康 =================

def test_hl01_cell_click_round_log(page):
    """健康格点击 → 渠道轮日志弹层（GET /api/logtail 真链）：pvTitle
    渠道｜轮次 + logpre 在场 + aria-label 随入口 + demo 底注词面；
    Esc 关闭。"""
    _goto(page)
    _mtab(page, "health")
    page.wait_for_timeout(600)
    assert page.evaluate(
        "document.querySelectorAll('#hbody .hrow').length") >= 5
    page.locator("#hbody .hc:not(.none)").first.click()
    page.wait_for_timeout(900)
    assert page.evaluate(
        "document.getElementById('pvMask').classList.contains('on')")
    title = page.inner_text("#pvTitle")
    assert title.startswith("📄") and "轮日志" in title, title
    assert page.evaluate(
        "!!document.querySelector('#pvMask .logpre')")
    assert page.get_attribute("#pvMask .pvcard", "aria-label") == "渠道轮日志"
    assert "演示模式 · 合成轮日志回放" in page.inner_text("#pvFoot")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.evaluate(
        "!document.getElementById('pvMask').classList.contains('on')")


def test_hl02_push_channels_render(page):
    """推送通道行（renderPushChannels 投影）：demo 钉钉连败在场 →
    「连败 N」红态 + 通道行 ≥1 + 近 24h 词面。"""
    _goto(page)
    _mtab(page, "health")
    page.wait_for_timeout(600)
    body = page.inner_text("#pushhl")
    assert "推送通道 · 近 24h" in body, body[:60]
    rows = page.evaluate(
        "document.querySelectorAll('#pushhl .hrow').length")
    assert rows >= 1
    assert "连败" in body   # demo 钉钉 fail_streak>0


def test_hl03_pulse_bar_jump_health_flash(page):
    """脉冲柱点击 → gotoPulseHealth：切健康子栏 + 失败渠道行辉光
    （hflash 双行）——状态落地非「跳到区域」。"""
    _goto(page)
    _mtab(page, "overview")
    page.wait_for_function(
        "document.querySelectorAll('#pulsebars .pbar').length > 0")
    idx = page.evaluate(
        "[...document.querySelectorAll('#pulsebars .pbar')]"
        ".findIndex(p=>p.dataset.bad)")
    assert idx >= 0   # demo 有失败轮
    page.locator("#pulsebars .pbar").nth(idx).click()
    page.wait_for_timeout(500)
    assert page.evaluate("MONTAB") == "health"
    assert page.evaluate(
        "document.querySelectorAll('#hbody .hflash').length") >= 1


# ================= §五 弹层 =================

def test_pv01_preview_open_esc_focus_return(page):
    """推送预览（demo /api/preview 豁免门=真 POST 全链）：真实点击 →
    🚨 标题 + 正文链接 + aria-label/底注随入口；Esc 关闭 + 焦点归还
    开启者 + 滚动锁解除。"""
    _goto(page)
    with page.expect_response(lambda r: "/api/preview" in r.url,
                              timeout=30000):
        page.locator("#pvBtn").click()
    page.wait_for_timeout(400)
    assert page.inner_text("#pvTitle").startswith("🚨")
    assert page.evaluate(
        "document.querySelectorAll('#pvBody a').length") > 0
    assert page.get_attribute("#pvMask .pvcard", "aria-label") == "钉钉推送预览"
    assert "近似渲染" in page.inner_text("#pvFoot")
    assert page.evaluate("document.body.style.overflow") == "hidden"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.evaluate(
        "!document.getElementById('pvMask').classList.contains('on')")
    assert page.evaluate("document.activeElement && "
                         "document.activeElement.id") == "pvBtn"
    assert page.evaluate("document.body.style.overflow") == ""


def test_pv02_preview_tab_focus_trap(page):
    """弹层 Tab 焦点圈闭：关闭钮 Shift+Tab → 尾焦点件；再 Tab → 首件
    （不逃逸背景页）。"""
    _goto(page)
    with page.expect_response(lambda r: "/api/preview" in r.url,
                              timeout=30000):
        page.locator("#pvBtn").click()
    page.wait_for_timeout(400)
    page.locator("#pvClose").focus()
    page.keyboard.press("Shift+Tab")
    page.wait_for_timeout(150)
    last_tag = page.evaluate(
        "document.activeElement.tagName + '|' + document.activeElement.className")
    assert last_tag.split("|")[0] == "A", last_tag   # 尾=正文链接
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def test_pv03_pushlog_open_expand(page):
    """推送记录弹层：真实点击 → 📨 标题 + 条目在场 + aria-label/底注随
    入口；点击条目展开全文（display 切换零插拔）；Esc 关闭。"""
    _goto(page)
    page.locator("button[onclick*='pushLog']").click()
    page.wait_for_timeout(800)
    assert "推送记录" in page.inner_text("#pvTitle")
    assert page.get_attribute("#pvMask .pvcard", "aria-label") == "推送记录"
    assert "合成推送记录回放" in page.inner_text("#pvFoot")   # demo 底注词面
    n = page.evaluate("document.querySelectorAll('.plitem').length")
    assert n >= 1
    page.locator(".plitem").first.click()
    page.wait_for_timeout(200)
    assert page.evaluate(
        "document.querySelector('.pldesp').style.display") == ""
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.evaluate(
        "!document.getElementById('pvMask').classList.contains('on')")


def test_ops01_run_button_arming_then_403(page):
    """立即扫描（api 双拍确认机制完整走通）：一拍=arming 态词面锁定；
    二拍=真 POST /api/run → demo 只读门 403 → 失败 toast 词面钉 +
    按钮复原（真实失败分支，无任何真实副作用）。"""
    _goto(page)
    btn = page.locator("#opscard button").first
    btn.click()
    page.wait_for_timeout(200)
    assert page.evaluate(
        "document.querySelector('#opscard button').dataset.arming") == "1"
    assert page.inner_text("#opscard button") == "⚠ 再点一次确认"
    btn.click()
    page.wait_for_timeout(1200)
    assert "❌ 失败: 演示模式只读——下载源码或 zip 即可真跑" in _toasts(page), \
        _toasts(page)
    assert page.inner_text("#opscard button") == "立即扫描一轮"
    assert page.evaluate(
        "document.querySelector('#opscard button').dataset.arming") is None


def test_ops02_hotkey_r_two_step_403(page):
    """R 快捷键立即扫描（keyRun 两段确认）：一按=警告 toast；三秒内
    二按=真 POST → 403 失败 toast 词面钉。"""
    _goto(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("r")
    page.wait_for_timeout(250)
    assert "⚠ 再按一次 R 确认立即扫描全部航线" in _toasts(page)
    page.keyboard.press("r")
    page.wait_for_timeout(1200)
    assert "❌ 失败: 演示模式只读——下载源码或 zip 即可真跑" in _toasts(page), \
        _toasts(page)


def test_login_panel_open_and_leave(page):
    """配置页登录卡面板：cnav 真实点击打开 → 5 渠道卡 + 「弹窗登录」
    词面在场（绝不点击——loginStart 生产态弹真窗）；切走=取消语义
    （面板隐藏、无任何 POST）。"""
    _goto(page)
    page.locator("#navCfg").click()
    page.wait_for_timeout(1500)
    page.locator("#cfgnav .cnav[data-p='login']").click()
    page.wait_for_timeout(800)
    assert page.is_visible("#panel-login")
    assert page.evaluate(
        "document.querySelectorAll('#loginRows .lgcard').length") == 5
    assert "弹窗登录" in page.inner_text("#loginRows")
    page.locator("#navMon").click()
    page.wait_for_timeout(400)
    assert page.evaluate("VIEW") == "mon"
    assert not page.is_visible("#cfgview")


# ================= §六 全局 =================

def test_gl01_theme_three_state_cycle(page):
    """主题三态：真实点击 themeBtn 循环 auto→light→dark：localStorage
    jptheme + html data-theme + 按钮 data-mode + aria-label 态名四面同拍。"""
    _goto(page)
    theme0 = page.evaluate("localStorage.getItem('jptheme')")
    assert theme0 in (None, "auto", "light", "dark")
    page.locator("#themeBtn").click()
    page.wait_for_timeout(250)
    assert page.evaluate("localStorage.getItem('jptheme')") == "light"
    assert page.evaluate(
        "document.documentElement.dataset.theme") == "light"
    assert page.get_attribute("#themeBtn", "data-mode") == "light"
    assert "亮色" in page.get_attribute("#themeBtn", "aria-label")
    page.locator("#themeBtn").click()
    page.wait_for_timeout(250)
    assert page.evaluate("localStorage.getItem('jptheme')") == "dark"
    assert page.evaluate(
        "document.documentElement.dataset.theme") == "dark"
    assert page.get_attribute("#themeBtn", "data-mode") == "dark"
    assert "暗色" in page.get_attribute("#themeBtn", "aria-label")


def test_gl02_theme_reload_persist(page):
    """主题持久：dark 落 localStorage → 真实重载 → 暗色保持（html
    data-theme + 按钮 data-mode=dark）；auto 档重载后跟随系统（headless=light）。"""
    _goto(page)
    page.locator("#themeBtn").click()   # →light
    page.locator("#themeBtn").click()   # →dark
    page.wait_for_timeout(250)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(400)
    assert page.evaluate("localStorage.getItem('jptheme')") == "dark"
    assert page.evaluate(
        "document.documentElement.dataset.theme") == "dark"
    assert page.get_attribute("#themeBtn", "data-mode") == "dark"


def test_gl03_hotkey_views_and_tabs(page):
    """快捷键 1/2 视图 + 3-6 分栏（含配置视图直达——gotoMonTab 收口
    路径）：keyboard.press 真按，逐面断言 VIEW/MONTAB/pane。"""
    _goto(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("2")
    page.wait_for_timeout(400)
    assert page.evaluate("VIEW") == "cfg"
    assert page.is_visible("#cfgview")
    page.keyboard.press("5")
    page.wait_for_timeout(500)
    assert page.evaluate("VIEW") == "mon"
    assert page.evaluate("MONTAB") == "details"
    page.keyboard.press("4")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "trend"
    page.keyboard.press("3")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "overview"
    page.keyboard.press("6")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "health"
    page.keyboard.press("1")
    page.wait_for_timeout(300)
    assert page.evaluate("VIEW") == "mon"
    assert page.is_visible("#monview")


def test_gl04_hotkey_slash_focus_search(page):
    """/ 快捷键：真按 → 切明细 + #fq 聚焦选中；接续真实键入 → FLT.q
    写入 + 结果集随行（完整输入管线）。"""
    _goto(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("/")
    page.wait_for_timeout(500)
    assert page.evaluate("MONTAB") == "details"
    assert page.evaluate(
        "document.activeElement && document.activeElement.id") == "fq"
    page.keyboard.type("CZ")
    page.wait_for_timeout(700)
    assert page.evaluate("JSON.stringify(FLT.q)") == '"CZ"'
    names = page.evaluate(
        "[...document.querySelectorAll('#ftable tbody tr[data-k]')]"
        ".map(r=>r.querySelectorAll('td')[3].textContent)")
    assert names and all("CZ" in n for n in names), names[:5]


def test_gl05_esc_cascade_drawer(page):
    """Esc 级联（抽屉支路，≤760 真实抽屉语境）：视口收窄至 390 →
    fltBtn 现身（宽档 fbar 常驻无此钮）→ 真实点击开抽屉（.open+aria）
    → Esc 关闭 + aria 回写 false + 焦点归还 fltBtn（setFltOpen 单源，
    旁路曾绕过）。"""
    _goto(page)
    _details(page)
    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(400)
    # _details opened the desktop filter row; close it so this test starts
    # from the real mobile drawer state before clicking fltBtn.
    page.evaluate("()=>{const fb=document.querySelector('.fbar');"
                  "if(fb&&fb.classList.contains('open'))setFltOpen(false);}")
    page.wait_for_timeout(200)
    assert page.is_visible("#fltBtn")   # ≤760 抽屉唯一入口
    page.locator("#fltBtn").click()
    page.wait_for_timeout(400)
    assert "open" in (page.get_attribute(".fbar", "class") or "")
    assert page.get_attribute("#fltBtn", "aria-expanded") == "true"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert "open" not in (page.get_attribute(".fbar", "class") or "")
    assert page.get_attribute("#fltBtn", "aria-expanded") == "false"
    assert page.evaluate(
        "document.activeElement && document.activeElement.id") == "fltBtn"
    page.set_viewport_size({"width": 1440, "height": 900})


def test_gl06_deeplink_startup(page):
    """URL 深链启动恢复：/#details 与 /#trend/u0（双段）直达对应子栏 +
    hash 保持；/#cfg 直达配置视图。"""
    page.goto(BASE + "/#details", wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "details"
    assert page.evaluate("location.hash") == "#details"
    page.goto(BASE + "/#trend/u0", wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "trend"
    assert page.evaluate("VIEW") == "mon"
    assert page.evaluate("location.hash") == "#trend/u0"
    page.goto(BASE + "/#cfg", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    assert page.evaluate("VIEW") == "cfg"
    assert page.is_visible("#cfgview")


def test_gl07_hashchange_live_and_guard(page):
    """活页 hashchange 消费：手改 hash → 子栏跟随 + 用户段回写；
    越界 /u9 守卫忽略（U 不变；hash 段保留=W30 在案备案）。"""
    _goto(page)
    page.evaluate("location.hash='#health'")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "health"
    assert page.evaluate("location.hash") == "#health/u0"
    page.evaluate("location.hash='#details/u9'")
    page.wait_for_timeout(400)
    assert page.evaluate("U") == 0
    assert page.evaluate("MONTAB") == "details"


def test_gl08_user_pills_single_user(page):
    """用户 pills/吸顶 chip：r368 起单用户也常显当前用户范围（监控视图
    按用户过滤的口径可见；越界深链守卫见 gl07）。"""
    _goto(page)
    assert page.evaluate("(S.users||[]).length") == 1
    assert not page.is_visible("#userPills")
    assert page.is_visible("#mtabUser")
    assert "👤" in page.inner_text("#mtabUser")


def test_gl09_footer_github_and_kbd(page):
    """页脚：GitHub 链接 target=_blank + rel=noopener（真实点击会离站，
    只钉属性面）+ 快捷键教学词面在场。"""
    _goto(page)
    assert page.get_attribute("#foot a", "target") == "_blank"
    assert "noopener" in (page.get_attribute("#foot a", "rel") or "")
    assert page.evaluate("document.querySelectorAll('#foot .kbd').length") >= 4


# ================= §七 空态 =================

def test_empty01_all_suspended_hero(page):
    """停用全部航线空态（route 拦截 /api/state 构造 suspended 载荷=
    load→render 网络入口全链，不 POST、不改服务端）：hero ⏸️ 词面 +
    停用清单 + pill「已全停用」+ montabs/opscard/图表/脉冲全回收 +
    前往配置启用按钮。"""
    import json
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    st = json.loads(op.open(BASE + "/api/state", timeout=3)
                    .read().decode("utf-8"))
    u0 = st["users"][0]
    emp = dict(st)
    emp["users"] = []
    emp["suspended"] = [{"name": u0["name"], "n": len(u0["routesArr"]),
                         "routesTxt": u0["routesTxt"]}]

    def _route(route, request):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(emp, ensure_ascii=False))
    page.route("**/api/state", _route)
    try:
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(900)
        hero = page.evaluate(
            "(() => {const h = document.querySelector('#users .hero');"
            "return h ? h.textContent : '';})()")
        assert "航线已全部停用" in hero, hero[:80]
        assert u0["name"] in hero   # 停用清单词面（与「从未配置」分立）
        assert page.inner_text("#pill") == "已全停用"
        assert page.evaluate(
            "document.getElementById('montabs').style.display") == "none"
        assert page.evaluate(
            "document.getElementById('opscard').style.display") == "none"
        assert page.evaluate(
            "document.getElementById('chartcard').style.display") == "none"
        assert page.evaluate(
            "document.getElementById('pulsecard').style.display") == "none"
        assert page.evaluate(
            "(() => {const b = [...document.querySelectorAll('#users button')]"
            ".find(b => b.textContent.indexOf('前往配置启用') >= 0);"
            "return !!b;})()")
    finally:
        page.unroute("**/api/state")
