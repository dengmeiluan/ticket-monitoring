# -*- coding: utf-8 -*-
"""cabin 消费端守卫：途牛串舱存量行的词面清污。

r222 观测 C 实锤（_scratch/r222_obs_report.md）：修复前近 48h 途牛
1,403 条高档舱标签明细中 1,196 条（85.2%）为串舱（舱名取首个政策、
价取最低政策），判据 A=行内硬证 cabin∈高档舱 且 price<bizPrice
（1,403/1,403 内证一致）；207 条 price==bizPrice 为真公务选中须保留。
读层已随 _adt_fare 选中政策配对根治（新轮不再产出），本守卫管
库内存量行在三大消费端（webui 舱位描述/report 次行/alerter 比价
离群判定）的词面清污——两层各自独立成立（LESSONS 廿四§11）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15122_cabin_guard.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.flightnorm import cabin_clean, cabin_text  # noqa: E402
from core.alerter import Alerter  # noqa: E402


def _mis(price=2615, biz=7800, cabin="公务舱"):
    return {"cabin": cabin, "price": price, "bizPrice": biz}


def test_cabin_clean_drops_mislabeled_high_cabin():
    # 串舱硬证：高档标签 + 行价低于公务参考价 → 标签置空（宁缺勿错）
    assert cabin_clean(_mis()) == ""


def test_cabin_clean_keeps_true_business_selection():
    # 真公务选中（r222 修复后唯一合法形态）：price==bizPrice 原样保留
    assert cabin_clean(_mis(price=7800)) == "公务舱"
    assert cabin_clean(_mis(price=7801)) == "公务舱"


def test_cabin_clean_keeps_without_bizprice():
    # 无 bizPrice 行不可内证：维持原值（守卫不越权）
    assert cabin_clean({"cabin": "公务舱", "price": 2615}) == "公务舱"
    assert cabin_clean({"cabin": "头等舱"}) == "头等舱"


def test_cabin_clean_passes_economy_and_odd_words():
    # 只查高档舱词；经济舱/空值/怪码不受影响
    assert cabin_clean(_mis(cabin="经济舱")) == "经济舱"
    assert cabin_clean(_mis(cabin="超级经济舱")) == "超级经济舱"
    assert cabin_clean({"cabin": "", "price": 1, "bizPrice": 2}) == ""


def test_cabin_text_uses_guard():
    # webui 舱位描述集成：串舱行不出「公务舱」词面
    f = _mis()
    f["plane"] = "空客320"
    assert "公务舱" not in cabin_text(f)
    assert "空客320" in cabin_text(f)
    f2 = _mis(price=7800)
    f2["plane"] = "空客320"
    assert "公务舱" in cabin_text(f2)


def test_outlier_not_triggered_by_mislabeled_cabin():
    # 比价组离群判定：串舱行不再制造「跨舱位」假离群
    fs = [{"cabin": "经济舱", "price": 2600},
          {"cabin": "经济舱", "price": 2610},
          {"cabin": "公务舱", "price": 2615, "bizPrice": 7800}]
    assert Alerter._outlier(fs) is False
    # 真跨舱位（价差 2×+）仍判离群：守卫不豁免真实信号
    fs2 = [{"cabin": "经济舱", "price": 2600},
           {"cabin": "公务舱", "price": 7800}]
    assert Alerter._outlier(fs2) is True


def test_cabin_clean_covers_letter_codes():
    # r222 推送审校 P0：qunar 单字母高档码（_cabin_cn 映射在查纯域
    # 之后曾整体绕过守卫）——￥2416 经济舱行实推成「头等舱」，48h
    # 冻结库 1,456 条字母码 85.7% 价位矛盾。守卫查映射后的语义类。
    assert cabin_clean({"cabin": "F", "price": 2416, "bizPrice": 5200}) == ""
    assert cabin_clean({"cabin": "A", "price": 2416, "bizPrice": 5200}) == ""
    assert cabin_clean({"cabin": "C", "price": 2600, "bizPrice": 7800}) == ""
    assert cabin_clean({"cabin": "J", "price": 2600, "bizPrice": 7800}) == ""
    # 真高档选中（字母码行 price==bizPrice）：原码保留（显示层再映射）
    assert cabin_clean({"cabin": "J", "price": 5200, "bizPrice": 5200}) == "J"
    assert cabin_clean({"cabin": "F", "price": 9900, "bizPrice": 5200}) == "F"
    # 经济舱族字母码不查
    assert cabin_clean({"cabin": "Y", "price": 100, "bizPrice": 9900}) == "Y"
    assert cabin_clean({"cabin": "M", "price": 100, "bizPrice": 9900}) == "M"
    # 无 bizPrice 字母码行不可内证：维持原值
    assert cabin_clean({"cabin": "F", "price": 2416}) == "F"


def test_cabin_class_single_source():
    # 大类映射上收 flightnorm 单源：alerter._cabin_cn 变委托同函数
    from core.alerter import _cabin_cn
    from core.flightnorm import cabin_class
    assert _cabin_cn is cabin_class
    assert cabin_class("F") == "头等舱"
    assert cabin_class("Y") == "经济舱"
    assert cabin_class("经济舱") == "经济舱"
    assert cabin_class("超级经济舱") == "超级经济舱"
    assert cabin_class("42") == ""          # 怪码宁缺勿错
    assert cabin_class("") == ""
