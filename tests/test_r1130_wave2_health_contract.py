# -*- coding: utf-8 -*-
"""r1130：2026-11-07 渠道健康整体重排契约（P0）。

1) 诊断条压缩：标题 + 最近一轮 + PC/H5/登录态三胶囊；逐渠道说明默认折叠，
   展开体为浮层（不推矩阵）；
2) 健康矩阵上移首屏：10 家渠道统一行（图标/中文名/格带/徽标/自检），左右缘对齐；
3) 去哪儿停服只在去哪儿行出现一次，不再独立横幅；
4) 节流 10 行；溯源默认折叠、展开为轻块（非卡片），首行 y 不变。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="健康页契约依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [1440, 390]


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1130h_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


def _open_health(pg):
    pg.evaluate("()=>switchView('mon')")
    pg.wait_for_timeout(350)
    pg.click("text=渠道健康")
    pg.wait_for_timeout(2000)
    # r1147：「节流与干预」默认折叠；展开后行文本/高度才可测。
    pg.evaluate("()=>{const f=document.getElementById('hpaceFold');"
                "if(f)f.open=true;}")
    # 健康矩阵与节流行都是异步二次渲染；固定 2s 在 xdist 并发下会量到
    # 「行数 0」或不可见的空壳。等到首行真有高度再读，仍为空则照常判红。
    pg.wait_for_function(
        "()=>{const r=document.querySelector('#hbody .hrow');"
        "return r&&r.getBoundingClientRect().height>1"
        "&&document.querySelectorAll('#paceBox .pace-row').length>=10}",
        timeout=15000)


SNAP = """(() => {
  const R=s=>{const e=document.querySelector(s);if(!e)return null;
    const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
  const rows=[...document.querySelectorAll('#hbody .hrow')];
  const chain=[...document.querySelectorAll('#srccap .scnode')];
  return {
    diag:R('#healthDiag'), health:R('#healthcard'), hbody:R('#hbody'),
    rows:rows.length,
    acts:document.querySelectorAll('#hbody .hrowbtn').length,
    rowH:rows[0]?+rows[0].getBoundingClientRect().height.toFixed(1):null,
    chainN:chain.length,
    chainTxt:chain.map(n=>n.textContent.replace(/\\s+/g,' ').trim()),
    chainCls:chain.map(n=>n.className),
    dead:chain.filter(n=>n.classList.contains('dead')).length,
    bodyDisplay:getComputedStyle(document.getElementById('healthDiagBody')).display,
    more:R('#healthDiagMore2'),
    moreTxt:document.getElementById('healthDiagMore2').textContent.trim(),
    paceRows:document.querySelectorAll('#paceBox .pace-row').length,
    traceBtns:[...document.querySelectorAll('#paceBox .pace-row button')]
      .filter(b=>/展开溯源|收起溯源/.test(b.textContent)).length,
    details:document.querySelectorAll('#paceBox .pace-detail').length,
    docOver:document.documentElement.scrollWidth-document.documentElement.clientWidth,
  };
})()"""


def test_health_strip_matrix_and_trace(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for w in WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 900 if w > 500 else 844},
                            is_mobile=(w <= 600), has_touch=(w <= 600))
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
            pg.wait_for_timeout(800)
            _open_health(pg)
            d = pg.evaluate(SNAP)
            if d["rows"] != 10 or d["acts"] != 10:
                bad.append("%d 健康行/自检动作 %d/%d" % (w, d["rows"], d["acts"]))
            if d["diag"]["h"] > (180 if w <= 600 else 130):
                bad.append("%d 诊断条高 %s（应 ≤%d）"
                           % (w, d["diag"]["h"], 180 if w <= 600 else 130))
            if d["hbody"]["y"] > (760 if w <= 600 else 660):
                bad.append("%d 健康矩阵未进首屏 y=%s" % (w, d["hbody"]["y"]))
            if d["chainN"] != 3:
                bad.append("%d 状态链胶囊 %d" % (w, d["chainN"]))
            if "已停服" not in d["chainTxt"][0]:
                bad.append("%d PC 状态未反映去哪儿停服: %s" % (w, d["chainTxt"]))
            if d["dead"] != 2:
                bad.append("%d 去哪儿 PC/H5 停服节点 %d（应 2）" % (w, d["dead"]))
            if d["bodyDisplay"] != "none":
                bad.append("%d 逐渠道说明默认未折叠" % w)
            if d["moreTxt"] != "展开说明":
                bad.append("%d 展开说明文案 %r" % (w, d["moreTxt"]))
            if d["paceRows"] != 10 or d["traceBtns"] != 10:
                bad.append("%d 节流行/溯源入口 %d/%d"
                           % (w, d["paceRows"], d["traceBtns"]))
            if d["details"] != 0:
                bad.append("%d 溯源默认未折叠" % w)
            if d["docOver"] > 1:
                bad.append("%d 横向溢出 %s" % (w, d["docOver"]))
            # 展开说明：触发器同坐标、矩阵不位移、10 张说明卡、浮层
            # 390 档点击会让页面滚动，视口坐标会整体上移；位置契约用
            # 页面绝对坐标（+scrollY），否则滚动被误读成「按钮位移」。
            m0 = pg.evaluate("()=>{const e=document.getElementById('healthDiagMore2');"
                             "const r=e.getBoundingClientRect();"
                             "return {x:r.x,y:r.y+scrollY}}")
            hy0 = pg.evaluate("()=>document.getElementById('healthcard')"
                              ".getBoundingClientRect().y+scrollY")
            pg.click("#healthDiagMore2")
            pg.wait_for_timeout(500)
            ex = pg.evaluate("""()=>{const b=document.getElementById('healthDiagBody');
              const m=document.getElementById('healthDiagMore2');const r=m.getBoundingClientRect();
              const br=b.getBoundingClientRect();const c=getComputedStyle(b);
              return {x:r.x,y:r.y+scrollY,cards:b.querySelectorAll('.hdiag-card').length,
                pos:c.position,disp:c.display,bTop:br.top,
                hy:document.getElementById('healthcard').getBoundingClientRect().y+scrollY,
                more:document.getElementById('healthDiagMore2').textContent.trim()}}""")
            if abs(ex["x"] - m0["x"]) > 1 or abs(ex["y"] - m0["y"]) > 1:
                bad.append("%d 说明触发器位移" % w)
            if abs(ex["hy"] - hy0) > 1:
                bad.append("%d 展开说明推走矩阵 %spx" % (w, ex["hy"] - hy0))
            if ex["disp"] == "none" or ex["pos"] != "absolute" or ex["cards"] != 10:
                bad.append("%d 说明浮层异常 %s cards=%s pos=%s"
                           % (w, ex["disp"], ex["cards"], ex["pos"]))
            if ex["more"] != "收起说明":
                bad.append("%d 展开后按钮文案 %r" % (w, ex["more"]))
            pg.click("#healthDiagMore2")
            pg.wait_for_timeout(350)
            # 溯源：展开一行，块为轻表格且首行 y 不变
            r0 = pg.evaluate("()=>document.querySelector('#paceBox .pace-row').getBoundingClientRect().y")
            pg.evaluate("""()=>{const b=[...document.querySelectorAll('#paceBox .pace-row button')]
              .find(x=>x.textContent.trim()==='展开溯源');if(b)b.click()}""")
            # r1451：溯源详情是**异步**取数据后建的（点开才请求 trace）。
            # 原来固定等 450ms，慢机上 `.pace-detail` 还没建出来 →
            # 量到 h=0/bg=null，报「溯源展开无内容；溯源详情出现卡片底」两条假红。
            try:
                pg.wait_for_function(
                    "()=>{const d=document.querySelector('#paceBox .pace-detail');"
                    "return d&&d.getBoundingClientRect().height>1}", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(250)
            tr = pg.evaluate("""()=>{const d=document.querySelector('#paceBox .pace-detail');
              const r0=document.querySelector('#paceBox .pace-row').getBoundingClientRect().y;
              return {ok:!!d,h:d?+d.getBoundingClientRect().height.toFixed(1):0,
                bg:d?getComputedStyle(d).backgroundColor:null,r0,detailCount:document.querySelectorAll('#paceBox .pace-detail').length}}""")
            if not tr["ok"] or tr["h"] < 40:
                bad.append("%d 溯源展开无内容" % w)
            if tr["bg"] not in ("rgba(0, 0, 0, 0)", "transparent"):
                bad.append("%d 溯源详情出现卡片底 %s" % (w, tr["bg"]))
            if abs(tr["r0"] - r0) > 1:
                bad.append("%d 溯源展开推走首行" % w)
            pg.close()
        b.close()
    assert not bad, "渠道健康: " + "；".join(bad)
