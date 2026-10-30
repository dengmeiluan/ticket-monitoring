# -*- coding: utf-8 -*-
"""r479：重登生效后不得继续催重登（可生效性 / 不重复无效操作）。

现场链：去哪儿国际 H5 24h 被登录墙拦 13/17、0 出数 → 面板判 `login`，
用户点「去登录」重存会话 → 之后 3 次全成功。但 24h 窗口里的旧 login 行
不会消失，`advise` 仍按「login 占多数」判 login，面板继续要求再登一次。
用户刚按提示做完，界面还催同一件事，只能读成「按了没用」。

修法：`path_stats` 额外给 `login_since_ok`（最近一次出数之后的登录墙
连击数，出数即清零），advise 用它判定「现在是否还进不去」；缺该字段
（旧载荷/单测）时退回总登录数，既有行为不变。
"""
import tempfile

import pytest


def _ps():
    """临时库。时间戳必须落在 24h 窗口内（path_stats 按 now 过滤），
    写字面日期会在第二天变成窗口外从而静默零样本。"""
    import os
    from datetime import datetime, timedelta
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    return PriceStorage(os.path.join(d, "t.db"))


def _at(minutes_ago):
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, status, at):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'fliggy','BKK','CAN','2026-11-05','H5',?)",
            (at, status))


def test_login_since_ok_resets_after_a_success():
    ps = _ps()
    stamps = []
    for i in range(12):
        t = _at(120 + i)
        if i == 0:
            last_login = t        # 记录**写入值**；循环后再算 _at(120)
        _row(ps, "login", t)      # 会跨秒，重算会差 1 秒（曾因此偶发红）
    _row(ps, "ok", _at(60))
    for i in range(3):
        _row(ps, "ok", _at(40 - i))
    n = ps.path_stats(24)["fliggy"]
    p = n["paths"]["H5"]
    assert p["login"] == 12, "总登录数仍应保留（历史证据）"
    assert p["login_since_ok"] == 0, "出数后登录连击未清零"
    assert n["last_login_at"] == last_login


def test_still_blocked_after_login_keeps_the_run():
    ps = _ps()
    _row(ps, "ok", _at(200))
    for i in range(9):
        _row(ps, "login", _at(120 - i*5))
    p = ps.path_stats(24)["fliggy"]["paths"]["H5"]
    assert p["login_since_ok"] == 9, "重登后又被拦的连击被吞掉"


def test_advise_stops_nagging_after_relogin_worked():
    from core.pacing import advise
    node = {"query_attempts": 45, "query_ok": 33,
            "scopes": {"intl": {"paths": {"H5": {
                "attempts": 45, "login": 27, "ok": 33, "calendar": 0,
                "empty": 0, "unsupported": 0, "login_since_ok": 0}}}}}
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert got["state"] != "login", "重登已生效仍在催重登：%r" % (got,)
    assert got["action"] != "relogin"


@pytest.mark.parametrize("run,expect_login", [(18, True), (2, False)])
def test_advise_uses_the_run_not_the_window_total(run, expect_login):
    from core.pacing import advise
    node = {"query_attempts": 20, "query_ok": 0,
            "scopes": {"intl": {"paths": {"H5": {
                "attempts": 20, "login": 20, "ok": 0, "calendar": 0,
                "empty": 0, "unsupported": 0, "login_since_ok": run}}}}}
    got = advise("fliggy", {}, {}, now=0, node=node)
    assert (got["state"] == "login") is expect_login, got
