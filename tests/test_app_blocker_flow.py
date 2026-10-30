# -*- coding: utf-8 -*-
"""拦路物接入采集流程：广告自动关、验证码/人脸独立入账、互不冒充。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler
from crawlers.app_zhixing import AppZhixingCrawler

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fixtures", "zhixing_list_dump.xml")


def _xml(*items):
    nodes = "".join(
        f'<node text="{t}" bounds="[{a},{b}][{c},{d}]" />'
        for t, a, b, c, d in items)
    return f'<hierarchy rotation="0">{nodes}</hierarchy>'


def _real():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


class FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeRuntime:
    def __init__(self, device):
        self._d = device

    def ensure_ready(self):
        return True, "ready"

    def device(self):
        return self._d

    def device_lock(self, timeout=600):
        return FakeLock()


class FakeDevice:
    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []

    def app_start(self, pkg):
        return True

    def app_stop(self, pkg):
        return True

    def root(self):
        # 快照恢复会先探 root；这个替身没快照，但方法要存在
        return False

    def dump(self, retries=2):
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def window_size(self):
        return (900, 1600)

    def current_activity(self):
        return "x/y"

    def screencap(self):
        return b""


def _crawler(pages):
    dev = FakeDevice(pages)
    c = AppZhixingCrawler({"android": {"enabled": True},
                           "app_boot_wait_s": 0},
                          logging.getLogger("t"))
    c._runtime = FakeRuntime(dev)
    c._skip_route = True
    return c, dev


def test_blocker_statuses_are_declared():
    """ad/captcha/face 必须在白名单里，否则会被静默归成 error。"""
    for s in ("ad", "captcha", "face"):
        assert s in AppCrawler.PATH_STATUS, s


def test_captcha_page_recorded_as_captcha_not_empty():
    page = _xml(("身份核实", 0, 0, 900, 60),
                ("请点击绿色数字7", 0, 600, 900, 700))
    c, _ = _crawler([page])
    c.safe_fetch("SHA", "CAN", ["2026-10-30"])
    st = [p["status"] for p in c.paths]
    assert "captcha" in st, st
    assert "empty" not in st, st


def test_face_page_recorded_as_face():
    page = _xml(("人脸识别", 0, 0, 900, 60),
                ("请正对屏幕", 0, 60, 900, 120))
    c, _ = _crawler([page])
    c.safe_fetch("SHA", "CAN", ["2026-10-30"])
    assert "face" in [p["status"] for p in c.paths]


def test_ad_with_close_is_dismissed_then_data_read():
    """广告可自动关闭：点掉之后照常出数据，不牺牲这一轮。

    点击序列取决于流程（现在先读长窗口日历再解析），所以断言"点过
    关闭按钮"而不是"第一个动作是它"——判据是行为发生，不是先后。
    """
    ad = _xml(("新人专享", 0, 0, 900, 40),
              ("限时活动", 0, 60, 900, 100),
              ("关闭", 840, 20, 890, 60))
    c, dev = _crawler([ad, _real()])
    rows = c.safe_fetch("SHA", "CAN", ["2026-10-30"])
    assert (865, 40) in dev.taps, dev.taps
    assert rows, "关掉广告后应能正常解析"
    assert not any(p["status"] == "ad" for p in c.paths), \
        "广告已关掉，不该再记成 ad 拦路"


def test_real_page_not_blocked_by_login_banner():
    """真实航班页有「登录解锁更低价」横幅，但数据能采 → 不算拦路。"""
    c, _ = _crawler([_real()])
    rows = c.safe_fetch("SHA", "CAN", ["2026-10-30"])
    assert rows, "登录横幅不该让整页被判成登录墙"
    assert "login" not in [p["status"] for p in c.paths]
