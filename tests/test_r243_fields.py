# -*- coding: utf-8 -*-
"""r243 数据层：qunar H5 中转 shareCarrier 自引用门 + 首段共享真值源。

W-1（_scratch/worker_r243_ch1.md 观察哨⑥触发翻案立案）：「首段共享
+二段常规」中转行（标本 3U1599/MU2161）——binfo1.codeShare=1、
binfo1.mainCarrier='CZ6305'（首段实际承运真值）在场但
mainCarrierSimpleNameAndNo 恒空，mixFlightName 末行兜底把第二段
自身词面「东航MU2161」当共享承运落库（DB 799 行中 12 行自引用
误导实证，含 MU8086/MF8561→「厦航MF8561」同构）。读者信息为负：
自引用误导 + 首段实际承运丢失（同班 PC 行 shareCarrier='CZ6305'
真值先例）。

修复三档：
1. 主源 mainCarrierSimpleNameAndNo（不变，v1590 既有钉）；
2. 真值源 mainCarrier 机读号（新增：在场且 ≠ 本行段号集——PC 直
   飞 m4 门「mainCarrier≠airCode」的段号集推广，PC 同键机读号
   形态先例）；
3. mixCodeShare 末行兜底加自引用门（末行号 ∈ 段号集 → 宁缺勿落，
   航班号提取用 _RE_FNO 先例正则）。

样本形态取自 W-1 调研 dump 实证 + test_v1590 同构构造器。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r243_fields.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


def _qn_trans_f(code="3U1599/MU2161", b1=None, b2=None, **top):
    """W-1 标本形态：中转行 code 含 /、info=binfo1、binfo2 带二段到达。"""
    f = {
        "minPrice": 1200, "code": code,
        "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                        "depDate": "2026-10-05", "arrDate": "2026-10-05",
                        "codeShare": 1,
                        "mainCarrierSimpleNameAndNo": ""}, **(b1 or {})),
        "binfo2": dict({"arrTime": "18:20", "arrDate": "2026-10-05"},
                       **(b2 or {})),
        "extparams": "{}",
    }
    f.update(top)
    return f


def _qn_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows, "样本应产出至少一行"
    return rows[0]


def test_qunar_trans_share_selfref_blocked():
    """末行兜底自引用门：末行号 ∈ 段号集（首段共享+二段常规）→ 不落。

    W-1 标本：mainCarrier 缺席、mixCodeShare=1、末行「东航MU2161」
    恰是本行第二段号——自引用词面宁缺勿落（DB 12/799 误导实证）。"""
    r = _qn_one(_qn_trans_f(
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert "shareCarrier" not in r, r.get("shareCarrier")


def test_qunar_trans_share_maincarrier_truth_wins():
    """真值源：binfo1.mainCarrier='CZ6305'（≠段号集）在主源空时落
    真值——首段实际承运恢复（同班 PC 行先例形态）。"""
    r = _qn_one(_qn_trans_f(
        b1={"mainCarrier": "CZ6305"},
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert r["shareCarrier"] == "CZ6305", r.get("shareCarrier")


def test_qunar_trans_share_maincarrier_own_seg_guarded():
    """真值源自飞防呆：mainCarrier=本行段号（挂自身 id）→ 不落，
    且不回落自引用末行（双门齐拦，对齐 PC 直飞 m4 家族律）。"""
    r = _qn_one(_qn_trans_f(
        b1={"mainCarrier": "3U1599"},
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert "shareCarrier" not in r, r.get("shareCarrier")


def test_qunar_trans_share_second_leg_truth_still_landed():
    """真二段承运保留：末行号 ∉ 段号集（NS8266/MU8801 行末行
    「东航MU2533」）→ 照落（v1590 立案的合法形态，自引用门勿误杀）。"""
    r = _qn_one(_qn_trans_f(
        code="NS8266/MU8801",
        mixCodeShare=1, mixFlightName="河北航NS8266\n\n东航MU2533"))
    assert r["shareCarrier"] == "东航MU2533", r.get("shareCarrier")


def test_qunar_trans_share_named_source_priority_unchanged():
    """主源优先不变：mainCarrierSimpleNameAndNo 有值时压过真值源与
    末行兜底（v1590 既有语义，三档档序锚）。"""
    r = _qn_one(_qn_trans_f(
        b1={"mainCarrierSimpleNameAndNo": "重庆航OQ2311",
            "mainCarrier": "OQ2311"},
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert r["shareCarrier"] == "重庆航OQ2311", r.get("shareCarrier")


def test_qunar_trans_share_non_mixcode_untouched():
    """非 mixCodeShare 行为不变：codeShare 无任何可落源时宁缺
    （v1590「不凭空造源」语义跨档序保留）。"""
    assert "shareCarrier" not in _qn_one(_qn_trans_f())


def test_qunar_trans_share_last_line_no_fno_blocked():
    """兜底门防御档：末行提取不到任何航班号（纯中文词面）同样不落
    ——无法排除自引用，宁缺（旧行为无条件落，防御收紧须有钉）。"""
    r = _qn_one(_qn_trans_f(
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n华夏航空直飞"))
    assert "shareCarrier" not in r, r.get("shareCarrier")


def test_qunar_direct_share_maincarrier_truth_lands():
    """真值档对直飞行同样生效（三档链直飞/中转共路）：code 单段、
    binfo.mainCarrier='FM9224' ≠ code → 落真值（PC 直飞 m4 家族
    同向，回归钉防后续收窄）。"""
    f = {"minPrice": 1200, "code": "MU2771",
         "binfo": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05",
                   "codeShare": 1, "mainCarrierSimpleNameAndNo": "",
                   "mainCarrier": "FM9224"},
         "extparams": "{}"}
    assert _qn_one(f)["shareCarrier"] == "FM9224"


def test_qunar_direct_share_maincarrier_own_code_guarded():
    """直飞真值档自飞防呆：mainCarrier=本班 code（挂自身 id）→
    不落（对齐 PC 直飞 m4 门「mainCarrier≠airCode」）。"""
    f = {"minPrice": 1200, "code": "MU2771",
         "binfo": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05",
                   "codeShare": 1, "mainCarrierSimpleNameAndNo": "",
                   "mainCarrier": "MU2771"},
         "extparams": "{}"}
    assert "shareCarrier" not in _qn_one(f)
