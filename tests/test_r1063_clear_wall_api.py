# -*- coding: utf-8 -*-
'''给 clear-wall 干预接口补契约测试（T131）。

注意：`webui.py` 里 `/api/channel/reset-app` 先在 **JS 文案**里出现、后才有
server handler，所以切片必须锚定 `elif self.path == "...":` 这一段，
否则会切到几百万字符的正文里去（本轮就踩过）。
'''
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _handler_slice(src: str, path: str) -> str:
    """取某个 API handler 的正文（到下一个 elif self.path 为止）。"""
    anchor = 'elif self.path == "%s":' % path
    i = src.index(anchor)
    j = src.find("elif self.path == ", i + len(anchor))
    return src[i:j if j > 0 else i + 4000]


def test_endpoint_exists_and_returns_shape():
    src = _w()
    seg = _handler_slice(src, "/api/channel/clear-wall")
    assert "_clear_login_wall_memo" in seg
    assert '"cleared"' in seg
    assert "下一轮" in seg, "应告诉用户下一步"


def test_reset_app_reuses_the_same_helper():
    src = _w()
    seg = _handler_slice(src, "/api/channel/reset-app")
    assert "_clear_login_wall_memo" in seg, seg[-500:]


def test_clear_wall_is_non_destructive():
    src = _w()
    seg = _handler_slice(src, "/api/channel/clear-wall")
    for bad in ("pm clear", "rm -rf", "shutil.rmtree"):
        assert bad not in seg, "clear-wall 不该做破坏性操作：%s" % bad
