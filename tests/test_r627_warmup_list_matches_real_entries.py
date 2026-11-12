# -*- coding: utf-8 -*-
"""r627：预热名单里没有入口的渠道，不能「可点但什么也不做」。

`warmup_platforms` 是自由文本框，后端白名单写死成五家；但其中
**ctrip / tongcheng 根本没有 `warmup_url`**（智行 App 也没有）。用户填
`ctrip` 后：后端保留 → 面板按 `WARM.indexOf(p)>=0` 渲染成**可点**按钮 →
点下去 `_warm_once()` 见 `warmup_url` 为空直接 return —— 无反应、无提示。
用户以为预热在跑，实际一次没发。

修法：可预热集合由**真实具备入口**的采集器派生（`_warmable()`），
保存时剔除无入口项并回传 `warmup_ignored`，配置页点名说明。
负控：把白名单改回写死五家即红。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_warmable_is_derived_from_real_entries():
    from crawlers import REGISTRY
    real = {k for k, cls in REGISTRY.items()
            if str(getattr(cls, "warmup_url", "") or "").strip()}
    assert set(webui._warmable()) == real, (
        "可预热集合没跟着真实入口走：声明 %s / 实际 %s"
        % (sorted(webui._warmable()), sorted(real)))
    # 这两家确实没有入口（本测试的前提，若哪天加了入口这里会失败提醒复核）
    for k in ("ctrip", "tongcheng"):
        assert k not in webui._warmable(), (
            "%s 本来没有 warmup_url，不该出现在可预热集合里" % k)


def test_channels_without_entry_are_not_offered():
    """面板按钮行不得把无入口渠道当可点（防止再次「点了没反应」）。"""
    w = _src()
    i = w.index("const WARM=cf.warmup_platforms||[]")
    seg = w[i:i + 900]
    assert "该渠道未配置预热入口" in seg, (
        "无入口渠道没有「不可用 + 原因」的呈现：%s" % seg[:300])


def test_save_filters_and_reports_ignored_channels():
    """保存端必须按真实入口过滤，并把被忽略项回传（不能静默丢弃）。"""
    w = _src()
    i = w.index('if glb.get("warmup_platforms") is not None:')
    seg = w[i:i + 900]
    assert "_warmable()" in seg, (
        "保存端没用 _warmable() 过滤（仍可能是手写白名单）：%s" % seg[:300])
    assert "ignored" in seg, (
        "被忽略的渠道没有回传，用户不知道填写没生效：%s" % seg[:300])


def test_readback_exposes_ignored_and_warmable():
    """回读端要给出 warmup_ignored / warmable，供配置页点名。"""
    w = _src()
    assert '"warmup_ignored"' in w, "回读缺 warmup_ignored"
    assert '"warmable"' in w, "回读缺 warmable 清单"
    i = w.index('"warmup_ignored"')
    seg = w[max(0, i - 400):i + 500]
    assert "_warmable()" in seg, "warmup_ignored 没有按真实入口算"


def test_config_page_names_the_ignored_channels():
    """配置页要把「这几家填了也没用」说出来。"""
    w = _src()
    i = w.index("glbWarmP")
    seg = w[i:i + 900]
    assert "没有预热入口" in seg, (
        "配置页没有提示哪些渠道没有入口：%s" % seg[:300])
    assert "warmable" in seg, (
        "配置页没有列出可填的渠道名：%s" % seg[:300])
