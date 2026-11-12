# -*- coding: utf-8 -*-
"""r1063 T24：换道成效必须能在界面看到（否则「可统计」只是后端一个数）。

数据从 `/api/pacing` 的 `failover` 来，源头是 `pacing.snapshot()`——与健康卡的
其它读数同源（一切统一状态）。没有换道时整段为空：不占位、不改行高（健康页的
几何门禁很紧）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_health_panel_renders_failover_stats():
    assert "const _fostats=(()=>{" in SRC
    assert "+_stats+_rail+_kv+_fostats" in SRC, "换道成效没进右栏"


def test_failover_line_is_empty_when_nothing_happened():
    """没有换道就返回空串——不占位，几何零变化。"""
    seg = SRC[SRC.index("const _fostats=(()=>{"):][:900]
    assert "if(!pre&&!sw&&!rows)return '';" in seg


def test_failover_line_names_zero_recovery():
    """回采 0 条要说明白（App 通路可能也被拦），不能只显示「换道 1 次」。"""
    # 窗口放宽：T50 起这段里还塞了每家渠道的判据输入（只挂在 title 上，
    # 可见文案不变）
    seg = SRC[SRC.index("const _fostats=(()=>{"):][:3200]
    assert "回采 0 条" in seg


def test_snapshot_exposes_failover_counters():
    from core.pacing import Pacing

    p = Pacing({})
    p.note_failover(preload=2, note="x")
    p.note_failover(switched=1, rows=7)
    f = p.snapshot()["failover"]
    assert f["preloads"] == 2 and f["switches"] == 1 and f["rows"] == 7, f
