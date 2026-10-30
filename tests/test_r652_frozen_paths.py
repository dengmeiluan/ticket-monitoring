# -*- coding: utf-8 -*-
"""r652：打包（PyInstaller）后，数据/登录态必须落在 exe 所在目录。

实测：冻结态 `__file__` 指向 `_internal/`，于是 `data/prices.db`、
`user_data/` 全被拼进程序内部目录——用户在安装目录下看不到自己的数据，
升级或重装一次就随包一起被清掉。源码态必须保持仓库根不变。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import paths


def test_source_mode_uses_repo_root(monkeypatch):
    """源码态：根目录 = core/ 的上一级（仓库根）。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    root = paths.app_root()
    assert os.path.isdir(os.path.join(root, "core")), root
    assert os.path.isdir(os.path.join(root, "crawlers")), root


def test_frozen_mode_uses_exe_dir(monkeypatch, tmp_path):
    """冻结态：根目录 = exe 所在目录，不是 _internal。"""
    exe = tmp_path / "TicketMonitor.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert paths.app_root() == str(tmp_path)


def test_relative_paths_anchor_to_exe_dir(monkeypatch, tmp_path):
    """`data/prices.db` 这类相对路径要拼到 exe 目录下。"""
    exe = tmp_path / "TicketMonitor.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    got = paths.resolve("data/prices.db").replace("\\", "/")
    want = (str(tmp_path) + "/data/prices.db").replace("\\", "/")
    assert got == want, "%s != %s" % (got, want)
    # 绝对路径原样
    assert paths.resolve(r"D:\other\a.db") == r"D:\other\a.db"


def test_main_and_crawlers_use_app_root_when_frozen():
    """三处根解析都要接上 core.paths，否则只修一半仍会写错位置。"""
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("main.py", "crawlers/base.py", "crawlers/app_base.py"):
        src = io.open(os.path.join(root, rel), encoding="utf-8",
                      newline="").read()
        assert "core.paths import app_root" in src, "%s 未接 app_root" % rel
        assert 'getattr(sys, "frozen", False)' in src, "%s 未判冻结态" % rel
