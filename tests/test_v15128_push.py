# -*- coding: utf-8 -*-
"""P3-2 接力修：_kpi_block 行3 丢注循环无地板档。

transCity 是渠道外部字段（现实词面 2-6 汉字，病理形态 ≥14 汉字可达）：
行3 丢注循环把行情注/税前注/舱位 token 依次删光后，`> 经{tc} 停{lay}`
仍可超 40 直出——行3 是 KPI 三行里唯一没过 _fit_line 的行
（r227 重放定性：镜像 14 字病理 → 41/40 直出）。

修复形态：循环后地板档按 _dw_raw 浮点累计逐字截（与 _mini_split /
_l2_fallbacks 地板同构），判据行恒达标不直出；截断保 token 原序
（先丢次要信号，城市判据首段恒保留可辨识）。
"""
import logging as _lg
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw
from core.models import Route

_TC_PATHO = "乌鲁木齐地窝堡国际机场中转楼T2"   # 病理 transCity（渠道外部字段）


def _mk_route(ad=1900, at=1700):
    return Route(from_code="SHA", to_code="URC", from_name="上海",
                 to_name="乌鲁木齐", dates=["2026-09-25"],
                 alert_direct=ad, alert_transfer=at)


def _mk_secs(direct_price, transfer_price=None, **tk):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        s["best_direct"] = {"price": direct_price, "name": "MU8369",
                            "depTime": "19:55", "arrTime": "01:25",
                            "_platform": "qunar"}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
        s["best_transfer"].update(tk)
    return [s]


def _desp_lines(secs, route=None):
    a = Alerter(_lg.getLogger("t"), storage=None)
    p = a._digest_payload([(route or _mk_route(), secs)],
                          fresh=False, with_tables=False)
    return [ln for ln in p["desp"].split("\n") if ln.strip()]


def test_kpi_l3_pathological_transcity_fits_40():
    """病理 transCity：行3 丢注循环删光 extras 后仍超 40——不得直出。"""
    lines = _desp_lines(_mk_secs(1950, 1780, transCity=_TC_PATHO,
                                 layoverT="23:59"))
    bad = [(round(_disp_dw(ln)), ln) for ln in lines if _disp_dw(ln) > 40]
    assert not bad, f"超 40 行直出: {bad}"


def test_kpi_l3_floor_keeps_judgment():
    """地板档不是删行：城市判据首段必须保留（防修复把行3 整行吞掉）。"""
    lines = _desp_lines(_mk_secs(1950, 1780, transCity=_TC_PATHO,
                                 layoverT="23:59"))
    assert any(ln.startswith("> 经") for ln in lines), lines


def test_kpi_l3_direct_baggage_combo_fits_40():
    """直挂词与病理 tc 同现（直挂词不在丢注循环 extras 删单里，循环
    删不动）：整行仍须恒达标。"""
    r = _mk_route()
    r.transfer_baggage = "direct"
    lines = _desp_lines(_mk_secs(1950, 1780, transCity=_TC_PATHO,
                                 layoverT="23:59"), route=r)
    bad = [(round(_disp_dw(ln)), ln) for ln in lines if _disp_dw(ln) > 40]
    assert not bad, f"超 40 行直出: {bad}"


def test_kpi_l3_normal_transcity_unchanged():
    """现实词面（2-6 汉字）不触地板：行3 原样全信息输出。"""
    lines = _desp_lines(_mk_secs(1950, 1780, transCity="郑州",
                                 layoverT="2:50"))
    assert any(ln == "> 经郑州 停2:50" for ln in lines), lines
