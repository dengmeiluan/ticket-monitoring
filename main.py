# -*- coding: utf-8 -*-
"""机票价格监控 主入口（多租户版）

用法:
    python main.py                # 按 config.yaml 启动定时监控
    python main.py --once         # 每条航线只跑一次后退出
    python main.py -c other.yaml  # 指定配置文件

多租户模型：采集与告警正交——
  采集层按 (航线, 日期) 去重共享（多人盯同航线只采一份），
  告警层按用户分发（各自的阈值 / 钉钉群 / @手机号）。
  去哪儿接口有 ~5 分钟全局限流（与航线无关），查询间错峰。
"""
import argparse

__version__ = "110.0.0"
import os
import subprocess
import sys
import time
import concurrent.futures
from pathlib import Path

import yaml

from core.logger import setup_logger
from core.models import Route
from core.storage import PriceStorage
from core.alerter import Alerter
from core.scheduler import run_scheduler
from core.notifier import build_notifier
from crawlers import REGISTRY


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_routes(routes_cfg: list) -> list:
    routes = []
    for r in routes_cfg or []:
        routes.append(Route(
            from_code=r["from"],
            from_name=r.get("from_name", r["from"]),
            to_code=r["to"],
            to_name=r.get("to_name", r["to"]),
            dates=list(r.get("dates", [])),
            alert_threshold=float(r.get("alert_threshold", 0) or 0),
            alert_direct=float(r.get("alert_direct", 0) or 0),
            alert_transfer=float(r.get("alert_transfer", 0) or 0),
            transfer_arrival_max=str(r.get("transfer_arrival_max", "02:00")),
            dep_time_min=str(r.get("dep_time_min", "") or ""),
            dep_time_max=str(r.get("dep_time_max", "") or ""),
        ))
    return routes


def build_users(cfg: dict) -> list:
    """归一化用户列表；兼容旧单用户格式（无 users 键则整体作为一个用户）。"""
    if "users" in cfg:
        raw_users = cfg["users"] or []
    else:
        raw_users = [{"name": "default", **{
            k: cfg[k] for k in ("routes", "platforms", "schedule", "notifier")
            if k in cfg}}]
    users = []
    for i, u in enumerate(raw_users):
        if not u.get("routes"):
            continue
        users.append({
            "name": str(u.get("name") or f"user{i+1}"),
            "routes": build_routes(u["routes"]),
            "platforms": u.get("platforms") or cfg.get(
                "platforms", ["qunar", "fliggy", "tongcheng", "tuniu"]),
            "notifier": u.get("notifier") or {},
            "schedule": u.get("schedule") or cfg.get("schedule") or {},
        })
    return users


