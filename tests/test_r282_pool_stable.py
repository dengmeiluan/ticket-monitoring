# -*- coding: utf-8 -*-
"""r282 P3-1 池序确定性：同价并列跨渠道班次轮间身份漂移。

机制（r282 推送审校实锤）：main sweep 的 as_completed 完成序
all_prices.extend 进池 → 池序随渠道完成序逐轮浮动 → 下游
min(key=price) 稳定取首 → 同价并列班次（价格/差额/合规全同）的
「首选班次」身份轮间翻转（实录：￥1760 同价双班 9C8807/9C8815 的
行2/行3 位置轮间对调，总表图并列在场兜底但行身份漂移）。

修法：池构造后按纯身份键（depart_time/arrive_time/flight_no/
airline/platform）稳定排序——与价格无关（价格排序仍由下游各消费点
自己的口径决定，_qual_price vs price 不在采集层提前分叉），只给
同价 tie-break 一个确定性底序；并发语义不动。
池元素是 FlightPrice dataclass（safe_fetch 返回类型）——喂真契约。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r282_pool_stable.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import FlightPrice
from main import _stable_pool


def _f(flight_no, dpt, art, price, plat, airline="春秋航空"):
    return FlightPrice(platform=plat, from_city="SHA", to_city="HAK",
                       depart_date="2027-01-30", price=price,
                       airline=airline, flight_no=flight_no,
                       depart_time=dpt, arrive_time=art)


# 实录样本：￥1760 同价双班（中转，直挂未标注），价格/合规全同
_TIE = [_f("9C8815", "07:05", "22:00", 1760, "qunar"),
        _f("9C8807", "14:05", "22:00", 1760, "fliggy")]


def test_tie_pair_identity_stable_across_completion_orders():
    # 两渠道完成序互换进池（今轮 fliggy 先、明轮 qunar 先），
    # 排序后身份序恒同——「取首」不再随轮次翻转
    pad = _f("XX111", "01:00", "02:00", 9999, "ctrip", airline="垫行航司")
    a = _stable_pool(list(reversed(_TIE)) + [pad])
    b = _stable_pool(_TIE + [pad])
    assert [f.flight_no for f in a] == [f.flight_no for f in b]
    # 同价对的相对序由身份键定：depart_time 早者恒前（07:05 < 14:05）
    nos = [f.flight_no for f in a]
    assert nos.index("9C8815") < nos.index("9C8807")


def test_sort_key_is_identity_not_price():
    # 价格不进键：价高的早班机仍排前（价格排序归下游口径，
    # 池序只承载同价 tie-break 的确定性）
    pool = [_f("AA001", "20:00", "23:00", 900, "qunar"),
            _f("BB002", "06:00", "09:00", 1500, "ctrip")]
    out = _stable_pool(pool)
    assert out[0].flight_no == "BB002"


def test_default_empty_fields_do_not_raise():
    # dataclass 缺省字段（flight_no/airline 为 "" 的早退残行形态）
    rough = [FlightPrice(platform="qunar", from_city="SHA", to_city="HAK",
                         depart_date="2027-01-30", price=500),
             _f("CC003", "08:00", "11:00", 700, "tuniu")]
    out = _stable_pool(rough)
    # 确定性即可（空身份键按字典序排前；残行由下游守卫过滤）
    assert [f.flight_no for f in out] == ["", "CC003"]


def test_original_list_not_mutated():
    src = list(_TIE)
    _stable_pool(src)
    assert src[0].flight_no == "9C8815"   # 原池序不污染（extend 语义不变）
