# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_bootstrap.py
- tests/test_r1063_live_check.py
- tests/test_r1063_ready_cache.py
- tests/test_r1063_setup_check.py
- tests/test_r1063_setup_fix.py
- tests/test_r1063_u2_requirement.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import os
import sys
import time

from core import bootstrap as B, live_check as LC, setup_check as SC, setup_check as sc
from core.android.runtime import AndroidRuntime


# ---- merged from tests/test_r1063_bootstrap.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rows(seq):
    return list(seq)


def test_fixes_until_clean():
    """第一轮有可修项 → 修；第二轮干净 → 停。"""
    calls = {"checks": 0, "fixed": []}
    states = [
        [
            {"level": SC.BAD, "name": "依赖", "detail": "缺 playwright",
             "fix": "pip install -r requirements.txt",
             "action": "install_deps"},
            {"level": SC.OK, "name": "配置", "detail": "ok"},
        ],
        [
            {"level": SC.OK, "name": "依赖", "detail": "ok"},
            {"level": SC.OK, "name": "配置", "detail": "ok"},
        ],
    ]

    def checks():
        i = min(calls["checks"], len(states) - 1)
        calls["checks"] += 1
        return [dict(r) for r in states[i]]

    def apply(row):
        calls["fixed"].append(row["name"])
        return True

    rep = B.bootstrap(echo=lambda *a, **k: None, checks=checks, apply=apply)
    assert rep["ok"] is True, rep
    assert rep["passes"] == 2, rep
    assert rep["fixed"] == ["依赖"], rep
    assert rep["remaining"] == [], rep


def test_stops_after_max_passes_when_never_clean():
    def checks():
        return _rows([{"level": SC.BAD, "name": "依赖", "detail": "x",
                       "fix": "pip install -r requirements.txt",
                       "action": "install_deps"}])

    rep = B.bootstrap(echo=lambda *a, **k: None, checks=checks,
                      apply=lambda row: True, max_passes=2)
    assert rep["passes"] == 2, "必须封顶，不能死循环"
    assert rep["ok"] is False


def test_apply_exception_does_not_break_run():
    def checks():
        return _rows([{"level": SC.WARN, "name": "数据目录", "detail": "缺",
                       "fix": "mkdir data", "action": "mkdir"}])

    def apply(row):
        raise RuntimeError("boom")

    rep = B.bootstrap(echo=lambda *a, **k: None, checks=checks, apply=apply,
                      max_passes=1)
    assert rep["passes"] == 1
    assert rep["fixed"] == []


def test_report_mentions_next_steps():
    lines = []
    B._report({"ok": True, "passes": 1, "fixed": ["依赖"], "remaining": []},
              echo=lines.append)
    txt = "\n".join(lines)
    assert "--start" in txt and "channel_matrix" in txt


def test_never_touches_accounts_or_policy():
    """硬边界：只做机器能否运行的事，不许改账号/策略/订阅。

    注意：不能拿裸 "login" 当判据——模块里有一句**提示语**
    `channel_matrix --login`（告诉用户去哪登），那是帮助文本，不是动作。
    这里查的是"会真的改状态"的调用。
    """
    src = io.open(os.path.join(ROOT, "core", "bootstrap.py"),
                  encoding="utf-8").read()
    for bad in ("set_config(", "strategy_overrides", "login_sessions",
                "save_session", "pm clear", "shutil.rmtree"):
        assert bad not in src, "引导不许碰账号/策略/破坏性操作：%s" % bad


# ---- merged from tests/test_r1063_live_check.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GOOD_SLOTS = {
    "ctrip": {"surface_label": "PC", "login_url": "https://passport.ctrip.com/x"},
    "ctrip_h5": {"surface_label": "H5", "login_url": "https://m.ctrip.com/"},
    "fliggy": {"surface_label": "PC", "login_url": "https://www.fliggy.com/"},
    "fliggy_h5": {"surface_label": "H5", "login_url": "https://m.tb.com/"},
    "tongcheng": {"surface_label": "PC", "login_url": "https://www.ly.com/"},
    "tongcheng_h5": {"surface_label": "H5", "login_url": "https://m.ly.com/"},
    "tuniu": {"surface_label": "PC", "login_url": "https://passport.tuniu.com/"},
    "tuniu_h5": {"surface_label": "H5", "login_url": "https://m.tuniu.com/"},
    "qunar": {"surface_label": "全端·已停服", "login_url": "https://user.qunar.com/"},
}


def _fake_get(base, path, timeout=20.0):
    if path == "/api/state":
        return {"version": LC.source_version() or "0"}
    if path == "/api/login-state":
        return {"slots": dict(GOOD_SLOTS)}
    if path == "/api/pacing":
        return {"channels": {"fliggy": {"session": {"windows": 1},
                                        "paths": {"PC": {"why": "ok"}}}},
                "degraded": {"device_env": {"n": 1}}}
    raise AssertionError(path)


