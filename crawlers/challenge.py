# -*- coding: utf-8 -*-
"""挑战页（验证码 / 登录墙）的**识别**与**处置**。

识别（`classify_text`）回答「这是不是挑战页」；处置（`ChallengeHandler`
接缝）回答「拿它怎么办」。默认处置就是现行做法：调用方记 blocked/login
并停手，由人在可见窗口里过完。

要改成自己处置，注册一个处理器即可——采集器、账本语义、界面都不用动：

    from crawlers.challenge import ChallengeHandler, ChallengeOutcome, register_handler

    class MyHandler(ChallengeHandler):
        name = "my-handler"

        def on_navigation(self, page, ctx):
            # ctx.signal 是识别结果；解完自行 reload，采集器随后照常解析
            return ChallengeOutcome(handled=True, detail="已自动处置")

    register_handler(MyHandler())

现成的处理器：``crawlers.slider.SliderHandler``（只对**几何滑块**尝试，强人机
不碰；需显式注册 + ``crawler.slider.auto`` 打开，默认不挂）。

处理器在**页面渲染完成之后**接手（导航一返回就调用），面对的是已经渲染
出来的挑战控件；它解完自行 reload，重载不会再触发本钩子。
未注册处理器时，接缝是纯转发：行为与开销都与没有接缝时一致。
"""
import re
from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class ChallengeSignal:
    kind: str          # login | slider | click | captcha | waf | refresh
    status: str        # login | blocked
    marker: str
    confidence: str = "high"

    @property
    def detail(self) -> str:
        labels = {
            "login": "登录门",
            "slider": "滑块验证",
            "click": "点选验证",
            "captcha": "人机验证",
            "waf": "访问验证",
            "refresh": "服务端强刷",
        }
        label = labels.get(self.kind, self.kind)
        return "%s（%s）" % (label, self.marker) if self.marker else label


# Normal list pages contain “登录/注册” in the header; only explicit walls
# match these markers.
_LOGIN_TEXT_RE = re.compile(
    r"请登录|请先登录|账号密码登录|扫码登录|验证码登录|手机登录/注册|手机号登录")
_LOGIN_URL_RE = re.compile(r"passport|/login|/signin", re.I)
_CHALLENGE_TEXT_RE = re.compile(
    r"验证码|人机验证|安全验证|访问验证|滑动验证|拖动|滑块|拼图|请完成验证")
_SLIDER_TEXT_RE = re.compile(r"滑动验证|拖动|滑块|拼图")
_CLICK_TEXT_RE = re.compile(r"点选|按顺序点击")
_WAF_TEXT_RE = re.compile(r"安全验证|访问验证|whaleguard|baxia", re.I)


def login_signal(marker: str = "login") -> ChallengeSignal:
    return ChallengeSignal("login", "login", str(marker or "login"))


def blocked_signal(kind: str = "captcha",
                   marker: str = "challenge") -> ChallengeSignal:
    return ChallengeSignal(kind or "captcha", "blocked", str(marker or ""))


def classify_text(text: str = "", url: str = "") -> Optional[ChallengeSignal]:
    """Classify a rendered page/body or URL as a login wall or challenge.

    Returns None for a normal page, including pages whose header merely has
    a “登录/注册” link. Login wins over challenge when both are present,
    because the operator action is the same and auth state is the stronger
    evidence.
    """
    body = str(text or "")
    target = str(url or "")
    url_hit = _LOGIN_URL_RE.search(target)
    text_hit = _LOGIN_TEXT_RE.search(body)
    if url_hit or text_hit:
        return login_signal((url_hit or text_hit).group(0))
    hit = (_CHALLENGE_TEXT_RE.search(body) or _CLICK_TEXT_RE.search(body)
           or _WAF_TEXT_RE.search(body))
    if not hit and not _WAF_TEXT_RE.search(target):
        return None
    if _SLIDER_TEXT_RE.search(body):
        kind = "slider"
    elif _CLICK_TEXT_RE.search(body):
        kind = "click"
    elif _WAF_TEXT_RE.search(body) or _WAF_TEXT_RE.search(target):
        kind = "waf"
    else:
        kind = "captcha"
    return blocked_signal(kind, hit.group(0) if hit else "waf")


# ===================== 处置接缝（识别之外的另一半） =====================


@dataclass(frozen=True)
class ChallengeContext:
    """一次挑战处置的上下文。字段尽量少而通用，不绑某个渠道。"""

    plat: str = ""            # 渠道名（ctrip / app_qunar …）
    surface: str = ""         # PC / H5 / APP
    date: str = ""
    url: str = ""
    body: str = ""            # 页面正文（浏览器）或 dump 的 xml（App）
    page: object = None       # 浏览器页面（App 路径为 None）
    device: object = None     # App 设备（浏览器路径为 None）
    crawler: object = None    # 采集器实例（需要读它自己的状态时用）
    signal: object = None     # 识别结果：浏览器=ChallengeSignal，App=Block


