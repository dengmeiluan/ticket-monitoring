# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r340_probe_webui.py
- tests/test_r368_probe_auth_reject.py
- tests/test_r565_probe_badge_no_shift.py
- tests/test_v288_probe_snapshot.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import copy
import crawlers
import json
import logging
import os
import pytest
import re
import sqlite3
import sys
import threading
import time
import webui

from core.models import FlightPrice, Route
from core.storage import PriceStorage
from crawlers import REGISTRY as _REGISTRY
from datetime import date, datetime, timedelta


# ---- merged from tests/test_r340_probe_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_search_view_source_contract():
    src = webui.PAGE
    for needle in ('id="searchview"', 'id="navSearch"', 'id="srxRows"',
                   'id="srxRawWrap"', 'function renderSearch()',
                   'function srxFetchRaw(', '/api/probe/raw?row=',
                   '非原站截图', 'srx-rawaudit'):
        assert needle in src, needle
    assert "v==='search'?'searchview':'cfgview'" in src
    assert "const _hv=location.hash.slice(1).split('/')[0]" in src
    assert "switchView('search',false)" in src


def test_probe_raw_replays_exact_extra(tmp_path):
    dbp = str(tmp_path / "probe.db")
    st = PriceStorage(dbp)
    extra = [
        {"price": 880, "name": "东航MU541", "code": "MU541",
         "depTime": "09:55", "arrTime": "13:40"},
        {"price": 901, "name": "上航FM830", "code": "FM830",
         "depTime": "18:10", "arrTime": "22:20"},
    ]
    fp = FlightPrice("ctrip", "SHA", "BKK", "2026-11-20", 880,
                     extra=json.dumps(extra, ensure_ascii=False))
    st.save(fp)
    conn = sqlite3.connect(dbp)
    rid = conn.execute("SELECT MAX(id) FROM flight_prices").fetchone()[0]
    conn.close()
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        out = webui._probe_raw(rid, 1)
        assert out["ok"] is True
        assert out["raw"]["code"] == "FM830"
        assert out["idx"] == 1 and out["count"] == 2
        assert out["row"]["platform"] == "ctrip"
        assert out["row"]["fetched_at"]
        assert webui._probe_raw(rid, 99)["ok"] is False
        assert webui._probe_raw(999999, 0)["err"] == "row not found"
        with pytest.raises(ValueError):
            webui._probe_raw(0, 0)
    finally:
        webui._State.cfg = old_cfg


def test_user_state_carries_provenance_fields(tmp_path):
    dbp = str(tmp_path / "state.db")
    st = PriceStorage(dbp)
    date = "2026-11-20"
    extra = [{
        "price": 880, "name": "东航MU541", "code": "MU541",
        "depTime": "09:55", "arrTime": "13:40", "depDate": date,
        "totalDuration": "4时45分", "transCity": "",
    }]
    st.save(FlightPrice("ctrip", "SHA", "BKK", date, 880,
                        extra=json.dumps(extra, ensure_ascii=False)))
    route = Route("SHA", "上海", "BKK", "曼谷", [date],
                  alert_direct=1000, alert_transfer=0)
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        stt = webui._user_state({"name": "probe", "routes": [route]})
    finally:
        webui._State.cfg = old_cfg
    f = stt["flights"][0]
    assert f["from"] == "SHA" and f["to"] == "BKK"
    assert f["rowId"] and f["rawIdx"] == 0
    assert f["fetchedAt"]
    assert f["th"] == 1000.0
    assert f["code"] == "MU541"

def test_state_cache_schema_guard():
    """API payload schema 升级后，旧磁盘快照不得回放（r340 实测：
    重启后 8765 仍回旧 body，provenance 字段全缺）。"""
    src = webui_full_src()
    assert "_STATE_SCHEMA = " in src
    assert '"schema": _STATE_SCHEMA' in src
    assert 'meta.get("schema") != _STATE_SCHEMA' in src or            'meta.get("schema")' in src and "_STATE_SCHEMA" in src

