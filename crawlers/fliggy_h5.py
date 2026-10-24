# -*- coding: utf-8 -*-
"""Fliggy Taobao-H5 data path (separate login slot).

The H5 page is a custom React app. We drive the visible route/date form,
capture the real ``*listingsearch`` mtop response, and parse only rows that
actually carry a flight number and price. No response -> no rows.
"""
import json
import os
import time
from typing import List

from core.intl import city_short_of, is_intl_route
from core.models import FlightPrice
from .base import BaseCrawler
from .challenge import classify_text

try:
    from core.channel_links import PLAT_NAME
except Exception:  # pragma: no cover
    PLAT_NAME = {}

H5_SEARCH_URL = ("https://market.m.taobao.com/app/trip/rx-traffic-search/"
                 "pages/index?biz=flight&defaultBiz=flight")


def _yuan(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return round(n / 100.0, 2) if n > 0 else 0.0


def _h5_city_name(code: str, intl: bool) -> str:
    code = str(code or "").upper()
    if intl:
        return city_short_of(code) or code
    try:
        from crawlers.qunar import QunarCrawler
        return QunarCrawler.CITY_NAME.get(code) or code
    except Exception:
        return code


def parse_listing(payload: dict, from_city: str, to_city: str,
                  depart_date: str) -> List[FlightPrice]:
    """Parse one real listingsearch payload; skip non-flight modules."""
    items = ((payload or {}).get("data") or {}).get("items") or []
    out, seen = [], {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("itemType") not in ("FLIGHT_DIRECT", "FLIGHT_TRANSFER"):
            continue
        for f in item.get("data") or []:
            if not isinstance(f, dict):
                continue
            infos = f.get("flightInfos") or []
            if not infos or not isinstance(infos[0], dict):
                continue
            fi = infos[0]
            segs = fi.get("flightSegments") or []
            seg = segs[0] if segs and isinstance(segs[0], dict) else {}
            fno = str(seg.get("marketingFlightNo") or "").strip()
            if not fno:
                continue
            dep_code = str(seg.get("depCityCode") or "").upper()
            arr_code = str(seg.get("arrCityCode") or "").upper()
            if not dep_code or not arr_code:
                continue
            if dep_code != str(from_city or "").upper():
                continue
            if arr_code != str(to_city or "").upper():
                continue
            dep = str(fi.get("depTime") or seg.get("depTime") or "")
            if not dep.startswith(str(depart_date or "")):
                continue
            price_info = f.get("priceInfo") or {}
            total = _yuan(price_info.get("adultTotalPrice"))
            base = _yuan(price_info.get("adultPrice"))
            after = _yuan(price_info.get("afterPromotionTotalPrice"))
            price = total or after or base
            if price <= 0:
                continue
            arr = str(fi.get("arrTime") or seg.get("arrTime") or "")
            airline = str(seg.get("marketingAirlineName") or "").split("|")[0]
            key = (fno, dep)
            if key in seen and seen[key].price <= price:
                continue
            seen[key] = FlightPrice(
                platform="fliggy",
                from_city=from_city, to_city=to_city,
                depart_date=depart_date, price=price,
                airline=airline[:20], flight_no=fno,
                depart_time=dep[11:16] if len(dep) >= 16 else dep,
                arrive_time=arr[11:16] if len(arr) >= 16 else arr,
                extra=json.dumps({
                    "src": "fliggy_h5", "price_basis": "adult_total",
                    "base": base, "tax": _yuan(price_info.get("adultTax")),
                    "after_promotion": after,
                    "segment": str(seg.get("segmentFlightDetailUniq") or "")[:80],
                }, ensure_ascii=False),
            )
    out.extend(seen.values())
    out.sort(key=lambda x: x.price)
    return out


class FliggyH5Crawler(BaseCrawler):
    """Data-path crawler using the independent Taobao H5 profile."""
    name = "fliggy"
    profile_name = "fliggy_h5"
    use_mobile = True

    def login_url(self) -> str:
        return H5_SEARCH_URL

    def _pick_city(self, page, idx: int, name: str) -> bool:
        page.evaluate(
            "(i)=>{const e=document.querySelectorAll("
            "'.flight-search-city-name-transition.area-name')[i];"
            "e&&e.click()}", idx)
        page.wait_for_timeout(900)
        inp = page.locator('input[placeholder*="搜索"]').first
        if not inp.count():
            return False
        try:
            inp.fill(name, timeout=5000)
        except Exception:
            return False
        page.wait_for_timeout(1200)
        return bool(page.evaluate(
            "(t)=>{const els=[...document.querySelectorAll('*')]"
            ".filter(e=>e.children.length===0&&e.textContent.trim().startsWith(t));"
            "const e=els.find(x=>/所有机场/.test(x.textContent))||els[0];"
            "if(!e)return false;let p=e;for(let i=0;i<4&&p;i++,p=p.parentElement){"
            "if(/city-picker|city-item|city-list|row/i.test(String(p.className)))"
            "{p.click();return true}}e.click();return true}", name))

    def _read_form(self, page):
        return page.evaluate("""()=>({
          cities:[...document.querySelectorAll('.area-name')].map(e=>e.innerText.trim()).slice(0,2),
          date:(document.querySelector('.traffic-show-date')||{}).innerText
            ? document.querySelector('.traffic-show-date').innerText.replace(/\\s+/g,' ')
            : ''})""")

    def _trigger_search(self, page) -> bool:
        return bool(page.evaluate("""()=>{
          const els=[...document.querySelectorAll('*')]
            .filter(e=>e.innerText && e.innerText.trim()==='搜索机票'
              && e.getBoundingClientRect().width>0);
          const e=els[els.length-1];if(!e)return false;e.click();return true}"""))

    def _select_date(self, page, date: str) -> bool:
        day = date[-2:].lstrip("0")
        page.evaluate("()=>{const e=document.querySelector("
                      "'.flight-date-showdate-transition-item');e&&e.click()}")
        page.wait_for_timeout(900)
        page.evaluate(
            "(d)=>{const els=[...document.querySelectorAll('*')]"
            ".filter(e=>e.children.length===0&&e.textContent.trim()===d"
            "&&e.getBoundingClientRect().width>0);"
            "const e=els.find(x=>/date-item|day/i.test(String(x.className)))"
            "||els[0];e&&e.click()}", day)
        page.wait_for_timeout(1000)
        shown = page.evaluate(
            "()=>{const e=document.querySelector('.traffic-show-date');"
            "return e?e.innerText.replace(/\\s+/g,' '):''}")
        mm = date[5:7].lstrip("0")
        return (day in shown and (mm + " 月") in shown) or (day in shown and "月" in shown)

    def _fetch_one(self, from_city: str, to_city: str, date: str):
        intl = is_intl_route(from_city, to_city)
        fc = from_city.upper()
        tc = to_city.upper()
        payloads = []
        self._last_login = False
        self._last_blocked = False
        with self.browser(headless=self.headless) as ctx:
            page = self.new_page(ctx)
            def on_resp(r):
                if "listingsearch" in r.url:
                    try:
                        payloads.append(r.json())
                    except Exception:
                        pass
            page.on("response", on_resp)
            page.goto(H5_SEARCH_URL, wait_until="domcontentloaded",
                      timeout=45000)
            page.wait_for_timeout(5000)
            if "login" in str(page.url).lower():
                self._last_login = True
                return []
            want_dep = _h5_city_name(fc, intl)
            want_arr = _h5_city_name(tc, intl)
            form = self._read_form(page)
            cities = form.get("cities") or []
            shown_date = str(form.get("date") or "")
            day = date[-2:].lstrip("0")
            month = date[5:7].lstrip("0")
            date_ok = day in shown_date and (month + " 月") in shown_date
            route_ok = (len(cities) >= 2 and cities[0] == want_dep
                        and cities[1] == want_arr)
            if not route_ok:
                if not date_ok and not self._select_date(page, date):
                    self._date_mismatch = True
                    return []
                self._date_mismatch = False
                if not self._pick_city(page, 0, want_dep):
                    return []
                if not self._pick_city(page, 1, want_arr):
                    return []
            elif not date_ok:
                if not self._select_date(page, date):
                    self._date_mismatch = True
                    return []
                self._date_mismatch = False
                self._trigger_search(page)
            else:
                self._date_mismatch = False
                self._trigger_search(page)
            deadline = time.time() + 18
            while time.time() < deadline and not payloads:
                page.wait_for_timeout(600)
            if not payloads:
                try:
                    txt = page.inner_text("body")[:3000]
                except Exception:
                    txt = ""
                sig = classify_text(txt, str(page.url))
                self._last_login = bool(sig and sig.status == "login")
                self._last_blocked = bool(sig and sig.status == "blocked")
                return []
            rows = []
            for payload in payloads:
                rows.extend(parse_listing(payload, fc, tc, date))
            if not rows:
                return []
            best = {}
            for row in rows:
                if row.depart_date not in best or row.price < best[row.depart_date].price:
                    best[row.depart_date] = row
            return [best[date]] if date in best else []

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        self.path_reset()
        if not os.path.isfile(self.session_state_path):
            self.path_note("H5", "login", detail="未保存淘宝 H5 会话")
            return []
        out = []
        for date in dates:
            t0 = time.time()
            self._date_mismatch = False
            try:
                rows = self._fetch_one(from_city, to_city, date)
            except Exception as e:
                self.path_note("H5", "error", date=date,
                               detail=str(e)[:140],
                               ms=int((time.time() - t0) * 1000))
                continue
            status = ("ok" if rows else
                      ("login" if getattr(self, "_last_login", False) else
                       ("blocked" if getattr(self, "_last_blocked", False) else "empty")))
            detail = ("淘宝 H5 listingsearch" if rows else
                      ("H5 登录墙" if status == "login" else
                       ("H5 验证页" if status == "blocked" else
                        ("H5 日期选择未匹配" if getattr(self, "_date_mismatch", False)
                         else "H5 无 listingsearch 响应"))))
            self.path_note("H5", status, rows=len(rows), date=date,
                           detail=detail,
                           ms=int((time.time() - t0) * 1000))
            out.extend(rows)
        return out
