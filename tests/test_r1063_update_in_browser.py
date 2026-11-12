# -*- coding: utf-8 -*-
"""r1063 T254：更新功能搬进浏览器（用户要求"一切功能都集成在浏览器上"）。

此前只有 CLI（`python -m core.update …`），服务器/无界面环境够用，
但桌面用户的诉求是"点一下就好"。本用例钉住：

* 后端存在 `POST /api/update/apply`（下载→备份→覆盖，失败回滚）；
* 前端有「立即升级」入口与 `updateApply()` 顶层函数（行内 onclick 只能解析全局名）；
* 升级**不覆盖** `config.yaml` / `user_data`（安全边界，核心.update 里的 SKIP）。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import update as U  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_apply_endpoint_exists():
    w = _w()
    assert 'elif self.path == "/api/update/apply":' in w
    i = w.index('elif self.path == "/api/update/apply":')
    seg = w[i:i + 1200]
    assert "_upd.download()" in seg and "_upd.apply(" in seg, \
        "一键升级要自己先下载再应用"
    assert '"ok": False' in seg, "失败要如实回报"


def test_frontend_has_one_click_button_and_global_fn():
    w = _w()
    assert "立即升级" in w and "onclick=\"return updateApply(this)\"" in w
    i = w.index("async function updateApply(")
    line_start = w.rfind("\n", 0, i) + 1
    assert w[line_start:i] == " ", "updateApply 必须是顶层函数（onclick 解析全局名）"
    seg = w[i:i + 900]
    assert "/api/update/apply" in seg
    assert "doRestart" in seg, "升级成功后要能自动重启生效"


def test_update_never_touches_user_config():
    """安全边界：升级不得覆盖 config.yaml 与用户数据。"""
    for p in ("config.yaml", "user_data/app_zhixing/x.json", "data/prices.db",
              "logs/monitor.log"):
        assert U._skip(p) is True, "%s 必须跳过" % p
    for p in ("core/update.py", "crawlers/ctrip.py", "webui.py",
              "main.py"):
        assert U._skip(p) is False, "%s 必须被升级覆盖" % p


def test_confirm_copy_explains_scope():
    """确认框要说清"会动什么、不会动什么"——否则用户不敢点。"""
    w = _w()
    i = w.index("async function updateApply(")
    seg = w[i:i + 1200]
    assert "不会动 config.yaml" in seg or "不会动 config" in seg, seg[:200]
    assert "备份" in seg
