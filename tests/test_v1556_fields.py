# -*- coding: utf-8 -*-
"""渠道字段第八批回归：qunar binfo.name 机型补采 + 年龄限制
标签白名单 / tongcheng 段级换乘楼配对 + data.pc 改期日历（trendGo 同
协议双渠道）/ fliggy 无餐食负向标签 + 中转行一期解析（日期时刻行+
中转定证行+机建燃油）/ ctrip aset 权益词扩充 / 哨兵 qunar|plane 移出
死键表 + tongcheng|tterm 入白名单。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1556_fields.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("t1556")
_CT = CtripCrawler({}, _LOG)


# ---- qunar：binfo.name 机型补采 ----

def _h5_direct(**binfo):
    f = {"minPrice": 1200, "code": "9C8846", "mixFlightName": "春秋9C8846",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f["binfo"].update(binfo)
    return f


def test_qunar_h5_plane_from_binfo_name():
    """binfo.name[1] 是 JSON 真值机型「波音737(中)」（dump 直飞 83%
    在场、值域 4 种干净形态）；体量括号同步落 planeSize。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_direct(name=["春秋", "波音737(中)"])])
    assert rows[0]["plane"] == "波音737(中)"
    assert rows[0]["planeSize"] == "中型机"
    rows2 = QunarCrawler._extract_flights_obj(
        [_h5_direct(name=["南航", "空客330(大)"])])
    assert rows2[0]["plane"] == "空客330(大)"
    assert rows2[0]["planeSize"] == "大型机"


def test_qunar_h5_plane_rejects_dirty_forms():
    """fullmatch 锚定：无体量形态「空客330」/带尾缀「737-800」「波音
    737MAX8」/共享行实际承运号「HO1256」一律不落（宁缺勿错）。"""
    for dirty in (["南航", "空客330"], ["厦航", "737-800"],
                  ["吉祥", "HO1256"], ["春秋", "波音737MAX8"],
                  ["春秋"], None):
        rows = QunarCrawler._extract_flights_obj(
            [_h5_direct(name=dirty)])
        assert rows[0]["plane"] == "", dirty
        assert rows[0]["planeSize"] == "", dirty


def test_qunar_h5_labels_age_limit_tops():
    """年龄限制硬性购买资格置顶收（限N 岁买错无法值机），正则 ^限\\d
    变体整句透传；截断 [:2] 下不被营销词挤掉。"""
    f = _h5_direct()
    f["listLabel"] = {"priceBottomLabels": [
        {"text": "已优惠￥7"},
        {"text": "限55岁(含)以上的旅客购买"},
        {"text": "出票后2小时内错购退票"}]}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["labels"].startswith("限55岁")
    assert "出票后2小时内错购退票" in rows[0]["labels"]
    # 变体：限N-N人·且需N周岁 / 限16-23(含)周岁预定
    f2 = _h5_direct()
    f2["listLabel"] = {"priceBottomLabels": [
        {"text": "限16-23(含)周岁的旅客预定"}]}
    rows2 = QunarCrawler._extract_flights_obj([f2])
    assert rows2[0]["labels"] == "限16-23(含)周岁的旅客预定"


def test_qunar_h5_labels_zhengzhou_rights():
    """「郑州机场中转权益」服务承诺词入白名单（dump 5-9 次/份中转行）；
    非白名单营销词维持不采。"""
    f = _h5_direct()
    f["listLabel"] = {"priceBottomLabels": [
        {"text": "中转低价"}, {"text": "郑州机场中转权益"}]}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["labels"] == "郑州机场中转权益"


# ---- tongcheng：段级换乘楼配对 + 改期日历 ----

