# -*- coding: utf-8 -*-
"""r1063 T272：双端登录弹窗里 **PC lane 必须在 H5 之前**。

用户原话：「途牛和同程的弹窗登录现在默认全部到 h5 页面了，原来不是 pc 吗」。
统一成双端后，四家（携程/飞猪/同程/途牛）的弹窗都要**先给 PC、再给 H5**，
否则用户第一眼看到 H5，会以为「再也回不到 PC 了」。

真机已验（同程）：`PC=True H5=True PC在前=True`，按钮为「重新登录 / 立即核验」。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_pc_lane_listed_before_h5_for_all_dual_channels():
    w = _w()
    i = w.index("const LG_DUAL={")
    seg = w[i:w.index("};", i)]
    for plat in ("ctrip", "fliggy", "tongcheng", "tuniu"):
        m = re.search(r"%s:\{[^}]*\}" % plat, seg)
        assert m, "LG_DUAL 缺 %s" % plat
        block = m.group(0)
        ipc = block.find("pc:")
        ih5 = block.find("h5:")
        assert ipc >= 0 and ih5 >= 0, "%s 必须同时有 pc/h5" % plat
        assert ipc < ih5, "%s 的 PC lane 必须排在 H5 之前" % plat


def test_dual_modal_title_says_two_sides():
    w = _w()
    i = w.index("const LG_DUAL={")
    seg = w[i:w.index("};", i)]
    assert seg.count("双端登录") >= 4, "四家的标题都要写清「双端」"
    assert "会话不共享" in seg, "要说明两端会话不共享（否则用户以为登录一次就够）"
