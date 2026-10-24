# -*- coding: utf-8 -*-
"""v1.5.284 组合探针：多航线/日期校验、逐腿状态与合并行身份。"""
import json
from types import SimpleNamespace

import pytest

import crawlers
import webui
from crawlers.base import BaseCrawler


class _FakeCrawler:
    def __init__(self, cfg, logger):
        pass

    def fetch(self, fc, tc, dates):
        d = dates[0]
        items = [
            {"price": 100, "code": "XX123", "name": "测试航XX123",
             "depTime": "08:00", "arrTime": "10:00", "depDate": d,
             "cabin": "经济舱"},
            {"price": 120, "code": "XX456", "name": "测试航XX456",
             "depTime": "12:00", "arrTime": "14:00", "depDate": d,
             "cabin": "公务舱"},
        ]
        return [SimpleNamespace(price=100, airline="测试航", flight_no="XX123",
                                depart_time="08:00", arrive_time="10:00",
                                extra=json.dumps(items, ensure_ascii=False))]


class _PathFakeCrawler(_FakeCrawler, BaseCrawler):
    def fetch(self, fc, tc, dates):
        self.path_reset()
        self.path_note("PC", "empty", date=dates[0], detail="PC 无明细")
        self.path_note("H5", "login", date=dates[0], detail="会话门拒")
        self.path_note("API", "ok", rows=2, date=dates[0], detail="接口明细")
        return super().fetch(fc, tc, dates)


@pytest.fixture()
def fake_plat():
    crawlers.REGISTRY["fake"] = _FakeCrawler
    webui._PROBE_LAST = 0
    old = getattr(webui._State, "cfg", None)
    webui._State.cfg = {"crawler": {}}
    try:
        yield "fake"
    finally:
        crawlers.REGISTRY.pop("fake", None)
        webui._State.cfg = old
        webui._PROBE_LAST = 0


def test_batch_probe_two_legs(fake_plat):
    j = webui._probe_search(None, None, None, [fake_plat], legs=[
        {"from": "上海", "to": "北京", "date": "2026-10-25"},
        {"from": "上海", "to": "纽约", "date": "2026-11-16"},
    ])
    assert j["ok"] and j.get("batch") is True
    assert len(j["legs"]) == 2
    assert [x["rows"] for x in j["legs"]] == [2, 2]
    assert all(x["status"] == "ok" for x in j["legs"])
    assert len(j["rows"]) == 4
    labels = {r["routeLabel"] for r in j["rows"]}
    assert labels == {"上海→北京", "上海→纽约"}
    assert {r["date"] for r in j["rows"]} == {"2026-10-25", "2026-11-16"}
    assert all("leg" in r and r["flightKey"] for r in j["rows"])
    assert {r["leg"] for r in j["rows"]} == {0, 1}
    assert {r["cabin"] for r in j["rows"]} == {"经济舱", "公务舱"}
    assert {r["date"] for r in j["rows"] if r["leg"] == 0} == {"2026-10-25"}
    assert len({r["rowKey"] for r in j["rows"]}) == 4


def test_batch_probe_rejects_over_limit_and_bad_leg(fake_plat):
    with pytest.raises(ValueError, match="最多 4 条"):
        webui._probe_search(None, None, None, [fake_plat], legs=[
            {"from": "上海", "to": "北京", "date": "2026-10-25"}] * 5)
    webui._PROBE_LAST = 0
    with pytest.raises(ValueError, match="第 2 条"):
        webui._probe_search(None, None, None, [fake_plat], legs=[
            {"from": "上海", "to": "北京", "date": "2026-10-25"},
            {"from": "上海", "to": "上海", "date": "2026-10-26"},
        ])


