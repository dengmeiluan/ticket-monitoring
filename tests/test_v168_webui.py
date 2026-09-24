# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v167_webui.py 模式；行为断言在
docs/uitest.py 补钉：亮色日历格 AA computed/.dn 色/错误态回收/条件承诺句）。

 价格日历亮色格文字 AA 整档欠齐（v163/v167 两轮 AA 收编盲区）：
真达标 rgba 合成白字 3.91 → 实色底 var(--green) 保白字 4.83；破线/超线
亮色白字 2.27~3.86 → 一律深字 + alpha 上限收 0.60；超线暗色统一
var(--tx)（FGDK 对暗红合成底 2.42~2.62 曾倒退，收编）；
擦边价字 --warn 对琥珀 tint 3.31 → --warn-deep 双主题 4.66/4.72
（暗色其余路径零改动）。
 .dn 降绿字 --ok-strong 白卡 4.21/okbg 3.73 欠 AA → --ok-txt
（/63/67 同族最后一枚）。
 renderHealth 空态/错误态回收 healthcard（500 错误体曾与完整格带
同屏并存）+ 错误词面不冒充「暂无扫描记录」。
 loadCfg users 形状守卫（500 错误体当数据曾静默渲染「0 用户+出厂
参数」假界面）+ catch 改 cfgErr 双通道。
 .fbar input:focus:not(.switch) 豁免（开关键盘焦点环被剥离）。
 日历「点击格看该日明细」承诺句条件拼接（恒无 link 分支不再空承诺）。
 脉冲柱点击跳健康补文案线索。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v168_webui.py -q
"""


class TestWebuiV168Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_cal_qual_solid_green_light_theme(self):
        """P1-1a：亮色真达标实色底保白字（rgba 合成白字最低 3.91 欠 AA）。"""
        assert "bg=DK?'rgba('+CG+',.88)':'var(--green)'" in self._src()

    def test_cal_breakline_light_dark_text_alpha_cap(self):
        """P1-1b：破线 alpha 上限 + 深浅字（收 0.60+暗色 FGDK 分支
        → 案结收 0.53 且亮暗恒 var(--tx)；修正衬底
        为 --card 后 0.56 仍欠 → 0.53）。"""
        src = self._src()
        assert "const a=0.25+Math.min(0.28,(1-r)*2.2);" in src
        assert "bg='rgba('+CG+','+a.toFixed(2)+')';\n    fg='var(--tx)';}" in src

    def test_cal_overline_light_dark_text_alpha_cap(self):
        """P1-1c：超线 alpha 上限 0.56（min(0.40,…)）+ 亮暗统一
        var(--tx)（暗色 FGDK 对暗红合成底 2.42~2.62 曾倒退，收编；
        上限 0.56：0.60 时暗色最深格小字 4.39 欠 AA）。"""
        src = self._src()
        assert "const a=0.16+Math.min(0.40,(r-1)*2.2);" in src
        assert "fg='var(--tx)';}}" in src

    def test_cal_near_price_warn_deep(self):
        """P1-1d：擦边价字 --warn-deep（--warn 亮色对琥珀 tint 3.31 欠）。"""
        assert ".calcell .cp.near{color:var(--warn-deep)}" in self._src()

    def test_dn_down_delta_uses_ok_txt(self):
        """：.dn 降绿字 --ok-txt（--ok-strong 白卡 4.21/okbg 3.73 欠）。"""
        assert ".dn{color:var(--ok-txt);font-weight:600}" in self._src()

    def test_health_empty_recycles_card_and_err_wording(self):
        """：空态/错误态回收 healthcard + 错误词面不冒充空态。"""
        src = self._src()
        assert "$('healthcard').style.display='none';" in src
        assert "'⚠ 健康数据读取失败（详见服务日志）'" in src

    def test_loadcfg_users_shape_guard_cfgerr(self):
        """：loadCfg users 形状守卫落 catch + cfgErr 双通道。
        （锚定 catch 段：buildForm 与 catch 之间插入 aria
        后处理块，cfgErr 双通道行为不变）"""
        src = self._src()
        assert "if(!j||!Array.isArray(j.users))throw new Error('配置接口响应异常');" in src
        assert "catch(e){cfgErr('配置读取失败: '+e);}}" in src

    def test_fbar_focus_not_switch(self):
        """：.fbar input:focus:not(.switch)（开关 UA 焦点环豁免）。"""
        assert ".fbar select:focus,.fbar input:focus:not(.switch){outline:none;" \
            in self._src()

    def test_cal_hint_conditional_on_link_cell(self):
        """：日历纯展示——格级点击跳转两域不相交恒不可用，死通道
        （dfull/calcell.link/点击格提示）整体收口，提示词面全页不在。"""
        src = self._src()
        assert ("红=超线（格底）</span>';" in src
                and "点击格看该日明细" not in src)

    def test_pulse_head_click_hint(self):
        """：脉冲卡头补「点击柱跳渠道健康」。"""
        assert "悬停看明细 · 点击柱跳渠道健康" in self._src()
