# -*- coding: utf-8 -*-
"""r258 推送层两案（TDD 先行，审校报告 _scratch/r258_push_audit.md
P2×1-2，零发送路径改动、单发零重试不触碰）：

- P-1 (r258-P2-1) 空池补偿行 p7 紧凑档词面粘连：实发形态
  「…无渠道明细7天最低￥1450」连读病句，且 r257-P3-3 为塞进同行把
  p7 压成紧凑形时参照时刻被裁——p7 改独立引用行长形
  「> 近7天直飞最低 ￥N（MM/DD HH:MM）」（4 位价 39/40、5 位价 40/40
  恒落位），同行拼接链与紧凑档整体退役。
- P-2 (r258-P2-2) debug/last_push.md 写入无来源标记：并行非生产进程
  （打桩端点/显式放行旁路）也会写该文件，LESSONS 十§4「mtime 对账」
  取证曾被测试写污染误导——写入头注释带 pid/入口来源。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r258_push.py -q
"""
import logging as _lg
import re
import sys
from datetime import datetime

import pytest

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

_DATE = "2026-09-25"
_ROUTES = [
    {"from": "SHA", "to": "URC", "from_name": "上海",
     "to_name": "乌鲁木齐", "dates": [_DATE],
     "alert_direct": 2000, "alert_transfer": 1800,
     "transfer_arrival_max": "02:00"},
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


@pytest.fixture()
def env(monkeypatch):
    import report as rep

    def _rounds(db, fc, tc, d, am, **kw):
        if (fc, tc) == ("SHA", "SYN"):
            return []
        return [(datetime(2026, 9, 20, 8, 0), 576.0, None)]

    monkeypatch.setattr(rep, "_rounds", _rounds)
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", _DATE):
                                                "http://x/t.png"})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    return {"rep": rep}


# ---------- P-1: p7 独立引用行长形 ----------

def test_empty_pool_p7_standalone_quote_line(env, monkeypatch):
    """空池补偿：p7 独立引用行（粘连消失 + 参照时刻找回 + 恒落位）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    n = FakeN()
    assert rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    d = n.sent["desp"]
    line = [ln for ln in d.splitlines() if "无渠道明细" in ln]
    assert line, d
    assert "7天最低" not in line[0] and "近7天" not in line[0], (
        "补偿行仍拼 p7（词面粘连）：" + line[0])
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref, "p7 参照行缺失：" + d
    assert ref[0].startswith("> 近7天直飞最低 ￥576（"), ref[0]
    assert rep._dw_line(ref[0]) <= 40, ref[0]


def test_empty_pool_p7_standalone_5digit_price(env, monkeypatch):
    """5 位价位带（主价位带上沿）：独立长形恒落位不塌地板。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    monkeypatch.setattr(
        rep, "_rounds",
        lambda db, fc, tc, d, am, **kw:
            [(datetime(2026, 9, 20, 8, 0), 12650.0, None)])
    n = FakeN()
    assert rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    d = n.sent["desp"]
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref and "￥12650" in ref[0], "5 位价参照行缺失：" + d
    assert rep._dw_line(ref[0]) <= 40, ref[0]


def test_constraint_empty_p7_standalone_quote_line(env, monkeypatch):
    """空约束分支（明细在但全被到达/衔接滤掉）同款独立行形态。"""
    rep = env["rep"]

    def _all_filtered(db, fc, tc, d, **kw):
        # 到达约束语义=当日达恒 OK、次日须 ≤02:00（_arrival_ok）——
        # 次日 03:30 达被淘汰；衔接 30min<90min 双保险不满足
        return [{"price": 900, "transCity": "兰州", "depTime": "08:00",
                 "arrTime": "03:30", "depDate": _DATE,
                 "arrDate": "2026-09-26", "layover": 30,
                 "_platform": "qunar"}]

    monkeypatch.setattr(rep, "_route_latest_flights", _all_filtered)
    n = FakeN()
    assert rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    d = n.sent["desp"]
    line = [ln for ln in d.splitlines() if "不满足到达/衔接约束" in ln]
    assert line and "近7天" not in line[0], line[0]
    # 补偿行自身恒 ≤40（r258 after 验收抓的回归：去 fallbacks 后长形
    # 51 宽超门直落——裸档 33 宽地板恒落位）
    assert rep._dw_line(line[0]) <= 40, line[0]
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref, "空约束分支 p7 参照行缺失：" + d
    assert rep._dw_line(ref[0]) <= 40, ref[0]


# ---------- P-2: last_push.md 写入来源标记 ----------

class _FakeResp:
    def __init__(self):
        self.text = '{"errcode":0,"errmsg":"ok"}'

    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    def __call__(self, url, **kw):
        self.payload = kw.get("json")
        return _FakeResp()


def _mk_notifier():
    import core.notifier as nm
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = _lg.getLogger("t258p")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    return n


def test_last_push_carries_source_marker(monkeypatch, tmp_path):
    """last_push.md 头注释带 pid/入口来源：并行非生产进程的写入可从
    内容分辨（十§4 mtime 对账取证不再被旁路写污染误导）。"""
    import os as _os
    monkeypatch.chdir(tmp_path)
    cap = _CapturePost()
    import core.notifier as nm
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = _mk_notifier()
    n.send("t", "正文内容")
    with open("debug/last_push.md", encoding="utf-8") as f:
        head = f.read()
    m = re.search(r"<!-- pid: (\d+) entry: (.+?) -->", head)
    assert m, "last_push.md 头注释缺来源标记（pid/entry）：" + head[:200]
    assert int(m.group(1)) == _os.getpid()
    # 实收正文仍在（取证锚语义不丢）：剥全部头注释行后逐字一致
    body = re.sub(r"\A(<!--[^>]*-->\n)+", "", head)
    assert body == cap.payload["markdown"]["text"]
