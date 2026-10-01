# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v173_webui.py 模式；行为断言在
docs/uitest.py 补钉）。

（WebUI 布局与交互第六轮，六新 lens：对齐网格律/间距节奏律/
响应式断点矩阵/交互反馈完备/跳转链路同源/视觉层级密度；P0=0，P1=0，
P2×4 全采纳，七条观察备案不立案）：
 1440 断点缝：wrap 跨断点一次性 +140px（1180→1320）而 statline/
    pulsewrap 仍锁 --kpiw=1168，1440-1919 全带卡内右缘 78px 空腔、同屏
    trend 卡全宽=跨卡右缘双轨（≥1920 空腔收敛同病灶半幅残留）。
    修法：.statline,#pulseLegend,.pulsewrap{max-width:none} 下放进
    @media(min-width:1440px) 块与 ≥1920 同律解锁（.grid/.kpisum 保持
    --kpiw 失比纪律）。
 光标 affordance 反信号：.hc/.pbar 挂 cursor:help 却点击开日志弹层/
    跳渠道健康（卡头文案明说「点击柱跳渠道健康」），help=「仅悬停读说明」
    与真实点击动作失配。修法：两处 cursor:pointer（title 悬停提示保留）。
 .pvbody a 推送预览正文链接真实可点（target=_blank）却无 hover 反馈，
    与 .toast:hover/a.vw:hover 同族先例不一致。修法：补:hover 下划线。
 明细子行（.stl）段间分隔 ' · ' 与段内 '·' 同字符两级歧义（生产峰值
    14 段行「准点100%·取消3% ｜ …」扫读无法分界）。修法：段间升级
    ' ｜ '（与行 title 的 ｜ 高层分隔语义一致），段内 '·' 不动。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v174_webui.py -q
"""


class TestWebuiV174Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_p1_1440_breakpoint_unlocks_nonratio_parts(self):
        """：非比例敏感件随 1440 断点解锁（1440-1919 空腔带回潮）。"""
        src = self._src()
        assert (".statline,#pulseLegend,.pulsewrap{max-width:none}" in src
                and "max-width:min(1320px,92vw)" in src), \
            "1440 解锁行丢失（断点缝空腔回潮）"
        # 下放进 1440 块：解锁行必须出现在 1440 media 声明之后、1920 块之前
        i1440 = src.index("min-width:1440px")
        i_unlock = src.index(".statline,#pulseLegend,.pulsewrap{max-width:none}")
        i1920 = src.index("min-width:1920px")
        assert i1440 < i_unlock < i1920, \
            "解锁行不在 1440 块内（仍在 ≥1920 独占=断点缝残留）"

    def test_p2_clickable_cells_use_pointer_cursor(self):
        """：.hc/.pbar 点击有动作必须 pointer（help 反信号回潮）。"""
        src = self._src()
        hc = src.index(".hc{width:6px")
        pbar = src.index(".pbar{flex:1")
        assert "cursor:help" not in src[hc:hc + 200], \
            ".hc 仍挂 cursor:help（点击开日志弹层与光标语义失配）"
        assert "cursor:help" not in src[pbar:pbar + 200], \
            ".pbar 仍挂 cursor:help（点击跳渠道健康与光标语义失配）"

    def test_p3_pvbody_link_hover_feedback(self):
        """：推送预览正文链接有 hover 反馈（可点无反馈回潮）。"""
        src = self._src()
        assert ".pvbody a:hover{text-decoration:underline}" in src, \
            ".pvbody a 缺 hover 反馈（与 .toast:hover/a.vw:hover 同族律）"

    def test_p4_stl_segment_separator_two_levels(self):
        """：明细子行段间 ' ｜ ' 与段内 '·' 两级分明（同符歧义回潮）。"""
        src = self._src()
        assert "].filter(Boolean).join(' ｜ ')}</div>" in src, \
            "明细 .stl 子行段间分隔未升级 ' ｜ '（与段内 '·' 同符歧义）"
        # 段内 '·' 复合词保持不动（廊桥43%·机龄N年 同段内小层）
        assert "'·廊桥'+he(String(f.bridgeRate))+'%'" in src, \
            "段内 '·' 小层被误改（两级分隔律：段间 ｜/段内 ·）"
