# -*- coding: utf-8 -*-
"""r676：登录态快照不得带动态 so——它让每次采集都把 App 卡死。

真机现场（去哪儿 com.Qunar）：
  * 快照里含 `files/plt_dynamic_so/libbnfacesdk.so`（**arm64** ELF）；
  * 模拟器是 **x86_64**；
  * 恢复快照把这个 so 写回设备 → App 启动时 `DynamicSoManager` 加载它 →
    主线程 Blocked 在 `Runtime.load0` 等锁 → ANR「没有响应」120s+，
    每次采集都「打不开首页」。

登录态只关心凭据（prefs/db/文件里的账号信息），不关心**可执行代码**：
so 与设备 ABI 绑定，跨设备复制必然出事。所以导出与恢复两侧都要排除。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import snapshot as S


def test_excludes_cover_dynamic_so_dir():
    joined = " ".join(S.SNAP_EXCLUDES)
    assert "plt_dynamic_so" in joined, S.SNAP_EXCLUDES


def test_export_command_excludes_dynamic_so():
    src = inspect.getsource(S.SnapshotManager.export)
    assert "SNAP_EXCLUDES" in src or "--exclude" in src, src[:400]


def test_restore_command_excludes_dynamic_so():
    """老快照里可能已带 so——恢复侧必须一起挡掉。"""
    src = inspect.getsource(S.SnapshotManager.restore)
    assert "excludes" in src, src[:400]
    assert "--exclude" in src, src[:400]


def test_snapshot_still_covers_login_state_paths():
    """排除 so 不能把登录态本身排掉。"""
    assert S.SNAP_PATHS == ("shared_prefs", "databases", "files")
    for p in ("shared_prefs", "databases"):
        assert p not in " ".join(S.SNAP_EXCLUDES), \
            "登录态目录被误排除：%s" % p
