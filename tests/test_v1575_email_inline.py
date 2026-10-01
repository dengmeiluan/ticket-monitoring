# -*- coding: utf-8 -*-
"""邮件推送图 CID 内嵌回归：desp 图床外链图（![..](http..)）发送
端下载转 cid 内嵌（收件端零外网请求——QQ/163 网页版对 http 外链图默认
折叠+免费图床直链加载慢）；下载失败/非图片保留外链，纯文本 part 恒用
desp 原文，钉钉等其他通道不受影响（无 send 协议形参变化）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1575_email_inline.py
"""
import logging
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notifier import (  # noqa: E402
    EmailNotifier,
    _inline_push_images,
    _sniff_img_fmt,
)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

LOG = logging.getLogger("t1575mail")

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64    # PNG 魔数开头的假 bytes
_JPG = b"\xff\xd8\xff\xe0" + b"y" * 32     # JPEG 魔数开头的假 bytes


def _em(**kw):
    d = dict(host="smtp.163.com", port=465, user="a@163.com",
             password="pw16", to="b@qq.com", logger=LOG)
    d.update(kw)
    return EmailNotifier(**d)


def _parts_of(msg):
    return msg.get_payload()


def _alt_parts(msg):
    """兼容 related（[0]=alternative）与纯 alternative（[0]=plain）两形态"""
    parts = msg.get_payload()
    if parts[0].get_content_type() == "multipart/alternative":
        plain, html = parts[0].get_payload()
    else:
        plain, html = parts[0], parts[1]
    assert plain.get_content_type() == "text/plain"
    assert html.get_content_type() == "text/html"
    return (plain.get_payload(decode=True).decode("utf-8"),
            html.get_payload(decode=True).decode("utf-8"))


_alt_html = _alt_parts


# ---- _sniff_img_fmt：魔数嗅探（软拒 HTML 页/webp 不内嵌） ----

def test_sniff_fmt_magic():
    assert _sniff_img_fmt(_PNG) == "png"
    assert _sniff_img_fmt(_JPG) == "jpeg"
    assert _sniff_img_fmt(b"<html>403</html>") == ""
    assert _sniff_img_fmt(b"RIFFxxxxWEBP") == ""


# ---- _inline_push_images：URL 提取/替换/去重/降级 ----

def test_inline_replaces_only_image_forms():
    desp = ("#### 📋 明细总表\n\n![明细总表](https://sm.ms/a.png)\n\n"
            "[打开同链](https://sm.ms/a.png)\n\n> 引用行")
    with mock.patch("core.notifier._fetch_push_image", return_value=_PNG):
        out, parts = _inline_push_images(desp, LOG)
    assert len(parts) == 1 and parts[0][0] == "push-img-1"
    # 图片形态换 cid；纯文字链接同 URL 保持原样（链接点开仍应是图片页）
    assert "![明细总表](cid:push-img-1)" in out
    assert "[打开同链](https://sm.ms/a.png)" in out


def test_inline_dedupes_same_url():
    desp = "![走势 09/25](https://sm.ms/a.png)\n\n![走势2](https://sm.ms/a.png)"
    with mock.patch("core.notifier._fetch_push_image", return_value=_PNG) as f:
        out, parts = _inline_push_images(desp, LOG)
    f.assert_called_once()
    assert len(parts) == 1
    assert out.count("(cid:push-img-1)") == 2


def test_inline_no_urls_is_noop():
    out, parts = _inline_push_images("#### 正文\n\n> 引用\n\n- 项", LOG)
    assert out == "#### 正文\n\n> 引用\n\n- 项" and parts == []


# ---- _build_msg：related 组装 / 降级保留外链 / 纯文本原文 ----

_DESP_IMG = ("#### 📋 明细总表 tier\n\n![明细总表](https://sm.ms/a.png)"
             "\n\n![走势](https://sm.ms/b.png)\n\n> 引用行")


def test_build_msg_inline_images_related_with_cids():
    n = _em()   # 无 snapshot_base：related 仅由推送图触发
    with mock.patch("core.notifier._fetch_push_image",
                    side_effect=[_PNG, _JPG]):
        msg = n._build_msg("t", _DESP_IMG)
    assert msg.get_content_type() == "multipart/related"
    parts = _parts_of(msg)
    assert parts[0].get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in parts[1:]] == [
        "image/png", "image/jpeg"]
    assert parts[1]["Content-ID"] == "<push-img-1>"
    assert parts[2]["Content-ID"] == "<push-img-2>"
    plain, html = _alt_html(msg)
    # HTML part 外链全数换 cid（收件端零外网请求）
    assert 'src="cid:push-img-1"' in html and 'src="cid:push-img-2"' in html
    assert "https://sm.ms/" not in html
    # 纯文本 part 恒用 desp 原文（外链保持可点）
    assert "![明细总表](https://sm.ms/a.png)" in plain


def test_build_msg_download_fail_keeps_external_alternative():
    n = _em()
    with mock.patch("core.notifier._fetch_push_image",
                    side_effect=OSError("连接超时")):
        msg = n._build_msg("t", _DESP_IMG)
    # 全部下载失败且无快照 → 维持无图 alternative（旧行为）
    assert msg.get_content_type() == "multipart/alternative"
    _, html = _alt_html(msg)
    assert "https://sm.ms/a.png" in html


def test_build_msg_partial_fail_mixed_parts():
    n = _em()
    with mock.patch("core.notifier._fetch_push_image",
                    side_effect=[_PNG, OSError("挂")]):
        msg = n._build_msg("t", _DESP_IMG)
    assert msg.get_content_type() == "multipart/related"
    parts = _parts_of(msg)
    assert len(parts) == 2   # alternative + 1 张成功内嵌
    _, html = _alt_html(msg)
    assert "cid:push-img-1" in html
    assert "https://sm.ms/b.png" in html   # 失败张保留外链


def test_build_msg_snapshot_plus_inline_order():
    n = _em(snapshot_base="http://127.0.0.1:8765/")
    with mock.patch("core.emailshot.render_console_png", return_value=_PNG), \
         mock.patch("core.notifier._fetch_push_image", return_value=_PNG):
        msg = n._build_msg("t", _DESP_IMG)
    parts = _parts_of(msg)
    assert parts[1].get_content_type() == "image/png"
    assert parts[1]["Content-ID"] == "<console-shot>"   # 快照恒在前
    assert parts[2]["Content-ID"] == "<push-img-1>"
    assert parts[3]["Content-ID"] == "<push-img-2>"
    _, html = _alt_html(msg)
    assert "cid:console-shot" in html


def test_build_msg_cap_six_images():
    n = _em()
    desp = "".join("![图%d](https://sm.ms/%d.png)\n\n" % (i, i)
                   for i in range(8))
    with mock.patch("core.notifier._fetch_push_image", return_value=_PNG):
        msg = n._build_msg("t", desp)
    parts = _parts_of(msg)
    assert len(parts) == 1 + 6   # alternative + 上限 6 张


def test_no_images_never_touches_network():
    n = _em(snapshot_base="http://127.0.0.1:8765/")
    with mock.patch("core.notifier.httpx.get",
                    side_effect=AssertionError("不应发起下载")), \
         mock.patch("core.emailshot.render_console_png", return_value=_PNG):
        msg = n._build_msg("t", "#### 正文\n\n> 引用行")
    assert msg.get_content_type() == "multipart/related"
