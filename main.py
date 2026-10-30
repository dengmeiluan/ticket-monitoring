# -*- coding: utf-8 -*-
"""机票价格监控 主入口（多租户版）

用法:
    python main.py # 按 config.yaml 启动定时监控
    python main.py --once # 每条航线只跑一次后退出
    python main.py -c other.yaml # 指定配置文件

多租户模型：采集与告警正交——
  采集层按 (航线, 日期) 去重共享（多人盯同航线只采一份），
  告警层按用户分发（各自的阈值 / 钉钉群 / @手机号）。
  去哪儿接口有 ~5 分钟全局限流（与航线无关），查询间错峰。
"""
import argparse
import json

__version__ = "1.5.306"
import os
import subprocess
import sys
import time
import concurrent.futures
from pathlib import Path

import yaml

from core.logger import setup_logger
from core.models import Route, price_band_ok
from core.intl import is_intl_route
from core.pacing import Pacing, stagger_offset, parse_local_ts
from core.storage import PriceStorage
from core.alerter import Alerter, sanitize_desp
from core.scheduler import run_scheduler
from core.notifier import build_notifier
from crawlers import REGISTRY
from crawlers.base import channel_slot


class _NoDupKeyLoader(yaml.SafeLoader):
    """重复键拒收加载器：yaml 规范对重复键的通行实现是静默 last-wins
    ——route 块混入重复 to_name/dates 时整条航线被吞、阈值被顶（r339
    生产事故实录：一个写盘动作丢 16 条航线）。加载层即拒，坏写入在
    启动/热重载当场炸而非静默丢数据。"""


def _construct_mapping_no_dup(loader, node, deep=False):
    seen = set()
    for k_node, _v in node.value:
        k = loader.construct_object(k_node, deep=deep)
        if k in seen:
            raise yaml.constructor.ConstructorError(
                None, None,
                f"配置出现重复键 {k!r}——YAML 重复键会静默吞掉前值"
                f"（航线块丢失形态），请检查配置写入工具",
                k_node.start_mark)
        seen.add(k)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_NoDupKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_dup)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=_NoDupKeyLoader)


def _sent_hit_text(plat: str, k: str, hit: int, n: int) -> str:
    """哨兵 <10% 触发词面分档：池浅（n<30）常为临期退化库存（已飞
    日期池收窄，仅存行天然缺字段）或天然小池，键死证据弱——单独词面
    不打「站点改版」归因（归因误导实锤：退化轮字段缺失与键名失效
    同词面不可辨）；池深（n≥30）维持键死强信号归因。模块级纯函数：
    make_sweep_job 闭包内联词面不可单测（难测=设计问题）。"""
    if n < 30:
        return (f"{plat} 字段 {k} 命中 {hit}/{n}（<10%，池浅〔{n}<30〕"
                f"疑临期退化库存/天然小池，键死证据弱——池深轮再现再寻源）")
    return (f"{plat} 字段 {k} 命中 {hit}/{n}（<10%，疑似站点改版"
            f"键名失效，决策信息在静默丢失）")


def build_routes(routes_cfg: list) -> list:
    routes = []
    for r in routes_cfg or []:
        if r.get("enabled") is False:
            # 停用航线：配置保留在 config.yaml（心理线/日期不丢），
            # 不入运行时模型——调度、状态、明细、日历全链路自动豁免
            continue
        # 只要直飞（UI 快捷旗标）：任何来源（页面保存/手改 config）
        # 的 direct_only 都强制中转阈 0——alerter 的 alert_transfer>0
        # 门即全链关断点，防「UI 收起中转输入、配置里却留旧中转价」
        # 的双源劈叉
        _tr = 0 if r.get("direct_only") else float(
            r.get("alert_transfer", 0) or 0)
        routes.append(Route(
            from_code=r["from"],
            from_name=r.get("from_name", r["from"]),
            to_code=r["to"],
            to_name=r.get("to_name", r["to"]),
            dates=list(r.get("dates", [])),
            alert_threshold=float(r.get("alert_threshold", 0) or 0),
            alert_direct=float(r.get("alert_direct", 0) or 0),
            alert_transfer=_tr,
            transfer_arrival_max=str(r.get("transfer_arrival_max", "02:00")),
            # 中转衔接下限与行李直挂必须传入 Route——漏传曾使主链路
            # （达标推送/总表/概览）的这两项配置整体失效（默认 0/""），
            # 而日报 dict 路径却生效，同一配置两条口径「时好时坏」
            transfer_layover_min=int(r.get("transfer_layover_min", 0) or 0),
            transfer_baggage=str(r.get("transfer_baggage", "") or ""),
            ret_date=str(r.get("ret_date", "") or ""),
            # 返程日多选（AiLao）：ret_dates 列表为准，legacy 单值键
            # 读取合并（去重保序）；两者皆空=单程
            ret_dates=list(dict.fromkeys(
                [d for d in (r.get("ret_dates") or [])
                 if str(d or "").strip()]
                + ([r["ret_date"]] if str(r.get("ret_date") or "").strip()
                   else []))),
            dep_time_min=str(r.get("dep_time_min", "") or ""),
            dep_time_max=str(r.get("dep_time_max", "") or ""),
            # r341 四门：价格上限/排除跨天/到达时段窗（模型+alerter
            # 同批；漏传=配置键整体失效的重演防线，同 transfer 门判例）
            price_max=float(r.get("price_max", 0) or 0),
            no_cross=bool(r.get("no_cross", False)),
            arr_time_min=str(r.get("arr_time_min", "") or ""),
            arr_time_max=str(r.get("arr_time_max", "") or ""),
            # r339j 五门：最长飞行总时长小时（0=不限；漏传=配置键整体
            # 失效的重演防线，同 transfer 门判例）
            max_duration_h=float(r.get("max_duration_h", 0) or 0),
            # r342 三门：最长中转衔接/排除经停/排除共享（漏传=配置键
            # 整体失效，同 transfer 门判例）
            transfer_layover_max=int(
                r.get("transfer_layover_max", 0) or 0),
            exclude_stop=bool(r.get("exclude_stop", False)),
            exclude_share=bool(r.get("exclude_share", False)),
            airlines=str(r.get("airlines", "") or ""),
            no_lcc=bool(r.get("no_lcc", False)),
            min_baggage=int(r.get("min_baggage", 0) or 0),
            widebody_only=bool(r.get("widebody_only", False)),
        ))
    return routes


def build_users(cfg: dict) -> list:
    """归一化用户列表；兼容旧单用户格式（无 users 键则整体作为一个用户）。"""
    if "users" in cfg:
        raw_users = cfg["users"] or []
    else:
        raw_users = [{"name": "default", **{
            k: cfg[k] for k in ("routes", "specials", "special_radar",
                                "platforms", "schedule", "notifier")
            if k in cfg}}]
    users = []
    for i, u in enumerate(raw_users):
        # 特价订阅可独立于航线存在（r319）：只订特价的用户同样入运行时
        if not u.get("routes") and not u.get("specials") \
                and not u.get("special_radar"):
            continue
        users.append({
            "name": str(u.get("name") or f"user{i+1}"),
            "routes": build_routes(u.get("routes")),
            "specials": u.get("specials") or [],
            "special_radar": u.get("special_radar") or {},
            "platforms": u.get("platforms") or cfg.get(
                "platforms", ["qunar", "fliggy", "tongcheng", "tuniu"]),
            "notifier": u.get("notifier") or {},
            "schedule": u.get("schedule") or cfg.get("schedule") or {},
        })
    return users


def _apply_browser_dir(cfg):
    """crawler.browser_dir：chromium 内核缓存位可配置（用户反馈「WIN
    安装的依赖文件全堆在 C 盘」——playwright 默认装
    %LOCALAPPDATA%\\ms-playwright 约 500MB 不可选盘）。空=渠道默认位
    行为不变；配置后内核安装与查找全部指向该目录（进程内全部浏览器
    子进程经环境变量继承）。启动级语义：安装发生在启动检查点，运行
    中改配置不迁移已装内核（全局卡标 ♻ 重启生效）。"""
    d = str((cfg.get("crawler") or {}).get("browser_dir") or "").strip()
    if d:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.abspath(
            os.path.expanduser(d))
    return bool(d)


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
        # 显式指向全局注册表（playwright 各平台标准缓存位），
        # 使安装与启动同轨（R50：LOCALAPPDATA 单一写法在
        # linux/mac 冻结态拼出相对路径找不到已装内核）
        if sys.platform == "win32":
            _pw_cache = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
        elif sys.platform == "darwin":
            _pw_cache = os.path.expanduser("~/Library/Caches/ms-playwright")
        else:
            _pw_cache = os.path.expanduser("~/.cache/ms-playwright")
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _pw_cache)
    os.environ.setdefault(
        "PLAYWRIGHT_DOWNLOAD_HOST",
        "https://cdn.npmmirror.com/binaries/playwright")
    pkg = os.path.dirname(playwright.__file__)
    # 驱动自带 node 名平台化（R50：win=node.exe，linux/mac=node）
    node = os.path.join(
        pkg, "driver", "node.exe" if sys.platform == "win32" else "node")
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


# 解析哨兵报警状态：(platform, field) → 上次报警日期（每渠道×字段每天至多一条）
_SENT_LAST = {}
# 连续命中天数：结构性无源字段连续第 3 天起降为 INFO——
# 如实催修但不再淹没真告警；断档（跳过一天）自动归零，恢复即重新
# 从 WARNING 起报
_SENT_CNT = {}
# 窗粒度供给基线：(platform, field, from, to, date) → 末次供给日。
# 该航线窗任一轮某字段分子 >0 即「该渠道在该窗供给过此字段」——
# 告警只对「曾见过真值后归零」触发；窗口诞生起恒零是渠道×窗的
# never-supplied 特征（SHA↔HAK 2027 四窗实证：URC 时代 100% 全勤、
# 换窗后恒零、起燃日=窗诞日），观测面由 conn 壳连续性哨与 dump
# 调研兜底，字段哨不再为其燃警。持久化见 _sent_load/_sent_save。
_SENT_SUPPLIED = {}
# 行数塌方检测：platform → 当天近 8 轮明细行数（进程内存；重启后重新
# 累计基线可接受——塌方是持续性现象，重启丢一轮基线不漏报持续故障）
_ROW_HIST = {}
# 渠道整轮零记录连续计数：platform → 连续零记录轮数。「零记录」（风控
# 断供 ok=false rows=0 形态）不产生记录行，行历史池（_ROW_HIST）对该
# 形态不入池——重启后基线为空即永不告警（tuniu 179991 断供 11.5h+
# 三哨全盲实录）。本计数只依赖「渠道本轮有无行」，与行历史池无关。
_ZERO_STREAK = {}
# 渠道部分断供连续计数：platform → 连续「有记录查询 <50%」轮数。
# 合计口径（ch_rows/zrow）对「部分 (route,date) 断供」失明——单查询
# 薄样本在场即合计非零、整哨静默（tuniu 179991 期间 1/4 查询在场
# 实录）。与 zrow 互斥分工：全断归 zrow，部分断归本哨。
_QSUP_STREAK = {}
# 域级全断连续计数与供给基线（r333）：qsup 的 sup=0 域原让渡 zrow，
# 而 zrow 输入=平台合计——「部分域全断」形态（tuniu dom 断供 intl
# 出数，dom 断供 5 天零告警实录）对双哨同时失明。streak 键
# (plat, dom)；基线 _DOMZERO_SEEN 记「本进程曾见该域 sup>0」（窗口
# 诞生起恒零=tongcheng intl 结构零载体，静默防误报）。基线进程内：
# 重启丢失语义与 zrow streak 一致（重启时已在断供中的域静默至恢复
# 再断，运行期新断供主场景全覆盖）。与 zrow 互斥分工不变：全平台
# 零记录归 zrow，域级全断（平台内任一其他域有记录）归本哨。
_DOMZERO_STREAK = {}
_DOMZERO_SEEN = {}
# 锚定仓库 data 目录：相对路径禁用——部分进程 CWD
# 不同（计划任务/手动启动差异）时状态加载失效=当日重复告警 ×4、
# 连续天数计数恒 0（「连续 3 天降 INFO」从未触发）
_SENT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "sentinel_state.json")
# 冻结态（PyInstaller）下 __file__ 在 _internal 里，直接用会把数据
# 写进程序内部目录（用户看不到、升级就丢）。统一走 core.paths。
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    from core.paths import app_root as _app_root
    _REPO_ROOT = _app_root()


def _open_console(url: str, logger=None) -> bool:
    """首次使用时把控制台拉到用户面前。返回是否真的打开了。

    不打开的话，双击 exe 的人只会看到一个黑窗口——他不知道要复制
    一行 URL 到浏览器，最常见的反应是「点开没反应，关了」。
    失败只记一句日志，绝不影响监控启动（无桌面环境/服务器上跑是正常的）。
    """
    try:
        if os.environ.get("TICKET_NO_OPEN"):
            return False            # 测试/服务器显式关闭
        import webbrowser
        ok = webbrowser.open(url, new=2)
        if ok:
            return True
        raise RuntimeError("webbrowser 未接管")
    except Exception as e:
        if logger is not None:
            logger.info("（未能自动打开浏览器：%s；请手动访问 %s）",
                        type(e).__name__, url)
        return False


def _sent_state_path():
    """哨状态落盘路径（写入面生产资格门，与 notifier._append_push_history
    同构三§7）：pytest 入口有 conftest autouse 隔离，但 demo/重放/探针
    类旁路进程（python 直跑）import main 即共享仓库 data 写面——合成
    记录的供给基线化石键与连续计数覆写曾写入生产哨状态（r320 观测
    立案）。显式重定向（SENTINEL_STATE_FILE）永远放行；未设重定向且
    非生产形态落临时目录独立文件（静默拒写生产面）；读侧同走本函数
    防读写劈叉。判定按入口文件名后缀，fail-open 边界与账本门同款
    （同名巧合才放行，认边界不叠过度工程）。"""
    env = (os.environ.get("SENTINEL_STATE_FILE") or "").strip()
    if env:
        return env
    if getattr(sys, "frozen", False):
        return _SENT_PATH
    a0 = str(sys.argv[0] if sys.argv else "").replace("\\", "/").lower()
    if a0.endswith("main.py") or a0.endswith("webui.py"):
        return _SENT_PATH
    import tempfile
    return os.path.join(tempfile.gettempdir(),
                        "ticket-monitor-sentinel-state.json")

# 磁盘水位地板（GB）：低于此值 DB 写入/走势渲染开始有挤占风险——
# 磁盘满时降级语义虽正确（补位跳过不炸轮），但静默无感知，运维侧
# 需要可感知信号。每轮扫描开头检查一次（15 分钟粒度足够）。
DISK_FLOOR_GB = 5.0


def disk_low(root, floor_gb=DISK_FLOOR_GB):
    """磁盘剩余水位检查：剩余空间低于地板返回 True。检查自身故障
    （路径不存在等）不误报不炸轮。"""
    try:
        import shutil
        return shutil.disk_usage(root).free < floor_gb * 1024 ** 3
    except Exception:
        return False


def _anchored(p, default):
    """CWD 漂移免疫（与 _SENT_PATH 同族收口）：config 相对路径
    锚定仓库根——计划任务/手动启动 CWD 不同曾另起新库新日志，
    _first_run 的 300s 节流查到空库必不跳过（首轮重推）。"""
    p = (str(p) if p else "").strip() or default
    return p if os.path.isabs(p) else os.path.join(_REPO_ROOT, p)


_STORAGE_STATE = os.path.join(_REPO_ROOT, "data", ".storage_paths.json")


def _load_storage_paths() -> dict:
    """上次成功启动时使用的绝对存储路径（跨重启迁移的源）。

    r342：旧实现只从「出厂默认路径」搬到自定义路径——第二次自定义
    改自定义时源恒缺席，所谓「无缝迁移」只成立一次。状态文件独立于
    config.yaml 与 data 库本身，启动成功即落盘；损坏/缺失按空处理，
    行为回退到默认路径，无迁移副作用。"""
    try:
        with open(_STORAGE_STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_storage_paths(db, ud, log, bdir) -> None:
    """启动成功后记录生效绝对路径（tmp+replace 原子写，失败不阻断）。"""
    try:
        os.makedirs(os.path.dirname(_STORAGE_STATE), exist_ok=True)
        tmp = _STORAGE_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"db": os.path.abspath(db),
                       "user_data": os.path.abspath(ud),
                       "log": os.path.abspath(log),
                       "browser_dir": os.path.abspath(bdir) if bdir else ""},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, _STORAGE_STATE)
    except Exception:
        pass


def _migrate_db_if_needed(old_db, new_db, sentinel_abs) -> bool:
    """db_path 变更后的旧库迁移（r339 用户指令「一切配置可变更化」）：
    旧库存在且新路径无文件 → 整体搬迁（含 -wal/-shm 伴生件，防 WAL
    未合卷丢最近写入）；新旧同路径/源缺席 → 不动。失败抛给调用方
    降级（沿旧路径继续，不阻断启动）。"""
    old_db, new_db = os.path.abspath(old_db), os.path.abspath(new_db)
    if old_db == new_db or not os.path.exists(old_db)             or os.path.exists(new_db):
        return False
    os.makedirs(os.path.dirname(new_db), exist_ok=True)
    import shutil
    for suffix in ("", "-wal", "-shm"):
        src = old_db + suffix
        if os.path.exists(src):
            shutil.move(src, new_db + suffix)
    return True


def _migrate_user_data_if_needed(old_ud, new_ud) -> bool:
    """user_data 目录迁移：仅目标不存在（或为空）时整体搬迁——
    目标已有登录态不覆盖（登录态丢失成本高于旧档保留）。"""
    old_ud, new_ud = os.path.abspath(old_ud), os.path.abspath(new_ud)
    if old_ud == new_ud or not os.path.isdir(old_ud)             or (os.path.isdir(new_ud) and os.listdir(new_ud)):
        return False
    os.makedirs(os.path.dirname(new_ud), exist_ok=True)
    import shutil
    shutil.move(old_ud, new_ud)
    return True


