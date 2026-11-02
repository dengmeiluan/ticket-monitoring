# -*- coding: utf-8 -*-
"""r599：悬浮窗宽度必须与落位解耦，否则钳位会把自己锁在折叠态。

用户可见症状（uitest `v297 图表点按显示明细` 389 档红）：
    {'left': 348, 'top': 364, 'right': 401, 'bottom': 522, 'vw': 390}
浮窗右沿越过视口 11px，且体形变成 53×158 的竖条。

机理不是「钳位算错」，而是 absolute 盒子默认 shrink-to-fit：可用宽度
等于**包含块右缘剩余空间**。一旦上一帧把 left 放到接近右缘，下一帧
innerHTML 一换，盒子只能按 min-content 折行（实测 141×49 → 53×158）。
落位函数随后读到这个假宽度去算钳位，把 left 又固定回同一处——自我维持，
永远回不到正常体形。

所以契约钉在 CSS 上：两个浮窗都必须 width:max-content。只改钳位算术
是治不好的（负控实测：把 placeAxis 的右界强行改成 vw-8，浮窗仍然折叠）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def _rule(src, sel):
    i = src.index(sel + "{")
    return src[i:src.index("}", i)]


def test_spmon_tip_declares_content_width():
    r = _rule(_w(), ".spmon-tip")
    assert "position:absolute" in r
    assert "width:max-content" in r, (
        "特价监控浮窗没有 width:max-content：左值贴右缘后会被压成 "
        "min-content，落位读到的宽度是假的")


def test_ws_tip_declares_content_width():
    r = _rule(_w(), ".ws-tip")
    assert "position:absolute" in r
    assert "width:max-content" in r, "关注走势浮窗同样会被压窄"


def test_content_width_does_not_remove_the_cap():
    """max-width 必须还在：去掉就变成一条横贯全屏的长条（r374 已修过）。"""
    w = _w()
    assert "max-width:270px" in _rule(w, ".ws-tip")
    assert "max-width:min(270px,calc(100vw - 16px))" in _rule(w, ".spmon-tip")


def test_renders_wide_tip_even_when_left_pins_to_the_right_edge():
    """真渲染：把浮窗摆到紧贴包含块右缘，再换内容，宽度不得塌。

    这条不可省：上面三条只查 CSS 声明，声明在但有别的规则覆盖时照样绿。
    实测（负控）改成 `width:auto` 后静态断言全绿，只有这条会红。
    """
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    # 现取空闲端口：固定端口在并发全量下会被别模块的 legacy 清理误杀，
    # 实测门禁里这条因此超时（其余 4553 条同批通过）。
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    port = _s.getsockname()[1]
    _s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = "http://127.0.0.1:%d/" % port
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                op.open(url, timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            import os as _os
            if not _os.path.exists(p.chromium.executable_path):
                import pytest
                pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.goto(url)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=20000)
            pg.evaluate("()=>{switchView('mon');showMonTab('specials')}")
            pg.wait_for_timeout(1200)
            got = pg.evaluate("""()=>{
              const t=document.getElementById('spMonTip'),
                    w=document.getElementById('spMonChart').parentElement;
              const blk=w.clientWidth;
              t.hidden=false;t.style.top='10px';
              t.innerHTML='<b>2026-11-13</b> · ¥1800<br>10-29 19:08 · 携程 · 裸价';
              t.style.left='0px';
              const wide={w:t.offsetWidth,h:t.offsetHeight};
              /* 贴右缘：只留 12px 可用宽——实测失败态就是 left 落在
                 318/320 这个位置，下一帧内容一换立刻折成 min-content。
                 用「贴到刚好不塌」的位置测不出问题（负控实测漏网）。 */
              t.style.left=(blk-12)+'px';
              const pinnedLeft=t.offsetLeft;
              t.innerHTML='<b>2026-11-26</b> · ¥1620<br>10-29 19:31 · 同程 · 含税';
              const pinned={w:t.offsetWidth,h:t.offsetHeight};
              /* 再走一次真实落位：手工 pin 是为了造出折叠条件，落位是
                 被测对象——两者分开量，否则测的只是我自己写的 left。 */
              PCHART.placeTipAxis(w,t,w.getBoundingClientRect().right-20,10);
              const r=t.getBoundingClientRect();
              const out={blk,wide,pinned,pinnedLeft,avail:blk-pinnedLeft,
                right:Math.round(r.right),vw:innerWidth,
                placedW:t.offsetWidth,
                maxW:getComputedStyle(t).maxWidth,
                cssW:getComputedStyle(t).width};
              t.style.left='0px';t.hidden=true;return out}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    # 贴右缘状态下换内容，宽度必须与宽松状态下同一量级（允许折行到
    # max-width 上限，但不能塌到 min-content 的 1/3）
    assert got["pinned"]["w"] >= got["wide"]["w"] - 2, (
        "贴右缘后浮窗被压窄：%s（宽松态 %s）" % (got["pinned"], got["wide"]))
    assert got["pinned"]["h"] < got["wide"]["h"] * 2, (
        "贴右缘后浮窗被折成竖条：%s（宽松态 %s）"
        % (got["pinned"], got["wide"]))
    assert got["right"] <= got["vw"] + 1, (
        "浮窗右沿越过视口：%s > %s" % (got["right"], got["vw"]))
