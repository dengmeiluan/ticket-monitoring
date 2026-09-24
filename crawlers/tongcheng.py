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

from core.models import PRICE_MAX, PRICE_MIN, FlightPrice
from .base import BaseCrawler, iata3


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
    # 起订阅落 dump，起一期解析（_extract_transfer_flights
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
                            # 中转报文一期解析：必须解析落库，不许仅落 dump
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
        # 下限与全链路价带单源 PRICE_MIN=100 一致，防裸价半截行
        prices = [p for p in prices if PRICE_MIN <= p <= PRICE_MAX]
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
            # 下限与全链路价带单源 PRICE_MIN=100 一致，防裸价半截行
            if PRICE_MIN <= lpv <= PRICE_MAX:
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
                        # 下限与全链路价带单源 PRICE_MIN=100 一致，防裸价半截行
                        if PRICE_MIN <= v <= PRICE_MAX:
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
        atp=含税总价（lps[] 多政策取有票最低）；中转走 connection
        独立接口（_extract_transfer_flights），data.tfs 实为筛选器
        配置（立减/仅看直飞/不看共享等）非航班数据。
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
        # 免费托运行李的 fc 码动态解析（data.cfs[ft=7].fis[fd=「免费托运
        # 行李」].fc，现网恒 "11"）：码义映射缺席时不落键（宁缺勿错，
        # 防 fc 码漂移后把无行李政策误标有行李）
        bag_fc = ""
        for _c in data.get("cfs") or []:
            if not (isinstance(_c, dict) and _c.get("ft") == 7):
                continue
            for _fi in _c.get("fis") or []:
                if isinstance(_fi, dict) \
                        and _fi.get("fd") == "免费托运行李":
                    bag_fc = str(_fi.get("fc") or "").strip()
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
            labels = ""
            left_tickets = None
            biz_price = None
            discount = ""
            bag_ok = False
            if isinstance(lps, list):
                for policy in lps:
                    if not (isinstance(policy, dict) and cls._has_ticket(policy.get("brs"))):
                        continue
                    try:
                        v = float(policy.get("atp") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not (PRICE_MIN <= v <= PRICE_MAX):
                        continue
                    # 公务/商务/头等舱政策价（bizPrice）：对每个有票政策
                    # 独立判定，不随最低价政策（次低价≠公务舱，串舱即错
                    # 配——ctrip 舱位配对同律）；判定词表与 tuniu
                    # _biz_fare 一致（三渠道同键同协议）。明确不采 cfcps
                    # （时段聚合价会挂别家航班公务价，B 篇 E1 实锤）。
                    # _has_ticket 同守卫：无票公务价是幻影参考宁缺
                    if (biz_price is None or v < biz_price) and any(
                            re.search(r"公务舱|商务舱|头等舱",
                                      str((pt or {}).get("td") or ""))
                            for pt in policy.get("pts") or []):
                        biz_price = v
                    if price is None or v < price:
                        price = v
                        # 随最低价政策复位防脏携带（
                        # 先高价新政带 atpt 后低价政无 atpt 时残留串行；
                        # 与 ctrip best_qty 无条件复位同律）
                        left_tickets = None
                        # 免费托运行李随最低价政策配对（fs[ft=7].fcs ⊇
                        # fc=经 cfs 动态解析的行李码）：每日 4 班低价行恰
                        # 是缺行李「裸价」（不含行李组政策均价 2160-3265
                        # vs 含行李组 4150-5321）——监控按最低价告警推出
                        # 的正是这批裸价，行级标记让达标价自带行李语义；
                        # 无 fc11 的最低价政策如实不落（防虚标）
                        bag_ok = bool(bag_fc) and any(
                            isinstance(g, dict) and g.get("ft") == 7
                            and bag_fc in [str(x) for x in (g.get("fcs") or [])]
                            for g in policy.get("fs") or [])
                        # 舱位名随价格政策走（pts[].td="6.8折经济舱"），
                        # 换新键名后顶层再无独立舱位字段
                        for pt in policy.get("pts") or []:
                            td = str((pt or {}).get("td") or "")
                            # 折扣同串复用（B 篇候选#3：现只提舱位丢
                            # 折扣；「5.4折经济舱」一次命中双抓，无
                            # 「N折」而含「全价」如实落「全价」，与
                            # tuniu/fliggy discount 同键同值域）
                            if not discount:
                                dm = re.search(r"(\d(?:\.\d)?)折", td)
                                if dm:
                                    discount = f"{dm.group(1)}折"
                                elif "全价" in td:
                                    discount = "全价"
                            cm = re.search(
                                r"(超级经济舱|经济舱|公务舱|头等舱|商务舱)", td)
                            if cm:
                                cabin_name = cm.group(1)
                                break
                        # 政策级舒适/机型标签随最低价政策配对（
                        # lps[].clct[{tt,td}] 80% 在场）：白名单只收
                        # 舒适决策词——tt=1「大机型」（同程唯一宽体信号，
                        # fl.mt 已证伪勿用）、tt=3「座椅较宽/平躺座椅」；
                        # tt=2「到达准点率N%」与 fl.sts 已采 prate 冗余
                        # 不采。注意 clct 的 tt 体系与 sts 不同（sts
                        # tt=1=准点率）勿混
                        _lw = []
                        for _c in policy.get("clct") or []:
                            _t = str((_c or {}).get("td") or "").strip()
                            if _t in ("大机型", "座椅较宽", "平躺座椅") \
                                    and _t not in _lw:
                                _lw.append(_t)
                        labels = "·".join(_lw)
                        # 余票紧张度（第九批）：lps[].atpt{tt,td}
                        # 「余1张」页红字稀缺真值随最低价政策配对（10-06
                        # 三份独立报文一致 2/48 行，恰挂该行有票最低价
                        # 政策；同政策 brs.al 仍桶值 20/30 证明 atpt 才是
                        # 稀缺信号）——与 ctrip leftTickets 同名同域；
                        # 值域守卫 1-9（≥10 渠道不发标签），解析失败/
                        # 缺省不落键（稀疏事件型，空=充足，勿造 0）
                        _at = policy.get("atpt")
                        if isinstance(_at, dict):
                            _lm = re.match(r"余(\d+)张",
                                           str(_at.get("td") or "").strip())
                            if _lm and 1 <= int(_lm.group(1)) <= 9:
                                left_tickets = int(_lm.group(1))
            if price is None:
                continue
            # 经停（$dirStop 在场即经停班，不得当直飞入库）：城市取
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
            # 机型体量（换源）：fl.amt 结构化体量（「中/大」，
            # 两日 dump 95/95 恒在）为主源——第六批用的 afn 括号渠道仅
            # ~66% 下发（31/47+32/48），是 DB planeSize 45.5% 半缺根因；
            # afn 括号降为 amt 缺失时兜底（值归一「大型机/中型机/小型机」
            # 与其他渠道同键同值域，「未定/其他」不落）
            _amt = str(f.get("amt") or "").strip()
            plane_size = f"{_amt}型机" if _amt in ("大", "中", "小") else ""
            if not plane_size:
                _pm = re.search(r"[（(]([大中小])[)）]",
                                str(f.get("afn") or ""))
                plane_size = f"{_pm.group(1)}型机" if _pm else ""
            # 共享实际承运（sfd+icsf 双守卫）：sfd「flightId_
            # CZ6993」须剥前缀；icsf=False 但 sfd 有值 27 行=假值不落；
            # 自飞挂自身 id（self=CZ6993 sfd=CZ6993 完全同号）不落——
            # 同航司不同号（CZ6993 营销/CZ6990 执飞）是真共享勿误杀
            share_carrier = ""
            if f.get("icsf") is True:
                _s = str(f.get("sfd") or "").split("_")[-1].strip()
                if _s and _s != str(f.get("fn") or "").strip():
                    share_carrier = _s
            # sts 标签子向量：tt=1 准点率 / tt=4 餐食（提取即得的决策
            # 信息）+ 扩容（两日 dump 95/95 恒在）：tt=2 机龄
            # （「机龄14.6年」→「14.6」，tuniu planeAge 串协议）、tt=6
            # 廊桥率 / tt=9 取消率（百分数 int，与 ctrip bridgeRate 同
            # 键同协议——廊桥率勿另起 jetBridgeRate）、tt=7 平均延误
            # （int 分钟，ctrip/tuniu avgDelay 同协议）、tt=3 机上 WiFi
            # （稀疏 3/95 真区分，词面白名单宁缺勿错，并 labels 走既有
            # 渲染防孤儿键）；tt=8「廉价航空」不采（flightnorm lcc 派生
            # 全渠道受益，单渠道标签反而漏）
            prate, meal = "", ""
            plane_age = avg_delay = cancel_rate = bridge_rate = ""
            wifi_txt = ""
            for st in f.get("sts") or []:
                if not isinstance(st, dict):
                    continue
                # 站点改版标签键 tx→td（新报文 td 881 处、tx 0 处，
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
                elif tt == 2 and not plane_age:
                    _ma = re.search(r"机龄(\d+(?:\.\d+)?)年", tx)
                    if _ma:
                        plane_age = _ma.group(1)
                elif tt == 6 and bridge_rate == "":
                    _mb = re.search(r"廊桥率(\d{1,3})\s*%", tx)
                    if _mb:
                        bridge_rate = int(_mb.group(1))
                elif tt == 7 and avg_delay == "":
                    _md = re.search(r"平均延误(\d{1,3})分钟", tx)
                    if _md:
                        avg_delay = int(_md.group(1))
                elif tt == 9 and cancel_rate == "":
                    _mc = re.search(r"取消率(\d{1,3})\s*%", tx)
                    if _mc:
                        cancel_rate = int(_mc.group(1))
                elif tt == 3 and not wifi_txt:
                    _t3 = tx.strip()
                    if _t3 in ("机上WiFi", "免费上网"):
                        wifi_txt = _t3
            if wifi_txt:
                labels = "·".join(x for x in (labels, wifi_txt) if x)
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
                # 公务/商务/头等舱参考价（ctrip/tuniu bizPrice 同键同
                # 协议，int 转写）+ 折扣（随最低价政策 pts 同串复用，
                # tuniu/fliggy discount 同键同态仅入 extra）——有值才落
                **({"bizPrice": int(biz_price)} if biz_price else {}),
                **({"discount": discount} if discount else {}),
                # 机型：主源 amn（真机型名「空客A321-200」100% 在场，
                # afn 三成行产出「326/73M/73L」裸码值），afn/旧键
                # equipmentName 兜底。清洗：旧键「机型」前缀（机型73M 曾
                # 直入推送决策行）与 _变体后缀（空客A320_186）
                "plane": (re.sub(r"_\d+$", "",
                          (f.get("amn") or f.get("afn")
                           or f.get("equipmentName") or ""))
                          .removeprefix("机型")
                          .split("（")[0].split("(")[0].strip()),
                # 免费托运行李标记（随最低价政策，值面与 qunar baggage
                # 同维度；flightnorm cabin_text 通路现成零渲染改动）
                **({"baggage": "免费托运"} if bag_ok else {}),
                "stopCitys": stop_city,
                "stopTime": stop_time,
                "prate": prate,
                "meal": meal,
                # 航站楼（fl 元素 dat/aat，47/47 在场，空串如实留空——
                # 同程曾是五渠道唯一零航站楼，补齐）
                "depTerminal": str(f.get("dat") or "").strip(),
                "arrTerminal": str(f.get("aat") or "").strip(),
                # 新决策字段：机场简称（dasn/aasn「天山/浦东」
                # 100% 在场，同城多场按机场区分下发）+ 政策舒适标签
                # （上面注释块：clct 白名单随最低价政策配对）
                "depAirport": str(f.get("dasn") or "").strip(),
                "arrAirport": str(f.get("aasn") or "").strip(),
                # 行级机场 IATA 码（第十二批调研 dump 实证：
                # fl[].dac/aac 与 dasn/aasn 同层两日 95/95 恒在——推翻
                # 「同程无源」预期，至此四渠道码值源齐三仅 fliggy
                # 无源；与中文机场名逐行配对零冲突、^[A-Z]{3}$ 零违例）。
                # iata3 守卫同 qunar/tuniu/ctrip 三源同律，同名落键即
                # propagate/_user_state 白名单自动继承零协议改动；勿用
                # fs[].fcs 分面副本作第二源（调研勿采在册）
                "depAirportCode": iata3(f.get("dac")),
                "arrAirportCode": iata3(f.get("aac")),
                "labels": labels,
                # 机型体量（上方 plane_size：amt 结构化主源+afn 括号兜底
                # ——第六批 afn 单源渠道仅 ~66% 下发是半缺根因）+
                # 共享实际承运（上方 share_carrier：sfd+icsf 双守卫）
                "planeSize": plane_size,
                "shareCarrier": share_carrier,
                # 决策字段（上方注释块：sts tt 体系+dump 命中率）
                "planeAge": plane_age,
                "avgDelay": avg_delay,
                "cancelRate": cancel_rate,
                "bridgeRate": bridge_rate,
            })
            if left_tickets is not None:
                out[-1]["leftTickets"] = left_tickets
        # 同班多政策只留最低价，防 TOP 名额被同班占满：
        # 旧去重键含 price 时同班多票价政策各行并存
        dedup = {}
        for row in out:
            k = (row["code"], row["depTime"])
            if k not in dedup or row["price"] < dedup[k]["price"]:
                dedup[k] = row
        # 改期比价日历（第八批调研 dump 实证）：data.pc[]=
        # 出发日 ±7 天每日最低价 15 点（{"dd":"2026-09-28","lp":886}，
        # book1 顶层恒在、connection 响应无此键），与 qunar
        # trendPrice.goFTrend 跨渠道同语义——落同名键 trendGo 同协议
        # [["MM-DD",价],…] 挂当轮最低价行，消费端（webui 改期窗口/
        # 趋势）零改动双渠道受益；逐点校验同 qunar _parse_trend_go
        # （dd 正则 + 价域 100-50000，坏点弃）；hlp 语义未证不采
        pc = data.get("pc")
        if isinstance(pc, list) and dedup:
            tg = []
            for p in pc:
                if not isinstance(p, dict):
                    continue
                d = str(p.get("dd") or "").strip()
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                    continue
                try:
                    v = float(p.get("lp"))
                except (TypeError, ValueError):
                    continue
                if not (100 <= v <= 50000):
                    continue
                tg.append([d[5:], round(v)])
            if tg:
                lo = min(dedup.values(), key=lambda f: f.get("price") or 9e9)
                lo["trendGo"] = tg
        return list(dedup.values())

    # 中转衔接时长 "2h15m"/"11h"（fps.sd）
    _RE_SD = re.compile(r"^(\d+)h(?:(\d+)m)?$")

    # connection 政策级服务标签白名单（lps[].fwbqs[].td）：真值唯一
    # 「第2程：免费上网」=中转第二段机上 WiFi 服务承诺，与 sts tt=3
    # 白名单同族同源；精确匹配渠道改文案即静默不并（宁缺勿错）
    _FWBQS_WORDS = ("第2程：免费上网",)

    @classmethod
    def _extract_transfer_flights(cls, text: str) -> list:
        """同程 connection/flights 中转明细一期（宁缺勿错）。

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
         增行级证据源（调研 候选#1）：stss 服务行
        ServiceType=="LUGGAGE" 且 ServiceName 白名单（「行李直达」/
        「免提取托运行李」两日 dump 各 1/24）双门命中也置 "direct"——
        两日 dump 图例五词恒全并存致 direct_only 恒 False，图例路径
        全库 direct=0；守卫：同类目不混入（LUGGAGE_DEPOSIT/TRANSFER_
        HOTEL）、任段廉航不落、反例条款（带此服务实为需重托运证据
        即回滚）在册。
         增采（10-05 dump 实证）：fp 层 dat/aat（出发/到达航站
        楼，26/26 在场，空串如实留空）→ depTerminal/arrTerminal；fp 层
        stss[].ServiceName（中转增值服务，19/26 fps 在场）去重以「/」
        联接 → transferService，doc.check「转机免安检」为页面级图例在
        场时并入串尾；随最低价政策配对 lps[].$tcTip.c2（「航司中转，
        享联程服务」，与 cabin 同律防政策错配）→ airlineTransfer。
        一期不采（置信不足/协议未列）：lps[].tags 混淆串、$showTransfer
        Rts/$mtsN5 带价营销签（每轮 churn）、跨航站楼明细、doc.terminal。"""
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
            tc_tip = ""
            fw_txt = ""   # 第二段服务承诺（随最低价政策配对）
            left_tickets = None
            for policy in fp.get("lps") or []:
                if not (isinstance(policy, dict)
                        and cls._has_ticket(policy.get("brs"))):
                    continue
                try:
                    v = float(policy.get("atp") or 0)
                except (TypeError, ValueError):
                    continue
                if PRICE_MIN <= v <= PRICE_MAX and (price is None or v < price):
                    price = v
                    # 随最低价政策复位防脏携带（同 book1）
                    left_tickets = None
                    # 舱位名随价格政策走（pts[].td，同 book1 直飞口径）
                    for pt in policy.get("pts") or []:
                        td_txt = str((pt or {}).get("td") or "")
                        cm = re.search(
                            r"(超级经济舱|经济舱|公务舱|头等舱|商务舱)",
                            td_txt)
                        if cm:
                            cabin_name = cm.group(1)
                            break
                    # 航司中转标注随最低价政策配对（$tcTip.c2，同 cabin
                    # 同律防政策错配）；c1「中转专享」营销词不采
                    tip = policy.get("$tcTip")
                    if isinstance(tip, dict):
                        tc_tip = str(tip.get("c2") or "").strip()
                    # 第二段服务承诺（fwbqs[].td 白名单）随最低价
                    # 政策配对：中转产品的服务权益语义（第二段机上
                    # WiFi），并 labels 既有渲染通道零新键
                    fw = policy.get("fwbqs")
                    if isinstance(fw, list):
                        fw_txt = "·".join(dict.fromkeys(
                            t for t in (str((x or {}).get("td") or "").strip()
                                        for x in fw if isinstance(x, dict))
                            if t in cls._FWBQS_WORDS))
                    # 余票紧张度随最低价政策配对（同 book1 直飞
                    # 口径；本轮 connection 未现样本，出现即采）
                    _at = policy.get("atpt")
                    if isinstance(_at, dict):
                        _lm = re.match(r"余(\d+)张",
                                       str(_at.get("td") or "").strip())
                        if _lm and 1 <= int(_lm.group(1)) <= 9:
                            left_tickets = int(_lm.group(1))
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
            # 机型体量：中转行整键必须产出（不产出即 DB 174 行全缺）
            # ——段级 ss[].amn 括号体量 80/96 段在场（「空客320(中)」），
            # 首个命中段取值，无括号形态不落（宁缺勿错）
            plane_size = ""
            for s in segs:
                _psm = re.search(r"[（(]([大中小])[)）]",
                                 str(s.get("amn") or ""))
                if _psm:
                    plane_size = f"{_psm.group(1)}型机"
                    break
            # 跨天按日期差（中转常 +1/+2 天，二元判断会谎报）
            try:
                from datetime import date as _d
                xday = (_d.fromisoformat(at[:10])
                        - _d.fromisoformat(dt[:10])).days
            except Exception:
                xday = 0
            # 中转增值服务名去重联接（ServiceType 8 类：住宿/休息室/
            # 餐食/行李寄存/摆渡车…）；「优惠*」为类目名非带价签可采；
            # doc.check「转机免安检」页面级图例（非行级归属）在场并入
            # 串尾——复用 transferBaggage「图例唯一指向才置」保守口径
            svc_names = []
            row_bag_ev = False
            for st in fp.get("stss") or []:
                if not isinstance(st, dict):
                    continue
                nm = str(st.get("ServiceName") or "").strip()
                if nm and nm not in svc_names:
                    svc_names.append(nm)
                # 行级直挂证据（调研 候选#1，两日 dump 各
                # 1/24 中转行命中）：页面级 doc 图例五词恒全并存 →
                # direct_only 恒 False，图例路径全库 direct=0——「行李
                # 直达/免提取托运行李」44 行/日的真实直挂信息三态「空=
                # 未知」吞掉。stss 结构化服务行才是行级绑定信号；双门
                # 精确匹配防同类目混入（LUGGAGE_DEPOSIT=免费行李寄存/
                # TRANSFER_HOTEL=免费住宿不同型不触发）。反例条款：线上
                # 若现「带此服务实为需重托运」证据即回滚（bag_direct
                # 哨兵线上观测兜底）
                if (str(st.get("ServiceType") or "").strip() == "LUGGAGE"
                        and nm in ("行李直达", "免提取托运行李")):
                    row_bag_ev = True
            # 廉航任段不落（flightnorm「春秋大概率不直挂」同律——
            # finditer 全段扫描，联程码串任一段命中即真）
            if row_bag_ev:
                from core.flightnorm import _is_lcc
                if _is_lcc(code):
                    row_bag_ev = False
            check_txt = str(doc.get("check") or "").strip()
            if check_txt and check_txt not in svc_names:
                svc_names.append(check_txt)
            # （调研 R3）：doc.book1「航班延误取消，免费退改」
            # 页面级图例（10-05/10-06 两 dump 4/4 connection 块恒在）——
            # 五渠道报文唯一「延误/取消免费退改」结构化信号，恰挂中转
            # 衔接风险保障语义；白名单双词精确匹配，渠道改文案即静默
            # 不并（宁缺勿错）；去重并入串尾与 check 同律
            b1_txt = str(doc.get("book1") or "").strip()
            if ("延误取消" in b1_txt and "免费退改" in b1_txt
                    and b1_txt not in svc_names):
                svc_names.append(b1_txt)
            svc_txt = "/".join(svc_names)
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
                # 渠道结构化真值标记：flightnorm 的 1440 回绕
                # 判伪豁免只认 layoverSrc=transInfo——真值跨天长停留恰会
                # 落入击杀区（qunar 同款协议），缺标记=长停留被静默归零
                "layoverSrc": "transInfo" if lay else "",
                "cabin": cabin_name,
                "plane": plane,
                # 中转行李直挂（图例唯一指向直挂才置，见 docstring）+
                # 行级证据（stss 双门，廉航守卫见上）；两源任一
                # 正向即 direct（行级证据救回图例全并存形态的行）
                "transferBaggage":
                    "direct" if (direct_only or row_bag_ev) else "",
                # 中转增值服务（stss[].ServiceName 去重「/」联接）；
                # doc.check「转机免安检」页面级图例在场并入串尾
                "transferService": svc_txt,
                # 航司中转 vs 自行中转（随最低价政策配对，空=无标注）
                "airlineTransfer": tc_tip,
                # 第二段服务承诺（有值才落——labels 既有渲染通道，
                # 行形态不漂移）
                **({"labels": fw_txt} if fw_txt else {}),
                # 航站楼（fp 层 dat/aat 结构化真值，空串如实留空）
                "depTerminal": str(fp.get("dat") or "").strip(),
                "arrTerminal": str(fp.get("aat") or "").strip(),
                # 机场级定位（fp 层 dasn/aasn「天山/浦东」，
                # 两日 dump 24/24+24/24 恒在——只读 dat/aat 航站楼会漏读
                # 机场名（DB 中转行 depAirport/arrAirport 174 行全缺的根因），
                # 必须一并读）+ 机型体量（上方 ss[].amn 括号）
                "depAirport": str(fp.get("dasn") or "").strip(),
                "arrAirport": str(fp.get("aasn") or "").strip(),
                # 中转行 IATA 码（conn 块两日 48/48 恒在）：段链
                # 取 ss[0].dac（首段出发=整体出发）/ss[-1].aac（末段到达
                # =整体到达，与 transTerminal 段级真值同位）；fp 层无
                # dac/aac 键（调研逐叶排尽仅段级有源）。中间段中转机场码
                # transCityCode 口径与 qunar 同律暂不启用（可选附带在册）
                "depAirportCode": iata3(segs[0].get("dac")),
                "arrAirportCode": iata3(segs[-1].get("aac")),
                "planeSize": plane_size,
                # 换乘楼配对（第八批调研 dump 实证）：段级
                # ss[0].aat=首段到达楼=中转楼（两日 48/48 在场，「T2」
                # 裸形态——段级无机场名键，asn 是航司名），与 qunar
                # transTerminal 同名同位零新渲染；ss[1].dat=二段出发楼
                # （可空串，10-06 张掖例），与到达楼配对成「T2 到 T5 出」
                # 换乘路径（同律 transDepTerminal 白名单既有渲染位）。
                # fp 层 dat≡ss[0].dat（24/24）证明 fp 层是整行口径、
                # 段级才是楼级真值；两处独立源各取各的，不等即跨楼信息
                "transTerminal": str(segs[0].get("aat") or "").strip(),
                "transDepTerminal": str(segs[1].get("dat") or "").strip(),
            })
            if left_tickets is not None:
                out[-1]["leftTickets"] = left_tickets
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
                    f.write((item.get("text") or "")[:4000000])
                    f.write("\n")
            self.logger.info("[tongcheng] 已保存 XHR: %s", path)
        except Exception:
            pass
