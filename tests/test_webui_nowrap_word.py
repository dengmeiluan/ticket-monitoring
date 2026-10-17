# -*- coding: utf-8 -*-
"""WebUI CJK 断词孤字修复（十七§6 判例：词组粒度 nowrap 唯一解）。

r268 WebUI 审计 P3-1 双面：① 停用卡 routesTxt 390 档把「乌鲁木齐」
折成「乌鲁/木齐」（routesTxt 是「航段+日期」的「、」分段清单，段为
不可分单元）；② 空态教学卡引号按钮名「测试推送」折成「测试推/送」。
修法零协议改动：routesTxt 按「、」分段逐段包 .nw（全局工具类），
段间「、」留断行位；ol 引号词包 .nw。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_webui_nowrap_word.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
                encoding="utf-8").read()


def test_suspended_routes_txt_word_wrap():
    # 停用卡 routesTxt 按「、」分段包 .nw（段=航段+日期不可分单元，
    # 「、」留在 nowrap span 外当断行位）；he() 先消毒再分段
    # （「、」非 HTML 特殊字符，消毒不改变分段）
    src = _src()
    assert "he(x.routesTxt).split('、').map(s=>'<span class=\"nw\">'" in src


def test_hero_teaching_quoted_word_wrap():
    # 教学卡 ol 引号按钮名整词包 .nw（390 档「测试推/送」断词孤字）
    src = _src()
    assert '<span class="nw">「🔔 测试推送」</span>' in src
