# -*- coding: utf-8 -*-
"""r1804：App 渠道的登录建议不能叫用户「去验证」（那是打开浏览器窗口）。

`app_qunar` 的墙是原生页：「+86 / 请输入手机号 / 获取验证码 / 您也可以尝试接听
语音验证码」——会话在 App 里，浏览器窗口登不进去。原来的建议照抄浏览器口径：

    登录态失效：点「去验证」用采集同一会话过验证，关窗即落库…

用户点进去、登完、回来，App 照样是登录墙。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import _APP_CN, advise  # noqa: E402

NOW = time.time()
OFF = {"active": False}
CH = {"needs_login": True, "state": "login"}


def _hint(plat):
    return advise(plat, dict(CH), {}, now=NOW, quiet=OFF).get("hint") or ""


def test_app_channel_advice_points_at_the_phone():
    for p, name in (("app_qunar", "去哪儿 App"), ("app_tongcheng", "同程 App"),
                    ("app_zhixing", "智行 App")):
        h = _hint(p)
        assert "手机上打开" in h, (p, h)
        assert "「%s」" % name in h, (p, h)
        assert "验证码需你本人填" in h, (p, h)
        assert "去验证" not in h, "App 渠道仍建议点「去验证」：" + h


def test_web_channel_advice_unchanged():
    h = _hint("ctrip")
    assert "去验证" in h, h
    assert "手机上打开" not in h, h


def test_app_name_map_covers_all_app_channels():
    for p in ("app_ctrip", "app_fliggy", "app_qunar", "app_tongcheng",
              "app_zhixing"):
        assert p in _APP_CN, "缺中文名：" + p
