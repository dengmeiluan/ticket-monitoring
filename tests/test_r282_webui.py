# -*- coding: utf-8 -*-
"""r282 WebUI 两案源码钉：搜索态手风琴三同步 + OPEN_USER 持久化。

案1 搜索态折叠用户卡 aria/chev 分裂：容器壳扫按命中可见性强展折叠卡
body，但 expandFolds 不含 .uhead2——头报收起、内容却显示。修法两段：
expandFolds 纳入 uhead2（_setFold 单源同步 aria/chev/tabindex）+
cfgSearchClear 回写源从 aria 换 OPEN_USER（搜索态把 aria 全改 true 后
aria 不再是可靠回写源，按它回写=清空后全卡展开）。
案3 OPEN_USER 持久化：全部写点收 setOpenUser 单源（localStorage 槽
jpcfguseropen，与折叠态 jpcfgfold 同惯例），buildForm 对槽值越界钳回。

行为钉在 docs/uitest.py「r282 WebUI 两案」段（红阶段两颗真缺陷钉在
修复前实红，即为抓 bug 能力实证）。本文件锁源码结构防退化。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r282_webui.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
                encoding="utf-8").read()


def _fn_body(src, name):
    """函数声明起到下一个顶层 function 为止的切片（块级语义，非字符窗）。"""
    m = re.search(r"function %s\(" % name, src)
    assert m, "function %s 不在场" % name
    nxt = re.search(r"\nfunction ", src[m.end():])
    end = m.end() + nxt.start() if nxt else len(src)
    return src[m.start():end]


def test_expand_folds_covers_user_head():
    body = _fn_body(_src(), "expandFolds")
    # 实效档：用户卡头纳入搜索态临时全开（显式单 body 形态）
    assert "#cfgform .uhead2" in body
    assert "_setFold(h,[b],false)" in body


def test_search_clear_rewrites_by_open_user_not_aria():
    src = _src()
    body = _fn_body(src, "cfgSearchClear")
    # 实效档：手风琴还原按 OPEN_USER 权威逐卡回写（b 缺守卫在位）
    assert "i!==OPEN_USER" in body
    assert "_setFold(h,[b],i!==OPEN_USER)" in body
    # 禁复活：旧形态（按已被搜索态污染的 aria 回写）在清空路径零残留
    assert "getAttribute('aria-expanded')==='true'?'':'none'" not in body


def test_open_user_writes_routed_through_single_setter():
    src = _src()
    # 直接赋值形态仅存四处合法点：let 声明 / 启动读槽恢复 /
    # setOpenUser 函数体 / buildForm 越界钳回——其余写点必须走
    # setOpenUser（localStorage 槽随写点同步）。负向先行排除
    # OPEN_USER=== 比较形态（其子串含 "OPEN_USER="）
    assert len(re.findall(r"OPEN_USER=(?!=)", src)) == 4
    for caller in ("setOpenUser(willOpen?u:-1)",
                   "setOpenUser(CFG.length)",
                   "setOpenUser(-1)", "setOpenUser(0)"):
        assert caller in src, caller
    # 持久化槽与折叠态槽同惯例（try/catch 收口）
    assert "jpcfguseropen" in src


def test_build_form_clamps_restored_slot():
    body = _fn_body(_src(), "buildForm")
    # 槽值恢复越界钳回（删用户/导入后 OPEN_USER 越界=全收假象）
    assert "if(OPEN_USER>=CFG.length)OPEN_USER=CFG.length-1;" in body
