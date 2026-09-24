# -*- coding: utf-8 -*-
"""v1.5.84 qunar PC 中转全程时长/停留重建（解析准确性）。

生产冻结 dump 实锤（第 14 轮渠道调研 B 上报 + 主修 dump 复核）：PC
wbdflightlist 顶层 transTime 语义=**中转停留时长**（45/45 行=b2.dep−
b1.arr 精确相等，「1天55分钟」即跨天停留；直飞行恒 int 0）——
「中转全程时长在 transTime」系 H5 时代口径误解，落库两面皆毒：
① totalDuration 落停留词面（「9小时」当全程）；
② 一级停留公式 t_m−f1−f2>0 在「停留>两段飞行和」时误触发
（真停 9h 记成 3h05，dump 21 中转行 8 行命中），衔接筛选/
layoverT 展示全链受染——normalize 守卫只拦「衔接≥全程」类，
此类低估值直通 layoverM。
夹具取生产冻结 dump 真实行（解析测试样本必须取生产 dump 实证结构）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v184_fields.py -q
"""

import json

from crawlers.qunar import QunarCrawler

# 生产冻结 dump 真实行（乌鲁木齐→上海 10-06 代）：transTime='9小时'
# 实为停留（b1.arr 12:20 → b2.dep 21:20），两段飞行 3h50+2h05
_PC_TRANS = json.loads(r'''{"binfo1":{"airCode":"GS7529","arrAirport":"武当山机场","arrAirportCode":"WDS","arrDate":"2026-10-06","arrTerminal":"","arrTime":"12:20","cabin":"M","codeShare":false,"crossDay":0,"crossDayDesc":"","date":"2026-10-06","depAirport":"乌鲁木齐天山","depAirportCode":"URC","depDate":"2026-10-06","depTerminal":"","depTime":"08:30","flightTime":"3小时50分钟","mealDesc":"无餐食","name":"新海航｜天津航空","planeFullType":"空客320(中)","planeType":"32C","shortCarrier":"GS","shortName":"新海航｜天津航空"},"binfo2":{"airCode":"FM9356","arrAirport":"浦东机场","arrAirportCode":"PVG","arrDate":"2026-10-06","arrTerminal":"T1","arrTime":"23:25","cabin":"L","codeShare":false,"crossDay":0,"crossDayDesc":"","date":"2026-10-06","depAirport":"武当山机场","depAirportCode":"WDS","depDate":"2026-10-06","depTerminal":"","depTime":"21:20","flightTime":"2小时5分钟","name":"上海航空","planeFullType":"波音737(中)","planeType":"73A","shortCarrier":"FM","shortName":"上航"},"minPrice":2550,"minbfPrice":0,"code":"GS7529/FM9356","flightType":"listMore","crossDayDesc":"","transCity":"十堰","transTime":"9小时","discountStr":"6.3折","priceLabel":[]}''')

