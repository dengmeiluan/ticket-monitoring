# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r627_warmup_list_matches_real_entries.py
- tests/test_r627b_warmup_ignored_is_behavioral.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import re
import sys
import webui


# ---- merged from tests/test_r627_warmup_list_matches_real_entries.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _src():
    return webui_full_src()


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


# ---- merged from tests/test_r627b_warmup_ignored_is_behavioral.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _readback_block():
    w = webui_full_src()
    i = w.index('"warmup_platforms": ", ".join(')
    j = w.index('"warmable": list(_warmable()),', i)
    return w[i:j + len('"warmable": list(_warmable()),')]


def test_readback_filters_and_reports_by_real_entries():
    blk = _readback_block()
    # 结构判据：过滤条件必须绑定 _warmable()，而不是写死的五家名单
    assert "if x in _warmable()" in blk, (
        "回读没有按真实入口过滤（写成死名单就会让 ctrip 混进可用列表）：\n%s" % blk)
    assert re.search(r"x not in _warmable\(\)", blk), (
        "ignored 列表没有按真实入口算：\n%s" % blk)


def test_warmable_matches_registry_warmup_url():
    from crawlers import REGISTRY
    real = tuple(sorted(k for k, cls in REGISTRY.items()
                        if str(getattr(cls, "warmup_url", "") or "").strip()))
    assert webui._warmable() == real, (
        "可预热集合与真实入口不一致：%s vs %s"
        % (webui._warmable(), real))
