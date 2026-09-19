"""途牛机票：纯 httpx 直连 (逆向 tac.js cookie, 不依赖浏览器)。

途牛国内机票真实价格通过接口 flight-api.tuniu.com/wzt/flight/v1/listFlight 异步轮询返回
(fareList), 带有 mtoken + tac.js 追踪/指纹 cookie 的风控 (缺失即 179991)。

逆向结论 (经验证):
  179991 的本质是缺少途牛自有的追踪 cookie (由 CDN 上的 tac.js 在前端生成)。
  补齐以下 cookie 后, httpx 可直接调 listFlight 拿到 fareList:

    udid    : GET https://h5api.tuniu.com/auth/getDeviceId?d={"type":1}&c={"ct":30}
    _taca   : "{loginTime}.{loginTime}.{loginTime}.1"  (loginTime = 毫秒时间戳)
    _tacb   : base64(newGuid())
    _tacc   : "1"
    _tact   : base64(newGuid())
    _tacau  : base64("0," + newGuid() + ",")
    _tacz2  : base64("0," + newGuid() + ",,")

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

from core.models import FlightPrice
from .base import BaseCrawler

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

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

FLIGHT_HOME = "https://m.tuniu.com/flight"
LIST_API = "https://flight-api.tuniu.com/wzt/flight/v1/listFlight"
DEVICE_ID_API = "https://h5api.tuniu.com/auth/getDeviceId"
COOKIE_DOMAIN = ".tuniu.com"


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
    def _looks_like_real_price(cls, body: str) -> bool:
        if not body or '"success":true' not in body:
            return False
        if '"fareList"' not in body and '"salePrice"' not in body:
            return False
        try:
            obj = json.loads(body)
        except Exception:
            return False
        data = obj.get("data") or {}
        return bool(data.get("fareList")) or cls._has_price(data)

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
            for poll in range(self.max_poll):
                d = dict(d_tmpl)
                d["pollTag"] = poll
                r = client.get(LIST_API, params={"d": json.dumps(d, ensure_ascii=False)}, headers=api_hdrs)
                last = r.text
                if self._looks_like_real_price(last):
                    return True, json.loads(last), blocked
                if "179991" in last:
                    blocked = True
                time.sleep(1.5)
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
                n_d = sum(1 for f in flights if not f["transCity"])
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
        # 价格带 300–50000 与其余四渠道对齐（v1.5.47 补下限：单渠道
        # 零下限曾让改版键义漂移出的小数/异常值直入渠道最低价对比）
        try:
            f = float(v)
            return f if 300 <= f <= 50000 else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _adt_fare(cls, price_list: list) -> tuple:
        """ADT 价与同 breakdown 折扣配对返回 (price, discount)。

        价格=各 flightPriceList 中 psgType=ADT 的最低 baseFare；折扣必须
        与所选价取自同一 fareBreakdownList（跨政策取折扣即错配）。
        discount 值形如 "6.7折"/"全价"（dump 实证），"0"/空=未报价占位
        （ADT 也有 13/77 行）不作为折扣值。无 ADT 价返回 (None, "")。"""
        best = None
        disc = ""
        for pr in price_list or []:
            for fb in pr.get("fareBreakdownList", []) or []:
                if fb.get("psgType") != "ADT":
                    continue
                p = cls._to_price(fb.get("baseFare"))
                if p and (best is None or p < best):
                    best = p
                    d = str(fb.get("discount") or "").strip()
                    disc = d if d not in ("", "0") else ""
        return (best, disc)

    @classmethod
    def _child_infant_fares(cls, price_list: list) -> tuple:
        """(child, infant) 最低 baseFare（psgType=CHD/INF，10-05 dump
        164 处实证）。与 qunar H5 childPrice/infantPrice 数值协议对齐
        （跨渠道口径统一）：无值返回 (None, None) 由调用方不落键。
        勿走 _to_price：其 300 下限是成人票价纪律，真实婴儿价常低于
        300 会被整段杀掉（宽域 50–50000 专用）。"""
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

    @classmethod
    def _fare_cabin(cls, fare: dict) -> str:
        """fare 层舱位名：改版后 detail.cabinTypeName 恒缺（100% 空），
        09-18 实报真键挂顶层 priceJourneyCabinList；10-06 实报再度改版
        ——顶层键消失，嵌套进 flightPriceList[].priceJourneyCabinList[]
        .priceFlightCabinList[].cabinTypeName（顶层读取 0/11479 行全空、
        舱位字段死了正是因此无人报警）。新嵌套层优先，旧顶层形态作
        兼容回退。宁缺勿错：无有效值返回空。"""
        for fp in fare.get("flightPriceList") or []:
            if isinstance(fp, dict):
                c = cls._cabin_from_pj(fp.get("priceJourneyCabinList"))
                if c:
                    return c
        return cls._cabin_from_pj(fare.get("priceJourneyCabinList"))

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
            price, fare_disc = cls._adt_fare(fare.get("flightPriceList"))
            child, infant = cls._child_infant_fares(
                fare.get("flightPriceList"))
            offer = {
                "airline": detail.get("airlineCompany"),
                "flight_no": flight_nos_str,
                "depart_time": detail.get("departureTime"),
                "arrive_time": detail.get("arrivalTime"),
                "price": price,
                "dep_date": detail.get("departureDate"),
                "arr_date": detail.get("arrivalDate"),
                "flight_time": detail.get("flightTime"),
                # 舱位在 fare 层（09 月改版后 detail.cabinTypeName 恒缺，
                # DB 实锤 100% 空；实报
                # priceJourneyCabinList[].priceFlightCabinList[].cabinTypeName）
                "cabin": (detail.get("cabinTypeName")
                          or cls._fare_cabin(fare) or ""),
                "layover": detail.get("duration"),
                # 决策四件套必须随 offer 透传：_offers_to_flights 从 offer
                # 读这些键，此前漏带导致机型/餐食/准点率/经停恒空（假解析）
                "craftTypeName": detail.get("craftTypeName") or "",
                "mealName": detail.get("mealName") or "",
                "onTimeRate": detail.get("onTimeRate") or "",
                "stopPoints": detail.get("stopPoints") or [],
                # ---- v1.5.49 决策字段补采（10-05 dump 46 航班实证，
                # flightList 值层，_find_flight_detail 已取到 detail）----
                # 航站楼：aTerminal 46/46（T1/T2），dTerminal 0/46（出发
                # 地单航站楼渠道下发空串）——留空不造
                "depTerminal": str(detail.get("dTerminal") or "").strip(),
                "arrTerminal": str(detail.get("aTerminal") or "").strip(),
                # 共享实际承运航班号：codeShare 实测即执飞航班号字符串
                # （"CZ6981"/"MU5700"，24/46；非布尔），与 v1.5.48
                # shareCarrier「实际承运航班号」语义一致直接落
                "shareCarrier": str(detail.get("codeShare") or "").strip(),
                # 历史平均延误（分钟）：字符串形态 "29"/""（键在场 46/46、
                # 可转数字 28/46），仅数字转 int，非数字留空
                "avgDelay": (int(str(detail["avgDelayTime"]).strip())
                             if str(detail.get("avgDelayTime") or "")
                             .strip().isdigit() else ""),
                # 机龄原始串（"6.3"，28/46），协议要求保留原始形态不转数值
                "planeAge": str(detail.get("flightYear") or "").strip(),
                # 折扣：与所选价同一 ADT breakdown 配对（"6.7折"/"全价"，
                # ADT 有值 64/77），_adt_fare 已过滤 "0" 占位
                "discount": fare_disc,
            }
            # 童婴价（v1.5.50，数值协议与 qunar H5 对齐）：无值不落键
            if child is not None:
                offer["childPrice"] = child
            if infant is not None:
                offer["infantPrice"] = infant
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
                "transCity": "中转" if is_transfer else "",
                "crossDayDesc": "" if dep_d == arr_d else "+1天",
                "totalDuration": dur,
                "cabin": (o.get("cabin") or "").strip(),
                "layover": (int(o["layover"])
                            if str(o.get("layover") or "").strip().isdigit()
                            else ""),
                "plane": str(o.get("craftTypeName") or "").split("（")[0]
                          .split("(")[0].strip(),
                "meal": str(o.get("mealName") or "").strip(),
                "prate": str(o.get("onTimeRate") or "").strip().rstrip("%"),
                # 经停决策字段：stopPoints 实报为 dict 列表（debug dump
                # 实锤 {"airPortCode":"NNY","cityName":"南阳","duration":
                # "50"}），曾按 isinstance(x,str) 过滤全滤空——经停班被
                # 当直飞入库，徽标/经停哪、停多久全丢
                "stopCitys": ";".join(
                    str(x.get("cityName") or x.get("airPortName") or "")
                    for x in (o.get("stopPoints") or [])
                    if isinstance(x, dict)
                    and (x.get("cityName") or x.get("airPortName"))),
                "stopTime": _stop_time(o.get("stopPoints")),
                # v1.5.49 新决策字段（offer 层已算好，键路径/dump 命中率
                # 见 _parse_offers 注释块）
                "depTerminal": str(o.get("depTerminal") or "").strip(),
                "arrTerminal": str(o.get("arrTerminal") or "").strip(),
                "shareCarrier": str(o.get("shareCarrier") or "").strip(),
                "avgDelay": (o.get("avgDelay")
                             if isinstance(o.get("avgDelay"), int) else ""),
                "planeAge": str(o.get("planeAge") or "").strip(),
                "discount": str(o.get("discount") or "").strip(),
            }
            # 童婴价透传（offer 层无值时键不存在，数值协议同 qunar）
            if isinstance(o.get("childPrice"), (int, float)):
                row["childPrice"] = o["childPrice"]
            if isinstance(o.get("infantPrice"), (int, float)):
                row["infantPrice"] = o["infantPrice"]
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
