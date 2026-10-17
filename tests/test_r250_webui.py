# -*- coding: utf-8 -*-
"""r250 WebUI P2-1（TDD 先行，审计报告 _scratch/r250_webui_audit.md）：

P2-1 明细数据行键盘焦点环左缘 2px 被首列吸附格不透明底遮蔽——
    #ftable tbody tr:focus-visible 的 inset 蓝环（L523）画在 tr 装饰层，
    而首列 td 自带不透明背景（吸附打底 L966 族/斑马/qual tint），td 背景
    绘制恒在 tr 装饰之上：键盘 ↑↓ 巡航明细行时环的左缘 x∈[0,2) 差分为
    零，价格锚定列一侧无焦点指示（环呈「左开口」三缘形态）。r249 P1-1
    修的是表头首列同一病灶，行族未随同收编。
    修法：环落 td 自身才在吸附列之上（tr 层修法无效）——置尾追加
    #ftable tbody tr:focus-visible td:first-child{box-shadow:inset 2px 0 0
    var(--blue),2px 0 0 var(--line)}（ID 特异度恒压 (0,2,1) 打底块；
    与吸附分隔投影双影并存，r249 表头修法同语言）。
    源码钉锁「新规则在场且 rindex 晚于投影声明」+ computed 行为钉锁
    「行聚焦时首格 boxShadow 含 inset 蓝环与投影双影」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r250_webui.py
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- P2-1: 明细行首列焦点环（源码序层叠钉 + computed 行为钉） ----------

def test_row_firstcol_focus_ring_source_pin():
    src = _page_src()
    ring = "#ftable tbody tr:focus-visible td:first-child{"
    assert ring in src, (
        "明细数据行缺首列焦点环复声明：tr:focus-visible 的 inset 环画在 "
        "tr 装饰层，被首列吸附格不透明底（--card/斑马/qual tint）盖住左缘 "
        "2px——环必须落 td 自身才在吸附列之上（tr 层修法无效）")
    proj = ".tw th:first-child,.tw td:first-child{"
    assert src.index(proj) < src.index(ring), (
        "行首列焦点环复声明必须置尾于吸附投影声明之后：同族层叠胜负由"
        "源码序决定（ID 特异度已恒压，序钉防未来同特异性块前插）")
    m = src.index(ring)
    seg = src[m:m + 220]
    assert "inset 2px 0 0 var(--blue)" in seg and "2px 0 0 var(--line)" in seg, (
        "行首列焦点环须双影叠加：inset 左缘蓝段（三值形态 x=2，非表头"
        "四值全环）+ 吸附投影共存（单写 inset 会吃掉首列吸附分隔投影，"
        "r249 表头修法同语言）")


def test_row_firstcol_focus_ring_computed(srv):
    """行为钉：明细数据行聚焦（focus-visible）时其首格 td 的 computed
    boxShadow 含双影——inset 蓝环 + 非环影颜色==--line 实色（吸附投影）。
    投影判据锚「--line 色值在场」而非几何正则：几何形如「2px 0px 0px」
    与 inset 环自身文本同形，正则判据在单影变异下空转（Soldier P2-1，
    M3 变异实证）。"""
    pw, page = srv
    got = page.evaluate("""() => {
      showMonTab('details');
      const tr=document.querySelector('#ftable tbody tr[data-k]');
      if(!tr)return 'NO_ROW';
      tr.focus({focusVisible:true});
      const td=tr.querySelector('td:first-child');
      const bs=getComputedStyle(td).boxShadow;
      const cs=getComputedStyle(document.documentElement);
      const toRgb=(hx)=>{const n=parseInt(hx.slice(1),16);
        return 'rgb('+((n>>16)&255)+', '+((n>>8)&255)+', '+(n&255)+')';};
      const blue=toRgb(cs.getPropertyValue('--blue').trim());
      const line=toRgb(cs.getPropertyValue('--line').trim());
      return {inset: bs.indexOf('inset')>=0,
              blueOk: bs.indexOf(blue)>=0, blue: blue,
              lineOk: bs.indexOf(line)>=0, line: line, bs: bs};
    }""")
    assert got != 'NO_ROW', "明细表未渲染数据行（demo 数据缺表格）"
    assert got["inset"], "行聚焦时首格无 inset 蓝环（左缘被吸附底遮蔽） bs=%s" % got["bs"]
    assert got["blueOk"], "行首列焦点环非蓝（--blue=%s 不在 %s）" % (
        got["blue"], got["bs"])
    assert got["lineOk"], (
        "行首列焦点环吃掉吸附投影（双影须共存；判据=非环影含 --line=%s "
        "实色，几何正则会命中 inset 环自身偏移文本空转） bs=%s" % (
            got["line"], got["bs"]))


# ---------- playwright srv fixture（demo 实例，行为钉共用；r245 加固版） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _srv_log_tail(logf):
    try:
        logf.flush()
        logf.seek(0)
        return logf.read()[-600:]
    except Exception:
        return "(日志不可读)"


@pytest.fixture(scope="module")
def srv():
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8798" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    base = None
    for _attempt in (1, 2):
        base = "http://127.0.0.1:%d" % _free_port()
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(base.rsplit(":", 1)[1])],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(40):
            try:
                op.open(base + "/api/state", timeout=2)
                break
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(0.5)
        else:
            continue
        if proc.poll() is None:
            break
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）\n服务输出尾:\n"
                    + _srv_log_tail(logf))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base, wait_until="networkidle")
        yield p, page
        browser.close()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if errors:
        raise AssertionError("demo 页面 JS 错误: %s" % errors)
