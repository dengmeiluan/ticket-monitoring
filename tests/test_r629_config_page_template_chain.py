# -*- coding: utf-8 -*-
"""r629：配置页「用户与航线」整页渲染不出来（模板链断了）。

现象：打开配置页 → 「用户与航线」面板只显示
`配置读取失败: TypeError: Object.keys(...).map(...).join(...) is not a function`，
航线行、心理价、渠道 chip 全部消失——**用户无法配置任何东西**。

根因不在 `Object.keys`：构建渠道 chip 的模板链在
`Object.keys(PLATS).map(...).join('')` 之后**丢了 `+`**：

    h+=`...<div class="sctl">`+
       Object.keys(PLATS).map(p=>`...`).join('')      ← 这里缺 `+`
       `<span class="chip pch p-app_zhixing...">`     ← 新模板当成了独立语句

于是 `.join('')` 的返回值没被拼上，而后面的模板串成了游离表达式；
更糟的是整段的解析结果让浏览器在运行期抛 `join is not a function`，
`loadCfg` 的 catch 把它显示成「配置读取失败」，**整页空白**。

这是并行会话提交「智行 App chip 可勾选」时插入新模板漏掉的连接符。
判据必须是**真渲染**：静态搜字符串看不出缺 `+`（试过一版静态正则，
中间夹着注释行、维护成本高且易假红，已删，只留渲染判据）。

负控：把 `+` 去掉 → `test_r601` 的「总阈值控件可见」立刻红。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_config_page_renders_route_rows():
    """真渲染：配置页必须渲染出航线行与「总阈值」控件。

    这条是 r629 的核心判据——缺口号时整页空白，但源码里每个词都在。
    """
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        ok = False
        for _ in range(140):
            try:
                op.open(base + "/api/state", timeout=1); ok = True; break
            except Exception:
                time.sleep(0.25)
        if not ok:
            import pytest
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                import pytest
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="users"]');if(c)c.click()}""")
            pg.wait_for_timeout(1200)
            got = pg.evaluate("""()=>({
              rows: document.querySelectorAll('.rline').length,
              thr: [...document.querySelectorAll('input')]
                    .filter(e=>/alert_threshold/.test(
                      e.getAttribute('onchange')||'')).length,
              err: (document.getElementById('panel-users')||{}).innerText||''})""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert "配置读取失败" not in got["err"], (
        "配置页渲染报错（模板链断裂时的典型表现）：%s" % got["err"][:160])
    assert got["rows"] > 0, "配置页没有渲染出任何航线行：%s" % got
    assert got["thr"] > 0, "配置页没有渲染出「总阈值」控件：%s" % got
    assert not errs, "页面抛错：%s" % errs[:3]
