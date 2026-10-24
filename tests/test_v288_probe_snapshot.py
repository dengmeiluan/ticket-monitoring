# -*- coding: utf-8 -*-
"""v1.5.288 探针快照/结果筛选分离与计数口径回归。"""
import threading

import webui


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
                   "to_name": "曼谷", "date": "2026-11-16"}],
        "want": ["ctrip", "tuniu"],
        "legs": [{
            "leg": 0, "from": "SHA", "from_name": "上海", "to": "BKK",
            "to_name": "曼谷", "date": "2026-11-16", "status": "running",
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
    assert "已保持中性视图" in src
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
            {"from": "上海", "to": "北京", "date": "2026-10-25"},
            {"from": "上海", "to": "北京", "date": "2026-10-26"},
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
                   "to_name": "北京", "date": "2026-10-25"}],
        "want": ["slowcancel"], "total": 1,
        "legs": [{"leg": 0, "from": "SHA", "from_name": "上海", "to": "BJS",
                  "to_name": "北京", "date": "2026-10-25", "status": "queued",
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
                              args=("t-cancel", "上海", "北京", "2026-10-25",
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
    old_cfg = getattr(webui._State, "cfg", None)
    old_logger = getattr(webui._State, "logger", None)
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)},
                        "output": {"db_path": str(tmp_path / "x.db")}}
    webui._State.logger = logging.getLogger("test-v288")
    webui._PROBE_AUTH.clear()
    try:
        # empty/calendar-only must never be recorded as session evidence
        webui._record_probe_auth("ctrip", "international", 0, "SHA", "BKK", "2026-11-16")
        assert not webui._PROBE_AUTH
        webui._record_probe_auth("ctrip", "international", 12, "SHA", "BKK", "2026-11-16")
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
        webui._PROBE_AUTH.clear()


def test_empty_info_distinguishes_calendar_fallback_rows():
    src = webui.PAGE
    # 有行但全是日历/补位时，不能落成空白“没有可展示的明细”
    assert "仅有日历/补位参考，无真实明细" in src
    assert "c.shown&&!c.shownReal" in src
    assert "发起探针补明细" in src


def test_probe_retry_bypasses_global_cooldown():
    # 直接读源文件，避免并行编辑时 inspect 行缓存命中邻近函数。
    src = open(webui.__file__, encoding="utf-8").read()
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
