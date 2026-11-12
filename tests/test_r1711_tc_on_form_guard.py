# -*- coding: utf-8 -*-
"""r1711：同程 App 动手前先确认「还站在机票表单」，偏了就快停并如实记账。

现场（账本近 24 小时）：

```
app-city   timeout  47 次    note: 点城市位后未打开城市页 · 页面: 火车票
app-date   timeout  16 次    note: … · 页面: 火车票
app-login  blocked  56 次    （多半是上面空跑累计出的熔断）
```

走错页还在硬点：每次白烧 **30–80 秒**（App 单次成本本来就 100–200 秒），
这些空跑还会累计成熔断，把整家渠道锁住。

**改法**：新增 `_on_flight_form(dev, entry)`，在 `_set_city` 与
`_pick_round_trip_dates` 开头各判一次页（一次 dump，约 1 秒）：
- 是机票表单 → 继续；
- 停在火车票页 / 认不出表单 → `path_note(entry, "timeout",
  detail="偏离机票表单（页面: 火车票），本次提前结束")` 并**立即返回**。

代价 1 秒，换来走错页时从 30–80 秒缩到 ~10 秒，且账本直接写明为什么结束
——不再需要事后手工 adb 截图才看得懂。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng import (  # noqa: E402
    _TRAIN_MARKERS, is_train_page)
from crawlers.app_tongcheng_parse import is_form  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


def test_guard_helper_exists():
    src = io.open(os.path.join(ROOT, "crawlers", "app_tongcheng.py"),
                  encoding="utf-8").read()
    assert "def _on_flight_form(" in src, "没有「还在机票表单」的守卫"
    assert src.count("self._on_flight_form(dev,") >= 2, \
        "守卫没有接进 _set_city 与 _pick_round_trip_dates"
    assert "本次提前结束" in src, "提前结束时没有写明原因"


def test_train_fixture_is_not_a_flight_form():
    xml = io.open(TRAIN, encoding="utf-8", errors="replace").read()
    assert is_form(xml) is False
    assert is_train_page(xml) is True
    assert _TRAIN_MARKERS, "火车票判据丢了"
