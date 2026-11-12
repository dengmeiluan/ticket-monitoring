# -*- coding: utf-8 -*-
"""r240 推送层（推送审校立案）：

P2-1 推送账本补 errcode 字段——钉钉 -1「系统繁忙」是幽灵送达
（报错但消息已入群，r231 用户实证消息一直收到），该诊断信号此前
只存进程内存（last_errcode），账本层不可回放对账：控制台「推送
记录」分不清「幽灵送达」与「真断推」。落账在产生点捕获结构化
信号（LESSONS 十九§3）：失败行带 errcode，成功行零新键（账本
schema 零噪音）。

P3-1 发送端截断尾注拆两行：尾注行自身 88 半角超宽（全链唯一
无守卫固定词面），手机端必折行断点不受控——按 40 半角拆两行
段落级换行（词面不动，两端渲染律 PC 不认单 \n）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r240_push.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.notifier as _nm  # noqa: E402
from core.notifier import DingTalkNotifier, _append_push_history  # noqa: E402

_LOG = logging.getLogger("r240")


def _last_rec():
    with open(os.environ["PUSH_HISTORY_FILE"], encoding="utf-8") as f:
        return json.loads(f.read().strip().splitlines()[-1])


class TestErrcodeLedger:
    def test_failure_rec_carries_errcode(self):
        _append_push_history("t", "d", False, ch="dingtalk", errcode=-1)
        rec = _last_rec()
        assert rec["ok"] is False and rec["errcode"] == -1, rec

    def test_success_rec_has_no_errcode_key(self):
        _append_push_history("t", "d", True, ch="dingtalk")
        assert "errcode" not in _last_rec()

    def test_dingtalk_send_failure_ledger_errcode(self, monkeypatch, tmp_path):
        """钉钉失败路径落账带 errcode（-1 幽灵送达信号入账本）。"""
        monkeypatch.chdir(tmp_path)   # last_push.md 落临时目录（P3-3 防覆写真档）
        recs = []
        monkeypatch.setattr(_nm, "_append_push_history",
                            lambda *a, **k: recs.append((a, k)))

        class _R:
            text = '{"errcode":-1,"errmsg":"系统繁忙"}'

            @staticmethod
            def json():
                return {"errcode": -1, "errmsg": "系统繁忙"}

        monkeypatch.setattr(_nm.httpx, "post", lambda *a, **k: _R())
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x", _LOG)
        assert d.send("t", "d") is False
        assert d.last_errcode == -1
        assert recs, "失败路径应落账"
        _a, k = recs[-1]
        assert k.get("ch") == "dingtalk" and k.get("errcode") == -1, (a, k)

    def test_dingtalk_send_success_no_errcode(self, monkeypatch, tmp_path):
        """成功路径零新键（账本 schema 零噪音）。"""
        monkeypatch.chdir(tmp_path)
        recs = []
        monkeypatch.setattr(_nm, "_append_push_history",
                            lambda *a, **k: recs.append((a, k)))

        class _R:
            text = '{"errcode":0,"errmsg":"ok"}'

            @staticmethod
            def json():
                return {"errcode": 0, "errmsg": "ok"}

        monkeypatch.setattr(_nm.httpx, "post", lambda *a, **k: _R())
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x", _LOG)
        assert d.send("t", "d") is True
        _a, k = recs[-1]
        assert k.get("errcode") is None, (a, k)


class TestTruncateNoteWrap:
    def test_note_lines_within_40_halfwidth(self):
        """截断尾注按段落级拆行后每行 ≤40 半角（40=20 全角手机行宽）。"""
        from core.notifier import _truncate_note
        note = _truncate_note(True)
        assert "\n\n" in note, "拆两行段落级换行（PC 不认单 \\n）"
        from core.alerter import _dw
        for ln in note.split("\n\n"):
            assert _dw(ln) <= 40, (ln, _dw(ln))

    def test_no_link_branch_wordform(self):
        """无链分支独立指引词面在位（test_v1589 钉面的单源锚）。"""
        from core.notifier import _truncate_note
        assert "本条已无跳转链接" in _truncate_note(no_link=True)
        assert "本条已无跳转链接" not in _truncate_note(False)


class TestWebuiErrcodePin:
    """控制台推送记录的错误码面：DEMO 样例随账本新字段同步现役
    形态（教学面错一字即误导解码），渲染消费点在案。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_demo_sample_mirrors_errcode(self):
        src = self._src()
        assert '"errcode": -1' in src, "DEMO pushlog 失败样例应带 errcode"

    def test_renderer_consumes_errcode(self):
        src = self._src()
        assert "p.errcode!=null" in src, "推送记录渲染应消费 errcode"
