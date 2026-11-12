# -*- coding: utf-8 -*-
"""r870 门禁：配置页「全部收齐」后，每个分区都必须留着能点回去的卡头。

实测缺陷（修前，「用户与航线」1512）：外层卡 `.ucard>.uhead` 的收纳体是一个
装着用户卡的匿名 DIV；`_uheadBodies` 把这块整只 `display:none`，于是用户卡的
`.uhead2` 卡头也一起消失——收齐后可见卡头 7→1，面板高 13188→63，只剩一行
面板标题。用户既看不到有哪些用户，也没有任何就地展开的入口，读作
「整页收空了」，与项目自己的「标题是回到内容唯一的入口」相违。

判据（按分区逐个量）：
  · 收齐后分区高度必须真的下降（不能是「按钮说收了、页面没动」）；
  · 收齐后必须仍有可见的卡头/分组标题（回到内容的入口）；
  · 再点一次必须完全复原（高度回到原值的 90% 以上）。
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


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

JS = r"""() => {
  const main = document.getElementById('cfgmain');
  const vis = e => e.offsetParent !== null && e.getBoundingClientRect().height > 1;
  const heads = [...main.querySelectorAll('.uhead,.uhead2,.grouplab,.rhead,.chhead')].filter(vis);
  /* r1464：CI 上 `login 分区「全部展开」没有复原：1850 → 1049`，本机却稳定
     1813→205→1813。光看总高判不出"少的是哪张卡"，这里把分区内每张 .ucard
     的高度一并带出来——失败信息里直接能看出是渠道入口板没回来，还是别的卡。 */
  const cards = [...main.querySelectorAll('.ucard')].map(c => ({
    id: (c.id || (c.className || '').toString().slice(0, 16)),
    h: Math.round(c.getBoundingClientRect().height)}));
  return {h: Math.round(main.getBoundingClientRect().height),
          heads: heads.length,
          cards,
          headTexts: heads.slice(0, 6).map(e => (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 18))};
}"""


def _wait_links(pg, lenient=False):
    """等「渠道入口」板真的渲染出来（login 分区的卡是异步拉的）。

    lenient=True 用于展开之后：这里**不主动重拉**——若"全部展开"本该把板子
    复原却没复原，就该让断言红出来，而不是由测试替产品补一次。
    """
    cond = "()=>document.querySelectorAll('#cfgChannelLinks .chband').length>=5"
    try:
        pg.wait_for_function(cond, timeout=8000)
        return
    except Exception:
        if lenient:
            return
    pg.evaluate("()=>{try{if(typeof srxChLinksLoad==='function')"
                "srxChLinksLoad('cfg')}catch(e){}}")
    pg.wait_for_function(cond, timeout=20000)


@pytest.fixture(scope="module")
def panes():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ok = False
        for _ in range(90):
            try:
                op.open(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1512, "height": 1000})
            pg.goto(BASE + "/", wait_until="domcontentloaded")
            pg.wait_for_timeout(2600)
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(1200)
            for p in ("login", "users", "pacing", "globals"):
                pg.evaluate("""(p)=>{const b=document.querySelector('#cfgview .cfgnav .cnav[data-p="'+p+'"]');
                    if(b)b.click();}""", p)
                pg.wait_for_timeout(800)
                # r1466：login 分区里「渠道入口」板是异步拉的。若在它到位前测
                # before、之后再测 restored，就变成"拿加载完的比没加载完的"，
                # CI 实测 1850 → 1049 正是这个形态（本机因为快，两侧都小 → 假绿）。
                # 这里先等板子就绪再测 before；展开后再等一次，确保比的是同一状态。
                if p == "login":
                    _wait_links(pg)
                before = pg.evaluate(JS)
                pg.evaluate("document.getElementById('cfgFoldAll').click()")
                pg.wait_for_timeout(900)
                folded = pg.evaluate(JS)
                pg.evaluate("""()=>{const b=document.getElementById('cfgFoldAll');
                    if(b && /全部展开/.test(b.textContent||'')) b.click();}""")
                pg.wait_for_timeout(900)
                if p == "login":
                    _wait_links(pg, lenient=True)
                restored = pg.evaluate(JS)
                # 再验一次重建后的回放：切走再切回（applyFolds 会按存档重放），
                # 收起态必须仍留着入口、展开态必须仍复原——否则「收起存档」只在
                # 当前 DOM 上成立，刷新就丢。
                pg.evaluate("document.getElementById('cfgFoldAll').click()")
                pg.wait_for_timeout(700)
                pg.evaluate("""(p)=>{const b=document.querySelector('#cfgview .cfgnav .cnav[data-p="'+p+'"]');
                    if(b)b.click();}""", "login" if p != "login" else "users")
                pg.wait_for_timeout(600)
                pg.evaluate("""(p)=>{const b=document.querySelector('#cfgview .cfgnav .cnav[data-p="'+p+'"]');
                    if(b)b.click();}""", p)
                pg.wait_for_timeout(700)
                refolded = pg.evaluate(JS)
                pg.evaluate("""()=>{const b=document.getElementById('cfgFoldAll');
                    if(b && /全部展开/.test(b.textContent||'')) b.click();}""")
                pg.wait_for_timeout(700)
                out[p] = {"before": before, "folded": folded, "restored": restored, "refolded": refolded}
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("pane", ["login", "users", "pacing", "globals"])
def test_fold_all_really_collapses(panes, pane):
    d = panes[pane]
    # 用户与航线收齐后仍有用户卡头 + 分组标题（回入口），实测 13188→300，
    # 所以这里守「至少减半」而不是某个固定比例。
    assert d["folded"]["h"] <= d["before"]["h"] * 0.5, (
        "%s 分区收齐后高度没明显下降：%s → %s"
        % (pane, d["before"]["h"], d["folded"]["h"]))


@pytest.mark.parametrize("pane", ["login", "users", "pacing", "globals"])
def test_fold_all_keeps_an_entry_back(panes, pane):
    d = panes[pane]
    assert d["folded"]["heads"] >= 1, (
        "%s 分区收齐后一个卡头/分组标题都不剩，用户没有回到内容的入口：%s"
        % (pane, d["folded"]))
    assert d["folded"]["heads"] >= min(2, d["before"]["heads"]), (
        "%s 分区收齐后卡头从 %d 掉到 %d（整块被藏了）：%s"
        % (pane, d["before"]["heads"], d["folded"]["heads"], d["folded"]["headTexts"]))


@pytest.mark.parametrize("pane", ["login", "users", "pacing", "globals"])
def test_expand_all_restores(panes, pane):
    d = panes[pane]
    assert d["restored"]["h"] >= d["before"]["h"] * 0.9, (
        "%s 分区「全部展开」没有复原：%s → %s（各卡：before=%s restored=%s）"
        % (pane, d["before"]["h"], d["restored"]["h"],
           d["before"].get("cards"), d["restored"].get("cards")))


@pytest.mark.parametrize("pane", ["login", "users", "pacing", "globals"])
def test_fold_state_survives_rebuild(panes, pane):
    """收起存档要在分区重建（切走再切回）后仍成立：既不能整页收空，
    也不能自己弹回来。"""
    d = panes[pane]
    r = d["refolded"]
    assert r["h"] <= d["before"]["h"] * 0.5, (
        "%s 切走再切回后收起态丢失（%s → %s）" % (pane, d["folded"]["h"], r["h"]))
    assert r["heads"] >= min(2, d["before"]["heads"]), (
        "%s 重建后入口也没了：%s" % (pane, r))
