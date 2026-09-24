# -*- coding: utf-8 -*-
"""渠道字段第九批回归：tongcheng leftTickets 余票紧张度（atpt
随最低价政策配对）/ ctrip transferService 联程服务明细（nt=103 flag=1）
/ qunar PC transferService+labelNote（软拒期搭车复活预案）/ qunar H5
bizPrice 备源（bizVendorPrice.totalPrice）+ labels 白名单三词 +
stopCitys 脏值卫生修复 / fliggy transTerminal 换乘楼号 + pend 首段
meal 合并 / 推送层 TIER_TABLE 档位词面单源收编（词面零变化）+ report
few 槽 leftTickets 双源 / demo 载体。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1557_fields.py
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

_LOG = logging.getLogger("t1557")
_CT = CtripCrawler({}, _LOG)


# ---- tongcheng：leftTickets 余票紧张度 ----

def _tc_flight(**extra):
    f = {"fn": "MF2370", "asn": "厦航", "dt": "2026-10-06 10:10",
         "at": "2026-10-06 14:55", "td": "4h45m", "amt": "中",
         "lps": [{"atp": 4350, "brs": {"al": 20},
                  "atpt": {"tt": 1, "td": "余1张"},
                  "pts": [{"tt": 2, "td": "全价经济舱"}]}]}
    f.update(extra)
    return f


def _tc_book1(f):
    obj = {"success": True, "data": {"ec": 0, "fl": [f]}}
    return json.dumps(obj, ensure_ascii=False)


def test_tongcheng_lefttickets_policy_paired():
    """atpt 随最低价政策配对（余N张=页红字稀缺真值，「余1张」→int）；
    与 ctrip leftTickets 同名同域。"""
    rows = TongchengCrawler._extract_flights(_tc_book1(_tc_flight()))
    assert rows[0]["leftTickets"] == 1


def test_tongcheng_lefttickets_guard_and_absent():
    """值域守卫 1-9（≥10 渠道不发标签、余0张=脏值）；键缺省不落键
    （稀疏事件型，空=充足，勿造 0）。"""
    f = _tc_flight()
    f["lps"][0]["atpt"]["td"] = "余10张"
    rows = TongchengCrawler._extract_flights(_tc_book1(f))
    assert "leftTickets" not in rows[0]
    f2 = _tc_flight()
    f2["lps"][0]["atpt"]["td"] = "余0张"
    rows2 = TongchengCrawler._extract_flights(_tc_book1(f2))
    assert "leftTickets" not in rows2[0]
    f3 = _tc_flight()
    del f3["lps"][0]["atpt"]
    rows3 = TongchengCrawler._extract_flights(_tc_book1(f3))
    assert "leftTickets" not in rows3[0]


def test_tongcheng_lefttickets_lowest_policy_not_bystander():
    """随最低价政策配对：非最低价政策带 atpt 不得串行（同 cabin 同律
    防政策错配）。"""
    f = _tc_flight(lps=[
        {"atp": 4350, "brs": {"al": 20},
         "atpt": {"tt": 1, "td": "余1张"}},
        {"atp": 4600, "brs": {"al": 20},
         "atpt": {"tt": 1, "td": "余3张"}}])
    rows = TongchengCrawler._extract_flights(_tc_book1(f))
    assert rows[0]["leftTickets"] == 1


def test_tongcheng_lefttickets_reset_on_lower_policy():
    """倒序脏携带：先高价新政带 atpt、后遍历到
    更低价政策无 atpt——leftTickets 必须复位不落，不得残留高价政策
    的值（与 ctrip best_qty 无条件复位同律）。"""
    f = _tc_flight(lps=[
        {"atp": 4600, "brs": {"al": 20},
         "atpt": {"tt": 1, "td": "余3张"}},
        {"atp": 4350, "brs": {"al": 20}}])
    rows = TongchengCrawler._extract_flights(_tc_book1(f))
    assert rows[0]["price"] == 4350
    assert "leftTickets" not in rows[0]


# ---- ctrip：transferService 联程服务明细（nt=103）----

_NT103 = {"notetype": 103, "notecnt": json.dumps(
    {"flag": 1, "key": "G5-LC-V2", "title": "华夏联程专享：",
     "value": "转机引导、行李直挂、航变免费改、一次值机、"
              "20KG免费行李、一次安检"}, ensure_ascii=False)}


def _ctrip_item(notes=(), segs=2):
    """最小中转 fltitem（两段 URC→SHA 经停形态）。"""
    dd, ad = "2026-10-06 14:00:00", "2026-10-06 20:50:00"
    seg_list = []
    for i in range(segs):
        seg_list.append({
            "basinfo": {"flgno": "G583F6C" if i == 0 else "G54332"},
            "dateinfo": {"ddate": dd if i == 0 else "2026-10-06 16:10:00",
                         "adate": dd if i == 0 else ad},
            "dportinfo": {"bsname": "T3", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}})
    return {"fcode": "G583F6C", "ddate": dd, "adate": ad,
            "mutilstn": seg_list,
            "notes": list(notes),
            "policyinfo": [{"tprice": 4050, "quantity": 9,
                            "drate": 6.7,
                            "classinfor": [{"cgrd": 0, "prate": 89}]}]}


def test_ctrip_transfer_service_nt103():
    """nt=103 flag=1 内嵌 JSON value 全文落 transferService（与
    tongcheng/qunar 同键同语义位）；title 产品名（地域品牌词）不并串。"""
    rows = _CT._extract_ctrip_flights(
        json.dumps({"fltitem": [_ctrip_item((_NT103,))]},
                   ensure_ascii=False))
    r = rows[0]
    assert r["transferService"].startswith("转机引导")
    assert "20KG免费行李" in r["transferService"]
    assert "华夏联程" not in r["transferService"]


def test_ctrip_transfer_service_flag0_sentinel_skipped():
    """flag=0（DEFAULT-TC 哨兵，value 空串）跳过——10-06 dump 5 处
    全此形态，键不落。"""
    sentinel = {"notetype": 103, "notecnt": json.dumps(
        {"flag": 0, "key": "DEFAULT-TC", "value": ""}, ensure_ascii=False)}
    rows = _CT._extract_ctrip_flights(
        json.dumps({"fltitem": [_ctrip_item((sentinel,))]},
                   ensure_ascii=False))
    assert "transferService" not in rows[0]


def test_ctrip_transfer_service_direct_gain_transfer_only():
    """「行李直挂」词条在真中转行（多段）补 transferBaggage=direct
    增益；单段行 is_transfer 门控天然不触发（键语义=中转行专属）。"""
    rows = _CT._extract_ctrip_flights(
        json.dumps({"fltitem": [_ctrip_item((_NT103,), segs=2)]},
                   ensure_ascii=False))
    assert rows[0]["transferBaggage"] == "direct"
    rows1 = _CT._extract_ctrip_flights(
        json.dumps({"fltitem": [_ctrip_item((_NT103,), segs=1)]},
                   ensure_ascii=False))
    assert rows1[0]["transferBaggage"] == ""


# ---- qunar PC：transferService + labelNote ----

def _pc_flight(**extra):
    f = {"minPrice": 1200, "code": "MF8266",
         "binfo": {"depTime": "12:05", "arrTime": "16:40",
                   "depDate": "2026-10-04", "arrDate": "2026-10-04",
                   "shortName": "厦航", "airCode": "MF8266"},
         "extparams": {}}
    f.update(extra)
    return f


def test_qunar_pc_transfer_service():
    """transitServiceLabel 短文本本体+Name 前缀落 transferService（    仅 _baggage_tag 找子串落布尔）；与 tongcheng/ctrip 同键同位。"""
    f = _pc_flight(transitServiceLabel="本服务包含免二次安检、免费餐食",
                   transitServiceLabelName="中转优享")
    rows = QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f]}}), "2026-10-04")
    assert rows[0]["transferService"] == "中转优享:本服务包含免二次安检、免费餐食"
    # Name 缺省退化裸 Label
    f2 = _pc_flight(transitServiceLabel="隔夜免费住宿")
    rows2 = QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f2]}}), "2026-10-04")
    assert rows2[0]["transferService"] == "隔夜免费住宿"
    # 双缺不落键
    rows3 = QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [_pc_flight()]}}), "2026-10-04")
    assert "transferService" not in rows3[0]


def test_qunar_pc_labelnote_forms():
    """priceLabel[].note 首条非空落 labelNote（str/数组双形态）；
    超 80 字截断；空数组/缺省不崩不落。"""
    note = "享受退改保护，如不可抗力导致一程航班调整，可致电去哪儿网或在机场柜台免费办理另一程改签或退票"
    f = _pc_flight(priceLabel=[{"name": "取消延误免费改", "note": note}])
    rows = QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f]}}), "2026-10-04")
    assert rows[0]["labelNote"] == note[:80]
    f2 = _pc_flight(priceLabel=[{"name": "宠物友好", "note": [note[:40]]}])
    rows2 = QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f2]}}), "2026-10-04")
    assert rows2[0]["labelNote"] == note[:40]
    f3 = _pc_flight(priceLabel=[{"name": "免费上网", "note": []}])
    rows3 = QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f3]}}), "2026-10-04")
    assert "labelNote" not in rows3[0]


# ---- qunar H5：bizPrice 备源 / labels 白名单三词 / stopCitys 脏值 ----

def test_qunar_h5_bizprice_fallback_source():
    """主源 businessClassMinPrice 无正值时 bizVendorPrice.totalPrice
    兜底（同现 260/260 值全等已证同义，备源独有行全为中转行）；主源
    优先；int 协议；备源 0/脏值不落。"""
    f = _h5_row(bizVendorPrice={"totalPrice": "4680"})
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["bizPrice"] == 4680
    assert isinstance(rows[0]["bizPrice"], int)
    # 主源在场时优先（int(2320.0) 主源形态）
    f["extparams"] = json.dumps({"businessClassMinPrice": 2320})
    rows2 = QunarCrawler._extract_flights_obj([f])
    assert rows2[0]["bizPrice"] == 2320
    # 备源脏值/零不落
    f3 = _h5_row(bizVendorPrice={"totalPrice": 0})
    rows3 = QunarCrawler._extract_flights_obj([f3])
    assert "bizPrice" not in rows3[0]
    f4 = _h5_row(bizVendorPrice="dirty")
    rows4 = QunarCrawler._extract_flights_obj([f4])
    assert "bizPrice" not in rows4[0]


def _h5_row(**extra):
    f = {"minPrice": 1200, "code": "SC8716/MU5534",
         "mixFlightName": "春秋9C8846", "transCity": "济南",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f.update(extra)
    return f


def test_qunar_h5_labels_whitelist_three_words():
    """全词表复核新并 3 词：宠物友好/弃餐赠里程/联程航班服务（服务
    承诺型，582 行 8 dump 仅 4 行稀疏在场）；营销 churn 维持不采。"""
    for word in ("宠物友好", "弃餐赠里程", "联程航班服务"):
        f = _h5_row(listLabel={"priceBottomLabels": [
            {"text": "比直飞省￥120"}, {"text": word}]})
        rows = QunarCrawler._extract_flights_obj([f])
        assert rows[0]["labels"] == word, word


def test_qunar_h5_stopcitys_placeholder_cleanup():
    """渠道恒逗号占位「,」归一后成裸「;」——纯分隔符形态视为占位落
    空串（30 行/轮脏值进 extra 污染覆盖率统计）；真值「西安;库尔勒」
    剥后非空不受影响。"""
    f = _h5_row(binfo={"depTime": "16:40", "arrTime": "21:30",
                       "depDate": "2026-10-06", "arrDate": "2026-10-06",
                       "stopsCitys": ",", "stopsAirPort": ","})
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["stopCitys"] == ""
    assert rows[0]["stopAirports"] == ""
    f2 = _h5_row(binfo={"depTime": "16:40", "arrTime": "21:30",
                        "depDate": "2026-10-06", "arrDate": "2026-10-06",
                        "stopsCitys": "西安,库尔勒"})
    rows2 = QunarCrawler._extract_flights_obj([f2])
    assert rows2[0]["stopCitys"] == "西安;库尔勒"


# ---- fliggy：transTerminal 换乘楼号 + pend 首段 meal 合并 ----

_TRANSFER_TXT = "\n".join([
    "春秋9C7006", "中型机 320",          # 首段（pend）
    "春秋9C7310", "中型机 320",          # 二段（cur）
    "10月05日 15:15", "10月05日 19:05",
    "10月06日 06:05", "10月06日 07:55",
    "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
    "¥2060 5.0折", "订票",
])


def test_fliggy_trans_terminal_pairing():
    """_TRANSFER_JS 楼号按首段号配对（行容器归属），剥「国际机场/机场」
    后缀对齐 qunar「咸阳T3」同形；二段号兜底；无映射不落。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"9C7006": "正定国际机场T2"})
    assert rows[0]["transTerminal"] == "正定T2"
    rows2 = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"9C7310": "正定机场T2"})
    assert rows2[0]["transTerminal"] == "正定T2"
    rows3 = FliggyCrawler._parse_pc_text(_TRANSFER_TXT, "2026-10-05")
    assert "transTerminal" not in rows3[0]


