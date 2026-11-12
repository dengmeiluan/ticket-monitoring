# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_update_zip_wrapper.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys
import zipfile

from core import update as U


# ---- merged from tests/test_r1063_update_zip_wrapper.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
