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

from core.models import PRICE_MAX, PRICE_MIN, FlightPrice
from core.flightnorm import AIRPORT_NAME_CN
from .base import BaseCrawler, iata3


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
        # 下限与全链路价带单源 PRICE_MIN=100 一致，防裸价半截行
        prices = [p for p in prices if PRICE_MIN <= p <= PRICE_MAX]
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
            # 共享航班实际承运（仅展示不入指纹）：首段 basinfo
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
            best_freelug = False   # 最低价政策带 FreeLuggage 旗标（nt=31，含免费托运额）
            best_disc = ""   # 最低价政策的折扣（随价配对，与舱位同律）
            best_qty = None   # 最低价政策的余票数（quantity 1-10）
            biz_price = None   # 高档舱（公务/头等）最低参考价
            biz_cgrd = None   # 胜出政策的舱别（1=公务 2=头等，词面随源）
            refund_free = False   # 最低价政策带「航变免费退改」
            hotel_free = False   # 最低价政策带「中转免费住宿」
            best_age = ""   # 最低价政策的年龄限制（「限青年/限老年/限年龄/限学生」）
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
                # 高档舱（公务/头等）最低参考价 bizPrice：cgrd∈{1,2}
                # 政策取最低 tprice，多档取 min（协议=「高档舱最低参考
                # 价」，qunar businessClassMinPrice/tuniu 高档舱政策/
                # fliggy 双价行高档词同键同语义；取 max 会成「公务￥
                # 头等价」舱名数值双误）。classinfor 首元素语义与
                # best_ci 舱位提取同律——dump 实证全部政策
                # first-hi==any-hi 全等、混合形态 0 例，宁缺勿错不认
                # 后位元素。主价即高档舱价时与 price 同值照落
                # （qunar 有源即落同律，渲染端「公务￥N」语义仍真）
                _cis = pi.get("classinfor")
                if (isinstance(_cis, list) and _cis
                        and isinstance(_cis[0], dict)
                        and _cis[0].get("cgrd") in (1, 2)
                        and PRICE_MIN <= v <= PRICE_MAX
                        and (biz_price is None or v < biz_price)):
                    biz_price = v
                    # 胜出（最低 tprice）政策的舱别随键（1=公务
                    # 2=头等）：渲染端词面随源——纯头等政策班的
                    # 「公务￥N」舱名数值双误在源头关闭（与「取 max
                    # 会成公务￥头等价」同族律）
                    biz_cgrd = _cis[0].get("cgrd")
                if PRICE_MIN <= v <= PRICE_MAX and (price is None or v < price):
                    price = v
                    try:
                        best_qty = int(q)
                    except (TypeError, ValueError):
                        best_qty = None
                    cis = pi.get("classinfor")
                    best_ci = (cis[0] if isinstance(cis, list) and cis
                               and isinstance(cis[0], dict) else {})
                    # 政策级退改/行李标签（notetype=10，notecnt 竖线分隔，
                    # dump 实证「航变免费退改|行李直达」）——随最低价政策
                    # 配对，与舱位同律（曾取非最低价政策的标签即错配）。
                    # 航变免费退改：稀疏权益词（10-05 dump 仅
                    # 1 政策带）不设独立键防孤儿，随 best 直挂同源并入
                    # labels 白名单走既有渲染
                    best_direct = any(
                        "行李直达" in str(fn.get("notecnt") or "")
                        for fn in (pi.get("fnotelst") or [])
                        if isinstance(fn, dict))
                    # 中转行李第二信号源（nt=31 FreeLuggage 旗标，逗号
                    # 分隔串精确匹配防子串误命中）：免费托运→推断两段
                    # 可直挂（qunar flightMark.freeLuggage 推断律同律，
                    # 非实测直挂证据）；直飞行以 labels「含免费托运」
                    # 观测词走既有渲染。ctrip 是五渠道唯一无行李出口
                    # 的渠道——「你看到的最低价不含免费托运」是比价
                    # 失真主因；9C/3U/FM/HO 恒 0=廉航票不含自洽
                    best_freelug = any(
                        "FreeLuggage" in (t.strip() for t in
                                          str(fn.get("notecnt") or "")
                                          .split(","))
                        for fn in (pi.get("fnotelst") or [])
                        if isinstance(fn, dict))
                    if any("航变免费退改" in str(fn.get("notecnt") or "")
                           for fn in (pi.get("fnotelst") or [])
                           if isinstance(fn, dict)):
                        refund_free = True
                    # 中转免费住宿：notetype=10 同源权益词
                    # （10-06 dump 4 政策在场、10-05 为 0——稀疏但真实，
                    # 防孤儿键随 labels 白名单走既有渲染）
                    if any("中转免费住宿" in str(fn.get("notecnt") or "")
                           for fn in (pi.get("fnotelst") or [])
                           if isinstance(fn, dict)):
                        hotel_free = True
                    # 年龄限制专享价（A 篇 C-1）：fnotelst nt=20
                    # 「2767_LimitedYoungAgePolicy」=青老年票硬性购买
                    # 资格（误购无法值机）。下划线尾段词表白名单四类映射，
                    # 未知英文类型整段丢弃宁缺勿错；只在最低价政策带
                    # 限制时落（「你看到的最低价买不了」强信号；dump
                    # 10 行实证受限政策即最低价政策）。S-4 破案：notes
                    # nt=104（zstd）与 nt=20 在 9/9 航班同现且 nt=20
                    # 自带细分与价格前缀——零新依赖取文案源
                    for fn in (pi.get("fnotelst") or []):
                        if (isinstance(fn, dict)
                                and fn.get("notetype") == 20):
                            best_age = {
                                "LimitedYoungAgePolicy": "限青年",
                                "LimitedOldAgePolicy": "限老年",
                                "LimitedAgePolicy": "限年龄",
                                "LimitedStudentPolicy": "限学生",
                            }.get(str(fn.get("notecnt") or "")
                                  .split("_")[-1], "")
                    # 折扣：drate 与 tprice/quantity/fnotelst
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
            # 衔接时长逐段 try：失败段 warning 跳过、保留累计，
            # 防一段脏值整段归零连累已成功段
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
            # 跨天按日期差映射，禁用 dur_min//1440——时长脏值
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
            plane_size = ""
            for s in segs:
                _ci_s = s.get("craftinfo") or {}
                if not craft:
                    craft = str(_ci_s.get("cdisname") or "").strip()
                # 机型体量（第六批四渠道收口最后缺口）：craftinfo
                # .kind 结构化真值（1=大型机/2=中型机，与 cdisname「(大)/
                # (中)」后缀 109/109 对完全自洽——渠道给的映射勿自维护
                # 宽体清单；E190 渠道判「中」照采）；kind 缺失段 5/175 时
                # cdisname 括号兜底（同源同信息）
                if not plane_size:
                    _kind = _ci_s.get("kind")
                    if _kind in (1, 2):
                        plane_size = {1: "大型机", 2: "中型机"}[_kind]
                    else:
                        # 括号兜底扫当前段 cdisname（扫
                        # 外层 craft 恒为首段，首段无括号+后段 kind 缺失
                        # 时会漏采后段括号信息）
                        _psm = re.search(r"[（(]([大中])[)）]",
                                         str(_ci_s.get("cdisname") or ""))
                        if _psm:
                            plane_size = f"{_psm.group(1)}型机"
                if craft and plane_size:
                    break
            ci = best_ci
            # 机龄：classinfor.extendinfos[].content「机龄9年」
            # 结构化真值，取数字串与 tuniu flightYear「6.3」原始形态协议
            # 对齐；随最低价政策配对与舱位同律
            plane_age = ""
            avg_delay = ""
            bridge_rate = ""
            has_wifi = ci.get("wifi") is True   # 结构化布尔优先（
            # dump 148/148 在场且与文本「机上Wi-Fi」完全对应——content
            # 文案改版时布尔仍真）；文本匹配降为兜底
            for _ei in (ci.get("extendinfos") or []):
                _c = str((_ei or {}).get("content") or "")
                # 机龄（精度）：「机龄1年6个月」月成分曾截断丢
                # （22/40 带月形态）——有月折算小数年与 tuniu flightYear
                # 「6.3」协议对齐；「机龄5个月」无年字形态曾整体丢失
                _m = re.search(r"机龄(\d+)年(?:(\d+)个月)?", _c)
                if _m:
                    _mo = int(_m.group(2) or 0)
                    plane_age = (f"{round(int(_m.group(1)) + _mo / 12, 1):g}"
                                 if _mo else _m.group(1))
                else:
                    _mm = re.search(r"机龄(\d+)个月", _c)
                    if _mm:
                        plane_age = f"{round(int(_mm.group(1)) / 12, 1):g}"
                # 平均延误/连廊率/Wi-Fi（content 全集 40 档实证：
                # 「平均延误N分钟」26 档/「连廊率N%」/「机上Wi-Fi」）——
                # avgDelay int 分钟与 tuniu 同协议（webui 明细次行「延N分」
                # 消费端已在）；连廊率取百分数数字；Wi-Fi 并 labels 走既有
                # 渲染（防孤儿键）。随最低价政策配对与舱位同律
                _md = re.search(r"平均延误(\d+)分钟", _c)
                if _md:
                    avg_delay = int(_md.group(1))
                _mb = re.search(r"连廊率(\d+)%", _c)
                if _mb:
                    bridge_rate = int(_mb.group(1))
                if not has_wifi and ("Wi-Fi" in _c or "WiFi" in _c):
                    has_wifi = True
            # 决策标签（item.aset[].tagarea[].tagcnt）：白名单只
            # 收稳定权益词——带价格的营销标签（青老年享￥N/已优惠）随价
            # 重摇每轮 churn 且脱离语境反成噪音；餐食结构化字段
            # （MealTag）不重复采
            labels = []
            # aset 层中转行李信号（同一次遍历，tagcnt 中转行
            # 专属 7+6/95）：「联程值机，行李直挂」=item 层直挂第二来源
            # （政策级 fnotelst nt=10 之外，随 item 不随政策、无错配）；
            # 「行李代转运」=明确的不直挂真值（transferBaggage 第三态
            # recheck——空串是「未知」，recheck 是「已知需重新托运」，
            # 直挂筛选下两者同为不满足，展示语义不同）
            _item_direct = _recheck = False
            # 准点率真源（tcode=InTimeTag 的 tagcnt「准点率N%」）：
            # classinfor.prate 值域仅 {100,97}，与 InTimeTag 逐行交叉
            # 一致率 1.2%（80 行双源）——伪源，InTimeTag 才是真源；
            # 采首个（两段中转行各带时取首段，与 best_ci=classinfor[0]
            # 首段配对同律，last-wins 会让口径漂到末段）；脏词面弃
            _intime = None
            for _a in (item.get("aset") or []):
                for _t in ((_a or {}).get("tagarea") or []):
                    _c = str((_t or {}).get("tagcnt") or "").strip()
                    _code = str((_t or {}).get("tcode") or "").strip()
                    if _code == "InTimeTag":
                        if _intime is None:
                            _im = re.search(r"(\d+)\s*%", _c)
                            if _im:
                                _intime = int(_im.group(1))
                        continue
                    # 证件限制（CredentialsLimit_NewStyle）：「限|」前缀=
                    # 购买资格门槛（误购无法出行）采入 labels；「荐|部分
                    # 证件价￥N」带价格随价 churn 不采（营销词纪律）
                    if _code == "CredentialsLimit_NewStyle" \
                            and _c.startswith("限|") and _c not in labels:
                        labels.append(_c)
                        continue
                    if _c == "行李代转运":
                        _recheck = True
                    elif _c == "联程值机，行李直挂":
                        _item_direct = True
                    elif _c and _c in ("宠物友好", "绿色飞行奖里程",
                                       "轻飞享奖里程", "免费上网",
                                       # 第八批扩充（178 班去重+
                                       # fresh 复验稳定非价格词）：中转
                                       # 餐食/地面接驳/舱内宠物第三态——
                                       # 地域品牌词（经兰飞/豫转豫好）与
                                       # 「优质中转·耗时短」churn 风险
                                       # 不收；「中转住宿」与政策级 nt=10
                                       # 既有 hotel_free 同义不重复
                                       "中转餐饮", "免费市区班车",
                                       "宠物进客舱",
                                       # 资格价标记（tcode=G_LoginMobile
                                       # Discount，纯词无价格不随价
                                       # churn）：该行价格非全民价
                                       # （登录/老客才可买）——「会员价/
                                       # 资格价」诉求在本报文唯一稳定
                                       # 落点；按 tagcnt 词面匹配不惧
                                       # tcode 换代
                                       "老客专享",
                                       # 经济舱售罄（tcode=EconomyClass
                                       # SellOut，1/230 稀疏但真——
                                       # CA8564 全班仅剩头等 9900 实证，
                                       # 该班经济舱买不到）
                                       "经济舱售罄"):
                        if _c not in labels:   # aset 同词重复去重（P2-8）
                            labels.append(_c)
            if has_wifi:
                labels.append("机上Wi-Fi")
            if refund_free:
                labels.append("航变免费退改")
            if hotel_free:
                labels.append("中转免费住宿")
            # 直飞行含免费托运观测词（中转行走 transferBaggage=direct
            # 既有展示，不重复落词）
            if best_freelug and not is_transfer:
                labels.append("含免费托运")
            # 联程服务明细（notes notetype=103 notecnt 内嵌 JSON，
            # 行级 2/260 稀疏事件型）：G5-LC-V2 产品行「转机引导、行李
            # 直挂、航变免费改、一次值机、20KG免费行李、一次安检」——
            # 全报文唯一行李额数字+直挂/免费改服务承诺，该行现有三源
            # 全空不采则永久缺失；flag=0（DEFAULT-TC 哨兵）value 空跳过，
            # title 产品名是地域品牌词不并串。与 tongcheng/qunar
            # transferService 同键同语义位；「20KG免费行李」随全文透传
            # 不拆独立键（单渠道孤源防孤儿）
            ts_svc = ""
            _ts_direct = False
            for _no in item.get("notes") or []:
                if not isinstance(_no, dict) or _no.get("notetype") != 103:
                    continue
                try:
                    _nj = json.loads(_no.get("notecnt") or "")
                except Exception:
                    continue
                if isinstance(_nj, dict) and _nj.get("flag") == 1:
                    ts_svc = str(_nj.get("value") or "").strip()
                    _ts_direct = "行李直挂" in ts_svc
                    break
            # 舱位字母：classNoteList notetype=2 notecnt 单字母
            # （Y/B/M/H/Q/...，classinfor 级 100% 在场；nt=1 恒等 prate
            # 纯重复不采）——退改等级的根（同为经济舱 Q 舱与 Y 舱退改
            # 天差地别），tuniu cabinCode 同键协议对齐；随最低价政策
            # 配对（best_ci 本就随价走），单字母正则校验宁缺勿错
            cabin_code = ""
            for _cn in (ci.get("classNoteList") or []):
                if isinstance(_cn, dict) and _cn.get("notetype") == 2:
                    _cc = str(_cn.get("notecnt") or "").strip()
                    if re.fullmatch(r"[A-Z]", _cc):
                        cabin_code = _cc
                    break
            # 会员专享资格价（classNoteList nt=3 旗标，12 政策/230 行
            # dump 实证，与 aset 老客专享零交集的第二资格价家族）：
            # 非会员出不了票的硬性购买门槛，与 nt=20 年龄限制同族并入
            # agePolicy 词面零新键。逗号串与分元素两形态按词表判
            # （split 归一）；裸 AirlineMemberShip 语义未证不采（宁缺
            # 勿错）；与年龄限制并存时「·」拼接
            _mem = ""
            for _cn in (ci.get("classNoteList") or []):
                if not (isinstance(_cn, dict) and _cn.get("notetype") == 3):
                    continue
                _words = [t.strip() for t in
                          str(_cn.get("notecnt") or "").split(",")
                          if t.strip()]
                if "LimitedCtripMemberShip" in _words:
                    _mem = "限携程会员"
                elif "LimitedAirlineMembership" in _words:
                    _mem = "限航司会员"
            if _mem:
                best_age = f"{best_age}·{_mem}" if best_age else _mem
            prate = ci.get("prate")
            if not isinstance(prate, (int, float)):
                # 补源（A 篇 R-C2）：classNoteList nt=1 与 prate 同指标
                # （两源同值 208/208 零背离），在场率 302/302 vs prate 键
                # 208/304——兜底后「准点N%」覆盖率 68%→近100%，零新键
                for _cn in (ci.get("classNoteList") or []):
                    if isinstance(_cn, dict) and _cn.get("notetype") == 1:
                        try:
                            prate = float(_cn.get("notecnt"))
                        except (TypeError, ValueError):
                            prate = None   # 脏值弃宁缺勿错
                        break
            prate = str(int(prate)) if isinstance(prate, (int, float)) else ""
            # 真源覆盖（上方 aset 遍历的 InTimeTag）：classinfor.prate/
            # nt=1 源仅作兜底，InTimeTag 有值即覆盖（{100,97} 两档伪源
            # 与真值大面积背离，交叉一致率仅 1.2%）
            if _intime is not None:
                prate = str(_intime)
            meal = str(ci.get("meal") or "").strip()
            cgrd_cn = {0: "经济舱", 1: "公务舱", 2: "头等舱"}
            cabin_cn = cgrd_cn.get(ci.get("cgrd"), "") if ci else ""
            # 航站楼：mutilstn 首末段 dportinfo/aportinfo.bsname
            # （"T2"）。多航站楼一侧才有值（乌→沪 arr 98/98 T1/T2、dep
            # 0/98——出发地单航站楼渠道下发空串），留空不造
            dep_term = str((first.get("dportinfo") or {}).get("bsname")
                           or "").strip()
            arr_term = str((last.get("aportinfo") or {}).get("bsname")
                           or "").strip()
            # 中转航站楼：中转点出发侧=第二段 dportinfo
            # （换乘后从哪栋楼走，30/52 行有值），首段到达侧兜底（通常
            # 同楼）；bsname 实测为裸楼名（「T3」/「T5」，dump 实证），
            # 与 qunar「咸阳T3」形态不同源勿混同。仅中转行落值防与
            # arr/dep 歧义。兜底改值级（调研④：dportinfo 在场
            # 但 bsname 空串时 dict 级 or 曾不回退）
            trans_term = ""
            if is_transfer and len(segs) > 1:
                trans_term = (str((segs[1].get("dportinfo") or {})
                                  .get("bsname") or "").strip()
                              or str((first.get("aportinfo") or {})
                                     .get("bsname") or "").strip())
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
                # 新决策字段（上面注释块：键路径 + dump 命中率）
                "discount": best_disc,
                "depTerminal": dep_term,
                "arrTerminal": arr_term,
                # 中转航站楼（换乘出发侧）+ 最低价政策余票数
                # （quantity 1-10 结构化紧俏度，10 疑「充足」封顶；
                # 无值不落防与 0 语义混淆）
                "transTerminal": trans_term,
                "leftTickets": best_qty,
                # 高档舱最低参考价（qunar bizPrice 同键同协议 int；
                # float 透传会让 alerter isinstance 门静默缺席）+
                # 舱别词面（bizCabin，渲染端缺省回退「公务」兼容
                # 存量行）
                **({"bizPrice": int(biz_price),
                    "bizCabin": {1: "公务", 2: "头等"}.get(biz_cgrd, "")}
                   if biz_price is not None else {}),
                # 年龄限制专享价（best_age：仅最低价政策带 nt=20 时有值）
                **({"agePolicy": best_age} if best_age else {}),
                # 机龄数字串（tuniu planeAge 同协议）+ 权益标签
                "planeAge": plane_age,
                "labels": "·".join(labels),
                # 平均延误 int 分钟（tuniu avgDelay 同协议，webui
                # 明细次行消费端已在）+ 连廊率百分数数字
                "avgDelay": avg_delay,
                "bridgeRate": bridge_rate,
                # 中转行李直挂（仅中转行置值；政策级 best_direct 主源
                # 优先，nt=31 FreeLuggage 推断源次之（免费托运→推断
                # 直挂，qunar flightMark.freeLuggage 同律），item 层
                # aset「联程值机，行李直挂」补缺；
                # 「行李代转运」落 recheck 三态；nt=103 联程明细
                # 含「行李直挂」亦为直挂证据（当前样本是单段经停行，
                # is_transfer 门控天然不触发，留作真中转带此 note 增益）；
                # 空串=未知，normalize 的 transitServiceLabel 兜底照常生效）
                "transferBaggage": (
                    "direct" if (is_transfer and (best_direct or best_freelug
                                                  or _item_direct
                                                  or _ts_direct))
                    else ("recheck" if (is_transfer and _recheck) else "")),
                # 机场三字码（mutilstn 首末段 dportinfo/aportinfo
                # .aport「URC/SHA」，dump 141/141 在场）——同城多场决策
                # 信息，五渠道键名对齐。 码值经 AIRPORT_NAME_CN
                # 归一为机场短名（与 qunar/tuniu/tongcheng 中文名同形；
                # 未收录保留码宁缺勿错——渲染端 _apt 只剥后缀转不了码）
                "depAirport": AIRPORT_NAME_CN.get(
                    str((first.get("dportinfo") or {}).get("aport")
                        or "").strip(),
                    str((first.get("dportinfo") or {}).get("aport")
                        or "").strip()),
                "arrAirport": AIRPORT_NAME_CN.get(
                    str((last.get("aportinfo") or {}).get("aport")
                        or "").strip(),
                    str((last.get("aportinfo") or {}).get("aport")
                        or "").strip()),
                # H1 第三源：AIRPORT_NAME_CN 归一前原码（DB 存量
                # 1302/1302 三字码形态，在案）——qunar/tuniu/
                # ctrip 三渠道码值源一次配齐，iata3 守卫同律
                "depAirportCode": iata3(
                    (first.get("dportinfo") or {}).get("aport")),
                "arrAirportCode": iata3(
                    (last.get("aportinfo") or {}).get("aport")),
                # 机型体量（上方 craft 循环 craftinfo.kind）+
                # 舱位字母（上方 classNoteList nt=2，随最低价政策配对）
                "planeSize": plane_size,
                "cabinCode": cabin_code,
                # 座椅倾斜角度（classinfor.seattilt，唯一未采的舱位物理
                # 参数）：结构化真值非零 89.4%、值域 100~180（180=可平
                # 躺），0 视未报不落（宁缺勿错，防与真值 0 混淆）；
                # bool 剔除（true 是 int 子类，落 1 即脏值）
                **({"seatTilt": int(ci["seattilt"])}
                   if isinstance(ci.get("seattilt"), (int, float))
                   and not isinstance(ci.get("seattilt"), bool)
                   and int(ci["seattilt"]) > 0 else {}),
                "stopCitys": ";".join(stops),
                "stopTime": (f"{stop_mins // 60}小时{stop_mins % 60}分"
                             if stop_mins > 0 else ""),
            })
            if ts_svc:
                out[-1]["transferService"] = ts_svc
        # 同班多政策只留最低价，防 TOP 名额被同班占满：
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
                    f.write((item.get("text") or "")[:4000000])
                    f.write("\n")
            self.logger.info("[ctrip] 已保存 XHR: %s", path)
        except Exception:
            pass
