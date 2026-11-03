# -*- coding: utf-8 -*-
"""CI 分片：覆盖全部测试文件、耗时均衡、快照解析不外溢。

分片只改变文件落到哪台 runner，不改变 pytest 的 loadfile 语义；覆盖缺口
会让某个测试文件在 CI 里静默不跑，所以这里同时钉「并集=全集」与
「新文件即使不在耗时快照里也会进组」。
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location(
        "ci_shard", ROOT / "tools" / "ci_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plan_covers_every_file_exactly_once():
    mod = _load()
    files = {p.relative_to(ROOT).as_posix() for p in mod.discover()}
    groups, loads = mod.plan(4)
    got = [p.relative_to(ROOT).as_posix() for g in groups for p in g]
    assert len(got) == len(set(got)), "同一测试文件被分进多组"
    assert set(got) == files, "分片漏掉测试文件"
    assert all(groups)
    assert max(loads) / min(loads) < 1.25, loads


def test_unknown_new_file_still_gets_a_group():
    mod = _load()
    files = mod.discover()
    seconds = {p.name: 10.0 for p in files}
    seconds.pop(files[0].name)
    groups, _ = mod.plan(3, seconds)
    assert files[0] in [p for g in groups for p in g]


def test_snapshot_reads_class_qualified_junit(tmp_path):
    mod = _load()
    xml = tmp_path / "pytest.xml"
    xml.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest tests">'
        '<testcase classname="tests.test_r290_login_stale.TestX" '
        'name="test_a" time="3.5"/>'
        '<testcase classname="tests.test_r290_login_stale" '
        'name="test_b" time="1.5"/>'
        "</testsuite></testsuites>", encoding="utf-8")
    out = tmp_path / "durations.json"
    payload = mod.snapshot(xml, out)
    assert payload["seconds"]["test_r290_login_stale.py"] == 5.0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["seconds"]["test_r290_login_stale.py"] == 5.0


def test_duration_snapshot_covers_most_test_files():
    mod = _load()
    seconds = mod.load_seconds()
    files = list(mod.discover())
    covered = sum(1 for p in files if p.name in seconds)
    assert covered / len(files) >= 0.9, (covered, len(files))
