# -*- coding: utf-8 -*-
"""r1063 T209-T210：App 日期视野可配置 + 智行长窗口日历**整窗收割**。

真机证据链：
1. 用户截图：智行 App 的"选择日期"弹层有整月价格；携程 App 列表能显示 01/29 带价
   —— 说明 `date_horizon_days = 62`（2026-11-05 的实测结论）至少对智行/携程偏保守。
2. 探针（16:01）：`长窗口日历 1 天 / 已渲染 61 格（有价 53）`
   —— **一屏已经拿到 53 个有价日期，却只留下订阅的那 1 天**。
3. 整窗收割后（16:04）：`长窗口日历 53 天 / 已渲染 61 格（有价 53）`
   —— 同一次抓取、63 秒，行数 1 → 53。

边界：日历价 = 每天最低价、无航班号，detail 里如实标注"另含 N 格非订阅日期
（日历价，非明细）"，读表的人不会把它当明细。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_horizon_is_configurable():
    import logging

    from crawlers import REGISTRY
    cls = REGISTRY["app_ctrip"]
    log = logging.getLogger("t")
    assert cls({}, log)._horizon_days() == 62, "默认必须保持既有行为"
    assert cls({"app_date_horizon_days": 120}, log)._horizon_days() == 120
    assert cls({"app_date_horizon_days": 120,
                "app_date_horizon_days_map": {"app_ctrip": 200}},
               log)._horizon_days() == 200, "按渠道优先"
    # 越界值不接受（防手滑写成 0 或天文数字）
    assert cls({"app_date_horizon_days": 0}, log)._horizon_days() == 62


def test_horizon_reject_uses_config():
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    i = src.index("def reject_far_dates")
    seg = src[i:i + 900]
    assert "_horizon_days()" in seg, "守卫必须用可配置视野，不能再用写死的常量"


def test_zhixing_calendar_harvests_whole_window():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert "app_calendar_harvest_all" in src
    assert "app_calendar_harvest_cap" in src
    i = src.index("_extra_days")
    seg = src[i - 600:i + 600]
    assert "另含" in src, "要在 detail 里如实标注非订阅日期"
    # 无价格子不该被算成"收了"
    assert 'price is None' in seg
