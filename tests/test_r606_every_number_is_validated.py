# -*- coding: utf-8 -*-
"""r606：配置页每个数字输入都必须有范围校验，越界要当场标红。

`glcell` 对**所有**数字输入都挂了 `oninput="glbCheck(this)"`，但 `glbCheck`
是按 `GLB_RANGES` 查表的——查不到就 `return null` 静默放行。实测全局参数面板
31 个数字控件里只有 5 个在表内（扫描周期/端口/采集超时/两处错峰），其余
26 个键入越界值时：输入框留着原值、onchange 里的 `Math.min/max` 把它夹掉、
保存下去的是夹后的值——用户看不出自己填的没生效。

本文件守三件事：
  1. 覆盖：面板里每个数字控件都能被 `glbRangeOf()` 解析出边界；
  2. 解析：比率/倍数类是小数字段，`parseInt('0.05')===0` 会永远判越界；
  3. 保存与输入同源：保存侧也要拦动态 id（`glbCad_*`），否则「输入标红、
     保存放行」两套结论。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_decimal_fields_parse_as_float():
    w = _w()
    i = w.index("function glbCheck(el,returnMsg)")
    seg = w[i:i + 500]
    assert "r.dec?parseFloat(v):parseInt(v)" in seg, (
        "比率/倍数类用 parseInt 会把 0.05 读成 0 → 永远判越界")


def test_dynamic_ids_resolved_by_prefix():
    w = _w()
    assert "GLB_RANGES_DYN" in w, "没有动态前缀规则表"
    assert "function glbRangeOf(" in w, "没有统一的范围解析入口"
    i = w.index("const GLB_RANGES_DYN=[")
    seg = w[i:i + 400]
    assert "glbCad_" in seg, "渠道节奏（动态 id）没有覆盖"


def test_save_path_also_checks_dynamic_ids():
    """输入侧标红、保存侧放行 = 两套结论；保存也要用同一解析器。"""
    w = _w()
    i = w.index("async function saveCfg()")
    seg = w[i:i + 2600]
    assert "glbRangeOf(el.id)" in seg, "保存侧没有覆盖动态 id 控件"


def test_every_numeric_control_has_a_range():
    """真渲染：面板里每个数字输入都要能被 glbRangeOf 解析（含动态 id）。"""
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
            pg = b.new_page(viewport={"width": 1400, "height": 1000})
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="globals"]');if(c)c.click()}""")
            pg.wait_for_timeout(900)
            got = pg.evaluate("""()=>{
              const ids=[...new Set([...document.querySelectorAll(
                  '#panel-globals input[type=number], #panel-pacing input[type=number], #cfgform .glcell input[type=number]')]
                .filter(e=>e.id).map(e=>e.id))];
              const miss=ids.filter(i=>!glbRangeOf(i));
              const probe=(id,v)=>{
                const e=document.getElementById(id);if(!e)return null;
                e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));
                const d=document.getElementById(id+'Err');
                return {txt:d?d.textContent:'',
                        vis:d?getComputedStyle(d).display:''};};
              return {n:ids.length, missing:miss,
                over:probe('glbHok','5'),      /* 比率越界 */
                okDec:probe('glbHok','0.8'),   /* 合法小数 */
                under:probe('glbAndBoot','1'),
                cad:probe('glbCad_qunar','99999')}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert got["n"] >= 25, "控件数量异常：%s" % got
    assert not got["missing"], "这些数字控件没有任何范围校验：%s" % got
    assert got["over"]["vis"] == "block" and "合格线" in got["over"]["txt"], (
        "比率越界没有标红：%s" % got)
    assert got["okDec"]["vis"] == "none", (
        "合法小数被误判越界（parseInt 吃掉了小数）：%s" % got)
    assert got["under"]["vis"] == "block", "整数越界没有标红：%s" % got
    assert got["cad"]["vis"] == "block", "动态 id 控件没有校验：%s" % got

def test_table_bounds_match_backend_clamps():
    """表里的 min/max 必须与后端 `parse_pacing` 的钳制一致。

    实测踩过：`per_minute` 后端下界是 **0**（0 = 不限），我凭 onchange 里
    的 `Math.max(0,…)` 手抄时写成了 1 —— 于是默认值 0 被判越界，
    **保存直接被拦**（`test_save_demo_readonly_gate` 与特价保存两条同时红）。
    边界不是文案，抄错一次就是「默认配置存不下去」。
    """
    import sys
    sys.path.insert(0, ROOT)
    from core.pacing import parse_pacing
    got = parse_pacing({"crawler": {
        "rate": {"per_minute": -5, "min_gap_s": -1},
        "max_concurrency": -1,
        "stagger_seconds": -1,
        "fast_ttl_min": 1,
        "slow_ttl_min": 1,
        "near_ratio": -1,
        "near_days": -1,
    }})
    # 负值一律夹回下界（不是拒绝），说明后端认的下界就是这些
    assert got["per_minute"] == 0, got["per_minute"]
    assert got["min_gap_s"] == 0, got["min_gap_s"]
    assert got["max_concurrency"] >= 0
    assert got["stagger_seconds"] == 0, got["stagger_seconds"]
    # 这几项后端对非法值是「回落默认」而不是「夹到边界」——判据是
    # 「非法输入不得原样通过」，不是「等于某个具体边界」。
    assert got["fast_ttl_min"] >= 5, got["fast_ttl_min"]
    assert got["slow_ttl_min"] >= 5, got["slow_ttl_min"]
    assert got["near_ratio"] >= 0, got["near_ratio"]
    assert got["near_days"] >= 0, got["near_days"]


def test_declared_zero_is_valid_where_backend_allows_zero():
    """凡是后端允许 0 的项，前端校验表下界也必须是 0（否则默认值存不下去）。"""
    w = _w()
    for cid in ("glbRpm", "glbGap", "glbSessMax", "glbMaxConc", "glbNearD",
                "glbJt", "glbStg"):
        i = w.index("{id:'%s'" % cid)
        seg = w[i:i + 90]
        assert "min:0" in seg, "%s 的下界不是 0（后端允许 0=不限）：%s" % (cid, seg)
