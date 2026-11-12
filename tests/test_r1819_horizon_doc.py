# -*- coding: utf-8 -*-
"""r1819：视野预过滤的**实测证据**要落档（免得以后只剩"我以为生效了"）。"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doc():
    return io.open(os.path.join(ROOT, "docs", "DISPATCH_HORIZON.md"),
                   encoding="utf-8").read()


def test_doc_records_rule_and_evidence():
    d = _doc()
    for k in ("62 天", "_drop_far_app_channels", "[规划]",
              "2027-01-29", "数据没少", "unsupported"):
        assert k in d, "落档缺 " + k


def test_doc_keeps_browser_coverage_fact():
    d = _doc()
    # 浏览器接住这件事必须写明——否则以后有人会以为"剔掉=少采"
    for p in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        assert p in d, "缺浏览器覆盖证据：" + p
    assert "入库 5 条价" in d, "缺入库条数证据"


def test_doc_says_it_is_not_a_halt():
    d = _doc()
    assert "别把它当成" in d and "停手" in d, "没说明与停手的区别"
