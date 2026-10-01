# -*- coding: utf-8 -*-
"""推送层钉（推送审校 P1-1：ghimg 同分钟竞态）。

心跳推送与日报同轮各自渲染上传同名趋势图，远端路径时间戳只到
分钟——后到者 PUT 缺 sha 被 GitHub 422 拒绝，日报走势图整节蒸发
（有文本兜底但图缺失）。路径加秒到 %H%M%S 消同分钟竞态；邮件
cid 直嵌的本地反推正则同步兼容 4/6 位双态（存量 push_history 里的
旧 4 位 URL 风暴延迟重发场景仍可直读本地，miss 才走下载兜底）。
"""
import re
import logging
from datetime import datetime

import report
from core import notifier


def test_upload_ghimg_path_has_seconds(monkeypatch, tmp_path):
    captured = {}

    class _R:
        status_code = 201
        text = ""

    def fake_put(url, **kw):
        captured["url"] = url
        return _R()

    monkeypatch.setattr(report.httpx, "put", fake_put)
    png = tmp_path / "trend_URC_SHA_2026-10-06.png"
    png.write_bytes(b"\x89PNG fake")
    url = report.upload_ghimg(str(png), {"repo": "o/r", "token": "t"},
                              logging.getLogger("t"))
    m = re.search(r"/charts/\d{8}/trend_URC_SHA_2026-10-06_(\d{6})\.png$",
                  url or "")
    assert m, f"路径未含 6 位时分秒戳: {url}"


def test_upload_ghimg_same_minute_distinct_paths(monkeypatch, tmp_path):
    # 同分钟两次上传（心跳+日报同轮竞态的构造形态）路径必须不同
    seq = [datetime(2026, 9, 29, 9, 8, 0), datetime(2026, 9, 29, 9, 8, 25)]

    class _FakeDT:
        @staticmethod
        def now():
            return seq[len(captured) % len(seq)]

    captured = []

    class _R:
        status_code = 201
        text = ""

    def fake_put(url, **kw):
        captured.append(url)
        return _R()

    monkeypatch.setattr(report.httpx, "put", fake_put)
    monkeypatch.setattr(report, "datetime", _FakeDT)
    png = tmp_path / "trend_URC_SHA_2026-10-06.png"
    png.write_bytes(b"\x89PNG fake")
    ih = {"repo": "o/r", "token": "t"}
    log = logging.getLogger("t")
    u1 = report.upload_ghimg(str(png), ih, log)
    u2 = report.upload_ghimg(str(png), ih, log)
    assert u1 and u2 and u1 != u2, \
        f"同分钟两次上传路径撞车: {u1} vs {u2}"


def test_local_push_image_matches_both_timestamps(tmp_path, monkeypatch):
    # 邮件 cid 直嵌反推正则兼容旧 4 位/新 6 位时分戳双态
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trend_X.png").write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)
    base = "https://cdn.jsdelivr.net/gh/o/r@main/charts/20260929/trend_X"
    assert notifier._local_push_image(base + "_0930.png") == b"png-bytes"
    assert notifier._local_push_image(base + "_093015.png") == b"png-bytes"
    assert notifier._local_push_image(base + ".png") == b""
