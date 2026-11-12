# -*- coding: utf-8 -*-
"""r321 WebUI 审计落地（TDD 先行，审计报告 _scratch/r321_webui.md）：

P3-1 [城市面板触控热区欠 36px 地板] r320 全量城市化新组件未入触控
    家族清单——.cp-city 32px / .cp-abc 字母格 22×24px 是全站现役最小
    可点件（字母索引 26 格 gap 2px 手机误触率高），面板 ≤760 落地
    抽屉恰是触控主战场。修法：coarse 置尾块两条声明（.cp-city
    min-height:36px；.cp-abc span 28×36），晚于基础声明（LESSONS
    二十一§1 同特异性后者胜）；fine 桌面观感零变化。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r321_webui.py -q
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（自包含，形态同 test_r286_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8796" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
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
    assert proc.poll() is None, "demo 实例启动失败"
    from playwright.sync_api import sync_playwright as _sp
    with _sp() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base + "/", wait_until="networkidle")
        try:
            yield (p, page)
        finally:
            browser.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


# ---------- P3-1: 城市面板触控地板（源码钉 + coarse 行为钉） ----------

def test_demo_statecache_disabled_unit():
    """单元钉（r321 复现案）：demo 态快照读写禁用——demo 的
    _State.version 恒 'demo'，快照跨版本守卫（meta.ver != 当前版）
    在 demo 永真；demo 临时库路径/内容恒定 → sig 恒匹配（sig 不含
    进程态端口）。双守卫同时失效，旧 demo 进程的快照永久顶替当前
    进程构建：svc（页脚服务地址）冻结为旧进程端口，且 /api/state
    未来的任何新键都会被旧快照吞掉（结构性风险）。demo 响应构建
    毫秒级，快照零收益——demo 态 _state_cache_path 恒 None（读写
    同断一处收口）。"""
    import webui
    old_ver = webui._State.version
    old_cfg = webui._State.cfg
    try:
        webui._State.cfg = {"output": {"db_path": "data/x.db"}}
        webui._State.version = "demo"
        assert webui._state_cache_path() is None, \
            "demo 态仍落快照路径（跨版本守卫在 demo 永真=旧结构永续）"
        webui._State.version = "9.9.9"
        assert webui._state_cache_path() is not None, \
            "非 demo 态快照路径被误伤（生产 SWR 语义必须保留）"
    finally:
        webui._State.version = old_ver
        webui._State.cfg = old_cfg


def test_demo_state_svc_current_port(srv):
    """行为钉（r321 复现案的观察面复核）：demo /api/state 响应健康
    （快照门生效后恒走构建路径）——svc 在 demo 态恒空串（_State.srv
    仅生产路径挂载），body 各字段恒定，故 demo 快照顶替当前键集下
    零可观察伤害；本钉锁「响应可取且结构在案」，结构性风险（未来
    /api/state 新键被旧快照吞）由单元钉的 demo 门收口。"""
    pw, page = srv
    j = page.evaluate(
        "fetch('/api/state').then(r=>r.json()).then(j=>({demo:j.demo,"
        "users:(j.users||[]).length,keys:Object.keys(j).sort().join(',')}))")
    assert j["demo"] is True and j["users"] >= 1, \
        "demo /api/state 响应异常：%s" % j




def test_citypanel_touch_floor_source_pin():
    """源码钉：coarse 置尾块两条触控地板声明在场，且位置晚于
    .cp-city/.cp-abc span 基础声明（同特异性置尾胜——LESSONS
    二十一§1；早插会被基础块盖回=死声明）。"""
    src = _page_src()
    m = re.search(
        r"@media\(pointer:coarse\)\{"
        r"\s*\.cp-city\{min-height:36px\}\s*"
        r"\.cp-abc span\{min-width:28px;min-height:36px\}\}", src)
    assert m, "coarse 触控地板块缺失（或声明形态漂移）"
    i_city = src.find(".cp-city{display:inline-flex")
    i_abc = src.find(".cp-abc span{min-width:22px")
    assert 0 < i_city < i_abc < m.start(), (
        "置尾块必须晚于两条基础声明（层叠地位）")


def test_citypanel_touch_floor_computed(srv):
    """行为钉：coarse 仿真（CDP setTouchEmulationEnabled，二十三§4）
    390×844 抽屉档下 .cp-city 与 .cp-abc span 渲染高 ≥36px（红态=
    基础 32/24px 仍胜出=触控热区缺陷本体）。cityPanelOpen(document.body)
    程序化开面板：el 仅定位/回填用，量纲无涉。"""
    pw, page = srv
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setTouchEmulationEnabled",
             {"enabled": True, "maxTouchPoints": 5})
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        # 城市表走 /api/config（loadCfg 惰性加载，仅切配置视图时拉取，
        # /api/state 不含 city）——先落位 cfg 视图等 CITY 到位再开面板
        # （行为钉显式落位律：面板数据前提不落位=探针自己的世界）
        page.evaluate("switchView('cfg')")
        page.wait_for_function("Object.keys(CITY||{}).length>0",
                               timeout=10000)
        page.evaluate("cityPanelOpen(document.body)")
        page.wait_for_timeout(300)
        r = page.evaluate(
            """()=>{const c=document.querySelector('.cp-city');
                    const a=document.querySelector('.cp-abc span');
                    return {city:c?c.getBoundingClientRect().height:null,
                            abc:a?a.getBoundingClientRect().height:null};}""")
        assert r["city"] is not None and r["abc"] is not None, \
            "城市面板未渲染（cityPanelBuild 未跑/城市表缺席？）"
        assert r["city"] >= 36, \
            "coarse 390 .cp-city 高 %s px（32 基础仍胜出=热区欠地板）" % r["city"]
        assert r["abc"] >= 36, \
            "coarse 390 字母格高 %s px（24 基础仍胜出=热区欠地板）" % r["abc"]
        assert page.evaluate(
            "matchMedia('(pointer:coarse)').matches"), "触屏仿真未生效"
    finally:
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
        page.evaluate("cityPanelClose()")
