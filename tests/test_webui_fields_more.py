# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r306_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import pytest
import sys

from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r306_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PC_BASE = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "FM9223/FM9224", "minPrice": "2472", "transCity": "",
         "extparams": {},
         "binfo": {"airCode": "FM9223", "shortName": "上航",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-10-04", "arrDate": "2026-10-05"}}]}})


def _pc_trans_sample(**kw):
    """PC 中转行夹具（dump 实证形态）：binfo1.transCityDepDate 与
    binfo2.date 均可缺席——断供形态=前者 0/210，兜底源 75/75 在场。"""
    s = json.loads(_PC_BASE)
    row = s["data"]["flights"][0]
    row["transCity"] = "兰州"
    b1 = {"depTime": "08:00", "arrTime": "11:00", "date": "2026-10-04",
          "depTerminal": "", "arrTerminal": "T2",
          "depAirport": "天山", "arrAirport": "地窝堡"}
    tgd = kw.pop("tgd", None)
    if tgd is not None:
        b1["transCityDepDate"] = tgd
    b2 = {"depTime": "15:30", "arrTime": "18:00",
          "arrDate": "2026-10-05"}
    b2d = kw.pop("b2date", None)
    if b2d is not None:
        b2["date"] = b2d
    row["binfo1"] = b1
    row["binfo2"] = b2
    return json.dumps(s)


def test_qunar_pc_trans_go_date_fallback_binfo2_date():
    # b1 源断供（键缺席）时兜底 binfo2.date：跨天中转二段起飞日复明
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample(b2date="2026-10-05"), "2026-10-04")
    assert fl and fl[0]["transGoDate"] == "2026-10-05"


def test_qunar_pc_trans_go_date_b1_source_wins():
    # 双源并存在场：b1 原序优先（渠道原序=权威序，双容器并读律），
    # b2.date 语义相同不因兜底翻转
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample(tgd="2026-10-05", b2date="2026-10-05"),
        "2026-10-04")
    assert fl and fl[0]["transGoDate"] == "2026-10-05"


def test_qunar_pc_trans_go_date_fallback_guards():
    # 守卫三件套对兜底源同门：同日不落（无增量）/坏格式不落/
    # 直飞行不落（键语义=中转二段）
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample(b2date="2026-10-04"), "2026-10-04")
    assert fl and "transGoDate" not in fl[0]
    fl2 = QunarCrawler._parse_pc_flights(
        _pc_trans_sample(b2date="10-05"), "2026-10-04")
    assert fl2 and "transGoDate" not in fl2[0]
    s = json.loads(_pc_trans_sample(b2date="2026-10-05"))
    # 真直飞行=无 binfo1/binfo2 段容器（PC 语义 binfo2 在场即中转/
    # 经停，transCity 偶发缺省也按中转——直接清 transCity 是「缺省
    # 中转」形态非直飞，夹具病修正）
    del s["data"]["flights"][0]["binfo1"]
    del s["data"]["flights"][0]["binfo2"]
    fl3 = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl3 and "transGoDate" not in fl3[0]


def test_qunar_pc_trans_go_date_fallback_earlier_not_set():
    # 早于出发日（不合理）的兜底源同样不落
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample(b2date="2026-10-03"), "2026-10-04")
    assert fl and "transGoDate" not in fl[0]


def test_webui_trans_go_date_gate_unchanged():
    # 白名单与渲染门零改动锚：消费端（明细「二段 X 起飞」拼 MM-DD）
    # 对恢复供给自动生效
    import webui
    src = webui_full_src()
    assert '"transGoDate": (f.get("transGoDate") or "").strip(),' in src
    assert "(f.lay2dep||f.transGoDate)" in src