def test_tongcheng_transfer_terminals_pair():
    """中转楼=ss[0].aat（段级真值，fp 层是整行口径）、二段出发楼=
    ss[1].dat 配对成换乘路径；ss[1].dat 空串（张掖例）如实留空。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "西安",
          "ss": [{"fn": "CZ6981", "aat": "T3"},
                 {"fn": "MU5700", "dat": "T5"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows[0]["transTerminal"] == "T3"
    assert rows[0]["transDepTerminal"] == "T5"
    fp2 = dict(fp, ss=[{"fn": "CZ6981", "aat": "T1"},
                       {"fn": "MU5700", "dat": ""}])
    rows2 = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp2]}}))
    assert rows2[0]["transTerminal"] == "T1"
    assert rows2[0]["transDepTerminal"] == ""


def test_tongcheng_trendgo_mounts_on_lowest():
    """data.pc[] 改期日历按 qunar trendGo 同协议落当轮最低价行：坏点
    （dd 形态/价越界）弃、hlp 不采；[[MM-DD,价],…] 形态。"""
    fl = [{"fn": "9C8846", "dt": "2026-10-06 16:40", "at": "2026-10-06 21:30",
           "atp": 2200, "lps": [{"atp": 2200, "brs": [{"al": 3}]}]},
          {"fn": "CZ6981", "dt": "2026-10-06 08:00", "at": "2026-10-06 12:00",
           "atp": 1800, "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}]
    pc = [{"dd": "2026-09-29", "lp": 750, "hlp": 2350},
          {"dd": "2026-10-6", "lp": 800},          # 坏点：dd 非零补形态
          {"dd": "2026-10-07", "lp": 20},          # 坏点：价越界
          {"dd": "2026-10-08"},                    # 坏点：缺 lp
          {"dd": "2026-10-06", "lp": 1800}]
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": fl, "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["code"] == "CZ6981"
    assert lo["trendGo"] == [["09-29", 750], ["10-06", 1800]]
    hi = next(r for r in rows if r["code"] == "9C8846")
    assert "trendGo" not in hi


# ---- fliggy：无餐食标签 + 中转行一期解析 ----

def test_fliggy_meal_negative_label():
    """机型行同行尾「无餐食」负向标签（has-food-label，出现即真）落
    meal 既有键；无标签行不落（有餐食不打标）。"""
    txt = ("春秋9C7006\n中型机 320 无餐食\n15:15\n21:30\n"
           "乌鲁木齐天山国际机场\n虹桥国际机场T1\n¥620 5.0折")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    hit = [r for r in rows if r.get("code") == "9C7006"]
    assert hit and hit[0]["meal"] == "无餐食"
    txt2 = "东航MU8369\n中型机 737\n15:15\n16:10\n" \
           "乌鲁木齐天山国际机场\n虹桥国际机场T1\n¥920 5.0折"
    rows2 = FliggyCrawler._parse_pc_text(txt2, "2026-10-05")
    assert rows2 and "meal" not in rows2[0]


def test_fliggy_transfer_row_full_parse():
    """中转块一期：二段行头+机型行 → 4 条日期时刻行 → 出发机场 →
    「城市中转」定证 → 到达机场 → 价/税/余票。合并 code「A/B」、
    时刻取 _dtl 首末、衔接=首段落−二段起（transInfo 真值豁免）、
    跨天按日期差、机建燃油行不夺主价。"""
    txt = "\n".join([
        "春秋9C7006", "中型机 320",          # 首段（pend）
        "春秋9C7310", "中型机 320 无餐食",   # 二段（cur）
        "10月05日 15:15", "10月05日 19:05",  # 首段起/落
        "10月06日 06:05", "10月06日 07:55",  # 二段起/落
        "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
        "100.0%", "约17小时",
        "¥2060 5.0折", "¥240机建燃油", "少量", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["code"] == "9C7006/9C7310"
    assert r["name"] == "春秋9C7006"
    assert r["depTime"] == "15:15" and r["arrTime"] == "07:55"
    assert r["depDate"] == "2026-10-05" and r["arrDate"] == "2026-10-06"
    assert r["crossDayDesc"] == "+1天"
    assert r["transCity"] == "石家庄"
    assert r["layover"] == 660 and r["layoverSrc"] == "transInfo"
    assert r["lay2dep"] == "06:05"
    assert r["price"] == 2060 and r["transferTax"] == 240
    assert r["fewTicket"] == "少量"
    assert r["meal"] == "无餐食"
    assert r["depAirport"] == "乌鲁木齐天山国际机场"
    assert r["arrAirport"] == "虹桥国际机场" and r["arrTerminal"] == "T1"


def test_fliggy_transfer_tax_guard_not_alt_price():
    """税行守卫：越界值（<60）不落 transferTax，且不得被价格分支当
    副价 min 吞（¥50 若落入比价支，主价 2060→50 即脏价）。"""
    txt = "\n".join([
        "春秋9C7006", "中型机 320",
        "春秋9C7310", "中型机 320",
        "10月05日 15:15", "10月05日 19:05",
        "10月06日 06:05", "10月06日 07:55",
        "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
        "¥2060 5.0折", "¥50机建燃油", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert len(rows) == 1
    assert rows[0]["price"] == 2060
    assert "transferTax" not in rows[0]


def test_fliggy_direct_rows_unaffected():
    """直飞行既有行为回归：双价行/余票/折扣/准点率分支在新分支共存下
    行为不变（中转块新分支只对「N月N日 HH:MM」「XX中转」两种新形态
    放行，直飞裸 HH:MM 序列零接触）。"""
    txt = "\n".join([
        "东航MU8369", "中型机 737", "16:40", "21:30 第2天",
        "乌鲁木齐天山国际机场", "虹桥国际机场T2", "94.5%",
        "¥920 5.0折", "少量",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert len(rows) == 1
    r = rows[0]
    assert r["depTime"] == "16:40" and r["arrTime"] == "21:30"
    assert r["crossDayDesc"] == "+1天"
    assert r["prate"] == "94" and r["fewTicket"] == "少量"
    assert r["arrTerminal"] == "T2"
    assert r["transCity"] == ""


# ---- ctrip：aset 权益词扩充 ----

def _ctrip_item(segs, policies, aset=None):
    item = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        item["aset"] = aset
    return item


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200):
    return {"tprice": price, "quantity": 5, "drate": 5.2}


def test_ctrip_labels_new_rights_words():
    """第八批扩充：中转餐饮/免费市区班车/宠物进客舱入 labels；地域
    品牌词（经兰飞/豫转豫好）churn 风险不收；中转住宿与政策级 nt=10
    同义不重复（hotel_free 既有出口）。"""
    aset = [{"tagarea": [{"tagcnt": t} for t in (
        "中转餐饮", "免费市区班车", "宠物进客舱",
        "经兰飞如意行权益", "享\"豫转豫好\"免费服务", "中转住宿")]}]
    item = _ctrip_item([_ctrip_seg("2026-10-06 16:40:00",
                                   "2026-10-06 21:30:00")],
                       [_ctrip_policy()], aset=aset)
    r = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert "中转餐饮" in r["labels"]
    assert "免费市区班车" in r["labels"]
    assert "宠物进客舱" in r["labels"]
    assert "经兰飞" not in r["labels"]
    assert "豫转豫好" not in r["labels"]
    assert "中转住宿" not in r["labels"]   # policy 级 nt=10 既有出口


# ---- 哨兵：qunar|plane 移出死键表 + tongcheng|tterm 入白名单 ----

def test_sentinel_qunar_plane_now_observed(monkeypatch, tmp_path):
    """qunar|plane H5 有源（移出死键表）：全灭轮应告警（比率
    观测 <10%）、命中轮不告警——键死静默回归 tx→td 事故有观测兜底。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    dead = [{"price": 1000, "cabin": "经济舱"} for _ in range(30)]
    _m._field_sentinel([_NS(platform="qunar", extra=json.dumps(dead))], _L())
    assert any("qunar" in str(a) and "plane" in str(a) for a in seen), seen
    seen.clear()
    alive = [{"price": 1000, "cabin": "经济舱", "plane": "波音737(中)"}
             for _ in range(30)]
    _m._field_sentinel([_NS(platform="qunar", extra=json.dumps(alive))], _L())
    assert not any("plane" in str(a) for a in seen), seen


