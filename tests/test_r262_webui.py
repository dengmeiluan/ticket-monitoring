# -*- coding: utf-8 -*-
"""r262 WebUI 一案（调研 _scratch/r262_audit_webui.md P3-1）：

W1 scroll-padding 死声明清理：≤760 合并块头部的 hdh+34 固定档与
541-760 带内 hdh+40 注记档，均被同带内更后的三段式实效档
（hdh+--mtabsh+--tabsh+4，源码序后者胜）覆盖——「带内覆写块随
变量单源化退役」纪律（LESSONS 二十一§7）的残留，纯维护债零行为差。
钉面：死档清零 + calc 声明计数收敛（防死档复活回归）。

行为不变由既有 computed 钉守护：docs/uitest.py 两处 scrollPaddingTop
几何断言 + test_r241_webui 活跃补偿含筛选条高项。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r262_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    return open("webui.py", encoding="utf-8").read()


def test_scroll_padding_dead_decls_retired():
    src = _src()
    # 两处死档清零：≤760 合并块头部固定档、541-760 带内注记档
    # （同带内三段式实效档按源码序覆盖，固定档任何视口不可达）
    assert "html{scroll-padding-top:calc(var(--hdh,76px) + 34px)}" not in src, \
        "≤760 块头 hdh+34 死档复活（被同带三段式实效档覆盖）"
    assert "scroll-padding-top:calc(var(--hdh,76px) + 40px)" not in src, \
        "541-760 带内 hdh+40 注记档复活（同带三段式实效档覆盖）"
    # calc 形态声明收敛 4 处：≤900 块与 761+ 块同串 hdh54+34、≤760
    # 块与 ≤540 块三段式（同值补档声明族计数钉，新档须连带清点；
    # 备案：≤900 hdh54+34 疑似全带被后置档接替的同族潜在死档，
    # Soldier Minor-2 在案，删除须先 live 复测 761-900 带 computed）
    assert src.count("scroll-padding-top:calc(") == 4, \
        "scroll-padding calc 声明数漂移：新补偿档须复核同值补档族"
    # 三段式实效档在位（≤760 与 ≤540 两带，含筛选条高项，JS 失效
    # 0px 兜底回落）
    assert src.count(
        "scroll-padding-top:calc(var(--hdh,134px) + var(--mtabsh)"
        " + var(--tabsh,0px) + 4px)") == 2, \
        "≤760/≤540 两带三段式实效补偿档缺失"
