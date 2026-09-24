# -*- coding: utf-8 -*-
"""v1.5.80 webui 回归（源码级钉，同 test_v178_webui.py 模式）。

v180 渠道字段三端收口：ctrip agePolicy 白名单透传 + 价格格 ⚠ 徽标
（demo 目检）；bizPrice 既有通道钉死防丢（tuniu/tongcheng 新接入零
前端改动依赖它）；demo 三渠道 bizPrice + ctrip agePolicy 对齐。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v180_webui.py -q
"""


class TestWebuiV180Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- ctrip agePolicy：白名单 + 渲染门（三端同轮） ----

    def test_agepolicy_whitelist_passthrough(self):
        """/api/state 载荷白名单透传 agePolicy（缺它=孤儿键前端恒空）。"""
        src = self._src()
        assert '"agePolicy": (f.get("agePolicy") or "").strip()' in src, \
            "白名单未透传 agePolicy（爬虫键到不了渲染门）"

    def test_agepolicy_render_warn_badge(self):
        """价格格 ⚠限XX价 徽标（pretax 同位；⚠+--warn 与孤低价警告同
        语义族=「这个价有坑」；title 说清后果：误购无法出行——资格受限（年龄/会员）通用语义）。"""
        src = self._src()
        assert "f.agePolicy?" in src, "价格格 agePolicy 徽标缺失"
        i0 = src.index("f.agePolicy?")
        seg = src[i0:i0 + 260]
        assert "pretax" in seg, "徽标未复用 pretax 同位样式"
        assert "title=" in seg and "出行" in seg, \
            "徽标缺 title 或未说明误购无法出行后果"
        assert "${f.agePolicy}" in seg, "徽标词面未携带档位词（限青年/限老年/限年龄）"

    def test_agepolicy_not_in_subrow(self):
        """agePolicy 徽标不入次行段数组（v1.5.55 容量红线 14 维持）。"""
        import re as _re
        page = self._src()
        m = _re.search(r"\$\{\[(.*?)\]\.filter\(Boolean\)\.join\(' ｜ '\)\}",
                       page, _re.S)
        assert m, "次行段数组锚点丢失"
        assert "agePolicy" not in m.group(1), "agePolicy 误入次行段（红线 +1）"

    # ---- bizPrice 通道：tuniu/tongcheng 接入零前端改动依赖它 ----

    def test_bizprice_tunnel_unchanged(self):
        """bizPrice 白名单通道在位（v1.5.55 七批建，三渠道共用）。"""
        src = self._src()
        assert '"bizPrice": _int_or_none(f.get("bizPrice"))' in src, \
            "bizPrice 白名单通道丢失（tuniu/tongcheng 接入变孤儿键）"

    # ---- demo 对齐：渲染门/CSV 目检数据源 ----

    @staticmethod
    def _demo_src():
        import core.demo as _d
        with open(_d.__file__, encoding="utf-8") as f:
            return f.read()

    def test_demo_carries_agepolicy_and_bizprice(self):
        """demo：ctrip 行带 agePolicy、tuniu/tongcheng 行带 bizPrice
        （渲染门目检与 CSV 列演示的数据源；缺它=演示页看不到新字段）。"""
        demo = self._demo_src()
        assert 'fs[0]["agePolicy"]' in demo, "demo ctrip 行缺 agePolicy"
        assert demo.count('fs[0]["bizPrice"]') >= 3, \
            "demo bizPrice 演示未覆盖 ctrip/tongcheng/tuniu 三渠道"

    # ---- audit_v180 P1/P2 落地（WebUI 审计报告） ----

    def test_p1_statline_two_col_narrow(self):
        """P1-1：≤760 带强制 statline 2 列——auto-fit 折 3 轨带
        （容器 474-632px≈视口 547-745）4 格变 3+1，第二行空轨露容器
        --line 灰底（缝隙法容器底外露）。2 列 4 格整除零空腔，纯 CSS
        零量纲（renderPulse 幽灵格方案在 display:none 容器量纲全零）。"""
        src = self._src()
        m = None
        import re as _re
        for m in _re.finditer(r"@media\(max-width:760px\)\{", src):
            seg = src[m.start():m.start() + 600]
            if ".statline{grid-template-columns:repeat(2,1fr)}" in seg:
                return
        assert False, "≤760 媒体块缺 statline 2 列规则（窄带灰底空腔仍在）"

    def test_p1_cfg_head_not_squeezed(self):
        """P1-2：配置卡头标题 flex:1（basis:0）被 nowrap 胶囊压到
        min-content=一字一行竖排——min-width 保底 + flex-wrap 让胶囊
        换行；rline 工具条同律。"""
        src = self._src()
        assert ".uhead2 b{flex:1;min-width:8em" in src, \
            "uhead2 标题缺 min-width 保底（窄带竖排字仍在）"
        i0 = src.index(".uhead2{")
        assert "flex-wrap:wrap" in src[i0:i0 + 200], \
            "uhead2 缺 flex-wrap（胶囊挤压标题不换行）"
        i1 = src.index('class="rline" style="display:flex')
        assert "flex-wrap:wrap" in src[i1:i1 + 120], \
            "rline 工具条缺 flex-wrap（添加用户/保存钮挤压标题）"

    def test_p2_notify_oktxt_contrast(self):
        """P2-2：NOTIFY_PAGE 孪生页 --ok-txt 令牌同步（主控台 P2-3 已
        收口、孪生页漏同步——.hitbar b 绿字对绿底 4.28:1 欠 AA）。"""
        src = self._src()
        i_notify = src.index("NOTIFY_PAGE")
        seg = src[i_notify:]
        assert "--ok-txt" in seg, "NOTIFY 页缺 --ok-txt 令牌"
        i_hit = seg.index(".hitbar b{")
        assert "var(--ok-txt)" in seg[i_hit:i_hit + 80], \
            "hitbar 绿字未消费 --ok-txt（4.28:1 欠 AA 仍在）"

    def test_p2_kpi_aria_uses_platcn(self):
        """P2-1：KPI aria-label 渠道名与可见 tooltip 同语言（读屏听到
        ctrip、明眼看到携程=双语分裂；platCn 与 numlink title 同源）。"""
        src = self._src()
        i0 = src.index("打开行情页（")
        assert "${platCn" in src[i0 - 40:i0 + 80], \
            "KPI aria-label 未消费 platCn（读屏渠道名仍是英文键）"

    def test_p2_trend_jump_focus_handoff(self):
        """P2-3：jumpRowTrend/jumpQual 跳转后焦点交接（jumpCalDate 有、
        同族两处漏——切视图后焦点坠 body，键盘 Tab 从头数）。"""
        src = self._src()
        i0 = src.index("function jumpRowTrend(")
        body = src[i0:src.index("\nfunction ", i0 + 10)]
        assert 'querySelector(\'.mtab[data-t="trend"]\')' in body \
            and ".focus()" in body, "jumpRowTrend 缺焦点交接"
        i1 = src.index("function jumpQual(")
        body1 = src[i1:src.index("\nfunction ", i1 + 10)] \
            if "\nfunction " in src[i1:i1 + 1200] else src[i1:i1 + 600]
        assert '.mtab[data-t="details"]' in body1 and ".focus()" in body1, \
            "jumpQual 缺焦点交接"

    def test_p2_filter_chips_empty_neutral(self):
        """P2-5：筛选 chips 默认「全选=全亮」12+ 枚实心蓝稀释选中语义
        ——初始空集（空集=全部语义已在过滤消费点 L1720-1722 在案），
        视觉中性，用户降选动作才有对比。三组集合 chips 同律。"""
        src = self._src()
        assert "else{FLT.plats=new Set();FLT._platsInit=true;}" in src, \
            "渠道 chips 仍初始回填全亮"
        assert "FLT.dates=new Set(keep.length?keep:new Set());" in src, \
            "日期 chips 仍初始回填全亮"
        assert "FLT.routes=new Set(keep.length?keep:new Set());" in src, \
            "航线 chips 仍初始回填全亮"

    def test_p2_touch_first_tap_reads(self):
        """P2-6：触屏首 tap=读数（保留 hover 十字线）、同点二次 tap=跳
        明细——旧形态轻 tap 直接离场，移动端既读不到数值也无法「点一下
        看看」而不换页。"""
        src = self._src()
        for anchor in ("let _tPin=null", "let _tGo=false", "let _tTouch=false"):
            assert anchor in src, f"触屏读数状态位缺失：{anchor}"
        i0 = src.index("let _tTouch=false")
        seg = src[src.index("$('chart').addEventListener('click'", i0):]
        assert "_tGo" in seg[:600] and "jumpTrendDetail" in seg[:600], \
            "click 路径未消费二次 tap 放行位（首 tap 仍直接跳转离场）"

    def test_p2_ios_blocks_crossref(self):
        """P2-8（审计建议修正案）：coarse 块与 ≤760 块条件语义不同
        （900+粗指针 vs 760 任意指针，删 coarse 丢 iPad 竖屏 16px 保护）
        ——不合并，改注释互指防清单漂移。"""
        src = self._src()
        n = src.count("font-size:16px}")
        assert "三处 16px 清单互指" in src, "16px 规则块缺互指注释（漂移风险）"

    def test_p2_srow_inputs_named(self):
        """P2-10：srow/gcell 输入程序化标签关联（渲染后 aria 自动
        关联 .slab b 标题——读屏匿名控件清零，单点后处理覆盖全部行）。"""
        src = self._src()
        assert "aria-label'" in src and ".slab b" in src, \
            "srow 输入缺 aria 自动关联（读屏匿名）"

    def test_p2_pulse_catch_has_note(self):
        """P2-7：/api/pulse 失败分支静默须显式论证（LESSONS 二十三：
        每个异步终点都要有落点——「有则显示」性质的论证注释）。"""
        src = self._src()
        i0 = src.index("/api/pulse")
        seg = src[i0:i0 + 400]
        assert "catch(e){}" in seg and ("有则显示" in seg or "静默" in seg), \
            "/api/pulse catch 缺静默论证注释"
