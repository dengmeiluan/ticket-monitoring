# -*- coding: utf-8 -*-
"""r339 双特性：
① Bark iOS 推送通道（论坛 AiLao 提案）——build_urgent_notifier 第四
   达标强提醒成员（与 ntfy 同位：系统级弹窗、心跳不触发、单发零重试
   同钉钉纪律）；POST /push JSON（GET 路径形态有 URL 长度上限，600
   截断语义装不下）；server 可自托管。
② 返程日期多选（AiLao：往返逻辑不清晰）——ret_dates 列表替换单
   ret_date 语义（legacy 键读取合并，跨产品兼容）；sweep 侧逐返程日
   采集（crawler/storage 零改动，行级 ret_date 列天然承载）。"""
import logging as _lg
from unittest import mock

import core.notifier as N


# ---- ① Bark 通道 ----

def _mk(monkeypatch, code=200):
    log = _lg.getLogger("t")
    bk = N.BarkNotifier(key="testkey123", logger=log)
    calls = []

    def _fake_post(url, **kw):
        calls.append((url, kw))
        return mock.Mock(status_code=200, json=lambda: {"code": code})
    monkeypatch.setattr(N.httpx, "post", _fake_post)
    return bk, calls


def test_bark_send_ok(monkeypatch):
    bk, calls = _mk(monkeypatch)
    assert bk.send("达标", "上海-海口 ￥900") is True
    assert len(calls) == 1
    url, kw = calls[0]
    assert url.endswith("/push")
    body = kw["json"]
    assert body["device_key"] == "testkey123"
    assert body["title"] and "￥900" in body["body"]
    assert kw.get("timeout") and kw.get("trust_env") is False  # 直连律


def test_bark_empty_key_no_call(monkeypatch):
    log = _lg.getLogger("t")
    bk = N.BarkNotifier(key="", logger=log)
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **k: calls.append(u)
                        or mock.Mock(status_code=200))
    assert bk.send("t", "b") is False
    assert calls == []


def test_bark_non200_false(monkeypatch):
    bk, calls = _mk(monkeypatch, code=400)
    assert bk.send("t", "b") is False


def test_bark_body_plain(monkeypatch):
    # 正文转写：图占位/链接还原/markdown 记号剥除（ntfy 同族律）
    bk, calls = _mk(monkeypatch)
    bk.send("t", "![x](https://img) [**直飞 ￥1**](https://a) # > * `z")
    body = calls[0][1]["json"]["body"]
    assert "![x]" not in body and "](https" not in body
    assert "https://a" in body and "直飞 ￥1" in body
    # 记号剥实断言（原恒真式改写：剥后无 markdown 残留字面）
    assert "#" not in body and "*" not in body and "`" not in body


def test_bark_in_urgent_builder():
    log = _lg.getLogger("t")
    outs = N.build_urgent_notifier(
        {"bark": {"enabled": True, "key": "k1"}}, log)
    assert any(isinstance(x, N.BarkNotifier) for x in outs)


def test_bark_absent_not_built():
    assert N.build_urgent_notifier({}, _lg.getLogger("t")) is None \
        or not any(isinstance(x, N.BarkNotifier)
                   for x in (N.build_urgent_notifier(
                       {}, _lg.getLogger("t")) or []))


# ---- ② 返程日期多选 ----

def _rt(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "NRT",
         "to_name": "东京成田", "dates": ["2026-11-16"],
         "alert_direct": 2500}
    d.update(kw)
    return d


def test_ret_dates_legacy_key_merges():
    r = main_rt = __import__("main").build_routes(
        [_rt(ret_date="2026-11-20")])[0]
    assert r.ret_dates == ["2026-11-20"]


def test_ret_dates_list_honored_dedupe():
    r = __import__("main").build_routes([_rt(ret_dates=[
        "2026-11-20", "2026-11-27", "2026-11-20"])])[0]
    assert r.ret_dates == ["2026-11-20", "2026-11-27"]


def test_ret_dates_absent_empty():
    r = __import__("main").build_routes([_rt()])[0]
    assert r.ret_dates == []
