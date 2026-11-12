# -*- coding: utf-8 -*-
"""r1773：同程城市页判据过期——App 现在叫「选择目的地」。

07:43 的真实账本 + 我 11-11 的手工截图对照：

- `parse_form_slots` 给出的上海=(314,879)、北京=(945,879) 与 `_form_slot()` **完全一致**
  → 坐标本来没问题（上一版把它归因到坐标是错的）；
- 真因是**判据过期**：点下去其实开了城市页，但那一页标题是「选择目的地」，
  正文是「你可能还想去 / 支持搜索城市 / 热门推荐 / 历史 · 热门」，
  而爬虫只认「热门城市 / 猜你想去」→ 等 12 秒 → 判「打不开城市页」。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng import _CITY_PAGE_MARKS, _is_city_page  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")
FORM = os.path.join(ROOT, "user_data", "app_tongcheng",
                    "app_fail_20261112_074311_043968_app-city.xml")


def test_new_city_page_wording_is_recognised():
    xml = ('<hierarchy><node text="选择目的地" bounds="[0,0][100,50]"/>'
           '<node text="你可能还想去" bounds="[0,60][100,90]"/>'
           '<node text="支持搜索城市/国家 中英文或拼音" bounds="[0,100][100,130]"/>'
           '</hierarchy>')
    assert _is_city_page(xml) is True
    assert "选择目的地" in _CITY_PAGE_MARKS


def test_train_and_form_pages_are_not_city_pages():
    train = io.open(TRAIN, encoding="utf-8", errors="replace").read()
    assert _is_city_page(train) is False, "火车票页被当成城市页"
    if os.path.exists(FORM):
        form = io.open(FORM, encoding="utf-8", errors="replace").read()
        assert _is_city_page(form) is False, "机票表单页被当成城市页"


def test_no_legacy_marker_only_checks_left():
    src = io.open(os.path.join(ROOT, "crawlers", "app_tongcheng.py"),
                  encoding="utf-8").read()
    assert '"热门城市" in x or "猜你想去" in x' not in src, \
        "仍有只认旧两个词的判据（会在新版城市页上判「没打开」）"
    assert src.count("_is_city_page(") >= 4, "没把判据统一到 helper"
