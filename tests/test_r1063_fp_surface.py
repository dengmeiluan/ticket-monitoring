# -*- coding: utf-8 -*-
"""r1063 T26：指纹核账必须**看得见**（载荷 + 策略面板一行）。

后端算得再准，没有出口就是"只有开发者知道"。这一条守两件事：
  1. `/api/strategy` 载荷带 `fingerprint` 段（两档，各带 count/worst/text）；
  2. 策略面板顶部有一行，命中时带**最严重那条的修复建议**，0 处时显示"已清"。
"""
import io
import os

import webui

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_payload_carries_fingerprint_audit():
    pl = webui._strategy_payload()
    fp = pl.get("fingerprint")
    # r1063 T32：三段——桌面档 / 移动档 / App 机型池（PC 与 App 同表）
    assert isinstance(fp, list) and len(fp) == 3, fp
    names = [x["name"] for x in fp]
    assert names == ["桌面档", "移动档", "App 机型池"], names
    for x in fp:
        assert "count" in x and "text" in x
        assert x["count"] == 0, ("仓库默认档应该没有矛盾：%s" % x)
        assert "已知矛盾全清" in x["text"]


def test_panel_renders_fingerprint_line():
    assert "function stratFpHTML(){" in SRC
    assert "h+=stratFpHTML();" in SRC, "面板没挂这一行"
    seg = SRC[SRC.index("function stratFpHTML(){"):][:1000]
    # 0 处时也要有话说（"核过了、干净"本身是信息）
    assert "已知矛盾全清" in seg
    # 命中时带修复建议
    assert "worst.fix" in seg or "worst.fix" in SRC
    assert "chip" in seg


def test_audit_failure_is_visible_not_silent():
    """核账跑不起来要进 `errors`，不许静默当成"没有矛盾"。"""
    assert 'out["errors"]["fingerprint"]' in SRC