def test_fliggy_pend_meal_merged():
    """首段「无餐食」二段未标：合并后 meal 保留（只搬 code/name/
    shareCarrier 首段标签整段丢失）；两段同标同值无冲突。"""
    lines = _TRANSFER_TXT.split("\n")
    lines[1] = "中型机 320 无餐食"   # 首段机型行打负标签
    rows = FliggyCrawler._parse_pc_text("\n".join(lines), "2026-10-05")
    assert rows[0]["meal"] == "无餐食"


def test_fliggy_transfer_js_regex_covers_digit_head():
    """_TRANSFER_JS 行号正则覆盖数字头二字码（9C7006 数字开头——
     旧正则采出「C7006」与解析侧 9C7006 配对全
    MISS，功能在唯一实证样本恒空），与 _RE_FNO 同支路。"""
    src = open("crawlers/fliggy.py", encoding="utf-8").read()
    assert r"((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})" in src
    for no in ("9C7006", "9C7310", "MU8369", "CZ6976"):
        assert FliggyCrawler._RE_FNO.search(no), no


# ---- 推送层：TIER_TABLE 档位词面单源收编 ----

def test_tier_table_projections():
    """五档×四投影完整性（qual/mkt/near/over/fall），梯度同向；词面
     发版形态逐字节锁定。"""
    from core.alerter import (TIER_EMOJI, TIER_FULL, TIER_SHORT,
                              TIER_TRANSCRIBE)
    assert list(TIER_FULL) == ["qual", "mkt", "near", "over", "fall"]
    assert TIER_EMOJI == {"qual": "🎯", "mkt": "🟩", "near": "🟨",
                          "over": "", "fall": "▼"}
    assert TIER_FULL == {"qual": "真达标", "mkt": "行情破线",
                         "near": "擦边", "over": "超线",
                         "fall": "达标回落"}
    assert TIER_SHORT == {"qual": "真达标", "mkt": "破线", "near": "擦边",
                          "over": "超线", "fall": "达标回落"}
    assert TIER_TRANSCRIBE == {"qual": "真达标 ", "mkt": "行情价 ",
                               "near": "擦边 ", "over": "", "fall": ""}


