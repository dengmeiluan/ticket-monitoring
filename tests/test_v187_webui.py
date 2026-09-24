# -*- coding: utf-8 -*-
"""v1.5.87 webui 回归（源码级钉，同 test_v181 模式）。

- audit_w2 P2-1：kbdtips 触屏隐藏的 coarse 块曾被置尾 ≤760 块反杀
  （同选择器媒体块源码序后者胜，LESSONS 二十一.1 反面案例）——
  coarse 隐藏块必须位于窄窗块之后，位置错了真实手机上快捷键教学
  对无键盘设备复活成误导文案
- audit_w2 P3-1：761-1439 带脉冲图例与柱区同轴（柱区 center 全宽域
  生效、图例同轴修复却只写到 1440——半区修复残留，同卡双轴）
- 观测纵深对称：_user_state 列表管线两处 flights 收集补 PRICE_MIN/MAX
  兜底（与曲线 _rounds 同带单源；爬虫端把关是唯一防线时，未来爬虫
  回归即「列表可见、图上不可见」反向复演）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v187_webui.py -q
"""


class TestWebuiV187Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_kbdtips_coarse_block_after_narrow_block(self):
        """coarse 隐藏块必须层叠在 ≤760 独立成行块之后（源码序后者胜）。"""
        src = self._src()
        assert "@media(max-width:760px){.kbdtips" in src, \
            "≤760 独立成行块缺失"
        i_narrow = src.index("@media(max-width:760px){.kbdtips")
        needle = "@media(pointer:coarse){.kbdtips{display:none}}"
        assert needle in src, "coarse 隐藏块缺失（触屏隐藏失效）"
        i_coarse = src.rindex(needle)
        assert i_coarse > i_narrow, \
            "coarse 隐藏块在 ≤760 块之前——同选择器源码序后者胜，" \
            "真实手机（coarse+窄屏双命中）display:block 复活"

    def test_price_band_guard_helper_exists(self):
        """列表端价格带兜底 helper（与曲线 _rounds 同带单源）。"""
        src = self._src()
        assert "def _price_in_band" in src, "价格带兜底 helper 缺失"
        i0 = src.index("def _price_in_band")
        seg = src[i0:i0 + 400]
        assert "PRICE_MIN" in seg and "PRICE_MAX" in seg, \
            "helper 未引用价格带单源（core.models PRICE_MIN/MAX）"

    def test_price_band_guard_both_collectors(self):
        """flights 两处收集点（当轮展开 + 近 6h 补位）同挂兜底。"""
        src = self._src()
        n = src.count('"price" in f and _price_in_band(f.get("price"))')
        assert n >= 2, \
            f"flights 收集点须同挂价格带兜底（期望 ≥2 处，现 {n} 处）"
