# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1734_state_vocabulary.py
- tests/test_r604b_state_attrs_not_dead_code.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import importlib
import io
import os
import sys


# ---- merged from tests/test_r1734_state_vocabulary.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 六个状态 → 代码里必须能找到的实现锚点
ANCHORS = {
    "停手": ("halt", "停手"),
    "停服": ("retired", "网页已停服"),
    "未在清单": ("disabled", "未在清单"),
    "冷却中": ("cooldown", "冷却中"),
    "夜间静默": ("quiet", "夜间静默中"),
    "零出数": ("no_ok", "全失败"),
}


def _doc():
    return io.open(os.path.join(ROOT, "docs", "HEALTH_STATES.md"),
                   encoding="utf-8").read()


def _webui():
    return webui_full_src()


def test_doc_lists_all_states():
    doc = _doc()
    for name in ANCHORS:
        assert name in doc, "文档漏了状态：%s" % name


def test_code_implements_each_state():
    w = _webui()
    missing = []
    for name, (code_kw, ui_kw) in ANCHORS.items():
        if code_kw not in w or ui_kw not in w:
            missing.append("%s（需要 %r / %r）" % (name, code_kw, ui_kw))
    assert not missing, "文档写了但代码没有：%s" % missing


def test_doc_rules_present():
    doc = _doc()
    for rule in ("状态先于动作", "建议必须有按钮", "口径不许冒充"):
        assert rule in doc, "文档缺规矩：%s" % rule


# ---- merged from tests/test_r604b_state_attrs_not_dead_code.py ----

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
    src = webui_full_src()
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
