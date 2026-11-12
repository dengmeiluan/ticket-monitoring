# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r341_route_gates.py
- tests/test_r905_route_advice_has_probe_button.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import ast
import json
import main
import os
import pytest
import socket
import sys
import threading
import time
import webui

from core.alerter import Alerter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


# ---- merged from tests/test_r341_route_gates.py ----

def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False, "baggage": "免费托运20kg", "planeSize": "大型机",
         "crossDayN": 0, "depTime": "08:00", "arrTime": "11:00"}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "PEK", "to_name": "北京",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


# ---- ① price_max ----

def test_price_max_filters_above_and_keeps_unparsable():
    rt = _route(price_max=1000)
    assert Alerter._route_filters([_flt(price=999)], rt)
    assert not Alerter._route_filters([_flt(price=1001)], rt)
    assert Alerter._route_filters([_flt(price=1000)], rt)   # 恰等保留
    # fail-open：票价不可解析的行保留（缺席剔除=整渠道误杀）
    assert Alerter._route_filters([_flt(price="")], rt)
    assert Alerter._route_filters([_flt(price=None)], rt)
    rt0 = _route()
    assert Alerter._route_filters([_flt(price=99999)], rt0)  # 0=不限
    # build_routes 从 dict 键透传（配置链同源）
    assert _route(price_max="800").price_max == 800.0


# ---- ② no_cross ----

def test_no_cross_filters_crossday():
    rt = _route(no_cross=True)
    assert not Alerter._route_filters([_flt(crossDayN=1)], rt)
    assert not Alerter._route_filters([_flt(crossDayN=2)], rt)
    assert Alerter._route_filters([_flt(crossDayN=0)], rt)
    assert Alerter._route_filters([_flt()], rt)             # 缺席=0
    assert Alerter._route_filters([_flt(crossDayN=1)], _route())


# ---- ③ 到达时段窗 ----

def test_arr_window():
    rt = _route(arr_time_min="06:00", arr_time_max="12:00")
    assert Alerter._route_filters([_flt(arrTime="09:30")], rt)
    assert not Alerter._route_filters([_flt(arrTime="23:40")], rt)  # 红眼
    # 跨午夜窗（22:00–02:00）：环形判定
    rt2 = _route(arr_time_min="22:00", arr_time_max="02:00")
    assert Alerter._route_filters([_flt(arrTime="23:30")], rt2)
    assert Alerter._route_filters([_flt(arrTime="01:10")], rt2)
    assert not Alerter._route_filters([_flt(arrTime="12:00")], rt2)
    # arrTime 缺席保留（与 widebody 同律：薄行无从判定不误杀）
    assert Alerter._route_filters([_flt(arrTime="")], rt)
    # 单端窗
    assert not Alerter._route_filters(
        [_flt(arrTime="05:00")], _route(arr_time_min="06:00"))
    assert Alerter._route_filters(
        [_flt(arrTime="23:00")], _route(arr_time_max="23:59"))


# ---- ④ airlines `!` 排除语法 ----

def test_airlines_bang_exclusion():
    rt = _route(airlines="!9C,!春秋")
    assert Alerter._route_filters([_flt()], rt)                       # 非排除项保留
    assert not Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt)             # 码命中排除
    assert not Alerter._route_filters(
        [_flt(airlineCode="HO", airline="春秋航空")], rt)             # 名称片段命中排除
    # 排除+白名单并存：先排除后白名单
    rt2 = _route(airlines="MU,!9C")
    assert Alerter._route_filters([_flt()], rt2)
    assert not Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt2)
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt2)            # 白名单仍生效
    # 纯排除=其余全保（无白名单语义）
    assert Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)


# ---- 全局配置透明化：_OPEN_KEYS bdir + 绝对路径消费面 ----

