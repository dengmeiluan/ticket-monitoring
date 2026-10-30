# -*- coding: utf-8 -*-
"""r515 / GitHub issue #8 #9 #10 的回归契约。

三条都是**用户真实踩到的**（dengmeiluan/ticket-monitoring, 2026-10-29）：

  #9  「默认端口 8765，但我通过反代其他端口后保存航线设置后他会默认
       跳转回 8765，同时保存失败」
      → 旧判据 `GLB.port !== location.port`：反代用户在 443/8080 上访问，
        配置里写着 8765，条件恒成立，保存后浏览器被强制跳到 host:8765
        （代理没这条路由）——表现就是「保存失败 + 跳回 8765」。
        正确判据是「**这次保存真的改了端口**」，且当前就在旧端口上访问。

  #10 「docker 本地构建部署后登录不弹窗，edge/chrome、windows/安卓都试过」
      → `/api/login` 只是起线程就返回 ok=true，前端立刻提示「窗口已弹出」；
        容器里没有图形环境时后台必然失败，用户永远等不到窗口。

  #8  「docker pull ghcr.io/dengmeiluan/ticket-monitoring:latest → denied」
      → 仓库**没有**推送镜像的流水线，这个标签从来不存在；而
        docker-compose.yml 的注释让人以为可以免构建。

每条都钉住「用户看到的那句话」，而不只是代码里有没有某个字符串。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


def test_reverse_proxy_port_save_does_not_hijack_the_browser():
    """#9：反代场景保存配置，不得把地址栏改到用户没访问过的端口。"""
    w = _read("webui.py")
    i = w.index("端口跳转（GitHub #9）")
    seg = w[i:i + 900]
    # 判据必须是「保存前后端口值不同」，而不是「配置值 ≠ 浏览器端口」
    assert "_portBefore" in seg, "没有记录保存前的端口"
    assert "String(_portBefore)===oldPort" in seg, \
        "跳转前没有确认「浏览器当前就在旧端口上」"
    assert "GLB.port||8765)!==oldPort" not in seg, \
        "仍在用「配置值 ≠ 浏览器端口」当跳转判据（反代会恒成立）"


def test_port_before_is_captured_before_the_save_request():
    """#9：`_portBefore` 必须在 fetch 之前取值，否则回读已覆盖它。"""
    w = _read("webui.py")
    i = w.index("const _portBefore=")
    j = w.index("fetch('/api/config'", i - 800)
    assert i < j, "`_portBefore` 取值晚于保存请求（回读会把它改掉）"


def test_port_redirect_still_works_for_the_normal_case():
    """#9 的另一半：本机直连 8765 且真改成 9000 时，仍然要跳过去。

    修反代不能把正常路径一起关掉——这是最容易在「修 bug」时引入的回归。
    用产品自己的表达式在 true 页面上求值，而不是复制一份判断逻辑。
    """
    from playwright.sync_api import sync_playwright
    import json as _json
    from functools import partial
    from http.server import (SimpleHTTPRequestHandler,
                             ThreadingHTTPServer)
    import threading
    import pytest
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r515_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r515t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8994), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    w = _read("webui.py")
    # 从产品源码里取出判定表达式原文，避免测试自说自话
    i = w.index("const _portChanged=")
    expr = w[i:w.index(";", i) + 1]
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context()
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.route("**/*", lambda r: r.fulfill(
                    status=200, content_type="text/html", body="<html></html>"))
                page.goto("http://127.0.0.1:8994/index.html")
                res = page.evaluate(
                    "(src)=>{const _portBefore=src.before;const GLB={port:src.now};"
                    "const oldPort=src.browser;"
                    "return eval(src.expr+';({changed:_portChanged,"
                    "jump:(_portChanged&&String(_portBefore)===oldPort)})');}",
                    {"before": "8765", "now": 9000, "browser": "8765",
                     "expr": expr})
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
    assert res["changed"] is True, res
    assert res["jump"] is True, \
        "本机真改端口时不再跳转（把正常路径关掉了）：%r" % (res,)


def test_login_without_gui_returns_an_actionable_error():
    """#10：没有图形环境时必须同步报错，而不是先提示「窗口已弹出」。"""
    w = _read("webui.py")
    i = w.index("def _start_login(")
    seg = w[i:i + 4200]
    assert "_no_gui" in seg, "没有图形环境预检"
    assert "DISPLAY" in seg and "WAYLAND_DISPLAY" in seg, \
        "没有检查 DISPLAY/WAYLAND_DISPLAY"
    assert '"kind": "no_gui"' in seg, \
        "没有把「无图形环境」作为可区分的错误类型返回"
    # 必须在起线程之前返回：先起线程再报错等于没修。
    # 锚 `def _run()` 而不是 `threading.Thread`——同一函数里线程名也含该串。
    assert seg.index("_no_gui") < seg.index("def _run():"), \
        "预检晚于起线程（用户仍会先看到「已弹出」）"


def test_frontend_says_why_login_cannot_open():
    """#10：前端对 no_gui 要给出可执行指引，且不被 80 字截断。"""
    w = _read("webui.py")
    assert "j.kind==='no_gui'" in w, "前端没有区分 no_gui"
    i = w.index("j.kind==='no_gui'")
    seg = w[i:i + 420]
    assert "图形界面" in seg, "没有说明「没有图形界面」"
    assert "user_data" in seg, "没有给出可执行的替代方案"


def test_compose_image_is_actually_published_by_a_workflow():
    """#8：compose 里写了 ghcr 镜像，工作流就必须真的能把它推上去。

    旧判据只防「注释里暗示存在镜像」；r674 起发行轮真推镜像，判据改成
    正向对账：镜像仓库路径、推送步骤、public 可见性提醒缺一不可——
    否则用户照 compose 拉取又会得到 denied（GitHub 对「不存在/无权限」
    返回同一回执，看不出差别）。
    """
    y = _read("docker-compose.yml")
    assert "build: ." in y, "没有本地构建兜底（无镜像/CI 失败时起不来）"
    assert "image: ghcr.io/dengmeiluan/ticket-monitoring:latest" in y, \
        "compose 没有指向工作流实际推送的镜像路径"
    w = _read(".github/workflows/release-build.yml")
    assert "push_image" in w, "工作流没有推送开关（issue #8 的诉求）"
    assert "packages: write" in w, "没有 packages 权限，推 ghcr 会 403"
    assert "docker push" in w, "没有真正的推送步骤"
    assert "ghcr.io/${{ github.repository }}" in w, \
        "推送路径与 compose 不是同源（仓库改名后会各写各的）"
    assert w.index("docker push") > w.index("if: ${{ inputs.push_image }}"), \
        "推送没有挂在开关上——日常跑 CI 会往包仓库写东西"
    assert "public" in w.lower(), "没有提醒把 package 设为 public"


def test_startup_failure_is_readable_when_launched_by_double_click():
    """#11 同类：发行包双击运行时，启动失败不能一闪而过。"""
    m = _read("main.py")
    i = m.index('if __name__ == "__main__":')
    seg = m[i:i + 1400]
    assert "traceback.print_exc()" in seg, "启动异常没有打印堆栈"
    assert "启动失败" in seg, "没有可读的失败结论"
    assert "isatty" in seg, "没有在可交互终端里停住（窗口会一闪而过）"
