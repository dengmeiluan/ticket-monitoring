# -*- coding: utf-8 -*-
"""r683：维度矩阵要能被产品读到，而不只是测试里的一张表。

用户的要求是「App 渠道信息更全，但 PC/H5 已有的**每个维度**都要对齐」。
`core/channels.py` 的 `CHANNEL_DIMENSIONS` 一直是声明式的，但除测试之外
**没有任何地方读它**——界面看不到、接口拿不到，这条要求就无从核实。

这里守两件事：
  1. `/api/channel-dims` 端点真实存在，且**从矩阵派生**（不是另抄一份）；
  2. 端点的字段能直接回答「谁对齐了、谁还差什么」。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _webui_src():
    with open(WEBUI, encoding="utf-8") as f:
        return f.read()


def test_endpoint_exists_in_post_chain():
    src = _webui_src()
    assert '"/api/channel-dims"' in src, "端点没接进请求链"


def test_endpoint_derives_from_single_source():
    """必须 import core.channels，不能自己再写一份 7×7 表。"""
    src = _webui_src()
    i = src.index('"/api/channel-dims"')
    block = src[i:i + 1400]
    for name in ("APP_BROWSER_PEER", "CHANNEL_DIMENSIONS", "DIMENSIONS",
                 "app_alignment_gaps"):
        assert name in block, "端点没有读 %s，等于另抄一份" % name


def test_payload_answers_alignment_question():
    """按端点同一段逻辑构造一次，检查它真能回答「谁没对齐」。"""
    from core.channels import (APP_BROWSER_PEER, CHANNEL_CN,
                               CHANNEL_DIMENSIONS, DIMENSIONS,
                               app_alignment_gaps)
    chans = [{"plat": p, "name": CHANNEL_CN.get(p, p),
              "cells": {d: (CHANNEL_DIMENSIONS.get(p) or {}).get(d, "")
                        for d in DIMENSIONS},
              "peer": APP_BROWSER_PEER.get(p, ""),
              "gaps": list(app_alignment_gaps(p))}
             for p in CHANNEL_DIMENSIONS]
    by = {c["plat"]: c for c in chans}

    # 每个渠道都要把每个维度表态（空 = 未验证，也是表态）
    for c in chans:
        assert set(c["cells"]) == set(DIMENSIONS), c["plat"]
        assert c["name"] and not c["name"].startswith("a"), \
            "界面会露出裸 id：%s" % c["name"]

    # App 渠道必须点名对齐基准，且缺口可枚举
    assert by["app_zhixing"]["peer"] == "ctrip"
    assert by["app_qunar"]["peer"] == "qunar"
    assert by["app_qunar"]["gaps"] == ["low_fare"], \
        by["app_qunar"]["gaps"]
    # 智行已无缺口：intl 已真机跑通；ctrip 基准本身也没有 low_fare，
    # 基准没有的维度不算缺口（App 比基准多出来的能力也不算）。
    assert by["app_zhixing"]["gaps"] == [], \
        by["app_zhixing"]["gaps"]

    # 浏览器渠道没有基准，不该冒出「缺口」
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert by[p]["gaps"] == [], by[p]["gaps"]


def test_gaps_only_count_peer_supported_dims():
    """App 多出来的能力不算缺口——用户明确说过 App 信息更全。"""
    from core.channels import app_alignment_gaps
    # ctrip 的 round_trip = n；智行也 n。基准不支持就不该算缺口。
    assert "round_trip" not in app_alignment_gaps("app_zhixing")
    assert "multi_city" not in app_alignment_gaps("app_qunar")
