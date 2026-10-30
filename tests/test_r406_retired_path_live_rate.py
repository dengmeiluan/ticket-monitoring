# -*- coding: utf-8 -*-
"""r406：退役通路不应拖低渠道健康度——但要能分清"退役"与"暂时没走"。

真实数据（24h）：
  同程 查询成功率 63.5%，其中「日历」35 次查询全失败（r384 已被「窗历」
  取代，最后一次尝试 10-26 22:36 之后再没人试）；而在用的「窗历」54/54、
  「H5」7/7 都是 100%。等于一个**已不存在的入口**把一条健康渠道说成
  三分之二坏。

判据（只用时间先后 + 是否还有产出）：
  路径 P 已淘汰 ⇔ ① 窗口内一次都没成功；
                 ② 存在另一条路 Q，Q 的最后尝试晚于 P；
                 ③ Q 在窗口内有过成功。

① 是关键。第一版漏了它，把**携程 PC（24h 成功 129 次）**误判成淘汰——
它只是最近一次尝试比 H5 早几分钟。这个用例就是为了钉住那次误判。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


def _store():
    return PriceStorage(os.path.join(tempfile.mkdtemp(prefix="tm_r406_"), "p.db"))


def _feed(st, plat, entries):
    """entries: [(path, status, attempt_id, date[, offset_s])]

    offset_s 用于造"时间先后"：判据靠 last_at 比较，同一秒内分不出顺序
    （真实库里新旧通路相隔数十分钟，测试必须还原这个形状）。
    """
    from datetime import datetime, timedelta
    # 全部落在"1 小时前"起步的窗口内（留足余量，避免跨午夜被 24h 过滤）
    base = datetime.now() - timedelta(hours=1)
    for e in entries:
        path, status, aid, d = e[0], e[1], e[2], e[3]
        off = e[4] if len(e) > 4 else 0
        ts = (base + timedelta(seconds=off)).strftime("%Y-%m-%d %H:%M:%S")
        st.save_fetch_path(plat, "SHA", "BKK", d, path, status,
                           rows=5 if status in ("ok", "calendar") else 0,
                           attempt_id=aid)
        with st._conn() as c:
            c.execute("UPDATE fetch_paths SET fetched_at=? WHERE attempt_id=?",
                      (ts, aid))


def _node(st, plat, scope=None):
    n = st.path_stats(hours=24)[plat]
    return n if scope is None else n["scopes"][scope]


def test_retired_path_excluded_from_live_rate():
    """旧「日历」全失败且之后无人再试 → 退役，不计入在用口径。"""
    st = _store()
    # 旧「日历」：3 次尝试全失败（早期）
    _feed(st, "tc", [("日历", "login", "a1", "2026-11-16", 0),
                     ("日历", "login", "a2", "2026-11-16", 10),
                     ("日历", "login", "a3", "2026-11-16", 20)])
    # 新「窗历」：之后每次都成功
    _feed(st, "tc", [("窗历", "calendar", "b1", "2026-11-16", 600),
                     ("窗历", "calendar", "b2", "2026-11-16", 900)])
    n = _node(st, "tc")
    assert n["retired_paths"] == ["日历"], n["retired_paths"]
    assert n["query_rate"] == round(2 / 5, 4), n["query_rate"]
    assert n["query_rate_live"] == 1.0, n["query_rate_live"]
    assert n["query_attempts_live"] == 2, n["query_attempts_live"]


def test_live_path_with_success_is_never_retired():
    """还在出数的路径永不退役——哪怕另一条路更晚尝试过。

    回归：第一版判据只看"别人更晚"，把携程 PC（129 次成功）判成退役。
    """
    st = _store()
    _feed(st, "ctrip", [("PC", "ok", "p1", "2026-11-16", 0),
                        ("PC", "ok", "p2", "2026-11-16", 10)])
    _feed(st, "ctrip", [("H5", "ok", "h1", "2026-11-16", 600),
                        ("H5", "ok", "h2", "2026-11-16", 700),
                        ("H5", "ok", "h3", "2026-11-16", 900)])
    n = _node(st, "ctrip")
    assert n["retired_paths"] == [], n["retired_paths"]
    assert n["query_rate_live"] == n["query_rate"]


def test_dead_path_without_replacement_is_not_retired():
    """失败路径若没有"更晚且成功"的替代者，不进退役名单（可能只是被限流）。"""
    st = _store()
    _feed(st, "q", [("H5", "login", "a1", "2026-11-16", 0),
                    ("H5", "login", "a2", "2026-11-16", 10)])
    n = _node(st, "q")
    assert n["retired_paths"] == [], n["retired_paths"]
    assert n["query_rate_live"] == n["query_rate"]


def test_mixed_query_counted_once():
    """同一次查询走了多条路径：只要有一条在用，就仍算一次在用查询。"""
    st = _store()
    # 同一次查询：旧日历失败 + 窗历成功（同一 attempt_id）
    # 同一次查询（同一 attempt_id）走了两条路：旧日历失败 + 窗历成功
    _feed(st, "tc", [("日历", "login", "m1", "2026-11-16", 0),
                     ("窗历", "calendar", "m1", "2026-11-16", 0)])
    # 另一次查询只走旧路径，且发生在更晚的时刻——它自己就是"最后尝试者"，
    # 因此旧路径无法被判成"被取代"（有意的保守：宁可少判退役，也不要把
    # 还在尝试的路说成废弃）。这里只验证"混合查询按一次计"。
    _feed(st, "tc", [("窗历", "calendar", "m2", "2026-11-16", 600)])
    n = _node(st, "tc")
    assert n["retired_paths"] == ["日历"], n["retired_paths"]
    # m1（含旧+新）算一次在用；m2 算一次 → 共 2 次，且都成功
    assert n["query_attempts_live"] == 2, n["query_attempts_live"]
    assert n["query_rate_live"] == 1.0
    # 原口径：m1（旧失败+新成功）与 m2（成功）两次查询，都判成功
    assert n["query_attempts"] == 2, n["query_attempts"]
    assert n["query_rate"] == 1.0, n["query_rate"]


def test_scopes_have_their_own_retired_sets():
    """国际退役不影响国内口径（同程国内 H5 一直正常）。"""
    st = _store()
    _feed(st, "tc", [("日历", "login", "d1", "2026-11-16", 0),
                     ("窗历", "calendar", "d2", "2026-11-16", 600)])
    # 国内：H5 正常
    st.save_fetch_path("tc", "SHA", "URC", "2026-11-16", "H5", "ok",
                       rows=9, attempt_id="dom1")
    n = _node(st, "tc")
    assert n["scopes"]["intl"]["retired_paths"] == ["日历"], n["scopes"]["intl"]
    assert n["scopes"]["dom"]["retired_paths"] == [], n["scopes"]["dom"]


# ── advise 必须采用在用口径，否则修了统计也传不到用户眼前 ──────────────

def test_advise_uses_live_rate():
    """退役路径拉低原口径时，advise 必须报在用口径的数字。

    真实形态：同程原口径 63.5%、在用口径 100%。若 advise 仍读原口径，
    用户看到的还是"63.5%、需要处理"——修了统计等于没修。
    """
    from core.pacing import advise
    st = _store()
    # 与真实形态一致：国内 H5 出明细 + 国际窗历出日历价
    _feed(st, "tc", [("日历", "login", "a1", "2026-11-16", 0),
                     ("日历", "login", "a2", "2026-11-16", 10)])
    _feed(st, "tc", [("窗历", "calendar", "b1", "2026-11-16", 600)])
    st.save_fetch_path("tc", "SHA", "URC", "2026-11-16", "H5", "ok",
                       rows=9, attempt_id="dom1")
    n = st.path_stats(hours=24)["tc"]
    assert n["query_rate"] < 1.0, "前置：原口径应被旧路径拖低"
    assert n["query_rate_live"] == 1.0
    a = advise("tc", {}, {}, node=n)
    assert "100%" in a["hint"], a["hint"]
    assert a["state"] == "ok", a


def test_advise_falls_back_when_no_retired():
    """没有退役路径时行为不变（不引入新分支差异）。"""
    from core.pacing import advise
    st = _store()
    _feed(st, "q", [("H5", "ok", "x1", "2026-11-16", 0),
                    ("H5", "ok", "x2", "2026-11-16", 10)])
    n = st.path_stats(hours=24)["q"]
    assert n["retired_paths"] == []
    assert n["query_rate_live"] == n["query_rate"]
    a = advise("q", {}, {}, node=n)
    assert a["state"] == "ok"
