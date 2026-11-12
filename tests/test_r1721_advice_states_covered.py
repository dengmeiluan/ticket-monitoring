# -*- coding: utf-8 -*-
"""r1721：`advise()` 能返回的每个 state，节流行都必须有专属文案。

现场：`advise()` 会返回 `state="cooldown"`（熔断/冷却中），而 label 链里
**没有这一支**——落到默认初值，用户看不到"这行在冷却、还剩多久"。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _adv_states():
    s = io.open(os.path.join(ROOT, "core", "pacing.py"), encoding="utf-8").read()
    i = s.index("def advise(")
    j = s.find("\ndef ", i + 10)
    body = s[i:j if j > i else len(s)]
    return sorted(set(re.findall(r'"state":\s*"([a-z_]+)"', body)))


def _ui_states():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    return sorted(set(re.findall(r"adv\.state==='([a-z_]+)'", w)))


def test_every_advice_state_has_a_row_branch():
    miss = [x for x in _adv_states() if x not in _ui_states()]
    assert not miss, "这些 state 没有专属行文案（会落到默认，读作正常）：%s" % miss


def test_cooldown_branch_shows_remaining():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = w.index("adv.state==='cooldown'")
    seg = w[i:i + 420]
    assert "冷却中" in seg, "冷却中没写「冷却中」"
    assert "remain_s" in seg or "分钟" in seg, "冷却中没有剩余时间"
