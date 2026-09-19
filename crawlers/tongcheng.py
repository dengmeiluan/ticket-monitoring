"""同程旅行机票：m.ly.com H5 + 手机UA + XHR 拦截

同程旅行（17u / ly.com）与智行同源，价格与携程/飞猪存在差异。
H5 入口为 m.ly.com 机票预订页 book1，列表通过 XHR 异步加载。

首跑请保持 debug=true，解析不到价格会把所有捕获的 XHR dump 到
debug/tongcheng_xhr_<date>.txt，据此再精确化字段解析。
"""
import os
import re
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

    # 同程机票真实列表接口（book1/flights）。connection/flights 是中转：
    # v1.5.48 起订阅落 dump，v1.5.49 起一期解析（_extract_transfer_flights
    # 产出中转行）——两报文结构不同，各喂各的解析器
    XHR_KEYS = [
        "flightbffv2/book1/flights",
        "connection/flights",
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
                        url = item.get("url") or ""
                        if "connection/flights" in url:
                            # 中转报文一期解析（v1.5.49）：此前仅落 dump
                            flights.extend(
                                self._extract_transfer_flights(
                                    item.get("text", "")))
                        elif "book1/flights" in url:
                            flights.extend(self._extract_flights(item.get("text", "")))
                    if price is not None and not flights:
                        # 仅头条价无明细：拒落价防污染（对齐 qunar 同款守卫）
                        # ——裸价曾绕过 0.5x 幻觉价守卫直入阈值告警/去抖
                        # 基准；站点改版（fl 键失效）时 lp 仍会给价
                        self.logger.warning(
                            "[tongcheng] %s 头条价 ￥%.0f 无任何明细"
                            "（疑页面结构改版），拒落价", date, price)
                        price = None
                    if price is not None:
                        best = min(flights, key=lambda f: f["price"]) if flights else None
                        # 价格一律取「有票明细最低」：lp 来自日历/中转区时
                        # 曾与明细错配——中转价挂在直飞航班上参与阈值判
                        # 定，用户按推送找到的是另一班（0.5x 守卫只拦得
                        # 住 >2 倍背离）。lp 降级为交叉校验
                        if best:
                            if price < best["price"] * 0.85:
                                self.logger.warning(
                                    "[tongcheng] 头条价 ￥%.0f 低于明细最低 "
                                    "￥%.0f 超 15%%（疑日历/中转成分），以明细为准",
                                    price, best["price"])
                            price = best["price"]
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
        # 下限与 qunar/明细口径统一 300（v1.5.37），防裸价半截行
        prices = [p for p in prices if 300 <= p <= 50000]
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
            # 下限与 qunar/明细口径统一 300（v1.5.37），防裸价半截行
            if 300 <= lpv <= 50000:
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
                        # 下限与 qunar/明细口径统一 300（v1.5.37），防裸价半截行
                        if 300 <= v <= 50000:
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
        2026-10-06 dump 实测键名改版（近 2810/2810 行 cabinlevel=None、
        plane 空串的根因）：顶层 cabinlevel/equipmentName 已消失——
        机型在 afn（"空客A320(中)"，amn+amt 同义拆分），舱位名在所选
        政策 lps[].pts[].td 文本（"6.8折经济舱"）；经停在 $dirStop
        （{"key":"经停","value":"宜昌","time":"45分"}，顶层 sc/sd 同义）。
        新旧键名兼容取值。"""
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
        out = []
        for f in fl:
            if not isinstance(f, dict):
                continue
            fn = (f.get("fn") or "").strip()
            dt, at = (f.get("dt") or ""), (f.get("at") or "")
            if not (fn and len(dt) >= 16 and len(at) >= 16):
                continue
            lps = f.get("lps")
            price = None
            cabin_name = ""
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
                        # 舱位名随价格政策走（pts[].td="6.8折经济舱"），
                        # 换新键名后顶层再无独立舱位字段
                        for pt in policy.get("pts") or []:
                            td = str((pt or {}).get("td") or "")
                            cm = re.search(
                                r"(超级经济舱|经济舱|公务舱|头等舱|商务舱)", td)
                            if cm:
                                cabin_name = cm.group(1)
                                break
            if price is None:
                continue
            # 经停（$dirStop 在场即经停班——此前被当直飞入库）：城市取
            # value（sc 同义兜底），停留取 "45分" 中文形态（顶层 sd 为
            # "45m" 英文形态，normalize 不认，宁缺勿错不取）
            ds = f.get("$dirStop")
            stop_city, stop_time = "", ""
            if isinstance(ds, dict):
                stop_city = str(ds.get("value") or "").strip()
                stop_time = str(ds.get("time") or "").strip()
            if not stop_city:
                stop_city = str(f.get("sc") or "").strip()
            dep_d, arr_d = dt[:10], at[:10]
            cross = "" if dep_d == arr_d else "+1天"
            # sts 标签子向量：tt=1 准点率 / tt=4 餐食（提取即得的决策信息）
            prate, meal = "", ""
            for st in f.get("sts") or []:
                if not isinstance(st, dict):
                    continue
                # v1.5.38 站点改版标签键 tx→td（新报文 td 881 处、tx 0 处，
                # DB 实锤 meal/prate 静默全空数日）——双键兼容取先到非空
                tt = st.get("tt")
                tx = str(st.get("td") or st.get("tx") or "")
                if tt == 1 and not prate:
                    # 100% 曾被 digits[:2] 截成「10」（新航线/短航段常见）：
                    # 取前导 1-3 位整数并限 1-100。新报文文本形如
                    # 「到达准点率97%」（CJK 前缀+百分号后置），须全文
                    # 搜索而非行首锚定
                    m = (re.search(r"(\d{1,3})\s*%", tx)
                         or re.match(r"\s*(\d{1,3})\s*$", tx))
                    if m and 0 < int(m.group(1)) <= 100:
                        prate = m.group(1)
                elif tt == 4 and not meal:
                    meal = tx
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
                # 舱位：政策文本提取优先，旧 dump 的 cabinlevel 数字映射兜底
                "cabin": cabin_name or {1: "经济舱", 2: "公务舱", 3: "头等舱"}.get(
                    f.get("cabinlevel"), ""),
                # 机型：新键 afn（"空客A320(中)"），旧键 equipmentName
                # 兼容。清洗（v1.5.47）：旧键「机型」前缀（机型73M 曾
                # 直入推送决策行）与 _变体后缀（空客A320_186）
                "plane": (re.sub(r"_\d+$", "",
                          (f.get("afn") or f.get("equipmentName") or ""))
                          .removeprefix("机型")
                          .split("（")[0].split("(")[0].strip()),
                "stopCitys": stop_city,
                "stopTime": stop_time,
                "prate": prate,
                "meal": meal,
            })
        # 同班多政策只留最低价，防 TOP 名额被同班占满（v1.5.37）：
        # 旧去重键含 price 时同班多票价政策各行并存
        dedup = {}
        for row in out:
            k = (row["code"], row["depTime"])
            if k not in dedup or row["price"] < dedup[k]["price"]:
                dedup[k] = row
        return list(dedup.values())

    # 中转衔接时长 "2h15m"/"11h"（fps.sd）
    _RE_SD = re.compile(r"^(\d+)h(?:(\d+)m)?$")

    @classmethod
    def _extract_transfer_flights(cls, text: str) -> list:
        """同程 connection/flights 中转明细一期（v1.5.49，宁缺勿错）。

        data.fps[] 结构（10-05 dump 25 行 / 10-06 22 行实证）：
          dt/at=整体起降完整时刻（25/25）、sd=衔接时长 "2h15m"（25/25，
          $sd 同义中文形态）、td=全程 "8h40m"、sc=中转城市（25/25）、
          ss[]=分段明细（fn/dt/at/asn/amn 段段齐全）、lps[]=分渠道报价
          （atp 含税价 25/25 有值，brs 余票口径同 book1）。
        产出中转行（统一 schema）：transCity=sc、整体起降时刻、layover
        用 sd 真值（分钟，非 binfo 式猜衔接）、price=lps 最低含税价、
        code=ss[].fn 以「/」联接、机型取首段 amn、舱位随最低价政策
        （lps[].pts[].td 同 book1 口径）。质量约定与 _extract_flights
        相同：航班号/起降时刻/价格任一缺失整行丢弃。
        transferBaggage：data.doc 是数据级服务图例字典（10-05/10-06 两
        dump 恒定 {"luggageSelf":行李自助直挂,"luggageAgain":重新托运
        行李,"terminal":跨航站楼,...}），行级无绑定信号（luggageSelf
        全文仅 doc 1 处，fps 无引用键）——图例同时含直挂/重新托运时
        单行无法判定，仅图例唯一含 luggageSelf（无 luggageAgain）时置
        "direct"，否则留空（bag_direct 哨兵线上观测兜底）。
        一期不采（置信不足/协议未列）：data.doc 其余标签、stss 增值
        服务、lps[].tags 混淆串、跨航站楼明细、doc.terminal。"""
        if not text:
            return []
        try:
            obj = json.loads(text)
        except Exception:
            return []
        data = obj.get("data")
        if not isinstance(data, dict):
            return []
        fps = data.get("fps")
        if not isinstance(fps, list):
            return []
        doc = data.get("doc") or {}
        direct_only = (bool(doc.get("luggageSelf"))
                       and not doc.get("luggageAgain"))
        out, seen = [], set()
        for fp in fps:
            if not isinstance(fp, dict):
                continue
            segs = [s for s in fp.get("ss") or [] if isinstance(s, dict)]
            fns = [str(s.get("fn") or "").strip() for s in segs]
            fns = [x for x in fns if x]
            # 中转行定义=两段起（单段属异形报文，宁缺勿错不产行）
            if len(fns) < 2:
                continue
            dt, at = str(fp.get("dt") or ""), str(fp.get("at") or "")
            if len(dt) < 16 or len(at) < 16:
                continue
            price = None
            cabin_name = ""
            for policy in fp.get("lps") or []:
                if not (isinstance(policy, dict)
                        and cls._has_ticket(policy.get("brs"))):
                    continue
                try:
                    v = float(policy.get("atp") or 0)
                except (TypeError, ValueError):
                    continue
                if 300 <= v <= 50000 and (price is None or v < price):
                    price = v
                    # 舱位名随价格政策走（pts[].td，同 book1 直飞口径）
                    for pt in policy.get("pts") or []:
                        td_txt = str((pt or {}).get("td") or "")
                        cm = re.search(
                            r"(超级经济舱|经济舱|公务舱|头等舱|商务舱)",
                            td_txt)
                        if cm:
                            cabin_name = cm.group(1)
                            break
            if price is None:
                continue
            # 衔接时长 sd 真值（"2h15m"）→ 分钟 int（normalize 与 ctrip
            # layover 同口径）；解析失败留空不猜
            lay = ""
            msd = cls._RE_SD.match(str(fp.get("sd") or "").strip())
            if msd:
                lay = int(msd.group(1)) * 60 + int(msd.group(2) or 0)
            code = "/".join(fns)
            key = (code, dt[11:16])
            if key in seen:
                continue
            seen.add(key)
            plane = ""
            for s in segs:
                plane = str(s.get("amn") or "")
                if plane:
                    break
            plane = (re.sub(r"_\d+$", "", plane).removeprefix("机型")
                     .split("（")[0].split("(")[0].strip())
            # 跨天按日期差（中转常 +1/+2 天，二元判断会谎报）
            try:
                from datetime import date as _d
                xday = (_d.fromisoformat(at[:10])
                        - _d.fromisoformat(dt[:10])).days
            except Exception:
                xday = 0
            out.append({
                "price": price,
                "code": code,
                "name": f"{segs[0].get('asn') or ''}{fns[0]}",
                "depTime": dt[11:16],
                "arrTime": at[11:16],
                "depDate": dt[:10],
                "arrDate": at[:10],
                "transCity": str(fp.get("sc") or "").strip(),
                "crossDayDesc": "" if xday <= 0 else f"+{xday}天",
                "totalDuration": str(fp.get("td") or "")
                .replace("h", "时").replace("m", "分"),
                "layover": lay if lay else "",
                # 渠道结构化真值标记（v1.5.49）：flightnorm 的 1440 回绕
                # 判伪豁免只认 layoverSrc=transInfo——真值跨天长停留恰会
                # 落入击杀区（qunar 同款协议），缺标记=长停留被静默归零
                "layoverSrc": "transInfo" if lay else "",
                "cabin": cabin_name,
                "plane": plane,
                # 中转行李直挂（图例唯一指向直挂才置，见 docstring）
                "transferBaggage": "direct" if direct_only else "",
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
                    f.write((item.get("text") or "")[:1000000])
                    f.write("\n")
            self.logger.info("[tongcheng] 已保存 XHR: %s", path)
        except Exception:
            pass
