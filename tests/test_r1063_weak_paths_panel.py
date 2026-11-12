# -*- coding: utf-8 -*-
"""r1063 T196-T198：通路弱环上屏（判据在 Python，前端只画）。

背景：objective 要求"每个链路可观测"——面板此前只有渠道级状态，
哪条**通路**在拖后腿要靠 `python -m core.channel_matrix` 才知道。

两级翻车都记在这里（都是靠真机验证才发现的）：
1. 前端自己判"成功率<0.9 就算弱环" → 把 `tuniu·PC 0%/45` 显示成弱环，
   而它其实是 `unsupported`（按设计不查 >30 天的 PC）——让用户去修不存在的东西；
2. 判据搬到 Python 后仍是空：因为钩子接在 `pac.snapshot()` 之后，
   而 `channels[].paths` 是**后面"与路径账合并"**才填进去的 → 空 paths。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.advise import weak_paths  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pacing(plat, path, rate, n, why=""):
    return {"channels": {plat: {"paths": {path: {
        "rate": rate, "attempts": n, "why": why}}}}}


def test_weak_path_reported():
    out = weak_paths(_pacing("tuniu", "H5/API", 0.73, 62,
                             "m.tuniu.com 列表接口"))
    assert out and out[0]["path"] == "H5/API", out
    assert out[0]["attempts"] == 62


def test_supported_but_flaky_counts_even_if_why_mentions_skip():
    """真机反例：73% 的通路 why 里带渠道级提示「>30 天的 PC 不查」，
    以前被当成能力边界剔除，导致面板一条弱环都不显示。"""
    out = weak_paths(_pacing("tuniu", "H5/API", 0.73, 62,
                             "距今天 >30 天的 PC 不查（风控），远日期走 H5/API"))
    assert out, "有产出的通路不可能是能力边界"


def test_unsupported_zero_rate_is_not_weak():
    out = weak_paths(_pacing("tuniu", "PC", 0.0, 45,
                             "距今天 >30 天的 PC 不查（风控）"))
    assert out == [], "按设计不查的通路不该让用户去修"


def test_high_rate_and_small_sample_are_ignored():
    assert weak_paths(_pacing("ctrip", "PC", 0.96, 27)) == []
    assert weak_paths(_pacing("ctrip", "PC", 0.2, 2)) == []


def test_sorted_by_loss_and_capped():
    p = {"channels": {
        "a": {"paths": {"p": {"rate": 0.5, "attempts": 10}}},
        "b": {"paths": {"q": {"rate": 0.1, "attempts": 100}}},
        "c": {"paths": {"r": {"rate": 0.8, "attempts": 50}}},
    }}
    out = weak_paths(p, limit=2)
    assert [x["plat"] for x in out] == ["b", "c"], out


def test_webui_hook_runs_after_paths_merge():
    """钩子必须在 paths 合并之后——否则 weak_paths 永远为空（T198 实测）。"""
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i_resp = w.index("data[\"weak_paths\"] = _wp2(data)")
    i_json = w.index("self._json(data)", i_resp)
    assert i_resp < i_json, "weak_paths 必须在响应之前算"
    # 老的错误位置不该再算 weak_paths
    seg = w[w.index("data[\"advice_top\"] = _tfp(data)"):][:400]
    assert "_wp(data)" not in seg, "旧钩子（paths 未合并）不该再算 weak_paths"
    # 前端只画，不再自己判
    assert "j.weak_paths" in w


def test_same_channel_does_not_monopolize_slots():
    """同一渠道的多条通路不该占满名额（真机：App 两条把 tuniu 挤没了）。"""
    p = {"channels": {"app_x": {"paths": {
        "a": {"rate": 0.0, "attempts": 200},
        "b": {"rate": 0.0, "attempts": 150},
    }}, "tuniu": {"paths": {"H5/API": {"rate": 0.74, "attempts": 66}}}}}
    out = weak_paths(p, limit=3)
    plats = [x["plat"] for x in out]
    assert plats.count("app_x") == 1, out
    assert "tuniu" in plats, "别的渠道被同一家挤掉了：%s" % out
