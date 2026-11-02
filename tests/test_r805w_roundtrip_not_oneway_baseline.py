# -*- coding: utf-8 -*-
"""r805w：往返价不许冒充单程明细基线。

`flight_prices` 没有 tripType 列——往返契约只落在
`extra[].tripType='RT'`（+ `backDate`）上。而 `latest_prices()` 按
`platform×航线×日期` 取 MAX(id) 当作「明细已采过」的 TTL 基线，**不看
口径**。

受控实验（本文件第二条用例复现）：同一天先存单程 ¥500、再存往返
¥1200，修复前 `latest_prices()` 返回 **¥1200**——重启后系统以为这条
航线当天已经采过明细，于是跳过采集；用户看到的"上次价格"其实是
往返总价。这正是本项目反复防的「静默换口径」。

判据：
  1. 往返行不进单程基线（返回 ¥500 而不是 ¥1200）；
  2. 当天只有往返行时，不返回任何单程基线（宁可当"没采过"）；
  3. 普通单程行照常返回（别把正常路径也挡掉）。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.storage import PriceStorage  # noqa: E402

FC, TC, D = "SHA", "BJS", "2026-11-27"


def _row(price, kind, ts):
    el = [{"price": price, "code": "HO1251", "name": "吉祥",
           "depDate": D, "depTime": "10:25", "arrTime": "12:40"}]
    if kind == "RT":
        el[0]["tripType"] = "RT"
        el[0]["backDate"] = "2026-12-01"
    return type("P", (), {
        "platform": "fliggy", "from_city": FC, "to_city": TC,
        "depart_date": D, "price": float(price), "airline": "吉祥",
        "flight_no": "HO1251", "depart_time": "10:25",
        "arrive_time": "12:40", "fetched_at": ts,
        "extra": json.dumps(el, ensure_ascii=False), "prov": ""})()


def _fresh():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_round_trip_row_does_not_replace_oneway_baseline():
    st = _fresh()
    # 单程先入库、往返后入库（MAX(id) 会选中往返那条）
    st.save_many([_row(500.0, "OW", "2026-11-27 10:00:00"),
                  _row(1200.0, "RT", "2026-11-27 10:05:00")])
    got = [(x["platform"], x["price"]) for x in st.latest_prices(24 * 7)]
    assert got == [("fliggy", 500.0)], (
        "往返 ¥1200 顶替了单程基线：重启后会以为当天明细已采过。实际 %s" % (got,))


def test_only_round_trip_means_no_oneway_baseline():
    st = _fresh()
    st.save_many([_row(1200.0, "RT", "2026-11-27 10:05:00")])
    got = st.latest_prices(24 * 7)
    assert got == [], (
        "当天只有往返行时不能返回单程基线（宁可当没采过）：%s" % (got,))


def test_plain_oneway_still_returned():
    """负控反面：修复不能把正常单程也挡掉。"""
    st = _fresh()
    st.save_many([_row(500.0, "OW", "2026-11-27 10:00:00")])
    got = [(x["platform"], x["price"]) for x in st.latest_prices(24 * 7)]
    assert got == [("fliggy", 500.0)], "普通单程基线被误挡：%s" % (got,)


def _daily_bucket(st):
    import sqlite3
    con = sqlite3.connect(st.db_path)
    try:
        return con.execute(
            "SELECT kind, n, lo, hi, open, close FROM price_daily "
            "WHERE from_city=? AND to_city=? AND depart_date=?",
            (FC, TC, D)).fetchall()
    finally:
        con.close()


def test_round_trip_does_not_inflate_daily_calendar():
    """`price_daily` 是**单程**价格日历的数据源，往返价不许混进去。

    受控实验（修复前）：先存单程 ¥500 重算日桶得
    `('d',1,500,500,500,500)`；再存往返 ¥1200 重算 → 变成
    `('d',2,500,1200,500,1200)`——**hi 与 close 被抬到往返价**。
    日历面板/日 OHLC/改期比价都读这张表，用户会看到"当天收盘 1200"，
    以为单程涨了 2.4 倍。
    """
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    st.save_many([_row(500.0, "OW", ts)])
    st.refresh_daily(FC, TC, D)
    before = _daily_bucket(st)
    assert before and before[0][3] == 500.0, before

    st.save_many([_row(1200.0, "RT", ts)])
    st.refresh_daily(FC, TC, D)
    after = _daily_bucket(st)
    assert after == before, (
        "往返价进了单程日桶：修复前 hi/close 会被抬到 1200。实际 %s" % (after,))
    # 反面：正常单程仍要能算进日桶
    st2 = _fresh()
    st2.save_many([_row(500.0, "OW", ts)])
    st2.refresh_daily(FC, TC, D)
    got = _daily_bucket(st2)
    assert got and got[0][1] == 1 and got[0][3] == 500.0, (
        "正常单程没能进日桶（修复过头）：%s" % (got,))


def _flight_bucket(st):
    import sqlite3
    con = sqlite3.connect(st.db_path)
    try:
        return con.execute(
            "SELECT n, lo, hi, open, close FROM flight_daily "
            "WHERE from_city=? AND to_city=? AND depart_date=?",
            (FC, TC, D)).fetchall()
    finally:
        con.close()


def test_round_trip_only_still_shows_on_calendar():
    """**反面回归**（r805y）：只配置往返的航线，日历不许空盘。

    r805x 的「一律排除往返」把口径污染治好了，却让「只配往返」的航线
    `price_daily`/`flight_daily` 双双 0 行——用户看不到任何走势。正确
    口径是**互斥而非排除**：有单程就用单程，一条单程都没有时用往返。
    """
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    st.save_many([_row(1200.0, "RT", ts)])
    st.refresh_daily(FC, TC, D)
    st.refresh_flight_daily(FC, TC, D)
    pd = _daily_bucket(st)
    fd = _flight_bucket(st)
    assert pd and pd[0][1] == 1 and pd[0][3] == 1200.0, (
        "只配往返时 price_daily 空了或价不对（走势长窗会整片没数）：%s" % (pd,))
    assert fd and fd[0][0] == 1 and fd[0][1] == 1200.0, (
        "只配往返时 flight_daily 空了或价不对：%s" % (fd,))


def test_mixed_still_prefers_oneway_not_average():
    """混合时必须**只用单程**，不能平均、也不能选较新的往返。"""
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    # 往返先入库、单程后入库（MAX(id) 会指向单程；这里主要防"平均"）
    st.save_many([_row(1200.0, "RT", ts), _row(500.0, "OW", ts)])
    st.refresh_daily(FC, TC, D)
    st.refresh_flight_daily(FC, TC, D)
    pd = _daily_bucket(st)
    fd = _flight_bucket(st)
    assert pd[0][1] == 1 and pd[0][4] == 500.0, (
        "混合时 price_daily 出现了往返/平均值：%s" % (pd,))
    assert fd[0][0] == 1 and fd[0][3] == 500.0, (
        "混合时 flight_daily 出现了往返/平均值：%s" % (fd,))


def test_round_trip_does_not_inflate_flight_daily():
    """`flight_daily` 按航班身份分桶——同一班机的单程价与往返总价会撞进
    同一个 key，hi/close 直接被抬到往返价（受控实验：500 → 1200）。
    航班历史面板要给的是「这班单程卖多少钱」。
    """
    import datetime
    # 不能用 now()-5min：刚过零点时它会落到前一天，而日桶按今天过滤，
    # 全量门禁在 00:00–00:05 之间跑就会全空。
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _fresh()
    st.save_many([_row(500.0, "OW", ts)])
    st.refresh_flight_daily(FC, TC, D)
    before = _flight_bucket(st)
    assert before and before[0][2] == 500.0, before

    st.save_many([_row(1200.0, "RT", ts)])
    st.refresh_flight_daily(FC, TC, D)
    after = _flight_bucket(st)
    assert after == before, (
        "往返价进了航班日桶：修复前 close 会从 500 变 1200。实际 %s" % (after,))
    st2 = _fresh()
    st2.save_many([_row(500.0, "OW", ts)])
    st2.refresh_flight_daily(FC, TC, D)
    got = _flight_bucket(st2)
    assert got and got[0][0] == 1 and got[0][1] == 500.0, (
        "正常单程没能进航班日桶（修复过头）：%s" % (got,))
