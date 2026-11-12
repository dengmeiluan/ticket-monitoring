# -*- coding: utf-8 -*-
"""r616：整页脚本必须真的能跑起来——每个视图/子页签零 pageerror。

r614 把 `const APP_PLAT_NAME=…` 写进了 `renderHealth()` 的函数体（缩进 0，
肉眼看像顶层），而另外三处（`PCN`、节流面板 `CN`、`appPlatName`）在顶层读它。
结果：整页只抛 `APP_PLAT_NAME is not defined`，`S` 永远不初始化，
全站白屏。而当时 r613/r614/r615 共 11 条断言**全绿**——它们都是静态
字符串检查，源码里那句声明好端端地在那里。

**静态断言测不到「这行代码在哪个作用域」。** 本文件把判据钉在运行时：
真开页面、走遍三个视图与所有子页签，pageerror 必须为 0，且 `S` 必须
是对象、`APP_PLAT_NAME` 必须在顶层可读。

判据强度：把 `const APP_PLAT_NAME` 挪回 `renderHealth()` 体内即整份红。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 三个视图 + 监控页六个子页签 + 配置页三个子页签
_VIEWS = [
    ("mon", "overview"), ("mon", "specials"), ("mon", "trend"),
    ("mon", "watch"), ("mon", "details"), ("mon", "health"),
    ("search", None),
    ("cfg", "login"), ("cfg", "users"), ("cfg", "globals"),
]


def _boot():
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
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            return srv, base
        except Exception:
            time.sleep(0.3)
    srv.kill()
    raise AssertionError("webui 未在 60s 内启动")


def test_every_view_runs_without_page_error():
    import pytest
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if not os.path.exists(p.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base)
            try:
                pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                     timeout=25000)
            except Exception:
                pass
            boot = pg.evaluate("""()=>({
              S: typeof S,
              users: (typeof S==='object'&&S&&S.users)?S.users.length:-1,
              apn: typeof APP_PLAT_NAME,
              apnZhixing: (typeof APP_PLAT_NAME==='object'&&APP_PLAT_NAME)
                          ?APP_PLAT_NAME.app_zhixing:null})""")

            walked, failed = [], []
            for view, tab in _VIEWS:
                before = len(errs)
                pg.evaluate("""([v,t])=>{
                  if(typeof switchView==='function')switchView(v);
                  if(t&&typeof showMonTab==='function')showMonTab(t);
                  if(t&&v==='cfg'){
                    const c=document.querySelector(
                      '#cfgnav .cnav[data-p="'+t+'"]');
                    if(c)c.click();}}""", [view, tab])
                pg.wait_for_timeout(450)
                walked.append("%s/%s" % (view, tab))
                if len(errs) > before:
                    failed.append("%s/%s → %s" % (view, tab, errs[before]))
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert boot["S"] == "object", (
        "整页脚本没跑起来（S=%s），首个错误：%s" % (boot["S"], errs[:3]))
    assert boot["users"] >= 1, "S.users 为空：%s" % boot
    assert boot["apn"] == "object", (
        "APP_PLAT_NAME 在顶层不可读（typeof=%s）——很可能又被写进了"
        "某个函数体内：%s" % (boot["apn"], errs[:3]))
    assert boot["apnZhixing"], "APP_PLAT_NAME.app_zhixing 丢失：%s" % boot
    assert not errs, "页面抛错 %d 条（走查 %d 个视图）：%s" % (
        len(errs), len(walked), errs[:5])
    assert not failed, "以下视图切换触发新错误：%s" % failed


def test_app_plat_name_declared_at_top_level():
    """静态旁证：声明行的缩进必须为 0（顶层不是函数体）。

    运行时判据在主测试；这条只防「缩进 0 却仍在函数里」之外的常见笔误，
    并给出比 pageerror 更容易定位的报错。
    """
    import io
    import re
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    m = re.search(r"^(\s*)const APP_PLAT_NAME=", w, re.M)
    assert m, "找不到 APP_PLAT_NAME 声明"
    assert m.group(1) == "", (
        "APP_PLAT_NAME 声明有 %d 个空格缩进——顶层 const 应顶格"
        % len(m.group(1)))
