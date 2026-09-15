# -*- coding: utf-8 -*-
"""飞猪机票爬虫（PC SSR 版，2026-09-09 重写）

背景：移动端 mtop.trip.flight.flightSearch v1.0 已被官方下线
（NOT_SUPPORT），新版走 serverless 网关+强制登录，无法低成本接入。
发现：PC 搜索结果页 sjipiao.fliggy.com 为服务端直出（SSR）——
航班列表直接渲染在 HTML/DOM 中，无需接口，滚动收集 innerText
按行状态机解析即可（与 qunar DOM 兜底同套路）。

注意：PC 页价格口径为「不含税费」的展示价，与含税渠道差约
￥50-130，参与比价时天然略偏优——展示层飞猪标注税前。
页面仅含直达+经停（经停不换机视为直达），中转由其他渠道覆盖。
"""
import json
import re
from typing import List

from .base import BaseCrawler
from .qunar import QunarCrawler as _Q
from core.models import FlightPrice


class FliggyCrawler(BaseCrawler):
    name = "fliggy"
    use_mobile = False  # 桌面 UA（PC SSR 页面）

    URL_TPL = ("https://sjipiao.fliggy.com/flight_search_result.htm"
               "?tripType=0&depCity={fc}&arrCity={tc}&depDate={d}"
               "&depCityName={fn}&arrCityName={tn}")

    _RE_FNO = re.compile(
        r"([\u4e00-\u9fa5]{1,3})?((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})$")
    _RE_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d")
    _RE_ARR = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d(?:\s*第(\d)天)?$")
    _RE_PRICE = re.compile(r"[¥￥]\s*(\d{3,5})")

    def login_url(self) -> str:
        return "https://www.fliggy.com/"

    # ==================== 主流程 ====================
    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        results: List[FlightPrice] = []
        fc, tc = from_city.upper(), to_city.upper()
        for date in dates:
            flights = self._fetch_pc(fc, tc, date)
            if flights:
                best = min(flights, key=lambda f: f["price"])
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=best.get("name", "")[:20],
                    flight_no=best.get("code", ""),
                    depart_time=best.get("depTime", ""),
                    arrive_time=best.get("arrTime", ""),
                    extra=json.dumps(flights, ensure_ascii=False),
                ))
                self.logger.info(
                    "[fliggy] %s 最低价 ￥%.0f（PC 明细 %d 条）",
                    date, best["price"], len(flights))
            else:
                self.logger.warning("[fliggy] %s PC 页未解析到航班", date)
            self._sleep()
        return results

    def _fetch_pc(self, fc: str, tc: str, date: str) -> list:
        import urllib.parse
        url = self.URL_TPL.format(
            fc=fc, tc=tc, d=date,
            fn=urllib.parse.quote(_Q.CITY_NAME.get(fc, fc)),
            tn=urllib.parse.quote(_Q.CITY_NAME.get(tc, tc)))
        texts = set()
        with self.browser() as ctx:
            page = self.new_page(ctx)
            try:
                page.goto(url, wait_until="load", timeout=40000)
                last_len, stale = 0, 0
                for _ in range(8):   # 虚拟列表逐屏收集，收敛即提前退出
                    page.wait_for_timeout(3000)
                    try:
                        page.mouse.wheel(0, 1200)
                    except Exception:
                        pass
                    txt = page.inner_text("body")
                    texts.add(txt)
                    if len(txt) == last_len:
                        stale += 1
                        if stale >= 2:   # 连续两屏内容不变=列表到底
                            break
                    else:
                        stale = 0
                    last_len = len(txt)
            except Exception as e:
                self.logger.warning("[fligpy] PC 页面异常: %s", e)
        full = "\n@@@\n".join(texts)
        return self._parse_pc_text(full, date)

    # ==================== 解析：行状态机 ====================
    @classmethod
    def _parse_pc_text(cls, text: str, date: str) -> list:
        """PC 页 innerText 行序（实测）：
        航班名行（东航MU8369 / 9C8945）
          → 机型行（中型机 737 共享|经停|）
          → 出发 HH:MM
          → 到达 HH:MM [第N天]
          → 起飞机场 / 到达机场
          → [准点率%]
          → ¥价格 [折扣] / 余票 / 订票
        """
        from datetime import datetime as _dt, timedelta as _td
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        out, cur = [], None
        d0 = _dt.strptime(date, "%Y-%m-%d")
        for i, ln in enumerate(lines):
            m = cls._RE_FNO.match(ln)
            if m and len(ln) <= 14 and not ln.startswith(("第", "星期")):
                if cur and "price" in cur:
                    out.append(cur)
                cur = {"name": ln, "code": m.group(2), "_i": i,
                       "transCity": "", "depDate": date}
                continue
            if cur is None or "price" in cur:
                continue
            if cls._RE_HHMM.match(ln) and "depTime" not in cur:
                cur["depTime"] = ln
                continue
            ma = cls._RE_ARR.match(ln) if "depTime" in cur else None
            if ma:
                cur["arrTime"] = ln[:5]
                days = int(ma.group(2)) - 1 if ma.group(2) else 0
                cur["arrDate"] = (d0 + _td(days=days)).strftime("%Y-%m-%d")
                cur["crossDayDesc"] = f"+{days}天" if days else ""
                continue
            if ln in ("经济舱", "公务舱", "头等舱", "商务舱") and "cabin" not in cur:
                cur["cabin"] = ln
                continue
            pm = cls._RE_PRICE.search(ln)
            if pm and "arrTime" in cur:
                cur["price"] = float(pm.group(1))
                continue
        if cur and "price" in cur:
            out.append(cur)
        # 去重（多屏收集同航班）与清理
        seen, clean = set(), []
        for f in out:
            f.pop("_i", None)
            f.setdefault("totalDuration", "")
            key = (f["code"], f.get("depTime"), f["price"])
            if key in seen:
                continue
            seen.add(key)
            clean.append(f)
        return clean
