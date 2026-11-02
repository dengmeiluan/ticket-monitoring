# -*- coding: utf-8 -*-
"""航线卡高频重排（r339 论坛用户 bigwolf 反馈）三案的模型侧钉：
日期快速选/只要直飞/高级约束折叠。后端语义只有一件——direct_only
旗标在任何消费路径下都强制中转阈 0（alerter 的 alert_transfer>0 门
即全链关断点），防「UI 收起了中转输入、手改 config 却仍报中转」的
双源劈叉。"""
import main


def test_direct_only_zeroes_transfer_alert():
    routes = main.build_routes([
        {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1500,
         "alert_transfer": 1300, "direct_only": True}])
    assert routes[0].alert_transfer == 0
    assert routes[0].alert_direct == 1500


def test_no_flag_keeps_transfer_alert():
    routes = main.build_routes([
        {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1500,
         "alert_transfer": 1300}])
    assert routes[0].alert_transfer == 1300


# ---- 航线级筛选约束（明细已解析字段升格：对齐 OTA 高频筛选面） ----

def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False, "baggage": "免费托运20kg", "planeSize": "大型机"}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "PEK", "to_name": "北京",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


def test_filter_airlines_by_code_and_name():
    from core.alerter import Alerter
    rt = _route(airlines="MU, 春秋")
    assert Alerter._route_filters([_flt()], rt)          # 码命中
    assert Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt)  # 名称片段命中
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)  # 不在白名单
    assert not Alerter._route_filters([_flt(airlineCode="", airline="")], rt)
    # 白名单失败语义：未标注航司的行按不满足（十七§5 保守筛选律）


def test_filter_no_lcc():
    from core.alerter import Alerter
    rt = _route(no_lcc=True)
    assert not Alerter._route_filters([_flt(lcc=True)], rt)
    assert Alerter._route_filters([_flt(lcc=False)], rt)
    assert Alerter._route_filters([_flt()], rt)   # 缺席≠廉航，不剔


def test_filter_min_baggage():
    from core.alerter import Alerter
    rt = _route(min_baggage=15)
    assert Alerter._route_filters([_flt()], rt)              # 20kg ≥ 15
    assert not Alerter._route_filters(
        [_flt(baggage="免费托运10kg")], rt)                    # 不足
    assert not Alerter._route_filters([_flt(baggage="")], rt)  # 未标注按不满足


def test_filter_widebody():
    from core.alerter import Alerter
    rt = _route(widebody_only=True)
    assert Alerter._route_filters([_flt()], rt)               # 大型机
    assert not Alerter._route_filters(
        [_flt(planeSize="中型机")], rt)
    assert not Alerter._route_filters(
        [_flt(planeSize="小型机")], rt)
    assert Alerter._route_filters([_flt(planeSize="")], rt)   # 缺席不剔（fail-open 防整渠道误杀）


def test_build_routes_filter_fields_passthrough():
    rt = _route(airlines="MU,MF", no_lcc=True, min_baggage=20,
                widebody_only=True)
    assert rt.airlines == "MU,MF" and rt.no_lcc is True
    assert rt.min_baggage == 20 and rt.widebody_only is True
    rt0 = _route()
    assert rt0.airlines == "" and rt0.no_lcc is False
    assert rt0.min_baggage == 0 and rt0.widebody_only is False
