# -*- coding: utf-8 -*-
"""达标警报链路离线演练·聚合版（一轮一消息，不真发钉钉，FakeN 捕获）。

运行：python tests/test_alert_path.py
覆盖：聚合 title（方向+日期）/🚨/@手机/正文高亮/走势图/明细总表/达标行/
出发时段窗口过滤——每次改推送逻辑后应复跑本演练。
"""
import logging
import sys
import os
import json
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402
from core.models import Route, FlightPrice  # noqa: E402


def _fp(price, name, dpt, art, trans="", cross="", plat="qunar", dep="2026-09-25"):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else (2 if cross == "+2天" else 0)
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep,
            "arrDate": str(d0 + dt.timedelta(days=days)),
            "transCity": trans, "crossDayDesc": cross,
            "totalDuration": "6时", "_platform": plat}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def main():
    log = logging.getLogger("probe")
    logging.basicConfig(level=logging.WARNING)
    captured = []

    class FakeN:
        def send(self, t, d, at_mobiles=None, is_at_all=False):
            captured.append((t, d, at_mobiles))
            return True

    a = Alerter(log, notifier=FakeN(), storage=None, digest=True,
                at_mobile="13800001234", storm_repeat=1, user="演练")
    a.round_charts = {("SHA", "URC", "2026-09-25"): "https://iili.io/fake1.png",
                      ("URC", "SHA", "2026-10-04"): "https://iili.io/fake2.png"}
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-09-25"],
               alert_direct=1900, alert_transfer=1700)
    p1 = _ps([_fp(2451, "南航CZ6976", "17:05", "00:05", cross="+1天"),
              _fp(1917, "Y87519", "12:05", "20:55", trans="郑州",
                  plat="ctrip")], "SHA", "URC", "2026-09-25")
    r2 = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
               to_name="上海", dates=["2026-10-04"],
               alert_direct=1600, alert_transfer=0, dep_time_min="17:00")
    p2 = _ps([_fp(1599, "南航CZ6981", "18:30", "23:40", dep="2026-10-04"),
              _fp(1780, "东航MU8370", "09:00", "14:10",
                  dep="2026-10-04")], "URC", "SHA", "2026-10-04")
    a.check_multi([(r1, p1), (r2, p2)])
    t, d, at = captured[0]
    checks = {
        "🚨聚合title（方向+日期）": (
            t.startswith("🚨 达标！乌→上 10/04 直飞￥1599")
            and "上→乌 09/25" in t),
        "@手机号": at == ["13800001234"],
        "正文@高亮": "@13800001234" in d,
        "两航线小节标题": d.count("## ✈️") == 2,
        "出发时段窗口标注": "17:00" in d and "出发" in d,
        "窗口过滤掉早班": "09:00" not in d.split("明细总表")[0],
        "每航线走势图": d.count("![走势](https://iili.io/") == 2,
        "明细总表图": "明细总表" in d,
        "达标行含航线标注": "乌→上 10/04" in d.split("🔥")[1][:80],
    }
    # 预览构建器对等性：同一数据构建 title/desp 与真实推送一致，
    # 且零副作用（不重发、不写库、跳过总表图床上传）
    built = [(r1, a._build_sections(r1, p1)), (r2, a._build_sections(r2, p2))]
    n_before = len(captured)
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    checks["预览title与真实推送一致"] = pv["title"] == t
    checks["预览正文含走势图"] = pv["desp"].count("![走势](https://iili.io/") == 2
    checks["预览正文含@高亮"] = "@13800001234" in pv["desp"]
    checks["预览跳过总表上传"] = "明细总表" not in pv["desp"]
    checks["预览无发送副作用"] = len(captured) == n_before
    checks["预览持续达标标题"] = a._digest_payload(
        built, fresh=False, with_tables=False)["title"].startswith("🔔 持续达标")
    # 电话通道守卫：未达标零触达 + 达标极简文案（重构曾吞掉 if hits 守卫）
    from core.notifier import AliyunAlertNotifier
    sent_ay = []

    class SpyAY(AliyunAlertNotifier):
        def __init__(self):
            pass

        def send(self, t, d):
            sent_ay.append((t, d))
            return True

    a2 = Alerter(log, notifier=FakeN(), storage=None, digest=True,
                 storm_repeat=1, user="演练", urgent_notifier=[SpyAY()])
    a2.round_charts = {}
    hi = _ps([_fp(1850, "南航CZ6976", "17:05", "00:05", cross="+1天")],
             "SHA", "URC", "2026-09-25")
    lo = _ps([_fp(2451, "南航CZ6976", "17:05", "00:05", cross="+1天")],
             "SHA", "URC", "2026-09-25")
    a2.check_multi([(r1, lo)])
    checks["未达标电话零触达"] = not sent_ay
    a2.check_multi([(r1, hi)])
    if sent_ay:
        t2, d2 = sent_ay[0]
        checks["达标电话极简文案"] = ("机票达标" in t2 and "立即下单" in d2
                                      and len(d2) < 60)
    # 免打扰时段（v3.0）：跨零点窗口判定 + 心跳静默 + 达标降级（电话/风暴抑制）
    from datetime import datetime as _dtm
    a3 = Alerter(log, notifier=None, storage=None, digest=True,
                 storm_repeat=3, user="演练",
                 quiet_start="23:00", quiet_end="07:00")
    checks["静默窗口跨零点判定"] = (
        a3._in_quiet(_dtm(2026, 9, 10, 23, 30))
        and a3._in_quiet(_dtm(2026, 9, 11, 2, 0))
        and not a3._in_quiet(_dtm(2026, 9, 10, 12, 0))
        and not a3._in_quiet(_dtm(2026, 9, 10, 7, 0)))
    checks["静默未配置不启用"] = not Alerter(log)._in_quiet(
        _dtm(2026, 9, 10, 23, 30))

    n3, ay3, nt3 = [], [], []

    class FakeN3:
        def send(self, t, d, at_mobiles=None, is_at_all=False):
            n3.append(t)
            return True

    class SpyAY3(AliyunAlertNotifier):
        def __init__(self):
            pass

        def send(self, t, d):
            ay3.append(t)
            return True

    class FakeNT3:
        def send(self, t, d, at_mobiles=None, is_at_all=False):
            nt3.append(t)
            return True

    a3 = Alerter(log, notifier=FakeN3(), storage=None, digest=True,
                 storm_repeat=3, user="演练",
                 urgent_notifier=[SpyAY3(), FakeNT3()],
                 quiet_start="23:00", quiet_end="07:00")
    a3._in_quiet = lambda: True          # 注入静默（测试不依赖真实时刻）
    a3.round_charts = {}
    a3.check_multi([(r1, lo)])
    checks["静默时段心跳零触达"] = not n3
    a3.check_multi([(r1, hi)])
    checks["静默达标主推照发"] = len(n3) == 1
    checks["静默达标ntfy照发"] = len(nt3) == 1
    checks["静默时段电话抑制"] = not ay3
    a4 = Alerter(log, notifier=FakeN3(), storage=None, digest=True,
                 storm_repeat=1, user="演练",
                 quiet_start="23:00", quiet_end="07:00")
    a4._in_quiet = lambda: False         # 窗口外：心跳正常推
    a4.round_charts = {}
    a4.check_multi([(r1, lo)])
    checks["非静默心跳正常推"] = len(n3) == 2

    bad = [k for k, v in checks.items() if not v]
    for k, v in checks.items():
        print((" ✓ " if v else " ✗ ") + k)
    assert not bad, "聚合达标链路演练失败: %s" % bad
    print("=== 聚合达标链路演练全过 ===")


if __name__ == "__main__":
    main()
