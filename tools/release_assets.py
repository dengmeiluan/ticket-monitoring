#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发版资产流水线：**下载 → 校验 → 上传**，三件容易做错的事收进一条命令。

为什么要有它（2026-11-15/16 各踩一次）：

1. GitHub artifact 的 `archive_download_url` 会 302 到 Azure Blob。用 urllib 把
   `Authorization` 一起带过去 → `401`；必须让 curl 默认"跨主机不转发凭据"；
2. 四个 artifact 里各含**同名**的 zip + `.sha256`，解压时改名就会串包；
3. 上传走代理时 `Expect: 100-continue` 会让 POST/PATCH 拿到空响应或 400，
   PowerShell 的 `Invoke-RestMethod -InFile` 传大文件还会「发送时发生错误」——
   必须 `curl -H "Expect:" --http1.1 --data-binary @file`，并且失败要重试。

解压 artifact 也走 `core.safezip.safe_extract()`：artifact 里的 zip 同样是"别人给的包"
（虽然来自本仓 CI），统一入口才有统一判据——`test_repo_has_single_extraction_entry`
会扫全仓，发现裸 `extractall(` 直接红。

用法：

    python tools/release_assets.py download            # 取最近一次成功的 release-build
    python tools/release_assets.py download 43836740755
    python tools/release_assets.py verify              # zip 完整性 + 与 .sha256 对照 + 写 SHA256SUMS
    python tools/release_assets.py upload              # 替换 Release 的 5 个资产并核对 digest
    python tools/release_assets.py all                 # download → verify → upload

token 从环境变量 `GH_TOKEN` 取，没有就读 `scripts/ghtoken.txt`（本地开发用，已在 .gitignore）。
`--dry-run` 只打印将要做什么，不下载/不上传。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "dengmeiluan/ticket-monitoring"
DIST = os.path.join(ROOT, "dist_package")
ASSETS = ["ticket-monitoring-win64.zip",
          "ticket-monitoring-linux-x64.zip",
          "ticket-monitoring-macos-arm64.zip",
          "ticket-monitoring-macos-x64.zip"]
SUMS = "SHA256SUMS.txt"


# ----------------------------------------------------------------- 基础
def token() -> str:
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t.strip()
    p = os.path.join(ROOT, "scripts", "ghtoken.txt")
    if os.path.exists(p):
        return io.open(p, encoding="utf-8").read().strip()
    raise SystemExit("缺 token：设 GH_TOKEN，或放 scripts/ghtoken.txt")


def curl(args, retries=4, dry=False):
    """带重试的 curl。固定关掉 `Expect: 100-continue` 并强制 http1.1（代理友好）。"""
    cmd = ["curl.exe" if os.name == "nt" else "curl", "-sS", "--http1.1",
           "-H", "Expect:"] + args
    if dry:
        print("    [dry-run] " + " ".join(cmd[:8]) + " …")
        return True
    for i in range(1, retries + 1):
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return True
        print("    curl 失败(第 %d/%d 次) exit=%s %s"
              % (i, retries, r.returncode, (r.stderr or "").strip()[:80]))
    return False


