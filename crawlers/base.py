"""爬虫基类：Playwright 持久化上下文 + 反爬基础处理 + XHR拦截"""
import os
import re
import json
import random
import time
import logging
import tempfile
import threading
from contextlib import contextmanager
from typing import List, Optional, Callable

from playwright.sync_api import sync_playwright, BrowserContext, Page, Response

from core.models import PRICE_MAX, PRICE_MIN, FlightPrice
from core.intl import tz_offset_min


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROFILE_LOCKS = {}
_PROFILE_LOCKS_GUARD = threading.Lock()


# 采集/探针共用：全局最多 2 个渠道浏览器，同渠道串行。调度器与探针
# 都必须走同一组闸门，否则两边叠加仍会同时开 4-5 个浏览器触发验证。
CHANNEL_GATE = threading.BoundedSemaphore(2)
_PLATFORM_LOCKS = {}
_PLATFORM_LOCKS_GUARD = threading.Lock()


def platform_lock(platform: str) -> threading.Lock:
    key = str(platform or "default")
    with _PLATFORM_LOCKS_GUARD:
        lock = _PLATFORM_LOCKS.get(key)
        if lock is None:
            lock = _PLATFORM_LOCKS[key] = threading.Lock()
        return lock


@contextmanager
def channel_slot(platform: str):
    # 统一 global→platform 顺序，避免与探针的嵌套锁顺序相反造成死锁。
    with CHANNEL_GATE:
        with platform_lock(platform):
            yield


class SessionBusyError(RuntimeError):
    """同一渠道资料目录正由登录或采集使用。"""


# 桌面/手机 UA
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/16.6 Mobile/15E148 Safari/604.1")


def iata3(v) -> str:
    """机场 IATA 三字码守卫（H1，qunar/tuniu/ctrip 三源同律）：
    ^[A-Z]{3}$ fullmatch，不匹配不落——空串/小写/中文/数字内部 id 一律
    挡（宁缺勿错，同 prate=20 占位守卫先例）。SHA 机场/城市双义警告在
    案：本键语义=机场级，消费端勿当城市码用。"""
    s = str(v or "").strip()
    return s if re.fullmatch(r"[A-Z]{3}", s) else ""


def iata2(v) -> str:
    """航司 IATA 二字码守卫（qunar shortCarrier / tuniu airlineIataCode
    跨渠道统一出口键 airlineCode，iata3 同律）：^[A-Z0-9]{2}$ fullmatch，
    不匹配不落——小写/三位/空串一律挡。数字参位合法（3U 川航/G5 华夏）。"""
    s = str(v or "").strip()
    return s if re.fullmatch(r"[A-Z0-9]{2}", s) else ""


