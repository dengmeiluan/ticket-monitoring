# -*- coding: utf-8 -*-
"""r1211：`apply()` 不许把**发行包**铺到源码根上（r1209 实测的真事故）。

现场：`v1.6.0.zip` 顶层是 `TicketMonitor.exe` + `_internal/`（1120 条目），
**没有 `main.py` / `webui.py`**。源码部署点「一键升级」后：备份 300 MB、
把 exe 载荷重铺一遍、源码一行没变、却返回 `ok: true`。

契约：
1. `deploy_mode()`：有 `sys.frozen` → `binary`，否则 `source`；
2. `_pick_zip(release, mode)`：源码部署优先 source 资产（没有就用 `zipball_url`）；
   发行版优先 win 包；
3. `apply()` 形状校验：源码根 + 包里没有 `main.py`/`webui.py` → **拒绝**，
   且**不许留下备份目录**（负控）。
"""
import io
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import update  # noqa: E402


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
