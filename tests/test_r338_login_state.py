# -*- coding: utf-8 -*-
"""r338 用户实报双缺陷钉（登录态卡片脱节 + 重复弹窗）。

缺陷 1（复位条件过宽）：qunar fetch 外壳「任何出数即清 login_suspect」
——日历价查询不需要登录（渠道侧「低价日历仍出价」在案），纯日历行
出数会把明细软空置位的会话失效证据洗掉：UI 卡片回「已有登录态」而
明细会话实际已死（用户实报：卡片显示已登录、弹窗登录发现网页端
未登录；实录 07:31-08:41 日历价每 1-10 分钟出 1 条、失效证据被反复
清洗）。修法：复位判据与 webui cal 行判定同构——行内 flight_no/
depart_time 至少一者在场（明细行）才证会话有效；纯日历行出数不清
证据（元素是 FlightPrice dataclass，按属性取——.get 形态对 dataclass
AttributeError 出数轮炸渠道，r290 钉 CI 抓获形态）。

缺陷 2（pending 窗防重入）：会话刚保存（_finish_login 置 pending 验
证窗）后再点「弹窗登录」会开第二个窗口并把卡片拉回「登录中…」——
lgFinishWatch 16s 轮询窗内 UI 反馈未落，用户误判失败重复点击（实录
08:36:40 保存成功 / 08:36:49 第二窗口弹出）。修法：_start_login 在
pending 窗内拒绝新弹窗（「会话刚保存，下轮采集验证中」）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r338_login_state.py -q
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PLAT = "qunar"


def _fresh_suspect():
    from crawlers.qunar import QunarCrawler
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    # 剥退避表（(0,) 零秒）：mock 路径的任何意外异常会被 fetch 外壳
    # 吞掉落进退避循环——真实 _BACKOFF_S 会让测试真睡 570 秒（挂起
    # 形态实录）；r290 fixture 同款纪律
    QunarCrawler._BACKOFF_S = (0,)
    QunarCrawler.login_suspect = True
    return QunarCrawler


def _fp(**kw):
    """FlightPrice 构造（_fetch_inner 真实返回元素是 dataclass 非
    dict——mock 必须尊重公共契约，dict 形态会让 .get 形态的缺陷判据
    在测试里假活、生产 AttributeError）。"""
    from core.models import FlightPrice
    base = dict(platform="qunar", from_city="SHA", to_city="PEK",
                depart_date="2026-11-16", price=500.0)
    base.update(kw)
    return FlightPrice(**base)


# ---------- 缺陷 1：login_suspect 复位判据 ----------

def test_calendar_only_rows_keep_suspect(monkeypatch):
    """纯日历行出数（无 flight_no/depart_time）不清会话失效证据。"""
    cls = _fresh_suspect()
    crawler = cls({}, logging.getLogger("t"))
    monkeypatch.setattr(crawler, "_fetch_inner", lambda f, t, d: [_fp()])
    res = crawler.fetch("SHA", "PEK", ["2026-11-16"])
    assert res, "日历行应照常出数（复位判据收窄不改变出数行为）"
    assert cls.login_suspect is True, (
        "纯日历行不证会话有效——失效证据必须保留（否则 UI 卡片"
        "在明细会话已死时仍显示「已有登录态」）")


def test_detail_rows_clear_suspect(monkeypatch):
    """明细行出数（flight_no 在场）照常清证据退「已有登录态」。"""
    cls = _fresh_suspect()
    crawler = cls({}, logging.getLogger("t"))
    monkeypatch.setattr(
        crawler, "_fetch_inner",
        lambda f, t, d: [_fp(flight_no="MU1234", depart_time="08:00")])
    res = crawler.fetch("SHA", "PEK", ["2026-11-16"])
    assert res
    assert cls.login_suspect is False


def test_mixed_rows_clear_suspect(monkeypatch):
    """混合行（日历+明细）按明细在场清证据（会话确证有效）。"""
    cls = _fresh_suspect()
    crawler = cls({}, logging.getLogger("t"))
    monkeypatch.setattr(
        crawler, "_fetch_inner",
        lambda f, t, d: [_fp(), _fp(flight_no="MU1234", depart_time="08:00")])
    crawler.fetch("SHA", "PEK", ["2026-11-16"])
    assert cls.login_suspect is False


# ---------- 缺陷 2：pending 窗防重入 ----------

def test_start_login_rejected_within_pending_window(monkeypatch):
    """会话刚保存（pending 窗内）再点弹窗登录被拒（防第二窗口）。"""
    import webui
    from crawlers import REGISTRY
    # 防真弹窗：_login_window 类级 no-op（RED 态 _start_login 仍会起
    # 线程——不 patch 会真开 Playwright 有头窗口）
    monkeypatch.setattr(REGISTRY[_PLAT], "_login_window",
                        lambda self, evt, *args, **kwargs: None)
    webui._State.login_sessions.pop(_PLAT, None)
    webui._State.login_pending[_PLAT] = time.time()
    try:
        r = webui._start_login(_PLAT)
        assert r.get("ok") is False, (
            "pending 验证窗内拒绝新弹窗——刚保存的会话在 10 分钟窗内"
            "待下轮采集验证，重复弹窗把卡片拉回「登录中」吞掉用户成果")
        assert _PLAT not in webui._State.login_sessions
    finally:
        webui._State.login_pending.pop(_PLAT, None)
        webui._State.login_sessions.pop(_PLAT, None)
