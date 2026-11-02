# -*- coding: utf-8 -*-
"""r849 门禁：用户卡头的两个动作链接，间隙点击不得落到父容器上。

实测缺陷（1512）：`.uact2 a::after{inset:-6px -4px}` 的横向 -4px 让两颗
链接的热区各向组内吃掉 4px，12px 的视觉间隙只剩 4px 真空白；在两颗的
正中间 elementFromPoint 得到的是**父容器** `.uact2`（既不是「查看明细」
也不是「走势」）——用户点缝隙等于点了个寂寞，正是「用户明细按钮排在那里
很别扭」的一类手感问题。

修法：纵向照旧外扩 6px（36px 触控地板不降），横向只在组的两端外扩 4px，
组内相邻边不越过自身盒子。修后实测：间隙中点归属 `span.uact2`（无链接），
两颗的左右边缘仍各自命中对应链接，高 36px 不变。
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
  const links=[...document.querySelectorAll('#monview .uact2 a')].slice(0,2);
  if(links.length<2) return {err:'need 2 links, got '+links.length};
  const R=e=>e.getBoundingClientRect();
  const a=R(links[0]), b=R(links[1]);
  const cy=(a.top+a.bottom)/2, gapMid=(a.right+b.left)/2;
  const at=x=>{const e=document.elementFromPoint(x,cy);
    return {tag:e?e.tagName:null, txt:(e&&(e.textContent||'')).trim().slice(0,10),
            owner:e&&e.closest('a')?(e.closest('a').textContent||'').trim().slice(0,10):null};};
  return {gap:+(b.left-a.right).toFixed(1),
          heights:[+a.height.toFixed(1), +b.height.toFixed(1)],
          mid:at(gapMid),
          leftEdge:at(a.left-3), rightEdge:at(b.right+3),
          sameRow: Math.abs(a.top-b.top) < 2};
}"""


@pytest.fixture(scope="module")
def probe():
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
            for w in (1512, 430):
                pg = br.new_page(viewport={"width": w, "height": 1400})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(1600)
                out[w] = pg.evaluate(JS)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 430])
def test_gap_between_actions_is_not_clickable(probe, w):
    """两颗链接的缝隙里不能有链接热区——点缝隙应是空操作，不是误触。"""
    d = probe[w]
    assert "err" not in d, d
    assert d["mid"]["owner"] is None, (
        "%d 档两颗动作链接的间隙中点命中了「%s」——热区吃掉了缝隙，"
        "点缝会误触" % (w, d["mid"]["owner"]))


@pytest.mark.parametrize("w", [1512, 430])
def test_each_action_is_still_reachable_at_its_edges(probe, w):
    d = probe[w]
    assert d["leftEdge"]["owner"], "%d 档「查看明细」左侧边缘点不到" % w
    assert d["rightEdge"]["owner"], "%d 档「走势」右侧边缘点不到" % w
    assert d["sameRow"], "%d 档两颗动作不在同一行" % w


@pytest.mark.parametrize("w", [1512, 430])
def test_actions_keep_the_touch_floor(probe, w):
    d = probe[w]
    assert min(d["heights"]) >= 36, (
        "%d 档动作链接可点高度 %s 低于 36px 触控地板" % (w, d["heights"]))
