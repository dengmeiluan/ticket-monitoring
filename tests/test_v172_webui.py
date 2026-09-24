# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v171_webui.py 模式；行为断言在
docs/uitest.py 补钉）。

（WebUI 布局美感与交互完整性第四轮；P0=0，P1×1+P2×3 全采纳）：
 saveCfg 航线阈值校验循环恒死码：for...of ('alert_direct','alert_transfer')
    圆括号逗号表达式求值取尾操作数，实际迭代 'alert_transfer' 的 14 个字符
    （r[k] 恒 undefined → 校验体永不触发）——UI 路径 number 输入非法值恒 ''
    被豁免无恙，唯一穿透口是导入配置（importCfg 对 thresholds 无归一化），
    非法阈值落 config.yaml 后 _route_view float ValueError → /api/state
    构建链崩溃/缓存停陈旧值。修法：`(` 改 `[`（与同函数 L3307 数组式对照）。
P2-A 健康时间线滚动暗示 xhint 主路径死档：health 首渲发生在页面加载时
    （默认概览页 #montab-health display:none → sw=cw=0 → toggle 恒 false），
    showMonTab 只翻 display 不重跑判定——「默认加载→点健康」这条最常见
    路径上 390/760 无右缘渐隐。修法：showMonTab 补 health 分支重跑同式
    toggle（≥1024 弹性档放得下恒 false 不误挂）。
P2-B 移动端「🎛 筛选」角标幻影计数：日期片全选回填（FLT.dates==日期全集
    =零筛选）被计入显示「筛选 1」——同函数 plats/routes 均有 size<all
    守卫唯 dates 双标。修法：与 plats/routes 逐字同构补 size<ds.length；
    伴随 buildDateChips 单日期早退分支清 FLT.dates（跨用户切换残留旧
    dates 会让明细过滤全灭，L1692 消费点）。
P2-C 配置表单重建不回焦：回车加日期（注释承诺三通道等价之一）成功后
    buildForm 整体 innerHTML 重建，焦点坠 body，连续录入须从页首重 Tab。
    修法：activeElement.id 快照 + 重建尾 focus({preventScroll:true}) 回焦
    （render data-k / table 先例的 id 版；无 id 元素不救同先例纪律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v172_webui.py -q
"""


class TestWebuiV172Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_p1_threshold_loop_iterates_keys_not_chars(self):
        """：阈值校验循环迭代键数组，圆括号字符串迭代死码消失。"""
        src = self._src()
        assert "for(const k of ['alert_direct','alert_transfer']){" in src, \
            "阈值校验未用数组字面量（逗号表达式退化为字符迭代＝校验恒死码）"
        assert "for(const k of ('alert_direct','alert_transfer')){" not in src, \
            "圆括号逗号表达式形态仍在（校验死码回潮）"

    def test_p2a_xhint_rerun_on_health_tab(self):
        """P2-A：showMonTab 补 health 分支 xhint 重跑（隐藏容器首渲死档）。"""
        src = self._src()
        assert ("if(t==='health')document.querySelectorAll('.hcells')"
                ".forEach(x=>x.classList.toggle('xhint',"
                "x.scrollWidth>x.clientWidth+4));") in src, \
            "showMonTab 缺 health 分支 xhint 重跑（主路径渐隐死档回潮）"

    def test_p2b_dates_full_select_not_counted(self):
        """P2-B：dates 全选不计筛选数（与 plats/routes 守卫同构）。"""
        src = self._src()
        assert "if(FLT.dates.size&&FLT.dates.size<ds.length)n++;" in src, \
            "dates 缺 size<ds.length 守卫（全选回填幻影计数回潮）"
        # 旧形态（无守卫早计）必须消失
        assert "if(FLT.dates.size)n++;" not in src, \
            "dates 无守卫早计仍在（幻影「筛选 1」回潮）"

    def test_p2b_single_date_early_exit_clears_dates(self):
        """P2-B 伴随：单日期早退清 FLT.dates（跨用户残留致过滤全灭）。"""
        src = self._src()
        assert "if(ds.length<2){box.innerHTML='';FLT.dates=new Set();return;}" in src, \
            "buildDateChips 单日期早退未清 FLT.dates（跨用户残留过滤全灭）"

    def test_p2b_single_route_early_exit_clears_routes(self):
        """P2-B 同族（采纳）：单航线早退清 FLT.routes——
        buildRouteChips 与 buildDateChips 同病对称（跨用户切到单航线
        用户时 routes 残留同样致明细过滤全灭，saveUI 无条件恢复）。"""
        src = self._src()
        assert "if(rs.length<2){box.innerHTML='';FLT.routes=new Set();return;}" in src, \
            "buildRouteChips 单航线早退未清 FLT.routes（与 dates 同病不对称回潮）"

    def test_p2c_buildform_focus_restore(self):
        """P2-C：buildForm 重建前快照 activeElement.id、重建尾回焦。"""
        src = self._src()
        assert "_fkid=(_fae&&_fae.id)?_fae.id:null;" in src, \
            "buildForm 缺 activeElement.id 快照（回车加日期后焦点坠 body）"
        assert "if(_fkid){const _fe=document.getElementById(_fkid);" \
               "if(_fe)_fe.focus({preventScroll:true});}" in src, \
            "buildForm 缺重建尾回焦（键盘连续录入流断裂回潮）"
