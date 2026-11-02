# -*- coding: utf-8 -*-
"""r199 数据层立案（C 路观测定谳两项 + 五渠道调研零新键归档）。

L1（观测立案）：ctrip 衔接为两段起降差重建的结构化真值（mutilstn
相邻段 adate→ddate，渠道唯一全量真实衔接），但行未带 layoverSrc
标记，flightnorm 的 %1440 击杀区启发式（服务「猜测值」的统计守卫）
把真值一并击杀——CZ6909/CZ8882 实锤（真停 21h + 全程 27h=2880 恰
1440 整数倍，生产 ~550 条/天 layoverT 被置空，衔接下限筛选同步误剔
真中转行）。真值标记豁免（qunar PC layoverSrc="times" 同律同值，
零新协议枚举），物理守卫（衔接≥全程/飞行剩余<60 分）不豁免。

L2（观测立案）：中转城市裸码 AIRPORT_CN 覆盖外原样落库（7 天 DB
实测 MIG 58 行/YBP 4 行渲染成英文码）——WDS/UYN/LYA/YCU 先例同律
补录（城市级中文，宁缺勿错不建机场全名）。

撤案备案（勿再立案）：tuniu prate=20 守卫在位（09-18 单日存量
354 条已老化出全部展示窗）；tongcheng cancelRate=0 为渠道显式真值
（无数据=键缺席机制独立在案，25k 行 None 同池互证）；prate=100
同航班跨渠道一致（94≈93 舍入差）为真值；bizPrice==price 四渠道
全期散布=真实偶发同价。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v199_fields.py -q
"""
import json

from core import flightnorm


# ==================== L1: ctrip 衔接真值豁免标记 ====================

class TestCtripLayoverTruthExempt:
    """ctrip 两段起降差衔接=结构化真值，带 layoverSrc="times" 标记
    后 flightnorm 1440 击杀区豁免；物理守卫照杀不豁免。"""

    @staticmethod
    def _parse(item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _transfer_item():
        """CZ6909/CZ8882 同构：首段 08:00→11:30，停 21h，次段
        08:30→11:00（+1天）——lay=1260、dur=1620，(lay+dur)%1440=0
        落击杀区。"""
        seg = lambda fn, dp, ap, dd, ad: {
            "basinfo": {"flgno": fn},
            "dateinfo": {"ddate": dd, "adate": ad},
            "dportinfo": {"city": dp}, "aportinfo": {"city": ap}}
        return {"mutilstn": [
            seg("CZ6909", "乌鲁木齐", "西安",
                "2026-10-05 08:00:00", "2026-10-05 11:30:00"),
            seg("CZ8882", "西安", "上海",
                "2026-10-06 08:30:00", "2026-10-06 11:00:00")],
            "policyinfo": [{"tprice": 1500, "quantity": 3,
                            "classinfor": [
                                {"cgrd": 0, "prate": 96, "meal": ""}]}]}

    def test_row_carries_truth_mark(self):
        rows = self._parse(self._transfer_item())
        assert rows, "夹具应产出中转行"
        assert rows[0].get("layover") == 1260, \
            f"衔接真值应原样落键：{rows[0].get('layover')!r}"
        assert rows[0].get("layoverSrc") == "times", \
            "真值行缺 layoverSrc 标记（1440 启发式将误杀）"

    def test_truth_survives_normalize(self):
        row = self._parse(self._transfer_item())[0]
        flightnorm.normalize(row, "2026-10-05")
        assert row.get("layoverT") == "21:00", \
            f"真衔接被启发式击杀置空：{row.get('layoverT')!r}"
        assert row.get("layoverM") == 1260

    def test_physical_guard_not_exempted(self):
        """豁免只挡 1440 启发式：衔接≥全程/飞行剩余<60 分的物理
        守卫照杀（真值标记不得复活渠道分段错值）。"""
        row = self._parse(self._transfer_item())[0]
        row["layover"] = 1700          # ≥ 全程 1620
        row["layoverSrc"] = "times"
        flightnorm.normalize(row, "2026-10-05")
        assert row.get("layoverM") == 0 and row.get("layoverT") == ""

    def test_direct_row_no_mark(self):
        """直飞行无衔接不落标记（有值才落，宁缺勿错）。"""
        it = {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                            "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                         "adate": "2026-10-05 11:30:00"},
                            "aportinfo": {"city": "上海"}}],
              "policyinfo": [{"tprice": 1200, "quantity": 3,
                              "classinfor": [
                                  {"cgrd": 0, "prate": 96, "meal": ""}]}]}
        rows = self._parse(it)
        assert rows and "layoverSrc" not in rows[0]


# ==================== L2: AIRPORT_CN 补录 ====================

class TestAirportCnSupplement:
    """中转城市裸码补录（7 天 DB 实测 MIG 58/YBP 4 行原样落库），
    WDS/UYN/LYA/YCU 先例同律。"""

    def test_mig_ybp_mapped(self):
        assert flightnorm.AIRPORT_CN.get("MIG") == "绵阳"
        assert flightnorm.AIRPORT_CN.get("YBP") == "宜宾"

    def test_normalize_rewrites_transcity(self):
        row = flightnorm.normalize({"transCity": "MIG"}, "2026-10-05")
        assert row["transCity"] == "绵阳"
        row = flightnorm.normalize({"transCity": "YBP"}, "2026-10-05")
        assert row["transCity"] == "宜宾"
