# -*- coding: utf-8 -*-
"""r1063 T220：周历**主动收割**（`crawler.week_calendar_harvest`）。

真机矩阵暴露的缺口：`PC·周历` **一次都没跑过**——因为 `_fill_week` 只在
"列表没拿到的日期"时兜底，而列表对配置那 1 天是成功的 → `missing` 为空 → 直接返回。
于是国际 4 条航线每家只有 1 天数据，而周历一次能给 ~7 天。

开关打开后（默认 False，多一次请求，交用户决定）：

```
ctrip  19s  rows=7   PC ok + PC·周历 ×6（￥1442/1398/1135/966/1066…）
fliggy 36s  rows=1   PC ok + PC·周历 empty（该航线周历无价）
```

第一次实现还有个错：收割模式把 `missing` 设成 `dates[:1]`，合并循环 `for d in missing`
→ 一次只加 1 天。改为遍历**周历返回的全部日期**（列表已有的不重复）才对。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_switch_exists_in_both():
    for name in ("ctrip.py", "fliggy.py"):
        s = _src(name)
        assert "week_calendar_harvest" in s, "%s 缺开关" % name


def test_harvest_only_adds_dates_missing_from_list():
    for name in ("ctrip.py", "fliggy.py"):
        s = _src(name)
        i = s.index("week_calendar_harvest")
        seg = s[i:i + 900]
        assert "if not missing and not _harvest" in seg, (
            "%s 默认行为必须保持：没缺日期就不跑周历" % name)
        # 收割时要遍历周历全部日期
        j = s.index("_targets")
        seg2 = s[j:j + 500]
        assert "sorted(cal" in seg2, "%s 收割必须遍历周历全部日期" % name
        assert "d not in have" in seg2, "%s 不许覆盖列表已有的真实数据" % name
