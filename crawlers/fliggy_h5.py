# -*- coding: utf-8 -*-
"""Fliggy Taobao-H5 data path (separate login slot).

The H5 page is a custom React app. We drive the visible route/date form,
capture the real ``*listingsearch`` mtop response, and parse only rows that
actually carry a flight number and price. No response -> no rows.
"""
import json
import os
import re
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


# mtop 会在**响应体**里拒绝，HTTP 仍然是 200：
#   ret=["FAIL_SYS_USER_VALIDATE","RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"]
# data 里没有 items，只有一个指向验证页的 url。r794 实测：搜索发出去了、
# 十几条 listingsearch 全是这种，页面同时跳到了结果壳页 —— 只看页面
# 正文什么都看不出来，账本当时把它记成「解析 0 行」，等于把风控说成解析问题。
#
# r795 **推翻「需要人工验证」这个结论**：文案是「被挤爆啦,请稍后重试」，
# 是**限流**不是验证墙。冷却 50 分钟后单次请求 4 条响应全部
# `SUCCESS::调用成功`、正常出数（9C8929 ¥400 SHA→CAN），账本 status=ok。
# 上一轮的 blocked 是我在 30 分钟内连打十几次自己打爆的配额。
#
# 所以分两档，处置完全不同：
#   RATE（RGV587「被挤爆/稍后重试」）→ soft_reject：等一会自己会好，
#        别让用户去解一个不存在的验证；
#   WALL（ret 里有验证话术，或 data 只有 _____tmd_____ 验证页 url）
#        → blocked：这才是要人去看一眼的那种。
_RATE_RE = re.compile(
    r"RGV587|FAIL_SYS_TRAFFIC_LIMIT|FLOW_LIMIT|被挤爆|稍后重试", re.I)
_WALL_RE = re.compile(
    r"FAIL_SYS_USER_VALIDATE|FAIL_SYS_ILLEGAL_ACCESS|"
    r"FAIL_SYS_TOKEN_EXOIRED|USER_VALIDATE|请完成验证|滑动验证", re.I)


