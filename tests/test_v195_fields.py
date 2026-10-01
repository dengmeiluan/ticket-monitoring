# -*- coding: utf-8 -*-
"""tongcheng ieso 售罄标记（r195 数据层唯一立案，B 路规格落地）。

报文路径 tc/book1/data/fl/[].ieso，bool，舱位域标记（非航班域）：
True=经济舱舱域售罄，公务/头等仍可能有余票（CA8564 实证 ieso=True
同时公务 brs_al=30）。词面与 ctrip tcode=EconomyClassSellOut 同串
「经济舱售罄」，同挂 labels 既有键——webui 明细列/CSV/report PNG
标签槽三端零改动。

判定链（宁漏勿错，四重守卫）：
  ieso is True（严格 bool）且 无任何有票的(超级)经济舱政策
  且 幸存行舱位名解析成功 且 幸存行非(超级)经济舱 → labels 追加。

两代报文形态通吃：
  第一代（09-24）：经济舱政策在场但 brs_al=0（被 _has_ticket 过滤）；
  第二代（09-28）：经济舱政策整条消失，仅剩公务 9900。
CZ6975 09-24 True→09-28 False 证明 ieso 是随抓取轮滚动的快照态，
词随轮重算无跨轮残留面。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v195_fields.py -q
"""

import json

import pytest

from crawlers.tongcheng import TongchengCrawler  # noqa: E402


def _tc_flight(**over):
    """最小 book1 航班（形态照抄 tests/test_v1554_fields.py 同族构造，
    真值锚：CA8564 2026-10-06 16:50 ieso=True 第二代=公务 9900 al=30）。"""
    f = {"fn": "CA8564", "dt": "2026-10-06 16:50:00",
         "at": "2026-10-06 21:35:00", "asn": "国航",
         "dasn": "天山", "aasn": "虹桥",
         "amt": "中", "afn": "空客330(中)",
         "lps": [{"atp": "9900", "brs": [{"al": 30}],
                  "pts": [{"td": "公务舱"}]}],
         "ieso": True}
    f.update(over)
    return json.dumps({"success": True, "data": {"fl": [f]}})


def _one(text):
    fs = TongchengCrawler._extract_flights(text)
    assert len(fs) == 1
    return fs[0]


def test_tongcheng_ieso_sellout_label_second_gen():
    """第二代形态：经济舱政策整条消失、仅剩公务有票 → 挂「经济舱售罄」。"""
    f = _one(_tc_flight())
    assert f["price"] == 9900 and f["cabin"] == "公务舱"
    assert "经济舱售罄" in f["labels"].split("·")


def test_tongcheng_ieso_first_gen_eco_policy_without_ticket():
    """第一代形态：经济舱政策在场但 al=0（无票被既有守卫滤），
    公务舱有票幸存 → 仍挂词（两代通吃）。"""
    f = _one(_tc_flight(lps=[
        {"atp": "2770", "brs": [{"al": 0}],
         "pts": [{"td": "7折经济舱"}]},
        {"atp": "9900", "brs": [{"al": 30}],
         "pts": [{"td": "公务舱"}]},
    ]))
    assert f["price"] == 9900 and f["cabin"] == "公务舱"
    assert "经济舱售罄" in f["labels"].split("·")


def test_tongcheng_ieso_contradiction_not_labeled():
    """矛盾态守卫：ieso=True 但经济舱政策有票（B 路两轮语料 0 例的
    幻想形态）→ 一律不挂，宁漏勿错。"""
    f = _one(_tc_flight(lps=[
        {"atp": "2770", "brs": [{"al": 9}],
         "pts": [{"td": "7折经济舱"}]},
        {"atp": "9900", "brs": [{"al": 30}],
         "pts": [{"td": "公务舱"}]},
    ]))
    assert f["price"] == 2770 and f["cabin"] == "经济舱"
    assert "经济舱售罄" not in f["labels"]


def test_tongcheng_ieso_eco_survivor_not_labeled():
    """防御：ieso=True 且幸存行自身就是(超级)经济舱 → 不挂
    （「经济舱售罄」挂经济舱行=语义自相矛盾）。"""
    f = _one(_tc_flight(
        lps=[{"atp": "2770", "brs": [{"al": 30}],
              "pts": [{"td": "7折经济舱"}]}]))
    assert f["cabin"] == "经济舱"
    assert "经济舱售罄" not in f["labels"]


@pytest.mark.parametrize("ieso", [False, None, "", "true", 1])
def test_tongcheng_ieso_non_strict_true_ignored(ieso):
    """类型守卫：严格 `is True`——False/缺失/空串/字符串"true"/1
    都不是渠道售罄声明（-1/1 类真值会误挂常态行）。"""
    f = _one(_tc_flight(ieso=ieso))
    assert "经济舱售罄" not in f["labels"]


def test_tongcheng_ieso_cabin_parse_fail_not_labeled():
    """舱位名解析失败（pts.td 无舱位词）→ 不挂，宁漏勿错。"""
    f = _one(_tc_flight(
        lps=[{"atp": "9900", "brs": [{"al": 30}],
              "pts": [{"td": "6.8折"}]}]))
    assert f["cabin"] == ""
    assert "经济舱售罄" not in f["labels"]


def test_tongcheng_ieso_labels_join_order():
    """既有标签共存：clct 舒适词在前、售罄词殿后，「·」join 单串。"""
    f = _one(_tc_flight(lps=[
        {"atp": "9900", "brs": [{"al": 30}],
         "pts": [{"td": "公务舱"}],
         "clct": [{"tt": 1, "td": "大机型"},
                  {"tt": 3, "td": "座椅较宽"}]}]))
    assert f["labels"] == "大机型·座椅较宽·经济舱售罄"


def test_tongcheng_ieso_absent_flight_unchanged():
    """回归锚：报文无 ieso 键的常态航班 labels 组装零变化。"""
    f = _one(_tc_flight(ieso=None))
    assert f["labels"] == ""


# ---- demo 演示面：tongcheng 售罄词目检覆盖（同 v191 meal 演示先例） ----

def test_demo_covers_ieso_sellout_label(tmp_path):
    """tongcheng 演示行 labels 含「经济舱售罄」（演示目检面与生产
    值域对齐——真实形态挂公务舱幸存行）。"""
    import sqlite3
    import core.demo as demo
    db = str(tmp_path / "demo.db")
    demo.build_demo_db(db)
    conn = sqlite3.connect(db)
    labels = set()
    for (extra,) in conn.execute(
            "SELECT extra FROM flight_prices WHERE platform='tongcheng' "
            "AND extra != ''"):
        for f in json.loads(extra):
            if f.get("labels"):
                labels.update(f["labels"].split("·"))
    conn.close()
    assert "经济舱售罄" in labels, "tongcheng 售罄词无演示目检面"
