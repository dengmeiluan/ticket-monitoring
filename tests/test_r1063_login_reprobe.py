# -*- coding: utf-8 -*-
"""r1063 T134：登录成功后**立刻自动复探**。

问题：登完只清墙，真正验证要等下一轮调度（可能几分钟）。用户登完就想知道"通没通"。

做法：`_kick_login_probe(plat)` 在 daemon 线程里跑 `_State.probe_cb`，
目标是「浏览器通路 + 同厂商 App 渠道」（`ctrip_h5` → `ctrip` + `app_ctrip`）。
* 不阻塞登录请求（立刻返回 targets）；
* `config.web.login_reprobe: false` 可关；
* 任何异常都吞掉——登录已经是成功路径。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_targets_include_vendor_app_channel(monkeypatch):
    import webui
    calls = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": (calls.append(p) or
                                             {"ok": True, "rows": 1}),
                        raising=False)
    monkeypatch.setattr(webui._State, "cfg", {}, raising=False)
    rep = webui._kick_login_probe("ctrip_h5")
    assert rep["ok"] is True
    assert rep["targets"] == ["ctrip", "app_ctrip"], rep
    time.sleep(0.8)
    assert calls == ["ctrip", "app_ctrip"], calls


def test_respects_config_off(monkeypatch):
    import webui
    calls = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": (calls.append(p) or {"ok": True}),
                        raising=False)
    monkeypatch.setattr(webui._State, "cfg",
                        {"web": {"login_reprobe": False}}, raising=False)
    rep = webui._kick_login_probe("fliggy")
    assert rep["ok"] is False and "关闭" in rep["why"], rep
    time.sleep(0.3)
    assert calls == []


def test_does_not_block(monkeypatch):
    import webui

    def slow(p, scope=""):
        time.sleep(1.5)
        return {"ok": True}

    monkeypatch.setattr(webui._State, "probe_cb", slow, raising=False)
    monkeypatch.setattr(webui._State, "cfg", {}, raising=False)
    t0 = time.time()
    webui._kick_login_probe("ctrip")
    dt = time.time() - t0
    assert dt < 0.5, "登录路径被探针阻塞了：%.2fs" % dt


def test_wired_into_login_success():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index("已清登录墙记忆")
    seg = src[i:i + 500]
    assert "_kick_login_probe" in seg, seg[:300]
