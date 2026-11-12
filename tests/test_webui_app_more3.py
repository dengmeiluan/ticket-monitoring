# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_app_login_clears_wall.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import sys


# ---- merged from tests/test_r1063_app_login_clears_wall.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui_full_src()


def test_app_login_finish_clears_wall_and_reprobes():
    """锚点必须用**本次改动独有**的文本：`/api/app-login/finish` 在 JS 里先出现，
    按它切片会切到前端代码里（本轮又踩了一次）。"""
    s = _src()
    i = s.index('note="App 内登录并导出快照（真机画面）")')
    seg = s[i:i + 1600]
    assert "_clear_login_wall_memo(_plata" in seg, \
        "App 登录成功后没有清登录墙记忆——用户会看到「登了还需要登录」"
    assert "_kick_login_probe(_plata)" in seg, \
        "登录成功应当顺手后台复探一次（与浏览器侧一致）"


def test_helper_clears_app_channel_wall(tmp_path, monkeypatch):
    """`_clear_login_wall_memo("app_ctrip")` 必须能清掉该渠道的墙文件。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "app_ctrip"
    d.mkdir(parents=True, exist_ok=True)
    (d / "login_wall.json").write_text(
        json.dumps({"until": 9e9, "detail": "该日被要求登录"}),
        encoding="utf-8")

    import webui
    monkeypatch.setattr(webui, "_ud_root_runtime", lambda: str(tmp_path),
                        raising=False)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)}},
                        raising=False)
    cleared = webui._clear_login_wall_memo("app_ctrip", "app_ctrip")
    assert not (d / "login_wall.json").exists(), cleared
    assert any("app_ctrip" in c for c in cleared), cleared
