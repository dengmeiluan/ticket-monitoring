# -*- coding: utf-8 -*-
"""r1452：去哪儿网页版 PC/H5 已停服，渠道入口不得再画成可点入口。

背景（用户 2026-11-11 实报）：Release 里的能力矩阵截图还是旧图（H5 打勾），
检索「渠道入口」仍给去哪儿摆四颗 PC/H5 国内/国际按钮、状态写「已有登录态，
待采集验证」。实际 PC（2026-10-10）与 H5（2026-11）机票查询均已停服，
数据只走 app_qunar。

本用例守三件事：
1. 数据层：去哪儿 20 个网页格子与特价格都带 `retired=True`，其余渠道不带；
2. 检索渠道入口：去哪儿行只有一句「网页版已停服 · 数据走 App」，零个 <a>；
3. 配置渠道板：去哪儿行不渲染四颗死链接，只留停服说明；矩阵 PC/H5 两格为「停」。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_qunar_web_cells_are_marked_retired():
    from core.channel_links import channel_links
    r = channel_links()
    qunar_cells = [c for c in r["cells"] if c["plat"] == "qunar"]
    assert len(qunar_cells) == 4, qunar_cells
    for c in qunar_cells:
        assert c["retired"] is True, c
        # 入口地址保留作历史参考（ok 仍表示 URL 存在），但前端必须按
        # retired 渲染，不能只看 url 就发链接。
        assert c["url"], c
    for c in r["cells"]:
        if c["plat"] != "qunar":
            assert c["retired"] is False, c
    for c in r["specials"]:
        assert c["retired"] is (c["plat"] == "qunar"), c


def _boot():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            return srv, base
        except Exception:
            time.sleep(0.3)
    srv.kill()
    raise RuntimeError("demo server did not start")


def test_rendered_entries_show_retired_not_dead_links():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1512, "height": 1000})
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                # 1) 检索渠道入口（异步 /api/channel-links）：等行真的出现
                pg.evaluate("()=>switchView('search')")
                pg.wait_for_timeout(900)
                pg.evaluate("()=>srxChLinksOpen()")
                pg.wait_for_function(
                    "()=>document.querySelectorAll('#srxChLinksBox .clx-row')"
                    ".length>=10", timeout=20000)
                row = pg.evaluate("""()=>{
                  const r=document.querySelector(
                    '#srxChLinksBox .clx-row[data-channel=qunar]');
                  if(!r)return null;
                  return {text:r.innerText||'', links:r.querySelectorAll('a').length,
                          retired:!!r.querySelector('.clx-retired')};
                }""")
                assert row, "渠道入口没有渲染去哪儿行"
                assert row["retired"], row
                assert "停服" in row["text"], row
                assert row["links"] == 0, row
                # 探针渠道 rail：去哪儿网页不可再勾选（否则探测必空转）
                chip = pg.evaluate("""()=>{
                  const q=document.querySelector(
                    '#srxPlatPick .srx-pchip[data-p=qunar] input');
                  return q?{checked:q.checked,disabled:q.disabled,
                           title:q.closest('label').title}:null;
                }""")
                assert chip and chip["disabled"] and not chip["checked"], chip
                assert "停服" in chip["title"], chip
                # 2) 配置渠道板：同一事实，不能换成四颗「不供」或死链接
                pg.evaluate("()=>switchView('cfg')")
                pg.wait_for_timeout(1000)
                pg.evaluate("()=>{const b=document.querySelector("
                            "'#cfgnav .cnav[data-p=\"login\"]');if(b)b.click()}")
                pg.wait_for_timeout(1200)
                try:
                    pg.wait_for_function(
                        "()=>document.querySelector("
                        "'#cfgChannelLinksBox .chband[data-channel=qunar]')",
                        timeout=8000)
                except Exception:
                    pg.evaluate("()=>{try{if(typeof srxChLinksLoad==='function')"
                                "srxChLinksLoad('cfg')}catch(e){}}")
                    pg.wait_for_function(
                        "()=>document.querySelector("
                        "'#cfgChannelLinksBox .chband[data-channel=qunar]')",
                        timeout=20000)
                band = pg.evaluate("""()=>{
                  const r=document.querySelector(
                    '#cfgChannelLinksBox .chband[data-channel=qunar]');
                  return {text:r.innerText||'',
                          chips:r.querySelectorAll('.chlink').length};
                }""")
                assert "停服" in band["text"], band
                assert band["chips"] == 0, band
                # 登录卡同一事实：不能一边写「已保存·待验证」一边写停服
                card = pg.evaluate("""()=>{
                  const c=document.querySelector(
                    '#loginRows .lgcard[data-channel=qunar]');
                  if(!c)return null;
                  return {text:c.innerText||'',
                          buttons:[...c.querySelectorAll('button')]
                            .map(b=>(b.textContent||'').trim())};
                }""")
                assert card and "停服" in card["text"], card
                assert "已保存" not in card["text"], card
                assert card["buttons"] == ["打开 App 登录"], card
                # 3) 矩阵端面：PC/H5 两行、去哪儿列都必须是「停」
                rows = pg.evaluate("""()=>{
                  const out={};
                  [...document.querySelectorAll('#cfgDimMatrix tbody tr')]
                    .forEach(tr=>{
                      const k=((tr.querySelector('th')||{}).innerText||'')
                        .split('\\n')[0].trim();
                      const tds=[...tr.querySelectorAll('td')];
                      out[k]=tds[1]?tds[1].innerText.trim():'';
                    });
                  return out;
                }""")
                assert rows.get("PC 端") == "停", rows
                assert rows.get("H5 端") == "停", rows
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


def test_setup_check_reports_host_platform_and_app_boundary():
    """自检第一步就说清平台边界：网页三平台可用；App 仅 Windows+MuMu。"""
    from core import setup_check as sc
    row = sc.check_platform()
    assert row["name"] == "运行平台", row
    assert "App 渠道" in row["detail"], row
    rows = sc.run_checks()
    assert rows[0]["name"] == "运行平台", rows[0]


def test_readmes_have_per_os_quickstart_and_consistent_python_floor():
    """README 中英都要有分系统步骤，且 Python 下限与 setup_check 同为 3.11。

    2026-11-11 用户实报：不同系统的引导脚本执行不清；此前 README 徽章
    写 3.10+，setup 脚本/CI/Docker 实际要求 3.11。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("README.md", "README_EN.md"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert "Windows" in text and "macOS" in text and "Linux" in text, name
        assert "Python 3.11+" in text, name
        assert "Python 3.10" not in text and "3.10%2B" not in text, name
        # 发行包体积必须跟当前 Release 资产同量级（旧文案 60–94MB 已过期）
        assert "127–250" in text, name
        assert "60–94" not in text, name
        # App 渠道平台边界必须写明，避免 macOS/Linux 用户白装模拟器
        assert "Windows + MuMu" in text, name
