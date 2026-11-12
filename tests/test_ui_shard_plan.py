# -*- coding: utf-8 -*-
"""UI 自检分片：段号从源码派生、并集=全集、workflow 与计划同源。

分片只改变哪台 runner 跑哪些段，不能有段漏跑或重复跑；段号写死在
workflow 里会在新增段后静默漏测，所以计划与 workflow 都必须从
``docs/uitest.py`` 的 ``_want(N)`` 派生并相互校验。
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location(
        "ui_shard", ROOT / "tools" / "ui_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sections_are_contiguous_from_zero():
    mod = _load()
    secs = mod.sections()
    assert secs[0] == 0
    assert secs == list(range(secs[-1] + 1)), secs
    assert len(secs) >= 40, "分段解析明显偏少：%d" % len(secs)


def test_plan_covers_every_section_exactly_once():
    mod = _load()
    secs = set(mod.sections())
    groups = mod.plan(2)
    got = [x for g in groups for x in g]
    assert len(got) == len(set(got)), "同一段被分进两片"
    assert set(got) == secs, "分片漏掉分段"
    assert all(groups)


def test_print_value_matches_plan_and_is_bounded():
    mod = _load()
    groups = mod.plan(2)
    for i, g in enumerate(groups):
        text = mod.fmt(g)
        assert text == mod.fmt(g)
        nums = []
        for part in text.split(","):
            if "-" in part:
                a, b = part.split("-")
                nums.extend(range(int(a), int(b) + 1))
            else:
                nums.append(int(part))
        assert nums == g, (i, text, g)


def test_workflow_matches_two_way_plan():
    mod = _load()
    mod.check_workflow(2)


def test_workflow_mismatch_is_red(monkeypatch, tmp_path):
    mod = _load()
    bad = tmp_path / "ci.yml"
    bad.write_text("jobs:\n  uitest:\n    runs-on: ubuntu-latest\n"
                   "  ci-ok:\n    steps:\n      - run: true\n",
                   encoding="utf-8")
    monkeypatch.setattr(mod, "WF", bad)
    try:
        mod.check_workflow(2)
    except SystemExit:
        pass
    else:
        raise AssertionError("workflow 与分片计划不一致却未报错")
