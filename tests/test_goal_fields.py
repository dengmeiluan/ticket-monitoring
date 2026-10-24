# -*- coding: utf-8 -*-
"""goal 轮数据层案件：FLG-1 fliggy 机型行第 4 形态、TN-1 tuniu 中转行。"""
from crawlers.fliggy import FliggyCrawler


# ---- FLG-1：机型行第 4 形态「其他机型」 ----
def test_fliggy_other_craft_prefix():
    """机型行第 4 形态「其他机型 31A 有餐食」（2026-10-20 dump 4/86 行，
    EU2776/EU2779 中转块首段；历史 4 dump 0 处=新生形态）：旧锚
    ^[大中小]型机 不识别 → 首段机型 31A 与「有餐食」词丢失、labels
    「首段31A」段位消歧词空转。新形态：plane 取型号码；「其他机型」
    无体量信号不落 planeSize（值域=大中小型机，体量筛选不被污染）；
    meal 管道照常接通；[大中小] 主形态零变化。"""
    txt = ("成都航EU2776\n\n其他机型 31A 有餐食\n\n19:55\n\n01:25\n\n"
           "美兰国际机场T1\n\n上海虹桥\n\n¥2522\n订票")
    f = FliggyCrawler._parse_pc_text(txt, "2026-10-20")[0]
    assert f.get("plane") == "31A", f
    assert "planeSize" not in f, f
    assert f.get("meal") == "有餐食", f
    # 无餐食态同构
    txt2 = ("成都航EU2779\n\n其他机型 31A 无餐食\n\n19:55\n\n01:25\n\n"
            "美兰国际机场T1\n\n上海虹桥\n\n¥2522\n订票")
    f2 = FliggyCrawler._parse_pc_text(txt2, "2026-10-20")[0]
    assert f2.get("plane") == "31A" and f2.get("meal") == "无餐食", f2
    # 主形态不受影响（防回归锚）
    txt3 = ("东航MU8369\n\n中型机 737 有餐食\n\n19:55\n\n01:25\n\n"
            "浦东T1\n\n乌鲁木齐\n\n¥2522\n订票")
    f3 = FliggyCrawler._parse_pc_text(txt3, "2026-10-20")[0]
    assert f3.get("plane") == "737" and f3.get("planeSize") == "中型机", f3


# ---- TN-1：tuniu 中转行拼装（flightOptionList 段链结构化真值） ----
def _tuniu_transfer_raw():
    """按 10-06 URC dump 实证形态构造（HU6354-HU7613，段链
    「号#日期#起#终」+ transferPoints 分钟真值）。"""
    return {"data": {
        "fareList": [
            {"flightOptions": [{"flightNos": "HU6354-HU7613"}],
             "flightPriceList": [{"fareBreakdownList": [
                 {"psgType": "ADT", "baseFare": 1580}]}]},
            {"flightOptions": [{"flightNos": "FM9223"}],
             "flightPriceList": [{"fareBreakdownList": [
                 {"psgType": "ADT", "baseFare": 2472}]}]},
        ],
        "flightList": {
            "HU6354#2026-10-06#URC#BJS": {
                "departureTime": "09:55", "arrivalTime": "13:25",
                "departureDate": "2026-10-06", "arrivalDate": "2026-10-06",
                "airlineCompany": "海南航空", "airlineIataCode": "HU",
                "craftTypeName": "737", "mealName": "点心餐",
                "dTerminal": "T3", "dPortName": "天山机场",
                "dPortIataCode": "URC"},
            "HU7613#2026-10-07#BJS#SHA": {
                "departureTime": "08:30", "arrivalTime": "10:55",
                "departureDate": "2026-10-07", "arrivalDate": "2026-10-07",
                "airlineCompany": "海南航空", "airlineIataCode": "HU",
                "craftTypeName": "789", "mealName": "正餐",
                "aTerminal": "T2", "aPortName": "浦东机场",
                "aPortIataCode": "SHA"},
            "FM9223": {
                "departureTime": "19:55", "arrivalTime": "01:25",
                "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
                "airlineCompany": "上海航空", "airlineIataCode": "FM",
                "craftTypeName": "737", "mealName": ""}},
        "flightOptionList": {
            "HU6354-HU7613": {
                "departureDate": "2026-10-06",
                "flightItems": [
                    {"flightNo": "HU6354#2026-10-06#URC#BJS"},
                    {"flightNo": "HU7613#2026-10-07#BJS#SHA"}],
                "totalTransfer": "2",
                "transferPoints": [
                    {"cityIataCode": "BJS", "cityName": "北京",
                     "transferTime": "340"}],
                "transitService": []}}}}


