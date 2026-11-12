# -*- coding: utf-8 -*-
"""r1210：备份必须有保留策略——否则「一键升级」会把磁盘吃掉。

实测（2026-11-10）：`user_data/update/` 下有 **26 个** `backup_*`，
每个约 996 个文件 → 合计 **7.58 GB**。每个备份都是 `apply()` 为了
"失败能回滚"整份拷下来的，没有清理策略就只增不减。

契约：
1. `prune_backups(keep)` 只保留最新 N 个（默认 3），其余删除；
2. **只动 `user_data/update/backup_*`**，不许碰用户数据/配置/日志；
3. `apply()` 成功后自动 prune（负控：keep 很小时老备份必须真的消失）。
"""
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import update  # noqa: E402


def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "main.py").write_text("V0", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "prices.db").write_text("DB", encoding="utf-8")
    return root


def _bak(root, name, at):
    d = root / "user_data" / "update" / name
    d.mkdir(parents=True)
    (d / "main.py").write_text("OLD", encoding="utf-8")
    os.utime(d, (at, at))
    return d


def test_prune_keeps_newest(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    now = time.time()
    _bak(root, "backup_a", now - 300)
    _bak(root, "backup_b", now - 200)
    _bak(root, "backup_c", now - 100)
    _bak(root, "backup_d", now - 10)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.prune_backups(2)
    left = [b["name"] for b in update.list_backups()]
    assert left == ["backup_d", "backup_c"], left
    assert sorted(rep["removed"]) == ["backup_a", "backup_b"], rep
    assert rep["freed_bytes"] > 0


def test_prune_never_touches_user_data(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    now = time.time()
    for i, nm in enumerate(("backup_1", "backup_2", "backup_3")):
        _bak(root, nm, now - 100 + i)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    update.prune_backups(1)
    assert (root / "data" / "prices.db").read_text(encoding="utf-8") == "DB", \
        "清理备份把用户数据删了"
    assert (root / "main.py").is_file()


def test_apply_prunes_automatically(tmp_path, monkeypatch):
    """负控：apply 成功后老备份必须被清（否则又回到只增不减）。"""
    root = _proj(tmp_path)
    now = time.time()
    for i in range(5):
        _bak(root, "backup_old%d" % i, now - 500 + i)
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V1")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.apply(str(z))
    assert rep["ok"] is True, rep
    assert "pruned" in rep, "apply 没带清理结果"
    left = [b["name"] for b in update.list_backups()]
    assert len(left) <= 3, left