# 跨天停留形态：transTime='1天55分钟'（b1.arr 21:55 → 次日 b2.dep
# 22:50，真停 24h55m）；span(b1.date→b2.arrDate)=2 天触发回绕存疑
# 守卫→停留不取、全程留空由 normalize 按起止时刻重算兜底
_PC_TRANS_WRAP = json.loads(r'''{"binfo1":{"airCode":"Y87570","arrAirport":"新郑机场","arrAirportCode":"CGO","arrDate":"2026-10-06","arrTerminal":"T2","arrTime":"21:55","cabin":"L","codeShare":false,"crossDay":0,"crossDayDesc":"","date":"2026-10-06","depAirport":"乌鲁木齐天山","depAirportCode":"URC","depDate":"2026-10-06","depTerminal":"","depTime":"17:55","flightTime":"4小时0分钟","mealDesc":"无餐食","name":"新海航｜金鹏航空","planeFullType":"737-800","planeType":"738","shortCarrier":"Y8","shortName":"新海航｜金鹏航空"},"binfo2":{"airCode":"Y87520","arrAirport":"浦东机场","arrAirportCode":"PVG","arrDate":"2026-10-08","arrTerminal":"T2","arrTime":"00:40","cabin":"L","codeShare":false,"crossDay":1,"crossDayDesc":"+1天","date":"2026-10-07","depAirport":"新郑机场","depAirportCode":"CGO","depDate":"2026-10-07","depTerminal":"T2","depTime":"22:50","flightTime":"1小时50分钟","name":"新海航｜金鹏航空","planeFullType":"737-800","planeType":"738","shortCarrier":"Y8","shortName":"新海航｜金鹏航空"},"minPrice":2700,"minbfPrice":0,"code":"Y87570/Y87520","flightType":"listMore","crossDayDesc":"+2天","transCity":"郑州","transTime":"1天55分钟","discountStr":"6.3折","priceLabel":[{"id":667,"name":"郑州机场中转权益","note":[]}],"transitServiceLabelName":"中转优享","transitServiceLabel":"中转优享：本服务包含免费休息区服务"}''')

# 直飞行（真实形态）：transTime=int 0，时长真值在 binfo.flightTime
_PC_DIRECT = {
    "binfo1": {"airCode": "9C6496", "arrTime": "21:30", "arrDate": "2026-10-06",
               "date": "2026-10-06", "depTime": "16:40", "flightTime": "4h35m",
               "name": "春秋航空", "shortName": "春秋航空"},
    "code": "9C6496", "crossDayDesc": "", "minPrice": 620,
    "transTime": 0,
}


def _one(raw):
    env = {"ret": True, "data": {"flights": [raw]}}
    fl = QunarCrawler._parse_pc_flights(json.dumps(env), "2026-10-06")
    assert fl, "夹具行被解析器整行丢弃（夹具结构与真实报文不符）"
    return fl[0]


class TestQunarPcTransferDuration:
    """中转行 totalDuration/layover 双字段源头重建。"""

    def test_transfer_totalduration_is_journey(self):
        f = _one(_PC_TRANS)
        # 全程=3h50 + 停9h + 2h05 = 14时55分（停留词面「9小时」不再冒充全程）
        assert f["totalDuration"] == "14时55分", \
            f"中转 totalDuration 仍落停留词面: {f['totalDuration']!r}"

    def test_transfer_layover_is_true_gap(self):
        f = _one(_PC_TRANS)
        # 停留权威=两段起降差 9h=540（一级公式曾误算 540−230−125=185）
        assert f["layover"] == 540, \
            f"中转 layover 偏离起降差真值: {f['layover']!r}"

    def test_transfer_wrap_guard_degrades_to_empty(self):
        f = _one(_PC_TRANS_WRAP)
        # span≥2 天回绕存疑→停留不取→全程留空（normalize 按起止时刻
        # 重算兜底，2*1440+00:40−17:55=1845=4h+24h55+1h50 精确自洽）
        assert f["totalDuration"] == ""
        assert f["layover"] == ""

    def test_transfer_normalize_integration(self):
        from core.flightnorm import normalize
        f = normalize(_one(_PC_TRANS), "2026-10-06")
        assert f["totalDuration"] == "14时55分"
        assert f["durM"] == 895
        assert f["layoverM"] == 540
        assert f["layoverT"] == "9:00"

    def test_transfer_missing_segment_degrades(self):
        import copy
        row = copy.deepcopy(json.loads(json.dumps(_PC_TRANS)))
        row["binfo2"]["flightTime"] = ""
        f = _one(row)
        # 两段飞行缺一→重建不可为→留空（normalize 重算兜底），
        # 停留仍由起降差权威给出
        assert f["totalDuration"] == ""
        assert f["layover"] == 540

    def test_direct_duration_unchanged(self):
        f = _one(_PC_DIRECT)
        assert f["totalDuration"] == "4时35分"
