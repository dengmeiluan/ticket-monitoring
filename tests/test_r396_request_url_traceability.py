# -*- coding: utf-8 -*-
"""r396：路径账的 request_url 列此前从没被写过——溯源断在这里。

实测真实库：`fetch_paths` 601 行里 `request_url` **全为空**（0/601），
尽管该列存在、`failure_recurrence` 也一直在 SELECT 它并作为证据回显。
后果是"这条路径失败时长什么样"只能靠 debug 截图猜，无法按 URL 复盘
是哪条入口、哪个 query、哪个日期被拦——目标里「可溯源/可验证」缺了
最基本的一环。

本组守卫钉三件事：
1. `path_note` 接受并保存调用方给的 URL（不是拿 `_last_page` 猜）；
2. 被拦状态仍可用页面 URL 兜底，但**不得覆盖**调用方显式给的值；
3. 三个持久化点（主采/补采/自检）都把 url 传给 `save_fetch_path`。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging  # noqa: E402

from core.storage import PriceStorage  # noqa: E402
from crawlers.base import BaseCrawler  # noqa: E402


class _Dummy(BaseCrawler):
    name = "dummy"
    URL_TPL = "https://example.test/list?date={date}"

    def __init__(self):
        super().__init__({}, logging.getLogger("t_r396"))

    def fetch(self, *a, **kw):  # pragma: no cover - 只测路径账
        return []


def _store():
    d = tempfile.mkdtemp(prefix="tm_r396_")
    return PriceStorage(os.path.join(d, "prices.db"))


def test_path_note_keeps_explicit_url():
    c = _Dummy()
    c.path_reset()
    rec = c.path_note("H5", "ok", rows=3, date="2026-11-16",
                      url="https://m.test/a?date=2026-11-16")
    assert rec["url"] == "https://m.test/a?date=2026-11-16"


def test_explicit_url_beats_page_fallback():
    """页面 URL 兜底不得覆盖调用方显式给的值（不同路径不同地址）。"""
    class _Page:
        url = "https://stale.test/from-previous-path"

    c = _Dummy()
    c.path_reset()
    c._last_page = _Page()
    rec = c.path_note("API", "login", date="2026-11-16",
                      url="https://api.test/touchInnerList")
    assert rec["url"] == "https://api.test/touchInnerList", rec


def test_page_url_still_used_when_caller_has_none():
    """调用方没给 URL 时，被拦状态仍要留下页面地址（原有行为）。"""
    class _Page:
        url = "https://passport.test/login?redirect=x"

    c = _Dummy()
    c.path_reset()
    c._last_page = _Page()
    rec = c.path_note("H5", "login", date="2026-11-16")
    assert rec["url"] == "https://passport.test/login?redirect=x", rec


def test_url_reaches_the_ledger():
    """端到端：URL 一路写进 fetch_paths 的 request_url 列。"""
    st = _store()
    c = _Dummy()
    c.path_reset()
    rec = c.path_note("H5", "soft_reject", detail="444",
                      url="https://m.test/x?d=2026-11-16")
    st.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                       rec["path"], rec["status"],
                       request_url=rec.get("url", ""),
                       note=rec.get("detail", ""))
    with st._conn() as conn:
        row = conn.execute(
            "SELECT request_url FROM fetch_paths ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "https://m.test/x?d=2026-11-16", row


def test_all_persist_points_pass_url():
    """三个落账点（主采/补采/自检）都必须把 url 传下去。

    只改其中一处会留下"有些路径有 URL、有些没有"的半吊子溯源，比全无
    更难排查（读者会以为空的那些是采集没走到）。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "main.py"), encoding="utf-8").read()
    calls = re.findall(r"save_fetch_path\((?:[^()]|\([^()]*\))*", src)
    assert len(calls) >= 3, [c[:60] for c in calls]
    missing = [c[:80] for c in calls if "request_url=" not in c]
    assert not missing, missing
