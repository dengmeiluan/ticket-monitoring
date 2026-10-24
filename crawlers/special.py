# -*- coding: utf-8 -*-
"""特价机票监控 发现层网络面（r319）：纯 httpx 双源，零浏览器零会话。

- 源1 途牛 queryCheapTickets：GET + callback 参数，响应 JSONP 壳需剥；
  接口层零风控免登录（与现役 listFlight 的 179991 风控是两套策略，
  互不相干）；出发地=出口 IP 推断不可指定（调研实证）。
- 源2 携程 15380 低价日历：POST JSON 极简 payload，无 cookie 无指纹头
  直连 200（「页面同源 XHR 未设防」现状非契约，随时可能纳入风控——
  失败一律返回 None 由编排面静默降级，绝不影响主监控）。

trust_env 恒 False（Soldier P2#3）：系统代理环境变量一律不吃（境外
出口会静默改途牛榜单城市→出发地闸全挡、携程日历风控升档，LESSONS
代理坑同族）；出口只由显式 proxy 形参控制（crawler.proxy 配置）。
失败不重试（发现层有轮次节流，下轮自然重试），超时短平快。"""
import json
import logging
from typing import Optional

import httpx

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0.0.0 Safari/537.36")

_TUNIU_URL = "https://flight-api.tuniu.com/query/queryCheapTickets"
_CTRIP_URL = ("https://m.ctrip.com/restapi/soa2/15380/bjjson/"
              "FlightIntlAndInlandLowestPriceSearch")
# 主题榜（r319d）：swift 机票频道首页「国内低价榜」价格填充接口——
# 出发地可控（dcs.code 双槽换出发地即换榜，SHA 变体实测），目的地=
# 渠道运营策展组（bd_* 语义未逆向），每条带官方 H5 深链
_CTRIP_BD_URL = "https://m.ctrip.com/restapi/soa2/19728/fuzzySearch"
# 飞猪 PC 特价航班榜（r319e）：普通 GET JSONP，免 cookie 免签名——
# H5 rx-home 的 mtop 签名闸在 PC 面完全绕开（agent E 实证）；出发地
# 用城市码（BJS 非 PEK），18 条/请求价格升序
_FLIGGY_BD_URL = "https://r.fliggy.com/rule/domestic"
# 飞猪单航线低价日历（r325 国际实证，国内同源）：零 cookie JSONP，
# 一次请求返回 leaveDate 起的连续日价；Referer 缺失会被 WAF 拒
_FLIGGY_CAL_URL = "https://r.fliggy.com/cheapestCalendar/pc"
# 同程 H5 低价日历（r368 实证：POST JSON 无登录/无签名/无验证码；
# 国际窗口 90 天、国内 180 天；channel=4 国内外通用，10060 国际无数据）
_TC_CAL_URL = ("https://wx.17u.cn/cheapflights/bffapi/cheapflightapi/"
               "lowestprice/queryCalendarLowestPrice")

_TUNIU_CAL_URL = "https://flight-api.tuniu.com/query/flight/v1/calendar"


