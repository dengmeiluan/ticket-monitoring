# -*- coding: utf-8 -*-
"""r237 数据层（渠道调研立案）：

qunar H5 listLabel.priceBottomLabels 白名单增补「免费上网」：
r237 冻结 dump 1/478 行首现（服务承诺型权益词），同词面在 PC
priceLabel 通道原生在采（全史 413 条）——H5 兜底路径漏采即该
权益在 H5 主路径期永久缺失（r237 观测窗 9 轮 qunar 全走 H5），
跨渠道词面不对称。随 labels 单源通道零新键（PNG 总表图列/
明细 title/CSV 三消费端现成）。

样本形态取自生产冻结 dump。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r237_fields.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("r237")
_QC = QunarCrawler({}, _LOG)


def _h5_f(texts):
    """H5 行最小载体：listLabel.priceBottomLabels 词面列表。"""
    return {"listLabel": {"priceBottomLabels": [{"text": t} for t in texts]}}


def test_h5_whitelist_free_wifi():
    """「免费上网」服务承诺型权益随 H5 白名单采入 labels。"""
    out = QunarCrawler._h5_labels_of(_h5_f(["免费上网"]))
    assert "免费上网" in out


def test_h5_whitelist_marketing_churn_still_excluded():
    """白名单增词不放松营销 churn 面：比价/降价类词与资格价词的
    变体/带价形态静默不采（全词精确匹配，子串放宽会放进 churn 词）。
    注意：变体钉是收编前置闸而非永拒钉——渠道未来真出「老会员专享」
    等新资格价词时，携 dump 证据链（家族律+跨轮复现）同轮收编并改钉。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["比直飞省¥30", "可再减¥20", "精选低价",
               "老会员专享", "黑钻会员专享", "新会员专享价",
               "体验价·限时"]))
    assert out == ""


def test_h5_whitelist_member_and_trial_price():
    """「新会员专享」「体验价」资格价词随 H5 白名单采入 labels：
    同槽「春秋绿翼会员专享丨超惠飞」家族先例在采；资格价互证形态
    （同班双价行/五价背离）在全部存量 dump 零在场=该载荷结构性
    不携带，按家族律+跨轮独立复现双要件收编（ctrip「老客专享」
    同族）；载体行恒为行内最低价，不采则读者把活动价当全民价。"""
    assert "新会员专享" in QunarCrawler._h5_labels_of(_h5_f(["新会员专享"]))
    assert "体验价" in QunarCrawler._h5_labels_of(_h5_f(["体验价"]))


def test_h5_whitelist_member_price_priority_over_service_word():
    """资格价词与既有白名单词同行共存：按渠道原序入 2 槽，无挤出异常。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["免费上网", "体验价"]))
    assert out == "免费上网·体验价"


def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（data.flights 普通数组形态）。"""
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    import json as _json
    return _json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_pc_stoptime_empty_not_landed():
    """PC 行 stopTime 无值不落键（直飞行无经停概念）：H5 段
    `if stop_time:` 门同族——PC 复活首日 397 行空串平铺的卫生收口。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([_pc_flight()]), "2026-10-05")
    assert rows and "stopTime" not in rows[0]


def test_pc_stoptime_valued_still_landed():
    """经飞行 stopTime 有值照落（门不得误杀真值）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b1={"stopTime": "1小时5分"})]), "2026-10-05")
    assert rows and rows[0].get("stopTime") == "1小时5分"


def test_pc_avgdelay_minus1_is_true_value():
    """avgDelay -1 真值族备案钉：PC 复活后 lateTime 连续值域
    -37~+17 在场，-1=历史平均提前 1 分钟（嵌在 -3/-2 之间），
    非 0 式占位——防未来「卫生化」按负值占位误吞真值。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b1={"lateTime": "-1"})]), "2026-10-05")
    assert rows and rows[0].get("avgDelay") == -1
