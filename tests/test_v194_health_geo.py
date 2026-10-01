# -*- coding: utf-8 -*-
"""r194 渠道健康格带「抖动」回归（源码级钉，同 v192/v191 模式）。

根因（2026-09-24 真机 Playwright 实测）：
  `.hcells{...;overflow-x:auto;padding:11px 0;margin:-9px 0}` —— 按 CSS
  规则 overflow-x 非 visible 会把 overflow-y 的 visible 计算值强制成
  auto，于是 `.hcells` 是**双轴滚动容器**。两处溢出因此变成真滚动条：
    ① `.hc::after{inset:-11px -1px}` 触控热点横向外扩 1px → 末格热点
       越过内容右缘 → `scrollWidth = clientWidth + 1`（真机 971 vs 970）
       → 横向滚动条**恒在**，且在 37px 衬垫框内吃掉纵向空间。
    ② hover 时 `.hc{transform:scaleY(1.35)}` 把**伪元素一起放大**
       （::after 是格本体的子级）→ 原本恰好铺满 37px 衬垫框的热点涨到
       ~50px → `scrollHeight 37→43` → 纵向滚动条闪现。
  而 ≥1024 档 `.hc{width:auto;flex:1 1 6px}` 是**弹性格**：纵向滚动条
  一出现，`clientWidth` 少一条滚动条宽（Windows 经典滚动条 17px）→
  整行 74+ 格全部收缩重排 → 鼠标扫过格带时逐格"呼吸"=用户所述抖动。

修法：桌面弹性档让 `.hcells` **不再是滚动容器**（overflow:clip，回退
overflow:hidden），基础规则把 y 轴改为恒定裁剪（overflow-y:hidden）——
滚动条与可滚区都不复存在，热点外扩与 hover 放大都不再改变几何。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
        tests/test_v194_health_geo.py -q
"""


class TestHealthCellsNoScrollbar:
    """webui.py 源码级钉死（渠道健康格带零滚动条/零重排）。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _rule(src, marker):
        """取以 marker 开头的那条 CSS 声明（到 '}' 为止）。"""
        i = src.index(marker)
        return src[i:src.index("}", i) + 1]

    @staticmethod
    def _media(src, marker):
        """取 marker 那个 @media 块的整段（到首个行首收尾括号为止）。

        收尾括号在本文件有两种缩进形态（`\\n}` 与 `\\n }`，块内语句
        另起一行时缩进一格），取先到者。"""
        i = src.index(marker)
        ends = [j for j in (src.find("\n}", i), src.find("\n }", i)) if j >= 0]
        j = min(ends)
        return src[i:j + 3]

    # ---- 修 A：基础规则掐掉被强制出来的纵向滚动条 ----

    def test_base_rule_y_axis_clipped(self):
        """.hcells 基础规则：x 窄档仍需可滚，y 必须恒定裁剪。

        `overflow-x:auto` 单独出现会让 overflow-y 计算值变 auto，
        hover 放大 ::after 即出纵滚条（真机 scrollHeight 37→43）。"""
        seg = self._rule(self._src(), ".hcells{display:flex")
        assert "overflow-x:auto" in seg, "窄档横向滚动能力被误删（390 档退化）"
        assert "overflow-y:hidden" in seg, \
            ".hcells 未把 y 轴改为恒定裁剪（hover 仍会闪纵滚条）"

    # ---- 修 B：桌面弹性档不再是滚动容器 ----

    def test_desktop_tier_not_scroll_container(self):
        """≥1024 弹性档：格带恒等于容器宽 → 必须非滚动容器。

        否则 1px 热点外扩 → 横滚条恒在；纵滚条闪现 → 弹性格全行重排。"""
        src = self._src()
        seg = self._media(src, "@media(min-width:1024px){")
        assert ".hcells{overflow:hidden;overflow:clip}" in seg, \
            "≥1024 档 .hcells 仍是滚动容器（滚动条→弹性格重排=抖动）"
        assert ".hc{width:auto;flex:1 1 6px}" in seg, \
            "≥1024 档弹性格铺满规则丢失"

    # ---- 回归护栏：不得把 v1.5.91 的触控热区修复一起改坏 ----

    def test_keeps_v191_hotspot_fix(self):
        """padding/margin 三件套 + ::after 热区尺寸不许被顺手改掉。

        裁剪切点=衬垫框（37px），热点纵向 -11px 恰好铺满衬垫框——
        改 padding 会让热点被裁、改 ::after 会让相邻格热区互相覆盖。"""
        src = self._src()
        seg = self._rule(src, ".hcells{display:flex")
        assert "padding:11px 0" in seg, "衬垫高度被改（热点纵向被裁）"
        assert "margin:-9px 0" in seg, "负 margin 回收丢失（行高回涨）"
        assert "pointer-events:none" in seg, \
            "容器事件穿透丢失（衬垫吞点击回归）"
        hot = self._rule(src, ".hc::after{")
        assert "inset:-11px -1px" in hot, \
            "热点 inset 被改（-1px 防串格 / -11px 触控基准纪律）"