def test_probe_city_resolver():
    assert webui._probe_city_code("上海") == ("SHA", "上海")
    assert webui._probe_city_code("曼谷") == ("BKK", "曼谷")
    assert webui._probe_city_code("bkk") == ("BKK", "曼谷")
    assert webui._probe_city_code("") == ("", "")


def test_probe_form_source_contract():
    src = webui.PAGE
    for needle in ('id="srxFrom"', 'id="srxTo"', 'id="srxDate"',
                   'id="srxPlatPick"', 'id="srxGo"', '主动探针',
                   '/api/probe/start', '/api/probe/task', '不入库、不推送'):
        assert needle in src, needle
    assert "function srxProbeRun()" in src
    assert "SRX.probe" in src


# ---- merged from tests/test_r368_probe_auth_reject.py ----

def _setcfg(tmp_path):
    return {"crawler": {"user_data_dir": str(tmp_path)}}


def test_probe_login_refusal_marks_login_required(tmp_path, monkeypatch):
    """A real 1999 login wall must flip the session to 需登录, not stay 可用."""
    old_cfg = getattr(webui._State, "cfg", None)
    old_logger = getattr(webui._State, "logger", None)
    old_reg = crawlers.REGISTRY.get("qunar")
    webui._State.cfg = _setcfg(tmp_path)
    webui._State.logger = logging.getLogger("test-r368")
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    webui._State.login_sessions.clear()
    webui._State.login_pending.clear()

    class _Wall:
        name = "qunar"

        def __init__(self, cfg, logger):
            self.paths = []
            self.probe_mode = False
            self.on_path = None

        def login_url(self):
            return ""

        def fetch(self, fc, tc, dates):
            self.paths = [{
                "path": "H5", "status": "login", "rows": 0,
                "date": dates[0],
                "detail": "国际列表 1999/8 未登录硬拒",
            }]
            return []

    crawlers.REGISTRY["qunar"] = _Wall
    webui._PROBE_LAST = 0
    try:
        # 探针计划拒绝过去日期；用未来日避免跨日把门禁变成日期过期失败
        future = (date.today() + timedelta(days=7)).isoformat()
        webui._probe_search(None, None, None, ["qunar"], legs=[{
            "from": "上海", "to": "曼谷", "date": future}])
        per = webui._PROBE_AUTH["qunar"]["international"]
        assert per.get("auth_ts")
        assert per["auth_reason"].startswith("国际列表")
        view = webui._login_state_view()["plats"]["qunar"]
        scope = view["scopes"]["international"]
        assert scope["needs_login"] is True, "登录墙未进入会话证据"
        assert scope["detail_available"] is False
        assert "1999" in scope["reason"]
        assert view["needs_login"] is True
        assert view["status"] == "login_required"
    finally:
        if old_reg is None:
            crawlers.REGISTRY.pop("qunar", None)
        else:
            crawlers.REGISTRY["qunar"] = old_reg
        webui._State.cfg = old_cfg
        webui._State.logger = old_logger
        webui._PROBE_AUTH.clear()
        webui._PROBE_LAST = 0
        webui._State.login_sessions.clear()
        webui._State.login_pending.clear()


def test_newer_probe_detail_clears_login_refusal(tmp_path, monkeypatch):
    """After a real detail arrives, the same scope must go back to available."""
    old_cfg = getattr(webui._State, "cfg", None)
    old_logger = getattr(webui._State, "logger", None)
    webui._State.cfg = _setcfg(tmp_path)
    webui._State.logger = logging.getLogger("test-r368b")
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    webui._State.login_sessions.clear()
    webui._State.login_pending.clear()
    try:
        now = time.time()
        webui._record_probe_auth_reject(
            "qunar", "international", "国际列表 1999/8 未登录硬拒",
            "SHA", "BKK", "2026-10-24", "H5")
        view = webui._login_state_view()["plats"]["qunar"]
        assert view["needs_login"] is True
        webui._record_probe_auth(
            "qunar", "international", 9, "SHA", "BKK", "2026-10-25")
        # force the new detail to be strictly newer than the refusal
        webui._PROBE_AUTH["qunar"]["international"]["detail_ts"] = now + 5
        webui._PROBE_AUTH["qunar"]["international"]["detail_at"] = (
            datetime.fromtimestamp(now + 5).strftime("%Y-%m-%d %H:%M:%S"))
        view = webui._login_state_view()["plats"]["qunar"]
        scope = view["scopes"]["international"]
        assert scope["needs_login"] is False
        assert scope["detail_available"] is True
        assert view["status"] == "available"
    finally:
        webui._State.cfg = old_cfg
        webui._State.logger = old_logger
        webui._PROBE_AUTH.clear()
        webui._State.login_sessions.clear()
        webui._State.login_pending.clear()


