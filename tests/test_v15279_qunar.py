# -*- coding: utf-8 -*-
"""1.5.279: Qunar PC 断供 → m.flight H5 主路径 / 用户链接同源；
Ctrip 国际登录态识别。"""
import inspect
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        return f.read()


def test_qunar_crawler_h5_first_and_pc_dead():
    from crawlers.qunar import QunarCrawler as QC
    assert QC.URL_TPL.startswith(
        "https://m.flight.qunar.com/ncs/page/flightlist")
    assert "flight.qunar.com/site/oneway_list.htm" not in QC.URL_TPL
    fn = inspect.getsource(QC._fetch_one)
    assert fn.index("_fetch_via_browser") < fn.index("_fetch_via_pc")
    body = inspect.getsource(QC._fetch_inner)
    assert "H5 浏览器优先" not in body  # 注释在 _fetch_one，防误挂
    assert "H5 浏览器优先" in fn


def test_qunar_user_links_are_h5_not_pc():
    import logging
    from core.alerter import Alerter
    from core.models import Route
    a = Alerter(logging.getLogger("t"), storage=None)
    r = Route(from_code="SHA", from_name="上海", to_code="CAN",
              to_name="广州", dates=["2026-10-23"])
    u = a._build_view_url(r, "2026-10-23", "qunar")
    assert "m.flight.qunar.com/ncs/page/flightlist" in u
    assert "flight.qunar.com/site/oneway_list.htm" not in u
    assert "depCity=%E4%B8%8A%E6%B5%B7" in u and "goDate=2026-10-23" in u


def test_qunar_page_has_no_dead_pc_link():
    page = _src()
    assert "flight.qunar.com/site/oneway_list.htm" not in page
    assert "m.flight.qunar.com/ncs/page/flightlist" in page


def test_ctrip_intl_login_is_classified():
    src = open(os.path.join(ROOT, "crawlers", "ctrip.py"),
               encoding="utf-8").read()
    assert "需登录 · 国际列表需携程会话" in src
    assert "CtripCrawler.login_suspect = True" in src
    assert "服务器发生异常" in src
