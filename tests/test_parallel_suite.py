# -*- coding: utf-8 -*-
"""并发验证架构门禁（r481）：

- demo 合成库必须按实例隔离。全部 demo 实例共用
  `%TEMP%/ticket_demo_prices.db` 时，并发启动各自重建同一文件，
  写锁会让实例停在「进程活、不监听」形态（r318 测试注释里的实测）；
- 测试模块不得再绑固定端口：并发时端口互抢，legacy netstat 清理
  还会按固定口 taskkill 到别的 worker 的 demo 服务；
- `tools/test_all.py` 的命令形状与文档口径：并发走 xdist
  （-p xdist.plugin / -n / --dist loadfile）且带插件隔离变量，
  串行命令与 CONTRIBUTING 的验收命令逐词一致。
"""
import importlib.util
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "tm_test_all", ROOT / "tools" / "test_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def test_demo_db_path_per_instance():
    """同一 %TEMP% 下不同端口的 demo 实例不能共用一个库文件。"""
    import webui
    a = webui._demo_db_path(8811)
    b = webui._demo_db_path(8812)
    assert a != b, "不同端口的 demo 仍共用同一个合成库：%s" % a
    assert Path(a).name == "ticket_demo_prices_8811.db", a
    assert Path(b).name == "ticket_demo_prices_8812.db", b
    assert Path(a).parent == Path(tempfile.gettempdir()), a


def test_demo_main_uses_per_port_db():
    """_demo_main 必须经 _demo_db_path 取库路径，不得回退写死文件名。"""
    src = _read(ROOT / "webui.py")
    assert "_demo_db_path(port)" in src or "_demo_db_path(args.port)" in src, (
        "_demo_main 没走 _demo_db_path：并发 demo 会再撞共享库")


def test_no_test_module_binds_fixed_port():
    """测试模块一律现取空闲端口；固定 PORT 在并发下互抢。"""
    hits = []
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        for lineno, line in enumerate(_read(p).splitlines(), 1):
            m = re.match(r"PORT\s*=\s*(\d{4})\s*$", line.strip())
            if m:
                hits.append("%s:%d PORT=%s" % (p.name, lineno, m.group(1)))
    assert not hits, "测试模块仍在绑定固定端口：\n" + "\n".join(hits)


def test_parallel_command_shape(tmp_path):
    """并发命令：显式加载 xdist（autoload 被关掉时也能用）+ 模块级分组。"""
    runner = _load_runner()
    junit = tmp_path / "pytest.xml"
    cmd, env = runner.build_pytest_command(workers=8, junit=junit)
    assert cmd[:3] == [sys.executable, "-m", "pytest"], cmd
    assert "tests/" in cmd, cmd
    assert "xdist.plugin" in cmd, "未显式加载 xdist 插件：%s" % cmd
    assert "-n" in cmd and cmd[cmd.index("-n") + 1] == "8", cmd
    assert "--dist" in cmd and cmd[cmd.index("--dist") + 1] == "loadfile", cmd
    assert "--junitxml=%s" % junit in cmd, cmd
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1", env


def test_serial_command_is_documented_one(tmp_path):
    """串行命令必须仍是 CONTRIBUTING 里那条验收命令（文档/脚本不漂移）。"""
    runner = _load_runner()
    cmd, env = runner.build_pytest_command(workers=1, junit=None, serial=True)
    assert cmd == [sys.executable, "-m", "pytest", "tests/", "-q"], cmd
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1", env
    text = _read(ROOT / "CONTRIBUTING.md")
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q" in text


def test_uitest_result_written_outside_repo():
    """UI 泳道与 pytest 同跑：结果先落临时文件，避免与 EOL/文档门禁抢写。"""
    runner = _load_runner()
    cmd, env, tmp_result = runner.build_uitest_command(port=8893)
    assert cmd == [sys.executable, "docs/uitest.py"], cmd
    assert env["UITEST_PORT"] == "8893", env
    assert Path(env["UITEST_RESULT"]) == Path(tmp_result)
    assert Path(tmp_result).parent != ROOT / "docs", (
        "UI 结果仍直接写仓库内 docs/uitest_result.txt，会和 pytest 门禁抢写")
    assert Path(tmp_result).name == "uitest_result.txt", tmp_result


def test_demo_db_cleanup_spares_fresh_and_listening(tmp_path, monkeypatch):
    """遗留合成库只回收「旧且没人监听」的；新文件与在跑实例不碰。"""
    runner = _load_runner()
    old = tmp_path / "ticket_demo_prices_40001.db"
    fresh = tmp_path / "ticket_demo_prices_40002.db"
    for p in (old, fresh):
        p.write_bytes(b"x")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    monkeypatch.setattr(runner, "_port_listening", lambda port: False)
    removed = runner.cleanup_demo_dbs(min_age=60, base_dir=tmp_path)
    assert removed == 1, removed
    assert not old.exists() and fresh.exists()


def test_mirror_ui_result_survives_transient_lock(tmp_path, monkeypatch):
    """docs/ 结果回写遇到 Windows 瞬时占用要重试，不能把整轮门禁崩掉。"""
    runner = _load_runner()
    src = tmp_path / "ui.txt"
    src.write_text(" ✓ a\n", encoding="utf-8")
    dst = tmp_path / "docs.txt"
    calls = {"n": 0}
    real = os.replace

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked")
        return real(a, b)

    monkeypatch.setattr(runner.os, "replace", flaky)
    assert runner.mirror_ui_result(src, dst) is True
    assert dst.read_text(encoding="utf-8").startswith(" ✓")
    assert calls["n"] >= 2