def test_empty_or_timeout_never_marks_login(tmp_path, monkeypatch):
    """Empty/calendar/timeout paths must not be recorded as auth evidence."""
    old_cfg = getattr(webui._State, "cfg", None)
    webui._State.cfg = _setcfg(tmp_path)
    monkeypatch.setattr(webui, "_health_state", lambda hours: {"evidence": {}})
    webui._PROBE_AUTH.clear()
    try:
        webui._record_probe_auth_reject("qunar", "international", "", "SHA", "BKK", "2026-10-24")
        assert not webui._PROBE_AUTH
    finally:
        webui._State.cfg = old_cfg
        webui._PROBE_AUTH.clear()


# ---- merged from tests/test_r565_probe_badge_no_shift.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _text():
    import webui
    return webui_full_src()


def _narrow_block(src):
    i = src.index("@media(max-width:760px){")
    j = src.index("\n  }\n", i)
    return src[i:j]


def _rule(block, sel):
    i = block.index(sel)
    b = block.index("{", i)
    e = block.index("}", b)
    return block[b + 1:e]


def test_title_and_badge_are_block_level_in_narrow_tier():
    block = _narrow_block(_text())
    b = _rule(block, "#searchview .srx-probehead>b")
    em = _rule(block, "#searchview .srx-probehead>em")
    assert "display:block" in b.replace(" ", ""), b
    assert "display:block" in em.replace(" ", ""), em


def test_title_has_fixed_height_so_line_box_cannot_grow():
    block = _narrow_block(_text())
    b = _rule(block, "#searchview .srx-probehead>b").replace(" ", "")
    assert "height:19.5px" in b, b
    assert "line-height:1.5" in b, b
    assert "align-self:flex-start" in b, b


def test_collapsed_card_is_still_block_not_flex():
    """收起态必须是 block——这条是抖动的来源，不能被「统一成 flex」改掉。"""
    src = _text()
    line = "#searchview .srx-probe:not(.open){display:block!important;padding:0!important}"
    assert line in src


def test_badge_keeps_placeholder_when_collapsed():
    """收起态 em 必须靠 visibility:hidden 占位。

    ≤900 档还有一条组规则把 em 写成 display:none，它靠后面同选择器
    的 `display:block!important;visibility:hidden!important` 覆盖——
    判据取源码里最后一条（同特异性下带 !important 者胜），而不是逐条禁。
    """
    src = _text()
    hits = list(re.finditer(
        r"\.srx-probe:not\(\.open\) \.srx-probehead>em\{([^}]*)\}", src))
    assert hits, "collapsed badge rule missing"
    body = hits[-1].group(1).replace(" ", "")
    assert "visibility:hidden" in body, body
    assert "display:none" not in body, body


# ---- merged from tests/test_v288_probe_snapshot.py ----

_D1 = (date.today() + timedelta(days=30)).isoformat()
_D2 = (date.today() + timedelta(days=31)).isoformat()
_D3 = (date.today() + timedelta(days=60)).isoformat()

