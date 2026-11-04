# -*- coding: utf-8 -*-
"""r805ad：一列装不下的分域差异，必须在悬停里说清。

延续 r805z（三方对照）与 r805ac（detail 审计）。本轮把 `intl` 维度量到
底，发现同程与去哪儿 App 的国际端**只有日历价**：

    账本里「带起降时刻的真实航班元素」（全历史）
      ctrip 765/3829 · qunar 1569/1766 · fliggy 533/2674
      tongcheng **481/0** · tuniu 77/2956 · app_zhixing 80/100
      app_qunar 45/**0**

同程国际 34 行全是 `source=tc_window_calendar`、`name=日历最低价`、
`depTime=''` —— 「窗历」本身不含航班级信息。

`intl=y` **仍然成立**（确实有国际报价，不是没有这个能力），所以不降级。
但矩阵只有一格 `intl`，读者看到 ✓ 会以为「国际也有航班号/机型/时刻」。
按 `SURFACE_NOTES` 的先例，给这种差异加 `DIMENSION_NOTES` 悬停说明。

判据（三层）：
  1. 源层：`DIMENSION_NOTES` 里必须给同程/去哪儿 App 的 intl 写明
     「只有日历价」——空着等于没解释；
  2. 接口层：`/api/channel-dims` 必须把 `dim_notes` 下发（否则前端
     拿不到，加了等于没加）；
  3. 渲染层：真浏览器里那些格子的 title 必须含该说明。

**不**断言「intl 应为 n」：那是把「没有明细」错读成「没有国际报价」。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_dimension_notes_explain_calendar_only_intl():
    from core.channels import DIMENSION_NOTES
    for plat in ("tongcheng", "app_qunar"):
        note = DIMENSION_NOTES.get((plat, "intl")) or ""
        assert note.strip(), (
            "%s 的国际端只有日历价，intl 格上必须写明（否则读者把"
            "「有国际报价」读成「国际也有航班明细」）" % plat)
        assert "日历" in note, (
            "%s 的 intl 说明没点出「只有日历价」：%r" % (plat, note))


def test_tuniu_intl_note_names_the_h5_path_and_pc_block():
    """途牛国际 y 的实情是「H5/API 出数、PC 被滑块拦」——必须在悬停里说清。

    只写 y 会让读者以为 PC 也能查；写 n 又与事实不符（H5 真出过数）。
    """
    from core.channels import DIMENSION_NOTES
    note = DIMENSION_NOTES.get(("tuniu", "intl")) or ""
    assert "H5" in note and "PC" in note, (
        "tuniu.intl 说明没点出「H5/API 出数、PC 被拦」的分端事实：%r" % note)
    assert "滑块" in note, "没说明 PC 为什么测不出：%r" % note
    assert "n" in note, "没说明「测不出不记 n」的口径：%r" % note


def test_api_exposes_dim_notes():
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8").read()
    assert "DIMENSION_NOTES" in src, (
        "channel_dims_payload 没引用分域说明单一事实源")
    i = src.index('"channels": [')
    seg = src[i:i + 900]
    assert "dim_notes" in seg, (
        "载荷没下发 dim_notes：前端无从渲染，说明加了等于没加")
    webui = io.open(os.path.join(ROOT, "webui.py"),
                    encoding="utf-8").read()
    assert "channel_dims_payload()" in webui, "接口没走单一矩阵载荷"


def test_rendered_tooltip_carries_dim_note():
    """渲染层：真浏览器读 title（走 demo，不需要真实渠道）。"""
    import socket
    import subprocess
    import time
    import urllib.request

    import pytest

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1100})
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("""async()=>{
                  switchView('cfg');
                  await new Promise(r=>setTimeout(r,2500));
                }""")
                got = pg.evaluate(r"""()=>{
                  const box=document.getElementById('cfgDimMatrix');
                  const rows=[...box.querySelectorAll('tr')];
                  const head=[...rows[0].querySelectorAll('th')]
                    .map(x=>(x.innerText||'').replace(/\s+/g,' ').trim());
                  for(const tr of rows){
                    const th=(tr.querySelector('th')||{}).innerText||'';
                    if(!/国际/.test(th))continue;
                    const cells=[...tr.querySelectorAll('td .cell')];
                    for(let i=0;i<cells.length;i++){
                      if(/同程/.test(head[i+1]||''))
                        return cells[i].getAttribute('title')||'';
                    }
                  }
                  return null;
                }""")
            finally:
                b.close()
        assert got, "找不到「国际 × 同程」格子"
        assert "日历" in got, (
            "界面悬停里没有「只有日历价」的说明：%r" % got[:120])
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
