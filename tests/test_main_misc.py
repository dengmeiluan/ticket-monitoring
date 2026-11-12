# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1219_empty_platforms.py
- tests/test_r1810_app_horizon_dispatch.py
- tests/test_r235_isolation.py
- tests/test_r245_disk.py
- tests/test_r280_firstgate.py
- tests/test_r339_browser_dir.py
- tests/test_r339_config_dupkey.py
- tests/test_r339_startup_paths.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import main
import main as M
import main as _m
import os
import pytest
import sqlite3
import sys
import textwrap
import yaml

from datetime import date, datetime, timedelta
from main import load_config


# ---- merged from tests/test_r1219_empty_platforms.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _cfg(user_extra, global_platforms="__absent__"):
    user = {"name": "u", "special_radar": {"x": 1}}   # 有内容才不会被跳过
    user.update(user_extra)
    cfg = {"users": [user]}
    if global_platforms != "__absent__":
        cfg["platforms"] = global_platforms
    return cfg


def test_explicit_empty_means_no_channels():
    users = M.build_users(_cfg({"platforms": []}))
    assert users, "用户被跳过了，用例没测到点子上"
    assert users[0]["platforms"] == [], "显式空列表被回落成默认渠道了"


def test_missing_key_falls_back_to_global():
    users = M.build_users(_cfg({}, global_platforms=["ctrip"]))
    assert users[0]["platforms"] == ["ctrip"]


def test_missing_everything_uses_legacy_default():
    users = M.build_users(_cfg({}))
    assert set(users[0]["platforms"]) == {"qunar", "fliggy", "tongcheng", "tuniu"}


def test_global_empty_also_means_none():
    users = M.build_users(_cfg({}, global_platforms=[]))
    assert users[0]["platforms"] == []


def test_explicit_list_wins():
    users = M.build_users(_cfg({"platforms": ["tuniu"]}, global_platforms=["ctrip"]))
    assert users[0]["platforms"] == ["tuniu"]


# ---- merged from tests/test_r1810_app_horizon_dispatch.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TODAY = date.today()


def test_far_dates_drop_app_channels_only():
    far = (TODAY + timedelta(days=200)).isoformat()
    near = (TODAY + timedelta(days=10)).isoformat()
    plats = {"app_zhixing", "app_qunar", "ctrip", "fliggy"}

    kept, dropped = M._drop_far_app_channels(plats, far, {})
    assert "app_zhixing" not in kept and "app_qunar" not in kept
    assert {"ctrip", "fliggy"} <= kept, "浏览器渠道不该被剔"
    assert {p for p, _ in dropped} == {"app_zhixing", "app_qunar"}

    kept2, dropped2 = M._drop_far_app_channels(set(plats), near, {})
    assert dropped2 == [], "近日期不该被剔"
    assert "app_zhixing" in kept2


def test_horizon_config_override():
    assert M._app_horizon_days({}, "app_zhixing") == 62
    cfg = {"crawler": {"app_date_horizon_days": 90}}
    assert M._app_horizon_days(cfg, "app_zhixing") == 90
    cfg2 = {"crawler": {"app_date_horizon_days": 90,
                        "app_date_horizon_days_map": {"app_ctrip": 120}}}
    assert M._app_horizon_days(cfg2, "app_ctrip") == 120
    assert M._app_horizon_days(cfg2, "app_qunar") == 90


def test_bad_date_is_noop():
    kept, dropped = M._drop_far_app_channels({"app_zhixing"}, "not-a-date", {})
    assert kept == {"app_zhixing"} and dropped == []


def test_filter_is_wired_before_failover():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    i = src.index("_drop_far_app_channels(plats")
    j = src.index("预置换道（r1063 T23）")
    assert i < j, "过滤必须在换道展开之前"


# ---- merged from tests/test_r235_isolation.py ----

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROD_SENT = os.path.join(_REPO, "data", "sentinel_state.json")


def test_sentinel_state_path_redirected():
    """autouse 夹具必须把 _SENT_PATH 重定向出仓库 data 目录。"""
    assert not os.path.normpath(_m._SENT_PATH).startswith(
        os.path.normpath(_REPO)), _m._SENT_PATH


def test_sentinel_memory_state_fresh():
    """_SENT_LAST/_SENT_CNT/_SENT_SUPPLIED 模块级全局不得跨测试残留
    ——前序用例的合成告警/供给态正是经由内存残留被后续漏补丁用例
    的 _sent_save 带进生产文件。"""
    assert not _m._SENT_LAST, dict(_m._SENT_LAST)
    assert not _m._SENT_CNT, dict(_m._SENT_CNT)
    assert not _m._SENT_SUPPLIED, dict(_m._SENT_SUPPLIED)


