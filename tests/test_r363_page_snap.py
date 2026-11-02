# -*- coding: utf-8 -*-
"""r363 首页 gzip/ETag 性能收口：

/ 是 3.2MB 内联 HTML，旧响应无 Content-Encoding、无 ETag，每次导航
全量重下。修法：_page_snap(version) 按代际缓存 (body, etag, gz)，
同代际并发只 replace/压缩一次；/ 按 If-None-Match 回 304，Accept-
Encoding: gzip 时发压缩体（约 370KB），Cache-Control: no-cache 保留
（升级重启后仍必回源校验，绝不拿旧页 JS）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r363_page_snap.py -q
"""
import gzip
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui


def test_page_snap_caches_by_version():
    w = _src()
    body1, etag1, gz1 = w._page_snap("r363-test-v1")
    body2, etag2, gz2 = w._page_snap("r363-test-v1")
    assert body1 is body2 and gz1 is gz2 and etag1 == etag2
    assert b"__PAGEVER__" not in body1
    assert b"r363-test-v1" in body1
    assert gzip.decompress(gz1) == body1
    # 内嵌 92 枚 PNG 已压缩，gzip 只收文本层（3.28→1.92MB）；至少省 25%
    assert len(gz1) < len(body1) * 0.75
    assert etag1.startswith('"p-') and etag1.endswith('"')

    body3, etag3, gz3 = w._page_snap("r363-test-v2")
    assert etag3 != etag1
    assert body3 != body1
    assert gzip.decompress(gz3) == body3


def test_root_sends_etag_304_and_gzip():
    s = _src().PAGE  # noqa: F841  (imports/bakes PAGE before reading source)
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index('def do_GET(self):')
    block = src[i:i + 1800]
    assert "_page_snap(_State.version)" in block
    assert 'If-None-Match' in block
    assert 'self.send_response(304)' in block
    assert 'Content-Encoding", "gzip"' in block
    assert 'Vary", "Accept-Encoding"' in block
    assert 'Cache-Control", "no-cache"' in block
    # 旧实现整页明文下发：无 ETag/压缩
    assert 'body = _page_html(_State.version).encode("utf-8")' not in block
