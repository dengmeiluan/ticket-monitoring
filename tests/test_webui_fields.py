# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r254_fields.py
- tests/test_r805ar_field_health_app.py
- tests/test_v15104_fields.py
- tests/test_v15106_fields.py
- tests/test_v15109_fields.py
- tests/test_v15115_fields.py
- tests/test_v1554_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import logging
import os
import pytest
import sqlite3
import sys
import tempfile

from core.notifier import _alert_body
from crawlers.base import iata2
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler, _stop_window
from webui import _cluster_round_rows


# ---- merged from tests/test_r254_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _fl(lo_atp=1800, hi_atp=2200):
    return [{"fn": "9C8846", "dt": "2026-10-06 16:40", "at": "2026-10-06 21:30",
             "atp": hi_atp, "lps": [{"atp": hi_atp, "brs": [{"al": 3}]}]},
            {"fn": "CZ6981", "dt": "2026-10-06 08:00", "at": "2026-10-06 12:00",
             "atp": lo_atp, "lps": [{"atp": lo_atp, "brs": [{"al": 3}]}]}]


def test_tongcheng_trendbiz_mounts_on_lowest():
    """hlp 与 lp 同槽同循环提取，落 trendBiz 挂当轮最低价行（trendGo
    同律逐行重复=extra 膨胀）；[[MM-DD,价],…] 形态同协议。"""
    pc = [{"dd": "2026-09-29", "lp": 750, "hlp": 2350},
          {"dd": "2026-10-06", "lp": 1800, "hlp": 5100}]
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(), "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["trendGo"] == [["09-29", 750], ["10-06", 1800]]
    assert lo["trendBiz"] == [["09-29", 2350], ["10-06", 5100]]
    hi = next(r for r in rows if r["code"] == "9C8846")
    assert "trendBiz" not in hi


def test_tongcheng_trendbiz_bad_points_dropped():
    """hlp 逐点同门守卫（价域 100-50000、非数/缺失弃）：坏点逐点弃，
    lp 好点照常落 trendGo；全坏点不落键（空列表不占位）。"""
    pc = [{"dd": "2026-09-29", "lp": 750, "hlp": 99},        # 价越界
          {"dd": "2026-10-01", "lp": 800, "hlp": "abc"},      # 非数
          {"dd": "2026-10-02", "lp": 900},                    # 缺 hlp
          {"dd": "2026-10-03", "lp": 950, "hlp": 60000}]      # 价越界上缘
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(), "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["trendGo"] == [["09-29", 750], ["10-01", 800],
                             ["10-02", 900], ["10-03", 950]]
    assert "trendBiz" not in lo
    # 好点混排：好 hlp 照落、坏点同点弃
    pc2 = [{"dd": "2026-09-29", "lp": 750, "hlp": 2350},
           {"dd": "2026-10-01", "lp": 800}]
    rows2 = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(), "pc": pc2}}))
    lo2 = min(rows2, key=lambda f: f["price"])
    assert lo2["trendBiz"] == [["09-29", 2350]]


def test_tongcheng_trendbiz_real_dump_shape():
    """10-05 代真实 dump 形态（三点全等实锤样本）：pc[0] dd=2026-10-06
    hlp=5100 配 lp=2250——值落 DB bizPrice 带互证量级。"""
    pc = [{"dd": "2026-10-06", "lp": 2250, "hlp": 5100, "hms": "HO2290..."},
          {"dd": "2026-10-07", "lp": 1625, "hlp": 2895}]
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(2250, 2600), "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["trendBiz"] == [["10-06", 5100], ["10-07", 2895]]


# ---- D3: flight_no 列词面归一（双名前缀剥离——最低价行 name 带营销
#      双名「新海航｜天津航空GS6478」塞进 flight_no 槽，与 ctrip/tuniu/
#      fliggy 裸号口径不一；对账列回归裸号，extra.code 本就裸号） ----

def test_qunar_flight_no_bare_code(monkeypatch):
    """qunar flight_no 落最低价行 code（裸号）而非 name（双名前缀）。"""
    import logging
    from crawlers.qunar import QunarCrawler
    c = QunarCrawler({}, logging.getLogger("t254"))
    flights = [{"code": "GS6478", "name": "新海航｜天津航空GS6478",
                "price": 900.0, "depTime": "08:00", "arrTime": "12:00"},
               {"code": "9C8866", "name": "春秋航空9C8866",
                "price": 619.0, "depTime": "19:00", "arrTime": "23:40"}]
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: (619.0, flights))
    rows = c._fetch_inner("乌鲁木齐", "上海", ["2026-10-15"])
    assert rows and rows[0].flight_no == "9C8866"
    assert rows[0].depart_time == "19:00"


def test_tongcheng_flight_no_bare_code(monkeypatch):
    """tongcheng flight_no 同律落 code 裸号（browser 链 mock 全路径）。"""
    import contextlib
    import logging
    from unittest.mock import MagicMock
    c = TongchengCrawler({}, logging.getLogger("t254"))
    book1 = {"data": {"lp": 700, "fl": [
        {"fn": "GS7587", "asn": "天津航空", "dt": "2026-10-15 07:30",
         "at": "2026-10-15 11:50", "atp": 780,
         "lps": [{"atp": 780, "brs": [{"al": 3}]}]},
        {"fn": "CZ6993", "asn": "南航", "dt": "2026-10-15 12:00",
         "at": "2026-10-15 16:20", "atp": 700,
         "lps": [{"atp": 700, "brs": [{"al": 5}]}]}]}}
    monkeypatch.setattr(c, "browser",
                        lambda: contextlib.nullcontext(MagicMock()))
    monkeypatch.setattr(c, "attach_xhr_collector",
                        lambda page, keys: [
                            {"url": "https://x/book1/flights?d=1",
                             "text": json.dumps(book1)}])
    monkeypatch.setattr(c, "_pick_lowest", lambda captured, page: 700.0)
    monkeypatch.setattr(c, "_bag_fc_from_captured", lambda captured: "")
    monkeypatch.setattr(c, "_sleep", lambda: None)
    monkeypatch.setattr(c, "_dump_xhr", lambda captured, name: None)
    rows = c.fetch("乌鲁木齐", "上海", ["2026-10-15"])
    assert rows and rows[0].flight_no == "CZ6993"


# ---- webui 三端接线（源码钉，trendGo/trendHoliday 同款透传形态） ----

def test_webui_trendbiz_whitelist_passthrough():
    """/api/state 汇聚白名单原样透传 trendBiz（trendGo 同款 f.get
    形态，原样透传不做整形）。"""
    import webui
    src = webui_full_src()
    assert '"trendBiz": f.get("trendBiz")' in src
    assert webui  # import 级验证（三.3）


def test_webui_trendbiz_render_gate():
    """渲染门：改期窗口柱图 title 附高档舱注（「公务￥X」词面，
    biz 日期映射与 hol 同构）+ CSV「改期公务」列对称「改期最低」。"""
    src = webui_full_src()
    assert 'f.trendBiz||[]' in src           # tgrowHtml biz 映射构造
    assert '公务￥' in src                    # 柱 title 附注词面
    assert '改期公务' in src                  # CSV 表头列


