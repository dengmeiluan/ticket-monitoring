# -*- coding: utf-8 -*-
"""门禁：发版形态必须**有东西会响**（2026-11-16 漂移后补）。

那天的事实：main 叠了 6 笔、Pages 部署 7 条、Release 停在旧 SHA，而 CI 全绿——
因为没有任何检查校验"对外发布形态"。这条门禁把机制本身钉住：

1. 构建戳只有一份实现（`core.buildstamp`），三处调用点都对得上；
2. `tools/release_guard.py` 能跑、`--offline` 不依赖 token；
3. 三道防线都在（pre-push 钩子 / guard.yml / drift.yml），且文档里有启用方法；
4. `tools/converge_history.py` 有演练模式；
5. 版本说明单源（CHANGELOG）；
6. **公开历史形状**：本仓库当前就是单一 root commit（这是对外承诺）。
"""
import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _git(args):
    return subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8",
                          errors="replace").stdout


def _run(args, **kw):
    return subprocess.run([sys.executable, "-X", "utf8"] + args, cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def test_buildstamp_single_source():
    """构建戳必须与运行时口径一致（含 webui_assets）。"""
    import importlib
    from core.buildstamp import stamp_of
    want = stamp_of(ROOT)
    assert len(want) == 12 and all(c in "0123456789abcdef" for c in want), want
    webui = importlib.import_module("webui")
    assert webui._build_stamp() == want, "webui 与服务端戳口径不一致"


def test_no_second_stamp_computation():
    """除 core/buildstamp.py 外，不许再有人自己算 `sha256(webui.py)` 当戳。"""
    hits = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {
            ".git", "_scratch", "_tools", "_vendor", "_internal", "build",
            "dist", "data", "logs", "user_data", "__pycache__",
            ".pytest_cache", "node_modules"}]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(base, f)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            if rel in ("core/buildstamp.py",) or rel.startswith("tests/"):
                continue
            try:
                src = io.open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            if 'sha256(' in src and '"webui.py"' in src and "buildstamp" not in src:
                hits.append(rel)
    assert not hits, "这些地方还在自己算构建戳（应改用 core.buildstamp）：%s" % hits


def test_release_guard_runs_offline():
    r = _run(["tools/release_guard.py", "--offline", "--no-collect", "--json"])
    out = r.stdout or ""
    assert "=== " in out and "通过 ===" in out, out[-400:]
    payload = None
    for line in out.splitlines():
        if line.startswith("{"):
            payload = json.loads(line)
    assert payload is not None, "guard 没收尾输出 JSON 报告"
    names = [row["check"] for row in payload["rows"]]
    # 规范 v2（2026-11-18）：形态判据从"单一 root commit"改成
    # "root + 外部贡献提交 + 1 笔收尾提交"（Contributors 只认 author）
    assert "history is a single root commit" in names
    assert "site build stamp current" in names


def test_three_defences_are_wired():
    hook = os.path.join(ROOT, ".githooks", "pre-push")
    assert os.path.exists(hook), "缺 .githooks/pre-push"
    h = io.open(hook, encoding="utf-8").read()
    assert "converge_history" in h, "钩子没告诉人怎么收敛"
    # 维护者决定：**不留绕过开关**——留口子等于规则可以被一行环境变量取消
    assert "ALLOW_MULTI_COMMIT" not in h, "钩子又长出绕过口子了"

    for wf in ("guard.yml", "drift.yml"):
        p = os.path.join(ROOT, ".github", "workflows", wf)
        assert os.path.exists(p), "缺工作流：" + wf
        body = io.open(p, encoding="utf-8").read()
        assert "release_guard" in body or "rev-list --count" in body, wf

    doc = io.open(os.path.join(ROOT, "docs", "RELEASE_PROCESS.md"),
                  encoding="utf-8").read()
    for k in ("发版漂移自检与收敛", "git config core.hooksPath .githooks",
              "tools/release_guard.py", "tools/converge_history.py"):
        assert k in doc, "RELEASE_PROCESS.md 缺：" + k


def test_converge_history_dry_run_works():
    r = _run(["tools/converge_history.py", "--dry-run"])
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode in (0, 2), out[-300:]
    assert "HEAD" in out and ("收敛" in out or "已经是单一" in out), out[-300:]


def test_notes_section_exists_for_current_version():
    from release_align_check import changelog_section
    s = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    import re
    ver = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', s).group(1)
    note, src = changelog_section(ver)
    assert note.strip(), "CHANGELOG 里没有 v%s 一节" % ver
    assert ver in src or "CHANGELOG" in src


def test_release_assets_tool_is_promoted():
    """资产流水线必须是一条命令，不是散落的野脚本（2026-11-15/16 各踩一次）。"""
    tool = os.path.join(ROOT, "tools", "release_assets.py")
    assert os.path.exists(tool), "缺 tools/release_assets.py"
    src = io.open(tool, encoding="utf-8").read()
    for sub in ("download", "verify", "upload"):
        assert sub in src, "工具缺子命令：" + sub
    # 三个踩过的坑必须体现在代码里，别再退回去
    assert "Expect:" in src, "缺代理友好的 Expect: 关掉（否则 POST/PATCH 会 400/空响应）"
    assert "--http1.1" in src, "缺 http1.1 强制"
    assert "SHA256SUMS" in src, "缺资产校验闭环"

    doc = io.open(os.path.join(ROOT, "docs", "RELEASE_PROCESS.md"),
                  encoding="utf-8").read()
    assert "tools/release_assets.py" in doc, "RELEASE_PROCESS.md 没提资产流水线工具"


