# -*- coding: utf-8 -*-
"""r193c：/api/state SWR 快照磁盘化——重启后首屏零等待。

冷构建即便从 222s 修到 ~26s，服务刚起时首个控制台请求仍要干等
（`_latest_state` 冷启动首建分支是**同步**等待，最多 300s）。把
「上一轮已发布快照」落盘、启动时恢复 = stale-while-revalidate 的
磁盘版：重启后首屏立即拿上次数据，后台按现行签名重建换新。

`_latest_state` 既有语义一字不改——只是 payload 不再随进程丢失。
"""

import gzip
import json
import os
import tempfile
import time


def _w():
    import webui
    return webui


class _Sandbox:
    """把 _State.cfg 指向临时库，用完还原模块级缓存/旗标。"""

    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.td.name, "t.db")
        with open(self.db, "wb"):
            pass

    def __enter__(self):
        w = _w()
        self.w = w
        self.old_cfg = w._State.cfg
        self.old_ver = w._State.version
        self.saved = {k: w._STATE_CACHE[k] for k in w._STATE_CACHE}
        self.saved_once = w._STATE_DISK_ONCE["on"]
        w._State.cfg = {"output": {"db_path": self.db}}
        for k in w._STATE_CACHE:
            w._STATE_CACHE[k] = None
        w._STATE_DISK_ONCE["on"] = False
        return self

    def __exit__(self, *a):
        w = self.w
        w._State.cfg = self.old_cfg
        w._State.version = self.old_ver
        for k, v in self.saved.items():
            w._STATE_CACHE[k] = v
        w._STATE_DISK_ONCE["on"] = self.saved_once
        self.td.cleanup()


def _payload():
    return {"updated": "2026-09-24 19:00", "version": "1.7.0",
            "users": [{"name": "邓美銮", "flights": [{"price": 1980}]}]}


def _body(p):
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


class TestSourcePins:
    def _src(self):
        return open(_w().__file__, encoding="utf-8").read()

    def test_latest_state_restores_before_signature(self):
        """恢复必须先于签名比对：命中同签名时连重建都省掉。"""
        src = self._src()
        i0 = src.index("def _latest_state():")
        i1 = src.index("def _latest_state_snap():")
        seg = src[i0:i1]
        assert "_state_restore_once()" in seg, "_latest_state 未接磁盘快照恢复"
        assert seg.index("_state_restore_once()") < seg.index("_state_signature()"), \
            "恢复必须发生在签名计算之前"

    def test_build_state_persists(self):
        src = self._src()
        i0 = src.index("def _build_state(sig):")
        i1 = src.index("def _state_rebuild_async():")
        seg = src[i0:i1]
        assert "_state_persist(" in seg, "发布快照后未落盘"

    def test_persist_is_atomic(self):
        """单文件原子替换：避免 meta/body 两份文件撕裂。"""
        src = self._src()
        i0 = src.index("def _state_persist(")
        i1 = src.index("def _state_restore(", i0)
        seg = src[i0:i1]
        assert "os.replace(" in seg, "落盘未用原子替换"

    def test_restore_is_best_effort(self):
        """恢复路径必须整体 try 包裹：坏文件不得让控制台起不来。"""
        src = self._src()
        i0 = src.index("def _state_restore():")
        i1 = src.index("def _state_restore_once(", i0)
        seg = src[i0:i1]
        assert "except Exception" in seg, "恢复未做异常兜底"


