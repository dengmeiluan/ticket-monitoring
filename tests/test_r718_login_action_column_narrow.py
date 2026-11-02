# -*- coding: utf-8 -*-
"""r718 手机宽度（390）下登录行的操作按钮也必须同列。

用户原话：「登录按钮看起来位置会飘，当状态不一致的时候，会显示不是同一行」。

桌面档（>700px）由 `grid-template-columns: max-content 1fr 96px` 锁住，
但窄档媒体规则此前写的是 `minmax(0,1fr) auto`——`auto` 按按钮**文字**定宽：
「登录」宽 50、左缘 312；「重新登录」宽 72、左缘 290，同一列表内右缘对齐
但左缘差 22px（390 实测）。这正是「状态不一致时按钮不在同一行」的成因。

判据：把视口调到 390×844（is_mobile + has_touch，贴近真机），要求 7 行的
操作按钮**左缘集合、右缘集合各自只有 1 个值**，且无横向溢出。
左右都查：只查右缘的话 `justify-self:end` 会让「差 22px」的缺陷漏网。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="窄档对标依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


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
    priv = tempfile.mkdtemp(prefix="r718_")
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
def mobile_page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844},
                        is_mobile=True, has_touch=True, device_scale_factor=2)
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        yield pg
        b.close()


def _measure(pg):
    return pg.evaluate("""(() => {
      const rows=[...document.querySelectorAll('#loginRows .lgcard')];
      const acts=rows.map(r=>{
        const a=r.querySelector('.lgact')
              || [...r.querySelectorAll('button,a.btn2')].pop();
        const ar=a?a.getBoundingClientRect():null;
        return {t:a?(a.textContent||'').trim():null,
                L:ar?Math.round(ar.left):null,
                R:ar?Math.round(ar.right):null,
                W:ar?Math.round(ar.width):null};
      });
      return {n:rows.length, acts,
              uniqL:[...new Set(acts.map(a=>a.L))],
              uniqR:[...new Set(acts.map(a=>a.R))],
              uniqW:[...new Set(acts.map(a=>a.W))],
              over:document.body.scrollWidth>window.innerWidth+1};
    })()""")


def test_phone_width_action_buttons_share_one_column(mobile_page):
    mobile_page.evaluate("switchView('cfg');showCfgPanel('login')")
    mobile_page.wait_for_timeout(2000)
    out = _measure(mobile_page)
    assert out["n"] >= 7, out["acts"]
    assert len(out["uniqL"]) == 1, (
        "390 档操作按钮左缘参差（状态不一致时会读作不在同一行）：%s"
        % out["acts"])
    assert len(out["uniqR"]) == 1, ("390 档操作按钮右缘参差：%s" % out["acts"])
    assert len(out["uniqW"]) == 1, ("390 档操作按钮宽度参差：%s" % out["acts"])
    assert not out["over"], "390 档横向溢出"


def test_phone_width_action_buttons_share_one_column_when_states_mixed(
        mobile_page):
    """窄档 + 混合登录态（用户实际遇到的组合）同样要同列。"""
    for st in ("ok", "login", "expired", "unknown", "wait", "part"):
        out = mobile_page.evaluate("""(st) => {
          const j = (typeof CHANNEL_STATE !== 'undefined' && CHANNEL_STATE.payload) || {};
          const slots = {};
          const base = (j.slots && j.slots.ctrip) || {};
          ['ctrip','qunar','fliggy','fliggy_h5','tongcheng','tuniu'].forEach(k => {
            slots[k] = Object.assign({}, base, {slot:k, plat:k.replace('_h5',''),
              requirement:'必须登录', status:st, detail:'T '+st,
              account: st==='ok' ? '138****8888' : ''});
          });
          CHANNEL_STATE.payload = Object.assign({}, j, {slots});
          if (typeof APP_LOGIN_STATE === 'object' && APP_LOGIN_STATE) {
            APP_LOGIN_STATE.app_zhixing = {status:st, detail:'', saved:true,
                                           active: st==='ok'};
            APP_LOGIN_STATE.app_qunar = {status: st==='ok'?'login':'ok',
                                         detail:'', saved:true, active:true};
          }
          renderLoginCards(true);
          const rows=[...document.querySelectorAll('#loginRows .lgcard')];
          const acts=rows.map(r=>{
            const a=r.querySelector('.lgact')
                  || [...r.querySelectorAll('button,a.btn2')].pop();
            const ar=a?a.getBoundingClientRect():null;
            return {t:a?(a.textContent||'').trim():null,
                    L:ar?Math.round(ar.left):null,
                    R:ar?Math.round(ar.right):null};
          });
          return {acts, uniqL:[...new Set(acts.map(a=>a.L))],
                  uniqR:[...new Set(acts.map(a=>a.R))]};
        }""", st)
        assert len(out["uniqL"]) == 1, (
            "390 档混合态 %s：按钮左缘参差 %s" % (st, out["acts"]))
        assert len(out["uniqR"]) == 1, (
            "390 档混合态 %s：按钮右缘参差 %s" % (st, out["acts"]))


# r731：把「状态全集」逐项注入，而不是只试 6 种组合。
# 每种状态都会产出**不同长度的按钮文案**（登录 / 重新登录 / 等待核验 /
# 立即核验 / 我已登录完成 / 正在保存会话… / 继续登录），「位置会飘」
# 正是文案长度变了而列宽跟着文字走造成的。所以枚举全部状态逐个量。
_ALL_STATUS = ("missing", "saved", "pending", "page_ok", "available",
               "login_required", "challenge", "save_error", "ok", "wait",
               "part", "expired", "unknown")


@pytest.mark.parametrize("st", _ALL_STATUS)
def test_every_status_keeps_action_column(mobile_page, st):
    out = mobile_page.evaluate("""(st) => {
      const j = (typeof CHANNEL_STATE !== 'undefined' && CHANNEL_STATE.payload) || {};
      const slots = {};
      const base = (j.slots && j.slots.ctrip) || {};
      ['ctrip','qunar','fliggy','fliggy_h5','tongcheng','tuniu'].forEach(k => {
        slots[k] = Object.assign({}, base, {slot:k, plat:k.replace('_h5',''),
          requirement:'必须登录', status:st, detail:'T '+st,
          account:'', saved: !['missing','save_error','login_required',
                              'challenge'].includes(st)});
      });
      CHANNEL_STATE.payload = Object.assign({}, j, {slots});
      if (typeof APP_LOGIN_STATE === 'object' && APP_LOGIN_STATE) {
        APP_LOGIN_STATE.app_zhixing = {status:st, detail:'', saved:true,
                                       active:false};
        APP_LOGIN_STATE.app_qunar = {status:st, detail:'', saved:true,
                                     active:false};
      }
      renderLoginCards(true);
      const rows=[...document.querySelectorAll('#loginRows .lgcard')];
      const acts=rows.map(r=>{
        const a=r.querySelector('.lgact')
              || [...r.querySelectorAll('button,a.btn2')].pop();
        const ar=a?a.getBoundingClientRect():null;
        return {t:a?(a.textContent||'').trim():null,
                L:ar?Math.round(ar.left):null,
                R:ar?Math.round(ar.right):null,
                W:ar?Math.round(ar.width):null};
      });
      return {n:rows.length, acts,
              uniqL:[...new Set(acts.map(a=>a.L))],
              uniqR:[...new Set(acts.map(a=>a.R))],
              uniqW:[...new Set(acts.map(a=>a.W))],
              over:document.body.scrollWidth>window.innerWidth+1};
    }""", st)
    assert out["n"] >= 7, out["acts"]
    assert len(out["uniqL"]) == 1, (
        "状态 %s：390 档按钮左缘参差（读作不在同一行）：%s" % (st, out["acts"]))
    assert len(out["uniqR"]) == 1, (
        "状态 %s：390 档按钮右缘参差：%s" % (st, out["acts"]))
    assert len(out["uniqW"]) == 1, (
        "状态 %s：390 档按钮宽度随文案变：%s" % (st, out["acts"]))
    assert not out["over"], "状态 %s：390 档横向溢出" % st


def test_action_texts_cover_the_enumerated_states(mobile_page):
    """副证：上面枚举的每个状态确实产出了**不同**的按钮文案。

    否则「都对齐了」可能只是因为每个状态渲染的是同一个按钮
    （判据恒真）。这里要求至少出现 4 种不同文案。
    """
    texts = set()
    for st in _ALL_STATUS:
        t = mobile_page.evaluate("""(st) => {
          const j = (typeof CHANNEL_STATE !== 'undefined' && CHANNEL_STATE.payload) || {};
          const base = (j.slots && j.slots.ctrip) || {};
          const slots = {};
          ['ctrip','qunar','fliggy','fliggy_h5','tongcheng','tuniu'].forEach(k => {
            slots[k] = Object.assign({}, base, {slot:k, plat:k.replace('_h5',''),
              requirement:'必须登录', status:st, account:''});
          });
          CHANNEL_STATE.payload = Object.assign({}, j, {slots});
          if (typeof APP_LOGIN_STATE === 'object' && APP_LOGIN_STATE) {
            APP_LOGIN_STATE.app_zhixing = {status:st, detail:'', saved:true,
                                           active:false};
            APP_LOGIN_STATE.app_qunar = {status:st, detail:'', saved:true,
                                         active:false};
          }
          renderLoginCards(true);
          const b=document.querySelector('#loginRows .lgcard .lgact button');
          return b?(b.textContent||'').trim():'';
        }""", st)
        if t:
            texts.add(t)
    assert len(texts) >= 4, (
        "枚举状态只产出了 %d 种按钮文案，对齐断言可能是恒真的：%s"
        % (len(texts), sorted(texts)))
