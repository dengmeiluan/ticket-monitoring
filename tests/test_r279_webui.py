# -*- coding: utf-8 -*-
"""r279 WebUI 两案（TDD 先行，审计报告 _scratch/r279_webui.md）：

P2-1 配置页 .srow 输入 16px iOS 防放大守卫三处触控块整体层叠败北——
    基础规则 .srow .sctl input:not(.switch) (0,3,1)（:not() 计入参量
    特异性）压过守卫清单 .srow input[type=...] (0,2,1)：390 视口实测
    .srow 全部输入 computed font-size:13px（同块 height:38px 因同形
    高特异声明而生效=同病互证）。iOS Safari/WKWebView 聚焦 <16px
    输入必触发视口自动放大且不回位——配置页用户名/心理价/免打扰
    时刻/日期等全部输入聚焦即爆版。修法：三处触控块（≤900coarse /
    901+coarse / ≤760 任意指针）各补与 height 行同形的高特异声明
    .srow .sctl input:not(.switch){font-size:16px}（同特异性置尾胜，
    三处清单互指既定纪律同批同步）。源码钉锁「三块同形声明在场且
    晚于基础 13px 声明」（count==3，漏改任一块即红）；行为钉锁层叠
    胜负（390 视口 computed 实测 16px——源码钉验不了层叠胜负，
    字面在场≠生效，r249 P1-1 先例同构）。
P3-1 demo_pulse 渠道族硬编码 4 渠道漏 ctrip——概览脉冲图例 4 渠道
    vs 健康卡 5 渠道（demo_health 走 _PLATS 单源），同一演示页两处
    渠道宇宙不一致。修法：chans 键集合与 _PLATS 渠道族一致。
    钉面锁 pulse/health/_PLATS 三方渠道族集合相等（chans 每轮恒
    全体在场，取任一轮即代表全族；漏/多任一渠道即红）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r279_webui.py
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


# ---------- P2-1: .srow iOS 防放大守卫（源码序钉 + computed 行为钉） ----------

def test_srow_ios_zoom_guard_source_pin():
    src = _page_src()
    guard = ".srow .sctl input:not(.switch){font-size:16px}"
    # 实效档：三处触控块（≤900coarse / 901+coarse / ≤760）各一，
    # 与同块 height:38px 行同形高特异（同特异性置尾后者胜）
    n = src.count(guard)
    assert n == 3, (
        ".srow 16px 防放大守须三处触控块同批在场（count=%d，三处清单"
        "互指纪律：漏改任一块=该带 iOS 聚焦仍爆版）" % n)
    # 源码序：守卫声明必须晚于基础规则块（基础 .srow 规则第二行即
    # 13px——同特异性层叠胜负由源码序决定，守卫在前被压制）。
    # 锚用基础规则块头专属子串（首个 font-size:13px 是 .pill 规则，
    # 拿它当锚会把「守卫被挪到基础规则之前」的史病放成假绿）
    base = src.index(".srow .sctl input:not(.switch){height:34px")
    assert "font-size:13px" in src[base:base + 200], (
        "基础 .srow 规则形态漂移：块头 200 字符内无 13px 声明，"
        "源码序锚失效须随形态改写")
    assert src.index(guard) > base, (
        "16px 守卫声明必须置尾于基础 13px 声明之后，否则同特异性"
        "被前者压制（层叠败北复发）")
    # 三处触控块的姊妹高特异行（height:38px）仍各在——守卫与触控
    # 高度同族共生，触控块重构时两者须同步
    assert src.count(".srow .sctl input:not(.switch){height:38px}") == 3


def test_srow_ios_zoom_guard_computed(srv):
    """行为钉：390 视口（命中 ≤760 任意指针块）下 .srow 输入族
    computed font-size 必须 16px。红态=守卫被基础 13px 压制（层叠
    败北），iOS 聚焦即触发视口自动放大。"""
    pw, page = srv
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    # srow 输入在配置页折叠用户卡内——先走真实展开路径（LESSONS
    # 十九§7：折叠详情探针目标必须先真实展开，否则 querySelector null）
    page.evaluate("switchView('cfg')")
    page.wait_for_timeout(600)
    page.evaluate("""()=>{const h=document.querySelector('#cfgform .uhead2');
        if(h&&h.getAttribute('aria-expanded')!=='true')h.click();}""")
    page.wait_for_timeout(400)
    page.evaluate("showCfgPanel('users')")
    page.wait_for_timeout(300)

    def fs(sel):
        return page.evaluate(
            "s=>{const e=document.querySelector(s);"
            "return e?getComputedStyle(e).fontSize:null;}", sel)

    # 审计实测 13px 的三类元素（无 type / number / 日期 dpick）
    for sel in (".srow .sctl input:not([type])",
                ".srow .sctl input[type=number]",
                "input[id^=dpick-]"):
        v = fs(sel)
        assert v is not None, "取样元素缺失：%s" % sel
        assert v == "16px", (
            "%s computed font-size=%s（≤760 带 16px 防放大守被层叠压制，"
            "iOS 聚焦必爆版）" % (sel, v))
    # 对照组：守卫不波及的既有正常件保持 16px（.fbar 输入族）
    assert fs(".fbar input[type=text]") == "16px"


# ---------- P3-1: demo_pulse 渠道族与 _PLATS 单源一致 ----------

def test_demo_pulse_channel_family_matches_health():
    from core.demo import _PLATS, demo_health, demo_pulse
    pulse = demo_pulse()
    pulse_plats = set(pulse["rounds"][0]["chans"].keys())
    health_plats = set(demo_health()["stats"].keys())
    expected = set(_PLATS)
    assert pulse_plats == expected, (
        "demo_pulse 渠道族 %s 与 _PLATS %s 不一致（概览脉冲图例渠道"
        "缺漏=同页两处渠道宇宙分裂）" % (sorted(pulse_plats), sorted(expected)))
    assert health_plats == expected, (
        "demo_health 渠道族 %s 与 _PLATS %s 不一致" % (
            sorted(health_plats), sorted(expected)))


def test_demo_pulse_dur_is_channel_mean():
    """dur 语义=轮墙钟时长均值（core/pulse.py 同形）：分母随渠道族
    单源（曾硬编码 /3——4 渠时代已 4/3 失真，补 ctrip 后 5/3 放大，
    statline「用时 Xs」与脉冲 tooltip 展示偏大 ~1.67 倍）。"""
    from core.demo import demo_pulse
    for r in demo_pulse()["rounds"]:
        lat = [c["lat"] for c in r["chans"].values()]
        expect = round(sum(lat) / len(lat), 1)
        assert abs(r["dur"] - expect) < 0.06, (
            "rounds[%s] dur=%s ≠ 渠道 lat 均值 %s（分母未随 chans 单源）"
            % (r["ts"], r["dur"], expect))


# ---------- srv fixture（自包含，形态同 test_r249_webui.py） ----------

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
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8795" in ln and "LISTENING" in ln:
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
