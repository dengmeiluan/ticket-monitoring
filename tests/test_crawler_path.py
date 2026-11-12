# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1565_app_path_elapsed.py
- tests/test_r670_path_status_says_what_it_means.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import pytest
import re
import sys
import time

from crawlers.app_base import AppCrawler


# ---- merged from tests/test_r1565_app_path_elapsed.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Fake(AppCrawler):
    name = "app_ctrip"
    PATH_STATUS = {"ok", "timeout", "error", "login", "blocked", "calendar",
                   "paced"}

    def __init__(self):
        self.user_data_root = "user_data"
        self.paths = []

    def note_app_stall(self, detail=""):
        pass


def test_ms_derived_from_previous_phase_when_not_passed():
    c = _Fake()
    c.path_note("app-login", "ok")          # 第一拍：只有起点
    fake_prev = ("app-login", time.time() - 12.0)
    c._phase_prev = fake_prev
    c.path_note("app-list", "timeout")      # 第二拍：应带上 ~12s
    rec = c.paths[-1]
    assert rec["ms"] > 10_000, (
        "App 通路耗时没被补上（ms=%s）——三率一险的速度口径会永远空白"
        % rec["ms"])
    assert rec["ms"] < 20_000, rec["ms"]


def test_no_previous_phase_means_no_invented_ms():
    c = _Fake()
    c._phase_prev = None
    c.path_note("app-login", "timeout")
    assert c.paths[-1]["ms"] == 0, (
        "没有上一拍时不许凭空造耗时：%s" % c.paths[-1])


def test_explicit_ms_wins():
    c = _Fake()
    c._phase_prev = ("app-login", time.time() - 9.0)
    c.path_note("app-list", "ok", ms=1234)
    assert c.paths[-1]["ms"] == 1234, c.paths[-1]


# ---- merged from tests/test_r670_path_status_says_what_it_means.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return webui_full_src()


def _front_table():
    s = _src()
    i = s.index("const SRX_PATH_CN={")
    seg = s[i:s.index("};", i)]
    out = {}
    for m in re.finditer(r"([a-z_]+)\s*:\s*'([^']+)'", seg):
        out[m.group(1)] = m.group(2)
    return out


def test_shared_codes_use_the_same_wording():
    """两套表**重叠的码**必须同名，但不要求逐字同一张表。

    `core.pacing.FAILURE_KINDS` 是**归因分类**（ip / captcha / soft / login…），
    `webui.SRX_PATH_CN` 是**账本状态码**（ok / login / blocked / soft_reject…）。
    两者维度不同：`ip` / `captcha` / `soft` 在账本里根本不会出现（归类后
    才得到），所以不能拿它们要求前端有名字。
    真正要守的是：**同一个码在两边不能说出两个意思**——例如 login 一边叫
    「登录态失效」一边叫「登录拒绝」，读者会以为是两件事。
    """
    from core.pacing import FAILURE_KINDS
    front = _front_table()
    # 仅在两边都有的码上对齐语义（语义相同即可，措辞可以更短）
    SAME = {
        "login": ("登录", "login"),
        "timeout": ("超时", "timeout"),
        "parse_error": ("解析", "parse_error"),
        "unsupported": ("不支持", "unsupported"),
        "empty": ("票", "empty"),
    }
    for code, (needle, front_key) in SAME.items():
        label = FAILURE_KINDS[code][0]
        assert needle in label, "后端 %s 的名字变了？%r" % (code, label)
        assert front_key in front, "前端缺 %s" % front_key
        assert needle in front[front_key], (
            "%s 两边说法对不上：后端「%s」前端「%s」"
            % (code, label, front[front_key]))


def test_dedup_codes_are_not_required_but_attribution_ones_are_absent():
    """归因码（ip/captcha/soft）不进状态表——账本里不会出现它们。"""
    front = _front_table()
    for code in ("ip", "captcha", "soft"):
        assert code not in front, (
            "%s 是归因分类，不是账本状态码；混进状态表会让读者分不清"
            "「为什么失败」和「哪一步失败」" % code)


def test_every_ledger_status_has_a_name():
    """path_note 写进账本的状态码，界面都要能读。"""
    from crawlers.base import BaseCrawler
    front = _front_table()
    missing = [st for st in BaseCrawler.PATH_STATUS if st not in front]
    assert not missing, "账本状态码在界面上没有名字：%s" % missing


def test_unknown_status_falls_back_to_the_raw_code():
    s = _src()
    i = s.index("function srxPathCN(st){")
    seg = s[i:i + 160]
    assert "SRX_PATH_CN[k]||k}" in seg, (
        "未知状态码必须原样返回（宁缺勿错），不能一律说成「无结果」：%r" % seg)


