# -*- coding: utf-8 -*-
"""r324 入场监控套件的共享夹具与助手（r490 从 test_r324_entry_mon.py 抽出）。

主题文件用 from entry_mon_harness import srv, page, ... 复用同一套
module 级 demo 服务 + 每用例独立浏览器上下文；拆文件只为让 xdist
按文件并行，用例语义与断言不动。
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
        pg._r324_base = BASE
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
