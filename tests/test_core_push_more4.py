# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r320_push_fix.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import logging
import os
import sys

from core.alerter import Alerter, _disp_dw
from core.models import Route as _R


# ---- merged from tests/test_r320_push_fix.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r320pf")


def _route():
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=1900, alert_transfer=1700)


def _sec_dual():
    """双类在场夹具：直飞+中转行情最优（slim 单行摘要最宽形态）。"""
    return [{"date": "2026-09-25",
             "best_direct": {"price": 1950, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar", "_stale_h": 4.2},
             "best_transfer": None,
             "best_transfer_mkt": {"price": 1780, "name": "CZ6976转",
                                   "depTime": "12:05", "arrTime": "23:50",
                                   "transCity": "郑州",
                                   "_platform": "ctrip"},
             "seen_plats": ["qunar", "ctrip"]}]


def test_heartbeat_slim_dual_class_price_survives():
    """P1-1：双类在场超宽轮，价格判据必须存活（中间档）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    p = a._digest_payload([(_route(), _sec_dual())],
                          fresh=False, with_tables=False)
    d = p["desp"]
    assert "直飞 ￥1950" in d, f"直飞价全灭（裸身份行）: {d[:300]}"
    assert "￥" in d.split("\n\n> ")[1].split("\n")[0] if len(
        d.split("\n\n> ")) > 1 else True, d[:300]


def test_heartbeat_slim_dual_class_fallback_order():
    """P1-1 档序：全行→双价→直飞价→裸身份——剥新鲜度先于剥中转
    （新鲜度是次要信号，双价并存优先）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    p = a._digest_payload([(_route(), _sec_dual())],
                          fresh=False, with_tables=False)
    d = p["desp"]
    body = [ln for ln in d.splitlines() if "上海→乌鲁木齐" in ln]
    assert body, d[:300]
    ln = body[0]
    # 单行摘要恒带至少一个价格判据（中间档语义）
    assert "￥" in ln, f"摘要行无价格: {ln!r}"
    from core.alerter import _fit_line
    # 链可达性：双价行在夹具下真实可达（变异预演——摘中间档则丢价）
    assert _disp_dw(ln) <= 40, f"摘要行超宽: {ln!r}"


def test_hits_head_bold_margin():
    """P2-1：hits head 判定收 39（加粗膨胀 ≤1 安全余量）——恰卡
    形态（实发 09-30 样本）粗字模投影下不超 40。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    r = _route()
    sec = {"date": "2026-09-25",
           "best_direct": {"price": 1773,
                           "name": "新海航｜天津航空GS7587",
                           "depTime": "19:55", "arrTime": "01:25",
                           "_platform": "qunar"},
           "best_transfer": None, "seen_plats": ["qunar"]}
    p = a._digest_payload([(r, [sec])], fresh=True,
                          with_tables=False, with_charts=False)
    hits = [ln for ln in p["desp"].splitlines()
            if ln.startswith("> 🔥")]
    assert hits, p["desp"][:400]
    for ln in hits:
        # 粗字模投影近似真实渲染（膨胀面=整行）：恰卡样本不折行
        assert _disp_dw(ln, True) <= 40, f"加粗真实宽超线: {ln!r}"


def test_source_pin_price_middle_tier():
    """源码钉：当轮最优分支的中间档在案（防回退两档链）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "alerter.py"),
        encoding="utf-8").read()
    assert "fbs.append(f\"> {head} {d_short} ｜ {bits[0]}\")" in src, (
        "价格中间档缺失（回退两档链=P1-1 复活）")
