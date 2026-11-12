#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Release 正文填充：把 `docs/RELEASE_BODY.md` 的占位符按**当轮事实**填成可发布正文。

为什么要有这个工具（2026-11-12 发版踩过的坑）：上一轮是"临时脚本塞占位符"，
把整篇 notes 与表格塞进了**行内反引号**，结果线上正文出现
「；执行与能力契约：…」孤立行、双表头、嵌套反引号。模板与填充必须分工明确：

- **行内占位符**只放短值（版本/SHA/日期/计数/路径）；
- **成块占位符**（`{{ASSET_TABLE}}` `{{RELEASE_NOTES}}`）各自整行或整节出现；
- **时效性断言**（资产来源、镜像来源、历史形态）由本工具按当轮事实生成，
  模板不假设"本轮是否重建"。

用法（在仓库根目录，且 `dist_package/` 已有四平台包 + SHA256SUMS.txt）：

    python tools/release_fill_body.py                # 写到 _scratch/release_body_filled.md
    python tools/release_fill_body.py --out body.md  # 指定输出
    python tools/release_fill_body.py --no-assets    # 资产未就绪时只填其余部分

时序断言由命令行开关显式声明（**不猜**）：
    --assets-rebuilt / --assets-reused
    --image-pushed   / --image-reused
    --history-single-root / --history-with-process
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = ("ticket-monitoring-win64.zip",
          "ticket-monitoring-linux-x64.zip",
          "ticket-monitoring-macos-arm64.zip",
          "ticket-monitoring-macos-x64.zip")


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def tracked_tests() -> str:
    m = re.search(r"已跟踪\s*([0-9]+)\s*项", _read(os.path.join(ROOT, "README.md")))
    return m.group(1) if m else "?"


def ui_counts() -> tuple:
    """UI 自检计数：优先读 uitest 结果缓存，读不到就返回模板默认占位。"""
    try:
        s = _read(os.path.join(ROOT, "docs", "uitest_result.txt"))
        m = re.search(r"(\d+)\s*/\s*(\d+)\s*通过", s)
        if m:
            return m.group(1), m.group(2)
    except OSError:
        pass
    return "", ""


