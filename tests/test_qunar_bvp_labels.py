# -*- coding: utf-8 -*-
"""qunar H5 labels 第二载体 bizVendorPrice.listLabel：

渠道正把服务承诺标签从顶层 listLabel 迁往 bvp（bizVendorPrice）
容器——「出票后2小时内错购退票」在新代 dump 的载体行（当轮最低
价档）唯一载体是 bvp.listLabel.priceBottomLabels，顶层同槽只有
营销词。单源读顶层即丢该行服务承诺：载体行恰是最需要退改信息的
低价档。并读两容器（顶层优先、bvp 兜底、同词去重），白名单门
不变；bvp 与顶层同 schema（家族律），同词「体验价」双载体并现
为纯镜像成员，去重后零增量。

样本形态取自生产冻结 dump（browser/httpx 双通道跨轮复现）。
运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_qunar_bvp_labels.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("bvp_labels")
_QC = QunarCrawler({}, _LOG)


def _f(top_texts, bvp_texts):
    """H5 行最小载体：顶层 + bvp 双 listLabel 容器。"""
    return {
        "listLabel": {"priceBottomLabels": [{"text": t} for t in top_texts]},
        "bizVendorPrice": {
            "listLabel": {"priceBottomLabels": [{"text": t}
                                                for t in bvp_texts]},
        },
    }


def test_bvp_carried_service_word_collected():
    """bvp 独载的白名单服务词随并读采入 labels：顶层只有营销词
    （不采）时，错购退票时效承诺不得因载体迁移而丢失。"""
    f = _f(["直飞低价"], ["出票后2小时内错购退票"])
    assert "出票后2小时内错购退票" in QunarCrawler._h5_labels_of(f)


def test_bvp_duplicate_word_deduped():
    """同词双载体并现（体验价镜像成员）：去重后只出一个。"""
    f = _f(["体验价"], ["体验价"])
    assert QunarCrawler._h5_labels_of(f) == "体验价"


def test_bvp_absent_no_regression():
    """无 bizVendorPrice 键（顶层载体代）：现行行为不变。"""
    f = {"listLabel": {"priceBottomLabels":
                       [{"text": "出票后2小时内错购退票"}]}}
    assert QunarCrawler._h5_labels_of(f) == "出票后2小时内错购退票"


def test_bvp_malformed_no_crash():
    """bvp 非 dict（脏形态）不炸、顶层照采。"""
    f = {"bizVendorPrice": "garbage",
         "listLabel": {"priceBottomLabels": [{"text": "体验价"}]}}
    assert QunarCrawler._h5_labels_of(f) == "体验价"


def test_bvp_age_gate_still_tops():
    """年龄资格词置顶语义跨容器保持：bvp 载体的年龄词仍居首。"""
    f = _f([], ["限55岁(含)以上的旅客购买", "出票后2小时内错购退票"])
    out = QunarCrawler._h5_labels_of(f)
    assert out.startswith("限55岁")


def test_bvp_whitelist_gate_unchanged():
    """并读不放松白名单门：bvp 载体的营销 churn 词照旧静默不采。"""
    f = _f([], ["比直飞省¥30", "中转低价推荐"])
    assert QunarCrawler._h5_labels_of(f) == ""
