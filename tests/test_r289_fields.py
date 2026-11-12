"""r289 数据层：折扣词面「全价+舱别」复合形态家族档。

背景（r289 渠道调研 A 报告 _scratch/r289_ch_a.md）：qunar PC 路径
discountStr 落库「全价经济舱/全价公务舱/全价商务舱」族 5,552 行
（DB 三面互证：值域分布 × cabinCode 舱别 100% 同源 × 消费端格式门
零显形——跨路径折扣位不对称实锤，H5 兄弟路径同场景出「10折」）。

v160 在案判例是「舱位描述文本冒充折扣」整串丢弃——本档不推翻其
精神（纯舱名/未实证复合形态照弃），只对「全价」token 做封闭集合
精确提取（tc「明珠经济舱全价」同串双抓同族先例，舱别语义仍由
cabin/cabinCode 承载）。落地层=discount_txt 单源消费端（DB 原值
不动，存量 5,552 行即时生效，PC 断供期无需 dump 复证）。
"""
from core.flightnorm import cabin_text, discount_txt


def test_discount_txt_fullfare_cabin_family():
    """全价三舱别复合形态精确提取「全价」；封闭集合外维持丢弃。"""
    assert discount_txt("全价经济舱") == "全价"
    assert discount_txt("全价公务舱") == "全价"
    assert discount_txt("全价商务舱") == "全价"
    # 未实证复合形态（无生产样本，不惯性扩域）/脏形态/纯舱名照弃
    assert discount_txt("全价头等舱") == ""
    assert discount_txt("全价折") == ""
    assert discount_txt("明珠经济舱") == ""
    assert discount_txt("商务舱") == ""
    # 既有两形态与空值零回归
    assert discount_txt("4.6折") == "4.6折"
    assert discount_txt("全价") == "全价"
    assert discount_txt("") == ""
    assert discount_txt(None) == ""


def test_cabin_text_fullfare_family_segment():
    """舱位描述串随家族档升级：全价段回收，「· 全价」入串；
    纯舱名形态维持不落（v160 断言翻转面=判例细化非回归）。"""
    assert cabin_text({"cabin": "经济舱", "discount": "全价经济舱"}) == \
        "经济舱 · 全价"
    # 纯舱名冒充形态维持丢弃（v160 语义担保保留）
    assert cabin_text({"cabin": "经济舱", "discount": "明珠经济舱"}) == \
        "经济舱"
    assert cabin_text({"cabin": "经济舱", "discount": "商务舱"}) == "经济舱"
