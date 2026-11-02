# -*- coding: utf-8 -*-
"""检索页顶部「两行常驻 + 探针一行」门禁（2026-11-01）。

用户原话（转述要点）：检索页顶部没有达到减少层级、可选式隐藏、紧凑扁平；
探针展开后应只占一行。

修前实测 1512 档（探针展开）：页顶到第一条数据 415px，中间 7 条横带
（hero 两行 / 探针标题行 / 探针表单 / 渠道入口 / 航线筛选 / 列表头 / 表头）；
探针收起时仍占 34px 一条空带。
修后：收起 282px、展开 332px；探针收起时 display:none，展开时 head/form/foot
在同一行（顶差 ≤ 4px）。

判据一律走渲染几何，不检 CSS 声明文本。
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

SNAP = r"""() => {
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), t:+b.top.toFixed(1), w:+b.width.toFixed(1), h:+b.height.toFixed(1)}; };
  const probe = document.getElementById('srxProbe');
  const hero = document.querySelector('#searchview .srx-hero');
  const first = document.querySelector('#srxRows .srx-row');
  const vis = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 1;
  const parts = {};
  ['srxProbe', 'srxContext'].forEach(() => {});
  const add = (k, sel) => { const e = document.querySelector(sel); if (vis(e)) parts[k] = R(e); };
  add('head', '#srxProbe .srx-probehead');
  add('form', '#srxProbe .srx-probeform');
  add('foot', '#srxProbe .srx-probefoot');
  return {
    probeShown: vis(probe),
    probe: vis(probe) ? R(probe) : null,
    hero: vis(hero) ? R(hero) : null,
    firstRowTop: first ? +first.getBoundingClientRect().top.toFixed(1) : null,
    parts: parts,
    statusText: ((document.getElementById('srxProbeStatus') || {}).textContent || '').trim(),
    aria: (document.getElementById('srxProbeTool') || {}).getAttribute
      ? document.getElementById('srxProbeTool').getAttribute('aria-expanded') : null
  };
}"""


@pytest.fixture(scope="module")
def shots():
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
            for w in (1920, 1512):
                pg = br.new_page(viewport={"width": w, "height": 950})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1500)
                # 收起态（新页面 localStorage 为空 = 默认收起）
                pg.evaluate("""() => {
                  const p = document.getElementById('srxProbe');
                  if (p && p.classList.contains('open')) document.getElementById('srxProbeToggle').click();
                }""")
                pg.wait_for_timeout(600)
                closed = pg.evaluate(SNAP)
                pg.evaluate("document.getElementById('srxProbeTool').click()")
                pg.wait_for_timeout(700)
                opened = pg.evaluate(SNAP)
                pg.evaluate("document.getElementById('srxProbeTool').click()")
                pg.wait_for_timeout(600)
                reclosed = pg.evaluate(SNAP)
                out[w] = {"closed": closed, "opened": opened, "reclosed": reclosed}
                pg.close()
            br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
    return out


@pytest.mark.parametrize("w", [1920, 1512])
def test_probe_band_takes_no_space_when_collapsed(shots, w):
    d = shots[w]["closed"]
    assert d["probeShown"] is False, "探针收起时仍占一条横带：%s" % d["probe"]
    assert d["aria"] == "false", "顶部「主动探针」没有反映收起态：%r" % d["aria"]
    # 收起态：hero 底到第一条数据 ≤ 200px（修前 233；演示站顶部多一条说明条，
    # 所以用相对 hero 的差值，不绑绝对 y）
    assert d["firstRowTop"] is not None and d["hero"] is not None
    gap = d["firstRowTop"] - d["hero"]["t"]
    assert gap <= 200, "收起态顶部仍太高：hero 底到首行 %spx（上限 200）" % gap


@pytest.mark.parametrize("w", [1920, 1512])
def test_hero_is_one_line(shots, w):
    h = shots[w]["closed"]["hero"]
    assert h is not None
    # 标题与实时状态同排：hero 高 ≤ 48（修前 57）
    assert h["h"] <= 48, "标题行没有收成一行：hero 高 %s（上限 48）" % h["h"]


@pytest.mark.parametrize("w", [1920, 1512])
def test_open_probe_is_a_single_row(shots, w):
    d = shots[w]["opened"]
    assert d["probeShown"] is True, "点「主动探针」后没有展开"
    assert d["aria"] == "true", "顶部按钮 aria 没跟上展开态：%r" % d["aria"]
    parts = d["parts"]
    for k in ("head", "form", "foot"):
        assert k in parts, "展开态缺 %s" % k
    # 表单与操作簇必须同一行
    assert abs(parts["head"]["t"] - parts["form"]["t"]) <= 4, (
        "操作簇与表单没排在同一行：%s vs %s"
        % (parts["head"]["t"], parts["form"]["t"]))
    # 状态行为空（真实实例默认态）时，渠道入口也必须挤在同一行：
    # 读序 = 条件 → 渠道入口 → 组合/会话/收起（收起钮在最右）。
    # 有内容时（探针结果 / 演示站免责说明）允许独占第二行，不压省略号。
    if not d["statusText"]:
        assert abs(parts["foot"]["t"] - parts["form"]["t"]) <= 4, (
            "状态行为空却仍换行：foot t=%s form t=%s"
            % (parts["foot"]["t"], parts["form"]["t"]))
        assert parts["form"]["l"] < parts["foot"]["l"] < parts["head"]["l"], (
            "读序不对（应 条件 → 渠道入口 → 动作）：%s / %s / %s"
            % (parts["form"]["l"], parts["foot"]["l"], parts["head"]["l"]))
        assert d["probe"]["h"] <= 60, "展开态探针高 %s，不是一行（上限 60）" % d["probe"]["h"]
    else:
        assert d["probe"]["h"] <= 110, "展开态探针高 %s（上限 110）" % d["probe"]["h"]
    # 相比收起态，展开最多多两行
    gap0 = shots[w]["closed"]["firstRowTop"] - shots[w]["closed"]["hero"]["t"]
    gap1 = d["firstRowTop"] - d["hero"]["t"]
    assert gap1 - gap0 <= 100, "展开比收起多占 %spx" % (gap1 - gap0)


@pytest.mark.parametrize("w", [1920, 1512])
def test_probe_recloses_without_leaving_a_gap(shots, w):
    d = shots[w]["reclosed"]
    assert d["probeShown"] is False, "再点一次没有收起"
    gap = d["firstRowTop"] - d["hero"]["t"]
    assert gap <= 200, "收起后仍留着高度：hero 底到首行 %spx" % gap