# ---- merged from tests/test_r805ar_field_health_app.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "data", "prices.db")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "field_health_rows.json")


def _route_with_app():
    if not os.path.isfile(DB):
        return None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"),
                               uri=True)
        try:
            row = conn.execute(
                "SELECT from_city, to_city, depart_date FROM flight_prices "
                "WHERE platform LIKE 'app%' AND extra!='' "
                "GROUP BY 1,2,3 ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        # CI/并行用例可能刚建了一个空/半建库：无表=无样本，走固定样本。
        return None
    return row


def _fixture_db():
    """用真实样本行重建最小 flight_prices 表（干净克隆的判据来源）。"""
    data = json.load(io.open(FIXTURE, encoding="utf-8"))
    path = os.path.join(tempfile.mkdtemp(prefix="r805ar_"), "prices.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE flight_prices (platform TEXT, from_city TEXT, "
            "to_city TEXT, depart_date TEXT, extra TEXT, fetched_at TEXT)")
        conn.executemany(
            "INSERT INTO flight_prices (platform, from_city, to_city, "
            "depart_date, extra, fetched_at) VALUES (?,?,?,?,?,?)",
            [(r["platform"], r["from_city"], r["to_city"],
              r["depart_date"], r["extra"], r["fetched_at"])
             for r in data["rows"]])
        conn.commit()
    finally:
        conn.close()
    return tuple(data["meta"]["route"]), path


def _sample():
    """(route, db)：本机生产库优先，缺失时用固定样本建临时库。"""
    route = _route_with_app()
    if route:
        return tuple(route), DB
    return _fixture_db()


def test_field_health_audits_app_channels():
    (fc, tc, date), db = _sample()
    assert fc and tc and date, "样本航线不完整"

    import webui
    # 用城市码直接调用（_probe_city_code 需要完整 cfg；这里绕过解析）
    # ——`_srx_health` 的城市解析在真实请求里已由上游完成。
    from core.citydata import CODE_NAME
    frm = CODE_NAME.get(fc, fc)
    to = CODE_NAME.get(tc, tc)
    out = webui._srx_health(frm, to, date, db=db)
    chans = {c["key"]: c for c in out.get("channels") or []}
    assert chans, "审计结果为空，判据失去锚点"

    app_rows = [c for c in chans.values() if str(c["key"]).startswith("app")]
    assert app_rows, (
        "该航线/日期明明有 App 渠道数据（%s→%s %s），审计结果里却没有"
        " App 渠道——字段覆盖率从不被检查：%s"
        % (fc, tc, date, list(chans)))
    for c in app_rows:
        assert int(c["rows"]) > 0, (
            "%s 有数据但审计读成 0 行：%s" % (c["key"], c))
        assert not str(c["name"]).startswith("app_"), (
            "%s 的名字是裸 id，应显示中文名：%r" % (c["key"], c["name"]))
        # 有分母才谈得上「覆盖率」
        rates = [v.get("rate") for v in (c.get("fields") or {}).values()
                 if v.get("rate") is not None]
        assert rates, "%s 的字段率全是 None（没有分母）" % c["key"]


def test_browser_channels_still_audited():
    """扩展覆盖面不能把原来的五家挤掉。"""
    (fc, tc, date), db = _sample()
    import webui
    from core.citydata import CODE_NAME
    out = webui._srx_health(CODE_NAME.get(fc, fc), CODE_NAME.get(tc, tc),
                            date, db=db)
    keys = {c["key"] for c in out.get("channels") or []}
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert p in keys, "浏览器渠道 %s 从审计里消失了" % p


def test_fixture_alone_audits_app_and_browser_channels():
    """干净克隆没有生产库：固定样本重建的表也必须过同一套判据。"""
    (fc, tc, date), db = _fixture_db()
    assert db != DB, "本用例必须走固定样本，不能回落到生产库"
    import webui
    from core.citydata import CODE_NAME
    out = webui._srx_health(CODE_NAME.get(fc, fc), CODE_NAME.get(tc, tc),
                            date, db=db)
    chans = {c["key"]: c for c in out.get("channels") or []}
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert p in chans, "浏览器渠道 %s 从审计里消失了" % p
    apps = [c for c in chans.values() if str(c["key"]).startswith("app")]
    assert apps, "固定样本里有 App 行，审计却没有 App 渠道"
    for c in apps:
        assert int(c["rows"]) > 0, c
        assert not str(c["name"]).startswith("app_"), c


# ---- merged from tests/test_v15104_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- fliggy 日历邻日最低价：trendGo 同协议归一（qunar goFTrend /
#      tongcheng pc[] 同族，消费端 webui 改期胶囊现成） ----

def test_fliggy_cal_points_protocol():
    # JS 采集器原始返回 [[YYYY-MM-DD,价],…] → 协议形态 [["MM-DD",价],…]
    raw = [["2026-10-03", 930], ["2026-10-04", 1190], ["2026-10-06", 3070]]
    assert FliggyCrawler._parse_cal_points(raw) == [
        ["10-03", 930], ["10-04", 1190], ["10-06", 3070]]


def test_fliggy_cal_points_guards():
    # 逐点校验宁缺勿错（同 qunar _parse_trend_go）：日期形不正/价越界
    # （价带 100-50000）/非数值，坏点逐点弃；全坏与非 list 输入→None
    raw = [["2026-10-03", 930], ["bad", 100], ["2026-10-04", 99],
           ["2026-10-05", 60000], ["2026-10-07", "abc"], [None, 500]]
    assert FliggyCrawler._parse_cal_points(raw) == [["10-03", 930]]
    assert FliggyCrawler._parse_cal_points([["bad", 1]]) is None
    assert FliggyCrawler._parse_cal_points([]) is None
    assert FliggyCrawler._parse_cal_points(None) is None
    assert FliggyCrawler._parse_cal_points("x") is None


_FLIGGY_TXT = ("MU8369\n19:55\n01:25 第2天\n¥2522\n订票\n\n"
               "9C6927\n06:40\n11:55\n¥900\n订票")


def test_fliggy_trendgo_attached_to_min_row():
    # 日历 7 点挂当轮最低价行（qunar/tongcheng 同律「仅挂当轮最低价
    # 行」——逐行重复=extra 膨胀）；高价行不挂
    fs = FliggyCrawler._parse_pc_text(
        _FLIGGY_TXT, "2026-10-06",
        cal_pts=[["10-03", 930], ["10-09", 900]])
    lo = min(fs, key=lambda f: f["price"])
    assert lo["trendGo"] == [["10-03", 930], ["10-09", 900]]
    hi = max(fs, key=lambda f: f["price"])
    assert "trendGo" not in hi


def test_fliggy_trendgo_absent_without_cal():
    # 无日历数据（页面异形/采集失败）不落键——行 schema 与既有轮全等
    fs = FliggyCrawler._parse_pc_text(_FLIGGY_TXT, "2026-10-06")
    assert fs and all("trendGo" not in f for f in fs)


# ---- qunar 中转二段出发日期 transGoDate ----

def _pc_trans_sample(tgd):
    s = json.loads(_PC_BASE)
    row = s["data"]["flights"][0]
    row["transCity"] = "兰州"
    b1 = {"depTime": "08:00", "arrTime": "11:00", "date": "2026-10-04",
          "depTerminal": "", "arrTerminal": "T2",
          "depAirport": "天山", "arrAirport": "地窝堡"}
    if tgd is not None:
        b1["transCityDepDate"] = tgd
    row["binfo1"] = b1
    row["binfo2"] = {"depTime": "15:30", "arrTime": "18:00",
                     "arrDate": "2026-10-05"}
    return json.dumps(s)


_PC_BASE = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "FM9223/FM9224", "minPrice": "2472", "transCity": "",
         "extparams": {},
         "binfo": {"airCode": "FM9223", "shortName": "上航",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-10-04", "arrDate": "2026-10-05"}}]}})


def test_qunar_pc_trans_go_date_cross_day():
    # 跨天中转二段起飞日（binfo1.transCityDepDate，WA 调研 23/23 在场）
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample("2026-10-05"), "2026-10-04")
    assert fl and fl[0]["transGoDate"] == "2026-10-05"


def test_qunar_pc_trans_go_date_guards():
    # 同日（无增量不落，同 transDepTerminal 纪律）/早于出发日（不合理）/坏格式
    fl = QunarCrawler._parse_pc_flights(
        _pc_trans_sample("2026-10-04"), "2026-10-04")
    assert fl and "transGoDate" not in fl[0]
    fl2 = QunarCrawler._parse_pc_flights(
        _pc_trans_sample("2026-10-03"), "2026-10-04")
    assert fl2 and "transGoDate" not in fl2[0]
    fl3 = QunarCrawler._parse_pc_flights(_pc_trans_sample("10-05"), "2026-10-04")
    assert fl3 and "transGoDate" not in fl3[0]
    # 直飞行（无中转）即使报文带键也不落——键语义=中转二段
    s = json.loads(_PC_BASE)
    s["data"]["flights"][0]["binfo1"] = {
        "depTime": "08:00", "arrTime": "11:00", "date": "2026-10-04",
        "transCityDepDate": "2026-10-05"}
    fl4 = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl4 and "transGoDate" not in fl4[0]


def test_qunar_h5_trans_go_date_both_extparams_shapes():
    # H5 源 extparams.transGoDate（JSON 串/dict 双形态，_stopflight 同律）
    row = {"code": "GS7587", "price": 800, "minPrice": 800,
           "transCity": "石家庄",
           "binfo1": {"depTime": "14:30", "arrTime": "00:20",
                      "depDate": "2026-10-06", "arrDate": "2026-10-07"},
           "binfo2": {"depTime": "06:05", "arrTime": "07:55"}}
    ep_dict = dict(row, extparams={"transGoDate": "2026-10-07"})
    fl = QunarCrawler._extract_flights_obj([ep_dict])
    assert fl and fl[0]["transGoDate"] == "2026-10-07"
    ep_str = dict(row, extparams=json.dumps({"transGoDate": "2026-10-07"}))
    fl2 = QunarCrawler._extract_flights_obj([ep_str])
    assert fl2 and fl2[0]["transGoDate"] == "2026-10-07"
    # 同日不落
    ep_same = dict(row, extparams={"transGoDate": "2026-10-06"})
    fl3 = QunarCrawler._extract_flights_obj([ep_same])
    assert fl3 and "transGoDate" not in fl3[0]


# ---- tuniu prate 空串占位卫生改（无值不落键同族律） ----

_TUINU_OFFER = {
    "airline": "厦航", "flight_no": "MF2356", "depart_time": "08:25",
    "arrive_time": "13:55", "price": 1500, "dep_date": "2026-10-06",
    "arr_date": "2026-10-06", "flight_time": 330, "cabin": "经济舱",
    "layover": "", "craftTypeName": "波音737-800", "mealName": "点心",
    "onTimeRate": "96", "stopPoints": [], "labels": "宽体机",
    "planeSize": "大型机", "depAirport": "天山机场", "arrAirport": "虹桥机场",
    "cabinCode": "D", "shareCarrier": "上航",
}


def test_tuniu_prate_real_value_still_set():
    fs = TuniuCrawler._offers_to_flights([dict(_TUINU_OFFER)])
    assert fs[0]["prate"] == "96"


def test_tuniu_prate_placeholder_and_empty_not_set():
    # 渠道「20%」占位（_prate 置空）与无值空串均不落键——
    # 生产 20.2% 行 prate='' 空串常态化（WC 观测），同族 avgDelay/
    # discount 无值不落键律收口
    o = dict(_TUINU_OFFER, onTimeRate="20")
    assert "prate" not in TuniuCrawler._offers_to_flights([o])[0]
    o2 = dict(_TUINU_OFFER, onTimeRate="")
    assert "prate" not in TuniuCrawler._offers_to_flights([o2])[0]
    o3 = dict(_TUINU_OFFER, onTimeRate=None)
    assert "prate" not in TuniuCrawler._offers_to_flights([o3])[0]


# ---- webui 白名单与渲染门（源码钉：字符串在场锚；行为面归 uitest） ----

def test_webui_trans_go_date_whitelist_and_gate():
    import webui
    src = webui_full_src()
    assert '"transGoDate": (f.get("transGoDate") or "").strip(),' in src
    # 渲染门：二段行携带日期形态（MM-DD 由 JS slice 产出）——
    # 钉门卫开关字面（任意提及即过=锚定力弱）
    assert "(f.lay2dep||f.transGoDate)" in src


# ---- merged from tests/test_v15106_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15106")
_CT = CtripCrawler({}, _LOG)


# ---- N2 qunar：H5 labels 白名单追加春秋绿翼会员专享 ----

def test_qunar_h5_greenwing_label_whitelisted():
    """「春秋绿翼会员专享丨超惠飞」全词入白名单：H5 主路径时代
    绿翼资格价不再断供（PC 软拒期间该词唯一入口）。"""
    f = {"listLabel": {"priceBottomLabels": [
        {"text": "春秋绿翼会员专享丨超惠飞"}]}}
    out = QunarCrawler._h5_labels_of(f, {})
    assert "春秋绿翼会员专享丨超惠飞" in out


def test_qunar_h5_greenwing_with_ordinary_labels():
    """绿翼词与普通白名单词同列表：两词并出、词序保持。"""
    f = {"listLabel": {"priceBottomLabels": [
        {"text": "宠物友好"},
        {"text": "春秋绿翼会员专享丨超惠飞"}]}}
    out = QunarCrawler._h5_labels_of(f, {})
    assert "宠物友好" in out
    assert "春秋绿翼会员专享丨超惠飞" in out


def test_qunar_h5_price_churn_word_not_whitelisted():
    """「XX会员专享￥99」带价 churn 词不入（全词匹配防子串误入）。"""
    f = {"listLabel": {"priceBottomLabels": [
        {"text": "会员专享￥99"}]}}
    assert QunarCrawler._h5_labels_of(f, {}) == ""
    # 真实近失形态：白名单词「春秋绿翼会员专享丨超惠飞」的航司前缀
    # 带价变体（生产 dump 实锤 churn 词面）——词干/剥价前缀类收编
    # 变异（如取「丨」前词干做包含或前缀匹配）会被此断言打红
    f2 = {"listLabel": {"priceBottomLabels": [
        {"text": "春秋绿翼会员专享￥99"}]}}
    assert QunarCrawler._h5_labels_of(f2, {}) == ""


# ---- N1 ctrip：nt=3 LimitedCardType → agePolicy「限卡支付」 ----

def _ctrip_seg(dd, ad, flgno="MU5633"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_limited_card_type():
    """nt=3 逗号串含 LimitedCardType：agePolicy=「限卡支付」——
    限指定卡类型支付的资格价，误购支付失败出不了票。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3,
                             "notecnt": "LockPrice,LimitedCardType"}]}
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg(
        "2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        "policyinfo": [_ctrip_policy(price=2410, ci=ci)]})
    assert r["agePolicy"] == "限卡支付"


def test_ctrip_limited_card_type_alone():
    """分元素形态（单 notecnt 即该词）：同收。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3, "notecnt": "LimitedCardType"}]}
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg(
        "2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        "policyinfo": [_ctrip_policy(price=1200, ci=ci)]})
    assert r["agePolicy"] == "限卡支付"


# ---- tongcheng：中转行 lay2dep（第二段起飞时刻） ----

def _tc_fp(ss_extra=None):
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05", "aat": "T3", "dac": "URC",
           "aac": "YZY"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30", "dat": "T5", "dac": "YZY",
           "aac": "PVG"}]
    if ss_extra is not None:
        ss = ss_extra
    return {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
            "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}


def _tc_rows(fp):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows
    return rows[0]


def test_tongcheng_transfer_lay2dep():
    """ss[1].dt 段级真值 → lay2dep=「18:20」（HH:MM）：
    「第二段什么时候再飞」，与已采 layover（停多久）互补。"""
    r = _tc_rows(_tc_fp())
    assert r["lay2dep"] == "18:20"


def test_tongcheng_transfer_lay2dep_seconds_form():
    """dt 带秒尾巴（"2026-10-05 18:20:00" 形态）：切片后仍 18:20。"""
    fp = _tc_fp()
    fp["ss"][1]["dt"] = "2026-10-05 18:20:00"
    assert _tc_rows(fp)["lay2dep"] == "18:20"


def test_tongcheng_transfer_lay2dep_bad_shape_dropped():
    """dt 缺失/非时刻形：不落键（宁缺勿错）。"""
    fp = _tc_fp()
    del fp["ss"][1]["dt"]
    assert "lay2dep" not in _tc_rows(fp)
    fp2 = _tc_fp()
    fp2["ss"][1]["dt"] = "不合格"
    assert "lay2dep" not in _tc_rows(fp2)


# ---- 呈现词面钉（title 帮助文案与新词同步，防静默漂移） ----

def test_webui_agepolicy_title_mentions_card_type():
    """agePolicy ⚠ 徽标 title 词面覆盖「指定卡类型」：
    限卡支付资格价入 agePolicy 族后帮助文案同步。"""
    import webui
    assert "指定卡类型" in webui.PAGE


def test_webui_fltbtn_title_carries_legend():
    """≤540 图例隐藏后语义并入 fltBtn title：三档关键词在场。"""
    import webui
    assert "档位图例" in webui.PAGE
    assert "深绿=真达标" in webui.PAGE
    assert "琥珀=擦边" in webui.PAGE


# ---- merged from tests/test_v15109_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- iata2 航司二字码守卫（iata3 同款，qunar/tuniu 跨渠道统一键） ----

def test_iata2_guard():
    assert iata2("MU") == "MU"
    assert iata2("3U") == "3U"
    # 小写/三位/空/非字母数字一律挡（宁缺勿错）
    assert iata2("mu") == ""
    assert iata2("MUU") == ""
    assert iata2("") == ""
    assert iata2(None) == ""
    assert iata2("M1") == "M1"


# ---- qunar PC：distance / airlineCode / shareAirline ----

def _pc_sample(binfo_extra=None, codeshare=False):
    b1 = {"airCode": "FM9223", "shortName": "上航", "shortCarrier": "FM",
          "depTime": "19:55", "arrTime": "01:25",
          "date": "2026-10-04", "arrDate": "2026-10-05",
          "distance": "3649"}
    if binfo_extra:
        b1.update(binfo_extra)
    row = {"code": "FM9223", "minPrice": "2472", "transCity": "",
           "extparams": {}, "binfo": b1}
    if codeshare:
        row["code"] = "FM9223"
        b1["codeShare"] = True
        b1["mainCarrier"] = "FM9224"
        b1["mainCarrierShortName"] = "上航"
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [row]}})


