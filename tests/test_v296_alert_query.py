# -*- coding: utf-8 -*-
"""v1.5.296: stale radar start clamps, no-notifier alerts stay silent."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers  # noqa: E402
import main  # noqa: E402
import webui  # noqa: E402


def test_radar_auto_query_clamps_past_start_and_skips_ended():
    r = {"from_name": "上海", "to_name": "曼谷", "start": "2026-10-24",
         "end": "2026-10-31", "nationwide": False, "channels": ["ctrip"]}
    q, why = webui._radar_auto_query(r, today="2026-10-25")
    assert why == "clamped" and q["start"] == "2026-10-25"
    assert q["end"] == "2026-10-31" and q["from"] == "上海"
    q, why = webui._radar_auto_query(
        {**r, "start": "2026-10-20", "end": "2026-10-24"},
        today="2026-10-25")
    assert q is None and why == "ended"
    q, why = webui._radar_auto_query({"from_name": "上海"},
                                     today="2026-10-25")
    assert q is None and why == "incomplete"


class _FakeCrawler:
    login_suspect = True


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def info(self, *a, **k):
        pass


def test_notifier_none_is_not_a_send_error(monkeypatch):
    monkeypatch.setattr(crawlers, "REGISTRY", {"qunar": _FakeCrawler})
    monkeypatch.setattr(main, "_sent_save", lambda: None)
    main._LOGIN_ALERT_STREAK.clear()
    main._SENT_LAST.clear()
    main._SENT_CNT.clear()
    log = _Logger()

    class _Al:
        notifier = None

    u = {"name": "u", "platforms": ["qunar"]}
    main._channel_login_alert_sentinel([(u, _Al())], log)
    main._channel_login_alert_sentinel([(u, _Al())], log)
    assert not any("NoneType" in w for w in log.warnings), log.warnings
