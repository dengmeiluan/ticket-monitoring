# -*- coding: utf-8 -*-
"""r254 推送两案：

推-1 图床显示 URL 百分号编码——_png_user_tag 保留租户 CJK 直拼
jsDelivr URL（账本 913 条），现行钉钉客户端自觉编码可拉图，但 RFC
3986 不保证：换显示端/内核版本差时非 ASCII 直拼可能 404。显示 URL
对 path 段 quote()（GitHub PUT 路径保留原文不受影响）。

推-2 发送端生产资格门——账本资格门拦得住写账本拦不住实发：旁路
调试脚本持真实 webhook 曾把「测试标题」实送生产群（ok=True 实锤
入群）。非生产形态进程（非 exe/非 main.py、webui.py 入口）未显式
重定向时拒绝真实域名发送——与 _prod_ledger_allowed 同构，发送面
收口；显式重定向（测试 webhook 变量）永远放行。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r254_push.py -q
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report  # noqa: E402


def test_upload_ghimg_display_url_quoted(monkeypatch, tmp_path):
    """显示 URL path 段百分号编码：CJK 租户段不再裸拼；PUT 路径保留
    原文（Contents API 未编码路径）。"""
    captured = {}

    class _R:
        status_code = 201
        text = ""

    def fake_put(url, **kw):
        captured["put_url"] = url
        return _R()

    monkeypatch.setattr(report.httpx, "put", fake_put)
    png = tmp_path / "trend_邓美銮_URC_SHA_2026-10-15.png"
    png.write_bytes(b"\x89PNG fake")
    url = report.upload_ghimg(str(png), {"repo": "o/r", "token": "t"},
                              logging.getLogger("t"))
    assert url, "上传应成功返回显示 URL"
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in url), \
        f"显示 URL 仍含裸 CJK: {url}"
    assert "%E9" in url, f"CJK 段未百分号编码: {url}"
    assert "/charts/" in captured["put_url"]
    # PUT 路径保留原文（不 quote）
    assert "trend_邓美銮_URC_SHA_2026-10-15_" in captured["put_url"]


def test_dingtalk_send_prod_gate_blocks_side_scripts(monkeypatch):
    """非生产形态进程未设重定向变量时，真实域名发送被资格门拒绝
    （返回 False 不发请求）；显式重定向变量放行（压测打桩路径）。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0,"errmsg":"ok"}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: False)
    # 旁路形态：无重定向变量 → 拒发（conftest autouse 放行的会话态
    # 由 delenv 显式摘除，monkeypatch LIFO 测试结束自恢复）
    monkeypatch.delenv("DING_WEBHOOK_ALLOW", raising=False)
    dt = DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=real",
        logging.getLogger("t"))
    ok = dt.send("t", "d")
    assert ok is False
    assert "url" not in sent, "资格门应拦住真实发送"
    # 显式重定向（测试 webhook 声明）→ 放行
    monkeypatch.setenv("DING_WEBHOOK_ALLOW", "1")
    ok2 = dt.send("t", "d")
    assert ok2 is True
    assert "oapi.dingtalk.com" in sent["url"]


def test_dingtalk_send_prod_gate_allows_prod_process(monkeypatch):
    """生产形态进程（exe/main.py/webui.py 入口）不受门影响。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: True)
    monkeypatch.delenv("DING_WEBHOOK_ALLOW", raising=False)
    dt = DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=real",
        logging.getLogger("t"))
    assert dt.send("t", "d") is True
    assert "oapi.dingtalk.com" in sent["url"]


def test_dingtalk_send_gate_spares_stub_endpoints(monkeypatch):
    """非真实域名（本地打桩/假端点）不受门限制——单测 fake 与压测
    打桩路径零感知。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: False)
    monkeypatch.delenv("DING_WEBHOOK_ALLOW", raising=False)
    dt = DingTalkNotifier("http://127.0.0.1:9/mock/robot",
                          logging.getLogger("t"))
    assert dt.send("t", "d") is True
    assert "127.0.0.1:9" in sent["url"]


def test_dingtalk_send_gate_rejects_zero_flag(monkeypatch):
    """严格判钉（Soldier Minor-1）：DING_WEBHOOK_ALLOW 取值「0」必须
    与「未设」同拒——门写松成 truthy 判断（设了就放行）时本钉变红。
    delenv 形态的既有钉抓不住该变异（无变量两态同假）。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: False)
    monkeypatch.setenv("DING_WEBHOOK_ALLOW", "0")
    dt = DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=real",
        logging.getLogger("t"))
    assert dt.send("t", "d") is False
    assert "url" not in sent, "ALLOW=0 应与未设同拒，不得放行真实域名"


def test_local_push_image_roundtrip_quoted_url(monkeypatch, tmp_path):
    """推-1 往返钉（Soldier P1-1）：quote 后的图 URL 尾段必须仍能
    反推本地渲染图——邮件通道 _local_push_image 按尾段**原文**拼
    data/{stem}.png，编码后反推恒 miss、回落高失败率网络下载；
    unquote 对存量裸 CJK 与 ASCII 茎双态 no-op。"""
    import urllib.parse as _up
    from core import notifier
    monkeypatch.chdir(tmp_path)
    stem = "trend_邓美銮_URC_SHA_2026-10-15"
    img = tmp_path / "data" / (stem + ".png")
    img.parent.mkdir()
    img.write_bytes(b"\x89PNG fake")
    path = f"charts/20261007/{stem}_030938.png"
    url = "https://cdn.jsdelivr.net/gh/o/r@main/" + _up.quote(path, safe=":/@")
    assert "%E9" in url
    assert notifier._local_push_image(url) == b"\x89PNG fake"