def risk_of(payload) -> str:
    """Return "<kind>:<marker>" for a rejection, "" for a normal payload.

    kind is ``rate`` (限流，等一等会自动恢复) or ``wall`` (验证墙，需人工)。
    """
    if not isinstance(payload, dict):
        return ""
    ret = payload.get("ret")
    blob = " ".join(str(x) for x in ret) if isinstance(ret, (list, tuple)) \
        else str(ret or "")
    m = _WALL_RE.search(blob)
    if m and not _RATE_RE.search(blob):
        return "wall:" + m.group(0)
    m = _RATE_RE.search(blob)
    if m:
        return "rate:" + m.group(0)
    data = payload.get("data")
    # 验证壳：data 只有 url（指向 h5api 的 ____tmd____ 验证页），没有任何结果容器
    if isinstance(data, dict) and set(data.keys()) == {"url"}:
        if "_____tmd_____" in str(data.get("url") or ""):
            return "wall:USER_VALIDATE"
    return ""


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

    # 结果行只在城市弹层里，且**必须点行本身**。旧判据取
    # `document.querySelectorAll('*')` 里第一个以城市名开头的叶节点，
    # 新首页的促销模块（`flight-onsale-od-select-od-text`）也有
    # 「北京」这类同名文本且排在结果行之前；点它什么都不会发生，
    # 但函数照样 return True —— 于是表单城市没变、搜索请求带着
    # 原航线发出去、解析按目标航线过滤后 0 行（r794 实测）。
    _PICK_ROW_JS = """(t)=>{
      const list=[...document.querySelectorAll(
        '[class*="flight-city-picker-search-line-item-name-wrapper"]')]
        .filter(e=>e.getBoundingClientRect().width>0);
      const hit=list.find(e=>(e.innerText||'').trim().startsWith(t));
      if(!hit)return false;
      hit.click();return true}"""

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
        if not page.evaluate(self._PICK_ROW_JS, name):
            return False
        # 点中被点的行≠表单已换城：弹层收起动画期间 `.area-name`
        # 会短暂是「旧城 新城」（实测 +200ms 时读到 `广州 长沙`，
        # +400ms 才只剩新城）。所以判据只能是表单读数，且要等稳定。
        for _ in range(10):
            page.wait_for_timeout(200)
            now = (self._read_form(page).get("cities") or [])
            if len(now) >= 2 and now[idx] == name:
                return True
        return False

    def _read_form(self, page):
        return page.evaluate("""()=>({
          cities:[...document.querySelectorAll('.area-name')].map(e=>e.innerText.trim()).slice(0,2),
          date:(document.querySelector('.traffic-show-date')||{}).innerText
            ? document.querySelector('.traffic-show-date').innerText.replace(/\\s+/g,' ')
            : ''})""")

    def _trigger_search(self, page) -> bool:
        # 点「搜索机票」会把整个页面导航到结果页；如果点击在 evaluate
        # 往返期间就把上下文带走，会抛 `Execution context was destroyed`。
        # 那不是失败——恰恰说明搜索已经发起（r794 实测）。
        try:
            return bool(page.evaluate("""()=>{
              const els=[...document.querySelectorAll('*')]
                .filter(e=>e.innerText && e.innerText.trim()==='搜索机票'
                  && e.getBoundingClientRect().width>0);
              const e=els[els.length-1];if(!e)return false;e.click();return true}"""))
        except Exception as e:
            if "Execution context was destroyed" in str(e):
                return True
            raise

    def _select_date(self, page, date: str) -> bool:
        """点日历里的目标日；**必须能跨月**。

        实测（2026-11-01 探针）：日历把所有月份都渲染在同一条纵向列表里，
        每月一个 `.month-header-text`（文案 `YYYY-MM`，2026-11 → 2027-06
        依次排下来）。原实现只点「当前可见月里文字等于 day 的第一个元素」：
        目标 2027-01-30 时它点到的是 **11 月的 30 日**，随后校验月份不符 →
        记「日期选择未匹配」，等于 90 天外的日期根本选不了。
        正确做法：滚到目标月那一节，**只在这一节的区段里**找 day。
        """
        ym = date[:7]
        day = str(int(date[-2:]))
        page.evaluate("()=>{const e=document.querySelector("
                      "'.flight-date-showdate-transition-item');e&&e.click()}")
        page.wait_for_timeout(900)
        moved = page.evaluate(
            """(arg)=>{
              const heads=[...document.querySelectorAll('.month-header-text')]
                .filter(e=>e.textContent.trim()===arg.ym);
              if(!heads.length)return false;
              heads[0].scrollIntoView({block:'center'});
              return true;
            }""", {"ym": ym, "day": day})
        if not moved:
            return False
        page.wait_for_timeout(600)
        clicked = page.evaluate(
            """(arg)=>{
              const heads=[...document.querySelectorAll('.month-header-text')];
              const i=heads.findIndex(e=>e.textContent.trim()===arg.ym);
              if(i<0)return false;
              const top=heads[i].getBoundingClientRect().bottom;
              const nxt=heads[i+1]?heads[i+1].getBoundingClientRect().top:1e9;
              const cells=[...document.querySelectorAll('.date-item-container')]
                .filter(e=>{const b=e.getBoundingClientRect();
                  return b.top>=top-2 && b.top<nxt;});
              const cell=cells.find(e=>{
                const t=[...e.querySelectorAll('*')].find(x=>x.children.length===0
                  && x.textContent.trim() && !isNaN(Number(x.textContent.trim())));
                return t && Number(t.textContent.trim())===Number(arg.day);
              });
              if(!cell)return false;
              cell.click();
              return true;
            }""", {"ym": ym, "day": day})
        if not clicked:
            return False
        page.wait_for_timeout(1000)
        shown = page.evaluate(
            "()=>{const e=document.querySelector('.traffic-show-date');"
            "return e?e.innerText.replace(/\\s+/g,' '):''}")
        # 月份必须**带边界**匹配：`"1 月" in "11 月 30 日"` 是真（子串），
        # 会把「选错月」判成成功——测试用例 `11 月 30 日` 抓到的就是这个。
        mm = str(int(date[5:7]))
        return bool(re.search(r"(?<!\d)%s\s*月\s*%s\s*日" % (mm, day), shown))

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
            self._pick_failed = ""
            if not date_ok:
                if not self._select_date(page, date):
                    self._date_mismatch = True
                    return []
            self._date_mismatch = False
            if not route_ok:
                if not self._pick_city(page, 0, want_dep):
                    self._pick_failed = "出发城市未选中 %s" % want_dep
                    return []
                if not self._pick_city(page, 1, want_arr):
                    self._pick_failed = "到达城市未选中 %s" % want_arr
                    return []
                # 点击返回 True 不等于表单真的变了（r794：旧判据点中首页
                # 促销块的同名文本）。发请求前用表单读数复核，否则会把
                # 原航线的结果按目标航线解析成 0 行，还记成「无响应」。
                now = (self._read_form(page).get("cities") or [])
                if len(now) < 2 or now[0] != want_dep or now[1] != want_arr:
                    self._pick_failed = "城市未生效 表单=%s" % ("/".join(now[:2]),)
                    return []
            # 前面两条分支原来都不点搜索：航线不匹配时选完城市直接返回，
            # 一次 listingsearch 都没发出，账本却记「无 listingsearch 响应」。
            self._trigger_search(page)
            # 首页会**自动重放上一次搜索**（r794 实测 +3.9s 就到了一条
            # 与本次无关航线的 listingsearch）。旧循环 `while ... not
            # payloads` 只要 buffer 非空就立刻退出，于是把上一条航线的
            # 结果按本次航线过滤，稳定得到 0 行。改成增量解析 + 等真实
            # 出数：旧响应过不了 route/date 两道闸，不影响本次判断。
            deadline = time.time() + 25
            rows, scanned = [], 0
            risk = ""
            while time.time() < deadline:
                while scanned < len(payloads):
                    p = payloads[scanned]
                    scanned += 1
                    r = risk_of(p)
                    if r:
                        risk = risk or r
                        continue
                    rows.extend(parse_listing(p, fc, tc, date))
                if rows:
                    break
                page.wait_for_timeout(600)
            self._responses = len(payloads)
            self._risk = risk
            if rows:
                self._last_blocked = False
                self._last_soft = False
            if not rows:
                if risk:
                    # 报文里拒了，但两种处置完全不同（见 risk_of 注释）：
                    # rate = 限流，等一会自己好 → soft_reject（不触发熔断、
                    #        不引导用户去解验证）；
                    # wall = 验证墙 → blocked（停下交人工）。
                    kind = risk.split(":", 1)[0]
                    if kind == "rate":
                        self._last_soft = True
                        return []
                    self._last_blocked = True
                    return []
                try:
                    txt = page.inner_text("body")[:3000]
                except Exception:
                    txt = ""
                sig = classify_text(txt, str(page.url))
                self._last_login = bool(sig and sig.status == "login")
                self._last_blocked = bool(sig and sig.status == "blocked")
                return []
            best = {}
            for row in rows:
                if row.depart_date not in best or row.price < best[row.depart_date].price:
                    best[row.depart_date] = row
            return [best[date]] if date in best else []

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        self.path_reset()
        # 往返诚实（与 ctrip / tuniu / App 渠道同律）：淘宝 H5 这条通路
        # 只做单程。此前签名收了 ret_date 却**一次都没用**——传返程日照样
        # 跑单程，返回的 price 是单程价，下游会把单程价当往返总价入库，
        # 推送与走势据此出现凭空价差。不发单程查询，直接 unsupported。
        #
        # 注意：`CHANNEL_DIMENSIONS.fliggy.round_trip = "y"` 描述的是
        # **PC**（FliggyCrawler，tripType/backDate 真参数）；飞猪 PC 与 H5
        # 是两套会话、两个采集器，能力不能互相代表。
        if ret_date:
            self.logger.warning(
                "[fliggy_h5] 往返暂不支持（返程 %s），未发起单程查询",
                ret_date)
            self.path_note("H5", "unsupported",
                           detail="淘宝 H5 往返暂不支持，未发起单程查询")
            return []
        if not os.path.isfile(self.session_state_path):
            self.path_note("H5", "login", detail="未保存淘宝 H5 会话")
            return []
        out = []
        for date in dates:
            t0 = time.time()
            self._date_mismatch = False
            self._responses = 0
            self._pick_failed = ""
            self._risk = ""
            self._last_soft = False
            try:
                rows = self._fetch_one(from_city, to_city, date)
            except Exception as e:
                self.path_note("H5", "error", date=date,
                               detail=str(e)[:140],
                               ms=int((time.time() - t0) * 1000))
                continue
            # 末位兜底不是 empty（r405）：走到这里说明既没拿到行，也没有
            # 登录/验证页证据。detail 会区分「有响应但解析 0 行」与
            # 「连响应都没等到」——后者是没拿到东西，前者说明解析契约
            # 对不上。记 empty 会让读者相信真没票而停止关注（r398b/
            # r400/r401/r402/r403 同一类）；记 error 才可查、可重试。
            status = ("ok" if rows else
                      ("login" if getattr(self, "_last_login", False) else
                       ("blocked" if getattr(self, "_last_blocked", False) else
                        ("soft_reject" if getattr(self, "_last_soft", False)
                         else "error"))))
            pick_failed = getattr(self, "_pick_failed", "")
            responses = getattr(self, "_responses", 0)
            risk = getattr(self, "_risk", "")
            kind, _, marker = risk.partition(":")
            detail = ("淘宝 H5 listingsearch" if rows else
                      ("H5 登录墙" if status == "login" else
                       ("H5 限流（mtop %s，冷却后自愈）" % marker if kind == "rate"
                        else
                        ("H5 风控验证（mtop %s）" % marker if kind == "wall"
                         else
                         ("H5 验证页" if status == "blocked" else
                          ("H5 日期选择未匹配" if getattr(self, "_date_mismatch", False)
                           else (pick_failed or
                                 ("H5 listingsearch 解析 0 行（响应 %d 条）"
                                  % responses if responses else
                                  "H5 无 listingsearch 响应"))))))))
            self.path_note("H5", status, rows=len(rows), date=date,
                           detail=detail,
                           ms=int((time.time() - t0) * 1000))
            out.extend(rows)
        return out
