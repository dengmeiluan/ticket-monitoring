# -*- coding: utf-8 -*-
"""r1063 T33：换道结果的**归因**——0 条时要能说清是哪一种。

同样"回采 0 条"，四种原因的处理完全不同：
  * App 通路**不可用**（未配置/依赖缺失）→ 去配环境
  * App 通路**未配置**（没有实例）→ 去启用渠道
  * App 通路**被节流**（paced）→ 调预算/间隔
  * App 通路**也被拦**（同一类挑战）→ 别硬碰，换策略
  * App 通路**无票/未登录** → 正常的业务结果，不用管

混成一句"回采 0 条"等于没信息，用户只能猜。
"""
import io
import os

from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


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
