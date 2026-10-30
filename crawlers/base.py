"""爬虫基类：Playwright 持久化上下文 + 反爬基础处理 + XHR拦截"""
import os
import sys
import re
import json
import random
import time
import logging
import tempfile
import threading
import zlib
from contextlib import contextmanager
from typing import List, Optional, Callable

from playwright.sync_api import sync_playwright, BrowserContext, Page, Response

from core.models import PRICE_MAX, PRICE_MIN, FlightPrice
from core.intl import tz_offset_min
from core.pacing import parse_retry_after, should_watch_response


# 冻结态用 exe 所在目录：否则 user_data（登录态）会落进 _internal，
# 用户找不到、升级即丢。与 main.py 同源（core.paths.app_root）。
if getattr(sys, "frozen", False):
    from core.paths import app_root as _app_root
    _REPO_ROOT = _app_root()
else:
    _REPO_ROOT = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
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
    # 先拿渠道锁，再拿全局浏览器配额。反过来的话，一个渠道在等自家
    # 锁时会一直占着全局配额，两个这样的等待者就能把其余渠道全堵死
    # （头阻塞）；先渠道后全局不会成环，因为没有任何线程跨渠道持锁。
    lock = platform_lock(platform)
    with lock:
        with CHANNEL_GATE:
            yield


class SessionBusyError(RuntimeError):
    """同一渠道资料目录正由登录或采集使用。"""


# 桌面/手机 UA
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")
_KERNEL_MAJOR = [0]
_KERNEL_LOCK = threading.Lock()


def kernel_major() -> int:
    """本机 Playwright Chromium 的真实主版本（带磁盘缓存）。

    用途只有一个：让 UA 里的 Chrome/xx 与真实内核一致。首次调用会起一次
    无头浏览器读 version（约 1 秒），之后读 data/.kernel_major。
    失败返回 0（调用方退回原 UA，不阻塞采集）。
    """
    if _KERNEL_MAJOR[0]:
        return _KERNEL_MAJOR[0]
    with _KERNEL_LOCK:
        if _KERNEL_MAJOR[0]:
            return _KERNEL_MAJOR[0]
        cache = os.path.join("data", ".kernel_major")
        try:
            with open(cache, encoding="utf-8") as f:
                v = int((f.read() or "0").strip() or 0)
            if v > 0:
                _KERNEL_MAJOR[0] = v
                return v
        except (OSError, ValueError):
            pass
        v = 0
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch(headless=True)
                v = int(str(b.version or "0").split(".")[0] or 0)
                b.close()
        except Exception:
            v = 0
        if v > 0:
            _KERNEL_MAJOR[0] = v
            try:
                os.makedirs("data", exist_ok=True)
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(str(v))
            except OSError:
                pass
        return v


MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/16.6 Mobile/15E148 Safari/604.1")

