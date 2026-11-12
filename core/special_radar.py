# -*- coding: utf-8 -*-
"""特价雷达：按用户航线 + 日期范围聚合低价日历/榜单。

只做“低价发现”：Ctrip 日历/全国榜、Fliggy 榜单、Tuniu 榜单为真实源；
Qunar/Tongcheng 尚无已验证的自定义航线日历，返回 not_connected，不拿
通用页冒充。任何日历/榜单价都不是航班明细，明细由探针任务获取。
"""
import hashlib
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from core.citydata import CITY, CODE_NAME
from core.intl import (INTL_CITY_HOT, INTL_CITY_NAME, INTL_CITY_SHORT,
                       airport_city_code)
from core.models import PRICE_MAX
# 「链路被策略停用」的唯一词面（与闸门同一个常量，别在这里抄一句中文）
from core.pacing import PATH_DISABLED
from core.specials import (
    SPECIAL_CAPABILITY,
    SpecialDeal,
    SpecialWatch,
    ctrip_calendar_deals,
    deals_from_ctrip_board,
    deals_from_fliggy_board,
    deals_from_tuniu,
)
# 闸门等待封顶（铁律 I6）：与采集器同一个常量，不在雷达里另抄一份数字。
# `crawlers.base` 早被 `crawlers.special` 拉进来（`profile_headers`），
# 这里没有新增依赖。
from crawlers.base import PATH_GATE_SLEEP_CAP_S
from crawlers.special import (
    fetch_ctrip_board,
    fetch_ctrip_calendar,
    fetch_fliggy_board,
    fetch_fliggy_calendar,
    fetch_tongcheng_calendar,
    fetch_tuniu_board,
    fetch_tuniu_calendar,
)

_IATA3 = re.compile(r"^[A-Z]{3}$")
_RADAR_MAX_DAYS = 90
# 去哪儿 App 低价页日期带的实测宽度：今天起 14 天（r815a 真机 14 天）。
_APP_QUNAR_STRIP_DAYS = 14
# 可查询渠道 = **能力表里真有发现源**的渠道，由 SPECIAL_CAPABILITY 派生。
# 手抄白名单曾漏掉 `app_zhixing`：r732 已把智行「特价」接成逐天报价源，
# 但这里没跟上，于是请求里的智行被静默丢弃（勾得到、点了不算）。
# 新增渠道时只改能力表；`test_r709` 会核对两边互为镜像。
# 可查询渠道 = **能力表里声明过**的渠道。含 sources 为空的声明
# （如 2026-11-02 起的 app_qunar）：保留查询能力，结果记 not_connected
# 并带原因，不能让渠道从雷达界面消失（用户要求「统一监控」）。
_CHANNELS = tuple(SPECIAL_CAPABILITY)

# 发现层短时缓存/冷却：同一条件重复点「查低价」不重复打源
_FLIGGY_CACHE = {}
_FLIGGY_COOLDOWN_UNTIL = 0.0
_QUNAR_CACHE = {}
_TUNIU_CACHE = {}
_TONGCHENG_CACHE = {}
_RADAR_CACHE_TTL = 180.0
_FLIGGY_COOLDOWN_S = 60.0
# fetch_fliggy_calendar 默认 20s；返回 None 且耗时接近超时视为网络超时，
# 否则按源软拒（65B success:false）归类。两类原因必须分别如实上报。
_FLIGGY_TIMEOUT_S = 20.0
_FLIGGY_TIMEOUT_RATIO = 0.9

# 价格口径词面（来源可核实才标含税/裸价，其余一律未知）
_BASIS_LABEL = {"tax_included": "含税总价", "bare": "裸价不含税",
                "unknown": "口径未标注"}

# ── 链路闸门 + 每源预算（r1063 T11）───────────────────────────────────
#
# 四个浏览器发现源（携程/飞猪/途牛/同程）在**真外发之前**先问一次链路闸门
# （`core.pacing.Pacing.gate_path`），各源另有一个秒级预算。雷达不是法外
# 之地：它打的是同一批上游（m.ctrip.com / r.fliggy.com / wx.17u.cn /
# flight-api.tuniu.com），操作员在策略里停用某家的低价日历，要的就是
# 「这家别再打了」；雷达绕过去，等于闸门只在采集器那一侧成立。
#
# 链路 id 用 `core/channels.PATH_CN` 里的**真实通路名**：这四家源就是该家
# 的**低价日历**通路，所以 `dim` 恒为 `low_fare`、`path` 用 `日历`。于是
# `crawler.strategy_overrides` 里的 `tongcheng/low_fare/日历` 这一条同时管住
# 采集器的日历和雷达的发现源——同一件事只有一个开关，不为雷达另造一条
# 能力矩阵里不存在的通路 id。
_RADAR_DIM = "low_fare"
_RADAR_PATH = "日历"
# 预算 pid：`core/strategy_contract.py` 里登记的名字是 `budget.fetch_s`
# （cfg `android.fetch_budget_s`，默认 540 秒，0 = 不限）。T11 的 brief 把它
# 写作 `budget.value`——那是改名前的叫法，仓里**没有**这个 pid，直接
# `resolve("budget.value")` 会当场 KeyError。这里读契约里的真名；契约默认值
# 只在本文件兜底一份，参数层读不到就按它算，绝不让雷达因参数层异常而停采。
_BUDGET_PID = "budget.fetch_s"
_BUDGET_DEFAULT_S = 540.0
# 闸门上下文：懒建一次、进程内复用（建不出来就是 None，闸门按放行处理）。
# 加锁做双检（复核第一轮）：雷达在 webui 的多线程请求里跑，无锁懒建会让
# 并发首调各造一个 `Pacing`，链路桶的账立刻分家——「刚发过」只记在其中
# 一份里，限速于是失效。
_RADAR_PACING = None
_RADAR_PACING_LOCK = threading.Lock()


def _pacing_ctx():
    """雷达共享的链路闸门上下文（懒建一次，之后复用）。

    与采集器各持一份 `Pacing` 不同，雷达手上没有 crawler 实例、也没有配置
    文件（`build_radar` 的签名不接 cfg），所以按 `Pacing({})` 的出厂值建：
    真正生效的速率与停用值来自**参数层**（`Pacing._param` →
    `strategy_params.resolve`，每次判定现读），本实例 cfg 只在参数层查不到
    时兜底。

    闸门是外发的必经路径：建不出来只能放行（并让调用方留痕），在这里抛
    异常等于把整个特价雷达停掉。
    """
    global _RADAR_PACING
    pac = _RADAR_PACING            # 快路径：只读一次属性，不加锁
    if pac is not None:
        return pac or None
    with _RADAR_PACING_LOCK:
        if _RADAR_PACING is None:
            try:
                from core.pacing import Pacing
                _RADAR_PACING = Pacing({})
            except Exception:
                _RADAR_PACING = False    # 失败只试一次，别每次调用都重建
        return _RADAR_PACING or None


