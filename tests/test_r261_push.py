# -*- coding: utf-8 -*-
"""r261 告警链守卫测试：双渠道毒价互抬穿透的混合池补层。

P0 复现（双渠道同轮毒价互抬分类池锚、毒价直通达标推送 7 次触达的
实锤形态，取证于 DB 10-04 15:34 轮）：qunar 1034 + ctrip 1100 同指纹
中转毒价，分类池 others 中位 1647.5、0.5×=823 双双逃过。守卫判定
粒度对齐（曲线端行级混合池同构）：告警链补明细混合池第二层 +
platform_mins 行级混合池（与 webui _state 行级守卫同判据）。
互抬对的解救机理=混合池锚供给变宽（健康锚进中位对抬线）；
健康锚供给不足时互抬属纯统计无解的数学边界，宁漏勿假守卫。
"""
import json
import logging

from core.alerter import Alerter
from core.models import FlightPrice, Route

_LOG = logging.getLogger("t261")


def _f(price, code, dpt, art, trans="", plat="qunar", dep="2026-10-06"):
    return {"price": price, "name": code, "code": code, "depTime": dpt,
            "arrTime": art, "depDate": dep, "arrDate": dep,
            "transCity": trans, "totalDuration": "8时45分",
            "_platform": plat}


def _plat(plat, rows, fc="URC", tc="SHA", d="2026-10-06"):
    """生产形态：每渠道一条 FlightPrice，extra=该渠道全部明细。"""
    return FlightPrice(platform=plat, from_city=fc, to_city=tc,
                       depart_date=d,
                       price=min(f["price"] for f in rows),
                       extra=json.dumps(rows, ensure_ascii=False))


def _route(**kw):
    base = dict(from_code="URC", from_name="乌鲁木齐", to_code="SHA",
                to_name="上海", dates=["2026-10-06"],
                alert_direct=1600, alert_transfer=1700)
    base.update(kw)
    return Route(**base)


def _dual_phantom_prices():
    """10-04 15:34 轮真实形态（毒价+同轮健康明细，值取自 DB 取证；
    渠道构成=行级池 5 渠道、中转明细 3 渠道——互抬穿透的前提是健康
    锚供给方在场，2 渠道互抬属纯统计无解的数学边界）。"""
    qunar = [_f(1034, "东航MU6108/MU9192", "14:30", "23:10", trans="兰州"),
             _f(2054, "天山GS7495/HO1236", "07:40", "09:50", trans="郑州"),
             _f(2244, "天山GS7495/HO1216", "07:40", "21:30", trans="郑州"),
             _f(1656, "上海FM9222", "09:05", "13:55"),
             _f(2344, "南航CZ6981", "18:30", "23:40")]
    ctrip = [_f(1100, "东航MU6108/MU9192", "14:30", "23:10", trans="兰州",
                plat="ctrip"),
             _f(2380, "乌鲁木齐UQ2545/HO1074", "10:15", "22:50",
                trans="郑州", plat="ctrip"),
             _f(2410, "春秋9C8866", "19:20", "23:55", plat="ctrip")]
    tuniu = [_f(2195, "东航MU6108/MU5138", "19:55", "09:10", trans="郑州",
                plat="tuniu"),
             _f(2360, "吉祥HO2214", "19:05", "23:55", plat="tuniu")]
    fliggy = [_f(2410, "南航CZ6981", "18:30", "23:40", plat="fliggy")]
    tc = [_f(2288, "东航MU6108/MU5152", "19:55", "10:45", trans="郑州",
             plat="tongcheng"),
          _f(2344, "南航CZ6981", "18:30", "23:40", plat="tongcheng")]
    return [_plat("qunar", qunar), _plat("ctrip", ctrip),
            _plat("tuniu", tuniu), _plat("fliggy", fliggy),
            _plat("tongcheng", tc)]


