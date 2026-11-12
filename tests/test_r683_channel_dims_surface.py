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


def _channels_src():
    with open(os.path.join(ROOT, "core", "channels.py"),
              encoding="utf-8") as f:
        return f.read()


def test_endpoint_derives_from_single_source():
    """必须走 core.channels 的单一载荷，不能自己再写一份矩阵。"""
    src = _webui_src()
    i = src.index('"/api/channel-dims"')
    assert "channel_dims_payload()" in src[i:i + 900], (
        "端点没走 core.channels.channel_dims_payload")
    payload = _channels_src()
    j = payload.index("def channel_dims_payload")
    block = payload[j:]
    for name in ("APP_BROWSER_PEER", "CHANNEL_DIMENSIONS", "DIMENSIONS",
                 "app_alignment_gaps"):
        assert name in block, "载荷没有读 %s，等于另抄一份" % name


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

    # App 渠道仍要点名「同源浏览器渠道」（产地/账号体系，界面展示用）
    assert by["app_zhixing"]["peer"] == "ctrip"
    assert by["app_qunar"]["peer"] == "qunar"
    # 缺口基准是**浏览器端整体能力**（用户原话：PC/H5 有的能力 App 都要有），
    # 不再按单家同源友商判——携程自己 round_trip=n 会把往返缺口自证掉。
    # 截至 2026-11-02 晚：去哪儿 App 往返已真机跑通；登录后「低价机票」
    # 落原生 RN 页（QReactNativeActivity1），14 天逐日价 41.2s 真出；
    # 日历整月也带价。两处旧缺口已补齐。
    # 2026-11-03：ctrip PC 多程 2 段已生产验证 → 浏览器端出现该能力，
    # 两家 App 仍未接多程，缺口只剩 multi_city（其余维度已对齐）。
    assert by["app_qunar"]["gaps"] == ["multi_city"], by["app_qunar"]["gaps"]
    assert by["app_zhixing"]["gaps"] == ["multi_city"], by["app_zhixing"]["gaps"]

    # 浏览器渠道没有基准，不该冒出「缺口」
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert by[p]["gaps"] == [], by[p]["gaps"]


def test_gaps_only_count_browser_supported_dims():
    """缺口只来自「浏览器端有而 App 没有」；App 更全不算缺口。"""
    from core.channels import app_alignment_gaps, browser_supported
    # multi_city：ctrip PC 2 段已 y → 浏览器端有；两家 App 未接，算缺口。
    assert browser_supported("multi_city")
    assert "multi_city" in app_alignment_gaps("app_qunar")
    assert "multi_city" in app_alignment_gaps("app_zhixing")
    # round_trip：飞猪/同程为 y（携程自己 n）→ 浏览器端有；两家 App 都已
    # 真机跑通（2026-10-31），故不是缺口。
    assert browser_supported("round_trip")
    assert "round_trip" not in app_alignment_gaps("app_qunar")
    assert "round_trip" not in app_alignment_gaps("app_zhixing")
