"""途牛机票：纯 httpx 直连 (逆向 tac.js cookie, 不依赖浏览器)。

途牛国内机票真实价格通过接口 flight-api.tuniu.com/wzt/flight/v1/listFlight 异步轮询返回
(fareList), 带有 mtoken + tac.js 追踪/指纹 cookie 的风控 (缺失即 179991)。

逆向结论 (经验证):
  179991 的本质是缺少途牛自有的追踪 cookie (由 CDN 上的 tac.js 在前端生成)。
  补齐以下 cookie 后, httpx 可直接调 listFlight 拿到 fareList:

    udid : GET https://h5api.tuniu.com/auth/getDeviceId?d={"type":1}&c={"ct":30}
    _taca : "{loginTime}.{loginTime}.{loginTime}.1" (loginTime = 毫秒时间戳)
    _tacb : base64(newGuid())
    _tacc : "1"
    _tact : base64(newGuid())
    _tacau : base64("0," + newGuid() + ",")
    _tacz2 : base64("0," + newGuid() + ",,")

  newGuid(): 32 位随机 hex, 在第 8/12/16/20 位后插入 "-" (复刻 tac.js)。

"hoop": 一圈一圈重试 (可设上限), 直到真正拿到真实价格 (fareList) 才停止。
每圈使用全新生成的 cookie 会话, 天然实现"换设备指纹"以规避频率限制。
实测: 同一出口 IP 约 3 次成功后触发 179991, 冷却约 10 分钟; 用滑动窗口限速。
"""
from __future__ import annotations

import os
import base64
import json
import random
import re
import threading
import time
from typing import Any, List, Optional

import httpx

from core.flightnorm import cabin_clean
from core.models import PRICE_MAX, PRICE_MIN, FlightPrice
from .base import BaseCrawler, iata2, iata3

