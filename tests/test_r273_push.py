# -*- coding: utf-8 -*-
"""r273 推送面四案（TDD：goal_r273_push.md 审校立案）：

P1 孤「经济舱」行3 引用段整段省略——直飞行默认舱位独占引用段占
   生产推送 78.5%（3021/3850、4956 段），WinToast 连读「；经济舱；」、
   短信 900 字额度与 TTS 同耗；「默认态不占语义位」与「超线不加点」
   同哲学。非默认舱位（公务/头等/超级经济）=异常态警示必留；
   「经济舱(Y)」括注形态含退改等级信息不省；中转行行3 多 token 不动。
P2 建议行 label 与档词贴法两制收口——达标档「中转 真达标」带空格，
   行情破线/恰线/擦边三档「中转行情低￥40」直连（:1486 注释自认
   空格防粘连连读，三分支漏网同律），同族词面两种贴法并存。
P3 日报 KPI 未设线+5 位价参照静默丢（r271 P3-2 翻身）——降级链
   插「保参照丢标注」中档（量测 33/40 可落位），降级序
   全形→保参照→保标注。
P4 日报空池补偿行与 p7 引用行四连换行（r269 观察级翻身）——
   两调用点改 `(_p7_quote_line() or "\n\n")`：p7 非空消四连、
   p7 空保持单空段，双分支零回归。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r273_push.py -q
"""
import logging as _lg
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402
from core.models import Route  # noqa: E402


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
    a = Alerter(_lg.getLogger("t273p"), storage=None)
    p = a._digest_payload([(route or _mk_route(), secs)],
                          fresh=False, with_tables=False)
    return [ln for ln in p["desp"].split("\n") if ln.strip()]


# ---------- P1: 孤「经济舱」行3 段 ----------

def test_kpi_l3_lone_default_cabin_omitted():
    secs = _mk_secs(1701)
    secs[0]["best_direct"]["cabin"] = "Y"          # 单字母默认档 → 裸「经济舱」
    lines = _desp_lines(secs)
    assert not any("经济舱" in ln for ln in lines), (
        f"直飞行默认舱位不应独占行3 引用段: {lines}")


def test_kpi_l3_nondefault_cabin_kept():
    secs = _mk_secs(1701)
    secs[0]["best_direct"]["cabin"] = "超级经济舱"   # 非默认=异常态警示必留
    lines = _desp_lines(secs)
    assert any("超级经济舱" in ln for ln in lines), lines


def test_kpi_l3_cabin_paren_form_kept():
    secs = _mk_secs(1701)
    secs[0]["best_direct"]["cabin"] = "经济舱(Y)"   # 括注形态含退改等级信息
    lines = _desp_lines(secs)
    assert any("经济舱(Y)" in ln for ln in lines), lines


def test_kpi_l3_transfer_multi_token_unchanged():
    secs = _mk_secs(None, 1660, cabin="Y")
    lines = _desp_lines(secs)
    assert any(ln.startswith("> ") and "经济舱" in ln for ln in lines), (
        f"中转行行3 多 token 不动: {lines}")


# ---------- P2: 建议行贴法两制 ----------

def _suggest(route, s):
    return Alerter(_lg.getLogger("t273p"), storage=None)._suggest_line(route, s)


def test_suggest_mkt_branch_space():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1750, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1660, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r == "中转 行情低￥40，蹲守", r


def test_suggest_exact_line_branch_space():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1750, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1700, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r.startswith("中转 行情破线"), r


def test_suggest_near_branch_space():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1750, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1730, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r.startswith("中转 擦边"), r


def test_suggest_qual_branch_space_unchanged():
    route = _mk_route(ad=0, at=1700)
    s = {"best_direct": None,
         "best_transfer": {"price": 1660, "_platform": "ctrip",
                           "transCity": "西安"},
         "best_transfer_mkt": {"price": 1660, "_platform": "ctrip"}}
    r = _suggest(route, s)
    assert r.startswith("中转 真达标 "), r


# ---------- P3/P4: 日报路径源码钉（闭包内函数，行为驱动需整链 DB 夹具） ----------

def _report_src():
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "report.py"),
            encoding="utf-8") as fh:
        return fh.read()


def test_daily_kpi_noline_reference_fallback_tier():
    src = _report_src()
    old = 'fallbacks=[base + "（未设线）"])'
    assert old not in src, "未设线分支仍是单档降级（参照静默丢）"
    # 参照词分支内绑一次（v225 计数钉语义：每分支求值一次），
    # fallback 链 = 全形 → 保参照丢标注（33/40 量测可落位）→ 保标注丢参照
    bind = "_p7n = _p7_note(False)"
    chain = 'fallbacks=[base + _p7n, base + "（未设线）"])'
    assert bind in src and chain in src, "未设线分支缺「保参照丢标注」中档"


def test_daily_empty_pool_p7_quad_newline_fixed():
    src = _report_src()
    assert src.count('(_p7_quote_line() or "\\n\\n")') == 2, (
        "空池两调用点应改 or 表达式：p7 非空消四连、p7 空保持单空段")
    assert '+ "\\n\\n" + _p7_quote_line()' not in src, (
        "旧拼接形态（恒前导空段+尾空段）禁复活")