# 本地指纹一致性（crawler.stealth，默认开）：
# 只抹掉「这是自动化浏览器」的显式标记，让页面看到一个普通 Chrome；
# 不伪造账号、不破解验证、不改 IP。缺了它，同一份 UA/视口也会因为
# navigator.webdriver=true 被直接降档——这是误判，不是我们在伪装身份。
STEALTH_JS = r"""
(() => {
  try { Object.defineProperty(Navigator.prototype, 'webdriver',
        {get: () => undefined, configurable: true}); } catch (e) {}
  try { if (__ADDCHROME__ && !window.chrome) { window.chrome = {runtime: {}}; } } catch (e) {}
  try { Object.defineProperty(navigator, 'languages',
        {get: () => ['zh-CN', 'zh'], configurable: true}); } catch (e) {}
  try {
    const q = navigator.permissions && navigator.permissions.query;
    if (q) {
      navigator.permissions.query = (p) =>
        (p && p.name === 'notifications')
          ? Promise.resolve({state: Notification.permission})
          : q.call(navigator.permissions, p);
    }
  } catch (e) {}
  try { Object.defineProperty(navigator, 'hardwareConcurrency',
        {get: () => __CORES__, configurable: true}); } catch (e) {}
  try { Object.defineProperty(navigator, 'deviceMemory',
        {get: () => __MEM__, configurable: true}); } catch (e) {}
  try { Object.defineProperty(navigator, 'platform',
        {get: () => '__PLAT__', configurable: true}); } catch (e) {}

  // WebGL：把调试扩展里"真实显卡"换成一台普通办公机（UNMASKED_* 是
  // 最常被拿去做指纹的两个参数，headless 默认值（SwiftShader）几乎是
  // 自报家门）。
  const VENDOR = '__GLV__';
  const RENDERER = '__GLR__';
  const patchGL = (proto) => {
    if (!proto) return;
    const orig = proto.getParameter;
    if (!orig) return;
    proto.getParameter = function (p) {
      if (p === 37445) return VENDOR;    // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return RENDERER;  // UNMASKED_RENDERER_WEBGL
      return orig.apply(this, arguments);
    };
    const origExt = proto.getSupportedExtensions;
    if (origExt) {
      proto.getSupportedExtensions = function () {
        const list = origExt.apply(this, arguments) || [];
        if (list.indexOf('WEBGL_debug_renderer_info') < 0) {
          list.push('WEBGL_debug_renderer_info');
        }
        return list;
      };
    }
  };
  try { patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype); } catch (e) {}
  try { patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype); } catch (e) {}

  // Canvas：确定性微扰（同一 profile 每次一致、不同 profile 不同）。
  // 只动 getImageData 的抽样像素（±1），肉眼不可见、不影响渲染，但让
  // "canvas 哈希"不再是跨会话稳定的唯一标识。用随机数反而更可疑：
  // 同一会话两次读数不一致，本身就是机器特征。
  try {
    const SEED = __SEED__;
    const origGet = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function () {
      const d = origGet.apply(this, arguments);
      try {
        const a = d.data;
        for (let i = 0; i < a.length; i += 997) {
          a[i] = (a[i] + ((SEED + i) % 3) - 1) & 255;
        }
      } catch (e) {}
      return d;
    };
  } catch (e) {}
})();
"""


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
                   "error", "parse_error", "unsupported", "calendar",
                   "soft_reject")

    def path_reset(self):
        self.paths = []
        self.last_path = ""
        self.last_status = ""

    def path_note(self, path: str, status: str, rows: int = 0,
                  date: str = "", detail: str = "", ms: int = 0,
                  http_status: int = 0, url: str = ""):
        if status not in self.PATH_STATUS:
            status = "error"
        rec = {"path": str(path), "status": status,
               "rows": int(rows or 0), "date": str(date or ""),
               "detail": str(detail or "")[:160], "ms": int(ms or 0),
               # HTTP 状态入账：200 空、202 软拒、444 关连接、403/429
               # 的处置完全不同，只有状态码能事后区分。
               "http": int(http_status or 0),
               # 记录当时是 PC 还是 H5 身份：验证窗口必须复用同一条
               # 路径的 UA/视口，否则"换个身份去过验证"会制造新指纹。
               "mobile": bool(getattr(self, "use_mobile", False))}
        # 请求 URL 入账（r396）：账本 request_url 列此前从没被写过
        # （实测 601/601 全空），"这条路径到底打了哪个地址"只能靠
        # 截图猜。由调用方显式传自己真实使用的 URL——不让本函数拿
        # `_last_page` 兜底，那可能是上一条路径遗留的页面（同一轮里
        # H5 浏览器失败后接 httpx，页面早已关闭），会把 A 路径的
        # 地址记到 B 路径头上。
        if url:
            rec["url"] = str(url)[:500]
        if not hasattr(self, "paths"):
            self.path_reset()
        self.paths.append(rec)
        self.last_path = rec["path"]
        self.last_status = rec["status"]
        # 被拦/登录墙往往返回 200 页面而不是 403：只在响应监听里记现场
        # 会漏掉最常见的人机验证。path_note 是各渠道确认"这条路过不去"
        # 的统一落点，在这里补页面 URL（调用方没显式给 url 时才用页面
        # 兜底），截图仍由上下文收尾统一落盘。
        if rec["status"] in ("blocked", "login", "soft_reject"):
            try:
                page = getattr(self, "_last_page", None)
                purl = str(getattr(page, "url", "") or "") if page else ""
                if purl and purl != "about:blank":
                    if not rec.get("url"):
                        rec["url"] = purl[:500]
                    if not self.last_block_url:
                        self.last_block_url = purl[:500]
                    if not self._scene_pending:
                        self._scene_pending = purl[:500]
            except Exception:
                pass
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
        # 按渠道绑出口（6 区）：proxy_map 优先于全局 proxy。
        # 多网卡/Clash 多监听端口/策略组时，让不同渠道走不同出口，
        # 一家被限流不牵连另一家。空=回全局 proxy（空=直连）。
        _pmap = config.get("proxy_map") or {}
        if isinstance(_pmap, dict) and str(_pmap.get(self.name) or "").strip():
            self.proxy = str(_pmap[self.name]).strip()
        # 会话年龄看门狗：profile 太久没更新会被站点当"新设备"，超过
        # N 天时强制预热一次（0=关闭）
        try:
            self.session_max_days = max(0, int(
                config.get("session_max_days", 0) or 0))
        except (TypeError, ValueError):
            self.session_max_days = 0
        # 指纹一致性（默认开）：关掉它 = 保留 navigator.webdriver 等自动化标记
        self.stealth: bool = bool(config.get("stealth", True))
        # 登录窗口默认沿用该 profile 自己的 PC/H5 身份；只有显式开启
        # login_desktop 才强制桌面（手机 profile 上滑块更难拖时的退路，
        # 代价是登录与采集指纹不一致）。
        self.login_desktop: bool = bool(config.get("login_desktop", False))

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
    def session_age_days(self) -> float:
        """会话距上次保存的天数（无快照=0，视作待建立不算老化）。"""
        ts = 0.0
        try:
            ts = float(self.session_saved_at or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts <= 0:
            return 0.0
        return max(0.0, (time.time() - ts) / 86400.0)

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
        ua = ((self.config.get("mobile_user_agent") or MOBILE_UA)
              if self.use_mobile
              else (self.config.get("user_agent") or DESKTOP_UA))
        if not self.stealth:
            return ua
        maj = kernel_major()
        if not maj:
            return ua
        # UA 里的 Chrome/126 与真实内核 151 不一致，本身就是一条高熵
        # 矛盾特征（UA-CH / 特性检测任一条都能看出来）。统一成真实主版本。
        if "Chrome/" in ua:
            import re as _re
            return _re.sub(r"Chrome/\d+(?:\.\d+)*",
                           "Chrome/%d.0.0.0" % maj, ua)
        return ua

    def _viewport(self) -> dict:
        if self.use_mobile:
            return {"width": 390, "height": 844}
        return {"width": 1366, "height": 900}

    def fingerprint(self) -> dict:
        """采集/预热/自检/验证窗口共用的浏览器身份参数（单一来源）。

        headless 与窗口位置属于"怎么显示"，不进入身份；UA、视口、移动
        标记、locale/timezone、出口代理与 canvas 种子必须一致——同一
        profile 在采集和人工验证里呈现两套身份，本身就会被风控当成
        会话被接管。
        """
        return {
            "ua": self._ua(),
            "viewport": self._viewport(),
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
            "is_mobile": bool(self.use_mobile),
            "has_touch": bool(self.use_mobile),
            "proxy": self.proxy,
            "stealth": bool(self.stealth),
            "seed": zlib.crc32(
                (self.profile_name or self.name).encode("utf-8")) % 997,
        }

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
        fp = self.fingerprint()
        with sync_playwright() as p:
            x, y = 40 + window_idx * 170, 24 + window_idx * 150
            launch_args = [f"--window-position={x},{y}"]
            if window_front:
                launch_args += [f"--window-size=1180,760",
                                f"--window-position={x},{y}"]
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=hl,
                user_agent=fp["ua"],
                viewport=fp["viewport"],
                locale=fp["locale"],
                timezone_id=fp["timezone"],
                is_mobile=fp["is_mobile"],
                has_touch=fp["has_touch"],
                # 可选本地代理（r319）：全部渠道采集出口统一走它
                proxy=({"server": fp["proxy"]} if fp["proxy"] else None),
                args=launch_args + [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ] + (["--disable-blink-features=AutomationControlled"]
                     if fp["stealth"] else []),
            )
            if fp["stealth"]:
                try:
                    # 种子按 profile 固定：同一档案跨重启指纹一致（像真人），
                    # 不同档案互不相同（不把多个身份缝成同一个）
                    if fp["is_mobile"]:
                        # iPhone + Safari UA 上不该存在 window.chrome，
                        # 加了反而是矛盾特征（Chromium 专属对象出现在 WebKit UA 里）
                        _rep = {"__PLAT__": "iPhone", "__CORES__": "6",
                                "__MEM__": "4", "__GLV__": "Apple Inc.",
                                "__GLR__": "Apple GPU", "__ADDCHROME__": "false"}
                    else:
                        _rep = {"__PLAT__": "Win32", "__CORES__": "8",
                                "__MEM__": "8", "__GLV__": "Intel Inc.",
                                "__ADDCHROME__": "true",
                                "__GLR__": ("ANGLE (Intel, Intel(R) UHD "
                                            "Graphics 630 Direct3D11 vs_5_0 "
                                            "ps_5_0, D3D11)")}
                    _rep["__SEED__"] = str(fp["seed"])
                    _js = STEALTH_JS
                    for _k, _v in _rep.items():
                        _js = _js.replace(_k, _v)
                    ctx.add_init_script(_js)
                except Exception:
                    pass
            state = None
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
                try:
                    state = ctx.storage_state() if save_session else None
                except Exception as e:
                    # 验证窗口关得太快时上下文可能已经关闭；若周期快照
                    # 已成功，可以安全忽略收尾失败。登录窗口没有任何快照
                    # 成功过时必须抛出——否则会把"没保存"报成"已保存"。
                    if save_session == "login" and not self._session_snap_ok:
                        raise
                    state = None
                    if save_session:
                        self.logger.warning("[%s] 会话收尾快照失败: %s",
                                            self.name, e)
            finally:
                # 被拒页面在关上下文前落盘：同一个采集线程、同一个 page，
                # 是 Playwright sync 唯一安全的截图时机
                try:
                    if self._scene_pending:
                        self.capture_scene(self._last_page, tag="block")
                except Exception:
                    pass
                ctx.close()
            # 保存、关闭、发布必须全部成功，调用方才能报告登录已保存。
            if state is not None:
                saved_at = time.time() if save_session == "login" else self.session_saved_at
                self._write_session_state(state, saved_at)

    def new_page(self, ctx: BrowserContext) -> Page:
        page = ctx.new_page()
        page.set_default_timeout(self.timeout_ms)
        page.set_default_navigation_timeout(self.timeout_ms)
        self._last_page = page
        self._watch_retry_after(page)
        return page

    # ---------- 风控信号：服务端让我们等多久（2 区）----------
    # 最近一次 429/503 响应里的 Retry-After 秒数；main 采集落地后读它，
    # 交给熔断器优先采用——比自算的 2^n 阶梯更接近对方真实配额。
    retry_after_s: int = 0
    # 最近一次被拒的现场 URL（403/429/503 时由响应监听记住）：
    # 「去验证」直接打开它，而不是让用户从首页重新找一遍
    last_block_url: str = ""
    # 若是 XHR/fetch 被拒，另外记住接口 URL；网页窗口打开的是页面地址，
    # 不是 JSON 接口（把接口地址端到人面前没法过验证）
    last_block_api: str = ""
    # 最近一次查询（main 写入）：重建入口 URL / 现场说明用
    last_query: tuple = ()
    # 现场归档（5 区 2.0）：被拒页面的截图/URL/标题留档
    _scene_pending: str = ""
    # 软拒现场（202 空体/444）：与 blocked 分开，避免把"会话没养好"
    # 当成"IP 被限流"或"真无票"。
    last_soft_reject: dict = {}
    _soft_pending: bool = False
    _last_page = None
    last_scene: dict = {}
    # 预热入口（子类覆盖）：空=该渠道在 fetch 内部自带预热（ctrip/同程）
    warmup_url: str = ""
    warmup_done_at: float = 0.0
    # 预热成功的判据（子类声明风控 cookie 名；空=不判，避免误报）
    RISK_COOKIES: tuple = ()
    warmup_cookie_ok: bool = True
    warmup_cookies: list = []
    # 本次登录/验证窗口是否已成功落过一次周期快照。有它时，关窗后
    # 收尾 storage_state 失败可以安全忽略；没有它就必须把错误抛给
    # 调用方——不能把"没保存"报成"已保存"。
    _session_snap_ok: bool = False

    def _watch_retry_after(self, page: Page):
        def _on_resp(resp):
            try:
                req = getattr(resp, "request", None)
                rtype = str(getattr(req, "resource_type", "") or "")
                url = str(resp.url or "")
                # 广告/统计/埋点的 403/429 不是渠道健康信号；只看文档
                # 与业务 XHR/fetch，避免第三方脚本把渠道误熔断。
                if not should_watch_response(rtype, url):
                    return
                if resp.status in (202, 444):
                    # 202 空体 / 444 关连接：不是"真无票"，是边缘/会话软拒。
                    # 记下来供主流程分层，不按 IP 限流熔断。
                    self.last_soft_reject = {
                        "code": int(resp.status),
                        "url": str(url or "")[:500],
                        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    self._soft_pending = True
                if resp.status in (403, 429, 503):
                    if rtype == "document":
                        target = url
                    else:
                        target = str(getattr(page, "url", "") or "")
                        if not target or target == "about:blank":
                            target = url
                        self.last_block_api = url[:500]
                    self.last_block_url = target[:500]
                    # 留现场：截图必须在本线程（Playwright sync 不跨线程），
                    # 这里只打标记，真正的落盘在 _browser_context 收尾处
                    self._scene_pending = target[:500]
                if resp.status not in (429, 503):
                    return
                hdr = resp.headers or {}
                raw = hdr.get("retry-after") or hdr.get("Retry-After") or ""
                sec = parse_retry_after(raw)
                if sec > 0:
                    self.retry_after_s = sec
                    self.logger.warning(
                        "[%s] 服务端 Retry-After=%ds（HTTP %d）"
                        "——本轮冷却按它来", self.name, sec, resp.status)
            except Exception:
                pass
        try:
            page.on("response", _on_resp)
        except Exception:
            pass

    def capture_scene(self, page=None, tag=""):
        """案发现场落盘：截图 + URL/标题 + 时间（人可看、可事后比对）。

        只能在采集线程里调用（Playwright sync API 跨线程会炸）；
        失败只记日志，绝不影响采集主流程。
        """
        page = page or self._last_page
        if page is None:
            return ""
        base = os.path.join("debug", "scene")
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            return ""
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = "%s_%s%s" % (self.name, stamp, ("_" + tag) if tag else "")
        png = os.path.join(base, name + ".png")
        meta = os.path.join(base, name + ".txt")
        try:
            page.screenshot(path=png, full_page=False)
        except Exception as e:
            self.logger.warning("[%s] 现场截图失败: %s", self.name, e)
        try:
            with open(meta, "w", encoding="utf-8") as f:
                f.write("url: %s\n" % getattr(page, "url", ""))
                try:
                    f.write("title: %s\n" % page.title())
                except Exception:
                    pass
                f.write("at: %s\nblock: %s\napi: %s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    self.last_block_url, self.last_block_api))
        except OSError:
            pass
        self.last_scene = {"png": png, "meta": meta,
                           "url": getattr(page, "url", "")}
        self._scene_pending = ""
        try:                       # 只留 7 天，防 debug/scene 无限膨胀
            cutoff = time.time() - 7 * 86400
            for fn in os.listdir(base):
                fp = os.path.join(base, fn)
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
        except OSError:
            pass
        return png

    def warmup(self, headless: bool = True) -> bool:
        """打一次首页让风控 JS 下发 cookie（调用方须已持 channel_slot）。

        已出数就预热等于白发请求，所以只由 main 在「本轮首次用到该渠道」
        时调一次；失败不抛，交给后续请求如实上报。
        """
        url = str(self.warmup_url or "").strip()
        if not url:
            return False
        t0 = time.time()
        try:
            with self.browser(headless=headless) as ctx:
                page = self.new_page(ctx)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                # 预热是否真的生效：看风控 cookie 有没有落下来。
                # 只看"访问过首页"等于没验证——深链仍会被当新会话。
                want = tuple(getattr(self, "RISK_COOKIES", ()) or ())
                if want:
                    try:
                        names = {c.get("name") for c in ctx.cookies()}
                        hit = [n for n in want if n in names]
                        self.warmup_cookies = hit
                        self.warmup_cookie_ok = bool(hit)
                        if not hit:
                            self.logger.warning(
                                "[%s] 预热未拿到风控 cookie（%s 均无），"
                                "深链大概率仍被拦", self.name, "/".join(want))
                    except Exception:
                        pass
            self.warmup_done_at = time.time()
            self.logger.info("[%s] 预热完成 %s（%.1fs）",
                             self.name, url, time.time() - t0)
            return True
        except SessionBusyError:
            self.logger.warning("[%s] 预热跳过：会话正被占用", self.name)
            return False
        except Exception as e:
            self.logger.warning("[%s] 预热失败: %s", self.name, e)
            return False

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
    # 最近一次采集是否因「同 profile 互斥」而让位（4 区会话卫生）：
    # 这是自家锁冲突，不是对方拒绝——main 据此跳过重试，避免裸 cookie
    # 连打把内部冲突升级成对方眼里的「新会话直捣深链」（444 之源）
    last_busy: bool = False

    def safe_fetch(self, from_city: str, to_city: str, dates: List[str],
                   ret_date: str = "") -> List[FlightPrice]:
        self.last_busy = False
        # 每次采集从零开始留证：上一轮的 blocked 路径、Retry-After、
        # 现场 URL 与截图都不能跨查询复用，否则一次早退/异常会把旧证据
        # 当成这一轮的拒绝原因，误熔断一个已经恢复的渠道。
        self.path_reset()
        self.retry_after_s = 0
        self.last_block_url = ""
        self.last_block_api = ""
        self._scene_pending = ""
        self.last_scene = {}
        self.last_soft_reject = {}
        self._soft_pending = False
        # 上一条查询的 page 不能留给本次截图/URL 兜底：httpx 直连路径
        # 不会 new_page，若不清空会把上一页截进本轮现场。
        self._last_page = None
        try:
            # 域标记入日志（r415）：健康面板此前只能按厂商聚合，同一家
            # 的国内与国际混成一个数——实报同程 13%，而它国际窗历当天
            # 全成功、国内 H5 全绿，看不出「哪一端坏了」。日志文本是健康
            # 解析的唯一数据源，域必须写在行首标记里才分得开。
            try:
                from core.intl import is_intl_route as _iir
                _scope = "国际" if _iir(from_city, to_city) else "国内"
            except Exception:
                _scope = ""
            self.logger.info("[%s] 开始抓取 %s->%s 日期=%s%s",
                             self.name, from_city, to_city, dates,
                             (" · " + _scope) if _scope else "")
            results = self.fetch(from_city, to_city, dates,
                                 ret_date=ret_date) or []
            self.logger.info("[%s] 抓取完成，得到 %d 条记录%s",
                             self.name, len(results),
                             (" · " + _scope) if _scope else "")
            return results
        except SessionBusyError as e:
            # 让位：不记异常栈（这是预期内的排队，不是故障），也不重试
            self.last_busy = True
            self.logger.warning("[%s] %s", self.name, e)
            return []
        except Exception as e:
            self.logger.exception("[%s] 抓取失败: %s", self.name, e)
            return []

    # ---------- 登录模式 ----------
    def interactive_login(self):
        """打开可见浏览器引导用户登录，按回车后保存会话退出。

        默认沿用 profile 自己的 PC/H5 身份（与采集一致）。若某些手机
        profile 的滑块无法用鼠标完成，可配置 crawler.login_desktop: true
        强制桌面视口；代价是登录指纹与采集指纹不同。"""
        url = self.login_url()
        self.logger.info("[%s] 启动登录浏览器（%s视口）：%s",
                         self.name,
                         "桌面" if not self.use_mobile else "移动",
                         url)
        bak = self.use_mobile
        if self.login_desktop and not self.login_mobile:
            self.use_mobile = False
        try:
            self._interactive_login_inner(url)
        finally:
            self.use_mobile = bak

    def _login_window(self, done_evt, idx: int = 0, timeout_s: float = 0,
                      ready_evt=None):
        """并行登录窗口：开登录页保持打开，done_evt 置位后关闭。

        返回 True=用户点击了「我已登录完成」；False=窗口被直接关闭
        （cookie 已周期快照，但未确认完成，调用方不得宣称登录成功）。
        idx 用于阶梯排布窗口位置避免叠死；timeout_s=0 表示不超时
        （命令行 --login 由用户决定），Web 登录传 600 秒。

        ready_evt（r620 · GitHub #10）：窗口**真的打开且登录页载入完成**
        之后置位。调用方（webui 的 /api/login）原先在线程启动后立刻回
        「已弹出」，但 Playwright 起不来（缺浏览器内核 / 显示服务异常 /
        profile 被占）时那一步永远到不了——用户等一个不存在的窗口，
        换八个浏览器都没用（issue 原话）。失败时本方法不置位，异常照常
        冒泡，由调用方把「没开成」如实回给点击者。
        """
        url = self.login_url()
        self.logger.info("[%s] 正在打开登录窗口：%s", self.name, url)
        self._session_snap_ok = False
        bak = self.use_mobile
        if self.login_desktop and not self.login_mobile:
            self.use_mobile = False
        try:
            with self.browser(headless=False, window_front=True,
                              window_idx=idx, save_session="login") as ctx:
                page = self.new_page(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                if ready_evt is not None:
                    # 到这里才是「窗口真的开了」；之前任何一步失败都不置位
                    ready_evt.set()
                self.logger.info("[%s] 登录窗口已打开：%s", self.name, url)
                import time as _t
                started_at = _t.time()
                deadline = (started_at + timeout_s) if timeout_s else 0.0
                keep_saved_at = self.session_saved_at or 0.0
                last_snap = 0.0
                while not done_evt.is_set():
                    if deadline and _t.time() >= deadline:
                        raise RuntimeError("登录窗口超时，请重新打开")
                    try:
                        closed = bool(page.is_closed())
                    except Exception:
                        closed = True
                    if closed:
                        # 关窗只落 cookie 快照，沿用旧 saved_at；随后抛错
                        # 让调用方明确「未确认」。不能在这里写 now——那会
                        # 把"关窗"伪装成"刚保存登录"，登录态卡片会说谎。
                        try:
                            state = ctx.storage_state()
                            if state:
                                self._write_session_state(state, keep_saved_at)
                                self._session_snap_ok = True
                        except Exception:
                            pass
                        self.logger.info("[%s] 登录窗口已关闭，cookie 快照已落盘"
                                         "（未确认，不判定登录成功）",
                                         self.name)
                        raise RuntimeError("登录窗口已关闭，尚未确认完成")
                    now = _t.time()
                    if now - last_snap >= 5:
                        try:
                            state = ctx.storage_state()
                            if state:
                                self._write_session_state(state, keep_saved_at)
                                self._session_snap_ok = True
                        except Exception:
                            pass
                        last_snap = now
                    _t.sleep(0.5)
            self.logger.info("[%s] 会话已保存到 %s", self.name, self.user_data_dir)
            return True
        finally:
            self.use_mobile = bak

    def open_challenge_window(self, url: str, done_evt,
                              timeout_s: float = 300, idx: int = 0):
        """Open the challenged page in a visible desktop window.

        The operator solves the challenge; this method only waits for the
        close/verify signal and persists the resulting session. It never
        drives the challenge. idx staggers multiple windows.

        Fingerprint idempotence: the window keeps the same mobile/desktop
        UA, viewport, locale, timezone, proxy and stealth seed as collection.
        Forcing a desktop UA on a mobile profile is a contradictory
        fingerprint and can itself trigger the challenge.
        """
        self.logger.info("[%s] 验证窗口已打开：%s", self.name, url)
        self._session_snap_ok = False
        with self.browser(headless=False, window_front=True,
                          window_idx=idx, save_session="login") as ctx:
            page = self.new_page(ctx)
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            import time as _t
            started_at = _t.time()
            deadline = (started_at + timeout_s) if timeout_s else 0.0
            # 周期快照沿用原 saved_at：只是防止关窗丢 cookie，不代表
            # "人已完成验证"；只有关窗正常返回时才把 saved_at 推到现在。
            keep_saved_at = self.session_saved_at or 0.0
            last_snap = 0.0
            while not done_evt.is_set():
                if deadline and _t.time() >= deadline:
                    raise RuntimeError("验证窗口超时，请重新打开")
                try:
                    closed = bool(page.is_closed())
                except Exception:
                    closed = True
                if closed:
                    # 关窗=人认为验证完成。上下文可能随窗口一起关闭，
                    # 所以先尝试最后一次快照；失败则用 5s 内的周期快照。
                    try:
                        state = ctx.storage_state()
                        if state:
                            self._write_session_state(state, _t.time())
                            self._session_snap_ok = True
                    except Exception:
                        pass
                    self.logger.info("[%s] 验证窗口已关闭，会话已保存到 %s",
                                     self.name, self.user_data_dir)
                    return True
                now = _t.time()
                if now - last_snap >= 5:
                    # 周期快照：避免"刚过完验证就关窗"丢掉最后一组成熟 cookie
                    try:
                        state = ctx.storage_state()
                        if state:
                            self._write_session_state(state, keep_saved_at)
                            self._session_snap_ok = True
                    except Exception:
                        pass
                    last_snap = now
                _t.sleep(0.5)
        self.logger.info("[%s] 验证会话已保存到 %s",
                         self.name, self.user_data_dir)
        return True

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
