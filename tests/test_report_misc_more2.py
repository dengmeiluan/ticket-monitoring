# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r389_gh_breaker.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import logging
import os
import report
import sys


# ---- merged from tests/test_r389_gh_breaker.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r389")
_IH = {"provider": "ghimg", "repo": "o/r", "ghtoken": "x"}


def _reset():
    report._GH_FAIL_UNTIL = 0.0


def test_failure_opens_breaker_and_skips_next_uploads(monkeypatch):
    calls = {"n": 0}

    def fake_upload(png, ih, logger):
        calls["n"] += 1
        return None                      # 恒失败（模拟 TLS EOF）

    monkeypatch.setattr(report, "upload_ghimg", fake_upload)
    _reset()
    # 一轮里的多张图：第一张失败打开熔断，后面直接跳过
    for i in range(4):
        assert report.upload_chart("x%d.png" % i, {}, _LOG, ih=_IH) is None
    assert calls["n"] == 1, "熔断后同轮其余图不得再撞网络（实际 %d）" % calls["n"]
    assert report._GH_FAIL_UNTIL > 0


def test_breaker_is_time_bounded(monkeypatch):
    calls = {"n": 0}

    def fake_upload(png, ih, logger):
        calls["n"] += 1
        return None

    monkeypatch.setattr(report, "upload_ghimg", fake_upload)
    _reset()
    report.upload_chart("a.png", {}, _LOG, ih=_IH)
    assert calls["n"] == 1
    # 熔断窗口过去后应重新尝试
    report._GH_FAIL_UNTIL = 9999999999.0
    assert report.upload_chart("b.png", {}, _LOG, ih=_IH) is None
    assert calls["n"] == 1, "窗口内不得尝试"
    report._GH_FAIL_UNTIL = 0.0
    report.upload_chart("c.png", {}, _LOG, ih=_IH)
    assert calls["n"] == 2, "窗口过后应恢复尝试"


def test_success_clears_breaker(monkeypatch):
    def ok_upload(png, ih, logger):
        return "https://cdn.jsdelivr.net/gh/o/r@main/x.png"

    monkeypatch.setattr(report, "upload_ghimg", ok_upload)
    report._GH_FAIL_UNTIL = 12345.0
    url = report.upload_chart("a.png", {}, _LOG, ih=_IH)
    assert url and report._GH_FAIL_UNTIL == 0.0, "成功必须清零熔断"


def test_breaker_does_not_affect_other_providers(monkeypatch):
    report._GH_FAIL_UNTIL = 9999999999.0
    called = {"n": 0}

    def fake_smms(png, token, logger):
        called["n"] += 1
        return "https://s/x.png"

    monkeypatch.setattr(report, "upload_smms", fake_smms)
    url = report.upload_chart("a.png", {}, _LOG,
                              ih={"provider": "smms", "token": "t"})
    assert url and called["n"] == 1, "熔断只作用于 ghimg"
