# -*- coding: utf-8 -*-
"""v1.5.86 爬虫价格带单源收编钉。

models.PRICE_MIN/MAX 注释宣称「取数链五处统一 100–50000、勿单侧
改值」（曲线/列表/日报/各渠道最低/查现价已单源），但五爬虫内仍
散布 13 处 `300 <= x <= 50000` 硬编码——三套并存时代的漏改：100–299
的真实促销价在摄取层被静默丢弃，且与「单源」注释不符。本钉固防
全爬虫带单源（数据观测移交立案）。100–299 放开后的误值风险由既有
守卫链承接（孤低价 ⚠ 永不判达标 + 行价<明细最低×0.5 杂污染弃用）。

运行:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v186_fields.py -q
"""
import glob
import os
import re


class TestCrawlerPriceBandSingleSource:
    def test_no_hardcoded_300_floor(self):
        # 全爬虫无 300 下界硬编码（历史三套并存漏改，统一 PRICE_MIN）
        for path in glob.glob(os.path.join("crawlers", "*.py")):
            src = open(path, encoding="utf-8").read()
            hits = re.findall(r"300\s*<=\s*\w+\s*<=\s*50000", src)
            assert not hits, f"{path} 残留 300 下界硬编码: {hits}"

    def test_main_no_hardcoded_300_floor(self):
        # 渠道指纹中位比观测路径同样单源（main.py 残留例：观测对
        # 100-299 合法促销价失明，与 models「单源」宣示不符）
        src = open("main.py", encoding="utf-8").read()
        hits = re.findall(r"300\s*<=\s*\w+\s*<=\s*50000", src)
        assert not hits, f"main.py 残留 300 下界硬编码: {hits}"
        assert "PRICE_MIN" in src, "main.py 未引用 PRICE_MIN"

    def test_crawlers_reference_price_constants(self):
        # 五爬虫引用单源常量（带收编后 import 必在场）
        for name in ("ctrip", "qunar", "tuniu", "tongcheng", "fliggy"):
            src = open(os.path.join("crawlers", f"{name}.py"),
                       encoding="utf-8").read()
            assert "PRICE_MIN" in src, f"crawlers/{name}.py 未引用 PRICE_MIN"

    def test_price_min_floor_is_100(self):
        # 单源下界语义锚：100（<100 真实国内航价几乎不存在）
        from core.models import PRICE_MAX, PRICE_MIN
        assert PRICE_MIN == 100
        assert PRICE_MAX == 50000
