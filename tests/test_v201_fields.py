# -*- coding: utf-8 -*-
"""数据层原生增量：ctrip classNoteList nt=3 裸词 LimitedAge 并入
agePolicy（零新键，扩既有出口）。

调研实证（转正候选专项）：
nt=3 'LimitedAge' 裸词 2/349 行（GS7529/MU8452 × 2 份 dump 独立复现），
同行受限价 tprice=2457 恰为行内最低有票价——年龄购买资格恰挂
「你看到的最低价买不了」语义；行内 nt=20 缺席、agePolicy 既有出口
零承载。家族推证：nt=20 侧 LimitedAgePolicy→「限年龄」映射已在案，
nt=3 裸词=同族载体迁移形态（价格前缀+细分 → 裸词）。防重钉：与
nt=20 同语义并存时不得拼出「限年龄·限年龄」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v201_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t201")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_limited_age_bare_word():
    """nt=3 裸词 LimitedAge（worker 实证形态，逗号串携 LockPrice 同伴）：
    agePolicy=「限年龄」——最低价票的年龄购买资格正是 agePolicy 语义
    （行内 nt=20 缺席、零既有承载）。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3,
                             "notecnt": "LockPrice,LimitedAge"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=2457, ci=ci)]))
    assert r["agePolicy"] == "限年龄"


def test_ctrip_limited_age_no_duplicate_with_nt20():
    """与 nt=20 同语义 LimitedAgePolicy 并存（载体双形态同现）：防重
    拼接——agePolicy 仍「限年龄」，不出「限年龄·限年龄」。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3, "notecnt": "LimitedAge"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=2457, ci=ci,
                       fnotelst=[{"notetype": 20,
                                  "notecnt": "2457_LimitedAgePolicy"}])]))
    assert r["agePolicy"] == "限年龄"