def ensure_chromium(platforms, logger=None):
    """playwright 系平台启用时确保 chromium 内核就绪（幂等；缺失自动下载）。"""
    if not ({"qunar", "ctrip", "tongcheng"} & set(platforms or [])):
        return
    try:
        import playwright
    except ImportError:
        return
    if getattr(sys, "frozen", False):
        # 冻结态 playwright 默认找驱动目录下 .local-browsers；
        # 显式指向全局注册表，使安装与启动同轨
        os.environ.setdefault(
            "PLAYWRIGHT_BROWSERS_PATH",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"))
    os.environ.setdefault(
        "PLAYWRIGHT_DOWNLOAD_HOST",
        "https://cdn.npmmirror.com/binaries/playwright")
    pkg = os.path.dirname(playwright.__file__)
    node = os.path.join(pkg, "driver", "node.exe")
    cli_js = os.path.join(pkg, "driver", "package", "cli.js")
    if os.path.exists(node) and os.path.exists(cli_js):
        # 驱动自带 node，直调 cli.js（源码/打包态通用）
        cmd = [node, cli_js, "install", "chromium"]
    elif not getattr(sys, "frozen", False):
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    else:
        warn = "未找到 playwright 驱动，无法自动安装 chromium"
        (logger.warning if logger else print)(warn)
        return
    msg = "检查/安装 chromium 内核（首次约 120MB，已安装则秒过）……"
    (logger.info if logger else print)(msg)
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        warn = f"chromium 安装命令执行失败: {e}；浏览器采集可能不可用"
        (logger.warning if logger else print)(warn)


def make_sweep_job(cfg, rt, logger, storage, charts_fn):
    """构造一轮全量扫描：航线去重 → 逐查询错峰采集 → 分发给订阅用户。

    rt 为运行时容器（dict）：users/alerters/cfg 均可被 web 配置热重载替换，
    每轮扫描开始时取最新值。cfg 形参只是热重载前的初始快照——扫描期一律读
    rt["cfg"]（reload_config 会同步更新），否则爬虫超时/错峰/日报时刻/图床
    等配置在首次热重载后仍沿用启动快照。去哪儿接口 ~5 分钟全局限流（与航线
    无关），每个 (航线, 日期) 查询之间错峰等待。"""
    import threading
    QUERY_GAP_S = 310   # 去哪儿全局限流安全间隔（qunar 渠道级自锁使用）
    # 进程级互斥：启动首轮 / 定时调度 / 网页手动触发统一防并发
    # （曾因"启动即扫 + /api/run"双跑导致每渠道抓两次、每消息推两条）
    _sweep_lock = threading.Lock()

    # 平台实例：按「平台集合」缓存（去哪儿实例的 token/浏览器会话复用）
    crawler_cache = {}
    # 热改无头模式后清缓存，下轮按新配置重建浏览器实例
    rt["clear_crawlers"] = crawler_cache.clear

    def get_crawlers(platforms):
        key = tuple(sorted(set(platforms)))
        if key not in crawler_cache:
            crawler_cfg = (rt.get("cfg") or cfg).get("crawler", {})
            insts = []
            for name in key:
                cls = REGISTRY.get(name)
                if cls:
                    insts.append(cls(crawler_cfg, logger))
            crawler_cache[key] = insts
        return crawler_cache[key]

    def sweep():
        if not _sweep_lock.acquire(blocking=False):
            logger.warning("[扫描] 上一轮仍在进行，跳过本次触发")
            return
        try:
            _sweep_inner()
        finally:
            _sweep_lock.release()

    def _sweep_inner():
        from core.pulse import PULSE
        users, alerters = rt["users"], rt["alerters"]
        logger.info("===== 开始一轮扫描（%d 用户 / %d 航线） =====",
                    len(users),
                    len({(r.from_code, r.to_code) for u in users for r in u["routes"]}))
        # 航线×日期 去重注册表：{(from,to,date): [订阅该组合的用户索引]}
        registry = {}
        for ui, u in enumerate(users):
            for r in u["routes"]:
                for d in r.dates:
                    registry.setdefault((r.from_code, r.to_code, d), set()).add(ui)

        queries = sorted(registry)
        PULSE.begin()

        def _timed_fetch(c, fc_, tc_, d_):
            # 单渠道计时入脉冲（成败=是否有数据），控制台可观察性数据源
            t0 = time.time()
            prices = c.safe_fetch(fc_, tc_, [d_])
            try:
                PULSE.channel(c.name, len(prices), time.time() - t0)
            except Exception:
                pass
            return prices

        user_pairs = {}   # 按用户聚合 (route, prices)，轮末一次聚合推送
        chart_cache = {}
        for qi, (fc, tc, d) in enumerate(queries):
            # 平台集合 = 所有订阅用户平台配置的并集（一次采集服务所有人）
            plats = set()
            for ui in registry[(fc, tc, d)]:
                plats |= set(users[ui]["platforms"])
            # 渠道并发（各平台相互独立：浏览器实例/会话目录均隔离）；
            # 去哪儿的全局限流错峰由 qunar 渠道自身控制（类级时间锁），
            # 不再让其余渠道陪等——多查询场景下每轮可省 2×QUERY_GAP_S
            all_prices = []
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max(1, len(plats) or 1)) as ex:
                futs = {ex.submit(_timed_fetch, c, fc, tc, d): c.name
                        for c in get_crawlers(plats)}
                for fu in concurrent.futures.as_completed(futs):
                    try:
                        prices = fu.result()
                    except Exception as e:
                        logger.warning("[并发] %s 抓取异常: %s", futs[fu], e)
                        continue
                    all_prices.extend(prices)
            storage.save_many(all_prices)
            # 走势图按航线一次生成、所有用户复用
            # charts_fn 返回 {(from,to,date): url} 整表——此处须取本航线的
            # 单个 URL 存缓存，否则 alerter 拿到 dict 嵌进 markdown 变裂图
            chart = charts_fn(fc, tc, d) or {}
            chart_url = chart.get((fc, tc, d))
            if chart_url:
                chart_cache[(fc, tc, d)] = chart_url
            # 分发：按用户聚合本轮全部 (route, prices)，
            # 一轮一消息（每航线一个小节，明细合并一张总表）
            for ui in sorted(registry[(fc, tc, d)]):
                u = users[ui]
                for r in u["routes"]:
                    if r.from_code == fc and r.to_code == tc and d in r.dates:
                        sub = [p for p in all_prices
                               if p.from_city == fc and p.to_city == tc
                               and p.depart_date == d]
                        user_pairs.setdefault(ui, []).append((r, sub))
            logger.info("[扫描] %s→%s %s 完成（%d/%d）", fc, tc, d, qi + 1, len(queries))
        # 轮末统一分发（全部航线采集完成后聚合推送）
        for ui, pairs in user_pairs.items():
            try:
                alerters[ui].round_charts = chart_cache
                alerters[ui].check_multi(pairs)
            except Exception as e:
                logger.warning("[%s] 聚合推送异常: %s", users[ui]["name"], e)
        # 每用户日报（到点触发一次，防重发按用户隔离）
        for ui, u in enumerate(users):
            try:
                from report import maybe_daily_report
                maybe_daily_report(rt.get("cfg") or cfg, logger,
                                   alerters[ui].notifier, user=u["name"])
            except Exception as e:
                logger.warning("[%s] 每日走势报告异常: %s", u["name"], e)
        PULSE.end()
        logger.info("===== 本轮扫描结束 =====")
        # 数据窗口维护：删 14 天前明细（extra 大 JSON 是增长主体）
        try:
            n = storage.purge(days=14)
            if n:
                logger.info("[存储] 已清理 %d 条过期价格记录", n)
        except Exception as e:
            logger.warning("[存储] 过期清理失败: %s", e)

    return sweep


