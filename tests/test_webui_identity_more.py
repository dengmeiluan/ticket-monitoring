# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_fp_surface.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import webui


# ---- merged from tests/test_r1063_fp_surface.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


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
