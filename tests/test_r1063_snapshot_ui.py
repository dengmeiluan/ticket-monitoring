# -*- coding: utf-8 -*-
"""r1063 T38：配置页的「策略快照」按钮（导出 / 导入并预览差异）。

两条硬约束：
1. **导入不新开写入口**——值只写进 `GLB`（面板本来就在编辑的脏状态），
   落盘仍由用户点「保存配置」走 `POST /api/config`；
2. **导入前先算差异并让人看一眼**，不静默覆盖。
"""
import io
import os

SRC = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()


def _fn(name):
    i = SRC.index("function %s(" % name)
    j = SRC.index("\nfunction ", i + 10)
    return SRC[i:j]


def test_toolbar_has_both_buttons_and_no_new_visual():
    assert "function stratSnapHTML(){" in SRC
    seg = _fn("stratSnapHTML")
    assert "导出配置" in seg and "导入配置" in seg
    assert 'class="btn2"' in seg            # 复用既有按钮尺寸，不新起视觉
    assert 'type="file"' in seg


def test_export_uses_the_readonly_endpoint_and_downloads():
    seg = _fn("stratExportSnap")
    assert "/api/strategy/snapshot" in seg
    assert "Blob(" in seg and "download=" in seg


def test_import_writes_into_the_same_dirty_state_not_a_new_path():
    seg = _fn("stratImportSnap")
    # 只写 GLB（面板的脏状态）；**不出现任何 POST**，否则就是第三条写通路
    assert "GLB.strategy_values" in seg
    assert "GLB.strategy_overrides" in seg
    assert "fetch(" not in seg, "导入不该自己发写请求"
    assert "method:'POST'" not in seg


def test_import_previews_before_overwriting():
    seg = _fn("stratImportSnap")
    assert "confirm(" in seg, "没有差异预览就直接覆盖了"
    assert "→" in seg, "预览里要看到 before→after"


def test_import_refuses_unknown_pid_in_the_preview():
    seg = _fn("stratImportSnap")
    assert "未识别" in seg
    assert "点「保存配置」" in SRC or "保存配置" in seg


def test_toolbar_is_mounted_in_the_panel():
    assert "h+=stratSnapHTML();" in SRC
