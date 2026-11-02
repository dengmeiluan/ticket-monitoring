# -*- coding: utf-8 -*-
"""r251 WebUI 落地钉（_scratch/r251_webui.md 审计消化）：

- W-1 (P2-1) 800ms 脏态巡检的无条件 textContent 重写 = 后台常驻
  childList 脉冲：textContent 同值赋值仍按规范删+插文本节点产
  childList 突变（空闲净态实测 ~75 次/分，监控/配置两视图各一份），
  翻译/比价类 MutationObserver 扩展被持续唤醒（LESSONS 十二§3 的
  定时器路径漏网面）。修法：写前守卫（同 nrSay 先例）——净态下
  连续 ≥2 个巡检周期 childList 零突变。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r251_webui.py -q
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
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    PORT = _free_port()
    BASE = "http://127.0.0.1:%d" % PORT
    logf = tempfile.TemporaryFile("w+", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"),
         "--demo", "--port", str(PORT)],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
    if not _wait_up(proc):
        proc.kill()
        logf.seek(0)
        pytest.fail("demo 服务未起来：%s" % logf.read()[-600:])
    yield proc
    proc.kill()
    logf.close()


def _page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(BASE, wait_until="networkidle")
        yield pg
        b.close()


@pytest.fixture(scope="module")
def page(srv):
    yield from _page(srv)


def test_idle_dirty_poll_zero_childlist_mutation(page):
    """净态空闲 ≥2 个巡检周期：#saveTxt/#cfgDirty 的 childList 突变=0。

    修复前：巡检每 800ms 无条件 textContent 重写（同值也删+插文本
    节点），~2s 观察窗内两件合计 ≥2 条突变。
    """
    mutations = page.evaluate(
        """async () => {
            // 静态 HTML 初始文案（"有未保存的修改"）≠ 巡检净态文案
            // （"0 处未保存的修改"）：saveTxt 的首个巡检周期是一次合法
            // 的初始化写——先等它落完（≥1 周期），再开始观察净态。
            await new Promise(r => setTimeout(r, 1200));
            const targets = ['saveTxt', 'cfgDirty']
                .map(id => document.getElementById(id))
                .filter(Boolean);
            if (!targets.length) return {error: '巡检目标件不存在'};
            let n = 0;
            const mo = new MutationObserver(ms => {
                for (const m of ms) if (m.type === 'childList') n++;
            });
            targets.forEach(t => mo.observe(t, {childList: true}));
            await new Promise(r => setTimeout(r, 2000));  // ≥2 个 800ms 周期
            mo.disconnect();
            return {mutations: n,
                    saveTxt: (document.getElementById('saveTxt')||{}).textContent};
        }""")
    assert "error" not in mutations, mutations
    # 净态前提钉死：demo 无 UI 编辑，n 恒 0——否则「恒脏下的零突变」
    # 会以「净态零突变」名义空过（前提失效守卫照样绿）
    assert mutations["saveTxt"] == '0 处未保存的修改', (
        "钉前提失效：demo 非净态 saveTxt=%r" % mutations["saveTxt"])
    assert mutations["mutations"] == 0, (
        "净态巡检仍在重写文本节点（childList 突变 %d 次，写前守卫缺失）"
        % mutations["mutations"])


def test_savebar_text_still_updated_on_dirty_flip(page):
    """守卫不改变语义：脏态计数变化时文案仍要更新（守卫只挡同值重写）。"""
    result = page.evaluate(
        """() => {
            const st = document.getElementById('saveTxt');
            if (!st) return {error: 'saveTxt 不存在'};
            const before = st.textContent;
            // 直接驱动巡检块读到的状态源不可行（页面闭包），
            // 退而验证：手动把 saveTxt 置为陈旧文案后，等一个巡检
            // 周期，巡检应把它写回当前正确文案（不同值→允许写）。
            st.textContent = '___stale___';
            return {before, stale: 'set'};
        }""")
    assert "error" not in result, result
    page.wait_for_timeout(1200)  # ≥1 个 800ms 周期
    after = page.evaluate(
        "() => (document.getElementById('saveTxt')||{}).textContent")
    assert after != '___stale___', (
        "巡检被守卫完全堵死：陈旧文案未被巡检写回（守卫只应挡同值重写）")
    assert '处未保存的修改' in after, "巡检写回的不是正确文案：%r" % after


def test_scan_window_nextrun_zero_childlist_mutation(page):
    """扫描窗净态（Soldier P2-2 同律收口）：#nextrun 恒「🔄 扫描中…」
    时每秒 tick 同值重写同样产 childList 脉冲——写前守卫应零突变。
    放流程最末（setNext 置 NEXTRUN 远过去，污染页面倒计时态，
    十八§6 新钉置尾纪律）。"""
    mutations = page.evaluate(
        """async () => {
            // NEXTRUN 置远过去 → d<=0 恒真 → tick 每秒走「扫描中…」分支
            setNext('2000-01-01 00:00:00');
            // 首拍是真变（原倒计时文案 → 「🔄 扫描中…」），先等它落完
            await new Promise(r => setTimeout(r, 1200));
            const el = document.getElementById('nextrun');
            if (!el) return {error: 'nextrun 不存在'};
            let n = 0;
            const mo = new MutationObserver(ms => {
                for (const m of ms) if (m.type === 'childList') n++;
            });
            mo.observe(el, {childList: true});
            await new Promise(r => setTimeout(r, 2000));  // 2 个 1s tick 周期
            mo.disconnect();
            return {mutations: n, text: el.textContent};
        }""")
    assert "error" not in mutations, mutations
    # 净态前提：观察窗内文案恒「扫描中…」（真变不在窗内）
    assert mutations["text"] == '🔄 扫描中…', (
        "钉前提失效：扫描窗文案漂移 %r" % mutations["text"])
    assert mutations["mutations"] == 0, (
        "扫描窗每秒同值重写 #nextrun（childList 突变 %d 次，写前守卫缺失）"
        % mutations["mutations"])
