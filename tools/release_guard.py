#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发版漂移体检：一条命令看清"仓库现在到底遵不遵守发版规范"。

为什么要有它（2026-11-16 的实况）：`main` 上叠了 6 笔提交、Pages 部署堆到 7 条、
Release 停在 `229a947` 而 HEAD 已经走到 `69364a0`——对外三个入口（仓库首页、
Deployments、Release）互相矛盾，但**没有任何东西会报错**：CI 照样绿，因为 CI 只跑
测试，不校验"公开发布形态"。于是漂移只能靠人肉发现。

判据（与 `docs/RELEASE_PROCESS.md` 一一对应）：

| 项 | 要求 | 谁受害 |
|---|---|---|
| 单一 root commit | `git rev-list --count HEAD == 1` | 公开历史可信度、Release 的"1 commit"标注 |
| 工作树干净 | 无未提交改动 | 资产与源码可能不同批 |
| 站点构建戳 | 本地烘焙戳 == 运行时口径 | 在线演示与源码不符 |
| README 计数 | 与 `pytest --collect-only` 一致 | 门禁假红/假绿 |
| 版本说明 | CHANGELOG 里有当前版本一节 | 用户看不到变更 |
| 标签/正文/部署/镜像/资产 | 见 `tools/release_align_check.py` | 见其输出 |

用法：

    python tools/release_guard.py              # 全量（含远端，需要 token）
    python tools/release_guard.py --offline    # 只跑本地项（CI 用，不需要 token）
    python tools/release_guard.py --hint       # 漂移时打印收敛步骤
    python tools/release_guard.py --json       # 机器可读（定时任务用来开 issue）

退出码：0 全部通过；1 有漂移；2 环境问题（缺 token / git 异常）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIGN = os.path.join(ROOT, "tools", "release_align_check.py")
sys.path.insert(0, ROOT)

PASS, FAIL = "OK", "FAIL"
_rows = []


def row(name, ok, detail=""):
    _rows.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print("%-4s %-42s %s" % (PASS if ok else FAIL, name, str(detail)[:180]),
          flush=True)
    return ok


def sh(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def version():
    try:
        s = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', s)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


# ------------------------------------------------------------------ 本地项
def check_history():
    """单一 root commit：公开历史的形状。"""
    count = sh("git", "rev-list", "--count", "HEAD")
    root = sh("git", "rev-list", "--max-parents=0", "HEAD")
    head = sh("git", "rev-parse", "HEAD")
    try:
        n = int(count)
    except ValueError:
        return row("history is a single root commit", False, "git 异常：%s" % count)
    ok = (n == 1) and (root == head)
    return row("history is a single root commit", ok,
               "提交数 %d%s" % (n, "" if ok else "（先收敛：python tools/converge_history.py）"))


def check_clean():
    dirty = [x for x in sh("git", "status", "--porcelain").splitlines() if x.strip()]
    return row("working tree clean", not dirty,
               "%d 个未提交改动" % len(dirty) if dirty else "")


def check_site_stamp():
    try:
        from core.buildstamp import stamp_of
        want = "code:" + stamp_of(ROOT)
    except Exception as e:
        return row("site build stamp current", False, "算不出戳：%r" % (e,))
    site = os.path.join(ROOT, "docs", "site", "index.html")
    try:
        page = open(site, encoding="utf-8").read()
    except OSError:
        return row("site build stamp current", False, "缺 docs/site/index.html")
    m = re.search(r'<meta name="tm-build" content="([^"]+)"', page)
    parts = (m.group(1).split() if m else [])
    ok = len(parts) >= 2 and parts[0].startswith(version()) and parts[1] == want
    return row("site build stamp current", ok,
               (m.group(1) if m else "无戳") + ("" if ok else " want " + want))


def check_readme_counts(collect=True):
    if not collect:
        return row("README test counts current", True, "跳过（--no-collect）")
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest",
                          "--collect-only", "-q"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         env=env).stdout
    m = re.search(r"(\d+) tests collected", out)
    if not m:
        return row("README test counts current", False, "collect 失败")
    n = m.group(1)
    bad = []
    for f in ("README.md", "README_EN.md"):
        try:
            t = open(os.path.join(ROOT, f), encoding="utf-8").read()
        except OSError:
            bad.append(f)
            continue
        if ("%s 项" % n) not in t and ("%s tests" % n) not in t:
            bad.append(f)
    return row("README test counts current", not bad,
               ("README 写成别的数：%s（应为 %s）" % (", ".join(bad), n)) if bad else n)


