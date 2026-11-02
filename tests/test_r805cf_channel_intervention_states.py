# -*- coding: utf-8 -*-
"""r805cf：账本里的「滑块 / 登录门」必须变成登录卡与健康卡上的干预状态。

现场（2026-11-01 22:21，`fetch_paths`）：
    tuniu PC blocked「人机验证页（滑块），需在渠道登录窗口完成验证」
可同一轮 monitor.log 里 tuniu 国内成功出数，于是：
    健康卡写「最近一轮正常」、登录卡写「已保存 · 会话待验证」。
用户原话：「飞猪h5刚刚是被滑块验证码拦住了，然后要求重新登录，途牛pc是要求
验证码，为啥这些状态不在渠道登录处能正确识别发给予反馈？全渠道健康和遇到
需要干预的应该有相关状态流转需要」。

判据（全部读真实账本字段，不猜）：
  1. 账本拦截未恢复 → 槽位 `status=challenge|login_required`、
     `needs_login=True`，并带 `block{kind,at,path,note}`；
  2. 同入口后来成功、或重新保存会话之后 → 拦截算已恢复，不许常驻红灯；
  3. 按端隔离：飞猪 H5 被拦不把 PC 一起点亮；
  4. 健康诊断卡：账本拦截压过「最近一轮正常」，动作指向人工验证；
  5. 前端登录卡渲染「需人机验证 / 打开验证」，顶部干预入口可见。
"""
import logging
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui
from crawlers import REGISTRY

CAPTCHA_NOTE = "人机验证页（滑块），需在渠道登录窗口完成验证"
LOGIN_NOTE = "登录门（710114/needLogin）"


def ts(hhmmss):
    """当天（2026-11-01）时刻 → 'YYYY-MM-DD HH:MM:SS'。"""
    return "2026-11-01 " + hhmmss


def epoch(hhmmss):
    return datetime.strptime(ts(hhmmss), "%Y-%m-%d %H:%M:%S").timestamp()


