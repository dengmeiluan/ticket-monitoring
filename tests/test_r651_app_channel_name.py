# -*- coding: utf-8 -*-
"""r651：App 渠道要有中文显示名，但不能混进「默认渠道全集」。

两件事必须同时成立，否则修一边坏一边：
  1. 页面上 `platAge` 等按渠道名展示的地方，App 渠道显示「智行 App」，
     而不是原始 id `app_zhixing`（与旁边「携程/飞猪」混排很突兀）；
  2. `Alerter.PLATFORM_CN` 是「默认渠道全集」的来源
     （`self.platforms = list(PLATFORM_CN)`）——把 App 塞进去，会让
     **没启用 App 渠道的用户**每轮都被记「智行 App 当轮无数据」。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter


def test_app_channel_has_chinese_name():
    assert Alerter.plat_cn("app_zhixing") == "智行 App"


def test_browser_channels_unchanged():
    assert Alerter.plat_cn("qunar") == "去哪儿"
    assert Alerter.plat_cn("fliggy") == "飞猪"
    assert Alerter.plat_cn("ctrip") == "携程"
    assert Alerter.plat_cn("tongcheng") == "同程"
    assert Alerter.plat_cn("tuniu") == "途牛"


def test_unknown_channel_falls_back_to_id():
    assert Alerter.plat_cn("no_such_plat") == "no_such_plat"


def test_default_platform_set_excludes_app_channel():
    """默认全集不能含 App 渠道——否则未启用者每轮收缺勤告警。"""
    assert "app_zhixing" not in Alerter.PLATFORM_CN
    a = Alerter(logging.getLogger("t"))
    assert "app_zhixing" not in a.platforms


def test_no_raw_platform_cn_get_left_in_message_paths():
    """消息路径必须走 plat_cn，直接 .get(p, p) 会漏掉 App 的中文名。"""
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "alerter.py"),
                  encoding="utf-8", newline="").read()
    bad = [ln for ln in src.splitlines()
           if "PLATFORM_CN.get(" in ln and "PLATFORM_CN.get(p)" not in ln]
    assert not bad, "仍有绕过 plat_cn 的取名：%s" % bad[:3]
