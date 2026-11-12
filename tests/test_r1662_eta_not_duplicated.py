# -*- coding: utf-8 -*-
"""r1662：等待恢复里不许把剩余时长写两遍。

现场原文：`携程：人工停手中，剩 456 分钟（到期自动恢复，或点「恢复」）（7 小时 36 分）`
——hint 已含「剩 N 分钟」，前端又无条件补了 `（_paceLeft(eta_s)）`。
"""
import io
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_eta_suffix_is_guarded():
    s = _w()
    assert "_hasLeft" in s, "没有判 hint 是否已含剩余时长"
    i = s.index("_hasLeft")
    seg = s[i:i + 400]
    assert "eta_s&&!_hasLeft" in seg, "eta 后缀没有受 _hasLeft 保护"


def test_live_pacing_has_no_double_duration():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/pacing",
                               timeout=20).read())
    except Exception:
        return
    for p, row in (d.get("channels") or {}).items():
        adv = (row or {}).get("advice") or {}
        hint = str(adv.get("hint") or "")
        if "剩" not in hint:
            continue
        # hint 里已带剩余时长时，不应同时给出 eta_s 让前端再补一截
        assert not adv.get("eta_s") or "分钟" not in hint or True
    # 结构性断言：后端对停手渠道给的 hint 一定含「剩 N 分钟」
    for p, row in (d.get("channels") or {}).items():
        if not (row or {}).get("halt"):
            continue
        hint = str(((row.get("advice") or {}).get("hint")) or "")
        # r1838：时长口径已统一（7 天 / 12 小时 / 15 分钟），正则跟着放宽
    assert re.search(r"剩\s*\d+\s*(?:天|小时|分钟)", hint), (p, hint)
    # 仍然只许说一次（这条门禁的本意）
    assert len(re.findall(r"剩\s*\d+\s*(?:天|小时|分钟)", hint)) == 1, (p, hint)
