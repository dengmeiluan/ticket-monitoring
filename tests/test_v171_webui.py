# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v170_webui.py 模式；行为断言在
docs/uitest.py 补钉）。

（WebUI 布局美感与交互完整性第三轮；P0=0，P1×1+P2×4 全采纳）：
 .glcell input:hover/:focus 补:not(.switch) 豁免——原 outline:none 吞掉
    全局参数三枚开关键盘焦点环（srow/fbar 对照均有 UA 环，真实 Tab 实测
    outline 3px none 仅剩 1px 25% 底线不可辨＝交互死区）；数字/文本输入
    样式零变化。
P2-A .tj（明细行 📈 跳走势，v166 新件）入触控热区外扩家族：
    position:relative +::after inset:-9px -4px（纵向补 18px 高到触控基准，
    横向 -4px 同 .tg 先例——右侧紧邻 ↗ vw 链接防吃相邻命中）。
P2-B 健康时间线弹性档门槛 1440→1024：1180/1280/1366 主流本带（wrap 1180
    封顶）恒 214px 左聚空腔（同病灶半幅残留）；1024 视口容器
    814px ≥ 格带本宽 768px 不溢出；<1024 保固定 6px + xhint 横滚暗示。
P2-C glcell 文本输入 16px 防放大：内联 13px 锁定致 iOS 聚焦自动放大且
    不回位，≤760 与 coarse 两份清单各补 .glcell input[type=text] 带
    !important 压内联（桌面观感不变）。
P2-D NOTIFY_PAGE 令牌在册漂移收口：亮色 --mut #617384→#5a6c7d（主站 AA
    收深时轻页未跟， 立的「notify 独立:root 令牌须随主站在册」规
    下最后残留）；.logo 圆角 7px→--r3:9px 令牌（主站 --r3 同值）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v171_webui.py -q
"""


class TestWebuiV171Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def _notify_src(self):
        src = self._src()
        return src[src.index("NOTIFY_PAGE"):]

    def test_p1_glcell_switch_focus_not_swallowed(self):
        """：glcell hover/focus 豁免 .switch，开关回落 UA 焦点环。"""
        src = self._src()
        assert ".glcell input:not(.switch):hover{border-bottom-color:var(--mut)}" in src, \
            "glcell hover 未豁免 .switch"
        assert ".glcell input:not(.switch):focus{outline:none;" in src, \
            "glcell focus 未豁免 .switch"
        # 旧形态（吞焦点环的无豁免 focus 规则）必须消失
        assert ".glcell input:focus{" not in src, \
            "存在未豁免 .switch 的 glcell focus 规则（键盘焦点环被吞回潮）"

    def test_p2a_tj_hitzone_family(self):
        """P2-A：.tj 入热区家族（relative +::after inset:-9px -4px）。"""
        src = self._src()
        assert ".dchip .dx,.pvx,a.vw,.hc,.tj{position:relative}" in src, \
            ".tj 未入 position:relative 组"
        assert ".tj::after{content:'';position:absolute;inset:-9px -4px}" in src, \
            ".tj 缺 ::after 热区外扩"

    def test_p2b_health_cells_elastic_breakpoint(self):
        """P2-B：弹性档门槛 1024（1440 旧档消失），1180-1439 空腔收口。"""
        src = self._src()
        assert "@media(min-width:1024px){\n  .hc{width:auto;flex:1 1 6px}\n }" in src, \
            "健康时间线弹性档门槛未降到 1024"
        assert "@media(min-width:1440px){\n  .hc{width:auto;flex:1 1 6px}\n }" not in src, \
            "1440 旧弹性档残留（1180-1439 空腔回潮）"

    def test_p2c_glcell_text_16px_two_media(self):
        """P2-C：≤760 与 coarse 两份清单各补 glcell 16px !important。"""
        src = self._src()
        n = src.count(".glcell input[type=text]{font-size:16px!important}")
        assert n == 3, "glcell 16px 防放大钉应恰在三份触控媒体清单(≤760/≤900/901+): %d" % n

    def test_p2c_glcell_input_explicit_text_type(self):
        """P2-C 伴随钉：glcell text/ro 型显式输出 type="text"——原生成
        `<input`（省略 type 属性）令 input[type=text] 选择器命中 0 元素，
        16px 防放大钉空转（行为钉预演抓回：HTML 默认 text 但属性选择器
        不认隐式形态）。"""
        src = self._src()
        assert '(type===\'text\'||type===\'ro\')?\' type="text"\':\' type="number"\'' in src, \
            "glcell 未显式输出 type=\"text\"（16px 防放大钉空转回潮）"

    def test_p2d_notify_tokens_aligned(self):
        """P2-D：notify --mut 对齐主站 #5a6c7d；.logo 圆角走 --r3 令牌。"""
        nsrc = self._notify_src()
        assert "--mut:#5a6c7d" in nsrc, "notify 亮色 --mut 未对齐主站"
        assert "--mut:#617384" not in nsrc, "notify 旧 --mut 值残留"
        assert "--r3:9px" in nsrc, "notify :root 缺 --r3 令牌"
        assert ".logo{width:26px;height:26px;border-radius:var(--r3);" in nsrc, \
            "notify .logo 圆角未走 --r3 令牌"
        assert "border-radius:7px" not in nsrc, "notify .logo 旧 7px 硬编码残留"
