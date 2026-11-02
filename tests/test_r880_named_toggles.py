# -*- coding: utf-8 -*-
"""r880：用户点名的三个「展开/收起」必须真·多态且可逆（实测固化）。

覆盖三条用户原话：
  ① 「展开探针…现在展开和收起都不在同一个位置，明显不是一个按钮多态的设计，
     并且展开的时候，demo 合成的位置抖动偏移了」
  ② 「展开概览下面是可以再点击选择出发日，然后再点击收起概览就整体收不回去了」
  ③ 「对比列表收起镜像按钮这种折叠按钮怎么能居中设计呢，并且能收起来，
     但是也给不了右边用啊，为什么不是左右按钮互相展开收起？」

实测结论（修后基线，1512/900 两档）：
  ① 探针触发器两态 (1329.5, 208.9) 与 (797, 254.9) 完全相同，收起态回位；
  ② 概览「展开→(选日/ctx=true)→收起」后 bodyH 46、bandH 40、hero t 不变、
     `ctx-collapsed` 仍为 true（r433 起不再连带重算筛选区）；
  ③ 镜像折叠钮在展开态与收起态距右缘恒为 10px（轨道右内衬），三档一致，
     既不居中、也不移动。
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

PROBE = r"""() => {
  const R = e => { if(!e) return null; const b=e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), t:+b.top.toFixed(1), w:+b.width.toFixed(1), h:+b.height.toFixed(1)}; };
  /* 2026-11-01：探针卡收成「默认不占位 + 展开一行」后，卡内的「收起探针」
     只在展开态存在（收起态整块 display:none）。两态同坐标的契约落在**外部
     入口** #srxProbeTool（工具行里那颗「主动探针」）上——它才是用户两态都能
     点到的同一颗按钮。卡内的收起钮是展开态的第二出口，不参与两态位移判据。 */
  const btn = document.getElementById('srxProbeTool') ||
              document.querySelector('#searchview .srx-probe-toggle');
  if (!btn) return {err:'no probe toggle'};
  const a = {btn:R(btn), aria:btn.getAttribute('aria-expanded')};
  btn.click();
  return new Promise(res => setTimeout(() => {
    const b = {btn:R(btn), aria:btn.getAttribute('aria-expanded'),
               probeH:+document.querySelector('#searchview .srx-probe').getBoundingClientRect().height.toFixed(1)};
    btn.click();
    setTimeout(() => res({closed:a, open:b,
      reclosed:{btn:R(btn), aria:btn.getAttribute('aria-expanded')}}), 480);
  }, 680));
}"""

OV = r"""() => {
  const R = e => { const b=e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), t:+b.top.toFixed(1)}; };
  const v=document.getElementById('searchview'), hero=document.getElementById('srxOvHero');
  const body=document.getElementById('srxOvBody'), band=document.getElementById('srxBand');
  const out={base:{bodyH:+body.getBoundingClientRect().height.toFixed(1),
                   bandH:+band.getBoundingClientRect().height.toFixed(1), hero:R(hero)}};
  hero.click();
  return new Promise(res=>setTimeout(()=>{
    out.open={bodyH:+body.getBoundingClientRect().height.toFixed(1),
              heroTxt:hero.textContent.trim(), aria:hero.getAttribute('aria-expanded')};
    // 模拟「在概览里选择出发日」：置 ctx，再收起
    try { if (typeof SRX !== 'undefined') SRX.ctx = true; } catch (e) {}
    hero.click();
    setTimeout(()=>{
      out.reclose={bodyH:+body.getBoundingClientRect().height.toFixed(1),
                   bandH:+band.getBoundingClientRect().height.toFixed(1),
                   hero:R(hero), heroTxt:hero.textContent.trim(), aria:hero.getAttribute('aria-expanded'),
                   collapsed:v.classList.contains('srx-ov-collapsed'),
                   ctxCollapsed:document.getElementById('srxContext').classList.contains('ctx-collapsed')};
      res(out);
    }, 700);
  }, 700));
}"""

MIR = r"""() => {
  const R = e => { const b=e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), w:+b.width.toFixed(1)}; };
  const mir=document.getElementById('srxMirror'), btn=mir.querySelector('.srx-foldbtn'),
        grid=document.getElementById('srxGrid');
  const o={mir:R(mir), btn:R(btn), grid:R(grid)};
  btn.click();
  return new Promise(res=>setTimeout(()=>{
    res({open:o, folded:{mir:R(mir), btn:R(btn), grid:R(grid)}});
  }, 700));
}"""


@pytest.fixture(scope="module")
def ui():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 900):
                pg = br.new_page(viewport={"width": w, "height": 950})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2800)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1800)
                out[w] = {"probe": pg.evaluate(PROBE)}
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(800)
                out[w]["ov"] = pg.evaluate(OV)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(800)
                out[w]["mir"] = pg.evaluate(MIR)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 900])
def test_probe_toggle_is_one_button_two_states(ui, w):
    d = ui[w]["probe"]
    assert not d.get("err"), d
    a, b, c = d["closed"], d["open"], d["reclosed"]
    assert b["aria"] == "true" and c["aria"] == "false", d
    assert b["probeH"] > a["btn"]["h"], "探针没有真正展开：%s" % b
    for k in ("l", "t"):
        assert abs(b["btn"][k] - a["btn"][k]) <= 1.0, (
            "%d 档探针展开时按钮%s移动了（%s → %s）" % (w, k, a["btn"][k], b["btn"][k]))
        assert abs(c["btn"][k] - a["btn"][k]) <= 1.0, (
            "%d 档探针收起后按钮%s没回原位（%s → %s）" % (w, k, a["btn"][k], c["btn"][k]))


@pytest.mark.parametrize("w", [1512, 900])
def test_overview_collapses_after_picking_a_day(ui, w):
    d = ui[w]["ov"]
    base, re_ = d["base"], d["reclose"]
    assert d["open"]["bodyH"] > base["bodyH"] + 40, "概览没有真正展开：%s" % d["open"]
    assert re_["collapsed"] is True, "点过出发日后，概览收不回去：%s" % re_
    assert abs(re_["bodyH"] - base["bodyH"]) <= 1.0, (
        "%d 档收起后折叠体高度没复原（%s vs %s）" % (w, re_["bodyH"], base["bodyH"]))
    assert abs(re_["hero"]["t"] - base["hero"]["t"]) <= 1.5, (
        "%d 档收起后触发器纵向没回原位（%s vs %s）"
        % (w, re_["hero"]["t"], base["hero"]["t"]))
    assert re_["aria"] == "false" and re_["heroTxt"] == "展开概览", re_


# 镜像只在「本来就是两列」的宽度上成立：≤1100 网格主动收单列，
# 镜像卡本身不挂载（宽 0），不构成「贴右缘」的前提。
@pytest.mark.parametrize("w", [1512])
def test_mirror_fold_button_sits_at_the_right_edge(ui, w):
    d = ui[w]["mir"]
    o, f = d["open"], d["folded"]
    assert o["mir"]["w"] > 100, "%d 档镜像未挂载：%s" % (w, o["mir"])
    # 展开态：距轨道右缘 = 轨道右内衬（10px），不是居中
    gap_open = o["mir"]["r"] - o["btn"]["r"]
    assert gap_open <= 12, "%d 档展开态折叠钮离右缘 %s（居中=被塞进带子中间）" % (w, gap_open)
    # 收起态：列表拿回整行后，折叠钮仍贴同一右缘（两态差 ≤2px）
    gap_folded = f["grid"]["r"] - f["btn"]["r"]
    assert abs(gap_folded - gap_open) <= 2.0, (
        "%d 档两态贴右不一致（展开 %s / 收起 %s）" % (w, gap_open, gap_folded))
    assert abs(f["btn"]["r"] - f["grid"]["r"]) <= 12, (
        "%d 档收起后折叠钮没贴网格右缘（差 %s）" % (w, f["grid"]["r"] - f["btn"]["r"]))
