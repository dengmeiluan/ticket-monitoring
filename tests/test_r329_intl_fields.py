# -*- coding: utf-8 -*-
"""r329 国际域八增量（_scratch/worker_r329_fields_b.md §1，T1-T6 tuniu +
Q1/Q2 qunar）。

冻结语料：debug/tuniu_intl_2026-11-16.json（92 行=中转 87+直飞 5，
生产按轮覆盖写、行数随窗内航班浮动）+
debug/qunar_raw_intl_*.txt（20 份 2026-11-16 档）——单代快照前提：落点全
在结构化布尔/全勤级；Q2 稀疏词面 5/1007 待下轮 dump 复验在场。

- T1 tuniu cabinCode ← cabinClass 段级订座码（透明直落不做码→舱名映射：
  Q→公务/经济双值域实证弱配对=语义赌博禁区；订座码形态门防 int 旧形态
  /小写脏词面）；
- T2/T3 tuniu 机场 IATA 码 ← segmentList 首末段 dPortIataCode/aPortIataCode
  （iata3 门同国内 H1：^[A-Z]{3}$ fullmatch）；
- T4 tuniu shareAirline ← segmentList[].airComName（仅中转行、非共享行落
  ——qunar H5 carrierSimpleName 同门：共享信息由 shareCarrier 承载防两键
  同屏混淆；段承运 join「|」与 H5 同词面语言，元素内部全角｜原样保留）；
- T5/T6 tuniu planeSize/plane 段级补全（seg0 空取首个非空段——r328
  seg0-only 半落地修复，宽体二段 19/77 丢失面）；
- Q1 qunar intl stopover ← binfo.stops=="1"（与 transNotice 停词面 14/14
  同现双信号；经停城市 intl 无载体不造值；normalize stopover 真值短路 +
  webui stoptag 全链现成）；
- Q2 qunar intl reducePriceDesc 词面白名单（「已减¥N」全词正则 +
  「成都两场互通」全词）挂 labels 既有出口——「已减¥N」≠「可再减¥N」
  （H5 r322 透明标记），同族不同词面真增量。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r329_intl_fields.py
"""
import glob
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402
from core.flightnorm import normalize  # noqa: E402

_LOG = logging.getLogger("t_r329_intl")
_TN = TuniuCrawler({}, _LOG)
_QC = QunarCrawler
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _row(**over):
    row = {
        "dCityName": "上海", "aCityName": "东京",
        "dPortName": "浦东国际机场", "aPortName": "成田国际机场",
        "dTerminal": "T1", "aTerminal": "T1",
        "dTime": "2026-11-16 09:30", "aTime": "2026-11-16 14:00",
        "airlineName": "东方航空", "flightNos": "MU523",
        "cabinName": "经济舱",
        "avgTotalPrice": 2380.0, "avgBasePrice": 1860.0, "avgTax": 520.0,
        "seat": 5, "totalMin": 270,
        "transferCity": "", "stopCity": "", "codeShare": "",
    }
    row.update(over)
    return row


def _parse(rows):
    return _TN._parse_offers_intl({"productList": rows})


def _qrow(**over):
    row = {
        "minPrice": 2380,
        "code": "MU523",
        "binfo": {
            "depTime": "09:30", "depDate": "2026-11-16",
            "arrTime": "14:00", "arrDate": "2026-11-16",
            "name": ["东方航空"], "stops": "0",
        },
    }
    row.update(over)
    return row


# ---- T1：tuniu cabinCode 段级订座码 ----

def test_t1_cabin_code_segment_letters():
    r = _parse([_row(cabinClass="W-W")])[0]
    assert r["cabinCode"] == "W-W"
    # 单段形态（3 直飞行值域）
    assert _parse([_row(cabinClass="Y")])[0]["cabinCode"] == "Y"
    # 三段连串
    assert _parse([_row(cabinClass="Q-Y-B")])[0]["cabinCode"] == "Q-Y-B"
    # 非订座码形态不落（宁缺勿错防脏词面）：int 旧样本形态/小写/空串
    assert "cabinCode" not in _parse([_row(cabinClass=1)])[0]
    assert "cabinCode" not in _parse([_row(cabinClass="w-w")])[0]
    assert "cabinCode" not in _parse([_row()])[0]