def test_sentinel_save_never_touches_repo_data(tmp_path):
    """端到端：供给轮写基线+断链轮触发告警链（当年污染生产文件的
    真实形态），生产 data/sentinel_state.json 必须逐字节不变。"""
    from types import SimpleNamespace as _NS

    # 构造事故形态：全新进程空内存态（import 时 _sent_load 读入的
    # 存量「当日已报」记录会让 _warn 首行短路，绕过落盘路径）
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    before = (open(_PROD_SENT, "rb").read()
              if os.path.exists(_PROD_SENT) else None)
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    def _info(*a, **k):
        pass

    _L.info = staticmethod(_info)
    alive = [{"price": 1000, "cabin": "经济舱", "stopover": True,
              "shareCarrier": "MU5700" if i % 3 == 0 else ""}
             for i in range(25)]
    _m._field_sentinel([_NS(platform="fliggy", extra=json.dumps(alive))],
                       _L())
    dead = [{"price": 1000, "cabin": "经济舱", "stopover": True}
            for _ in range(25)]
    _m._field_sentinel([_NS(platform="fliggy", extra=json.dumps(dead))],
                       _L())
    _m._sent_save()
    assert any("shareCarrier" in str(a) for a in seen), seen

    after = (open(_PROD_SENT, "rb").read()
             if os.path.exists(_PROD_SENT) else None)
    assert after == before, "生产哨兵文件被测试写入"
    # 落盘去向是重定向后的隔离文件，且合成键真实在盘
    with open(_m._SENT_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert any(k.startswith("fliggy|") for k in saved)


# ---- merged from tests/test_r245_disk.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_disk_low_threshold_boundary():
    """disk_low 纯函数：剩余 < 地板=低水位；地板=0 恒不误报。
    以阈值参数为注入点（真实磁盘真实调用，无 mock——floor 取
    天文大值必低、取 0 恒安全，两端边界真实可达）。"""
    from main import disk_low
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert disk_low(root, floor_gb=10 ** 9) is True    # 剩余必小于天文大值
    assert disk_low(root, floor_gb=0) is False         # free<0 恒假


def test_disk_low_bad_root_no_crash():
    """不存在的路径不抛异常、返回 False（检查自身故障不误报不炸轮）。"""
    from main import disk_low
    assert disk_low(os.path.join(os.path.abspath(os.sep), "no", "such",
                                 "dir"), floor_gb=10 ** 9) is False


def test_disk_low_wired_into_sweep():
    """接线钉：扫描轮开头挂水位检查（每轮一次，WARNING 词面在位）。"""
    src = open("main.py", encoding="utf-8").read()
    assert "disk_low(_REPO_ROOT" in src
    assert "磁盘] 剩余" in src


# ---- merged from tests/test_r280_firstgate.py ----

class TestFirstRunGate:
    def test_gate_skips_only_first_round(self):
        """核心复现：fresh 谓词下首次跳过、之后恒放行。
        旧实现等价于每轮重查谓词（第二次仍 True）——修正前此断言红。"""
        gate = _m._FirstRunGate(lambda: 120.0)
        assert gate.should_skip() is True
        assert gate.should_skip() is False
        assert gate.should_skip() is False

    def test_gate_predicate_queried_once(self):
        """谓词只在有臂时被查询一次；耗臂后不再触谓词（DB 读每轮零开销）。"""
        calls = []
        gate = _m._FirstRunGate(lambda: calls.append(1) or 120.0)
        gate.should_skip()
        gate.should_skip()
        assert len(calls) == 1

    def test_gate_stale_or_missing_no_skip(self):
        """首轮上轮落库已老（>300s）或 DB 不可读（None）：不跳过。"""
        assert _m._FirstRunGate(lambda: 900.0).should_skip() is False
        assert _m._FirstRunGate(lambda: None).should_skip() is False
        assert _m._FirstRunGate(lambda: 299.9).should_skip() is True

    def test_gate_exposes_last_age(self):
        """Soldier Minor-3：跳过分支的日志龄取 gate.last_age（单次读库），
        不再二次读库（两读可竞态不一致，日志面失真）。"""
        gate = _m._FirstRunGate(lambda: 120.0)
        assert gate.should_skip() is True
        assert gate.last_age == 120.0

    def test_first_gate_shared_instance(self):
        """Soldier Minor-2：gate 实例必须在 main() 创建一次、_first_run
        闭包复用——每轮新建 gate 等于节流每轮重装臂，first-only 退化。"""
        src = open("main.py", encoding="utf-8").read()
        assert src.count("_first_gate = _FirstRunGate(") == 1
        assert "if _first_gate.should_skip():" in src
        assert "_first_gate.last_age" in src, "日志龄未走单次读库"


class TestRecentSweepAge:
    def _mkdb(self, tmp_path, ts):
        db = tmp_path / "p.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE flight_prices (fetched_at TEXT)")
        if ts is not None:
            con.execute("INSERT INTO flight_prices VALUES (?)", (ts,))
        con.commit()
        con.close()
        return str(db)

    def test_fresh_db_age_positive(self, tmp_path):
        ts = (datetime.now() - timedelta(seconds=60)
              ).strftime("%Y-%m-%d %H:%M:%S")
        age = _m._recent_sweep_age(self._mkdb(tmp_path, ts))
        assert age is not None and 0 <= age < 300

    def test_stale_db_age_over_window(self, tmp_path):
        ts = (datetime.now() - timedelta(minutes=30)
              ).strftime("%Y-%m-%d %H:%M:%S")
        age = _m._recent_sweep_age(self._mkdb(tmp_path, ts))
        assert age is not None and age > 300

    def test_empty_table_returns_none(self, tmp_path):
        assert _m._recent_sweep_age(self._mkdb(tmp_path, None)) is None

    def test_missing_db_returns_none(self, tmp_path):
        assert _m._recent_sweep_age(str(tmp_path / "nope.db")) is None


