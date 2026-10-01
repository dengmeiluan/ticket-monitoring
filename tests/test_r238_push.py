# -*- coding: utf-8 -*-
"""r238 推送层落地（推送审校 P2-1）：

- WinToast `_plain` 档位转写后双空格回潮（P2-1）：行级空格坍缩
  （:1238）在 `_EMOJI_TIER_WORDS` 转写（:1267）之前执行，转写词
  尾随空格（「真达标 」）+ 原行内空格再叠出双空格——`_alert_body`
  （ntfy/短信/TTS）坍缩在转写后故干净，两路必须同律。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r238_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notifier import WindowsToastNotifier    # noqa: E402


def test_plain_no_double_space_after_tier_transcribe():
    """P2-1 复现钉：KPI 行经 _plain 剥壳+档位转写后不得残留双空格。

    输入形态=真实达标轮 KPI 行（markdown 链接壳 + 🎯 档位点 +
    行内空格）：剥壳坍缩后「🎯 直飞 ￥1710」干净，但转写
    🎯→「真达标 」（尾随空格）与行内空格叠加=「真达标  直飞」。
    """
    desp = "- [**🎯 直飞 ￥1710**](https://example.com/view)　低￥190·10%"
    out = WindowsToastNotifier._plain(desp, 180)
    assert "真达标" in out, out
    assert "  " not in out, "转写后双空格回潮: %r" % (out,)


def test_plain_transcribe_words_multiline_no_double_space():
    """多行混合形态（🎯/🟨 双档行）转写后同样无双空格、无行首空格。"""
    desp = ("- [**🎯 直飞 ￥1710**](https://example.com/a)　线￥1900\n"
            "- [**🟨 中转 ￥2279**](https://example.com/b)　差￥579（34%）")
    out = WindowsToastNotifier._plain(desp, 180)
    assert "真达标" in out and "擦边" in out, out
    for seg in out.split("；"):
        assert "  " not in seg, "双空格残留: %r" % (seg,)
        assert not seg.startswith(" "), "段首空格: %r" % (seg,)
