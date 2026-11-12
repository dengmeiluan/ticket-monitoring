# -*- coding: utf-8 -*-
"""r1197：更新闭环必须"在浏览器里能走完"——检查 / 升级 / 回滚 / 知道要重启。

后端文件语义已由 `test_r1189`（apply 的备份/跳过/失败回滚）与
`test_r1197`（list_backups / rollback）用真 zip 验过；这里守界面与接口：

1. 三个端点都在：`/api/update/status`、`/api/update/start`、`/api/update/rollback`；
2. 页面有卡片 + 三个按钮 + 进度轮询，默认收起；
3. **负控**：页面里不许自己实现"覆盖文件/回滚"（那是第二份语义，迟早和 core 分叉）。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


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
