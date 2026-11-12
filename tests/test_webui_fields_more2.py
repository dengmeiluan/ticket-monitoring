# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v182_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import copy
import json
import os
import pytest
import sys

from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_v182_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 样本基座（同 v1554 PC 预案样本形态；lateTime 按生产 dump
# ---- 真实结构放 binfo/binfo1 分段层——v181 自造顶层形态的教训） ----

_PC_BASE = {
    "code": "FM9223", "minPrice": "2472", "transCity": "",
    "extparams": {"childPrice": 0, "infantPrice": None},
    "binfo": {"airCode": "FM9223", "shortName": "上航",
              "depTime": "19:55", "arrTime": "01:25",
              "date": "2026-10-04", "arrDate": "2026-10-05",
              "flightTime": "5h30m",
              "depTerminal": "", "arrTerminal": "T2",
              "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥机场",
              "planeFullType": "空客330(大)"},
}

_PC_LAYOVER_BASE = {
    "code": "3U1986/CZ3543", "minPrice": "1980",
    "transCity": "兰州",
    "extparams": {"childPrice": 0, "infantPrice": None},
    "binfo1": {"airCode": "3U1986", "shortName": "川航",
               "depTime": "08:20", "arrTime": "11:10",
               "date": "2026-10-04", "arrDate": "2026-10-04",
               "depTerminal": "T3", "arrTerminal": "T2",
               "depAirport": "乌鲁木齐天山", "arrAirport": "中川机场"},
    "binfo2": {"airCode": "CZ3543", "shortName": "南航",
               "depTime": "13:05", "arrTime": "16:05",
               "date": "2026-10-04", "arrDate": "2026-10-04",
               "depTerminal": "T2", "arrTerminal": "T1",
               "depAirport": "中川机场", "arrAirport": "虹桥机场"},
}


def _pc_raw(binfo_latetime=None):
    fl = copy.deepcopy(_PC_BASE)
    if binfo_latetime is not None:
        fl["binfo"]["lateTime"] = binfo_latetime
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [fl]}})


def _pc_layover_raw(binfo1_latetime=None):
    fl = copy.deepcopy(_PC_LAYOVER_BASE)
    if binfo1_latetime is not None:
        fl["binfo1"]["lateTime"] = binfo1_latetime
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [fl]}})


# ---- B1 读层修复：分段层 lateTime → avgDelay ----

def test_qunar_pc_latetime_from_binfo_segment():
    """直飞行 lateTime 在 binfo 分段层（生产 dump 真实形态）→ avgDelay。"""
    fl = QunarCrawler._parse_pc_flights(_pc_raw(binfo_latetime="-16"),
                                        "2026-10-04")
    f = fl[0]
    assert f.get("avgDelay") == -16 and isinstance(f["avgDelay"], int)


def test_qunar_pc_layover_latetime_from_binfo1():
    """中转行 lateTime 在 binfo1（首段口径）→ avgDelay；不取 binfo2。"""
    raw = json.loads(_pc_layover_raw(binfo1_latetime="-24"))
    raw["data"]["flights"][0]["binfo2"]["lateTime"] = "-99"
    fl = QunarCrawler._parse_pc_flights(json.dumps(raw), "2026-10-04")
    f = fl[0]
    assert f.get("avgDelay") == -24


def test_qunar_pc_latetime_zero_not_set():
    """lateTime="0" 未报价占位不落键（宁缺勿错，备案转正）。"""
    fl = QunarCrawler._parse_pc_flights(_pc_raw(binfo_latetime="0"),
                                        "2026-10-04")
    assert "avgDelay" not in fl[0]


def test_qunar_pc_latetime_invalid_not_set():
    """非数字（脏样本）不落键——读层换位后守卫语义不变。"""
    fl = QunarCrawler._parse_pc_flights(_pc_raw(binfo_latetime="abc"),
                                        "2026-10-04")
    assert "avgDelay" not in fl[0]


def test_qunar_pc_latetime_absent_not_set():
    """binfo 段无 lateTime → 不落键。"""
    fl = QunarCrawler._parse_pc_flights(_pc_raw(), "2026-10-04")
    assert "avgDelay" not in fl[0]


# ---- avgDelay 负值渲染词面单源 _ad_txt（webui 源码级钉） ----

class TestAvgDelayWordface:
    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_ad_txt_single_source_defined(self):
        """词面单源 _ad_txt 在场：负=早到N分 / 正=延N分 / 0 与缺失空。"""
        src = self._src()
        assert "function _ad_txt" in src, "缺 _ad_txt 词面单源"
        i0 = src.index("function _ad_txt")
        seg = src[i0:i0 + 220]
        assert "早到" in seg, "词面缺负值（提前）形态"
        assert "延" in seg, "词面缺正值（延误）形态"

    def test_detail_row_consumes_ad_txt(self):
        """明细次行消费点走 _ad_txt（旧「延+负数」病面根除）。"""
        src = self._src()
        assert "_ad_txt(f.avgDelay)" in src, "明细次行未走 _ad_txt"
        assert "'延'+he(String(f.avgDelay))" not in src, \
            "旧病面「延-16分」拼接仍在场"

    def test_csv_column_consumes_ad_txt(self):
        """CSV「均延」列同走 _ad_txt（数据面与展示面同词面）。"""
        src = self._src()
        i0 = src.index("function _ad_txt")
        csv_i = src.index("'均延'")
        assert csv_i > i0, "CSV 列定义在单源之前（异常）"
        seg = src[csv_i:csv_i + 900]
        assert "_ad_txt(f.avgDelay)" in seg, "CSV 均延列未走 _ad_txt"
