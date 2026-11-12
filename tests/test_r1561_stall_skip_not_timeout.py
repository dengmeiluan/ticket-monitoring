# -*- coding: utf-8 -*-
"""r1561：熔断期间的跳过**不许**再记一次超时（否则窗口无限续期，渠道永不恢复）。

现场：app_tongcheng 刚订阅后连续 27 次 timeout、每次 elapsed_ms=0，
日志里「剩 29 分钟 → 剩 30 分钟」反复回到 30 —— 自我续期的活锁。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402


class _Fake(AppCrawler):
    name = "app_ctrip"
    APP_STALL_STREAK = 3
    APP_STALL_S = 1800

    def __init__(self):
        self.notes = []
        self.user_data_root = "user_data"
        self._timeout_streak = 5

    # 只接我们要验的两个钩子
    def app_stall_left_s(self):
        return 1200.0

    def app_gone_left_s(self):
        return 0.0

    def active_plat(self):  # 有人正在别的渠道登录？没有
        return ""

    def path_note(self, path, status, date=None, detail=""):
        self.notes.append((path, status, detail))

    def service_closed_skip(self, dates):
        return False

    def login_wall_skip(self, dates, path=""):
        return False


def test_stall_skip_is_blocked_not_timeout():
    c = _Fake()
    skipped = c.early_skip(["2026-12-01"], path="app-login")
    assert skipped is True, "熔断期间必须跳过"
    assert c.notes, "跳过也必须留一条通路记录（否则用户看不出为什么没跑）"
    for path, status, detail in c.notes:
        # r1841：闸门跳过 = **我方主动不发** → paced（原先是 blocked）。
        # 这条门禁真正要守的是「绝不能记 timeout」——那会让 _timeout_streak+1
        # 并再次续期熔断窗口，渠道永远回不来。
        assert status == "paced", (
            "熔断跳过被记成 %r —— 应记 paced（我方主动不发）：%s"
            % (status, detail))
        assert status != "timeout", "熔断跳过被记成 timeout，会续期熔断窗口"
        assert "暂停中" in detail, detail
        assert "本轮未发请求" in detail, "没说明这一轮根本没发请求"


def test_stall_skip_does_not_touch_timeout_streak():
    c = _Fake()
    before = c._timeout_streak
    c.early_skip(["2026-12-01"], path="app-login")
    assert c._timeout_streak == before, (
        "熔断跳过改变了连败计数（%d → %d）" % (before, c._timeout_streak))