def row(hhmmss, entry, status, note="", rows=0):
    return {"fetched_at": ts(hhmmss), "entry_path": entry,
            "path_status": status, "note": note, "rows": rows}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离存储：会话保存时刻可控、账本行按用例注入。"""
    saved = {"at": epoch("22:00:00")}

    class Channel:
        login_suspect = False

        def __init__(self, cfg, logger):
            self.user_data_root = cfg.get("user_data_dir", str(tmp_path))

        @property
        def session_saved_at(self):
            return saved["at"]

    for platform in REGISTRY:
        (tmp_path / platform).mkdir()
        (tmp_path / platform / "marker").write_text("profile")
        monkeypatch.setitem(REGISTRY, platform, Channel)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)},
                         "output": {"db_path": str(tmp_path / "state.db")}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {}, raising=False)
    monkeypatch.setattr(webui._State, "logger", logging.getLogger("r805cf"))
    monkeypatch.setattr(webui, "_health_state",
                        lambda hours: {"rounds": [], "evidence": {}})
    monkeypatch.setattr(webui, "_recent_path_rows",
                        lambda hours=24: {}, raising=False)
    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: Channel(cfg, logger))
    monkeypatch.setattr(webui, "_SLOT_VERIFY", {}, raising=False)
    return saved


# ── 纯函数：账本行 → 未恢复的拦截 ─────────────────────────────

def test_captcha_row_becomes_a_captcha_block():
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)],
        saved_at=epoch("22:00:00"))
    assert b and b["kind"] == "captcha", b
    assert b["path"] == "PC" and b["at"] == ts("22:21:11")


def test_login_wall_row_becomes_a_login_block():
    b = webui._path_block_from_rows(
        [row("21:52:33", "H5/API", "login", LOGIN_NOTE)],
        saved_at=epoch("21:00:00"))
    assert b and b["kind"] == "login", b


def test_unknown_blocked_note_is_not_guessed():
    """看不懂的 blocked（如 App 城市页失败）不许冒充验证/登录。"""
    b = webui._path_block_from_rows(
        [row("21:58:55", "app-route", "blocked",
             "设出发地失败：切档后没取到首页（dump 连续为空）")],
        saved_at=0)
    assert b is None, b


def test_later_success_on_same_entry_resolves_the_block():
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
         row("22:31:00", "PC", "ok", "", rows=5)],
        saved_at=epoch("22:00:00"))
    assert b is None, "同一入口之后已经成功，滑块不该继续顶着红灯"


def test_success_on_other_surface_does_not_resolve():
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
         row("22:31:00", "H5/API", "ok", "", rows=5)],
        saved_at=epoch("22:00:00"))
    assert b and b["path"] == "PC", "H5 成功不能把 PC 的滑块抹掉"


def test_unsupported_attempt_does_not_resolve_the_block():
    """unsupported 只是这次没走这条通路，没证明页面已打开。"""
    b = webui._path_block_from_rows(
        [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
         row("22:31:00", "PC", "unsupported", "该端不支持往返")],
        saved_at=epoch("22:00:00"))
    assert b and b["kind"] == "captcha", b


def test_network_error_is_not_a_block():
    b = webui._path_block_from_rows(
        [row("11:38:31", "PC", "error",
             "Page.goto: net::ERR_PROXY_CONNECTION_FAILED")],
        saved_at=0)
    assert b is None, b


# ── 登录状态：槽位确实带上拦截并会随重登恢复 ─────────────────

def test_tuniu_pc_captcha_surfaces_on_the_login_slot(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)]})
    v = webui._login_state_view()
    st = v["slots"]["tuniu"]
    assert st["status"] == "challenge", st
    assert st["needs_login"] is True
    assert st["block"]["kind"] == "captcha"
    assert st["block"]["path"] == "PC"
    assert "滑块" in st["block"]["note"]


def test_relogin_after_the_captcha_clears_it(env, monkeypatch):
    env["at"] = epoch("22:30:00")            # 用户 22:30 重新保存了会话
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)]})
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] != "challenge", st
    assert st["needs_login"] is False
    assert not st.get("block")


def test_fliggy_h5_captcha_does_not_light_up_pc(env, monkeypatch):
    env["at"] = epoch("22:00:00")
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "fliggy": [
            row("22:21:11", "H5", "blocked",
                "人机验证页，需在渠道登录窗口完成验证"),
            row("22:30:00", "PC", "ok", "", rows=48),
        ]})
    v = webui._login_state_view()
    assert v["slots"]["fliggy_h5"]["status"] == "challenge", v["slots"]["fliggy_h5"]
    assert v["slots"]["fliggy"].get("block") in (None, {}), v["slots"]["fliggy"]


def test_tuniu_intl_login_wall_reaches_the_slot(env, monkeypatch):
    """途牛国际入口的 710114/needLogin 要在登录卡上说「需重新登录」。"""
    env["at"] = epoch("11:00:00")
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("11:38:31", "H5/API", "login", LOGIN_NOTE)]})
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] == "login_required", st
    assert st["needs_login"] is True
    assert st["block"]["kind"] == "login"


# ── 健康诊断卡：账本拦截压过「最近一轮正常」 ─────────────────

def test_diag_card_shows_captcha_even_when_round_is_ok():
    from core.health_diag import classify_round
    cards = classify_round(
        {"tuniu": {"s": "ok", "ok": 1, "tot": 1, "cal": 0, "detail": 37,
                   "note": ""}},
        login={"tuniu": {"status": "challenge", "needs_login": True,
                         "challenge": {"kind": "captcha",
                                       "at": ts("22:21:11"),
                                       "path": "PC", "note": CAPTCHA_NOTE}}},
        all_plats=("tuniu",))
    c = cards[0]
    assert c["kind"] == "captcha", c
    assert c["label"] == "需要人工验证"
    assert "验证" in c["action"]
    assert "22:21" in c["evidence"] and "PC" in c["evidence"]


def test_diag_card_ignores_resolved_history():
    from core.health_diag import classify_round
    cards = classify_round(
        {"tuniu": {"s": "ok", "ok": 1, "tot": 1, "cal": 0, "detail": 37,
                   "note": ""}},
        login={"tuniu": {"status": "available", "needs_login": False}},
        all_plats=("tuniu",))
    assert cards[0]["kind"] == "ok", cards[0]


# ── 前端渲染：登录卡 / 顶部干预入口 / 健康诊断卡 ─────────────────

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def demo_base():
    import subprocess
    import tempfile
    import time
    import urllib.request

    pytest.importorskip("playwright",
                        reason="渲染门禁依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r805cf_")
    envd = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
                PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        base = "http://127.0.0.1:%d" % _free_port()
        proc = subprocess.Popen(
            [sys.executable, os.path.join(root, "webui.py"), "--demo",
             "--port", base.rsplit(":", 1)[1]],
            cwd=root, stdout=logf, stderr=subprocess.STDOUT, env=envd)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(base + "/api/state", timeout=2)
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
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


def test_login_card_renders_captcha_state(demo_base):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(demo_base + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
        out = pg.evaluate("""()=>{
          const block={kind:'captcha',at:'2026-11-01 22:21:11',path:'PC',
                       url:'https://flight.tuniu.com/domestic/list/x',
                       note:'人机验证页（滑块），需在渠道登录窗口完成验证'};
          CHANNEL_STATE={payload:{demo:false,
            plats:{tuniu:{status:'challenge',needs_login:true,saved:true,
                          saved_at:1793518030,active:false,saving:false,
                          pending:false,error:'',scopes:{},stale:false}},
            slots:{tuniu:{slot:'tuniu',plat:'tuniu',surface:'',surface_label:'全端',
              name:'途牛',account:'途牛账号',requirement:'必须登录',profile:'tuniu',
              saved:true,saved_at:1793518030,active:false,saving:false,pending:false,
              status:'challenge',needs_login:true,health_need_login:true,
              stale:false,error:'',detail:'',verified_at:'',page_ok:false,
              session_verified:false,detail_ok:false,block:block}}},
            error:'',request:1,at:Date.now(),pending:null};
          renderLoginCards(true);
          renderChannelState();
          const card=document.querySelector('#loginRows [data-channel="tuniu"]');
          const btn=card?card.querySelector('.lgact button'):null;
          const ha=document.getElementById('hauthact');
          return {text:card?card.innerText:'', act:btn?btn.innerText:'',
                  onclick:btn?String(btn.getAttribute('onclick')||''):'',
                  bg:btn?getComputedStyle(btn).backgroundColor:'',
                  haHidden:ha?ha.hidden:null, haText:ha?ha.innerText:'',
                  haTitle:ha?ha.title:''};}""")
        # 账本没有记到被拦页地址时退回「弹窗登录」，不能编一个地址出来
        out_nourl = pg.evaluate("""()=>{
          CHANNEL_STATE.payload.slots.tuniu.block={kind:'captcha',
            at:'2026-11-01 22:21:11',path:'PC',
            note:'人机验证页（滑块），需在渠道登录窗口完成验证'};
          renderLoginCards(true);
          const btn=document.querySelector('#loginRows [data-channel="tuniu"] .lgact button');
          return btn?String(btn.getAttribute('onclick')||''):'';}""")
        pg.close()
        br.close()
    assert "需人机验证" in out["text"], out["text"]
    assert "打开验证" in out["act"], out["act"]
    assert "loginChallenge" in out["onclick"], out["onclick"]
    assert "loginStart" in out_nourl, out_nourl
    assert out["haHidden"] is False, "顶部干预入口没亮"
    assert "途牛" in out["haTitle"], out["haTitle"]


def test_health_diag_card_renders_captcha(demo_base):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(demo_base + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
        out = pg.evaluate("""()=>{
          HL=JSON.stringify({demo:false,diag_at:'2026-11-01 22:21',
            diag:[{plat:'tuniu',name:'途牛',kind:'captcha',label:'需要人工验证',
              action:'打开渠道可见窗口完成验证',s:'ok',ok:1,tot:1,detail:37,cal:0,
              login:'challenge',cookie:'',evidence:'2026-11-01 22:21:11 · PC · 滑块'}]});
          renderHealthDiag();
          const card=document.querySelector('#healthDiagBody .hdiag-card');
          return {text:card?card.innerText:'',
                  kinds:card?card.className:'',
                  buttons:card?Array.from(card.querySelectorAll('button')).map(b=>b.innerText):[]};}""")
        pg.close()
        br.close()
    assert "需要人工验证" in out["text"], out["text"]
    assert "去验证" in " ".join(out["buttons"]), out["buttons"]


# ── 人机验证入口：打开账本里被拦的那一页（r805cg） ─────────────

def test_block_carries_the_blocked_url():
    b = webui._path_block_from_rows(
        [dict(row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
              request_url="https://flight.tuniu.com/domestic/list/SHA_BJS")],
        saved_at=epoch("22:00:00"))
    assert b and b["url"].endswith("/SHA_BJS"), b


def test_challenge_target_requires_a_blocked_url(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [row("22:21:11", "PC", "blocked", CAPTCHA_NOTE)]})
    t = webui._challenge_target("tuniu")
    assert t["ok"] is False and "被拦页地址" in t["err"], t
    assert webui._challenge_target("ctrip")["ok"] is False


def test_challenge_target_carries_url_and_desktop_flag(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [dict(row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
                       request_url="https://flight.tuniu.com/domestic/list/x")]})
    t = webui._challenge_target("tuniu")
    assert t["ok"] is True and t["desktop"] is True, t
    assert t["plat"] == "tuniu" and t["url"].endswith("/x")


def test_challenge_window_uses_blocked_page_and_desktop_identity(env, monkeypatch):
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [dict(row("22:21:11", "PC", "blocked", CAPTCHA_NOTE),
                       request_url="https://flight.tuniu.com/domestic/list/x")]})
    seen = {}

    class Fake:
        name = "tuniu"
        use_mobile = True

        def __init__(self, cfg, logger):
            pass

        def open_challenge_window(self, url, evt, timeout_s=0, idx=0,
                                  ready_evt=None):
            seen.update(url=url, mobile=self.use_mobile)
            if ready_evt is not None:
                ready_evt.set()
            evt.wait(3)
            return True

        def _login_window(self, *a, **k):
            seen["login_window"] = True
            return True

    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: Fake(cfg, logger))
    webui._State.login_pending.clear()
    res = webui._start_login("tuniu", "tuniu",
                             url="https://flight.tuniu.com/domestic/list/x",
                             desktop=True)
    assert res.get("ok") is True, res
    assert seen.get("url", "").endswith("/x"), seen
    assert seen.get("mobile") is False, "PC 被拦却用手机档打开验证"
    assert "login_window" not in seen
    webui._finish_login("tuniu", "tuniu")
    import time as _t
    deadline = _t.time() + 5
    while webui._State.login_sessions.get("tuniu") and _t.time() < deadline:
        _t.sleep(0.05)
    from core.storage import PriceStorage
    rows = PriceStorage(
        str(webui._State.cfg["output"]["db_path"])).interventions("tuniu", 8)
    assert any("人机验证完成" in str(r.get("note") or "") for r in rows), rows


def test_challenge_window_uses_mobile_identity_for_h5_block(env, monkeypatch):
    url = "https://m.ctrip.com/restapi/soa2/19728/json/flightListSearch"
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "ctrip": [dict(row("22:21:11", "H5", "blocked", CAPTCHA_NOTE),
                       request_url=url)]})
    seen = {}

    class Fake:
        name = "ctrip"
        use_mobile = False

        def __init__(self, cfg, logger):
            pass

        def open_challenge_window(self, u, evt, timeout_s=0, idx=0,
                                  ready_evt=None):
            seen.update(url=u, mobile=self.use_mobile)
            if ready_evt is not None:
                ready_evt.set()
            evt.wait(3)
            return True

        def _login_window(self, *a, **k):
            seen["login_window"] = True
            return True

    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: Fake(cfg, logger))
    t = webui._challenge_target("ctrip")
    assert t["ok"] is True and t["mobile"] is True and t["desktop"] is False, t
    webui._State.login_pending.clear()
    res = webui._start_login("ctrip", "ctrip", url=t["url"],
                             desktop=False, mobile=True)
    assert res.get("ok") is True, res
    assert seen.get("url") == url and seen.get("mobile") is True, seen
    webui._finish_login("ctrip", "ctrip")
    import time as _t
    deadline = _t.time() + 5
    while webui._State.login_sessions.get("ctrip") and _t.time() < deadline:
        _t.sleep(0.05)
