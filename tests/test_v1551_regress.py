"""回归：渠道字段三批（同程中转增值服务/航司中转/航站楼、
飞猪航站楼行分支、ctrip 平均延误/连廊率/Wi-Fi/航变退改）+ 推送侧
仪表条撤超线 + 小注/标题日期/建议行词面收口。夹具形态全部取自
debug/ dump 实证（10-05/10-06）。"""
import json

import pytest


# ==================== 渠道字段三批 ====================

class TestTongchengTransferFields:
    """同程 connection 报文 增采四字段（10-05 dump：stss 19/
    fps、$tcTip 37 处、dat/aat 26/26、doc.check 恒定「转机免安检」）。"""

    def _rows(self, fps, doc=None):
        from crawlers.tongcheng import TongchengCrawler
        obj = {"success": True, "data": {"fps": fps,
                                         "doc": doc or {}}}
        return TongchengCrawler._extract_transfer_flights(
            json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _fp(**over):
        fp = {
            "dt": "2026-10-05 15:15", "at": "2026-10-06 07:55",
            "td": "16h40m", "sd": "11h0m", "sc": "石家庄",
            "dat": "", "aat": "T2",
            "ss": [{"fn": "9C7006", "dt": "2026-10-05 15:15",
                    "at": "2026-10-05 19:05", "asn": "春秋",
                    "amn": "空客A320"},
                   {"fn": "9C7310", "dt": "2026-10-06 06:05",
                    "at": "2026-10-06 07:55", "asn": "春秋",
                    "amn": "空客A320"}],
            "lps": [{"atp": 2320, "brs": [{"al": 5}],
                     "pts": [{"td": "5.6折经济舱"}],
                     "$tcTip": {"c1": "中转专享",
                                "c2": "航司中转，享联程服务"}}],
            "stss": [
                {"ServiceType": "TRANSFER_LOUNGE",
                 "ServiceName": "免费休息室"},
                {"ServiceType": "TRANSFER_MEAL",
                 "ServiceName": "免费餐食"},
                {"ServiceType": "TRANSFER_MEAL",
                 "ServiceName": "免费餐饮"},
                {"ServiceType": "TRANSFER_MEAL",
                 "ServiceName": "免费餐食"}],   # 重复项去重
        }
        fp.update(over)
        return fp

    def test_transfer_service_dedup_and_check(self):
        rows = self._rows([self._fp()],
                          doc={"check": "转机免安检"})
        assert rows, "行被丢弃"
        r = rows[0]
        # 去重保序：免费餐食只出现一次
        assert r["transferService"] == ("免费休息室/免费餐食/免费餐饮"
                                        "/转机免安检")

    def test_airline_transfer_follows_lowest_policy(self):
        # 两政策：低价政策带 $tcTip——标注须随最低价配对（与 cabin 同律）
        fps = [self._fp(lps=[
            {"atp": 2500, "brs": [{"al": 5}],
             "pts": [{"td": "经济舱"}],
             "$tcTip": {"c2": "自行中转"}},
            {"atp": 2320, "brs": [{"al": 5}],
             "pts": [{"td": "经济舱"}],
             "$tcTip": {"c2": "航司中转，享联程服务"}}])]
        r = self._rows(fps)[0]
        assert r["airlineTransfer"] == "航司中转，享联程服务"
        assert r["price"] == 2320

    def test_terminals_from_fp_layer(self):
        r = self._rows([self._fp()])[0]
        assert r["depTerminal"] == ""      # 单航站楼出发侧空串不造
        assert r["arrTerminal"] == "T2"

    def test_no_stss_leaves_empty_but_check_only(self):
        # 10-06 形态：stss 覆盖 1/23——无服务行如实留空，仅 doc.check 并入
        fp = self._fp()
        fp.pop("stss")
        r = self._rows([fp], doc={"check": "转机免安检"})[0]
        assert r["transferService"] == "转机免安检"


class TestTongchengDirectTerminal:
    """直飞 fl 元素 dat/aat（47/47 在场）：同程曾是五渠道唯一零航站楼。"""

    def test_direct_terminal(self):
        from crawlers.tongcheng import TongchengCrawler
        obj = {"data": {"fl": [{
            "fn": "GS7587", "asn": "天津", "dac": "URC", "aac": "PVG",
            "dt": "2026-10-05 07:10", "at": "2026-10-05 13:45",
            "td": "6h35m", "dat": "", "aat": "T2",
            "lps": [{"atp": 1180, "brs": [{"al": 5}]}]}]}}
        rows = TongchengCrawler._extract_flights(
            json.dumps(obj, ensure_ascii=False))
        assert rows[0]["depTerminal"] == ""
        assert rows[0]["arrTerminal"] == "T2"


class TestFliggyTerminalLines:
    """飞猪机场行分支（10-05 HTML 实证：出发侧「乌鲁木齐天山国际机场」
    无 T 码 35 处、到达侧「虹桥国际机场T2」带码为主）。"""

    def _parse(self, lines):
        from crawlers.fliggy import FliggyCrawler
        return FliggyCrawler._parse_pc_text("\n".join(lines), "2026-10-05")

    def test_dep_no_code_arr_with_code(self):
        rows = self._parse([
            "春秋9C8866", "中型机 321", "15:15", "19:05",
            "乌鲁木齐天山国际机场", "虹桥国际机场T2", "96%", "¥1180"])
        assert rows and rows[0]["depTerminal"] == ""
        assert rows[0]["arrTerminal"] == "T2"

    def test_both_with_code(self):
        rows = self._parse([
            "东航MU8369", "中型机 737", "08:00", "12:30",
            "虹桥国际机场T1", "浦东国际机场T2", "¥2320"])
        assert rows[0]["depTerminal"] == "T1"
        assert rows[0]["arrTerminal"] == "T2"

    def test_terminal_not_stolen_after_price(self):
        # 页面尾部异源模块含「机场」文本：价格已定时机场行守卫不再吸收
        rows = self._parse([
            "春秋9C8866", "中型机 321", "15:15", "19:05",
            "乌鲁木齐天山国际机场", "虹桥国际机场T2", "¥1180",
            "酒店距机场3公里"])
        assert rows[0]["arrTerminal"] == "T2"
        assert rows[0]["price"] == 1180


class TestCtripExtendinfos:
    """ctrip extendinfos 补采（content 全集 40 档实证）：平均延误 int
    分钟与 tuniu 同协议（webui 明细次行消费端已在）、连廊率、Wi-Fi 与
    航变免费退改并入 labels 走既有渲染（防孤儿键）。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        obj = {"fltitem": [item]}
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _item(extend, fnotelst=None):
        seg = {"basinfo": {"flgno": "MU5137"},
               "dateinfo": {"ddate": "2026-10-05 08:00:00",
                            "adate": "2026-10-05 11:30:00"},
               "aportinfo": {"city": "上海"}}
        ci = {"cgrd": 0, "prate": 96, "meal": "有餐食",
              "extendinfos": extend}
        it = {"mutilstn": [seg],
              "policyinfo": [{"tprice": 1200, "quantity": 1,
                              "classinfor": [ci]}]}
        if fnotelst is not None:
            it["policyinfo"][0]["fnotelst"] = fnotelst
        return it

    def test_avgdelay_bridge_wifi(self):
        rows = self._parse(self._item([
            {"content": "平均延误21分钟"},
            {"content": "连廊率100%"},
            {"content": "机上Wi-Fi"},
            {"content": "机龄8年5个月"}]))
        r = rows[0]
        assert r["avgDelay"] == 21
        assert r["bridgeRate"] == 100
        assert "机上Wi-Fi" in r["labels"]
        # 机龄精度协议：「8年5个月」→ 8+5/12 折算小数年（曾截断
        # 丢月成分，与 tuniu flightYear 小数协议对齐）
        assert r["planeAge"] == "8.4"

    def test_refund_free_into_labels(self):
        rows = self._parse(self._item(
            [{"content": "平均延误18分钟"}],
            fnotelst=[{"notecnt": "航变免费退改|行李直达"}]))
        r = rows[0]
        assert "航变免费退改" in r["labels"]
        # 随最低价政策配对：另一政策带词但价高时不取
        rows2 = self._parse({
            "mutilstn": [{"basinfo": {"flgno": "MU5137"},
                          "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                       "adate": "2026-10-05 11:30:00"},
                          "aportinfo": {"city": "上海"}}],
            "policyinfo": [
                {"tprice": 900, "quantity": 1,
                 "classinfor": [{"cgrd": 0, "prate": 96, "meal": "",
                                 "extendinfos": []}]},
                {"tprice": 1200, "quantity": 1,
                 "classinfor": [{"cgrd": 0, "prate": 96, "meal": "",
                                 "extendinfos": []}],
                 "fnotelst": [{"notecnt": "航变免费退改"}]}]})
        assert "航变免费退改" not in (rows2[0]["labels"] or "")


# ==================== 推送语义档收口 ====================

class TestGaugeOverlineRemoved:
    """撤超线仪表条：🟦 进度格=行1 百分比二次编码且「有图无例」
    （生产 200 条 185 条成串蓝块）；超线默认态不占语义点（定律）。"""

    def test_overline_returns_empty(self):
        from core.alerter import Alerter
        g = Alerter._gauge
        assert g(1500, 1600) == "🟩" * 5       # 破线行保留档位强化
        assert g(2319, 1600) == ""             # 超线撤
        assert g(None, 1600) == ""

    def test_multi_kpi_no_blue_blocks(self, monkeypatch, tmp_path):
        # digest 文本不再出现 🟦 成串块（与 test_core_units「超线不加点」
        # 语义测试同向的仪表条侧收口）
        from core.alerter import Alerter
        a = Alerter.__new__(Alerter)
        a.logger = None
        a._prev_hit = False
        g = Alerter._gauge
        assert g(1850, 1600) == "" and g(5000, 1600) == ""


class TestNoteAndTitleWording:
    """小注化石与词面收口：四档色时代「价格标绿=真达标」会让人把描边
    绿（行情破线）读成真达标；建议行「达标」正名「真达标」。"""

    def test_table_note_distinguishes_green_shades(self):
        from core import alerter
        src = open(alerter.__file__, encoding="utf-8").read()
        assert "价格标绿=真达标" not in src
        # 推送审校 P1：标题行 47 半角超 40 铁律（每推必现）+
        # 「描绿=行情价」与图内图例「行情破线」同屏两词面——改「破线」
        # 并去括号壳，两处（总表/TOP5）同律 38/40。
        # 档位词面收编 _TIER_TABLE：字面收敛为 _TBL_HEAD_TIER
        # 派生常量（×2 手抄归一），钉投影等价+两处引用计数
        assert "实绿=真达标·描绿=行情价" not in src
        assert "实绿=" not in src
        assert alerter._TBL_HEAD_TIER == "深绿=真达标·描绿=破线"
        assert src.count("_TBL_HEAD_TIER}") == 2

    def test_suggest_line_uses_qual_word(self):
        from core.alerter import Alerter, gap_txt, TIER_FULL
        # gap_txt 单源：真达标口径产出「低￥N」
        assert gap_txt(1800, 1900, True) == "低￥100"
        assert TIER_FULL["qual"] == "真达标"
        src = open(Alerter.__module__.replace(".", "/") + ".py",
                   encoding="utf-8").read()
        # 词面投影收编：钉 f-string 投影式（词面零变化由
        # TIER_FULL 断言+test_core_units 输出级钉双护栏）
        assert "{label} {TIER_FULL['qual']} " in src
        assert "{gap_txt(price, th, True)}，建议出手" in src

    def test_png_titles_mmdd(self):
        import report
        from core import alerter
        src = open(report.__file__, encoding="utf-8").read()
        # 走势标题与日报表标题（report.py）、单航线表标题（alerter.py）MM/DD
        assert src.count("{date[5:].replace('-', '/')}") >= 2
        asrc = open(alerter.__file__, encoding="utf-8").read()
        assert "{sections[0]['date'][5:].replace('-', '/')}" in asrc
