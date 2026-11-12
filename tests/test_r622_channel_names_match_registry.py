# -*- coding: utf-8 -*-
"""r622：界面上出现的渠道名，必须对应一个**真的存在**的渠道。

`APP_PLAT_NAME` 里同时写了 `app_zhixing`（智行 App）和 `app_meituan`
（美团 App），但 `crawlers.REGISTRY` 里只有前者——美团 App 的解析根本
没有接入（`docs/superpowers/plans/2026-10-29-app-channels-p1.md` 明写
「未落地：`tests/test_app_meituan_parse.py` —— 美团 App 解析未接入」）。

后果不是「少个名字」，而是**语义错误**：名字表是「我们说支持哪些渠道」
的对外声明，里面躺着一个跑不起来的条目，读者（和后来的维护者）会以为
美团 App 已经能用；而它在配置页既勾不到、也不会被实例化。

**判据**：`APP_PLAT_NAME` 的键集合 ⊆ `crawlers.REGISTRY` 的键集合。
新增 App 渠道的顺序应当是「先有采集器 + 进 REGISTRY + 进健康/告警映射」，
最后才出现在名字表里。

负控：把 `app_meituan:'美团 App'` 加回去即红。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _app_names():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    m = re.search(r"const APP_PLAT_NAME=\{(.*?)\};", w, re.S)
    assert m, "找不到 APP_PLAT_NAME 声明"
    return set(re.findall(r"([A-Za-z_][\w]*)\s*:", m.group(1)))


def test_app_name_table_only_lists_real_channels():
    from crawlers import REGISTRY
    named = _app_names()
    assert named, "APP_PLAT_NAME 为空（名字表失去意义）"
    ghost = sorted(named - set(REGISTRY))
    assert not ghost, (
        "名字表里有 REGISTRY 中不存在的渠道（界面会宣称一个跑不起来的渠道）：%s\n"
        "现有 REGISTRY：%s" % (ghost, sorted(REGISTRY)))


def test_registry_app_channels_are_all_named():
    """反过来也要成立：REGISTRY 里的 App 渠道必须有中文名（不能露原始 id）。"""
    from crawlers import REGISTRY
    named = _app_names()
    missing = sorted(k for k in REGISTRY if k.startswith("app_") and k not in named)
    assert not missing, "这些 App 渠道没有中文名（界面会显示原始 id）：%s" % missing


def test_unimplemented_meituan_is_not_advertised():
    """美团 App 解析未接入——在接入前不得出现在名字表里。"""
    assert "app_meituan" not in _app_names(), (
        "美团 App 尚未接入采集器，却已经出现在渠道名表里")
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    assert "p-app_meituan" not in w, (
        "配置页出现了美团 App 的勾选 chip，但后端没有这个渠道")
