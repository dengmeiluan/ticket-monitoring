# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_captcha_backend_setup.py
- tests/test_r1063_challenge_readpoints.py
- tests/test_r1063_challenge_scope.py
- tests/test_r1063_click_challenge.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import pytest
import re
import sys

from core import setup_check as SC, strategy_params as sp
from core.strategy_contract import STRATEGIES
from crawlers import captcha, captcha as cp, slider as sl


# ---- merged from tests/test_r1063_captcha_backend_setup.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_check_captcha_backend_exists_and_is_ok_here():
    """本机已装 ddddocr → 该行必须是 OK（且不是 BAD：不装也能采）。"""
    row = SC.check_captcha_backend()
    assert row["name"] == "识别后端"
    assert row["level"] in (SC.OK, SC.WARN)


def test_check_captcha_backend_declares_safe_fix():
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    i = src.index("def check_captcha_backend")
    seg = src[i:i + 900]
    assert 'pip install ddddocr' in seg, "缺自动安装提示"
    assert 'action="install_deps"' in seg, "必须能被一键引导自动修"


def test_apply_fix_installs_named_package(monkeypatch):
    """`pip install ddddocr` 必须装 ddddocr，不能变成 requirements 全量。"""
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(SC.subprocess, "run", fake_run)
    ok = SC.apply_fix({"fix": "pip install ddddocr", "action": "install_deps"},
                      echo=lambda *a, **k: None)
    assert ok is True
    assert "ddddocr" in captured["args"], captured
    assert "-r" not in captured["args"], "不该退化成 requirements 全量安装"


def test_apply_fix_keeps_requirements_path(monkeypatch):
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(SC.subprocess, "run", fake_run)
    SC.apply_fix({"fix": "pip install -r requirements.txt",
                  "action": "install_deps"}, echo=lambda *a, **k: None)
    assert "-r" in captured["args"], captured
    assert any("requirements.txt" in str(x) for x in captured["args"])


# ---- merged from tests/test_r1063_challenge_readpoints.py ----

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


# ---- merged from tests/test_r1063_challenge_scope.py ----

@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def test_channel_override_turns_slider_off_for_one_channel_only():
    """渠道覆盖优先于调用方 cfg（cfg 显式给 on，覆盖给 off）。"""
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"slider_attempt.auto": "off"}}}})
    ok_f, why_f = sl.should_attempt("fliggy", {})
    ok_c, why_c = sl.should_attempt("ctrip", {"slider": {"auto": "auto"}})
    assert ok_f is False, (ok_f, why_f)
    assert ok_c is True, (ok_c, why_c)
    # 文案不许写死键名（开关可能来自渠道覆盖）
    assert "crawler.slider.auto" not in why_f, why_f


def test_caller_cfg_still_wins_when_provider_has_no_opinion():
    """没有 `set_config`（离线/单测）时，调用方传的 cfg 必须照旧生效。"""
    assert sl.should_attempt("ctrip", {"slider": {"auto": False}})[0] is False
    assert sl.should_attempt("ctrip", {"slider": {"auto": "auto"}})[0] is True


def test_daily_cap_follows_the_channel_override():
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"slider_guard.daily_cap": 1}}}})
    # cap=1：用掉一次之后就不许再试（账本写到 tmp）
    import tempfile
    d = tempfile.mkdtemp()
    sl.note_result("ctrip", False, {}, user_data_dir=d, profile="ctrip")
    ok, why = sl.should_attempt("ctrip", {"slider": {"auto": "auto"}},
                                user_data_dir=d, profile="ctrip")
    assert ok is False and "上限" in why, (ok, why)
    sp.invalidate()


def test_captcha_click_switch_follows_the_channel_override(monkeypatch):
    monkeypatch.setattr(cp, "_det_backend", lambda: object())
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"captcha_solve.click": False}}}})
    assert cp._pval("captcha_solve.click", "fliggy",
                    True) is False
    assert cp._pval("captcha_solve.click", "ctrip", True) is True