def test_sentinel_tongcheng_tterm_whitelisted(monkeypatch, tmp_path):
    """tongcheng|tterm 入白名单恒 0 观测：中转行 ≥20 且换乘楼全灭应
    告警、带值不告警（中转行 <20 门槛不报——供给侧稀疏非键死）。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    dead = [{"price": 1000, "transCity": "西安"}
            for _ in range(20)]
    dead += [{"price": 1000} for _ in range(10)]
    _m._field_sentinel([_NS(platform="tongcheng", extra=json.dumps(dead))],
                       _L())
    assert any("tterm" in str(a) or "transTerminal" in str(a)
               for a in seen), seen
    seen.clear()
    alive = [{"price": 1000, "transCity": "西安", "transTerminal": "T2"}
             for _ in range(20)]
    alive += [{"price": 1000} for _ in range(10)]
    _m._field_sentinel([_NS(platform="tongcheng", extra=json.dumps(alive))],
                       _L())
    assert not any("tterm" in str(a) or "transTerminal" in str(a)
                   for a in seen), seen


# ---- 修复回归 ----

def test_fliggy_double_transfer_block_dropped():
    """三段两转异形块宁缺勿错整行弃（实跑复现：二次定证曾
    覆写 transCity/中转机场错占 arr 位/pend 顶成二段，产出多字段错值
    行看似正常入库）。"""
    txt = "\n".join([
        "春秋9C7006", "中型机 320",
        "春秋9C7310", "中型机 320",
        "春秋9C8801", "中型机 320",
        "10月05日 15:15", "10月05日 19:05",
        "10月06日 06:05", "10月06日 09:05",
        "10月06日 12:05", "10月06日 14:05",
        "乌鲁木齐天山国际机场", "石家庄中转", "正定国际机场",
        "郑州中转", "虹桥国际机场T1",
        "¥2060 5.0折", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert rows == [], rows


def test_fliggy_transfer_truth_survives_phantom_guard():
    """低价中转真值豁免 0.5x 中位幻影锚（¥900 中转 vs 直飞
    群 2020 曾被误杀弃行——layoverSrc=transInfo 是渠道结构化真值非页面
    猜测，守卫只服务猜测值）。"""
    direct = ("东航MU836%d\n中型机 737\n1%d:1%d\n1%d:2%d\n"
              "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥1980 5.0折")
    blocks = [direct % (i, 6 + i, i, 7 + i, i) for i in range(4)]
    trans = "\n".join([
        "春秋9C7006", "中型机 320",
        "春秋9C7310", "中型机 320",
        "10月05日 15:15", "10月05日 19:05",
        "10月06日 06:05", "10月06日 07:55",
        "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
        "¥900 5.0折", "¥240机建燃油", "订票",
    ])
    txt = "\n".join(blocks + [trans])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    codes = [r["code"] for r in rows]
    assert "9C7006/9C7310" in codes, codes
    tr = next(r for r in rows if r["code"] == "9C7006/9C7310")
    assert tr["price"] == 900 and tr["transferTax"] == 240