#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建「root + 署名提交（真实改动）+ 收尾」的历史，并让文件列表保持初版形态。

为什么署名提交必须是**真实改动**（2026-11-18 实测）：
GitHub 的贡献统计**不把 empty 提交算作贡献**——
`graphs/contributors-data` 里 4 笔提交（含 2 笔 empty 署名）只算出 1 笔。
所以署名提交要在某个文件里留一行署名注释；**收尾提交必须把它删回**，
这样每个文件的 `git log -1` 仍指向收尾提交（标题就是「初版」）。

用法：
    python tools/rebuild_history.py            # 演练
    python tools/rebuild_history.py --yes      # 执行（会重写 main 的历史）
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

# 登录名 → (作者名, 邮箱, 留署名注释的文件, 一句话贡献说明)
SIG = {
    "1wizzy": (
        "1Wizzy",
        "54066145+1Wizzy@users.noreply.github.com",
        "webui.py",
        "明细台有效筛选分类标签渲染为转义 SVG 源码的修复（PR #13）",
    ),
    "flobby949": (
        "Flobby949",
        "58168056+Flobby949@users.noreply.github.com",
        "main.py",
        "启动即扫时定时任务永久暂停、POSIX 端口绑定、空扫描卡「加载中」三项修复（PR #5/#6/#7）",
    ),
    "shengcun-scanner": (
        "Shengcun-Scanner",
        "356718639+Shengcun-Scanner@users.noreply.github.com",
        "core/safezip.py",
        "core/safezip.py 的原始实现（PR #17）",
    ),
    "ismoss": (
        "ismoss",
        "100745527+ismoss@users.noreply.github.com",
        "crawlers/base.py",
        "登录判定与阶段机、托运分档（PR #20）",
    ),
    "rogeryong": (
        "RogerYong",
        "12882512+RogerYong@users.noreply.github.com",
        "main.py",
        "能力边界轮不再算渠道断供（PR #21）",
    ),
}
MARK = "# 署名标记：%s\n"


def sh(*a, check=True, quiet=True):
    r = subprocess.run(a, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("失败: %s\n%s" % (" ".join(a), (r.stderr or "")[-300:]))
    if not quiet:
        print((r.stdout or "").strip()[:300])
    return (r.stdout or "").strip()


def version():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', src)
    return m.group(1) if m else "0.0.0"


def documented():
    if not os.path.exists(DOC):
        return []
    out = []
    for line in io.open(DOC, encoding="utf-8").read().splitlines():
        m = re.match(r"^\|\s*\[@([A-Za-z0-9][A-Za-z0-9-]*)\]", line.strip())
        if m and m.group(1).lower() in SIG:
            out.append(m.group(1).lower())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="重建 root + 署名提交 + 收尾")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)

    root = sh("git", "rev-list", "--max-parents=0", "HEAD")
    title = "机票监控台 · 初版（滚动更新） v%s" % version()
    people = documented()
    print("root:", root[:7], "| 版本:", version(), "| 署名:", people or "（无）")
    if not a.yes:
        print("演练结束；加 --yes 执行")
        return 0

    # 1) 把当前工作树（含未提交改动）收进 root
    sh("git", "add", "-A")
    sh("git", "reset", "--soft", root)
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "--amend", "-m", title)
    print("root:", sh("git", "rev-parse", "--short", "HEAD"))

    # 2) 每位贡献者一笔**真实改动**的署名提交
    marks = []
    for login in people:
        name, email, path, why = SIG[login]
        line = MARK % why
        full = os.path.join(ROOT, path)
        src = io.open(full, encoding="utf-8").read()
        io.open(full, "w", encoding="utf-8", newline="\n").write(
            src.rstrip("\n") + "\n" + line)
        sh("git", "add", path)
        sh("git", "commit", "-q", "--author=%s <%s>" % (name, email),
           "-m", "署名：%s —— %s" % (name, why),
           "-m", "本笔是真实改动（在文件里加一行署名注释）：GitHub 的贡献统计不计 "
                 "empty 提交，所以署名提交必须有内容差异；收尾提交会把该行删回。")
        marks.append((path, line))
        print("  署名:", sh("git", "rev-parse", "--short", "HEAD"), name)

    # 3) 收尾提交：删回署名注释 → 文件最后修改都指向它
    for path, line in marks:
        full = os.path.join(ROOT, path)
        src = io.open(full, encoding="utf-8").read()
        io.open(full, "w", encoding="utf-8", newline="\n").write(
            src.replace(line, ""))
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "-m", title,
       "-m", "收尾提交：删回署名注释，使每个文件的最后修改都指向本笔（标题即初版）；"
             "tag v1.0 / Release 资产 / 正文 SHA 指向它。")
    print("收尾:", sh("git", "rev-parse", "--short", "HEAD"))
    print(sh("python", "-X", "utf8", "tools/release_guard.py", "--offline",
             "--no-collect", "--history-only", check=False, quiet=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
