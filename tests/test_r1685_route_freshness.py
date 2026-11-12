# -*- coding: utf-8 -*-
"""r1685：关注航线价格卡必须写「多久前更新」，且时间解析要吃得下 "MM-DD HH:MM"。

现场：`上海→东京成田 ¥968 … 8 天` 这一行没有任何时间信息——价格是刚采的还是
几小时前的旧价分不出来（停了手的渠道尤其危险）。

第一版踩的坑：点位时间是 `"11-05 07:17"`（无年份），`Date.parse` 按 2001 年解释
→ 页面出现「219145 小时前」。门禁把这条钉死。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_card_shows_freshness():
    s = _w()
    i = s.index("function monRouteCard")
    seg = s[i:i + 4000]
    assert "_fresh" in seg, "价格卡没有渲染「多久前」"
    assert "分钟前" in seg and "小时前" in seg, "没有分钟/小时两级文案"


def test_timestamp_parser_handles_month_day_only():
    s = _w()
    i = s.index("function monRouteCard")
    seg = s[i:i + 4000]
    assert "_ptTs" in seg, "没有专门的点位时间解析函数"
    assert "Date.parse(String(p&&p[0]))" not in seg, (
        "又直接交给 Date.parse 了——无年份会被当成 2001 年（实测「219145 小时前」）")
    assert "+m[1]-1" in seg, "无年份分支缺失（跨年回退）"


def test_stale_tone_exists():
    s = _w()
    assert ".monroute-main .th.aging" in s, "超阈值没有告警色"


def test_very_old_shows_absolute_date():
    s = _w()
    i = s.index("function monRouteCard")
    seg = s[i:i + 4000]
    assert "2880" in seg, "超过 48 小时仍未退回绝对日期，会读成「823 小时前」"
    assert "停在 " in seg, "缺少「停在 MM-DD」的写法"
    # r1693：口径必须写准——这是「价格点」的时刻，不是每次采集。
    assert "最近价格点" in seg, "title 仍写「最近采集」，会冤枉渠道"
    assert "720" in seg, "告警阈值未按价格点语义放宽到 12 小时"
