# -*- coding: utf-8 -*-
"""r288 WebUI 批（_scratch/r288_webui_audit.md 落地）：

- R288-1 switchView cfg→mon 回程批横滚暗示漏重判：xhint 重判清单
  四批同族（showMonTab details/renderHealth/resize/switchView 回程），
  唯回程批缺 .tw——窄窗进配置停留后回监控且明细 tab 为持久 tab 时，
  .tw 可滚但右缘渐隐提示缺失（窗口期到下次 resize/数据变化）。
- R288-2 demo 冷失败态 #hsrcNote 静态默认词失真：静态 HTML 默认
  「解析自 monitor.log」，render 未跑（fetch 失败）时与演示横幅同屏
  矛盾——静态默认留空，render 成功路径回设（r236 语义担保不丢）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r288_webui.py -q
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_switchview_back_batch_rejudges_tw():
    """R288-1：cfg→mon 回程批的 xhint 重判清单必须含 .tw（与其余
    三批同族齐备；窗口锚=chart() 早退补拍行，块内定位不靠字符数）。"""
    src = _src()
    i = src.find("if(MONTAB==='trend')chart();")
    assert i > 0, "回程批锚点易位"
    seg = src[i:i + 400]
    m = re.search(r"document\.querySelectorAll\('([^']+)'\)", seg)
    assert m, "回程批重判选择器未找到"
    sels = m.group(1).split(",")
    assert ".tw" in sels, f"cfg→mon 回程批缺 .tw 重判: {m.group(1)}"


def test_hsrcnote_static_default_neutral():
    """R288-2：静态默认词面留空（冷失败态不显生产词面）；render
    成功路径回设在案（r236 P3-1a 语义担保随行）。"""
    src = _src()
    assert '<span id="hsrcNote"></span>' in src, \
        "hsrcNote 静态默认词面非空（冷失败态失真）"
    assert "s.demo?'演示合成数据':'解析自 monitor.log'" in src, \
        "render 成功路径回设缺失"