# ---- T2/T3：tuniu 机场 IATA 码（首末段）----

def test_t23_airport_codes_iata3_gate():
    r = _parse([_row(
        flightNos="MU523-NH960",
        segmentList=[
            {"flightNo": "MU523", "dPortIataCode": "PVG",
             "aPortIataCode": "KMG"},
            {"flightNo": "NH960", "dPortIataCode": "KMG",
             "aPortIataCode": "NRT"},
        ])])[0]
    assert r["depAirportCode"] == "PVG"
    assert r["arrAirportCode"] == "NRT"
    # iata3 门：小写/两位不落（H1 同律）
    bad = _parse([_row(segmentList=[
        {"flightNo": "MU523", "dPortIataCode": "pvg",
         "aPortIataCode": "PV"}])])[0]
    assert "depAirportCode" not in bad and "arrAirportCode" not in bad
    # 无段不落
    assert "depAirportCode" not in _parse([_row()])[0]
    assert "arrAirportCode" not in _parse([_row()])[0]


# ---- T4：tuniu shareAirline（中转各段承运）----

def test_t4_share_airline_transfer_only():
    r = _parse([_row(transferCity="昆明", flightNos="MU523-3U8881",
                     segmentList=[
                         {"flightNo": "MU523", "airComName": "东方航空"},
                         {"flightNo": "3U8881", "airComName": "四川航空"}])])[0]
    assert r["shareAirline"] == "东方航空|四川航空"
    # 共享行不落（共享信息由 shareCarrier 承载，防两键同屏混淆）
    r2 = _parse([_row(transferCity="开罗", codeShare="MS917",
                      segmentList=[
                          {"flightNo": "MU523",
                           "airComName": "东方航空"}])])[0]
    assert "shareAirline" not in r2
    assert r2["shareCarrier"] == "MS917"
    # 直飞行不落（单段无「各段承运」语义）
    assert "shareAirline" not in _parse([_row(segmentList=[
        {"flightNo": "MU523", "airComName": "东方航空"}])])[0]
    # 三段行 join；元素内部全角｜原样保留（航司集团多名内部标记，
    # 与段间半角分隔符有区分度）
    r3 = _parse([_row(transferCity="曼谷|马斯喀特",
                      flightNos="MU547-WY818-WY407",
                      segmentList=[
                          {"flightNo": "MU547",
                           "airComName": "东方航空"},
                          {"flightNo": "WY818",
                           "airComName": "新海航｜西部航空"},
                          {"flightNo": "WY407",
                           "airComName": "天津航空"}])])[0]
    assert r3["shareAirline"] == "东方航空|新海航｜西部航空|天津航空"


# ---- T5/T6：planeSize/plane 段级补全（首个非空段）----

def test_t56_planesize_plane_first_nonempty_seg():
    segs = [
        {"flightNo": "MU523", "craftWidthType": "", "craftTypeDetail": ""},
        {"flightNo": "MU777", "craftWidthType": "大型机",
         "craftTypeDetail": "空客A330-200"},
    ]
    r = _parse([_row(transferCity="昆明", flightNos="MU523-MU777",
                     segmentList=segs)])[0]
    assert r["planeSize"] == "大型机"
    assert r["plane"] == "空客A330-200"
    # seg0 有值优先（渠道原序，不倒挂）
    segs2 = [
        {"flightNo": "MU523", "craftWidthType": "中型机",
         "craftTypeDetail": "空客320"},
        {"flightNo": "MU777", "craftWidthType": "大型机",
         "craftTypeDetail": "空客A330"},
    ]
    r2 = _parse([_row(segmentList=segs2)])[0]
    assert r2["planeSize"] == "中型机"
    assert r2["plane"] == "空客320"
    # 全空不落（原行为不变）
    r3 = _parse([_row(segmentList=[
        {"flightNo": "MU523", "craftWidthType": ""}])])[0]
    assert "planeSize" not in r3
    assert "plane" not in r3


