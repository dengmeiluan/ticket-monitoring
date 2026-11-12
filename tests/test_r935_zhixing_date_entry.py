# -*- coding: utf-8 -*-
"""r935：日期入口只认中文格式，横线格式永远找不到。

真实日志（2026-11-04 11:28，重启后第一轮）：

    [app_zhixing] 长窗口日历未打开：找不到日期入口
    [app_zhixing] 明细页没解析出带价航班：2026-11-16
    [app_zhixing] 抓取完成，得到 0 条记录

`open_date_dialog()` 找日期入口的判据是：

```python
if re.fullmatch(r"\\d{1,2}月\\d{1,2}日", n.text or ""):
```

但智行的日期文案有**两种**，而 `tests/fixtures/zhixing_list_dump.xml`
（真实真机 dump）里**只有横线那种**：

    中文格式节点: []                                  ← 一个都没有
    横线格式节点: ['10-29', '10-30', '10-31', '11-01', ...]

也就是说在这份真实页面上，旧判据**必然**返回「找不到日期入口」——
长窗口日历打不开，明细页自然没有带价航班。

修法：两种格式都认，**优先后中文**（它才是「打开日历」的那一行），
没有再退回横线格子。

> 这类 bug 的共同点：**判据假设了"只有一种写法"**。修的时候要拿真实
> fixture 验一遍「旧判据在这份数据上能不能命中」——能命中才说明判据成立。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r935_zhixing_date_entry.py -q
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_zhixing_nav import nodes, open_date_dialog  # noqa: E402

_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "zhixing_list_dump.xml")


# ---------------------------------------------------------------------------
# 1. 真实 fixture：旧判据命中不了，新判据能
# ---------------------------------------------------------------------------
def test_fixture_has_no_chinese_date_format():
    """确认这份真实 dump 里**没有** `N月N日`——旧判据必死。"""
    s = io.open(_FIXTURE, encoding="utf-8").read()
    cn = [n.text for n in nodes(s)
          if re.fullmatch(r"\d{1,2}月\d{1,2}日", (n.text or "").strip())]
    assert cn == [], cn


def test_fixture_has_dash_date_format():
    s = io.open(_FIXTURE, encoding="utf-8").read()
    dash = [n.text for n in nodes(s)
            if re.fullmatch(r"\d{1,2}-\d{1,2}", (n.text or "").strip())]
    assert dash, "fixture 里应该有横线格式日期，否则本用例失去锚点"


def test_dash_format_is_recognised_as_trigger(monkeypatch):
    """横线格式必须能被识别成日期入口（修前它是"找不到"）。"""
    s = io.open(_FIXTURE, encoding="utf-8").read()

    class Dev:
        def __init__(self):
            self.taps = 0

        def dump(self):
            return s

        def tap(self, *a):
            self.taps += 1
            return True
    d = Dev()
    ok, detail = open_date_dialog(d)
    # 不再报"找不到日期入口"；点到了入口就算过了这一关
    assert "找不到日期入口" not in detail, detail
    assert d.taps == 1, detail


# ---------------------------------------------------------------------------
# 2. 中文格式仍然优先（它才是"打开日历"的那一行）
# ---------------------------------------------------------------------------
def test_chinese_format_preferred(monkeypatch):
    xml = ('<node text="10-29" bounds="[10,10][80,40]" />'
           '<node text="11月16日" bounds="[200,10][300,40]" />')
    tapped = {}

    class Dev:
        def dump(self):
            return xml

        def tap(self, x, y):
            tapped["xy"] = (x, y)
            return True
    open_date_dialog(Dev())
    # 应该点中文那一行（cx≈250），不是横线那一格（cx≈45）
    assert tapped["xy"][0] > 150, tapped


# ---------------------------------------------------------------------------
# 3. 两种都没有：如实报（并说清判据）
# ---------------------------------------------------------------------------
def test_neither_format_reports_clearly():
    xml = '<node text="机票查询" bounds="[10,10][80,40]" />'

    class Dev:
        def dump(self):
            return xml

        def tap(self, *a):
            raise AssertionError("不该点")
    ok, detail = open_date_dialog(Dev())
    assert ok is False
    assert "找不到日期入口" in detail
    # 文案要写出认哪些格式，便于下次一眼看出是判据问题
    assert "N月N日" in detail or "N-N" in detail


# ---------------------------------------------------------------------------
# 4. 已打开就不再点
# ---------------------------------------------------------------------------
def test_already_open_returns_ok():
    xml = '<node text="Search_Calendar_Dialog_Title" bounds="[10,10][80,40]" />'

    class Dev:
        def dump(self):
            return xml

        def tap(self, *a):
            raise AssertionError("不该点")
    ok, detail = open_date_dialog(Dev())
    assert ok is True and "已打开" in detail


# ---------------------------------------------------------------------------
# 5. 空页面（uiautomator 未就绪）如实报
# ---------------------------------------------------------------------------
def test_empty_dump_reports_not_ready():
    class Dev:
        def dump(self):
            return ""

        def tap(self, *a):
            raise AssertionError("不该点")
    ok, detail = open_date_dialog(Dev())
    assert ok is False and "未取到页面" in detail
