# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r256_push.py
- tests/test_r326_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys


# ---- merged from tests/test_r256_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(path):
    return open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path),
        encoding="utf-8").read()


def _wcag_ratio(fg, bg):
    """WCAG 2.x 相对亮度对比度比。"""
    def lum(c):
        v = [x / 255.0 for x in c]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
             for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    l1, l2 = sorted((lum(fg), lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class TestPoolNoteSingleSource:
    def test_literal_count_is_one(self):
        """「近2.5时」裸字面量全文残留计数==1（常量定义处）——
        消费点与注释全部改走 _POOL_NOTE。"""
        src = _src("report.py")
        assert src.count("近2.5时") == 1, [
            i + 1 for i, l in enumerate(src.splitlines()) if "近2.5时" in l]

    def test_constant_defined_and_consumed(self):
        """常量定义在场且四个消费点走 f-string 插值。"""
        src = _src("report.py")
        assert '_POOL_NOTE = "近2.5时"' in src
        assert '{_POOL_NOTE}各渠道最新' in src
        assert '· {_POOL_NOTE}口径' in src
        assert '该日期{_POOL_NOTE}无渠道明细' in src


class TestTrendDayLabelContrast:
    def test_new_color_in_place(self):
        """跨天日期标签新色 (120, 94, 32) 在场，旧色零残留。"""
        src = _src("report.py")
        assert "fill=(120, 94, 32)" in src
        assert "(150, 120, 60)" not in src

    def test_contrast_meets_aa(self):
        """新色对 DESIGN.BG 算术复算 ≥4.5:1（AA 正文档）。"""
        ratio = _wcag_ratio((120, 94, 32), (236, 239, 244))
        assert ratio >= 4.5, ratio


# ---- merged from tests/test_r326_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _main_src():
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "main.py"), encoding="utf-8") as f:
        return f.read()


def test_special_push_send_passes_sanitize():
    src = _main_src()
    # 实效档：特价推送经消毒单源出口（与 alerter 全部 send 同守卫）
    assert "a.notifier.send(sanitize_desp(title), sanitize_desp(desp))" in src
    # 禁复活：裸直发（未过 sanitize_desp）不得回归
    assert "a.notifier.send(title, desp)" not in src
