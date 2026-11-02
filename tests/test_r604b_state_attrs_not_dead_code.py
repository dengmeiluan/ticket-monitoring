# -*- coding: utf-8 -*-
"""r604b：`_State` 的类属性不能被写进函数体（不可达），否则整条链路静默失效。

实测（2026-10-29 门禁）：`webui._State` 上 `login_sessions` / `login_errors` /
`login_saved_cb` / `login_pending` 四个属性全部缺失，13 条 `test_channel_status`
在 setup 阶段就 `AttributeError`。查下去是合并时把这四行落在了
`_app_login_ctx()` 的 `return {...}` **之后**——函数体里的 `return` 之后是死代码，
类属性从未被定义。

后果不是「报错」，而是**静默失效**：
  - `login_sessions` 缺失 → 网页登录进行中标记不存在 → 重复点登录不会被拦；
  - `login_pending` 缺失 → 保存后的验证窗口不存在 → 刚登完就被建议重登；
  - `login_errors` 缺失 → 保存失败原因不落账；
  - `login_saved_cb` 缺失 → 登录后不清采集器缓存，新 cookie 不生效。

这类缺陷静态读代码很难发现（四行看起来就在「类里」附近），只有
`hasattr(_State, ...)` 才抓得住。
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NEEDED = ("login_sessions", "login_errors", "login_saved_cb",
          "login_pending", "app_login")


def test_state_actually_owns_login_attributes():
    """真 import 后 check——不是查源码里出现过这几个名字。"""
    sys.path.insert(0, ROOT)
    w = importlib.import_module("webui")
    missing = [k for k in NEEDED if not hasattr(w._State, k)]
    assert not missing, (
        "webui._State 缺少这些属性（多半被写进了函数体成为死代码）：%s"
        % missing)


def test_login_sessions_is_mutable_and_per_process():
    """类属性必须是可变 dict，且各属性互不共享同一个对象。"""
    sys.path.insert(0, ROOT)
    import importlib
    w = importlib.import_module("webui")
    a = w._State.login_sessions
    b = w._State.login_pending
    assert isinstance(a, dict) and isinstance(b, dict)
    assert a is not b, "login_sessions 与 login_pending 指向同一对象"


def test_no_assignment_after_return_in_login_ctx():
    """`_app_login_ctx` 的 return 之后不得再有赋值（死代码）。

    这条守的是**成因**：即便将来把属性补回类体，只要还能往 return 后面
    追加代码，同一种错就会再犯一次。
    """
    import io
    import re
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                  newline="").read()
    i = src.index("def _app_login_ctx()")
    # 函数体到下一个顶格 def/class 为止
    j = len(src)
    for m in re.finditer(r"^(?:def |class )", src[i + 10:], re.M):
        j = i + 10 + m.start()
        break
    body = src[i:j]
    lines = body.splitlines()
    ret_at = None
    for n, ln in enumerate(lines):
        if ln.startswith("    return "):
            ret_at = n
            break
    assert ret_at is not None, "_app_login_ctx 没有顶层 return"
    # return 可能是多行字典：按括号配平跳过续行，否则会把 return 的
    # 后半段当成「return 之后的代码」（本门禁第一版就这么假红过一次）
    depth = lines[ret_at].count("{") - lines[ret_at].count("}")
    n = ret_at + 1
    while depth > 0 and n < len(lines):
        depth += lines[n].count("{") - lines[n].count("}")
        n += 1
    after = [ln for ln in lines[n:] if ln.strip()
             and not ln.strip().startswith("#")]
    assert not after, (
        "return 之后还有代码（不可达，写了也不生效）：%s" % after[:3])
