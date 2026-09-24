# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v169_webui.py 模式；行为断言在
docs/uitest.py 补钉：glsec 归一/hairline/glcell 内衬/notify --pill/toast hover）。

（WebUI 布局美感第二轮；P0=0/P1=0，P2×9 中 4 项采纳 5 项备案）：
P2-A glsec→subsec 归一：两套分区标签字面样式同源（10.5px/1.2px/--mut/
uppercase），原内联版缺::after hairline 且 margin ±1px → glsec 改输出
class="subsec"，配置页全局参数区获得与推送区一致的收尾线。
P2-B .glcell 内衬 11px 14px → 12px 14px（与 .lgcard/.chcard 同档；
11px 垂直档系全卡盘点唯一游离值，卡内衬实为层级清晰的四档体系）。
P2-C 全胶囊家族令牌化：--pill:999px 单源，.tag/.switch/.hbadge/.upill/
.mchip（20/18px）与 NOTIFY_PAGE .md a（999px）六处消费并轨；
notify 独立页自带:root 令牌区，--pill 漏补则 CTA 圆角塌 0
（行为钉 docs/uitest.py「notify --pill 令牌在册」兜底）。
P2-E .toast 可点击关闭补:hover{background:var(--hover)}（与 .pvx 同语言）。
P2-D/F/G/H/I 备案不动：hitbar 移动端 1px 差/开关状态色即反馈不再叠
hover/走势 canvas 点击命中成本高/脉冲柱群居中系 事故决策/
--kpiw 1168 流式封顶系 决策。

m-b 钉收编（v169-mbspare 分支遗留）：--fill2 暗值断言（uitest 行为钉）。
五路调研缩波全 PASS：渠道关案第六轮维持（qunar 555 路径零固定漂移/
ctrip 34 键零增减+notes 2-10 型未回摆+disAmount 0.74% 未触发/
tuniu 84 族零 diff+foldFlag 恒 True/layover 绝迹/tongcheng direct 第五轮
连续 PASS 0/54/fliggy recheck 零增长+PC 天花板维持）；观测八项全 PASS
零回归（脏价 0/6,075、曲线-列表零分歧、lay2dep 190/190、IATA 569/569）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v170_webui.py -q
"""


class TestWebuiV170Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def _notify_src(self):
        import webui as _w
        src = self._src()
        i = src.index("NOTIFY_PAGE")
        return src[i:]

    def test_pill_token_defined_and_six_consumers(self):
        """P2-C：--pill 令牌单源 + 六处消费并轨，20/18/999px 硬编码归零。"""
        src = self._src()
        assert "--pill:999px" in src, "主站 :root 缺 --pill 令牌"
        # 消费端：CSS 区五选择器逐个点名（border-radius:var(--pill)）
        import re
        m = re.findall(r"\.(tag|switch|hbadge|upill|mchip)\{[^}]*?"
                       r"border-radius:var\(--pill\)", src)
        assert sorted(set(m)) == ["hbadge", "mchip", "switch", "tag", "upill"], \
            "主站胶囊五选择器消费不全: %s" % m
        # notify 页 .md a 消费
        nsrc = self._notify_src()
        assert "border-radius:var(--pill)" in nsrc, "notify .md a 未并轨"
        # notify 页:root 补定义（漏补→computed 塌 0，uitest CTA 钉先红）
        assert "--pill:999px" in nsrc, "notify 独立 :root 缺 --pill（CTA 圆角塌 0 先例）"
        # 硬编码残留归零（含 20px/18px 旧写法；50% 圆形/微元素 1~8px 不在列）
        resid = re.findall(r"border-radius:(?:20|18|999)px", src)
        assert not resid, "胶囊家族硬编码残留: %s" % resid

    def test_glsec_normalized_to_subsec(self):
        """P2-A：glsec 输出 class="subsec"（hairline 收尾线+margin 归一）。"""
        src = self._src()
        assert 'const glsec=t=>\'<div class="subsec">\'+t+\'</div>\';' in src, \
            "glsec 未归一 subsec"
        assert 'glsec' in src and src.count('class="glsec"') == 0
        # .subsec 基线仍带 hairline（归一收益的本体）
        assert ".subsec::after{content:'';flex:1;height:1px;background:var(--line)}" in src

    def test_glcell_padding_12_14(self):
        """P2-B：.glcell 内衬并入 12px 14px（与 .lgcard/.chcard 同档）。"""
        src = self._src()
        assert ".glcell{border:1px solid var(--line);border-radius:var(--r2);" \
               "padding:12px 14px;" in src
        # 11px 垂直档仅余表头/按钮等非卡容器形态（audit 盘点对象为卡容器）
        assert "padding:11px 14px" not in src, "glcell 11px 游离档残留"

    def test_toast_hover_rule(self):
        """P2-E：.toast:hover{background:var(--hover)} 与 .pvx 同语言。"""
        src = self._src()
        assert ".toast:hover{background:var(--hover)}" in src
