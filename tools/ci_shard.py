#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 测试分片：按历史耗时把 tests/test_*.py 贪心均分到 N 组。

耗时快照 tests/ci_durations.json 由一次全量 JUnit 生成：
  python tools/ci_shard.py --snapshot _scratch/test_run/<ts>/pytest.xml
新测试文件不在快照里时按 DEFAULT_SECONDS 计权，仍会进分片（不漏跑）。

用法：
  python tools/ci_shard.py --stats 4        # 各组文件数/耗时与均衡度
  python tools/ci_shard.py --print 4 0      # 第 0 组文件（空格分隔，给 pytest）
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
DURATIONS = TESTS / "ci_durations.json"
DEFAULT_SECONDS = 20.0


def discover():
    """tests/ 下全部测试文件，按路径排序（分片结果必须可复现）。"""
    files = sorted(p for p in TESTS.rglob("test_*.py") if p.is_file())
    if not files:
        raise SystemExit("tests/test_*.py 未找到")
    return files


def load_seconds():
    try:
        data = json.loads(DURATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("seconds") or {}
    out = {}
    for name, value in raw.items():
        try:
            out[str(name)] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return out


def snapshot(junit_path, out_path=None):
    """从 JUnit XML 生成按文件聚合的耗时快照（覆盖旧快照）。"""
    out_path = Path(out_path) if out_path else DURATIONS
    root = ET.parse(str(junit_path)).getroot()
    known = {p.name for p in discover()}
    seconds = {}
    for case in root.iter("testcase"):
        file_attr = (case.get("file") or "").replace("\\", "/")
        stem = Path(file_attr).stem if file_attr else ""
        if not stem:
            parts = (case.get("classname") or "").split(".")
            if len(parts) > 1 and parts[0] == "tests":
                stem = parts[1]
        name = stem + ".py" if stem else ""
        if name not in known:
            continue
        try:
            dt = float(case.get("time") or 0)
        except (TypeError, ValueError):
            dt = 0.0
        seconds[name] = seconds.get(name, 0.0) + dt
    for name in known:
        seconds.setdefault(name, DEFAULT_SECONDS)
    payload = {
        "source": Path(junit_path).name,
        "seconds": {k: round(seconds[k], 1) for k in sorted(seconds)},
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    return payload


def plan(groups_n, seconds=None):
    """LPT 贪心：耗时长的先放，进当前总耗时最小的组。"""
    seconds = load_seconds() if seconds is None else seconds
    files = discover()
    groups = [[] for _ in range(groups_n)]
    loads = [0.0] * groups_n
    ordered = sorted(files,
                     key=lambda p: (-seconds.get(p.name, DEFAULT_SECONDS),
                                    p.name))
    for p in ordered:
        k = min(range(groups_n), key=lambda i: (loads[i], i))
        groups[k].append(p)
        loads[k] += seconds.get(p.name, DEFAULT_SECONDS)
    for g in groups:
        g.sort(key=lambda p: p.name)
    return groups, loads


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", metavar="JUNIT",
                    help="用全量 JUnit XML 重建耗时快照")
    ap.add_argument("--stats", type=int, metavar="N",
                    help="打印 N 组的分片统计")
    ap.add_argument("--print", nargs=2, type=int, metavar=("N", "INDEX"),
                    help="打印第 INDEX 组的测试文件（供 pytest 直接消费）")
    args = ap.parse_args(argv)

    if args.snapshot:
        payload = snapshot(args.snapshot)
        print("快照 %d 个文件，合计 %.1fs"
              % (len(payload["seconds"]),
                 sum(payload["seconds"].values())))
        return 0

    if args.stats:
        groups, loads = plan(args.stats)
        seconds = load_seconds()
        covered = [p.relative_to(ROOT).as_posix()
                   for g in groups for p in g]
        missing = sorted({p.relative_to(ROOT).as_posix()
                          for p in discover()} - set(covered))
        dup = len(covered) - len(set(covered))
        for i, files in enumerate(groups):
            print("group %d  %4d files  %8.1fs" % (i, len(files), loads[i]))
        lo, hi = min(loads), max(loads)
        print("total %.1fs  max/min %.2f  dup %d  missing %d"
              % (sum(loads), (hi / lo) if lo else 0.0, dup, len(missing)))
        if missing or dup:
            print("分片覆盖缺口：%s" % (missing or dup), file=sys.stderr)
            return 2
        known = sum(1 for p in discover() if p.name in seconds)
        print("耗时快照覆盖 %d/%d 个测试文件" % (known, len(discover())))
        return 0

    if args.print:
        n, idx = args.print
        if not 0 <= idx < n:
            ap.error("INDEX 须在 0..%d" % (n - 1))
        groups, _ = plan(n)
        paths = [p.relative_to(ROOT).as_posix() for p in groups[idx]]
        bad = [p for p in paths if any(ch.isspace() for ch in p)]
        if bad:
            print("测试路径含空白，无法作为 argv 传递：%s" % bad,
                  file=sys.stderr)
            return 2
        print(" ".join(paths))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