def test_tuniu_transfer_offer_assembled():
    """TN-1：tuniu 中转行整体缺口收口（五渠道唯一零中转行渠道）。
    flightOptionList 段链 + transferPoints 结构化真值在场时，多段
    offer 拼装中转行而非整行跳过：整体起终=段链日期×段时刻（多段
    offer 地雷的「整体起终不可得」前提不复存在）、transCity=真实
    城市名（跨渠道协议：渲染「经北京」；旧死分支「中转」标记词
    退役）、layover=分钟+layoverSrc=transInfo 豁免族、机型/餐食随
    末段（fliggy 主槽=二段段位协议）、全程时长带日期维度重建。"""
    from crawlers.tuniu import TuniuCrawler
    raw = _tuniu_transfer_raw()
    offers = TuniuCrawler._parse_offers(raw)
    nos = [o["flight_no"] for o in offers]
    assert nos == ["HU6354-HU7613", "FM9223"], nos
    tr = offers[0]
    # 整体起终（旧缺陷=首段口径 13:25/当日）
    assert tr["depart_time"] == "09:55" and tr["arrive_time"] == "10:55", tr
    assert tr["dep_date"] == "2026-10-06" and tr["arr_date"] == "2026-10-07", tr
    # 中转结构化真值
    assert tr["transCity"] == "北京", tr
    assert tr["layover"] == 340 and tr["layoverSrc"] == "transInfo", tr
    # 段位协议：机型/餐食随末段
    assert tr["craftTypeName"] == "789" and tr["mealName"] == "正餐", tr
    # 全程时长（日期维度重建：1440+655-595=1500 分钟）
    assert tr["flight_time"] == "1500", tr
    assert tr["price"] == 1580.0, tr
    # 行级 schema（_offers_to_flights）：transCity 透传真城市名
    rows = TuniuCrawler._offers_to_flights(offers)
    row = rows[0]
    assert row["code"] == "HU6354/HU7613", row
    assert row["transCity"] == "北京", row
    assert row["layover"] == 340, row
    assert row["arrDate"] == "2026-10-07" and row["crossDayDesc"] == "+1天", row
    assert row["totalDuration"] == "25时0分", row
    # 直飞行对照不回归
    assert rows[1]["code"] == "FM9223" and "transCity" not in rows[1], rows[1]
    # normalize 层：layover 分钟派生 layoverT，transInfo 真值豁免守卫
    from core.flightnorm import normalize as _norm
    nf = _norm(row, "2026-10-06")
    assert nf.get("layoverT") == "5:40", nf


def test_tuniu_transfer_offer_guard_without_seglings():
    """宁缺勿错守卫：flightOptionList 缺该组合号、或段链项缺时刻
    detail 时，多段 offer 仍整行跳过（旧行为兜底，不造数据）。"""
    from crawlers.tuniu import TuniuCrawler
    raw = _tuniu_transfer_raw()
    del raw["data"]["flightOptionList"]["HU6354-HU7613"]["transferPoints"]
    assert [o["flight_no"] for o in TuniuCrawler._parse_offers(raw)] == ["FM9223"]
    raw2 = _tuniu_transfer_raw()
    raw2["data"]["flightList"] = {}          # 段 detail 全缺
    assert [o["flight_no"] for o in TuniuCrawler._parse_offers(raw2)] == ["FM9223"]