def main():
    ap = argparse.ArgumentParser(description=f"机票监控 ticket-monitoring v{__version__}")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    ap.add_argument("--once", action="store_true", help="每条航线只运行一次后退出")
    ap.add_argument("--setup", action="store_true", help="重跑配置向导")
    ap.add_argument("--report", action="store_true",
                    help="立即生成价格走势图并推送钉钉（未配图床则只存本地）")
    ap.add_argument("--install-browser", action="store_true",
                    help="仅安装/更新 chromium 内核后退出")
    ap.add_argument("--setup-login", action="store_true",
                    help="顺序弹出浏览器引导登录所有已启用渠道（每家登录一次永久复用）")
    ap.add_argument("--login", metavar="PLATFORM",
                    help="登录指定平台(ctrip/fliggy/tongcheng)，弹出可见浏览器，登录完成后回车保存会话")
    args = ap.parse_args()

    cfg_path = Path(args.config)

    if args.setup:
        from wizard import run_wizard
        run_wizard(str(cfg_path))
        print("配置完成，重新运行程序即开始监控。")
        return

    if args.install_browser:
        ensure_chromium(["qunar"])
        return

    if not cfg_path.exists():
        # 无配置文件时给一个空骨架，直接进 web 页面配置（不再强制 CLI 向导）
        cfg = {"users": [], "schedule": {"interval_minutes": 30,
                                         "jitter_minutes": 5},
               "crawler": {"headless": True, "debug": True},
               "output": {"db_path": "data/prices.db",
                          "log_path": "logs/monitor.log"}}
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        except Exception:
            pass
        print("未找到配置——已生成空骨架，请在 http://127.0.0.1:8765 页面配置")
    else:
        cfg = load_config(str(cfg_path))

    out = cfg.get("output", {})
    logger = setup_logger(out.get("log_path", "logs/monitor.log"))
    ensure_chromium(cfg.get("platforms") or ["qunar"], logger)
    storage = PriceStorage(out.get("db_path", "data/prices.db"))

    # 运行时容器：web 配置热重载时替换 users/alerters/cfg，sweep 每轮取最新；
    # rt["cfg"] 是配置的单一事实源（reload_config 同步更新）
    rt = {}
    rt["cfg"] = cfg

    def build_runtime():
        users = build_users(cfg)
        alerters = []
        for u in users:
            ncfg = u["notifier"]
            notifier = build_notifier(ncfg, logger)
            if notifier:
                logger.info("[%s] 已启用推送: %s", u["name"], type(notifier).__name__)
            from core.notifier import build_urgent_notifier
            urgent = build_urgent_notifier(ncfg, logger)
            if urgent:
                logger.info("[%s] 已启用达标强提醒: %s",
                            u["name"], type(urgent).__name__)
            alerters.append(Alerter(
                logger, notifier=notifier, storage=storage,
                push_drop_min=float((ncfg or {}).get("push_drop_min", 30)),
                push_rise_min=float((ncfg or {}).get("push_rise_min", 50)),
                digest=bool((ncfg or {}).get("digest", False)),
                at_mobile=str(((ncfg or {}).get("dingtalk") or {}).get(
                    "at_mobile", "")),
                storm_repeat=int((ncfg or {}).get("storm_repeat", 3)),
                user=u["name"],
                platforms=u.get("platforms"),
                urgent_notifier=urgent,
                quiet_start=str((ncfg or {}).get("quiet_start", "") or ""),
                quiet_end=str((ncfg or {}).get("quiet_end", "") or ""),
                base_url="http://127.0.0.1:%d" % int(
                    ((cfg.get("web") or {}).get("port", 8765)) or 8765),
            ))
        rt["users"], rt["alerters"] = users, alerters
        return users

    build_runtime()
    if not rt["users"]:
        logger.warning("配置中没有任何用户/航线——可通过 http://127.0.0.1:8765 配置")

    # 走势图生成（按航线，一次上传多用户复用）
    def charts_fn(fc, tc, d):
        try:
            from report import prepare_round_charts
            return prepare_round_charts(cfg, logger, route_override=(fc, tc, d))
        except Exception as e:
            logger.warning("走势图准备失败: %s", e)
            return {}

    sched_ref = [None, int((cfg.get("schedule") or {}).get(
        "interval_minutes", 30) or 30)]  # [scheduler实例, 当前周期]
    # 调度参数可变引用：wrapped 每轮实时读取，热改周期/扰动即生效
    sched_state = {"interval_minutes": sched_ref[1],
                   "jitter_minutes": int((cfg.get("schedule") or {}).get(
                       "jitter_minutes", 0) or 0)}

    def reload_config():
        """web 配置保存后的热重载：重读 config.yaml 并重建用户/告警器。"""
        nonlocal cfg
        cfg = load_config(str(cfg_path))
        rt["cfg"] = cfg
        users = build_runtime()
        logger.info("[热重载] %d 用户已生效：%s", len(users),
                    "、".join(u["name"] for u in users))
        # 同步 webui 的内存引用（否则状态页仍用启动时的旧用户配置）
        try:
            from webui import _State
            _State.users, _State.cfg = rt["users"], cfg
        except Exception:
            pass
        # 调度周期热更新：interval 变化时重排调度器（无需重启）
        try:
            sc = (cfg.get("schedule") or {})
            new_iv = int(sc.get("interval_minutes", 30) or 30)
            new_jm = int(sc.get("jitter_minutes", 0) or 0)
            sched_state["interval_minutes"] = new_iv
            sched_state["jitter_minutes"] = new_jm
            from core.scheduler import SCHED
            if SCHED is not None and new_iv != sched_ref[1]:
                from apscheduler.triggers.interval import IntervalTrigger
                SCHED.reschedule_job(
                    "price_monitor",
                    trigger=IntervalTrigger(minutes=new_iv))
                sched_ref[1] = new_iv
                logger.info("[热重载] 调度周期已更新为 %d 分钟", new_iv)
        except Exception as e:
            logger.warning("[热重载] 调度周期更新失败: %s", e)
        # 无头模式变化 → 清爬虫实例缓存（下轮按新配置重建浏览器）
        try:
            new_hl = bool((cfg.get("crawler") or {}).get("headless", True))
            if new_hl != rt.get("headless", new_hl):
                rt["headless"] = new_hl
                if rt.get("clear_crawlers"):
                    rt["clear_crawlers"]()
                    logger.info("[热重载] 无头模式已切换为 %s，爬虫实例下轮重建",
                                new_hl)
        except Exception as e:
            logger.warning("[热重载] 爬虫缓存清理失败: %s", e)
        # 控制台端口变化 → 原地重绑（响应送回后异步切换）
        try:
            new_port = int((cfg.get("web") or {}).get("port", 8765) or 8765)
            if new_port != rt.get("web_port", new_port):
                rt["web_port"] = new_port
                from webui import rebind_web
                rebind_web(new_port)
                logger.info("[热重载] 控制台端口热切换至 %d", new_port)
        except Exception as e:
            logger.warning("[热重载] 控制台端口切换失败: %s", e)
        return len(users)

    sweep = make_sweep_job(cfg, rt, logger, storage, charts_fn)

    # ---------- 登录引导：--login 单家 / --setup-login 全部 ----------
    login_set = []
    if getattr(args, "setup_login", False):
        plat_all = set()
        for u in build_users(load_config(str(cfg_path))):
            plat_all |= set(u.get("platforms") or [])
        login_set = [p for p in ("qunar", "ctrip", "tongcheng", "tuniu", "fliggy")
                     if p in plat_all]
    elif getattr(args, "login", ""):
        login_set = [args.login]
    if login_set:
        import threading
        # 五窗齐弹：每家独立线程+浏览器（user_data 各自独立无冲突），
        # 阶梯排布窗口；用户自由登录，回一次车统一保存关闭
        done_evt = threading.Event()
        results = {}

        def _open_window(pname, idx):
            try:
                cls = REGISTRY.get(pname)
                crawler = cls(cfg.get("crawler", {}) or {}, logger)
                crawler._login_window(done_evt, idx)
                results[pname] = "ok"
            except Exception as e:
                results[pname] = f"fail: {e}"

        threads = []
        for i, pname in enumerate(login_set):
            t = threading.Thread(target=_open_window, args=(pname, i), daemon=True)
            t.start()
            threads.append(t)
            import time as _t
            _t.sleep(1.2)   # 错峰启动避免窗口抢焦点
        print()
        print("=" * 64)
        print("  已同时打开 %d 个浏览器窗口（每家一个，窗口阶梯排布）。" % len(login_set))
        print("  请逐个完成登录（点各站右上角登录）。")
        print("  全部完成后回到这里按一次 Enter，统一保存会话并关闭。")
        print("=" * 64)
        try:
            input(">>> 全部登录完成后按 Enter：")
        except EOFError:
            import time as _t
            _t.sleep(120)
        done_evt.set()
        for t in threads:
            t.join(timeout=20)
        print("\n".join(f"  {k}: {v}" for k, v in results.items()))
        print("会话已持久化（user_data/），监控将自动复用。")
        return

    if args.report:
        from report import build_and_push
        for u, a in zip(rt["users"], rt["alerters"]):
            build_and_push(cfg, logger, a.notifier, user=u["name"])
        return

    # 伴生本地控制台（127.0.0.1，随监控常驻；--once 不启动）
    if not args.once:
        try:
            from webui import start_web

            def _report_push():
                from report import build_and_push
                ok = True
                for u, a in zip(rt["users"], rt["alerters"]):
                    ok = build_and_push(cfg, logger, a.notifier, user=u["name"]) and ok
                return ok

            start_web(cfg, sweep, _report_push, logger, users=rt["users"],
                      reload_cb=reload_config, config_path=str(cfg_path),
                      version=__version__)
            rt["web_port"] = int((cfg.get("web") or {}).get("port", 8765))
            rt["headless"] = bool((cfg.get("crawler") or {}).get(
                "headless", True))
        except Exception as e:
            logger.warning("控制台启动异常: %s", e)

    sched_cfg = (rt["users"][0]["schedule"] if rt["users"]
                 else cfg.get("schedule") or {})
    interval = int(sched_cfg.get("interval_minutes", 30))
    jitter = int(sched_cfg.get("jitter_minutes", 0))
    run_on_start = bool(sched_cfg.get("run_on_start", True))
    if not rt["users"]:
        run_on_start = False  # 无用户时空转，等 web 配置热重载
        interval = max(interval, 5)
    sched_state["interval_minutes"] = interval
    sched_state["jitter_minutes"] = jitter
    logger.info("启动定时调度，每 %d 分钟一轮 (±%d 随机扰动)", interval, jitter)
    try:
        def _first_run():
            """启动首轮节流：上轮完成 <5 分钟则跳过（连环重启不轰炸推送）。"""
            try:
                import sqlite3 as _sq
                from datetime import datetime as _dt
                db = (cfg.get("output") or {}).get("db_path", "data/prices.db")
                row = _sq.connect(db).execute(
                    "SELECT MAX(fetched_at) FROM flight_prices").fetchone()
                if row and row[0]:
                    age = (_dt.now() - _dt.strptime(
                        row[0][:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
                    if age < 300:
                        logger.info("[启动] 上轮 %.0f 分钟前已完成，跳过首轮",
                                    age / 60)
                        return
            except Exception:
                pass
            sweep()

        run_scheduler(_first_run, sched_state,
                      run_on_start)  # BlockingScheduler，阻塞至此
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，停止监控")


if __name__ == "__main__":
    main()
