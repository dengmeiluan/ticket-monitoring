# -*- coding: utf-8 -*-
"""特价机票监控 纯逻辑层（r319）。

社区诉求（LinuxDo）：选定出发地 → 特价机票榜单 + 返程配对。调研定谳
（_scratch/worker_r319_special_{ctrip,others}.md）：各平台无统一「出发地→
多目的地特价榜」现成接口，本项目以三源发现 + 现役爬虫跨渠道核实合成：

- 源1 途牛 queryCheapTickets：1 请求全榜单（出发地=出口 IP），roundTrip
  成对下发；priceBase=特价裸价（税前，飞猪同族）
- 源2 携程 15380 低价日历：出发地可指定，目的地池逐城 1 请求；
  price=列表有票 tprice 同口径（双源 382 互证）；反向同接口配对返程
- 源3 携程 19728 主题榜：swift 首页「国内低价榜」价格填充接口，出发地
  可控（r319d 探针实证）、运营策展目的地组、每条带官方深链（裸价口径）

口径定案：两源价格语义不一（裸价/含税混源）→ **推送/达标口径一律=
跨渠道核实价**（现役列表爬虫各渠道最低，真实可买价），源价只做
「是否值得核实」的触发器并标注词面。本模块全部纯函数（解析/过滤/
配对/去抖/核实决策/消息拼装），不触碰网络与进程——网络面在
crawlers/special.py，编排面在 main.make_sweep_job。

宁缺勿错三线（与现役爬虫带同律）：0 元尾填充过滤（携程 381 天尾部
0 元实测）、PRICE_MIN/MAX 统一带、过期日/越窗过滤。"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, List, Optional, Tuple
from urllib.parse import quote

from .citydata import CITY
from .flightnorm import AIRPORT_NAME_CN
from .alerter import _dw, _fit_line
from .models import PRICE_MAX, PRICE_MIN

# 发现源（r319 五源：途牛榜单 / 携程低价日历 / 携程特价搜索榜 /
# 飞猪 PC 榜；去哪儿 lowFlight 缓采、同程不采——见设计稿 §11 定谳表）
SRC_TUNIU = "tuniu"
SRC_CTRIP = "ctrip"
SRC_CTRIP_BD = "ctripbd"
SRC_FLIGGY = "fliggy"
_KNOWN_SOURCES = (SRC_TUNIU, SRC_CTRIP, SRC_CTRIP_BD, SRC_FLIGGY)
# 推送词面：源价口径标注（tuniu/ctripbd/fliggy=榜单裸价 / ctrip=日历价）
_SRC_LABEL = {SRC_TUNIU: "榜单", SRC_CTRIP: "日历",
              SRC_CTRIP_BD: "主题榜", SRC_FLIGGY: "飞猪榜"}

# 特价雷达渠道能力（只陈述现役发现源，不把未接入写成可用）。
SPECIAL_CAPABILITY = {
    "ctrip": {"sources": [SRC_CTRIP_BD, SRC_CTRIP],
              "note": "主题榜 + 低价日历"},
    "tuniu": {"sources": [SRC_TUNIU], "note": "特价榜单（无公开特价页）"},
    "fliggy": {"sources": [SRC_FLIGGY], "note": "PC 特价榜"},
    "qunar": {"sources": [], "note": "lowFlight 缓采；H5 低价榜"},
    "tongcheng": {"sources": [], "note": "采集未接入；H5 特价榜"},
}

# 核实容忍带：核实价 > 源价 ×1.15 判「榜单价虚高/口径差」丢弃
_VERIFY_TOLERANCE = 1.15

_RE_YYYYMMDD = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_CTRIP_DATE = re.compile(r"/Date\((-?\d+)(?:([+-])(\d{2})(\d{2}))?\)/")
_RE_IATA3 = re.compile(r"[A-Z]{3}")

# 内置目的地池（发现层源2 逐城轮询用）：主流城市+热门旅游地，
# 与用户 dest_pool 白名单取并集。代码全部机场/城市三字码
# （BJS 北京城市码与现役 ctrip CITY_NAME 同律）。
SPECIAL_DEST_POOL = [
    ("BJS", "北京"), ("CAN", "广州"), ("SZX", "深圳"), ("HGH", "杭州"),
    ("NKG", "南京"), ("WUH", "武汉"), ("CSX", "长沙"), ("XMN", "厦门"),
    ("CKG", "重庆"), ("CTU", "成都"), ("SIA", "西安"), ("KMG", "昆明"),
    ("LJG", "丽江"), ("DLU", "大理"), ("JHG", "西双版纳"), ("URC", "乌鲁木齐"),
    ("SYX", "三亚"), ("HAK", "海口"), ("TSN", "天津"), ("TAO", "青岛"),
    ("DLC", "大连"), ("SHE", "沈阳"), ("HRB", "哈尔滨"), ("CGQ", "长春"),
    ("CGO", "郑州"), ("HFE", "合肥"), ("FOC", "福州"), ("KHN", "南昌"),
    ("KWE", "贵阳"), ("NNG", "南宁"), ("KWL", "桂林"), ("LHW", "兰州"),
    ("HET", "呼和浩特"), ("INC", "银川"), ("XNN", "西宁"), ("TYN", "太原"),
    ("SJW", "石家庄"), ("ZUH", "珠海"), ("SWA", "揭阳"), ("WNZ", "温州"),
    ("NGB", "宁波"), ("SHA", "上海"), ("TCZ", "腾冲"), ("DIG", "香格里拉"),
]
# 去重保序（手抄池防重复条目静默翻倍请求量）
_SEEN = set()
SPECIAL_DEST_POOL = [(c, n) for c, n in SPECIAL_DEST_POOL
                     if not (c in _SEEN or _SEEN.add(c))]
_POOL_NAME = dict(SPECIAL_DEST_POOL)


def iata3(v) -> str:
    s = str(v or "").strip().upper()
    return s if _RE_IATA3.fullmatch(s) else ""


@dataclass
class SpecialWatch:
    """一条特价订阅（用户 specials[0] 归一化产物）。"""
    from_code: str
    from_name: str
    max_price: float          # 心理价位：榜单/日历价 ≤ 此值才值得核实
    days: int = 30            # 只认未来 N 天内日期（1..180）
    round_trip: bool = True   # 返程配对开关
    round_trip_days: int = 7  # 返程窗：去程日期 +0~+N 天（0..30）
    interval_rounds: int = 4  # 每 N 个扫描轮跑一次发现（≥1）
    dest_pool: list = None    # 目的地白名单（空=内置池全量）
    platforms: list = None    # 发现源（缺省三源）

    def effective_pool(self) -> List[Tuple[str, str]]:
        """内置池 ∪ 用户白名单（白名单可补池外目的地，名称缺省用码）。"""
        if not self.dest_pool:
            return list(SPECIAL_DEST_POOL)
        extra = [(c, _POOL_NAME.get(c) or c) for c in self.dest_pool
                 if c not in dict(SPECIAL_DEST_POOL)]
        return list(SPECIAL_DEST_POOL) + extra


@dataclass
class SpecialDeal:
    """一条候选特价（发现层产物；推送价=核实价，另存）。"""
    src: str                  # tuniu / ctrip
    from_code: str
    to_code: str
    date: str                 # 去程 YYYY-MM-DD
    src_price: float          # 榜单/日历价（触发器口径）
    ret_date: str = ""        # 往返返程日（成对下发/反向配对）
    ret_price: float = 0.0    # 返程源价
    airline: str = ""
    discount: str = ""        # 「2.1折」词面
    link: str = ""            # 购买深链（往返=round 模板）
    to_name: str = ""
    # 价格口径（发现层必须随价标注；未知不得假设含税）：
    # tax_included=None 表示源未声明口径，True/False 为源可核实口径。
    tax_included: Optional[bool] = None
    price_basis: str = "unknown"       # tax_included / bare / unknown
    price_basis_label: str = "口径未标注"


def _to_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def parse_specials(raw, today: date) -> List[SpecialWatch]:
    """users[].specials 原始列表 → 归一化订阅。坏条目整条丢弃（宁缺
    勿错，不炸进程），钳制防手滑：days 1..180（≤0 回 30）、往返窗
    0..30、节流 ≥1。"""
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is False:
            continue
        code = iata3(item.get("from"))
        if not code:
            continue
        try:
            max_price = float(item.get("max_price") or 0)
        except (TypeError, ValueError):
            continue
        if max_price <= 0:
            continue
        days = _to_int(item.get("days"), 30)
        days = 30 if days <= 0 else min(days, 180)
        rt_days = _to_int(item.get("round_trip_days"), 7)
        plats = [str(p) for p in (item.get("platforms") or [])
                 if p in _KNOWN_SOURCES]
        pool = []
        for c in (item.get("dest_pool") or []):
            cc = iata3(c)
            if cc and cc not in pool:
                pool.append(cc)
        out.append(SpecialWatch(
            from_code=code,
            from_name=str(item.get("from_name") or code),
            max_price=max_price,
            days=days,
            round_trip=bool(item.get("round_trip", True)),
            round_trip_days=max(0, min(rt_days, 30)),
            interval_rounds=max(1, _to_int(item.get("interval_rounds"), 4)),
            dest_pool=pool,
            platforms=plats or [SRC_TUNIU, SRC_CTRIP, SRC_CTRIP_BD,
                                SRC_FLIGGY],
        ))
    return out


def tuniu_link(from_code: str, to_code: str, d: str, ret: str = "") -> str:
    """途牛深链。单程=TuniuCrawler.list_url 单源直用（同源铁律：用户
    链接与爬虫主路径同源——PC 域 cheapList 模板曾在此处 造成 m. 站/
    flight. 站双轨，校准轮对齐现役推送链接口径，爬虫改版自动跟随）；
    往返=cheapList.js 官方 round 模板（唯一实证返程深链，H5 RT 路径
    未实证不杜撰）。"""
    if ret:
        return (f"http://flight.tuniu.com/city_{from_code}_{to_code}/"
                f"round/?start={d}&back={ret}")
    from crawlers.tuniu import TuniuCrawler   # 单源直用（无环：tuniu 只依赖 core.models）
    return TuniuCrawler.list_url(from_code, to_code, d)


def ctrip_link(from_code: str, to_code: str, to_name: str, d: str,
               from_name: str) -> str:
    """携程 H5 taro 深链（现役 URL_TPL 同族，调研已验证可渲染）。"""
    return ("https://m.ctrip.com/html5/flight/taro/first?from=inner"
            f"&tripType=ONE_WAY&dcity={from_code}"
            f"&dcityName={quote(from_name or from_code)}"
            f"&acity={to_code}&acityName={quote(to_name or to_code)}"
            f"&ddate={d}")


def special_deal_link(src: str, from_name: str, to_name: str,
                      depart_date: str, ret_date: str = "") -> str:
    """Verified source-channel deep link for one stored special deal."""
    fc = CITY.get(str(from_name or "").strip(), "")
    tc = CITY.get(str(to_name or "").strip(), "")
    if not fc or not tc or not depart_date:
        return ""
    if src == SRC_TUNIU:
        return tuniu_link(fc, tc, depart_date, ret_date or "")
    if src in (SRC_CTRIP, SRC_CTRIP_BD):
        return ctrip_link(fc, tc, to_name, depart_date, from_name)
    if src == SRC_FLIGGY:
        return ("https://sjipiao.fliggy.com/flight_search_result.htm"
                f"?depCity={fc}&arrCity={tc}&tripType=0"
                f"&depDate={depart_date}&searchBy=1314")
    return ""


def _in_window(d: str, today: date, days: int) -> bool:
    try:
        dd = date.fromisoformat(d)
    except ValueError:
        return False
    return today <= dd <= today + timedelta(days=days)


def deals_from_tuniu(payload: dict, watch: SpecialWatch,
                     today: date) -> List[SpecialDeal]:
    """途牛 queryCheapTickets 响应 → 候选特价。

    出发地闸：榜单城市=出口 IP 推断（不可指定），orgCityIata≠订阅
    出发地整条挡（含 airComFlightInfo 分组泄漏的异出发地特价——本
    解析只吃 cityFlightInfo 主榜单）。往返槽 roundTrip 与单程同构
    （returnDate 在场即成对下发），一并入池。"""
    data = (payload or {}).get("data") or {}
    cfi = data.get("cityFlightInfo") or {}
    rows = list(cfi.get("singleTrip") or [])
    rows += list(cfi.get("roundTrip") or [])
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        org, dst = iata3(r.get("orgCityIata")), iata3(r.get("dstCityIata"))
        if not org or not dst or org != watch.from_code:
            continue
        d = str(r.get("departureDate") or "")
        if not _RE_YYYYMMDD.match(d) or not _in_window(d, today, watch.days):
            continue
        try:
            price = float(r.get("priceBase") or 0)
        except (TypeError, ValueError):
            continue
        # 价带下限与五渠道爬虫同源同律（PRICE_MIN=100）：99 元档超特
        # 大促真实存在，此处有意牺牲——榜单语境下与垃圾价/拆分价不可
        # 辨，误杀损失小于毒价放行损失（宁缺勿错）
        if not (PRICE_MIN <= price <= PRICE_MAX
                and price <= watch.max_price):
            continue
        try:
            disc = float(r.get("discount") or 0)
        except (TypeError, ValueError):
            disc = 0.0
        ret = str(r.get("returnDate") or "")
        if not _RE_YYYYMMDD.match(ret):
            ret = ""
        # roundTrip 槽：priceBase=往返总价（Soldier P3#6），ret_price
        # 存同值仅作占位——推送渲染按「往返含返程」词面，勿当返程单程价
        out.append(SpecialDeal(
            src=SRC_TUNIU, from_code=org, to_code=dst, date=d,
            src_price=price, ret_date=ret,
            ret_price=price if ret else 0.0,
            airline=str(r.get("arlineCompany") or ""),
            discount=(f"{disc:g}折" if 0 < disc < 10 else ""),
            link=tuniu_link(org, dst, d, ret),
            to_name=str(r.get("dstCityName") or ""),
            tax_included=False, price_basis="bare",
            price_basis_label="裸价不含税",
        ))
    return out


def _decode_ctrip_date(v: str) -> str:
    """/Date(1792857600000+0800)/ → '2026-10-25'（按报文自带偏移换算，
    服务器时区无关）。烂形态返回空串由调用方过滤。无偏移的 /Date(ms)/
    形态按 UTC epoch 解释——当前调研实证 381 条全带 +0800（.NET UTC
    DateTime JSON 形态）；若渠道改发 unspecified 本地墙钟形态会漂一天，
    由日历观察哨（候选骤零/整体漂移）兜底。"""
    m = _RE_CTRIP_DATE.match(str(v or ""))
    if not m:
        return ""
    ms = int(m.group(1)) / 1000.0
    secs = ms
    if m.group(2):
        off = int(m.group(3)) * 3600 + int(m.group(4)) * 60
        secs += off if m.group(2) == "+" else -off
    return (date(1970, 1, 1) + timedelta(seconds=secs)).isoformat()


def ctrip_calendar_deals(payload: dict, from_code: str, to_code: str,
                         to_name: str, watch: SpecialWatch,
                         today: date, days: Optional[int] = None
                         ) -> List[SpecialDeal]:
    """携程 15380 低价日历（单航线跨日期）→ 候选特价。

    price=列表有票 tprice 同口径（双源互证）；尾部 0 元零填充过滤；
    软拒形态③（200 Success 空壳）自然得空表。days 缺省=watch.days
    （去程窗）；**返程解析须传放宽窗**（watch.days+round_trip_days，
    Soldier P3#7——去程贴窗尾时返程日在去程窗外的合法形态曾被误滤）。
    价带下限 PRICE_MIN=100 与五渠道爬虫同源同律（宁缺勿错）；99 元
    超特大促档是真实存在的形态，此处有意牺牲（<100 档与垃圾价/拆分
    价在榜单语境不可辨，误杀损失小于毒价放行损失）。"""
    rows = (payload or {}).get("priceList") or []
    win = watch.days if days is None else days
    # 整年分布基线（校准轮落地）：有效价全集取最低，候选 ≤ 年低 1.01
    # 即打「年度最低」词面——绝对低价线筛不出「真降价」，分布比才筛得
    # 出（¥450 的 URC 是特价、¥480 的 BJS 只是寻常）
    year_min = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            _p = float(r.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if PRICE_MIN <= _p <= PRICE_MAX and (year_min is None
                                             or _p < year_min):
            year_min = _p
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = _decode_ctrip_date(r.get("departDate"))
        if not d or not _in_window(d, today, win):
            continue
        try:
            price = float(r.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if not (PRICE_MIN <= price <= PRICE_MAX
                and price <= watch.max_price):
            continue
        out.append(SpecialDeal(
            src=SRC_CTRIP, from_code=from_code, to_code=to_code, date=d,
            src_price=price,
            link=ctrip_link(from_code, to_code, to_name, d,
                            watch.from_name),
            to_name=to_name,
            discount=("年度最低" if year_min is not None
                      and price <= year_min * 1.01 else ""),
            tax_included=None, price_basis="unknown",
            price_basis_label="口径未标注",
        ))
    return out


def deals_from_ctrip_board(payload: dict, watch: SpecialWatch,
                           today: date) -> List[SpecialDeal]:
    """携程 19728 主题榜 → 候选特价。

    routes[].departCity.code=出发地（≠订阅出发地整条挡——策展组
    bd_* 替换失效时服务端可能仍返回原出发地行，闸在此兜底）；
    pl[] 每项一个日期价（isContainsTax=False 裸价口径，与途牛同族
    ——推送一律以核实价为准）。jumpUrl=官方 H5 深链随行直用。"""
    out = []
    for rt in (payload or {}).get("routes") or []:
        if not isinstance(rt, dict):
            continue
        org = iata3((rt.get("departCity") or {}).get("code"))
        arr = (rt.get("arriveCity") or {})
        dst = iata3(arr.get("code"))
        if not org or not dst or org != watch.from_code:
            continue
        to_name = str(arr.get("name") or "")
        for pl in rt.get("pl") or []:
            if not isinstance(pl, dict):
                continue
            d = str(pl.get("departDate") or "")
            if not _RE_YYYYMMDD.match(d) or not _in_window(d, today,
                                                           watch.days):
                continue
            try:
                price = float(pl.get("price") or 0)
            except (TypeError, ValueError):
                continue
            # 价带下限同族备案见 ctrip_calendar_deals（99 元档有意牺牲）
            if not (PRICE_MIN <= price <= PRICE_MAX
                    and price <= watch.max_price):
                continue
            link = str(pl.get("jumpUrl") or "")
            if not link.startswith("http"):
                link = ctrip_link(org, dst, to_name, d, watch.from_name)
            # decRate=-0.74 → 2.6 折（校准轮实测值域，与现役折扣词面
            # 同口径：1+decRate 即折扣率）
            try:
                _dr = float(pl.get("decRate") or 0)
            except (TypeError, ValueError):
                _dr = 0.0
            _zk = 1.0 + _dr
            out.append(SpecialDeal(
                src=SRC_CTRIP_BD, from_code=org, to_code=dst, date=d,
                src_price=price, link=link, to_name=to_name,
                discount=(f"{_zk * 10:g}折" if 0 < _zk < 1 else ""),
                tax_included=False, price_basis="bare",
                price_basis_label="裸价不含税"))
    return out


def deals_from_fliggy_board(payload: dict, watch: SpecialWatch,
                            today: date) -> List[SpecialDeal]:
    """飞猪 PC 特价航班榜 → 候选特价。

    data.flights[]：depCode=出发城市码（≠订阅出发地整条挡——城市/
    机场码口径差在此兜底）；soldOut=true 剔（无票价，与现役 quantity
    守卫同语义）；discount 数值折（1.9=1.9折，常 null）。深链与现役
    FliggyCrawler.URL_TPL 同域同路径族（sjipiao SSR 页）。"""
    data = (payload or {}).get("data") or {}
    out = []
    for f in data.get("flights") or []:
        if not isinstance(f, dict) or f.get("soldOut"):
            continue
        org, dst = iata3(f.get("depCode")), iata3(f.get("arrCode"))
        if not org or not dst or org != watch.from_code:
            continue
        d = str(f.get("depDate") or "")
        if not _RE_YYYYMMDD.match(d) or not _in_window(d, today, watch.days):
            continue
        try:
            price = float(f.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if not (PRICE_MIN <= price <= PRICE_MAX
                and price <= watch.max_price):
            continue
        try:
            disc = float(f.get("discount") or 0)
        except (TypeError, ValueError):
            disc = 0.0
        to_name = str(f.get("arrName") or "")
        out.append(SpecialDeal(
            src=SRC_FLIGGY, from_code=org, to_code=dst, date=d,
            src_price=price, to_name=to_name,
            discount=(f"{disc:g}折" if 0 < disc < 10 else ""),
            link=("https://sjipiao.fliggy.com/flight_search_result.htm"
                  f"?depCity={org}&arrCity={dst}&tripType=0&depDate={d}"
                  "&searchBy=1314"),
            tax_included=None, price_basis="unknown",
            price_basis_label="口径未标注",
        ))
    return out


def pair_ctrip_returns(out_deals: List[SpecialDeal],
                       rev_deals: List[SpecialDeal],
                       watch: SpecialWatch) -> None:
    """携程返程配对（就地写 out_deals）：反向日历同接口查询，窗
    [去程日, 去程日+round_trip_days]，返程源价 ≤ 心理价位取最低。
    watch.round_trip=False 时整体跳过。"""
    if not watch.round_trip:
        return
    rt_days = timedelta(days=watch.round_trip_days)
    for o in out_deals:
        if o.ret_date:
            continue   # 榜单已成对（途牛 roundTrip）不覆盖
        try:
            d0 = date.fromisoformat(o.date)
        except ValueError:
            continue
        cands = [r for r in rev_deals
                 if r.from_code == o.to_code and r.to_code == o.from_code
                 and o.date <= r.date <= (d0 + rt_days).isoformat()
                 and r.src_price <= watch.max_price]
        if cands:
            best = min(cands, key=lambda r: r.src_price)
            o.ret_date, o.ret_price = best.date, best.src_price


def special_key(d: SpecialDeal) -> str:
    """去抖键（storage 侧再冠 'special|' 前缀入 alert_state 表）。

    键粒度=OD+日期（**不含 src**，Soldier P2#1）：同一 OD+同日两源
    各报价时只核实/推送一次——用户不需要知道特价来自哪家的榜，重复
    快讯即噪声；后到源只可能通过「降价 ≥drop_min」路径再触发。"""
    return f"{d.from_code}|{d.to_code}|{d.date}"


def select_for_verify(deals: List[SpecialDeal],
                      get_pushed: Callable[[str], Optional[float]],
                      cap: int = 3, drop_min: float = 30,
                      blocked: Optional[Callable[[str], bool]] = None
                      ) -> List[SpecialDeal]:
    """候选选择：同 OD+日期跨源去重（保源价低者，Soldier P2#1）；新键
    （未推过）或源价较已推价降 ≥drop_min 才重核；blocked(key)=True 的
    键跳过（核实未过的当日负缓存，Soldier P2#2——drop/retry 不落
    pushed 态会让坏候选每轮重占 cap 预算，第 4 名以后新候选永久饿死）；
    按源价升序取前 cap 条。"""
    best = {}
    for d in deals:
        k = special_key(d)
        cur = best.get(k)
        if cur is None or d.src_price < cur.src_price:
            best[k] = d
    out = []
    for k, d in sorted(best.items(), key=lambda kv: kv[1].src_price):
        pushed = get_pushed(k)
        if pushed is not None and d.src_price >= pushed - drop_min:
            continue
        if blocked is not None and blocked(k):
            continue
        out.append(d)
        if len(out) >= max(1, cap):
            break
    return out


def verify_verdict(min_price: Optional[float], src_price: float,
                   max_price: float) -> Tuple[str, object]:
    """核实判定：min_price=该 OD+日期跨渠道最低可买价（None=全渠道
    零行 → 'retry' 下轮再核）；超容忍带 → 'drop/虚高'（榜单价不可信）；
    超心理线 → 'drop/超线'；否则 ('push', 核实价)。"""
    if min_price is None:
        return ("retry", None)
    min_price = float(min_price)
    if min_price > src_price * _VERIFY_TOLERANCE:
        return ("drop", "虚高")
    if min_price > max_price:
        return ("drop", "超线")
    return ("push", min_price)


def should_push(price: float, pushed: Optional[float],
                drop_min: float = 30) -> bool:
    """推送去抖：首推恒推；已推则须降价 ≥drop_min 才重推。"""
    if pushed is None:
        return True
    return price <= pushed - drop_min


def special_due(round_no: int, interval_rounds: int, force: bool) -> bool:
    """轮次节流：第 1、1+N、… 轮跑发现；force=保存配置即触发。"""
    if force:
        return True
    n = max(1, int(interval_rounds or 1))
    return (round_no - 1) % n == 0


def build_special_push(watch: SpecialWatch,
                       results: List[Tuple[SpecialDeal, float]]
                       ) -> Tuple[str, str]:
    """核实通过集 → (title, desp)。行=核实价主口径+源价标注+深链，
    往返段随行。空集返回空串（调用方跳过推送）。"""
    if not results:
        return "", ""
    title = f"💰 特价快讯｜{watch.from_name}出发"
    blocks = []
    for d, vp in results:
        tname = (d.to_name or _POOL_NAME.get(d.to_code)
                 or AIRPORT_NAME_CN.get(d.to_code) or d.to_code)
        # 行宽纪律（钉钉手机 ≤20 全角/行）：行组装一律段落级 \n\n
        # （r339e P2-2：段内单 \n 在 PC 被并回一行，日期与价格贴字
        # 「10-20￥2600」实锤）。币符统一全角 ￥（c330 审校 C4：半角 ¥
        # 是全库唯一币符分叉，「确定安全字符集」在册币符是全角）；
        # 附加段（折扣+航司）超宽剥尾保价判据——价格行此前无任何守卫
        # （价+源价是核心判据）
        _pw = (f"￥{float(vp):.0f}（{_SRC_LABEL.get(d.src, d.src)}"
               f"源价￥{d.src_price:.0f}）")
        _tw = ((d.discount or "")
               + (f"·{d.airline}" if d.airline else ""))
        if _tw and _dw(_pw) + _dw(_tw) > 40:
            _tw = ""
        # 首行行宽守卫（r339e P2-2：长名域实测 48/40）——降级链
        # 剥机场括注→剥名保日期地板（价格判据在第二行恒不陪葬）
        _fn = re.sub(r"[（(][^（）()]*[）)]", "", watch.from_name)
        _tn = re.sub(r"[（(][^（）()]*[）)]", "", tname)
        head = _fit_line(
            f"✅ {watch.from_name}→{tname} {d.date[5:]}",
            fallbacks=[
                f"✅ {_fn}→{_tn} {d.date[5:]}",
                f"✅ {d.date[5:]}"])
        line = f"{head}\n\n{_pw}{_tw}"
        if d.ret_date:
            if d.ret_price and abs(d.ret_price - d.src_price) > 0.5:
                # 返程独立有价（ctrip 反向日历配对的单程价）
                line += f"\n\n返程 {d.ret_date[5:]} ￥{d.ret_price:.0f}"
            else:
                # 途牛 roundTrip：src_price 已是往返总价，返程段不重复
                # 显价（词面「返程 ¥X」会被读成返程单程价，Soldier P3#6）
                line += f"\n\n往返含返程 {d.ret_date[5:]}"
        if d.link:
            line += f"\n\n[购买直达]({d.link})"
        blocks.append(line)
    return title, "\n\n".join(blocks)
