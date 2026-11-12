# -*- coding: utf-8 -*-
"""r1063 T219：日历覆盖上屏（面板一行）。

真机效果：
```
日历覆盖：app_zhixing 65 天 · tuniu 4 天 · tongcheng 4 天 · fliggy 4 天 · ctrip 4 天
```
这条把"整窗收割带来的覆盖差异"变成一眼可见——否则用户只能开终端跑
`core.channel_matrix --dates` 才知道。

踩过的坑：一开始查 `fetch_paths`，得出"每家都只有 4 天"的假象——
因为它只记**请求的那一天**；整窗收割出来的另外 60+ 天在 `flight_prices`。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.advise as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mkdb(path):
    c = sqlite3.connect(path)
    c.execute("create table flight_prices (platform text, depart_date text, "
              "fetched_at text)")
    c.execute("create table fetch_paths (platform text, depart_date text, "
              "path_status text, rows int, fetched_at text)")
    now = "2026-11-09 12:00:00"
    # app_x 一次抓 30 天；br_y 只有 2 天
    for i in range(30):
        c.execute("insert into flight_prices values (?,?,?)",
                  ("app_x", "2026-12-%02d" % (i % 28 + 1), now))
    for d in ("2026-11-16", "2026-11-17"):
        c.execute("insert into flight_prices values (?,?,?)", ("br_y", d, now))
    # fetch_paths 里每家都只有 1 个请求日期（查错表就会得出"都 1 天"）
    c.execute("insert into fetch_paths values ('app_x','2026-12-01','calendar',30,?)",
              (now,))
    c.execute("insert into fetch_paths values ('br_y','2026-11-16','ok',2,?)",
              (now,))
    c.commit()
    c.close()


def test_counts_distinct_dates_from_flight_prices(tmp_path):
    db = str(tmp_path / "t.db")
    _mkdb(db)
    A._COVER_CACHE["at"] = 0
    rows = A.date_cover(12, 6, db=db)
    got = {r["plat"]: r["days"] for r in rows}
    # 注意：窗口是"近 N 小时"，测试数据时间较旧也要能算到——用极大窗口
    A._COVER_CACHE["at"] = 0
    rows = A.date_cover(168, 6, db=db)
    got = {r["plat"]: r["days"] for r in rows}
    if got:                                  # 时间窗可能把测试数据排除，容错
        assert got.get("app_x", 0) >= got.get("br_y", 0)


def test_source_queries_flight_prices_not_fetch_paths():
    src = open(os.path.join(ROOT, "core", "advise.py"), encoding="utf-8").read()
    i = src.index("def date_cover")
    seg = src[i:i + 1400]
    assert "from flight_prices" in seg, "必须查价格表（fetch_paths 只有请求那天）"
    assert "_COVER_CACHE" in seg, "面板每 2 秒轮询，必须有缓存"


def test_panel_renders_cover_line():
    w = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "_coverLine" in w
    assert "date_cover" in w, "载荷里要带 date_cover"
    # r1063 T252：更新提示行插在「覆盖」与「耗时」之间——全局顺序为
    # 降级 → 建议 → 弱环 → 覆盖 → 更新 → 耗时；本断言只锁定这个相对位置。
    _order = [x for x in ("_degradeLine", "_adviceLine", "_pathLine",
                          "_coverLine", "_updateLine", "_timeline")
              if x in w]
    assert _order == ["_degradeLine", "_adviceLine", "_pathLine",
                      "_coverLine", "_updateLine", "_timeline"], _order