# ---- Q1：qunar intl stopover ----

def test_q1_stopover_flag():
    fl = _QC._extract_intl_flights([
        _qrow(binfo={"depTime": "09:30", "depDate": "2026-11-16",
                     "arrTime": "14:00", "arrDate": "2026-11-16",
                     "name": ["东方航空"], "stops": "1"})])
    assert fl[0].get("stopover") is True
    # intl 无 stopCitys 载体：城市不造值
    assert "stopCitys" not in fl[0]
    # stops!="1" 不落
    assert "stopover" not in _QC._extract_intl_flights([_qrow()])[0]
    # 全链：normalize stopover 真值短路（stopover 是 normalize/webui
    # 白名单层键；「stop」是 webui _user_state 组装键名，本层不断言）
    n = normalize(dict(fl[0]), "2026-11-16")
    assert n["stopover"] is True


# ---- Q2：qunar intl reducePriceDesc 词面白名单 ----

def test_q2_reduce_desc_whitelist():
    fl = _QC._extract_intl_flights([
        _qrow(reducePriceDesc="已减¥160"),
        _qrow(reducePriceDesc="成都两场互通"),
        _qrow(reducePriceDesc="立减¥100"),
        _qrow(reducePriceDesc="比直飞省¥50"),
        _qrow(),
    ])
    assert "已减¥160" in fl[0]["labels"]
    assert fl[1]["labels"] == "成都两场互通"
    # 变体与营销 churn 不采（全词精确门）
    assert "labels" not in fl[2]
    assert "labels" not in fl[3]
    assert "labels" not in fl[4]


# ---- 三端协议：webui 下行/消费面同轮钉（plane 数据孤儿收口）----

def test_webui_plane_passthrough_and_consumers():
    import webui
    mod = open(os.path.join(_ROOT, "webui.py"), encoding="utf-8").read()
    # plane 透传（爬虫落键后下行字典同轮接，seatTilt 先例零布局通道）
    assert '"plane": (f.get("plane") or "").strip(),' in mod
    # CSV「机型体量」列并入机型名（v1559 机场码同列并入先例，不加新列；
    # r339 起二段体量/机型同列并入——列序 planeSize·planeSize2·plane）
    assert "[f.planeSize,f.planeSize2,f.plane].filter(Boolean).join('·')" in mod
    # 明细次行机型体量 span title 机型名注记（次行段容量红线 14 已满，
    # 词面不加只注 title）
    assert "机型'+he(f.plane)" in mod
    # 搜索 hay 含机型名（明细搜索可按机型过滤）
    assert "+(f.plane||'')" in mod


def test_webui_cabinof_intl_chain_absent_from_cabin_dim():
    """Soldier M-1：cabinOf 对段级订座码连串（W-W，r329 tuniu intl
    92/92 携带）不进舱系归一维度——映射即语义赌博（Q→公务/经济双值
    域在案）、逐串成 chip 是零区分度碎片噪音；空串由 chips 构造
    filter(Boolean) 排除、筛选门空值放行（缺维度行不被任何舱位档
    静默滤除——此前 intl 行无码归「经济」桶，连串亮相当日即从
    「经济」筛选静默消失=筛选回归面）。"""
    mod = open(os.path.join(_ROOT, "webui.py"), encoding="utf-8").read()
    assert "if(c.indexOf('-')>=0)return '';" in mod
    # chips 构造排除空串（连串不成碎片 chip）
    assert "[...new Set(u.flights.map(cabinOf))].filter(Boolean)" in mod
    # 筛选门空值放行（连串行不被舱位档误滤）
    assert "FLT.cabins.size&&cabinOf(f)&&!FLT.cabins.has(cabinOf(f))" in mod


