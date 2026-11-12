# -*- coding: utf-8 -*-
"""r1243：升级必须**拒绝覆盖未提交的工作**（15:24 事故的护栏）。

事故：2026-11-10 15:24，一次「一键升级」用源码包覆盖整个工作树，当天 24 处未提交
改动被抹掉。`apply()` 自带的备份救不了——它只备份"将被覆盖的文件"，而连续几次
升级后备份里可能已经是上一次覆盖后的状态（实测 15:23/15:24 那三份备份里，
我的标记一个都没有）。

契约：
1. 工作树相对 git HEAD 有改动 → `apply()` **拒绝**，并说清有多少处、怎么继续；
2. 显式 `force=True` 才动手；
3. 不在 git 仓库里（取不到状态）→ 不拦（不能因为护栏把正常用户挡在外面）。
"""
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import update  # noqa: E402


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