_RE_HHMM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def _hhmm(s) -> str:
    """从渠道时刻串提取 HH:MM（[-5:] 切片对 "19:55:00" 会切出 "5:00"）。"""
    m = _RE_HHMM.search(str(s or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _stop_time(points) -> str:
    """stopPoints[].duration（分钟）→「X小时Y分」中文形态（normalize 的
    stopTimeT 只认这个格式）；无有效值返回空串宁缺勿错。"""
    total = 0
    for x in points or []:
        if isinstance(x, dict):
            try:
                total += int(float(x.get("duration") or 0))
            except (TypeError, ValueError):
                pass
    return f"{total // 60}小时{total % 60}分" if total > 0 else ""


def _stop_window(points) -> str:
    """stopPoints[].arrivalTime/departrueTime（departrue 为渠道原始
    拼写）→ 经停窗口「HH:MM-HH:MM」；多段「/」连接。段缺任一时刻
    不成对（宁缺勿错）；与 duration 数值互证成立（19:20→20:05 =
    45 分）。五渠道唯一经停段时刻源，判红眼/晚间滞留。"""
    legs = []
    for x in points or []:
        if not isinstance(x, dict):
            continue
        m = _RE_HHMM.search(str(x.get("arrivalTime") or ""))
        m2 = _RE_HHMM.search(str(x.get("departrueTime") or ""))
        if m and m2:
            legs.append(f"{int(m.group(1)):02d}:{m.group(2)}"
                        f"-{int(m2.group(1)):02d}:{m2.group(2)}")
    return "/".join(legs)


def _prate(v) -> str:
    """onTimeRate 净化：途牛对无真值航班下发恒「20%」占位默认值
    （10-05/06 dump 实锤 9 家航司同刻 20%，同航班 ctrip 实为 90-97，
    9/9 全背离）——原样入库会拉低准点率对比可信度，宁缺勿错置空。"""
    s = str(v or "").strip().rstrip("%").strip()
    return "" if s in ("20", "20.0") else s

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

FLIGHT_HOME = "https://m.tuniu.com/flight"
LIST_API = "https://flight-api.tuniu.com/wzt/flight/v1/listFlight"
DEVICE_ID_API = "https://h5api.tuniu.com/auth/getDeviceId"
COOKIE_DOMAIN = ".tuniu.com"

# 降级样本早收门槛：渠道存在 fareList 截断降级形态（实录：截断轮
# n=1/3 条、最低价落库较健康轮虚高 50%，且逐轮交替出勤）；门槛只
# 约束「首响即收」——薄样本续询穷尽后仍以 best-so-far 兜底返回，
# 真稀疏日期零数据丢失（不丢数据，也不早收坏样本）。
# 门槛值=健康带下缘：自然轮 n 分布三段——薄带 3-15/空档 16-38/
# 健康 39+。两级被否决的取法：门槛落在薄带内时，恰卡门槛的截断轮
# 8 班全缺真最低班、落库虚高；门槛落在空档中段时，20-38 段首响
# 即收即过闸——「空档恒空」的 dump 抽样推断被自然轮逐轮分布推翻
# （DB 该带按日出勤，抽检 min/max 在场=真稀疏与良性截断并存）。
# 按「整个过闸带落入续询面」的设计哲学取 39：健康轮零额外请求
# 不回退，<39 全带续询（渠道分布再漂移时按逐轮 n 分布复检门槛）
_FARE_FLOOR = 39
_THIN_MAX = 3


class TuniuCrawler(BaseCrawler):
    name = "tuniu"
    use_mobile = True

    RATE_MAX = 3
    RATE_WINDOW = 600.0

    @classmethod
    def list_url(cls, fc: str, tc: str, date: str) -> str:
        """列表页入口（fetch 与用户侧 _build_view_url 同源构造——
        链接一致性测试曾锚测试文件内的硬编码字符串，爬虫改版不红）。"""
        return (f"https://m.tuniu.com/flight/domestic/new/"
                f"{fc}_{tc}_OW_1_0_0?deptDate={date}&isGo=0")

    def __init__(self, config: dict, logger):
        super().__init__(config, logger)
        self.max_attempts: int = int(config.get("max_attempts", 5))
        self.max_poll: int = int(config.get("tuniu_max_poll", 10))
        self.backoff_s: float = float(config.get("backoff_seconds", 5))
        self.rate_limit: bool = bool(config.get("rate_limit", True))
        self._success_times: list = []
        self._rate_lock = threading.Lock()

    def login_url(self) -> str:
        return "https://www.tuniu.com/"

    def _rate_acquire(self):
        while True:
            with self._rate_lock:
                now = time.time()
                self._success_times[:] = [t for t in self._success_times if now - t < self.RATE_WINDOW]
                if len(self._success_times) < self.RATE_MAX:
                    return
                wait = self.RATE_WINDOW - (now - self._success_times[0]) + 0.5
            time.sleep(min(wait, 30))

    def _rate_record(self):
        with self._rate_lock:
            self._success_times.append(time.time())

    @staticmethod
    def _new_guid() -> str:
        out = ""
        for o in range(1, 33):
            out += format(random.randint(0, 15), "x")
            if o in (8, 12, 16, 20):
                out += "-"
        return out

    @staticmethod
    def _b64(s: str) -> str:
        return base64.b64encode(s.encode("utf-8")).decode("ascii")

    def _fetch_udid(self, client: httpx.Client) -> str:
        try:
            r = client.get(
                DEVICE_ID_API,
                params={"d": '{"type":1}', "c": '{"ct":30}'},
                headers={"Referer": "https://m.tuniu.com/"},
                timeout=15,
            )
            return r.json().get("data", {}).get("udid", "") or ""
        except Exception:
            return ""

    def _install_tac_cookies(self, client: httpx.Client) -> None:
        now = int(time.time() * 1000)
        cookies = {
            "udid": self._fetch_udid(client),
            "_taca": f"{now}.{now}.{now}.1",
            "_tacb": self._b64(self._new_guid()),
            "_tacc": "1",
            "_tact": self._b64(self._new_guid()),
            "_tacau": self._b64("0," + self._new_guid() + ","),
            "_tacz2": self._b64("0," + self._new_guid() + ",,"),
        }
        for k, v in cookies.items():
            if v:
                client.cookies.set(k, v, domain=COOKIE_DOMAIN, path="/")

    @staticmethod
    def _has_price(node: Any) -> bool:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("salePrice", "baseFare", "lowestPrice", "barePrice") and isinstance(v, (int, float)) and v > 0:
                    return True
                if TuniuCrawler._has_price(v):
                    return True
        elif isinstance(node, list):
            return any(TuniuCrawler._has_price(i) for i in node)
        return False

    @classmethod
    def _poll_sample(cls, body: str) -> tuple:
        """轮询响应定样：(obj, fare 条数, 是否历史无 fareList 价格形)。

        坏 JSON / success 非 true → (None, 0, False)；data 缺席/非 dict
        视为空（n=0、无历史价格形）。历史形态（data.salePrice 等、
        无 fareList）保持首响即收语义。"""
        try:
            obj = json.loads(body)
        except Exception:
            return None, 0, False
        if not isinstance(obj, dict) or obj.get("success") is not True:
            return None, 0, False
        data = obj.get("data") or {}
        if not isinstance(data, dict):
            return None, 0, False
        n = len(data.get("fareList") or [])
        return obj, n, (n == 0 and cls._has_price(data))

    def _one_attempt(self, depart_code, arrive_code, depart_date):
        client = httpx.Client(
            headers={
                "User-Agent": self._ua() or UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "sec-ch-ua-platform": '"iOS"',
                "sec-ch-ua-mobile": "?1",
            },
            timeout=25,
            follow_redirects=True,
        )
        try:
            client.get(FLIGHT_HOME)
            client.get(self.list_url(depart_code, arrive_code, depart_date))

            self._install_tac_cookies(client)
            mtoken = client.cookies.get("mtoken", "") or ""

            d_tmpl = {
                "systemId": 53, "channelCount": 0,
                "adultQuantity": 1, "childQuantity": 0, "babyQuantity": 0,
                "supportBlack": True,
                "segmentList": [
                    {"dCityIataCode": depart_code, "aCityIataCode": arrive_code, "departDate": depart_date}
                ],
                "rph": 0, "hackersFlightNos": None, "tokenKey": mtoken,
            }
            api_hdrs = {"Referer": "https://m.tuniu.com/", "Accept": "application/json"}

            last = ""
            blocked = False
            best = None  # 薄样本 best-so-far: (obj, n)
            thin_seen = 0
            for poll in range(self.max_poll):
                d = dict(d_tmpl)
                d["pollTag"] = poll
                r = client.get(LIST_API, params={"d": json.dumps(d, ensure_ascii=False)}, headers=api_hdrs)
                last = r.text
                if "179991" in last:
                    blocked = True
                obj, n, legacy_price = self._poll_sample(last)
                if obj is not None and (n >= _FARE_FLOOR or legacy_price):
                    return True, obj, blocked
                if n > 0:
                    # 薄样本（0<n<门槛）：不早收，记 best-so-far 续询——
                    # 截断降级逐轮交替，紧邻两拍大概率拿到全量；
                    # 薄响应最多连看 _THIN_MAX 个（礼貌预算有界）
                    # （n<门槛含空档带 16-38：DB 逐轮分布实证该带非恒空，
                    # 真稀疏由 best-so-far 兜底零丢失）
                    if best is None or n > best[1]:
                        best = (obj, n)
                    thin_seen += 1
                    if thin_seen >= _THIN_MAX:
                        break
                time.sleep(1.5)
            if best is not None:
                self.logger.warning(
                    "[tuniu] %s 疑似降级样本 fareList n=%d（早收门槛 %d 条）"
                    "——以 best-so-far 兜底",
                    depart_date, best[1], _FARE_FLOOR)
                return True, best[0], blocked
            return False, None, blocked
        except Exception as ex:
            self.logger.warning("[tuniu] 请求异常: %s", ex)
            return False, None, False
        finally:
            client.close()

    def _hoop(self, fc, tc, date) -> Optional[dict]:
        attempt = 0
        while True:
            attempt += 1
            if self.rate_limit:
                self._rate_acquire()
            ok, raw, blocked = self._one_attempt(fc, tc, date)
            if ok:
                if self.rate_limit:
                    self._rate_record()
                self.logger.info("[tuniu] %s 第 %d 圈拿到真实价格", date, attempt)
                return raw
            if self.max_attempts and attempt >= self.max_attempts:
                self.logger.warning("[tuniu] %s 达到最大重试圈数 %d 仍未拿到价格%s",
                                     date, self.max_attempts, "(疑似风控/179991)" if blocked else "")
                return None
            time.sleep(self.backoff_s * (2 if blocked else 1))

    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        results: List[FlightPrice] = []
        fc, tc = from_city.upper(), to_city.upper()
        for date in dates:
            raw = self._hoop(fc, tc, date)
            self._dump_raw(raw, f"tuniu_raw_{date}")
            if raw is None:
                self.logger.warning("[tuniu] %s 未拿到真实价格", date)
                self._sleep()
                continue

            offers = self._parse_offers(raw, logger=self.logger)
            best = self._lowest_offer(offers)
            flights = self._offers_to_flights(offers)
            if best is not None and best.get("price"):
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=best.get("airline") or "",
                    flight_no=best.get("flight_no") or "",
                    depart_time=best.get("depart_time") or "",
                    arrive_time=best.get("arrive_time") or "",
                    extra=json.dumps(flights, ensure_ascii=False) if flights else "",
                ))
                n_d = sum(1 for f in flights if not f.get("transCity"))
                self.logger.info("[tuniu] %s 最低价 ￥%.0f (%s %s)（明细 %d 条：直飞 %d / 中转 %d）",
                                 date, best["price"], best.get("airline") or "",
                                 best.get("flight_no") or "",
                                 len(flights), n_d, len(flights) - n_d)
            else:
                self.logger.warning("[tuniu] %s 未解析到价格", date)
            self._sleep()
        return results

    @staticmethod
    def _to_price(v: Any) -> Optional[float]:
        # 价格带 300–50000 与其余四渠道对齐（补下限：单渠道
        # 零下限曾让改版键义漂移出的小数/异常值直入渠道最低价对比）
        try:
            f = float(v)
            return f if PRICE_MIN <= f <= PRICE_MAX else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _adt_fare(cls, price_list: list) -> tuple:
        """ADT 价与同 breakdown 折扣/公布运价/舱位配对返回 (price,
        discount, black, stdfare, cabin, cabin_code)。

        价格=各 flightPriceList 中 psgType=ADT 的最低 baseFare；折扣、
        公布运价、舱名与舱位代码全部随选中价所在政策提取（跨政策取
        即串舱——r222 实锤：公务舱政策排前时行价是经济舱最低价却标
        「公务舱」，三份 dump 5/40、2/46、3/44 复现）。discount 值形如
        "6.7折"/"全价"（dump 实证），"0"/空=未报价占位（ADT 也有
        13/77 行）不作为折扣值。无 ADT 价返回 (None, "", False, None,
        "", "")。black=选中价政策 supportBlack 旗标（渠道调研 B：45/117
        报价单选中价来自黑卡政策，报文零文字性会员门标注——不改选价
        口径，只落透明标记让受众自判）；同价平手按普通政策算（标记零
        误报），舱名随平手胜者。stdfare=同条目 bcTaxExclusiveFare 舱位
        公布运价（报销/里程累积口径，baseFare=bcTax×1.01 恒系数互证；
        ADT 正值 56%、-1/0 占位 44%——非正数一律 None 不落键）。
        cabin_code=选中政策内聚合恰一个舱位代码才落（政策内多码宁缺
        勿错；跨政策聚合曾把出勤压到 35-59%）。"""
        best = None
        disc = ""
        black = False
        std = None
        cab = ""
        code = ""
        for pr in price_list or []:
            is_black = bool(pr.get("supportBlack"))
            for fb in pr.get("fareBreakdownList", []) or []:
                if fb.get("psgType") != "ADT":
                    continue
                p = cls._to_price(fb.get("baseFare"))
                if not p:
                    continue
                if best is None or p < best or (p == best and black and not is_black):
                    best = p
                    d = str(fb.get("discount") or "").strip()
                    disc = d if d not in ("", "0") else ""
                    black = is_black
                    cab = cls._cabin_from_pj(pr.get("priceJourneyCabinList"))
                    codes = []
                    for pj in pr.get("priceJourneyCabinList") or []:
                        for pfc in (pj.get("priceFlightCabinList") or []):
                            c = str((pfc or {}).get("cabinCode") or "").strip()
                            if c and c not in codes:
                                codes.append(c)
                    code = codes[0] if len(codes) == 1 else ""
                    try:
                        s = float(fb.get("bcTaxExclusiveFare"))
                    except (TypeError, ValueError):
                        s = None
                    # 有限性+值域双挡：inf/NaN 与超价格带脏值不落
                    # （inf 过 s>0 会产非法 JSON Infinity）
                    std = s if s and 0 < s <= PRICE_MAX else None
        return (best, disc, black, std, cab, code)

    @classmethod
    def _biz_fare(cls, price_list: list) -> Optional[float]:
        """公务/商务/头等舱政策的 ADT 最低 baseFare（bizPrice）。

        与 _adt_fare 完全独立遍历（次低价≠公务舱，串舱即错配——ctrip
        「舱位随最低价政策配对」同律；主价链的舱名随选中政策提取后，
        本函数的独立高档舱口径不变）；舱位判定挂 priceJourneyCabinList
        嵌套层（_cabin_from_pj 同路径）；判定词表与 tongcheng pts.td 一致
        （三渠道 bizPrice 同键同协议）。无高档舱政策/全部超域返回 None，
        调用方不落键。"""
        best = None
        for pr in price_list or []:
            if cls._cabin_from_pj(
                    pr.get("priceJourneyCabinList")) not in (
                    "公务舱", "商务舱", "头等舱"):
                continue
            for fb in pr.get("fareBreakdownList", []) or []:
                if fb.get("psgType") != "ADT":
                    continue
                p = cls._to_price(fb.get("baseFare"))
                if p and (best is None or p < best):
                    best = p
        return best

    @classmethod
    def _child_infant_fares(cls, price_list: list) -> tuple:
        """(child, infant) 最低 baseFare（psgType=CHD/INF，10-05 dump
        164 处实证）。与 qunar H5 childPrice/infantPrice 数值协议对齐
        （跨渠道口径统一）：无值返回 (None, None) 由调用方不落键。
        勿走主价格带过滤（PRICE_MIN 下界是成人票价纪律，真实婴儿价
        常低于下界会被整段杀掉——本函数自带宽域 50–50000）。"""
        child = infant = None
        for pr in price_list or []:
            for fb in pr.get("fareBreakdownList", []) or []:
                t = fb.get("psgType")
                if t not in ("CHD", "INF"):
                    continue
                try:
                    p = float(fb.get("baseFare"))
                except (TypeError, ValueError):
                    continue
                if not (50 < p <= 50000):
                    continue
                if t == "CHD":
                    child = p if child is None else min(child, p)
                else:
                    infant = p if infant is None else min(infant, p)
        return (child, infant)

    @classmethod
    def _cabin_from_pj(cls, pj_list) -> str:
        """priceJourneyCabinList → priceFlightCabinList → cabinTypeName。"""
        for pj in pj_list or []:
            if not isinstance(pj, dict):
                continue
            for pc in pj.get("priceFlightCabinList") or []:
                if isinstance(pc, dict) and str(pc.get("cabinTypeName") or "").strip():
                    return str(pc["cabinTypeName"]).strip()
        return ""

    @staticmethod
    def _find_flight_detail(flight_list: dict, flight_no: str) -> dict:
        if not isinstance(flight_list, dict):
            return {}
        if flight_no in flight_list:
            return flight_list[flight_no]
        for key, val in flight_list.items():
            if key.split("#", 1)[0] == flight_no:
                return val
        return {}

    @classmethod
    def _parse_offers(cls, raw: Optional[dict], logger=None) -> List[dict]:
        if not raw:
            return []
        data = raw.get("data", raw) or {}
        fare_list = data.get("fareList") or []
        flight_list = data.get("flightList") or {}

        offers: List[dict] = []
        seen = set()
        for fare in fare_list:
            options = fare.get("flightOptions") or []
            flight_nos_str = options[0].get("flightNos") if options else None
            if not flight_nos_str:
                continue
            first_no = flight_nos_str.split("-")[0]
            detail = cls._find_flight_detail(flight_list, first_no)
            # 多段 offer 地雷（保守修）：detail 只能按首段航班号取到，
            # 其 arrTime/arrDate/flightTime 均为首段口径——当整体写入会让
            # 「最晚到达约束」按第一段到达误判。整体起终字段不可得时显式
            # 跳过该 offer（宁缺勿错，不造数据）
            if "-" in flight_nos_str or detail.get("transCity"):
                if logger:
                    logger.debug("[tuniu] 跳过多段中转 offer %s"
                                 "（明细仅首段口径，整体起终不可得）",
                                 flight_nos_str)
                continue
            price, fare_disc, fare_black, fare_std, fare_cab, fare_code = \
                cls._adt_fare(fare.get("flightPriceList"))
            child, infant = cls._child_infant_fares(
                fare.get("flightPriceList"))
            biz = cls._biz_fare(fare.get("flightPriceList"))
            offer = {
                "airline": detail.get("airlineCompany"),
                # 航司二字码（detail.airlineIataCode「MU」，45/45+46/46
                # 全场）：机器可读航司键，与 qunar shortCarrier 跨渠道
                # 统一出口 airlineCode；iata2 守卫不匹配落空串。注意
                # detail 层 dCityIataCode/aCityIataCode 是城市码勿混
                "airlineCode": iata2(detail.get("airlineIataCode")),
                "flight_no": flight_nos_str,
                "depart_time": detail.get("departureTime"),
                "arrive_time": detail.get("arrivalTime"),
                "price": price,
                "dep_date": detail.get("departureDate"),
                "arr_date": detail.get("arrivalDate"),
                "flight_time": detail.get("flightTime"),
                # 舱位在 fare 层且随选中价政策配对（r222 串舱修复：舱名
                # 取 _adt_fare 胜出政策的 cabinTypeName，跨政策借名即
                # 串舱；detail.cabinTypeName 恒缺〔DB 实锤 100% 空〕，
                # 旧顶层形态走 fare 级兼容回退，两层皆无宁缺勿错）。
                # 写入端再过 cabin_clean 清污门（与消费端同判据单源）：
                # 渠道会把低价政策标成高档舱名（DB 近 7 天 cabin=公务舱
                # 4039 行 price 中位 3310≈经济舱、bizPrice=8340 同行
                # 100% 同现），价位矛盾形态落库即脏值——消费端渲染门
                # 全挡，此门管 DB 面（补全链的补全源读取也在 alerter
                # 侧过同门，双层各自独立成立）
                "cabin": cabin_clean(
                    {"cabin": (detail.get("cabinTypeName") or fare_cab
                               or cls._cabin_from_pj(
                                   fare.get("priceJourneyCabinList"))
                               or ""),
                     "price": price, "bizPrice": biz}),
                # 黑卡价旗标随选中价透传（offer→row 有值才落，见 _adt_fare）
                "blackCard": fare_black,
                # 公务/商务/头等舱参考价（ctrip bizPrice 同键同协议，
                # webui 通道现成；offer→row 有值才落）
                "bizPrice": biz,
                # 决策四件套必须随 offer 透传：_offers_to_flights 从 offer
                # 读这些键，漏带即机型/餐食/准点率/经停恒空（假解析）
                # craftTypeName 缺失行落 craftType 原码兜底（B 篇 33/33
                # 恒在，补 DB 11% 机型缺口；不建码表翻译宁缺勿错，
                # 值形「73M」与 tongcheng plane 同域）
                "craftTypeName": (detail.get("craftTypeName")
                                  or str(detail.get("craftType")
                                         or "").strip()),
                "mealName": detail.get("mealName") or "",
                "onTimeRate": _prate(detail.get("onTimeRate")),
                "stopPoints": detail.get("stopPoints") or [],
                # ---- 决策字段补采（10-05 dump 46 航班实证，
                # flightList 值层，_find_flight_detail 已取到 detail）----
                # 航站楼：aTerminal 46/46（T1/T2）；dTerminal 间歇下发
                # （09-25 dump 43/43 有值，10-04~07 恒空串）——两键同守
                # 有值才落（无值不落键族律：键在场零信息；消费端 or ""
                # 判定缺键等价）
                **({"arrTerminal": str(detail.get("aTerminal")).strip()}
                   if str(detail.get("aTerminal") or "").strip() else {}),
                **({"depTerminal": str(detail.get("dTerminal")).strip()}
                   if str(detail.get("dTerminal") or "").strip() else {}),
                # 共享实际承运航班号：codeShare 实测即执飞航班号字符串
                # （"CZ6981"/"MU5700"，24/46；非布尔），与
                # shareCarrier「实际承运航班号」语义一致直接落
                # （sAirComName 航司名兜底合并至下方 shareCarrier）
                # 历史平均延误（分钟）：字符串形态 "29"/""（键在场 46/46、
                # 可转数字 28/46），仅数字转 int；无值/非数字不落键
                # （空串占位曾达生产 44.2%——消费端 None/缺键等价，
                # 哨兵出勤统计不变，纯 DB 卫生）
                **({"avgDelay": int(str(detail["avgDelayTime"]).strip())}
                   if str(detail.get("avgDelayTime") or "")
                   .strip().isdigit() else {}),
                # 机龄原始串（"6.3"，28/46），协议要求保留原始形态不转数值；
                # 无值不落键（空串占位曾 42% 平铺——缺席与空串消费端
                # 等价，载荷卫生 avgDelay/discount 同族）
                **({"planeAge": _pa} if (_pa := str(detail.get("flightYear")
                                                  or "").strip()) else {}),
                # 宽体机标签（调研④）：planeModelName 值域
                # 大/中/小，仅「大」落「宽体机」——craftTypeName 今日
                # 「波音737-800」无大小后缀，机型大小信息仅此键有；
                # 中/小不落（宽体=静音/宽敞正决策信号，反向词是噪音）；
                # 无值不落键（r241 残留族收口，offer 层与行层透传各自成立）
                **(({"labels": _lb}
                    if (_lb := ("宽体机" if str(detail.get("planeModelName")
                                                or "").strip() == "大"
                               else "")) else {})),
                # 机型体量结构化键（大/中/小 → 「大型机…」，与
                # fliggy/qunar PC 同键同值域；「宽体机」labels 是展示词
                # 保留双通道）；无值不落键（r241 残留族收口）。
                # 观察哨 W-T1（r268 渠道调研）：同层新槽位 crowdTagName
                # 三代恒空（按需扩容/拥挤度提示词嫌疑）——下发非空词面
                # 即复核（labels 同出口收，词面进白名单判据照走）
                **(({"planeSize": _ps}
                    if (_ps := {"大": "大型机", "中": "中型机",
                                "小": "小型机"}.get(
                       str(detail.get("planeModelName") or "").strip(), ""))
                    else {})),
                # 机场全名（dPortName/aPortName「天山机场/
                # 浦东机场」，dump 136/136 在场）——同城多场（虹桥 vs
                # 浦东）决策信息，五渠道键名对齐
                "depAirport": str(detail.get("dPortName") or "").strip(),
                "arrAirport": str(detail.get("aPortName") or "").strip(),
                # H1 机器可读机场码（dPortIataCode/aPortIataCode
                # 137/137 全 ^[A-Z]{3}$，与 qunar 48 共同航班号 48/48 同
                # 码对；iata3 守卫不匹配不落）。注意 detail 层还有
                # dCityIataCode/aCityIataCode 是城市码同串不同义，勿混
                "depAirportCode": iata3(detail.get("dPortIataCode")),
                "arrAirportCode": iata3(detail.get("aPortIataCode")),
                # 舱位代码随选中价政策聚合（_adt_fare 政策内单码守卫）
                "cabinCode": fare_code,
                # 共享实际承运：codeShare=执飞航班号优先（「CZ6981」），
                # 缺时落共享航司名 sAirComName（「上航」，70/136——
                # codeShare 73 行与之互补）
                "shareCarrier": (str(detail.get("codeShare") or "").strip()
                                 or str(detail.get("sAirComName")
                                        or "").strip()),
                # 折扣：与所选价同一 ADT breakdown 配对（"6.7折"/"全价"，
                # ADT 有值 64/77），_adt_fare 已过滤 "0" 占位
            }
            # discount 无值不落键（avgDelay 同族键卫生：空串占位曾达
            # 生产现窗 5.7%，消费端 None/空串等价、出勤统计不虚高）
            if fare_disc:
                offer["discount"] = fare_disc
            # 公布运价（与所选价同 breakdown 配对，_adt_fare 内已挡
            # -1/0 占位）：报销/里程累积口径，float 协议无值不落键
            if fare_std:
                offer["stdFare"] = fare_std
            # 童婴价（数值协议与 qunar H5 对齐）：无值不落键
            if child is not None:
                offer["childPrice"] = child
            if infant is not None:
                offer["infantPrice"] = infant
            # layover（detail.duration，卫生改有值才落）：键级
            # 渠道侧消失（两日 dump 0/90；DB 09-10 起 12 天 ~8 万行
            # 0 非空，起即空非本轮回归）——fliggy totalDuration
            # 先例防恒空键堆 extra；渠道若恢复键级在场自动回归
            if detail.get("duration"):
                offer["layover"] = detail.get("duration")
            key = (offer["flight_no"], offer["depart_time"], offer["price"])
            if key not in seen:
                seen.add(key)
                offers.append(offer)
        return offers

    @staticmethod
    def _lowest_offer(offers: List[dict]) -> Optional[dict]:
        priced = [o for o in offers if o.get("price")]
        return min(priced, key=lambda o: o["price"]) if priced else None

    @staticmethod
    def _offers_to_flights(offers: List[dict]) -> List[dict]:
        """统一航班级明细 schema（挂 extra）。flightNos 含多段即中转；
        该端点实测以直飞为主。"""
        out = []
        for o in offers:
            if not o.get("price"):
                continue
            dep_d = (o.get("dep_date") or "")[:10]
            arr_d = (o.get("arr_date") or "")[:10]
            dep_t = _hhmm(o.get("depart_time"))
            arr_t = _hhmm(o.get("arrive_time"))
            if not (dep_d and arr_d and dep_t and arr_t):
                continue
            fnos = (o.get("flight_no") or "").replace("-", ",")
            is_transfer = "," in fnos
            ft = o.get("flight_time")
            dur = ""
            try:
                mins = int(ft)
                dur = f"{mins // 60}时{mins % 60}分"
            except (TypeError, ValueError):
                pass
            # 决策字段（detail 已取到，只多取 4 键）：机型/餐食/准点率/经停点
            row = {
                "price": float(o["price"]),
                "code": fnos.replace(",", "/"),
                "name": f"{o.get('airline') or ''}{fnos.split(',')[0]}",
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                # 「属性不适用即落空串」残留族无值不落键（r241 观测
                # 立案 8 键收口；transCity 中转标记/crossDayDesc 跨天
                # 标识有值照落）
                **({"transCity": "中转"} if is_transfer else {}),
                **(({"crossDayDesc": "+1天"} if dep_d != arr_d else {})),
                "totalDuration": dur,
                "cabin": (o.get("cabin") or "").strip(),
                # 黑卡价透明标记：仅选中价来自黑卡政策时落键（有值才落）
                **({"blackCard": True} if o.get("blackCard") else {}),
                # 公务/商务/头等舱参考价（int 协议与 qunar bizPrice 对齐）
                **({"bizPrice": int(o["bizPrice"])}
                   if o.get("bizPrice") else {}),
                "plane": str(o.get("craftTypeName") or "").split("（")[0]
                          .split("(")[0].strip(),
                "meal": str(o.get("mealName") or "").strip(),
                # 无值不落键（avgDelay/discount 同族律：渠道占位「20%」
                # 与无值经 _prate 置空后，空串键曾达生产 20.2% 常态化）
                **({"prate": _prt}
                   if (_prt := _prate(o.get("onTimeRate"))) else {}),
                # 经停决策字段：stopPoints 实报为 dict 列表（debug dump
                # 实锤 {"airPortCode":"NNY","cityName":"南阳","duration":
                # "50"}），曾按 isinstance(x,str) 过滤全滤空——经停班被
                # 当直飞入库，徽标/经停哪、停多久全丢；三键无值不落
                # （r241 残留族收口，stopCitys/stopTime/stopWin 同源同门）
                **(({"stopCitys": _scp} if (_scp := ";".join(
                    str(x.get("cityName") or x.get("airPortName") or "")
                    for x in (o.get("stopPoints") or [])
                    if isinstance(x, dict)
                    and (x.get("cityName") or x.get("airPortName")))) else {})),
                **(({"stopTime": _stt} if (_stt := _stop_time(
                    o.get("stopPoints"))) else {})),
                # 经停窗口绝对时刻（arrivalTime/departrueTime 对，多段
                # 「/」连接；恒落键与 stopCitys/stopTime 同族形态）
                **(({"stopWin": _sw} if (_sw := _stop_window(
                    o.get("stopPoints"))) else {})),
                # 新决策字段（offer 层已算好，键路径/dump 命中率
                # 见 _parse_offers 注释块）。航站楼随 offer 层同守
                # 无值不落键：offer 缺键时 str(o.get(...)) 恒产空串，
                # 空串键照落=DB 面恒空键（行层与 offer 层各自独立
                # 成立；dTerminal 间歇下发，恒空代际自然零出勤）
                **({"arrTerminal": str(o["arrTerminal"]).strip()}
                   if o.get("arrTerminal") else {}),
                **({"depTerminal": str(o["depTerminal"]).strip()}
                   if o.get("depTerminal") else {}),
                **(({"shareCarrier": _shc}
                    if (_shc := str(o.get("shareCarrier") or "").strip())
                    else {})),
                # 决策字段必须随 offer 透传（教训两次在案）：航司二字码/
                # 公布运价同律，漏带即行级恒空
                "airlineCode": str(o.get("airlineCode") or "").strip(),
                **({"stdFare": float(o["stdFare"])}
                   if o.get("stdFare") else {}),
                # 无值不落键（同 detail 层：空串占位曾达生产 44.2%）
                **({"avgDelay": o["avgDelay"]}
                   if isinstance(o.get("avgDelay"), int) else {}),
                **({"planeAge": o["planeAge"]} if o.get("planeAge") else {}),
                # 无值不落键（detail 层同律：空串占位不落）
                **({"discount": o["discount"]} if o.get("discount") else {}),
                # 五键透传：labels 曾在 offer 层算好但此处漏带
                # ——「决策字段必须随 offer 透传」教训重演（注释
                # 在案），DB 实锤全库 labels 键存在率 0%（宽体机功能
                # 空转根因）；其余为机场名/机型体量/舱位代码新键；
                # labels/planeSize 无值不落键（r241 残留族收口，
                # offer 层同门）
                **(({"labels": _lbo}
                    if (_lbo := str(o.get("labels") or "").strip())
                    else {})),
                **(({"planeSize": _pso}
                    if (_pso := str(o.get("planeSize") or "").strip())
                    else {})),
                "depAirport": str(o.get("depAirport") or "").strip(),
                "arrAirport": str(o.get("arrAirport") or "").strip(),
                # H1 透传（offer 层已守卫；「决策字段必须随
                # offer 透传」教训 / 两次在案）
                "depAirportCode": str(o.get("depAirportCode") or "").strip(),
                "arrAirportCode": str(o.get("arrAirportCode") or "").strip(),
                "cabinCode": str(o.get("cabinCode") or "").strip(),
            }
            # 童婴价透传（offer 层无值时键不存在，数值协议同 qunar）
            if isinstance(o.get("childPrice"), (int, float)):
                row["childPrice"] = o["childPrice"]
            if isinstance(o.get("infantPrice"), (int, float)):
                row["infantPrice"] = o["infantPrice"]
            # layover 透传（卫生同律）：航班级固定键曾对恒空
            # 源每行落 ""（detail.duration 键级消失 12 天 ~8 万行 0 非
            # 空）——有值才落，防恒空键堆 extra；渠道恢复在场自动回归
            if str(o.get("layover") or "").strip().isdigit():
                row["layover"] = int(o["layover"])
            out.append(row)
        return out

    def _dump_raw(self, raw: Optional[dict], tag: str):
        if not self.debug or not raw:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        path = os.path.join(self.debug_dir, tag + ".json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            self.logger.info("[tuniu] 已保存原始响应: %s", path)
        except Exception:
            pass
