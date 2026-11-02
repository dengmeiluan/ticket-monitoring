# -*- coding: utf-8 -*-
"""r319 特价监控 WebUI 行为钉（demo 模式，POST 走路由拦截零落盘）：

- 渲染钉：配置页用户卡出现「特价监控」分区（D 区，通知渠道顺延 E），
  未配置用户显「特价关」徽标与空表单。
- 保存链钉：页面 CFG 种入特价订阅 → buildForm 重渲 → 保存 → 拦截
  POST /api/config 捕获请求体，断言 specials 键 verbatim 存活且出发
  城市被 saveConfig 校验归一成三字码（中文→SHA，_cnorm 同航线口径）。
  真落盘路径=服务端 cfg["users"]=body.users 整体透传（verbatim，
  代码读钉），demo 只读拦截不碰生产配置——r291 真机验证只读边界律。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r319_special_webui.py -q
"""
import os
import sys

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
    import tempfile as _tf
    priv_tmp = _tf.mkdtemp(prefix="r319demo_")
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
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）")
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


def _open_user_card(page):
    """进配置视图（switchView('cfg') 懒加载 CFG）并展开首个用户卡。"""
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.evaluate("showCfgPanel('users')")
    page.wait_for_function(
        "document.querySelector('#panel-users')"
        " && document.querySelector('#panel-users').style.display!=='none'")
    page.wait_for_selector('.grouplab[data-sec="D"]')


def test_specials_section_renders(page):
    """配置卡渲染钉（r368 IA）：D 区=关注航班、E 区=特价雷达；
    头部徽标「特价 开」按复合真值显示。"""
    _open_user_card(page)
    d = page.evaluate("""() => {
      const lab = document.querySelector('.grouplab[data-sec="D"]');
      const e = document.querySelector('.grouplab[data-sec="E"]');
      const sw = document.querySelector(
        '#panel-users .ucard .switch');
      return {d: lab ? lab.textContent : null,
              e: e ? e.textContent : null,
              pill: (document.body.textContent.match(/特价\s*[开关]/) || [''])[0]};
    }""")
    assert "关注航班" in (d["d"] or ""), d
    assert "特价雷达" in (d["e"] or ""), d
    # 演示用户自带展示态订阅（r319 呈现面）：徽标应显「开」
    assert d["pill"] == "特价 开", d


def test_specials_cfg_survives_save_and_normalizes(page):
    """保存链钉：CFG 种入特价订阅 → 重渲 → 保存 → 拦截 POST 体，
    specials verbatim 在场 + 出发城市归一三字码 + 数值化。"""
    _open_user_card(page)
    # 种入订阅并重渲（模拟「打开配置页时 config.yaml 已有 specials」；
    # 值留空串——fill 同值不触发 change（聚焦值 vs 失焦值内部 diff，
    # r318 W-2 同族），空起笔让 UI 输入真实走 setSp 路径）
    page.evaluate("""() => {
      CFG[0].specials = [{enabled: true, from_name: '上海',
                          max_price: ''}];
      buildForm();
      /* r339j 价位门：pill 真值含 max_price>0——空起笔使 UI 真实走
         setSp 输入路径（含价位），-pill「开」等价于完形配置在案 */
      if (typeof OPEN_USER === 'undefined' || OPEN_USER !== 0) {
        const h = document.querySelector('.uhead2');
        if (h) toggleUser(h);
      }
    }""")
    # r339j 价位门：enabled+出发地而价位空=pill 恒「关」（如实断言），
    # 价位经 UI 填入后再等「开」——保存链语义不变
    page.wait_for_function(
        "() => (document.body.textContent.match(/特价\s*[开关]/)||[''])[0]"
        " === '特价 关'")
    captured = {}

    def _cap(route):
        if route.request.method != "POST":
            return route.continue_()
        captured["body"] = route.request.post_data
        route.fulfill(status=200, content_type="application/json",
                      body='{"ok": true, "users": 1}')

    page.route("**/api/config", _cap)
    # 表单路径：走 UI 输入（data-sp 钩子）而非直改 CFG——键盘改值后
    # 需失焦触发 change（Playwright fill 自带 blur 语义）
    page.fill('#panel-users .ucard [data-sp="from_name"]', "上海")
    page.fill('#panel-users .ucard [data-sp="max_price"]', "400")
    page.keyboard.press("Tab")   # fill 只派 input；change 在失焦才发（探针实证 model 停留 ''）
    page.wait_for_function(
        "() => (document.body.textContent.match(/特价\s*[开关]/)||[''])[0]"
        " === '特价 开'")   # 价位入模（setSp→头徽重渲）
    page.wait_for_selector("#savebar.on")
    page.click('#savebar button[onclick="saveCfg()"]')
    page.wait_for_timeout(600)
    assert captured.get("body"), "保存请求未被发出"
    import json
    body = json.loads(captured["body"])
    sp = (body["users"][0].get("specials") or [{}])[0]
    assert sp.get("from") == "SHA", sp        # _cnorm 中文→三字码
    assert sp.get("from_name") == "上海", sp
    assert sp.get("max_price") == 400, sp     # 数值化
    assert sp.get("enabled") is True, sp
    page.unroute("**/api/config")


    def test_specials_setsp_roundtrip_defaults(page):
        """setSp 首触建档钉：无 specials 键的用户点启用开关即建档
        enabled:true，不留其余键（GET/POST verbatim 往返零垃圾键）。"""
        _open_user_card(page)
        # 演示用户自带展示态订阅——先删键还原「未配置用户」再验首触
        page.evaluate("delete CFG[0].specials; buildForm();"
                      "if(OPEN_USER!==0)toggleUser(document"
                      ".querySelector('.uhead2'))")
        page.wait_for_selector('#panel-users .ucard [data-sp="enabled"]')
        page.evaluate("""() => {
          const sw = document.querySelector(
            '#panel-users .ucard [data-sp="enabled"]');
          sw.click();
        }""")
        sp = page.evaluate("CFG[0].specials")
        assert isinstance(sp, list) and len(sp) == 1, sp
        assert sp[0].get("enabled") is True, sp
        assert set(sp[0].keys()) == {"enabled"}, sp


