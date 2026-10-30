# -*- coding: utf-8 -*-
"""r611：干预成功率不能被「远期偶然成功」冒充。

`intervention_success_rate()` 的判定是 `healed = any(win)`——窗口里只要有
**任意一条**成功就算这次干预救回来了。而窗口右界原先只有「下一次人工干预」；
对**最后一次**干预它为空，窗口一路延伸到 `now`。

窗口越宽越容易命中某次偶然成功，所以这个设计必然高估成功率。实测：

    干预后 24h 内 10 次全失败 → 20 天后因别的原因偶然成功一次
    旧实现：healed=1 / n=1 / rate=1.0     ← 读作「这次干预 100% 有效」
    真实：  这次干预根本没救回来

修法：窗口右界再加「干预后 N 小时」封顶（与 `intervention_effect` 同口径）；
有下一次干预时取更早的那个边界。

**必看的副作用**：更老的干预会因为落在 `hours` 窗口外而**不再出现在结果里**
（`n=None` 表示该动作没有可判样本），这是诚实的——不是「0 次成功」。
面板本来就按 `unjudged`/「样本不足」分开表述，不会把它读成失败。
"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fixture(*, fail_after=10, later_ok=True, days_later=20):
    """造一次 10 天前的干预：之后 N 小时全失败，远期（days_later）偶然成功。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "sr.db")
    st = PriceStorage(db)
    now = dt.datetime.now().replace(microsecond=0)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    t0 = now - dt.timedelta(days=10)
    with st._conn() as c:
        c.execute("UPDATE interventions SET at=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"),))
        rows = [("fail", t0 + dt.timedelta(hours=i + 1))
                for i in range(fail_after)]
        if later_ok:
            rows.append(("ok", now - dt.timedelta(days=days_later)))
        for s, at in rows:
            c.execute(
                "INSERT INTO fetch_paths(platform,entry_path,path_status,"
                "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
                ("ctrip", "PC", s, "SHA", "BJS", "2026-11-01",
                 at.strftime("%Y-%m-%d %H:%M:%S")))
    return st


def test_far_future_success_does_not_heal_the_intervention():
    """干预后 24h 全失败 → 不能因为在 20 天后偶然成功就记 healed。"""
    st = _fixture(fail_after=10, later_ok=True, days_later=20)
    d = st.intervention_success_rate(hours=24).get("warmup") or {}
    assert d.get("healed") != 1, (
        "远期偶然成功被当成干预生效（healed=%r, rate=%r）"
        % (d.get("healed"), d.get("rate")))


def test_immediate_success_still_counts():
    """真在窗口内恢复的仍必须算 healed——收紧窗口不能把好的也判没。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "ok.db")
    st = PriceStorage(db)
    now = dt.datetime.now().replace(microsecond=0)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    t0 = now - dt.timedelta(hours=3)
    with st._conn() as c:
        c.execute("UPDATE interventions SET at=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"),))
        c.execute(
            "INSERT INTO fetch_paths(platform,entry_path,path_status,"
            "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
            ("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-01",
             (t0 + dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")))
    d = st.intervention_success_rate(hours=24).get("warmup") or {}
    assert d.get("healed") == 1 and d.get("n") == 1, d


def test_next_intervention_still_closes_the_window():
    """有下一次人工干预时，窗口仍须在那一刻结束（不能被 N 小时拉长）。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "nxt.db")
    st = PriceStorage(db)
    now = dt.datetime.now().replace(microsecond=0)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    st.save_intervention("ctrip", "verify", before="fail", after="")
    with st._conn() as c:
        marks = list(c.execute(
            "SELECT id, at FROM interventions ORDER BY id").fetchall())
        t0 = now - dt.timedelta(hours=6)
        t1 = now - dt.timedelta(hours=2)
        c.execute("UPDATE interventions SET at=? WHERE id=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"), marks[0]["id"]))
        c.execute("UPDATE interventions SET at=? WHERE id=?",
                  (t1.strftime("%Y-%m-%d %H:%M:%S"), marks[1]["id"]))
        # 成功时刻在两次干预之间 → 属于第一次干预；在第二次之后再说
        c.execute(
            "INSERT INTO fetch_paths(platform,entry_path,path_status,"
            "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
            ("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-01",
             (t0 + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
        c.execute(
            "INSERT INTO fetch_paths(platform,entry_path,path_status,"
            "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
            ("ctrip", "PC", "ok", "SHA", "BJS", "2026-11-01",
             (t1 + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
    r = st.intervention_success_rate(hours=24)
    assert (r.get("warmup") or {}).get("healed") == 1, r
    assert (r.get("verify") or {}).get("healed") == 1, r
