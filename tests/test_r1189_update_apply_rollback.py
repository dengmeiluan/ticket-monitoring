# -*- coding: utf-8 -*-
"""r1189：升级必须"先备份、失败回滚、用户数据一律不动"——用真 zip 打一遍。

v2.1 §8 要求更新是**页面内闭环**，但闭环的前提是后端这三条真的成立。
本文件不碰真项目目录：把 `update._root()` 指到 tmp_path 上，造一个"假项目"，
再用真 zip 走 `apply()`，逐条验：

1. 代码文件被覆盖；
2. `user_data/` `data/` `logs/` `config.yaml` `.git/` **一个字节都不许变**；
3. 备份目录里留着被覆盖前的原件；
4. **失败回滚**：覆盖过程中抛异常 → 原文件必须被还原（这条最容易写成"看起来有代码"）；
5. 负控：zip 里只有被跳过的文件 → 必须明确报"没有可覆盖的文件"，不许假装成功。
"""
import io
import os
import shutil
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys  # noqa: E402
sys.path.insert(0, ROOT)

from core import update  # noqa: E402


def _fake_project(tmp_path):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "user_data").mkdir()
    (root / "data").mkdir()
    (root / "logs").mkdir()
    (root / ".git").mkdir()
    (root / "main.py").write_text("OLD-MAIN", encoding="utf-8")
    (root / "core" / "x.py").write_text("OLD-X", encoding="utf-8")
    (root / "config.yaml").write_text("db_path: data/prices.db\n", encoding="utf-8")
    (root / "user_data" / "keep.txt").write_text("USER-DATA", encoding="utf-8")
    (root / "data" / "prices.db").write_text("DB", encoding="utf-8")
    (root / "logs" / "m.log").write_text("LOG", encoding="utf-8")
    (root / ".git" / "config").write_text("GIT", encoding="utf-8")
    return root


def _mk_zip(tmp_path, entries, name="pkg.zip"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for arc, content in entries.items():
            z.writestr(arc, content)
    return str(p)


def _apply(monkeypatch, root, zip_path):
    monkeypatch.setattr(update, "_root", lambda: str(root))
    return update.apply(zip_path)


def test_covers_code_keeps_user_assets(tmp_path, monkeypatch):
    root = _fake_project(tmp_path)
    z = _mk_zip(tmp_path, {
        "main.py": "NEW-MAIN",
        "core/x.py": "NEW-X",
        "config.yaml": "MUST-NOT-WIN\n",
        "user_data/keep.txt": "MUST-NOT-WIN",
        "data/prices.db": "MUST-NOT-WIN",
        "logs/m.log": "MUST-NOT-WIN",
        ".git/config": "MUST-NOT-WIN",
    })
    rep = _apply(monkeypatch, root, z)
    assert rep["ok"] is True, rep
    assert (root / "main.py").read_text(encoding="utf-8") == "NEW-MAIN"
    assert (root / "core" / "x.py").read_text(encoding="utf-8") == "NEW-X"
    # 用户资产一律不动
    assert (root / "config.yaml").read_text(encoding="utf-8").startswith("db_path")
    assert (root / "user_data" / "keep.txt").read_text(encoding="utf-8") == "USER-DATA"
    assert (root / "data" / "prices.db").read_text(encoding="utf-8") == "DB"
    assert (root / "logs" / "m.log").read_text(encoding="utf-8") == "LOG"
    assert (root / ".git" / "config").read_text(encoding="utf-8") == "GIT"
    # 备份里必须有被覆盖前的原件
    assert os.path.isdir(rep["backup"]), rep
    bak_main = os.path.join(rep["backup"], "main.py")
    assert os.path.isfile(bak_main), "没有备份原件，失败时无从回滚"
    assert io.open(bak_main, encoding="utf-8").read() == "OLD-MAIN"


def test_rollback_restores_original_on_failure(tmp_path, monkeypatch):
    """覆盖阶段炸掉：原文件必须被还原（这是"回滚"三个字唯一有意义的证明）。"""
    root = _fake_project(tmp_path)
    z = _mk_zip(tmp_path, {"main.py": "NEW-MAIN", "core/x.py": "NEW-X"})
    real_copy2 = shutil.copy2
    state = {"overwriting": False}

    def boom(src, dst, *a, **kw):
        s, d = str(src), str(dst)
        if "_bak_" in d or "backup_" in d:          # 备份阶段照常
            return real_copy2(src, dst, *a, **kw)
        # 覆盖阶段：先成功写一个，再在第二个文件上炸
        if s.endswith("main.py"):
            real_copy2(src, dst, *a, **kw)
            state["overwriting"] = True
            return dst
        if s.endswith("x.py") and state["overwriting"]:
            raise OSError("模拟磁盘写失败")
        return real_copy2(src, dst, *a, **kw)

    monkeypatch.setattr(update.shutil, "copy2", boom)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.apply(z)
    assert rep["ok"] is False, rep
    assert rep.get("rolled_back", 0) >= 1, rep
    # 已经被覆盖的 main.py 必须回到旧内容
    assert (root / "main.py").read_text(encoding="utf-8") == "OLD-MAIN", \
        "回滚没把 main.py 还原：用户会拿到半套代码"


def test_all_skipped_is_an_error(tmp_path, monkeypatch):
    """负控：zip 里只有被跳过的文件时，不许报成功。"""
    root = _fake_project(tmp_path)
    z = _mk_zip(tmp_path, {"user_data/keep.txt": "X", "data/prices.db": "Y"})
    rep = _apply(monkeypatch, root, z)
    assert rep["ok"] is False
    assert "没有可覆盖的文件" in rep["err"]


def test_missing_zip_is_honest(tmp_path, monkeypatch):
    root = _fake_project(tmp_path)
    rep = _apply(monkeypatch, root, str(tmp_path / "nope.zip"))
    assert rep["ok"] is False
    assert "找不到更新包" in rep["err"]
