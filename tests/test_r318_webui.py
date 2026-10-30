# -*- coding: utf-8 -*-
"""r318 WebUI 落地钉（_scratch/worker_r318_webui.md 审计消化）：

- W-1 (P2) 配置分区恢复块 TDZ 断折：初始化路径 showCfgPanel 先于
  CFGQ 声明执行，函数内 `if(CFGQ)` 抛 ReferenceError 被恢复块 catch
  静默吞（零 console 错=零 JS 错门禁盲区）——「记住上次分区」每次
  断折且逻辑态（CFGPANEL 已赋值）/视觉态（面板 display 未切）劈叉。
  修复=恢复块移至声明序之后。钉=预置 localStorage 分区恢复值加载页，
  断言目标面板真实可见——单看 CFGPANEL 抓不住劈叉。
- W-2 (P2) 已弃值复活：discardCfg→loadCfg 重建销毁焦点中的脏输入，
  销毁性 blur 迟到 change 以 DOM 旧值写回模型（GLB=脏值/表单=服务端
  值/CLEAN=服务端值三方劈叉），再点保存落盘已弃值。修复=loadCfg 内
  buildForm 前复位焦点元素 dirty 基准（放 loadCfg 不放 buildForm：
  添加通道类有意重建的保脏值语义不受累）。钉=程序化路径（无
  mousedown 转焦）调 discardCfg，等重建完成后断言模型==服务端值。
- W-3 (P3) .tj 外扩热区横向收敛：富信息行 route 词组恰在行中心的
  偶发几何下，::after 横向外扩放大跳走势劫持面（行中心点击真实
  复现）；横向收 0（纵向 -11px 触控 36px 基准保留、横向 32.5 本体
  在案豁免档不变）后劫持面缩至本体词组。钉=源码钉+computed inset。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r318_webui.py -q
"""
import os
import sys
from pathlib import Path

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
    # demo 合成库固定落 %TEMP%/ticket_demo_prices.db（写密集：14 天×
    # 48 轮 INSERT）——外部 demo 实例并行重建时写锁让本 demo 阻塞在
    # 「进程活、不监听」形态；每模块独立 TEMP 根治共享竞态
    import tempfile as _tf
    priv_tmp = _tf.mkdtemp(prefix="r318demo_")
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
            proc.kill()   # 重试前杀旧实例：防泄漏+防两进程互抢 DB
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            logf.flush()
            logf.seek(0)
            tail = logf.read()[-600:]
        except Exception:
            tail = "(日志不可读)"
        pytest.fail("demo 启动失败（两次新端口重试后）\n服务输出尾:\n" + tail)
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


def test_cfg_panel_restore_lands_visible(page):
    """预置 jpcfgpanel='globals' 加载页：globals 面板必须真实可见
    （修前 TDZ 断折→display 停在 login，CFGPANEL/视觉态劈叉）。"""
    page.add_init_script(
        "try{localStorage.setItem('jpcfgpanel','globals')}catch(e){}")
    page.goto(BASE + "/")
    page.wait_for_function(
        "typeof CFGPANEL!=='undefined' && CFGPANEL==='globals'")
    st = page.evaluate("""() => {
      const g = document.querySelector('#panel-globals');
      const l = document.querySelector('#panel-login');
      return {g: g ? g.style.display !== 'none' : null,
              l: l ? l.style.display !== 'none' : null};
    }""")
    assert st["g"] is True, st
    assert st["l"] is False, st


def test_discard_cfg_no_ghost_writeback(page):
    """焦点脏输入下程序化放弃：重建后模型必须==服务端值（修前迟到
    change 把 DOM 旧值 42 写回 GLB，再保存即落盘已弃值）。"""
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg'); showCfgPanel('globals')")
    page.wait_for_function(
        "typeof CFG!=='undefined' && CFG && document.querySelector('#glbIv')"
        " && document.querySelector('#glbIv').offsetParent !== null")
    page.focus("#glbIv")
    page.fill("#glbIv", "42")   # fill 只发 input：脏值未提交、焦点仍在
    page.evaluate("discardCfg()")
    # 等重建完成（新 #glbIv 以服务端值渲染）——innerHTML 与销毁事件
    # 同任务同步派发，此刻迟到 change（若在）已落定，读 GLB 即终态
    page.wait_for_function(
        "() => {const el = document.querySelector('#glbIv');"
        " return el && el.value === '15';}", timeout=8000)
    v = page.evaluate("GLB.interval_minutes")
    assert v == 15, v


def test_tj_hotzone_horizontal_converged(page):
    """.tj 外扩热区横向收 0：源码钉+computed inset 双证（纵向 -11px
    触控基准保留）。"""
    src = Path(os.path.join(ROOT, "webui.py")).read_text(encoding="utf-8")
    assert ".tj::after{content:'';position:absolute;inset:-11px 0}" in src
    page.goto(BASE + "/")
    # 明细表只在 details 子栏渲染（render 在非明细视图跳过重建）——
    # 切子栏触发 table() 后 .tj 才入场
    page.evaluate("showMonTab('details')")
    page.wait_for_selector("#ftable tbody tr .tj")
    ins = page.evaluate(
        "() => {const cs = getComputedStyle("
        "document.querySelector('#ftable tbody tr .tj'), '::after');"
        " return cs.top + '|' + cs.right;}")
    assert ins == "-11px|0px", ins
