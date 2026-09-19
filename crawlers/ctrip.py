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
                    if price is not None and not flights:
                        # 仅头条价无明细：拒落价防污染（对齐 qunar/tongcheng
                        # 同款守卫）——裸价曾绕过 0.5x 幻觉价守卫直入阈值
                        # 告警/去抖基准；站点改版时 headline 仍会给价
                        self.logger.warning(
                            "[ctrip] %s 头条价 ￥%.0f 无任何明细"
                            "（疑页面结构改版），拒落价", date, price)
                        price = None
                    if price is not None:
                        best = min(flights, key=lambda f: f["price"]) if flights else None
                        # 价格一律取「有票明细最低」：headline 下限 100 vs
                        # 明细 300，头条有价明细无行时曾挂羊头（如 250 配
                        # 500 班的航班号/时刻，0.5x 守卫恰好拦不住）——
                        # 与 tongcheng 同步收敛为明细同源
                        if best:
                            if price < best["price"] * 0.85:
                                self.logger.warning(
                                    "[ctrip] 头条价 ￥%.0f 低于明细最低 ￥%.0f "
                                    "超 15%%，以明细为准", price, best["price"])
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
        # 下限与 qunar/明细口径统一 300（v1.5.37），防裸价半截行
        prices = [p for p in prices if 300 <= p <= 50000]
        return float(min(prices)) if prices else None

    def _extract_ctrip_flights(self, text: str) -> list:
        """携程航班明细（统一 schema）。

        fltitem[].mutilstn[] = 航段：basinfo.flgno=航班号、
        dateinfo.ddate/adate=完整起降时刻、aportinfo.city=到达城市；
        多段即中转。seg 内 fsitem[]（{"city":"宜昌","stopTime":45,...}，
        dump 实证）= 经停点，在场是「经停」不是「中转」，不改 mutilstn
        中转判定，只补 stopCitys/stopTime 原始字段。价格取 policyinfo[]
        中 quantity>0 的最低 tprice。响应根有 dict / list 两种形态。
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
        out = []
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
            # 共享航班实际承运（v1.5.48，仅展示不入指纹）：首段 basinfo
            # ishared=true 时 crerflgno=实际执飞航班号（dump 实证
            # 3U5276→MU5700，共享行 100% 在场）
            _b0 = first.get("basinfo") or {}
            share = (str(_b0.get("crerflgno") or "").strip()
                     if _b0.get("ishared") else "")
            # 经停点采集（fsitem 挂在每个 seg 内，直飞行为 null）：city 取
            # 分号串、stopTime 分钟累计转「X小时Y分」（tuniu/qunar PC 同
            # 口径，normalize 据此产 stopCity/stopTimeT/stopover）
            stops = []
            stop_mins = 0
            for s in segs:
                for fs in s.get("fsitem") or []:
                    if not isinstance(fs, dict):
                        continue
                    fc = str(fs.get("city") or "").strip()
                    if not fc:
                        continue
                    stops.append(fc)
                    try:
                        stop_mins += int(float(fs.get("stopTime") or 0))
                    except (TypeError, ValueError):
                        pass
            price = None
            best_ci = {}   # 最低价政策的舱位信息（舱位/餐食/准点率随价走）
            best_direct = False   # 最低价政策带「行李直达」标签（中转行李直挂）
            best_disc = ""   # 最低价政策的折扣（随价配对，与舱位同律）
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
                    cis = pi.get("classinfor")
                    best_ci = (cis[0] if isinstance(cis, list) and cis
                               and isinstance(cis[0], dict) else {})
                    # 政策级退改/行李标签（notetype=10，notecnt 竖线分隔，
                    # dump 实证「航变免费退改|行李直达」）——随最低价政策
                    # 配对，与舱位同律（曾取非最低价政策的标签即错配）
                    best_direct = any(
                        "行李直达" in str(fn.get("notecnt") or "")
                        for fn in (pi.get("fnotelst") or [])
                        if isinstance(fn, dict))
                    # 折扣（v1.5.49）：drate 与 tprice/quantity/fnotelst
                    # 同在 policyinfo 层（10-05 dump 实证 157/157 政策行
                    # 在场；classinfor 内 0 命中——注意非 classinfor.drate），
                    # 随最低价政策配对与舱位同律；6.70 浮点 → 「6.7折」
                    # 对齐 qunar discountStr 既有消费格式（report 图折扣
                    # 只认「N.N折」）。合理域 [0.5,10]（0.0001 类脏值弃，
                    # dump 1/98 行实证；真实值域 2.3-10）
                    try:
                        _dr = float(pi.get("drate"))
                        best_disc = f"{_dr:g}折" if 0.5 <= _dr <= 10 else ""
                    except (TypeError, ValueError):
                        best_disc = ""
            if price is None:
                continue
            dur_min = 0
            try:
                from datetime import datetime as _dt
                t0 = _dt.strptime(dd[:19], "%Y-%m-%d %H:%M:%S")
                t1 = _dt.strptime(ad[:19], "%Y-%m-%d %H:%M:%S")
                dur_min = int((t1 - t0).total_seconds() // 60)
            except Exception:
                pass
            # 衔接时长逐段 try（v1.5.37）：原整段 try 一段脏值即全部
            # 归零连累已成功段——改为失败段 warning 跳过、保留累计
            lay_min = 0
            from datetime import datetime as _dt
            for _si in range(len(segs) - 1):
                try:
                    _a = _dt.strptime(
                        (segs[_si].get("dateinfo") or {}).get("adate", "")[:19],
                        "%Y-%m-%d %H:%M:%S")
                    _b = _dt.strptime(
                        (segs[_si + 1].get("dateinfo") or {}).get("ddate",
                                                                  "")[:19],
                        "%Y-%m-%d %H:%M:%S")
                    lay_min += max(0, int((_b - _a).total_seconds() // 60))
                except Exception as e:
                    self.logger.warning(
                        "[ctrip] 第 %d 段衔接时长解析失败，跳过: %s", _si, e)
            dur = f"{dur_min // 60}时{dur_min % 60}分" if dur_min else ""
            code = "/".join(fnos)
            dep_d, arr_d = dd[:10], ad[:10]
            # 跨天按日期差（v1.5.41）：曾用 dur_min//1440 映射，时长脏值
            # 时错上加错（≥3 天一律「+2天」，与按日期差的其他渠道口径
            # 不一致）——日期字段本身是唯一事实源（flightnorm 同约定）
            try:
                from datetime import datetime as _dtc
                _xday = (_dtc.strptime(arr_d, "%Y-%m-%d")
                         - _dtc.strptime(dep_d, "%Y-%m-%d")).days
            except Exception:
                _xday = max(0, dur_min // 1440)
            cross = {0: "", 1: "+1天", 2: "+2天"}.get(
                max(0, _xday), f"+{max(0, _xday)}天")
            is_transfer = len(segs) > 1
            trans = ""
            if is_transfer:
                tc = ((segs[0].get("aportinfo") or {}).get("city") or "").strip()
                from .qunar import QunarCrawler as _Q
                trans = _Q.CITY_NAME.get(tc, tc) or "中转"
            # 决策字段（提取即得，同一次响应）：舱位/机型/准点率/餐食。
            # 真实挂载路径（dump 实证）：classinfor 在 policyinfo[] 内
            # （cgrd 数字 0=经济舱 1=公务 2=头等），craftinfo 在 segs 层。
            # 舱位随最低价政策配对（曾取「第一个带 classinfor 的政策」，
            # 与展示的最低价不同舱——真实字段但错误配对，误导性半假数据）
            craft = ""
            for s in segs:
                craft = ((s.get("craftinfo") or {}).get("cdisname") or "").strip()
                if craft:
                    break
            ci = best_ci
            # 机龄（v1.5.50）：classinfor.extendinfos[].content「机龄9年」
            # 结构化真值，取数字串与 tuniu flightYear「6.3」原始形态协议
            # 对齐；随最低价政策配对与舱位同律
            plane_age = ""
            for _ei in (ci.get("extendinfos") or []):
                _m = re.search(r"机龄([\d.]+)年",
                               str((_ei or {}).get("content") or ""))
                if _m:
                    plane_age = _m.group(1)
                    break
            # 决策标签（v1.5.50，item.aset[].tagarea[].tagcnt）：白名单只
            # 收稳定权益词——带价格的营销标签（青老年享￥N/已优惠）随价
            # 重摇每轮 churn 且脱离语境反成噪音；餐食/准点率已有结构化
            # 字段（MealTag/InTimeTag）不重复采
            labels = []
            for _a in (item.get("aset") or []):
                for _t in ((_a or {}).get("tagarea") or []):
                    _c = str((_t or {}).get("tagcnt") or "").strip()
                    if _c and _c in ("宠物友好", "绿色飞行奖里程",
                                     "轻飞享奖里程", "免费上网"):
                        labels.append(_c)
            prate = ci.get("prate")
            prate = str(int(prate)) if isinstance(prate, (int, float)) else ""
            meal = str(ci.get("meal") or "").strip()
            cgrd_cn = {0: "经济舱", 1: "公务舱", 2: "头等舱"}
            cabin_cn = cgrd_cn.get(ci.get("cgrd"), "") if ci else ""
            # 航站楼（v1.5.49）：mutilstn 首末段 dportinfo/aportinfo.bsname
            # （"T2"）。多航站楼一侧才有值（乌→沪 arr 98/98 T1/T2、dep
            # 0/98——出发地单航站楼渠道下发空串），留空不造
            dep_term = str((first.get("dportinfo") or {}).get("bsname")
                           or "").strip()
            arr_term = str((last.get("aportinfo") or {}).get("bsname")
                           or "").strip()
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
                "cabin": cabin_cn,
                "plane": craft,
                "prate": prate,
                "meal": meal,
                "shareCarrier": share,
                # v1.5.49 新决策字段（上面注释块：键路径 + dump 命中率）
                "discount": best_disc,
                "depTerminal": dep_term,
                "arrTerminal": arr_term,
                # v1.5.50：机龄数字串（tuniu planeAge 同协议）+ 权益标签
                "planeAge": plane_age,
                "labels": "·".join(labels),
                # 中转行李直挂（仅中转行置 direct；空串=未知，normalize
                # 的 transitServiceLabel 兜底照常生效）
                "transferBaggage": ("direct"
                                    if (is_transfer and best_direct) else ""),
                "stopCitys": ";".join(stops),
                "stopTime": (f"{stop_mins // 60}小时{stop_mins % 60}分"
                             if stop_mins > 0 else ""),
            })
        # 同班多政策只留最低价，防 TOP 名额被同班占满（v1.5.37）：
        # 旧去重键含 price 时同班多票价政策各行并存
        dedup = {}
        for row in out:
            k = (row["code"], row["depTime"])
            if k not in dedup or row["price"] < dedup[k]["price"]:
                dedup[k] = row
        return list(dedup.values())

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
                    f.write((item.get("text") or "")[:1000000])
                    f.write("\n")
            self.logger.info("[ctrip] 已保存 XHR: %s", path)
        except Exception:
            pass
