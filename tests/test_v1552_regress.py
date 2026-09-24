# -*- coding: utf-8 -*-
"""回归：渠道字段四批（途牛 prate=20 占位守卫、飞猪余票紧张、
qunar/ctrip 中转航站楼 transTerminal、ctrip 余票数 leftTickets/机龄精度/
Wi-Fi 结构化布尔/中转免费住宿）+ 推送侧 emoji 转写单源「真达标」词面 +
webui 样例词面/改期微图图例/CSV 双列钉死。夹具形态取自 debug/ dump
实证（10-05/10-06，调研A/调研D）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1552_regress.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


# ==================== 渠道字段四批 ====================

class TestTuniuPratePlaceholder:
    """途牛 onTimeRate=20 渠道占位默认值（调研D 全库实证：202/208 行
    =20、17/17 指纹跨渠道背离 ctrip 90-97、9 家航司同刻 20、「同响应
    多样性」方案 202/202 全含非 20 值被证伪）——恒 20 置空宁缺勿错。"""

    def test_placeholder_variants(self):
        from crawlers.tuniu import _prate
        assert _prate("20") == ""
        assert _prate("20%") == ""
        assert _prate(20) == ""
        assert _prate(" 20 ") == ""
        assert _prate("94") == "94"
        assert _prate("94%") == "94"
        assert _prate("96.67") == "96.67"
        assert _prate(None) == ""
        assert _prate("") == ""

    def test_offer_passthrough_sanitized(self):
        """守卫在 detail→offer 唯一透传点生效：入库 prate 读 offer 键，
        单一写点无旁路（调研D 核对:428→:509）。"""
        from crawlers.tuniu import TuniuCrawler
        detail = {"airlineCompany": "东航",
                  "departureTime": "20:20", "arrivalTime": "01:15",
                  "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
                  "flightTime": "295", "onTimeRate": "20%"}
        raw = {"data": {
            "fareList": [{"flightOptions": [{"flightNos": "MU8370"}],
                          "flightPriceList": [
                              {"fareBreakdownList": [
                                  {"baseFare": 3600, "psgType": "ADT"}]}]}],
            "flightList": {"MU8370#2026-10-06#URC#SHA": detail}}}
        offers = TuniuCrawler._parse_offers(raw)
        assert offers and offers[0].get("onTimeRate") == ""
        detail["onTimeRate"] = "97%"
        offers2 = TuniuCrawler._parse_offers(
            {"data": dict(raw["data"],
                          flightList={"MU8370#2026-10-06#URC#SHA": detail})})
        assert offers2 and offers2[0].get("onTimeRate") == "97"


class TestFliggyFewTicket:
    """飞猪 .less-tag 余票紧张行（10-05/06 dump：少量 20/「3张」等
    26/32 行在场，innerText 序列位于价格行后 ≤2 行）。"""

    def _parse(self, lines):
        from crawlers.fliggy import FliggyCrawler
        return FliggyCrawler._parse_pc_text("\n".join(lines), "2026-10-05")

    def test_few_ticket_after_price(self):
        rows = self._parse([
            "春秋9C8866", "中型机 321", "15:15", "19:05",
            "乌鲁木齐天山国际机场", "虹桥国际机场T2", "¥1180", "少量"])
        assert rows and rows[0]["fewTicket"] == "少量"

    def test_ticket_count_form(self):
        rows = self._parse([
            "东航MU5137", "中型机 737", "08:00", "11:30",
            "虹桥国际机场T1", "浦东国际机场T2", "¥2320", "3张"])
        assert rows and rows[0]["fewTicket"] == "3张"

    def test_not_stolen_far_from_price(self):
        # 行距锚：价格行 3 行外的同形短行不吸入（防页面其他模块）
        rows = self._parse([
            "春秋9C8866", "中型机 321", "15:15", "19:05",
            "乌鲁木齐天山国际机场", "虹桥国际机场T2", "¥1180",
            "经济舱", "温馨提示", "少量"])
        assert "fewTicket" not in rows[0]

    def test_ignored_without_price(self):
        # 无价格行（_price_i 缺失）不落键
        rows = self._parse(["少量"])
        assert rows == []


class TestQunarTransTerminal:
    """qunar 中转航站楼（二期）：transInfo.firstArrInfo 结构化
    真值（中转行 88% 有值），「咸阳T3」形态含机场名防同城多场歧义。"""

    def _row(self, trans_info):
        from crawlers.qunar import QunarCrawler
        # transInfo 真实挂 binfo1 层（爬虫 info = binfo or binfo1）
        b1 = {"depTime": "08:00", "arrTime": "11:00",
              "depDate": "2026-09-25", "arrDate": "2026-09-25"}
        if trans_info is not None:
            b1["transInfo"] = trans_info
        f = {"minPrice": 800, "code": "MU8369", "transCity": "西安",
             "binfo1": b1,
             "binfo2": {"depTime": "13:30", "arrTime": "17:20",
                        "depDate": "2026-09-25", "arrDate": "2026-09-25"}}
        rows = QunarCrawler._extract_flights_obj([f])
        return rows[0] if rows else {}

    def test_terminal_from_first_arr_info(self):
        r = self._row({"transTime": "5时50分",
                       "firstArrInfo": {"airport": "咸阳", "terminal": "T3"},
                       "secondDepInfo": {"time": "13:30"}})
        assert r["transTerminal"] == "咸阳T3"

    def test_missing_terminal_stays_empty(self):
        assert self._row({"transTime": "5时50分"})["transTerminal"] == ""
        assert self._row(None).get("transTerminal", "") == ""


class TestCtripNewFields:
    """ctrip 四项（10-05/06 dump）：leftTickets=最低价政策 quantity
    1-10；transTerminal=第二段 dportinfo（换乘出发侧）；机龄月成分折算
    小数年；Wi-Fi 结构化布尔优先；中转免费住宿入 labels。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        obj = {"fltitem": [item]}
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _ci(**over):
        ci = {"cgrd": 0, "prate": 96, "meal": "", "extendinfos": []}
        ci.update(over)
        return ci

    def _direct(self, quantity=3, ci=None):
        return {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                              "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                           "adate": "2026-10-05 11:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 1200, "quantity": quantity,
                                "classinfor": [ci or self._ci()]}]}

    def test_left_tickets_from_lowest_policy(self):
        rows = self._parse(self._direct(quantity=3))
        assert rows[0]["leftTickets"] == 3
        # 随最低价政策配对：贵政策余票多不误取
        it = self._direct(quantity=2)
        it["policyinfo"].append({"tprice": 1500, "quantity": 9,
                                 "classinfor": [self._ci()]})
        assert self._parse(it)[0]["leftTickets"] == 2

    def test_zero_quantity_policy_dropped(self):
        # quantity 0/缺 = 无票诱饵价：整政策剔除（既有过滤器，守卫不变）
        rows = self._parse(self._direct(quantity=0))
        assert rows == []

    def test_trans_terminal_from_second_segment(self):
        seg = lambda fn, dp, ap, dd, ad: {
            "basinfo": {"flgno": fn},
            "dateinfo": {"ddate": dd, "adate": ad},
            "dportinfo": dp, "aportinfo": ap}
        it = {"mutilstn": [
            seg("MU5137", {"city": "乌鲁木齐"},
                {"city": "西安", "bsname": "T5"},
                "2026-10-05 08:00:00", "2026-10-05 11:00:00"),
            seg("MU9900", {"city": "西安", "bsname": "西安T5"},
                {"city": "上海", "bsname": "T1"},
                "2026-10-05 14:00:00", "2026-10-05 17:00:00")],
            "policyinfo": [{"tprice": 1500, "quantity": 3,
                            "classinfor": [self._ci()]}]}
        rows = self._parse(it)
        assert rows[0]["transTerminal"] == "西安T5"
        # 直飞行不落中转航站楼
        assert self._parse(self._direct())[0]["transTerminal"] == ""

    def test_plane_age_month_precision(self):
        rows = self._parse(self._direct(ci=self._ci(extendinfos=[
            {"content": "机龄1年6个月"}])))
        assert rows[0]["planeAge"] == "1.5"
        rows = self._parse(self._direct(ci=self._ci(extendinfos=[
            {"content": "机龄5个月"}])))
        assert rows[0]["planeAge"] == "0.4"
        rows = self._parse(self._direct(ci=self._ci(extendinfos=[
            {"content": "机龄9年"}])))
        assert rows[0]["planeAge"] == "9"

    def test_wifi_structured_bool(self):
        # content 无「机上Wi-Fi」文本、结构化布尔为真 → 仍入 labels
        rows = self._parse(self._direct(ci=self._ci(wifi=True)))
        assert "机上Wi-Fi" in rows[0]["labels"]
        rows = self._parse(self._direct(ci=self._ci(wifi=False)))
        assert "机上Wi-Fi" not in rows[0]["labels"]

    def test_transfer_hotel_into_labels(self):
        it = self._direct()
        it["policyinfo"][0]["fnotelst"] = [
            {"notecnt": "航变免费退改|中转免费住宿"}]
        labels = self._parse(it)[0]["labels"]
        assert "中转免费住宿" in labels
        assert "航变免费退改" in labels