def test_contract_declares_channel_scope_for_captcha_solve():
    """声明必须与读点一致：读点已按 plat 求值，scope 就得有 channel。"""
    from core.strategy_contract import STRATEGIES

    s = [x for x in STRATEGIES if x.id == "captcha_solve"][0]
    assert "channel" in tuple(s.scope), s.scope


def test_param_layer_priority_is_documented_in_code():
    """优先级写进了文档串——这条守的是"下一个人不会再把它改错"。"""
    import io
    import os

    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "slider.py"),
        encoding="utf-8").read()
    seg = src[src.index("def _pval("):][:700]
    assert "source" in seg and "default" in seg


# ---- merged from tests/test_r1063_click_challenge.py ----

# ---------------- 降级：没有检测后端时不假装可解 ----------------

def test_click_is_solvable_only_with_a_detector(monkeypatch):
    monkeypatch.setattr(captcha, "_det_backend", lambda: None)
    k = captcha.classify_kind("请按顺序点击图中的汉字", "请按顺序点击")
    assert k.name == "click"
    assert k.solvable is False, "没有检测后端却声称可解"
    assert "缺检测后端" in "、".join(k.reasons), k.reasons

    monkeypatch.setattr(captcha, "_det_backend", lambda: object())
    k2 = captcha.classify_kind("请按顺序点击图中的汉字", "请按顺序点击")
    assert k2.solvable is True, "有检测后端却不肯尝试（限制性设计没清干净）"
    assert "检测后端可用" in "、".join(k2.reasons), k2.reasons


def test_detect_targets_without_backend_returns_empty(monkeypatch):
    monkeypatch.setattr(captcha, "_det_backend", lambda: None)
    assert captcha.detect_targets(b"\x89PNG...") == [], \
        "没有后端时必须返回空（宁可不动，也不许瞎点）"


def test_detect_targets_sorts_by_reading_order(monkeypatch):
    class _Det:
        def detection(self, png):
            # 故意打乱：右、左、中
            return [[300, 10, 340, 50], [10, 10, 50, 50], [150, 10, 190, 50]]

    monkeypatch.setattr(captcha, "_det_backend", lambda: _Det())
    pts = captcha.detect_targets(b"x")
    assert [round(p[0]) for p in pts] == [30, 170, 320], pts


def test_detect_targets_respects_expected_count(monkeypatch):
    class _Det:
        def detection(self, png):
            return [[10, 10, 50, 50], [150, 10, 190, 50], [300, 10, 340, 50]]

    monkeypatch.setattr(captcha, "_det_backend", lambda: _Det())
    assert len(captcha.detect_targets(b"x", expect=2)) == 2


# ---------------- 可达性：点击分支必须早于「找输入框」 ----------------

def test_click_branch_runs_before_the_answer_box_lookup():
    import io
    from pathlib import Path

    src = io.open(os.path.join(Path(__file__).resolve().parents[1],
                               "crawlers", "captcha.py"),
                  encoding="utf-8").read()
    body = src[src.index("def attempt(page"):]
    i_click = body.index('if k.name == "click":')
    i_box = body.index("box = _first(page, _INPUT_SELECTORS)")
    assert i_click < i_box, (
        "点击分支排在『找答案输入框』之后：点选题没有 input，会先被挡掉")


# ---------------- 文案：限制性表述已清掉 ----------------

BANNED = ("交给人工", "交人工", "按性价比", "越算越像机器", "不必投入")


def test_no_restrictive_wording_left_in_challenge_modules():
    import io

    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    bad = []
    for name in ("crawlers/slider.py", "crawlers/captcha.py",
                 "crawlers/challenge.py", "config.example.yaml"):
        txt = io.open(os.path.join(root, name), encoding="utf-8").read()
        for w in BANNED:
            if w in txt:
                bad.append("%s：%s" % (name, w))
    assert not bad, "限制性文案没清干净：%s" % "、".join(bad)


def test_behavior_type_is_stated_as_scope_decision():
    """行为型不自动解要写成「范围决定」，而不是含糊的「暂不支持」。"""
    import io

    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    cfg = io.open(os.path.join(root, "config.example.yaml"),
                  encoding="utf-8").read()
    assert "范围决定" in cfg
    assert "真机" in cfg, "没给出提高采集率的替代方向"
