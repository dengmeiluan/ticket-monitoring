# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v1552_regress.py
- tests/test_v197_regress.py
- tests/test_v198_regress.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import datetime as dt
import json
import logging
import os
import pytest
import re
import sqlite3
import sys


# ---- merged from tests/test_v1552_regress.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

    def test_missing_terminal_not_set(self):
        # 无值不落键（恒空键卫生律，transTerminal 对收口同律）
        assert "transTerminal" not in self._row({"transTime": "5时50分"})
        assert "transTerminal" not in self._row(None)


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
        # 直飞行不落中转航站楼（无值不落键）
        assert "transTerminal" not in self._parse(self._direct())[0]

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
        assert "机上Wi-Fi" not in rows[0].get("labels", "")

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
                           "> 💡 直飞 真达标 低￥32，建议出手")
        assert "真达标" in body and "直飞 ￥1468" in body
        assert "直飞 真达标" in body
        assert "🎯" not in body


# ==================== webui 词面/结构钉死 ====================

class TestWebuiPinWords:
    """webui 源码级钉死（预览样例=教学面，词面错一字即误导解码；
    样例串若复活已撤的 🟦 超线仪表条即红）。样例串在
    Python 服务端 handler 而非 PAGE 内，故读模块源文件。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_sample_legend_and_suggest_line(self):
        src = self._src()
        assert src.count("🎯真达标 🟩破线 🟨擦边 超线") >= 2   # NDEMO/pushlog 样例
        assert "直飞 真达标 低￥20，建议出手" in src
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

    def _sent(self, monkeypatch, tmp_path, prices, keep_supplied=False):
        from types import SimpleNamespace as _NS
        import main as _m
        monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
        monkeypatch.setattr(_m, "_ROW_HIST", {})
        _m._SENT_LAST.clear()
        _m._SENT_CNT.clear()
        if not keep_supplied:
            _m._SENT_SUPPLIED.clear()
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
        # 直挂标注健康出勤（10/30≈33%）——r288 起 bag_direct 哨
        # 门槛 10，零出勤夹具会合法开火
        for _r in rows[:10]:
            _r["transferBaggage"] = "direct"
        assert self._sent(monkeypatch, tmp_path,
                          [("ctrip", rows), ("fliggy", rows)]) == []

    def test_zero_hit_new_field_warns(self, monkeypatch, tmp_path):
        """供给基线语义（r316）：健康轮写 lft/tterm 供给，断链轮归零
        真警（「曾供给后断链」检测力不丢）。"""
        healthy = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                    "leftTickets": 5, "transCity": "西安",
                    "transTerminal": "咸阳T3"} for _ in range(30)]
        seen0 = self._sent(monkeypatch, tmp_path, [("ctrip", healthy)])
        assert seen0 == [], seen0
        dead = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
                 "transCity": "西安"}
                for _ in range(30)]
        seen = self._sent(monkeypatch, tmp_path, [("ctrip", dead)],
                          keep_supplied=True)
        flat = " ".join(str(a) for w in seen for a in w)
        assert "leftTickets" in flat
        assert "transTerminal" in flat


# ---- merged from tests/test_v197_regress.py ----

# ==================== D1: ctrip InTimeTag 0 占位绕挡 ====================

class TestCtripIntimeZero:
    """InTimeTag 下发 0%（组合行填槽，结构性占位）时不得落库：
    覆盖分支同过 0 值挡，且伪源不得借 0 占位兜底落「准点100%」。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _item(intime_tag, prate=100):
        """classinfor.prate 恒给伪源 100（生产常态）：真源在场时
        伪源必须被覆盖或置空，不得落库。"""
        item = {"mutilstn": [{"basinfo": {"flgno": "GS7486/FM9426"},
                              "dateinfo": {"ddate": "2026-10-06 08:00:00",
                                           "adate": "2026-10-06 14:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 2050, "quantity": 1,
                                "classinfor": [
                                    {"cgrd": 0, "prate": prate,
                                     "meal": ""}]}]}
        if intime_tag is not None:
            item["aset"] = [{"tagarea": [{"tcode": "InTimeTag",
                                          "tagcnt": intime_tag}]}]
        return item

    def test_intime_zero_is_placeholder_not_truth(self):
        rows = self._parse(self._item("准点率0%"))
        assert rows, "夹具应产出航班行"
        # r311 起 0 占位连空串键一并不落（无值不落键收口），
        # 守卫实效语义不变：不产「准点0%」词面
        assert "prate" not in rows[0], \
            f"InTimeTag 0% 占位落库为 {rows[0].get('prate')!r}（渲染准点0%）"

    def test_intime_real_overrides_pseudo_source(self):
        rows = self._parse(self._item("准点率94%"))
        assert rows[0]["prate"] == "94", "真源覆盖伪源失效"

    def test_intime_absent_pseudo_zero_still_blocked(self):
        """InTimeTag 缺席时伪源 0 由既有挡位拦（v196 钉不回退）；
        r311 起挡位弃值连空串键一并不落。"""
        rows = self._parse(self._item(None, prate=0))
        assert "prate" not in rows[0]


# ==================== E1: build_and_push 入口清陈旧 errcode ====================

class TestBuildPushErrcodeReset:
    """build_and_push 在 send 之前提前 return（无图床 provider/
    无可画数据）时，notifier.last_errcode 仍是上一条告警轮的 -1
    留痕——maybe_daily_report 的「-1 幽灵按已推落账」守卫误命中，
    当日日报被静默吞。入口清零：本轮尚未发送，任何残留皆陈旧。"""

    def test_stale_errcode_cleared_on_early_return(self):
        from report import build_and_push

        class _StaleN:
            last_errcode = -1          # 上轮告警轮残留（类属性即实例可见）

            def send(self, *a, **kw):
                return True

        n = _StaleN()
        ok = build_and_push({}, logging.getLogger("t"), n)
        assert ok is False, "无图床 cfg 应走提前 return"
        assert getattr(n, "last_errcode", "missing") is None, \
            "提前 return 未清陈旧 errcode（幽灵守卫将误吞当日日报）"

    def test_reset_at_function_head(self):
        """清零必须位于函数入口（provider 判空之前）：两个提前
        return 分支都要被覆盖。"""
        import webui  # noqa: F401  (确保 CWD 无关的 import 面)
        import report as _rep
        with open(_rep.__file__, encoding="utf-8") as f:
            src = f.read()
        i0 = src.index("def build_and_push(")
        i1 = src.index("ih = _image_host_cfg(cfg)", i0)
        head = src[i0:i1]
        assert "last_errcode" in head, \
            "清零不在入口段（provider 判空前），第二个提前 return 不受覆盖"


# ==================== E2: push_history 落盘实收形态 ====================

class TestPushHistorySentForm:
    """钉钉 send 超 18000 字节截断后，push_history 落盘的应是
    群内实收形态（含截断尾注），不是截断前的原始 desp——控制台
    「推送记录」与群里实际收到的内容不一致曾无从对账。"""

    def test_history_records_truncated_form(self, monkeypatch):
        import core.notifier as N
        cap = {}

        def fake_hist(title, desp, ok, ch="serverchan", img=None,
                      errcode=None):
            cap["desp"] = desp

        monkeypatch.setattr(N, "_append_push_history", fake_hist)

        class _Resp:
            status_code = 200
            text = '{"errcode":0,"errmsg":"ok"}'

            def json(self):
                return {"errcode": 0}

        monkeypatch.setattr(N.httpx, "post", lambda *a, **kw: _Resp())
        n = N.DingTalkNotifier(
            "https://oapi.dingtalk.com/robot/send?access_token=x",
            logging.getLogger("t"))
        tail = "TAILMARK-被切尾段"
        desp = "x" * 19000 + tail
        assert n.send("t", desp) is True
        assert cap["desp"] != desp, "落盘=截断前原文（与群内实收不一致）"
        assert "已截断" in cap["desp"], "落盘缺截断留痕尾注"
        assert tail not in cap["desp"], "被切尾段混入落盘（非实收形态）"

    def test_history_normal_round_is_untouched(self, monkeypatch):
        """未超限轮：落盘=发送文本（尾空段收口后的形态），零回归。"""
        import core.notifier as N
        cap = {}

        def fake_hist(title, desp, ok, ch="serverchan", img=None,
                      errcode=None):
            cap["desp"] = desp

        monkeypatch.setattr(N, "_append_push_history", fake_hist)

        class _Resp:
            status_code = 200
            text = '{"errcode":0,"errmsg":"ok"}'

            def json(self):
                return {"errcode": 0}

        monkeypatch.setattr(N.httpx, "post", lambda *a, **kw: _Resp())
        n = N.DingTalkNotifier(
            "https://oapi.dingtalk.com/robot/send?access_token=x",
            logging.getLogger("t"))
        n.send("t", "正常内容\n\n")
        # r318 防指纹时刻行契约：落账=实收形态（send 出站正文尾部
        # 携带 ⏰ HH:MM 防钉钉正文模糊查重）——正文主体仍零改写
        assert cap["desp"].startswith("正常内容"), cap["desp"]
        assert "正常内容\n\n" in cap["desp"] and "⏰ " in cap["desp"], cap["desp"]


class TestServerChanHistorySentForm:
    """ServerChan 同族收口（Soldier P2-1）：31800 字节截断后落盘
    应为实收形态（含尾注），记录≠实收的缺陷不随通道切换复发。"""

    def test_history_records_truncated_form(self, monkeypatch):
        import core.notifier as N
        cap = {}
        monkeypatch.setattr(
            N, "_append_push_history",
            lambda t, d, ok, ch="serverchan", img=None:
            cap.update(desp=d, ok=ok))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"code":0}'

        monkeypatch.setattr(N.urllib.request, "urlopen",
                            lambda *a, **kw: _Resp())
        n = N.ServerChanNotifier("SCT123", logging.getLogger("t"))
        tail = "TAILMARK-被切尾段"
        desp = "x" * 33000 + tail
        assert n.send("t", desp) is True
        assert cap["desp"] != desp, "落盘=截断前原文（记录≠实收）"
        assert "已截断" in cap["desp"], "落盘缺截断留痕尾注"
        assert tail not in cap["desp"], "被切尾段混入落盘"


