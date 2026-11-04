# -*- coding: utf-8 -*-
"""r934：弹层没关就放弃——失败本可恢复，却白跑整条航线。

真实日志（2026-11-03~04，同一形态 **15 次**）：

    [nav] 已切到国内档
    [warn] 点了日期但弹层没关
    [app_zhixing] 明细前置选日期失败：点了日期但弹层没关
    [app_zhixing] 明细页没解析出带价航班：2027-02-14

机制：App 里"点日历格子 → 弹层应自己关"，但落点偶尔偏到弹层头部
（`app_zhixing_nav` 的注释早就写了这个现场），于是日历不关。原代码：

```python
if "Search_Calendar_Dialog" in left:
    return False, "点了日期但弹层没关"     # ← 直接放弃
```

一次脏点击 = 整条航线没明细。而这类失败**是可恢复的**：按一次 BACK
关掉弹层，再点一次格子就成了。

`app_qunar` 的日期选择有**同一族**写法（`return False  # 弹层没关 = 没选上`），
所以修法收成一个共享函数 `app_base.dismiss_until_gone()`，两处都用它。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r934_dismiss_retry.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_base import dismiss_until_gone  # noqa: E402


class FakeDev:
    """``frames`` 逐帧返回 dump；记录 BACK 次数。"""

    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.backs = 0
        self.dumps = 0

    def dump(self):
        self.dumps += 1
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def keyevent(self, code):
        self.backs += 1
        return True


DIALOG = '<node text="Search_Calendar_Dialog" />'
HOME = '<node text="机票查询" />'


# ---------------------------------------------------------------------------
# 1. 已经关掉：不该按 BACK
# ---------------------------------------------------------------------------
def test_already_gone_does_not_press_back():
    d = FakeDev([HOME])
    gone, xml = dismiss_until_gone(d, "Search_Calendar_Dialog")
    assert gone is True
    assert d.backs == 0
    assert "机票查询" in xml


# ---------------------------------------------------------------------------
# 2. 一次 BACK 就关掉（最常见）
# ---------------------------------------------------------------------------
def test_one_back_closes_dialog():
    d = FakeDev([DIALOG, HOME])
    gone, xml = dismiss_until_gone(d, "Search_Calendar_Dialog", tries=2)
    assert gone is True
    assert d.backs == 1


# ---------------------------------------------------------------------------
# 3. 按了几次都关不掉：如实返回 False（不假装成功）
# ---------------------------------------------------------------------------
def test_still_open_returns_false():
    d = FakeDev([DIALOG])
    gone, _ = dismiss_until_gone(d, "Search_Calendar_Dialog", tries=2)
    assert gone is False
    assert d.backs == 2


# ---------------------------------------------------------------------------
# 4. 设备异常也不能抛
# ---------------------------------------------------------------------------
def test_keyevent_failure_is_fail_soft():
    class Bad(FakeDev):
        def keyevent(self, code):
            raise RuntimeError("device gone")
    d = Bad([DIALOG])
    gone, _ = dismiss_until_gone(d, "Search_Calendar_Dialog")
    assert gone is False


def test_dump_failure_is_fail_soft():
    class Bad(FakeDev):
        def dump(self):
            raise RuntimeError("uiautomator dead")
    d = Bad([DIALOG])
    try:
        gone, _ = dismiss_until_gone(d, "Search_Calendar_Dialog")
    except Exception as e:                    # noqa: BLE001
        raise AssertionError("不该抛：%s" % e)
    assert gone is False


# ---------------------------------------------------------------------------
# 5. 两处调用点都在（源码钉）
# ---------------------------------------------------------------------------
def test_zhixing_retries_instead_of_giving_up():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    # 只钉**不变量**：弹层没关不许直接放弃，必须 BACK + 重试。
    # r938 之后重试的正确形态是「重新打开弹层再点」（BACK 已把弹层关掉，
    # 就地找格子注定失败）；具体形态由 test_r938_date_retry_reopen.py 钉住。
    assert "dismiss_until_gone" in src, "智行仍直接放弃，没有 BACK 重试"
    assert ("open_date_dialog(dev)" in src
            or "重试一次点击" in src), "没有可用的重试路径"
    assert ("重开弹层失败" in src or "重试后仍开" in src), \
        "重试后仍失败没有独立证据"


def test_qunar_retries_instead_of_giving_up():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert "dismiss_until_gone" in src, "qunar 日期弹层仍直接放弃"