def test_snapshot_and_result_filter_contract():
    src = webui.PAGE
    for needle in (
        "function srxCountModel(",
        "function srxDateIsSnapshot(",
        "function srxDateLock(",
        "function srxEmptyInfo(",
        "任务快照",
        "结果筛选",
        "清除结果筛选",
        "所选日期未采",
        "原始响应",
        "跨日期",
    ):
        assert needle in src, needle
    # 头部不得再把跨日期总量写成“本轮 N 行”
    assert "' · 本轮 '+real.length" not in src
    # KPI 主卡改为本次明细，日历/补位进入次级行
    assert "k('本轮解析行'" not in src
    assert "k('本次明细'" in src
    # 单腿探针日期是快照，不得进入可删结果筛选
    assert "if(SRX.date&&!snap)" in src
    assert "if(srxDateLock()){toast('已提交任务的日期是快照" in src
    # 组合探针 pair 为空时 brief 会提前返回，capbar 必须独立渲染
    assert "srxRenderBrief();srxRenderCapbar();" in src


def test_task_view_exposes_request_channels_and_real_statuses():
    task = {
        "id": "t1", "status": "running", "created": 1.0, "started": 1.0,
        "updated": 2.0, "finished": None, "total": 2,
        "plans": [{"from": "SHA", "from_name": "上海", "to": "BKK",
                   "to_name": "曼谷", "date": _D3}],
        "want": ["ctrip", "tuniu"],
        "legs": [{
            "leg": 0, "from": "SHA", "from_name": "上海", "to": "BKK",
            "to_name": "曼谷", "date": _D3, "status": "running",
            "rows": 3, "detail": 3, "cal": 0,
            "channels": {
                "ctrip": {"status": "ok", "phase": "完成", "n": 3,
                          "detail": 3, "cal": 0, "raw_n": 1, "paths": []},
                "tuniu": {"status": "running", "phase": "解析明细", "n": 0,
                          "detail": 0, "cal": 0, "raw_n": 0, "paths": []},
            },
        }],
        "rows": [], "rowkeys": set(), "events": [], "cancel": threading.Event(),
        "truncated": False, "err": "",
    }
    webui._PROBE_TASKS["t1"] = task
    try:
        view = webui._probe_task_view("t1")
    finally:
        webui._PROBE_TASKS.pop("t1", None)
    assert view["want"] == ["ctrip", "tuniu"]
    assert view["done"] == 1 and view["total"] == 2
    assert view["legs"][0]["channels"]["ctrip"]["detail"] == 3
    assert view["legs"][0]["channels"]["tuniu"]["phase"] == "解析明细"
    assert view["legs"][0]["channels"]["tuniu"]["status"] == "running"


def test_neutral_first_entry_does_not_restore_query():
    src = webui.PAGE
    # jpsrx2 只恢复展示偏好，条件必须显式确认
    assert "['sort','view','calAxis','dtab','fieldFilter','mch','mview']" in src
    assert "SRX.restoreChip=parts.join" in src
    assert "恢复上次条件" in src
    # 首次进入/切换用户不得保留旧渠道、关键词或结果筛选
    assert "SRX.plats=[];SRX.q='';SRX.f={...SRX_DEFAULT_F};SRX.agg=false" in src


def test_batch_incremental_does_not_reset_user_scope():
    src = webui.PAGE
    assert "if(!prev&&!opt.keepScope){" in src
    assert "if(SRX.probe.batch){SRX.pair='';SRX.date=''}" in src


def _row_extra():
    return __import__("json").dumps([{
        "price": 100, "code": "XX123", "name": "测试航XX123",
        "depTime": "08:00", "arrTime": "10:00", "cabin": "经济舱",
    }], ensure_ascii=False)


def test_probe_global_channel_gate_and_same_platform_serialization(monkeypatch):
    import json
    import threading
    import time
    from types import SimpleNamespace
    import crawlers

    state = {"active": 0, "max": 0, "plat_active": {}, "plat_max": {}}
    lock = threading.Lock()

    class _Slow:
        name = "slow"

        def __init__(self, cfg, logger):
            pass

        def fetch(self, fc, tc, dates):
            p = self.name
            with lock:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
                state["plat_active"][p] = state["plat_active"].get(p, 0) + 1
                state["plat_max"][p] = max(state["plat_max"].get(p, 0),
                                           state["plat_active"][p])
            time.sleep(0.2)
            with lock:
                state["active"] -= 1
                state["plat_active"][p] -= 1
            return [SimpleNamespace(price=100, airline="测试航", flight_no="XX123",
                                    depart_time="08:00", arrive_time="10:00",
                                    extra=_row_extra())]

    crawlers.REGISTRY["slow"] = _Slow
    old_cfg = getattr(webui._State, "cfg", None)
    webui._State.cfg = {"crawler": {}}
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(None, None, None, ["slow"], legs=[
            {"from": "上海", "to": "北京", "date": _D1},
            {"from": "上海", "to": "北京", "date": _D2},
        ])
        assert len(j["rows"]) == 2
        assert state["max"] <= 2
        assert state["plat_max"]["slow"] == 1
    finally:
        crawlers.REGISTRY.pop("slow", None)
        webui._State.cfg = old_cfg
        webui._PROBE_LAST = 0


