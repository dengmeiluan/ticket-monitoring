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
import shutil
import tempfile
import re
import json
import time
import urllib.parse
from collections import Counter
from datetime import date, datetime
from typing import List, Optional

import httpx

from core.models import PRICE_MAX, PRICE_MIN, FlightPrice, price_band_ok
from core.citydata import CODE_NAME as _CODE_NAME
from core.intl import (airport_city_code, city_name_of, city_short_of,
                       is_intl_route)
from .base import BaseCrawler, iata2, iata3
from .challenge import ChallengeSignal, blocked_signal, classify_text, login_signal

_LOG = logging.getLogger(__name__)

# 廉航二字码：中转基本需重新值机（与 core.flightnorm.AIRLINE_LCC 同口径）
_LCC_CODES = {"9C", "KN", "AQ", "GX", "DZ", "EU", "8L", "PN", "QW",
              "G5", "BK", "KY"}


def _is_timeout_failure(exc) -> bool:
    """请求/加载超时判定（含 http 库与 Playwright 的 Timeout 族）。

    超时是基础设施失败，不是「服务端按未登录处理」的证据——不得据此
    置 login_suspect。类型名覆盖 httpx.ConnectTimeout/ReadTimeout 与
    playwright TimeoutError（均非内建 TimeoutError 子类）。"""
    return isinstance(exc, TimeoutError) \
        or "timeout" in type(exc).__name__.lower()


def _odd_code_shapes(rows) -> list:
    """非标准航班号形态观测哨（dbobs W1）：渠道经停伪码族
    （G581O1J/G583F6C，源报文 binfo.airCode 同串）每轮在产——渠道
    本态不拦截，DEBUG 留痕供渠道改版形态切换发现；中转合串码逐段
    验，全真码段不扰。"""
    odd = []
    for f in rows or []:
        code = str(f.get("code") or "")
        for seg in code.split("/"):
            if seg and not re.fullmatch(r"[A-Z0-9]{2}\d{3,4}", seg):
                odd.append(code)
                break
    return odd


def _span_days(d1: str, d2: str) -> int:
    """depDate→arrDate 跨度天数（解析失败按 0——守卫从宽不误伤）。"""
    try:
        return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
    except (TypeError, ValueError):
        return 0


def _layover_pinned(b1, b2):
    """跨日中转停留的日期钉计算（分钟），钉不住返回 None。

    停留=二段起飞日(binfo2.date/depDate)相对首段到达日(binfo1.arrDate)
    的天数差×1440+二段起飞钟面−首段到达钟面。旧 (d2−a1)%1440 在真停
    ≥24h 时钟面差落 [0,1440) 不触发回绕修正——SC4926 真停 24:05 被
    落成 0:05（ctrip 同指纹 1445 互证），LAY_MIN 衔接筛选按 5 分钟
    保守误剔隔夜中转候选（r273 观测切片②实锤）。渠道分段级 date 键
    是结构化真值（PC dump 中转行 23/23 在场），语义逐行验证
    （b1.arrDate ≤ b2.date ≤ b2.arrDate）；验证不过/键缺/解析败/
    结果 ≤0 返回 None，调用方退回旧 %1440 形态（<24h 停留两法数学
    等价）。"""
    def _hm(s):
        try:
            h, m = str(s).strip().split(":")
            return int(h) * 60 + int(m)
        except (ValueError, TypeError):
            return None

    def _d(s):
        try:
            return date.fromisoformat(str(s).strip()[:10])
        except (TypeError, ValueError):
            return None

    a1 = _hm((b1.get("arrTime") or ""))
    d2 = _hm((b2.get("depTime") or ""))
    a1d = _d(b1.get("arrDate") or "")
    d2d = _d(b2.get("date") or b2.get("depDate") or "")
    a2d = _d(b2.get("arrDate") or "")
    if a1 is None or d2 is None or a1d is None or d2d is None \
            or a2d is None or not (a1d <= d2d <= a2d):
        return None
    lay = (d2d - a1d).days * 1440 + (d2 - a1)
    return lay if 0 < lay <= 3 * 1440 else None


def _meal_from_addons(add) -> tuple:
    """H5 flightAddInfoIntegration.flightAdditionInfos[] → (餐食, 托运)文本。

    实测 name 全集（9/25 报文 75 行 + 2027 春节档 4 dump 221 行）：
    正餐/有餐/有餐食/无餐食/点心/点心餐/早餐/小食 + 非餐项（免费托运
    20KG/廊桥登机率--/起飞准点率--/平均延误--/WiFi未知...），餐食按含
    「餐/点心/小食」词识别（「小食」系吉祥 HO 小食班次行内唯一餐食词，
    值域全量普查含「小食」子串的词仅其本身，补词零误采面），托运顺带
    按含「托运」识别，
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
        if not meal and ("餐" in nm or "点心" in nm or "小食" in nm):
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
    直挂——按不满足处理（用户实锤）。lcc 双参照系（r336 Soldier m4
    随迁）：渠道廉航标注（intl filter join 落 f["lcc"]）与静态二字码
    同语义同门——intl 行暂无标签载体（惰性），随载体回场自动生效。"""
    from core.flightnorm import _is_lcc
    if _is_lcc(f.get("code") or "") or _is_lcc(f.get("name") or "") \
            or f.get("lcc"):
        return ""
    sv = ((f.get("transitServiceLabel") or "")
          + (f.get("transitServiceLabelName") or ""))
    return "direct" if ("行李免提" in sv or "免费托运" in sv) else ""


def _pos_num_s(v):
    """宽容正数判定：int/float/数字字符串均可（R38 国际真报文
    taxPrice="402" 字符串形态实证；与国内 _pos_num 只认 int/float
    不同——国际渠道值全为字符串）。"""
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


