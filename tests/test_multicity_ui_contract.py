# -*- coding: utf-8 -*-
"""多程 UI 面契约：配置编辑器、概览整单卡、状态供货与提醒接线不被拆掉。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402


def _src():
    with open(webui.__file__, encoding="utf-8") as f:
        return f.read()


def test_config_page_has_mc_editor():
    page = webui.PAGE
    for token in ("function mcCardHTML(", "function addMCRoute(",
                  "function mcSegSet(", "function mcAddSeg(",
                  "function mcDelSeg(", "srow mcrow",
                  "添加多程行程", "多程仅携程 PC 可采",
                  "3+ 段当前未接通", "整单心理价"):
        assert token in page, token


def test_route_helpers_are_mc_aware():
    page = webui.PAGE
    for token in ("function _isMC(", "function _mcIssues(",
                  "function _routeDates(", "function _mcEnds(",
                  "if(_isMC(r)){h+=mcCardHTML(i,j,r);return;}",
                  "_routeDates(r).forEach", "const _e=_rEnds(r);",
                  "if(_isMC(r))return _mcIssues(r);",
                  "rr.style.display=(!_mc&&_rtOn(r)", "整单≤￥"):
        assert token in page, token


def test_overview_card_and_state_contract():
    page = webui.PAGE
    src = _src()
    for token in ("function monMCCard(", 'id="monMCList"',
                  "u.mcRoutes", "多程行程 · 整单总价",
                  "整单总价只取渠道页面，不由段价相加",
                  "m.history", "mcspark", "trendSparkSvg",
                  "function mcExport(", "function mcCsvRows(",
                  "function _csvCell("):
        assert token in page, token
    for token in ('"mcRoutes": mc_routes', "_multicity_payload(",
                  "def _multicity_history(", "mode=ro",
                  "def _multicity_alert_round(",
                  "get_alert_state(dk)", "set_alert_state(dk, price)"):
        assert token in src, token
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        main_src = f.read()
    for token in ("def collect_multicity(", "_multicity_alert_round(",
                  "get_crawlers([\"ctrip\"])"):
        assert token in main_src, token
