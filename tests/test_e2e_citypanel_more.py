# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r320_citypanel.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r320_citypanel.py ----

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






def _open_cfg(page):
    """进配置视图、展开用户卡分区（城市输入在折叠分区内——先走真实
    展开路径）。CFG 属配置视图懒加载：先 switchView 触发拉取。"""
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.evaluate("showCfgPanel('users')")
    page.wait_for_function(
        "document.querySelector('#panel-users')"
        " && document.querySelector('#panel-users').style.display!=='none'")
    page.evaluate("expandFolds()")
    page.wait_for_timeout(400)


def _city_inputs(page):
    return page.locator(
        '#cfgview input[onclick="cityPanelOpen(this)"]')










def test_source_pins_datalist_retired():
    """源码钉：cityx 下发两处 + _cityx 单源 + datalist（citydl）
    零残留 + 保焦点/Esc capture 交互在案。"""
    src = webui_full_src()
    assert src.count('"cityx": _cityx()') == 2
    assert "def _cityx():" in src
    assert "citydl" not in src, "native datalist 残留（289 城改自定义面板）"
    assert "e.target.closest('.cp-city,.cp-x,.cp-abc'))e.preventDefault()" in src
    assert "cityPanelPick" in src and "cityPanelFilter" in src