def test_qunar_pc_distance_and_airline_code():
    fl = QunarCrawler._parse_pc_flights(_pc_sample(), "2026-10-04")
    assert fl and fl[0]["distance"] == 3649          # int 协议
    assert fl[0]["airlineCode"] == "FM"


def test_qunar_pc_distance_guards():
    # "0"/负数/非数字不落键（数值协议无值不落键律，同 avgDelay）
    for bad in ("0", "-5", "abc", ""):
        fl = QunarCrawler._parse_pc_flights(
            _pc_sample({"distance": bad}), "2026-10-04")
        assert fl and "distance" not in fl[0], bad
    # 键缺席同口径
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"distance": None}), "2026-10-04")
    assert fl and "distance" not in fl[0]


def test_qunar_pc_airline_code_guard():
    # 非二字码形态（小写/超长）守卫落空串（str 协议同 depAirportCode）
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"shortCarrier": "mu"}), "2026-10-04")
    assert fl and fl[0]["airlineCode"] == ""
    fl2 = QunarCrawler._parse_pc_flights(
        _pc_sample({"shortCarrier": "MUU"}), "2026-10-04")
    assert fl2 and fl2[0]["airlineCode"] == ""


def test_qunar_pc_share_airline_gate():
    # 共享承运航司名：与 shareCarrier 同门（codeShare + mainCarrier≠airCode）
    fl = QunarCrawler._parse_pc_flights(_pc_sample(codeshare=True),
                                        "2026-10-04")
    assert fl and fl[0]["shareAirline"] == "上航"
    assert fl[0]["shareCarrier"] == "FM9224"
    # 非共享行：shareAirline 无值不落键（r239 空串落键收口），
    # shareCarrier 同门仍空串直落（留观）
    fl2 = QunarCrawler._parse_pc_flights(_pc_sample(), "2026-10-04")
    assert (fl2 and "shareAirline" not in fl2[0]
            and "shareCarrier" not in fl2[0])


