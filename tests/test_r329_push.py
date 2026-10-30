# -*- coding: utf-8 -*-
"""r329 推送层四案（_scratch/worker_r329_push.md）：P1-1 承运档 /
P2-1 日历行空时刻裸段 / P2-3 舱码国际值域门 / P3-1 风暴标题保尾 /
P2-4 机场码辨识槽。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r329_push.py
"""
import json
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from core.alerter import Alerter, _storm_title  # noqa: E402
from core.models import Route, FlightPrice  # noqa: E402
import report as _rep  # noqa: E402

_LOG = logging.getLogger("t_r329_push")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fp(price, name, dpt, art, trans="", cross="", plat="qunar",
        dep="2026-11-16", **over):
    d0 = date.fromisoformat(dep)
    days = 1 if cross == "+1天" else (2 if cross == "+2天" else 0)
    f = {"price": price, "name": name, "code": name, "depTime": dpt,
         "arrTime": art, "depDate": dep,
         "arrDate": str(d0 + timedelta(days=days)),
         "transCity": trans, "crossDayDesc": cross,
         "totalDuration": "6时", "_platform": plat}
    f.update(over)
    return f


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


class _FakeN:
    def __init__(self):
        self.calls = []

    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        self.calls.append((t, d, at_mobiles))
        return True


# ---- P1-1：shareAirline 单独在场「承运·」档（webui 同语言三档）----

def test_p11_share_txt_three_tiers():
    _share = _rep._share_txt
    # 组合档：共享·名+号（存量行为不变）
    assert _share({"shareCarrier": "CZ8404", "shareAirline": "南航"}) \
        == "共享·南航CZ8404"
    # 号-only 档（存量行为不变）
    assert _share({"shareCarrier": "CZ8404"}) == "共享·CZ8404"
    # 名-only 档（r329 P1-1：非共享中转行二段承运，webui「承运·」同词面）
    assert _share({"shareAirline": "东方航空|四川航空"}) \
        == "承运·东方航空|四川航空"
    # 双空零词
    assert _share({}) == ""
    # 模块源钉：_parts 的 share 键消费单源函数（调用点内联是档序
    # 回退温床，LESSONS 十九§9）
    src = open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()
    assert '("share", _share_txt(f))' in src


# ---- P2-3：舱码括注门扩国际段级值域（webui 任意非空即显对齐）----

def test_p23_cabin_bracket_intl_gate():
    _cb = _rep._cabin_bracket
    # 存量行为：单字母/字母+数字括注
    assert _cb("经济舱", "Y") == "经济舱(Y)"
    assert _cb("经济舱", "B0") == "经济舱(B0)"
    # r329 国际段级连串过门（webui/PNG 同语言）
    assert _cb("经济舱", "W-W") == "经济舱(W-W)"
    assert _cb("经济舱", "Q-Y-B") == "经济舱(Q-Y-B)"
    # 非经济舱不括注（存量行为）
    assert _cb("公务舱", "Y") == "公务舱"
    # 空码不括注
    assert _cb("经济舱", "") == "经济舱"


# ---- P2-1：日历价行空时刻跳过 seg 段（生产 13 条推送裸「> →」根治）----

def test_calendar_row_never_enters_push_hits():
    a = Alerter(_LOG, notifier=_FakeN(), storage=None, digest=True,
                storm_repeat=1, user="演练")
    r = Route(from_code="PVG", to_code="NRT", from_name="上海",
              to_name="东京", dates=["2026-11-16"],
              alert_direct=3000, alert_transfer=0)
    # 日历最低价行：name=「日历最低价」、时刻双空。它不是可出手机票，
    # 不得进入推送分类池/命中，也不得产出「日历最低价 →」空段。
    p = _ps([_fp(2580, "日历最低价", "", "", plat="ctrip")],
            "PVG", "NRT", "2026-11-16")
    assert a._build_sections(r, p) == []
    # 同一轮里的正常航班仍必须命中（守卫不误杀真实低价）
    r2 = Route(from_code="NRT", to_code="PVG", from_name="东京",
               to_name="上海", dates=["2026-11-16"],
               alert_direct=3000, alert_transfer=0)
    p2 = _ps([_fp(2620, "东航MU524", "15:10", "18:25", plat="qunar")],
             "NRT", "PVG", "2026-11-16")
    built = [(r, a._build_sections(r, p)), (r2, a._build_sections(r2, p2))]
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    desp = pv["desp"]
    # 裸「> →」零信息段绝迹（含「> →(+1天)」变体）
    assert "> →" not in desp, desp
    assert "日历最低价 →" not in desp, desp
    # 正常航班命中且 seg 完整；日历航线不冒充命中
    assert "🔥" in desp and "东→上" in desp, desp[-400:]
    assert "15:10→18:25" in desp


# ---- P2-4：机场码辨识槽（国际 city 级查询 PVG/SHA 分辨）----

def test_p24_airport_token_slot():
    src = open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()
    # parts 机场槽本体（Soldier m-3 半死钉补全：丢档链 3 个 "airport"
    # 字符串满足不了此断言，主修复点被摘即红）
    assert '("airport", _apt)' in src
    # 丢档链末三档才丢（辨识信息在 cabin/lcc 档级保留）：_chain 区域
    # 内 "airport" 计数==3（4/5/6 档 drop 元组各一）
    chain_zone = src.split("_chain = (")[1].split("for _drop")[0]
    assert chain_zone.count('"airport"') == 3, chain_zone


# ---- P3-1：风暴标题保尾「等N条」计数 ----

def test_p31_storm_title_keeps_count_tail():
    # 主推标题（≤51 字符主体+「等21条」尾）：风暴前缀拼入后
    # 「等N条」规模感知不再被切点吃掉
    body = "上海→洛阳 11/16 · 北京→上海 11/17 · 成都→拉萨 11/18" \
           " · 西安→昆明 11/19 · 广州→厦门 11/20"
    full = body + "等21条"
    t = _storm_title(2, 3, full)
    assert t.startswith("📞 达标提醒 2/3 ")
    assert len(t) <= 60, (len(t), t)
    assert t.endswith("等21条"), t
    # 短标题（不触发截断）原样保留
    t2 = _storm_title(1, 3, "上海→洛阳 11/16")
    assert t2 == "📞 达标提醒 1/3 上海→洛阳 11/16"
    # 无计数尾的长标题：旧切法行为不变
    t3 = _storm_title(2, 3, body)
    assert len(t3) <= 60 and t3.startswith("📞 达标提醒 2/3 ")
