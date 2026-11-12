# -*- coding: utf-8 -*-
"""r1063 T155：`channel_matrix --slider` —— 验证尝试战果可见。

背景：`crawlers/slider.py` 早就实现**简单滑块/算数/文字**类验证的自动尝试
（缺口识别含 `ddddocr`、轨迹模拟、每日上限、连败 2 次拉黑 7 天），
但战果只写在 `user_data/<profile>/slider_ledger.json`，**面板和命令行都看不到**。

这跟"一切可统计 / 一切可区分"不符，所以补一个只读视图。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channel_matrix as CM  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mk(tmp_path, plat="fliggy", fails=1, k_ok=2, k_fail=1, blocked=0):
    import time
    d = tmp_path / "fliggy"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        plat: {
            "tries": k_ok + k_fail, "day_used": 3, "fails": fails,
            "blocked_until": (time.time() + blocked) if blocked else 0,
            "last_ok": 1700000000,
            "by_kind": {"slider": {"tries": k_ok + k_fail, "ok": k_ok,
                                   "fail": k_fail}},
        }
    }
    (d / "slider_ledger.json").write_text(json.dumps(rec), encoding="utf-8")


def test_slider_stats_reads_ledger(tmp_path):
    _mk(tmp_path)
    rep = CM.slider_stats(str(tmp_path))
    assert rep["ok"] and len(rep["rows"]) == 1
    r = rep["rows"][0]
    assert r["plat"] == "fliggy" and r["profile"] == "fliggy"
    assert r["tries"] == 3 and r["today"] == 3 and r["fails"] == 1
    assert "滑块 2/3" in r["kinds"], r["kinds"]


def test_slider_text_shows_cooldown(tmp_path):
    _mk(tmp_path, blocked=600)
    rep = CM.slider_stats(str(tmp_path))
    txt = CM._slider_text(rep)
    assert "分钟" in txt, txt
    assert "滑块" in txt


def test_slider_text_empty_is_explanatory():
    txt = CM._slider_text({"ok": True, "rows": [], "root": "user_data"})
    assert "没有验证尝试记录" in txt
    assert "强人机验证" in txt, "要说明强验证不硬刚，避免误以为没实现"


def test_kind_cn_covers_all_kinds_used_by_slider():
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    for kind in ("slider", "arithmetic", "text"):
        assert kind in CM.SLIDER_KIND_CN, kind
        assert kind in src, "slider.py 里用的类别必须在中文表里有名字：%s" % kind


def test_cli_has_slider_flag():
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--slider" in src and "def slider_stats(" in src
