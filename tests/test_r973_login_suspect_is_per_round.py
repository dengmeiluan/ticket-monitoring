# -*- coding: utf-8 -*-
"""r973：`login_suspect` 必须按轮清零——否则成功轮次会被记成登录失败。

现场（2026-11-05 生产日志，同一轮两行）：

```
00:42:14 [app_qunar] 抓取完成，得到 1 条记录
00:42:14 [app_qunar] 风控评分 48（slow）：间隔放大到 2.5×，本轮只跑快层
         （临期日期）；建议 登录墙（会话已失效）／登录连续失败 6 次（+30）
```

**取到数的那一轮被记成登录失败**，连击数 6→7→8 只涨不落。

根因链条：

1. 五个 App 渠道共 21 处 `login_suspect = True`，**0 处复位**
   （app_qunar 6 / app_zhixing 5 / app_tongcheng 6 / app_ctrip 3 / app_fliggy 1）；
2. `_round_signals()["login_wall"] = ("login" in statuses) or bool(self.login_suspect)`
   —— 粘住的 True 让每一轮都像"有登录墙"；
3. `_note_round_risk()` 里 `login_hit` 因此恒真 → `note_result(..., False,
   device_risk=True)`，**成功轮次不计入成功**；
4. 风险分升到 slow → 间隔 2.5×、只跑快层 → 爬取率被压死；
   而且登录连击数只涨不落，还会误导"该重登"（与"减少重登"的目标正面冲突）。

修法：`login_suspect` 是**本轮观测**，在 `safe_fetch()`（唯一入口）按轮清零，
判据只认本轮证据。浏览器渠道不动（它们用类属性且有成对 True/False 逻辑）。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r973_login_suspect_is_per_round.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import core.riskscore as riskscore  # noqa: E402
from crawlers.app_base import AppCrawler  # noqa: E402

_LOG = logging.getLogger("r973")


class _RecLedger:
    """登录账本替身：只记 `note_result` 的调用形态。"""

    def __init__(self):
        self.calls = []

    def note_result(self, plat, ok, device_risk=False, **kw):
        self.calls.append({"plat": plat, "ok": bool(ok),
                           "device_risk": bool(device_risk)})
        return {}

    def rec(self, plat):
        return {}

    def signals(self, plat):
        return {"login_fail_streak": 0}

    def wait_s(self, plat, now=None):
        return 0

    def should_rotate(self, plat):
        return False


class _Crawler(AppCrawler):
    name = "app_probe973"
    package = ""
    LOGIN_FORM_MARKS = ()

    def __init__(self, rows=None, notes=None, boom=False):
        super().__init__({}, _LOG)
        self._rows = rows or []
        self._notes = notes or []
        self._boom = boom
        self._rec_ledger = _RecLedger()

    # 只替换登录账本与打分，其余走生产逻辑
    def _ledger(self):
        return self._rec_ledger

    def fetch(self, from_city, to_city, dates, ret_date=""):
        for path, status in self._notes:
            self.path_note(path, status)
        if self._boom:
            raise RuntimeError("boom")
        return list(self._rows)


def _assess_stub(calm=True):
    def _go(*a, **k):
        return {"level": "calm" if calm else "slow", "score": 0,
                "reasons": [], "advice": {"text": ""}}
    return _go


# ---------------------------------------------------------------------------
# 1. 核心：做过登录墙、但这一轮成功了 → 必须记成功，不许记登录失败
# ---------------------------------------------------------------------------
def test_stale_suspect_does_not_turn_success_into_login_failure(monkeypatch):
    monkeypatch.setattr(riskscore, "assess", _assess_stub())
    c = _Crawler(rows=[object()], notes=[("app-calendar", "ok")])
    c.login_suspect = True          # 上一轮留下的"终身标记"
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    calls = c._rec_ledger.calls
    assert calls, "成功轮次完全没进登录账本"
    assert calls[-1]["ok"] is True, \
        "取到数的轮次被记成登录失败：%r" % (calls,)
    assert calls[-1]["device_risk"] is False


def test_login_wall_this_round_still_recorded_as_failure(monkeypatch):
    """清零不等于"忽略登录墙"：**本轮**真遇到登录墙，照实记失败。"""
    monkeypatch.setattr(riskscore, "assess", _assess_stub(calm=False))
    c = _Crawler(rows=[], notes=[("app-login", "login")])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    calls = c._rec_ledger.calls
    assert calls and calls[-1]["ok"] is False
    assert calls[-1]["device_risk"] is True


def test_suspect_is_reset_even_when_fetch_raises(monkeypatch):
    monkeypatch.setattr(riskscore, "assess", _assess_stub())
    c = _Crawler(rows=[], notes=[], boom=True)
    c.login_suspect = True
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    assert c.login_suspect is False, "异常轮次没清零，标记会继续粘住"


# ---------------------------------------------------------------------------
# 2. 判据只认本轮证据
# ---------------------------------------------------------------------------
def test_round_signals_ignore_stale_flag_after_reset(monkeypatch):
    monkeypatch.setattr(riskscore, "assess", _assess_stub())
    c = _Crawler(rows=[object()], notes=[("app-calendar", "ok")])
    c.login_suspect = True
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    assert c._round_signals()["login_wall"] is False, \
        "本轮没有任何 login 证据，却仍报登录墙"


def test_round_signals_detect_login_status_in_round():
    c = _Crawler()
    c.path_note("app-login", "login")
    assert c._round_signals()["login_wall"] is True


# ---------------------------------------------------------------------------
# 3. 结构约束：清零必须发生在唯一入口，且渠道里不该再出现"只置不清"
# ---------------------------------------------------------------------------
def test_reset_happens_in_safe_fetch():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    i = src.find("def safe_fetch(")
    head = src[i:i + 1400]
    assert "self.login_suspect = False" in head, \
        "safe_fetch 开头没有按轮清零 login_suspect"
