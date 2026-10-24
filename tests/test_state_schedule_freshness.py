"""调度变化不能被未变化的票价缓存冻结成永久「扫描中」。"""
import gzip
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.blocking import BlockingScheduler

from core import scheduler
from core.storage import PriceStorage
import webui


@pytest.mark.parametrize("compressed", [False, True])
def test_state_refreshes_schedule_without_rebuilding_prices(tmp_path, monkeypatch,
                                                           compressed):
    db = tmp_path / "prices.db"
    PriceStorage(str(db))
    monkeypatch.setattr(webui._State, "cfg", {"output": {"db_path": str(db)}})
    monkeypatch.setattr(webui._State, "users", [])
    monkeypatch.setattr(webui._State, "version", "schedule-test")
    monkeypatch.setitem(webui.DEMO, "on", False)
    monkeypatch.setattr(webui, "_STATE_CACHE", dict.fromkeys(webui._STATE_CACHE))
    monkeypatch.setattr(webui, "_STATE_BUILDING", {"on": False})
    monkeypatch.setattr(webui, "_STATE_DISK_ONCE", {"on": True})
    builds = []
    original_build = webui._build_state

    def build(sig):
        builds.append(sig)
        original_build(sig)

    monkeypatch.setattr(webui, "_build_state", build)
    sched = BlockingScheduler(timezone="Asia/Shanghai")
    monkeypatch.setattr(scheduler, "SCHED", sched)
    old = datetime(2026, 10, 23, 14, 27, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    new = old.replace(hour=14, minute=59, second=45)
    sched.add_job(lambda: None, "interval", minutes=30,
                  id="price_monitor", next_run_time=old)
    server = webui._Srv(("127.0.0.1", 0), webui._Handler)
    monkeypatch.setattr(webui._State, "srv", server, raising=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(etag=""):
        headers = {"If-None-Match": etag}
        if compressed:
            headers["Accept-Encoding"] = "gzip"
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/state" % server.server_port, headers=headers)
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return response.code, response.headers.get("ETag"), (
                json.loads(body) if body else None)

    try:
        status, first_etag, first = get()
        assert status == 200
        assert first["next_run"] == "2026-10-23 14:27:12"
        db_mtime = db.stat().st_mtime_ns

        sched.modify_job("price_monitor", next_run_time=new)
        status, second_etag, second = get(first_etag)
        assert status == 200, "调度已变化，不能用旧 ETag 返回 304"
        assert second["next_run"] == "2026-10-23 14:59:45"
        assert second_etag != first_etag
        assert get(second_etag)[0] == 304

        sched.remove_job("price_monitor")
        status, _, stopped = get(second_etag)
        assert status == 200
        assert stopped["next_run"] == ""
        assert db.stat().st_mtime_ns == db_mtime
        assert len(builds) == 1, "调度变化不应重算票价历史"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
