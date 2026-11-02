# -*- coding: utf-8 -*-
r"""r668：新接入一个 App 渠道时，每个分区都要有它的落点。

并行会话接入去哪儿 App（r665）后，人工普查发现有一处需要规则确认：
节流「最小间隔」控件**只在渠道已勾选时出现**（未启用就不显示，这是
r659 定下的设计），而登录卡 / 节流行 / 健康「未扫描」行要无条件覆盖。

这条门禁把当时的普查结论钉住，避免下次接新渠道又靠人肉看：

① 登录卡数量与 `APP_CHANNELS + LOGIN_SLOTS 的厂商` 一致（含新 App）；
② 勾选全部 App 渠道后，节流分区里每个渠道都有自己的「最小间隔」控件；
③ 已勾选但没扫过的 App 渠道，健康卡必须出现「未扫描：<中文名>」；
④ 预热渠道清单不得包含没有 `warmup_url` 的 App 渠道（可点但什么也不做
   正是 r627 修过的缺陷）。

负控见各测试注释；其中 ③ 的负控是去掉 enabled_platforms。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _render():
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1400})
                pg.set_default_timeout(20000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                out = {}
                pg.evaluate("()=>{try{switchView('cfg')}catch(e){}}")
                pg.wait_for_timeout(1200)
                pg.evaluate("""()=>{const c=document.querySelector(
                  '#cfgnav .cnav[data-p="login"]');if(c)c.click()}""")
                pg.wait_for_timeout(900)
                out["login_cards"] = pg.evaluate(
                    "()=>[...document.querySelectorAll('#loginRows .lgcard')]"
                    ".length")
                pg.evaluate("""()=>{const c=document.querySelector(
                  '#cfgnav .cnav[data-p="pacing"]');if(c)c.click()}""")
                pg.wait_for_timeout(800)
                out["cadence"] = pg.evaluate("""()=>{
                  CFG[0].platforms=CFG[0].platforms.concat(
                    Object.keys(APP_PLAT_NAME)
                      .filter(p=>CFG[0].platforms.indexOf(p)<0));
                  buildForm();
                  const box=document.getElementById('cfgpacing');
                  return [...box.querySelectorAll('[id^="glbCad_"]')]
                    .map(e=>e.id.replace('glbCad_',''))
                    .filter(x=>!/Err$/.test(x));}""")
                out["warmable"] = pg.evaluate("()=>GLB.warmable")
                out["health_miss"] = pg.evaluate("""()=>{
                  const appKeys=Object.keys(APP_PLAT_NAME);
                  const rounds=[];
                  for(let i=0;i<3;i++) rounds.push({ts:'10-30 0'+i+':00',
                    plats:{fliggy:{s:'ok',ok:1,tot:1,cal:0,detail:1}}});
                  renderHealth({rounds:rounds,
                    stats:{fliggy:{ok:1,part:0,fail:0,rate:1,cal:0,
                                   detail:1,auth:0,maint:0}},
                    paths:{},by_scope:{},
                    enabled_platforms:['fliggy'].concat(appKeys),
                    push:{channels:{}}});
                  const m=document.querySelector('#hbody .hmiss');
                  return m?m.innerText:'';}""")
                return out
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


@pytest.fixture(scope="module")
def got():
    return _render()


def test_login_section_covers_every_channel(got):
    from core.channels import APP_CHANNELS
    from core.login_slots import LOGIN_SLOTS
    plats = set(APP_CHANNELS)
    plats |= {s.get("plat") for s in LOGIN_SLOTS.values()}
    assert got["login_cards"] >= len(plats), (
        "登录卡只有 %d 张，渠道（含 App）有 %d 个：%s"
        % (got["login_cards"], len(plats), sorted(plats)))


def test_pacing_cadence_control_exists_for_every_enabled_app(got):
    from core.channels import APP_CHANNELS
    missing = [p for p in APP_CHANNELS if p not in got["cadence"]]
    assert not missing, (
        "这些 App 渠道勾选后仍没有「最小间隔」控件：%s（实际：%s）"
        % (missing, got["cadence"]))


def test_unscanned_enabled_app_is_named_in_health(got):
    from core.channels import APP_CHANNELS, plat_cn
    assert got["health_miss"], "已勾选但未扫描的渠道没有任何说明"
    for p in APP_CHANNELS:
        assert plat_cn(p) in got["health_miss"], (
            "%s 已勾选但没扫，健康卡没点名它：%r" % (p, got["health_miss"]))
        assert p not in got["health_miss"], (
            "未扫描说明里露出了原始 id：%r" % got["health_miss"])


def test_warmup_list_excludes_channels_without_entry(got):
    """预热渠道只能是真有入口的——列进去就是「可点但没反应」（r627）。"""
    from crawlers import REGISTRY
    no_entry = [k for k, cls in REGISTRY.items()
                if not str(getattr(cls, "warmup_url", "") or "").strip()]
    bad = [p for p in got["warmable"] if p in no_entry]
    assert not bad, "预热清单里含没有入口的渠道：%s" % bad
