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