def test_tuniu_transfer_seg_detail_date_disambiguation():
    """Soldier Major-1：段 detail 按段链完整键精确优先（flightList
    同号多日期键并存时裸号前缀匹配按 dict 序取首个=A 段时刻来自
    另一日期班期的混装行）。段链键与 flightList 键同格式，精确键
    命中即根治；缺精确键回退裸号兜底（旧行为）。"""
    from crawlers.tuniu import TuniuCrawler
    raw = _tuniu_transfer_raw()
    # 同号 HU7613 两日期键并存：10-06 键重建插前（dict 序在前、
    # 到达 09:00）与段链所指 10-07（到达 10:55）——裸号前缀匹配
    # 按 dict 序会错取 10-06
    fl = raw["data"]["flightList"]
    raw["data"]["flightList"] = {
        "HU7613#2026-10-06#BJS#SHA": {
            "departureTime": "07:00", "arrivalTime": "09:00",
            "departureDate": "2026-10-06", "arrivalDate": "2026-10-06",
            "airlineCompany": "海南航空", "airlineIataCode": "HU",
            "craftTypeName": "73A", "mealName": "点心餐"},
        **fl}
    tr = TuniuCrawler._parse_offers(raw)[0]
    assert tr["arrive_time"] == "10:55", tr      # 精确键 10-07 时刻
    assert tr["craftTypeName"] == "789", tr      # 末段随精确键非 73A


def test_transfer_row_layover_src_passthrough():
    """Soldier Major-2：layoverSrc 随 layover 行级透传——offer 层
    transInfo 真值源标丢失则 flightnorm 假衔接豁免族对拼装行不可达
    （真值跨天长停留落 1440 倍数 ±15 击杀区被归零=该豁免要防的
    误杀形态）。"""
    from crawlers.tuniu import TuniuCrawler
    rows = TuniuCrawler._offers_to_flights(
        TuniuCrawler._parse_offers(_tuniu_transfer_raw()))
    assert rows[0].get("layover") == 340, rows[0]
    assert rows[0].get("layoverSrc") == "transInfo", rows[0]


# ---- P1-1：国际航线出链与爬虫取数路径同源 ----
def test_build_view_url_intl_same_source():
    """国际航线出链与爬虫取数路径同源：ctrip from=outer、qunar
    touch interlist、fliggy ie/ 国际壳、tuniu m2015 带参落地页；
    同程国际双端登录墙维持空串（宁缺勿错）。国内形态零变化锚。"""
    from core.models import Route
    from core.alerter import Alerter
    r = Route(from_code="SHA", from_name="上海", to_code="NRT",
              to_name="东京", dates=["2026-10-20"])
    # ctrip 国际（r360）：PC 列表是航班维度真源（H5 只出日历），
    # 出链与 batchSearch 取数同源；城市级码（NRT→TYO）与爬虫同参
    u = Alerter._build_view_url(None, r, "2026-10-20", "ctrip")
    assert "flights.ctrip.com/online/list/oneway-sha-tyo" in u, u
    assert "depdate=2026-10-20" in u, u
    # qunar 国际（R48c G1 同源收口）：touch interlist 同参+城市名链
    # （CITY_NAME→city_short_of）；国内 PC 壳零变化锚
    uq = Alerter._build_view_url(None, r, "2026-10-20", "qunar")
    assert "touch.qunar.com/ncs/page/interlist" in uq, uq
    assert "depCity=%E4%B8%8A%E6%B5%B7" in uq and "arrCity=%E4%B8%9C%E4%BA%AC" in uq, uq
    assert "goDate=2026-10-20" in uq, uq
    # ctrip 国内：from=inner 零变化锚
    r_dom = Route(from_code="SHA", from_name="上海", to_code="URC",
                  to_name="乌鲁木齐", dates=["2026-10-20"])
    u2 = Alerter._build_view_url(None, r_dom, "2026-10-20", "ctrip")
    assert "from=inner" in u2, u2
    # tuniu 国际：m2015 带参落地页（与 INTL_LIST_PG 同参）；国内不受影响
    ut_intl = Alerter._build_view_url(None, r, "2026-10-20", "tuniu")
    assert "m.tuniu.com/m2015/intlFlight/flight/list" in ut_intl, ut_intl
    assert "route=SHA-NRT" in ut_intl and "date=2026-10-20" in ut_intl, ut_intl
    u3 = Alerter._build_view_url(None, r_dom, "2026-10-20", "tuniu")
    assert "m.tuniu.com/flight/domestic" in u3, u3
    uq2 = Alerter._build_view_url(None, r_dom, "2026-10-20", "qunar")
    assert "m.flight.qunar.com/ncs/page/flightlist" in uq2, uq2
    # fliggy 国际（r326 A1 收口）：ie/ 国际壳+城市码；2026-10-23 原站
    # 复核旧 searchBy/arrDate 参数页 404，最小 crawler 同参页 200 且同航班可搜。
    uf = Alerter._build_view_url(None, r, "2026-10-20", "fliggy")
    assert "sijipiao.fliggy.com/ie/flight_search_result.htm" in uf, uf
    assert "depCity=SHA" in uf and "arrCity=TYO" in uf, uf
    assert "depDate=2026-10-20" in uf, uf
    assert "searchBy=" not in uf and "arrDate=" not in uf, uf
    # 同程国际：国际面独立前后端+列表双端登录墙（report_tongcheng.md
    # 实证）——按途牛先例宁缺链接（消费端剥壳只出文本）
    assert Alerter._build_view_url(None, r, "2026-10-20", "tongcheng") == ""
    # 两渠道国内零变化锚
    uf2 = Alerter._build_view_url(None, r_dom, "2026-10-20", "fliggy")
    assert "sjipiao.fliggy.com/flight_search_result.htm" in uf2, uf2
    ut = Alerter._build_view_url(None, r_dom, "2026-10-20", "tongcheng")
    assert "m.ly.com/ft/touch/book1" in ut, ut


