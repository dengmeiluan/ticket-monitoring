# -*- coding: utf-8 -*-
"""本轮 WebUI 层源码钉（EN 增强五案 + riskPolicy 消费端）：

1. 脉冲卡入概览 tab（首屏 chrome 税收口）：pulsecard DOM 移入
   #montab-overview，details/trend/health 首屏省 ~252px；红帽徽标
   （ovAlert+renderPulseAlert）保证渠道异常在其他 tab 仍全局可见。
2. 桌面视图切换器吸顶：761+ 档 #montabs sticky 贴 header 底，
   追加块置尾（与 ≤540/≤390 同选择器块命中域不相交）；锚点补偿
   scroll-padding 同块联动。
3. 中转列条件隐藏：全直飞结果集切 no-transfer 类整列隐藏，
   xrow colspan 展开行不受扰（行为钉 uitest 验横贯）。
4. 配置即时校验：GLB_RANGES 单源表驱动 glbCheck 输入即校验，
   saveCfg 复用同表（防两处漂移）。
5. 明细价格字号阶梯：cozy 档 15px，compact 档保持密度语义。
6. ctrip riskPolicy 高风险政策透明标记消费端：API 白名单 strip 门 +
   价格格 ⚠ 徽标（warn 色与 title 风险说明；词面不加「价」尾）。

钉面分层：JS/CSS 断言走 webui.PAGE（内嵌 SPA 字符串）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15111_webui.py -q
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return pathlib.Path(webui.__file__).read_text(encoding="utf-8")


def test_pulsecard_inside_overview_tab():
    """脉冲卡 DOM 位于概览 tab 容器内（容器开标签先于 pulsecard）。"""
    src = _src()
    assert src.index('id="montab-overview"') < src.index('id="pulsecard"')
    assert src.index('id="pulsecard"') < src.index("</div><!-- /montab-overview -->")


def test_pulse_alert_badge_wiring():
    """红帽徽标三件套：概览 tab 红点、渲染函数、renderPulse 尾部接线。"""
    src = _src()
    assert 'id="ovAlert"' in src
    assert "function renderPulseAlert(fails)" in src
    assert "renderPulseAlert(last.fails||0);" in src


def test_pulse_alert_badge_a11y():
    """徽标读屏语义（WebUI 审计 EN-9）：role=img + aria-label 静态
    在位——display:none 天然从可访问性树移除，点亮即暴露。"""
    src = _src()
    assert 'id="ovAlert" role="img" aria-label="最新轮有渠道失败' in src


def test_desktop_montabs_sticky_tail_block():
    """桌面吸顶：761+ 主块的 sticky 声明消费 --hdh 动态贴 header 实高
    （top:var(--hdh,54px)，fallback 与旧固定值等效）；761-900 带内
    固定校准覆写块已随动态化退役——变量自动跟随倒计时折行，固定
    单值反而在实高漂移时盖住切换器（WD P1-1 生产 768 实测盖 33px）。
    本钉锁两件事：主块形态（消费变量）+ 固定校准块不回流。"""
    src = _src()
    assert "#montabs{position:sticky;top:var(--hdh,54px)" in src
    assert "html{scroll-padding-top:calc(var(--hdh,54px) + 34px)" in src
    main761 = src.index("@media(min-width:761px){")   # 带 { 直连=主块
    sticky_at = src.index("#montabs{position:sticky;top:var(--hdh,54px")
    assert sticky_at > main761
    # 桌面档形态唯一：源码更后的同形声明会按层叠序劫持
    assert src.count("#montabs{position:sticky;top:var(--hdh,54px") == 1
    # 固定校准块退役：带内覆写（固定 top/补偿像素）不得回流——
    # 回流即 reintroduce 实高漂移下的遮挡缺陷
    assert ("@media(min-width:761px) and (max-width:900px)"
            not in src)


def test_transfer_column_conditional_hide():
    """中转列条件隐藏：CSS 选择器与 table() 按当前结果集切类成对。"""
    src = _src()
    assert "#ftable.no-transfer th:nth-child(8)" in src
    assert "rows.every(f=>!f.transfer)" in src
    assert src.count("no-transfer") >= 3   # CSS 类名 + JS toggle×2 处


def test_glb_ranges_single_source_table():
    """配置校验单源表：glbCheck 输入即校验、saveCfg 复用同表、
    glcell 数字项挂 oninput、越界红边与行内提示样式在位。"""
    src = _src()
    assert "const GLB_RANGES=[" in src
    assert "function glbCheck(el,returnMsg)" in src
    assert 'oninput="glbCheck(this)"' in src
    savecfg = src[src.index("async function saveCfg()"):]
    assert "for(const r of GLB_RANGES)" in savecfg[:600]
    assert ".glcell input.invalid" in src
    assert ".glcell .verr" in src


def test_price_font_size_tier():
    """价格字号阶梯：cozy 档 15px、compact 档不命中（密度语义保留）。"""
    src = _src()
    assert ":root:not([data-density=compact]) #ftable td.price{font-size:15px}" in src


def test_riskpolicy_whitelist_and_badge():
    """ctrip 高风险政策透明标记消费端：API 白名单 strip 门 + 价格格
    ⚠ 徽标（warn 色与 title 风险说明在位；词面不加「价」尾——它是
    政策风险标记不是资格价语义）。"""
    src = _src()
    assert '"riskPolicy": (f.get("riskPolicy") or "").strip(),' in src
    assert ('f.riskPolicy?`<span class="pretax" style="color:var(--warn);'
            'cursor:help" title="渠道标注的高风险政策价') in src
    assert "⚠${f.riskPolicy}</span>" in src


def test_demo_riskpolicy_sample():
    """demo 演示样本：首行 riskPolicy 在场（演示页价格格徽标目检点）。"""
    import webui
    demo = pathlib.Path(
        os.path.join(os.path.dirname(webui.__file__), "core", "demo.py")
    ).read_text(encoding="utf-8")
    assert 'fs[0]["riskPolicy"] = "高风险政策"' in demo


def test_details_tabs_scroll_hint():
    """P1-W1 ≤540 明细吸顶条横滚暗示与筛选入口常在：::after 装饰层
    渐隐挂 xhint 类点亮（不用容器 mask——mask 会把 sticky 的 fltBtn
    一起淡出）；fltBtn sticky 钉可视右缘（筛选抽屉 ≤760 唯一入口
    不依赖滚动可达）。"""
    src = _src()
    assert "#montab-details .tabs::after" in src
    assert "#montab-details .tabs.xhint::after" in src
    assert "#montab-details .tabs>#fltBtn{position:sticky;right:0" in src
    # 四处组合选择器 xhint 判定循环（showMonTab health 分支/
    # renderHealth/resize debounce/switchView，同判定
    # scrollWidth>clientWidth+4）选择器扩展覆盖明细条
    assert src.count(".hcells,#montab-details .tabs") >= 4
    # 第 5 处循环：showMonTab details 分支独立明细条判定（首渲在
    # 隐藏容器 sw=0，切回补一拍）——组合计数钉罩不住它，独立钉。
    # r253 起 .tw（表内横滚提示）并入同批
    assert ("if(t==='details')document.querySelectorAll("
            "'#montab-details .tabs,.tw')") in src


def test_footer_link_hover():
    """M1 页脚/演示条链接 hover 反馈（与 NOTIFY 轻页同位对齐，
    自约「真实可点链接悬停零反馈」属缺陷）。"""
    src = _src()
    assert "#foot a:hover,.demoBar a:hover{text-decoration:underline}" in src
