"""途牛机票：纯 httpx 直连 (逆向 tac.js cookie, 不依赖浏览器)。

途牛国内机票真实价格通过接口 flight-api.tuniu.com/wzt/flight/v1/listFlight 异步轮询返回
(fareList), 带有 mtoken + tac.js 追踪/指纹 cookie 的风控 (缺失即 179991)。

逆向结论 (经验证):
  179991 的本质是缺少途牛自有的追踪 cookie (由 CDN 上的 tac.js 在前端生成)。
  补齐以下 cookie 后, httpx 可直接调 listFlight 拿到 fareList:

    udid : GET https://h5api.tuniu.com/auth/getDeviceId?d={"type":1}&c={"ct":30}
    _taca : "{loginTime}.{loginTime}.{loginTime}.1" (loginTime = 毫秒时间戳)
    _tacb : base64(newGuid())
    _tacc : "1"
    _tact : base64(newGuid())
    _tacau : base64("0," + newGuid() + ",")
    _tacz2 : base64("0," + newGuid() + ",,")

  newGuid(): 32 位随机 hex, 在第 8/12/16/20 位后插入 "-" (复刻 tac.js)。

"hoop": 一圈一圈重试 (可设上限), 直到真正拿到真实价格 (fareList) 才停止。
每圈使用全新生成的 cookie 会话, 天然实现"换设备指纹"以规避频率限制。
实测: 同一出口 IP 约 3 次成功后触发 179991, 冷却约 10 分钟; 用滑动窗口限速。
"""
from __future__ import annotations

import os
import base64
import json
import datetime as _dtm
import random
import re
import threading
import time
from typing import Any, List, Optional

import httpx

from core.flightnorm import cabin_clean, fmt_dur
from core.intl import airport_city_code, is_intl_route
from core.models import PRICE_MAX, PRICE_MIN, FlightPrice, price_band_ok
from .base import BaseCrawler, iata2, iata3
from .challenge import blocked_signal, login_signal

_RE_HHMM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
# 舱位订座码形态门（r329：段级订座码串「W-W」单字母连串——B 报告
# 77/77 实证值域；int 旧舱等形态/小写一律不落防脏词面）
# R4 族带数字形态（'R4-W'/'R4-X1'）漂移曾在案，裁决维持不采：出勤
# 地板钉（test_r329_intl_fields 缺席 ≤40 带即哨）；翻身前提=价位带
# 互锁+cabin 词面同现双证（qunar R2/R3/R4 同族先例验证形态）
_RE_CABIN_CODE = re.compile(r"[A-Z](-[A-Z])*")


