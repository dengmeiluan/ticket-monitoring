# -*- coding: utf-8 -*-
"""控制台整套邮件快照：Playwright 无头渲染 webui 主视图 →
整页截图 PNG，以 CID 内嵌进邮件。

形态演进（实测驱动）：首版走「渲染后 DOM 序列化整套发」——QQ 邮箱
网页版实测剥 <style> 块，class 选择器全失去定义，flex/grid 布局散架
（用户截图实证：内容在、布局垮）。改整页截图：视觉与网页 100% 一致，
不依赖客户端 CSS 支持度——与钉钉推送「图为主」同一产品定律。

为什么必须走 Playwright 而不能直接发 PAGE 源码：控制台是 SPA，数据
由 JS 拉 /api/state 后渲染，邮件客户端禁 JS，源码发过去只是空壳。

CID 内嵌（multipart/related）而非外链/纯 data URI：QQ 邮箱对 http
外链图默认折叠（要点「显示图片」），CID 附件直出；data URI 在部分
客户端被剥。
"""
import logging
from typing import Optional

_CID = "console-shot"


def _port_rejects(base_url: str) -> bool:
    """控制台端口快速探测：连接拒绝/1s 不通即 True——
    服务未启动是快照失败常态，禁直进 Playwright goto 硬等 30s（+
    wait_for_function 再 30s）独占推送轮 ~1 分钟；1s 探测对悬挂
    （防火墙 drop）同样快速降级，正常路径多花 <50ms。"""
    try:
        from urllib.parse import urlparse
        u = urlparse(base_url)
        host = (u.hostname or "").strip()
        if not host:
            return False
        import socket
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=1.0):
            return False
    except OSError:
        return True
    except ValueError:
        return False


def render_console_png(base_url: str, logger: logging.Logger,
                       timeout_s: int = 30) -> Optional[bytes]:
    """渲染控制台主视图并返回整页截图 PNG bytes（失败返回 None，
    调用方降级轻壳——邮件通路优先于形态完整，渲染挂了邮件照发）。"""
    if _port_rejects(base_url):
        logger.info("[EmailShot] 控制台端口不通（未启动/悬挂），快速降级轻壳")
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                # 700px = 邮箱正文栏典型宽度；页面自动进 ≤760 窄屏
                # 响应式（adapt 不 amputate）；2x 缩放保文字锐度
                pg = browser.new_page(
                    viewport={"width": 700, "height": 1200},
                    device_scale_factor=2)
                pg.goto(base_url, wait_until="domcontentloaded",
                        timeout=timeout_s * 1000)
                # 等数据真渲染完：#pill 初始「加载中…」、失败「⚪ 服务
                # 未启动」、空配置「⚪ 未配置」（P2-5 补排——
                # 不含「未启动」子串，曾会被放行截成空配置快照发出），
                # 数据到了才变运行态（window.S 不可用——S 是
                # let 声明不挂 window）；空壳截图发出去比轻壳更糟
                pg.wait_for_function(
                    "() => { const p = document.querySelector('#pill');"
                    " if (!p) return false;"
                    " const t = p.textContent || '';"
                    " return t && !t.includes('加载中')"
                    " && !t.includes('未启动')"
                    " && !t.includes('未配置'); }",
                    timeout=timeout_s * 1000)
                # 入场动画走完再拍（动画中途截图=半空 KPI/半画曲线）
                pg.wait_for_timeout(1800)
                png = pg.screenshot(full_page=True, type="png")
                logger.info("[EmailShot] 控制台整页截图完成：%d KB",
                            len(png) // 1024)
                return png
            finally:
                browser.close()
    except Exception as e:
        logger.warning("[EmailShot] 控制台截图失败（降级轻壳）: %s", e)
        return None
