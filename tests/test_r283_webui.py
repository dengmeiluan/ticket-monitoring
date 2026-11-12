# -*- coding: utf-8 -*-
"""r283 WebUI：≤760 明细页档位图例触屏可见（审计 P3）。

宽档明细页价格档位图例常驻（.tabs>b.muted），≤760 两带隐藏后
语义并入 #fltBtn title——触屏读不到 title，档位色成纯装饰。
修法：筛选抽屉（#fltwrap）内渠道片行后补一行图例（.flgrow 行包
#fltlegend；r283v 自抽屉尾提位=触屏主流档首屏可达，行级开关宽档
零占位），基础 display:none（宽档已有常驻图例不重复），≤760 两带
媒体块内 .flgrow{display:flex} 放行（触屏用户点开筛选即得色义解码）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r283_webui.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()


def test_fltlegend_element_in_drawer():
    """抽屉内图例元素在场（r352 移到预设行后，窄屏更早可达），词面与
    宽档常驻图例同语言（四方同语言律）。"""
    m = re.search(r'<div class="frow flgrow"><span class="muted" '
                  r'id="fltlegend">([^<]+)</span>', _SRC)
    assert m, "抽屉图例补位行不在场"
    assert "深绿=真达标" in m.group(1) and "描绿=行情破线" in m.group(1) \
        and "琥珀=擦边" in m.group(1), m.group(1)


def test_fltlegend_hidden_by_default():
    """补位行基础 display:none（行级开关）：宽档已有 .tabs 常驻图例，
    抽屉图例行不重复显示、不占 .frow+.frow 空缝。"""
    assert re.search(r'\.flgrow\{display:none\}', _SRC), \
        "缺补位行基础隐藏规则——宽档将双份图例/空行缝"


def test_fltlegend_visible_in_narrow_bands():
    """≤760 两带媒体块内各有一条行级放行规则（图例隐藏的带=触屏
    真空带，抽屉补位与隐藏规则同块同域）。"""
    n = len(re.findall(r'\.flgrow\{display:flex\}', _SRC))
    assert n == 2, f"窄带放行规则 {n} 条（预期 2：≤760 与 ≤540 两带）"
