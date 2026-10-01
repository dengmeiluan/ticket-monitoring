# -*- coding: utf-8 -*-
"""r192 WebUI 回归（源码级钉，同 test_v191 模式）。

- 修 1（点击闪烁）：弹层开合摘视口滚动条 → 内容横移 ~17px（开/关各
  跳一次）=「健康格点击闪烁不丝滑」的机械根因。修法双层：
  CSS `scrollbar-gutter:stable`（现代浏览器 gutter 常驻零位移）+
  JS 滚动条宽度补偿（padding-right 垫平，老内核兜底）。
- 修 2（点击卡顿）：明细表全量 innerHTML 重建实测 549 班 ~214ms
  （布局 122ms + 解析 40ms + 拼串 ~50ms）——排序/筛选/chip/每拍刷新
  每次点击都是 200ms 长任务。修法：切片渲染（首拍只渲 120 行，
  滚动近底按需续载），旧「已显示前 300 班」截断提示退役。
- 修 3（弹层背后闪帧）：弹层开着（半透明可透视背景）时 10s 轮询
  照常全量重渲 = 点击/阅读间隙背后闪一帧。load() 整拍跳过
  （LASTTXT 不吞，关弹层后下一拍自然补上）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v192_webui.py -q
"""


class TestWebuiV192Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- 修 1：弹层开合零布局位移 ----

    def test_scrollbar_gutter_stable(self):
        """viewport gutter 常驻：现代 Chrome/Edge 弹层开合内容零横移。"""
        src = self._src()
        assert "scrollbar-gutter:stable" in src, \
            "html 缺 scrollbar-gutter:stable（弹层开合仍会横移）"

    def test_pv_mask_scroll_compensate(self):
        """老内核兜底：锁滚前量滚动条宽垫 padding-right，关弹层复位。"""
        src = self._src()
        i0 = src.index("function _openPvMask()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert ("window.innerWidth-document.documentElement.clientWidth") \
            in seg, "_openPvMask 缺滚动条宽度测量（老内核仍横移）"
        assert "paddingRight" in seg, "_openPvMask 缺 padding-right 补偿"
        # closePv 必须复位补偿，否则关弹层后右侧多一条空白垫
        j0 = src.index("function closePv()")
        j1 = src.index("function ", j0 + 10)
        jseg = src[j0:j1]
        assert "paddingRight=''" in jseg, "closePv 未复位 padding-right"

    # ---- 修 2：明细表切片渲染 ----

    def test_table_chunked_render(self):
        """table() 首拍只渲首屏切片，滚动续载取代 300 行一次性重建。"""
        src = self._src()
        i0 = src.index("function table()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert "const CAP=300" not in seg, \
            "旧 300 行一次性截断仍在（点击卡顿根因未除）"
        assert "_chunkHtml(0)" in seg, "table() 未接入首屏切片"
        assert "_tblAppend" in seg, "table() 滚动位深于首屏时未补切片"
        assert "function _tblAppend" in src, "缺切片续载单源函数"
        assert "const _CHUNK=" in src, "缺切片尺寸常量"
        assert "function _chunkHtml" in src, "缺切片 HTML 构建单源"
        # 续载行不再播入场动画（滚动追加行延迟渐显=越滚越"卡"的观感）
        assert "animation:none" in src.split("function _chunkHtml")[1] \
            .split("function ")[0], "续载切片行缺 animation:none"

    def test_table_scroll_append_listener(self):
        """.tw 滚动近底预取下一切片（passive 不阻塞滚动合成）。"""
        src = self._src()
        assert ("#tablecard .tw") in src, "缺滚动容器监听锚"
        i0 = src.index("addEventListener('scroll'")
        seg = src[max(0, i0 - 200):i0 + 300]
        assert "{passive:true}" in seg, "滚动监听缺 passive（合成器阻塞）"
        assert "_tblAppend" in seg, "滚动监听未接续载"

    # ---- 修 3：弹层开着跳过整拍轮询 ----

    def test_load_defer_while_popup(self):
        """弹层开着 load() 整拍跳过：背后重渲闪帧 + 抢主线程。"""
        src = self._src()
        i0 = src.index("async function load()")
        i1 = src.index("LOADN=true", i0)
        seg = src[i0:i1]
        assert ("$('pvMask').classList.contains('on')") in seg, \
            "load() 未在弹层开启时整拍跳过"
