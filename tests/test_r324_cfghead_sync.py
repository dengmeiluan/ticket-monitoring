# -*- coding: utf-8 -*-
"""r324 配置面卡头随行刷新钉（穷举审计 C1-C8，用户令：不许再有
渲染交互数据不一致）：

- C1 改用户名：uhead2 名/uava/「删除用户」按钮停旧值
- C2 关 Windows 弹窗：🔔 pill + A 头不随行
- C3 启/停钉钉：推送 pill + A 头 + E 头不动（chSync 只亮通道卡灯）
- C4 togPlat：B 头「N / 5 渠道」不随行
- C5 启/停特价：🎯 pill + D 头不随行（真值=enabled+城市复合）
- C6 ntfy 启停：E 头渠道清单不动
- C7 quickDep：rhead muted 出发窗摘要不随行（写点绕过 setRoute）
- C8 邮件通道填 user：卡头标题身份不随行

统一修复：syncUserHead(i) 单源外科重算（禁 buildForm 全量重建，
十一§3 销毁性 blur 家族）+ C7 接 syncRouteHead + C8 扩 chSync。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_cfghead_sync.py -q
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
    priv_tmp = _tf.mkdtemp(prefix="r324ch_")
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


def _to_cfg(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.wait_for_timeout(400)


def _restore(page, snapshot):
    """模型快照还原 + buildForm 全量重建（测试收尾态复位）。"""
    page.evaluate("""((snap) => {
      CFG.length = 0;
      for (const u of snap.users) CFG.push(JSON.parse(JSON.stringify(u)));
      GLB = JSON.parse(JSON.stringify(snap.glb));
      buildForm();
    })""", snapshot)


_SNAP = """
(() => ({glb: JSON.parse(JSON.stringify(GLB)),
        users: JSON.parse(JSON.stringify(CFG))}))()
"""


def _pill(head, idx):
    return f"""(() => {{
      const p = document.querySelectorAll(
        '#cfgform .ucard')[0].querySelectorAll('.uhead2 .upill')[{idx}];
      return {{t: p.textContent.trim(), ok: p.classList.contains('ok')}};
    }})()"""


def test_c1_rename_updates_head(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          const inp = document.querySelector(
            '#cfgform input[onchange*="CFG[0].name"]');
          inp.value = '审计改名AB';
          inp.dispatchEvent(new Event('change', {bubbles: true}));
          const head = document.querySelector('#cfgform .ucard .uhead2');
          const del = document.querySelector(
            '#cfgform button[onclick^="delUser"]');
          return {model: CFG[0].name,
                  headName: head.querySelector('b').textContent,
                  uava: head.querySelector('.uava').textContent,
                  delBtn: (del.getAttribute('aria-label')||'').trim()};
        })()""")
        assert out["model"] == "审计改名AB", out
        assert out["headName"] == "审计改名AB", out
        assert out["uava"] == "审", out
        assert "审计改名AB" in out["delBtn"], out
    finally:
        _restore(page, snap)


def test_c2_win_toast_pill_follows(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          const sw = document.querySelector(
            '#cfgform input[onchange*="setN(0,\\'win_toast\\'"]');
          sw.click();
          const aHead = document.querySelector(
            '#cfgform .grouplab[data-sec="A"] .gsum').textContent;
          return {model: CFG[0].notifier.win_toast,
                  pill: document.querySelectorAll(
                    '#cfgform .ucard .uhead2 .upill')[2].textContent.trim(),
                  aHead};
        })()""")
        assert out["model"] is False, out
        assert out["pill"] == "弹窗 关", out
        assert "弹窗关" in out["aHead"], out
    finally:
        _restore(page, snap)


def test_c3_dingtalk_toggle_updates_heads(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          const sw = document.querySelector(
            '#cfgform input[onchange*="setDt(0,\\'enabled\\'"]');
          sw.click();
          const g = (no) => document.querySelector(
            '#cfgform .grouplab[data-sec="' + no + '"] .gsum').textContent;
          return {model: CFG[0].notifier.dingtalk.enabled,
                  pill: document.querySelectorAll(
                    '#cfgform .ucard .uhead2 .upill')[3].textContent.trim(),
                  aHead: g('A'), eHead: g('F')};
        })()""")
        assert out["model"] is True, out
        # r345：开关开但 Webhook 空 → 待完善（后端会跳过，不能假绿）
        assert out["pill"] == "推送待完善", out
        assert "钉钉待完善" in out["aHead"], out
        assert "钉钉待完善" in out["eHead"], out
    finally:
        _restore(page, snap)