# ---- P3-2：_fmt_brief 地板档对 6 位国际价超预算 ----
def test_fmt_brief_floor_scales_with_price_face():
    """地板 8≥价格词面 7.6 按国内 5 位价标定（￥50000 词面 7.625 恰
    满）；r325 国际带上界 200000 引入 6 位价域后未重标——￥199999
    词面 9 半角超 budget=8，消费点拼满前缀后整行最坏 41/40。地板
    预算下限改「价格词面实测宽与 8 取大」（标定值非常量律）。"""
    from core.alerter import Alerter, _disp_dw
    f = {"price": 199999, "name": "东航MU587", "depTime": "10:00",
         "arrTime": "15:50"}
    # 消费点按 _brief_floor 传预算：6 位价地板档 9 半角恰好落位
    # （budget=8 直调时词面 9>8 物理不可满足，地板恒落位律的备案域）
    assert _disp_dw(Alerter._fmt_brief(
        f, budget=Alerter._brief_floor(199999))) <= 9
    # 国内 5 位价形态零变化（地板 8 恰满锚）
    f5 = {"price": 50000, "name": "东航MU587", "depTime": "10:00",
          "arrTime": "15:50"}
    assert _disp_dw(Alerter._fmt_brief(f5, budget=8)) <= 8
    # 消费点地板下限单源
    assert Alerter._brief_floor(199999) == 9
    assert Alerter._brief_floor(50000) == 8
    # 整行形态（report 消费点拼满前缀）：渠道名截断基准随地板收紧，
    # 6 位价满前缀整行 ≤40（审计实证最坏 41/40 的构成=pre32+地板9）
    import report as _rep
    from core.alerter import _dw as _dw_a
    row6 = {"price": 199999, "name": "东航MU587", "depTime": "10:00",
            "arrTime": "15:50"}
    out = _rep._daily_market_fallback(
        {"ctrip": (199999, True)}, best_rows={"ctrip": row6})
    for ln in out.strip().split("\n"):
        assert _dw_a(ln) <= 40, (ln, _dw_a(ln))


