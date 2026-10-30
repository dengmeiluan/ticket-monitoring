# -*- coding: utf-8 -*-
r"""r675：容器里不能让「保存一次配置」把监听地址钉死成 127.0.0.1。

背景（issue #8/#11 的容器同类）：镜像内置 `ENV TM_WEB_HOST=0.0.0.0`，
`_bind_host()` 的优先级是「config 显式值 > 环境变量 > 127.0.0.1」。但
GET /api/config 的 globals.host 只读文件字面值并缺省成 127.0.0.1：

- 页面显示 127.0.0.1，服务实际绑 0.0.0.0（状态说谎）；
- 更糟的是保存任何配置都会把这个 127.0.0.1 回写 yaml；
- 下次重启容器 → 显式值压过 TM_WEB_HOST → 只绑回环 → `-p 8765:8765`
  端口映射不可达，表现为「容器在跑但网页打不开」。

判据（真起服务 + 真读配置）：
① `_bind_host`：显式值 > 环境变量 > 缺省；
② `_startup_vals`（重启中心的数据源）报的是生效值；
③ GET /api/config 在「文件没写 host + TM_WEB_HOST=0.0.0.0」时报 0.0.0.0；
④ 真保存一次配置后，yaml 里落的是 0.0.0.0，不是 127.0.0.1。

负控：把 GET 的 host 改回「读文件缺省 127.0.0.1」→ ③④ 红。
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bind_host_priority(monkeypatch):
    import webui
    monkeypatch.delenv("TM_WEB_HOST", raising=False)
    assert webui._bind_host({}) == "127.0.0.1"
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    assert webui._bind_host({}) == "0.0.0.0"
    assert webui._bind_host({"web": {}}) == "0.0.0.0"
    # 显式值优先——用户主动指定 0.0.0.0 时不能被环境变量覆盖
    monkeypatch.setenv("TM_WEB_HOST", "127.0.0.1")
    assert webui._bind_host({"web": {"host": "0.0.0.0"}}) == "0.0.0.0"


def test_startup_vals_reports_effective_host(monkeypatch):
    import webui
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    out = webui._startup_vals({"web": {"port": 8765}})
    assert out["host"] == "0.0.0.0", (
        "重启中心拿文件缺省值比较，容器里会造出永远差一项的假待重启")


@pytest.fixture(scope="module")
def live():
    import webui
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="r675_")
    cfg_path = os.path.join(tmp, "c.yaml")
    # 只读样例副本：绝不让探针写仓库里的 config.example.yaml
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg_path)
    old_bind = webui._bind_host
    old_env = os.environ.get("TM_WEB_HOST")
    os.environ["TM_WEB_HOST"] = "0.0.0.0"
    webui.start_web(cfg={"web": {"port": port}}, job=None,
                    report_push=None, config_path=cfg_path)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            op.open(base + "/api/state", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    yield base, cfg_path, op
    if old_env is None:
        os.environ.pop("TM_WEB_HOST", None)
    else:
        os.environ["TM_WEB_HOST"] = old_env
    webui._bind_host = old_bind


def _get(base, path, op):
    with op.open(base + path, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(base, path, body, op):
    req = urllib.request.Request(
        base + path, method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with op.open(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def test_config_page_reports_effective_host(live):
    base, _cfg, op = live
    j = _get(base, "/api/config", op)
    assert j["globals"]["host"] == "0.0.0.0", (
        "容器里页面显示 127.0.0.1，服务实际绑 0.0.0.0——状态说谎")


def test_save_does_not_pin_loopback_into_yaml(live):
    import yaml
    base, cfg, op = live
    j = _get(base, "/api/config", op)
    glb = j["globals"]
    # 模拟用户在网页里改了一个热更新项后保存（原样回传页面拿到的 globals）
    glb["interval_minutes"] = 20
    out = _post(base, "/api/config", {"users": j.get("users") or [],
                                      "globals": glb}, op)
    assert out.get("ok"), out
    with open(cfg, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    host = ((saved.get("web") or {}).get("host") or "")
    assert host == "0.0.0.0", (
        "保存一次配置就把 host=%r 写进 yaml；容器重启后将只绑回环，"
        "端口映射不可达（issue #8 同类的「容器在跑但打不开」）" % host)
