# -*- coding: utf-8 -*-
"""r805ca：达标推送里两个 App 渠道必须显示中文名，不是裸 id。

用户要求「把两款 App 的能力接入到整个项目中的每个角落」。推送是核心用户面，
也是唯一按渠道名拼正文的地方——`PLATFORM_CN_EXTRA` 在 r644 补过名字，但没有
门禁证明「App 行的推送文案里真的出现了中文名」。这里直调纯构建器，不发送。
"""
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter                      # noqa: E402
from core.models import FlightPrice, Route            # noqa: E402


class _FakeN:
    def __init__(self):
        self.sent = []

    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        self.sent.append((t, d))
        return True


def _row(plat):
    f = {"price": 2500, "name": "国航CA847", "code": "国航CA847",
         "depTime": "02:25", "arrTime": "07:10", "depDate": "2026-11-16",
         "arrDate": "2026-11-16", "transCity": "", "crossDayDesc": "",
         "totalDuration": "5时", "_platform": plat}
    return FlightPrice(platform=plat, from_city="SHA", to_city="BKK",
                       depart_date="2026-11-16", price=2500,
                       extra=json.dumps([f], ensure_ascii=False))


def _digest_text(plat):
    a = Alerter(logging.getLogger("push-" + plat), notifier=_FakeN(),
                storage=None, digest=True, at_mobile="", storm_repeat=1,
                user="推送演练")
    r = Route(from_code="SHA", to_code="BKK", from_name="上海",
              to_name="曼谷", dates=["2026-11-16"],
              alert_direct=3000, alert_transfer=0)
    built = [(r, a._build_sections(r, [_row(plat)]))]
    pv = a._digest_payload(built, fresh=True, with_tables=False,
                           with_charts=False)
    return pv["title"] + "\n" + pv["desp"]


def test_app_channel_rows_render_chinese_names_in_digest():
    for plat, cn in (("app_qunar", "去哪儿 App"), ("app_zhixing", "智行 App")):
        body = _digest_text(plat)
        assert cn in body, "%s 的推送文案里没有中文名：%s" % (plat, body[:300])
        assert plat not in body, (
            "%s 的推送文案里露出了裸 id：%s" % (plat, body[:300]))