def test_c4_plat_toggle_updates_bhead(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          const before = CFG[0].platforms.length;
          const chip = document.querySelector('#cfgform .pch.on');
          chip.click();
          const bHead = document.querySelector(
            '#cfgform .grouplab[data-sec="B"] .gsum').textContent;
          return {before, after: CFG[0].platforms.length, bHead};
        })()""")
        assert out["after"] == out["before"] - 1, out
        assert out["bHead"] == str(out["after"]) + " / 5 渠道", out
    finally:
        _restore(page, snap)


def test_c5_specials_pill_composite_truth(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          CFG[0].specials = [{enabled: true, from_name: '上海',
                              max_price: 400}];
          buildForm();   // r339j 价位门：_spOn 复合真值含 max_price>0——钉数据同步完形
          const pillAt = () => {{
            const p = document.querySelectorAll(
              '#cfgform .ucard .uhead2 .upill')[1];
            return {t: p.textContent.trim(), ok: p.classList.contains('ok')};
          }};
          const dHead = () => document.querySelector(
            '#cfgform .grouplab[data-sec="D"] .gsum').textContent;
          const on = pillAt();
          const dOn = dHead();
          const sw = document.querySelector(
            '#cfgform input[onchange*="setSp(0,\\'enabled\\'"]');
          sw.click();
          return {on, dOn,
                  model: CFG[0].specials[0].enabled,
                  off: pillAt(), dOff: dHead()};
        })()""")
        assert out["on"]["t"] == "特价 开" and out["on"]["ok"], out
        assert out["dOn"] == "按用户独立", out
        assert out["model"] is False, out
        assert out["off"]["t"] == "特价 关" and not out["off"]["ok"], out
        assert out["dOff"] == "按用户独立", out
        # r339j 价位门反例：enabled+出发地齐但价位 0=未完形→恒「关」
        out2 = page.evaluate("""(() => {
          CFG[0].specials = [{enabled: true, from_name: '上海',
                              max_price: 0}];
          buildForm();
          const p = document.querySelectorAll(
            '#cfgform .ucard .uhead2 .upill')[1];
          return {t: p.textContent.trim(),
                  ok: p.classList.contains('ok')};})()""")
        assert out2["t"] == "特价 关" and not out2["ok"], out2
    finally:
        _restore(page, snap)


def test_c6_ntfy_topic_updates_ehead(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          const inp = document.querySelector(
            '#cfgform input[onchange*="setNtfy(0,\\'topic\\'"]');
          inp.value = 'audit-topic-x';
          inp.dispatchEvent(new Event('change', {bubbles: true}));
          return {model: CFG[0].notifier.ntfy,
                  eHead: document.querySelector(
                    '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
        })()""")
        assert out["eHead"] and "ntfy✓" in out["eHead"], out
    finally:
        _restore(page, snap)


def test_c7_quickdep_updates_rhead_muted(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          const rl = document.querySelector('.rline[data-rk="0:0"]');
          const chip = [...rl.querySelectorAll('.schip')]
            .find(c => (c.getAttribute('title') || '') === '00:00–06:00');
          chip.click();
          const muted = document.querySelector(
            '.rline[data-rk="0:0"] .rhead .muted').textContent;
          const withWin = muted;
          const off = [...rl.querySelectorAll('.schip')]
            .find(c => c.textContent.trim() === '不限');
          off.click();
          const muted2 = document.querySelector(
            '.rline[data-rk="0:0"] .rhead .muted').textContent;
          return {withWin, afterOff: muted2,
                  modelWin: [CFG[0].routes[0].dep_time_min,
                             CFG[0].routes[0].dep_time_max]};
        })()""")
        assert "00:00–06:00 出发" in out["withWin"], out
        assert "出发" not in out["afterOff"], out
        assert out["modelWin"] == ["", ""], out
    finally:
        _restore(page, snap)


def test_c8_email_user_updates_card_title(page):
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          CFG[0].notifier.emails = [{host: 'smtp.163.com', port: 465}];
          buildForm();
          const inp = document.querySelector(
            '#cfgform input[onchange*="setEm(0,0,\\'user\\'"]');
          inp.value = 'audit@163.com';
          inp.dispatchEvent(new Event('change', {bubbles: true}));
          const head = document.querySelector(
            '#cfgform .chcard[data-ch="email0"] .chhead');
          return {model: CFG[0].notifier.emails[0].user,
                  title: head.childNodes[1].textContent};
        })()""")
        assert out["model"] == "audit@163.com", out
        assert out["title"] == "邮件·audit@163.com", out
    finally:
        _restore(page, snap)


def test_c9_city_panel_pick_writes_model(page):
    """C9（用户实报第二击的真凶）：城市面板点选必须把选择写进模型——
    cityPanelPick 曾在 cityPanelClose()（置 _cpEl=null）之后才派发
    change，null.dispatchEvent TypeError 被吞，选城从未入模（输入框
    值是面板写的故历代无人察觉；卡头随行修复上线后才显形）。
    钉=cityPanelOpen→cityPanelPick 全真链，模型+码+卡头三面随行。"""
    _to_cfg(page)
    snap = page.evaluate(_SNAP)
    try:
        out = page.evaluate("""(() => {
          addRoute(0);
          const J = CFG[0].routes.length - 1;
          const fin = document.querySelector(
            '.rline[data-rk="0:' + J + '"] input[onchange*="from_name"]');
          cityPanelOpen(fin);
          cityPanelPick('北京');
          const rl = document.querySelector('.rline[data-rk="0:' + J + '"]');
          const head = rl.querySelector('.rhead');
          const r = CFG[0].routes[J];
          return { modelFrom: r.from, fromName: r.from_name,
                   headName: head.querySelector('b').textContent,
                   headCode: head.querySelector('.rtcode').textContent };
        })()""")
        assert out["modelFrom"] == "BJS" and out["fromName"] == "北京", out
        assert out["headName"] == "北京 → 海口", out
        assert out["headCode"] == "BJS→HAK", out
    finally:
        _restore(page, snap)


def test_source_pins_userhead_sync():
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "function syncUserHead" in src, "卡头刷新单源应在案"
    assert src.count("syncUserHead(i)") >= 9, (
        "九写点（W1-W3/W4-W7/W11/W15）应接线")
    assert "syncRouteHead(i,j)" in src, "航线头单源应在案"
    qi = src.find("function quickDep")
    assert qi >= 0 and "syncRouteHead(i,j)" in src[qi:qi + 400], (
        "quickDep 应接航线头随行")
