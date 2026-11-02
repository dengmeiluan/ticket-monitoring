# -*- coding: utf-8 -*-
"""r610：干预前后必须用**同样长**的窗口比，否则效果会被历史稀释。

`intervention_effect()` 的 before 取「干预前 N 小时」，而 after 原先写的是
`fetched_at >= at`——**一路统计到现在**。后果：

  干预当场就生效（之后 24h 内 10/10 成功），但 8 天后渠道又因别的原因恶化，
  那 90 条失败仍然落进 after → 1/100 = 10%，面板写「干预未见改善」。
  用户看到的是「上次干预无效」，而它其实救回来过。

实测（本文件复现）：before=0.0(n=10) / after=1.0(n=10) 才是事实；
旧实现对同一份数据给 after=0.1(n=100)。

注意：**不要**因此丢掉回落观测——`trend`（30 分钟分桶序列）与
`regressed` 本来就是为「先好后坏」准备的，它们看的是干预之后的全程，
与 after 的"同窗口效果"是两件事。
"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fixture(before_ok, after_ok, later_ok, days_later=8):
    """造一份干预前后数据：T0 为干预时刻（10 天前）。"""
    from core.storage import PriceStorage
    db = os.path.join(tempfile.mkdtemp(), "iv.db")
    st = PriceStorage(db)
    st.save_intervention("ctrip", "warmup", before="fail", after="")
    now = dt.datetime.now().replace(microsecond=0)
    t0 = now - dt.timedelta(days=10)
    with st._conn() as c:
        c.execute("UPDATE interventions SET at=?",
                  (t0.strftime("%Y-%m-%d %H:%M:%S"),))
        rows = []
        for i in range(10):
            rows.append(("ok" if i < before_ok else "fail",
                         (t0 - dt.timedelta(hours=i + 1))))
        for i in range(10):
            rows.append(("ok" if i < after_ok else "fail",
                         (t0 + dt.timedelta(hours=i + 1))))
        span = max(1, days_later)
        for i in range(30):
            rows.append(("ok" if i < later_ok else "fail",
                         (t0 + dt.timedelta(days=2 + i % span))))
        for s, at in rows:
            c.execute(
                "INSERT INTO fetch_paths(platform,entry_path,path_status,"
                "from_city,to_city,depart_date,fetched_at) VALUES(?,?,?,?,?,?,?)",
                ("ctrip", "PC", s, "SHA", "BJS", "2026-11-01",
                 at.strftime("%Y-%m-%d %H:%M:%S")))
    return st


def test_after_is_bounded_by_the_same_window():
    """干预后 24h 全成功、之后持续恶化 → after 必须仍是 1.0，不是被稀释的低值。"""
    st = _fixture(before_ok=0, after_ok=10, later_ok=0)
    e = st.intervention_effect("ctrip", hours=24)
    assert e["after_n"] <= 20, (
        "干预后统计越过了同窗口（%d 条样本），会被远期恶化稀释" % e["after_n"])
    assert e["after"] == 1.0, "干预后 24h 实际全成功，却被算成 %r" % e["after"]
    assert e["before"] == 0.0


def test_window_is_symmetric_in_sample_count():
    """两段窗口等长时，样本量应当同量级（不是一边 10 一边 100）。"""
    st = _fixture(before_ok=0, after_ok=10, later_ok=0)
    e = st.intervention_effect("ctrip", hours=24)
    assert abs(e["after_n"] - e["before_n"]) <= 5, (
        "before=%d 条 / after=%d 条：窗口不等长，两个百分比不可比"
        % (e["before_n"], e["after_n"]))


def test_regression_is_still_reported():
    """收紧 after 窗口后，「先好后坏」仍必须能被判出来（trend/regressed 不受影响）。"""
    from core.pacing import effect_verdict
    st = _fixture(before_ok=0, after_ok=10, later_ok=0)
    v = effect_verdict(st.intervention_effect("ctrip", hours=24))
    assert v[0] == "regressed", (
        "干预后回落没有被判出来（收紧窗口不该影响回落观测）：%r" % (v,))


def test_real_improvement_is_reported():
    from core.pacing import effect_verdict
    st = _fixture(before_ok=0, after_ok=10, later_ok=30)
    v = effect_verdict(st.intervention_effect("ctrip", hours=24))
    assert v[0] == "improved", v


def test_genuinely_ineffective_intervention_is_reported():
    from core.pacing import effect_verdict
    st = _fixture(before_ok=0, after_ok=0, later_ok=0)
    v = effect_verdict(st.intervention_effect("ctrip", hours=24))
    assert v[0] == "no_effect", v
