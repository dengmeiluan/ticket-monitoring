"""携程机票：m.ctrip.com H5 (taro) + 手机UA + XHR 拦截

数据源接口 flightListSearchForH5 返回 JSON。
每个航班(fltitem)的 policyinfo 内含多个销售政策，
每个政策有 tprice(含税价) 与 quantity(余票)。quantity 为 null/0 表示
无票(诱饵价)，必须剔除，否则会拿到买不到的超低价。
"""
import base64
import logging
import os
import re
import json
import time
import urllib.parse
from typing import List

from core.models import FlightPrice, price_band_ok
from core.citydata import CODE_NAME as _CODE_NAME
from core.flightnorm import AIRPORT_NAME_CN
from core.intl import (INTL_CITY_NAME, airport_city_code, is_intl_route,
                       tz_offset_min)
from .base import BaseCrawler, iata2, iata3
from .challenge import classify_text

_LOG = logging.getLogger(__name__)

# pid zstd 解码依赖（fltitem[].pid=`__Zstd__|`+base64 的政策载荷）：
# 缺失时行李额采集整体跳过（爬虫其余功能不受影响），打包漏装不至于炸
try:
    from zstandard import ZstdDecompressor
except Exception:
    ZstdDecompressor = None

# pid policies.tag 的免费托运额形态（freeLuggageAmount_20）+ 手提行
# 李额孪生家族（carryOnLuggageMaxWeight_7/carryOnLuggageMaxAmount_1，
# 政策行 100% 在场，值域 KG 5/7/8 × 件 1/2）。checkinLuggageMaxAmount
# 不在本式内、值域门另挡：实测值域 {-2, 0}——0 值行与
# freeLuggageAmount_0 完全同步，「无免费托运」词面已由后者承载，
# 零增量维持不采。观察哨（r338 登记）：旧档外首例
# checkinLuggageMaxAmount_1（「托运 1 件」，1/1348 tag）——值域再扩
# （_2+）或占比上升即按「托运件数」立项（freeLuggageAmount_N 只携
# KG 维度，件数维度现无出口）
_RE_PID_FREE = re.compile(r"^freeLuggageAmount_(\d+)$")
_RE_PID_CARRY_W = re.compile(r"^carryOnLuggageMaxWeight_(\d+)$")
_RE_PID_CARRY_A = re.compile(r"^carryOnLuggageMaxAmount_(\d+)$")

# 机龄恒档粗化守卫：渠道对整年机龄恒下发 '5'（自然基线占比 0-2%，
# 恒档期逐日 100% 持续，r315 备案触发线到达）——精确 '5' 读层置空
# （落键门见 _extract_ctrip_flights），带月形态与其他整年照落；渠道
# 恢复多值下发（逐日 '5' 占比回落）即移除本常量恢复复采
_PLANEAGE_COARSE = "5"


