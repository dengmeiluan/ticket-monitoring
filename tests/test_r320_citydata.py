# -*- coding: utf-8 -*-
"""r320 全国城市数据表钉（用户情报：连云港配置存不进 → 产品升级为
全国民航城市全量静态表）：

- 数据源：ctrip 特价榜 DOMESTIC_ALL 响应的结构化城市对（构建期一次
  性拉取 8 出发地并集 238 对，清洗后 237 城），码零手抄；
- 兼容铁律：旧 50 城手抄表的 (名,码) 语义零漂移（存量配置的码不
  变）；香格里拉/汕头别名补回（同机场异名）；
- 形态门：码全 [A-Z]{3}、首字母分组全覆盖且 ∈ A-Z、热门组 ⊆ 全表、
  CODE_NAME 码→名唯一；
- 单源：wizard.CITY 改引 citydata（配置页联想/归一下发同源）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r320_citydata.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.citydata import (CITY, CITY_HOT, CITY_NPY, CITY_PY,  # noqa: E402
                           CODE_NAME)

# 旧 50 城手抄表语义快照（wizard.py 迁移前定格，存量配置兼容铁律）
_LEGACY = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "重庆": "CKG", "杭州": "HGH", "西安": "SIA",
    "南京": "NKG", "武汉": "WUH", "长沙": "CSX", "厦门": "XMN",
    "三亚": "SYX", "海口": "HAK", "昆明": "KMG", "丽江": "LJG",
    "大理": "DLU", "西双版纳": "JHG", "香格里拉": "DIG", "腾冲": "TCZ",
    "乌鲁木齐": "URC", "青岛": "TAO", "天津": "TSN", "郑州": "CGO",
    "济南": "TNA", "福州": "FOC", "温州": "WNZ", "宁波": "NGB",
    "合肥": "HFE", "贵阳": "KWE", "南宁": "NNG", "桂林": "KWL",
    "兰州": "LHW", "西宁": "XNN", "银川": "INC", "呼和浩特": "HET",
    "太原": "TYN", "石家庄": "SJW", "哈尔滨": "HRB", "长春": "CGQ",
    "沈阳": "SHE", "大连": "DLC", "珠海": "ZUH", "汕头": "SWA",
    "泉州": "JJN", "无锡": "WUX", "烟台": "YNT", "威海": "WEH",
    "敦煌": "DNH", "张家界": "DYG",
}


def test_city_table_scale_and_users_case():
    """全国民航网覆盖规模 + 用户实报城（连云港）在场。"""
    assert len(CITY) >= 200, len(CITY)
    assert CITY.get("连云港") == "LYG"
    assert CODE_NAME.get("LYG") == "连云港"


def test_legacy_names_codes_zero_drift():
    """旧 50 城 (名,码) 语义零漂移（存量配置兼容铁律）。"""
    bad = {n: (c, CITY.get(n)) for n, c in _LEGACY.items()
           if CITY.get(n) != c}
    assert not bad, f"旧城漂移: {bad}"


def test_code_shape_and_uniqueness():
    """码形态全验 + 码→名转写唯一 + 名→码无同名异码。"""
    for n, c in CITY.items():
        assert re.fullmatch(r"[A-Z]{3}", c), (n, c)
    for c, n in CODE_NAME.items():
        assert re.fullmatch(r"[A-Z]{3}", c) and 1 <= len(n) <= 10, (c, n)
    assert len(CODE_NAME) >= 200


def test_pinyin_groups_and_hot():
    """首字母分组全覆盖（面板字母导航）；热门组 ⊆ 全表。"""
    assert set(CITY_PY) == set(CITY), "首字母表与城市表不同域"
    for n, py in CITY_PY.items():
        assert re.fullmatch(r"[A-Z]", py), (n, py)
    assert 8 <= len(CITY_HOT) <= 30
    assert set(CITY_HOT) <= set(CITY)


def test_name_py_full_coverage():
    """拼音全拼表（官方 namePy，面板搜索的拼音通道）：覆盖全表、
    小写字母串形态（渠道引号瑕疵已清洗）。"""
    assert set(CITY_NPY) == set(CITY), "全拼表与城市表不同域"
    for n, p in CITY_NPY.items():
        assert re.fullmatch(r"[a-z]+", p), (n, p)
    assert CITY_NPY.get("连云港") == "lianyungang"


def test_wizard_city_single_source():
    """wizard.CITY 单源化（配置页联想/归一与采集词表同源防漂移）。"""
    import wizard
    assert wizard.CITY is CITY or wizard.CITY == CITY, (
        "wizard.CITY 未接 citydata 单源（手抄表漂移风险）")


def test_crawler_cityname_superset():
    """三渠道 CITY_NAME 全国超集（码→中文名转写全通；用户实报城
    连云港在场）。旧键旅游名语义保留（DIG=香格里拉）。"""
    from crawlers.ctrip import CtripCrawler
    from crawlers.qunar import QunarCrawler
    from crawlers.tongcheng import TongchengCrawler
    for cls in (CtripCrawler, QunarCrawler, TongchengCrawler):
        t = cls.CITY_NAME
        assert len(t) >= 250, (cls.__name__, len(t))
        assert t.get("LYG") == "连云港", cls.__name__
        assert t.get("DIG") == "香格里拉", cls.__name__
