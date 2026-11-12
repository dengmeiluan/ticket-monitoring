# -*- coding: utf-8 -*-
"""App 渠道通用小步验证：任选一个渠道、一条航线、跑一次看有没有行。

为什么要有这个（在 ``app_ctrip_probe.py`` 之后抽象出来）
------------------------------------------------------
`app_ctrip_probe.py` 当时只服务携程一个渠道。但本项目的 App 渠道有
五个（携程/去哪儿/同程/智行/飞猪），而它们**共用同一套设备底座**
（分辨率、竖屏锁、UI dump、坐标基准）。底座一动，五个渠道都可能受影响，
所以需要一个能对任意渠道跑一次的入口，才能"改一处、验五处"。

构造方式与 ``main.py`` 的同一条路径保持一致（不另造配置口径）：

    crawler_cfg = dict(cfg["crawler"])
    crawler_cfg["user_data_dir"] = <session root>
    crawler_cfg["android"] = cfg["android"]

用法::

    python scripts/app_channel_probe.py --channel app_qunar --to PEK
    python scripts/app_channel_probe.py --channel all --date 2026-11-16
"""
import argparse
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402

from crawlers import REGISTRY  # noqa: E402

APP_CHANNELS = ("app_ctrip", "app_qunar", "app_tongcheng",
                "app_fliggy", "app_zhixing")


def _build(channel: str, cfg: dict, logger):
    crawler_cfg = dict(cfg.get("crawler", {}) or {})
    crawler_cfg["user_data_dir"] = os.path.abspath(
        os.path.join(ROOT, cfg.get("user_data_dir") or "user_data"))
    crawler_cfg["android"] = cfg.get("android") or {}
    cls = REGISTRY.get(channel)
    if cls is None:
        raise SystemExit("REGISTRY 里没有 %s（渠道没注册？）" % channel)
    return cls(crawler_cfg, logger)


def probe_one(channel: str, cfg: dict, frm: str, to: str, date: str,
              raw: bool = True) -> dict:
    logger = logging.getLogger(channel)
    out = {"channel": channel, "rows": 0, "secs": 0.0, "paths": [],
           "error": "", "ok": False}
    try:
        crawler = _build(channel, cfg, logger)
    except SystemExit as e:
        out["error"] = str(e)
        return out
    print("\n=== %s / %s→%s / %s ===" % (channel, frm, to, date))
    t0 = time.time()
    try:
        rows = (crawler.fetch(frm, to, [date]) if raw
                else crawler.safe_fetch(frm, to, [date]))
    except Exception as e:
        print("  !! 抛异常：%s: %s" % (type(e).__name__, str(e)[:160]))
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        rows = []
    out["secs"] = time.time() - t0
    out["rows"] = len(rows or [])
    out["ok"] = bool(rows)
    out["paths"] = list(crawler.paths or [])
    for r in (rows or [])[:4]:
        print("    %-12s %s" % (getattr(r, "flight_no", "") or "",
                                getattr(r, "price", None)))
    for p in out["paths"]:
        print("    %-18s %-10s rows=%s %s"
              % (p.get("path"), p.get("status"), p.get("rows"),
                 str(p.get("detail") or "")[:70]))
    if crawler.last_error:
        print("    last_error:", str(crawler.last_error)[:160])
    print("  -> %s  %d 行  %.1fs" % ("OK" if out["ok"] else "FAIL",
                                     out["rows"], out["secs"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="App 渠道通用小步验证")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--channel", default="app_qunar",
                    help="渠道名，或 all 表示五个都跑")
    ap.add_argument("--from", dest="frm", default="SHA")
    ap.add_argument("--to", default="PEK")
    ap.add_argument("--date", default="2026-11-16")
    ap.add_argument("--safe", action="store_true",
                    help="走 safe_fetch（含策略闸门）而不是直调 fetch")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not (cfg.get("android") or {}).get("enabled"):
        print("android.enabled=false：App 渠道不会跑")
        return 2

    channels = (list(APP_CHANNELS) if args.channel == "all"
                else [args.channel])
    results = [probe_one(c, cfg, args.frm, args.to, args.date,
                         raw=not args.safe) for c in channels]

    print("\n=== 汇总 ===")
    for r in results:
        print("  %-14s %-5s rows=%-3d %.1fs %s"
              % (r["channel"], "OK" if r["ok"] else "FAIL", r["rows"],
                 r["secs"], r["error"][:60]))
    ok = sum(1 for r in results if r["ok"])
    print("  通过 %d/%d" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
