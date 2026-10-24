# -*- coding: utf-8 -*-
"""特价雷达：按用户航线 + 日期范围聚合低价日历/榜单。

只做“低价发现”：Ctrip 日历/全国榜、Fliggy 榜单、Tuniu 榜单为真实源；
Qunar/Tongcheng 尚无已验证的自定义航线日历，返回 not_connected，不拿
通用页冒充。任何日历/榜单价都不是航班明细，明细由探针任务获取。
"""
import hashlib
import re
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from core.citydata import CITY, CODE_NAME
from core.intl import (INTL_CITY_HOT, INTL_CITY_NAME, INTL_CITY_SHORT,
                       airport_city_code)
from core.models import PRICE_MAX
from core.specials import (
    SpecialDeal,
    SpecialWatch,
    ctrip_calendar_deals,
    deals_from_ctrip_board,
    deals_from_fliggy_board,
    deals_from_tuniu,
)
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
_CHANNELS = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")

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
    if q.nationwide:
        rows = []
        w = q.start
        while w <= q.end:
            e = min(q.end, w + timedelta(days=30))
            payload = fetch_ctrip_board(q.from_code, q.from_name,
                                        w.isoformat(), e.isoformat(),
                                        logger, proxy=proxy)
            if payload is None:
                return [], _status("error", "全国榜请求失败")
            rows.extend(deals_from_ctrip_board(
                payload, _watch(q, _RADAR_MAX_DAYS), date.today()))
            w = e + timedelta(days=1)
        return rows, _status("ok" if rows else "empty", "", len(rows))
    payload = fetch_ctrip_calendar(q.from_code, q.to_code,
                                   q.start.isoformat(), logger, proxy=proxy)
    if payload is None:
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
    天数；软拒回退榜单须标 partial/fallback 并进入冷却。"""
    global _FLIGGY_COOLDOWN_UNTIL
    key = _cache_key(q)
    profile_hash = _profile_hash(q)
    hit = _cache_get(_FLIGGY_CACHE, key)
    if hit:
        return hit
    if time.time() < _FLIGGY_COOLDOWN_UNTIL:
        return [], _status("error", "飞猪限流冷却中（60 秒），稍后重试")
    rows = []
    seen = set()
    w = q.start
    covered_until = None
    requested_days = (q.end - q.start).days + 1
    fail_kinds = set()
    failed = 0
    calls = 0
    while w <= q.end and calls < 5:
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
    if not rows and failed:
        # 国内出发榜与日历不同端点：日历不可用时回退榜单（仍按航线过滤）
        board_rows = []
        w = q.start
        while w <= q.end:
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
    国内出发榜冒充。国内日历失败才回退榜单，且回退原因必须随行。"""
    from core.intl import is_intl_route
    if is_intl_route(q.from_code, q.to_code):
        return [], _status(
            "unsupported",
            "途牛无官方国际低价日历（不以内陆出发榜代替）")
    key = _cache_key(q)
    profile_hash = _profile_hash(q)
    hit = _cache_get(_TUNIU_CACHE, key)
    if hit:
        return hit
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
    payload = fetch_tuniu_board(logger, proxy=proxy)
    if payload is None:
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
    并写明边界，不写成 empty。同条件成功结果短 TTL 缓存。"""
    anchor = q.start
    if anchor <= date.today():
        anchor = date.today() + timedelta(days=1)
    if anchor > q.end:
        return [], _status("empty", "日期范围仅含今天；同程日历需从明天起查")
    key = _cache_key(q, extra=(anchor.isoformat(),))
    profile_hash = _profile_hash(q)
    hit = _cache_get(_TONGCHENG_CACHE, key)
    if hit:
        return hit
    days = fetch_tongcheng_calendar(
        q.from_code, q.from_name or CODE_NAME.get(q.from_code, q.from_code),
        q.to_code, q.to_name or CODE_NAME.get(q.to_code, q.to_code),
        anchor.isoformat(), logger, proxy=proxy)
    if days is None:
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
    只读取真实 getFlightCalendar 响应；不做签名逆向/验证码绕过。"""
    global _QUNAR_COOLDOWN_UNTIL
    from urllib.parse import quote
    from crawlers.qunar import QunarCrawler
    key = _cache_key(q, user_data_dir)
    profile_hash = _profile_hash(q, user_data_dir)
    hit = _cache_get(_QUNAR_CACHE, key)
    if hit:
        return hit
    if time.time() < _QUNAR_COOLDOWN_UNTIL:
        return [], _status(
            "error", "去哪儿低价页风控冷却中（10 分钟），稍后重试")
    dep = q.from_name or CODE_NAME.get(q.from_code, q.from_code)
    arr = q.to_name or CODE_NAME.get(q.to_code, q.to_code)
    obj = QunarCrawler.fetch_low_price_calendar(
        dep, arr, q.start.isoformat(), q.end.isoformat(),
        logger, timeout=22.0, proxy=proxy, profile_root=user_data_dir)
    if obj is None:
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
        try:
            if ch == "ctrip":
                rows, st = _ctrip_deals(q, logger, proxy)
            elif ch == "fliggy":
                rows, st = _fliggy_deals(q, logger, proxy)
            elif ch == "tuniu":
                rows, st = _tuniu_deals(q, logger, proxy)
            elif ch == "tongcheng":
                rows, st = _tongcheng_deals(q, logger, proxy)
            elif ch == "qunar":
                rows, st = _qunar_deals(q, logger, proxy, user_data_dir)
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
