# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r342_config_deck.py
- tests/test_r645_config_single_indent.py
- tests/test_r649_config_save_is_serialized.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io as _io
import json
import logging
import main
import os
import pytest
import re
import sys
import tempfile
import threading
import urllib.request
import webui
import yaml

from core.alerter import Alerter


# ---- merged from tests/test_r342_config_deck.py ----

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
    src = webui_full_src()
    assert "os.path.abspath(sys.argv[0])" in src
    assert "for _a in sys.argv[1:]" in src
    assert '"--restart-delay", "3"' in src


# ---- merged from tests/test_r645_config_single_indent.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def test_params_cell_uses_shared_indent_token():
    """参数格标签要与卡头同线：padding = --cfg-ico - 9px（=22px）。"""
    src = _src()
    m = re.search(r"#cfgview #cfgglobals \.glcell,#cfgview #cfgpacing \.glcell\{"
                  r"\s*padding-left:([^!]+)!important\}", src)
    assert m, "参数格缩进规则不见了"
    assert m.group(1).replace(" ", "") == "calc(var(--cfg-ico)-9px)", m.group(1)


def test_no_negative_margin_alignment_in_cfg_rows():
    """回归守卫：不得用负 margin 把行推出 overflow:hidden 容器（会裁字）。"""
    src = _src()
    for sel in ("#cfgview #cfgform .srow", "#cfgview #cfgform .grouplab"):
        for m in re.finditer(re.escape(sel) + r"\{([^}]*)\}", src):
            body = m.group(1).replace(" ", "")
            assert "margin-left:-" not in body, (
                "%s 又用负 margin 对齐了——.ucard 有 overflow:hidden，会裁掉首字：%s"
                % (sel, body))


def test_group_header_never_pushes_text_with_padding():
    """分组标题首个子元素是序号徽标；改 padding 会把它推出边界。"""
    src = _src()
    hits = list(re.finditer(r"#cfgview \.grouplab\{([^}]*)\}", src))
    assert hits, "分组标题基础规则不见了"
    body = hits[-1].group(1).replace(" ", "")
    assert "padding-left:0!important" in body, body


# ---- merged from tests/test_r649_config_save_is_serialized.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _run_once(tries=6):
    """返回 (成功次数, 总次数)：两项都留下的次数。"""
    import webui

    tmp = tempfile.mkdtemp(prefix="r649t_")
    cfg = os.path.join(tmp, "config.yaml")
    base = {"users": [], "web": {"port": 0, "host": "127.0.0.1"},
            "schedule": {"interval_minutes": 30}}
    _io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump(base, allow_unicode=True))

    st = webui._State
    st.cfg = dict(base)
    st.boot_cfg = dict(base)
    st.users = []
    st.alerters = []
    st.job = None
    st.report_push = None
    st.reload_cb = None
    st.config_path = cfg
    st.version = "r649"
    st.login_saved_cb = None
    st.logger = logging.getLogger("r649t")
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False

    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    port = srv.server_address[1]
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/api/config" % port

    def post(payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except Exception as e:                     # noqa: BLE001
            return "ERR:%s" % e

    ok = 0
    try:
        for _ in range(tries):
            ths = [threading.Thread(target=post, args=(p,)) for p in (
                {"users": [], "globals": {"interval_minutes": 47}},
                {"users": [], "globals": {"fast_ttl_min": 33}})]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            saved = yaml.safe_load(_io.open(cfg, encoding="utf-8"))
            sc = saved.get("schedule") or {}
            if sc.get("interval_minutes") == 47 and sc.get("fast_ttl_min") == 33:
                ok += 1
            # 复位，下一轮从干净状态开始
            _io.open(cfg, "w", encoding="utf-8").write(
                yaml.safe_dump(base, allow_unicode=True))
    finally:
        srv.shutdown()
        srv.server_close()
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)
    return ok, tries


def test_concurrent_saves_do_not_lose_updates():
    ok, tries = _run_once()
    assert ok == tries, (
        "并发保存丢更新：%d/%d 轮两项都在（其余轮次有一项被覆盖，"
        "但两次都返回了 200）" % (ok, tries))
