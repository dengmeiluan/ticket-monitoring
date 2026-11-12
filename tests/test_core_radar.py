# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r696_radar_app_channel_frontend.py
- tests/test_r709_radar_covers_all_channels.py
- tests/test_r813b_radar_zhixing_rendered.py
- tests/test_v295_radar_alert_store.py
- tests/test_v295_radar_scope.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
from support_webui_src import webui_full_src

import json
import os
import pytest
import re
import socket
import subprocess
import sys
import time
import urllib.request

from core.channels import APP_CHANNELS, BROWSER_CHANNELS
from core.special_radar import _CHANNELS
from core.specials import SPECIAL_CAPABILITY
from core.storage import PriceStorage


# ---- merged from tests/test_r696_radar_app_channel_frontend.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _src():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_names_are_lazy_not_immediately_evaluated():
    """渠道名必须是**惰性**函数，不能在顶层立刻读 SRX_PLATS。"""
    s = _src()
    assert "function srxRadarName(" in s, "缺少惰性取名函数"
    assert "function srxRadarChannelKeys(" in s, "缺少惰性取键函数"
    assert "SRX_RADAR_NAMES=(function(){" not in s, \
        "渠道名表仍在顶层立刻求值（会撞 SRX_PLATS 的 TDZ，整页挂掉）"


def test_name_lookup_covers_app_channels():
    s = _src()
    i = s.index("function srxRadarName(")
    block = s[i:i + 360]
    assert "SRX_PLATS" in block and "APP_PLAT_NAME" in block, \
        "取名函数没有同时读两张表，App 渠道会露裸 id"


def test_config_chips_not_limited_to_browser_keys():
    s = _src()
    i = s.index("<b>查询渠道</b>")
    block = s[i:i + 900]
    assert "srxRadarChannelKeys()" in block, \
        "配置页芯片仍用 SRX_PLAT_KEYS，App 渠道勾不到"
    assert "SRX_PLAT_KEYS.map" not in block


def test_radar_chip_list_covers_every_app_source():
    """可勾选清单必须覆盖**所有已接入发现源**的 App 渠道。

    旧断言把「智行未接入」钉成期望，而 r732 已把智行「特价」接成逐天
    报价源（SPECIAL_CAPABILITY + 后端分发都在）；白名单没跟上，结果是
    勾得到、请求被静默丢弃。改为守「有源就必须可勾选」。
    """
    s = _src()
    i = s.index("var SRX_RADAR_APP_KEYS=")
    block = s[i:i + 120]
    assert "app_qunar" in block, block
    assert "app_zhixing" in block, \
        "智行已有真实发现源，可勾选清单不能再把它排除"


def test_no_bare_srx_plats_lookup_left():
    s = _src()
    assert not re.findall(r"SRX_PLATS\[b\.channel\]", s)
    assert not re.findall(r"SRX_RADAR_NAMES", s), \
        "仍有地方引用已删除的 SRX_RADAR_NAMES"


def test_radar_app_channels_known_to_both_tables():
    """后端有的雷达渠道，前端两张来源表都必须能给出名字。"""
    import core.special_radar as sr
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    known = set(BROWSER_CHANNELS) | set(APP_CHANNELS)
    for ch in sr._CHANNELS:
        assert ch in known, "%s 后端有、前端两张表都没有" % ch


# ---- merged from tests/test_r709_radar_covers_all_channels.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_special_entry_channels_not_hardcoded():
    src = _webui()
    m = re.search(r"function srxSpecialEntryHTML\([\s\S]{0,1600}", src)
    assert m, "找不到 srxSpecialEntryHTML"
    body = m.group(0)
    assert "SRX_PLAT_KEYS" in body or "SRX_PLATS" in body, (
        "特价雷达入口的渠道清单又写死了——新增渠道会再次从界面消失")
    # 去掉注释后，不应再有写死的五家清单字面量
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    body = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.splitlines())
    assert not re.search(r"\[\s*'ctrip'\s*,\s*'qunar'", body), body[:300]


def test_capability_covers_every_app_channel():
    for plat in APP_CHANNELS:
        assert plat in SPECIAL_CAPABILITY, (
            "%s 没有特价能力声明：雷达里它会彻底消失，用户看不出「这家有没有"
            "特价、为什么没参与」" % plat)
        entry = SPECIAL_CAPABILITY[plat]
        assert "note" in entry and entry["note"], plat