class CtripCrawler(BaseCrawler):
    name = "ctrip"
    use_mobile = True  # 移动端 H5

    # 采集路径状态超集：base 表无 unsupported，path_note 会把它降级
    # 成 error（假失败）——往返不支持的证据必须原样落账（§5/§10 诚实
    # 数据；webui 对 unsupported 已渲染「本端不供」，非 error 面）
    PATH_STATUS = BaseCrawler.PATH_STATUS + ("unsupported",)

    # 携程 H5 机票单程列表（taro 版，用户提供的真实入口）
    URL_TPL = ("https://m.ctrip.com/html5/flight/taro/first?from=inner"
               "&tripType=ONE_WAY"
               "&dcity={from_city}&dcityName={from_name}"
               "&acity={to_city}&acityName={to_name}"
               "&ddate={date}")

    # 国际版壳（r325，调研 _scratch/intl/report_ctrip.md）：from=outer
    # 即国际壳，列表接口与国内同一条 soa2/14488 flightListSearchForH5
    # ——IATA3 直通（dccode/accode，dcid/acid 传 undefined 即可），
    # 同 XHR 键同解析器，集成=参数分支而非新爬虫。风控同一面
    # （whaleguard 只认 profile 信任度，国内国际同判，生产 profile 通用）
    URL_TPL_INTL = ("https://m.ctrip.com/html5/flight/taro/first?from=outer"
                    "&tripType=ONE_WAY"
                    "&dcity={from_city}&dcityName={from_name}"
                    "&acity={to_city}&acityName={to_name}"
                    "&ddate={date}")

    # 国际 PC 列表页（2026-10-22 实证）：国际 14488 列表业务性拒答，
    # 但 flights.ctrip.com PC 站在受信 profile 下会发 batchSearch 出
    # 真实行程列表（SHA→TYO 174 行程/2.5MB，含税价/舱位/余票/行李）。
    # 机场码先归并城市码（NRT→TYO），与日历端点同口径。
    URL_LIST_INTL = ("https://flights.ctrip.com/online/list/"
                     "oneway-{from_city}-{to_city}?depdate={date}")
    # 国内 PC 列表：H5 taro 列表在部分日期只给日历/空壳，
    # flights.ctrip.com 国内 batchSearch 仍是真实行程来源。
    URL_LIST_DOM = ("https://flights.ctrip.com/online/list/"
                    "oneway-{from_city}-{to_city}?depdate={date}"
                    "&cabin=y_s_c_f&adult=1&child=0&infant=0")

    # 仅认航班列表接口；LowestPriceSearch 是跨日期低价日历，会混入其他日期价格
    XHR_KEYS = [
        "flightListSearchForH5",
    ]

    # PC 国际列表分页/增量：batchSearch 首批全量，pull 为滚动补量
    XHR_KEYS_INTL_LIST = [
        "batchSearch",
        "international/search/api/search/batchSearch",
        "international/search/api/search/pull/",
    ]

    CITY_NAME = {
        "SZX": "深圳", "KMG": "昆明", "PEK": "北京", "BJS": "北京",
        "SHA": "上海", "PVG": "上海", "CAN": "广州", "HGH": "杭州",
        "CTU": "成都", "SIA": "西安", "CKG": "重庆", "NKG": "南京",
        "WUH": "武汉", "CSX": "长沙", "XMN": "厦门", "SYX": "三亚",
        "HAK": "海口", "LJG": "丽江", "DLU": "大理", "JHG": "西双版纳",
        "DIG": "香格里拉", "TCZ": "腾冲", "URC": "乌鲁木齐",
    }

    # 全国城市超集（r320 全量城市化）：官方字典投影补齐。旧键值保留
    # （DIG=香格里拉/SWA=汕头 旅游名语义不漂移，存量推送词面不变）
    for _c, _n in _CODE_NAME.items():
        if _c not in CITY_NAME:
            CITY_NAME[_c] = _n

    def login_url(self) -> str:
        return "https://www.ctrip.com/"

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        self.path_reset()
        # 往返诚实（§5/§10）：Ctrip 未实现回程查询，忽略 ret_date 返回
        # 单程价会被告警/走势当成往返总价（Fliggy/同程已真往返）。不发
        # 单程查询，直接以 unsupported 落账，宁缺勿错。
        if ret_date:
            self.logger.warning(
                "[ctrip] 往返明细暂不支持（返程 %s），未发起单程查询",
                ret_date)
            self.path_note(
                "TRIP", "unsupported",
                detail="往返明细暂不支持，未发起单程查询")
            return []
        # 国际分流（r325→R44b 定谳改道）：14488 列表端点对国际查询
        # 业务性拒答（请求体与国内逐字段同构仍 30212，r39_reqdiff
        # 实证），国际真价面=FlightIntlAndInlandLowestPriceSearch
        # 日历端点——独立通道 _fetch_intl，国内主流程不再带 intl 分支
        if is_intl_route(from_city, to_city):
            return self._fetch_intl(from_city, to_city, dates)
        results: List[FlightPrice] = []   # init 恢复（r324 协调）：ret_date 编辑曾连带吞行，生产 15:49 起 NameError 零落库
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
                url = self._entry_url(from_city, to_city, date)
                self.logger.info("[ctrip] GET %s", url)
                captured = self.attach_xhr_collector(page, self.XHR_KEYS)
                t_h5 = time.time()
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
                        flights.extend(self._extract_ctrip_flights(
                            item.get("text", "")))
                    # 起飞日门（§5 日期诚实）：H5 部分日期返回滚动/推荐
                    # 位行（ddate 非目标日），按请求日打标=日期错位价。
                    # 仅在行内有日期字段时过滤，无日期字段不臆造。
                    _drop_date = 0
                    if flights:
                        flights, _drop_date = self._filter_date_scope(
                            flights, date)
                        if _drop_date:
                            self.logger.warning(
                                "[ctrip] %s 剔除 %d 条非目标日起飞行"
                                "（滚动/推荐位）", date, _drop_date)
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
                        n_d = sum(1 for f in flights if not f.get("transCity"))
                        self.logger.info(
                            "[ctrip] %s 最低价 ￥%.0f（明细 %d 条：直飞 %d / 中转 %d）",
                            date, price, len(flights), n_d, len(flights) - n_d)
                        self.path_note(
                            "H5", "ok", rows=len(flights), date=date,
                            detail="m.ctrip.com H5 列表",
                            ms=int((time.time() - t_h5) * 1000))
                    else:
                        self.logger.warning("[ctrip] %s 未解析到价格", date)
                        try:
                            _body = page.inner_text("body")[:800]
                        except Exception:
                            _body = ""
                        _blocked = bool(re.search(
                            r"whaleguard|验证码|安全验证|访问验证|滑块", _body))
                        _login = bool(re.search(
                            r"登录|扫码|账号密码", _body))
                        if _blocked:
                            _detail = "风控验证页"
                        elif _drop_date:
                            _detail = ("滚动/推荐行日期不符已剔除 %d 行"
                                       % _drop_date)
                        else:
                            _detail = "H5 列表未解析到价格"
                        self.path_note(
                            "H5", "blocked" if _blocked
                            else ("login" if _login else "empty"),
                            date=date, detail=_detail,
                            ms=int((time.time() - t_h5) * 1000))
                        self._debug_snapshot(page, f"nopx_{date}")
                except Exception as e:
                    self.logger.exception("[ctrip] %s 抓取异常: %s", date, e)
                    self.path_note("H5", "error", date=date,
                                   detail=str(e)[:120],
                                   ms=int((time.time() - t_h5) * 1000))
                self._sleep()
        # H5 列表缺日时补国内 PC 列表；H5 已出数的日期不重复请求。
        missing = [d for d in dates if d not in {r.depart_date for r in results}]
        if missing:
            try:
                self.logger.info("[ctrip][dom] H5 缺 %d 日，补 PC 列表: %s",
                                 len(missing), ",".join(missing))
                results.extend(self._fetch_intl_list(
                    from_city, to_city, from_city, to_city, missing,
                    url_tpl=self.URL_LIST_DOM, label="国内"))
            except Exception as e:
                self.logger.warning("[ctrip][dom] PC 列表补采失败: %s", e)
        return results

    @staticmethod
    def _band_ok(v, intl: bool = False) -> bool:
        """价带 scope-aware 单源门（r325 INTL_DESIGN §1.3）：国内窄带
        100-50000 逐字节不变，国际行（el intl 探针）宽带 100-200000
        ——长途经济舱全档+高档舱低价窗，core.models 单源。"""
        return price_band_ok(v, el={"intl": 1} if intl else None)

    def _fetch_intl(self, from_city: str, to_city: str,
                    dates: List[str]) -> List[FlightPrice]:
        """国际=PC 航班列表优先，缺日回退日历（R44b → r360 换面）。

        R44b 时 14488 国际列表业务性拒答，只能采日历；2026-10-22 复核
        发现 PC 国际站（flights.ctrip.com）在受信 profile 下会发
        international/search/api/search/batchSearch 真列表（SHA→TYO
        174 行程/2.5MB，含税价/舱位/余票/行李/时刻）。列表优先，日历
        只补列表缺日：国际面首次具备航班维度（可同班比价/监控/走势），
        同一路由不再让「日历最低价」顶替真实航班。两边都无价=当日无数据。
        """
        # 机场→城市归并（R44c：端点键是城市级码——生产 acity=NRT
        # 机场码直传=全窗 380 行零报价实锤，同程/飞猪 _fetch_intl 同律）
        fc, tc = (airport_city_code(from_city.upper()),
                  airport_city_code(to_city.upper()))
        # 机场级航线判定：请求码与城市归并码不同（PVG→SHA/NRT→TYO）。
        # 日历端点无机场维度，城市日历价挂到机场级航线即跨机场串价
        # （PVG→NRT 的缺口被 SHA→TYO 日历价补上，混入虹桥/羽田面），
        # 机场级缺口不做日历回填（宁空勿错，逐日留空证据）。
        apt_scope = (from_city.strip().upper() != fc
                     or to_city.strip().upper() != tc)
        results = self._fetch_intl_list(from_city, to_city, fc, tc, dates)
        got = {r.depart_date for r in results}
        missing = [d for d in dates if d not in got]
        if missing:
            if apt_scope:
                self.logger.warning(
                    "[ctrip][intl] 机场级航线 %s→%s 缺 %d 日，不回填城市"
                    "日历（%s）", from_city, to_city, len(missing),
                    ",".join(missing))
                for d in missing:
                    self.path_note("日历", "empty", date=d,
                                   detail="机场级航线不回填城市日历价")
                return results
            self.logger.warning(
                "[ctrip][intl] PC 列表覆盖 %d/%d 天，日历兜底: %s",
                len(got), len(dates), ",".join(missing))
            results.extend(self._fetch_intl_calendar(
                from_city, to_city, fc, tc, missing))
        return results

    def _fetch_intl_list(self, from_city: str, to_city: str,
                         fc: str, tc: str, dates: List[str],
                         url_tpl: str = "", label: str = "国际") -> List[FlightPrice]:
        """PC 国际列表：batchSearch/pull 捕获 → 行程行解析。

        profile 未登录时 data.needUserLogin=true 且无行程——置
        login_suspect 供 main.py 登录门槛，不造假数据。pull 为滚动
        补量，行结构与 batchSearch 同构，解析器同源。
        """
        results: List[FlightPrice] = []
        with self.browser() as ctx:
            warm = self.new_page(ctx)
            try:
                warm.goto("https://flights.ctrip.com/",
                          wait_until="domcontentloaded", timeout=30000)
                warm.wait_for_timeout(2500)
            except Exception as e:
                self.logger.warning("[ctrip][intl] PC 预热失败: %s", e)
            finally:
                try:
                    warm.close()
                except Exception:
                    pass
            for date in dates:
                # 每日独立 page：上一日的 pull 迟到响应不会混进下一日
                # 的 finished 判定（多日期监控窗实测必需）
                page = self.new_page(ctx)
                captured = self.attach_xhr_collector(
                    page, self.XHR_KEYS_INTL_LIST)
                url = (url_tpl or self.URL_LIST_INTL).format(
                    from_city=fc.lower(), to_city=tc.lower(), date=date)
                self.logger.info("[ctrip][intl] GET %s", url)
                t_pc = time.time()
                try:
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=45000)
                    # 首包 batchSearch 可能只带 finished:false 空壳，真实
                    # 行程随后由 pull 补量（实测 6.7s/9.7s 两包，均 174
                    # 行）——等到「有行且 finished=true」或首包有行后
                    # 9s 宽限，既不在空壳上早退，也不为空结果干等
                    t0 = time.monotonic()
                    parsed, flights, need_login = set(), [], False
                    first_rows_at = None
                    finished = False
                    # 有行后的 9s 宽限从首行到达起算（旧实现从 goto 起算，
                    # 首包慢时会在 pull 补量前早退，实测 173→136 行）；
                    # 总等待 16s 给单日最坏情况留出 15min 栅栏余量。
                    while time.monotonic() - t0 < 16:
                        for item in list(captured):
                            u = item.get("url", "")
                            if u in parsed:
                                continue
                            parsed.add(u)
                            body = item.get("text") or ""
                            part, nl = self._extract_intl_list(body, date)
                            if part and first_rows_at is None:
                                first_rows_at = time.monotonic()
                            flights.extend(part)
                            need_login = need_login or nl
                            if not finished and re.search(
                                    r'"finished"\s*:\s*true', body):
                                finished = True
                        if finished:
                            break
                        if (flights and first_rows_at is not None
                                and time.monotonic() - first_rows_at > 9):
                            break
                        page.wait_for_timeout(600)
                    # 两包各约 2.6MB，debug 全量落盘会按日×14 膨胀数十
                    # MB；国际列表只在内存解析并落 extra 行（可溯源到
                    # 每行价格/舱位/余票/行李），这里只记捕获体积
                    self.logger.info(
                        "[ctrip][intl] %s 捕获 %d 包（%s 字节）", date,
                        len(captured),
                        ",".join(str(len(x.get("text") or ""))
                                 for x in captured))
                    # 同班多政策/两接口重叠：保留最低价（H5 同律）
                    dedup = {}
                    for f in flights:
                        k = (f["code"], f["depTime"])
                        if k not in dedup or f["price"] < dedup[k]["price"]:
                            dedup[k] = f
                    flights = list(dedup.values())
                    # 机场级路线只保留该机场：Ctrip 城市搜索 TYO 会混入
                    # HND，NRT 路由照单全收会把成田与羽田合并进趋势/
                    # 告警/同班（实测 136 行中 58 行 HND；LHR 混入
                    # LGW/STN/LCY）。城市级路线（SHA/TYO）不过滤。
                    flights, _drop_apt = self._filter_airport_scope(
                        flights, from_city, to_city)
                    if _drop_apt:
                        self.logger.info(
                            "[ctrip][intl] %s 机场级路线过滤城市内其他机场"
                            " %d 行", date, _drop_apt)
                    try:
                        _body = page.inner_text("body")[:1200]
                    except Exception:
                        _body = ""
                    if not flights and (need_login or "手机登录/注册" in _body
                                        or "账号密码登录" in _body):
                        CtripCrawler.login_suspect = True
                        self.logger.warning(
                            "[ctrip][intl] 需登录 · PC 列表需携程会话"
                            "（请在配置页「渠道登录」重登 ctrip）")
                    if not flights:
                        self.logger.warning(
                            "[ctrip][intl] %s PC 列表未解析到航班", date)
                        _blocked = bool(re.search(
                            r"whaleguard|验证码|安全验证|访问验证", _body))
                        self.path_note(
                            "PC", "blocked" if _blocked
                            else ("login" if need_login else "empty"),
                            date=date, detail=("风控验证页" if _blocked
                                               else "国际列表未解析到航班"),
                            ms=int((time.time() - t_pc) * 1000))
                        self._sleep()
                        continue
                    CtripCrawler.login_suspect = False
                    self.path_note("PC", "ok", rows=len(flights), date=date,
                                   detail="flights.ctrip.com %s列表" % label,
                                   ms=int((time.time() - t_pc) * 1000))
                    best = min(flights, key=lambda f: f["price"])
                    results.append(FlightPrice(
                        platform=self.name,
                        from_city=from_city, to_city=to_city,
                        depart_date=date, price=best["price"],
                        flight_no=best.get("name", ""),
                        depart_time=best.get("depTime", ""),
                        arrive_time=best.get("arrTime", ""),
                        extra=json.dumps(flights, ensure_ascii=False),
                    ))
                    n_d = sum(1 for f in flights if not f.get("transCity"))
                    self.logger.info(
                        "[ctrip][intl] %s 最低含税价 ￥%.0f（明细 %d 条："
                        "直飞 %d / 中转 %d）", date, best["price"],
                        len(flights), n_d, len(flights) - n_d)
                except Exception as e:
                    self.logger.exception(
                        "[ctrip][intl] %s PC 抓取异常: %s", date, e)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                # 逐日整页导航本身已天然限速（10s 级），不再叠加
                # 5–15s 随机 sleep——14 日窗曾因此额外多花 2–3 分钟
                time.sleep(0.5)
        return results

    @staticmethod
    def _filter_airport_scope(flights: list, from_city: str,
                              to_city: str):
        """机场级路线只保留该机场；返回 (flights, dropped)。

        城市级路线（SHA/TYO）不筛：Ctrip 城市搜索本就覆盖同城多场。
        机场级路线（NRT/LHR/PVG）必须筛——CTrip TYO 会混入 HND，
        LHR 会混入 LGW/STN/LCY，照单全收会让趋势/告警/同班比价
        把“上海→成田”写成“上海→东京”并混入羽田价格。
        """
        dropped = 0
        for key, raw in (("depAirportCode", from_city),
                         ("arrAirportCode", to_city)):
            want = str(raw or "").upper()
            if not want or airport_city_code(want) == want:
                continue
            before = len(flights)
            flights = [f for f in flights
                       if str(f.get(key) or "").upper() == want]
            dropped += before - len(flights)
        return flights, dropped

    @staticmethod
    def _filter_date_scope(flights: list, date: str):
        """国内 H5 起飞日门：行内日期异于请求日即剔；返回 (kept, dropped)。

        渠道在部分日期返回滚动/推荐位行（dateinfo.ddate 非目标日），
        解析器照收后按请求日打标=日期错位价（§5 诚实数据）。只在行内
        确有日期字段（depDate/date，解析器原生输出 depDate）时过滤：
        无日期字段的行保持原行为，不臆造日期。非法日期串不硬判。
        """
        dropped = 0
        kept = []
        for f in flights:
            raw = ""
            if isinstance(f, dict):
                for k in ("depDate", "date"):
                    v = f.get(k)
                    if v:
                        raw = str(v).strip()
                        break
            day = raw[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and day != date:
                dropped += 1
                continue
            kept.append(f)
        return kept, dropped

    @staticmethod
    def _extract_intl_list(body: str, date: str):
        """PC 国际列表 batchSearch/pull → (统一航班行, needUserLogin)。

        行程顶层 flightSegments[].flightList 为全部航段（直飞 1 段、
        中转多段）。priceList 每项一个销售政策，含税总价=
        adultPrice+adultTax；ticketCount 缺省=渠道未下发（实测 363/489
        行缺省且页面照常展示），不是无票，显式<=0 才剔除。价格取
        目标日起飞、价带内最低政策；舱位看 priceUnitList.cabinClass
        （S=超级经济，itineraryCabin=Y-@S 是混合舱不能直接当 S）；
        余票/行李/共享承运随最低价政策配对。只认 depDate==目标日。
        """
        try:
            obj = json.loads(body)
        except Exception:
            return [], False
        data = (obj or {}).get("data") or {}
        if not isinstance(data, dict):
            return [], False
        need_login = bool(data.get("needUserLogin"))
        out = []
        for it in data.get("flightItineraryList") or []:
            if not isinstance(it, dict):
                continue
            segs = [s for s in (it.get("flightSegments") or [])
                    if isinstance(s, dict)]
            legs = [f for s in segs for f in (s.get("flightList") or [])
                    if isinstance(f, dict)]
            if not legs:
                continue
            first, last = legs[0], legs[-1]
            dd = str(first.get("departureDateTime") or "")
            ad = str(last.get("arrivalDateTime") or "")
            if len(dd) < 16 or len(ad) < 16 or dd[:10] != date:
                continue
            best = None
            for p in it.get("priceList") or []:
                if not isinstance(p, dict):
                    continue
                q = p.get("ticketCount")
                if q is not None:
                    try:
                        if int(q) <= 0:
                            continue
                    except (TypeError, ValueError):
                        pass
                try:
                    total = (float(p.get("adultPrice") or 0)
                             + float(p.get("adultTax") or 0))
                except (TypeError, ValueError):
                    continue
                if not price_band_ok(total, el={"intl": 1}):
                    continue
                if best is None or total < best[0]:
                    best = (total, p)
            if best is None:
                continue
            price, pol = best
            cabin_classes, seat_classes = [], []
            for u in pol.get("priceUnitList") or []:
                for fs in (u or {}).get("flightSeatList") or []:
                    cc = str(fs.get("cabinClass") or "").upper()
                    sc = str(fs.get("seatClass") or "").upper()
                    if cc and cc not in cabin_classes:
                        cabin_classes.append(cc)
                    if sc and sc not in seat_classes:
                        seat_classes.append(sc)
            visa = {}
            try:
                visa = json.loads(pol.get("luggageVisaKey") or "{}")
            except (TypeError, ValueError):
                visa = {}
            visa_legs = ((visa.get("criteria") or {}).get("FlightInfoList")
                         or [])
            if not seat_classes:
                seat_classes = [str(v.get("SeatClass") or "").upper()
                                for v in visa_legs
                                if v.get("SeatClass")]
            if not cabin_classes:
                cabin_classes = [str(v.get("Cabin") or "").upper()
                                 for v in visa_legs if v.get("Cabin")]
            if cabin_classes and all(c == "S" for c in cabin_classes):
                cabin_cn = "超级经济舱"
            elif cabin_classes and all(c in ("Y", "S")
                                       for c in cabin_classes):
                cabin_cn = ("经济舱" if all(c == "Y" for c in cabin_classes)
                            else "经济舱/超经")
            elif cabin_classes and all(c == "C" for c in cabin_classes):
                cabin_cn = "公务舱"
            elif cabin_classes and all(c == "F" for c in cabin_classes):
                cabin_cn = "头等舱"
            else:
                cabin_cn = "/".join(cabin_classes)
            cabin_code = "/".join(seat_classes)
            share, share2 = "", ""
            for idx, vl in enumerate(visa_legs):
                opn = str(vl.get("OperatingFlightNo") or "").strip()
                mfn = str(vl.get("MarketingFlightNo") or "").strip()
                if opn and mfn and opn != mfn:
                    if idx == 0:
                        share = opn
                    elif idx == 1:
                        share2 = opn
            bag = ""
            for dl in ((pol.get("baggage") or {}).get("dataList") or []):
                cb = (((dl or {}).get("adultBaggage") or {})
                      .get("checkedBaggage") or {})
                c = str(cb.get("baggageContent") or "").strip()
                if c:
                    bag = c
                    break
            dep_ap = str(first.get("departureAirportShortName")
                         or first.get("departureAirportName")
                         or first.get("departureAirportCode") or "")
            arr_ap = str(last.get("arrivalAirportShortName")
                         or last.get("arrivalAirportName")
                         or last.get("arrivalAirportCode") or "")
            dep_apc = str(first.get("departureAirportCode") or "").upper()
            arr_apc = str(last.get("arrivalAirportCode") or "").upper()
            fnos = [str(f.get("flightNo") or "").strip()
                    for f in legs if f.get("flightNo")]
            if not fnos:
                continue
            dep_d, arr_d = dd[:10], ad[:10]
            try:
                from datetime import datetime as _dt
                _xday = (_dt.strptime(arr_d, "%Y-%m-%d")
                         - _dt.strptime(dep_d, "%Y-%m-%d")).days
            except Exception:
                _xday = 0
            cross = ({0: "", 1: "+1天", 2: "+2天"}.get(_xday)
                     or (f"+{_xday}天" if _xday > 0 else ""))
            # DST 按航班日取真历法（抓取日 10 月仍夏令时会让 LHR
            # 11 月航班错 60 分钟；base._stamp_intl 同律）
            tz_dep = tz_offset_min(dep_apc, when=date)
            tz_arr = tz_offset_min(arr_apc, when=date)
            dur_min = 0
            try:
                dur_min = int(segs[0].get("duration") or 0)
            except (TypeError, ValueError):
                dur_min = 0
            if dur_min <= 0:
                try:
                    from datetime import datetime as _dt
                    t0 = _dt.strptime(dd[:19], "%Y-%m-%d %H:%M:%S")
                    t1 = _dt.strptime(ad[:19], "%Y-%m-%d %H:%M:%S")
                    dur_min = int((t1 - t0).total_seconds() // 60)
                    if tz_dep is not None and tz_arr is not None:
                        dur_min -= (tz_arr - tz_dep)
                except Exception:
                    dur_min = 0
            lay_min = 0
            lay_src = "ct"
            _tds = []
            for l in legs[:-1]:
                try:
                    _v = int(l.get("transferDuration") or 0)
                except (TypeError, ValueError):
                    _v = 0
                _tds.append(_v)
            if _tds and all(v > 0 for v in _tds):
                lay_min = sum(_tds)
            else:
                lay_src = "times"
                try:
                    from datetime import datetime as _dt
                    for _i in range(len(legs) - 1):
                        _a = _dt.strptime(
                            str(legs[_i].get("arrivalDateTime"))[:19],
                            "%Y-%m-%d %H:%M:%S")
                        _b = _dt.strptime(
                            str(legs[_i + 1].get("departureDateTime"))[:19],
                            "%Y-%m-%d %H:%M:%S")
                        lay_min += max(0, int((_b - _a).total_seconds()
                                              // 60))
                except Exception:
                    lay_min = 0
            dur = f"{dur_min // 60}时{dur_min % 60}分" if dur_min else ""
            is_transfer = len(legs) > 1
            _lay2dep = _tgd = ""
            if is_transfer:
                _b2dd = str(legs[1].get("departureDateTime") or "")
                if len(_b2dd) >= 16 and _b2dd[11:16] != dd[11:16]:
                    _lay2dep = _b2dd[11:16]
                if _b2dd[:10] > dep_d:
                    _tgd = _b2dd[:10]
            trans = ""
            trans_terminal = ""
            if is_transfer:
                trans = str(first.get("arrivalCityName") or "").strip()
                trans_terminal = str(first.get("arrivalTerminal") or "")
            plane = str(first.get("aircraftName") or "").strip()
            plane_size = {"L": "大型机", "M": "中型机",
                          "S": "小型机"}.get(
                              str(first.get("aircraftSize") or "").upper(), "")
            plane2 = ""
            plane_size2 = ""
            if is_transfer:
                plane2 = str(legs[1].get("aircraftName") or "").strip()
                plane_size2 = {"L": "大型机", "M": "中型机",
                               "S": "小型机"}.get(
                                   str(legs[1].get("aircraftSize")
                                       or "").upper(), "")
            left = None
            q = pol.get("ticketCount")
            if q is not None:
                try:
                    if int(q) > 0:
                        left = int(q)
                except (TypeError, ValueError):
                    left = None
            tax = 0.0
            try:
                tax = float(pol.get("adultTax") or 0)
            except (TypeError, ValueError):
                tax = 0.0
            row = {
                "price": price,
                "code": "/".join(fnos),
                "name": fnos[0],
                "depTime": dd[11:16],
                "arrTime": ad[11:16],
                "depDate": dep_d,
                "arrDate": arr_d,
                "totalDuration": dur,
                "cabin": cabin_cn,
                "depAirport": dep_ap,
                "arrAirport": arr_ap,
                "depAirportCode": iata3(dep_apc),
                "arrAirportCode": iata3(arr_apc),
                "intl": 1,
                **({"tz_dep": tz_dep, "tz_arr": tz_arr}
                   if tz_dep is not None and tz_arr is not None
                   and tz_dep != tz_arr else {}),
                **({"transCity": trans} if trans else {}),
                **({"crossDayDesc": cross} if cross else {}),
                **({"layover": lay_min} if lay_min else {}),
                **({"lay2dep": _lay2dep} if _lay2dep else {}),
                **({"transGoDate": _tgd} if _tgd else {}),
                **({"layoverSrc": lay_src} if lay_min else {}),
                **({"plane": plane} if plane else {}),
                **({"planeSize": plane_size} if plane_size else {}),
                **({"plane2": plane2} if plane2 else {}),
                **({"planeSize2": plane_size2} if plane_size2 else {}),
                **({"shareCarrier": share} if share else {}),
                **({"shareCarrier2": share2} if share2 else {}),
                **({"airlineCode": iata2(
                    first.get("marketAirlineCode"))}
                   if iata2(first.get("marketAirlineCode")) else {}),
                **({"depTerminal": str(first.get("departureTerminal"))}
                   if first.get("departureTerminal") else {}),
                **({"arrTerminal": str(last.get("arrivalTerminal"))}
                   if last.get("arrivalTerminal") else {}),
                **({"transTerminal": trans_terminal}
                   if trans_terminal else {}),
                **({"cabinCode": cabin_code} if cabin_code else {}),
                **({"baggage": bag} if bag else {}),
                **({"leftTickets": left} if left is not None else {}),
                **({"tax": tax} if tax > 0 else {}),
            }
            out.append(row)
        return out, need_login

    @staticmethod
    def _empty_calendar_status(body: str, url: str = "") -> str:
        """Empty calendar result: login/blocked evidence must not be empty."""
        sig = classify_text(body, url)
        return sig.status if sig else "empty"

    def _fetch_intl_calendar(self, from_city: str, to_city: str,
                             fc: str, tc: str,
                             dates: List[str]) -> List[FlightPrice]:
        """国际=日历兜底（R44b）：壳页自动加载的
        FlightIntlAndInlandLowestPriceSearch 日历（soa2/15380）——
        受信 profile 200 出价，逐日 price/totalPrice/transportPrice
        （税费构成）。采集=壳 URL 直达日历自发请求+收集器捕获，目标
        日逐行匹配（/Date(毫秒+0800)/ 还原，不混窗—— domestic
        LowestPriceSearch 混日期教训同律）；price=0 无报价日剔除
        （宁缺勿错）。日历无时刻语义：depTime/arrTime 结构化占位
        空串（飞猪/同程日历行律），intl=1 直接落键（无 tz 可戳）。"""
        results: List[FlightPrice] = []
        with self.browser() as ctx:
            page = self.new_page(ctx)
            try:
                page.goto("https://m.ctrip.com/html5/",
                          wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
            except Exception as e:
                self.logger.warning("[ctrip] 预热失败: %s", e)
            for date in dates:
                url = self._entry_url(fc, tc, date)
                self.logger.info("[ctrip][intl] GET %s", url)
                captured = self.attach_xhr_collector(page, [
                    "FlightIntlAndInlandLowestPriceSearch"])
                t_cal = time.time()
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(9000)
                    self._dump_xhr(captured, f"ctrip_intlcal_{date}")
                    # 国际列表/日历对匿名会话会弹「手机登录/注册」；
                    # 服务器异常则不是登录问题，单独记录不冒充已登录。
                    try:
                        _body = page.inner_text("body")[:1200]
                    except Exception:
                        _body = ""
                    _page_url = str(getattr(page, "url", ""))
                    _cal_status = self._empty_calendar_status(_body, _page_url)
                    if _cal_status == "login":
                        CtripCrawler.login_suspect = True
                        self.logger.warning(
                            "[ctrip][intl] 需登录 · 国际列表需携程会话"
                            "（请在配置页「渠道登录」重登 ctrip）")
                    elif _cal_status == "blocked":
                        self.logger.warning(
                            "[ctrip][intl] %s 日历页命中人机/访问验证",
                            date)
                    elif "服务器发生异常" in _body:
                        self.logger.warning(
                            "[ctrip][intl] %s 渠道返回服务器异常", date)
                    flights = []
                    for item in captured:
                        flights.extend(self._extract_intl_calendar(
                            item.get("text", ""), date))
                    if not flights:
                        self.logger.warning(
                            "[ctrip][intl] %s 未拿到日历价", date)
                        self.path_note(
                            "日历", _cal_status, date=date,
                            detail=("登录/验证页，非空结果"
                                    if _cal_status != "empty" else
                                    "国际日历未返回该日报价"),
                            ms=int((time.time() - t_cal) * 1000))
                        self._sleep()
                        continue
                    best = min(flights, key=lambda f: f["price"])
                    self.path_note("日历", "calendar", rows=len(flights),
                                   date=date,
                                   detail="仅日历最低价，无航班明细",
                                   ms=int((time.time() - t_cal) * 1000))
                    results.append(FlightPrice(
                        platform=self.name,
                        from_city=from_city, to_city=to_city,
                        depart_date=date, price=best["price"],
                        flight_no="", depart_time="", arrive_time="",
                        extra=json.dumps(flights, ensure_ascii=False),
                    ))
                    self.logger.info(
                        "[ctrip][intl] %s 日历最低含税价 ￥%.0f（%d 行）",
                        date, best["price"], len(flights))
                except Exception as e:
                    self.logger.exception(
                        "[ctrip][intl] %s 抓取异常: %s", date, e)
                self._sleep()
        return results

    @staticmethod
    def _extract_intl_calendar(body: str, date: str) -> list:
        """国际日历捕获体 → 目标日元素行。departDate=/Date(毫秒+0800)/
        epoch 按报文自带 +0800 锚定还原（不用本地时区——UTC 运行环境
        解出前一日=目标日全等匹配漏空，CI 实锤）；price=0 无报价剔除；
        transportPrice>0 落 tax（税费构成透传，消费端「含税」展示用）。"""
        import re
        from datetime import datetime, timedelta, timezone
        try:
            data = json.loads(body)
        except (TypeError, ValueError):
            return []
        out = []
        _tz8 = timezone(timedelta(hours=8))
        for row in (data or {}).get("priceList") or []:
            if not isinstance(row, dict):
                continue
            m = re.search(r"/Date\((\d+)", str(row.get("departDate") or ""))
            if not m:
                continue
            day = datetime.fromtimestamp(
                int(m.group(1)) / 1000, tz=_tz8).strftime("%Y-%m-%d")
            if day != date:
                continue   # 只取目标日（不混窗）
            total = row.get("totalPrice") or row.get("price") or 0
            try:
                total = float(total)
            except (TypeError, ValueError):
                continue
            if not price_band_ok(total, el={"intl": 1}):
                continue
            # 观察哨：row.flag=「当月最低价日」渠道高亮标记（双捕获独立
            # 复证：flag=1 行全为月最低价、无 flag 月份 0）。缓采挂哨不
            # 落地——本函数只取目标日行（不混窗），flag 的信息量在「哪天
            # 是月最低」，与已在产的 trendGo 改期窗口出口语义重叠，单独
            # 落一标记需连带整月价族才可读。翻身条件：trendGo 出口若对
            # 国际面断供/覆盖不足，再评估以 flag 为锚的月最低价提取。
            el = {"price": total, "name": "日历最低价", "code": "",
                  "depDate": date,
                  # 结构化占位键（同飞猪/同程日历行律，R22）
                  "depTime": "", "arrTime": "", "intl": 1}
            try:
                tax = float(row.get("transportPrice") or 0)
            except (TypeError, ValueError):
                tax = 0.0
            if tax > 0:
                el["tax"] = tax
            out.append(el)
        return out

    def _entry_url(self, from_city: str, to_city: str, date: str) -> str:
        """入口 URL 单源（r325 国际分流）：国际航线（core.intl 自动
        判定）走 from=outer 国际壳。城市显示名 CITY_NAME → 国际字典
        → 裸码三级回退（名字只进壳 URL 做展示，真正查询参数是 14488
        请求体里的 dccode/accode IATA 码，直通零映射）。"""
        tpl = (self.URL_TPL_INTL if is_intl_route(from_city, to_city)
               else self.URL_TPL)

        def _name(code: str) -> str:
            c = str(code).upper()
            return self.CITY_NAME.get(c) or INTL_CITY_NAME.get(c) or code

        return tpl.format(
            from_city=from_city.upper(),
            to_city=to_city.upper(),
            from_name=urllib.parse.quote(_name(from_city)),
            to_name=urllib.parse.quote(_name(to_city)),
            date=date,
        )

    def _pick_lowest(self, captured: list, intl: bool = False) -> float | None:
        prices: list = []
        for item in captured:
            prices.extend(self._extract_ctrip_prices(item.get("text", "")))
        # 下限与全链路价带单源 PRICE_MIN=100 一致，防裸价半截行
        # （r325 scope-aware：国际行走 _band_ok 宽带档）
        prices = [p for p in prices if self._band_ok(p, intl)]
        return float(min(prices)) if prices else None

    @staticmethod
    def _pid_payload(item):
        """pid zstd 载荷解码单源（_pid_free_kgs 消费）：
        `__Zstd__|`+base64+zstd → dict，任一门失败返回 None（宁缺勿
        错）。decompressobj 不依赖帧头内嵌内容尺寸（decompress() 在
        渠道改压缩参数去尺寸头时全线静默失效）。

        观察哨（pid 顶域恒值键）：containTaxFuel（价含税燃油）与
        issupermember（会员价）现恒 false 占位——任一翻 true 即裸价/
        会员价口径事件，先词面/价位互证再动口径（键名推断不构成
        采/改依据）。

        观察哨（pid.policies 恒值族，r308 渠道调研 317 政策×6 dump
        值域普查）：bprice（商务价位）与 bginfo（行李位）恒空、
        young（青年资格）恒 false——翻非零即按「pid 政策级公务价/
        行李额/青年价」立项调研（现行李额只走 tag 家族 freeLuggage
        Amount_*，公务价只走 policyinfo.cgrd，政策级源是另一语义域）。
        同族恒值族（InvoiceType/MaxPCount/… 26 键）值域普查备案不逐
        键挂哨，全量键 diff 复检时一并复验。

        观察哨（pid policies.proinfolst 产品码族，r324 渠道调研 245
        政策全量值域）：["Normal"]/["AirlineMarketing"]/
        ["BusinessPriority","StandardPrice",…]/["WeakLimitedProduct",
        "LimitedAirlineMembership",…]/["SplicingNfd"]——英文内部旗标
        零中文词面整族不采；WeakLimitedProduct/LimitedAirline
        Membership 的语义已被 nt=3 classNoteList 限定词面（限航司
        会员/限协议等）承载。触发条件：任一产品码与渠道自带中文词面
        （root.filterlst 字典条目或行内 aset/fnotelst 独占词）同现且
        该词无既有出口，按 nt=3 同律评估收编；纯英文码出现维持不采。"""
        pid = item.get("pid")
        if (not isinstance(pid, str) or not pid.startswith("__Zstd__|")
                or ZstdDecompressor is None):
            return None
        try:
            blob = base64.b64decode(pid[len("__Zstd__|"):], validate=True)
            obj = json.loads(
                ZstdDecompressor().decompressobj()
                .decompress(blob).decode("utf-8"))
        except Exception:
            _LOG.debug("ctrip pid 解码失败（跳过）", exc_info=True)
            return None
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _pid_free_kgs(item) -> list:
        """pid zstd 载荷 → [(price, grade, free_kg, carry_kg, carry_pc), ...]
        候选表。

        pid=`__Zstd__|`+base64+zstd 的政策载荷（恒在，dump 实测全量可
        解），trlinfos[].policies 为 dict：price/grade/tag[]，tag 内
        freeLuggageAmount_N 免费托运额与 carryOnLuggageMax{Weight,
        Amount}_N 手提行李额（每政策恒 4 tag 家族各 1，政策行 100%
        在场）。四门守卫：前缀校验 / 依赖与解码失败静默 / tag 正则 /
        值域（托运 0-50；手提 KG 1-20、件 1-9——观测 5/7/8×1/2，超界
        宁缺勿错）。任一门失败返回空表——宁缺勿错，行李额随政策走，
        错配即把别的政策的额挂到本行误导。手提额与托运额独立判定：
        家族缺一侧时该侧不落、另一侧照常（部分在场形态防御）。
        """
        obj = CtripCrawler._pid_payload(item)
        if obj is None:
            return []
        out = []
        trlinfos = obj.get("trlinfos")
        if not isinstance(trlinfos, list):
            return []
        for tr in trlinfos:
            pol = tr.get("policies") if isinstance(tr, dict) else None
            if not isinstance(pol, dict):
                continue
            try:
                pp = float(pol.get("price"))
            except (TypeError, ValueError):
                continue
            pg = str(pol.get("grade") or "").strip()
            if not pg:
                continue
            kg = cw = ca = None
            tags = pol.get("tag")
            if isinstance(tags, list):
                for t in tags:
                    _ts = str(t)
                    # 家族内首现优先（Soldier P2-2：同行同家族重复 tag
                    # 旧取首个——末个覆写是防御面漂移）
                    if kg is None and (m := _RE_PID_FREE.match(_ts)):
                        kg = int(m.group(1))
                    elif cw is None and (m := _RE_PID_CARRY_W.match(_ts)):
                        cw = int(m.group(1))
                    elif ca is None and (m := _RE_PID_CARRY_A.match(_ts)):
                        ca = int(m.group(1))
            if kg is not None and not 0 <= kg <= 50:
                kg = None
            if cw is not None and not 1 <= cw <= 20:
                cw = None
            if ca is not None and not 1 <= ca <= 9:
                ca = None
            if kg is not None or (cw is not None and ca is not None):
                out.append((pp, pg, kg, cw, ca))
        return out

    # 观察哨（item.notes 全族，r313 渠道调研四 dump 两代复验）：
    # notetype 消费现况=104（高风险政策价 zstd 载荷，_risk_tags）/
    # 105（诱饵价 showPrice，_lure_price_tag）；nt=2「火车替代」
    # 中文词面（notecnt「衢州距离上海火车约1小时57分钟」形，每 dump
    # 0~1 条挂个别航班行）暂不采——挂行级语义未证（航线级事实落在
    # 单一行有错配风险）。翻身条件：渠道 UI 核实为「航线有高铁替代
    # X时X分可达」类航线级提示，或复现面升至常规航线可见档，届时按
    # 响应级事实落报告注记而非行级键。nt=6（低频 1-2 条/份）值域为
    # 区间串 '4-6'/'4-12'，语义未证（疑似成团人数域，与已收
    # LimitedPassengerNumPolicy 同域）——观察哨：dump 出现与 nt=20
    # 同现互证或渠道 UI 词面实证，即按 nt=20 文案源同律评估收编；
    # nt=4 混合舱位哨（r333 走查维持）：词面「经济舱+公务舱」
    # （classinfor 两元素 cgrd=(0,2)，10-05 实锤 2 政策行均行内最低
    # 价、两段 meal 全空=真实渠道词面非解析伪影）——若跨 dump 复现
    # ≥2 翻身，按「多舱位混合产品」词面直落 labels 评估；fresh 代
    # 4 dump 零复现维持观察。intlcal 日历通道结构性无 nt 概念，
    # 不在走查范围。其余 nt（15/25/30）无词面或营销 churn，整族
    # 维持不采。观察哨（r338 登记新 nt=100）：3 行/2530 全直飞行、
    # notecnt 恒 "1" 无词面——值翻非 "1"、现配套中文词面、或与已知
    # 决策域键同现互证，即按 nt 家族同律立项。
    @staticmethod
    def _risk_tags(item) -> list:
        """nt=104 zstd 载荷 → [price, ...]（limitTag=HighRiskPolicy 条目价）。

        notes notetype=104 的 notecnt=裸 base64+zstd 行级报价载荷
        （pid 的 __Zstd__| 前缀门在此不适用）；items.priceInfoList 是
        双层 JSON 字符串，二次解析后每条 price/grade/limitTag/policyId。
        limitTag 值域 {"",LimitedAgePolicy,HighRiskPolicy}：LimitedAge
        Policy 已由 nt=20 文案源消费（同族同现、nt=20 自带细分词面），
        此处只出口 HighRiskPolicy 新语义。守卫同 _pid_free_kgs：依赖
        缺失/解码失败静默（任一门失败该 note 跳过）、双层结构校验、
        白名单值——宁缺勿错。
        """
        out = []
        for no in item.get("notes") or []:
            if not isinstance(no, dict) or no.get("notetype") != 104:
                continue
            if ZstdDecompressor is None:
                return []
            try:
                obj = json.loads(
                    ZstdDecompressor().decompressobj()
                    .decompress(base64.b64decode(
                        str(no.get("notecnt") or ""), validate=True))
                    .decode("utf-8"))
                pil = json.loads(
                    (obj.get("items") or {}).get("priceInfoList") or "")
            except Exception:
                _LOG.debug("ctrip nt=104 解码失败（风险标记跳过）",
                           exc_info=True)
                continue
            if not isinstance(pil, list):
                continue
            for p in pil:
                if (isinstance(p, dict)
                        and p.get("limitTag") == "HighRiskPolicy"):
                    try:
                        out.append(float(p.get("price") or 0))
                    except (TypeError, ValueError):
                        continue
        return out

    @staticmethod
    def _lure_price_tag(item, min_price) -> tuple:
        """nt=105 展示价透明标记：showPrice（渠道列表展示价，plain
        JSON 非 zstd）与行最低有票 tprice 背离、且背离值 ∈ nt=104
        items.FILTED_PRICES（渠道过滤价清单）时，展示价是不可购诱饵价
        （点进必涨价）——返回 (labels 词面, showPrice int)。词面进
        labels（PNG 总表图列/明细 title/CSV 通道），数值走独立键
        lurePrice（webui 价格格徽标，riskPolicy 同构三端协议）。守卫
        三件套：FILTED_PRICES 数值等值匹配（容差 0.01；源形态是
        '2767.0' 浮点串，逐字比对会被形态差误杀）、背离幅度 ≤5%
        （实证域 0.40%–3.00%，超界形态未证宁缺勿错）、任一解码失败
        静默跳过（_risk_tags 四门纪律同款）。"""
        if min_price is None:
            return "", None
        show = None
        for no in item.get("notes") or []:
            if not isinstance(no, dict) or no.get("notetype") != 105:
                continue
            try:
                show = float(json.loads(
                    str(no.get("notecnt")) or "{}").get("showPrice") or 0)
            except Exception:
                return "", None
            break
        if not show or abs(show - min_price) < 0.01:
            return "", None
        if abs(show - min_price) / min_price > 0.05:
            return "", None
        for no in item.get("notes") or []:
            if not isinstance(no, dict) or no.get("notetype") != 104:
                continue
            if ZstdDecompressor is None:
                return "", None
            try:
                obj = json.loads(
                    ZstdDecompressor().decompressobj()
                    .decompress(base64.b64decode(
                        str(no.get("notecnt") or ""), validate=True))
                    .decode("utf-8"))
                fp = str((obj.get("items") or {}).get("FILTED_PRICES")
                         or "")
            except Exception:
                continue
            for t in fp.split(","):
                try:
                    if abs(float(t) - show) < 0.01:
                        return f"页面价￥{show:g}不可购", int(show)
                except ValueError:
                    continue
        return "", None

    @staticmethod
    def _alliance_tags(root, fnos: list) -> list:
        """根级 allilst 航盟词面：行航班号二字码 ∈ airs 时落盟名
        （白名单透传不自解析）。airs 只列本响应内出现过的航司（部分
        字典）——未列不得推判「无联盟」，仅正向落词；未知盟名宁缺勿
        错。直飞行落单盟，中转两段异盟齐落（labels 去重自洽）。"""
        out = []
        if not isinstance(root, dict):
            return out
        codes = {str(f)[:2].upper() for f in fnos if f}
        for al in root.get("allilst") or []:
            if not isinstance(al, dict):
                continue
            name = str(al.get("alliname") or "").strip()
            if name not in ("天合联盟", "星空联盟", "寰宇一家"):
                continue
            airs = {str(a).strip().upper() for a in al.get("airs") or []}
            if airs & codes and name not in out:
                out.append(name)
        return out

    def _extract_ctrip_flights(self, text: str, intl: bool = False) -> list:
        """携程航班明细（统一 schema）。

        fltitem[].mutilstn[] = 航段：basinfo.flgno=航班号、
        dateinfo.ddate/adate=完整起降时刻、aportinfo.city=到达城市；
        多段即中转。seg 内 fsitem[]（{"city":"宜昌","stopTime":45,...}，
        dump 实证）= 经停点，在场是「经停」不是「中转」，不改 mutilstn
        中转判定，只补 stopCitys/stopTime 原始字段。价格取 policyinfo[]
        中 quantity>0 的最低 tprice。响应根有 dict / list 两种形态。
        intl（r325）：国际航线档——价带走 _band_ok 宽带（商务舱
        >5 万合法），解析器其余逻辑同源零分支（同接口实证）。
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
            # 观察哨（dateinfo 恒值族，r313 渠道调研 6 dump 全量恒值）：
            # dateinfo.status/plandeptime 恒 null、atrange/dtrange 恒空——
            # status 翻非空即「航班状态（延误/取消）」语义事件，届时按
            # 行级状态键立项；pid.mileageOffsetExchangeAmount/Id 恒 0，
            # 翻非零即「里程抵扣」事件。全量键 diff 时一并复验。
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
            # 观察哨（pid 聚合推荐旗标，c330 渠道调研 4 dump 值域普查）：
            # pid.aggRecommend/isaggrecommend（2/88 True）=「NearFlight」
            # 临近航班推荐位行，其 basinfo.flgno=None 恰被上方 fnos 门
            # 自然丢弃——推荐位行不混窗，正确性无虞。翻身条件：True 行
            # 翻成带航班号形态（fnos 门放行）即推荐行混窗事件，须复核
            # ddate 与查询日的错位面（过期滚动返回同族律）。
            # 共享航班实际承运（仅展示不入指纹）：首段 basinfo
            # ishared=true 时 crerflgno=实际执飞航班号（dump 实证
            # 3U5276→MU5700，共享行 100% 在场）
            _b0 = first.get("basinfo") or {}
            share = (str(_b0.get("crerflgno") or "").strip()
                     if _b0.get("ishared") else "")
            # 二段及以后实际承运（goal 轮调研唯一增量，旧代 3 例稀疏
            # 形态 MU8201→KN5977；新代 0/96）：ishared 门+非空双门
            # 宁缺勿错，多段共享段序「/」连接；直飞行/未共享段/空串
            # 段均无键（采集先行，消费随出勤——fliggy _via 备案同族）
            _seg_shares = []
            for s in segs[1:]:
                _sb = s.get("basinfo") or {}
                if _sb.get("ishared"):
                    _sc = str(_sb.get("crerflgno") or "").strip()
                    if _sc:
                        _seg_shares.append(_sc)
            share2 = "/".join(_seg_shares)
            # 航司二字码：basinfo.aircode 渠道原生词面（调研 dump 268/268
            # 段恒在，与 flgno 前缀恒等但不走派生——原生源优先，fliggy
            # 无原生源才派生），iata2 守卫单源拒脏形，无值不落键
            _ac = iata2(_b0.get("aircode"))
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
            # 观察哨（nt=31 词面域）：FreeLuggage/FreeRRE 已消费，同族新
            # 词面 TransitLowestWeight/LowestPrice/TR 现为英文内部码零词面
            # 不采——出现配套中文词面或与 pid freeLuggage/中转价位可互证
            # 形态时按「中转最低行李额/最低价」决策域调研。
            # r321 复核增补：ItineraryFloor 首现（6/168 政策行，与
            # TransitLowestWeight/LowestPrice/TR 并现）同为英文内部码
            # 零词面，并入本哨家族表
            best_disc = ""   # 最低价政策的折扣（随价配对，与舱位同律）
            best_qty = None   # 最低价政策的余票数（quantity 1-10）
            biz_price = None   # 高档舱（公务/头等）最低参考价
            biz_cgrd = None   # 胜出政策的舱别码（1/2=高档舱，词随 cgrd_cn）
            refund_free = False   # 最低价政策带「航变免费退改」
            hotel_free = False   # 最低价政策 nt=10 / aset「中转住宿」带「中转免费住宿」
            best_age = ""   # 最低价政策的年龄限制（「限青年/限老年/限年龄/限学生」）
            # pid zstd 载荷的行李额候选表（数字托运额随政策走）：
            # 解码失败/依赖缺失返回空表，消费在下方最低价政策配对处
            pid_pols = self._pid_free_kgs(item)
            # 观察哨（policyinfo.discountInfo，r308 渠道调研 380/380
            # 值域普查）：showType∈{0,2} 而 disAmount 恒 0.0——「立减
            # 金额」槽位历史值域未见非零。disAmount>0 出现=渠道启用
            # 立减促销，价格口径与标签域双重事件，立项调研后再动
            # （促销价是否可购、是否入达标口径均需词面/互证取证）
            # 观察哨（policyinfo.limitPrice，c330 渠道调研 160/162 政策
            # 恒 0）：限价槽恒 0 占位，历史值域未见非零。翻非零=限价域
            # 事件，届时按 qunar isLimitPrice 同律取证（限价是否可购、
            # 与行价的关系）再议采否
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
                        and self._band_ok(v, intl)
                        and (biz_price is None or v < biz_price)):
                    biz_price = v
                    # 胜出（最低 tprice）政策的舱别码随键：渲染端词面
                    # 随源——高档政策班的「公务￥N」舱名数值双误在源
                    # 头关闭（与「取 max 会成公务￥头等价」同族律）；
                    # 码→词映射见 cgrd_cn 处 r256 勘误注释（现行代
                    # 1/2 词面均=公务）
                    biz_cgrd = _cis[0].get("cgrd")
                if self._band_ok(v, intl) and (price is None or v < price):
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
                    if (any("航变免费退改" in str(fn.get("notecnt") or "")
                            for fn in (pi.get("fnotelst") or [])
                            if isinstance(fn, dict))
                            # nt=31 英文旗标 FreeRRE（「航变免费退改」
                            # 的独立载体，72/289 政策行在场；与 nt=10
                            # 中文真源 66/66 同现，另有 6 行独立在场而
                            # nt=10 缺席——不收该 6 行权益永久缺失。
                            # 逗号分隔等值匹配防子串误命中，同串
                            # FreeLuggage 同门纪律）
                            or any("FreeRRE" == t.strip()
                                   for fn in (pi.get("fnotelst") or [])
                                   if isinstance(fn, dict)
                                   for t in str(fn.get("notecnt") or "")
                                   .split(","))):
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
                                # 第 5 词（渠道调研收编，1/511 稀疏）：
                                # 成团人数硬性购买资格（dump 行内 aset
                                # 「2-3人享￥N」+资格价互证，与 qunar
                                # 「限3-9人」同语义族）
                                "LimitedPassengerNumPolicy": "限人数",
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
            # 备源备案（r308 渠道调研，结构化真值与现读法全等预验证）：
            # fltitem.totalduration（int 分钟）与日期差推算 236/236 全等
            # （null 5 例不计）——推算链失效（dateinfo 键改版等）时的
            # 第一换源；同族备源 mutilstn[].transferduration（中转行
            # seg[1] 专属）与 costtime 83/83 全等，为 layover 的
            # costtime 语义漂移时换源首选。备源非失效不采（宁缺勿错）。
            # 衔接时长结构化真源优先（CT-W3 挂哨结案，双 dump 代际互证
            # 83/83 全等）：fltitem.costtime（item 级，两段中转 100% 在场、
            # 直飞行结构性不出）——结构化字段少一次对 dateinfo 键存活的
            # 依赖（渠道改版双源冗余）。真值挂来源标 layoverSrc="ct"
            # （LESSONS 一.7；来源变了标记跟着变，flightnorm 判伪豁免面
            # 同步收编）。0/负/非数字视为占位退回推算（宁缺勿错，与
            # prate 恒 0 组合行占位同律）；三段中转 costtime 语义未证
            # （单值 vs 逐段归属），维持逐段差累计
            lay_min = 0
            lay_src = "times"
            from datetime import datetime as _dt
            if len(segs) == 2:
                try:
                    _ctv = int(item.get("costtime"))
                except (TypeError, ValueError):
                    _ctv = 0
                if _ctv > 0:
                    lay_min = _ctv
                    lay_src = "ct"
                    # 观测留痕（r285 Soldier M-3）：语义漂移可察——
                    # 日期差可算且与结构化背离时记 debug（同值常态
                    # 静默，防日志刷屏；渠道改 costtime 语义时此处
                    # 是唯一线索面）
                    try:
                        _da = _dt.strptime(
                            (segs[0].get("dateinfo") or {}).get(
                                "adate", "")[:19], "%Y-%m-%d %H:%M:%S")
                        _db2 = _dt.strptime(
                            (segs[1].get("dateinfo") or {}).get(
                                "ddate", "")[:19], "%Y-%m-%d %H:%M:%S")
                        _ddv = int((_db2 - _da).total_seconds() // 60)
                        if _ddv != _ctv:
                            self.logger.debug(
                                "[ctrip] costtime=%s 与日期差=%s 背离"
                                "（航班 %s），结构化优先",
                                _ctv, _ddv, item.get("pid"))
                    except Exception:
                        pass
            if not lay_min:
                # 衔接时长逐段 try：失败段 warning 跳过、保留累计，
                # 防一段脏值整段归零连累已成功段（日期差推算兜底）
                for _si in range(len(segs) - 1):
                    try:
                        _a = _dt.strptime(
                            (segs[_si].get("dateinfo") or {}).get("adate",
                                                                  "")[:19],
                            "%Y-%m-%d %H:%M:%S")
                        _b = _dt.strptime(
                            (segs[_si + 1].get("dateinfo") or {}).get(
                                "ddate", "")[:19],
                            "%Y-%m-%d %H:%M:%S")
                        lay_min += max(0, int((_b - _a).total_seconds()
                                              // 60))
                    except Exception as e:
                        self.logger.warning(
                            "[ctrip] 第 %d 段衔接时长解析失败，跳过: %s",
                            _si, e)
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
            # 中转二段起飞时刻组：mutilstn[1].dateinfo.ddate（中转行
            # 双 dump 复证 100% 在场，结构化真值非推算）。复用 qunar
            # 既有 lay2dep/transGoDate 键与 webui「二段 X 起飞」渲染
            # 位，零新键；跨天中转「二段哪天几点起飞」仅此键承载，
            # 不可由既有键反推。守卫同 qunar 纪律：lay2dep≠整体
            # 起飞（防渠道复制态假值）；transGoDate 晚于出发日才落
            # （跨天辨识信息，同天二段日期无增量）；仅中转行落，
            # 无值不落键（本地卫生律）
            _lay2dep = ""
            _tgd = ""
            if is_transfer:
                _b2dd = str((segs[1].get("dateinfo") or {}).get("ddate")
                            or "")
                if len(_b2dd) >= 16 and len(dd) >= 16:
                    if _b2dd[11:16] != dd[11:16]:
                        _lay2dep = _b2dd[11:16]
                    if _b2dd[:10] > dep_d:
                        _tgd = _b2dd[:10]
            trans = ""
            if is_transfer:
                tc = ((segs[0].get("aportinfo") or {}).get("city") or "").strip()
                from .qunar import QunarCrawler as _Q
                trans = _Q.CITY_NAME.get(tc, tc) or "中转"
            # 决策字段（提取即得，同一次响应）：舱位/机型/准点率/餐食。
            # 真实挂载路径（dump 实证）：classinfor 在 policyinfo[] 内
            # （cgrd 数字→词见 cgrd_cn 处 r256 勘误：现行代 0=经济舱
            # 1/2=公务舱），craftinfo 在 segs 层。
            # 舱位随最低价政策配对（曾取「第一个带 classinfor 的政策」，
            # 与展示的最低价不同舱——真实字段但错误配对，误导性半假数据）
            craft = ""
            plane_size = ""
            for s in segs:
                _ci_s = s.get("craftinfo") or {}
                if not craft:
                    craft = str(_ci_s.get("cdisname") or "").strip()
                # 机型体量（第六批四渠道收口最后缺口）：craftinfo
                # .kind 结构化真值（1=大型机/2=中型机/3=小型机，与
                # cdisname「(大)/(中)/(小)」后缀对完全自洽——渠道给的
                # 映射勿自维护宽体清单；E190 渠道判「中」照采，C909
                # 支线机判「小」同律）；kind 缺失段 5/175 时
                # cdisname 括号兜底（同源同信息）
                if not plane_size:
                    _kind = _ci_s.get("kind")
                    if _kind in (1, 2, 3):
                        plane_size = {1: "大型机", 2: "中型机",
                                      3: "小型机"}[_kind]
                    else:
                        # 括号兜底扫当前段 cdisname（扫
                        # 外层 craft 恒为首段，首段无括号+后段 kind 缺失
                        # 时会漏采后段括号信息）
                        _psm = re.search(r"[（(]([大中小])[)）]",
                                         str(_ci_s.get("cdisname") or ""))
                        if _psm:
                            plane_size = f"{_psm.group(1)}型机"
                if craft and plane_size:
                    break
            # 中转二段机型/体量（r339a 候选 A）：mutilstn[1].craftinfo
            # 65/65 中转行在场、48/65 二段机型≠首段——「全程坐什么
            # 飞机」与 widebody 全程判的二段证据；与首段同门（kind
            # ∈{1,2,3} 结构化真值，缺失 cdisname 括号兜底）；仅中转
            # 行落、无值不落键
            craft2 = ""
            plane_size2 = ""
            if is_transfer and len(segs) > 1:
                _ci2 = segs[1].get("craftinfo") or {}
                craft2 = str(_ci2.get("cdisname") or "").strip()
                _kind2 = _ci2.get("kind")
                if _kind2 in (1, 2, 3):
                    plane_size2 = {1: "大型机", 2: "中型机",
                                   3: "小型机"}[_kind2]
                else:
                    _psm2 = re.search(r"[（(]([大中小])[)）]", craft2)
                    if _psm2:
                        plane_size2 = f"{_psm2.group(1)}型机"
            ci = best_ci
            # 机龄：classinfor.extendinfos[].content「机龄9年」
            # 结构化真值，取数字串与 tuniu flightYear「6.3」原始形态协议
            # 对齐；随最低价政策配对与舱位同律。粗化哨（证据面备案）：
            # DB 全史值域 15 值（'5' 占 1874/2676=70%，16.5/8.5/18.3
            # 等多值在案）——'5' 高占比是「部分粗化」非恒档占位：值域
            # 多值证明载体真实，且真 5 年机龄与默认'5'不可分辨（同航班
            # 跨渠道 22/22 异值是疑点非铁证），零误杀证据不成立、不置
            # 空；触发线=值域塌缩单值或'5'占比 >80% 持续，方按恒档
            # 占位处置（读层置空 + 历史值域证据在案）
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
            # 首段配对同律，last-wins 会让口径漂到末段）；脏词面弃。
            # 聚集哨（量化触发线）：100% 曾连续两代 12 行聚集于
            # 同一远期航线——「100% 占比高」本身不定性（真源多值
            # 87/90/83 在案，三形态不可分辨）。快照聚集（连续多代
            # 同航线 100% 单值）只是必要观察信号：远期航线待观察
            # 航班少，快照面天然窄化，聚集可长期在场而非粗化——
            # 3 代触发线曾到达，DB 全天值域裁决为多值 {100,87,97}
            # 非塌缩。处置的充分条件=全天/全史值域塌缩单值（全库
            # 值域终审，恒档占位分界律）；值域多值在场时只观察不
            # 置空（读层恒档置空需历史值域零误杀证据先备）
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
                        # 基座行为保持：只置 _recheck 不进 labels——
                        # 行李服务语义由 transferBaggage=recheck 的
                        # 「需转运」徽标承载（历史裁决，词面不重复）
                        _recheck = True
                    elif _c == "行李免费转运":
                        # （tcode=G_KWEBAG202311，昆航中转 2/190 稀疏）
                        # 显式转运真值置 _recheck（旗标推断让位见
                        # transferBaggage 门）；词面随 labels 出口——
                        # 「免费」是服务承诺增量，与「行李代转运」的
                        # 纯徽标裁决分属两档
                        _recheck = True
                        if _c not in labels:
                            labels.append(_c)
                    elif _c == "联程值机，行李直挂":
                        _item_direct = True
                    elif _c == "中转免二次托运":
                        # 直挂第 5 信号源（渠道调研收编，2/174 稀疏，
                        # tcode=G_HETZZMTY）：显式「免二次托运=直挂」
                        # 真值，与「联程值机，行李直挂」同向归并
                        _item_direct = True
                    elif _c == "中转住宿":
                        # 跨天中转免费住宿的 aset 层独立载体：可与政策
                        # 级 nt=10 双现行，也可单独在场（该行全部政策
                        # 无 nt=10 实证）——按「与 nt=10 同义不收」
                        # 排除曾让这类行的权益词永久缺失；归一为
                        # hotel_free 同串（labels 去重自洽，零新键）
                        hotel_free = True
                    elif _c and _c in ("宠物友好", "绿色飞行奖里程",
                                       "轻飞享奖里程", "免费上网",
                                       # 第八批扩充（178 班去重+
                                       # fresh 复验稳定非价格词）：中转
                                       # 餐食/地面接驳/舱内宠物第三态——
                                       # 地域品牌词**纯词形态**已凭
                                       # 「载体行 0 并现+无既有出口」
                                       # 复验收编（见下方三件）；带价
                                       # 营销词「优质中转·耗时短」
                                       # churn 风险维持不收
                                       "中转餐饮", "免费市区班车",
                                       # 中转餐食（tcode=G_INCZZXX，银川
                                       # 中转产品词）：与「中转餐饮」并存
                                       # 异域（DB 实证「中转餐饮」采石家
                                       # 中转 73 行、「中转餐食」是银川
                                       # 中转行唯一餐食域词面，meal/
                                       # MealTag/nt103 全空）——超集补词
                                       # 零误采，不收则该行餐食信息
                                       # 永久缺失
                                       "中转餐食",
                                       "宠物进客舱",
                                       # 中转免费休息（渠道调研收编，
                                       # tcode=G_HETXXS，2/174）：服务
                                       # 承诺型稀疏词与免费市区班车同
                                       # 批同律；休息≠中转住宿，既有
                                       # 白名单不覆盖
                                       "中转免费休息",
                                       # 专属休息/一次安检免二次安检
                                       # （第 18 轮调研收编，2/544
                                       # 稀疏同行现）：HU/HO 中转行
                                       # 唯一权益词，同行零既有出口
                                       # 不收则永久缺失
                                       "专属休息", "一次安检/免二次安检",
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
                                       "经济舱售罄",
                                       # 赠快速安检（tcode=G_KMZZAJ，
                                       # 恒挂中转行）：中转快速安检服务
                                       # 承诺，与专属休息/一次安检同族
                                       # 稀疏权益词；tagcnt 纯词无价格
                                       # 不随价 churn
                                       "赠快速安检",
                                       # 赠餐食、休息厅（tcode=G_ALLDRZZZFWB，
                                       # 3/160 两代际首现）：中转餐食+
                                       # 休息厅服务承诺，载体行 nt=103/
                                       # nt=10/行内其余 aset 词零既有
                                       # 出口承载，不收则永久缺失；
                                       # 与赠快速安检/专属休息同族纯词
                                       "赠餐食、休息厅",
                                       # 地域中转权益品牌词三件（调研
                                       # 复验收编：载体行 nt=10/aset
                                       # 中转住宿/nt=103 全部 0 并现，
                                       # 无既有出口承载不收则永久缺失；
                                       # tagcnt 纯词无价格不随价 churn，
                                       # 第八批「地域品牌词 churn 风险」
                                       # 排除依据针对的是带价营销词，
                                       # 与本组纯词形态不同；qunar
                                       # 「郑州机场中转权益」同族先例）
                                       # 郑州中转 G_2025CGOZZCS 5/191、
                                       # 昆明长水 G_KMZZHZS 2/191、
                                       # 兰州 G_LHWZZJD 1/191、
                                       # 合肥 G_HFEZZXXS 1/191
                                       '享“豫转豫好”免费服务',
                                       "晚安长水",
                                       "经兰飞如意行权益",
                                       '享“皖美中转”休息室服务'):
                        if _c not in labels:   # aset 同词重复去重（P2-8）
                            labels.append(_c)
            if has_wifi:
                labels.append("机上Wi-Fi")
            # 中转服务 fcode（fltitem.fcode 逗号分元素，直飞恒 None）：
            # 「英文内部码不采」的排除依据被渠道自带 filterlst 词面
            # 字典部分证伪——唯一有独立信息增量的 _5（载体行既有出口
            # 仅地域品牌词，休息室服务内容无处承载）静态白名单直映。
            # 不引根级字典防漂移（字典自身 churn，_4「赠中转酒店」
            # 被撤即先例）；与「赠餐食、休息厅」同义近域互斥（labels
            # 已含休息厅/休息室子串词不重拼，同词面重复拼接去重律的
            # 近域变体）
            for _fc in str(item.get("fcode") or "").split(","):
                _fw = {"transitServiceId_5": "赠中转休息室"}.get(
                    _fc.strip())
                if (_fw and _fw not in labels
                        and not any("休息厅" in _l or "休息室" in _l
                                    for _l in labels)):
                    labels.append(_fw)
            # 观察哨（fcode 新码流）：字典只认渠道自带词面直映（现仅
            # transitServiceId_5）——G_* 形态新码（如 G_DRD）出现且载体
            # 行有独占中文词面（root.filterlst 字典条目或 aset 同行独占）
            # 时按同律收编，无独占词面维持不采。
            # r311 复核增补：G_DRD「当日达」与 depDate==arrDate 53/53
            # 全等=派生零增量不采；翻身条件精化为「G_DRD 出现在跨天行」
            # （词面与日期对背离=渠道语义事件，届时按事件定性）。
            # r312 渠道调研增补（transitServiceId_4「赠中转酒店」）：
            # 244 行仅旧代单行在场（2027 档 4 dump 0 次），载体行
            # nt=103/aset 中转住宿/nt=103 三源全空=无既有出口承载、
            # 渠道字典词有读者词面——跨轮复现 ≥2 代再按 _5 同律
            # 「fcode 直映静态白名单」收编（不引根级 filterlst 字典
            # 防漂移），本轮维持观察
            if refund_free:
                labels.append("航变免费退改")
            if hotel_free:
                labels.append("中转免费住宿")
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
            # 舱位字母：classNoteList notetype=2 notecnt 订座舱位码
            # （Y/B/M/H/Q/... 单字母 + 字母+数字两字符子舱码 R1/B0
            # ——B0 挂直飞全价且 pid 政策 grade 同价 0.01 内精确互证
            # 2/2，R1 挂 9C 首段 3.7 折深折与 qunar 已转正的春秋子舱
            # 码同族同指纹；历史同域 R2/W9/D3 全为字母+数字形态，
            # 字母+字母无生产实证不采（Soldier m-3 收窄）；
            # classinfor 级 100% 在场；nt=1 恒等 prate 纯重复不采）
            # ——退改等级的根（同为经济舱 Q 舱与 Y 舱退改天差地别），
            # tuniu cabinCode 同键协议对齐；随最低价政策配对（best_ci
            # 本就随价走），正则校验宁缺勿错（数字开头/三字符/小写拒）
            cabin_code = ""
            for _cn in (ci.get("classNoteList") or []):
                if isinstance(_cn, dict) and _cn.get("notetype") == 2:
                    _cc = str(_cn.get("notecnt") or "").strip()
                    if re.fullmatch(r"[A-Z][0-9]?", _cc):
                        cabin_code = _cc
                    break
            # pid 数字行李额配对落值：最低价有票政策 (price, 舱位字母)
            # 与 pid 政策 (price, grade) 双门匹配才落（dump 实证 grade
            # 与 nt=2 字母一致率 48/48；可采面 ~22%，pid 政策非最低价
            # 或舱位不匹配时宁缺勿错不落）。0=「无免费托运」词面直述
            # （春秋裸价的比价失真硬证据），正数=「免费托运NKG」数字
            # 词面；手提额孪生家族同门同落（「手提NKG·M件」，春秋
            # free=0 行恒 7KG×1件——「最低价不含托运」比价失真的手提
            # 侧补全；侧缺失独立判定）。仅直飞行落值：中转行 pid 是
            # 段级分算价（配对天然不中），且行李额属单件级字段，组合
            # 行继承有结构性风险
            baggage = ""
            carryon = ""
            if pid_pols and cabin_code and price is not None \
                    and not is_transfer:
                for _pp, _pg, _kg, _cw, _ca in pid_pols:
                    if abs(_pp - price) < 0.01 and _pg == cabin_code:
                        # 单行整体取用不混拼（同价同舱位多政策行李额
                        # 可不同，跨行拼装=误导；首行全无效属防御面
                        # 漂移场景——dump 251/251 每政策恒 4 家族各 1
                        # 且全值域内，生产不可达，Soldier P2-1 备案）
                        if _kg is not None:
                            baggage = ("无免费托运" if _kg == 0
                                       else f"免费托运{_kg}KG")
                        if _cw is not None and _ca is not None:
                            carryon = f"手提{_cw}KG·{_ca}件"
                        break
            # 高风险政策透明标记：nt=104 报价条目 limitTag=HighRiskPolicy
            # 与落库最低价同价（价门精确到分）即落。同价条目 limitTag
            # 零分歧 215/215 实证（价内一致），pid 舱位门在此不适用——
            # limitTag 行 cabin_code 100% 缺失且 grade 全 Y 无区分度。
            # 中转行同样落：nt=104 是行级报价载荷（priceInfoList 与
            # policyinfo 同源），价门精确配对即真值——非 pid 段级分算
            # 形态，「仅直飞」先例不适用（dump 两轮 13/13 命中全为
            # 中转行、直飞样本 0，维持中转门=永久零出勤死代码）。
            # 行级兜底「本班存在」不采——最低价未必是高风险价，挂行级
            # 即误导。agePolicy 同语义位：「你看到的最低价是渠道高风险
            # 政策价」强信号，配对不中宁缺勿错不落
            risk = ""
            risk_pols = self._risk_tags(item)
            if risk_pols and price is not None:
                if any(abs(_rp - price) < 0.01 for _rp in risk_pols):
                    risk = "高风险政策"
            # 直飞行含免费托运观测词（中转行走 transferBaggage=direct
            # 既有展示，不重复落词）：pid 精确额已落 baggage 时让位
            # （「免费托运20KG」与「含免费托运」同屏冗余，双门匹配的
            # 数字额比 nt=31 布尔推断更精确）
            if best_freelug and not is_transfer and not baggage:
                labels.append("含免费托运")
            # 会员专享资格价与年龄资格（classNoteList nt=3 旗标）：
            # 非会员/非符合年龄人群/非指定卡支付出不了票的硬性购买
            # 门槛，与 nt=20 年龄限制同族并入 agePolicy 词面零新键
            # （LimitedAge 裸词=nt=20 LimitedAgePolicy 的载体迁移形态，
            # 同词面）。逗号串与分元素两形态按词表判（split 归一）；
            # 裸 AirlineMemberShip 语义未证不采（宁缺勿错）；与 nt=20
            # 并存时「·」拼接，同词面已在不重拼。
            # 按段全元素扫描：classinfor 元素=按段舱位（cis 数==段数
            # 222/223 dump 直证；pid trlinfos 段级 (price,grade) 求和
            # 等于 tprice 的同产品子集佐证），任一段的受限票都使整程不可购——旗标
            # 曾恒挂第二段元素而首元素门永不命中（「限协议」落地零出勤
            # 根因；冻结 dump 旗标行漏采面 5/21）。结构门：cis 数==段数
            # 才全元素扫，形态不符（未证形状）维持首元素宁缺勿错
            _mems = []
            _hr2 = False    # nt=3 HighRisk 旗标（riskPolicy 第二源）
            _prem = False   # nt=3 PremiumEcoProduct（超级经济舱标记）
            _flag_cis = (cis if (isinstance(cis, list)
                                 and len(cis) == len(segs)) else [ci])
            for _el in _flag_cis:
                if not isinstance(_el, dict):
                    continue
                for _cn in (_el.get("classNoteList") or []):
                    if not (isinstance(_cn, dict)
                            and _cn.get("notetype") == 3):
                        continue
                    _words = [t.strip() for t in
                              str(_cn.get("notecnt") or "").split(",")
                              if t.strip()]
                    # 两旗标（词表成员判定，逗号串/分
                    # 元素两形态同门）：HighRisk=riskPolicy 第二源
                    # （这些行 nt=104 报价载荷全部空转，语义只此一
                    # 载体，双 dump 12/218 复现）；PremiumEcoProduct=
                    # 超级经济舱产品标记（S 舱深折扣+座椅倾斜 100°，
                    # 档位语义零既有出口，双 dump 5/218 复现）。两者都
                    # 随最低价政策配对——旗标挂别的政策时行价未必是
                    # 该政策价，挂行级即误导（nt=104 价门同律）
                    if "HighRisk" in _words:
                        _hr2 = True
                    if "PremiumEcoProduct" in _words:
                        _prem = True
                    # 单元素内多词全收（链序=词表序）：每个映射词都是
                    # 独立硬门槛，链式只留首词会把其余限制藏进渲染外
                    # （单槽时代的产物，多段扫描后按序收集保真）
                    for _chk, _word in (
                            ("LimitedCtripMemberShip", "限携程会员"),
                            ("LimitedAirlineMembership", "限航司会员"),
                            ("LimitedAge", "限年龄"),
                            ("LimitedCardType", "限卡支付"),
                            # 航司大客户协议价（COR 协议票，成对
                            # AirlineAgreementIDLimit）：普通旅客误购
                            # 无法出票/值机的硬资格，与限卡支付/限航司
                            # 会员同门；该政策价=行内最低有票价互证在案
                            # （「你看到的最低价买不了」）。渲染端拼
                            # 「价」→「⚠限协议价」，词面不带价字
                            ("LimitedAirlineAgreementID", "限协议"),
                            # 限人数（nt=3 独立载体；nt=20 载体
                            # LimitedPassengerNumPolicy 同词既有）——
                            # 成团人数硬资格，与限卡支付同门
                            ("LimitedPassengerNum", "限人数")):
                        if _chk in _words and _word not in _mems:
                            _mems.append(_word)
            for _w in _mems:
                if _w in (best_age or ""):
                    continue
                best_age = f"{best_age}·{_w}" if best_age else _w
            # 第二源应用点：nt=104 价门已落即不再动（词面同「高风险
            # 政策」，双源同值无重复面），只补 nt=104 空转行；超经
            # 标签直进 labels（PNG 总表图列/title/CSV 既有通道零新键）
            if not risk and _hr2 and price is not None:
                risk = "高风险政策"
            if _prem and "超级经济舱" not in labels:
                labels.append("超级经济舱")
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
            # 0 占位挡（组合中转无单航班真值，DB 实证 6 行
            # prate='0' 流入曾渲染「准点0%」假数据；消费端
            # prate_txt 同守卫通吃存量行）
            prate = str(int(prate)) if isinstance(prate, (int, float)) and float(prate) > 0 else ""
            # 真源覆盖（上方 aset 遍历的 InTimeTag）：classinfor.prate/
            # nt=1 源仅作兜底，InTimeTag 有值即覆盖（{100,97} 两档伪源
            # 与真值大面积背离，交叉一致率仅 1.2%）；InTimeTag 下发 0%
            # 系组合/codeshare 行填槽占位（结构性，与上方 0 值挡同律），
            # 连同伪源一并置空——伪源 100 借 0 占位兜底落库曾渲染「准点
            # 100%」，比「准点0%」更隐蔽
            if _intime is not None:
                prate = str(_intime) if _intime > 0 else ""
            meal = str(ci.get("meal") or "").strip()
            # cgrd 数字→词存在代际不稳定性：r256 两份冻结 dump 五面
            # 实证当前代 2=公务舱（nt=4 词面 69/69「公务舱」且「头等
            # 舱」全 dump 0 例、cgrd=1 零出场、nt=2 舱位字母 C/D/I/R/
            # Q/Z 公务族 F/A 零出场、tprice p50≈经济舱 2.2×），旧代
            # CA8564「全班仅剩头等 9900」时代 2 曾=头等——渠道词面
            # （fnotelst nt=4）是唯一权威，数字映射只在词面复验通过期
            # 内有效，每轮全量键 diff 复验（LESSONS 廿四§10 防线）
            cgrd_cn = {0: "经济舱", 1: "公务舱", 2: "公务舱"}
            cabin_cn = cgrd_cn.get(ci.get("cgrd"), "") if ci else ""
            # 航站楼：mutilstn 首末段 dportinfo/aportinfo.bsname
            # （"T2"）。多航站楼一侧才有值（乌→沪 arr 98/98 T1/T2、dep
            # 0/98——出发地单航站楼渠道下发空串），无值不落键
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
            # labels 增补词面（零新键）：nt=105 诱饵价透明标记
            # （展示价 ∈ 渠道过滤清单 = 点进必涨价，用户点携程前先知）
            # + 根级 allilst 航盟归属（二字码 ∈ airs 才正向落词）
            _lure, _lure_p = self._lure_price_tag(item, price)
            if _lure:
                labels.append(_lure)
            for _al in self._alliance_tags(obj, fnos):
                labels.append(_al)
            # 时区戳（r325，INTL_DESIGN §1.2）：起降机场各自算对 UTC
            # 偏移，两端已知且不同才落键——纯国内对（同 UTC+8）朴素差
            # 本就正确，落键白占 schema；跨区对（PVG+480/NRT+540）不
            # 落键会让 flightnorm 国际档被 naive 渠道时长骗过 ±时区差。
            # 任一端字典外（偏移未知）不落，flightnorm 对无时区行信渠道
            _tz_dep = tz_offset_min(str((first.get("dportinfo") or {})
                                        .get("aport") or ""))
            _tz_arr = tz_offset_min(str((last.get("aportinfo") or {})
                                        .get("aport") or ""))
            out.append({
                "price": price,
                "code": code,
                "name": fnos[0],
                "depTime": dd[11:16],
                "arrTime": ad[11:16],
                "depDate": dep_d,
                "arrDate": arr_d,
                **({"tz_dep": _tz_dep, "tz_arr": _tz_arr}
                   if _tz_dep is not None and _tz_arr is not None
                   and _tz_dep != _tz_arr else {}),
                # 「属性不适用即落空串」残留族无值不落键（r241 观测
                # 立案 10 键收口，缺席≡空串消费端等价；中转/有值照落）。
                # 观察哨（transCity 码形态混入）：渠道偶发把三字码
                # （JGS/LYA/YCU 形）直接下进 city 槽（14 天窗 12 行，
                # 恰卡经停/中转航线），直出渲染读者不可读——量爬升或
                # 稳定复现即立项走 AIRPORT_NAME_CN 归一同律；零星
                # 个位数维持观察不动笔
                **({"transCity": trans} if trans else {}),
                **({"crossDayDesc": cross} if cross else {}),
                "totalDuration": dur,
                # 衔接无值不落键（直飞行恒空串平铺，qunar 直飞行同形
                # 语义常态一并收口；中转有值照落）
                **({"layover": lay_min} if lay_min else {}),
                **({"lay2dep": _lay2dep} if _lay2dep else {}),
                **({"transGoDate": _tgd} if _tgd else {}),
                # 衔接来源标记（qunar PC "times" 同律同值）：两段起降
                # 差重建=结构化真值，flightnorm 1440 击杀区启发式只服务
                # 猜测值——无标记时跨天长真停（lay+dur 恰 1440 倍数）
                # 被误杀置空（生产 ~550 条/天，衔接下限筛选连带误剔）
                **({"layoverSrc": lay_src} if lay_min else {}),
                "cabin": cabin_cn,
                **({"plane": craft} if craft else {}),
                # prate 无值不落键（r241 同族残留收口，r311 观测
                # post-start 空串 179 例；缺席≡空串消费端等价）
                **({"prate": prate} if prate else {}),
                **({"meal": meal} if meal else {}),
                **({"shareCarrier": share} if share else {}),
                **({"shareCarrier2": share2} if share2 else {}),
                # 航司二字码（五渠道协议对齐补口：tuniu/qunar/fliggy/
                # tongcheng 同名键，webui 白名单/CSV 航司码列/搜索 hay
                # 三消费面通用形态已就位）
                **({"airlineCode": _ac} if _ac else {}),
                # 新决策字段（上面注释块：键路径 + dump 命中率）；
                # 无值不落键（DB 观测 direct 574 空串平铺，qunar 同形）
                **({"discount": best_disc} if best_disc else {}),
                # 航站楼无值不落键（单航站楼侧渠道恒下发空串，恒空键
                # 卫生律与 tuniu 同族；多航站楼侧真值照落）
                **({"depTerminal": dep_term} if dep_term else {}),
                **({"arrTerminal": arr_term} if arr_term else {}),
                # 中转航站楼（换乘出发侧）+ 最低价政策余票数
                # （quantity 1-10 结构化紧俏度，10 疑「充足」封顶；
                # 无值不落防与 0 语义混淆）。 中转楼无值不落键（同族
                # 恒空键卫生律，str 槽位空串=无值；有值照落不变）
                **({"transTerminal": trans_term} if trans_term else {}),
                "leftTickets": best_qty,
                # 高档舱最低参考价（qunar bizPrice 同键同协议 int；
                # float 透传会让 alerter isinstance 门静默缺席）+
                # 舱别词面（bizCabin，渲染端缺省回退「公务」兼容
                # 存量行）
                **({"bizPrice": int(biz_price),
                    # 舱别词面随 cgrd_cn 同律（r256 勘误：现行代
                    # 2=公务，见上方映射注释）
                    "bizCabin": {1: "公务", 2: "公务"}.get(biz_cgrd, "")}
                   if biz_price is not None else {}),
                # 年龄限制专享价（best_age：最低价政策 nt=20 或
                # classinfor nt=3 资格旗标在场时有值）
                **({"agePolicy": best_age} if best_age else {}),
                # 高风险政策透明标记（nt=104 与最低价同价条目；有值
                # 才落——webui 白名单/价格格徽标同轮接入）
                **({"riskPolicy": risk} if risk else {}),
                # 诱饵价透明标记数值（webui 价格格徽标数据源；词面
                # 已随 labels 走 PNG/title/CSV 通道）
                **({"lurePrice": _lure_p} if _lure_p is not None else {}),
                # 机龄数字串（tuniu planeAge 同协议）+ 权益标签
                # （labels 无值不落键：直飞行无标签词面时空串平铺，
                # r241 观测 18.5% 在案）。
                # 恒档粗化守卫：渠道对整年机龄恒下发 '5'（r309 首证
                # dump 恒档；r315 备案「部分粗化」挂哨并定触发线=值域
                # 塌缩单值或占比 >80% 持续；r318 双口径普查证实逐日
                # 供给连续 7 天 100% 恒 '5'（自然基线占比 0-2%），双线
                # 到达）→ 格式化后精确 '5' 读层置空。带月形态（'5.9'）
                # 与其他整年照落——恒档下发只在整年无月形态，月成分
                # 是真机龄可分辨形态，防误杀。撤守卫条件=逐日 '5' 占
                # 比回落（渠道恢复多值下发），移除常量即恢复复采。
                # 无值不落键（r310 观测：空串占位平铺 8,209/25,228
                # 元素；门 != "" 非 truthy，「机龄0年」显式真值照落）
                **({"planeAge": plane_age}
                   if plane_age not in ("", _PLANEAGE_COARSE) else {}),
                **({"labels": "·".join(labels)} if labels else {}),
                # 平均延误 int 分钟（tuniu avgDelay 同协议，webui
                # 明细次行消费端已在）+ 连廊率百分数数字——无值不
                # 落键同上律（r310 观测空串平铺 10,493/25,228 元素，
                # 与 tongcheng `!= ""` 门对齐；0 分钟照落）
                **({"avgDelay": avg_delay} if avg_delay != "" else {}),
                # 中转行李直挂（仅中转行置值；显式证据优先序：政策级
                # nt=10「行李直达」/aset「联程值机，行李直挂」/nt=103
                # 直挂词全为显式真值，nt=31 FreeLuggage 是旗标推断源
                # ——显式转运词（行李代转运/行李免费转运）在场时推断
                # 让位 recheck（显式真值 > 推断律；「把需转运当直挂」
                # 的决策伤害大于反向，直挂筛选语义下保守方向正确），
                # 显式直挂证据仍在场时 direct 赢（显式>显式按源权威
                # 序，政策级>item 层；item 层内直挂词与转运词并现时
                # 同按直挂赢——生产 3 行「行李代转运」+「联程值机，
                # 行李直挂」并现即此形态，徽标=直挂、转运词若在
                # labels 由读者自行权衡服务承诺）；
                # 「行李代转运」落 recheck 三态；nt=103 联程明细
                # 含「行李直挂」亦为直挂证据（当前样本是单段经停行，
                # is_transfer 门控天然不触发，留作真中转带此 note 增益）；
                # 空串=未知，normalize 的 transitServiceLabel 兜底照常生效）
                # transferBaggage 无值不落键（直飞行恒空串与中转行无证据
                # 空串支路随族收口，normalize setdefault 兜底语义不变）
                **(({"transferBaggage": "direct"}
                    if (is_transfer and (best_direct or _item_direct
                                         or _ts_direct
                                         or (best_freelug and not _recheck)))
                    else ({"transferBaggage": "recheck"}
                          if (is_transfer and _recheck) else {}))),
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
                # 舱位字母（上方 classNoteList nt=2，随最低价政策配对；
                # 无注记不落键——after 观测抓产中转行空串，同族不落）
                **({"planeSize": plane_size} if plane_size else {}),
                # 二段机型/体量（上方二段提取；仅中转行有值，无值
                # 不落键同律）
                **({"plane2": craft2} if craft2 else {}),
                **({"planeSize2": plane_size2} if plane_size2 else {}),
                **({"cabinCode": cabin_code} if cabin_code else {}),
                # pid 数字托运额词面（免费托运NKG/无免费托运，双门匹配
                # 才有值；数字额比 tongcheng 布尔词面/qunar 词面更精确，
                # report 明细图既有词条零改动透出）
                **({"baggage": baggage} if baggage else {}),
                # pid 数字手提额词面（手提NKG·M件，与 baggage 同门同落；
                # 廉航「无托运但有手提」比价面的手提侧）
                **({"carryon": carryon} if carryon else {}),
                # 经济舱「公布运价」撤采（r254 定谳）：pid items.L_Y_Price
                # 经双源 raw 对照实为卖价镜像（与行价恒等、深折行也不含
                # 全价），与 tuniu bcTaxExclusiveFare（税前公布价）跨渠道
                # 不对等——原「跨渠道对等」承诺失真，恒等镜像零信息增量
                # 不采；CSV「公布运价」列回归 tuniu 纯口径
                # 座椅倾斜角度（classinfor.seattilt，唯一未采的舱位物理
                # 参数）：结构化真值非零 89.4%、值域 100~180（180=可平
                # 躺），0 视未报不落（宁缺勿错，防与真值 0 混淆）；
                # bool 剔除（true 是 int 子类，落 1 即脏值）。
                # DB 全史值域 {100: 2363, 110: 313} 双值实证——载体
                # 真实、100°/110° 均为经济舱常态倾角，渠道本态非占位
                # （恒值占位不会产双值），值域再扩即自然跟随
                **({"seatTilt": int(ci["seattilt"])}
                   if isinstance(ci.get("seattilt"), (int, float))
                   and not isinstance(ci.get("seattilt"), bool)
                   and int(ci["seattilt"]) > 0 else {}),
                **({"stopCitys": ";".join(stops)} if stops else {}),
                **({"stopTime": f"{stop_mins // 60}小时{stop_mins % 60}分"}
                   if stop_mins > 0 else {}),
            })
            if ts_svc:
                out[-1]["transferService"] = ts_svc
            if bridge_rate != "":
                # 连廊率无值不落键（载荷卫生：正则未命中旧落空串
                # ~180 行/日，int 真值占 99.3%）
                out[-1]["bridgeRate"] = bridge_rate
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
