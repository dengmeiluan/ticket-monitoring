# -*- coding: utf-8 -*-
"""r260 WebUI 精细化（TDD 先行，r260_audit_webui P2-1 + P3-1~4）：

U1 状态 pill 状态符单源（P2-1）：pillState 词面去状态 emoji
（⚪/🚨/❌）——::before 7px 状态点与词面内嵌 emoji 双状态符并置，
达标态绿点与红 🚨 同框语义打架、失败态双圆点并排；状态语言单源
交给 ::before 色档（.pill.ok 绿脉冲/常态 --mut 灰点），文案保留
纯词面。document.title 的 🚨 保留（标签页无 ::before 载体，
title 是该面唯一状态符）。
U2 健康卡时间窗词面统一「近 24h」（P3-2）：同卡「近 24 小时」
vs「近 24h」双词面，390 档两处窗口说明同屏重复。
U3 日期分隔符统一 MM/DD（P3-3a）：改期胶囊 .tg「11-04」与同格簇
mdat「11/02」双分隔符；二段起飞日期 transGoDate.slice(5) 同族
漏点（全站惯例 d.slice(5).replace('-','/')）。
U4 时长词面归一（P3-3b）：dur 列直显渠道原词（totalDuration 值域
实测 94.8% 中文 + 5.2%「25h40m」英文形态在场，多渠道同屏混排），
durTxt 单源展示端归一（后端排序键 _dur_min 不动）。
U5 失败态词面去重（P3-4）：state 失败时 pill 与 updated 槽同屏
双「服务未启动」——updated 槽改空（_markStale 家族已在五处骨架
落「服务未启动，恢复后自动刷新」，增量信息由骨架承载）。
U6 预览弹层焦点归还正面钉（P3-1）：审计探针 Esc 后 ae=BODY 疑为
programmatic click 伪影（真实 click 焦点在按钮；归还链
_openPvMask 记录 → closePv focus 归还完整在位）——源码钉锁归还
链防退化，真实路径复测归真机环节。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r260_webui.py
"""
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("t260w")


def _page_src():
    import webui
    return webui.PAGE


# ---------- U1: 状态 pill 状态符单源 ----------

def test_pill_state_calls_have_no_status_emoji():
    """pillState 全部调用实参零状态 emoji：词面侧退役、::before
    色档单源（达标 .pill.ok 绿脉冲 / 常态 --mut 灰点）。"""
    import re as _re
    src = _page_src()
    calls = _re.findall(r"pillState\(([^;]*?)\);", src)
    assert len(calls) >= 6, "pillState 调用面清零=API 漂移"
    for c in calls:
        for e in ("⚪", "🚨", "❌", "✅", "⚠"):
            assert e not in c, f"pill 词面内嵌状态 emoji {e!r}: {c.strip()[:60]}"


def test_pill_dot_carrier_intact():
    """状态点载体在位：.pill::before 圆点 + .pill.ok 绿脉冲（状态
    语言唯一出口），词面退役后不出现「无点无 emoji」的裸文案态。"""
    src = _page_src()
    assert ".pill::before{content:'';width:7px;height:7px;" in src
    assert ".pill.ok::before{background:var(--green);" in src


# ---------- U2: 健康卡时间窗词面统一 ----------

def test_health_window_wording_single_form():
    src = _page_src()
    assert "近 24 小时" not in src, "同卡「近 24 小时/近 24h」双词面"
    # 同族全收口：空态说明行（健康卡 ×2）与走势空态（48h）同律，
    # 钉面锁全族清零——只锁「近 」前缀形态会漏空态行
    assert "24 小时" not in src and "48 小时" not in src, (
        "「N 小时」词面残留（与控件/chip 的「48h」族双轨）")
    assert src.count("近 24h") >= 3, "seclab/计数行/推送通道段三处统一"


# ---------- U3: 日期分隔符统一 MM/DD ----------

def test_tg_pill_and_transfer_date_slash_form():
    src = _page_src()
    # 日期斜杠轨已收口 dSlash 单源（r261）：钉面随形态改写，
    # 语义担保保留——消费点必须走单源而非内联换装
    assert "function dSlash(" in src, "dSlash 日期短标单源缺失"
    # 改期胶囊：lo[0]（MM-DD）与全站惯例同形
    assert "${he(dSlash(lo[0]))}" in src, (
        ".tg 胶囊日期未走 dSlash 单源（MM-DD 形态与同格簇 mdat MM/DD 双分隔符）")
    # 二段起飞日期同族漏点：transGoDate 直出 MM-DD
    assert "dSlash(f.transGoDate)" in src, (
        "二段起飞日期未走 dSlash 单源（同族漏点）")


# ---------- U4: 时长词面归一 ----------

def test_dur_txt_defined_and_wired():
    src = _page_src()
    assert "function durTxt(" in src, "durTxt 单源缺失"
    assert "${durTxt(f.dur)||'—'}" in src, "dur 列未走 durTxt 归一"


def test_dur_txt_computed(srv):
    """行为钉：英文 h/m 形态归一中文、中文原样透传、空串归空
    （消费端 '—' 兜底不变）。"""
    pw, page = srv
    got = page.evaluate(
        "() => [durTxt('25h40m'), durTxt('5时19分'), durTxt(''),"
        " durTxt('10h5m'), durTxt('125分')]")
    assert got == ["25时40分", "5时19分", "", "10时5分", "125分"]


# ---------- U5: 失败态词面去重 ----------

def test_failure_state_no_dup_wording():
    src = _page_src()
    assert "（服务未启动）" not in src, (
        "updated 槽与 pill 同屏双「服务未启动」")
    assert "$('updated').textContent='';_markStale();" in src, (
        "冷启动失败分支 updated 槽应改空（增量信息由 _markStale 骨架承载）")


# ---------- U6: 预览弹层焦点归还正面钉 ----------

def test_pv_focus_return_chain():
    src = _page_src()
    assert "_PV_RETURN=document.activeElement" in src, "开层记录缺失"
    assert "const ret=_PV_RETURN;_PV_RETURN=null;" in src, "关层取件缺失"
    assert "ret.focus()" in src, "归还调用缺失"


# ---------- playwright srv fixture（demo 实例，行为钉共用；r251 形态） ----------

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
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    base = None
    from playwright.sync_api import sync_playwright as _sp
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
    with _sp() as p:
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
