# -*- coding: utf-8 -*-
"""r1063 T274：距离建议阈值可配置（一切可配置 / 零配置也能跑）+ 配置快照同步。

两件事：
1. `crawler.advice_distance_min_n` / `advice_distance_gap` 能调阈值
   （不配＝代码默认 6 / 0.25）。真机验证：写成 200 → 建议消失；还原 → 回来。
2. **面板保存后必须同步 `_State.cfg`**。此前 `/api/config` 只调 `reload_cb()`
   更新主程序配置，而 `_effective_crawler_config()` 读的是启动快照——
   于是**任何 crawler 选项在面板里改完都不生效**（它的 docstring 写"stay live"
   是空头承诺）。直接改文件同样不生效，直到重启。
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.advise import distance_advice  # noqa: E402


def _w():
    import io
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _db(tmp_path, rows, name="a.db"):
    p = os.path.join(str(tmp_path), name)
    c = sqlite3.connect(p)
    c.execute("create table fetch_paths(platform text, depart_date text, "
              "path_status text, fetched_at text)")
    for plat, dd, st, n in rows:
        for _ in range(n):
            c.execute("insert into fetch_paths values(?,?,?,datetime('now'))",
                      (plat, dd, st))
    c.commit()
    c.close()
    return p


def _d(offset):
    import datetime as dt
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


def test_config_keys_are_read_and_clamped():
    w = _w()
    assert 'advice_distance_min_n' in w and 'advice_distance_gap' in w
    i = w.index('data["distance_advice"]')
    seg = w[i - 700:i + 200]
    assert "min_n=max(1, min(_mn, 200))" in seg, "要有下限/上限，防误配把建议关死"
    assert "gap=max(0.05, min(_gp, 0.95))" in seg


def test_min_n_high_suppresses_advice(tmp_path):
    """阈值调高 → 样本不足 → 不建议（真机就是这样把建议关掉的）。"""
    db = _db(tmp_path, [("tuniu", _d(7), "ok", 6),
                        ("tuniu", _d(80), "timeout", 6)])
    assert distance_advice(24, db=db) , "默认阈值下应报"
    assert distance_advice(24, min_n=200, db=db) == [], "阈值调高应不报"


def test_gap_threshold_is_respected(tmp_path):
    """近端 100% / 远端 90%（差 10pp）：gap=0.05 报，gap=0.12 不报。"""
    db = _db(tmp_path, [("fliggy", _d(7), "ok", 10),
                        ("fliggy", _d(80), "ok", 9),
                        ("fliggy", _d(80), "timeout", 1)])
    assert distance_advice(24, gap=0.05, db=db), "差 10pp 应报（阈值 5pp）"
    assert distance_advice(24, gap=0.12, db=db) == [], "差 10pp 不该过 12pp 阈值"


def test_save_syncs_cfg_snapshot():
    """面板保存后要同步 `_State.cfg`，否则 crawler 选项"改了不生效"。"""
    w = _w()
    assert "_State.cfg = _live_cfg" in w
    i = w.index("st.reload_cb() if st.reload_cb else 0")
    seg = w[i:i + 900]
    assert "from main import load_config" in seg, "要用同一个 config_path 重载"
    assert "boot_cfg" in w, "启动快照仍保留（需重启差量判定要用）"

def test_effective_cfg_reads_snapshot(monkeypatch):
    """`_effective_crawler_config()` 必须读 `_State.cfg`（保存后会同步它）。

    这是"面板里改配置 → 立即生效"链条的**中间环**：
    保存处理里 `_State.cfg = load_config(...)`，这里确认下游真的读它。
    """
    import webui

    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"advice_distance_min_n": 200,
                                     "advice_distance_gap": 0.5}},
                        raising=False)
    eff = webui._effective_crawler_config()
    assert eff.get("advice_distance_min_n") == 200
    assert eff.get("advice_distance_gap") == 0.5
