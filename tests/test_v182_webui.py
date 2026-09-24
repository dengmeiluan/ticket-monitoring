# -*- coding: utf-8 -*-
"""v1.5.82 webui 回归（源码级钉，同 test_v181_webui.py 模式）。

audit_v182 八案（fresh lens：三态完备性/键盘读屏/性能感知/文案微交互）：
- P2-1 /api/state 500 错误体分支落点（无旧数据→_markStale；有旧数据→保旧不 clobber）
- P2-2 /api/health 500 错误体保陈旧（与 catch 分支政策对齐）
- P2-3 零轮次空态教学句（「恢复全部 0 班」误导根除）
- P2-4 脉冲柱/健康格 roving tabindex（400+ 拍 Tab 穿越负担根除）
- P2-5 图标按钮 aria-label×4 + 排序表头 aria-sort + 税前徽标 title
- P2-6 明细表 >300 行渲染截断+表尾指路（350-600ms 主线程冻结缓解；CSV 恒全量）
- P2-7 toast 错误词面统一（信息类去 err 红边；j.err 直透点 heFriendly 包裹）
- P2-8 日历格日期 MM-DD → MM/DD 与全站斜杠轨统一

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v182_webui.py -q
"""


class TestWebuiV182Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- P2-1 /api/state 错误体分支落点 ----

    def test_state_errbody_branch(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 1400]
        # 错误体（无 users）显式分支在场，且双形态各有落点
        assert "j&&j.users" in seg or "j && j.users" in seg, \
            "load() 未区分错误体与正常载荷"
        assert "_markStale('服务异常')" in seg, \
            "冷启动错误体未落 _markStale（词面与骨架同轨）"

    # ---- P2-2 /api/health 错误体保陈旧 ----

    def test_health_errbody_keep_stale(self):
        src = self._src()
        i0 = src.index("function renderHealth")
        seg = src[i0:i0 + 700]
        assert "healthcard').style.display!=='none')return" in seg, \
            "renderHealth 已有时间线时不保陈旧（500 掀翻时间线病面仍在）"

    # ---- P2-3 零轮次空态教学句 ----

    def test_empty_state_teaching(self):
        src = self._src()
        i0 = src.index("没有符合条件的航班")
        seg = src[max(0, i0 - 260):i0]
        assert "u.flights.length?" in seg or "flights.length?" in seg.replace(" ", ""), \
            "erow 未按「零数据 vs 筛选空」分叉"
        assert "本轮尚无采集数据" in src, "零轮次教学句不在场"

    # ---- P2-4 roving tabindex ----

    def test_roving_tabindex_pulse_health(self):
        src = self._src()
        assert "function _roving" in src, "缺 _roving 方向键移动函数"
        # 脉冲柱族：rv 标记（data-rv+动态 tabindex）在 renderPulse 内定义
        i0 = src.index("function renderPulse")
        seg = src[i0:i0 + 2400]
        assert "data-rv" in seg and 'tabindex="${i===0?0:-1}"' in seg, \
            "脉冲柱未挂 roving 标记/动态 tabindex"
        assert seg.count("${rv}") >= 2, "zero/普通两分支未都引用 rv"
        # 健康格族：data-rv+首格锚该渠道首个可交互格（非轮位 0——
        # 首轮缺扫时 .hc none 无 tabindex，按轮位锚=该族零停靠点）
        i1 = src.index('class="hc ${c.s}"')
        seg1 = src[max(0, i1 - 300):i1 + 400]
        assert "data-rv" in seg1 and 'tabindex="${ri===firstIdx?0:-1}"' in seg1, \
            "健康格未挂 roving 标记/动态 tabindex"
        assert "findIndex(r=>(r.plats||{})[p])" in seg1, \
            "roving 首格未锚首个可交互格（渠道首轮缺扫=零停靠点回退）"

    # ---- P2-5 读屏语义 ----

    def test_icon_buttons_aria_label(self):
        src = self._src()
        i0 = src.index('id="ntBtn"')
        seg = src[max(0, i0 - 60):i0 + 160]
        assert "aria-label" in seg, "通知按钮缺 aria-label"
        i1 = src.index('id="themeBtn"')
        assert "aria-label" in src[max(0, i1 - 60):i1 + 160], \
            "主题按钮缺 aria-label"
        i2 = src.index('id="denBtn"')
        assert "aria-label" in src[max(0, i2 - 60):i2 + 160], \
            "密度按钮缺 aria-label"
        i3 = src.index('class="pvx"')
        assert "aria-label" in src[max(0, i3 - 60):i3 + 160], \
            "弹层关闭钮缺 aria-label"

    def test_sort_header_aria_sort(self):
        src = self._src()
        i0 = src.index('class="srt${SORT.k===k?')
        seg = src[i0:i0 + 400]
        assert "aria-sort" in seg, "排序表头缺 aria-sort"

    def test_pretax_title(self):
        src = self._src()
        i0 = src.index('税前</span>')
        seg = src[max(0, i0 - 120):i0]
        assert "title=" in seg and "机建燃油" in seg, \
            "「税前」徽标缺解释 title（同格家族唯一漏网）"

    # ---- P2-6 明细表渲染截断 ----

    def test_table_render_cap(self):
        src = self._src()
        i0 = src.index("function table()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert "const CAP=" in seg, "table() 无渲染截断常量"
        assert "shown" in seg, "渲染循环未切换到截断后的 shown"
        assert "导出 CSV" in seg, "截断提示行缺 CSV 指路"

    # ---- P2-7 toast 错误词面统一 ----

    def test_toast_wordface(self):
        src = self._src()
        assert "function heFriendly" in src, "缺 heFriendly 友好化单源"
        # 全函数窗（截到下一函数）：后段新增 toast 也入钉
        i0 = src.index("function expCsv()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert ",'err')" not in seg, "expCsv 信息类 toast 仍挂 err 红边"
        # 三处直透点全部包裹
        for anchor in ("toast(j.err||'读取失败'", "toast(j.err||'预览失败'",
                       "toast(j.err||'启动失败'"):
            assert anchor not in src, f"j.err 直透点未包裹：{anchor}"

    # ---- P2-8 日历格日期格式 ----

    def test_cal_date_slash(self):
        src = self._src()
        i0 = src.index('<div class="cd">')
        seg = src[max(0, i0 - 80):i0 + 80]
        assert "replace('-','/')" in seg, "日历格日期未统一斜杠轨"
