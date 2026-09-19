"""去哪儿机票：httpx 优先 + 浏览器兜底（混合模式）

针对去哪儿 touchInnerList 接口的 Ctrip ubtrms / chloroFp 风控：
- Bella token + caf7be/pre 等指纹头 + cookies 由浏览器跑风控 JS 生成，
  无法纯 httpx 离线生成（服务端校验指纹自洽性后下发 token）
- token 本身可复用（实测有效期 >5分钟，可能 24h）
- 但接口有全局频率限流（约5分钟/次），与航线无关，httpx 连续请求必 1999

混合策略（省约50%浏览器开销）：
1. 每轮第一条航线优先 httpx（用缓存的 token）
2. httpx 成功 → 直接返回；后续航线也尝试 httpx，失败则回退浏览器
3. httpx 1999/无token/异常 → 浏览器单条查（拦请求刷新 token + 解析响应拿价）
4. 浏览器每次跑都会刷新 token，供下次 httpx 使用

实测：浏览器握手后立即 httpx 可拿到真实价格（minPrice 与 DOM 一致）；
但 httpx 第二次（5分钟内）必被风控，故多航线场景第二条起回退浏览器。
"""
import logging
import os
import re
import json
import time
import urllib.parse
from collections import Counter
from datetime import date, datetime
from typing import List, Optional

import httpx

from core.models import FlightPrice
from .base import BaseCrawler

_LOG = logging.getLogger(__name__)

# 廉航二字码：中转基本需重新值机（与 core.flightnorm.AIRLINE_LCC 同口径）
_LCC_CODES = {"9C", "KN", "AQ", "GX", "DZ", "EU", "8L", "PN", "QW",
              "G5", "BK", "KY"}


def _span_days(d1: str, d2: str) -> int:
    """depDate→arrDate 跨度天数（解析失败按 0——守卫从宽不误伤）。"""
    try:
        return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
    except (TypeError, ValueError):
        return 0


def _meal_from_addons(add) -> tuple:
    """H5 flightAddInfoIntegration.flightAdditionInfos[] → (餐食, 托运)文本。

    实测 name 全集（9/25 报文 75 行）：正餐/有餐/有餐食/无餐食/点心/
    点心餐/早餐 + 非餐项（免费托运20KG/廊桥登机率--/WiFi未知...），
    餐食按含「餐/点心」词识别，托运顺带按含「托运」识别（v1.5.37），
    各取首个；托运文本直入 f["baggage"]——cabin_text（flightnorm）
    对 baggage 原样拼接，报文原名「免费托运20KG」即所需形态。
    （真实报文证据，勿照抄 PC mealDesc）。"""
    meal = baggage = ""
    items = add.get("flightAdditionInfos") if isinstance(add, dict) else None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip()
        if not nm:
            continue
        if not meal and ("餐" in nm or "点心" in nm):
            meal = nm
        if not baggage and "托运" in nm:
            baggage = nm
        if meal and baggage:
            break
    return meal, baggage


