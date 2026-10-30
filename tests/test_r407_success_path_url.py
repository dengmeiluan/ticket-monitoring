# -*- coding: utf-8 -*-
"""r407：成功路径也要留地址——否则"可复现"只在失败时成立。

r396 只补了被拦/登录/软拒状态的 URL（走页面兜底）。出数时
`request_url` 仍恒为空：事后无法回答"这条成功记录当时打的是哪个
端点、哪些参数"，复现与对照都断了。

本守卫钉两件事：
1. 同程窗历成功记录必须带 **真实端点**；
2. 那个端点必须是 special.py 里真正发请求的 `_TC_CAL_URL`
   （`wx.17u.cn/cheapflights/bffapi/...`），**不是** INTL_CALENDAR_API
   ——后者是已被签名门拒的 ts/calendar，记错地址比不记更糟。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _read(fn):
    return open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()


def test_window_calendar_success_records_real_url():
    src = _read("tongcheng.py")
    i = src.index('self.path_note("窗历", "calendar"')
    # 前面几行是导入真实端点的代码
    block = src[max(0, i - 700):i + 400]
    assert "url=" in block, block
    assert "_TC_CAL_URL" in block, block


def test_recorded_url_is_the_one_actually_called():
    """记录的地址必须就是 special.py 真正 POST 的那个。"""
    from crawlers.special import _TC_CAL_URL
    assert "wx.17u.cn/cheapflights/bffapi" in _TC_CAL_URL, _TC_CAL_URL
    src = _read("tongcheng.py")
    i = src.index('self.path_note("窗历", "calendar"')
    block = src[max(0, i - 700):i + 400]
    # 不得把 ts/calendar 那个已被门拒的地址记进来（只看代码行，跳过注释）
    code = " ".join(ln.split("#", 1)[0] for ln in block.splitlines())
    assert "INTL_CALENDAR_API" not in code, code


def test_h5_list_success_records_page_url():
    src = _read("tongcheng.py")
    i = src.index('"H5列表", "ok"')
    block = src[i:i + 400]
    assert "url=" in block, block


def test_url_param_still_optional():
    """不传 url 的调用点行为不变（不得强制所有渠道都改）。"""
    import inspect
    from crawlers.base import BaseCrawler
    sig = inspect.signature(BaseCrawler.path_note)
    assert sig.parameters["url"].default == ""
