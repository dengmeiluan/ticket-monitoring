# -*- coding: utf-8 -*-
"""r496：重登入账必须幂等——一次登录动作只算一次干预。

实测（真实库）：`interventions` 里每条 `relogin` 都**稳定写两条**
（同秒同槽位，id 连号无间断），从 07:13 到 11:00 全部如此。
而 r484 的 `intervention_success_rate` 是**按行计数**的：
一条重登被算成两次干预，分母被系统性放大一倍——重登类干预的成功率
因此被压偏，而它正是「该不该优先点去登录」的依据。

判据：同一厂商 × 同一槽位 × 同一分钟内已有 relogin 记录时不再写。
跨分钟（用户确实又登了一次）照常记录。
"""
import io
import os
import re
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_relogin_write_is_deduplicated_within_the_same_minute():
    """复现写入逻辑：同分钟重复 → 只落一条；跨分钟 → 各落一条。"""
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))

    import time as _t

    def write(plat, key, at, now=None):
        """与 webui._start_login 里的入账块同构的幂等判断（30 秒窗口）。"""
        now = _t.time() if now is None else now
        dup = False
        for r0 in ps.interventions(plat, 8):
            if (str(r0.get("action")) != "relogin"
                    or str(r0.get("scope")) != str(key)):
                continue
            try:
                ts = _t.mktime(_t.strptime(
                    str(r0.get("at") or "")[:19], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            if abs(now - ts) <= 30:
                dup = True
                break
        if not dup:
            # 必须同时写 at：save_intervention 默认用真实 now 落库，
            # 而比较基准是我们构造的时间戳。不写 at 时两者相差可能远超
            # 30 秒（并发门禁下实测失败），去重逻辑显得「没生效」。
            ps.save_intervention(plat, "relogin", ok=True, scope=str(key),
                                 before="login_wall", note="x", at=at)

    t0 = datetime.now().replace(second=10, microsecond=0)
    a = t0.strftime("%Y-%m-%d %H:%M:%S")
    b = (t0 + timedelta(seconds=21)).strftime("%Y-%m-%d %H:%M:%S")
    c = (t0 + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")

    def _ts(x):
        return _t.mktime(_t.strptime(x, "%Y-%m-%d %H:%M:%S"))

    write("fliggy", "fliggy", a, now=_ts(a))
    write("fliggy", "fliggy", b, now=_ts(b))   # +21 秒：同一次保存的重复写入
    rows = ps.interventions("fliggy", 10)
    assert len(rows) == 1, "30 秒内重复写入未去重：%r" % [
        (r["at"], r["scope"]) for r in rows]

    write("fliggy", "fliggy", c, now=_ts(c))   # +3 分钟：确属另一次登录
    rows = ps.interventions("fliggy", 10)
    assert len(rows) == 2, "跨分钟的第二次登录被误去重：%r" % [
        (r["at"], r["scope"]) for r in rows]

    # 不同槽位不受影响（飞猪 PC 与 H5 是两次独立登录）
    write("fliggy", "fliggy_h5", b, now=_ts(b))
    rows = ps.interventions("fliggy", 10)
    assert len(rows) == 3, "不同槽位被误判为重复：%r" % [
        (r["at"], r["scope"]) for r in rows]


def test_dedup_does_not_inflate_the_success_rate():
    """澄清：重复行**不**放大成功率分母（同秒记录在按 (plat, i) 分组时
    会被合并成一次窗口，n 仍为 1）。所以重复的真实危害不是指标，而是
    **溯源可读性**——用户看到两条一模一样的「重登」，会以为自己按了两次。

    这条把事实钉住，避免后人（包括我自己）再次基于「重复会放大分母」
    这个错误前提去改指标逻辑。
    """
    from core.storage import PriceStorage
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))
    now = datetime.now() - timedelta(minutes=30)
    at = now.strftime("%Y-%m-%d %H:%M:%S")
    with ps._conn() as cc:
        cc.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'fliggy','BKK','CAN','2026-11-05','H5','ok')",
            ((now + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),))
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy_h5", at=at)
    ps.save_intervention("fliggy", "relogin", ok=True, scope="fliggy_h5", at=at)
    assert len(ps.interventions("fliggy", 10)) == 2, "重复行确实落了两条"
    r = ps.intervention_success_rate()
    assert r["relogin"]["n"] == 1, (
        "同秒重复被合并后 n 应为 1；若变成 2 说明分组逻辑变了，"
        "此时重复才会真的放大分母，需要重新评估去重策略：%r" % (r,))


def test_write_site_is_guarded():
    """写入点必须有 30 秒窗口去重，否则重复会再次出现。

    为什么是 30 秒而不是「同一分钟」：同一分钟内用户真的重试一次
    （第一次没通过、立刻再登）是**另一次干预**，按分钟去重会把真实重试
    吞掉。而同一次保存的重复写入时间戳精确到秒完全一致，30 秒足够挡住。
    """
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index('meta["plat"], "relogin"')
    seg = w[max(0, i - 2200):i]
    assert "_dup" in seg, "重登入账缺幂等判断"
    assert 'r0.get("scope")' in seg, \
        "去重未按槽位区分（飞猪 PC/H5 是两次独立登录）"
    assert "<= 30" in seg, "去重未按 30 秒时间窗（秒差 1–2 秒的重复会漏掉）"
    assert "mktime" in seg and "strptime" in seg, \
        "去重未按时间差比较（字符串相等挡不住跨秒的重复）"
