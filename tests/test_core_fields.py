# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r289_fields.py
- tests/test_r301_fields.py
- tests/test_v186_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import glob
import os
import re
import sys

from core.flightnorm import cabin_text, discount_txt, normalize as _norm


# ---- merged from tests/test_r289_fields.py ----

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


# ---- merged from tests/test_r301_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- F1：经停城市 JGS（井冈山）裸码转中文 ----
def test_trans_city_jgs_normalized():
    f = {"name": "上航FM9269", "price": 1750, "depTime": "09:10",
         "arrTime": "13:30", "depDate": "2027-01-30", "arrDate": "2027-01-30",
         "transCity": "JGS", "totalDuration": "4时20分"}
    _norm(f, "2027-01-30")
    assert f["transCity"] == "井冈山", f


def test_trans_city_chinese_kept():
    g = {"name": "上航FM9269", "price": 1750, "depTime": "09:10",
         "arrTime": "13:30", "depDate": "2027-01-30", "arrDate": "2027-01-30",
         "transCity": "井冈山", "totalDuration": "4时20分"}
    _norm(g, "2027-01-30")
    assert g["transCity"] == "井冈山", g


# ---- F2：经停停留 ≥ 全程必为渠道脏值，stopTimeT 不落 ----
def _base(**kw):
    f = {"name": "东航MU136", "price": 1750, "depTime": "09:10",
         "arrTime": "13:30", "depDate": "2027-01-30", "arrDate": "2027-01-30",
         "totalDuration": "4时20分", "stopCitys": "井冈山",
         "stopTime": "24小时45分"}
    f.update(kw)
    return f


def test_stop_time_ge_total_invalid():
    f = _base()
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f
    # 行本体信息不受牵连：经停城市与健康行一样保留
    assert f.get("stopCity") == "井冈山", f
    # 幂等：第二遍 normalize 终态一致（不复活）
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


def test_stop_time_healthy_kept():
    f = _base(stopTime="45分", code="FM9269", name="上航FM9269")
    _norm(f, "2027-01-30")
    assert f.get("stopTimeT") == "0:45", f


def test_stop_time_equal_total_invalid():
    # 恰等于全程同样是脏值（停留吃满全程=两段飞行 0 分钟，不存在）
    f = _base(stopTime="4时20分")
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


def test_stop_time_no_dur_no_guard():
    # 缺起降时刻走早退分支（durM 永不派生）：守卫不触发，宁缺勿错
    f = {"name": "东航MU136", "price": 1750, "stopCitys": "井冈山",
         "stopTime": "24小时45分"}
    _norm(f, "2027-01-30")
    assert f.get("stopTimeT") == "24:45", f


def test_stop_time_dur_recomputed_guard_holds():
    # totalDuration 缺席但起降在场：时长被起降差重算后守卫仍判定
    f = _base()
    f.pop("totalDuration")
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


def test_stop_time_threedigit_minute_guard_holds():
    # Soldier m2 收口钉：派生侧 :02d 对「N小时M分」M≥100 类词面产
    # 3 位分钟（"6:0"形态族），守卫分钟域 \d+ 宽收不漏（窄于 \d{2}
    # 时此形态静默失明）。样本 4小时120分=360 分钟 ≥ 全程 260 分钟
    f = _base(stopTime="4小时120分")
    _norm(f, "2027-01-30")
    assert "stopTimeT" not in f, f


# ---- merged from tests/test_v186_fields.py ----

class TestCrawlerPriceBandSingleSource:
    def test_no_hardcoded_300_floor(self):
        # 全爬虫无 300 下界硬编码（历史三套并存漏改，统一 PRICE_MIN）
        for path in glob.glob(os.path.join("crawlers", "*.py")):
            src = open(path, encoding="utf-8").read()
            hits = re.findall(r"300\s*<=\s*\w+\s*<=\s*50000", src)
            assert not hits, f"{path} 残留 300 下界硬编码: {hits}"

    def test_main_no_hardcoded_300_floor(self):
        # 渠道指纹中位比观测路径同样单源（main.py 残留例：观测对
        # 100-299 合法促销价失明，与 models「单源」宣示不符）。
        # r325 收口升级：带过滤走 price_band_ok scope-aware 单源
        # （国际航线宽带档），main.py 不再直引常量做裸比较
        src = open("main.py", encoding="utf-8").read()
        hits = re.findall(r"300\s*<=\s*\w+\s*<=\s*50000", src)
        assert not hits, f"main.py 残留 300 下界硬编码: {hits}"
        assert "price_band_ok" in src, "main.py 未走 price_band_ok 单源"

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
