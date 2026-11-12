# -*- coding: utf-8 -*-
"""r976：app_qunar 选日期失败后要重试一次（现场：弹层被误触关掉）。

证据（2026-11-05 07:03:53 真机现场 `debug/scene/qunar_app_20261105_070353_pickdate-cell.txt`）：
页面停在**单程列表页**——头部「上海 / 曼谷」、MU/KY 航班卡齐全，
说明日历弹层在选日途中被误触关掉、并且搜索被触发了。
`_pick_date` 第 ③ 步里 `"选择日期" not in xml` 成立 → 直接放弃这一天，
于是明明能再选一次的一天被记成 0 行（`pick-date-failed`）。

原实现只 `_ensure_home()` 一次就返回失败。现在：回首页 → 重试一次。
一次为限：每次失败约 30–40s，而单航线预算 `android.fetch_budget_s=180` 是硬约束。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r976_qunar_pickdate_retry.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_qunar import AppQunarCrawler  # noqa: E402


class _Dev:
    def dump(self):
        return "<x/>"

    def window_size(self):
        return (900, 1600)


def _crawler(pick_results, rows_note="航班明细"):
    """造一个只测 `_one_date` 编排的替身（不打设备、不解析页面）。"""
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.login_suspect = False
    c.last_error = ""
    c.paths = []
    calls = {"pick": 0, "home": 0}

    c._ensure_home = lambda dev: "<home/>"            # noqa: E712
    c._route_unchanged = lambda dev, a, b: True       # 航线未变 → 跳过设城市
    c._scroll_home = lambda dev, want="": "<home/>"

    def _pick(dev, xml, target):
        i = calls["pick"]
        calls["pick"] += 1
        return bool(pick_results[i]) if i < len(pick_results) else False


    c._pick_date = _pick
    c.logger = type("L", (), {
        "info": staticmethod(lambda *a, **k: None),
        "warning": staticmethod(lambda *a, **k: None),
        "error": staticmethod(lambda *a, **k: None),
    })()

    return c, calls


def _run(c, monkeypatch):
    """跑 `_one_date`，把选日之后的重活（搜索/解析）替换成哨兵。

    `_one_date` 选日成功后的最后一跳是
    `return self._search_and_parse(dev, target, from_city, to_city)`，
    所以替身必须是这个 4 参签名；返回一行价格即代表"这一天没被白丢"。
    """
    import crawlers.app_qunar as m
    monkeypatch.setattr(m.AppQunarCrawler, "_search_and_parse",
                        lambda self, dev, target, fc="", tc="": [{"price": 662}],
                        raising=False)
    return c._one_date(_Dev(), "上海", "曼谷", "2026-11-16")


def test_retries_once_after_pick_date_failure(monkeypatch):
    """第一次选日失败、第二次成功 → 必须继续搜索，而不是报 pick-date-failed。"""
    c, calls = _crawler([False, True])
    got = _run(c, monkeypatch)
    assert calls["pick"] == 2, "选日期没有重试（现场那次弹层被误触关掉）: %r" % calls
    assert got == [{"price": 662}], got


def test_gives_up_after_second_failure(monkeypatch):
    """两次都失败才认输，且不得继续搜索（否则会记串日期价）。"""
    c, calls = _crawler([False, False])
    got = _run(c, monkeypatch)
    assert calls["pick"] == 2, calls
    # 两次都失败 → 不搜索、返回 ([], "pick-date-failed")（绝不产出日期错位价）
    assert got == ([], "pick-date-failed"), got


def test_first_try_success_does_not_retry(monkeypatch):
    """一次就成功时不许再点一次（白烧 30–40s 设备预算）。"""
    c, calls = _crawler([True])
    got = _run(c, monkeypatch)
    assert calls["pick"] == 1, calls
    assert got == [{"price": 662}], got


def test_retry_is_wired_in_source():
    """结构约束：`_one_date` 的失败分支里必须有第二次 `_pick_date` 调用。

    锚点取 `_one_date` 函数体之后的第一处 `pick-date-failed`
    （文件里更早的那处是 `_fetch_locked` 的注释，不是失败分支）。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    start = src.find("def _one_date(")
    assert start > 0, "找不到 _one_date"
    # 锚点用**真正的返回语句**：`_one_date` 的 docstring 里也写着
    # `pick-date-failed`（解释 reason 语义），按裸字样找会命中 docstring。
    i = src.find('return [], "pick-date-failed"', start)
    assert i > start, "找不到 _one_date 里真正的 pick-date-failed 返回"
    seg = src[start:i]
    assert seg.count("self._pick_date(") == 2, \
        "失败分支里应恰好有 2 次 _pick_date（主调用 + 重试），实际 %d" \
        % seg.count("self._pick_date(")
