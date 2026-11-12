# -*- coding: utf-8 -*-
"""r1063 T127：把「App 侧被风控」做成面板可见的降级项（不只是写日志）。

背景：用户反复问"为什么 0 条"。App 侧的「需登录」「验证页」「阿里访问被拒绝安全页」
都属于**必须换手段**的一类（登录 / 改走浏览器通路），但以前只写日志——
面板上永远只看到"0 条"，看不出是哪一类卡住。

现在：`mark_login_wall()` 额外记一条 `degraded.note("app_risk_blocked", 渠道, 原因)`，
面板「降级」那行会显示「App 风控」+ 下一步建议（去登录 / 换浏览器通路）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mark_login_wall_records_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import degraded as dg
    with dg._LOCK:
        dg._STATE.clear()

    from crawlers import app_base
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    # 结构保证：记账发生在 mark_login_wall 里
    i = src.index("def mark_login_wall")
    seg = src[i:i + 700]
    assert "app_risk_blocked" in seg, seg[:300]
    assert "degraded" in seg


def test_degraded_cap_is_known(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import degraded as dg
    with dg._LOCK:
        dg._STATE.clear()
    dg.note("app_risk_blocked", "app_fliggy", "需登录（119 分钟内不再重试）")
    snap = dg.snapshot()
    assert "app_risk_blocked" in snap
    assert snap["app_risk_blocked"]["n"] == 1


def test_panel_has_label_and_advice():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "app_risk_blocked:'App 风控'" in w
    assert "改用同名的浏览器通路" in w
