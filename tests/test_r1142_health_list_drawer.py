# -*- coding: utf-8 -*-
"""r1142：渠道健康“单行列表 + 行内详情”契约（真实渲染 + 负控）。

用户约束（2026-11-10）：全站不使用侧边抽屉。每行只回答
「哪家 / 现在怎样 / 成功率 / 国内国际 / 详情」；分域、通路、会话、
停服说明与自检全部在该行正下方的整宽行内面板展开；节流计划默认
折成 44px 摘要条。行内第二段证据、每行自检按钮、常驻节流面板以及
右侧抽屉都要有门禁防止回潮。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(BASE + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_health(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=(width <= 600), has_touch=(width <= 600))
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof showMonTab==='function'", timeout=25000)
    page.evaluate("switchView('mon');showMonTab('health')")
    page.wait_for_function("document.querySelectorAll('#hbody .hrow').length>0", timeout=25000)
    page.wait_for_timeout(900)
    return ctx, page, errs


SNAP = """() => {
  const vis=e=>{const r=e.getBoundingClientRect();return r.width>0.5&&r.height>0.5};
  const rows=[...document.querySelectorAll('#hbody .hrow')].filter(vis);
  const info=rows.map(r=>{
    const cs=getComputedStyle(r), cells=r.querySelector('.hcells');
    const act=r.querySelector('.hrowact'), badge=r.querySelector('.hbadge');
    const hs=r.querySelector('.hsum');
    const det=r.nextElementSibling&&r.nextElementSibling.classList.contains('hcdet')
      ? r.nextElementSibling : null;
    return {h:+r.getBoundingClientRect().height.toFixed(1),
      left:+r.getBoundingClientRect().left.toFixed(1),
      right:+r.getBoundingClientRect().right.toFixed(1),
      bottom:+r.getBoundingClientRect().bottom.toFixed(1),
      cols:cs.gridTemplateColumns.trim().split(/\\s+/).length,
      btns:r.querySelectorAll('[data-hcdetail]').length,
      scope:r.querySelectorAll('.hscope,.hpath,.hslots').length,
      hasDet:!!det, detHidden:det?det.hidden:null,
      cellsW:cells?+cells.getBoundingClientRect().width.toFixed(1):0,
      segs:cells?cells.querySelectorAll('.hseg').length:0,
      cells:cells?cells.querySelectorAll('.hc').length:0,
      btnH:act&&act.querySelector('button')?+act.querySelector('button').getBoundingClientRect().height.toFixed(1):0,
      btnAria:act&&act.querySelector('button')?act.querySelector('button').getAttribute('aria-expanded'):null,
      btnTxt:act&&act.querySelector('button')?act.querySelector('button').textContent:'',
      badgeR:badge?+badge.getBoundingClientRect().right.toFixed(1):null,
      actR:act?+act.getBoundingClientRect().right.toFixed(1):null,
      hsum:hs?hs.innerText:''};
  });
  const f=document.getElementById('hpaceFold'), sum=f.querySelector('summary');
  const push=document.getElementById('pushhl');
  return {rows:info, n:info.length,
    fold:{open:f.open,h:+f.getBoundingClientRect().height.toFixed(1),
          sumH:+sum.getBoundingClientRect().height.toFixed(1)},
    pushAfter:!!(f.compareDocumentPosition(push)&Node.DOCUMENT_POSITION_FOLLOWING),
    noscopes:document.getElementById('hbody').classList.contains('noscopes'),
    over:document.documentElement.scrollWidth-document.documentElement.clientWidth,
    hasDrawer:!!document.getElementById('hcDrawer')};
}"""


def snap(page):
    return page.evaluate(SNAP)


def detail(page):
    return page.evaluate(
        """() => {const p=document.querySelector('#hbody .hcdet:not([hidden])');
          if(!p)return {hidden:true,
            focusIsBtn:!!(document.activeElement&&document.activeElement.matches
              &&document.activeElement.matches('#hbody [data-hcdetail]'))};
          const r=p.getBoundingClientRect();
          const b=document.querySelector('#hbody [data-hcdetail][aria-expanded="true"]');
          return {hidden:false,w:+r.width.toFixed(1),h:+r.height.toFixed(1),
            left:+r.left.toFixed(1),top:+r.top.toFixed(1),
            sections:p.querySelectorAll('.hcd-sec').length,
            scope:!!p.querySelector('.hscope'),path:!!p.querySelector('.hpath'),
            slots:!!p.querySelector('.hslots'),
            fallback:/无分域\\/通路样本/.test(p.innerText),
            acts:p.querySelectorAll('.hcd-acts button').length,
            focusInPanel:p.contains(document.activeElement),
            focusIsBtn:!!(b&&document.activeElement===b),
            bodyOverflow:getComputedStyle(document.body).overflow,
            mask:!!document.querySelector('.hcmask')};}"""
    )


def test_desktop_single_line_rows_and_inline_detail(srv, browser):
    ctx, page, errs = open_health(browser, 1440, 1000)
    try:
        d = snap(page)
        assert not errs, errs
        assert d["over"] <= 0
        assert d["n"] == 10, "健康行数 %s" % d["n"]
        assert d["hasDrawer"] is False, "侧边抽屉 #hcDrawer 已废弃，不得回流"
        for i, r in enumerate(d["rows"]):
            assert r["h"] <= 56, "第%d行 %.1fpx > 56" % (i + 1, r["h"])
            assert r["btns"] == 1, "第%d行详情按钮 %d 个" % (i + 1, r["btns"])
            assert r["scope"] == 0, "第%d行仍有行内证据段" % (i + 1)
            assert r["hasDet"], "第%d行缺行内详情容器" % (i + 1)
            assert r["detHidden"] is True, "第%d行详情默认应收起" % (i + 1)
            assert r["btnAria"] == "false" and r["btnTxt"] == "详情"
            assert r["segs"] == 6 and r["cells"] == 24, "第%d行时间段 %s/%s" % (i + 1, r["segs"], r["cells"])
            assert r["cellsW"] >= 700, "第%d行时间线宽 %.1f" % (i + 1, r["cellsW"])
            assert 28 <= r["btnH"] <= 32, "桌面详情按钮 %.1fpx" % r["btnH"]
        assert d["fold"]["open"] is False, "节流应默认折叠"
        assert 42 <= d["fold"]["sumH"] <= 46, "节流摘要 %.1fpx" % d["fold"]["sumH"]
        assert d["pushAfter"], "推送通道应排在节流折叠条之后"
        # 演示无分域样本：不留第五列空位
        assert d["noscopes"] is True
        assert all(r["cols"] == 4 for r in d["rows"]), [r["cols"] for r in d["rows"]]

        page.click("#hbody .hrow [data-hcdetail]")
        page.wait_for_timeout(300)
        det = detail(page)
        assert det["hidden"] is False
        row = snap(page)["rows"][0]
        # 整宽行内面板：与所属行同边、正下方、无侧边抽屉/遮罩/滚动锁
        assert abs(det["left"] - (row["left"] + 2)) <= 1.5, "面板未对齐行左缘"
        assert abs(det["w"] - (row["right"] - row["left"] - 4)) <= 1.5, "面板宽度不是整行宽"
        assert det["top"] >= row["bottom"] - 0.5, "面板未落在行下方"
        assert det["sections"] >= 2, "面板缺分域/操作段"
        assert det["acts"] >= 1, "面板缺自检动作"
        assert det["fallback"] or det["path"], "面板没有可读内容"
        assert det["mask"] is False, "行内详情不应有遮罩"
        assert det["bodyOverflow"] != "hidden", "行内详情不应锁滚动"
        after = snap(page)["rows"][0]
        assert after["btnAria"] == "true" and after["btnTxt"] == "收起"

        # Esc 收起并把焦点还给触发器
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        back = detail(page)
        assert back["hidden"] is True
        assert back.get("focusIsBtn"), "Esc 后焦点未回详情按钮"
        assert snap(page)["rows"][0]["btnTxt"] == "详情"

        # 行内详情不是模态：点击外部不关闭；再点按钮才收起
        page.click("#hbody .hrow [data-hcdetail]")
        page.wait_for_timeout(200)
        page.mouse.click(40, 500)
        page.wait_for_timeout(200)
        assert detail(page)["hidden"] is False, "行内详情被外部点击误关"
        page.click("#hbody .hrow [data-hcdetail]")
        page.wait_for_timeout(200)
        assert detail(page)["hidden"] is True
        assert snap(page)["over"] <= 0
    finally:
        ctx.close()


def test_mobile_rows_and_inline_detail(srv, browser):
    ctx, page, errs = open_health(browser, 390, 844)
    try:
        d = snap(page)
        assert not errs, errs
        assert d["over"] <= 0
        assert d["n"] == 10
        for i, r in enumerate(d["rows"]):
            assert 60 <= r["h"] <= 90, "第%d行 %.1fpx 不在 60–90" % (i + 1, r["h"])
            assert r["cols"] == 4, "第%d行 %d 列（应留出详情列）" % (i + 1, r["cols"])
            assert r["btns"] == 1
            assert r["scope"] == 0
            assert r["hasDet"] and r["detHidden"] is True
            assert r["segs"] == 6 and r["cells"] == 24
            assert r["cellsW"] >= 300, "第%d行时间线宽 %.1f < 300" % (i + 1, r["cellsW"])
            assert r["btnH"] >= 36, "触摸详情按钮 %.1f < 36" % r["btnH"]
        page.click("#hbody .hrow [data-hcdetail]")
        page.wait_for_timeout(300)
        det = detail(page)
        row = snap(page)["rows"][0]
        assert det["hidden"] is False
        assert det["w"] >= row["right"] - row["left"] - 5, "窄档面板未满行宽 %.1f" % det["w"]
        assert det["sections"] >= 2
        assert det["acts"] >= 1
        assert det["fallback"] or det["path"], "窄档面板没有可读内容"
        assert page.evaluate(
            "document.documentElement.scrollWidth-innerWidth") <= 1, "详情展开后横向溢出"
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert detail(page)["hidden"] is True
    finally:
        ctx.close()


def test_push_summary_when_all_healthy(srv, browser):
    ctx, page, errs = open_health(browser, 1440, 1000)
    try:
        r = page.evaluate(
            """() => {const el=document.getElementById('pushhl');
              const before=el.innerHTML;
              renderPushChannels({channels:{email:{ok:18,fail:0,fail_streak:0,
                last:'11-10 07:00',last_ok:'11-10 07:00'}}});
              const out={rows:el.querySelectorAll('.hrow').length,
                txt:el.innerText.replace(/\s+/g,' '),
                muted:!!el.querySelector('.muted')};
              el.innerHTML=before;
              return out;}"""
        )
        assert not errs, errs
        assert r["rows"] == 0, "全绿时仍渲染逐通道行"
        assert r["muted"] and "全部正常" in r["txt"], r
    finally:
        ctx.close()


def test_scoped_rows_keep_alignment(srv, browser):
    ctx, page, errs = open_health(browser, 1440, 1000)
    try:
        page.evaluate(
            """async () => {
              const j=await (await fetch('/api/health')).json();
              j.paths=j.paths||{};
              Object.keys(j.stats||{}).forEach((k,i)=>{
                const p=j.paths[k]||(j.paths[k]={});
                p.scopes={dom:{query_attempts:40,query_rate_live:i%2?0.98:0.93},
                          intl:{query_attempts:30,query_rate_live:i%3?0.86:0.99}};});
              renderHealth(j);
            }"""
        )
        page.wait_for_timeout(300)
        d = snap(page)
        assert not errs, errs
        assert d["noscopes"] is False
        assert all(r["cols"] == 5 for r in d["rows"]), [r["cols"] for r in d["rows"]]
        assert all(r["hsum"] for r in d["rows"]), "有分域样本却无摘要列"
        assert all(r["btns"] == 1 for r in d["rows"])
        page.click("#hbody .hrow [data-hcdetail]")
        page.wait_for_timeout(250)
        det = detail(page)
        assert det["hidden"] is False and det["path"], "通路明细未渲染进行内面板"
        for key in ("badgeR", "actR"):
            vals = [r[key] for r in d["rows"]]
            assert max(vals) - min(vals) <= 1.5, "%s 各行未对齐: %s" % (key, vals)
    finally:
        ctx.close()


def test_negative_probes_detect_regressions(srv, browser):
    ctx, page, _ = open_health(browser, 1440, 1000)
    try:
        page.evaluate(
            """() => {const r=document.querySelector('#hbody .hrow');
              const b=document.createElement('button');
              b.setAttribute('data-hcdetail','x');r.appendChild(b);}"""
        )
        assert snap(page)["rows"][0]["btns"] == 2, "重复详情按钮未被数到"
        page.evaluate(
            """() => {const r=document.querySelector('#hbody .hrow');
              r.style.setProperty('height','90px','important');
              r.style.setProperty('min-height','90px','important');}"""
        )
        assert snap(page)["rows"][0]["h"] >= 89, "行高负控未被量到"
        page.evaluate(
            """() => {const r=document.querySelector('#hbody .hrow');
              const s=document.createElement('span');s.className='hscope';s.textContent='x';
              r.appendChild(s);}"""
        )
        assert snap(page)["rows"][0]["scope"] == 1, "行内证据负控未被数到"
    finally:
        ctx.close()
