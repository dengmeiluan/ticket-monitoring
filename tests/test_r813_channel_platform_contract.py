# -*- coding: utf-8 -*-
"""r813：渠道平台能力契约（N 维）——7 家渠道 × 11 条质量轴无缺口。

这不是又一份能力声明表：每一格都去读真实登记点（REGISTRY / 健康卡 /
诊断卡 / 雷达 / 告警 / 演示 / 前端表 / 官方图标 / flight_daily 主键 /
门禁文件），改了实现这里就会变。它回答用户点名的那组问题：

    可配置 可观测 可干预 可见性 可溯源 可识别 可区分
    可幂等 语义清晰 可指导 可判断

三条硬约束：
1. 当前接线必须**零 n**（否则新渠道接线漏项会被放行）；
2. 判据必须能被打红——幽灵渠道、删中文名、把渠道踢出雷达，
   对应格必须变红（负控在下面，不是靠「之前跑绿过」）；
3. 报告用中文轴名 + 渠道 id，能直接指着说「缺哪一格」。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.channel_contract as cc  # noqa: E402
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, CHANNEL_CN  # noqa: E402

ALL = tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)


def test_axes_cover_every_requested_quality():
    """用户点名的 11 条一条不少，顺序稳定（文档/报告都按这个顺序读）。"""
    assert cc.AXIS_IDS == (
        "configurable", "observable", "intervenable", "visible",
        "traceable", "identifiable", "distinguishable", "idempotent",
        "semantics", "actionable", "judgeable",
    )
    assert len(set(cc.AXIS_CN.values())) == len(cc.AXIS_IDS), "中文名必须唯一"


def test_every_registered_channel_has_every_axis():
    matrix = cc.audit_all()
    assert set(matrix) == set(ALL)
    for plat, row in matrix.items():
        assert set(row) == set(cc.AXIS_IDS), plat
        for axis, cell in row.items():
            assert cell.state in (cc.Y, cc.N, cc.NA), (plat, axis, cell.state)
            assert cell.detail, (plat, axis)


def test_current_wiring_has_no_gap():
    """新增渠道时最先红的就是这条：报告会点名缺哪一格、看哪里。"""
    g = cc.gaps()
    assert not g, "渠道平台契约出现缺口：\n" + cc.render_text()


def test_report_is_human_readable():
    text = cc.render_text()
    for plat in ALL:
        assert plat in text
    for cn in cc.AXIS_CN.values():
        assert cn[:4] in text, cn
    assert "缺口" in text or "无缺口" in text


def test_ghost_channel_is_reported_not_silently_green():
    """负控①：未登记渠道不能因为「函数不抛异常」就算通过。"""
    row = cc.audit("ghost_app")
    red = [a for a, c in row.items() if c.state == cc.N]
    assert set(red) >= {"configurable", "observable", "intervenable",
                        "visible", "traceable", "identifiable",
                        "distinguishable", "idempotent", "semantics",
                        "judgeable"}, red
    assert "ghost_app" in cc.render_text({"ghost_app": row})


def test_missing_chinese_name_is_a_gap(monkeypatch):
    """负控②：删掉中文名，可识别格必须红（而不是兜底成裸 id 也算过）。"""
    monkeypatch.delitem(CHANNEL_CN, "app_qunar")
    matrix = cc.audit_all()
    cell = matrix["app_qunar"]["identifiable"]
    assert cell.state == cc.N, cell
    assert "中文名" in cell.detail


def test_channel_hidden_from_radar_is_a_gap(monkeypatch):
    """负控③：把智行踢出雷达白名单（本次修的真实缺陷），可见性格必须红。"""
    import core.special_radar as radar
    monkeypatch.setattr(
        radar, "_CHANNELS",
        tuple(p for p in radar._CHANNELS if p != "app_zhixing"))
    matrix = cc.audit_all()
    cell = matrix["app_zhixing"]["visible"]
    assert cell.state == cc.N, cell
    assert "特价雷达" in cell.detail


def test_advice_without_landing_is_a_gap(monkeypatch):
    """负控④：建议只有英文动作、没有中文说明 → 可指导格必须红。"""
    import core.pacing as pacing
    monkeypatch.setattr(
        pacing, "advise",
        lambda *a, **k: {"state": "login", "action": "relogin",
                         "hint": "", "severity": "act"})
    matrix = cc.audit_all()
    cell = matrix["ctrip"]["actionable"]
    assert cell.state == cc.N, cell


def test_semantics_rejects_illegal_tristate(monkeypatch):
    """负控⑤：把某维改成 y/n/"" 之外的值 → 语义清晰格必须红。"""
    import core.channels as ch
    row = dict(ch.CHANNEL_DIMENSIONS["tuniu"])
    row["calendar"] = "yes"
    matrix = dict(ch.CHANNEL_DIMENSIONS)
    matrix["tuniu"] = row
    monkeypatch.setattr(ch, "CHANNEL_DIMENSIONS", matrix)
    cells = cc.audit_all()
    assert cells["tuniu"]["semantics"].state == cc.N


def test_browser_platform_lists_are_aliases_not_copies():
    """浏览器渠道清单只能有一个对象：节奏/诊断/入口板不得再手抄一份。

    r813 前这三处各写一份 `("ctrip","qunar","fliggy","tongcheng","tuniu")`；
    加渠道时漏改任意一处，就出现「能采但不在节流表/诊断卡/入口板」。
    用 `is` 而不是 `==`：相等的副本同样会在下次加渠道时漂移。
    """
    import core.channel_links as links
    import core.health_diag as diag
    import core.pacing as pacing
    from core.channels import BROWSER_CHANNELS
    assert pacing.PLATFORMS is BROWSER_CHANNELS
    assert diag.PLATFORMS is BROWSER_CHANNELS
    assert links.PLATS is BROWSER_CHANNELS


def test_crawler_app_channels_is_the_same_object():
    """`crawlers.APP_CHANNELS` 必须是 core 那份本身，不能是副本。

    bootstrap（设备引导）读的是 crawlers 这份；新增 App 渠道只改 core 时，
    副本会让新渠道「能采但设备引导永远不认」。
    """
    import crawlers
    from core.channels import APP_CHANNELS
    assert crawlers.APP_CHANNELS is APP_CHANNELS


def test_probe_picker_is_counted_as_a_visible_surface():
    """检索页的主动探针也是渠道可见面：后端收 7 家，picker 不能只给 5 个。"""
    matrix = cc.audit_all()
    for p in ALL:
        cell = matrix[p]["visible"]
        assert cell.state == cc.Y, (p, cell)
        assert "主动探针" in cell.detail, (p, cell.detail)
    # 负控：picker 缺一款 App 时 helper 必须报出来
    ok, detail = cc._probe_picker_covers(
        '<div id="srxPlatPick"><label data-p="ctrip"></label></div>',
        ("ctrip", "app_qunar"))
    assert not ok and "app_qunar" in detail, (ok, detail)


def test_strict_mode_fails_on_gap(monkeypatch, capsys):
    """CLI 的 --strict 必须把缺口变成非零退出码（发版前可串进流程）。"""
    monkeypatch.setattr(sys, "argv", ["channel_contract", "--strict"])
    monkeypatch.setattr(cc, "gaps", lambda *a, **k: [("ctrip", "visible", "x")])
    assert cc.main() == 1
    out = capsys.readouterr().out
    assert "缺口 1 处" in out or "[可配置] ctrip" in out, out