def _gate_path(plat, logger=None, *, grab=True):
    """这条发现源**能不能发**：能 → `""`；不能 → 停用/冷却的完整原因。

    口径与采集器的 `path_gate()` 一致（`crawlers/base.py`），只做三件事：
    **等要给闸门、等待封顶、只记链路桶**。

    * 被拒只跳**这一条源**，调用方不许用它 `return` 整个查询、也不许记
      `error`（那是「对方拒绝」）。拿到的原因交给 `_paced_reject` 拼成
      「我方按策略克制」的 `unsupported`。
    * 等待封顶 `PATH_GATE_SLEEP_CAP_S`（铁律 I6），且不在锁内睡。
    * 记账**只写 `渠道|链路` 桶**（`channel=False`）：渠道桶由调度按轮记，
      这里再记一次就是重复计数（`per_minute` 半减、`min_gap` 翻倍）。

    `grab=False` 是**只问不动账**（复核第一轮）：缓存命中那一轮没有任何
    外发，既不该写链路桶，也不该为一个发不出去的请求去等一趟限速。

    调用点位置：有缓存的源（飞猪/途牛/同程/去哪儿）在**缓存命中之后**才
    `grab`；携程没有缓存，闸门就在函数最前面。
    """
    pac = _pacing_ctx()
    if pac is None:
        return ""
    try:
        allow, wait_s, why = pac.gate_path(plat, _RADAR_DIM, _RADAR_PATH)
    except Exception as e:
        if logger is not None:
            logger.warning("[特价雷达·%s] 链路闸门判定失败（%s）：按放行处理",
                           plat, e)
        return ""
    if not allow:
        return str(why or PATH_DISABLED)
    if not grab:
        return ""
    try:
        wait = float(wait_s or 0)
    except (TypeError, ValueError):
        wait = 0.0
    if wait > 0:
        time.sleep(min(wait, PATH_GATE_SLEEP_CAP_S))
    try:
        pac.record(plat, path=_RADAR_PATH, channel=False)
    except TypeError:      # 旧签名不认 channel= ：宁可少记一次，也别重复计数
        pass
    except Exception:
        pass
    return ""


def _paced_reject(plat, note, dim="", path=""):
    """被链路闸门挡下时的统一返回：`unsupported` + 「我方按策略克制」。

    `paced` 的语义是「**我方**按策略克制、没发请求」，与 `error`（对方拒绝）
    和 `empty`（确实没有低价）是三件不同的事，处置方向也完全不同。所以：

    * **不许**写成 0 行/`empty`（那是「这家没低价」，本仓库定义的最严重
      静默缺陷），也**不许**写 `error`（那是对方拒绝）；
    * 状态字沿用面板已有的 `unsupported`（`SRX_RADAR_ST` → 「不支持」），
      `paced=True` 单独标出来；
    * 理由句里必须带**渠道与链路**（`scope`），否则面板只报一句「被停用」，
      操作员定位不到是哪条路（复核第一轮）。
    """
    scope = "/".join([x for x in (str(plat or ""), str(dim or ""),
                                  str(path or "")) if x])
    detail = str(note or "").strip() or PATH_DISABLED
    return [], _status(
        "unsupported",
        "我方按策略克制：%s 没有发请求（%s）；不是对方拒绝，也不是无票"
        % (scope or "该链路", detail),
        paced=True, plat=plat, dim=dim, path=path)


def _cache_with_gate(hit, plat, logger=None):
    """缓存命中时只**问**一次闸门（不动账、不睡）：把「这条链路现在被停用」
    写进 `reason`。

    为什么要标（复核第一轮）：`_cache_get` 会把 180 秒内的成功结果连同当时
    的状态一起复用，面板于是看到一份**旧数据**却仍显示「可用」。链路刚被
    停用时，读者会以为停用没生效。这里补一句「已被停用 + 缓存复用」，并置
    `stopped_now=True`，让「旧数据」与「还在跑」在面板上区分得开。
    """
    rows, st = hit
    why = _gate_path(plat, logger, grab=False)
    if not why:
        return rows, st
    st = dict(st)
    base = str(st.get("reason") or "").strip()
    st["reason"] = ((base + "；") if base else "") + (
        "该链路现已被策略停用（%s），本条为缓存复用，不是本轮新采" % why)
    st["stopped_now"] = True
    return rows, st


def _on(pid: str, plat: str = "") -> bool:
    """读一条策略的 `enabled` 开关（r1063 T12c），**缺省 True＝今天的行为**。

    雷达这一侧管两条：`budget`（单源预算还生效不生效）与 `proxy_route`
    （这家渠道还走不走配置的出口）。读不懂按开启处理：一个拼错的 `flase`
    静默把预算关掉，就是「配了不生效」最难查的那一类。
    """
    try:
        from core import strategy_params as sp
        got = sp.resolve(str(pid), plat=str(plat or "")).value
    except Exception:               # 参数层不可用：按开启处理（缺省即旧行为）
        return True
    if isinstance(got, bool):
        return got
    if isinstance(got, (int, float)):
        return bool(got)
    text = str(got).strip().lower()
    if not text:
        return True
    if text in ("1", "true", "yes", "on", "y", "是", "开"):
        return True
    if text in ("0", "false", "no", "off", "n", "否", "关"):
        return False
    return True


def _budget_s(plat) -> float:
    """该渠道发现源的**单源**秒级预算；`0` = 不限（与 Android 采集同口径）。

    `budget.enabled` 关掉 → 一律按 `0`（不限时）返回：预算这条策略不生效 =
    这一趟扫描不设截止时刻（不是"用默认值"——默认值也会截止，那是另一回事）。
    """
    if not _on("budget.enabled", plat):
        return 0.0
    try:
        from core import strategy_params as sp
        v = float(sp.resolve(_BUDGET_PID, plat=str(plat or "")).value)
    except Exception:
        return float(_BUDGET_DEFAULT_S)
    return max(0.0, v)


def _budget_deadline(budget_s) -> float:
    """预算截止时刻；`0` = 不限（所有判定都要先看这个 0 值）。"""
    try:
        b = float(budget_s or 0)
    except (TypeError, ValueError):
        return 0.0
    return (time.time() + b) if b > 0 else 0.0


def _budget_hit(deadline) -> bool:
    """预算是否已用完。`0`（不限）**恒为 False**——别让「没配预算」变成
    「立刻收工」，那会把没配的东西读成全部停采。"""
    return bool(deadline) and time.time() >= float(deadline)


def _budget_reject(plat, rows, budget_s, extra=""):
    """预算耗尽时的统一返回：`timeout` + 「预算耗尽」，已采到的行照常返回。

    丢掉刚拿到的行是另一种静默损失；状态单独成 `timeout`，理由里写清这
    是**我方**的上限——不是对方拒绝，更不能据此说「没有票」。
    """
    out = list(rows or [])
    why = ("预算耗尽：%s 单源预算 %ds 用完，提前收工（已采 %d 行）；"
           "这是我方的预算上限，不是对方拒绝，也不能据此判断有没有票"
           % (plat, int(budget_s or 0), len(out)))
    if extra:
        why += "；" + str(extra)
    return out, _status("timeout", why, len(out), partial=bool(out),
                        budget_s=int(budget_s or 0))



@dataclass
class RadarQuery:
    user: str
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    start: date
    end: date
    channels: list
    nationwide: bool = False


def _intl_name_index() -> dict:
    """中文名 → 国际码：热榜序优先消歧（曼谷→BKK 而非 DMK），
    先收展示全名、再收搜索短名（短名已占用则不动）。"""
    hot = [c for c in INTL_CITY_HOT if c in INTL_CITY_NAME]
    order = hot + [c for c in INTL_CITY_NAME if c not in set(hot)]
    idx = {}
    for c in order:
        n = INTL_CITY_NAME.get(c)
        if n:
            idx.setdefault(n, c)
    for c in order:
        n = INTL_CITY_SHORT.get(c)
        if n:
            idx.setdefault(n, c)
    return idx


_INTL_NAME2CODE = _intl_name_index()


def _city(v) -> tuple:
    s = str(v or "").strip()
    if _IATA3.fullmatch(s.upper()):
        c = s.upper()
        return c, (CODE_NAME.get(c) or INTL_CITY_NAME.get(c) or c)
    c = CITY.get(s, "")
    if not c:
        c = _INTL_NAME2CODE.get(s, "")
    return c, (s if c else "")


