# -*- coding: utf-8 -*-
"""r245 WebUI 落地钉（_scratch/r245_webui.md 审计消化）：

- W-1 (P3-1) 走势卡「线内区间/直飞达标线/中转达标线」三枚图例色票与
  ringNote 环标句随心理价缺省（th=0）隐藏——zone/dash/TIER 对 0 全
  no-op，色票对空挂图例=装饰信号领先数据（二十三§6；calStats 档位
  图例「仅 th>0 拼接」同族半迁移收口，判定式同源防漂移）。
  th=0 恰是 UI 新建用户/航线的默认值（alert_direct=0）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r245_webui.py -q
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 动态空闲端口：固定端口在共享 runner 上有占用竞态（CI ubuntu 8797
# 被占→demo 绑定失败静默退场→探活 20s 超时假红），起服前现场取口
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
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False   # 服务进程已死：速败留诊断，不烧满 20s 探活
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _srv_log_tail(logf):
    try:
        logf.flush()
        logf.seek(0)
        return logf.read()[-600:]
    except Exception:
        return "(日志不可读)"


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    # 残留清理（动态端口下通常无残留；netstat/taskkill 为 Windows
    # 形态，非 Windows 或命令缺失静默跳过——清理是保险不是前置）
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8797" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    # 两次机会：每次新取空闲口重绑；服务 stdout/stderr 同收一缓冲，
    # 失败断言带日志尾——CI Linux 独有红的第一手定性证据（r245
    # 首轮 CI 红为无诊断裸断言，红因不可见只能远猜）。
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
        if _wait_up(proc):
            break
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）\n服务输出尾:\n"
                    + _srv_log_tail(logf))
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture(scope="module")
def pg(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10000)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        yield page
        b.close()


def test_th_legend_tickets_follow_threshold(pg):
    """三色票逐侧门：th=0 全隐 + 环标句退场；单侧在位仅隐缺席侧；
    恢复后全部回位（chart() 每次重算无条件重写，恢复条件与
    lgDirect/lgTrans 同律）。demo 数据 th>0 恒真故以页面内变异取态。"""
    m = pg.evaluate("""(()=>{
      showMonTab('trend');
      const g=id=>getComputedStyle(document.getElementById(id)).display;
      const r=curRoute().r, keep=r.th;
      const set=(d,t)=>{r.th={direct:d,transfer:t};chart();};
      set(0,0);
      const off={zone:g('lgZone'),thD:g('lgThD'),thT:g('lgThT'),
                 ringGone:$('ringNote').innerHTML.indexOf('环标：')<0};
      set(keep.direct,0);
      const half={zone:g('lgZone'),thD:g('lgThD'),thT:g('lgThT')};
      set(keep.direct,keep.transfer);
      const on={zone:g('lgZone'),thD:g('lgThD'),thT:g('lgThT')};
      return {off:off,half:half,on:on,
              noteOn:$('ringNote').innerHTML.indexOf('环标：')===0};
    })()""")
    assert m["off"] == {"zone": "none", "thD": "none", "thT": "none",
                        "ringGone": True}, m
    assert m["half"]["zone"] != "none", m
    assert m["half"]["thD"] != "none", m
    assert m["half"]["thT"] == "none", m
    assert all(v != "none" for v in m["on"].values()), m
    assert m["noteOn"], m


def test_th_legend_tickets_kline_mode(pg):
    """K 线模式同门：达标虚线/区间在 K 线模式照画（dash 调用无模式
    分流），色票门只看 th 不看模式；th=0 时 K 线环标词表段退场而
    桶语义句保留（行首无悬挂 <br>）。"""
    m = pg.evaluate("""(()=>{
      showMonTab('trend');setMode('kline');
      const g=id=>getComputedStyle(document.getElementById(id)).display;
      const r=curRoute().r, keep=r.th;
      r.th={direct:0,transfer:0};chart();
      const off={zone:g('lgZone'),thD:g('lgThD'),thT:g('lgThT'),
                 ringGone:$('ringNote').innerHTML.indexOf('环标：')<0,
                 bucketKept:$('ringNote').innerHTML.indexOf('K线=')>=0,
                 noLeadBr:$('ringNote').innerHTML.indexOf('<br>')!==0};
      r.th=keep;chart();setMode('line');
      return off;
    })()""")
    assert m["zone"] == "none" and m["thD"] == "none" and m["thT"] == "none", m
    assert m["ringGone"] and m["bucketKept"] and m["noLeadBr"], m
