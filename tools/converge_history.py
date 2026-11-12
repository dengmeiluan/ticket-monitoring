#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `main` 上的多笔提交收敛成**单一 root commit**（保留最终文件树，一字不改）。

发版规范要求对外历史是这个形状（Release 页会标「1 commit to main since this
release」，贡献者也会按它理解仓库状态）。但日常开发难免在 main 上叠几笔提交，
于是每次发版前都要做同一套动作——手工做太容易出错（`reset --soft` 用错基、
树被悄悄改了、忘了改标题里的版本号）。

本工具只做**一件事**：把 N 笔压成 1 笔，且**校验树哈希前后一致**；
推送、跑 CI、重建资产、移标签、prune 部署这些"对外动作"它不代劳，
跑完会打印清单（见 docs/RELEASE_PROCESS.md）。

    python tools/converge_history.py --dry-run     # 先看会发生什么
    python tools/converge_history.py --yes         # 真做（工作树必须干净）
    python tools/converge_history.py --yes --message-file msg.txt   # 自定义正文

做完之后：

    git push --force origin main
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE_FMT = "机票监控台 · 初版（滚动更新） v%s"


def sh(*args, check=False):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("命令失败：%s\n%s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def version():
    s = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', s)
    return m.group(1) if m else "0.0.0"


def build_message(root_msg, ver, extra=""):
    """保留 root 提交原有正文，只把标题里的版本号对齐当前版本。"""
    lines = root_msg.splitlines()
    title = TITLE_FMT % ver
    if lines:
        lines[0] = title
    else:
        lines = [title]
    if extra.strip():
        lines += ["", extra.strip()]
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="多提交 → 单一 root commit（保留文件树）")
    ap.add_argument("--yes", action="store_true", help="真的执行（否则只演练）")
    ap.add_argument("--dry-run", action="store_true", help="同默认行为：只演练")
    ap.add_argument("--message-file", default="", help="替换提交正文（标题仍自动对齐版本）")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="工作树不干净也继续（不推荐：会让未提交改动混进树里）")
    a = ap.parse_args(argv)

    head = sh("git", "rev-parse", "HEAD")
    count = int(sh("git", "rev-list", "--count", "HEAD") or 0)
    root = sh("git", "rev-list", "--max-parents=0", "HEAD")
    tree_before = sh("git", "rev-parse", "HEAD^{tree}")
    ver = version()
    dirty = [x for x in sh("git", "status", "--porcelain").splitlines() if x.strip()]

    print("当前 HEAD %s · 提交数 %d · root %s" % (head[:7], count, root[:7] or "—"))
    print("目标版本 %s · 树 %s" % (ver, tree_before[:12]))
    if count <= 1 and head == root:
        print("已经是单一 root commit，无需收敛。")
        return 0
    if dirty and not a.allow_dirty:
        print("工作树不干净（%d 项），先提交或 stash：" % len(dirty))
        for d in dirty[:8]:
            print("  " + d)
        print("（确实要带着未提交改动收敛，才加 --allow-dirty）")
        return 2

    root_msg = sh("git", "log", "-1", "--format=%B", root)
    if a.message_file:
        custom = open(os.path.join(ROOT, a.message_file), encoding="utf-8").read()
        msg = build_message(root_msg, ver, "")
        # 标题自动对齐，正文用自定义内容
        msg = msg.splitlines()[0] + "\n\n" + custom.strip() + "\n"
    else:
        msg = build_message(root_msg, ver)
    print("\n--- 新的提交信息 ---")
    print(msg)

    if not a.yes:
        print("（演练模式：加 --yes 才会真的改写历史）")
        return 0

    sh("git", "reset", "--soft", root, check=True)
    msg_path = os.path.join(ROOT, "_scratch", "_converge_msg.txt")
    os.makedirs(os.path.dirname(msg_path), exist_ok=True)
    with open(msg_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(msg)
    sh("git", "commit", "--amend", "-q", "-F", msg_path, check=True)

    new_head = sh("git", "rev-parse", "HEAD")
    tree_after = sh("git", "rev-parse", "HEAD^{tree}")
    new_count = int(sh("git", "rev-list", "--count", "HEAD") or 0)
    print("\nHEAD %s · 提交数 %d · 树 %s" % (new_head[:7], new_count, tree_after[:12]))
    if tree_after != tree_before:
        print("!! 树哈希变了（%s → %s）：这不正常，用 git reset --hard %s 回退并人工排查"
              % (tree_before[:12], tree_after[:12], head))
        return 3
    if new_count != 1:
        print("!! 收敛后仍不是单一提交（%d）" % new_count)
        return 3
    print("树哈希未变、提交数 = 1 ✓")
    print("\n接下来（发版清单）：")
    print("  1) git push --force origin main")
    print("  2) 等 CI 绿 → 触发 release-build（push_image=true）")
    print("  3) 下载/校验/上传四平台资产 → tools/release_fill_body.py 更新正文")
    print("  4) git tag -f v1.0 HEAD && git push origin refs/tags/v1.0 --force")
    print("  5) python tools/prune_deployments.py")
    print("  6) python tools/release_guard.py   # 必须 0 漂移")
    return 0


if __name__ == "__main__":
    sys.exit(main())