def test_per_leg_channels_only_run_requested_leg():
    """失败重试逐腿渠道：每条腿只跑自己的失败渠道，不复制到全腿。"""
    calls_a, calls_b = [], []

    def _mk(label, sink):
        class _C:
            def __init__(self, cfg, logger):
                pass

            def fetch(self, fc, tc, dates):
                sink.append((fc, tc, dates[0]))
                return []
        return _C

    crawlers.REGISTRY["legacy_a"] = _mk("a", calls_a)
    crawlers.REGISTRY["legacy_b"] = _mk("b", calls_b)
    old = getattr(webui._State, "cfg", None)
    webui._State.cfg = {"crawler": {}}
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(
            None, None, None, ["legacy_a", "legacy_b"],
            legs=[{"from": "上海", "to": "北京", "date": "2026-10-25"},
                  {"from": "上海", "to": "广州", "date": "2026-10-25"}],
            leg_wants={0: ["legacy_a"], 1: ["legacy_b"]})
        assert calls_a == [("SHA", "BJS", "2026-10-25")]
        assert calls_b == [("SHA", "CAN", "2026-10-25")]
        assert j["legs"][0]["channels"].keys() == {"legacy_a"}
        assert j["legs"][1]["channels"].keys() == {"legacy_b"}
    finally:
        crawlers.REGISTRY.pop("legacy_a", None)
        crawlers.REGISTRY.pop("legacy_b", None)
        webui._State.cfg = old
        webui._PROBE_LAST = 0


def test_single_probe_response_keeps_legacy_shape(fake_plat):
    j = webui._probe_search("上海", "北京", "2026-10-25", [fake_plat])
    assert j["ok"] and "batch" not in j
    assert j["from"] == "SHA" and j["to"] == "BJS"
    assert j["date"] == "2026-10-25" and len(j["rows"]) == 2
    assert j["channels"][fake_plat]["status"] == "ok"


def test_probe_channel_paths_are_reported(fake_plat):
    crawlers.REGISTRY["pathfake"] = _PathFakeCrawler
    try:
        j = webui._probe_search("上海", "北京", "2026-10-25",
                                ["pathfake"])
        paths = j["channels"]["pathfake"]["paths"]
        assert [(x["path"], x["status"], x["rows"]) for x in paths] == [
            ("PC", "empty", 0), ("H5", "login", 0), ("API", "ok", 2)]
        assert paths[1]["detail"] == "会话门拒"
    finally:
        crawlers.REGISTRY.pop("pathfake", None)


def test_tuniu_pc_items_parse_real_shape():
    from crawlers.tuniu import TuniuCrawler
    items = [{
        "airline": "东航", "fn": "MU5195 32N", "dep": "18:00",
        "depAir": "浦东机场T1", "arr": "20:15", "arrAir": "大兴机场",
        "dur": "2h15m", "rate": "100%", "price": "经济舱¥405起",
        "cross": "20:15", "rowText": "东航 MU5195 18:00 20:15",
    }, {
        "airline": "国航", "fn": "CA8322 320", "dep": "06:55",
        "depAir": "浦东机场T2", "arr": "09:25", "arrAir": "大兴机场",
        "dur": "2h30m", "rate": "81%", "price": "经济舱¥500起",
        "cross": "09:25", "rowText": "国航 CA8322",
    }]
    rows = TuniuCrawler._parse_pc_items(items, "2026-10-24")
    assert len(rows) == 2
    assert rows[0]["code"] == "MU5195"
    assert rows[0]["price"] == 405.0
    assert rows[0]["depTime"] == "18:00" and rows[0]["arrTime"] == "20:15"
    assert rows[0]["depAirport"] == "浦东机场T1"
    assert rows[0]["cabin"] == "经济舱"
    assert rows[0]["source"] == "tuniu_pc"



def test_field_audit_cabin_uses_real_cabin_only():
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "{k:'cabin',label:'舱位',raw:['cabin','cabinName'],get:f=>f.cabin||''" in src
    assert "get:f=>f.cabinT||f.cabinCode" not in src
    assert "(_g0.cabinT||_g0.cabinCode?' · '+he(srxCabinClass(_g0)):'')" not in src