def fetch_tuniu_calendar(from_code: str, to_code: str, departure_date: str,
                         logger: logging.Logger, timeout: float = 15.0,
                         proxy: str = "") -> Optional[list]:
    """途牛国内单航线低价日历（官方 H5 同源接口，零登录/零签名）。

    type=1 单程；机场码须先归并为城市码；国际航线该接口无日历。
    返回逐日 [{date,price}]（裸价，不含税）；渠道明确无日历返回 []。
    """
    from core.intl import airport_city_code, is_intl_route
    if is_intl_route(from_code, to_code):
        return []
    fc = airport_city_code(from_code)
    tc = airport_city_code(to_code)
    payload = {
        "orgCityIataCode": fc, "dstCityIataCode": tc,
        "departureDate": departure_date, "backDate": "",
        "type": "1", "serverMonth": 12,
    }
    try:
        with httpx.Client(
                headers={"User-Agent": _UA,
                         "Accept": "application/json, text/javascript, */*; q=0.01",
                         "Referer": "https://m.tuniu.com/"},
                timeout=timeout, trust_env=False,
                proxy=proxy or None) as c:
            r = c.get(_TUNIU_CAL_URL, params={
                "d": json.dumps(payload, separators=(",", ":"))})
            if r.status_code != 200:
                logger.warning("[特价·tuniu] 日历 %s→%s HTTP %s",
                               fc, tc, r.status_code)
                return None
            obj = r.json()
            if not isinstance(obj, dict):
                return None
            if not obj.get("success"):
                if "暂无价格日历" in str(obj.get("msg") or ""):
                    return []
                logger.warning("[特价·tuniu] 日历 %s→%s msg=%s",
                               fc, tc, obj.get("msg"))
                return None
            rows = obj.get("data")
            return rows if isinstance(rows, list) else []
    except Exception as e:
        logger.warning("[特价·tuniu] 日历 %s→%s 抓取失败: %s", fc, tc, e)
        return None



def _strip_jsonp(text: str) -> Optional[dict]:
    """'cb({...})' / 'jQuery...({...})' → dict；裸 JSON 亦兼容。"""
    s = (text or "").strip()
    if not s:
        return None
    if not s.startswith("{"):
        l, r = s.find("("), s.rfind(")")
        if l < 0 or r <= l:
            return None
        s = s[l + 1:r]
    try:
        obj = json.loads(s)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def fetch_tuniu_board(logger: logging.Logger, timeout: float = 15.0,
                      proxy: str = "") -> Optional[dict]:
    """途牛特价榜单（全量，出发地跟随出口 IP）。失败返回 None。

    proxy：可选本地代理（如 http://127.0.0.1:7897，Clash 出口 IP
    即榜单城市——想换城市看榜换出口即可；空=直连）。"""
    try:
        with httpx.Client(
                headers={"User-Agent": _UA,
                         "Referer": "http://flight.tuniu.com/"},
                timeout=timeout,
                trust_env=False,
                proxy=proxy or None,
                follow_redirects=True) as c:
            r = c.get(_TUNIU_URL, params={"callback": "cb"})
            if r.status_code != 200:
                logger.warning("[特价·tuniu] 榜单 HTTP %s", r.status_code)
                return None
            obj = _strip_jsonp(r.text)
            if not obj or not obj.get("success"):
                logger.warning("[特价·tuniu] 榜单响应异常（success 假/非 JSON）")
                return None
            return obj
    except Exception as e:
        logger.warning("[特价·tuniu] 榜单抓取失败: %s", e)
        return None


def fetch_ctrip_calendar(from_code: str, to_code: str, start_date: str,
                         logger: logging.Logger, timeout: float = 15.0,
                         proxy: str = "") -> Optional[dict]:
    """携程低价日历（单航线跨日期，startDate 起整年）。失败返回 None。

    payload 为调研实测最小可用集（calendarSelections/grade 语义未证，
    照抄页面原值）。proxy 语义同 fetch_tuniu_board。"""
    payload = {
        "searchType": 1,
        "departNewCityCode": from_code,
        "arriveNewCityCode": to_code,
        "passengerList": [{"passengerCount": 1, "passengerType": "Adult"}],
        "grade": 1,
        "calendarSelections": [{"selectionType": 8,
                                "selectionContent": ["1"]}],
        "startDate": start_date,
        "flag": 0,
        "channelName": "MobileH5",
        "lowPriceExtendInfo": [],
    }
    try:
        with httpx.Client(
                headers={"User-Agent": _UA,
                         "Content-Type": "application/json",
                         "Referer": "https://m.ctrip.com/"},
                timeout=timeout,
                trust_env=False,
                proxy=proxy or None) as c:
            r = c.post(_CTRIP_URL, json=payload)
            if r.status_code != 200:
                logger.warning("[特价·ctrip] 日历 %s→%s HTTP %s（疑纳入"
                               "风控，观察哨语义）", from_code, to_code,
                               r.status_code)
                return None
            obj = r.json()
            ack = ((obj or {}).get("responseStatus") or {}).get("Ack", "")
            if ack and ack != "Success":
                logger.warning("[特价·ctrip] 日历 %s→%s Ack=%s",
                               from_code, to_code, ack)
                return None
            return obj
    except Exception as e:
        logger.warning("[特价·ctrip] 日历 %s→%s 抓取失败: %s",
                       from_code, to_code, e)
        return None