class BaseCrawler:
    name: str = "base"
    # 子类覆盖：是否使用手机端模拟
    use_mobile: bool = False
    # 登录窗口是否保留手机模拟（淘宝 H5 等手机域需要；桌面渠道保持
    # False 以便鼠标操作滑块/点选验证）
    login_mobile: bool = False
    # H5 数据路径可复用独立登录槽位的 profile，而平台名仍保持 fliggy
    profile_name: str = ""
    # 会话失效证据标记（类级：实例每轮新建，实例级存不住）：最近采集
    # 被服务端按未登录处理时置 True，成功拿到数据即清（恢复自愈，
    # 进程重启复位=重启后无失效证据）。控制台登录态卡片读它分层——
    # 本地会话档案在（saved）而标记在场时显示「会话可能失效」
    login_suspect: bool = False

    # ── 采集链路观测（PC/H5/API/日历 逐路径尝试账本）──
    # 只记代码真实走过的尝试，不按结果反推路径；探针面板与渠道状态共用。
    PATH_STATUS = ("ok", "empty", "login", "blocked", "timeout",
                   "error", "parse_error", "unsupported", "calendar")

    def path_reset(self):
        self.paths = []
        self.last_path = ""
        self.last_status = ""

    def path_note(self, path: str, status: str, rows: int = 0,
                  date: str = "", detail: str = "", ms: int = 0):
        if status not in self.PATH_STATUS:
            status = "error"
        rec = {"path": str(path), "status": status,
               "rows": int(rows or 0), "date": str(date or ""),
               "detail": str(detail or "")[:160], "ms": int(ms or 0)}
        if not hasattr(self, "paths"):
            self.path_reset()
        self.paths.append(rec)
        self.last_path = rec["path"]
        self.last_status = rec["status"]
        cb = getattr(self, "on_path", None)
        if cb:
            try:
                cb(rec)
            except Exception:
                pass
        return rec

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.headless: bool = config.get("headless", True)
        # 用户主动探针可复用可见会话取明细；定时监控不弹窗。
        self.probe_mode: bool = False
        self.timeout_ms: int = int(config.get("timeout_seconds", 45)) * 1000
        self.delay_min: float = float(config.get("delay_min", 2))
        self.delay_max: float = float(config.get("delay_max", 5))
        self.debug: bool = bool(config.get("debug", False))
        self.debug_dir: str = config.get("debug_dir", "debug")
        root = str(config.get("user_data_dir") or "user_data").strip() or "user_data"
        self.user_data_root = os.path.abspath(os.path.join(_REPO_ROOT, root))
        # 可选本地代理（r319，如 Clash http://127.0.0.1:7897）：浏览器与
        # httpx 采集面统一走它，让出口 IP 可变（IP 级限流绕行）。注意
        # 国内站+境外出口=风控风险升档，建议国内直落节点或负载均衡组
        self.proxy: str = str(config.get("proxy", "") or "").strip()

    # ---------- 浏览器 ----------
    @property
    def user_data_dir(self) -> str:
        # 不同平台/登录槽位不同目录，避免互相污染
        path = os.path.join(self.user_data_root,
                            self.profile_name or self.name)
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def session_state_path(self) -> str:
        return os.path.join(self.user_data_root,
                            self.profile_name or self.name,
                            "session-state.json")

    def _read_session_state(self) -> dict:
        try:
            with open(self.session_state_path, encoding="utf-8") as f:
                state = json.load(f)
            return state if isinstance(state, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            self.logger.warning("[%s] 无法读取会话快照", self.name)
            return {}

    @property
    def session_saved_at(self) -> float:
        """明确确认登录并保存的时刻；旧 profile 迁移不算重新登录。"""
        try:
            return float(self._read_session_state().get("saved_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _write_session_state(self, state: dict, saved_at: float):
        state = dict(state, saved_at=saved_at)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.user_data_dir,
                    prefix=".session-state-", suffix=".tmp", delete=False) as f:
                tmp = f.name
                json.dump(state, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.session_state_path)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def load_session_cookies(self, domains=None) -> list:
        """读取最新快照，保留 Cookie 的域、路径和期限，不缓存认证值。"""
        if not os.path.isfile(self.session_state_path) and os.path.isdir(
                os.path.join(self.user_data_root, self.name, "Default")):
            # 既有用户无需重登：首次 HTTP 采集导出 Chromium 已存会话。
            # 仅迁移快照，不设置新登录时间，也不代表渠道已接受会话。
            with self.browser(headless=True, save_session="migrate"):
                pass
        state = self._read_session_state()
        domains = [domains] if isinstance(domains, str) else domains
        allowed = [str(d).lower().lstrip(".") for d in domains or []]
        now = time.time()
        cookies = []
        for c in state.get("cookies") or []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            domain = str(c.get("domain") or "").lower().lstrip(".")
            if allowed and not any(domain == d or domain.endswith("." + d)
                                   for d in allowed):
                continue
            try:
                expiry = float(c.get("expires", -1))
            except (TypeError, ValueError):
                continue
            if expiry >= 0 and expiry <= now:
                continue
            cookies.append(dict(c))
        return cookies

    def _ua(self) -> str:
        if self.use_mobile:
            return self.config.get("mobile_user_agent") or MOBILE_UA
        return self.config.get("user_agent") or DESKTOP_UA

    def _viewport(self) -> dict:
        if self.use_mobile:
            return {"width": 390, "height": 844}
        return {"width": 1366, "height": 900}

    @contextmanager
    def browser(self, headless: Optional[bool] = None,
                window_front: bool = False, window_idx: int = 0,
                save_session: Optional[str] = None):
        """启动持久化浏览器上下文。headless=None 时使用配置。"""
        path = os.path.normcase(os.path.realpath(self.user_data_dir))
        with _PROFILE_LOCKS_GUARD:
            lock = _PROFILE_LOCKS.setdefault(path, threading.Lock())
        if not lock.acquire(blocking=False):
            raise SessionBusyError(
                "[%s] 会话正在登录或采集，请完成当前操作后重试" % self.name)
        try:
            with self._browser_context(headless, window_front, window_idx,
                                       save_session) as ctx:
                yield ctx
        finally:
            lock.release()

    @contextmanager
    def _browser_context(self, headless, window_front, window_idx, save_session):
        hl = self.headless if headless is None else headless
        with sync_playwright() as p:
            x, y = 40 + window_idx * 170, 24 + window_idx * 150
            launch_args = [f"--window-position={x},{y}"]
            if window_front:
                launch_args += [f"--window-size=1180,760",
                                f"--window-position={x},{y}"]
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=hl,
                user_agent=self._ua(),
                viewport=self._viewport(),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                is_mobile=self.use_mobile,
                has_touch=self.use_mobile,
                # 可选本地代理（r319）：全部渠道采集出口统一走它
                proxy=({"server": self.proxy} if self.proxy else None),
                args=launch_args + [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                # Chromium 重开可能丢弃 expires=-1 的会话 Cookie；只补
                # profile 缺少的键，避免旧快照覆盖站点已更新的持久 Cookie。
                if os.path.isfile(self.session_state_path):
                    saved = self.load_session_cookies()
                    if saved:
                        key = lambda c: (c["name"], c["domain"], c.get("path", "/"))
                        existing = {key(c) for c in ctx.cookies()}
                        missing = [c for c in saved if key(c) not in existing]
                        if missing:
                            ctx.add_cookies(missing)
                yield ctx
                state = ctx.storage_state() if save_session else None
            finally:
                ctx.close()
            # 保存、关闭、发布必须全部成功，调用方才能报告登录已保存。
            if state is not None:
                saved_at = time.time() if save_session == "login" else self.session_saved_at
                self._write_session_state(state, saved_at)

    def new_page(self, ctx: BrowserContext) -> Page:
        page = ctx.new_page()
        page.set_default_timeout(self.timeout_ms)
        page.set_default_navigation_timeout(self.timeout_ms)
        return page

    # ---------- 工具 ----------
    def _sleep(self):
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def _debug_snapshot(self, page: Page, tag: str, extra_text: str = None):
        """extra_text 在场时另落 {base}.txt——存「解析器实际吃的文本流」
        而非 DOM 壳（innerText 是渲染态产物，page.content() 里没有，
        存壳的 dump 冻结回放结构性 0 行命中）；每轮覆盖写不膨胀。"""
        if not self.debug:
            return
        try:
            os.makedirs(self.debug_dir, exist_ok=True)
            base = os.path.join(self.debug_dir, f"{self.name}_{tag}")
            try:
                page.screenshot(path=base + ".png", full_page=True)
            except Exception:
                pass
            try:
                with open(base + ".html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            except Exception:
                pass
            if extra_text:
                try:
                    with open(base + ".txt", "w", encoding="utf-8") as f:
                        f.write(extra_text)
                except Exception:
                    pass
            self.logger.info("[%s] 已保存调试快照: %s.{png,html%s}",
                             self.name, base, ",txt" if extra_text else "")
        except Exception as e:
            self.logger.warning("[%s] 保存快照失败: %s", self.name, e)

    # ---------- XHR 拦截：通用工具 ----------
    def attach_xhr_collector(self, page: Page, url_patterns: List[str]):
        """监听匹配的 XHR/Fetch 响应，缓存其 JSON 文本。

        返回一个 list，调用方在抓取过程中读取它。
        """
        captured: list = []

        def on_response(resp: Response):
            try:
                url = resp.url
                if not any(p in url for p in url_patterns):
                    return
                # 仅尝试 JSON
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct and not url.endswith(".json"):
                    # 也允许文本，部分平台返回 application/javascript
                    pass
                try:
                    text = resp.text()
                except Exception:
                    return
                captured.append({"url": url, "text": text})
            except Exception:
                pass

        page.on("response", on_response)
        return captured

    @staticmethod
    def extract_prices_from_text(text: str) -> List[int]:
        """从任意文本/JSON 字符串中抽取看起来像机票价格的数字。

        优先级：lowestPrice / salePrice / TotalPrice 等"含税总价"字段；
        退一步再用 price / adultPrice / minPrice；
        最后兜底从 ￥xxxx 文本里取。
        """
        prices: list = []
        if not text:
            return prices

        # 第 1 档：明确的最低价/销售总价字段（最可信）
        for m in re.finditer(
            r'"(lowestPrice|salePrice|TotalPrice|displayPrice|cabinTotalPrice)"\s*:\s*"?(\d{3,5})',
            text,
        ):
            try:
                prices.append(int(m.group(2)))
            except Exception:
                pass
        if prices:
            return [p for p in prices if PRICE_MIN <= p <= PRICE_MAX]

        # 第 2 档：通用价格字段（飞猪 H5 里 price/totalPrice 可能是附加产品价，谨慎）
        for m in re.finditer(
            r'"(minPrice|adultPrice|Price)"\s*:\s*"?(\d{3,5})',
            text,
        ):
            try:
                prices.append(int(m.group(2)))
            except Exception:
                pass
        if prices:
            return [p for p in prices if PRICE_MIN <= p <= PRICE_MAX]

        # 第 3 档：兜底，￥xxx 文本
        for m in re.finditer(r"[￥￥]\s*(\d{3,5})", text):
            prices.append(int(m.group(1)))
        return [p for p in prices if PRICE_MIN <= p <= PRICE_MAX]

    # ---------- 子类必须实现 ----------
    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        raise NotImplementedError

    def login_url(self) -> str:
        """登录引导页 URL，被 --login 模式使用。"""
        raise NotImplementedError

    # ---------- 国际支线公共能力（r325，INTL_DESIGN §1.2）----------
    def _stamp_intl(self, flights: list, fc: str, tc: str) -> None:
        """国际元素戳（就地）：intl=1（共享消费端国际档开关：价带
        宽带/免税垫/到达窗泛化/跨天扩档）+ 跨区时区对（两端偏移已知
        且不同才落 tz_dep/tz_arr——同区对朴素差本就正确，落键白占
        schema；flightnorm 国际档凭键修正 naive 渠道时长，无键信渠道）。
        时区按各行航班日取 DST 真历法（r326：抓取时刻印章对跨 DST
        航班日错 60min——SHA→CAI/FRA 抓取日夏令时而航班日已冬令时，
        211 行系统差实证）。"""
        for _f in flights:
            _when = str(_f.get("depDate") or "").strip() or None
            _tz_dep = tz_offset_min(fc, when=_when)
            _tz_arr = tz_offset_min(tc, when=_when)
            _f["intl"] = 1
            if (_tz_dep is not None and _tz_arr is not None
                    and _tz_dep != _tz_arr):
                _f["tz_dep"] = _tz_dep
                _f["tz_arr"] = _tz_arr

    # ---------- 公共调用入口 ----------
    def safe_fetch(self, from_city: str, to_city: str, dates: List[str],
                   ret_date: str = "") -> List[FlightPrice]:
        try:
            self.logger.info("[%s] 开始抓取 %s->%s 日期=%s",
                             self.name, from_city, to_city, dates)
            results = self.fetch(from_city, to_city, dates,
                                 ret_date=ret_date) or []
            self.logger.info("[%s] 抓取完成，得到 %d 条记录", self.name, len(results))
            return results
        except Exception as e:
            self.logger.exception("[%s] 抓取失败: %s", self.name, e)
            return []

    # ---------- 登录模式 ----------
    def interactive_login(self):
        """打开可见浏览器引导用户登录，按回车后保存会话退出。

        登录一律用桌面视口：手机模拟（is_mobile/touch）下鼠标拖滑块
        验证码经常失灵（页面监听 touch 事件）——cookie 同域通用，
        采集时仍用各自视口不受影响。"""
        url = self.login_url()
        self.logger.info("[%s] 启动登录浏览器（桌面视口）：%s", self.name, url)
        bak = self.use_mobile
        self.use_mobile = False
        try:
            self._interactive_login_inner(url)
        finally:
            self.use_mobile = bak

    def _login_window(self, done_evt, idx: int = 0, timeout_s: float = 0):
        """并行登录窗口：开登录页保持打开，done_evt 置位后关闭。
        idx 用于阶梯排布窗口位置避免叠死；timeout_s=0 表示不超时
        （命令行 --login 由用户决定），Web 登录传 600 秒。"""
        url = self.login_url()
        self.logger.info("[%s] 登录窗口已打开：%s", self.name, url)
        bak = self.use_mobile
        if not self.login_mobile:
            self.use_mobile = False
        try:
            with self.browser(headless=False, window_front=True,
                              window_idx=idx, save_session="login") as ctx:
                page = self.new_page(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                import time as _t
                deadline = (_t.time() + timeout_s) if timeout_s else 0.0
                while not done_evt.is_set():
                    if deadline and _t.time() >= deadline:
                        raise RuntimeError("登录窗口超时，请重新打开")
                    try:
                        closed = bool(page.is_closed())
                    except Exception:
                        closed = True
                    if closed:
                        raise RuntimeError("登录窗口已关闭，未保存会话")
                    _t.sleep(0.5)
            self.logger.info("[%s] 会话已保存到 %s", self.name, self.user_data_dir)
        finally:
            self.use_mobile = bak

    def open_challenge_window(self, url: str, done_evt,
                              timeout_s: float = 300, idx: int = 0):
        """Open the challenged page in a visible desktop window.

        The operator solves the challenge; this method only waits for the
        close/verify signal and persists the resulting session. It never
        drives the challenge. idx staggers multiple windows.
        """
        self.logger.info("[%s] 验证窗口已打开：%s", self.name, url)
        bak = self.use_mobile
        if not self.login_mobile:
            self.use_mobile = False
        try:
            with self.browser(headless=False, window_front=True,
                              window_idx=idx, save_session="login") as ctx:
                page = self.new_page(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                import time as _t
                deadline = (_t.time() + timeout_s) if timeout_s else 0.0
                while not done_evt.is_set():
                    if deadline and _t.time() >= deadline:
                        raise RuntimeError("验证窗口超时，请重新打开")
                    try:
                        closed = bool(page.is_closed())
                    except Exception:
                        closed = True
                    if closed:
                        raise RuntimeError("验证窗口已关闭，未保存会话")
                    _t.sleep(0.5)
            self.logger.info("[%s] 验证会话已保存到 %s",
                             self.name, self.user_data_dir)
        finally:
            self.use_mobile = bak

    def _interactive_login_inner(self, url: str):
        with self.browser(headless=False, window_front=True,
                          save_session="login") as ctx:
            page = self.new_page(ctx)
            page.goto(url, wait_until="domcontentloaded")
            print()
            print("=" * 60)
            print(f"  请在浏览器里完成 [{self.name}] 登录（手机号验证码等）。")
            print(f"  登录完成后回到这里，按 Enter 保存会话并关闭浏览器。")
            print("=" * 60)
            try:
                input(">>> 完成后按 Enter：")
            except EOFError:
                time.sleep(60)
        self.logger.info("[%s] 会话已保存到 %s", self.name, self.user_data_dir)