def test_dual_channel_phantom_blocked_by_mixed_pool():
    """毒价互抬穿透复现：分类池拦不住的 1034/1100，混合池补层必须拦。"""
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(), _dual_phantom_prices())
    assert len(secs) == 1
    s = secs[0]
    xp = [(p, int(v)) for p, v in s["xphans"]]
    assert ("qunar", 1034) in xp, f"qunar 毒价未被标记: {xp}"
    assert ("ctrip", 1100) in xp, f"ctrip 毒价未被标记: {xp}"
    # 达标/行情池均不见毒价（top_transfer=行情口径、pool=达标口径源）
    for pool_name in ("top_transfer", "pool", "all_flights"):
        got = {int(f["price"]) for f in s[pool_name]
               if f.get("price") is not None}
        assert 1034 not in got, f"{pool_name} 泄漏 qunar 毒价"
        assert 1100 not in got, f"{pool_name} 泄漏 ctrip 毒价"


def test_phantom_kept_out_of_platform_mins():
    """行级毒价不得进 platform_mins（图挂兜底「各渠道最低」文本行
    的次生泄漏面，与 webui _state 行级守卫同判据同输入）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(), _dual_phantom_prices())
    pm = secs[0]["platform_mins"]
    assert pm.get("qunar") != 1034, f"行级毒价泄漏 platform_mins: {pm}"
    assert pm.get("ctrip") != 1100, f"行级毒价泄漏 platform_mins: {pm}"
    # 健康行价不被误伤：剔除毒行后该渠道行价=剩余明细最低
    assert pm.get("qunar") == 1656 and pm.get("ctrip") == 2380, pm


def test_healthy_low_transfer_not_killed():
    """误杀面守护：真实低价中转（多渠道同水位，真降价案形态
    576-670 五渠道互证）不因混合池守卫陪葬。"""
    rows = [_f(590, "南航CZ6981", "18:30", "23:40"),
            _f(640, "东航MU8370", "09:00", "14:10", trans="西安")]
    prices = [_plat("qunar", rows),
              _plat("ctrip", [_f(600, "南航CZ6981", "18:30", "23:40",
                                 plat="ctrip"),
                              _f(670, "东航MU8370", "09:00", "14:10",
                                 trans="西安", plat="ctrip")]),
              _plat("tuniu", [_f(670, "南航CZ6981", "18:30", "23:40",
                                 plat="tuniu")])]
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(alert_direct=800, alert_transfer=800),
                             prices)
    s = secs[0]
    assert not s["xphans"], f"真降价被误拦: {s['xphans']}"
    assert min(int(f["price"]) for f in s["top_transfer"]) == 640


def test_thin_pool_mutual_lift_is_declared_boundary():
    """数学边界钉：健康锚供给不足（1 个健康渠道）时毒价对互抬
    纯统计不可分（两条毒价恰似真实双渠道价差），守卫不拦=诚实
    边界而非缺陷——锁死「不为个案引入假迭代/假守卫」的裁决。"""
    prices = [_plat("qunar", [_f(1034, "东航MU6108/MU9192", "14:30",
                                 "23:10", trans="兰州")]),
              _plat("ctrip", [_f(1100, "东航MU6108/MU9192", "14:30",
                                 "23:10", trans="兰州", plat="ctrip")]),
              _plat("tuniu", [_f(2300, "南航CZ6981", "18:30", "23:40",
                                 plat="tuniu")])]
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(), prices)
    assert secs[0]["xphans"] == [], (
        f"薄池互抬被「拦」=存在假守卫机制: {secs[0]['xphans']}")


def test_xchan_mark_call_count_constant():
    """性能钉：守卫调用次数每 section 恒定（分类池直飞/中转各 1 +
    混合池 1 = 3 次），随行数/渠道数恒定——曲线端曾有条件表达式
    退化 O(n²) 的先例，上界钉防同病。"""
    calls = {"n": 0}
    orig = Alerter._mark_xchan

    def _counting(rows):
        calls["n"] += 1
        return orig(rows)

    a = Alerter(_LOG, storage=None, digest=True)
    a._mark_xchan = _counting
    a._build_sections(_route(), _dual_phantom_prices())
    assert calls["n"] == 3, f"守卫调用次数漂移: {calls['n']}"
