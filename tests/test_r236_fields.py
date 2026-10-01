# -*- coding: utf-8 -*-
"""r236 数据层（渠道调研立案）：

ctrip aset 中转权益新词面「赠餐食、休息厅」（tcode=G_ALLDRZZZFWB）
→ labels 白名单增补一词：r236 冻结 dump（10-05/10-06 两代际）3/160
行首现（CZ5640 系两段中转行），载体行 nt=103/fnotelst nt=10/行内
其余 aset 词（「已优惠￥90」营销/「准点率83%」=InTimeTag 已采 prate）
零既有出口承载——不收则该行「中转赠餐食+休息厅」权益永久缺失。
同族白名单先例齐备（免费市区班车/中转免费休息/专属休息/赠快速安检/
地域品牌词三件），纯词无价格不随价 churn；随 labels 单源通道零新键
（PNG 总表图列/明细 title/CSV 三消费端现成）。

样本形态取自生产冻结 dump。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r236_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("r236")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies, aset=None):
    it = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        it["aset"] = aset
    return it


def _ctrip_seg(dd, ad, flgno="CZ5640"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T3", "aport": "SHA"}}


def _ci_plain(letter="Y"):
    return {"cgrd": 0,
            "classNoteList": [{"notetype": 2, "notecnt": letter}]}


def _ctrip_policy_cis(price, cis, qty=5):
    return {"tprice": price, "quantity": qty, "drate": 5.2,
            "classinfor": cis}


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


_D = ("2026-10-06 08:30:00", "2026-10-06 13:50:00")


def test_aset_meal_lounge_label():
    """aset「赠餐食、休息厅」（tcode=G_ALLDRZZZFWB）→ labels：中转
    服务承诺词随白名单收编（tagcnt 精确等值匹配，勿按 tcode 匹配
    以免疫换代——「老客专享」先例同律）。"""
    aset = [{"tagarea": [{"tcode": "G_ALLDRZZZFWB",
                          "tagcnt": "赠餐食、休息厅"}]}]
    r = _one(_ctrip_item([_ctrip_seg(*_D)],
                         [_ctrip_policy_cis(1200, [_ci_plain()])],
                         aset=aset))
    assert "赠餐食、休息厅" in r["labels"]


def test_aset_meal_lounge_with_existing_words_no_dup():
    """新词与既有白名单词同行并存：各自一次、零重复拼接（aset 同词
    去重纪律的并存回归钉）。"""
    aset = [{"tagarea": [
        {"tcode": "G_ALLDRZZZFWB", "tagcnt": "赠餐食、休息厅"},
        {"tcode": "G_KMZZAJ", "tagcnt": "赠快速安检"}]}]
    r = _one(_ctrip_item([_ctrip_seg(*_D)],
                         [_ctrip_policy_cis(1200, [_ci_plain()])],
                         aset=aset))
    ls = r["labels"].split("·")
    assert ls.count("赠餐食、休息厅") == 1
    assert ls.count("赠快速安检") == 1
