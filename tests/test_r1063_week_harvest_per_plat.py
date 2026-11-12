# -*- coding: utf-8 -*-
"""r1063 T230：周历收割**按渠道**开关（`week_calendar_harvest_map`）。

真机依据：
```
fliggy  PC·周历  1 次  14.8s  永远 empty（页面里连一个 ¥ 都没有，已抓页面确认）
ctrip   PC·周历  2 次   7.6s  一次 5–6 天有价
```
全局开关只能全开/全关 → 为了省飞猪这 14.8 秒，就得牺牲携程的收益。
本开关让"只关飞猪"成为可能，且**不改默认行为**（缺省回全局值）。

验证：
```
fliggy 49s rows=1 [('PC','ok')]              ← 周历已关
ctrip  39s rows=7 [('PC','ok'),('PC·周历','ok')]  ← 仍开
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_map_supported_in_both():
    for name in ("ctrip.py", "fliggy.py"):
        s = _src(name)
        assert "week_calendar_harvest_map" in s, "%s 缺按渠道覆盖" % name
        i = s.index("week_calendar_harvest_map")
        seg = s[i:i + 500]
        assert "get(self.name" in seg, "%s 必须按 self.name 取覆盖值" % name
        assert 'week_calendar_harvest' in seg, "%s 缺省要回退到全局开关" % name


def test_note_explains_why_per_channel():
    """注释里要写清"为什么需要按渠道"（飞猪无价 14.8s/次），否则后人会删掉。"""
    s = _src("fliggy.py")
    i = s.index("week_calendar_harvest_map")
    seg = s[max(0, i - 400):i + 400]
    assert "无价" in seg or "14.8" in seg, "要把飞猪的实测结果写进注释"
