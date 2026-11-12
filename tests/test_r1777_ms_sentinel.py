# -*- coding: utf-8 -*-
"""r1777：零成本步骤不许继承相邻步骤的耗时（`ms=-1` 哨兵）。

账本实测（智行近 24h）：

```
app-date  unsupported  24 次   平均 37146 ms   ← 它只是拿 dates 和视野比一下
航班明细   ok           22 次   平均  7561 ms
```

`reject_far_dates()` 是微秒级的视图比对，却在 r1565 的「分段时间兜底」里继承了
**前一步**（App 启动/登录）的 37 秒，读账本的人会误判瓶颈在"日期检查"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing import AppZhixingCrawler  # noqa: E402


class _Log:
    def info(self, fmt, *a):
        pass

    warning = info


def _crawler():
    c = AppZhixingCrawler({}, _Log())
    c.paths = []
    c.user_data_root = os.path.join(os.getcwd(), "_scratch", "_u")
    return c


def test_known_zero_ms_is_not_filled_from_delta():
    c = _crawler()
    c.path_note("app-login", "ok", detail="登录正常")          # 假定这步很慢
    c.path_note("app-date", "unsupported", ms=-1, detail="日期超视野")
    rows = {r["path"]: r for r in c.paths}
    assert rows["app-date"]["ms"] == 0, rows["app-date"]


def test_missing_ms_still_backfills():
    """没传 ms 的（真实的抓取步骤）仍要兜底补，不然速度口径又空了。"""
    c = _crawler()
    c.path_note("app-login", "ok", detail="登录正常")
    c.path_note("app-city", "timeout", detail="点城市位失败")
    rows = {r["path"]: r for r in c.paths}
    assert rows["app-city"]["ms"] >= 0


def test_horizon_note_uses_sentinel():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "app_base.py"),
        encoding="utf-8").read()
    i = src.index("def reject_far_dates")
    seg = src[i:i + 1200]
    assert "ms=-1" in seg, "日期视野检查没用哨兵"
    assert "_ms_known_zero" in src, "没有哨兵处理"
