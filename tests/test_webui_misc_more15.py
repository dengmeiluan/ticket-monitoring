# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r339h_airalias.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import main
import os
import pytest
import sys
import urllib.request

from core.airlines import alias_payload, resolve_codes


# ---- merged from tests/test_r339h_airalias.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 1. 别称解析单源 ----

def test_resolve_three_writings():
    assert resolve_codes("东航") == {"MU"}
    assert resolve_codes("东方航空") == {"MU"}
    assert resolve_codes("MU") == {"MU"}
    assert resolve_codes("mu") == {"MU"}          # 码大小写不敏感
    assert resolve_codes("春秋") == {"9C"}
    assert resolve_codes(" 国航 ") == {"CA"}       # 首尾空白容忍


def test_resolve_unknown_is_empty():
    """表外条目=空集（匹配面退回名称片段兜底，别名表只做增量）。"""
    assert resolve_codes("桦航") == frozenset()
    assert resolve_codes("") == frozenset()


def test_payload_shape():
    p = alias_payload()
    assert p["alias"]["东航"] == "MU" and p["alias"]["MU"] == "MU"
    assert p["alias"]["中国东方航空"] == "MU"
    assert p["name"]["MU"] == "中国东方航空"
    # 数据保守律抽验：错别称不得混入（南航≠CZ 以外公司）
    assert p["alias"]["南航"] == "CZ" and p["alias"]["海航"] == "HU"


# ---- 2. 筛选双门集成（白名单 + ! 排除） ----

def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False}
    d.update(kw)
    return d


def _route(airlines):
    return main.build_routes([
        {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1000,
         "airlines": airlines}])[0]


def test_whitelist_short_alias_matches():
    """用户点名案：写「东航」必须等价「东方航空」（MU 行保留）。"""
    from core.alerter import Alerter
    rt = _route("东航")
    assert Alerter._route_filters([_flt()], rt)              # 简称→码
    assert Alerter._route_filters(
        [_flt(airlineCode="MU", airline="中国东方航空")], rt)  # 全称行
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)      # 他司照剔


def test_whitelist_full_name_and_mixed():
    from core.alerter import Alerter
    rt = _route("东方航空,9C")
    assert Alerter._route_filters([_flt()], rt)
    assert Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt)
    rt2 = _route("MU,东航")   # 混写：码+简称
    assert Alerter._route_filters([_flt()], rt2)


def test_ban_short_alias_excludes():
    from core.alerter import Alerter
    rt = _route("!东航")
    assert not Alerter._route_filters([_flt()], rt)           # 排除表同接
    assert Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)      # 他司保留


def test_unknown_entry_falls_back_to_fragment():
    """表外条目零行为回退：名称片段匹配照旧（fail-close 语义不变）。"""
    from core.alerter import Alerter
    rt = _route("东方")     # 非全称非简称→片段兜底
    assert Alerter._route_filters([_flt()], rt)
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)


# ---- 3. PAGE 词面与载荷接线 ----

def _page_src():
    import webui
    return webui.PAGE


def test_page_preview_and_hint():
    src = _page_src()
    assert "function airPreviewHTML(" in src
    assert "function airPreview(" in src
    assert 'id="airpv-${i}-${j}"' in src
    assert "oninput=\"airPreview(${i},${j},this)\"" in src
    # 提示词面：三写法等价承诺明示（用户点名问题的正面回答）
    assert "码 / 全称 / 简称" in src and "三写法等价" in src
    # placeholder 与匹配面一致（旧「MU,9C,东航」写法本就命中——码全等；
    # 新示例覆盖排除语法展示面）
    assert 'placeholder="如 MU,东航,!9C"' in src


def test_airalias_payload_wired_in_demo():
    """demo 载荷带 airline_alias（预览与后端同源的前半链）。"""
    from core.demo import build_demo_db, demo_cfg, demo_health
    import webui
    # 载荷组装函数级验证（不起服务）：_airalias 单源直查
    a = webui._airalias()
    assert a["alias"]["东航"] == "MU" and a["name"]["MU"]


# ---- 4. 行为钉（demo 实例真跑：输入即预览） ----

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _wait_up(proc, base):
    import time
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        if proc.poll() is not None:
            return False
        try:
            op.open(base + "/", timeout=1).read(64)
            return True
        except Exception:
            time.sleep(0.25)
    return False





