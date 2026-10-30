# -*- coding: utf-8 -*-
r"""r672：前端每一个写端点，都不能被我们自己的安全闸门拦掉。

r671 给 `_do_POST` 加了跨站闸门（Origin 不同源 → 403，带 body 非 JSON →
415）。这类闸门最容易犯的错不是「拦不住」，而是**把产品自己的请求也拦了**：
r671 第一版就因为 `fetch(path,{method:'POST'})` 不带 body、浏览器自动补
`Content-Type: text/plain`，把「打开文件夹 / 测试弹窗 / 立即扫描 / 重启」
全打成 415。

所以判据不看「闸门写没写对」，而是**从前端源码里把端点清单派生出来，在真实
浏览器里逐个打一遍**，只允许「被路由处理了」的响应，不允许 403/415：
- 403 = 被跨站闸门误判（同源请求不该出现）；
- 415 = 被 Content-Type 判据误伤。

允许的响应：200 / 400 / 404 / 409 / 500（业务层拒绝或未接 job），
这些都是「进了业务逻辑」的证据。新增端点自动纳入，不用改这条测试。
"""
import io
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BLOCKED = (403, 415)


def _endpoints():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                  newline="").read()
    eps = set()
    for m in re.finditer(r"fetch\('(/api/[^']*)',\s*\{\s*method:\s*'POST'",
                         src):
        eps.add(m.group(1))
    # 拼接式：fetch('/api/'+act, {method:'POST'}) —— 取 act 的全部字面量
    for m in re.finditer(r"fetch\('/api/'\+act,\s*\{\s*method:\s*'POST'", src):
        for lit in re.finditer(r"act\s*=\s*'([a-z-]+)'", src):
            eps.add("/api/" + lit.group(1))
    return sorted(eps)


def test_endpoint_census_is_not_empty():
    eps = _endpoints()
    assert len(eps) >= 20, "端点清单只扫到 %d 个，判据失效：%s" % (len(eps), eps)


@pytest.fixture(scope="module")
def live():
    import shutil
    import socket
    import tempfile
    import time
    import urllib.request

    import webui

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp(prefix="r672_")
    cfg = os.path.join(tmp, "c.yaml")
    # 复制到临时目录：任何写配置的端点都不许碰仓库里的配置文件
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg)
    webui._bind_host = lambda c: "127.0.0.1"
    webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                    job=None, report_push=None, config_path=cfg)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(160):
        try:
            op.open(base + "/api/state", timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip("控制台未在期限内起来")
    yield base
    shutil.rmtree(tmp, ignore_errors=True)


def test_no_endpoint_is_blocked_by_our_own_guard(live):
    from playwright.sync_api import sync_playwright

    eps = _endpoints()
    if not os.path.exists(
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "ms-playwright")):
        pytest.skip("chromium 二进制缺失")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page()
            pg.set_default_timeout(20000)
            pg.goto(live)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=30000)
            # 两种真实调用形态都要验：
            # ① 无 body（浏览器自动补 text/plain）——r671b 的回归就是这一类；
            # ② 带 JSON body（绝大多数写接口的真实形态）。
            res = pg.evaluate("""async (eps)=>{
              const out={};
              for(const p of eps){
                try{
                  const r=await fetch(p,{method:'POST'});
                  out[p+' #nobody']=r.status;
                }catch(e){ out[p+' #nobody']='ERR'; }
                try{
                  const r=await fetch(p,{method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:'{}'});
                  out[p+' #json']=r.status;
                }catch(e){ out[p+' #json']='ERR'; }
              }
              return out;}""", eps)
        finally:
            b.close()
    blocked = {p: s for p, s in res.items() if s in BLOCKED}
    assert not blocked, (
        "这些写端点被自家闸门拦掉了（同源请求不该 403/415）：%s" % blocked)
