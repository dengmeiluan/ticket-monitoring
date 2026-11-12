# -*- coding: utf-8 -*-
"""r1063 T56：挑战族**最后 4 处**读点归位（渠道覆盖真的生效）。

上一轮（T42）修了 `slider_attempt.auto` / `slider_guard.daily_cap|max_fails` /
`captcha_solve.arithmetic|text|click`。这轮扫出剩下的：

| 参数 | 原来 | 现在 |
|---|---|---|
| `slider_attempt.single_shot` | 两处裸读 `sec.get("single_shot")` | `_pval(...)` → 渠道覆盖生效 |
| `captcha_solve.ocr_scale` | 裸读 `_cfg(config).get("ocr_scale")` | `_pval(...)` |
| `captcha_solve.auto_verify` | `main` 读**顶层 cfg**（只能全局） | 按 `plat` 走参数层，无意见才回落 cfg |
| `slider_attempt.enabled` | **完全没有读点**（界面上关了不生效） | `should_attempt()` 开头先问族开关 |
| `captcha_solve.enabled` | 只在 `pacing` 里问 | `attempt()` 入口也认（直接调用方也受约束） |

外加一条**回归门禁**：挑战族里凡声明了 `channel` 作用域的参数，读点不许是"裸读"。
"""
import io
import os
import re

import pytest

from core import strategy_params as sp
from core.strategy_contract import STRATEGIES
from crawlers import slider as sl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDER = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                 encoding="utf-8").read()
CAPTCHA = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_family_switch_actually_gates_slider_attempt():
    """`slider_attempt.enabled` 以前**没有读点**，界面上关了也不生效。"""
    sp.set_config({})
    assert sl.should_attempt("ctrip", {"slider": {"auto": "auto"}})[0] is True
    sp.set_config({"crawler": {"strategy_enabled": {
        "slider_attempt": False}}})
    ok, why = sl.should_attempt("ctrip", {"slider": {"auto": "auto"}})
    assert ok is False and "策略族开关" in why, (ok, why)


def test_family_switch_honours_channel_override():
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"slider_attempt.enabled": False}}}})
    assert sl.should_attempt("fliggy",
                             {"slider": {"auto": "auto"}})[0] is False
    assert sl.should_attempt("ctrip",
                             {"slider": {"auto": "auto"}})[0] is True


def test_single_shot_and_ocr_scale_go_through_the_param_layer():
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"slider_attempt.single_shot": True,
                  "captcha_solve.ocr_scale": 2.0}}}})
    assert sp.resolve("slider_attempt.single_shot", plat="ctrip").value is True
    assert sp.resolve("slider_attempt.single_shot",
                      plat="fliggy").value is False
    assert float(sp.resolve("captcha_solve.ocr_scale",
                            plat="ctrip").value) == 2.0


def test_no_raw_leaf_reads_left_in_the_challenge_family():
    """门禁：挑战族里声明了 channel 的参数，读点不许是裸读。

    裸读的定义：`sec.get("<leaf>")` / `_cfg(...).get("<leaf>")` 而同一行没有
    `_pval(` / `resolve(` 包装。`auto` 这类"参数层无意见时的回落"允许出现，
    但必须出现在 `_pval(...)` 的实参里。
    """
    fam = {"slider_attempt", "slider_guard", "captcha_solve"}
    files = {"slider.py": SLIDER, "captcha.py": CAPTCHA}
    bad = []
    for s in STRATEGIES:
        if s.id not in fam:
            continue
        for p in s.params:
            leaf = p.cfg.rsplit(".", 1)[-1]
            if leaf in ("enabled",):
                continue          # 族开关走 switch_on()，形式不同
            for name, src in files.items():
                pat = (r'(?:sec|_cfg\([^)]*\))\.get\("' + re.escape(leaf)
                       + r'"\)')
                for m in re.finditer(pat, src):
                    ln = src[:m.start()].count("\n")
                    lines = src.splitlines()
                    # 参数可能跨行传：本行 + 前 3 行里出现包装调用就算包住
                    win = "\n".join(lines[max(0, ln - 3):ln + 1])
                    if ("_pval(" not in win and "resolve(" not in win
                            and "switch_on(" not in win):
                        bad.append("%s:%s %s"
                                   % (name, p.pid, lines[ln].strip()[:70]))
    assert not bad, "还有裸读（渠道覆盖会被忽略）：\n" + "\n".join(bad)


def test_auto_verify_is_resolved_per_channel_in_main():
    assert "captcha_solve.auto_verify" in MAIN
    i = MAIN.index("captcha_solve.auto_verify")
    seg = MAIN[max(0, i - 500):i + 500]
    assert 'plat=c.name' in seg, "没有按渠道求值"
    assert "!= \"default\"" in seg or "!=" in seg, "应只在参数层有意见时覆盖 cfg"


def test_captcha_enabled_is_read_at_the_entry_too():
    assert 'captcha_solve.enabled' in CAPTCHA, "attempt() 入口没问族开关"