def test_tier_legend_and_head_equiv():
    """收编词面零变化：图例行/图头片段输出与 逐字节一致。"""
    from core.alerter import Alerter, _TBL_HEAD_TIER, _MKT_SHORT
    leg = Alerter._legend_line()
    assert leg.startswith("> ⏱")
    assert "🎯真达标 🟩破线 🟨擦边 超线" in leg
    assert _TBL_HEAD_TIER == "深绿=真达标·描绿=破线"
    assert _MKT_SHORT == "行情"


def test_notifier_derived_words_equiv():
    """notifier 转写表/剥注表改挂投影后与 字面全等（别名保留
    同名）；转写序 🎯→🟩→🟨→🔥 即替换序不变。"""
    import core.notifier as N
    assert N._EMOJI_TIER_WORDS == (("🎯", "真达标 "), ("🟩", "行情价 "),
                                   ("🟨", "擦边 "), ("🔥", "命中 "))
    assert N._MKT_NOTE_DUPS == ("（行情价）", "*行情", "行情价", "行情破线")
    body = N._alert_body("🎯真达标 🟩破线 🔥命中")
    assert "🎯" not in body and "🟩" not in body and "🔥" not in body


def test_kpi_tier_txt_suffix_via_projection():
    """kpi_tier_txt 破线未达标「·行情」尾注走投影（词面不变）。"""
    from core.alerter import kpi_tier_txt
    assert kpi_tier_txt("最低", 1500, 1600, False) == "最低 ￥1500 低￥100·行情"
    assert kpi_tier_txt("最低", 1500, 1600, True) == "最低 ￥1500 低￥100"