def _pos_num(v):
    """正数值提取：0/非数/布尔 → None（0 是渠道「未报价」占位符，
    现实不存在 0 元票，按宁缺勿错不落键防「已报价 0 元」假数据）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if v > 0 else None


def _baggage_tag(f: dict) -> str:
    """中转服务标签 → 行李直挂信号（保守判定）。

    仅认接口明确写「行李免提 / 免费托运」的中转联程产品；普通自行
    中转无该标签，返回 ""（未知——不做断言，筛选时如实按未知处理）。
    廉航（春秋等）的中转标签多为机场「代转运」服务包装、两段并不
    直挂——按不满足处理（用户实锤）。"""
    from core.flightnorm import _is_lcc
    if _is_lcc(f.get("code") or "") or _is_lcc(f.get("name") or ""):
        return ""
    sv = ((f.get("transitServiceLabel") or "")
          + (f.get("transitServiceLabelName") or ""))
    return "direct" if ("行李免提" in sv or "免费托运" in sv) else ""


class QunarCrawler(BaseCrawler):
    name = "qunar"
    use_mobile = True

    # 去哪儿单程列表 H5（用户提供的真实入口）
    URL_TPL = (
        "https://touch.qunar.com/ncs/page/flightlist"
        "?depCity={from_name}&arrCity={to_name}"
        "&goDate={date}&from=touch_index_search"
        "&child=0&baby=0&cabinType=0"
    )
    # PC 版单程列表：H5 接口 touchInnerList 自 2026-09-11 风控升级
    # （token 每轮刷新成功仍 1999，阶梯退避耗尽），PC 页 + wbdflightlist
    # 接口在同款无头浏览器下实测正常出全量明细（77 条级），改为主路径
    PC_URL_TPL = (
        "https://flight.qunar.com/site/oneway_list.htm?"
        "searchDepartureAirport={from_name}&searchArrivalAirport={to_name}"
        "&searchDepartureTime={date}&nextNDays=0&startSearch=true"
        "&fromCode={fcode}&toCode={tcode}&from=flight_dom_search"
    )
    PC_API_MARK = "wbdflightlist"
    # wbdflightlist 的 minPrice 每次请求重摇（实测同条目 50 秒间隔连续
    # 6 采样无一重复，~11% 采样出现 150-200 元幻影低价，页面渲染价同样
    # 在变）——单次采样必然撞运气，多份采样逐条目取中位数治之
    PC_SAMPLES = 3
    # 自适应降暴露：首采样较上轮跌超 5%（幻影信号特征，正常轮间波动
    # <3%）才值得花额外请求加采复核，平时单采样即收工
    PC_DROP_RATIO = 0.95

    def __init__(self, config, logger):
        super().__init__(config, logger)
        # (from_city, to_city, date) -> 上轮合并后最低价（骤降侦测参考）
        self._pc_prev = {}
        # (from_city, to_city, date) -> {"min": 阈值}，main.py 按查询注入；
        # 幻影低价恰好落在达标线附近时单采样不可信（见 _fetch_pc）
        self.threshold_hints = {}

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

    # 反自动化指纹脚本：让设备指纹与 iPhone UA 自洽，骗过 chloroFp 服务端校验
    # 关键：Ctrip 风控发现「iPhone UA + Win32/NVIDIA WebGL」矛盾会拒发指纹 token
    _STEALTH_JS = r"""
    (function(){
      const define = (obj, prop, val) => {
        try { Object.defineProperty(obj, prop, {get: () => val, configurable: true}); } catch(e){}
      };
      // 基础导航器：对齐 iPhone Safari
      define(navigator, 'webdriver', undefined);
      define(navigator, 'languages', ['zh-CN','zh']);
      define(navigator, 'platform', 'iPhone');
      define(navigator, 'maxTouchPoints', 5);
      define(navigator, 'hardwareConcurrency', 6);
      define(navigator, 'vendor', 'Apple Computer, Inc.');
      try { delete navigator.deviceMemory; } catch(e){}
      // plugins 真机 Safari 为空
      define(navigator, 'plugins', []);
      window.chrome = undefined;

      // WebGL：把 NVIDIA/ANGLE 伪装成 Apple GPU
      const APPLE_VENDOR = 'Apple Inc.';
      const APPLE_RENDERER = 'Apple GPU';
      const patchGL = (proto) => {
        if (!proto || !proto.getParameter) return;
        const orig = proto.getParameter;
        proto.getParameter = function(p){
          // UNMASKED_VENDOR_WEBGL=37445, UNMASKED_RENDERER_WEBGL=37446
          if (p === 37445) return APPLE_VENDOR;
          if (p === 37446) return APPLE_RENDERER;
          // VENDOR=7936, RENDERER=7937
          if (p === 7936) return 'WebKit';
          if (p === 7937) return 'WebKit WebGL';
          return orig.call(this, p);
        };
      };
      try { patchGL(WebGLRenderingContext.prototype); } catch(e){}
      try { patchGL(WebGL2RenderingContext.prototype); } catch(e){}

      // 触摸事件支持标记
      try {
        define(window, 'ontouchstart', null);
      } catch(e){}
    })();
    """

    # 去哪儿单程列表真实数据接口
    API_URL = "https://touch.qunar.com/flight/api/touchInnerList"

    # 风控占位响应特征
    RISK_CODE = 1999
    # token 有效期（保守取 20h，实际约 24h）
    TOKEN_TTL_S = 20 * 3600

    def login_url(self) -> str:
        # 触屏版登录入口，登录后 cookie 作用于 touch.qunar.com，与抓取同源
        return "https://flight.qunar.com/"

    # ==================== 主流程 ====================
    # 阶梯式限流自锁（替代固定 310s 预防等待——实测一轮 11 分钟里
    # 9.8 分钟在等）：平时只保礼貌间隔；空数据疑似限流才退避，
    # 冷却期类级共享（多查询间生效），拿到数据即重置
    _MIN_GAP_S = 8                 # 相邻查询礼貌间隔（登录态实测零限流，20→12→8；失败有阶梯退避兜底）
    _BACKOFF_S = (90, 180, 300)    # 疑似限流的阶梯退避
    _last_done_ts = 0.0
    _cooldown_until = 0.0

    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        import time as _t
        for attempt in range(len(self._BACKOFF_S) + 1):
            wait = max(QunarCrawler._cooldown_until - _t.time(),
                       self._MIN_GAP_S - (_t.time() - QunarCrawler._last_done_ts))
            if wait > 0:
                self.logger.info("[qunar] 错峰等待 %ds", int(wait))
                _t.sleep(wait)
            try:
                res = self._fetch_inner(from_city, to_city, dates)
            except Exception as e:
                self.logger.warning("[qunar] 抓取异常: %s", e)
                res = []
            QunarCrawler._last_done_ts = _t.time()
            if res:
                QunarCrawler._cooldown_until = 0.0
                return res
            if attempt >= len(self._BACKOFF_S):
                self.logger.warning("[qunar] 阶梯重试耗尽（%d 次），本轮放弃",
                                    attempt)
                return []
            back = self._BACKOFF_S[attempt]
            self.logger.warning("[qunar] 三路径空结果——qunar 已于 09-12 起对"
                                "未登录会话软性返回空列表（低价日历仍出价）；"
                                "请在配置页「渠道登录」重新登录 qunar。先按限流重试 %ds（第 %d 次）",
                                back, attempt + 1)
            QunarCrawler._cooldown_until = _t.time() + back
        return []

    def _fetch_inner(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        results: List[FlightPrice] = []
        for date in dates:
            got = None
            try:
                got = self._fetch_one(from_city, to_city, date)
            except Exception as e:
                self.logger.exception("[qunar] %s 抓取异常: %s", date, e)
            if got is not None:
                price, flights = got
                best = min(flights, key=lambda f: f["price"]) if flights else None
                # 幻觉价守卫：提取价低于自身明细最低的一半 = 杂响应污染
                # （实测行价 ￥313 vs 同一 extra 明细最低 ￥2225，7 倍背离，
                # 直出概览「全线最低」并污染 last_lowest/去抖基准）
                if best and price < best["price"] * 0.5:
                    self.logger.warning(
                        "[qunar] 提取价 ￥%.0f 与自身明细最低 ￥%.0f 严重背离，"
                        "弃用改与明细同源", price, best["price"])
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
                n_direct = sum(1 for f in flights if not f["transCity"])
                self.logger.info("[qunar] %s 最低价 ￥%.0f（航班明细 %d 条：直飞 %d / 中转 %d）",
                                 date, price, len(flights), n_direct,
                                 len(flights) - n_direct)
            else:
                self.logger.warning("[qunar] %s 未解析到价格", date)
            # 日期间隔只在多日期时需要；末条后的 _sleep 是纯空等
            # （fetch() 的 _MIN_GAP_S 已保证与下一查询的礼貌间隔）
            if date != dates[-1]:
                self._sleep()
        return results

    def _fetch_one(self, from_city: str, to_city: str, date: str) -> Optional[tuple]:
        """单日期抓取：PC 版优先（wbdflightlist 完整明细），失败回退
        H5 浏览器，再回退 httpx（仅价格）。"""
        got = self._fetch_via_pc(from_city, to_city, date)
        if got is not None:
            return got
        self.logger.info("[qunar] PC 未命中，回退 H5 浏览器")
        got = self._fetch_via_browser(from_city, to_city, date)
        if got is not None:
            self.logger.info("[qunar] H5 浏览器命中（完整明细）")
            return got
        self.logger.info("[qunar] H5 未命中，回退 httpx（仅价格）")
        return self._fetch_via_httpx(from_city, to_city, date)

    # ==================== PC 版主路径（wbdflightlist） ====================
    def _fetch_via_pc(self, from_city: str, to_city: str,
                      date: str) -> Optional[tuple]:
        """PC 版列表页抓取：桌面上下文打开 flight.qunar.com 列表页，
        拦截 wbdflightlist 接口响应（完整 JSON，含全部航班明细）。

        user_data 登录态 cookie 在 .qunar.com 主域，PC 与 H5 共用；
        桌面 UA/视口（H5 的 iPhone 伪装对 PC 域反而可疑）。"""
        fc, tc = from_city.upper(), to_city.upper()
        from_name = self.CITY_NAME.get(fc, from_city)
        to_name = self.CITY_NAME.get(tc, to_city)
        url = self.PC_URL_TPL.format(
            from_name=urllib.parse.quote(from_name),
            to_name=urllib.parse.quote(to_name),
            date=date, fcode=fc, tcode=tc)
        snap = {"texts": []}

        def on_resp(resp):
            if self.PC_API_MARK in resp.url:
                try:
                    t = resp.text()
                    snap["texts"].append(t)
                    # 软拒绝空壳（code:-1 + flights:[]，~125B vs 正常 183KB）：
                    # 接口级拒绝，等待与加采均无意义，立即短路回退 H5
                    flat = t.replace(" ", "")
                    if '"flights":[]' in flat and '"total":0' in flat:
                        snap["soft_reject"] = True
                except Exception:
                    pass

        self.logger.info("[qunar] 浏览器 GET %s", url[:120])
        bak = self.use_mobile
        self.use_mobile = False
        samples = []
        key = (from_city, to_city, date)
        resample = True  # 首采样解析失败时保守加采
        try:
            with self.browser(headless=self.headless) as ctx:
                page = self.new_page(ctx)
                page.on("response", on_resp)
                for i in range(self.PC_SAMPLES):
                    if i == 1 and not resample:
                        break  # 首采样无骤降迹象，单采样收工（降风控暴露）
                    base = len(snap["texts"])
                    try:
                        page.goto(url, wait_until="load")
                    except Exception as e:
                        self.logger.warning("[qunar] PC 页面异常: %s", e)
                        break
                    for _ in range(12):
                        page.wait_for_timeout(2000)
                        try:
                            page.mouse.wheel(0, 1500)
                        except Exception:
                            pass
                        if len(snap["texts"]) > base:
                            break
                    if snap.get("soft_reject"):
                        break  # 软拒绝：跳过剩余采样，快速回退 H5
                    for t in snap["texts"][base:]:
                        flights = self._parse_pc_flights(t, date)
                        if flights:
                            samples.append(flights)
                            break
                    if i == 0 and samples:
                        prev = self._pc_prev.get(key)
                        best1 = min(f["price"] for f in samples[0])
                        # 幻影低价跌幅可 <5%（如 2900→2770）而达标线恰在其
                        # 上：破线推送是用户立刻出手的信号，恰是幻影价最
                        # 不可出现的位置——落阈值×1.05 内必加采复核
                        th = (self.threshold_hints.get(key) or {}).get("min")
                        near_th = bool(th and best1 <= float(th) * 1.05)
                        resample = self._needs_resample(prev, best1) or near_th
                        if resample:
                            self.logger.info(
                                "[qunar] 首采样 ￥%.0f%s，疑似骤降 → 加采复核",
                                best1,
                                f"（上轮 ￥{prev:.0f}）" if prev
                                else (f"（距线近，线 ￥{float(th):.0f}）"
                                      if near_th else "（无上轮参考）"))
                        else:
                            self.logger.info(
                                "[qunar] 首采样 ￥%.0f 与上轮 ￥%.0f 相当，单采样收工",
                                best1, prev)
        finally:
            self.use_mobile = bak
        if snap["texts"]:
            self._dump_raw_text(snap["texts"][-1],
                                f"pc_{from_name}_{to_name}_{date}")
        merged = self._merge_pc_samples(samples)
        if merged:
            best = min(merged, key=lambda x: x["price"])
            self._pc_prev[key] = float(best["price"])
            self.logger.info(
                "[qunar] PC 命中（wbdflightlist，%d 份采样中位，明细 %d 条）",
                len(samples), len(merged))
            return (float(best["price"]), merged)
        if snap.get("soft_reject"):
            self.logger.info("[qunar] PC 软拒绝（空壳响应），直接回退 H5 浏览器")
        elif snap["texts"]:
            self.logger.warning("[qunar] PC 接口有响应但未解析出明细")
        return None

    @staticmethod
    def _needs_resample(prev, best1) -> bool:
        """首采样骤降侦测（纯函数）：较上轮跌超 PC_DROP_RATIO（或无上轮
        参考）才加采——幻影低价的信号特征；正常波动不花额外请求。"""
        if not prev:
            return True
        try:
            return float(best1) <= float(prev) * QunarCrawler.PC_DROP_RATIO
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _parse_pc_flights(text: str, date: str) -> list:
        """解析 PC 版 wbdflightlist JSON 为统一航班明细（extra schema）。

        与 H5 同族接口的结构差异：data.flights 为普通数组（非字符串化）；
        中转整体到达时刻在 binfo2.arrTime（binfo1.arr 是中转段到达）；
        直飞时长在 binfo.flightTime（"5h30m"），中转全程时长在 transTime；
        无 mixFlightName，显示名用 binfo.shortName+airCode 拼。纯函数。"""
        try:
            obj = json.loads(text)
        except Exception:
            return []
        data = obj.get("data") if isinstance(obj, dict) else None
        if not isinstance(data, dict):
            return []
        raw = data.get("flights") or []
        if not isinstance(raw, list):
            return []
        out, seen = [], set()
        for f in raw:
            if not isinstance(f, dict):
                continue
            try:
                price = float(f.get("minPrice") or 0)
            except (TypeError, ValueError):
                continue
            if not (300 <= price <= 50000):
                continue
            b1 = f.get("binfo1") or f.get("binfo") or {}
            b2 = f.get("binfo2") or {}
            if not isinstance(b1, dict) or not b1:
                continue
            dep_t = (b1.get("depTime") or "").strip()
            arr_t = ((b2.get("arrTime") if b2 else b1.get("arrTime"))
                     or "").strip()
            # binfo2 在场即中转/经停（transCity 偶发缺省）——缺城市时以
            # 占位词「中转」兜底，防止该行被下游误分为直飞（显示层有
            # 「经中转」病句守卫）
            tc = (f.get("transCity") or "").strip()
            if b2 and not tc:
                tc = "中转"
            if not (dep_t and arr_t):
                continue
            # 中转行缺到达日：跨天/到达约束全链路无从判定（当日达回退
            # 会把跨天班误判当日达，到达约束形同虚设）——与 H5 同门槛
            # 整行丢弃（宁缺勿错）
            arr_d = ((b2.get("arrDate") if b2 else b1.get("arrDate"))
                     or "").strip()
            if b2 and not arr_d:
                continue
            code = (f.get("code") or "").strip()
            if not code:
                continue
            key = (code, dep_t, price)
            if key in seen:
                continue
            seen.add(key)
            air = (b1.get("shortName") or b1.get("name") or "").strip()
            dur = (f.get("transTime") or "").strip()
            if not dur:
                ft = (b1.get("flightTime") or "").strip()
                if ft:
                    dur = re.sub(r"(\d+)h(\d+)m", r"\1时\2分", ft)
            lay = ""
            if b2:
                # 中转停留（决策关键：停多久）三级计算：
                # ① 全程时长 − 两段飞行时长；② 第二段起飞 − 第一段到达
                # （跨天自动回绕）——两段起降时刻比 transTime 更稳定可得，
                # 覆盖 ① 缺 transTime/flightTime 的 ~20% 缺失行
                try:
                    from core.flightnorm import dur_min as _dm
                    t_m = _dm(dur)
                    f1_m = _dm(b1.get("flightTime"))
                    f2_m = _dm(b2.get("flightTime"))
                    if t_m and f1_m and f2_m and t_m - f1_m - f2_m > 0:
                        lay = t_m - f1_m - f2_m
                except Exception:
                    lay = ""
                if not lay:
                    def _hm(s):
                        try:
                            h, m = str(s).strip().split(":")
                            return int(h) * 60 + int(m)
                        except (ValueError, TypeError):
                            return None
                    a1 = _hm(b1.get("arrTime"))
                    d2 = _hm(b2.get("depTime"))
                    if a1 is not None and d2 is not None:
                        lay = (d2 - a1) % 1440
                        # %1440 回绕只在 depDate→arrDate 跨度 ≤1 天时可信：
                        # span≥2 天的 ~25h 真实停留会被回绕成 60min 假值
                        # （宁缺勿错）
                        span = _span_days(
                            (b1.get("date") or b1.get("depDate") or ""),
                            (b2.get("arrDate") or ""))
                        if span >= 2 and lay < 300:
                            lay = ""
            out.append({
                "price": price,
                "code": code,
                "name": (air + b1.get("airCode", "")) if air else code,
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": (b1.get("date") or b1.get("depDate") or date).strip(),
                "arrDate": ((b2.get("arrDate") if b2 else b1.get("arrDate"))
                            or "").strip(),
                "transCity": tc,
                "crossDayDesc": (f.get("crossDayDesc") or "").strip(),
                "totalDuration": dur,
                "cabin": (b1.get("cabin") or "").strip(),
                "discount": (f.get("discountStr") or "").strip(),
                "layover": lay,
                "plane": (b1.get("planeType") or "").strip(),
                "transferBaggage": _baggage_tag(f),
                # 经停决策字段（binfo1 已在手，提取即得）：经停城市/
                # 机场、餐食——此前 raw 有而 extra 无，用户无法判断
                # 经停航班「经停哪、停多久」
                "stopCitys": ";".join(b1.get("stopCitys") or []),
                "stopAirports": ";".join(b1.get("stopAirports") or []),
                # 经停停留时长（raw 实证 "1小时5分"/"45分"，44/47 为空）：
                # 「经停哪、停多久」的停多久数据源，normalize 转时刻式
                "stopTime": (b1.get("stopTime") or "").strip(),
                "meal": (b1.get("mealDesc") or "").strip(),
                # v1.5.48 与 H5 对齐：余票标签/共享实际承运（binfo1 层）。
                # 注意（v1.5.49 PC dump 复核）：fewTicketStr/
                # mainCarrierSimpleNameAndNo 是 H5 键名，PC wbdflightlist
                # 报文实测无此键（10-04 PC 报文 0 命中）——PC 恢复主路径前
                # 此两字段在此恒空转，勿据「字段恒空」误判解析链路损坏
                "fewTicket": (f.get("fewTicketStr")
                              or b1.get("fewTicketStr") or "").strip(),
                "shareCarrier": ((b1.get("mainCarrierSimpleNameAndNo") or "").strip()
                                 if b1.get("codeShare") else ""),
                # v1.5.50 决策标签（PC priceLabel，72/72 在场 27/72 非空）：
                # name 即中文决策词，取前 3 防营销词串撑爆展示位
                "labels": QunarCrawler._labels_of(f),
            })
        return out

    _LABEL_MAX = 3   # 决策标签上限

    @staticmethod
    def _labels_of(f):
        """PC priceLabel 决策标签（[{id,name,note[]}]）：name 即中文
        决策词（取消延误免费改/宠物友好/免费上网/联程航班服务…），
        id 不稳定（667 同时对应「取消延误免费改」与「郑州机场中转
        权益」）必须以 name 为准；note 长文本不落库。H5 链路无此键
        （PC 专属）——PC 软拒绝期间此字段恒空转，勿误判解析损坏。"""
        arr = f.get("priceLabel")
        if not isinstance(arr, list):
            return ""
        names = []
        for t in arr:
            n = str((t or {}).get("name") or "").strip()
            if n and n not in names:
                names.append(n)
            if len(names) >= QunarCrawler._LABEL_MAX:
                break
        return "·".join(names)

    @staticmethod
    def _merge_pc_samples(samples: list) -> list:
        """多份采样逐条目中位合并（纯函数）。

        wbdflightlist 的 minPrice 每请求重摇、响应内无任何可信度判别
        字段（priceLabel 与幻影价无关），统计中位是唯一降噪手段：
        3 份取中位，2 份取高（对幻影低价保守），单份原样（退化即现状）。
        其余字段取中位价所属样本；price 以外的 float 不动，
        多于一份时附 samples 轨迹便于事后审计。"""
        if not samples:
            return []
        # 分组键 (code, depTime)：同航班号一天两班（早晚班）按 code 单键
        # 会混池取中位——另一班整行消失、留下行价时错配（与行内 dedupe
        # 键 (code, dep_t, price) 同一前提：同号不同时刻允许并存）
        by_key, order = {}, []
        for flights in samples:
            for f in flights:
                k = (f.get("code"), f.get("depTime") or "")
                if k not in by_key:
                    by_key[k] = []
                    order.append(k)
                by_key[k].append(f)
        out = []
        for k in order:
            hits = by_key[k]
            prices = sorted(float(h["price"]) for h in hits)
            mid = prices[len(prices) // 2]
            base = next(h for h in hits if float(h["price"]) == mid)
            g = dict(base)
            g["price"] = mid
            if len(hits) > 1:
                g["samples"] = [float(h["price"]) for h in hits]
            out.append(g)
        return out

    # ==================== httpx 续航 ====================
    def _fetch_via_httpx(self, from_city: str, to_city: str, date: str) -> Optional[float]:
        """用缓存 token 直接 httpx POST，返回价格或 None。"""
        token = self._load_token()
        if not token:
            return None

        fc, tc = from_city.upper(), to_city.upper()
        from_name = self.CITY_NAME.get(fc, from_city)
        to_name = self.CITY_NAME.get(tc, to_city)

        # 基于模板构造新 body：替换城市/日期/时间戳，保留 Bella
        body = dict(token["body_template"])
        body["depCity"] = from_name
        body["arrCity"] = to_name
        body["goDate"] = date
        body["firstRequest"] = True
        body["startNum"] = 0
        body["sort"] = 5
        body["_v"] = 2
        body["underageOption"] = ""
        now_ms = int(time.time() * 1000)
        body["r"] = now_ms
        body["st"] = now_ms - 1

        headers = dict(token["headers"])
        headers["referer"] = "https://touch.qunar.com/ncs/page/flightlist"
        cookies = dict(token["cookies"])

        try:
            r = httpx.post(
                self.API_URL,
                headers=headers,
                content=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                cookies=cookies,
                timeout=25,
            )
        except Exception as e:
            self.logger.warning("[qunar] httpx 请求异常: %s", e)
            return None

        if r.status_code != 200:
            self.logger.warning("[qunar] httpx status=%d", r.status_code)
            return None

        text = r.text
        self._dump_raw_text(text, f"httpx_{from_name}_{to_name}_{date}")

        if self._is_risk_text(text):
            self.logger.warning("[qunar] httpx 命中风控(1999)，可能是限流或token过期")
            return None

        flights = self._parse_response_flights(text)
        if not flights:
            # 碎片响应仅价格无明细：裸价曾直入阈值告警并污染去抖基准
            # （0.5x 幻觉价守卫依赖明细，此路径完全裸奔）——整单拒收走重试。
            # v1.5.48 起分片形态已可还原，此路只剩真截断/风控形态
            self.logger.warning("[qunar] httpx 响应无明细，拒落价防污染")
            return None
        # 行价=本渠道明细最低价（与浏览器路径同律）：顶层 minPrice 每请求
        # 重摇、且不再参与取价——散点与明细两套来源曾造出 1-2 倍内的
        # 幻影低价窗口（渠道指纹比 p50=0.978 低价侧漂移的源头之一）
        prices = sorted({f["price"] for f in flights if f.get("price")})
        self.logger.info("[qunar] httpx 明细价格列表: %s", prices)
        return float(min(prices)), flights

    @staticmethod
    def _is_risk_text(text: str) -> bool:
        try:
            obj = json.loads(text)
        except Exception:
            return False
        bstatus = obj.get("bstatus") or {}
        if bstatus.get("code") == QunarCrawler.RISK_CODE:
            return True
        if obj.get("ret") is False and obj.get("data") is None:
            return True
        return False

    # ==================== 浏览器单条查（兜底 + 刷新 token） ====================
    def _fetch_via_browser(self, from_city: str, to_city: str, date: str) -> Optional[float]:
        """浏览器跑一次页面：拦请求刷新 token + 解析响应拿价。

        一次浏览器调用同时完成三件事：
        1. 拦截 touchInnerList 请求，存 token（headers+cookies+body模板含 Bella）
        2. 拦截响应，解析价格
        3. 返回价格
        """
        from_name = self.CITY_NAME.get(from_city.upper(), from_city)
        to_name = self.CITY_NAME.get(to_city.upper(), to_city)
        url = self.URL_TPL.format(
            from_name=urllib.parse.quote(from_name),
            to_name=urllib.parse.quote(to_name),
            date=date,
        )
        self.logger.info("[qunar] 浏览器 GET %s", url)

        snap = {
            "headers": None, "body_template": None,
            "cookies": None, "response_texts": [],
        }

        with self.browser() as ctx:
            try:
                ctx.add_init_script(self._STEALTH_JS)
            except Exception:
                pass
            page = self.new_page(ctx)

            def on_request(req):
                if "touchInnerList" in req.url and snap["headers"] is None:
                    snap["headers"] = dict(req.headers)
                    try:
                        snap["body_template"] = json.loads(req.post_data or "{}")
                    except Exception:
                        snap["body_template"] = {}
                    self.logger.info("[qunar] 拦截请求，Bella长度=%d",
                                    len(snap["body_template"].get("Bella", "")))

            def on_response(resp):
                if "touchInnerList" in resp.url:
                    try:
                        snap["response_texts"].append(resp.text())
                    except Exception:
                        pass

            page.on("request", on_request)
            page.on("response", on_response)

            try:
                page.goto(url, wait_until="load")
                # 轮询等待请求+响应都拿到
                for _ in range(12):
                    page.wait_for_timeout(2000)
                    try:
                        page.mouse.wheel(0, 1500)
                    except Exception:
                        pass
                    if snap["response_texts"]:
                        break
            except Exception as e:
                self.logger.warning("[qunar] 浏览器页面异常: %s", e)

            # 明细三级来源：①响应 data 完整形态（直接可解）
            # ②多个响应逐个试（分页/缓存形态各异）③DOM 渲染文本（永远完整）
            flights = []
            for t in snap["response_texts"]:
                flights = self._parse_response_flights(t)
                if flights:
                    break
            if not flights:
                try:
                    dom_text = page.eval_on_selector(
                        ".flight-list.flight-show-one", "el => el.innerText")
                    self._dump_raw_text(dom_text, f"dom_{from_name}_{to_name}_{date}")
                    flights = self._parse_dom_flights(dom_text, date)
                    if flights:
                        self.logger.info("[qunar] 响应为分片形态，DOM 兜底提取 %d 条",
                                         len(flights))
                except Exception:
                    pass

            # 导出 cookies
            try:
                ck = ctx.cookies()
                snap["cookies"] = {c["name"]: c["value"] for c in ck}
            except Exception:
                snap["cookies"] = {}

        # 存 token（供下次 httpx）
        if snap["headers"] and snap["body_template"] and snap["body_template"].get("Bella"):
            self._save_token(snap)
            self.logger.info("[qunar] token 已刷新，有效期 %dh", self.TOKEN_TTL_S // 3600)

        # 解析响应价格（明细为空时拒落价：与 httpx 路径同防——裸价曾
        # 绕过 0.5x 幻觉价守卫直入告警/去抖）
        if snap["response_texts"] and flights:
            text = snap["response_texts"][0]
            self._dump_raw_text(text, f"browser_{from_name}_{to_name}_{date}")
            # 行价同源自证：此前取响应文本 minPrice 散点 min()，而明细
            # 3/4 轮走 DOM 兜底（响应分片形态，10-04~06 实测 JSON 明细
            # 0 条）——散点与明细两套来源，散点里 DOM 未渲染的更低价
            # （09-25 实证散点 1288 vs DOM 明细最低 1298）会造出 1-2
            # 倍内的幻影低价窗口，0.5x 守卫拦不住。改为行价=本渠道
            # 明细最低价，行价与明细严格同源
            prices = [f["price"] for f in flights if f.get("price")]
            if prices:
                self.logger.info("[qunar] 浏览器提取价格列表: %s", sorted(set(prices)))
                return (float(min(prices)), flights)
        return None

    # ==================== token 持久化 ====================
    @property
    def _token_path(self) -> str:
        return os.path.join(self.user_data_root, self.name, "token.json")

    def _load_token(self) -> Optional[dict]:
        try:
            with open(self._token_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            return None
        updated_at = obj.get("updated_at", 0)
        if time.time() - updated_at > self.TOKEN_TTL_S:
            return None
        return obj

    def _save_token(self, snap: dict):
        os.makedirs(os.path.dirname(self._token_path), exist_ok=True)
        data = {
            "headers": snap["headers"],
            "body_template": snap["body_template"],
            "cookies": snap["cookies"],
            "updated_at": time.time(),
        }
        try:
            with open(self._token_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning("[qunar] 保存 token 失败: %s", e)

    def _dump_raw_text(self, text: str, tag: str):
        """保存原始响应文本到 debug 目录，用于排查价格异常。"""
        if not self.debug or not text:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        safe_tag = re.sub(r'[^\w]', '_', tag)
        path = os.path.join(self.debug_dir, f"qunar_raw_{safe_tag}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.logger.info("[qunar] 已保存响应: %s (len=%d)", path, len(text))
        except Exception:
            pass


    # ==================== 航班明细提取（纯 JSON 直读，零正则） ====================
    @staticmethod
    def _reassemble_h5_data(data):
        """H5 分片混淆 data 串还原（页面 t1000 同构纯函数）。

        渠道把结构化 JSON 打散成定长分片做两两置换（页内 JS join 后
        才 parse），浏览器/httpx 通道拿到的都是乱序原串——此前
        json.loads 失败即弃，3/4 轮退化 DOM 兜底（cabin/meal/托运/
        停留等结构化字段全丢）。还原算法与页面 JS 一致：counter 为
        定长切片长度（每响应变化，暴力求解）、s=counter%k 为交换步长
        （k=8 真浏览器分支、k=3 反爬降级，两分支都试）、尾部余量
        （RegExp.$'）不参与置换；还原串须过 json.loads + flights
        非空结构校验才接受。debug 六份 dump（浏览器/httpx × 未乱序/
        分片）实测 100% 还原，单次 ~12ms（1.4MB）。"""

        def _valid(obj):
            return (isinstance(obj, dict)
                    and isinstance(obj.get("flights"), list) and obj["flights"])

        if not isinstance(data, str) or not data:
            return None
        try:
            obj = json.loads(data)  # 完整/未乱序形态（counter%k==0 恒等置换）
            return obj if _valid(obj) else None
        except Exception:
            pass
        n = len(data)
        for k in (8, 3):
            for ctr in range(2, 1000):
                if ctr >= n:
                    break
                nch = n // ctr
                s = ctr % k
                # 预筛：还原后首块必来自原第 s 块（"{" 开头），假阳性
                # 由 _valid 的结构校验兜底
                src = s if (s and s < nch) else 0
                if data[src * ctr: src * ctr + 2] != '{"':
                    continue
                frags = [data[i:i + ctr] for i in range(0, n - ctr + 1, ctr)]
                suffix = data[len(frags) * ctr:]
                i, j = 0, s
                while j < len(frags):
                    frags[i], frags[j] = frags[j], frags[i]
                    i, j = j + 1, j + 1 + s
                try:
                    obj = json.loads("".join(frags) + suffix)
                except Exception:
                    continue
                if _valid(obj):
                    return obj
        return None

    @staticmethod
    def _parse_response_flights(text):
        """从完整响应文本解析航班明细。

        data 为字符串化 JSON：完整形态直接可解；分片混淆形态由
        _reassemble_h5_data 还原（v1.5.48 起 DOM 兜底降级为真兜底）；
        真截断/风控形态返回 []。"""
        try:
            outer = json.loads(text)
        except Exception:
            return []
        data = outer.get("data") if isinstance(outer, dict) else outer
        if isinstance(data, str):
            data = QunarCrawler._reassemble_h5_data(data)
            if data is None:
                return []
        trend = None
        if isinstance(data, dict):
            trend = data.get("trendPrice")
            data = data.get("flights") or []
        if not isinstance(data, list):
            return []
        out = QunarCrawler._extract_flights_obj(data)
        tg = QunarCrawler._parse_trend_go(trend)
        if tg and out:
            # route 级买票时机曲线（goFTrend=D-7..D+7 最低价 15 点）只挂
            # 当轮最低价行：逐行重复 ≈ 每轮 +300B×75 行 extra 膨胀，挂
            # 一行即可代表全轮（H5 现役主路径在场，PC 报文无此键）
            lo = min(out, key=lambda f: f.get("price") or 9e9)
            lo["trendGo"] = tg
        return out

    @staticmethod
    def _parse_trend_go(trend):
        """trendPrice.goFTrend → [["MM-DD",价],…]（买票时机曲线数据源）。

        逐点结构校验宁缺勿错：price 是字符串；10-04 dump 曾见渠道侧
        数组截断接缝（index 4 后混入 AB 配置文本），坏点直接丢弃。
        单程国内无 backFTrend（0 命中），出现时留待后续。"""
        if not isinstance(trend, dict):
            return None
        arr = trend.get("goFTrend")
        if not isinstance(arr, list):
            return None
        out = []
        for p in arr:
            if not isinstance(p, dict):
                continue
            d = str(p.get("date") or "").strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                continue
            try:
                v = float(p.get("price"))
            except (TypeError, ValueError):
                continue
            if not (100 <= v <= 50000):
                continue
            out.append([d[5:], round(v)])
        return out or None

    @staticmethod
    def _extract_flights_obj(flights_raw):
        """flights 数组 → 统一航班明细。

        字段语义（实测）：直飞时刻在 binfo，中转在 binfo1/binfo2
        （binfoX 的 dep/arr 即整体起终）；code 含 / 为中转；
        mixFlightName 首段为中转显示名；transTime 为全程时长。"""
        out, seen = [], set()
        for f in flights_raw:
            if not isinstance(f, dict):
                continue
            try:
                price = float(f.get("minPrice") or 0)
            except (TypeError, ValueError):
                continue
            if not (300 <= price <= 50000):
                continue
            code = (f.get("code") or f.get("flightKey") or "").strip()
            if not code:
                continue
            info = f.get("binfo") or f.get("binfo1") or {}
            b2 = f.get("binfo2") or {}
            dep_t = (info.get("depTime") or "").strip()
            arr_t = (info.get("arrTime") or "").strip()
            dep_d = (info.get("depDate") or "").strip()
            arr_d = (info.get("arrDate") or "").strip()
            if not (dep_t and arr_t and dep_d and arr_d):
                continue
            key = (code, dep_t, price)
            if key in seen:
                continue
            seen.add(key)
            mix_raw = (f.get("mixFlightName") or "").splitlines()
            mix = mix_raw[0].strip() if mix_raw else ""
            trans = (f.get("transCity") or "").strip()
            if isinstance(b2, dict) and b2 and not trans:
                trans = "中转"   # binfo2 在场即中转，防 transCity 缺省被误分直飞
            # 中转衔接：第二段起飞 − 第一段到达（跨天回绕）——H5 结构
            # 中 binfo1.arr 即第一段到达、binfo2.dep 即第二段起飞。
            # 假衔接源头掐灭（5/5 真实样本验证）：H5 的 binfo2 是 binfo1
            # 的复制，binfo2.depTime == binfo1.depTime == 整体起飞时刻，
            # 此时 (dep−arr)%1440 = 1440−全程 的回绕垃圾（全程>12.5h 时
            # 绕过 normalize 物理守卫，线上 345 条假「停 X:XX」实锤）——
            # 缺独立第二段时刻或与整体起飞相同都弃算（宁缺勿错）
            lay = ""
            b2_dep = (b2.get("depTime") if isinstance(b2, dict) else "") or ""
            b1_arr = info.get("arrTime") or ""
            # 整体到达防御（v1.5.41）：b2 真独立（第二段起飞≠整体起飞）
            # 时 binfo1.arr 是首段到达、binfo2.arr 才是整体到达（PC 语义
            # 「binfoX 的 dep/arr 即整体起终」在分段态以二段为准）——
            # 防渠道未来下发真分段时整体到达被首段污染；复制态 b2.arr
            # ==info.arr 取谁等价，行为不变
            if b2_dep and b2_dep != dep_t:
                b2_arr = (b2.get("arrTime")
                          if isinstance(b2, dict) else "") or ""
                if b2_arr:
                    arr_t = b2_arr
                b2_arrd = (b2.get("arrDate")
                           if isinstance(b2, dict) else "") or ""
                if b2_arrd:
                    arr_d = b2_arrd
            if b2_dep and b1_arr and b2_dep != dep_t:
                def _hm(s):
                    try:
                        h, m = str(s).strip().split(":")
                        return int(h) * 60 + int(m)
                    except (ValueError, TypeError):
                        return None
                a1, d2 = _hm(b1_arr), _hm(b2_dep)
                if a1 is not None and d2 is not None:
                    lay = (d2 - a1) % 1440
                    # %1440 回绕只在 depDate→arrDate 跨度 ≤1 天时可信：
                    # span≥2 天的 ~25h 真实停留会被回绕成 60min 假值
                    span = _span_days(dep_d, arr_d)
                    if span >= 2 and lay < 300:
                        lay = ""
            # v1.5.48：binfo1.transInfo 是渠道结构化真值（首末段四段
            # 时刻+transTime 停留+中转城；分片重组后中转行 100% 在场，
            # 直飞行无此键），中转行直接采信——上面 binfo2 猜衔接链路
            # 降为无 transInfo 时的兜底（binfo2 是 binfo1 复制、整体
            # 时刻口径，只能算不能信）；lay2dep 同步换真二段起飞时刻
            # （旧值=binfo2.depTime=整体起飞，明细「二段 X 起飞」曾
            # 一直显示整体起飞时刻）
            lay2dep = ((b2.get("depTime")
                        if isinstance(b2, dict) else "") or "").strip()
            ti = info.get("transInfo")
            lay_src = ""
            if isinstance(ti, dict) and ti and trans:
                try:
                    from core.flightnorm import dur_min as _cn_min
                    tm = _cn_min(ti.get("transTime"))
                except Exception:
                    tm = None
                if tm and tm > 0:
                    lay = tm
                    lay_src = "transInfo"
                    sdi = ti.get("secondDepInfo") or {}
                    if isinstance(sdi, dict) and sdi.get("time"):
                        lay2dep = str(sdi["time"]).strip()
            # 经停城市/机场（v1.5.37 修订旧注释误判）：H5 实际键名为复数
            # stopsCitys/stopsAirPort，字符串形态挂 binfo1/binfo2 层
            # （binfo2 常是 binfo1 复制，两级互为兜底）；9/25-10/06 六份
            # 报文实测全为空串、真值分隔符未采样到，按 PC 口径把常见
            # 分隔符归一为「;」透传
            sc = ((info.get("stopsCitys") or b2.get("stopsCitys") or "")
                  .strip().replace(",", ";"))
            sa = ((info.get("stopsAirPort") or b2.get("stopsAirPort") or "")
                  .strip().replace(",", ";"))
            meal, baggage = _meal_from_addons(
                f.get("flightAddInfoIntegration"))
            # ---- v1.5.49 决策字段补采（10-05 dump 71 行实证）----
            # extparams 以 JSON 字符串下发（71/71 在场），解析一次供
            # 儿童/婴儿价、折扣、退改规则取用；解析失败静默跳过不造默认值
            epd = None
            _ep = f.get("extparams")
            if isinstance(_ep, str) and _ep:
                try:
                    epd = json.loads(_ep)
                except Exception:
                    epd = None
            # 航站楼（binfo1.depTerminal/arrTerminal 同层直读；H5 直飞行
            # 信息挂 binfo、中转挂 binfo1/binfo2，info 取 binfo or binfo1
            # 天然覆盖）：仅多航站楼一侧有值（乌→沪 arr 71/71 T1/T2、
            # dep 0/71；沪→乌 dep 75/75、arr 0/75——单航站楼侧渠道下发
            # 空串/缺键），留空不造；中转行 transInfo.firstArrInfo/
            # secondDepInfo/secondArrInfo.terminal 一期不采（保持字段
            # 单值口径）
            dep_term = (info.get("depTerminal") or "").strip()
            arr_term = (info.get("arrTerminal") or "").strip()
            # 儿童/婴儿价（extparams.childPrice/infantPrice，数值）：0 为
            # 「未报价」占位（childPrice 35/71 行为 0，中转/全价行），
            # 仅收正数（_pos_num）
            child_price = (_pos_num(epd.get("childPrice"))
                           if isinstance(epd, dict) else None)
            infant_price = (_pos_num(epd.get("infantPrice"))
                            if isinstance(epd, dict) else None)
            # 折扣（extparams.listLowestCabinDiscount "4.6" 数值串，
            # 71/71 在场）→ 落既有键名 discount（PC discountStr 同键，
            # flightnorm.cabin_text/report 图均按此消费），"4.6" 拼
            # 「4.6折」对齐 PC 值形态（report 图折扣只认「N.N折」）；
            # 合理域 [0.5,10]（脏值弃，与 ctrip drate 同律）
            disc_txt = ""
            if isinstance(epd, dict):
                try:
                    _lc = float(epd.get("listLowestCabinDiscount"))
                    disc_txt = f"{_lc:g}折" if 0.5 <= _lc <= 10 else ""
                except (TypeError, ValueError):
                    disc_txt = ""
            # 退改（extparams.refundChangeRule，嵌套 JSON 串 47/71 在场，
            # 内含 returnFee/changeFee/timeStamp）：只收前两键成短 JSON
            # 串（协议定版 {"returnFee":N,"changeFee":M}），changeFee=-1
            # 为渠道「不可改」语义如实透传；无值不落键
            refund_txt = ""
            if isinstance(epd, dict):
                _rcr = epd.get("refundChangeRule")
                if isinstance(_rcr, str) and _rcr:
                    try:
                        _rj = json.loads(_rcr)
                    except Exception:
                        _rj = None
                    if isinstance(_rj, dict):
                        _fee = {k: _rj[k] for k in ("returnFee", "changeFee")
                                if k in _rj}
                        if _fee:
                            refund_txt = json.dumps(
                                _fee, ensure_ascii=False,
                                separators=(",", ":"))
            # 中转行李直挂新源（flightMark.freeLuggage 布尔，71/71 在场，
            # True 55/False 16，9C 春秋恒 False 自洽）：语义推断——
            # freeLuggage=免费托运 → 推断两段可直挂，非实测直挂证据；
            # 仅中转行置 direct（直飞行无直挂概念），bag_direct 哨兵线上
            # 观测兜底，若命中率异常下轮回滚
            trans_bag = ("direct"
                         if (trans and (f.get("flightMark") or {})
                             .get("freeLuggage") is True) else "")
            row = {
                "price": price,
                "code": code,
                "name": mix or code,
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                "transCity": trans,
                "crossDayDesc": (f.get("crossDayDesc") or "").strip(),
                "totalDuration": (f.get("transTime") or "").strip(),
                "layover": lay,
                "lay2dep": lay2dep,
                # 停留来源标记：transInfo=渠道结构化真值（flightnorm 对
                # 该来源跳过 1440 回绕启发判伪——真值跨天长停留恰落在
                # 击杀区，dump 实测 3/150 误杀）；空=旧猜衔接链路兜底
                "layoverSrc": lay_src,
                # 决策字段移植（9/25 完整 H5 报文 75 行实测，勿照抄 PC 键名）：
                # H5 无 binfo.cabin → binfo1.cabinDegree 是同义舱位代码
                # （26/26 中转行有值 T/Q/E/...，直飞行 None）；H5 无
                # mealDesc → 餐食在 flightAddInfoIntegration.flightAdditionInfos[]
                # （正餐/有餐食/无餐食/点心...）；经停城市键实为复数
                # stopsCitys/stopsAirPort（旧注释误判「无 stopCitys 键」），
                # 无 stopTime 键、extparams.stops 是布尔非数组（无停留
                # 分钟可转）；planeType/transitServiceLabel 键仍无
                # （flightMark.planeType 75/75 空串）不移植；经停标记走
                # extparams.stopFlight 布尔（6/6 与 DOM「停」行交叉一致）
                # → normalize 产 stopover
                "cabin": (info.get("cabinDegree") or "").strip(),
                # v1.5.48 新决策字段：余票紧张标签（值域实测仅「票少」）
                "fewTicket": (f.get("fewTicketStr") or "").strip(),
                # 共享航班实际承运（仅展示，不入指纹）：营销号 code 的
                # 真实执飞航司+航班号，如「上航FM9224」
                "shareCarrier": ((info.get("mainCarrierSimpleNameAndNo") or "").strip()
                                 if info.get("codeShare") else ""),
                "meal": meal,
                "baggage": baggage,
                "stopCitys": sc,
                "stopAirports": sa,
                "stopFlight": QunarCrawler._stopflight(f.get("extparams")),
                # v1.5.49 新决策字段（上面注释块：键路径 + dump 命中率）
                "depTerminal": dep_term,
                "arrTerminal": arr_term,
                "discount": disc_txt,
                "transferBaggage": trans_bag,
            }
            # 数值/JSON 串型字段无值不落键（childPrice/infantPrice 为数值
            # 协议、refundChange 为定版短 JSON 串，空串语义不明宁缺勿错）
            if child_price is not None:
                row["childPrice"] = child_price
            if infant_price is not None:
                row["infantPrice"] = infant_price
            if refund_txt:
                row["refundChange"] = refund_txt
            out.append(row)
        return out

    @staticmethod
    def _stopflight(ep):
        """extparams 渠道现以 JSON 字符串下发，升级为对象时子串匹配
        静默 False → H5 兜底经停班全判直飞：两种形态都认。"""
        if isinstance(ep, str):
            return '"stopFlight":true' in ep
        if isinstance(ep, dict):
            return bool(ep.get("stopFlight"))
        return False

    # ==================== DOM 兜底（touch 页渲染后列表） ====================
    _RE_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
    # 价格容千分位（"1,234"——渠道改格式时整渠道曾静默空转）
    _RE_PRICE = re.compile(r"^[￥¥]?(\d{1,3}(?:,\d{3})+|\d{3,5})$")
    _RE_FNO = re.compile(r"[\u4e00-\u9fa5]{0,6}((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})")
    # 航班号合规校验（v1.5.47 联程混淆码守卫）：IATA 号=两位航司码+
    # 3-4 位数字。「华夏航G581O1J」被 _RE_FNO 回溯截成假号 G581——
    # 任何渠道都查不到，却进了指纹与推送文案（「中转华夏航G581」）
    _RE_FNO_V = re.compile(r"^[A-Z0-9]{2}\d{3,4}$")
    _RE_DUR = re.compile(r"^(\d+)h(?:(\d+)m)?$")

    @classmethod
    def _parse_dom_flights(cls, text: str, date: str) -> list:
        """解析列表容器 innerText（渲染后 DOM）为航班明细。

        页面数据接口的 data 常为分片混淆体（页面 JS join 后才 parse），
        但渲染后的 DOM 文本永远完整。每班字段按行排列（2026-09 实测）：
        直飞  HH:MM|机场|N时M分|(+N天)?|HH:MM|机场|航司 机型|价格
        中转  HH:MM|机场|NhMm|转|中转城市|(+N天)?|HH:MM|机场|航司(空格分隔多段)|价格
              （时长为 h/m 形态且只有全程一个时长段；无二段起飞时刻）
        经停  HH:MM|机场|N时(分)?|停|(+N天)?|HH:MM|...
        价格后可能跟「票少」等尾注，跳过。"""
        from datetime import datetime as _dt, timedelta as _td
        out, seen = [], set()
        cur = None

        def close():
            nonlocal cur
            f = cur
            cur = None
            if not f or "price" not in f or "arrTime" not in f:
                return
            if not (300 <= f["price"] <= 50000):
                return
            codes = f.pop("_codes")
            bad = f.pop("_code_bad", False)
            code = "/".join(codes)
            if not code and not bad:
                return    # 无航司名行的杂段照旧丢弃；混淆码真班保留
            f["code"] = code
            key = (code, f["depTime"], f["price"])
            if key in seen:
                return
            seen.add(key)
            cross = f.pop("_cross", "")
            try:
                d0 = _dt.strptime(date, "%Y-%m-%d")
                f["depDate"] = d0.strftime("%Y-%m-%d")
                days = int(cross[1]) if cross else 0
                f["arrDate"] = (d0 + _td(days=days)).strftime("%Y-%m-%d")
            except ValueError:
                f["depDate"], f["arrDate"] = date, ""
            f["crossDayDesc"] = cross
            f.setdefault("transCity", "")
            f.setdefault("totalDuration", "")
            out.append(f)

        for raw in text.split("\n"):
            seg = raw.strip()
            if not seg or seg.startswith("【"):
                continue
            if cur is None:
                if cls._RE_HHMM.match(seg):
                    cur = {"depTime": seg, "_codes": []}
                continue
            if cls._RE_HHMM.match(seg):
                # 到达时刻到来：暂存的时长段是全程（直飞行）
                if "_pend" in cur:
                    p = cur.pop("_pend")
                    cur["totalDuration"] = f"{p // 60}时{p % 60:02d}分"
                if "arrTime" in cur:
                    close()          # 新一班开始（上一班缺价格被丢弃）
                    cur = {"depTime": seg, "_codes": []}
                else:
                    cur["arrTime"] = seg
                continue
            if cls._RE_PRICE.match(seg) and "arrTime" in cur:
                if "_pend" in cur:   # 价格前把悬挂的时长段落为全程
                    p = cur.pop("_pend")
                    cur["totalDuration"] = f"{p // 60}时{p % 60:02d}分"
                cur["price"] = float(
                    cls._RE_PRICE.match(seg).group(1).replace(",", ""))
                close()
                continue
            if seg in ("票少", "熊"):
                continue
            if seg in ("转", "停") or "联程" in seg:
                # 中转/经停行 DOM 文本里唯一的时长段是全程时长（实测
                # "10h55m 转 西安 +1天 09:55" = 23:00→09:55 全程），
                # 真实停留时长页面列表不渲染——留空不作假
                if "_pend" in cur:
                    p = cur.pop("_pend")
                    cur["totalDuration"] = f"{p // 60}时{p % 60:02d}分"
                cur["_via"] = "转" if seg != "停" else "停"
                continue
            if re.match(r"^\+\d+天$", seg):
                if "_pend" in cur:
                    p = cur.pop("_pend")
                    cur["totalDuration"] = f"{p // 60}时{p % 60:02d}分"
                cur["_cross"] = seg
                continue
            if cls._RE_DUR.match(seg) or re.match(r"^(\d+)时(\d+)?分?$", seg):
                mm = cls._RE_DUR.match(seg)
                if mm:
                    h, m = mm.groups()
                    cur["_pend"] = int(h) * 60 + int(m or 0)
                else:
                    mm2 = re.match(r"^(\d+)时(\d+)?分?$", seg)
                    cur["_pend"] = int(mm2.group(1)) * 60 + int(mm2.group(2) or 0)
                continue
            # 机场名消歧行只出现在「转/停」标记之前；标记后的同形行是
            # 中转城市（乌鲁木齐=URC 最常见中转城市，硬编码跳过曾致 URC
            # 中转班 transCity 永缺、整行判直飞）
            if not cur.get("_via") and seg.startswith(("浦东", "虹桥", "乌鲁木齐")):
                continue
            fnos = cls._RE_FNO.findall(seg)
            if fnos:
                # 联程混淆码守卫（v1.5.47）：段内存在不合规号（「华夏航
                # G581O1J」被 _RE_FNO 回溯截成假号 G581，任何渠道都查
                # 不到却进了指纹与推送文案）→ 整段置空 code、name 保留
                # 原文；价格/时刻真实不动，行保留（close 依 _code_bad）
                if any(not cls._RE_FNO_V.match(c) for c in fnos):
                    cur["name"] = seg
                    cur["_codes"] = []
                    cur["_code_bad"] = True
                else:
                    head = cls._RE_FNO.search(seg).group(0)
                    cur["name"] = head
                    cur["_codes"].extend(fnos)
                # 名行自带机型（v1.5.43）：DOM 名行「春秋9C8866 空客321(中)」
                # 实证 40 行含机型 token，此前整段只取航班号——plane 98%
                # 缺口的单渠道自源修复主力（快照统计 波音737(中)×25/
                # 空客321×8/空客320×4/空客330×1）
                if "plane" not in cur:
                    mpn = re.search(r"(?:波音|空客)\d{2,3}(?:\([中小大]\))?",
                                    seg)
                    if mpn:
                        cur["plane"] = mpn.group(0)
                continue
            if cur.get("_via") == "转" and not cur.get("transCity"):
                cur["transCity"] = seg
                continue
        close()
        # 幻影价守卫（v1.5.44，fliggy 中位锚同思想移植）：明细中位数作
        # 群体锚，单行价 < 中位×0.5 视为页面异源模块污染弃行。本路径此前
        # 零群体防线——价格行即 close、第二价格行静默丢弃，但页面尾部
        # 推荐/日历模块凑齐「时刻+航班号+价格」即可造出幻影低价行
        # （fliggy CA8564 同构事故；合法跨舱位双价与明细群同量级不误伤）
        if len(out) >= 4:
            med = sorted(f["price"] for f in out)[len(out) // 2]
            kept = [f for f in out if f["price"] >= med * 0.5]
            for f in out:
                if f["price"] < med * 0.5:
                    _LOG.warning("[qunar] DOM 幻影价守卫弃行 %s ￥%.0f"
                                 "（< 明细中位 ￥%.0f 的 0.5x，页面异源"
                                 "模块污染）", f.get("code"), f["price"], med)
            out = kept
        return out