def test_all_good(monkeypatch):
    monkeypatch.setattr(LC, "_get", _fake_get)
    rep = LC.check(8765)
    assert rep["ok"] is True, rep
    assert rep["detail"]["slots"] == 9
    assert rep["detail"]["with_session"] == 1
    assert rep["detail"]["why_rows"] == 1


def test_flags_version_mismatch(monkeypatch):
    def g(base, path, timeout=20.0):
        if path == "/api/state":
            return {"version": "1.5.307"}
        return _fake_get(base, path, timeout)

    monkeypatch.setattr(LC, "_get", g)
    rep = LC.check(8765)
    assert rep["ok"] is False
    assert any("版本不一致" in p for p in rep["problems"]), rep


def test_flags_pc_slot_pointing_at_mobile(monkeypatch):
    def g(base, path, timeout=20.0):
        if path == "/api/login-state":
            bad = {k: dict(v) for k, v in GOOD_SLOTS.items()}
            bad["tuniu"]["login_url"] = "https://m.tuniu.com/flight/"
            return {"slots": bad}
        return _fake_get(base, path, timeout)

    monkeypatch.setattr(LC, "_get", g)
    rep = LC.check(8765)
    assert rep["ok"] is False
    assert any("移动域" in p for p in rep["problems"]), rep


def test_flags_missing_session_and_why(monkeypatch):
    def g(base, path, timeout=20.0):
        if path == "/api/pacing":
            return {"channels": {"fliggy": {"paths": {"PC": {}}}},
                    "degraded": {}}
        return _fake_get(base, path, timeout)

    monkeypatch.setattr(LC, "_get", g)
    rep = LC.check(8765)
    assert rep["ok"] is False
    assert any("session" in p for p in rep["problems"]), rep
    assert any("why" in p for p in rep["problems"]), rep


def test_offline_instance_reports_clearly(monkeypatch):
    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(LC, "_get", boom)
    rep = LC.check(1)
    assert rep["ok"] is False and "连不上" in rep["problems"][0]


def test_source_version_matches_main():
    txt = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    v = LC.source_version()
    assert v and '__version__ = "%s"' % v in txt


# ---- merged from tests/test_r1063_ready_cache.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "core", "android", "runtime.py"),
              encoding="utf-8").read()
SRC_AB = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                 encoding="utf-8").read()


def test_cache_knob_is_read_from_raw_config():
    """`ready_cache_s` 从原始 android: 段读（不进 AndroidConfig，避免破坏钉住的字段集）。"""
    from core.android.runtime import AndroidRuntime
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 0})
    rt._ready_ok_at = time.time()
    assert rt.ensure_ready()[1] != "ready-cached", "0 应关闭缓存"
    rt2 = AndroidRuntime({"enabled": True})
    rt2._ready_ok_at = time.time()
    assert rt2.ensure_ready()[1] == "ready-cached", "缺省 60 秒应命中缓存"


def test_success_is_cached():
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 60})
    rt._ready_ok_at = time.time()
    ok, why = rt.ensure_ready()
    assert ok is True and why == "ready-cached"
    assert rt._state == "ready(cached)"


def test_cache_expires():
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 60})
    rt._ready_ok_at = time.time() - 61
    ok, why = rt.ensure_ready()
    assert why != "ready-cached", "过期必须重新探测"


def test_zero_ttl_disables_cache():
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 0})
    rt._ready_ok_at = time.time()
    ok, why = rt.ensure_ready()
    assert why != "ready-cached"


def test_failures_are_never_cached():
    """失败的调用不许写缓存戳——否则设备掉了会被"缓存"掩盖。"""
    rt = AndroidRuntime({"enabled": False, "ready_cache_s": 60})
    ok, _ = rt.ensure_ready()
    assert ok is False
    assert getattr(rt, "_ready_ok_at", 0.0) == 0.0


def test_source_marks_every_prepare_step():
    """前置每一步都要有名字（否则又回到"只有总数"）。"""
    for name in ("前置·竖屏", "前置·登录态", "前置·权限框", "前置·切前台",
                 "前置·ANR", "前置·props", "前置·定位", "前置·cpuinfo"):
        assert 'self.timed("%s")' % name in SRC_AB, name


# ---- merged from tests/test_r1063_setup_check.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_rows_have_a_fixed_shape():
    rows = sc.run_checks()
    assert rows, "自检必须至少有一项"
    for r in rows:
        assert set(r) >= {"level", "name", "detail", "fix"}, r
        assert r["level"] in (sc.OK, sc.WARN, sc.BAD), r


def test_python_check_reports_ok_here():
    r = sc.check_python()
    assert r["level"] == sc.OK, r


def test_modules_check_names_what_is_missing():
    r = sc.check_modules(names=("yaml", "definitely_not_a_module_xyz"))
    assert r["level"] == sc.BAD
    assert "definitely_not_a_module_xyz" in r["detail"]
    assert "pip install" in r["fix"]


def test_config_check_reads_platforms():
    r = sc.check_config()
    assert r["level"] in (sc.OK, sc.WARN, sc.BAD), r
    if r["level"] == sc.OK:
        assert "订阅" in r["detail"]




