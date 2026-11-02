# -*- coding: utf-8 -*-
"""r805ae：`round_trip=y` 但只覆盖一端时，「范围」必须与声明同源。

矩阵一格装不下「飞猪仅国际 / 途牛仅国内」。此前检索页把这句话**写死在
JS 表**里（`RT_SCOPE_NOTE={fliggy:'飞猪仅国际',…}`），而矩阵格子里的 ✓
悬停什么也没说——同一件事两处文案、两份事实源。声明的单一事实源是
`core/channels.py`，范围也应从那里下发。

判据：
  1. 源层：凡 `round_trip=y` 且**只覆盖一端**的渠道，必须同时有
     `DIMENSION_SCOPE`（短标签，检索页 chip 用）与 `DIMENSION_NOTES`
     （完整说明，矩阵格悬停用）——只写短标签等于没解释为什么；
     反过来，**全覆盖**的渠道不得带 scope（否则「智行仅国际」这类
     假限定会被拼出来）。
  2. 接口层：`/api/channel-dims` 下发 `dim_scopes`，前端从它拼文案。
  3. 渲染层：真浏览器里「往返票」chip 的 title 与矩阵格的 title 都要
     出现范围词——写死在 JS 的旧表虽然也能让 chip 出现文字，但矩阵格
     仍会空着，这正是本门禁要分开量的原因。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_every_unsupported_cell_is_explained():
    """任何写「不支持」的格子都必须说明为什么，否则会被读成「渠道没有」。

    两次踩点：携程**产品上有往返**、五个浏览器站点**都有多程入口**，
    只是我们没接/结果页不给总价。只显示「不支持」= 把「我们不采集」
    读成「渠道没有这个产品」，用户自然要问「为啥不都实现」。
    """
    from core.channels import (CHANNEL_DIMENSIONS, DIMENSION_NOTES,
                               DIMENSIONS)
    missing = ["%s.%s" % (p, d)
               for p in CHANNEL_DIMENSIONS
               for d in DIMENSIONS
               if CHANNEL_DIMENSIONS[p].get(d) == "n"
               and not (DIMENSION_NOTES.get((p, d)) or "").strip()]
    assert not missing, (
        "这些格子写 n 却没有说明为什么：%s" % sorted(missing))


def test_partial_round_trip_channels_declare_scope_and_note():
    from core.channels import (CHANNEL_DIMENSIONS, DIMENSION_NOTES,
                               DIMENSION_SCOPE, DIMENSIONS)
    partial = {p for p, cells in CHANNEL_DIMENSIONS.items()
               if cells.get("round_trip") == "y"
               and (p, "round_trip") in DIMENSION_SCOPE}
    assert partial == {"fliggy", "tuniu", "tongcheng", "qunar",
                      "app_qunar"}, (
        "「只覆盖一端」的往返渠道集合变了：%s（改声明时同步改本判据）"
        % sorted(partial))
    for p in partial:
        sc = DIMENSION_SCOPE[(p, "round_trip")]
        assert sc in ("仅国际", "仅国内"), (
            "%s 的范围短标签不是「仅国际/仅国内」：%r" % (p, sc))
        note = DIMENSION_NOTES.get((p, "round_trip")) or ""
        assert sc.strip("仅") in note, (
            "%s 的完整说明没写出范围（%r 里找不到 %r）——短标签与长说明"
            "必须说同一件事" % (p, note, sc))
    # 反向：全覆盖的渠道不得带 scope，否则会拼出假限定
    full = [p for p, cells in CHANNEL_DIMENSIONS.items()
            if cells.get("round_trip") == "y" and p not in partial]
    for p in full:
        assert (p, "round_trip") not in DIMENSION_SCOPE, (
            "%s 往返是全覆盖，不该有限定标签（会读成「只覆盖一端」）" % p)
    assert "round_trip" in DIMENSIONS, "本门禁的维度锚点失效"


def test_frontend_does_not_hardcode_rt_scope():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "RT_SCOPE_NOTE" not in src, (
        "前端仍留着写死的往返范围表——声明改了它不会跟着改")
    i = src.find('"channels": [')
    assert i > 0, "接口片段锚点失效"
    seg = src[i:i + 900]
    assert "dim_scopes" in seg, (
        "接口没下发 dim_scopes，前端无从拼范围文案（只能退回写死）")


def test_rendered_scope_reaches_both_chip_and_matrix():
    """渲染层：chip 的 title 与矩阵格的 title 都要带范围词。"""
    import socket
    import subprocess
    import time
    import urllib.request

    import pytest

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
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1100})
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                got = pg.evaluate("""async()=>{
                  switchView('cfg');
                  await new Promise(r=>setTimeout(r,2500));
                  const box=document.getElementById('cfgDimMatrix');
                  const rows=[...box.querySelectorAll('tr')];
                  const head=[...rows[0].querySelectorAll('th')]
                    .map(x=>(x.innerText||'').replace(/\\s+/g,' ').trim());
                  const out={};
                  for(const tr of rows){
                    const th=(tr.querySelector('th')||{}).innerText||'';
                    if(!/往返/.test(th))continue;
                    const cells=[...tr.querySelectorAll('td .cell')];
                    for(let i=0;i<cells.length;i++){
                      const t=cells[i].getAttribute('title')||'';
                      if(/飞猪/.test(head[i+1]||''))out.fliggy=t;
                      if(/途牛/.test(head[i+1]||''))out.tuniu=t;
                    }
                  }
                  switchView('search');
                  await new Promise(r=>setTimeout(r,1500));
                  /* 精确取「往返票」那颗：同排还有「关注」chip，
                     按 .chip.schip 取第一个会抓到后者（实测踩到一次）。 */
                  const chip=[...document.querySelectorAll('.chip.schip')]
                    .find(x=>/往返票/.test(x.textContent||''));
                  out.chip=chip?(chip.getAttribute('title')||''):'';
                  return out;
                }""")
            finally:
                b.close()
        assert got.get("fliggy"), "找不到「往返 × 飞猪」格子"
        from core.channels import DIMENSION_SCOPE
        # 范围词从声明取，不把说明的具体措辞钉进测试
        # （说明写「只有国际能出…」，短标签写「仅国际」，说的是同一件事）
        for plat, key in (("fliggy", "fliggy"), ("tuniu", "tuniu")):
            word = DIMENSION_SCOPE[(plat, "round_trip")].strip("仅")
            assert word in got.get(key, ""), (
                "矩阵格悬停没写 %s 的往返范围（缺 %r）：%r"
                % (plat, word, got.get(key, "")[:120]))
        # chip 按**当前航线**给范围：demo 的默认航线是 SHA→SYX（国内），
        # 所以这里只能出现「途牛仅国内」，不能出现「飞猪仅国际」——
        # 国内航线上飞猪没有往返是事实，但它属于「暂无往返数据」那一栏，
        # 范围栏再写一遍「飞猪仅国际」就是文不对题。国际航线的对偶断言
        # 见 test_scope_note_follows_the_route_type。
        assert "仅国内" in got.get("chip", ""), (
            "检索页「往返票」chip 没按航线给范围：%r" % got.get("chip", "")[:200])
        assert "仅国际" not in got.get("chip", ""), (
            "国内航线上不该出现「飞猪仅国际」这种无关提示：%r"
            % got.get("chip", "")[:200])
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def test_scope_note_follows_the_route_type():
    """范围提示必须按**当前航线**收窄，不是把所有渠道的范围堆在一起。

    矩阵一格 `round_trip=y` 只说了「有往返」，`DIMENSION_SCOPE` 说了
    「仅国际/仅国内」，但往返卡是有具体航线的：国内航线上「飞猪仅国际」
    这句提示等于没说；更糟的是旧实现把飞猪同时列进「暂无往返数据」——
    在国内航线上飞猪**确实**没有，但它只覆盖国际这件事被读成了缺陷。
    实测（2026-11-01）：国内航线 miss=「携程、去哪儿网页、飞猪、同程」、
    scope=「途牛仅国内、去哪儿 App仅国内」；国际航线 miss=「携程、去哪儿网页、
    同程、途牛、去哪儿 App」、scope=「飞猪仅国际」——两边的范围词不再交叉。
    去哪儿 App 的范围来自现场：表单设了「往返 + 返程日」，搜索后仍是单程
    国际列表（2026-11-01 SHA→LHR），所以它算「国内才有」。
    """
    import socket
    import subprocess
    import time
    import urllib.request

    import pytest

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
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1100})
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                got = pg.evaluate("""async()=>{
                  switchView('cfg');
                  await new Promise(r=>setTimeout(r,2800));
                  return {
                    intl_sha_can: isIntlCode('CAN'),
                    intl_sha_nrt: isIntlCode('NRT'),
                    dom_miss: _rtNoSupportNames(false),
                    intl_miss: _rtNoSupportNames(true),
                    dom_scope: _rtScopeNote(false),
                    intl_scope: _rtScopeNote(true)
                  };
                }""")
            finally:
                b.close()
        assert got["intl_sha_can"] is False and got["intl_sha_nrt"] is True, (
            "航线类型判定失效，本判据失去锚点：%s" % got)
        assert "飞猪" in got["dom_miss"], (
            "国内航线上飞猪（仅国际）应算「这条航线没有往返」：%r"
            % got["dom_miss"])
        assert "途牛" not in got["dom_miss"], (
            "国内航线上途牛能出往返，不该列进「暂无」：%r" % got["dom_miss"])
        assert "途牛" in got["intl_miss"], (
            "国际航线上途牛（仅国内）应算没有：%r" % got["intl_miss"])
        assert "飞猪" not in got["intl_miss"], (
            "国际航线上飞猪能出往返，不该列进「暂无」：%r" % got["intl_miss"])
        assert "去哪儿 App" in got["intl_miss"], (
            "国际航线上去哪儿 App（仅国内）应算没有：%r" % got["intl_miss"])
        assert "去哪儿 App" not in got["dom_miss"], (
            "国内航线上去哪儿 App 能出往返，不该列进「暂无」：%r"
            % got["dom_miss"])
        assert "途牛仅国内" in got["dom_scope"], (
            "国内航线应提示「途牛仅国内」：%r" % got["dom_scope"])
        assert "去哪儿 App仅国内" in got["dom_scope"], (
            "国内航线应提示「去哪儿 App仅国内」：%r" % got["dom_scope"])
        assert "飞猪仅国际" in got["intl_scope"], (
            "国际航线应提示「飞猪仅国际」：%r" % got["intl_scope"])
        assert "飞猪" not in got["dom_scope"], (
            "国内航线不该出现「飞猪仅国际」这种无关提示：%r" % got["dom_scope"])
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
