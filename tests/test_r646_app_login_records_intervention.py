# -*- coding: utf-8 -*-
r"""r646：App 登录成功必须入干预账（可溯源 / 干预成功率的前提）。

网页登录保存会话后会写一条 `relogin` 干预（含槽位与端）；而 App 登录
（`/api/app-login/finish`）只在内存里结束——账本里查不到。后果：
- 节流面板的「上次干预 44%→100%」永远不会以 App 重登为分界；
- 干预成功率统计不到 App 这条链路（用户按了、也成功了，却不算数）。

这里走真实 POST 路由 + 打桩 registry（不起真机），断言落库。
负控：去掉记录分支 → 账本为空，本测试红。
"""
import io as _io
import json
import logging
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_app_login_finish_writes_a_relogin_intervention():
    import webui
    from core.storage import PriceStorage

    tmp = tempfile.mkdtemp(prefix="r646t_")
    cfg = os.path.join(tmp, "config.yaml")
    base = {"users": [], "web": {"port": 0, "host": "127.0.0.1"},
            "schedule": {"interval_minutes": 30},
            "output": {"db_path": os.path.join(tmp, "prices.db")}}
    _io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump(base, allow_unicode=True))

    st = webui._State
    st.cfg = dict(base)
    st.boot_cfg = dict(base)
    st.users = []
    st.alerters = []
    st.job = None
    st.report_push = None
    st.reload_cb = None
    st.config_path = cfg
    st.version = "r646"
    st.login_saved_cb = None
    st.logger = logging.getLogger("r646t")
    st.app_login = None
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False

    class _FakeSess:
        status = "pending"

        def finish(self, ok, msg):
            self.status = "done"

    class _FakeReg:
        def __init__(self):
            self.s = _FakeSess()

        def get(self, plat):
            return self.s

        def drop(self, plat):
            pass

    reg = _FakeReg()
    old_reg = webui._app_login_registry
    old_ctx = webui._app_login_ctx
    webui._app_login_registry = lambda: reg
    webui._app_login_ctx = lambda: {
        "packages": {"app_zhixing": "cn.suanya.zhixing"},
        "runtime_factory": lambda: None, "verify": None, "snapshot": None}

    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/app-login/finish" % port,
            data=json.dumps({"plat": "app_zhixing"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
                body = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            code = e.code
            body = json.loads(e.read().decode())
        assert code == 200 and body.get("ok"), (
            "App 登录完成接口没有成功：%s %s" % (code, body))

        rows = PriceStorage(base["output"]["db_path"]).interventions(
            "app_zhixing", 5)
        acts = [(r.get("action"), r.get("scope")) for r in rows]
        assert ("relogin", "app") in acts, (
            "App 登录成功后没有入干预账（不可溯源、干预成功率算不到）：%s"
            % acts)
    finally:
        srv.shutdown()
        srv.server_close()
        webui._app_login_registry = old_reg
        webui._app_login_ctx = old_ctx
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)