# ---- tuniu：airlineCode / stdFare（同 breakdown 配对） ----

def _tuniu_raw(breakdowns, airline_iata="MU"):
    """breakdowns: [(baseFare, bcTax, discount)]，每个元组一条
    flightPriceList（各自 fareBreakdownList 单 ADT 条目）。"""
    fpl = [
        {"fareBreakdownList": [
            {"baseFare": bf, "psgType": "ADT",
             **({"bcTaxExclusiveFare": bc} if bc is not None else {}),
             **({"discount": d} if d else {})}],
         "priceJourneyCabinList": [
             {"priceFlightCabinList": [{"cabinTypeName": "经济舱"}]}]}
        for bf, bc, d in breakdowns]
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": fpl}
    flight_list = {
        "MU8370#2026-10-06#URC#SHA": {
            "airlineCompany": "东航", "airlineIataCode": airline_iata,
            "departureTime": "20:20", "arrivalTime": "01:15",
            "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
            "flightTime": "295"}}
    return {"data": {"fareList": [fare], "flightList": flight_list}}


def test_tuniu_airline_code_offer_to_row():
    offers = TuniuCrawler._parse_offers(_tuniu_raw([(3600, 2900, "7.7折")]))
    assert offers and offers[0]["airlineCode"] == "MU"
    rows = TuniuCrawler._offers_to_flights(offers)
    # 决策字段必须随 offer 透传（两次在案的教训，逐行断言防再犯）
    assert rows and rows[0]["airlineCode"] == "MU"
    # 守卫：非二字码落空串
    bad = TuniuCrawler._parse_offers(
        _tuniu_raw([(3600, 2900, "")], airline_iata="muu"))
    assert bad and bad[0]["airlineCode"] == ""


