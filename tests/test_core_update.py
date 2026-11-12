# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1189_update_apply_rollback.py
- tests/test_r1211_update_deploy_shape.py
- tests/test_r1352_update_truth_and_channel_icons.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import pytest
import shutil
import sys
import zipfile

from core import update


# ---- merged from tests/test_r1189_update_apply_rollback.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, ROOT)

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


# ---- merged from tests/test_r1211_update_deploy_shape.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _rel(assets=None, zipball="https://x/zipball/main"):
    return {"assets": assets or [], "zipball_url": zipball}


def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "main.py").write_text("V0", encoding="utf-8")
    (root / "webui.py").write_text("W0", encoding="utf-8")
    return root


def _zip(tmp_path, entries, name="p.zip"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        for k, v in entries.items():
            zf.writestr(k, v)
    return str(p)


def test_deploy_mode_source_by_default():
    assert update.deploy_mode() in ("source", "binary")
    assert update.deploy_mode() == "source"       # pytest 里当然不是 frozen


def test_pick_zip_prefers_source_asset_for_source_deploy():
    rel = _rel([
        {"name": "ticket-monitoring-win64.zip",
         "browser_download_url": "https://x/win.zip"},
        {"name": "ticket-monitoring-source.zip",
         "browser_download_url": "https://x/src.zip"},
    ])
    assert update._pick_zip(rel, "source") == "https://x/src.zip"
    assert update._pick_zip(rel, "binary") == "https://x/win.zip"


def test_pick_zip_falls_back_to_zipball_for_source():
    rel = _rel([{"name": "ticket-monitoring-win64.zip",
                 "browser_download_url": "https://x/win.zip"}],
               zipball="https://x/zipball/main")
    assert update._pick_zip(rel, "source") == "https://x/zipball/main"


def test_apply_refuses_binary_package_on_source_root(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    z = _zip(tmp_path, {"TicketMonitor.exe": "EXE", "_internal/base_library.zip": "LIB"})
    monkeypatch.setattr(update, "_root", lambda: str(root))
    before = set(os.listdir(root / "user_data" / "update"))
    rep = update.apply(z)
    assert rep["ok"] is False, rep
    assert ("发行包" in rep["err"]) or ("源码" in rep["err"]), rep
    after = set(os.listdir(root / "user_data" / "update"))
    assert after == before, "拒绝时不许留下备份目录：%s" % (after - before)
    assert (root / "main.py").read_text(encoding="utf-8") == "V0", "源码被改了"


def test_apply_accepts_source_package(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    z = _zip(tmp_path, {"main.py": "V1", "webui.py": "W1", "core/x.py": "X"})
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.apply(z)
    assert rep["ok"] is True, rep
    assert (root / "main.py").read_text(encoding="utf-8") == "V1"


# ---- merged from tests/test_r1352_update_truth_and_channel_icons.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_download_refuses_when_latest(monkeypatch):
    from core import update as U
    monkeypatch.setattr(U, "check", lambda *a, **k: {
        "ok": True, "has_update": False, "latest": "v1.6.0", "local": "1.6.0"})
    r = U.download()
    assert r["ok"] is False and "已是最新" in r["err"], r


def test_apply_and_rollback_invalidate_cache():
    i = WEBUI.find("def _update_start_async(")
    assert i > 0
    # 后端必须在进入下载状态前确认 has_update（最新版不再起任务）
    seg = WEBUI[i:i + 1500]
    assert "has_update" in seg and "已是最新版本" in seg, seg[:600]
    # download/apply/rollback 三处语义在 core 内；扫描源码里的失效调用
    src = io.open(os.path.join(ROOT, "core", "update.py"), encoding="utf-8").read()
    assert "def _invalidate_cache(" in src
    assert src.count("_invalidate_cache()") >= 3  # 定义之外，apply + rollback 各一次


def test_cache_file_really_removed(tmp_path, monkeypatch):
    from core import update as U
    p = tmp_path / "update_check.json"
    p.write_text('{"ok":true,"has_update":true}', encoding="utf-8")
    monkeypatch.setattr(U, "_cache_path", lambda: str(p))
    U._invalidate_cache()
    assert not p.exists()


pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")


def _free_port():
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port










