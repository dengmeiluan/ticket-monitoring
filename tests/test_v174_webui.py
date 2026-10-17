# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v173_webui.py 模式；行为断言在
docs/uitest.py 补钉）。

（WebUI 布局与交互第六轮，六新 lens：对齐网格律/间距节奏律/
响应式断点矩阵/交互反馈完备/跳转链路同源/视觉层级密度；P0=0，P1=0，
P2×4 全采纳，七条观察备案不立案）：
 断点缝：wrap 跨渐进带断口而 statline/
    pulsewrap 仍锁 --kpiw=1168，宽带全带卡内右缘空腔、同屏
    trend 卡全宽=跨卡右缘双轨。
    修法：.statline,#pulseLegend,.pulsewrap{max-width:none} 下放进
    解锁块与 ≥1920 同律解锁（.grid/.kpisum 保持
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
        """：非比例敏感件随 1280 渐进带解锁（解锁与 wrap 托底释放
        同拍，渐进带内空腔归零）。"""
        src = self._src()
        # 上限统一 min(1716px,max(1180px,92vw))（渐进+托底封顶连续
        # 函数）——放宽语义保持，断点随托底释放点同步 1280。
        # r302 W1：纯 none 退役（≥1726 双轴回潮病灶形态），四族同上限
        assert (".statline,#pulseLegend,.pulsewrap"
                "{max-width:min(1440px,100%)}" in src
                and "max-width:min(1716px,max(1180px,92vw))" in src), \
            "1280 放宽行丢失（断点缝空腔回潮）"
        # 放宽行必须出现在 1280 media 声明之后、1920 块之前
        i1280 = src.index("min-width:1280px")
        i_unlock = src.index(
            ".statline,#pulseLegend,.pulsewrap{max-width:min(1440px,100%)}")
        i1920 = src.index("min-width:1920px")
        assert i1280 < i_unlock < i1920, \
            "放宽行不在 1280 块内（仍在 ≥1920 独占=断点缝残留）"

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
