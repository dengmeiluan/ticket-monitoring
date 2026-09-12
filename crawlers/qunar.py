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
import os
import re
import json
import time
import urllib.parse
from collections import Counter
from datetime import datetime
from typing import List, Optional

import httpx

from core.models import FlightPrice
from .base import BaseCrawler


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
                    snap["texts"].append(resp.text())
                except Exception:
                    pass

        self.logger.info("[qunar] 浏览器 GET %s", url[:120])
        bak = self.use_mobile
        self.use_mobile = False
        try:
            with self.browser(headless=self.headless) as ctx:
                page = self.new_page(ctx)
                page.on("response", on_resp)
                try:
                    page.goto(url, wait_until="load")
                    for _ in range(12):
                        page.wait_for_timeout(2000)
                        try:
                            page.mouse.wheel(0, 1500)
                        except Exception:
                            pass
                        if snap["texts"]:
                            break
                except Exception as e:
                    self.logger.warning("[qunar] PC 页面异常: %s", e)
        finally:
            self.use_mobile = bak
        if snap["texts"]:
            self._dump_raw_text(snap["texts"][0],
                                f"pc_{from_name}_{to_name}_{date}")
        for t in snap["texts"]:
            flights = self._parse_pc_flights(t, date)
            if flights:
                best = min(flights, key=lambda x: x["price"])
                self.logger.info("[qunar] PC 命中（wbdflightlist，明细 %d 条）",
                                 len(flights))
                return (float(best["price"]), flights)
        if snap["texts"]:
            self.logger.warning("[qunar] PC 接口有响应但未解析出明细")
        return None

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
            if not (dep_t and arr_t):
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
                # 中转停留 = 全程时长 - 两段飞行时长（决策关键：停多久）
                try:
                    from core.flightnorm import dur_min as _dm
                    t_m = _dm(dur)
                    f1_m = _dm(b1.get("flightTime"))
                    f2_m = _dm(b2.get("flightTime"))
                    if t_m and f1_m and f2_m and t_m - f1_m - f2_m > 0:
                        lay = t_m - f1_m - f2_m
                except Exception:
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
                "transCity": (f.get("transCity") or "").strip(),
                "crossDayDesc": (f.get("crossDayDesc") or "").strip(),
                "totalDuration": dur,
                "cabin": (b1.get("cabin") or "").strip(),
                "discount": (f.get("discountStr") or "").strip(),
                "layover": lay,
                "plane": (b1.get("planeType") or "").strip(),
            })
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

        prices = self._extract_qunar_prices(text)
        if not prices:
            self.logger.warning("[qunar] httpx 响应无价格，len=%d", len(text))
            return None
        self.logger.info("[qunar] httpx 提取价格列表: %s", sorted(set(prices)))
        return float(min(prices)), self._parse_response_flights(text)

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

        # 解析响应价格
        if snap["response_texts"]:
            text = snap["response_texts"][0]
            self._dump_raw_text(text, f"browser_{from_name}_{to_name}_{date}")
            prices = self._extract_qunar_prices(text)
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

    # ==================== 价格解析 ====================
    @staticmethod
    def _extract_qunar_prices(text: str) -> list:
        """解析 touchInnerList JSON，提取航班最低价。

        去哪儿接口 data 字段是字符串化的 JSON（引号被转义为 \\"）。
        实测只有 minPrice 字段可信（航班最低价，与 DOM 渲染价一致）；
        totalPrice 字段含非价格数据（如 "127b"、4、42 等编码/附加费），
        不可作为价格候选。

        解析优先级：
        1) json.loads 全量解析 data 字符串，递归取 minPrice
        2) 兜底正则（兼容转义引号 \\" 形式）只取 minPrice
        """
        if not text:
            return []
        try:
            obj = json.loads(text)
        except Exception:
            return QunarCrawler._regex_extract_prices(text)

        data = obj.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return QunarCrawler._regex_extract_prices(text)
        if not isinstance(data, dict):
            return QunarCrawler._regex_extract_prices(text)

        prices: list = []

        # 1) 顶层 minPrice（最可信，实测与 DOM 渲染价一致）
        v = data.get("minPrice")
        try:
            iv = int(float(v))
            if 300 <= iv <= 50000:
                prices.append(iv)
        except Exception:
            pass
        if prices:
            return prices

        # 2) 递归遍历航班节点，只取 minPrice（totalPrice 含非价格数据）
        def scan(node):
            if isinstance(node, dict):
                v = node.get("minPrice")
                if v is not None:
                    try:
                        iv = int(float(v))
                        if 300 <= iv <= 50000:
                            prices.append(iv)
                    except Exception:
                        pass
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        scan(v)
            elif isinstance(node, list):
                for v in node:
                    scan(v)

        scan(data)
        if prices:
            return prices

        # 3) 兜底正则
        return QunarCrawler._regex_extract_prices(text)

    @staticmethod
    def _regex_extract_prices(text: str) -> list:
        """正则兜底：只取 minPrice，要求值后跟引号闭合（排除 "127b" 等非数字值）。

        实测 totalPrice 字段含 "127b"、"4" 等非价格数据，
        故正则只匹配 minPrice 且要求数字后紧跟引号。
        """
        prices: list = []
        # minPrice":"910" 或 minPrice\":\"910\"  要求数字后有引号闭合
        for m in re.finditer(
            r'minPrice\\?["\']\s*:\s*\\?["\'](\d{3,5})\\?["\']',
            text,
        ):
            try:
                prices.append(int(m.group(1)))
            except Exception:
                pass
        return [p for p in prices if 300 <= p <= 50000]


    # ==================== 航班明细提取（纯 JSON 直读，零正则） ====================
    @staticmethod
    def _parse_response_flights(text):
        """从完整响应文本解析航班明细。

        data 为字符串化 JSON：浏览器通道完整可解；httpx 通道是截断
        碎片（页面 JS 才能拼接），解析失败返回 []，由浏览器轮补充。"""
        try:
            outer = json.loads(text)
        except Exception:
            return []
        data = outer.get("data") if isinstance(outer, dict) else outer
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return []
        if isinstance(data, dict):
            data = data.get("flights") or []
        if not isinstance(data, list):
            return []
        return QunarCrawler._extract_flights_obj(data)

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
            out.append({
                "price": price,
                "code": code,
                "name": mix or code,
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                "transCity": (f.get("transCity") or "").strip(),
                "crossDayDesc": (f.get("crossDayDesc") or "").strip(),
                "totalDuration": (f.get("transTime") or "").strip(),
            })
        return out

    # ==================== DOM 兜底（touch 页渲染后列表） ====================
    _RE_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
    _RE_PRICE = re.compile(r"^\d{3,5}$")
    _RE_FNO = re.compile(r"[\u4e00-\u9fa5]{0,6}((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})")
    _RE_DUR = re.compile(r"^(\d+)h(\d+)m$")

    @classmethod
    def _parse_dom_flights(cls, text: str, date: str) -> list:
        """解析列表容器 innerText（渲染后 DOM）为航班明细。

        页面数据接口的 data 常为分片混淆体（页面 JS join 后才 parse），
        但渲染后的 DOM 文本永远完整。每班字段按行排列：
        直飞  HH:MM|机场|N时M分|(+N天)?|HH:MM|机场|航司航班号|价格
        中转  HH:MM|机场|NhMm|转/联程|中转城市|+N天|HH:MM|机场|航司(多段｜分隔)|价格
        经停  HH:MM|机场|N时?|停|(+N天)?|HH:MM|...
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
            code = "/".join(f.pop("_codes"))
            if not code:
                return
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
                if "arrTime" in cur:
                    close()          # 新一班开始（上一班缺价格被丢弃）
                    cur = {"depTime": seg, "_codes": []}
                else:
                    cur["arrTime"] = seg
                continue
            if cls._RE_PRICE.match(seg) and "arrTime" in cur:
                cur["price"] = float(seg)
                close()
                continue
            if seg in ("票少", "熊"):
                continue
            if seg in ("转", "停") or "联程" in seg:
                cur["_via"] = "转" if seg != "停" else "停"
                continue
            if re.match(r"^\+\d+天$", seg):
                cur["_cross"] = seg
                continue
            if cls._RE_DUR.match(seg):
                h, m = cls._RE_DUR.match(seg).groups()
                cur["totalDuration"] = f"{h}时{m}分"
                continue
            m = re.match(r"^(\d+)时(\d+)?分?$", seg)
            if m:
                cur["totalDuration"] = f"{m.group(1)}时{m.group(2) or 0}分"
                continue
            if seg.startswith(("浦东", "虹桥", "乌鲁木齐")):
                continue
            fnos = cls._RE_FNO.findall(seg)
            if fnos:
                head = cls._RE_FNO.search(seg).group(0)
                cur["name"] = head
                cur["_codes"].extend(fnos)
                continue
            if cur.get("_via") == "转" and not cur.get("transCity"):
                cur["transCity"] = seg
                continue
        close()
        return out
