# -*- coding: utf-8 -*-
"""r1063 T96：把两类"卡点"送到面板 + 降级账本落盘。

问题：设备环境矛盾（携程 50003 / 阿里强制滑块的常见根因）与 App 内人机验证
**从来不出现在界面上** —— 用户只看到"0 条"，不知道该跑审计、该清数据还是该登账号。

做法：
1. `consistency.note_if_issues()` → `degraded.note("device_env")`；
2. App 内滑块失败 → `degraded.note("app_captcha")`；
3. 面板文案补 `device_env` / `app_captcha` 的中文名与"下一步"。

**关键修复**：`degraded` 原先只在进程内存里，而自检是**独立进程**——
它写的结论面板永远读不到。现在落盘（`user_data/degraded.json`，24h TTL），
`snapshot()` 合并内存与文件。

顺带修了审计自身的两个 bug（自检当场抓到）：
* `/proc/cpuinfo` 的 Hardware 行只取了第一个词 → `Qualcomm Technologies, Inc SM8650`
  被读成 `Qualcomm`，与 `ro.soc.model` 一比就"矛盾"（假阳性）；
* 判据改为**包含**而非相等（真机 Hardware 有单串与多词两种形态）。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fresh_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import degraded as dg
    with dg._LOCK:
        dg._STATE.clear()
    return dg


def test_degraded_persists_across_processes(tmp_path, monkeypatch):
    dg = _fresh_degraded(tmp_path, monkeypatch)
    dg.note("device_env", "", "1 处矛盾", now=time.time())
    # 模拟"另一个进程"：清空内存后再读
    with dg._LOCK:
        dg._STATE.clear()
    snap = dg.snapshot()
    assert "device_env" in snap, snap
    assert "1 处矛盾" in snap["device_env"]["last"]


def test_degraded_ttl_drops_old(tmp_path, monkeypatch):
    dg = _fresh_degraded(tmp_path, monkeypatch)
    dg.note("app_captcha", "app_fliggy", "滑块未过",
            now=time.time() - dg._TTL_S - 60)
    with dg._LOCK:
        dg._STATE.clear()
    assert "app_captcha" not in dg.snapshot(), "超过 TTL 的旧账应丢弃"


def test_degraded_counts_accumulate_on_disk(tmp_path, monkeypatch):
    dg = _fresh_degraded(tmp_path, monkeypatch)
    _t = time.time()          # 必须用当前时间附近：TTL 24h 会丢掉旧账
    dg.note("app_captcha", "p", "第一次", now=_t)
    dg.note("app_captcha", "p", "第二次", now=_t + 1)
    with dg._LOCK:
        dg._STATE.clear()
    snap = dg.snapshot()
    assert snap["app_captcha"]["n"] == 2
    assert snap["app_captcha"]["last"] == "第二次"


def test_cpuinfo_hardware_parsed_as_whole_line():
    """`Qualcomm Technologies, Inc SM8650` 不能用第一个词当型号。"""
    from core.android import consistency as C
    assert "整行" in io.open(os.path.join(
        ROOT, "core", "android", "consistency.py"), encoding="utf-8").read()
    # 判据：包含即一致
    facts = {"soc_model": "SM8650",
             "cpuinfo_hardware": "Qualcomm Technologies, Inc SM8650",
             "board": "pineapple", "hardware": "qcom",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert "ro.soc.model vs cpuinfo" not in keys, keys


def test_multiword_vs_single_token_both_accepted():
    from core.android import consistency as C
    for hw in ("SM8650", "Qualcomm Technologies, Inc SM8650"):
        facts = {"soc_model": "SM8650", "cpuinfo_hardware": hw}
        assert not C.audit(facts)["items"]


def test_panel_has_labels_and_next_steps():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "device_env:'设备环境'" in src
    assert "app_captcha:'人机验证'" in src
    assert "core.android.consistency" in src and "identity_boot_module" in src
    assert "reset-app" in src


def test_setup_check_has_device_env_row():
    from core import setup_check as sc
    assert callable(getattr(sc, "check_device_env", None))
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    i = src.index("def run_checks")
    assert "check_device_env()" in src[i:i + 400]