def test_tuniu_std_fare_paired_with_selected_adt():
    # stdFare 必须与所选最低 ADT 价同一 breakdown（跨政策错配先例）：
    # 两政策各带 bcTax，最低价 2871 的公布运价 2900 随行
    offers = TuniuCrawler._parse_offers(
        _tuniu_raw([(2871, 2900, "6.2折"), (3000, 3100, "5.9折")]))
    assert offers[0]["price"] == 2871
    assert offers[0]["stdFare"] == 2900
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and rows[0]["stdFare"] == 2900


def test_tuniu_std_fare_guards():
    # -1/0 占位不落键（调研实证 ADT 负值/零占位 44%）
    for bad in (-1, 0):
        offers = TuniuCrawler._parse_offers(
            _tuniu_raw([(2871, bad, "6.2折")]))
        assert offers and "stdFare" not in offers[0], bad
    # 键缺席同口径
    offers = TuniuCrawler._parse_offers(
        _tuniu_raw([(2871, None, "6.2折")]))
    assert offers and "stdFare" not in offers[0]
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and "stdFare" not in rows[0]


# ---- _propagate_fields：物理属性列表扩展（airlineCode/distance/
#      shareAirline 同航班全渠道同值可补；stdFare 是报价属性不补） ----

def test_propagate_physical_fields():
    from core.alerter import Alerter
    base = {"code": "MU8370", "depDate": "2026-10-06",
            "depTime": "20:20", "arrTime": "01:15",
            "arrDate": "2026-10-07", "price": 2200}
    full = dict(base, _platform="qunar", airlineCode="MU", distance=3649,
                shareAirline="东航")
    blank = dict(base, _platform="ctrip")
    Alerter._propagate_fields([full, blank])
    assert blank["airlineCode"] == "MU"
    assert blank["distance"] == 3649
    assert blank["shareAirline"] == "东航"
    # 值冲突不补（宁缺勿错，与 cabin 同律）：两个不同非空值在场时
    # 第三行保持空（单值在场会按机制正常补——传播的语义就是「组内
    # 恰一个非空值才补」）
    conflict = dict(base, _platform="tuniu", airlineCode="CZ")
    other = dict(base, _platform="qunar", airlineCode="MU")
    blank2 = dict(base, _platform="fliggy")
    Alerter._propagate_fields([conflict, other, blank2])
    assert "airlineCode" not in blank2


# ---- webui 三端：透传白名单 + 渲染门/CSV（源码钉，行为面归 uitest） ----

def test_webui_payload_and_gates_pins():
    import webui
    src = webui_full_src()
    # 透传白名单（载荷协议四键）
    assert '"airlineCode": (f.get("airlineCode") or "").strip().upper(),' in src
    assert '"shareAirline": (f.get("shareAirline") or "").strip(),' in src
    assert '"distance": _int_or_none(f.get("distance")),' in src
    assert '"stdFare": _num_or_none(f.get("stdFare")),' in src
    # 渲染门：共享承运名+号组合（有名列合成，无名单独号）
    assert "f.shareAirline?f.shareAirline+f.shareCarrier:f.shareCarrier" in src
    # CSV 列：航程/航司码/公布运价/实际承运
    assert "航程" in src and "航司码" in src
    assert "公布运价" in src and "实际承运" in src


def test_webui_audit_fixes_pins():
    """WebUI 审计三修源码钉（行为面归 uitest/探针）：
    P2-1 比价链锚 nowrap（防锚内折行价与 ↗ 分离）/
    P2-2 弹层底注三入口各回设（pvFoot id + 三处 textContent）/
    Minor-1 读数档位后缀与环标图例逐字同形（●真达标）。"""
    import webui
    src = webui_full_src()
    # P2-1：锚本体 nowrap（td 折行放开规则的残留面）
    assert "#ftable tr.xrow td a.vw{white-space:nowrap}" in src
    # P2-2：底注入口化（id + 三入口显式回设——静态初始值是假单源）
    assert 'id="pvFoot"' in src
    assert "轮日志为原文直读" in src
    assert "推送历史本地存档回放" in src
    assert "$('pvFoot').innerHTML='本地近似渲染" in src
    # Minor-1：读数后缀 ●真达标（曾 🎯 与图例 ● 同档三字面）
    assert "q===2?' ●真达标'" in src


def test_dingtalk_at_tail_space_preserved(monkeypatch):
    """@手机号 段尾随空格是钉钉 @ 高亮的组成部分（alerter 三处有意
    追加「@xxx 」带尾空格）；rstrip() 曾把它连同尾空段一并吞掉（实发
    历史 09-29 起 @ 段失空格，推送审校 P1-1）——只剥尾部换行，
    有意尾随空格必须存活。"""
    import logging
    import core.notifier as N
    cap = {}
    monkeypatch.setattr(N, "_append_push_history",
                        lambda t, d, ok, ch="serverchan", img=None,
                        errcode=None: cap.update(desp=d))

    class _Resp:
        status_code = 200
        text = '{"errcode":0,"errmsg":"ok"}'

        def json(self):
            return {"errcode": 0}

    monkeypatch.setattr(N.httpx, "post", lambda *a, **kw: _Resp())
    n = N.DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=x",
        logging.getLogger("t"))
    n.send("t", "正文\n\n@13800138000 ")
    # r318 防指纹时刻行契约：send 出站正文尾部追加 ⏰ HH:MM（钉钉
    # 机器人正文模糊查重，恒定正文被应答 -1 但照投）——@ 段尾随
    # 空格仍须存活（@ 高亮组成部分，rstrip 只剥换行），只是不再位于
    # desp 末尾（其后跟时刻行）
    assert "正文\n\n@13800138000 \n\n⏰ " in cap["desp"], \
        "尾随空格被吞（@ 高亮意图回退）"
    # v162 契约不回退：尾空段仍剥（图片行后「\n\n」尾随空段）
    n.send("t2", "图片行\n\n![x](https://a/b.png)\n\n")
    assert cap["desp"].startswith("图片行\n\n![x](https://a/b.png)")


# ---- merged from tests/test_v15115_fields.py ----

