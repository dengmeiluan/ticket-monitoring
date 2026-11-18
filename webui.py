# -*- coding: utf-8 -*-
"""伴生本地控制台（多租户版）：纯标准库 HTTP 服务（127.0.0.1），随监控常驻

页面能力：每用户状态卡与仪表 / 多航线可切走势图（canvas 自绘+悬停十字线）/
航班明细表（日期列·筛选·排序·同班跨渠道比价展开）/ 下轮倒计时 /
智能刷新（响应不变不重渲染，页面隐藏暂停）/ 一键立即扫描一轮、一键推送走势报告。
"""
import gzip
import hashlib
import json
import logging
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.storage import PriceStorage
from core.pacing import PLATFORMS
from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER, slot_crawler
from crawlers.base import CHANNEL_GATE, platform_lock, channel_slot
from core.alerter import (Alerter, _qual_price, FLIGGY_TAX_PAD,
                          xchan_phantom_idx, NEAR_RATIO, _append_before_at)
from report import _rounds, recent_platform_flights, _daily_minima

# 仓库根锚定（CWD 漂移免疫家族，与 main._SENT_PATH 同族收口）：
# 与 main 同进程但 db/log/notify 读取曾按 CWD 解析——main 锚定后单向
# 分叉，CWD 漂移时 sqlite3.connect 会在错误路径静默新建空库（写副作用）
_ROOT = os.path.dirname(os.path.abspath(__file__))


def _anchored(p, default):
    """相对路径锚定仓库根（绝对路径原样）。"""
    p = (str(p) if p else "").strip() or default
    return p if os.path.isabs(p) else os.path.join(_ROOT, p)


def _ud_root(cfg=None):
    """`user_data` 根目录（**唯一口径**，绝对路径）。

    `main.py` 注进采集器的 `session_root` 与这里的返回值必须一致——两边都走
    `core.yield_stats.user_data_root()`（config 显式值 > `TM_USER_DATA_DIR` >
    `"user_data"`），本地只做「锚到仓库根」这一步（与 `main._anchored` 同律）。

    **禁止**再用 `_anchored((cfg["crawler"]).get("user_data_dir") or "user_data")`
    自己算一遍（r1063 T10 复核）：那套判据把出厂字面量 `user_data` 当显式
    目录、绕过环境变量层，而 `user_data_root()` 把「显式传默认值」当「没配」
    ——装了 `TM_USER_DATA_DIR` 就**算出两个目录**，界面读/写的资料目录与采集器
    实际用的那个不一致（「界面说没有、其实有」，与 T6 Critical 同一形态、
    方向相反）。

    确实需要「用户在配置里填的那个字面值」的地方（配置页输入框、迁移预案
    展示）请**直接读配置值**，并把本函数的返回值作为「实际生效值」并列
    呈现——两套判据不许各算一份。
    """
    from core.yield_stats import user_data_root
    c = cfg if isinstance(cfg, dict) else (_State.cfg or {})
    return _anchored(user_data_root(c.get("crawler")), "user_data")


def _ud_root_runtime():
    """**运行期**（采集器正在读的那个）根目录。

    `user_data_dir` 是启动级设置：`main.py` 的 `session_root` 在启动时就固定
    并注进每条爬虫，热改要重启才生效（`_effective_crawler_config()` 同理只认
    `boot_cfg`）。所以「按实际资料目录去查文件」的地方（App 登录快照、登录卡
    `saved` 判定）必须读 `boot_cfg`，否则热改后界面去看新目录、采集器还在旧
    目录，又是一次方向相反的分叉。
    """
    boot = _State.boot_cfg if _State.boot_cfg is not None else (_State.cfg or {})
    return _ud_root(boot if isinstance(boot, dict) else None)


# `user_data` 目录在配置里的键名（`core.yield_stats.user_data_root()` 的入参键）。
# 提成常量只为下面 `_ud_abs()` 能拼一份「假如配置这么写」的入参：本文件有一条
# 门禁禁止 `_anchored(...)` 里出现 `user_data_dir` 字面量（那是「自己另判一遍
# 配置语义」的形状），用常量既守住形状，又不必把判据复制一遍。
_UD_KEY = "user_data_dir"


def _ud_abs(raw="", cfg=None):
    """某个**字面值**对应的 `user_data` 实际生效绝对路径（唯一口径）。

    `raw` 是「要展示/要检验的那个字面值」，来源有两个：配置文件里已经写着的，
    或配置页输入框里用户刚敲、还没保存的。两种情况都按「假如配置就写这个值」
    求值，结果与保存重启后 `main.py` 注给爬虫的 `session_root` 一致：

      * 非空且不等于出厂字面量 → 就用它（锚到仓库根）；
      * 空 / `user_data` / `./user_data` 这类**等于出厂值**的写法 → 继续走
        `TM_USER_DATA_DIR`（`user_data_root()` 判「显式传默认值 = 没配」，
        与 `main._session_user_data()` 是同一条规则）。

    为什么不能只把字面值 `_anchored()` 一下（本函数取代的正是那个写法）：
    装了 `TM_USER_DATA_DIR` 时采集器读 env 目录，而只锚字面值会让配置页的
    绝对路径行、存在性徽标、迁移预案统统指向仓库 `user_data/`——「界面说
    没有、其实有」，正是 T6 Critical 的同一形态、方向相反。
    """
    from core.yield_stats import user_data_root
    typed = str(raw or "").strip()
    if not typed:
        base = cfg if isinstance(cfg, dict) else (_State.cfg or {})
        return _ud_root(base)
    return _anchored(user_data_root({_UD_KEY: typed}), "user_data")


def _ud_source(raw="", default="user_data"):
    """`ud` 生效路径的**来源**：`config` / `env` / `default`。

    只为「解释给人看」：用户看到输入框里的 `user_data` 与旁边的绝对路径不是
    同一处，必须能读到「谁把它改掉的」。**路径本身永远由 `user_data_root()`
    算**（见 `_ud_abs`），这里判错的代价只是标签写错，绝不会算出另一个目录。
    """
    typed = str(raw or "").strip()
    dflt = str(default or "user_data").strip() or "user_data"
    if typed and os.path.normpath(typed) != os.path.normpath(dflt):
        return "config"
    return ("env" if (os.environ.get("TM_USER_DATA_DIR") or "").strip()
            else "default")


# open-folder 白名单解析（端点与测试共用单源）：键→config 路径→
# _anchored 仓库根基准→目录化（文件取父目录，不存在则按原字面父路径
# 返回由端点兜底创建）。曾按 __file__ 双层 dirname 手写基准=解析到
# 仓库上级目录还 makedirs 造野目录（用户实报「打开路径错误」根因）
_OPEN_KEYS = {"db": lambda c: str(((c.get("output") or {}).get(
    "db_path", "data/prices.db")) or "data/prices.db"),
    "log": lambda c: str(((c.get("output") or {}).get(
        "log_path", "logs/monitor.log")) or "logs/monitor.log"),
    # 资料目录给**实际生效**的那个（唯一口径）：否则装了 TM_USER_DATA_DIR
    # 时按钮打开的是一个采集器根本不用的目录
    "ud": lambda c: _ud_root(c),
    # bdir 空=playwright 系统默认缓存位（非本仓可控路径）→ None，
    # 端点按「未自定义」回执（打开仓库根是误导，r341）
    "bdir": lambda c: (str(((c.get("crawler") or {}).get(
        "browser_dir", "") or "").strip()) or None),
    # r342：配置文件本体与浏览器默认缓存位（显式键——bdir 空语义不动）
    "cfg": lambda c: os.path.abspath(_State.config_path),
    "bdir_default": lambda c: _playwright_cache_default()}


# 存储四件单源（键 → config 段/键/默认值/类型）。配置页路径卡、
# /api/config storage 与 /api/path-check 共用，防三处手抄漂移。
_STORAGE_SPECS = {
    "db": ("数据库", "output", "db_path", "data/prices.db", "file"),
    "log": ("运行日志", "output", "log_path", "logs/monitor.log", "file"),
    "ud": ("浏览器资料目录", "crawler", "user_data_dir", "user_data", "dir"),
    "bdir": ("浏览器内核目录", "crawler", "browser_dir", "", "dir"),
}


def _playwright_cache_default() -> str:
    """playwright 默认内核缓存位绝对路径（不探测网络、不创建目录）。"""
    p = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    if not p:
        base = (os.environ.get("LOCALAPPDATA") or "").strip()
        p = os.path.join(base, "ms-playwright") if base else os.path.join(
            os.path.expanduser("~"), ".cache", "ms-playwright")
    return os.path.abspath(os.path.expanduser(p))


def _storage_raw(cfg: dict, kind: str) -> str:
    spec = _STORAGE_SPECS.get(kind)
    if not spec:
        return ""
    _label, sec, key, default, _typ = spec
    return str(((cfg or {}).get(sec) or {}).get(key) or default or "")


def _open_file_target(which: str, cfg: dict):
    """键 → 可在默认应用打开的文件绝对路径；目录/未知/缺席返回 None。"""
    if which == "cfg":
        p = os.path.abspath(_State.config_path)
    elif which in _STORAGE_SPECS:
        p = _path_meta(which, _storage_raw(cfg or {}, which), cfg).get("abs")
    else:
        return None
    return p if p and os.path.isfile(p) else None


_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    "COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def _bad_path_reason(abs_p: str) -> str:
    """Windows 目标路径的静态否决项；空串=通过。"""
    # 跨平台：CI 跑 Linux 时 os.path.splitdrive 不识别 D:，会把盘符
    # 误当目录名并因冒号判非法。显式剥离盘符后再逐段检查。
    _p = str(abs_p or "").replace("\\", "/")
    _p = re.sub(r"^[A-Za-z]:", "", _p)
    for part in re.split(r"[\\/]+", _p):
        if not part:
            continue
        if any(ch in part for ch in '<>:"|?*'):
            return "路径含 Windows 不允许的字符（<>:\"|?*）：" + part
        if part != part.rstrip(" ."):
            return "文件名/目录名不能以空格或句点结尾：" + part
        if part.split(".")[0].upper() in _WIN_RESERVED:
            return "使用了 Windows 保留名：" + part
    return ""


def _storage_save_error(cfg: dict) -> str:
    """保存前的四路径总检；空串=通过。

    与 /api/path-check 同源，但独立于前端预览：即便有人绕过 UI 直接
    POST，也不能把非法/同址/不可写路径写进 config.yaml 等重启才炸。
    """
    seen = {}
    for kind in _STORAGE_SPECS:
        label = _STORAGE_SPECS[kind][0]
        m = _path_meta(kind, _storage_raw(cfg or {}, kind), cfg or {})
        if not m.get("ok"):
            return "%s：路径元数据读取失败" % label
        if m.get("invalid"):
            return "%s：%s" % (label, m["invalid"])
        abs_p = m.get("abs") or ""
        if abs_p in seen:
            return "%s与%s不能使用同一路径" % (label, seen[abs_p])
        seen[abs_p] = label
        if m.get("exists") and not m.get("writable"):
            return "%s：目标已存在但不可写，请换一个位置" % label
        typ = _STORAGE_SPECS[kind][4]
        if typ == "file" and m.get("exists") and m.get("is_dir"):
            return "%s指向目录，请填文件路径" % label
        if typ == "dir" and m.get("exists") and not m.get("is_dir"):
            return "%s指向文件，请填目录路径" % label
    return ""


def _path_meta(kind: str, raw: str, cfg: dict = None) -> dict:
    """路径配置 → 可视化元数据（绝对路径/存在性/体积/父目录可写）。

    bdir 空值不代表无效：空=playwright 系统默认缓存位，abs 指默认位
    且 default=True（配置页显示「系统默认」而非空白）。其余键空值
    回落 default 与 _anchored 同律。

    `ud` 例外：它的 `abs` 是**实际生效**目录（唯一口径，见 `_ud_abs`），
    并额外下发 `configured`/`configured_abs`/`effective_abs`/`source`/
    `diverged`，让界面能把「配置里填的」与「实际生效的」并列显示。
    `db`/`log` 是**启动级**键，语义不同（配置改了重启才生效、迁移预览要
    给目标），仍按字面值锚定，不动。"""

    spec = _STORAGE_SPECS.get(kind)
    if not spec:
        return {"ok": False, "err": "未知存储项"}
    label, _sec, _key, default, typ = spec
    typed = str(raw or "").strip()
    is_default = not typed
    # 字面值**单靠自己**会落在哪（不计 `TM_USER_DATA_DIR` 那一层）：只用于
    # 「配置里填的 / 实际生效的」并列展示，不作任何读写判据。
    literal_abs = os.path.abspath(_anchored(typed or default, ""))
    if kind == "bdir" and is_default:
        abs_p = _playwright_cache_default()
    elif kind == "ud":
        # 资料目录走唯一口径（r1063 T10 复核）：`abs` 与「打开资料目录」
        # 按钮（`_OPEN_KEYS["ud"]` → `_ud_root`）、存在性徽标、迁移预案必须
        # 指**同一个目录**，即采集器此刻真正在用的那个。原来这里只把配置
        # 字面值锚成路径，装了 `TM_USER_DATA_DIR` 就与按钮当场互相矛盾：
        # 上面的「→ 绝对路径」说仓库 `user_data/`，点按钮却打开 env 目录。
        abs_p = os.path.abspath(_ud_abs(typed, cfg))
    else:
        abs_p = literal_abs
    exists = os.path.exists(abs_p)
    is_dir = os.path.isdir(abs_p) if exists else typ == "dir"
    size = 0
    mtime = 0
    if exists:
        try:
            # 目录不做递归计量：/api/config 每开一次配置页都遍历
            # 近 4GB 的浏览器缓存会拖慢首屏（实测 300ms+ 竞态），
            # 路径卡对目录只需要存在性与可写性；文件体积照常。
            if os.path.isfile(abs_p):
                size = os.path.getsize(abs_p)
            mtime = int(os.path.getmtime(abs_p))
        except OSError:
            pass
    # 存在目录=自身即父；缺失目录/文件=字面父目录（缺失目录自身不可
    # 当父目录探测，否则「父目录尚不存在」对 user_data_x 恒误报）
    parent = abs_p if (exists and is_dir) else os.path.dirname(abs_p)
    parent_exists = os.path.isdir(parent)
    # 父目录可写探测：只查权限位/尝试等价判断，不创建文件
    parent_writable = False
    if parent_exists:
        try:
            parent_writable = os.access(parent, os.W_OK)
        except OSError:
            parent_writable = False
    # 父目录尚不存在≠不可写：向上找最近已存在的祖先探测权限——
    # 重启时 os.makedirs 会逐级创建；UI 曾把「待创建」误报「不可写」。
    probe = parent
    while probe and not os.path.isdir(probe):
        nxt = os.path.dirname(probe)
        if nxt == probe:
            break
        probe = nxt
    ancestor_exists = bool(probe and os.path.isdir(probe))
    ancestor_writable = False
    if ancestor_exists:
        try:
            ancestor_writable = os.access(probe, os.W_OK)
        except OSError:
            ancestor_writable = False
    creatable = bool((parent_writable if parent_exists else ancestor_writable)
                     and not exists)
    writable = False
    if exists:
        try:
            writable = os.access(abs_p, os.W_OK)
        except OSError:
            writable = False
    elif creatable:
        writable = True
    out = {"ok": True, "kind": kind, "label": label,
           "raw": typed, "abs": abs_p, "type": typ,
           "default": is_default, "exists": bool(exists),
           "is_dir": bool(is_dir), "size": int(size), "mtime": mtime,
           "parent": parent, "parent_exists": bool(parent_exists),
           "parent_writable": bool(parent_writable),
           "creatable": creatable, "writable": bool(writable),
           "invalid": _bad_path_reason(abs_p),
           "ancestor": probe or "", "ancestor_exists": ancestor_exists,
           "ancestor_writable": bool(ancestor_writable)}
    if kind == "ud":
        # 「我填的」与「实际生效的」并列下发（唯一口径的展示面）：
        # 前端两行都画出来，谁也冒充不了谁——只显示其中一个，另一个在用户
        # 眼里就是假的（输入框写着 user_data，路径行却是 env 目录）。
        out.update({
            "configured": typed or default,       # 配置里那个字面值
            "configured_abs": literal_abs,        # 该字面值单靠自己指向的目录
            "effective_abs": abs_p,               # 实际生效（== abs）
            "source": _ud_source(typed, default),  # config / env / default
            "diverged": (os.path.normcase(abs_p)
                         != os.path.normcase(literal_abs)),
        })
    return out



def _storage_view(cfg: dict) -> dict:
    return {k: _path_meta(k, _storage_raw(cfg, k), cfg)
            for k in _STORAGE_SPECS}


_DEMO_ROOT = (r"C:\TicketMonitor" if os.name == "nt"
              else "/opt/ticket-monitor")


def _demo_storage_view() -> dict:
    """演示模式的路径元数据一律指向合成目录，不暴露运行机真实路径。"""
    out = {}
    for kind, (label, _group, _key, default, typ) in _STORAGE_SPECS.items():
        rel = default or "ms-playwright"
        abs_p = os.path.join(_DEMO_ROOT, *rel.split("/"))
        parent = os.path.dirname(abs_p)
        out[kind] = {
            "ok": True, "kind": kind, "label": label, "raw": default,
            "abs": abs_p, "type": typ, "default": True,
            "exists": kind != "bdir", "is_dir": typ == "dir",
            "size": 0 if typ == "dir" else (32768 if kind == "db" else 4096),
            "mtime": 0, "parent": parent, "parent_exists": True,
            "parent_writable": True, "creatable": kind == "bdir",
            "writable": True, "invalid": "", "ancestor": _DEMO_ROOT,
            "ancestor_exists": True, "ancestor_writable": True}
    return out


def _demo_runtime_view() -> dict:
    return {"root": _DEMO_ROOT,
            "config_path": os.path.join(_DEMO_ROOT, "config.yaml"),
            "config_exists": True, "config_size": 1824, "config_mtime": 0,
            "pid": 0, "version": "demo", "listen": "127.0.0.1:8799",
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tz": time.strftime("%Z") or "",
            "argv": ["TicketMonitor.exe", "--demo"], "demo": True}


def _demo_neutral_path(meta: dict) -> dict:
    """把路径预检结果中的运行机根目录替换为演示合成根。"""
    if str(getattr(_State, "version", "")) != "demo":
        return meta
    root = os.path.abspath(_ROOT)
    for key in ("abs", "parent", "ancestor", "current_abs", "from", "to",
                # `ud` 的「配置字面值指向的目录」与「实际生效目录」同样是
                # 运行机真实路径，演示模式必须一并抹成合成根
                "configured_abs", "effective_abs"):
        val = meta.get(key)
        if isinstance(val, str) and val.lower().startswith(root.lower()):
            meta[key] = _DEMO_ROOT + val[len(root):]
    return meta


def _demo_pacing_globals():
    """演示载荷里的节流开关（r628）：与真实分支同源、同默认值。

    只读 `_State.cfg`，不碰磁盘；解析失败时退回与 DEFAULTS 一致的值，
    保证「演示站看到的开关态」与「进程实际行为」一致。
    """
    cfg = _State.cfg or {}
    crw = cfg.get("crawler") or {}
    warm = crw.get("warmup") or {}
    brk = crw.get("breaker") or {}
    try:
        from core.pacing import parse_pacing as _pp
        p = _pp(cfg)
    except Exception:
        p = {}
    return {
        "warmup_enabled": bool(warm.get("enabled", True)),
        "warmup_platforms": ", ".join(
            [x for x in (warm.get("platforms") or p.get("warmup_platforms")
                         or ("qunar", "fliggy", "tuniu"))
             if x in _warmable()]),
        "warmup_ignored": [
            x for x in (warm.get("platforms") or [])
            if x not in _warmable()],
        "warmable": list(_warmable()),
        "breaker_enabled": bool(brk.get("enabled", True)),
        "health_penalty_enabled": bool(
            crw.get("health_penalty_enabled", True)),
        "health_ok_ratio": p.get("health_ok_ratio", 0.7),
        "health_slow_ratio": p.get("health_slow_ratio", 0.4),
        "health_slow_factor": p.get("health_slow_factor", 1.5),
        "health_slowest_factor": p.get("health_slowest_factor", 3.0),
        "health_min_samples": p.get("health_min_samples", 5),
    }


def _demo_config_payload() -> dict:
    """演示 /api/config 与静态演示站共用的单一载荷源。

    配置卡、航线摘要与 state 同源，防止静态站出现「1 条旧航线 / 9 月
    日期」而监控页是 6 条 11 月航线的双源矛盾。
    """
    from core.demo import DEMO_SCAN_PLATS
    from core.demo import demo_routes as _demo_routes
    from wizard import CITY as _CITY_TAB
    return {
        "users": [{
            "name": "演示用户",
            "routes": [
                {"from": r["from"], "from_name": r["from_name"],
                 "to": r["to"], "to_name": r["to_name"],
                 "dates": r["dates"],
                 "alert_direct": r["alert_direct"],
                 "alert_transfer": r["alert_transfer"]}
                for r in _demo_routes()],
            "notifier": {"dingtalk": {"enabled": False},
                         "win_toast": True,
                         "image_host": {"provider": "ghimg",
                                        "repo": "demo/ticket-img"}},
            "platforms": list(DEMO_SCAN_PLATS),
            "specials": [{"enabled": True, "from": "SHA",
                          "from_name": "上海",
                          "max_price": 400, "days": 30}],
        }],
        "city": dict(_CITY_TAB),
        "cityx": _cityx(), "intl": _intl_payload(),
        "airline_alias": _airalias(), "demo": True,
        "globals": {"interval_minutes": 15, "jitter_minutes": 5,
                    "port": int(((_State.cfg or {}).get("web") or {})
                                .get("port", 8765) or 8765),
                    # r628：演示分支原先不回读节流开关，配置页读
                    # `GLB.x !== false`，undefined 一律当「开」——演示站
                    # 会展示与真实行为不符的开关态。
                    **_demo_pacing_globals(),
                    "android": dict((_State.cfg or {}).get("android") or {}),
                    "run_on_start": True, "headless": True,
                    "timeout_seconds": 45, "delay_min": 5, "delay_max": 15,
                    "user_agent": "", "debug": False, "browser_dir": "",
                    "db_path": "data/prices.db",
                    "log_path": "logs/monitor.log",
                    "user_data_dir": "user_data",
                    "globals_abs": {
                        "db": os.path.join(_DEMO_ROOT, "data", "prices.db"),
                        "log": os.path.join(_DEMO_ROOT, "logs", "monitor.log"),
                        "ud": os.path.join(_DEMO_ROOT, "user_data"),
                        "bdir": os.path.join(_DEMO_ROOT, "ms-playwright")}},
        "storage": _demo_storage_view(),
        "restart": {"required": False, "changed": [], "labels": {},
                    "running": {}, "saved": {}},
        "runtime": _demo_runtime_view()}


_EXIT_PROBES = ("https://myip.ipip.net", "https://api.ipify.org?format=json")


def _exit_hist_path():
    return os.path.join("data", "exit_history.json")


def _exit_history():
    try:
        with open(_exit_hist_path(), encoding="utf-8") as f:
            h = json.load(f)
        return [str(x) for x in (h or []) if x][-10:]
    except (OSError, ValueError):
        return []


def _exit_history_push(ip):
    h = _exit_history() + [str(ip)]
    try:
        os.makedirs("data", exist_ok=True)
        with open(_exit_hist_path(), "w", encoding="utf-8") as f:
            json.dump(h[-10:], f)
    except OSError:
        pass


def _proxy_map_clean(pm):
    """按渠道绑出口（r600）的写入清洗：只留合法出口，不healthy的值一律丢弃。

    与全局 `crawler.proxy` 同一套形态校验。这条不是洁癖：漏 scheme 的
    `127.0.0.1:7897` 会让该渠道的 httpx 抛 InvalidURL，而故障表象是
    「这一家渠道全红」——最难归因回配置笔误，所以宁可当成空（跟随全局），
    也不要把脏值落盘。
    空值不落键：proxy_map 里塞空串会让「跟随全局」与「显式直连」两种
    语义混在一起，读配置的人分不清。
    """
    out = {}
    for k, v in (pm or {}).items():
        v = str(v or "").strip()[:300]
        if v and re.match(r"^https?://[^\s/]+:\d+$", v):
            out[str(k)[:40]] = v
    return out


def _app_login_expired(plat: str, hours: int = 24) -> bool:
    """账本证据：最近一次 App 采集是否以「登录失效」收尾。

    快照文件存在 ≠ 会话有效。现场（2026-11-01 21:28 起）：去哪儿 App 快照
    仍标「已保存」，但每轮都停在登录墙——登录卡却写「已保存 · 会话待验证」，
    用户不会去重登。判据取账本最近若干条：先遇到 login/「快照已失效」→ 失效；
    先遇到带行数的 ok → 会话可用。
    """
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        if not os.path.isfile(db):
            return False
        with sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"),
                             uri=True) as c:
            rows = c.execute(
                "SELECT path_status, rows, note FROM fetch_paths "
                "WHERE platform=? AND fetched_at >= datetime('now', ?) "
                "ORDER BY fetched_at DESC LIMIT 20",
                (str(plat or ""), "-%d hours" % int(hours))).fetchall()
        for st, n, note in rows:
            st, note = str(st or ""), str(note or "")
            if st == "login" or "快照已失效" in note:
                return True
            if st == "ok" and int(n or 0) > 0:
                return False
        return False
    except Exception:
        return False


def _enabled_plats():
    """用户采集清单里的渠道（r1624）：不在其中的渠道「没有样本」是正常的。

    读不到就返回 None——**不能返回空集合**：那会把所有渠道都说成"不在清单里"，
    比不说更糟。
    """
    try:
        u = ((_State.cfg or {}).get("users") or [{}])[0] or {}
        pl = u.get("platforms")
        if isinstance(pl, (list, tuple)):
            return set(str(x) for x in pl)
    except Exception:
        pass
    return None


def _retired_reason(plat):
    """该渠道是否已「停服/退役」（r1638）：有就给一句人话，否则空串。

    判据只认账本里**最后一条**记录的原文：`unsupported` 且提到
    「停服」——这正是采集器写下的结论（去哪儿 PC：「网页通路已停服，
    暂停查询」）。有它就不该再提示「去启用」：勾了也不会采。
    """
    try:
        rows = _strategy_storage().recent_paths(str(plat or ""), 1)
    except Exception:
        return ""
    if not rows:
        return ""
    r0 = rows[0] or {}
    note = str(r0.get("note") or "")
    if str(r0.get("path_status") or "") == "unsupported" and "停服" in note:
        return "网页已停服"
    return ""


def _last_seen_of(plat):
    """该渠道**不限窗口**的最近采集样本时刻（r516）。

    窗口口径的 `path_stats.last_at` 在「采集停了很多天」时是空的，
    分不出「新装还没跑」和「跑过但停了」——这两个状态给用户的动作完全
    不同（等一轮 vs 去查采集进程），所以单独查一次全表。
    """
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        if not os.path.isfile(db):
            return ""
        with sqlite3.connect(db) as c:
            row = c.execute(
                "SELECT MAX(fetched_at) FROM fetch_paths WHERE platform=?",
                (str(plat or ""),)).fetchone()
        return str((row or [""])[0] or "")
    except Exception:
        return ""


def _paths_payload(hours=24, demo=False):
    """PC/H5 路径账（可观测）：近 N 小时 渠道×入口 的尝试/成功/拦截。

    「哪条路还能出数」只在账本里有答案——同渠道 PC 92% 而 H5 41% 时，
    要收的是 H5，不是把整家渠道降频。
    """
    hours = max(1, min(24 * 90, int(hours or 24)))
    if demo:
        try:
            from core.demo import demo_health
            plats = _demo_paths_from_rounds(
                (demo_health() or {}).get("rounds") or [])
        except Exception:
            plats = {}
        return {"ok": True, "hours": hours, "platforms": plats,
                "demo": True}
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        if not os.path.isfile(db):
            return {"ok": True, "hours": hours, "platforms": {},
                    "note": "库尚未创建"}
        return {"ok": True, "hours": hours,
                "platforms": PriceStorage(db).path_stats(hours)}
    except Exception as e:
        return {"ok": False, "err": str(e)[:160]}


def _normalize_mc_users(users):
    """保存配置前归一多程航线：2–4 段校验 + 首/末段与日期派生。

    配置页与手改 yaml 共用这一道：非法段在这里拒绝（400），不留到
    下一轮 build_routes 才炸；保存成功后 `/api/config` 回读的 from/to
    与 segments 一致，界面标题不再依赖另一份单 O-D 字段。
    """
    from core.multicity import MultiCityError, normalize_segments
    from wizard import CITY as _CITY
    _rev = {}
    for _n, _c in _CITY.items():
        _rev.setdefault(_c, _n)
    try:
        _intl = (_intl_payload() or {}).get("map") or {}
    except Exception:
        _intl = {}
    for u in users or []:
        for r in (u.get("routes") or []):
            if "segments" not in r:
                continue
            segs = r.get("segments")
            if not segs:
                r.pop("segments", None)
                continue
            try:
                segs = normalize_segments(segs)
            except MultiCityError as e:
                raise ValueError("用户「%s」的多程行程不合法：%s"
                                 % (u.get("name") or "", e))
            r["segments"] = segs
            r["from"] = segs[0]["from"]
            r["to"] = segs[-1]["to"]
            r["dates"] = list(dict.fromkeys(s["date"] for s in segs))
            # 段码是唯一事实源：名称从段码反查，避免改段后沿用旧城市名
            r["from_name"] = _rev.get(r["from"]) or _intl.get(
                r["from"]) or r["from"]
            r["to_name"] = _rev.get(r["to"]) or _intl.get(
                r["to"]) or r["to"]
    return users


def _mc_chain_label(segs):
    """多程链头：段间断点用「/」断开（开口程不画成假闭环）。"""
    segs = list(segs or [])
    if not segs:
        return ""
    out = str(segs[0].get("from") or "")
    prev = out
    for s in segs:
        f = str(s.get("from") or "")
        t = str(s.get("to") or "")
        if f and prev and f != prev:
            out += " / " + f
        out += "→" + t
        prev = t
    return out


def _multicity_history(db_path, segments_key, limit=96):
    """多程整单历史点（只读）：[[ISO 时刻, 总价], ...] 升序。

    表不存在/库未建均返回空；不补点、不拿 latest 伪造历史。
    """
    if not db_path or not os.path.isfile(db_path):
        return []
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace(
            "\\", "/"), uri=True)
        try:
            rows = conn.execute(
                "SELECT fetched_at,total_price FROM itinerary_history "
                "WHERE segments_key=? ORDER BY fetched_at DESC LIMIT ?",
                (str(segments_key), max(1, min(500, int(limit))))
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return []
    return [[str(r[0]).replace(" ", "T"), float(r[1])]
            for r in reversed(rows)]


def _multicity_payload(route_id="", segments_key="", limit=200,
                       demo=None, db_path="", with_history=False):
    """多程整单总价只读视图（route_id / segments_key / limit）。

    只认 `itinerary_daily` 里由渠道页面自报的整单价；GET 不得建库建表，
    所以真库用 mode=ro 打开，老库没有表时按「从未采集多程」返回空，
    由界面区分「没有样本」和「读失败」。
    """
    try:
        limit = max(1, min(500, int(limit or 200)))
    except (TypeError, ValueError):
        limit = 200
    if demo is None:
        demo = bool(DEMO["on"])
    head = {"ok": True, "demo": bool(demo), "route_id": str(route_id or ""),
            "segments_key": str(segments_key or ""), "limit": limit}
    if demo:
        head.update(items=[], count=0, note="演示数据不含多程整单样本")
        return head
    db = db_path or _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")
    if not db or not os.path.isfile(db):
        head.update(items=[], count=0, note="库尚未创建")
        return head
    sql = ("SELECT platform,route_id,segments_key,depart_date,total_price,"
           "legs_json,fetched_at FROM itinerary_daily")
    where, args = [], []
    if route_id:
        where.append("route_id=?")
        args.append(str(route_id))
    if segments_key:
        where.append("segments_key=?")
        args.append(str(segments_key))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY depart_date DESC, fetched_at DESC LIMIT ?"
    args.append(limit)
    conn = sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"),
                           uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            raise
        head.update(items=[], count=0, note="库中尚无多程表（从未采集）")
        return head
    finally:
        conn.close()
    for r in rows:
        try:
            r["extra"] = json.loads(r.pop("legs_json") or "{}")
        except ValueError:
            r["extra"] = {}
        if with_history:
            r["history"] = _multicity_history(
                db, r.get("segments_key") or "")
    head.update(items=rows, count=len(rows))
    return head


def _exit_check(timeout=8.0):
    """出口自检（6 区）：按当前代理取一次公网 IP。

    换热点/重播宽带之后点一下就知道"IP 到底变没变"，不用开浏览器
    对照。只发一次请求，失败如实报错（不重试，避免自检本身变成负担）。
    """
    if DEMO["on"]:
        return {"ok": False, "err": "演示模式不发起外网请求", "proxy": ""}
    proxy = str(((_State.cfg or {}).get("crawler") or {})
                .get("proxy", "") or "").strip()
    last = ""
    for url in _EXIT_PROBES:
        t0 = time.time()
        try:
            import httpx
            r = httpx.get(url, proxy=(proxy or None), timeout=timeout,
                          follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", r.text or "")
            if m:
                ip = m.group(1)
                prev = (_exit_history() or [""])[-1]
                same24 = bool(prev and prev.rsplit(".", 1)[0]
                              == ip.rsplit(".", 1)[0])
                _exit_history_push(ip)
                # 「重播有没有换到新 IP」是本地唯一能自证的换出口手段：
                # 没有第二条宽带时，重播 PPPoE 是唯一可重复的动作
                return {"ok": True, "ip": ip, "via": url,
                        "proxy": proxy, "prev_ip": prev,
                        "changed": bool(prev and prev != ip),
                        "same_subnet": same24,
                        "elapsed_ms": int((time.time() - t0) * 1000)}
            last = "响应里没有可识别的 IP"
        except Exception as e:
            last = str(e)[:140]
    return {"ok": False, "err": last or "检测失败", "proxy": proxy}


def _demo_pacing_payload():
    """演示站只读快照：不接真 Pacing（demo 不起扫描），但要让配置页
    的状态条有东西可渲染，避免"发布出去的演示站写着读取失败"。"""
    from core.pacing import parse_pacing
    pac = parse_pacing(_State.boot_cfg or _State.cfg or {})
    # 演示载荷的渠道清单按真实渠道表派生（r652）：原先写死 5 家浏览器渠道，
    # app_zhixing 整家不出现在演示站节流面板上——而它已经能采集、有登录入口。
    # 来源用 cadence 的键（core.pacing 已把 App 并入），拿不到再退回 REGISTRY。
    _ch = None
    try:
        _ch = [k for k in (pac.get("cadence") or {})]
    except Exception:
        _ch = None
    if not _ch:
        try:
            from crawlers import REGISTRY as _R
            _ch = sorted(_R.keys())
        except Exception:
            _ch = []
    chans = {p: {"state": "ok", "remain_s": 0, "strikes": 0,
                 "reason": "", "needs_login": False,
                 "advice": {"state": "ok", "action": "none",
                            "severity": "ok", "eta_s": 0,
                            "hint": "演示数据，无需操作"}}
             for p in _ch}
    return {"ok": True, "cfg": pac,
            "quiet": {"start": pac["scan_quiet_start"],
                      "end": pac["scan_quiet_end"], "active": False},
            "channels": chans, "bucket": {},
            "last_round": {"at": "", "fast": 6, "slow": 2, "skip": 3,
                           "trips": [], "busy": []},
            "plan": []}


def _startup_vals(cfg: dict) -> dict:
    """启动级四键的**生效绝对路径**（运行态重启差量与迁移预览共用）。

    r342：按字面值比较会把「显式写默认值」误判为需重启；统一锚定
    绝对路径后，默认/显式默认等价，且重启中心展示的是用户可核对的
    真实落点。bdir 空=渠道默认位（不进重启差量）。"""
    defaults = {"db_path": "data/prices.db",
                "log_path": "logs/monitor.log",
                "user_data_dir": "user_data"}
    out = {}
    for k in ("db_path", "log_path", "user_data_dir", "browser_dir"):
        if k in ("db_path", "log_path"):
            raw = str(((cfg or {}).get("output") or {}).get(k) or "")
        else:
            raw = str(((cfg or {}).get("crawler") or {}).get(k) or "")
        if k == "browser_dir":
            out[k] = os.path.abspath(_anchored(raw, "")) if raw.strip() else ""
        elif k == "user_data_dir":
            # 资料目录同样走唯一口径（r1063 T10 复核）：重启差量与迁移预案
            # 比较的必须是**生效目录**。只锚字面值时，装了 `TM_USER_DATA_DIR`
            # 的机器上这里报仓库 `user_data/`，而采集器实际读 env 目录——
            # 「重启中心说没变、实际变了」与「配置页路径行」同一处错。
            out[k] = os.path.abspath(_ud_abs(raw, cfg))
        else:
            out[k] = os.path.abspath(_anchored(
                raw.strip() or defaults[k], defaults[k]))

    # r345：监听地址与启动即扫同样是启动级——保存后进程未重启不会生效，
    # 旧重启中心只列四路径，UI 的 ♻ 徽标因此悬空。
    # r675：取**生效值**而非文件字面值——容器内 host 缺省时生效的是
    # TM_WEB_HOST；拿文件缺省 127.0.0.1 比较会造出「保存后永远差一项」的
    # 假待重启，也会让配置页把错误值写回文件。
    out["host"] = _bind_host(cfg or {})
    out["run_on_start"] = bool(
        ((cfg or {}).get("schedule") or {}).get("run_on_start", True))
    return out


def _runtime_view(demo: bool = False) -> dict:
    """运行时身份（配置页透明化）：程序根/配置文件绝对路径/PID/版本/
    配置文件体积与修改时间——「我现在跑的是哪份配置」一屏可核对。"""
    p = os.path.abspath(_State.config_path)
    size, mtime, exists = 0, 0, os.path.isfile(p)
    if exists:
        try:
            size = os.path.getsize(p)
            mtime = int(os.path.getmtime(p))
        except OSError:
            pass
    return {"root": os.path.abspath(_ROOT), "config_path": p,
            "config_exists": bool(exists), "config_size": int(size),
            "config_mtime": int(mtime), "pid": os.getpid(),
            "version": str(getattr(_State, "version", "") or ""),
            "listen": str(getattr(_State, "listen", "") or ""),
            "started_at": str(getattr(_State, "started_at", "") or ""),
            "tz": time.strftime("%Z") or "",
            "argv": list(sys.argv),
            "demo": bool(demo)}


def _restart_view(file_cfg: dict) -> dict:
    """当前 config.yaml vs 进程启动时配置：已保存但重启后才生效的键。

    这是「重启可视化」的单源——保存后刷新页面仍能看到待重启项，
    不再依赖前端 GLB_CLEAN 的单会话差量。"""
    # 比较基准必须是进程启动快照而非热重载后的 _State.cfg：保存配置
    # 会热重载内存引用，用当前引用比较会把「已保存待重启」瞬间抹平
    running = _startup_vals(
        getattr(_State, "boot_cfg", None) or _State.cfg or {})
    saved = _startup_vals(file_cfg or {})
    changed = [k for k in running if running[k] != saved[k]]
    labels = {"db_path": "数据库", "log_path": "运行日志",
              "user_data_dir": "浏览器资料目录",
              "browser_dir": "浏览器内核目录",
              "host": "控制台监听地址",
              "run_on_start": "启动即扫"}
    return {"required": bool(changed), "changed": changed,
            "labels": {k: labels[k] for k in changed},
            "running": running, "saved": saved}


def _open_folder_target(which, cfg):
    """键 → 应在资源管理器中打开的目录绝对路径；白名单外返回 None。"""
    fn = _OPEN_KEYS.get(which)
    if not fn:
        return None
    v = fn(cfg or {})
    if not v:
        return None
    p = _anchored(v, "")
    return p if os.path.isdir(p) else os.path.dirname(p)


# 演示模式（python webui.py --demo）：/api/* 走合成数据，POST 全部只读拦截
DEMO = {"on": False}


def _dur_min(txt) -> int:
    """'5时25分'/'5小时25分'/'5h25m' → 分钟数；解析不出返回 0。"""
    m = re.match(r"\s*(\d+)\s*(?:小时|[时hH])\s*(?:(\d+)\s*分?m?)?", str(txt or ""))
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


def _load_asset(name: str) -> str:
    """前端模板资产与源码解耦：字节级原样读取，禁止任何改写。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui_assets", name)
    with open(path, "rb") as _f:
        return _f.read().decode("utf-8")


PAGE = _load_asset("page.html")


NOTIFY_PAGE = _load_asset("notify.html")


def _no_graphical_env() -> bool:
    """当前进程是否确定没有图形环境（Docker / 无 X 的 Linux）。

    单源：登录窗口能不能弹出，只看这一处。测试改为替换本函数，
    不必再用 monkeypatch 去改进程级 `os.environ.get`——那会把补丁
    泄漏给同进程的其它用例（实测让 `_bind_host` 读到被替换的 get，
    容器监听地址门禁在 CI 上假红）。

    #14：macOS 是 posix，但窗口系统走 Quartz/Cocoa，没有 DISPLAY /
    WAYLAND_DISPLAY。旧判据把 macOS 原生包一律判成无图形环境，
    网页里点「渠道登录」得到 no_gui；同一台 Mac 上命令行
    `--login` 却能弹窗。无头判定只对 Linux 成立。
    """
    # `TM_FORCE_GUI=1`：用户明知有桌面却被判无头时的出口（GitHub #14 场景）
    if str(os.environ.get("TM_FORCE_GUI") or "").strip() in ("1", "true",
                                                            "yes", "on"):
        return False
    return (sys.platform.startswith("linux")
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY"))


def _bind_host(cfg: dict) -> str:
    """监听地址解析单源：config web.host 显式值最优先；缺席/空时
    TM_WEB_HOST 环境变量出口（Docker 镜像内置 0.0.0.0——容器内服务
    绑回环时 -p 端口映射不可达：CI 冒烟 curl 与 NAS compose 双双
    不可达实录）；都无=127.0.0.1（非容器默认行为不变）。"""
    v = str((cfg.get("web") or {}).get("host", "") or "").strip()
    if v:
        return v
    return os.environ.get("TM_WEB_HOST") or "127.0.0.1"


def _cityx():
    """城市面板扩展数据（r320 全量城市化）：拼音首字母分组/全拼/
    热门组——配置页城市选择面板的搜索与字母导航数据源。city 键
    （名→码 dict）保持原形零回归，扩展字段走独立 cityx 键。
    国际城拼音随 r326 并入两表（「国际」页签三路搜索同权）。"""
    from core.citydata import CITY_HOT, CITY_NPY, CITY_PY
    from core.intl import INTL_CITY_NPY, INTL_CITY_PY
    return {"py": {**CITY_PY, **INTL_CITY_PY},
            "npy": {**CITY_NPY, **INTL_CITY_NPY},
            "hot": CITY_HOT}


def _airalias():
    """航司别称字典下发（r339h 用户实报「东航 vs 东方航空」）：与
    alerter 白名单/排除匹配同源（core.airlines），前端白名单输入的
    实时解析预览用。"""
    from core.airlines import alias_payload
    return alias_payload()


def _intl_payload():
    """国际城市面板数据（r325，INTL_DESIGN §3）：码→展示名 map（配
    置页国际页签与名称→码回填）、热门序、大陆码全集（前端
    isIntlCode「国际」徽标判定单源——与 core.intl 同源下发）。"""
    from core.intl import (INTL_CITY_HOT, INTL_CITY_NAME,  # noqa: E402
                           INTL_REGION, INTL_REGIONS,
                           MAINLAND_CODES)
    return {"map": INTL_CITY_NAME, "hot": INTL_CITY_HOT,
            "region": INTL_REGION, "regions": INTL_REGIONS,
            "mainland": sorted(MAINLAND_CODES)}


_TREND_DAYS = (30, 90, 180)   # 长窗档位单源（前端 chips 与钳制同源）


def _trend_route_ok(parts, lo, platform, route):
    """长窗日桶的航线条件门：flight_daily 只有 flight_key/lo/platform，
    能判的维度按与短窗/列表同一语义过滤；判不了的维度（舱位是否廉航、
    行李额、机型）不伪造。flight_key 已含中转/跨天/经停/起降时刻。"""
    if not route:
        return True

    def _g(k):
        if isinstance(route, dict):
            return route.get(k)
        return getattr(route, k, None)

    if _g("direct_only") and len(parts) > 6 and parts[6]:
        return False
    if _g("exclude_stop") and len(parts) > 8 and parts[8] == "1":
        return False
    if _g("no_cross") and len(parts) > 7 and parts[7]:
        return False
    for lo_k, hi_k, idx in (("dep_time_min", "dep_time_max", 4),
                            ("arr_time_min", "arr_time_max", 5)):
        val = str(parts[idx] if len(parts) > idx else "")
        if not re.match(r"^\d{1,2}:\d{2}$", val):
            continue
        _m = lambda s: (int(s.split(":")[0]) * 60 + int(s.split(":")[1]))
        v = _m(val)
        lo_v, hi_v = _g(lo_k), _g(hi_k)
        if lo_v and re.match(r"^\d{1,2}:\d{2}$", str(lo_v)) and v < _m(str(lo_v)):
            return False
        if hi_v and re.match(r"^\d{1,2}:\d{2}$", str(hi_v)) and v > _m(str(hi_v)):
            return False
    _al = str(_g("airlines") or "").replace("，", ",")
    if _al.strip():
        _want = [x.strip().upper() for x in _al.split(",") if x.strip()]
        _ban = [x[1:].strip() for x in _want if x.startswith("!") and x[1:].strip()]
        _allow = [x for x in _want if not x.startswith("!")]
        _code = str(parts[2] if len(parts) > 2 else "").upper()
        if _ban and any(b in _code for b in _ban):
            return False
        if _allow and not any(a in _code for a in _allow):
            return False
    try:
        _pmax = float(_g("price_max") or 0)
    except (TypeError, ValueError):
        _pmax = 0
    if _pmax and float(lo) > _pmax:
        return False
    _ch = _g("channels")
    if isinstance(_ch, list) and _ch and platform not in _ch:
        return False
    return True


def _trend_from_flights(st, from_city, to_city, depart_date, days,
                        route=None):
    """长窗航线日桶：优先用 flight_daily（仅真实航班，已排除日历薄行）。

    同一采集日按直飞/中转聚合所有航班级桶：lo=当日最低、hi=当日最高，
    open/close 取当日首末航班级桶（按 fetched_max）。没有航班级日桶时
    返回 None，由调用方回退 price_daily（该池含日历价，必须在 UI 标注）。
    """
    with st._conn() as c:
        rows = c.execute(
            "SELECT day, flight_key, platform, lo, hi, open, close, fetched_max "
            "FROM flight_daily WHERE from_city=? AND to_city=? "
            "AND depart_date=? AND day>=date('now','localtime',?) "
            "ORDER BY day, fetched_max, flight_key",
            (from_city, to_city, depart_date, "-%d days" % days)).fetchall()
    if not rows:
        return None
    groups = {}
    for r in rows:
        try:
            lo, hi = float(r["lo"]), float(r["hi"])
        except (TypeError, ValueError):
            continue
        parts = str(r["flight_key"] or "").split("|")
        if not _trend_route_ok(parts, lo, str(r["platform"] or ""), route):
            continue
        kind = "t" if len(parts) > 6 and parts[6] else "d"
        groups.setdefault((r["day"], kind), []).append((lo, hi, r))
    out = {"d": [], "t": []}
    for (day, kind), gs in sorted(groups.items()):
        los = [x[0] for x in gs]; his = [x[1] for x in gs]
        first, last = gs[0][2], gs[-1][2]
        try:
            op = float(first["open"])
        except (TypeError, ValueError):
            op = los[0]
        try:
            cl = float(last["close"])
        except (TypeError, ValueError):
            cl = his[-1]
        out[kind].append([day, min(los), 0, op, cl, max(his)])
    if not (out["d"] or out["t"]):
        return None
    return {"direct": out["d"], "transfer": out["t"]}


def _trend_payload(q: dict) -> dict:
    """/api/trend 组装（r320b 半年走势）：长窗日桶双系列（direct/
    transfer，pts 与 history 同构 [MM-DD, lo, flag]——前端渲染管线
    零改）。days 白名单钳到最近合法档（30/90/180）；缺参拒绝。
    读前惰性刷新今日桶（防长期不开控制台漏桶）。"""
    frm = (q.get("from") or [""])[0].strip().upper()
    to = (q.get("to") or [""])[0].strip().upper()
    date = (q.get("date") or [""])[0].strip()
    if not (frm and to and date):
        return {"ok": False, "err": "缺少 from/to/date 参数"}
    try:
        days = int((q.get("days") or ["180"])[0])
    except ValueError:
        days = 180
    days = min(_TREND_DAYS, key=lambda d: (abs(d - days), -d))
    try:
        th = float((q.get("th") or ["0"])[0])
    except ValueError:
        th = 0.0

    def _qv(k):
        return str((q.get(k) or [""])[0] or "").strip()

    rf = {}
    if _qv("rdirect") in ("1", "true", "on"):
        rf["direct_only"] = True
    if _qv("rnostop") in ("1", "true", "on"):
        rf["exclude_stop"] = True
    if _qv("rnocross") in ("1", "true", "on"):
        rf["no_cross"] = True
    if _qv("rairlines"):
        rf["airlines"] = _qv("rairlines")
    if _qv("rdepmin"):
        rf["dep_time_min"] = _qv("rdepmin")
    if _qv("rdepmax"):
        rf["dep_time_max"] = _qv("rdepmax")
    if _qv("rarrmin"):
        rf["arr_time_min"] = _qv("rarrmin")
    if _qv("rarrmax"):
        rf["arr_time_max"] = _qv("rarrmax")
    try:
        _rpmax = float(_qv("rpmax") or 0)
    except ValueError:
        _rpmax = 0
    if _rpmax > 0:
        rf["price_max"] = _rpmax
    _rch = [x.strip() for x in _qv("rchannels").split(",") if x.strip()]
    if _rch:
        rf["channels"] = _rch
    if _State.cfg is not None:
        # 数据源与 /api/state 同源（_State.cfg 单一事实源）——本函数
        # 初版读 config_path，demo 态从未设置该路径，会读穿真实
        # config.yaml→生产 DB（r323 P1-1）
        _db = _anchored(((_State.cfg or {}).get("output") or {}).get("db_path"),
                        "data/prices.db")
    else:
        import yaml as _y
        with open(_State.config_path, encoding="utf-8") as _yf:
            _cfg = _y.safe_load(_yf) or {}
        _db = _anchored((_cfg.get("output") or {}).get("db_path"),
                        "data/prices.db")
    st = PriceStorage(_db)
    try:
        st.refresh_daily(frm, to, date)
        fd = _trend_from_flights(st, frm, to, date, days, route=rf or None)
        if fd:
            return {"ok": True, "days": days, "basis": "flight_daily",
                    "filtered": bool(rf),
                    "direct": fd["direct"], "transfer": fd["transfer"]}
        if rf:
            # 有航线条件但无航班级日桶：日历池无法按直飞/航司/时段过滤，
            # 宁可不画，也不把未过滤的日历最低价冒充本航线曲线。
            return {"ok": True, "days": days,
                    "basis": "flight_daily_filtered_empty",
                    "filtered": True, "direct": [], "transfer": [],
                    "note": "长窗无航班级日桶，且航线条件无法套用到日历池；未用日历价替代"}
        d = st.daily_series(frm, to, date, days=days, th_d=th, kind="d")
        t = st.daily_series(frm, to, date, days=days, th_d=th, kind="t")
        basis = "price_daily_calendar"
    except Exception as e:
        return {"ok": False, "err": str(e)}
    # 航线级日桶含日历价（前端图例已注明）：价格可展示，但不能把
    # 日历最低价标成「真达标」——flag 一律 0，只保留价格与目标线。
    # 航班级达标由明细/关注台（flight_daily）承担。
    # 日桶是预聚合 OHLC：一并下发开/收/高，K线不再把单日 lo 复制成
    # 开=收=高=低（假 K 线曾与图注「开/收=当日首末价」矛盾）。
    pts = lambda rows: [[r["day"], r["lo"], 0, r["open"], r["close"],
                         r["hi"]] for r in rows]
    return {"ok": True, "days": days, "basis": basis,
            "direct": pts(d), "transfer": pts(t)}


class _State:
    cfg = None
    boot_cfg = None   # 进程启动快照（重启差量基准，热重载不覆盖）
    users = None
    alerters = []     # 与 users 对齐；雷达降价提醒复用用户通知通道
    pacing = None     # 节流/熔断上下文（main 挂接；/api/pacing 只读快照）
    warm_cb = None    # 手动预热回调（main 挂接；可干预入口）
    verify_cb = None  # 弹出验证窗口回调（main 挂接；人工过验证）
    scene = None      # 案发现场（main 挂接；被拦 URL/证据/验证后探测）
    # 采集运行时容器（r1063 T6）：「中断本轮」改的是它的 `_round_gen`——
    # worker 每个检查点拿自己捕获的代际与它比，不等就收工。main 挂接一句
    # `_State.rt = rt` 即可；未挂接时 `_runtime_rt()` 会按任务回调的闭包找一次。
    rt = None
    probe_cb = None   # 渠道自检回调（main 挂接；单查询跑完整链路）
    # 解除中的渠道（r480）：解除后会立刻单查探测，并发第二次请求会再跑
    # 一次并覆盖结果。前端只挡同页连点，跨标签页必须在这里兜住。
    reset_open = set()
    # 闸门锁（r481）：判断与占位必须原子。Handler 是多线程并发的，
    # 先判断再占位会让两个标签页同时通过（负控实测：插入让出点即双跑探测）。
    reset_lock = threading.Lock()
    # App 渠道登录会话（r604）：与浏览器登录的 login_sessions 并列，
    # 但载体不同——那边是 Playwright 窗口，这边是 adb 帧流。
    app_login = None   # 惰性创建 AppLoginRegistry
    login_sessions = {}   # plat -> {"evt": Event}（进行中的网页登录窗口）
    login_errors = {}    # plat -> 最近一次登录保存失败的安全摘要
    login_saved_cb = None  # 登录保存后清理采集器缓存
    login_pending = {}    # plat -> finish 时刻（保存→下轮采集验证的过渡窗，
    #                          窗内卡片词面「验证中」不再说「建议重登」——
    #                          刚点完登录就被建议重登是词面自相矛盾）
    job = None
    report_push = None
    reload_cb = None
    config_path = "config.yaml"
    version = ""
    listen = ""
    started_at = ""
    logger = logging.getLogger("ticket-monitor")
    lock = threading.Lock()


# ── 策略控制：人工停手 / 恢复 / 中断本轮（r1063 T6）──────────────────
#
# 三个动作共用一条纪律：**出错不许变成 500 堆栈**。前端 `fetch` 拿到的是
# 「请求失败」，看不出是磁盘满了、参数写错了还是运行时没挂接——而停手是
# 安全动作，操作员必须知道它到底有没有生效。所以实现在下面这三个模块级
# 函数里（返回 `(HTTP 码, 响应体)`），路由分支只做搬运与兜底。
#
# 三族的语义（台账同族分界见 `core/storage.py`）：人工干预（probe/relogin/
# reset…）、自动事件（auto_*）、**策略变更（strategy_*，本族）**。
# 策略变更既不是「人救了一次」也不是「程序自己跳闸」，它是参数被改了——
# 因此不进人工干预的成功率分母，也不当人工干预的前后对比分界。


def _profile_of(plat):
    """某渠道**资料目录名**（＝采集器决策时用的 `profile`）。

    口径只有一份，在 `core/policy.py::profile_of`（`profile_name or name`）：
    **绝不能图省事写成 `profile=plat`**（复核 2026-11-06 Critical）——
    `crawlers/fliggy_h5.py::FliggyH5Crawler` 的 `name="fliggy"` 而
    `profile_name="fliggy_h5"`，写成 plat 就会把停手写进一个没人读的目录。

    r1063 T18 起这里**代理**到 `core.policy.profile_of`，不再自己抄一份：
    停手的写侧（webui）与读侧（`main.py` 注入给 `gate_path` 的读点）必须
    同源，否则会出现「界面说到点了、采集器还在跑」。爬虫包不可用时那边按
    原值兜底，这里不再重复兜底逻辑。
    """
    try:
        from core.policy import profile_of as _pf
        return _pf(plat)
    except Exception:
        return str(plat or "").strip()      # 极端兜底：按原值，别把停手写丢


def _policy_engine(plat=""):
    """某渠道对应的策略引擎（定位 `strategy_halt.json` 与自动状态）。

    `base_dir` = `_ud_root(_State.boot_cfg)/profile`——**profile 必须传**
    （见 `_profile_of`），否则停手落到 `user_data/` 而采集器读
    `user_data/<profile>/`，界面说「已停手」、采集照跑。

    根目录走**唯一口径** `_ud_root()`（r1063 T10）：原先这里自己判「字面量
    `user_data` 就当没配 → pop 掉让环境变量接管」，而 `main.py` 把同一份
    配置锚成仓库绝对路径注进爬虫——两边各算一遍，装了 `TM_USER_DATA_DIR`
    就**算出两个目录**：停手写进 A、采集器只读 B（T6 Critical 往深一层）。

    而且必须是 `boot_cfg`（**运行期**那一份，见 `_ud_root_runtime()`）：
    `_State.cfg` 是热重载后的新值，`user_data_dir` 却要重启才生效，重启前
    采集器仍在 boot 的目录里读写——拿 cfg 会让停手落到一个「界面以为已生效、
    采集器没在读」的目录，同一形态再犯一次。
    """
    from core.policy import default_engine
    cfg = dict(_State.cfg or {})
    cfg["user_data_dir"] = _ud_root_runtime()
    return default_engine(cfg, repo_root=_ROOT, profile=_profile_of(plat))


def _strategy_storage():
    """干预账本（停手/恢复/中断的痕迹都记在这本账上）。"""
    from core.storage import PriceStorage
    return PriceStorage(_anchored(
        ((_State.cfg or {}).get("output") or {}).get("db_path"),
        "data/prices.db"))


# ── 策略目录只读接口（r1063 T12a）──────────────────────────────────────
#
# `GET /api/strategy`（Spec §6(c)）：目录 + 当前生效值 + 来源 + 十五轴矩阵
# + 停手表。**只读**——参数编辑仍走 `POST /api/config` 的 `glb` 整表，停/恢复
# 走 `/api/strategy/{halt,resume}`。这个接口不写任何东西，也不许长成第二个写
# 路径：写路径只有一个，界面上的「保存」永远整表 POST 回 `/api/config`。


def _strategy_param_rows(strategy):
    """一条策略的参数生效值：`[{pid, value, source, default, lo, hi}]`。

    值一律问 `core.strategy_params.resolve()`（**唯一求值入口**）：界面上显示的
    数字必须与闸门决策时用的是同一个数，这里自己再读一遍 cfg 就会出现「显示 3、
    按 5 跑」——那正是本项目把「配了不生效」列为头号缺陷的原因。

    单参数求值炸了只让那一行退回声明的默认值并带上 `err`：整条策略从面板上
    消失会让用户以为这条策略不存在（实际上它只是某个键读不出来）。
    """
    try:
        from core import strategy_params as _sp
    except Exception as _ie:          # 参数层不可用：如实标在每一行上，别装作没参数
        # `cfg` / `kind` 是 T12b 的渲染器要用的：控件 id 由 cfg 点路径派生
        # （`crawler.policy.pace.watch` → `glbPaceWatch`），控件形态由 kind
        # 决定（数字框 / 开关 / 文本框）。目录里本来就有这两项，只是此前
        # 没售出——界面若自己猜「这是不是数字」，猜错就画错控件。
        return [{"pid": p.pid, "cfg": p.cfg, "kind": p.kind,
                 "value": p.default, "source": "default",
                 "default": p.default, "lo": p.lo, "hi": p.hi,
                 "err": "参数层不可用：%s" % str(_ie)[:60]}
                for p in strategy.params]
    rows = []
    for p in strategy.params:
        try:
            got = _sp.resolve(p.pid)
            rows.append({"pid": p.pid, "cfg": p.cfg, "kind": p.kind,
                         "value": got.value,
                         "source": got.source, "default": p.default,
                         "lo": p.lo, "hi": p.hi})
        except Exception as _pe:
            rows.append({"pid": p.pid, "cfg": p.cfg, "kind": p.kind,
                         "value": p.default, "source": "default",
                         "default": p.default, "lo": p.lo, "hi": p.hi,
                         "err": "求值失败（界面显示的是目录默认值）：%s"
                                % str(_pe)[:80]})
    return rows


def _strategy_tip(strategy):
    """这条策略**此刻的下一步**：`{action, text, route}`（r1063 T12c）。

    来源只有一个：`core/strategy_advice.advise()`（按策略分化，不是 28 条同一
    句）。`route` 是动作码对应的**真实路由**（`/api/run`、`/api/strategy/resume`
    …），界面据此显示动作名；空串表示「只建议、无执行入口」（换身份要人决定）。
    建议器炸了只让这一行没有建议，不许把整条策略行带没——所以这里吞异常并给
    一句可读的兜底，原因进 `err`。
    """
    try:
        from core import strategy_advice as _sa
        got = _sa.advise(strategy.id, {})
        return {"action": str(got.get("action") or "none"),
                "text": str(got.get("text") or ""),
                "route": _sa.route_of(str(got.get("action") or ""))}
    except Exception as _ae:          # 建议器不可用：如实标一行，不装作没问题
        return {"action": "none", "text": "",
                "route": "", "err": "建议器不可用：%s" % str(_ae)[:60]}


# 覆盖层级的「深度」：数值越大越靠近现场（顺序与
# `core/strategy_params._lookup_keys` 的查找链一致：渠道 → 维度 → 链路）。
# 健康卡策略条靠它分清「自动处置中（全局调过）」与「已按渠道覆盖」——
# 两者在界面上必须是两种底色，否则用户看不出是谁说了算（Spec 附录 C）。
_STRAT_LAYER_DEEP = {"global": 1, "channel": 3, "dimension": 4, "path": 5}


def _strategy_halt_owner():
    """「人工停手」这条窗口归目录里哪条策略管（pid 形如 `block_window.*`）。

    芯片要能点回配置页的对应策略行，所以 id 必须从目录派生——在界面或这里
    写死一个 `block_window` 字面量就是第二份声明（目录改名后界面会指向一条
    不存在的行）。目录里找不到就返回空字典，界面据此不出跳转，绝不编一个。
    """
    from core.strategy_contract import STRATEGIES as _STS
    for s in _STS:
        for p in s.params:
            if str(p.pid).split(".")[0] == "block_window":
                return {"id": s.id, "label": s.label}
    return {}


def _strategy_channel_tip(rows, halt, plat):
    """本渠道此刻的**建议**：`{id, action, text, route}` 或 `None`。

    文案只有一个来源：`core.strategy_advice.advise()`（与 `/api/strategy` 的
    `tip` 同一个建议器、同一套动作码）。这里只负责回答「先劝哪一条」：

    * 人工停手中 → 劝恢复（人刚按下的动作，下一步就是放行）；
    * 否则 → 劝本渠道覆盖/已停用的第一条（`rows` 已按 cover 优先排好）；
    * 一条非默认策略都没有 → `None`：界面不出建议行，也不编一句「一切正常」。
    """
    if halt:
        sid, ctx = halt.get("id"), {"halt": True}
    elif rows:
        sid = rows[0].get("id")
        ctx = {"enabled": bool(rows[0].get("enabled", True))}
    else:
        return None
    if not sid:
        return None
    try:
        from core import strategy_advice as _sa
        got = _sa.advise(sid, ctx)
        act = str(got.get("action") or "none")
        return {"id": sid, "action": act, "text": str(got.get("text") or ""),
                "route": _sa.route_of(act)}
    except Exception:
        return None


def _strategy_strip_rows(plats=(), halts=None):
    """每渠道「策略条」的行数据（Spec §6(b)）：`{plat: {...}}`。

    只挑两类，其余**不占屏幕**（28 条 × 10 家的笛卡尔积糊上去等于没有信息）：

    * **非默认**：该渠道求值出来的来源不是 `default`（全局也算——用户真改过）；
    * **本渠道覆盖**：来源落在渠道/维度/链路层 → `state="cover"`（换底色）。

    返回值每个渠道三段：

    * `strategies`：`[{id, label, src, state, enabled}]`，`cover` 排在前面
      （「谁说了算」先露），最多由界面裁到 6 颗；
    * `halt`：**人工停手生效中**才给 `{id, label, until, left_s}`——这是运行期
      状态（不写配置），与熔断的自动冷却在界面上必须是两种颜色；
    * `tip`：本渠道此刻该动的那一条（见 `_strategy_channel_tip`）。

    `label` 直出目录里的那 20 字：界面不许自己拼策略名，也不许拼 id。
    """
    from core import strategy_params as _sp
    from core.strategy_contract import STRATEGIES as _STS

    halt_owner = _strategy_halt_owner()
    halts = halts if isinstance(halts, dict) else {}
    out = {}
    for plat in tuple(plats or ()):
        rows = []
        for s in _STS:
            depth, src, enabled = 0, "default", True
            for p in s.params:
                try:
                    got = _sp.resolve(p.pid, plat=plat)
                except Exception:
                    continue            # 单个参数读不出：不让整条策略从条上消失
                if str(p.pid) == (s.id + ".enabled"):
                    enabled = bool(got.value)
                gsrc = str(got.source or "default")
                deep = _STRAT_LAYER_DEEP.get(gsrc, 0)
                if gsrc != "default" and deep >= depth:
                    depth, src = deep, gsrc
            if depth <= 0:
                continue                # 全默认：这条策略此刻不占用户屏幕
            rows.append({"id": s.id, "label": s.label, "src": src,
                         "state": ("cover" if depth >= 3 else "auto"),
                         "enabled": enabled})
        rows.sort(key=lambda r: 0 if r["state"] == "cover" else 1)
        rec = halts.get(plat) or {}
        try:
            left = int(rec.get("left_s") or 0)
        except (TypeError, ValueError):
            left = 0
        halt = None
        if left > 0 and halt_owner.get("id"):
            try:
                until = float(rec.get("until") or 0)
            except (TypeError, ValueError):
                until = 0.0
            halt = {"id": halt_owner["id"],
                    "label": str(halt_owner.get("label") or ""),
                    "until": until, "left_s": left}
        out[plat] = {"strategies": rows, "halt": halt,
                     "tip": _strategy_channel_tip(rows, halt, plat)}
    return out


# 十五轴矩阵缓存（r1063 T44）：`audit()` 实测 2.75s/次，而面板每次打开/保存/
# 停手都会重新拉 `/api/strategy`——不缓存的话用户感受就是"点一下卡三秒"。
# 失效条件：参数层换了一份配置对象，或 `_State.cfg` 换了对象（保存/热重载）。
_STRAT_AUDIT_CACHE = {"sig": None, "rows": None, "matrix": None}


def _strategy_audit_cached():
    """`(rows, matrix)`，按配置对象身份缓存。返回的两者一起用，别只拿一个。"""
    from core import strategy_contract as _strat
    try:
        from core import strategy_params as _sp
        _cfg_obj = getattr(_sp, "_CFG", None)
    except Exception:
        _cfg_obj = None
    sig = (id(_cfg_obj), id(getattr(_State, "cfg", None)))
    if (_STRAT_AUDIT_CACHE.get("sig") == sig
            and _STRAT_AUDIT_CACHE.get("rows") is not None):
        return _STRAT_AUDIT_CACHE["rows"], _STRAT_AUDIT_CACHE["matrix"]
    rows = _strat.audit()
    matrix = _strat.matrix(rows=rows)
    # r1515：audit() 首次求值会按需初始化 strategy_params._CFG；若沿用求值
    # **前**的 id(None) 存签名，第二次请求的签名必然对不上，缓存永远只命中
    # 一次、每次打开面板都重跑 5s。求值后重取对象身份再落缓存。
    try:
        from core import strategy_params as _sp2
        _cfg_obj = getattr(_sp2, "_CFG", None)
    except Exception:
        pass
    sig = (id(_cfg_obj), id(getattr(_State, "cfg", None)))
    _STRAT_AUDIT_CACHE.update({"sig": sig, "rows": rows, "matrix": matrix})
    return rows, matrix


def _demo_strategy_payload():
    """演示用的策略载荷（r1673）：与真实载荷同源，但清空停手表。

    烘焙站点是给公众看的合成数据，绝不能带上开发机 `user_data/*/
    strategy_halt.json` 里的真实停手（否则演示不可复现，还会泄露
    "某台机器上谁被风控了"）。
    """
    try:
        out = _strategy_payload()
    except Exception as e:
        return {"ok": False, "demo": True,
                "err": "演示策略载荷生成失败：%s" % str(e)[:80]}
    out["halt"] = {}
    out["halt_scopes"] = {}
    out["demo"] = True
    return out


def _strategy_payload():
    """`GET /api/strategy` 的载荷（`matrix` 段由路由那一支现取现算，不在这里）。

    **逐段降级**（复核 2026-11-06 的要求：装配面任何一段坏掉不许整条 500）：
    渠道全集 / 覆盖字典 / 台账聚合 / 停手表各自 try——哪段炸了只让那段空或零，
    原因写进 `errors`。理由是面板一打开就白屏比少一段更糟；而静默降级等于
    让用户把「没读到」当成「没有」，所以 `errors` 必须给人看。

    台账读不出来时 `stats` 仍然**三个键齐全且为 0**：缺键会让界面画成
    `undefined`，「没有数字」与「数字是 0」在界面上是两件事。
    """
    from core.strategy_contract import STRATEGIES as _STS
    out = {"ok": True, "plats": [], "strategies": [], "overrides": {},
           "halt": {}, "errors": {}}
    # 渠道全集：粒度下拉的渠道段只许这 10 家（与 core/channels.py 同源）
    try:
        out["plats"] = list(_ALL_PLATS)
    except Exception as _pe:
        out["errors"]["plats"] = "渠道全集读不到：%s" % str(_pe)[:80]
    # 覆盖字典：**原样透传**（键是作用域串，值是 {pid: 值}），界面据它显示
    # 「生效值来自：渠道覆盖」。不是字典时如实点名——静默当成「没有覆盖」
    # 就是同一族缺陷（配了不生效）。
    try:
        _raw = ((_State.cfg or {}).get("crawler") or {}).get("strategy_overrides")
        if _raw is None or isinstance(_raw, dict):
            out["overrides"] = dict(_raw or {})
        else:
            out["errors"]["overrides"] = (
                "crawler.strategy_overrides 不是字典（%s）：这层覆盖不会生效"
                % type(_raw).__name__)
    except Exception as _oe:
        out["errors"]["overrides"] = "覆盖字典读不到：%s" % str(_oe)[:80]
    # 台账聚合（一次取齐 28 条的计数，按 note 的 `[<sid>]` 前缀，见
    # `PriceStorage.strategy_stats`）：失败给 0 并写明原因，不假装「没干预过」。
    stats = {}
    try:
        stats = _strategy_storage().strategy_stats() or {}
    except Exception as _se:
        out["errors"]["stats"] = ("台账读不到，干预计数按 0 出：%s"
                                  % str(_se)[:80])
    for s in _STS:
        st = stats.get(s.id) or {}
        out["strategies"].append({
            "id": s.id, "cn": s.cn, "family": s.family,
            "trigger": s.trigger, "scope": list(s.scope),
            "label": s.label, "intent": s.intent, "effect": s.effect,
            "auto_default": bool(s.auto_default), "api": list(s.api),
            "advice": s.advice,
            # r1063 T12c：这一步该点哪个按钮（动作码 + ≤40 字中文短句 + 路由）。
            # 与 `label/intent/effect` 三个字段分开：那三句说「它是什么/防什么/
            # 改了会怎样」，这句说「现在做什么」，混起来界面就有两个答案。
            "tip": _strategy_tip(s),
            "params": _strategy_param_rows(s),
            "stats": {"interventions": int(st.get("interventions") or 0),
                      "healed": int(st.get("healed") or 0),
                      "unhealed": int(st.get("unhealed") or 0),
                      "unjudged": int(st.get("unjudged") or 0)},
        })
    # r1063 T158：把**通路清单**暴露给界面（含本轮新增的 `PC·国际` / `PC·周历`），
    # 让策略面板能把「链路级」覆盖按行渲染，而不是让用户手打作用域键。
    # 只增字段：老前端忽略未知键，不影响既有渲染。
    try:
        from core.channels import PATH_CN as _PCN
        out["paths"] = [{"id": _k, "cn": _v}
                        for _k, _v in sorted(_PCN.items())]
    except Exception:
        out["paths"] = []
    # 停手表：按 **profile** 读（与采集器决策时同一个目录，口径由
    # `_policy_engine` 定；写成 plat 会读一个没人写的目录）。
    # 单个渠道读不出 ≠ 整段坏：那个渠道不出现在表里，其余照常。
    _read_halt = None
    try:
        from core.policy import read_halt as _read_halt
    except Exception as _he:
        out["errors"]["halt"] = "策略层读不到停手：%s" % str(_he)[:80]
    # r1667：**演示态不读真实停手表**。原先 demo 会读到开发机
    # `user_data/*/strategy_halt.json`，公开演示站与 CI 因此带上别人的停手
    # 状态（停手按钮变「恢复」），演示不再可复现。演示只该有合成数据。
    if DEMO["on"]:
        _read_halt = None
    if _read_halt is not None:
        out["halt_scopes"] = {}
        for _p in out["plats"]:
            try:
                _tbl = _read_halt(_policy_engine(_p).base_dir) or {}
            except Exception:
                continue
            for _k, _r in _tbl.items():
                _ks = str(_k)
                # 渠道级已在 `out["halt"]`；这里只收带作用域的那些
                # （键形如 `plat/<维度>` 或 `plat/<维度>/<链路>`）。
                if not _ks.startswith(_p + "/"):
                    continue
                try:
                    _u = float((_r or {}).get("until") or 0)
                except (TypeError, ValueError):
                    _u = 0.0
                out["halt_scopes"].setdefault(_p, []).append({
                    "scope": _ks[len(_p) + 1:], "until": _u,
                    "left_s": max(0, int(_u - time.time()))})
            try:
                _rec = (_read_halt(_policy_engine(_p).base_dir) or {}).get(_p)
            except Exception:
                continue
            if not _rec:
                continue
            try:
                _until = float(_rec.get("until") or 0)
            except (TypeError, ValueError):
                _until = 0.0
            out["halt"][_p] = {"until": _until,
                               "note": str(_rec.get("note") or ""),
                               "left_s": max(0, int(_until - time.time()))}
    # 逐渠道「策略条」（r1063 T13，Spec §6(b)）：「非默认 / 本渠道覆盖」的策略
    # + 人工停手 + 此刻的建议。**逐段降级**：这一段算不出来就让健康卡那条空一行
    # （行的其余部分照常），原因进 `errors`——静默当成「没有策略」是另一种谎话。
    try:
        out["channels"] = _strategy_strip_rows(out["plats"], out["halt"])
    except Exception as _ce:
        out["errors"]["channels"] = ("逐渠道策略条算不出来（健康卡那一条先空着）："
                                     "%s" % str(_ce)[:80])
    # 指纹一致性核账（r1063 T26）：两档各跑一次，离线可跑（不碰浏览器）。
    # 命中就带「修复建议」，让面板直接告诉用户哪里自相矛盾——这类矛盾是风控里
    # 最便宜的证据，而它恰恰是"看不见"的。
    try:
        from core import fp_audit as _fpa
        from crawlers.base import (DESKTOP_UA as _DUA, MOBILE_UA as _MUA,
                                   profile_headers as _ph)
        _geo = (_State.cfg or {}).get("geo") or {}
        _tls = str((_State.cfg or {}).get("tls_impersonate") or "chrome")
        _cases = []
        for _nm2, _ua2, _mob2, _vp2 in (
                ("桌面档", _DUA, False, {"width": 1366, "height": 900}),
                ("移动档", _MUA, True,
                 {"width": 390, "height": 844, "has_touch": True})):
            _fpx = {"ua": _ua2, "is_mobile": _mob2,
                    "locale": str(_geo.get("locale") or "zh-CN")}
            _hits2 = _fpa.audit(_fpx, _ph(dict(_fpx)), _vp2,
                                tls_impersonate=_tls,
                                config=_State.cfg or {})
            _cases.append({"name": _nm2, "count": len(_hits2),
                           "worst": (_hits2[0] if _hits2 else None),
                           "text": _fpa.summary(_hits2)})
        # App 侧（r1063 T32）：机型池逐个核「指纹/机型/SoC/构建」是否自洽。
        # PC 与 App 放同一段，才是"全链路"——分成两处又会出现两套口径。
        try:
            _n_pool, _ph = _fpa.audit_pool()
            _cases.append({
                "name": "App 机型池",
                "count": len(_ph),
                "worst": (_ph[0] if _ph else None),
                "text": ("App 机型池 %d 个：%s"
                         % (_n_pool, _fpa.summary(_ph)))})
        except Exception as _pe3:
            out["errors"]["fingerprint_app"] = ("App 机型池核账没跑起来：%s"
                                               % str(_pe3)[:80])
        out["fingerprint"] = _cases
    except Exception as _fpe:
        out["errors"]["fingerprint"] = ("指纹核账没跑起来（不影响采集）：%s"
                                        % str(_fpe)[:80])
    # 成功率保护的**逐作用域读数**（r1063 T16，Spec §6(b) 的延伸）：
    # 渠道级 / 维度级 / 链路级三档的实时倍数，供策略行显示「哪一条被压到几倍」。
    # 数据只从 `pacing.snapshot()` 取——与健康卡、`/api/pacing` 同一份状态，
    # 不在 webui 里另算一遍（「一切统一状态」）。
    try:
        _pac = getattr(_State, "pacing", None)
        snap = (_pac.snapshot() if _pac is not None else {}) or {}
        health = {}
        for _p, _ch in (snap.get("channels") or {}).items():
            rec = {}
            if _ch.get("health"):
                rec["channel"] = dict(_ch["health"])
            if _ch.get("health_dims"):
                rec["dims"] = {str(k): dict(v) for k, v
                               in _ch["health_dims"].items()}
            if _ch.get("health_paths"):
                rec["paths"] = {str(k): dict(v) for k, v
                                in _ch["health_paths"].items()}
            if rec:
                health[str(_p)] = rec
        out["health"] = health
    except Exception as _pe2:
        out["errors"]["health"] = ("成功率保护的逐作用域读数读不到：%s"
                                   % str(_pe2)[:80])
    return out


def _strategy_override_apply(cfg, ovr):
    """把面板提交的**粒度覆盖**写进 `cfg["crawler"]["strategy_overrides"]`。

    `ovr` 形状：`{作用域串: {pid: 值或 None}}`；作用域串与参数覆盖同一套
    语法（`plat` 之外的 `plat/dim`、`plat/dim/path`）。`值=None` 表示**清除**
    该覆盖（回到上一级）；某作用域被清空则整条作用域删掉。

    为什么在这里统一校验而不是信前端（r1063 T19）：
      * 未知 pid / 未知维度写进去**查不到**，界面却会显示「已覆盖」——
        这正是本项目最痛的一类缺陷（配了不生效）；
      * 值必须过 `strategy_params.clamp()`，与求值同一个入口，界面显示的
        边界就是落盘的边界。

    返回被写/被清的条目数；有问题直接 `ValueError`（整块不写，别写一半）。
    """
    if ovr is None:
        return 0
    if not isinstance(ovr, dict):
        raise ValueError("strategy_overrides 必须是 {作用域: {参数 id: 值}} 的字典"
                         "（收到 %s）" % type(ovr).__name__)
    from core import strategy_params as _sparams
    from core.strategy_contract import STRATEGIES as _STRS_O
    from core.channels import DIMENSIONS as _DIMS_O
    _PLATS_O = set(_ALL_PLATS)
    _CFG_OF = {_p.pid: _p for _s in _STRS_O for _p in _s.params}
    crawler = cfg.setdefault("crawler", {})
    if not isinstance(crawler, dict):
        raise ValueError("cfg['crawler'] 不是字典，无法写策略覆盖")
    cur = crawler.get("strategy_overrides")
    if cur is None:
        cur = {}
    if not isinstance(cur, dict):
        raise ValueError("crawler.strategy_overrides 不是字典（%s）："
                         "这一层覆盖不会生效" % type(cur).__name__)
    bad = []
    touched = 0
    for scope, kv in ovr.items():
        sc = str(scope or "").strip().strip("/")
        if not sc:
            bad.append("作用域为空（全局值请走 strategy_values）")
            continue
        # 作用域语法与 `core/strategy_params._lookup_keys` 一致：
        #   `plat`（整家） / `plat/dim` / `plat/dim/path`
        # 第一段必须是**渠道**——写成维度会被拼成查不到的键。
        # 注意 `split("/", 2)`：链路名自己就带斜杠（`detail/H5/API`），
        # 这与 `core/strategy_params._lookup_keys` 的切法必须逐字一致，
        # 否则合法的链路级覆盖会被判成「非法作用域」，正是「配了不生效」。
        parts = sc.split("/", 2)
        if parts[0] not in _PLATS_O:
            bad.append("%s（第一段 %r 不是渠道）" % (sc, parts[0]))
            continue
        if len(parts) > 1 and parts[1] not in tuple(_DIMS_O):
            bad.append("%s（维度 %r 不认识）" % (sc, parts[1]))
            continue
        if not isinstance(kv, dict):
            bad.append("%s（值必须是 {参数 id: 值}）" % sc)
            continue
        tgt = dict(cur.get(sc) or {})
        for pid, raw in kv.items():
            key = str(pid or "")
            if key not in _CFG_OF:
                bad.append("%s/%s（目录里没有这个参数）" % (sc, key))
                continue
            if raw is None:
                tgt.pop(key, None)
                touched += 1
                continue
            try:
                val, _note = _sparams.clamp(key, raw)
            except Exception as _pe:
                bad.append("%s/%s（%s）" % (sc, key, str(_pe)[:50]))
                continue
            tgt[key] = val
            touched += 1
        if tgt:
            cur[sc] = tgt
        else:
            cur.pop(sc, None)
    if bad:
        raise ValueError("这些策略覆盖没写进去：%s" % "、".join(bad[:4]))
    if cur:
        crawler["strategy_overrides"] = cur
    else:
        crawler.pop("strategy_overrides", None)
    return touched


def _strategy_scope_of(plat):
    """台账 `scope` 的取值：**渠道词汇**（ctrip/qunar/…）。

    绝不写成 `strategy:<id>`：`scope` 这一列是渠道/航线域的词汇表，
    面板的 `_ivScope` 表按它出中文标签（`tests/test_r654_*` 会逐值核对）。
    策略 id 放 `note` 的 `[<sid>]` 前缀里——那里本来就是自由文本。
    """
    return str(plat or "")


def _until_str(ts):
    """到期时间的人话（空/不可解析 → 空串，别写出 1970 年）。"""
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _strategy_ledger(plat, action, ok, note, before="", after="", scope=None):
    """写一条**策略族**干预账（`strategy_*`）。返回是否真的记上了。

    写不进去不许影响动作本身：停手已经落盘，账本只是痕迹。所以异常在这里
    收成一条 warning 并返回 False——**但返回值必须被消费**（复核 2026-11-06）：
    三个接口把它带进响应（`ledger`/`warn`），操作员才知道「这次操作查不到」。
    """
    scope = _strategy_scope_of(plat) if scope is None else str(scope or "")
    try:
        _strategy_storage().save_intervention(
            _strategy_scope_of(plat), action, ok=bool(ok), scope=scope,
            before=str(before or "")[:400], after=str(after or "")[:400],
            note=str(note or "")[:400])
        return True
    except Exception as _le:
        try:
            _State.logger.warning("[策略账] 写入失败（这次操作不会出现在溯源里）："
                                  "%s %s · %s: %s", plat, action,
                                  type(_le).__name__, _le)
        except Exception:
            pass
        return False


def _ledger_tail(out, ledger_ok, action="操作"):
    """把台账结果并进响应：`ledger` 永远在，失败时多一句中文 `warn`。

    为什么不让失败无声（复核 2026-11-06）：账本是「事后查得到」的唯一凭据。
    动作生效了但没记上，操作员下次翻溯源会以为没做过这件事。
    """
    out["ledger"] = bool(ledger_ok)
    if not ledger_ok:
        out["warn"] = "动作已生效，但台账没记上（数据库不可写）：这次%s查不到" \
                      "溯源记录" % action
    return out


def _strategy_scope_arg(body, plat):
    """解析停手/恢复的 `scope` 参数（r1063 T18）：`""`＝渠道级。

    允许 `"<维度>"` 或 `"<维度>/<链路>"`。**维度必须来自 `DIMENSIONS`**：
    写一个拼错的维度会落成一条永远查不到的停手（界面报「已停手」、渠道照跑），
    正是本分支一直在打的那种缺陷。返回 `(scope, err)`，`err` 非空即 400。
    """
    raw = str(body.get("scope") or "").strip().strip("/")
    if not raw:
        return "", ""
    parts = raw.split("/")
    try:
        from core.channels import DIMENSIONS as _DIMS
    except Exception:
        return "", "维度表读不到，无法校验停手作用域"
    dim = parts[0].strip()
    if dim not in tuple(_DIMS):
        return "", "未知维度 %r（允许：%s）" % (dim, "/".join(_DIMS))
    rest = raw[len(dim):].strip("/")
    if not rest:
        return dim, ""
    if len(rest) > 80 or " " in rest:
        return "", "链路名过长或含空格：%r" % (rest,)
    return dim + "/" + rest, ""


def _strategy_halt_api(payload):
    """`POST /api/strategy/halt`：`{plat, minutes, note?, sid?, scope?}` → 人工停手。

    `scope` 为空＝渠道级（历史行为）；`"intl"`＝只停该维度；`"detail/H5/API"`
    ＝只停那一条链路（r1063 T18）。

    成功回 `{ok, plat, scope, key, until}`（`minutes<=0` 时 `until=0`＝立即失效）；
    失败回 `{ok:false, err:"<中文>"}`，参数问题 400、落盘失败 500。
    """
    body = payload if isinstance(payload, dict) else {}
    plat = str(body.get("plat") or body.get("platform") or "").strip()
    if not plat:
        return 400, {"ok": False, "err": "缺少 plat：人工停手必须指定渠道"}
    if plat not in _ALL_PLATS:
        return 400, {"ok": False, "err": "未知渠道 %s" % plat}
    scope, _serr = _strategy_scope_arg(body, plat)
    if _serr:
        return 400, {"ok": False, "err": _serr}
    if "minutes" not in body:
        return 400, {"ok": False,
                     "err": "缺少 minutes：停手分钟数（0 = 立即失效）"}
    try:
        mins = int(float(body.get("minutes")))
    except (TypeError, ValueError, OverflowError):
        return 400, {"ok": False,
                     "err": "停手分钟数 %r 无法解析（要整数分钟）"
                            % (body.get("minutes"),)}
    from core.policy import halt_key, read_halt, set_halt
    key = halt_key(plat, scope)
    try:
        eng = _policy_engine(plat)
        before = _until_str((read_halt(eng.base_dir).get(key) or {})
                            .get("until"))
    except Exception as _ee:
        return 500, {"ok": False, "err": "策略层不可用：%s" % str(_ee)[:120]}
    sid = str(body.get("sid") or body.get("strategy_id") or plat)
    raw = str(body.get("note") or "").strip()
    # 停手文件里的 `note` 是**给人看的一句话**（面板直接贴在停手卡上），
    # 保持用户原话；`[<sid>]` 前缀只进台账（那是策略变更的溯源口径）。
    note = raw or ("人工停手 %d 分钟" % mins)
    ledger_note = ("[%s] 人工停手 %d 分钟%s%s"
                   % (sid, mins, ("（作用域 %s）" % scope) if scope else "",
                      ("：" + raw) if raw else ""))
    try:
        rec = set_halt(eng.base_dir, plat, mins, note, scope=scope)
    except ValueError as ve:
        return 400, {"ok": False, "err": str(ve)}
    except Exception as _se:
        return 500, {"ok": False, "err": "停手失败：%s" % str(_se)[:120]}
    # **`rec is False` 才算失败**（陷阱 A）：`minutes<=0` 写盘成功后返回的是
    # 合法的空表 `{}`，写成 `if not rec:` 会把「立即失效」报成 500。
    if rec is False:
        _led = _strategy_ledger(plat, "strategy_halt", False,
                                ledger_note + "（写盘失败：停手未生效）",
                                before=before)
        return 500, _ledger_tail({"ok": False,
                                  "err": "停手没能落盘（磁盘或权限问题），"
                                         "请重试"}, _led, "停手")
    until = 0.0
    try:
        until = float(((rec or {}).get(key) or {}).get("until") or 0.0)
    except (TypeError, ValueError):
        until = 0.0
    _led = _strategy_ledger(plat, "strategy_halt", True, ledger_note,
                            before=before, after=_until_str(until))
    return 200, _ledger_tail({"ok": True, "plat": plat, "scope": scope,
                              "key": key, "until": until},
                             _led, "停手")


def _strategy_resume_api(payload):
    """`POST /api/strategy/resume`：`{plat, sid?, scope?}` → 撤掉人工停手。

    `scope` 与停手一致（空＝渠道级，`"intl"`＝维度，`"detail/H5/API"`＝链路）。

    **只解人工停手**：自动熔断归 `/api/pacing/reset`（走 `reset_auto()`）。
    本来就没有停手 → 回 200 且 `cleared=false`（目的已达成，不是失败）。
    """
    body = payload if isinstance(payload, dict) else {}
    plat = str(body.get("plat") or body.get("platform") or "").strip()
    if not plat:
        return 400, {"ok": False, "err": "缺少 plat：恢复必须指定渠道"}
    if plat not in _ALL_PLATS:
        return 400, {"ok": False, "err": "未知渠道 %s" % plat}
    scope, _serr = _strategy_scope_arg(body, plat)
    if _serr:
        return 400, {"ok": False, "err": _serr}
    from core.policy import clear_halt, halt_key, read_halt
    key = halt_key(plat, scope)
    try:
        eng = _policy_engine(plat)
        halts = read_halt(eng.base_dir)
    except Exception as _ee:
        return 500, {"ok": False, "err": "策略层不可用：%s" % str(_ee)[:120]}
    if key not in (halts or {}):
        return 200, _ledger_tail({"ok": True, "plat": plat, "scope": scope,
                                  "cleared": False}, True, "恢复")
    before = _until_str((halts.get(key) or {}).get("until"))
    try:
        ok = clear_halt(eng.base_dir, plat, scope=scope)
    except Exception as _ce:
        return 500, {"ok": False, "err": "恢复失败：%s" % str(_ce)[:120]}
    sid = str(body.get("sid") or body.get("strategy_id") or plat)
    note = ("[%s] 人工恢复%s（原到期 %s）"
            % (sid, ("（作用域 %s）" % scope) if scope else "", before or "-"))
    if not ok:
        # 写盘失败：文件里那条还在，停手继续生效——不许报「已恢复」
        _led = _strategy_ledger(plat, "strategy_resume", False,
                                note + "（写盘失败：停手仍然生效）",
                                before=before)
        return 500, _ledger_tail({"ok": False,
                                  "err": "恢复没能落盘（磁盘或权限问题）："
                                         "人工停手仍然生效，请重试"}, _led, "恢复")
    _led = _strategy_ledger(plat, "strategy_resume", True, note, before=before)
    return 200, _ledger_tail({"ok": True, "plat": plat, "cleared": True},
                             _led, "恢复")


def _closure_dicts(fn, depth=3, out=None, seen=None):
    """收集回调闭包里（层数受限）的字典——找采集运行时容器 `rt` 用。"""
    out = [] if out is None else out
    seen = set() if seen is None else seen
    for cell in (getattr(fn, "__closure__", None) or ()):
        try:
            val = cell.cell_contents
        except Exception:
            continue
        if isinstance(val, dict):
            out.append(val)
        elif callable(val) and depth > 0 and id(val) not in seen:
            seen.add(id(val))
            _closure_dicts(val, depth - 1, out, seen)
    return out


def _runtime_rt():
    """采集运行时容器（`main.py` 的 `rt`）：`_round_gen` 就挂在它上面。

    优先 `_State.rt`（main 挂一句 `_State.rt = rt` 即可）。没挂接时按任务回调
    的闭包找一次：`job` 是 `lambda: sweep(force=True)`，`sweep` 的闭包里就
    有 `rt`。为什么要这么绕——**中断本轮的唯一真实开关**就是
    `rt["_round_gen"]`（worker 在加载锁、发请求、写现场等每个检查点都拿自己
    捕获的代际与它比，不等就提前收工，见 `main.py` 的 `_gen` 判定）。找不到
    就如实回失败：假装中断成功比不中断更糟，操作员会以为已经停了。
    命中后挂回 `_State.rt`，后续调用不再扫。
    """
    rt = getattr(_State, "rt", None)
    if isinstance(rt, dict):
        return rt
    found = []
    for name in ("job", "probe_cb", "warm_cb", "login_saved_cb", "reload_cb"):
        fn = getattr(_State, name, None)
        if callable(fn):
            try:
                found.extend(_closure_dicts(fn))
            except Exception:
                continue
    for d in found:
        if "_round_gen" in d:
            _State.rt = d
            return d
    for d in found:
        if "cfg" in d and "users" in d:
            _State.rt = d
            return d
    return None


def _round_abort_api(payload):
    """`POST /api/round/abort`：`{plat?, sid?}` → 中断当前采集轮次。

    做法是**递增轮次代际**，不发信号、不杀线程：worker 在下一个检查点自己
    收工（`rt["_round_gen"]` 与本轮捕获的值不等）。这样既不会把半条请求
    打断在 socket 上，也不会让「晚到的 worker」把现场/失败写进下一轮的账。

    没有指定渠道时台账用 `platform="*"`（＝整轮，不是某个渠道）：三种策略族
    行因此都能按平台聚（`"*"` 一桶），不会出现一堆 `platform=""` 的空键。
    `scope` 留空＝动作级（与既有账本约定一致：空 scope 不进分域统计）。
    """
    body = payload if isinstance(payload, dict) else {}
    plat = str(body.get("plat") or body.get("platform") or "").strip()
    if plat and plat not in _ALL_PLATS:
        return 400, {"ok": False, "err": "未知渠道 %s" % plat}
    rt = _runtime_rt()
    if not isinstance(rt, dict):
        return 503, {"ok": False,
                     "err": "采集运行时未挂接，无法中断本轮（本轮可能尚未开始）"}
    try:
        gen = int(rt.get("_round_gen") or 0) + 1
        rt["_round_gen"] = gen
    except Exception as _ae:
        return 500, {"ok": False, "err": "中断本轮失败：%s" % str(_ae)[:120]}
    sid = str(body.get("sid") or body.get("strategy_id") or plat or "round")
    _led = _strategy_ledger(
        plat or "*", "strategy_abort", True,
        "[%s] 人工中断本轮（代际 → %d，worker 在下一个检查点收工）"
        % (sid, gen), scope="")
    return 200, _ledger_tail({"ok": True, "gen": gen, "plat": plat}, _led,
                             "中断")


def _auto_reset(plat):
    """「解除自动熔断」的**策略层**部分：清 `policy_state.json`，**不碰人工停手**。

    返回 `(ok, err)`。为什么要单独一个函数并对返回值负责（复核 2026-11-06
    Important 2）：`PolicyEngine.reset_auto()` 自己吞掉异常、原先返回 `None`，
    路由那圈 `except` 永远走不到——磁盘写不动时界面照样报「已解除」，而策略层
    还在拦，操作员只会以为按钮坏了。`ok=False` 时界面**不许**说「已解除」。

    无论成败都写一条 `strategy_auto_reset` 台账（第三族，不进人工成功率）。
    返回 `(ok, err, ledger_ok)`——`ledger_ok` 让路由能如实说「动作生效了但
    台账没记上」。
    """
    plat = str(plat or "").strip()
    sid = plat or "round"
    try:
        eng = _policy_engine(plat)
        ok = bool(eng.reset_auto(plat))
    except Exception as _e:
        ok = False
        _State.logger.warning("[干预] 策略层自动状态清除异常：%s", _e)
    if not ok:
        led = _strategy_ledger(
            plat, "strategy_auto_reset", False,
            "[%s] 解除自动熔断：自动状态未能清除（策略层可能仍在拦）" % sid)
        return False, ("熔断已解除，但策略层自动状态没能清除（磁盘/权限）："
                       "策略层可能仍在拦，请重试"), led
    led = _strategy_ledger(
        plat, "strategy_auto_reset", True,
        "[%s] 解除自动熔断：自动状态机已清（人工停手不动）" % sid)
    return True, "", led


# 配置保存互斥（r649）：/api/config 是「读 yaml → 改 → 写 yaml」的读改写序列。
# ThreadingHTTPServer 下两个并发保存会互相覆盖——实测两次都回 200，但 3 次里
# 有 2 次丢掉其中一项改动（A 改轮询周期、B 改 TTL，最终只有一项生效）。
# 用户看到「保存成功」，配置已被回滚。锁要覆盖到 reload 回调结束：否则
# 热重载可能读到别人写了一半的 yaml。
_CFG_SAVE_LOCK = threading.Lock()


# ── App 渠道登录（r604）──────────────────────────────────────────
# 包一层，把 webui 的配置/日志接到 core.android.login_api 上；
# login_api 本身不 import webui，避免循环依赖。
APP_LOGIN_PACKAGES = {"app_zhixing": "cn.suanya.zhixing",
                      "app_qunar": "com.Qunar",
                      "app_fliggy": "com.taobao.trip",
                      "app_ctrip": "ctrip.android.view",
                      "app_tongcheng": "com.tongcheng.android"}


def _app_login_registry():
    from core.android.login_session import AppLoginRegistry
    if _State.app_login is None:
        with _State.lock:
            if _State.app_login is None:
                _State.app_login = AppLoginRegistry()
    # r1063 T167：把会话表登记给 login_api，采集侧才能"看到有人在登录"并让位
    # （否则定时轮次会把 App 切走，用户的登录会话当场作废）。
    try:
        from core.android import login_api as _la
        _la.set_registry(_State.app_login)
    except Exception:
        pass
    return _State.app_login


def _app_login_ctx():
    """构造 login_api 需要的上下文：运行时工厂 + 校验 + 快照。"""
    from core.android.runtime import get_runtime

    cfg = _State.cfg or {}

    def _runtime():
        if not (cfg.get("android") or {}).get("enabled"):
            return None
        return get_runtime(cfg, _State.logger)

    def _needs_login(plat: str = ""):
        return _app_login_expired(plat)

    def _verify(plat: str = ""):
        """dump 首页判断是否真的登录了（只认明确的登录墙文案）。"""
        rt = _runtime()
        dev = rt.device() if rt else None
        if dev is None:
            return True, "无法校验（设备不可用）"
        xml = dev.dump()
        if not xml:
            return True, "无法校验（未取到页面）"
        # 每个渠道的登录墙形态不同：去哪儿是手机号表单，智行是「立即登录」
        # 文案。混用会把「去哪儿登录页」判成已登录，登录卡提前变绿。
        if (plat or "") == "app_qunar":
            if "请输入手机号" in xml or "获取验证码" in xml:
                return False, "页面仍是手机号登录页，请完成登录后再试"
        if (plat or "") in ("app_ctrip", "app_fliggy"):
            try:
                act = dev.current_activity() or ""
            except Exception:
                act = ""
            if "CtripLoginActivity" in act:
                return False, "页面仍是携程登录页，请完成登录后再试"
            if "login" in act.lower():
                return False, "页面仍是飞猪登录页，请完成登录后再试"
        try:
            from crawlers.app_zhixing_parse import detect_state
            st = detect_state(xml)
        except Exception:
            st = "unknown"
        if st == "login":
            return False, "页面仍是登录墙，请完成登录后再试"
        return True, "已离开登录墙"

    def _snapshot_info(plat: str = "") -> dict:
        """快照文件是否存在（含 mtime），供登录卡显示「已保存」。

        不需要设备：只读本地文件。没有它时用户登录完、会话结束后卡片
        一直显示「未保存会话」，与事实相反。
        """
        try:
            # 目录必须与采集器**实际在写**的那个一致（唯一口径 + 启动级，
            # 见 `_ud_root_runtime()`）。原来自己 `_anchored(... or
            # "user_data")` 算一遍：装了 `TM_USER_DATA_DIR` 就永远找不到
            # 采集器写在 env 目录里的快照，卡片一直显示「未保存会话」，
            # 与事实相反——这是「界面说没有、其实有」的方向（T6 Critical
            # 的镜像形态，r1063 T10 复核）。
            udir = _ud_root_runtime()
            p = os.path.join(udir, "android_snapshots",
                             (plat or "app_zhixing") + ".tar.gz")
            if not (os.path.isfile(p) and os.path.getsize(p) > 0):
                return {"exists": False}
            return {"exists": True, "mtime": os.path.getmtime(p),
                    "size": os.path.getsize(p)}
        except OSError:
            return {"exists": False}

    def _snapshot(plat: str = ""):
        """导出**当前登录渠道**的登录态。

        plat 来自 handle_finish 的契约（回调本就拿得到渠道 id）。此前这里
        把包名与快照名写死成智行：在去哪儿 App 登录后点「保存会话」，
        落盘的是 app_zhixing.tar.gz——界面显示已保存，下次采集却永远
        「快照已失效」。这类缺陷不抛异常，日志还会写「快照 0.6 MB」。
        """
        plat = str(plat or "").strip() or "app_zhixing"
        pkg = APP_LOGIN_PACKAGES.get(plat)
        if not pkg:
            return False, f"该渠道没有登记包名：{plat}"
        rt = _runtime()
        dev = rt.device() if rt else None
        if dev is None:
            return False, "设备不可用"
        try:
            from core.android.snapshot import SnapshotManager, SnapshotStore
            # 快照与浏览器登录态同放 user_data 下：同为本地凭证，
            # 同受「资料目录整体搬迁」那套启动级逻辑管理。
            # 目录用 `_ud_root_runtime()`（唯一口径 + 启动级）：导出的快照
            # 必须落在采集器会去恢复的那个目录，否则「登录一次永久复用」
            # 从导出那一刻就失效；相对路径直接 join 还会随 cwd 漂移。
            udir = _ud_root_runtime()
            store = SnapshotStore(os.path.join(udir, "android_snapshots"))
            mgr = SnapshotManager(dev, store, pkg)
            return mgr.export(plat)
        except Exception as e:
            return False, f"快照失败：{type(e).__name__}"

    def _device_state(plat: str = "") -> dict:
        """**账本侧证据**：这台 App 在设备上最近一次采集到底出没出数。

        为什么需要（r1372，用户原话：「为什么后台不能发现 App 已经登录了，
        状态自动幂等？浏览器一样」）：浏览器卡片的「会话有效」是从 profile /
        快照推出来的**自动结论**，而 App 卡片只看「有没有导过快照」——
        设备上明明登着、账本里明明有 ok 行，界面却只说「未保存会话」。

        判据纯读库、不碰设备，所以**幂等**（重启后结论一致，也不会占用设备锁）：
          · 最近一次 `ok/calendar` 晚于（或等于）最近一次 `login` → 设备登录有效；
          · 否则最近一次是 `login` → 设备上被要求登录；
          · 账本里没有该渠道记录 → 未知（不猜）。
        """
        plat = str(plat or "").strip()
        if not plat:
            return {}
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"),
                                  uri=True, timeout=3)
        except Exception:
            return {}
        try:
            def _last(statuses):
                marks = ",".join("?" * len(statuses))
                row = con.execute(
                    "select max(fetched_at) from fetch_paths "
                    "where platform=? and path_status in (%s)" % marks,
                    (plat,) + tuple(statuses)).fetchone()
                return str((row and row[0]) or "")

            ok_at = _last(("ok", "calendar"))
            login_at = _last(("login",))
        except Exception:
            return {}
        finally:
            try:
                con.close()
            except Exception:
                pass
        if ok_at and (not login_at or ok_at >= login_at):
            return {"state": "logged_in", "at": ok_at,
                    "why": "设备登录有效：最近一轮 App 采集出过数（%s）" % ok_at}
        if login_at:
            return {"state": "login_wall", "at": login_at,
                    "why": "设备上被要求登录：最近一次 App 采集命中登录墙（%s）"
                           % login_at}
        return {"state": "unknown", "at": "",
                "why": "账本里还没有该渠道的采集记录"}

    return {"packages": APP_LOGIN_PACKAGES,
            "runtime_factory": _runtime,
            "verify": _verify,
            "snapshot": _snapshot,
            "snapshot_info": _snapshot_info, "needs_login": _needs_login,
            "device_state": _device_state}


def _test_email_launch() -> str:
    """测试邮件 launch：按配置 base_url 公网判定。
    独立模块级函数=执行级可测（曾内联三元表达式
    中变量名写错 NameError，被端点 except 吞成「发送失败」，源钉
    grep 抓不到执行错误）。"""
    from core.notifier import launch_is_public
    bu = str(((_State.cfg or {}).get("web") or {})
             .get("base_url", "") or "").strip()
    return bu if launch_is_public(bu) else ""


_LOGIN_PLATS = ("qunar", "ctrip", "tongcheng", "tuniu", "fliggy")
# 「自检」是健康诊断卡的动作，不是登录：App 渠道也有诊断卡（health_diag
# 按启用渠道出卡），必须能自检；拿登录槽位表当白名单会让 App 卡上的
# 按钮永远报「未知渠道」。
from core.channels import APP_CHANNELS as _APP_CHANNELS  # noqa: E402
_SELFCHECK_PLATS = tuple(_LOGIN_PLATS) + tuple(_APP_CHANNELS)
# 可干预端点（解除/自检/验证/预热）必须与渠道全集同源：App 渠道也在
# 节流表里出按钮，只按浏览器五家校验会直接 400「未知渠道」。
_ALL_PLATS = tuple(PLATFORMS) + tuple(_APP_CHANNELS)
# r1169：**登录状态的唯一真源**。后端只认这 7 档（+1 个兜底），
# 槽位/卡片/chip 的文案与色调都由 `state7` / `state_cn` 派生。
# 以前后端有 10 个 status 词、前端另有三套各写一份的中文表（LBL /
# SLOT_STATUS_CN / lgShortStatus），同一个 page_ok 在三处三种说法——
# 用户在三张卡上读到三种状态，这就是"一切统一状态"要消灭的漂移。
SLOT_STATE7 = (
    ("usable", "可用"),          # 真出过明细
    ("reachable", "入口可达"),    # 页面核验通过，但没出过明细
    ("unverified", "已存待验"),   # 只存了会话/正在登录，还没证据
    ("need_login", "需登录"),     # 登录墙
    ("need_verify", "需验证"),    # 人机验证（滑块/点选）
    ("broken", "失败"),          # 保存失败/报错
    ("retired", "停服"),         # 渠道侧已停服
)

_SLOT_STATE_MAP = {
    "available": "usable",
    "page_ok": "reachable",
    "saved": "unverified", "pending": "unverified",
    "saving": "unverified", "active": "unverified",
    "login_required": "need_login", "missing": "need_login",
    "challenge": "need_verify",
    "save_error": "broken", "error": "broken",
    "retired": "retired", "service_closed": "retired",
}


def _slot_state7(status, service_closed: bool = False):
    """把任意 status 折进 7 档，返回 `(state7, 中文)`。

    未登记的**新词**一律落 `("unknown", "待确认")`——宁可说"待确认"，
    也不许静默空白（静默空白会被当成"正常"，那才是真事故）。
    """
    if service_closed:
        return "retired", "停服"
    want = _SLOT_STATE_MAP.get(str(status or ""), "")
    for code, cn in SLOT_STATE7:
        if code == want:
            return code, cn
    return "unknown", "待确认"


# 登录槽位核验（独立端会话）：只记录真实页面分类结果，未核验不猜。
# r1156：结论必须落盘——只在内存时，重启一次「已核验」就退回「已存待验」，
# 用户读到的正是「我登录了，你页面没变」。
_SLOT_VERIFY_PATH = os.path.join("user_data", "slot_verify.json")
_SLOT_VERIFY = {}
_SLOT_VERIFY_LOCK = threading.Lock()
_SLOT_VERIFY_THREAD = None


def _slot_verify_load() -> dict:
    """读回上次的核验结论；文件缺失/损坏一律降级为空，绝不抛异常。"""
    try:
        with open(_SLOT_VERIFY_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    out = {}
    for k, v in (data or {}).items():
        if isinstance(v, dict):
            out[str(k)] = dict(v)
    return out


def _slot_verify_save() -> None:
    """原子落盘（先写 .tmp 再 replace）；失败只告警，不打断核验本身。"""
    try:
        d = os.path.dirname(_SLOT_VERIFY_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = _SLOT_VERIFY_PATH + ".tmp"
        with _SLOT_VERIFY_LOCK:
            payload = {k: dict(v) for k, v in _SLOT_VERIFY.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=0)
        os.replace(tmp, _SLOT_VERIFY_PATH)
    except Exception:
        try:
            _State.logger.warning("[登录] 槽位核验结果落盘失败", exc_info=True)
        except Exception:
            pass


_SLOT_VERIFY.update(_slot_verify_load())


def _effective_crawler_config() -> dict:
    """Session storage is a startup setting; other crawler options stay live.

    r1063 T275：这句"stay live"此前是**空头承诺**——本函数读 `_State.cfg`
    （`start_web()` 的启动快照），而 `/api/config` 保存只调 `st.reload_cb()`
    更新主程序那份，于是面板里改任何 crawler 选项都不生效（默认值恰好等于
    旧值时，这种 bug 能藏几个月）。现在保存处理会 `_State.cfg = load_config()`
    同步本快照，这句话才成立。**直接改 config.yaml 仍需重启**（没有文件监听）。
    """
    current = dict(((_State.cfg or {}).get("crawler") or {}))
    # 资料目录属于启动级设置：生效值是**运行期**那一份（唯一口径，见
    # `_ud_root_runtime()`）。原来自己 `_anchored(boot... or "user_data")` 算
    # 一遍，装了 `TM_USER_DATA_DIR` 就与采集器实际读的目录分叉（r1063 T10）。
    current["user_data_dir"] = _ud_root_runtime()
    return current


# 账本拦截的两种性质：滑块/验证码要人工过验证，登录门要重登。两件事都
# 不影响「会话是否保存」，但都是**必须人工处理**的当前状态。此前登录卡
# 只读 monitor.log 的认证证据，滑块被拦那一轮只要另有一张成功，整轮就是
# ok——健康卡写「最近一轮正常」，登录卡写「已保存·待验证」（现场
# 2026-11-01 22:21 途牛 PC：账本 blocked「人机验证页（滑块）」，日志同轮
# 国内却成功出数）。账本里的事实必须能走到界面上。
_PATH_CAPTCHA_MARKS = ("验证码", "滑块", "人机", "challenge", "captcha",
                       "安全验证", "滑动验证", "拼图")
_PATH_LOGIN_MARKS = ("登录", "login", "会话失效", "快照已失效")
# unsupported 不算恢复：它只说明这次没走这条通路，没证明页面已经打开。
_PATH_RECOVERED = ("ok", "calendar", "empty")


def _recent_path_rows(hours: int = 24) -> dict:
    """近 N 小时的采集尝试，按平台分组。只读；库不在/读失败一律当空。"""
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        if not os.path.isfile(db):
            return {}
        with sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"),
                             uri=True) as c:
            rows = c.execute(
                "SELECT fetched_at, platform, entry_path, path_status, "
                "rows, note, request_url FROM fetch_paths "
                "WHERE fetched_at >= datetime('now','localtime', ?) "
                "ORDER BY fetched_at", ("-%d hours" % int(hours),)).fetchall()
    except Exception:
        return {}
    out = {}
    for at, plat, entry, status, n, note, url in rows:
        out.setdefault(str(plat or ""), []).append({
            "fetched_at": str(at or ""), "entry_path": str(entry or ""),
            "path_status": str(status or ""), "rows": int(n or 0),
            "note": str(note or ""), "request_url": str(url or ""),
        })
    return out


def _entry_matches_surface(entry: str, surface: str) -> bool:
    ep = str(entry or "").upper()
    sf = str(surface or "").lower()
    if not sf:
        return True
    if sf == "pc":
        return ep.startswith("PC")
    if sf == "h5":
        return ep.startswith("H5")
    return True


def _path_block_kind(status: str, note: str) -> str:
    low = str(note or "").lower()
    if any(k in note or k in low for k in _PATH_CAPTCHA_MARKS):
        return "captcha"
    if (str(status or "") == "login"
            or any(k in note or k in low for k in _PATH_LOGIN_MARKS)):
        return "login"
    return ""


def _path_block_from_rows(rows, entry="", saved_at=0.0):
    """挑出**尚未恢复**的账本拦截（滑块/登录门）。

    恢复判据只认**同一入口**后来的真实成功（ok/calendar/empty）或更新的
    会话保存。明细证据（scopes.detail_at）没有入口归属，不能拿来解除某个
    入口的拦截——r813g 现场：H5/API 与 PC 同一秒成功，PC 的滑块被当成
    「已恢复」，登录卡显示 available（用户点名的「途牛 PC 要验证码，
    为什么登录处看不到」）。看不懂的 blocked（如 App 城市页失败）不冒充
    验证/登录。
    """
    ok_at = {}
    parsed = []
    for r in rows or []:
        at = str(r.get("fetched_at") or "")
        try:
            t = datetime.strptime(at, "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, TypeError):
            continue
        ep = str(r.get("entry_path") or "")
        if not _entry_matches_surface(ep, entry):
            continue
        parsed.append((t, ep, r))
        if str(r.get("path_status") or "") in _PATH_RECOVERED:
            ok_at[ep] = max(ok_at.get(ep, 0.0), t)
    base = float(saved_at or 0)
    best = None
    for t, ep, r in parsed:
        st = str(r.get("path_status") or "")
        if st not in ("blocked", "login"):
            continue
        kind = _path_block_kind(st, str(r.get("note") or ""))
        if not kind:
            continue
        if t <= ok_at.get(ep, 0.0) or t <= base:
            continue
        if best is None or t > best["ts"]:
            best = {"kind": kind, "at": str(r.get("fetched_at") or ""),
                    "path": ep, "note": str(r.get("note") or ""),
                    "url": str(r.get("request_url") or ""), "ts": t}
    return best


def _clear_qunar_stale_auth(scopes: dict, saved_at: float, event_time) -> dict:
    """去哪儿单 profile：任一 scope 的真实明细成功，已证明账号会话可用；
    更早的其它 scope 拒绝（unknown/路由级）是限流/软拒残留，不能把整张
    登录卡挂成「需登录」。只在最新成功明细之后仍有拒绝时才保留。
    """
    latest = 0.0
    for s in (scopes or {}).values():
        latest = max(latest, float(event_time(s.get("detail_at")) or 0))
    saved = float(saved_at or 0)
    if latest <= saved:
        return scopes
    for s in (scopes or {}).values():
        dt = float(event_time(s.get("detail_at")) or 0)
        if s.get("needs_login") and dt < latest:
            s["needs_login"] = False
        # 明细已在登录快照之后成功时，「会话失效」只是历史残留文案；
        # 即使该 scope 的 needs_login 已被别处清掉，也不能继续挂着它。
        if (s.get("reason") == "会话失效"
                and not s.get("needs_login") and dt >= saved):
            s["reason"] = ""
    return scopes


def _surface_detail_ok(rows, surface: str) -> bool:
    """该**端面**（PC / H5）是否真的出过数（r1063 T270）。

    为什么要单独算：`plats[plat].scopes` 是按**维度**（domestic/international）
    聚合的，没有端面维度；H5 槽位此前只能拿"入口页可达"当证据，
    于是**永远显示"已保存·待验证"**（用户原话："我途牛 h5 也登录了，但页面没变"）。

    口径：该端面对应的通路（名字以 `H5` / `PC` 开头，如 `H5`、`H5/API`、`PC·国际`）
    里有任意一条 `ok > 0`，即认为明细可用——这是"真出过数"，不是"页面能打开"。
    """
    want = (surface or "").upper()
    if not want:
        return False
    for r in rows or []:
        r = r or {}
        # 账本字段：`entry_path` / `path_status` / `rows`（`_recent_path_rows` 的原样）
        path = str(r.get("entry_path") or r.get("path")
                   or r.get("entry") or "").upper()
        if not path.startswith(want):
            continue
        st = str(r.get("path_status") or r.get("status") or "").lower()
        if st in ("ok", "calendar"):
            return True
        try:
            if int(r.get("rows") or 0) > 0:
                return True
        except Exception:
            continue
    return False


def _login_state_view() -> dict:
    """One current authentication snapshot, separate from historical health."""
    import os as _os
    import time as _t
    from crawlers import REGISTRY
    cfg = _effective_crawler_config()
    root = cfg["user_data_dir"]
    try:
        # 认证快照要的是「已接收的拒绝证据」，默认仍走 _health_state——
        # 它是可注入点（测试 monkeypatch 它来喂证据）。
        # 但 _health_state → _health_decorate → _login_state_view 会递归，
        # 所以装饰层在调用本函数前会置 _IN_HEALTH_DECORATE：那种重入
        # 情形下改走「直接解析日志」，绕开装饰层，不打断注入契约。
        if _IN_HEALTH_DECORATE:
            # 重入标志只对置位它的同一线程有效：后台健康装饰线程置真时，
            # 请求线程仍必须走可注入的 _health_state（并发门禁实测：
            # 别线程的 True 会让 pending 窗拿旧日志证据，新拒绝结束不了窗）。
            if getattr(_IN_HEALTH_DECORATE_TID, "ident", None) == \
                    threading.get_ident():
                from core.health import parse_health
                evidence = parse_health(_read_log_tail(max_age_h=26),
                                        hours=24).get("evidence", {})
            else:
                evidence = _health_state(24).get("evidence", {})
        else:
            evidence = _health_state(24).get("evidence", {})
    except Exception:
        evidence = {}
    path_rows = _recent_path_rows(24)

    def event_time(value):
        try:
            return datetime.fromisoformat(value).timestamp() if value else 0.0
        except (ValueError, TypeError):
            return 0.0

    plats = {}
    for p in _LOGIN_PLATS:
        d = _os.path.join(root, p)
        try:
            saved = _os.path.isdir(d) and next(_os.scandir(d), None) is not None
        except OSError:
            saved = False
        crawler = REGISTRY[p](cfg, _State.logger)
        saved_at = float(getattr(crawler, "session_saved_at", 0) or 0)
        # 未来时间戳（恢复错时钟/手改快照）会把所有当前认证拒绝永久压成旧证据；
        # 只接受已经发生的保存时间，超过 5 分钟时钟偏差视为不可信。
        if saved_at < 0 or saved_at > _t.time() + 300:
            saved_at = 0.0
        # The persisted save time survives a service restart. Legacy pending is
        # only a transition hint, never a reason to suppress newer rejection.
        pending_at = _State.login_pending.get(p, 0)
        scopes = {}
        for scope, ev in (evidence.get(p) or {}).items():
            auth_at, detail_at = event_time(ev.get("auth_at")), event_time(ev.get("detail_at"))
            scopes[scope] = {
                "needs_login": auth_at > max(saved_at, detail_at),
                "auth_at": ev.get("auth_at", ""),
                "detail_at": ev.get("detail_at", ""),
                "reason": ev.get("auth_reason", ""),
                "detail_available": detail_at > saved_at and detail_at > auth_at,
            }
        # 本轮探针真实明细作为即时可用证据，与历史健康同源合并；
        # 空结果/日历价/超时不会写入这里，也不得反推登录失效。
        with _PROBE_TASK_LOCK:
            probe_scopes = json.loads(json.dumps(_PROBE_AUTH.get(p) or {}))
        for scope, pe in probe_scopes.items():
            dts = float(pe.get("detail_ts") or 0)
            ats = float(pe.get("auth_ts") or 0)
            cur = scopes.get(scope) or {
                "needs_login": False, "auth_at": "", "detail_at": "",
                "reason": "", "detail_available": False,
            }
            changed = False
            if dts > event_time(cur.get("detail_at")):
                cur.update({
                    "detail_at": pe.get("detail_at", ""),
                    "probe_count": int(pe.get("detail_count") or 0),
                    "probe_route": (pe.get("from", "") + "→" + pe.get("to", "")),
                    "probe_date": pe.get("date", ""),
                    "source": "probe",
                })
                changed = True
            if ats > event_time(cur.get("auth_at")):
                cur.update({
                    "auth_at": pe.get("auth_at", ""),
                    "reason": pe.get("auth_reason", ""),
                    "auth_path": pe.get("auth_path", ""),
                    "auth_source": "probe",
                })
                changed = True
            if not changed:
                continue
            da = event_time(cur.get("detail_at"))
            aa = event_time(cur.get("auth_at"))
            cur["detail_available"] = da > saved_at and da > aa
            cur["needs_login"] = aa > max(saved_at, da)
            scopes[scope] = cur
        if p == "qunar":
            _clear_qunar_stale_auth(scopes, saved_at, event_time)
        rejected = any(s["needs_login"] for s in scopes.values())
        available = any(s["detail_available"] for s in scopes.values())
        session = _State.login_sessions.get(p) or {}
        active = bool(session)
        saving = bool(session.get("saving"))
        pending = bool(pending_at and _t.time() - pending_at < 600)
        # 只有晚于用户点「登录完成」的新拒绝/新明细才能结束待验证窗；
        # 旧证据不能把刚点的登录瞬间打回「建议重登」。
        newer_reject = any(event_time(s.get("auth_at")) > pending_at
                           for s in scopes.values())
        newer_detail = any(event_time(s.get("detail_at")) > pending_at
                           for s in scopes.values())
        pending = pending and not newer_reject and not newer_detail
        error = _State.login_errors.get(p, "")
        if active:
            status = "saving" if saving else "active"
        elif rejected:
            status = "login_required"
        elif error:
            status = "save_error"
        elif pending:
            status = "pending"
        elif available:
            status = "available"
        else:
            status = "saved" if saved else "missing"
        needs_login = rejected and not active
        # 账本拦截（滑块/登录门）：与「会话失效」是两件事，但都要人工处理。
        # 飞猪两端各一套会话，厂商标级只挂聚合证据、不改 status——否则
        # H5 被拦会把 PC 槽位一起点亮（槽位在下面按各自 entry 重算）。
        _blk = _path_block_from_rows(
            path_rows.get(p) or [],
            saved_at=max(saved_at, float(pending_at or 0)))
        if active or saving:
            _blk = None
        if _blk and p != "fliggy":
            status = ("challenge" if _blk["kind"] == "captcha"
                      else "login_required")
            needs_login = True
        plats[p] = {
            "saved": saved, "saved_at": saved_at, "active": active,
            "saving": saving, "status": status, "pending": pending,
            "needs_login": needs_login, "health_need_login": needs_login,
            "stale": bool(getattr(REGISTRY[p], "login_suspect", False)),
            "error": error, "scopes": scopes, "challenge": _blk or {},
        }
    slots = {}
    for key in LOGIN_SLOT_ORDER:
        meta = LOGIN_SLOTS[key]
        # r1063 T179：**凡独立端槽位**（槽位名≠渠道名，如 ctrip_h5）都按
        # 自己的 profile 算状态。此前只有 fliggy_h5 走这条路，其余 `_h5`
        # 抄渠道级状态 → 没登录也显示「会话有效·明细可用」（假可用）。
        if key != meta.get("plat"):
            snap = _os.path.join(root, meta["profile"], "session-state.json")
            saved = _os.path.isfile(snap)
            try:
                saved_at = float(slot_crawler(
                    key, cfg, _State.logger).session_saved_at or 0)
            except Exception:
                saved_at = 0.0
            session = _State.login_sessions.get(key) or {}
            active = bool(session)
            saving = bool(session.get("saving"))
            pending_at = _State.login_pending.get(key, 0)
            pending = bool(pending_at and _t.time() - pending_at < 600)
            verify = dict(_SLOT_VERIFY.get(key) or {})
            error = _State.login_errors.get(key, "")
            if active:
                status = "saving" if saving else "active"
            elif verify.get("status") == "challenge":
                status = "challenge"
            elif verify.get("status") == "login_required":
                status = "login_required"
            elif verify.get("status") == "error":
                status = "save_error"
            elif error:
                status = "save_error"
            elif verify.get("status") == "page_ok":
                status = "page_ok"
            elif pending:
                status = "pending"
            elif saved:
                status = "saved"
            else:
                status = "missing"
            # 账本上搜索路径的拦截比「入口页可达」更具体：入口页能开、
            # 搜索却被滑块挡住时，核验会写 page_ok——不能拿它盖掉事实。
            _blk = _path_block_from_rows(
                path_rows.get(meta["plat"]) or [], entry="h5",
                saved_at=max(saved_at, float(pending_at or 0)))
            if active or saving:
                _blk = None
            if _blk:
                status = ("challenge" if _blk["kind"] == "captcha"
                          else "login_required")
            needs_login = status in ("login_required", "challenge")
            # 三态分离：已保存（persisted）≠ 会话已核验 ≠ 本次明细成功。
            # H5 页面核验只能证明入口可达；不把 page_ok 当明细证据。
            page_ok = status == "page_ok"
            # r1063 T270：**端面自己的通路真的出过数**才算明细可用。
            # 写死 False 会让"已登录的 H5"永远停在「已保存·待验证」。
            detail_ok = _surface_detail_ok(
                path_rows.get(meta["plat"]) or [], meta.get("surface") or "")
            session_verified = page_ok or detail_ok
            # r1063 T270b：**detail_ok 抬成 available**。否则即便该端面昨天
            # 真的出过数，卡片仍停在「已保存·待验证」——用户读作"登录没生效"。
            # 但被拦（challenge/login_required）不许被"出过数"盖掉。
            if detail_ok and status in ("saved", "pending", "page_ok"):
                status = "available"
            slots[key] = {
                "slot": key, "plat": meta["plat"], "surface": meta["surface"],
                "surface_label": meta["surface_label"],
                "name": meta["name"], "account": meta["account"],
                "requirement": meta["requirement"], "profile": meta["profile"],
                "login_url": meta["login_url"],
                "saved": saved, "saved_at": saved_at, "active": active,
                "saving": saving, "status": status, "pending": pending,
                "needs_login": needs_login,
                "health_need_login": needs_login, "stale": False,
                "error": error,
                "detail": verify.get("detail", ""),
                "verified_at": verify.get("at", ""),
                "page_ok": page_ok, "session_verified": session_verified,
                "detail_ok": detail_ok, "block": _blk or {},
            }
        else:
            base = dict(plats[meta["plat"]])
            _scopes = base.get("scopes") or {}
            _detail_ok = any(bool(v.get("detail_available"))
                             for v in _scopes.values())
            _sess_verified = bool(_scopes) and not base.get("needs_login") and (
                _detail_ok or any(v.get("auth_at") for v in _scopes.values()))
            # 厂商标级为飞猪刻意保留「未按端改写」的 status，槽位按自己的
            # entry 重算：PC 被拦只点亮 PC 槽，H5 的拦截留在 H5 槽。
            _blk = _path_block_from_rows(
                path_rows.get(meta["plat"]) or [],
                entry=meta.get("surface") or "",
                saved_at=max(float(base.get("saved_at") or 0),
                             float(_State.login_pending.get(key, 0) or 0)))
            if base.get("active") or base.get("saving"):
                _blk = None
            _st = base.get("status") or ""
            _nl = bool(base.get("needs_login"))
            if _blk:
                _st = ("challenge" if _blk["kind"] == "captcha"
                       else "login_required")
                _nl = True
            # r1063 T250：**PC 槽位也要读核验结果**。此前这里把 verified_at
            # 写死成空、detail 写死空，只有 H5 分支读 `_SLOT_VERIFY`——
            # 于是"核验成功"在 PC 卡片上完全看不见，按钮还是「立即核验」，
            # 用户读到"核验了却一直要我核验"（issue #15）。
            _pv = dict(_SLOT_VERIFY.get(key) or {})
            _pv_st = str(_pv.get("status") or "")
            if not (_blk or base.get("active") or base.get("saving")):
                if _pv_st == "challenge":
                    _st, _nl = "challenge", True
                elif _pv_st == "login_required":
                    _st, _nl = "login_required", True
                elif _pv_st == "page_ok" and _st in ("pending", "saved", ""):
                    _st = "page_ok"
            slots[key] = dict(base, **{
                "slot": key, "plat": meta["plat"],
                "surface": meta["surface"],
                "surface_label": meta["surface_label"],
                "name": meta["name"], "account": meta["account"],
                "requirement": meta["requirement"], "profile": meta["profile"],
                "login_url": meta["login_url"],
                "detail": _pv.get("detail", ""),
                "verified_at": _pv.get("at", ""),
                "page_ok": _st == "page_ok", "session_verified": _sess_verified,
                "detail_ok": _detail_ok,
                "status": _st, "needs_login": _nl,
                "health_need_login": _nl, "block": _blk or {},
                "challenge": _blk or {},
            })
    # r1169：两条分支（独立端 / 厂商级）各自算完 status 之后，**在这里统一**
    # 补 state7 / state_cn —— 单一真源只写一次，前端不再自己造中文。
    for _k, _s in slots.items():
        _closed = bool((LOGIN_SLOTS.get(_k) or {}).get("service_closed"))
        _s7, _scn = _slot_state7(_s.get("status"), _closed)
        _s["state7"] = _s7
        _s["state_cn"] = _scn
    for _p, _s in plats.items():
        _s7, _scn = _slot_state7(_s.get("status"))
        _s["state7"] = _s7
        _s["state_cn"] = _scn
    try:
        _ensure_slot_verify_loop()
    except Exception:
        pass
    return {"ok": True, "plats": plats, "slots": slots,
            # 槽位顺序也由后端下发：前端不许再硬编码一份（第二份声明）。
            "slot_order": list(LOGIN_SLOT_ORDER),
            "state7_table": [{"code": c, "cn": n} for c, n in SLOT_STATE7]}


def _challenge_target(key: str) -> dict:
    """账本里该槽位**可打开的验证页**（服务端唯一取 URL 的地方）。"""
    v = _login_state_view()
    sl = (v.get("slots") or {}).get(str(key or "")) or {}
    blk = sl.get("block") or {}
    if str(blk.get("kind") or "") != "captcha":
        return {"ok": False, "err": "该槽位当前没有待处理的人机验证"}
    if not blk.get("url"):
        return {"ok": False,
                "err": "账本没有记录被拦页地址——请用「弹窗登录」完成验证"}
    _p = str(blk.get("path") or "").upper()
    return {"ok": True, "plat": str(sl.get("plat") or ""), "slot": str(key),
            "url": str(blk.get("url")),
            "desktop": _p.startswith("PC"), "mobile": _p.startswith("H5")}


def _spawn_cli_login(plat: str) -> tuple:
    """另起一个进程跑 `--login <plat>`（= 终端里那条命令）。

    为什么需要（GitHub #14）：macOS 打包版里进程内的有头窗口打不开，而
    同一台机器跑 `--login` 却能弹。与其让用户自己开终端，不如**按钮直接走同一条路**。
    返回 (ok, detail)。
    """
    import subprocess
    import sys as _sys
    plat = str(plat or "").strip()
    if not plat:
        return False, "缺少渠道"
    try:
        if getattr(_sys, "frozen", False):
            cmd = [_sys.executable, "--login", plat]
        else:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "main.py")
            cmd = [_sys.executable, script, "--login", plat]
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(cmd, cwd=os.getcwd(), close_fds=True, **kw) \
            if os.name != "nt" else subprocess.Popen(cmd, cwd=os.getcwd(), **kw)
        return True, "已在独立进程打开登录窗口（与命令行 --login 同一条路）"
    except Exception as e:
        return False, "另起登录进程也失败：%s" % str(e)[:120]


def _login_phase_view(key: str) -> dict:
    """登录流程的**服务端真实阶段**（给按钮文案用，不当进度条）。

    前端原来的秒表只是从点击时刻起算 Date.now() 差值，与登录窗口的
    真实状态无关：用户切到登录窗口后，控制台页面被浏览器节流，
    setInterval 从 500ms 掉到分钟级，秒数就停住，读作卡死。这里回后端
    真实阶段，前端只负责把它翻成中文；秒数仅作辅助信息。
    """
    import time as _t
    key = str(key or "")
    sess = _State.login_sessions.get(key)
    if not sess:
        return {"ok": True, "slot": key, "active": False, "phase": "",
                "msg": "", "phase_s": 0, "elapsed_ms": 0, "err": ""}
    now = _t.time()
    phase = str(sess.get("phase") or "")
    since = float(sess.get("phase_at") or now)
    opened = float(sess.get("opened_at") or 0)
    msg = {
        "queued": "排队等采集让出该渠道（已请求叫停本轮）",
        "opening": "正在启动浏览器并打开登录页",
        "waiting_user": "窗口已打开，请在窗口里完成登录",
        "saving": "正在保存会话",
        "saved": "会话已保存",
        "error": "登录未完成",
    }.get(phase, "")
    return {"ok": True, "slot": key, "active": True, "phase": phase,
            "phase_s": max(0, int(now - since)),
            "elapsed_ms": (int((now - opened) * 1000) if opened else 0),
            "msg": msg, "err": str(sess.get("error") or "")}


def _start_login(plat: str, slot: str = "", url: str = "",
                 desktop: bool = False, mobile: bool = False) -> dict:
    """网页登录：按登录槽位弹出有头浏览器窗口并保存独立会话。

    `url` 非空时改为打开**账本里被拦截的那一页**（人机验证入口），并按
    采集时的身份档（PC 块 → 桌面档）打开：在手机档/登录页过完验证，
    下一轮 PC 采集仍会被站点当成换端而继续拦。URL 只由服务端从
    `fetch_paths.request_url` 取，不接受客户端传入。
    """
    import time as _t
    key = str(slot or plat or "")
    meta = LOGIN_SLOTS.get(key)
    if meta is None or (plat and meta.get("plat") != plat):
        return {"ok": False, "err": "未知登录槽位: %s" % key}
    # pending 验证窗防重入：同一槽位刚保存时拒绝第二个窗口。
    _lp = _State.login_pending.get(key)
    if (_lp is not None and _t.time() - _lp < 600
            and not _login_state_view()["slots"][key]["needs_login"]):
        return {"ok": False,
                "err": "该登录槽位刚保存，正在核验——无需重复登录"}
    with _State.lock:
        if key in _State.login_sessions:
            return {"ok": False,
                    "err": "该登录槽位窗口已打开——请在窗口完成登录后点「我已登录完成」"}
        # 有头浏览器可行性（GitHub #10）：这个接口只是「起线程」，真正的
        # 开窗在后台发生——在没有图形环境的容器里（Docker / 无 X 的 Linux）
        # 必然失败，而用户收到的是「登录窗口已弹出」，随后什么也没发生，
        # 八个浏览器、两种系统都试过也没用（issue 原话）。这里同步判一次，
        # 把「打不开」的原因直接回给点击者，而不是让他等一个不存在的窗口。
        _no_gui = _no_graphical_env()
        if _no_gui:
            _msg = ("当前服务没有图形环境（未设置 DISPLAY / WAYLAND_DISPLAY），"
                    "无法弹出有头浏览器窗口。Docker 部署请改用「导入会话」或"
                    "在宿主机本机运行后用同一份 user_data；命令行可用 "
                    "python main.py --login 在桌面环境完成登录。")
            _State.login_errors[key] = _msg
            return {"ok": False, "err": _msg, "kind": "no_gui"}
        evt = threading.Event()
        # ready（r620）：线程里「登录页真的载入完成」才置位。接口据此
        # 区分「窗口开了」与「根本没开成」，不再一律回报「已弹出」。
        ready = threading.Event()
        session = {"evt": evt, "done": threading.Event(),
                   "ready": ready, "saving": False,
                   "saved": False, "error": "",
                   # 服务端真实阶段（前端按钮文案据此显示，不再拿自由秒表
                   # 冒充进度）：queued → opening → waiting_user →
                   # saving → saved / error
                   "phase": "queued", "phase_at": _t.time(),
                   "opened_at": 0.0}
        _State.login_errors.pop(key, None)
        # r1063 T183：登录窗要拿和采集同一把渠道锁。开会话就请采集收尾，
        # 否则用户要干等一轮（并且超时后线程仍会开窗 → 窗口一直闪）。
        session["cancel"] = threading.Event()
        _State.login_sessions[key] = session
    try:
        from core import interrupt as _itr
        _itr.request(by="browser-login")
        _State.logger.info("[登录] %s 已请求叫停本轮为登录让路", key)
    except Exception:
        pass
    cfg = _effective_crawler_config()
    logger = _State.logger

    def _run():
        try:
            crawler = slot_crawler(key, cfg, logger)
            if url and (desktop or mobile):
                # 被拦页是什么端面，验证就用同一身份档：PC 块用桌面档、
                # H5 块用手机档。跨档过完验证，采集下一轮仍会被当成换端。
                try:
                    crawler.use_mobile = bool(mobile)
                except Exception:
                    pass
            # 与采集共用同一把渠道锁：登录窗口和定时采集不能同时打开
            # 同一 profile（否则 SessionBusy 或两份上下文互相覆盖会话）。
            # 锁键用平台名（采集侧 channel_slot(c.name)）；用 profile_name
            # 会和采集侧的键分叉。测试替身没有 .name 时回退到槽位平台。
            _lock_key = str(meta.get("plat") or key)
            # 排队标记（r620）：采集正占着这把锁时，这里是**正常等待**，
            # 不是「窗口打不开」。等待方据此不判失败，也不会误报原因。
            session["queued"] = True
            with channel_slot(_lock_key):
                session["queued"] = False
                session["phase"] = "opening"
                session["phase_at"] = _t.time()
                # r1063 T183：等锁期间调用方已判超时并取消 → 不许再开窗
                # （否则就是"僵尸窗口"：面板说失败，窗口却在几十秒后弹出来）。
                if session.get("cancel") is not None \
                        and session["cancel"].is_set():
                    raise RuntimeError("登录请求已取消（等待渠道锁超时）")
                if url:
                    # 打开被拦页本身（列表/搜索页），人工过关后关窗即保存。
                    confirmed = crawler.open_challenge_window(
                        url, evt, timeout_s=600, idx=0,
                        ready_evt=session.get("ready"))
                else:
                    # 并发的登录窗按序错开位置，避免几个窗口叠在同一坐标
                    # 反复互相遮挡（用户误以为窗口在不停重开）。
                    _win_idx = max(0, min(4,
                                          len(_State.login_sessions) - 1))
                    confirmed = crawler._login_window(
                        evt, _win_idx, timeout_s=600,
                        ready_evt=session.get("ready"))
            if not confirmed and not evt.is_set():
                raise RuntimeError("登录窗口已关闭，尚未确认完成")
            session["phase"] = "saving"
            session["phase_at"] = _t.time()
            session["saved"] = True
            _State.login_pending[key] = _t.time()
            try:
                from crawlers import REGISTRY as _R
                cls = _R.get(meta["plat"])
                if cls is not None and "_cooldown_until" in vars(cls):
                    cls._cooldown_until = 0
            except Exception:
                pass
            if _State.login_saved_cb:
                try:
                    _State.login_saved_cb(meta["plat"])
                except Exception:
                    _State.logger.warning(
                        "[登录] %s 会话已保存，采集缓存刷新失败", key)
            _State.logger.info("[登录] %s 会话已保存（%s）", key,
                               "人机验证" if url else "网页登录")
            session["phase"] = "saved"
            session["phase_at"] = _t.time()
            # 重登入账（r478）：这是对成功率影响最大的一次干预（实测去哪儿
            # 国际 H5 被登录墙拦 13/17 后重登即恢复出数），但原先只有
            # warm/verify/probe/reset 写 interventions——重登过什么、之后
            # 有没有真的恢复，账本与溯源都查不到，节流面板的「上次干预
            # 44%→100%」也永远不会以重登为分界。槽位写进 scope，PC/H5
            # 各自可分；after 留给后台采集去填，不在这里编造。
            try:
                _rls = PriceStorage(_anchored(
                    ((_State.cfg or {}).get("output") or {}).get(
                        "db_path"), "data/prices.db"))
                # 幂等（r496）：实测账本里每次重登都**稳定写两条**（同秒同槽位，
                # id 连号无间断，07:13→11:00 全部如此）。溯源里并排两条一模一样
                # 的「重登」，用户会以为自己按了两次。
                # 注意：重复行**不**放大 intervention_success_rate 的分母
                # （同秒记录在按 (plat,i) 分组时会被合并，n 仍是 1，已用测试钉住）
                # ——所以这里是可读性修复，不要据此去改指标逻辑。
                # 同槽位 30 秒内已记过就不再写（一次登录动作 = 一条记录）。
                # 用 30 秒而不是「同一分钟」：同一分钟内用户真的重试一次
                # （第一次没通过、立刻再登）是**另一次干预**，按分钟去重会
                # 把真实的重试吞掉，账本少一条。30 秒足够挡住同一次保存
                # 尾部的重复写入（实测两条时间戳精确到秒完全一致）。
                _dup = False
                try:
                    _now = time.time()
                    for _r0 in _rls.interventions(meta["plat"], 8):
                        if (str(_r0.get("action")) != "relogin"
                                or str(_r0.get("scope")) != str(key)):
                            continue
                        try:
                            _ts = time.mktime(time.strptime(
                                str(_r0.get("at") or "")[:19],
                                "%Y-%m-%d %H:%M:%S"))
                        except Exception:
                            continue
                        if abs(_now - _ts) <= 30:
                            _dup = True
                            break
                except Exception:
                    _dup = False
                if not _dup:
                    _rls.save_intervention(
                        meta["plat"], "relogin", ok=True, scope=str(key),
                        before=("captcha" if url else "login_wall"),
                        note=(("人机验证完成，会话已保存（%s）" % url)
                              if url else
                              ("网页登录保存会话（槽位 %s / %s）" % (
                                  key, meta.get("surface_label") or "全端"))))
            except Exception:
                _State.logger.warning("[登录] %s 干预入账失败", key)
            # r1063 T128：登录成功 → 立刻清登录墙记忆（否则下一轮仍短路）
            try:
                _cleared = _clear_login_wall_memo(
                    str(meta.get("plat") or plat), key)
                if _cleared:
                    _State.logger.info("[登录] %s 已清登录墙记忆：%s", key,
                                       "、".join(_cleared))
            except Exception:
                pass
            # r1063 T134：清完墙立刻在后台复探一次，用户不用等下一轮
            try:
                _kick_login_probe(str(meta.get("plat") or plat))
            except Exception:
                pass
            if str(key or "").endswith("_h5"):
                threading.Thread(target=_verify_login_slot,
                                 args=(key,), daemon=True,
                                 name="slot-verify").start()
        except Exception as e:
            # 原因分层（r620）：ready 未置位 = 窗口根本没开成，把真实异常
            # 带给点击者（这是 #10 的核心：不能只说「详见日志」）；
            # 开过之后才失败（关窗未确认 / 保存出错）仍用中文安全摘要，
            # 不把内部堆栈甩到界面上。
            _was_open = bool(session.get("ready") is not None
                             and session["ready"].is_set())
            if _was_open:
                session["error"] = "会话保存未完成，请重试登录；详见本机日志"
            else:
                # r1063 T71：进程内开不出来时，可退回"命令行那条路"（macOS 打包版实测有效）。
                # **默认关闭**（r620 契约）：兜底成功会清空 error，把"真实原因"变成
                # 一句笼统话。macOS 用户需要时在 config 写 `web.login_cli_fallback: true`。
                _fb_on = bool((((_State.cfg or {}).get("web") or {})
                               .get("login_cli_fallback") or False))
                _pok, _pdetail = ((False, "未开启 login_cli_fallback")
                                  if not _fb_on else
                                  _spawn_cli_login(str(meta.get("plat") or plat)))
                if _pok:
                    session["error"] = ""
                    session["cli_fallback"] = _pdetail
                    _State.login_errors.pop(key, None)
                    _State.logger.info("[登录] %s %s", key, _pdetail)
                else:
                    session["error"] = "登录窗口没能打开：%s / %s" % (
                        (str(e)[:120] or type(e).__name__), _pdetail)
            _State.login_errors[key] = session.get("error") or ""
            _State.login_pending.pop(key, None)
            session["phase"] = "error"
            session["phase_at"] = _t.time()
            _State.logger.warning("[登录] %s 登录窗口异常: %s", key, e)
        finally:
            with _State.lock:
                if _State.login_sessions.get(key) is session:
                    _State.login_sessions.pop(key, None)
            session["done"].set()

    threading.Thread(target=_run, daemon=True).start()
    # 「已弹出」必须是事实（r620 · GitHub #10）：起线程 ≠ 窗口打开，
    # Playwright 起不来时那一步永远到不了。这里等 ready（最多 45 秒，
    # goto 自带 40 秒超时），拿到才回报成功；线程先失败就如实回报原因。
    _deadline = _t.time() + 45
    _t0 = _t.time()
    _ok_ready = ready.wait(0.5)
    while not _ok_ready and _t.time() < _deadline:
        if session.get("done").is_set():
            break            # 线程已结束（失败或关窗），不再等
        _ok_ready = ready.wait(0.5)
    if not _ok_ready:
        # r1063 T183：**排队中 ≠ 打不开**。采集正占着渠道锁时，窗口会在
        # 采集收尾后自动弹出（我们已经请求叫停本轮），不能报失败让用户狂点
        # （每点一次就多一只线程排队 → 窗口轮流开合，就是"一直闪"）。
        if bool(session.get("queued")):
            _State.logger.info(
                "[登录] %s 正在排队等采集让出渠道锁（已请求叫停本轮），"
                "窗口稍后会自动弹出", key)
            return {"ok": True, "plat": meta["plat"], "slot": key,
                    "queued": True, "pending_open": True,
                    "next": "正在等采集让出该渠道（已请求叫停本轮）；"
                            "窗口会自动弹出，请稍候，不要重复点击"}
        with _State.lock:
            _err = str(session.get("error") or "")
            if _State.login_sessions.get(key) is session:
                _State.login_sessions.pop(key, None)
        # 非排队仍没打开：**取消后台线程**，否则它稍后拿到锁还会开一个
        # 僵尸窗口（面板已报失败，用户却看到窗口弹出来）。
        try:
            session["cancel"].set()
            session["evt"].set()
        except Exception:
            pass
        _msg = (_err or "登录窗口未能在 45 秒内打开（可能是缺少浏览器内核、"
                "显示服务不可用，或该渠道 profile 正被采集占用）；"
                "详见本机日志 logs/monitor.log")
        _State.login_errors[key] = _msg
        _State.logger.warning("[登录] %s 登录窗口未能打开：%s", key, _msg)
        return {"ok": False, "err": _msg, "kind": "window_failed"}
    _State.logger.info("[登录] 已弹出 %s 登录窗口", key)
    # 窗口真的开了才进入「等用户操作」阶段——前端据此把按钮从
    # 「正在打开窗口」换成「窗口已打开，请去完成登录」。
    session["phase"] = "waiting_user"
    session["phase_at"] = _t.time()
    session["opened_at"] = _t.time()
    # 开窗耗时如实回传：用户在等待期间只能看到一个静态「正在打开窗口…」，
    # 分不清「在排队等渠道锁」和「在等浏览器启动」。实测（2026-11-01）
    # 起窗耗时主要取决于是否撞上采集锁，两者对用户意味着完全不同的处置
    # （前者只需等，后者要查浏览器）。
    return {"ok": True, "plat": meta["plat"], "slot": key,
            "waited_ms": int((_t.time() - _t0) * 1000),
            "queued": bool(session.get("queued"))}


def _profile_session_file(plat: str, slot: str = "") -> str:
    """该槽位浏览器 profile 里的 storage state 路径（优先 slot 再 plat）。"""
    names = [str(slot or ""), str(plat or "").split(":")[0]]
    base = str(plat or "").split(":")[0]
    if base.endswith("_h5"):
        base = base[:-3]
    names.append(base)
    for n in names:
        if not n:
            continue
        p = os.path.join(str((_State.cfg or {}).get("crawler", {}).get(
            "user_data_dir", "user_data")), n, "session-state.json")
        if os.path.isfile(p):
            return p
    return ""


def _finish_login(plat: str, slot: str = "") -> dict:
    key = str(slot or plat or "")
    sess = _State.login_sessions.get(key)
    if not sess:
        # r1063 T139：没有窗口也算保存——只要 profile 里已有会话文件（6 小时内）。
        # r1161：**陈旧会话不等于"没有会话文件"**。以前只要 mtime ≥ 6h 就落进
        # "profile 里没有会话文件"这条错误文案里，用户照着提示反复重登也修不好
        # （途牛「保存登录」保存不了）。现在把两种情况拆开：
        #   * 会话还新鲜 → 照旧按已有登录态保存；
        #   * 会话陈旧 → 仍不假装"刚登录"（守住 r1063 的诚实契约），但**自动发起
        #     一次真核验**（*_h5 走页面核验，PC 走真查询自检），让状态自己更新，
        #     并把"多久没更新"如实说出来；
        #   * 真的没文件 → 文案承认"还没有任何登录记录"。
        f = _profile_session_file(plat, key)
        age_h = None
        if f:
            try:
                age_h = max(0.0, (time.time() - os.path.getmtime(f)) / 3600.0)
            except Exception:
                age_h = None
        if f and (age_h is None or age_h < 6):
            cleared = []
            try:
                cleared = _clear_login_wall_memo(str(plat or ""), key)
            except Exception:
                pass
            try:
                _kick_login_probe(str(plat or ""))
            except Exception:
                pass
            _State.logger.info(
                "[登录] %s 无活动窗口，按已有登录态保存（%s，清理 %s，会话龄 %.1f 小时）",
                key, os.path.basename(f), "、".join(cleared) or "无",
                age_h if age_h is not None else -1.0)
            return {"ok": True, "plat": plat, "slot": key, "saved": True,
                    "profile_already_logged_in": True,
                    "cleared": cleared,
                    "age_h": round(age_h, 2) if age_h is not None else None,
                    "stale": False,
                    "next": "已按浏览器现有登录态保存（状态待核验后更新）"}
        if f:
            try:
                _kick_login_probe(str(plat or ""))
            except Exception:
                pass
            verifying = False
            if str(key or "").endswith("_h5"):
                try:
                    threading.Thread(target=_verify_login_slot, args=(key,),
                                     daemon=True,
                                     name="slot-verify-stale").start()
                    verifying = True
                except Exception:
                    verifying = False
            _State.logger.info(
                "[登录] %s 现有会话已 %.1f 小时未更新，不按新登录保存（已发起核验=%s）",
                key, age_h if age_h is not None else -1.0, verifying)
            return {"ok": False,
                    "err": ("该槽位没有进行中的登录窗口；现有会话已 %.1f 小时未更新，"
                            "不能当作刚登录" % (age_h if age_h is not None else 0.0)),
                    "hint": "已自动发起核验；也可点「去登录」重登一次（登完直接关窗即保存）",
                    "stale": True,
                    "age_h": round(age_h, 2) if age_h is not None else None,
                    "verifying": verifying}
        return {"ok": False,
                "err": ("该槽位没有进行中的登录窗口，且还没有任何登录记录"
                        "（profile 里没有会话文件）"),
                "hint": "先点「去登录」打开窗口，登完**直接关窗**即可（关窗即保存）"}
    globals().get("_PROBE_CHALLENGE_TS", {}).pop(plat, None)
    try:
        from crawlers import REGISTRY as _R
        _cls = _R.get(plat)
        if _cls is not None and "_cooldown_until" in vars(_cls):
            _cls._cooldown_until = 0
    except Exception:
        pass
    sess["saving"] = True
    sess["phase"] = "saving"
    sess["phase_at"] = time.time()
    SRX_LOGIN_T=0;SCAT=0;
    sess["evt"].set()
    # Acknowledges the save request; only the worker may publish saved/pending.
    return {"ok": True, "plat": plat, "slot": key,
            "saving": True, "saved": False}


# 登录槽位的 plat → 同厂商的 App 渠道（登录一次，两边都清墙）
# r1163：**从 APP_CHANNELS 派生，禁止写死**。此前 tuniu 指向 "app_tuniu"，而
# `core.channels.APP_CHANNELS` 只有五家（app_zhixing / app_qunar / app_fliggy /
# app_ctrip / app_tongcheng）——不存在 app_tuniu。于是途牛登录保存后，
# 「同厂商一起清墙」和「同厂商 App 复探」对途牛静默失效，用户读到的是
# 「APP 也登录了，但页面没变」。派生写法天然对齐：加渠道自动生效，删渠道不再幽灵。
VENDOR_APP_PLATS = {
    _vp: tuple(_va for _va in _APP_CHANNELS if _va == "app_" + _vp)
    for _vp in PLATFORMS
}


def _kick_login_probe(plat: str) -> dict:
    """登录成功后异步复探（r1063 T134）：浏览器通路 + 同厂商的 App 渠道。

    不阻塞登录请求：起一个 daemon 线程顺序探，结果写进路径账（矩阵里可见）。
    任何异常都吞掉——登录已经是成功路径。
    """
    try:
        on = bool(((_State.cfg or {}).get("web") or {})
                  .get("login_reprobe", True))
    except Exception:
        on = True
    if not on:
        return {"ok": False, "why": "已配置关闭（web.login_reprobe=false）"}
    cb = getattr(_State, "probe_cb", None)
    if cb is None:
        return {"ok": False, "why": "probe_cb 未挂接"}

    base = str(plat or "").split(":")[0]
    if base.endswith("_h5"):
        base = base[:-3]
    targets = [base] + [t for t in VENDOR_APP_PLATS.get(base, ())
                        if t in _ALL_PLATS]
    targets = [t for t in targets if t in _ALL_PLATS]

    def _run():
        for t in targets:
            try:
                out = cb(t, scope="")
                ok = bool((out or {}).get("ok"))
                rows = (out or {}).get("rows")
                _State.logger.info("[登录] 自动复探 %s → ok=%s rows=%s",
                                   t, ok, rows)
            except Exception as e:
                _State.logger.warning("[登录] 自动复探 %s 异常：%s", t,
                                      str(e)[:120])

    threading.Thread(target=_run, daemon=True, name="login-reprobe").start()
    return {"ok": True, "targets": targets}


def _clear_login_wall_memo(plat: str, key: str = "") -> list:
    """清掉某渠道的登录墙记忆（App 侧 json + service_state memo）。

    返回被清掉的项（用于日志）。任何异常都不抛出——登录已经是成功路径，
    清理失败不该让它变成失败。
    """
    cleared = []
    base = str(plat or "").split(":")[0]
    # 槽位 plat 可能带端的后缀（fliggy_h5 / ctrip_h5…），厂商名要再去掉 _h5
    if base.endswith("_h5"):
        base = base[:-3]
    names = {base, str(key or "")}
    # r1063 T130：同厂商的 App 渠道也一起清（浏览器登录成功 = 账号可用）
    for v, apps in VENDOR_APP_PLATS.items():
        if base == v or base in apps:
            names.update(apps)
            names.add(v)
    names.discard("")
    try:
        from core.yield_stats import user_data_root
        root = str(user_data_root(_effective_crawler_config()))
    except Exception:
        root = "user_data"
    for p in sorted(names):
        f = os.path.join(root, p, "login_wall.json")
        try:
            if os.path.isfile(f):
                os.remove(f)
                cleared.append(p)
        except Exception:
            pass
        try:
            from core import service_state as _ss
            for kind in ("login_wall", "app_gone"):
                if _ss.until(root, p, kind) > 0:
                    _ss.clear(root, p, kind)
                    cleared.append("%s·%s" % (p, kind))
        except Exception:
            pass
    return cleared


def _verify_login_slot(key: str) -> dict:
    """Open any slot that has a saved session and classify the real page.

    只记录真实页面结果：跳登录页 → `login_required`，验证页 → `challenge`，
    干净页面 → `page_ok`（不等于"出价可用"）。

    r1153：**不再写死 fliggy_h5**。此前只有飞猪 H5 能页面核验，其余 8 个槽位
    点「核验」直接被 400 拒掉；而 `/api/login-state` 对 PC/H5 槽位都读本函数
    的结果（r1063 T250）——闸门不放行，它们就永远停在"需核验"，用户读到的
    就是「我登录了，但你页面没变」。
    """
    meta = LOGIN_SLOTS.get(str(key or ""))
    if not meta:
        return {"ok": False, "err": "未知登录槽位：%s" % key}
    try:
        from crawlers.challenge import classify_text
        cfg = _effective_crawler_config()
        crawler = slot_crawler(key, cfg, _State.logger)
        if not os.path.isfile(crawler.session_state_path):
            return {"ok": False, "err": "该槽位还没有保存会话"}
        with crawler.browser(headless=True) as ctx:
            page = crawler.new_page(ctx)
            page.goto(meta["login_url"], wait_until="domcontentloaded",
                      timeout=40000)
            page.wait_for_timeout(4000)
            page_url = str(getattr(page, "url", "") or "")
            body = page.inner_text("body")[:4000]
        # r1063 T253：核验打开的就是登录页，忽略 URL 启发式（否则永远判需登录）
        sig = classify_text(body, page_url, ignore_url=True)
        if sig is not None and sig.status == "blocked":
            status, detail = "challenge", sig.detail
        elif sig is not None and sig.status == "login":
            status, detail = "login_required", sig.detail
        else:
            status, detail = "page_ok", "页面未命中登录墙/验证"
    except Exception as e:
        status, detail = "error", str(e)[:160]
    result = {"ok": status != "error", "status": status, "detail": detail,
              "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              # r1153：留时间戳，供 _slots_due_for_verify() 挑"最久没核验"的槽位
              "ts": time.time()}
    with _SLOT_VERIFY_LOCK:
        _SLOT_VERIFY[key] = result
    _slot_verify_save()          # r1156：结论落盘，重启后不退回「已存待验」
    return result


# ── 更新闭环（r1197）────────────────────────────────────────────
# 页面要能：看版本 → 一键检查 → 一键升级（后台带进度）→ 回滚 → 知道"要重启一次"。
# 升级/回滚的**文件语义**全在 `core/update.py`（已用真 zip 验过：备份、跳过用户
# 资产、失败回滚）；这里只做"状态机 + 触发线程"，不重复实现覆盖逻辑。
_UPDATE_LOCK = threading.Lock()
_UPDATE_JOB = {"state": "idle", "pct": 0, "msg": "", "ok": None, "at": ""}


def _update_status() -> dict:
    from core import update as _up
    try:
        info = _up.check()
    except Exception as e:
        info = {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:120])}
    with _UPDATE_LOCK:
        job = dict(_UPDATE_JOB)
    try:
        baks = _up.list_backups()
    except Exception:
        baks = []
    return {"ok": True,
            "local": str(_up.local_version() or ""),
            "latest": str(info.get("latest") or ""),
            "has_update": bool(info.get("has_update")),
            "reason": str(info.get("reason") or ""),
            "cached": bool(info.get("cached")),
            "check_err": str(info.get("err") or ""),
            "job": job, "backups": len(baks),
            "next": "升级与回滚都是文件替换，完成后需要重启一次程序"}


def _update_start_async() -> dict:
    """后台下载 + 应用；立刻返回。进度用 `/api/update/status` 轮询。"""
    # r1352：**先确认真的有新版本**再进下载状态。旧实现不查 has_update，
    # 页面在状态还没取回时点「下载并升级」也会起任务——最新版用户因此
    # 反复下载/覆盖同一个包。检查失败也不放行：宁可让人先重试检查。
    from core import update as _up0
    try:
        _chk = _up0.check()
    except Exception as e:
        return {"ok": False, "err": "无法确认新版本：%s: %s"
                % (type(e).__name__, str(e)[:100])}
    if not _chk.get("ok"):
        return {"ok": False, "err": "无法确认新版本：%s"
                % (_chk.get("err") or "检查更新失败")}
    if not _chk.get("has_update"):
        return {"ok": False, "err": "已是最新版本（%s），无需升级"
                % (_chk.get("latest") or _chk.get("local") or "")}
    with _UPDATE_LOCK:
        st = str(_UPDATE_JOB.get("state") or "idle")
        if st in ("downloading", "applying"):
            return {"ok": False, "err": "已经在升级中（%s）" % st,
                    "job": dict(_UPDATE_JOB)}
        _UPDATE_JOB.update({"state": "downloading", "pct": 5,
                            "msg": "准备中", "ok": None,
                            "at": time.strftime("%Y-%m-%d %H:%M:%S")})

    def _set(state, pct, msg):
        with _UPDATE_LOCK:
            _UPDATE_JOB.update({"state": state, "pct": int(pct),
                                "msg": str(msg)[:160]})

    def _run():
        from core import update as _up
        try:
            _set("downloading", 20, "正在下载更新包")
            _up.download()
            _set("applying", 60, "正在应用（先备份再覆盖）")
            rep = _up.apply()
            if rep.get("ok"):
                _set("done", 100, "已应用；请重启程序生效（备份：%s）"
                     % os.path.basename(str(rep.get("backup") or "")))
            else:
                _set("failed", 100, rep.get("err") or "应用失败")
            with _UPDATE_LOCK:
                _UPDATE_JOB["ok"] = bool(rep.get("ok"))
        except Exception as e:
            _set("failed", 100, "%s: %s" % (type(e).__name__, str(e)[:120]))
            with _UPDATE_LOCK:
                _UPDATE_JOB["ok"] = False

    threading.Thread(target=_run, daemon=True, name="update-apply").start()
    return {"ok": True, "state": "started", "job": dict(_UPDATE_JOB)}


def _slots_due_for_verify(verify_map, now=None, ttl_s=1800):
    """纯函数：从核验结果表里挑「最久没核验且已过期」的一个槽位键。

    * 没核验过的（无 `ts`）视为最旧，优先核验；
    * 全部新鲜 → 返回 None：宁可空转，也不要凭空多开一个浏览器
      （9 个槽位同时核验既慢，又像机器）。
    """
    now = time.time() if now is None else float(now)
    best, best_ts = None, None
    for key, info in dict(verify_map or {}).items():
        ts = float((info or {}).get("ts") or 0.0)
        if now - ts < float(ttl_s):
            continue
        if best_ts is None or ts < best_ts:
            best, best_ts = key, ts
    return best


def _slot_verify_loop():
    """定时核验**任一已保存会话的槽位**（不再写死 fliggy_h5）。

    r1153：每 5 分钟最多核验 1 个「最久没核验」的槽位；没有会话文件的槽位
    不进候选（没有会话就没什么可核验的，报错只会制造噪声）。
    """
    while True:
        time.sleep(300)
        try:
            cfg = _effective_crawler_config()
            cand = {}
            for key in LOGIN_SLOT_ORDER:
                # 只核验「以页面为证据」的独立端槽位（*_h5）；PC 槽位走真查询自检
                # （/api/channel/probe），拿载荷当证据，比打开登录页更可信。
                if not str(key or "").endswith("_h5"):
                    continue
                if _State.login_sessions.get(key):
                    continue          # 有活动窗口时由窗口自身收口
                try:
                    crawler = slot_crawler(key, cfg, _State.logger)
                except Exception:
                    continue
                if not os.path.isfile(crawler.session_state_path):
                    continue
                with _SLOT_VERIFY_LOCK:
                    cand[key] = dict(_SLOT_VERIFY.get(key) or {})
            due = _slots_due_for_verify(cand)
            if due:
                _verify_login_slot(due)
        except Exception:
            _State.logger.warning("[登录] 槽位定时核验异常", exc_info=True)


def _ensure_slot_verify_loop():
    global _SLOT_VERIFY_THREAD
    if _SLOT_VERIFY_THREAD is not None and _SLOT_VERIFY_THREAD.is_alive():
        return
    _SLOT_VERIFY_THREAD = threading.Thread(
        target=_slot_verify_loop, daemon=True, name="slot-verify-loop")
    _SLOT_VERIFY_THREAD.start()


def _quiet_view() -> dict:
    """夜间静默窗（r1739）：与 /api/pulse 同源，供页头改口用。

    读不到就返回 active=False——不能凭空说在静默。
    """
    try:
        _p = getattr(_State, "pacing", None)
        if _p is None:
            return {"start": "", "end": "", "active": False, "left_s": 0}
        _c = getattr(_p, "cfg", {}) or {}
        return {"start": str(_c.get("scan_quiet_start") or ""),
                "end": str(_c.get("scan_quiet_end") or ""),
                "active": bool(_p.quiet_now()),
                "left_s": int(_p.seconds_until_quiet_end() or 0)}
    except Exception:
        return {"start": "", "end": "", "active": False, "left_s": 0}


def _next_run() -> str:
    """调度器下一轮时间（SCHED 未起/打包单跑时返回空串）。
    demo 模式合成演示值：⏱ 倒计时 chip 与 header 三行折行形态是
    生产常态元素，demo 缺该字段时全链零覆盖（r302 审计 T1），
    --hdh 动态单源与吸顶补偿随之获得演示面回归载体。"""
    if DEMO["on"]:
        from datetime import timedelta as _td
        return (datetime.now() + _td(minutes=5)).strftime(
            "%Y-%m-%d %H:%M:%S")
    try:
        from core.scheduler import SCHED
        if SCHED:
            job = SCHED.get_job("price_monitor")
            if job and job.next_run_time:
                return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return ""


def _view_url(rr: dict, date: str, plat: str) -> str:
    """明细行内 ↗ 跳转链接——复用 Alerter._build_view_url，与各渠道爬虫
    已验证取数路径同源（链接必须点开有数据；qunar 为 touch H5 列表页
    与 H5 兜底出数同源）。
    空/未知平台返回 ""（宁缺勿错，与 alerter 同策略）——曾缺省回落
    "qunar"，控制台缺平台行会误出去哪儿链接（挂羊头风险）。"""
    try:
        from types import SimpleNamespace
        from core.alerter import Alerter
        ns = SimpleNamespace(from_code=(rr or {}).get("from", ""),
                             from_name=(rr or {}).get("from_name", ""),
                             to_code=(rr or {}).get("to", ""),
                             to_name=(rr or {}).get("to_name", ""))
        return Alerter._build_view_url(None, ns, date or "", plat or "")
    except Exception:
        return ""


def _mc_segments_of(r):
    """多程段（dict 配置或运行时 Route）；空=单 O-D。"""
    segs = (r.get("segments") if isinstance(r, dict)
            else getattr(r, "segments", None))
    return list(segs or [])


def _route_view(r) -> dict:
    """归一化航线：兼容 dict 配置（from/to）与运行时 Route 对象（from_code/to_code）。"""
    if isinstance(r, dict):
        d = r
    else:
        try:
            from dataclasses import asdict as _asdict
            d = _asdict(r)
        except Exception:
            return {}
    return {
        "from": d.get("from_code", d.get("from", "")),
        "to": d.get("to_code", d.get("to", "")),
        "from_name": d.get("from_name") or d.get("from", ""),
        "to_name": d.get("to_name") or d.get("to", ""),
        "dates": d.get("dates") or [],
        "alert_direct": float(d.get("alert_direct", 0) or 0),
        "alert_transfer": float(d.get("alert_transfer", 0) or 0),
        "transfer_arrival_max": d.get("transfer_arrival_max", "02:00"),
        "transfer_layover_min": int(d.get("transfer_layover_min", 0) or 0),
        "transfer_baggage": d.get("transfer_baggage", "") or "",
        "dep_time_min": d.get("dep_time_min", "") or "",
        "dep_time_max": d.get("dep_time_max", "") or "",
        # r342 三门（状态视图透传：前端卡头摘要/条件徽标可读）
        "transfer_layover_max": int(
            d.get("transfer_layover_max", 0) or 0),
        "exclude_stop": bool(d.get("exclude_stop", False)),
        "exclude_share": bool(d.get("exclude_share", False)),
        "price_max": float(d.get("price_max", 0) or 0),
        "no_cross": bool(d.get("no_cross", False)),
        "arr_time_min": d.get("arr_time_min", "") or "",
        "arr_time_max": d.get("arr_time_max", "") or "",
    }


def _routes_txt(routes) -> str:
    """用户卡头/教学卡/停用卡共用的航线摘要词面（在役与停用同源，
    双口径漂移防线）：同城市对聚合一段、日期随组——「上海→海口
    01-29/01-30、海口→上海 02-14」。逐航线直拼曾让同对不同日期各占
    一槽（「上海→海口、上海→海口、海口→上海」同对重复观感）且日期
    缺席。日期 MM-DD 短形、「/」并档；空日期组回退裸对。段内不产出
    分隔符「、」（前端按「、」切段逐段 nowrap）。截前面 [:3] 条目级
    截断语义维持（教学卡 n 计数另报总数）。"""
    groups = {}
    order = []
    for r in (routes or [])[:3]:
        rv = _route_view(r)
        if not rv:
            continue
        key = (rv["from_name"], rv["to_name"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        for d in rv["dates"]:
            if d and d not in groups[key]:
                groups[key].append(d)
    segs = []
    for fn, tn in order:
        base = f"{fn}→{tn}"
        ds = [d[5:10] if len(d) >= 10 else d for d in groups[(fn, tn)]]
        segs.append(f"{base} {'/'.join(ds)}" if ds else base)
    return "、".join(segs)


def _dep_win_of(r):
    """出发窗口元组（dict 路由配置 → (dmin,dmax)；未配置 None）——
    走势/日历取数与明细列表同窗（曲线与列表同口径）。"""
    dmin = (r.get("dep_time_min") or "").strip()
    dmax = (r.get("dep_time_max") or "").strip()
    return (dmin, dmax) if (dmin or dmax) else None


def _scan_marker_window():
    """本轮开始时刻（data/last_scan.json，main 每轮写）。

    同轮多航线按顺序完成可跨 8-10 分钟，420s 行间断口会把先完成的
    航线误判成补位；有轮次标记时以标记划轮，无标记才回退断口。
    陈旧/损坏标记不采，防崩溃轮把旧行当新轮——阈值随调度周期放宽：
    固定 45min 在 30min 周期下，一轮跑久/推迟就会让标记早于最后一
    批行失效，整页当轮真实明细被统一标成「补位」（用户实报满屏补位
    的根因之一）。取 周期×1.5+15min，夹在 45min…6h。
    """
    try:
        from datetime import datetime as _dt
        try:
            _iv = float(((_State.cfg or {}).get("schedule") or {}).get(
                "interval_minutes", 30) or 30)
        except Exception:
            _iv = 30.0
        # 一整轮跨 7 航线实测 ~22min：45min 上限在扫描稍晚时就把整轮
        # 标记判陈旧，回退 420s 断口 → 只剩最后一行算当轮，其余全标
        # 「补位」。取 周期×1.5+30（30min 周期=75min），覆盖一轮+一次
        # 调度延迟仍诚实（超期即不用标记，宁标补位不冒充当轮）。
        _ttl = min(360, max(75, _iv * 1.5 + 30)) * 60
        db = _anchored(((_State.cfg or {}).get("output") or {}).get("db_path"),
                       "data/prices.db")
        p = os.path.join(os.path.dirname(os.path.abspath(db)),
                         "last_scan.json")
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        start = str(j.get("start") or "").strip()
        if not start:
            return ""
        t = _dt.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
        if (_dt.now() - t).total_seconds() > _ttl:
            return ""
        return start
    except Exception:
        return ""


def _cluster_round_rows(rows, gap_s: int = 420, scan_start: str = ""):
    """按时间断口聚"轮"：倒序相邻行距 >gap_s 秒视为轮边界。

    一轮内多查询错峰完成跨 2-3 分钟、轮间隔 ~15 分钟——原"最新 1 分钟片"
    会切掉前几查询的明细。纯函数便于单测。
     收口 420s（观测收口：原 600s 曾把生产实测 483-503s 的相邻
    轮并桶——曲线桶取窗口内 min、列表 dedupe 取最新行，313 桶 6 桶
    口径分歧 1.9%（幅度 ≤￥253）；420 < 483 实测最小轮间隔，同轮改
    report._rounds 桶界（两套阈值曾 300/600 并存致「图有列无」——
    历史教训：两端必须同值）。轮内错峰跨 2-3 分钟仍同轮不受影响。
    语义刻意保持：曲线合并桶取窗口内最低价、列表 dedupe 只留最新行
    （最新快照语义）。"""
    from datetime import datetime as _dt

    def _ts(s):
        try:
            return _dt.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    if scan_start:
        start = _ts(scan_start)
        if start is not None:
            # 有轮次标记：只取本轮开始后的行，跨航线 8-10 分钟不再
            # 被 420s 断口切成“补位”；标记缺失/损坏时回退断口。
            return [r for r in rows
                    if (_ts(r["fetched_at"]) or start) >= start]

    out, prev_t = [], None
    for r in rows:
        t = _ts(r["fetched_at"])
        if prev_t is not None and t and (prev_t - t).total_seconds() > gap_s:
            break
        out.append(r)
        prev_t = t or prev_t
    return out


def _suspended_users(runtime_users, cfg_users):
    """停用态用户轻标记（停用态空态二分）：运行时 routes 空且配置
    同名用户名下航线全部 enabled=False 的用户。/api/state 用它区分
    「从未配置」（教学卡）与「已停用」（暂停卡+启用入口）两种空态——
    全停用用户在 states 过滤处被剔出（routes 空），不补此标记前端
    只能呈现教学卡，回归用户找心理线配置被误导。原始 routes 只从
    st.cfg 单一事实源取（热载安全，LESSONS 十二§1）；采集豁免层
    （main.build_routes）不动。"""
    cfg_by_name = {}
    for cu in cfg_users or []:
        if isinstance(cu, dict) and cu.get("name"):
            cfg_by_name[cu["name"]] = cu
    out = []
    for u in runtime_users or []:
        if not isinstance(u, dict) or u.get("routes"):
            continue
        cu = cfg_by_name.get(u.get("name") or "")
        if not cu:
            continue
        raw = [r for r in (cu.get("routes") or []) if isinstance(r, dict)]
        if not raw or any(r.get("enabled") is not False for r in raw):
            continue
        out.append({
            "name": cu.get("name") or "",
            "n": len(raw),
            "routesTxt": _routes_txt(raw),
        })
    return out


_PROBE_LOCK = threading.Lock()
_PROBE_LAST = 0.0
# 同一轮探针跨腿共享渠道浏览器上限 2；同渠道串行，避免同一 profile
# 被两个腿同时打开导致登录墙/会话占用（r366 国内腿实测 4 浏览器并发
# 触发 ctrip/fliggy/tongcheng 登录墙）。
_PROBE_CHANNEL_GATE = CHANNEL_GATE


def _probe_plat_lock(plat):
    return platform_lock(plat)
_PROBE_COOLDOWN = 60.0
# 被挑战/登录墙的渠道重试冷却：重试不得在冷却内再次打开验证页。
_PROBE_CHALLENGE_COOLDOWN = 900.0
_PROBE_CHALLENGE_TS = {}


def _probe_city_code(v):
    """城市输入 → IATA3：支持三字码 / 国内中文名 / 国际展示名（唯一前缀）。"""
    t = str(v or "").strip()
    if not t:
        return "", ""
    if len(t) == 3 and t.isalpha():
        code = t.upper()
        try:
            from core.citydata import CITY
            name = next((n for n, c in CITY.items() if c == code), code)
            if name == code:
                from core.intl import INTL_CITY_NAME
                name = INTL_CITY_NAME.get(code, code)
        except Exception:
            name = code
        return code, name
    try:
        from core.citydata import CITY
        from core.intl import INTL_CITY_NAME
        hits = {c for n, c in CITY.items() if n == t}
        for c, n in INTL_CITY_NAME.items():
            if n == t:
                hits.add(c)
        if not hits:
            # 唯一前缀（如"东京"→东京成田/东京羽田不唯一，宁可拒绝）
            hits = {c for n, c in CITY.items() if n.startswith(t)}
            for c, n in INTL_CITY_NAME.items():
                if n.startswith(t):
                    hits.add(c)
        if len(hits) == 1:
            code = next(iter(hits))
            name = next((n for n, c in CITY.items() if c == code),
                        INTL_CITY_NAME.get(code, code))
            return code, name
    except Exception:
        pass
    return "", ""


_PROBE_BATCH_MAX = 4
# 固定渠道优先级：故障处理、取数保障、核验深度与资源分配依此顺序；
# 价格/最低价/达标仍由真实数据决定，不因优先级改写结果。
PLATFORM_PRIORITY = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")


def _plat_rank(p):
    return PLATFORM_PRIORITY.index(p) if p in PLATFORM_PRIORITY else 99


def _probe_leg_plan(frm, to, date):
    """单条探针计划：城市/日期校验 + 展示名；调用方补条目序号。"""
    from datetime import datetime as _dt, date as _date
    fc, fn = _probe_city_code(frm)
    tc, tn = _probe_city_code(to)
    if not fc or not tc:
        raise ValueError("出发/到达城市无法解析（支持三字码或中文城市名）")
    if fc == tc:
        raise ValueError("出发与到达不能相同")
    try:
        d = _dt.strptime(str(date or ""), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("日期格式应为 YYYY-MM-DD")
    if d < _date.today():
        raise ValueError("日期不能早于今天")
    if d > _date.today().replace(year=_date.today().year + 1):
        raise ValueError("日期不能超过一年")
    return {"from": fc, "from_name": fn, "to": tc, "to_name": tn,
            "date": str(date)}


_PROBE_TASKS = {}
_PROBE_CHALLENGES = {}
_PROBE_CHALLENGE_SESSIONS = {}
_PROBE_TASK_LOCK = threading.RLock()
# 探针真实明细是“当前会话在该入口/航线/日期可用”的即时证据；
# 只记成功明细，空结果/日历价/超时都不得反推登录失效。
_PROBE_AUTH = {}
_PROBE_TASK_KEEP = 4
_PROBE_TASK_TTL = 3600


def _probe_task_cleanup():
    now = time.time()
    with _PROBE_TASK_LOCK:
        for _tid, _t in list(_PROBE_TASKS.items()):
            if (_t.get("status") != "running"
                    and now - float(_t.get("updated") or 0) > _PROBE_TASK_TTL):
                _PROBE_TASKS.pop(_tid, None)
        done = [x for x in _PROBE_TASKS.values() if x.get("status") != "running"]
        done.sort(key=lambda x: x.get("updated") or 0)
        while len(done) > _PROBE_TASK_KEEP:
            _PROBE_TASKS.pop(done.pop(0)["id"], None)
        live = {str(x.get("id")) for x in _PROBE_TASKS.values()}
        for cid, ch in list(_PROBE_CHALLENGES.items()):
            if (ch.get("task_id") not in live
                    and cid not in _PROBE_CHALLENGE_SESSIONS):
                _PROBE_CHALLENGES.pop(cid, None)


def _probe_task_event(task, leg=None, plat=None, phase="", status="",
                      msg="", **kw):
    if not task:
        return
    ev = {"t": time.strftime("%H:%M:%S"), "ts": round(time.time(), 3),
          "leg": leg, "plat": plat, "phase": phase, "status": status,
          "msg": str(msg or "")}
    ev.update({k: v for k, v in kw.items() if v is not None})
    with _PROBE_TASK_LOCK:
        task["events"].append(ev)
        if len(task["events"]) > 400:
            del task["events"][:len(task["events"]) - 400]
        task["updated"] = time.time()


def _probe_task_channel(task, leg, plat, **kw):
    if not task:
        return
    with _PROBE_TASK_LOCK:
        try:
            ch = task["legs"][leg]["channels"][plat]
            ch.update({k: v for k, v in kw.items() if v is not None})
        except (KeyError, IndexError):
            return
        task["updated"] = time.time()


def _record_probe_auth(plat, scope, detail, frm, to, date):
    if not detail:
        return
    now = time.time()
    with _PROBE_TASK_LOCK:
        per = _PROBE_AUTH.setdefault(plat, {})
        cur = per.get(scope) or {}
        if now < float(cur.get("detail_ts") or 0):
            return
        cur.update({
            "detail_ts": now,
            "detail_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "detail_count": int(detail),
            "from": frm, "to": to, "date": date, "source": "probe",
        })
        per[scope] = cur


def _record_probe_auth_reject(plat, scope, reason, frm, to, date, path=""):
    """Explicit login/verification wall from the current probe attempt.

    Empty/calendar/timeout paths never call this; only a real login or
    challenge path does, so a missing detail is never inferred as logout.
    """
    reason = str(reason or "").strip()
    if not reason:
        return
    now = time.time()
    with _PROBE_TASK_LOCK:
        per = _PROBE_AUTH.setdefault(plat, {})
        cur = per.get(scope) or {}
        if now < float(cur.get("auth_ts") or 0):
            return
        cur.update({
            "auth_ts": now,
            "auth_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "auth_reason": reason[:160],
            "auth_path": str(path or ""),
            "auth_from": frm, "auth_to": to, "auth_date": date,
            "source": "probe",
        })
        per[scope] = cur


def _probe_task_add_rows(task, rows):
    if not task or not rows:
        return 0
    added = 0
    with _PROBE_TASK_LOCK:
        seen = task.setdefault("rowkeys", set())
        for r in rows:
            try:
                rr = dict(r)
                rr["isCal"] = bool(rr.get("isCal"))
                rr["isStale"] = False
                rr["stale"] = 0
                rr["rowKey"] = _srx_row_key(rr)
                rr["flightKey"] = _srx_flight_key(rr)
                rr["rawKey"] = _srx_raw_key(rr)
            except Exception:
                rr = dict(r)
                rr["rowKey"] = str(id(r))
            if rr["rowKey"] in seen:
                continue
            seen.add(rr["rowKey"])
            task["rows"].append(rr)
            added += 1
            if len(task["rows"]) >= 4000:
                task["truncated"] = True
                break
        task["updated"] = time.time()
    return added


def _probe_task_view(task_id, rows_from=0):
    with _PROBE_TASK_LOCK:
        t = _PROBE_TASKS.get(str(task_id or ""))
        if not t:
            return None
        rows = t["rows"][max(0, int(rows_from)):]
        legs = []
        for lg in t["legs"]:
            x = {k: lg.get(k) for k in ("leg", "from", "from_name", "to",
                                        "to_name", "date", "status",
                                        "rows", "detail", "cal")}
            x["channels"] = lg["channels"]
            legs.append(x)
        done = sum(1 for lg in t["legs"] for c in lg["channels"].values()
                   if c.get("status") not in ("queued", "running"))
        detail = sum(int(c.get("detail") or 0)
                     for lg in t["legs"] for c in lg["channels"].values())
        cal = sum(int(c.get("cal") or 0)
                  for lg in t["legs"] for c in lg["channels"].values())
        failed = sum(1 for lg in t["legs"] for c in lg["channels"].values()
                     if c.get("status") in ("error", "timeout", "parse_error",
                                            "blocked", "login_required", "challenge",
                                            "session_busy", "partial"))
        raw_n = sum(int(c.get("raw_n") or 0)
                    for lg in t["legs"] for c in lg["channels"].values())
        challenges = [dict(c) for c in _PROBE_CHALLENGES.values()
                      if c.get("task_id") == str(t.get("id"))]
        challenges.sort(key=lambda c: c.get("created") or 0)
        return {"ok": True, "id": t["id"], "status": t["status"],
                "created": t["created"], "started": t["started"],
                "updated": t["updated"], "elapsed_ms": int((
                    (t.get("finished") or time.time())
                    - (t.get("started") or time.time())) * 1000),
                "total": t["total"], "done": done, "detail": detail,
                "cal": cal, "failed": failed, "raw": raw_n,
                "rows_total": len(t["rows"]), "rows_from": max(0, int(rows_from)),
                "rows": rows, "legs": legs, "events": list(t["events"]),
                "truncated": bool(t.get("truncated")),
                "plans": t.get("plans") or [], "want": t.get("want") or [],
                "skipped": t.get("skipped") or [],
                "challenges": challenges,
                "parent": t.get("parent") or "",
                "err": t.get("err") or ""}


def _probe_takeover_url(plat, fc, tc, fn, tn, date):
    """Same channel/route/date URL as the probe, for the visible window."""
    from types import SimpleNamespace
    from core.alerter import Alerter
    route = SimpleNamespace(
        from_code=str(fc or "").upper(), to_code=str(tc or "").upper(),
        from_name=str(fn or fc or ""), to_name=str(tn or tc or ""))
    # r1063 T70：先问"该端登录入口"——`_build_view_url` 给的是**查看详情**深链
    # （途牛那条是 H5），拿它当登录弹窗会弹错端（用户实测：PC 弹成 m.tuniu.com）。
    try:
        from core.channel_links import login_entry_url as _leu
        url = _leu(plat, "pc")
    except Exception:
        url = ""
    if not url:
        try:
            url = Alerter._build_view_url(None, route, str(date or ""), plat)
        except Exception:
            url = ""
    if not url:
        from crawlers import REGISTRY
        try:
            c = REGISTRY[plat](_effective_crawler_config(), _State.logger)
            url = c.login_url()
        except Exception:
            url = ""
    return str(url or "")


def _probe_challenge_ticket(task_id, leg, plat, plan, paths):
    """Create/update a ticket only when an attempt really hit a challenge."""
    bad = next((p for p in (paths or [])
                if p.get("status") == "login"), None)
    if bad is None:
        bad = next((p for p in (paths or [])
                    if p.get("status") == "blocked"), None)
    if bad is None:
        return None
    cid = "%s:%s:%s" % (task_id, leg, plat)
    now = time.time()
    url = _probe_takeover_url(
        plat, plan.get("from"), plan.get("to"),
        plan.get("from_name"), plan.get("to_name"), plan.get("date"))
    kind = "login" if bad.get("status") == "login" else "blocked"
    detail = str(bad.get("detail") or bad.get("status") or "")[:160]
    with _PROBE_TASK_LOCK:
        t = _PROBE_CHALLENGES.get(cid)
        if t is None:
            t = {"id": cid, "task_id": str(task_id), "leg": int(leg),
                 "plat": plat, "from": plan.get("from"),
                 "to": plan.get("to"),
                 "from_name": plan.get("from_name") or plan.get("from"),
                 "to_name": plan.get("to_name") or plan.get("to"),
                 "date": plan.get("date"), "kind": kind,
                 "detail": detail, "path": bad.get("path") or "",
                 "url": url, "status": "open", "rows": 0,
                 "attempts": 1, "created": now, "updated": now}
            _PROBE_CHALLENGES[cid] = t
        elif t.get("status") not in ("passed", "skipped"):
            t.update(kind=kind, detail=detail, path=bad.get("path") or "",
                     url=url or t.get("url") or "", updated=now,
                     attempts=int(t.get("attempts") or 0) + 1)
            if t.get("status") not in ("window_open", "verifying"):
                t["status"] = "open"
        return t


def _probe_open_challenge(cid):
    cid = str(cid or "")
    with _PROBE_TASK_LOCK:
        t = _PROBE_CHALLENGES.get(cid)
        if not t:
            return {"ok": False, "err": "验证票据不存在"}
        if t.get("status") in ("passed", "skipped"):
            return {"ok": False, "err": "该票据已结束"}
        if cid in _PROBE_CHALLENGE_SESSIONS:
            return {"ok": False, "err": "该渠道验证窗口已打开"}
        if len(_PROBE_CHALLENGE_SESSIONS) >= 2:
            return {"ok": False, "err": "同时最多打开两个验证窗口"}
        if not t.get("url"):
            return {"ok": False, "err": "没有可打开的渠道页面，请先登录渠道"}
        evt, done = threading.Event(), threading.Event()
        session = {"evt": evt, "done": done, "error": ""}
        _PROBE_CHALLENGE_SESSIONS[cid] = session
        t["status"] = "window_open"
        t["expires_at"] = time.time() + 300
        t["attempts"] = int(t.get("attempts") or 0) + 1
        t["updated"] = time.time()

    def _run():
        try:
            from crawlers import REGISTRY
            c = REGISTRY[t["plat"]](_effective_crawler_config(), _State.logger)
            c.open_challenge_window(t["url"], evt, timeout_s=300,
                                    idx=len(_PROBE_CHALLENGE_SESSIONS) - 1)
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            with _PROBE_TASK_LOCK:
                session["error"] = msg[:120]
                if t.get("status") in ("window_open", "verifying"):
                    t["status"] = ("expired" if ("超时" in msg or "关闭" in msg)
                                   else "failed")
                    t["detail"] = msg[:160]
                t["expires_at"] = 0
                t["updated"] = time.time()
            _State.logger.warning(
                "[challenge] %s 窗口结束异常: %s", cid, msg)
        finally:
            session["done"].set()
            with _PROBE_TASK_LOCK:
                if _PROBE_CHALLENGE_SESSIONS.get(cid) is session:
                    _PROBE_CHALLENGE_SESSIONS.pop(cid, None)

    threading.Thread(target=_run, daemon=True,
                     name="challenge-window").start()
    return {"ok": True, "ticket": dict(t)}


def _probe_verify_challenge(cid):
    cid = str(cid or "")
    with _PROBE_TASK_LOCK:
        t = _PROBE_CHALLENGES.get(cid)
        if not t:
            return {"ok": False, "err": "验证票据不存在"}
        if t.get("status") in ("passed", "skipped"):
            return {"ok": False, "err": "该票据已结束"}
        session = _PROBE_CHALLENGE_SESSIONS.get(cid)
        if session:
            t["status"] = "verifying"
            t["updated"] = time.time()
    if session:
        session["evt"].set()
        if not session["done"].wait(15):
            with _PROBE_TASK_LOCK:
                t["status"] = "failed"
                t["detail"] = "验证窗口关闭超时，请重新打开"
                t["updated"] = time.time()
            return {"ok": False, "err": "验证窗口仍在关闭，请稍后再试"}

    rows, paths, detail = [], [], ""
    try:
        from crawlers import REGISTRY
        cfg = dict(_effective_crawler_config())
        cfg.update({"max_attempts": 1, "tuniu_max_poll": 3,
                    "backoff_seconds": 1})
        c = REGISTRY[t["plat"]](cfg, _State.logger)
        c.probe_mode = False
        try:
            # Qunar 的 fetch 外壳带 90/180/300s 阶梯退避；核验只做一次
            # 数据路径检查，直接走 _fetch_inner，避免 UI 卡十分钟。
            if t["plat"] == "qunar" and hasattr(c, "_fetch_inner"):
                rows = c._fetch_inner(t["from"], t["to"], [t["date"]]) or []
            else:
                rows = c.fetch(t["from"], t["to"], [t["date"]]) or []
        finally:
            paths = list(getattr(c, "paths", []) or [])
        bad = next((p for p in paths
                    if p.get("status") in ("blocked", "login")), None)
        if bad and not rows:
            passed = False
            detail = str(bad.get("detail") or bad.get("status") or "")[:160]
        elif not paths and not rows:
            passed = False
            detail = "未取得可核验响应"
        else:
            passed = True
            detail = ("验证通过 · %d 行" % len(rows)) if rows else \
                     "验证通过 · 该日期无可售明细"
            if bad:
                detail += "（仍有路径验证/登录，已取得明细）"
    except Exception as e:
        passed = False
        detail = str(e)[:160]

    now = time.time()
    with _PROBE_TASK_LOCK:
        t["status"] = "passed" if passed else "failed"
        t["rows"] = len(rows)
        t["detail"] = detail
        t["expires_at"] = 0
        t["updated"] = now
        if passed:
            _PROBE_CHALLENGE_TS.pop(t["plat"], None)
            globals()["_PROBE_LAST"] = 0.0
        result = dict(t)
    return {"ok": True, "passed": passed, "ticket": result,
            "legs": [{"from": t["from"], "to": t["to"],
                      "date": t["date"]}],
            "plats": [t["plat"]], "rows": len(rows)}


def _probe_skip_challenge(cid):
    cid = str(cid or "")
    with _PROBE_TASK_LOCK:
        t = _PROBE_CHALLENGES.get(cid)
        if not t:
            return {"ok": False, "err": "验证票据不存在"}
        if t.get("status") in ("passed", "skipped"):
            return {"ok": False, "err": "该票据已结束"}
        session = _PROBE_CHALLENGE_SESSIONS.get(cid)
        t["status"] = "skipped"
        t["expires_at"] = 0
        t["updated"] = time.time()
        result = dict(t)
    if session:
        session["evt"].set()
    return {"ok": True, "ticket": result}


def _probe_filter_want(want, now=None):
    """Retry: drop channels still cooling after a challenge/login wall."""
    ts_now = time.time() if now is None else now
    blocked = [p for p in want
               if _PROBE_CHALLENGE_TS.get(p, 0)
               and ts_now - _PROBE_CHALLENGE_TS[p] < _PROBE_CHALLENGE_COOLDOWN]
    allowed = [p for p in want if p not in blocked]
    return allowed, blocked


def _probe_exc_status(exc: Exception) -> str:
    """探针异常 → 渠道状态；会话占用/解析异常不得混成普通 error。"""
    from crawlers.base import SessionBusyError
    if isinstance(exc, SessionBusyError):
        return "session_busy"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "parse_error"
    return "error"


def _probe_result_status(rows, paths, cal=0):
    """把入口证据映射成渠道终态：验证码/登录墙/超时/失败不得写成空结果。"""
    if rows:
        bad = any((p.get("status") in ("login", "blocked", "error", "timeout"))
                  for p in (paths or []))
        if bad:
            return "partial"
        if cal and cal >= len(rows):
            return "calendar_only"
        return "ok"
    states = {p.get("status") for p in (paths or [])}
    if "blocked" in states:
        return "challenge"
    if "login" in states:
        return "login_required"
    if "timeout" in states:
        return "timeout"
    if "parse_error" in states:
        return "parse_error"
    if "session_busy" in states:
        return "session_busy"
    if "unsupported" in states:
        return "unsupported"
    if "error" in states:
        return "error"
    return "empty"


def _probe_start_task(task_id, frm, to, date, legs, plats, retry=False,
                      leg_wants=None):
    """后台线程：真实采集，事件/行增量写入 task；异常落 task。"""
    task = _PROBE_TASKS.get(task_id)
    if not task:
        return
    try:
        _probe_search(frm, to, date, plats, legs, task=task,
                      cancel=task["cancel"], retry=retry,
                      leg_wants=leg_wants)
    except Exception as e:
        cancelled = task["cancel"].is_set()
        with _PROBE_TASK_LOCK:
            task["status"] = "cancelled" if cancelled else "error"
            if not cancelled:
                task["err"] = str(e)[:200]
        _probe_task_event(task, phase="任务取消" if cancelled else "任务异常",
                          status="cancelled" if cancelled else "error",
                          msg="已取消" if cancelled else str(e)[:200])
    finally:
        with _PROBE_TASK_LOCK:
            if task["status"] in ("running", "stopping"):
                task["status"] = ("cancelled" if task["cancel"].is_set()
                                  else "done")
            task["finished"] = time.time()
            task["updated"] = time.time()
        _probe_task_event(
            task, phase="任务结束",
            status="cancelled" if task["status"] == "cancelled" else "done",
            msg="已取消" if task["status"] == "cancelled" else "全部子任务已结束")


def _probe_search(frm, to, date, plats, legs=None, task=None, cancel=None,
                  retry=False, leg_wants=None):
    """主动探针：任意 OD/日期并发真实渠道采集（不落库、不触发推送）。

    legs=[{from,to,date},…] 时一次采集最多 _PROBE_BATCH_MAX 条航线/日期；
    腿间最多两路并行、腿内渠道并发；单腿保持旧返回结构。
    """
    import concurrent.futures as _cf
    import time as _time
    from datetime import datetime as _dt
    from core.flightnorm import (normalize as _norm, cabin_clean as _cc,
                                 cabin_class as _ccl)
    from core.intl import is_intl_route as _is_intl
    from core.alerter import Alerter as _A
    from crawlers import REGISTRY as _REG

    if legs is not None and not isinstance(legs, list):
        raise ValueError("legs 必须为数组")
    raw_legs = legs if isinstance(legs, list) and legs else None
    plans = []
    if raw_legs is not None:
        if len(raw_legs) > _PROBE_BATCH_MAX:
            raise ValueError("组合探针最多 %d 条航线/日期" % _PROBE_BATCH_MAX)
        _seen = set()
        for _i, _leg in enumerate(raw_legs, 1):
            if not isinstance(_leg, dict):
                raise ValueError("第 %d 条缺少 from/to/date" % _i)
            try:
                _p = _probe_leg_plan(_leg.get("from"), _leg.get("to"),
                                     _leg.get("date"))
            except ValueError as _e:
                raise ValueError("第 %d 条：%s" % (_i, _e))
            _key = (_p["from"], _p["to"], _p["date"])
            if _key in _seen:
                raise ValueError("第 %d 条与前面重复：%s→%s %s"
                                 % (_i, _p["from_name"], _p["to_name"],
                                    _p["date"]))
            _seen.add(_key)
            plans.append(_p)
    else:
        plans = [_probe_leg_plan(frm, to, date)]
    want = [p for p in (plats or list(_REG.keys())) if p in _REG]
    want.sort(key=_plat_rank)
    if not want:
        raise ValueError("至少选择一个渠道")
    if retry:
        _allowed, _blocked = _probe_filter_want(want)
        if _blocked and not _allowed:
            raise RuntimeError(
                "渠道验证冷却中，请稍后再试：%s" % "、".join(_blocked))
        want = _allowed
    _now0 = _time.time()
    # 重试是用户对已结束任务的显式恢复：跳过滤全局冷却，但渠道验证
    # 冷却仍由 _probe_filter_want 闸住
    if not retry and _now0 - _PROBE_LAST < _PROBE_COOLDOWN:
        raise RuntimeError("探针冷却中，请 %.0fs 后再试" % (_PROBE_COOLDOWN - (_now0 - _PROBE_LAST)))
    if not _PROBE_LOCK.acquire(False):
        raise RuntimeError("已有探针在采集，请稍后再试")
    globals()["_PROBE_LAST"] = _now0
    cfg = (_State.cfg or {})
    crawler_cfg = dict(cfg.get("crawler") or {})
    # 探针与定时采集必须拿到同一份 android 段（r630）：这里自建爬虫实例，
    # 少了这一段时 App 渠道会一律报 runtime not ready: disabled——
    # 「渠道自检」按钮点了永远失败，而定时采集其实正常。
    crawler_cfg["android"] = cfg.get("android") or {}
    t0 = _time.time()
    batch = raw_legs is not None

    def run_leg(ix, plan):
        fc, fn = plan["from"], plan["from_name"]
        tc, tn = plan["to"], plan["to_name"]
        dat = plan["date"]
        leg_want = (leg_wants or {}).get(ix) or want
        leg_want = [q for q in leg_want if q in _REG]
        leg_want.sort(key=_plat_rank)
        if not leg_want:
            raise RuntimeError("第 %d 条没有可执行渠道" % (ix + 1))
        scope = "international" if _is_intl(fc, tc) else "domestic"
        route = {"from": fc, "from_name": fn, "to": tc, "to_name": tn,
                 "dates": [dat]}
        out, channels = [], {}
        leg_cap = 900 if batch else 1200
        lt = _time.time()
        if task:
            task["legs"][ix]["status"] = "running"
            _probe_task_event(task, leg=ix, phase="组合开始", status="running",
                              msg=fn + "→" + tn + " " + dat)
            for p in leg_want:
                _probe_task_channel(task, ix, p, phase="排队",
                                    status="queued")
                _probe_task_event(task, leg=ix, plat=p, phase="排队",
                                  status="queued", msg="等待可用槽位")

        def one(p):
            t = _time.time()
            if cancel is not None and cancel.is_set():
                _probe_task_channel(task, ix, p, phase="已取消",
                                    status="cancelled")
                _probe_task_event(task, leg=ix, plat=p, phase="已取消",
                                  status="cancelled", msg="请求前已取消")
                return {"n": 0, "rows": [], "ms": 0,
                        "status": "cancelled", "detail": 0, "cal": 0}
            _probe_task_channel(task, ix, p, phase="请求中", status="running")
            _probe_task_event(task, leg=ix, plat=p, phase="请求渠道",
                              status="running", msg="已启动真实请求")
            c = None
            try:
                c = _REG[p](crawler_cfg, _State.logger)
                c.probe_mode = True

                def _on_path(rec, _p=p, _ix=ix, _c=c):
                    if not task:
                        return
                    _probe_task_channel(
                        task, _ix, _p,
                        paths=list(getattr(_c, "paths", []) or []),
                        lastPath=getattr(_c, "last_path", ""),
                        lastStatus=getattr(_c, "last_status", ""))
                    _probe_task_event(
                        task, leg=_ix, plat=_p,
                        phase="链路 " + str(rec.get("path") or ""),
                        status=str(rec.get("status") or ""),
                        msg="%s · %s · %d 行%s" % (
                            rec.get("path"), rec.get("status"),
                            int(rec.get("rows") or 0),
                            (" · " + rec["detail"]) if rec.get("detail") else ""),
                        path=rec.get("path"), pathRows=rec.get("rows"))

                c.on_path = _on_path
                with _probe_plat_lock(p):
                    if cancel is not None and cancel.is_set():
                        _probe_task_channel(task, ix, p, phase="已取消",
                                            status="cancelled")
                        _probe_task_event(task, leg=ix, plat=p, phase="已取消",
                                          status="cancelled",
                                          msg="排队等待时任务已取消")
                        return {"n": 0, "rows": [], "ms": int((_time.time() - t) * 1000),
                                "status": "cancelled", "detail": 0, "cal": 0}
                    with _PROBE_CHANNEL_GATE:
                        if cancel is not None and cancel.is_set():
                            _probe_task_channel(task, ix, p, phase="已取消",
                                                status="cancelled")
                            _probe_task_event(task, leg=ix, plat=p, phase="已取消",
                                              status="cancelled",
                                              msg="等待全局浏览器配额时任务已取消")
                            return {"n": 0, "rows": [], "ms": int((_time.time() - t) * 1000),
                                    "status": "cancelled", "detail": 0, "cal": 0}
                        _probe_task_channel(task, ix, p, phase="等待响应",
                                            status="running")
                        _probe_task_event(
                            task, leg=ix, plat=p, phase="等待响应",
                            status="running",
                            msg="请求已发出，等待 %s 上游返回" % p)
                        fps = c.fetch(fc, tc, [dat]) or []
                        _ok_paths = [x for x in (getattr(c, "paths", []) or [])
                                     if x.get("status") == "ok"
                                     and int(x.get("rows") or 0) > 0]
                        if not _ok_paths:
                            _ok_paths = [x for x in (getattr(c, "paths", []) or [])
                                         if x.get("status") == "calendar"]
                        _entry_path = (_ok_paths[-1].get("path") or ""
                                       if _ok_paths else "")
                        _entry_status = (_ok_paths[-1].get("status") or "unknown"
                                         if _ok_paths else "unknown")
                        _probe_task_event(
                            task, leg=ix, plat=p, phase="接收数据",
                            status="running",
                            msg="收到 %d 条渠道记录" % len(fps),
                            n_raw=len(fps))
                _probe_task_channel(task, ix, p, phase="解析中",
                                    status="running")
                _probe_task_event(task, leg=ix, plat=p, phase="解析明细",
                                  status="running",
                                  msg="已取得 %d 条渠道记录" % len(fps),
                                  n_raw=len(fps))
                rows = []
                for fp in fps:
                    try:
                        obj = json.loads(fp.extra or "[]")
                    except Exception:
                        obj = []
                    items = obj if isinstance(obj, list) else ([obj] if isinstance(obj, dict) else [])
                    synthetic = not bool(items)
                    if synthetic:
                        items = [{"price": fp.price, "name": fp.airline,
                                  "code": fp.flight_no, "depTime": fp.depart_time,
                                  "arrTime": fp.arrive_time, "depDate": dat}]
                    for raw_ix, it in enumerate(items):
                        if not isinstance(it, dict):
                            continue
                        raw_item = json.loads(json.dumps(it, ensure_ascii=False))
                        g = dict(it)
                        g["_platform"] = p
                        g["_pair"] = (fc, tc)
                        try:
                            _norm(g, dat)
                        except Exception:
                            pass
                        pr = g.get("price", fp.price)
                        try:
                            pr = round(float(pr))
                        except (TypeError, ValueError):
                            continue
                        if pr <= 0:
                            continue
                        dep = str(g.get("depTime") or fp.depart_time or "")
                        arr = str(g.get("arrTime") or fp.arrive_time or "")
                        code = str(g.get("code") or fp.flight_no or "")
                        name = str(g.get("name") or g.get("airline") or fp.airline or "")
                        dur = str(g.get("totalDuration") or g.get("duration") or "")
                        trans = str(g.get("transCity") or "")
                        _cab = _ccl(_cc({"cabin": g.get("cabin")
                                         or g.get("cabinName") or "",
                                         "price": pr,
                                         "bizPrice": g.get("bizPrice")}))
                        rows.append({
                            "price": pr, "code": code, "name": name,
                            "depTime": dep, "arrTime": arr, "dur": dur,
                            "date": dat, "transfer": bool(trans), "trans": trans,
                            "cross": str(g.get("crossDayDesc") or ""),
                            "isCal": not (dep and arr),   # r386：只认时刻（无航班号中转行是真班次）
                            "probeIdx": raw_ix, "synthetic": synthetic,
                            "intl": 1 if _is_intl(fc, tc) else 0,
                            "plat": _A.plat_cn(p), "platKey": p,
                            "from": fc, "to": tc,
                            "fetchedAt": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "stale": 0, "qual": False, "near": False, "brk": False,
                            "xphan": False, "rowId": None, "rawIdx": None,
                            "th": 0, "probe": 1,
                            # 渠道 extra 为空时不得把解析值伪装成 raw
                            "raw": None if synthetic else raw_item,
                            "view": _view_url(route, dat, p),
                            "depAirport": str(g.get("depAirport") or ""),
                            "arrAirport": str(g.get("arrAirport") or ""),
                            "depTerminal": str(g.get("depTerminal") or ""),
                            "arrTerminal": str(g.get("arrTerminal") or ""),
                            "cabinT": str(g.get("cabin") or g.get("cabinName") or ""),
                            "cabin": _cab,
                            "plane": str(g.get("plane") or g.get("craftTypeDetail") or ""),
                            "baggage": str(g.get("baggage") or ""),
                            "meal": str(g.get("meal") or ""),
                            "prate": str(g.get("prate") or ""),
                            "leftTickets": g.get("leftTickets") or g.get("seat"),
                            "tax": g.get("tax") if g.get("tax") is not None else None,
                            "labels": str(g.get("labels") or ""),
                            "entryPath": _entry_path,
                            "prov": {"entryPath": _entry_path,
                                     "pathStatus": _entry_status,
                                     "evidenceLevel": "path"
                                     if _entry_path else "unknown",
                                     "kind": ("calendar" if _entry_status == "calendar"
                                              else "detail")},
                            "leg": ix, "route": fn + "→" + tn,
                            "routeLabel": fn + "→" + tn,
                        })
                        if len(rows) >= leg_cap:
                            break
                    if len(rows) >= leg_cap:
                        break
                _probe_task_event(
                    task, leg=ix, plat=p, phase="标准化去重",
                    status="running",
                    msg="标准化 %d 行为统一字段（渠道原始行 %d 条）"
                        % (len(rows), len(fps)))
                det = sum(1 for x in rows if not x.get("isCal"))
                cal = len(rows) - det
                if det > 0:
                    _record_probe_auth(p, scope, det, fc, tc, dat)
                items_n = 0
                for _fp in fps:
                    try:
                        _obj = json.loads(_fp.extra or "[]")
                        items_n += len(_obj) if isinstance(_obj, list) else 1
                    except Exception:
                        items_n += 1
                paths = list(getattr(c, "paths", []) or [])
                if any(pp.get("status") in ("blocked", "login")
                       for pp in paths):
                    _PROBE_CHALLENGE_TS[p] = _time.time()
                if task:
                    _probe_challenge_ticket(task["id"], ix, p, plan, paths)
                result_status = _probe_result_status(rows, paths, cal=cal)
                if result_status in ("login_required", "challenge"):
                    bad_auth = next(
                        (pp for pp in paths if pp.get("status") == "login"),
                        None)
                    if bad_auth is None:
                        bad_auth = next(
                            (pp for pp in paths
                             if pp.get("status") == "blocked"), None)
                    if bad_auth is not None:
                        _record_probe_auth_reject(
                            p, scope,
                            bad_auth.get("detail") or bad_auth.get("status") or "",
                            fc, tc, dat, bad_auth.get("path") or "")
                if result_status in ("ok", "calendar_only"):
                    _PROBE_CHALLENGE_TS.pop(p, None)
                _probe_task_event(
                    task, leg=ix, plat=p, phase="解析完成", status=result_status,
                    msg="渠道记录 %d · 有效 %d（明细 %d / 日历 %d）"
                        % (len(fps), len(rows), det, cal),
                    n=len(rows), detail=det, cal=cal,
                    raw_n=len(fps), items_n=items_n)
                return {"n": len(rows), "rows": rows,
                        "ms": int((_time.time() - t) * 1000),
                        "status": result_status,
                        "detail": det, "cal": cal,
                        "raw_n": len(fps), "items_n": items_n,
                        "paths": paths,
                        "truncated": len(rows) >= leg_cap}
            except Exception as e:
                _status = _probe_exc_status(e)
                _probe_task_event(task, leg=ix, plat=p, phase="失败",
                                  status=_status, msg=str(e)[:160])
                return {"n": 0, "rows": [], "ms": int((_time.time() - t) * 1000),
                        "status": _status, "err": str(e)[:160],
                        "detail": 0, "cal": 0,
                        "paths": list(getattr(c, "paths", []) or [])}

        try:
            # 渠道浏览器并发上限 2：五路同时冷启会触发同程/途牛/飞猪
            # 验证码（用户实测：新开浏览器即弹验证）。按优先级两两推进
            # 既保留并行加速，又降低同 IP 多浏览器指纹叠加的风控面
            ex = _cf.ThreadPoolExecutor(max_workers=min(2, max(1, len(want))))
            futs = {ex.submit(one, p): p for p in leg_want}
            try:
                for fut in _cf.as_completed(futs, timeout=150):
                    p = futs[fut]
                    try:
                        r = fut.result()
                    except Exception as e:
                        r = {"n": 0, "rows": [], "status": "error", "err": str(e)[:160]}
                    channels[p] = {k: r[k] for k in (
                        "n", "status", "ms", "err", "detail", "cal",
                        "raw_n", "items_n", "paths") if k in r}
                    out.extend(r.get("rows") or [])
                    if task:
                        _cancelled = cancel is not None and cancel.is_set()
                        _probe_task_channel(
                            task, ix, p,
                            phase="已取消" if _cancelled else "完成",
                            status="cancelled" if _cancelled else r.get("status"),
                            n=r.get("n"), detail=r.get("detail", 0),
                            cal=r.get("cal", 0), ms=r.get("ms"),
                            raw_n=r.get("raw_n"), items_n=r.get("items_n"),
                            paths=r.get("paths"),
                            lastPath=(r.get("paths") or [{}])[-1].get("path")
                            if r.get("paths") else None,
                            lastStatus=(r.get("paths") or [{}])[-1].get("status")
                            if r.get("paths") else None,
                            err=r.get("err", ""))
                        # 已返回的明细即使在取消后也必须保留，不能丢已完成结果。
                        _probe_task_add_rows(task, r.get("rows") or [])
                        _probe_task_event(
                            task, leg=ix, plat=p, phase="渠道结束",
                            status="cancelled" if _cancelled else r.get("status"), n=r.get("n"),
                            detail=r.get("detail", 0), cal=r.get("cal", 0),
                            ms=r.get("ms"), msg=r.get("err", ""))
            except _cf.TimeoutError:
                for fut, p in futs.items():
                    if p not in channels:
                        channels[p] = {"n": 0, "status": "timeout",
                                       "ms": 150000, "detail": 0, "cal": 0}
                        if task:
                            _probe_task_channel(task, ix, p, phase="超时",
                                                status="timeout", ms=150000)
                            _probe_task_event(task, leg=ix, plat=p,
                                              phase="超时", status="timeout",
                                              msg="超过 150 秒未返回")
            finally:
                ex.shutdown(wait=False)
        except Exception as e:
            return {"leg": ix, "from": fc, "from_name": fn, "to": tc,
                    "to_name": tn, "date": dat, "rows": [],
                    "channels": channels,
                    "elapsed_ms": int((_time.time() - lt) * 1000),
                    "truncated": False, "status": "error", "err": str(e)[:160]}
        channels = {p: channels[p] for p in sorted(channels, key=_plat_rank)}
        out.sort(key=lambda x: (x["price"], x["depTime"] or "99:99"))
        truncated = len(out) >= leg_cap and any(
            c.get("status") == "ok" for c in channels.values())
        all_empty = all(c.get("status") in ("empty", "ok")
                        for c in channels.values())
        leg_status = ("cancelled" if (cancel is not None and cancel.is_set())
                      else ("ok" if out else ("empty" if all_empty else "error")))
        if task:
            det = sum(1 for x in out if not x.get("isCal"))
            task["legs"][ix].update({
                "status": leg_status, "rows": len(out), "detail": det,
                "cal": len(out) - det,
                "elapsed_ms": int((_time.time() - lt) * 1000)})
            _probe_task_event(task, leg=ix, phase="组合结束",
                              status=leg_status,
                              msg="%s→%s %s · %d 行" % (fn, tn, dat, len(out)),
                              n=len(out), detail=det, cal=len(out) - det)
        return {"leg": ix, "from": fc, "from_name": fn, "to": tc,
                "to_name": tn, "date": dat, "rows": out,
                "channels": channels,
                "elapsed_ms": int((_time.time() - lt) * 1000),
                "truncated": truncated, "status": leg_status}

    legs_out = []
    try:
        if cancel is not None and cancel.is_set():
            for i, p in enumerate(plans):
                if task:
                    task["legs"][i]["status"] = "cancelled"
                    for q in want:
                        _probe_task_channel(task, i, q, phase="已取消",
                                            status="cancelled")
            raise RuntimeError("任务已取消")
        if not batch:
            legs_out = [run_leg(0, plans[0])]
        else:
            ex = _cf.ThreadPoolExecutor(max_workers=min(2, len(plans)))
            futs = {ex.submit(run_leg, i, p): i for i, p in enumerate(plans)}
            try:
                for fut in _cf.as_completed(futs, timeout=360):
                    try:
                        legs_out.append(fut.result())
                    except Exception as e:
                        _i = futs[fut]
                        _p = plans[_i]
                        legs_out.append({"leg": _i, "from": _p["from"],
                                         "from_name": _p["from_name"],
                                         "to": _p["to"], "to_name": _p["to_name"],
                                         "date": _p["date"], "rows": [],
                                         "channels": {}, "elapsed_ms": 0,
                                         "truncated": False, "status": "error",
                                         "err": str(e)[:160]})
            except _cf.TimeoutError:
                for fut, _i in futs.items():
                    if not any(x.get("leg") == _i for x in legs_out):
                        _p = plans[_i]
                        legs_out.append({"leg": _i, "from": _p["from"],
                                         "from_name": _p["from_name"],
                                         "to": _p["to"], "to_name": _p["to_name"],
                                         "date": _p["date"], "rows": [],
                                         "channels": {}, "elapsed_ms": 0,
                                         "truncated": False, "status": "timeout"})
            finally:
                ex.shutdown(wait=False)
    finally:
        _PROBE_LOCK.release()
        globals()["_PROBE_LAST"] = _time.time()

    legs_out.sort(key=lambda x: x.get("leg", 0))
    out = [r for lg in legs_out for r in lg.get("rows") or []]
    truncated = any(lg.get("truncated") for lg in legs_out)
    if len(out) > 4000:
        out = out[:4000]
        truncated = True
    out.sort(key=lambda x: (x.get("leg", 0), x["price"],
                            x.get("depTime") or "99:99"))
    merged = {}
    for lg in legs_out:
        for p, c in (lg.get("channels") or {}).items():
            m = merged.setdefault(p, {"n": 0, "status": "ok", "ms": 0,
                                      "_err": False, "paths": []})
            m["n"] += int(c.get("n") or 0)
            m["ms"] = max(m["ms"], int(c.get("ms") or 0))
            m["paths"].extend(dict(x, leg=lg.get("leg"))
                              for x in (c.get("paths") or []))
            st = c.get("status")
            if st in ("error", "timeout"):
                m["_err"] = True
    for m in merged.values():
        # 组合内某腿有行即该渠道有量；逐腿未供/失败由 legs[].channels 如实展示
        m["status"] = "ok" if m["n"] > 0 else ("error" if m["_err"] else "empty")
        m.pop("_err", None)
    merged = {p: merged[p] for p in sorted(merged, key=_plat_rank)}
    for r in out:
        r["isCal"] = not (r.get("depTime") and r.get("arrTime"))
        r["isStale"] = False
        r["stale"] = 0
        r["rowKey"] = _srx_row_key(r)
        r["flightKey"] = _srx_flight_key(r)
        r["rawKey"] = _srx_raw_key(r)
    first = plans[0]
    resp = {"ok": True, "rows": out, "channels": merged,
            "elapsed_ms": int((_time.time() - t0) * 1000), "saved": False,
            "truncated": truncated,
            "probe_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "from": first["from"], "from_name": first["from_name"],
            "to": first["to"], "to_name": first["to_name"],
            "date": first["date"]}
    if batch:
        resp["batch"] = True
        resp["legs"] = [{k: lg.get(k) for k in (
            "leg", "from", "from_name", "to", "to_name", "date", "channels",
            "elapsed_ms", "truncated", "status", "err")} for lg in legs_out]
        for lg in resp["legs"]:
            lg["rows"] = len(legs_out[lg["leg"]].get("rows") or [])
    return resp

def _probe_raw(row_id, idx):
    """检索页原始行回放（单源）：row_id + extra[idx] → 原始对象与行元数据。
    只读；不重新解析、不改写；异常由调用端转 JSON 错误。"""
    rid = int(row_id or 0)
    i = int(idx or 0)
    if rid <= 0 or i < 0 or i > 3000:
        raise ValueError("bad row/idx")
    db = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT rowid AS id, platform, from_city, to_city, depart_date, "
            "price, extra, prov, fetched_at FROM flight_prices WHERE rowid=?",
            (rid,)).fetchone()
    finally:
        conn.close()
    if not r:
        return {"ok": False, "err": "row not found", "raw": None}
    try:
        obj = json.loads(r["extra"] or "[]")
    except Exception:
        obj = []
    item = (obj[i] if isinstance(obj, list) and 0 <= i < len(obj) else None)
    try:
        prov = json.loads(r["prov"] or "{}")
    except (TypeError, ValueError):
        prov = {}
    return {
        "ok": isinstance(item, dict),
        "row": {k: r[k] for k in (
            "id", "platform", "from_city", "to_city",
            "depart_date", "price", "fetched_at")},
        "raw": item if isinstance(item, dict) else None,
        "prov": prov if isinstance(prov, dict) else {},
        # DB 只存解析后的 extra；不能在 UI 标成 HTTP 原始响应。
        "evidence_level": "parsed_extra",
        "idx": i,
        "count": len(obj) if isinstance(obj, list) else 0,
    }


def _srx_row_key(o):
    """检索台稳定行身份（跨轮不随 rowId 漂移）：价格/rowId 不参与。
    - 真实航班：f|route|plat|flightKey|cabin（flightKey 已含完整号/时刻/中转/跨天/经停）
    - 主动探针：p|route|plat|flightKey|cabin|probeIdx（探针不入库）
    - 补位：s|route|plat|flightKey|cabin
    - 日历/薄行：c|route|plat|date|rawIdx（无完整号/时刻，不冒充同班）
    rowId/rawIdx 只用于 raw 回放（rawKey），不再作为选中/复核身份。"""
    frm = str(o.get("from") or "")
    to = str(o.get("to") or "")
    plat = str(o.get("platKey") or "")
    date = str(o.get("date") or "")
    fk = _srx_flight_key(o)
    cabin = str(o.get("cabinT") or o.get("cabinCode") or "")
    if fk:
        base = "|".join((frm, to, plat, fk, cabin))
        if o.get("probe"):
            return "p|" + base + "|" + str(o.get("probeIdx") if o.get("probeIdx") is not None else "")
        if o.get("isStale"):
            return "s|" + base
        return "f|" + base
    if o.get("isCal"):
        return "c|%s|%s|%s|%s|%s|%s|%s" % (frm, to, plat, date,
                                        o.get("rawIdx") if o.get("rawIdx") is not None else "",
                                        "s" if o.get("isStale") else "",
                                        o.get("price") if o.get("price") is not None else "")
    return "x|%s|%s|%s|%s" % (frm, to, plat, date)


def _srx_raw_key(o):
    """raw 回放键：只含 rowId/rawIdx 或探针原始下标；与选中身份分离。"""
    if o.get("rowId") is not None:
        return "r%d:%s" % (int(o["rowId"]), o.get("rawIdx"))
    if o.get("probe"):
        return "p|%s|%s|%s|%s" % (o.get("from") or "", o.get("to") or "",
                                  o.get("platKey") or "",
                                  o.get("probeIdx") if o.get("probeIdx") is not None else "")
    return ""


def _srx_flight_key(o):
    """同班键：只有完整航班号 + 起降时刻才成组；日历/薄行返回空。
    复合航班号（A/B）按航段排序归一；航线/日期/时刻/中转/跨天/经停
    全部纳入，避免跨航线、直飞与中转误并。"""
    code = str(o.get("code") or "").upper().replace(" ", "")
    dep = str(o.get("depTime") or "").strip()
    arr = str(o.get("arrTime") or "").strip()
    if not code or not dep or not arr:
        return ""
    segs = [x for x in code.replace("，", "/").replace(",", "/").split("/") if x]
    code_n = "/".join(sorted(segs))
    return "|".join((str(o.get("from") or ""), str(o.get("to") or ""),
                     code_n, str(o.get("date") or ""), dep, arr,
                     str(o.get("trans") or ""), str(o.get("cross") or ""),
                     "1" if o.get("stop") else "0"))


def _srx_health(frm, to, date, db=None):
    """字段健康：按当前航线/日期读取各渠道最近成功的 raw extra，
    统计 raw 键可得率（不是值正确率）。没数据的渠道如实返回 0/0。"""
    from core.alerter import Alerter as _A
    fc, _fn = _probe_city_code(frm)
    tc, _tn = _probe_city_code(to)
    if not fc or not tc or not str(date or "").strip():
        raise ValueError("from/to/date required")
    db = db or _anchored((_State.cfg.get("output") or {}).get(
        "db_path"), "data/prices.db")
    specs = [
        ("price", ("price", "avgTotalPrice", "minPrice", "adultPrice")),
        ("tax", ("tax", "avgTax", "taxPrice")),
        ("depTime", ("depTime", "dTime", "departTime")),
        ("arrTime", ("arrTime", "aTime", "arriveTime")),
        ("duration", ("totalDuration", "duration", "flyTime")),
        ("cabin", ("cabin", "cabinName", "cabinT", "cabinCode")),
        ("plane", ("plane", "planeSize", "craftType", "aircraft")),
        ("baggage", ("baggage", "carryon", "bag")),
        ("meal", ("meal", "hasMeal")),
        ("leftTickets", ("leftTickets", "seat", "seatCount")),
    ]
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    byp, captured = {}, {}
    # 覆盖面：默认五家 + 用户启用的 App + **该航线/日期在库里真出现过的
    # 渠道**。只遍历 `PLATFORM_CN` 时 App 渠道的字段覆盖率从不被审计——
    # 界面上看起来「没有这件事」，而不是「覆盖率为 0」。
    # 「库里出现过」必须自己算：只靠 `_State.users` 的话，历史上采过、
    # 后来被停用的渠道会从审计里消失，等于把已存在的问题藏起来。
    _present = sorted({
        str(r[0]) for r in conn.execute(
            "SELECT DISTINCT platform FROM flight_prices "
            "WHERE from_city=? AND to_city=? AND depart_date=?",
            (fc, tc, str(date))).fetchall() if r and r[0]})
    _plats = _diag_platforms(_present)
    _names = dict(_A.PLATFORM_CN, **_A.PLATFORM_CN_EXTRA)
    try:
        # 每平台最近 3 条成功 raw；SQL 侧 LIMIT，避免把全历史 extra
        # （热门航线可达数百 MB）读入内存后再丢弃。
        for _p in _plats:
            rows = conn.execute(
                "SELECT extra, fetched_at FROM flight_prices "
                "WHERE platform=? AND from_city=? AND to_city=? "
                "AND depart_date=? AND extra!='' "
                "ORDER BY fetched_at DESC LIMIT 3",
                (_p, fc, tc, str(date))).fetchall()
            for r in rows:
                try:
                    obj = json.loads(r["extra"] or "[]")
                except Exception:
                    continue
                items = obj if isinstance(obj, list) else ([obj] if isinstance(obj, dict) else [])
                items = [x for x in items if isinstance(x, dict)]
                if not items:
                    continue
                byp.setdefault(_p, []).extend(items)
                if _p not in captured:
                    captured[_p] = r["fetched_at"]
    finally:
        conn.close()
    out = []
    for p in _plats:
        cn = _names.get(p, p)
        items = byp.get(p, [])
        total = len(items)
        fields = {}
        for key, keys in specs:
            n = 0
            for it in items:
                v = None
                for k in keys:
                    if k in it and it[k] not in (None, "", []):
                        v = it[k]
                        break
                if v is not None:
                    n += 1
            fields[key] = {"n": n, "total": total,
                           "rate": (round(n / total * 100) if total else None)}
        out.append({"key": p, "name": cn, "rows": len(items),
                    "capturedAt": captured.get(p, ""), "fields": fields})
    return {"ok": True, "from": fc, "to": tc, "date": str(date),
            "source": "flight_prices.extra", "measure": "raw_key_rate",
            "channels": out}


def _srx_links(frm, to, date):
    """各渠道真实落地页链接：与爬虫取数路径同源；本态不供返回空串。"""
    from core.alerter import Alerter as _A
    fc, fn = _probe_city_code(frm)
    tc, tn = _probe_city_code(to)
    if not fc or not tc:
        raise ValueError("from/to required")
    rr = {"from": fc, "from_name": fn, "to": tc, "to_name": tn}
    import re as _re
    if date and not _re.match(r"^\d{4}-\d{2}-\d{2}$", str(date)):
        raise ValueError("date must be YYYY-MM-DD")
    # App 渠道没有网页落地页（真机内采集）：也占一行并带 app 标记，
    # 前端才能说「App 无网页落地页」而不是笼统的「本态不供落地页」。
    _apps = [{"key": p, "name": cn, "url": "", "ok": False, "app": True,
              "note": "App 渠道走 Android 真机采集，没有网页落地页"}
             for p, cn in _A.PLATFORM_CN_EXTRA.items()
             if p in _APP_CHANNELS]
    if not date:
        return {"ok": True, "from": fc, "to": tc, "date": "",
                "links": [{"key": p, "name": cn, "url": "", "ok": False}
                          for p, cn in _A.PLATFORM_CN.items()] + _apps}
    links = []
    for p, cn in _A.PLATFORM_CN.items():
        url = _view_url(rr, str(date or ""), p)
        links.append({"key": p, "name": cn, "url": url, "ok": bool(url)})
    return {"ok": True, "from": fc, "to": tc, "date": str(date or ""),
            "links": links + _apps}


def _srx_calendar_raw(frm, to, date, days=14, axis="both"):
    """双轴日历（诚实拆分）：
    - departure：按出发日的 DB 行最低价（真实有则给点，没采就不生成）
    - observation：近 N 个采集日的最低观测价（原 _daily_minima 轴）
    前端明确标注两条轴，禁止把采集日当出发日、也不按日因子重算价格。
    """
    from datetime import datetime as _dt, date as _date, timedelta as _td
    fc, _fn = _probe_city_code(frm)
    tc, _tn = _probe_city_code(to)
    try:
        base = _dt.strptime(str(date or ""), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("date must be YYYY-MM-DD")
    days = max(1, min(int(days or 14), 31))
    db = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")
    dep = []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        # 出发日轴：当前窗口（锚点起 N 天）真实落库的出发日最低价。
        # 价格与 capturedAt 必须来自同一行：旧实现 MIN(price)+MAX(fetched_at)
        # 会把旧日历价配上新采集时间，构成虚假的时间-价格配对。
        end = base + _td(days=days - 1)
        # 每天只取最低价那一行（窗口函数），不再把 400+ 行 / 10MB
        # extra 全量拉回逐行 JSON 解析；n 仍保留当天总行数。
        rows = conn.execute(
            "SELECT depart_date, platform, price, fetched_at, extra, n FROM ("
            " SELECT depart_date, platform, price, fetched_at, extra,"
            " ROW_NUMBER() OVER (PARTITION BY depart_date"
            "   ORDER BY price ASC, fetched_at DESC) rn,"
            " COUNT(*) OVER (PARTITION BY depart_date) n"
            " FROM flight_prices"
            " WHERE from_city=? AND to_city=? AND depart_date BETWEEN ? AND ?"
            " AND extra!=''"
            ") WHERE rn=1 ORDER BY depart_date",
            (fc, tc, base.isoformat(), end.isoformat())).fetchall()
        for r in rows:
            d0 = r["depart_date"]
            is_cal = True
            try:
                obj = json.loads(r["extra"] or "[]")
                items = obj if isinstance(obj, list) else ([obj] if isinstance(obj, dict) else [])
                is_cal = not any(
                    isinstance(x, dict)
                    and str(x.get("depTime") or "").strip()
                    and str(x.get("arrTime") or "").strip()
                    for x in items)   # r386：只认时刻（无航班号中转行也算真班次）
            except Exception:
                pass
            dep.append({"date": d0, "price": round(float(r["price"])),
                        "capturedAt": r["fetched_at"],
                        "platform": r["platform"], "isCal": is_cal,
                        "rows": r["n"] or 1})
        # 采集日轴只在显式请求时计算：默认出发日轴不需要 _daily_minima
        # 的 1.6 万次 normalize，进检索页不再为另一条轴白等数秒。
        obs = []
        if axis in ("observation", "both"):
            try:
                from report import _daily_minima as _dm
                obs = [{"date": k, "price": round(v), "tier": q}
                       for k, v, q in (_dm(db, fc, tc, base.isoformat(),
                                           "02:00", days=days) or [])]
            except Exception:
                obs = []
    finally:
        conn.close()
    return {"ok": True, "from": fc, "to": tc, "anchor": base.isoformat(),
            "days": days,
            "departure": dep,
            "observation": obs,
            "note": "departure=出发日真实落库最低价（含渠道日历/补位，标注 platform/isCal）；observation=采集日观测最低价（真实航班）；两轴不可互换"}


# ===== r351 指定航班关注与渠道监控 =====
# 关注条目只存身份与监控口径（不存价格/不写监控库），价格与趋势每次按
# flight_prices 实时回放；缺失即空，不生成假历史。文件与库同目录隔离，
# 单文件原子替换，避免与 config.yaml/页面快照互相踩写。
_WATCH_LOCK = threading.RLock()
_WATCH_CACHE = {}
_WATCH_CACHE_TTL = 30.0
# 关注航班可选渠道 = 5 家浏览器 + 已注册的 App 渠道。
#
# 这个元组是 `_watch_channels()` 的**硬白名单**：不在里面的渠道会被
# 静默丢弃（既不报错也不提示），于是「把智行 App 加进关注航班」会
# 填得进去、存不下来。用户要求新渠道接入每个角落，关注台是点名面
# 之一，故从 `crawlers.APP_CHANNELS` 派生而不是写死 5 家。
def _watch_plats() -> tuple:
    base = ["qunar", "ctrip", "tuniu", "fliggy", "tongcheng"]
    try:
        from crawlers import APP_CHANNELS as _apps
        base += [p for p in _apps if p not in base]
    except Exception:
        pass
    return tuple(base)


_WATCH_PLATS = _watch_plats()
_DEMO_WATCH_PATH = None


_CAL_CACHE = {"key": None, "at": 0.0, "val": None}
_CAL_LOCK = threading.Lock()


def _srx_calendar(frm, to, date, days=14, axis="both"):
    """日历缓存（30s，按航线/日期/轴）：默认出发日轴不再懒算采集日轴。"""
    db = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")
    key = (db, str(frm or ""), str(to or ""), str(date or ""),
           int(days or 14), str(axis or "departure"))
    now = time.time()
    with _CAL_LOCK:
        if _CAL_CACHE["key"] == key and now - _CAL_CACHE["at"] < 30:
            return _CAL_CACHE["val"]
        val = _srx_calendar_raw(frm, to, date, days, axis=axis)
        _CAL_CACHE.update(key=key, at=time.time(), val=val)
        return val

def _watch_path():
    if _DEMO_WATCH_PATH:
        return _DEMO_WATCH_PATH
    db = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")
    return os.path.join(os.path.dirname(db) or ".", "flight_watch.json")


def _watch_read():
    try:
        with open(_watch_path(), encoding="utf-8") as f:
            obj = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    if not isinstance(obj, dict):
        return {}
    out = {}
    for user, items in obj.items():
        if not isinstance(user, str) or not isinstance(items, list):
            continue
        clean = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if not (it.get("id") and it.get("flightKey")):
                continue
            # r977：旧记录的 channels 是「浏览器五家」出厂默认，App 渠道
            # 接入后这些记录仍只存 5 家，关注台覆盖分母永远 /5。无
            # channelsRev 的历史行按出厂默认迁移到全渠道（一次性；之后
            # 用户主动取消 App 会带 channelsRev=2 保存，不再被重新加回）。
            if not it.get("channelsRev"):
                it["channels"] = _watch_channels(it.get("channels"), migrate=True)
                it["channelsRev"] = 2
            else:
                it["channels"] = _watch_channels(it.get("channels"))
            it["cabin"] = _watch_cabin(it.get("cabin"))
            it["active"] = bool(it.get("active", True))
            clean.append(it)
        out[user[:80]] = clean
    return out


def _watch_write(data):
    path = _watch_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _watch_cabin(value):
    from core.flighthist import cabin_class
    return cabin_class(str(value or "")[:80])


def _watch_channels(value, allowed=None, migrate=False):
    base = [p for p in (allowed or _WATCH_PLATS) if p in _WATCH_PLATS]
    if not base:
        base = list(_WATCH_PLATS)
    if not isinstance(value, list):
        return list(base)
    if migrate:
        _browser = [p for p in _WATCH_PLATS if not str(p).startswith("app_")]
        _picked = [str(p or "").strip() for p in value]
        if (len(_browser) < len(_WATCH_PLATS) and len(_picked) == len(_browser)
                and set(_picked) == set(_browser)):
            return list(_WATCH_PLATS)
    out = []
    for p in value:
        p = str(p or "").strip()
        if p in base and p not in out:
            out.append(p)
    return out or list(base)


def _watch_user_record(user):
    for u in _State.users or []:
        name = u.get("name") if isinstance(u, dict) else getattr(u, "name", "")
        if str(name or "") == str(user or ""):
            return u
    return None


def _watch_route_enabled(route):
    if isinstance(route, dict):
        return route.get("enabled") is not False
    return getattr(route, "enabled", True) is not False


def _watch_user_routes(user):
    rec = _watch_user_record(user)
    if isinstance(rec, dict):
        routes = list(rec.get("routes") or [])
    else:
        routes = list(getattr(rec, "routes", None) or [])
    # 停用航线不参与采集，也不能作为关注航班的父级
    return [r for r in routes if _watch_route_enabled(r)]


def _watch_route_dates(route):
    """配置航线日期：dates 列表优先；兼容单日与起止区间。"""
    _alias = {"from": "from_code", "to": "to_code",
              "start": "start_date", "end": "end_date"}

    def _get(k):
        if isinstance(route, dict):
            return route.get(k)
        return getattr(route, k, None) or getattr(route, _alias.get(k, ""), None)

    def _day(v):
        s = str(v or "").strip()[:10]
        return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else ""

    dates = [_day(x) for x in (_get("dates") or []) if _day(x)]
    if dates:
        return dates
    one = _day(_get("date"))
    if one:
        return [one]
    start = _day(_get("start_date") or _get("start"))
    end = _day(_get("end_date") or _get("end"))
    if start and end:
        return [start, end]  # 区间端点，下方按区间比较
    return []


def _watch_route_allows(entry, route):
    """关注航班是否继承父航线的适用条件（不是声明上的子集）。

    关注航班是父航线明细集合的指定子集：父航线配了「只要直飞/排除
    跨天/排除经停/出发到达时段/航司名单/渠道」时，关注条目必须真实
    满足这些条件，否则它不属于该集合。返回 (ok, reason)。
    """
    if route is None:
        return False, "父航线不存在"
    def _g(k):
        if isinstance(route, dict):
            return route.get(k)
        return getattr(route, k, None)

    def _mins(v):
        m = re.match(r"^(\d{1,2}):(\d{2})", str(v or ""))
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    dep = _mins(entry.get("depTime"))
    arr = _mins(entry.get("arrTime"))
    for lo_k, hi_k, val, label in (
            ("dep_time_min", "dep_time_max", dep, "出发时段"),
            ("arr_time_min", "arr_time_max", arr, "到达时段")):
        lo, hi = _mins(_g(lo_k)), _mins(_g(hi_k))
        if val is not None:
            if lo is not None and val < lo:
                return False, "不在父航线%s内" % label
            if hi is not None and val > hi:
                return False, "不在父航线%s内" % label
    if _g("direct_only") and entry.get("trans"):
        return False, "父航线只要直飞"
    if _g("no_cross") and entry.get("cross"):
        return False, "父航线排除跨天"
    if _g("exclude_stop") and entry.get("stop"):
        return False, "父航线排除经停"
    if _g("exclude_share") and (entry.get("shareCarrier") or entry.get("codeShare")):
        return False, "父航线排除共享航班"
    if str(_g("transfer_baggage") or "") == "direct" and entry.get("trans"):
        if str(entry.get("bagState") or "") != "direct":
            return False, "父航线要求行李直挂，关注航班无直挂证据"
    _rc = _g("channels")
    if isinstance(_rc, list) and _rc and entry.get("channels"):
        if not set(entry.get("channels") or []).issubset(set(_rc)):
            return False, "关注渠道超出父航线渠道"
    _al = str(_g("airlines") or "").replace("，", ",")
    if _al.strip():
        _want = [x.strip().upper() for x in _al.split(",") if x.strip()]
        _ban = [x[1:].strip() for x in _want if x.startswith("!") and x[1:].strip()]
        _allow = [x for x in _want if not x.startswith("!")]
        _m = re.match(r"^([A-Z0-9]{2})", str(entry.get("code") or "").upper())
        _hay = (str(entry.get("airline") or "") + " " + (_m.group(1) if _m else "")).upper()
        if _ban and any(b in _hay for b in _ban):
            return False, "命中父航线航司排除项"
        if _allow and not any(a in _hay for a in _allow):
            return False, "不在父航线航司名单内"
    return True, ""


def _watch_parent_route(entry, user):
    """关注航班的父级配置航线：同 from/to，且日期在航线日期集合/区间内。"""
    date = str(entry.get("date") or "")[:10]
    frm = str(entry.get("from") or "").upper()
    to = str(entry.get("to") or "").upper()
    if not date or not frm or not to:
        return None
    _ralias = {"from": "from_code", "to": "to_code"}
    for route in _watch_user_routes(user):
        def _g(k):
            if isinstance(route, dict):
                return route.get(k)
            return getattr(route, k, None) or getattr(route, _ralias.get(k, ""), None)
        if str(_g("from") or "").upper() != frm or str(_g("to") or "").upper() != to:
            continue
        dates = _watch_route_dates(route)
        if not dates:
            return route
        if len(dates) == 2:
            start = str(_g("start_date") or _g("start") or "")[:10]
            end = str(_g("end_date") or _g("end") or "")[:10]
            if start and end and start <= date <= end:
                return route
        if date in dates:
            return route
    return None


def _watch_raw_known(entry):
    """flight_daily 尚未聚合时，用近期 raw 行确认候选身份。

    只用于新增/改身份校验（deep），列表渲染不扫 raw，避免关注清单
    每次读取都回放大量 extra。"""
    from core.flighthist import key_from_raw
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT platform, extra FROM flight_prices "
                "WHERE from_city=? AND to_city=? AND depart_date=? "
                "AND extra!='' AND fetched_at >= datetime('now','localtime','-2 days') "
                "ORDER BY id DESC LIMIT 1500",
                (entry.get("from"), entry.get("to"), entry.get("date"))).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return False
    for plat, extra in rows:
        try:
            obj = json.loads(extra or "[]")
        except ValueError:
            continue
        items = obj if isinstance(obj, list) else (
            [obj] if isinstance(obj, dict) else [])
        for raw in items:
            if not isinstance(raw, dict):
                continue
            got = key_from_raw(entry.get("from"), entry.get("to"),
                               entry.get("date"), raw, plat)
            if got and got[1] == entry.get("flightKey"):
                return True
    return False


def _watch_known_flight(entry, deep=False):
    """该航班身份是否已出现在此航线/日期的采集明细中。

    返回 (known, has_rows)。旧库无 flight_daily 或该航线/日期尚无任何
    明细时，返回 (True, False)，表示“等待采集”而不是伪造存在。
    deep=True 时在 daily 未命中后回放近期 raw，覆盖“已采集、日桶
    尚未刷新”的窗口；不会把不存在身份放行。"""
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        conn = sqlite3.connect(db)
        try:
            one = conn.execute(
                "SELECT 1 FROM flight_daily WHERE from_city=? AND to_city=? "
                "AND depart_date=? AND flight_key=? LIMIT 1",
                (entry.get("from"), entry.get("to"),
                 entry.get("date"), entry.get("flightKey"))).fetchone()
            if one:
                return True, True
            any_row = conn.execute(
                "SELECT 1 FROM flight_daily WHERE from_city=? AND to_city=? "
                "AND depart_date=? LIMIT 1",
                (entry.get("from"), entry.get("to"),
                 entry.get("date"))).fetchone()
        finally:
            conn.close()
        if deep and _watch_raw_known(entry):
            return True, True
        return False, bool(any_row)
    except (sqlite3.Error, OSError):
        return True, False


def _watch_scope_detail(entry, user):
    if _State.users and _watch_user_record(user) is None:
        return False, "用户不存在", "user_missing"
    d = str(entry.get("date") or "")
    if d and d < time.strftime("%Y-%m-%d"):
        return False, "航班日期已过", "expired"
    _route = _watch_parent_route(entry, user)
    if _route is None:
        return False, "未匹配关注航线/日期（历史保留；请编辑绑定）", "route_missing"
    _applies, _why = _watch_route_allows(entry, _route)
    if not _applies:
        return False, "不满足父航线适用条件：%s" % _why, "route_filtered"
    known, has_rows = _watch_known_flight(entry)
    if has_rows and not known:
        # 采集轮次可能临时缺行：身份仍属于该航线/日期集合，保留监控，
        # 等下一轮出现；不能因此把关注判成“范围外”或停发提醒。
        return True, "该航班本轮采集明细未出现，等待下一轮；历史保留", "flight_missing"
    return True, "", "ok"


def _watch_scope(entry, user):
    """关注航班是配置航线+日期明细集合中的指定航班子集。

    旧关注若已无对应配置航线/日期，保留身份与历史，但标记为未匹配；
    只有同 from/to 且日期命中的配置航线才产生新的采集/判定。
    """
    if _State.users and _watch_user_record(user) is None:
        return False, "用户不存在"
    d = str(entry.get("date") or "")
    if d and d < time.strftime("%Y-%m-%d"):
        return False, "航班日期已过"
    ok, reason, _state = _watch_scope_detail(entry, user)
    return ok, reason


def _watch_id(flight_key, cabin):
    return hashlib.sha1(
        (str(flight_key) + "|" + str(cabin)).encode("utf-8")).hexdigest()[:20]


def _watch_user(value):
    user = str(value or "").strip()
    if not user:
        raise ValueError("缺少 user")
    if len(user) > 80:
        raise ValueError("user 过长")
    return user


def _watch_entry(payload, old=None, user=None):
    if not isinstance(payload, dict):
        raise ValueError("缺少 watch 对象")
    frm = str(payload.get("from") or "").strip()[:40]
    to = str(payload.get("to") or "").strip()[:40]
    date = str(payload.get("date") or "").strip()[:10]
    code = str(payload.get("code") or "").strip().upper()[:24]
    dep = str(payload.get("depTime") or "").strip()[:8]
    arr = str(payload.get("arrTime") or "").strip()[:8]
    if not all((frm, to, date, code, dep, arr)):
        raise ValueError("关注航班缺少 from/to/date/code/depTime/arrTime")
    if not re.match(r"^[A-Z0-9]{2}\d{1,4}(?:/[A-Z0-9]{2}\d{1,4})*$",
                    code):
        raise ValueError("航班号格式应如 MU541 或 MU541/MU542")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise ValueError("date 必须为 YYYY-MM-DD")
    if old is None and date < time.strftime("%Y-%m-%d"):
        raise ValueError("航班日期已过（%s），不能新增关注" % date)
    # 身份可编后，改到过去日期会生成一条永不采集的“已过期”关注；
    # 仅允许保留原日期（历史关注仍可改渠道/目标做复盘）
    if (old is not None and date < time.strftime("%Y-%m-%d")
            and date != str(old.get("date") or "")):
        raise ValueError("航班日期已过（%s），不能改到过去日期" % date)

    def _hm(v):
        m = re.match(r"^(\d{1,2}):(\d{2})$", str(v or "").strip())
        if not m:
            raise ValueError("起降时刻必须为 HH:MM")
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise ValueError("起降时刻超出范围")
        return "%02d:%02d" % (h, mi)

    dep, arr = _hm(dep), _hm(arr)
    fcode, _fn = _probe_city_code(frm)
    tcode, _tn = _probe_city_code(to)
    if not fcode and re.match(r"^[A-Za-z]{3}$", frm):
        fcode = frm.upper()
    if not tcode and re.match(r"^[A-Za-z]{3}$", to):
        tcode = to.upper()
    if not fcode or not tcode:
        raise ValueError("出发/到达城市无法解析")
    frm, to = fcode, tcode
    _scope_changed = False
    if user is not None and _State.users:
        _scope_changed = (
            old is None
            or str(old.get("from") or "").upper() != frm
            or str(old.get("to") or "").upper() != to
            or str(old.get("date") or "")[:10] != date)
        if _scope_changed and _watch_parent_route(
                {"from": frm, "to": to, "date": date}, user) is None:
            raise ValueError(
                "该航线/日期未配置关注航线；关注航班只能从已配置航线的采集明细中选择")
    trans = str(payload.get("trans") or "").strip()[:40]
    raw_cross = str(payload.get("cross") or "").strip()[:16]
    if raw_cross in ("", "当天", "0", "+0", "+0天"):
        cross = ""
    else:
        m = re.match(r"^\+?\s*(\d)\s*天?$", raw_cross)
        if not m or int(m.group(1)) > 7:
            raise ValueError("cross 必须为当天或 +1天…+7天")
        cross = "+%s天" % m.group(1)
    stop = bool(payload.get("stop"))
    cabin = _watch_cabin(payload.get("cabin"))
    flight_key = _srx_flight_key({
        "from": frm, "to": to, "date": date, "code": code,
        "depTime": dep, "arrTime": arr, "trans": trans,
        "cross": cross, "stop": stop})
    if not flight_key:
        raise ValueError("无法生成航班身份")
    if _scope_changed:
        _known, _has_rows = _watch_known_flight(
            {"from": frm, "to": to, "date": date, "flightKey": flight_key},
            deep=True)
        if _has_rows and not _known:
            raise ValueError("该航班不在此航线/日期的采集明细中；请从实时候选航班中选择")
    target = payload.get("target")
    if target in (None, ""):
        target = None
    else:
        try:
            target = int(round(float(target)))
        except (TypeError, ValueError):
            raise ValueError("target 必须为数字")
        if target <= 0:
            target = None   # 0 等同未设目标：仅观察，不伪装达标线
        elif target > 1000000:
            raise ValueError("target 超出范围")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created = (old or {}).get("createdAt") or payload.get("createdAt") or now
    entry = {
        "id": _watch_id(flight_key, cabin),
        "flightKey": flight_key,
        "from": frm, "to": to, "date": date, "code": code,
        "depTime": dep, "arrTime": arr, "trans": trans,
        "cross": cross, "stop": stop, "cabin": cabin,
        "airline": str(payload.get("airline") or "").strip()[:40],
        "shareCarrier": str(payload.get("shareCarrier") or "").strip()[:40],
        "codeShare": bool(payload.get("codeShare")),
        "bagState": str(payload.get("bagState") or "").strip()[:20],
        "platKey": str(payload.get("platKey") or "").strip()[:20],
        "channels": _watch_channels(payload.get("channels")),
        "channelsRev": 2,
        "target": target,
        "active": bool(payload.get("active", True)),
        "notify": bool(payload.get("notify", True)),
        "note": str(payload.get("note") or "").strip()[:160],
        "createdAt": created, "updatedAt": now,
    }
    if _scope_changed and user is not None and _State.users:
        # 仅身份/范围变更时重验父航线适用条件：历史关注改目标价/渠道
        # 不应被现在的航线筛选挡住（否则旧条目永远保存不了）。
        _pr = _watch_parent_route(entry, user)
        if _pr is None:
            raise ValueError("该航线/日期未配置关注航线")
        _ok, _why = _watch_route_allows(entry, _pr)
        if not _ok:
            raise ValueError("该航班不满足父航线适用条件：%s" % _why)
    return entry


def _watch_in_scope(entry, user):
    return _watch_scope(entry, user)[0]


def _watch_public(entry, user):
    item = dict(entry)
    item["inScope"], item["scopeReason"], item["scopeState"] = _watch_scope_detail(entry, user)
    item["legacy"] = (not item["inScope"] and item["scopeState"] in
                      ("route_missing", "flight_missing", "date_missing"))
    item.setdefault("notify", True)      # 旧文件无 notify 字段：默认开启
    return item


def _watch_list(user):
    with _WATCH_LOCK:
        data = _watch_read()
        items = data.get(user, [])
    return {"ok": True, "user": user,
            "watches": [_watch_public(x, user) for x in items],
            "file": "data/flight_watch.json",
            "note": "关注只保存配置航线+日期下的航班身份与监控口径；价格/趋势每次按该航线真实落库行回放，探针结果不写关注。"}


def _watch_apply(user, body):
    user = _watch_user(user)
    op = str(body.get("op") or "add").strip()
    with _WATCH_LOCK:
        data = _watch_read()
        items = data.get(user, [])
        if op == "add":
            entry = _watch_entry(body.get("watch") or {}, user=user)
            old = next((x for x in items if x.get("id") == entry["id"]), None)
            if old:
                # add 语义=新建；同身份静默 upsert 会覆盖目标/渠道/提醒，
                # 用户看不到任何提示。改为明确冲突，编辑走 update。
                raise ValueError("该航班已在关注清单（%s）；请直接编辑或先移除"
                                 % (old.get("code") or entry.get("code") or ""))
            if len(items) >= 100:
                raise ValueError("关注航班最多 100 条；请先移除不再关注的条目")
            items.insert(0, entry)
        elif op == "update":
            wid = str(body.get("id") or "").strip()
            old = next((x for x in items if x.get("id") == wid), None)
            if not old:
                raise ValueError("关注条目不存在")
            patch = body.get("patch") or {}
            # 身份也可独立编辑：改航线/日期/航班/时刻/舱位时重建 flightKey
            # 与新 id；新身份历史从零累计，旧身份采集记录仍留在明细。
            _ident = {"from", "to", "date", "code", "depTime", "arrTime",
                      "trans", "cross", "stop", "cabin"}
            if _ident & set(patch):
                merged = dict(old)
                merged.update({k: patch[k] for k in _ident if k in patch})
                entry = _watch_entry(merged, old=old, user=user)
                if entry["id"] != wid and any(
                        x is not old and x.get("id") == entry["id"]
                        for x in items):
                    raise ValueError("目标航班已在关注清单，请直接编辑该条")
                if entry["id"] != wid:
                    items[items.index(old)] = entry
                else:
                    old.update(entry)
                old = entry
            if "channels" in patch:
                old["channels"] = _watch_channels(patch.get("channels"))
            if "active" in patch:
                old["active"] = bool(patch.get("active"))
            if "notify" in patch:
                old["notify"] = bool(patch.get("notify"))
            if "target" in patch:
                t = patch.get("target")
                if t in (None, ""):
                    old["target"] = None
                else:
                    try:
                        t = max(0, min(1000000, int(round(float(t)))))
                    except (TypeError, ValueError):
                        raise ValueError("target 必须为数字")
                    old["target"] = t if t > 0 else None
            if "note" in patch:
                old["note"] = str(patch.get("note") or "").strip()[:160]
            old["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif op == "remove":
            wid = str(body.get("id") or "").strip()
            if not any(x.get("id") == wid for x in items):
                raise ValueError("关注条目不存在")
            items = [x for x in items if x.get("id") != wid]
        else:
            raise ValueError("未知操作")
        data[user] = items
        _watch_write(data)
        _WATCH_CACHE.clear()
    return {"ok": True, "user": user,
            "watches": [_watch_public(x, user) for x in data[user]]}


def _watch_match_key(entry, g):
    return _srx_flight_key({
        "from": entry.get("from"), "to": entry.get("to"),
        "date": entry.get("date"), "code": g.get("code"),
        "depTime": g.get("depTime"), "arrTime": g.get("arrTime"),
        "trans": g.get("transCity") or "",
        "cross": g.get("crossDayDesc") or "",
        "stop": bool(g.get("stopover")),
    })


def _flight_trend_core(entry, days=14):
    """航班历史核心：raw 采集点 + flight_daily 日桶（关注无关）。

    raw 明细提供采集时刻级点；flight_daily 提供 raw purge 后的日 OHLC。
    两者都只来自真实落库行，不补点、不插值。
    """
    days = max(1, min(int(days or 14), 180))
    cache_key = (entry.get("flightKey"), entry.get("cabin") or "",
                 tuple(entry.get("channels") or ()), days)
    now = time.time()
    cached = _WATCH_CACHE.get(cache_key)
    if cached and now - cached[0] < _WATCH_CACHE_TTL:
        return cached[1]
    fc, _ = _probe_city_code(entry.get("from"))
    tc, _ = _probe_city_code(entry.get("to"))
    if not (fc and tc):
        raise ValueError("关注城市无法解析")
    db = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")
    chans = entry.get("channels") or list(_WATCH_PLATS)
    marks = ",".join("?" for _ in chans)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, platform, price, extra, fetched_at FROM flight_prices "
            "WHERE platform IN (%s) AND from_city=? AND to_city=? "
            "AND depart_date=? AND extra!='' AND fetched_at >= "
            "datetime('now', 'localtime', ?) "
            "ORDER BY fetched_at DESC, id DESC LIMIT 12000" % marks,
            tuple(chans) + (fc, tc, entry.get("date"),
                            "-%d days" % days)).fetchall()
        rows = list(reversed(rows))      # 保留最新 12000 行后回正序
        hsql = ("SELECT day,platform,n,lo,hi,open,close,fetched_max,cabin "
                "FROM flight_daily WHERE from_city=? AND to_city=? "
                "AND depart_date=? AND flight_key=? "
                "AND day>=date('now','localtime',?) "
                "AND platform IN (%s) " % marks)
        hargs = [fc, tc, entry.get("date"), entry.get("flightKey"),
                 "-%d days" % days] + list(chans)
        if entry.get("cabin"):
            hsql += "AND cabin=? "
            hargs.append(entry.get("cabin"))
        hsql += "ORDER BY day, platform, cabin"
        try:
            hrows = conn.execute(hsql, hargs).fetchall()
        except sqlite3.OperationalError:
            hrows = []      # 旧库未建 flight_daily 时 raw 路径照常
    finally:
        conn.close()
    from core.flightnorm import normalize as _fnorm
    from core.flightnorm import dep_mismatch as _dmis
    from core.flightnorm import cabin_text as _cabtxt
    points, daily, latest = [], {}, {}
    for r in rows:
        try:
            obj = json.loads(r["extra"] or "[]")
        except ValueError:
            continue
        items = obj if isinstance(obj, list) else (
            [obj] if isinstance(obj, dict) else [])
        for idx, raw in enumerate(items):
            if not isinstance(raw, dict) or raw.get("price") in (None, ""):
                continue
            g = dict(raw)
            g["_platform"] = r["platform"]
            _fnorm(g, entry.get("date") or "")
            if _dmis(g, entry.get("date") or ""):
                continue
            if _watch_match_key(entry, g) != entry.get("flightKey"):
                continue
            if entry.get("cabin"):
                # 舱位口径：raw 未给舱位的行不能确认属于该舱，宁缺勿错
                if _watch_cabin(_cabtxt(g)) != entry.get("cabin"):
                    continue
            try:
                price = round(float(g.get("price")))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            eff = _qual_price({"price": price, "_platform": r["platform"],
                               "intl": 1 if g.get("intl") else 0})
            at = str(r["fetched_at"] or "")
            day = at[:10]
            points.append([at, price, r["platform"], round(float(eff), 1),
                           int(r["id"] or 0), idx, _watch_cabin(_cabtxt(g))])
            if day:
                cur = daily.get(day)
                if cur is None or price < cur:
                    daily[day] = price
            last = latest.get(r["platform"])
            if not last or at >= last.get("at", ""):
                latest[r["platform"]] = {
                    "price": price, "eff": round(float(eff), 1),
                    "at": at, "rowId": int(r["id"] or 0), "idx": idx,
                    "cabin": _watch_cabin(_cabtxt(g))}
    history = []
    for h in hrows:
        try:
            history.append({
                "day": str(h["day"]), "platform": str(h["platform"]),
                "n": int(h["n"] or 0), "lo": float(h["lo"]),
                "hi": float(h["hi"]), "open": float(h["open"]),
                "close": float(h["close"]),
                "cabin": str(h["cabin"] or ""),
                "fetched_max": str(h["fetched_max"] or "")})
        except (TypeError, ValueError):
            continue
    hist_daily = {}
    for h in history:
        d = h["day"]
        if d and (d not in hist_daily or h["lo"] < hist_daily[d]):
            hist_daily[d] = h["lo"]
    for d, v in hist_daily.items():
        if d not in daily or v < daily[d]:
            daily[d] = v
    if not latest and history:
        last_day = max(h["day"] for h in history)
        for h in history:
            if h["day"] != last_day:
                continue
            prev = latest.get(h["platform"])
            # 同平台同日可能有多舱位日桶；取最低 close，不按 SQL 行序取任意一条
            if prev is None or h["close"] < prev.get("price", 1e18):
                latest[h["platform"]] = {
                    "price": h["close"], "eff": h["close"],
                    "at": h["fetched_max"], "rowId": 0, "idx": 0,
                    "agg": True, "day": last_day, "cabin": h["cabin"]}
    if len(points) > 1500:
        points = points[-1500:]
    cur = None
    if latest:
        p0, best = min(latest.items(), key=lambda kv: kv[1]["eff"])
        cur = {"platform": p0, **best}
    out = {"ok": True, "id": entry.get("id"), "days": days,
           "from": fc, "to": tc, "date": entry.get("date"),
           "channels": chans, "points": points,
           "daily": sorted(daily.items()), "history": history,
           "latest": latest, "current": cur,
           "scannedRows": len(rows),
           "note": "点=按采集时刻回放的真实同航班同舱位行；日桶=全航线采集落库、按平台/舱位分组的日 OHLC（不依赖关注配置）；price 为渠道列表价，eff 为达标口径（飞猪加税垫）；raw 未给舱位的行不并入指定舱；没有采集点不生成历史"}
    _WATCH_CACHE[cache_key] = (now, out)
    if len(_WATCH_CACHE) > 64:
        _WATCH_CACHE.pop(next(iter(_WATCH_CACHE)))
    return out


def _watch_trend(user, wid, days=14):
    user = _watch_user(user)
    with _WATCH_LOCK:
        entries = _watch_read().get(user, [])
        entry = next((x for x in entries if x.get("id") == str(wid)), None)
    if not entry:
        raise ValueError("关注条目不存在")
    return _flight_trend_core(entry, days)


def _flight_trend(payload, days=14):
    """任意航班的真实历史：无需先加入关注（全航线采集已落 flight_daily）。"""
    entry = _watch_entry(payload)
    out = _flight_trend_core(entry, days)
    out["watch"] = False
    out["flight"] = {
        "from": entry.get("from"), "to": entry.get("to"),
        "date": entry.get("date"), "code": entry.get("code"),
        "depTime": entry.get("depTime"), "arrTime": entry.get("arrTime"),
        "trans": entry.get("trans"), "cross": entry.get("cross"),
        "stop": entry.get("stop"), "cabin": entry.get("cabin")}
    return out


def _mc_field(r, name, default=None):
    """多程航线字段：配置 dict 与运行时 Route 两形同读。"""
    if isinstance(r, dict):
        return r.get(name, default)
    return getattr(r, name, default)


def _multicity_alert_round(user, notifier, storage, logger, base_url="",
                           drop_min=10):
    """多程整单达标提醒：只按渠道页面自报总价判定，按行程去抖。

    与关注航班同一套纪律：价格回到线上方清 0，下次跌破可再提醒；
    继续下探仅在跌幅达 drop_min 时补推；通知未被接受不写状态。
    """
    from core.multicity import segments_key
    if notifier is None or storage is None:
        return 0
    uname = _mc_field(user, "name", "") or ""
    routes = _mc_field(user, "routes", []) or []
    sent = 0
    for r in routes:
        if _mc_field(r, "enabled", True) is False:
            continue
        segs = _mc_segments_of(r)
        if not segs:
            continue
        # 首段已过期不提醒（与关注航班同一纪律；行龄 6h 挡不住隔夜过期行程）
        if segs[0]["date"] < datetime.now().strftime("%Y-%m-%d"):
            continue
        try:
            key = segments_key(segs)
            thr = float(_mc_field(r, "alert_threshold", 0) or 0)
        except Exception:
            continue
        if thr <= 0:
            continue
        try:
            rows = storage.itineraries(segments_key=key, limit=1)
        except Exception:
            continue
        if not rows:
            continue
        row = rows[0]
        if str(row.get("platform") or "") not in (
                _mc_field(user, "platforms", []) or []):
            continue
        try:
            price = float(row.get("total_price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        try:
            age = (datetime.now() - datetime.strptime(
                str(row.get("fetched_at") or ""),
                "%Y-%m-%d %H:%M:%S")).total_seconds()
        except (TypeError, ValueError):
            age = 1e9
        if age > 6 * 3600:
            continue
        dk = "mc|%s|%s|%s" % (uname, key, int(round(thr)))
        try:
            last = storage.get_alert_state(dk)
        except Exception:
            last = None
        if price > thr:
            if last not in (None, 0):
                try:
                    storage.set_alert_state(dk, 0)
                except Exception:
                    pass
            continue
        if last is not None and last > 0 and price > last - drop_min:
            continue
        pname = Alerter.plat_cn(str(row.get("platform") or "")) or "渠道"
        chain = _mc_chain_label(segs)
        extra = row.get("extra") or {}
        leg_lines = []
        for i, leg in enumerate(extra.get("legs") or []):
            times = "%s→%s" % (leg.get("dep") or "—", leg.get("arr") or "—")
            leg_lines.append("- 第%d段 %s %s→%s %s %s" % (
                i + 1, leg.get("flight_no") or "—",
                leg.get("from") or "", leg.get("to") or "",
                leg.get("date") or "", times))
        base = (base_url or "").rstrip("/")
        if re.match(r"^https?://(127\.0\.0\.1|localhost)([:/]|$)", base):
            base = ""
        link = base or ""
        title = "🚨 多程整单达标｜%s ¥%s" % (chain, int(round(price)))
        desp = (
            "### 多程整单总价达标\n\n"
            "**%s** · %d 段\n\n"
            "- 当前整单：**¥%s**（%s，%s）\n"
            "- 心理价：¥%s，低于目标 **¥%s**\n"
            "- 整单口径：渠道页面自报「多程含税价」，不是各段单程相加\n"
            "%s%s"
        ) % (
            chain, len(segs), int(round(price)), pname,
            row.get("fetched_at") or "—", int(round(thr)),
            int(round(thr - price)),
            ("\n" + "\n".join(leg_lines)) if leg_lines else "",
            ("\n\n[打开控制台核对行程](%s)" % link) if link else "")
        try:
            res = notifier.send(title, desp)
        except Exception as e:
            logger.warning("[多程] %s %s 提醒发送失败：%s", uname, chain, e)
            continue
        if res is False:
            logger.warning("[多程] %s %s 提醒未被通知器接受", uname, chain)
            continue
        try:
            storage.set_alert_state(dk, price)
        except Exception:
            pass
        sent += 1
        logger.info("[多程] %s %s 达标 ¥%s ≤ ¥%s，已提醒",
                    uname, chain, int(round(price)), int(round(thr)))
    return sent


def _watch_alert_round(user, notifier, storage, logger, base_url="",
                       drop_min=10):
    """关注航班目标提醒：每轮扫描后按真实落库行核对目标。

    去抖键含目标价：目标改变即重新起算；价格回到目标上方时清 0，
    下次跌破可再提醒；同一目标下的继续下探仅在跌幅达到 drop_min
    时补推，避免每轮同价刷屏。通知失败不写状态，下轮可重试。
    """
    if notifier is None or storage is None:
        return 0
    sent = 0
    try:
        items = _watch_list(user).get("watches") or []
    except Exception:
        return 0
    for w in items:
        if w.get("active") is False or w.get("notify") is False:
            continue
        if w.get("target") in (None, "") or not w.get("inScope"):
            continue
        if str(w.get("date") or "") < datetime.now().strftime("%Y-%m-%d"):
            continue
        try:
            target = int(round(float(w.get("target"))))
        except (TypeError, ValueError):
            continue
        try:
            tr = _watch_trend(user, w.get("id"), days=2)
        except Exception:
            continue
        cur = tr.get("current") or {}
        # 达标判定与检索台「达标」标记同口径：eff（含税垫/跨渠道口径），
        # 不是渠道列表裸价。两者不一致会出现 UI 未达标却推送的情况。
        price = cur.get("eff")
        if price is None:
            price = cur.get("price")
        if price is None:
            continue
        _route = _watch_parent_route(w, user)
        _maxp = 0
        try:
            _maxp = float((_route or {}).get("price_max") or 0) if isinstance(_route, dict) else float(getattr(_route, "price_max", 0) or 0)
        except (TypeError, ValueError):
            _maxp = 0
        if _maxp and price > _maxp:
            continue
        try:
            _age = (datetime.now() - datetime.strptime(
                str(cur.get("at") or ""), "%Y-%m-%d %H:%M:%S")).total_seconds()
        except (TypeError, ValueError):
            _age = 1e9
        if _age > 6 * 3600:
            continue
        key = "watch|%s|%s|%s|%s" % (
            user, w.get("id"), w.get("date"), target)
        try:
            last = storage.get_alert_state(key)
        except Exception:
            last = None
        if price > target:
            if last not in (None, 0):
                try:
                    storage.set_alert_state(key, 0)
                except Exception:
                    pass
            continue
        if last is not None and last > 0 and price > last - drop_min:
            continue
        pname = Alerter.plat_cn(str(cur.get("platform") or "")) or "渠道"
        gap = target - price
        latest = tr.get("latest") or {}
        covered = len(latest)
        total = len(w.get("channels") or [])
        base = (base_url or "").rstrip("/")
        if re.match(r"^https?://(127\.0\.0\.1|localhost)([:/]|$)", base):
            base = ""
        link = "%s/#watch/u%s" % (base, _watch_user_index(user)) if base else ""
        title = "🎯 关注航班达标｜%s ¥%s" % (w.get("code") or "—", price)
        desp = (
            "### 指定航班目标价提醒\n\n"
            "**%s** %s→%s · %s · %s→%s%s\n\n"
            "- 当前最低：**¥%s**（%s，%s）\n"
            "- 目标价：¥%s，低于目标 **¥%s**\n"
            "- 同班覆盖：%d/%d 个监控渠道\n"
            "- 采集时间：%s\n"
            "%s"
        ) % (
            w.get("code") or "—", w.get("from") or "", w.get("to") or "",
            w.get("date") or "", w.get("depTime") or "—",
            w.get("arrTime") or "—",
            (" · 经 " + w.get("trans")) if w.get("trans") else "",
            price, pname, cur.get("at") or "—", target, gap,
            covered, total, cur.get("at") or "—",
            ("\n[打开关注航班监控台](%s)" % link) if link else "")
        try:
            res = notifier.send(title, desp)
        except Exception as e:
            logger.warning("[关注] %s %s 提醒发送失败：%s",
                           user, w.get("code"), e)
            continue
        if res is False:
            logger.warning("[关注] %s %s 提醒未被通知器接受",
                           user, w.get("code"))
            continue
        try:
            storage.set_alert_state(key, price)
        except Exception:
            pass
        sent += 1
        logger.info("[关注] %s %s 达标 ¥%s ≤ ¥%s，已提醒",
                    user, w.get("code"), price, target)
    return sent


def _watch_user_index(user):
    """控制台用户段（用于关注提醒里的本机深链）。"""
    try:
        for i, u in enumerate(_State.users or []):
            nm = u.get("name") if isinstance(u, dict) else getattr(u, "name", "")
            if str(nm or "") == user:
                return i
    except Exception:
        pass
    return 0


def _state_stale_hours():
    """补位窗口随调度周期：7 天一轮的配置不能在 6h 后把整页清空。"""
    try:
        iv = float(((_State.cfg or {}).get("schedule") or {}).get(
            "interval_minutes", 30) or 30)
    except Exception:
        iv = 30.0
    return int(max(6, min(168, iv / 60.0 + 1)))


def _user_state(u):
    """单个用户的状态视图（最新轮明细 + 近期补位 + 走势历史）。

    探针/测试构造 /api/state 变体前必读的形状契约（r333 空态构造
    三连撤的备案落点，LESSONS 廿三§1 异步失败落点域）：history/
    history7/th 恒为 {direct:[],transfer:[]} 对象——history 塞 [] 或
    th 塞 null → 前端 H0.direct/CR.r.th.direct TypeError（探针伪影
    非缺陷）；best 恒为 {direct:brief|null,transfer:brief|null}
    （未扫描=brief 内层 null，best 本体不 null）；「已配置未扫描」
    服务端真形=routesArr/routesTxt 在、各 history 空数组、brief
    null、hit False——逐字段对齐后再构造。"""
    st = _State
    db = _anchored((st.cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # 当轮窗口随调度周期放宽：固定 -40min 在 30min 周期下，一轮跨多
    # 航线跑 20min + 调度抖动就會整轮落在窗外，主路径一行取不到→全量
    # 走近期补位，页面满屏「补位」（用户实报根因）。下限 40min 保留
    # 原行为，长周期配置按 周期×1.5+20 放宽，上限 3h。
    try:
        _iv = float((st.cfg.get("schedule") or {}).get(
            "interval_minutes", 30) or 30)
    except Exception:
        _iv = 30.0
    _win = int(min(180, max(40, _iv * 1.5 + 20)))
    # prov 必须随行取出：下游 g["_prov"]=r["prov"] 直接喂给 /api/state
    # 的 prov 字段；缺列时每行都落到 except 分支变成 {}，整页补位行
    # 失去来源（用户实报「补位数据看着奇怪、无法核对」）。旧库/测试库
    # 可能没有该列，按 PRAGMA 自适应，缺列时行为与旧版一致。
    _has_prov = any(_r[1] == "prov" for _r in conn.execute(
        "PRAGMA table_info(flight_prices)").fetchall())
    rows = conn.execute(
        "SELECT rowid AS id, platform, from_city, to_city, depart_date, price, "
        "extra, fetched_at" + (", prov" if _has_prov else "") + " "
        "FROM flight_prices "
        "WHERE extra != '' AND fetched_at >= "
        "datetime('now', 'localtime', ?) "
        "ORDER BY id DESC", ("-%d minutes" % _win,)).fetchall()
    conn.close()
    flights, latest, seen = [], "", set()
    plat_min = {}
    # 停用航线不进 routesArr/日历（日报 _chart_routes
    # 已滤对齐）：生产 cfg 路线是 dict（enabled:false 滤）、demo 是
    # Route 对象（无 enabled 字段，getattr 兜底不误杀）
    def _enabled(r):
        if isinstance(r, dict):
            return r.get("enabled") is not False
        return getattr(r, "enabled", True) is not False
    raw_routes = [r for r in (u.get("routes") or []) if _enabled(r)]
    mc_raw = [r for r in raw_routes if _mc_segments_of(r)]
    routes = [_route_view(r) for r in raw_routes
              if not _mc_segments_of(r)]
    # 出发时段约束（与告警链路同一套窗口；按 航线+日期 粒度，
    # 同航线不同日期可有不同窗口，如返程 10-4 仅晚间 / 10-5 全天）
    win = {}
    for r in routes:
        if (r.get("dep_time_min") or "").strip() or (r.get("dep_time_max") or "").strip():
            for d in r.get("dates") or [""]:
                win[(r["from"], r["to"], d)] = (
                    r["dep_time_min"].strip(), r["dep_time_max"].strip())

    def _keep(f):
        pair = f.get("_pair")
        w = win.get((pair[0], pair[1], f.get("depDate", "")))
        if not w:
            return True
        return Alerter._dep_in_window(f.get("depTime", ""), w[0], w[1])

    from core.models import price_band_ok

    def _price_in_band(v, el=None):
        """列表端价格带兜底（与曲线 _rounds 同带单源 core.models，
        r325 委托 price_band_ok scope-aware：国际行元素 intl 键即
        国际带，勿被国内窄带丢行）：曲线端有 _rounds 带过滤而列表端
        曾零防线——纵深不对称，爬虫端把关一旦回归即「列表可见、图上
        不可见」反向复演。两处 flights 收集点（当轮展开+近 6h 补位）
        同挂；非数值=False 宁缺勿错。"""
        return price_band_ok(v, el=el)

    # 该用户关注的航线集合（明细/全线最低都只看自己航线）
    my_pairs = {(r["from"], r["to"]) for r in routes}
    rows = _cluster_round_rows(rows, scan_start=_scan_marker_window())
    # 跨渠道孤低价守卫·行级：FlightPrice 行=渠道最低价，幻影
    # 渠道最低（< 其他渠道最低中位 ×0.5）不进 plat_min（概览 mchip 曾
    # 直出「￥700」）、不进明细池。Row 不可写 → 按下标集合标记
    _row_ph = set()
    _rgrp = {}
    for _ri, r in enumerate(rows):
        _rgrp.setdefault(
            (r["from_city"], r["to_city"], r["depart_date"]), []).append(_ri)
    for _idxs in _rgrp.values():
        _ent = [(rows[i]["price"]
                 + (FLIGGY_TAX_PAD if rows[i]["platform"] == "fliggy" else 0),
                 rows[i]["platform"]) for i in _idxs]
        for i in xchan_phantom_idx(_ent):
            _row_ph.add(_idxs[i])
    for ri, r in enumerate(rows):
        if ri in _row_ph:
            continue
        if my_pairs and (r["from_city"], r["to_city"]) not in my_pairs:
            continue
        try:
            obj = json.loads(r["extra"])
        except Exception:
            continue
        if not isinstance(obj, list):
            continue
        # 同一渠道/日期可能有“日历行 + 明细行”两类 parent row：都保留
        # （日历行供检索台显式展示），但 plat_min 只取真实航班元素，
        # 旧实现先按 (platform,date) 只留第一行，日历行会把真实行挤掉。
        real_items = [x for x in obj if isinstance(x, dict)
                      and str(x.get("code") or "").strip()
                      and str(x.get("depTime") or "").strip()
                      and str(x.get("arrTime") or "").strip()]
        kind = "real" if real_items else "cal"
        seen_key = (r["platform"], r["from_city"], r["to_city"],
                    r["depart_date"], kind)
        if seen_key in seen:
            continue
        seen.add(seen_key)
        if real_items:
            _prices = []
            for _x in real_items:
                if "price" not in _x or not _price_in_band(_x.get("price"), _x):
                    continue
                try:
                    _prices.append(round(float(_x["price"])))
                except (TypeError, ValueError):
                    pass
            if _prices:
                plat_min[r["platform"]] = min(
                    plat_min.get(r["platform"], 9e9), min(_prices))
        if isinstance(obj, list):
            from core.flightnorm import normalize as _fnorm
            for _ri, f in enumerate(obj):
                if isinstance(f, dict) and "price" in f and _price_in_band(f.get("price"), f):
                    g = dict(f)
                    g["_platform"] = r["platform"]
                    g["_pair"] = (r["from_city"], r["to_city"])
                    # 生产溯源自证：原始行 ID + 原始 extra 下标 + 采集时刻
                    # （/api/probe/raw 按这两个键回放同一行，不重新解析）
                    g["_row_id"] = r["id"]
                    g["_fetched_at"] = r["fetched_at"]
                    g["_raw_idx"] = _ri
                    g["_prov"] = (r["prov"] if _has_prov else "") or ""
                    _fnorm(g, r["depart_date"] or "")
                    if g.get("_dep_mismatch"):
                        continue   # 渠道滚动行不入列表池（与推送/曲线同滤）
                    if _keep(g):
                        flights.append(g)
    route = routes[0] if routes else {}
    th_d = float(route.get("alert_direct", 0) or 0)
    th_t = float(route.get("alert_transfer", 0) or 0)
    am = route.get("transfer_arrival_max", "02:00") or "02:00"
    route_by_pair = {(r["from"], r["to"]): r for r in routes}
    # 同航线不同日期可有不同阈值/窗口（如乌→上 10/04 线 1600、10/05 线 1900）：
    # 按城市对索引会让后配置的日期覆盖前者——必须 (航线,日期) 精确匹配再回退航线
    route_by_fd = {}
    for _r in routes:
        for _d0 in _r.get("dates") or [""]:
            route_by_fd[(_r["from"], _r["to"], _d0)] = _r

    def _rr_of(f):
        _p = f.get("_pair") or ("", "")
        return (route_by_fd.get((_p[0], _p[1], f.get("depDate", "")))
                or route_by_pair.get(_p) or route)

    # 达标判定与推送同口径（Alerter._transfer_ok）：直飞仅比阈值；中转=
    # 到达约束 + 衔接下限 + 直挂约束；layoverM 缺失按不满足（宁漏不虚报）。
    # 每行按所属航线的阈值（同航线不同日期可有不同线）。概览 KPI/浏览器
    # 通知与明细行共用本函数——三个通道对「能不能出手」同一句话。
    def _qual_of(f, transfer, price):
        rq = _rr_of(f)
        # 补位行（近 6h 缓存）不是当轮实时可出手机票：与 hit/推送链
        # 「达标只认当轮」同口径。旧实现只排除日历行，主表仍把 0.2h
        # 补位标成真达标（r355 独立审计实锤）。
        if f.get("_stale_h"):
            return False
        # 日历薄行（只有渠道最低价、无航班号/时刻）不是可出手机票：
        # 旧实现把 719 日历价标成“真达标”，KPI/hit 也被点亮——这是
        # 数据诚实红线，宁可少一个绿点，不把日历价冒充可购买机票。
        if not (str(f.get("code") or "").strip()
                and str(f.get("depTime") or "").strip()
                and str(f.get("arrTime") or "").strip()):
            return False
        # 孤低价行永不判达标（与推送/走势同一防线，控制台不留例外口子）
        if f.get("_xphan"):
            return False
        # 达标口径价：飞猪税前展示价加税垫（与推送 _collect_hits 同式；
        # 国际行含税口径免税垫，intl 键随行透传）
        eff = _qual_price({"price": price,
                           "_platform": f.get("_platform"),
                           "intl": f.get("intl")})
        if transfer:
            qt = float(rq.get("alert_transfer", 0) or 0)
            return bool(qt and eff <= qt and Alerter._transfer_ok(f, {
                "transfer_arrival_max": rq.get("transfer_arrival_max", "02:00") or "02:00",
                "transfer_layover_min": float(rq.get("transfer_layover_min", 0) or 0),
                "transfer_baggage": rq.get("transfer_baggage", "")}))
        qd = float(rq.get("alert_direct", 0) or 0)
        return bool(qd and eff <= qd)
    # 近期明细补位：当轮缺明细的平台用近 6h 成功明细——与推送链同款
    # 逐航线×日期补齐（曾只补 routes[0] 首日期：多日期/多航线时钉钉
    # 明细有该渠道补位价而控制台没有）
    from core.flightnorm import dep_mismatch as _dmm
    try:
        have_pd = {((f.get("_pair") or ("", ""))[0],
                    (f.get("_pair") or ("", ""))[1],
                    f.get("_platform"), f.get("depDate", ""))
                   for f in flights
                   if str(f.get("code") or "").strip()
                   and str(f.get("depTime") or "").strip()
                   and str(f.get("arrTime") or "").strip()}
        # 当轮日历行也算「已供」：否则 recent 补位会把同一条日历行再加
        # 一遍（rowId=None + _stale_h=0.1），列表出现同渠道同日历价双行，
        # KPI 日历价/补位行重复计数。明细补位仍保留（当轮只有日历时，
        # 近 6h 航班明细仍有观察价值）。
        have_cal = {((f.get("_pair") or ("", ""))[0],
                     (f.get("_pair") or ("", ""))[1],
                     f.get("_platform"), f.get("depDate", ""))
                    for f in flights
                    if not (str(f.get("code") or "").strip()
                            and str(f.get("depTime") or "").strip()
                            and str(f.get("arrTime") or "").strip())
                    and f.get("price") not in (None, "")}
        recent = {}
        for _r in routes:
            for _d0 in _r.get("dates") or [""]:
                _k3 = (_r.get("from", ""), _r.get("to", ""))
                for p, (age, fl) in recent_platform_flights(
                        db, _k3[0], _k3[1], _d0, hours=_state_stale_hours()).items():
                    if (_k3[0], _k3[1], p, _d0) in have_pd:
                        continue
                    _prev = recent.get((_k3[0], _k3[1], p, _d0))
                    if not _prev or age < _prev[0]:
                        recent[(_k3[0], _k3[1], p, _d0)] = (age, fl, _k3)
        for (_frm0, _to0, p, _d0), (age, fl, _k3) in recent.items():
            for f in fl:
                if isinstance(f, dict) and "price" in f and _price_in_band(f.get("price"), f):
                    if not Alerter._stale_sane(f):
                        continue
                    g = dict(f)
                    g["_platform"] = p
                    g["_stale_h"] = max(0.1, round(age, 1))
                    g["_fetched_at"] = g.get("_fetched_at") or f.get(
                        "_fetched_at") or ""
                    # 补位行溯源必须随行进入列表池：recent_platform_flights
                    # 已把 DB 的 prov 挂到 _prov，合并时若只拷 fetched_at，
                    # /api/state 里所有补位行的 prov 都会退化成 {}。
                    if not g.get("_prov"):
                        g["_prov"] = f.get("_prov") or ""
                    g["_pair"] = _k3
                    g["depDate"] = g.get("depDate") or _d0
                    _is_cal = not (str(g.get("depTime") or "").strip()
                                   and str(g.get("arrTime") or "").strip())
                    if _is_cal and (_frm0, _to0, p, g["depDate"]) in have_cal:
                        continue   # 当轮已有同日历行：补位不再复制一条
                    if _dmm(g, _d0):
                        continue   # 渠道滚动行不入列表池（与推送/曲线同滤）
                    if _keep(g):
                        flights.append(g)
    except Exception:
        pass
    # 先全量归一化，再做同指纹衔接补全（qunar 列表页不渲染停留时长，
    # 同班次在携程测得的真实停留补到缺行——与聚合池同口径）
    from core.flightnorm import normalize as _fnorm_all, prate_txt
    import logging as _logging
    _lg_state = _logging.getLogger("ticket-monitor")
    for f in flights:
        try:
            _fnorm_all(f, f.get("depDate", ""))
        except Exception as e:
            # 归一化失败曾整行静默丢弃零留痕（访客审计会质疑吞异常）——
            # debug 级留痕，坏数据可回溯
            _lg_state.debug("state 归一化失败 %s: %s", f.get("name", "?"), e)
    Alerter._propagate_layover(flights)
    # 跨渠道孤低价守卫·明细级（与告警池/走势池同一判定）：
    # 按 航线×日期×直/中 分组打 _xphan——明细行保留显示（原始保真）但
    # 永不判达标、不进行情最优/KPI（前端价格挂 ⚠ 角标）
    _fgrp = {}
    for f in flights:
        _fgrp.setdefault((f.get("_pair"), f.get("depDate", ""),
                          bool(f.get("transCity"))), []).append(f)
    for _g in _fgrp.values():
        Alerter._mark_xchan(_g)
    def _int_or_none(v):
        """int 协议键统一转写：渠道缺省空串/None/脏值
        → None（前端 !=null 门才干净）；非整数值（840.0 浮型）取整。"""
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _prov_obj(v):
        if not v:
            return {}
        try:
            obj = json.loads(v)
        except (TypeError, ValueError):
            return {}
        return obj if isinstance(obj, dict) else {}

    def _num_or_none(v):
        """float 协议键转写（_int_or_none 同型）：儿童票半价可出现
        X.5，int 取整会丢 5 角——数值即透传，脏值→None 不占位。"""
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out = []
    for f in flights:
        transfer = bool(f.get("transCity"))
        try:
            price = round(float(f["price"]))
        except (TypeError, ValueError):
            price = f["price"]
        # 多航线：每行明细按其所属航线的阈值判达标
        qual = _qual_of(f, transfer, price)
        # 日历/薄行没有航班身份，只有一条渠道最低价：不参与达标判定，
        # 也不得落 near/brk（否则明细会给出「行情破线」的绿描边暗示）
        is_cal = not (f.get("depTime") and f.get("arrTime"))
        rr = _rr_of(f)
        # 每行都带航线标签+📈 走势入口：走势是可观测性的基础能力，
        # 单启用航线×单日期也必须能点开（旧条件曾让整表入口消失）。
        rt_label = f"{rr.get('from_name','')}→{rr.get('to_name','')}" if rr else ""
        thv = float(rr.get("alert_transfer" if transfer else "alert_direct", 0) or 0)
        # 明细行链接保持该行自身渠道（行价=该渠道报价，落点价=文案价）；
        # 同价跨渠道优选只做在概览 KPI 卡与推送链接（_pref_platform）
        # R28（RT 深链复议）：日历行渠道自带 RT 感知深链（tripType=1+
        # arrDate，飞猪日历 url 字段实证）优先——_view_url 恒单程形态，
        # 往返行点开单程页=所见非所点
        view = (str(f.get("view") or "").strip()
                or _view_url(rr, f.get("depDate", ""),
                             f.get("_platform") or ""))
        if view and not view.lower().startswith(("http://", "https://")):
            view = ""   # 第三方 raw 注入 javascript:/data: 的防线
        # 空/未知平台 _view_url 返回 ""（宁缺勿错，不出去哪儿挂羊头链）
        # 擦边：未达标但距线 10% 以内（表格琥珀提示，扫读一眼看出快到了）
        # 擦边带宽 NEAR_RATIO 已收口 core.alerter 单源
        near = (not qual and not is_cal and not f.get("_stale_h") and thv > 0
                and 0 < (price - thv) / thv <= NEAR_RATIO)
        # 行情破线未达标（第四档，前端描边绿）：价≤线但非直挂/衔接不足/
        # 税前等约束不满足；near 价>线与本档价≤线天然互斥（brk 低优先）
        brk = (not qual and not is_cal and not f.get("_stale_h") and thv > 0
               and price <= thv)
        from core.flightnorm import (cabin_text as _ct, cabin_clean as _cc,
                                     cabin_class as _ccl, normalize as _fnorm)
        _fnorm(f, f.get("depDate", ""))  # 幂等兜底：demo 等未过汇聚点的路径
        # 真实舱位单源：cabinT 是「舱名·折扣·机型·行李」描述串，不能当
        # 舱位列消费（qunar H5 无舱名时该串只剩机型/折扣，明细「舱位」
        # 曾显示「空客320(中)·10折」）。cabin 只保留舱名/舱系，脏词
        # （机型/折扣/未知码）经 cabin_class 归零，宁缺勿错。
        _cab_src = f.get("cabin") or f.get("cabinName") or ""
        _cab_real = _ccl(_cc({"cabin": _cab_src, "price": f.get("price"),
                              "bizPrice": f.get("bizPrice")}))
        # 决策字段透传（爬虫端 normalize 落库，缺失=None → 前端空值不占位）：
        # 航站楼 depTerminal/arrTerminal（qunar/ctrip/tuniu）、历史平均延误 avgDelay（tuniu，分钟）
        try:
            avg_delay = int(f.get("avgDelay"))
        except (TypeError, ValueError):
            avg_delay = None

        out.append({
            "price": price, "transfer": transfer, "name": f.get("name", ""), "th": thv,
            "code": f.get("code", ""),
            # 国际行（r325）：intl 徽标 + 税费拆分（price 已含税，
            # tax 只是构成透传——「含税￥N」词面前端拼）
            "intl": 1 if f.get("intl") else 0,
            "tax": _num_or_none(f.get("tax")),
            "cabinT": _ct(f), "cabin": _cab_real,
            "layoverT": f.get("layoverT", ""),
            "prate": prate_txt(f.get("prate")),
            "meal": str(f.get("meal") or "").strip(),
            # 托运额词面（「免费托运20KG」/「无免费托运」）：ctrip pid
            # 数字额与 qunar/tongcheng 既有 baggage 同键透传——全渠道
            # 行李词面在 WebUI 一并对等
            "baggage": (f.get("baggage") or "").strip(),
            # 手提额词面（「手提7KG·1件」，ctrip pid 孪生家族同门）
            "carryon": (f.get("carryon") or "").strip(),
            "shareCarrier": (f.get("shareCarrier") or "").strip(),
            # 共享承运航司名（qunar mainCarrierShortName，与 shareCarrier
            # 同门）：前端渲染门「共享·名+号」组合消费，CSV「实际承运」列
            "shareAirline": (f.get("shareAirline") or "").strip(),
            # 航司二字码（qunar shortCarrier/tuniu airlineIataCode 跨渠道
            # 统一出口，iata2 守卫在爬虫端）：CSV「航司码」列 + 搜索 hay
            "airlineCode": (f.get("airlineCode") or "").strip().upper(),
            # 航程公里（qunar distance，int 协议）：CSV「航程」列 +
            # 航班名格 title 注记（中转绕行程度参考）
            "distance": _int_or_none(f.get("distance")),
            # 舱位公布运价（tuniu bcTaxExclusiveFare，与所选价同
            # breakdown 配对）：CSV「公布运价」列（报销/里程累积口径）
            "stdFare": _num_or_none(f.get("stdFare")),
            "fewTicket": (f.get("fewTicket") or "").strip(),
            "crossDayN": _int_or_none(f.get("crossDayN")),
            "depTerminal": (f.get("depTerminal") or "").strip(),
            "arrTerminal": (f.get("arrTerminal") or "").strip(),
            # 渠道字段三批透传（tongcheng 转机服务/航司中转文案，ctrip·qunar
            # 权益标签；trendGo=[[MM-DD,价],…] 仅挂 qunar/tongcheng/fliggy 当轮最低
            # 价行，点数与窗口随渠道——原样透传不做整形，前端空值不占位）。
            # 核实：qunar PC
            # 新采 transferService 与 tongcheng/ctrip 既有同名键同语义（中转
            # 服务权益文本），行到这里自动并入既有渲染位（中转 tag title）
            # 与 CSV「中转服务」列，零新增键
            "trendGo": f.get("trendGo"),
            # 改期日历节假日标注（tongcheng pc[].holidayName·tag，与
            # trendGo 同点同源同挂当轮最低价行）：[[MM-DD,词],…] 原样
            # 透传，改期窗口柱图 title 消费（「哪天便宜为什么便宜」
            # 解释变量）；其他渠道无源不落键
            "trendHoliday": f.get("trendHoliday"),
            # 高档舱改期日历价（tongcheng pc[].hlp，trendGo 同槽兄弟键
            # r254 翻案采入）：[[MM-DD,价],…] 同协议同挂当轮最低价行，
            # 柱图 title「公务￥X」附注 + CSV「改期公务」列；其他渠道
            # 无源不落键
            "trendBiz": f.get("trendBiz"),
            # 渠道字段十二批透传：fliggy 周边城市特价（J_Nearby 模块，
            # 两代 dump 在场）——[[日期,目的码,目的名,价,折扣词,公里数,
            # 锚城市],…] 已过爬虫端 _parse_nearby 逐点守卫（日期形/
            # iata3/价带/折扣词形），挂当轮 fliggy 最低价行（trendGo
            # 同槽同律，无值不落键）。消费端=航班名格 title 注记 + CSV
            # 「周边特价」列（明细次行段容量红线 14 已满不加段元素，
            # title/CSV 零布局风险——seatTilt 先例）；推送侧零改动
            "nearby": f.get("nearby"),
            # 渠道字段十三批透传：fliggy 往返程推荐（J_RoundRecommend
            # 模块，三代 dump 在场）——[[去程日期,返程日期,价,去程码,
            # 返程码],…] 已过爬虫端 _parse_round 逐点守卫（日期形/
            # iata3/价带/返程不早于去程），挂当轮 fliggy 最低价行
            # （trendGo/nearby 同槽第三兄弟，无值不落键）。消费端=
            # 航班名格 title 注记 + CSV「往返推荐」列（_nb_txt 零布局
            # 风险先例）；推送侧零改动
            "trendRound": f.get("trendRound"),
            # 中转二段出发日期（qunar transGoDate，跨天中转「二段哪天
            # 起飞」决策辨识信息——lay2dep 只有 HH:MM）：明细「二段 X
            # 起飞」渲染位拼 MM-DD 前缀，空串不占位同批内纪律
            "transGoDate": (f.get("transGoDate") or "").strip(),
            "transferService": (f.get("transferService") or "").strip(),
            "airlineTransfer": (f.get("airlineTransfer") or "").strip(),
            "labels": (f.get("labels") or "").strip(),
            # 渠道字段九批透传：qunar PC labels 适用条件说明
            # （「享受退改保护…」形，解释决策标签何时生效）——渲染挂
            # labels 既有 title 通道（'｜' 分隔同现状惯例），CSV +1 列
            # 「标签说明」；空串不占位同批内纪律
            "labelNote": (f.get("labelNote") or "").strip(),
            # 渠道字段四批透传：中转航站楼（qunar transInfo/
            # ctrip mutilstn，「咸阳T3」形）/ctrip 最低价政策余票数
            # int 1-10（None=无值不占位）。 核实：fliggy 新产
            # transTerminal、tongcheng 新采 leftTickets 与既有键同键同
            # 协议，白名单与渲染门渠道无关（明细次行「换乘·X」/「余N张」
            # 词面照常出），行到这里自动生效零改动
            "transTerminal": (f.get("transTerminal") or "").strip(),
            "leftTickets": f.get("leftTickets"),
            "avgDelay": avg_delay,
            # 渠道字段六批透传：中转出发楼（qunar secondDep
            # Info「正定T2」形，与 transTerminal 配对成换乘路径）+ 机场
            # 名（tuniu/tongcheng/fliggy 中文名、ctrip/qunar PC 三字码）
            # + 机型体量（「大型机/中型机/小型机」五渠道同值域）
            # + 舱位代码
            # （tuniu 单舱位守卫后）
            "transDepTerminal": (f.get("transDepTerminal") or "").strip(),
            "depAirport": (f.get("depAirport") or "").strip(),
            "arrAirport": (f.get("arrAirport") or "").strip(),
            # 渠道字段十一批透传：机场 IATA 码（qunar H5 binfo
            # depAirportId 系/tuniu dPortIataCode/ctrip 原码三源，iata3
            # 守卫）——恒 3 大写字母 strip+upper 直通不做 int 转写，空串
            # 不占位同邻键；消费端 _ttc 机场中文旁注 + CSV「机场/航站楼」
            # 列并入（不加新列）+ 搜索 hay
            "depAirportCode": (f.get("depAirportCode") or "").strip().upper(),
            "arrAirportCode": (f.get("arrAirportCode") or "").strip().upper(),
            "planeSize": (f.get("planeSize") or "").strip(),
            # 二段机型/体量（r339a 三端同轮：ctrip 中转二段 craftinfo，
            # 仅中转行有值；消费面=明细次行 planeSize span 并列 +
            # CSV 机型列并入，零新列零布局风险）
            "plane2": (f.get("plane2") or "").strip(),
            "planeSize2": (f.get("planeSize2") or "").strip(),
            # 机型细名（r329 三端同轮收口：tuniu craftTypeDetail 段级
            # 首个非空段；此前爬虫落键、下行不透传、前端零消费=数据
            # 孤儿——CSV「机型体量」列同列并入 + 次行 title 注记 +
            # 搜索 hay 三消费面，v1559 同列并入先例零布局风险）
            "plane": (f.get("plane") or "").strip(),
            "cabinCode": (f.get("cabinCode") or "").strip(),
            # 座椅倾斜角度（ctrip classinfor.seattilt，100~180°，
            # 0=未报爬虫端不落）：int 协议转写（七批先例）；渲染门=
            # cabinCode 悬停 title 注记 + CSV 列（明细次行段容量
            # 红线 14 已满不加段元素，title/CSV 零布局风险）
            "seatTilt": _int_or_none(f.get("seatTilt")),
            # 途牛儿童/婴儿价（渠道调研移交：爬虫已采、消费端补齐）：
            # float 协议（半价 X.5 不截断），渲染=航班名格 title 注记
            # + CSV「儿童/婴儿」列（次行段红线 14 已满不加段元素，
            # title/CSV 零布局风险——seatTilt 先例）
            "childPrice": _num_or_none(f.get("childPrice")),
            "infantPrice": _num_or_none(f.get("infantPrice")),
            # 渠道字段七批透传：廊桥率/取消率/公务舱价（int
            # 协议）、机龄 planeAge（str）、廉航旗标 lcc（normalize 派生
            # bool）—— ：爬虫缺省产出是空串非缺键（tongcheng
            # sts/ctrip extendinfos 未命中行），空串过 JS !=null 会渲染
            # 「·取消%」脏词面——复用 avgDelay 的 int→None 转写（
            # 先例），非数字一律 None 前端不占位
            "bridgeRate": _int_or_none(f.get("bridgeRate")),
            "cancelRate": _int_or_none(f.get("cancelRate")),
            "bizPrice": _int_or_none(f.get("bizPrice")),
            # 高档舱舱别词面（公务/头等，随 bizPrice 同源落键）——
            # CSV/title 词面随源，缺省由前端回退「公务」兼容存量行
            "bizCabin": f.get("bizCabin") or None,
            # 渠道字段八批透传：fliggy 中转行机建燃油合计
            # （int 协议 None 不占位，同上三键转写）——飞猪列表价裸价
            # 口径的补税提示，渲染位明细次行；只采+展示不接达标口径
            # （FLIGGY_TAX_PAD 归零定标，无配对样本证据不动比价）
            "transferTax": _int_or_none(f.get("transferTax")),
            "planeAge": f.get("planeAge") or None,
            "lcc": bool(f.get("lcc")),
            # tuniu 黑卡价透明标记（渠道调研 B）：选中价来自黑卡政策时
            # 爬虫落 blackCard=True，此处透传渲染门标「黑卡价」；不改
            # 选价口径（报文零文字性会员门标注，口径取证留 WATCH）
            "blackCard": bool(f.get("blackCard")),
            # qunar 退改费结构化双键（价位级决策字段）：int 协议
            # （_int_or_none 转写，-1「不可办理」如实保留非数字缺失
            # 归 None）；渲染=价格格徽标 + CSV「退改」列，词面单源
            # _rc_txt。推送 PNG 次行 rc 槽已透传（r304：影子渲染实测
            # 拆行增量 0.8%，report._rc_word 与本函数词面逐字同——
            # 改词面两处同轮；退改从未进推送文本，「图≥文本」律不涉）
            "returnFee": _int_or_none(f.get("returnFee")),
            "changeFee": _int_or_none(f.get("changeFee")),
            # ctrip 年龄限制专享价：最低价政策带 nt=20
            # 资格限制词面「限青年/限老年/限年龄/限学生/限携程会员/
            # 限航司会员」（并存「·」拼接）——该价非资格旅客误购无法
            # 出行，价格格 ⚠ 徽标（⚠+warn 与孤低价警告同语义族）
            "agePolicy": (f.get("agePolicy") or "").strip(),
            # ctrip 高风险政策透明标记：nt=104 报价条目与最低价同价
            # 条目 limitTag=HighRiskPolicy（价门精确到分+仅直飞）——
            # 渠道级购买风险提示，价格格 ⚠ 徽标（与 agePolicy 同
            # warn 语义族；词面不加「价」尾：它是政策风险标记不是
            # 资格价语义）
            "riskPolicy": (f.get("riskPolicy") or "").strip(),
            # qunar 值机时效风险警示（listPopView 弹层，双词面守卫在
            # 爬虫端）：「临近起飞需确认值机」固定词面，价格格 ⚠ 徽标
            # （agePolicy/riskPolicy 同 warn 语义族）——载体行 fewTicket/
            # labels/refundChange 全空时的行级唯一购买风险出口
            "ticketRisk": (f.get("ticketRisk") or "").strip(),
            # ctrip 诱饵价透明标记（nt=105 展示价 ∈ nt=104 渠道过滤
            # 清单=页面展示价不可购，点进必涨价；爬虫端已守卫 FP 互证
            # +背离 ≤5% 双门）——价格格 ⚠ 徽标（agePolicy/riskPolicy
            # 同 warn 语义族），防用户以渠道列表展示价比价后预期落空
            "lurePrice": _int_or_none(f.get("lurePrice")),
            "bagState": (f.get("transferBaggage") or "").strip(),
            # qunar PC 特惠产品权益（「航变免费改、20Kg免费行李」，稀疏；
            # 门不下发即孤儿键，PC 复活当日会静默丢失）
            "ptripNote": (f.get("ptripNote") or "").strip(),
            # 未知衔接下发 null（r51：曾压 0 参与衔接区间断言，
            # 设下限后无段时刻的国际中转整渠道静默消失）
            "layoverM": (f.get("layoverM") or None),
            "layMin": int(rr.get("transfer_layover_min", 0) or 0),
            "lay2dep": (f.get("lay2dep") or ""),
            # 载荷卫生：飞行行 tam 曾为 56 键白名单
            # 唯一无消费键（前端 f.tam 零读取、CSV 无此列；「次日 HH:MM
            # 前到达」的 tam 消费全在 KPI best brief 的同名字段，见
            # _best_brief）——行级删键，brief 载体保留
            "bag": f.get("transferBaggage") == "direct",
            "stop": bool(f.get("stopover")),
            "stopCity": (f.get("stopCity") or "").strip(),
            "stopTimeT": (f.get("stopTimeT") or "").strip(),
            # 经停窗口绝对时刻（tuniu stopPoints 段时刻，词面直传）
            "stopWin": (f.get("stopWin") or "").strip(),
            "depTime": f.get("depTime", ""), "arrTime": f.get("arrTime", ""),
            "date": f.get("depDate", ""),
            # 检索页生产溯源：城市对 + 原始 DB 行/下标 + 采集时刻
            "from": (f.get("_pair") or ("", ""))[0],
            "to": (f.get("_pair") or ("", ""))[1],
            "fetchedAt": f.get("_fetched_at") or "",
            "rowId": _int_or_none(f.get("_row_id")),
            "rawIdx": _int_or_none(f.get("_raw_idx")),
            "prov": _prov_obj(f.get("_prov")),
            "trans": f.get("transCity", ""), "cross": f.get("crossDayDesc", ""),
            # 日历薄行标记（无航班号无时刻=日历价，非具体航班）。
            # isCal 与 cal 同值但语义化，供检索台列表/矩阵/导出统一消费。
            "cal": is_cal,
            "isCal": not (f.get("depTime") and f.get("arrTime")),
            "route": rt_label,
            "dur": f.get("totalDuration") or "",
            "durM": _dur_min(f.get("totalDuration")),
            "plat": Alerter.plat_cn(f.get("_platform", "")),
            "platKey": f.get("_platform", ""),
            # 补位行 age 可能 <0.5h：保留一位小数并设 0.1 地板，
            # 不再四舍五入成 0 冒充本轮；isStale 是显式布尔门。
            "stale": (max(0.1, round(float(f["_stale_h"]), 1))
                      if f.get("_stale_h") else 0),
            "isStale": bool(f.get("_stale_h")),
            "xphan": bool(f.get("_xphan")),
            "qual": qual, "near": near, "brk": brk, "view": view,
        })
    # 检索台稳定行身份 / 同班键：价格/时刻变化不再改选中，日历行不参与
    # 同班比价（旧前端把 code||name 当键，两条“日历最低价”被误判 2 源）。
    for _o in out:
        _o["rowKey"] = _srx_row_key(_o)
        _o["flightKey"] = _srx_flight_key(_o)
        _o["rawKey"] = _srx_raw_key(_o)
    # 同班比价离群旗标下发：与钉钉/总表图同一 Alerter._outlier
    # 口径（最高>2×最低 或 组内舱位大类>1）。前端本地曾只判 2×——跨舱位
    # ≤2× 时 webui 显示「可省」而推送显示「差」，同屏两语言。组级属性
    # 挂组内每行（指纹与前端 fp 同构：日期/时刻/中转/跨天/经停）
    _og = {}
    for _o in out:
        _k = (_o["date"], _o["depTime"], _o["arrTime"], _o["trans"],
              _o["cross"], _o["stop"])
        _byp = _og.setdefault(_k, {})
        _cur = _byp.get(_o["plat"])
        if _cur is None or _o["price"] < _cur["price"]:
            _byp[_o["plat"]] = _o
    for _byp in _og.values():
        if len(_byp) > 1:
            _ol = Alerter._outlier(
                sorted(_byp.values(), key=lambda x: x["price"]))
            for _o in _byp.values():
                _o["outlier"] = _ol
    def _real_offer(f):
        # r386：真实班次判据=有起降时刻（与 _is_calendar_row 同律）。
        # 曾额外要求航班号——飞猪国际中转卡片渠道只给航司名不给航班号，
        # 会被当成"非真实班次"整类剔出直飞/中转最优池（页面看着没中转）。
        return bool(str(f.get("depTime") or "").strip()
                    and str(f.get("arrTime") or "").strip())
    directs = [f for f in flights
               if not f.get("transCity") and not f.get("_xphan")
               and _real_offer(f)]
    # 中转到达约束按各自航线（原实现拿 routes[0] 的 am 一刀切——多航线混串）
    def _am_of(f):
        rr = _rr_of(f)
        return rr.get("transfer_arrival_max", "02:00") or "02:00"

    # 行情口径（与走势曲线 _rounds 一致）：到达约束 + 衔接下限（行李不参与）
    def _lay_ok(f):
        rr = _rr_of(f)
        lm = int(rr.get("transfer_layover_min", 0) or 0)
        m = f.get("layoverM")
        return lm <= 0 or (isinstance(m, int) and m >= lm)

    oks = [f for f in flights if f.get("transCity") and not f.get("_xphan")
           and _real_offer(f)
           and Alerter._arrival_ok(f, _am_of(f)) and _lay_ok(f)]

    def _best_brief(f, pool=None):
        if not f:
            return None
        rr = _rr_of(f) or {}
        label = (f"{rr.get('from_name', '')}→{rr.get('to_name', '')}"
                 if rr and len(routes) > 1 else "")
        dshort = (f.get("depDate") or "")[5:].replace("-", "/")
        if label and len(dshort) == 5:
            label += f" {dshort}"
        # 阈值随航班所属航线：全局最低价配 routes[0] 的线 = 跨航线虚报达标
        th_v = float(rr.get("alert_transfer" if f.get("transCity")
                            else "alert_direct", 0) or 0)
        # 同价多渠道跳转优先去哪儿/携程（与推送链接同规则）；view_plat
        # 与链接同源下发（tooltip「去X查看」与落点一致，副行仍显原渠道）
        # R28（RT 深链复议）：日历行渠道自带 RT 感知深链优先（同上律）
        view_plat = Alerter._pref_platform(f, pool or [f])
        # KPI/best 的「在X查看」必须与落点同源：旧实现取行自身渠道 URL，
        # 而同价优选 view_plat 可能是另一渠道，文案点名携程却打开飞猪。
        _pref_view = _view_url(rr, f.get("depDate", ""), view_plat)
        view = _pref_view or ""
        if view and not view.lower().startswith(("http://", "https://")):
            view = ""
        return {"price": f["price"], "name": f.get("name", ""),
                "depTime": f.get("depTime", ""), "arrTime": f.get("arrTime", ""),
                "trans": f.get("transCity", ""),
                "cross": f.get("crossDayDesc", ""),
                "bag": f.get("transferBaggage") == "direct",
                "bagState": (f.get("transferBaggage") or "").strip(),
                "stop": bool(f.get("stopover")),
                "stopCity": (f.get("stopCity") or "").strip(),
                "stopTimeT": (f.get("stopTimeT") or "").strip(),
                "stopWin": (f.get("stopWin") or "").strip(),
                "plat": f.get("_platform", ""),
                "view_plat": view_plat,
                # 国际档随 brief 下发（r326 A2：飞猪国际行价恒含税总价
                # 口径，「税前」角标须分档豁免——同屏「含税￥N」互斥）
                "intl": bool(f.get("intl")),
                # 真实达标语义（与明细 qual 同源）：行情最低班未必能出手
                # （非直挂/衔接不足时 qual=False，KPI 卡不亮绿）
                "qual": _qual_of(f, bool(f.get("transCity")),
                                 round(float(f["price"]))),
                "stale": round(f["_stale_h"], 1) if f.get("_stale_h") else 0,
                "route": label, "view": view, "th": th_v,
                "tam": (rr.get("transfer_arrival_max", "02:00") or "02:00"),
                # 所属日期（delta 按日期精确匹配 routes_arr 用——单航线
                # 多日期时 route 为空串，label 匹配会错配首日期序列）
                "date": (f.get("depDate") or "")}

    # 多日期航线概览按日期分看（用户原话「我想看 10-5 和 10-6 的」）：
    # 全池 min 只会露出一个日期的行情，另一日期不可见
    _dates_all = sorted({d for _r in routes for d in (_r.get("dates") or [])})
    def _best_by_date(pool):
        out = {}
        for d in _dates_all:
            c = [f for f in pool if (f.get("depDate") or "") == d]
            if c:
                best = min(c, key=lambda f: f["price"])
                out[d] = _best_brief(best, pool=c)
        return out

    hist = _rounds(db, route.get("from", ""), route.get("to", ""),
                   (route.get("dates") or [""])[0], am,
                   layover_min=int(route.get("transfer_layover_min", 0) or 0),
                   dep_win=_dep_win_of(route),
                   th_d=th_d, th_t=th_t, rc=route)

    def _pts(hist, key, th):
        """走势点 [时刻, 价, 档]：档=2 真达标（旗标，与明细🔥/推送🎯同口径）、
        1 行情破线但未达标、0 其余。组装不得丢弃 _rounds 的达标旗标，
        否则前端退化成「裸价≤线」画达标环——飞猪税前价/非直挂中转在图上虚画
        达标，与列表含义不一致（曲线口径收口）。"""
        out = []
        for row in hist:
            v = row[key]
            if not v:
                continue
            q = row[key + 2] if len(row) >= key + 3 else None
            flag = 2 if q else (1 if (th and v <= th) else 0)
            out.append([row[0].strftime("%m-%d %H:%M"), v, flag])
        return out

    h_d = _pts(hist, 1, th_d)
    h_t = _pts(hist, 2, th_t)
    # 多航线走势：每 (航线,日期) 一条序列，前端图上切着看（必须画全部，不许只画第一条）
    routes_arr, seen_rd = [], set()
    for r in routes:
        am_r = r.get("transfer_arrival_max", "02:00") or "02:00"
        for d0 in r.get("dates") or [""]:
            if (r["from"], r["to"], d0) in seen_rd:
                continue
            seen_rd.add((r["from"], r["to"], d0))
            try:
                hist_r = _rounds(db, r["from"], r["to"], d0, am_r,
                                 layover_min=int(r.get("transfer_layover_min", 0) or 0),
                                 dep_win=_dep_win_of(r),
                                 th_d=float(r.get("alert_direct", 0) or 0),
                                 th_t=float(r.get("alert_transfer", 0) or 0),
                                 rc=r)
            except Exception:
                hist_r = []
            rd = _pts(hist_r, 1, float(r.get("alert_direct", 0) or 0))
            rt_ = _pts(hist_r, 2, float(r.get("alert_transfer", 0) or 0))
            # 7 天序列（范围切换）+ 14 天价格日历（热力卡）
            try:
                hist7 = _rounds(db, r["from"], r["to"], d0, am_r, hours=168,
                                layover_min=int(r.get("transfer_layover_min", 0) or 0),
                                dep_win=_dep_win_of(r),
                                th_d=float(r.get("alert_direct", 0) or 0),
                                th_t=float(r.get("alert_transfer", 0) or 0),
                                rc=r)
            except Exception:
                hist7 = []
            r7d = _pts(hist7, 1, float(r.get("alert_direct", 0) or 0))
            r7t = _pts(hist7, 2, float(r.get("alert_transfer", 0) or 0))
            try:
                cal = _daily_minima(db, r["from"], r["to"], d0, am_r, days=14,
                                    layover_min=int(r.get("transfer_layover_min", 0) or 0),
                                    dep_win=_dep_win_of(r),
                                    th_d=float(r.get("alert_direct", 0) or 0))
            except Exception:
                cal = []
            short = d0[5:].replace("-", "/") if len(d0) >= 10 else ""
            routes_arr.append({
                "label": f"{r['from_name']}→{r['to_name']}"
                         + (f" {short}" if short else ""),
                "from": r["from"], "to": r["to"],
                "date": d0,
                "th": {"direct": float(r.get("alert_direct", 0) or 0),
                       "transfer": float(r.get("alert_transfer", 0) or 0)},
                "history": {"direct": rd, "transfer": rt_},
                "history7": {"direct": r7d, "transfer": r7t},
                "cal": cal,
            })
    # 渠道数据新鲜度（每平台最新一条距今年小时；无=该渠道无任何数据）
    plat_age = {}
    try:
        conn = sqlite3.connect(db)
        for p, ts in conn.execute(
                "SELECT platform, MAX(fetched_at) FROM flight_prices "
                "GROUP BY platform"):
            try:
                t = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                plat_age[Alerter.plat_cn(p)] = round(
                    (datetime.now() - t).total_seconds() / 3600, 1)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    bd_brief = _best_brief(min(directs, key=lambda f: f["price"])
                           if directs else None, pool=directs)
    xt_brief = _best_brief(min(oks, key=lambda f: f["price"])
                           if oks else None, pool=oks)
    bbd_d = _best_by_date(directs)
    bbd_t = _best_by_date(oks)

    def _delta_vs_prev(brief, key, date=None):
        """较上轮涨跌：取最优航班所属航线的走势序列，倒数两点之差。
        序列末点即当前轮，倒数第二点为上轮（与推送的「较上轮」同源语义）。
        date 给定时按日期精确匹配 routes_arr 条目（多日期分组 KPI 用；
        label 匹配在单航线多日期时 route 为空串会错配到首日期序列）。"""
        if not brief:
            return None
        ser = None
        if date is not None:
            ser = next((r["history"][key] for r in routes_arr
                        if r.get("date") == date), None)
        if ser is None and brief.get("route"):
            ser = next((r["history"][key] for r in routes_arr
                        if r["label"] == brief["route"]), None)
        if ser is None and routes_arr:
            ser = routes_arr[0]["history"][key]
        if ser and len(ser) >= 2:
            try:
                return round(float(ser[-1][1]) - float(ser[-2][1]))
            except Exception:
                pass
        return None

    # 多程行程：与单 O-D 分开供货（routesArr 是逐日单程走势，多程行
    # 来自 itinerary_daily 的整单总价）。latest 为 None 时前端按
    # supported/expired 说出「为什么还没数」，不拿空值画价格。
    mc_routes = []
    _today0 = datetime.now().strftime("%Y-%m-%d")
    _plats0 = set((u.get("platforms") if isinstance(u, dict)
                   else getattr(u, "platforms", None))
                  or _State.cfg.get("platforms") or ())
    from core.multicity import segments_key as _segments_key
    for _mr in mc_raw:
        _segs0 = _mc_segments_of(_mr)
        try:
            _key0 = _segments_key(_segs0)
        except Exception:
            continue
        if isinstance(_mr, dict):
            _fn0 = _mr.get("from_name") or _segs0[0]["from"]
            _tn0 = _mr.get("to_name") or _segs0[-1]["to"]
            _thr0 = float(_mr.get("alert_threshold", 0) or 0)
        else:
            _fn0 = getattr(_mr, "from_name", "") or _segs0[0]["from"]
            _tn0 = getattr(_mr, "to_name", "") or _segs0[-1]["to"]
            _thr0 = float(getattr(_mr, "alert_threshold", 0) or 0)
        _latest0 = None
        try:
            _mp0 = _multicity_payload(segments_key=_key0, limit=1,
                                      demo=bool(DEMO["on"]), db_path=db)
            if _mp0.get("items"):
                _row0 = _mp0["items"][0]
                _latest0 = {
                    "price": float(_row0.get("total_price") or 0),
                    "platform": str(_row0.get("platform") or ""),
                    "fetched_at": str(_row0.get("fetched_at") or ""),
                    "depart_date": str(_row0.get("depart_date") or ""),
                    "legs": ((_row0.get("extra") or {}).get("legs") or []),
                    "prov": ((_row0.get("extra") or {}).get("prov") or {}),
                }
        except Exception:
            _latest0 = None
        mc_routes.append({
            "key": _key0,
            "label": _mc_chain_label(_segs0),
            "from": _segs0[0]["from"], "to": _segs0[-1]["to"],
            "from_name": _fn0, "to_name": _tn0,
            "segments": _segs0,
            "dates": [s["date"] for s in _segs0],
            "threshold": _thr0,
            "supported": "ctrip" in _plats0,
            "expired": _segs0[0]["date"] < _today0,
            "latest": _latest0,
            "history": _multicity_history(db, _key0),
        })

    _routes_txt_all = _routes_txt(routes)
    if mc_routes:
        _routes_txt_all = "、".join(
            ([_routes_txt_all] if _routes_txt_all else [])
            + ["多程 " + m["label"] for m in mc_routes])
    return {
        "name": u.get("name", ""),
        "routesTxt": _routes_txt_all,
        "mcRoutes": mc_routes,
        "th": {"direct": th_d, "transfer": th_t},
        "best": {
            "direct": bd_brief,
            "transfer": xt_brief,
        },
        "best_by_date": {
            "dates": _dates_all,
            "direct": bbd_d,
            "transfer": bbd_t,
        },
        # 过期监控日期（全部 dates < today）：sweep 已跳过期查询（渠道
        # 对过期查询滚动返回其他日期航班，照常落库=把别的日期的价挂进
        # 过期桶）——概览对过期日期渲染「已过期·停采」徽标，让「为何
        # 没数据」可自解释
        "expiredDates": [d for d in _dates_all
                         if d and d < datetime.now().strftime("%Y-%m-%d")],
        # 多日期分组 KPI 的「较上轮」按日期拆分：
        # dgroup 分支 delta 恒 null 曾让多日期航线概览无任何涨跌信息）；
        # 按日期精确匹配 routes_arr 条目，与单日期 delta 同源同语义
        "delta_by_date": {
            "direct": {d: _delta_vs_prev(b, "direct", d)
                       for d, b in bbd_d.items()},
            "transfer": {d: _delta_vs_prev(b, "transfer", d)
                         for d, b in bbd_t.items()},
        },
        "delta": {"direct": _delta_vs_prev(bd_brief, "direct",
                                           (bd_brief or {}).get("date")),
                  "transfer": _delta_vs_prev(xt_brief, "transfer",
                                             (xt_brief or {}).get("date"))},
        "minsTxt": " ｜ ".join(f"{Alerter.plat_cn(k)} ￥{v:.0f}"
                              for k, v in sorted(plat_min.items(), key=lambda kv: kv[1])),
        "minsArr": [[Alerter.plat_cn(k), round(v)]
                    for k, v in sorted(plat_min.items(), key=lambda kv: kv[1])],
        "flights": sorted(out, key=lambda x: x["price"]),
        "history": {"direct": h_d, "transfer": h_t},
        "routesArr": routes_arr,
        "platAge": plat_age,
        # 本用户勾选的采集渠道（r805）。此前这份载荷里根本没这个键，
        # 配置页的 `(u.platforms||[])` 恒为空 → **7 个 chip 里只有前端
        # 自己兜底的那几家亮着，两个 App 永远显示未勾选**，用户勾了
        # 也看不出变化（保存其实生效，只是回显丢了）。
        # `u` 是 dict 不是对象：用 getattr 会恒取 None（r805 实测拿到 []）。
        "platforms": list((u.get("platforms")
                           if isinstance(u, dict) else
                           getattr(u, "platforms", None))
                          or _State.cfg.get("platforms") or ()),
        # 达标判定以"每行各自航线阈值"为准（与推送语义一致），
        # 不再拿全局最低价配 routes[0] 的线（跨航线虚报）。
        # 补位 stale 行不参与（与推送链「达标只认当轮实时数据」同口径，
        # alerter fresh_d/fresh_t 同式）——否则渠道限流时控制台 pill 🚨
        # 而钉钉不推，同问题两条链路结论相反
        "hit": any(f["qual"] and not f["stale"] and not f.get("isCal")
                   for f in out),
        "roundUpdated": max([f.get("fetchedAt") or "" for f in out
                             if not f.get("isStale")] or [""]),
    }


_STATE_CACHE = {"sig": None, "payload": None, "body": None,
                "etag": None, "gz": None}
_STATE_LOCK = threading.RLock()   # 可重入——同锁快照读取嵌套调 _latest_state
_STATE_BUILDING = {"on": False}

# ---- /api/state SWR 快照的磁盘副本 ----
# 冷启动首建分支是**同步**等待（见 _latest_state）：真机全量重算即便
# 从 222s 收到 ~26s，服务刚起时首个控制台请求仍要干等。把上一轮已
# 发布的快照落盘、首个请求时恢复，用户首屏立即拿到上次数据，后台再
# 按现行签名重建换新——stale-while-revalidate 的磁盘版，语义与内存
# 态一字不差（sig 对不上就自然落到既有 SWR 路径）。
_STATE_DISK_ONCE = {"on": False}      # 恢复只在首个请求做一次
_STATE_CACHE_TTL = 48 * 3600          # 超过则丢弃（不展示数天前价格）
_STATE_CACHE_MAGIC = b"TKMSTATE1\n"
# /api/state payload schema: bump whenever serialized fields change in a way
# that must not be served from an older disk snapshot (r340 adds provenance).
_STATE_SCHEMA = "probe-r365-1"


def _state_cache_path():
    """快照文件路径（与库同目录、随库隔离）。不可解析返回 None。

    与 DB 同名加后缀：demo 模式的临时库天然落到系统临时目录，不污染
    仓库（跨次复用由版本/签名双守卫兜住，陈旧快照不会误展示）。

    demo 态恒 None（读写同断一处收口）：demo 的 _State.version 恒
    "demo"，跨版本守卫（meta.ver != 当前版）在 demo 永真；demo 临时
    库路径/内容恒定 → sig 恒匹配。双守卫同时失效，旧代码时代的快照
    会永久顶替当前结构（r321 实证：临时目录快照 body 缺 r320 新增
    city 键，demo/审计/烘焙的 /api/state 全部被冻结在旧结构）。demo
    响应构建毫秒级，快照零收益。"""
    if str(_State.version or "") == "demo":
        return None
    try:
        db = _anchored(((_State.cfg or {}).get("output") or {}).get("db_path"),
                       "data/prices.db")
        d = os.path.dirname(os.path.abspath(db))
        return os.path.join(d, os.path.basename(db) + ".statecache")
    except Exception:
        return None


def _state_persist(sig, body, etag, gz):
    """发布快照后落盘（best-effort，任何异常静默）。

    单文件布局 `MAGIC + 4B(meta 长度) + meta + gz`，一次 os.replace
    原子换入。拆成 meta/body 两份文件会在中途崩溃时撕裂——body 已
    换新而 meta 仍旧，恢复出 body/etag 不配对的响应（轮询按新 etag
    落陈旧缓存被 304 粘死）。"""
    base = _state_cache_path()
    if not base or gz is None:
        return
    try:
        meta = json.dumps(
            {"sig": (list(sig) if sig is not None else None),
             "schema": _STATE_SCHEMA,
             "etag": etag or "", "ts": time.time(),
             # payload 结构随程序版本演进：跨版本快照一律不认（升版后
             # 首次请求慢一次，之后照旧毫秒级）——比前端拿旧结构渲染
             # 出空列安全
             "ver": str(_State.version or "")},
            ensure_ascii=False).encode("utf-8")
        tmp = base + ".tmp"
        with open(tmp, "wb") as f:
            f.write(_STATE_CACHE_MAGIC)
            f.write(len(meta).to_bytes(4, "big"))
            f.write(meta)
            f.write(gz)
        os.replace(tmp, base)
    except Exception:
        pass


def _state_restore():
    """从磁盘恢复上一轮快照（best-effort，坏文件一律静默丢弃）。

    恢复出的 sig 是**上一轮**的签名——与当前库不符时 _latest_state
    自然走既有的 SWR 路径（回旧值 + 后台重建），不需要任何新分支。"""
    base = _state_cache_path()
    if not base:
        return
    try:
        with open(base, "rb") as f:
            if f.read(len(_STATE_CACHE_MAGIC)) != _STATE_CACHE_MAGIC:
                return
            n = int.from_bytes(f.read(4), "big")
            meta = json.loads(f.read(n).decode("utf-8"))
            gz = f.read()
        if not gz:
            return
        if time.time() - float(meta.get("ts") or 0) > _STATE_CACHE_TTL:
            return
        if str(meta.get("ver") or "") != str(_State.version or ""):
            return          # 跨版本快照结构可能已变，不认
        if str(meta.get("schema") or "") != _STATE_SCHEMA:
            return          # payload schema 变更后旧快照不可回放
        body = gzip.decompress(gz)
        payload = json.loads(body.decode("utf-8"))
        sig = meta.get("sig")
        with _STATE_LOCK:
            if _STATE_CACHE["payload"] is not None:
                return          # 本进程已构建，活缓存优先
            _STATE_CACHE["payload"] = payload
            _STATE_CACHE["body"] = body
            _STATE_CACHE["etag"] = meta.get("etag") or ""
            _STATE_CACHE["gz"] = gz
            _STATE_CACHE["sig"] = tuple(sig) if sig else None
    except Exception:
        pass


def _state_restore_once():
    """首个 /api/state 请求前尝试恢复一次（热路径零重复 IO）。"""
    if _STATE_DISK_ONCE["on"]:
        return
    _STATE_DISK_ONCE["on"] = True
    _state_restore()


def _state_signature():
    """当前 /api/state 缓存签名；DB 不可读时返回 None（禁用缓存路径）。"""
    st = _State
    # cfg 未加载时是 None（例如直接挂 _Handler 起服务、配置还没读盘）——
    # 曾在这里 `st.cfg.get(...)` 直接抛 AttributeError，导致首屏
    # /api/state 整个 500，界面拿不到任何状态（实测两个 500）。
    cfg = st.cfg if isinstance(st.cfg, dict) else {}
    db = _anchored((cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    try:
        sst = os.stat(db)
        users = st.users or []
        return (db, sst.st_mtime_ns, sst.st_size,
                hash(json.dumps(users, default=str, ensure_ascii=False)),
                st.version)
    except OSError:
        return None


def _build_state(sig):
    """全量重建并写入缓存（payload/body/etag/gz 同批落位，永不出现半新半旧）。

    ：重活（全历史 extra JSON 逐条解析——现库体量实测 ~145s，
     时代的「11~14s」注释已过时）移到锁外做——异步重建线程若
    持锁构建，SWR 回旧值的请求会整体钉死在锁上（每轮扫描后控制台
    /api/state 假死 ~2.4 分钟的根因）；发布段收成同锁一次赋值，body/
    etag/gz 原子成对（撕裂修复语义不变）。并发双构建无害：
    单飞旗标已挡重入，即便穿透也是先完成者先发布、后完成者整体覆盖。"""
    st = _State
    # 同一容错：cfg 未加载时按空配置出「无用户/无航线」的空状态，
    # 而不是让整个 /api/state 500（首屏看不到任何东西）。
    # 只在这两个函数里用局部别名：不能回写 st.cfg，否则配置随后加载
    # 时会被这份空字典盖掉。
    _cfg = st.cfg if isinstance(st.cfg, dict) else {}
    users = st.users or [{"name": "default", "routes": _cfg.get("routes") or []}]
    states = [_user_state(u) for u in users if u.get("routes")]
    # 更新时间取 DB 最新一条
    import sqlite3 as sq
    db = _anchored((_cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    updated = ""
    try:
        conn = sq.connect(db)
        row = conn.execute(
            "SELECT MAX(fetched_at) FROM flight_prices").fetchone()
        conn.close()
        updated = row[0] if row and row[0] else ""
    except Exception:
        pass
    out = {"updated": updated, "users": states,
           "suspended": _suspended_users(users, _cfg.get("users") or []),
           "next_run": _next_run(), "version": st.version,
           "build": _build_stamp(),
           # r1739：静默窗内 `next_run` 指的那一轮会被跳过，页头只说
           # 「下轮 05:04」就是假承诺。把窗口一并下发，界面照它改口。
           "quiet": _quiet_view(),
           "demo": bool(DEMO["on"]),
           # 页脚「本地服务」实际监听地址（热切换/自定义 host 下页脚
           # 口径随实况；服务未起时留空）
           "svc": (("%s:%d" % _State.srv.server_address)
                   if getattr(_State, "srv", None) else "")}
    body = (json.dumps(out, ensure_ascii=False).encode("utf-8")
            if sig is not None else None)
    # ETag 随响应体一并缓存：轮询 304 路径零 hash 开销
    etag = ('"%s"' % hashlib.md5(body).hexdigest() if body else None)
    gz = (gzip.compress(body, 6) if body else None)
    with _STATE_LOCK:
        _STATE_CACHE["payload"] = out
        _STATE_CACHE["body"] = body
        _STATE_CACHE["etag"] = etag
        _STATE_CACHE["gz"] = gz
        _STATE_CACHE["sig"] = sig
    # 发布即落盘：下次进程重启时首个控制台请求能立刻命中（见
    # _state_persist/_state_restore）。异步重建路径在此锁外；同步
    # 兜底路径（_latest_state 直调）随外层 RLock 可重入无死锁
    _state_persist(sig, body, etag, gz)


def _state_rebuild_async():
    """后台单飞重建：构建中再多的请求/轮询也只触发一次重建。"""
    if _STATE_BUILDING["on"]:
        return
    _STATE_BUILDING["on"] = True

    def _run():
        try:
            # 构建移出锁外（见 _build_state docstring）——持锁
            # 构建曾把 SWR 回旧值的取锁路径一并钉死
            sig = _state_signature()
            if sig is not None and _STATE_CACHE["sig"] == sig:
                return  # 别的线程已建好
            _build_state(sig)
        except Exception as e:
            try:
                (_State.logger or print)("[控制台] 状态重建异常: %s" % e)
            except Exception:
                pass
        finally:
            _STATE_BUILDING["on"] = False

    threading.Thread(target=_run, daemon=True, name="state-rebuild").start()


def prewarm_state():
    """缓存预热：启动后/每轮扫描落库后后台调一次，用户打开控制台永远
    命中热缓存（全历史重算 11~14s 不再落在用户请求里）。"""
    _state_rebuild_async()


def _latest_state():
    """全量状态；按 (DB 文件, mtime_ns, size, 用户配置摘要, 版本) 签名缓存。

    控制台每 10s 轮询本端点——轮间 DB 不变时不得全量重算
    （extra JSON 逐条解析 + 每航线×日期 走势/日历多查询）。配置摘要取
    users 的 JSON 哈希（Route 对象经 default=str 进 repr，阈值改动即换签），
    不用对象 id（CPython id 复用会让热重载后撞上旧签名返回脏缓存）。

    签名失效时分两路：有旧 payload → 立即回陈旧值 + 后台单飞重建
    （stale-while-revalidate，用户零等待，下一个轮询拿到新值）；进程后
    首建（无旧值可回）→ 触发同一单飞后台构建并轮询等待（构建
    在锁外做后，等锁改等旗标——持锁构建时代首请求会钉死全部并发请求）。"""
    _state_restore_once()   # 上一轮快照先顶上（先于签名比对：同签名连建都省）
    sig = _state_signature()
    if sig is not None and _STATE_CACHE["sig"] == sig:
        return _STATE_CACHE["payload"]
    if _STATE_CACHE["payload"] is not None:
        _state_rebuild_async()
        return _STATE_CACHE["payload"]
    # 冷启动首建：单飞后台构建 + 锁外轮询等待。等待绝不可发生在锁内：
    # 构建线程的发布段需要这把锁，持锁等待=互等死锁（CI uitest
    # 实锤：demo 首请求永挂）。此处已在无锁区（snap 端两段式，见下）
    _state_rebuild_async()
    deadline = time.time() + 300
    while _STATE_BUILDING["on"] and time.time() < deadline:
        time.sleep(0.2)
        if sig is not None and _STATE_CACHE["sig"] == sig:
            return _STATE_CACHE["payload"]
    with _STATE_LOCK:
        if sig is not None and _STATE_CACHE["sig"] == sig:
            return _STATE_CACHE["payload"]
        if _STATE_CACHE["payload"] is None:
            _build_state(sig)   # 后台线程异常兜底：缓存仍空则同步补建
        return _STATE_CACHE["payload"]


def _latest_state_snap():
    """/api/state 响应三元组 (body, etag, gz)：同锁内成对读取。

     两段式：先无锁调 _latest_state()（触发/等待重建——等待段
    绝不可持锁，否则与构建线程发布段互等死锁），再同锁一拍读取三元组。
    签名命中时连 json.dumps 都省掉（370KB 级载荷每次 dumps 要十几毫秒，
    轮询路径零序列化）。 的撕裂不变量保持：body/etag/gz 三元组
    仍在一个锁区内读齐——重建线程发布段同锁一次落位，读侧不会拿到旧
    body 配新 etag 下发 200（客户端按新 etag 落陈旧缓存被 304 粘死）。"""
    _latest_state()
    with _STATE_LOCK:
        body = _STATE_CACHE["body"]
        # 下一轮时间独立于票价缓存：空扫描/失败扫描未写库时，旧时间
        # 会一直命中相同 ETag，前端到点后永久显示「扫描中」。只更新
        # 轻量调度字段和响应三元组，不为此重算整份航班历史。
        if not DEMO["on"]:
            next_run = _next_run()
            payload = _STATE_CACHE.get("payload") or {}
            if payload.get("next_run") != next_run:
                payload = dict(payload, next_run=next_run)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                _STATE_CACHE.update(
                    payload=payload, body=body,
                    etag='"%s"' % hashlib.md5(body).hexdigest(),
                    gz=gzip.compress(body, 6))
        if body is None:
            body = json.dumps(_STATE_CACHE["payload"],
                              ensure_ascii=False).encode("utf-8")
        return (body, _STATE_CACHE.get("etag") or "",
                _STATE_CACHE.get("gz"))


def _preview_payload(user_idx: int) -> dict:
    """钉钉推送预览：从 DB 最新一轮还原 (route, sections)，
    调 _digest_payload 纯构建（不发送/不拨号/不传图床）。"""
    import types
    from core.models import FlightPrice, Route
    st = _State
    users = st.users or []
    if not users:
        return {"ok": False, "err": "尚未配置用户"}
    user_idx = max(0, min(int(user_idx or 0), len(users) - 1))
    u = users[user_idx]
    db = _anchored((st.cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, from_city, to_city, depart_date, price, extra, "
        "fetched_at FROM flight_prices WHERE extra != '' AND fetched_at >= "
        "datetime('now', 'localtime', '-40 minutes') "
        "ORDER BY id DESC").fetchall()
    conn.close()
    rows = _cluster_round_rows(rows, scan_start=_scan_marker_window())
    if not rows:
        return {"ok": False, "err": "暂无本轮数据，先「立即扫描一轮」跑一轮"}
    by_key = {}
    for r in rows:
        by_key.setdefault(
            (r["from_city"], r["to_city"], r["depart_date"]), []).append(r)
    a = Alerter(st.logger, notifier=None,
                storage=types.SimpleNamespace(db_path=db), digest=True,
                at_mobile=str(((u.get("notifier") or {}).get("dingtalk")
                               or {}).get("at_mobile", "")),
                user=u.get("name", ""),
                platforms=u.get("platforms") or None)
    built = []
    for r0 in (u.get("routes") or []):
        rv = _route_view(r0)
        if not rv.get("from"):
            continue
        route = Route(
            from_code=rv["from"], from_name=rv["from_name"],
            to_code=rv["to"], to_name=rv["to_name"], dates=rv["dates"],
            alert_direct=rv["alert_direct"],
            alert_transfer=rv["alert_transfer"],
            transfer_arrival_max=rv["transfer_arrival_max"],
            transfer_layover_min=rv["transfer_layover_min"],
            transfer_baggage=rv["transfer_baggage"],
            dep_time_min=rv["dep_time_min"], dep_time_max=rv["dep_time_max"])
        # 逐日期独立成 entry（与生产 main.py 按查询日期逐条喂条的
        # 形状对齐）：曾把多日期价格并进一条产出单节「MM/DD-MM/DD」
        # +次日期 📍 mini 折行——预览≠实发的结构性差异（实发恒为
        # 逐日期独立全节），构建参考失真
        for d in rv["dates"]:
            prices = [FlightPrice(
                platform=row["platform"], from_city=row["from_city"],
                to_city=row["to_city"], depart_date=row["depart_date"],
                price=row["price"], extra=row["extra"],
                fetched_at=row["fetched_at"])
                for row in by_key.get((rv["from"], rv["to"], d), [])]
            if prices:
                secs = a._build_sections(route, prices)
                if secs:
                    built.append((route, secs))
    if not built:
        return {"ok": False, "err": "本轮数据为空"}
    # with_charts=False：预览无本轮走势图 URL，整段跳过走势块——
    # 缺图分支曾恒出假警告误导用户（词面已中性化「缺失」）；
    # with_tables=False 同理在 desp 尾补占位注——预览≠实发的结构性
    # 差异不标注，构建参考读者会误以为实发也无表
    p = a._digest_payload(built, fresh=True, with_tables=False,
                          with_charts=False)
    return {"ok": True, "title": p["title"],
            # @ 前插单源（审校 P3-4）：预览注曾直拼 desp 尾落在 @ 段
            # 之后，「@ 恒为消息末行」不变量在预览器破例；
            # _append_before_at 同时承担前导段落分隔（@ 段不与引用行粘连）
            "desp": _append_before_at(
                p["desp"], "> （预览态无明细总表图，实发附整表PNG）"),
            "hits": len(p["hits"]), "user": u.get("name", "")}


_HEALTH_CACHE = {"sig": None, "payload": None, "busy": False, "at": 0.0}
_HEALTH_LOCK = threading.Lock()


def _cookie_states() -> dict:
    """Read-only session-state expiry hint (no cookie values leave disk)."""
    from crawlers import REGISTRY
    cfg = _effective_crawler_config()
    out = {}
    now = time.time()
    # 渠道集合从注册表派生（r710）：写死五家会让 App 渠道的「会话将过期」
    # 提示永远缺失，而 App 同样是必须登录的。
    from crawlers import APP_CHANNELS as _APP_PLATS
    _plats = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu") + tuple(_APP_PLATS)
    for p in _plats:
        try:
            c = REGISTRY[p](cfg, _State.logger)
            path = getattr(c, "session_state_path", "")
            if not path or not os.path.isfile(path):
                out[p] = "missing"
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies") or []
            if not cookies:
                out[p] = "missing"
                continue
            valid = False
            for ck in cookies:
                exp = ck.get("expires", -1)
                try:
                    exp = float(exp)
                except (TypeError, ValueError):
                    exp = -1
                if exp in (-1.0, 0.0) or exp > now:
                    valid = True
                    break
            out[p] = "unverified" if valid else "expired"
        except Exception:
            out[p] = "unverified"
    return out


# 装饰层重入标志：_health_decorate → _attach_diag_slots → _login_state_view
# 若再调 _health_state(24) 会绕回 _health_decorate 无限递归（实测把
# /api/health 挂死）。置位后 _login_state_view 改走「直接解析日志」。
# 标志按线程记账：其他线程置真不得改变本线程的登录态证据来源。
_IN_HEALTH_DECORATE = False
_IN_HEALTH_DECORATE_TID = threading.local()


def _attach_diag_slots(out: dict) -> None:
    """给诊断卡补会话维度（只读 /api/login-state，不碰数据库）。

    飞猪 PC/H5 两套 cookie，诊断卡只写「登录态失效」+「打开登录」时，
    用户会去核错那一端。这里把失效端与目标槽位挂到卡片上。
    单独成函数是为了让演示路径也能用，而不必走 _health_decorate 的
    PriceStorage 分支（那会把 demo 的 /api/health 拖到 25s 以上）。
    """
    try:
        _lv = _login_state_view() or {}
        _slots = _lv.get("slots") or {}
        if not _slots:
            return
        _by_plat = {}
        for _sk, _sv in _slots.items():
            _by_plat.setdefault((_sv or {}).get("plat") or _sk, []).append(
                dict(_sv or {}, key=_sk))
        for _c in out.get("diag") or []:
            _own = _by_plat.get(_c.get("plat")) or []
            if len(_own) < 2:
                continue
            _c["slots"] = [{
                "slot": _x.get("slot") or _x.get("key"),
                "surface": _x.get("surface_label") or _x.get("surface") or "全端",
                "needs_login": bool(_x.get("needs_login")),
                "status": _x.get("status") or "",
            } for _x in _own]
            _dead = [x for x in _c["slots"]
                     if x["needs_login"] or x["status"] == "save_error"]
            if _dead:
                _c["dead_surfaces"] = [x["surface"] for x in _dead]
                _c["slot_action"] = _dead[0]["slot"]
    except Exception:
        pass


def _demo_paths_from_rounds(rounds):
    """演示载荷的分通路账：只用轮次里已有的字段聚合，不编造数据。

    演示的 /api/health 走的是轻路径（不能进 _health_decorate，那里会开
    PriceStorage 把接口挂死），于是 j.paths 永远是空的，分域小标与分通路
    行在演示里从不出现——「健康只有厂商一个数」在演示环境尤其明显。
    健康卡与节流面板必须读同一份聚合，否则同一页会一边显示分通路、
    一边写「按轮判定」自相矛盾。
    """
    try:
        rounds = rounds or []
        if not rounds:
            return {}
        agg = {}
        for r in rounds:
            for p, c in (r.get("plats") or {}).items():
                # qdet/qcal 是「查询级」拆分（一行轮次 ≈ 一次查询），
                # 与生产 path_stats 同名同义；缺了它节流行会写出
                # 「查询 93% · 明细 0 / 日历 0」自相矛盾的一串。
                a = agg.setdefault(p, {"att": 0, "ok": 0, "det": 0, "cal": 0,
                                       "part": 0, "fail": 0, "qdet": 0,
                                       "qcal": 0})
                s = str(c.get("s") or "")
                det, cal = int(c.get("detail") or 0), int(c.get("cal") or 0)
                # 维护轮既不算成功也不算失败（与健康徽标「维护轮不计分母」
                # 同口径），否则飞猪会出现查询 15% 而同通路 100% 的打架。
                if s == "maint":
                    continue
                if det > 0:
                    a["qdet"] += 1
                elif cal > 0:
                    a["qcal"] += 1
                a["att"] += 1
                if s == "ok":
                    a["ok"] += 1
                    if det > 0:
                        a["det"] += 1
                    elif cal > 0:
                        a["cal"] += 1
                elif s == "part":
                    a["part"] += 1
                else:
                    a["fail"] += 1
                # 通路维度：失败轮也算该渠道的尝试——否则通路率的分母只剩
                # 成功轮，会写出「明细 100%」而同一行徽标是 93%（实测），
                # 两个数字打架。通路名取自「出数形态」，失败轮沿用该渠道
                # 已知的那条通路；一条都没有时不臆造通路（避免「无出数 0%」）。
                if det > 0:
                    course = "明细"
                elif cal > 0:
                    course = "日历"
                else:
                    course = a.get("_course") or ""
                    if not course:
                        continue
                a["_course"] = a.get("_course") or course
                node = a.setdefault("paths", {}).setdefault(
                    course, {"attempts": 0, "ok": 0, "detail_ok": 0, "calendar_ok": 0})
                node["attempts"] += 1
                if s in ("ok", "part") and (det > 0 or cal > 0):
                    node["ok"] += 1
                    node["detail_ok"] += 1 if det > 0 else 0
                    node["calendar_ok"] += 1 if cal > 0 else 0
        paths = {}
        for p, a in agg.items():
            if not a["att"]:
                continue
            pp = {}
            for name, nd in (a.get("paths") or {}).items():
                if not nd["attempts"]:
                    continue
                pp[name] = dict(nd, rate=round(nd["ok"] / nd["attempts"], 4))
            if not pp:
                continue
            paths[p] = {"paths": pp, "retired": [],
                        "query_attempts": a["att"],
                        "query_ok": a["ok"],
                        "query_detail_ok": a["qdet"],
                        "query_calendar_only": a["qcal"],
                        "query_rate": round(a["ok"] / a["att"], 4)}
        return paths
    except Exception:
        return {}


def _attach_demo_paths(out: dict) -> None:
    """把分通路账挂到演示 /api/health 载荷上（与 /api/paths 同源）。"""
    # r538：演示态必须让**卡片自己**说明数据来源。原先只有页头那行
    # 「DEMO · 合成健康」带标识，诊断卡仍逐张写「最近一轮正常」——
    # 与真实环境一模一样的措辞，用户读作「补位数据很奇怪」。
    # 演示走的是轻路径（不经 _health_decorate），故标志在这里落。
    out["demo"] = True
    for _c in out.get("diag") or []:
        if isinstance(_c, dict) and _c.get("label"):
            _c["label"] = "演示 · " + str(_c["label"])
    try:
        paths = _demo_paths_from_rounds(out.get("rounds") or [])
        if paths:
            out["paths"] = paths
    except Exception:
        pass


def _demo_health_payload() -> dict:
    """演示 /api/health 的完整轻量载荷（诊断卡 + 分通路 + 渠道全集）。

    静态烘焙与在线 demo 共用。**不含** `_attach_diag_slots`：那一步读
    本机真实登录态，公开演示站不能把访客自己的登录状态烘进 HTML。
    """
    from core.demo import demo_health
    from core.health_diag import classify_round
    out = demo_health()
    rounds = out.get("rounds") or []
    plats = (rounds[-1].get("plats") if rounds else {}) or {}
    out["diag"] = classify_round(plats, all_plats=tuple(plats))
    out["diag_at"] = rounds[-1].get("ts", "") if rounds else ""
    _attach_demo_paths(out)
    out["enabled_platforms"] = _enabled_platforms()
    return out


def _diag_platforms(seen_plats=None) -> tuple:
    """诊断卡要覆盖的渠道：默认 5 家浏览器渠道 + 用户启用的 App 渠道。

    只并入**用户 platforms 里配了的** App 渠道（或本轮真跑过的）：
    没启用的人不该看到一张「本轮未扫描」的空卡。
    """
    from core.health_diag import PLATFORMS
    out = list(PLATFORMS)
    try:
        from crawlers import APP_CHANNELS
    except Exception:
        APP_CHANNELS = ()
    enabled = set(seen_plats or [])
    try:
        for u in (_State.users or []):
            enabled |= set(u.get("platforms") or [])
    except Exception:
        pass
    for p in APP_CHANNELS:
        if p in enabled and p not in out:
            out.append(p)
    return tuple(out)


def _health_decorate(out: dict) -> dict:
    global _IN_HEALTH_DECORATE
    from core.health_diag import classify_round
    rounds = out.get("rounds") or []
    plats = (rounds[-1].get("plats") if rounds else {}) or {}
    # 诊断卡只覆盖默认 5 家浏览器渠道；用户启用的 App 渠道（智行 App）
    # 跑过也永远不出卡——「看得见的渠道才能干预」，于是它连自检入口
    # 都没有。把「用户实际启用的渠道」并进去：没启用的不会多出空卡。
    # r977：诊断卡必须覆盖**与同屏健康行/节流行相同的渠道集合**。
    # 旧实现只取最近一轮的 plats：最后一轮若只跑了浏览器五家，App 渠道
    # 就会从诊断卡里整块消失，而下方健康行/节流行仍有它——同屏三张表
    # 三个渠道集合，用户读作「渠道能力只覆盖了一部分」。
    # 近 24h stats 里出现过的渠道都并入（含 App），再由 _diag_platforms
    # 补上用户启用但还没跑过的渠道。
    _plats = list(plats)
    try:
        for _p, _st in (out.get("stats") or {}).items():
            _n = ((_st or {}).get("ok", 0) + (_st or {}).get("part", 0)
                  + (_st or {}).get("fail", 0))
            if _p and _n and _p not in _plats:
                _plats.append(_p)
    except Exception:
        pass
    # 登录证据必须喂给诊断器：此前只传 cookie，`lg` 恒空，App 渠道的
    # 「登录态失效」就被归成「抓取失败（原因待核对）」（现场 2026-11-01：
    # 去哪儿 App 卡显示抓取失败，而账本每轮都是 app-login/login）。
    # 本函数在 _health_state 调用栈内：读 _login_state_view 会再调
    # _health_state → 递归（实测 /api/health 直接挂死 >60s）。必须置重入标志。
    _prev_in = _IN_HEALTH_DECORATE
    _prev_tid = getattr(_IN_HEALTH_DECORATE_TID, "ident", None)
    _IN_HEALTH_DECORATE = True
    _IN_HEALTH_DECORATE_TID.ident = threading.get_ident()
    try:
        _login_ev = dict((_login_state_view().get("plats") or {}))
    except Exception:
        _login_ev = {}
    finally:
        _IN_HEALTH_DECORATE = _prev_in
        if _prev_tid is None:
            try:
                del _IN_HEALTH_DECORATE_TID.ident
            except AttributeError:
                pass
        else:
            _IN_HEALTH_DECORATE_TID.ident = _prev_tid
    try:
        # 登录卡的 App「已保存会话」判定：查的必须是采集器**真的写进去**的
        # 那个目录（唯一口径 + 启动级，见 `_ud_root_runtime()`）。原来自算
        # 一遍 → 装了 `TM_USER_DATA_DIR` 时永远判「未保存」（r1063 T10 复核）。
        _udir = _ud_root_runtime()
        from crawlers import APP_CHANNELS as _APPCH
        for _p in _APPCH:
            _login_ev[_p] = {
                "needs_login": _app_login_expired(_p),
                "saved": os.path.isfile(os.path.join(
                    _udir, "android_snapshots", _p + ".tar.gz")),
            }
    except Exception:
        pass
    out["diag"] = classify_round(plats, login=_login_ev,
                                 cookie=_cookie_states(),
                                 all_plats=_diag_platforms(_plats))
    out["diag_at"] = rounds[-1].get("ts", "") if rounds else ""
    # r1633：诊断卡也要能说**为什么不动**。停手中的渠道卡片原先写
    # 「本轮未扫描 / 抓取失败 / 去登录」，用户会去登录、去排查，
    # 而其实是我们自己人工停了（今天携程/飞猪 12h 停手就是这样）。
    # 同理：不在采集清单里的渠道写「等待下一轮或手动扫描」也是假的。
    try:
        import time as _ht2
        from core.policy import read_halt as _rh3
        _hn2 = _ht2.time()
        _plan = _enabled_plats()
        for _c2 in (out.get("diag") or []):
            if not isinstance(_c2, dict):
                continue
            _pp = str(_c2.get("plat") or "")
            try:
                _rec3 = (_rh3(_policy_engine(_pp).base_dir)
                         or {}).get(_pp) or {}
                _u3 = float(_rec3.get("until") or 0)
            except Exception:
                _u3 = 0.0
                _rec3 = {}
            _c2["halt"] = ({"until": _u3,
                           "left_s": max(0, int(_u3 - _hn2)),
                           "note": str(_rec3.get("note") or "")}
                          if _u3 > _hn2 else None)
            _rr = _retired_reason(_pp)
            # r1677：**证据**行用账本最近一条补全。空证据或
            # 「抓取失败」等于让用户猜；账本里明明有原文
            # （如「搜索后要求登录 · 页面: 登录」）。
            try:
                _ev = str(_c2.get("evidence") or "").strip()
                if not _ev or _ev == "抓取失败":
                    _rows = _strategy_storage().recent_paths(_pp, 1)
                    if _rows:
                        _r0 = _rows[0] or {}
                        _c2["evidence"] = (
                            "%s · %s · %s · %s"
                            % (str(_r0.get("fetched_at") or "")[5:16],
                               str(_r0.get("entry_path") or "?"),
                               str(_r0.get("path_status") or ""),
                               str(_r0.get("note") or "")))[:160]
            except Exception:
                pass
            _c2["retired"] = _rr
            # 停服的渠道不存在"勾选就能采"，所以不再判 no_plan。
            _c2["no_plan"] = bool(not _rr and _plan is not None
                                  and _pp and _pp not in _plan)
    except Exception:
        pass
    # r538：演示态必须让**卡片自己**说明数据来源。原先只有页头那行
    # 「DEMO · 合成健康」带标识，诊断卡仍然逐张写「最近一轮正常」——
    # 与真实环境的结论一模一样的措辞，用户读作「补位数据很奇怪」。
    # 这里把 demo 标志与口径一并下发，前端据此改写状态词。
    out["demo"] = bool(DEMO["on"])
    if DEMO["on"]:
        for _c in out["diag"] or []:
            if isinstance(_c, dict) and _c.get("label"):
                _c["label"] = "演示 " + str(_c["label"])
    # 诊断卡也要多会话维度（r430）。此处在 _health_state 调用栈内，
    # 必须置重入标志，否则 _login_state_view 再调 _health_state 会递归。
    # （global 已在本函数开头声明一次；重复声明在 3.11 会报
    #   "used prior to global declaration"。）
    _prev = _IN_HEALTH_DECORATE
    _prev_tid2 = getattr(_IN_HEALTH_DECORATE_TID, "ident", None)
    _IN_HEALTH_DECORATE = True
    _IN_HEALTH_DECORATE_TID.ident = threading.get_ident()
    try:
        _attach_diag_slots(out)
    finally:
        _IN_HEALTH_DECORATE = _prev
        if _prev_tid2 is None:
            try:
                del _IN_HEALTH_DECORATE_TID.ident
            except AttributeError:
                pass
        else:
            _IN_HEALTH_DECORATE_TID.ident = _prev_tid2
    # 通路维度（r416）：同一厂商内 PC/H5/日历/窗历是不同通路，成功率与
    # 退役状态本就分开记在 path_stats 里，只是健康面板拿不到。补在这里，
    # 前端就能在徽标下显示「PC 100% · 窗历 100%（旧日历已退役）」这类
    # 事实，而不是一个笼统的厂商数。
    try:
        from core.storage import PriceStorage
        dbp = _anchored(((_State.cfg or {}).get("output") or {}).get(
            "db_path"), "data/prices.db")
        if os.path.isfile(dbp):
            ps = PriceStorage(dbp).path_stats(hours=24)
            paths = {}
            for _p, _node in (ps or {}).items():
                _pp = {}
                for _pn, _pv in (_node.get("paths") or {}).items():
                    _pp[_pn] = {
                        "rate": _pv.get("rate"),
                        "attempts": _pv.get("attempts"),
                        "last_ok_at": _pv.get("last_ok_at"),
                    }
                if _pp:
                    # 分域也用**查询口径**（与 advice 同源）：健康时间线按
                    # 轮次统计，两者天然不同；同一面板里若混用两套口径，
                    # 用户会以为数据打架（国际 13% vs 73%）。
                    _sc = {}
                    for _sn, _sv in (_node.get("scopes") or {}).items():
                        if not isinstance(_sv, dict):
                            continue
                        _q = _sv.get("query_attempts") or 0
                        if _q:
                            # 字段名必须与前端一致（r490）：前端分域读的是
                            # `query_attempts[_live]` / `query_rate[_live]`，
                            # 这里曾经只发 {rate, attempts}——两侧不同名，
                            # 于是「分域」这一维在真实页面上**从未渲染过**
                            # （字符串守卫 test_goal_d 只查 scoped('dom','国内')
                            # 在场，看不见这类字段名错配）。
                            # 同时带上 *_live（剔除退役通路后的查询口径）：
                            # 前端优先用它，否则退役通路的历史成败会把
                            # 分域读数拖低，与徽标口径打架。
                            _sc[_sn] = {
                                "rate": _sv.get("query_rate"),
                                "attempts": _q,
                                "query_rate": _sv.get("query_rate"),
                                "query_attempts": _q,
                                "query_rate_live": _sv.get("query_rate_live"),
                                "query_attempts_live": _sv.get(
                                    "query_attempts_live"),
                            }
                    paths[_p] = {
                        "paths": _pp,
                        "retired": list(_node.get("retired_paths") or []),
                        "scopes": _sc,
                        # 在用口径：剔除退役通路后的查询成功率（与 advice
                        # 同源）。同程「76%」里含旧日历的历史成败，而在用的
                        # 窗历/H5 都是 100%——徽标该说在用口径。
                        "query_rate_live": _node.get("query_rate_live"),
                        "query_attempts_live": _node.get("query_attempts_live"),
                    }
            if paths:
                out["paths"] = paths
    except Exception:
        pass
    return out


def _channel_evidence_path() -> str:
    return _anchored("logs/channel_evidence.jsonl", "logs/channel_evidence.jsonl")


def _append_channel_evidence(card: dict, user: str = "") -> None:
    path = _channel_evidence_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "user": user, "plat": card.get("plat"),
                "kind": card.get("kind"), "label": card.get("label"),
                "s": card.get("s"), "ok": card.get("ok"),
                "tot": card.get("tot"), "login": card.get("login"),
                "cookie": card.get("cookie"),
                "evidence": card.get("evidence", ""),
            }, ensure_ascii=False) + "\n")
        if os.path.getsize(path) > 512 * 1024:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-500:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except Exception as e:
        try:
            _State.logger.warning("[诊断] 证据账本写入失败: %s", e)
        except Exception:
            pass


def _warmable():
    """能预热的渠道 = REGISTRY 里 warmup_url 非空的那些（r627）。

    以前这里是一份手写白名单，含 ctrip/tongcheng —— 两家都没有入口，
    用户填进「预热渠道」后按钮可点、点了没反应。判据要跟着真实能力走。
    """
    try:
        from crawlers import REGISTRY as _R
        return tuple(sorted(k for k, cls in _R.items()
                            if str(getattr(cls, "warmup_url", "") or "").strip()))
    except Exception:
        return ("fliggy", "qunar", "tuniu")


def _enabled_platforms():
    """用户配置里勾选过的渠道并集（r604）。

    健康卡的行来自日志里**出现过**的渠道，配了却没被扫的渠道整行不渲染，
    用户读作「这个渠道不存在」。后端把「勾了哪些」一并下发，前端才能说
    「已勾选，但近 24h 无扫描记录」——而不是让人去配置页反复确认。
    """
    out = []
    for u in ((_State.cfg or {}).get("users") or []):
        for p in (u.get("platforms") or []):
            p = str(p or "").strip()
            if p and p not in out:
                out.append(p)
    return out


def _device_lock_view(cfg: dict) -> dict:
    """设备锁持有者快照（r925 的观测面）：谁占着、多久、预算还剩多少。

    只读模块级状态，不碰 adb；Android 关时直接返回 enabled=False。
    2026-11-04 事故里「卡死 10 小时查不出是谁占着锁」，日志之外必须
    在健康页也能一眼看到，否则同一个洞还会再踩。
    """
    and_cfg = (cfg or {}).get("android") if isinstance(cfg, dict) else None
    enabled = bool((and_cfg or {}).get("enabled"))
    out = {"enabled": enabled, "owner": "", "held_s": 0,
           "budget_left": 0.0, "deadline_hits": 0, "unavailable": ""}
    if not enabled:
        return out
    try:
        from core.android.runtime import get_runtime
        rt = get_runtime(cfg, getattr(_State, "logger", None))
        st = rt.lock_state()
        since = float(st.get("since") or 0)
        out.update({
            "owner": str(st.get("owner") or ""),
            "held_s": int(max(0.0, time.time() - since)) if since > 0 else 0,
            "budget_left": round(float(st.get("budget_left") or 0), 1),
            "deadline_hits": int(st.get("deadline_hits") or 0),
        })
    except Exception as e:
        out["unavailable"] = str(e)[:120]
    return out


def _health_state(hours: int = 24) -> dict:
    """渠道健康时间线：解析 monitor.log（尾部 2MB 封顶，防长日志拖慢）。

    按 (monitor.log, push_history.jsonl) 双文件 (路径, mtime_ns, size)
    签名缓存——控制台每 10s 轮询，轮间双账本不变时不再重复解析；
    推送账本参与签名（推送轮更新不依赖 monitor.log，只锚日志会让
    通道健康滞后到下一扫描轮才刷新）。"""
    from core.health import parse_health
    logp = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "log_path"), "logs/monitor.log")
    php = os.environ.get("PUSH_HISTORY_FILE") or os.path.join(
        "logs", "push_history.jsonl")
    parts = []
    for p in (logp, logp + ".1", logp + ".2", logp + ".3", php):
        try:
            st = os.stat(p)
            parts.extend([p, st.st_mtime_ns, st.st_size])
        except OSError:
            pass
    sig = (tuple(parts), hours) if parts else None
    with _HEALTH_LOCK:
        if (sig is not None and _HEALTH_CACHE["sig"] == sig
                and time.time() - _HEALTH_CACHE["at"] < 30):
            return _HEALTH_CACHE["payload"]
        # 日志每写一行 mtime_ns 就变，10s 轮询几乎必 miss；8 个并发
        # 请求曾各花 9.3s 齐解析（审计 P1）。有旧值时立即回旧值 +
        # 单飞后台刷新；2s 内不重复起刷，避免扫描期日志抖动打满 CPU。
        if _HEALTH_CACHE["payload"] is not None:
            if not _HEALTH_CACHE["busy"] and time.time() - _HEALTH_CACHE["at"] >= 2:
                _HEALTH_CACHE["busy"] = True

                def _run():
                    try:
                        out = parse_health(
                            _read_log_tail(max_age_h=hours + 2), hours=hours)
                        out["push"] = _push_channel_state(hours=hours)
                        out = _health_decorate(out)
                        with _HEALTH_LOCK:
                            _HEALTH_CACHE.update(
                                sig=sig, payload=out, busy=False,
                                at=time.time())
                    except Exception as e:
                        try:
                            (_State.logger or print)(
                                "[控制台] 健康缓存刷新异常: %s" % e)
                        except Exception:
                            pass
                        with _HEALTH_LOCK:
                            _HEALTH_CACHE["busy"] = False

                threading.Thread(target=_run, daemon=True,
                                 name="health-rebuild").start()
            return _HEALTH_CACHE["payload"]
    out = parse_health(_read_log_tail(max_age_h=hours + 2), hours=hours)
    out["push"] = _push_channel_state(hours=hours)
    out = _health_decorate(out)
    with _HEALTH_LOCK:
        _HEALTH_CACHE.update(sig=sig, payload=out, busy=False, at=time.time())
    return out


def _radar_db_path() -> str:
    return _anchored(((_State.cfg or {}).get("output") or {}).get(
        "db_path"), "data/prices.db")


def _radar_ok_dates(result: dict) -> tuple:
    """Keep only real calendar observations from channels that succeeded.

    Cached/fallback runs and failed channels may still be displayed live, but
    they must not enter history or move an alert baseline.
    """
    sts = result.get("channels") or {}
    dates = []
    for d in result.get("dates") or []:
        keep = {}
        for ch, rec in (d.get("by_channel") or {}).items():
            s = sts.get(ch) or {}
            if s and (s.get("cache_hit") or s.get("fallback")
                      or s.get("status") != "ok"):
                continue
            keep[ch] = rec
        if keep:
            dates.append({**d, "by_channel": keep})
    if dates:
        return dates, "ok"
    if any((s or {}).get("cache_hit") for s in sts.values()):
        return dates, "cache_hit"
    if any((s or {}).get("fallback") for s in sts.values()):
        return dates, "fallback"
    if result.get("dates") or any((s or {}).get("status") == "ok"
                                  for s in sts.values()):
        return dates, "partial"
    return dates, "empty"


def _radar_alert_dispatch(user, query, date, low, dec, channel, basis):
    from core.alerter import sanitize_desp
    st = PriceStorage(_radar_db_path())
    qkey = st.radar_query_key(query)
    al = next((a for a in (_State.alerters or [])
               if getattr(a, "user", "") == user), None)
    if not al or not getattr(al, "notifier", None):
        st.record_radar_alert(user, qkey, date, dec.price, dec.prev_low,
                              channel, basis, dec.kind, low.get("link") or "",
                              "", "skipped", "no_notifier")
        return False, "no_notifier"
    if hasattr(al, "_in_quiet") and al._in_quiet():
        st.record_radar_alert(user, qkey, date, dec.price, dec.prev_low,
                              channel, basis, dec.kind, low.get("link") or "",
                              "", "skipped", "quiet")
        return False, "quiet"
    fl = _radar_low_flights(query.get("from"),
                            low.get("to") or query.get("to"),
                            date, limit=3)
    fs = fl.get("flights") or []
    title = "📉 特价雷达%s %s→%s %s ￥%.0f" % (
        "新低" if dec.kind == "new_low" else "阈值",
        query.get("from", ""), low.get("to") or query.get("to", ""),
        date, dec.price)
    lines = ["- **价格**：￥%.0f（%s）" % (
        dec.price, low.get("basis_label") or basis or "口径未标注")]
    if dec.prev_low is not None:
        lines.append("- **较上次低点**：￥%.0f（降 ￥%.0f）"
                     % (dec.prev_low, dec.prev_low - dec.price))
    lines.append("- **渠道**：%s" % Alerter.plat_cn(channel))
    if fs:
        lines.append("- **该日真实明细**：")
        for f in fs:
            lines.append("  - %s %s→%s ￥%.0f %s" % (
                f.get("code") or "—", f.get("depTime") or "—",
                f.get("arrTime") or "—", float(f.get("price") or 0),
                f.get("platform_cn") or ""))
    else:
        lines.append("- **该日真实明细**：尚未采集；日历价不能生成航班")
    if low.get("link"):
        lines.append("- [打开官方渠道](%s)" % low["link"])
    try:
        ok = bool(al.notifier.send(sanitize_desp(title),
                                   sanitize_desp("\n\n".join(lines))))
        err = "" if ok else "send_failed"
    except Exception as e:
        ok, err = False, str(e)[:160]
    st.record_radar_alert(user, qkey, date, dec.price, dec.prev_low,
                          channel, basis, dec.kind, low.get("link") or "",
                          json.dumps(fs, ensure_ascii=False),
                          "sent" if ok else "failed", err)
    return ok, err


def _radar_eval_alerts(user, query, dates, st):
    from core.radar_alerts import RadarAlertCfg, evaluate
    raw = st.radar_alert_config(user)
    acfg = RadarAlertCfg(enabled=bool(raw["enabled"]),
                         drop_min=float(raw["drop_min"]),
                         threshold=float(raw["threshold"]),
                         cooldown_h=float(raw["cooldown_h"]))
    qkey = st.radar_query_key(query)
    for d in dates:
        items = list((d.get("by_channel") or {}).items())
        if not items:
            continue
        channel, low = min(items, key=lambda kv: float(
            kv[1].get("price") or 0))
        price = float(low.get("price") or 0)
        basis = str(low.get("basis") or "")
        prev = st.get_radar_alert_state(user, qkey, d["date"])
        dec = evaluate(
            float(prev["low_price"]) if prev else None,
            (prev or {}).get("low_basis") or "",
            price, basis, int((prev or {}).get("armed", 1)),
            (prev or {}).get("last_alert_at"), datetime.now(), acfg)
        now_s = datetime.now().isoformat(timespec="seconds")
        if dec.action == "basis_reset" or not prev:
            low_price, low_at = price, now_s
            low_ch, low_basis = channel, basis
        else:
            prev_low = float(prev["low_price"])
            if price <= prev_low:
                low_price, low_at = price, now_s
                low_ch, low_basis = channel, basis
            else:
                low_price = prev_low
                low_at = prev.get("low_at") or now_s
                low_ch = prev.get("low_channel") or ""
                low_basis = prev.get("low_basis") or ""
        last_at = (prev or {}).get("last_alert_at") or ""
        last_price = (prev or {}).get("last_alert_price")
        if dec.action in ("new_low", "threshold"):
            ok, _err = _radar_alert_dispatch(
                user, query, d["date"], low, dec, channel, basis)
            if ok:
                last_at, last_price = now_s, price
        st.save_radar_alert_state(
            user, qkey, d["date"], low_price, low_at, low_ch, low_basis,
            last_price, last_at, dec.armed)


def _radar_save_result(result: dict, source: str = "manual") -> int:
    """Persist one radar run; auto runs may dispatch a price alert."""
    q = result.get("query") or {}
    user = str(q.get("user") or "")
    if not user:
        return 0
    dates, status = _radar_ok_dates(result)
    if DEMO["on"]:
        status = "demo"
    st = PriceStorage(_radar_db_path())
    n = st.save_radar_snapshot(user, q, {**result, "dates": dates},
                               run_status=status)
    if source == "auto" and status == "ok" and dates:
        try:
            _radar_eval_alerts(user, q, dates, st)
        except Exception as e:
            _State.logger.warning("[雷达提醒] 评估失败: %s", e)
    return n


def _radar_history(user: str, days: int = 120,
                   query_key: str = "") -> dict:
    st = PriceStorage(_radar_db_path())
    out = st.radar_history(user, days=days, query_key=query_key)
    out["auto_interval_h"] = 2
    # r1814：自动刷新到底会不会跑？`special_radar` 没配航线/区间时，后台
    # 每轮都「跳过（incomplete）」，而卡片照写「每 2 小时自动」——假承诺。
    try:
        _u = next((x for x in (_State.users or [])
                   if (x.get("name") if isinstance(x, dict)
                       else getattr(x, "name", "")) == user), None)
        _r = ((_u.get("special_radar") if isinstance(_u, dict)
               else getattr(_u, "special_radar", None)) or {})
        _q, _why = _radar_auto_query(_r)
        out["auto_ok"] = bool(_q)
        out["auto_why"] = "" if _q else str(_why or "incomplete")
    except Exception:
        out["auto_ok"] = True   # 判不了就别断言它停了
        out["auto_why"] = ""
    return out


def _radar_low_flights(frm, to, date, limit: int = 5) -> dict:
    """Lowest *real detail* flights for one radar low-price date.

    Radar calendar rows carry no flight identity; this reads already
    collected detail rows (or flight_daily when raw was purged) and never
    fabricates a flight for a calendar-only price.
    """
    frm = str(frm or "").upper()
    to = str(to or "").upper()
    date = str(date or "")[:10]
    if not (frm and to and date):
        raise ValueError("from/to/date required")
    db = _radar_db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = []
    try:
        raw = conn.execute(
            "SELECT id, platform, extra, prov, fetched_at FROM flight_prices "
            "WHERE from_city=? AND to_city=? AND depart_date=? "
            "AND extra!='' AND fetched_at >= datetime('now','localtime','-14 days') "
            "ORDER BY fetched_at DESC LIMIT 300",
            (frm, to, date)).fetchall()
        seen = {}
        for r in raw:
            try:
                pv = json.loads(r["prov"] or "{}")
            except (TypeError, ValueError):
                pv = {}
            try:
                obj = json.loads(r["extra"] or "[]")
            except ValueError:
                continue
            items = obj if isinstance(obj, list) else (
                [obj] if isinstance(obj, dict) else [])
            for idx, it in enumerate(items):
                if not isinstance(it, dict):
                    continue
                code = str(it.get("code") or it.get("flightNo") or "")
                dep = str(it.get("depTime") or "")
                arr = str(it.get("arrTime") or "")
                if not (code and dep and arr):
                    continue
                try:
                    price = round(float(it.get("price")))
                except (TypeError, ValueError):
                    continue
                if price <= 0:
                    continue
                key = _srx_flight_key({
                    "from": frm, "to": to, "date": date, "code": code,
                    "depTime": dep, "arrTime": arr,
                    "trans": str(it.get("transCity") or ""),
                    "cross": str(it.get("crossDayDesc") or ""),
                    "stop": bool(it.get("stopover"))})
                cur = seen.get(key)
                if cur is None or price < cur["price"]:
                    seen[key] = {
                        "price": price, "code": code,
                        "name": str(it.get("name") or it.get("airline") or ""),
                        "depTime": dep, "arrTime": arr,
                        "trans": str(it.get("transCity") or ""),
                        "cross": str(it.get("crossDayDesc") or ""),
                        "stop": bool(it.get("stopover")),
                        "platform": str(r["platform"] or ""),
                        "fetched_at": str(r["fetched_at"] or ""),
                        "rowId": int(r["id"]),
                        "rawIdx": idx,
                        "entryPath": str((pv or {}).get("entryPath") or ""),
                        "prov": pv if isinstance(pv, dict) else {},
                        "detail": True,
                    }
        rows = sorted(seen.values(), key=lambda x: x["price"])[:limit]
        if not rows:
            hist = conn.execute(
                "SELECT flight_key, platform, close, fetched_max FROM "
                "flight_daily WHERE from_city=? AND to_city=? AND "
                "depart_date=? ORDER BY close LIMIT 50",
                (frm, to, date)).fetchall()
            for h in hist:
                parts = str(h["flight_key"] or "").split("|")
                if len(parts) < 6:
                    continue
                rows.append({
                    "price": round(float(h["close"] or 0)),
                    "code": parts[2], "name": "",
                    "depTime": parts[4], "arrTime": parts[5],
                    "trans": parts[6] if len(parts) > 6 else "",
                    "cross": parts[7] if len(parts) > 7 else "",
                    "stop": len(parts) > 8 and parts[8] == "1",
                    "platform": str(h["platform"] or ""),
                    "fetched_at": str(h["fetched_max"] or ""),
                    "detail": False,
                })
            rows = [r for i, r in enumerate(rows)
                    if r["price"] > 0 and r["code"] not in
                    {x["code"] for x in rows[:i]}][:limit]
    finally:
        conn.close()
    from core.channels import plat_cn as _plat_cn
    for r in rows:
        r["platform_cn"] = _plat_cn(r["platform"])
    return {"ok": True, "from": frm, "to": to, "date": date,
            "found": bool(rows), "flights": rows,
            "note": ("来自已采集的真实航班明细" if any(
                r.get("detail") for r in rows) else
                "仅有历史日桶，无当轮原始行；请用该日探针核对")}


def _push_channel_state(hours: int = 24, tail_bytes: int = 262_144) -> dict:
    """推送通道健康：读推送账本尾部按通道聚合（只读消费，发送链路
    零触碰）。钉钉 -1 幽灵期邮件通道全绿时，主推送面在健康页不可见
    （逐条 ⚠️ 仅推送记录弹窗）——通道级 ok 率/连败补齐盲区。
    账本路径与写入面同源（PUSH_HISTORY_FILE 重定向同轨）；fail_streak
    =最后一条成功之后的连续失败数（升序尾长）。"""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    path = os.environ.get("PUSH_HISTORY_FILE") or os.path.join(
        "logs", "push_history.jsonl")
    empty = {"channels": {}}
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - tail_bytes))
            raw = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return empty
    lines = raw.splitlines()
    if lines and not lines[0].lstrip().startswith("{"):
        lines = lines[1:]   # 尾读切断的首半行丢弃
    chans: dict = {}
    t0 = _dt.now() - _td(hours=hours)
    for ln in lines:
        try:
            rec = _json.loads(ln)
        except ValueError:
            continue
        ch = rec.get("ch")
        if not ch:
            continue   # 旧账无通道字段，不入聚合
        try:
            ts = _dt.strptime(rec.get("ts", ""), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        if ts < t0:
            continue
        c = chans.setdefault(ch, {"ok": 0, "fail": 0, "fail_streak": 0,
                                  "last": "", "last_ok": ""})
        ok = bool(rec.get("ok"))
        hm = ts.strftime("%m-%d %H:%M")
        c["ok" if ok else "fail"] += 1
        c["last"] = hm   # 升序遍历尾现=最近一条
        if ok:
            c["last_ok"] = hm   # 尾现=最近一次成功
            c["fail_streak"] = 0
        else:
            c["fail_streak"] += 1
    return {"channels": chans, "window_hours": hours}


def _read_log_tail(max_bytes: int = 6_000_000, max_age_h=None) -> str:
    """按时间顺序拼接轮转日志：monitor.log.3→.2→.1→当前。
    RotatingFileHandler 到 5MiB 即改名；每份按默认 6MiB 整读，避免
    24h 窗口的历史轮次被 2MiB 尾读静默截掉。旧文件按 mtime 跳过
    （健康 24h 窗口之外的 .2/.3 不参与解析）。"""
    import os
    import time
    logp = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "log_path"), "logs/monitor.log")
    now = time.time()
    chunks = []
    for p in (logp + ".3", logp + ".2", logp + ".1", logp):
        try:
            st = os.stat(p)
        except OSError:
            continue
        if max_age_h and now - st.st_mtime > max_age_h * 3600:
            continue
        try:
            size = st.st_size
            with open(p, "rb") as f:
                if size > max_bytes:
                    f.seek(size - max_bytes)
                text = f.read().decode("utf-8", errors="replace")
                # 轮转文件可能不以换行收尾；直接拼接会把下一份的首行
                # 粘到上一份末行，解析器会丢掉一条真实事件。
                if text and not text.endswith("\n"):
                    text += "\n"
                chunks.append(text)
        except OSError:
            continue
    return "".join(chunks)


def _log_tail(plat: str, ts: str) -> dict:
    """某轮某渠道的日志原文：轮开始时间前 2 分钟至后 10 分钟窗口内，
    带该渠道标签的行 + 轮边界行（供健康格子点击查看）。"""
    import re
    from datetime import datetime as _dt, timedelta as _td
    if not re.match(r"^[\w-]+$", plat or ""):
        return {"ok": False, "err": "bad plat"}
    try:
        t0 = _dt.strptime(ts, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return {"ok": False, "err": "bad ts"}
    lo, hi = t0 - _td(minutes=2), t0 + _td(minutes=10)
    tag = "[" + plat + "]"
    line_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ")
    lines = []
    for ln in _read_log_tail().splitlines():
        m = line_re.match(ln)
        if not m:
            continue
        try:
            t = _dt.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if lo <= t <= hi and (tag in ln or "=====" in ln):
            lines.append(ln)
    return {"ok": True, "lines": lines[-60:], "plat": plat, "ts": ts}


class _Srv(ThreadingHTTPServer):
    """Windows 禁用地址复用：SO_REUSEADDR 允许同端口双绑静默影身
    （僵尸控制台持端口、新实例起在同端口却收不到连接——LESSONS 十.4
    双实例坑的放大器）。POSIX 允许复用 TIME_WAIT 地址以支持立即重启，
    仍拒绝绑定正在监听的端口。"""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def handle_error(self, request, client_address):
        # 客户端中途断开（刷新/提前关闭/探针超时）会让写回炸
        # ConnectionReset/ConnectionAborted/BrokenPipe——socketserver
        # 默认逐条打 traceback 到 stderr，err 文件随使用刷屏（逐条
        # 定性全为断连噪音）。断连族静默；其余异常维持默认输出。
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 才走 keep-alive/条件请求：HTTP/1.0（默认）下 Chromium
    # 不缓存 /api/state，也不会发 If-None-Match，304 分支形同虚设
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        # GET JSON 统一内容 ETag：健康/脉冲/配置轮询在数据未变时回 304，
        # 不再每拍重新传输/解析 3-100KB。POST 响应不参与条件请求。
        etag = '"%s"' % hashlib.sha1(body).hexdigest()
        if self.command == "GET" and code == 200:
            _inm = self.headers.get("If-None-Match") or ""
            if etag in [x.strip() for x in _inm.split(",") if x.strip()]:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
        self.send_response(code)
        if self.command == "GET" and code == 200:
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 健康/脉冲/配置等 JSON 也有 50-100KB；大包按客户端能力 gzip
        if len(body) > 1024 and "gzip" in (
                self.headers.get("Accept-Encoding") or ""):
            import gzip as _gz
            body = _gz.compress(body, 6)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body_ok(self):
        """POST body 是否为可接受的 JSON 形态（r672）。

        规则：**只有带 body 才要求 application/json**。`fetch(path,
        {method:'POST'})` 不带 body 时浏览器自动补 `text/plain`，无条件 415
        会把「立即扫描 / 打开文件夹 / 测试弹窗 / 重启 / 登录核验」这些
        无参按钮全打哑（实测 r672 端点普查里 13 个端点各 2 种形态全 415）。
        无 body 本就没有可解析载荷，CSRF 拿它也只能触发幂等动作；跨站
        请求仍由 Origin 闸门拦下，不靠 Content-Type 兜底。

        返回 True = 放行；False = 已回 415，调用方直接 return。
        """
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            return True
        ct = (self.headers.get("Content-Type") or "").lower()
        if "application/json" in ct:
            return True
        self._json({"ok": False, "err": "Content-Type 必须为 application/json"},
                   415)
        return False

    def _post_json(self, label="请求", max_len=16384):
        """POST JSON 统一闸门：同源 + application/json + 体积上限。

        干预类接口会开浏览器窗口、发真实请求，不能只靠"只监听
        127.0.0.1"——本机浏览器里的任意网页都能向 localhost POST。
        """
        if self.command != "POST":
            self._json({"ok": False, "err": "仅支持 POST"}, 405)
            return None
        # 与 _json_body_ok 同一条判据（只有带 body 才要求 JSON），在此内联：
        # 本方法被独立单测直接打在鸭子类型替身上调用（替身只实现 headers/
        # rfile/_json），不依赖类上的其它辅助方法。
        try:
            _n = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            _n = 0
        if _n > 0 and "application/json" not in (
                self.headers.get("Content-Type") or "").lower():
            self._json({"ok": False,
                        "err": "Content-Type 必须为 application/json"}, 415)
            return None
        origin = self.headers.get("Origin") or ""
        if origin:
            from urllib.parse import urlparse as _up
            if (_up(origin).netloc or "") != (self.headers.get("Host") or ""):
                self._json({"ok": False, "err": "跨站%s请求已拒绝" % label}, 403)
                return None
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > max_len:
            self._json({"ok": False, "err": "请求体过大"}, 413)
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json({"ok": False, "err": "请求体不是合法 JSON"}, 400)
            return None
        if not isinstance(body, dict):
            self._json({"ok": False, "err": "请求体必须为对象"}, 400)
            return None
        return body

    def do_HEAD(self):
        """HEAD / 供 uptime/探活使用：只回头部，不构建响应体。"""
        if self.path == "/":
            body, etag, _gz = _page_snap(_State.version)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        if self.path.startswith("/assets/icons/"):
            self._serve_icon(self.path, head_only=True)
            return
        self.send_error(405)

    def do_GET(self):
        """r1338：给慢 GET 留痕（**只记日志，不改语义**）。

        实测 `/api/login-state` 平时 0.1–2s，但在采集轮次占着设备锁时会拖到
        **34.9s**（前端只能一直显示加载态）。以前这类慢请求在日志里完全看不见，
        用户报"页面卡住"时无从对账。这里超过 2s 记一条 WARNING，把路径与耗时写清楚，
        既能定位卡在哪，又不会因为异常路径影响正常响应。
        """
        _t0 = time.time()
        try:
            try:
                return self._do_GET_impl()
            except AttributeError:
                # 测试里存在只借用 do_GET 的**替身 handler**（`_Get` 之类），
                # 它没有完整 Handler 的 `_do_GET_impl`。此时退回类上的实现，
                # 让计时包装对替身也透明（r1386：CI 实测 AttributeError ×2）。
                return _Handler._do_GET_impl(self)
        finally:
            _dt = time.time() - _t0
            if _dt > 2.0:
                try:
                    _State.logger.warning("[api] GET %s 耗时 %.1fs",
                                          self.path.split("?")[0], _dt)
                except Exception:
                    pass

    _ICON_NAME_RE = re.compile(r"img_[0-9a-f]{8}\.(png|svg)\Z")

    def _serve_icon(self, raw_path, head_only=False):
        """内容寻址静态图标（渠道/航司官方图标、favicon）。

        文件名 = 内容 md5 前 8 位，内容永不变化 → 授予 immutable
        一年缓存。只放行 `img_<8位hex>.(png|svg)` 字面形状，并以
        realpath 重锚回 icons 目录内，双保险挡路径穿越；不存在即 404。
        """
        name = raw_path.split("?", 1)[0][len("/assets/icons/"):]
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        mime = {"png": "image/png", "svg": "image/svg+xml"}.get(ext)
        icons = os.path.realpath(
            os.path.join(_ROOT, "webui_assets", "icons"))
        p = os.path.realpath(os.path.join(icons, name))
        if not (mime and self._ICON_NAME_RE.fullmatch(name)
                and p.startswith(icons + os.sep) and os.path.isfile(p)):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with open(p, "rb") as _f:
            body = _f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header(
            "Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _do_GET_impl(self):
        if self.path.startswith("/assets/icons/"):
            self._serve_icon(self.path)
            return
        if self.path == "/":
            body, etag, gz = _page_snap(_State.version)
            # no-cache=每次导航必回源校验：升级重启后浏览器绝不拿旧
            # 页 JS；ETag 让未变更代际直接 304（页面 gzip 后 → 0 字节）。
            # 图标已外置 webui_assets/icons/（immutable 强缓存），页面
            # gzip 是纯文本层收益（实测 2.58MB 原文 → 数百 KB）
            if etag and etag == self.headers.get("If-None-Match", "").strip():
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            if "gzip" in (self.headers.get("Accept-Encoding") or "") and gz:
                body = gz
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/notify":
            self.send_response(302)
            self.send_header("Location", "/notify/latest")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/notify/"):
            # Windows 弹窗点击直达：单条达标详情（轻页，非控制台）
            try:
                import json as _j
                import os as _os
                import re as _re2
                nid = _re2.sub(r"[^A-Za-z0-9]", "",
                               self.path[len("/notify/"):].split("?")[0])
                if nid == "latest":
                    # 便捷入口回归语义：latest 走「最新存档」分支（曾按
                    # nid 处理找 latest.json——该文件恒不存在，入口恒死）
                    nid = ""
                data = None
                d = _anchored(None, "data/notify")
                if DEMO["on"]:
                    # desp 内「真达标/破线/擦边」为图例词面手抄样例——
                    # 与 alerter._legend_line/_TIER_TABLE 同源词面，改版
                    # 日须同轮同步（同步律；投影化因 desp 是静态演示
                    # 文本、不引 Python 侧依赖）
                    data = {"nid": "NDEMO",
                            "title": "🚨 达标 上海→乌鲁木齐 09/25",
                            "desp": "#### 🚨 已达标——可出手\n\n"
                                    "> ⏱09:00 🎯真达标 🟩破线 🟨擦边 超线\n\n"
                                    "[**🎯 直飞 ￥1468**](https://m.flight.qunar.com/ncs/page/flightlist?depCity=%E4%B8%8A%E6%B5%B7&arrCity=%E4%B9%8C%E9%B2%81%E6%9C%A8%E9%BD%90&goDate=2026-09-25&from=touch_index_search&child=0&baby=0&cabinType=0)"
                                    "　线￥1600　低￥132\n\n"
                                    "国航CA1295 21:10-02:35(+1天)\n\n"
                                    "> 经济舱 · 经停乌鲁木齐\n\n"
                                    "乌鲁木齐→上海 10/06 · 国航CA1295 21:10-02:35 +1天",
                            "ts": "（演示数据）"}
                elif nid:
                    p = _os.path.join(_ROOT, "data", "notify", nid + ".json")
                    if _os.path.isfile(p):
                        with open(p, encoding="utf-8") as _nf:
                            data = _j.load(_nf)
                else:
                    if _os.path.isdir(d):
                        for f in sorted(_os.listdir(d), reverse=True):
                            if f.endswith(".json"):
                                with open(_os.path.join(d, f),
                                          encoding="utf-8") as _nf:
                                    data = _j.load(_nf)
                                break
                if data is None:
                    data = {"title": "通知不存在或已过期",
                            "desp": "详情仅保留最近 20 条，请从最新一条系统弹窗进入。",
                            "ts": ""}
                payload = _j.dumps(data, ensure_ascii=False).replace(
                    "</", "<\\/")
                body = NOTIFY_PAGE.replace(
                    "__PAYLOAD__", payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/paths"):
            try:
                from urllib.parse import parse_qs as _pqs3
                from urllib.parse import urlparse as _up3
                _q = _pqs3(_up3(self.path).query)
                try:
                    _h = int((_q.get("hours") or ["24"])[0])
                except (TypeError, ValueError):
                    _h = 24
                self._json(_paths_payload(_h, demo=DEMO["on"]))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/trace"):
            try:
                from urllib.parse import parse_qs as _pqs4
                from urllib.parse import urlparse as _up4
                _q = _pqs4(_up4(self.path).query)
                _plat = str((_q.get("platform") or [""])[0]).strip()
                try:
                    _lim = int((_q.get("limit") or ["8"])[0])
                except (TypeError, ValueError):
                    _lim = 8
                if DEMO["on"]:
                    self._json({"ok": True, "platform": _plat, "rows": [],
                                "demo": True})
                    return
                db = _anchored(((_State.cfg or {}).get("output") or {}).get(
                    "db_path"), "data/prices.db")
                rows = []
                ivs = []
                eff = None
                if os.path.isfile(db):
                    _st = PriceStorage(db)
                    rows = _st.recent_paths(_plat, _lim)
                    ivs = _st.interventions(_plat, _lim)
                    eff = _st.intervention_effect(_plat, 24)
                self._json({"ok": True, "platform": _plat, "rows": rows,
                            "interventions": ivs, "effect": eff})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/strategy/snapshot":
            # 导出策略配置快照（r1063 T37）：只读。
            # **导入不在这里**：写配置只有一条通路（`POST /api/config`），
            # 为快照另开写入口会立刻出现"谁最后写"的问题。导入走 CLI：
            #   python -m core.cfg_snapshot apply config.yaml snap.json
            try:
                from core.cfg_snapshot import export as _snap_export
                _snap = _snap_export(_State.cfg or {})
                self._json({"ok": True, "snapshot": _snap,
                            "counts": {"values": len(_snap.get("values") or {}),
                                       "overrides": len(_snap.get("overrides")
                                                        or {})}})
            except Exception as _se:
                self._json({"ok": False,
                            "err": "快照导出失败：%s" % str(_se)[:120]}, 500)
        elif self.path.split("?")[0] == "/api/err-codes":
            # r1179：错误码对照表（码 → 人话 → 三个动作）。前端只渲染，不自己写说法。
            try:
                from core import err_codes as _ec
                self._json({"ok": True, "kinds": _ec.KIND_CN,
                            "rows": _ec.table()})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/update/status":
            # r1197：更新闭环的只读状态（页面据此显示版本/进度/备份数）。
            try:
                self._json(_update_status())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/update/start":
            try:
                self._json(_update_start_async())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/update/rollback":
            try:
                from core import update as _up
                rep = _up.rollback()
                rep["ok"] = bool(rep.get("ok"))
                self._json(rep)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/three-rates":
            # r1183：三率一险（爬取率/效率/速度/风险）。数字只从 core.rates 出，
            # 那里与 core.baseline 共用同一份 SQL——页面不许自己再算一遍。
            try:
                from urllib.parse import urlparse as _u3, parse_qs as _q3
                from core import rates as _rt
                _q3v = _q3(_u3(self.path).query)
                _h3 = int((_q3v.get("hours") or ["12"])[0] or 12)
                # r1421：演示实例没有真库，`snapshot()` 会返回空表——公开演示页
                # 与 CI 的「三率一险」卡片就成了空壳（也让依赖"有行"的门禁在干净
                # 环境必红）。演示态改走合成快照，并带 demo: True 标识。
                if DEMO["on"]:
                    self._json(_rt.demo_snapshot(hours=_h3))
                else:
                    _sn3 = _rt.snapshot(hours=_h3)
                    # r1731：把「人工停手」一并下发。停手期间历史成功率照旧
                    # 好看（窗口内是停手之前的样本），不标出来就会被当现状。
                    try:
                        import time as _ht3
                        from core.policy import read_halt as _rh4
                        _hn3 = _ht3.time()
                        _hs3 = {}
                        for _hp3 in set(list(_sn3.get("by_plat") or {})):
                            _rc3 = (_rh4(_policy_engine(_hp3).base_dir)
                                    or {}).get(_hp3) or {}
                            try:
                                _u3b = float(_rc3.get("until") or 0)
                            except (TypeError, ValueError):
                                _u3b = 0.0
                            if _u3b > _hn3:
                                _hs3[_hp3] = {
                                    "left_s": int(_u3b - _hn3),
                                    "note": str(_rc3.get("note") or ""),
                                }
                        _sn3["halts"] = _hs3
                    except Exception:
                        _sn3["halts"] = {}
                    self._json(_sn3)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/err-codes/explain":
            try:
                from urllib.parse import urlparse as _ue, parse_qs as _qe
                from core import err_codes as _ec
                _q = _qe(_ue(self.path).query)
                _txt = (_q.get("text") or [""])[0]
                self._json({"ok": True, "result": _ec.explain(_txt)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/strategy":
            # `GET /api/strategy`（Spec §6(c)，r1063 T12a）：**只读**目录视图。
            # 目录 + 当前生效值 + 来源 + 十五轴矩阵 + 停手表，界面与 CLI
            # （`python -m core.strategy_contract`）取的是**同一份** `audit()`：
            # 这里不另算一套结论，「界面说绿、CLI 说红」是最难查的一类不一致。
            # 写路径不在这里也不新增：参数编辑走 `POST /api/config` 的 `glb`
            # 整表，停/恢复走 `/api/strategy/{halt,resume}`。
            try:
                from core import strategy_contract as _strat
                out = _strategy_payload()
                # 矩阵段单独兜：审计要通读 4.4MB 的 webui.py 与全量生产源码，
                # 它炸了不该把目录段一起丢掉（面板至少还能看和改参数）。
                try:
                    _rows, _matrix = _strategy_audit_cached()
                except Exception as _ae:
                    out["errors"]["matrix"] = ("十五轴矩阵求值失败：%s"
                                               % str(_ae)[:80])
                    out["matrix"] = []
                    out["defects_n"] = None
                else:
                    # 聚合在契约里（`_cells`/`matrix`），与 matrix_text 同源；
                    # 这里把已算好的行传进去，一条 3000 格的审计不跑两遍。
                    out["matrix"] = _matrix
                    out["defects_n"] = len({(r.sid, r.axis) for r in _rows
                                            if r.state == "n"})
                self._json(out)
            except Exception as e:
                self._json({"ok": False,
                            "err": "策略目录接口失败：%s" % str(e)[:120]}, 500)
        elif self.path.split("?")[0] == "/api/insight":
            # r1063 T266：把 --ms / --dist 两个诊断视图搬进浏览器（只读）。
            try:
                from urllib.parse import parse_qs, urlparse
                _qs = parse_qs(urlparse(str(getattr(self, "path", ""))).query)
                _view = (_qs.get("view") or ["ms"])[0]
                _h = int((_qs.get("hours") or ["24"])[0])
                from core import channel_matrix as _cm
                if _view == "dist":
                    _txt, _title = _cm.dist_table(_h), "距离分桶成功率"
                else:
                    _txt = _cm.ms_table(_h, 14)
                    _title = "通路耗时（近 %d 小时）" % _h
                self._json({"ok": True, "view": _view, "title": _title,
                            "lines": [x for x in str(_txt).splitlines()
                                      if x.strip()]})
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:160]}, 500)
        elif self.path.split("?")[0] == "/api/update/check":
            # r1063 T251：检测更新（只读，6 小时缓存）。issue #15 里用户
            # 直接问"更新要卸载重装吗" —— 说明这个能力一直缺失。
            # r1063 T265：**必须容忍 `?force=1`**——只比裸路径会漏匹配，
            # 前端拿到空响应，报 `Unexpected end of JSON input`（真机踩过）。
            try:
                from core import update as _upd
                _q = str(getattr(self, "path", "") or "")
                _force = "force=1" in _q
                self._json(_upd.check(force=_force, timeout=6.0))
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:160]}, 500)
        elif self.path == "/api/pacing":
            try:
                if DEMO["on"]:
                    self._json(_demo_pacing_payload())
                    return
                pac = getattr(_State, "pacing", None)
                if pac is None:
                    self._json({"ok": False,
                                "err": "节流未挂接（扫描任务尚未初始化）"}, 503)
                    return
                data = pac.snapshot()
                # r1614：把**人工停手**并进每个渠道。停手期间 breaker 的 state
                # 仍是 ok，页面就只能写「正常」——用户看不出它被停掉、更看不到
                # 还剩多久（今天给携程/飞猪设 12h 停手后就是这样）。
                # 停手是运行期干预，权威来源只有 core.policy 的 strategy_halt.json。
                try:
                    import time as _ht
                    from core.policy import read_halt as _rh2
                    _hn = _ht.time()
                    _hch = data.setdefault("channels", {})
                    # snapshot() 只含 7 条（有 breaker 记录的那些）；App 渠道
                    # 常常不在里面，而它们的行照样要显示停手——所以按全渠道遍历。
                    for _hp in list(_ALL_PLATS):
                        _hrow = _hch.setdefault(_hp, {})
                        _rec2 = (_rh2(_policy_engine(_hp).base_dir)
                                 or {}).get(_hp) or {}
                        try:
                            _hu = float(_rec2.get("until") or 0)
                        except (TypeError, ValueError):
                            _hu = 0.0
                        _hrow["halt"] = ({"until": _hu,
                                          "left_s": max(0, int(_hu - _hn)),
                                          "note": str(_rec2.get("note") or "")}
                                         if _hu > _hn else None)
                except Exception:
                    pass
                # r1063 T194：auto 诊断的结论随同一份载荷下发（面板直接渲染，
                # 不再多发一次请求，避免卡片与建议对不上）。
                try:
                    from core.advise import top_from_pacing as _tfp
                    from core.advise import weak_paths as _wp
                    data["advice_top"] = _tfp(data)
                    # 注意：weak_paths 不在这里算——`channels[].paths` 是下面
                    # "与路径账合并"之后才有的，此处为空（r1063 T198 实测）。
                except Exception:
                    data["advice_top"] = []
                # 建议引擎（该等还是该干预）：与路径账合并后才说得准
                try:
                    from core.pacing import advise
                    _ps = (_paths_payload(24).get("platforms") or {})
                    _scene = getattr(_State, "scene", None) or {}
                    _eff = {}
                    _rec = []
                    try:
                        _dbp3 = _anchored(
                            ((_State.cfg or {}).get("output") or {}).get(
                                "db_path"), "data/prices.db")
                        if os.path.isfile(_dbp3):
                            _rec = PriceStorage(_dbp3).failure_recurrence(24, 3)
                    except Exception:
                        _rec = []
                    try:
                        from core.pacing import failure_kind
                        for _r in _rec:
                            _lbl, _act, _auto = failure_kind(_r.get("kind"))
                            _r["kindLabel"] = _lbl
                            _r["advice"] = _act
                            _r["autoHeal"] = bool(_auto)
                    except Exception:
                        pass
                    data["recurrences"] = _rec
                    try:
                        _dbp2 = _anchored(
                            ((_State.cfg or {}).get("output") or {}).get(
                                "db_path"), "data/prices.db")
                        if os.path.isfile(_dbp2):
                            _pst = PriceStorage(_dbp2)
                            # 干预成效必须覆盖**本次载荷里的每个渠道**：
                            # 写死浏览器五家时，App 渠道即使干预成功也拿不到
                            # effect（面板上永远没有「上次干预」）。
                            _p0s = (set((data.get("channels") or {}).keys())
                                    | set(_LOGIN_PLATS) | set(_APP_CHANNELS))
                            for _p0 in sorted(_p0s):
                                _eff[_p0] = _pst.intervention_effect(_p0, 24)
                            # 干预成功率（r484）：按动作回答「按哪个钮真有用」。
                            # 原始需求点名要这个指标；此前只有「上一次干预前后
                            # 对比」，答不了「这类干预一共 12 次、几次真救回来」。
                            data["iv_rate"] = _pst.intervention_success_rate()
                    except Exception:
                        _eff = {}
                    for _p, _ch in (data.get("channels") or {}).items():
                        # 全窗口无记录时 `path_stats` 可能整个不含该渠道，
                        # `node` 就是空 dict，`advise` 只能判「待首轮」。补齐
                        # 该渠道**全表**最近样本时刻，才能说出「采集停了」
                        # （r516，用户反馈「登录都配好了但渠道全红」）。
                        _nd = dict(_ps.get(_p) or {})
                        if not _nd.get("last_seen_at"):
                            try:
                                _nd["last_seen_at"] = _last_seen_of(
                                    _p) or ""
                            except Exception:
                                pass
                        # r1649：停手中——只说「停着、还剩多久、怎么恢复」，
                        # 不再给 probe/route 这类「去做点什么」的建议。
                        _hrow2 = _hch.get(_p) or {}
                        _hrow3 = _hrow2.get("halt") or {}
                        _hl = _hrow3.get("left_s")
                        if _hl:
                            # r1783：把**停手理由**与**可读时长**说出来。
                            # 原来只写「剩 10079 分钟」，理由被丢掉——用户看不出为什么。
                            _mins = max(1, int(_hl / 60))
                            if _mins >= 48 * 60:
                                _dur = "%d 天" % max(1, round(_mins / 1440))
                            elif _mins >= 120:
                                _dur = "%d 小时" % max(1, round(_mins / 60))
                            else:
                                _dur = "%d 分钟" % _mins
                            _note = str(_hrow3.get("note") or "").strip()
                            _ch["advice"] = {
                                "state": "halted", "action": "resume",
                                "severity": "wait",
                                "hint": (
                                    ("人工停手中：%s · 剩 %s（到期自动恢复，"
                                     "或点「恢复」）" % (_note, _dur))
                                    if _note else
                                    ("人工停手中，剩 %s（到期自动恢复，"
                                     "或点「恢复」）" % _dur)),
                                "eta_s": int(_hl)}
                            continue
                        _rr2 = _retired_reason(_p)
                        if _rr2:
                            _ch["advice"] = {
                                "state": "retired", "action": "none",
                                "severity": "ok",
                                "hint": ("%s：该通路已停止服务，已从采集"
                                         "里移除，无需勾选" % _rr2),
                                "eta_s": 0}
                            continue
                        _ch["advice"] = advise(
                            _p, _ch, _ps.get(_p, {}).get("paths") or {},
                            node=_nd,
                            quiet=data.get("quiet") or {},
                            enabled=_enabled_plats())
                        # 通路维度回传（r416）：同一厂商内 PC/H5/日历/窗历
                        # 是不同通路，各自成功率与退役状态本来就是分开记的
                        # （path_stats），此前只在 hint 文本里露一角，面板
                        # 看不到。这里只挑面板用得上的字段，避免把整个
                        # path_stats 塞进每 10s 的轮询响应。
                        _node = _ps.get(_p) or {}
                        # 会话可用窗口（r1063 T94）：量化"登录后能用多久"。
                        # 只回结构化字段，前端要不要显示由它决定。
                        try:
                            from core import session_window as _sw
                            _session = _sw.summary(_ud_root(), _p)
                        except Exception:
                            _session = {}
                        if _session:
                            _ch["session"] = _session
                        _paths = {}
                        for _pn, _pv in (_node.get("paths") or {}).items():
                            _paths[_pn] = {
                                "rate": _pv.get("rate"),
                                "attempts": _pv.get("attempts"),
                                "last_ok_at": _pv.get("last_ok_at"),
                                "why": _pv.get("last_why") or "",
                            }
                        if _paths:
                            _ch["paths"] = _paths
                            _ch["retired_paths"] = list(
                                _node.get("retired_paths") or [])
                        _ch["scene"] = _scene.get(_p) or {}
                        _e = _eff.get(_p) or {}
                        if _e.get("has"):
                            try:
                                from core.pacing import effect_verdict
                                _st0, _hint, _sev = effect_verdict(_e)
                                _ch["effect"] = {
                                    "state": _st0, "hint": _hint,
                                    "severity": _sev,
                                    "before": _e.get("before"),
                                    "after": _e.get("after"),
                                    "action": _e.get("action"),
                                    "after_n": _e.get("after_n"),
                                }
                                # 干预已见效时，不要再让 chip 同时说
                                # "路径劣化"：旧 24h 样本仍含失败，但结论
                                # 已被干预后的新样本推翻。改为"恢复中"，
                                # 并保留"再观察一轮"的诚实口径。
                                if (_st0 in ("improved", "recovered")
                                        and (_ch.get("advice") or {})
                                        .get("state") in
                                        ("path_degraded", "degraded")):
                                    _ch["advice"] = {
                                        "state": "recovering",
                                        "action": "watch",
                                        "severity": "ok" if _st0 ==
                                        "recovered" else "wait",
                                        "eta_s": 0,
                                        "hint": _hint + "；旧 24h 样本仍含"
                                                "干预前失败，下一轮自然转正常",
                                    }
                            except Exception:
                                pass
                except Exception as _ae:
                    _State.logger.warning("[建议] 生成失败: %s", _ae)
                data["ok"] = True
                # r1063 T198：弱环必须**在 paths 合并之后**算（见上）。
                # 口径在 core.advise.weak_paths（能力边界/退役/样本量/天花板）。
                try:
                    from core.advise import weak_paths as _wp2
                    data["weak_paths"] = _wp2(data)
                    # 日历覆盖（r1063 T219）：面板一行看到"每家覆盖多少天"
                    try:
                        from core.advise import date_cover as _dcv
                        data["date_cover"] = _dcv(12, 6)
                    except Exception:
                        data["date_cover"] = []
                    # r1063 T268：结构性建议——"这家近端能成、远端明显不行"
                    # （今天两次靠人工跑分桶才发现，现在由系统自己说）
                    try:
                        from core.advise import distance_advice as _da2
                        # r1063 T274：阈值可配置（不配＝代码默认，零配置可用）
                        _cc = _effective_crawler_config() or {}
                        try:
                            _mn = int(_cc.get("advice_distance_min_n") or 6)
                        except Exception:
                            _mn = 6
                        try:
                            _gp = float(_cc.get("advice_distance_gap") or 0.25)
                        except Exception:
                            _gp = 0.25
                        data["distance_advice"] = _da2(
                            24, min_n=max(1, min(_mn, 200)),
                            gap=max(0.05, min(_gp, 0.95)))
                    except Exception:
                        data["distance_advice"] = []
                    # r1063 T265：**永远**带当前版本（用户要看得见自己在跑什么）
                    try:
                        import main as _m2
                        data["version"] = str(getattr(_m2, "__version__", ""))
                    except Exception:
                        data["version"] = ""
                    # r1063 T251：有新版本/新构建才下发 update
                    try:
                        from core.update import check as _upd_check
                        _u = _upd_check(timeout=3.0)
                        if _u.get("ok") and _u.get("has_update"):
                            data["update"] = {
                                "latest": _u.get("latest"),
                                "reason": _u.get("reason"),
                                "url": _u.get("url"),
                            }
                    except Exception:
                        pass
                except Exception:
                    data.setdefault("weak_paths", [])
                self._json(data)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/exit-check"):
            try:
                self._json(_exit_check())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/login-phase":
            # 登录阶段轮询（轻量 GET）：只读内存里的 session 阶段，
            # 不走 _login_state_view（那个要算健康证据，代价大）。
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                _slot = str((_q.get("slot") or [""])[0] or "")
                self._json(_login_phase_view(_slot))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/state":
            try:
                # body/etag/gz 同锁快照一次取齐，304 判定不再撕裂
                body, etag, gz = _latest_state_snap()
                # 轮询 304：响应未变时浏览器连 370KB 的下载都省掉
                if (etag and etag == self.headers.get("If-None-Match", "").strip()):
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Vary", "Accept-Encoding")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("ETag", etag)
                # gzip：462KB 级载荷压到 ~60KB（缓存内随 body 一次性压缩）
                if "gzip" in (self.headers.get("Accept-Encoding") or "") and gz:
                    body = gz
                    self.send_header("Content-Encoding", "gzip")
                    self.send_header("Vary", "Accept-Encoding")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json({"err": str(e)}, 500)
        elif self.path.startswith("/api/channel-links"):
            try:
                from urllib.parse import parse_qs as _pqs
                from urllib.parse import urlparse as _up2
                from core.channel_links import channel_links as _chlinks
                _q = _pqs(_up2(self.path).query)
                _fv = (_q.get("from") or [""])[0]
                _tv = (_q.get("to") or [""])[0]
                _dv = (_q.get("date") or [""])[0]
                _fn = (_q.get("from_name") or [""])[0]
                _tn = (_q.get("to_name") or [""])[0]
                self._json(_chlinks(_fv, _tv, _dv, _fn, _tn))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/health":
            try:
                if DEMO["on"]:
                    out = _demo_health_payload()
                    # 只有在线 demo 才补真实槽位；静态烘焙不读本机登录态。
                    global _IN_HEALTH_DECORATE
                    _prevd = _IN_HEALTH_DECORATE
                    _prevd_tid = getattr(_IN_HEALTH_DECORATE_TID, "ident", None)
                    _IN_HEALTH_DECORATE = True
                    _IN_HEALTH_DECORATE_TID.ident = threading.get_ident()
                    try:
                        _attach_diag_slots(out)
                    finally:
                        _IN_HEALTH_DECORATE = _prevd
                        if _prevd_tid is None:
                            try:
                                del _IN_HEALTH_DECORATE_TID.ident
                            except AttributeError:
                                pass
                        else:
                            _IN_HEALTH_DECORATE_TID.ident = _prevd_tid
                    out["device_lock"] = _device_lock_view({})
                    self._json(out)
                else:
                    _hp = _health_state()
                    # 健康卡空态的「停摆」判断（r517）：`rounds` 为空时前端
                    # 分不出「从未采集」和「采集停了」，会一律写
                    # 「完成一轮采集后会出现时间线」——而节流行此时可能已经
                    # 写着「采集停了」。补一个整库最近采集时刻给它。
                    try:
                        _hdb = _anchored(
                            ((_State.cfg or {}).get("output") or {}).get(
                                "db_path"), "data/prices.db")
                        if os.path.isfile(_hdb):
                            with sqlite3.connect(_hdb) as _hc:
                                _hr = _hc.execute(
                                    "SELECT MAX(fetched_at) FROM fetch_paths"
                                ).fetchone()
                            _hp["last_seen_at"] = str(
                                (_hr or [""])[0] or "")
                        else:
                            _hp["last_seen_at"] = ""
                    except Exception:
                        _hp["last_seen_at"] = ""
                    _hp["enabled_platforms"] = _enabled_platforms()
                    _hp["device_lock"] = _device_lock_view(_State.cfg or {})
                    self._json(_hp)
            except Exception as e:
                self._json({"err": str(e)}, 500)
        elif self.path == "/api/channel-dims":
            # 能力矩阵只在 core/channels.py 里声明，界面和
            # 测试都读不到——「App 对齐 PC/H5 每个维度」
            # 就无从核实。只读不写：无侧作用。
            try:
                from core.channels import channel_dims_payload
                self._json(channel_dims_payload())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.split("?")[0] == "/api/multicity":
            # 多程整单总价只读面：只读 itinerary_daily，库/表缺失返回
            # 空态而不是 500，界面才能把「没样本」和「读失败」分开。
            try:
                from urllib.parse import parse_qs as _pqs
                from urllib.parse import urlparse as _up3
                _q = _pqs(_up3(self.path).query)
                self._json(_multicity_payload(
                    route_id=(_q.get("route_id") or [""])[0],
                    segments_key=(_q.get("segments_key") or [""])[0],
                    limit=(_q.get("limit") or ["200"])[0],
                    with_history=(_q.get("history") or [""])[0]
                    in ("1", "true", "yes")))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/pulse":
            try:
                if DEMO["on"]:
                    from core.demo import demo_pulse
                    self._json(demo_pulse())
                else:
                    from core.pulse import PULSE
                    _pv = PULSE.view()
                    # r1716：静默窗要摆在页面上。01:00–07:00 期间不采集，
                    # 页面若只说「最后更新 3 小时前」，没人分得清是静默还是坏了。
                    try:
                        _pac2 = getattr(_State, "pacing", None)
                        if _pac2 is not None:
                            _pc2 = getattr(_pac2, "cfg", {}) or {}
                            _pv["quiet"] = {
                                "start": str(_pc2.get("scan_quiet_start")
                                             or ""),
                                "end": str(_pc2.get("scan_quiet_end") or ""),
                                "active": bool(_pac2.quiet_now()),
                                "left_s": int(_pac2.seconds_until_quiet_end()
                                               or 0),
                            }
                    except Exception:
                        pass
                    self._json(_pv)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/pushlog":
            try:
                if DEMO["on"]:
                    # 样例与现役推送格式同步（#### 标题/四档图例「真达标」/
                    # 🎯-低-差口径、撤超线仪表条后行1=差价百分比）；旧
                    # 🟦超线 图例样例曾误导预览（随仪
                    # 表条撤除一并下架）
                    self._json({"ok": True, "items": [
                        {"ts": "2026-09-10 09:00:02", "ok": True,
                         "ch": "dingtalk",
                         "title": "🚨 达标！乌→上 10/04 直飞￥1580｜另监控 乌→上 10/05",
                         "desp": "#### 🚨 已达标——可出手\n\n"
                                 "> ⏱09:00 🎯真达标 🟩破线 🟨擦边 超线\n\n"
                                 "#### ✈️ 上海→乌鲁木齐 10/04\n\n"
                                 "[**🎯 直飞 ￥1580**](https://example.com)"
                                 "　线￥1600　低￥20·1%\n\n"
                                 "国航CA1295 21:10-02:35(+1天)\n\n"
                                 "> 经济舱 · 行李直挂\n\n"
                                 "> 💡 直飞 真达标 低￥20，建议出手\n\n"
                                 "> 📉 近7天 直飞 ↓3%"},
                        {"ts": "2026-09-10 08:45:03", "ok": True,
                         "ch": "email",
                         "title": "❌ 全部未达标｜最近 上→乌 09/25 直飞差￥570｜另监控 上→乌 09/26",
                         "desp": "#### ❌ 1 条航线 2 个日期全部未达标\n\n"
                                 "直飞 ￥2470　线￥1900　差￥570（30%）\n\n"},
                        {"ts": "2026-09-10 08:30:00", "ok": False,
                         "ch": "dingtalk",
                         "errcode": -1,
                         "title": "❌ 全部未达标｜上→乌 09/25",
                         "desp": "#### ❌ 1 条航线全部未达标\n\n"},
                        {"ts": "2026-09-10 08:15:00", "ok": False,
                         "ch": "dingtalk",
                         "errcode": -2,
                         "title": "❌ 全部未达标｜上→乌 09/25",
                         "desp": "#### ❌ 1 条航线全部未达标\n\n"},
                    ]})
                    return
                import os as _os
                items = []
                p = _anchored(None, "logs/push_history.jsonl")
                try:
                    size = _os.path.getsize(p)
                    with open(p, "rb") as f:
                        if size > 262144:
                            f.seek(size - 262144)
                        lines = f.read().decode(
                            "utf-8", errors="replace").splitlines()
                    if size > 262144 and len(lines) > 1:
                        lines = lines[1:]   # 首行可能被截半
                    for ln in reversed(lines):
                        try:
                            items.append(json.loads(ln))
                        except Exception:
                            continue
                        if len(items) >= 40:
                            break
                except FileNotFoundError:
                    pass
                self._json({"ok": True, "items": items})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/radar/history"):
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                qs = _pq(_up(self.path).query)
                user = (qs.get("user") or [""])[0].strip()
                if not user:
                    self._json({"ok": False, "err": "缺少 user"}, 400)
                    return
                try:
                    days = int((qs.get("days") or ["120"])[0])
                except ValueError:
                    days = 120
                qkey = (qs.get("query_key") or [""])[0].strip()
                self._json(_radar_history(user, days, qkey))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 400)
        elif self.path.startswith("/api/radar/alert-config"):
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                qs = _pq(_up(self.path).query)
                user = (qs.get("user") or [""])[0].strip()
                if not user:
                    self._json({"ok": False, "err": "缺少 user"}, 400)
                    return
                st = PriceStorage(_radar_db_path())
                if self.command == "GET":
                    self._json({"ok": True, "user": user,
                                "config": st.radar_alert_config(user)})
                    return
                if DEMO["on"]:
                    self._json({"ok": False, "err": "演示模式不保存提醒配置"}, 400)
                    return
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站提醒配置请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("bad body")
                if str(body.get("user") or "").strip() != user:
                    raise ValueError("user 不一致")
                cfg = {
                    "enabled": bool(body.get("enabled")),
                    "drop_min": max(0.0, min(float(body.get("drop_min") or 0), 10000.0)),
                    "threshold": max(0.0, min(float(body.get("threshold") or 0), 200000.0)),
                    "cooldown_h": max(1.0, min(float(body.get("cooldown_h") or 12), 168.0)),
                }
                st.set_radar_alert_config(user, cfg)
                self._json({"ok": True, "user": user,
                            "config": st.radar_alert_config(user)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:160]}, 400)
        elif self.path.startswith("/api/radar/alerts"):
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                qs = _pq(_up(self.path).query)
                user = (qs.get("user") or [""])[0].strip()
                if not user:
                    self._json({"ok": False, "err": "缺少 user"}, 400)
                    return
                try:
                    days = int((qs.get("days") or ["30"])[0])
                except ValueError:
                    days = 30
                st = PriceStorage(_radar_db_path())
                self._json({"ok": True, "user": user,
                            "alerts": st.radar_alerts(user, days)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:160]}, 400)
        elif self.path.startswith("/api/radar/flights"):
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                qs = _pq(_up(self.path).query)
                self._json(_radar_low_flights(
                    (qs.get("from") or [""])[0],
                    (qs.get("to") or [""])[0],
                    (qs.get("date") or [""])[0]))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 400)
        elif self.path == "/api/login-state":
            try:
                if DEMO["on"]:
                    # 演示模式也必须给出 6 个会话槽位：登录卡与健康卡的
                    # 「会话维度」都按 slots 渲染，只给 plats 会静默回落到
                    # 旧的「按厂商一行」结构，把飞猪 PC/H5 双端藏掉。
                    _demo_slots = {}
                    for _k in LOGIN_SLOT_ORDER:
                        _m = LOGIN_SLOTS[_k]
                        _demo_slots[_k] = {
                            "slot": _k, "plat": _m["plat"],
                            "surface": _m["surface"],
                            "surface_label": _m["surface_label"],
                            "name": _m["name"], "account": _m["account"],
                            "requirement": _m["requirement"],
                            "profile": _m["profile"],
                            "login_url": _m["login_url"],
                            "saved": False, "saved_at": 0, "active": False,
                            "saving": False, "status": "missing", "pending": False,
                            "needs_login": False, "health_need_login": False,
                            "stale": False, "error": "", "detail": "",
                            "verified_at": "", "page_ok": False,
                            "session_verified": False, "detail_ok": False,
                        }
                    self._json({"ok": True, "demo": True,
                                "plats": {
                                    p: {"saved": False, "active": False,
                                        "stale": False, "pending": False}
                                    for p in _LOGIN_PLATS},
                                "slots": _demo_slots})
                else:
                    self._json(_login_state_view())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/channel/selfcheck":
            try:
                if DEMO["on"]:
                    self._json({"ok": False, "err": "演示模式不生成真实诊断证据"}, 400)
                    return
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站诊断请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 16384:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                plat = str((body or {}).get("plat") or "")
                if plat not in _SELFCHECK_PLATS:
                    raise ValueError("未知渠道")
                out = _health_state(24)
                card = next((c for c in (out.get("diag") or [])
                             if c.get("plat") == plat), None)
                if not card:
                    raise ValueError("诊断数据未到")
                _append_channel_evidence(card, str((body or {}).get("user") or ""))
                self._json({"ok": True, "card": card,
                            "evidence_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:160]}, 400)
        elif self.path.startswith("/api/logtail"):
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                if DEMO["on"]:
                    # 合成日志必须回放被点击格子的同一轮次/渠道：旧实现
                    # 写死 09-09 14:00 + qunar，点 10-21 17:41 的携程格
                    # 也会显示另一天另一渠道的日志（轮次身份失真）。
                    from datetime import datetime as _dt, timedelta as _td
                    _p = q.get("plat", [""])[0] or "qunar"
                    _ts = q.get("ts", [""])[0] or _dt.now().strftime("%Y-%m-%d %H:%M")
                    try:
                        _t0 = _dt.strptime(_ts, "%Y-%m-%d %H:%M")
                    except ValueError:
                        _t0 = _dt.now()
                    _f = "%Y-%m-%d %H:%M:%S"
                    self._json({"ok": True, "lines": [
                        _t0.strftime(_f) + " [INFO] ticket-monitor: ===== 开始一轮扫描（1 用户 / 3 航线） =====",
                        (_t0 + _td(seconds=17)).strftime(_f) + " [INFO] ticket-monitor: [" + _p + "] 示例采集完成：直飞 44 / 中转 26，最低价 ￥1850（DEMO 合成）",
                        (_t0 + _td(seconds=45)).strftime(_f) + " [INFO] ticket-monitor: ===== 本轮扫描结束 =====",
                    ], "plat": _p, "ts": _ts, "demo": True})
                else:
                    self._json(_log_tail(q.get("plat", [""])[0],
                                         q.get("ts", [""])[0]))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/srx/links"):
            # 检索台五渠道深链：与爬虫取数路径同源；本态不供返回空串
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                self._json(_srx_links(_q.get("from", [""])[0],
                                      _q.get("to", [""])[0],
                                      _q.get("date", [""])[0]))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/srx/health"):
            # 字段健康：raw 键可得率（非值正确率），按航线/日期现算
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                self._json(_srx_health(_q.get("from", [""])[0],
                                       _q.get("to", [""])[0],
                                       _q.get("date", [""])[0]))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/srx/flight/trend"):
            # 任意航班历史：数据来自全航线采集落库，不要求已有关注条目
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                _ch = [x for x in (_q.get("channels", [""])[0] or "").split(",")
                       if x in _WATCH_PLATS]
                _payload = {
                    "from": _q.get("from", [""])[0],
                    "to": _q.get("to", [""])[0],
                    "date": _q.get("date", [""])[0],
                    "code": _q.get("code", [""])[0],
                    "depTime": _q.get("depTime", [""])[0],
                    "arrTime": _q.get("arrTime", [""])[0],
                    "trans": _q.get("trans", [""])[0],
                    "cross": _q.get("cross", [""])[0],
                    "stop": _q.get("stop", ["0"])[0] in ("1", "true", "True"),
                    "cabin": _q.get("cabin", [""])[0],
                    "channels": _ch or list(_WATCH_PLATS),
                }
                self._json(_flight_trend(_payload,
                                         _q.get("days", ["30"])[0]))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/srx/watch/trend"):
            # 指定航班监控历史：按真实落库同航班行回放采集点/日最低，
            # 只读不写关注文件；没有点不生成假曲线。
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                self._json(_watch_trend(_q.get("user", [""])[0],
                                        _q.get("id", [""])[0],
                                        _q.get("days", ["14"])[0]))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/srx/watch"):
            # 航班关注清单：条目本身不含价格，inScope 由用户航线配置现算
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                self._json(_watch_list(_watch_user(_q.get("user", [""])[0])))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/app-login"):
            # App 渠道登录（r604）：帧是二进制 PNG，不能走 _json。
            # 复用 login_api 的路由分发，保持与测试同一套实现。
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                from core.android import login_api as _la
                _u = _up(self.path)
                _q = _pq(_u.query)
                _r = _la.dispatch(_app_login_registry(), "GET", _u.path,
                                  _q, None, _app_login_ctx())
                if isinstance(_r, tuple) and len(_r) == 3 and \
                        isinstance(_r[0], bytes):
                    _body, _code, _hdr = _r
                    if not _body:
                        self.send_response(_code)
                        for _k, _v in _hdr.items():
                            self.send_header(_k, _v)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        self.send_response(_code)
                        for _k, _v in _hdr.items():
                            self.send_header(_k, _v)
                        self.send_header("Content-Length", str(len(_body)))
                        self.end_headers()
                        self.wfile.write(_body)
                else:
                    _obj, _code = _r
                    self._json(_obj, _code)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/srx/calendar"):
            # 双轴日历：出发日真实落库 vs 采集日观测，禁止互换
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                self._json(_srx_calendar(_q.get("from", [""])[0],
                                         _q.get("to", [""])[0],
                                         _q.get("date", [""])[0],
                                         _q.get("days", ["14"])[0],
                                         axis=_q.get("axis", ["departure"])[0]))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/probe/task"):
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                q = _pq(_up(self.path).query)
                _tid = (q.get("id") or [""])[0]
                try:
                    _rf = int((q.get("rows_from") or ["0"])[0])
                except (TypeError, ValueError):
                    _rf = 0
                _v = _probe_task_view(_tid, _rf)
                if _v is None:
                    self._json({"ok": False, "err": "任务不存在或已过期"}, 404)
                else:
                    self._json(_v)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/probe/raw"):
            # 检索页“解析 ⇄ 原始行”证据端点：按 DB 行 ID + extra 下标
            # 回放当轮原始对象；只读、本地、无路径参数，不重新解析。
            try:
                from urllib.parse import urlparse as _up, parse_qs as _pq
                _q = _pq(_up(self.path).query)
                _out = _probe_raw(_q.get("row", ["0"])[0],
                                  _q.get("idx", ["0"])[0])
                self._json(_out, 200 if _out.get("ok") or
                           _out.get("err") == "row not found" else 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 400)
        elif self.path == "/api/specials":
            # 特价雷达（r320）：最近核实的特价（special_deals 留痕，
            # 与推送正交）。demo 态同表（demo 库同 SCHEMA）自然空榜。
            try:
                import sqlite3 as _sq
                import yaml as _y
                with open(_State.config_path, encoding="utf-8") as _yf:
                    _cfg = _y.safe_load(_yf) or {}
                _db = (_cfg.get("output") or {}).get(
                    "db_path", "data/prices.db")
                if not os.path.isabs(_db):
                    _db = os.path.join(_ROOT, _db)
                conn = _sq.connect(_db)
                conn.row_factory = _sq.Row
                try:
                    rows = [dict(r) for r in conn.execute(
                        "SELECT src,from_city,to_city,depart_date,ret_date,"
                        "ret_price,src_price,price,fetched_at "
                        "FROM special_deals ORDER BY id DESC LIMIT 10")]
                finally:
                    conn.close()
                from core.specials import (SPECIAL_CAPABILITY,
                                           special_deal_link)
                for _r in rows:
                    _r["url"] = special_deal_link(
                        _r.get("src"), _r.get("from_city"),
                        _r.get("to_city"), _r.get("depart_date"),
                        _r.get("ret_date") or "")
                    # 源 id ≠ 渠道 id：tuniucal 是途牛渠道，其余 App 源就是
                    # 渠道 id。直接回填 src 会让 tuniucal 在行首变成无图标
                    # 裸 id（审计 P2）。
                    _r["plat"] = {
                        "tuniu": "tuniu", "tuniucal": "tuniu",
                        "ctrip": "ctrip", "ctripbd": "ctrip",
                        "fliggy": "fliggy", "qunar": "qunar",
                        "tongcheng": "tongcheng",
                        "app_qunar": "app_qunar",
                        "app_zhixing": "app_zhixing",
                        "app_ctrip": "app_ctrip",
                        "app_tongcheng": "app_tongcheng",
                    }.get(str(_r.get("src") or ""),
                          str(_r.get("src") or ""))
                self._json({"ok": True, "deals": rows,
                            "capabilities": SPECIAL_CAPABILITY})
            except Exception as e:
                # 能力声明不依赖 special_deals 表是否已建/可读：库异常时
                # 也要下发，否则雷达勾选区只剩「渠道能力 · 」空标题。
                from core.specials import SPECIAL_CAPABILITY as _SC
                self._json({"ok": False, "deals": [],
                            "capabilities": _SC, "err": str(e)})
        elif self.path.startswith("/api/trend"):
            # 半年走势（r320b）：长窗日桶双系列懒加载（/api/state 不背
            # 半年体积）；days 白名单钳制在 _trend_payload 单源
            try:
                from urllib.parse import urlparse, parse_qs as _pq
                _q = _pq(urlparse(self.path).query)
                self._json(_trend_payload(_q))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/path-check"):
            # 路径目标预检（r342 迁移可视化）：只读元数据，不创建目录、
            # 不写文件；生产/演示同端点（GET 无副作用，不受 demo 只读门）
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                kind = (q.get("which") or [""])[0]
                raw = (q.get("path") or [""])[0]
                if kind not in _STORAGE_SPECS:
                    self._json({"ok": False, "err": "未知存储项"})
                    return
                meta = _demo_neutral_path(
                    _path_meta(kind, raw, _State.cfg or {}))
                cur = _demo_neutral_path(_path_meta(
                    kind, _storage_raw(_State.cfg or {}, kind),
                    _State.cfg or {}))
                meta["current_abs"] = cur.get("abs")
                # 「当前配置里填的是**字面值**」与「它的实际生效目录」并列下发
                # （r1063 T10 复核）：迁移预案里的 `from` 必须是生效目录
                # （采集器正在写的那个），而用户需要看到自己填的 `user_data`
                # 为什么等于另一个绝对路径——只给一个就会与输入框互相打脸。
                meta["current_literal"] = str(_storage_raw(
                    _State.cfg or {}, kind) or "")
                meta["current_source"] = cur.get("source") or ""
                meta["same_as_current"] = bool(
                    meta.get("abs") == cur.get("abs"))

                # 文件类型不允许落在已有目录；目录类型不允许落在已有文件
                typ = meta.get("type")
                valid, warn = True, ""
                if meta.get("invalid"):
                    valid, warn = False, meta["invalid"]
                if valid:
                    for _ok in _STORAGE_SPECS:
                        if _ok == kind:
                            continue
                        _om = _demo_neutral_path(_path_meta(
                            _ok, _storage_raw(_State.cfg or {}, _ok),
                            _State.cfg or {}))
                        if _om.get("abs") and _om.get("abs") == meta.get("abs"):
                            valid, warn = False, (
                                "与「%s」路径相同，请换一个位置"
                                % (_om.get("label") or _ok))
                            break
                if valid and typ == "file" and meta.get("exists") \
                        and meta.get("is_dir"):
                    valid, warn = False, "目标是目录——数据库/日志须为文件路径"
                elif valid and typ == "dir" and meta.get("exists") \
                        and not meta.get("is_dir"):
                    valid, warn = False, "目标是文件——该配置须为目录路径"
                elif valid and not meta.get("parent_exists"):
                    if meta.get("creatable"):
                        valid, warn = True, "父目录尚不存在，保存重启时会自动创建"
                    else:
                        valid, warn = False, "父目录尚不存在且最近祖先不可写，请换一个位置"
                elif valid and not meta.get("parent_writable"):
                    valid, warn = False, "父目录不可写，请换一个位置"
                elif valid and meta.get("exists") and not meta.get("writable"):
                    valid, warn = False, "目标已存在但不可写，请换一个位置"
                meta["valid"] = bool(valid)
                meta["warning"] = warn
                # 启动迁移预案：db/user_data 启动时整档搬迁；日志/内核
                # 目录不搬迁（切换后新位置生效、旧档保留——如实展示，
                # 不让「可迁移」承诺覆盖未迁移项）
                _mode = "none" if meta.get("same_as_current") else (
                    "move" if kind in ("db", "ud") else (
                        "new_file" if kind == "log" else "switch_only"))
                meta["migration_mode"] = _mode
                if _mode == "move":
                    meta["migration"] = {
                        # 源是**实际生效**目录：`main.py` 搬迁时用的是
                        # session_root（启动已固定），不是配置里的字面值
                        "from": cur.get("abs") or "",
                        "from_literal": str(cur.get("configured") or ""),
                        "to": meta.get("abs") or "",
                        "source_exists": bool(cur.get("exists")),
                        "target_exists": bool(meta.get("exists")),
                        "will_move": bool(cur.get("exists"))
                        and not meta.get("exists"),
                        "conflict": bool(meta.get("exists"))}
                    _demo_neutral_path(meta["migration"])
                self._json(meta)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/config":
            try:
                if DEMO["on"]:
                    # 演示模式不回读真实 config.yaml（webhook/secret 不落页面）。
                    # 航线/日期复用演示数据单源（core.demo.demo_routes 滚动
                    # 日期）——日期硬编码曾与演示数据脱节，配置页航线摘要
                    # 与监控/走势/明细各视图互相矛盾且随时间越来越旧；
                    # globals.port 随实际 --port（_State.cfg 由 demo_cfg 写入）
                    self._json(_demo_config_payload())
                    return
                import yaml as _y
                with open(_State.config_path, encoding="utf-8") as _yf:
                    cfg = _y.safe_load(_yf)
                # 物化生效值：win_toast 缺省即开启——补写显式布尔，让配置页
                # 勾选态与 config.yaml 都反映真实状态（所见即所存）
                for u0 in (cfg.get("users") or []):
                    n0 = u0.get("notifier") or {}
                    n0["win_toast"] = bool(n0.get("win_toast", True))
                    u0["notifier"] = n0
                from wizard import CITY
                self._json({"users": cfg.get("users") or [],
                            "city": CITY,
                            "cityx": _cityx(), "airline_alias": _airalias(),
                            "intl": _intl_payload(),
                            "globals": {
                                "interval_minutes": int(
                                    (cfg.get("schedule") or {}).get(
                                        "interval_minutes", 30) or 30),
                                "jitter_minutes": int(
                                    (cfg.get("schedule") or {}).get(
                                        "jitter_minutes", 0) or 0),
                                # 1 区 · 夜间静默窗（只管抓取，区别于
                                # notifier.quiet_* 的"只停推送"）
                                "scan_quiet_start": str(
                                    (cfg.get("schedule") or {}).get(
                                        "scan_quiet_start", "") or ""),
                                "scan_quiet_end": str(
                                    (cfg.get("schedule") or {}).get(
                                        "scan_quiet_end", "") or ""),
                                # 3 区 · 两级 TTL：贴近阈值走快层，远离走慢层
                                "fast_ttl_min": int(
                                    (cfg.get("schedule") or {}).get(
                                        "fast_ttl_min", 15) or 15),
                                "slow_ttl_min": int(
                                    (cfg.get("schedule") or {}).get(
                                        "slow_ttl_min", 120) or 120),
                                "near_ratio": float(
                                    (cfg.get("schedule") or {}).get(
                                        "near_ratio", 0.15) or 0.15),
                                # 5 区 · 起跑错峰 + 令牌桶
                                "stagger_seconds": int(
                                    (cfg.get("schedule") or {}).get(
                                        "stagger_seconds", 0) or 0),
                                "min_gap_s": float(
                                    ((cfg.get("crawler") or {}).get("rate")
                                     or {}).get("min_gap_s", 0) or 0),
                                "per_minute": int(
                                    ((cfg.get("crawler") or {}).get("rate")
                                     or {}).get("per_minute", 0) or 0),
                                # L1/L3 · 首页预热（每轮每渠道一次）
                                "warmup_enabled": bool(
                                    ((cfg.get("crawler") or {}).get("warmup")
                                     or {}).get("enabled", True)),
                                "warmup_platforms": ", ".join(
                                    [x for x in (
                                        ((cfg.get("crawler") or {}).get(
                                            "warmup") or {}).get("platforms")
                                        or ["qunar", "fliggy", "tuniu"])
                                     if x in _warmable()]),
                                # 没有预热入口、被忽略的项（r627）：界面要能
                                # 说「这几家填了也不会预热」，而不是静默丢弃。
                                "warmup_ignored": [
                                    x for x in (
                                        ((cfg.get("crawler") or {}).get(
                                            "warmup") or {}).get("platforms")
                                        or [])
                                    if x not in _warmable()],
                                "warmable": list(_warmable()),
                                # 2 区 · 熔断
                                "breaker_enabled": bool(
                                    ((cfg.get("crawler") or {}).get("breaker")
                                     or {}).get("enabled", True)),
                                "health_penalty_enabled": bool(
                                    (cfg.get("crawler") or {}).get(
                                        "health_penalty_enabled", True)),
                                # 成功率保护阈值（r487）：**必须回读**。
                                # 只写不回读时，配置页渲染的是默认值——
                                # 用户改完阈值再打开，看到的是 0.7/0.4/5；
                                # 随手再保存一次就把自己设的值覆盖回默认。
                                "health_min_samples": int(
                                    (cfg.get("crawler") or {}).get(
                                        "health_min_samples", 5) or 5),
                                "health_ok_ratio": float(
                                    (cfg.get("crawler") or {}).get(
                                        "health_ok_ratio", 0.7)),
                                "health_slow_ratio": float(
                                    (cfg.get("crawler") or {}).get(
                                        "health_slow_ratio", 0.4)),
                                "health_slow_factor": float(
                                    (cfg.get("crawler") or {}).get(
                                        "health_slow_factor", 1.5)),
                                "health_slowest_factor": float(
                                    (cfg.get("crawler") or {}).get(
                                        "health_slowest_factor", 3.0)),
                                "breaker_base_s": int(
                                    ((cfg.get("crawler") or {}).get("breaker")
                                     or {}).get("base_s", 300) or 300),
                                "breaker_cap_s": int(
                                    ((cfg.get("crawler") or {}).get("breaker")
                                     or {}).get("cap_s", 3600) or 3600),
                                # 仅文件可改的采集参数（r521）：这些键在采集端
                                # 真实生效（会话到期强制续期 / 并发上限 / 浏览器
                                # 指纹 / 登录窗是否可见），但配置页没有编辑控件。
                                # 只回读、不提供编辑：网页热改这些键会给人「已
                                # 生效」的错觉，实际要采集端重载。
                                "session_max_days": int(
                                    (cfg.get("crawler") or {}).get(
                                        "session_max_days", 0) or 0),
                                "max_concurrency": int(
                                    (cfg.get("crawler") or {}).get(
                                        "max_concurrency", 0) or 0),
                                "tls_impersonate": str(
                                    (cfg.get("crawler") or {}).get(
                                        "tls_impersonate", "") or ""),
                                "login_desktop": bool(
                                    (cfg.get("crawler") or {}).get(
                                        "login_desktop", False)),
                                # r523：接管原先「只能在文件里改」的其余键。
                                "mobile_user_agent": str(
                                    (cfg.get("crawler") or {}).get(
                                        "mobile_user_agent", "") or ""),
                                "debug_dir": str(
                                    (cfg.get("crawler") or {}).get(
                                        "debug_dir", "") or ""),
                                "login_cooldown_s": int(
                                    ((cfg.get("crawler") or {}).get("breaker")
                                     or {}).get("login_cooldown_s", 900) or 900),
                                "login_cooldown_max_s": int(
                                    ((cfg.get("crawler") or {}).get("breaker")
                                     or {}).get("login_cooldown_max_s",
                                               14400) or 14400),
                                "challenge_cooldown_s": int(
                                    ((cfg.get("crawler") or {}).get("breaker")
                                     or {}).get("challenge_cooldown_s",
                                               21600) or 0),
                                "near_days": int(
                                    (cfg.get("schedule") or {}).get(
                                        "near_days", 3) or 3),
                                "cadence": dict(
                                    (cfg.get("crawler") or {}).get(
                                        "cadence") or {}),
                                # Android 真机通道（r603）：此后端已真读
                                # （core/android/config.py），但配置页
                                # 一个控件都没有——用户只能改文件。
                                "android": dict(cfg.get("android") or {}),
                                "run_on_start": bool(
                                    (cfg.get("schedule") or {}).get(
                                        "run_on_start", True)),
                                "port": int((cfg.get("web") or {}).get(
                                    "port", 8765) or 8765),
                                "base_url": str(
                                    (cfg.get("web") or {}).get(
                                        "base_url", "") or ""),
                                # 上报**实际生效**的监听地址（r675）：容器里
                                # 文件没写 host、由镜像 ENV TM_WEB_HOST=0.0.0.0
                                # 生效时，旧实现按文件缺省报 127.0.0.1——
                                # 页面显示回环、服务却在全网卡；更糟的是保存
                                # 任何配置都会把这个 127.0.0.1 写回 yaml，
                                # 下次重启容器就只绑回环、-p 端口映射直接不可达。
                                "host": _bind_host(cfg),
                                "headless": bool((cfg.get("crawler") or {}).get(
                                    "headless", True)),
                                # r910/r958：拟人化与浏览器内核（原先只能改文件）
                                "humanize": bool((cfg.get("crawler") or {}).get(
                                    "humanize", True)),
                                "humanize_rounds": int(
                                    (cfg.get("crawler") or {}).get(
                                        "humanize_rounds", 2) or 2),
                                "policy_gate": bool(
                                    (cfg.get("crawler") or {}).get(
                                        "policy_gate", True)),
                                "daily_cap": int(
                                    ((cfg.get("crawler") or {}).get(
                                        "slider") or {}).get("daily_cap", 3) or 0),
                                "max_fails": int(
                                    ((cfg.get("crawler") or {}).get(
                                        "slider") or {}).get("max_fails", 2) or 2),
                                "device_distance": int(
                                    ((cfg.get("crawler") or {}).get(
                                        "slider") or {}).get(
                                            "device_distance", 260) or 260),
                                "single_shot": bool(
                                    ((cfg.get("crawler") or {}).get(
                                        "slider") or {}).get("single_shot", False)),
                                "captcha_arithmetic": bool(
                                    ((cfg.get("crawler") or {}).get(
                                        "captcha") or {}).get(
                                            "arithmetic", True)),
                                "captcha_text": bool(
                                    ((cfg.get("crawler") or {}).get(
                                        "captcha") or {}).get("text", True)),
                                "captcha_ocr_scale": float(
                                    ((cfg.get("crawler") or {}).get(
                                        "captcha") or {}).get(
                                            "ocr_scale", 3.0) or 3.0),
                                "align_display": bool(
                                    (((cfg.get("android") or {}).get(
                                        "identity") or {}).get(
                                            "align_display", True))),
                                "spoof_abi": (((cfg.get("android") or {}).get(
                                    "identity") or {}).get("spoof_abi")),
                                "browser_channel": str(
                                    (cfg.get("crawler") or {}).get(
                                        "browser_channel", "") or ""),
                                "profile_wait_s": float(
                                    (cfg.get("crawler") or {}).get(
                                        "profile_wait_s", 0) or 0),
                                "timeout_seconds": int(
                                    (cfg.get("crawler") or {}).get(
                                        "timeout_seconds", 45) or 45),
                                "delay_min": int(
                                    (cfg.get("crawler") or {}).get(
                                        "delay_min", 5) or 5),
                                "delay_max": int(
                                    (cfg.get("crawler") or {}).get(
                                        "delay_max", 15) or 15),
                                "user_agent": str(
                                    (cfg.get("crawler") or {}).get(
                                        "user_agent", "") or ""),
                                # 采集代理（r319）：空=直连；浏览器与 httpx
                                # 发现层出口统一走它（保存热生效）
                                "proxy": str((cfg.get("crawler") or {}).get(
                                    "proxy", "") or ""),
                                # 按渠道绑出口（r600）：一家被限流不牵连
                                # 另一家；空 = 该渠道回全局 proxy
                                "proxy_map": dict(
                                    (cfg.get("crawler") or {}).get(
                                        "proxy_map") or {}),
                                "debug": bool((cfg.get("crawler") or {}).get(
                                    "debug", False)),
                                # 指纹一致性（L3）：抹掉 navigator.webdriver
                                # 这类「自动化浏览器」显式标记
                                "stealth": bool((cfg.get("crawler") or {}).get(
                                    "stealth", True)),
                                # 命中人机验证时自动开窗（默认关）
                                "auto_verify": bool(
                                    (cfg.get("crawler") or {}).get(
                                        "auto_verify", False)),
                                # 内核缓存位（启动级）：空=playwright 渠道
                                # 默认位；配置后 chromium 安装与查找全部
                                # 指向该目录（重启生效）
                                "browser_dir": str(
                                    (cfg.get("crawler") or {}).get(
                                        "browser_dir", "") or ""),
                                # 启动级路径四件：可编辑（保存重启生效，
                                # 旧档启动序列自动搬迁）
                                "db_path": str(
                                    (cfg.get("output") or {}).get(
                                        "db_path", "data/prices.db")
                                    or "data/prices.db"),
                                "log_path": str(
                                    (cfg.get("output") or {}).get(
                                        "log_path", "logs/monitor.log")
                                    or "logs/monitor.log"),
                                # 配置里**填的那个字面值**（可编辑输入框的真实
                                # 内容：用户写 `user_data` 就显示 `user_data`，
                                # 不能拿生效路径覆盖他的输入，否则一保存就把
                                # 环境变量重定向固化成绝对路径）
                                "user_data_dir": str(
                                    (cfg.get("crawler") or {}).get(
                                        "user_data_dir", "user_data")
                                    or "user_data"),
                                # 绝对路径展示（r341「一切配置透明化」）：
                                # 相对=程序目录锚定解析，bdir 空=系统默认位。
                                # `ud` 给的是**实际生效**的目录（唯一口径）：
                                # 装了 `TM_USER_DATA_DIR` 时它与上面那个字面值
                                # 不同，界面上一行「→ 绝对路径」正好把「我填的」
                                # 与「实际用的」并列给用户看（r1063 T10）。
                                # T10 复核后 `storage.ud.abs` 与这里同源同值
                                # （都走 `_ud_abs`/`_ud_root`），此处只作 `glAbs`
                                # 在元数据缺失时的兜底，不再有第二个口径。
                                "globals_abs": {
                                    "db": os.path.abspath(_anchored(str(
                                        (cfg.get("output") or {}).get(
                                            "db_path", "data/prices.db")
                                        or "data/prices.db"), "")),
                                    "log": os.path.abspath(_anchored(str(
                                        (cfg.get("output") or {}).get(
                                            "log_path", "logs/monitor.log")
                                        or "logs/monitor.log"), "")),
                                    "ud": os.path.abspath(_ud_root(cfg)),
                                    "bdir": (os.path.abspath(_anchored(str(
                                        (cfg.get("crawler") or {}).get(
                                            "browser_dir", "") or ""), ""))
                                        if str((cfg.get("crawler") or {}).get(
                                            "browser_dir", "") or "").strip()
                                        else "")}},
                            # r342 一切配置可视化：路径元数据（存在/
                            # 体积/可写）、启动差量（重启中心单源）与
                            # 运行时身份（根目录/配置文件绝对路径/PID）
                            "storage": _storage_view(cfg),
                            "restart": _restart_view(cfg),
                            "runtime": _runtime_view(demo=False)})
            except Exception as e:
                self._json({"err": str(e)}, 500)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_POST(self):
        # HTTP/1.1 keep-alive：先把请求体整体读掉，再交给路由。演示只读
        # / 参数错误等早退分支若不读体，残留 JSON 会被当成下一请求行
        # （实测 501 Unsupported method '{"provider":...}GET'）。
        try:
            _n = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            _n = 0
        _raw = self.rfile.read(_n) if _n > 0 else b""
        _orig = self.rfile
        import io as _io
        self.rfile = _io.BytesIO(_raw)
        try:
            self._do_POST()
        finally:
            self.rfile = _orig

    def _do_POST(self):
        st = _State
        if DEMO["on"] and self.path != "/api/preview":
            self._json({"ok": False, "demo": True,
                        "err": "演示模式只读——下载源码或 zip 即可真跑"}, 403)
            return
        # r671：写接口统一跨站闸门。原先只有 /api/app-login 做了
        # Origin 同源校验，/api/config 与 /api/restart 谁都能调——而
        # README 教用户为了手机访问把 web.host 改成 0.0.0.0，那一刻同一
        # 局域网（或经反向代理暴露后）的任何页面都能**改配置、重启进程**。
        # 实测：带 `Origin: http://evil.example` 的 POST /api/config 回 200
        # 并真落盘，/api/restart 回 200 并真重启。
        #
        # 放在最前面：新增写接口自动继承，不必逐个记得加。GET 不受影响
        # （只读页面与 /api/state 轮询照常），演示模式已在上面短路。
        # 判定只认「带 Origin 且与 Host 不同源」——命令行 curl / 脚本
        # 不带 Origin，仍可正常调用（本机运维需要）。
        #
        # Content-Type 只在**带 body** 时要求 JSON（r671b）：`fetch(path,
        # {method:'POST'})` 不带 body 时浏览器会自动补
        # `Content-Type: text/plain`，按「非 JSON 一律 415」会把
        # 「打开文件夹 / 测试弹窗 / 立即扫描 / 重启」这些无参按钮全部
        # 打哑（实测同源调用直接 415）。无 body 的请求本来也没有可解析
        # 的载荷，CSRF 拿它也只能触发幂等动作。
        try:
            _len1 = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            _len1 = 0
        # 唯一判据源：带 body 才要求 JSON（见 _json_body_ok）。
        if not self._json_body_ok():
            return
        _org1 = self.headers.get("Origin") or ""
        if _org1:
            from urllib.parse import urlparse as _up1
            if (_up1(_org1).netloc or "") != (self.headers.get("Host") or ""):
                self._json({"ok": False, "err": "跨站请求已拒绝"}, 403)
                return
        if self.path == "/api/session/reset":
            # 手动「换一份干净档案」（r1063 T47）：用户实机验证过——清数据后又能看机票。
            # **只挪不删**：整个目录改名备份，随时可还原；我们自己的状态文件拷回新档案。
            try:
                body = self._post_json("会话重置")
                if body is None:
                    return
                plat = str((body or {}).get("plat") or "").strip()
                if not plat:
                    self._json({"ok": False, "err": "缺少 plat"}, 400)
                    return
                from core import session_reset as _sr
                root = str(_State.cfg.get("crawler", {}).get("user_data_dir")
                           or "user_data") if isinstance(_State.cfg, dict) \
                    else "user_data"
                rep = _sr.backup(plat, root, reason="manual",
                                 keep=_sr._keep_cfg(plat, 3))
                if rep.get("ok"):
                    # 记数：健康行要显示「已重建 N 次」（手动也要算）
                    _pac = getattr(_State, "pacing", None)
                    if _pac is not None:
                        try:
                            _pac.note_reset(plat)
                        except Exception:
                            pass
                self._json({"ok": bool(rep.get("ok")), "result": rep,
                            "note": "旧档案已备份；新档案是干净的浏览器身份"
                                    "（登录态会丢，需要时到「渠道登录」重登）"})
            except Exception as e:
                self._json({"ok": False, "err": "重置失败：%s" % str(e)[:120]}, 500)
        elif self.path == "/api/session/restore":
            # 还原某份备份（重置后悔药）：当前档案会被挪开，不覆盖。
            try:
                body = self._post_json("会话还原")
                if body is None:
                    return
                plat = str((body or {}).get("plat") or "").strip()
                name = str((body or {}).get("name") or "").strip()
                if not plat:
                    self._json({"ok": False, "err": "缺少 plat"}, 400)
                    return
                from core import session_reset as _sr
                root = "user_data"
                if isinstance(_State.cfg, dict):
                    root = str((_State.cfg.get("crawler", {})
                                .get("user_data_dir")) or "user_data")
                rep = _sr.restore(plat, root, name)
                self._json({"ok": bool(rep.get("ok")), "result": rep})
            except Exception as e:
                self._json({"ok": False, "err": "还原失败：%s" % str(e)[:120]}, 500)
        if self.path == "/api/config":
            # 读改写串行（r649）：并发保存会丢更新（实测两次都回 200，
            # 但 3 次里 2 次只有一项生效），热重载也可能读到半份文件。
            with _CFG_SAVE_LOCK:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    import yaml as _y
                    with open(st.config_path, encoding="utf-8") as _yf:
                        cfg = _y.safe_load(_yf) or {}
                    cfg["users"] = body.get("users") or []
                    try:
                        _normalize_mc_users(cfg["users"])
                    except ValueError as _mce:
                        # 多程形状是数据契约：坏段在这里拒绝，别等下一轮
                        # build_routes 才让整轮扫描起不来。
                        self._json({"ok": False, "err": str(_mce)}, 400)
                        return
                    glb = body.get("globals") or {}
                    if glb.get("interval_minutes"):
                        cfg.setdefault("schedule", {})["interval_minutes"] = \
                            max(5, int(glb["interval_minutes"]))
                    if glb.get("jitter_minutes") is not None:
                        cfg.setdefault("schedule", {})["jitter_minutes"] = \
                            max(0, int(glb["jitter_minutes"]))
                    # 1/3/5 区 · 节流参数（保存即热生效）：非法值一律回默认，
                    # 坏配置不能让监控整轮停摆
                    _sc0 = cfg.setdefault("schedule", {})
                    for _k in ("scan_quiet_start", "scan_quiet_end"):
                        if glb.get(_k) is not None:
                            _v = str(glb[_k]).strip()[:5]
                            if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", _v):
                                _v = ""
                            _sc0[_k] = _v
                    for _k, _d in (("fast_ttl_min", 15), ("slow_ttl_min", 120)):
                        if glb.get(_k) is not None:
                            try:
                                _v = int(glb[_k])
                            except (TypeError, ValueError):
                                _v = _d
                            _sc0[_k] = max(5, min(1440, _v))
                    if glb.get("near_ratio") is not None:
                        try:
                            _nr = float(glb["near_ratio"])
                        except (TypeError, ValueError):
                            _nr = 0.15
                        _sc0["near_ratio"] = max(0.0, min(1.0, _nr))
                    if glb.get("stagger_seconds") is not None:
                        try:
                            _sg = int(glb["stagger_seconds"])
                        except (TypeError, ValueError):
                            _sg = 0
                        _sc0["stagger_seconds"] = max(0, min(120, _sg))
                    if glb.get("port"):
                        cfg.setdefault("web", {})["port"] = \
                            max(1024, int(glb["port"]))
                    if glb.get("base_url") is not None:
                        cfg.setdefault("web", {})["base_url"] = \
                            str(glb["base_url"]).strip()[:300]
                    if glb.get("host") is not None and str(glb["host"]).strip():
                        _h = str(glb["host"]).strip()[:64]
                        try:
                            _probe = socket.socket(socket.AF_INET,
                                                   socket.SOCK_STREAM)
                            try:
                                _probe.bind((_h, 0))
                            finally:
                                _probe.close()
                        except OSError as _e:
                            self._json({"ok": False, "err": (
                                "监听地址不可用（本机没有该地址：%s）：%s"
                                % (_h, _e))}, 400)
                            return
                        cfg.setdefault("web", {})["host"] = _h
                    if glb.get("headless") is not None:
                        cfg.setdefault("crawler", {})["headless"] = \
                            bool(glb["headless"])
                    # 启动级路径三件可写（r339 用户指令「一切配置可变更化」）：
                    # 保存进 config.yaml，重启进程生效；旧档由启动序列自动搬迁
                    # 空串=显式回默认（db/log/ud 不能落空键；bdir 空=渠道默认）
                    if glb.get("db_path") is not None:
                        cfg.setdefault("output", {})["db_path"] = \
                            (str(glb["db_path"]).strip()[:300]
                             or "data/prices.db")
                    if glb.get("log_path") is not None:
                        cfg.setdefault("output", {})["log_path"] = \
                            (str(glb["log_path"]).strip()[:300]
                             or "logs/monitor.log")
                    if glb.get("user_data_dir") is not None:
                        cfg.setdefault("crawler", {})["user_data_dir"] = \
                            (str(glb["user_data_dir"]).strip()[:300]
                             or "user_data")
                    # 保存级总检（r346）：非法字符/保留名、四路径同址、
                    # 目标不可写与文件/目录错配——不能只靠前端预览。
                    _perr = _storage_save_error(cfg)
                    if _perr:
                        raise ValueError(_perr)
                    # 路径语义守卫（r342）：文件键不得指向已有目录、目录键
                    # 不得指向已有文件、库与日志不得同址——错配会在重启
                    # 迁移/启动时才炸，前端如实拦截比事后排障便宜
                    _db_abs = os.path.abspath(_anchored(str(
                        (cfg.get("output") or {}).get(
                            "db_path", "data/prices.db") or "data/prices.db"), ""))
                    _lg_abs = os.path.abspath(_anchored(str(
                        (cfg.get("output") or {}).get(
                            "log_path", "logs/monitor.log")
                        or "logs/monitor.log"), ""))
                    # 资料目录按**唯一口径**取实际生效路径（r1063 T10）：
                    # 与 `main.py` 重启后会注进采集器的是同一个判据；自己
                    # 用 `_anchored(cfg值)` 算一遍，装了 `TM_USER_DATA_DIR`
                    # 时校验的是一个重启后根本不会用的目录。
                    _ud_abs = os.path.abspath(_ud_root(cfg))
                    if os.path.isdir(_db_abs):
                        raise ValueError("数据库路径指向目录，请填文件路径（如 data/prices.db）")
                    if os.path.isdir(_lg_abs):
                        raise ValueError("日志路径指向目录，请填文件路径（如 logs/monitor.log）")
                    if os.path.isfile(_ud_abs):
                        raise ValueError("浏览器资料目录指向文件，请填目录路径")
                    _bd_raw = str((cfg.get("crawler") or {}).get(
                        "browser_dir", "") or "").strip()
                    if _bd_raw and os.path.isfile(os.path.abspath(_anchored(
                            _bd_raw, ""))):
                        raise ValueError("浏览器内核目录指向文件，请填目录路径")
                    if _db_abs == _lg_abs:
                        raise ValueError("数据库与运行日志不能使用同一路径")
                    if glb.get("run_on_start") is not None:
                        cfg.setdefault("schedule", {})["run_on_start"] = \
                            bool(glb["run_on_start"])
                    # 采集参数：rt["cfg"] 单一事实源，保存热生效（起）
                    _crw = cfg.setdefault("crawler", {})
                    # r958：拟人化/浏览器内核从此前「只能改文件」进入页面
                    if glb.get("humanize") is not None:
                        _crw["humanize"] = bool(glb["humanize"])
                    if glb.get("humanize_rounds") is not None:
                        try:
                            _hr = int(glb["humanize_rounds"])
                        except (TypeError, ValueError):
                            _hr = 2
                        _crw["humanize_rounds"] = max(1, min(6, _hr))
                    if glb.get("policy_gate") is not None:
                        _crw["policy_gate"] = bool(glb["policy_gate"])
                    _sl0 = dict(_crw.get("slider") or {})
                    for _sk, _lo, _hi, _sd in (
                            ("daily_cap", 0, 20, 3),
                            ("max_fails", 1, 10, 2),
                            ("device_distance", 40, 1000, 260)):
                        if glb.get(_sk) is not None:
                            try:
                                _sv = int(glb[_sk])
                            except (TypeError, ValueError):
                                _sv = _sd
                            _sl0[_sk] = max(_lo, min(_hi, _sv))
                    if glb.get("single_shot") is not None:
                        _sl0["single_shot"] = bool(glb["single_shot"])
                    if _sl0:
                        _crw["slider"] = _sl0
                    _cap0 = dict(_crw.get("captcha") or {})
                    if glb.get("captcha_arithmetic") is not None:
                        _cap0["arithmetic"] = bool(glb["captcha_arithmetic"])
                    if glb.get("captcha_text") is not None:
                        _cap0["text"] = bool(glb["captcha_text"])
                    if glb.get("captcha_ocr_scale") is not None:
                        try:
                            _cs = float(glb["captcha_ocr_scale"])
                        except (TypeError, ValueError):
                            _cs = 3.0
                        _cap0["ocr_scale"] = max(1.0, min(6.0, _cs))
                    if _cap0:
                        _crw["captcha"] = _cap0
                    if glb.get("browser_channel") is not None:
                        _bc = str(glb["browser_channel"]).strip().lower()
                        _crw["browser_channel"] = (
                            _bc if _bc in ("", "chrome") else "")
                    if glb.get("profile_wait_s") is not None:
                        try:
                            _pw = float(glb["profile_wait_s"])
                        except (TypeError, ValueError):
                            _pw = 0.0
                        _crw["profile_wait_s"] = max(0.0, min(120.0, _pw))
                    if glb.get("timeout_seconds"):
                        _crw["timeout_seconds"] = min(
                            600, max(10, int(glb["timeout_seconds"])))
                    if glb.get("delay_min") is not None:
                        _crw["delay_min"] = max(0, int(glb["delay_min"]))
                    if glb.get("delay_max") is not None:
                        _crw["delay_max"] = max(0, int(glb["delay_max"]))
                    if glb.get("user_agent") is not None:
                        _crw["user_agent"] = str(glb["user_agent"]).strip()[:600]
                    # 采集代理（r319）：空串=清空回直连（显式落键不留脏）；
                    # 形态校验（Soldier P2#4）——非 http(s)://host:port 的
                    # 手滑输入（如漏 scheme 的 127.0.0.1:7897）会让 httpx
                    # 抛 InvalidURL 使发现层全哑，宁缺勿错一律回直连
                    if glb.get("proxy") is not None:
                        _px = str(glb["proxy"]).strip()[:300]
                        if _px and not re.match(r"^https?://[^\s/]+:\d+$", _px):
                            _px = ""
                        _crw["proxy"] = _px
                    # 按渠道绑出口（r600）：与全局 proxy 同一套形态校验——
                    # 漏 scheme 的手滑输入会让该渠道 httpx 抛 InvalidURL，
                    # 而故障表现是「这一家全红」，最难归因回配置笔误。
                    if isinstance(glb.get("proxy_map"), dict):
                        _crw["proxy_map"] = _proxy_map_clean(glb["proxy_map"])
                    # Android 真机通道（r603）：字段范围与 core/android/config.py
                    # 的钳制逐项一致，避免界面能填出后端会悄悄改掉的值。
                    if isinstance(glb.get("android"), dict):
                        _and = glb["android"]
                        _a0 = dict(cfg.get("android") or {})
                        if _and.get("enabled") is not None:
                            _a0["enabled"] = bool(_and["enabled"])
                        if _and.get("provider") is not None:
                            _a0["provider"] = (str(_and["provider"]).strip()
                                               or "mumu")[:40]
                        if _and.get("install_dir") is not None:
                            _a0["install_dir"] = str(
                                _and["install_dir"]).strip()[:400]
                        for _ak, _alo, _ahi, _ad in (
                                ("vm_index", 0, 64, 0),
                                ("boot_timeout_s", 10, 600, 180),
                                ("action_timeout_s", 5, 900, 60),
                                ("fetch_budget_s", 0, 3600, 540)):
                            if _and.get(_ak) is not None:
                                try:
                                    _av = int(_and[_ak])
                                except (TypeError, ValueError):
                                    _av = _ad
                                _a0[_ak] = max(_alo, min(_ahi, _av))
                        if _and.get("snapshot") is not None:
                            _a0["snapshot"] = bool(_and["snapshot"])
                        # r958：设备身份/痕迹隐藏/前台复用（嵌套键，逐项钳制）
                        _aid = _and.get("identity")
                        if isinstance(_aid, dict):
                            _id0 = dict(_a0.get("identity") or {})
                            if _aid.get("enabled") is not None:
                                _id0["enabled"] = bool(_aid["enabled"])
                            if "use_root" in _aid:
                                _ur = _aid.get("use_root")
                                _id0["use_root"] = (
                                    None if _ur is None else bool(_ur))
                            if _aid.get("reboot") is not None:
                                _rb = str(_aid["reboot"]).strip().lower()
                                _id0["reboot"] = (
                                    _rb if _rb in ("zygote", "full", "none")
                                    else "zygote")
                            if _aid.get("force") is not None:
                                _id0["force"] = bool(_aid["force"])
                            _a0["identity"] = _id0
                        _ast = _and.get("stealth")
                        if isinstance(_ast, dict):
                            _st0 = dict(_a0.get("stealth") or {})
                            for _sk in ("enabled", "hide_dev_options"):
                                if _ast.get(_sk) is not None:
                                    _st0[_sk] = bool(_ast[_sk])
                            _a0["stealth"] = _st0
                        if _and.get("keep_app_alive") is not None:
                            _a0["keep_app_alive"] = bool(
                                _and["keep_app_alive"])
                        # vendor 段与文件里已有的 brand/model/…合并，只落
                        # apply：整体覆盖会把用户手写在 yaml 的官方键冲掉。
                        _avd = _and.get("vendor")
                        if isinstance(_avd, dict):
                            _v0 = dict(_a0.get("vendor") or {})
                            if _avd.get("apply") is not None:
                                _v0["apply"] = bool(_avd["apply"])
                            _a0["vendor"] = _v0
                        # 模拟定位（r601 补齐）：纬/经度控件写回，保留用户
                        # 手写在 yaml 的 name/alt/enabled，只更新给出的坐标。
                        _ag = _and.get("geo")
                        if isinstance(_ag, dict):
                            _g0 = dict(_a0.get("geo") or {})
                            for _gk, _glo, _ghi in (("lat", -90.0, 90.0),
                                                    ("lon", -180.0, 180.0),
                                                    ("alt", -1000.0, 10000.0)):
                                if _ag.get(_gk) is None:
                                    continue
                                try:
                                    _gv = float(_ag[_gk])
                                except (TypeError, ValueError):
                                    continue
                                _g0[_gk] = max(_glo, min(_ghi, _gv))
                            if _ag.get("name") is not None:
                                _g0["name"] = str(_ag["name"]).strip()[:80]
                            _a0["geo"] = _g0
                        cfg["android"] = _a0
                    if glb.get("align_display") is not None or "spoof_abi" in glb:
                        _a2 = dict(cfg.get("android") or {})
                        _id2 = dict(_a2.get("identity") or {})
                        if glb.get("align_display") is not None:
                            _id2["align_display"] = bool(glb["align_display"])
                        if "spoof_abi" in glb:
                            _sa = glb.get("spoof_abi")
                            _sat = str(_sa).strip().lower()
                            if _sa is None or _sa is False or _sat in (
                                    "", "false", "none"):
                                _id2["spoof_abi"] = None
                            elif _sat == "auto":
                                _id2["spoof_abi"] = "auto"
                            elif _sat == "true":
                                _id2["spoof_abi"] = True
                        _a2["identity"] = _id2
                        cfg["android"] = _a2
                    if glb.get("debug") is not None:
                        _crw["debug"] = bool(glb["debug"])
                    if glb.get("stealth") is not None:
                        _crw["stealth"] = bool(glb["stealth"])
                    if glb.get("auto_verify") is not None:
                        _crw["auto_verify"] = bool(glb["auto_verify"])
                    # 内核缓存位（启动级）：保存进配置，重启进程生效；
                    # 空串=显式回渠道默认位（显式落键不留脏）
                    if glb.get("browser_dir") is not None:
                        _crw["browser_dir"] = \
                            str(glb["browser_dir"]).strip()[:300]
                    # 2/5 区 · 熔断与请求预算（保存即热生效）
                    _rate0 = _crw.setdefault("rate", {})
                    if glb.get("min_gap_s") is not None:
                        try:
                            _mg = float(glb["min_gap_s"])
                        except (TypeError, ValueError):
                            _mg = 0.0
                        _rate0["min_gap_s"] = round(max(0.0, min(300.0, _mg)), 1)
                    if glb.get("per_minute") is not None:
                        try:
                            _pm = int(glb["per_minute"])
                        except (TypeError, ValueError):
                            _pm = 0
                        _rate0["per_minute"] = max(0, min(600, _pm))
                    _warm0 = _crw.setdefault("warmup", {})
                    if glb.get("warmup_enabled") is not None:
                        _warm0["enabled"] = bool(glb["warmup_enabled"])
                    if glb.get("warmup_platforms") is not None:
                        # 可预热 = **真的声明了入口**（warmup_url 非空）的渠道。
                        # 曾用手写白名单，里面含 ctrip/tongcheng —— 这两家没有
                        # 入口，填进去后按钮可点但点了什么也不做（r627）。
                        _wl = [x.strip() for x in
                               str(glb["warmup_platforms"]).split(",") if x.strip()]
                        _warm0["platforms"] = [x for x in _wl if x in _warmable()]
                        _ignored = [x for x in _wl if x not in _warmable()]
                        if _ignored:
                            _warm0["ignored"] = _ignored
                    _brk0 = _crw.setdefault("breaker", {})
                    if glb.get("breaker_enabled") is not None:
                        _brk0["enabled"] = bool(glb["breaker_enabled"])
                    if glb.get("health_penalty_enabled") is not None:
                        _crw["health_penalty_enabled"] = bool(
                            glb["health_penalty_enabled"])
                    # 成功率保护阈值（r485）：四档数字可调，不再写死
                    for _hk, _hc in (("health_min_samples", int),
                                     ("health_ok_ratio", float),
                                     ("health_slow_ratio", float),
                                     ("health_slow_factor", float),
                                     ("health_slowest_factor", float)):
                        if glb.get(_hk) is not None:
                            try:
                                _crw[_hk] = _hc(glb[_hk])
                            except (TypeError, ValueError):
                                pass
                    if glb.get("breaker_base_s") is not None:
                        try:
                            _bb = int(glb["breaker_base_s"])
                        except (TypeError, ValueError):
                            _bb = 300
                        _brk0["base_s"] = max(30, min(3600, _bb))
                    if glb.get("breaker_cap_s") is not None:
                        try:
                            _bc = int(glb["breaker_cap_s"])
                        except (TypeError, ValueError):
                            _bc = 3600
                        _brk0["cap_s"] = max(120, min(86400, _bc))
                    # r523：把原先「只能在文件里改」的采集细节落盘（热生效）。
                    _crw2 = cfg.setdefault("crawler", {})
                    for _ck, _cd, _lo, _hi in (
                            ("session_max_days", 0, 0, 365),
                            ("max_concurrency", 0, 0, 16)):
                        if glb.get(_ck) is not None:
                            try:
                                _crw2[_ck] = max(_lo, min(_hi, int(glb[_ck])))
                            except (TypeError, ValueError):
                                _crw2[_ck] = _cd
                    for _sk2 in ("mobile_user_agent", "tls_impersonate",
                                 "debug_dir"):
                        if glb.get(_sk2) is not None:
                            _crw2[_sk2] = str(glb[_sk2] or "").strip()[:300]
                    if glb.get("login_desktop") is not None:
                        _crw2["login_desktop"] = bool(glb["login_desktop"])
                    if glb.get("login_cooldown_s") is not None:
                        try:
                            _lc2 = int(glb["login_cooldown_s"])
                        except (TypeError, ValueError):
                            _lc2 = 900
                        _brk0["login_cooldown_s"] = max(60, min(86400, _lc2))
                    if glb.get("login_cooldown_max_s") is not None:
                        try:
                            _lcm2 = int(glb["login_cooldown_max_s"])
                        except (TypeError, ValueError):
                            _lcm2 = 14400
                        _brk0["login_cooldown_max_s"] = max(
                            300, min(86400, _lcm2))
                    if glb.get("challenge_cooldown_s") is not None:
                        try:
                            _cc2 = int(glb["challenge_cooldown_s"])
                        except (TypeError, ValueError):
                            _cc2 = 21600
                        _brk0["challenge_cooldown_s"] = max(0, min(604800,
                                                                   _cc2))
                    if glb.get("near_days") is not None:
                        try:
                            _nd2 = int(glb["near_days"])
                        except (TypeError, ValueError):
                            _nd2 = 3
                        cfg.setdefault("schedule", {})["near_days"] = max(
                            0, min(30, _nd2))
                    if isinstance(glb.get("cadence"), dict):
                        _cad0 = _crw2.setdefault("cadence", {})
                        # 白名单必须含 App 渠道：界面已经能为「智行 App」
                        # 生成节奏控件，若这里只放行 5 家浏览器渠道，
                        # 用户填的值会被静默丢弃——能填、不生效、不报错。
                        try:
                            from core.channels import (
                                APP_CHANNELS as _APPCH,
                                BROWSER_CHANNELS as _BRCH)
                            _cad_ok = set(_BRCH) | set(_APPCH)
                        except Exception:
                            _cad_ok = {"qunar", "fliggy", "ctrip",
                                       "tongcheng", "tuniu"}
                        for _cp, _cv in glb["cadence"].items():
                            if _cp not in _cad_ok:
                                continue
                            try:
                                # 与 core/pacing.py 同口径：整数分钟、0..10080。
                                _cad0[_cp] = max(0, min(10080, int(_cv)))
                            except (TypeError, ValueError):
                                pass
                    # ── 策略参数的逐条编辑（r1063 T12b）─────────────────
                    # 「策略控制」面板的每一行都直接改参数，而写路径**仍然
                    # 只有这一条**（Spec §5「不新开一路」）：`glb` 整表里带
                    # `strategy_values`（键是 `Param.pid`），值写到该参数声明
                    # 的 cfg 点路径（全局层）。不为参数另开写接口——两个写入口
                    # 就会在「谁最后写」上打架，yaml 与本页脏状态迟早劈叉：
                    # `/api/strategy` 只读、`/api/strategy/{halt,resume}` 只做
                    # 运行期停手/恢复，参数一律回这条路。
                    #
                    # 两个名字各管一层，别混用：`strategy_overrides` 是**粒度
                    # 覆盖**（作用域串 → {pid: 值}，见 core/strategy_params.py），
                    # `strategy_values` 是**全局层**的逐参数编辑（pid → 值）。
                    #
                    # 夹取与类型规整一律问 `strategy_params.clamp()`：**与求值
                    # 同一个入口**，所以界面显示的边界就是落盘的边界（界面自己
                    # 抄一遍 Math.min/max 是这类分叉的老剧本）。
                    # 粒度覆盖（r1063 T19）：面板选中「维度/链路」作用域时改的
                    # 参数走这一支，落进 `crawler.strategy_overrides`——与
                    # `strategy_values` 同一条保存通路，不新开写接口。
                    _ovr = glb.get("strategy_overrides")
                    if _ovr is not None:
                        try:
                            _n_ovr = _strategy_override_apply(cfg, _ovr)
                        except ValueError as _ove:
                            raise ValueError(str(_ove))
                        st.logger.info("[web配置] 策略覆盖写入 %d 项", _n_ovr)
                    _edits = glb.get("strategy_values")
                    if _edits is not None:
                        if not isinstance(_edits, dict):
                            raise ValueError(
                                "strategy_values 必须是 {参数 id: 值} 的字典"
                                "（收到 %s）——整块丢弃等于「配了不生效」"
                                % type(_edits).__name__)
                        from core import strategy_params as _sparams
                        from core.strategy_contract import (
                            STRATEGIES as _STRS_E)
                        _CFG_OF = {_p.pid: _p.cfg for _s in _STRS_E
                                   for _p in _s.params}
                        _bad = []
                        for _pid, _raw in _edits.items():
                            _key = str(_pid or "")
                            if _key not in _CFG_OF:
                                # 未知 pid 不许静默丢：那是「以为改到了」
                                _bad.append("%s（目录里没有这个参数）" % _key)
                                continue
                            try:
                                _val, _note = _sparams.clamp(_key, _raw)
                            except Exception as _pe:
                                _bad.append("%s（%s）"
                                            % (_key, str(_pe)[:60]))
                                continue
                            _segs = [x for x in _CFG_OF[_key].split(".")
                                     if x]
                            _node = cfg
                            _ok_node = True
                            for _sg in _segs[:-1]:
                                _nx = _node.get(_sg)
                                if not isinstance(_nx, dict):
                                    _nx = {}
                                    _node[_sg] = _nx
                                _node = _nx
                                if not isinstance(_node, dict):
                                    _ok_node = False
                                    break
                            if _ok_node and _segs:
                                _node[_segs[-1]] = _val
                        if _bad:
                            raise ValueError(
                                "这些策略参数没写进去（取值转不过声明类型）：%s"
                                % "、".join(_bad[:4]))
                    # win_toast 缺省即开启——保存时落显式布尔进 config.yaml
                    for u0 in (cfg["users"] or []):
                        n0 = u0.get("notifier") or {}
                        n0["win_toast"] = bool(n0.get("win_toast", True))
                        u0["notifier"] = n0
                    with open(st.config_path, "w", encoding="utf-8") as f:
                        _y.safe_dump(cfg, f, allow_unicode=True,
                                     sort_keys=False, width=100)
                    n = st.reload_cb() if st.reload_cb else 0
                    # 签名缓存作废：签名五元组只含运行时 users 形态，cfg 派生
                    # 键（suspended 等）在「只改停用航线配置」场景下 users 序列
                    # 化逐字节不变，不作废则卡片文本陈旧到进程重启
                    _STATE_CACHE["sig"] = None
                    # r1063 T274b：**同步本进程的配置快照**。此前只重载了主程序
                    # 那份，而 `_effective_crawler_config()` 读的是 `_State.cfg`
                    # （启动快照）→ 面板里改 crawler 选项永远不生效。
                    # `boot_cfg` 保持不动：它用于「需重启」差量判定。
                    # 放在签名缓存作废**之后**：`test_r267` 钉的是
                    # 「reload_cb → 紧接作废签名缓存」这条不变量，别被插队。
                    try:
                        from main import load_config as _live_load
                        _live_cfg = _live_load(str(st.config_path))
                        if isinstance(_live_cfg, dict) and _live_cfg:
                            _State.cfg = _live_cfg
                    except Exception as _le:
                        try:
                            st.logger.warning("[web配置] 同步配置快照失败: %s",
                                              _le)
                        except Exception:
                            pass
                    st.logger.info("[web配置] 已保存并热重载：%d 用户", n)
                    # 保存回执带路径元数据与启动差量：前端保存后无需再
                    # 拉一次配置即可点亮「需重启」与迁移预案
                    self._json({"ok": True, "users": n,
                                "storage": _storage_view(cfg),
                                "restart": _restart_view(cfg)})
                except Exception as e:
                    self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/open-folder":
            # 打开数据所在文件夹 / 默认应用打开文件（r342）：
            # 白名单键经 _open_folder_target/_open_file_target 单源解析；
            # os.startfile/xdg-open 参数直传零 shell 引号注入口。
            # action=folder（默认，兼容旧前端）/file；目录动作才 makedirs
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                which = str(body.get("which") or "")
                action = str(body.get("action") or "folder")
                if action not in ("folder", "file"):
                    self._json({"ok": False, "err": "未知动作"})
                    return
                _file = _open_file_target(which, st.cfg or {}) \
                    if action == "file" else None
                if action == "file" and not _file:
                    self._json({"ok": False,
                                "err": "文件尚不存在——保存并重启后可用"})
                    return
                _tgt = _file or _open_folder_target(which, st.cfg or {})
                if not _tgt:
                    self._json({"ok": False, "err": "未知目标"})
                    return
                if not _file:
                    os.makedirs(_tgt, exist_ok=True)
                if sys.platform == "win32":
                    os.startfile(_tgt)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", _tgt],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["xdg-open", _tgt],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                self._json({"ok": True, "path": _tgt,
                            "action": action})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/restart":
            # 进程自重启（启动级配置生效通道）：先拉起携 --restart-delay
            # 的新实例（延迟抢锁——旧进程退出才释放 data/.instance.lock，
            # 即时抢锁必撞锁退场），旧进程延时自退；os._exit 直退：
            # SQLite WAL 崩溃安全，调度线程随进程终结不留尾巴
            try:
                # 新实例命令行必须带脚本本体：旧实现只拼 sys.executable
                # + sys.argv[1:]，漏掉 sys.argv[0]（main.py），重启后
                # 实际执行的是 `python --restart-delay 3` ——旧进程已退、
                # 新进程秒退，控制台随之失踪。过滤 flag 时连值一起剥，
                # 防连续重启把 "3" 当残留参数喂给 argparse。
                _args, _skip = [], False
                for _a in sys.argv[1:]:
                    if _a == "--restart-delay":
                        _skip = True
                        continue
                    if _skip:
                        _skip = False
                        continue
                    _args.append(_a)
                _script = ([] if getattr(sys, "frozen", False)
                           or not (sys.argv and sys.argv[0].endswith(".py"))
                           else [os.path.abspath(sys.argv[0])])
                cmd = [sys.executable] + _script + _args \
                    + ["--restart-delay", "3"]
                kw = {"cwd": _ROOT}
                if os.name == "nt":
                    kw["creationflags"] = (
                        getattr(subprocess, "DETACHED_PROCESS", 0)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                subprocess.Popen(cmd, **kw)
                st.logger.warning("[web] 收到重启指令，新实例已拉起，"
                                  "本进程 1s 后退出：%s", cmd)
                threading.Timer(1.0, lambda: os._exit(0)).start()
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-push":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                from core.notifier import DingTalkNotifier
                n = DingTalkNotifier(
                    webhook=body.get("webhook", ""),
                    logger=st.logger,
                    secret=body.get("secret", ""))
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                # 带版本号：群里能直接核对当前运行版本（僵尸实例鉴别）
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                extra = (f"\n\n当前运行版本 v{ver} ｜ ⏰ {now}" if ver
                         else f"\n\n⏰ {now}")
                ok = n.send(
                    "✅ 机票监控｜测试推送",
                    # #### 纪律（# 级大标题喧宾夺主）+ 正文行 ≤40 半角
                    # （22 全角行手机窄屏折行断点不受控）
                    "#### ✅ 测试推送成功\n\n该钉钉机器人配置可用。\n\n"
                    "监控警报将发送到此群。" + extra)
                self._json({"ok": bool(ok),
                                            "err": None if ok else (
                                                (getattr(n, "last_errcode", None)
                                                 and ("errcode=%s（自定义关键词/加签/IP 白名单不符为高频因）"
                                                      % n.last_errcode))
                                                or "发送失败（详见服务日志）")})   # test-push 失败详情透传（通道审计 P2-3）
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-toast":
            # Windows 本机弹窗通路测试（达标强提醒链路，点击可直达详情）
            try:
                from core.notifier import WindowsToastNotifier
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                host = self.headers.get("Host") or "127.0.0.1:8765"
                n = WindowsToastNotifier(st.logger)
                ok = n.send(
                    "🔔 弹窗测试——通路正常",
                    ("版本 v%s ｜ ⏰ %s\n收到即代表达标弹窗可用，"
                     "点击本弹窗验证直达" % (ver or "?", now)),
                    launch="http://%s/" % host)
                self._json({"ok": bool(ok),
                            "err": "" if ok else "本机不支持（需 Windows）"})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-ntfy":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                topic = (body.get("topic") or "").strip()
                if not topic:
                    self._json({"ok": False, "err": "请先填写主题"})
                    return
                from core.notifier import NtfyNotifier
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                n = NtfyNotifier(topic=topic, logger=st.logger,
                                 priority=int(body.get("priority") or 5))
                ok = n.send("🔔 ntfy 测试——通路正常",
                            ("版本 v%s ｜ ⏰ %s\n收到即代表达标强提醒链路可用"
                             % (ver or "?", now)))
                self._json({"ok": bool(ok),
                            "err": None if ok else (
                                getattr(n, "last_err", None)
                                or "发送失败（详见服务日志）")})   # test-ntfy：失败详情透传（通道审计 P2-2/P2-3，前端 ❌ 词面可行动）
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-bark":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                key = (body.get("key") or "").strip()
                if not key:
                    self._json({"ok": False, "err": "请先填写 Bark Key"})
                    return
                from core.notifier import BarkNotifier
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                n = BarkNotifier(key=key, logger=st.logger,
                                 server=(body.get("server") or "").strip()
                                 or "https://api.day.app")
                ok = n.send("🔔 Bark 测试——通路正常",
                            ("版本 v%s ｜ ⏰ %s\n收到即代表达标强提醒链路可用"
                             % (ver or "?", now)))
                self._json({"ok": bool(ok),
                            "err": None if ok else (
                                (getattr(n, "last_errcode", None) and ("HTTP %s" % n.last_errcode))
                                or getattr(n, "last_err", None)
                                or "发送失败（详见服务日志）")})   # test-bark：失败详情透传（通道审计 P2-2）
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-email":
            # 邮件通路测试：直调 EmailNotifier 用表单当前值
            # 真实发信——SMTP 授权码对错只有真发才知道（同图床/ntfy
            # 「测试必须如实报告通路死活」纪律）；正文即 HTML 正式形态
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                if not ((body.get("user") or "").strip()
                        and (body.get("password") or "").strip()):
                    self._json({"ok": False,
                                "err": "请先填写发件账号和授权码"})
                    return
                if not (body.get("to") or "").strip():
                    self._json({"ok": False, "err": "请先填写收件邮箱"})
                    return
                from core.notifier import EmailNotifier
                now = __import__('datetime').datetime.now().strftime(
                    '%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                # 测试邮件 = 正式形态（整套快照）：snapshot_base
                # 指向本控制台，渲染失败自动降级轻壳（通路优先于形态）
                host = self.headers.get("Host") or "127.0.0.1:8765"
                n = EmailNotifier(
                    host=str(body.get("host") or ""),
                    port=int(body.get("port") or 465),
                    user=str(body.get("user") or ""),
                    password=str(body.get("password") or ""),
                    to=str(body.get("to") or ""),
                    logger=st.logger,
                    snapshot_base="http://%s/" % host)
                # 整段走 % 格式化，正文里的字面 % 必须写成 %%
                # （issue #18：「100% 同视觉」漏转义曾让测试邮件 100% 发不出去）
                desp = ("#### 📸 测试邮件——通路正常（控制台整页截图）\n\n"
                        "正文即正式推送形态：控制台整页截图直嵌，KPI/走势/"
                        "明细与网页 100%% 同视觉。\n\n"
                        "> 版本 v%s ｜ ⏰ %s\n\n"
                        "- 截图渲染失败自动降级纯文字轻壳，通路不受影响"
                        % (ver or "?", now))
                ok = n.send("✅ 机票监控｜邮件通路测试", desp,
                            # launch 与主路径同律（回环
                            # base_url 异机必死链，按钮/页脚指引两态联动）；
                            # snapshot_base 回环合法（快照服务端本机渲染）
                            launch=_test_email_launch())
                self._json({"ok": bool(ok),
                            "err": (getattr(n, "last_err", "")
                                    or "发送失败（详见监控日志）")})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-imghost":
            # 图床通路测试（P1-1）：直调所选床上传函数，绕开
            # upload_chart 的 provider 路由——freeimage 连败记忆会静默
            # 跳档，走 upload_chart 测试会假绿；测试必须如实报告所选床
            # 死活（死亡/退避期返回 None 如实报败）
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                provider = (body.get("provider") or "").strip().lower()
                token = (body.get("token") or "").strip()
                if provider not in ("freeimage", "ghimg", "smms"):
                    self._json({"ok": False, "err": "未知图床服务"})
                    return
                if provider == "smms" and not token:
                    self._json({"ok": False, "err": "请先填写 sm.ms Token"})
                    return
                if provider == "ghimg" and (
                        not (body.get("repo") or "").strip() or not token):
                    self._json({"ok": False,
                                "err": "请先填写 GitHub 图库仓库与 Token"})
                    return
                import base64 as _b64
                import tempfile as _tf
                from report import upload_freeimage, upload_smms
                _png = _tf.NamedTemporaryFile(suffix=".png", delete=False)
                try:
                    # 1×1 透明 PNG 内存图：测通路不产图
                    _png.write(_b64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                        "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
                    _png.close()
                    # 独立捕获 logger：不碰服务主 logger，失败时捞出图床
                    # 响应摘要随 err 回显（upload_smms 失败只回 None）
                    tlog = logging.getLogger("webui.imghost-test")
                    tlog.propagate = False
                    tlog.setLevel(logging.WARNING)
                    _buf = []

                    class _Cap(logging.Handler):
                        def emit(self, record):
                            _buf.append(record.getMessage())

                    _h = _Cap()
                    tlog.addHandler(_h)
                    try:
                        if provider == "freeimage":
                            # 连败退避跳档/端点死亡均返回 None：端点
                            # 拿不到 URL 即报败（日志经 _Cap 随附）
                            url = upload_freeimage(_png.name, tlog)
                        elif provider == "ghimg":
                            from report import upload_ghimg
                            url = upload_ghimg(_png.name, {
                                "repo": (body.get("repo") or "").strip(),
                                "token": token,
                                "proxy": (body.get("proxy") or "").strip()},
                                tlog)
                        else:
                            url = upload_smms(_png.name, token, tlog)
                    finally:
                        tlog.removeHandler(_h)
                    if url:
                        self._json({"ok": True, "url": url})
                    else:
                        _detail = _buf[-1] if _buf else "上传失败（详见服务日志）"
                        self._json({"ok": False, "err": _detail[:120]})
                finally:
                    try:
                        os.remove(_png.name)
                    except OSError:
                        pass
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/app-login"):
            # App 渠道登录（r604）：与 /api/login 完全同一套安全边界
            # ——Content-Type 必须是 json、Origin 必须同源、体积 ≤32KB。
            try:
                # r671b/r672：只有**带 body** 才要求 JSON。`fetch(path,
                # {method:'POST'})` 不带 body 时浏览器自动补 text/plain，
                # 无条件 415 会把这类同源按钮打哑（r672 端点普查实测
                # /api/app-login* 五个端点各两个调用形态全 415）。无 body
                # 本就没有可解析载荷，CSRF 也只能触发幂等动作。
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (
                            self.headers.get("Host") or ""):
                        self._json({"ok": False,
                                    "err": "跨站登录请求已拒绝"}, 403)
                        return
                from urllib.parse import urlparse as _up, parse_qs as _pq
                from core.android import login_api as _la
                _u = _up(self.path)
                # 与 /api/login 同源：body 从 self.rfile 读（_do_POST 上方
                # 已把原始字节塞回 rfile），体积上限 32KB 由 parse_body 守。
                try:
                    _n = int(self.headers.get("Content-Length", 0) or 0)
                except (TypeError, ValueError):
                    _n = 0
                if _n > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                _body = _la.parse_body(self.rfile.read(_n) if _n > 0 else b"")
                _r = _la.dispatch(_app_login_registry(), "POST", _u.path,
                                  _pq(_u.query), _body, _app_login_ctx())
                # r1063 T175：开登录会话时**顺手叫停本轮**——否则用户要等
                # 正在飞的那条航线跑完（最长 300s），面板上只能显示"等采集 N 秒"。
                # 只对"建会话"这一步做；按钮点击/输入等高频调用不重复请求。
                try:
                    if (_u.path.rstrip("/") == "/api/app-login"
                            and isinstance(_r[0], dict) and _r[0].get("ok")):
                        from core import interrupt as _itr
                        _itr.request(by="app-login")
                        _State.logger.info(
                            "[App登录] 已请求叫停本轮为登录让路（航线边界生效）")
                except Exception:
                    pass
                _obj, _code = _r
                # App 登录也要入干预账（r646）：网页登录成功会写 relogin，
                # App 这条链路原先只在内存里结束——账本里查不到，节流面板
                # 的「上次干预 44%→100%」永远不会以 App 重登为分界，干预
                # 成功率也算不到它。scope 写动作本身，after 留给后台采集填。
                try:
                    if (_u.path.rstrip("/") == "/api/app-login/finish"
                            and isinstance(_obj, dict) and _obj.get("ok")):
                        from core.storage import PriceStorage as _PSa
                        _plata = str((_body or {}).get("plat")
                                     or (_pq(_u.query).get("plat") or [""])[0])
                        if _plata:
                            _PSa(_anchored(
                                ((_State.cfg or {}).get("output") or {}).get(
                                    "db_path"), "data/prices.db")
                            ).save_intervention(
                                _plata, "relogin", ok=True, scope=_plata,
                                before="login_wall",
                                note="App 内登录并导出快照（真机画面）")
                            # r1063 T168：App登录成功后清墙——否则用户明明登成功了，
                            # 面板与 early_skip 仍按旧墙判「需登录（N 分钟内不再重试）」。
                            try:
                                _cleared = _clear_login_wall_memo(_plata, _plata)
                                _State.logger.info(
                                    "[App登录] %s 已清登录墙记忆：%s", _plata,
                                    "、".join(_cleared) or "无")
                            except Exception:
                                pass
                            # 顺手后台复探一次（与浏览器登录一致：登完就验）
                            try:
                                _kick_login_probe(_plata)
                            except Exception:
                                pass
                except Exception as _e:
                    try:
                        _State.logger.warning("[App登录] 干预入账失败：%s", _e)
                    except Exception:
                        pass
                self._json(_obj, _code)
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 413)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/special-radar":
            if DEMO["on"]:
                self._json({"ok": False, "err": "演示模式不发起真实特价查询"}, 400)
                return
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站特价查询请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("bad body")
                from core.special_radar import build_radar
                cfg = _effective_crawler_config()
                out = build_radar(body, _State.logger,
                                  proxy=str(cfg.get("proxy") or ""),
                                  user_data_dir=str(
                                      cfg.get("user_data_dir")
                                      or "user_data"))
                try:
                    _radar_save_result(out)
                except Exception as _e:
                    _State.logger.warning("[雷达] 监控快照写入失败: %s", _e)
                self._json(out)
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:200]}, 500)
        elif self.path == "/api/login":
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站登录请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(_start_login(str(body.get("platform", "")),
                                        str(body.get("slot", ""))))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/login-challenge":
            # 人机验证入口：只打开**账本里被拦的那一页**，URL 由服务端从
            # fetch_paths.request_url 取，不接受客户端传入（防 SSRF/跳转）。
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站登录请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                _key = str(body.get("slot") or body.get("platform") or "")
                _t = _challenge_target(_key)
                if not _t.get("ok"):
                    self._json(_t)
                else:
                    self._json(_start_login(
                        _t["plat"], _t["slot"], url=_t["url"],
                        desktop=bool(_t["desktop"]),
                        mobile=bool(_t["mobile"])))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/login-finish":
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站登录请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(_finish_login(str(body.get("platform", "")),
                                         str(body.get("slot", ""))))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path in ("/api/challenge/open",
                           "/api/challenge/verify",
                           "/api/challenge/skip"):
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up1
                    if ((_up1(_origin).netloc or "")
                            != (self.headers.get("Host") or "")):
                        self._json({"ok": False, "err": "跨站验证请求已拒绝"},
                                   403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                _cid = str(body.get("id") or "")
                if self.path == "/api/challenge/open":
                    self._json(_probe_open_challenge(_cid))
                elif self.path == "/api/challenge/verify":
                    self._json(_probe_verify_challenge(_cid))
                else:
                    self._json(_probe_skip_challenge(_cid))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/srx/watch":
            # 关注增删改：只写身份/渠道/目标/启停，不写价格
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站关注请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("bad body")
                self._json(_watch_apply(body.get("user"), body))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/login-verify":
            try:
                if DEMO["on"]:
                    self._json({"ok": False, "err": "演示模式不核验真实会话"}, 400)
                    return
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站核验请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 32768:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                slot = str((body or {}).get("slot", ""))
                # r1153：任一**已登记的槽位**都能核验（此前只放行 fliggy_h5，
                # 其余槽位点「核验」必 400，用户看到的就是"登录了页面也不变"）。
                if slot not in LOGIN_SLOTS:
                    self._json({"ok": False, "err": "未知登录槽位：%s" % slot}, 400)
                    return
                threading.Thread(target=_verify_login_slot, args=(slot,),
                                 daemon=True, name="slot-verify-manual").start()
                self._json({"ok": True, "slot": slot, "verifying": True})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/probe/start":
            if DEMO["on"]:
                self._json({"ok": False, "err": "演示模式不发起真实外网探针"}, 400)
                return
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站探针请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 65536:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("bad body")
                from crawlers import REGISTRY as _REG
                _legs = body.get("legs")
                _raw = _legs if isinstance(_legs, list) and _legs else None
                _plans = []
                if _raw is not None:
                    if len(_raw) > _PROBE_BATCH_MAX:
                        raise ValueError("组合探针最多 %d 条航线/日期" % _PROBE_BATCH_MAX)
                    _seen = set()
                    for _i, _leg in enumerate(_raw, 1):
                        if not isinstance(_leg, dict):
                            raise ValueError("第 %d 条缺少 from/to/date" % _i)
                        try:
                            _p = _probe_leg_plan(_leg.get("from"), _leg.get("to"),
                                                 _leg.get("date"))
                        except ValueError as _e:
                            raise ValueError("第 %d 条：%s" % (_i, _e))
                        _k = (_p["from"], _p["to"], _p["date"])
                        if _k in _seen:
                            raise ValueError("第 %d 条与前面重复" % _i)
                        _seen.add(_k)
                        _plans.append(_p)
                else:
                    _plans = [_probe_leg_plan(body.get("from"), body.get("to"),
                                              body.get("date"))]
                _want = [p for p in (body.get("plats") or list(_REG.keys()))
                         if p in _REG]
                _want.sort(key=_plat_rank)
                if not _want:
                    raise ValueError("至少选择一个渠道")
                _retry = bool(body.get("retry"))
                _skipped = []
                if _retry:
                    _allowed, _skipped = _probe_filter_want(_want)
                    if _skipped and not _allowed:
                        self._json({
                            "ok": False,
                            "err": "渠道验证冷却中，请稍后再试：%s"
                                   % "、".join(_skipped)}, 409)
                        return
                    _want = _allowed
                import time as _t
                if not _retry and _t.time() - _PROBE_LAST < _PROBE_COOLDOWN:
                    _remain = _PROBE_COOLDOWN - (_t.time() - _PROBE_LAST)
                    self._json({"ok": False,
                                "err": "探针冷却中，请 %.0fs 后再试"
                                       % _remain}, 409)
                    return
                if _PROBE_LOCK.locked():
                    self._json({"ok": False, "err": "已有探针在采集，请稍后再试"}, 409)
                    return
                # 逐腿渠道：失败重试只重跑该腿失败的渠道，不再把整个
                # 渠道复制到所有腿（旧实现一个失败会触发五倍上游请求）。
                _leg_wants = {}
                for _i, _p in enumerate(_plans):
                    _lp = None
                    if _raw is not None and isinstance(_raw[_i], dict):
                        _lp = _raw[_i].get("plats")
                    if isinstance(_lp, list) and _lp:
                        _lw = [q for q in _lp if q in _REG]
                        _lw.sort(key=_plat_rank)
                        if not _lw:
                            raise ValueError("第 %d 条未选择有效渠道" % (_i + 1))
                    else:
                        _lw = list(_want)
                    if _retry:
                        _lw = [q for q in _lw if q in _want]
                        if not _lw:
                            raise ValueError(
                                "第 %d 条渠道均在验证冷却中" % (_i + 1))
                    _leg_wants[_i] = _lw
                _want_all = sorted({q for _v in _leg_wants.values() for q in _v},
                                   key=_plat_rank)
                _tid = "%x" % _t.time_ns()
                _now = _t.time()
                _legs_t = []
                for _i, _p in enumerate(_plans):
                    _legs_t.append({
                        "leg": _i, "from": _p["from"],
                        "from_name": _p["from_name"], "to": _p["to"],
                        "to_name": _p["to_name"], "date": _p["date"],
                        "status": "queued", "rows": 0, "detail": 0, "cal": 0,
                        "channels": {q: {"status": "queued", "phase": "排队",
                                         "n": 0, "detail": 0, "cal": 0,
                                         "ms": 0, "err": ""}
                                     for q in _leg_wants[_i]}})
                _task = {"id": _tid, "status": "running", "created": _now,
                         "updated": _now, "started": _now, "finished": None,
                         "plans": _plans, "want": _want_all,
                         "leg_wants": _leg_wants,
                         "skipped": list(_skipped),
                         "parent": str(body.get("parent") or ""),
                         "total": sum(len(_v) for _v in _leg_wants.values()),
                         "legs": _legs_t,
                         "rows": [], "rowkeys": set(), "events": [],
                         "cancel": threading.Event(), "truncated": False,
                         "err": ""}
                _probe_task_cleanup()
                with _PROBE_TASK_LOCK:
                    _PROBE_TASKS[_tid] = _task
                if _skipped:
                    _probe_task_event(
                        _task, phase="渠道冷却", status="challenge",
                        msg="跳过验证冷却渠道：%s" % "、".join(_skipped))
                threading.Thread(
                    target=_probe_start_task,
                    args=(_tid, body.get("from"), body.get("to"),
                          body.get("date"), _raw, _want_all, _retry,
                          _leg_wants),
                    daemon=True).start()
                self._json({"ok": True, "task": _probe_task_view(_tid)})
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/probe/cancel":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                _tid = str((body or {}).get("id") or "")
                with _PROBE_TASK_LOCK:
                    _task = _PROBE_TASKS.get(_tid)
                    if not _task:
                        self._json({"ok": False, "err": "任务不存在"}, 404)
                        return
                    if _task["status"] == "running":
                        _task["cancel"].set()
                        _task["status"] = "stopping"
                        _task["updated"] = time.time()
                _probe_task_event(_task, phase="正在停止", status="stopping",
                                  msg="已发送取消；执行中的请求结束前不再写入结果")
                self._json({"ok": True, "task": _probe_task_view(_tid)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 400)
        elif self.path == "/api/probe/search":
            # 主动探针：任意航线/日期并发真实渠道采集；不落库、不推送。
            if DEMO["on"]:
                self._json({"ok": False, "err": "演示模式不发起真实外网探针"}, 400)
                return
            try:
                if not self._json_body_ok():
                    return
                _origin = self.headers.get("Origin") or ""
                if _origin:
                    from urllib.parse import urlparse as _up0
                    if (_up0(_origin).netloc or "") != (self.headers.get("Host") or ""):
                        self._json({"ok": False, "err": "跨站探针请求已拒绝"}, 403)
                        return
                length = int(self.headers.get("Content-Length", 0))
                if length > 65536:
                    self._json({"ok": False, "err": "请求体过大"}, 413)
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("bad body")
                self._json(_probe_search(body.get("from"), body.get("to"),
                                         body.get("date"), body.get("plats"),
                                         body.get("legs")))
            except ValueError as e:
                self._json({"ok": False, "err": str(e)}, 400)
            except RuntimeError as e:
                self._json({"ok": False, "err": str(e)}, 409)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path in ("/api/update/start", "/api/update/rollback"):
            # r1197：POST 侧补两个动作（GET 侧只有只读状态）。
            # start = 后台下载+应用（带进度，见 /api/update/status）；
            # rollback = 用最新备份把文件拷回去（语义在 core.update.rollback）。
            try:
                if self.path.endswith("/start"):
                    self._json(_update_start_async())
                else:
                    # r1200：回滚会**覆盖代码文件**，必须显式确认 + 点名备份。
                    # 事故记录：r1198 的探针直接 POST 了一个空 body，默认"用最新备份"
                    # 把 996 个文件拷了回去（本机备份恰好等于当前工作树，未丢改动，
                    # 但这个默认值本身就是一颗雷）。现在要点名 + confirm。
                    from core import update as _up
                    _body = {}
                    try:
                        _len = int(self.headers.get("Content-Length", 0) or 0)
                        if 0 < _len <= 32768:
                            _body = json.loads(self.rfile.read(_len) or b"{}")
                    except Exception:
                        _body = {}
                    if not (isinstance(_body, dict) and _body.get("confirm")):
                        self._json({
                            "ok": False,
                            "err": ("回滚会覆盖代码文件，必须显式确认："
                                    "body 传 {\"confirm\": true, \"backup\": \"<名字>\"}"),
                            "backups": [b["name"] for b in _up.list_backups()[:10]],
                        }, 400)
                        return
                    self._json(_up.rollback(str(_body.get("backup") or "")))
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:200]}, 500)
        elif self.path == "/api/update/apply":
            # r1063 T254：浏览器一键升级（下载→备份→覆盖，失败回滚）。
            # 升级**不会**覆盖 config.yaml / user_data（见 core.update.SKIP）。
            try:
                from core import update as _upd
                _d = _upd.download()
                if not _d.get("ok"):
                    self._json({"ok": False,
                                "err": _d.get("err") or "下载失败"})
                else:
                    _r = _upd.apply(_d.get("path") or "")
                    if _r.get("ok"):
                        _r["next"] = ("升级完成（%d 个文件，已备份到 %s）；"
                                      "点「重启生效」或调用 /api/restart"
                                      % (_r.get("files") or 0,
                                         _r.get("backup") or ""))
                    self._json(_r)
            except Exception as e:
                self._json({"ok": False, "err": str(e)[:160]}, 500)
        elif self.path == "/api/run/stop":
            # r1063 T172：手动中止本轮（航线边界生效；不强杀线程）。
            try:
                from core import interrupt as _itr
                st = _itr.request(by="panel")
                self._json({"ok": True, **st,
                            "next": "已请求中止：不再派发下一条航线；"
                                    "正在飞的那条会跑完并照常落库"})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/run":
            # r1063 T172：新一轮开始先清掉上一轮遗留的中止请求
            try:
                from core import interrupt as _itr
                _itr.clear()
            except Exception:
                pass

            if st.job is None:
                self._json({"ok": False, "err": "job 未挂接"}, 500)
                return
            if not st.lock.acquire(blocking=False):
                self._json({"ok": False, "err": "一轮扫描正在进行中"}, 409)
                return
            try:
                st.job()
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
            finally:
                st.lock.release()
        elif self.path == "/api/strategy/halt":
            # 人工停手（r1063 T6）：最高优先级、单独落盘（`strategy_halt.json`）。
            try:
                body = self._post_json("停手")
                if body is None:
                    return
                code, out = _strategy_halt_api(body)
                self._json(out, code)
            except Exception as e:
                self._json({"ok": False,
                            "err": "停手请求处理失败：%s" % str(e)[:120]}, 500)
        elif self.path == "/api/strategy/resume":
            # 恢复人工停手：只解人下的命令，**不碰**自动熔断（那是解除）
            try:
                body = self._post_json("恢复")
                if body is None:
                    return
                code, out = _strategy_resume_api(body)
                self._json(out, code)
            except Exception as e:
                self._json({"ok": False,
                            "err": "恢复请求处理失败：%s" % str(e)[:120]}, 500)
        elif self.path == "/api/round/abort":
            # 中断本轮：递增轮次代际，worker 在下一个检查点收工
            try:
                body = self._post_json("中断")
                if body is None:
                    return
                code, out = _round_abort_api(body)
                self._json(out, code)
            except Exception as e:
                self._json({"ok": False,
                            "err": "中断请求处理失败：%s" % str(e)[:120]}, 500)
        elif self.path == "/api/pacing/reset":
            try:
                body = self._post_json("解除")
                if body is None:
                    return
                plat = str(body.get("platform") or "").strip()
                if plat not in _ALL_PLATS:
                    self._json({"ok": False, "err": "未知渠道"}, 400)
                    return
                pac = getattr(_State, "pacing", None)
                if pac is None or not plat:
                    self._json({"ok": False,
                                "err": "节流未挂接或缺少 platform"}, 400)
                    return
                before = ((pac.snapshot().get("channels") or {})
                          .get(plat) or {})
                # 幂等（r480）：解除后面紧跟一次真实单查（10–60 秒）。第二个
                # 请求并发进来会再跑一次探测，两次结果互相覆盖——用户看到
                # 的可能不是最后一次。前端 PACE_BUSY 只挡同一页连点，第二个
                # 标签页/直接调接口必须由这里兜住。
                _rsg = _State.reset_open
                with _State.reset_lock:
                    if plat in _rsg:
                        self._json({"ok": False, "dup": True,
                                    "platform": plat,
                                    "err": "正在解除并单查探测该渠道，"
                                           "等这次结果出来再看"}, 409)
                        return
                    _rsg.add(plat)
                try:
                    pac.reset(plat)
                except Exception:
                    with _State.reset_lock:
                        _rsg.discard(plat)
                    raise
                try:
                    # 「解除自动熔断」只解**自动**档位（r1063 T6）：节流闸门解除
                    # 之外，策略层的自动状态机（`policy_state.json` 的 blocked/
                    # 余温）同批清掉——否则界面显示「已解除」而策略层还在拦，
                    # 用户以为按钮坏了。**人工停手不动**（那是 `strategy_halt.json`，
                    # 只有 `/api/strategy/resume` 或到期能解）：两个按钮两件事，
                    # 绑在一起就会出现「点一下解除，顺手把人的停手也解了」——
                    # 操作员最不能接受的一类意外。
                    # 放在这个 try 里（不是 pac.reset 旁边）：失败要**提前回**，
                    # 而 `_State.reset_open` 只在 finally 里释放。
                    _pa_ok, _pa_err, _pa_led = _auto_reset(plat)
                    if not _pa_ok:
                        self._json(_ledger_tail(
                            {"ok": False, "err": _pa_err, "platform": plat,
                             "policy_reset": False, "before": before},
                            _pa_led, "解除自动熔断"), 500)
                        return
                    _State.logger.info(
                        "[干预] 手动解除 %s 熔断（原剩余 %ss · 原因 %s）",
                        plat, before.get("remain_s", 0),
                        before.get("reason") or "-")
                    after = ((pac.snapshot().get("channels") or {})
                             .get(plat) or {})
                    # 解除只是"允许再试"，不等于"已经恢复"。立刻单查一次，
                    # 用真实结果落账；未通就重新熔断，避免把"解除了"显示成
                    # "好了"（这是干预后一致性最容易被破坏的一处）。
                    _probe = None
                    _cb = getattr(_State, "probe_cb", None)
                    if _cb is not None:
                        try:
                            _probe = _cb(plat, scope="")
                        except Exception as _pe:
                            _probe = {"ok": False, "err": str(_pe)[:120]}
                    _ok = bool((_probe or {}).get("rows"))
                    _rows = int((_probe or {}).get("rows") or 0)
                    if _probe is not None and not _ok:
                        try:
                            # **这一条是渠道级结论，故意不递 path/dim**（波次六
                            # 写明，别让下一个读的人猜）：上面 `_cb(plat,
                            # scope="")` 探的是整家渠道（`scope=""` = 不分
                            # 国内/国际），拿回来的只有一个「出数/没出数」，
                            # 既不知道栽在哪条链路、也不知道属于哪个维度；
                            # 硬填 `path=`/`dim=` 等于把「整家没出数」编成
                            # 「某条路被风控」，会让 `渠道|链路` 那一层凭空
                            # 多出一条不存在的证据。要路径级证据只能等真实
                            # 采集回来（那时 `safe_fetch` 自己会带上 path）。
                            pac.observe(plat, ["blocked"], "手动解除后探测未出数")
                        except Exception:
                            pass
                    after2 = ((pac.snapshot().get("channels") or {})
                              .get(plat) or {})
                    try:
                        from core.storage import PriceStorage as _PS
                        _dbp = _anchored(
                            ((_State.cfg or {}).get("output") or {}).get(
                                "db_path"), "data/prices.db")
                        _PS(_dbp).save_intervention(
                            plat, "reset", ok=_ok,
                            rows=_rows,
                            before="%s/%s" % (before.get("state"),
                                              before.get("reason")),
                            after="%s/%s" % (after2.get("state"),
                                             after2.get("reason")),
                            note=("手动解除后单查：%s" % (
                                ("出数 %d 条" % _rows) if _ok
                                else ((_probe or {}).get("err") or "未出数"))),
                            ms=int((_probe or {}).get("ms") or 0))
                    except Exception:
                        pass

                finally:
                    with _State.reset_lock:
                        _rsg.discard(plat)
                self._json({"ok": True, "platform": plat,
                            "policy_reset": True, "ledger": bool(_pa_led),
                            "before": before, "after": after2,
                            "probe": _probe})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/channel/probe":
            try:
                body = self._post_json("自检")
                if body is None:
                    return
                plat = str(body.get("platform") or "").strip()
                if plat not in _ALL_PLATS:
                    self._json({"ok": False, "err": "未知渠道"}, 400)
                    return
                cb = getattr(_State, "probe_cb", None)
                if cb is None:
                    self._json({"ok": False,
                                "err": "自检未挂接或缺少 platform"}, 400)
                    return
                _scope = str(body.get("scope") or "").strip().lower()
                if _scope not in ("", "dom", "intl"):
                    self._json({"ok": False, "err": "scope 必须是 dom/intl/空"}, 400)
                    return
                _out = cb(plat, scope=_scope)
                # r676：把**本次真实查询**的结果并入登录态证据（与探针任务
                # 写的是同一本账）。此前 /api/channel/probe 出数只写路径账/
                # 干预账，登录卡看不到——用户点完「核验」状态不变，读作
                # 「核验没效果」。只认明确证据：出数=可用；有 login/blocked
                # 通路=被拦；0 条且无拦截证据**不**下任何登录结论（empty 可能
                # 就是无票，不能反推会话失效）。
                try:
                    if isinstance(_out, dict) and _out.get("ok"):
                        _q = _out.get("query") or []
                        _sc = str(_out.get("scope") or "")
                        _rows = int(_out.get("rows") or 0)
                        if _rows > 0 and len(_q) >= 3:
                            _record_probe_auth(plat, _sc or "dom", _rows,
                                               _q[0], _q[1], _q[2])
                        elif not _rows:
                            _bad = [x for x in (_out.get("paths") or [])
                                    if str(x.get("status")) in
                                    ("login", "blocked")]
                            if _bad and len(_q) >= 3:
                                _b0 = _bad[0]
                                _record_probe_auth_reject(
                                    plat, _sc or "dom",
                                    "登录墙" if str(_b0.get("status")) == "login"
                                    else "人机验证",
                                    _q[0], _q[1], _q[2],
                                    path=str(_b0.get("path") or ""))
                except Exception:
                    _State.logger.warning("[自检] 登录态证据写入失败（不影响结果）")
                self._json(_out)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/channel/verify":
            try:
                body = self._post_json("验证")
                if body is None:
                    return
                plat = str(body.get("platform") or "").strip()
                if plat not in _ALL_PLATS:
                    self._json({"ok": False, "err": "未知渠道"}, 400)
                    return
                if plat.startswith("app_"):
                    self._json({"ok": False, "app_login": True,
                                "platform": plat,
                                "err": "App 渠道没有网页验证窗：请用「渠道登录」"
                                       "的内嵌真机画面完成登录"})
                    return
                cb = getattr(_State, "verify_cb", None)
                if cb is None or not plat:
                    self._json({"ok": False,
                                "err": "验证窗口未挂接或缺少 platform"}, 400)
                    return
                self._json(cb(plat))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/channel/warmup":
            try:
                body = self._post_json("预热")
                if body is None:
                    return
                plat = str(body.get("platform") or "").strip()
                if plat not in _ALL_PLATS:
                    self._json({"ok": False, "err": "未知渠道"}, 400)
                    return
                cb = getattr(_State, "warm_cb", None)
                if cb is None or not plat:
                    self._json({"ok": False,
                                "err": "预热未挂接或缺少 platform"}, 400)
                    return
                out = cb(plat)
                _State.logger.info("[干预] 手动预热 %s → %s",
                                   plat, "成功" if out.get("ok") else out.get("err"))
                self._json(out)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/channel/reset-app":
            # 清某个 App 的本地数据（r1063 T87）：平台重新评估设备的最便宜一步。
            try:
                body = self._post_json("清 App 数据")
                if body is None:
                    return
                plat = str(body.get("platform") or "").strip()
                if plat not in _ALL_PLATS:
                    self._json({"ok": False, "err": "未知渠道"}, 400)
                    return
                if plat not in _APP_CHANNELS:
                    self._json({"ok": False,
                                "err": "只有 App 渠道有「App 数据」可清（浏览器渠道请用重登/清会话）"},
                               400)
                    return
                if not body.get("confirm"):
                    self._json({"ok": False, "need_confirm": True,
                                "err": "这是破坏性操作：会清掉该 App 的登录态与本地缓存，"
                                       "需带 confirm=true 再调一次"}, 400)
                    return
                from crawlers import REGISTRY as _REG
                pkg = str(getattr(_REG.get(plat), "package", "") or "")
                if not pkg:
                    self._json({"ok": False, "err": "该渠道没有包名"}, 400)
                    return
                from core.android import emulator as _emu
                dev = _emu.device(_State.cfg or {})
                out = dev._sh("shell", "pm", "clear", pkg) or ""
                ok = "Success" in str(out)
                _State.logger.warning("[干预] 清 App 数据 %s（%s）→ %s",
                                      plat, pkg, str(out).strip()[:60])
                if ok:
                    # 清完就没有登录墙了，记忆也要清掉，否则窗口内不会再去试。
                    # r1063 T131：统一走 _clear_login_wall_memo（连 app_gone 一起清）
                    try:
                        _clear_login_wall_memo(plat, "")
                    except Exception:
                        pass
                self._json({"ok": ok, "plat": plat, "pkg": pkg,
                            "detail": str(out).strip()[:120],
                            "next": "该渠道需重新登录（App 内登一次即可）" if ok
                                    else "pm clear 未返回 Success，请查设备连接"})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/channel/clear-wall":
            # 清登录墙/自杀熔断记忆（r1063 T131）：非破坏性，只让下一轮立刻重试。
            # 适用：换了出口 IP、重启过模拟器、在 App 里登好了但没走槽位登录流程。
            try:
                body = self._post_json("清登录墙")
                if body is None:
                    return
                plat = str(body.get("platform") or "").strip()
                if plat not in _ALL_PLATS:
                    self._json({"ok": False, "err": "未知渠道"}, 400)
                    return
                cleared = _clear_login_wall_memo(plat, "")
                _State.logger.info("[干预] 清登录墙 %s → %s", plat,
                                   "、".join(cleared) or "没有需要清的")
                self._json({"ok": True, "plat": plat, "cleared": cleared,
                            "next": ("已清 %d 项，下一轮会立刻重试" % len(cleared))
                                    if cleared else
                                    "本来就没有墙，下一轮照常"})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/push":
            if st.report_push is None:
                self._json({"ok": False, "err": "report 未挂接"}, 500)
                return
            try:
                ok = st.report_push()
                self._json({"ok": bool(ok)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/preview":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(_preview_payload(int(body.get("user", 0) or 0)))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


_BUILD_STAMP = {"v": ""}


def _build_stamp() -> str:
    """构建戳：**唯一实现在 `core.buildstamp`**（webui.py + webui_assets/*）。

    以前这里自己算一份，`tools/demo_build.py` 与 `tools/release_align_check.py`
    各算一份（只算 webui.py），模板外置后三处口径分叉，烘焙站点与运行时戳
    永远对不上。现在统一委托，谁要算戳都调 `core.buildstamp.stamp()`。
    """
    if _BUILD_STAMP["v"]:
        return _BUILD_STAMP["v"]
    try:
        from core.buildstamp import stamp_of
        _BUILD_STAMP["v"] = stamp_of(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        _BUILD_STAMP["v"] = "unknown"
    return _BUILD_STAMP["v"]


def _page_html(version):
    """PAGE 注入页面代际（__PAGEVER__ → 运行版本）：页面 load() 轮询
    比对 state.version，失配亮「刷新」横幅——Cache-Control: no-cache
    管不住重启窗口期一直开着的旧标签页（今日「布局抖动/点击不通」
    实报=陈旧标签页跑着中间代际代码，12 档窗宽矩阵证实现行代码零振荡）。
    demo/烘焙站传 demo 代际同律，令牌必须替换勿泄漏。

    同时注入通路名表（r658）：健康卡的「分通路」小标与 core.pacing 的
    路径劣化提示都要给 `app-list` / `android-runtime` 这类账本键名
    一个中文名。表在 core/channels.py 单源，前端不许再抄一份。
    """
    from core.channels import PATH_CN as _PATH_CN
    return (PAGE
            .replace("__PATH_CN__",
                     json.dumps(_PATH_CN, ensure_ascii=False,
                                sort_keys=True))
            .replace("__PAGEVER__", version or "")
            .replace("__PAGEBUILD__", _build_stamp()))


_PAGE_SNAP = {"ver": None, "body": b"", "etag": "", "gz": b""}
_PAGE_SNAP_LOCK = threading.Lock()


def _page_snap(version):
    """首页三元组 (body, etag, gz) 按代际缓存：整页只 replace/
    压缩一次；同代际并发请求共用一份 gz，避免每导航重复 6 级压缩。"""
    ver = version or ""
    with _PAGE_SNAP_LOCK:
        if _PAGE_SNAP["ver"] == ver:
            return _PAGE_SNAP["body"], _PAGE_SNAP["etag"], _PAGE_SNAP["gz"]
        body = _page_html(ver).encode("utf-8")
        etag = '"p-%s-%s"' % (
            re.sub(r"[^A-Za-z0-9_.-]", "", ver) or "0",
            hashlib.sha1(body).hexdigest()[:16])
        _PAGE_SNAP.update(ver=ver, body=body, etag=etag,
                          gz=gzip.compress(body, 6))
        return body, etag, _PAGE_SNAP["gz"]


_RADAR_AUTO_STARTED = False


def _radar_auto_query(r, today=None):
    """Build the auto-loop query; clamp a stale start to today.

    The user's saved range may start yesterday while the end is still in the
    future. parse_query() correctly rejects past starts for ad-hoc queries,
    but the background loop must keep monitoring the remaining range instead
    of failing forever after midnight.
    """
    from datetime import date as _date
    frm = str((r or {}).get("from_name") or (r or {}).get("from") or "").strip()
    start = str((r or {}).get("start") or "").strip()
    end = str((r or {}).get("end") or "").strip()
    if not (frm and start and end):
        return None, "incomplete"
    today = today or _date.today().isoformat()
    try:
        _date.fromisoformat(start)
        _date.fromisoformat(end)
    except ValueError:
        return None, "invalid"
    if end < today:
        return None, "ended"
    why = ""
    if start < today:
        start, why = today, "clamped"
    return {
        "from": frm,
        "to": str((r or {}).get("to_name") or (r or {}).get("to") or ""),
        "nationwide": bool((r or {}).get("nationwide")),
        "start": start, "end": end,
        "channels": (r or {}).get("channels") or [],
    }, why


def _radar_auto_loop():
    """Best-effort radar monitoring: every 2h while the console runs.

    Skips while a scan holds the job lock (avoid browser/profile contention),
    records only official calendar/board prices, and never invents rows.
    """
    from core.special_radar import build_radar
    first = True
    while True:
        # 首轮 90s 后即积累一次快照，之后每 2 小时；旧实现先睡 2 小时
        # 才第一次取数，控制台刚启动时监控日历会长时间空窗。
        time.sleep(90 if first else 7200)
        first = False
        try:
            if DEMO["on"] or not _State.users:
                continue
            if _State.lock.locked():
                _State.logger.info("[雷达监控] 扫描进行中，跳过本轮快照")
                continue
            cfg = _effective_crawler_config()
            for u in list(_State.users)[:3]:
                r = (u.get("special_radar") if isinstance(u, dict)
                     else getattr(u, "special_radar", None)) or {}
                q, why = _radar_auto_query(r)
                if not q:
                    _State.logger.info("[雷达监控] 跳过 %s（%s）",
                                       (u.get("name") if isinstance(u, dict)
                                        else getattr(u, "name", "")), why)
                    continue
                if why == "clamped":
                    _State.logger.warning(
                        "[雷达监控] 开始日期已过，自动从 %s 继续", q["start"])
                try:
                    out = build_radar({
                        "user": (u.get("name") if isinstance(u, dict)
                                 else getattr(u, "name", "")),
                        **q,
                    }, _State.logger, proxy=str(cfg.get("proxy") or ""),
                        user_data_dir=str(cfg.get("user_data_dir") or "user_data"))
                    n = _radar_save_result(out, source="auto")
                    _State.logger.info("[雷达监控] 快照 %d 条", n)
                except Exception as e:
                    _State.logger.warning("[雷达监控] 单用户失败: %s", e)
                time.sleep(60)
        except Exception as e:
            try:
                _State.logger.warning("[雷达监控] 循环异常: %s", e)
            except Exception:
                pass


def _candidate_ports(port, tries: int = 10):
    """端口候选序列：原端口，然后 +1、+2……（r1195 零配置要求）。

    为什么要自动挪位：双击启动的人遇到"端口被占"只会看到一句英文报错，
    然后以为程序坏了；而最常见的占用源就是**上一次没关干净的自己**。
    """
    try:
        base = int(port)
    except (TypeError, ValueError):
        base = 8765
    return [base + i for i in range(max(1, int(tries or 1)))]


def _bind_console(host: str, port, tries: int = 10):
    """逐个候选端口尝试绑定，返回 `(srv, 实际端口, 最后错误)`。

    成功即止；全失败返回 `(None, 0, 最后错误)`——由调用方决定怎么告警。
    本函数不打日志、不吞语义，便于单测（`tests/test_r1195_port_fallback.py`）。
    """
    last = None
    for p in _candidate_ports(port, tries):
        try:
            return _Srv((host, p), _Handler), p, None
        except OSError as e:          # WinError 10048 / EADDRINUSE 都落在这里
            last = e
            continue
    return None, 0, last


def start_web(cfg, job, report_push, logger=None, users=None,
              reload_cb=None, config_path="config.yaml", version="",
              login_saved_cb=None, alerters=None):
    """在守护线程里启动本地控制台；失败只告警不中断监控。"""
    _State.cfg = cfg
    import copy as _copy
    _State.boot_cfg = _copy.deepcopy(cfg)
    _State.users = users
    _State.alerters = list(alerters or [])
    _State.job = job
    _State.report_push = report_push
    _State.reload_cb = reload_cb
    _State.config_path = config_path
    _State.version = version
    _State.login_saved_cb = login_saved_cb
    if logger:
        _State.logger = logger
    port = int((cfg.get("web") or {}).get("port", 8765))
    # 监听地址可配（web.host，默认 127.0.0.1）：手机端钉钉「完整详情」
    # 依赖局域网可达——服务只绑回环时 base_url 配了也连不上，host 必须可配
    host = _bind_host(cfg)
    try:
        # r1195：端口被占用时自动 +1 再试（最多 10 个），并把真实端口说清楚。
        # 以前这里一绑不上就只记一句"启动失败"，用户看到的是"打开没反应"。
        srv, actual, bind_err = _bind_console(host, port)
        if srv is None:
            _State.logger.warning(
                "[控制台] 端口 %d~%d 都被占用或不可绑，控制台没起来：%s"
                "；关掉占用的实例或改 web.port 后重启",
                port, port + 9, bind_err)
            return None
        if actual != int(port):
            _State.logger.warning(
                "[控制台] 端口 %d 被占用，已自动改用 %d —— 请访问 "
                "http://127.0.0.1:%d （原端口可能是上一次没退干净的实例）",
                int(port), actual, actual)
        _State.srv = srv
        _State.port = actual
        _State.listen = "{}:{}".format(host, actual)
        _State.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        _State.logger.info("[控制台] http://%s:%d （随监控常驻）",
                           host if host != "0.0.0.0" else "0.0.0.0(全网卡)",
                           actual)
        # 启动预热：后台先把 /api/state 全量建好，首个打开控制台的请求
        # 直接命中热缓存（全历史重算 11~14s 不落在用户首屏）
        def _warm():
            time.sleep(1.5)
            _state_rebuild_async()
        threading.Thread(target=_warm, daemon=True, name="state-warm").start()
        # r1515：十五轴矩阵是 CPU 密集的（首次 5s），首个打开健康/配置的人
        # 不该替全站付这笔钱。state 预热之后再排一次，开面板时直接命中缓存。
        def _warm_strat():
            time.sleep(3.0)
            try:
                _strategy_audit_cached()
            except Exception:
                pass
        threading.Thread(target=_warm_strat, daemon=True,
                         name="strategy-warm").start()
        global _RADAR_AUTO_STARTED
        if not _RADAR_AUTO_STARTED and not DEMO["on"]:
            _RADAR_AUTO_STARTED = True
            threading.Thread(target=_radar_auto_loop, daemon=True,
                             name="radar-auto").start()
        return srv
    except Exception as e:
        _State.logger.warning("[控制台] 启动失败: %s", e)
        return None


def rebind_web(port: int) -> bool:
    """控制台原地换绑端口：配置页改端口保存即生效，无需重启进程。

    旧 server 异步关闭（让当前响应先送回浏览器），随后新端口起监听。"""
    old = getattr(_State, "srv", None)

    def _do():
        try:
            if old:
                old.shutdown()
                old.server_close()
        except Exception:
            pass
        try:
            host = _bind_host(_State.cfg)
            srv = _Srv((host, int(port)), _Handler)
            _State.srv = srv
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _State.logger.info("[控制台] 已热切换至 http://127.0.0.1:%d",
                               int(port))
            # state 缓存签名不含端口：只作废签名让下个请求走 SWR
            # （先回旧值、后台按新端口重建）——连 payload 一起清会让
            # 首个 /api/state 落入冷启动首建全量重算，换绑后分钟级假死
            with _STATE_LOCK:
                _STATE_CACHE["sig"] = None
        except Exception as e:
            _State.logger.warning("[控制台] 端口 %s 切换失败: %s", port, e)

    threading.Timer(0.4, _do).start()
    return True


def _demo_seed_watches(db, state=None):
    """演示态播种 2 个关注航班：让总览关注卡/关注台/走势在零配置下可见。
    只写临时演示库旁的 flight_watch.json，不触碰真实 data/。"""
    try:
        state = state or _latest_state()
        rows = ((state.get("users") or [{}])[0].get("flights") or [])
        picked, seen = [], set()
        for f in rows:
            if len(picked) >= 2:
                break
            if not (f.get("code") and f.get("depTime") and f.get("arrTime")
                    and f.get("date")):
                continue
            k = (f.get("from"), f.get("to"), f.get("date"))
            if k in seen:
                continue
            seen.add(k)
            picked.append(f)
        watches = []
        for f in picked:
            try:
                e = _watch_entry({
                    "from": f.get("from"), "to": f.get("to"),
                    "date": f.get("date"), "code": f.get("code"),
                    "depTime": f.get("depTime"), "arrTime": f.get("arrTime"),
                    "trans": f.get("trans") or "",
                    "cross": f.get("cross") or f.get("crossDayDesc") or "",
                    "stop": bool(f.get("stop")),
                    "cabin": f.get("cabin") or "",
                    "channels": list(_WATCH_PLATS),
                })
                price = f.get("price")
                e["target"] = int(round(float(price) * 0.9)) if price else None
                e["note"] = "演示：目标价与渠道可在配置台独立调整"
                watches.append(e)
            except Exception:
                pass
        if watches:
            _watch_write({"演示用户": watches})
            _WATCH_CACHE.clear()
    except Exception:
        pass


def _demo_db_path(port):
    """demo 合成库按端口分文件：全体实例共用单一 %TEMP%/ticket_demo_prices.db
    时，并发启动会各自重建同一文件，写锁让后者卡在「进程活、不监听」
    （r318 fixture 实测；并发全量下每个 webui 测试模块都会起一个 demo）。"""
    return os.path.join(tempfile.gettempdir(),
                        "ticket_demo_prices_%d.db" % int(port))


def _demo_db_sweep(keep_port, max_age_s=3600):
    """清掉历史遗留的 demo 库（r498）。实测临时目录里堆了 37 个、
    合计 182MB——每个测试/演示进程按端口建一个，从不回收，长跑会占满
    临时盘。

    只删**同时满足**两个条件的：① 不是本次端口；② 超过 1 小时没被写过。
    活跃实例会持续写它自己的库，mtime 很新，不会被误删；正在被别的实例
    占用的旧文件删不掉（Windows 会抛 OSError），静默跳过即可。
    """
    now = time.time()
    removed = 0
    try:
        # 整个函数体都在 try 内：gettempdir() 可能因环境异常抛错，而清理
        # 是尽力而为——绝不能让启动路径因此崩掉。keep 的计算也走它，
        # 所以同样放进 try。
        keep = os.path.basename(_demo_db_path(keep_port))
        base = tempfile.gettempdir()
        for name in os.listdir(base):
            if not (name.startswith("ticket_demo_prices_")
                    and name.endswith(".db")):
                continue
            if name == keep:
                continue
            p = os.path.join(base, name)
            try:
                if now - os.path.getmtime(p) < max_age_s:
                    continue
                os.remove(p)
                removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def _demo_main():
    """`python webui.py --demo`：零配置演示控制台（开源访客一键体验）。

    生成确定性合成库（系统临时目录，不污染仓库），渲染链路与真机完全一致。"""
    import argparse
    import os
    import tempfile
    ap = argparse.ArgumentParser(description="机票监控控制台 · 演示模式")
    ap.add_argument("--demo", action="store_true", help="启动演示数据控制台")
    ap.add_argument("--port", type=int, default=8765,
                    help="控制台端口（演示模式配合截图脚本用 8799）")
    args = ap.parse_args()
    if not args.demo:
        print("控制台由 main.py 随监控启动；零配置体验请加 --demo")
        return
    from core.demo import build_demo_db, demo_cfg, demo_routes
    from core.models import Route
    # 先回收历史遗留库再建本次的（r498，见 _demo_db_sweep 注释）
    try:
        _swept = _demo_db_sweep(args.port)
        if _swept:
            print("已清理 %d 个历史演示库（临时目录）" % _swept)
    except Exception:
        pass
    # 先占端口再建库（r499）：顺序反了会毁数据。实测链路——同一端口起第二个
    # demo 时，旧代码先 build_demo_db（executescript 重建整库），再绑定端口；
    # Windows 下 allow_reuse_address=False，绑定必然失败退出，但那时第一个
    # 实例正在用的库**已经被清空重建**，且没有任何提示。
    # 先绑定：占不到端口就在动数据之前退出。
    try:
        srv = _Srv(("127.0.0.1", args.port), _Handler)
    except OSError as e:
        print(f"⚠ 端口 {args.port} 已被占用，本次演示未启动"
              f"（若是另一个演示实例，直接用它即可）：{e}")
        return
    db = _demo_db_path(args.port)
    build_demo_db(db)
    DEMO["on"] = True
    _State.cfg = demo_cfg(db, port=args.port)
    _State.boot_cfg = demo_cfg(db, port=args.port)
    _State.users = [{
        "name": "演示用户",
        "routes": [Route(
            from_code=r["from"], from_name=r["from_name"],
            to_code=r["to"], to_name=r["to_name"], dates=r["dates"],
            alert_direct=r["alert_direct"],
            alert_transfer=r["alert_transfer"],
            transfer_arrival_max=r["transfer_arrival_max"],
            # 衔接下限/行李直挂曾未映射——演示静默丢失这两个配置维度
            transfer_layover_min=r.get("transfer_layover_min", 0),
            transfer_baggage=r.get("transfer_baggage", ""),
            dep_time_min=r["dep_time_min"], dep_time_max=r["dep_time_max"])
            for r in demo_routes()],
        # 演示用户默认勾选的采集渠道 = 5 家浏览器 + 已注册 App。
        # 写死 5 家会让演示的配置页只显示 5 个可勾项，而健康卡/检索/
        # 关注台都已按 7 家渲染——同一页两套渠道宇宙。
        "platforms": list(_watch_plats()),
        "notifier": {"dingtalk": {"at_mobile": "138****1234"}},
        "schedule": {"interval_minutes": 15},
    }]
    _State.version = "demo"
    global _DEMO_WATCH_PATH
    _DEMO_WATCH_PATH = os.path.join(
        tempfile.gettempdir(), "ticket_demo_watch_%d.json" % args.port)
    _demo_seed_watches(db)
    # srv 已在建库之前绑定好（r499）：这里不能再建一次，否则二次绑定必失败
    _State.listen = "127.0.0.1:{}".format(args.port)
    _State.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    # 控制台可能跑在 GBK 终端（Windows 默认）：emoji 直出会
    # UnicodeEncodeError 令演示服务启动即死（pytest/截图脚本实锤）
    print(f"[DEMO] 演示控制台: http://127.0.0.1:{args.port}  （数据为合成，Ctrl+C 退出）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # 合成库每次启动按需重建，退出即删：批量起 demo 时不在 %TEMP% 留库
        try:
            os.remove(db)
        except OSError:
            pass


if __name__ == "__main__":
    _demo_main()
