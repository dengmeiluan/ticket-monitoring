# -*- coding: utf-8 -*-
"""r805ai：开了「往返票」却没配返程日，必须报「待完善」。

采集端按 `ret_dates` 逐对跑（`main.py` 遍历 `ret_dates` 调
`crawler.fetch(..., ret_date=...)`），空集合等于**一次都不跑往返**。
但 `toggleRT` 只把 `ret_dates` 置为 `[]` 并 toast「请配置返程日期」，
`_routeIssues` 原先不检查这一项——于是这条航线在概览里显示「完整」，
用户以为往返在跑，实际生产账本一条 TRIP 都不会有。

2026-11-01 生产账本实测佐证：412 条 fetch_paths 里 `entry_path='TRIP'`
**为 0**，而当前 `config.yaml` 的六条航线全部没有 `ret_dates` ——
「界面说开着、实际没采」不是推论，是账本事实。

判据（渲染层）：四种路由形态逐一喂给 `_routeIssues`。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_round_trip_without_return_dates_is_reported_incomplete():
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
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                got = pg.evaluate("""()=>{
                  const base={from:'SHA',to:'CAN',dates:['2026-12-01'],
                              alert_direct:500, alert_transfer:0};
                  const mk=o=>Object.assign({},base,o);
                  return {
                    single: _routeIssues(mk({})),
                    rt_empty: _routeIssues(mk({ret_dates:[]})),
                    rt_one: _routeIssues(mk({ret_dates:['2026-12-05']})),
                    rt_legacy: _routeIssues(mk({ret_date:'2026-12-05'}))
                  };
                }""")
            finally:
                b.close()
        assert not errs, "页面报错：%s" % errs[:3]
        assert got["single"] == [], (
            "单程航线不该报任何待完善项：%s" % got["single"])
        assert any("往返" in x for x in got["rt_empty"]), (
            "开了往返但没配返程日，必须报「待完善」——否则界面说在跑、"
            "账本一条 TRIP 都不会有：%s" % got["rt_empty"])
        assert got["rt_one"] == [], (
            "配了返程日就不该再报：%s" % got["rt_one"])
        assert got["rt_legacy"] == [], (
            "legacy 单值 ret_date 也是有效返程配置，不该报：%s"
            % got["rt_legacy"])
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