# 生产 dump 逐字实证形态（tuniu_raw_2026-10-06.json CA8564 行）
_SP = {"airPortCode": "XNN", "airPortName": "曹家堡机场",
       "arrivalTime": "2026-10-06 19:20:00", "cityCode": "XNN",
       "cityName": "西宁", "departrueTime": "2026-10-06 20:05:00",
       "duration": "45"}

_OFFER = {
    "airline": "厦航", "flight_no": "MF2356", "depart_time": "08:25",
    "arrive_time": "13:55", "price": 1500, "dep_date": "2026-10-06",
    "arr_date": "2026-10-06", "flight_time": 330, "cabin": "经济舱",
    "layover": "", "craftTypeName": "波音737-800", "mealName": "点心",
    "onTimeRate": "96", "stopPoints": [_SP], "labels": "",
    "planeSize": "大型机", "depAirport": "天山机场", "arrAirport": "虹桥机场",
    "cabinCode": "D", "shareCarrier": "",
}


def test_stop_window_single_leg():
    assert _stop_window([_SP]) == "19:20-20:05"


def test_stop_window_multi_legs_joined():
    sp2 = dict(_SP, arrivalTime="2026-10-06 21:10:00",
               departrueTime="2026-10-06 21:55:00")
    assert _stop_window([_SP, sp2]) == "19:20-20:05/21:10-21:55"


def test_stop_window_partial_missing_pair_skipped():
    # 单段缺任一时刻 → 该段不成对（宁缺勿错），余段照出
    half = dict(_SP, departrueTime=None)
    assert _stop_window([half, _SP]) == "19:20-20:05"


def test_stop_window_empty_and_dirty_input():
    assert _stop_window([]) == ""
    assert _stop_window(None) == ""
    assert _stop_window(["x", 7, {}]) == ""
    # 脏时刻（无 HH:MM 可提）不成对
    dirty = dict(_SP, arrivalTime="TBD", departrueTime="")
    assert _stop_window([dirty]) == ""


def test_offers_row_carries_stopwin():
    fs = TuniuCrawler._offers_to_flights([dict(_OFFER)])
    assert fs[0]["stopWin"] == "19:20-20:05"


def test_offers_row_without_stops_keeps_empty_key():
    # 无值不落键（r241 残留族收口）：无经停行 stopWin/stopCitys/
    # stopTime 整族缺席（有值照落见上例 19:20-20:05）
    o = dict(_OFFER, stopPoints=[])
    row = TuniuCrawler._offers_to_flights([o])[0]
    assert "stopWin" not in row and "stopCitys" not in row
    assert "stopTime" not in row


# ---- webui 三端透传（源码钉：载荷出口与消费词面在场；行为面归 uitest） ----

def test_webui_stopwin_payload_and_gate():
    import webui
    src = webui_full_src()
    # Python 载荷两处出口（KPI brief + 明细行，与 stopTimeT 同位同构）
    assert src.count('"stopWin": (f.get("stopWin") or "").strip(),') == 2
    # 前端消费：brief 与明细 stoptag 括注 + CSV 经停列
    assert "brief.stopWin" in src
    assert "f.stopWin" in src


# ---- merged from tests/test_v1554_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- qunar H5 labels 层级修复（背书真值在 binfo 层，顶层恒占位） ----

def test_qunar_h5_labels_binfo_notice_takes_priority():
    f = {"transNotice": "转",
         "listLabel": {"priceBottomLabels": [{"text": "出票后2小时内错购退票"}]}}
    info = {"transNotice": "华夏联程"}
    out = QunarCrawler._h5_labels_of(f, info)
    assert "华夏联程" in out
    assert "出票后2小时内错购退票" in out


def test_qunar_h5_labels_placeholder_ting_excluded():
    # 「停」（经停标记，与 stopFlight 冗余）与「转」同为占位不落
    f = {"transNotice": "停"}
    assert QunarCrawler._h5_labels_of(f, {"transNotice": "停"}) == ""


def test_qunar_h5_labels_top_level_fallback():
    # binfo 层无 transNotice 时顶层兜底（旧链路兼容）
    f = {"transNotice": "华夏联程"}
    assert QunarCrawler._h5_labels_of(f, {}) == "华夏联程"


# ---- qunar H5 中转行 arrTerminal 语义修正 + transDepTerminal ----

_H5_TRANS = {
    "code": "GS7587", "price": 800, "minPrice": 800,
    "crossDayDesc": "+1天", "transCity": "石家庄", "transTime": "17时25分",
    "binfo1": {"depTime": "14:30", "arrTime": "00:20",
               "depDate": "2026-10-06", "arrDate": "2026-10-07",
               "codeShare": False,
               "depTerminal": "", "arrTerminal": "T2",
               "transInfo": {
                   "transCity": "石家庄", "transTime": "5h45m",
                   "firstArrInfo": {"airport": "正定", "terminal": "T2"},
                   "secondDepInfo": {"airport": "正定", "terminal": "T2",
                                     "time": "06:05"},
                   "secondArrInfo": {"airport": "虹桥", "terminal": "T1",
                                     "time": "07:55"}}},
}


def test_qunar_h5_transfer_arr_terminal_whole_journey():
    # binfo1.arrTerminal=T2（中转楼）须被 secondArrInfo.terminal=T1（整体
    # 到达楼）覆盖——与 arrTime 的整体口径对齐（漏网键）
    raw = json.dumps({"ret": True, "data": json.dumps(
        {"flights": [_H5_TRANS]})}
    )
    fl = QunarCrawler._parse_response_flights(raw)
    assert len(fl) == 1
    assert fl[0]["arrTerminal"] == "T1"
    assert fl[0]["arrAirport"] == "虹桥"


def test_qunar_h5_trans_dep_terminal_same_building_not_set():
    # secondDepInfo 与 firstArrInfo 同楼=无换乘增量，不落（宁缺勿错，
    # 无值不落键：无增量时键整体缺席非空串占位）
    raw = json.dumps({"ret": True, "data": json.dumps(
        {"flights": [_H5_TRANS]})}
    )
    fl = QunarCrawler._parse_response_flights(raw)
    assert "transDepTerminal" not in fl[0]


def test_qunar_h5_trans_dep_terminal_diff_building():
    h = json.loads(json.dumps(_H5_TRANS))
    h["binfo1"]["transInfo"]["secondDepInfo"]["terminal"] = "T5"
    raw = json.dumps({"ret": True, "data": json.dumps({"flights": [h]})})
    fl = QunarCrawler._parse_response_flights(raw)
    assert fl[0]["transDepTerminal"] == "正定T5"


# ---- qunar PC 复活预案（报文键在场而解析器未读的补读） ----

_PC_SAMPLE = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "FM9223", "minPrice": "2472", "transCity": "",
         "extparams": {"childPrice": 0, "infantPrice": None,
                       "refundChangeRule": '{"returnFee":0,"changeFee":0}'},
         "binfo": {"airCode": "FM9223", "shortName": "上航",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-10-04", "arrDate": "2026-10-05",
                   "flightTime": "5h30m",
                   "depTerminal": "", "arrTerminal": "T2",
                   "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥机场",
                   "planeFullType": "空客330(大)",
                   "piaoShao": True, "piaoShaoDesc": "票少",
                   "codeShare": True, "mainCarrier": "FM9224",
                   "pTrip": True, "pTripNote": "航变免费改、20Kg免费行李"}},
    ]}})


