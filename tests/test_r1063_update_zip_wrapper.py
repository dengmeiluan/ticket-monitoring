# -*- coding: utf-8 -*-
"""r1063 T264b：zip **包装层**判定的两个形态都要钉住。

背景（真 bug，被 `test_r1063_update_apply_safety` 逮到）：
早期 `apply()` 只看"顶层唯一且是目录"就认定它是 release 包装层——
于是 zip 里只有 `core/` 时，`base` 指到 `<tmp>/core`，`relpath` 退化成
`mod.py`，文件被**静默摊到项目根**。

正确形态：
* 唯一顶层目录里含项目根标志（`main.py`/`webui.py`/`core`…）→ 剥一层；
* 唯一顶层目录只是普通目录（如 `core/`）→ **不剥**。
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import update as U  # noqa: E402


def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "core" / "mod.py").write_text("OLD-CODE\n", encoding="utf-8")
    return root


def _zip(tmp_path, entries):
    z = tmp_path / "u.zip"
    with zipfile.ZipFile(z, "w") as f:
        for k, v in entries.items():
            f.writestr(k, v)
    return str(z)


def test_wrapper_dir_is_stripped_when_it_looks_like_root(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    monkeypatch.setattr(U, "_root", lambda: str(root))
    z = _zip(tmp_path, {"ticket-monitoring/main.py": "print(1)\n",
                        "ticket-monitoring/core/mod.py": "NEW-CODE\n"})
    r = U.apply(z)
    assert r["ok"], r
    assert (root / "core" / "mod.py").read_text(encoding="utf-8") == "NEW-CODE\n"
    assert (root / "main.py").read_text(encoding="utf-8") == "print(1)\n"
    assert not (root / "ticket-monitoring").exists(), "包装层目录不该被创建"


def test_single_plain_dir_is_not_stripped(tmp_path, monkeypatch):
    """只有 `core/` 的 zip 不得被当包装层（否则文件摊到项目根）。"""
    root = _proj(tmp_path)
    monkeypatch.setattr(U, "_root", lambda: str(root))
    z = _zip(tmp_path, {"core/mod.py": "NEW-CODE\n"})
    r = U.apply(z)
    assert r["ok"], r
    assert (root / "core" / "mod.py").read_text(encoding="utf-8") == "NEW-CODE\n"
    assert not (root / "mod.py").exists(), "文件被摊到项目根 = 回归"
