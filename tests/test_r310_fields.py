# -*- coding: utf-8 -*-
"""ctrip avgDelay/planeAge 空串落键收口（r310 观测立案）：

观测实录（_scratch/r310_observe_C.md §1.2）：ctrip 组装字典对
avgDelay 无条件落键，extendinfos 缺「平均延误N分钟」content 的行以
空串占位平铺（近 3 天 10,493/25,228 元素，10-10 15:43:11 起新形态）；
同字典 planeAge 同型（8,209 空串）。对照 tongcheng `!= ""` 门与五渠
道「无值不落键」律收口——缺席与空串在消费端等价（webui int()
try/except→None、哨兵 isinstance/str().strip() 计数口径对两形态同
行为，收口纯载荷卫生）。门型取 `!= ""` 不取 truthy：平均延误 0 分
钟/机龄 0 年是渠道显式真值，truthy 门会吞 0（LESSONS 卅§4）。

样本形态取自生产 dump 结构（policyinfo[].classinfor[].extendinfos[]
.content，test_v1551_regress 同款夹具）。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r310_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_r310")
_CT = CtripCrawler({}, _LOG)


def _parse(extend):
    seg = {"basinfo": {"flgno": "MU5137"},
           "dateinfo": {"ddate": "2026-10-15 08:00:00",
                        "adate": "2026-10-15 11:30:00"},
           "aportinfo": {"city": "上海"}}
    ci = {"cgrd": 0, "prate": 96, "meal": "有餐食",
          "extendinfos": extend}
    obj = {"fltitem": [{"mutilstn": [seg],
                        "policyinfo": [{"tprice": 1200, "quantity": 1,
                                        "classinfor": [ci]}]}]}
    rows = _CT._extract_ctrip_flights(json.dumps(obj, ensure_ascii=False))
    assert rows
    return rows[0]


def test_avgdelay_no_content_no_key():
    """extendinfos 无「平均延误N分钟」content → avgDelay 键不落。"""
    r = _parse([{"content": "机龄8年"}])
    assert "avgDelay" not in r, r.get("avgDelay")


def test_avgdelay_int_and_zero_fall():
    """有 content 落 int；0 分钟是渠道显式真值照落（!= "" 门非 truthy）。"""
    r = _parse([{"content": "平均延误21分钟"}])
    assert r["avgDelay"] == 21
    r0 = _parse([{"content": "平均延误0分钟"}])
    assert r0["avgDelay"] == 0


def test_planeage_no_content_no_key():
    """extendinfos 无机龄 content → planeAge 键不落。"""
    r = _parse([{"content": "平均延误21分钟"}])
    assert "planeAge" not in r, r.get("planeAge")


def test_planeage_falls_and_zero_year_kept():
    """有 content 落词面；机龄 0 年照落（truthy 门会吞「0」）。"""
    r = _parse([{"content": "机龄8年5个月"}])
    assert r["planeAge"] == "8.4"
    r0 = _parse([{"content": "机龄0年"}])
    assert r0["planeAge"] == "0"


def test_both_absent_empty_extendinfos():
    """extendinfos=[] → 两键双双不落（空串占位平铺收口主形态）。"""
    r = _parse([])
    assert "avgDelay" not in r, r.get("avgDelay")
    assert "planeAge" not in r, r.get("planeAge")


def test_scheduler_misfire_grace_pinned():
    """接力调度器必须带 misfire 宽限窗：满载外邻作业窗口内 due 轮
    被 misfire 丢弃后，显式接力无人排定=调度链静默死亡（进程活、
    端口听、零扫描）。宽限窗让迟到轮照跑、接力链自愈。"""
    from core import scheduler as sch

    added = {}

    class FakeSched:
        def __init__(self, timezone=None):
            pass

        def add_job(self, fn, **kw):
            added.update(kw)
            added["fn"] = fn

        def modify_job(self, *a, **k):
            pass

        def get_job(self, _):
            return object()

        def start(self):
            pass

    orig = sch.BlockingScheduler
    sch.BlockingScheduler = FakeSched
    try:
        sch.run_scheduler(lambda: None,
                          {"interval_minutes": 5, "jitter_minutes": 0},
                          run_on_start=False)
    finally:
        sch.BlockingScheduler = orig
    assert added.get("misfire_grace_time", 0) >= 300, added
    assert added.get("coalesce") is True
