# -*- coding: utf-8 -*-
"""r1063 T175：开 App 登录会话时**顺手叫停本轮**，别让用户干等"等采集 N 秒"。

面板上曾出现「正在打开窗口… 12s · 等采集」——因为采集正占着设备。
我的两个能力可以组合解决：

* T167 **采集让位**：有登录会话时 App 渠道让位——但只对**下一条**航线生效，
  正在飞的那条要走完（最长 300s）；
* T172 **手动中止**：请求中止后不再派发下一条航线。

所以开登录会话时顺手 `interrupt.request()`，设备最迟在**当前航线结束时**空出来，
而不是等整轮跑完。

边界：只对「建会话」（`POST /api/app-login`）做一次，按钮点击/输入等高频调用
不重复请求（否则每点一下都写一遍标记文件）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_app_login_create_requests_interrupt():
    s = _src()
    i = s.index('_la.dispatch(_app_login_registry(), "POST", _u.path')
    seg = s[i:i + 1200]
    assert "叫停本轮为登录让路" in seg, "开会话没有请求叫停本轮"
    assert "_itr.request(by=\"app-login\")" in seg
    # 只对建会话那一步
    assert '_u.path.rstrip("/") == "/api/app-login"' in seg, \
        "必须只在建会话时请求，别让每次点击都写标记"
    assert "_r[0].get(\"ok\")" in seg, "只有会话建成功才叫停"


def test_interrupt_ttl_is_short_enough_for_login():
    """中止请求的 TTL 要够长（覆盖建会话→设备空出），但别无限。"""
    from core import interrupt as IT
    assert 300 <= IT.TTL_S <= 1800, IT.TTL_S