def test_batch_probe_ui_wiring():
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "function srxProbeAddLeg()" in src
    assert "function srxProbeRunBatch()" in src
    assert "function srxShownRows(rows)" in src
    assert "body:JSON.stringify(_p)" in src and "/api/probe/start" in src
    assert "if(o.retry)_p.retry=true" in src
    assert "if(SRX.probe&&SRX.probe.batch){" in src and "let a=srxAll();" in src
    assert "组合探针 · 未入库" in src
    assert "function srxTaskStart(payload,opts)" in src
    assert "srx-batchlist" in src
    assert "function srxTaskPaths(lg)" in src and "srx-tpaths" in src
    assert "人机验证" in src
    assert "max_workers=min(2" in src


def test_watch_identity_cannot_move_to_past_date():
    base = {"from": "SHA", "to": "BKK", "date": "2026-11-16",
            "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
            "channels": ["qunar"]}
    old = webui._watch_entry(dict(base))
    # 历史关注保留原日期时，仍可改渠道/目标做复盘
    webui._watch_entry(dict(old), old=old)
    with pytest.raises(ValueError, match="不能改到过去日期"):
        webui._watch_entry(dict(old, date="2020-01-01"), old=old)


def test_one_leg_batch_still_renders_as_batch(fake_plat):
    j = webui._probe_search(None, None, None, [fake_plat], legs=[
        {"from": "上海", "to": "北京", "date": "2026-10-25"}])
    assert j.get("batch") is True and len(j["legs"]) == 1
    assert j["legs"][0]["rows"] == 2 and len(j["rows"]) == 2


class _ThinCrawler(_FakeCrawler):
    def fetch(self, fc, tc, dates):
        d = dates[0]
        it = {"price": 90, "code": "XX999", "name": "薄行航",
              "depTime": "06:00", "depDate": d}
        return [SimpleNamespace(price=90, airline="薄行航", flight_no="XX999",
                                depart_time="06:00", arrive_time="",
                                extra=json.dumps([it], ensure_ascii=False))]


def test_batch_missing_arrival_time_stays_calendar(fake_plat):
    crawlers.REGISTRY["thin"] = _ThinCrawler
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(None, None, None, ["thin"], legs=[
            {"from": "上海", "to": "北京", "date": "2026-10-25"}])
        row = j["rows"][0]
        assert row["arrTime"] == ""
        assert row["isCal"] is True and row["qual"] is False
    finally:
        crawlers.REGISTRY.pop("thin", None)
        webui._PROBE_LAST = 0


class _OneLegOnlyCrawler(_FakeCrawler):
    def fetch(self, fc, tc, dates):
        if tc != "BJS":
            return []
        return super().fetch(fc, tc, dates)


def test_batch_merged_channel_ok_when_any_leg_has_rows(fake_plat):
    crawlers.REGISTRY["oneleg"] = _OneLegOnlyCrawler
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(None, None, None, ["oneleg"], legs=[
            {"from": "上海", "to": "北京", "date": "2026-10-25"},
            {"from": "上海", "to": "纽约", "date": "2026-11-16"}])
        assert j["channels"]["oneleg"]["n"] == 2
        assert j["channels"]["oneleg"]["status"] == "ok"
        assert j["legs"][0]["channels"]["oneleg"]["status"] == "ok"
        assert j["legs"][1]["channels"]["oneleg"]["status"] == "empty"
    finally:
        crawlers.REGISTRY.pop("oneleg", None)
        webui._PROBE_LAST = 0


def test_batch_ensure_does_not_pin_single_pair_or_date():
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "if(SRX.probe&&SRX.probe.batch){" in src
    assert "组合结果默认跨腿/日期全量" in src


