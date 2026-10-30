# -*- coding: utf-8 -*-
"""r342 配置工作台：新筛选门 / 路径元数据 / 重启差量 / 日期双通道与
航司智能选择的面板钉。

用户诉求（2026-10-20）：配置页高级感与紧凑度；航司白名单「东航还是
东方航空」零黑箱；区间日期与指定日期同时渲染；更多智能筛选项；
存储路径可改可迁移、绝对路径/打开文件/重启可视化全部落地。
"""
import os

import main
import webui
from core.alerter import Alerter


def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False, "baggage": "免费托运20kg", "planeSize": "大型机",
         "crossDayN": 0, "depTime": "08:00", "arrTime": "11:00",
         "stop": False, "shareCarrier": "", "codeShare": ""}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "PEK", "to_name": "北京",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


# ---- ① 新筛选门 ----

def test_exclude_stop_and_share_fail_open_on_unknown():
    rt = _route(exclude_stop=True, exclude_share=True)
    assert Alerter._route_filters([_flt()], rt)                 # 缺席≠经停/共享
    assert not Alerter._route_filters([_flt(stop=True)], rt)
    assert not Alerter._route_filters([_flt(shareCarrier="MU")], rt)
    assert not Alerter._route_filters([_flt(codeShare=True)], rt)
    assert Alerter._route_filters([_flt(stop=True)], _route())  # 0=不限


def test_transfer_layover_max_known_only():
    good = {"depDate": "2027-01-29", "arrDate": "2027-01-29",
            "arrTime": "14:00", "crossDayDesc": "",
            "layoverM": 180, "transferBaggage": ""}
    rt = _route(transfer_layover_max=240)
    assert Alerter._transfer_ok(good, rt)                        # 恰在窗内
    assert not Alerter._transfer_ok(dict(good, layoverM=300), rt)  # 超长
    # 未知衔接不误杀（上限=舒适度偏好，不是安全底线）
    assert Alerter._transfer_ok(
        {k: v for k, v in good.items() if k != "layoverM"},
        _route(transfer_layover_max=60))
    assert Alerter._transfer_ok(good, _route())                  # 0=不限


def test_new_fields_passthrough_and_defaults():
    rt = _route(exclude_stop=True, exclude_share=True,
                transfer_layover_max="240")
    assert rt.exclude_stop is True and rt.exclude_share is True
    assert rt.transfer_layover_max == 240
    rt0 = _route()
    assert rt0.exclude_stop is False and rt0.exclude_share is False
    assert rt0.transfer_layover_max == 0


# ---- ② 路径元数据 ----

def test_path_meta_file_and_missing_dir_parent():
    m = webui._path_meta("db", "data/probe.db", {})
    assert m["ok"] and m["type"] == "file"
    assert m["abs"].startswith(webui._ROOT)
    assert m["parent"].startswith(webui._ROOT)
    # 缺失目录的父目录=字面父（曾把缺失目录自身当父，恒误报不存在）
    d = webui._path_meta("ud", "ghost_user_data_probe", {})
    assert d["parent"] == webui._ROOT
    assert d["parent_exists"] is True
    # bdir 空=playwright 默认位，仍给绝对路径（不再空白）
    b = webui._path_meta("bdir", "", {})
    assert b["default"] is True and os.path.isabs(b["abs"])


def test_storage_view_shape_and_open_targets():
    view = webui._storage_view({})
    assert set(view) == {"db", "log", "ud", "bdir"}
    for k in view:
        assert view[k]["abs"]
    assert webui._open_folder_target("db", {})
    assert webui._open_folder_target("cfg", {})
    # 不存在文件不可「打开文件」
    assert webui._open_file_target(
        "db", {"output": {"db_path": "data/definitely_missing_probe.db"}}
    ) is None