def _recent_sweep_age(db_path):
    """上轮落库距今秒数；DB 缺失/不可读/空表返回 None（调用方按不跳过）。"""
    try:
        import sqlite3 as _sq
        from datetime import datetime as _dt
        row = _sq.connect(db_path).execute(
            "SELECT MAX(fetched_at) FROM flight_prices").fetchone()
        if row and row[0]:
            return (_dt.now() - _dt.strptime(
                row[0][:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        pass
    return None


class _FirstRunGate:
    """首轮节流门（first-only）：仅进程启动后的首次触发检查「上轮落库
    是否新鲜」，新鲜则跳过首轮（连环重启不轰炸推送），之后恒放行。
    每轮触发都重查会把 5 分钟级短周期的实际轮距拉长一个数量级——
    单轮扫描时长超过间隔时，每个对齐点都距上轮落库不足节流窗。"""

    def __init__(self, age_fn, within_s=300):
        self._age_fn = age_fn
        self._within_s = within_s
        self._armed = True
        self.last_age = None  # 首检读到的龄值（日志单次读库用）

    def should_skip(self):
        if not self._armed:
            return False
        self._armed = False
        self.last_age = self._age_fn()
        return self.last_age is not None and self.last_age < self._within_s


def _sent_load():
    """哨兵状态落盘回读：进程重启不得让当日已报警字段重复告警。
     值为 [日期, 连续天数]；旧格式（纯日期串）兼容读入。告警留痕键
    按段数分形回读：平键 (plat,fld)（行为型哨/zrow/qsup 族）与窗键
    (plat,fld,fc,tc,date)（字段/行型哨，与供给基线同粒度）。供给基线
    家族（supplied| 前缀，键含窗四元组）与 zdom 域供给基线
    （domzero| 前缀，键=(plat,dom)）同文件分族回读。"""
    import json as _json
    import os as _os
    try:
        with open(_sent_state_path(), encoding="utf-8") as f:
            for k, v in _json.load(f).items():
                if k.startswith("supplied|"):
                    parts = k.split("|", 5)
                    if len(parts) == 6:
                        _SENT_SUPPLIED[tuple(parts[1:])] = v
                    continue
                if k.startswith("domzero|"):
                    parts = k.split("|", 2)
                    if len(parts) == 3:
                        _DOMZERO_SEEN[(parts[1], parts[2])] = v
                    continue
                if k.startswith("loginstreak|"):
                    _LOGIN_ALERT_STREAK[k.split("|", 1)[1]] = int(v or 0)
                    continue
                parts = k.split("|")
                if len(parts) == 5:
                    # 窗键控告警留痕（与供给基线同粒度）
                    _wk = tuple(parts)
                    if isinstance(v, list):
                        _SENT_LAST[_wk] = v[0]
                        _SENT_CNT[_wk] = int(v[1] or 0)
                    else:
                        _SENT_LAST[_wk] = v
                    continue
                plat, fld = k.split("|", 1)
                if isinstance(v, list):
                    _SENT_LAST[(plat, fld)] = v[0]
                    _SENT_CNT[(plat, fld)] = int(v[1] or 0)
                else:
                    _SENT_LAST[(plat, fld)] = v
    except Exception:
        pass


def _sent_save():
    import json as _json
    import os as _os
    try:
        _sent_file = _sent_state_path()
        _os.makedirs(_os.path.dirname(_sent_file), exist_ok=True)
        out = {"|".join(k): [v, _SENT_CNT.get(k, 0)]
               for k, v in _SENT_LAST.items()}
        for k, v in _SENT_SUPPLIED.items():
            out["supplied|" + "|".join(k)] = v
        for k, v in _DOMZERO_SEEN.items():
            out["domzero|" + "|".join(k)] = v
        for k, v in _LOGIN_ALERT_STREAK.items():
            out["loginstreak|" + k] = v
        with open(_sent_file, "w", encoding="utf-8") as f:
            _json.dump(out, f, ensure_ascii=False)
    except Exception:
        pass


def _sent_backfill_domzero(db_path):
    """zdom 供给基线 DB 回填（r334 案③）：_DOMZERO_SEEN 持久化之外的
    首启补层——哨上线时渠道已处断供中的域（tuniu dom 断供第 5 天实
    录：zrow 被 intl 行压住、zdom 被基线门压住的无哨在响态），进程内
    与持久化基线双双为空=永静默盲区。DB 历史行证明「曾供给」（该平台
    该域存在任意历史行即成立——行在=该域查询活过），按航线对
    is_intl_route 判域补记；全库史结构零域（tongcheng intl）无行可证
    不补记，静默语义保留。幂等：已有基线零操作；DB 缺失/不可读零炸。"""
    if not db_path or not os.path.exists(db_path):
        return
    import sqlite3 as _sq
    try:
        con = _sq.connect(db_path)
        try:
            cur = con.execute(
                "SELECT DISTINCT platform, from_city, to_city "
                "FROM flight_prices")
            added = False
            for plat, fc, tc in cur:
                if not plat or not fc or not tc:
                    continue
                dom = "intl" if is_intl_route(fc, tc) else "dom"
                if not _DOMZERO_SEEN.get((plat, dom)):
                    _DOMZERO_SEEN[(plat, dom)] = True
                    added = True
            if added:
                _sent_save()
        finally:
            con.close()
    except Exception:
        pass


# 桶键 → extra 行键映射（基线回填的宽松判据）：与 _field_sentinel
# buckets 的分子读取同源但只判「行内曾出现该键的非空形态」——宽松门
# 只会多补不漏补（占位值族多补的代价=断链恢复时多一次人工核对；
# term/apt 族并集键任一行键非空即算，与桶分子口径一致）
_SUP_ROWKEY = {
    "cabin": ("cabin",), "meal": ("meal",), "prate": ("prate",),
    "plane": ("plane",), "psize": ("planeSize",),
    "discount": ("discount",),
    "avgd": ("avgDelay",), "page": ("planeAge",),
    "cancel": ("cancelRate",), "bridge": ("bridgeRate",),
    "share": ("shareCarrier",), "few": ("fewTicket",),
    "term": ("depTerminal", "arrTerminal"),
    "tterm": ("transTerminal",), "svc": ("transferService",),
    "lft": ("leftTickets",), "ccode": ("cabinCode",),
    "apt": ("depAirport", "arrAirport"),
    "aptc": ("depAirportCode", "arrAirportCode"),
    "stopcity": ("stopCitys",), "layover": ("layover",),
    "bag_direct": ("transferBaggage",), "trans": ("transCity",),
}


def _sent_backfill_supplied(db_path):
    """基线断代修复：状态文件里窗三段为空的 supplied 键（窗粒度上线
    前的渠道×字段粒度供给记录，迁移时原样留档）在内存与磁盘均为死重
    ——窗粒度告警门查不到它们，而它们证明的「历史曾有供给」恰是
    「曾供给后归零」判据。断链发生在迁移之前时，迁移后恒零永不重记
    supplied，never-supplied 门把真断链错判成新窗无源静默（fliggy|
    prate + tongcheng 四键断链 7 天零告警实录）。回填：按空窗键的
    (渠道,字段) 全库扫 DB 历史行，行内非空形态在场即按该行窗四元组
    补记供给基线（末次供给日=行 fetched_at，ORDER BY 保证后写覆盖）；
    trans 供给键（行型断供哨，晚于迁移上线）随全库渠道一并回填——
    新哨首启即继承历史中转供给史。回填毕删除空窗死键并落盘（幂等：
    下次启动零空窗键零触发）。返回补记键数（测试锚）。"""
    stale = [k for k in _SENT_SUPPLIED if not (k[2] and k[3] and k[4])]
    if not stale or not db_path or not os.path.exists(db_path):
        return 0
    targets = {}   # plat → {fld,…}：空窗键证明过的历史供给面
    for plat, fld, *_ in stale:
        targets.setdefault(plat, set()).add(fld)
    for plat in {k[0] for k in _SENT_SUPPLIED}:
        targets.setdefault(plat, set()).add("trans")   # 行型哨新键随批
    import sqlite3 as _sq
    import json as _json
    added = 0
    try:
        con = _sq.connect(db_path)
        try:
            cur = con.execute(
                "SELECT platform, from_city, to_city, depart_date, extra,"
                " fetched_at FROM flight_prices ORDER BY fetched_at")
            for plat, fc, tc, dd, extra, fts in cur:
                flds = targets.get(plat)
                if not flds or not extra or not (fc and tc and dd):
                    continue
                try:
                    obj = _json.loads(extra)
                except Exception:
                    continue
                if not isinstance(obj, list):
                    continue
                hit = set()
                for f in obj:
                    if not isinstance(f, dict):
                        continue
                    for fld in flds:
                        if fld in hit:
                            continue
                        for rk in _SUP_ROWKEY.get(fld) or ():
                            v = f.get(rk)
                            if v is None or isinstance(v, bool):
                                continue
                            if isinstance(v, (int, float)) or str(v).strip():
                                hit.add(fld)
                                break
                _day = str(fts or "")[:10] or None
                for fld in hit:
                    sk = (plat, fld, str(fc), str(tc), str(dd))
                    if _day and sk not in _SENT_SUPPLIED:
                        added += 1
                    if _day:
                        _SENT_SUPPLIED[sk] = _day
        finally:
            con.close()
    except Exception:
        return added
    for k in stale:
        _SENT_SUPPLIED.pop(k, None)
    _sent_save()
    return added


def _split_expired_queries(queries, today):
    """查询集 → (在采, 过期)。监控日期早于今日的查询跳过采集：过期航班
    无购买意义，而渠道对过期查询会滚动返回其他日期航班（qunar/tongcheng
    滚次日、ctrip 滚两日，DB 1996 行实证）——照常落库即把别的日期的价
    挂进过期桶，曲线画活点、推送按过期日期呈现（决策级错位）。跳过后
    过期日期曲线自然冻结在最后真实轮、推送自然不再错位，渠道礼貌预算
    同步节省。"""
    live, expired = [], []
    for q in queries:
        (expired if (q[2] and q[2] < today) else live).append(q)
    return live, expired


def _channel_zero_sentinel(ch_rows, logger):
    """渠道整轮零记录哨：本轮该渠道全部查询合计 0 行 → 连续计数 +1，
    连续 ≥2 轮 WARNING（当日至多一条，复用 _SENT_LAST 状态文件防刷屏）；
    恢复出数即归零。单轮零记录不报（瞬时风控常态，tuniu 179991 单轮
    自愈先例）。「零记录」形态不产生记录行，行数塌方哨（_ROW_HIST 池）
    与「有记录 0 行明细」观测（no_det）对该形态双双失明——本哨在渠道
    行数聚合层观测，覆盖「请求发出但渠道零返回」的断供盲区。"""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    for plat, n in (ch_rows or {}).items():
        if n > 0:
            _ZERO_STREAK[plat] = 0
            continue
        streak = _ZERO_STREAK.get(plat, 0) + 1
        _ZERO_STREAK[plat] = streak
        if streak < 2:
            continue
        key = (plat, "zrow")
        if _SENT_LAST.get(key) == today:
            continue
        cnt = _SENT_CNT.get(key, 0) + 1 if _SENT_LAST.get(key) == yest else 1
        _SENT_CNT[key] = cnt
        _SENT_LAST[key] = today
        _sent_save()
        msg = (f"渠道 {plat} 连续 {streak} 轮零记录（请求发出但渠道零返回，"
               f"疑似风控断供/接口失效），已持续观测——若为风控请留意"
               f" --login 恢复，持续多日请核渠道接口存亡")
        if cnt >= 3:
            logger.info("[解析哨兵][连续%d日] %s", cnt, msg)
        else:
            logger.warning("[解析哨兵] %s", msg)


_LOGIN_ALERT_STREAK = {}   # plat -> 连续在燃轮数（内存态：重启复位=
#                           重新累计，与 login_suspect 类级标记同哲学）


def _channel_login_alert_sentinel(user_notifiers, logger):
    """渠道会话失效钉钉告警哨（r338 用户提案「渠道问题应告警出来方便
    干预」）：login_suspect（类级失效证据，采集现场产生点捕获）连续
    ≥2 轮在燃 → 推钉钉，让人及时到配置页重登。

    背景实录：qunar 会话失效后「三路径空结果」WARNING 只刷日志数小时
    ——日志用户不看、达标推送无达标不发生、UI stale 又被日历价清洗
    （同轮修复）——需人工干预类渠道问题必须浮出到推送面。

    纪律：单轮瞬时风控不鸣（≥2 与 zrow 同门槛）；当日去重、连续 ≥3 日
    降 INFO 只记（每 3 日再推一次防遗忘）；恢复单条通知（告警闭环——
    「好了没」不用再问）；推送面按用户启用平台过滤（多租户不扰无关
    用户）；send 单发零重试铁律不涉；正文短词面（防指纹带）且全部
    走安全集在册字符。"""
    import datetime as _dt
    from crawlers import REGISTRY
    today = _dt.date.today().isoformat()
    yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    for plat, cls in REGISTRY.items():
        if not hasattr(cls, "login_suspect"):
            continue
        targets = [(u, al.notifier) for u, al in user_notifiers
                   if plat in (u.get("platforms") or [])
                   and getattr(al, "notifier", None) is not None]
        if not targets:
            _LOGIN_ALERT_STREAK.pop(plat, None)
            continue
        key = (plat, "login")
        if getattr(cls, "login_suspect", False):
            streak = _LOGIN_ALERT_STREAK.get(plat, 0) + 1
            _LOGIN_ALERT_STREAK[plat] = streak
            _sent_save()   # streak 持久化：跨重启累计（长轮周期+频繁
            #               重启下内存态永到不了 2=告警哑火，生产实录）
            if streak < 2:
                continue
            if _SENT_LAST.get(key) == today:
                continue
            cnt = _SENT_CNT.get(key, 0) + 1 if _SENT_LAST.get(key) == yest else 1
            _SENT_CNT[key] = cnt
            _SENT_LAST[key] = today
            _sent_save()
            # 段落律 \n\n（钉钉 PC 不认单 \n），每段 ≤40 半角——行宽
            # 守卫钉在 tests/test_r340_push.py（手拼行直发 112 半角教训）
            msg = "\n\n".join((
                f"⚠ 渠道 {plat} 会话可能已失效",
                f"连续 {streak} 轮被服务端按未登录处理",
                "请到配置页「渠道登录」重新登录",
                "恢复后会收到通知"))
            if cnt >= 3 and cnt % 3 != 0:
                logger.info("[渠道告警][连续%d日] %s", cnt, msg)
                continue
            for _u, nf in targets:
                try:
                    nf.send("渠道登录态告警", msg)
                except Exception as e:
                    logger.warning("[渠道告警] 推送异常: %s", e)
        else:
            if _LOGIN_ALERT_STREAK.get(plat, 0) >= 2 \
                    and _SENT_LAST.get(key) in (today, yest):
                msg = "\n\n".join((
                    f"渠道 {plat} 登录态已恢复",
                    "服务端重新承认会话"))
                for _u, nf in targets:
                    try:
                        nf.send("渠道登录态恢复", msg)
                    except Exception as e:
                        logger.warning("[渠道告警] 恢复通知异常: %s", e)
                _SENT_CNT.pop(key, None)
                _sent_save()
            if _LOGIN_ALERT_STREAK.get(plat):
                _LOGIN_ALERT_STREAK[plat] = 0
                _sent_save()


def _channel_partial_sentinel(qry_sup, logger):
    """渠道部分断供哨（qsup）：本轮该渠道「有记录查询数/采集查询数」
    严格 <50% 且非全断 → 连续 ≥2 轮 WARNING（当日去重、连续 ≥3 日降
    INFO、恢复归零，与 zrow 同纪律，复用 _SENT_LAST/_SENT_CNT）。

    分母按域（dom/intl）分流、逐域独立评估（c330 F1）：渠道×域存在
    结构性零供给面（tongcheng 全库史 intl 零记录），合并口径会把
    「dom 满勤 + intl 全断」算成 4/24 恒 <50% 每日必鸣；按域拆分后
    dom 满勤不评估，假火自然消失。真部分断供按域告警，词面带「国内
    窗/国际窗」辨识；streak 键 (plat, dom) 域级独立，留痕键
    (plat, "qsup:dom"/"qsup:intl")。

    sup=0（域级全断）原无条件让渡 zrow（r330 设计），但 zrow 输入=
    平台合计行数——「部分域全断」形态（tuniu dom 断供 intl 出数，
    observe r333 备案①实录：dom 断供 5 天双哨零告警）对双哨同时
    失明。现行（r333）：域级全断在本哨内有条件评估，两道门防误报
    ——①防双响门：平台内任一其他域有记录才归本哨，全平台零记录
    仍归 zrow 领地（互斥分工不双响）；②供给基线门：本进程曾见该域
    sup>0 才评估（窗口诞生起恒零=tongcheng intl 结构零形态静默）。
    词面带「零记录」与域辨识，留痕键 (plat, "zdom:dom"/"zdom:intl")
    与部分断供分族。

    合计口径对「部分 (route,date) 断供」失明：单查询薄样本在场即合计
    非零，zrow/行数塌方/no_det 三面全静默（实录：渠道风控期间恒仅
    1/4 查询出薄样本、其余零记录，三面数十轮全静默）。**全平台零
    记录（每域 sup=0）归 zrow 领地，本哨不双响**——互斥分工防同一
    故障两条告警；部分域全断归本哨域级评估（见上）。恰好 50%（2/4）
    不属部分断供（严格比较，薄样本带与健康带的分离带
    取整半）。分母语义=本轮完成采集的查询数（safe_fetch 异常自吞使
    「发起」与「完成」现实恒等价；若未来异常改为上浮，分母须随语义
    复核）。"""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    _dom_txt = {"dom": "国内窗", "intl": "国际窗"}
    for plat, doms in (qry_sup or {}).items():
        for dom, pair in (doms or {}).items():
            sup, tot = pair
            if tot <= 0:
                # 零查询（停用/未订阅/该域无订阅）：不评估
                _QSUP_STREAK[(plat, dom)] = 0
                continue
            if sup >= tot:
                # 满勤：部分断供与域级全断的「连续」一并清零（恢复
                # 即归零；部分断供被满勤打断后须重新累计），并记域
                # 供给基线（域级全断哨的「曾供给」判据）
                _QSUP_STREAK[(plat, dom)] = 0
                _DOMZERO_STREAK[(plat, dom)] = 0
                _DOMZERO_SEEN[(plat, dom)] = True
                continue
            if sup <= 0:
                # 域级全断（r333 根治）：原无条件让渡 zrow——但 zrow
                # 输入=平台合计行数，「部分域全断」形态（tuniu dom
                # 断供 intl 出数，dom 断供 5 天零告警实录）对双哨
                # 同时失明。改有条件评估，两道门防误报：①防双响门
                # ——平台内任一其他域有记录才归本哨（全平台零记录
                # =zrow 领地，互斥分工不双响）；②供给基线门——窗口
                # 诞生起恒零（tongcheng intl 结构零载体）静默。连续
                # 语义与 zrow 同纪律：连续 ≥2 轮告警、当日至多一条、
                # 连续 ≥3 日降 INFO、恢复出数归零。
                _QSUP_STREAK[(plat, dom)] = 0
                if not any(p2[0] > 0 for d2, p2 in (doms or {}).items()
                           if d2 != dom):
                    _DOMZERO_STREAK[(plat, dom)] = 0
                    continue
                if not _DOMZERO_SEEN.get((plat, dom)):
                    _DOMZERO_STREAK[(plat, dom)] = 0
                    continue
                zstreak = _DOMZERO_STREAK.get((plat, dom), 0) + 1
                _DOMZERO_STREAK[(plat, dom)] = zstreak
                if zstreak < 2:
                    continue
                zkey = (plat, "zdom:" + dom)
                if _SENT_LAST.get(zkey) == today:
                    continue
                zcnt = (_SENT_CNT.get(zkey, 0) + 1
                        if _SENT_LAST.get(zkey) == yest else 1)
                _SENT_CNT[zkey] = zcnt
                _SENT_LAST[zkey] = today
                _sent_save()
                zmsg = (
                    f"渠道 {plat} {_dom_txt.get(dom, dom)}连续 {zstreak} 轮"
                    f"零记录（本轮其余窗口有数据，疑似风控/接口局部断供），"
                    f"已持续观测——若为风控请留意 --login 恢复")
                if zcnt >= 3:
                    logger.info("[解析哨兵][连续%d日] %s", zcnt, zmsg)
                else:
                    logger.warning("[解析哨兵] %s", zmsg)
                continue
            # 0 < sup < tot：薄样本也算「曾供给」（部分断供期间渠道
            # 仍活着，随后整域断供须能过基线门被评估）；有记录轮打断
            # 域级全断的「连续」累计（拍手形态 零→1/4→零 不得产出
            # 「连续 2 轮零记录」假词面——词面须与事实一致）
            _DOMZERO_SEEN[(plat, dom)] = True
            _DOMZERO_STREAK[(plat, dom)] = 0
            if sup * 2 >= tot:
                _QSUP_STREAK[(plat, dom)] = 0
                continue
            streak = _QSUP_STREAK.get((plat, dom), 0) + 1
            _QSUP_STREAK[(plat, dom)] = streak
            if streak < 2:
                continue
            key = (plat, "qsup:" + dom)
            if _SENT_LAST.get(key) == today:
                continue
            cnt = _SENT_CNT.get(key, 0) + 1 if _SENT_LAST.get(key) == yest else 1
            _SENT_CNT[key] = cnt
            _SENT_LAST[key] = today
            _sent_save()
            msg = (f"渠道 {plat} 部分断供：本轮{_dom_txt.get(dom, dom)}仅 "
                   f"{sup}/{tot} 个查询有记录"
                   f"（其余查询零记录，疑似风控/接口局部失效），已持续观测"
                   f"——若为风控请留意 --login 恢复")
            if cnt >= 3:
                logger.info("[解析哨兵][连续%d日] %s", cnt, msg)
            else:
                logger.warning("[解析哨兵] %s", msg)


def _xchan_ratios(xchan):
    """指纹组 → {platform: [组内最低/组中位比,…]}（渠道中位比观测的
    纯计算部分，便于单测）。组内 <3 渠道不产出。"""
    ratios = {}
    for _fp, byp in xchan.items():
        if len(byp) < 3:
            continue
        lows = {pl: min(vs) for pl, vs in byp.items()}
        med = sorted(lows.values())[len(lows) // 2]
        if med <= 0:
            continue
        for pl, v in lows.items():
            ratios.setdefault(pl, []).append(v / med)
    return ratios


def _stable_pool(rows: list) -> list:
    """采集池的确定性底序（同价并列班次身份漂移根治）。

    as_completed 完成序进池使池序随渠道完成序逐轮浮动，下游一切
    「同价取首」（min 稳定取首/TOP5 截断/比价组代表行）的首选班次
    身份随轮次翻转（实录：￥1760 同价双班 9C8807/9C8815 行2/行3
    对调——价格/差额/合规全同，漂移的只是行身份）。按纯身份键
    （起降时刻/航班号/航司/渠道）稳定排序：与价格无关——价格排序
    仍由下游各消费点自己的口径决定（_qual_price 与 page price 口径
    不同，采集层不提前分叉），本序只承载同价 tie-break 的确定性。
    池元素是 FlightPrice dataclass（safe_fetch 返回类型），属性访问
    直取；五字段 str 默认 "" 无缺键面。返回新列表不污染进池序。"""
    return sorted(rows, key=lambda f: (
        f.depart_time or "", f.arrive_time or "",
        f.flight_no or "", f.airline or "", f.platform))


# 路由级栅栏总超时：≈1.44× tuniu 5 重试圈实测最长 10.4min（00:07 轮
# SHA→HAK 00:21:08→00:31:30），慢渠道不误杀；其余渠道合法上界 ≤2.9min，
# 余量 >5×。超时只放行栅栏，不杀已泊车线程（线程随 shutdown(wait=False)
# 滞留，渠道自身无超时调用点另有 AbortSignal 治本）。
_ROUTE_FUT_TIMEOUT = 15 * 60


def _collect_route_futures(futs_map, timeout_s, logger):
    """路由级 futures 栅栏（r326 挂死根治）：concurrent.futures.wait
    总超时替代 as_completed 无界等待。

    00:33 资源耗尽把 tongcheng 页内 evaluate（playwright 设计无超时）
    打成永久泊车，as_completed 无 timeout + executor with 退出 join
    把单渠道泊车放大为整进程 30 分钟纯静默（4 渠道已抓行陪葬未落库）。
    返回 ([(渠道名, prices)...], [超时渠道名])——超时渠道由调用方按
    失败查询计健康口径；泊车线程不 join、不取消运行中 future。"""
    done, pending = concurrent.futures.wait(futs_map, timeout=timeout_s)
    for _pf in pending:
        logger.warning("[并发] %s 路由级超时(%ds)，按断供记健康时间线",
                       futs_map[_pf], timeout_s)
    out = []
    for fu in done:
        try:
            out.append((futs_map[fu], fu.result()))
        except Exception as e:
            logger.warning("[并发] %s 抓取异常: %s", futs_map[fu], e)
    return out, [futs_map[_pf] for _pf in pending]


def _field_sentinel(all_prices, logger):
    """解析层哨兵：按渠道统计决策字段命中率 + 中转衔接字段覆盖 + 行数
    塌方（扩容面：cabin/meal/prate 三字段之外）。

    站点改版（键名变更）过去只能靠人看 DB 才发现——同程 sts tx→td
    实锤：meal/prate 静默全空数日、8783 行无决策信息。行数 ≥20 且
    命中率 <10% 判定「疑似整字段失效」，WARNING 留痕（每渠道×字段
    每天至多一条防刷屏）。字段结构性无源的渠道（渠道页面/报文本无
    此信息）经 _SENT_DEAD_KEYS 豁免不入比率观测——告警只对「曾有
    真源后断链」的活字段触发，不追认结构性无源为故障。

    扩容项（决策关键字段，P0 调研定论）：
    - plane 机型命中率（<10%）：qunar DOM 名行自源提取的存活观测；
    - transferBaggage=="direct" 命中率（<1% 且 ≥10 中转行）：五渠道仅
      qunar 偶发有源，「直挂筛选的中转达标告警实质近空」的 P0 缺口
      无观测不修——此哨兵即寻源进度的温度计（分母改中转行，
      全行分母曾让直飞占比高的渠道近乎恒真）；
    - 中转行 layover 覆盖率（<10% 且 ≥20 中转行；双键兼容——
      原只读 normalize 后的 layoverM，而爬虫原始 extra 写的键是
      layover，全库 0 命中=健康渠道 ctrip 天天被假告警、真断供反而
      与日常同面目）：中转停留单点依赖 ctrip _propagate_layover 补全，
      ctrip 解析坏→全链停留静默归零；
    - 行数塌方：本轮行数 < 近 8 轮中位数 30% 且连续 ≥2 轮——「有响应
      但明细骤减 90%」时字段命中率与 pulse 双双不报（分池
      键含航线+日期、记当条记录行数——单平台累计值混池曾让基线失真）。

     扩容：
    - 渠道指纹中位比（同指纹 ≥3 渠道组内「本渠道最低/组中位」，样本
      ≥20 且 p50 偏离 ±10% 告警）：渠道口径系统性漂移（飞猪税前史实、
      qunar minPrice 重摇）的第二层观测——行级 0.5x 守卫之外
      的兜底观测；
    - 经停城市覆盖（≥5 经停行且 <10%）：「经停」徽标无地点，「停哪」
      无从决策；
    - 行数绝对下限（同查询其他渠道中位 ≥30 而本渠道 <10 连续 2 轮）：
      塌方哨兵 base≥20 门槛下，小渠道长期低位成了自己的基线永不触发；
    - 连续命中 ≥3 天的哨兵降级 INFO（结构性无源字段每日一报曾淹没
      真告警），断档自动恢复 WARNING。

    刻意不观测：stopFlight（qunar H5 经停布尔有标记但
    stopsCitys 恒空——入城市覆盖分母=制造新的结构性永空假火，与
    死键表同理）。discount 不在排除列：折扣与无折扣可售按渠道按
    航班稀疏出勤曾是「<10% 出勤线必误报」的前提，「全价」词面并入
    后（flightnorm.discount_txt 单源，五渠道恒有源）前提已不成立，
    按比率观测入列——断链即词面代行静默死亡的强信号。

     扩容：
    - 结构性死键表（qunar|prate、qunar|plane、fliggy|meal）：观测键=
      渠道×字段，但现役路径无源的组合继续观测=健康渠道天天假告警，
      「疑似站点改版」归因错误（审计键名三方对账定论）；
    - 新决策字段命中率（shareCarrier/fewTicket/depTerminal）：同班同
      物理属性跨渠道应有值，键名失效静默死亡正是 tx→td 事故模式；
    - 渠道明细全空观测：extra 空/解析败/无价行的记录对哨兵与
      脉冲双双隐身（有记录 0 行明细形态），故单列观测。

    扩容：
    - 直飞行群分母分流（cabin/meal/prate/plane/psize/discount）：单件
      行属性在组合体（中转行）上无单一真值，全行分母曾让降级轮
      直飞 2 行满勤被 20 条中转行稀释成 2/22<10% 六键齐鸣假火——
      分子分母同口径只数直飞行，门槛平移 direct_n≥10（出勤率分母
      按行群切分的实现侧跟进）；机场码（apt/aptc）全行属性维持
      全行分母；
    - 恒 0 检查四键随族分流（avgd/cancel/bridge/page）：准点/取消/
      廊桥/机龄同为单件行属性，直飞售罄清空的降级夜全行分母
      （20 条中转行）撞分子恒 0 曾齐鸣「键名失效」假火——分子
      分母同步直飞行群、门槛 direct_n≥10，直飞行群在场时键死
      照报、售罄夜静默；
    - 跨渠道 IATA 码对分歧（(depAirportCode,arrAirportCode) 同航班号
      同指纹两渠道不一致）：DB 全库 293 组合级配对 d=0 纯净基线定证
      的零容忍告警面——分歧=某渠道码解析错或渠道下发异码，出票机场
      与展示不符的决策性错误；单轮分歧 ≥1 组即 WARNING（每日至多一
      条）。配对读 DB 原始行：_propagate_fields 补全只改推送期副本
      不落库，天然 pre-propagate 口径，补全不会掩盖分歧；
    - 机场 IATA 码覆盖率入比率观测（aptc 桶，union 口径同 apt）：码
      键单渠道键死会让配对退化成单源、分歧哨兵永不触发——<10% 即响
      （tx→td 事故模式第二道防线）；fliggy|aptc 入死键表（
      调研页面定证无源：全部 URC/SHA token 在 URL query/页级配置/
      筛选分面，0 处行级数据源，观测即天天假火）。
    """
    import json as _json
    import datetime as _dt
    import re as _re
    # 结构性死键（现役路径无源，告警=假火）：qunar 准点率 PC/H5 报文
    # 均无源；fliggy 餐食标签双态打标（有餐食/无餐食同位同构）后
    # 出勤率在爬坡，出勤口径转比率观测的门槛数据未足——维持死键
    # 备案防爬坡期假火，键死由 dump 冒烟观测兜底，出勤稳定后复评。
    # fliggy|cabin（调研后转有源但极稀疏：仅页面并列非经济舱单报价
    # 行才出现，快照 1/33 行；双价行撤键宁缺勿错——全行口径 ~3% 远
    # 低于 10% 阈值必假火，维持死键备案，键死由 dump 冒烟观测兜底）
    # qunar|plane 移出（第八批：H5 binfo.name[1] 真值机型
    # 直飞 83% 在场，死键备案失效，转入比率观测——解析断链 <10% 即响）
    _SENT_DEAD_KEYS = {("qunar", "prate"),
                       ("fliggy", "meal"), ("fliggy", "cabin"),
                       # qunar|cabin 键故意退场（H5 cabinDegree 与
                       # PC binfo1.cabin 两路撤伪定谳：跨源同一「段级
                       # 折扣桶冒充行级舱位」伪语义出口）——「站点改版
                       # 键名失效」语义不再适用，观测即天天假火
                       # fliggy 行级 IATA 码页面定证无源（全部
                       # URC/SHA token 在 URL query/页级配置/筛选分面，
                       # 0 处行级数据源）——观测即天天假火，同结构性
                       # 无源死键逻辑
                       ("fliggy", "aptc"),
                       ("qunar", "cabin")}
    # qunar|psize 随 plane 一并移出死键表——
    # binfo.name 括号体量与机型同一 fullmatch 源（H5 直飞 55% 在场，
    # 旧「仅 PC 路产出」理由已被证伪）；同源断链由 plane 哨兵覆盖，
    # psize 比率观测并行兜底
    # 新字段有源渠道白名单（/49 dump 冒烟实证命中率）：不在表内
    # 的渠道不告警（同死键表逻辑——无源渠道观测即假火）
    _SENT_FIELD_SOURCES = {
        ("qunar", "share"), ("ctrip", "share"), ("fliggy", "share"),
        ("tuniu", "share"),                                   # codeShare 24/46
        ("qunar", "few"),
        ("qunar", "term"), ("ctrip", "term"), ("tuniu", "term"),
        # 航站楼单侧命中（多航站楼侧近全量、单航站楼侧空串），dep/arr
        # 并集恒非 0——恒 0 才是键死
        # 扩容（渠道字段三批 dump 实证）：同程航站楼 dat/aat
        # 47/47 在场、同程中转增值服务 19/26 fps、ctrip 平均延误近乎
        # 全航班（「平均延误N分钟」content 26 档）
        ("tongcheng", "term"), ("fliggy", "term"),
        ("tongcheng", "svc"), ("ctrip", "avgd"),
        # 扩容（渠道字段四批 dump 实证）：ctrip 余票数近乎全政策
        # （quantity 148/148）、中转航站楼仅中转行（qunar 88%/ctrip 57%
        # 中转行）、fliggy 余票紧张标签 26/32
        ("ctrip", "lft"),
        ("qunar", "tterm"), ("ctrip", "tterm"),
        ("fliggy", "few"),
        # 扩容（渠道字段第七批 dump 实证）：机型体量四渠道
        # （ctrip craftinfo.kind 95%+/tongcheng amt 95/95/tuniu 71%/fliggy
        # 100%；qunar PC-only 已入死键表）、机场级定位五渠道 H5/报文层
        # 近全量（qunar binfo.depAirport 92/92）、tongcheng sts 四键
        # （机龄/廊桥/取消率/延误 95/95）、ctrip 廊桥率近乎全政策、
        # 舱位字母（ctrip nt=2 随政策 145/145、tuniu 32%）、机龄三渠道
        # （ctrip 100%/tuniu 59%/tongcheng 95/95）。
        # 注意：本集合只被下方恒 0 循环查询；psize/apt
        # 走比率循环（psize=直飞行群批、apt=全行批，两批同查
        # _SENT_DEAD_KEYS），在此处列出不生效——
        # 备案它们 dump 命中率于比率循环注释，勿误以为删本集合条目可停观测
        ("tongcheng", "avgd"),
        ("tongcheng", "cancel"), ("tongcheng", "bridge"),
        ("ctrip", "bridge"),
        # page 观测面豁免 (ctrip, page)：ctrip 机龄恒档守卫
        # （crawlers/ctrip.py _PLANEAGE_COARSE）置空后行内恒无键——
        # 「命中 0」是守卫预期行为非断链信号，断链监测责任移交守卫
        # 观察哨（撤守卫条件=逐日 '5' 占比回落，届时移除常量并恢复
        # 本表成员）
        ("tongcheng", "page"), ("tuniu", "page"),
        ("ctrip", "ccode"), ("tuniu", "ccode"),
        # 扩容（渠道字段第八批 dump 实证）：tongcheng 中转换乘楼
        # ss[0].aat 段级两日 48/48 在场（「T2」裸形态，transTerminal 同
        # 名键挂中转行）；fliggy transferTax（中转行内 100%）不设桶——
        # trans_n≥20 门槛在 fliggy 中转供给量级下永不可达，观测无意义，
        # 键死由 dump 冒烟兜底
        ("tongcheng", "tterm"),
        # 九批新键全部不设观测桶（稀疏事件型/软拒期，恒 0 告警
        # =天天假火，同 fliggy|transferTax 先例，键死由 dump 冒烟兜底）：
        # tongcheng|leftTickets（余1张 2/48 行稀缺事件型）、ctrip|
        # transferService（nt=103 联程明细 2/260，G5 产品行未在轮即无
        # 行）、qunar|transferService·labelNote（PC 软拒期恒 0 产出，
        # 复活预案搭车——同 qunar|psize 曾入死键表逻辑，PC 复活时随
        # prate/plane 一并评估移入观测）、fliggy|transTerminal（N=1 定
        # 证不足先观测 dump，不入桶）
    }
    buckets = {}
    xchan = {}   # 指纹 → {platform: [价,…]}（渠道中位比观测）
    iata_x = {}   # 指纹 → {platform: {(dep,arr) 码对,…}}（码对分歧观测）
    no_det = {}   # platform → 明细 0 行记录数（渠道全空观测）
    # 本函数在单 (航线×日期) 查询循环内调用——all_prices 同窗，
    # 窗三元组取首条记录（getattr 防御夹具无属性）
    _p0 = (all_prices or [None])[0]
    _win = (str(getattr(_p0, "from_city", "") or "") if _p0 else "",
            str(getattr(_p0, "to_city", "") or "") if _p0 else "",
            str(getattr(_p0, "depart_date", "") or "") if _p0 else "")
    for p in all_prices or []:
        if not getattr(p, "extra", ""):
            no_det[getattr(p, "platform", "?")] = \
                no_det.get(getattr(p, "platform", "?"), 0) + 1
            continue
        try:
            obj = _json.loads(p.extra)
        except Exception:
            no_det[getattr(p, "platform", "?")] = \
                no_det.get(getattr(p, "platform", "?"), 0) + 1
            continue
        if not isinstance(obj, list):
            no_det[getattr(p, "platform", "?")] = \
                no_det.get(getattr(p, "platform", "?"), 0) + 1
            continue
        b = buckets.setdefault(p.platform, {
            "n": 0, "direct_n": 0,
            "cabin": 0, "meal": 0, "prate": 0, "plane": 0,
            "trans_n": 0, "layover": 0, "bag_direct": 0,
            "stop_n": 0, "stop_city": 0,
            "share": 0, "few": 0, "term": 0, "svc": 0, "avgd": 0,
            "lft": 0, "tterm": 0,
            # 第七批观测桶（上方白名单注释块：来源渠道+命中率）
            "psize": 0, "apt": 0, "page": 0, "ccode": 0,
            "cancel": 0, "bridge": 0,
            # 机场 IATA 码覆盖率（比率观测，fliggy 入死键表）
            "aptc": 0,
            # 折扣词面出勤（比率观测，直飞行群口径——分母=direct_n）：
            # 直飞行恒有源——无折扣可售亦落「全价」词面
            # （flightnorm.discount_txt 单源），出勤高且稳，<10% 断链
            # 即键死信号
            "discount": 0})
        n_rows = 0
        for f in obj:
            if not isinstance(f, dict) or "price" not in f:
                continue
            b["n"] += 1
            n_rows += 1
            # 行群分流（直飞行群观测的分子分母口径）：中转行是两段
            # 拼接的组合体，单件行属性（舱位/餐食/准点率/机型）无单一
            # 真值可填——渠道以 0 占位被读层挡、段级伪语义已撤，混入
            # 全行分母曾让降级轮（直飞 2 行满勤 2/2）被 20 条中转行
            # 稀释成 2/22<10% 六键齐鸣假火。分子分母同口径只数直飞行。
            _is_trans = bool(str(f.get("transCity") or "").strip())
            if not _is_trans:
                b["direct_n"] += 1
                # 桶键→行键映射：psize 桶的行键是 planeSize（历史
                # 命名差），其余同名
                for k in ("cabin", "meal", "prate", "plane", "discount"):
                    if str(f.get(k) or "").strip():
                        b[k] += 1
                if str(f.get("planeSize") or "").strip():
                    b["psize"] += 1
                # 单件行属性四键（准点/取消/廊桥/机龄）分子随分母
                # 同步直飞行群：这四字段只挂直飞行（中转组合体结构性
                # 无源），恒 0 检查见下方 _DIRECT_ONLY 分流
                if isinstance(f.get("avgDelay"), int):
                    b["avgd"] += 1
                if str(f.get("planeAge") or "").strip():
                    b["page"] += 1
                if isinstance(f.get("cancelRate"), int):
                    b["cancel"] += 1
                if isinstance(f.get("bridgeRate"), int):
                    b["bridge"] += 1
            # 新决策字段命中率：物理属性跨渠道应有值，
            # 键名失效=静默死亡（tx→td 事故模式）
            if str(f.get("shareCarrier") or "").strip():
                b["share"] += 1
            if str(f.get("fewTicket") or "").strip():
                b["few"] += 1
            if (str(f.get("depTerminal") or "").strip()
                    or str(f.get("arrTerminal") or "").strip()):
                b["term"] += 1
            # 扩容：中转增值服务（同程 stss）——键名失效静默死亡
            # 同属 tx→td 事故模式
            if str(f.get("transferService") or "").strip():
                b["svc"] += 1
            # 扩容：ctrip 余票数（int 协议，None=无值不落）、
            # 中转航站楼（仅中转行，计数在 trans_n 块内）
            if isinstance(f.get("leftTickets"), int):
                b["lft"] += 1
            # 第七批观测（上方白名单注释块）：机场级定位/舱位字母
            # 走 str 非空口径（机龄/取消率/廊桥率已上移直飞行群块
            # ——分子分母同口径）；
            # psize/discount 已上移直飞行群块（分子分母同口径）
            if (str(f.get("depAirport") or "").strip()
                    or str(f.get("arrAirport") or "").strip()):
                b["apt"] += 1
            if str(f.get("cabinCode") or "").strip():
                b["ccode"] += 1
            if str(f.get("transCity") or "").strip():
                b["trans_n"] += 1
                # 双键兼容（根治假火）：layoverM 是 alerter 读取时
                # normalize 的产物，爬虫原始 extra 写的键是 layover——
                # 只读 layoverM 会全库 0 命中，健康渠道天天被假告警、
                # 真断供反而与日常同面目不可分辨
                _lay = f.get("layoverM") or f.get("layover")
                if isinstance(_lay, int) and _lay > 0:
                    b["layover"] += 1
                if str(f.get("transTerminal") or "").strip():
                    b["tterm"] += 1
            if f.get("transferBaggage") == "direct":
                b["bag_direct"] += 1
            # 经停城市覆盖（新观测）：「停」行只报经停不报地点，
            # 用户只见经停不知停哪——原始标记 stopCitys（qunar PC/ctrip/
            # tongcheng）或 _via=停（qunar H5 DOM 兜底）。fliggy 的
            # stopover 直落行刻意不入分母：经停地点在 tooltip 非
            # SSR 结构性无源（stopFlight 排除先例——入分母=制造
            # 结构性永空假火；SSR 化即升级信号，由调研升级哨兜底）
            _sc = str(f.get("stopCitys") or "").strip()
            if _sc or f.get("_via") == "停":
                b["stop_n"] += 1
                if _sc:
                    b["stop_city"] += 1
            # 渠道级系统性偏差观测：行级 0.5x 守卫之外的第二
            # 层——渠道口径整体漂移（飞猪税前史实、qunar minPrice 重摇）
            # 现有观测无一条会响。同指纹（航班号+起降时刻+中转+到达日）
            # 跨渠道组内「本渠道最低 / 组中位」，聚合 p50 判系统性偏离
            _code = str(f.get("code") or "").strip().upper()
            try:
                _pv = float(f["price"])
            except (TypeError, ValueError):
                _pv = 0.0
            if _code and price_band_ok(_pv, el=f):
                _fp = (_code, str(f.get("depTime") or ""),
                       str(f.get("arrTime") or ""),
                       str(f.get("transCity") or ""),
                       str(f.get("arrDate") or ""))
                xchan.setdefault(_fp, {}).setdefault(
                    p.platform, []).append(_pv)
            # IATA 码覆盖率（union 口径同 apt）+ 跨渠道码对
            # 配对收集（双码齐且航班号在场才参对——iata3 守卫在爬虫端，
            # 此处复核防测试夹具/历史行脏值入对）
            _dc = str(f.get("depAirportCode") or "").strip()
            _ac = str(f.get("arrAirportCode") or "").strip()
            if _dc or _ac:
                b["aptc"] += 1
            if (_code and _re.fullmatch(r"[A-Z]{3}", _dc)
                    and _re.fullmatch(r"[A-Z]{3}", _ac)):
                _ifp = (_code, str(f.get("depTime") or ""),
                        str(f.get("arrTime") or ""),
                        str(f.get("transCity") or ""),
                        str(f.get("arrDate") or ""))
                iata_x.setdefault(_ifp, {}).setdefault(
                    p.platform, set()).add((_dc, _ac))
        # 分池键含航线+日期、记当条记录行数：单平台键曾把
        # 大/小航线交错混池抬基线；且同平台多条记录时 b["n"] 是累计值，
        # 逐条 append 曾让历史序列变成递增累加数列（中位数基线失真）。
        # getattr 防御：测试夹具用极简 SimpleNamespace 无航线属性
        _k = (p.platform, getattr(p, "from_city", ""),
              getattr(p, "to_city", ""), getattr(p, "depart_date", ""))
        _ROW_HIST.setdefault(_k, []).append(n_rows)
        del _ROW_HIST[_k][:-8]
        if n_rows == 0:
            # 解析成 list 但全部行无 price：与 extra 空/解析败同属
            # 「有记录 0 行明细」形态，一并计入全空观测
            no_det[p.platform] = no_det.get(p.platform, 0) + 1
    # 键随日期累积清理：分池键含日期，长跑月级缓慢泄漏——
    # 当前轮不扫的 (航线,日期) 键 sweep 掉（基线 4 轮即重建，代价可忽略）
    _live = {(getattr(p, "from_city", ""), getattr(p, "to_city", ""),
              getattr(p, "depart_date", "")) for p in all_prices or []}
    for _k in [k for k in _ROW_HIST if (k[1], k[2], k[3]) not in _live]:
        del _ROW_HIST[_k]
    _xchan_ratio_map = _xchan_ratios(xchan)
    today = _dt.date.today().isoformat()
    # 供给基线扫描：本轮窗内某字段分子 >0 即「该渠道在该窗供给过此
    # 字段」（分子为正本身就证明真值载体在场，无需等比率门槛）——
    # 写入窗粒度基线；此后归零才构成「曾供给后断链」真警。分母键
    # 不入基线；bucket 键 stop_city 的告警键名是 stopcity（映射对齐）。
    # 新键落盘（重启不丢），既有键只刷新内存值。
    _BUCKET_WARN_KEY = {"stop_city": "stopcity"}
    _sup_new = False
    for plat, b in buckets.items():
        for k, v in b.items():
            if (isinstance(v, int) and v > 0
                    and k not in ("n", "direct_n", "trans_n", "stop_n")):
                _sk = (plat, _BUCKET_WARN_KEY.get(k, k),
                       _win[0], _win[1], _win[2])
                if _sk not in _SENT_SUPPLIED:
                    _sup_new = True
                _SENT_SUPPLIED[_sk] = today
    if _sup_new:
        _sent_save()
    # trans 行型供给标记（中转面供给哨）：中转行数>0 即该窗中转供给
    # 在场——此后「直飞满量而中转零行」构成行型断供真警（见告警循环）
    for plat, b in buckets.items():
        if b["trans_n"] > 0:
            _tsk = (plat, "trans", _win[0], _win[1], _win[2])
            if _tsk not in _SENT_SUPPLIED:
                _sup_new = True
            _SENT_SUPPLIED[_tsk] = today
    if _sup_new:
        _sent_save()

    # 行为型哨（告警对象是「行为」不是「字段供给」，分子无供给语义）：
    # 不经供给基线门——rowfall 行数塌方/median 指纹中位比/noDet 明细
    # 全空/rowlow 行数低位恒零分子，入基线判定=永久静默误杀
    _BEHAVIOR_FIELDS = {"rowfall", "median", "noDet", "rowlow"}

    def _warn(key, msg, *args):
        # 窗键控 + 窗粒度供给基线门（必须前置）：字段/行型哨的去重与
        # 连击键升到与供给基线同粒度 (plat,fld,fc,tc,date)——共享平键
        # 的同日「今日已报」短路曾吞掉次窗断供首鸣（同渠道多窗断供
        # 只有首窗鸣实录），连日升级亦被跨窗共享摊薄。never-supplied
        # 特征静默：窗键下本窗留痕只能在供给后产生（供给门在留痕写点
        # 之前），无源窗键永无留痕可摘——旧共享键时代的摘除机械退役，
        # pop 他窗互扰随之结构性消失；行为型哨（跨窗聚合量）与 iata
        # 分歧保持平键。
        if key[1] not in _BEHAVIOR_FIELDS and key[0] != "iata":
            key = (key[0], key[1], _win[0], _win[1], _win[2])
            if key not in _SENT_SUPPLIED:
                return
        if _SENT_LAST.get(key) == today:
            return
        # 连续命中计数：昨日也命中则 +1、断档归零——结构性
        # 无源字段连续第 3 天起降为 INFO（如实催修但不再淹没真告警），
        # 恢复后自动重置、重新从 WARNING 起报；窗键下按窗独立累计
        yest = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        cnt = _SENT_CNT.get(key, 0) + 1 if _SENT_LAST.get(key) == yest else 1
        _SENT_CNT[key] = cnt
        _SENT_LAST[key] = today
        _sent_save()
        if len(key) == 5:
            # 词面自带窗辨识：读者不复算即知哪一窗断供
            msg = msg + "（窗 %s→%s %s）"
            args = args + (_win[0], _win[1], _win[2])
        if cnt >= 3:
            logger.info("[解析哨兵][连续%d日] " + msg, cnt, *args)
        else:
            logger.warning("[解析哨兵] " + msg, *args)

    def _sent_retire(plat, k):
        """观测面豁免/死键退役的存量留痕摘除：退役后 _warn 永不被调，
        留痕悬挂成陈旧状态（ctrip|page 豁免后假火一日留痕悬挂实录）。
        摘除面=同 (plat,k) 全族（窗键 5 元 + 旧平键 2 元一并清）。幂等：
        无留痕零操作。"""
        _dead = [kk for kk in _SENT_LAST if kk[0] == plat and kk[1] == k]
        if _dead:
            for kk in _dead:
                _SENT_LAST.pop(kk, None)
                _SENT_CNT.pop(kk, None)
            _sent_save()

    for plat, b in buckets.items():
        # 门槛 50→20：tongcheng 48 行 / fliggy ~33 / tuniu ~26 量级的
        # 小渠道当轮曾全部逃逸哨兵（tuniu 舱位解析死透数日无报警实锤）；
        # 20 行下 2/20=10% 即不触发，小样本偶发波动不会误报。
        # 再收 20→10：tuniu 现役 ~12 行仍处 10-19 行死区
        # （三条门槛全不命中=观测失明）；10 行下 0/10=0% 才触发，
        # 零命中是强信号不致误报
        if b["n"] >= 10:
            for k in ("apt", "aptc"):
                if (plat, k) in _SENT_DEAD_KEYS:
                    _sent_retire(plat, k)   # 结构性无源（死键表）：观测即假火
                    continue
                if b[k] / b["n"] < 0.10:
                    # 词面经 %s 参数传入（_sent_hit_text 产物含裸 %，
                    # 直接拼 msg 会被 _warn 的 [连续%d日] 分支二次格式化
                    # 触发 TypeError——消息整条丢失，Soldier P1-1）
                    _warn((plat, k), "%s",
                          _sent_hit_text(plat, k, b[k], b["n"]))
            # 直飞行群比率观测（单件行属性：cabin/meal/prate/plane/
            # psize/discount）：分母=直飞行数，门槛同步平移——样本
            # 不足的本轮不观测（行群观测的样本就是行群自身，全行
            # 分母曾稀释出降级轮六键齐鸣假火）
            if b["direct_n"] >= 10:
                for k in ("cabin", "meal", "prate", "plane", "psize",
                          "discount"):
                    if (plat, k) in _SENT_DEAD_KEYS:
                        _sent_retire(plat, k)   # 死键表同上
                        continue   # 结构性无源（死键表）：观测即假火
                    if b[k] / b["direct_n"] < 0.10:
                        _warn((plat, k), "%s",
                              _sent_hit_text(plat, k, b[k], b["direct_n"]))
            # 单件行属性四键（准点/取消/廊桥/机龄）分母随分子同步
            # 直飞行群：这四字段只挂直飞行（中转组合体结构性无源），
            # 直飞售罄清空的降级夜全行分母（n≥20 条中转行）撞分子
            # 恒 0 曾齐鸣「键名失效」假火（dump 与 DB 双证解析链健康
            # 的轮被错误归因）——分母改 direct_n、门槛 10（同直飞行
            # 群比率观测族），直飞行群在场时键死照报、售罄夜静默。
            _DIRECT_ONLY = ("avgd", "cancel", "bridge", "page")
            for k in ("share", "few", "term", "svc", "avgd", "lft", "tterm",
                      "cancel", "bridge", "page", "ccode"):
                if (plat, k) not in _SENT_FIELD_SOURCES:
                    _sent_retire(plat, k)   # 无源渠道退役：留痕同轮摘
                    continue   # 无源渠道不观测（同死键表逻辑）
                # svc/tterm 分母门槛（/52）：transferService/
                # transTerminal 只挂中转行，DB 实测同程中转记录仅 7.3%
                # ——86% 轮次 n≥20 而 svc 恒 0 命中=结构性每日假火（真
                # 供给侧稀疏非键死），复用 layover 的 trans_n≥20 门槛；
                # 中转解析整体死亡由行数哨兵兜底
                if k in ("svc", "tterm") and b["trans_n"] < 20:
                    continue
                # 恒 0 才算死：共享/余票/航站楼覆盖率随航线
                # 波动（DB 实测 20-40%），比率阈值会误报——0 命中才是
                # 键名失效信号（tx→td 事故形态），样本门槛防小样本
                # （全行批 20/直飞行群批 10，与各自比率观测族对齐）
                _donly = k in _DIRECT_ONLY
                _denom = b["direct_n"] if _donly else b["n"]
                if b[k] == 0 and _denom >= (10 if _donly else 20):
                    _warn((plat, k), "%s 决策字段 %s 命中 0/%d（键名失效/"
                           "渠道改版，或本航线天然无此属性——共享/航站楼"
                           "覆盖率随 OD 波动，连日恒 0 才需寻源）",
                           plat, {"share": "shareCarrier",
                                  "few": "fewTicket",
                                  "term": "depTerminal",
                                  "svc": "transferService",
                                  "avgd": "avgDelay",
                                  "lft": "leftTickets",
                                  "tterm": "transTerminal",
                                  "cancel": "cancelRate",
                                  "bridge": "bridgeRate",
                                  "page": "planeAge",
                                  "ccode": "cabinCode"}[k], _denom)
            # 分母=中转行：transferBaggage 只挂中转行，全行
            # 分母曾让直飞占比高的渠道该指标数学上近乎恒真（温度计失真）。
            # 门槛 10=与全行哨对齐（小渠道逃逸判例 50→20→10 同族）：
            # 50 门槛下四渠道集体失明（fliggy 单轮中转行 max 16、
            # 14 天 1499 轮 ≥50 轮数=0；tongcheng ≥50 轮全停在量级
            # 回落前）——有出勤的不火、零出勤的不达门槛永不评估
            if b["trans_n"] >= 10 and b["bag_direct"] / b["trans_n"] < 0.01:
                _warn((plat, "bag_direct"), "%s 行李直挂命中 %d/%d 中转行"
                       "（<1%%：直挂筛选的中转达标告警实质近空，寻源待修）",
                       plat, b["bag_direct"], b["trans_n"])
        if b["trans_n"] >= 20 and b["layover"] / b["trans_n"] < 0.10:
            _warn((plat, "layover"), "%s 中转停留覆盖 %d/%d（<10%%："
                   "衔接时长供给单点化，ctrip 补全链若断全链静默归零）",
                   plat, b["layover"], b["trans_n"])
        # 中转面行型供给哨：直飞行群满量而中转零行——查询粒度合计
        # （zrow/qsup/rowfall）对「行型断供」失明（tongcheng conn 中转
        # 壳断供 10 天直飞 99.6% 满勤三面全静默实录）。供给基线门同
        # 字段哨：该窗曾有中转行后归零才警，窗口诞生起无中转供给静默
        # （天然无中转航线，卅二§1 同律）
        if b["direct_n"] >= 20 and b["trans_n"] == 0 and (
                (plat, "trans", _win[0], _win[1], _win[2])
                in _SENT_SUPPLIED):
            _warn((plat, "trans"), "%s 直飞行群 %d 满量而中转零行（该窗"
                   "历史曾有中转供给——行型断供，渠道中转接口/壳改版"
                   "嫌疑，dump 取证核对）", plat, b["direct_n"])
        # 经停城市覆盖：≥5 经停行且城市覆盖 <10%——「经停」
        # 徽标无地点，「停哪/停多久」无从决策
        if b["stop_n"] >= 5 and b["stop_city"] / b["stop_n"] < 0.10:
            _warn((plat, "stopcity"), "%s 经停城市覆盖 %d/%d（<10%%：经停"
                   "徽标无地点，停哪无从决策）",
                   plat, b["stop_city"], b["stop_n"])
        # 行数塌方按 (平台,航线,日期) 分池判：基线取同池近轮
        # 中位数——单平台混池键曾让大/小航线交错抓取时基线失真
        for _hk, hist in _ROW_HIST.items():
            if _hk[0] != plat:
                continue
            if len(hist) >= 4:
                base = sorted(hist[:-2])[len(hist[:-2]) // 2]
                # base≥2（c330 F2 自 10 收至数学下限：门槛 ≥10 时薄渠道
                # 每池基线 2 行数学上永不评估——tongcheng 供数塌方 95%
                # 三面全静默实录；<2 时 30% 线无整数命中无从谈塌方，
                # 基线 1→0 归查询面/全断哨领地。塌方线 30% 与连 2 轮
                # 持续性门槛不变，单轮偶发零误杀纪律在薄渠道同成立）
                if base >= 2 and hist[-1] < base * 0.3 and hist[-2] < base * 0.3:
                    _warn((plat, "rowfall"), "%s 行数塌方 %d/%d（近轮中位数"
                           "的 <30%% 连续 2 轮：有响应但明细骤减）",
                           plat, hist[-1], base)
        # 渠道指纹中位比：本渠道样本 ≥20 才判，p50 <0.9 或
        # >1.1 即渠道报价口径系统性漂移（非单行毒价——那是 alerter
        # 0.5x 孤低价守卫的辖区）
        _plat_rs = _xchan_ratio_map.get(plat) or []
        if len(_plat_rs) >= 20:
            _rs_sorted = sorted(_plat_rs)
            _p50 = _rs_sorted[len(_rs_sorted) // 2]
            if _p50 < 0.9 or _p50 > 1.1:
                _warn((plat, "median"), "%s 同指纹组中位比 p50=%.2f（n=%d，"
                       "<0.9/>1.1：渠道报价口径系统性漂移，非单行毒价）",
                       plat, _p50, len(_plat_rs))

    # 渠道明细全空：≥2 条记录解析后 0 行——「有记录但 0 行
    # 明细」形态对字段/塌方/脉冲三面隐形（仅 qunar 有拒落价守卫）；1 条
    # 空记录是常态波动不入报。独立于 buckets 循环：extra 全空的渠道
    # 根本不会建桶，放进桶循环=对最该报的形态失明
    for plat, cnt in no_det.items():
        if cnt >= 2:
            _warn((plat, "noDet"), "%s 本轮 %d 条记录明细 0 行（extra 空/"
                   "解析败/无价行）", plat, cnt)

    # 跨渠道 IATA 码对分歧：同航班号同指纹任两渠道 (dep,arr)
    # 码对集合不一致即分歧——DB 全库 293 组合级配对 d=0 纯净基线定证的
    # 零容忍告警面（码解析错=出票机场与展示不符的决策性错误，宁严勿松）。
    # DB 原始行天然 pre-propagate（_propagate_fields 只改推送期副本不
    # 落库），跨渠道补全不会掩盖分歧
    _div_n = 0
    _div_eg = ""
    for _ifp, per in iata_x.items():
        _ps = list(per)
        for _i in range(len(_ps)):
            for _j in range(_i + 1, len(_ps)):
                if per[_ps[_i]] != per[_ps[_j]]:
                    _div_n += 1
                    if not _div_eg:
                        _pi = sorted(per[_ps[_i]])[0]
                        _pj = sorted(per[_ps[_j]])[0]
                        _div_eg = "%s %s:%s/%s≠%s:%s/%s" % (
                            _ifp[0], _ps[_i], _pi[0], _pi[1],
                            _ps[_j], _pj[0], _pj[1])
    if _div_n:
        _warn(("iata", "div"), "跨渠道 IATA 码对分歧 %d 组（示例 %s——某"
               "渠道码解析错或渠道下发异码，出票机场恐与展示不符）",
               _div_n, _div_eg)

    # 行数绝对下限：塌方哨兵 base≥20 门槛下，小渠道长期低位
    # （tuniu 1-7 行实况）成了自己的基线永不触发——同查询其他渠道
    # 中位 ≥30 而本渠道 <10 连续 2 轮仍要响
    _low_cur = {}
    for (pk, fck, tck, dtk), hist in _ROW_HIST.items():
        if len(hist) >= 2:
            _low_cur.setdefault((fck, tck, dtk), {})[pk] = (hist[-1], hist[-2])
    for (fck, tck, dtk), per in _low_cur.items():
        for pk, (v1, v2) in per.items():
            if v1 >= 10 or v2 >= 10:
                continue
            oth = sorted(o1 for pk2, (o1, _o2) in per.items() if pk2 != pk)
            if oth and oth[len(oth) // 2] >= 30:
                _warn((pk, "rowlow"), "%s 行数 %d 连续低位（同查询其他渠道"
                       "中位 %d：渠道侧明细骤减或解析半瘫，基线低于塌方"
                       "门槛故单列观测）", pk, v1, oth[len(oth) // 2])
    # 过期窗键留痕 sweep（r336 Soldier m3 卫生债随迁，_ROW_HIST 键
    # sweep 同族）：键内嵌出发日期早于今天的告警留痕永不再命中（窗
    # 已过期跳采），长跑月级缓慢泄漏。平键（行为型哨/zrow/qsup，无
    # 日期维度）与 _SENT_SUPPLIED 供给基线（r334 案③持久化「曾供给」
    # 记忆，化石窗由「未过期窗」枚举语义处置）不在清理域。
    import datetime as _dt
    _today_s = _dt.date.today().isoformat()
    # 形态门：k[4] 须为 10 位日期串才参与过期比较——空串（夹具/异常
    # 形态的无窗键）与短串不是日期，「空 < today」恒真曾误清同日
    # 已报留痕（全量红当场抓获）
    for _sk in [k for k in _SENT_LAST
                if len(k) == 5 and len(k[4]) == 10 and k[4] < _today_s]:
        _SENT_LAST.pop(_sk, None)
        _SENT_CNT.pop(_sk, None)


_sent_load()


def make_sweep_job(cfg, rt, logger, storage, charts_fn):
    """构造一轮全量扫描：航线去重 → 逐查询错峰采集 → 分发给订阅用户。

    rt 为运行时容器（dict）：users/alerters/cfg 均可被 web 配置热重载替换，
    每轮扫描开始时取最新值。cfg 形参只是热重载前的初始快照——扫描期一律读
    rt["cfg"]（reload_config 会同步更新），否则爬虫超时/错峰/日报时刻/图床
    等配置在首次热重载后仍沿用启动快照。去哪儿接口 ~5 分钟全局限流（与航线
    无关），每个 (航线, 日期) 查询之间错峰等待。"""
    import threading
    # 进程级互斥：启动首轮 / 定时调度 / 网页手动触发统一防并发
    # （曾因"启动即扫 + /api/run"双跑导致每渠道抓两次、每消息推两条）
    _sweep_lock = threading.Lock()
    # 节流/熔断上下文（1–5 区）：与进程同寿命——熔断状态跨轮保留，
    # 热重载只换阈值不丢"这家现在不能碰"的既成事实
    rt["pacing"] = Pacing(cfg)
    # 重启续 TTL：库里有真实明细就当作刚采过，避免每次重启/调试都把
    # 全部查询重新打一遍（这是"反复跑数据"最常见的限流来源）。
    try:
        _seeded = 0
        for _r in (storage.latest_prices(24 * 7) or []):
            if rt["pacing"].seed_fetch(
                    _r.get("platform"),
                    (_r.get("from_city"), _r.get("to_city"),
                     _r.get("depart_date")),
                    _r.get("price"), parse_local_ts(_r.get("fetched_at"))):
                _seeded += 1
        if _seeded:
            logger.info("[节流] 从库续上 %d 条明细 TTL 基线（重启不重打全量）",
                        _seeded)
    except Exception as _se:
        logger.warning("[节流] TTL 基线续读失败（按无历史启动）: %s", _se)
    # 案发现场（每渠道最近一次被拦的时间/URL/证据 + 验证后探测结果）
    rt["scene"] = {}
    # 每轮只给每个渠道做一次起跑错峰（并发同渠道不重复睡）
    _stagger_todo = set()
    _stagger_lock = threading.Lock()
    # 每轮每个渠道只预热一次（首页 cookie 拿到即可，多发无益）
    _warm_todo = set()
    _warm_lock = threading.Lock()
    # 特价监控轮次计数（r319）：每 N 轮跑一次发现，节流语义见 special_due
    _special_round_no = [0]

    # ---------- 特价监控（r319）：双源发现 → 跨渠道核实 → 推送 ----------
    def _specials_for_user(ui, u, watch, today):
        """单用户单轮：发现（途牛榜单+携程日历，纯 httpx 轻请求）→
        新低候选 → 现役爬虫跨渠道核实（以核实价为推送口径）→ 通知。
        u 由调用方直传（Soldier P3#5：热重载整体替换 rt["users"] 后
        按索引重取会与 watch 张冠李戴）。发现层失败静默降级（返回
        None/空表即本轮无源），绝不炸主扫描。"""
        import datetime as _dt
        import random as _random
        from core.specials import (SRC_CTRIP, SRC_CTRIP_BD, SRC_FLIGGY,
                                   SRC_TUNIU, build_special_push,
                                   ctrip_calendar_deals,
                                   deals_from_ctrip_board,
                                   deals_from_fliggy_board,
                                   deals_from_tuniu, pair_ctrip_returns,
                                   select_for_verify, should_push,
                                   special_key, verify_verdict)
        from crawlers import special as _special_net
        # 本地代理（crawler.proxy，如 Clash http://127.0.0.1:7897）：
        # 发现层出口走它——tuniu 榜单城市跟随出口 IP，换出口=换城市看榜
        _proxy = str(((rt.get("cfg") or {}).get("crawler") or {})
                     .get("proxy", "") or "").strip()
        deals = []
        if SRC_TUNIU in (watch.platforms or []):
            payload = _special_net.fetch_tuniu_board(logger, proxy=_proxy)
            if payload:
                got = deals_from_tuniu(payload, watch, today)
                if got:
                    logger.info("[特价] tuniu 榜单候选 %d 条", len(got))
                deals += got
        if SRC_CTRIP_BD in (watch.platforms or []):
            # 特价搜索榜（r319f PC 变体）：一请求得全中国多目的地低价
            # （223 路线/446 价格点，出发地可控实证），补日历池外全网面
            _bd_end = (today + _dt.timedelta(days=min(watch.days, 30))
                       ).isoformat()
            payload = _special_net.fetch_ctrip_board(
                watch.from_code, watch.from_name, today.isoformat(),
                _bd_end, logger, proxy=_proxy)
            if payload:
                got = deals_from_ctrip_board(payload, watch, today)
                if got:
                    logger.info("[特价] ctrip 搜索榜候选 %d 条", len(got))
                deals += got
        if SRC_FLIGGY in (watch.platforms or []):
            # 飞猪 PC 榜（r319f）：免签名 GET JSONP，18 条/请求价格升序；
            # 窗实证 3/7 天形态，取 min(days,7) 与实证对齐
            payload = _special_net.fetch_fliggy_board(
                watch.from_code, today.isoformat(),
                (today + _dt.timedelta(days=min(watch.days, 7))
                 ).isoformat(), logger, proxy=_proxy)
            if payload:
                got = deals_from_fliggy_board(payload, watch, today)
                if got:
                    logger.info("[特价] fliggy 榜候选 %d 条", len(got))
                deals += got
        if SRC_CTRIP in (watch.platforms or []):
            hits = {}   # dest → (name, deals)：正向有候选才拉反向配返程
            for code, name in watch.effective_pool():
                payload = _special_net.fetch_ctrip_calendar(
                    watch.from_code, code, today.isoformat(), logger,
                    proxy=_proxy)
                if payload:
                    got = ctrip_calendar_deals(payload, watch.from_code,
                                               code, name, watch, today)
                    if got:
                        hits[code] = (name, got)
                time.sleep(_random.uniform(2.0, 3.0))   # 日历请求错峰
            for code, (name, got) in hits.items():
                if watch.round_trip:
                    rpayload = _special_net.fetch_ctrip_calendar(
                        code, watch.from_code, today.isoformat(), logger,
                        proxy=_proxy)
                    if rpayload:
                        rdeals = ctrip_calendar_deals(
                            rpayload, code, watch.from_code,
                            watch.from_name, watch, today,
                            days=watch.days + watch.round_trip_days)
                        pair_ctrip_returns(got, rdeals, watch)
                    time.sleep(_random.uniform(2.0, 3.0))
                deals += got
            if hits:
                logger.info("[特价] ctrip 日历候选 %d 城地 %d 条", len(hits),
                            sum(len(v[1]) for v in hits.values()))
        if not deals:
            return
        drop_min = float(((u.get("notifier") or {}).get(
            "push_drop_min", 30)) or 30)

        def _pushed(k):
            return storage.get_alert_state("special|" + k)

        # 核实未过负缓存（Soldier P2#2）：drop/retry 不落 pushed 态，
        # 坏候选会每轮重占 cap=3 预算饿死新候选——按日戳记
        # specialfail| 键，当日跳过、次日自然重试（alert_state 恒存
        # 体量可控：键数=出过候选的 OD+日期数）
        import datetime as _dtf
        _stamp = float(_dtf.date.today().strftime("%Y%m%d"))

        def _blocked(k):
            try:
                return storage.get_alert_state("specialfail|" + k) == _stamp
            except Exception:
                return False

        cands = select_for_verify(deals, _pushed, cap=3, drop_min=drop_min,
                                  blocked=_blocked)
        if not cands:
            return
        # 核实渠道=用户平台集去掉 qunar：minPrice 每请求重摇（~11% 幻影
        # 低价）会污染核实 min（比真实还低的价→放行虚价）；全局限流也
        # 不适合按需核实。其余渠道照常（tuniu 现役 listFlight 断供时
        # safe_fetch 空表，天然退出核实池）。
        plats = set(u.get("platforms") or []) - {"qunar"}
        crawlers = get_crawlers(plats) if plats else []
        verified = []
        for d in cands:
            prices = []
            for c in crawlers:
                with channel_slot(c.name):
                    rows = c.safe_fetch(d.from_code, d.to_code,
                                        [d.date]) or []
                prices += [p.price for p in rows if p.price]
            action, val = verify_verdict(
                min(prices) if prices else None, d.src_price,
                watch.max_price)
            if action != "push":
                storage.set_alert_state("specialfail|" + special_key(d),
                                        _stamp)
                logger.info("[特价] %s→%s %s 核实未过（%s，源价￥%.0f），"
                            "当日冷却次日重试",
                            d.from_code, d.to_code, d.date, val, d.src_price)
                continue
            if not should_push(val, _pushed(special_key(d)), drop_min):
                continue
            verified.append((d, val))
        if not verified:
            return
        # 核实留痕（r320）：控制台概览「特价雷达」卡数据源——核实通过
        # 即记，与推送正交（免打扰/无通道形态控制台仍可见）
        for d, val in verified:
            try:
                storage.save_special_deal(d.src, d.from_code, d.to_code,
                                          d.date, float(val), d.src_price,
                                          d.ret_date, d.ret_price)
            except Exception as e:
                logger.warning("[特价] 留痕失败: %s", e)
        alerters_now = rt["alerters"] or []
        if ui >= len(alerters_now):
            return
        a = alerters_now[ui]
        title, desp = build_special_push(watch, verified)
        try:
            quiet = a._in_quiet()
        except Exception:
            quiet = False
        if quiet:
            # 免打扰不推送也不记已推——下轮自然重推（去抖状态未落）
            logger.info("[特价] 免打扰时段，%d 条顺延下轮", len(verified))
            return
        if a.notifier:
            # 消毒单源出口（八§1）：特价文案拼渠道自由词面
            # （discount/airline），与 alerter 全部 send 同守卫不留绕行口
            a.notifier.send(sanitize_desp(title), sanitize_desp(desp))
        for d, val in verified:
            storage.set_alert_state("special|" + special_key(d), float(val))
        logger.info("[特价] 已推送 %d 条：%s", len(verified), "；".join(
            f"{d.from_code}→{d.to_code} {d.date} ￥{val:.0f}({d.src})"
            for d, val in verified))

    def _specials_round():
        """扫描轮尾跑特价监控：轮次节流（每 N 轮）+配置保存即触发
        （rt["special_force"] 由 reload_config 置位）。无订阅用户零开销。"""
        from core.specials import parse_specials, special_due
        _special_round_no[0] += 1
        import datetime as _dt
        today = _dt.date.today()
        # force 在轮首弹出（Soldier P3#12）：本轮执行中（44 城×2-3s，
        # 最坏十来分钟）再次保存配置置位的 force 留给下轮立跑，不被吞
        force = bool(rt.pop("special_force", False))
        try:
            for ui, u in enumerate(rt["users"] or []):
                for watch in parse_specials(u.get("specials"), today):
                    if not special_due(_special_round_no[0],
                                       watch.interval_rounds, force):
                        continue
                    try:
                        _specials_for_user(ui, u, watch, today)
                    except Exception as e:
                        logger.warning("[特价] 用户 %s 本轮异常: %s",
                                       u.get("name"), e)
        except Exception as e:
            logger.warning("[特价] 轮编排异常: %s", e)


    # 平台实例：按「平台集合」缓存（去哪儿实例的 token/浏览器会话复用）
    crawler_cache = {}
    from threading import RLock
    crawler_cache_lock = RLock()
    session_root = _anchored((cfg.get("crawler") or {}).get("user_data_dir"),
                             "user_data")
    # 热改无头模式后清缓存，下轮按新配置重建浏览器实例
    def clear_crawlers(platform=None):
        with crawler_cache_lock:
            for key in list(crawler_cache):
                if platform is None or platform in key:
                    del crawler_cache[key]
    rt["clear_crawlers"] = clear_crawlers

    def get_crawlers(platforms):
        key = tuple(sorted(set(platforms)))
        with crawler_cache_lock:
            if key not in crawler_cache:
                _full = rt.get("cfg") or cfg
                crawler_cfg = dict(_full.get("crawler", {}))
                crawler_cfg["user_data_dir"] = session_root
                # App 渠道读的是顶层 android: 段（不属于 crawler），
                # 且要能区分「没配」与「配了但关闭」——所以整段落进去，
                # 由 core.android.config.normalize 判 enabled。
                crawler_cfg["android"] = _full.get("android") or {}
                insts = []
                for name in key:
                    cls = REGISTRY.get(name)
                    if cls:
                        insts.append(cls(crawler_cfg, logger))
                crawler_cache[key] = insts
            return crawler_cache[key]

    # 干预闸门锁（r481）：三处「同渠道只允许一次」的占位都必须在锁内
    # 完成「判断 + 置位」，否则 ThreadingHTTPServer 的并发请求会让双方
    # 都通过判断（负控实测：插入让出点即开出两个验证窗）。
    _WARM_LOCK = threading.Lock()
    _VERIFY_LOCK = threading.Lock()

    def warm_channel(platform):
        """手动预热（可干预入口）：拿实例 → 持 channel_slot → 打一次首页。

        与自动预热共用同一把渠道锁，人工干预不会与采集抢同一会话。

        幂等（r480）：同一渠道已在预热时直接拒绝。前端 PACE_BUSY 只挡
        同一页面上的连点，挡不住第二个标签页/直接调接口——而重复预热
        是本系统里最没价值又最伤风控的动作（既叠加指纹，又把成功率打低）。

        原子性（r481）：闸门必须是「判断 + 置位」在锁内一步完成。
        先独立判断再置位的话，两个标签页同时点会让双方都通过判断
        （ThreadingHTTPServer 是并发处理请求的）——负控实测：在判断与
        置位之间插入一个让出点即可开出**两个**窗口。
        """
        _wg = rt.setdefault("warm_open", {})
        with _WARM_LOCK:
            if _wg.get(platform):
                return {"ok": False, "dup": True,
                        "err": "该渠道正在预热，等这次结束再看结果"}
            _wg[platform] = True
        try:
            try:
                insts = get_crawlers([platform])
            except Exception as e:
                return {"ok": False, "err": str(e)[:120]}
            if not insts:
                return {"ok": False, "err": "未知渠道: %s" % platform}
            c = insts[0]
            url = str(getattr(c, "warmup_url", "") or "").strip()
            if not url:
                return {"ok": False,
                        "err": "%s 无独立预热入口（内部自带或不需要）" % platform}
            try:
                with channel_slot(c.name):
                    ok = c.warmup()
            except Exception as e:
                return {"ok": False, "err": str(e)[:120]}
            try:
                if rt.get("pacing") is not None:
                    rt["pacing"].record(platform)
                storage.save_intervention(
                    platform, "warmup", ok=bool(ok), scope="",
                    note="%s 风控 cookie %s" % (
                        url, ",".join(getattr(c, "warmup_cookies", []) or [])
                        or "无"))
            except Exception:
                pass
            return {"ok": bool(ok), "platform": platform, "url": url}
        finally:
            # 任何 return 路径都要放行：占位在锁内完成，释放也必须无条件，
            # 否则一次「没有预热入口」就会把该渠道永久锁死。
            with _WARM_LOCK:
                _wg.pop(platform, None)

    rt["warm_channel"] = warm_channel

    def _probe_channel(c, scene):
        """验证后单查探测：只打一条已知查询，验证「真的通了」。"""
        q = (scene or {}).get("query") or list(
            getattr(c, "last_query", ()) or ())
        if not q:
            # 没有查询记录也要持渠道锁：预热同样会开浏览器，不能和采集
            # 抢同一 profile。
            with channel_slot(c.name):
                ok = c.warmup()
                if rt.get("pacing") is not None:
                    rt["pacing"].record(c.name)
            return bool(ok), 0, "无查询记录，仅预热"
        try:
            fc, tc, d = q[0], q[1], q[2]
        except (IndexError, TypeError):
            return False, 0, "查询记录不完整"
        try:
            with channel_slot(c.name):
                prices = c.safe_fetch(fc, tc, [d])
                if rt.get("pacing") is not None:
                    rt["pacing"].record(c.name)
        except Exception as e:
            return False, 0, str(e)[:120]
        return bool(prices), len(prices), ""

    def _refetch_failed(platform, limit=8):
        """验证通过后补采本轮失败的查询（最多 8 条，避免变成第二轮全量）。

        只负责「把缺的数据补回来并落库」；告警仍走下一轮聚合，
        避免同一条降价因为补采被推两遍。
        """
        qs = sorted((rt.get("failed") or {}).get(platform) or [])[:limit]
        if not qs:
            return {"n": 0, "rows": 0}
        try:
            insts = get_crawlers([platform])
        except Exception as e:
            return {"n": 0, "rows": 0, "err": str(e)[:80]}
        if not insts:
            return {"n": 0, "rows": 0, "err": "未知渠道"}
        c = insts[0]
        got = []
        for _i, (fc, tc, d) in enumerate(qs):
            _attempt = "refill-%s-%d-%d" % (platform, int(time.time() * 1000),
                                            _i)
            try:
                _one = []
                with channel_slot(c.name):
                    _one = c.safe_fetch(fc, tc, [d]) or []
                    got.extend(_one)
                    if rt.get("pacing") is not None:
                        rt["pacing"].record(platform)
                # 补采出数 = 这条链路已恢复：复位熔断并刷新该键 TTL，
                # 否则"补采成功"之后下一轮仍按旧的冷却/劣化处理。
                if _one and rt.get("pacing") is not None:
                    try:
                        rt["pacing"].reset(platform)
                        rt["pacing"].note_fetch(
                            platform, (fc, tc, d),
                            min(p.price for p in _one), True)
                    except (AttributeError, TypeError, ValueError):
                        pass
                # 补采也是真实采集：路径账要记，否则「验证后恢复了」
                # 在统计里看不到，下一轮还会拿旧失败率继续罚该渠道。
                for _rec in (getattr(c, "paths", None) or []):
                    try:
                        storage.save_fetch_path(
                            platform, fc, tc, d, _rec.get("path", ""),
                            _rec.get("status", ""),
                            rows=_rec.get("rows", 0),
                            note=_rec.get("detail", ""),
                            evidence_level="refill",
                            attempt_id=_attempt,
                            request_url=str(_rec.get("url") or ""),
                            http_status=int(_rec.get("http") or 0))
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("[补采] %s %s→%s %s 未完成: %s",
                               platform, fc, tc, d, e)
        if got:
            try:
                storage.save_many(got)
                for _k in {(p.from_city, p.to_city, p.depart_date)
                           for p in got}:
                    try:
                        storage.refresh_daily(*_k)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("[补采] 落库失败: %s", e)
        logger.info("[补采] %s 补采 %d 条查询，落库 %d 条",
                    platform, len(qs), len(got))
        return {"n": len(qs), "rows": len(got)}

    rt["refetch_failed"] = _refetch_failed

    def verify_channel(platform):
        """现场 + 弹出验证窗口（可干预）：用**采集同一份 profile** 打开
        被拒地址，人工过验证后 cookie 直接落进采集档案，下一轮生效。

        关窗即视为「人认为搞定了」：自动解除冷却 + 单查探测，把
        「验证有没有用」当场告诉人，而不是等下轮再猜。

        幂等（r480）：同一渠道已有验证窗在开时直接拒绝。旧实现无守卫，
        第二次请求的线程会先卡在 channel_slot 上，等第一个窗口关掉后
        **再弹一个窗**——人刚做完验证，屏幕上又冒出一个同样的页面，
        而且第二次的 done 事件无人触发，窗口只能靠 900s 超时收场。
        """
        _ving = rt.setdefault("verify_open", {})
        # 原子性（r481）：判断与置位必须在同一把锁内。分两步做时，两个
        # 标签页同时点会让双方都通过判断——负控实测：在两者之间插入一个
        # 让出点即开出两个窗口，且第二个窗的 done 事件无人触发。
        with _VERIFY_LOCK:
            if _ving.get(platform):
                return {"ok": False, "dup": True,
                        "err": "该渠道的验证窗口已经开着——完成验证后直接关窗，"
                               "系统会自动解除冷却并单查探测"}
            _ving[platform] = True
        # 预检失败要在锁内回滚：占位已在锁内完成，任何提前返回都必须撤销，
        # 否则该渠道再也打不开验证窗口。
        _resolved = False
        try:
            try:
                insts = get_crawlers([platform])
            except Exception:
                insts = []
            if not insts:
                return {"ok": False, "err": "未知渠道: %s" % platform}
            c = insts[0]
            scene = (rt.get("scene") or {}).get(platform) or {}
            url = (scene.get("url") or getattr(c, "last_block_url", "")
                   or getattr(c, "warmup_url", "") or c.login_url() or "")
            if not url:
                return {"ok": False, "err": "无法确定要打开的地址"}
            _resolved = True
        except Exception as e:
            return {"ok": False, "err": str(e)[:120]}
        finally:
            if not _resolved:
                with _VERIFY_LOCK:
                    _ving.pop(platform, None)

        done = threading.Event()

        def _run():
            _t0 = time.time()
            bak = c.use_mobile
            try:
                # 与采集共用渠道锁：验证窗口开的是采集同一份 profile，
                # 不持锁会和正在跑的采集抢浏览器（SessionBusy）或让
                # 两份不同指纹的上下文同时指向同一个档案。
                try:
                    if isinstance(scene.get("mobile"), bool):
                        c.use_mobile = scene["mobile"]
                    with channel_slot(c.name):
                        c.open_challenge_window(url, done, timeout_s=900)
                except Exception as e:
                    logger.warning("[验证] %s 窗口异常: %s", platform, e)
                    return
                finally:
                    c.use_mobile = bak
                # 关窗 = 人完成了验证：立刻解除冷却并探测一次
                try:
                    if rt.get("pacing") is not None:
                        rt["pacing"].reset(platform)
                except Exception:
                    pass
                try:
                    if isinstance(scene.get("mobile"), bool):
                        c.use_mobile = scene["mobile"]
                    ok, rows, note = _probe_channel(c, scene)
                finally:
                    c.use_mobile = bak
                # 验证没通过就重新竖起熔断：先 reset 是为了让探测能打出去；
                # 探测仍被拦时若保持 reset，渠道会显示"已恢复"并在下一轮
                # 立刻再撞一次——这是把"验证失败"伪装成"已修复"。
                if not ok and rt.get("pacing") is not None:
                    try:
                        _st = [x.get("status") for x in
                               (getattr(c, "paths", None) or [])]
                        _note = " ".join(
                            str(x.get("detail") or "") for x in
                            (getattr(c, "paths", None) or [])
                            if x.get("status") not in ("ok", "calendar", "empty"))
                        _kind, _cd = rt["pacing"].observe(
                            platform, _st, _note,
                            retry_after=int(
                                getattr(c, "retry_after_s", 0) or 0))
                        if _kind:
                            rt["scene"].setdefault(platform, {})["retripped"] = {
                                "kind": _kind, "cooldown_s": int(_cd)}
                            logger.warning(
                                "[验证] %s 未通过，重新熔断 %ds（%s）",
                                platform, _cd, _kind)
                    except Exception as _re:
                        logger.warning("[验证] %s 重新熔断失败: %s",
                                       platform, _re)
                refill = _refetch_failed(platform) if ok else {"n": 0,
                                                              "rows": 0}
                rt["scene"].setdefault(platform, {})["verify"] = {
                    "at": time.strftime("%H:%M:%S"), "ok": ok,
                    "rows": rows, "note": note, "refill": refill}
                # 落干预账：重启后仍能回答"上次验证是否真的恢复"
                try:
                    _aft = (rt.get("pacing").snapshot()["channels"]
                            .get(platform) if rt.get("pacing") else {}) or {}
                    storage.save_intervention(
                        platform, "verify", ok=ok, rows=rows,
                        scope=str(scene.get("kind") or ""),
                        before=str(scene.get("kind") or ""),
                        after="%s/%s" % (_aft.get("state"),
                                         _aft.get("reason")),
                        note=("；".join(filter(None, [note,
                              ("补采 %d 条/落库 %d" % (refill.get("n", 0),
                                                       refill.get("rows", 0)))
                              if refill.get("n") else ""]))),
                        ms=int((time.time() - _t0) * 1000))
                except Exception:
                    pass
                logger.info("[验证] %s 回归探测：%s（%d 条）%s", platform,
                            "通过" if ok else "未通过", rows, note)
            finally:
                # 任何路径都要放行（含 window 异常时的 early return），
                # 否则一次异常会让该渠道再也打不开验证窗口。
                with _VERIFY_LOCK:
                    rt.get("verify_open", {}).pop(platform, None)
                # 与在途标记同源清除：窗口关了就不再显示「正在验证」，
                # 此时结果已经落进 scene["verify"]，面板改读验证结论。
                try:
                    (rt.get("scene", {}).get(platform) or {}).pop(
                        "verify_open_at", None)
                except Exception:
                    pass

        # 置位已在锁内完成（见函数头）。线程启动失败要回滚并如实报错。
        _launched = False
        try:
            threading.Thread(target=_run, daemon=True,
                             name="verify-%s" % platform).start()
            _launched = True
            # 窗口开着的这 15 分钟必须是「可见状态」（r482）：原先面板仍写
            # 「需登录 / 去验证」，用户点了看不到任何变化，只好再点一次——
            # 这才是连点的真实根因，光有幂等拒绝只是在事后拦，人还是懵的。
            try:
                rt.setdefault("scene", {}).setdefault(platform, {})["verify_open_at"] = (
                    time.strftime("%H:%M:%S"))
                rt["scene"][platform]["verify_timeout_s"] = 900
            except Exception:
                pass
            logger.info("[干预] 打开 %s 验证窗口：%s（关窗即保存会话并自动探测）",
                        platform, url)
            return {"ok": True, "platform": platform, "url": url,
                    "scene": scene,
                    "hint": "窗口已打开：完成验证后直接关闭窗口——会话自动保存、"
                            "冷却自动解除、并立刻单查探测一次"}
        finally:
            if not _launched:
                with _VERIFY_LOCK:
                    _ving.pop(platform, None)

    rt["verify_channel"] = verify_channel

    _probe_lock = threading.Lock()
    _probing = set()

    def probe_channel(platform, timeout_s=90, scope=""):
        """渠道自检（可干预）：跑完整链路（预热 + 一条真实查询），
        回报「到底能不能出数」以及出在哪条路上。

        与定时采集共用同一把渠道锁，所以自检不会和正在跑的轮次抢会话；
        同一渠道同时只允许一次自检。scope=dom/intl 可选：国内与国际
        走的是不同入口/登录墙，混在一起自检会把"国际被拦"误读成"整家挂"。
        查询取该 scope 第一条航线的第一个日期——自检验的是链路，不是价格。
        """
        _want = str(scope or "").strip().lower()
        if _want not in ("", "dom", "intl"):
            return {"ok": False, "err": "scope 必须是 dom/intl/空"}
        try:
            insts = get_crawlers([platform])
        except Exception as e:
            return {"ok": False, "err": str(e)[:120]}
        if not insts:
            return {"ok": False, "err": "未知渠道: %s" % platform}
        c = insts[0]
        with _probe_lock:
            if platform in _probing:
                return {"ok": False, "err": "该渠道正在自检中，稍后再试"}
            _probing.add(platform)
        t0 = time.time()
        try:
            q = None
            for _u in (rt.get("users") or []):
                for _r in (_u.get("routes") or []):
                    # 航线可能是 dict（原始配置）也可能是 Route 对象
                    # （build_users 之后），两种都要能读
                    def _f(_r, *_ns, _d=""):
                        for _n in _ns:
                            _v = (_r.get(_n) if isinstance(_r, dict)
                                  else getattr(_r, _n, None))
                            if _v:
                                return _v
                        return _d
                    _ds = _f(_r, "dates") or []
                    if _ds:
                        _fc = _f(_r, "from_code", "from", "from_city",
                                 _d="SHA")
                        _tc = _f(_r, "to_code", "to", "to_city", _d="NRT")
                        _is_intl = bool(is_intl_route(_fc, _tc))
                        if _want == "dom" and _is_intl:
                            continue
                        if _want == "intl" and not _is_intl:
                            continue
                        q = (_fc, _tc, _ds[0])
                        break
                if q:
                    break
            if not q and _want:
                return {"ok": False,
                        "err": "当前配置没有%s航线，无法按该范围自检"
                               % ("国际" if _want == "intl" else "国内")}
            if not q:
                q = ("SHA", "NRT", _dtm.now().strftime("%Y-%m-%d"))
            warm = None
            if str(getattr(c, "warmup_url", "") or "").strip():
                with channel_slot(c.name):
                    warm = c.warmup()
                if rt.get("pacing") is not None:
                    rt["pacing"].record(platform)
            with channel_slot(c.name):
                prices = c.safe_fetch(q[0], q[1], [q[2]])
                if rt.get("pacing") is not None:
                    rt["pacing"].record(platform)
            _raw_paths = [dict(x) for x in (getattr(c, "paths", None) or [])]
            # 自检出数 = 链路已通：清熔断 + 刷新 TTL，否则会出现
            # "自检显示 ✓N 条，下一轮仍显示冷却/劣化" 的自相矛盾。
            if prices and rt.get("pacing") is not None:
                try:
                    rt["pacing"].reset(platform)
                    rt["pacing"].note_fetch(
                        platform, (q[0], q[1], q[2]),
                        min(p.price for p in prices), True)
                except (AttributeError, TypeError, ValueError):
                    pass
            # 自检也写路径账（evidence_level=probe）：否则"刚验证通过"无法
            # 覆盖 24h 里的旧劣化，下一次刷新仍判路径劣化。
            _attempt = "probe-%s-%d" % (platform, int(time.time() * 1000))
            for _rec in _raw_paths:
                try:
                    storage.save_fetch_path(
                        platform, q[0], q[1], q[2],
                        _rec.get("path", ""), _rec.get("status", ""),
                        rows=_rec.get("rows", 0),
                        note=_rec.get("detail", ""),
                        evidence_level="probe", attempt_id=_attempt,
                        request_url=str(_rec.get("url") or ""),
                        http_status=int(_rec.get("http") or 0))
                except Exception:
                    pass
            paths = [{"path": p.get("path"), "status": p.get("status"),
                      "rows": p.get("rows"),
                      "detail": str(p.get("detail") or "")[:80]}
                     for p in _raw_paths]
            out = {"ok": True, "platform": platform, "query": list(q),
                   "scope": (_want or ("intl" if is_intl_route(q[0], q[1])
                                       else "dom")),
                   "rows": len(prices), "paths": paths,
                   "warmup": (bool(warm) if warm is not None else None),
                   "cookies": list(getattr(c, "warmup_cookies", []) or []),
                   "blocked_url": (c.last_block_url or "")[:120],
                   "api": (getattr(c, "last_block_api", "") or "")[:120],
                   "scene": dict(getattr(c, "last_scene", {}) or {}),
                   "retry_after": int(getattr(c, "retry_after_s", 0) or 0),
                   "ms": int((time.time() - t0) * 1000)}
            try:
                storage.save_intervention(
                    platform, "probe", ok=bool(prices), rows=len(prices),
                    scope=str(out["scope"]), after=out["scope"],
                    note="/".join("%s %s×%s" % (
                        x.get("path"), x.get("status"), x.get("rows"))
                        for x in paths)[:300],
                    ms=out["ms"])
            except Exception:
                pass
            logger.info("[自检] %s/%s → %d 条（%s，%.1fs）", platform,
                        out["scope"], out["rows"],
                        "/".join(str(p["status"]) for p in paths) or "无路径",
                        out["ms"] / 1000.0)
            return out
        except Exception as e:
            return {"ok": False, "err": str(e)[:160]}
        finally:
            with _probe_lock:
                _probing.discard(platform)

    rt["probe_channel"] = probe_channel

    def sweep(force=False):
        if not _sweep_lock.acquire(blocking=False):
            logger.warning("[扫描] 上一轮仍在进行，跳过本次触发")
            return
        try:
            _sweep_inner(force=force)
        finally:
            _sweep_lock.release()

    def _sweep_inner(force=False):
        from core.pulse import PULSE
        from datetime import datetime as _dtm
        # 轮次标记（单源）：同一轮多航线按顺序完成可跨 8-10 分钟，
        # 控制台 420s 断口聚类会把先完成的 NRT/BKK 误判为“补位”并
        # 压掉真达标。这里把本轮开始时刻落盘，state 以它划轮，
        # 不再靠行间断口猜。end 只作审计留痕，不参与新鲜度判断。
        _scan_marker = os.path.join(
            os.path.dirname(os.path.abspath(storage.db_path)),
            "last_scan.json")
        _scan_start = _dtm.now().strftime("%Y-%m-%d %H:%M:%S")

        def _mark_scan(end=""):
            try:
                with open(_scan_marker, "w", encoding="utf-8") as _f:
                    json.dump({"start": _scan_start, "end": end,
                               "pid": os.getpid()}, _f)
            except OSError as _e:
                logger.warning("[扫描] 轮次标记写入失败: %s", _e)

        # 1 区 · 夜间静默窗：凌晨价格几乎不动，停扫对监控价值无损、
        # 对站点负荷收益最大。手动「立即扫描」传 force 绕过（人要马上看）。
        # 位置刻意在 _mark_scan 之前——静默轮不落轮次标记，否则控制台
        # 会把「本轮」当成一次全渠道空轮，反而像集体故障。
        pac = rt.get("pacing")
        if pac is not None:
            try:
                if not force and pac.quiet_now():
                    # r391：窗口结束即补采。跳过轮不落轮次标记，但若照常
                    # 按 24–37 分钟的间隔接力，07:00 窗口结束后最坏还要
                    # 再等半小时才有第一轮（数据已 6 小时陈旧）。把下次
                    # 触发重排到窗口结束 +1 分钟。
                    _until = pac.seconds_until_quiet_end()
                    if _until is not None:
                        rt["_wake_at"] = _until
                    logger.info(
                        "[节流] 夜间静默窗 %s–%s 内，本轮跳过采集"
                        "（手动「立即扫描」可强制；窗口结束 %s 后自动补采）",
                        pac.cfg.get("scan_quiet_start") or "-",
                        pac.cfg.get("scan_quiet_end") or "-",
                        ("%.0f 分钟" % (_until / 60.0)) if _until else "-")
                    return
            except Exception as _pe:
                logger.warning("[节流] 静默窗判定失败，本轮照常扫描: %s", _pe)
            pac.begin_round(_dtm.now().strftime("%H:%M:%S"))
            # 轮次代际：超时泊车的 worker 可能晚于本轮结束才拿到渠道锁，
            # 它不能再发请求、也不能把现场/失败写进下一轮的账。
            rt["_round_gen"] = int(rt.get("_round_gen") or 0) + 1
            _stagger_todo.clear()
            _warm_todo.clear()
            rt["failed"] = {}          # 本轮失败的渠道查询（验证后补采用）
            # 成功率保护（自动）：近 24h 账本差的渠道自动拉长 TTL，
            # 不等它撞出 429 才熔断。读一次聚合，失败不影响本轮。
            try:
                from core.pacing import shadow_path_preference
                for _p, _node in (storage.path_stats(24) or {}).items():
                    # 影子模式：只记录"本会怎么排路径"，不改变采集顺序。
                    # 先用一天对照，确认不会因统计偏差误杀再开自动。
                    try:
                        # 分域跑影子：国内与国际的入口能力不同，合并统计
                        # 会把"国际 H5 被墙"误算成"国内也该少走 H5"。
                        for _sc, _sn in ((_node.get("scopes") or {})
                                         .items()):
                            _sh = shadow_path_preference(
                                (_sn or {}).get("paths") or {})
                            if _sh["avoid"] or _sh["prefer"]:
                                logger.info(
                                    "[路径影子] %s/%s 偏好 %s · 建议避让 %s"
                                    "（仅记录，不改变本轮顺序）",
                                    _p, _sc,
                                    ",".join("%s %.0f%%" % (x[0], x[1] * 100)
                                             for x in _sh["prefer"]) or "-",
                                    ",".join("%s %.0f%%" % (x[0], x[1] * 100)
                                             for x in _sh["avoid"]) or "-")
                        if not (_node.get("scopes") or {}):
                            _sh = shadow_path_preference(
                                _node.get("paths") or {})
                            if _sh["avoid"] or _sh["prefer"]:
                                logger.info(
                                    "[路径影子] %s 偏好 %s · 建议避让 %s"
                                    "（仅记录，不改变本轮顺序）", _p,
                                    ",".join("%s %.0f%%" % (x[0], x[1] * 100)
                                             for x in _sh["prefer"]) or "-",
                                    ",".join("%s %.0f%%" % (x[0], x[1] * 100)
                                             for x in _sh["avoid"]) or "-")
                    except Exception:
                        pass
                    _qn = int(_node.get("query_attempts") or 0)
                    if _qn >= 5:
                        # 查询口径：H5 被拦但 PC 兜底成功 = 渠道仍健康；
                        # 用路径口径会把"换路成功"误罚成整家降频。
                        pac.set_health(_p, _node.get("query_rate") or 0, _qn)
                    else:
                        pac.set_health(_p, _node.get("rate") or 0,
                                       _node.get("attempts") or 0)
            except Exception as _he:
                logger.warning("[节流] 成功率账本读取失败: %s", _he)
        _mark_scan()
        users, alerters = rt["users"], rt["alerters"]
        if disk_low(_REPO_ROOT):
            logger.warning("[磁盘] 剩余水位低于 %.0fGB，写库/渲染图可能"
                           "被挤占，请及时清理", DISK_FLOOR_GB)
        logger.info("===== 开始一轮扫描（%d 用户 / %d 航线） =====",
                    len(users),
                    len({(r.from_code, r.to_code) for u in users for r in u["routes"]}))
        # 航线×日期 去重注册表：{(from,to,date): [订阅该组合的用户索引]}
        registry = {}
        for ui, u in enumerate(users):
            for r in u["routes"]:
                for d in r.dates:
                    registry.setdefault((r.from_code, r.to_code, d), set()).add(ui)

        # 先按出发日、再按航线排序：临期日期优先采到，避免"越近的越晚
        # 才采"，也让预算不足时先保住最可能下单的日期。
        queries = sorted(registry, key=lambda k: (str(k[2]), str(k[0]),
                                                  str(k[1])))
        # 过期监控日期跳采（_split_expired_queries：渠道对过期查询滚动
        # 返回其他日期航班，照常落库=把别的日期的价挂进过期桶）——
        # 过期航班无购买意义，跳过即治本；日志留痕供「为何没数据」对账
        import datetime as _dt
        _today = _dt.date.today().isoformat()
        queries, _expired_q = _split_expired_queries(queries, _today)
        if _expired_q:
            logger.info("[扫描] 跳过 %d 个过期日期查询（渠道将滚动返回"
                        "其他日期航班）：%s", len(_expired_q),
                        ", ".join(f"{fc}→{tc} {d}" for fc, tc, d in _expired_q))
        PULSE.begin()
        ch_rows = {}   # 渠道 → 本轮合计行数（整轮零记录哨输入）
        _paced_n = [0]  # 本轮被节流主动跳过的渠道查询数（可观测）
        _ran_plats = set()  # 本轮真正发过请求的渠道（告警只对它们计数）
        qry_sup = {}   # 渠道 → {dom/intl: [有记录查询数, 采集查询数]}
        # （部分断供哨输入，c330 F1 起按域分流：intl 结构性零供给面
        # 不与 dom 合并成假比率，哨内逐域独立评估）

        def _stagger_wait(name):
            """5 区 · 起跑错峰：同轮每家只偏移一次，且不持任何锁。"""
            if pac is None or not pac.cfg.get("stagger_seconds"):
                return
            with _stagger_lock:
                if name in _stagger_todo:
                    return
                _stagger_todo.add(name)
            d = stagger_offset(name, pac.cfg["stagger_seconds"])
            if d > 0:
                logger.info("[节流] %s 起跑偏移 %.1fs（同轮渠道不挤同一秒）",
                            name, d)
                time.sleep(d)

        def _warm_once(c):
            """L1/L3 · 本轮首次用到该渠道时先打首页（持 channel_slot）。

            深链直入是最强的机器指纹（无 referer、无风控 cookie）；先访问
            首页能把这一条抹掉。每轮每渠道只做一次，失败不阻断采集。
            """
            if pac is None or not pac.cfg.get("warmup_enabled"):
                return
            in_list = c.name in (pac.cfg.get("warmup_platforms") or ())
            # 上一轮被软拒（202 空体/444）的渠道：即便不在预热名单，
            # 本轮也必须先养会话再查深链。
            try:
                forced = bool((pac.snapshot()["channels"]
                               .get(c.name) or {}).get("needs_warmup"))
            except Exception:
                forced = False
            # 会话老化看门狗：profile 太久没更新会被站点当"新设备"，
            # 超过 session_max_days 时即便不在预热名单也强制续一次
            try:
                aged = bool(getattr(c, "session_max_days", 0)) and (
                    c.session_age_days > c.session_max_days)
            except Exception:
                aged = False
            if not in_list and not aged and not forced:
                return
            if not str(getattr(c, "warmup_url", "") or "").strip():
                return
            if aged and not in_list:
                logger.warning("[会话] %s 已 %.0f 天未更新，强制预热续期",
                               c.name, c.session_age_days)
            with _warm_lock:
                if c.name in _warm_todo:
                    return
                _warm_todo.add(c.name)
            with channel_slot(c.name):
                ok = c.warmup()
                # 预热也是一次真实请求：计入令牌桶，避免紧接着的深链
                # 请求把"首页+列表"挤在同一秒（等于没降频）。
                if pac is not None:
                    pac.record(c.name)
                    # 只有真的拿到风控 cookie 才清软拒标记；否则下一轮
                    # 继续先预热（只访问首页≠已养熟会话）
                    try:
                        # 没有声明风控 cookie 判据的渠道（如 tuniu）拿不到
                        # "真的养熟了"的证据，不能据此清软拒；等它自然
                        # 成功出数后由 observe(reset) 清。
                        _has_risk = bool(getattr(c, "RISK_COOKIES", ()) or ())
                        if _has_risk and getattr(c, "warmup_cookie_ok", False):
                            pac.note_warmup_ok(c.name)
                    except Exception:
                        pass
                return ok

        def _timed_fetch(c, fc_, tc_, d_, th_min=None, gen=None):
            # 单渠道计时入脉冲（成败=是否有数据），控制台可观察性数据源
            t0 = time.time()
            prices = []
            key = (fc_, tc_, d_)
            # 提交时由主线程传入轮次代际；worker 晚启动/晚拿锁时用它
            # 判断"这已经是上一轮的活了"。
            _gen = gen
            if _gen is not None and rt.get("_round_gen") != _gen:
                if pac is not None:
                    pac.note_paced(c.name, "stale_round")
                return [], "paced"
            # 同一轮同一渠道的一次采集（含多返程日）共用一个 attempt_id，
            # 路径账据此按「查询」而不是按「路径行」算成功率。
            _attempt = "%s-%d-%d" % (c.name, int(time.time() * 1000),
                                     threading.get_ident())
            _prices = []
            _paths = []
            # 证据必须在渠道锁内取走：超时泊车的 worker 之后仍会继续写
            # c.paths / last_scene，锁外读可能读到"下一个查询"的证据，
            # 把 A 查询的拦截算到 B 查询头上。这里一次快照，后续只用副本。
            # 3/5 区闸门一律在「渠道锁外」判定与等待——持锁睡眠会把
            # 5 家渠道串成一条队，慢渠道拖死整轮（旧 310s 预防等待的教训）
            if pac is not None:
                try:
                    _days = None
                    try:
                        _days = (_dt.date.fromisoformat(str(d_))
                                 - _dt.date.today()).days
                    except (TypeError, ValueError):
                        _days = None
                    tier, why = pac.plan_query(c.name, key, th_min,
                                               days_ahead=_days)
                    pac.note_plan(c.name, key, tier, why)
                    if tier == "skip":
                        pac.note_paced(c.name, why)
                        return [], "paced"
                    ok, remain = pac.allow(c.name)
                    if not ok:
                        _ch = (pac.snapshot()["channels"].get(c.name) or {})
                        logger.info(
                            "[节流] %s 熔断中（剩余 %ds · %s），本轮跳过"
                            " %s→%s %s", c.name, remain,
                            _ch.get("reason") or "?", fc_, tc_, d_)
                        pac.note_paced(c.name, "breaker")
                        return [], "paced"
                    _stagger_wait(c.name)
                    _warm_once(c)
                    if _gen is not None and rt.get("_round_gen") != _gen:
                        pac.note_paced(c.name, "stale_round")
                        return [], "paced"
                    # 令牌桶等待必须有预算上限：wait_hint 只算不睡，
                    # 这里睡到窗口重新可用为止；若超过本轮 30s 预算，
                    # 宁可跳过这条查询，也不提前打出去把限额坐实。
                    _deadline = time.time() + 30.0
                    while True:
                        _w = pac.wait_hint(c.name)
                        if _w <= 0:
                            break
                        if _w > max(0.0, _deadline - time.time()):
                            logger.info(
                                "[节流] %s 令牌桶还需 %.1fs，超过本轮预算，"
                                "跳过 %s→%s %s", c.name, _w, fc_, tc_, d_)
                            pac.note_paced(c.name, "budget")
                            return [], "paced"
                        logger.info("[节流] %s 令牌桶等待 %.1fs", c.name, _w)
                        time.sleep(_w + 0.05)
                except Exception as _pe:
                    logger.warning("[节流] 前置闸门异常（放行本轮）: %s", _pe)
            with channel_slot(c.name):
                if _gen is not None and rt.get("_round_gen") != _gen:
                    logger.info("[节流] %s 上一轮超时 worker 让位，不再发请求",
                                c.name)
                    pac.note_paced(c.name, "stale_round")
                    return [], "paced"
                # 2 区 · 整批持锁：同渠道多返程日一次做完，避免释放锁后
                # 被别的查询插进来——插队会打断入口页预热链（444 之源）
                _sent_here = False
                for _rd in (ret_dates.get(key) or [""]):
                    if _gen is not None and rt.get("_round_gen") != _gen:
                        # 轮次已翻页：这条旧查询不再发新请求，避免"上一轮
                        # 的活"在下一轮继续占额度/打断预热链
                        logger.info("[节流] %s 旧轮查询在返程循环中让位",
                                    c.name)
                        pac.note_paced(c.name, "stale_round")
                        return [], "paced"
                    if pac is not None:
                        pac.record(c.name)
                    c.last_query = key
                    if pac is not None and not _sent_here:
                        # 一次查询=一次发送；多返程日同批不重复计预算
                        pac.note_sent(c.name)
                        _sent_here = True
                    _prices.extend(c.safe_fetch(fc_, tc_, [d_],
                                                ret_date=_rd))
                    if getattr(c, "last_busy", False):
                        # 4 区 · 会话卫生：自家 profile 互斥没抢到只让位，
                        # 不重试——重试会跳过入口预热，把自家冲突变成对方
                        # 眼里的「新会话直捣深链」（444 主因）
                        if pac is not None:
                            pac.note_busy(c.name)
                        logger.warning(
                            "[会话] %s profile 正被占用，本轮让位该渠道"
                            "（不重试：裸 cookie 连打会把冲突升级成 444）",
                            c.name)
                        break
                _paths = [dict(x) for x in (getattr(c, "paths", []) or [])]
                # 202/444 软拒：把"没拿到业务响应"标成独立状态，
                # 不冒充 empty（真无票），也不冒充 error（解析失败）。
                if getattr(c, "_soft_pending", False) and not any(
                        x.get("status") in ("ok", "calendar") for x in _paths):
                    _code = int((getattr(c, "last_soft_reject", {}) or {})
                                .get("code") or 0)
                    _paths.append({
                        "path": "H5" if getattr(c, "use_mobile", False)
                                else "PC",
                        "status": "soft_reject", "rows": 0,
                        "date": d_,
                        "detail": "HTTP %d 软拒（会话/边缘未给业务响应）"
                                  % _code if _code else "软拒（无业务响应）",
                        "mobile": bool(getattr(c, "use_mobile", False)),
                        "httpStatus": _code,
                    })
            prices = _prices
            paths = _paths
            _soft = any(x.get("status") == "soft_reject" for x in paths)
            if pac is not None:
                try:
                    pac.note_result(c.name, ok=bool(prices), soft=bool(_soft))
                except Exception:
                    pass
            if pac is not None and not prices and not _soft:
                try:
                    if _gen is None or rt.get("_round_gen") == _gen:
                        rt.setdefault("failed", {}).setdefault(
                            c.name, set()).add(key)
                except Exception:
                    pass
            # 服务端让我们等多久（429/503 的 Retry-After）：有就优先于
            # 自算的 2^n 阶梯——这是唯一「对方明说」的配额信号
            _ra = 0
            _gen_ok = (_gen is None or rt.get("_round_gen") == _gen)
            if pac is not None:
                try:
                    _ra = int(getattr(c, "retry_after_s", 0) or 0)
                    c.retry_after_s = 0
                except (TypeError, ValueError, AttributeError):
                    _ra = 0
                if prices:
                    # 出数即健康：哪怕某条 fallback 路径被拒（H5 blocked →
                    # PC ok），也不能据失败路径把整渠道熔断——那会把
                    # "换路径成功"误判成"被封"，是本末倒置。
                    # 但旧轮 worker 的结果不能改新轮的熔断/TTL 状态。
                    if _gen_ok:
                        # 连续成功才完全清零 strikes：只成功一次就复位，
                        # 会让抖动渠道在"冷却/恢复"间反复横跳。
                        pac.note_ok(c.name)
                        try:
                            pac.note_fetch(c.name, key,
                                           min(p.price for p in prices), True)
                        except (AttributeError, TypeError, ValueError):
                            pass
                else:
                    # 2 区 · 落地归因：只拿「失败路径」的证据判定——成功
                    # 路径的文案（接口字段里带「验证」字样）不能触发熔断
                    _bad = [x for x in paths
                            if x.get("status") not in ("ok", "calendar",
                                                       "empty")]
                    _note = " ".join(str(x.get("detail") or "")
                                     for x in _bad)
                    if _gen_ok:
                        _kind, _cd = pac.observe(
                            c.name, [x.get("status") for x in _bad], _note,
                            retry_after=_ra)
                    else:
                        _kind, _cd = "", 0
                    if _kind:
                        # 案发现场：时间/类型/查询/被拒 URL/证据摘要，
                        # 「去验证」直接拿它开窗口，不用人工再找一遍
                        # 轮末之后才落地的证据不写：它属于上一轮，写进来
                        # 会让下一轮的「去验证」打开上一轮的现场。
                        if _gen is not None and rt.get("_round_gen") != _gen:
                            _kind = ""
                            _cd = 0
                    if _kind:
                        _bad0 = next(
                            (x for x in _bad
                             if x.get("status") in ("blocked", "login")),
                            _bad[0] if _bad else {})
                        rt["scene"][c.name] = {
                            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "kind": _kind, "query": list(key),
                            "url": str(getattr(c, "last_block_url", "") or ""),
                            "api": str(getattr(c, "last_block_api", "") or ""),
                            "note": _note[:200],
                            # 被拦时用的 PC/H5 身份：验证窗口必须复用，
                            # 不能拿另一个视口去过验证
                            "mobile": (bool(_bad0.get("mobile"))
                                       if "mobile" in _bad0 else None),
                            "files": dict(getattr(c, "last_scene", {}) or {})}
                        # 自动熔断也入账（action=auto_trip）。原先只有手动
                        # warm/verify/probe 写 interventions，于是账本在
                        # 35 小时里"零干预"——系统自己熔断过什么、冷却多久，
                        # 事后完全无法追溯。只记状态跃迁（每个 kind 一次），
                        # 不记每次失败，量级与手动干预同一档。
                        try:
                            storage.save_intervention(
                                c.name, "auto_trip", ok=False,
                                scope=_kind, note=("自动熔断 %s，冷却 %ss · %s"
                                                   % (_kind, int(_cd),
                                                      _note[:120])))
                        except Exception:
                            pass
                        _ch = (pac.snapshot()["channels"].get(c.name) or {})
                        logger.warning(
                            "[节流] %s 命中%s，熔断 %ds（第 %d 次）",
                            c.name, _kind, _cd, _ch.get("strikes", 0))
                        # 自动开窗（可配置）：命中人机验证时直接把窗口端到
                        # 人面前，不用等人发现状态条变红。同渠道 10 分钟内
                        # 只开一次，防连点。
                        _auto = bool(((rt.get("cfg") or cfg).get("crawler")
                                      or {}).get("auto_verify", False))
                        if _kind == "captcha":
                            if _auto:
                                _av = rt.setdefault("_auto_verify_at", {})
                                if time.time() - _av.get(c.name, 0) > 600:
                                    _av[c.name] = time.time()
                                    logger.info("[干预] %s 命中验证，自动打开"
                                                "验证窗口（auto_verify）", c.name)
                                    threading.Thread(
                                        target=verify_channel, args=(c.name,),
                                        daemon=True).start()
                            else:
                                # 「自动开窗已关闭」要留痕（r505）：否则命中验证后
                                # 界面只剩「需验证」，用户既不知道本来可以自动处理，
                                # 也不知道是自己关掉的——属「可识别」缺口。
                                logger.warning(
                                    "[干预] %s 命中验证，但「命中验证自动开窗」"
                                    "已关闭（配置 · 全局参数 → 采集）；"
                                    "需要人工点「去验证」", c.name)
            ok_paths = [x for x in paths
                        if x.get("status") in ("ok", "calendar")]
            selected = ok_paths[-1] if ok_paths else None
            pid = 0
            for rec in paths:
                rid = storage.save_fetch_path(
                    c.name, fc_, tc_, d_, rec.get("path", ""),
                    rec.get("status", ""), rows=rec.get("rows", 0),
                    note=rec.get("detail", ""), evidence_level="path",
                    attempt_id=_attempt,
                    request_url=str(rec.get("url") or ""),
                    http_status=int(rec.get("http")
                                    or rec.get("httpStatus") or 0))
                if rec is selected:
                    pid = rid
            prov = json.dumps({
                "entryPath": (selected or {}).get("path", ""),
                "pathId": pid,
                "pathStatus": (selected or {}).get("status", "unknown"),
                "evidenceLevel": "path" if selected else "unknown",
                "kind": ("calendar" if selected and
                         selected.get("status") == "calendar" else "detail"),
            }, ensure_ascii=False)
            for p in prices:
                try:
                    p.prov = prov
                except AttributeError:
                    pass
            try:
                PULSE.channel(c.name, len(prices), time.time() - t0)
            except Exception:
                pass
            return prices, "ok"

        # 往返回程日旁挂（R15，INTL_DESIGN §2.6；r339 多返程扩展）：
        # 查询键 (fc,tc,d) → 返程日列表——同键多用户取并集（去重保
        # 序；往返对同 OD 同日异回程的混订场景由列表语义承载）
        ret_dates = {}
        for (fc_, tc_, d_), uis in registry.items():
            for ui in uis:
                for r in users[ui]["routes"]:
                    if (r.from_code == fc_ and r.to_code == tc_
                            and d_ in r.dates):
                        rds = getattr(r, "ret_dates", None) or (
                            [r.ret_date] if getattr(r, "ret_date", "")
                            else [])
                        for _rd in rds:
                            if _rd not in ret_dates.setdefault(
                                    (fc_, tc_, d_), []):
                                ret_dates[(fc_, tc_, d_)].append(_rd)

        user_pairs = {}   # 按用户聚合 (route, prices)，轮末一次聚合推送
        chart_cache = {ui: {} for ui in range(len(users))}
        for qi, (fc, tc, d) in enumerate(queries):
            # 平台集合 = 所有订阅用户平台配置的并集（一次采集服务所有人）
            plats = set()
            th_min = None  # 该查询的最低达标线（qunar 幻影价复核参考）
            for ui in registry[(fc, tc, d)]:
                plats |= set(users[ui]["platforms"])
                for r in users[ui]["routes"]:
                    if r.from_code == fc and r.to_code == tc and d in r.dates:
                        for v in (r.alert_direct, r.alert_transfer):
                            try:
                                v = float(v or 0)
                            except (TypeError, ValueError):
                                continue
                            if v > 0:
                                th_min = v if th_min is None else min(th_min, v)
            for c in get_crawlers(plats):
                try:
                    c.threshold_hints[(fc, tc, d)] = {"min": th_min}
                except AttributeError:
                    pass
            # 渠道并发（各平台相互独立：浏览器实例/会话目录均隔离）；
            # 去哪儿的全局限流错峰由 qunar 渠道自身控制（类级时间锁），
            # 不再让其余渠道陪等
            all_prices = []
            _cap = int(((rt.get("pacing").cfg.get("max_concurrency")
                         if rt.get("pacing") else 0) or 0))
            _mw = max(1, len(plats) or 1)
            if _cap:
                _mw = min(_mw, _cap)
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=_mw)
            try:
                futs = {ex.submit(_timed_fetch, c, fc, tc, d, th_min,
                                  rt.get("_round_gen")): c.name
                        for c in get_crawlers(plats)}
                results, timed_out = _collect_route_futures(
                    futs, timeout_s=_ROUTE_FUT_TIMEOUT, logger=logger)
                for _nm, _res in results:
                    # 节流跳过（TTL 内 / 熔断中 / 会话让位）不进健康分母：
                    # 主动不发请求不是"断供"，否则健康度被自己的克制染红，
                    # 反而诱导人去"多点几次"把限流坐实
                    if isinstance(_res, tuple) and len(_res) == 2:
                        prices, _meta = _res
                    else:
                        prices, _meta = (_res or []), "ok"
                    if _meta == "paced":
                        _paced_n[0] += 1
                        continue
                    _ran_plats.add(_nm)
                    all_prices.extend(prices)
                    ch_rows[_nm] = ch_rows.get(_nm, 0) + len(prices)
                    # 分母按域分流（c330 F1）：渠道×域结构性零供给面
                    # （intl 全断）不与 dom 满勤合并成假比率，qsup 逐域
                    # 独立评估——intl 全断归 zrow 领地，dom 满勤不评估
                    _dom = "intl" if is_intl_route(fc, tc) else "dom"
                    _qs = qry_sup.setdefault(_nm, {}).setdefault(_dom, [0, 0])
                    _qs[1] += 1
                    if prices:
                        _qs[0] += 1
                # 泊车渠道按失败查询计（比率哨分母照记：路由级断供
                # 也要进「有记录查询数/启用查询数」口径）
                for _nm in timed_out:
                    _dom = "intl" if is_intl_route(fc, tc) else "dom"
                    _qs = qry_sup.setdefault(_nm, {}).setdefault(_dom, [0, 0])
                    _qs[1] += 1
            finally:
                # wait=False：泊车 worker（无超时 playwright 调用）不随
                # 栅栏 join——with 形态的 shutdown(wait=True) 曾把已放行
                # 的栅栏重新焊死在退出路径上
                ex.shutdown(wait=False)
            all_prices = _stable_pool(all_prices)
            storage.save_many(all_prices)
            # 半年走势日桶（r320b）：落库后立即重算本 (航线,日期) 的
            # 当日聚合桶（幂等重扫修正）——purge 删 14 天前明细后长窗
            # 仍完整；与 purge 顺序无耦合（桶在轮尾当日刷新）
            if all_prices:
                try:
                    storage.refresh_daily(fc, tc, d)
                except Exception:
                    logger.exception("[日桶] %s→%s %s 刷新失败",
                                     fc, tc, d)
                try:
                    _fd_days = {_dt.date.today().isoformat(),
                                (_dt.date.today() - _dt.timedelta(days=1)).isoformat()}
                    for _fd_day in _fd_days:
                        storage.refresh_flight_daily(fc, tc, d, _fd_day)
                except Exception:
                    logger.exception("[航班日桶] %s→%s %s 刷新失败",
                                     fc, tc, d)
            _field_sentinel(all_prices, logger)
            # 走势图按用户各自生成（多租户同 OD 时各用户阈值/衔接
            # 下限画自己的图——「全部用户 seen 首遇配置胜出」的内容
            # 级渗漏与本地互覆双根治；charts_fn 返回 {(from,to,date):
            # url} 整表，取本航线单 URL 入该用户缓存，alerter 拿到
            # dict 嵌进 markdown 变裂图）
            for ui in sorted(registry[(fc, tc, d)]):
                _cu = charts_fn(fc, tc, d, users[ui]["name"]) or {}
                _cu_url = _cu.get((fc, tc, d))
                if _cu_url:
                    chart_cache[ui][(fc, tc, d)] = _cu_url
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
        # 节流账本（可观测）：「少发了多少」比「抓到了多少」更能说明风险
        # 姿态——只跳不报等于黑箱，用户会误以为是渠道挂了
        if pac is not None:
            try:
                _lr = pac.snapshot()["last_round"]
                _fast = int(_lr.get("fast") or 0)
                _slow = int(_lr.get("slow") or 0)
                _ttl = int(_lr.get("skip") or 0)
                logger.info(
                    "[节流] 计划 %d 次渠道查询（快层 %d / 慢层 %d / TTL 内 %d）"
                    "；实际未发 %d 次 · 熔断触发 %d · 会话让位 %s",
                    _fast + _slow + _ttl, _fast, _slow, _ttl, _paced_n[0],
                    len(_lr.get("trips") or []),
                    ",".join(_lr.get("busy") or []) or "无")
            except Exception as _pe:
                logger.warning("[节流] 账本汇总失败: %s", _pe)
        # 渠道级告警：连续 N 轮零数据主动推一条（不替代面板，只是别让人
        # 一直盯着）。只在"真的发过请求"的渠道上计数——被节流跳过的轮次
        # 不算断供，否则静默窗会误报。
        try:
            # 配置就近用户（所有 notifier 设置都在 users[].notifier 里），
            # 顶层 notifier 只作兼容兜底。多用户时取第一个真正配了推送
            # 的用户，不能因为 0 号用户没配就整条告警静默。
            _u0 = next(
                (u for u in (rt.get("users") or [])
                 if (u.get("notifier") or {})), {})
            _cn = ((_u0.get("notifier") or {}).get("channel_alert")
                   or ((rt.get("cfg") or cfg).get("notifier") or {})
                   .get("channel_alert") or {})
            if _cn.get("enabled", True):
                import time as _t
                from core.channel_alert import alert_text, should_alert
                _rounds = int(_cn.get("rounds", 3) or 3)
                _cool = float(_cn.get("cooldown_h", 6) or 6) * 3600
                _now = _t.time()
                for _p in _ran_plats:
                    _st = rt.setdefault("zero_streak", {}).setdefault(
                        _p, {"n": 0, "last_alert": 0.0, "last_ok": 0.0})
                    if ch_rows.get(_p, 0) > 0:
                        _st["n"] = 0
                        _st["last_ok"] = _now
                        continue
                    _st["n"] = int(_st.get("n") or 0) + 1
                    if not should_alert(_st["n"], _rounds, _st["last_alert"],
                                        _now, _cool):
                        continue
                    _a0 = next((a for a in alerters
                                if getattr(a, "notifier", None) is not None),
                               None)
                    if _a0 is None:
                        continue
                    try:
                        if _a0._in_quiet():
                            continue
                    except Exception:
                        pass
                    _scene = (rt.get("scene") or {}).get(_p) or {}
                    _title, _desp = alert_text(
                        _p, _st["n"], _st.get("last_ok"), _now,
                        _scene.get("note") or "")
                    _a0.notifier.send(sanitize_desp(_title),
                                      sanitize_desp(_desp))
                    _st["last_alert"] = _now
                    logger.warning("[渠道告警] %s 连续 %d 轮零数据，已推送",
                                   _p, _st["n"])
        except Exception as _ce:
            logger.warning("[渠道告警] 判定失败: %s", _ce)
        # 轮末统一分发（全部航线采集完成后聚合推送）
        for ui, pairs in user_pairs.items():
            try:
                alerters[ui].round_charts = chart_cache.get(ui) or {}
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
        # 指定航班关注目标提醒（r352）：轮尾按真实落库行核对，
        # 去抖状态存 alert_state；通知失败下轮重试，不阻断扫描。
        try:
            from webui import _watch_alert_round
            for _ui, _u in enumerate(users):
                if _ui >= len(alerters):
                    continue
                _watch_alert_round(
                    _u["name"], alerters[_ui].notifier, storage, logger,
                    base_url=getattr(alerters[_ui], "base_url", ""))
        except Exception as e:
            logger.warning("[关注] 轮次提醒异常: %s", e)
        # 特价监控（r319）：轮尾跑（与主采集错峰；内部全自吞不炸轮）
        try:
            _specials_round()
        except Exception as e:
            logger.warning("[特价] 本轮异常: %s", e)
        PULSE.end()
        _mark_scan(_dtm.now().strftime("%Y-%m-%d %H:%M:%S"))
        # 渠道整轮零记录哨（本轮全部查询聚合行数；风控断供「零记录」
        # 形态对行历史池/no_det 双盲，独立观测面）
        try:
            _channel_zero_sentinel(ch_rows, logger)
        except Exception as e:
            logger.warning("[解析哨兵] 零记录哨异常: %s", e)
        # 渠道部分断供哨（查询级比率口径；合计口径对部分 (route,date)
        # 断供失明——单查询在场即合计非零整哨静默）
        try:
            _channel_partial_sentinel(qry_sup, logger)
        except Exception as e:
            logger.warning("[解析哨兵] 部分断供哨异常: %s", e)
        # 渠道会话失效钉钉告警哨（r338 用户提案：需人工干预类渠道
        # 问题浮出推送面，日志级告警用户零感知实录）
        try:
            _channel_login_alert_sentinel(
                list(zip(users, alerters)), logger)
        except Exception as e:
            logger.warning("[渠道告警] 哨异常: %s", e)
        logger.info("===== 本轮扫描结束 =====")
        # 数据窗口维护：删过期明细（extra 大 JSON 是增长主体）。
        # 保留天数单源在 PriceStorage.RAW_RETAIN_DAYS（8 天）：所有
        # 读取方都在 168h 内，14 天纯占盘（实测白占 184 MB）。
        try:
            _sz0 = os.path.getsize(storage.db_path) if os.path.isfile(
                storage.db_path) else 0
            n = storage.purge()
            if n:
                logger.info("[存储] 已清理 %d 条过期价格记录", n)
                # 删除不缩文件：删得多且距上次够久才 VACUUM（会短暂锁库）
                if storage.maybe_vacuum(n):
                    try:
                        _sz1 = os.path.getsize(storage.db_path)
                        logger.info("[存储] VACUUM 完成：%.0f MB → %.0f MB",
                                    _sz0 / 1048576.0, _sz1 / 1048576.0)
                    except OSError:
                        logger.info("[存储] VACUUM 完成")
        except Exception as e:
            logger.warning("[存储] 过期清理失败: %s", e)
        # 控制台缓存预热：扫描写库使 /api/state 签名失效，后台先重建，
        # 用户打开控制台永远命中热缓存（首屏不等全量重算）
        try:
            import webui as _webui
            _webui.prewarm_state()
        except Exception:
            pass

    return sweep


def acquire_instance_lock() -> bool:
    """单实例互斥锁：多实例并发会抢采/互踩 DB/调度互相干扰（历史多轮
    事故）。锁文件 data/.instance.lock 被第二个实例加锁失败 → 立即
    退出；进程退出时 OS 自动释放（含崩溃）。三平台（R50）：Windows
    msvcrt.locking / POSIX fcntl.flock。"""
    lock_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", ".instance.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    global _LOCK_FP
    _LOCK_FP = open(lock_path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(_LOCK_FP.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_LOCK_FP.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except ImportError:
        # 理论不可达（msvcrt/fcntl 皆标准库）：双保险友好出口
        print("⚠ 当前平台无文件锁原语：跳过单实例锁（多实例风险由部署方保证）")
        return True
    except OSError:
        try:
            _LOCK_FP.close()
        except Exception:
            pass
        return False


_LOCK_FP = None


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
    ap.add_argument("--app-status", action="store_true",
                    help="检查 Android 运行时（App 渠道）状态后退出；只读，不安装任何东西")
    ap.add_argument("--setup-login", action="store_true",
                    help="顺序弹出浏览器引导登录所有已启用渠道（每家登录一次永久复用）")
    ap.add_argument("--login", metavar="PLATFORM",
                    help="登录指定平台(ctrip/fliggy/tongcheng)，弹出可见浏览器，登录完成后回车保存会话")
    ap.add_argument("--restart-delay", type=float, default=0.0,
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    # 锁在参数解析后：--version/--help 曾被单实例锁拦下，
    # 发版门禁「exe 实跑 --version」在监控运行时必假红
    if args.restart_delay > 0:
        # 自重启通道（webui /api/restart 拉起）：旧进程约 1s 后退出才
        # 释放 data/.instance.lock——新实例即时抢锁必撞锁退场（十五§1
        # 同族），延迟到旧进程死后再加锁
        time.sleep(args.restart_delay)
    if args.app_status:
        # 只读体检：先于实例锁返回。体检不该因为"已有实例在跑"而失败
        # ——恰恰相反，那正是用户想确认状态的时刻。
        from core.android.bootstrap import status as _app_status
        _p = Path(args.config)
        _cfg = load_config(str(_p)) if _p.exists() else {}

        def _app_evidence():
            """「验证可采集」的判据：库里真有过 App 渠道的成功记录。

            不看日志、不看配置——只认落库事实；读不到库就是没验证过，
            保持未勾选，不猜。
            """
            try:
                from core.storage import PriceStorage
                _db = ((_cfg.get("output") or {}).get("db_path")
                       or "data/prices.db")
                import sqlite3
                import os as _os
                if not _os.path.exists(_db):
                    return False
                con = sqlite3.connect(_db)
                try:
                    row = con.execute(
                        "SELECT COUNT(1) FROM flight_prices "
                        "WHERE platform LIKE 'app_%'").fetchone()
                    return bool(row and row[0] > 0)
                finally:
                    con.close()
            except Exception:
                return False

        _st = _app_status(_cfg, evidence=_app_evidence)
        print(f"Android 运行时：{_st['state']}")
        print(f"  说明：{_st['detail']}")
        for _s in _st.get("steps") or []:
            print(f"    [{'x' if _s['done'] else ' '}] {_s['label']}")
        if _st.get("next"):
            print(f"  下一步：{_st['next']}")
        return

    if not acquire_instance_lock():
        print("⚠ 已有实例在运行（检测到实例锁），本次启动退出。"
              "控制台仍可用：浏览器打开 http://127.0.0.1:8765")
        sys.exit(1)

    # pidfile 进程自写（start.ps1 亦写同文件同值=双保险；/api/restart
    # 直拉的新实例此前漏写→status/stop 假死盲区，r339g 活体首鸣实锤）
    try:
        (Path(__file__).resolve().parent / ".monitor.pid").write_text(
            str(os.getpid()), encoding="ascii")
    except OSError:
        pass

    cfg_path = Path(args.config)

    if args.setup:
        from wizard import run_wizard
        run_wizard(str(cfg_path))
        print("配置完成，重新运行程序即开始监控。")
        return

    if args.install_browser:
        ensure_chromium(["qunar"])
        return

    if args.app_status:
        # 只读体检：打印 Android 运行时状态与下一步，不安装任何东西
        from core.android.bootstrap import status as _app_status
        _cfg = load_config(str(cfg_path)) if cfg_path.exists() else {}
        _st = _app_status(_cfg)
        print(f"Android 运行时：{_st['state']}")
        print(f"  说明：{_st['detail']}")
        for _s in _st.get("steps") or []:
            print(f"    [{'x' if _s['done'] else ' '}] {_s['label']}")
        if _st.get("next"):
            print(f"  下一步：{_st['next']}")
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
    logger = setup_logger(_anchored(out.get("log_path"), "logs/monitor.log"))
    # 启动级路径迁移（r339/r342「一切配置可变更化」）：源=上次成功
    # 启动记录（跨重启链式迁移），目标=本次 config.yaml；db/user_data
    # 自动搬迁，日志/内核目录不搬（切换后新位置生效，旧档保留）。
    _new_db = _anchored(out.get("db_path", "data/prices.db"),
                        "data/prices.db")
    _new_ud = _anchored(str((cfg.get("crawler") or {}).get(
        "user_data_dir", "user_data") or "user_data"), "user_data")
    _new_log = _anchored(out.get("log_path", "logs/monitor.log"),
                         "logs/monitor.log")
    _new_bdir = str((cfg.get("crawler") or {}).get("browser_dir", "") or "")
    _prev = _load_storage_paths()
    _old_db = _prev.get("db") or _anchored("data/prices.db",
                                            "data/prices.db")
    _old_ud = _prev.get("user_data") or _anchored("user_data",
                                                  "user_data")
    try:
        if _migrate_db_if_needed(
                _old_db, _new_db, _anchored("data/.r339_sentinel",
                                      "data/.r339_sentinel")):
            logger.info("[迁移] 旧数据库已搬迁至 %s", _new_db)
    except Exception as e:
        logger.warning("[迁移] 数据库搬迁失败（新路径继续；旧档保留）: %s", e)
    try:
        if _migrate_user_data_if_needed(_old_ud, _new_ud):
            logger.info("[迁移] 旧浏览器登录态已搬迁至 %s", _new_ud)
    except Exception as e:
        logger.warning("[迁移] 登录态搬迁失败（新目录继续；旧档保留）: %s", e)
    _apply_browser_dir(cfg)
    ensure_chromium(cfg.get("platforms") or ["qunar"], logger)
    # App 渠道（可选）：只在勾了 App 渠道时才检查，未勾选零开销。
    # 与 ensure_chromium 的差别：**不自动下载**——MuMu 约 7GB 且需一次
    # 管理员确认，越界替用户装会被当成流氓行为，只给可执行的指引。
    try:
        from core.android.bootstrap import ensure_android_runtime
        _app_plats = set()
        for _u in (cfg.get("users") or []):
            _app_plats |= set(_u.get("platforms") or [])
        ensure_android_runtime(sorted(_app_plats), cfg, logger)
    except Exception as e:
        logger.warning("[app] 引导检查失败（不影响其他渠道）: %s", e)
    storage = PriceStorage(_anchored(out.get("db_path"), "data/prices.db"))
    # 迁移源状态只在库成功打开后落盘：路径不可写等启动失败时保留
    # 上一次成功源，下次启动仍能重试搬迁（提前落盘会让真源被遗忘）
    _save_storage_paths(_new_db, _new_ud, _new_log, _new_bdir)
    # 基线断代回填（空窗旧键在册才触发，幂等）：生产哨状态 10-16 格式
    # 迁移遗留的渠道×字段粒度供给记录转窗粒度基线——迁移前断链的字段
    # 否则永被 never-supplied 门静默（fliggy|prate 等五字段假阴实录）
    _sent_backfill_supplied(_anchored(out.get("db_path"), "data/prices.db"))
    # zdom 域供给基线 DB 回填（幂等）：哨上线时已处断供中的域进程内
    # 永不建立基线（tuniu dom 断供第 5 天「无哨在响」实录）——DB 历史
    # 行按域补记「曾供给」，全库史结构零域（tongcheng intl）不补记
    _sent_backfill_domzero(_anchored(out.get("db_path"), "data/prices.db"))

    # 运行时容器：web 配置热重载时替换 users/alerters/cfg，sweep 每轮取最新；
    # rt["cfg"] 是配置的单一事实源（reload_config 同步更新）
    rt = {}
    rt["cfg"] = cfg

    def build_runtime():
        users = build_users(cfg)
        alerters = []
        for u in users:
            ncfg = u["notifier"]
            notifier = build_notifier(ncfg, logger, base_url=str(
                (cfg.get("web") or {}).get("base_url") or (
                    "http://127.0.0.1:%d" % int(
                        ((cfg.get("web") or {}).get("port", 8765))
                        or 8765))))
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
                # 心跳正文形态三态线（slim/full/auto，默认 slim）：
                # 消费层完备而配置线缺席=示例键成死键文档（配置
                # full/auto 静默无效果）；层级=notifier 顶层与
                # push_drop_min 平级
                heartbeat_style=str((ncfg or {}).get("heartbeat_style")
                                    or "slim"),
                storm_repeat=int((ncfg or {}).get("storm_repeat", 3)),
                # 图床配置直传（推送表格图走 upload_chart 统一
                # 入口，provider 可切 smms；freeimage 上传端点已封禁）
                image_host=dict((ncfg or {}).get("image_host") or {}),
                user=u["name"],
                platforms=u.get("platforms"),
                urgent_notifier=urgent,
                quiet_start=str((ncfg or {}).get("quiet_start", "") or ""),
                quiet_end=str((ncfg or {}).get("quiet_end", "") or ""),
                # base_url 可配置：钉钉「完整详情」链接的可达性取决于它——
                # 服务默认绑 127.0.0.1，手机端钉钉点开必死链；手机要看详情需
                # 配 web.base_url 为本机局域网地址（如 http://192.168.x.x:8765）
                base_url=str((cfg.get("web") or {}).get("base_url") or (
                    "http://127.0.0.1:%d" % int(
                        ((cfg.get("web") or {}).get("port", 8765)) or 8765))),
            ))
        rt["users"], rt["alerters"] = users, alerters
        return users

    build_runtime()

    # 走势图生成（按航线按用户：各用户以自己的配置画自己的图）
    def charts_fn(fc, tc, d, user=""):
        try:
            from report import prepare_round_charts
            return prepare_round_charts(cfg, logger,
                                        route_override=(fc, tc, d),
                                        user=user)
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
        # 特价订阅保存即触发（r319）：下轮扫描立跑发现，新配置马上见效
        rt["special_force"] = True
        # 同步 webui 的内存引用（否则状态页仍用启动时的旧用户配置）
        try:
            from webui import _State
            _State.users, _State.cfg = rt["users"], cfg
        except Exception:
            pass
        # 节流参数热更新（1–5 区）：只换阈值，保留熔断/令牌桶的既成状态
        # （热改参数不该顺带"赦免"一个刚被限流的渠道）
        try:
            _pac = rt.get("pacing")
            if _pac is not None:
                _pac.refresh(cfg)
                try:
                    from webui import _State as _WS
                    _WS.pacing = _pac
                except Exception:
                    pass
                _pc = _pac.cfg
                logger.info(
                    "[热重载] 节流已更新：快 %.0f/慢 %.0f 分钟 · 静默 %s–%s"
                    " · 错峰 %ds · 熔断 %s（base %ds/cap %ds）",
                    _pc["fast_ttl_min"], _pc["slow_ttl_min"],
                    _pc["scan_quiet_start"] or "关",
                    _pc["scan_quiet_end"] or "关",
                    _pc["stagger_seconds"],
                    "开" if _pc["breaker_enabled"] else "关",
                    _pc["breaker_base_s"], _pc["breaker_cap_s"])
        except Exception as e:
            logger.warning("[热重载] 节流参数更新失败: %s", e)
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
        # 采集代理变化 → 同律清缓存（r319：浏览器/httpx 出口随新代理）
        try:
            new_pxy = str((cfg.get("crawler") or {}).get(
                "proxy", "") or "").strip()
            if new_pxy != rt.get("proxy", new_pxy):
                rt["proxy"] = new_pxy
                if rt.get("clear_crawlers"):
                    rt["clear_crawlers"]()
                    logger.info("[热重载] 采集代理已切换为 %s，爬虫实例下轮"
                                "重建", new_pxy or "直连")
        except Exception as e:
            logger.warning("[热重载] 代理热更新失败: %s", e)
        # Android 通道变化 → 同律清缓存（r629：配置页刚勾上智行 App 时
        # 缓存里已有该渠道实例，它是按启动时「android 为空」建的，会一直
        # 报 runtime not ready: disabled，看起来就是「勾了也不跑」）
        try:
            new_and = dict(cfg.get("android") or {})
            if new_and != rt.get("android", new_and):
                rt["android"] = new_and
                if rt.get("clear_crawlers"):
                    rt["clear_crawlers"]()
                    logger.info("[热重载] Android 通道配置已变更（%s），"
                                "爬虫实例下轮重建",
                                "启用" if new_and.get("enabled") else "关闭")
        except Exception as e:
            logger.warning("[热重载] Android 通道热更新失败: %s", e)
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

            # 控制台「立即扫描」传 force：人工要马上看结果，静默窗不该挡
            start_web(cfg, lambda: sweep(force=True), _report_push, logger,
                      users=rt["users"],
                      alerters=rt["alerters"],
                      reload_cb=reload_config, config_path=str(cfg_path),
                      version=__version__, login_saved_cb=rt["clear_crawlers"])
            try:
                from webui import _State as _WS
                _WS.pacing = rt.get("pacing")
                _WS.warm_cb = rt.get("warm_channel")
                _WS.verify_cb = rt.get("verify_channel")
                _WS.probe_cb = rt.get("probe_channel")
                _WS.scene = rt.get("scene")
            except Exception:
                pass
            rt["web_port"] = int((cfg.get("web") or {}).get("port", 8765))
            rt["headless"] = bool((cfg.get("crawler") or {}).get(
                "headless", True))
            # 采集代理启动态初值（热重载 diff 基准，r319）
            rt["proxy"] = str((cfg.get("crawler") or {}).get(
                "proxy", "") or "").strip()
            # Android 通道启动态初值（热重载 diff 基准，r629）
            rt["android"] = dict(cfg.get("android") or {})
            # 首次使用引导（r653）：没有航线时，用户双击打不开任何东西——
            # 只有一个黑窗口，不知道下一步做什么。主动拉起控制台，
            # 并在终端里写清「打开它 → 加航线 → 勾渠道 → 保存」。
            if not rt["users"]:
                _url = "http://127.0.0.1:%d" % rt["web_port"]
                logger.info("=" * 52)
                logger.info("首次使用：你的浏览器会自动打开配置页")
                logger.info("  1) 在「用户与航线」里添加一条关注航线")
                # 渠道名从单一事实源派生：新增 App 渠道时这句文案自动跟上
                # （写死「含『智行 App』」在接入去哪儿后就不全了）。
                from core.channels import APP_CHANNELS, CHANNEL_CN
                _apps = "「%s」" % "」「".join(
                    CHANNEL_CN[p] for p in APP_CHANNELS)
                logger.info("  2) 勾选要用的渠道（App 渠道：%s 需先在"
                            "「全局参数 · Android 真机通道」启用）", _apps)
                logger.info("  3) 点「保存并生效」，采集即刻开始")
                logger.info("打不开就手动访问：%s", _url)
                logger.info("=" * 52)
                _open_console(_url, logger)
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
        _first_gate = _FirstRunGate(
            lambda: _recent_sweep_age(_anchored(
                (cfg.get("output") or {}).get("db_path"), "data/prices.db")))

        def _first_run():
            """首轮节流（语义见 _FirstRunGate）：仅启动后的首次触发检查。

            同时把 sweep 期间登记的「静默窗结束即唤醒」转交调度器
            （r391）：窗口内跳过轮把秒数写 rt["_wake_at"]，这里落到
            sched_state，_schedule_next 才会把下一轮提前。"""
            try:
                if _first_gate.should_skip():
                    logger.info("[启动] 上轮 %.0f 分钟前已完成，跳过首轮",
                                (_first_gate.last_age or 0) / 60)
                    return
                sweep()
            finally:
                _wake = rt.pop("_wake_at", None)
                if _wake:
                    sched_state["wake_at"] = _wake

        run_scheduler(_first_run, sched_state,
                      run_on_start)  # BlockingScheduler，阻塞至此
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，停止监控")


if __name__ == "__main__":
    # 发行包是 PyInstaller 单文件，双击运行 = 一个控制台窗口。
    # 旧写法 `main()` 一抛异常窗口立刻关闭，用户只看到浏览器
    # 「无法连接服务器 127.0.0.1:8765」（GitHub issue #11 即此形态）：
    # 没有任何线索说明是缺 config.yaml、端口被占、还是依赖缺失。
    # 这里把异常原样打出来并停住，让人能读到真正的原因。
    try:
        main()
    except SystemExit:
        raise
    except BaseException as _e:            # noqa: BLE001 - 入口兜底
        import traceback
        traceback.print_exc()
        try:
            print("\n⚠ 启动失败：%s: %s" % (type(_e).__name__, _e))
            print("   常见原因：config.yaml 缺失或格式错误 / 端口 8765 被占用 /"
                  " 依赖未安装。")
            print("   详细日志见 logs/monitor.log。")
        except Exception:
            pass
        # 双击启动时没有父终端可回看：停住，别让窗口一闪而过。
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\n按回车键关闭…")
        except Exception:
            pass
        raise SystemExit(1)
