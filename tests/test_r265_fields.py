# -*- coding: utf-8 -*-
"""r265 渠道字段：fliggy「换航站楼」后缀断锚修复（R1，本轮调研唯一真候选）。

证据（_scratch/research_r265_ch2.md §3 + observe_r265 §1 + 主修 dump
行级回放亲核）：10-15 dump 行 33（BK2934+9C8946 西安中转）渠道新增
`<label class="change-terminal">换航站楼</label>`，与 transfer-city-label
同 div 兄弟，行文本实证为「西安中转 换航站楼」（两 label 间空白节点
渲染成单空格）——击碎定证锚 `^([一-鿿]{2,8})中转$`（crawlers/fliggy.py
定证行）：唯一跨楼行整行丢失（transDepTerminal 唯一载体），孤儿 pend
与相邻块首段拼成嵌合脏行（10-07 生产 13 轮实录 code=9C8946/9C7372，
错误航班组合+正确时刻价的伪装行）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r265_fields.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("t265")

# 双中转块：块 1 定证行带「换航站楼」后缀（渠道 change-terminal label
# 与城市 label 同 div 兄弟，10-15 dump 行文本实证为「西安中转 换航站楼」
# ——两 label 间空白节点渲染成单空格）；块 2 正常行——修复前块 1 整行
# 丢失、其孤儿首段污染块 2 的合并配对（生产 13 轮嵌合实录）。
_CHANGE_TERMINAL_TXT = "\n".join([
    # 块 1：BK2776 + FM9402，长沙中转（跨楼行）
    "奥凯BK2776", "中型机 738",
    "上航FM9402", "中型机 738",
    "10月15日 15:15", "10月15日 19:05",
    "10月16日 06:05", "10月16日 07:55",
    "乌鲁木齐天山国际机场", "长沙中转 换航站楼", "黄花国际机场T1",
    "¥2060 5.0折", "订票",
    # 块 2：HU7149 + MF8215，兰州中转（正常形态）
    "海航HU7149", "中型机 738",
    "春运MF8215", "中型机 738",
    "10月15日 20:15", "10月15日 22:45",
    "10月16日 09:05", "10月16日 11:05",
    "黄花国际机场T2", "兰州中转", "中川国际机场",
    "¥1870 4.2折", "订票",
])


def _codes(rows):
    return [r.get("code") for r in rows]


def test_fliggy_change_terminal_block_recovered():
    """带「换航站楼」后缀的中转定证行照常定证入库：块 1 行找回
    （code=A/B 合串、transCity=长沙），块 2 不受污染，无第三行。"""
    rows = FliggyCrawler._parse_pc_text(_CHANGE_TERMINAL_TXT, "2026-10-15")
    assert _codes(rows) == ["BK2776/FM9402", "HU7149/MF8215"], _codes(rows)
    assert rows[0]["transCity"] == "长沙"
    assert rows[1]["transCity"] == "兰州"


def test_fliggy_change_terminal_cross_terminal_landed():
    """跨楼真值找回：transfer_map 双 p1 配对照常落 transTerminal/
    transDepTerminal（该 label 是 transDepTerminal 唯一载体）。"""
    rows = FliggyCrawler._parse_pc_text(
        _CHANGE_TERMINAL_TXT, "2026-10-15",
        transfer_map={"BK2776": ("黄花机场T1", "黄花机场T2 起飞")})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert rows[0]["transDepTerminal"] == "黄花T2"


def test_fliggy_change_terminal_suffix_not_landed():
    """「换航站楼」词面零增量不落键：跨楼事实由 transTerminal≠
    transDepTerminal 派生（既有出口承载），不新增词面键。
    （配套性质声明：本钉为卫生钉非回归检测钉——回退修复时该行
    整行丢弃、词面同样不入行，本钉不红；行找回的回归检测由
    test_fliggy_change_terminal_block_recovered 承载。）"""
    rows = FliggyCrawler._parse_pc_text(
        _CHANGE_TERMINAL_TXT, "2026-10-15",
        transfer_map={"BK2776": ("黄花机场T1", "黄花机场T2 起飞")})
    assert "换航站楼" not in str(rows[0])


def test_fliggy_change_terminal_glued_variant():
    """无空格拼行变体（两 label 间无空白节点的渲染形态）同样定证：
    后缀容忍空白可有可无，两种词形都不得断锚。"""
    txt = _CHANGE_TERMINAL_TXT.replace("长沙中转 换航站楼",
                                       "长沙中转换航站楼")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-15")
    assert _codes(rows) == ["BK2776/FM9402", "HU7149/MF8215"], _codes(rows)
    assert rows[0]["transCity"] == "长沙"


# R1 第二断锚（dump origin-no=36 行级实证）：中转二段行头带「经停」
# 后缀（「吉祥HO1068 经停」）——_RE_FNO 行尾 $ 前不容后缀 → 二段行头
# 不识别 → cur 停留首段 → 「兰州中转」定证合并 pend(孤儿)/cur(首段)
# 产嵌合（修复前与断锚一复合成生产 13 轮脏行），无孤儿时产首段单段
# 半截行（DB 存量 158 元素慢性族根因，fliggy 特有、tongcheng 同形为 0）。
_STOPOVER_LEG_TXT = "\n".join([
    "春秋9C7372", "中型机 320 无餐食",
    "吉祥HO1068 经停", "中型机 320 有餐食",
    "10月15日 15:00", "10月15日 18:00",
    "10月15日 19:45", "10月16日 00:30",
    "乌鲁木齐天山国际机场", "兰州中转", "浦东国际机场T2",
    "¥822 2.0折", "订票",
])


def test_fliggy_stopover_suffix_second_leg_pairing():
    """二段行头「经停」后缀照常识别行头：A/B 配对成中转行（code 合串/
    transCity/时刻链/餐食仲裁全链真值），stopover 落键与机型行经停
    同值域（True）。"""
    rows = FliggyCrawler._parse_pc_text(_STOPOVER_LEG_TXT, "2026-10-15")
    assert _codes(rows) == ["9C7372/HO1068"], _codes(rows)
    r = rows[0]
    assert r["transCity"] == "兰州"
    assert r["stopover"] is True
    assert r["depTime"] == "15:00" and r["arrTime"] == "00:30"
    assert r["lay2dep"] == "19:45"
    assert r["meal"] == "无餐食"   # 两段异值保守仲裁（L471-475 既有语义）


def test_fliggy_stopover_suffix_direct_leg():
    """直飞行头带「经停」后缀同样识别：stopover 落键，行不丢。"""
    txt = "\n".join([
        "川航3U8880 经停", "中型机 320 有餐食",
        "08:00", "12:30",
        "乌鲁木齐天山国际机场", "上海虹桥国际机场T2",
        "¥980 3.2折", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-15")
    assert len(rows) == 1 and rows[0]["code"] == "3U8880"
    assert rows[0]["stopover"] is True
