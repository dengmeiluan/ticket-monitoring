# -*- coding: utf-8 -*-
"""r1186：弹窗不许"弹错渠道"——`LG_DUAL[plat]||LG_DUAL.fliggy` 的回落是病根。

现场（2026-11-10 13:0x 实测 `lgDualModalHTML('qunar')`）：
```
LG_DUAL 里只有 ['ctrip','fliggy','tongcheng','tuniu']   ← 没有 qunar
调 lgDualModalHTML('qunar') → 返回标题「飞猪双端登录」、lane 是 fliggy/fliggy_h5
```
也就是说：点去哪儿「双端登录」，弹出来的是**飞猪的弹窗**。用户之前反复报
"弹窗弹错渠道 / 样式和交互又变了"，这就是机械原因。

契约：表里没登记的渠道，必须**按后端 slots 现推** `plat` + `plat+"_h5"` 两条 lane，
不许回落到任何别的渠道。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_no_fallback_to_another_vendor():
    """负控：**代码里**不许再出现"回落到飞猪"（注释里说明历史病根是允许的）。"""
    import re

    code = re.sub(r"/\*.*?\*/", "", WEBUI, flags=re.S)
    assert "LG_DUAL[plat]||LG_DUAL.fliggy" not in code, (
        "弹窗仍在回落到飞猪：未登记渠道会弹错别人的窗口")
    assert "||LG_DUAL.fliggy" not in code


def test_fallback_derives_from_backend_slots():
    assert "function _lgDualFallback(" in WEBUI
    i = WEBUI.find("function _lgDualFallback(")
    seg = WEBUI[i:i + 900]
    assert "p+'_h5'" in seg, "兜底没有按 plat+_h5 推 H5 lane"
    assert "CHANNEL_STATE" in seg, "兜底没有读后端 slots（会退回写死）"


def test_modal_uses_fallback():
    i = WEBUI.find("function lgDualModalHTML(")
    seg = WEBUI[i:i + 200]
    assert "_lgDualFallback(plat)" in seg, "弹窗构造没有走兜底"


def test_five_vendors_will_all_get_a_modal():
    """5 家浏览器渠道都必须能开出自己的弹窗（其中 qunar 走兜底）。"""
    from core.channels import BROWSER_CHANNELS
    for plat in BROWSER_CHANNELS:
        assert plat in WEBUI, plat
    assert "qunar" in WEBUI