# ---- merged from tests/test_r339_browser_dir.py ----

def test_browser_dir_sets_env(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    try:
        assert main._apply_browser_dir(
            {"crawler": {"browser_dir": "~/pw-cache"}}) is True
        v = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        assert os.path.isabs(v) and v.endswith("pw-cache")
        assert "~" not in v  # expanduser 已展开
    finally:
        # _apply_browser_dir 直写 os.environ 不经 monkeypatch——delenv
        # 对缺席变量不登记 undo，直接写入会泄漏全程（后位一切
        # chromium.launch 找去 pw-cache 全灭实录）；显式还原
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)


def test_browser_dir_empty_keeps_default(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert main._apply_browser_dir({"crawler": {"browser_dir": ""}}) is False
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_browser_dir_missing_key_keeps_default(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert main._apply_browser_dir({}) is False
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_browser_dir_overrides_existing_env(monkeypatch):
    # 配置优先律：显式配置压过进程外继承的旧环境变量（如用户手动
    # set 过旧路径后改用配置文件——配置是单一事实源）
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", r"D:\old-cache")
    assert main._apply_browser_dir(
        {"crawler": {"browser_dir": r"D:\new-cache"}}) is True
    # 断言值=配置路径的 abspath（实现语义：env 落绝对形态——Linux 上
    # 盘符路径是相对形态会被 abspath 加 cwd 前缀，Windows 原样；两
    # 平台各自成立，直接对表实现同式，CI-Linux 差异当日红定谳）
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == \
        os.path.abspath(os.path.expanduser(r"D:\new-cache"))


def test_browser_dir_wired_at_startup():
    # 接线钉：main() 在 ensure_chromium 之前应用（内核安装与查找同轨）
    src = open("main.py", encoding="utf-8").read()
    apply_pos = src.index("def _apply_browser_dir")
    call_pos = src.index("_apply_browser_dir(cfg)")
    chrom_pos = src.index("ensure_chromium(cfg.get(\"platforms\")")
    assert apply_pos < call_pos < chrom_pos


def test_browser_dir_four_way_domain():
    # 配置面四方域律（LESSONS 十四§8）：选项域==消费域==验证域==演示域
    # 同轮对齐——任一方单独缺席当日红
    src = webui_full_src()
    assert '"browser_dir": str(' in src, "供给域（/api/config globals）缺席"
    assert 'glb.get("browser_dir") is not None' in src, "保存域缺席"
    assert "'glbBdir'" in src, "选项域（全局卡 glcell 行）缺席"
    assert '"browser_dir": ""' in src, "演示域（demo 夹具取值形态）缺席"


# ---- merged from tests/test_r339_config_dupkey.py ----

_CLEAN = textwrap.dedent("""\
    users:
    - name: 测试用户
      routes:
      - from: SHA
        from_name: 上海
        to: HAK
        to_name: 海口
        dates:
        - '2027-01-29'
        alert_direct: 1500
        alert_transfer: 1300
      platforms:
      - qunar
    schedule:
      interval_minutes: 30
    crawler:
      headless: true
    output:
      db_path: data/prices.db
      log_path: logs/monitor.log
    web:
      port: 8765
    """)

# 事故原文形态：BKK 块内出现第二组 to_name/dates/alert_direct（新加坡）
_MANGLED = textwrap.dedent("""\
    users:
    - name: 测试用户
      routes:
      - from: SHA
        from_name: 上海
        to: BKK
        to_name: 曼谷
        dates:
        - '2026-11-16'
        alert_direct: 900
        alert_transfer: 0
        to_name: 新加坡
        dates:
        - '2026-11-16'
        alert_direct: 950
        alert_transfer: 0
      platforms:
      - qunar
    schedule:
      interval_minutes: 30
    output:
      db_path: data/prices.db
      log_path: logs/monitor.log
    web:
      port: 8765
    """)


def test_clean_config_loads_and_keeps_routes(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_CLEAN, encoding="utf-8")
    cfg = load_config(str(p))
    rts = cfg["users"][0]["routes"]
    assert len(rts) == 1
    assert rts[0]["to_name"] == "海口"
    assert rts[0]["alert_direct"] == 1500


def test_duplicate_route_key_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_MANGLED, encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError) as ei:
        load_config(str(p))
    assert "to_name" in str(ei.value)


def test_duplicate_top_level_key_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_CLEAN + "\nschedule:\n  interval_minutes: 10\n",
                 encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_config(str(p))


# ---- merged from tests/test_r339_startup_paths.py ----

def test_db_path_migration_moves_old_default_db(tmp_path, monkeypatch):
    old_db = tmp_path / "old" / "prices.db"
    old_db.parent.mkdir(parents=True)
    old_db.write_bytes(b"sqlite-data")
    new_db = tmp_path / "new" / "prices.db"
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_db_if_needed(
        str(old_db), str(new_db), str(tmp_path / "sentinel.db"))
    assert r is True
    assert new_db.exists() and new_db.read_bytes() == b"sqlite-data"
    assert not old_db.exists()


def test_db_path_noop_when_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_db_if_needed(
        str(tmp_path / "ghost.db"), str(tmp_path / "new.db"),
        str(tmp_path / "sentinel.db"))
    assert r is False
    assert not (tmp_path / "new.db").exists()


def test_user_data_dir_migration(tmp_path, monkeypatch):
    old_ud = tmp_path / "old" / "user_data"
    (old_ud / "profile").mkdir(parents=True)
    (old_ud / "profile" / "cookies").write_text("x")
    new_ud = tmp_path / "new" / "user_data"
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_user_data_if_needed(str(old_ud), str(new_ud))
    assert r is True
    assert (new_ud / "profile" / "cookies").exists()


def test_user_data_noop_when_target_exists(tmp_path, monkeypatch):
    old_ud = tmp_path / "old" / "user_data"
    old_ud.mkdir(parents=True)
    (old_ud / "keep").write_text("x")
    new_ud = tmp_path / "new" / "user_data"
    new_ud.mkdir(parents=True)
    (new_ud / "existing").write_text("y")
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    r = main._migrate_user_data_if_needed(str(old_ud), str(new_ud))
    assert r is False   # 目标已在：不覆盖（迁移只在空目标时执行）
    assert (new_ud / "existing").exists()


def test_wal_companion_files_migrate_with_db(tmp_path, monkeypatch):
    old_db = tmp_path / "old" / "prices.db"
    old_db.parent.mkdir(parents=True)
    old_db.write_bytes(b"sqlite-data")
    (tmp_path / "old" / "prices.db-wal").write_bytes(b"wal")
    (tmp_path / "old" / "prices.db-shm").write_bytes(b"shm")
    new_db = tmp_path / "new" / "prices.db"
    monkeypatch.setattr(main, "_REPO_ROOT", str(tmp_path))
    main._migrate_db_if_needed(
        str(old_db), str(new_db), str(tmp_path / "sentinel.db"))
    assert new_db.exists()
    assert not (tmp_path / "old" / "prices.db-wal").exists()
    assert not (tmp_path / "old" / "prices.db-shm").exists()
    assert (tmp_path / "new" / "prices.db-wal").exists() or not (
        tmp_path / "old" / "prices.db-wal").exists()


def test_filter_is_rewired_after_preload():
    """反补/预置换道会把 App 孪生加回来，加完必须再滤一次。

    r1810 的过滤在「订阅平台并集」之后执行，而反补（plan_backstop）与
    `_preload` 都在它**之后**才往 plats 里加 App——不加这道复滤，超视野的
    App 会重新混进派发集合，白起一次设备（账本 `app-date unsupported`）。
    """
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    i_pre = src.index("for _src0, _app0 in list((_preload or {}).items()):")
    i_again = src.index(
        "plats, _far2 = _drop_far_app_channels(plats, d, cfg, ret_dates=_rd_q)",
        i_pre)
    i_crawl = src.index("_crawlers = get_crawlers(plats)", i_pre)
    assert i_pre < i_again < i_crawl, (i_pre, i_again, i_crawl)


def test_switch_target_respects_horizon():
    """第二波换道目标也要过视野过滤（`plan_switch` 不经过规划过滤）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    i_switch = src.index("_app, _why = _fo.plan_switch(")
    i_guard = src.index(
        "_kept3, _far3 = _drop_far_app_channels({_app}, d, cfg, ret_dates=_rd3)",
        i_switch)
    i_crawl = src.index("_apps = get_crawlers([_app])", i_switch)
    assert i_switch < i_guard < i_crawl, (i_switch, i_guard, i_crawl)
