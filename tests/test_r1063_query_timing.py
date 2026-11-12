# -*- coding: utf-8 -*-
"""r1063 T27：耗时构成（墙钟 / 有效工作 / 空等）——提速必须先有这两个数。

一轮慢有两种完全不同的原因：
  * **活多**：有效工作接近墙钟 → 要提并发或砍请求；
  * **在等**：栅栏模型下最慢的那家决定整条查询时长 → 要打破栅栏（跨查询流水线）。
只报"总时长"分不出这两种，照着优化就是猜。
"""
import io
import os

from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def test_pacing_accumulates_and_derives_idle_ratio():
    p = Pacing({})
    p.note_query_timing(wall=10.0, work=4.0, tasks=6, paced=2)
    t = p.snapshot()["timing"]
    assert (t["n"], t["tasks"], t["paced"]) == (1, 6, 2)
    assert t["wall"] == 10.0 and t["work"] == 4.0
    assert t["idle_ratio"] == 0.6, t        # 60% 的时间在等

    p.note_query_timing(wall=10.0, work=9.0, tasks=3, paced=0)
    t2 = p.timing_stats()
    assert t2["n"] == 2
    assert t2["idle_ratio"] == 0.35, t2     # (20-13)/20


def test_no_samples_means_no_ratio():
    assert Pacing({}).snapshot()["timing"]["idle_ratio"] is None


def test_bad_values_are_ignored_not_crashing():
    p = Pacing({})
    p.note_query_timing(wall="x", work=None)
    p.note_query_timing(wall=-1, work=2)
    assert p.timing_stats()["n"] == 0


def test_main_records_each_task_and_query():
    """接线钉子：任务耗时按**查询键**登记，收尾按同一键取走。"""
    assert "_LAT_LOCK" in MAIN and "_LAT.append(" in MAIN
    assert "(str(fc_), str(tc_), str(d_))" in MAIN, "登记没带查询键"
    assert "_rec[0] == _qkey" in MAIN, "收尾没按查询键取"
    assert "note_query_timing(" in MAIN
    # 节流跳过也要记（它占墙钟但不产数）
    assert "0.0, False" in MAIN


def test_health_panel_renders_timing_line():
    assert "const _timeline=(()=>{" in SRC
    # 不再钉"紧邻"：中间可能插别的读数行（T60 插了 `_degradeLine`）。
    # 守的仍是「耗时行进了右栏，且在换道成效之后」。
    i_f = SRC.index("+_fostats")
    i_t = SRC.index("+_timeline")
    assert i_t > i_f, "耗时行没进右栏（或顺序反了）"
    assert i_t - i_f < 200, "耗时行离右栏太远，可能没拼接进去"
    seg = SRC[SRC.index("const _timeline=(()=>{"):][:1100]
    assert "本轮耗时" in seg and "空等" in seg
    assert "if(!n)return '';" in seg, "没有样本时应当不占位"


# ---------------- 限速等待 vs 真实抓取（r1063 T29） ----------------

def test_gate_wait_is_split_from_real_fetch():
    """有效工作里**有多少在等我方令牌桶**必须单列。

    数据告诉我们 qunar 单查询 82.8s 是最大头；但 82.8s 里是"在等限速"还是
    "真的在抓"，决定该调限速还是改抓取——不分开两种可能都成立。
    """
    p = Pacing({})
    p.note_query_timing(wall=20.0, work=12.0, tasks=5, gate=7.5)
    t = p.snapshot()["timing"]
    assert t["gate"] == 7.5
    assert t["fetch"] == 4.5, t          # 抓取 = 有效工作 - 等待
    assert t["gate_ratio"] == 0.625, t   # 等待占有效工作的 62.5%
    assert t["idle_ratio"] == 0.4


def test_gate_ratio_none_without_samples():
    assert Pacing({}).timing_stats()["gate_ratio"] is None


def test_main_measures_gate_before_the_channel_slot():
    """闸门必须量在 `channel_slot` **之前**：锁内的等待是渠道串行，不是限速。"""
    i_gate = MAIN.index("_gate_s = time.time() - _t_task0")
    i_slot = MAIN.index("with channel_slot(c.name):", i_gate - 400)
    assert i_gate < i_slot, "闸门计时刻在锁内了（会把抓取时间算成等待）"
    assert "float(_gate_s or 0.0)" in MAIN


def test_panel_mentions_gate_share():
    """面板必须把"其中有多少是等我方限速"说出来。

    T53 起措辞是**闸门等待**：它（占墙钟的比例，全局）与行内「等 Ns」
    （单渠道等待秒数）不是同一个数，术语必须能区分。
    """
    seg = SRC[SRC.index("const _timeline=(()=>{"):][:1800]
    assert "其中闸门等待" in seg
    assert "限速等待" not in seg, "「限速等待」会与行内「等 Ns」混淆"
