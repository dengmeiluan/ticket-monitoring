# -*- coding: utf-8 -*-
"""升级包解压不得写出缓存目录（zip slip）：`..`、绝对路径、符号链接一律拒绝。

升级包是 `--download` 从 release 拉下来的，成员名由发布方决定；
`extractall()` 照名字落盘，`../x` 或 `/x` 就写到了缓存目录之外。
正常发行包不受影响（同一用例在最后覆盖）。
"""
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import update as U  # noqa: E402


def _zip(tmp_path, entries, links=()):
    p = tmp_path / "update.zip"
    with zipfile.ZipFile(p, "w") as f:
        for name, text in entries.items():
            f.writestr(name, text)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o120777 << 16)
            f.writestr(info, "/etc/passwd")
    return str(p)


def _dest(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    return d


def test_extract_refuses_parent_traversal(tmp_path):
    dest = _dest(tmp_path)
    z = _zip(tmp_path, {"../escaped.txt": "x"})
    with zipfile.ZipFile(z) as f:
        with pytest.raises(RuntimeError):
            U._safe_extract(f, str(dest))
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_refuses_absolute_member(tmp_path):
    dest = _dest(tmp_path)
    target = tmp_path / "abs.txt"
    z = _zip(tmp_path, {str(target): "x"})
    with zipfile.ZipFile(z) as f:
        with pytest.raises(RuntimeError):
            U._safe_extract(f, str(dest))
    assert not target.exists()


def test_extract_refuses_symlink_member(tmp_path):
    dest = _dest(tmp_path)
    z = _zip(tmp_path, {"core/mod.py": "NEW\n"}, links=("link",))
    with zipfile.ZipFile(z) as f:
        with pytest.raises(RuntimeError):
            U._safe_extract(f, str(dest))
    assert not os.path.lexists(os.path.join(str(dest), "link"))


def test_normal_members_still_extract(tmp_path):
    dest = _dest(tmp_path)
    z = _zip(tmp_path, {"core/mod.py": "NEW-CODE\n", "webui.py": "NEW-UI\n"})
    with zipfile.ZipFile(z) as f:
        U._safe_extract(f, str(dest))
    assert (dest / "core" / "mod.py").read_text(encoding="utf-8") == "NEW-CODE\n"
    assert (dest / "webui.py").read_text(encoding="utf-8") == "NEW-UI\n"


def test_apply_refuses_escaping_member_and_leaves_project_untouched(
        tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "core" / "mod.py").write_text("OLD-CODE\n", encoding="utf-8")
    monkeypatch.setattr(U, "_root", lambda: str(root))
    z = _zip(tmp_path, {"core/mod.py": "NEW\n", "../../escaped.txt": "x"})

    r = U.apply(z)

    assert not r["ok"], r
    assert (root / "core" / "mod.py").read_text(encoding="utf-8") == "OLD-CODE\n"
    assert not (tmp_path / "escaped.txt").exists()
