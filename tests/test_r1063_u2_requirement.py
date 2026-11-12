# -*- coding: utf-8 -*-
"""r1063 T95：`uiautomator2` 必须是声明依赖——否则新用户装完就是"慢 6 倍"。

T80 把 UI 取树改成"优先 u2 + 复用连接"，单次 dump **2.1–3.1s → 0.07s**，
智行整轮 42.5s → 18.6s。但这条路径是 **fail-soft** 的：没装 `uiautomator2`
就自动退回 CLI —— **功能不缺、速度静默掉回 6 倍慢**。

这正是"看起来能用所以没人发现"的坑，对"GitHub 下载即用"的目标是硬伤：
用户装完能跑，但每轮白等二十多秒却不知道原因。

所以三件事都要有：
1. `requirements.txt` 声明它；
2. `setup_check` 出一行"取树后端：u2（快）/ 未装（慢 6 倍）"；
3. 手册里写清楚（见 `docs/CAPABILITY_AND_UNBLOCK.md` 安装段）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_requirements_declares_uiautomator2():
    s = io.open(os.path.join(ROOT, "requirements.txt"),
                encoding="utf-8").read()
    assert "uiautomator2" in s
    # 要写明"没装会慢"，否则下一个人会以为是可选加速
    assert "慢" in s or "6 倍" in s


def test_setup_check_reports_backend():
    from core import setup_check as sc
    row = sc.check_dump_backend()
    assert row.get("name") == "取树后端"
    assert row.get("level") in ("ok", "warn")
    if row.get("level") == "ok":
        assert "uiautomator2" in row.get("detail", "")
    else:
        assert "慢 6 倍" in row.get("detail", "")
        assert "pip install" in row.get("fix", "")


def test_backend_row_is_in_run_checks():
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    i = src.index("def run_checks")
    seg = src[i:i + 400]
    assert "check_dump_backend()" in seg, seg


def test_missing_u2_degrades_not_crashes(monkeypatch):
    """没装 u2 时必须报 warn 而不是抛——`--fix` 还要能给人一条命令。"""
    import importlib.metadata as md

    def _boom(_name):
        raise md.PackageNotFoundError("uiautomator2")

    monkeypatch.setattr(md, "version", _boom)
    from core import setup_check as sc
    row = sc.check_dump_backend()
    assert row["level"] == "warn"
    assert "uiautomator2" in row["fix"]
