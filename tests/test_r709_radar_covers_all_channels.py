# -*- coding: utf-8 -*-
"""r709：特价雷达的「渠道入口」区必须覆盖**全部**渠道。

缺陷事实（2026-10-31）：前端 `srxSpecialEntryHTML` 把渠道清单写成
`['ctrip','qunar','fliggy','tongcheng','tuniu']` —— 5 家浏览器渠道。
接入两家 App 之后，去了特价雷达的用户**根本看不到 App**：去哪儿 App
的低价机票（每天一条）和智行 App 的特价入口在界面上等于不存在。

这与用户要求（「各页面渠道信息展示要把原来的渠道一块布局考虑」）
直接冲突，所以钉三条：
  1. 前端渠道清单必须从 SRX_PLATS/SRX_PLAT_KEYS 派生，不得写死；
  2. 后端 SPECIAL_CAPABILITY 必须覆盖每家 App 渠道（哪怕是「形态不同、
     暂无可用源」也要如实登记，界面才说得清为什么不参与）；
  3. 雷达查询白名单 `_CHANNELS` 里出现的渠道，必须在能力表里有来源，
     不许「查了但界面说不出它是什么」。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channels import APP_CHANNELS, BROWSER_CHANNELS  # noqa: E402
from core.special_radar import _CHANNELS  # noqa: E402
from core.specials import SPECIAL_CAPABILITY  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        return f.read()


def test_special_entry_channels_not_hardcoded():
    src = _webui()
    m = re.search(r"function srxSpecialEntryHTML\([\s\S]{0,1600}", src)
    assert m, "找不到 srxSpecialEntryHTML"
    body = m.group(0)
    assert "SRX_PLAT_KEYS" in body or "SRX_PLATS" in body, (
        "特价雷达入口的渠道清单又写死了——新增渠道会再次从界面消失")
    # 去掉注释后，不应再有写死的五家清单字面量
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    body = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.splitlines())
    assert not re.search(r"\[\s*'ctrip'\s*,\s*'qunar'", body), body[:300]


def test_capability_covers_every_app_channel():
    for plat in APP_CHANNELS:
        assert plat in SPECIAL_CAPABILITY, (
            "%s 没有特价能力声明：雷达里它会彻底消失，用户看不出「这家有没有"
            "特价、为什么没参与」" % plat)
        entry = SPECIAL_CAPABILITY[plat]
        assert "note" in entry and entry["note"], plat


def test_radar_channels_have_declared_sources():
    for plat in _CHANNELS:
        entry = SPECIAL_CAPABILITY.get(plat)
        assert entry is not None, "%s 在雷达白名单里但能力表没有" % plat


def test_every_channel_with_source_is_radar_selectable():
    """有发现源 ⇒ 可选；声明过但无源的渠道也必须保留可选。

    r805cj：app_qunar 的入口变成 H5 WebView（不可读），sources 清空、
    矩阵记 n；但用户要求「统一监控」，不能让它从雷达里消失——查询它
    必须返回 not_connected + 原因。因此白名单 = **能力表全部声明键**，
    而有源的渠道是其子集。
    """
    missing = [p for p in (list(APP_CHANNELS) + list(BROWSER_CHANNELS))
               if p not in SPECIAL_CAPABILITY]
    assert not missing, "这些渠道在特价雷达里没有声明：%s" % missing
    with_source = tuple(p for p, e in SPECIAL_CAPABILITY.items()
                        if e.get("sources"))
    assert set(with_source) <= set(_CHANNELS), (
        "有发现源的渠道没进雷达白名单：%s" % (set(with_source) - set(_CHANNELS)))
    assert set(_CHANNELS) == set(SPECIAL_CAPABILITY), (
        "雷达白名单必须与能力声明一致（含无源但需显示原因的渠道）：%s"
        % (set(_CHANNELS) ^ set(SPECIAL_CAPABILITY)))
    # r732 更正了旧结论：智行「特价」不是目的地榜，而是与去哪儿 App 同一
    # 契约的「一条航线 × 逐天报价」。断言守「有源 + 写清口径边界」，
    # 不再要求 note 里出现已被推翻的「目的地」。
    zx = SPECIAL_CAPABILITY.get("app_zhixing") or {}
    assert zx.get("sources"), "智行已有逐天报价发现源，sources 不能是空的"
    assert "口径" in (zx.get("note") or ""), (
        "note 要写清价格口径边界（页面未标含税），否则读者会误当含税价")


def test_zhixing_channel_survives_query_filter():
    """往返：带智行的请求必须原样留下，不能被白名单静默丢掉。"""
    from core.special_radar import parse_query
    q = parse_query({"from": "上海", "to": "北京",
                     "start": "2026-12-01", "end": "2026-12-03",
                     "channels": ["app_zhixing"]})
    assert q.channels == ["app_zhixing"], q.channels


def test_frontend_app_keys_mirror_declared_app_channels():
    """前端可勾选 App 清单与后端「已声明」的 App 渠道一致。

    r805cj：app_qunar 仍要出现在界面上（点了会显示「未接入」原因），
    所以镜像的是**声明**而非「有源」。
    """
    src = _webui()
    m = re.search(r"var SRX_RADAR_APP_KEYS=\[([^\]]*)\]", src)
    assert m, "找不到 SRX_RADAR_APP_KEYS"
    fe = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    be = set(APP_CHANNELS) & set(SPECIAL_CAPABILITY)
    assert fe == be, "前端可勾选 %s / 后端已声明 %s" % (sorted(fe), sorted(be))