def check_notes():
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from release_align_check import changelog_section
        note, src = changelog_section(version())
    except Exception as e:
        return row("release notes for current version", False, repr(e)[:80])
    return row("release notes for current version", bool(note.strip()),
               src or "CHANGELOG 里没有 v%s 一节" % version())


# ------------------------------------------------------------------ 远端项
def check_remote():
    """远端项交给校验器本身（唯一真源），本工具只汇总它的结论。"""
    if not os.path.exists(ALIGN):
        return row("release alignment (remote)", False, "缺 tools/release_align_check.py")
    r = subprocess.run([sys.executable, "-X", "utf8", ALIGN], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.startswith(("FAIL", "==="))]
    fails = [ln for ln in tail if ln.startswith("FAIL")]
    ok = r.returncode == 0
    detail = "全部通过" if ok else "；".join(f[5:60].strip() for f in fails[:4])
    if not ok and not fails:
        detail = (r.stderr or r.stdout or "")[-160:].replace("\n", " ")
    return row("release alignment (tag/body/deploy/image/assets)", ok, detail)


HINT = """
收敛步骤（漂移时按这个顺序做，全部通过后再谈发版）：

  1) python tools/converge_history.py            # 多提交 → 单一 root commit（保留树）
  2) git push --force origin main                # 推公开历史
  3) 等 CI 绿：gh run list --branch main -L 1
  4) 触发构建：release-build（push_image=true）
  5) 下载四平台资产 → 校验 → 上传替换 → 更新正文（tools/release_fill_body.py）
  6) git tag -f v1.0 HEAD && git push origin refs/tags/v1.0 --force
  7) python tools/prune_deployments.py           # 部署只留 1 条
  8) python tools/release_guard.py               # 必须 0 漂移

细节见 docs/RELEASE_PROCESS.md「发版漂移自检与收敛」。
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="发版漂移体检")
    ap.add_argument("--offline", action="store_true", help="只跑本地项（CI 用）")
    ap.add_argument("--no-collect", action="store_true", help="跳过 pytest 用例数采集")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--hint", action="store_true", help="漂移时打印收敛步骤")
    ap.add_argument("--issue-body", default="", help="把报告写成 GitHub issue 正文")
    a = ap.parse_args(argv)

    print("版本 %s · HEAD %s · 分支 main" % (version(), sh("git", "rev-parse", "--short", "HEAD")),
          flush=True)
    check_history()
    check_clean()
    check_notes()
    check_site_stamp()
    check_readme_counts(not a.no_collect)
    if not a.offline:
        check_remote()

    bad = [r for r in _rows if not r["ok"]]
    print("\n=== %d/%d 通过 ===" % (len(_rows) - len(bad), len(_rows)), flush=True)
    if bad:
        print("漂移项：%s" % "；".join(r["check"] for r in bad), flush=True)
        if a.hint:
            print(HINT, flush=True)

    if a.issue_body:
        lines = ["<!-- release-drift-report -->",
                 "自动生成，请勿手改（`tools/release_guard.py --issue-body`）。",
                 "", "版本 `%s` · HEAD `%s`" % (version(), sh("git", "rev-parse", "--short", "HEAD")),
                 "", "| 检查 | 结果 | 说明 |", "| --- | --- | --- |"]
        for r in _rows:
            lines.append("| %s | %s | %s |"
                         % (r["check"], "✅" if r["ok"] else "❌",
                            r["detail"].replace("|", "\\|")))
        if bad:
            lines += ["", "## 收敛步骤", "```", HINT.strip(), "```"]
        open(a.issue_body, "w", encoding="utf-8", newline="\n").write(
            "\n".join(lines) + "\n")
        print("issue 正文已写：%s" % a.issue_body, flush=True)

    if a.json:
        print(json.dumps({"ok": not bad, "rows": _rows}, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
