# -*- coding: utf-8 -*-
"""r322 数据层（qunar「可再减¥N」透明标记收编）：

qunar H5 listLabel.priceBottomLabels 的 reduceShowLabel「可再减¥N」
旧定性=营销 churn 不采（r307 备案：当时 205-241 次/份高频=每行都
有零区分度）。新代 dump 形态三要素翻转定性，按透明标记路径收编：

1. 频率形态变化：4 份新代 442 行仅 1 行在场（GS6549/KN2918 海→沪
   2027-02-13）——稀疏=有区分度的真实减价标记，非高频 churn；
2. 数值自洽：packageCutPrice=2204.0 ≡ lowPrice 2350 − 减额 146
   （browser/httpx 双通道同值），45/45 镜像行（packageCutPrice≡
   lowPrice）渠道本就不发此标签——标签在场即真减价形态；
3. 页面公开承诺：该词面是渠道列表页对真实用户的展示承诺
   （reduceShowLabel），非内部结算字段。

边界纪律：价格口径不动（packageCutPrice 数值不采入任何价格字段，
防达标判定价污染——可购性活体验证挂账 headless 被风控）；正则臂
精确形态「^可再减¥+数字+$」，「可再减¥N起」变体、「比直飞省¥N」
营销族、「可再减」裸词仍拒。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r322_fields.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("r322")
_QC = QunarCrawler({}, _LOG)


def _h5_f(texts):
    """H5 行最小载体：listLabel.priceBottomLabels 词面列表。"""
    return {"listLabel": {"priceBottomLabels": [{"text": t} for t in texts]}}


def test_h5_reduce_label_collected():
    """「可再减¥146」透明标记采入 labels（案 GS6549/KN2918 实锤形态）。"""
    out = QunarCrawler._h5_labels_of(_h5_f(["可再减¥146"]))
    assert "可再减¥146" in out, out


def test_h5_reduce_label_variants_still_excluded():
    """正则臂精确形态：裸词/起字变体/非 ¥ 计价形态仍拒。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["可再减", "可再减¥20起", "可再减20", "再减¥20"]))
    assert out == "", out


def test_h5_marketing_churn_family_still_excluded():
    """营销 churn 族不随本臂放宽：比直飞省/精选低价族维持排除。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["比直飞省¥30", "精选低价", "当日达低价", "中转-耗时最短"]))
    assert out == "", out


def test_h5_reduce_label_with_service_words_order_kept():
    """与服务承诺词共存：渠道原序、3 槽上限内正常编排。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["免费上网", "可再减¥146"]))
    assert out == "免费上网·可再减¥146", out
