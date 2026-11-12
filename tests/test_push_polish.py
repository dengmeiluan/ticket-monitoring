# -*- coding: utf-8 -*-
"""推送图文打磨四案：

1. 仪表条 emoji 挂档位投影（单源律）：_gauge 颜色字面与 _TIER_TABLE
   改版日必须同步，字面 🟩 是档位 emoji 单源的最后一块漂移面。
2. legacy 明细头注行宽缓冲：头注恰卡 39/40 时档位全词改版（真达标
   →四字）即 41/40 折行——与日报兜底标题减字同族（恰满零缓冲）。
3. 病理长渠道名截断留痕：兜底行截尾渠道名补半角 (截) 标——与运维
   对账行的截断标记纪律一致（静默截尾=读者不知有截）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_push_polish.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.alerter as alerter  # noqa: E402
from core.alerter import Alerter, _disp_dw  # noqa: E402

_LOG = logging.getLogger("push_polish")


def test_gauge_emoji_follows_tier_table(monkeypatch):
    """仪表条颜色挂 TIER_EMOJI 投影：改档位 emoji 单源处，仪表条
    随动不漂移（变异验证：把投影值改掉，输出必须跟着变）。"""
    monkeypatch.setitem(alerter.TIER_EMOJI, "mkt", "◇")
    out = Alerter._gauge(100.0, 200.0, bars=3)
    assert out == "◇" * 3, out


def test_gauge_overline_still_empty():
    """超线默认态不占语义点（返空）不受收口影响。"""
    assert Alerter._gauge(300.0, 200.0) == ""


def test_legacy_tbl_head_has_buffer():
    """legacy 明细头注行宽 ≤38（留 2 半角缓冲）：档位全词改版
    （真达标→四字 +2）不折行。"""
    head = "#### 📋 明细TOP " + alerter._TBL_HEAD_TIER
    assert _disp_dw(head) <= 38, (_disp_dw(head), head)


def test_retired_top5_word_absent():
    """「明细TOP5」9 半角形态退役（39/40 恰满零缓冲的根源）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "alerter.py"),
        encoding="utf-8").read()
    assert "明细TOP5" not in src


def test_daily_market_clip_marks():
    """日报兜底渠道名截断留痕：病理长平台键截尾后带 (截) 标。"""
    from report import _daily_market_fallback
    long_plat = "超长平台名称测试用假想渠道" * 3
    out = _daily_market_fallback({long_plat: (1234.0, True)})
    assert out, out
    assert "(截)" in out, out
    for ln in out.strip().split("\n\n"):
        assert _disp_dw(ln) <= 40, ln


def test_channel_market_clip_marks():
    """告警兜底渠道名截断留痕：与日报侧同纪律。"""
    a = Alerter(_LOG, storage=None)
    long_plat = "超长平台名称测试用假想渠道" * 3
    sections = [{"date": "2026-10-11",
                 "platform_mins": {long_plat: 1234.0},
                 "plat_top3": {long_plat: [
                     {"price": 1234.0, "name": "MU8369",
                      "depTime": "19:55", "arrTime": "01:25"}]}}]
    out = a._channel_market_lines(sections)
    assert out, out
    assert "(截)" in out, out
    for ln in out.strip().split("\n\n"):
        if ln:
            assert _disp_dw(ln) <= 40, ln


def test_webui_ring_note_mkt_expanded_word():
    """webui 环标豁免区 mkt 词与 alerter 单源的同步律钉（alerter
    导语律注释「同步律注释+test 源码钉代管」的落地）：单源 FULL 词
    改版日，webui 豁免区多三字的展开词必须随之复核语义仍成立；反向
    「顺手统一」（把展开词收进单源或删除）也在此拦下——推送图例
    40 半角预算装不下展开词，豁免区只存在于 UI 渲染面。计数钉口径：
    webui.py 源码恰 2 处（折线/K线图注各一），备案注释已避让词面。"""
    assert alerter.TIER_FULL["mkt"] == "行情破线"
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    # 环标图例专属锚（</span> 后贴词面）：恰折线/K线两分支各一处；
    # 全词另有价格格 title 与注释形态，不在本钉射程
    assert src.count("span>行情破线未达标") == 2, \
        src.count("span>行情破线未达标")
