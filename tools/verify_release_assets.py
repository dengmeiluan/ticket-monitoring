# -*- coding: utf-8 -*-
"""发版资产校验：四平台 zip + SHA256SUMS.txt。

用法：
    python tools/verify_release_assets.py --dir dist_package

校验项：资产集合恰好五个、SHA256SUMS 四行且与实际文件哈希一致、
包根为 TicketMonitor(.exe) + _internal/、不含配置/数据/日志/凭据。
"""
import argparse
import hashlib
import io
import os
import re
import sys
import zipfile

ZIPS = {
    "ticket-monitoring-win64.zip": "TicketMonitor.exe",
    "ticket-monitoring-linux-x64.zip": "TicketMonitor",
    "ticket-monitoring-macos-arm64.zip": "TicketMonitor",
    "ticket-monitoring-macos-x64.zip": "TicketMonitor",
}
SUMS = "SHA256SUMS.txt"
FORBIDDEN = ("config.yaml", "data/", "logs/", "user_data/",
             "ghtoken", ".env", ".git/")
SUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+)$")


def _forbidden(name):
    """按顶层路径段判定，避免 _internal/tzdata/ 被 'data/' 误伤。"""
    low = name.lower().lstrip("./")
    return (low in ("config.yaml", "ghtoken", ".env")
            or low.startswith(("data/", "logs/", "user_data/", ".git/")))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_errors(path, exe_name):
    errs = []
    try:
        z = zipfile.ZipFile(path)
    except Exception as exc:  # noqa: BLE001
        return ["打不开 zip：%s" % exc]
    names = z.namelist()
    if not names:
        errs.append("zip 为空")
    if exe_name not in names:
        errs.append("缺包根 %s" % exe_name)
    if not any(n.startswith("_internal/") for n in names):
        errs.append("缺 _internal/")
    bad = [n for n in names if _forbidden(n)]
    if bad:
        errs.append("含敏感/运行态文件：%s" % bad[:5])
    return errs


def verify(directory):
    errs = []
    if not os.path.isdir(directory):
        return ["目录不存在：%s" % directory]
    files = sorted(os.listdir(directory))
    expected = set(ZIPS) | {SUMS}
    missing = sorted(expected - set(files))
    extra = sorted(set(files) - expected)
    if missing:
        errs.append("缺资产：%s" % missing)
    if extra:
        errs.append("多余资产：%s" % extra)
    for name, exe in ZIPS.items():
        p = os.path.join(directory, name)
        if os.path.isfile(p):
            errs.extend("%s：%s" % (name, e) for e in _zip_errors(p, exe))
    sp = os.path.join(directory, SUMS)
    sums = {}
    if os.path.isfile(sp):
        try:
            text = io.open(sp, encoding="utf-8").read()
        except OSError as exc:
            errs.append("SHA256SUMS 读取失败：%s" % exc)
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = SUM_RE.match(line)
            if not m:
                errs.append("SHA256SUMS 行格式错：%s" % line[:60])
                continue
            sums[m.group(2).strip()] = m.group(1).lower()
        if len(sums) != 4:
            errs.append("SHA256SUMS 应为 4 行，实际 %d" % len(sums))
        for name in ZIPS:
            p = os.path.join(directory, name)
            if not os.path.isfile(p):
                continue
            got = _sha256(p)
            if name not in sums:
                errs.append("SHA256SUMS 缺 %s" % name)
            elif sums[name] != got:
                errs.append("%s 哈希不符：清单 %s / 实际 %s"
                            % (name, sums[name], got))
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="dist_package")
    args = ap.parse_args()
    errs = verify(args.dir)
    if errs:
        print("FAIL: %d 项" % len(errs))
        for e in errs[:30]:
            print("  - " + e)
        return 1
    print("OK: 四平台资产与 SHA256SUMS 一致（%s）" % args.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