def test_storage_path_state_roundtrip(tmp_path, monkeypatch):
    """跨重启迁移源状态：自定义→自定义第二次改址仍有源可搬。"""
    monkeypatch.setattr(main, "_STORAGE_STATE", str(tmp_path / "sp.json"))
    main._save_storage_paths(str(tmp_path / "a.db"), str(tmp_path / "ud"),
                             str(tmp_path / "m.log"), "")
    d = main._load_storage_paths()
    assert d["db"] == str(tmp_path / "a.db")
    assert d["user_data"] == str(tmp_path / "ud")
    assert d["browser_dir"] == ""
    # 损坏状态回退空字典，不阻断启动
    (tmp_path / "sp.json").write_text("{bad", encoding="utf-8")
    assert main._load_storage_paths() == {}
    # 启动链以「上次成功路径」为迁移源（非仅出厂默认）
    src = open(main.__file__, encoding="utf-8").read()
    assert "_prev = _load_storage_paths()" in src
    assert '_old_db = _prev.get("db")' in src
    assert "_save_storage_paths(_new_db, _new_ud" in src
    # 状态只在库成功打开后落盘：失败启动不得遗忘真正的迁移源
    assert src.index("storage = PriceStorage") < \
        src.index("_save_storage_paths(_new_db")


# ---- ③ 启动差量（重启可视化） ----

def test_restart_view_normalizes_explicit_defaults(monkeypatch):
    base = {"schedule": {}, "output": {}, "crawler": {}}
    monkeypatch.setattr(webui._State, "boot_cfg", dict(base))
    same = {"output": {"db_path": "data/prices.db",
                       "log_path": "logs/monitor.log"},
            "crawler": {"user_data_dir": "user_data"}}
    r = webui._restart_view(same)
    assert r["required"] is False and r["changed"] == []
    # 绝对路径差量可读（面板显示 running→saved）
    moved = {"output": {"db_path": "data2/prices.db",
                        "log_path": "logs/monitor.log"},
             "crawler": {"user_data_dir": "user_data"}}
    r2 = webui._restart_view(moved)
    assert r2["required"] is True and "db_path" in r2["changed"]
    assert os.path.isabs(r2["saved"]["db_path"])


# ---- ④ PAGE 面钉：日期双通道/航司智能选择/路径与重启 ----

def test_page_pins_r342_deck():
    src = webui.PAGE
    for token in (
            'class="dcompose"', 'role="tablist"', 'data-dm="range"',
            'data-dm="single"', "按区间", "按指定日",
            'id="${p}from-${i}-${j}"', 'id="${p}to-${i}-${j}"',
            'id="${p}add-${i}-${j}"', 'class="btn2 dapply primary"',
            "function _dateRowHTML(", "function setDateMode(",
            "function _commitDates(",
            # r345 心智模型：一次只开一个编辑器，加入=合并去重
            ".dpanel[hidden]{display:none}", "加入区间", "加入日期",
            "airChipsHTML(", "airMode(", "_airQuickHTML(",
            "applyRoutePreset(", "exclude_stop", "exclude_share",
            "transfer_layover_max", "pathPreview(", "openRestartCenter(",
            "cfgOverview", "fltsum", "applyFltPreset(", "renderFltSum(",
            "airHasUnknown(", "cfgRosterEmpty",
            'id="confirmMask"', "function openConfirm(", "function runConfirm(",
            "class=\"chdel\"", "id=\"fltAirQ\"", "class=\"frow attrgrid\"",
            ".chgrid{display:flex;flex-direction:column"):
        assert token in src, token
    # 智能预设 + 新增筛选门都必须落在航线卡内（不是死文案）
    assert "省心直飞" in src and "少中转久等" in src and "行李优先" in src
    assert "中转衔接窗口" in src
    assert "data-which=\"bdir\"" in src


def test_restart_cmd_includes_script():
    """重启命令必须携带脚本本体（曾漏 sys.argv[0] → 旧退新亡）。"""
    src = open(webui.__file__, encoding="utf-8").read()
    assert "os.path.abspath(sys.argv[0])" in src
    assert "for _a in sys.argv[1:]" in src
    assert '"--restart-delay", "3"' in src
