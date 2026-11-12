# -*- coding: utf-8 -*-
"""r968：登录判据必须三态，且必须**先确认看的是携程**。

## 事故一：两态判据把"看不见"报成"没登录"

用户报"携程登录了，问题不变"，我连跑三次
`scripts/ctrip_login.py --check`，得到 **一次"已登录" + 三次"未登录"**，
而这期间设备状态没有任何变化。根因是旧判据两态收尾：

```python
if "登录携程" in xml or "登录/注册" in xml: return False
return ("全部订单" in xml) or ("我的钱包" in xml)   # 看不见也算 False
```

第二行同时承担了"真的未登录"和"**页面根本没认出来**"。
`未登录` 这个字会直接把人推去做一次**重新登录**，而"减少重登次数"
正是本项目的目标之一 —— 误报一个需要人工动作的结论，比诚实说"不知道"坏得多。
所以引入第三种答案 `unknown`，并且 `--check` 不许把它印成"未登录"。

## 事故二：判据根本没保证看的是携程（更致命）

实测 dump 只有两个文本节点 `智行 / 10` —— 那时**前台是智行**，
携程进程在后台（`pidof` 有 pid ≠ 在前台）。
旧代码就在智行的页面上点「我的」，然后给出"携程未登录"的结论。
于是读数跟着"上一个渠道把哪个 App 留在了前台"变化。

这与 `crawlers/app_base._ensure_own_app`（2026-11-02 为解决
"智行照着去哪儿首页解析"而加）是同一个病，所以复用同一手法：
`current_activity()` 比对包名 → 不对就 `app_start()` → 再校验。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r968_three_state_login_check.py -q
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "tm_ctrip_login", os.path.join(ROOT, "scripts", "ctrip_login.py"))
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)

HOME = ('<hierarchy><node text="智行" resource-id="x:id/t" '
        'class="android.widget.TextView" bounds="[0,0][120,60]"/></hierarchy>')
MINE_TAB = ('<node text="我的" resource-id="x:id/tab" '
            'class="android.widget.TextView" bounds="[0,2740][126,2800]"/>')
ORDERS = ('<node text="全部订单" resource-id="x:id/o" '
          'class="android.widget.TextView" bounds="[0,300][200,360]"/>')
LOGIN_ENTRY = ('<node text="登录携程" resource-id="x:id/l" '
               'class="android.widget.TextView" bounds="[0,600][200,660]"/>')
UNKNOWN_PAGE = ('<hierarchy><node text="携程旅行" '
                'class="android.widget.TextView" bounds="[0,0][10,10]"/>'
                '</hierarchy>')


class _Dev:
    """模拟真实时序：**切前台之前** dump 到别人家的页面，切之后才是携程的。

    第一版替身错在这里：`app_start` 之后仍返回切换前的页面，
    于是"切成功却仍判 unknown"——测出来的是替身的缺陷，不是代码的。
    """

    def __init__(self, before, after, front="cn.suanya.zhixing",
                 start_ok=True):
        self.before = list(before)
        self.after = list(after)
        self.screens = self.before
        self.i = 0
        self.front = front
        self.start_ok = start_ok
        self.started = []

    def dump(self, *a, **k):
        s = self.screens[min(self.i, len(self.screens) - 1)]
        self.i += 1
        return s

    def tap(self, *a, **k):
        return True

    def current_activity(self, *a, **k):
        return self.front

    def app_start(self, pkg, *a, **k):
        self.started.append(pkg)
        if not self.start_ok:
            return False
        self.front = pkg
        self.screens = self.after      # 切成功后页面换成携程自己的
        self.i = 0
        return True

    def shell(self, *a, **k):
        return ""


def _no_wait(monkeypatch):
    """去掉 `_ensure_front` 的固定等待：测试不该真睡 3 秒。"""
    monkeypatch.setattr(cl.time, "sleep", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# 1. 三态：看不见 ≠ 没登录
# ---------------------------------------------------------------------------
def test_splash_screen_is_unknown_not_logged_out(monkeypatch):
    _no_wait(monkeypatch)
    assert cl.login_state(_Dev([HOME], [UNKNOWN_PAGE])) == "unknown", \
        "看不见的页面又被报成未登录"


def test_empty_dump_is_unknown(monkeypatch):
    _no_wait(monkeypatch)
    assert cl.login_state(_Dev([HOME], [""])) == "unknown"


def test_login_entry_is_out(monkeypatch):
    _no_wait(monkeypatch)
    assert cl.login_state(_Dev([HOME], [MINE_TAB + LOGIN_ENTRY])) == "out"


def test_account_page_is_in(monkeypatch):
    _no_wait(monkeypatch)
    assert cl.login_state(_Dev([HOME], [MINE_TAB, ORDERS])) == "in"


def test_login_entry_wins_over_account_marks(monkeypatch):
    """两个方向同时出现（"登录后查看全部订单"这类文案）时，以登录入口为准。"""
    _no_wait(monkeypatch)
    assert cl.login_state(_Dev([HOME], [LOGIN_ENTRY + ORDERS])) == "out"


# ---------------------------------------------------------------------------
# 2. 前台：判之前必须确认看的是携程
# ---------------------------------------------------------------------------
def test_foreign_foreground_is_switched_before_judging(monkeypatch):
    """前台是智行时先切到携程，再按**携程**页面判（本次事故的复现与修复）。"""
    _no_wait(monkeypatch)
    d = _Dev([HOME], [MINE_TAB, ORDERS], front="cn.suanya.zhixing")
    assert cl.login_state(d) == "in", "没切前台就判，或切了仍按旧页面判"
    assert d.started == [cl.PKG], d.started


def test_switch_failure_is_unknown_not_a_verdict(monkeypatch):
    """切不到前台 ⇒ unknown。**不许**拿别人家页面给携程下结论。"""
    _no_wait(monkeypatch)
    d = _Dev([HOME], [ORDERS], front="cn.suanya.zhixing", start_ok=False)
    assert cl.login_state(d) == "unknown"


def test_switch_success_but_unrecognized_page_is_unknown(monkeypatch):
    """切成功但页面认不出来（闪屏/广告/风控页）⇒ unknown。"""
    _no_wait(monkeypatch)
    assert cl.login_state(_Dev([HOME], [UNKNOWN_PAGE])) == "unknown"


def test_front_pkg_returns_package_only():
    d = _Dev([HOME], [HOME], front=cl.PKG + "/.MainActivity")
    assert cl._front_pkg(d) == cl.PKG


def test_no_foreground_info_does_not_claim_success(monkeypatch):
    """读不到包名时不许谎报"已在携程"（宁可 unknown）。"""
    _no_wait(monkeypatch)

    class _Blind(_Dev):
        def current_activity(self, *a, **k):
            return ""

    d = _Blind([HOME], [ORDERS])
    # 起始前台读不到 → 会尝试 app_start → 成功 → 复查时仍读不到 → False
    assert cl.login_state(d) == "unknown", "读不到前台却给出了结论"


# ---------------------------------------------------------------------------
# 3. 兼容接口与文案
# ---------------------------------------------------------------------------
def test_is_logged_in_returns_none_when_unsure(monkeypatch):
    _no_wait(monkeypatch)
    assert cl.is_logged_in(_Dev([HOME], [UNKNOWN_PAGE])) is None
    assert cl.is_logged_in(_Dev([HOME], [LOGIN_ENTRY])) is False
    assert cl.is_logged_in(_Dev([HOME], [ORDERS])) is True


def test_check_text_never_calls_unknown_not_logged_in():
    """`--check` 的未知文案里不许出现"未登录"——它是人工动作的触发器。"""
    src = open(os.path.join(ROOT, "scripts", "ctrip_login.py"),
               encoding="utf-8").read()
    i = src.find("if args.check:")
    body = src[i:i + 700]
    assert "无法判定" in body, "unknown 要有独立文案"
    assert "不要据此重登" in body, "要显式挡住照着这句话去重登"
    m = re.search(r'"unknown":\s*"([^"]*(?:"[^"]*)*)"', body)
    assert m, "找不到 unknown 的文案"
    assert "未登录" not in m.group(1), \
        "unknown 文案里出现了未登录：会诱发多余的重登"
