# -*- coding: utf-8 -*-
"""r1600：人工停手必须在页面上可见（写在状态列），并给一键恢复。

现场：给携程/飞猪设了 12 小时停手后，节流行读的是
`PACESTRAT.channels[k].halt`，而停手表在**顶层** `halt[plat]` → 恒为 null：
「它为什么不动」只能翻日志，「停手」按钮也不隐藏（点下去是重复停手）。

**为什么写在状态列**：第一版把 chip 放在渠道名旁边，实测把「携程」挤成
「携..」（名称被 ellipsis 截断）——状态列本来就是「这行怎么了」的位置。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_pace_row_reads_top_level_halt():
    w = _w()
    assert "PACESTRAT.halt&&PACESTRAT.halt[k]" in w, \
        "节流行没有从顶层 halt 读停手状态（旧写法 channels[k].halt 恒为 null）"
    assert "PACESTRAT.channels&&PACESTRAT.channels[k]||{}).halt" not in w, \
        "还在读 channels[k].halt——那永远是 null"


def test_halted_row_writes_status_column():
    w = _w()
    # r1618：状态列只有 ~70px，完整句「停手 · 剩 629 分钟」在 900/1200 档
    # 被 ellipsis 裁掉（实测）。按数量级压成「停手 10h」「停手 42m」。
    assert "'\u505c\u624b '" in w, "\u505c\u624b\u884c\u6ca1\u6709\u5728\u72b6\u6001\u5217\u5199\u5269\u4f59\u65f6\u957f"
    assert "const _lab=_haltNow" in w, (
        "\u6ca1\u6709\u6309\u505c\u624b\u72b6\u6001\u8986\u76d6\u72b6\u6001\u5217\u6587\u6848")
    assert "const _tone=_haltNow" in w, (
        "\u505c\u624b\u72b6\u6001\u6ca1\u6709\u4e2d\u6027\u8272")


def test_chip_must_not_squeeze_channel_name():
    w = _w()
    assert "nm-halt" not in w, (
        "又把停手 chip 塞进渠道名里了：实测会把「携程」挤成「携..」")


def test_halted_row_offers_resume():
    w = _w()
    assert ":resume" in w, "停手行没有「恢复」按钮"
    assert "paceResume(this," in w, "「恢复」没有接到 paceResume"


def test_halt_state_triggers_one_repaint():
    w = _w()
    assert "PACE_HALT_SIG" in w, \
        "没有按停手表签名补一次重绘：首绘时 /api/strategy 还没回来，停手会缺一拍"


def test_halt_duration_is_compact():
    w = _w()
    assert "+'h'" in w and "+'m'" in w, (
        "\u505c\u624b\u65f6\u957f\u6ca1\u6709\u6309\u6570\u91cf\u7ea7\u538b\u7f29\uff08\u4f1a\u5728 900/1200 \u6863\u88ab\u88c1\uff09")
