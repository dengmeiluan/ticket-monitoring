# -*- coding: utf-8 -*-
"""r306 渠道调研落地：qunar PC transGoDate 源断供换源。

binfo1.transCityDepDate 在 PC 主路径 dump 全量 0 命中（调研期 23/23
在场→0/210 断供，跨天中转「二段哪天起飞」展示位失明）——兜底
binfo2.date（75/75 在场，语义=二段起飞日，_layover_pinned 已消费同键
并做 a1d≤d2d≤a2d 校验）。守卫三件套（YYYY-MM-DD 形 + 晚于出发日 +
仅中转行）对兜底源同门生效；b1 源在场时原序优先（双容器并读律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r306_fields.py
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

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
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    assert '"transGoDate": (f.get("transGoDate") or "").strip(),' in src
    assert "(f.lay2dep||f.transGoDate)" in src
