# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v162_webui.py 模式；行为断言在
docs/uitest.py 三钉：gradient 打底 computed 样式/价格绿字 AA/chip 跟随）。

 明细行尾 📈 跳走势后航线 chip 高亮停留旧路由（jumpRowTrend 只
chart 不重建——togChart/jumpCalDate 均显式重建，补 buildChartChips）；
 达标行 sticky 吸附格 rgba 重涂叠行身同值 rgba 成双层绿底（首格
#daebe2 vs 行身 #ecf5f0 色带）+ 半透明格横滚被下层列透视——gradient
不透明 --card 打底 + 同值 tint 单层叠加；
 达标行价格绿字 --green 对绿 tint 底 4.19~4.35:1 欠 AA（13px/800
非大字）→ --ok-txt 5.18~6.36 全过（同族收编）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v167_webui.py -q
"""


class TestWebuiV167Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_jump_row_trend_rebuilds_chart_chips(self):
        """：跳走势后 chip 高亮显式重建跟随（亮选片停留旧路由根除）。"""
        assert "gotoMonTab('trend');buildChartChips();" in self._src()

    def test_qual_sticky_cell_gradient_single_layer(self):
        """：吸附格 gradient 不透明打底 + 同值 tint 单层（横滚不透）。"""
        src = self._src()
        for tint in (".08", ".14", ".12"):
            assert ("linear-gradient(rgba(var(--okrgb),%s),"
                    "rgba(var(--okrgb),%s)),var(--card)" % (tint, tint)) in src
        # 暗色换谱成对（67,192,114）
        assert src.count("linear-gradient(rgba(67,192,114,") == 2

    def test_qual_price_uses_ok_txt_token(self):
        """：达标行价格绿字 --ok-txt（AA 收编，--green 退役）。"""
        assert "tr.qual td.price{color:var(--ok-txt);font-weight:800}" \
            in self._src()