# ---- P3-1：legacy 单航线 digest 尾部详情链接段落律 ----
def test_legacy_digest_jump_link_paragraph_break(monkeypatch):
    """legacy _push_digest 尾部「查看详情」链接单 \\n 收尾（全链唯一
    违例：钉钉 PC 不认单 \\n，图行与链接粘成一段）。段落律：拼接
    收尾一律段落级 \\n\\n。"""
    import logging
    from core.alerter import Alerter
    from core.models import Route

    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    sent = []

    def _route():
        return Route(from_code="SHA", from_name="上海", to_code="URC",
                     to_name="乌鲁木齐", dates=["2026-09-25"],
                     alert_direct=1900, alert_transfer=1700)

    def _sect(price):
        bd = {"price": price, "name": "MU8369", "depTime": "19:55",
              "arrTime": "01:25", "_platform": "qunar"}
        return [{"date": "2026-09-25", "best_direct": bd,
                 "best_transfer": None, "top_direct": [bd],
                 "top_transfer": [], "platform_mins": {"qunar": price},
                 "plat_top3": {"qunar": [bd]}, "seen_plats": ["qunar"]}]

    a = Alerter(logging.getLogger("tgoal"), notifier=FakeN(),
                storage=None, digest=True, user="t")
    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")
    monkeypatch.setattr(a, "_archive_notify", lambda t, d, **kw: "")
    monkeypatch.setattr(a, "_send_urgent",
                        lambda t, d, hits, launch="": True)
    a._push_digest(_route(), _sect(1750))
    assert sent, "达标轮主推丢失"
    for _t, _d in sent:
        ls = _d.split("\n")
        hits = [(k, ln) for k, ln in enumerate(ls) if "👉 在" in ln]
        assert hits, _d[-300:]
        for k, ln in hits:
            # 段落律：查看详情行与前一内容行之间必须有空行（split 后
            # 前元素=空串；行首形态=独占一行的段落）
            assert k == 0 or ls[k - 1] == "", (ls[k - 1], ln)


# ---- P2-1（推送审校）：日报图挂兜底空池归因 ----
def test_daily_top_fallback_empty_pool_attributed():
    """日报图挂兜底对空池整段 continue——图挂日中转被窗口/衔接滤除
    时读者失去「为何没有中转」解释位（图内空态与告警兜底都有归因
    行，日报兜底独缺=能力不对称）。空池改出组头+归因行，词面复用
    _group_empty_note/_transfer_empty_note 单源且行走 _fit_line
    守卫（r286 钉语义：双约束全形 ≈50 半角超限落主体档，短约束
    形态全形可达）；有行池零变化。"""
    import report as _rep
    # 短约束形态（调用点缺省档）：全形 35 半角可达
    out = _rep._daily_top_fallback([], [], lay_min=0, arrival_max="02:00")
    assert "直飞最优" in out and "中转最优" in out, out
    assert "暂无满足约束的班次（02:00 前到达）" in out, out
    # 直飞组全形 42 超限 → 主体档=note 剥括注「暂无数据」
    # （组头「直飞最优」承载段位，归因细节在 40 线下不可达）
    assert "\n\n暂无数据\n\n" in out, out
    # 双约束形态：全形 50 超限落主体档（约束细节先丢=档序律）
    out2 = _rep._daily_top_fallback([], [], lay_min=90,
                                    arrival_max="02:00")
    assert "暂无满足约束的班次" in out2, out2
    assert "衔接≥90" not in out2, out2
    # 双约束缺省档（渠道未回数）：全形 46 超限 → 主体=「暂无数据」
    # （单源派生：缺省形态错落约束词=误导读者找不存在的约束）
    out3 = _rep._daily_top_fallback([], [], lay_min=0, arrival_max="")
    assert "该轮渠道未回中转班次" not in out3, out3
    ls3 = [ln for ln in out3.split("\n\n") if ln.strip()]
    from core.alerter import _dw as _dw_a
    assert all(_dw_a(ln) <= 38 for ln in ls3), ls3   # r286 缓冲线同律
    # 默认参数向后兼容（旧 2 位置调用形态不炸）
    _rep._daily_top_fallback([], [])
