# -*- coding: utf-8 -*-
"""r1197：升级要能"退回去"——`list_backups()` / `rollback()` 的行为门禁。

`apply()` 失败会自动回滚，但**成功之后**用户仍可能想退回上一个版本。
以前没有这个入口（"回滚"只活在异常分支里）。本文件守两件事：

1. 备份目录按时间**新→旧**列出，且只认 `backup_*`；
2. `rollback()` 把备份里的文件拷回项目根，**用户数据/配置/日志一个字节不动**
   （负控：往备份里塞一份 `data/x.db`，回滚不许把它写进项目）。
"""
import io
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import update  # noqa: E402


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