def test_probe_result_status_distinguishes_blockers_from_empty():
    assert webui._probe_result_status([], [{"status": "blocked"}]) == "challenge"
    assert webui._probe_result_status([], [{"status": "login"}]) == "login_required"
    assert webui._probe_result_status([], [{"status": "timeout"}]) == "timeout"
    assert webui._probe_result_status([], [{"status": "error"}]) == "error"
    assert webui._probe_result_status([], [{"status": "empty"}]) == "empty"
    assert webui._probe_result_status([{"price": 1}], []) == "ok"
    assert webui._probe_result_status([{"price": 1}], [{"status": "login"}]) == "partial"


def test_cancel_preserves_fetched_rows():
    import json
    import threading
    import time
    from types import SimpleNamespace
    import crawlers

    class _Slow:
        name = "slowcancel"

        def __init__(self, cfg, logger):
            pass

        def fetch(self, fc, tc, dates):
            time.sleep(0.25)
            return [SimpleNamespace(price=100, airline="测试航", flight_no="XX123",
                                    depart_time="08:00", arrive_time="10:00",
                                    extra=_row_extra())]

    crawlers.REGISTRY["slowcancel"] = _Slow
    old_cfg = getattr(webui._State, "cfg", None)
    webui._State.cfg = {"crawler": {}}
    webui._PROBE_LAST = 0
    cancel = threading.Event()
    task = {
        "id": "t-cancel", "status": "running", "created": time.time(),
        "started": time.time(), "updated": time.time(), "finished": None,
        "plans": [{"from": "SHA", "from_name": "上海", "to": "BJS",
                   "to_name": "北京", "date": _D1}],
        "want": ["slowcancel"], "total": 1,
        "legs": [{"leg": 0, "from": "SHA", "from_name": "上海", "to": "BJS",
                  "to_name": "北京", "date": _D1, "status": "queued",
                  "rows": 0, "detail": 0, "cal": 0,
                  "channels": {"slowcancel": {"status": "queued", "phase": "排队",
                                              "n": 0, "detail": 0, "cal": 0,
                                              "ms": 0, "err": ""}}}],
        "rows": [], "rowkeys": set(), "events": [], "cancel": cancel,
        "truncated": False, "err": "",
    }
    webui._PROBE_TASKS["t-cancel"] = task
    try:
        th = threading.Thread(target=webui._probe_start_task,
                              args=("t-cancel", "上海", "北京", _D1,
                                    None, ["slowcancel"]), daemon=True)
        th.start()
        time.sleep(0.08)
        cancel.set()
        th.join(10)
        view = webui._probe_task_view("t-cancel")
        assert view is not None
        assert view["status"] == "cancelled"
        assert view["rows_total"] >= 1
        assert view["legs"][0]["channels"]["slowcancel"]["detail"] >= 1
    finally:
        crawlers.REGISTRY.pop("slowcancel", None)
        webui._State.cfg = old_cfg
        webui._PROBE_TASKS.pop("t-cancel", None)
        webui._PROBE_LAST = 0


