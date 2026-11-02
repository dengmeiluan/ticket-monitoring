# -*- coding: utf-8 -*-
r"""r649：并发保存配置不得丢更新。

`/api/config` 是「读 yaml → 改 → 写 yaml」的读改写序列。服务端是
`ThreadingHTTPServer`，两个并发保存会各自读同一份旧 cfg、各自改一项、
再各自整份写回 —— 后写的把先写的覆盖掉。实测：

    两次 POST 都返回 200，但 3 次里有 2 次只有一项生效
    （A 改轮询周期=47、B 改 TTL=33，最终 interval_minutes 仍是 30）

用户看到「保存成功」，配置已被回滚。同一把锁还要覆盖到热重载：否则
重载可能读到别人写了一半的 yaml。

更严重的后果（负控实测）：没有锁时并发写还会**把 yaml 写坏** ——
两个线程同时 `open(..., "w")` 再 dump，文件被交错截断，
报 `expected <block end>, but found '{'`，下次启动直接读不出配置。

判据是行为：两个线程同时 POST 不同字段，落盘后**两项都必须存在**，
且文件必须仍是合法 yaml。
负控：把锁换成 `contextlib.nullcontext()`（结构不变、只去掉互斥）→
必现写坏/丢更新，本测试红。
"""
import io as _io
import json
import logging
import os
import sys
import tempfile
import threading
import urllib.request

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _run_once(tries=6):
    """返回 (成功次数, 总次数)：两项都留下的次数。"""
    import webui

    tmp = tempfile.mkdtemp(prefix="r649t_")
    cfg = os.path.join(tmp, "config.yaml")
    base = {"users": [], "web": {"port": 0, "host": "127.0.0.1"},
            "schedule": {"interval_minutes": 30}}
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
    st.version = "r649"
    st.login_saved_cb = None
    st.logger = logging.getLogger("r649t")
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False

    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    port = srv.server_address[1]
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/api/config" % port

    def post(payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except Exception as e:                     # noqa: BLE001
            return "ERR:%s" % e

    ok = 0
    try:
        for _ in range(tries):
            ths = [threading.Thread(target=post, args=(p,)) for p in (
                {"users": [], "globals": {"interval_minutes": 47}},
                {"users": [], "globals": {"fast_ttl_min": 33}})]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            saved = yaml.safe_load(_io.open(cfg, encoding="utf-8"))
            sc = saved.get("schedule") or {}
            if sc.get("interval_minutes") == 47 and sc.get("fast_ttl_min") == 33:
                ok += 1
            # 复位，下一轮从干净状态开始
            _io.open(cfg, "w", encoding="utf-8").write(
                yaml.safe_dump(base, allow_unicode=True))
    finally:
        srv.shutdown()
        srv.server_close()
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)
    return ok, tries


def test_concurrent_saves_do_not_lose_updates():
    ok, tries = _run_once()
    assert ok == tries, (
        "并发保存丢更新：%d/%d 轮两项都在（其余轮次有一项被覆盖，"
        "但两次都返回了 200）" % (ok, tries))
