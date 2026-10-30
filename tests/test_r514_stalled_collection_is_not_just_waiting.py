# -*- coding: utf-8 -*-
"""r514：`after is None` 的两种原因必须分开说——「还没轮到采集」vs「采集停了」。

真实库（2026-10-29 16:05 实测，data/prices.db）：

    fliggy：最近一次重登 15:54，`after_n=0`，该渠道最后一条样本停在
            **10-28 14:33**（25.6 小时前）——整个采集当天没跑。
    qunar ：`after_n=120`，正常。

旧文案对两种情况一律写「干预后还没有新样本」。fliggy 这一天重登了 **103 次**，
读者看到的永远是「还没有新样本」，会一直等一个**不会来**的样本，而不是去看
采集为什么停了——这是「可判断 / 可干预的及时性」缺口。

判据：`该渠道最近一条样本 < 这次干预时刻` 且已过 ≥2 小时。
用 `after_n == 0` 判断是不对的：干预刚做完还没轮到采集时它也是 0，
那只是正常等待，不该报警。
"""
import os
import tempfile
from datetime import datetime, timedelta

from core.storage import PriceStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'%s','BKK','CAN','2026-11-05','H5',?)" % plat,
            (at, status))


def test_stalled_is_true_when_last_sample_predates_the_intervention():
    ps = _ps()
    now = datetime.now()
    iv_at = _fmt(now - timedelta(hours=1))
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy",
                         at=iv_at)
    # 最后一条样本在 26 小时前（早于干预，且已远超 2 小时）
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(hours=26)))
    e = ps.intervention_effect("fliggy", 24)
    assert e["stalled"] is True, \
        "采集停了 26 小时却没标出来：%r" % (e,)
    assert e["stalled_hours"] >= 25, e
    assert e["last_sample_at"], e
    assert e["after"] is None, e


def test_fresh_wait_is_not_reported_as_stalled():
    """干预刚做完、还没轮到采集：正常等待，不能报「采集已停」。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("fliggy", "probe", ok=True, at=_fmt(now))
    # 半小时前刚有样本（早于干预，但远不到停摆阈值）
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(minutes=30)))
    e = ps.intervention_effect("fliggy", 24)
    assert e["stalled"] is False, \
        "刚采集过却被报成停摆：%r" % (e,)
    assert e["stalled_hours"] is None, e


def test_threshold_boundary_is_two_hours():
    """2 小时是阈值：刚过线算停摆，线内不算——两侧都要钉，否则阈值会被改歪。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("fliggy", "probe", ok=True, at=_fmt(now))
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(hours=1, minutes=50)))
    assert ps.intervention_effect("fliggy", 24)["stalled"] is False, \
        "1h50m 没到阈值就被判停摆"

    ps2 = _ps()
    ps2.save_intervention("fliggy", "probe", ok=True, at=_fmt(now))
    _row(ps2, "fliggy", "ok", _fmt(now - timedelta(hours=2, minutes=20)))
    assert ps2.intervention_effect("fliggy", 24)["stalled"] is True, \
        "2h20m 已超阈值却没判停摆"


def test_samples_after_the_intervention_are_never_stalled():
    """干预后已经有样本：即使该渠道很久没再采，也不算「这次干预没被验证」。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("ctrip", "probe", ok=True,
                         at=_fmt(now - timedelta(hours=30)))
    _row(ps, "ctrip", "ok", _fmt(now - timedelta(hours=29)))  # 干预后
    e = ps.intervention_effect("ctrip", 72)
    assert e["after_n"] == 1, e
    assert e["stalled"] is False, \
        "干预后已有样本，却仍报采集停摆：%r" % (e,)


def test_stalled_is_per_channel_not_global():
    """单渠道停摆不得牵连其它渠道。"""
    ps = _ps()
    now = datetime.now()
    ps.save_intervention("fliggy", "relogin", ok=True, at=_fmt(now))
    _row(ps, "fliggy", "ok", _fmt(now - timedelta(hours=30)))
    ps.save_intervention("qunar", "probe", ok=True, at=_fmt(now))
    _row(ps, "qunar", "ok", _fmt(now - timedelta(hours=1)))
    assert ps.intervention_effect("fliggy", 24)["stalled"] is True
    assert ps.intervention_effect("qunar", 24)["stalled"] is False


def test_the_two_no_sample_states_read_differently_in_the_panel():
    """面板上两种状态必须是两句话，且停摆那句要点明时长与最后样本。"""
    import io
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "采集已停" in w, "面板没有区分「采集停了」"
    assert "这次干预还没被验证" in w, "停摆状态没有说明干预未经证实"
    assert w.count("干预后还没有新样本") >= 1, \
        "「正常等待」那句被删掉了（两种状态要并存）"
    # 两处追溯面板都要有
    assert w.count("eff.stalled") >= 2, \
        "只有一处面板区分了停摆：%d" % w.count("eff.stalled")
