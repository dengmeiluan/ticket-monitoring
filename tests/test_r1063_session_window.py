# -*- coding: utf-8 -*-
"""r1063 T93：会话可用期——把"登录后能用一会儿"变成数字。

用户原话："飞猪登录了可以用一会儿，现在全被拦住了"。
这句话是判断"账号风控 vs 设备风控"的关键，但一直只有口头描述。

做法：在路径账的中央入口 `path_note()` 记**状态转变**：

* `ok` / `calendar` → 可用时刻；
* `login` / `blocked` / `captcha` / `face` → 失效时刻；
* 两者相邻即构成一个"可用窗口"，落到 `user_data/<渠道>/session_window.json`。

读数（CLI：`python -m core.session_window`）：

```
app_fliggy   上次可用 812 秒后被拦(login) | 样本 2 个窗口 平均 640s | 恢复 1 次 平均 900s
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import session_window as SW  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _root():
    import tempfile
    return tempfile.mkdtemp()


def test_ok_then_block_makes_a_window():
    r = _root()
    SW.note(r, "p", "ok", now=1000.0)
    SW.note(r, "p", "login", now=1812.0)
    s = SW.summary(r, "p")
    assert s["last_window_s"] == 812.0, s
    assert s["last_block_kind"] == "login"
    assert "812" in s["last_window_text"]


def test_calendar_counts_as_usable():
    r = _root()
    SW.note(r, "p", "calendar", now=100.0)
    SW.note(r, "p", "captcha", now=160.0)
    assert SW.summary(r, "p")["last_window_s"] == 60.0


def test_block_without_prior_ok_is_ignored():
    """先被拦（从没可用过）不该编出一个窗口。"""
    r = _root()
    SW.note(r, "p", "login", now=200.0)
    s = SW.summary(r, "p")
    assert s["last_window_s"] == 0 and s["windows"] == 0


def test_recovery_interval_is_recorded():
    r = _root()
    SW.note(r, "p", "login", now=100.0)
    SW.note(r, "p", "ok", now=1900.0)
    s = SW.summary(r, "p")
    assert s["recover_s"] == 1 and s["avg_recover_s"] == 1800.0, s


def test_avg_and_cap():
    r = _root()
    for i in range(30):
        SW.note(r, "p", "ok", now=1000.0 + i * 100)
        SW.note(r, "p", "login", now=1050.0 + i * 100)
    s = SW.summary(r, "p")
    assert s["windows"] <= SW.KEEP
    assert s["avg_window_s"] == 50.0, s


def test_empty_status_is_noop_and_never_raises():
    r = _root()
    assert SW.note(r, "p", "") == {}
    assert SW.summary(r, "p")["windows"] == 0
    assert SW.summary(_root(), "nope")["last_window_s"] == 0


def test_wired_into_both_path_notes():
    for name in ("app_base.py", "base.py"):
        src = io.open(os.path.join(ROOT, "crawlers", name),
                      encoding="utf-8").read()
        assert "session_window" in src, name
