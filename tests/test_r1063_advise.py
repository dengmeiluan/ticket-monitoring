# -*- coding: utf-8 -*-
"""r1063 T163：`python -m core.advise` —— 把五把尺子合成"现在最该做什么"。

objective 里有"**一切可建议 / 一切可意图理解**"。尺子已经很多
（matrix / trend / dates / login / slider + 降级项），但要人自己拼。本模块
**只读**地把现场事实翻成带命令的建议，按"能不能立刻换来数据"排序。

三条判据是踩出来的：
1. **能力边界不算被拦**（`tuniu PC 远日期不查`、`ctrip 日历 机场级不回填`）——
   首版把它们列进"0 成功率"，会把人引去清墙/换 IP，全是白费；
2. **样本太少不算结论**（attempts < 3 跳过）；
3. **已永久停服/退役的渠道不算"今天被拦"**（复用 `setup_check._is_retired`，
   不另写一份判据）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import advise as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_need_login_picks_only_flagged_slots():
    slots = {
        "ctrip": {"needs_login": False, "surface_label": "PC"},
        "tuniu": {"needs_login": True, "surface_label": "PC",
                  "login_url": "https://passport.tuniu.com/login"},
        "tuniu_h5": {"needs_login": True, "surface_label": "H5"},
    }
    got = A._need_login(slots)
    assert [x["slot"] for x in got] == ["tuniu", "tuniu_h5"]


def _pacing(paths, plat="ctrip", needs_login=False):
    return {"channels": {plat: {"needs_login": needs_login, "paths": paths}}}


def test_boundary_is_not_treated_as_blocked():
    """`不查/不回填/视野` 这类是能力边界，不该进建议。"""
    p = _pacing({"PC": {"rate": 0.0, "attempts": 9,
                        "why": "距今天 >30 天的 PC 不查（风控）"}})
    assert A._blocked_channels(p) == []


def test_low_sample_is_ignored():
    p = _pacing({"PC": {"rate": 0.0, "attempts": 1, "why": "超时"}})
    assert A._blocked_channels(p) == []


def test_real_block_is_reported():
    p = _pacing({"H5": {"rate": 0.0, "attempts": 10,
                        "why": "原站返回访问被拒绝（安全页）"}})
    got = A._blocked_channels(p)
    assert got and got[0]["plat"] == "ctrip"
    assert "0 成功率" in got[0]["why"]


def test_advise_ranks_login_first():
    rep = {"ok": True, "port": 8765,
           "pacing": _pacing({"PC": {"rate": 1.0, "attempts": 5, "why": "ok"}}),
           "slots": {"tuniu": {"needs_login": True, "surface_label": "PC"}}}
    out = A.advise(rep)
    assert out["ok"] and out["items"]
    assert out["items"][0]["kind"] == "login"
    assert "channel_matrix --login" in out["items"][0]["cmd"]


def test_text_has_commands_and_disclaimer():
    rep = A.advise({"ok": True, "port": 8765, "pacing": {},
                    "slots": {}})
    txt = A._text(rep)
    assert "现在最该做的" in txt
    assert "只读诊断" in txt


def test_module_is_read_only():
    """诊断不许改状态：不写配置、不发 POST、不动登录。"""
    src = io.open(os.path.join(ROOT, "core", "advise.py"),
                  encoding="utf-8").read()
    for bad in ("set_config(", "strategy_overrides", "method=\"POST\"",
                "login_sessions", "save_session"):
        assert bad not in src, "advise 必须是只读：%s" % bad