def test_radar_channels_have_declared_sources():
    for plat in _CHANNELS:
        entry = SPECIAL_CAPABILITY.get(plat)
        assert entry is not None, "%s 在雷达白名单里但能力表没有" % plat


def test_every_channel_with_source_is_radar_selectable():
    """有发现源 ⇒ 可选；声明过但无源的渠道也必须保留可选。

    r805cj：app_qunar 的入口变成 H5 WebView（不可读），sources 清空、
    矩阵记 n；但用户要求「统一监控」，不能让它从雷达里消失——查询它
    必须返回 not_connected + 原因。因此白名单 = **能力表全部声明键**，
    而有源的渠道是其子集。
    """
    missing = [p for p in (list(APP_CHANNELS) + list(BROWSER_CHANNELS))
               if p not in SPECIAL_CAPABILITY]
    assert not missing, "这些渠道在特价雷达里没有声明：%s" % missing
    with_source = tuple(p for p, e in SPECIAL_CAPABILITY.items()
                        if e.get("sources"))
    assert set(with_source) <= set(_CHANNELS), (
        "有发现源的渠道没进雷达白名单：%s" % (set(with_source) - set(_CHANNELS)))
    assert set(_CHANNELS) == set(SPECIAL_CAPABILITY), (
        "雷达白名单必须与能力声明一致（含无源但需显示原因的渠道）：%s"
        % (set(_CHANNELS) ^ set(SPECIAL_CAPABILITY)))
    # r732 更正了旧结论：智行「特价」不是目的地榜，而是与去哪儿 App 同一
    # 契约的「一条航线 × 逐天报价」。断言守「有源 + 写清口径边界」，
    # 不再要求 note 里出现已被推翻的「目的地」。
    zx = SPECIAL_CAPABILITY.get("app_zhixing") or {}
    assert zx.get("sources"), "智行已有逐天报价发现源，sources 不能是空的"
    assert "口径" in (zx.get("note") or ""), (
        "note 要写清价格口径边界（页面未标含税），否则读者会误当含税价")


def test_zhixing_channel_survives_query_filter():
    """往返：带智行的请求必须原样留下，不能被白名单静默丢掉。"""
    from core.special_radar import parse_query
    q = parse_query({"from": "上海", "to": "北京",
                     "start": "2026-12-01", "end": "2026-12-03",
                     "channels": ["app_zhixing"]})
    assert q.channels == ["app_zhixing"], q.channels


def test_frontend_app_keys_mirror_declared_app_channels():
    """前端可勾选 App 清单与后端「已声明」的 App 渠道一致。

    r805cj：app_qunar 仍要出现在界面上（点了会显示「未接入」原因），
    所以镜像的是**声明**而非「有源」。
    """
    src = _webui()
    m = re.search(r"var SRX_RADAR_APP_KEYS=\[([^\]]*)\]", src)
    assert m, "找不到 SRX_RADAR_APP_KEYS"
    fe = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    be = set(APP_CHANNELS) & set(SPECIAL_CAPABILITY)
    assert fe == be, "前端可勾选 %s / 后端已声明 %s" % (sorted(fe), sorted(be))


# ---- merged from tests/test_r813b_radar_zhixing_rendered.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port










# ---- merged from tests/test_v295_radar_alert_store.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_alert_config_defaults_and_upsert(tmp_path):
    st = PriceStorage(str(tmp_path / "cfg.db"))
    assert st.radar_alert_config("u") == {
        "enabled": False, "drop_min": 50.0, "threshold": 0.0,
        "cooldown_h": 12.0}
    st.set_radar_alert_config("u", {
        "enabled": False, "drop_min": 80, "threshold": 450,
        "cooldown_h": 6})
    assert st.radar_alert_config("u") == {
        "enabled": False, "drop_min": 80.0, "threshold": 450.0,
        "cooldown_h": 6.0}


