# -*- coding: utf-8 -*-
"""v1.5.85 推送审校立案落地(字节预算规模化+recheck 徽标+尾注丢失面)。

审计立案(_scratch/r184_push_audit.md):
- 立案 P2-②:达标节恒全量无字节上限——20 航线全达标实测 desp
  31506B 击穿 17900B 发送端切点,截断吃掉尾部明细总表(比价唯一
  载体)与 @手机号段(触达载体)。修法:hit 行(head/seg/tail 全量
  vs head 价格判据地板档)与 sec 节共用预算,head 总额预留制(地板
  档恒落位靠预算设计,LESSONS 二十五§2);尾段预留 1500→1800B。
- 立案 P2-①:transferBaggage='recheck'(需转运,fliggy 真实值域)
  WebUI 明细行有标签而 PNG 徽标只有直挂/经停两态——直挂筛选航线
  上「达标失效」判据图上看不出。修法:badge 链补 recheck 分支。
- 审校建议:notifier 截断尾注补「@提醒」丢失面(此前尾注只提
  总表/对账段,@段结构性垫底被吃却无人知晓)。

运行:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v185_push.py -q
"""

import datetime as dt
import json
import logging

from core.alerter import Alerter
from core.models import FlightPrice, Route


def _fp(price, name, dpt, art, dep):
    d0 = dt.date.fromisoformat(dep)
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep,
            "arrDate": str(d0 + dt.timedelta(days=1)),
            "transCity": "", "crossDayDesc": "+1天",
            "totalDuration": "6时", "_platform": "qunar"}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _alerter():
    log = logging.getLogger("v185probe")
    logging.basicConfig(level=logging.CRITICAL)

    class FakeN:
        def send(self, *a, **k):
            return True
    return Alerter(log, notifier=FakeN(), storage=None, digest=True,
                   at_mobile="13800001234", storm_repeat=0, user="probe")


def _built(a, n_routes):
    """n_routes 条全达标航线 × 2 日期(规模化达标压力场景)。"""
    built = []
    for i in range(n_routes):
        d1 = "2026-10-0%d" % (1 + i % 9)
        d2 = "2026-10-1%d" % (i % 10)
        r = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐%d" % i, dates=[d1, d2],
                  alert_direct=5000, alert_transfer=0)
        p1 = _ps([_fp(2000 - i, "南航CZ697%d" % i, "17:05", "00:05", d1)],
                 "SHA", "URC", d1)
        p2 = _ps([_fp(2100 - i, "南航CZ698%d" % i, "18:30", "23:40", d2)],
                 "SHA", "URC", d2)
        built.append((r, a._build_sections(r, p1 + p2)))
    return built


class TestDigestBudgetScale:
    """立案 P2-②:规模化达标不击穿发送端切点,判据地板档恒落位。"""

    def test_qualified_scale_within_byte_ceiling(self):
        a = _alerter()
        pv = a._digest_payload(_built(a, 20), fresh=True, with_tables=False)
        b = len(pv["desp"].encode("utf-8"))
        # 构建端份额控制:20 航线全达标实测曾 31506B——发送端 17900B
        # 截断吃掉尾部总表/@段;构建端受控后恒 ≤17800(留尾注余量)
        assert b <= 17800, f"规模化达标 desp 超预算: {b}B"

    def test_hit_head_verdicts_survive(self):
        a = _alerter()
        pv = a._digest_payload(_built(a, 20), fresh=True, with_tables=False)
        # 地板档=🔥 价格判据行:份额降级只丢 seg/tail(时刻/链接),
        # 判据(能不能出手、多少钱)40 条全保
        assert pv["desp"].count("🔥") == 40, \
            f"命中判据行被预算吞: {pv['desp'].count('🔥')}/40"

    def test_demote_note_covers_hit_loss(self):
        a = _alerter()
        pv = a._digest_payload(_built(a, 40), fresh=True, with_tables=False)
        # 40 航线强压场景触发 hit 降级:说明行钉死 hit 丢失面词面
        # (命中行仅价格),不能只说「航线较多」。全形态「仅价格判据」
        # 55/40 超宽(审校 P2-1),降级等义压缩档保「命中行仅价格」
        assert "命中行仅价格" in pv["desp"], \
            "降级说明行缺 hit 丢失面语义"


class TestRecheckBadgeAndTailNote:
    """立案 P2-①+审校建议:recheck 徽标与截断尾注 @提醒。"""

    def test_report_badge_chain_has_recheck(self):
        import report
        with open(report.__file__, encoding="utf-8") as f:
            src = f.read()
        i0 = src.index('if f.get("transferBaggage") == "direct":')
        seg = src[i0:i0 + 600]
        # badge 链补 recheck 分支(需转运:直挂筛选航线上达标失效
        # 的判据,图上看不出=图缺列表有)
        assert 'f.get("transferBaggage") == "recheck"' in seg, \
            "PNG badge 链缺 recheck(需转运)分支"
        assert "需转运" in seg, "recheck 徽标词面缺"

    def test_notifier_tail_note_mentions_at(self):
        import core.notifier as nt
        with open(nt.__file__, encoding="utf-8") as f:
            src = f.read()
        # 截断尾注补 @段丢失面:@手机号段结构性垫底,被截断时
        # 读者须知道高亮触达没了(钉钉 markdown 纯文本 @ 高亮在
        # 尾段被切即蒸发)
        assert "@提醒" in src, "发送端截断尾注未覆盖 @段丢失面"
