# -*- coding: utf-8 -*-
"""r244 数据层：qunar totalDuration 词面归一（H5 英文词面 + PC 整小时 '5h'）。

D-1（r244 渠道调研 A + 数据观测双立案，before 基线在 _scratch/r244_obs.md）：
- H5 出口 `_extract_flights_obj` 的 totalDuration 直接透传顶层 transTime
  原始词面——本代窗中转行 416/416=100% 英文词面（'25h40m' 主形 389 +
  '5h' 整小时形 27；起点 2026-09-21，与 DB 保留窗同寿），数值全对
  （复算矛盾 0）纯词面缺陷。消费端 normalize 有同型归一（'29h55m'
  →'X时YY分'），但 DB/CSV/API dur 面原词面出场。
- PC 直飞/经停分支 `re.sub(r"(\\d+)h(\\d+)m", ...)` 对整小时词面 '5h'
  不命中（窗内 340 item）——同族英文词面缺口。

修复：两处出口统一走 dur_min→fmt_dur 单源归一（unparseable 原样保留，
不收紧落键面）；与 PC 重建路径/DOM 兜底路径的 'X时YY分' 词面对齐。

样本形态取自 r244_obs before 基线 + test_core_units._PC_SAMPLE 同构。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r244_fields.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


def _h5_trans(**top):
    """H5 中转行最小形态：info=binfo1、顶层 transTime 英文词面（缺陷态）。"""
    f = {
        "minPrice": 1200, "code": "3U1599/MU2161",
        "transTime": "25h40m",
        "binfo1": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05"},
        "binfo2": {"arrTime": "18:20", "arrDate": "2026-10-05"},
        "extparams": "{}",
    }
    f.update(top)
    return f


def _h5_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows, "样本应产出至少一行"
    return rows[0]


# ---- H5 出口：词面归一 ----

def test_qunar_h5_td_en_word_normalized():
    """中转行顶层 transTime='25h40m'（本代 416/416 缺陷态）→ 归一
    '25时40分'（与 binfo1.transTime 中文真值逐行值等形异）。"""
    assert _h5_one(_h5_trans())["totalDuration"] == "25时40分"


def test_qunar_h5_td_whole_hour_normalized():
    """整小时形 '5h'（观测窗 27 条）→ '5时00分'（fmt_dur 统一形态）。"""
    assert _h5_one(_h5_trans(transTime="5h"))["totalDuration"] == "5时00分"


def test_qunar_h5_td_unparseable_preserved():
    """unparseable 词面原样保留（归一只换形不造值：'1天2时' 渠道口径
    _dur_min 不认 → 透传，宁存原词勿丢值）。"""
    assert _h5_one(_h5_trans(transTime="1天2时"))["totalDuration"] == "1天2时"


def test_qunar_h5_td_absent_not_landed():
    """无值不落语义跨归一保留：transTime 与 info.totalDuration 双缺
    → 键不落（r241 空串收口钉回归）。"""
    f = _h5_trans()
    f.pop("transTime")
    assert "totalDuration" not in _h5_one(f)


def test_qunar_h5_td_chinese_unpadded_padded():
    """中文非填充形 '3时5分' → 统一 '3时05分'（直飞行已是中文词面，
    归一对齐 PC 重建/DOM 兜底路径的 fmt_dur 形态）。"""
    assert _h5_one(_h5_trans(transTime="3时5分"))["totalDuration"] == "3时05分"


# ---- PC 出口：直飞/经停分支整小时词面 ----

def _pc_direct(flight_time):
    return __import__("json").dumps({
        "ret": True, "data": {"flights": [
            {"code": "FM9223", "minPrice": "2472", "transCity": "",
             "transTime": "",
             "binfo": {"airCode": "FM9223", "shortName": "上航",
                       "name": "上海航空", "depTime": "19:55",
                       "arrTime": "01:25", "date": "2026-10-05",
                       "arrDate": "2026-10-06",
                       "flightTime": flight_time}},
        ]}}, ensure_ascii=False)


def test_qunar_pc_direct_whole_hour_normalized():
    """PC 直飞行 flightTime='5h'（窗内 340 item 缺陷态）→ '5时00分'
    （旧 re.sub 不命中原样透传英文词面）。"""
    out = QunarCrawler._parse_pc_flights(_pc_direct("5h"), "2026-10-05")
    assert out and out[0]["totalDuration"] == "5时00分", out


def test_qunar_pc_direct_standard_unchanged():
    """标准形 '5h30m' 行为不变（旧 re.sub 已归一的形态，回归钉）。"""
    out = QunarCrawler._parse_pc_flights(_pc_direct("5h30m"), "2026-10-05")
    assert out and out[0]["totalDuration"] == "5时30分"


def test_qunar_pc_direct_garbage_flighttime_dropped():
    """flightTime 不可解析词面 → 不落键（旧 re.sub 透传垃圾词面落库；
    归一后 _fd(_dm(garbage))='' 走无值不落，宁缺勿错）。"""
    out = QunarCrawler._parse_pc_flights(_pc_direct("N/A"), "2026-10-05")
    assert out and "totalDuration" not in out[0]
