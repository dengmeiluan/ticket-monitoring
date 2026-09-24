# -*- coding: utf-8 -*-
"""推送审校回归： 真达标行撤 🟩 满格仪表条（multi 主路径
对齐 legacy 与 docstring）/ kpi_tier_txt 破线未达标词面带行情短注
（图脱离消息上下文可判档）/ ops 回退截尾去 U+2026。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1556_push.py
"""
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, kpi_tier_txt  # noqa: E402
from core.models import Route, FlightPrice  # noqa: E402


def _fp(price, name, dpt, art, plat="qunar", dep="2026-09-25"):
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep, "arrDate": dep,
            "transCity": "", "crossDayDesc": "",
            "totalDuration": "6时", "_platform": plat}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _mk_alerter():
    log = logging.getLogger("t1556push")
    return Alerter(log, notifier=None, storage=None, digest=True,
                   at_mobile="", storm_repeat=1, user="演练")


# ----：kpi_tier_txt 行情消歧（单源单测） ----

def test_kpi_tier_txt_market_disambiguation():
    """破线未达标：词面带「·行情」短注（「低￥N」词面属真达标档，
    图内 summary 脱离上下文曾读成可出手）；真达标无注；恰达线/超线/
    擦边口径不变。"""
    assert kpi_tier_txt("中转", 1500, 1700, False).endswith("低￥200·行情")
    assert kpi_tier_txt("直飞", 1500, 1700, True).endswith("低￥200")
    assert "·行情" not in kpi_tier_txt("直飞", 1500, 1700, True)
    assert "行情破线" in kpi_tier_txt("直飞", 1700, 1700, False)
    assert "真达标" in kpi_tier_txt("直飞", 1700, 1700, True)
    assert "差￥300" in kpi_tier_txt("直飞", 2000, 1700, False)
    assert "擦边" in kpi_tier_txt("直飞", 1780, 1700, False)


# ----：multi 主路径真达标行无仪表条（真实链路） ----

def test_multi_digest_qual_row_no_gauge():
    """真达标行已有 🎯+低￥N+hits 🔥 三重同义（撤达标行），
    multi 主路径 `_g` 无条件吃 _gauge 曾让 🎯 行下挂 🟩 满格——与图例
    「🟩=破线」同色两义、主次拉平。纯真达标场景（无破线蹲守行）desp
    不得出现 🟩 满格条。"""
    a = _mk_alerter()
    d = "2026-09-25"
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    r2 = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
               to_name="上海", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    p1 = _ps([_fp(1468, "南航CZ6981", "18:30", "23:40")], "SHA", "URC", d)
    p2 = _ps([_fp(1520, "东航MU8369", "08:00", "13:00")], "URC", "SHA", d)
    pv = a._digest_payload([(r1, a._build_sections(r1, p1)),
                            (r2, a._build_sections(r2, p2))],
                           fresh=True, with_tables=False, with_charts=False)
    desp = pv["desp"]
    assert "🎯" in desp
    assert "🟩🟩🟩🟩🟩" not in desp, desp


def test_multi_digest_market_row_keeps_gauge():
    """行情破线（未达标）行仪表条保留（设计原意：只给破线行
    留 🟩 满格强化）—— 修复不得矫枉过正撤掉蹲守档强化。"""
    a = _mk_alerter()
    d = "2026-09-25"
    # 中转行情班：到达约束内（00:55 ≤ 02:00）但直挂约束不满足
    # （transfer_baggage=direct 行未标注）→ 进 top_transfers 成
    # best_transfer_mkt（KPI 展示班），qual_hit=False、price≤th →
    # 行情破线档成立
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=[d], alert_direct=1900,
               alert_transfer=1900, transfer_baggage="direct")
    r2 = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
               to_name="上海", dates=[d], alert_direct=1900,
               alert_transfer=1900, transfer_baggage="direct")
    p1 = _ps([{"price": 1800, "name": "春秋9C7006", "code": "9C7006/9C7310",
               "depTime": "15:15", "arrTime": "00:55", "depDate": d,
               "arrDate": "2026-09-26", "transCity": "石家庄",
               "crossDayDesc": "+1天", "totalDuration": "9时40分",
               "layover": 180, "layoverSrc": "transInfo",
               "_platform": "fliggy"}], "SHA", "URC", d)
    p2 = _ps([{"price": 1500, "name": "春秋9C8846", "code": "9C8846",
               "depTime": "09:00", "arrTime": "23:00", "depDate": d,
               "arrDate": d, "transCity": "西安",
               "crossDayDesc": "", "totalDuration": "5时",
               "layover": 120, "layoverSrc": "transInfo",
               "_platform": "tongcheng"}], "URC", "SHA", d)
    pv = a._digest_payload([(r1, a._build_sections(r1, p1)),
                            (r2, a._build_sections(r2, p2))],
                           fresh=True, with_tables=False, with_charts=False)
    desp = pv["desp"]
    assert "🟩🟩🟩🟩🟩" in desp, desp


# ----：ops 回退截尾不用 U+2026 ----

def test_ops_truncate_no_ellipsis_char():
    """「…」钉钉渲染成。。（钉钉渲染定律）——总表上传失败回退的 ops 注截尾
    尾注改「（截）」，全链 desp 不再出现 U+2026 字符。"""
    a = _mk_alerter()
    d = "2026-09-25"
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    p1 = _ps([_fp(1468, "南航CZ6981", "18:30", "23:40")], "SHA", "URC", d)
    secs = a._build_sections(r1, p1)
    # 模拟超宽 ops 注走截尾 fallback（_fit_line 空尾档）
    from core.alerter import _fit_line
    _n = "孤低价拦截×3：飞猪￥9900、去哪儿￥9500、同程￥9300、途牛￥9100"
    out = _fit_line(_n, fallbacks=[
        _n[:_n.find("：") + 1] + "（截）" if "：" in _n else _n[:18] + "（截）"])
    assert "…" not in out
    assert "（截）" in out
    # 全链组装路径也不产 …（图 URL 假链触发 ops 回退）
    a.round_charts = {}
    pv = a._digest_payload([(r1, secs)], fresh=True, with_tables=False,
                           with_charts=False)
    assert "…" not in pv["desp"], pv["desp"]
