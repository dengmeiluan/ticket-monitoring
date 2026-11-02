# -*- coding: utf-8 -*-
"""登录桥接端点与其他写接口同门：跨站简单 POST 不得开窗/保存会话。"""
from pathlib import Path


def _block(src, path):
    start = src.index('elif self.path == "%s"' % path)
    end = src.find("elif self.path ==", start + 1)
    return src[start:end if end != -1 else start + 3000]


def test_login_endpoints_require_same_origin_json():
    """登录桥接端点与其它写接口同一道门：JSON 判据 + 同源 + 体积上限。

    r672b 起「Content-Type 必须为 application/json」收进单源
    `_json_body_ok()`（只有带 body 才要求 JSON）——逐分支再写一份会让
    无 body 的同源 POST 全被打成 415。所以这里守的是「调了同一道门」，
    而不是「每个分支里都抄了一遍那句话」。
    """
    import webui

    src = Path(webui.__file__).read_text(encoding="utf-8")
    for path in ("/api/login", "/api/login-finish"):
        block = _block(src, path)
        assert "if not self._json_body_ok():" in block, path
        assert "跨站登录请求已拒绝" in block, path
        assert "请求体过大" in block, path
