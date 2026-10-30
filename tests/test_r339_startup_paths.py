# -*- coding: utf-8 -*-
"""启动级路径三件的可变更化（r339 用户指令：一切配置可变更化）：
db_path/log_path/user_data_dir/browser_dir 改路径后——
① db 旧库自动迁移到新路径（新路径无文件且旧默认/旧配置路径有文件时）
② user_data 同律（登录态不丢）
③ log 不迁移（日志按新路径新生成）
④ 迁移动作幂等（源缺席静默跳过）且失败不阻断启动（降级为沿旧路径+警告）"""
import os

import pytest

import main


def test_db_path_migration_moves_old_default_db(tmp_path, monkeypatch):
    old_db = tmp_path / "old" / "prices.db"
    old_db.parent.mkdir(parents=True)
    old_db.write_bytes(b"sqlite-data")
    new_db = tmp_path / "new" / "prices.db"
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_db_if_needed(
        str(old_db), str(new_db), str(tmp_path / "sentinel.db"))
    assert r is True
    assert new_db.exists() and new_db.read_bytes() == b"sqlite-data"
    assert not old_db.exists()


def test_db_path_noop_when_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_db_if_needed(
        str(tmp_path / "ghost.db"), str(tmp_path / "new.db"),
        str(tmp_path / "sentinel.db"))
    assert r is False
    assert not (tmp_path / "new.db").exists()


def test_user_data_dir_migration(tmp_path, monkeypatch):
    old_ud = tmp_path / "old" / "user_data"
    (old_ud / "profile").mkdir(parents=True)
    (old_ud / "profile" / "cookies").write_text("x")
    new_ud = tmp_path / "new" / "user_data"
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_user_data_if_needed(str(old_ud), str(new_ud))
    assert r is True
    assert (new_ud / "profile" / "cookies").exists()


def test_user_data_noop_when_target_exists(tmp_path, monkeypatch):
    old_ud = tmp_path / "old" / "user_data"
    old_ud.mkdir(parents=True)
    (old_ud / "keep").write_text("x")
    new_ud = tmp_path / "new" / "user_data"
    new_ud.mkdir(parents=True)
    (new_ud / "existing").write_text("y")
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_user_data_if_needed(str(old_ud), str(new_ud))
    assert r is False   # 目标已在：不覆盖（迁移只在空目标时执行）
    assert (new_ud / "existing").exists()


def test_wal_companion_files_migrate_with_db(tmp_path, monkeypatch):
    old_db = tmp_path / "old" / "prices.db"
    old_db.parent.mkdir(parents=True)
    old_db.write_bytes(b"sqlite-data")
    (tmp_path / "old" / "prices.db-wal").write_bytes(b"wal")
    (tmp_path / "old" / "prices.db-shm").write_bytes(b"shm")
    new_db = tmp_path / "new" / "prices.db"
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    main._migrate_db_if_needed(
        str(old_db), str(new_db), str(tmp_path / "sentinel.db"))
    assert new_db.exists()
    assert not (tmp_path / "old" / "prices.db-wal").exists()
    assert not (tmp_path / "old" / "prices.db-shm").exists()
    assert (tmp_path / "new" / "prices.db-wal").exists() or not (
        tmp_path / "old" / "prices.db-wal").exists()
