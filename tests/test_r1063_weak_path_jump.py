# -*- coding: utf-8 -*-
"""r1063 T200：弱环 → **直达策略行**（可调整，不只是可自检）。

链路闭合：面板上看到弱环 → 点主文本 → 直接落到该「渠道·链路」的策略覆盖行，
改完保存即生效；不想改就点同一行末尾的 `⟳` 跑一次真查询自检。

真机验证（1512×950）：
```
弱环主链接: app_fliggy·app-login 0%/118 → srxWeakJump('app_fliggy','app-login')
跳转结果: 面板打开 · 31 行策略 · 渠道=app_fliggy · 作用域=app-login · 无 JS 报错
```
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_jump_helper_is_top_level():
    """行内 onclick 只能解析全局名（上次 srxWeakProbe 就栽在这）。"""
    w = _w()
    i = w.index("function srxWeakJump(")
    line_start = w.rfind("\n", 0, i) + 1
    assert w[line_start:i] == " ", "srxWeakJump 不是顶层函数"


def test_jump_targets_globals_panel_and_uses_scope_fill():
    w = _w()
    i = w.index("function srxWeakJump(")
    seg = w[i:i + 2200]
    assert "showCfgPanel('globals')" in seg, "策略行在「全局参数」面板里"
    assert "stratScopeFill(sel)" in seg, "链路选项必须由 stratScopeFill 铺（含全量目录）"
    assert "select.ssel2" in seg, "要把作用域设成该链路"
    assert "scrollIntoView" in seg, "要滚到那一行，否则用户还得自己找"


def test_weak_item_binds_both_jump_and_probe():
    w = _w()
    i = w.index("通路弱环（近24h）")
    seg = w[i - 900:i + 900]
    assert "srxWeakJump" in seg, "主文本应跳到策略行"
    assert "srxWeakProbe" in seg, "末尾应保留一键自检"
    assert "esc(r.path)" in seg, "跳转必须带上链路名"
