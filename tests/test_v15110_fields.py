# -*- coding: utf-8 -*-
"""本轮数据层（渠道调研立案 T-N1）：

tongcheng：connection 中转报价的免费托运证据——fps[].lps[]（有票
最低价政策）.fs[ft=7].fcs 含码 "11"=「免费托运行李」（码义源=同轮
book1 data.cfs 动态码表，conn 响应自身无 cfs 键），27/47 中转行在
场且现行解析零采集（回放 27/27 行 transferBaggage=""，纯增益）。
中转行占 tc 明细约 30%，裸价 vs 含托运价的比价失真与 book1 直飞侧
行级标记动机同害。落既有 baggage「免费托运」词面零新键，消费端
（webui/CSV/report）既有通道零改动。

守卫四条（与 book1 同门）：①码义映射缺席（bag_fc=""）不落键；
②随最低价有票政策配对（防政策错配虚标）；③fc 漂移即静默不并；
④不作为 transferBaggage=direct 推断源（直挂三态语义留给行级
证据守卫）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15110_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t15110")


# ---- T-N1 tongcheng：conn 中转免费托运（bag_fc 跨报文线程） ----

def _tc_bag_fp(policies=None):
    """最低价政策带 fs[ft=7].fcs=["11"] 的 conn 中转样本
    （fp 形态与 test_v15106 _tc_fp 同构，lps 换双政策）。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30"}]
    if policies is None:
        policies = [{"atp": 1500, "brs": [{"al": 5}],
                     "pts": [{"td": "6.8折经济舱"}],
                     "fs": [{"ft": 7, "fcs": ["11"]}]}]
    return {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
            "lps": policies}


def _tc_bag_rows(fp, bag_fc="11"):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}), bag_fc)
    assert rows
    return rows[0]


def test_tc_conn_baggage_with_mapping():
    """最低价政策 fs[ft=7].fcs 含码 11 + bag_fc="11"：
    baggage=「免费托运」——中转裸价的行李语义随最低价政策落键。"""
    r = _tc_bag_rows(_tc_bag_fp())
    assert r["baggage"] == "免费托运"


def test_tc_conn_baggage_no_mapping_no_key():
    """码表缺席（bag_fc=""，book1 不在场/无 cfs 键）：行级码命中也
    不落键——码义映射缺席不落键（宁缺勿错，防码漂移后把无行李
    政策误标有行李）。"""
    r = _tc_bag_rows(_tc_bag_fp(), bag_fc="")
    assert "baggage" not in r


def test_tc_conn_baggage_follows_lowest_policy():
    """行李随最低价有票政策配对：最低价政策无码、次低价政策有码
    → 不落（监控按最低价告警，推出的裸价不得虚标行李）。"""
    ps = [{"atp": 1500, "brs": [{"al": 5}], "pts": [{"td": "经济舱"}]},
          {"atp": 1600, "brs": [{"al": 3}], "pts": [{"td": "6.8折经济舱"}],
           "fs": [{"ft": 7, "fcs": ["11"]}]}]
    r = _tc_bag_rows(_tc_bag_fp(ps))
    assert "baggage" not in r


def test_tc_conn_baggage_fc_drift_silent():
    """fc 漂移（码表给 12 而政策挂 11）：静默不并——码义与行级码
    不一致说明渠道改了码表语义，硬对会误标。"""
    r = _tc_bag_rows(_tc_bag_fp(), bag_fc="12")
    assert "baggage" not in r


def test_tc_conn_baggage_not_transfer_direct():
    """baggage「免费托运」≠ 直挂：doc 双图例并存（direct_only=False）
    且无 stss 行级证据时 transferBaggage 不落键——免费托运不参与
    直挂三态推断（语义留给行级证据守卫；空串键已按无值不落键
    族律退役，消费端 ==direct 判定缺键等价）。"""
    r = _tc_bag_rows(_tc_bag_fp())
    assert "transferBaggage" not in r


def test_tc_bag_fc_helper_single_source():
    """book1 cfs 码表提取抽单源 helper：conn 跨报文线程与 book1
    内联解析共用同一取值函数（防两份同逻辑漂移）。"""
    data = {"cfs": [{"ft": 7,
                     "fis": [{"fd": "免费托运行李", "fc": " 11 "}]}]}
    assert TongchengCrawler._bag_fc(data) == "11"
    assert TongchengCrawler._bag_fc({}) == ""
    assert TongchengCrawler._bag_fc({"cfs": [{"ft": 8, "fis": [
        {"fd": "免费托运行李", "fc": "11"}]}]}) == ""
    assert TongchengCrawler._bag_fc({"cfs": [{"ft": 7, "fis": [
        {"fd": "免费退改", "fc": "11"}]}]}) == ""


def test_tc_bag_fc_from_captured():
    """fetch 跨报文线程的 captured 提取纯函数（可测面）：book1 在场
    取码 / 缺席空串 / 坏 JSON 空串——映射缺席 conn 行级码命中也不落。"""
    _bag = TongchengCrawler._bag_fc_from_captured
    ok = [{"url": "https://m.ly.com/flightbffv2/book1/flights",
           "text": json.dumps({"data": {"cfs": [{"ft": 7, "fis": [
               {"fd": "免费托运行李", "fc": "11"}]}]}})}]
    assert _bag(ok) == "11"
    assert _bag([{"url": "https://x/connection/flights",
                  "text": "{}"}]) == ""
    assert _bag([{"url": "https://m.ly.com/flightbffv2/book1/flights",
                  "text": "not-json"}]) == ""
    assert _bag([]) == ""
