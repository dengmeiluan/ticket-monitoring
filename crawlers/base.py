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

from .challenge import ChallengeContext, install_navigation_guard
from . import stealth_ext


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

# 链路闸门单次等待的**硬上限**（秒）。铁律 I6：本仓库每一处 sleep 都必须
# 有累计上限——否则 `min_gap_s` 配大了、或链路桶里排着一队未消化的窗口，
# 一次采集会被钉在纯空等上，后面的渠道整轮轮不到（qunar 曾累计空等
# 2891 秒 = 48.6 分钟，就是这个形态）。超出的部分不补：宁可这一轮少等，
# 也不拿别人的时间去赌一条链路的礼貌间隔。
PATH_GATE_SLEEP_CAP_S = 15.0


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


def _dedupe_cookies(cookies):
    """按 (name, domain, path) 去重，保留先出现的（Playwright 遇重复会拒收）。"""
    out, seen = [], set()
    for c in (cookies or []):
        try:
            key = (str(c.get("name") or ""), str(c.get("domain") or ""),
                   str(c.get("path") or "/"))
        except AttributeError:
            out.append(c)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def tap_design(dev, x, y):
    """按**设计基准**(900×1600) 点击；设备没有该入口时退回 `tap()`。

    为什么要有（r1263）：`tap_design/swipe_design` 只有 `AdbDevice` 实现，
    测试里的假设备（鸭子类型）没有这两个方法 → 爬虫一调就 AttributeError。
    这条兜底让"替代实现"也能跑，同时保留真实设备上的坐标换算。
    """
    fn = getattr(dev, "tap_design", None)
    return fn(x, y) if callable(fn) else dev.tap(x, y)


def swipe_design(dev, *args, **kwargs):
    """按设计基准滑动；设备没有该入口时退回 `swipe()`。"""
    fn = getattr(dev, "swipe_design", None)
    return fn(*args, **kwargs) if callable(fn) else dev.swipe(*args, **kwargs)


def cookies_or_empty(ctx, logger=None) -> list:
    """读浏览器 cookie；同名跨域重复导致 Playwright 拒读时降级为空列表。"""
    try:
        return list(ctx.cookies() or [])
    except Exception as e:
        if "Multiple cookies exist" not in str(e):
            raise
        try:
            if logger is not None:
                logger.warning("[cookie] 浏览器 jar 存在同名跨域重复，读取降级为空：%s",
                               str(e)[:80])
        except Exception:
            pass
        return []


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


# 移动档 UA（r1063 T25）：**必须与运行时同族**。运行时是 Playwright Chromium，
# 旧值是一个 iPhone/Safari 的 UA——那会同时与 `navigator.userAgentData`、
# `window.chrome`、`sec-ch-ua*` 三处矛盾（`python -m core.fp_audit` 报 high）。
# 现在用 Android Chrome：引擎、UA-CH、TLS(chrome) 三处自洽。
# 「这条通路的服务已经下线」的报文特征（r1063 T67）
# 现场实证（去哪儿）：`服务调整通知：…网页版机票查询及预订服务已停止提供，请前往…App`
SERVICE_CLOSED_MARKS = ("停止提供", "已停止服务", "服务已下线", "业务调整",
                        "请前往", "请下载")


def is_service_closed_body(bodies):
    """响应里是不是**明确写着"这条通路没了"**。返回 (bool, 依据片段)。

    为什么要与"被拦/改版"分开：被拦等一会儿可能好、改版能改解析；
    **停服只能换通路**（换 App/换家）。判据只认明确字面，不做推测。
    """
    for b in (bodies or ()):
        try:
            t = (b.decode("utf-8", "replace") if isinstance(b, bytes)
                 else str(b or ""))
        except Exception:
            continue
        if not t:
            continue
        hits = [m for m in SERVICE_CLOSED_MARKS if m in t]
        # 至少两个特征同时出现才算（避免登录页"请下载 App"这类误判）
        if len(hits) >= 2 or "停止提供" in t:
            return True, t[:160]
    return False, ""


def scoped_id(pid: str, plat: str, fallback):
    """按**渠道**取身份参数（r1063 T58）：参数层有意见才采用，否则用配置值。

    为什么需要：UA / 移动 UA / TLS 指纹这些"伪装参数"只读 `self.config` 的全局
    值，界面上按渠道改就白改。优先级与 `slider._pval`、`Pacing._scoped` 一致：
    **参数层是默认来源，不是永远优先**。

    fail-soft：参数层出任何问题都退回 `fallback`，伪装参数读不到不该让采集挂掉。
    """
    try:
        from core import strategy_params as _sp
        got = _sp.resolve(str(pid), plat=str(plat or ""))
        if str(getattr(got, "source", "default")) != "default":
            return got.value
    except Exception:
        pass
    return fallback


MOBILE_UA = MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/126.0.0.0 Mobile Safari/537.36")