def parse_query(payload: dict) -> RadarQuery:
    p = payload or {}
    fc, fn = _city(p.get("from"))
    if not fc:
        raise ValueError("出发城市无法识别")
    nationwide = bool(p.get("nationwide"))
    if nationwide:
        tc, tn = "", "全国"
    else:
        tc, tn = _city(p.get("to"))
        if not tc:
            raise ValueError("到达城市无法识别（全国模式请勾选全国）")
        if tc == fc:
            raise ValueError("出发与到达不能相同")
    try:
        start = date.fromisoformat(str(p.get("start") or ""))
        end = date.fromisoformat(str(p.get("end") or ""))
    except ValueError:
        raise ValueError("日期范围应为 YYYY-MM-DD")
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    if start < date.today():
        raise ValueError("开始日期不能早于今天")
    if (end - start).days + 1 > _RADAR_MAX_DAYS:
        raise ValueError("日期范围最多 %d 天" % _RADAR_MAX_DAYS)
    channels = [str(c) for c in (p.get("channels") or _CHANNELS)
                if c in _CHANNELS]
    if not channels:
        raise ValueError("至少选择一个渠道")
    return RadarQuery(str(p.get("user") or ""), fc, fn, tc, tn,
                      start, end, channels, nationwide)


def _watch(q: RadarQuery, days: int) -> SpecialWatch:
    return SpecialWatch(
        from_code=q.from_code, from_name=q.from_name,
        max_price=float(PRICE_MAX), days=max(1, min(180, days)),
        round_trip=False, platforms=[])


def _in_range(d: str, q: RadarQuery) -> bool:
    try:
        x = date.fromisoformat(d)
    except ValueError:
        return False
    return q.start <= x <= q.end


def normalize(deals, q: RadarQuery) -> list:
    """候选 deals -> 按日期/渠道聚合；同渠道同日期取最低。"""
    by_date = {}
    for d in deals or []:
        if not _in_range(d.date, q):
            continue
        if not q.nationwide and d.to_code and d.to_code != q.to_code:
            continue
        ch = {"ctripbd": "ctrip", "fliggycal": "fliggy",
              "tongchengcal": "tongcheng",
              "tuniucal": "tuniu"}.get(d.src, d.src)
        if ch not in q.channels:
            continue
        rec = by_date.setdefault(d.date, {})
        cur = rec.get(ch)
        if cur is None or float(d.src_price) < float(cur["price"]):
            basis = getattr(d, "price_basis", "unknown") or "unknown"
            if basis not in _BASIS_LABEL:
                basis = "unknown"
            rec[ch] = {
                "price": float(d.src_price),
                "kind": ("calendar" if d.src in
                         ("ctrip", "fliggycal", "tongchengcal", "qunar",
                          "tuniucal") else "board"),
                "src": d.src,
                "to": d.to_code or "",
                "to_name": d.to_name or "",
                "link": d.link or "",
                "discount": d.discount or "",
                "tax_included": getattr(d, "tax_included", None),
                "basis": basis,
                "basis_label": (getattr(d, "price_basis_label", "")
                                or _BASIS_LABEL[basis]),
            }
    out = []
    for d in sorted(by_date):
        rec = by_date[d]
        best_ch = min(rec, key=lambda c: rec[c]["price"])
        out.append({"date": d, "best": dict(rec[best_ch], channel=best_ch),
                    "by_channel": rec})
    return out


