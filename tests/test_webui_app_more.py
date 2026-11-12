# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_app_calendar_gap.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sys


# ---- merged from tests/test_r1063_app_calendar_gap.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_gap_helpers_exist():
    s = _src("app_base.py")
    for fn in ("_calendar_min_gap_s", "_calendar_due", "_mark_calendar",
               "_calendar_stamp_path"):
        assert "def %s" % fn in s, "缺 %s" % fn


def test_gap_is_configurable_with_sane_bounds():
    import logging

    from crawlers import REGISTRY
    cls = REGISTRY["app_zhixing"]
    log = logging.getLogger("t")
    assert cls({}, log)._calendar_min_gap_s() == 3600, "默认一小时"
    assert cls({"app_calendar_min_gap_s": 0}, log)._calendar_min_gap_s() == 0
    assert cls({"app_calendar_min_gap_s": 999999}, log)._calendar_min_gap_s() \
        == 24 * 3600, "上限一天，防手滑写成天文数字"


def test_due_then_mark_then_not_due(tmp_path, monkeypatch):
    import logging

    from crawlers import REGISTRY
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    c = REGISTRY["app_zhixing"]({"app_calendar_min_gap_s": 3600,
                                "user_data_dir": str(tmp_path)},
                               logging.getLogger("t"))
    c.user_data_root = str(tmp_path)
    assert c._calendar_due() is True, "没有时间戳时应当放行"
    c._mark_calendar()
    assert c._calendar_due() is False, "刚刷过就该拦"
    # 间隔设 0 = 不限频
    c2 = REGISTRY["app_zhixing"]({"app_calendar_min_gap_s": 0,
                                 "user_data_dir": str(tmp_path)},
                                logging.getLogger("t"))
    c2.user_data_root = str(tmp_path)
    assert c2._calendar_due() is True


def test_fetch_skips_calendar_but_keeps_detail_path():
    s = _src("app_zhixing.py")
    assert "_calendar_due()" in s, "fetch 里必须问一次"
    assert "本轮只做明细" in s, "跳过时要如实记账，不能静默"
    # 明细块必须仍在日历块之外/之后执行
    i_cal = s.index("_cal_due")
    i_detail = s.index("_enter_detail_and_parse", i_cal)
    assert i_detail > i_cal, "明细必须在日历之后照常执行（不能被连累）"
