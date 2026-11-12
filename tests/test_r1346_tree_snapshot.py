# -*- coding: utf-8 -*-
"""r1346：升级前必须打**整树快照**（与"覆盖清单"无关的安全网）。

事故复盘（2026-11-10 15:24）：一次「一键升级」用源码包覆盖整个工作树，
当天 24 处未提交改动全丢。为什么 `apply()` 自带的 `backup_*` 没救回来？
因为它只备份**将被覆盖的文件**；连续三次升级后，备份里存的已经是
**上一次覆盖后**的状态（实测那三份备份里我的标记一个都没有）。

契约：
1. `apply()` 在动任何文件之前先整树打包（`tree_<ts>.zip`）；
2. 快照失败 → **中止升级**（没有安全网就不覆盖）；
3. 快照必须包含源码与测试（且不把 `user_data/`、`.git`、`__pycache__` 打进去）；
4. 只保留最近 keep 份（每份几十 MB，不设上限会吃光磁盘）。
"""
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import update  # noqa: E402


def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "user_data" / "secret.txt").write_text("不该进快照", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
    (root / "main.py").write_text("V0", encoding="utf-8")
    (root / "webui.py").write_text("W0", encoding="utf-8")
    (root / "core" / "a.py").write_text("A0", encoding="utf-8")
    return root


def test_snapshot_contains_sources_not_userdata(tmp_path):
    root = _proj(tmp_path)
    out = update.snapshot_tree(str(root), tag="t1")
    assert out and os.path.isfile(out), out
    names = set(zipfile.ZipFile(out).namelist())
    assert "main.py" in names and "webui.py" in names and "core/a.py" in names
    assert not any(n.startswith("user_data/") for n in names), names
    assert not any("__pycache__" in n for n in names), names
    assert not any(n.endswith(".pyc") for n in names), names


def test_snapshot_skips_build_outputs(tmp_path):
    """构建产物/安装包不进安全网（本机实测 `_build` 100+MB、根 exe 12MB）。

    不是洁癖：安全网必须**比风险快**。实测未过滤时 12.7GB / >7 分钟，
    过滤后 33MB / 1.5 秒。
    """
    root = _proj(tmp_path)
    (root / "_build").mkdir()
    (root / "_build" / "TicketMonitor.zip").write_bytes(b"x" * 100)
    (root / "build").mkdir()
    (root / "build" / "app.exe").write_bytes(b"x" * 100)
    (root / "TicketMonitor.exe").write_bytes(b"x" * 100)
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("keep", encoding="utf-8")
    out = update.snapshot_tree(str(root), tag="t2")
    names = set(zipfile.ZipFile(out).namelist())
    assert "docs/note.md" in names, names
    assert not any(n.startswith("_build/") for n in names), names
    assert not any(n.startswith("build/") for n in names), names
    assert not any(n.lower().endswith(".exe") for n in names), names
    assert not any(n.lower().endswith(".zip") for n in names), names


def test_apply_makes_tree_snapshot_before_overwrite(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V1")
        zf.writestr("webui.py", "W1")
        zf.writestr("core/a.py", "A1")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty", lambda r: [], raising=False)
    rep = update.apply(str(z), force=True)
    assert rep["ok"] is True, rep
    snaps = [f for f in os.listdir(root / "user_data" / "update" / "treetars")
             if f.endswith(".zip")]
    assert snaps, "升级前没有整树快照"
    p = root / "user_data" / "update" / "treetars" / snaps[0]
    names = zipfile.ZipFile(p).namelist()
    assert "main.py" in names
    # 快照里存的必须是**覆盖前**的内容
    assert zipfile.ZipFile(p).read("main.py") == b"V0"


def test_apply_aborts_when_snapshot_fails(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V1")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty", lambda r: [], raising=False)
    monkeypatch.setattr(update, "snapshot_tree", lambda *a, **k: "")
    rep = update.apply(str(z), force=True)
    assert rep["ok"] is False, rep
    assert "快照失败" in rep["err"], rep
    # 关键：文件一个都没动
    assert (root / "main.py").read_text(encoding="utf-8") == "V0"


def test_prune_keeps_newest_n(tmp_path):
    root = _proj(tmp_path)
    d = root / "user_data" / "update" / "treetars"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        p = d / ("tree_%d.zip" % i)
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    removed = update.prune_tree_snaps(str(root), keep=2)
    left = sorted(os.listdir(d))
    assert len(left) == 2, left
    assert len(removed) == 3, removed
    assert "tree_4.zip" in left, left          # 最新的留下
