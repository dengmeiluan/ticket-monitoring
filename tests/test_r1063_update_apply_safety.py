# -*- coding: utf-8 -*-
"""r1063 T264：`core.update.apply()` 的**安全承诺**必须在真实执行下验证。

面板上我写了三句话，用户会据此点「立即升级」，所以每句都要有测试：

1. **会覆盖**代码文件（`core/`、`crawlers/`、`webui.py` …）；
2. **不会覆盖** `config.yaml`、`user_data/`、`data/`、`logs/`（用户资产）；
3. 覆盖前**必有备份**；备份失败就中止（不出现"改了一半"）。

全部在临时目录里跑，不碰真实仓库。
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import update as U  # noqa: E402


def _mkroot(tmp_path):
    """造一个迷你"项目"：代码 + 用户资产都在。"""
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "user_data").mkdir()
    (root / "data").mkdir()
    (root / "core" / "mod.py").write_text("OLD-CODE\n", encoding="utf-8")
    (root / "webui.py").write_text("OLD-UI\n", encoding="utf-8")
    (root / "config.yaml").write_text("routes: [mine]\n", encoding="utf-8")
    (root / "user_data" / "slot.json").write_text('{"cookie":"mine"}',
                                                 encoding="utf-8")
    (root / "data" / "prices.db").write_bytes(b"USER-DB")
    return root


def _mkzip(tmp_path, entries):
    z = tmp_path / "update.zip"
    with zipfile.ZipFile(z, "w") as f:
        for name, text in entries.items():
            f.writestr(name, text)
    return str(z)


def test_apply_updates_code_but_never_user_assets(tmp_path, monkeypatch):
    root = _mkroot(tmp_path)
    monkeypatch.setattr(U, "_root", lambda: str(root))
    z = _mkzip(tmp_path, {
        "core/mod.py": "NEW-CODE\n",
        "webui.py": "NEW-UI\n",
        # 更新包里**故意塞**用户资产：实现必须无视它们
        "config.yaml": "routes: [HIJACKED]\n",
        "user_data/slot.json": '{"cookie":"HIJACKED"}',
        "data/prices.db": "HIJACKED",
    })
    r = U.apply(z)
    assert r["ok"], r
    assert (root / "core" / "mod.py").read_text(encoding="utf-8") == "NEW-CODE\n"
    assert (root / "webui.py").read_text(encoding="utf-8") == "NEW-UI\n"
    # 用户资产一个字节都不该变
    assert (root / "config.yaml").read_text(encoding="utf-8") == "routes: [mine]\n"
    assert (root / "user_data" / "slot.json").read_text(
        encoding="utf-8") == '{"cookie":"mine"}'
    assert (root / "data" / "prices.db").read_bytes() == b"USER-DB"


def test_apply_writes_backup_before_overwrite(tmp_path, monkeypatch):
    root = _mkroot(tmp_path)
    monkeypatch.setattr(U, "_root", lambda: str(root))
    z = _mkzip(tmp_path, {"core/mod.py": "NEW-CODE\n"})
    r = U.apply(z)
    assert r["ok"] and r.get("backup")
    bak = r["backup"]
    assert os.path.isdir(bak), bak
    # 备份里保留**覆盖前**的内容
    backed = os.path.join(bak, "core", "mod.py")
    assert os.path.isfile(backed), bak
    assert io.open(backed, encoding="utf-8").read() == "OLD-CODE\n"


def test_apply_rolls_back_when_copy_fails(tmp_path, monkeypatch):
    """覆盖中途失败 → 必须回滚到升级前（不能留半新半旧）。"""
    root = _mkroot(tmp_path)
    monkeypatch.setattr(U, "_root", lambda: str(root))
    z = _mkzip(tmp_path, {"core/mod.py": "NEW-CODE\n", "webui.py": "NEW-UI\n"})
    real_copy = U.shutil.copy2
    state = {"n": 0}

    def flaky(src, dst, *a, **kw):
        state["n"] += 1
        # 备份 1 次 + 覆盖 1 次，第 3 次（第二个覆盖）时炸
        if state["n"] == 3:
            raise OSError("disk full (simulated)")
        return real_copy(src, dst, *a, **kw)

    monkeypatch.setattr(U.shutil, "copy2", flaky)
    r = U.apply(z)
    monkeypatch.setattr(U.shutil, "copy2", real_copy)
    assert not r["ok"], r
    assert r.get("rolled_back", 0) >= 1, r
    # 回滚后原文件恢复
    assert (root / "core" / "mod.py").read_text(encoding="utf-8") == "OLD-CODE\n"


def test_apply_rejects_missing_zip(tmp_path, monkeypatch):
    root = _mkroot(tmp_path)
    monkeypatch.setattr(U, "_root", lambda: str(root))
    r = U.apply(str(tmp_path / "nope.zip"))
    assert not r["ok"] and "找不到更新包" in str(r.get("err"))

def test_skip_protects_dot_dirs_and_envs():
    """`.git` / `.venv` 必须被跳过（lstrip("./") 曾把 `.git` 剥成 `git`，保护失效）。"""
    assert U._skip(".git/config") is True
    assert U._skip(".git/refs/heads/main") is True
    assert U._skip(".venv/lib/x.py") is True
    assert U._skip(".gitignore") is False, "点开头 ≠ 目录，别误伤普通文件"


def test_skip_never_blocks_packaged_runtime():
    """**`_internal/` 必须被覆盖** —— PyInstaller onedir 的运行时，
    不换等于升级后程序起不来（这里只拦用户资产与环境目录）。"""
    assert U._skip("_internal/python311.dll") is False
    assert U._skip("_internal/numpy/core/x.pyd") is False
    assert U._skip("ticket-monitoring.exe") is False
    assert U._skip("webui.py") is False
    assert U._skip("core/update.py") is False


def test_skip_handles_relative_prefixes():
    assert U._skip("./core/x.py") is False
    assert U._skip("./user_data/a.json") is True
    assert U._skip("user_data\\a.json") is True, "Windows 反斜杠也要归一"
