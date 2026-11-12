# -*- coding: utf-8 -*-
"""r1071：配置分区折叠在「全部收齐/全部展开/搜索/清空/重建」五路下同源。"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="配置折叠路径依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


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
    priv = tempfile.mkdtemp(prefix="r1071_")
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


SNAP = """(() => {
  const root = document.getElementById('cfgglobals');
  const secs = [...root.querySelectorAll('.subsec[data-cfgsec]')];
  return {
    folded: secs.filter(s => s.classList.contains('folded')).length,
    total: secs.length,
    firstOpen: secs[0] && !secs[0].classList.contains('folded'),
    btnTexts: secs.map(s => {
      const b = s.querySelector('.secfold'); return b ? b.textContent.trim() : null;
    }),
    foldAllText: (document.getElementById('cfgFoldAllTxt') || {}).textContent || '',
    qsearch: document.getElementById('cfgview').classList.contains('qsearch'),
    hitVisible: [...root.querySelectorAll('.glcell')].some(c =>
      (c.textContent || '').includes('指纹一致性') && c.getBoundingClientRect().height > 1),
    pageOver: document.documentElement.scrollWidth - innerWidth,
  };
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1400)
    pg.evaluate("()=>{switchView('cfg');showCfgPanel('globals')}")
    pg.wait_for_timeout(1800)


def test_five_fold_paths_stay_consistent(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 900},
                        is_mobile=True, has_touch=True)
        _open(pg)
        a = pg.evaluate(SNAP)
        assert a["folded"] == a["total"] - 1 and a["firstOpen"], a

        # 全部收齐：首组也收起，词面转「全部展开」
        pg.evaluate("()=>cfgFoldAll()")
        pg.wait_for_timeout(500)
        b1 = pg.evaluate(SNAP)
        assert b1["folded"] == b1["total"], b1
        assert b1["foldAllText"] == "全部展开", b1
        assert all(t == "展开" for t in b1["btnTexts"]), b1

        # 全部展开：全开，词面回「全部收齐」，搜索不再需要临时展开
        pg.evaluate("()=>cfgFoldAll()")
        pg.wait_for_timeout(500)
        c = pg.evaluate(SNAP)
        assert c["folded"] == 0, c
        assert c["foldAllText"] == "全部收齐", c
        assert all(t == "收起" for t in c["btnTexts"]), c

        # 搜索命中折叠组：qsearch 生效且目标字段可见
        pg.evaluate("()=>{document.getElementById('cfgSearch').value='指纹一致性';cfgFilter('指纹一致性')}")
        pg.wait_for_timeout(600)
        d = pg.evaluate(SNAP)
        assert d["qsearch"] is True and d["hitVisible"] is True, d

        # 清空搜索：回到搜索前的「全开」态，而不是默认首组
        pg.evaluate("()=>cfgSearchClear()")
        pg.wait_for_timeout(600)
        e = pg.evaluate(SNAP)
        assert e["qsearch"] is False and e["folded"] == 0, e

        # 重建（保存后的同一路径）：全开态保持
        pg.evaluate("()=>{try{buildForm()}catch(err){}}")
        pg.wait_for_timeout(900)
        f = pg.evaluate(SNAP)
        assert f["folded"] == 0, f
        assert f["pageOver"] <= 1, f

        # 刷新页面：localStorage 里的折叠态仍然有效
        _open(pg)
        g = pg.evaluate(SNAP)
        assert g["folded"] == 0, g
        b.close()
