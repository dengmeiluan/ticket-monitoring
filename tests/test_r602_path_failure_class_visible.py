# -*- coding: utf-8 -*-
"""r602：渠道健康的「分通路」小标必须能定位**为什么**掉，不能只有百分比。

用户要求「可区分、可定位、状态清晰」。渠道健康的通路维（r415）此前只给
成功率：`H5 80% · PC 100%`。但同样的 20%，是「登录墙」还是「软拒」决定
用户该做什么——前者重登能解，后者只能等它自愈。逐格 title 里有信息，
但要一格一格点开才能在 7 天账本里拼出来。

真实账本（`data/prices.db`，2026-10-29 实测）确实有这个形态：
    qunar  H5     ok 131 / login 70 / soft_reject 8 / empty 9
    qunar  API    ok 5   / login 20 / empty 4
其中 login 与 soft 是分开计数的（core/storage.py 的 bump 分支），前端
只要读出来即可——所以缺的是展示，不是数据。
"""
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_path_label_carries_failure_classes():
    w = _w()
    i = w.index("const _pi=(j.paths||{})[p]||{};")
    seg = w[i:i + 1200]
    assert "_v.login" in seg, "通路小标没有读登录墙计数"
    assert "_v.soft" in seg, "通路小标没有读软拒计数"
    assert "需登录" in seg and "软拒" in seg, "通路小标没有给出中文分类名"


def test_failure_classes_only_shown_when_present():
    """正常通路不得被加上噪声——只在计数 >0 时附注。"""
    w = _w()
    i = w.index("const _pi=(j.paths||{})[p]||{};")
    seg = w[i:i + 1200]
    assert "if((_v.login||0)>0)" in seg, "登录墙没有做 >0 判断"
    assert "if((_v.soft||0)>0)" in seg, "软拒没有做 >0 判断"


def _render_health(paths):
    """起一个 demo 服，喂合成 paths 给 renderHealth，回收 .hpath 文本。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                op.open(base + "/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            import os as _os
            if not _os.path.exists(p.chromium.executable_path):
                import pytest
                pytest.skip("chromium 二进制缺失")
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            got = pg.evaluate("""(paths)=>{
              const j={rounds:[{ts:'12:00',plats:{qunar:{ok:2,cal:0,detail:2}}}],
                last_seen_at:'2026-10-29 11:40',
                stats:{qunar:{ok:2,part:0,fail:0,rate:1.0,
                  cal:0,detail:2,detail_ok:2,cal_only:0,auth:0}},
                by_scope:{}, paths:{qunar:paths}};
              renderHealth(j);
              const e=document.querySelector('#healthcard .hpath');
              return e?e.textContent:null;}""", paths)
            b.close()
            return got
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def test_renders_failure_class_for_a_login_walled_path():
    """真渲染：登录墙要出现在通路小标里（这是用户实际读到的字）。"""
    got = _render_health({
        "paths": {
            "H5": {"attempts": 10, "ok": 2, "rate": 0.2, "login": 7, "soft": 1},
            "PC": {"attempts": 5, "ok": 5, "rate": 1.0, "login": 0, "soft": 0},
        },
        "retired": [],
    })
    assert got, "通路小标没有渲染"
    # 通路小标自 r636 起带口径词与样本数（`H5 单次 20%（10 次 · 需登录 7 …）`）：
    # 域级是查询口径、通路级是尝试口径，不标就会被读成同一个分母。
    assert re.search(r"H5 单次 20%", got), got
    assert "需登录 7" in got, "登录墙次数没有出现在小标里：%s" % got
    assert "软拒 1" in got, "软拒次数没有出现在小标里：%s" % got
    # 正常通路不该被挂上分类噪声
    assert "需登录 0" not in got and "软拒 0" not in got, \
        "健康通路被加了失败分类噪声：%s" % got


def test_render_omits_classifier_when_no_failures():
    got = _render_health({
        "paths": {"PC": {"attempts": 9, "ok": 9, "rate": 1.0,
                         "login": 0, "soft": 0}},
        "retired": [],
    })
    assert got and re.search(r"PC 单次 100%", got), got
    assert "需登录" not in got and "软拒" not in got, got


def test_pacing_panel_path_line_uses_the_same_classifier():
    """同一份账本在两处渲染，分类口径必须一致（r602）。

    渠道健康卡与节流面板速览都列「通路 成功率」。只在一处加分类，
    同屏会出现「健康卡说需登录 7、节流面板只说 20%」的两种说法——
    这正是用户反复提的「不要两个面板互相矛盾」。
    """
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("const pws=[];")
    seg = w[i:i + 900]
    assert "w.login" in seg, "节流面板通路行没有读登录墙计数"
    assert "w.soft" in seg, "节流面板通路行没有读软拒计数"
    assert "需登录" in seg and "软拒" in seg, "节流面板通路行缺中文分类名"
    # 两处必须各自都在：一处被删就是口径分叉。
    # 按拼接表达式精确计数——`'需登录 '` 在徽标 caption 里还有一处，
    # 用宽口径会把「少了一处」误判成达标（负控实测）。
    assert "_fx.push('需登录 '+_v.login)" in w, "健康卡通路行的分类被删了"
    assert "_pf.push('需登录 '+w.login)" in w, "节流面板通路行的分类被删了"
