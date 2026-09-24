# -*- coding: utf-8 -*-
"""r191 WebUI 回归（源码级钉，同 test_v188 模式）。

- audit P1-1：健康格触控热区被 overflow 裁剪——.hcells{overflow-x:auto}
  使 overflow-y 强制 auto，.hc::after 纵向 -11px 外扩热区被裁到 19px
  （37px 声明形同虚设）且伴随 9px 隐藏纵向滚动陷阱。修法：容器上下
  padding 外衬 11px（热区落回裁剪框内）+ margin 负值回收（行高零漂移）
  + 容器 pointer-events:none / 格本体 auto（衬垫区不吞点击）。
- audit P2-1：mkactAll 注释债——注释声称给 .calcell 补键盘可达而
  选择器实际不含，注释如实化。
- audit P2-2：非激活排序列缺 aria-sort="none"（读屏器排序态三值
  完整性：ascending/descending/none）。
- audit P2-3：日历超线档 .cd/.cx 撤 0.85 opacity 税——与 qhit/qbrk
  免税纪律对齐（撤税后极档对比度 4.97/4.70 仍过 AA）；免税例外
  规则在无税基线上成恒真死码，同批连带清理。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v191_webui.py -q
"""


class TestWebuiV191Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_hcells_touch_target_not_clipped(self):
        """P1-1：.hcells 容器 padding 外衬+margin 回收+pointer-events
        穿透，.hc::after 37px 热区不被 overflow 裁剪。"""
        src = self._src()
        assert (".hcells{display:flex;gap:2px;flex:1;overflow-x:auto;"
                "padding:11px 0;margin:-9px 0;pointer-events:none}") in src, \
            ".hcells 外衬修法缺失（热区仍被 overflow 裁剪）"
        assert ".hcells .hc{pointer-events:auto}" in src, \
            ".hc 本体 pointer-events 恢复缺失"
        assert ".hc::after{content:'';position:absolute;inset:-11px -1px}" \
            in src, ".hc::after 热区声明被误动"

    def test_mkact_all_comment_honest(self):
        """P2-1：键盘可达选择器说明注释与 mkactAll 真实选择器一致
        （.calcell 不在选择器内，不得写进注释成员清单）。"""
        src = self._src()
        assert ".calcell/.plitem/.dx" not in src, \
            "mkactAll 注释仍声称覆盖 .calcell（注释债未清）"
        assert ("[role=\"button\"],span[onclick],.mtab,#tabs span[data-f],"
                ".cnav,.plitem,.dx,.tg") in src, \
            "mkactAll 选择器本体被误动"

    def test_aria_sort_none_on_inactive_columns(self):
        """P2-2：表头排序态 aria-sort 三值完整——非激活列显式
        aria-sort="none"，激活列 ascending/descending 保留。"""
        src = self._src()
        assert ("aria-sort=\"${SORT.k===k?(SORT.dir>0?'ascending':"
                "'descending'):'none'}\"") in src, \
            "表头 aria-sort 未三值化（非激活列缺 none）"
        assert "'ascending':'descending'" in src, \
            "激活列排序态词面被误动"

    def test_calendar_hot_cell_no_opacity_tax(self):
        """P2-3：.cd/.cx 撤 0.85 opacity 税，qhit/qbrk 免税例外死码
        连带清理（无税基线上 opacity:1=默认值恒真）。"""
        src = self._src()
        assert ".calcell .cd{font-size:11px;font-weight:600}" in src, \
            ".cd 基线规则缺失（撤税形态不符）"
        assert (".calcell .cx{font-size:10.5px;margin-top:1px;"
                "font-variant-numeric:tabular-nums}") in src, \
            ".cx 基线规则缺失（撤税形态不符）"
        assert ".calcell .cd{font-size:11px;font-weight:600;opacity:.85}" \
            not in src and "tabular-nums;opacity:.85}" not in src, \
            "日历超线档 opacity 税残留"
        assert ".calcell.qhit .cd,.calcell.qhit .cx{opacity:1}" not in src \
            and ".calcell.qbrk .cd,.calcell.qbrk .cx{opacity:1}" not in src, \
            "免税例外死码残留"
