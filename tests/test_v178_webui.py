# -*- coding: utf-8 -*-
"""v1.5.78 webui 回归（源码级钉，同 test_v176_webui.py 模式；行为断言在
docs/uitest.py 补钉 + _scratch/v178_c1_pin.py 单测）。

C-1 走势点→该轮明细入口（audit_v177 备案落地）：
 - 后端 routesArr 系列带 date 全日期（前端锁定 FLT.dates 的键）；
 - 前端 jumpTrendDetail 复用 jumpCalDate 联动路径（勿抄写第二份）；
 - canvas click / 键盘 Enter 双入口 + cursor affordance；
 - 图例承诺句条件在场（数据 N>0 且系列带 date 双前提）——
   「文案在场则承诺必死」jumpCalDate 条件化同律。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v178_webui.py -q
"""


class TestWebuiV178Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_routesarr_series_carries_full_date(self):
        """/api/state routesArr 系列必须带 date 全日期（YYYY-MM-DD）——
        走势点跳明细时 FLT.dates 锁定的就是它；缺它=跳转目标不存在。"""
        src = self._src()
        assert '"date": d0' in src, \
            "routes_arr 系列未带 date 全日期（C-1 跳转目标键缺失）"

    def test_jump_trend_detail_reuses_calendar_path(self):
        """jumpTrendDetail 定义在位且复用 jumpCalDate（联动路径单源）。"""
        src = self._src()
        assert "function jumpTrendDetail()" in src, \
            "jumpTrendDetail 未定义（走势点→明细入口缺失）"
        i0 = src.index("function jumpTrendDetail()")
        i1 = src.index("function ", i0 + 10)
        body = src[i0:i1]
        assert "jumpCalDate(" in body, \
            "jumpTrendDetail 未复用 jumpCalDate（联动路径双份抄写）"
        assert "curRoute().r.date" in body, \
            "jumpTrendDetail 未从当前系列取 date（跳转目标悬空）"

    def test_chart_click_and_keyboard_wired(self):
        """canvas click 与键盘 Enter 双入口都接到 jumpTrendDetail。"""
        src = self._src()
        i_click = src.index("$('chart').addEventListener('click'")
        i_end = src.index("\n", i_click)
        seg = src[i_click:i_click + 600]
        assert "jumpTrendDetail()" in seg, "canvas click 未接 jumpTrendDetail"
        assert "e.button!==0" in seg, "click 未过滤非主键（右键误跳）"
        assert "_tTap" in seg, "触屏滑动防误触守卫缺失（>8px 位移不跳）"
        i_end = src.index("$('chart').addEventListener('touchend'",
                   src.index("let _tTap"))
        endseg = src[i_end:i_end + 700]
        assert "_tTap=null" in endseg, \
            "touchend 未清 _tTap（混合设备残坐标误吞后续鼠标点击）"
        i_key = src.index("$('chart').addEventListener('keydown'")
        kseg = src[i_key:i_key + 900]
        assert "jumpTrendDetail()" in kseg, "键盘 Enter 未接 jumpTrendDetail"

    def test_cursor_affordance_on_chart(self):
        """canvas 可点须有 cursor affordance（v1.5.74 cursor affordance 律）。"""
        src = self._src()
        assert "#chart{cursor:pointer}" in src, \
            "#chart 无 pointer 光标（可点性无 affordance）"

    def test_hint_promise_conditional(self):
        """图例承诺句「点击看该航线当日明细」必须双前提条件在场：
        N>0（有点可点）且 CR.r.date（有处可跳）——空态死承诺防线。
        词面对齐实际行为（画布任意点命中=该系列航线+当日，日历族口径）。"""
        src = self._src()
        assert "点击看该航线当日明细" in src, "图例承诺句丢失"
        i0 = src.index("点击看该航线当日明细")
        seg = src[max(0, i0 - 200):i0]
        assert "CR.r.date" in seg and "N>0" in seg, \
            "承诺句未挂 N>0+CR.r.date 双前提（空态死承诺风险）"

    def test_canvas_aria_mentions_enter_jump(self):
        """canvas aria-label 补 Enter 跳转提示（键盘可达性闭环）。"""
        src = self._src()
        assert "aria-label=\"价格走势图：聚焦后按左右方向键逐点读数，Home/End 跳首尾，Enter 看该轮明细\"" in src, \
            "canvas aria-label 未含 Enter 跳转提示"

    # ---- tuniu 黑卡价透明标记：白名单 + 渲染门（三端同轮） ----

    def test_blackcard_whitelist_passthrough(self):
        """/api/state 载荷白名单透传 blackCard（缺它=孤儿键前端恒空）。"""
        src = self._src()
        assert '"blackCard": bool(f.get("blackCard"))' in src, \
            "白名单未透传 blackCard（爬虫键到不了渲染门）"

    def test_blackcard_render_tag(self):
        """「黑卡价」徽标挂在价格单元格（复用 .pretax 小标签样式，与
        fliggy「税前」同位——黑卡修饰的是价格本身，比埋进次行醒目；
        次行段数红线 14 不动）。词面与推送图槽位逐字同形「黑卡价」
        （锚定可见文本，title 里的字不算）。"""
        src = self._src()
        i0 = src.index("f.blackCard?'<span class=\"pretax\"")
        seg = src[i0:i0 + 170]
        assert ">黑卡价</span>" in seg and "title=" in seg, \
            "价格格黑卡徽标缺失/词面与推送图不一致或缺解释 title"

    def test_subrow_segment_capacity_still_14(self):
        """黑卡徽标不入次行段数组（v1.5.55 容量红线 14 语义维持）。"""
        page = self._src()
        m = None
        import re as _re
        m = _re.search(r"\$\{\[(.*?)\]\.filter\(Boolean\)\.join\(' ｜ '\)\}",
                       page, _re.S)
        assert m, "次行段数组锚点丢失"
        body = m.group(1)
        assert "blackCard" not in body, "黑卡徽标误入次行段（红线 +1）"

    # ---- audit_v178 P2 落地（焦点交接/原子换行/链接 nowrap） ----

    def test_p2_jump_focus_handoff(self):
        """跳明细后焦点交接明细 tab：原视图（日历格/走势 canvas）隐藏后
        焦点坠 body，键盘用户失位（audit_v178 P2-1）。"""
        src = self._src()
        i0 = src.index("function jumpCalDate(")
        i1 = src.index("\nfunction ", i0 + 10)
        body = src[i0:i1]
        assert '.mtab[data-t="details"]' in body, "焦点交接目标缺失"
        assert ".focus()" in body, "jumpCalDate 未做焦点交接"

    def test_p2_route_span_atomic_wrap(self):
        """航班列「航线 📈」1280-1440 档 mid-word 撕裂：route 文本
        inline-block 原子换行（audit_v178 P2-2）。"""
        src = self._src()
        i0 = src.index('${f.route?`<span class="stl">')
        seg = src[i0:i0 + 130]
        assert "display:inline-block" in seg, "route 文本非原子换行"

    def test_p2_kpisum_link_nowrap(self):
        """概览「查看明细 ▾ / 走势 ▾」768 档 ▾ 孤行折断：链接 nowrap
        （audit_v178 P2-3）。"""
        src = self._src()
        i0 = src.index("查看明细 ▾")
        seg = src[max(0, i0 - 240):i0]
        assert "white-space:nowrap" in seg, "kpisum 链接未 nowrap"