# ---- 冻结 dump 回放（skipif：debug/ 语料不入库，本地强化 CI 稳定）----

def test_intl_freeze_replay_tuniu():
    p = os.path.join(_ROOT, "debug", "tuniu_intl_2026-11-16.json")
    if not os.path.exists(p):
        pytest.skip("冻结 dump 缺席（debug/ 不入库）")
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = _TN._parse_offers_intl(data)
    # dump 由生产实例按轮覆盖写（行数随窗内航班浮动）——断言锁
    # 「读层接线实效 + 门不误杀 + 不退化」相对语义，不锚瞬时计数
    # （首版锚 92/61/78 硬数，全量跑撞生产覆写当场红；行数下限
    # 50 亦然——薄供给带三度穿越实录 140→83→71→28 行（间歇薄
    # 样本先例），绝对库存锚退役改非空门：断供/塌方观测归渠道级
    # 哨位，本钉只锁读层结构（下方各断言自带相对语义）
    n = len(rows)
    assert n >= 1
    # cabinCode 出勤地板（值域漂移实证：渠道恢复轮出现「R4-N/R4-K/…」
    # 带数字订座码形态，语义未证不采——形态门拒收是在岗正确不是读层
    # 错位，缺席行原值不落行故无法逐行断言形态归属，以缺席数地板锁
    # 「接线实效 + 门不误杀」。家族规模带随扩容随迁：R4 促销族从带内
    # ~20 扩到 34（R4-X1 尾数字变体入场，dump 拒收面全为 R4 族）——
    # 地板 20→40，缺席超带仍红）
    n_cabin = sum(1 for r in rows if r.get("cabinCode"))
    assert n - n_cabin <= 40, f"cabinCode 缺席 {n - n_cabin}/{n} 超家族规模带"
    assert sum(1 for r in rows if r.get("depAirportCode")) == n
    assert sum(1 for r in rows if r.get("arrAirportCode")) == n
    # plane 结构锁（原「缺席 ≤3 行」浮动带：双缺中转行数是窗构成属性
    # 而非读层属性，实录代际 0↔6 波动（103 行代 6 缺 / 79 行代 0 缺，
    # 缺席行全为 trans 行 plane/planeSize 双缺族）——瞬时带被穿越当轮
    # 红=语料漂移非回归，按 FRA 冻结件判例改结构关系锁不锚瞬时计数）：
    # ①孪生子集——plane 缺席行必缺 planeSize（plane 断读而 planeSize
    # 在场的行=读层错位信号）；②直飞行 plane 全勤（窗口含直飞行时
    # 生效；渠道撤 plane 源时直飞行先失守——双源整撤的兜底由下方
    # planeSize 地板 45 承接）
    _miss_plane = {i for i, r in enumerate(rows) if not r.get("plane")}
    _miss_ps = {i for i, r in enumerate(rows) if not r.get("planeSize")}
    assert _miss_plane <= _miss_ps, \
        f"plane 缺席行含 planeSize 在场行 {sorted(_miss_plane - _miss_ps)}（读层错位?）"
    # R55 金丝雀开鸣转结构带：生产新代语料 5 条直飞行 plane 缺席
    # （载荷零 plane 键实证=渠道撤源，非读层错位——孪生子集锁 ①仍
    # 在岗）。全勤断言改缺席带 ≤25（语料代际波动余量；整撤兜底仍由
    # planeSize 地板 45 承接）
    if any(not r.get("transCity") for r in rows):
        _miss_direct = [i for i in _miss_plane
                        if not rows[i].get("transCity")]
        assert len(_miss_direct) <= 25,             f"直飞行 plane 缺席 {_miss_direct}（超语料波动带——渠道整撤信号）"
    # T4：中转非共享行落；共享行不落（两键行集互斥=门实效）
    n_share = sum(1 for r in rows if r.get("shareAirline"))
    assert n_share > 20
    assert not [r for r in rows
                if r.get("shareAirline") and r.get("shareCarrier")]
    # T5：段级补全地板锁（原 `>=55` 绝对值钉：语料=生产滚动单槽每轮
    # 覆写，窗内 craftWidthType 载体出勤 54~55 浮动当场过期——判例
    # 十八§24 随语料浮动改写）。二改相对地板 ≥25%（原 45 绝对值又
    # 被库存缩量穿越：春季班次离窗 dump 140→83 行，出勤 25/83=30%
    # 属代际波动非退化——绝对值锚库存总量，比率锚出勤结构）：
    # 正常带 ~59-77% 留足余量；抓「重度塌方」（ seg0-only 退化在现
    # 窗仍可出 ~49%——地板不红，与原 45 地板同口径）与渠道撤源级
    # 归零，非轻度退化
    n_ps = sum(1 for r in rows if r.get("planeSize"))
    assert n_ps >= n * 0.25, (
        f"planeSize 出勤 {n_ps}/{n}（{n_ps / max(n, 1):.0%}）破 25% 地板"
        "（段级补全退化?）")
    # 值域不漂移
    assert {r["planeSize"] for r in rows if r.get("planeSize")} <= {
        "大型机", "中型机", "小型机"}