def test_alert_state_upsert_and_history(tmp_path):
    st = PriceStorage(str(tmp_path / "st.db"))
    st.save_radar_alert_state("u", "q", "2026-11-01", 500,
                              "2026-10-24T10:00:00", "ctrip", "bare")
    got = st.get_radar_alert_state("u", "q", "2026-11-01")
    assert got["low_price"] == 500 and got["armed"] == 1
    st.save_radar_alert_state("u", "q", "2026-11-01", 450,
                              "2026-10-24T12:00:00", "fliggy", "bare",
                              450, "2026-10-24T12:00:00", 0)
    got = st.get_radar_alert_state("u", "q", "2026-11-01")
    assert got["low_price"] == 450 and got["armed"] == 0
    assert got["low_channel"] == "fliggy"
    rid = st.record_radar_alert(
        "u", "q", "2026-11-01", 450, 500, "fliggy", "bare", "new_low",
        "", "[]", "sent")
    assert rid > 0
    alerts = st.radar_alerts("u")
    assert alerts[0]["kind"] == "new_low" and alerts[0]["status"] == "sent"


# ---- merged from tests/test_v295_radar_scope.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _q(to, start, end, channels=("ctrip",)):
    return {"from": "SHA", "to": to, "nationwide": False,
            "start": start, "end": end, "channels": list(channels)}


def _result(day, price, to="BJS", channel="ctrip"):
    return {"dates": [{
        "date": day,
        "by_channel": {channel: {
            "price": price, "to": to, "basis": "bare",
            "kind": "calendar", "link": ""}},
    }]}


def test_query_key_is_stable_and_channel_scoped(tmp_path):
    st = PriceStorage(str(tmp_path / "q.db"))
    k1 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))
    k2 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07",
                               ("fliggy", "ctrip")))
    assert k1 != k2
    assert k1 == st.radar_query_key(
        _q("BJS", "2026-11-01", "2026-11-07"))


def test_history_does_not_mix_routes(tmp_path):
    st = PriceStorage(str(tmp_path / "h.db"))
    st.save_radar_snapshot("u", _q("BJS", "2026-11-01", "2026-11-07"),
                           _result("2026-11-01", 500, "BJS"))
    st.save_radar_snapshot("u", _q("CAN", "2026-12-01", "2026-12-07"),
                           _result("2026-12-01", 400, "CAN"),
                           run_status="ok")
    q1 = st.radar_query_key(_q("BJS", "2026-11-01", "2026-11-07"))
    h = st.radar_history("u", query_key=q1)
    assert h["query"]["to"] == "BJS"
    assert [d["date"] for d in h["dates"]] == ["2026-11-01"]
    latest = st.radar_history("u")
    assert latest["query"]["to"] == "CAN"
    assert latest["query_key"] == st.radar_query_key(
        _q("CAN", "2026-12-01", "2026-12-07"))


def test_non_ok_run_is_ledger_only(tmp_path):
    st = PriceStorage(str(tmp_path / "r.db"))
    q = _q("BJS", "2026-11-01", "2026-11-07")
    n = st.save_radar_snapshot("u", q, _result("2026-11-01", 500),
                               run_status="cache_hit")
    assert n == 0
    h = st.radar_history("u")
    assert h["dates"] == []
    assert h["last_run"]["status"] == "cache_hit"
    assert h["query"]["to"] == "BJS"


def test_old_snapshot_table_is_migrated(tmp_path):
    import sqlite3
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE radar_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL,
        from_city TEXT NOT NULL, to_city TEXT NOT NULL,
        nationwide INTEGER NOT NULL DEFAULT 0,
        depart_date TEXT NOT NULL, channel TEXT NOT NULL,
        price REAL NOT NULL, tax_included INTEGER NOT NULL DEFAULT -1,
        basis TEXT, kind TEXT, link TEXT, query_start TEXT,
        query_end TEXT, fetched_at TEXT NOT NULL);
    """)
    c.execute("INSERT INTO radar_snapshots (user,from_city,to_city,nationwide,"
              "depart_date,channel,price,tax_included,basis,kind,link,"
              "query_start,query_end,fetched_at) VALUES "
              "('u','SHA','BJS',0,'2026-11-01','ctrip',500,1,'bare',"
              "'calendar','','2026-11-01','2026-11-07','2026-10-24 10:00:00')")
    c.commit()
    c.close()
    st = PriceStorage(p)
    h = st.radar_history("u")
    assert h["query"]["to"] == "BJS"
    assert h["dates"][0]["price"] == 500