class QunarCrawler(BaseCrawler):
    name = "qunar"
    use_mobile = True

    # 去哪儿单程列表 H5（用户提供的真实入口）
    URL_TPL = (
        "https://m.flight.qunar.com/ncs/page/flightlist"
        "?depCity={from_name}&arrCity={to_name}"
        "&goDate={date}&from=touch_index_search"
        "&child=0&baby=0&cabinType=0"
    )
    # PC 版单程列表（2026-10-10 起已停服，仅保留显式复活探测）：
    # H5 接口 touchInnerList 曾风控升级，PC 页 + wbdflightlist 曾为主
    # 路径；停服后由 _fetch_one 的 PC_PROBE_ON_MISS 开关控制，默认不走。
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
    # 2026-10-10 PC 站停服：H5 未命中时默认不再等 PC 复活
    # （3 采样×等待≈72s/日期）；保留代码供人工显式置 True 做一次性复核。
    PC_PROBE_ON_MISS = False

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

    # 全国城市超集（r320 全量城市化）：官方字典投影补齐。旧键值保留
    # （DIG=香格里拉/SWA=汕头 旅游名语义不漂移，存量推送词面不变）
    for _c, _n in _CODE_NAME.items():
        if _c not in CITY_NAME:
            CITY_NAME[_c] = _n

    # 去哪儿单程列表真实数据接口
    API_URL = "https://touch.qunar.com/flight/api/touchInnerList"

    # 风控占位响应特征
    RISK_CODE = 1999
    # token 有效期（保守取 20h，实际约 24h）
    TOKEN_TTL_S = 20 * 3600

    # 2026-10-10 起 PC /site/ 只留停服通知与 App 下载入口，统一登录页
    # 仍提供手机号验证码/扫码（2026-10-22 实测），Cookie 落 .qunar.com
    # 主域，与 H5 列表/明细取数共用。
    LOGIN_URL = "https://user.qunar.com/passport/login.jsp"
    # H5 机票首页：停服后的用户入口（自动取数仍走 URL_TPL 列表页）。
    H5_HOME = "https://touch.qunar.com/h5/flight/"

    def login_url(self) -> str:
        return self.LOGIN_URL

    # ==================== 主流程 ====================
    # 阶梯式限流自锁（替代固定 310s 预防等待——实测一轮 11 分钟里
    # 9.8 分钟在等）：平时只保礼貌间隔；空数据疑似限流才退避，
    # 冷却期类级共享（多查询间生效），拿到数据即重置
    _MIN_GAP_S = 8                 # 相邻查询礼貌间隔（登录态实测零限流，20→12→8；失败有阶梯退避兜底）
    _BACKOFF_S = (90, 180, 300)    # 疑似限流的阶梯退避
    _last_done_ts = 0.0
    _cooldown_until = 0.0

    @staticmethod
    def fetch_low_price_calendar(dep_name: str, arr_name: str,
                                 start_date: str, end_date: str,
                                 logger=None, timeout: float = 35.0,
                                 proxy: str = "",
                                 profile_root: str = "user_data"):
        """去哪儿官方 H5 低价日历（特价页官方深链，零登录）。

        页面 JS 自行生成 bella/june 签名；本函数只加载官方页面并读取
        getFlightCalendar 的真实响应，不逆向签名、不绕过验证码/风控。
        成功返回响应 dict；观测到页面风控证据返回 None（调用方进入长
        冷却）；加载超时/浏览器不可用则抛 TimeoutError/RuntimeError，
        由调用方按失败如实上报，不冒充风控冷却。"""
        from urllib.parse import quote
        log = logger or _LOG
        prof = tempfile.mkdtemp(prefix="qn_radar_")
        # 使用已保存的去哪儿会话（仅复制 Cookie/Preferences/Local State，
        # 不复制缓存与历史）；无会话时仍走官方页面匿名路径。
        src = os.path.join(profile_root, "qunar")
        if os.path.isdir(src):
            for rel in ("Default/Network/Cookies", "Default/Preferences",
                        "Local State"):
                sp = os.path.join(src, rel)
                if not os.path.isfile(sp):
                    continue
                dp = os.path.join(prof, rel)
                try:
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    shutil.copy2(sp, dp)
                except OSError as e:
                    log.warning("[特价·qunar] 会话文件复制失败 %s: %s",
                                rel, e)
        url = ("https://touch.qunar.com/lowFlight/flightList"
               "?dep=" + quote(dep_name) + "&arr=" + quote(arr_name) +
               "&flightType=1&startDate=" + start_date +
               "&endDate=" + end_date +
               "&tag=-1&days=-1&tagNames="
               "&cat=touchjpgg_lowFlight-cheap-ticket_urban_flow_research"
               "&hybridid=flight_tejia&bizSource=SUPER_LOW")
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            log.warning("[特价·qunar] Playwright 不可用: %s", e)
            shutil.rmtree(prof, ignore_errors=True)
            raise RuntimeError("去哪儿低价页 Playwright 不可用: %s" % e)
        obj = {}
        load_errors = []
        try:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    prof, headless=True,
                    viewport={"width": 390, "height": 844},
                    user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 "
                                "like Mac OS X) AppleWebKit/605.1.15 "
                                "(KHTML, like Gecko) Version/17.0 "
                                "Mobile/15E148 Safari/604.1"),
                    locale="zh-CN", timezone_id="Asia/Shanghai",
                    is_mobile=True, has_touch=True,
                    proxy={"server": proxy} if proxy else None)
                page = ctx.new_page()

                def _on_resp(r):
                    if "getFlightCalendar" not in r.url:
                        return
                    obj["resp_seen"] = True
                    try:
                        j = r.json()
                    except Exception:
                        return
                    if not isinstance(j, dict):
                        return
                    st = j.get("bstatus")
                    bcode = st.get("code") if isinstance(st, dict) else st
                    # 页面侧风控/人机码（10003 通用风控、1999/2008 登录、
                    # 10004 点选、code 7/8/9 同族）——只识别不绕过。
                    if bcode in (1999, 2008, 10003, 10004) \
                            or j.get("code") in (7, 8, 9):
                        obj["risk"] = str(bcode or j.get("code"))
                    ok = (st == 0 or bcode == 0)
                    lp = j.get("lowPriceList") or (
                        (j.get("data") or {}).get("lowPriceList")
                        if isinstance(j.get("data"), dict) else None)
                    if ok and isinstance(lp, list):
                        obj["data"] = {"lowPriceList": lp,
                                       "bstatus": 0}
                page.on("response", _on_resp)
                # 总预算以调用方 timeout 为上限；每次尝试另给独立窗口，
                # 避免首个 deadline 耗尽后第二次尝试立即空转。
                total = max(8.0, float(timeout))
                overall_deadline = time.time() + total
                for attempt in range(2):
                    remaining = overall_deadline - time.time()
                    if remaining <= 0:
                        break
                    attempt_deadline = min(
                        overall_deadline,
                        time.time() + max(4.0, min(remaining, total / 2.0)))
                    try:
                        page.goto(
                            url, wait_until="domcontentloaded",
                            timeout=max(1000, int(min(remaining, total)
                                                  * 1000)))
                    except Exception as e:
                        load_errors.append(str(e)[:120])
                        log.warning("[特价·qunar] 页面加载失败(第%d次): %s",
                                    attempt + 1, str(e)[:120])
                    while time.time() < attempt_deadline \
                            and not obj.get("data"):
                        page.wait_for_timeout(500)
                    if obj.get("data"):
                        break
                    # 10003 为页面侧通用风控失败，按页面正常重试一次
                    url += ("&_r=" + str(int(time.time())))
                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception as e:
            log.warning("[特价·qunar] 低价页异常: %s", str(e)[:160])
            shutil.rmtree(prof, ignore_errors=True)
            raise RuntimeError("去哪儿低价页加载失败: %s" % str(e)[:160])
        finally:
            shutil.rmtree(prof, ignore_errors=True)
        if obj.get("data"):
            return obj["data"]
        if obj.get("risk"):
            log.warning("[特价·qunar] 页面风控证据 %s，按风控进入冷却",
                        obj["risk"])
            return None
        if obj.get("resp_seen") and not load_errors:
            # 页面已正常响应日历接口但无有效行：原站真实空档，非风控。
            return {"bstatus": 0, "lowPriceList": []}
        raise TimeoutError("去哪儿低价页加载超时或无响应")

    def fetch(self, from_city: str, to_city: str, dates: List[str],
              ret_date: str = "") -> List[FlightPrice]:
        import time as _t
        self.path_reset()
        self._last_challenge = None
        self._query_challenge = None
        self._last_no_result = False
        self._last_failure_status = ""
        # 往返诚实（§5/§10）：qunar 未实现回程查询，忽略 ret_date 返回
        # 单程价会被告警/走势当成往返总价。不发单程查询，unsupported 落账。
        if ret_date:
            self.logger.warning(
                "[qunar] 往返明细暂不支持（返程 %s），未发起单程查询",
                ret_date)
            self.path_note(
                "TRIP", "unsupported",
                detail="往返明细暂不支持，未发起单程查询")
            return []
        for attempt in range(len(self._BACKOFF_S) + 1):
            wait = max(QunarCrawler._cooldown_until - _t.time(),
                       self._MIN_GAP_S - (_t.time() - QunarCrawler._last_done_ts))
            if wait > 0:
                self.logger.info("[qunar] 错峰等待 %ds", int(wait))
                _t.sleep(wait)
            fail_status = ""
            try:
                res = self._fetch_inner(from_city, to_city, dates)
                fail_status = getattr(self, "_last_failure_status", "") or ""
            except Exception as e:
                self.logger.warning("[qunar] 抓取异常: %s", e)
                res = []
                fail_status = ("timeout" if _is_timeout_failure(e)
                               else "error")
                for _d in dates:
                    self.path_note(
                        "QUERY", fail_status, date=_d,
                        detail="%s: %s" % (type(e).__name__, str(e)[:120]))
            self._last_failure_status = ""
            QunarCrawler._last_done_ts = _t.time()
            if res:
                QunarCrawler._cooldown_until = 0.0
                self._last_no_result = False
                # 服务端重新承认会话：清失效证据，登录态卡片退回「已有
                # 登录态」。复位判据与 webui cal 行判定同构（flight_no/
                # depart_time 至少一者在场=明细行）：日历价查询不需要
                # 登录（渠道侧「低价日历仍出价」在案），纯日历行出数不
                # 证会话有效——旧「任何出数即复位」被日历价反复清洗
                # 失效证据，UI 卡片在明细会话已死时仍显示「已有登录态」
                # （r338 用户实报）
                # 元素是 FlightPrice dataclass 非 dict（.get 形态对
                # dataclass AttributeError——qunar 出数轮整渠道炸，
                # r290 钉在 CI 抓获的形态）：按属性取
                if any(getattr(r, "flight_no", "") or getattr(r, "depart_time", "")
                       for r in res):
                    QunarCrawler.login_suspect = False
                return res
            _ch = (getattr(self, "_query_challenge", None)
                   or getattr(self, "_last_challenge", None))
            if _ch and _ch.status == "blocked":
                # 人机/访问验证不是会话失效，也不该按限流退避连打。
                self.logger.warning(
                    "[qunar] %s 在案，跳过退避重试", _ch.detail)
                return []
            if getattr(self, "_last_no_result", False) and not fail_status:
                # 原站明确返回“没有符合条件的航班”：不是登录失效，也不是
                # 网络失败；不置 login_suspect、不进入限流退避链。
                self.logger.warning(
                    "[qunar] 原站明确返回无符合条件的航班"
                    "（1999/no-result）——按空结果记录，不冒充会话失效")
                return []
            if fail_status:
                # 超时/网络/异常是基础设施失败，不冒充「会话失效」，
                # 也不进入空结果的限流退避链（路径账已按 timeout/error
                # 逐日落账，UI 不再显示为 empty）。
                self.logger.warning(
                    "[qunar] 本轮按 %s 记录（非会话失效证据），"
                    "不置 login_suspect、不进入空结果退避链", fail_status)
                return []
            if attempt >= len(self._BACKOFF_S):
                self.logger.warning("[qunar] 阶梯重试耗尽（%d 次），本轮放弃",
                                    attempt)
                return []
            if QunarCrawler.login_suspect:
                # 会话失效证据在案（软性空列表+本地档案在，r290 产生点
                # 捕获）——确定性拒绝不走全档退避（r339c 观测：退避链
                # 570s+4 轮抓取≈17min 必触 900s 路由栅栏，单渠道超时
                # 连锁是长链主因；登录态不会在退避窗内自愈，重试注定
                # 同果，NOT_SUPPORT 同族律）。下轮调度自然重试，出数即
                # 复位（上方 328 行）；不设冷却防顺带压制他线查询
                self.logger.warning(
                    "[qunar] 会话失效证据在案，跳过退避重试"
                    "（请在配置页「渠道登录」重新登录 qunar）")
                return []
            back = self._BACKOFF_S[attempt]
            self.logger.warning("[qunar] 三路径空结果——qunar 已于 09-12 起对"
                                "未登录会话软性返回空列表（低价日历仍出价）；"
                                "请在配置页「渠道登录」重新登录 qunar。先按限流重试 %ds（第 %d 次）",
                                back, attempt + 1)
            # 服务端按未登录处理的证据（产生点捕获）：登录态卡片分层
            # 「会话可能失效，建议重登」的数据源——本地档案在而会话死
            QunarCrawler.login_suspect = True
            QunarCrawler._cooldown_until = _t.time() + back
        return []

    def _fetch_inner(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        # 国际分流（r325）：core.intl 自动判定，错峰/退避外壳与国内共用
        if is_intl_route(from_city, to_city):
            return self._fetch_intl(from_city, to_city, dates)
        self._last_failure_status = ""
        results: List[FlightPrice] = []
        for date in dates:
            got = None
            try:
                got = self._fetch_one(from_city, to_city, date)
            except Exception as e:
                _fail = ("timeout" if _is_timeout_failure(e) else "error")
                self._last_failure_status = _fail
                self.path_note(
                    "H5", _fail, date=date,
                    detail="%s: %s" % (type(e).__name__, str(e)[:120]))
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
                    flight_no=(best or {}).get("code", ""),
                    depart_time=(best or {}).get("depTime", ""),
                    arrive_time=(best or {}).get("arrTime", ""),
                    extra=json.dumps(flights, ensure_ascii=False) if flights else "",
                ))
                n_direct = sum(1 for f in flights if not f.get("transCity"))
                for _oc in _odd_code_shapes(flights):
                    self.logger.debug(
                        "[qunar] 非标准航班号形态 %s（经停伪码/渠道本态"
                        "观测哨，改版形态切换时升级排查）", _oc)
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
        """单日期抓取：H5 浏览器优先（2026-10 起 PC 断供）；
        PC 复活探测默认关闭，最后 httpx token 直连；真截断/风控整单拒落价。"""
        # 2026-10-10 起 PC 列表页 302 回 www.qunar.com 促销聚合，
        # wbdflightlist 断供；H5 列表页（m.flight）仍出全量明细。
        # H5 先行；匿名/失效会话 H5 空结果时不再把每日期 ~72s 耗在
        # PC 死入口上，直接走 token 直连。PC 探测保留为显式开关。
        self._last_challenge = None
        got = self._fetch_via_browser(from_city, to_city, date)
        _sig = getattr(self, "_last_challenge", None)
        _h5_status = ("ok" if got else (_sig.status if _sig else
                       ("login" if QunarCrawler.login_suspect else "empty")))
        self.path_note(
            "H5", _h5_status,
            rows=len(got[1]) if got else 0, date=date,
            detail=(_sig.detail if _sig else
                    ("原站返回无符合条件的航班（可能受指纹 SDK/风控环境影响）"
                     if getattr(self, "_last_no_result", False)
                     else "touch.qunar.com H5 列表")))
        if got is not None:
            self.logger.info("[qunar] H5 浏览器命中（完整明细）")
            return got
        if _sig and _sig.status == "blocked":
            # 人机验证：停手，不再换路径连打（重试只会加深风控）。
            self._query_challenge = _sig
            return None
        if _sig:
            # 登录墙：保留 H5 login 证据，但仍允许 httpx token 路径取数；
            # token 有效时不能因为 H5 登录页丢掉真实明细。
            self._query_challenge = _sig
        if self.PC_PROBE_ON_MISS:
            self.logger.info("[qunar] H5 未命中，探测 PC 是否复活")
            got = self._fetch_via_pc(from_city, to_city, date)
            self.path_note("PC", "ok" if got else "empty",
                           rows=len(got[1]) if got else 0, date=date,
                           detail="PC 复活探测（默认停服）")
            if got is not None:
                return got
            self.logger.info("[qunar] PC 未命中，回退 httpx")
        else:
            self.logger.info("[qunar] H5 未命中，跳过已停服的 PC，回退 httpx")
        self._last_challenge = None
        got = self._fetch_via_httpx(from_city, to_city, date)
        _sig = getattr(self, "_last_challenge", None)
        _api_status = ("ok" if got else (_sig.status if _sig else
                        ("login" if QunarCrawler.login_suspect else "empty")))
        self.path_note(
            "API", _api_status,
            rows=len(got[1]) if got else 0, date=date,
            detail=(_sig.detail if _sig else
                    ("原站返回无符合条件的航班（可能受指纹 SDK/风控环境影响）"
                     if getattr(self, "_last_no_result", False)
                     else "touchInnerList token 直连")))
        if _sig:
            self._query_challenge = _sig
        return got

    # ==================== PC 版复活探测（默认关闭，wbdflightlist） ====================
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
                    # 接口级拒绝，等待与加采均无意义，立即短路回退 H5。
                    # PC 复活哨（r323 定性）：本路径曾整代停摆（10-08
                    # 起软拒连续 8 天，每次抓取仍先试本路径=复活探测
                    # 天然在跑，停软拒即自然回勤零需改码）——停摆期
                    # PC-only 键族（avgDelay/transferService/labelNote/
                    # distance/ptripNote/cabinCode 直飞）断供属渠道侧
                    # 供给收缩，勿按解析断链排查；avgDelay 归零定性先
                    # 过「守卫蕴含零 vs 断链零」口径关
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
            self.logger.info("[qunar] PC 软拒绝（空壳响应），交由调用方回退")
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
        直飞时长在 binfo.flightTime（"5h30m"）；顶层 transTime 语义=
        中转停留时长（非全程，全程由两段飞行+停留重建）；
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
            if not (PRICE_MIN <= price <= PRICE_MAX):
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
            # 中转停留（决策关键：停多久）权威=两段起降差带日期钉：
            # 真停 ≥24h 时 (d2−a1)%1440 钟面差落 [0,1440) 不触发回绕
            # 修正（SC4926 停 24:05 曾落 0:05 → LAY_MIN 保守误剔隔夜
            # 中转，ctrip 同指纹 1445 互证）——二段起飞日取分段级
            # binfo2.date 结构化真值（23/23 在场）钉天数百位；钉不住
            # 退 %1440 旧形态（<24h 两法数学等价），span≥2 天且差值
            # <5h 的回绕假值不取（~25h 真实停留会被回绕成 60min，
            # 宁缺勿错）。顶层 transTime 在 PC 报文的语义=停留时长
            # （生产 dump 45/45 行=b2.dep−b1.arr 精确相等，跨天含
            # 1440，「1天55分钟」即跨天停留；直飞行恒 int 0）
            stop_m = None
            if b2:
                stop_m = _layover_pinned(b1, b2)
                if stop_m is None:
                    def _hm(s):
                        try:
                            h, m = str(s).strip().split(":")
                            return int(h) * 60 + int(m)
                        except (ValueError, TypeError):
                            return None
                    a1 = _hm(b1.get("arrTime"))
                    d2 = _hm(b2.get("depTime"))
                    if a1 is not None and d2 is not None:
                        stop_m = (d2 - a1) % 1440
                        if _span_days(
                                (b1.get("date") or b1.get("depDate") or ""),
                                (b2.get("arrDate") or "")) >= 2 \
                                and stop_m < 300:
                            stop_m = None
            from core.flightnorm import dur_min as _dm, fmt_dur as _fd
            # 全程时长：中转=两段飞行+停留重建（停留>两段飞行和时，旧
            # 一级公式 t_m−f1−f2 曾把真停 9h 算成 3h05、停留词面落
            # totalDuration，衔接筛选/layoverT 展示全链受染）；任一
            # 组件缺失留空，normalize 按起止时刻重算兜底。直飞=transTime
            # 恒 int 0 不可用，flightTime 词面转换
            if b2:
                _f1 = _dm(b1.get("flightTime"))
                _f2 = _dm(b2.get("flightTime"))
                dur = _fd(_f1 + stop_m + _f2) \
                    if (_f1 and _f2 and stop_m) else ""
            else:
                ft = (b1.get("flightTime") or "").strip()
                # 直飞/经停词面归一走 dur_min→fmt_dur 单源：'5h' 整小时
                # 形旧 re.sub 不命中、英文词面透传入库（r244 窗内 340
                # item）；不可解析词面 _fd(_dm)='' 走无值不落（旧 re.sub
                # 对垃圾词面原样透传落库）
                dur = _fd(_dm(ft)) if ft else ""
            lay = stop_m if stop_m else ""
            # 二段起飞时刻（binfo2.depTime 49/49 真独立≠dep_t=
            # 整体起飞，非 H5 曾见的复制态）：H5 lay2dep 源
            # transInfo.secondDepInfo.time，PC 无 transInfo、真值在
            # binfo2.depTime 取法即得——PC 独占主路径期明细「二段 X
            # 起飞」展示位全渠道归零；H5 防复制态假值守卫同律
            # 照挂（≠整体起飞才落，防渠道复制态回潮）
            lay2dep = ""
            _b2dt = str(b2.get("depTime") or "").strip()
            if _b2dt and _b2dt != dep_t:
                lay2dep = _b2dt
            # PC 复活预案（10-04 PC 报文 72 行实证）：报文键
            # 一直在场而解析器未读——PC 软拒一旦解除，term/tterm/机场
            # 名/机型体量/退改不掉队。层级：直飞挂 binfo（b1 已兼容）、
            # 中转整体到达挂 binfo2（与 arrTime 取法同型）；
            # extparams 挂 flight 顶层（dict 形态，H5 是 JSON 串，双形态
            # 兼容取）
            dep_term = (b1.get("depTerminal") or "").strip()
            # b2 缺失的中转行 arrTerminal 退化为 b1（首段到达=中转楼）——
            # 与 arrTime 同源同取法（备案 m2：H5 侧同型错位已改
            # secondArrInfo 真值，PC 报文无 transInfo、软拒不跑主路径，
            # binfo2 缺失形态未见 dump 实证，复活时随 arrTime 一并核）
            arr_term = ((b2.get("arrTerminal") if b2
                         else b1.get("arrTerminal")) or "").strip()
            # 中转航站楼对齐 H5「咸阳T3」形态：PC arrAirport 带机场
            # 后缀（「咸阳机场」）须剥——H5 transInfo.airport 无后缀；
            # b1.arrTerminal 空串时退化纯机场名（「遥墙」）无换乘楼
            # 信息——不落（宁缺勿错）
            _t_arr = str(b1.get("arrAirport") or "").strip()
            _t_ter = str(b1.get("arrTerminal") or "").strip()
            trans_term = (
                (_t_arr[:-2] if _t_arr.endswith("机场") else _t_arr) + _t_ter
            ) if (b2 and _t_ter) else ""
            # 中转二段出发楼（binfo2.depTerminal 47/49 非空，
            # 8/49 真跨楼=咸阳 T3→T5/T5→T2 换乘实证）：H5 同键同律
            # 「与到达楼同楼无增量不落」（≠_t_ter 才落）；形态与
            # trans_term 同型=depAirport 剥「机场」+楼号「咸阳T5」
            trans_dep_term = ""
            _sdt_t = str(b2.get("depTerminal") or "").strip() if b2 else ""
            if _sdt_t and _sdt_t != _t_ter:
                _sda_t = str(b2.get("depAirport") or "").strip()
                trans_dep_term = (
                    (_sda_t[:-2] if _sda_t.endswith("机场") else _sda_t)
                    + _sdt_t)
            # 机场名（中文全名「虹桥机场」，72/72 在场）：同城多场
            # （虹桥 vs 浦东）决策信息，与 tuniu/tongcheng/ctrip 键名对齐
            dep_air = (b1.get("depAirport") or "").strip()
            arr_air = ((b2.get("arrAirport") if b2
                        else b1.get("arrAirport")) or "").strip()
            # 预案补遗（10-04 报文 72 行再核）：binfo1 层还有
            # depAirportCode/arrAirportCode（IATA「URC/SHA/PVG」72/72，
            # 五渠道唯一 qunar 码值源，H5 是中文）、distance（公里数，
            # 中转/经停行取两段段和=全程实际飞行公里，见提取处）、
            # meal 布尔 47/72（与 mealDesc 校验位）；复活时
            # 码值源可与 AIRPORT_NAME_CN 归一连用。
            # 复活轮首查项（10-04 PC 载荷 72 行定谳）：minbfPrice
            # 72/72 恒 0=恒值占位，勿落；旧注「与 minPrice 差
            # 1268~1506」系误挂——1268 实为响应级
            # data.min_flight.all.price（全航班最低价，SC8714/MU5578
            # 行），非行级差值。复活轮如再见到非零值，先核响应级
            # 同名键是否串层。
            # 观察哨（顶域恒值，r313 渠道调研三 dump 复验）：isInter
            # 恒 false——翻 true 即「国际线」语义事件，届时先核查询
            # 参数是否串域再议行级立项
            # H1：PC 侧码值预案搭车（键名 depAirportCode/
            # arrAirportCode 与 H5 出口天然对齐；H5 已用 depAirportId
            # 主源先行，PC 软拒期间此路零产出随复活预案生效）；iata3
            # 守卫同律
            dep_code = iata3(b1.get("depAirportCode"))
            arr_code = iata3((b2 if b2 else b1).get("arrAirportCode"))
            # 机型体量（planeFullType「波音737(中)」括号体量）：值域
            # 含「机型未定/其他机型/波音737MAX8/737-800」无体量形态
            # ——正则不命中不落（宁缺勿错）；值归一「大型机/中型机/
            # 小型机」与 fliggy/tuniu/tongcheng 同键同值域
            _pft = str(b1.get("planeFullType") or "")
            _pm = re.search(r"[（(]([大中小])[)）]", _pft)
            plane_size = (f"{_pm.group(1)}型机" if _pm else "")
            # 余票紧张/共享承运 PC 真键换源（fewTicketStr/
            # mainCarrierSimpleNameAndNo 是 H5 键名，PC 0 命中恒空转
            # —— 注释已自知；piaoShaoDesc「票少」7/47、
            # mainCarrier「FM9224」与 codeShare 22/22 同步）。
            # 自飞防呆（m4，对齐同程）：mainCarrier 与本班
            # airCode 完全同号=自飞挂自身 id 不落——同航司不同号
            # （FM9223 营销/FM9224 执飞）是真共享勿误杀
            few_t = ((f.get("fewTicketStr") or b1.get("fewTicketStr")
                      or b1.get("piaoShaoDesc") or "")).strip()
            # 观察哨（listLabel.nextPriceLabels，c330 渠道调研 8 dump
            # 词面配对）：现行内容=fewTicketStr 词面纯镜像（旧代 18/18
            # 精确同现同词面「票少」，新代双载体同撤 0/64）——词面已由
            # fewTicket 出口承载。翻身条件：nextPriceLabels 出现
            # fewTicketStr 未携带的新词面时，按 fewTicket/labels 出口
            # 复评（词面域层 grep，勿按键名孤儿判）
            # 观察哨（PC binfo.tof，r308 渠道调研 3 dump 值域 {70:206,
            # 0:4} 恒档、历史同）：疑准点率槽位——qunar 是全渠道唯一
            # 无 prate 源渠道，tof 值域分化（非 {70,0}）即准点率域
            # 首查项（addon「起飞准点率--」词面族 W-Q2 哨的 PC 侧翻身
            # 点）；布尔⇔词面校验位 piaoShao⇔piaoShaoDesc、meal⇔
            # mealDesc 双双全等零增量不采，值域漂移时一并复验。
            # r312 渠道调研分化面在案（b2 侧）：binfo2.tof 75 行值域
            # {70:60, 40:6, 0:9}，tof=40 跨 2 dump 复现（10-04 四行
            # MF8266/MU2533 等、10-06 两行二段同 HO1114）；b1 同窗仍恒
            # {70,0}。40 语义未证（准点率 40% 与内部指标两可、无词面
            # 互证、仅二段层）——维持不采；翻身条件=「起飞准点率--」
            # 词面族下发真值，或 tof 与任一可读词面并现，届时按既有
            # avgDelay/prate 出口键回归（读层换真值源调研先行）
            if not few_t:
                # 二段票少（binfo2.piaoShaoDesc，r256 dump 10-06 两例
                # CZ6646/MU5464、HU7859/FM9348：b1 缺席而 b2=「票少」
                # ——「买了第一段、买不到第二段」的直接购买风险，现行
                # 出口双空读者不可见）。词面=「二段」+渠道原词（紧张
                # 段位明示防误判首段）；b1 在场时上面已取到原词，整行
                # 紧张语义不被二段状态覆盖
                _b2f = str(b2.get("piaoShaoDesc") or "").strip()
                if _b2f:
                    few_t = "二段" + _b2f
            _mc = str(b1.get("mainCarrier") or "").strip()
            _ac = str(b1.get("airCode") or "").strip()
            share_c = ((b1.get("mainCarrierSimpleNameAndNo") or _mc).strip()
                       if (b1.get("codeShare") and _mc
                           and _mc != _ac) else "")
            # 共享承运航司名（mainCarrierShortName「南航」，与 codeShare
            # 行精确同步 23/73+20/66）：实际承运方决定服务/退改/里程累积，
            # 号「FM9224」只给班次、名才给承运方。与 shareCarrier 同门
            # （codeShare + mainCarrier≠airCode 自飞防呆）。
            # codeShareList 哨位升级（r321）：binfo1.codeShareList 恒
            # [0,0] 占位被打破（13/147 中转行 [0/1,0/1]，与 codeShare=1
            # 精确同现、元素数==段数=按段型）——但共享明细词面未随槽
            # 下发（10/13 行 mainCarrier 空），仅剩无词面「哪段共享」
            # 位置位，零读者增量不采；翻身条件=该槽随行下发实际承运
            # 名/号词面，届时按 shareCarrier 出口回归
            share_air = (str(b1.get("mainCarrierShortName") or "").strip()
                         if (b1.get("codeShare") and _mc
                             and _mc != _ac) else "")
            # 观察哨（r323 渠道调研）：flights[].shareFlights 恒 []（534
            # /534 全量）——翻非空=共享明细列表下发事件，与上行
            # codeShareList 哨同域联动（届时按 shareCarrier 出口评估）
            # 航程公里（binfo.distance「3649」串，73/73+66/66 全场）：
            # 中转绕行程度/燃油锚参考；int 协议无值不落键（同 avgDelay）。
            # 键语义=全程实际飞行公里：中转/经停行（binfo2 在场）两段
            # distance 48/48 全场在场，取段和；二段缺席时不落键——首段
            # 部分和冒充全程是错信息，宁缺勿错（prate=20 守卫同律）
            _dist = None
            _ds = str(b1.get("distance") or "").strip()
            if _ds:
                try:
                    _dist = int(_ds)
                except ValueError:
                    _dist = None
                if _dist is not None and _dist <= 0:
                    _dist = None
                if _dist is not None and b2:
                    _ds2 = str(b2.get("distance") or "").strip()
                    try:
                        _d2 = int(_ds2) if _ds2 else None
                    except ValueError:
                        _d2 = None
                    _dist = (_dist + _d2) if (_d2 and _d2 > 0) else None
            # 航司二字码（binfo.shortCarrier，全场在场）：机器可读航司键，
            # 与 tuniu airlineIataCode 跨渠道统一出口 airlineCode；
            # iata2 守卫不匹配落空串（str 协议同 depAirportCode）
            # 特惠产品权益（pTrip=true 才有 Note，dump 3/47 全同步；
            # 「航变免费改、20Kg免费行李」高价值稀疏字段）
            ptrip_note = (b1.get("pTripNote") or "").strip() \
                if b1.get("pTrip") is True else ""
            # 中转服务权益（transitServiceLabel 短文本本体，72 行
            # 中转行的 40% 在场 5 种值域）：现仅 _baggage_tag 在同键找
            # 「行李免提」子串落布尔，权益全文（免二次安检/免费餐食/隔夜
            # 免费住宿…）从未落——购买中转产品的核心决策信息。Name
            # （中转优享/专享服务）作前缀同落；Content 多 KB 法务全文
            # 不采。与 tongcheng/ctrip transferService 同键名同语义位
            _tsl = (f.get("transitServiceLabel") or "").strip()
            _tsn = (f.get("transitServiceLabelName") or "").strip()
            transfer_svc = QunarCrawler._svc_txt(_tsn, _tsl)
            # 退改/童婴价（extparams.refundChangeRule 内嵌 JSON 串
            # 47/47、childPrice/infantPrice）：与 H5 同协议，
            # 0 为未报价占位只收正数（_pos_num）、changeFee=-1 不可改
            # 如实透传
            _rcr = ""
            child_price = infant_price = None
            _ep = f.get("extparams")
            _epd = _ep if isinstance(_ep, dict) else None
            if _epd is None and isinstance(_ep, str) and _ep:
                try:
                    _epd = json.loads(_ep)
                except Exception:
                    _epd = None
            if isinstance(_epd, dict):
                child_price = _pos_num(_epd.get("childPrice"))
                infant_price = _pos_num(_epd.get("infantPrice"))
                _rcr = str(_epd.get("refundChangeRule") or "")
            refund_txt = ""
            if _rcr:
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
            # 中转二段出发日期（binfo1.transCityDepDate，调研 dump
            # 23/23 中转行在场）：跨天中转的「二段哪天起飞」决策辨识
            # 信息——lay2dep 只有 HH:MM 无日期，跨天班读不出二段日期。
            # PC 主路径该源断供（dump 全量 0 命中、调研期 23/23 在场）
            # ——兜底 binfo2.date（75/75 在场，语义=二段起飞日，
            # _layover_pinned 同键真源）；双源并存在场 b1 原序优先
            # （双容器并读律）。守卫：YYYY-MM-DD 形 + 晚于本行出发日
            # （早于=不合理、等于=无增量不落，同 transDepTerminal 纪律）
            # + 仅中转行，三件对兜底源同门生效
            _tgd = str(b1.get("transCityDepDate") or "").strip()
            if not _tgd:
                _tgd = str(b2.get("date") or "").strip()
            _d_dep = (b1.get("date") or b1.get("depDate") or date).strip()
            if (not tc or not re.match(r"^\d{4}-\d{2}-\d{2}$", _tgd)
                    or not re.match(r"^\d{4}-\d{2}-\d{2}$", _d_dep)
                    or _tgd <= _d_dep):
                _tgd = ""
            # 经停停留时长（raw 实证 "1小时5分"/"45分"）无值不落键：
            # 与 H5 段 `if stop_time:` 门同族——PC 段曾无条件落键，
            # 直飞行无经停概念恒空串，PC 复活首日 397 行空串平铺
            # （H5 轮直飞行零空串双证门在位）
            _stt = str(b1.get("stopTime") or "").strip()
            out.append({
                "price": price,
                "code": code,
                "name": (air + b1.get("airCode", "")) if air else code,
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": (b1.get("date") or b1.get("depDate") or date).strip(),
                "arrDate": ((b2.get("arrDate") if b2 else b1.get("arrDate"))
                            or "").strip(),
                # 「属性不适用即落空串」残留族无值不落键（r241 观测
                # 立案 8 键收口，H5 兜底路径同轮对齐；中转/有值照落）
                **({"transCity": tc} if tc else {}),
                # 跨天词双位补源（dbobs W2，H5 健康 dump 70 行中 3 行
                # 经停/共享族只在 binfo 层、值零分歧）：顶层缺席时回退
                # binfo——顶层有值优先（既有行为不变）
                **({"crossDayDesc": _cdd}
                   if (_cdd := (str(f.get("crossDayDesc") or "").strip()
                                or str(b1.get("crossDayDesc") or "").strip()))
                   else {}),
                # 全程时长（str 槽位无值不落，恒空键卫生律——r237 观测
                # 中转 8 条空串平铺收口，下同族四键）
                **({"totalDuration": dur} if dur else {}),
                # cabin 撤伪（H5 cabinDegree 同案）：binfo1.cabin 跨源
                # 与 cabinDegree 逐行全等 15/15=同一「段级折扣桶冒充
                # 行级舱位」伪语义出口，两字符 'R3' 漂移已在场——两侧
                # 同收不落；信息由 discountStr 承载，存量行由消费端
                # cabin_clean 守卫通吃
                **({"discount": (f.get("discountStr") or "").strip()}
                   if (f.get("discountStr") or "").strip() else {}),
                # 舱位码（S-Q2 预登记转正，PC 复活轮双 dump 复证直飞行
                # 62/62+36/36 在场）：仅直飞行收——中转段级 binfo1.cabin
                # 与 cabinDegree 逐行全等=r222 撤伪案（段级折扣桶冒充
                # 行级舱位，'R1' 数字漂移在场）维持不落；无值不落键。
                # 值域=标准订座单字符（B/E/H/J/K/L/M/P/T/W/Y 含 J 公务）
                # + 春秋自有子舱码 R2/R3/R4 三字符形态（双渠道同指纹
                # 100% 双证+价位带互锁 R4<R3<R2+tuniu 经济舱词面同现，
                # 全库 144 元素实证真值）——勿加「单字符」守卫误杀
                **({"cabinCode": _cab}
                   if (not b2 and (_cab := str(b1.get("cabin") or "")
                                   ).strip()) else {}),
                **({"layover": lay} if lay != "" else {}),
                # 与 H5 出口同位同序（空串不落值口径同邻键）：直飞行
                # 曾恒带空串落库（消费端 falsy 门兜住属门欠账），
                # 条件展开与 ctrip/tongcheng 同键缺席口径对齐
                **({"lay2dep": lay2dep} if lay2dep else {}),
                **({"transGoDate": _tgd} if _tgd else {}),
                # 停留来源标记：times=两段起降差重建（PC transTime 语义
                # 实为停留，本值为时刻级真值）——flightnorm 对该来源
                # 跳过 1440 回绕启发判伪（同 transInfo 豁免先例：真值
                # 恰会落进击杀区，真停 9h+全程 14h55 = 1435 实锤误杀）；
                # 无标记不落键（缺席与空串在消费端 .get() not in 语义
                # 下等价）
                **({"layoverSrc": "times"} if stop_m else {}),
                # 机型词面源换采（Q-1，r242 渠道调研立案）：PC 主路径
                # planeType 是机读码（'73P'/'738'/'32Q' 读者读不出，
                # 新代 DB 422 条目 100% 机读形态），planeFullType 是
                # 可读形态（'波音737(中)' 139/139 在场；裸机型
                # '737-800'/'波音737MAX8' 是干净真值照落，与 H5
                # binfo.name[1] fullmatch 锚定拒裸形不同域）；渠道垃圾
                # 占位词不落（宁缺勿错；黑名单外的未来值域漂移，键出勤
                # 哨测不出——归调研轮 plane 值域复检，r242 Soldier
                # 观察-2 备案）；机读码源随换源退役不回落（读者零增量），无值不落键
                # （r241 残留族同口径；消费端 flightnorm.cabin_text
                # .get 门 / alerter 跨渠道补全白名单既有通道零改动）
                **(({"plane": _pn} if (_pn := _pft.strip())
                    and _pn not in ("机型未定", "其他机型") else {})),
                # transferBaggage 无值不落键（_baggage_tag 空串=未标注，
                # normalize setdefault 兜底语义不变）
                **(({"transferBaggage": _tb} if (_tb := _baggage_tag(f))
                    else {})),
                # 经停决策字段（binfo1 已在手，提取即得）：经停城市/
                # 机场、餐食——raw 有而 extra 无会让用户无法判断
                # 经停航班「经停哪、停多久」。 挂起④阈值触发
                # （PC dump 3/144：中转二段经停陇南/庆阳真值挂 binfo2，
                # b1 恒空数组）取法「b1 值优先、b2 回退」（与 arrTime/
                # arrTerminal 同型）；join 后剥两端分隔符伪影（数组空串
                # 元素 join 出「;庆阳」形态，与 H5 渠道「,庆阳」同型）；
                # 无值不落键（r241 残留族收口）
                **(({"stopCitys": _sc} if (_sc := (
                    ";".join(b1.get("stopCitys") or []).strip(";")
                    or ";".join(b2.get("stopCitys") or [])
                ).strip(";")) else {})),
                # stopAirports 退役（载荷卫生 tam 先例）：全仓零消费孤儿键，
                # DB 近 7 天非空仅 3.7% 且全为单机场城市机场全名，与
                # stopCitys 同层同源零决策增量——行级删键，存量不动
                # 经停停留时长：「经停哪、停多久」的停多久数据源，
                # normalize 转时刻式；无值不落键（门在上文 _stt，
                # 与 H5 段同族）
                **({"stopTime": _stt} if _stt else {}),
                # meal 无值不落键（r311 同族残留收口：H5 路径 r242
                # 已收，PC 路径漏随；「无餐食」渠道显式词面是有值形态
                # 照落，空串只代表信息缺席）。
                # 观察哨（r311 渠道调研）：二段餐食 binfo2.mealDesc
                # PC 中转行 75/75 在场但与 binfo1 75/75 全等「无餐食」
                # =段级同值占位嫌疑，零增量不采；出现 binfo2≠binfo1
                # 的真分化样本即按「二段X」词面采（同「二段票少」律）
                **(({"meal": _pc_meal}
                    if (_pc_meal := (b1.get("mealDesc") or "").strip())
                    else {})),
                # 与 H5 对齐：余票标签/共享实际承运。注意
                # （PC dump 复核 + 换源落地）：
                # fewTicketStr/mainCarrierSimpleNameAndNo 是 H5 键名，
                # PC 真键 piaoShaoDesc/mainCarrier（10-04 报文 0 命中 vs
                # 真键全命中）——换源补齐，H5 键名留前兜底双形态兼容
                **({"fewTicket": few_t} if few_t else {}),
                **({"shareCarrier": share_c} if share_c else {}),
                # 共享承运航司名无值不落（直 233/中 254 空串平铺收口，
                # 观测「疑似新族」假火源之首；shareCarrier 同门已空串
                # 直落——留观：若下轮观测立 new 族同律收口）
                **({"shareAirline": share_air} if share_air else {}),
                "airlineCode": iata2(b1.get("shortCarrier")),
                # PC 复活预案新键（上面注释块：层级 + 命中率）；航站楼
                # 无值不落键（单航站楼侧恒空串，恒空键卫生律 tuniu 同族）
                **({"depTerminal": dep_term} if dep_term else {}),
                **({"arrTerminal": arr_term} if arr_term else {}),
                # 中转航站楼对无值不落键（同族恒空键卫生律，str 槽位
                # 空串=无值；有值照落不变）
                **({"transTerminal": trans_term} if trans_term else {}),
                # 与 H5 出口同位（换乘路径「T3 到 T5 出」配对键）
                **({"transDepTerminal": trans_dep_term}
                   if trans_dep_term else {}),
                "depAirport": dep_air,
                "arrAirport": arr_air,
                # H1 PC 预案搭车（str 空串口径同邻键）
                "depAirportCode": dep_code,
                "arrAirportCode": arr_code,
                # 机型体量无值不落键（r241 残留族收口，amt 同族）
                **({"planeSize": plane_size} if plane_size else {}),
                # 退改短 JSON/童婴价：无值不落键（数值协议同 H5）
                # 决策标签（PC priceLabel，72/72 在场 27/72 非空）：
                # name 即中文决策词，取前 3 防营销词串撑爆展示位；
                # 传 b1（binfo.transNotice「华夏联程」并入）；
                # 无值不落键（r241 残留族收口）。观察哨（r338 登记
                # 新词面 churn）：「秋季旅游节」（3 行/210 PC）与
                # 「中转联程需知」（1 行）——跨代复现 ≥2 且定性为
                # 资格/权益（非季节活动营销）再按 labels 同律评估；
                # 纯活动词维持不采
                **(({"labels": _lb} if (_lb := QunarCrawler._labels_of(f, b1))
                    else {})),
            })
            if ptrip_note:
                # 特惠产品权益无值不落键（载荷卫生：旧平铺落键使
                # extra 恒挂空串 ptripNote，pTrip=true 从未命中）
                out[-1]["ptripNote"] = ptrip_note
            if refund_txt:
                out[-1]["refundChange"] = refund_txt
                # 退改费结构化双键（价位级决策字段）：_rj 在手边直取，
                # changeFee=-1「不可改」如实保留（与 refundChange 串
                # 同协议）；半在场键按「无值不落键」逐键判
                if "returnFee" in _rj:
                    out[-1]["returnFee"] = _rj["returnFee"]
                if "changeFee" in _rj:
                    out[-1]["changeFee"] = _rj["changeFee"]
            # 延误分钟（binfo/binfo1.lateTime 字符串 int，分段层
            # 92/92+51/51 在场；顶层恒缺——dump 实证，读顶层=0 命中）：
            # 与 tuniu/ctrip/tongcheng 的 avgDelay 同语义异源，统一落
            # avgDelay 出口键——webui 明细次行「延N分」通道现成，跨渠道
            # 第四源；值域以负为主兼有正值（实测 -37~+17，负=历史平均
            # 提前分钟）如实透传，
            # 渲染词面由消费端 _ad_txt 按符号分叉；取 b1（首段/直飞
            # 一体覆盖），不取 binfo2（二段延误≠全程口径）；
            # "0" 未报价占位与非数字不落（宁缺勿错）
            _lt = str(b1.get("lateTime") or "").strip()
            if _lt and _lt != "0":
                try:
                    out[-1]["avgDelay"] = int(_lt)
                except ValueError:
                    pass
            # 观察哨 W-Q2（r268 渠道调研）：H5 flightAdditionInfos 的
            # 「起飞准点率/平均延误/廊桥登机率」三代恒 "--"——qunar
            # 全渠道唯一 prate/avgDelay 中文词面载体，下发真值即按
            # 既有 avgDelay/prate 出口键回归（读层换真值源调研先行）。
            # 并档（r324 渠道调研 n=72）：同容器第四恒档词「WiFi未知」
            # ——下发「有WiFi/无WiFi/全航程WiFi」类真值（非「未知」
            # 档）即按机上网络便利域立项，meal/labels 渲染位现成
            if child_price is not None:
                out[-1]["childPrice"] = child_price
            if infant_price is not None:
                out[-1]["infantPrice"] = infant_price
            # PC-only 键断供备案（观测口径）：transferService 源
            # transitServiceLabel、labelNote 源 priceLabel.note 均为
            # PC 路径专属——PC 路径停摆期间这两键出勤归零属路径断供
            # 而非渠道撤标，PC 复活即自动恢复，勿据 H5 era 归零误判
            # 回归。PC 主路径当前健康出勤，两键随路径恢复回升属路径
            # 恢复亦非回归；H5 链路 labels 白名单继续在役作再断供兜底
            if transfer_svc:
                out[-1]["transferService"] = transfer_svc
            # 标签适用条件说明（priceLabel[].note，22 条/72 行
            # 中位 46 字）：labels 已采 name（「取消延误免费改」），note
            # 是该承诺的适用条件（退改保护语境）——随 labels 同源取首条
            # 非空、超 80 字截断（note 形态 str/数组双兼容）
            _ln = ""
            for _t in (f.get("priceLabel") or []):
                _nv = (_t or {}).get("note")
                if isinstance(_nv, list):
                    _nv = _nv[0] if _nv else ""
                _nv = str(_nv or "").strip()
                if _nv:
                    _ln = _nv[:80]
                    break
            if _ln:
                out[-1]["labelNote"] = _ln
            # 航程公里条件键（无值不落键，同 refundChange/avgDelay 族）
            if _dist:
                out[-1]["distance"] = _dist
        return out

    _LABEL_MAX = 3   # 决策标签上限
    # intl reducePriceDesc 白名单门（r329）：「已减¥N」全词正则 +
    # 「成都两场互通」全词——「已减¥N」≠「可再减¥N」（H5 r322 透明
    # 标记）同族不同词面；「两场互通」=到达场≠票面场的运营信息
    # （值机/接机决策）。变体/营销 churn 一律不采（宁缺勿错）
    _RE_REDUCE_DESC = re.compile(r"^已减¥\d+$")

    @staticmethod
    def _h5_labels_of(f, info=None):
        """H5 决策标签（调研④ dump 实证），与 PC priceLabel
        （_labels_of）同一 labels 键出口、同一「·」联接形态：
        - 双载体并读：listLabel 顶层与 bizVendorPrice.listLabel 两
          容器的 priceBottomLabels[] 按 text 显式白名单采（顶层在前
          =渠道原序优先，同词去重）——服务承诺词的载体分落两容器，
          「出票后2小时内错购退票」的载体行唯一载体在 bvp；
          id（reduceShowLabel）被「中转低价/中转高性价比」类营销词
          共用勿按 id；白名单只收服务承诺型文本（错购退票时效），
          营销 churn 词（205-241 次/份）不采；
        - transNotice 仅非默认值落：343/537 次是占位「转」无信息量，
          「华夏联程」类航司自营联程产品背书（稀疏）才是决策信息，
          与 transferBaggage 同类。
         层级修复：背书真值挂 binfo/binfo1 层（10-05 dump 实证
        「华夏联程」×2 仅在 binfo 层，顶层恒占位「转」——上线首日 DB
        仅白名单词命中、背书 0 采），info 优先、顶层降为兜底；占位排除
        补「停」（经停标记与 stopFlight 冗余，dump 3-4 次/份）。"""
        # 显式白名单（宁缺勿错）：渠道侧加变体词时静默不采好过误采营销词。
        # 并入「郑州机场中转权益」（第八批调研：5-9 次/份中转行，
        # 机场中转产品服务背书，与 transNotice「华夏联程」同类服务承诺型）
        # 全词表复核再并 4 词（服务承诺型，582 行 8 dump 仅 4 行
        # 稀疏在场）：宠物友好/弃餐赠里程/联程航班服务/春秋绿翼会员
        # 专享丨超惠飞（航司会员资格价，PC priceLabel 同词面在册；
        # H5 全词精确匹配零误杀，勿用「会员专享」子串防带价 churn
        # 词误入）——不可自算、影响购买资格/权益；营销 churn（比直飞
        # 省¥N/可再减¥N/当日达低价/精选低价/中转-耗时最短）
        # 维持不采。
        # 并入「免费上网」（r237 调研：服务承诺型权益，H5 1/478 行
        # 稀疏在场；同词面 PC priceLabel 通道原生在采——H5 兜底路径
        # 漏采即该权益在 H5 主路径期永久缺失，跨渠道词面不对称）
        # 并入「新会员专享」「体验价」（资格价词，全库 14 份完整 dump
        # 定谳：①同槽家族律——priceBottomLabels 已收春秋绿翼会员
        # 专享，跨渠道 ctrip「老客专享」同语义位已收，「新会员专享/
        # 体验价」=渠道新客会员资格价同族成员；②跨轮独立复现——
        # 「新会员专享」两轮双会话同航班同词面同价恒定，「体验价」
        # 生产代 52~59% 行级出勤；③资格价互证形态（同班双价行/五价
        # 背离）全库零在场=H5 载荷结构性不携带，不构成永久挂哨理由；
        # ④载体行恒为行内最低价，不采则读者把活动价当全民价、比价
        # 失真零承载；PC 侧「体验价」已由 _labels_of 原生在采，H5 不
        # 收即同渠道双路径不对称。全词精确匹配防变体（老会员/黑钻
        # 会员专享、新会员专享价、体验价·限时）与带价 churn 误入。）
        # 渠道本态备案（r308 渠道调研，勿按缺陷立案）：qunar 新代
        # （2027 春节档 dump）静默撤「体验价/票少」词面——旧代
        # 体验价 43-77/份、票少 3-19/份，新代 dump 双双归零，同批
        # 冻结 dump 过现行解析器回放=源 0→产物 0 全等，DB labels
        # 出勤骤降与之同源；「郑州机场中转权益」新代仍 1-2 行/份
        # 在场证明白名单通道活着。词面恢复即自然复采；白名单长程
        # 零出勤哨（廿四§19）继续有效。
        _WHITELIST = ("出票后2小时内错购退票", "郑州机场中转权益",
                      "宠物友好", "弃餐赠里程", "联程航班服务",
                      "春秋绿翼会员专享丨超惠飞", "免费上网",
                      "新会员专享", "体验价")
        words = []
        # 双载体并读：服务承诺词的载体分顶层 listLabel 与
        # bizVendorPrice.listLabel 两容器（同 schema 家族槽，新代
        # dump 实证「出票后2小时内错购退票」的载体行唯一载体在 bvp
        # ——顶层同槽只有营销词）；顶层在前=渠道原序优先，白名单
        # 与去重门对两容器同门生效（同词双载体并现=纯镜像成员）。
        _bvp = f.get("bizVendorPrice")
        _bvp_ll = _bvp.get("listLabel") if isinstance(_bvp, dict) else None
        arr = []
        for _ll in (f.get("listLabel"), _bvp_ll):
            if isinstance(_ll, dict):
                arr.extend(_ll.get("priceBottomLabels") or [])
        # 年龄限制硬性购买资格置顶收（第八批 dump 实证 10/287 行：
        # 「限55岁(含)以上的旅客购买」「限3-9人·且需55周岁(含)以上旅客
        # 购买」「限16-23(含)周岁的旅客预定」——老年票/青年票买错无法
        # 值机）。正则收窄到人群限定形态（裸 ^限\d
        # 会放进「限2件/限N张」类规则/营销词），整句透传渠道原词零解析
        # 歧义；置顶防下方 [:2] 截断挤掉
        for t in arr or []:
            txt = str((t or {}).get("text") or "").strip()
            if re.match(r"^限\d+(?:[-~]\d+)?(?:[(（]含[)）])?(?:岁|人|周岁)",
                        txt) and txt not in words:
                words.append(txt)
                break
        for t in arr or []:
            txt = str((t or {}).get("text") or "").strip()
            # 「可再减¥N」透明标记（r322）：reduceShowLabel 实锤形态
            # 数值自洽（2204=2350−146 双通道复现，45/45 镜像行不发此
            # 标签）+新代稀疏 1/442（旧定性 churn 的高频形态已变）+
            # 页面公开承诺词面。价格口径不动（packageCutPrice 数值
            # 不采，防达标判定价污染；可购性活体验证挂账）。正则臂
            # 精确形态防变体（起字/裸词/非¥计价）与营销族（比直飞省）
            if (txt in _WHITELIST or re.match(r"^可再减¥\d+$", txt)) \
                    and txt not in words:
                words.append(txt)
        notice = ""
        for _src in ((info or {}), f):
            _tn = str((_src or {}).get("transNotice") or "").strip()
            if _tn and _tn not in ("转", "停"):
                notice = _tn
                break
        if notice and notice not in words:
            words.append(notice)
        return "·".join(words[:2])

    @staticmethod
    def _labels_of(f, b1=None):
        """PC priceLabel 决策标签（[{id,name,note[]}]）：name 即中文
        决策词（取消延误免费改/宠物友好/免费上网/联程航班服务…），
        id 不稳定（667 同时对应「取消延误免费改」与「郑州机场中转
        权益」）必须以 name 为准；note 长文本不落库。H5 链路无此键
        （PC 专属）——PC 软拒绝期间此字段恒空转，勿误判解析损坏；
        PC 主路径恢复后随路径回勤，勿误判回归。
         并入 binfo.transNotice（「华夏联程」航司自营联程背书，
        4/144 稀疏且 3/4 行 priceLabel 为空=漏采即整行丢失）：b1 层主源
        顶层兜底、「转/停」占位排除、去重——与 H5 _h5_labels_of 同律；
        _LABEL_MAX 容量不足时不挤掉 priceLabel 现有名。"""
        names = []
        qualified = []
        arr = f.get("priceLabel")
        if isinstance(arr, list):
            for t in arr:
                n = str((t or {}).get("name") or "").strip()
                if not n:
                    continue
                # 资格词置顶：「限N周岁」「需实名认证」是购买资格门槛
                # （误购无法出行），按 name 顺序截前 3 时会被「体验价」
                # 等非资格词挤出槽位——资格词先收，其余词让位（「体验价」
                # 在 H5 白名单侧为资格价词、PC 侧 name 直采无资格待遇，
                # 两路径各按自身门型行事，置顶只认「周岁/实名认证」硬门槛）
                (qualified if ("周岁" in n or "实名认证" in n)
                 else names).append(n)
        names = qualified + names
        out, seen = [], set()
        for n in names:
            if n not in seen:
                out.append(n)
                seen.add(n)
            if len(out) >= QunarCrawler._LABEL_MAX:
                break
        names = out
        if len(names) < QunarCrawler._LABEL_MAX:
            for _src in ((b1 or {}), f):
                _tn = str((_src or {}).get("transNotice") or "").strip()
                if _tn and _tn not in ("转", "停") and _tn not in names:
                    names.append(_tn)
                    break
        return "·".join(names)

    @staticmethod
    def _merge_pc_samples(samples: list) -> list:
        """多份采样逐条目中位合并（纯函数）。

        wbdflightlist 的 minPrice 每请求重摇、响应内无任何可信度判别
        字段（priceLabel 与幻影价无关），统计中位是唯一降噪手段：
        3 份取中位，2 份取高（对幻影低价保守），单份原样（退化即现状）。
        其余字段取中位价所属样本；price 以外的 float 不动，
        一律附 samples 轨迹（单命中落单元素——「无轨迹」与「单采样
        退化」不可区分时，幻影尖刺行审计无从下手）。"""
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
            g["samples"] = prices
            out.append(g)
        return out

    # ==================== httpx 续航 ====================
    def _fetch_via_httpx(self, from_city: str, to_city: str,
                         date: str) -> Optional[tuple]:
        """用缓存 token 直接 httpx POST：分片还原出完整明细，
        返回 (行价, 明细列表)；token 缺失/风控/无明细拒落价时 None。"""
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
        headers["referer"] = "https://m.flight.qunar.com/ncs/page/flightlist"
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

        _sig = self._risk_signal(text)
        if _sig:
            self._last_challenge = _sig
            if _sig.status == "login":
                QunarCrawler.login_suspect = True
            self.logger.warning(
                "[qunar] httpx 命中%s，可能是限流或 token 过期",
                _sig.detail)
            return None

        flights = self._parse_response_flights(text)
        if not flights:
            # 碎片响应仅价格无明细：裸价曾直入阈值告警并污染去抖基准
            # （0.5x 幻觉价守卫依赖明细，此路径完全裸奔）——整单拒收走重试。
            # 起分片形态已可还原，此路只剩真截断/风控形态
            self.logger.warning("[qunar] httpx 响应无明细，拒落价防污染")
            return None
        # 行价=本渠道明细最低价（与浏览器路径同律）：顶层 minPrice 每请求
        # 重摇、且不再参与取价——散点与明细两套来源曾造出 1-2 倍内的
        # 幻影低价窗口（渠道指纹比 p50=0.978 低价侧漂移的源头之一）
        prices = sorted({f["price"] for f in flights if f.get("price")})
        self.logger.info("[qunar] httpx 明细价格列表: %s", prices)
        return float(min(prices)), flights

    @staticmethod
    def _no_result_text(text: str) -> bool:
        """Qunar overloads 1999: login walls AND “no matching flights”.

        The 200 + `bstatus 1999` + data null shape is not enough; only the
        message distinguishes them. Treat explicit “no flights” wording as
        an empty result, never as a login failure.
        """
        try:
            obj = json.loads(text)
        except Exception:
            return False
        if not isinstance(obj, dict):
            return False
        msgs = []
        b = obj.get("bstatus")
        if isinstance(b, dict):
            msgs.append(str(b.get("msg") or ""))
        msgs.append(str(obj.get("msg") or ""))
        s = " ".join(msgs).lower()
        return any(x in s for x in (
            "没有查询到", "未查询到", "无航班", "no flight", "no matching"))

    @staticmethod
    def _risk_signal(text: str) -> Optional[ChallengeSignal]:
        """Map Qunar's domestic/intl risk state machine to one signal.

        Domestic previously only recognized 1999; the same Judge codes
        7/8/9/10004 appear on domestic responses too. Recognizing them
        first keeps a challenge page from being recorded as empty.
        """
        try:
            obj = json.loads(text)
        except Exception:
            return classify_text(text)
        if not isinstance(obj, dict):
            return classify_text(text)
        if QunarCrawler._no_result_text(text):
            return None
        bstatus = (obj.get("bstatus") or {}).get("code")
        code = obj.get("code")
        if bstatus in (1999, 2008) or code == 8:
            return login_signal("1999/2008")
        if code == 7:
            return blocked_signal("slider", "code 7")
        if code == 9:
            return blocked_signal("refresh", "code 9")
        if bstatus == 10004:
            return blocked_signal("click", "bstatus 10004")
        if obj.get("ret") is False and obj.get("data") is None:
            # 软性空列表/风控壳：不是成功空结果，宁可标 blocked。
            return blocked_signal("waf", "ret=false/data=null")
        return classify_text(text)

    @staticmethod
    def _is_risk_text(text: str) -> bool:
        return QunarCrawler._risk_signal(text) is not None

    @staticmethod
    def _intl_risk_path(risk: str) -> tuple:
        """International risk string -> (path status, kind)."""
        return {
            "login": ("login", "login"),
            "slider": ("blocked", "slider"),
            "captcha": ("blocked", "click"),
            "refresh": ("blocked", "refresh"),
        }.get(str(risk or ""), ("empty", ""))

    @staticmethod
    def _intl_body_risk(text: str) -> str:
        """HTML/body-only challenge (no JSON envelope) -> intl risk token."""
        sig = classify_text(text)
        if not sig:
            return ""
        if sig.status == "login":
            return "login"
        return "slider" if sig.kind == "slider" else "captcha"

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
        self._last_challenge = None

        snap = {
            "headers": None, "body_template": None,
            "cookies": None, "response_texts": [],
        }

        with self.browser() as ctx:
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

            # 无明细时先认风控/登录证据，避免把验证页当空结果。
            if not flights:
                for t in snap["response_texts"]:
                    if self._no_result_text(t):
                        self._last_no_result = True
                        continue
                    _sig = self._risk_signal(t)
                    if _sig:
                        self._last_challenge = _sig
                        if _sig.status == "login":
                            QunarCrawler.login_suspect = True
                        break
                if getattr(self, "_last_challenge", None) is None:
                    try:
                        _body_text = page.inner_text("body")[:1200]
                    except Exception:
                        _body_text = ""
                    _sig = classify_text(
                        _body_text, url=str(getattr(page, "url", "")))
                    if _sig:
                        self._last_challenge = _sig
                        if _sig.status == "login":
                            QunarCrawler.login_suspect = True

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
            # 行价同源自证：行价禁取响应文本 minPrice 散点 min()，明细
            # 3/4 轮走 DOM 兜底（响应分片形态，10-04~06 实测 JSON 明细
            # 0 条）——散点与明细两套来源，散点里 DOM 未渲染的更低价
            # （09-25 实证散点 1288 vs DOM 明细最低 1298）会造出 1-2
            # 倍内的幻影低价窗口，0.5x 守卫拦不住。行价=本渠道
            # 明细最低价，行价与明细严格同源
            prices = [f["price"] for f in flights if f.get("price")]
            if prices:
                self.logger.info("[qunar] 浏览器提取价格列表: %s", sorted(set(prices)))
                return (float(min(prices)), flights)
        return None

    # ───── 国际支线（r325，调研 _scratch/intl/report_qunar.md）─────
    # 国际只有 H5 单腿（PC 面 2026-10 实测 302→404 断供）：touchInterList
    # 与国内 touchInnerList 同族（同 SPA/同 Bella/同 binfo 行结构），但
    # 未登录=1999 硬拒（国内是软性空列表）——生产 .qunar.com 主域登录
    # cookie 同域直接生效。风控状态机（Judge 源码实证）：业务 code
    # 7=滑块/8=跳登录/9=强刷、bstatus.code 10004=点选——只记录+退避，
    # 不绕过（宁缺勿错同律）
    INTL_URL_TPL = ("https://touch.qunar.com/ncs/page/interlist"
                    "?depCity={from_name}&arrCity={to_name}&goDate={date}"
                    "&from=touch_index_search")
    INTL_API_MARK = "touchInterList"

    def _intl_city_name(self, code: str) -> str:
        """国际航线 URL 城市名：国内字典 → 国际城市级短名（qunar 搜索
        参数是中文城市名，report §3 实证；机场全名形态未验证不用）
        → 裸码三级回退。"""
        c = str(code).upper()
        return self.CITY_NAME.get(c) or city_short_of(c) or code

    # r336 T1/T2：intl filter 字典面的行级 join 词表。白名单收口
    # 「宁缺勿错」：渠道未来新增同槽词（如「需落地签」）不自动透传，
    # 按同槽扩表并过词面安全集审（LESSONS 二十八§1 新字符过禁律）
    _INTL_VISA_WORDS = ("需过境签",)
    _INTL_LCC_WORD = "廉价航空"

    @classmethod
    def _intl_filter_tags(cls, data) -> tuple:
        """intl data.allFilters 字典面 → (码域签证表, 词面签证表, 廉航名集)。

        T1 过境签（filterId=transCitys，labels 命中白名单词的选项）：
        ①码域主通道——detailItemId 即城市码（TPE/LON 冻结件实证，
        [A-Z]{3} 形态门防 UI 项混入），行级链推导转点码直查；②词面
        兜底——title 剥国别括号后缀归一为城市名（「台北(中国)」→
        「台北」；半角括号实证、全角形态一并兼容），供渠道真值
        transCity 行全等查（该形态无段链可推码）。
        T2 廉航（filterId=carriers）：labels 含「廉价航空」的航司
        中文全名入集（与行 binfo.name[] 同词面域，r335 已证 36 档）。
        结构实证：allFilters[].filterId → details[].detailItems[]，
        选项名键 title（detailItemTitle 为调研报告词面的另一代形态，
        双态并读防键名漂移）。"""
        out_code: dict = {}
        out_city: dict = {}
        out_lcc: set = set()
        for det in (data or {}).get("allFilters") or []:
            if not isinstance(det, dict):
                continue
            fid = det.get("filterId")
            if fid not in ("transCitys", "carriers"):
                continue
            for d2 in det.get("details") or []:
                for di in (d2 or {}).get("detailItems") or []:
                    if not isinstance(di, dict):
                        continue
                    labels = [str(x).strip()
                              for x in (di.get("labels") or [])
                              if str(x).strip()]
                    if not labels:
                        continue
                    title = str(di.get("title")
                                or di.get("detailItemTitle")
                                or "").strip()
                    if not title:
                        continue
                    if fid == "carriers":
                        if cls._INTL_LCC_WORD in labels:
                            out_lcc.add(title)
                    else:
                        hits = [w for w in cls._INTL_VISA_WORDS
                                if w in labels]
                        if not hits:
                            continue
                        item_id = str(di.get("detailItemId")
                                      or "").strip().upper()
                        if re.fullmatch(r"[A-Z]{3}", item_id):
                            out_code[item_id] = hits[0]
                        city = re.sub(r"[（(][^（）()]*[）)]$",
                                      "", title).strip()
                        if city:
                            out_city[city] = hits[0]
        return out_code, out_city, out_lcc

    @classmethod
    def _parse_intl_response(cls, text: str) -> tuple:
        """touchInterList 响应文本 → (flights, risk)。

        解码三级同国内律：明文 JSON → data 串分片 _reassemble_h5_data
        （t1000 同款置换形态）→ 都失败返回无明细（外层存 dump 拒落价，
        宁缺勿错）。风控态原样上抛由 _fetch_intl 分档处置。"""
        try:
            outer = json.loads(text)
        except Exception:
            return [], ""
        if not isinstance(outer, dict):
            return [], ""
        if cls._no_result_text(text):
            return [], "empty"
        bcode = (outer.get("bstatus") or {}).get("code")
        code = outer.get("code")
        risk = ""
        if bcode in (1999, 2008) or code == 8:
            # 1999=未登录硬拒（调研实证）；2008=登录态判定另一形态
            # （校准 R8 生产 profile 实测 {"bstatus":{"code":2008}，
            # "code":8} 同现）——登录族一并分流
            risk = "login"
        elif code == 7:
            risk = "slider"
        elif code == 9:
            risk = "refresh"
        elif bcode == 10004:
            risk = "captcha"
        if risk:
            return [], risk
        data = outer.get("data")
        if isinstance(data, str):
            data = cls._reassemble_h5_data(data)
        if not isinstance(data, dict):
            return [], ""
        # 容器键两代形态并存：登录态真报文=flights（R40 census 60 行
        # 实测，生产 21:48/21:51 登录后两连败实锤），调研期预期=routes
        # ——flights 优先，routes 保兼容
        flights = cls._extract_intl_flights(
            data.get("flights") or data.get("routes"),
            filter_tags=cls._intl_filter_tags(data))
        # 改期比价曲线与国内 H5 同族接线（生产 19/19 dump 在场、消费
        # 端在产、出口键已有）：同国内律只挂当轮最低价行防 extra 膨胀；
        # 值域门按国际宽带单源（intl=True）
        tg = cls._parse_trend_go(data.get("trendPrice"), intl=True)
        if tg and flights:
            lo = min(flights, key=lambda f: f.get("price") or 9e9)
            lo["trendGo"] = tg
        return flights, ""

    @classmethod
    def _extract_intl_flights(cls, routes_raw, filter_tags=None) -> list:
        """国际 routes 行 → 统一明细 schema（r325）。

        行结构与国内 H5 flights[] 同族（binfo/binfo1/binfo2/transCity/
        minPrice 同键），国际特有价格三键（渲染层实证「税费¥」词面）：
        minPrice=含税 / nakedPrice=裸票价 / taxPrice=税费——price 恒取
        含税 minPrice（INTL_DESIGN §1.2 口径），nakedPrice/taxPrice 拆分
        透传。行键全清单待生产登录态首采 dump 定谳（report §7.3），
        解析全 .get 容错 + 无值不落键：渠道改版只会缺键不会炸。
        到达时刻取 binfo2 整体到达（中转行 report §4 实证），直飞行
        无 binfo2 回落 binfo。
        filter_tags=（码域签证表, 词面签证表, 廉航名集）三表
        （_intl_filter_tags 产出，r336 T1/T2）：中转城市命中签证表落
        labels 白名单词（硬性出行资格）——码域主通道=链推导转点的
        airport_city_code 归一码直查（行级展示名「台北桃园」与 filter
        归一名「台北」词面域失配曾 7 行零贴签，push 审校 P3）；词面
        兜底通道=渠道真值 transCity（无段链可推码）剥括号归一名全等。
        binfo.name[] 航司名命中廉航集落 lcc=True（normalize
        `if not f.get("lcc")` 门天然让位）。None=既有行为零变化。"""
        _visa_by_code, _visa_by_city, _lcc_names = \
            filter_tags or ({}, {}, set())
        out = []
        for f in routes_raw or []:
            if not isinstance(f, dict):
                continue
            try:
                price = float(f.get("minPrice") or 0)
            except (TypeError, ValueError):
                continue
            if not price_band_ok(price, el={"intl": 1}):
                continue
            # 国际 RT 真报文：code 可为列表（多段），需归一为 / 连接串
            code_val = f.get("code")
            if isinstance(code_val, list):
                code = "/".join(str(x).split("|")[0] for x in code_val if x)
            else:
                code = str(code_val or "").strip()
            if not code:
                continue
            info = f.get("binfo") or f.get("binfo1") or {}
            b2 = f.get("binfo2") or {}
            dep_t = (info.get("depTime") or "").strip()
            dep_d = (info.get("depDate") or "").strip()
            arr_t = str((b2.get("arrTime") if isinstance(b2, dict) else "")
                        or info.get("arrTime") or "").strip()
            arr_d = str((b2.get("arrDate") if isinstance(b2, dict) else "")
                        or info.get("arrDate") or "").strip()
            if not (dep_t and arr_t and dep_d and arr_d):
                continue
            mix_raw = (f.get("mixFlightName") or "").splitlines()
            # 展示名三级链：mixFlightName（国内同族）→ binfo.name 航司
            # 中文名列表（R40 census 60/60，去重 / 连接）→ code 裸串
            _bn = info.get("name") if isinstance(info, dict) else None
            _names: list = []
            if isinstance(_bn, list):
                for _n in _bn:
                    _s = str(_n).strip()
                    if _s and _s not in _names:
                        _names.append(_s)
            if mix_raw and mix_raw[0].strip():
                name = mix_raw[0].strip()
            elif _names:
                name = "/".join(_names)
            else:
                name = code
            # 中转城市真键位在 binfo（R40 census 37/60），行级键为
            # 调研期预期形态，两级并读
            trans = str(f.get("transCity")
                        or (info.get("transCity")
                            if isinstance(info, dict) else "") or "").strip()
            # r326 补采：渠道只为 1 转行下发 transCity（495 行冻结语料
            # 429 行多段、74 行多段断供——断供行以「直飞」身份进直飞池
            # 污染幻影守卫锚中位+读者把两转 26h 行程当直飞）。code[] 段链
            # FNO|FROM-TO|DATE 链式推导：段间衔接港=转点、同号续段=经停
            # 不换机不入转点；渠道真值在场即定谳不覆盖；城市名走
            # city_name_of 统一链（国际 177 城→国内反查→裸码，裸码真值
            # 仍优于误判直飞）
            _tc: list = []
            if not trans and isinstance(code_val, list):
                _segstrs = [str(x).strip() for x in code_val if str(x).strip()]
                for _i in range(len(_segstrs) - 1):
                    _a = _segstrs[_i].split("|")
                    _b = _segstrs[_i + 1].split("|")
                    if len(_a) < 2 or len(_b) < 2:
                        continue
                    _to = (_a[1].split("-") + [""])[1].strip().upper()
                    _from2 = (_b[1].split("-") + [""])[0].strip().upper()
                    if not _to or not _from2:
                        continue
                    if _to == _from2:
                        _cc = _to
                    elif airport_city_code(_to) == airport_city_code(_from2):
                        # 跨场自转（同城异场：LGA 落地→EWR 起飞、MXP→BGY
                        # 实录）——机场码精确衔接在城市级成立，转点=该城；
                        # 映射表走官方机场归属口径非统计猜测，异城对
                        # （HEL→ARN）恒等回退不相等=不误接
                        _cc = airport_city_code(_to)
                    else:
                        continue   # 链不衔接（异常段链）不入转点
                    if _a[0].strip() and _a[0].strip() == _b[0].strip():
                        continue   # 同号续段=经停不换机
                    if _cc not in _tc:
                        _tc.append(_cc)
                if _tc:
                    trans = "/".join(city_name_of(c) for c in _tc)
            # intl 降价/运营词面白名单（上方 _RE_REDUCE_DESC 注）：
            # 行级单串载体，非 H5 listLabel 数组形态
            _rd = str(f.get("reducePriceDesc") or "").strip()
            if not (QunarCrawler._RE_REDUCE_DESC.fullmatch(_rd)
                    or _rd == "成都两场互通"):
                _rd = ""
            # r336 T1：中转城市过境签标注（filter 字典面 join）——
            # 多转点任一命中即落（行程含该中转地=资格约束对整程生效）。
            # 双通道（push 审校 P3 收口）：码域主通道=链推导转点码
            # airport_city_code 归一后直查（行级展示名「台北桃园」与
            # filter 归一名「台北」词面域失配曾 7 行零贴签）；词面
            # 兜底通道=渠道真值 transCity（无段链可推码）全等查
            _visa = ""
            if _tc:
                for _c in _tc:
                    _v = _visa_by_code.get(airport_city_code(_c) or _c)
                    if _v:
                        _visa = _v
                        break
            if not _visa and _visa_by_city and trans:
                for _c in trans.split("/"):
                    _v = _visa_by_city.get(_c.strip())
                    if _v:
                        _visa = _v
                        break
            _label = "·".join(x for x in (_rd, _visa) if x)
            row = {
                "price": price,
                "code": code,
                "name": name,
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                "airlineCode": iata2(code.split("/")[0][:2]),
                # 国际特有拆分（税费已含在 minPrice 内，两键只作构成
                # 透传，消费端展示「含税」时可用）
                # taxPrice/nakedPrice 为字符串数字（RT 真报文 "402" 实证）
                **({"tax": float(f["taxPrice"])}
                   if _pos_num_s(f.get("taxPrice")) else {}),
                **({"nakedPrice": float(f["nakedPrice"])}
                   if _pos_num_s(f.get("nakedPrice")) else {}),
                # 营销角标（r51 差距普查：『当日低价』1/60，恰全场
                # 最低行——labels 族键，词面直传）
                **({"labels": _bt} if (_bt := str(
                    f.get("bigTrafficTag") or "").strip()) else {}),
                **({"cabin": _c} if (_c := str(f.get("cabinDesc") or "").strip()) else {}),
                # R42/R45 信息量对齐（国内行同族键名直用）：键名对齐
                # 国内 totalDuration/crossDayDesc——webui dur/cross 映射、
                # CSV 列、推送行（report 1244/1256）全链零改动即消费；
                # binfo 内 60/60 在场（R40 census），无值不落键卫生律
                **({"totalDuration": _du} if (_du := str(
                    (info.get("totalDuration") if isinstance(info, dict) else "")
                    or "").strip()) else {}),
                **({"crossDayDesc": _cd} if (_cd := str(
                    (info.get("crossDayDesc") if isinstance(info, dict) else "")
                    or "").strip()) else {}),
                **({"codeShare": "1"} if isinstance(info, dict)
                   and str(info.get("codeShare") or "").strip()
                   not in ("", "0") else {}),
                **({"depAirport": _da} if (_da := str(
                    (info.get("depAirport") if isinstance(info, dict) else "")
                    or "").strip()) else {}),
                **({"arrAirport": _aa} if (_aa := str(
                    (info.get("arrAirport") if isinstance(info, dict) else "")
                    or "").strip()) else {}),
                **({"transCity": trans} if trans else {}),
                # 经停标记（r329：binfo.stops=="1" 结构化真值，与
                # transNotice 停词面 14/14 同现双信号；intl 无 stopCitys
                # 载体城市不造值——normalize stopover 真值短路 + webui
                # stoptag 全链现成，PC binfo1.stops 同名同义跨端在册）
                **({"stopover": True} if isinstance(info, dict)
                   and str(info.get("stops") or "").strip() == "1" else {}),
                # fewTicketStr 为真键名（R40 census 60/60；行级
                # fewTicket 为调研期预期，两键并读）
                **({"fewTicket": _fw} if (_fw := str(
                    f.get("fewTicket") or f.get("fewTicketStr")
                    or "").strip()) else {}),
                **({"depTerminal": _dt} if (_dt := str(
                    f.get("depTerminal") or info.get("depTerminal") or "").strip()) else {}),
                **({"arrTerminal": _at} if (_at := str(
                    f.get("arrTerminal") or info.get("arrTerminal") or "").strip()) else {}),
                # 决策标签（r329 白名单：reducePriceDesc 词面挂 labels
                # 既有出口，与 PC priceLabel/H5 listLabel 同出口三端
                # 同消费；无值不落键同族律）；r336 T1 过境签词同出口
                # 「·」联接（H5 _h5_labels_of 同形态）
                **({"labels": _label} if _label else {}),
                # r336 T2：渠道廉航标注 join（binfo.name[] 航司中文名
                # 任一命中即落）——normalize `if not f.get("lcc")` 门
                # 让位，静态 AIRLINE_LCC 二字码表不覆盖的国际廉航
                # （OD/D7/FD/SL/IJ/GK 族）由渠道权威词面补齐
                **({"lcc": True} if (_lcc_names
                                     and any(n in _lcc_names
                                             for n in _names)) else {}),
            }
            # 观察哨（intl 恒空/恒档键族）：
            # ticketInsufficient（键名语义「票不足」，词面载体恒缺席）
            # 翻非空=按 fewTicket 出口评估；
            # dataExt.isLimitPrice：r337 首火取证结案（10/528 行翻 true，
            # 全部 PVG_SFO 单 dump 同一拼接行群，listTag=英文供给码
            # LBF_1^CPC/ASA^CPC 零中文词面、价非 dump 最低）=维持不采；
            # 哨继续，观察面=「true 行出现配套中文词面 / 价变异常聚集」
            # （ctrip limitPrice 哨同律取证）；载体注记：dataExt 与
            # luggageAvgPrice 本代已迁入 extparams（JSON 串）内侧，全量
            # 键 diff 按新路径核对，行级顶层缺席勿误判断链；
            # luggageAvgPrice 恒 0，翻非零=行李购买价域事件。
            # 旧哨 extparams.unionPtripFlightNo 退役：intl extparams 键域
            # 已整代更换（该键在新代 dump 全量缺席，哨前提消失空转），
            # 新代 extparams 逐键裁决见调研报告 Q14（英文内部码零词面
            # 整族不采，其余恒档键按上方三哨承接）
            out.append(row)
        return out

    @staticmethod
    def _detail_fields_from_text(txt: str) -> dict:
        """interdetail 渲染词面 → 详情维度（r53 富矿实锤：机型/餐食/
        行李/退改 per vendor，首档=行价 vendor）。词面锚定非选择器——
        SPA class 混淆漂移高频而中文词面稳定（r51 同律）。"""
        out = {}
        m = re.search(r"((?:空客|波音|ARJ|C919|庞巴迪|E\d{3})[^\s|]{0,12}?"
                      r"\((?:中|大|小)\))", txt)
        if m:
            out["plane"] = m.group(1)
        m = re.search(r"(无餐食|有餐食)", txt)
        if m:
            out["meal"] = m.group(1)
        m = re.search(r"(无托运行李|托运行李\s?\d+KG)"
                      r"(，?手提行李\s?\d+件x\d+KG)?", txt)
        if m:
            out["baggage"] = m.group(0).replace(" ", "")
        m = re.search(r"(退票费¥?\d+起，改期费¥?\d+起)", txt)
        if m:
            out["refundChange"] = m.group(1)
        return out

    def _fetch_intl(self, from_city: str, to_city: str,
                    dates: List[str]) -> List[FlightPrice]:
        """国际采集主路径（r325）：仅浏览器单路径——纯 httpx 被 Bella
        签名（改参数即失效）+ t1000 动态解码 + 登录墙三重门锁死
        （report §7.1 C 级），浏览器路径页面自执 JS 天然免疫。拦截用
        page.route 取响应体（on_response.text() 有「响应体已释放」
        时序丢体风险，q4 实证）。频率纪律沿用 fetch() 外壳错峰/退避。"""
        results: List[FlightPrice] = []
        fc, tc = from_city.upper(), to_city.upper()
        for date in dates:
            url = self.INTL_URL_TPL.format(
                from_name=urllib.parse.quote(self._intl_city_name(fc)),
                to_name=urllib.parse.quote(self._intl_city_name(tc)),
                date=date)
            self.logger.info("[qunar][intl] 浏览器 GET %s", url)
            bodies: list = []

            def _cap(route):
                try:
                    resp = route.fetch()
                    try:
                        bodies.append(resp.text())
                    except Exception:
                        pass
                    route.fulfill(response=resp)
                except Exception:
                    try:
                        route.continue_()
                    except Exception:
                        pass

            with self.browser() as ctx:
                page = self.new_page(ctx)
                page.route("**/*touchInterList*", _cap)
                try:
                    page.goto(url, wait_until="load")
                    for _ in range(12):
                        page.wait_for_timeout(2000)
                        try:
                            page.mouse.wheel(0, 1500)
                        except Exception:
                            pass
                        if bodies:
                            break
                except Exception as e:
                    self.logger.warning("[qunar][intl] 页面异常: %s", e)

                # R53 详情增强：最廉价行 interdetail 采 机型/餐食/行李/
                # 退改 四维（列表载荷结构性缺位）。flightCode 缓存摊销
                # ——同一航班只采一次（典型 0-2 次/航线/日），防风控加压
                _detail = {}
                _dkey = None
                if bodies:
                    try:
                        import json as _json
                        _raw = []
                        for _t in bodies:
                            try:
                                _o = _json.loads(
                                    _t[_t.find("{"):_t.rfind("}")+1])
                                _d = _o.get("data")
                                if isinstance(_d, str):
                                    _d = self._reassemble_h5_data(_d)
                                _rf = (_d or {}).get("flights") or []
                                if _rf:
                                    _raw = _rf
                                    break
                            except Exception:
                                continue
                        _cand = [f for f in _raw if isinstance(f, dict)
                                 and f.get("flightCode")]
                        if _cand:
                            _ch = min(_cand, key=lambda f: float(
                                f.get("minPrice") or 9e9))
                            _fc = _ch["flightCode"]
                            _dkey = ("/".join(
                                str(x).split("|")[0]
                                for x in (_ch.get("code") or [])
                                if x), round(float(_ch["minPrice"]), 2))
                            # 双门节流：fc 缓存 + 全程 ≥600s 一次
                            # （r53b 事故：首輪 22 航線每條新 fc 連發
                            # interdetail 導航=風暴，08:44 起 1999 全線
                            # 硬拒——會話預算律，導航計入速率檔）
                            if (_fc != getattr(self, "_detail_fc_last", None)
                                    and time.time()
                                    - getattr(self, "_detail_last_ts", 0) > 600):
                                _det_url = (
                                    "https://touch.qunar.com/ncs/page/"
                                    "interdetail?startCity="
                                    + urllib.parse.quote(
                                        self._intl_city_name(fc))
                                    + "&destCity=" + urllib.parse.quote(
                                        self._intl_city_name(tc))
                                    + "&startDate=" + date
                                    + "&flightCode="
                                    + urllib.parse.quote(_fc))
                                page.goto(_det_url, wait_until="load")
                                for _ in range(6):
                                    page.wait_for_timeout(2000)
                                    if self._detail_fields_from_text(
                                            page.inner_text("body")):
                                        break
                                _detail = self._detail_fields_from_text(
                                    page.inner_text("body"))
                                self._detail_fc_last = _fc
                                self._detail_last_ts = time.time()
                                if _detail:
                                    self.logger.info(
                                        "[qunar][intl] 详情增强: %s",
                                        _detail)
                    except Exception as e:
                        self.logger.warning(
                            "[qunar][intl] 详情增强失败(不影响主流程): %s", e)

            flights, risk = [], ""
            for t in bodies:
                flights, risk = self._parse_intl_response(t)
                if flights or risk:
                    break
            self._dump_raw_text(bodies[0] if bodies else "",
                                f"intl_{fc}_{tc}_{date}")
            if not flights and not risk:
                risk = self._intl_body_risk(bodies[0] if bodies else "")
            if risk == "empty":
                self._last_no_result = True
                self.path_note("H5", "empty", date=date,
                               detail="原站明确返回无符合条件的航班")
                self._sleep()
                continue
            if risk == "login":
                # 登录态卡片分层「会话可能失效」同款证据（国内 313 同律）
                QunarCrawler.login_suspect = True
                self.path_note("H5", "login", date=date,
                               detail="国际列表 1999/8 未登录硬拒")
                # 1999 硬拒不设 30 分钟冷却（r339 观测轮 2 定谳：cooldown
                # sleep 在 worker 线程内同步等 1776s——错峰等待即栅栏内
                # 泊车，每查询吃满 900s 路由栅栏实录 8 条/日）。硬拒面
                # 已由 login_suspect 砍退避门（fetch 外壳单次放弃）+
                # 下轮调度自然承接，30min 压制面的「1999 风暴」防御
                # 对象已消失；「成功一次即自清」复位律不变
                self.logger.warning(
                    "[qunar][intl] %s 未登录硬拒（1999/8）——请在配置页"
                    "「渠道登录」重登 qunar；本轮放弃不压制", date)
                self._sleep()
                continue
            if risk in ("slider", "captcha", "refresh"):
                _status, _kind = self._intl_risk_path(risk)
                self.logger.warning(
                    "[qunar][intl] %s 风控%s（%s/%s）——本轮拒采不绕过",
                    date, "强刷" if risk == "refresh" else "验证码",
                    risk, _kind)
                self.path_note("H5", _status, date=date,
                               detail="国际列表风控 %s（%s）" % (risk, _kind))
                self._sleep()
                continue
            if flights:
                self.path_note("H5", "ok", rows=len(flights), date=date,
                               detail="touch.qunar.com 国际列表")
                self._stamp_intl(flights, fc, tc)
                # R53 详情增强合并：interdetail 四维落最低行（_dkey=
                # (code 链, 价格) 对位——原始行与提取行同源匹配）
                if _detail and _dkey:
                    for _f in flights:
                        if (round(_f["price"], 2) == _dkey[1]
                                and _f["code"] == _dkey[0]):
                            _f.update(_detail)
                            break
                best = min(flights, key=lambda f: f["price"])
                results.append(FlightPrice(
                    platform=self.name,
                    from_city=from_city, to_city=to_city,
                    depart_date=date, price=float(best["price"]),
                    airline=str(best.get("airlineCode") or ""),
                    flight_no=str(best.get("code") or "").split("/")[0],
                    depart_time=best.get("depTime", ""),
                    arrive_time=best.get("arrTime", ""),
                    extra=json.dumps(flights, ensure_ascii=False),
                ))
                n_d = sum(1 for f in flights if not f.get("transCity"))
                self.logger.info(
                    "[qunar][intl] %s 最低含税价 ￥%.0f (%s)（明细 %d 条："
                    "直飞 %d / 中转 %d）",
                    date, best["price"], best.get("code") or "",
                    len(flights), n_d, len(flights) - n_d)
            else:
                self.logger.warning(
                    "[qunar][intl] %s 未解析到价格（响应 %d 份%s）",
                    date, len(bodies), f"，风控态 {risk}" if risk else "")
                self.path_note("H5", "empty", date=date,
                               detail="国际列表有响应但未解析出价格")
            self._sleep()
        return results

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
        才 parse），浏览器/httpx 通道拿到的都是乱序原串——必须先还原
        再 parse，json.loads 失败即弃会让 3/4 轮退化 DOM 兜底
        （cabin/meal/托运/停留等结构化字段全丢）。还原算法与页面 JS 一致：counter 为
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
        _reassemble_h5_data 还原（起 DOM 兜底降级为真兜底）；
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
            # route 级改期比价曲线（goFTrend=出发日期±7 天最低价 15 点，中心=行
            # depDate——生产实证 10-06 行曲线 09-29~10-13；语义是「换个日子
            # 飞多少钱」非「现在买 vs 再等等」）只挂
            # 当轮最低价行：逐行重复 ≈ 每轮 +300B×75 行 extra 膨胀，挂
            # 一行即可代表全轮（H5 现役主路径在场，PC 报文无此键）
            lo = min(out, key=lambda f: f.get("price") or 9e9)
            lo["trendGo"] = tg
        return out

    @staticmethod
    def _parse_trend_go(trend, intl=False):
        """trendPrice.goFTrend → [["MM-DD",价],…]（改期比价曲线数据源：出发
        日期 ±N 天同航线每日最低价，消费端语义=改期窗口非买票时机）。

        逐点结构校验宁缺勿错：price 是字符串；10-04 dump 曾见渠道侧
        数组截断接缝（index 4 后混入 AB 配置文本），坏点直接丢弃。
        单程国内无 backFTrend（0 命中），出现时留待后续。
        intl=True 时值域门走国际宽带单源（price_band_ok el={"intl":1}，
        上界 200000——长途高价 78139 实证于 cabinDesc 行价，国内 50000
        门会丢国际高价点）；默认维持国内门行为。"""
        if not isinstance(trend, dict):
            return None
        arr = trend.get("goFTrend")
        if not isinstance(arr, list):
            return None
        el = {"intl": 1} if intl else None
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
            if not price_band_ok(v, el=el):
                continue
            out.append([d[5:], round(v)])
        return out or None

    @staticmethod
    def _extract_flights_obj(flights_raw):
        """flights 数组 → 统一航班明细。

        字段语义（实测）：直飞时刻在 binfo，中转在 binfo1/binfo2
        （binfoX 的 dep/arr 即整体起终）；code 含 / 为中转；
        mixFlightName 首段为中转显示名；transTime 为全程时长。
        同族 PC 接口（wbdflightlist）同名键 transTime 已实证为
        停留时长（45/45 dump）——两端语义相反。H5 口径已结案：
        transTime == binfo1.totalMinute（结构化全程时长）268/268
        零背离、=停留时长 0 例（13 份 H5 dump 逐行核对，r308 渠道
        调研），当前读法正确；防未来 H5/PC 混窗时错用对方语义。
        totalMinute 为本读法的结构化备源（int 型，与 transTime
        全等已预验证）——transTime 词面失效时第一换源。"""
        out, seen = [], set()
        for f in flights_raw:
            if not isinstance(f, dict):
                continue
            try:
                price = float(f.get("minPrice") or 0)
            except (TypeError, ValueError):
                continue
            if not (PRICE_MIN <= price <= PRICE_MAX):
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
            # 值机时效风险警示（listPopView 弹层；r254 复核转常态备案：
            # H5 侧 10-05/10-06 代 5-6/代 在场、出口在产消费，键健康，
            # 观察哨结案改纯备案）：「临近起飞请先到值机柜台确认仍有
            # 时间值机/出票失败自动取消/已出票退改损失自负」——载体行
            # fewTicket/labels/refundChange 全空，行级唯一购买风险出口。
            # 双词面守卫（title 含「提示」且 mainText 含「值机柜台」）
            # 防弹层被渠道复用为营销位；mainText 偶带 font 标签，
            # strip 后参与判定与留痕。PC 复活轮核 wbdflightlist 同键
            # （无此键=PC 无源确认，出口维持 H5 侧供给）。
            lp = f.get("listPopView")
            ticket_risk = ""
            if isinstance(lp, dict):
                _mt = re.sub(r"<[^>]+>", "",
                             str(lp.get("mainText") or ""))
                if "提示" in str(lp.get("title") or "") \
                        and "值机柜台" in _mt:
                    ticket_risk = "临近起飞需确认值机"
            key = (code, dep_t, price)
            if key in seen:
                continue
            seen.add(key)
            mix_raw = (f.get("mixFlightName") or "").splitlines()
            mix = mix_raw[0].strip() if mix_raw else ""
            # 共享实际承运三档：主源 mainCarrierSimpleNameAndNo（带名，
            # codeShare 门控）→ 真值 mainCarrier 机读号（≠本行段号集；
            # PC 直飞 m4 门「mainCarrier≠airCode」的段号集推广）→
            # mixCodeShare 末行兜底。「首段共享+二段常规」行（标本
            # 3U1599/MU2161）主源恒空、真值 mainCarrier='CZ6305' 在场，
            # 末行恰是二段自身词面「东航MU2161」——无门时自引用落库
            # （DB 799 行中 12 行误导实证），末行号 ∈ 段号集宁缺勿落；
            # 末行提取不到任何航班号同样不落（无法排除自引用，
            # 观测形态末行恒带号，此为防御档）。真值档作用于全部
            # codeShare 行（含直飞），dump 实证 mainCarrier 仅中转行
            # 在场（1/140）——直飞扩展面与 PC m4 门对齐、有段号集
            # 守卫，渠道未来直飞下发时语义正确
            _share_c = ((info.get("mainCarrierSimpleNameAndNo") or "").strip()
                        if info.get("codeShare") else "")
            _segs = set(code.split("/"))
            if not _share_c and info.get("codeShare"):
                _mc = (info.get("mainCarrier") or "").strip()
                if _mc and _mc not in _segs:
                    _share_c = _mc
            if (not _share_c and info.get("codeShare")
                    and f.get("mixCodeShare") and len(mix_raw) > 1):
                _last = mix_raw[-1].strip()
                _fnos = QunarCrawler._RE_FNO.findall(_last)
                if _fnos and not any(c in _segs for c in _fnos):
                    _share_c = _last
            trans = (f.get("transCity") or "").strip()
            if isinstance(b2, dict) and b2 and not trans:
                trans = "中转"   # binfo2 在场即中转，防 transCity 缺省被误分直飞
            # 中转各段承运航司中文名（carrierSimpleName「南航|东航」，
            # 中转行 100% 在场）——非共享中转行的二段承运方唯一
            # 载体在此（shareCarrier 只在 codeShare 行、PC shareAirline
            # 同键=共享行专属）。H5 兜底路径专属源（PC 主路径无此键，
            # 复活期归零属断供非回归）。全角分隔符归一；「null」垃圾
            # 串不落（mainCarrier 家族曾现字符串 null）；共享行不落
            # （承运信息由 shareCarrier 词面承载，防两键同屏混淆）；
            # 仅中转行落（单段无「各段承运」语义）。消费端渲染门带
            # 非共享行独立档（「承运·」词面），三端同轮接线。
            _share_air = ""
            if trans and not _share_c:
                _cs = str(info.get("carrierSimpleName") or "").strip()
                if _cs and _cs.lower() != "null":
                    _share_air = _cs.replace("｜", "|")
            # 中转衔接：第二段起飞 − 第一段到达（跨天回绕）——H5 结构
            # 中 binfo1.arr 即第一段到达、binfo2.dep 即第二段起飞。
            # 假衔接源头掐灭（5/5 真实样本验证）：H5 的 binfo2 是 binfo1
            # 的复制，binfo2.depTime == binfo1.depTime == 整体起飞时刻，
            # 此时 (dep−arr)%1440 = 1440−全程 的回绕垃圾（全程>12.5h 时
            # 绕过 normalize 物理守卫，线上 345 条假「停 X:XX」实锤）——
            # 缺独立第二段时刻或与整体起飞相同都弃算（宁缺勿错）。
            # 缓采挂哨（r308 渠道调研）：binfo1.totalDuration 在中转行
            # =首段飞行时长（「4时50分」290min ≠ totalMinute 470 全程），
            # 直飞行=全程（已采 totalDuration 同值零增量）——二段时长
            # 无独立源（binfo2 复制态），单落首段呈半截信息不采；哨=
            # binfo2.depTime ≠ binfo1.depTime 的行检出（真分段形态到场）
            # 时两段时长配对齐再立项。
            lay = ""
            b2_dep = (b2.get("depTime") if isinstance(b2, dict) else "") or ""
            b1_arr = info.get("arrTime") or ""
            # 整体到达防御：b2 真独立（第二段起飞≠整体起飞）
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
                    # 日期钉优先（同 PC 路径：真停 ≥24h 的 %1440 回绕
                    # 根治；助手自读 info.arrDate 首段到达日——arr_d
                    # 可能已被上方 b2 整体到达口径覆写，不回传）
                    lay = _layover_pinned(info, b2)
                    if lay is None:
                        lay = (d2 - a1) % 1440
                        # %1440 回绕只在 depDate→arrDate 跨度 ≤1 天时可信：
                        # span≥2 天的 ~25h 真实停留会被回绕成 60min 假值
                        span = _span_days(dep_d, arr_d)
                        if span >= 2 and lay < 300:
                            lay = ""
            # binfo1.transInfo 是渠道结构化真值（首末段四段
            # 时刻+transTime 停留+中转城；分片重组后中转行 100% 在场，
            # 直飞行无此键），中转行直接采信——上面 binfo2 猜衔接链路
            # 降为无 transInfo 时的兜底（binfo2 是 binfo1 复制、整体
            # 时刻口径，只能算不能信）；lay2dep 同步换真二段起飞时刻
            # （旧值=binfo2.depTime=整体起飞，明细「二段 X 起飞」曾
            # 一直显示整体起飞时刻）
            lay2dep = ((b2.get("depTime")
                        if isinstance(b2, dict) else "") or "").strip()
            trans_term = ""
            ti = info.get("transInfo")
            lay_src = ""
            if isinstance(ti, dict) and ti and trans:
                # 中转航站楼（二期，撤一期「保持单值口径」定论）：
                # transInfo.firstArrInfo 结构化真值（中转行 88% 有值），
                # 「咸阳T3」形态含机场名防同城多场歧义，与 ctrip
                # transTerminal 同名同形（换乘哪栋楼=决策字段）
                tfa = ti.get("firstArrInfo")
                if isinstance(tfa, dict) and tfa.get("terminal"):
                    trans_term = (str(tfa.get("airport") or "").strip()
                                  + str(tfa.get("terminal")).strip())
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
            # 经停城市（修订旧注释误判）：H5 实际键名为复数
            # stopsCitys，字符串形态挂 binfo/binfo2 层
            # （binfo2 常是 binfo1 复制，两级互为兜底）；9/25-10/06 六份
            # 报文实测全为空串、真值分隔符未采样到，按 PC 口径把常见
            # 分隔符归一为「;」透传。stopsAirPort 半边退役（载荷卫生
            # tam 先例，零消费孤儿键，与 PC 路同轮收口）
            # 读取无条件（中转行 binfo1.stopsCitys 同样照落——陇南/
            # 阿拉尔真值 10-05/10-07 dump 在案，r331 防回归钉
            # test_r331_fields 锁此通道），换源门只管下方 transInfo 补缺
            sc = ((info.get("stopsCitys") or b2.get("stopsCitys") or "")
                  .strip().replace(",", ";").strip(";"))
            # 渠道恒逗号占位「,」经上面 replace 成裸「;」——纯分隔符
            # 形态视为占位落空串（卫生修复：中转行 30 行/轮脏值
            # ";" 进 extra 污染覆盖率统计；真值「西安;库尔勒」剥后非空不受影响）。
            # 补前导/尾部分隔符伪影：渠道「,庆阳」曾归一成
            #「;庆阳」放行（DB 99 行在案）——两端 strip(";") 同步根治，
            # 下方纯分隔符断言保留作防御
            if not sc.strip(";"):
                sc = ""
            # 经停城市/时长换源补缺：stopsCitys 六份报文实测恒
            # 逗号占位，经停真值挂 binfo.transInfo{transCity,transTime}
            # （stopFlight=true 行 5/5 在场：「西安」+「1小时5分」/「45分」/
            # 「18时30分」）——仅经停行采（中转行 transInfo 是衔接四段
            # 结构，trans 已在上方采过停留），门控 _stopflight 防普通
            # 直飞行 transInfo 空占位串误入
            stop_time = ""
            if not trans and QunarCrawler._stopflight(f.get("extparams")):
                _ti_s = info.get("transInfo")
                if isinstance(_ti_s, dict):
                    _sct = str(_ti_s.get("transCity") or "").strip()
                    if _sct:
                        sc = _sct
                    stop_time = str(_ti_s.get("transTime") or "").strip()
            meal, baggage = _meal_from_addons(
                f.get("flightAddInfoIntegration"))
            # ---- 决策字段补采（10-05 dump 71 行实证）----
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
            # 空串/缺键），无值不落键；中转行航站楼二期已单列 transTerminal
            # （transInfo.firstArrInfo，见上）
            dep_term = (info.get("depTerminal") or "").strip()
            arr_term = (info.get("arrTerminal") or "").strip()
            # 中转行 arrTerminal 语义修正：binfo1.arrTerminal 是
            # 首段到达=中转楼，与 arrTime/arrDate 的整体口径错位（DB 实锤
            # 2552 行非空仅 166 与 transTerminal 同源—— 修了
            # 时刻两键漏了楼号）。整体到达楼真值在 transInfo.secondArrInfo
            # （乌→沪 24/24、27/27 非空），有值才覆盖、空串不覆盖（宁缺
            # 勿错，与 arrTime 防御同型）；顺带采 secondArrInfo
            # .airport 到达机场名（「虹桥」，同城多场决策信息，仅中转行
            # 有源）。中转出发楼 secondDepInfo（换乘哪栋楼出，与 trans
            # Terminal 到达楼构成「T2 到 T5 出」路径）：与到达楼同楼时
            # 无增量不落
            trans_dep_term = ""
            trans_arr_air = ""
            if isinstance(ti, dict) and ti and trans:
                _sat = str(((ti.get("secondArrInfo") or {})
                            .get("terminal")) or "").strip()
                if _sat:
                    arr_term = _sat
                trans_arr_air = str(((ti.get("secondArrInfo") or {})
                                     .get("airport")) or "").strip()
                _tfa_t = str(((ti.get("firstArrInfo") or {})
                              .get("terminal")) or "").strip()
                _sdt = str(((ti.get("secondDepInfo") or {})
                            .get("terminal")) or "").strip()
                _sda = str(((ti.get("secondDepInfo") or {})
                            .get("airport")) or "").strip()
                if _sdt and _sdt != _tfa_t:
                    trans_dep_term = _sda + _sdt
            # 机场级定位漏读修复（dump 实证 binfo/binfo1 层
            # depAirport 直飞 48/48+中转 44/44 全量在场，解析器必须读全
            # ——否则 DB depAirport 仅 11.6% 全来自 PC 行）：dep 全行直读；
            # arr 直飞行补 binfo.arrAirport（中文「虹桥/浦东」100%），
            # 中转行仍 secondArrInfo 真值优先（binfo1.arrAirport 是三字
            # 码「SHA」且语义为整体到达——缺 secondArrInfo 时宁缺不落
            # 码，防中文名列混入码形态）
            dep_air = (info.get("depAirport") or "").strip()
            if trans:
                arr_air = trans_arr_air
            else:
                arr_air = (info.get("arrAirport") or "").strip()
            # H1 机场 IATA 码（挂起项跨渠道归一定证成立，调研
            # 三重定证：全样本 ^[A-Z]{3}$ 零违例/跨渠道 48 共同航班号
            # 48/48 同码对/DB 中文名映射域零冲突）。取法：dep 全行读
            # binfo/binfo1 的 depAirportId（直飞 138/138+中转 76/76，
            # 首段出发=整体出发）；arr 直飞行 binfo.arrAirportId（138/
            # 138）、中转行只认 binfo2.arrAirportId（整体到达 76/76）
            # ——勿用 binfo1.arrAirport(Id)，那是首段中转场码（
            # 在案，混入即脏）。iata3 守卫不匹配不落
            dep_code = iata3(info.get("depAirportId"))
            if trans:
                arr_code = iata3(b2.get("arrAirportId"))
            else:
                arr_code = iata3(info.get("arrAirportId"))
            # 机型补采（第八批调研 dump 实证）：binfo.name[1] 是
            # JSON 真值机型「波音737(中)」（直飞 83% 在场，值域 4 种干净
            # 形态；H5 主路径不采的话 DB plane 仅 10.7% 且全是旧 ICAC 码+
            # DOM 兜底轮残留）。fullmatch 锚定：中转行 name 无机型、共享
            # 行 name[1]=实际承运号、「737-800/波音737MAX8」无体量形态
            # 一律不命中自动弃（宁缺勿错）；体量括号同步落 planeSize，
            # 与 tongcheng amt/ctrip kind 同值域「大型机/中型机」
            plane_txt, plane_size = "", ""
            _nm = info.get("name")
            if isinstance(_nm, list) and len(_nm) > 1:
                _pm = re.fullmatch(r"((?:波音|空客)\d{2,3})\(([中小大])\)",
                                   str(_nm[1] or "").strip())
                if _pm:
                    plane_txt = f"{_pm.group(1)}({_pm.group(2)})"
                    plane_size = {"大": "大型机", "中": "中型机",
                                  "小": "小型机"}[_pm.group(2)]
            # 儿童/婴儿价（extparams.childPrice/infantPrice，数值）：0 为
            # 「未报价」占位（childPrice 35/71 行为 0，中转/全价行），
            # 仅收正数（_pos_num）；同律补公务舱最低价 bizPrice
            # （extparams.businessClassMinPrice 正数 32-45% 在场，0=无
            # 公务舱/未报价占位——economyClassMinPrice 恒等 minPrice
            # 纯重复不采）
            # 断供备案（防下轮观测误判回归）：bizPrice/
            # childPrice/infantPrice 三键为 H5-only 源，PC 行
            # businessClassMinPrice 恒 0 且无 bizVendorPrice（调研
            # 定证无源非漏采）——09:52 起 PC 独占主路径后
            # DB 部署窗 0/573（_scratch/.md §7 逐小时定证
            # 断点）；H5 兜底回归即恢复，勿按回归排查、勿寻 PC 源
            child_price = (_pos_num(epd.get("childPrice"))
                           if isinstance(epd, dict) else None)
            infant_price = (_pos_num(epd.get("infantPrice"))
                            if isinstance(epd, dict) else None)
            biz_price = (_pos_num(epd.get("businessClassMinPrice"))
                         if isinstance(epd, dict) else None)
            if biz_price is None:
                # 备源（bizVendorPrice.totalPrice 字符串数字）：
                # 与主源同现 260/260 行值全等（同公务舱体验价报价），备源
                # 独有 22/582 行全为中转行（主源 extparams 无值）——采后
                # 公务舱可报行 272/272 全覆盖；仅主源无正值时兜底，int
                # 协议落键处统一
                _bv = f.get("bizVendorPrice")
                if isinstance(_bv, dict):
                    try:
                        _bvp = float(_bv.get("totalPrice") or 0)
                        # band 守卫对齐 PRICE_MAX：字符串 "1e999"→inf 类
                        # 脏值不落（int(inf) 在落键处 OverflowError 炸整
                        # 轮，m1）
                        if 0 < _bvp <= 50000:
                            biz_price = _bvp
                    except (TypeError, ValueError):
                        pass
            # 折扣（extparams.listLowestCabinDiscount "4.6" 数值串，
            # 71/71 在场）→ 落既有键名 discount（PC discountStr 同键，
            # flightnorm.cabin_text/report 图均按此消费），"4.6" 拼
            # 「4.6折」对齐 PC 值形态（report 图折扣只认「N.N折」）；
            # 合理域 [0.5,10]（脏值弃，与 ctrip drate 同律）。
            # 观察哨（discount 值域）：部分航线期整窗值域塌缩恒「10折」
            # （同航班他渠道真折扣在案=渠道侧占位透传；历史值域真含
            # 10 折，不置空防误杀真全价行）——按渠道本态展示、禁据此
            # 键做口径决策；轮值域恢复多值即自然复采
            disc_txt = ""
            if isinstance(epd, dict):
                try:
                    _lc = float(epd.get("listLowestCabinDiscount"))
                    disc_txt = f"{_lc:g}折" if 0.5 <= _lc <= 10 else ""
                except (TypeError, ValueError):
                    disc_txt = ""
            # 观察哨（extparams 两恒值键）：packageCutPrice（套餐打包
            # 价，现值 ≡ lowPrice 逐行全等=纯重复）出现 ≠lowPrice 取值
            # 即按「套餐价」决策字段调研；satisfyPassengerLimit（恒
            # false 占位）翻 true 即按购买资格限制词调研（labels 限龄
            # 白名单通道现成）。另备：binfo1.totalMinute（结构化全程
            # 时长 int，与重建值互证预验）为中转 totalDuration 重建
            # 失效时的换源首选，非失效不采。
            # 扩员（r324 渠道调研 PC extparams n=135 值域）：newUser
            # NoRisk/weiXinDirect/needShowBuyHigherPayLabel/
            # filterShareShowAct 同门恒 false——任一翻 true 按「新客
            # 保障/渠道直连/升舱引导」购买资格域先词面取证再立项；
            # PC 停摆期仅离线备案，随路径恢复一并复验。
            # 哨位升级（r308 渠道调研）：套餐域新键
            # listLowestPackageCutPrice（列表级锚，每 dump 1-2 恒值，
            # 与 min(minPrice) 逐 dump 配对 8/9 精确相等）——取值
            # < 本 dump min(minPrice) 时=「套餐拆分价击穿列表最低」
            # 事件，按套餐价决策域立案。复核口径：packageCutPrice
            # 形态已漂移 str"1560.0" vs int 1560 双态并存——哨位脚本
            # 一律数值比较（float() 归一），禁字符串等值比较，防
            # 哨位自伤假阳。
            # r321 首例事件（孤例不立案）：GS6549/KN2918 行
            # packageCutPrice=2204 < lowPrice=2350（1/219，bvp 缺席），
            # 同 dump listLowestPackageCutPrice=1849 未击穿列表最低
            # 1750（列表级无事件）——跨轮复现 ≥2 再按套餐价决策域
            # 立项
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
            # 观察哨（r308 渠道调研两恒值域）：①flightMark.cabinTypes
            # （["2"]:345/["1","2"]:184/["1"]:2 内部码，与 bizPrice>0
            # 双向不完全相关、语义未证）——值域出现 "3" 或与 bizPrice
            # 相关性翻转时按舱位域调研（公务舱可报信息现由 bizPrice
            # 承载）；②bizVendorPrice 恒值族 sellStatus/transferLowest/
            # highCostPerformance（恒 0/false/空串）——翻非恒值时分别
            # 按「不可售/中转最低/高性价比」域立项（现值纯占位）。
            # 扩员（r324 渠道调研 bvp 行 66 全键值域）：userMsgCopy/
            # userMsgCopyPrice/roundingDownPrice/hasUnionPack/
            # leftTagType/flightItemType/airTrainTransferShow/
            # bigTrafficAirTrain/flightAndTrainNearBy/nearbyFlight/
            # showFlightPriceInfo 同门恒 false/0——任一成员翻非恒值，
            # 按「购买资格/渠道直连/套餐打包/抹零」域先词面互证再
            # 立项（键名推断不构成采依据）
            # name 显示名源修复（调研 R1）：mixFlightName 只在
            # 中转行在场（dump 49/143 与中转行数相等），直飞行恒落裸码
            # （DB 24h 55.7% 明细 name 无航司名—— depAirport
            # 「在场真值未读」同型）；真值在 binfo.name[0]（直飞 94/94
            # 「春秋9C8866」形）与 binfo1.names[0]（混淆码行「华夏航
            # G581O1J」全文形态）。守卫：仅当本行 code 是显示名子串才
            # 采用（防渠道名称与航班号错位——「中联航KN5807」vs
            # 「中国联航KN5807」字面不同即拒绝），取不到维持 code
            # （宁缺勿错）
            disp = mix
            if not disp:
                for _k in ("name", "names"):
                    _nl = info.get(_k)
                    if isinstance(_nl, list) and _nl:
                        _n0 = str(_nl[0] or "").strip()
                        if _n0 and code in _n0:
                            disp = _n0
                            break
            # 中转二段出发日期（extparams.transGoDate，H5 真源；JSON
            # 串/dict 双形态 _stopflight 同律）：跨天中转「二段哪天
            # 起飞」决策辨识信息，与 PC binfo1.transCityDepDate 双源
            # 各自路径同键。守卫同 PC：形正 + 晚于出发日 + 仅中转行
            _tgd = QunarCrawler._trans_go_date(f.get("extparams"))
            if (not trans or not re.match(r"^\d{4}-\d{2}-\d{2}$", _tgd)
                    or not re.match(r"^\d{4}-\d{2}-\d{2}$", dep_d)
                    or _tgd <= dep_d):
                _tgd = ""
            # 航司二字码派生补源：H5 无 shortCarrier（PC 专属键），
            # PC 软拒断供期消费面（webui 搜索/CSV 列/alerter 跨渠道
            # 补全白名单）航司维度全空。flightMark.carrier ≡ code
            # 前缀（146/146 实证的可派生性）→ 从 code 派生（直飞
            # 首二字、中转各段首二字斜杠连写），iata2 守卫同律不
            # 匹配落空串；PC shortCarrier 恢复后语义一致无需切换
            _ac = "/".join(p for p in (iata2(_s[:2])
                                       for _s in code.split("/")) if p)
            # 全程时长（str 槽位无值不落，与 PC 出口同口径）。词面归一
            # dur_min→fmt_dur：顶层 transTime 原词面透传曾把中转行英文
            # '25h40m'/'5h' 全量染进 DB（r244 before 基线 416/416=100%，
            # 数值全对纯词面缺陷；消费端 normalize 有同型归一但 DB/CSV/
            # API dur 面原词面出场）。unparseable 原样保留不造值。
            # 兜底哨（r308 渠道调研口径结案的连带面）：totalDuration
            # 兜底在中转行=首段飞行时长语义（binfo1.totalDuration 实证
            # ≠全程 totalMinute，见 _extract_flights_obj 缓采挂哨）——
            # transTime 在场时兜底不可达（268/268 满勤）故现行为正确；
            # transTime 词面若失效，真换源按备案取 totalMinute（结构化
            # 全程 int），勿沿用本兜底把首段时长冒充全程落库
            _td = str(f.get("transTime")
                      or info.get("totalDuration")
                      or "").strip()
            if _td:
                from core.flightnorm import dur_min as _tdm, fmt_dur as _tfd
                _tv = _tdm(_td)
                if _tv is not None:
                    _td = _tfd(_tv)
            row = {
                "price": price,
                "code": code,
                "name": disp or code,
                "depTime": dep_t,
                "arrTime": arr_t,
                "depDate": dep_d,
                "arrDate": arr_d,
                # 「属性不适用即落空串」残留族无值不落键（r241 观测
                # 立案 8 键，与 PC 出口同轮对齐；中转/有值照落）
                **({"transCity": trans} if trans else {}),
                **({"crossDayDesc": _cdd}
                   if (_cdd := (str(f.get("crossDayDesc") or "").strip()
                                or str(info.get("crossDayDesc") or "").strip()))
                   else {}),
                **({"totalDuration": _td} if _td else {}),
                **({"layover": lay} if lay != "" else {}),
                # 空串不落（与 PC 出口同口径）：直飞行曾恒带空串落库
                **({"lay2dep": lay2dep} if lay2dep else {}),
                **({"transGoDate": _tgd} if _tgd else {}),
                # 停留来源标记：transInfo=渠道结构化真值（flightnorm 对
                # 该来源跳过 1440 回绕启发判伪——真值跨天长停留恰落在
                # 击杀区，dump 实测 3/150 误杀）；无标记不落键（缺席与
                # 空串在消费端语义下等价）
                **({"layoverSrc": lay_src} if lay_src else {}),
                # 值机时效风险警示（listPopView 弹层，双词面守卫在上方
                # ——落固定词面，读者语义=「误购可能不能出行/出票失败
                # 自动取消」，价格格 ⚠ 徽标消费，agePolicy/riskPolicy
                # 同语义族同轮接线）
                **({"ticketRisk": ticket_risk} if ticket_risk else {}),
                # 决策字段移植（9/25 完整 H5 报文 75 行实测，勿照抄 PC 键名）：
                # H5 无 mealDesc → 餐食在 flightAddInfoIntegration.flightAdditionInfos[]
                # （正餐/有餐食/无餐食/点心...）；经停城市键实为复数
                # stopsCitys（stopsAirPort 半边已退役，载荷卫生零消费），
                # 无 stopTime 键、extparams.stops 是布尔非数组（无停留
                # 分钟可转；起经停停留经 transInfo 换源补采，
                # 见上 stopTime 字段）；planeType/transitServiceLabel 键仍无
                # （flightMark.planeType 75/75 空串）不移植；经停标记走
                # extparams.stopFlight 布尔（6/6 与 DOM「停」行交叉一致）
                # → normalize 产 stopover。
                # cabinDegree 不落 cabin（r222 dump 定谳撤伪语义出口）：
                # 该键只在中转行出现、值域漂移（9/25 实测 T/Q/E → 10-05
                # A/L/N/R1…，含两字符 'R1'），10/10 'A' 行全为中转且价位
                # 1747-1950（头等价位应 3-5×）——是段级折扣桶（多来自
                # 廉航第二段）非行级舱位；9/25「同义舱位代码」推断有误，
                # T/Q/E 时代靠「未知字母默认经济舱」映射惯例遮蔽，值域
                # 漂出头等/公务映射后爆雷（￥2416 经济舱行被推成
                # 「头等舱」）。宁缺勿错：cabin 键不产，原始值留 dump 备研。
                # 机型/体量（上方注释块：binfo.name[1]，normalize
                # cabin_text 已消费 plane 拼舱位行、webui planeSize 白名单
                # 既有渲染位零改动）；无值不落键（r242 after 观测 r1
                # 抓漏：中转行空串平铺，与 PC 出口 walrus 门同口径；
                # fullmatch 锚定已拒脏形，门只管「本行无词面」）
                **(({"plane": plane_txt} if plane_txt else {})),
                **({"planeSize": plane_size} if plane_size else {}),
                # 新决策字段：余票紧张标签（值域实测仅「票少」）；
                # 无值不落键（r241 残留族收口）
                **(({"fewTicket": _ft}
                    if (_ft := (f.get("fewTicketStr") or "").strip())
                    else {})),
                # 共享航班实际承运（仅展示，不入指纹）：营销号 code 的
                # 真实执飞航司+航班号，如「上航FM9224」。三档链见
                # 上方组装处（主源带名→真值 mainCarrier→末行兜底
                # 带自引用门），此处只消费现值
                **({"shareCarrier": _share_c} if _share_c else {}),
                # 中转各段承运航司名（carrierSimpleName，非共享中转行
                # 专属；无值不落键同上）
                **({"shareAirline": _share_air} if _share_air else {}),
                # 无 addon 信息不落键（r242 after 观测 r1 抓漏：中转行
                # 空串平铺，「无餐食/无免费托运」渠道显式词面是有值形态
                # 照落——空串只代表信息缺席）
                **(({"meal": meal} if meal else {})),
                **(({"baggage": baggage} if baggage else {})),
                **(({"stopCitys": _scc} if (_scc := sc) else {})),
                "stopFlight": QunarCrawler._stopflight(f.get("extparams")),
                # 新决策字段（上面注释块：键路径 + dump 命中率）；航站
                # 楼无值不落键（单航站楼侧恒空串，恒空键卫生律 tuniu 同族）
                **({"depTerminal": dep_term} if dep_term else {}),
                **({"arrTerminal": arr_term} if arr_term else {}),
                # 中转航站楼对无值不落键（同族恒空键卫生律，str 槽位
                # 空串=无值；有值照落不变）
                **({"transTerminal": trans_term} if trans_term else {}),
                # 中转机场出发楼（secondDepInfo，「正定T2」形，
                # 与 transTerminal 到达楼配对成换乘路径）+ 到达机场名
                # transArrAir→arrAirport（换源见上方注释块）
                **({"transDepTerminal": trans_dep_term}
                   if trans_dep_term else {}),
                "depAirport": dep_air,
                "arrAirport": arr_air,
                # H1 机器可读机场码（str 空串口径同邻键；webui
                # 白名单/渲染门另端同轮接入）
                "depAirportCode": dep_code,
                "arrAirportCode": arr_code,
                # 航司二字码（派生补源见上方注释块；与 PC 同键同出口，
                # webui 白名单/CSV 列/alerter 补全白名单三消费面现成）
                "airlineCode": _ac,
                # 折扣词面无值不落（与 PC 出口同口径）
                **({"discount": disc_txt} if disc_txt else {}),
                # transferBaggage 无值不落键（trans_bag 空串=未标注，
                # normalize setdefault 兜底语义不变）
                **({"transferBaggage": trans_bag} if trans_bag else {}),
                # 决策标签（调研④ dump 实证，与 PC priceLabel 的
                # labels 键同出口；PC 软拒期间 H5 侧本就无标签源）
                # 传 info：背书真值在 binfo 层（层级修复见函数注）；
                # 无值不落键（r241 残留族收口）
                **(({"labels": _lbh}
                    if (_lbh := QunarCrawler._h5_labels_of(f, info))
                    else {})),
            }
            # 数值/JSON 串型字段无值不落键（childPrice/infantPrice 为数值
            # 协议、refundChange 为定版短 JSON 串，空串语义不明宁缺勿错）
            if child_price is not None:
                row["childPrice"] = child_price
            if infant_price is not None:
                row["infantPrice"] = infant_price
            if biz_price is not None:
                # int 协议：渠道价无小数语义，float 透传曾
                # 让 alerter isinstance(int) 门静默缺席 compare 公务词条
                row["bizPrice"] = int(biz_price)
            if refund_txt:
                row["refundChange"] = refund_txt
                # 退改费结构化双键（与 PC 出口同协议，_rj 为本行
                # refund_txt 的解析 dict——refund_txt 非空则必经本行
                # 赋值）；-1「不可改」如实保留，半在场键逐键判
                if "returnFee" in _rj:
                    row["returnFee"] = _rj["returnFee"]
                if "changeFee" in _rj:
                    row["changeFee"] = _rj["changeFee"]
            if stop_time:
                row["stopTime"] = stop_time
            out.append(row)
        return out

    @staticmethod
    def _svc_txt(tsn: str, tsl: str) -> str:
        """中转服务权益词：Name:Label 拼接；Label 自带 Name 前缀
        （'中转优享：免费餐食'）时不再重复拼（观测：
        '中转优享:中转优享：…' 双前缀病）。"""
        tsl = str(tsl or "").strip()
        tsn = str(tsn or "").strip()
        if not tsl:
            return ""
        if tsn and not tsl.startswith(tsn):
            return f"{tsn}:{tsl}"
        return tsl

    @staticmethod
    def _stopflight(ep):
        """extparams 渠道现以 JSON 字符串下发，升级为对象时子串匹配
        静默 False → H5 兜底经停班全判直飞：两种形态都认。串形态
        容忍冒号后空格（紧凑度非协议，`"stopFlight": true`
        形态曾静默 False）。"""
        if isinstance(ep, str):
            return bool(re.search(r'"stopFlight"\s*:\s*true', ep))
        if isinstance(ep, dict):
            return bool(ep.get("stopFlight"))
        return False

    @staticmethod
    def _trans_go_date(ep):
        """extparams.transGoDate 中转二段出发日期：JSON 串/dict 双形态
        解析（_stopflight 同律），裸值返回由消费点守卫（形正/晚于出发
        日/仅中转行）。"""
        if isinstance(ep, str):
            m = re.search(r'"transGoDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"', ep)
            return m.group(1) if m else ""
        if isinstance(ep, dict):
            return str(ep.get("transGoDate") or "").strip()
        return ""

    # ==================== DOM 兜底（touch 页渲染后列表） ====================
    _RE_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
    # 价格容千分位（"1,234"——渠道改格式时整渠道曾静默空转）
    _RE_PRICE = re.compile(r"^[￥¥]?(\d{1,3}(?:,\d{3})+|\d{3,5})$")
    _RE_FNO = re.compile(r"[\u4e00-\u9fa5]{0,6}((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})")
    # 航班号合规校验（联程混淆码守卫）：IATA 号=两位航司码+
    # 3-4 位数字。「华夏航G581O1J」被 _RE_FNO 回溯截成假号 G581——
    # 任何渠道都查不到，却进了指纹与推送文案（「中转华夏航G581」）
    _RE_FNO_V = re.compile(r"^[A-Z0-9]{2}\d{3,4}$")
    _RE_DUR = re.compile(r"^(\d+)h(?:(\d+)m)?$")

    @classmethod
    def _parse_dom_flights(cls, text: str, date: str) -> list:
        """解析列表容器 innerText（渲染后 DOM）为航班明细。

        页面数据接口的 data 常为分片混淆体（页面 JS join 后才 parse），
        但渲染后的 DOM 文本永远完整。每班字段按行排列（2026-09 实测）：
        直飞 HH:MM|机场|N时M分|(+N天)?|HH:MM|机场|航司 机型|价格
        中转 HH:MM|机场|NhMm|转|中转城市|(+N天)?|HH:MM|机场|航司(空格分隔多段)|价格
              （时长为 h/m 形态且只有全程一个时长段；无二段起飞时刻）
        经停 HH:MM|机场|N时(分)?|停|(+N天)?|HH:MM|...
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
            if not (PRICE_MIN <= f["price"] <= PRICE_MAX):
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
            # _via（转/停 哨兵）不在此 pop：flightnorm.normalize 消费它
            # 导出 stopover（DOM「停」=同机号经停），清洗点在消费端
            try:
                d0 = _dt.strptime(date, "%Y-%m-%d")
                f["depDate"] = d0.strftime("%Y-%m-%d")
                days = int(cross[1]) if cross else 0
                f["arrDate"] = (d0 + _td(days=days)).strftime("%Y-%m-%d")
            except ValueError:
                f["depDate"], f["arrDate"] = date, ""
            # crossDayDesc/transCity 无值不落键（r241 残留族收口：
            # DOM 兜底路径与 _extract_flights_obj 同键缺席口径对齐，
            # 「转」状态机路径有值才写）
            if cross:
                f["crossDayDesc"] = cross
            # totalDuration 空串 setdefault 撤（DOM 兜底族外残留对齐：
            # normalize 有时刻即重算写键、消费端全 .get——空串兜底
            # 零信息，无值不落家族律）
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
                # 联程混淆码守卫：段内存在不合规号（「华夏航
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
                # 名行自带机型：DOM 名行「春秋9C8866 空客321(中)」
                # 实证 40 行含机型 token，整段只取航班号即造成 plane 98%
                # 缺口——名行机型是单渠道自源修复主力（快照统计 波音737(中)×25/
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
        # _via 写入端根治（fliggy 同律 r223）：DOM 状态机内部哨兵不得随行
        # 出解析器——「停」直落 stopover，「转」已由状态机直落 transCity
        # 无残留键；normalize 读层 pop 保持双保险（幂等不翻转已定语义）
        for f in out:
            if f.pop("_via", None) == "停":
                f["stopover"] = True
        # 幻影价守卫（fliggy 中位锚同思想移植）：明细中位数作
        # 群体锚，单行价 < 中位×0.5 视为页面异源模块污染弃行。本路径流式
        # 形态（价格行即 close、第二价格行静默丢弃）必须有群体防线兜底：页面尾部
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
