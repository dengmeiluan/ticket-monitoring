# -*- coding: utf-8 -*-
"""v1.5.86 推送钉：发送端截断终验（推送审校唯一 P2）。

notifier 截断流程：cut_b=text[:17900]→img/edge 切点不触发时保持
17900B→追加 108B 尾注=18008B>18000 上限（切点窗口
[17893,17898] 同理）——钉钉网关按字节拒收/服务端再截，单发铁律
下该轮必丢。修法=追加后终验：超限按「上限-尾注」重切再补尾注
（尾注地板档恒落位，正文按剩余预算让位——预留制投影）。

运行:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v186_push.py -q
"""
import logging

import core.notifier as nm


class _FakeResp:
    def __init__(self):
        self.text = '{"errcode":0,"errmsg":"ok"}'

    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    """捕获 payload 的 httpx.post 替身（零网络）。"""

    def __call__(self, url, **kw):
        self.url = url
        self.payload = kw.get("json")
        return _FakeResp()


class TestTruncateFinalGuard:
    def _mk(self):
        n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
        n.logger = logging.getLogger("t")
        n.last_errcode = None
        n._fail_streak = 0
        n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
        return n

    def test_truncated_body_never_exceeds_18000(self, monkeypatch, tmp_path):
        # 19000B 纯 ASCII（无 ![ 无 \n\n）→ img/edge 切点全不触发，
        # 修前产物=17900+尾注 108B=18008B 超限
        monkeypatch.chdir(tmp_path)   # send() 向 CWD 落 debug/last_push.md
        cap = _CapturePost()
        monkeypatch.setattr(nm.httpx, "post", cap)
        n = self._mk()
        desp = "a" * 19000
        n.send("t", desp)
        txt = cap.payload["markdown"]["text"]
        assert len(txt.encode("utf-8")) <= 18000, \
            f"截断产物 {len(txt.encode('utf-8'))}B 超钉钉 18000B 上限"
        assert "已截断" in txt, "尾注丢失面说明未落位"

    def test_truncate_with_link_keeps_note_and_limit(self, monkeypatch, tmp_path):
        # 双图链：尾部图链被 img 切点切掉（防死链，既有语义），
        # 前部图链保留；终验不改变形态，仅保证字节闭合
        monkeypatch.chdir(tmp_path)   # send() 向 CWD 落 debug/last_push.md
        cap = _CapturePost()
        monkeypatch.setattr(nm.httpx, "post", cap)
        n = self._mk()
        desp = ("x" * 8000 + "\n\n![走势](https://a.com/x.png)\n\n"
                + "y" * 8000 + "\n\n![走势](https://b.com/t.png)\n\n"
                + "z" * 2500)
        n.send("t", desp)
        txt = cap.payload["markdown"]["text"]
        assert len(txt.encode("utf-8")) <= 18000
        assert "](https://a.com/x.png)" in txt, "在位图链被误切"