def test_probe_channels_follow_fixed_priority():
    names = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")
    old = {p: crawlers.REGISTRY.get(p) for p in names}
    for p in names:
        crawlers.REGISTRY[p] = _FakeCrawler
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search("上海", "北京", "2026-10-25",
                                list(reversed(names)))
        assert list(j["channels"]) == list(webui.PLATFORM_PRIORITY)
    finally:
        for p in names:
            if old[p] is None:
                crawlers.REGISTRY.pop(p, None)
            else:
                crawlers.REGISTRY[p] = old[p]
        webui._PROBE_LAST = 0


def test_probe_ui_priority_order_source():
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "const SRX_PLAT_ORDER=['ctrip','qunar','fliggy','tongcheng','tuniu'];" in src
    assert 'aria-label="探针渠道（优先级：携程、去哪儿、飞猪、同程、途牛）"' in src
    assert "SRX_PLAT_ORDER.filter(p=>(lg.channels||{})[p])" in src


def _mk_task(plans, want):
    import threading as _th
    legs = []
    for i, p in enumerate(plans):
        legs.append({"leg": i, "from": p["from"], "from_name": p["from_name"],
                     "to": p["to"], "to_name": p["to_name"], "date": p["date"],
                     "status": "queued", "rows": 0, "detail": 0, "cal": 0,
                     "channels": {q: {"status": "queued", "phase": "排队",
                                      "n": 0, "detail": 0, "cal": 0,
                                      "ms": 0, "err": ""} for q in want}})
    return {"id": "t1", "status": "running", "created": 0, "updated": 0,
            "started": 0, "finished": None, "plans": plans, "want": want,
            "total": len(plans) * len(want), "legs": legs, "rows": [],
            "rowkeys": set(), "events": [], "cancel": _th.Event(),
            "truncated": False, "err": ""}


def test_probe_task_records_real_channel_phases(fake_plat):
    plan = webui._probe_leg_plan("上海", "北京", "2026-10-25")
    task = _mk_task([plan], [fake_plat])
    webui._PROBE_LAST = 0
    j = webui._probe_search(None, None, None, [fake_plat],
                            legs=[{"from": "上海", "to": "北京",
                                   "date": "2026-10-25"}], task=task)
    assert j["ok"] and task["legs"][0]["channels"][fake_plat]["status"] == "ok"
    assert len(task["rows"]) == 2 and task["legs"][0]["rows"] == 2
    phases = {e["phase"] for e in task["events"]}
    assert {"排队", "请求渠道", "解析明细", "解析完成", "渠道结束"} <= phases
    v = webui._probe_task_view("t1")
    # _probe_task_view reads registry; register for this assertion
    if v is None:
        webui._PROBE_TASKS["t1"] = task
        v = webui._probe_task_view("t1")
        webui._PROBE_TASKS.pop("t1", None)
    assert v["done"] == 1 and v["detail"] == 2 and v["raw"] >= 0


def test_probe_task_cancel_before_start_is_cancelled(fake_plat):
    plan = webui._probe_leg_plan("上海", "北京", "2026-10-25")
    task = _mk_task([plan], [fake_plat])
    task["cancel"].set()
    webui._PROBE_TASKS["t1"] = task
    webui._PROBE_LAST = 0
    try:
        webui._probe_start_task("t1", None, None, None,
                                [{"from": "上海", "to": "北京",
                                  "date": "2026-10-25"}], [fake_plat])
        assert task["status"] == "cancelled" and task["rows"] == []
    finally:
        webui._PROBE_TASKS.pop("t1", None)
        webui._PROBE_LAST = 0


def test_neutral_state_and_task_ui_pins():
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "上次条件未自动应用" in src and "data-restore=\"1\"" in src
    assert "function srxTaskStart(payload,opts)" in src
    assert "function srxTaskCancel()" in src and "function srxTaskRetry()" in src
    assert "SRX_TASK_ROWS_SEEN" in src and "/api/probe/start" in src
    assert "本次渠道产物" in src and "仅日历" in src and "会话" in src
    assert "#searchview.srx-probe-on .srx-brief" in src
