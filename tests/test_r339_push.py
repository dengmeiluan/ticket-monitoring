# -*- coding: utf-8 -*-
"""r339 推送审校落地（_scratch/r339e_report.md 五案 TDD）：

P1-1 特价标题 🎯 复用 qual 档位语义点 → 邮件横幅 _TIER_BANNER 首中
「达标 · 可出手」绿底——特价（≤心理价位）与达标阈值口径不同轴，
决策级误标（「低￥N 被读成可出手」P0 同型）。换 💰（非档位符号，
已在安全集在册）。
P2-1 Bark 通道强提醒文本纪律三件套（ntfy 同族律）：_alert_body 消费
（图例/仪表条/⏱/@ 行滤除）+ 档位 emoji 转写 + 截断留痕 + 悬垂冒号剥。
P2-2 特价正文：段内单 \n → 段落律 \n\n（PC 贴字「10-20￥2600」根治）；
首行进 _fit_line 家族守卫（长名域实测 48/40）。
P3-1 走势图点环小注 mkt 词条补「（未必可购）」限定（同图族与总表
summary 词条对齐）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339_push.py -q
"""
import logging
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.notifier as N
from core.specials import SpecialDeal, SpecialWatch, build_special_push

_LOG = logging.getLogger("t339p")

_W = SpecialWatch(from_code="URC", from_name="乌鲁木齐",
                  max_price=2000.0, round_trip=False)

_D = SpecialDeal(src="tuniu", from_code="URC", to_code="ALK",
                 date="2026-11-16", src_price=1800.0,
                 airline="东方航空", discount="3.2折",
                 to_name="阿拉善左旗（阿拉善左旗机场）")


# ---- P1-1：特价标题不复用档位语义点 ----

def test_special_title_avoids_tier_emoji():
    title, desp = build_special_push(_W, [(_D, 1600.0)])
    assert title, "标题空"
    for e in ("🎯", "🚨", "🔔", "🔥"):
        assert e not in title, f"标题复用档位语义点 {e}：{title}"


def test_special_title_banner_not_mislabeled():
    """决策级断言：特价标题进邮件壳横幅不产「达标」绿底。"""
    title, _ = build_special_push(_W, [(_D, 1600.0)])
    html = N._banner_html(title)
    assert "达标" not in html, "特价邮件横幅误标达标"


# ---- P2-2：特价正文段落律 + 首行行宽 ----

def test_special_desp_paragraph_law():
    """段内无单 \n（PC 贴字根治：日期与价格行间必须 \n\n）。"""
    _, desp = build_special_push(_W, [(_D, 1600.0)])
    assert "\n" not in desp.replace("\n\n", ""), \
        f"段内单 \\n 违段落律：{desp!r}"


def test_special_first_line_fitted():
    """首行（长名域）≤40 半角（_dw 真函数），且价格判据保留（地板
    档语义：✅ 短名+价格恒落位）。"""
    from core.alerter import _dw
    _, desp = build_special_push(_W, [(_D, 1600.0)])
    first = desp.split("\n")[0]
    assert _dw(first) <= 40, f"首行 {len(first)} 超 40 半角：{first!r}"
    assert "￥1600" in desp, "价格判据丢失"


# ---- P2-1：Bark 强提醒文本纪律 ----

def _mk_bark(monkeypatch):
    bk = N.BarkNotifier(key="k1", logger=_LOG)
    calls = []
    monkeypatch.setattr(
        N.httpx, "post",
        lambda u, **kw: calls.append((u, kw))
        or mock.Mock(status_code=200, json=lambda: {"code": 200}))
    return bk, calls


def test_bark_body_filters_legend_at_gauge(monkeypatch):
    """图例行/仪表条/@行滤除 + 档位 emoji 转写为词（_alert_body 同族）。"""
    bk, calls = _mk_bark(monkeypatch)
    desp = ("> ⏱ 17:53 🎯真达标 🟩破线 🟨擦边 超线\n\n"
            "#### 上海 → 海口\n\n直飞 **￥900** 低￥200\n\n"
            "🟩🟩🟩🟩🟩\n\n@13800138000 \n\n⏰ 17:53")
    bk.send("达标", desp)
    body = calls[0][1]["json"]["body"]
    assert "⏱" not in body and "🟩" not in body, body
    assert "@138" not in body, body
    assert "￥900" in body, "价格判据丢失"


def test_bark_truncation_has_note(monkeypatch):
    """600 截断带留痕（「（已截断」尾注，钉钉/ntfy/短信/WinToast 同族）。"""
    bk, calls = _mk_bark(monkeypatch)
    bk.send("t", "字" * 900)
    body = calls[0][1]["json"]["body"]
    assert len(body) <= 640, f"截断失效：{len(body)}"
    assert "已截断" in body, f"截断无留痕：{body[-40:]!r}"


def test_bark_dangling_colon_stripped(monkeypatch):
    """URL 避让让位后悬垂冒号剥（ntfy 同构守卫）。"""
    bk, calls = _mk_bark(monkeypatch)
    bk.send("t", "中转 ￥2650:\n\n[购买](https://example.invalid/x)")
    body = calls[0][1]["json"]["body"]
    assert not body.rstrip().endswith((":", "：")), f"悬垂冒号：{body[-30:]!r}"


# ---- P3-1：走势图小注 mkt 词条购买性限定 ----

def test_trend_ring_note_mkt_buy_limit():
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "report.py"), encoding="utf-8").read()
    assert "未必可购" in mod, "走势图小注缺 mkt 购买性限定"
