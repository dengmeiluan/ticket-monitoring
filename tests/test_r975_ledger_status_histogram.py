# -*- coding: utf-8 -*-
"""r975：账本要能区分「真的没票」与「没抓到」。

真实证据（2026-11-05 读生产账本）：

```
[app_qunar] paths["航班明细"] = {"ok": 16, "fail": 24, "rows": 16}
```

40 次尝试 16 次出数的背后，24 次失败**分不清**是哪一类：

  * `empty`  —— 站点确实没票/该日期无航班（**正常，不该修**）
  * `error`/`timeout` —— 解析或交互失败（**该修解析**）
  * `login`/`captcha` —— 登录墙/风控（**该重登或降速**）

旧 `YieldLedger.note()` 只累加 ok/fail/rows，status 直接丢弃，
于是三类在账本里合成一个数字。这与本轮修过的 `unknown`、`app-silent`、
`snap-restore` 同一族：**测量把"缺失"当成了一句结论**。

改法（只增不改）：
  * `note()` 收可选 `status`，累加进该路径的 `st` 直方图；
  * `ok/fail` 语义**不动**（`empty` 仍算"没取到数"）；
  * 老账本没有 `st` 键，读时 `.get` 兜底，不迁移。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r975_ledger_status_histogram.py -q
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.yield_stats import default_ledger  # noqa: E402


def _read(root, plat):
    with open(os.path.join(root, plat, "yield_stats.json"),
              encoding="utf-8") as fh:
        return json.load(fh)[plat]


def test_status_histogram_counts_each_kind(tmp_path):
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "航班明细", False, 0, status="empty")
    led.note("demo", "航班明细", False, 0, status="empty")
    led.note("demo", "航班明细", False, 0, status="error")
    led.note("demo", "航班明细", True, 7, status="ok")
    body = _read(str(tmp_path), "demo")
    bucket = body["paths"]["航班明细"]
    assert bucket["st"] == {"empty": 2, "error": 1, "ok": 1}, bucket
    # ok/fail 语义一个字都没动
    assert bucket["ok"] == 1 and bucket["fail"] == 3, bucket
    assert body["total"] == {"ok": 1, "fail": 3, "rows": 7}, body["total"]


def test_empty_still_counts_as_no_data(tmp_path):
    """直方图不是"洗白"：empty 仍然算没取到数（ok=False）。"""
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "航班明细", False, 0, status="empty")
    body = _read(str(tmp_path), "demo")
    assert body["total"]["ok"] == 0 and body["total"]["fail"] == 1


def test_status_is_optional_and_backward_compatible(tmp_path):
    """不传 status（老调用点）照旧工作，且不产生空的 st 键。"""
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "PC", True, 3)
    bucket = _read(str(tmp_path), "demo")["paths"]["PC"]
    assert bucket["ok"] == 1 and bucket["rows"] == 3
    assert "st" not in bucket, bucket


def test_old_ledger_without_st_is_readable(tmp_path):
    """老账本（没有 st 键）读取不得抛异常，rate/samples 照常。"""
    d = tmp_path / "demo"
    d.mkdir(parents=True)
    (d / "yield_stats.json").write_text(json.dumps({"demo": {
        "hours": {}, "total": {"ok": 2, "fail": 1, "rows": 9},
        "paths": {"PC": {"ok": 2, "fail": 1, "rows": 9, "last": 0.0}},
    }}), encoding="utf-8")
    led = default_ledger(str(tmp_path), "demo")
    assert abs(led.rate("demo") - 2.0 / 3.0) < 1e-9
    assert led.samples("demo", "PC") == 3


def test_callers_record_a_status():
    """两个采集器调用点必须真的把 status 传下去（否则一行都不会进直方图）。"""
    import io
    for f in ("crawlers/base.py", "crawlers/app_base.py"):
        src = io.open(os.path.join(ROOT, f), encoding="utf-8").read()
        assert "status=_st" in src, "%s 没把 status 传给 led.note" % f


# ---------------------------------------------------------------------------
# 顶行口径：非采集通路不进分母
# ---------------------------------------------------------------------------
def test_snapshot_excludes_non_sample_paths(tmp_path):
    """顶行只算"真的打了站点"的通路。

    实测（2026-11-05 生产账本）：app_qunar 的 `航班明细` 是 16/40（0.28），
    但 total 里混着 37 条 TRIP（往返不支持）与 35 条 unknown（app-silent
    上线前的旧轮次），顶行因此被压到 0.09，读起来像"整个渠道全挂"。
    """
    led = default_ledger(str(tmp_path), "demo")
    for _ in range(16):
        led.note("demo", "航班明细", True, 3, status="ok")
    for _ in range(24):
        led.note("demo", "航班明细", False, 0, status="empty")
    for _ in range(37):
        led.note("demo", "TRIP", False, 0, status="unsupported")
    for _ in range(35):
        led.note("demo", "unknown", False, 0)
    for _ in range(292):
        led.note("demo", "snap-restore", False, 0)

    old = led.snapshot()                      # 历史口径
    new = led.snapshot(exclude_infra=True)    # 真实采集口径
    assert old["demo"]["n"] == 16 + 24 + 37 + 35 + 292, old["demo"]
    assert new["demo"]["n"] == 40, new["demo"]
    assert new["demo"]["ok"] == 16, new["demo"]
    # 0.40 成功率 → Wilson 下界约 0.27，明显高于被污染时的 0.09
    assert new["demo"]["lower"] > 0.2, new["demo"]


def test_snapshot_default_keeps_old_behaviour(tmp_path):
    """默认（不带 exclude_infra）行为必须和以前一模一样，不能悄悄改语义。"""
    led = default_ledger(str(tmp_path), "demo")
    led.note("demo", "snap-restore", False, 0)
    led.note("demo", "航班明细", True, 5, status="ok")
    snap = led.snapshot()
    assert snap["demo"]["n"] == 2 and snap["demo"]["ok"] == 1, snap["demo"]