class TestRoundTrip:
    def test_persist_then_restore(self):
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            gz = gzip.compress(body, 6)
            sig = (sb.db, 111, 222, 333, "1.7.0")
            w._state_persist(sig, body, '"e1"', gz)
            assert os.path.exists(w._state_cache_path()), "快照未落盘"

            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._state_restore()

            assert w._STATE_CACHE["payload"] == p
            assert w._STATE_CACHE["sig"] == sig, "签名须还原为可比较的 tuple"
            assert isinstance(w._STATE_CACHE["sig"], tuple)
            assert w._STATE_CACHE["etag"] == '"e1"'
            assert w._STATE_CACHE["body"] == body
            assert w._STATE_CACHE["gz"] == gz

    def test_restore_does_not_clobber_live_cache(self):
        """已有活缓存（本进程已构建）时恢复不得覆盖。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            w._state_persist((sb.db, 1, 2, 3, "v"), body, '"e"',
                             gzip.compress(body, 6))
            live = {"updated": "fresh"}
            w._STATE_CACHE["payload"] = live
            w._STATE_CACHE["sig"] = ("live",)
            w._state_restore()
            assert w._STATE_CACHE["payload"] == live
            assert w._STATE_CACHE["sig"] == ("live",)

    def test_corrupt_file_is_ignored(self):
        """垃圾内容 → 静默丢弃，缓存保持空（不抛、不半填充）。"""
        with _Sandbox() as sb:
            w = sb.w
            with open(w._state_cache_path(), "wb") as f:
                f.write(b"\x00garbage-not-a-snapshot")
            w._state_restore()
            assert w._STATE_CACHE["payload"] is None

    def test_missing_file_is_noop(self):
        with _Sandbox() as sb:
            sb.w._state_restore()
            assert sb.w._STATE_CACHE["payload"] is None

    def test_stale_snapshot_dropped(self):
        """超 TTL 的快照不恢复（避免展示数天前的价格）。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            meta = json.dumps({"sig": [sb.db, 1, 2, 3, "v"], "etag": '"e"',
                               "ts": time.time() - w._STATE_CACHE_TTL - 60},
                              ensure_ascii=False).encode("utf-8")
            gz = gzip.compress(body, 6)
            with open(w._state_cache_path(), "wb") as f:
                f.write(w._STATE_CACHE_MAGIC + len(meta).to_bytes(4, "big")
                        + meta + gz)
            w._state_restore()
            assert w._STATE_CACHE["payload"] is None, "过期快照应被丢弃"

    def test_version_mismatch_dropped(self):
        """跨版本快照结构可能已变 → 一律不认（升级后首请求慢一次）。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            w._State.version = "vA"
            w._state_persist((sb.db, 1, 2, 3, "vA"), body, '"e"',
                             gzip.compress(body, 6))
            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._State.version = "vB"
            w._state_restore()
            assert w._STATE_CACHE["payload"] is None, "跨版本快照应被丢弃"

    def test_same_version_restored(self):
        with _Sandbox() as sb:
            w = sb.w
            w._State.version = "vSame"
            p = _payload()
            body = _body(p)
            w._state_persist((sb.db, 1, 2, 3, "v"), body, '"e"',
                             gzip.compress(body, 6))
            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._state_restore()
            assert w._STATE_CACHE["payload"] == p

    def test_restore_once_flag(self):
        """_state_restore_once 只生效一次（热路径零重复 IO）。"""
        with _Sandbox() as sb:
            w = sb.w
            w._state_restore_once()
            assert w._STATE_DISK_ONCE["on"] is True
            # 第二次即使有盘上快照也不再读
            p = _payload()
            body = _body(p)
            w._state_persist((sb.db, 1, 2, 3, "v"), body, '"e"',
                             gzip.compress(body, 6))
            w._state_restore_once()
            assert w._STATE_CACHE["payload"] is None


class TestEtagIntegrity:
    def test_body_etag_gz_consistent(self):
        """恢复后三元组必须同一份快照（body 与 gz 解压结果一致）。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            gz = gzip.compress(body, 6)
            w._state_persist((sb.db, 9, 8, 7, "v"), body, '"ez"', gz)
            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._state_restore()
            assert gzip.decompress(w._STATE_CACHE["gz"]) == w._STATE_CACHE["body"]
            assert json.loads(w._STATE_CACHE["body"].decode("utf-8")) == p
