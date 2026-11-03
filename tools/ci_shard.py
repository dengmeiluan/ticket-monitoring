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
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
DURATIONS = TESTS / "ci_durations.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
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


# xdist --dist loadfile 的固定成本：每个文件都要重新导入一次测试模块。
# 只按纯测试耗时均分会把大量短文件堆到同一片（实测第 2 片 341 个文件，
# 比其他片多一倍，墙钟被导入开销拖长 ~100s）。把它计进权重再 LPT。
FILE_OVERHEAD_S = 1.0


def plan(groups_n, seconds=None):
    """LPT 贪心：耗时（含每文件导入开销）长的先放，进当前总权重最小的组。"""
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
        loads[k] += seconds.get(p.name, DEFAULT_SECONDS) + FILE_OVERHEAD_S
    for g in groups:
        g.sort(key=lambda p: p.name)
    return groups, loads


def check_workflow(groups_n, path=None):
    """CI workflow 的片数/选片命令/聚合检查必须与本次分片一致。

    matrix 只有 3 组却传 --print 4 时，第 4 片永远不会被调度，而且
    任何单看 --stats 的检查都发现不了——这是静默漏跑。返回空串=一致。
    """
    path = Path(path) if path else CI_WORKFLOW
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "读不到 CI workflow：%s" % exc
    m = re.search(r"matrix:\s*\n\s*group:\s*\[([^\]]*)\]", text)
    if not m:
        return "CI workflow 没有 group matrix"
    groups = [int(x) for x in re.findall(r"\d+", m.group(1))]
    if groups != list(range(groups_n)):
        return "CI matrix group=%s 与本次 %d 片不一致" % (groups, groups_n)
    if "tools/ci_shard.py --print %d" % groups_n not in text:
        return "CI 未按 %d 片选文件" % groups_n
    if "--dist loadfile" not in text:
        return "CI 丢了 --dist loadfile"
    if not re.search(r"^  uitest:\s*$", text, re.M) or \
            "python docs/uitest.py" not in text:
        return "CI 缺独立 UI 自检岗（uitest + docs/uitest.py）"
    if not re.search(r"ci-ok:\s*\n(?:.*\n)*?\s*needs:\s*\[test,\s*uitest\]",
                     text):
        return "CI 缺 ci-ok 聚合（needs test+uitest）"
    if not re.search(r"concurrency:\s*\n(?:.*\n)*?"
                     r"\s*cancel-in-progress:\s*true", text):
        return "CI 缺 concurrency cancel-in-progress"
    return ""


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
            print("group %d  %4d files  %8.1fs（权重，含 1.0s/文件）"
                  % (i, len(files), loads[i]))
        lo, hi = min(loads), max(loads)
        print("total %.1fs（权重）  max/min %.2f  dup %d  missing %d"
              % (sum(loads), (hi / lo) if lo else 0.0, dup, len(missing)))
        if missing or dup:
            print("分片覆盖缺口：%s" % (missing or dup), file=sys.stderr)
            return 2
        known = sum(1 for p in discover() if p.name in seconds)
        print("耗时快照覆盖 %d/%d 个测试文件" % (known, len(discover())))
        err = check_workflow(args.stats)
        if err:
            print("CI 分片契约不一致：%s" % err, file=sys.stderr)
            return 2
        print("CI workflow 与 %d 片矩阵一致（选片/loadfile/ci-ok/取消旧跑）"
              % args.stats)
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
