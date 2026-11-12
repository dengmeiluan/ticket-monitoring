# -*- coding: utf-8 -*-
"""r1577：同程会记住上次停留的 tab——停在「火车票」时必须先切回「机票」。

证据来自生产：2026-11-11 自动留证的 `app-city` 失败 dump
（`tests/fixtures/tongcheng_train_page.xml`）显示那一刻屏上是**火车票表单**
（查询火车票 / 高铁动车 / 学生票 / 上海→北京 / 11月12日），城市位当然找不到。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng import (  # noqa: E402
    _flight_tab_node, is_train_page)
from crawlers.app_tongcheng_parse import is_form  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


def _fixture():
    return io.open(FIX, encoding="utf-8", errors="replace").read()


def test_train_page_is_recognised():
    xml = _fixture()
    assert is_train_page(xml) is True, "火车票页没被认出来——城市位会一直找错"
    assert is_form(xml) is False, "火车票页被当成机票表单：城市/日期会读到火车票的"


def test_flight_tab_node_is_the_topmost():
    node = _flight_tab_node(_fixture())
    assert node is not None, "火车票页里找不到「机票」tab，没法切回去"
    # tab 在顶部；同屏没有比它更靠上的「机票」候选
    assert node["cy"] < 1200, "取到的「机票」节点不在顶部区域：%s" % node


def test_plain_text_is_not_train_page():
    assert is_train_page("<hierarchy></hierarchy>") is False
    assert is_train_page('<node text="机票查询"/>') is False, \
        "有机票查询就不算火车票页"