def test_only_safe_actions_are_auto_fixable():
    rows = [{"level": sc.BAD, "name": "a", "detail": "",
             "fix": "python -m playwright install chromium"},
            {"level": sc.BAD, "name": "b", "detail": "",
             "fix": "启动 MuMu 模拟器"},
            {"level": sc.OK, "name": "c", "detail": "", "fix": ""}]
    todo = sc.fixable(rows)
    assert [r["name"] for r in todo] == ["a"], todo
    # 账号/登录类修复永远不许自动做
    assert all("MuMu" not in r["fix"] for r in todo)


def test_android_check_is_honest_when_no_device():
    r = sc.check_android()
    assert r["level"] in (sc.OK, sc.WARN, sc.BAD), r
    # 已启用但没设备 → 必须是 warn 且说清怎么办
    if r["level"] == sc.WARN and "设备" in r["detail"]:
        assert r["fix"]


def test_main_exit_code_reflects_bad_items(monkeypatch, capsys):
    monkeypatch.setattr(sc, "run_checks",
                        lambda: [sc._row(sc.BAD, "x", "y", "手动作业")])
    assert sc.main([]) == 1
    monkeypatch.setattr(sc, "run_checks",
                        lambda: [sc._row(sc.OK, "x", "y")])
    assert sc.main([]) == 0


def test_unsubscribed_channels_are_named(monkeypatch, tmp_path):
    """未订阅的渠道必须被**点名**——否则用户以为"没有这个能力"。

    飞猪 App 是最鲜活的例子：能力在、注册表也在，只是从未进过 platforms，
    于是近 30 天账本一条记录都没有，而界面上只显示"未启用"占位行。

    这里造一个临时根目录（干净检出里本来没有 config.yaml），
    否则 `check_config()` 会在"配置不存在"就返回，走不到未订阅那一段。
    """
    import yaml

    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"users": [{"platforms": ["ctrip"]}]},
                       allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(sc, "_root", lambda: str(tmp_path))
    r = sc.check_config()
    assert r["level"] == sc.WARN, r
    assert "未订阅" in r["detail"], r
    assert "app_fliggy" in r["detail"], r
    assert r["fix"]


# ---- merged from tests/test_r1063_setup_fix.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_fixable_uses_actions_not_wording():
    rows = [
        {"level": sc.BAD, "name": "配置", "detail": "", "fix": "换个说法也行",
         "action": "create_config"},
        {"level": sc.BAD, "name": "目录", "detail": "", "fix": "",
         "action": "mkdir"},
        {"level": sc.BAD, "name": "人工", "detail": "", "fix": "手动作业",
         "action": "manual"},
        {"level": sc.OK, "name": "好", "detail": "", "fix": "", "action": ""},
    ]
    got = [r["name"] for r in sc.fixable(rows)]
    assert got == ["配置", "目录"], got


def test_old_rows_without_action_still_work():
    """向后兼容：没有 `action` 时退回匹配文案。"""
    rows = [{"level": sc.BAD, "name": "x", "detail": "",
             "fix": "python -m playwright install chromium"}]
    assert [r["name"] for r in sc.fixable(rows)] == ["x"]


def test_create_config_copies_example_and_never_overwrites(monkeypatch,
                                                          tmp_path):
    import shutil
    from pathlib import Path

    (tmp_path / "config.example.yaml").write_text("users: []\n",
                                                  encoding="utf-8")
    monkeypatch.setattr(sc, "_root", lambda: str(tmp_path))
    row = {"action": "create_config", "fix": ""}
    assert sc.apply_fix(row, echo=lambda *_a: None) is True
    assert (tmp_path / "config.yaml").exists()

    # 已存在时绝不覆盖（用户可能已经填了账号）
    (tmp_path / "config.yaml").write_text("users:\n- name: 我\n",
                                           encoding="utf-8")
    assert sc.apply_fix(row, echo=lambda *_a: None) is True
    assert "我" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_mkdir_creates_data_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_root", lambda: str(tmp_path))
    assert sc.apply_fix({"action": "mkdir", "fix": ""},
                        echo=lambda *_a: None) is True
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "user_data").is_dir()


def test_one_click_setup_scripts_exist_and_chain_the_same_steps():
    for name in ("setup.ps1", "setup.sh"):
        p = os.path.join(ROOT, name)
        assert os.path.exists(p), name
        txt = io.open(p, encoding="utf-8").read()
        for step in ("requirements.txt", "playwright install chromium",
                     "core.setup_check --fix"):
            assert step in txt, (name, step)


def test_setup_scripts_do_not_touch_accounts_or_strategy():
    """一键装机不许自作主张改账号/策略（那是人的事）。"""
    for name in ("setup.ps1", "setup.sh"):
        txt = io.open(os.path.join(ROOT, name), encoding="utf-8").read()
        for bad in ("notifier", "token", "platforms:", "strategy_overrides"):
            assert bad not in txt, (name, bad)


# ---- merged from tests/test_r1063_u2_requirement.py ----

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
