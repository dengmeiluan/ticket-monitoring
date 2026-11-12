# -*- coding: utf-8 -*-
"""r1063 T64：App 版本与改版侦测（用户实测：智行今天升级到 10.26.2）。

回答两个问题：
1. **它升级了吗** —— `dumpsys package` 的 versionName/versionCode/lastUpdateTime，
   与上次快照比对 → 变了记 `app_upgrade`（带旧→新）；
2. **规则是不是失效了** —— 连续 N 轮「0 行 + 认不出页面」→ 记 `app_layout`（疑似改版）。

真机实测（2026-11-08 08:56）：智行 10.26.2 / 飞猪 10.0.10.104 / 去哪儿 10.4.24 /
同程 11.5.2 / 携程 8.97.0，五个包全读到。
"""
import io
import json
import os
import tempfile

import pytest

from core.android import appversion as av


class _Dev:
    """假设备：只实现 `_sh("shell", cmd)`（与真实 AdbDevice 同形状）。"""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def _sh(self, *args, timeout=None):
        self.calls.append(" ".join(str(a) for a in args))
        cmd = " ".join(str(a) for a in args)
        for pkg, txt in self.table.items():
            if pkg in cmd:
                return txt
        return ""


def _dumpsys(name, code, upd="2026-11-08 08:54:18"):
    return ("Packages:\n  Package [com.x]:\n"
            "    versionCode=%d minSdk=24 targetSdk=30\n"
            "    versionName=%s\n"
            "    lastUpdateTime=%s\n" % (code, name, upd))


def test_reads_versions_from_dumpsys():
    dev = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.2", 710262),
                "com.taobao.trip": _dumpsys("10.0.10.104", 8100723)})
    got = av.read_versions(dev, ["cn.suanya.zhixing", "com.taobao.trip",
                                 "com.nonexistent"])
    assert got["cn.suanya.zhixing"]["name"] == "10.26.2"
    assert got["cn.suanya.zhixing"]["code"] == 710262
    assert got["cn.suanya.zhixing"]["updated"].startswith("2026-11-08")
    assert "com.nonexistent" not in got, "查不到的包不能凭空记录"
    assert any("dumpsys package" in c for c in dev.calls)


def test_first_run_only_records_a_baseline():
    d = tempfile.mkdtemp()
    dev = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.2", 710262)})
    rep = av.check(dev, ["cn.suanya.zhixing"], root=d,
                   plat_of=lambda p: "app_zhixing")
    assert rep["ok"] and rep["changed"] == {}, "首次记录不算升级"
    assert os.path.exists(av._state_path(d))


def test_upgrade_is_detected_and_recorded():
    d = tempfile.mkdtemp()
    old = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.1", 710261)})
    av.check(old, ["cn.suanya.zhixing"], root=d)
    new = _Dev({"cn.suanya.zhixing": _dumpsys("10.26.2", 710262)})
    rep = av.check(new, ["cn.suanya.zhixing"], root=d,
                   plat_of=lambda p: "app_zhixing")
    assert list(rep["changed"]) == ["cn.suanya.zhixing"], rep
    ch = rep["changed"]["cn.suanya.zhixing"]
    assert ch["old"]["name"] == "10.26.1" and ch["new"]["name"] == "10.26.2"
    from core import degraded as dg
    snap = dg.snapshot()
    assert "app_upgrade" in snap, snap
    assert "10.26.1 → 10.26.2" in snap["app_upgrade"]["last"]
    dg.reset()


def test_layout_risk_needs_two_consecutive_bad_rounds():
    d = tempfile.mkdtemp()
    assert av.note_layout_risk("app_zhixing", rows=0, path="unknown",
                               root=d) is False
    assert av.note_layout_risk("app_zhixing", rows=0, path="unknown",
                               root=d) is True
    from core import degraded as dg
    assert "app_layout" in dg.snapshot()
    dg.reset()


def test_layout_risk_clears_when_data_comes_back():
    d = tempfile.mkdtemp()
    av.note_layout_risk("app_zhixing", rows=0, path="unknown", root=d)
    av.note_layout_risk("app_zhixing", rows=3, path="航班明细", root=d)
    # 计数应被清零：再来一次"坏轮"只是第 1 次
    assert av.note_layout_risk("app_zhixing", rows=0, path="unknown",
                               root=d) is False


def test_broken_state_file_never_raises():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "device"), exist_ok=True)
    with open(av._state_path(d), "w", encoding="utf-8") as f:
        f.write("{ 不是 json")
    dev = _Dev({"com.x": _dumpsys("1.0", 1)})
    rep = av.check(dev, ["com.x"], root=d)
    assert rep["ok"], rep
    with open(av._state_path(d), encoding="utf-8") as f:
        json.load(f)                    # 已被重写成合法 JSON


def test_main_and_setup_are_wired():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
    setup = io.open(os.path.join(root, "core", "setup_check.py"),
                    encoding="utf-8").read()
    assert "appversion" in main and "note_layout_risk" in main
    assert "AndroidRuntime" in setup, "自检必须走真实设备层（别再误报没连到设备）"
    assert "launch_emulator" in setup and "restart_emulator" in setup


def test_emulator_module_exposes_lifecycle():
    from core.android import emulator as em
    for fn in ("status", "ensure_running", "restart"):
        assert callable(getattr(em, fn, None)), fn

_UI_OK = ('<hierarchy><node text="机票"/><node text="出发"/><node text="到达"/>'
          '<node text="搜索"/><node text="往返"/><node text="国内"/>'
          '<node text="国际"/></hierarchy>')
_UI_BAD = ('<hierarchy><node text="酒店"/><node text="火车票"/>'
           '<node text="我的"/></hierarchy>')


def test_probe_anchors_reports_hit_rate():
    """升级后"界面还认不认得"要能量出来（真机：智行 10.26.2 命中 7/7）。"""
    ok = av.probe_anchors(None, "app_zhixing", xml=_UI_OK)
    assert ok["rate"] == 1.0 and ok["missing"] == [], ok
    bad = av.probe_anchors(None, "app_zhixing", xml=_UI_BAD)
    assert bad["rate"] < 0.6 and bad["missing"], bad
    from core import degraded as dg
    assert "app_layout" in dg.snapshot(), "命中率太低要记疑似改版"
    dg.reset()


def test_probe_anchors_handles_empty_tree():
    rep = av.probe_anchors(None, "app_zhixing", xml="")
    assert rep["ok"] is False and "UI" in str(rep.get("why") or "")


def test_probe_uses_content_desc_too():
    xml = ('<hierarchy><node content-desc="机票"/><node content-desc="出发"/>'
           '<node content-desc="到达"/><node content-desc="搜索"/>'
           '<node content-desc="往返"/><node content-desc="国内"/>'
           '<node content-desc="国际"/></hierarchy>')
    assert av.probe_anchors(None, "app_zhixing", xml=xml)["rate"] == 1.0