def _status(status, reason="", rows=0, **extra):
    out = {"status": status, "reason": reason, "rows": int(rows or 0),
           "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    out.update(extra)
    return out


def _profile_hash(q: RadarQuery, profile_root: str = "") -> str:
    """用户 + 本地 profile 身份摘要；缓存不得跨身份复用。"""
    raw = "%s|%s" % (q.user or "", profile_root or "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _cache_key(q: RadarQuery, profile_root: str = "", extra=()) -> tuple:
    return (q.user or "", _profile_hash(q, profile_root),
            q.from_code, q.to_code, q.start.isoformat(),
            q.end.isoformat(), tuple(sorted(q.channels))) + tuple(extra)


def _cache_put(cache: dict, key, rows, st: dict, profile_hash: str) -> None:
    now = time.time()
    cache[key] = {
        "ts": now,
        "rows": list(rows),
        "status": dict(st),
        "generated_at": st.get("generated_at")
        or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile_hash": profile_hash,
    }


def _cache_get(cache: dict, key, ttl: float = _RADAR_CACHE_TTL):
    """命中时重放原状态/原因/采集时间；只追加复用标记，绝不把回退或
    部分结果改写成「复用成功结果」。"""
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - float(entry.get("ts") or 0) >= ttl:
        return None
    rows = list(entry.get("rows") or [])
    orig = dict(entry.get("status") or {})
    cached_at = datetime.fromtimestamp(
        float(entry.get("ts") or 0)).strftime("%Y-%m-%d %H:%M:%S")
    st = dict(orig)
    st["cache_hit"] = True
    st["cached_at"] = cached_at
    st["generated_at"] = entry.get("generated_at")
    st["profile_hash"] = entry.get("profile_hash")
    st["original_status"] = orig.get("status")
    st["original_reason"] = orig.get("reason") or ""
    if st["original_reason"]:
        st["reason"] = (st["original_reason"]
                        + "（复用缓存，原采集于 %s）" % cached_at)
    else:
        st["reason"] = "复用 3 分钟内成功结果（缓存于 %s）" % cached_at
    st["rows"] = len(rows)
    return rows, st


def _ctrip_deals(q: RadarQuery, logger, proxy) -> tuple:
    """携程发现源：全国模式走特价榜，单航线走低价日历。

    入口先问链路闸门（r1063 T11）：`ctrip/low_fare/日历` 被策略停用时整源
    报 `unsupported`+「被策略停用」，不伪装成 0 行。预算（`budget.fetch_s`）
    在**每次外发前**判：全国榜要连打多个 30 天窗，超预算就带着已采到的行
    提前收工并报 `timeout`+「预算耗尽」。
    """
    why = _gate_path("ctrip", logger)
    if why:
        return _paced_reject("ctrip", why, _RADAR_DIM, _RADAR_PATH)
    budget_s = _budget_s("ctrip")
    deadline = _budget_deadline(budget_s)
    if q.nationwide:
        rows = []
        w = q.start
        while w <= q.end:
            if _budget_hit(deadline):
                return _budget_reject("ctrip", rows, budget_s)
            e = min(q.end, w + timedelta(days=30))
            payload = fetch_ctrip_board(q.from_code, q.from_name,
                                        w.isoformat(), e.isoformat(),
                                        logger, proxy=proxy)
            if payload is None:
                if _budget_hit(deadline):
                    return _budget_reject("ctrip", rows, budget_s,
                                          "本节外发结束时预算已用完")
                return [], _status("error", "全国榜请求失败")
            rows.extend(deals_from_ctrip_board(
                payload, _watch(q, _RADAR_MAX_DAYS), date.today()))
            w = e + timedelta(days=1)
        return rows, _status("ok" if rows else "empty", "", len(rows))
    payload = fetch_ctrip_calendar(q.from_code, q.to_code,
                                   q.start.isoformat(), logger, proxy=proxy)
    if payload is None:
        if _budget_hit(deadline):
            return _budget_reject("ctrip", [], budget_s,
                                  "本次外发结束时预算已用完")
        return [], _status("error", "低价日历请求失败")
    days = (q.end - date.today()).days + 2
    rows = ctrip_calendar_deals(payload, q.from_code, q.to_code, q.to_name,
                                _watch(q, days), date.today())
    return rows, _status("ok" if rows else "empty", "", len(rows))


def _fliggy_fail_kind(elapsed: float, exc=None) -> str:
    """None 返回的成因归类：异常名/类型可判超时；fetch 内部吞异常时用
    耗时贴近 20s 超时阈值判定网络超时，否则按 65B 软拒。"""
    if exc is not None:
        name = type(exc).__name__.lower()
        if isinstance(exc, TimeoutError) or "timeout" in name:
            return "timeout"
        return "network"
    if elapsed >= _FLIGGY_TIMEOUT_S * _FLIGGY_TIMEOUT_RATIO:
        return "timeout"
    return "refusal"


def _fliggy_fail_label(kinds) -> str:
    parts = []
    if "timeout" in kinds:
        parts.append("网络超时（%ds）" % int(_FLIGGY_TIMEOUT_S))
    if "refusal" in kinds:
        parts.append("源软拒/限流（65B）")
    if "network" in kinds:
        parts.append("网络错误")
    return "飞猪日历" + "、".join(parts)


def _fliggy_deals(q: RadarQuery, logger, proxy) -> tuple:
    """飞猪单航线 cheapestCalendar（国内/国际同源，含税价）：一次返回
    leaveDate 起 7 天，按 7 天窗口滚动；最多 5 次（35 天）避免对源
    短窗连打。任一窗口不可用不伪造；超窗如实标注 requested/covered
    天数；软拒回退榜单须标 partial/fallback 并进入冷却。

    r1063 T11：缓存/冷却之后、第一次外发之前问链路闸门（命中缓存的这一轮
    不碰上游：只问不动账、不等限速，被停用时在 reason 里注明「缓存复用」）；
    每轮 7 天窗**和回退榜单的每一窗**前都判预算，超预算就带着已采行收工并
    报 `timeout`+「预算耗尽」，不再继续打源。
    """
    global _FLIGGY_COOLDOWN_UNTIL
    key = _cache_key(q)
    profile_hash = _profile_hash(q)
    hit = _cache_get(_FLIGGY_CACHE, key)
    if hit:
        return _cache_with_gate(hit, "fliggy", logger)
    if time.time() < _FLIGGY_COOLDOWN_UNTIL:
        return [], _status("error", "飞猪限流冷却中（60 秒），稍后重试")
    why = _gate_path("fliggy", logger)
    if why:
        return _paced_reject("fliggy", why, _RADAR_DIM, _RADAR_PATH)
    budget_s = _budget_s("fliggy")
    deadline = _budget_deadline(budget_s)
    rows = []
    seen = set()
    w = q.start
    covered_until = None
    requested_days = (q.end - q.start).days + 1
    fail_kinds = set()
    failed = 0
    calls = 0
    budget_cut = False
    while w <= q.end and calls < 5:
        if _budget_hit(deadline):
            budget_cut = True
            break
        if calls:
            time.sleep(1.0)   # 源短窗连打会软拒（65B success:false）
        calls += 1
        t0 = time.time()
        exc = None
        try:
            days = fetch_fliggy_calendar(q.from_code, q.to_code,
                                         w.isoformat(), logger, proxy=proxy)
        except Exception as ex:      # 网络异常不得静默成「无票」
            days, exc = None, ex
        if days is None:
            failed += 1
            fail_kinds.add(_fliggy_fail_kind(time.time() - t0, exc))
            w = w + timedelta(days=7)
            continue
        maxd = None
        for d in days:
            if not isinstance(d, dict):
                continue
            date_s = str(d.get("leaveDate") or "")
            try:
                dd = date.fromisoformat(date_s)
                maxd = max(maxd, dd) if maxd else dd
            except ValueError:
                pass
            if not _in_range(date_s, q) or date_s in seen:
                continue
            try:
                price = float(d.get("price") or 0) + float(d.get("tax") or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            link = str(d.get("url") or "").strip()
            if link.startswith("//"):
                link = "https:" + link
            rows.append(SpecialDeal("fliggycal", q.from_code, q.to_code,
                                    date_s, price, link=link,
                                    to_name=q.to_name,
                                    tax_included=True,
                                    price_basis="tax_included",
                                    price_basis_label="含税总价"))
            seen.add(date_s)
        if maxd:
            covered_until = (max(covered_until, min(q.end, maxd))
                             if covered_until else min(q.end, maxd))
            w = maxd + timedelta(days=1)
        else:
            # 空表=该窗口已应答（源明确无价），覆盖到窗口尾
            covered_until = (max(covered_until,
                                 min(q.end, w + timedelta(days=6)))
                             if covered_until
                             else min(q.end, w + timedelta(days=6)))
            w = w + timedelta(days=7)
    covered_days = ((covered_until - q.start).days + 1
                    if covered_until else 0)
    partials = []
    fail_label = _fliggy_fail_label(fail_kinds) if fail_kinds else ""
    if fail_label:
        partials.append("%s（%d 个窗口失败）" % (fail_label, failed))
    if covered_days < requested_days:
        partials.append("飞猪日历仅覆盖 %d/%d 天（单次最多 5 个 7 天窗）"
                        % (covered_days, requested_days))
    partial = "；".join(partials)
    if budget_cut:
        # 预算用完就**连回退榜单那一次外发也不做**（回退同样是打源）。
        # 覆盖天数的实话照样带上，别让读者以为跑满了 5 个窗。
        return _budget_reject("fliggy", rows, budget_s, partial)
    if not rows and failed:
        # 国内出发榜与日历不同端点：日历不可用时回退榜单（仍按航线过滤）。
        # **回退循环同样要判预算**（复核第一轮 Important）：日历 5 个 7 天窗
        # 已经把预算吃光时，原来这里还会接着打 4 次榜（实测 t=83/98/113/128），
        # 最后把「我方预算用完」报成 `error`（「网络超时…稍后重试」）——既继续
        # 烧请求，又把我们的上限说成对方的失败。
        board_rows = []
        w = q.start
        while w <= q.end:
            if _budget_hit(deadline):
                return _budget_reject(
                    "fliggy", board_rows, budget_s,
                    ((partial + "；") if partial else "")
                    + "回退国内出发榜中途预算用完，剩余窗口未采")
            e = min(q.end, w + timedelta(days=6))
            payload = fetch_fliggy_board(q.from_code, w.isoformat(),
                                         e.isoformat(), logger, proxy=proxy)
            if payload is not None:
                board_rows.extend(deals_from_fliggy_board(
                    payload, _watch(q, _RADAR_MAX_DAYS), date.today()))
            w = e + timedelta(days=1)
        if board_rows:
            _FLIGGY_COOLDOWN_UNTIL = time.time() + _FLIGGY_COOLDOWN_S
            st = _status(
                "ok", (partial or "飞猪日历不可用")
                + "；回退国内出发榜（榜单价口径未标注）",
                len(board_rows), partial=True, fallback="board",
                requested_days=requested_days, covered_days=covered_days,
                window_limit=5)
            _cache_put(_FLIGGY_CACHE, key, board_rows, st, profile_hash)
            return board_rows, st
        if _budget_hit(deadline):
            # 榜单跑完但没数、且预算已耗尽：仍然是我们到点收工，不是对方
            # 拒绝——也别顺手把 60 秒冷却挂上（那不是源的行为）。
            return _budget_reject(
                "fliggy", board_rows, budget_s,
                ((partial + "；") if partial else "")
                + "回退国内出发榜未出数且预算已用完")
        _FLIGGY_COOLDOWN_UNTIL = time.time() + _FLIGGY_COOLDOWN_S
        return [], _status("error",
                           (partial or "飞猪日历不可用") + "，稍后重试",
                           partial=True, fallback="board_empty",
                           requested_days=requested_days,
                           covered_days=covered_days, window_limit=5)
    st = _status("ok" if rows else "empty", partial, len(rows),
                 partial=bool(partial), requested_days=requested_days,
                 covered_days=covered_days, window_limit=5)
    if rows:
        _cache_put(_FLIGGY_CACHE, key, rows, st, profile_hash)
    return rows, st


def _tuniu_deals(q: RadarQuery, logger, proxy) -> tuple:
    """途牛国内走官方单航线日历（裸价，不含税）；国际无官方日历，不用
    国内出发榜冒充。国内日历失败才回退榜单，且回退原因必须随行。

    r1063 T11：国际档先回「渠道不供国际日历」这个**能力事实**（本来就不
    外发，不必过闸门），国内档在缓存之后问闸门；回退榜单是**第二次外发**，
    动手前先判预算，超预算就报 `timeout`+「预算耗尽」而不是继续打。
    """
    from core.intl import is_intl_route
    if is_intl_route(q.from_code, q.to_code):
        return [], _status(
            "unsupported",
            "途牛无官方国际低价日历（不以内陆出发榜代替）")
    key = _cache_key(q)
    profile_hash = _profile_hash(q)
    hit = _cache_get(_TUNIU_CACHE, key)
    if hit:
        return _cache_with_gate(hit, "tuniu", logger)
    why = _gate_path("tuniu", logger)
    if why:
        return _paced_reject("tuniu", why, _RADAR_DIM, _RADAR_PATH)
    budget_s = _budget_s("tuniu")
    deadline = _budget_deadline(budget_s)
    days = fetch_tuniu_calendar(q.from_code, q.to_code,
                                q.start.isoformat(), logger, proxy=proxy)
    if days is not None:
        rows = []
        for d in days:
            if not isinstance(d, dict):
                continue
            date_s = str(d.get("date") or "")
            if not _in_range(date_s, q):
                continue
            try:
                price = float(d.get("price"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            link = ("https://m.tuniu.com/flight/domestic/new/"
                    "%s_%s_OW_1_0_0?deptDate=%s"
                    % (q.from_code, q.to_code, date_s))
            rows.append(SpecialDeal("tuniucal", q.from_code, q.to_code,
                                    date_s, price, link=link,
                                    to_name=q.to_name,
                                    tax_included=False, price_basis="bare",
                                    price_basis_label="裸价不含税"))
        st = _status("ok" if rows else "empty",
                     "裸价（不含税）" if rows else "", len(rows))
        if rows:
            _cache_put(_TUNIU_CACHE, key, rows, st, profile_hash)
        return rows, st
    # 回退榜单是**第二次外发**：预算用完就停手，别再打第二个端点。
    if _budget_hit(deadline):
        return _budget_reject("tuniu", [], budget_s,
                              "国内日历未出数，回退榜单那一次没有再发")
    payload = fetch_tuniu_board(logger, proxy=proxy)
    if payload is None:
        if _budget_hit(deadline):
            return _budget_reject("tuniu", [], budget_s,
                                  "回退榜单未出数且预算已用完")
        return [], _status(
            "error", "途牛国内日历请求失败，回退榜单亦失败")
    rows = deals_from_tuniu(payload, _watch(q, _RADAR_MAX_DAYS), date.today())
    if rows:
        return rows, _status(
            "ok", "途牛国内日历请求失败，回退出发地榜单（裸价；"
            "出发地随出口 IP）", len(rows), partial=True, fallback="board")
    # 榜单出发地跟随出口 IP：目标出发地不在榜单里时不能判定“无票”
    orgs = set()
    data = ((payload or {}).get("data") or {}).get("cityFlightInfo") or {}
    for key in ("singleTrip", "roundTrip"):
        for r in data.get(key) or []:
            if isinstance(r, dict):
                org = str(r.get("orgCityIata") or "").upper()
                if org:
                    orgs.add(org)
    if orgs and q.from_code not in orgs:
        return [], _status(
            "unsupported",
            "榜单出发地跟随出口 IP（当前：%s）"
            % "/".join(sorted(orgs)), fallback="board")
    return [], _status("empty", "途牛国内日历与出发地榜单均无该航线日期价",
                       fallback="board")


def _tongcheng_deals(q: RadarQuery, logger, proxy) -> tuple:
    """同程 H5 低价日历：一次同步返回 90/180 天窗口（无登录/签名）。
    anchor 不可为今天（渠道 code=5）；区间按查询范围过滤。渠道
    code=5（非法航线/超窗）由 crawler 映射为空表，此处标 unsupported
    并写明边界，不写成 empty。同条件成功结果短 TTL 缓存。

    r1063 T11：缓存之后问闸门；这个源**只有一个外发点**，所以预算只能
    在事后判——外发结束时预算已用完，就把「不知道对方有没有」如实报成
    `timeout`+「预算耗尽」，而不是拿 `error` 冒充对方拒绝。
    """
    anchor = q.start
    if anchor <= date.today():
        anchor = date.today() + timedelta(days=1)
    if anchor > q.end:
        return [], _status("empty", "日期范围仅含今天；同程日历需从明天起查")
    key = _cache_key(q, extra=(anchor.isoformat(),))
    profile_hash = _profile_hash(q)
    hit = _cache_get(_TONGCHENG_CACHE, key)
    if hit:
        return _cache_with_gate(hit, "tongcheng", logger)
    why = _gate_path("tongcheng", logger)
    if why:
        return _paced_reject("tongcheng", why, _RADAR_DIM, _RADAR_PATH)
    budget_s = _budget_s("tongcheng")
    deadline = _budget_deadline(budget_s)
    days = fetch_tongcheng_calendar(
        q.from_code, q.from_name or CODE_NAME.get(q.from_code, q.from_code),
        q.to_code, q.to_name or CODE_NAME.get(q.to_code, q.to_code),
        anchor.isoformat(), logger, proxy=proxy)
    if days is None:
        if _budget_hit(deadline):
            return _budget_reject("tongcheng", [], budget_s,
                                  "本次外发结束时预算已用完")
        return [], _status("error", "同程低价日历请求失败")
    rows = []
    for d in days:
        if not isinstance(d, dict):
            continue
        date_s = str(d.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(d.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        rows.append(SpecialDeal("tongchengcal", q.from_code, q.to_code,
                                date_s, price, to_name=q.to_name,
                                tax_included=None, price_basis="unknown",
                                price_basis_label="口径未标注"))
    if not days:
        return [], _status(
            "unsupported",
            "同程日历无数据（渠道 code=5：非法航线或超出可查窗口）")
    st = _status("ok" if rows else "empty",
                 "" if rows else "同程日历窗口内无有效价格", len(rows))
    if rows:
        _cache_put(_TONGCHENG_CACHE, key, rows, st, profile_hash)
    return rows, st


_QUNAR_COOLDOWN_UNTIL = 0.0


def _qunar_deals(q: RadarQuery, logger, proxy,
                 user_data_dir: str = "user_data") -> tuple:
    """去哪儿官方 H5 低价日历：加载官方特价页，由页面 JS 生成签名，
    只读取真实 getFlightCalendar 响应。

    r1063 T11（复核第一轮补）：这是雷达**第五个真外发的浏览器源**——它要
    开一次页面会话才拿得到签名，比纯 httpx 的四个源更贵，所以同样要过闸门
    与预算；停掉 `qunar/low_fare/日历` 后雷达不许再打它。
    """
    global _QUNAR_COOLDOWN_UNTIL
    from urllib.parse import quote
    from crawlers.qunar import QunarCrawler
    key = _cache_key(q, user_data_dir)
    profile_hash = _profile_hash(q, user_data_dir)
    hit = _cache_get(_QUNAR_CACHE, key)
    if hit:
        return _cache_with_gate(hit, "qunar", logger)
    if time.time() < _QUNAR_COOLDOWN_UNTIL:
        return [], _status(
            "error", "去哪儿低价页风控冷却中（10 分钟），稍后重试")
    why = _gate_path("qunar", logger)
    if why:
        return _paced_reject("qunar", why, _RADAR_DIM, _RADAR_PATH)
    budget_s = _budget_s("qunar")
    deadline = _budget_deadline(budget_s)
    dep = q.from_name or CODE_NAME.get(q.from_code, q.from_code)
    arr = q.to_name or CODE_NAME.get(q.to_code, q.to_code)
    obj = QunarCrawler.fetch_low_price_calendar(
        dep, arr, q.start.isoformat(), q.end.isoformat(),
        logger, timeout=22.0, proxy=proxy, profile_root=user_data_dir)
    if obj is None:
        # 单外发点：预算已用完就报 `timeout`+「预算耗尽」，别拿 `error`
        # 冒充对方拒绝（还会顺手把 10 分钟风控冷却挂上，双重误导）。
        if _budget_hit(deadline):
            return _budget_reject("qunar", [], budget_s,
                                  "本次外发结束时预算已用完")
        _QUNAR_COOLDOWN_UNTIL = time.time() + 600
        return [], _status(
            "error", "去哪儿低价页未返回数据（页面签名风控或加载超时）")
    _QUNAR_COOLDOWN_UNTIL = 0.0
    rows = []
    for d in obj.get("lowPriceList") or []:
        if not isinstance(d, dict):
            continue
        date_s = str(d.get("depDate") or d.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(d.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        link = ("https://touch.qunar.com/lowFlight/flightList?dep="
                + quote(dep) + "&arr=" + quote(arr)
                + "&flightType=1&startDate=" + date_s
                + "&endDate=" + date_s + "&tag=-1&days=-1"
                + "&hybridid=flight_tejia&bizSource=SUPER_LOW")
        rows.append(SpecialDeal("qunar", q.from_code, q.to_code,
                                date_s, price, link=link,
                                to_name=q.to_name,
                                tax_included=None, price_basis="unknown",
                                price_basis_label="口径未标注"))
    st = _status("ok" if rows else "empty", "", len(rows))
    if rows:
        _cache_put(_QUNAR_CACHE, key, rows, st, profile_hash)
    return rows, st


def _app_paced_reject(plat, note, path="low-fare"):
    """App 源被 T9 的链路闸门挡下（账本记 `paced`）→ 单独成一档。

    薄壳：口径与浏览器源的 `_paced_reject` 完全一致（复核第一轮要求两个
    helper 合成一个），这里只固定 App 侧的维度/通路（`low_fare` / `low-fare`）。

    `paced` 的语义是「**我方**按策略克制、没发请求」，与 `error`（对方
    拒绝）和 `empty`（确实没有低价）是三件不同的事，处置方向也完全不同：
    T9 落地后账本里第一条非 ok 的记录一律被读成「有 note 就是失败」，于是
    停用 App 低价在特价面板显示「失败」，把人引去查风控（`_app_zhixing_deals`
    更糟：显示成「无日期价」）。
    """
    return _paced_reject(plat, note, _RADAR_DIM, path)


def _app_qunar_deals(q: RadarQuery, logger) -> tuple:
    """去哪儿 App「低价机票」：每天一条最低价（App 渠道的 low_fare 源）。

    与 H5 lowFlight 的差别：
      * 走真机（MuMu + adb），不需要 Playwright，也没有页面 JS 签名；
      * 价格是**当天最低价**。页面本身**没有写口径**（真机 dump 里
        找不到「含税 / 优惠前 / 到手」任何字样），所以只能标
        `tax_included=None` + 「口径未标注」——**不能**假设含税：
        App 卡片上另有 `已减 ¥70` 这类优惠，标含税会让人误以为到手价。

    采不到要区分「被拦/要登录」与「确实没有低价」：前者 error，后者 empty。
    """
    from crawlers.app_qunar import AppQunarCrawler
    # 低价页日期带从**今天**起算（14 天）。雷达的日期区间可以是未来任意
    # 起点：只传区间长度会让 11-10..11-12 实际只抓 11-02..11-04，过滤后
    # 变空且没有原因（2026-11-02 线上实测 176s / empty / dates=[]）。
    today = date.today()
    strip_end = today + timedelta(days=_APP_QUNAR_STRIP_DAYS - 1)
    if q.end < today:
        return [], _status("empty", "请求区间已过去；App 低价日期带从今天起算")
    if q.start > strip_end:
        return [], _status(
            "empty", "App 低价日期带只覆盖今天起 %d 天（到 %s），请求区间 %s..%s 超出"
            % (_APP_QUNAR_STRIP_DAYS, strip_end.isoformat(),
               q.start.isoformat(), q.end.isoformat()))
    days = max(1, min(_APP_QUNAR_STRIP_DAYS,
                     (min(q.end, strip_end) - today).days + 1))
    crawler = AppQunarCrawler(
        {"user_data_dir": "user_data",
         "android": {"enabled": True}}, logger)
    rows_d = crawler.low_fare(q.from_code, q.to_code, days=days) or []
    out = []
    for r in rows_d:
        date_s = str(r.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append(SpecialDeal(
            "app_qunar", q.from_code, q.to_code, date_s, price,
            link="", to_name=q.to_name, tax_included=None,
            price_basis="unknown",
            price_basis_label="口径未标注"))
    if rows_d and not out:
        _got = sorted(str(r.get("date") or "") for r in rows_d
                      if r.get("date"))
        return [], _status(
            "empty", "App 返回日期带 %s..%s 未覆盖请求区间 %s..%s"
            % (_got[0], _got[-1], q.start.isoformat(), q.end.isoformat()))
    # 采不到要区分「被拦/要登录」与「确实没有低价」：前者照实说，
    # 后者才是 empty。crawler 的账本里已经写明了卡点。
    note = ""
    pstatus = ""
    for pth in getattr(crawler, "paths", []) or []:
        if pth.get("path") == "low-fare" and pth.get("status") != "ok":
            note = str(pth.get("detail") or pth.get("status") or "")
            pstatus = str(pth.get("status") or "")
            break
    if not out and pstatus == "paced":
        # 我方按策略克制（T9 闸门跳过），不是失败、也不是没票。
        return _app_paced_reject("app_qunar", note)
    if not out and pstatus == "unsupported":
        # 通路本身接不上（结果页变 WebView / 产品下线）：既不是网络错误，
        # 也不是「当天没低价」。记 not_connected，前端按未接通展示原因。
        return out, _status("not_connected", note)
    if out and q.end > strip_end:
        _tail = "App 低价日期带只到 %s，区间后半段未覆盖" % strip_end.isoformat()
        note = (note + "；" if note else "") + _tail
    st = _status("ok" if out else ("error" if note else "empty"),
                 note, len(out))
    return out, st


def _app_ctrip_deals(q: RadarQuery, logger) -> tuple:
    """携程 App 原生价格日历：该航线逐天一条最低价（OCR 读屏）。

    2026-11-02/03 真机 calendar() 连续两次 SHA→PEK 61 天 ¥380–420
    （app-calendar ok，OCR 3.7/3.8s）；国际档 SHA→NRT 连续两次
    54/53 天 ¥864–1530（两月视野，未滚动；11-10 查价）。
    页面未标含税/优惠口径，行标 `tax_included=None` + 「口径未标注」。
    """
    from datetime import date as _d, timedelta as _td
    from crawlers.app_ctrip import AppCtripCrawler
    today = _d.today()
    max_end = today + _td(days=62)
    if q.end < today:
        return [], _status("empty", "请求区间已过去；App 日历从今天起算")
    if q.start > max_end:
        return [], _status(
            "empty", "App 日历只覆盖今天起 62 天（到 %s），请求区间 %s..%s 超出"
            % (max_end.isoformat(), q.start.isoformat(), q.end.isoformat()))
    days = max(1, (min(q.end, max_end) - today).days + 1)
    crawler = AppCtripCrawler(
        {"user_data_dir": "user_data",
         "android": {"enabled": True}}, logger)
    rows_d = crawler.low_fare(q.from_code, q.to_code, days=days) or []
    out = []
    for r in rows_d:
        date_s = str(r.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append(SpecialDeal(
            "app_ctrip", q.from_code, q.to_code, date_s, price,
            link="", to_name=q.to_name, tax_included=None,
            price_basis="unknown",
            price_basis_label="口径未标注"))
    note, pstatus = "", ""
    for pth in getattr(crawler, "paths", []) or []:
        # `low-fare` 也在这里看：本源调的是 `crawler.low_fare()`，它被 T9 的
        # 闸门跳过时账本记的是 `low-fare/paced`，不看就等于把「我方克制」
        # 显示成「无日期价」。
        if pth.get("path") in ("app-calendar", "android-ocr", "app-login",
                               "low-fare") \
                and pth.get("status") != "ok":
            note = str(pth.get("detail") or pth.get("status") or "")
            pstatus = str(pth.get("status") or "")
            break
    if not out and pstatus == "paced":
        return _app_paced_reject("app_ctrip", note)   # 我方克制，不是失败
    if not out and pstatus in ("unsupported",):
        return out, _status("not_connected", note)
    if not out and pstatus == "login":
        return out, _status("error", note or "携程 App 需要登录")
    if out:
        last = max(str(getattr(r, "date", "") or "") for r in out)
        want = min(q.end, max_end).isoformat()
        # 国际档日历只渲染两个月，屏幕外的后半段读不到；别让读者
        # 把「请求区间」当成已经全部覆盖。
        if last < want:
            _tail = ("本次可见日历到 %s；请求区间 %s..%s 未完全覆盖"
                     % (last, q.start.isoformat(), q.end.isoformat()))
            note = (note + "；" if note else "") + _tail
    return out, _status("ok" if out else ("error" if note else "empty"),
                        note, len(out))


def _app_fliggy_deals(q: RadarQuery, logger) -> tuple:
    """飞猪 App 价格日历：该航线逐天一条最低价（OCR 读屏）。

    2026-11-06 真机：日历页每格是「日号 + 其下方最低价」（纵向差约 70px，
    无价写「查看」），`low_fare()` 直接 OCR 整月逐日价。
    SHA→PEK 45 天返回 **35 行**、连续 20 天无缺口、最低 ¥338（11-10）。
    页面未标含税/优惠口径 → 行标 `tax_included=None` + 「口径未标注」。
    """
    from datetime import date as _d, timedelta as _td
    from crawlers.app_fliggy import AppFliggyCrawler
    today = _d.today()
    max_end = today + _td(days=62)
    if q.end < today:
        return [], _status("empty", "请求区间已过去；App 日历从今天起算")
    if q.start > max_end:
        return [], _status(
            "empty", "App 日历只覆盖今天起 62 天（到 %s），请求区间 %s..%s 超出"
            % (max_end.isoformat(), q.start.isoformat(), q.end.isoformat()))
    days = max(1, (min(q.end, max_end) - today).days + 1)
    crawler = AppFliggyCrawler(
        {"user_data_dir": "user_data",
         "android": {"enabled": True}}, logger)
    rows_d = crawler.low_fare(q.from_code, q.to_code, days=days) or []
    out = []
    for r in rows_d:
        date_s = str(r.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append(SpecialDeal(
            "app_fliggy", q.from_code, q.to_code, date_s, price,
            link="", to_name=q.to_name, tax_included=None,
            price_basis="unknown",
            price_basis_label="口径未标注"))
    note, pstatus = "", ""
    for pth in getattr(crawler, "paths", []) or []:
        if pth.get("path") in ("app-calendar", "android-ocr", "app-login",
                               "app-block") \
                and pth.get("status") != "ok":
            note = str(pth.get("detail") or pth.get("status") or "")
            pstatus = str(pth.get("status") or "")
            break
    if not out and pstatus == "blocked":
        return out, _status("blocked", note or "飞猪 App 被安全页拦截")
    if not out and pstatus in ("unsupported",):
        return out, _status("not_connected", note)
    if not out and pstatus == "login":
        return out, _status("error", note or "飞猪 App 需要登录")
    return out, _status("ok" if out else ("error" if note else "empty"),
                        note, len(out))


def _app_tongcheng_deals(q: RadarQuery, logger) -> tuple:
    """同程 App 原生价格日历：该航线逐天一条最低价（App 渠道的 low_fare 源）。

    日期弹层一次渲染 2–3 个月，每个日格 content-desc 自带 `¥`；与浏览器
    同程 H5 日历同一契约（发现源，不是明细）。页面未标价格口径，行标
    `tax_included=None` + 「口径未标注」，不假设含税。
    """
    from datetime import date as _d, timedelta as _td
    from crawlers.app_tongcheng import AppTongchengCrawler
    today = _d.today()
    max_end = today + _td(days=60)
    if q.end < today:
        return [], _status("empty", "请求区间已过去；App 日历从今天起算")
    if q.start > max_end:
        return [], _status(
            "empty", "App 日历只覆盖今天起 60 天（到 %s），请求区间 %s..%s 超出"
            % (max_end.isoformat(), q.start.isoformat(), q.end.isoformat()))
    days = max(1, (min(q.end, max_end) - q.start).days + 1)
    crawler = AppTongchengCrawler(
        {"user_data_dir": "user_data",
         "android": {"enabled": True}}, logger)
    rows_d = crawler.low_fare(q.from_code, q.to_code, days=days,
                              anchor_ymd=q.start.isoformat()) or []
    out = []
    for r in rows_d:
        date_s = str(r.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append(SpecialDeal(
            "app_tongcheng", q.from_code, q.to_code, date_s, price,
            link="", to_name=q.to_name, tax_included=None,
            price_basis="unknown",
            price_basis_label="口径未标注"))
    note, pstatus = "", ""
    for pth in getattr(crawler, "paths", []) or []:
        # `low-fare` 同 `_app_ctrip_deals`：本源走的就是 `crawler.low_fare()`。
        if pth.get("path") in ("app-calendar", "app-login", "low-fare") \
                and pth.get("status") != "ok":
            note = str(pth.get("detail") or pth.get("status") or "")
            pstatus = str(pth.get("status") or "")
            break
    if not out and pstatus == "paced":
        return _app_paced_reject("app_tongcheng", note)   # 我方克制，不是失败
    if not out and pstatus == "unsupported":
        return out, _status("not_connected", note)
    if not out and pstatus == "login":
        return out, _status("error", note or "同程 App 需要登录")
    if out and q.end > max_end:
        _tail = "App 日历只到 %s，区间后半段未覆盖" % max_end.isoformat()
        note = (note + "；" if note else "") + _tail
    return out, _status("ok" if out else ("error" if note else "empty"),
                        note, len(out))


def _app_zhixing_deals(q: RadarQuery, logger) -> tuple:
    """智行 App「特价」：该航线逐天一条最低价（App 渠道的 low_fare 源）。

    真机实测（2026-10-31）：首页「特价」页签 → 设出发/到达 + 日期区间 →
    「搜索特价」→ 结果页逐天列出 `02.16 周二 ¥1646`。与去哪儿 App
    「低价机票」同一个契约（发现源，不是明细）。

    此前这里被记成"目的地低价榜、口径对不上"——那是把首页「省钱攻略」里
    按目的地报价的推荐卡当成了「特价」档。**结论已更正**。

    页面本身没写价格口径（dump 里没有含税/优惠前/到手字样），所以只能标
    `tax_included=None` + 「口径未标注」，不假设含税。
    """
    from crawlers.app_zhixing import AppZhixingCrawler
    days = max(1, min(_RADAR_MAX_DAYS, (q.end - q.start).days + 1))
    crawler = AppZhixingCrawler(
        {"user_data_dir": "user_data",
         "android": {"enabled": True}}, logger)
    rows_d = crawler.low_fare(q.from_code, q.to_code, days=days,
                              anchor_ymd=q.start.isoformat()) or []
    out = []
    for r in rows_d:
        date_s = str(r.get("date") or "")
        if not _in_range(date_s, q):
            continue
        try:
            price = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append(SpecialDeal(
            "app_zhixing", q.from_code, q.to_code, date_s, price,
            link="", to_name=q.to_name, tax_included=None,
            price_basis="unknown",
            price_basis_label="口径未标注"))
    note, pstatus = "", ""
    for pth in getattr(crawler, "paths", []) or []:
        if pth.get("path") == "low-fare" and pth.get("status") != "ok":
            note = str(pth.get("detail") or pth.get("status") or "")
            pstatus = str(pth.get("status") or "")
            break
    # `paced` 必须单独成档：旧写法把它当成「没出数但有原因」→ `empty`，
    # 面板于是显示「无日期价」，读起来像「智行这段时间没有低价」。
    if not out and pstatus == "paced":
        return _app_paced_reject("app_zhixing", note)
    # 没出数也要带原因：页面停在别的航线/日期带是「没按请求取」，
    # 不是抓取失败；旧写法把有 note 的情况记成 error，读者会去查风控。
    st = _status("ok" if out else "empty", note, len(out))
    return out, st


def _entry(links, plat):
    for c in (links or {}).get("specials") or []:
        if c.get("plat") == plat and c.get("surface") == "h5" and c.get("ok"):
            return c.get("url") or ""
    return ""


def _pick_lowest(dates):
    """跨渠道最低价：同口径比较优先含税总价。存在多口径时不把裸价
    最小值冒充“最低”，而是标注 lowest_basis/basis_mixed 并保留跨口径
    更便宜的记录供用户自行判断。"""
    if not dates:
        return None, False
    cands = []
    for d in dates:
        for ch, rec in d["by_channel"].items():
            item = dict(rec)
            item["channel"] = ch
            item["date"] = d["date"]
            cands.append(item)
    bases = {c.get("basis") or "unknown" for c in cands}
    mixed = len(bases) > 1
    tax_rows = [c for c in cands if c.get("tax_included") is True]
    pool = tax_rows or cands
    b = min(pool, key=lambda c: c["price"])
    basis = b.get("basis") or "unknown"
    low = {"date": b["date"], **{k: v for k, v in b.items() if k != "date"}}
    low["lowest_basis"] = basis
    low["lowest_basis_label"] = (b.get("basis_label")
                                 or _BASIS_LABEL.get(basis,
                                                     _BASIS_LABEL["unknown"]))
    low["basis_mixed"] = mixed
    low["lowest_date"] = b["date"]
    low["lowest_platform"] = b.get("channel")
    raw = min(cands, key=lambda c: c["price"])
    if raw is not b and raw["price"] < b["price"]:
        low["cheaper_cross_basis"] = {
            "date": raw["date"], "price": raw["price"],
            "channel": raw.get("channel"), "basis": raw.get("basis"),
            "basis_label": raw.get("basis_label"),
        }
    if mixed:
        low["note"] = ("价格口径混合（含税/裸价/未标注）；最低价按%s口径"
                       "选取，不可跨口径直接比较" % low["lowest_basis_label"])
    elif b.get("tax_included") is not True:
        low["note"] = "最低价为%s，不是含税总价" % low["lowest_basis_label"]
    return low, mixed


def build_radar(payload: dict, logger, proxy: str = "",
                user_data_dir: str = "user_data") -> dict:
    from core.channel_links import channel_links
    q = parse_query(payload)
    # 机场码先归并城市码（PVG→SHA/PEK→BJS/NRT→TYO）：渠道按城市码收，
    # 直接用机场码会得到假空结果。
    q = replace(q, from_code=airport_city_code(q.from_code),
                to_code=(airport_city_code(q.to_code) if q.to_code else ""))
    links = channel_links(q.from_code, q.to_code,
                          q.start.isoformat(), q.from_name, q.to_name)
    per = {}
    status = {}
    for ch in q.channels:
        if q.nationwide and ch != "ctrip":
            status[ch] = _status("unsupported", "全国模式仅携程支持")
            per[ch] = []
            continue
        # 出口/代理策略关掉 = 这家渠道走**直连**（`proxy_route.enabled`，
        # scope 声明了渠道级，所以按渠道问）。缺省开启＝沿用调用方给的出口，
        # 行为逐位不变。
        _px = proxy if _on("proxy_route.enabled", ch) else ""
        try:
            if ch == "ctrip":
                rows, st = _ctrip_deals(q, logger, _px)
            elif ch == "fliggy":
                rows, st = _fliggy_deals(q, logger, _px)
            elif ch == "tuniu":
                rows, st = _tuniu_deals(q, logger, _px)
            elif ch == "tongcheng":
                rows, st = _tongcheng_deals(q, logger, _px)
            elif ch == "qunar":
                rows, st = _qunar_deals(q, logger, _px, user_data_dir)
            elif ch == "app_qunar":
                rows, st = _app_qunar_deals(q, logger)
            elif ch == "app_zhixing":
                rows, st = _app_zhixing_deals(q, logger)
            elif ch == "app_tongcheng":
                rows, st = _app_tongcheng_deals(q, logger)
            elif ch == "app_ctrip":
                rows, st = _app_ctrip_deals(q, logger)
            elif ch == "app_fliggy":
                rows, st = _app_fliggy_deals(q, logger)
            else:
                rows, st = [], _status(
                    "not_connected", "自定义航线低价日历尚未验证接入；可用明细探针")
            per[ch] = rows
            status[ch] = st
        except Exception as ex:
            per[ch] = []
            status[ch] = _status("error", str(ex)[:120])
    dates = normalize([d for rows in per.values() for d in rows], q)
    for ch in q.channels:
        n = sum(1 for d in dates if ch in d["by_channel"])
        st = status.get(ch) or _status("empty")
        st["rows"] = n
        st["days"] = len({d["date"] for d in dates
                          if ch in d["by_channel"]})
        if st["status"] == "ok" and n == 0:
            st["status"] = "empty"
            st["reason"] = st.get("reason") or "该航线在榜单/日历中没有日期价"
        if st["status"] not in ("ok", "unsupported", "not_connected",
                                "error"):
            st["url"] = _entry(links, ch)
    lowest, basis_mixed = _pick_lowest(dates)
    return {
        "ok": True,
        "query": {"user": q.user, "from": q.from_code, "from_name": q.from_name,
                  "to": q.to_code, "to_name": q.to_name,
                  "nationwide": q.nationwide, "start": q.start.isoformat(),
                  "end": q.end.isoformat(), "channels": q.channels},
        "dates": dates,
        "channels": status,
        "sources": status,
        "lowest": lowest,
        "lowest_basis": (lowest or {}).get("lowest_basis"),
        "basis_mixed": basis_mixed,
        "lowest_date": (lowest or {}).get("date"),
        "lowest_platform": (lowest or {}).get("channel"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "日历/榜单价仅用于发现低价；航班明细请用探针真实采集。",
    }
