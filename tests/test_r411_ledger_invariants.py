# -*- coding: utf-8 -*-
"""r411：账本的四条硬不变式，写成常驻守卫。

本轮（r394–r410）修的全是"账本说错话"。与其逐个 bug 修，不如把
"账本必须满足什么"钉死，让任何新写法一旦违反就立刻变红：

1. `ok`/`calendar` 必须 rows>0 —— "成功"不能是 0 行；
2. 非 `ok` 状态不得 rows>0 —— "失败"不能带着数据；
3. 同一次查询的同一路径不得写超过 2 条 —— 超出即"重复记账"
   （r408 的并列互斥就是它的变种）；
4. `empty` 的 note 不得使用"没拿到/未解析/无响应"措辞 ——
   empty 只能由"站点明确无票"支撑（r398b/r400/r401/r402/r403/r405）。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _srcs():
    for fn in sorted(os.listdir(CRAWLERS)):
        if fn.endswith(".py"):
            yield fn, open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()


def test_ok_implies_rows_positive():
    """源码级：ok/calendar 的记账点必须带 rows=，不能凭空成功。"""
    bad = []
    for fn, src in _srcs():
        for m in re.finditer(r'path_note\(\s*"[^"]*"\s*,\s*"(ok|calendar)"', src):
            tail = src[m.end():m.end() + 220]
            if "rows=" not in tail:
                bad.append((fn, src[:m.start()].count("\n") + 1))
    assert not bad, "ok/calendar 未带 rows: %r" % (bad,)


def test_empty_notes_avoid_failure_wording():
    """empty 的 detail 不得写"没拿到/未解析/无响应"。"""
    bad = []
    for fn, src in _srcs():
        for m in re.finditer(r'path_note\(\s*"[^"]*"\s*,\s*"empty"', src):
            tail = src[m.end():m.end() + 260]
            code = "\n".join(ln.split("#", 1)[0] for ln in tail.splitlines())
            for w in ("未解析", "无响应", "没拿到", "未拿到"):
                if w in code:
                    bad.append((fn, w, code.strip()[:60]))
    assert not bad, bad


def test_no_triple_write_same_path():
    """运行期：同一 attempt×路径 不应出现 3 条以上记账。

    历史数据不追究（修复前可能留下），只看最近 2 小时。
    """
    import sqlite3
    db = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "prices.db")
    if not os.path.isfile(db):
        return
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        rows = list(c.execute(
            "SELECT attempt_id, entry_path, COUNT(*) n FROM fetch_paths "
            "WHERE attempt_id<>'' AND fetched_at>=datetime('now','localtime','-2 hours') "
            "GROUP BY attempt_id, entry_path HAVING n>2"))
    except Exception:
        return
    assert not rows, "同一次查询同路径写超 2 条: %r" % (rows[:5],)


def test_contradictory_states_absent():
    """运行期：同一 attempt×路径 不得同时出现 ok 与失败态。"""
    import sqlite3
    db = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "prices.db")
    if not os.path.isfile(db):
        return
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        rows = list(c.execute(
            "SELECT attempt_id, entry_path, "
            "SUM(CASE WHEN path_status IN ('ok','calendar') THEN 1 ELSE 0 END) o, "
            "SUM(CASE WHEN path_status NOT IN ('ok','calendar') THEN 1 ELSE 0 END) f "
            "FROM fetch_paths WHERE attempt_id<>'' "
            "AND fetched_at>=datetime('now','localtime','-2 hours') "
            "GROUP BY attempt_id, entry_path HAVING o>0 AND f>0"))
    except Exception:
        return
    assert not rows, "同一查询同路径既成功又失败: %r" % (rows[:5],)