def test_qunar_pc_terminal_and_airport_keys():
    fl = QunarCrawler._parse_pc_flights(_PC_SAMPLE, "2026-10-04")
    f = fl[0]
    assert "depTerminal" not in f         # 出发侧无值不落键（恒空键卫生律）
    assert f["arrTerminal"] == "T2"
    assert f["depAirport"] == "乌鲁木齐天山"
    assert f["arrAirport"] == "虹桥机场"


def test_qunar_pc_plane_size_and_sources():
    fl = QunarCrawler._parse_pc_flights(_PC_SAMPLE, "2026-10-04")
    f = fl[0]
    assert f["planeSize"] == "大型机"        # 「空客330(大)」括号体量
    assert f["fewTicket"] == "票少"          # piaoShaoDesc 真键换源
    assert f["shareCarrier"] == "FM9224"     # mainCarrier 真键换源
    assert f["ptripNote"] == "航变免费改、20Kg免费行李"
    assert f["refundChange"] == '{"returnFee":0,"changeFee":0}'
    assert "childPrice" not in f             # 0=未报价占位不落


def test_qunar_pc_plane_size_placeholder_not_set():
    # 「机型未定/其他机型/737-800」无体量形态不落（宁缺勿错）
    s = json.loads(_PC_SAMPLE)
    s["data"]["flights"][0]["binfo"]["planeFullType"] = "机型未定"
    fl = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert "planeSize" not in fl[0]


def test_qunar_pc_share_carrier_self_flight_guard():
    # 自飞防呆：mainCarrier 与本班 airCode 完全同号不落；
    # 同航司不同号（FM9223 营销/FM9224 执飞）是真共享保留
    s = json.loads(_PC_SAMPLE)
    b = s["data"]["flights"][0]["binfo"]
    b["airCode"] = "FM9223"
    b["mainCarrier"] = "FM9223"
    fl = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert "shareCarrier" not in fl[0]
    b["mainCarrier"] = "FM9224"
    fl2 = QunarCrawler._parse_pc_flights(json.dumps(s), "2026-10-04")
    assert fl2[0]["shareCarrier"] == "FM9224"


# ---- tuniu：labels 透传漏键修复（宽体机空转根因）+ 新键 ----

_TUINU_OFFER = {
    "airline": "厦航", "flight_no": "MF2356", "depart_time": "08:25",
    "arrive_time": "13:55", "price": 1500, "dep_date": "2026-10-06",
    "arr_date": "2026-10-06", "flight_time": 330, "cabin": "经济舱",
    "layover": "", "craftTypeName": "波音737-800", "mealName": "点心",
    "onTimeRate": "96", "stopPoints": [], "labels": "宽体机",
    "planeSize": "大型机", "depAirport": "天山机场", "arrAirport": "虹桥机场",
    "cabinCode": "D", "shareCarrier": "上航",
}


def test_tuniu_labels_passthrough_fix():
    # offer 层算好 labels 但 _offers_to_flights 白名单漏带，
    # DB 实锤全库 labels 键存在率 0%（宽体机功能空转根因）
    fs = TuniuCrawler._offers_to_flights([dict(_TUINU_OFFER)])
    assert fs[0]["labels"] == "宽体机"
    assert fs[0]["planeSize"] == "大型机"
    assert fs[0]["depAirport"] == "天山机场"
    assert fs[0]["arrAirport"] == "虹桥机场"
    assert fs[0]["cabinCode"] == "D"
    assert fs[0]["shareCarrier"] == "上航"


def test_tuniu_cabin_code_multi_cabin_guard():
    # 舱位代码随选中价政策聚合（r222）：选中政策内多码不落（宁缺勿
    # 错），单码落值——ctrip 舱位配对纪律先例
    multi = [{"fareBreakdownList": [{"baseFare": 1500, "psgType": "ADT"}],
              "priceJourneyCabinList": [{"priceFlightCabinList": [
                  {"cabinCode": "Y"}, {"cabinCode": "B"}]}]}]
    assert TuniuCrawler._adt_fare(multi)[5] == ""
    single = [{"fareBreakdownList": [{"baseFare": 1500, "psgType": "ADT"}],
               "priceJourneyCabinList": [{"priceFlightCabinList": [
                   {"cabinCode": "M"}]}]}]
    assert TuniuCrawler._adt_fare(single)[5] == "M"


# ---- tongcheng：机场简称 / clct 白名单 / 共享双守卫 / afn 体量 ----

def _tc_flight(**over):
    f = {"fn": "GS7587", "dt": "2026-10-06 09:30:00",
         "at": "2026-10-06 14:05:00", "asn": "天津", "td": "4h35m",
         "afn": "空客320(中)", "dasn": "天山", "aasn": "虹桥",
         "dat": "", "aat": "T2", "icsf": True, "sfd": "flightId_CZ6993",
         "lps": [{"atp": "800", "brs": [{"al": 9}],
                  "pts": [{"td": "6.8折经济舱"}],
                  "clct": [{"tt": 1, "td": "大机型"},
                           {"tt": 2, "td": "到达准点率97%"},
                           {"tt": 3, "td": "座椅较宽"}]}]}
    f.update(over)
    return json.dumps({"success": True, "data": {"fl": [f]}})


def test_tongcheng_airport_and_labels():
    fs = TongchengCrawler._extract_flights(_tc_flight())
    f = fs[0]
    assert f["depAirport"] == "天山"
    assert f["arrAirport"] == "虹桥"
    assert f["labels"] == "大机型·座椅较宽"    # tt=2 准点率冗余不采
    assert f["planeSize"] == "中型机"           # afn 括号体量
    assert f["plane"] == "空客320"              # 原有清洗不受影响


def test_tongcheng_share_carrier_double_guard():
    # icsf=True 且 sfd 非自飞同号才落（剥 flightId_ 前缀）
    fs = TongchengCrawler._extract_flights(_tc_flight())
    assert fs[0]["shareCarrier"] == "CZ6993"
    # icsf=False 但 sfd 有值=假值不落（dump 实证 27 行）
    fs2 = TongchengCrawler._extract_flights(_tc_flight(icsf=False))
    assert "shareCarrier" not in fs2[0]
    # 自飞挂自身 id（完全同号 GS7587→GS7587）不落
    fs3 = TongchengCrawler._extract_flights(_tc_flight(fn="CZ6993",
                                                       sfd="flightId_CZ6993"))
    assert "shareCarrier" not in fs3[0]
    # 同航司不同号是真共享勿误杀（fn=CZ6993 营销 → CZ6990 执飞）
    fs4 = TongchengCrawler._extract_flights(_tc_flight(fn="CZ6993",
                                                       sfd="flightId_CZ6990"))
    assert fs4[0]["shareCarrier"] == "CZ6990"


# ---- ctrip：机场三字码 + aset 层行李三态（走真实解析入口） ----

