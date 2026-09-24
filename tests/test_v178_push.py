# -*- coding: utf-8 -*-
"""tuniu 黑卡价标记：推送 PNG 决策字段次行槽位钉（源码级，同族先例
test_v172_push.py）。

槽位纪律：black 与 discount 同丢档（都解释价格；价格本体与恒保组
准点/餐食/托运不动）。哨兵不设（38.5% 频率必触 <10% 日警线假火，
备案 HANDOFF）。
"""

import report


class TestPushV178BlackCard:
    @staticmethod
    def _src():
        with open(report.__file__, encoding="utf-8") as f:
            return f.read()

    def test_black_slot_in_parts(self):
        """决策字段次行有 black 槽位（黑卡价词面挂 blackCard 条件）。"""
        src = self._src()
        assert '("black", ("黑卡价" if f.get("blackCard") else ""))' in src, \
            "PNG 次行缺 black 槽位"

    def test_black_in_drop_tiers(self):
        """black 入丢档链（与 discount 同档可丢，恒保组不动）。"""
        src = self._src()
        i0 = src.index("for _drop, _ss in (")
        seg = src[i0:i0 + 700]
        assert '"black"' in seg, "black 未入丢档链（超宽行背着它重试）"
