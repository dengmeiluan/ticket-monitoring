# -*- coding: utf-8 -*-
"""r655：渠道清单必须只有一个事实源，否则加渠道必然漏改。

`APP_CHANNELS` 曾在三处各写一份（crawlers/__init__、core/pacing、
core/health_diag）。加第二个 App 渠道时漏改一处，就是「渠道能采但不在
节流表里 / 不进诊断卡 / 界面露裸 id」的静默缺陷——能跑，但少一半功能。

为什么当时各写一份：crawlers 依赖 core，core 再 import crawlers 会循环。
解法是抽出零依赖的 core/channels.py，三方都从它取。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_all_sides_share_one_tuple():
    import crawlers
    from core import channels, health_diag, pacing
    assert crawlers.APP_CHANNELS == channels.APP_CHANNELS
    assert pacing.APP_CHANNELS == channels.APP_CHANNELS
    assert health_diag.APP_CHANNELS == channels.APP_CHANNELS


def test_health_diag_cn_has_every_app_channel():
    """每个 App 渠道都要有中文名，否则界面显示裸 id。"""
    from core import channels, health_diag
    for p in channels.APP_CHANNELS:
        assert health_diag.CN.get(p), "%s 在诊断卡里没有中文名" % p


def test_no_second_hardcoded_app_list():
    """源码里不得再出现第二份写死的 App 渠道元组。"""
    for rel in ("core/pacing.py", "core/health_diag.py"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8",
                      newline="").read()
        assert 'APP_CHANNELS = ("app_zhixing"' not in src, (
            "%s 里又写死了一份渠道清单，加渠道时会漏改" % rel)


def test_channels_module_is_dependency_free():
    """core/channels.py 只放常量：一旦它 import 项目内模块就会重新引入
    core → crawlers → core 的循环。"""
    import re
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8", newline="").read()
    # 只看真正的 import 语句（注释里提到路径是允许的）
    for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M):
        mod = m.group(1)
        assert not mod.startswith("crawlers") and not mod.startswith("core"), (
            "core/channels.py 不应依赖项目内模块：%s" % mod)


def test_browser_and_app_sets_do_not_overlap():
    from core import channels
    assert not (set(channels.BROWSER_CHANNELS) & set(channels.APP_CHANNELS))