def test_probe_detail_evidence_updates_session_without_empty_inference(tmp_path, monkeypatch):
    import logging
    import crawlers
    old_cfg = getattr(webui._State, "cfg", None)
    old_logger = getattr(webui._State, "logger", None)
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)},
                        "output": {"db_path": str(tmp_path / "x.db")}}
    webui._State.logger = logging.getLogger("test-v288")
    # 健康证据来自真实 monitor.log；本测试只验证「探针明细」的推理边界，
    # 不能让本机日志里恰好存在的途牛明细把断言顶成 available。
    monkeypatch.setattr(webui, "_health_state",
                        lambda *a, **k: {"evidence": {}})
    # _login_state_view 的状态优先级是 active > rejected > error > pending >
    # available：本机或前序用例（登录保存成功/失败的用例）在
    # _State.login_errors / login_sessions / login_pending 里留下的记录
    # 会盖过本用例喂的探针证据，全量跑时曾把 available 判成 save_error
    # （单跑必绿、全量必红）。本用例只验证探针证据的推理边界，先把这三份
    # 全局态清空，退出时还原。
    _globals = ("login_errors", "login_sessions", "login_pending")
    _old_globals = {k: copy.deepcopy(getattr(webui._State, k)) for k in _globals}
    for _k in _globals:
        setattr(webui._State, _k, {})
    _old_reg = dict(crawlers.REGISTRY)
    webui._PROBE_AUTH.clear()
    try:
        # empty/calendar-only must never be recorded as session evidence
        webui._record_probe_auth("ctrip", "international", 0, "SHA", "BKK", _D3)
        assert not webui._PROBE_AUTH
        webui._record_probe_auth("ctrip", "international", 12, "SHA", "BKK", _D3)
        view = webui._login_state_view()
        scope = view["plats"]["ctrip"]["scopes"]["international"]
        assert scope["probe_count"] == 12
        assert scope["detail_available"] is True
        assert view["plats"]["ctrip"]["status"] == "available"
        # no detail for this channel => no invented availability
        assert view["plats"]["tuniu"]["status"] != "available"
    finally:
        webui._State.cfg = old_cfg
        webui._State.logger = old_logger
        for _k, _v in _old_globals.items():
            setattr(webui._State, _k, _v)
        crawlers.REGISTRY.clear()
        crawlers.REGISTRY.update(_old_reg)
        webui._PROBE_AUTH.clear()


def test_empty_info_distinguishes_calendar_fallback_rows():
    src = webui.PAGE
    # 有行但全是日历/补位时，不能落成空白“没有可展示的明细”
    assert "仅有日历/补位参考，无真实明细" in src
    assert "c.shown&&!c.shownReal" in src
    assert "发起探针补明细" in src


def test_probe_retry_bypasses_global_cooldown():
    # 直接读源文件，避免并行编辑时 inspect 行缓存命中邻近函数。
    src = webui_full_src()
    assert "def _probe_search(" in src
    assert "retry=False" in src
    assert "if not retry and _now0 - _PROBE_LAST" in src
    assert "if not retry and _now0 - _PROBE_LAST" in src
    assert "retry=retry" in src
    assert "retry:true" in webui.PAGE
    assert "o.retry)_p.retry=true" in webui.PAGE


def test_audit_fixes_counts_filters_status_and_exit():
    src = webui.PAGE
    # other-date count must honor result channel filter
    assert "base.filter(f=>ps.has(f.platKey)&&(!SRX.date||f.date!==SRX.date))" in src
    # filter-empty must be evaluated before fallback-only
    i_filter = src.index("kind:'filter',title:'筛选无结果'")
    i_fallback = src.index("kind:'fallback',title:'仅有日历/补位参考")
    assert i_filter < i_fallback
    # task channel status must preserve login/blocked severity, not collapse to ok
    assert "login_required:5,blocked:5,challenge:5" in src
    # retry must keep submitted scope and batch view
    assert "keepScope:!!o.merge,forceBatch:!!o.merge" in src
    assert "if(!prev&&!opt.keepScope)" in src
    # exiting probe cancels a running backend task, clears the task view and
    # closes the probe panel (no unpolled "采集中" shell)
    assert "function srxExitProbe(){\n const running=" in src
    assert "if(running)srxTaskCancel();" in src
    assert "SRX_TASK_GEN++" in src
    assert "_pp.classList.remove('open')" in src
    # session chip must not claim recent detail while current run is rejected
    assert "会话 本次需登录" in src
