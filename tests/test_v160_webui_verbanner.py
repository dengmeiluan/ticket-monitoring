# -*- coding: utf-8 -*-
"""回归：版本失配刷新横幅（__PAGEVER__ 服务端注入 + load
轮询比对 state.version）——根治跨重启旧标签页长期跑旧代码：今日用户
实报「布局抖动/点击不通」实为重启窗口期一直开着的标签页跑着中间代际
代码（现行代码 12 档窗宽矩阵零振荡），no-cache 管不住已打开的页面。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v160_webui_verbanner.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_page_html_injects_version():
    import webui
    html = webui._page_html("1.5.60")
    assert "const PGVER='1.5.60'" in html
    assert "__PAGEVER__" not in html
    # 空版本（极端）注入空串：守卫要求 PGVER 非空才亮，静默不误报
    assert "const PGVER=''" in webui._page_html("")


def test_banner_elements_and_guard_pins():
    import webui
    src = webui.PAGE
    assert 'id="verbar"' in src                # 横幅条
    assert 'id="verTxt"' in src                # 版本号槽
    assert "s.version!==PGVER" in src          # 失配守卫字面
    assert "location.reload()" in src          # 刷新动线
    # 双主题样式在位
    assert ".verbar{" in src
    assert 'html[data-theme="dark"] .verbar{' in src


def test_demo_build_bakes_matching_generation():
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(os.path.dirname(here),
                            "docs", "demo_build.py"),
               encoding="utf-8").read()
    # 烘焙站必须同样注入代际（直用 PAGE 原串会令牌泄漏+横幅误报）
    assert "_page_html(" in src
    assert "webui.PAGE" not in src