def test_open_keys_bdir_none_when_empty():
    # 空=系统默认 playwright 缓存位（非本仓可控路径）→ None，
    # 端点按「未自定义」回执，防打开仓库根误导
    assert webui._open_folder_target("bdir", {"crawler": {"browser_dir": ""}}) is None
    assert webui._open_folder_target("bdir", {"crawler": {"browser_dir": "D:/pw-cache"}})
    assert webui._OPEN_KEYS["bdir"]({"crawler": {}}) is None
    # 既有三键不回退
    assert webui._open_folder_target("db", {"output": {"db_path": "data/prices.db"}})


def test_page_consumes_globals_abs_and_route_gates():
    # PAGE 词面钉：绝对路径展示/新增筛选行/快捷挡/卡头摘要词面防回退
    for token in ("globals_abs", "glAbs(", "→ 绝对路径：",
                  "价格上限", "排除跨天", "到达时段窗口",
                  "quickArr", "customArrWin",
                  "到达':'", "!9C,!春秋", 'data-which="bdir"',
                  "系统默认 playwright 缓存位"):
        assert token in webui.PAGE, token


# ---- merged from tests/test_r905_route_advice_has_probe_button.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _route_advice():
    from core.pacing import advise
    now = time.time()
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60))
    paths = {"H5": {"attempts": 10, "ok": 1, "rate": 0.1,
                    "rate_excl_empty": 0.1, "last_at": last}}
    return advise("ctrip", ch={}, paths=paths, now=now,
                  node={"scopes": {"dom": {"paths": paths}}})


def test_route_advice_promises_probe():
    adv = _route_advice()
    assert adv["state"] == "path_degraded", adv
    assert adv["action"] == "route", adv
    assert "自检" in adv["hint"], adv["hint"]


def test_probe_button_covers_every_action_that_promises_it():
    src = open(os.path.join(ROOT, "core", "pacing.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    promised = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {}
        for key_node, value_node in zip(node.keys, node.values):
            if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value, str):
                keys[key_node.value] = value_node
        if "action" not in keys or "hint" not in keys:
            continue
        if "自检" not in (ast.get_source_segment(src, node) or ""):
            continue
        action = keys["action"]
        if isinstance(action, ast.Constant) and isinstance(action.value, str):
            promised.add(action.value)
    assert {"probe", "route"} <= promised, (
        "advise() 里承诺「自检」的 action 集合变了：%s"
        % sorted(promised))

    web = webui_full_src()
    start = web.index("const _advAct=")
    window = web[start:start + 1200]
    cond_start = window.index("if(")
    cond = window[cond_start:window.index("ac.push", cond_start)]
    missing = [a for a in sorted(promised) if a not in cond]
    assert not missing, (
        "这些 action 的 hint 让人点「自检」，但按钮分支没覆盖：%s\n%s"
        % (missing, cond))
    # 按钮本体在条件之后的块里；条件里只需要动作名，别把整个分支
    # 截到第一个 ac.push（那正是 probe 按钮自己）。
    body = window[cond_start:cond_start + 700]
    assert "probeNow" in body and ":probe" in body, (
        "分支没有真的渲染自检按钮：%s" % body)


def _payloads(advice):
    paths = {
        "ctrip": {
            "paths": {"H5": {"attempts": 12, "ok": 5, "rate": 0.417}},
            "retired_paths": [],
            "scopes": {"dom": {"query_rate": 0.95, "query_attempts": 9}},
            "query_attempts": 18, "query_ok": 9,
            "last_ok_at": "2026-11-02 23:00:00",
        },
    }
    pacing = {
        "ok": True, "quiet": {},
        "last_round": {"at": "2026-11-02 23:00:00", "sent": 1,
                       "paced": 0, "fast": 1, "slow": 0, "skip": 0,
                       "trips": []},
        "channels": {
            "ctrip": {"state": "", "needs_login": False, "scene": {},
                      "advice": advice, "health": {}},
        },
        "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
        "coverage": {"sent": ["ctrip"], "ok": ["ctrip"], "ratio": 1.0},
        "recurrences": [], "effect": {}, "iv_rate": {},
    }
    return paths, pacing