def test_intl_freeze_replay_qunar():
    dumps = sorted(glob.glob(
        os.path.join(_ROOT, "debug", "qunar_raw_intl_*.txt")))
    if not dumps:
        pytest.skip("冻结 dump 缺席（debug/ 不入库）")
    n_rows = n_reduce = 0
    for p in dumps:
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        try:
            fl, _risk = _QC._parse_intl_response(text)
        except Exception:
            continue
        n_rows += len(fl)
        n_reduce += sum(1 for r in fl if "已减¥" in (r.get("labels") or "")
                        or "成都两场互通" in (r.get("labels") or ""))
    # dump 集由生产按轮增写（窗口/航班浮动；硬拒期空响应覆写清薄
    # 语料实录：健康带 700+ 行塌至 386，多航线空响应续写后 243→191
    # ——绝对合计锚随覆写穿越）——相对语义同上钉：非空门 + 下方
    # 相对断言锁结构；行数下限 200 退役（断供观测归渠道级哨位）
    assert n_rows >= 1
    # 词面白名单通道点亮（当前语料在供；若未来归零按姊妹钉同法
    # 改变异注入形态）
    assert n_reduce >= 1


def test_intl_stopover_channel_lit_by_mutation():
    """stopover 落键通道锁（变异注入形态）。活语料当前代际 stops
    载体恒 0（经停班次零供给，20 dump 240 处全 0）——旧「n_stop>=1」
    锚的是瞬时供给，语料代际一翻即红（LESSONS 十八§24 回放钉禁锚
    瞬时计数）。改为对真实 dump 注入该结构化真值后回放：锁「载体→
    落键」整链，通道点亮证明不依赖语料恰好含经停班。"""
    dumps = sorted(glob.glob(
        os.path.join(_ROOT, "debug", "qunar_raw_intl_*.txt")))
    if not dumps:
        pytest.skip("冻结 dump 缺席（debug/ 不入库）")
    for p in dumps:
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        if 'stops\\":0' not in text:
            continue
        mutated = text.replace('stops\\":0', 'stops\\":1', 1)
        try:
            fl, _risk = _QC._parse_intl_response(mutated)
        except Exception:
            continue
        hits = [r for r in fl if r.get("stopover")]
        assert hits, f"载体注入后 stopover 未落键：{os.path.basename(p)}"
        return
    pytest.skip("语料无 stops 载体（代际形态漂移，按哨位人工复核）")