def api(path):
    r = subprocess.run(
        ["curl.exe" if os.name == "nt" else "curl", "-sS", "--http1.1",
         "-H", "Expect:", "-H", "Authorization: Bearer " + token(),
         "-H", "Accept: application/vnd.github+json",
         "https://api.github.com/repos/%s%s" % (REPO, path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not (r.stdout or "").strip():
        raise SystemExit("GitHub API 无响应：%s（%s）" % (path, (r.stderr or "")[:120]))
    return json.loads(r.stdout)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_build_run():
    runs = api("/actions/workflows/release-build.yml/runs?per_page=10")["workflow_runs"]
    for r in runs:
        if r.get("conclusion") == "success":
            return r["id"], r["head_sha"][:7]
    raise SystemExit("没找到成功的 release-build 记录")


# ----------------------------------------------------------------- 三步
def do_download(run_id=None, dry=False):
    if not run_id:
        run_id, sha = latest_build_run()
        print("使用最近的 release-build：run=%s sha=%s" % (run_id, sha))
    arts = api("/actions/runs/%s/artifacts" % run_id)["artifacts"]
    print("artifacts: %d" % len(arts))
    os.makedirs(DIST, exist_ok=True)
    for a in arts:
        name, url = a["name"], a["archive_download_url"]
        tmp = os.path.join(DIST, "_dl_" + name)
        print("download %-40s %.1f MB" % (name, a["size_in_bytes"] / 1e6), flush=True)
        ok = curl(["-L", "--fail", "--retry", "3", "--retry-delay", "3",
                   "-H", "Authorization: Bearer " + token(), "-o", tmp, url],
                  dry=dry)
        if not ok:
            print("  !! 下载失败")
            return 1
        if dry:
            continue
        # 包内文件名与 Release 资产同名，**不许改名**；解压走统一入口（见模块 docstring）
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from core.safezip import safe_extract
        with zipfile.ZipFile(tmp) as z:
            safe_extract(z, DIST)
        os.remove(tmp)
        print("  ok", flush=True)
    if not dry:
        print("\n=== dist_package ===")
        for f in sorted(os.listdir(DIST)):
            print("  %-44s %.1f MB" % (f, os.path.getsize(os.path.join(DIST, f)) / 1e6))
    return 0


def do_verify():
    rows, bad = [], []
    for name in ASSETS:
        p = os.path.join(DIST, name)
        if not os.path.exists(p):
            bad.append((name, "缺文件"))
            continue
        try:
            broken = zipfile.ZipFile(p).testzip()
        except Exception as e:
            bad.append((name, "zip 打不开：%s" % str(e)[:40]))
            continue
        digest = sha256(p)
        side = p + ".sha256"
        want = (io.open(side, encoding="utf-8").read().strip().split()[0]
                if os.path.exists(side) else "")
        ok = broken is None and (not want or want == digest)
        print("%-40s %7.1f MB  zip_ok=%s  sha_match=%s"
              % (name, os.path.getsize(p) / 1e6, broken is None,
                 "n/a" if not want else (want == digest)))
        if not ok:
            bad.append((name, "校验失败"))
        rows.append((name, digest))
    if bad:
        print("资产有问题：%s" % bad)
        return 1
    out = "".join("%s  %s\n" % (d, n) for n, d in rows)
    io.open(os.path.join(DIST, SUMS), "w", encoding="ascii", newline="").write(out)
    print("\n已写 dist_package/%s：\n%s" % (SUMS, out))
    return 0


def do_upload(dry=False):
    rel = api("/releases/tags/v1.0")
    rid = rel["id"]
    print("release id=%s 现有资产 %d 个" % (rid, len(rel.get("assets") or [])))
    for a in rel.get("assets") or []:
        print("  delete %s" % a["name"])
        curl(["-X", "DELETE",
              "https://api.github.com/repos/%s/releases/assets/%s" % (REPO, a["id"]),
              "-H", "Authorization: Bearer " + token()], dry=dry)
    for name in ASSETS + [SUMS]:
        p = os.path.join(DIST, name)
        if not os.path.exists(p):
            print("  !! 缺本地文件：%s（先 verify）" % name)
            return 1
        url = ("https://uploads.github.com/repos/%s/releases/%s/assets?name=%s"
               % (REPO, rid, name))
        print("upload %-40s %.1f MB" % (name, os.path.getsize(p) / 1e6), flush=True)
        ok = curl(["-X", "POST", "-H", "Authorization: Bearer " + token(),
                   "-H", "Content-Type: application/octet-stream",
                   "--data-binary", "@" + p, url,
                   "-o", os.path.join(ROOT, "_scratch", "_upload_resp.json")], dry=dry)
        print("  %s" % ("ok" if ok else "FAILED"), flush=True)
        if not ok:
            return 1
    if dry:
        return 0
    rel2 = api("/releases/tags/v1.0")
    local = {}
    for line in io.open(os.path.join(DIST, SUMS), encoding="ascii"):
        if line.strip():
            d, _s, n = line.strip().partition("  ")
            local[n.strip()] = d.strip()
    print("\n=== 资产清单（远端 digest vs 本地清单）===")
    bad = []
    for a in rel2["assets"]:
        d = (a.get("digest") or "").replace("sha256:", "")
        if a["name"] in local:
            ok = d == local[a["name"]]
            if not ok:
                bad.append(a["name"])
            mark = "✓" if ok else "✗ 与本地清单不一致"
        else:
            mark = "（清单未列）"
        print("  %-40s %12d  %s  %s" % (a["name"], a["size"], d[:16], mark))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="发版资产：下载 → 校验 → 上传")
    ap.add_argument("cmd", choices=["download", "verify", "upload", "all"])
    ap.add_argument("run_id", nargs="?", default="", help="download 用的 run id（默认取最近成功）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "download":
        return do_download(a.run_id or None, a.dry_run)
    if a.cmd == "verify":
        return do_verify()
    if a.cmd == "upload":
        return do_upload(a.dry_run)
    rc = do_download(a.run_id or None, a.dry_run)
    if rc == 0 and not a.dry_run:
        rc = do_verify()
    if rc == 0:
        rc = do_upload(a.dry_run)
    return rc


if __name__ == "__main__":
    sys.exit(main())