# ==================== 推送侧转写单源 ====================

class TestEmojiTierWords:
    """强提醒 emoji 转写单源 + 真达标词面：转写词与建议行
    同条消息并存，「达标/真达标」两词面曾打架（调研B）。"""

    def test_single_source_word_face(self):
        from core.notifier import _EMOJI_TIER_WORDS
        assert ("🎯", "真达标 ") in _EMOJI_TIER_WORDS
        assert ("🟩", "行情价 ") in _EMOJI_TIER_WORDS
        assert ("🟨", "擦边 ") in _EMOJI_TIER_WORDS

    def test_alert_body_transcribes_qual_word(self):
        from core.notifier import _alert_body
        body = _alert_body("🎯 直飞 ￥1468　线￥1500　低￥32\n\n"
                           "> 💡 直飞真达标 低￥32，建议出手")
        assert "真达标" in body and "直飞 ￥1468" in body
        assert "直飞真达标" in body
        assert "🎯" not in body


# ==================== webui 词面/结构钉死 ====================

class TestWebuiPinWords:
    """webui 源码级钉死（预览样例=教学面，词面错一字即误导解码；
    样例串若复活已撤的 🟦 超线仪表条即红）。样例串在
    Python 服务端 handler 而非 PAGE 内，故读模块源文件。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_sample_legend_and_suggest_line(self):
        src = self._src()
        assert src.count("🎯真达标 🟩破线 🟨擦边 超线") >= 2   # NDEMO/pushlog 样例
        assert "直飞真达标 低￥20，建议出手" in src
        assert "无标超线" not in src

    def test_removed_gauge_sample_gone(self):
        src = self._src()
        assert "🟦⬜" not in src          # 超线仪表条样例已下架
        assert "tgleg" in src             # 改期微图图例行在位
        assert "display:block;max-width:460px" in src   # tgbox 内联死代码修复

    def test_csv_extra_columns(self):
        src = self._src()
        assert "'孤低价','改期最低'" in src


# ==================== 哨兵白名单扩容 ====================

class TestSentinelNewFields:
    """哨兵扩容：ctrip|lft、qunar|ctrip|tterm、fliggy|few——
    新决策字段恒 0 命中=键死观测（同 tx→td 事故模式）。"""

    def _sent(self, monkeypatch, tmp_path, prices):
        from types import SimpleNamespace as _NS
        import main as _m
        monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
        monkeypatch.setattr(_m, "_ROW_HIST", {})
        _m._SENT_LAST.clear()
        _m._SENT_CNT.clear()
        seen = []

        class _L:
            def warning(self, *a, **k):
                seen.append(a)

        class _I:
            def info(self, *a, **k):
                pass

        rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
        _m._field_sentinel(rows, _L())
        return seen

    def test_healthy_rows_no_warning(self, monkeypatch, tmp_path):
        # 夹具带齐全部受观测字段的命中值——排他性断言：任何误报=白名单
        # 或门槛写错（死键测试同法）
        rows = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "prate": "96", "plane": "737",
                 "shareCarrier": "MU5700", "arrTerminal": "T1",
                 "avgDelay": 21, "layover": 90,
                 "leftTickets": 5,
                 "transCity": "西安", "transTerminal": "咸阳T3",
                 "fewTicket": "少量",
                 # 第七批受观测字段命中值（排他断言要求夹具
                 # 带齐全部白名单/比率字段——缺值=假键死红）；
                 # aptc 同律（fliggy 死键表不计，ctrip 须带值）；
                 # discount 同律（「全价」并入后恒有源）
                 "discount": "4.5折",
                 "planeSize": "中型机", "depAirport": "咸阳",
                 "depAirportCode": "URC", "arrAirportCode": "SHA",
                 "cabinCode": "Y", "bridgeRate": 80, "planeAge": "6.3"}
                for _ in range(30)]
        assert self._sent(monkeypatch, tmp_path,
                          [("ctrip", rows), ("fliggy", rows)]) == []

    def test_zero_hit_new_field_warns(self, monkeypatch, tmp_path):
        dead = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "transCity": "西安"}
                for _ in range(30)]
        seen = self._sent(monkeypatch, tmp_path, [("ctrip", dead)])
        flat = " ".join(str(a) for w in seen for a in w)
        assert "leftTickets" in flat
        assert "transTerminal" in flat
