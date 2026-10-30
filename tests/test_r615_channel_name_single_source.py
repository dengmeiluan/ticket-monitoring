# -*- coding: utf-8 -*-
"""r615：渠道名表必须只有**一个源**——散落的「5 家名单」会漏掉新渠道。

r614 修了健康卡与节流面板两张 `CN` 表，但同一份「5 家中文名」在前端还抄了
第三份：`PCN`（概览脉冲条 tooltip）。再加上筛选 chip 直接 `${he(p)}` 打原始 id，
智行 App 在这两处仍会以 `app_zhixing` 出现。

**这不是三处笔误，是一个结构性隐患**：每抄一份名单就多一个漂移点。
本文件把判据钉在「不许再出现只列 5 家的独立名单」上——
凡是渠道名表，都必须 `Object.assign(…, APP_PLAT_NAME)`。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 5 家浏览器渠道的中文名——只允许出现在 Object.assign 的第一参里
_FIVE = "{'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'}"


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_no_standalone_five_platform_name_table():
    """不允许存在「只有 5 家、且没并入 APP_PLAT_NAME」的独立名单。"""
    w = _w()
    bad = []
    # 只查「以 5 家渠道 id 为键」的正查表；`PK`/`PKEY` 那类
    # 「中文名 → id」的反查表方向相反，不受这条约束。
    for m in re.finditer(
            r"const\s+(\w+)\s*=\s*\{[^}]*'qunar'\s*:[^}]*\};", w):
        name, stmt = m.group(1), m.group(0)
        if "APP_PLAT_NAME" not in stmt:
            bad.append(name)
    assert not bad, (
        "这些渠道名表只列了 5 家、没并入 APP_PLAT_NAME（新渠道会漏）：%s" % bad)


def test_all_three_tables_merge_the_single_source():
    w = _w()
    assert w.count("(typeof APP_PLAT_NAME!=='undefined')?APP_PLAT_NAME:{}") >= 3, (
        "并入 APP_PLAT_NAME 的表少于 3 张（健康卡/节流面板/脉冲条）")


def test_filter_chip_uses_the_name_table():
    """筛选 chip 不能直接打原始渠道 id。"""
    w = _w()
    i = w.index("onclick=\"togChip(this)\"")
    seg = w[i:i + 220]
    assert "CN[p]" in seg, "筛选 chip 仍直接显示原始 id：%s" % seg[:120]


def test_pulse_tooltip_table_merges_app_names():
    """PCN（脉冲条 tooltip 的唯一名源）必须并入 APP_PLAT_NAME。

    这里只做静态断言：`PCN` 定义在概览渲染的作用域内，不是全局变量，
    真渲染探针读不到它（实测 `PCN` 未定义 → 页面评估超时）。
    三张表都走同一个 `Object.assign`，静态判据已足够——动态部分由
    r614 的健康卡渲染断言覆盖（那张表在全局作用域）。
    """
    w = _w()
    i = w.index("const PCN=")
    seg = w[i:i + 260]
    assert "APP_PLAT_NAME" in seg, "PCN 没有并入 APP_PLAT_NAME：%s" % seg[:140]
    assert "'qunar'" in seg and "tuniu" in seg, seg
