# -*- coding: utf-8 -*-
"""r256 推送层两案落地钉（_scratch/r256_push_audit.md 审计消化，
P0-P2=0 后的可选顺手项收编）：

- P-1 ⏱「近2.5时」词面提常量单源：散点 4 消费点（render 默认小注/
  ⏱ 口径行/无数据降级档×3/日报 stamp_note）+ 注释 4 处散写——
  「改词必漏」家族形态（LESSONS 十六§3b 词面域单源律），收口为
  _POOL_NOTE 单常量，裸字面量全文残留计数==1（只剩定义处）。
  词面本身不变（「近2.5时」：与数据窗 max_age_min=150 严格一致、
  行宽 31/40 达标，r255 既判语义正确；全写「小时」纯读感不动钉面）。
- P-2 走势跨天日期标签对比度提 AA：fill (150,120,60) 对 BG
  (236,239,244) 仅 3.61:1（AA-large-only，14px 辅助刻度不豁免）——
  改 (120,94,32) ≥4.5:1（canvas 像素层文字是 DOM 扫描盲区，
  LESSONS 四§6 第二通道算术复算钉收口）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r256_push.py -q
"""
import os
import sys

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
