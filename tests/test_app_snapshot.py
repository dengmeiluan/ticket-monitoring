# -*- coding: utf-8 -*-
"""登录态快照：存取、无快照不假装成功、导出失败如实报错。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.snapshot import SnapshotManager, SnapshotStore

GZ = b"\x1f\x8b\x08\x00" + b"0" * 64


class FakeProc:
    def __init__(self, out=b"", rc=0):
        self.stdout, self.returncode = out, rc


class FakeDevice:
    def __init__(self, rooted=True, has_file=True, pushed=True):
        self.rooted = rooted
        self.has_file = has_file
        self.pushed = pushed
        self.calls = []
        self.adb_path = "adb"
        self.serial = "s"

    def root(self):
        return self.rooted

    def app_stop(self, pkg):
        self.calls.append(("stop", pkg))
        return True

    def app_start(self, pkg):
        self.calls.append(("start", pkg))
        return True

    def current_activity(self):
        # export() 会先停 App 再打包（否则 SQLite 的 -wal 还没落盘，
        # 打出的快照恢复后仍是登录墙）。夹具默认「App 在前台」，
        # 让这条分支真的被执行到。
        return "mResumedActivity: ActivityRecord{1 cn.suanya.zhixing/.Main}"

    def _sh(self, *args, **kw):
        cmd = " ".join(str(a) for a in args[1:])
        self.calls.append(("sh", cmd))
        if cmd.startswith("ls /sdcard/tm_snapshot"):
            return "/sdcard/tm_snapshot.tgz\n" if self.has_file else ""
        if "echo DONE" in cmd:
            return "DONE\n"
        return ""


def _store():
    return SnapshotStore(tempfile.mkdtemp(prefix="snaptest_"))


def test_store_roundtrip():
    st = _store()
    info = st.save_bytes("app_zhixing", GZ)
    assert info["exists"] is True and info["size"] == len(GZ)
    assert st.load_bytes("app_zhixing") == GZ
    assert st.exists("app_zhixing") is True


def test_store_rejects_empty():
    st = _store()
    try:
        st.save_bytes("app_zhixing", b"")
        assert False, "空快照应被拒绝"
    except ValueError:
        pass


def test_store_info_when_missing():
    st = _store()
    assert st.info("nope") == {"exists": False}
    assert st.exists("nope") is False


def test_store_sanitizes_plat_name():
    st = _store()
    p = st.path_for("../evil/x")
    assert os.path.dirname(p) == st.base_dir
    assert ".." not in os.path.basename(p)


def test_restore_without_snapshot_fails_honestly():
    st = _store()
    mgr = SnapshotManager(FakeDevice(), st, "cn.suanya.zhixing")
    ok, detail = mgr.restore("app_zhixing")
    assert ok is False
    assert "没有可恢复的快照" in detail


def test_export_without_root_fails_honestly():
    st = _store()
    mgr = SnapshotManager(FakeDevice(rooted=False), st, "cn.suanya.zhixing")
    ok, detail = mgr.export("app_zhixing")
    assert ok is False
    assert "root" in detail


def test_export_reports_when_tar_missing():
    st = _store()
    mgr = SnapshotManager(FakeDevice(has_file=False), st,
                          "cn.suanya.zhixing")
    ok, detail = mgr.export("app_zhixing")
    assert ok is False
    assert detail


def test_restore_stops_app_before_writing():
    st = _store()
    st.save_bytes("app_zhixing", GZ)
    dev = FakeDevice()
    mgr = SnapshotManager(dev, st, "cn.suanya.zhixing")
    mgr.restore("app_zhixing")
    kinds = [c[0] for c in dev.calls]
    assert "stop" in kinds, "恢复前必须先停 App"


def test_snapshot_paths_exclude_cache():
    from core.android.snapshot import SNAP_PATHS
    assert "shared_prefs" in SNAP_PATHS
    assert "app_ctripwebapp6" not in SNAP_PATHS, \
        "128MB 网页缓存不属于登录态，不能打进快照"


# ---- r640：恢复不能把设备上更新的登录态回滚 ----
def test_restore_skipped_when_device_login_is_newer(tmp_path):
    """设备上的用户信息库比快照新时，必须跳过恢复。

    否则用户刚在 App 里登的新账号会被旧快照覆盖回去，且没有任何提示。
    """
    import os
    import time
    from core.android.snapshot import SnapshotManager, SnapshotStore

    store = SnapshotStore(str(tmp_path))
    store.save_bytes("app_zhixing", b"\x1f\x8b" + b"0" * 64)
    snap = store.path_for("app_zhixing")
    old = time.time() - 7200
    os.utime(snap, (old, old))

    class Dev:
        adb_path = "adb"
        serial = "x"

        def _sh(self, *a, **k):
            return "%d\n" % int(time.time())

        def root(self):
            return True

        def app_stop(self, pkg):
            return True

    called = {"stop": 0}
    d = Dev()

    def stop(pkg):
        called["stop"] += 1
        return True

    d.app_stop = stop
    mgr = SnapshotManager(d, store, "cn.suanya.zhixing")
    ok, detail = mgr.restore("app_zhixing")
    assert ok is False, "不应覆盖更新的设备登录态"
    assert "比快照新" in detail, detail
    assert called["stop"] == 0, "跳过时必须完全不动 App（不要 force-stop）"


def test_restore_proceeds_when_device_has_no_login(tmp_path):
    """设备上没有登录库（换机/重装）时应正常恢复。"""
    import os
    import time
    from core.android.snapshot import SnapshotManager, SnapshotStore

    store = SnapshotStore(str(tmp_path))
    store.save_bytes("app_zhixing", b"\x1f\x8b" + b"0" * 64)

    class Dev:
        adb_path = "adb"
        serial = "x"

        def _sh(self, *a, **k):
            if "stat" in str(a):
                return ""
            if "tar xzf" in str(a) or "cd " in str(a):
                # restore() 的判据是 tar 自己的退出码（`echo DONE` 无条件执行，
                # tar 失败也会被判成功）；夹具按新契约回传 TAR_RC。
                return "TAR_RC=0"
            return ""

        def root(self):
            return True

        def app_stop(self, pkg):
            return True

        def app_start(self, pkg):
            return True

        def current_activity(self):
            return "com.Qunar/.Main"

    import core.android.device as devmod

    class P:
        returncode = 0
        stdout = b""

    orig = devmod._run
    devmod._run = lambda *a, **k: P()
    try:
        mgr = SnapshotManager(Dev(), store, "cn.suanya.zhixing")
        assert mgr.device_login_mtime() == 0
        ok, detail = mgr.restore("app_zhixing")
        assert ok is True, detail
    finally:
        devmod._run = orig
