# -*- coding: utf-8 -*-
"""r1063 T80：UI 取树提速——优先 u2 并复用连接。

真机实测（MuMu，同一屏）：

| 方式 | 单次耗时 |
|---|---|
| CLI（rm + uiautomator dump + cat） | **2.1–3.1s** |
| u2（每次重连） | 0.54s |
| u2（**复用连接**，本次改动） | **0.07s** |

一次采集要取树 5–6 次，所以这是整轮最大的固定成本：

* 改前整轮 **42.5s**
* 改后整轮 **18.6 / 19.2s**（两次真机，数据都对：MU5185 ¥334、MU5165 ¥333）

**新鲜度必须验证**（否则就是"在旧界面上盲点"，比慢更糟）：
打开通知栏后 dump 立刻变化（0.04s 内），哈希与原屏不同 → 是真取，不是缓存。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.device import AdbDevice  # noqa: E402


def _dev(**kw):
    d = object.__new__(AdbDevice)
    d.adb_path = ""
    d.serial = "1.2.3.4:5555"
    d.timeout = 5
    d.last_error = ""
    d._u2_conn = None
    d._u2_first = True
    d._prefer_u2 = False
    d.calls = []
    d._sh = lambda *a, **_k: (d.calls.append(a), "")[1]
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_dump_prefers_u2_and_reuses_connection():
    d = _dev()
    connects = []
    xml = "<hierarchy><node text=\"x\"/></hierarchy>"

    class _Conn:
        def dump_hierarchy(self):
            return xml

    def _fake_u2_device():
        if d._u2_conn is None:
            connects.append(1)
            d._u2_conn = _Conn()
        return d._u2_conn

    d._u2_device = _fake_u2_device
    assert d.dump() == xml
    assert d.dump() == xml
    assert d.dump() == xml
    assert len(connects) == 1, "连接必须复用（实测省下的正是连接开销）"
    assert not d.calls, "u2 可用时不该再去跑 CLI"


def test_falls_back_to_cli_when_u2_unavailable():
    d = _dev()
    d.dump_u2 = lambda: ""
    d.dump()
    assert any("uiautomator" in " ".join(a) for a in d.calls), d.calls
    assert d._u2_first is False, "u2 不可用后本会话不再每轮白试"


def test_u2_connection_is_dropped_on_error():
    d = _dev()

    class _Boom:
        def dump_hierarchy(self):
            raise RuntimeError("agent 挂了")

    d._u2_conn = _Boom()
    d._u2_device = lambda: d._u2_conn
    assert d.dump_u2() == ""
    assert d._u2_conn is None, "坏连接必须丢掉，下一轮重建"
    assert "u2 dump" in d.last_error


def test_u2_dump_rejects_non_hierarchy():
    d = _dev()

    class _Junk:
        def dump_hierarchy(self):
            return "not xml"

    d._u2_conn = _Junk()
    d._u2_device = lambda: d._u2_conn
    assert d.dump_u2() == ""


def test_source_keeps_cli_path_intact():
    """CLI 老路径必须一字不动地留着（u2 在不支持的设备上要能兜住）。"""
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "core", "android", "device.py"), encoding="utf-8").read()
    assert "uiautomator\", \"dump\"" in src
    assert "_u2_first" in src and "_u2_conn" in src