def fetch_ctrip_board(from_code: str, from_name: str, start_date: str,
                      end_date: str, logger: logging.Logger,
                      timeout: float = 15.0,
                      proxy: str = "") -> Optional[dict]:
    """携程 19728 特价搜索榜（出发地→全中国多目的地低价，每条带
    官方深链）。失败返回 None。

    payload=PC 特价机票页变体（r319f 实证，agent E）：source=
    online_special_search + acs DOMESTIC_ALL——223 路线/446 价格点/
    31 连续日（vs themeboard 策展组 5 条，~89 倍覆盖），schema 与
    themeboard 完全同构（解析层复用）；出发地 dcs[0].code 可控
    （BJS/SHA 实证）；响应 ~870KB/请求。深链字段 PC 变体是 app
    scheme（ctrip://），解析层 http 门自动回退构造链。trust_env 恒
    False，proxy 语义同 fetch_tuniu_board。"""
    payload = {"tt": 1, "source": "online_special_search", "st": 18,
               "segments": [{"dcs": [{"ct": 1, "code": from_code,
                                      "name": from_name}],
                             "acs": [{"ct": 3, "code": "DOMESTIC_ALL",
                                      "name": "全中国"}],
                             "dow": [], "sr": None,
                             "drl": [{"begin": start_date,
                                      "end": end_date}],
                             "ddate": None}]}
    try:
        with httpx.Client(
                headers={"User-Agent": _UA,
                         "Content-Type": "application/json",
                         "Referer": "https://m.ctrip.com/"},
                timeout=timeout, trust_env=False,
                proxy=proxy or None) as c:
            r = c.post(_CTRIP_BD_URL, json=payload)
            if r.status_code != 200:
                logger.warning("[特价·ctripbd] 主题榜 HTTP %s", r.status_code)
                return None
            return r.json()
    except Exception as e:
        logger.warning("[特价·ctripbd] 主题榜抓取失败: %s", e)
        return None


def fetch_fliggy_calendar(from_code: str, to_code: str, leave_date: str,
                          logger: logging.Logger, timeout: float = 20.0,
                          proxy: str = "") -> Optional[list]:
    """飞猪单航线低价日历（国内/国际同源，含税价）。失败返回 None，
    无报价返回 []。城市码用 IATA 城市码（机场码先归并）。"""
    from core.intl import airport_city_code
    fc = airport_city_code(from_code)
    tc = airport_city_code(to_code)
    try:
        with httpx.Client(
                headers={"User-Agent": _UA,
                         "Referer": "https://sijipiao.fliggy.com/ie/"
                                    "flight_search_result.htm"},
                timeout=timeout, trust_env=False,
                proxy=proxy or None, follow_redirects=True) as c:
            r = c.get(_FLIGGY_CAL_URL, params={
                "bizType": 1, "depCityCode": fc, "arrCityCode": tc,
                "leaveDate": leave_date, "calendarType": 0,
                "tripType": 0, "callback": "cb"})
            if r.status_code != 200:
                logger.warning("[特价·fliggy] 日历 %s→%s HTTP %s",
                               fc, tc, r.status_code)
                return None
            obj = _strip_jsonp(r.text)
            if not isinstance(obj, dict) or not isinstance(
                    obj.get("result"), list):
                logger.warning("[特价·fliggy] 日历拒绝/空体 len=%d",
                               len(r.text or ""))
                return None
            return obj["result"]
    except Exception as e:
        logger.warning("[特价·fliggy] 日历 %s→%s 抓取失败: %s", fc, tc, e)
        return None


