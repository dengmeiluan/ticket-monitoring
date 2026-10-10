# -*- coding: utf-8 -*-
"""r281 WebUI P2-1（TDD 先行，审计报告 _scratch/r281_web_report.md）：

配置搜索孤儿容器壳——r280 P2-1 孤儿头修复只收口结构头本体，头的
宿主容器链（面板卡壳 #sec-login/#sec-users/#sec-globals-card、
用户卡 #cfgform>.ucard、用户卡 body 包裹层 .ucard>div）在命中集中
于单面板时子件全隐、padding 独存成 26-110px 空白残影条（截图实锤
_scratch/r281_web_shot_cfgsearch_orphan_1440.png），被误读为渲染
残缺。修法：孤儿头扫之后补容器收尾扫——容器内存在可见内容行
（ROWS 口径，头类含内——头级 inline 已由孤儿头扫写对）才在位，
无内容行结构的卡（空态引导）不参与防误杀；cfgSearchClear 清单
对称复位。源码钉锁「收尾扫在孤儿头扫之后 + 复位清单含容器族」，
行为钉锁搜索态三容器壳 computed none + 命中面板卡壳不动 + 清空
对称还原。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r281_webui.py
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


SWEEP = ("#cfgview .cfpanel>.ucard,#cfgview #cfgform>.ucard,"
         "#cfgview #cfgform>.ucard>div")


# ---------- 源码钉 ----------

def test_cfgsearch_orphan_container_source_pin():
    src = _page_src()
    # 收尾扫与复位清单各一份（漏复位清单=清空后容器壳滞留 display:none）
    n = src.count(SWEEP)
    assert n == 2, (
        "容器族选择器须两处在场（cfgFilter 收尾扫 + cfgSearchClear 复位"
        "清单），count=%d" % n)
    # 收尾扫必须在孤儿头扫写入点之后（容器可见性判定消费头级 inline
    # 结果，顺序颠倒=按上一轮头状态判容器，假隐/假显）
    anchor = src.index("g.style.display=keep?'':'none';});")
    sweep_in_filter = src.find(SWEEP, anchor)
    assert sweep_in_filter > 0, (
        "cfgFilter 内缺容器收尾扫（孤儿头扫之后无容器族选择器）")
    # 复位清单（第一处）在收尾扫之前属正常（cfgSearchClear 定义在前）；
    # 额外验证收尾扫带「无内容行不参与」守卫（rows.length 空卡防误杀）
    body = src[sweep_in_filter:sweep_in_filter + 700]
    assert "rows.length" in body, (
        "容器收尾扫缺无内容行守卫（空态引导卡等无 ROWS 结构的卡"
        "会被误隐）")
    # Soldier Minor-1：renderHealth 空态分支必须清推送连败源
    # （账本空窗后 _ovPushStreak 残留=红帽常亮而指引落空）
    hs = src.index("function renderHealth(j){")
    empty_ret = src.index("暂无扫描记录", hs)
    seg = src[empty_ret:empty_ret + 400]
    assert "renderPushChannels({channels:{}})" in seg, (
        "renderHealth 空态分支缺推送源清零（红帽 stale 残留）")
    # Soldier Minor-2：cfgSearchClear 必须按 aria-expanded 重写手风琴
    ci = src.index("function cfgSearchClear()")
    cseg = src[ci:ci + 1400]
    assert "aria-expanded" in cseg, (
        "cfgSearchClear 缺手风琴态重写（容器族复位强制展开折叠卡，"
        "aria/视觉状态分裂）")


# ---------- 行为钉 ----------

def test_overview_alert_covers_push_streak(srv):
    """R281-1 呈现面（推送审校 _scratch/r281_push_report.md §③）：
    概览红帽只挂采集失败——钉钉 -1 幽灵期采集面全绿、推送通道连败
    34 轮 10h 期间控制台零主动暴露（本轮生产实录，￥1749 达标价静默
    丢失）。修法=概览红帽双源合成：采集失败（pulse 轮）与推送连败
    （health 轮）各写各的缓存，任一非零即亮——两轮询独立刷新互不
    覆盖，推送源点亮后 pulse 轮写采集零不得熄灭。不动发送/落账。"""
    pw, page = srv
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(300)
    # 冻结轮询渲染源（LESSONS 二十七§6：墨迹类断言先冻结刷新源），
    # 防周期轮询用真实 demo 数据覆盖注入态
    page.evaluate("renderHealth=function(){};renderPulse=function(){}")
    disp = lambda: page.evaluate(
        "document.querySelector('#ovAlert').style.display")
    # 基线：采集零失败 + 推送零连败 = 灭
    page.evaluate("renderPulseAlert(0)")
    page.evaluate("renderPushChannels({channels:{}})")
    assert disp() == "none", "双源清零后红帽应灭"
    # 推送连败 34 → 亮（不经 renderPulseAlert——health 轮独立点亮）
    page.evaluate(
        "renderPushChannels({channels:{dingtalk:{ok:0,fail:34,"
        "fail_streak:34,last:'2026-10-11 01:00:00',last_ok:''}}})")
    assert disp() == "", "推送连败未点亮概览红帽（连败可感知缺口未收口）"
    # 关键行为：pulse 轮写采集源 0 不得熄灭推送源（双源不互相覆盖）
    page.evaluate("renderPulseAlert(0)")
    assert disp() == "", "pulse 轮覆盖了推送连败源（红帽闪烁互搏回归）"
    # 推送源清零 + 采集零失败 = 灭
    page.evaluate("renderPushChannels({channels:{}})")
    page.evaluate("renderPulseAlert(0)")
    assert disp() == "none", "双源清零后红帽应灭"
    # 采集失败仍独立点亮（原语义零回归）
    page.evaluate("renderPulseAlert(2)")
    assert disp() == "", "采集失败点亮面回归"
    # 推送连败清零后采集失败保持点亮
    page.evaluate(
        "renderPushChannels({channels:{dingtalk:{ok:9,fail:0,"
        "fail_streak:0,last:'',last_ok:''}}})")
    assert disp() == "", "推送恢复后采集失败源被误熄"


def test_cfgsearch_orphan_containers_hidden(srv):
    pw, page = srv
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(300)
    page.evaluate("switchView('cfg')")
    page.wait_for_timeout(800)
    # 真实键入路径（oninput→防抖 250ms）
    page.fill("#cfgSearch", "扫描周期")
    page.wait_for_timeout(700)

    def disp(sel):
        return page.evaluate(
            "s=>{const e=document.querySelector(s);"
            "return e?getComputedStyle(e).display:null;}", sel)

    # 命中面板（全局参数）真有可见命中行——防「全隐」假阳性
    vis_hit = page.evaluate(
        """()=>Array.from(document.querySelectorAll(
               '#cfgglobals .glgrid>div'))
            .some(d=>getComputedStyle(d).display!=='none')""")
    assert vis_hit, "命中面板无可见命中行（搜索词与 demo 数据失配，钉失效）"
    # 三容器壳收口：登录卡壳/用户卡/用户卡 body 包裹层全隐
    assert disp("#sec-login") == "none", (
        "#sec-login 卡壳残影（孤儿头已隐但宿主容器 padding 独存）")
    assert disp("#cfgform > .ucard") == "none", (
        "用户卡容器残影")
    assert disp("#cfgform > .ucard > div:not(.uhead2)") == "none", (
        "用户卡 body 包裹层残影（纯 padding 撑高）")
    # 命中面板卡壳不受扰
    assert disp("#sec-globals-card") != "none", (
        "命中面板卡壳被误隐（收尾扫射程越界）")
    # 清空对称复位
    page.evaluate("cfgSearchClear()")
    page.wait_for_timeout(200)
    assert disp("#sec-login") != "none", "清空后 #sec-login 未复位"
    assert disp("#cfgform > .ucard") != "none", "清空后用户卡未复位"
    assert disp("#cfgform > .ucard > div:not(.uhead2)") != "none", (
        "清空后 body 包裹层未复位（展开态应回 padding 在场形态）")


def test_cfgsearch_clear_keeps_accordion_folded(srv):
    """Soldier Minor-2：cfgSearchClear 容器族复位把折叠用户卡的 body
    包裹层一并 display=''——清空后手风琴被强制展开且 aria-expanded
    仍 false（头说收起内容却显示，状态分裂）。修法=清空路径按
    aria-expanded 单源重写手风琴：收起态清空后保持收起。"""
    pw, page = srv
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(300)
    page.evaluate("switchView('cfg')")
    page.wait_for_timeout(800)
    # 把首卡收起（走真实 toggleUser 路径，aria-expanded 同步翻转）
    page.evaluate(
        """()=>{const h=document.querySelector('#cfgform .uhead2');
            if(h.getAttribute('aria-expanded')==='true')h.click();}""")
    page.wait_for_timeout(200)
    body_disp = lambda: page.evaluate(
        "()=>{const h=document.querySelector('#cfgform .uhead2');"
        "return h.nextElementSibling.style.display;}")
    assert body_disp() == "none", "前置：首卡应已收起"
    # 搜索→清空：收起态必须保持（旧行为=容器族复位强制展开）
    page.fill("#cfgSearch", "扫描周期")
    page.wait_for_timeout(700)
    page.evaluate("cfgSearchClear()")
    page.wait_for_timeout(300)
    aria = page.evaluate(
        "()=>document.querySelector('#cfgform .uhead2')"
        ".getAttribute('aria-expanded')")
    assert aria == "false", "清空后 aria-expanded 应保持 false（手风琴态）"
    assert body_disp() == "none", (
        "清空后收起卡被容器族复位强制展开（aria/视觉状态分裂，"
        "Soldier Minor-2）")


# ---------- srv fixture（自包含，形态同 test_r279_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _srv_log_tail(logf):
    try:
        logf.seek(0)
        return "".join(logf.readlines()[-20:])
    except Exception:
        return "<log 不可读>"


@pytest.fixture(scope="module")
def srv():
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
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
