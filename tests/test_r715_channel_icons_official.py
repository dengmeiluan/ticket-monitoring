# -*- coding: utf-8 -*-
"""r715 每家渠道（含两家 App）都必须有官方图标，且不能退化成字符牌。

用户原话：「要保持使用官方渠道图标作为精致质感的标准」。判据取**渲染结果**
而不是源码字符串：
1. `SRX_BRAND_IMG` 里每个 `SRX_PLATS` 渠道都有 base64 图标；
2. 真浏览器里，配置页 7 个 chip、登录区 7 行、健康卡渠道行都渲染出
   `<img class="bic">`、`naturalWidth>0`、且**没有** `.bic-fb` 回退牌；
3. 图标尺寸同族一致（配置页 16×16，登录区 24px 宽）。

不量隐藏面板：不可见元素 `getBoundingClientRect()` 恒 0，
会让「宽高>0」这类判据恒假（也会让 `w==0` 恒真）——必须先切到可见面板。
"""
import os
import re
import sys

import pytest

pytest.importorskip("playwright",
                    reason="图标判据依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _src():
    return open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_every_plat_has_official_icon_in_registry():
    """注册表层面：SRX_PLATS 的每个键都要挂着**非空的 data:image 值**。

    判据只查「键名存在」会空转：把值删成 `"app_qunar":""` 时键名还在，
    门禁照样绿（2026-10-31 负控实测）。必须把键与其后的 data URI 一起匹配。
    """
    src = _src()
    i = src.index("const SRX_PLATS={")
    j = src.index("};", i)
    plats = re.findall(r"(\w+):\[", src[i:j])

    k = src.index("const SRX_BRAND_IMG={")
    line = src[k:src.index("\n", k)]
    am = re.search(r"const SRX_BRAND_ALIAS=\{(.*?)\};", src, re.S)
    alias = dict(re.findall(r"(\w+):'(\w+)'", am.group(1) if am else ""))
    missing = []
    for p in plats:
        key = p if re.search(r'"%s"\s*:' % re.escape(p), line) else alias.get(p)
        m = re.search(r'"%s"\s*:\s*"data:image/[a-z+]+;base64,([A-Za-z0-9+/=]+)"'
                      % re.escape(key or ""), line)
        if not m or len(m.group(1)) < 100:
            missing.append(p)
    assert plats, "SRX_PLATS 解析为空（判据本身失效）"
    assert not missing, "这些渠道没有可用的官方图标（会退化成字符牌）：%s" % missing


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

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r715_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture(scope="module")
def page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        yield pg
        b.close()


def test_config_chips_render_official_icons_at_uniform_size(page):
    page.evaluate("switchView('cfg');showCfgPanel('users')")
    page.wait_for_timeout(1800)
    rows = page.evaluate("""(() => {
      return [...document.querySelectorAll('#cfgform .pch')].map(c => {
        const img = c.querySelector('img.bic');
        const r = img ? img.getBoundingClientRect() : null;
        return {txt: (c.textContent||'').trim(), img: !!img,
                fb: !!c.querySelector('.bic-fb'),
                natural: img ? img.naturalWidth : 0,
                w: r ? +r.width.toFixed(1) : 0,
                h: r ? +r.height.toFixed(1) : 0};
      });
    })()""")
    assert len(rows) >= 7, rows
    for r in rows:
        assert r["img"], "chip「%s」没有官方图标" % r["txt"]
        assert not r["fb"], "chip「%s」退化了字符牌" % r["txt"]
        assert r["natural"] > 0, "chip「%s」图标没解码（naturalWidth=0）" % r["txt"]
        assert (r["w"], r["h"]) == (16.0, 16.0), "chip「%s」图标尺寸 %s×%s 不是 16" % (
            r["txt"], r["w"], r["h"])


def test_login_rows_render_official_icons_at_uniform_size(page):
    page.evaluate("switchView('cfg');showCfgPanel('login')")
    page.wait_for_timeout(2200)
    rows = page.evaluate("""(() => {
      return [...document.querySelectorAll('#loginRows .lgcard')].map(r => {
        const n = r.querySelector('.lgname');
        const img = r.querySelector('img.bic');
        const rr = img ? img.getBoundingClientRect() : null;
        return {name: n ? (n.textContent||'').trim() : null,
                img: !!img, fb: !!r.querySelector('.bic-fb'),
                natural: img ? img.naturalWidth : 0,
                w: rr ? +rr.width.toFixed(1) : 0};
      });
    })()""")
    assert len(rows) >= 7, rows
    widths = set()
    for r in rows:
        assert r["img"], "登录行「%s」没有官方图标" % r["name"]
        assert not r["fb"], "登录行「%s」退化了字符牌" % r["name"]
        assert r["natural"] > 0, "登录行「%s」图标没解码" % r["name"]
        widths.add(r["w"])
    assert len(widths) == 1, "登录行图标宽度不一致（同族应同尺寸）：%s" % widths
    assert widths.pop() == 24.0, "登录行图标应为 24px 宽"


def test_search_channel_chips_cover_all_plats_with_icons(page):
    """检索台的渠道快筛也要有全部 7 家（含两家 App）且带官方图标。

    坑：`#srxPlats` 默认在收起的 `#srxContext`（`.ctx-collapsed` 会
    `display:none` 掉第二个 `.srx-line`）里，直接量宽高恒 0——
    「0 裁切 / 不溢出」在这种前提下是**假绿**。必须先 `SRX.ctx=true`。
    """
    page.evaluate("switchView('search')")
    page.wait_for_timeout(2500)
    page.evaluate("()=>{SRX.ctx=true;"
                  "if(typeof srxRenderCtx==='function')srxRenderCtx();}")
    page.wait_for_timeout(1200)
    out = page.evaluate("""(() => {
      const box = document.getElementById('srxPlats');
      if (!box) return {exists: false};
      const chips = [...box.querySelectorAll('.srx-chip')];
      return {exists: true, boxW: Math.round(box.getBoundingClientRect().width),
              n: chips.length,
              items: chips.map(c => ({
                t: (c.textContent||'').trim(), plat: c.dataset.plat || '',
                w: Math.round(c.getBoundingClientRect().width),
                clip: c.scrollWidth > c.clientWidth + 1,
                img: !!c.querySelector('img.bic'),
                fb: !!c.querySelector('.bic-fb')})),
              overflow: box.scrollWidth > box.clientWidth + 1};
    })()""")
    if not out.get("exists"):
        pytest.skip("检索台未渲染渠道快筛（无数据态）")
    assert out["boxW"] > 0, "渠道快筛容器宽度为 0，测量无效（可能仍在折叠态）"
    labels = [i["t"] for i in out["items"]]
    assert any("全部渠道" in t for t in labels), labels
    for name in ("智行 App", "去哪儿 App", "携程", "去哪儿", "飞猪", "同程", "途牛"):
        assert any(t.startswith(name) for t in labels), (
            "检索台渠道快筛缺少「%s」：%s" % (name, labels))
    for i in out["items"]:
        if not i["plat"]:
            continue  # 「全部渠道」是无图标的按钮
        assert i["img"], "快筛「%s」没有官方图标" % i["t"]
        assert not i["fb"], "快筛「%s」退化了字符牌" % i["t"]
    assert not out["overflow"], "渠道快筛一行溢出（会被裁掉尾部渠道）"
    assert all(not i["clip"] for i in out["items"]), \
        ["%s 文字被裁" % i["t"] for i in out["items"] if i["clip"]]


def test_login_rows_keep_one_action_column_under_mixed_states(page):
    """状态不一致时，7 行的操作按钮仍必须在同一列、同一高度。

    用户原话：「登录按钮看起来位置会飘，当状态不一致的时候，会显示不是
    同一行」。按钮**文字**按状态而变（弹窗登录 / 双端登录 / 继续登录 /
    登录 / 重新登录），若按内容定宽就会左右参差——实测各档宽度下
    `justify-self:end` + 96px 定宽把它们锁在同一列。

    判据用渲染矩形取「左缘集合」与「行高集合」，两者都必须各只有 1 个值。
    造态覆盖 ok/login/expired/unknown/wait/part 六种，App 槽位与浏览器槽位
    故意给不同状态。
    """
    page.evaluate("switchView('cfg');showCfgPanel('login')")
    page.wait_for_timeout(2200)
    for st in ("ok", "login", "expired", "unknown", "wait", "part"):
        out = page.evaluate("""(st) => {
          const j = (typeof CHANNEL_STATE !== 'undefined' && CHANNEL_STATE.payload) || {};
          const slots = {};
          const base = (j.slots && j.slots.ctrip) || {};
          ['ctrip','qunar','fliggy','fliggy_h5','tongcheng','tuniu'].forEach(k => {
            slots[k] = Object.assign({}, base, {slot: k, plat: k.replace('_h5',''),
              requirement: '必须登录', status: st, detail: 'T ' + st,
              account: st === 'ok' ? '138****8888' : ''});
          });
          CHANNEL_STATE.payload = Object.assign({}, j, {slots});
          if (typeof APP_LOGIN_STATE === 'object' && APP_LOGIN_STATE) {
            APP_LOGIN_STATE.app_zhixing = {status: st, detail: '',
                                           saved: true, active: st === 'ok'};
            APP_LOGIN_STATE.app_qunar = {status: st === 'ok' ? 'login' : 'ok',
                                         detail: '', saved: true, active: true};
          }
          renderLoginCards(true);
          const rows = [...document.querySelectorAll('#loginRows .lgcard')];
          const acts = rows.map(r => {
            const a = r.querySelector('.lgact')
                    || [...r.querySelectorAll('button,a.btn2')].pop();
            const ar = a ? a.getBoundingClientRect() : null;
            return {name: (r.querySelector('.lgname')||{}).textContent || '',
                    act: a ? (a.textContent||'').trim() : null,
                    L: ar ? Math.round(ar.left) : null,
                    W: ar ? Math.round(ar.width) : null,
                    H: Math.round(r.getBoundingClientRect().height)};
          });
          return {acts, uniqL: [...new Set(acts.map(a => a.L))],
                  uniqH: [...new Set(acts.map(a => a.H))]};
        }""", st)
        assert len(out["acts"]) >= 7, (st, out["acts"])
        assert len(out["uniqL"]) == 1, (
            "状态 %s 下操作按钮左缘参差：%s" % (st, out["acts"]))
        assert len(out["uniqH"]) == 1, (
            "状态 %s 下行高参差（按钮把行顶成两行）：%s" % (st, out["acts"]))
        assert out["uniqH"][0] == 52, (st, out["acts"])