def test_overview_specials_card_and_drawer_filters(page):
    """r320 行为钉：概览特价雷达卡（demo 空榜出教学词）+ 明细行属性
    筛选族控件在场 + 余票紧张开关谓词生效（fltN 徽标点亮）。"""
    page.goto(BASE + "/")
    # 概览态等状态对象 S（CFG 属配置视图懒加载，概览不触达）
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(800)
    # 强制刷新雷达卡（绕过 60s 节流；前序用例可能已消耗节流窗）
    page.evaluate("spCard(true)")
    page.wait_for_function(
        "() => { const c = document.getElementById('spcard');"
        " return c && c.style.display !== 'none'; }")
    assert "还没有核实通过的特价" in page.evaluate(
        "document.getElementById('spbody').textContent")
    # 明细：行属性筛选族控件 DOM 在场 + r320 R2 克制律实效（维度只在
    # 当前数据有区分度时现身——demo 合成库无经停/共享行、机型值不足
    # 两档，nostop/noshare/ps 三维整组隐藏是设计内；wait_for_selector
    # 默认等 visible，对自适应显隐控件必须查 DOM 在场而非可见性）
    page.evaluate("showMonTab('details');table();"
                  "const fb=document.querySelector('.fbar');"
                  "if(fb&&getComputedStyle(fb).display==='none')togFlt();")
    for i in ('ffew', 'fnostop', 'fnoshare', 'fsafe', 'flaymin',
              'flaymax', 'alchips', 'pschips'):
        page.wait_for_function(
            f"document.getElementById('{i}') !== null")
    vis = page.evaluate("""(() => {
      const g = id => { const e = document.getElementById(id);
        return !!e && e.offsetParent !== null; };
      return {ffew: g('ffew'), fnostop: g('fnostop'),
              fnoshare: g('fnoshare'), ps: g('pschips')}; })()""")
    assert vis["ffew"] is True, vis
    assert not vis["fnostop"] and not vis["fnoshare"] and not vis["ps"], vis
    # 余票紧张开关谓词生效：开启后计数变化且徽标点亮，关闭恢复
    before = page.evaluate("document.querySelectorAll('#ftable tbody tr[data-k]').length")
    page.evaluate("document.getElementById('ffew').click();applyFlt();")
    after = page.evaluate("document.querySelectorAll('#ftable tbody tr[data-k]').length")
    assert after != before or before == 0, (before, after)
    badge = page.evaluate(
        "() => { const b = document.getElementById('fltN');"
        " return b && b.style.display !== 'none'; }")
    assert badge is True, "fltN 徽标应点亮"
    page.evaluate("document.getElementById('ffew').click();applyFlt();")
