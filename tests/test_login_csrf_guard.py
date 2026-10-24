# -*- coding: utf-8 -*-
"""登录桥接端点与其他写接口同门：跨站简单 POST 不得开窗/保存会话。"""
from pathlib import Path


def _block(src, path):
    start = src.index('elif self.path == "%s"' % path)
    end = src.find("elif self.path ==", start + 1)
    return src[start:end if end != -1 else start + 3000]


def test_login_endpoints_require_same_origin_json():
    import webui

    src = Path(webui.__file__).read_text(encoding="utf-8")
    for path in ("/api/login", "/api/login-finish"):
        block = _block(src, path)
        assert "Content-Type 必须为 application/json" in block, path
        assert "跨站登录请求已拒绝" in block, path
        assert "请求体过大" in block, path