def fetch_tongcheng_calendar(from_code: str, from_name: str, to_code: str,
                             to_name: str, anchor_date: str,
                             logger: logging.Logger, timeout: float = 20.0,
                             proxy: str = "") -> Optional[list]:
    """同程单航线低价日历（一次返回 90/180 天窗口）。失败 None；
    渠道明确「无数据」返回 []。anchor_date 不可为今天（code 5）。"""
    from core.intl import is_intl_city
    oint = 1 if is_intl_city(from_code) else 0
    dint = 1 if is_intl_city(to_code) else 0
    payload = {
        "dateInfo": {"dateType": 0, "start": anchor_date, "end": anchor_date},
        "originList": [{"code": from_code, "name": from_name,
                        "type": oint, "nameType": str(oint)}],
        "destList": [{"code": to_code, "name": to_name,
                      "type": dint, "nameType": str(dint)}],
        "channel": 4,
    }
    try:
        with httpx.Client(
                headers={"User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS "
                                        "17_0 like Mac OS X) AppleWebKit/605.1.15"
                                        " (KHTML, like Gecko) Version/17.0 "
                                        "Mobile/15E148 Safari/604.1"),
                         "Content-Type": "application/json"},
                timeout=timeout, trust_env=False,
                proxy=proxy or None, follow_redirects=True) as c:
            r = c.post(_TC_CAL_URL, json=payload)
            if r.status_code != 200:
                logger.warning("[特价·tongcheng] 日历 %s→%s HTTP %s",
                               from_code, to_code, r.status_code)
                return None
            obj = r.json()
            if not isinstance(obj, dict):
                return None
            if not obj.get("success"):
                # code 5 = 渠道无数据（非法航线/超出窗口），不是网络失败
                if obj.get("code") == 5:
                    return []
                logger.warning("[特价·tongcheng] 日历 %s→%s code=%s",
                               from_code, to_code, obj.get("code"))
                return None
            data = obj.get("data") or {}
            table = data.get("flightCalendarPriceMap") or {}
            key = "%s-%s" % (from_code, to_code)
            rows = table.get(key)
            if rows is None and table:
                rows = next(iter(table.values()))
            return rows if isinstance(rows, list) else []
    except Exception as e:
        logger.warning("[特价·tongcheng] 日历 %s→%s 抓取失败: %s",
                       from_code, to_code, e)
        return None


def fetch_fliggy_board(from_code: str, start_date: str, end_date: str,
                       logger: logging.Logger, timeout: float = 15.0,
                       proxy: str = "") -> Optional[dict]:
    """飞猪 PC 特价航班榜（出发城市→多目的地低价，18 条/请求价格
    升序）。失败返回 None。

    普通 GET JSONP 免 cookie 免签名（r319f 实证：H5 mtop 签名闸只在
    rx-home，PC 面完全绕开）；routes 用城市码（BJS 非 PEK，机场码
    0 条实测）；startDate/endDate 窗实证 3/7 天形态。trust_env 恒
    False，proxy 语义同 fetch_tuniu_board。"""
    try:
        with httpx.Client(
                headers={"User-Agent": _UA,
                         "Referer": "https://www.fliggy.com/jipiao/"},
                timeout=timeout, trust_env=False,
                proxy=proxy or None) as c:
            r = c.get(_FLIGGY_BD_URL, params={
                "routes": f"{from_code}-",
                "startDate": start_date, "endDate": end_date,
                "callback": "cb"})
            if r.status_code != 200:
                logger.warning("[特价·fliggy] 榜单 HTTP %s", r.status_code)
                return None
            obj = _strip_jsonp(r.text)
            if not obj or obj.get("status") != 200:
                logger.warning("[特价·fliggy] 榜单响应异常（status 非 200）")
                return None
            return obj
    except Exception as e:
        logger.warning("[特价·fliggy] 榜单抓取失败: %s", e)
        return None
