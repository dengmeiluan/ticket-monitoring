"""同程旅行机票：m.ly.com H5 + 手机UA + XHR 拦截

同程旅行（17u / ly.com）与智行同源，价格与携程/飞猪存在差异。
H5 入口为 m.ly.com 机票预订页 book1，列表通过 XHR 异步加载。

首跑请保持 debug=true，解析不到价格会把所有捕获的 XHR dump 到
debug/tongcheng_xhr_<date>.txt，据此再精确化字段解析。
"""
import os
import json
import urllib.parse
from typing import List

from core.models import FlightPrice
from .base import BaseCrawler


class TongchengCrawler(BaseCrawler):
    name = "tongcheng"
    use_mobile = True

    # 同程旅行 H5 机票单程预订页（用户提供的真实入口）
    URL_TPL = (
        "https://m.ly.com/ft/touch/book1"
        "?date={date}&childticket=0,0&an=1&cn=0&baby=0"
        "&fromCity={from_name}&toCity={to_name}"
        "&fromcitycode={from_city}&fromCode={from_city}"
        "&tocitycode={to_city}&toCode={to_city}"
        "&acn={to_name}&dcn={from_name}"
        "&refId=&cabin=0&platcode=518&direct=0&thirdMemberId="
        "&fPassType=&nametype=0,0&frompage=HOME&outrefid="
    )

    # 同程机票真实列表接口（book1/flights）。connection/flights 是中转，单列即可
    XHR_KEYS = [
        "flightbffv2/book1/flights",
    ]

    CITY_NAME = {
        "SZX": "深圳", "KMG": "昆明", "PEK": "北京", "BJS": "北京",
        "SHA": "上海", "PVG": "上海", "CAN": "广州", "HGH": "杭州",
        "CTU": "成都", "SIA": "西安", "CKG": "重庆", "NKG": "南京",
        "WUH": "武汉", "CSX": "长沙", "XMN": "厦门", "SYX": "三亚",
        "HAK": "海口", "LJG": "丽江", "DLU": "大理", "JHG": "西双版纳",
        "DIG": "香格里拉", "TCZ": "腾冲", "URC": "乌鲁木齐",
    }
    # 向导城市超集（三字码 -> 中文名），与 wizard.CITY 保持一致
    CITY_NAME.update({
        "TAO": "青岛", "TSN": "天津", "CGO": "郑州", "TNA": "济南",
        "FOC": "福州", "WNZ": "温州", "NGB": "宁波", "HFE": "合肥",
        "KWE": "贵阳", "NNG": "南宁", "KWL": "桂林", "LHW": "兰州",
        "XNN": "西宁", "INC": "银川", "HET": "呼和浩特", "TYN": "太原",
        "SJW": "石家庄", "HRB": "哈尔滨", "CGQ": "长春", "SHE": "沈阳",
        "DLC": "大连", "ZUH": "珠海", "SWA": "汕头", "JJN": "泉州",
        "WUX": "无锡", "YNT": "烟台", "WEH": "威海", "DNH": "敦煌",
        "DYG": "张家界",
    })

    def login_url(self) -> str:
        return "https://www.ly.com/"

    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        results: List[FlightPrice] = []
        with self.browser() as ctx:
            page = self.new_page(ctx)
            for date in dates:
                fc, tc = from_city.upper(), to_city.upper()
                url = self.URL_TPL.format(
                    from_city=fc,
                    to_city=tc,
                    from_name=urllib.parse.quote(self.CITY_NAME.get(fc, from_city)),
                    to_name=urllib.parse.quote(self.CITY_NAME.get(tc, to_city)),
                    date=date,
                )
                self.logger.info("[tongcheng] GET %s", url)
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

                    price = self._pick_lowest(captured, page)
                    self._dump_xhr(captured, f"tongcheng_xhr_{date}")
                    flights = []
                    for item in captured:
                        flights.extend(self._extract_flights(item.get("text", "")))
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
                            "[tongcheng] %s 最低价 ￥%.0f（明细 %d 条：直飞 %d / 中转 %d）",
                            date, price, len(flights), n_d, len(flights) - n_d)
                    else:
                        self.logger.warning("[tongcheng] %s 未解析到价格", date)
                        self._debug_snapshot(page, f"nopx_{date}")
                except Exception as e:
                    self.logger.exception("[tongcheng] %s 抓取异常: %s", date, e)
                self._sleep()
        return results

    def _pick_lowest(self, captured: list, page) -> float | None:
        prices: list = []
        for item in captured:
            prices.extend(self._extract_prices(item.get("text", "")))
        prices = [p for p in prices if 100 <= p <= 50000]
        if prices:
            return float(min(prices))
        return None

    @staticmethod
    def _extract_prices(text: str) -> list:
        """解析同程 book1/flights 接口 JSON。

        权威最低价为 data.lp（当前查询日期最低价）。
        同时遍历 data.fl[] 取每个航班的 atp（含税总价）做交叉校验，
        但只采纳"有票"航班：lps[].brs[].al（余票数）> 0。
        注意：data.pc[] 是价格日历，含其它日期价格，必须排除。
        """
        if not text:
            return []
        try:
            obj = json.loads(text)
        except Exception:
            return []

        data = obj.get("data")
        if not isinstance(data, dict):
            return []

        prices: list = []

        # 1) 权威字段：当前查询日期最低价
        lp = data.get("lp")
        try:
            lpv = int(float(lp))
            if 100 <= lpv <= 50000:
                prices.append(lpv)
        except Exception:
            pass

        # 2) 航班列表交叉校验：仅取有余票航班的最低价
        fl = data.get("fl")
        if isinstance(fl, list):
            for flt in fl:
                if not isinstance(flt, dict):
                    continue
                lps = flt.get("lps")
                if not isinstance(lps, list):
                    continue
                for policy in lps:
                    if not isinstance(policy, dict):
                        continue
                    atp = policy.get("atp")
                    has_ticket = TongchengCrawler._has_ticket(policy.get("brs"))
                    if not has_ticket:
                        continue
                    try:
                        v = int(float(atp))
                        if 100 <= v <= 50000:
                            prices.append(v)
                    except Exception:
                        pass

        return prices

    @staticmethod
    def _has_ticket(brs) -> bool:
        """brs[].al 为余票数，-1 表示充足，>0 表示有票，0 表示无票。"""
        if not isinstance(brs, list) or not brs:
            return True  # 无余票信息时不误杀
        for b in brs:
            if isinstance(b, dict):
                al = b.get("al")
                try:
                    if al is None or int(al) != 0:
                        return True
                except Exception:
                    return True
        return False

    @classmethod
    def _extract_flights(cls, text: str) -> list:
        """同程 book1/flights 航班明细（统一 schema，挂 extra）。

        data.fl[]：fn=航班号 asn=航司 dt/at=完整起降时刻 td=全程
        atp=含税总价（lps[] 多政策取有票最低）；中转在 tfs 分区，v1 不做。
        """
        if not text:
            return []
        try:
            obj = json.loads(text)
        except Exception:
            return []
        data = obj.get("data")
        if not isinstance(data, dict):
            return []
        fl = data.get("fl")
        if not isinstance(fl, list):
            return []
        out, seen = [], set()
        for f in fl:
            if not isinstance(f, dict):
                continue
            fn = (f.get("fn") or "").strip()
            dt, at = (f.get("dt") or ""), (f.get("at") or "")
            if not (fn and len(dt) >= 16 and len(at) >= 16):
                continue
            lps = f.get("lps")
            price = None
            if isinstance(lps, list):
                for policy in lps:
                    if not (isinstance(policy, dict) and cls._has_ticket(policy.get("brs"))):
                        continue
                    try:
                        v = float(policy.get("atp") or 0)
                    except (TypeError, ValueError):
                        continue
                    if 300 <= v <= 50000 and (price is None or v < price):
                        price = v
            if price is None:
                continue
            key = (fn, dt, price)
            if key in seen:
                continue
            seen.add(key)
            dep_d, arr_d = dt[:10], at[:10]
            cross = "" if dep_d == arr_d else "+1天"
            out.append({
                "price": price,
                "code": fn,
                "name": f"{f.get('asn') or ''}{fn}",
                "depTime": dt[11:16],
                "arrTime": at[11:16],
                "depDate": dep_d,
                "arrDate": arr_d,
                "transCity": "",
                "crossDayDesc": cross,
                "totalDuration": (f.get("td") or "").replace("h", "时").replace("m", "分"),
                "cabin": {1: "经济舱", 2: "公务舱", 3: "头等舱"}.get(
                    f.get("cabinlevel"), ""),
                "plane": (f.get("equipmentName") or "").split("（")[0]
                          .split("(")[0].strip(),
            })
        return out

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
            self.logger.info("[tongcheng] 已保存 XHR: %s", path)
        except Exception:
            pass
