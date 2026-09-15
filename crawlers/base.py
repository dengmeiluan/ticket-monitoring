"""爬虫基类：Playwright 持久化上下文 + 反爬基础处理 + XHR拦截"""
import os
import re
import json
import random
import time
import logging
from contextlib import contextmanager
from typing import List, Optional, Callable

from playwright.sync_api import sync_playwright, BrowserContext, Page, Response

from core.models import FlightPrice


# 桌面/手机 UA
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/16.6 Mobile/15E148 Safari/604.1")


class BaseCrawler:
    name: str = "base"
    # 子类覆盖：是否使用手机端模拟
    use_mobile: bool = False

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.headless: bool = config.get("headless", True)
        self.timeout_ms: int = int(config.get("timeout_seconds", 45)) * 1000
        self.delay_min: float = float(config.get("delay_min", 2))
        self.delay_max: float = float(config.get("delay_max", 5))
        self.debug: bool = bool(config.get("debug", False))
        self.debug_dir: str = config.get("debug_dir", "debug")
        self.user_data_root: str = config.get("user_data_dir", "user_data")

    # ---------- 浏览器 ----------
    @property
    def user_data_dir(self) -> str:
        # 不同平台不同目录，避免互相污染
        path = os.path.join(self.user_data_root, self.name)
        os.makedirs(path, exist_ok=True)
        return path

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
                window_front: bool = False, window_idx: int = 0):
        """启动持久化浏览器上下文。headless=None 时使用配置。"""
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
                args=launch_args + [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            try:
                yield ctx
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass

    def new_page(self, ctx: BrowserContext) -> Page:
        page = ctx.new_page()
        page.set_default_timeout(self.timeout_ms)
        page.set_default_navigation_timeout(self.timeout_ms)
        return page

    # ---------- 工具 ----------
    def _sleep(self):
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def _debug_snapshot(self, page: Page, tag: str):
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
            self.logger.info("[%s] 已保存调试快照: %s.{png,html}", self.name, base)
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
            return [p for p in prices if 100 <= p <= 50000]

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
            return [p for p in prices if 100 <= p <= 50000]

        # 第 3 档：兜底，￥xxx 文本
        for m in re.finditer(r"[￥￥]\s*(\d{3,5})", text):
            prices.append(int(m.group(1)))
        return [p for p in prices if 100 <= p <= 50000]

    # ---------- 子类必须实现 ----------
    def fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        raise NotImplementedError

    def login_url(self) -> str:
        """登录引导页 URL，被 --login 模式使用。"""
        raise NotImplementedError

    # ---------- 公共调用入口 ----------
    def safe_fetch(self, from_city: str, to_city: str, dates: List[str]) -> List[FlightPrice]:
        try:
            self.logger.info("[%s] 开始抓取 %s->%s 日期=%s",
                             self.name, from_city, to_city, dates)
            results = self.fetch(from_city, to_city, dates) or []
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

    def _login_window(self, done_evt, idx: int = 0):
        """并行登录窗口：开登录页保持打开，done_evt 置位后关闭。
        idx 用于阶梯排布窗口位置避免叠死。"""
        url = self.login_url()
        self.logger.info("[%s] 登录窗口已打开：%s", self.name, url)
        bak = self.use_mobile
        self.use_mobile = False
        try:
            with self.browser(headless=False, window_front=True,
                              window_idx=idx) as ctx:
                page = self.new_page(ctx)
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                import time as _t
                while not done_evt.is_set():
                    _t.sleep(0.5)
            self.logger.info("[%s] 会话已保存到 %s", self.name, self.user_data_dir)
        finally:
            self.use_mobile = bak

    def _interactive_login_inner(self, url: str):
        with self.browser(headless=False, window_front=True) as ctx:
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
