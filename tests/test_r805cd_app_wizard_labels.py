# -*- coding: utf-8 -*-
"""r805cd：App 引导清单的步骤文案必须覆盖**所有**已注册 App 渠道。

用户原话：「渠道登录里智行 APP 的名字就不全」。同一类缺陷也出现在首次
引导：`STEPS` 曾写死「安装智行 App」，但安装检查其实遍历 `APP_CHANNELS`
——接入去哪儿 App 后，这一步仍只报智行，用户无从判断去哪儿 App 装没装。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.bootstrap import STEPS            # noqa: E402
from core.channels import APP_CHANNELS, plat_cn     # noqa: E402


def test_apk_step_names_every_registered_app_channel():
    label = dict(STEPS)["apk"]
    for p in APP_CHANNELS:
        cn = plat_cn(p)
        assert cn in label, "引导步骤没写全 App 渠道名：%r（缺 %s）" % (label, cn)
    assert "智行 App" in label and "去哪儿 App" in label, label
    assert label.strip() != "安装智行 App", "仍是写死单渠道的旧文案"