# 本地指纹一致性（crawler.stealth，默认开）：
# 只抹掉「这是自动化浏览器」的显式标记，让页面看到一个普通 Chrome。
# 缺了它，同一份 UA/视口也会因为 navigator.webdriver=true 被直接降档。
STEALTH_JS = r"""
(() => {
  try { Object.defineProperty(Navigator.prototype, 'webdriver',
        {get: () => undefined, configurable: true}); } catch (e) {}
  // oscpu 是 Firefox 独有；Chromium 两档都不该出现（默认就没有，
  // 这里显式清掉，负控断言钉住 'oscpu' in navigator === false）。
  try {
    if ('oscpu' in navigator) {
      try { delete Navigator.prototype.oscpu; } catch (e) {}
      try { delete navigator.oscpu; } catch (e) {}
    }
  } catch (e) {}
  // NetworkInformation：headless 下时有时无且不自洽。两档统一给一个
  // 由 profile seed 派生的自洽对象（同 profile 稳定，不随机）。
  try {
    const conn = {
      effectiveType: __CONN_EFFECTIVE__,
      type: __CONN_EFFECTIVE__,
      saveData: __CONN_SAVEDATA__,
      rtt: __CONN_RTT__,
      downlink: __CONN_DOWNLINK__,
      onchange: null
    };
    Object.defineProperty(Navigator.prototype, 'connection',
      {get: () => conn, configurable: true});
  } catch (e) {}
  try {
    if (__ADDCHROME__) {
      if (!window.chrome) { window.chrome = {runtime: {}}; }
    } else {
      try { delete window.chrome; } catch (e) {
        Object.defineProperty(window, 'chrome',
          {get: () => undefined, configurable: true});
      }
    }
  } catch (e) {}
  try { Object.defineProperty(navigator, 'languages',
        {get: () => ['zh-CN', 'zh'], configurable: true}); } catch (e) {}
  try { Object.defineProperty(navigator, 'vendor',
        {get: () => __VENDOR__, configurable: true}); } catch (e) {}
  try { Object.defineProperty(navigator, 'platform',
        {get: () => __PLAT__, configurable: true}); } catch (e) {}
  try { Object.defineProperty(navigator, 'hardwareConcurrency',
        {get: () => __CORES__, configurable: true}); } catch (e) {}
  try {
    if (__MEM__ > 0) {
      Object.defineProperty(navigator, 'deviceMemory',
        {get: () => __MEM__, configurable: true});
    } else {
      try { delete navigator.deviceMemory; } catch (e) {}
      try { delete Navigator.prototype.deviceMemory; } catch (e) {}
    }
  } catch (e) {}
  try { Object.defineProperty(navigator, 'maxTouchPoints',
        {get: () => __MAXTOUCH__, configurable: true}); } catch (e) {}

  // screen / DPR：headless 默认 800×600 会和声明的 viewport 打架。
  try {
    const screenProps = [
      ['width', __SW__], ['height', __SH__],
      ['availWidth', __AW__], ['availHeight', __AH__],
      ['colorDepth', 24], ['pixelDepth', 24]
    ];
    for (const [k, v] of screenProps) {
      try {
        Object.defineProperty(Screen.prototype, k,
          {get: () => v, configurable: true});
      } catch (e) {
        try {
          Object.defineProperty(window.screen, k,
            {get: () => v, configurable: true});
        } catch (e2) {}
      }
    }
    Object.defineProperty(window, 'devicePixelRatio',
      {get: () => __DPR__, configurable: true});
  } catch (e) {}

  // userAgentData：移动档是 Safari UA，不该出现 Chromium 专属对象。
  try {
    if (__UAD__) {
      const uad = __UAD__;
      if (!uad.getHighEntropyValues) {
        uad.getHighEntropyValues = () => Promise.resolve({
          brands: uad.brands, mobile: uad.mobile, platform: uad.platform,
          architecture: 'x86', bitness: '64', model: '',
          platformVersion: '10.0.0', uaFullVersion: uad.fullVersion,
          wow64: false
        });
      }
      Object.defineProperty(Navigator.prototype, 'userAgentData',
        {get: () => uad, configurable: true});
    } else {
      try { delete navigator.userAgentData; } catch (e) {}
      try { delete Navigator.prototype.userAgentData; } catch (e) {}
    }
  } catch (e) {}

  // plugins / mimeTypes：headless 默认空数组，真实 Chrome 有 PDF 插件。
  try {
    const PLUGINS = __PLUGINS__;
    const MIMES = __MIMES__;
    const mimeObjs = MIMES.map((m) => ({
      type: m.type, suffixes: m.suffixes, description: m.description,
      enabledPlugin: null
    }));
    const pluginObjs = PLUGINS.map((p) => {
      const po = {name: p.name, filename: p.filename,
                  description: p.description, length: p.mimes.length};
      const mine = p.mimes.map((idx) => mimeObjs[idx]);
      mine.forEach((m, i) => {
        po[i] = m;
        if (m) { m.enabledPlugin = po; }
      });
      po.item = (i) => po[i] || null;
      po.namedItem = (n) => mine.find((m) => m && m.type === n) || null;
      return po;
    });
    const pluginArray = {
      length: pluginObjs.length,
      item: (i) => pluginObjs[i] || null,
      namedItem: (n) => pluginObjs.find((p) => p.name === n) || null,
      refresh: () => {}
    };
    pluginObjs.forEach((p, i) => { pluginArray[i] = p; pluginArray[p.name] = p; });
    const mimeArray = {
      length: mimeObjs.length,
      item: (i) => mimeObjs[i] || null,
      namedItem: (n) => mimeObjs.find((m) => m.type === n) || null
    };
    mimeObjs.forEach((m, i) => { mimeArray[i] = m; mimeArray[m.type] = m; });
    Object.defineProperty(navigator, 'plugins',
      {get: () => pluginArray, configurable: true});
    Object.defineProperty(navigator, 'mimeTypes',
      {get: () => mimeArray, configurable: true});
  } catch (e) {}

  try {
    const q = navigator.permissions && navigator.permissions.query;
    if (q) {
      navigator.permissions.query = (p) =>
        (p && p.name === 'notifications')
          ? Promise.resolve({state: Notification.permission})
          : q.call(navigator.permissions, p);
    }
  } catch (e) {}

  // WebGL：把调试扩展里"真实显卡"换成一台普通办公机（UNMASKED_* 是
  // 最常被拿去做指纹的两个参数，headless 默认值（SwiftShader）几乎是
  // 自报家门）。
  const VENDOR = __GLV__;
  const RENDERER = __GLR__;
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

# 桌面 GPU 按 seed 选一台，保证同 profile 稳定、不同 profile 可不同；
# 移动档是 iPhone Safari，GL 只能是 Apple 系。
_DESKTOP_GL = (
    ("Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce MX250 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
)
_PDF_MIMES = (
    {"type": "application/pdf", "suffixes": "pdf",
     "description": "Portable Document Format"},
    {"type": "text/pdf", "suffixes": "pdf",
     "description": "Portable Document Format"},
)
_DESKTOP_PLUGINS = (
    {"name": "PDF Viewer", "filename": "internal-pdf-viewer",
     "description": "Portable Document Format", "mimes": [0, 1]},
    {"name": "Chrome PDF Viewer", "filename": "internal-pdf-viewer",
     "description": "Portable Document Format", "mimes": [0, 1]},
    {"name": "Chromium PDF Viewer", "filename": "internal-pdf-viewer",
     "description": "Portable Document Format", "mimes": [0, 1]},
)
_MOBILE_PLUGINS = (
    {"name": "PDF Viewer", "filename": "internal-pdf-viewer",
     "description": "Portable Document Format", "mimes": [0, 1]},
)


def stealth_replacements(fp: dict) -> dict:
    """指纹占位符的唯一替换来源（测试可直接审计）。

    同一 profile 的 seed 固定 → GPU/尺寸/插件不变；移动/桌面两档
    的 vendor/platform/触摸/DPR/userAgentData 互斥，不能缝在一起。
    """
    mobile = bool((fp or {}).get("is_mobile"))
    vp = (fp or {}).get("viewport") or {}
    width = int(vp.get("width") or (390 if mobile else 1366))
    height = int(vp.get("height") or (844 if mobile else 900))
    seed = int((fp or {}).get("seed") or 0)
    if mobile:
        # Android Chrome（r1063 T25）：与 MOBILE_UA 同族。旧值是 iPhone/Safari
        # 那一套（Apple vendor / iPhone platform / Apple GPU / 无 chrome /
        # 无 userAgentData），与 Chromium 运行时的能力面直接对不上——
        # 换掉 UA 却留这套，等于把矛盾从"UA 与引擎"搬到"页面与头"。
        glv, glr = "Qualcomm", "Adreno (TM) 730"
        vendor, plat = "Google Inc.", "Linux armv8l"
        cores, mem, touch, dpr = 8, 8, 5, 2.625      # Pixel 8 口径
        plugins = ()
    else:
        glv, glr = _DESKTOP_GL[seed % len(_DESKTOP_GL)]
        vendor, plat = "Google Inc.", "Win32"
        cores, mem, touch, dpr = 8, 8, 0, 1
        plugins = _DESKTOP_PLUGINS
    # userAgentData：**两档都给**（两档都是 Chromium）。移动档 `mobile: true`
    # + `platform: "Android"`，与 MOBILE_UA 和 sec-ch-ua-* 三处自洽。
    uad = None
    m = re.search(r"Chrome/(\d+)", str((fp or {}).get("ua") or ""))
    major = m.group(1) if m else "126"
    uad = {
        "brands": [
            {"brand": "Chromium", "version": major},
            {"brand": "Google Chrome", "version": major},
            {"brand": "Not-A.Brand", "version": "99"},
        ],
        "mobile": bool(mobile),
        "platform": "Android" if mobile else "Windows",
        "fullVersion": "%s.0.0.0" % major,
    }
    return {
        "__ADDCHROME__": "true",      # 两档都是 Chromium：都该有 window.chrome
        "__VENDOR__": json.dumps(vendor),
        "__PLAT__": json.dumps(plat),
        "__CORES__": str(cores),
        "__MEM__": str(mem),
        "__MAXTOUCH__": str(touch),
        "__DPR__": str(dpr),
        "__SW__": str(width),
        "__SH__": str(height),
        "__AW__": str(width),
        "__AH__": str(height),
        "__UAD__": (json.dumps(uad, ensure_ascii=False)
                    if uad is not None else "null"),
        "__PLUGINS__": json.dumps(plugins, ensure_ascii=False),
        "__MIMES__": json.dumps(_PDF_MIMES, ensure_ascii=False),
        "__GLV__": json.dumps(glv),
        "__GLR__": json.dumps(glr),
        "__SEED__": str(seed),
        # NetworkInformation：rtt 50–100、downlink 8–12，按 seed 单射派生
        # （seed%51 与 seed//51 组合唯一），同 profile 稳定、不同 profile 不同。
        "__CONN_EFFECTIVE__": json.dumps("4g"),
        "__CONN_SAVEDATA__": "false",
        "__CONN_RTT__": str(50 + seed % 51),
        "__CONN_DOWNLINK__": "%.1f" % (8.0 + (seed // 51) * 0.2),
    }


def _accept_language(locale) -> str:
    """locale → Accept-Language；zh-CN 固定为 zh-CN,zh;q=0.9。"""
    loc = str(locale or "zh-CN").replace("_", "-")
    low = loc.lower()
    if low == "zh-cn" or not low:
        return "zh-CN,zh;q=0.9"
    if low.startswith("zh"):
        return "%s,zh;q=0.9" % loc
    if low == "en-us" or low.startswith("en"):
        return ("en-US,en;q=0.9" if low == "en-us"
                else "%s,en;q=0.9" % loc)
    return "%s,en;q=0.9" % loc


def profile_headers(fp: dict, extra=None) -> dict:
    """按指纹档案生成稳定 HTTP 头（B1 单源）。

    - UA 取 fp["ua"]；Accept-Language 由 fp["locale"] 派生；
    - 只要 UA 是 Chromium 系（桌面/移动都算）就发 sec-ch-ua*，
      版本与 UA 的 Chrome 大版本一致；移动档发 `?1` + `"Android"`；
    - UA 不是 Chromium（如用户自配 Safari UA）时**不发** UA-CH——
      发了反而与 UA 矛盾（`python -m core.fp_audit` 会报 high）；
    - Referer / Accept-Encoding 等由 extra 传入，本函数不硬编码；
    - 同 profile 多次调用逐项一致（不随机）。
    """
    fp = fp or {}
    ua = str(fp.get("ua") or "")
    mobile = bool(fp.get("is_mobile"))
    identity = {"user-agent", "accept-language", "sec-ch-ua",
                "sec-ch-ua-mobile", "sec-ch-ua-platform"}
    out = {}
    for k, v in (extra or {}).items():
        if str(k).lower() in identity:
            continue
        out[str(k)] = v
    out["User-Agent"] = ua
    out["Accept-Language"] = _accept_language(fp.get("locale"))
    # UA-CH 只在 UA 本身是 Chromium 系时才发（Safari/Firefox 档发了才是矛盾）。
    # r1063 T25：**移动档同样要发**——Android Chrome 会发 sec-ch-ua*，
    # 缺了等于自曝"UA 被改写"，与 UA 里写着 Mobile Safari 一样致命。
    m = re.search(r"Chrome/(\d+)", ua)
    if m:
        major = m.group(1)
        out["sec-ch-ua"] = (
            '"Chromium";v="%s", "Google Chrome";v="%s", '
            '"Not-A.Brand";v="99"' % (major, major))
        out["sec-ch-ua-mobile"] = "?1" if mobile else "?0"
        out["sec-ch-ua-platform"] = '"Android"' if mobile else '"Windows"'
    return out


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


def pacing_cfg_for(config) -> dict:
    """把采集器手上的配置包成 `parse_pacing` 认的形状（复核 2026-11-06）。

    **采集器收到的是 `crawler:` 段**（`main.py:1910`
    `crawler_cfg = dict(_full["crawler"])`），而 `parse_pacing` 读的是
    `cfg["crawler"]["rate"] / ["breaker"] / ["schedule"]`（`core/pacing.py:182-185`）。
    直接把 `self.config` 递给 `Pacing` 会让这份实例永远跑在 `DEFAULTS` 上
    （`min_gap_s 0` / `per_minute 0`）——「配了不生效」且从数字上看不出来，
    正是本仓库列为头号缺陷的那一类。

    也接受整份 cfg（含 `crawler:` 段）：此时原样用，**不再套一层**，否则
    `cfg["crawler"]["crawler"]` 一样是空的。
    """
    if not isinstance(config, dict):
        return {}
    if isinstance(config.get("crawler"), dict):
        return config
    return {"crawler": config}


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
                   "soft_reject",
                   # `paced` = **我方主动不发请求**（配额让位/节流跳过）。
                   # 它不是「被对方拒绝」，不该算进爬取率分母——否则
                   # 「主动让步」会被读成「渠道不行」（qunar 国际航线就是因为
                   # 让位被记成 soft_reject，成功率看起来只有 50%）。
                   "paced")

    def path_reset(self):
        self.paths = []
        self.last_path = ""
        self.last_status = ""
        # r1063 T227：耗时兜底的**起点**。`path_note` 用"上一条记账至今"
        # 估算步耗时；没有起点时，每次抓取的第一条记账会是 0（实测 11 条里
        # 有 6 条 0，全是各实例的第一条）。
        try:
            import time as _t0
            self._ms_prev = _t0.time()
        except Exception:
            pass

    # ---------- 分段计时（r1063 T77）----------
    # 只做观测：计时抛异常绝不影响采集。
    def timed(self, name: str):
        try:
            return self.phases_timer()(name)
        except Exception:
            import contextlib
            return contextlib.nullcontext()

    def phases_timer(self):
        if getattr(self, "_phases", None) is None:
            from core.phase_timer import PhaseTimer
            self._phases = PhaseTimer()
        return self._phases

    def path_note(self, path: str, status: str, rows: int = 0,
                  date: str = "", detail: str = "", ms: int = 0,
                  http_status: int = 0, url: str = ""):
        if status not in self.PATH_STATUS:
            status = "error"
        # 分段打点（r1063 T77）：上一条账到这一条账的间隔 = 上一步的耗时。
        try:
            import time as _pt
            _now = _pt.time()
            if getattr(self, "_phase_prev", None):
                _pn, _pt0 = self._phase_prev
                self.phases_timer().mark(_pn, _now - _pt0)
            self._phase_prev = (str(path), _now)
        except Exception:
            pass
        # r1063 T227：**耗时兜底**。显式 ms 优先；没给就用本实例上一条记账
        # 到这一条的间隔（同实例串行，≈ 这一步的耗时；含闸门等待）。
        # 与今天踩过的坑区分：那次是跨渠道用"相邻记录时间差"，把别的通路
        # 的时间算到自己头上——同实例内部没有这个问题。
        if not ms:
            try:
                _pv = getattr(self, "_ms_prev", None)
                if _pv:
                    _gap = (_now - _pv) * 1000.0
                    if 0 < _gap < 900000:      # 15 分钟内才算有效
                        ms = int(_gap)
            except Exception:
                pass
        try:
            self._ms_prev = _now
        except Exception:
            pass
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
        # 会话可用期（r1063 T93）：量化"登录后能用多久"
        try:
            from core import session_window as _sw
            from core.yield_stats import user_data_root as _udr
            # 走**唯一口径**（r972）：config 显式值 > TM_USER_DATA_DIR > user_data
            _sw.note(_udr(self.config), self.name, rec["status"])
        except Exception:
            pass
        # 被拦/登录墙往往返回 200 页面而不是 403：只在响应监听里记现场
        # 会漏掉最常见的人机验证。path_note 是各渠道确认"这条路过不去"
        # 的统一落点，在这里补页面 URL（调用方没显式给 url 时才用页面
        # 兜底），截图仍由上下文收尾统一落盘。
        #
        # **`soft_reject` 不算"被拦"**（2026-11-04）：它是"发了、对方软拒/
        # 限流"（去哪儿 1999 就是这一类），不是风控拦截。原来看起来一并
        # 记进 `last_block_url` → `debug/scene/*_block.txt` 越堆越多，
        # 实测 62 份里 **57 份其实是 1999 限流**，读起来像"被风控拦了 62 次"，
        # 把真拦截（人机验证）淹掉了。账本里 status 已经区分了两者，
        # 现场留证也该区分。
        if rec["status"] in ("blocked", "login"):
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

    # ── 链路闸门（r1063 T8）：用某条通路之前先问一次 ──
    def _pacing_ctx(self):
        """本采集器的节流上下文（懒建一次，之后复用）。

        `main.py` 那份 `rt["pacing"]` 管的是**渠道级**节奏（每条查询前
        `wait_hint` / 每条查询后 `record`）；这里要的是**链路级**的账：
        「这条通路刚才用过没有」。两者若共用一份实例，采集器写链路桶时
        就必然连渠道桶一起写（`record` 的默认语义），于是同一个请求被记
        两遍。所以缺省自建一份，只承载链路桶；主流程/测试要注入时把
        `self._pacing` 填上即可（那时由调用方负责 `channel=False`）。

        配置层由 `pacing_cfg_for` 包一层 `crawler:`（复核 2026-11-06）：
        采集器拿到的就是 `crawler:` 段，直接递进去会永远跑在 `DEFAULTS`。

        **刷新边界（r1063 fix-wave 1 起已接线，如实写明边界）**：热重载时
        `main.py` 的 `reload_config()` 除了 `rt["pacing"].refresh(cfg)`，还会遍历
        **已经建过**的采集器实例逐份 `refresh()` 这里的私有实例。递进来的 cfg
        与构造时同形——只有 `crawler:` 段（`pacing_cfg_for`），所以本实例能拿到
        的是**由 `crawler:` 段派生**的那几项：速率 / 熔断阈值 / 错峰
        `stagger_seconds` / 并发 `max_concurrency`。**静默窗（`scan_quiet_*`）
        与调度周期住在外层 `schedule:` 段，本实例从来收不到**——它们由
        `rt["pacing"]`（那份用整份 cfg 刷新）与调度器负责，热生效的也是那两份。
        懒建的实例（还没被问过闸门）下次构造时自然读到新 cfg。闸门真正用的速率
        值仍来自**参数层**（`_rate_limits` 优先 `strategy_params`；它的
        `set_config()` 已由 r1063 T14 接在 `main.py` 的启动路径与
        `reload_config()` 上），本实例的 cfg 只在参数层查不到/非法时兜底。
        """
        pac = getattr(self, "_pacing", None)
        if pac is not None:
            return pac
        try:
            from core.pacing import Pacing
            pac = Pacing(pacing_cfg_for(self.config))
        except Exception as e:
            # 闸门是采集的必经路径：构造不出来只能放行（并留痕），
            # 让它抛异常等于把整家渠道停采。
            pac = None
            log = getattr(self, "logger", None)
            if log is not None:
                log.warning("[%s] 链路闸门不可用（%s）：本轮按放行处理",
                            self.name, e)
        self._pacing = pac
        return pac

    def note_wait(self, sec) -> None:
        """记一次「本渠道在等」（秒）。闸门睡眠与渠道内部限速都走这里。

        为什么统一到一处：面板要给用户一个数——「这家的 80s 里有多少是在
        等我方限速」。分散在各个渠道里各记一套，最后就没人能给出这个数。
        """
        try:
            v = float(sec or 0)
        except (TypeError, ValueError):
            return
        if v > 0:
            self.waited_s = round(float(getattr(self, "waited_s", 0))
                                  + v, 2)

    def path_gate(self, path: str, dim: str = "", *, date: str = "") -> bool:
        """用 `path` 这条通路之前问一次：能不能用、要不要等。False=跳过它。

        决策顺序与口径全部在 `core.pacing.Pacing.gate_path`（策略停用 →
        熔断 → 限速），这里只做三件事：**封顶等待**、**记 paced 证据**、
        **只记链路桶**。

        * `allow=False`：只跳过**这一条通路**，调用点不许 `return` 整个
          查询。同一次查询里别的通路照跑——否则用户关掉一条劣化通路，
          等于整家渠道停采（这正是本闸门要挡的连坐）。
        * 证据记 `paced` 而不是失败：`paced` 的语义是「我方主动不发请求」，
          算进爬取率分母会把「主动让步」读成「渠道不行」，还会拉开整家
          渠道的熔断。
        * 等待封顶 `PATH_GATE_SLEEP_CAP_S`（铁律 I6）。
        * 记账**只写 `渠道|链路` 桶**（`channel=False`）：渠道桶的账
          `main.py` 已经为这条查询记过一次，这里再记一次就是重复计数
          （`per_minute` 减半、`min_gap` 翻倍）。节流实现若不吃
          `channel=`（旧签名），**宁可这条链路不记账**，也不退回带渠道
          口径的写法——那等于把双记重新打开。

        `dim` 是维度段（`domestic`/`intl`/`calendar`/`round_trip`/…，见
        `core.channels.DIMENSIONS`）：`渠道/维度/链路` 的覆盖要靠它才查
        得到，传空串等于把该链路的策略覆盖全部跳过。

        `date` 只在**逐日**的调用点给（qunar 的 H5/PC/API 三条都是逐日
        问的）：`paced` 证据带上日期，多日查询才看得出这一天被跳了
        （不带就成了「这一轮跳过了一条路」，看不出是哪天）。
        """
        pac = self._pacing_ctx()
        if pac is None:
            return True
        try:
            allow, wait_s, why = pac.gate_path(self.name, dim, path)
        except Exception as e:
            log = getattr(self, "logger", None)
            if log is not None:
                log.warning("[%s] 链路闸门判定失败（%s）：%s 按放行处理",
                            self.name, e, path)
            return True
        if not allow:
            self.path_note(path, "paced", date=date, detail=why)
            log = getattr(self, "logger", None)
            if log is not None:
                log.info("[%s] 跳过通路 %s%s：%s", self.name, path,
                         ("（%s）" % date) if date else "", why)
            return False
        # 等待必须封顶（铁律 I6）。只等闸门自己算出来的那一段，
        # 不在锁内睡（闸门本身只算不睡）。
        try:
            wait = float(wait_s or 0)
        except (TypeError, ValueError):
            wait = 0.0
        if wait > 0:
            _slp = min(wait, PATH_GATE_SLEEP_CAP_S)
            time.sleep(_slp)
            self.note_wait(_slp)      # 记「在等」（r1063 T30）
        # 只有**这条通路真的要发一次请求**时才记账，且只记链路桶。
        # 旧签名（`record` 不吃 `channel=`）时**不记**：退回
        # `record(plat, path=path)` 会把渠道桶一起写，`per_minute` 当场
        # 减半、`min_gap` 当场翻倍——宁可这条链路少记一次账。
        try:
            pac.record(self.name, path=path, channel=False)
        except TypeError:
            pass
        except Exception:
            pass
        return True

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
        # 资料根目录：与账本同一口径（config > TM_USER_DATA_DIR > user_data）。
        # 这一处是第 5 个写点（浏览器 profile / 登录态快照都落在这里），
        # 漏了它测试照样会把合成资料写进真 user_data。
        # 直接调用、不写兜底副本：`core.yield_stats` 不反向依赖 crawlers，
        # 没有循环导入风险；留一份同样的字面量只会让"唯一口径"名存实亡。
        from core.yield_stats import user_data_root
        self.user_data_root = os.path.abspath(
            os.path.join(_REPO_ROOT, user_data_root(config)))
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
        # 本渠道累计「等」了多少秒（r1063 T30）：闸门睡眠 + 渠道内部限速/退避。
        # 它与抓取耗时分开——「在等」和「在抓」是两种问题，优化手段不同。
        self.waited_s: float = 0.0
        # 登录窗口默认沿用该 profile 自己的 PC/H5 身份；只有显式开启
        # login_desktop 才强制桌面（手机 profile 上滑块更难拖时的退路，
        # 代价是登录与采集指纹不一致）。
        self.login_desktop: bool = bool(config.get("login_desktop", False))
        # 挑战处置引导：`crawler.slider.auto` 开了就自动挂上滑块处理器。
        # 放在这里而不是 main/webui——只要采集器被创建就生效，不用每个入口
        # 各写一遍（之前就是因为没人注册，配置开了也不生效）。
        try:
            from .challenge import ensure_slider_handler
            ensure_slider_handler(
                config, user_data_dir=self.user_data_root,
                profile=str(self.profile_name or self.name),
                logger=getattr(self, "logger", None))
        except Exception:
            pass

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

    @staticmethod
    def _cookie_key(c: dict) -> tuple:
        return (c.get("name"), c.get("domain"), c.get("path", "/"))

    @classmethod
    def _restore_plan(cls, existing: list, saved: list,
                      now: float = 0.0) -> list:
        """选择要写回上下文的快照 Cookie（缺失或比档案更新）。

        旧逻辑只补「档案没有的键」：档案里同名 Cookie 一旦过期/变旧，
        新快照永远盖不上去，重开浏览器就像掉登录。这里按 expires
        比较，只让快照替换「已过期」或「到期更早」的同名 Cookie；
        档案里更新的持久 Cookie 不被旧快照覆盖。
        """
        now = now or time.time()
        have = {}
        for c in existing or []:
            if isinstance(c, dict) and c.get("name"):
                have[cls._cookie_key(c)] = c
        out = []
        for c in saved or []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            cur = have.get(cls._cookie_key(c))
            if cur is None:
                out.append(c)
                continue
            try:
                se = float(c.get("expires", -1))
                ce = float(cur.get("expires", -1))
            except (TypeError, ValueError):
                continue
            if ce > 0 and ce <= now:
                out.append(c)
            elif se > 0 and ce > 0 and se > ce:
                out.append(c)
        return out

    def _state_has_auth(self, state: dict) -> bool:
        # 只认渠道声明的登录凭证；RISK_COOKIES 里的统计/风控 Cookie
        # 未登录也在场，拿它们当判据会把掉登录状态覆盖进快照。
        # 同名还不够：空值/已过期的持久 Cookie 是残留，不是登录证据
        # （2026-11-02 实测 QN1/cookie2 匿名就下发，曾导致登出态回写）。
        want = tuple(getattr(self, "AUTH_COOKIES", ()) or ())
        if not want:
            return False
        now = time.time()
        for c in (state or {}).get("cookies") or []:
            if not isinstance(c, dict) or c.get("name") not in want:
                continue
            if not str(c.get("value") or "").strip():
                continue
            try:
                exp = float(c.get("expires", -1))
            except (TypeError, ValueError):
                continue
            if exp > 0 and exp <= now:
                continue
            return True
        return False

    def _should_refresh_snapshot(self, save_session) -> bool:
        """采集态是否回写快照（沿用 saved_at，不冒充重新登录）。"""
        return bool(
            save_session is None
            and self.session_saved_at > 0
            and getattr(self, "AUTH_COOKIES", ()))

    def _session_state_allowed(self, state: dict, save_session) -> bool:
        """登录窗口/采集态的快照是否允许落盘。

        登录窗口的“我已登录完成”只是用户声明，不是登录证据；若快照里
        没有 AUTH_COOKIES（空值/过期不算），覆盖旧快照会把上一份可用
        会话弄丢。采集态同理：登出态不覆盖。
        migrate 是旧 profile 迁移，不要求认证。
        """
        if not state:
            return False
        if save_session in (None, "login"):
            return self._state_has_auth(state)
        return True

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
        # 按渠道求值（r1063 T58）：界面上按渠道换 UA 要真的生效
        _mob = scoped_id("identity_headers.mobile_ua", self.name,
                         self.config.get("mobile_user_agent"))
        _desk = scoped_id("identity_headers.ua", self.name,
                          self.config.get("user_agent"))
        ua = ((_mob or MOBILE_UA) if self.use_mobile else (_desk or DESKTOP_UA))
        if not self.stealth:
            return ua
        maj = kernel_major()
        if not maj:
            # 记账（r1063 T60）：UA 里的 Chrome 主版本与真实内核不同步，本身就是
            # 一条高熵矛盾特征（UA-CH / 特性检测任一条都能看出来）。
            try:
                from core import degraded as _dg
                _dg.note("ua_kernel", str(getattr(self, "name", "") or ""),
                         "读不到内核主版本，UA 无法与真实内核对齐")
            except Exception:
                pass
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

    def _geo(self) -> tuple:
        """(locale, timezone)：与出口 IP 的地理一致（可选，默认 zh-CN/上海）。

        为什么需要：挂着境外/异地出口，而页面报 `Asia/Shanghai` + `zh-CN`，
        「IP 在 A 地、时区在 B 地」是风控里最便宜的一条矛盾判定。仓库既有
        结论也是这个方向（国内站 + 境外出口 = 风控升档）。

        配置（默认不写 = 完全保持原行为）::

            crawler:
              geo:
                locale: zh-CN
                timezone: Asia/Shanghai
                # 也可按渠道覆盖：qunar: {locale: zh-CN, timezone: Asia/Shanghai}

        时区非法时退回 Asia/Shanghai（宁可少一次适配，也不要启动失败）。
        """
        cfg = self.config.get("geo") if isinstance(self.config, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        per = cfg.get(self.name) if isinstance(cfg.get(self.name), dict) else {}
        loc = str(per.get("locale") or cfg.get("locale") or "zh-CN").strip()
        tz = str(per.get("timezone") or cfg.get("timezone")
                 or "Asia/Shanghai").strip()
        if not loc:
            loc = "zh-CN"
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)          # 不合法会抛，交给下面兜底
        except Exception:
            tz = "Asia/Shanghai"
        return loc, tz

    def fingerprint(self) -> dict:
        """采集/预热/自检/验证窗口共用的浏览器身份参数（单一来源）。

        headless 与窗口位置属于"怎么显示"，不进入身份；UA、视口、移动
        标记、locale/timezone、出口代理与 canvas 种子必须一致——同一
        profile 在采集和人工验证里呈现两套身份，本身就会被风控当成
        会话被接管。

        locale/timezone 可由 ``crawler.geo`` 覆盖（默认不变），用于让
        「时区/语言」与出口 IP 的地理对上；**键集固定 9 个**，不新增。
        """
        loc, tz = self._geo()
        return {
            "ua": self._ua(),
            "viewport": self._viewport(),
            "locale": loc,
            "timezone": tz,
            "is_mobile": bool(self.use_mobile),
            "has_touch": bool(self.use_mobile),
            "proxy": self.proxy,
            "stealth": bool(self.stealth),
            "seed": zlib.crc32(
                (self.profile_name or self.name).encode("utf-8")) % 997,
        }

    def _profile_wait_s(self) -> float:
        """``crawler.profile_wait_s``：拿不到会话锁时最多等多久（默认 0=不等）。

        默认 0 保持现行语义（立刻抛 SessionBusyError 让位）。设成 15–30 秒
        的意义：登录窗口/探针只占锁几十秒，让采集**等一会儿**比丢一整轮更
        划算——历史上 SessionBusyError 占了失败样本的 38.9%，全是这种「抢
        不到就整轮放弃」。
        """
        try:
            v = float(self.config.get("profile_wait_s", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(120.0, v))

    @contextmanager
    def browser(self, headless: Optional[bool] = None,
                window_front: bool = False, window_idx: int = 0,
                save_session: Optional[str] = None):
        """启动持久化浏览器上下文。headless=None 时使用配置。"""
        path = os.path.normcase(os.path.realpath(self.user_data_dir))
        with _PROFILE_LOCKS_GUARD:
            lock = _PROFILE_LOCKS.setdefault(path, threading.Lock())
        if not lock.acquire(blocking=False):
            wait_s = self._profile_wait_s()
            if wait_s <= 0 or not lock.acquire(timeout=wait_s):
                raise SessionBusyError(
                    "[%s] 会话正在登录或采集，请完成当前操作后重试" % self.name)
            self.logger.info("[%s] 会话被占用，等待 %.0fs 后取得（profile_wait_s）",
                             self.name, wait_s)
        try:
            with self._browser_context(headless, window_front, window_idx,
                                       save_session) as ctx:
                yield ctx
        finally:
            lock.release()

    def login_window_size(self) -> tuple:
        """登录窗口尺寸（宽, 高）——按端给默认值，可用配置覆盖。

        `web.login_window`（PC，默认 1280×900）与 `web.login_window_h5`
        （H5，默认 480×880）。H5 是手机页面，给手机比例窗口才点得到控件。
        任何非法配置都退回默认值——**这里抛异常等于弹不出窗**。
        """
        # r1063 T181：端从**槽位**来（login_surface），没有才退回采集口径。
        # 反例（现场）：CtripCrawler.use_mobile=True 是采集走 m 站的意思，
        # 但它的 **PC 登录槽位**必须开桌面尺寸窗口，否则 passport 页面被裁。
        _surf = str(getattr(self, "login_surface", "") or "").lower()
        if _surf in ("h5", "mobile", "m"):
            is_h5 = True
        elif _surf in ("pc", "desktop", "web"):
            is_h5 = False
        else:
            is_h5 = bool(getattr(self, "use_mobile", False))
        cfg = (self.config or {}).get("web") or {}
        default = (480, 880) if is_h5 else (1280, 900)
        key = "login_window_h5" if is_h5 else "login_window"
        v = cfg.get(key) or {}
        try:
            w = int(v.get("w") or default[0])
            h = int(v.get("h") or default[1])
        except (TypeError, ValueError, AttributeError):
            return default
        if w < 320 or h < 480:          # 太小的窗口人没法登录
            return default
        return (w, h)

    @contextmanager
    def using_surface(self, surface: str):
        """临时切到该端**独立槽位 profile**（r1063 T144）。

        `slot_crawler` 给每个槽位分了独立 profile，但采集时必须**主动切过去**，
        否则 H5 通路还在读 PC profile —— 用户登两次却只用一次。
        只在目标 profile **确有会话**时才切，避免把已登录的 PC 态切丢。
        """
        old = self.profile_name
        switched = False
        try:
            if str(surface or "").lower() == "h5":
                cand = "%s_h5" % self.name
                try:
                    has = os.path.isfile(os.path.join(
                        self.user_data_root, cand, "session-state.json"))
                except Exception:
                    has = False
                if has:
                    self.profile_name = cand
                    switched = True
            yield self
        finally:
            if switched:
                self.profile_name = old

    @contextmanager
    def _browser_context(self, headless, window_front, window_idx, save_session):
        hl = self.headless if headless is None else headless
        fp = self.fingerprint()
        with sync_playwright() as p:
            x, y = 40 + window_idx * 170, 24 + window_idx * 150
            launch_args = [f"--window-position={x},{y}"]
            if window_front:
                # r1063 T140：登录窗口尺寸可配，且按端给默认值
                # （PC 1280×900 够看表格；H5 480×880 是手机比例，点得到）
                _w, _h = self.login_window_size()
                try:
                    self.logger.info(
                        "[登录窗] %s 端=%s 尺寸=%dx%d",
                        self.name,
                        (getattr(self, "login_surface", "") or "（未标注）"),
                        _w, _h)
                except Exception:
                    pass
                launch_args += [f"--window-size={_w},{_h}",
                                f"--window-position={x},{y}"]
            # 旁路关闭（WebRTC 内网 IP 泄漏等）：不改页面行为，只掐泄漏面。
            # 与 STEALTH_JS 同一条开关，stealth=false 时零干预。
            launch_args += stealth_ext.launch_args(fp)
            # 可选启动参数（当前只有 channel）：单独走 `**_kw`；代理那行必须
            # 保持原字面量——test_r319_proxy 用源码钉住它，防止有人顺手把
            # 「出口统一」删掉（那是 IP 级限流的唯一开关）。
            _kw = {}
            # 可选：用系统真 Chrome（crawler.browser_channel: chrome）。
            # 默认空=沿用自带 Chromium，不改变任何既有行为。
            _chan = stealth_ext.channel(self.config)
            if _chan:
                _kw["channel"] = _chan
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
                **_kw,
            )
            if fp["stealth"]:
                try:
                    # 种子按 profile 固定：同一档案跨重启指纹一致（像真人），
                    # 不同档案互不相同（不把多个身份缝成同一个）
                    _rep = stealth_replacements(fp)
                    _js = STEALTH_JS
                    for _k, _v in _rep.items():
                        _js = _js.replace(_k, _v)
                    # 补齐层（WebRTC/音频/设备枚举/chrome 子对象/外框尺寸）：
                    # **拼进同一个 init script**，不上第二个 add_init_script——
                    # 「stealth 开时恰好 1 个脚本」是既有测试钉住的契约。
                    _ext = stealth_ext.extra_js(fp)
                    if _ext:
                        _js = _js + "\n" + _ext
                    ctx.add_init_script(_js)
                except Exception as _ste:
                    # 记账（r1063 T61）：伪装脚本没注进去 = **整个 stealth 失效**，
                    # 页面依旧是自动化特征。以前这里只有 pass。
                    try:
                        from core import degraded as _dg
                        _dg.note("stealth_init", str(self.name),
                                 "注入伪装脚本失败：%s" % str(_ste)[:80])
                    except Exception:
                        pass
            state = None
            try:
                # Chromium 重开可能丢弃 expires=-1 的会话 Cookie；快照
                # 只补缺失/更旧的键，不覆盖档案里更新的持久 Cookie。
                if os.path.isfile(self.session_state_path):
                    saved = self.load_session_cookies()
                    if saved:
                        plan = self._restore_plan(ctx.cookies(), saved)
                        if plan:
                            try:
                                ctx.add_cookies(_dedupe_cookies(plan))
                            except Exception as _ce:
                                if "Multiple cookies exist" not in str(_ce):
                                    raise
                                _seen, _by_name = set(), []
                                for _c in _dedupe_cookies(plan):
                                    _n = str(_c.get("name") or "")
                                    if _n in _seen:
                                        continue
                                    _seen.add(_n)
                                    _by_name.append(_c)
                                ctx.add_cookies(_by_name)
                yield ctx
                # 采集成功后回写一次快照（沿用原 saved_at，不代表重新
                # 登录）：否则短命会话 Cookie 只停留在登录那一刻，进程
                # 重启后快照已过期，表现成「过一会又要登录」。
                _refresh = self._should_refresh_snapshot(save_session)
                try:
                    state = (ctx.storage_state()
                             if (save_session or _refresh) else None)
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
                if not self._session_state_allowed(state, save_session):
                    if save_session == "login":
                        # 用户点了“我已登录完成”，但快照里没有登录凭证：
                        # 不能把登出态写成刚登录，也不覆盖旧快照。
                        raise RuntimeError(
                            "未检测到登录凭证（AUTH_COOKIES），未覆盖旧快照")
                    # 采集回写只在认证 Cookie 仍在场时发生：已掉登录的
                    # 状态不覆盖上一份可用快照。
                    state = None
                if state is not None:
                    saved_at = (time.time() if save_session == "login"
                                else self.session_saved_at)
                    self._write_session_state(state, saved_at)

    def new_page(self, ctx: BrowserContext) -> Page:
        page = ctx.new_page()
        page.set_default_timeout(self.timeout_ms)
        page.set_default_navigation_timeout(self.timeout_ms)
        self._last_page = page
        self._watch_retry_after(page)
        # 挑战处置接缝：导航完成后交给已注册的处理器（没注册=纯转发，
        # 行为与开销都不变）。处理器解完自行 reload，采集器照常解析。
        install_navigation_guard(page, lambda url: ChallengeContext(
            plat=self.name, url=url, crawler=self))
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
    # 真正的登录凭证（子类声明；空=不做采集后快照回写）。必须比
    # RISK_COOKIES 更严：cna/_bfa 等统计风控 Cookie 未登录也在场。
    AUTH_COOKIES: tuple = ()
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
                # 拟人化养熟（crawler.humanize，默认开）：让这次预热看起来是
                # 「打开首页 → 扫一眼 → 滚两屏」而不是「打开首页 → 立刻走」。
                # 只在预热这一段做——采集主路径不插多余动作（会点错控件）。
                try:
                    _h = self._humanize()
                    if _h[0]:
                        from .human import warm as _human_warm
                        _rep = _human_warm(page, self.profile_name or self.name,
                                           rounds=_h[1])
                        self.logger.info(
                            "[%s] 预热拟人化：移动 %d / 滚动 %d / %.1fs",
                            self.name, _rep.get("moves", 0),
                            _rep.get("scrolls", 0), _rep.get("seconds", 0))
                except Exception as _he:
                    self.logger.warning(
                        "[%s] 预热拟人化失败（不阻断预热）: %s",
                        self.name, _he)
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

    # ---------- 预热时序（日历/深链前置） ----------
    def wait_risk_cookies(self, ctx, names=None, timeout_s: float = 12.0,
                          poll_s: float = 0.8) -> list:
        """等**风控 cookie 真的落下**再继续，而不是死等固定秒数。

        为什么不能靠 ``page.wait_for_timeout(4000)``：预热的价值不在"停留了
        几秒"，而在"服务端把会话 cookie 发下来了"。固定等待有两个失败模式：

        * 快了 → cookie 还没下来就去打深链/日历，服务端当新会话 → 444/202 软拒
          （仓库既有归因里 444 占 23.8%，很大一部分就是这种时序错）；
        * 慢了 → 白等，且下一轮并不会因此更稳。

        这里改成**轮询到 cookie 出现即返回**：命中就立刻走（比固定等待快），
        没命中就等满超时并如实返回空列表（调用方据此记"预热未生效"，
        而不是假装成功）。

        ``names`` 省略时用渠道自己的 ``RISK_COOKIES``。
        """
        want = tuple(names or getattr(self, "RISK_COOKIES", ()) or ())
        if not want:
            return []
        end = time.time() + max(0.0, float(timeout_s))
        hit = []
        while True:
            try:
                names_now = {c.get("name") for c in ctx.cookies()}
            except Exception:
                names_now = set()
            hit = [n for n in want if n in names_now]
            if hit:
                return hit
            if time.time() >= end:
                break
            time.sleep(max(0.1, float(poll_s)))
        return hit

    # ---------- 工具 ----------
    def _humanize(self) -> tuple:
        """(是否启用, 轮数)：``crawler.humanize`` / ``crawler.humanize_rounds``。

        默认开、2 轮（约 4–8s）。关掉只影响预热时的那段「扫一眼」动作，
        不影响任何采集路径——这也是它敢默认开的原因。
        """
        raw = self.config.get("humanize") if isinstance(self.config, dict) else None
        if isinstance(raw, str):
            v = raw.strip().lower()
            on = v not in ("0", "false", "no", "off", "")
        elif raw is None:
            on = True
        else:
            on = bool(raw)
        try:
            rounds = int(self.config.get("humanize_rounds", 2) or 2)
        except (TypeError, ValueError):
            rounds = 2
        return on, max(1, min(6, rounds))

    # ---------- 统一策略 ----------
    def _policy(self):
        """策略引擎（懒加载；拿不到就返回 None = 全放行）。"""
        eng = getattr(self, "_policy_engine", None)
        if eng is not None:
            return eng
        try:
            from core.policy import default_engine
            self._policy_engine = default_engine(
                self.config, repo_root=_REPO_ROOT,
                profile=str(getattr(self, "profile_name", "") or self.name))
        except Exception:
            self._policy_engine = None
        return self._policy_engine

    def _policy_now(self, *, two_way: bool = True, statuses=None,
                    soft: bool = False, captcha: bool = False,
                    login_wall: bool = False):
        """拿一份决定。默认 `two_way=True` = 只查询、不推进状态机。"""
        eng = self._policy()
        if eng is None:
            return None
        try:
            return eng.decide(self.name, two_way=two_way, statuses=statuses,
                              soft=soft, captcha=captcha,
                              login_wall=login_wall)
        except Exception:
            return None

    def _policy_cached(self, ttl: float = 30.0, now: float = None):
        """带 TTL 的决定缓存：`_sleep` 一次采集里会被调几十次。

        不做缓存等于每次停顿都去读两份 JSON（产量 1 份 + 登录 1 份），
        纯白花 IO；而倍率 30 秒内不会变。
        """
        ts = float(now if now is not None else time.time())
        cache = getattr(self, "_policy_cache", None)
        if cache and ts - cache[0] <= ttl:
            return cache[1]
        pol = self._policy_now(two_way=True)
        self._policy_cache = (ts, pol)
        return pol

    def _policy_enabled(self, dim: str = "") -> bool:
        """``crawler.policy_gate``：统一策略的**总开关**（默认开）。

        关掉它只影响「闸门 + 倍率」，账本照记、报表照出——这样排障时能一键
        回到「各部件各自为政」的旧行为，而不会把度量也一起丢掉。

        **读参数层，不读 `self.config`**（复核 2026-11-06 Important）：
        `self.config` 是构造时注入的**冷冻配置**，`main.reload_config()` 只喂
        参数提供者、从不重建采集器，所以拿它判开关时「保存后热生效」是假的——
        界面写着热生效、实际要重启。这里改成决策那一刻问
        `strategy_params.switch_on("policy_gate.enabled", plat=渠道, dim=维度)`：
        同一个采集器对象，下一次 `decide()` 就吃到新值。

        `dim`（r1063 fix-wave 2）：`渠道/维度` 层写的
        `policy_gate.enabled: false` 要能让这个采集器看到——否则维度级覆盖
        只有界面文案。缺省空串 = 只看渠道层，与迁移前逐位相同。

        读不到（参数层整个不可用 / 这个键一层都没配过）时退回本实例配置里的
        `policy_gate` 旧键：那是这台机器上的**全局层**值，生产环境两处是同一
        份 cfg（`main.py` 注入的就是整份 `crawler:` 段），而只给 `crawler:`
        段的单测/嵌入方行为因此逐位不变。
        """
        try:
            from core.pacing import _flag
            from core.strategy_params import switch_on
            raw = self.config.get("policy_gate") \
                if isinstance(self.config, dict) else None
            return switch_on("policy_gate.enabled",
                             plat=str(getattr(self, "name", "") or ""),
                             dim=str(dim or ""), fallback=_flag(raw, True))
        except Exception:            # 参数层不可用：按本实例配置（旧行为）
            raw = self.config.get("policy_gate") \
                if isinstance(self.config, dict) else None
            if isinstance(raw, str):
                return raw.strip().lower() not in ("0", "false", "no", "off", "")
            return True if raw is None else bool(raw)

    def _policy_gate(self, dim: str = "") -> bool:
        """采集入口的统一闸门。返回 False = 本轮不发请求。

        只有 `riskscore` 到 `pause`/`human`/`rotate` 档才会关闸；**登录退避
        不关闸**（登录墙要如实记 `login` 并继续跑，由人过完再采），产量差也
        不关闸（真无票与风控无关）。关闸轮次**不计入爬取率**——它不是渠道
        的失败，是我们自己选择不打。

        `dim` 原样递给 `_policy_enabled()`（维度级覆盖要用它）。
        """
        if not self._policy_enabled(dim=dim):
            return True
        pol = self._policy_now(two_way=False)
        if pol is None:
            return True
        self._policy_cache = (time.time(), pol)
        if pol.allow:
            self.last_policy = pol.as_dict()
            return True
        self.last_policy = pol.as_dict()
        self.policy_blocked = True
        log = getattr(self, "logger", None)
        if log is not None:
            log.warning("[%s] 策略暂停本轮（%s，%ds 后可试）：%s", self.name,
                        pol.state, pol.wait_s(),
                        "／".join(pol.reasons)[:200])
        return False

    def _sleep(self):
        """页内停顿：**对数正态** + **按策略倍率放大**。

        均匀分布的间隔本身就是一条机器特征（机器人喜欢均匀），所以用
        对数正态（区间仍是 `delay_min..delay_max`）。在此基础上乘策略层给的
        `pace_factor`：降档时上限抬高（1.5×/2.5×），有余量时允许压到 0.8×
        但**不低于配置的 delay_min**——配置是人定的地板，不替人做决定。
        """
        try:
            pol = self._policy_cached()
            scale = float(getattr(pol, "pace_factor", 1.0) or 1.0) \
                if pol is not None else 1.0
        except Exception:
            scale = 1.0
        lo = float(self.delay_min)
        hi = float(self.delay_max) * max(1.0, scale)
        if hi < lo:
            hi = lo
        try:
            from .human import human_delay
            d = human_delay(lo, hi)
        except Exception:
            d = random.uniform(lo, hi)
        time.sleep(d)

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
        # 统一策略闸门：只有 riskscore 到 human/rotate 档才关（长期姿态），
        # 短时冷却仍归 ChannelBreaker（它拿得到 Retry-After）。关闸轮次
        # 不发请求、也不计入爬取率——那是我们选择不打，不是渠道失败。
        self.policy_blocked = False
        # 维度（r1063 fix-wave 2）：闸门开关（`policy_gate.enabled`）可被
        # `渠道/维度` 层覆盖，所以这里把本次采集的维度递给它。口径与
        # `main._dim_of_query()` 同一句：挂了返程日 = 往返采集，否则明细。
        if not self._policy_gate(
                dim="round_trip" if str(ret_date or "").strip() else "detail"):
            return []
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
            self._yield_note(results)
            self._policy_note_round()
            return results
        except SessionBusyError as e:
            # 让位：不记异常栈（这是预期内的排队，不是故障），也不重试
            self.last_busy = True
            self.logger.warning("[%s] %s", self.name, e)
            # **不记成功率**：抢不到自家锁不是渠道的问题。把它记成失败，
            # 等于用自家冲突去惩罚对方站点（仓库里已记为双重错误）。
            return []
        except Exception as e:
            self.logger.exception("[%s] 抓取失败: %s", self.name, e)
            self._yield_note([])
            self._policy_note_round()
            return []

    def _policy_note_round(self) -> None:
        """把本轮**已发生的事实**喂回策略层（推进状态机，不改本轮流程）。

        喂的是路径账本里真实记下的东西：HTTP 状态、软拒、挑战、登录墙。
        不喂猜测值——策略层据此决定下一轮的姿态（停/降速/换身份）。
        """
        try:
            codes = [int(p.get("http") or 0) for p in (self.paths or [])]
            self._policy_now(
                two_way=False, statuses=codes,
                soft=bool(self.last_soft_reject),
                captcha=any(p.get("status") == "blocked"
                            for p in (self.paths or [])),
                login_wall=any(p.get("status") == "login"
                               for p in (self.paths or [])))
            self._policy_cache = None      # 下轮重新判
        except Exception:
            pass

    # ---------- 爬取率账本 ----------
    # 解析失败留现场的容量上限（份数）：多了没用，还会占满盘
    PARSE_SCENE_KEEP = 10
    PARSE_SCENE_MAX_BYTES = 400_000

    # ---------- 登录墙记忆（r1063 T69，通用）----------
    LOGIN_WALL_FILE = "login_wall.json"
    LOGIN_PROBE_S = 2 * 3600

    def login_wall_path(self) -> str:
        from core.yield_stats import user_data_root as _udr
        return os.path.join(str(_udr(self.config)), self.name,
                            self.LOGIN_WALL_FILE)

    def login_wall_until(self) -> float:
        try:
            with open(self.login_wall_path(), encoding="utf-8") as f:
                return float((json.load(f) or {}).get("until") or 0)
        except Exception:
            return 0.0

    def mark_login_wall(self, detail: str = "") -> None:
        """记住"这家要登录"，落盘（跨进程）。登好后由 `clear_login_wall` 清掉。"""
        # r1063 T127：登录墙/验证页要在面板「降级」里可见，否则只看到 0 条
        try:
            from core import degraded as _dg
            _dg.note("app_risk_blocked", self.name, str(detail or "")[:110])
        except Exception:
            pass
        try:
            win = float(self.config.get("login_probe_s") or self.LOGIN_PROBE_S)
        except (TypeError, ValueError):
            win = float(self.LOGIN_PROBE_S)
        try:
            p = self.login_wall_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"until": time.time() + win,
                           "detail": str(detail)[:200],
                           "at": time.time()}, f, ensure_ascii=False)
        except Exception:
            pass

    def clear_login_wall(self) -> None:
        try:
            os.remove(self.login_wall_path())
        except Exception:
            pass

    def login_wall_skip(self, dates, path: str = "app-login") -> bool:
        """登录墙窗口内让位：**不发请求**，状态记 `login`（健康页显示需登录）。

        为什么记 `login` 而不是 `paced`：`paced` 是"我方主动让位"，而这里
        是"等人动手登录"——两者对用户的含义完全不同，界面要能分清。
        """
        until = self.login_wall_until()
        now = time.time()
        if until <= now:
            return False
        left_m = (until - now) / 60.0
        for d in (dates or []):
            try:
                self.path_note(path, "login", date=d,
                               detail="需登录（%.0f 分钟内不再重试）："
                                      "到「渠道登录」登一次即可恢复" % left_m)
            except Exception:
                continue
        return True

    # ---------- 通路停服（r1063 T68，通用）----------
    SERVICE_CLOSED_FILE = "service_closed.json"
    SERVICE_PROBE_S = 6 * 3600

    def _sst_root(self) -> str:
        from core.yield_stats import user_data_root as _udr
        return str(_udr(self.config))

    def service_closed_path(self) -> str:
        """停服记忆落盘位置（口径在 `core.service_state`，与 App 侧共用）。"""
        from core import service_state as _sst
        return _sst.path_for(self._sst_root(), self.name, "service_closed")

    def service_closed_until(self) -> float:
        """停服记忆到期时间（0=没记过）。读不到就当没记过——不吓唬自己。"""
        from core import service_state as _sst
        return _sst.until(self._sst_root(), self.name, "service_closed")

    def mark_service_closed(self, detail: str = "", *, permanent=False) -> None:
        """记住"这条通路停服了"并落盘（跨进程有效）。

        `permanent=True` 表示**永久停服**（用户确认过的那种，例如去哪儿网页版
        机票查询下线）：不再按窗口探测，直到有人手动清掉记忆。
        """
        from core import service_state as _sst
        try:
            win = float(self.config.get("service_probe_s")
                        or self.SERVICE_PROBE_S)
        except (TypeError, ValueError):
            win = float(self.SERVICE_PROBE_S)
        _sst.mark(self._sst_root(), self.name, "service_closed", detail,
                  window_s=win, permanent=permanent)

    def service_closed_skip(self, dates, path: str = "QUERY") -> bool:
        """停服窗口内让位：**不发请求**、记 `unsupported`。返回是否让位。

        `unsupported` 是**能力边界**，不计入渠道失败；记成 `error`/`empty`
        会白白拉低成功率（T67 定下的口径）。
        """
        until = self.service_closed_until()
        now = time.time()
        if until <= now:
            return False
        left_h = (until - now) / 3600.0
        for d in (dates or []):
            try:
                self.path_note(
                    path, "unsupported", date=d,
                    detail="网页通路已停服，暂停查询（%.1f 小时后重探）" % left_h)
            except Exception:
                continue
        return True

    def save_parse_scene(self, bodies, tag: str = "", anchors=()) -> dict:
        """把"有响应但解析不出"的现场存下来，返回**结构指纹**（r1063 T66）。

        为什么必须留：`国际列表有响应但未解析出价格` 这类记录只说明"没对上"，
        但**对不上哪一版**、长什么样，全靠猜。存一份 HTML + 一份结构指纹之后，
        下一次改版只要比两个指纹（节点数/高频 class/锚点命中）就知道变没变。

        ``anchors`` 给解析真正依赖的选择器/文案：命不中就说明页面结构变了。
        """
        out = {"path": "", "bytes": 0, "nodes": 0, "classes": 0,
               "anchors": {}, "why": ""}
        try:
            body = ""
            for b in (bodies or ()):
                if isinstance(b, bytes):
                    b = b.decode("utf-8", "replace")
                if b:
                    body = str(b)
                    break
            if not body:
                out["why"] = "没有响应体"
                return out
            out["bytes"] = len(body)
            import re as _re
            out["nodes"] = len(_re.findall(r"<(?:div|li|tr|a|span)\b", body))
            cls = _re.findall(r'class="([^"]{1,80})"', body)
            out["classes"] = len(set(cls))
            for a in (anchors or ()):
                out["anchors"][str(a)] = body.count(str(a))
            # 落盘
            from core.yield_stats import user_data_root
            root = os.path.join(user_data_root(self.config), self.name,
                                "parse_fail")
            os.makedirs(root, exist_ok=True)
            fn = "%s_%s.html" % (str(tag or "parse")[:24],
                                 time.strftime("%Y%m%d_%H%M%S"))
            fp = os.path.join(root, fn)
            with open(fp, "w", encoding="utf-8", errors="replace") as f:
                f.write(body[:self.PARSE_SCENE_MAX_BYTES])
            out["path"] = fp
            self._prune_parse_scenes(root)
        except Exception as e:
            out["why"] = "%s: %s" % (type(e).__name__, str(e)[:60])
        return out

    def _prune_parse_scenes(self, root: str) -> None:
        """只留最近 N 份现场（按修改时间）。"""
        try:
            files = [os.path.join(root, n) for n in os.listdir(root)
                     if n.endswith(".html")]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for p in files[int(self.PARSE_SCENE_KEEP):]:
                try:
                    os.remove(p)
                except OSError:
                    continue
        except Exception:
            pass

    @staticmethod
    def scene_sig(scene: dict) -> str:
        """把结构指纹压成一句话，直接写进路径账的 detail。"""
        if not scene or not scene.get("bytes"):
            return "无现场（%s）" % str((scene or {}).get("why") or "未知")
        miss = [k for k, v in (scene.get("anchors") or {}).items() if not v]
        return "现场 %d 字节/%d 节点/%d 类，锚点未命中 %s，已存 %s" % (
            scene.get("bytes") or 0, scene.get("nodes") or 0,
            scene.get("classes") or 0,
            ("、".join(miss)[:60] if miss else "无"),
            os.path.basename(str(scene.get("path") or "")) or "未落盘")

    def _yield_ledger(self):
        """成功率账本（懒加载；拿不到就当没有，绝不阻断采集）。"""
        led = getattr(self, "_yield_led", None)
        if led is not None:
            return led
        try:
            from core.yield_stats import default_ledger, user_data_root
            # 根目录唯一口径（config > TM_USER_DATA_DIR > user_data）；
            # 测试由 conftest 的 autouse fixture 重定向，别再往真 user_data 写
            root = user_data_root(self.config)
            profile = str(getattr(self, "profile_name", "") or self.name)
            self._yield_led = default_ledger(
                os.path.join(_REPO_ROOT, root), profile)
        except Exception:
            self._yield_led = None
        return self._yield_led

    def _yield_note(self, results) -> dict:
        """记一次「这轮到底取没取到数」，并按需打一条建议。

        口径：**只有 rows>0 才算成功**；`ok` 的判据从本轮的 `paths` 账本
        里取（`core.yield_stats.statuses_ok`），不看返回列表长度——两者
        不一致时（解析出 0 行但路径标 ok）以路径账本为准，因为那是采集
        链路的原生事实。
        """
        try:
            # **归因缺口**（与 app_base 的 app-silent 对称）：既没出数、
            # 又一条通路都没记时，`statuses_ok([])` 返回空 path，账本只会
            # 落成 `unknown` —— 报表上看得出「失败」却看不出卡在哪，
            # 与真风控混在同一个分母里。
            # 放在取账本**之前**：留痕不该依赖账本可用
            # （允许说不出原因，不允许什么都不说）；健康卡读的是 self.paths。
            if not self.paths and not results:
                try:
                    self.path_note(
                        "web-silent", "error",
                        detail="抓取返回空且未记录任何通路")
                except Exception:
                    pass
            led = self._yield_ledger()
            if led is None:
                return {}
            from core.yield_stats import (statuses_ok, is_paced,
                                          is_non_attempt)
            # 主动让位（配额/节流）**不算样本**：既不是成功也不是失败。
            # qunar 国际航线的配额让位原先被记成 soft_reject，账面成功率
            # 只有 50%，看起来像被风控，实际是在守配额（2026-11-04）。
            if is_paced(self.paths):
                return {"minutes": int(self.config.get("interval_minutes", 30)
                                       or 30), "factor": 1.0, "paced": True}
            # 非采集轮（不支持的通路 / 纯基础设施步骤）**不进样本**：
            # 把它算成"渠道失败"会让建议间隔和健康卡都指向错误结论
            # ——实测 app_zhixing 数据通路 0.99，却被 snap-restore 的
            # 266 条"0 行"拖到 0.59，于是建议间隔从 24 分钟涨到 45 分钟。
            if is_non_attempt(self.paths):
                return {"minutes": int(self.config.get("interval_minutes", 30)
                                       or 30), "factor": 1.0, "paced": True,
                        "non_attempt": True,
                        "why": "非采集轮（不支持的通路/基础设施），不计样本"}
            ok, rows, path = statuses_ok(self.paths)
            if not ok and results:
                # 路径账本没标 ok 但确实拿到行：仍算成功，路径归到 last_path
                ok, rows = True, len(results)
                path = path or (self.last_path or "unknown")
            # 顺便记下主通路的**状态**：账本只累加 ok/fail 的话，
            # "确实没票(empty)"、"解析失败(error)"、"登录墙(login)"
            # 会混成一个 fail 数字，处置方向完全不同（2026-11-05）。
            _pv = next((r for r in (self.paths or [])
                        if str(r.get("path") or "") == path), {})
            _st = str(_pv.get("status") or "")
            # 原因原文一起进账（r1063 T75）：只留状态的话，"为什么失败"要靠翻日志
            led.note(self.name, path or "unknown", ok, rows=rows, status=_st,
                     detail=str(_pv.get("detail") or ""))
            # 分段耗时也进账（r1063 T77）：只记成功率的话，"慢在哪一步"永远是谜
            try:
                _ph = self.phases_timer().summary()
                if _ph:
                    led.note_phases(self.name, _ph)
            except Exception:
                pass
            rec = led.recommend_interval(
                self.name, int(self.config.get("interval_minutes", 30)
                               or 30))
            if rec.get("factor", 1.0) != 1.0:
                self.logger.info(
                    "[%s] 爬取率建议：间隔 %.0f→%d 分钟（%s）",
                    self.name, float(self.config.get("interval_minutes", 30)
                                     or 30),
                    rec["minutes"], rec.get("why", ""))
            return rec
        except Exception:
            return {}

    def yield_snapshot(self) -> dict:
        """给面板/日志的整体爬取率视图（拿不到返回空）。"""
        try:
            led = self._yield_ledger()
            return led.snapshot() if led is not None else {}
        except Exception:
            return {}

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
        # r1063 T182：**槽位**的登录页优先（H5 槽位 → m 站）。
        # 以前这里只有 self.login_url()，而它返回的是渠道的 PC 登录页，
        # 于是 tuniu_h5 / ctrip_h5 都登在 PC 域上（H5 域拿不到 cookie）。
        url = (str(getattr(self, "login_url_override", "") or "")
               or self.login_url())
        self.logger.info("[%s] 正在打开登录窗口：%s（端=%s）", self.name, url,
                         getattr(self, "login_surface", "") or "未标注")
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
                        # 超时但已拿到凭证：同样按「已存待验」处理（r1063 T103）
                        try:
                            _st = ctx.storage_state()
                            if _st and self._session_state_allowed(
                                    _st, "login"):
                                self._write_session_state(_st, keep_saved_at)
                                self._session_snap_ok = True
                                self._login_saved_on_close = True
                                self.logger.info(
                                    "[%s] 登录窗口超时，但已拿到登录凭证 → "
                                    "记为「已存待验」", self.name)
                                return True
                        except Exception:
                            pass
                        raise RuntimeError("登录窗口超时，请重新打开")
                    try:
                        closed = bool(page.is_closed())
                    except Exception:
                        closed = True
                    if closed:
                        # 关窗只落 cookie 快照，沿用旧 saved_at；随后抛错
                        # 让调用方明确「未确认」。不能在这里写 now——那会
                        # 把"关窗"伪装成"刚保存登录"，登录态卡片会说谎。
                        _saved = False
                        try:
                            state = ctx.storage_state()
                            if state and self._session_state_allowed(
                                    state, "login"):
                                self._write_session_state(state, keep_saved_at)
                                self._session_snap_ok = True
                                _saved = True
                            else:
                                self.logger.info(
                                    "[%s] 登录窗口已关闭，未检测到登录凭证，"
                                    "旧快照保留", self.name)
                        except Exception:
                            pass
                        if _saved:
                            # r1063 T103：**关窗但已拿到登录凭证 = 成功**。
                            # 用户的自然动作就是登完关窗；以前这里一律抛错，
                            # 于是界面显示"登录无效"，而 cookie 其实已经落盘。
                            # 标记"已存待验"，由 _verify_login_slot 真核验一次。
                            self._login_saved_on_close = True
                            self.logger.info(
                                "[%s] 登录窗口已关闭，已拿到登录凭证 → 记为"
                                "「已存待验」，随后自动核验", self.name)
                            return True
                        raise RuntimeError(
                            "登录窗口已关闭，且未检测到登录凭证"
                            "（请确认已登录后再关闭窗口）")
                    now = _t.time()
                    if now - last_snap >= 5:
                        try:
                            state = ctx.storage_state()
                            # 登录未完成前不落盘：否则会用登出态覆盖旧快照
                            if state and self._session_state_allowed(
                                    state, "login"):
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
                              timeout_s: float = 300, idx: int = 0,
                              ready_evt=None):
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
            if ready_evt is not None:
                ready_evt.set()
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
