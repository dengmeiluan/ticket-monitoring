# -*- coding: utf-8 -*-
"""本轮推送层源码钉（推送审校立案 P2-1/P2-2）：

P2-1 @手机号段不进强提醒通道正文：_digest_payload 在 desp 尾追加
「@13800138000 」（钉钉 @ 高亮载体）早于 _send_urgent 分发点，
_alert_body/_plain 过滤清单均无 @ 行——电话/短信 900 字额度被 12 位
手机号占据且 TTS 播报读数字、弹窗尾行同噪音。修法=两处过滤清单各加
一条 @ 前缀判定（与 ⏱/⚠ 同族结构化前缀判定）；@段追加点不动（钉钉
@ 高亮依赖 desp 原文，挪动波及存档/邮件按钮三消费点）。

P2-2 「飞猪(维护中)」旧废弃期残留注删除：fliggy 已循 PC SSR 复活
为现役主力，「维护中」语义=官方下线预期管理，健康渠道 round-miss
（限流单轮缺失）被误标维护态会把读者导向「渠道废弃」的错误预期
（实况=下轮自然回）。ops_notes 组装抽为 _ops_notes 方法（难测=设计
信号，行为测试随抽取可写）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15111_push.py -q
"""
import logging
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rsrc():
    return open(os.path.join(_BASE, "report.py"), encoding="utf-8").read()


def test_risk_slot_in_table_png():
    """ctrip 高风险政策透明标记入总表图决策次行（三端协议渲染门
    收口：爬虫键 ↔ webui 白名单/价格格徽标 ↔ PNG 槽——agePolicy
    同族「能不能买/买了有何风险」决策词三处全落，缺 PNG 槽=推送图
    面缺失该信号、图内信息容量低于被撤文本版）。PNG 端无 ⚠：
    U+26A0 在 msyh 无字形渲染 tofu 方框（E-1 同律），词面自带
    「高风险」醒目字。"""
    src = _rsrc()
    assert '("risk", str(f.get("riskPolicy") or "").strip())' in src, \
        "riskPolicy 未入总表图次行（三端渲染门缺角）"
    assert "⚠{f['riskPolicy']}" not in src, "PNG 端 ⚠ 残留（tofu 方框）"


def test_drop_chain_last_tier_drops_risk():
    """超宽极端行 risk 入末档丢档链：与 labels/age 同族增益词
    （「高风险政策」5 全角恒占槽），五档全败的极端超宽行若不入链
    则直接回退单行整截、恒保组（准点/餐食/托运/共享/余票）一并
    蒸发——丢增益词保恒保组，次行仍可决策。"""
    src = _rsrc()
    # 正则容忍元组换行/空白变化（源码串钉的格式化敏感面）；
    # tkrisk（「临近起飞需确认值机」8 全角）与 age/risk 同族增益词，
    # r248 随槽位扩员入末档丢档链
    assert re.search(
        r'"labels",\s*"age",\s*"risk",\s*"tkrisk",\s*"carryon', src), \
        "丢档链末档未含 risk/tkrisk（超宽行恒保组被整截）"


def test_alert_body_filters_at_mobile():
    """强提醒正文（电话/短信/ntfy）滤 @手机号 行：TTS 不读 12 位数字，
    900 字额度不被占；价格主判据行保留。"""
    from core.notifier import _alert_body
    desp = ("#### 🚨 达标！上→乌 10/06 直飞 ￥1264\n\n"
            "直飞 **￥1264**　线￥1900　差￥636\n\n"
            "@13800138000 ")
    body = _alert_body(desp)
    assert "13800138000" not in body, body
    assert "￥1264" in body, body


def test_wintoast_plain_filters_at_mobile():
    """Windows 弹窗第二行同样滤 @手机号 行（尾行噪音）。"""
    from core.notifier import WindowsToastNotifier as W
    p = W._plain("🚨 达标！上→乌 10/06\n\n直飞 **￥1264**\n\n@13800138000 ",
                 200)
    assert "13800138000" not in p, p
    assert "￥1264" in p, p


def test_ops_note_fliggy_not_maintaining():
    """fliggy round-miss 无数据：词面=「飞猪」不带「(维护中)」括注——
    PC SSR 复活后维护态语义已失真（限流单轮缺失=下轮自然回）。"""
    from core.alerter import Alerter
    al = Alerter(logging.getLogger("t15111"))
    route = SimpleNamespace(from_name="上海", to_name="乌鲁木齐")
    rs = [(route, [{"date": "2026-10-06",
                    "seen_plats": ["ctrip", "qunar", "tuniu",
                                   "tongcheng"]}])]
    notes = al._ops_notes(rs)
    assert notes and "飞猪" in notes[0], notes
    assert "维护中" not in notes[0], notes


def test_ops_note_mixed_keeps_others_plain():
    """其他渠道名照常直出（括注删除不得伤及词表主体）。"""
    from core.alerter import Alerter
    al = Alerter(logging.getLogger("t15111"),
                 platforms=["ctrip", "qunar", "tuniu", "tongcheng",
                            "fliggy"])
    route = SimpleNamespace(from_name="上海", to_name="乌鲁木齐")
    rs = [(route, [{"date": "2026-10-06", "seen_plats": []}])]
    notes = al._ops_notes(rs)
    assert notes, notes
    for p in ("携程", "去哪儿", "途牛", "同程", "飞猪"):
        assert p in notes[0], (p, notes)
    assert "维护中" not in notes[0], notes
