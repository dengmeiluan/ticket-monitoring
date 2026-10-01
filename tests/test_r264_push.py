# -*- coding: utf-8 -*-
"""推送层两案（波3 推送审校立案 P2/P3-1）：

P2 「行情价」行3 注词面脱裸字面量：alerter KPI 行3 兜底注
l3_note = "行情价" 是生产代码唯一裸档位词字面量，与
TIER_TRANSCRIBE["mkt"]（转写表）值耦合——词面改版日转写表
改了、行3 注仍旧词，ntfy/短信/TTS 侧「转写词+行情价」叠词
静默复发（剥注表 _MKT_NOTE_DUPS 按「行情价」剥注，两词面
同值时剥得净；分叉后剥注失配=纯文本通道残留）。收编为投影
引用：l3_note 直接消费 TIER_TRANSCRIBE["mkt"].strip()（与
_MKT_NOTE_PAREN L106 同形态），词面改版日自动跟随。

P3-1 走势图达标虚线词条：直飞达标虚线 C_TH 与比价警示红
C_CMP 同值（194,42,46），同图内「红=参考线+红=▼回落事件」
两义并存，图内点环小注此前只解码 ▼红——补「红虚线=直飞
达标线」词条进同一循环（C_TH_T 棕金虚线无歧义不入注）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r264_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.alerter as A  # noqa: E402


def test_l3_note_literal_single_source():
    """源码钉：带 ASCII 双引号的「行情价」字面量在 alerter 源内
    只剩 _TIER_TABLE 转写词列定义一处（count==1）；行3 注赋值
    形态必须是 TIER_TRANSCRIBE 投影（运行时求值，词面改版日
    monkeypatch/改表自动跟随——裸字面量则两处分叉）。注释与
    中文引号「」形态不进计数（LESSONS 二十§10：计数钉锁声明
    枚举，注释不是声明）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count('"行情价"') == 0, (
        "「行情价」裸字面量残留：行3 注必须消费 "
        "TIER_TRANSCRIBE[\"mkt\"].strip() 投影，与转写表同源"
        "（词面改版日叠词静默复发族）")
    assert src.count('"行情价 "') == 1, (
        "转写表 mkt 行定义缺席或漂移（带尾空格的词面恰定义一处）")
    assert 'l3_note = TIER_TRANSCRIBE["mkt"].strip()' in src, (
        "行3 注赋值未走 TIER_TRANSCRIBE 投影（与 _MKT_NOTE_PAREN "
        "同形态的单源引用）")


def test_mkt_note_paren_derived_from_transcribe():
    """行为钉（Soldier P2-1 改写）：_MKT_NOTE_PAREN 是 import 期
    绑定的模块常量，锁「常量由转写表投影派生」的等式——改表词面
    而忘改派生式（或退化为裸字面量手抄）时本钉红。l3_note 本体
    深埋嵌套函数无独立入口（直调不可达），其单源性由源码钉
    （前一颗锁赋值形态）承担——此处不重复锁不可达面。"""
    assert A._MKT_NOTE_PAREN == "（" + A.TIER_TRANSCRIBE["mkt"].strip() + "）", (
        "_MKT_NOTE_PAREN 与转写表投影分叉：常量必须由 "
        "TIER_TRANSCRIBE[\"mkt\"].strip() 派生（词面改版日只改表）")


def test_trend_ring_note_red_dash_entry():
    """源码钉：走势图点环分档小注循环内补「红虚线」词条——
    直飞达标虚线（C_TH）与 ▼红回落（C_CMP）同值同图两义，
    小注是图面唯一解码位。词条必须与点环注同一循环产出
    （分散第二绘制点=两处维护面），计数==1 且落在
    「=TIER_FULL['fall']」行之后的同一语句切片内。"""
    src = open("report.py", encoding="utf-8").read()
    assert src.count("红虚线") == 1, (
        "「红虚线」词条缺席或分散：达标虚线两义解码必须收在"
        "点环小注单循环内")
    fall_i = src.index("={TIER_FULL['fall']}")
    seg = src[fall_i:fall_i + 300]
    assert "红虚线" in seg, (
        "「红虚线」词条未落在点环小注循环内（散落第二绘制点）")
