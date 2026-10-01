# -*- coding: utf-8 -*-
"""v1.5.82 渠道字段回归：qunar PC lateTime 读层修复（B1）+ avgDelay
负值渲染词面单源。

- B1 读层错位修复：lateTime 真值 100% 在 binfo/binfo1 分段层
  （dump 实证 92/92+51/51，顶层恒缺 0/143），现行 f.get("lateTime")
  顶层读法导致 PC 代 avgDelay 0 命中——改读 b1（binfo1 or binfo，
  直飞/中转首段一体覆盖；勿取 binfo2，二段延误≠全程口径）
- 值域负数如实透传（dump 实测 -24~0，语义=历史平均提前分钟），
  渲染端词面按符号分叉单源 _ad_txt：负=早到N分 / 正=延N分 / 0 与
  缺失不占位；"0" 未报价占位不落键（宁缺勿错，v1.5.81 Minor 备案转正）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v182_fields.py -q
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


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
        with open(_w.__file__, encoding="utf-8") as f:
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
