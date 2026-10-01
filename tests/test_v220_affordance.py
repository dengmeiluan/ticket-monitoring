# -*- coding: utf-8 -*-
"""r220 P2-3：明细行展开 affordance（▸ 指示符 + aria-expanded 态翻转）。

首访用户此前只能靠 title 悬停才发现同班比价可展开——行首要有一枚
常驻指示符，展开态旋转为 ▾；态翻转走 aria-expanded 属性（attribute
变更不在 childList MutationObserver 过滤内，扩展免疫约束不变）。
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("R220_SKIP") == "1", reason="manual skip")


class _Src:
    @staticmethod
    def read():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()


class TestRowExpandAffordance:
    def test_row_template_has_aria_expanded_and_indicator(self):
        """明细行模板：aria-expanded 态属性 + .xind 指示符元素在场。"""
        src = _Src.read()
        assert 'aria-expanded=' in src, "明细行模板缺 aria-expanded 态属性"
        assert 'class="xind"' in src or "class='xind'" in src, \
            "明细行模板缺 .xind 展开指示符"

    def test_togrow_flips_aria_state_both_branches(self):
        """togRow 开/收两支都回写 aria 态（收支共用 _ariaOff 单源，开支直设 true）。"""
        src = _Src.read()
        i0 = src.index("function togRow")
        seg = src[i0:i0 + 900]
        assert "_ariaOff()" in seg, "togRow 缺 _ariaOff 回写（收支单源）"
        assert "setAttribute('aria-expanded','true')" in seg, \
            "togRow 开支缺 aria-expanded=true 直设"

    def test_indicator_css_rotates_when_open(self):
        """CSS：▸ 指示符在场，展开态 rotate(90deg)（与 .pill::after 同语言）。"""
        src = _Src.read()
        assert ".xind::before" in src, "缺 .xind::before 指示符规则"
        assert "aria-expanded" in src.split(".xind::before", 1)[1], \
            "缺展开态旋转规则（aria-expanded 选择器须在 .xind::before 之后）"
        assert "rotate(90deg)" in src, "缺 rotate(90deg) 展开态"

    def test_restore_honours_expanded_state(self):
        """重渲染按 EXP 回填 aria-expanded 初始态（恢复路径与交互路径同源）。"""
        src = _Src.read()
        marker = 'aria-expanded="${EXP'
        assert marker in src, "aria-expanded 初始值未按 EXP 态回填（模板插值缺失）"

    def test_aria_off_single_source_all_writers(self):
        """aria 回写走 _ariaOff 单源；EXP 清零的旁路（tgGo 互斥/Esc）必须同收。
        静态初始值是假单源：共享态每个入口都要显式回写（LESSONS 二十§1）。"""
        src = _Src.read()
        assert "function _ariaOff" in src, "缺 _ariaOff 单源 helper"
        body = src[src.index("function _ariaOff"):]
        body = body[:body.index("function ", 10)] if "function " in body[10:] else body
        n_q = body.count('aria-expanded="true"')
        # r257 P3-3 起查询点=2（tr 数据行家族 + .tg 改期胶囊家族，
        # 互斥收口两族都收敛本单源；新增家族须同轮 +1 并改本钉）
        assert n_q == 2, f"_ariaOff 体内查询点 {n_q}!=2"
        # 消费点受控枚举:togRow 收支+开前、tgGo 互斥、Esc 收比价+收改期
        # （r257 P3-3 起 Esc 双分支；写点新增须同轮 +1 并改本钉）
        # 「_ariaOff();」调用形态,定义签名 _ariaOff(){ 不含 ); 精确排除
        n_call = src.count("_ariaOff();")
        assert n_call == 5, \
            f"_ariaOff 调用点 {n_call}!=5（togRow×2+tgGo×1+Esc×2）"
