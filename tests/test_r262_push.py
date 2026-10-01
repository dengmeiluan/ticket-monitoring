# -*- coding: utf-8 -*-
"""r262 推送层两案（调研 _scratch/r262_audit_push.md P3-1/P3-2）：

P1 「*行情」短注词面单源化：产出侧（KPI 降级链 forms、破线尾注）与
剥段消费（_mini_split 去短注档）三处各自手抄字面量——词面改版日
剥段档匹配串与产出词面分叉，剥段静默失效（不炸、不留痕，只在
「该行超宽需要剥段」的触发档显形；LESSONS 十六§3b 同源律）。
收编为 _MKT_NOTE 常量：源码钉锁字面量零残留，行为钉锁剥段消费
与常量同源（monkeypatch 常量后剥段跟随）。

P2 混合池边界注释补全：纯注释零行为，由全量回归兜底。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r262_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.alerter as A  # noqa: E402


def test_mkt_note_literal_zero_residual():
    """源码钉：「*行情」带引号字面量零残留——三处消费点全部走
    _MKT_NOTE 单源（裸字面量残留计数钉，count==0 即只剩定义式
    "*" + _MKT_SHORT）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert '"*行情"' not in src, (
        "「*行情」短注字面量残留：产出与剥段消费必须同出 _MKT_NOTE 单源"
        "（词面改版日剥段档静默失效族，LESSONS 十六§3b）")
    assert src.count("_MKT_NOTE") >= 4, (
        "_MKT_NOTE 定义+消费点不足（期望定义 1 处+消费 ≥3 处）")


def test_mini_split_strip_follows_mkt_note_constant(monkeypatch):
    """行为钉：剥段消费与 _MKT_NOTE 同源——常量改版（模拟词面改版日）
    后 _mini_split 去短注档剥掉的是新词面，不残留。旧形态（字面量
    手抄）下 monkeypatch 不生效，「*促」残留进输出。"""
    monkeypatch.setattr(A, "_MKT_NOTE", "*促")
    # 样本按真实计宽函数网格探找（手算不当作依据）：原样超宽、剥新
    # 词面达标，两段各自 head+seg ≤40——坏形态走拆行档时 seg_b 完整
    # 保留，「*促」不会被地板截吃掉（防截断假绿）；具体宽度以自证
    # 断言为准，注释不锚数字
    seg_a = "甲" * 10
    seg_b = "🟩直飞￥1200" + A._MKT_NOTE
    head = "D2"
    line = head + " ｜ ".join([seg_a, seg_b])
    no_note = head + " ｜ ".join(
        [seg_a, seg_b.replace(A._MKT_NOTE, "")])
    assert A._disp_dw(line) > 40, "样本未进降级面（原样须超宽）"
    assert A._disp_dw(no_note) <= 40, "样本未卡「去短注档」（剥注后须达标）"
    assert A._disp_dw(head + seg_a) <= 40 and A._disp_dw(head + seg_b) <= 40
    out = A._mini_split(head, [seg_a, seg_b])
    assert "*促" not in out, (
        "去短注档未跟随 _MKT_NOTE 常量：剥段消费与产出词面分叉"
        "（触发档显形族：该行超宽时短注剥不掉，随拆行/截断路径烂尾）")


def test_mkt_note_family_cross_module_single_source():
    """Soldier Major-1 收口钉：「（行情价）」与「*行情」两词面的跨模块
    手抄收编——产出（alerter 降级链 / report 日报 KPI 尾注）与剥注
    消费（notifier _MKT_NOTE_DUPS，ntfy/短信/TTS 纯文本通道转写前
    共用）同出 alerter 投影单源；跨模块手抄在词面改版日静默分叉
    （剥注表失配=纯文本通道残留营销注，且钉旧字面量的测试不会红）。
    收编是引用改写：四元组值面逐字节不变（行为零差由全量回归背书）。"""
    a_src = open("core/alerter.py", encoding="utf-8").read()
    n_src = open("core/notifier.py", encoding="utf-8").read()
    r_src = open("report.py", encoding="utf-8").read()
    for tag, src in (("alerter", a_src), ("notifier", n_src), ("report", r_src)):
        assert '"（行情价）"' not in src, (
            "%s 手抄「（行情价）」字面量残留：须走 _MKT_NOTE_PAREN 单源" % tag)
    assert '"*行情"' not in n_src, (
        "notifier 剥注表手抄「*行情」残留：须引用 alerter._MKT_NOTE")
    import core.alerter as A2
    import core.notifier as N
    assert A2._MKT_NOTE_PAREN == "（行情价）"
    assert N._MKT_NOTE_DUPS == ("（行情价）", "*行情", "行情价", "行情破线"), (
        "_MKT_NOTE_DUPS 值面漂移：收编不得改变四元组值")