# ==================== E3: 近 7 天趋势行恢复常驻 ====================

def _mk_db(tmp_path, rows, date="2026-10-06"):
    """(hours_ago, 直飞价, 中转价) 多轮库；样本时刻动态生成+锚定
    今天中午（168h 相对窗，固定时刻会随日历滑出窗「上午绿下午红」，
    裸 now 相对偏移跨日历日会翻转日期桶）。"""
    from core.storage import SCHEMA
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    now = dt.datetime.now().replace(hour=12, minute=0, second=0,
                                    microsecond=0)
    for h, dprice, tprice in rows:
        ts = (now - dt.timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
        fs = [{"price": dprice, "name": "CZ6976", "code": "CZ6976",
               "transCity": "", "depTime": "08:00", "arrTime": "11:00",
               "depDate": date, "arrDate": date, "totalDuration": "3时"}]
        if tprice is not None:
            fs.append({"price": tprice, "name": "MU8370", "code": "MU8370",
                       "transCity": "郑州", "depTime": "09:00",
                       "arrTime": "15:30", "depDate": date,
                       "arrDate": date, "totalDuration": "6时30分"})
        conn.execute(
            "INSERT INTO flight_prices (platform,from_city,to_city,"
            "depart_date,price,fetched_at,extra) VALUES (?,?,?,?,?,?,?)",
            ("qunar", "SHA", "URC", date, dprice, ts,
             json.dumps(fs, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return db


class TestTrendLineResident:
    """近 7 天趋势行恢复常驻：走势图窗 48h 承载不了 168h 文本信息，
    撤常驻让正常有图轮的 7 天趋势彻底消失（图内容量≥被撤文本版）。"""

    def test_trend_line_present_in_charted_round(self, tmp_path):
        from core.alerter import Alerter
        from core.models import FlightPrice, Route
        import types as _ty

        db = _mk_db(tmp_path, [(3, 2000, None), (1, 1500, None)])
        captured = []

        class FakeN:
            def send(self, t, d, at_mobiles=None, is_at_all=False,
                     launch=""):
                captured.append((t, d, at_mobiles))
                return True

        a = Alerter(logging.getLogger("t"), notifier=FakeN(),
                    storage=_ty.SimpleNamespace(db_path=db), digest=True)
        # 有图场景（走势图上传成功的正常轮）：撤常驻的形态下此轮
        # desp 无「近7天」——回归钉
        a.round_charts = {("SHA", "URC", "2026-10-06"):
                          "https://iili.io/fake1.png"}
        r = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐", dates=["2026-10-06"],
                  alert_direct=1600, alert_transfer=0)
        extra = json.dumps([{"price": 1500, "name": "CZ6976",
                             "code": "CZ6976", "depTime": "08:00",
                             "arrTime": "11:00", "depDate": "2026-10-06",
                             "arrDate": "2026-10-06", "transCity": "",
                             "totalDuration": "3时"}])
        ps = [FlightPrice(platform="qunar", from_city="SHA", to_city="URC",
                          depart_date="2026-10-06", price=1500,
                          extra=extra)]
        a.check_multi([(r, ps)])
        assert captured, "达标轮应产生聚合推送"
        desp = captured[0][1]
        assert "近7天" in desp, \
            "有图正常轮 7 天趋势行缺席（撤常驻后图内无 168h 承载）"
        assert "直飞" in desp and "↓" in desp

    def test_missing_chart_fallback_still_present(self, tmp_path):
        """趋势行全文恰一次：常驻一处 + 缺图分支不补位（防双份回归
        用行为钉——源码钉抓不住「恢复补位」的静默回归）。"""
        from core.alerter import Alerter
        from core.models import FlightPrice, Route
        import types as _ty

        db = _mk_db(tmp_path, [(3, 2000, None), (1, 1500, None)])
        captured = []

        class FakeN:
            def send(self, t, d, at_mobiles=None, is_at_all=False,
                     launch=""):
                captured.append((t, d, at_mobiles))
                return True

        a = Alerter(logging.getLogger("t"), notifier=FakeN(),
                    storage=_ty.SimpleNamespace(db_path=db), digest=True)
        a.round_charts = {}   # 缺图场景
        r = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐", dates=["2026-10-06"],
                  alert_direct=1600, alert_transfer=0)
        extra = json.dumps([{"price": 1500, "name": "CZ6976",
                             "code": "CZ6976", "depTime": "08:00",
                             "arrTime": "11:00", "depDate": "2026-10-06",
                             "arrDate": "2026-10-06", "transCity": "",
                             "totalDuration": "3时"}])
        ps = [FlightPrice(platform="qunar", from_city="SHA", to_city="URC",
                          depart_date="2026-10-06", price=1500,
                          extra=extra)]
        a.check_multi([(r, ps)])
        assert captured, "达标轮应产生聚合推送"
        desp = captured[0][1]
        assert desp.count("近7天") == 1, \
            f"趋势行出现 {desp.count('近7天')} 次（常驻+补位双份或缺席）"


# ==================== D 路 WebUI 三案（源码级钉） ====================

class TestWebuiV197Pins:
    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_route_label_always_emitted(self):
        """📈 走势入口：每一行都必须带 route 标签，不再按航线/日期数量
        设门——单启用航线×单日期也必须能点开走势（旧门曾让整表入口消失）。"""
        src = self._src()
        i = src.index("rt_label = ")
        seg = src[i:i + 180]
        assert "if rr else" in seg, "route 标签仍受条件门限制"
        assert "len(routes) > 1" not in seg, "旧多航线门残留"
        assert "len(rr.get(\"dates\")" not in seg, "旧多日期门残留"

    def test_anim_clip_covers_tag_zone(self):
        """入场动画 clip 终帧须覆盖标签可达域（低标注可画到 W-3）：
        (W-L-R+4) 死区曾残留早帧悬浮字。"""
        src = self._src()
        assert "(W-L-R+4)*e" not in src, "动画 clip 死区未收口"
        assert "(W-L+2)*e" in src, "clip 终帧宽度未覆盖标签可达域"

    def test_min_tag_overlap_forces_vertical_stagger(self):
        """「低」标注互叠罚分带纵向错距梯度：必撞时错开 ≥16px 的
        候选胜出，不再完全同位互盖。"""
        src = self._src()
        assert "16-Math.abs(cy-b[1])" in src, \
            "互叠罚分无纵向错距梯度（双系列低标注同位互盖）"
        assert "?999:0)" not in src, "旧常数罚分形态残留"


# ==================== 版本门禁随批 ====================

def test_version_bumped_this_round():
    """发版批内 bump（铁律：版本号与功能改动同批）；>= 元组比较
    只拦落后允许领先。"""
    import re
    import subprocess
    from main import __version__ as v
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", v)
    assert m, v
    cur = tuple(map(int, m.groups()))
    assert cur >= (1, 5, 96), f"版本未随本轮 bump: {v}"


# ---- merged from tests/test_v198_regress.py ----

# ==================== D1: ctrip aset「中转住宿」标签归一 ====================

class TestCtripTransferHotelTag:
    """aset 层「中转住宿」入 labels 白名单并归一「中转免费住宿」：
    与政策级 nt=10 双现行时去重单串（labels 是 ·join 单串）。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _item(aset_tags=None, policy_notes=None):
        """policy_notes：fnotelst 注释列表（nt=10 词面走这里）。"""
        item = {"mutilstn": [{"basinfo": {"flgno": "3U8230"},
                              "dateinfo": {"ddate": "2026-10-06 08:00:00",
                                           "adate": "2026-10-06 14:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 2050, "quantity": 1,
                                "classinfor": [
                                    {"cgrd": 0, "prate": 100, "meal": ""}]}]}
        if policy_notes:
            item["policyinfo"][0]["fnotelst"] = [
                {"notetype": 10, "notecnt": n} for n in policy_notes]
        if aset_tags:
            item["aset"] = [{"tagarea": [
                {"tcode": tc, "tagcnt": c} for tc, c in aset_tags]}]
        return item

    def test_aset_hotel_tag_normalized(self):
        """该行全部政策无 nt=10 承载（3U8230 生产实证），aset 词是
        唯一载体——归一为「中转免费住宿」入 labels。"""
        rows = self._parse(self._item(
            aset_tags=[("G_XIYZZZS202601", "中转住宿")]))
        assert rows, "夹具应产出航班行"
        assert "中转免费住宿" in (rows[0].get("labels") or ""), \
            f"aset「中转住宿」被排除，权益词永久缺失：{rows[0].get('labels')!r}"

    def test_dual_carrier_dedup(self):
        """政策级 nt=10 与 aset 词双现行：labels 单串只出现一次。"""
        rows = self._parse(self._item(
            aset_tags=[("G_XIYZZZS202601", "中转住宿")],
            policy_notes=["中转免费住宿"]))
        assert rows
        assert (rows[0].get("labels") or "").count("中转免费住宿") == 1

    def test_non_transfer_benefit_unaffected(self):
        """既有 nt=10 路径不回退：无 aset 词时照常落词。"""
        rows = self._parse(self._item(policy_notes=["中转免费住宿"]))
        assert rows
        assert "中转免费住宿" in (rows[0].get("labels") or "")


# ==================== P1: 901+ 粗指针档 chip 触控基准 ====================

class TestCoarseChipTouchBaseline:
    """>900px 粗指针块 .chip 补 font-size:13px（与 ≤900 姊妹块同值）：
    该档 chip 本体 35px 差 1px 不达 36 触控基准。钉锁级联实际胜者——
    规则必须落在 901+ 块内（媒体块无「更严条件更后胜」，块内声明即
    该档胜者），且其后再无同选择器 font-size 覆写。"""

    def _src(self):
        import webui
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_chip_fontsize_in_901_coarse_block(self):
        src = self._src()
        m = re.search(
            r"@media\(pointer:coarse\) and \(min-width:901px\)\{.*?"
            r"\.chip,\.mchip,\.rngchip\{padding:9px 14px;font-size:13px\}",
            src, re.S)
        assert m, "901+ 粗指针块 .chip 缺 font-size:13px（35px<36 基准）"

    def test_no_later_chip_fontsize_override(self):
        """置尾纪律反杀面：901+ 块之后不得再有「1280 粗指针上下文
        可适用」的 .chip font-size 覆写——窄屏块（条件含 max-width，
        1280 不适用）合法豁免，无宽度上界或 coarse 块内覆写即反杀。"""
        src = self._src()
        m = re.search(
            r"@media\(pointer:coarse\) and \(min-width:901px\)\{.*?"
            r"\.chip,\.mchip,\.rngchip\{padding:9px 14px;font-size:13px\}",
            src, re.S)
        assert m, "前置钉失守"
        tail = src[m.end():]
        for mm in re.finditer(r"\.chip[,{][^}]*font-size", tail):
            ctx = tail[:mm.start()]
            i_media = ctx.rfind("@media(")
            cond = ctx[i_media:ctx.find("{", i_media)] if i_media >= 0 else ""
            assert "max-width" in cond, \
                "901+ 块之后存在 1280 粗指针可适用的 .chip font-size 覆写" \
                f"（层叠反杀）：{cond!r}"

    def test_rngchip_fontsize_in_all_touch_blocks(self):
        """三触控块（≤900 粗指针/901+ 粗指针/≤760 触控）.rngchip 同值
        补 font-size:13px：基础 12px 时段挡位本体 ~35px 差 1px 不达
        36 触控基准——只补一档则「同值补档」注释失准（姊妹块缺陷类
        一次清完，防下轮再审计同案）。"""
        src = self._src()
        n = src.count(".rngchip{padding:9px 14px;font-size:13px}")
        assert n >= 3, f"三触控块 .rngchip 须同值 13px，实得 {n} 处"


# ==================== P2: 走势入场动画可见性 ====================

class TestChartAnimReveal:
    """入场动画轮跳过首绘：先全量画满终帧再逐帧 clip 重绘同内容=
    零视觉产出。守卫钉：动画分支前不得有无条件 chartDraw() 首绘。"""

    def _src(self):
        import webui
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_anim_path_skips_initial_full_draw(self):
        src = self._src()
        i = src.index("const _anim=CHART_ANIM&&!RM;")
        seg = src[i:i + 200]
        assert "if(!_anim){chartDraw();" in seg, \
            "动画轮未跳过首绘（全量终帧先画满，clip 逐帧重绘零视觉产出）"
        assert seg.index("if(!_anim){chartDraw();") < seg.index("if(_anim){"), \
            "直绘守卫必须位于动画分支之前（顺序即语义）"

    def test_non_anim_path_still_direct_draw(self):
        """RM/非动画路径保持直绘（终帧立即可见，r197 死区钉前提）。"""
        src = self._src()
        assert re.search(r"if\(!_anim\)\{chartDraw\(\);", src), \
            "直绘守卫缺失"


# ==================== P3: CSV 准点率列 ====================

class TestCsvOntimeColumn:
    """CSV 增「准点率」列：决策字段（准点率影响购买决策）进导出面，
    就近插位贴「取消率」（UI 明细次行同款「准点N%·取消N%」并提）。"""

    def _page(self):
        import webui
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_head_has_ontime_next_to_cancel(self):
        m = re.search(r"const head=\[(.*?)\];", self._page(), re.S)
        assert m, "CSV 列头锚点丢失"
        head = m.group(1)
        # v295：采集入口/证据级别（路径级溯源，贴渠道）= 48
        assert head.count(",") + 1 == 48, \
            f"列数锚应随批内增列保持同步（r269 往返推荐=45；r51 税费=46；v295 入口/证据=48）：{head.count(',') + 1}"
        assert "'准点率'" in head
        assert head.index("'准点率'") < head.index("'取消率'"), \
            "准点率应就近插位贴取消率（次行并提同序）"

    def test_row_value_form(self):
        page = self._page()
        assert "(f.prate?f.prate+'%':'')" in page, \
            "CSV 行值缺准点率取值（与明细次行同形：有值出 N%）"


# ==================== E1: kpi_tier_txt 真达标档显名 ====================

class TestKpiTierQualNamed:
    """真达标态补「·真达标」（与破线态「·行情」对称）：PNG summary
    脱离消息上下文时正向档不显名、靠「无·行情注」单向消歧。词面取
    TIER_FULL 单源；恰达线 gap_txt 已出完整词面不双挂。"""

    def test_qual_state_named(self):
        from core.alerter import kpi_tier_txt
        t = kpi_tier_txt("直飞", 100, 200, True)
        assert t == "直飞 ￥100 低￥100·真达标", \
            f"真达标态无档位词面：{t!r}"

    def test_brk_unqualified_note_unchanged(self):
        from core.alerter import kpi_tier_txt
        assert kpi_tier_txt("直飞", 100, 200, False) == \
            "直飞 ￥100 低￥100·行情"

    def test_exact_line_not_double_tagged(self):
        from core.alerter import kpi_tier_txt
        t = kpi_tier_txt("直飞", 200, 200, True)
        assert t == "直飞 ￥200 真达标", f"恰达线不双挂：{t!r}"
        assert t.count("真达标") == 1

    def test_over_and_near_unchanged(self):
        from core.alerter import kpi_tier_txt
        assert kpi_tier_txt("直飞", 300, 200, False) == \
            "直飞 ￥300 差￥100"
        t = kpi_tier_txt("直飞", 210, 200, False)
        assert t.startswith("直飞 ￥210 擦边") and "真达标" not in t


# ==================== E2: KPI 行2 地板档截断 ====================

class TestL2FloorTruncation:
    """行2 降级链地板档恒达标：超预算时保尾截头（r281 P2-1 修法 B，
    真实计宽网格选形：时刻/跨天锚定行尾=决策级辨识信息，头部名段
    让位；旧「保头截尾」曾把到达时刻截成半截甚至整段消失）。"""

    def test_floor_truncated_to_budget(self):
        from core.alerter import _l2_fallbacks, _disp_dw
        base = "中国联合航空 KN9999 超长航司名超长航司名超长航司名"
        assert _disp_dw(base) > 40, "夹具应超预算"
        fbs = _l2_fallbacks(base, "+1天", "↑5%")
        assert _disp_dw(fbs[-1]) <= 40, \
            f"地板档超宽原样吐（{ _disp_dw(fbs[-1]) }/40）"

    def test_floor_keeps_identity_head(self):
        # 旧钉锁「保头」（base.startswith(floor)）——修法 B 后地板
        # 改保尾（尾部锚定 cross+时刻域，头部名段让位），钉随模型
        # 改写：地板恒为 base+cross 的尾缀且预算内（恒达标律不变）
        from core.alerter import _l2_fallbacks, _disp_dw
        base = "中国联合航空 KN9999 超长航司名超长航司名超长航司名"
        fbs = _l2_fallbacks(base, "", "")
        assert fbs[-1], "地板档缺失"
        assert _disp_dw(fbs[-1]) <= 40, "地板档超预算"
        assert base.endswith(fbs[-1]), (
            "地板档应为 base 尾缀（保尾截头，尾部决策信息锚定）")

    def test_normal_input_order_unchanged(self):
        """档序语义不回退：跨天档先于地板档（涨跌档=恒宽死档已按
        档序律删除，LESSONS 十九§9：辨识信息先于次要信号被丢）。
        r281 修法 B 后 cross 真入地板链：短输入下地板=base+cross
        整串（预算内恒达标），地板档不再缺席 cross。"""
        from core.alerter import _l2_fallbacks
        fb = _l2_fallbacks("MU 08:00→11:00", "+1天", "↑5%")
        assert fb[0] == "MU 08:00→11:00+1天", "跨天档不在首位"
        assert fb[-1].endswith("+1天"), "地板档 cross 缺席（次生丢失）"
        assert fb[-1] == "MU 08:00→11:00+1天", (
            "短输入下地板=整串（预算内恒达标）")
