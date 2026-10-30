# -*- coding: utf-8 -*-
"""r613：配置页的渠道勾选必须覆盖**全部已注册渠道**，含 App 渠道。

`app_zhixing` 早已是正式渠道：`crawlers/__init__.py` 的 `REGISTRY`、
`core/health.py` 的健康日志正则、`core/channel_alert.py` 的告警名映射里
都有它；模块注释也写明「App 渠道必须显式加进用户 `platforms:` 才会被实例化」。

但配置页的渠道勾选来自 `PLATS`（只有 5 家浏览器渠道），用户**没有任何入口**
把 `app_zhixing` 加进自己的 `platforms`——只能手改 config.yaml。
这与「配置页面不允许存在任何无法配置的项」直接冲突。

修法：在渠道勾选行末尾补一个 App 渠道 chip，title 里点明它依赖
「全局参数 · Android 真机通道」总开关（那是另一组配置，避免让人误以为
勾了就会跑）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_app_channel_is_selectable():
    """App 渠道 chip 由 APP_PLAT_NAME 派生（r665 起不再逐个写死）。"""
    w = _w()
    i = w.index("chip pch p-${p}")
    seg = w[i:i + 900]
    assert "APP_PLAT_NAME" in seg and "p-${p}" in seg, (
        "App 渠道 chip 应通过 APP_PLAT_NAME 派生：%s" % seg[:200])
    assert "togPlat(${i},'${p}',this)" in seg, (
        "App 渠道 chip 没有接到 togPlat（点了不会写 platforms）")


def test_app_chip_states_its_dependency():
    """必须点明依赖 Android 总开关，否则用户勾了却不跑，无从判断。"""
    w = _w()
    i = w.index("title=\"真机采集（${APP_PLAT_NAME[p]}）")
    seg = w[i:i + 300]
    assert "Android" in seg and "总开关" in seg, (
        "App 渠道 chip 没说明它依赖 Android 真机通道总开关：%s" % seg[:120])


def test_every_registry_channel_has_a_chip():
    """REGISTRY 里的每个渠道都要能在页面上勾选——这是通用不变式。"""
    import sys
    sys.path.insert(0, ROOT)
    from crawlers import REGISTRY
    w = _w()
    i = w.index("chip pch p-${p}")
    seg = w[i:i + 900]
    # 渠道 chip 有两个来源：`PLATS` 动态表（p-${p}）与
    # `APP_PLAT_NAME` 动态表（同样 p-${p}，App 渠道走这个）。
    # 两张表都是从源码解析出来的真实键，不是写死清单。
    dyn = set()
    k = w.index("const PLATS={")
    for part in w[k:w.index("}", k)].split(","):
        if ":" in part:
            dyn.add(part.split(":", 1)[0].strip().split()[-1].strip("'\""))
    ak = w.index("const APP_PLAT_NAME={")
    body = w[ak:w.index("};", ak)]
    for part in body.split("{", 1)[1].split(","):
        if ":" in part:
            dyn.add(part.split(":", 1)[0].strip().strip("'\""))
    missing = [c for c in REGISTRY
               if c not in dyn and ("p-" + c) not in seg and ("'%s'" % c) not in seg]
    assert not missing, "这些已注册渠道在页面上勾不到：%s" % missing


def test_renders_all_chips_and_toggles():
    """真渲染：每个已注册渠道都有一枚可点 chip，且点了真的写进 CFG.platforms。

    不再断言"恰好 6 个"——渠道数随接入增加（r665 加了去哪儿 App），
    写死数量会让「加渠道」本身变成红灯。判据改为：REGISTRY 里每个渠道
    都能在 DOM 里找到对应 chip，且至少对**每个 App 渠道**做一次
    开→关往返。
    """
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    sys.path.insert(0, ROOT)
    from crawlers import REGISTRY

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
    try:
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                op.open(base + "/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            import os as _os
            if not _os.path.exists(p.chromium.executable_path):
                import pytest
                pytest.skip("chromium 二进制缺失")
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 1000})
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="users"]');if(c)c.click()}""")
            pg.wait_for_timeout(900)
            pg.evaluate("()=>{try{setOpenUser([0])}catch(e){};buildForm()}")
            pg.wait_for_timeout(900)
            got = pg.evaluate("""(want)=>{
              const chips=[...document.querySelectorAll('#cfgform .chip.pch')];
              const res={n:chips.length,missing:[],tog:[]};
              for(const w of want){
                const chip=chips.find(c=>String(c.className)
                  .indexOf('p-'+w)>=0);
                if(!chip){res.missing.push(w);continue}
                const before=(CFG[0].platforms||[]).slice();
                chip.click();
                const after=(CFG[0].platforms||[]).slice();
                chip.click();
                const back=(CFG[0].platforms||[]).slice();
                res.tog.push({p:w,before:before,after:after,back:back});
              }
              return res}""",
                          [c for c in REGISTRY if c.startswith("app_")])
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert not got["missing"], "这些已注册渠道没有渲染 chip：%s" % got["missing"]
    assert got["n"] >= len(REGISTRY), (
        "渠道勾选数量少于已注册渠道数：%d < %d" % (got["n"], len(REGISTRY)))
    assert got["tog"], "没有 App 渠道可供往返测试"
    for t in got["tog"]:
        assert t["p"] in t["after"], "%s 点了没写进 platforms：%s" % (
            t["p"], t)
        assert t["p"] not in t["back"], "%s 再点没能取消：%s" % (t["p"], t)
