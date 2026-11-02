# -*- coding: utf-8 -*-
"""ctrip planeAge 恒档粗化守卫（r318 观测立案，r315 备案触发线到达）：

观测实录（_scratch/r318_pa_census.py 双口径普查）：ctrip planeAge 逐日
供给 10-10 起连续 7 天 100% 恒 '5'（自然基线 10-02~10-07 占比 0-2%），
r315 备案触发线「值域塌缩单值或占比 >80% 持续」双线到达。按备案预设
处置读层置空：格式化后精确 '5'（整年无月）不落键——恒档下发形态即此
形态；「机龄5年11个月」→'5.9' 月成分形态照落，防误杀真 5 年 X 月机
龄。撤守卫条件=逐日 '5' 占比回落（渠道恢复多值下发），届时移除常量
即恢复复采。

样本形态取自生产 dump 结构（test_r310_fields 同款夹具）。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r318_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_r318")
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


def test_planeage_bare_five_quarantined():
    """机龄整 5 年（恒档下发形态）→ planeAge 键不落（读层置空）。"""
    r = _parse([{"content": "机龄5年"}])
    assert "planeAge" not in r, r.get("planeAge")


def test_planeage_five_with_months_still_lands():
    """「机龄5年11个月」→'5.9' 照落：月成分形态非恒档下发值。"""
    r = _parse([{"content": "机龄5年11个月"}])
    assert r["planeAge"] == "5.9", r.get("planeAge")


def test_planeage_other_years_still_land():
    """非 5 整年照落（守卫零外溢）：8 年→'8'、0 年→'0' 显式真值。"""
    r = _parse([{"content": "机龄8年"}])
    assert r["planeAge"] == "8", r.get("planeAge")
    r0 = _parse([{"content": "机龄0年"}])
    assert r0["planeAge"] == "0", r0.get("planeAge")


# ---- 解析哨兵×恒档守卫的口径适配（守卫置空非断链） ----

class _CapLog:
    def __init__(self):
        self.seen = []

    def info(self, *a, **k):
        pass

    def warning(self, msg, *a, **k):
        self.seen.append(msg % a if a else str(msg))


def _sent_reset(_m):
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()


def test_field_sentinel_ctrip_page_exempt():
    """供给基线在场的归零轮：守卫在岗时 ctrip planeAge 置空不再误报
    「键名失效/渠道改版」——置空是 _PLANEAGE_COARSE 守卫的预期行为，
    断链监测责任移交守卫观察哨（撤守卫条件=逐日 '5' 占比回落），
    哨兵退出 (ctrip, page) 观测。"""
    import json as _json
    from types import SimpleNamespace as _NS
    import main as _m
    lg = _CapLog()
    _sent_reset(_m)
    supply = [{"price": 1000 + i, "plane": "空客321(中)",
               "planeSize": "中型机", "planeAge": "6.3"}
              for i in range(30)]
    _m._field_sentinel([_NS(platform="ctrip",
                            extra=_json.dumps(supply))], lg)
    assert lg.seen == [], lg.seen          # 供给轮零告警
    guarded = [{"price": 1000 + i, "plane": "空客321(中)",
                "planeSize": "中型机"} for i in range(30)]
    _m._field_sentinel([_NS(platform="ctrip",
                            extra=_json.dumps(guarded))], lg)
    assert not any("planeAge" in s for s in lg.seen), lg.seen


def test_field_sentinel_other_page_still_observed():
    """豁免只及 (ctrip, page)：源码钉锁「ctrip 退出、tongcheng/tuniu
    保留」——防豁免扩面弱化断链防线，也防 page 观测面被整表清空。"""
    import os as _os
    from pathlib import Path as _Path
    src = _Path(_os.path.join(_os.path.dirname(
        _os.path.dirname(_os.path.abspath(__file__)),
    ), "main.py")).read_text(encoding="utf-8")
    assert '("ctrip", "page"),' not in src, "ctrip page 豁免未落地"
    assert '("tongcheng", "page"),' in src and '("tuniu", "page")' in src
