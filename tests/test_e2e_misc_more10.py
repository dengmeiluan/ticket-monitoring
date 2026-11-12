# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r324_monsync.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r324_monsync.py ----

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False








def test_source_pins_monsync():
    """源码钉：F3 守卫前移、F4 签名失效、F2 启动深链消费正面锚。"""
    src = webui_full_src()
    pi = src.find("async function pulse(")
    assert pi >= 0, "pulse 应在案"
    pbody = src[pi:pi + 800]
    guard = "if(!(S&&S.users&&S.users.length))return;"
    assert guard in pbody and pbody.index(guard) < pbody.index("PU=t"), (
        "pulse 空守卫应先于签名记账（F3）")
    ri = src.find("console.error('render:',e)")
    assert ri >= 0, "render 异常拍应在案"
    assert "LASTTXT=''" in src[ri:ri + 220], (
        "render 异常分支应失效签名（F4：自愈提前到下一拍）")
    assert "深链用户段恢复" in src and "U=Math.min(_un,99)" in src, (
        "启动深链消费正面锚（F2 撤案防重复发现）")
