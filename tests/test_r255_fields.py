# -*- coding: utf-8 -*-
"""r255 数据层：同程「超惠飞」产品标签收编 labels 白名单。

证据链（r255 渠道调研 B，三代独立复现）：pts[].td="超惠飞" 本代
10-15 dump 18 处在场，恰挂 9C 春秋班最低价政策；同政策
fs[ft=7].fcs 缺免费托运码「11」互证=「裸价无行李」产品形态明示；
四既有出口（cabin/discount/clct 白名单/baggage）零覆盖=真读者
增量；qunar H5 priceBottomLabels 白名单已收同族词面
「春秋绿翼会员专享丨超惠飞」，tc 侧收编补齐跨渠道对称。
白名单精确匹配、值域扩展自然免疫（非白名单词面零落键）。
isf（r254「恒值化退役」定谳被推翻——值形是字符串 "True"/"False"，
truthy 门统计事故）恢复观察哨：不采，代码零改动，台账随 HANDOFF。
"""

import json

from crawlers.tongcheng import TongchengCrawler


def _tc_direct(**kw):
    fl = {"fn": "9C6117", "asn": "春秋航空",
          "dt": "2026-10-15 19:00", "at": "2026-10-15 23:40",
          "td": "4h40m", "afn": "空客A320(中)",
          "lps": [{"atp": 670, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "超惠飞"}],
                   "fs": [{"ft": 7, "fcs": ["3", "6", "7"]}]}]}
    fl.update(kw)
    return json.dumps({"data": {"fl": [fl]}}, ensure_ascii=False)


def test_tongcheng_chaohuifei_label_direct():
    """直飞 9C 班 pts[].td="超惠飞" → labels 含「超惠飞」（生产
    dump 实证形态：独占 tt=2 元素，舱位/折扣正则均不命中的旁路
    词面）；产品形态词排 clct 舒适词之前（行李语义优先呈现）。"""
    text = _tc_direct(
        lps=[{"atp": 670, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "超惠飞"}],
              "fs": [{"ft": 7, "fcs": ["3", "6", "7"]}],
              "clct": [{"tt": 1, "td": "大机型"}]}])
    out = TongchengCrawler._extract_flights(text)
    assert len(out) == 1
    f = out[0]
    assert f["price"] == 670, f
    assert "超惠飞" in f.get("labels", ""), f
    assert f["labels"].index("超惠飞") < f["labels"].index("大机型"), f


def test_tongcheng_chaohuifei_absent_on_normal_policy():
    """对照班（舱位词面政策）labels 不含「超惠飞」——白名单精确
    匹配，非超惠飞词面零污染。"""
    text = _tc_direct(
        lps=[{"atp": 1500, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "6.8折经济舱"}]}])
    out = TongchengCrawler._extract_flights(text)
    f = out[0]
    assert f["cabin"] == "经济舱", f
    assert "超惠飞" not in f.get("labels", ""), f


def test_tongcheng_chaohuifei_label_transfer():
    """中转路径同槽同轮：lps[].pts[].td="超惠飞" → labels 含
    （同白名单词，中转 9C 段在场即捕获；无值不落键律随 labels
    既有出口）。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "9C6117", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 820, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "超惠飞"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows, "中转样本应产出至少一行"
    assert "超惠飞" in rows[0].get("labels", ""), rows[0]


def test_tongcheng_chaohuifei_transfer_absent_keeps_service_labels():
    """中转无超惠飞时 labels 维持服务承诺原形——白名单并链不得
    挤掉既有 fw_txt 档（第二段服务承诺）。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows
    assert "超惠飞" not in rows[0].get("labels", ""), rows[0]


# ---- Soldier P1-1/P1-2：随最低价政策复位（脏携带复现钉） ----

def test_tongcheng_chaohuifei_no_carryover_direct():
    """Soldier P1-1：直飞多政策 [超惠飞@670, 普通经济舱@500]——
    500 行成为最低价时 chaofei 必须随政策复位，「超惠飞」不得
    脏携带到普通舱行 labels（ Soldiery 探针场景）。"""
    text = _tc_direct(
        lps=[{"atp": 670, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "超惠飞"}]},
             {"atp": 500, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "5.4折经济舱"}]}])
    out = TongchengCrawler._extract_flights(text)
    assert len(out) == 1
    f = out[0]
    assert f["price"] == 500, f
    assert "超惠飞" not in f.get("labels", ""), f


def test_tongcheng_chaohuifei_no_carryover_transfer():
    """Soldier P1-2：中转多政策 [超惠飞@820(带WiFi), 普通@600(无fwbqs)]
    ——600 行成为最低价时超惠飞与服务承诺双双复位，陈旧 fw_txt
    通道不得把上一政策的词面残留到新最低价行。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "9C6117", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 820, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "超惠飞"}],
                   "fwbqs": [{"td": "第2程：免费上网"}]},
                  {"atp": 600, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows
    f = rows[0]
    assert f.get("price") == 600, f
    assert "超惠飞" not in f.get("labels", ""), f
    assert "免费上网" not in f.get("labels", ""), f


def test_tongcheng_chaohuifei_exact_match_only():
    """Soldier Minor-2：白名单精确匹配的值域免疫——近形词面
    （「超惠飞X」子串变异）不得命中。"""
    text = _tc_direct(
        lps=[{"atp": 670, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "超惠飞X"}]}])
    out = TongchengCrawler._extract_flights(text)
    f = out[0]
    assert "超惠飞" not in f.get("labels", ""), f