# ---- report few 槽双源 + demo 载体 ----

def test_report_few_slot_lefttickets():
    """PNG 次行余票槽双源：fewTicket 文本优先，leftTickets 数值转
    「余N张」（ctrip/tongcheng 同键同协议，值域 1-9）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "leftTickets" in src
    assert 'f"余{f[\'leftTickets\']}张"' in src


def test_demo_carriers_for_new_fields():
    """demo 合成带齐新键载体：qunar/tongcheng 中转行 transferService、
    qunar labelNote 与 labels 配对（生产端唯一源=qunar PC）、tongcheng
    leftTickets（词面挂载体段纪律——载体缺则渲染门整段消失）。"""
    from core.demo import _mk_detail
    import random
    for plat in ("qunar", "tongcheng", "ctrip"):
        fs = _mk_detail(random.Random(7), plat, "2026-10-10", 1500)
        assert fs, plat
    tq = _mk_detail(random.Random(7), "tongcheng", "2026-10-10", 1500)
    assert any("transferService" in f for f in tq if f.get("transCity"))
    assert any("leftTickets" in f for f in tq)
    tqu = _mk_detail(random.Random(7), "qunar", "2026-10-10", 1500)
    assert any("transferService" in f for f in tqu if f.get("transCity"))
    assert "labelNote" in tqu[0]
    assert tqu[0].get("labels")