def test_history_shape_signature_scheme():
    """本仓形态：root 1 笔 + 贡献者署名提交（empty）+ 维护者收尾 1 笔。

    浅克隆（CI 的 test 分片是 fetch-depth: 1）看不到完整历史，跳过；
    该不变量由 `.github/workflows/guard.yml`（fetch-depth: 0）里的
    `release_guard.py --offline` 核对——下面顺带断言那个作业还在。
    """
    wf = io.open(os.path.join(ROOT, ".github", "workflows", "guard.yml"),
                 encoding="utf-8").read()
    assert "fetch-depth: 0" in wf, "guard.yml 必须全历史克隆"
    assert "release_guard.py --offline" in wf, "guard.yml 没调 guard"
    if _git(["rev-parse", "--is-shallow-repository"]).strip() == "true":
        import pytest as _pytest
        _pytest.skip("浅克隆看不到完整历史，由 guard 作业核对")
    from release_guard import history_shape
    ok, detail = history_shape()
    assert ok, detail
    assert "root=1" in detail and "收尾 1 笔" in detail, detail


def test_history_shape_negative_controls():
    """负控（临时仓库）：只有 root / 收尾之后再补提交 / merge 都必须判红。"""
    import shutil
    import subprocess
    import tempfile

    tmp = tempfile.mkdtemp(prefix="shape_")
    repo = os.path.join(tmp, "r")
    try:
        def run(*a, **kw):
            return subprocess.run(a, cwd=repo, capture_output=True, text=True,
                                  encoding="utf-8", **kw)

        def guard_rc():
            r = subprocess.run([sys.executable, "-X", "utf8",
                                os.path.join(ROOT, "tools", "release_guard.py"),
                                "--offline", "--no-collect", "--history-only",
                                "--repo", repo],
                               capture_output=True, text=True, encoding="utf-8")
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        subprocess.run(["git", "init", "-q", repo], check=True)
        run("git", "config", "user.email", "m@t")
        run("git", "config", "user.name", "maint")
        io.open(os.path.join(repo, "a.txt"), "w", encoding="utf-8").write("a\n")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "root")

        # 1) 只有 root（没有收尾提交）→ 必红
        rc, out = guard_rc()
        assert rc != 0, out
        assert "收尾" in out, out

        # 2) root + 收尾（empty，同作者）→ 通过
        run("git", "commit", "-q", "--allow-empty", "-m", "closing")
        rc, out = guard_rc()
        assert rc == 0, out

        # 3) 收尾之后再补一笔维护者提交 → 必红
        run("git", "commit", "-q", "--allow-empty", "-m", "extra")
        rc, out = guard_rc()
        assert rc != 0, out

        # 4) merge 提交 → 必红
        run("git", "checkout", "-q", "-b", "side")
        run("git", "commit", "-q", "--allow-empty", "-m", "side")
        run("git", "checkout", "-q", "-")
        run("git", "merge", "-q", "--no-ff", "-m", "merge side", "side")
        rc, out = guard_rc()
        assert rc != 0, out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_contributors_list_matches_pr_authors():
    """docs/CONTRIBUTORS.md 记的每个人，main 上都要有以他作者身份的提交。

    浅克隆（CI 的 test 分片是 fetch-depth: 1）看不到历史里的他作者，本用例跳过；
    这条不变量由 `.github/workflows/guard.yml`（fetch-depth: 0）里的
    `release_guard.py --offline` 负责——下面的断言保证那个作业真的还在。
    """
    shallow = _git(["rev-parse", "--is-shallow-repository"]).strip()
    wf = io.open(os.path.join(ROOT, ".github", "workflows", "guard.yml"),
                 encoding="utf-8").read()
    assert "fetch-depth: 0" in wf, "guard.yml 必须全历史克隆（否则作者核对形同虚设）"
    assert "release_guard.py --offline" in wf, "guard.yml 没调 guard，跳过就没有替代者"
    if shallow == "true":
        import pytest as _pytest
        _pytest.skip("浅克隆看不到历史作者，由 guard 作业（fetch-depth: 0）核对")
    r = _run(["tools/sync_contributors.py", "--strict"])
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def test_contributors_check_catches_missing(tmp_path):
    """负控：文档记了一个不存在的人，必须报错（门禁不空转）。"""
    import shutil
    fake = tmp_path / "docs"
    fake.mkdir()
    (fake / "CONTRIBUTORS.md").write_text(
        "| 贡献者 | 内容 | 提交 |\n|---|---|---|\n"
        "| [@nobody-here-xyz](https://github.com/nobody-here-xyz) | x | y |\n",
        encoding="utf-8")
    # 复制工具到临时仓库根，并在其中跑（工具按自身位置定位 ROOT）
    (tmp_path / "tools").mkdir()
    shutil.copy(os.path.join(ROOT, "tools", "contributors_check.py"),
                tmp_path / "tools" / "contributors_check.py")
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "m@t"])
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "maint"])
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"],
                   check=True)
    r = subprocess.run([sys.executable, "-X", "utf8",
                        str(tmp_path / "tools" / "contributors_check.py"),
                        "--quiet"], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode != 0, "文档里记了不存在的人却没报错"
