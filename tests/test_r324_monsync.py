# -*- coding: utf-8 -*-
"""r324 监控面一致性钉（穷举审计 F1/F3/F4 + F2 假案正面锚）：

- F1（P1）明细行 📈 跳走势：jumpRowTrend 曾缺 renderCal()——走势卡
  与价格日历同屏两航线结论并存（LASTTXT 签名门使轮询不自愈）；钉=
  跳转后 calTitle 与目标航线同拍（togChart/setRange 同律）。
- F2 撤案正面锚：启动块 4582 已有「深链用户段恢复」（restoreUI 之后、
  越界钳制自愈）——审计假案（行号漂移期漏读），锚防下轮重复发现。
- F3 pulse 签名记账先于消费：state 空守卫早退时 PU 已记账，pulsecard
  缺席至 /api/pulse 文本变化——守卫前移到记账之前。
- F4 render 异常拍被 LASTTXT 吞：异常分支补签名失效，自愈从「数据
  变化拍」提前到「下一拍」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_monsync.py -q
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    import subprocess
    import tempfile
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    import tempfile as _tf
    priv_tmp = _tf.mkdtemp(prefix="r324ms_")
    env = dict(os.environ, TEMP=priv_tmp, TMP=priv_tmp,
               TMPDIR=priv_tmp)
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        if _wait_up(proc):
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture()
def page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        yield pg
        browser.close()


def test_f1_jump_row_trend_updates_cal(page):
    """明细行 📈 跳走势后：calTitle 与目标航线同拍（不再停旧航线）。"""
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("showMonTab('details');table();")
    page.wait_for_timeout(400)
    out = page.evaluate("""(() => {
      const u = S.users[U];
      const arr = u.routesArr || [];
      if (arr.length < 2) return {skip: true};
      const cur = (typeof CHR[u.name] === 'number')
        ? CHR[u.name] : ((CHR[u.name] || {}).i || 0);
      const tgt = (cur + 1) % arr.length;
      const e = arr[tgt];
      const m = String(e.label || '').match(/^(.*) (\\d\\d\\/\\d\\d)$/);
      const rt = m ? m[1] : (e.from_name + '→' + e.to_name);
      const d = m ? m[2] : String(e.date || '').slice(5).replace('-', '/');
      jumpRowTrend(rt, d);
      return {rt, tgt,
              calTitle: document.getElementById('calTitle').textContent,
              chrI: (CHR[u.name] || {}).i};
    })()""")
    if out.get("skip"):
        pytest.skip("demo routesArr <2（无多航线跳转面）")
    assert out["chrI"] == out["tgt"], out
    assert out["rt"] in out["calTitle"], out


def test_source_pins_monsync():
    """源码钉：F3 守卫前移、F4 签名失效、F2 启动深链消费正面锚。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    pi = src.find("async function pulse(")
    assert pi >= 0, "pulse 应在案"
    pbody = src[pi:pi + 800]
    guard = "if(!(S&&S.users&&S.users.length))return;"
    assert guard in pbody and pbody.index(guard) < pbody.index("PU=t"), (
        "pulse 空守卫应先于签名记账（F3）")
    ri = src.find("console.error('render:',e)")
    assert ri >= 0, "render 异常拍应在案"
    assert "LASTTXT=''" in src[ri:ri + 220], (
        "render 异常分支应失效签名（F4：自愈提前到下一拍）")
    assert "深链用户段恢复" in src and "U=Math.min(_un,99)" in src, (
        "启动深链消费正面锚（F2 撤案防重复发现）")
