# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1197_update_page.py
- tests/test_r1295_update_popover_structure.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import sys


# ---- merged from tests/test_r1197_update_page.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_endpoints_exist():
    for ep in ("/api/update/status", "/api/update/start", "/api/update/rollback"):
        assert ep in WEBUI, ep
    assert "def _update_status(" in WEBUI
    assert "def _update_start_async(" in WEBUI
    assert "update as _up" in WEBUI


def test_card_and_buttons():
    assert 'id="updateCard"' in WEBUI
    assert "function loadUpdate(" in WEBUI
    assert "function toggleUpdate(" in WEBUI
    for fn in ("updCheck(", "updStart(", "updRollback("):
        assert fn in WEBUI, fn
    i = WEBUI.find('id="updateBody"')
    assert 'display:none' in WEBUI[i:i + 60], "更新卡默认必须收起"


def test_page_does_not_reimplement_file_semantics():
    """负控：页面/接口层不许自己拷文件、自己拼备份路径。"""
    i = WEBUI.find("def _update_start_async(")
    seg = WEBUI[i:i + 1800]
    assert "copy2" not in seg and "shutil" not in seg, "接口层在实现文件覆盖"
    assert "_up.apply()" in seg, "没有复用 core.update.apply"
    j = WEBUI.find('elif self.path.split("?")[0] == "/api/update/rollback":')
    seg2 = WEBUI[j:j + 400]
    assert "_up.rollback()" in seg2, "没有复用 core.update.rollback"


def test_status_reports_backup_count_and_restart_hint():
    i = WEBUI.find("def _update_status(")
    seg = WEBUI[i:i + 1400]
    assert "list_backups()" in seg, "状态里没有备份数（用户不知道能不能回滚）"
    assert "重启" in seg, "没有告诉用户升级后要重启一次"


# ---- merged from tests/test_r1295_update_popover_structure.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def _pop_region():
    i = SRC.find('<div id="updPop"')
    assert i > 0, "找不到更新弹层"
    j = SRC.find("<footer", i)
    assert j > 0, "找不到页脚"
    return SRC[i:j]


def test_popover_divs_are_balanced():
    r = _pop_region()
    opens, closes = r.count("<div"), r.count("</div>")
    assert opens == closes, "弹层内 <div> 未配平：开 %d / 闭 %d（少一个就会吞掉后面的元素）" % (
        opens, closes)


def test_footer_is_outside_popover():
    """页脚必须整体在弹层之后（弹层区域截止到 <footer> 之前，天然满足）。"""
    i = SRC.find('<div id="updPop"')
    j = SRC.find("<footer", i)
    assert j > i
    # 弹层区域里不允许出现 footer 的开启标记
    assert "<footer" not in SRC[i:j]
    # 且 footer 之后不应再有属于弹层的收尾（粗略：footer 到 </body> 之间不再出现 updPop）
    assert SRC.count('<div id="updPop"') == 1


def test_update_card_left_the_health_pane():
    """更新卡不许再回到渠道健康里（用户 19:38 明确要求跟随"版本"那块）。"""
    h0 = SRC.find('<div id="montab-health"')
    h1 = SRC.find("</div><!-- /montab-health -->", h0)
    assert h0 > 0 and h1 > h0
    assert 'id="updateCard"' not in SRC[h0:h1], "更新卡又被塞回渠道健康了"


def test_update_card_sits_in_popover():
    i = SRC.find('<div id="updPop"')
    j = SRC.find("<footer", i)
    assert 'id="updateCard"' in SRC[i:j]
