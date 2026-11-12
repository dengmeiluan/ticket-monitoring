# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_pace_row_no_extra_line.py
- tests/test_r517_health_empty_state_stalled.py
- tests/test_r518_health_stale_banner.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import sys
import threading

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


# ---- merged from tests/test_webui_health_more.py ----

# ---- merged from tests/test_r1063_pace_row_no_extra_line.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = {
    "ok": True, "quiet": {}, "last_round": {"sent": 12, "paced": 5},
    "channels": {"fliggy": {"state": "ok",
                            "advice": {"state": "path_degraded",
                                       "action": "route", "severity": "auto",
                                       "eta_s": 0, "hint": "国际 H5 有效率偏低"}}},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {}, "cfg": {},
}
PATHS = {"fliggy": {"paths": {"H5": {"attempts": 32, "rate": 0.25}},
                    "retired_paths": [],
                    "scopes": {"intl": {"attempts": 32, "rate": 0.25,
                                        "query_attempts": 12,
                                        "query_rate": 0.42}}}}
HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": PATHS, "diag": [], "coverage": {}}


def _with_my_fields(pacing):
    out = json.loads(json.dumps(pacing))
    ch = out["channels"]["fliggy"]
    ch["resets"] = 2
    ch["waited_s"] = 210.0
    ch["health_paths"] = {"intl/H5/API": {"penalty": 2}}
    ch["sr"] = {"fails": 3, "kind": "captcha", "day": 1,
                "why": "连续被拦 3 次"}
    return out








# ---- merged from tests/test_r517_health_empty_state_stalled.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_health_empty_state_mentions_stalled_collection():
    w = _w()
    i = w.index("function renderHealth(j)")
    seg = w[i:i + 1500]
    assert "last_seen_at" in seg, "健康卡空态没有使用最近采集时刻"
    assert "采集已停" in seg, "空态没有「采集停了」这一支"
    # 原来那句必须仍在（新装用户看到的是它，不能被替换掉）
    assert "完成一轮采集后" in seg, "「从未采集」的提示被删掉了"
    # 停摆分支要给出可执行方向，而不是只报一个时间
    assert "检查监控进程" in seg, "停摆空态没有给出下一步"


def test_health_payload_supplies_last_seen_at():
    w = _w()
    i = w.index('elif self.path == "/api/health":')
    seg = w[i:i + 3000]
    assert 'last_seen_at' in seg, "/api/health 没有下发最近采集时刻"
    assert "MAX(fetched_at)" in seg, "没有查全表最近样本"


def test_stalled_branch_needs_a_real_threshold():
    """阈值必须在场且是 6 小时（360 分钟）——与节流行同一口径。"""
    w = _w()
    i = w.index("function renderHealth(j)")
    seg = w[i:i + 1500]
    assert ">=360" in seg, "空态停摆没有 6 小时阈值（会与节流行口径不一致）"




# ---- merged from tests/test_r518_health_stale_banner.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_stale_banner_is_built_once_per_render():
    """每轮轮询都会重跑，旧标记必须先清掉——否则同屏叠出好几个。"""
    w = _w()
    i = w.index("采集已停 '+Math.floor(_m2/60)")
    seg = w[max(0, i - 900):i + 200]
    assert "querySelectorAll('#hroundcnt ~ .hstale').forEach(e=>e.remove())" in seg, \
        "没有清理上一轮插入的停摆标记（会越叠越多）"


def test_stale_banner_uses_tokens_not_new_colors():
    w = _w()
    i = w.index("#healthcard .hstale{")
    seg = w[i:i + 320]
    assert "var(--warn-deep)" in seg and "var(--r-amber-soft)" in seg, \
        "停摆标记没有走全站语义色令牌"
    assert "font-size:11px" in seg, "字号不在阶上"


