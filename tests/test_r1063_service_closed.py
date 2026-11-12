# -*- coding: utf-8 -*-
"""r1063 T67：去哪儿**网页版停服**的识别与自动换道。

**现场证据**（真实抓取，`user_data/qunar/parse_fail/intl_11-20_20261108_092517.html`，208 字节）::

    {"ret":true,"code":1,"data":{"asyncComplete":true,
     "errorMsg":"服务调整通知：去哪儿旅行网页版机票查询及预订服务已停止提供，
                 请前往去哪儿旅行 App 查询、预订机票。"}}

所以 qunar 浏览器通路不是改版、不是限流，是**服务下线**——今天 6.5% 的成功率
就是这个原因，重试再多次也不会好。

三步：识别（记 `unsupported` 而非 `error`）→ 记账（`service_closed` 进降级账本）
→ 自动换道（`is_switch_worthy` 把停服也算进去，App 是唯一通路）。
"""
import io
import os

from core import failover as fo
from crawlers.base import is_service_closed_body

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = ('{"ret":true,"code":1,"data":{"asyncComplete":true,"errorMsg":'
        '"服务调整通知：去哪儿旅行网页版机票查询及预订服务已停止提供，'
        '请前往去哪儿旅行 App 查询、预订机票。"}}')


def test_detects_the_real_qunar_payload():
    closed, why = is_service_closed_body([REAL.encode()])
    assert closed is True
    assert "停止提供" in why


def test_login_page_prompt_is_not_a_service_closure():
    """登录页也常写「请下载 App」——不能误判成停服（那会白退役一条活通路）。"""
    assert is_service_closed_body(["请下载 App 查看更低价"])[0] is False


def test_normal_page_is_not_closed():
    assert is_service_closed_body(["<div>KN5956 ¥337</div>"])[0] is False
    assert is_service_closed_body([])[0] is False


def test_switch_policy_covers_closures_and_blocks():
    assert fo.is_switch_worthy("captcha") is True       # 行为型被拦
    assert fo.is_switch_worthy("service_closed") is True  # 停服（App 唯一通路）
    assert fo.is_switch_worthy("empty") is False        # 无票：不用换
    assert fo.is_service_closed("service_closed") is True
    assert fo.is_service_closed("captcha") is False


def test_main_uses_switch_worthy():
    main = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "is_switch_worthy(_kind0)" in main
    # 老写法（只认行为型）不许回退
    assert "if _fo.is_behavior_block(_kind0):" not in main


def test_qunar_marks_closure_as_unsupported_not_error():
    q = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                encoding="utf-8").read()
    assert "is_service_closed_body" in q
    i = q.index("is_service_closed_body")
    seg = q[i:i + 1200]
    assert '"H5", "unsupported"' in seg, "停服必须记 unsupported（不算失败）"
    assert 'note("service_closed"' in seg, "停服要进降级账本（面板才看得见）"


def test_panel_knows_the_new_capability():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "service_closed:'通路停服'" in w
    assert "service_closed:'这家网页版已停服" in w

def test_closed_memo_survives_instances():
    """停服记忆要落盘、跨实例有效（否则每次重启又白跑一轮）。"""
    import logging
    import os
    import tempfile
    import time

    from crawlers.qunar import QunarCrawler

    tmp = tempfile.mkdtemp()
    c = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t67"))
    assert c.service_closed_until() == 0.0
    c.mark_service_closed("服务已停止提供")
    assert c.service_closed_until() > time.time()
    assert os.path.exists(c.service_closed_path())
    c2 = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t67"))
    assert c2.service_closed_until() > time.time(), "新实例必须记得"


def test_closed_memo_short_circuits_fetch():
    """记住停服后，`fetch` 必须**不碰网络**、立刻返回并记 unsupported。

    一次查询百秒级——明知停服还去跑是纯浪费（今天 qunar 成功率 6.5% 就是这么来的）。
    """
    import logging
    import tempfile
    import time

    from crawlers.qunar import QunarCrawler

    tmp = tempfile.mkdtemp()
    c = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t67"))
    c.mark_service_closed("服务已停止提供")
    notes = []
    real_note = c.path_note
    c.path_note = lambda *a, **kw: notes.append((a, kw)) or real_note(*a, **kw)
    t0 = time.time()
    rows = c.fetch("SHA", "SIN", ["2026-11-20"])
    assert rows == []
    assert time.time() - t0 < 3, "停服窗口内不该再去跑（实测一次 137s）"
    assert any("unsupported" in str(n[0]) for n in notes), notes
    assert any("已停服" in str(n[1].get("detail", "")) for n in notes), notes

def test_permanent_closure_is_recorded_and_never_probes():
    """用户确认去哪儿网页版是**永久**停服 → 记忆 100 年，不再白探。"""
    import json
    import logging
    import tempfile
    import time

    from crawlers.qunar import QunarCrawler

    tmp = tempfile.mkdtemp()
    c = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t68"))
    c.mark_service_closed("网页版永久停服", permanent=True)
    assert c.service_closed_until() - time.time() > 3000 * 86400, "应是永久窗口"
    with open(c.service_closed_path(), encoding="utf-8") as f:
        rec = json.load(f)
    assert rec.get("permanent") is True and rec.get("detail")


def test_setup_check_distinguishes_retired_from_unsubscribed():
    """`qunar` 是"已退役（停服）"，不该再显示成"想采就加上"。"""
    import json
    import os
    import tempfile
    import time

    from core import setup_check as sc

    root = tempfile.mkdtemp()
    d = os.path.join(root, "user_data", "qunar")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "service_closed.json"), "w",
              encoding="utf-8") as f:
        json.dump({"until": time.time() + 86400 * 365, "permanent": True}, f)
    assert sc._is_retired(root, "qunar") is True
    assert sc._is_retired(root, "fliggy") is False
    # 临时停服（非 permanent）不算退役
    d2 = os.path.join(root, "user_data", "tuniu")
    os.makedirs(d2, exist_ok=True)
    with open(os.path.join(d2, "service_closed.json"), "w",
              encoding="utf-8") as f:
        json.dump({"until": time.time() + 3600, "permanent": False}, f)
    assert sc._is_retired(root, "tuniu") is False


def test_close_memo_lives_on_the_base_class():
    """一处实现、一个口径：qunar 不再自带一套 `_sc_*`。"""
    import os

    from crawlers.base import BaseCrawler

    for name in ("service_closed_path", "service_closed_until",
                 "mark_service_closed", "service_closed_skip"):
        assert hasattr(BaseCrawler, name), name
    q = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                encoding="utf-8").read()
    assert "def _sc_until" not in q, "qunar 不该再有自己的实现"
    assert "self.mark_service_closed(_closed, permanent=True)" in q
