# -*- coding: utf-8 -*-
"""r605：配置页的「隐式夹取」必须当场回写并说明，不能静默改值。

用户要求「可配置可准确可对齐」。健康保护有两条真实约束，后端
（`core/pacing.py` 的 `parse`）会实施，前端 onchange 也会夹：

    health_slow_ratio  ≤ health_ok_ratio        （降频线 ≤ 合格线）
    health_slowest_factor ≥ health_slow_factor  （重降频倍数 ≥ 轻降频倍数）

问题不是「该不该夹」，而是**夹了不说**：输入框留着用户键入的原值
（实测键入 0.9），`GLB` 里存的是 0.7，保存下去也是 0.7——「我配了 0.9，
实际跑 0.7」，既不报错也不提示。`glcell` 早就留了 `.verr` 出错位，
但全站从未使用（`display:none` 且无人写）。

修法：`glbClamp(el, id, applied, reason)` 统一回写真实生效值 + 显示原因，
6 秒后自动收起。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_clamp_helper_exists_and_shows_reason():
    w = _w()
    assert "function glbClamp(" in w, "缺少夹取反馈函数"
    i = w.index("function glbClamp(")
    seg = w[i:i + 900]
    assert "box.textContent=reason" in seg, "没有把原因写进提示位"
    # 样式表 `.glcell .verr{display:none}` 会压过空串：必须显式 block，
    # 否则「回写发生了、解释永远看不见」（实测 display 仍是 none）
    assert "box.style.display='block'" in seg, "提示位没有真正显示"
    assert "el.value=txt" in seg, "没有把输入框回写成真实生效值"


def test_three_constraints_call_the_helper():
    w = _w()
    for cid, keyword in (("glbHslow", "降频线不能高于合格线"),
                         ("glbHslf", "重降频倍数不能低于轻降频倍数"),
                         ("glbBcs", "熔断封顶")):
        i = w.index("'%s'" % cid)
        seg = w[i:i + 400]
        assert "glbClamp(this" in seg, "%s 没有调用夹取反馈" % cid
        assert keyword in seg, "%s 的提示没说明被夹原因" % cid


def test_clamp_rules_match_backend():
    """前端夹取规则必须与后端 parse 的上下界一致，否则两边会打架。"""
    import sys
    sys.path.insert(0, ROOT)
    from core.pacing import parse_pacing
    got = parse_pacing({"crawler": {"health_ok_ratio": 0.7,
                                    "health_slow_ratio": 0.9,
                                    "health_slow_factor": 1.5,
                                    "health_slowest_factor": 1.0}})
    assert got["health_slow_ratio"] <= got["health_ok_ratio"], got
    assert got["health_slowest_factor"] >= got["health_slow_factor"], got


def test_render_rewrites_input_and_shows_reason():
    """真渲染：键入越界值 → 输入框回到生效值 + 说明可见。"""
    import json
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

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
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="globals"]');if(c)c.click()}""")
            pg.wait_for_timeout(900)
            got = pg.evaluate("""()=>{
              const ok=document.getElementById('glbHok');
              const slow=document.getElementById('glbHslow');
              if(!ok||!slow)return {missing:true};
              ok.value='0.7';
              ok.dispatchEvent(new Event('change',{bubbles:true}));
              slow.value='0.9';
              slow.dispatchEvent(new Event('change',{bubbles:true}));
              const err=document.getElementById('glbHslowErr');
              let g=null;try{g=GLB}catch(e){}
              return {shown:slow.value, state:g&&g.health_slow_ratio,
                      errTxt:err?err.textContent:'',
                      errVis:err?getComputedStyle(err).display:''}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert not got.get("missing"), "找不到阈值控件：%s" % got
    assert float(got["shown"]) == 0.7, "输入框没有回写成生效值：%s" % got
    assert float(got["state"]) == 0.7, "状态没有夹到合格线：%s" % got
    assert "不能高于合格线" in got["errTxt"], "没说明为什么被改：%s" % got
    assert got["errVis"] == "block", "说明不可见（被 .verr 的 display:none 压住）：%s" % got
