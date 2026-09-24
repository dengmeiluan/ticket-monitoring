"""v1.5.79 WebUI 回归钉：审计 P2 五案（audit_v179）。

①P2-1 health() fetch 失败静默——catch 点亮 #healthEmpty 错误文案
（守卫：healthcard 可见=已有真实时间线，保陈旧数据不闪错）；
②P2-2 走势空态假在场（_markStale 家族第 5 处漏网）——静态初始文案
改「数据加载中…」，教学词面挪到 chart() 确无数据分支，_markStale
在空态在场时置「服务未启动」；
③P2-3 桌面档 savebar×toast 1px 巧合缝——≥761 抬升（≤760 同族先例）；
④P2-4 header 状态 pill 可点——jumpQual() 直达「仅达标」明细
（role/tabindex/键盘由 mkact 家族 span[onclick] 收编）；
⑤P2-5 术语统一——「监控平台」×2 →「监控渠道」。
"""

from webui import PAGE


def test_health_fail_not_silent():
    """①health() catch 不再空吞：守卫式点亮 healthEmpty 错误态。"""
    assert "renderHealth(JSON.parse(t));}catch(e){}}" not in PAGE, \
        "health() catch 仍为空吞死码"
    assert "$('healthcard').style.display==='none'" in PAGE, \
        "health() catch 缺 healthcard 守卫（会闪掉已绘制的真实时间线）"
    assert PAGE.count("⚠ 健康数据读取失败") >= 2, \
        "错误词面应同时在 renderHealth err 分支与 health() catch（≥2 处）"


def test_trend_empty_state_guarded():
    """②走势空态三态完备：静态=加载中；S 到达且确无数据=教学词面；
    fetch 失败（_markStale）=服务未启动，且不覆盖已绘制图表。"""
    assert 'id="chartEmpty" style="display:flex">数据加载中…' in PAGE, \
        "静态初始文案应为中性「数据加载中…」（教学词面在此=假空态）"
    assert ("$('chartEmpty').innerHTML='暂无走势数据<span>完成第一轮扫描后"
            in PAGE), "教学词面应挂在 chart() 确无数据分支（S 已到达才承诺）"
    assert ("const ce=$('chartEmpty');if(ce&&ce.style.display!=='none')"
            in PAGE), "_markStale 应守卫翻新 chartEmpty（已绘制图表不动）"


def test_desktop_savebar_toast_lift():
    """③≥761 档 savebar 在场 toast 抬升（桌面 savebar 顶缘 77px 与
    toast 基础 78px 仅 1px 巧合缝）；媒体条件与 ≤760 的 148px 互斥。"""
    assert "@media(min-width:761px){body:has(.savebar.on) #toasts{bottom:96px}}" in PAGE


def test_pill_jump_to_qualified():
    """④pill 挂 onclick=jumpQual（role/tabindex/键盘由 mkact 收编），
    jumpQual 带 S 空态守卫并切「🔥 仅达标」类别挡。"""
    # title 含「将重置现有筛选」副作用声明（审计 P2-1：resetFlt 静默
    # 清用户筛选须显式告知，落地 toast 同步）
    assert 'id="pill" title="跳转达标明细（仅达标档，将重置现有筛选）" onclick="jumpQual()"' in PAGE
    assert "toast(" in PAGE[PAGE.find("function jumpQual"):PAGE.find("function jumpQual") + 500]
    assert "function jumpQual(){if(!S)return;" in PAGE
    i = PAGE.find("function jumpQual")
    assert "F='q'" in PAGE[i:i + 300], "jumpQual 应切到「🔥 仅达标」类别挡"


def test_term_channel_unified():
    """⑤「监控平台」词面清零，统一「监控渠道」（配置页 B 分区 2 处）。"""
    assert "监控平台" not in PAGE
    assert PAGE.count("监控渠道") >= 2
