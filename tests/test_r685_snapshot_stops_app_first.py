# -*- coding: utf-8 -*-
"""r685：快照必须在 App 停机后打包，否则打出的是一份「空登录态」。

现场（2026-10-30）：在去哪儿 App 里登录成功、列表页已经有真实票价，
立刻导出快照（0.6 MB，`databases/RKStorage` 在包里），随后恢复 → 仍是
登录墙。根因是 App 还在运行：SQLite 的新会话大部分压在 `-wal` 里，
`tar` 抓到的只是旧库。

这条缺陷最像「成功」：文件有大小、包里文件齐全、日志写着「快照 0.6 MB」，
唯独恢复后回不到登录态。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.snapshot import SnapshotManager, SnapshotStore


class FakeDev:
    def __init__(self, activity="com.Qunar/.MainActivity", root=True):
        self._activity = activity
        self._root = root
        self.calls = []

    def root(self):
        self.calls.append(("root",))
        return self._root

    def current_activity(self):
        self.calls.append(("activity",))
        return self._activity

    def app_stop(self, pkg):
        self.calls.append(("stop", pkg))
        self._activity = "com.android.launcher/.Launcher"
        return True

    def _sh(self, *args, **kw):
        cmd = args[-1] if args else ""
        self.calls.append(("sh", cmd[:60]))
        if "ls /sdcard" in str(cmd):
            return "/sdcard/tm_snapshot.tgz"
        return ""


def _mgr(tmp_path, dev):
    store = SnapshotStore(str(tmp_path / "snaps"))
    return SnapshotManager(dev, store, "com.Qunar")


def test_export_stops_running_app_first(tmp_path, monkeypatch):
    """App 在跑时，打包之前必须先 force-stop。"""
    import core.android.snapshot as mod
    dev = FakeDev(activity="com.Qunar/.MainActivity")
    mgr = _mgr(tmp_path, dev)

    # 让取回数据这一步直接失败，只关心"有没有先停"
    monkeypatch.setattr(mod, "_run", lambda *a, **k: None, raising=False)
    mgr.export("app_qunar")

    kinds = [c[0] for c in dev.calls]
    assert "stop" in kinds, "App 还在跑就直接打包了：%s" % kinds
    assert kinds.index("stop") < kinds.index("sh"), \
        "先打包后停 App，WAL 里的会话没落盘"


def test_export_does_not_stop_when_app_not_running(tmp_path, monkeypatch):
    """没在跑就别停——无谓的 stop 会拖慢登录卡的「保存会话」。"""
    import core.android.snapshot as mod
    dev = FakeDev(activity="com.android.launcher/.Launcher")
    mgr = _mgr(tmp_path, dev)
    monkeypatch.setattr(mod, "_run", lambda *a, **k: None, raising=False)
    mgr.export("app_qunar")
    assert "stop" not in [c[0] for c in dev.calls], dev.calls


def test_export_reports_missing_root(tmp_path):
    """没有 root 要如实报，不能返回一个空快照。"""
    dev = FakeDev(root=False)
    mgr = _mgr(tmp_path, dev)
    ok, detail = mgr.export("app_qunar")
    assert not ok and "root" in detail


class RestoreDev(FakeDev):
    """恢复路径：push 成功，可由 tar_rc 控制解包结果。"""

    adb_path = "adb"
    serial = "127.0.0.1:16384"

    def __init__(self, tar_rc=0):
        super().__init__(activity="com.android.launcher/.Launcher")
        self.tar_rc = tar_rc
        self.started = []

    def app_start(self, pkg):
        self.started.append(pkg)
        return True

    def _sh(self, *args, **kw):
        cmd = str(args[-1]) if args else ""
        self.calls.append(("sh", cmd[:80]))
        if "TAR_RC" in cmd:
            return "tar: /sdcard/tm_snapshot.tgz: No such file or directory\nTAR_RC=%d\n" % self.tar_rc
        return ""


def _ok_run(*a, **k):
    return type("P", (), {"returncode": 0, "stdout": b""})()


def _restore_mgr(tmp_path, dev):
    from core.android.snapshot import SnapshotStore as Store
    store = Store(str(tmp_path / "snaps"))
    store.save_bytes("app_qunar", b"\x1f\x8b" + b"0" * 64)
    return SnapshotManager(dev, store, "com.Qunar")


def test_restore_fails_when_tar_exit_code_nonzero(tmp_path, monkeypatch):
    """tar 失败必须报失败。

    现场：解包命令以 `echo DONE` 结尾，DONE 无条件输出——/sdcard 上没有
    快照文件时 tar 明明报 No such file，恢复仍返回「已恢复快照」。界面
    与账本都写着成功，设备上什么都没变（用户视角：登录了一次又一次）。
    """
    import core.android.snapshot as mod
    import subprocess
    dev = RestoreDev(tar_rc=2)
    monkeypatch.setattr(mod, "_run", _ok_run, raising=False)
    monkeypatch.setattr(subprocess, "run", _ok_run, raising=False)
    mgr = _restore_mgr(tmp_path, dev)
    ok, detail = mgr.restore("app_qunar")
    assert not ok, "tar 退出码 2 却报成功：%s" % detail
    assert "2" in detail or "解包" in detail, detail
    assert "com.Qunar" not in dev.started, "解包失败还去启动 App"


def test_restore_succeeds_on_zero_exit_code(tmp_path, monkeypatch):
    import core.android.snapshot as mod
    import subprocess
    dev = RestoreDev(tar_rc=0)
    monkeypatch.setattr(mod, "_run", _ok_run, raising=False)
    monkeypatch.setattr(subprocess, "run", _ok_run, raising=False)
    mgr = _restore_mgr(tmp_path, dev)
    ok, detail = mgr.restore("app_qunar")
    assert ok, detail
    assert dev.started == ["com.Qunar"]