def _ctrip_item(aset_words, transfer=True):
    seg = {"basinfo": {"flgno": "GS7587" if transfer else "MU5533"},
           "dateinfo": {"ddate": "2026-10-06 09:30:00",
                        "adate": "2026-10-06 14:05:00"},
           "dportinfo": {"city": "URC", "aport": "URC", "bsname": ""},
           "aportinfo": {"city": "SHA", "aport": "SHA", "bsname": "T2"}}
    return {"mutilstn": [seg] if not transfer else [seg, dict(seg)],
            "policyinfo": [{"tprice": 800, "quantity": 5}],
            "aset": [{"tagarea": [{"tagcnt": w} for w in aset_words]}]}


def _ctrip_parse(item):
    return CtripCrawler._extract_ctrip_flights(
        object.__new__(CtripCrawler), json.dumps({"fltitem": [item]}))


def test_ctrip_transfer_baggage_recheck_from_aset():
    # 「行李代转运」=明确不直挂真值（transferBaggage 第三态）
    fs = _ctrip_parse(_ctrip_item(["行李代转运"]))
    assert len(fs) == 1 and fs[0]["transCity"]
    assert fs[0]["transferBaggage"] == "recheck"


def test_ctrip_transfer_baggage_direct_from_aset():
    # 「联程值机，行李直挂」=item 层直挂第二来源（政策级无信号时生效）
    fs = _ctrip_parse(_ctrip_item(["联程值机，行李直挂"]))
    assert fs[0]["transferBaggage"] == "direct"


def test_ctrip_transfer_baggage_direct_transfer_not_set_on_direct():
    # 行李词是中转行专属信号：直飞行 is_transfer 门不落
    fs = _ctrip_parse(_ctrip_item(["行李代转运", "联程值机，行李直挂"],
                                  transfer=False))
    assert len(fs) == 1 and not fs[0].get("transCity")
    assert "transferBaggage" not in fs[0]


def test_ctrip_airport_codes_landed():
    # 机场三字码（dportinfo/aportinfo.aport）入门； 起经
    # AIRPORT_NAME_CN 归一为机场短名（与 qunar/tuniu 中文名同形）
    fs = _ctrip_parse(_ctrip_item([], transfer=False))
    assert fs[0]["depAirport"] == "乌鲁木齐天山"
    assert fs[0]["arrAirport"] == "虹桥"


# ---- fliggy：planeSize 行首体量词 + 机场名 ----

def test_fliggy_plane_size_and_airport_name():
    txt = ("国航CA8564\n14:30\n18:45\n虹桥国际机场T2\n大型机 789 经停\n"
           "¥960 4.5折\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert fs[0]["planeSize"] == "大型机"
    assert fs[0]["plane"] == "789"
    assert fs[0]["depAirport"] == "虹桥国际机场"
    assert fs[0]["depTerminal"] == "T2"


# ---- webui 轮聚类 600s 收口（与曲线 _rounds 同序） ----

def _row(ts):
    from datetime import datetime
    return {"fetched_at": ts}


def test_cluster_round_rows_600s_aligns_curve():
    # 契约=倒序输入（最新在前）、时间戳=DB 形态空格分隔：
    # 8 分钟断口在 600s 阈值下仍同轮（300s 旧值会把 10:08/10:00 切出
    # 「本轮」=图有列无）
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:08:00",
            "2026-09-20 10:00:00"]
    out = _cluster_round_rows([_row(t) for t in rows], gap_s=600)
    assert len(out) == 3


def test_cluster_round_rows_splits_across_rounds():
    # 真轮界（倒序 14/8 分钟断口）：只有最新轮（10:16）保留
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:02:00",
            "2026-09-20 09:54:00"]
    out = _cluster_round_rows([_row(t) for t in rows], gap_s=600)
    assert len(out) == 1
    assert out[0]["fetched_at"] == "2026-09-20 10:16:00"


def test_cluster_round_rows_scan_marker_keeps_slow_routes():
    """同一轮多航线跨 8-10 分钟完成：有轮次标记时不按 420s 断口切开。

    生产实证 13:37 NRT 与 13:45 SIN 相隔 466s，旧断口把 NRT 标补位，
    IJ004 ￥972 真达标被压成 stale。标记 start=13:34 时三行都属本轮。
    """
    rows = ["2026-10-22 13:45:35", "2026-10-22 13:37:49",
            "2026-10-22 13:34:02", "2026-10-22 13:23:10"]
    out = _cluster_round_rows([_row(t) for t in rows],
                              scan_start="2026-10-22 13:34:00")
    assert [r["fetched_at"] for r in out] == rows[:3]
    # 标记缺失时回退断口，旧轮不会被合并
    out2 = _cluster_round_rows([_row(t) for t in rows])
    assert len(out2) == 1
    # /api/state 传入的是 sqlite3.Row（无 .get）：标记分支必须只下标访问
    class _RowLike:
        def __init__(self, ts):
            self._d = {"fetched_at": ts}

        def __getitem__(self, k):
            return self._d[k]
    out3 = _cluster_round_rows([_RowLike(t) for t in rows],
                               scan_start="2026-10-22 13:34:00")
    assert len(out3) == 3


# ---- notifier：恰达线剥注 + 装饰符剥离 ----

def test_alert_body_strips_broken_line_word():
    # 恰达线（diff==0 非达标）「行情破线」与 🟩 转写「行情价 」同句
    # 双词面——转写前剥注同律（推送审校）
    body = _alert_body("🎯真达标 直飞 ￥1900 线￥1900 行情破线")
    assert "行情破线" not in body


def test_alert_body_strips_decorative_emoji():
    body = _alert_body(
        "#### 📋 明细总表 实绿=真达标·描绿=破线\n\n✈️ 乌→上 走势↑ ↓\n\n💡 建议")
    for w in ("📋", "✈", "💡"):
        assert w not in body
    assert "涨" in body and "跌" in body   # 箭头转可读词


def test_notify_page_raw_conversion_complete():
    # NOTIFY_PAGE 改 raw 消 DeprecationWarning——守护「半截转换」回归
    # （源码 `\\s` 在 raw 下浏览器实收字面「反斜杠+s」，
    # 档位方块行静默跌落普通段落）
    import webui
    assert r"/\\s/g" not in webui.NOTIFY_PAGE    # 不许残留双反斜杠形态
    assert "/\\s/g" in webui.NOTIFY_PAGE         # 解码态单反斜杠（空白类）
    assert "match(/\\(" in webui.NOTIFY_PAGE     # 图片链接正则解码态 \(


def test_ptrip_note_not_orphan():
    # 爬虫落键、渲染门必须下发（防 PC 复活当日静默丢失）
    src = webui_full_src()
    assert '"ptripNote"' in src


def test_trend_ring_candle_and_watch_honesty_pins():
    # 长窗日桶 flag=0 不得按价格回退成真达标；K线用日桶真 OHLC；
    # 关注台 stale/paused/expired 不得显示已达标。
    src = webui_full_src()
    assert "const TIER=(q,v,tv)=>q===2?2:(q===1?1:0);" in src
    assert 'pts = lambda rows: [[r["day"], r["lo"], 0, r["open"]' in src
    assert "const ohlc=g.every(x=>x.length>=6);" in src
    assert "const eligible=!!(w.active&&w.inScope&&q&&!q.stale);" in src
    assert "if(!q||q.stale||!w.active||!w.inScope)return '';" in src

# ---- __main__ from tests/test_v1554_fields.py ----

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
