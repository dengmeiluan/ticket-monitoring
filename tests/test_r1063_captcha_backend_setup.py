# -*- coding: utf-8 -*-
"""r1063 T191-T192：识别后端（ddddocr）纳入自检 + `apply_fix` 按提示装。

背景：
* 用户早前问"简单滑块/文字/算数能不能自动过、Python 有没有现成框架"——`ddddocr`
  就是那个框架；但它在 `requirements.txt` 里是**注释掉的可选项**，自检不查、
  一键引导也就装不上，能力等于"有代码没后端"。
* 更糟的是 `apply_fix` 老实现里 `cmd.startswith("pip install")` **一律**跑
  `pip install -r requirements.txt`——提示"装 ddddocr"时实际什么都没装，
  提示与动作对不上。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import setup_check as SC  # noqa: E402

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
