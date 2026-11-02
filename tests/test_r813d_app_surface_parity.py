# -*- coding: utf-8 -*-
"""r813d：App 渠道在各产品面上与浏览器渠道同权（用户点名的「全项目覆盖」）。

2026-11-01 审计发现同一类缺陷的 6 个落点（都是「5 家写死表」的变体）：

1. 演示 `/api/health` 的诊断卡只有 5 家——`classify_round(plats)` 用默认
   `all_plats=PLATFORMS`，而演示轮次里本来有 7 家 → 两张 App 卡整张消失；
2. 诊断卡上的「自检」按钮对 App 报「未知渠道」——端点拿登录槽位表
   `_LOGIN_PLATS` 当白名单（App 走 `/api/app-login`，不在槽位表里）；
3. 批量自检把两家 App 各跑两遍——`SRX_PLATS` 已含 7 家，再
   `.concat(APP_PLAT_NAME)` 重复追加；
4. 健康卡「轮日志」标题里 App 显示裸 id；
5. 特价雷达航班行 / 达标推送文案里 App 显示裸 id；
6. 干预作用域把 `app` 标成「智行 App」——去哪儿 App 的重登也被写成智行。

本门禁：演示诊断卡走**真 HTTP 响应**；其余走源码结构（演示是只读门，
自检 POST 一律 403，不能在 demo 里伪造一次成功写）。每条都钉住「单一
名称/清单源」，防止下次加渠道再冒一张 5 家表。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _src():
    with open(WEBUI, encoding="utf-8") as f:
        return f.read()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    p = subprocess.Popen([sys.executable, "webui.py", "--demo",
                          "--port", str(port)],
                         cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(160):
        try:
            op.open("http://127.0.0.1:%d/api/state" % port, timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        p.terminate()
        pytest.skip("演示服务未在期限内起来")
    yield port
    p.terminate()


def test_demo_health_diag_covers_all_registered_channels(server):
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS, plat_cn
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    h = json.load(op.open("http://127.0.0.1:%d/api/health" % server))
    plats = [c.get("plat") for c in (h.get("diag") or [])]
    all_plats = tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)
    assert set(plats) == set(all_plats), plats
    by = {c["plat"]: c for c in h["diag"]}
    for p in APP_CHANNELS:
        assert by[p].get("name") == plat_cn(p), by[p]


def test_health_grid_handles_six_and_eight_cards(server):
    """只启用一个 App（6 张）或未来第 8 家（8 张）也不能出现单张独占一行。

    当前 7 张规则只覆盖 5/7；6 张在 1512 的 auto-fit 会排成 5+1（孤卡），
    8 张则会 6+2。这里克隆真实卡放进一个**合成 .hdiag 容器**（宽度取真实
    网格），只验证列数规则本身——不碰健康页的 10s 轮询重绘。
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1512, "height": 1100})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            pg.goto("http://127.0.0.1:%d/#health" % server,
                    wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_function(
                "typeof S!=='undefined' && S && S.users", timeout=15000)
            pg.wait_for_selector(".hdiag-card", timeout=15000)
            pg.wait_for_timeout(1200)

            def make(n):
                pg.evaluate("""(n)=>{
                  const old=document.getElementById('srxTestHdiag');
                  if(old)old.remove();
                  const src=document.querySelector('#healthDiagBody .hdiag')
                    ||document.querySelector('.hdiag');
                  const w=src.getBoundingClientRect().width;
                  const cards=[...src.querySelectorAll('.hdiag-card')];
                  if(!cards.length)throw new Error('没有可克隆的诊断卡');
                  const box=document.createElement('div');
                  box.className='hdiag';box.id='srxTestHdiag';
                  box.dataset.n=String(n);
                  box.style.width=w+'px';box.style.maxWidth='100%';
                  for(let i=0;i<n;i++)
                    box.appendChild(cards[i%cards.length].cloneNode(true));
                  document.body.appendChild(box);
                }""", n)

            def rows():
                return pg.evaluate("""()=>{
                  const box=document.getElementById('srxTestHdiag');
                  if(!box)return [];
                  const cs=[...box.querySelectorAll('.hdiag-card')];
                  const m={};
                  cs.forEach(c=>{const r=c.getBoundingClientRect();
                    const bt=c.querySelector('[data-diagself]');
                    const k=Math.round(r.top);
                    (m[k]=m[k]||[]).push({w:Math.round(r.width),
                      btn:bt?Math.round(bt.getBoundingClientRect().top):-1});});
                  return Object.values(m).map(a=>({n:a.length,
                    w:[...new Set(a.map(x=>x.w))],
                    btn:[...new Set(a.map(x=>x.btn))]}));
                }""")

            for n, cases in (
                    (6, ((1512, 6), (900, 3), (768, 3), (390, 1))),
                    (8, ((1512, 4), (900, 4), (768, 4), (390, 1)))):
                for w, want in cases:
                    pg.set_viewport_size({"width": w, "height": 1100})
                    pg.wait_for_timeout(250)
                    make(n)
                    rws = rows()
                    assert [r["n"] for r in rws] == [1] * n if w == 390                         else ([r["n"] for r in rws] == [want, want]
                              if not (n == 6 and w == 1512)
                              else [r["n"] for r in rws] == [6]), (
                        "%d 张 %d 档排布异常：%s" % (n, w, rws))
                    for r in rws:
                        assert len(r["w"]) == 1 and len(r["btn"]) == 1, (w, r)
            pg.evaluate("""()=>{const e=document.getElementById('srxTestHdiag');
              if(e)e.remove();}""")
            assert not errs, errs[:3]
        finally:
            b.close()


def test_diag_cards_stay_aligned_at_every_width(server):
    """全部诊断卡：不留单张、同排按钮同一纵坐标、同排卡等宽。

    实测缺陷（r813f）：`data-n` 定列规则只写了 5 张，7 张退回 auto-fit，
    900/768 排成 3+3+**1（第 7 张独占 1/3 宽）**、1512 排成 5+2；卡宽
    175px 时「登录/Cookie/最近轮次」有的折两行、有的三行，同排「自检」
    纵坐标差 17px。修法是显式列数 + 卡头/登录行定高地板。卡数从
    BROWSER_CHANNELS + APP_CHANNELS 派生，加渠道不用再改期望值。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    from playwright.sync_api import sync_playwright

    n_cards = len(BROWSER_CHANNELS) + len(APP_CHANNELS)

    def measure(pg, width):
        pg.set_viewport_size({"width": width, "height": 1100})
        pg.goto("http://127.0.0.1:%d/#health" % server,
                wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_function(
            "typeof S!=='undefined' && S && S.users", timeout=15000)
        pg.wait_for_selector(".hdiag-card", timeout=15000)
        pg.wait_for_timeout(900)
        return pg.evaluate("""()=>[...document.querySelectorAll('.hdiag-card')].map(c=>{
          const r=c.getBoundingClientRect();
          const b=c.querySelector('[data-diagself]');
          return {top:Math.round(r.top),width:Math.round(r.width),
                  btn:b?Math.round(b.getBoundingClientRect().top):-1,
                  self:b?b.getAttribute('data-diagself'):''};})""")

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1512, "height": 1100})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            for width in (1512, 1280, 1024, 900, 768, 390):
                cards = measure(pg, width)
                assert len(cards) == n_cards, (width, len(cards))
                rows = {}
                for c in cards:
                    rows.setdefault(c["top"], []).append(c)
                counts = [len(v) for _, v in sorted(rows.items())]
                if width > 700:
                    assert 1 not in counts, (
                        "%d 档有单张独占一行：%s" % (width, counts))
                for _, v in rows.items():
                    assert len({c["width"] for c in v}) == 1, (width, v)
                    assert len({c["btn"] for c in v}) == 1, (
                        "%d 档同行「自检」纵坐标不一致：%s"
                        % (width, sorted({c["btn"] for c in v})))
                if width <= 700:
                    assert counts == [1] * n_cards, (width, counts)
            selfs = {c["self"] for c in cards}
            assert set(APP_CHANNELS) <= selfs, selfs
            assert not errs, errs[:3]
        finally:
            b.close()


def test_selfcheck_whitelist_is_diagnosis_not_login():
    s = _src()
    assert "_SELFCHECK_PLATS = tuple(_LOGIN_PLATS) + tuple(_APP_CHANNELS)" in s
    assert "if plat not in _SELFCHECK_PLATS:" in s
    # 旧写法（登录槽位当白名单）不得回潮
    assert "if plat not in _LOGIN_PLATS:\n                    raise ValueError" \
        not in s


def test_batch_selfcheck_does_not_probe_apps_twice():
    s = _src()
    assert "Object.keys(SRX_PLATS).concat(Object.keys(APP_PLAT_NAME))" not in s
    assert ":Object.keys(SRX_PLATS);" in s


def test_log_title_uses_shared_name_table():
    s = _src()
    i = s.index("async function showLog(")
    block = s[i:i + 1400]
    assert "PCN[p]" in block, block[:300]
    assert "'tongcheng':'同程','tuniu':'途牛'}[p]" not in block


def test_radar_flights_and_push_use_single_name_source():
    s = _src()
    assert 'r["platform_cn"] = _plat_cn(r["platform"])' in s
    assert 'pname = Alerter.plat_cn(str(cur.get("platform") or "")) or "渠道"' in s
    for old in ('"tongcheng": "同程", "tuniu": "途牛"}',
                '"fliggy": "飞猪", "tongcheng": "同程"}.get('):
        assert old not in s, old


def test_same_flight_coverage_denominator_is_not_hardcoded_five():
    """同班覆盖分母写死 5：接入两家 App 后会显示「7/5」。"""
    s = _src()
    assert "'/5 渠道'" not in s
    assert "const _nCh=Math.max(1,new Set(all.map(x=>x.platKey)).size);" in s
    assert "ps.size+'/'+_nCh+' 渠道</span>" in s


def test_pacing_effect_is_computed_for_app_channels_too():
    """节流面板「干预成效」不能只算浏览器五家。"""
    s = _src()
    i = s.index("_eff[_p0] = _pst.intervention_effect")
    block = s[max(0, i - 500):i]
    assert "_APP_CHANNELS" in block, block[-300:]
    assert '"qunar", "tongcheng", "tuniu"]' not in block.replace("\n", " ")


def test_lowest_pill_and_login_toast_use_shared_app_names():
    """「全线最低」胶囊与登录 toast 也不许出现裸 App id。

    这两处各留了一张 5 家名字表：胶囊 `PLATCN`（图标已改 srxPlatKey、
    名字没改）和 toast 的 `LOGIN_CN` 链。App 最便宜/点去登录时会把
    `app_qunar` / `app` 直接打到屏上。
    """
    s = _src()
    assert "const PLATCN=" not in s
    assert "platCN(brief.view_plat||brief.plat)" in s
    i = s.index("const _nm=(typeof LOGIN_SLOT_CN")
    toast = s[i:i + 400]
    assert "APP_PLAT_NAME[p]" in toast, (
        "登录 toast 的名称链没有 App 名：%r" % toast[:200])


def test_intervention_scope_app_is_split_per_channel():
    """两个 App 的登录干预必须可区分：写渠道 id，不合并成 app。"""
    s = _src()
    assert "app:'智行 App'" not in s
    assert "app_zhixing:'智行 App'" in s
    assert "app_qunar:'去哪儿 App'" in s
    assert "app:'App 登录（旧记录）'" in s
    assert "scope=_plata" in s