@dataclass(frozen=True)
class ChallengeOutcome:
    """处置结果。handled=True 表示「已处置，调用方可以继续」。"""

    handled: bool = False
    detail: str = ""


class ChallengeHandler:
    """挑战处置处理器基类。子类按需实现钩子。

    - `on_navigation(page, ctx)`：浏览器页面，**导航完成、页面已渲染**时调用。
      处理器可自行解验证并 reload；重载不会再次触发本钩子。
    - `on_device(dev, xml, ctx)`：App 设备（adb）。dump 出的界面判定为
      验证码/人脸时调用，处理完自行重新 dump 即可。
    """

    name = "handler"

    def on_navigation(self, page, ctx) -> ChallengeOutcome:
        return ChallengeOutcome()

    def on_device(self, dev, ctx) -> ChallengeOutcome:
        return ChallengeOutcome()


_HANDLER = None


def register_handler(handler):
    """注册处理器（全局唯一；重复注册覆盖旧的）。"""
    global _HANDLER
    _HANDLER = handler
    return handler


def unregister_handler():
    """注销处理器，回到默认处置（记 blocked/login 并停手）。"""
    global _HANDLER
    handler, _HANDLER = _HANDLER, None
    return handler


def current_handler():
    return _HANDLER


def ensure_slider_handler(config=None, *, user_data_dir="user_data",
                          profile: str = "", logger=None):
    """按配置**自动**挂上滑块处理器（幂等，默认关）。

    为什么需要这一层：``SliderHandler`` 写好了，但"谁去注册它"一直没人接——
    ``crawler.slider.auto`` 配成 ``simple`` 也不会生效，功能等于死的
    （2026-11-03 全仓搜过：``register_handler`` 只有在测试里被调用过）。

    这里做成**幂等 + 失败静默**的引导函数，由 ``BaseCrawler.__init__`` 调用，
    于是只要采集器启动就会按配置生效，不用改 main / webui：

    * ``crawler.slider.auto`` 为假/未配 → **不注册**，保持"识别→记账→停手"；
    * 为真 → 注册 ``SliderHandler``（内部仍会二次分级：强人机一律不碰）；
    * 已经注册过同一个处理器 → 直接返回，不重复覆盖。

    返回当前处理器（可能是 None）。
    """
    try:
        from . import slider as slider_mod
        cur = _HANDLER
        want = slider_mod.should_attempt(
            "probe", config, user_data_dir=user_data_dir, profile=profile)[0]
        if not want:
            return cur
        # 优先挂**超集**处理器：它覆盖滑块 + 算数 + 文字（强人机一律不碰）。
        # 挂不上时退回只处理滑块的旧实现，保证老行为可用。
        try:
            from . import captcha as captcha_mod
            handler_cls = captcha_mod.SolverHandler
            handler_name = "solver-handler"
        except Exception:
            handler_cls = slider_mod.SliderHandler
            handler_name = "slider-handler"
        if getattr(cur, "name", "") in ("solver-handler", "slider-handler"):
            return cur
        return register_handler(handler_cls(
            config, user_data_dir=user_data_dir, profile=profile,
            logger=logger))
    except Exception:
        return _HANDLER


def _ctx_with(ctx, **kw):
    base = ctx if isinstance(ctx, ChallengeContext) else ChallengeContext()
    return replace(base, **kw)


def after_navigation(page, ctx=None) -> bool:
    """导航完成后交给处理器处置挑战页。返回 True = 已被处置。

    没注册处理器 → 直接 False（现行行为：采集器自己识别并记账）。
    识别用同一套 `classify_text`，处理器拿到的是**已渲染**的页面。
    """
    handler = _HANDLER
    if handler is None:
        return False
    try:
        body = page.inner_text("body")[:2000]
    except Exception:
        body = ""
    url = str(getattr(page, "url", "") or "")
    signal = classify_text(body, url)
    if signal is None:
        return False
    try:
        out = handler.on_navigation(page, _ctx_with(
            ctx, body=body, url=url, page=page, signal=signal))
    except Exception:
        return False
    return bool(out is not None and out.handled)


def handle_device(dev, xml, ctx=None):
    """App 侧：把设备上的挑战交给处理器。返回 outcome；没注册处理器 → None。"""
    handler = _HANDLER
    if handler is None:
        return None
    try:
        return handler.on_device(dev, _ctx_with(ctx, body=xml, device=dev))
    except Exception:
        return None


def install_navigation_guard(page, ctx_factory=None):
    """给页面的 `goto` 装一层：导航完成后交给处理器。

    没有注册处理器时这层是**纯转发**——不读页面、不改行为、不加开销。
    已装过则不重复装（同一页可能被多个采集流程复用）。
    """
    if getattr(getattr(page, "goto", None), "_challenge_guarded", False):
        return False
    _orig = page.goto

    def _goto(url, *args, **kw):
        result = _orig(url, *args, **kw)
        if _HANDLER is not None:
            ctx = ctx_factory(url) if ctx_factory is not None else None
            after_navigation(page, ctx)
        return result

    _goto._challenge_guarded = True
    page.goto = _goto
    return True
