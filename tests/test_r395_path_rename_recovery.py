# -*- coding: utf-8 -*-
"""r395：通路改名后，复发账的「已恢复」判定不能失联。

真实 10-26/27 数据：同程国际 r384 把通路从「日历」换成「窗历」（同一
条业务通路的新入口名，单次 HTTP/航线、只出含税总价）。复发账按
`entry_path` 精确匹配成功行，于是旧「日历」的 12–15 次 soft_reject
永远等不到「窗历」的成功 —— 面板对 SHA→BKK/LHR/NRT/SIN 四线永久挂
「需人工」，而这几条线每轮都在出价（窗历 calendar 行）。这是把一个
可以自愈的状态说成必须人工介入，属于目标里「状态可区分」的反面。

修法：日历族（日历/窗历）按族匹配恢复；族外仍按字面入口名，避免
H5 的成功去顶日历的账（不同通路不互相担保）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import CAL_PATH_FAMILY  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def _db():
    d = tempfile.mkdtemp(prefix="tm_r395_")
    return PriceStorage(os.path.join(d, "prices.db"))


def _rows(store):
    return store.failure_recurrence(hours=24, min_count=1)


def test_family_is_shared_not_duplicated():
    """族表只有一份定义（pacing/storage 共用），避免两处漂移。"""
    assert CAL_PATH_FAMILY == ("日历", "窗历")
    import core.pacing as pacing
    src = open(pacing.__file__, encoding="utf-8").read()
    # 不得再各写一份字面量族表
    assert '_CAL_FAMILY = ("日历", "窗历")' not in src
    assert "_CAL_FAMILY = CAL_PATH_FAMILY" in src


def test_rename_counts_as_recovered():
    """旧「日历」失败 → 新「窗历」成功 = 已恢复（r384 真实形态）。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "窗历", "calendar", rows=1, note="同程低价日历 90 天窗口")
    rows = [r for r in _rows(s) if r["path"] == "日历"]
    assert rows, "复发组应仍在（毛病确实反复过）"
    assert rows[0]["status"] == "soft_reject"
    assert rows[0]["recovered"] is True, rows[0]


def test_other_paths_still_recovered_within_own_name():
    """族外不跨通路担保：H5 成功不能顶日历的账。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "H5", "ok", rows=20, note="www.ly.com H5 列表")
    rows = [r for r in _rows(s) if r["path"] == "日历"]
    assert rows[0]["recovered"] is False, rows[0]


def test_still_failing_after_rename_is_not_recovered():
    """窗历也失败时不得谎称已恢复（别把真故障洗白）。"""
    s = _db()
    for _ in range(2):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "窗历", "calendar", rows=1, note="同程低价日历 90 天窗口")
    s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                      "窗历", "soft_reject", note="窗历门拒 code=444")
    rows = [r for r in _rows(s) if r["path"] == "窗历"]
    assert rows, "窗历自身失败也要进复发账"
    assert rows[0]["recovered"] is False, rows[0]


def test_route_scoped_not_channel_wide():
    """别的航线成功不能顶本航线（原有语义不能因族匹配而放宽）。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                          "日历", "soft_reject", note="国际日历会话门拒 code=444")
    s.save_fetch_path("tongcheng", "SHA", "LHR", "2026-11-16",
                      "窗历", "calendar", rows=1, note="同程低价日历 90 天窗口")
    rows = [r for r in _rows(s) if r["to_city"] == "BKK"]
    assert rows[0]["recovered"] is False, rows[0]


def test_relabel_groups_merge_after_classification():
    """归类改写后同类要合并，不能并列出两条一模一样的行。

    真实形态（qunar API HAK→SHA）：SQL 先按 path_status 分成 login(4) 与
    empty(3) 两组，改写把 login 也判成 empty，界面上就成了
    「empty×4」和「empty×3」两条同名行——读者会以为是两件事。
    """
    s = _db()
    for _ in range(4):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "login",
                          note="原站返回无符合条件的航班（可能受指纹 SDK/风控环境影响）")
    for _ in range(3):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "empty",
                          note="原站返回符合条件的航班占位")
    rows = [r for r in _rows(s)
            if r["platform"] == "qunar" and r["path"] == "API"]
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "empty"
    assert rows[0]["count"] == 7, rows[0]


def test_relabel_merge_keeps_distinct_statuses_apart():
    """合并不许把不同状态揉成一团（soft_reject 与 empty 是两件事）。"""
    s = _db()
    for _ in range(3):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "login",
                          note="国际列表 1999/8 未登录硬拒")
    for _ in range(2):
        s.save_fetch_path("qunar", "HAK", "SHA", "2027-02-14", "API", "empty",
                          note="原站无符合条件的航班")
    rows = [r for r in _rows(s)
            if r["platform"] == "qunar" and r["path"] == "API"]
    assert sorted(r["status"] for r in rows) == ["empty", "soft_reject"], rows
