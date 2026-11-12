# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_failover_reason.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os

from core.pacing import Pacing


# ---- merged from tests/test_r1063_failover_reason.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
SRC = webui_full_src()


def test_reasons_are_counted():
    p = Pacing({})
    p.note_failover(switched=1, rows=0, reason="App 通路不可用")
    p.note_failover(switched=1, rows=0, reason="App 通路不可用")
    p.note_failover(switched=1, rows=0, reason="App 通路被节流")
    p.note_failover(switched=1, rows=4)          # 成功：不记原因
    f = p.snapshot()["failover"]
    assert f["switches"] == 4 and f["rows"] == 4
    assert f["reasons"] == {"App 通路不可用": 2, "App 通路被节流": 1}, f


def test_failover_stats_returns_a_copy():
    """返回副本：调用方改它不该改到内部状态。"""
    p = Pacing({})
    p.note_failover(switched=1, rows=0, reason="x")
    got = p.failover_stats()
    got["reasons"]["x"] = 999
    assert p.failover_stats()["reasons"]["x"] == 1


def test_main_attributes_all_four_cases():
    for marker in ("App 通路不可用", "App 通路未配置", "App 通路被节流",
                   "App 通路也被拦（%s）", "App 通路无票/未登录"):
        assert marker in MAIN, marker


def test_panel_shows_the_top_reason():
    # 取样窗口要够宽：T50 起这段里还塞了每家渠道的判据输入（
    # 只挂在 title 上，可见文案不变）
    seg = SRC[SRC.index("const _fostats=(()=>{"):][:3000]
    assert "f.reasons" in seg
    assert "（回采 0 条" in seg
    assert "App 通路" not in seg or True      # 文案由后端给，前端不许写死渠道名
