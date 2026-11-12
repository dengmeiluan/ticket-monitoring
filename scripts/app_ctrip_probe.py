# -*- coding: utf-8 -*-
"""`app_ctrip`（携程 App）小步验证：单渠道、单航线、跑一次，看有没有行。

为什么需要这个脚本
------------------
`app_ctrip` 是完整实现的渠道（`crawlers/app_ctrip.py`，能力矩阵
domestic/intl/calendar/round_trip = y），但**它不在 `users[].platforms` 里**，
所以采集从不调用它 —— 用户在 App 里登录成功也就不可能改变任何结果
（2026-11-05 定位，见 docs §6.47）。

接入前按仓内既有规矩**先小步验证**：跑一条航线，看到真实行数再常开。
仓里没有现成的单渠道调试入口（`main.py` 只有 `--once` 全渠道），
所以这里补一个，并且**构造方式完全照抄 `main.py:1909-1920`**：

    crawler_cfg = dict(cfg["crawler"])
    crawler_cfg["user_data_dir"] = <session root>
    crawler_cfg["android"] = cfg["android"]

自己另拼一套配置的话，"探针通过但生产跑不通"这种坑迟早出现。

用法：
    python scripts/app_ctrip_probe.py                 # 默认 SHA→CAN 单程
    python scripts/app_ctrip_probe.py --to PEK --date 2026-11-16
    python scripts/app_ctrip_probe.py --raw           # 绕过策略闸门直调 fetch
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


def _build_crawler(cfg: dict, logger):
    """按 main.py 的同一条路径构造渠道（不另造配置口径）。"""
    crawler_cfg = dict(cfg.get("crawler", {}) or {})
    crawler_cfg["user_data_dir"] = cfg.get("user_data_dir") or "user_data"
    # App 渠道读顶层 android: 段；整段落进去，由 normalize 判 enabled
    crawler_cfg["android"] = cfg.get("android") or {}
    cls = REGISTRY.get("app_ctrip")
    if cls is None:
        raise SystemExit("REGISTRY 里没有 app_ctrip（渠道没注册？）")
    return cls(crawler_cfg, logger)


def main() -> int:
    ap = argparse.ArgumentParser(description="携程 App 渠道小步验证")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--from", dest="frm", default="SHA")
    ap.add_argument("--to", default="CAN")
    ap.add_argument("--date", default="2026-11-16")
    ap.add_argument("--raw", action="store_true",
                    help="绕过策略闸门，直接调 fetch（看渠道本身能力）")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("app_ctrip_probe")

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    android = cfg.get("android") or {}
    if not android.get("enabled"):
        print("android.enabled=false：App 渠道不会跑，先确认配置")
        return 2

    crawler = _build_crawler(cfg, logger)
    print("=== 渠道 %s / 航线 %s→%s / 日期 %s ===" % (
        crawler.name, args.frm, args.to, args.date))
    t0 = time.time()
    try:
        if args.raw:
            rows = crawler.fetch(args.frm, args.to, [args.date])
        else:
            rows = crawler.safe_fetch(args.frm, args.to, [args.date])
    except Exception as e:                      # 探针本身失败要看得见原因
        print("!! 抓取抛异常：%s: %s" % (type(e).__name__, str(e)[:200]))
        rows = []
    dt = time.time() - t0

    print()
    print("=== 结果 ===")
    print("  行数 = %d  耗时 = %.1fs" % (len(rows or []), dt))
    for r in (rows or [])[:6]:
        price = getattr(r, "price", None)
        name = getattr(r, "flight_no", "") or getattr(r, "name", "")
        print("    %-12s %s" % (name, price))
    print("  通路记录:")
    for p in (crawler.paths or []):
        print("    %-18s %-10s rows=%s %s" % (
            p.get("path"), p.get("status"), p.get("rows"),
            str(p.get("detail") or "")[:80]))
    if crawler.last_error:
        print("  last_error:", str(crawler.last_error)[:200])

    if rows:
        print()
        print(">>> 通过：这个渠道现在能出数，可以考虑加入 platforms 常开")
        return 0
    print()
    print(">>> 没出数。先把上面的通路记录贴出来判断卡在哪一步"
          "（登录墙 / 首页没起来 / 列表解析 / 风控页），不要直接开常驻。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
