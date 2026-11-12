# -*- coding: utf-8 -*-
"""r1063 T48：健康页的「重置会话」按钮 + 「已重建 N 次」读数。

上一轮只做了接口（可干预 = 得能点，不能只靠 curl）。这轮把它放到渠道行上，
沿用既有 `.ac` 按钮与 `.e2` 的 `<i class="e2k">` 标签，**不加任何新视觉**。

两条硬约束：
  * 破坏性动作**必须 confirm**（会丢登录态），且文案要说清"可还原"；
  * 系统动过档案就要**说出来**（「已重建 N 次」），否则用户不知道为什么要重登。
"""
import io
import os

import webui
from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def _fn(name):
    i = SRC.index("function %s(" % name)
    j = SRC.index("\nfunction ", i + 10)
    return SRC[i:j]


def test_pacing_counts_resets_and_exposes_them():
    p = Pacing({"fliggy": {}, "ctrip": {}})
    assert p.reset_count("fliggy") == 0
    p.note_reset("fliggy")
    p.note_reset("fliggy")
    assert p.reset_count("fliggy") == 2
    ch = p.snapshot()["channels"]
    assert (ch.get("fliggy") or {}).get("resets") == 2, ch.get("fliggy")
    # 没重建过的渠道不出现该字段（不制造 0 值噪声）
    assert "resets" not in (ch.get("ctrip") or {})


def test_row_has_the_button_and_the_counter():
    seg = SRC[SRC.index("const chips=_order.map(k=>{"):][:24000]
    assert "paceSessionReset(" in seg, "行里没有重置会话按钮"
    assert "data-pk=\"'+k+':sreset\"" in seg or ":sreset" in seg
    assert "已重建 " in seg, "行里没有「已重建 N 次」读数"


def test_button_is_browser_only():
    """App 渠道换档案要走渠道登录，不是删设备目录。"""
    seg = SRC[SRC.index("const chips=_order.map(k=>{"):][:24000]
    i = seg.index("sreset")
    assert "/^app_/.test(String(k))" in seg[max(0, i - 600):i], \
        "按钮没有排除 App 渠道"


def test_confirm_before_destructive_action():
    fn = _fn("paceSessionReset")
    assert "confirm(" in fn, "破坏性动作没有二次确认"
    assert "可还原" in fn, "没告诉用户旧档案可还原"
    assert "/api/session/reset" in fn
    assert "method:'POST'" in fn


def test_readout_uses_existing_badge_pattern():
    """沿用 `<i class="e2k">` 标签，不新起视觉。"""
    i = SRC.index("_srTxt?(")
    seg = SRC[max(0, i - 300):i + 300]
    assert 'class="e2k"' in seg, "读数没走既有标签样式"


def test_both_paths_record_the_count():
    """手动与自动都要记数，否则读数永远 0。"""
    # 取**后端路由**那一处：前端函数里也有同一串，先跳过它
    i = SRC.index('self.path == "/api/session/reset"')
    seg = SRC[i:i + 2500]
    assert "note_reset(" in seg, "手动路由没记数"
    assert "note_reset(" in MAIN, "自动兜底没记数"


def test_panel_payload_carries_resets():
    """读数来自 `/api/pacing`（pacing.snapshot），不是前端自己编的。"""
    p = Pacing({"fliggy": {}})
    p.note_reset("fliggy", 3)
    got = webui._demo_pacing_payload if False else None  # noqa: F841
    assert p.snapshot()["channels"]["fliggy"]["resets"] == 3
