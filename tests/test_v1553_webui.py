# -*- coding: utf-8 -*-
"""webui 回归（源码级钉死）：环标词面/环半径对齐、C_NEAR 加深
成对与 RGB 令牌化、图例词面收口、过渡动画三件套、mono 收尾、亮色
--mut 加深、toast/倒计时可达性、URL 深链、2K canvas 高度档、--kpiw 合档。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1553_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1553Pins:
    """webui.py 源码级钉死：改色/词面/结构错一处即失败，源码钉模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- A/B 环标词面与半径 ----------

    def test_kline_ring_anchor_wording(self):
        src = self._src()
        # K线图例括注失实修正：●锚真达标轮自身价，○ 才锚桶最低价
        assert "环标：●标在真达标轮自身价 · ○标在桶最低价" in src
        assert "环标（标在桶最低价）" not in src

    def test_ring_radius_no_inversion(self):
        """●实心 r=5 / ○擦边 r=5 / ○破线 r=5 全档对齐（推送 PNG 同档），
        旧 ○破线 5.5 倒挂清零。"""
        src = self._src()
        assert "5.5,1,grn" not in src
        assert src.count("[5,1,grn]") == 2      # K线 + 折线两分支

    # ---- C 图例词面收口 ----------

    def test_details_tab_legend(self):
        src = self._src()
        # audit：色面指代与日历同词面（实绿→深绿）
        assert "深绿=真达标 · 描绿=行情破线 · 琥珀=擦边" in src
        assert "实绿=真达标" not in src                # 旧词面不回潮
        assert "描边绿=行情破线未必可出手" not in src   # 旧词面已收进 title
        assert 'title="描绿=行情破线' in src

    def test_calendar_footnote_disambiguated(self):
        """日历红=格底色（与走势 ▼红箭头两语义），尾注消歧。"""
        src = self._src()
        assert "红=超线（格底）" in src
        assert "红=超线（直飞）" not in src

    def test_pushlog_sample_untouched(self):
        """铁律：NDEMO/pushlog 样例串有 count>=2 断言守护，不得受本轮影响。"""
        assert self._src().count("🎯真达标 🟩破线 🟨擦边 超线") >= 2

    # ---- D/E C_NEAR 加深 + RGB 令牌 ----------

    def test_warn_deepened_pairs(self):
        src = self._src()
        assert "--warn:#8a6c00" in src                      # 亮色加深过 AA
        assert "--warn:#d9b34a" in src                      # 暗色不动
        assert "9a7800" not in src                          # 旧值全文件清零
        assert "154,120,0" not in src
        assert "'#8a6c00'" in src                           # JS 环色兜底两处
        assert "[138,108,0]" in src                         # 日历热力兜底

    def test_rgb_tokens_defined_and_consumed(self):
        src = self._src()
        assert "--warn-rgb:138,108,0" in src
        assert "--warn-rgb:217,179,74" in src               # 暗色成对
        assert "--blue-rgb:11,98,214" in src
        assert "--blue-rgb:99,164,248" in src               # 暗色成对
        assert "rgba(var(--warn-rgb),.55)" in src           # .bar i.near 渐变尾
        assert "rgba(var(--warn-rgb),.45)" in src           # --warnbd
        assert "rgba(var(--blue-rgb),.12)" in src           # .cdt.run
        assert "rgba(var(--blue-rgb),.5)" in src            # cfgflash
        assert "11,98,214" not in src.replace("--blue-rgb:11,98,214", "")

    # ---- F 过渡动画三件套 ----------

    def test_pvmask_transition(self):
        src = self._src()
        assert "opacity:0;visibility:hidden;transition:opacity .18s,visibility .18s" in src
        assert ".pvmask.on{opacity:1;visibility:visible}" in src
        assert "transform:translateY(10px);transition:transform .18s" in src
        assert ".pvmask.on .pvcard{transform:translateY(0)}" in src
        assert ".pvmask{position:fixed;inset:0;background:rgba(16,24,40,.45);z-index:200;display:flex" in src

    def test_savebar_transition(self):
        src = self._src()
        # 补 visibility 双态（隐藏态按钮在焦点树内，键盘 Tab
        # 曾命中不可见按钮静默保存/回滚配置）
        assert ("transform:translateY(140%);opacity:0;visibility:hidden;\n"
                "   transition:transform .22s,opacity .22s,visibility .22s") in src
        assert ".savebar.on{transform:translateY(0);opacity:1;visibility:visible}" in src
        assert "classList.toggle('on',dirty&&VIEW==='cfg')" in src   # JS 硬翻已改类切换
        assert "sb.style.display" not in src

    def test_hc_hover_smoothed(self):
        assert "transition:transform .12s ease" in self._src()

    # ---- G/H mono 与 muted ----------

    def test_mono_finishing(self):
        src = self._src()
        assert "#ftable tbody td:nth-child(8)" in src       # 中转列入组
        assert 'id="updated" style="font-family:var(--num)"' in src
        assert 'id="fcnt" style="font-family:var(--num)"' in src
        assert "color:var(--mut);border-radius:10px;padding:2px 10px;margin-right:8px;font-size:11px;\n      font-family:var(--num);" in src  # .cdt 圆角并轨 10px；mono 档位断言不变

    def test_light_mut_deepened(self):
        src = self._src()
        assert "--mut:#5a6c7d" in src
        assert "--mut:#7f92a6" in src                       # 暗色不动

    # ---- I 可达性 ----------

    def test_toasts_and_timer_aria(self):
        src = self._src()
        assert "box.setAttribute('role','status');box.setAttribute('aria-live','polite')" in src
        assert 'id="nextrun" class="cdt" role="timer"' in src

    # ---- J URL 深链 ----------

    def test_url_deeplink_sync(self):
        src = self._src()
        # showMonTab 与 switchView 尾部各一处 replaceState 同步；
        # hashchange else 归位分支再+1（白名单外/空 hash 清洗
        # 防「URL=#bogus_tab 而视图停 cfg」不一致态）
        assert src.count("history.replaceState(null,'',") == 3
        assert "['overview','trend','details','health'].indexOf(_h)>=0" in src   # hash 白名单防注入
        assert "location.hash.slice(1)==='cfg')switchView('cfg')" in src

    # ---- K/L 宽屏档 ----------

    def test_2k_canvas_height_tier(self):
        # 断点随卡宽突破档同步 1800→1920（1800-1919 带内突破卡
        # 距视口边仅 60-119px 失衡；canvas 高度档与卡宽两块必须联动）
        assert "@media(min-width:1920px){\n  canvas{height:clamp(280px,42vh,460px)}}" in self._src()

    def test_kpiw_merged_tier(self):
        src = self._src()
        # 流式 min(1168px,100%)——992 固定值在 1366/1280 主流本
        # 留 ~150px 右空腔；多档覆写随流式收口删除
        assert "--kpiw:min(1168px,100%)" in src
        assert "--kpiw:1168px" not in src
        assert "--kpiw:1160px" not in src
        assert "--kpiw:1172px" not in src