def asset_rows(dist_dir):
    rows = []
    for name in ASSETS:
        p = os.path.join(dist_dir, name)
        if not os.path.exists(p):
            raise SystemExit("缺资产：%s（先下载四平台包到 dist_package/）" % p)
        rows.append((name, os.path.getsize(p), _sha256(p)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="填充 Release 正文")
    ap.add_argument("--dist", default=os.path.join(ROOT, "dist_package"))
    ap.add_argument("--out", default=os.path.join(ROOT, "_scratch",
                                                 "release_body_filled.md"))
    ap.add_argument("--ui-count", default="",
                    help="UI 自检通过数（结果文件不入库，优先显式给）")
    ap.add_argument("--ui-total", default="")
    ap.add_argument("--sums-file", default="",
                    help="复用既有 SHA256SUMS.txt（不向本地包要哈希）")
    ap.add_argument("--no-assets", action="store_true",
                    help="资产表留空（资产未就绪时）")
    ap.add_argument("--assets-rebuilt", action="store_true")
    ap.add_argument("--assets-reused", action="store_true")
    ap.add_argument("--assets-same-build", action="store_true")
    ap.add_argument("--image-pushed", action="store_true")
    ap.add_argument("--image-reused", action="store_true")
    ap.add_argument("--live-ok", action="store_true",
                    help="发布时本机控制台在线并与源码对账过")
    ap.add_argument("--live-off", action="store_true",
                    help="发布时本机控制台处于停用状态（未联机对账）")
    ap.add_argument("--history-single-root", action="store_true")
    ap.add_argument("--history-with-process", action="store_true")
    a = ap.parse_args(argv)

    ver = re.search(r'__version__\s*=\s*"([^"]+)"',
                    _read(os.path.join(ROOT, "main.py"))).group(1)
    head = _git("rev-parse", "HEAD")
    today = date.today().isoformat()
    body = _read(os.path.join(ROOT, "docs", "RELEASE_BODY.md"))
    body = body[body.find("# ticket-monitoring 初版"):]

    # ---- 成块：资产表（模板已有表头，这里只给行）----
    if a.sums_file:
        rows = []
        for line in _read(a.sums_file).splitlines():
            line = line.strip()
            if not line:
                continue
            digest, _sep, name = line.partition("  ")
            rows.append((name.strip(), 0, digest.strip()))
        table = "\n".join("| `%s` | `%s` |" % (n, d)
                          for n, _s, d in rows)
        table += ("\n| `SHA256SUMS.txt` | 上述四行的 `sha256sum` 清单"
                  "（可 `sha256sum -c` 校验） |")
    elif a.no_assets:
        table = "| _（本轮未附加安装包）_ | — |"
    else:
        rows = asset_rows(a.dist)
        table = "\n".join("| `%s` | `%s` |" % (n, d) for n, _s, d in rows)
        table += ("\n| `SHA256SUMS.txt` | 上述四行的 `sha256sum` 清单"
                  "（可 `sha256sum -c` 校验） |")

    # ---- 成块：版本变更（独立小节）----
    notes_path = "docs/release-notes-v%s.md" % ver
    try:
        notes = _read(os.path.join(ROOT, notes_path))
        notes = re.sub(r"^### ", "#### ", notes, flags=re.M)
        notes = re.sub(r"^## ", "### ", notes, flags=re.M)
        notes = re.sub(r"^# ", "### ", notes, flags=re.M)
    except OSError:
        notes = "（缺 %s）" % notes_path

    # ---- 时效性断言：按命令行显式声明，不猜 ----
    if a.assets_rebuilt:
        prov = ("四平台安装包**由本版本源码构建**（`release-build` 在 `%s` 上绿，"
                "`--version` = %s），与源码同批次。" % (head[:7], ver))
    elif a.assets_same_build:
        prov = ("四平台安装包与本版本源码同版（`release-build` 在 `%s` 上绿；"
                "包体取自同一版本的同名构建——`TicketMonitor.spec` 的 "
                "`datas=[]` 不打包 docs，两棵树只差文档，故与当前树等价），"
                "`--version` = %s。" % (head[:7], ver))
    elif a.assets_reused:
        prov = ("四平台安装包沿用本 Release 既有资产（上一冻结构建），"
                "`--version` = %s；与当前源码不是同一构建批次。" % ver)
    else:
        prov = "四平台安装包 `--version` = %s（来源见 `SHA256SUMS.txt`）。" % ver

    if a.image_pushed:
        image = ("**镜像已按本版本源码推送** `sha-%s`；`latest` 可能仍指向旧轮，"
                 "对账请用 `sha-%s`。" % (head[:7], head[:7]))
    elif a.image_reused:
        image = ("**本轮未重建镜像**，`latest` 属上一发布轮，"
                 "不作为当前源码的对账依据。")
    else:
        image = "容器镜像见 ghcr（按需 `push_image`）。"

    if a.live_ok:
        live = ("公开站点与线上 8765 已完成联机对账（版本与源码一致）；")
    elif a.live_off:
        live = ("公开站点与源码已对齐；本机控制台按用户要求处于**停用**"
                "状态（发布时未在线，故未做联机对账）；")
    else:
        live = "公开站点与源码已对齐；"
    image_short = ("容器镜像见 `sha-%s`。" % head[:7]) if a.image_pushed \
        else "容器镜像本版本未重建。"
    if a.history_single_root:
        hist = "单一 root commit（公开历史即本版源码）"
    elif a.history_with_process:
        hist = ("滚动发布：历史含初始化提交与过程提交，`tag v1.0` 指向本轮源码 "
                "`%s`" % head[:7])
    else:
        hist = "发布以 `tag v1.0` 指向本版本源码 `%s` 为准" % head[:7]

    uc, ut = ((a.ui_count, a.ui_total) if a.ui_count
             else ui_counts())
    repl = {
        "{{VERSION}}": ver,
        "{{SOURCE_SHA}}": head,
        "{{DATE}}": today,
        "{{TRACKED_TESTS}}": tracked_tests(),
        "{{TEST_COUNTS}}": tracked_tests(),
        "{{UI_COUNT}}": uc,
        "{{UI_TOTAL}}": ut,
        "{{SCREENSHOT_BASE}}": ("https://raw.githubusercontent.com/"
                                "dengmeiluan/ticket-monitoring/main"),
        "{{RELEASE_NOTES_PATH}}": notes_path,
        "{{RELEASE_NOTES}}": notes,
        "{{ASSET_TABLE}}": table,
        "{{ASSET_PROVENANCE}}": prov,
        "{{IMAGE_PROVENANCE}}": image,
        "{{HISTORY_SHAPE}}": hist,
        "{{LIVE_STATUS}}": live,
        "{{IMAGE_PROVENANCE_SHORT}}": image_short,
    }
    for k, v in repl.items():
        body = body.replace(k, v)

    left = sorted(set(re.findall(r"\{\{[A-Z0-9_…]+\}\}", body)))
    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    print("已写 %s（%d 字节）" % (out, len(body)))
    print("版本 %s · HEAD %s · 已跟踪测试 %s · UI %s/%s"
          % (ver, head[:7], tracked_tests(), uc or "?", ut or "?"))
    if left:
        print("!! 仍有未替换占位符：", left)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
