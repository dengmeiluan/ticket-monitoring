# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r683_channel_dims_surface.py
- tests/test_r805af_channel_icon_coverage.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

from support_webui_src import webui_full_src

import io
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r683_channel_dims_surface.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _webui_src():
    with io.StringIO(webui_full_src()) as f:
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


# ---- merged from tests/test_r805af_channel_icon_coverage.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _plats():
    src = webui_full_src()
    i = src.find("const SRX_PLATS=")
    assert i > 0, "SRX_PLATS 锚点失效"
    seg = src[i:src.find("};", i)]
    ids = re.findall(r"([A-Za-z_][A-Za-z0-9_]*):\[", seg)
    return ids


def test_every_platform_has_official_icon():
    src = webui_full_src()
    ids = _plats()
    assert len(ids) == 10, "渠道数变了：%s（改声明时同步改本判据）" % ids
    # App 与同品牌浏览器渠道可共用一张官方图（SRX_BRAND_ALIAS）。
    m = re.search(r"const SRX_BRAND_ALIAS=\{([^}]*)\}", src)
    aliases = dict(re.findall(r"([a-z_]+)\s*:\s*'([a-z_]+)'",
                              m.group(1) if m else ""))
    for p in ids:
        # 图标外置化：注册表值由内嵌 data URI 改为 /assets/icons/ URL。
        key = p if re.search(r'"%s":"/assets/icons/' % re.escape(p), src) \
            else aliases.get(p)
        assert key and re.search(
            r'"%s":"/assets/icons/' % re.escape(key or ""), src), (
            "%s 没有官方图标（SRX_BRAND_IMG 缺这个 key，也无别名）——"
            "用户要求全站渠道都带官方图标" % p)


def test_frontend_has_no_second_name_table():
    src = webui_full_src()
    i = src.find("function srxPlatKey")
    assert i > 0, "srxPlatKey 锚点失效"
    body = src[i:src.index("\n}", i)]
    assert "SRX_PLATS" in body, (
        "srxPlatKey 没有从 SRX_PLATS 派生——回到写死表就又漏 App 渠道")
    assert "const m={'去哪儿'" not in body, (
        "srxPlatKey 里仍有第二份中文名表")
    # 全仓扫描：任何「中文渠道名 → id」的写死表都只会有 5 家浏览器渠道，
    # 加第三个 App 渠道时必然漏。实测已清掉三处（srxPlatKey / buildChips
    # 的 PK / KPI 胶囊的 PKEY），这条防它们以别的变量名长回来。
    import re as _re
    pat = _re.compile(r"\{[^{}\n]*?'去哪儿'\s*:[^{}\n]*?\}")
    hits = []
    for m in pat.finditer(src):
        s = m.group(0)
        if s.count(":") >= 5 and "SRX_PLATS" not in s:
            hits.append(src[:m.start()].count("\n") + 1)
    assert not hits, (
        "又有写死的「中文渠道名→id」表（%s 行）：只列 5 家，App 渠道"
        "会丢图标——改走 srxPlatKey" % hits)




