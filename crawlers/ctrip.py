"""携程机票：m.ctrip.com H5 (taro) + 手机UA + XHR 拦截

数据源接口 flightListSearchForH5 返回 JSON。
每个航班(fltitem)的 policyinfo 内含多个销售政策，
每个政策有 tprice(含税价) 与 quantity(余票)。quantity 为 null/0 表示
无票(诱饵价)，必须剔除，否则会拿到买不到的超低价。
"""
import os
import re
import json
import urllib.parse
from typing import List

from core.models import FlightPrice
from .base import BaseCrawler


class CtripCrawler(BaseCrawler):
    name = "ctrip"
    use_mobile = True  # 移动端 H5

    # 携程 H5 机票单程列表（taro 版，用户提供的真实入口）
    URL_TPL = ("https://m.ctrip.com/html5/flight/taro/first?from=inner"
               "&tripType=ONE_WAY"
               "&dcity={from_city}&dcityName={from_name}"
               "&acity={to_city}&acityName={to_name}"
               "&ddate={date}")

    # 仅认航班列表接口；LowestPriceSearch 是跨日期低价日历，会混入其他日期价格
    XHR_KEYS = [
        "flightListSearchForH5",
    ]

    CITY_NAME = {
        "SZX": "深圳", "KMG": "昆明", "PEK": "北京", "BJS": "北京",
        "SHA": "上海", "PVG": "上海", "CAN": "广州", "HGH": "杭州",
        "CTU": "成都", "SIA": "西安", "CKG": "重庆", "NKG": "南京",
        "WUH": "武汉", "CSX": "长沙", "XMN": "厦门", "SYX": "三亚",
        "HAK": "海口", "LJG": "丽江", "DLU": "大理", "JHG": "西双版纳",
        "DIG": "香格里拉", "TCZ": "腾冲", "URC": "乌鲁木齐",
    }

    def login_url(self) -> str:
        return "https://www.ctrip.com/"

    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        results: List[FlightPrice] = []
        with self.browser() as ctx:
            page = self.new_page(ctx)
            # 首页预热：直捣机票页会被风控软拒（列表接口报服务器异常），
            # 先访问 m.ctrip.com 首页让风控 JS 下发 cookie
            try:
                page.goto("https://m.ctrip.com/html5/", wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
            except Exception as e:
                self.logger.warning("[ctrip] 预热失败: %s", e)
            for date in dates:
                url = self.URL_TPL.format(
                    from_city=from_city.upper(),
                    to_city=to_city.upper(),
                    from_name=urllib.parse.quote(self.CITY_NAME.get(from_city.upper(), from_city)),
                    to_name=urllib.parse.quote(self.CITY_NAME.get(to_city.upper(), to_city)),
                    date=date,
                )
                self.logger.info("[ctrip] GET %s", url)
                captured = self.attach_xhr_collector(page, self.XHR_KEYS)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(8000)
                    for _ in range(4):
                        try:
                            page.mouse.wheel(0, 2000)
                        except Exception:
                            pass
                        page.wait_for_timeout(1200)

                    self._dump_xhr(captured, f"ctrip_xhr_{date}")
                    price = self._pick_lowest(captured)
                    flights = []
                    for item in captured:
                        flights.extend(self._extract_ctrip_flights(item.get("text", "")))
                    if price is not None:
                        best = min(flights, key=lambda f: f["price"]) if flights else None
                        results.append(FlightPrice(
                            platform=self.name,
                            from_city=from_city, to_city=to_city,
                            depart_date=date, price=price,
                            flight_no=(best or {}).get("name", ""),
                            depart_time=(best or {}).get("depTime", ""),
                            arrive_time=(best or {}).get("arrTime", ""),
                            extra=json.dumps(flights, ensure_ascii=False) if flights else "",
                        ))
                        n_d = sum(1 for f in flights if not f["transCity"])
                        self.logger.info(
                            "[ctrip] %s 最低价 ￥%.0f（明细 %d 条：直飞 %d / 中转 %d）",
                            date, price, len(flights), n_d, len(flights) - n_d)
                    else:
                        self.logger.warning("[ctrip] %s 未解析到价格", date)
                        self._debug_snapshot(page, f"nopx_{date}")
                except Exception as e:
                    self.logger.exception("[ctrip] %s 抓取异常: %s", date, e)
                self._sleep()
        return results

    def _pick_lowest(self, captured: list) -> float | None:
        prices: list = []
        for item in captured:
            prices.extend(self._extract_ctrip_prices(item.get("text", "")))
        prices = [p for p in prices if 100 <= p <= 50000]
        return float(min(prices)) if prices else None

    @staticmethod
    def _extract_ctrip_flights(text: str) -> list:
        """携程航班明细（统一 schema）。

        fltitem[].mutilstn[] = 航段：basinfo.flgno=航班号、
        dateinfo.ddate/adate=完整起降时刻、aportinfo.city=到达城市；
        多段即中转。价格取 policyinfo[] 中 quantity>0 的最低 tprice。
        响应根有 dict / list 两种形态。
        """
        if not text:
            return []
        try:
            obj = json.loads(text)
        except Exception:
            return []
        if isinstance(obj, list):
            flt = obj
        elif isinstance(obj, dict):
            flt = obj.get("fltitem") or []
        else:
            return []
        out, seen = [], set()
        for item in flt:
            if not isinstance(item, dict):
                continue
            segs = item.get("mutilstn") or []
            segs = [s for s in segs if isinstance(s, dict)]
            if not segs:
                continue
            first, last = segs[0], segs[-1]
            dd = ((first.get("dateinfo") or {}).get("ddate") or "")
            ad = ((last.get("dateinfo") or {}).get("adate") or "")
            if len(dd) < 16 or len(ad) < 16:
                continue
            fnos = []
            for s in segs:
                g = ((s.get("basinfo") or {}).get("flgno") or "").strip()
                if g:
                    fnos.append(g)
            if not fnos:
                continue
            price = None
            for pi in item.get("policyinfo") or []:
                if not isinstance(pi, dict):
                    continue
                try:
                    q = pi.get("quantity")
                    if q is None or int(q) <= 0:
                        continue
                    v = float(pi.get("tprice") or 0)
                except (TypeError, ValueError):
                    continue
                if 300 <= v <= 50000 and (price is None or v < price):
                    price = v
            if price is None:
                continue
            key = ("/".join(fnos), dd[:16], price)
            if key in seen:
                continue
            seen.add(key)
            dur_min = 0
            try:
                from datetime import datetime as _dt
                t0 = _dt.strptime(dd[:19], "%Y-%m-%d %H:%M:%S")
                t1 = _dt.strptime(ad[:19], "%Y-%m-%d %H:%M:%S")
                dur_min = int((t1 - t0).total_seconds() // 60)
            except Exception:
                pass
            lay_min = 0
            try:
                from datetime import datetime as _dt
                for _si in range(len(segs) - 1):
                    _a = _dt.strptime(
                        (segs[_si].get("dateinfo") or {}).get("adate", "")[:19],
                        "%Y-%m-%d %H:%M:%S")
                    _b = _dt.strptime(
                        (segs[_si + 1].get("dateinfo") or {}).get("ddate",
                                                                  "")[:19],
                        "%Y-%m-%d %H:%M:%S")
                    lay_min += max(0, int((_b - _a).total_seconds() // 60))
            except Exception:
                lay_min = 0
            dur = f"{dur_min // 60}时{dur_min % 60}分" if dur_min else ""
            cross = {0: "", 1: "+1天", 2: "+2天"}.get(dur_min // 1440, "+2天")
            code = "/".join(fnos)
            dep_d, arr_d = dd[:10], ad[:10]
            is_transfer = len(segs) > 1
            trans = ""
            if is_transfer:
                tc = ((segs[0].get("aportinfo") or {}).get("city") or "").strip()
                from .qunar import QunarCrawler as _Q
                trans = _Q.CITY_NAME.get(tc, tc) or "中转"
            out.append({
                "price": price,
                "code": code,
                "name": fnos[0],
                "depTime": dd[11:16],
                "arrTime": ad[11:16],
                "depDate": dep_d,
                "arrDate": arr_d,
                "transCity": trans,                "crossDayDesc": cross,
                "totalDuration": dur,
                "layover": lay_min or "",
            })
        return out

    @staticmethod
    def _extract_ctrip_prices(text: str) -> list:
        """解析携程 flightListSearchForH5 JSON，返回所有"有票"政策的含税价。

        逐航班递归遍历 policyinfo，配对 (tprice, quantity)，
        quantity 为 null/0 的政策剔除（无票诱饵价）。
        """
        if not text:
            return []
        try:
            obj = json.loads(text)
        except Exception:
            # 解析失败则退回正则（但仍要求 tprice 与 quantity 在同一对象，尽量配对）
            return CtripCrawler._regex_fallback(text)

        # 兼容两种根结构：旧版 dict（价格在 fltitem 子树），新版顶层直接是 list
        if isinstance(obj, dict):
            root = obj.get("fltitem")
            if not isinstance(root, list):
                return CtripCrawler._regex_fallback(text)
        elif isinstance(obj, list):
            root = obj
        else:
            return CtripCrawler._regex_fallback(text)

        prices: list = []

        def scan(node):
            """递归找 tprice，并取同级 quantity 判断是否有票"""
            if isinstance(node, dict):
                if "tprice" in node:
                    tp = node.get("tprice")
                    qty = node.get("quantity", None)
                    try:
                        tpv = int(float(tp))
                    except Exception:
                        tpv = None
                    has_ticket = qty is not None
                    if has_ticket:
                        try:
                            has_ticket = int(qty) > 0
                        except Exception:
                            has_ticket = True  # 非数字但非 null，视为有票
                    if tpv is not None and has_ticket:
                        prices.append(tpv)
                for v in node.values():
                    scan(v)
            elif isinstance(node, list):
                for v in node:
                    scan(v)

        for f in root:
            scan(f)
        return prices

    @staticmethod
    def _regex_fallback(text: str) -> list:
        """JSON 解析失败时的兜底：仅取 tprice 紧跟 quantity 非 null 的。"""
        prices: list = []
        for m in re.finditer(
            r'"tprice"\s*:\s*(\d+(?:\.\d+)?)\s*,\s*"quantity"\s*:\s*(null|"?\d+"?)',
            text,
        ):
            qty = m.group(2)
            if qty == "null":
                continue
            try:
                if int(qty.strip('"')) <= 0:
                    continue
            except Exception:
                pass
            prices.append(int(float(m.group(1))))
        return prices

    def _dump_xhr(self, captured: list, tag: str):
        if not self.debug or not captured:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        path = os.path.join(self.debug_dir, tag + ".txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                for i, item in enumerate(captured):
                    f.write(f"\n----- [{i}] {item['url']} -----\n")
                    f.write((item.get("text") or "")[:200000])
                    f.write("\n")
            self.logger.info("[ctrip] 已保存 XHR: %s", path)
        except Exception:
            pass
