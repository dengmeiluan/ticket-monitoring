# -*- coding: utf-8 -*-
"""r1063 T253：**"核验一直不通过"的真根因**——URL 启发式把登录页自己判成登录墙。

issue #15 原话：「PC 飞猪网页已经登录但是核验一直不通过，携程登录不了」。

根因：`_verify_login_slot()` 打开的就是**登录页** `meta["login_url"]`，而
`classify_text()` 里

```python
_LOGIN_URL_RE = re.compile(r"passport|/login|/signin", re.I)
if url_hit or text_hit: return login_signal(...)
```

——URL 自己命中 `passport` / `/login`，于是**无条件**判"需登录"，
与"用户到底有没有登录"完全无关。携程 / 途牛 / 去哪儿的登录页 URL 全部命中。

修：`classify_text(..., ignore_url=True)` 供槽位核验使用，只按页面正文判断。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.challenge import classify_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGIN_URL = "https://passport.tuniu.com/login"


def test_login_url_alone_no_longer_forces_login():
    """已登录页面 + 登录页 URL → 旧逻辑必判需登录；新逻辑必须放行。"""
    body = "我的订单 退出登录 会员中心 钱包"
    old = classify_text(body, LOGIN_URL)
    assert old is not None and old.status == "login", (
        "旧行为应命中 URL 启发式（用于证明这个 bug 真实存在）")
    new = classify_text(body, LOGIN_URL, ignore_url=True)
    assert new is None, "已登录页面不该被判成登录墙（issue #15 的核心）"


def test_unlogged_page_still_detected():
    """忽略 URL 后，**正文**仍要能认出登录页。"""
    sig = classify_text("请输入手机号 手机号登录 账号密码登录", LOGIN_URL,
                        ignore_url=True)
    assert sig is not None and sig.status == "login", sig


def test_default_behaviour_unchanged_for_collection():
    """采集侧默认仍看 URL（登录页 = 需要登录），不要被这次改动带走。"""
    sig = classify_text("机票 酒店 火车票", LOGIN_URL)
    assert sig is not None and sig.status == "login"


def test_verify_calls_with_ignore_url():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "classify_text(body, page_url, ignore_url=True)" in w, \
        "槽位核验必须忽略 URL 启发式，否则永远判需登录"
