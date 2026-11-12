#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 PR 列表**去重**核对贡献者，并维护 `docs/CONTRIBUTORS.md`。

维护者的要求（原话）：「每次提交的时候，都根据 pr 列表，去重人员」。
这条工具就是那句话的可执行版本：

1. 拉全部 PR（含已关闭/已合并）→ 取作者 → **按登录名去重** → 排除维护者与机器人；
2. 与 `docs/CONTRIBUTORS.md` 里登记的名单对账：
   - PR 里有人、文档里没有 → `--strict` 下**失败**（防止漏人）；
   - 文档里有人、PR 列表里没有 → 只提示（可能是 issue 报告者，保留记录）；
3. `--write` 按 PR 列表重写文档里的表格（去重、排序、附上 PR 号）。

用法：
    python tools/sync_contributors.py            # 只对账
    python tools/sync_contributors.py --strict   # 漏人就非零退出（guard/CI 用）
    python tools/sync_contributors.py --write    # 重写 docs/CONTRIBUTORS.md 表格
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "dengmeiluan/ticket-monitoring"
MAINTAINER = "dengmeiluan"
BOTS = {"github-actions", "dependabot", "renovate"}
DOC = os.path.join(ROOT, "docs", "CONTRIBUTORS.md")
TABLE_HEAD = "| 贡献者 | 署名方式 | PR |"
BEGIN = "<!-- CONTRIBUTORS:TABLE:BEGIN -->"
END = "<!-- CONTRIBUTORS:TABLE:END -->"
ROW = re.compile(r"^\|\s*\[@([A-Za-z0-9][A-Za-z0-9-]*)\]")


def token():
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t.strip()
    p = os.path.join(ROOT, "scripts", "ghtoken.txt")
    if os.path.exists(p):
        return io.open(p, encoding="utf-8").read().strip()
    return ""


def pull_authors(tok):
    """→ {login: [pr_number, ...]}（已去重，按登录名排序）。"""
    out = {}
    page = 1
    while True:
        r = subprocess.run(
            ["curl.exe" if os.name == "nt" else "curl", "-sS", "--http1.1",
             "-H", "Expect:", "-H", "Authorization: Bearer " + tok,
             "-H", "Accept: application/vnd.github+json",
             "https://api.github.com/repos/%s/pulls?state=all&per_page=100&page=%d"
             % (REPO, page)], capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        try:
            batch = json.loads(r.stdout or "[]")
        except ValueError:
            break
        if not batch:
            break
        for p in batch:
            login = str((p.get("user") or {}).get("login") or "")
            if not login or login == MAINTAINER or login.lower() in BOTS:
                continue
            out.setdefault(login, []).append(int(p["number"]))
        page += 1
        if page > 10:
            break
    return {k: sorted(set(v)) for k, v in sorted(out.items())}


def committed_logins(tok):
    """main 上以某人作者身份落库的账号（commits API 的 author.login）。"""
    r = subprocess.run(
        ["curl.exe" if os.name == "nt" else "curl", "-sS", "--http1.1",
         "-H", "Expect:", "-H", "Authorization: Bearer " + tok,
         "-H", "Accept: application/vnd.github+json",
         "https://api.github.com/repos/%s/commits?sha=main&per_page=100" % REPO],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        items = json.loads(r.stdout or "[]")
    except ValueError:
        return set()
    return {str((c.get("author") or {}).get("login"))
            for c in items if (c.get("author") or {}).get("login")}


def documented():
    if not os.path.exists(DOC):
        return {}
    txt = io.open(DOC, encoding="utf-8").read()
    return {m.group(1): True for m in (ROW.match(l.strip())
                                       for l in txt.splitlines()) if m}


def render(authors, committed):
    lines = [TABLE_HEAD, "|---|---|---|"]
    for login, prs in authors.items():
        commit = "作者提交（`git log --author=%s`）" % login \
            if login in committed else "历史贡献（已随 PR 合入，作者提交在早期历史中）"
        lines.append("| [@%s](https://github.com/%s) | %s | %s |"
                     % (login, login, commit,
                        "、".join("#%d" % n for n in prs)))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PR 列表去重核对贡献者")
    ap.add_argument("--strict", action="store_true", help="漏人就非零退出")
    ap.add_argument("--write", action="store_true", help="重写文档表格")
    a = ap.parse_args(argv)
    tok = token()
    if not tok:
        # 没有 token 就没法拉 PR 列表：这不代表"人不全"，只是核对不了。
        # 保持退出码 0，避免在本地/无 token 环境里假红；CI 与 guard 都注入了
        # GH_TOKEN（见 .github/workflows/guard.yml），那里是严格核对。
        print("⚠ 无 token（GH_TOKEN / scripts/ghtoken.txt），跳过 PR 列表对账")
        return 0

    authors = pull_authors(tok)
    committed = committed_logins(tok)
    doc = documented()

    print("PR 作者（去重）%d 位：" % len(authors))
    missing = []
    for login, prs in authors.items():
        mark = "✓ 有作者提交" if login in committed else "· 历史贡献"
        if login not in doc:
            mark += "  ⚠ 文档未登记"
            missing.append(login)
        print("  %-20s %-28s %s" % (login, mark,
                                    "、".join("#%d" % n for n in prs)))
    extra = [k for k in doc if k not in authors]
    if extra:
        print("文档里有、PR 列表里没有（可能是 issue 报告者，保留）：%s"
              % ", ".join(sorted(extra)))

    if a.write:
        txt = io.open(DOC, encoding="utf-8").read()
        table = render(authors, committed)
        b, e = BEGIN, END
        if b in txt and e in txt:
            head, rest = txt.split(b, 1)
            _old, tail = rest.split(e, 1)
            txt = head + b + "\n" + table + "\n" + e + tail
        else:
            txt = (txt.rstrip() + "\n\n## 名单（自动生成，勿手改）\n\n"
                   + b + "\n" + table + "\n" + e + "\n")
        io.open(DOC, "w", encoding="utf-8", newline="\n").write(txt)
        print("已重写生成区（%d 位）" % len(authors))

    if missing and a.strict:
        print("\n漏登记：%s（--write 可自动补齐）" % ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
