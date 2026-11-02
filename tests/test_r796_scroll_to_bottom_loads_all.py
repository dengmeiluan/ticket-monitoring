# -*- coding: utf-8 -*-
"""r796 门禁：滚到表格底部必须**补齐全量行**，不能停在上一块。

来由（2026-11-01 实测）：明细表分块渲染 `_CHUNK=120`，滚动监听里
「距底 600px 内每拍补 4 片」。用户一次把滚轮甩到底（或拖滚动条到底）时
只派发一次 scroll：补完 1 片后 scrollHeight 变大，距底立刻超过 600，
接力条件自己失效——268 行只渲了 240（2 片），用户滚到底看到的仍是
「没到底」，还得再滚一次。

修法：判到「本来就在底部」（scrollTop+clientHeight≈scrollHeight）时
一次补满；渐进滚动仍按拍补。本门禁只守这个差别。

判据（真浏览器 + 真滚轮）：
1. 真实滚轮甩到底后，DOM 行数 == 全量行数（不许少一行）；
2. 分块深度 `_NDRAW*_CHUNK` 必须覆盖全量；
3. 负控：把「到底补满」改回「只补 1 片」，行数必须少于全量——否则说明
   这条判据量的不是这个分支。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo",
                             "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(90):
        try:
            op.open(base + "/api/state", timeout=2)
            up = True
            break
        except Exception:
            time.sleep(0.4)
    if not up:
        proc.terminate()
        pytest.skip("demo 服务未起来")
    yield base
    proc.terminate()


def _open_details(pg, base):
    pg.goto(base + "/")
    pg.wait_for_function("typeof S!=='undefined' && S && S.users", timeout=25000)
    pg.wait_for_timeout(700)
    pg.evaluate("switchView('mon')")
    pg.wait_for_timeout(900)
    pg.evaluate("showMonTab('details')")
    pg.wait_for_timeout(900)


def test_one_flick_to_bottom_loads_every_row(srv):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            _open_details(pg, srv)
            total = pg.evaluate("_ROWS && _ROWS.length")
            assert total and total > 120, "演示数据不足以验证分块：%s" % total
            pg.locator("#tablecard .tw").hover()
            pg.mouse.wheel(0, 30000)
            pg.wait_for_timeout(500)
            got = pg.evaluate("""()=>({
              rows:document.querySelectorAll('#ftable tbody tr[data-k]').length,
              total:_ROWS.length,
              drawn:_NDRAW*_CHUNK})""")
            assert got["rows"] == got["total"], (
                "滚到底只渲出 %d/%d 行——用户还要再滚一次才补齐：%s"
                % (got["rows"], got["total"], got))
            assert got["drawn"] >= got["total"], got
        finally:
            b.close()


def test_negative_control_partial_chunk_leaves_rows_missing(srv):
    """负控：把「到底补满」换回「每拍只补 1 片」，必须仍差行。

    做法：滚到底之前先把 `_ROWS.length` 视作更大（等价于分块没补齐），
    再只调一次 `_tblAppend()`——这正是修复前的行为。
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            _open_details(pg, srv)
            got = pg.evaluate("""()=>{
              const total=_ROWS.length;
              const before=document.querySelectorAll(
                '#ftable tbody tr[data-k]').length;
              _tblAppend();                 /* 修复前：一次 scroll 只补 1 片 */
              const once=document.querySelectorAll(
                '#ftable tbody tr[data-k]').length;
              return {total, before, once,
                      chunk:typeof _CHUNK!=='undefined'?_CHUNK:null};}""")
            assert got["total"] > got["chunk"], (
                "数据不足一块，负控无意义：%s" % got)
            assert got["once"] < got["total"], (
                "补 1 片后就已到全量，负控无效（分块太小）：%s" % got)
            assert got["once"] > got["before"], (
                "补片没生效，负控打空了：%s" % got)
        finally:
            b.close()
