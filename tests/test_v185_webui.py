# -*- coding: utf-8 -*-
"""v1.5.85 webui 三端同轮钉(seatTilt 白名单+渲染门)。

seatTilt(ctrip classinfor.seattilt,座椅倾斜角度 100~180°)三端:
crawlers 落键 → webui 白名单透传(int 协议,_int_or_none 先例)→
渲染门=明细行 cabinCode 悬停 title 注记 + CSV「座椅倾斜」列
(明细次行段数组容量红线 14 已满,不加段元素——LESSONS 明细次行段
容量红线;title/CSV 零布局风险)。

运行:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v185_webui.py -q
"""


class TestWebuiSeatTilt:
    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_whitelist_passthrough_int(self):
        src = self._src()
        # 白名单透传:int 协议转写(非数字→None 前端不占位,七批先例)
        assert '"seatTilt": _int_or_none(f.get("seatTilt"))' in src, \
            "webui 白名单缺 seatTilt 透传(int 协议)"

    def test_cabin_code_title_annotation(self):
        src = self._src()
        # 渲染门:cabinCode 悬停 title 并注座椅倾斜(ctrip cabinCode
        # 100% 在场与 seatTilt 同源配对;缺一不注)
        assert "座椅倾斜" in src and "seatTilt" in src, \
            "cabinCode title 缺座椅倾斜注记"

    def test_csv_column(self):
        src = self._src()
        # CSV「座椅倾斜」列:cabinCode 列之后(导出分析消费面)
        i0 = src.index("(f.cabinT||'').replace(/<[^>]*>/g,'')")
        seg = src[i0:i0 + 400]
        assert "seatTilt" in seg, "CSV 缺座椅倾斜列(cabinCode 列后)"


class TestAuditV185Design:
    """r184 WebUI 审计落地钉(P1×1+P2×7,设计层)。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_p1_pulse_legend_centered_at_1440(self):
        src = self._src()
        # ≥1440 解锁后 statline 全宽/柱区居中/图例左贴边三轴分裂——
        # 图例与柱区同轴。同轴条件全宽度域无条件生效（柱区 center
        # 全宽域生效；窄档少轮次双轴残留一并收口，覆盖钉在
        # test_v188_webui）
        assert "#pulseLegend{justify-content:center}" in src, \
            "图例未与脉冲柱区同轴居中"

    def test_p2_jump_entries_declare_filter_reset(self):
        src = self._src()
        # pill 与「全线最低」mchip 跳转会隐式 resetFlt 清用户筛选——
        # title 必须声明副作用,jumpQual 落地后 toast 同步告知
        assert src.count("将重置现有筛选") >= 2, \
            "pill/mchip title 未声明 resetFlt 副作用"
        i0 = src.index("function jumpQual()")
        assert "toast(" in src[i0:i0 + 400], "jumpQual 缺落地 toast"

    def test_p2_tablist_semantics(self):
        src = self._src()
        # 三族标签页(监控 tabs/明细筛选 tabs/配置导航)补 tablist/tab
        # +aria-selected 动态回写(mkactAll 同源挂载)
        assert "function tabAria()" in src, "tabAria 助手缺"
        assert "setAttribute('aria-selected'" in src, "aria-selected 回写缺"

    def test_p2_form_a11y_trio(self):
        src = self._src()
        assert 'aria-label="搜索配置项"' in src, "#cfgSearch 缺 label"
        assert 'id="fltBtn" aria-expanded="false"' in src, \
            "#fltBtn 初始 aria-expanded 缺"
        assert 'aria-expanded' in src.split("function togFlt")[1][:600], \
            "togFlt 未同步 aria-expanded"
        i0 = src.index('id="savebar"')
        assert 'role="status"' in src[i0 - 40:i0 + 60], "savebar 缺 role=status"

    def test_p2_montabs_grid_narrow(self):
        src = self._src()
        # ≤390 四片 3+1 折行「渠道健康」孤片成行——≤760 两列网格
        assert "@media(max-width:760px){#montabs{display:grid;grid-template-columns:1fr 1fr;gap:8px}}" \
            in src, "montabs 窄档未改两列网格"

    def test_p2_pulse_legend_swatch_uniform(self):
        src = self._src()
        # 图例双色票形制同排(渠道 12×8 方块 vs 红帽 18×4 细条)——
        # 红帽改与渠道同规格 inline i
        assert '<i style="background:var(--red);width:12px;height:8px' in src, \
            "红帽色票未统一 12×8 形制"

    def test_p2_pill_static_affordance(self):
        src = self._src()
        assert ".pill::after{content:" in src, "pill 缺静态可点线索"

    def test_p2_kbd_tips_block_narrow(self):
        src = self._src()
        assert "@media(max-width:760px){.kbdtips{display:block;margin:6px 0 0;margin-left:0}}" \
            in src, "窄窗快捷键教学未独立成行"
