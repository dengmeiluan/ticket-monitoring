# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v168_webui.py 模式；行为断言在
docs/uitest.py 补钉：qhit 小字 computed opacity/健康时间线 ≥1440 铺满）。

五路调研（布局美感专项轮 + 零立案 + 渠道五轮关案维持）：
 日历真达标格 .cd/.cx opacity:.85 税（白字系唯一实底档 3.94 欠 AA，
  只修了 .cp 的同格姊妹层残留半截）→ q=2 格挂 qhit 类，
小字 opacity:1（亮 4.83/暗 6.67 双过）。
 --fill2 渐变顶带双主题欠 AA（亮 4.25~4.34/暗 4.32~4.44）→ 收深
#1d6fd8/#3771c4（全带 ≥4.86）；--fill-t 同族先例。
 chip 徽标 .bd 基线 opacity:.9 税 + 选中底令牌（3.28~3.98 欠）→
删税 + --chip-on-warn #ffe9b8 / --chip-on-red #ffe0e1。
 暗色危险确认态 --red 作填充底白字 3.49 → #b3393c 覆写（5.89），
--red 令牌不动（作文字色 5.12 仍正确）。
 健康时间线 ≥1440 拉伸空洞（96 格左聚 ~740px 空白）→ 弹性格铺满。
 推送预览弹层三段内衬 16/18/16 错位 → pvbody 对齐 16。
 令牌卫生子集：seclab 死声明删/mchip.best 阴影 spread 补齐/
容器瓦片圆角 12px 双轨并 10px/pvcard 14px→var(--r)/rtcode 14.5→14。
 概览 kpisum 补「走势 ▾」直达（jumpRowTrend('') 空路由=当前视图，
与「查看明细 ▾」对称）；「描绿→浅绿」词面建议不采纳（明细破线是描边
样式，主词「行情破线」三视图本已统一）。
（既有 备案案结）：日历破线暗色 FGDK 带 3.21~3.61
全欠 → alpha 上限 0.56 + 亮暗恒 var(--tx)。
：--ok-strong 死令牌删除（消费 0 实锤）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v169_webui.py -q
"""


class TestWebuiV169Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_cal_qhit_class_and_css(self):
        """q=2 格挂 qhit 类；小字对比度由无税基线全档保证
        （.cd/.cx 无 opacity 声明，v191 钉锁定基线形态）。"""
        src = self._src()
        assert "(q===2?' qhit':'')" in src
        assert ".calcell .cd{font-size:11px;font-weight:600}" in src

    def test_cal_qbrk_breakline_small_text(self):
        """q=1 破线格挂 qbrk 类（语义锚）；小字对比度由无税
        基线全档保证（极档 4.97/4.70 过 AA）。"""
        src = self._src()
        assert "(q===1?' qbrk':'')" in src
        assert ".calcell .cx{font-size:10.5px;" \
               "margin-top:1px;font-variant-numeric:tabular-nums}" in src

    def test_dark_uava_gradient_deep(self):
        """暗色 .uava 渐变第二站收 --fill（#63a4f8 白字
        2.56 实锤 → fill2→fill 全带 4.86~5.59）。"""
        src = self._src()
        assert ('html[data-theme="dark"] .uava{background:'
                'linear-gradient(135deg,var(--fill2),var(--fill))}') in src

    def test_cal_breakline_m1_tx_constant_alpha_053(self):
        """案结 + 修正：alpha 上限 0.53（合成底真实衬底
        #calcard --card 非 --bg，0.5373 交点留余量）+ 亮暗恒 var(--tx)。"""
        src = self._src()
        assert "const a=0.25+Math.min(0.28,(1-r)*2.2);" in src
        assert "fg=DK?(a>=0.55?FGDK" not in src

    def test_fill2_deepened_both_themes(self):
        """：--fill2 亮 #1d6fd8 / 暗 #3771c4（渐变顶带白字全带 ≥4.86）。"""
        src = self._src()
        assert "--fill2:#1d6fd8" in src
        assert "--fill2:#3771c4" in src
        assert "--fill2:#2f83ea" not in src
        assert "--fill2:#3f82d8" not in src

    def test_chip_bd_tax_removed_and_on_tokens_lightened(self):
        """：.bd 删 opacity:.9 税 + 选中底令牌提亮（全表 ≥4.5）。"""
        src = self._src()
        assert ".chip .bd{font-style:normal;font-size:10px;margin-left:4px}" in src
        assert "--chip-on-warn:#ffe9b8" in src
        assert "--chip-on-red:#ffe0e1" in src
        assert "--chip-on-warn:#ffe3a3" not in src
        assert "--chip-on-red:#ffc4c5" not in src

    def test_dark_arming_fltbtn_deep_red(self):
        """：暗色 arming/筛选角标填充底 #b3393c 覆写（3.49→5.89）。"""
        src = self._src()
        assert 'html[data-theme="dark"] button.arming{background:#b3393c' in src
        assert 'html[data-theme="dark"] #fltBtn b{background:#b3393c}' in src

    def test_health_cells_fill_wide(self):
        """：≥1440 时间线弹性格均分铺满（容器保 flex:1 占满；审计原
        「容器收缩+max-width 12」模型 Chrome 实测格宽归零，弃用）。"""
        src = self._src()
        assert "@media(min-width:1440px){" in src
        assert ".hc{width:auto;flex:1 1 6px}" in src
        assert ".hcells{flex:0 1 auto}" not in src

    def test_pvbody_padding_aligned(self):
        """：pvbody 水平内衬 16 与 pvhead/pvfoot 三段对齐（曾 18 凸出 2px）。"""
        assert ".pvbody{padding:14px 16px;" in self._src()

    def test_token_hygiene_subset(self):
        """卫生子集：seclab 死声明删/mchip.best spread/圆角并轨/
        pvcard 令牌化/rtcode 14。"""
        src = self._src()
        assert ".seclab{display:flex;align-items:baseline;gap:9px}" in src
        assert "margin:22px 2px 9px" not in src
        assert "box-shadow:0 2px 8px -2px var(--glow)}   /* -2px spread" in src
        assert src.count("border-radius:12px;padding:4px;box-shadow:var(--sh1)") == 0  # nav
        assert "border-radius:12px;padding:2px 10px" not in src  # .cdt
        assert "border-radius:12px;padding:10px 14px" not in src  # savebar
        assert ".pvcard{background:var(--card);border-radius:var(--r);" in src
        assert ".rtcode{font-family:var(--num);font-size:14px;" in src

    def test_kpisum_trend_shortcut(self):
        """：概览 kpisum 补「走势 ▾」直达（jumpRowTrend('') 空路由
        =当前视图，与「查看明细 ▾」对称）。"""
        assert "pickUser(${i});jumpRowTrend('')" in self._src()

    def test_ok_strong_dead_token_removed(self):
        """：--ok-strong 死令牌删除（var 消费 0 + 定义 0，词面仅存
        历史注释）。"""
        src = self._src()
        assert "var(--ok-strong)" not in src
        assert "--ok-strong:#" not in src
