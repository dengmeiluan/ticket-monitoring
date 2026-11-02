# -*- coding: utf-8 -*-
"""r628：演示载荷与真实载荷不许各抄一份 —— 节流开关在演示下曾恒显示「开」。

`/api/config` 有两条路：真实模式逐项回读 config.yaml，演示模式走
`_demo_config_payload()`。后者只手工抄了一部分 globals，**节流六项一个都没有**。
而配置页读 `GLB.x !== false`：

    +glcell('熔断','glbBrk','GLB.breaker_enabled=this.checked',
            GLB.breaker_enabled!==false, ...)

`undefined !== false` 为真 → **永远显示「开」**，哪怕 `_State.cfg` 里关着。
演示站是官方预览面（静态站与本地 --demo 共用这份载荷），等于对外展示
一份与真实行为不符的开关状态。

修法：演示分支也按 `_State.cfg` 回读同一批键（`_demo_pacing_globals()`），
预热名单同样用 `_warmable()` 过滤。
负控：把 `**_demo_pacing_globals()` 从载荷里去掉即红。
"""
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 配置页会读、且 `!== false` 判定的节流开关：缺一个就必然谎报「开」
_REQUIRED = ("warmup_enabled", "breaker_enabled", "health_penalty_enabled",
             "warmup_platforms", "warmable")


def test_demo_payload_contains_pacing_keys():
    """静态：演示载荷必须并入节流六项（不许再手抄漏项）。"""
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("def _demo_config_payload()")
    j = w.index("def ", i + 10)
    body = w[i:j]
    assert "_demo_pacing_globals()" in body, (
        "演示载荷没有再并入节流开关（会重现「恒显示开」）：\n%s" % body[:400])


def test_demo_pacing_globals_has_every_key_and_follows_cfg():
    import webui
    from core.pacing import DEFAULTS
    webui._State.cfg = {"crawler": {
        "warmup": {"enabled": False, "platforms": ["qunar", "ctrip"]},
        "breaker": {"enabled": False},
        "health_penalty_enabled": False,
    }}
    g = webui._demo_pacing_globals()
    for k in _REQUIRED:
        assert k in g, "演示载荷缺 %s（配置页会把它当「开」）" % k
    # 必须跟着 _State.cfg 走，不能写死 True
    assert g["warmup_enabled"] is False, g
    assert g["breaker_enabled"] is False, g
    assert g["health_penalty_enabled"] is False, g
    # 名单：ctrip 没有入口要进 ignored，不能混进可用名单
    assert "ctrip" not in g["warmup_platforms"], g
    assert "ctrip" in g["warmup_ignored"], g
    # 阈值也在（r485 的可配项在演示下同样要能显示真实值）
    assert g["health_ok_ratio"] == DEFAULTS["health_ok_ratio"], g


def test_demo_api_config_reports_disabled_switch():
    """真跑一次：演示服务的 /api/config 必须如实说出「关」。"""
    import pytest
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
            pytest.skip("演示服务未在期限内起来")
        j = json.loads(op.open(base + "/api/config", timeout=20).read().decode("utf-8"))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=6)
        except Exception:
            srv.kill()

    g = j.get("globals") or {}
    missing = [k for k in _REQUIRED if k not in g]
    assert not missing, (
        "演示 /api/config 缺这些键，配置页会把它们一律显示成「开」：%s" % missing)
    assert isinstance(g.get("warmable"), list) and g["warmable"], g