def test_uitest_summary_missing_file_is_failure(tmp_path):
    """UI 结果文件缺失（playwright 导入前就崩）不能被当成 0/0 绿。"""
    runner = _load_runner()
    s = runner.summarize_uitest(tmp_path / "nope.txt")
    assert s["failed"] == 1, s


def test_junit_summary_counts_and_failures(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite tests="3" failures="1" errors="0"'
        ' skipped="1" time="1.5">'
        '<testcase classname="tests.test_x" name="test_ok" time="0.1"/>'
        '<testcase classname="tests.test_x" name="test_bad" time="0.2">'
        '<failure message="boom: first line">trace</failure></testcase>'
        '<testcase classname="tests.test_x" name="test_skip">'
        '<skipped message="no chromium"/></testcase>'
        "</testsuite></testsuites>\n", encoding="utf-8")
    runner = _load_runner()
    s = runner.summarize_junit(xml)
    assert s["passed"] == 1, s
    assert s["failed"] == 1, s
    assert s["skipped"] == 1, s
    assert s["failures"] == [
        "tests.test_x::test_bad :: boom: first line"], s["failures"]


def test_sections_arg_ranges():
    r = _load_runner()
    assert r.sections_arg([0, 1, 2, 5, 9, 10, 11]) == "0-2,5,9-11"
    assert r.sections_arg([3]) == "3"


def test_plan_contiguous_covers_every_section_once():
    r = _load_runner()
    w = [34.4, 1.3, 24.9, 83.2, 0.3, 1.5, 1.2, 9.5] + [1.0] * 8
    groups = r.plan_contiguous(w, 4, overhead=6)
    assert [i for g in groups for i in g] == list(range(len(w))), groups
    assert all(groups), groups
    worst = max(sum(w[i] for i in g) + 6 for g in groups)
    # 单段（83.2s）不可拆时，最重组最多就是「最大单段 + 每片固定开销」
    assert worst <= max(w) + 6 + 1e-6, (worst, groups)


def test_plan_shards_uses_verified_groups():
    r = _load_runner()
    prof = r.load_ui_profile()
    assert prof is not None
    n = len(prof.get("shards") or [])
    if n:
        groups = r.plan_shards(prof, n)
        assert sorted(i for g in groups for i in g) == list(range(len(prof["weights"])))
        assert groups == [sorted(g) for g in prof["shards"]], groups
    groups = r.plan_shards(prof, 4)
    assert sorted(i for g in groups for i in g) == list(range(len(prof["weights"])))


def test_merge_ui_results_keeps_order_and_flags_mismatch(tmp_path):
    r = _load_runner()
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text(" … s1\n ✓ a\n ✗ b :: boom\nJS 错误: 无\n=== 1/2 通过 ===\n",
                 encoding="utf-8")
    b.write_text(" … s2\n ✓ c\nJS 错误: [x]\n=== 1/1 通过 ===\n",
                 encoding="utf-8")
    text, ok, bad, errs, mismatch = r.merge_ui_results([a, b], total_checks=3)
    assert (ok, bad) == (2, 1), (ok, bad)
    assert mismatch is None, "总数相等时不该报不一致"
    assert "=== 2/3 通过 ===" in text
    assert errs and "x" in errs[0]
    assert text.index(" … s1") < text.index(" … s2")
    # 覆盖变少＝有检查没跑到（r503 那次 569/666 就是这种），必须判异常
    _, _, _, _, short = r.merge_ui_results([a, b], total_checks=4)
    assert short == "short", short
    # 覆盖变多＝新增了 UI 检查，profile 快照旧了；不是缺口，不得判失败（r507）
    _, _, _, _, grown = r.merge_ui_results([a, b], total_checks=2)
    assert grown == "grown", grown


def test_ui_profile_shape():
    r = _load_runner()
    prof = r.load_ui_profile()
    assert prof is not None, "缺少 docs/uitest_profile.json（UI 分片权重）"
    assert len(prof["sections"]) == len(prof["weights"]) > 0
    assert prof["total_checks"] > 0
    assert all(s["seconds"] >= 0 for s in prof["sections"])


def test_a_probe_auth_leak_from_previous_file():
    """负控源：模拟上一文件留在进程里的探针明细（故意写全局）。"""
    import webui
    webui._PROBE_AUTH.setdefault("qunar", {})["domestic"] = {"detail_ts": 1}


def test_b_probe_auth_is_reset_between_tests():
    """conftest 的 autouse 归零必须挡住上一测试的探针证据（r367 并发假红）。"""
    import webui
    assert webui._PROBE_AUTH == {}, webui._PROBE_AUTH


def test_contributing_documents_parallel_default():
    text = _read(ROOT / "CONTRIBUTING.md")
    assert "tools/test_all.py" in text, "CONTRIBUTING 没给并发全量命令"
    release = _read(ROOT / "docs" / "RELEASE_PROCESS.md")
    assert "tools/test_all.py" in release, (
        "RELEASE_PROCESS 没把并发命令列为默认验证口径")
