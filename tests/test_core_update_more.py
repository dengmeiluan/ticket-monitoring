# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1197_update_rollback.py
- tests/test_r1243_update_dirty_guard.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import sys
import time
import zipfile

from core import update


# ---- merged from tests/test_r1197_update_rollback.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _fake_project(tmp_path):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "main.py").write_text("NEW-MAIN", encoding="utf-8")
    (root / "core" / "x.py").write_text("NEW-X", encoding="utf-8")
    (root / "data" / "prices.db").write_text("DB-LIVE", encoding="utf-8")
    return root


def _make_backup(root, name, files, at=0.0):
    bak = root / "user_data" / "update" / name
    for rel, content in files.items():
        p = bak / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if at:
        os.utime(bak, (at, at))
    return bak


def test_list_backups_newest_first(tmp_path, monkeypatch):
    root = _fake_project(tmp_path)
    now = time.time()
    _make_backup(root, "backup_20260101_000000", {"main.py": "A"}, at=now - 100)
    _make_backup(root, "backup_20260202_000000", {"main.py": "B"}, at=now - 10)
    (root / "user_data" / "update" / "not_a_backup").mkdir()
    monkeypatch.setattr(update, "_root", lambda: str(root))
    got = update.list_backups()
    assert [b["name"] for b in got] == ["backup_20260202_000000",
                                        "backup_20260101_000000"], got
    assert all(b["files"] >= 1 for b in got)


def test_rollback_restores_files_and_skips_user_assets(tmp_path, monkeypatch):
    root = _fake_project(tmp_path)
    _make_backup(root, "backup_20260101_000000", {
        "main.py": "OLD-MAIN",
        "core/x.py": "OLD-X",
        "data/prices.db": "DB-FROM-BACKUP",   # 负控样本：必须被跳过
    })
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.rollback()
    assert rep["ok"] is True, rep
    assert (root / "main.py").read_text(encoding="utf-8") == "OLD-MAIN"
    assert (root / "core" / "x.py").read_text(encoding="utf-8") == "OLD-X"
    assert (root / "data" / "prices.db").read_text(encoding="utf-8") == "DB-LIVE", \
        "回滚把用户数据写掉了"


def test_rollback_without_backup_is_honest(tmp_path, monkeypatch):
    root = _fake_project(tmp_path)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.rollback()
    assert rep["ok"] is False
    assert "没有可用的备份" in rep["err"]


def test_apply_then_rollback_roundtrip(tmp_path, monkeypatch):
    """端到端：升级 → 回滚 → 内容回到升级前。"""
    root = _fake_project(tmp_path)
    (root / "main.py").write_text("V1", encoding="utf-8")
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V2")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    up = update.apply(str(z))
    assert up["ok"] is True, up
    assert (root / "main.py").read_text(encoding="utf-8") == "V2"
    back = update.rollback()
    assert back["ok"] is True, back
    assert (root / "main.py").read_text(encoding="utf-8") == "V1", \
        "回滚后没回到升级前的内容"


# ---- merged from tests/test_r1243_update_dirty_guard.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _clean_proj(tmp_path):
    """建一个"干净"的假项目（并用 monkeypatch 让 _git_dirty 返回空）。"""
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "main.py").write_text("V0", encoding="utf-8")
    (root / "webui.py").write_text("W0", encoding="utf-8")
    return root


def _zip(tmp_path):
    p = tmp_path / "p.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("main.py", "V1")
        zf.writestr("webui.py", "W1")
    return str(p)


def test_apply_refuses_when_dirty(tmp_path, monkeypatch):
    root = _clean_proj(tmp_path)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty",
                        lambda r: [" M webui.py", " M main.py"], raising=False)
    rep = update.apply(_zip(tmp_path))
    assert rep["ok"] is False, rep
    assert "未提交改动" in rep["err"], rep
    assert rep["dirty_n"] == 2, rep
    # 关键：**一个文件都没被改**
    assert (root / "main.py").read_text(encoding="utf-8") == "V0"
    assert (root / "webui.py").read_text(encoding="utf-8") == "W0"


def test_force_overrides(tmp_path, monkeypatch):
    root = _clean_proj(tmp_path)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty", lambda r: [" M webui.py"], raising=False)
    rep = update.apply(_zip(tmp_path), force=True)
    assert rep["ok"] is True, rep
    assert (root / "main.py").read_text(encoding="utf-8") == "V1"


def test_clean_tree_still_upgrades(tmp_path, monkeypatch):
    root = _clean_proj(tmp_path)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    monkeypatch.setattr(update, "_git_dirty", lambda r: [], raising=False)
    rep = update.apply(_zip(tmp_path))
    assert rep["ok"] is True, rep


def test_non_git_dir_is_not_blocked(tmp_path, monkeypatch):
    """取不到 git 状态（非仓库/无 git）时必须放行——护栏不能挡正常用户。"""
    root = _clean_proj(tmp_path)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    # 用真实实现：临时目录不是 git 仓库 → 应返回空列表
    monkeypatch.undo()
    monkeypatch.setattr(update, "_root", lambda: str(root))
    assert update._git_dirty(str(root)) == []
    rep = update.apply(_zip(tmp_path))
    assert rep["ok"] is True, rep


def test_cli_passes_force():
    src = io.open(os.path.join(ROOT, "core", "update.py"), encoding="utf-8").read()
    assert "import subprocess" in src, "缺少 subprocess 导入"
    assert 'apply(z, force="--force" in argv)' in src, "CLI 没把 --force 传下去"
