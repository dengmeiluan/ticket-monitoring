# -*- coding: utf-8 -*-
"""r339h 航司白名单匹配语义透明化（用户点名案：「东方航空是写东航
还是写东方航空？必须细节到这种程度」）：

- 病灶=裸名称片段匹配下「东航」不是「东方航空」的子串（必败），
  而输入框 placeholder 示例「MU,9C,东航」承诺了它=承诺面与匹配面
  劈叉；
- 根治=core.airlines 别称单源：resolve_codes 三写法（码/全称/简称）
  等价归一到码，alerter 白名单与 ! 排除双门同接；表外条目返回空集
  =名称片段兜底零回退；
- 透明面=WebUI 实时解析预览（airPreview，与后端同源字典经
  /api/config airline_alias 下发）+提示词面三写法明示。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339h_airalias.py -q
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.airlines import resolve_codes, alias_payload  # noqa: E402
import main  # noqa: E402


# ---- 1. 别称解析单源 ----

def test_resolve_three_writings():
    assert resolve_codes("东航") == {"MU"}
    assert resolve_codes("东方航空") == {"MU"}
    assert resolve_codes("MU") == {"MU"}
    assert resolve_codes("mu") == {"MU"}          # 码大小写不敏感
    assert resolve_codes("春秋") == {"9C"}
    assert resolve_codes(" 国航 ") == {"CA"}       # 首尾空白容忍


def test_resolve_unknown_is_empty():
    """表外条目=空集（匹配面退回名称片段兜底，别名表只做增量）。"""
    assert resolve_codes("桦航") == frozenset()
    assert resolve_codes("") == frozenset()


def test_payload_shape():
    p = alias_payload()
    assert p["alias"]["东航"] == "MU" and p["alias"]["MU"] == "MU"
    assert p["alias"]["中国东方航空"] == "MU"
    assert p["name"]["MU"] == "中国东方航空"
    # 数据保守律抽验：错别称不得混入（南航≠CZ 以外公司）
    assert p["alias"]["南航"] == "CZ" and p["alias"]["海航"] == "HU"


# ---- 2. 筛选双门集成（白名单 + ! 排除） ----

def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False}
    d.update(kw)
    return d


def _route(airlines):
    return main.build_routes([
        {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1000,
         "airlines": airlines}])[0]


def test_whitelist_short_alias_matches():
    """用户点名案：写「东航」必须等价「东方航空」（MU 行保留）。"""
    from core.alerter import Alerter
    rt = _route("东航")
    assert Alerter._route_filters([_flt()], rt)              # 简称→码
    assert Alerter._route_filters(
        [_flt(airlineCode="MU", airline="中国东方航空")], rt)  # 全称行
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)      # 他司照剔


def test_whitelist_full_name_and_mixed():
    from core.alerter import Alerter
    rt = _route("东方航空,9C")
    assert Alerter._route_filters([_flt()], rt)
    assert Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt)
    rt2 = _route("MU,东航")   # 混写：码+简称
    assert Alerter._route_filters([_flt()], rt2)


def test_ban_short_alias_excludes():
    from core.alerter import Alerter
    rt = _route("!东航")
    assert not Alerter._route_filters([_flt()], rt)           # 排除表同接
    assert Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)      # 他司保留


def test_unknown_entry_falls_back_to_fragment():
    """表外条目零行为回退：名称片段匹配照旧（fail-close 语义不变）。"""
    from core.alerter import Alerter
    rt = _route("东方")     # 非全称非简称→片段兜底
    assert Alerter._route_filters([_flt()], rt)
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)


# ---- 3. PAGE 词面与载荷接线 ----

def _page_src():
    import webui
    return webui.PAGE


def test_page_preview_and_hint():
    src = _page_src()
    assert "function airPreviewHTML(" in src
    assert "function airPreview(" in src
    assert 'id="airpv-${i}-${j}"' in src
    assert "oninput=\"airPreview(${i},${j},this)\"" in src
    # 提示词面：三写法等价承诺明示（用户点名问题的正面回答）
    assert "码 / 全称 / 简称" in src and "三写法等价" in src
    # placeholder 与匹配面一致（旧「MU,9C,东航」写法本就命中——码全等；
    # 新示例覆盖排除语法展示面）
    assert 'placeholder="如 MU,东航,!9C"' in src


def test_airalias_payload_wired_in_demo():
    """demo 载荷带 airline_alias（预览与后端同源的前半链）。"""
    from core.demo import build_demo_db, demo_cfg, demo_health
    import webui
    # 载荷组装函数级验证（不起服务）：_airalias 单源直查
    a = webui._airalias()
    assert a["alias"]["东航"] == "MU" and a["name"]["MU"]


# ---- 4. 行为钉（demo 实例真跑：输入即预览） ----

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _wait_up(proc, base):
    import time
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        if proc.poll() is not None:
            return False
        try:
            op.open(base + "/", timeout=1).read(64)
            return True
        except Exception:
            time.sleep(0.25)
    return False


import pytest  # noqa: E402


@pytest.fixture(scope="module")
def srv():
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    global BASE
    import subprocess
    import tempfile
    port = _free_port()
    BASE = "http://127.0.0.1:%d" % port
    logf = open(os.path.join(tempfile.gettempdir(),
                             "r339h_srv.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
    if not _wait_up(proc, BASE):
        proc.kill()
        pytest.fail("demo 启动失败")
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
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg._errs = errs
        yield pg
        browser.close()


def test_airline_preview_live(page):
    """输入「东航」→ 预览片「东航 → MU 中国东方航空」；不在册条目
    如实标注片段匹配；清空即收。"""
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.evaluate("showCfgPanel('users')")
    page.evaluate("""(()=>{const rl=document.querySelector(
      '#cfgform .rline[data-rk]');
      const h=rl&&rl.querySelector('.rhead');
      if(h&&FOLD.route[rl.dataset.rk]!==false)h.click();
      const ra=rl&&rl.querySelector('.rtheadadv, [onclick*="foldRtadv"]');
      if(ra&&ra.getAttribute('aria-expanded')!=='true')ra.click();})()""")
    page.wait_for_timeout(300)
    inp = page.locator('input[onchange*="airlines"]').first
    inp.fill("东航,!9C,桦航")
    inp.dispatch_event("input")
    page.wait_for_timeout(150)
    pv = page.locator(".airpv").first
    assert pv.is_visible()
    txt = pv.inner_text()
    assert "东航" in txt and "MU" in txt and "中国东方航空" in txt
    assert "排除" in txt and "9C" in txt
    assert "桦航" in txt and "不在册" in txt
    inp.fill("")
    inp.dispatch_event("input")
    page.wait_for_timeout(100)
    assert not pv.is_visible()
    assert not page._errs, page._errs
