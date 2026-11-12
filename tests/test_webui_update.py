# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_release_assets_forbidden.py
- tests/test_r1063_source_vs_running.py
- tests/test_r1063_update_apply_safety.py
- tests/test_r1063_update_check_entry.py
- tests/test_r1063_update_in_browser.py
- tests/test_r1063_update_zip_slip.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import importlib.util
import io
import os
import pytest
import re
import sys
import zipfile

from core import update as U


# ---- merged from tests/test_r1063_release_assets_forbidden.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "tools", "verify_release_assets.py")


def _mod():
    spec = importlib.util.spec_from_file_location("vra", SPEC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_secrets_and_repo_history_are_forbidden():
    m = _mod()
    for name in (".env", ".git/config", "./.env", "ghtoken", "config.yaml",
                 "user_data/a.json", "data/prices.db", "logs/monitor.log"):
        assert m._forbidden(name) is True, "%s 必须被拦（原来 .env/.git 拦不住）" % name


def test_normal_release_content_is_allowed():
    m = _mod()
    for name in ("ticket-monitoring-win64.zip", "webui.py",
                 "_internal/tzdata/x", "_internal/numpy/core/x.pyd",
                 ".envrc", ".github/workflows/ci.yml"):
        assert m._forbidden(name) is False, "%s 不该被拦（避免误伤）" % name


# ---- merged from tests/test_r1063_source_vs_running.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_source_version_is_read():
    from core import setup_check as sc
    v = sc._source_version()
    assert v and v[0].isdigit(), v
    # 与 main.py 里的一致
    txt = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert '__version__ = "%s"' % v in txt


def test_running_instance_row_exists_and_shaped():
    from core import setup_check as sc
    row = sc.check_running_instance(port_hint=1)   # 1 号端口必然连不上
    assert row.get("name") == "运行实例"
    assert row.get("level") in ("ok", "warn", "info")


def test_warns_when_version_differs(monkeypatch):
    """实例版本与源码不一致时必须 warn，并给出两条出路。"""
    import json
    import urllib.request

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"version": "0.0.1-old"}).encode()

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _Resp())
    from core import setup_check as sc
    row = sc.check_running_instance(port_hint=8765)
    assert row["level"] == "warn"
    assert "尚未生效" in row["detail"]
    assert "python main.py" in row["fix"]


def test_row_is_wired_into_run_checks():
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    i = src.index("def run_checks")
    assert "check_running_instance()" in src[i:i + 500]


def test_gitignore_covers_runtime_artifacts():
    gi = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    for pat in (".tmp_*/", "config.yaml.bak_*", "prices.db",
                "_mumu_backup_*/"):
        assert pat in gi, pat


# ---- merged from tests/test_r1063_update_apply_safety.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_r1063_update_check_entry.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_route_tolerates_query_string():
    w = _w()
    assert 'self.path.split("?")[0] == "/api/update/check"' in w, \
        "路由必须按 ? 切分后再比，否则 ?force=1 拿不到响应"


def test_panel_always_shows_version_and_check_entry():
    w = _w()
    assert 'data["version"]' in w, "载荷要永远带当前版本"
    assert "updateCheck" in w and "检查更新" in w
    # 无更新时也要有那一行（很小的版本 + 检查入口）
    i = w.index("if(!u||!u.latest){")
    seg = w[i:i + 700]
    assert "检查更新" in seg and "j.version" in seg, seg[:200]


def test_frontend_survives_empty_body():
    w = _w()
    i = w.index("async function updateCheck(")
    seg = w[i:i + 900]
    assert "catch(_e){j=null;}" in seg, "空/非 JSON 响应不能抛 SyntaxError"
    assert "非 JSON" in seg, "要给出可读提示"


def test_check_update_does_not_auto_apply():
    """检查更新只读；写文件必须人点头（绝不在检查里顺手 apply）。"""
    w = _w()
    i = w.index("async function updateCheck(")
    seg = w[i:w.index("async function updateApply(")]
    assert "/api/update/apply" not in seg, "检查更新不得触发 apply"


# ---- merged from tests/test_r1063_update_in_browser.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_apply_endpoint_exists():
    w = _w()
    assert 'elif self.path == "/api/update/apply":' in w
    i = w.index('elif self.path == "/api/update/apply":')
    seg = w[i:i + 1200]
    assert "_upd.download()" in seg and "_upd.apply(" in seg, \
        "一键升级要自己先下载再应用"
    assert '"ok": False' in seg, "失败要如实回报"


def test_frontend_has_one_click_button_and_global_fn():
    w = _w()
    assert "立即升级" in w and "onclick=\"return updateApply(this)\"" in w
    i = w.index("async function updateApply(")
    line_start = w.rfind("\n", 0, i) + 1
    assert w[line_start:i] == " ", "updateApply 必须是顶层函数（onclick 解析全局名）"
    seg = w[i:i + 900]
    assert "/api/update/apply" in seg
    assert "doRestart" in seg, "升级成功后要能自动重启生效"


def test_update_never_touches_user_config():
    """安全边界：升级不得覆盖 config.yaml 与用户数据。"""
    for p in ("config.yaml", "user_data/app_zhixing/x.json", "data/prices.db",
              "logs/monitor.log"):
        assert U._skip(p) is True, "%s 必须跳过" % p
    for p in ("core/update.py", "crawlers/ctrip.py", "webui.py",
              "main.py"):
        assert U._skip(p) is False, "%s 必须被升级覆盖" % p


def test_confirm_copy_explains_scope():
    """确认框要说清"会动什么、不会动什么"——否则用户不敢点。"""
    w = _w()
    i = w.index("async function updateApply(")
    seg = w[i:i + 1200]
    assert "不会动 config.yaml" in seg or "不会动 config" in seg, seg[:200]
    assert "备份" in seg


# ---- merged from tests/test_r1063_update_zip_slip.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
