#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对「记录在案的贡献者，在 main 上是否真有以他作者身份落库的提交」。

为什么需要它（2026-11-18 实测）：GitHub 的 **Contributors 只统计 commit 的 `author`**，
`Co-authored-by:` 不进那个列表。我们据此把历史形态改成了
「root（维护者）+ 外部贡献提交（作者=贡献者）+ 1 笔收尾提交」，见
`docs/RELEASE_PROCESS.md` §3.1。

这条工具把"说好了要给作者身份"变成**可验证**的：读 `docs/CONTRIBUTORS.md` 的表格，
逐个 login 在 `git log` 里找他署名的提交。谁被记了名却没提交，直接非零退出。

    python tools/contributors_check.py            # 人类可读
    python tools/contributors_check.py --quiet    # 只返回码（给 guard/CI 用）
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "CONTRIBUTORS.md")
# 行首是 `| [@login](url)`，login 之后可能还有括号注释（如「（Roni Saguey）」）
ROW = re.compile(r"^\|\s*\[@([A-Za-z0-9][A-Za-z0-9-]*)\]\(")


def log_authors():
    out = subprocess.run(["git", "log", "--format=%an%x09%ae%x09%s"],
                         cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    rows = []
    for line in out.splitlines():
        name, _t1, rest = line.partition("\t")
        email, _t2, subj = rest.partition("\t")
        rows.append((name.strip(), email.strip(), subj.strip()))
    return rows


def documented_logins():
    if not os.path.exists(DOC):
        return []
    logins = []
    for line in io.open(DOC, encoding="utf-8").read().splitlines():
        m = ROW.match(line.strip())
        if m:
            logins.append(m.group(1))
    return logins


def main(argv=None):
    ap = argparse.ArgumentParser(description="贡献者作者身份核对")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logins = documented_logins()
    authors = log_authors()
    if not logins:
        if not a.quiet:
            print("docs/CONTRIBUTORS.md 里没有登记任何贡献者（表格为空）")
        return 0

    missing = []
    for login in logins:
        key = login.lower()
        hits = [(n, e, s) for (n, e, s) in authors
                if key in e.lower() or key in n.lower()]
        if not a.quiet:
            if hits:
                print("  ✓ %-20s %d 笔：%s" % (login, len(hits), hits[0][2][:60]))
            else:
                print("  ✗ %-20s 没有以他作者身份落库的提交" % login)
        if not hits:
            missing.append(login)

    if missing:
        print("\n这些贡献者被记了名，但 main 上没有他们的作者提交"
              "（GitHub Contributors 不会显示他们）：%s" % ", ".join(missing))
        return 1
    if not a.quiet:
        print("\n全部 %d 位贡献者都有作者提交 ✓" % len(logins))
    return 0


if __name__ == "__main__":
    sys.exit(main())
