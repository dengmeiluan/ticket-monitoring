# -*- coding: utf-8 -*-
"""r188 webui 回归（源码级钉，同 test_v187 模式）。

- audit P2-1：≤760 少轮次图例与柱簇同轴残留——柱区 .pulsewrap 的
  center 全宽域生效（L552 无媒体壳），图例同轴却写在 761+ 媒体壳里，
  窄档少轮次「柱簇居中/图例左贴边」Δ125px 双轴；去媒体壳改无条件
  同轴（无更早同选择器 justify 规则，无置尾反杀面）
- audit P2-2：coarse 触控清单漏 button 本体（裸 button 基础 padding
  下高 35px<36px 基准）+ ≤760 头部 .pill 唯一 jumpQual 入口热区
  31px<36px
- audit P2-3：renderPulse 无条件点亮 pulsecard——删光用户后 P2-4
  回收只封 render 分支，10s 脉冲轮询又把「运行脉冲」挂回 onboarding
  hero 上方驻留；开头补空 users 守卫

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v188_webui.py -q
"""


class TestWebuiV188Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_pulse_legend_center_unconditional(self):
        """图例与柱区同轴全宽度域（去 761 媒体壳；柱区 center L552
        本就无媒体壳，同轴条件两键必须同域）。"""
        src = self._src()
        assert "#pulseLegend{justify-content:center}" in src, \
            "图例无条件同轴缺失（≤760 少轮次双轴残留）"
        i_uncond = src.index("#pulseLegend{justify-content:center}")
        assert "@media(min-width:761px){#pulseLegend" not in src, \
            "761 媒体壳残留（同键双处声明，媒体块死代码）"
        # 无条件块必须在基础 max-width 规则之后（同选择器源码序后者胜，
        # 虽属性不相交，位置律统一）
        i_base = src.index("#pulseLegend{max-width:var(--kpiw)}")
        assert i_uncond > i_base, "无条件同轴块位置早于基础规则"

    def test_coarse_touch_bare_button_36px(self):
        """两处 coarse 触控清单（≤900 粗指针块与 >901 粗指针块）补
        button 本体 36px 基准（裸 button 基础 padding 高 35px 欠档）。"""
        src = self._src()
        assert src.count("button{min-height:36px}") >= 2, \
            "coarse 触控清单 button 本体 36px 未两块齐补"

    def test_pill_narrow_touch_target_36px(self):
        """头部 .pill（唯一 jumpQual 入口）热区 36px 基准：≤760 块与
        两 coarse 块（iPad 带 761+ 粗指针 pill ~33px 同欠档）三处齐补。"""
        src = self._src()
        assert ".pill{font-size:14px;padding:5px 12px;min-height:36px}" \
            in src, "≤760 .pill 触控热区未补 36px"
        assert src.count(".pill{min-height:36px}") >= 2, \
            "coarse 触控清单 .pill 36px 未两块齐补"

    def test_render_pulse_empty_users_guard(self):
        """renderPulse 开头空 users 守卫（删光用户后 10s 轮询不复明
        pulsecard——P2-4 回收的另一半）。"""
        src = self._src()
        needle = ("function renderPulse(j){"
                  "if(!(S&&S.users&&S.users.length))return;")
        assert needle in src, "renderPulse 空 users 守卫缺失"
