# -*- coding: utf-8 -*-
"""按时间窗统计各渠道的**真实出数率**，用来判断改动到底有没有效。

为什么单独有这个脚本
--------------------
`yield_report.py` 读的是账本，账本按渠道聚合，看不出「改动前 vs 改动后」
的趋势。而这个项目一天里改了二十几处，**必须能把一天切片对比**，
否则"有没有变好"只能靠感觉。

口径（避免误读）
----------------
* 分子 = 该时段内「抓取完成」**有出数**的调用数；分母 = 调用数。
  **不是行数** —— 一次调用可能出 0 行也可能出几十行。
* 分桶按**日志时间**。中途重启监控会让桶里混进「设备掉线」「预热」
  这类非渠道因素，所以**小样本桶（<10 次）不要下结论**。
  2026-11-04 的 17 点桶就是典型：当天两次把设备搞挂，50% 这个数字
  完全不能读成"改动后变差"。

用法
----
    python scripts/yield_timeline.py                 # 今天
    python scripts/yield_timeline.py --day 2026-11-03
"""
from __future__ import annotations

import argparse
import collections
import io
import os
import re
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG = os.path.join(ROOT, "logs", "monitor.log")
DB = os.path.join(ROOT, "data", "prices.db")
TS = "%Y-%m-%d %H:%M:%S"

# 完成一次抓取的所有出口都算一次「调用」
_DONE = re.compile(r"\[(\w+)\] 抓取完成，得到 (\d+) 条")
_HEAD = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")

# 小样本门槛：低于这个次数的桶只标注、不下结论
MIN_SAMPLE = 10


def _bucket_label(ts: datetime) -> str:
    """按 3 小时切片（够粗以覆盖整轮，又够细以看出趋势拐点）。"""
    lo = ts.hour - (ts.hour % 3)
    return "%02d-%02d" % (lo, lo + 3)


def load(day: str):
    """从日志里取出 (时间, 渠道, 行数)。日志是唯一的"过程证据"。"""
    if not os.path.isfile(LOG):
        return []
    lines = io.open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    out = []
    for line in lines:
        if not line.startswith(day):
            continue
        m = _HEAD.match(line)
        if not m:
            continue
        d = _DONE.search(line)
        if not d:
            continue
        out.append((datetime.strptime(m.group(1), TS), d.group(1),
                    int(d.group(2))))
    return out


def report(day: str) -> int:
    rows = load(day)
    if not rows:
        print("日志里没有 %s 的抓取完成记录" % day)
        return 1

    buckets = collections.defaultdict(
        lambda: collections.defaultdict(lambda: [0, 0, 0]))
    # bucket -> channel -> [有数次数, 总次数, 行数合计]
    for ts, ch, n in rows:
        b = buckets[_bucket_label(ts)][ch]
        b[1] += 1
        b[2] += n
        if n > 0:
            b[0] += 1

    print("=== %s 各时段「有出数的调用占比」===" % day)
    for bk in sorted(buckets):
        tot_ok = sum(v[0] for v in buckets[bk].values())
        tot_all = sum(v[1] for v in buckets[bk].values())
        tot_rows = sum(v[2] for v in buckets[bk].values())
        rate = 100.0 * tot_ok / tot_all if tot_all else 0.0
        flag = "" if tot_all >= MIN_SAMPLE else "   ← 样本小，别下结论"
        print("\n%s 时  整体 %.0f%%（%d/%d 次有数，共 %d 行）%s"
              % (bk, rate, tot_ok, tot_all, tot_rows, flag))
        for ch in sorted(buckets[bk], key=lambda k: -buckets[bk][k][1]):
            ok, alln, nrow = buckets[bk][ch]
            print("    %-14s %3d/%-3d %3.0f%%   %4d 行"
                  % (ch, ok, alln, 100.0 * ok / alln if alln else 0, nrow))

    if os.path.isfile(DB):
        conn = sqlite3.connect(DB)
        try:
            cur = conn.execute(
                "SELECT substr(fetched_at,12,2), count(*) FROM flight_prices "
                "WHERE fetched_at>=? GROUP BY substr(fetched_at,12,2) "
                "ORDER BY 1", (day,))
            print("\n=== 入库行数按小时 ===")
            for hh, n in cur.fetchall():
                print("  %s 时 %3d  %s" % (hh, n, "#" * max(1, int(n / 3))))
        finally:
            conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="按时间窗看各渠道出数率")
    ap.add_argument("--day", default=datetime.now().strftime("%Y-%m-%d"))
    return report(ap.parse_args().day)


if __name__ == "__main__":
    sys.exit(main())