def _hhmm(s) -> str:
    """从渠道时刻串提取 HH:MM（[-5:] 切片对 "19:55:00" 会切出 "5:00"）。"""
    m = _RE_HHMM.search(str(s or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _stop_time(points) -> str:
    """stopPoints[].duration（分钟）→「X小时Y分」中文形态（normalize 的
    stopTimeT 只认这个格式）；无有效值返回空串宁缺勿错。"""
    total = 0
    for x in points or []:
        if isinstance(x, dict):
            try:
                total += int(float(x.get("duration") or 0))
            except (TypeError, ValueError):
                pass
    return f"{total // 60}小时{total % 60}分" if total > 0 else ""


def _stop_window(points) -> str:
    """stopPoints[].arrivalTime/departrueTime（departrue 为渠道原始
    拼写）→ 经停窗口「HH:MM-HH:MM」；多段「/」连接。段缺任一时刻
    不成对（宁缺勿错）；与 duration 数值互证成立（19:20→20:05 =
    45 分）。五渠道唯一经停段时刻源，判红眼/晚间滞留。"""
    legs = []
    for x in points or []:
        if not isinstance(x, dict):
            continue
        m = _RE_HHMM.search(str(x.get("arrivalTime") or ""))
        m2 = _RE_HHMM.search(str(x.get("departrueTime") or ""))
        if m and m2:
            legs.append(f"{int(m.group(1)):02d}:{m.group(2)}"
                        f"-{int(m2.group(1)):02d}:{m2.group(2)}")
    return "/".join(legs)


def _prate(v) -> str:
    """onTimeRate 净化：途牛对无真值航班下发占位默认值——旧形态恒
    「20%」（dump 实锤 9 家航司同刻 20%，同航班 ctrip 实为 90-97，
    9/9 全背离）；后占位换形为低档带「50%/56%」（航班级恒挂：50 档
    101 次采样仅 2 个航班、56 档亦 2 个跨全窗恒定；伴随矛盾：50 档
    avgDelay 恒 9 分钟与 50% 准点语义互斥、56 档 avgDelay 全缺；
    历史健康带 70-100 无此二值——「不在历史真值域」是零误杀硬证据）。
    原样入库会渲染「准点50%」假数据（比 20% 更隐蔽）并经告警链同
    指纹补全扩散，宁缺勿错置空。63 档 avgDelay 25/36 有分布=真值
    维持不挡；渠道值域恢复多值（50/56 带 avgDelay 背离消除）即撤
    守卫（每轮全量键 diff 复验本守卫依据）。"""
    s = str(v or "").strip().rstrip("%").strip()
    return "" if s in ("20", "20.0", "50", "50.0", "56", "56.0") else s

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

FLIGHT_HOME = "https://m.tuniu.com/flight"
LIST_API = "https://flight-api.tuniu.com/wzt/flight/v1/listFlight"
DEVICE_ID_API = "https://h5api.tuniu.com/auth/getDeviceId"
COOKIE_DOMAIN = ".tuniu.com"

# 降级样本早收门槛：渠道存在 fareList 截断降级形态（实录：截断轮
# n=1/3 条、最低价落库较健康轮虚高 50%，且逐轮交替出勤）；门槛只
# 约束「首响即收」——薄样本续询穷尽后仍以 best-so-far 兜底返回，
# 真稀疏日期零数据丢失（不丢数据，也不早收坏样本）。
# 门槛值=健康带下缘：自然轮 n 分布三段——薄带 3-15/空档 16-38/
# 健康 39+。两级被否决的取法：门槛落在薄带内时，恰卡门槛的截断轮
# 8 班全缺真最低班、落库虚高；门槛落在空档中段时，20-38 段首响
# 即收即过闸——「空档恒空」的 dump 抽样推断被自然轮逐轮分布推翻
# （DB 该带按日出勤，抽检 min/max 在场=真稀疏与良性截断并存）。
# 按「整个过闸带落入续询面」的设计哲学取 39：健康轮零额外请求
# 不回退，<39 全带续询（渠道分布再漂移时按逐轮 n 分布复检门槛）
_FARE_FLOOR = 39
_THIN_MAX = 3

# 连续全败降载档（r306 观测：静默空响应形态无 179991 字面、
# blocked=False，绕过风控判据后 5 圈×10 拍对每日期空转 ~110s、
# 每轮 ~7.3min=轮距拉长主因）。连续 _LADDER_STRIKE 个查询全败后
# 收紧为 1 圈×3 拍，任一成功复位全预算——降载档每轮仍探测（恢复
# 零延迟自愈，优于维护锁存的重启重探），对风控端点更礼貌（行为
# 风控停手换路径，重试只会加深）。真稀疏日期（fareList 恒空）同样
# 计连败——无害：健康查询首响即收不吃降载预算，降载只收窄无望
# 重试的深度，不收窄单圈内的轮询面。
_LADDER_STRIKE = 4
_LITE_ATTEMPTS = 1
_LITE_POLLS = 3


def _ladder(streak: int, attempts: int, polls: int) -> tuple:
    """连败降载档决策（纯函数）：streak≥阈值返回（1 圈，3 拍），
    否则原预算；min 防病理小配置被放大。"""
    if streak >= _LADDER_STRIKE:
        return min(_LITE_ATTEMPTS, attempts), min(_LITE_POLLS, polls)
    return attempts, polls


class IntlFailure:
    """国际通道的带类型失败结果（替代裸 None，防调用方一律落 empty）。

    status ∈ timeout/error/parse_error；detail 进 path_note 证据链。
    仅在「请求未成功」时替代 raw 数据返回，成功路径契约不变。
    """
    __slots__ = ("status", "detail")

    def __init__(self, status: str, detail: str = ""):
        self.status = status
        self.detail = str(detail or "")

    def __repr__(self) -> str:
        return f"IntlFailure({self.status!r}, {self.detail!r})"


class TuniuCrawler(BaseCrawler):
    name = "tuniu"
    use_mobile = True
    # 确保 parse_error 可入账（不依赖 base 白名单版本；重复项去重）
    PATH_STATUS = tuple(dict.fromkeys(
        BaseCrawler.PATH_STATUS + ("parse_error",)))

    @staticmethod
    def _exc_status(exc) -> str:
        """异常 → 路径状态：httpx 超时族、解码/JSON 失败与其他请求
        异常分开记账，禁止一起落成 empty。"""
        if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
            return "parse_error"
        name = type(exc).__name__.lower()
        if "json" in name or "decode" in name:
            return "parse_error"
        if isinstance(exc, TimeoutError) or "timeout" in name:
            return "timeout"
        return "error"
    # 国内 listFlight 710114 登录墙证据（webui /api/login-state 消费）；
    # 国际通道独立，不受该标记影响
    login_suspect = False

    RATE_MAX = 3
    RATE_WINDOW = 600.0

    PC_URL_TPL = ("https://flight.tuniu.com/domestic/list/"
                  "{fc}_{tc}_ST_1_0_0/?start={date}")

    @classmethod
    def list_url(cls, fc: str, tc: str, date: str) -> str:
        """列表页入口（fetch 与用户侧 _build_view_url 同源构造——
        链接一致性测试曾锚测试文件内的硬编码字符串，爬虫改版不红）。"""
        return (f"https://m.tuniu.com/flight/domestic/new/"
                f"{fc}_{tc}_OW_1_0_0?deptDate={date}&isGo=0")

    def __init__(self, config: dict, logger):
        super().__init__(config, logger)
        self.max_attempts: int = int(config.get("max_attempts", 5))
        self.max_poll: int = int(config.get("tuniu_max_poll", 10))
        self.backoff_s: float = float(config.get("backoff_seconds", 5))
        self.rate_limit: bool = bool(config.get("rate_limit", True))
        self._success_times: list = []
        self._rate_lock = threading.Lock()
        # 连续全败计数（实例生命周期：get_crawlers 按平台集合键缓存，
        # 异构订阅部署下同平台多实例各自计数、进入延迟随之放大——单
        # 用户同构部署=单实例等价进程生命周期；任一成功复位）。降载
        # 档判据按「查询」计数不按「圈」（单查询内 5 圈连败只计 1）
        self._fail_streak: int = 0
        # 国际通道独立连败计数（r325）：国内登录墙（710114 账号态）
        # 与国际通道（systemId 63/错误族 710000）完全独立——共桶会让
        # 国内连败拖累国际健康的降载节奏
        self._fail_streak_intl: int = 0
        self._login_wall: bool = False
        self._last_challenge = None
        self._last_challenge_intl = None
        self._saved_cookies: list = []
        self._saved_cookies_at: float = 0.0
        self._saved_token: str = ""
        self._saved_token_at: float = 0.0

    def login_url(self) -> str:
        return "https://www.tuniu.com/"

    @property
    def user_data_dir(self) -> str:
        """登录槽位把 PC/H5 会话分别存在 surfaces/{pc,h5}；采集必须读同一面。

        历史上只读 user_data/tuniu（base），用户重新登录后 base 没有
        tuniuuser_id/_taca，接口恒 710114，而 surfaces/h5 是登录态。
        """
        base = os.path.join(self.user_data_root,
                            self.profile_name or self.name)
        surface = "h5" if self.use_mobile else "pc"
        path = os.path.join(base, "surfaces", surface)
        if os.path.isdir(os.path.join(path, "Default")):
            return path
        os.makedirs(base, exist_ok=True)
        return base

    def _rate_acquire(self):
        while True:
            with self._rate_lock:
                now = time.time()
                self._success_times[:] = [t for t in self._success_times if now - t < self.RATE_WINDOW]
                if len(self._success_times) < self.RATE_MAX:
                    return
                wait = self.RATE_WINDOW - (now - self._success_times[0]) + 0.5
            time.sleep(min(wait, 30))

    def _rate_record(self):
        with self._rate_lock:
            self._success_times.append(time.time())

    @staticmethod
    def _new_guid() -> str:
        out = ""
        for o in range(1, 33):
            out += format(random.randint(0, 15), "x")
            if o in (8, 12, 16, 20):
                out += "-"
        return out

    @staticmethod
    def _b64(s: str) -> str:
        return base64.b64encode(s.encode("utf-8")).decode("ascii")

    def _fetch_udid(self, client: httpx.Client) -> str:
        try:
            r = client.get(
                DEVICE_ID_API,
                params={"d": '{"type":1}', "c": '{"ct":30}'},
                headers={"Referer": "https://m.tuniu.com/"},
                timeout=15,
            )
            return r.json().get("data", {}).get("udid", "") or ""
        except Exception:
            return ""

    def _install_tac_cookies(self, client: httpx.Client) -> None:
        now = int(time.time() * 1000)
        udid = client.cookies.get("udid") or self._fetch_udid(client)
        cookies = {
            "udid": udid,
            "_taca": f"{now}.{now}.{now}.1",
            "_tacb": self._b64(self._new_guid()),
            "_tacc": "1",
            "_tact": self._b64(self._new_guid()),
            "_tacau": self._b64("0," + self._new_guid() + ","),
            "_tacz2": self._b64("0," + self._new_guid() + ",,"),
        }
        for k, v in cookies.items():
            if not v:
                continue
            # 654: 保存会话里的 _taca 带登录时间，重写会破坏 710114 登录态；
            # 任何已存在（保存态或站点下发）的 cookie 都不得覆盖。
            if client.cookies.get(k):
                continue
            client.cookies.set(k, v, domain=COOKIE_DOMAIN, path="/")

    @staticmethod
    def _has_price(node: Any) -> bool:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("salePrice", "baseFare", "lowestPrice", "barePrice") and isinstance(v, (int, float)) and v > 0:
                    return True
                if TuniuCrawler._has_price(v):
                    return True
        elif isinstance(node, list):
            return any(TuniuCrawler._has_price(i) for i in node)
        return False

    @classmethod
    def _poll_sample(cls, body: str) -> tuple:
        """轮询响应定样：(obj, fare 条数, 是否历史无 fareList 价格形)。

        坏 JSON / success 非 true → (None, 0, False)；data 缺席/非 dict
        视为空（n=0、无历史价格形）。历史形态（data.salePrice 等、
        无 fareList）保持首响即收语义。"""
        try:
            obj = json.loads(body)
        except Exception:
            return None, 0, False
        if not isinstance(obj, dict) or obj.get("success") is not True:
            return None, 0, False
        data = obj.get("data") or {}
        if not isinstance(data, dict):
            return None, 0, False
        n = len(data.get("fareList") or [])
        return obj, n, (n == 0 and cls._has_price(data))

    @staticmethod
    def _token_from_request(url: str) -> str:
        """从页面 listFlight 请求的 d 参数提取 tokenKey（请求级校验）。"""
        try:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(str(url or "")).query)
            obj = json.loads((q.get("d") or ["{}"])[0])
            return str((obj or {}).get("tokenKey") or "")
        except Exception:
            return ""

    def _saved_page_token(self, fc: str, tc: str, date: str) -> str:
        """用保存登录态打开 H5 列表页，抓取页面请求里的 tokenKey。

        页面列表请求即使因参数/返回段形态不完整而 170001，tokenKey 仍是
        同一登录会话的请求级校验令牌；把它用于爬虫修正后的单段请求。
        与 cookie 同一次浏览器读取共用，缓存 5 分钟；失败则回退空 token。
        """
        now = time.time()
        if self._saved_token and now - self._saved_token_at < 300:
            return self._saved_token
        token = ""
        try:
            with self.browser(headless=True) as ctx:
                page = self.new_page(ctx)
                seen = {}

                def on_req(req):
                    if "listFlight" in req.url and not seen.get("t"):
                        tk = self._token_from_request(req.url)
                        if tk:
                            seen["t"] = tk
                page.on("request", on_req)
                page.goto(self.list_url(fc, tc, date),
                          wait_until="domcontentloaded", timeout=25000)
                deadline = time.time() + 10
                while time.time() < deadline and not seen.get("t"):
                    page.wait_for_timeout(400)
                token = seen.get("t", "")
                # 同一次浏览器读取顺带刷新 cookie 缓存（登录态只存 user_data）
                out = []
                for c in ctx.cookies():
                    if "tuniu.com" in str(c.get("domain") or ""):
                        out.append((str(c.get("name") or ""),
                                    str(c.get("value") or ""),
                                    str(c.get("domain") or "")))
                if out:
                    self._saved_cookies = out
                    self._saved_cookies_at = now
            if token:
                self.logger.info("[tuniu] 页面 tokenKey 长度=%d", len(token))
        except Exception as ex:
            self.logger.warning("[tuniu] 读取页面 tokenKey 失败: %s", ex)
        self._saved_token = token
        self._saved_token_at = now if token else 0.0
        return token

    def _saved_session_cookies(self) -> list:
        """从持久化浏览器档案取途牛 cookie（登录态只存在 user_data）。

        国内 listFlight 2026-10 起对匿名返回 710114「请登录」；此前
        爬虫每圈新建 httpx 匿名会话，用户在「渠道登录」保存的会话
        从未被使用。缓存 5 分钟，避免每个日期都拉起浏览器。
        """
        now = time.time()
        if self._saved_cookies and now - self._saved_cookies_at < 300:
            return self._saved_cookies
        out = []
        try:
            with self.browser(headless=True) as ctx:
                page = self.new_page(ctx)
                page.goto("https://m.tuniu.com/flight/",
                          wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(800)
                for c in ctx.cookies():
                    if "tuniu.com" in str(c.get("domain") or ""):
                        out.append((str(c.get("name") or ""),
                                    str(c.get("value") or ""),
                                    str(c.get("domain") or "")))
        except Exception as ex:
            self.logger.warning("[tuniu] 读取已保存会话失败: %s", ex)
        self._saved_cookies = out
        self._saved_cookies_at = now
        return out

    PC_ITEMS_JS = r"""() => [...document.querySelectorAll('.J-flightlist')].map(r => {
      const txt = s => { const e = r.querySelector(s); return e ? e.innerText.trim() : ''; };
      const arrEl = r.querySelector('.fl-arriveInf .hours');
      const arrLines = arrEl ? arrEl.innerText.split(String.fromCharCode(10)) : [];
      const tipEl = r.querySelector('.fl-arriveInf .hours [data-tip]');
      return {
        airline: txt('.aircom'), fn: txt('.flihtnumber'),
        dep: txt('.fl-departInf .hours'),
        depAir: txt('.fl-departInf .airport'),
        arr: (arrLines[0] || '').trim(),
        arrAir: txt('.fl-arriveInf .airport'),
        dur: txt('.durationTime'),
        rate: txt('.fl-rate'),
        price: txt('.price'),
        cross: arrLines.join(' '),
        arrTip: tipEl ? tipEl.getAttribute('data-tip') : '',
        rowText: r.innerText
      };
    })"""

    @classmethod
    def _parse_pc_items(cls, items, date: str) -> list:
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            fn = " ".join(str(it.get("fn") or "").split())
            m = re.match(r"^([A-Z0-9]{2}\d{3,4})\s*(.*)$", fn)
            if not m:
                continue
            code, plane = m.group(1), m.group(2).strip()
            dep = str(it.get("dep") or "").strip()
            arr = str(it.get("arr") or "").strip()
            if not (re.match(r"^\d{2}:\d{2}$", dep)
                    and re.match(r"^\d{2}:\d{2}$", arr)):
                continue
            pm = re.search(r"[￥¥]\s*([0-9]+(?:\.[0-9]+)?)",
                           str(it.get("price") or ""))
            if not pm:
                continue
            price = float(pm.group(1))
            if not price_band_ok(price):
                continue
            cabin = ""
            cm = re.search(r"(超级经济舱|经济舱|公务舱|头等舱)",
                           str(it.get("price") or ""))
            if cm:
                cabin = cm.group(1)
            rate = ""
            rm = re.search(r"(\d{1,3})%", str(it.get("rate") or ""))
            if rm:
                rate = int(rm.group(1))
            cross = ""
            ct = str(it.get("cross") or "")
            if "+1" in ct or "+2" in ct:
                cross = "+" + ct.split("+", 1)[1][:1] + "天"
            elif it.get("arrTip"):
                try:
                    from datetime import date as _d
                    ad = _d.fromisoformat(str(it["arrTip"]).split(" ")[0])
                    n = (ad - _d.fromisoformat(date)).days
                    if n > 0:
                        cross = "+%d天" % n
                except Exception:
                    cross = ""
            out.append({
                "price": price, "code": code,
                "name": str(it.get("airline") or "").strip(),
                "depTime": dep, "arrTime": arr, "depDate": date,
                "totalDuration": str(it.get("dur") or ""),
                "depAirport": str(it.get("depAir") or "").strip(),
                "arrAirport": str(it.get("arrAir") or "").strip(),
                "plane": plane, "prate": rate,
                **({"cabin": cabin} if cabin else {}),
                **({"crossDayDesc": cross} if cross else {}),
                "source": "tuniu_pc",
                "transfer": bool(re.search(r"中转|经停", str(it.get("rowText") or ""))),
            })
        uniq = {}
        for r in out:
            k = (r["code"], r["depTime"], r["arrTime"], r["price"])
            uniq.setdefault(k, r)
        return list(uniq.values())

    def _fetch_pc_dom(self, fc: str, tc: str, dates: List[str],
                      headless=None, path_label: str = "PC") -> dict:
        """途牛 PC 国内列表；headless 失败时由调用方复用可见会话重试。"""
        out = {}
        bak = self.use_mobile
        self.use_mobile = False
        try:
            with self.browser(headless=headless) as ctx:
                page = self.new_page(ctx)
                for date in dates:
                    url = self.PC_URL_TPL.format(fc=fc, tc=tc, date=date)
                    t0 = time.time()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_selector(".J-flightlist", state="attached", timeout=18000)
                        page.wait_for_timeout(1200)
                        items = page.evaluate(self.PC_ITEMS_JS) or []
                        out[date] = self._parse_pc_items(items, date)
                        self._debug_snapshot(page, f"tuniu_pc_{fc}{tc}_{date}",
                                             extra_text=page.inner_text("body"))
                        self.path_note(path_label, "ok" if out[date] else "empty",
                                       rows=len(out[date]), date=date,
                                       ms=int((time.time() - t0) * 1000),
                                       detail="flight.tuniu.com 国内列表")
                    except Exception as e:
                        self.logger.warning("[tuniu] %s PC 列表加载失败: %s", date, e)
                        out[date] = []
                        try:
                            _body = page.inner_text("body")[:1200]
                        except Exception:
                            _body = ""
                        _blocked = bool(re.search(
                            r"验证码|人机验证|滑动验证|拖动|安全验证|拼图", _body))
                        if not _blocked:
                            try:
                                _blocked = bool(page.evaluate(
                                    "() => !!document.querySelector("
                                    "'[class*=captcha],[class*=verify],"
                                    "[id*=captcha],[class*=slide],[class*=drag]')"))
                            except Exception:
                                pass
                        self.path_note(
                            path_label, "blocked" if _blocked else "error",
                            date=date,
                            detail=("人机验证页（滑块），需在渠道登录窗口完成验证"
                                    if _blocked else str(e)[:120]),
                            ms=int((time.time() - t0) * 1000))
                        if _blocked:
                            # 同一 profile 连续请求只会加重风控，遇到滑块即停。
                            break
                    self._sleep()
        finally:
            self.use_mobile = bak
        return out

    def _one_attempt(self, depart_code, arrive_code, depart_date, polls=None):
        page_token = self._saved_page_token(depart_code, arrive_code, depart_date)
        client = httpx.Client(
            headers={
                "User-Agent": self._ua() or UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Origin": "https://m.tuniu.com",
                "Referer": "https://m.tuniu.com/",
            },
            timeout=25,
            follow_redirects=True,
        )
        try:
            # 先让站点下发 mtoken/风控基础 cookie，再覆盖保存会话；反过来
            # 会被站点的匿名 connect.sid 覆盖，接口又回到 710114。
            client.get(FLIGHT_HOME)
            for _ck, _cv, _cd in self._saved_session_cookies():
                try:
                    client.cookies.set(_ck, _cv, domain=_cd, path="/")
                except Exception:
                    pass
                # 654: connect.sid 是 m.tuniu.com 的 host-only 会话 cookie，
                # listFlight 在 flight-api.tuniu.com 上收不到它；同一登录会话
                # 在父域再挂一次，不改变值，只修正跨子域可见性。
                if _cd == "m.tuniu.com":
                    try:
                        client.cookies.set(_ck, _cv, domain=COOKIE_DOMAIN, path="/")
                    except Exception:
                        pass
            self._install_tac_cookies(client)
            mtoken = client.cookies.get("mtoken", "") or ""

            d_tmpl = {
                "systemId": 53, "channelCount": 0,
                "adultQuantity": 1, "childQuantity": 0, "babyQuantity": 0,
                "supportBlack": True,
                "segmentList": [
                    {"dCityIataCode": depart_code, "aCityIataCode": arrive_code, "departDate": depart_date}
                ],
                "rph": 0, "hackersFlightNos": None,
                "tokenKey": page_token or mtoken,
            }
            api_hdrs = {"Origin": "https://m.tuniu.com",
                        "Referer": "https://m.tuniu.com/",
                        "Accept": "application/json"}

            last = ""
            blocked = False
            best = None  # 薄样本 best-so-far: (obj, n)
            thin_seen = 0
            for poll in range(self.max_poll if polls is None else polls):
                d = dict(d_tmpl)
                d["pollTag"] = poll
                r = client.get(LIST_API, params={"d": json.dumps(d, ensure_ascii=False)}, headers=api_hdrs)
                last = r.text
                if "710114" in last or "请登录" in last:
                    type(self).login_suspect = True
                    self._login_wall = True
                    self._last_challenge = login_signal("710114/needLogin")
                    self.logger.warning(
                        "[tuniu] %s 国内接口 710114 请登录——需在渠道登录保存途牛会话",
                        depart_date)
                    return False, None, True
                if "179991" in last:
                    blocked = True
                    self._last_challenge = blocked_signal("waf", "179991")
                obj, n, legacy_price = self._poll_sample(last)
                if obj is not None and (n >= _FARE_FLOOR or legacy_price):
                    return True, obj, blocked
                if n > 0:
                    # 薄样本（0<n<门槛）：不早收，记 best-so-far 续询——
                    # 截断降级逐轮交替，紧邻两拍大概率拿到全量；
                    # 薄响应最多连看 _THIN_MAX 个（礼貌预算有界）
                    # （n<门槛含空档带 16-38：DB 逐轮分布实证该带非恒空，
                    # 真稀疏由 best-so-far 兜底零丢失）
                    if best is None or n > best[1]:
                        best = (obj, n)
                    thin_seen += 1
                    if thin_seen >= _THIN_MAX:
                        break
                time.sleep(1.5)
            if best is not None:
                self.logger.warning(
                    "[tuniu] %s 疑似降级样本 fareList n=%d（早收门槛 %d 条）"
                    "——以 best-so-far 兜底",
                    depart_date, best[1], _FARE_FLOOR)
                return True, best[0], blocked
            return False, None, blocked
        except Exception as ex:
            self.logger.warning("[tuniu] 请求异常: %s", ex)
            return False, None, False
        finally:
            client.close()

    def _hoop(self, fc, tc, date) -> Optional[dict]:
        eff_a, eff_p = _ladder(self._fail_streak, self.max_attempts,
                               self.max_poll)
        if (self._fail_streak == _LADDER_STRIKE
                and (eff_a < self.max_attempts or eff_p < self.max_poll)):
            # 降载档进入沿（恰达阈值首查才响，续期不重复刷屏；圈/拍
            # 任一维收窄都算进入——病理配置只收窄拍维度时静默=观测
            # 失明）；动态词面全走参数位（裸 % 参与格式化=消息静默消失律）
            self.logger.warning(
                "[tuniu] 连续 %d 个查询全败——降载重试（%d 圈×%d 拍），"
                "任一成功自动复位全预算",
                self._fail_streak, eff_a, eff_p)
        attempt = 0
        while True:
            attempt += 1
            if self.rate_limit:
                self._rate_acquire()
            ok, raw, blocked = self._one_attempt(fc, tc, date, polls=eff_p)
            if ok:
                type(self).login_suspect = False
                if self._fail_streak >= _LADDER_STRIKE:
                    self.logger.info(
                        "[tuniu] 降载档恢复：连续全败 %d 个查询后拿到价格"
                        "——重试预算复位", self._fail_streak)
                self._fail_streak = 0
                if self.rate_limit:
                    self._rate_record()
                self.logger.info("[tuniu] %s 第 %d 圈拿到真实价格", date, attempt)
                return raw
            if self._login_wall:
                # 710114 是账号态门，不是风控频率；重试只会空转
                self._fail_streak += 1
                self._login_wall = False
                return None
            if eff_a and attempt >= eff_a:
                # 连败计数按「查询」落账（收尾一次），不按「圈」
                self._fail_streak += 1
                self.logger.warning("[tuniu] %s 达到最大重试圈数 %d 仍未拿到价格%s",
                                     date, eff_a, "(疑似风控/179991)" if blocked else "")
                return None
            time.sleep(self.backoff_s * (2 if blocked else 1))

    # ───── 国际支线（r325，调研 _scratch/intl/report_tuniu.md）─────
    # 国际整条产品线跑在 m2015 老应用（seajs+zepto），与国内 SPA 完全
    # 分家：不同域名路径/systemId(63)/错误码族（710000=OK）——国内
    # 710114 登录墙不连坐（2026-10-17 实测 7 查询全受理）。IATA3 直收
    # （route 校验 ^[A-Za-z]{3}-[A-Za-z]{3}$），无需内部 ID 映射。
    # token 门（非登录）：列表页隐藏域 GUID → Σ(charCode×(i+1)) 过程
    # 中 >80 则 -=80，三层混淆 JS 已还原并实测闭环
    INTL_LIST_PG = ("https://m.tuniu.com/m2015/intlFlight/flight/list"
                    "?route={route}&date={date}&adult=1&child=0&baby=0"
                    "&cabinClass=0")
    INTL_QF_API = "https://m.tuniu.com/api/intlFlight/intelProduct/queryFlight"

    @staticmethod
    def _token_secret(guid: str) -> int:
        """列表页 #token GUID → tokenSecret（report_tuniu.md §6 三层
        混淆还原算法；实测：错 token → data.message「403 token error」，
        对 token → needQueryMore 正常出询）。"""
        secret = 0
        for i, ch in enumerate(str(guid or "")):
            secret += ord(ch) * (i + 1)
            if secret > 80:
                secret -= 80
        return secret

    @staticmethod
    def _intl_query_body(fc: str, tc: str, date: str, poll: int,
                         token: int) -> dict:
        """queryFlight 请求体单源（校准 R1 定谳钉）：请求面字段=
        dCityCode/aCityCode——误用响应回显字段 dCityIataCode/aCityIataCode
        服务端静默忽略→回显 null→异步聚合永不完结（30 拍零行实测）；
        selectFlightNos/distributeId 空槽必带（probe7 成功样本同构）。"""
        return {"systemId": 63,
                "segmentList": [{"departDate": date,
                                 "dCityCode": fc, "aCityCode": tc}],
                "adultQuantity": 1, "childQuantity": 0,
                "babyQuantity": 0, "cabinClass": 0,
                "channelCount": 0,
                "selectFlightNos": "", "distributeId": "",
                "pollTag": poll,
                "token": token}

    def _one_attempt_intl(self, fc: str, tc: str, date: str,
                          polls: Optional[int] = None):
        """国际 queryFlight 单圈：列表页取会话+GUID → tokenSecret →
        轮询（needQueryMore='1'=异步聚合中，续拍取最新非空 productList）。
        返回 (ok, data, blocked)：ok=True 且 data=完整聚合响应（即使
        productList 为空——只有这种干净响应才允许调用方落 empty）；
        ok=False 时 data 为带类型的 IntlFailure（timeout/error/
        parse_error），blocked 仅保留给外层退避加倍。"""
        client = httpx.Client(
            headers={
                "User-Agent": self._ua() or UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "sec-ch-ua-platform": '"iOS"',
                "sec-ch-ua-mobile": "?1",
            },
            timeout=25,
            follow_redirects=True,
        )
        try:
            # X-Requested-With 必带（probe7 成功样本同款；校准 R1：缺失
            # 不拒但同族XHR面一致性纪律）+ Referer=已填参真实列表页
            api_hdrs = {"Referer": self.INTL_LIST_PG.format(
                            route=f"{fc}-{tc}", date=date),
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest"}

            def _new_token():
                r = client.get(self.INTL_LIST_PG.format(route=f"{fc}-{tc}",
                                                        date=date))
                m = re.search(r'id="token"\s+value="([^"]+)"', r.text)
                return self._token_secret(m.group(1)) if m else None

            secret = _new_token()
            last_msg = ""
            last_data = None
            for poll in range(self.max_poll if polls is None else polls):
                if secret is None:
                    # 列表页拿不到 token（页面改版）：停，外层退避
                    self.logger.warning(
                        "[tuniu][intl] %s 列表页未取到 #token（疑改版）",
                        date)
                    return False, IntlFailure(
                        "error", "国际列表页未取到 #token（疑改版）"), True
                d = self._intl_query_body(fc, tc, date, poll, secret)
                r = client.get(self.INTL_QF_API,
                               params={"d": json.dumps(d, ensure_ascii=False)},
                               headers=api_hdrs)
                try:
                    obj = r.json()
                except Exception as ex:
                    return False, IntlFailure(
                        "parse_error", f"queryFlight 响应非 JSON: {ex}"), False
                if not isinstance(obj, dict):
                    return False, IntlFailure(
                        "parse_error", "queryFlight 响应非 JSON 对象"), False
                data = obj.get("data")
                if data is None:
                    data = {}
                if not isinstance(data, dict):
                    return False, IntlFailure(
                        "parse_error", "queryFlight 响应 data 非对象"), False
                # 观察哨（report §6b）：国际通道预留登录门 needLogin
                # 未启用——翻 true 即停采报事件（勿绕，同国内 710114 纪律）
                if data.get("needLogin"):
                    self._last_challenge_intl = login_signal("needLogin")
                    self.logger.warning(
                        "[tuniu][intl] needLogin 翻真——国际登录门启用，"
                        "停采（观察哨触发）")
                    return False, None, True
                msg = str(data.get("message") or "")
                if msg:
                    # token 门拒绝：换会话重取 GUID 再拍（报告 §6a 实测
                    # 同会话重试无效，新 GUID 新 token 即解）
                    if msg != last_msg:
                        self.logger.warning("[tuniu][intl] %s %s——换会话重取 token",
                                            date, msg)
                        secret = _new_token()
                    last_msg = msg
                    time.sleep(1.5)
                    continue
                plist = data.get("productList")
                if plist is None:
                    plist = []
                if not isinstance(plist, list):
                    return False, IntlFailure(
                        "parse_error", "productList 非数组"), False
                if plist:
                    last_data = data
                if str(data.get("needQueryMore")) != "1":
                    # 聚合完成（含明确空盘）：优先最新非空盘，整份响应
                    # 交调用方分层——空 productList 才是真源边界证据
                    return True, (last_data if last_data is not None
                                  else data), False
                time.sleep(1.5)
            # 拍数用尽：聚合未完结时以已拿到的最新非空盘兜底
            if last_data is not None:
                return True, last_data, bool(last_msg)
            if last_msg:
                self._last_challenge_intl = blocked_signal("waf", "token门")
                return False, IntlFailure(
                    "error", f"国际 token 门持续拒绝: {last_msg}"), True
            return False, IntlFailure(
                "timeout", "国际聚合超时（needQueryMore=1 轮询耗尽，"
                           "productList 为空）"), False
        except Exception as ex:
            self.logger.warning("[tuniu][intl] 请求异常: %s", ex)
            return False, IntlFailure(
                self._exc_status(ex), f"国际请求异常: {ex}"), False
        finally:
            client.close()

    def _hoop_intl(self, fc: str, tc: str, date: str) -> Optional[dict]:
        """国际圈重试外壳：复用连败降载档（独立计数——国内登录墙
        连败不得拖累国际健康的降载节奏，两通道错误族完全独立）。"""
        eff_a, eff_p = _ladder(self._fail_streak_intl, self.max_attempts,
                               self.max_poll)
        attempt = 0
        while True:
            attempt += 1
            if self.rate_limit:
                self._rate_acquire()
            ok, raw, blocked = self._one_attempt_intl(fc, tc, date,
                                                      polls=eff_p)
            if ok:
                self._fail_streak_intl = 0
                if self.rate_limit:
                    self._rate_record()
                return raw
            if isinstance(raw, IntlFailure):
                # 保留最近一次带类型失败证据（调用方按此落
                # timeout/error/parse_error，不得回落 empty）
                self._last_intl_failure = raw
            if (self._last_challenge_intl is not None
                    and self._last_challenge_intl.status == "login"):
                # needLogin 是确定性账号门，重试只会空转。
                self.logger.warning(
                    "[tuniu][intl] %s 登录门在案，停止重试", date)
                return None
            if eff_a and attempt >= eff_a:
                self._fail_streak_intl += 1
                self.logger.warning(
                    "[tuniu][intl] %s 达最大重试圈数 %d 未拿到价格",
                    date, eff_a)
                return None
            time.sleep(self.backoff_s * (2 if blocked else 1))

    def _parse_offers_intl(self, data: Optional[dict]) -> List[dict]:
        """国际 productList 行 → 统一航班级明细 schema（extra 元素）。
        字段映射单源=report_tuniu.md §4（页面 #JSegment 模板 +
        flightList.js model 双重实证，值形非猜测）：avgTotalPrice=含税
        人均价（本系统国际价口径，INTL_DESIGN §1.2）、avgTax/avgBasePrice
        拆分透传、跨天无服务端字段由 dTime/aTime 日期差自推导（与渠道
        前端 DateDiff 同款）。价带走国际宽带（商务舱 >5 万合法）。"""
        out: List[dict] = []
        if not isinstance(data, dict):
            return out
        # 观察哨（r333 走查精化触发面）：行级营销载体成员=
        # promotionInfo/tagList/fPay 翻非空、isHighLight/isTop 翻
        # true——任一事件成员出现即按 labels 词面评估收编；
        # promotionInfoSet（恒 True 布尔）与顶层 promotionIcon
        # （容器级「优惠活动」图标 chrome，无行级绑定、解析器不读）
        # 为常驻噪音成员不计触发，防哨位自出生空转、也防下轮把
        # promotionIcon 当新营销载体重查（判例廿五§13 内容定性关）。
        for it in data.get("productList") or []:
            if not isinstance(it, dict):
                continue
            try:
                price = float(it.get("avgTotalPrice"))
            except (TypeError, ValueError):
                continue
            if not price_band_ok(price, el={"intl": 1}):
                continue
            d_tm, a_tm = str(it.get("dTime") or ""), str(it.get("aTime") or "")
            dep_d, arr_d = d_tm[:10], a_tm[:10]
            dep_t, arr_t = _hhmm(d_tm), _hhmm(a_tm)
            if not (dep_d and arr_d and dep_t and arr_t):
                continue
            fnos = str(it.get("flightNos") or "").replace("-", ",")
            if not fnos:
                continue
            # 中转：transferCity 非空即中转（模板「转」标实证）；
            # 经停：stopCity 非空（模板「经停」标实证）；两者全空=直飞
            trans = str(it.get("transferCity") or "").strip()
            stops = str(it.get("stopCity") or "").strip()
            # 共享：codeShare=执飞航班号串直落（r326 门型错配修复：
            # 真实值域 'MS917'×7 非布尔，旧 '1/TRUE/Y/T' 门恒假=共享
            # 信息 0/253 永久丢失），缺时 sAirComName 航司名兜底——
            # 国内 _parse_offers 同键同款直落
            _segs = it.get("segmentList") if isinstance(
                it.get("segmentList"), list) else []
            _share = (str(it.get("codeShare") or "").strip()
                      or str(it.get("sAirComName") or "").strip())
            # 中转停留 transMin 按段结构化真值（r326 增量：dump 61/62
            # 行可配对而库内 0/253）：段[0] 恒 '0'、段[i]=第 i 跳衔接
            # 停留；形状门=段数-1==转点数 且全数字（国内 transferPoints
            # 同门），求和落 layover + transInfo 真值源标（豁免族同标）
            _lay = None
            # None 门非 truthy 门：段[0].transMin=整数 0 是「首段无衔接」
            # 真值，0 or '' 会吞成空串令形状门恒败（卅一§4 二犯实录，
            # 单测夹具串形态绿而冻结 dump 回放红）
            _tmins = []
            for _s in _segs:
                _v = (_s or {}).get("transMin")
                _tmins.append("" if _v is None else str(_v).strip())
            if (_segs and all(t.isdigit() for t in _tmins)
                    and len(_segs) - 1 == len(trans.split("|"))):
                _lay = sum(int(t) for t in _tmins)
            # 中转各段承运航司名（r329：airComName 段级 join「|」，仅
            # 中转行、非共享行落——qunar H5 carrierSimpleName 同门：共享
            # 信息由 shareCarrier 承载防两键同屏混淆；元素内部全角｜原样
            # 保留=航司集团多名内部标记，与段间半角分隔符有区分度）
            _air_names = []
            for _s in _segs:
                _n = str((_s or {}).get("airComName") or "").strip()
                if _n:
                    _air_names.append(_n)
            _share_air = ("|".join(_air_names)
                          if (trans and not _share and _air_names) else "")
            # 机型体量/机型名：首个非空段（r329 段级补全：r328 seg0-only
            # 半落地——19/77 行 seg0 空而二段宽体有值，丢失面恰是长途
            # 宽体段；seg0 有值时渠道原序优先不倒挂）
            _psize = ""
            _ptype = ""
            for _s in _segs:
                if not _psize:
                    _w = str((_s or {}).get("craftWidthType") or "").strip()
                    if _w:
                        _psize = _w
                if not _ptype:
                    _dt = str((_s or {}).get("craftTypeDetail")
                              or (_s or {}).get("craftTypeName")
                              or "").split("（")[0].split("(")[0].strip()
                    if _dt:
                        _ptype = _dt
            try:
                n_day = max(0, (_dtm.date.fromisoformat(arr_d)
                                - _dtm.date.fromisoformat(dep_d)).days)
            except ValueError:
                n_day = 0
            row = {
                "price": price,
                "code": fnos.replace(",", "/"),
                "name": (f"{str(it.get('airlineName') or '').split('|')[0]}"
                         f"{fnos.split(',')[0]}"),
                # 航司名纯词（多段「|」连接取首段主承运）：FlightPrice
                # 行级 airline 与消费端航司词面同源（无值不落键同族律）
                **({"airline": _al}
                   if (_al := str(it.get("airlineName") or "")
                       .split("|")[0].strip()) else {}),
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                # 跨天无服务端字段（report §4）：日期差自推导，与
                # flightnorm cross_days 国际档（上限 7）同语言
                **(({"crossDayDesc": f"+{n_day}天"}) if n_day > 0 else {}),
                **({"transCity": trans.replace("|", "/")} if trans else {}),
                "totalDuration": fmt_dur(it.get("totalMin")),
                "airlineCode": iata2(str(fnos.split(",")[0])[:2]),
                # 舱名/余票/税费拆分（税已含在 price 内，tax 只作
                # 构成透传；barePrice=裸价排序口径）
                **({"cabin": _s} if (_s := str(it.get("cabinName") or "").strip()) else {}),
                **({"leftTickets": int(it["seat"])}
                   if isinstance(it.get("seat"), int) and 0 < it["seat"] < 9 else {}),
                **({"tax": float(it["avgTax"])}
                   if isinstance(it.get("avgTax"), (int, float))
                   and float(it["avgTax"]) > 0 else {}),
                **({"barePrice": float(it["avgBasePrice"])}
                   if isinstance(it.get("avgBasePrice"), (int, float))
                   and float(it["avgBasePrice"]) > 0 else {}),
                # 机场全名/航站楼（无值不落键同族律）
                **({"depAirport": _s} if (_s := str(it.get("dPortName") or "").strip()) else {}),
                **({"arrAirport": _s} if (_s := str(it.get("aPortName") or "").strip()) else {}),
                **({"depTerminal": _s} if (_s := str(it.get("dTerminal") or "").strip()) else {}),
                **({"arrTerminal": _s} if (_s := str(it.get("aTerminal") or "").strip()) else {}),
                # 共享：codeShare 执飞号/sAirComName 兜底直落（上方预计算）
                **({"shareCarrier": _share} if _share else {}),
                # 中转各段承运航司名（上方预计算：仅中转行、非共享行落）
                **({"shareAirline": _share_air} if _share_air else {}),
                # 舱位订座码（r329：cabinClass 段级订座码串透明直落，不做
                # 码→舱名映射——Q→公务/经济双值域实证弱配对=语义赌博
                # 禁区；形态门防 int 旧舱等/小写脏词面）
                **({"cabinCode": _s} if (_s := str(it.get("cabinClass") or "").strip())
                   and _RE_CABIN_CODE.fullmatch(_s) else {}),
                # 机场 IATA 码（r329：段链首末段 dPortIataCode/
                # aPortIataCode，iata3 门同国内 H1 三源同律）
                **({"depAirportCode": _s}
                   if (_s := iata3(((_segs or [{}])[0] or {})
                                   .get("dPortIataCode"))) else {}),
                **({"arrAirportCode": _s}
                   if (_s := iata3(((_segs or [{}])[-1] or {})
                                   .get("aPortIataCode"))) else {}),
                # 机型体量：首个非空段 craftWidthType（上方预计算：
                # r329 段级补全，值域与国内同词面不变）
                **({"planeSize": _psize} if _psize else {}),
                # 中转停留分钟 + 真值源标（上方形状门求和）
                **({"layover": _lay, "layoverSrc": "transInfo"}
                   if _lay else {}),
                **(({"stopCitys": _st} if (_st := stops.replace("|", ";")) else {})),
            }
            # 机型名：craftTypeDetail 主源（r326：dump 62/62 在场且
            # 更细'波音777-300ER'，旧源 craftTypeName 65% 且粗、恰在
            # 新宽体机型上空），缺落旧源同槽兜底；r329 段级补全=
            # 首个非空段（上方预计算）
            if _ptype:
                row["plane"] = _ptype
            out.append(row)
        return out

    def _fetch_intl(self, from_city: str, to_city: str,
                    dates: List[str],
                    ret_date: str = "") -> List[FlightPrice]:
        # ret_date 签名先收（fetch 调用形态 R15 往返一期已穿链，签名
        # 缺参=每轮 TypeError 生产四连实锤）；RT 语义 v1 未接（同
        # ctrip intl 律：双段形态待登录取数定谳）
        """国际采集主路径（r325）：与国内 fetch 同构（圈重试/限速/
        明细最低价同源），价格恒含税口径。"""
        results: List[FlightPrice] = []
        # 机场码→城市码归并（r334 案②）：tuniu dCityCode/aCityCode 只认
        # 城市码（PVG-CDG 与 SHA-CDG 探针多拍终态恒空、SHA-BKK 单拍
        # 出数；校准 R4x「acity=NRT 直传全窗零报价」同案）——纯机场码
        # 航线（PVG-CDG/LAX/DXB/SFO、SHA-NRT/LHR/JFK/YYZ）配线即死
        # 全史零行。fliggy/ctrip/tongcheng 三渠道同款归并先例
        # （fliggy:341/ctrip:196/tongcheng:151）；落库保持配置原码。
        fc = airport_city_code(from_city.upper())
        tc = airport_city_code(to_city.upper())
        for date in dates:
            t_h5 = time.time()
            self._last_challenge_intl = None
            self._last_intl_failure = None
            raw = self._hoop_intl(fc, tc, date)
            self._dump_raw(raw, f"tuniu_intl_{date}")
            if raw is None or isinstance(raw, IntlFailure):
                self.logger.warning("[tuniu][intl] %s 未拿到真实价格", date)
                _sig = getattr(self, "_last_challenge_intl", None)
                _fail = (raw if isinstance(raw, IntlFailure)
                         else getattr(self, "_last_intl_failure", None))
                if _sig is not None:
                    status, detail = _sig.status, _sig.detail
                elif isinstance(_fail, IntlFailure):
                    # 超时/请求异常/解析失败按类型落账（不是无票）
                    status, detail = _fail.status, _fail.detail
                elif type(self).login_suspect:
                    status, detail = "login", "国际接口要求登录"
                else:
                    status, detail = "error", "国际接口未返回价格（无失败证据）"
                self.path_note(
                    "H5/API", status, date=date, detail=detail,
                    ms=int((time.time() - t_h5) * 1000))
                self._sleep()
                continue
            flights = self._parse_offers_intl(raw)
            self._stamp_intl(flights, fc, tc)
            best = min(flights, key=lambda f: f["price"]) if flights else None
            if best is not None:
                self.path_note("H5/API", "ok", rows=len(flights), date=date,
                               detail="国际列表接口",
                               ms=int((time.time() - t_h5) * 1000))
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=str(best.get("airline") or ""),
                    flight_no=str(best.get("code") or "").split("/")[0],
                    depart_time=best.get("depTime", ""),
                    arrive_time=best.get("arrTime", ""),
                    extra=json.dumps(flights, ensure_ascii=False),
                ))
                n_d = sum(1 for f in flights if not f.get("transCity"))
                self.logger.info(
                    "[tuniu][intl] %s 最低含税价 ￥%.0f (%s)（明细 %d 条："
                    "直飞 %d / 中转 %d）",
                    date, best["price"], best.get("code") or "",
                    len(flights), n_d, len(flights) - n_d)
            else:
                self.logger.warning("[tuniu][intl] %s 未解析到价格", date)
                _plist = (raw.get("productList")
                          if isinstance(raw, dict) else None)
                if _plist is not None and not isinstance(_plist, list):
                    self.path_note(
                        "H5/API", "parse_error", date=date,
                        detail="国际接口 productList 非数组",
                        ms=int((time.time() - t_h5) * 1000))
                elif isinstance(_plist, list) and _plist:
                    # 有行但全被解析门剔除=解析失败，不是真源无票
                    self.path_note(
                        "H5/API", "parse_error", date=date,
                        detail="国际接口 %d 行均未解析出价格" % len(_plist),
                        ms=int((time.time() - t_h5) * 1000))
                else:
                    # 干净聚合响应（needQueryMore != '1'）且空 productList
                    # 才允许落 empty：真源边界
                    self.path_note("H5/API", "empty", date=date,
                                   detail="国际接口聚合完成但无报价",
                                   ms=int((time.time() - t_h5) * 1000))
            self._sleep()
        return results

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        self.path_reset()
        if is_intl_route(from_city, to_city):
            return self._fetch_intl(from_city, to_city, dates,
                                    ret_date=ret_date)
        results: List[FlightPrice] = []
        # 途牛国内列表/接口使用城市码（北京=BJS），机场码 PEK 会落空；
        # 与飞猪/携程国内同律先归并城市码，FlightPrice 仍保留原航线。
        fc, tc = airport_city_code(from_city.upper()), airport_city_code(to_city.upper())
        pc_map = {}
        h5_token = ""
        if not ret_date:
            try:
                h5_token = self._saved_page_token(fc, tc, dates[0])
            except Exception:
                h5_token = ""
        if not ret_date and not h5_token:
            try:
                pc_map = self._fetch_pc_dom(fc, tc, dates)
            except Exception as e:
                self.logger.warning("[tuniu] PC 列表异常，回退 H5/API: %s", e)
                pc_map = {}
            # 无痕 profile 会触发滑块；复用已保存的可信会话开可见窗口
            # 再取一次（不破解验证码；仍被挑战则如实落 blocked）。
            missing = [d for d in dates if not (pc_map.get(d) or [])]
            # 可见窗口只在用户主动探针时兜底；定时监控不弹窗。
            if missing and getattr(self, "probe_mode", False):
                try:
                    self.logger.info("[tuniu] PC 无明细，复用已保存会话可见窗口重试 %d 日", len(missing))
                    headed = self._fetch_pc_dom(fc, tc, missing, headless=False,
                                                path_label="PC可见")
                    for d in missing:
                        if headed.get(d):
                            pc_map[d] = headed[d]
                except Exception as e:
                    self.logger.warning("[tuniu] PC 可见窗口重试失败: %s", e)
        for date in dates:
            pc_rows = pc_map.get(date) or []
            if pc_rows:
                best = min(pc_rows, key=lambda f: f["price"])
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=best.get("name", "")[:20],
                    flight_no=best.get("code", ""),
                    depart_time=best.get("depTime", ""),
                    arrive_time=best.get("arrTime", ""),
                    extra=json.dumps(pc_rows, ensure_ascii=False)))
                self.last_path = "PC列表"
                self.logger.info(
                    "[tuniu] %s PC 明细 %d 条 · 最低 ￥%.0f",
                    date, len(pc_rows), float(best["price"]))
                continue
            t_h5 = time.time()
            self._last_challenge = None
            raw = self._hoop(fc, tc, date)
            self._dump_raw(raw, f"tuniu_raw_{date}")
            if raw is None:
                self.logger.warning("[tuniu] %s 未拿到真实价格", date)
                _sig = getattr(self, "_last_challenge", None)
                self.path_note(
                    "H5/API",
                    _sig.status if _sig else
                    ("login" if type(self).login_suspect else "empty"),
                    date=date,
                    detail=(_sig.detail if _sig else
                            "m.tuniu.com 接口未返回价格"),
                    ms=int((time.time() - t_h5) * 1000))
                self._sleep()
                continue

            offers = self._parse_offers(raw, logger=self.logger)
            best = self._lowest_offer(offers)
            flights = self._offers_to_flights(offers)
            if best is not None and best.get("price"):
                self.path_note("H5/API", "ok", rows=len(flights), date=date,
                               detail="m.tuniu.com 列表接口",
                               ms=int((time.time() - t_h5) * 1000))
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=best.get("airline") or "",
                    flight_no=best.get("flight_no") or "",
                    depart_time=best.get("depart_time") or "",
                    arrive_time=best.get("arrive_time") or "",
                    extra=json.dumps(flights, ensure_ascii=False) if flights else "",
                ))
                n_d = sum(1 for f in flights if not f.get("transCity"))
                self.logger.info("[tuniu] %s 最低价 ￥%.0f (%s %s)（明细 %d 条：直飞 %d / 中转 %d）",
                                 date, best["price"], best.get("airline") or "",
                                 best.get("flight_no") or "",
                                 len(flights), n_d, len(flights) - n_d)
            else:
                self.logger.warning("[tuniu] %s 未解析到价格", date)
                self.path_note("H5/API", "empty", date=date,
                               detail="接口有响应但未解析出价格",
                               ms=int((time.time() - t_h5) * 1000))
            self._sleep()
        return results

    @staticmethod
    def _to_price(v: Any) -> Optional[float]:
        # 价格带 300–50000 与其余四渠道对齐（补下限：单渠道
        # 零下限曾让改版键义漂移出的小数/异常值直入渠道最低价对比）
        try:
            f = float(v)
            return f if PRICE_MIN <= f <= PRICE_MAX else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _adt_fare(cls, price_list: list) -> tuple:
        """ADT 价与同 breakdown 折扣/公布运价/舱位配对返回 (price,
        discount, black, stdfare, cabin, cabin_code)。

        价格=各 flightPriceList 中 psgType=ADT 的最低 baseFare；折扣、
        公布运价、舱名与舱位代码全部随选中价所在政策提取（跨政策取
        即串舱——r222 实锤：公务舱政策排前时行价是经济舱最低价却标
        「公务舱」，三份 dump 5/40、2/46、3/44 复现）。discount 值形如
        "6.7折"/"全价"（dump 实证），"0"/空=未报价占位（ADT 也有
        13/77 行）不作为折扣值。无 ADT 价返回 (None, "", False, None,
        "", "")。black=选中价政策 supportBlack 旗标（渠道调研 B：45/117
        报价单选中价来自黑卡政策，报文零文字性会员门标注——不改选价
        口径，只落透明标记让受众自判）；同价平手按普通政策算（标记零
        误报），舱名随平手胜者。stdfare=同条目 bcTaxExclusiveFare 舱位
        公布运价（报销/里程累积口径，baseFare=bcTax×1.01 恒系数互证；
        ADT 正值 56%、-1/0 占位 44%——非正数一律 None 不落键）。
        cabin_code=选中政策内聚合恰一个舱位代码才落（政策内多码宁缺
        勿错；跨政策聚合曾把出勤压到 35-59%）。

        观察哨（退改费槽位）：fareBreakdownList 的 changeFee/diffFee/
        totalRiseFee 三键恒在但全量恒 0（未报价占位）——ADT 选中
        breakdown 出现非零 changeFee 即按 qunar 同名同义键补采
        returnFee/changeFee（取法挂本函数胜出政策配对，与 discount/
        stdFare 同门，消费端 _rc_txt 出口现成）。"""
        best = None
        disc = ""
        black = False
        std = None
        cab = ""
        code = ""
        for pr in price_list or []:
            is_black = bool(pr.get("supportBlack"))
            for fb in pr.get("fareBreakdownList", []) or []:
                if fb.get("psgType") != "ADT":
                    continue
                p = cls._to_price(fb.get("baseFare"))
                if not p:
                    continue
                if best is None or p < best or (p == best and black and not is_black):
                    best = p
                    d = str(fb.get("discount") or "").strip()
                    disc = d if d not in ("", "0") else ""
                    black = is_black
                    cab = cls._cabin_from_pj(pr.get("priceJourneyCabinList"))
                    codes = []
                    for pj in pr.get("priceJourneyCabinList") or []:
                        for pfc in (pj.get("priceFlightCabinList") or []):
                            c = str((pfc or {}).get("cabinCode") or "").strip()
                            if c and c not in codes:
                                codes.append(c)
                    code = codes[0] if len(codes) == 1 else ""
                    try:
                        s = float(fb.get("bcTaxExclusiveFare"))
                    except (TypeError, ValueError):
                        s = None
                    # 有限性+值域双挡：inf/NaN 与超价格带脏值不落
                    # （inf 过 s>0 会产非法 JSON Infinity）
                    std = s if s and 0 < s <= PRICE_MAX else None
        return (best, disc, black, std, cab, code)

    @classmethod
    def _biz_fare(cls, price_list: list) -> Optional[float]:
        """公务/商务/头等舱政策的 ADT 最低 baseFare（bizPrice）。

        与 _adt_fare 完全独立遍历（次低价≠公务舱，串舱即错配——ctrip
        「舱位随最低价政策配对」同律；主价链的舱名随选中政策提取后，
        本函数的独立高档舱口径不变）；舱位判定挂 priceJourneyCabinList
        嵌套层（_cabin_from_pj 同路径）；判定词表与 tongcheng pts.td 一致
        （三渠道 bizPrice 同键同协议）。无高档舱政策/全部超域返回 None，
        调用方不落键。"""
        best = None
        for pr in price_list or []:
            if cls._cabin_from_pj(
                    pr.get("priceJourneyCabinList")) not in (
                    "公务舱", "商务舱", "头等舱"):
                continue
            for fb in pr.get("fareBreakdownList", []) or []:
                if fb.get("psgType") != "ADT":
                    continue
                p = cls._to_price(fb.get("baseFare"))
                if p and (best is None or p < best):
                    best = p
        return best

    @classmethod
    def _child_infant_fares(cls, price_list: list) -> tuple:
        """(child, infant) 最低 baseFare（psgType=CHD/INF，10-05 dump
        164 处实证）。与 qunar H5 childPrice/infantPrice 数值协议对齐
        （跨渠道口径统一）：无值返回 (None, None) 由调用方不落键。
        勿走主价格带过滤（PRICE_MIN 下界是成人票价纪律，真实婴儿价
        常低于下界会被整段杀掉——本函数自带宽域 50–50000）。

        观察哨（资格价族，goal 轮观测轮定谳）：psgType=GMJC 在末代
        dump（断供前 10-12/13）7 处/文件在场，值域恰为同政策 ADT
        半价（36/36）——军残/残疾类资格价假说，消费端无对应词面、
        语义未证维持不采。渠道恢复供给后按本键复核：值域脱离「ADT
        半价」带或与资格词面并现，即按「资格价」决策域立项（对齐
        qunar priceLabel 限龄族的透明标记先例）；渠道级观测随 trans
        行型哨与 zrow 哨覆盖。"""
        child = infant = None
        for pr in price_list or []:
            for fb in pr.get("fareBreakdownList", []) or []:
                t = fb.get("psgType")
                if t not in ("CHD", "INF"):
                    continue
                try:
                    p = float(fb.get("baseFare"))
                except (TypeError, ValueError):
                    continue
                if not (50 < p <= 50000):
                    continue
                if t == "CHD":
                    child = p if child is None else min(child, p)
                else:
                    infant = p if infant is None else min(infant, p)
        return (child, infant)

    @classmethod
    def _cabin_from_pj(cls, pj_list) -> str:
        """priceJourneyCabinList → priceFlightCabinList → cabinTypeName。

        观察哨（fareList[].filtered.cabinType 码 4）：渠道舱位词表只
        定义 1=经济舱/"2,3"=头等公务，码 4 无词面（推断超级经济舱未
        证）——filters 词表出现新 code→text 对即按渠道自带词面复验
        （数字码→中文映射只在「词面复验通过期内」有效）。"""
        for pj in pj_list or []:
            if not isinstance(pj, dict):
                continue
            for pc in pj.get("priceFlightCabinList") or []:
                if isinstance(pc, dict) and str(pc.get("cabinTypeName") or "").strip():
                    return str(pc["cabinTypeName"]).strip()
        return ""

    @staticmethod
    def _find_flight_detail(flight_list: dict, flight_no: str) -> dict:
        if not isinstance(flight_list, dict):
            return {}
        if flight_no in flight_list:
            return flight_list[flight_no]
        for key, val in flight_list.items():
            if key.split("#", 1)[0] == flight_no:
                return val
        return {}

    @classmethod
    def _build_transfer_offer(cls, fare: dict, flight_nos_str: str,
                              data: dict) -> Optional[dict]:
        """多段 offer 拼装中转行（flightOptionList 段链结构化真值）。
        段链 flightItems[].flightNo=「号#日期#起#终」自带逐段日期，
        整体起终=首段出发×末段到达（多段 offer 地雷的「明细仅首段
        口径」前提不复存在）；transCity/layover 取 transferPoints
        真值（layoverSrc=transInfo 结构化豁免族）；机型/餐食随末段
        （fliggy 中转主槽=二段段位协议同构）；全程时长带日期维度
        重建（钟面差%1440 盲区的根治形态）。任一结构前提缺席返
        None（调用方退回整行跳过，宁缺勿错不造数据）。"""
        fol = data.get("flightOptionList") or {}
        entry = fol.get(flight_nos_str)
        if not isinstance(entry, dict):
            return None
        # 观察哨（r333 走查：出勤零=守卫蕴含零非断链）：同条目并列
        # 键 transitService（r333 语料 3 条合格段链值域恒 []）——
        # 翻身条件=「多段条目在场且 transitService 非 []」，届时按
        # flightnorm transitServiceLabel 兜底族评估「中转服务承诺」
        # 词面（对齐 tongcheng fwbqs「第N程：免费上网」出口位）。
        items = [it for it in (entry.get("flightItems") or [])
                 if isinstance(it, dict) and it.get("flightNo")]
        tps = [t for t in (entry.get("transferPoints") or [])
               if isinstance(t, dict)
               and (t.get("cityName") or t.get("cityIataCode"))]
        if len(items) < 2 or not tps:
            return None
        flight_list = data.get("flightList") or {}
        segs = []
        for it in items:
            parts = str(it["flightNo"]).split("#")
            no = parts[0]
            seg_date = parts[1] if len(parts) > 1 else ""
            # 段链完整键精确优先：flightList 同号多日期键并存时裸号
            # 前缀匹配按 dict 序取首个=A 段时刻来自另一日期班期的
            # 混装行（Soldier Major-1）；键同格式精确命中即根治
            det = flight_list.get(str(it["flightNo"]))
            if not isinstance(det, dict) or not det:
                det = cls._find_flight_detail(flight_list, no)
            if not (no and str(det.get("departureTime") or "").strip()
                    and str(det.get("arrivalTime") or "").strip()):
                return None
            segs.append((no, seg_date, det))
        first_no, first_date, first_det = segs[0]
        last_no, last_date, last_det = segs[-1]
        dep_date = (first_date
                    or str(first_det.get("departureDate") or ""))[:10]
        arr_date = (last_date
                    or str(last_det.get("arrivalDate") or ""))[:10]
        if not (len(dep_date) == 10 and len(arr_date) == 10):
            return None
        price, fare_disc, fare_black, fare_std, fare_cab, fare_code = \
            cls._adt_fare(fare.get("flightPriceList"))
        child, infant = cls._child_infant_fares(
            fare.get("flightPriceList"))
        biz = cls._biz_fare(fare.get("flightPriceList"))
        if not price:
            return None
        # 转点城市/停留：城市名在场即落（数量与段数不匹配的未证形状
        # 不求和落 layover——宁缺勿错）；transferTime 分钟字符串
        trans_city = ";".join(
            str(t.get("cityName") or t.get("cityIataCode")).strip()
            for t in tps)
        layover = None
        if len(tps) == len(items) - 1 and all(
                str(t.get("transferTime") or "").strip().isdigit()
                for t in tps):
            layover = sum(int(str(t["transferTime"]).strip())
                          for t in tps)
        # 全程时长（分钟）：段链日期权威，钟面差带日期维度
        flight_time = ""
        try:
            from datetime import date as _d
            d0 = _d.fromisoformat(dep_date)
            d1 = _d.fromisoformat(arr_date)

            def _m(hhmm: str) -> int:
                hh, mm = str(hhmm).split(":")[:2]
                return int(hh) * 60 + int(mm)

            dur = ((d1 - d0).days * 1440
                   + _m(last_det["arrivalTime"])
                   - _m(first_det["departureTime"]))
            if dur > 0:
                flight_time = str(dur)
        except (ValueError, IndexError):
            pass
        offer = {
            "airline": first_det.get("airlineCompany"),
            "airlineCode": iata2(first_det.get("airlineIataCode")),
            "flight_no": flight_nos_str,
            "depart_time": first_det.get("departureTime"),
            "arrive_time": last_det.get("arrivalTime"),
            "price": price,
            "dep_date": dep_date,
            "arr_date": arr_date,
            "flight_time": flight_time,
            # 舱位/黑卡/公务价随选中价政策（与直飞同管道，r222 串舱
            # 防线复用；cabin_clean 清污门同门生效）
            "cabin": cabin_clean(
                {"cabin": (fare_cab
                           or cls._cabin_from_pj(
                               fare.get("priceJourneyCabinList"))
                           or ""),
                 "price": price, "bizPrice": biz}),
            "blackCard": fare_black,
            "bizPrice": biz,
            # 机型/餐食随末段（fliggy 中转主槽=二段段位协议）；组合行
            # 单件字段（准点率/机龄/延误/经停点）无单一真值不落
            "craftTypeName": (last_det.get("craftTypeName")
                              or str(last_det.get("craftType")
                                     or "").strip()),
            "mealName": last_det.get("mealName") or "",
            # 中转结构化真值：城市名透传（跨渠道协议=渲染「经北京」，
            # 旧「中转」标记死分支退役）；layover 分钟 + transInfo
            # 真值源标（normalize 守卫豁免族）
            "transCity": trans_city,
            **({"layover": layover, "layoverSrc": "transInfo"}
               if layover else {}),
            # 航站楼/机场名/机场码：首段出发×末段到达（行级真值）
            **({"depTerminal": str(first_det.get("dTerminal")).strip()}
               if str(first_det.get("dTerminal") or "").strip() else {}),
            **({"arrTerminal": str(last_det.get("aTerminal")).strip()}
               if str(last_det.get("aTerminal") or "").strip() else {}),
            "depAirport": str(first_det.get("dPortName") or "").strip(),
            "arrAirport": str(last_det.get("aPortName") or "").strip(),
            "depAirportCode": iata3(first_det.get("dPortIataCode")),
            "arrAirportCode": iata3(last_det.get("aPortIataCode")),
            "cabinCode": fare_code,
        }
        if fare_disc:
            offer["discount"] = fare_disc
        if fare_std:
            offer["stdFare"] = fare_std
        if child is not None:
            offer["childPrice"] = child
        if infant is not None:
            offer["infantPrice"] = infant
        return offer

    @classmethod
    def _parse_offers(cls, raw: Optional[dict], logger=None) -> List[dict]:
        if not raw:
            return []
        data = raw.get("data", raw) or {}
        fare_list = data.get("fareList") or []
        # 观察哨（r323 渠道调研）：fareList[].copyLowestFlag 新槽位
        # （2027 档 dump 19/19 恒 False，更早代无此键）——「渠道标记
        # 最低价」嫌疑（键名推断，无报文词面，采了即口径赌博）。翻
        # True 即事件：随全量键 diff 复验其值域与行价关系后再议采集
        flight_list = data.get("flightList") or {}

        offers: List[dict] = []
        seen = set()
        for fare in fare_list:
            options = fare.get("flightOptions") or []
            flight_nos_str = options[0].get("flightNos") if options else None
            if not flight_nos_str:
                continue
            first_no = flight_nos_str.split("-")[0]
            detail = cls._find_flight_detail(flight_list, first_no)
            # 多段 offer：flightOptionList 段链结构化真值在场时拼装
            # 中转行（整体起终=段链日期×段时刻，转点城市/停留分钟
            # 真值直落）；段链不可得时退回旧行为整行跳过（宁缺勿错）
            if "-" in flight_nos_str or detail.get("transCity"):
                offer_tr = cls._build_transfer_offer(
                    fare, flight_nos_str, data)
                if offer_tr is not None:
                    key = (offer_tr["flight_no"], offer_tr["depart_time"],
                           offer_tr["price"])
                    if key not in seen:
                        seen.add(key)
                        offers.append(offer_tr)
                elif logger:
                    logger.debug("[tuniu] 跳过多段中转 offer %s"
                                 "（段链结构化真值不可得）", flight_nos_str)
                continue
            price, fare_disc, fare_black, fare_std, fare_cab, fare_code = \
                cls._adt_fare(fare.get("flightPriceList"))
            child, infant = cls._child_infant_fares(
                fare.get("flightPriceList"))
            biz = cls._biz_fare(fare.get("flightPriceList"))
            offer = {
                "airline": detail.get("airlineCompany"),
                # 航司二字码（detail.airlineIataCode「MU」，45/45+46/46
                # 全场）：机器可读航司键，与 qunar shortCarrier 跨渠道
                # 统一出口 airlineCode；iata2 守卫不匹配落空串。注意
                # detail 层 dCityIataCode/aCityIataCode 是城市码勿混
                "airlineCode": iata2(detail.get("airlineIataCode")),
                "flight_no": flight_nos_str,
                "depart_time": detail.get("departureTime"),
                "arrive_time": detail.get("arrivalTime"),
                "price": price,
                "dep_date": detail.get("departureDate"),
                "arr_date": detail.get("arrivalDate"),
                "flight_time": detail.get("flightTime"),
                # 舱位在 fare 层且随选中价政策配对（r222 串舱修复：舱名
                # 取 _adt_fare 胜出政策的 cabinTypeName，跨政策借名即
                # 串舱；detail.cabinTypeName 恒缺〔DB 实锤 100% 空〕，
                # 旧顶层形态走 fare 级兼容回退，两层皆无宁缺勿错）。
                # 写入端再过 cabin_clean 清污门（与消费端同判据单源）：
                # 渠道会把低价政策标成高档舱名（DB 近 7 天 cabin=公务舱
                # 4039 行 price 中位 3310≈经济舱、bizPrice=8340 同行
                # 100% 同现），价位矛盾形态落库即脏值——消费端渲染门
                # 全挡，此门管 DB 面（补全链的补全源读取也在 alerter
                # 侧过同门，双层各自独立成立）
                "cabin": cabin_clean(
                    {"cabin": (detail.get("cabinTypeName") or fare_cab
                               or cls._cabin_from_pj(
                                   fare.get("priceJourneyCabinList"))
                               or ""),
                     "price": price, "bizPrice": biz}),
                # 黑卡价旗标随选中价透传（offer→row 有值才落，见 _adt_fare）
                "blackCard": fare_black,
                # 公务/商务/头等舱参考价（ctrip bizPrice 同键同协议，
                # webui 通道现成；offer→row 有值才落）
                "bizPrice": biz,
                # 决策四件套必须随 offer 透传：_offers_to_flights 从 offer
                # 读这些键，漏带即机型/餐食/准点率/经停恒空（假解析）
                # craftTypeName 缺失行落 craftType 原码兜底（B 篇 33/33
                # 恒在，补 DB 11% 机型缺口；不建码表翻译宁缺勿错，
                # 值形「73M」与 tongcheng plane 同域）
                "craftTypeName": (detail.get("craftTypeName")
                                  or str(detail.get("craftType")
                                         or "").strip()),
                "mealName": detail.get("mealName") or "",
                # 观察哨（机上 WiFi）：detail.hasWifi 与
                # priceFlightCabinList[].hasWifi 两层全量恒 False（占位）
                # ——任一层翻 True 即按 labels 同出口收「机上WiFi」词面
                "onTimeRate": _prate(detail.get("onTimeRate")),
                "stopPoints": detail.get("stopPoints") or [],
                # ---- 决策字段补采（10-05 dump 46 航班实证，
                # flightList 值层，_find_flight_detail 已取到 detail）----
                # 航站楼：aTerminal 46/46（T1/T2）；dTerminal 间歇下发
                # （09-25 dump 43/43 有值，10-04~07 恒空串）——两键同守
                # 有值才落（无值不落键族律：键在场零信息；消费端 or ""
                # 判定缺键等价）
                **({"arrTerminal": str(detail.get("aTerminal")).strip()}
                   if str(detail.get("aTerminal") or "").strip() else {}),
                **({"depTerminal": str(detail.get("dTerminal")).strip()}
                   if str(detail.get("dTerminal") or "").strip() else {}),
                # 共享实际承运航班号：codeShare 实测即执飞航班号字符串
                # （"CZ6981"/"MU5700"，24/46；非布尔），与
                # shareCarrier「实际承运航班号」语义一致直接落
                # （sAirComName 航司名兜底合并至下方 shareCarrier）
                # 历史平均延误（分钟）：字符串形态 "29"/""（键在场 46/46、
                # 可转数字 28/46），仅数字转 int；无值/非数字不落键
                # （空串占位曾达生产 44.2%——消费端 None/缺键等价，
                # 哨兵出勤统计不变，纯 DB 卫生）
                **({"avgDelay": int(str(detail["avgDelayTime"]).strip())}
                   if str(detail.get("avgDelayTime") or "")
                   .strip().isdigit() else {}),
                # 机龄原始串（"6.3"，28/46），协议要求保留原始形态不转数值；
                # 无值不落键（空串占位曾 42% 平铺——缺席与空串消费端
                # 等价，载荷卫生 avgDelay/discount 同族）
                **({"planeAge": _pa} if (_pa := str(detail.get("flightYear")
                                                  or "").strip()) else {}),
                # 宽体机标签（调研④）：planeModelName 值域
                # 大/中/小，仅「大」落「宽体机」——craftTypeName 今日
                # 「波音737-800」无大小后缀，机型大小信息仅此键有；
                # 中/小不落（宽体=静音/宽敞正决策信号，反向词是噪音）；
                # 无值不落键（r241 残留族收口，offer 层与行层透传各自成立）
                **(({"labels": _lb}
                    if (_lb := ("宽体机" if str(detail.get("planeModelName")
                                                or "").strip() == "大"
                               else "")) else {})),
                # 机型体量结构化键（大/中/小 → 「大型机…」，与
                # fliggy/qunar PC 同键同值域；「宽体机」labels 是展示词
                # 保留双通道）；无值不落键（r241 残留族收口）。
                # 观察哨 W-T1（r268 渠道调研）：同层新槽位 crowdTagName
                # 前提更新（r324 渠道调研最新代叶清点）：键级缺席（非
                # 恒空值）——触发条件相应改「键回归且带非空词面」即
                # 复核（labels 同出口收，词面进白名单判据照走）；键
                # 回归空值与带值是两种事件，届时分别复核
                **(({"planeSize": _ps}
                    if (_ps := {"大": "大型机", "中": "中型机",
                                "小": "小型机"}.get(
                       str(detail.get("planeModelName") or "").strip(), ""))
                    else {})),
                # 机场全名（dPortName/aPortName「天山机场/
                # 浦东机场」，dump 136/136 在场）——同城多场（虹桥 vs
                # 浦东）决策信息，五渠道键名对齐
                "depAirport": str(detail.get("dPortName") or "").strip(),
                "arrAirport": str(detail.get("aPortName") or "").strip(),
                # H1 机器可读机场码（dPortIataCode/aPortIataCode
                # 137/137 全 ^[A-Z]{3}$，与 qunar 48 共同航班号 48/48 同
                # 码对；iata3 守卫不匹配不落）。注意 detail 层还有
                # dCityIataCode/aCityIataCode 是城市码同串不同义，勿混
                "depAirportCode": iata3(detail.get("dPortIataCode")),
                "arrAirportCode": iata3(detail.get("aPortIataCode")),
                # 舱位代码随选中价政策聚合（_adt_fare 政策内单码守卫）
                "cabinCode": fare_code,
                # 共享实际承运：codeShare=执飞航班号优先（「CZ6981」），
                # 缺时落共享航司名 sAirComName（「上航」，70/136——
                # codeShare 73 行与之互补）。
                # 观察哨（codeShare 口径）：该键在场率已漂移至全量在场
                # ——抽验若现「值=同航线近期班号但时刻相异」形态即渠道
                # 语义漂移（假共享），须复核 shareCarrier 全量落键口径
                "shareCarrier": (str(detail.get("codeShare") or "").strip()
                                 or str(detail.get("sAirComName")
                                        or "").strip()),
                # 折扣：与所选价同一 ADT breakdown 配对（"6.7折"/"全价"，
                # ADT 有值 64/77），_adt_fare 已过滤 "0" 占位
            }
            # discount 无值不落键（avgDelay 同族键卫生：空串占位曾达
            # 生产现窗 5.7%，消费端 None/空串等价、出勤统计不虚高）
            if fare_disc:
                offer["discount"] = fare_disc
            # 公布运价（与所选价同 breakdown 配对，_adt_fare 内已挡
            # -1/0 占位）：报销/里程累积口径，float 协议无值不落键
            if fare_std:
                offer["stdFare"] = fare_std
            # 童婴价（数值协议与 qunar H5 对齐）：无值不落键
            if child is not None:
                offer["childPrice"] = child
            if infant is not None:
                offer["infantPrice"] = infant
            # layover（detail.duration，卫生改有值才落）：键级
            # 渠道侧消失（两日 dump 0/90；DB 09-10 起 12 天 ~8 万行
            # 0 非空，起即空非本轮回归）——fliggy totalDuration
            # 先例防恒空键堆 extra；渠道若恢复键级在场自动回归
            if detail.get("duration"):
                offer["layover"] = detail.get("duration")
            key = (offer["flight_no"], offer["depart_time"], offer["price"])
            if key not in seen:
                seen.add(key)
                offers.append(offer)
        return offers

    @staticmethod
    def _lowest_offer(offers: List[dict]) -> Optional[dict]:
        priced = [o for o in offers if o.get("price")]
        return min(priced, key=lambda o: o["price"]) if priced else None

    @staticmethod
    def _offers_to_flights(offers: List[dict]) -> List[dict]:
        """统一航班级明细 schema（挂 extra）。flightNos 含多段即中转；
        该端点实测以直飞为主。"""
        out = []
        for o in offers:
            if not o.get("price"):
                continue
            dep_d = (o.get("dep_date") or "")[:10]
            arr_d = (o.get("arr_date") or "")[:10]
            dep_t = _hhmm(o.get("depart_time"))
            arr_t = _hhmm(o.get("arrive_time"))
            if not (dep_d and arr_d and dep_t and arr_t):
                continue
            fnos = (o.get("flight_no") or "").replace("-", ",")
            is_transfer = "," in fnos
            ft = o.get("flight_time")
            dur = ""
            try:
                mins = int(ft)
                dur = f"{mins // 60}时{mins % 60}分"
            except (TypeError, ValueError):
                pass
            # 决策字段（detail 已取到，只多取 4 键）：机型/餐食/准点率/经停点
            row = {
                "price": float(o["price"]),
                "code": fnos.replace(",", "/"),
                "name": f"{o.get('airline') or ''}{fnos.split(',')[0]}",
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                # 「属性不适用即落空串」残留族无值不落键（r241 观测
                # 立案 8 键收口；transCity 中转标记/crossDayDesc 跨天
                # 标识有值照落）
                # transCity：拼装中转行透传真城市名（跨渠道协议=
                # 渲染「经北京」，flightnorm AIRPORT_CN 反查同域）；
                # 无真值的多段形态兜底「中转」标记（_build_transfer_
                # offer 保证真值在场，此兜底防多段行混入直飞池）
                **({"transCity": (_tc or "中转")}
                   if (_tc := str(o.get("transCity") or "").strip())
                   or is_transfer else {}),
                **(({"crossDayDesc": "+1天"} if dep_d != arr_d else {})),
                "totalDuration": dur,
                "cabin": (o.get("cabin") or "").strip(),
                # 黑卡价透明标记：仅选中价来自黑卡政策时落键（有值才落）
                **({"blackCard": True} if o.get("blackCard") else {}),
                # 公务/商务/头等舱参考价（int 协议与 qunar bizPrice 对齐）
                **({"bizPrice": int(o["bizPrice"])}
                   if o.get("bizPrice") else {}),
                "plane": str(o.get("craftTypeName") or "").split("（")[0]
                          .split("(")[0].strip(),
                # meal 无值不落键（r311 同族残留收口：五渠道 meal 平铺
                # 末位；「无餐」词面是有值形态照落。备案：同行 plane
                # 仍平铺，断供期无观测窗实证，r311_recon_A 备案复供后议）
                **({"meal": _tn_meal}
                   if (_tn_meal := str(o.get("mealName") or "").strip())
                   else {}),
                # 无值不落键（avgDelay/discount 同族律：渠道占位「20%」
                # 与无值经 _prate 置空后，空串键曾达生产 20.2% 常态化）
                **({"prate": _prt}
                   if (_prt := _prate(o.get("onTimeRate"))) else {}),
                # 经停决策字段：stopPoints 实报为 dict 列表（debug dump
                # 实锤 {"airPortCode":"NNY","cityName":"南阳","duration":
                # "50"}），曾按 isinstance(x,str) 过滤全滤空——经停班被
                # 当直飞入库，徽标/经停哪、停多久全丢；三键无值不落
                # （r241 残留族收口，stopCitys/stopTime/stopWin 同源同门）。
                # 观察哨（stopPoints[].airPortName 机场全名）：低值不采
                # 备案（r338 值域精化：机场名与城市名字面可派生率
                # 10/17——「姜营机场/南阳」等 7 处机场名不含城市字面，
                # 旧「恒可派生」前提字面已破；但 cityName↔airPortName
                # 城市归属 0 例不一致，且「经停哪里」已由 stopCitys
                # 承载、经停短暂落地无值机/航站楼决策差）——出现
                # 归属不一致（airPortName 与 cityName 分属不同城市）
                # 的行再按经停机场全名立项
                **(({"stopCitys": _scp} if (_scp := ";".join(
                    str(x.get("cityName") or x.get("airPortName") or "")
                    for x in (o.get("stopPoints") or [])
                    if isinstance(x, dict)
                    and (x.get("cityName") or x.get("airPortName")))) else {})),
                **(({"stopTime": _stt} if (_stt := _stop_time(
                    o.get("stopPoints"))) else {})),
                # 经停窗口绝对时刻（arrivalTime/departrueTime 对，多段
                # 「/」连接；恒落键与 stopCitys/stopTime 同族形态）
                **(({"stopWin": _sw} if (_sw := _stop_window(
                    o.get("stopPoints"))) else {})),
                # 新决策字段（offer 层已算好，键路径/dump 命中率
                # 见 _parse_offers 注释块）。航站楼随 offer 层同守
                # 无值不落键：offer 缺键时 str(o.get(...)) 恒产空串，
                # 空串键照落=DB 面恒空键（行层与 offer 层各自独立
                # 成立；dTerminal 间歇下发，恒空代际自然零出勤）
                **({"arrTerminal": str(o["arrTerminal"]).strip()}
                   if o.get("arrTerminal") else {}),
                **({"depTerminal": str(o["depTerminal"]).strip()}
                   if o.get("depTerminal") else {}),
                **(({"shareCarrier": _shc}
                    if (_shc := str(o.get("shareCarrier") or "").strip())
                    else {})),
                # 决策字段必须随 offer 透传（教训两次在案）：航司二字码/
                # 公布运价同律，漏带即行级恒空
                "airlineCode": str(o.get("airlineCode") or "").strip(),
                **({"stdFare": float(o["stdFare"])}
                   if o.get("stdFare") else {}),
                # 无值不落键（同 detail 层：空串占位曾达生产 44.2%）
                **({"avgDelay": o["avgDelay"]}
                   if isinstance(o.get("avgDelay"), int) else {}),
                **({"planeAge": o["planeAge"]} if o.get("planeAge") else {}),
                # 无值不落键（detail 层同律：空串占位不落）
                **({"discount": o["discount"]} if o.get("discount") else {}),
                # 五键透传：labels 曾在 offer 层算好但此处漏带
                # ——「决策字段必须随 offer 透传」教训重演（注释
                # 在案），DB 实锤全库 labels 键存在率 0%（宽体机功能
                # 空转根因）；其余为机场名/机型体量/舱位代码新键；
                # labels/planeSize 无值不落键（r241 残留族收口，
                # offer 层同门）
                **(({"labels": _lbo}
                    if (_lbo := str(o.get("labels") or "").strip())
                    else {})),
                **(({"planeSize": _pso}
                    if (_pso := str(o.get("planeSize") or "").strip())
                    else {})),
                "depAirport": str(o.get("depAirport") or "").strip(),
                "arrAirport": str(o.get("arrAirport") or "").strip(),
                # H1 透传（offer 层已守卫；「决策字段必须随
                # offer 透传」教训 / 两次在案）
                "depAirportCode": str(o.get("depAirportCode") or "").strip(),
                "arrAirportCode": str(o.get("arrAirportCode") or "").strip(),
                "cabinCode": str(o.get("cabinCode") or "").strip(),
            }
            # 童婴价透传（offer 层无值时键不存在，数值协议同 qunar）
            if isinstance(o.get("childPrice"), (int, float)):
                row["childPrice"] = o["childPrice"]
            if isinstance(o.get("infantPrice"), (int, float)):
                row["infantPrice"] = o["infantPrice"]
            # layover 透传（卫生同律）：航班级固定键曾对恒空
            # 源每行落 ""（detail.duration 键级消失 12 天 ~8 万行 0 非
            # 空）——有值才落，防恒空键堆 extra；渠道恢复在场自动回归。
            # layoverSrc 源标随 layover 同行透传（Soldier Major-2：
            # offer 层 transInfo 真值标丢失=flightnorm 假衔接豁免族
            # 对拼装行不可达，真值长停留落击杀区被误归零）
            if str(o.get("layover") or "").strip().isdigit():
                row["layover"] = int(o["layover"])
                if str(o.get("layoverSrc") or "").strip():
                    row["layoverSrc"] = str(o["layoverSrc"]).strip()
            out.append(row)
        return out

    def _dump_raw(self, raw: Optional[dict], tag: str):
        if not self.debug or not raw:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        path = os.path.join(self.debug_dir, tag + ".json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            self.logger.info("[tuniu] 已保存原始响应: %s", path)
        except Exception:
            pass
