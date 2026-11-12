# -*- coding: utf-8 -*-
"""r1063 T265：面板「检查更新」入口 + 路由必须容忍 `?force=1`。

真机踩到：只比裸路径 `self.path == "/api/update/check"`，带 query 时不匹配，
返回空响应 → 前端 `JSON.parse('')` 抛
`Failed to execute 'json' on 'Response': Unexpected end of JSON input`，
用户看到的是"检查更新请求失败"，而不是结论。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_route_tolerates_query_string():
    w = _w()
    assert 'self.path.split("?")[0] == "/api/update/check"' in w, \
        "路由必须按 ? 切分后再比，否则 ?force=1 拿不到响应"


def test_panel_always_shows_version_and_check_entry():
    w = _w()
    assert 'data["version"]' in w, "载荷要永远带当前版本"
    assert "updateCheck" in w and "检查更新" in w
    # 无更新时也要有那一行（很小的版本 + 检查入口）
    i = w.index("if(!u||!u.latest){")
    seg = w[i:i + 700]
    assert "检查更新" in seg and "j.version" in seg, seg[:200]


def test_frontend_survives_empty_body():
    w = _w()
    i = w.index("async function updateCheck(")
    seg = w[i:i + 900]
    assert "catch(_e){j=null;}" in seg, "空/非 JSON 响应不能抛 SyntaxError"
    assert "非 JSON" in seg, "要给出可读提示"


def test_check_update_does_not_auto_apply():
    """检查更新只读；写文件必须人点头（绝不在检查里顺手 apply）。"""
    w = _w()
    i = w.index("async function updateCheck(")
    seg = w[i:w.index("async function updateApply(")]
    assert "/api/update/apply" not in seg, "检查更新不得触发 apply"
