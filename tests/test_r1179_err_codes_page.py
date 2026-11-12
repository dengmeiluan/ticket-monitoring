# -*- coding: utf-8 -*-
"""r1179：错误码表要上页面（不是只躺在 core/err_codes.py 里）。

断言三件事：
1. 两个只读端点存在（`/api/err-codes`、`/api/err-codes/explain`）；
2. 页面有容器 + 折叠按钮 + 加载函数，且**不在页面里另写一份码表**；
3. 负控：容器默认收起（密度契约：不许默认铺一张表）。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_endpoints_exist():
    assert '"/api/err-codes"' in WEBUI
    assert '"/api/err-codes/explain"' in WEBUI
    assert "from core import err_codes as _ec" in WEBUI


def test_page_container_and_loader():
    assert 'id="errCodeCard"' in WEBUI
    assert 'id="errCodeBody"' in WEBUI
    assert "function loadErrCodes(" in WEBUI
    assert "function toggleErrCodes(" in WEBUI
    assert "onclick=\"toggleErrCodes()\"" in WEBUI


def test_page_does_not_duplicate_the_table():
    """负控：页面里不许出现码 → 说法的第二份拷贝。"""
    assert "环境存在风险" not in WEBUI, "webui.py 里又写了一份 50003 的解释"
    assert "阿里 NC 滑块" not in WEBUI, "webui.py 里又写了一份 x2VW8 的解释"


def test_default_collapsed():
    """密度契约：默认收起，一行摘要即可。"""
    i = WEBUI.find('id="errCodeBody"')
    seg = WEBUI[i:i + 80]
    assert 'display:none' in seg, "错误码表默认必须是收起的：%r" % seg
