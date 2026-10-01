# -*- coding: utf-8 -*-
"""WebUI 三案源码钉：carryon 三端承载 + P1-1 sticky 修复（含滚动
重接线）+ P2-1 脏态三色统一 + P2-2 触控热区外扩。

P1-1（WebUI 审计）：前轮落地的 ≤540 sticky 吸顶在
`.tw` 52vh 内滚架构下永不触发（触发点滚动 821px > 页面最大滚动
756px，差口 65-156px 结构性）——修复=≤540 放开 .tw max-height 让
明细跟页滚（吸顶注释宣称的行为），同轮把切片续载监听/End 跳底/
重建滚动位三条 .tw 内滚路径重接线到页面滚动，两容器监听互斥门防
水平滚动伪事件触发纵向补片。

P2-1：「有未保存的修改」三件三色（导航红点 --red/配置琥珀字
--warn/savebar 橙点 --orange）统一收编 --warn——脏态保琥珀、红留给
真警戒；且 --warn 亮色 #8a6c00 对白底 ≥4.5:1（--orange #c96a10 仅
3.75:1 不达 AA）。

P2-2：#foot a（16px）/ .demoBar a（27px）低于 36px 触控基准且无
::after 外扩——按 .dchip .dx 家族纪律补纯命中区外扩（视觉零变化）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v204_webui.py -q
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from webui import PAGE


def _src():
    import webui as _w
    with open(_w.__file__, encoding="utf-8") as fh:
        return fh.read()


# ---- carryon 三端（爬虫键见 test_v204_fields；此处白名单/渲染门） ----

def test_v204_carryon_payload():
    assert '"carryon": (f.get("carryon") or "").strip(),' in _src()


def test_v204_carryon_csv():
    assert ",'直挂','托运额','手提额','经停'," in PAGE
    assert ("(f.bagState==='direct'?'是':(f.bagState==='recheck'?'需转运':''))"
            ",f.baggage||'',f.carryon||'',"
            "f.stop?('是'+(f.stopWin?'('+f.stopWin+')':'')):''") in PAGE


def test_v204_carryon_title():
    # title 悬停承载（baggage 同款分隔符链：前文有无判'｜'，
    # carryon 与前后段的分隔条件同步扩，防粘连/孤立分隔符）
    assert "(f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null)" in PAGE
    assert ("(f.baggage?he(f.baggage):'')"
            "+((f.labels||f.labelNote||f.baggage)&&f.carryon?'｜':'')"
            "+(f.carryon?he(f.carryon):'')") in PAGE
    assert ("((f.labels||f.labelNote||f.baggage||f.carryon)"
            "&&f.bizPrice!=null?'｜':'')") in PAGE
    assert ("(f.labels||f.labelNote||f.bizPrice!=null||f.baggage||f.carryon"
            ")?'｜':'')") in PAGE


# ---- P1-1：sticky 可达（.tw 放开内滚）+ 三条内滚路径重接线 ----

def test_v204_tw_maxheight_released_in_540_block():
    # ≤540 块内、sticky 规则之后追加 .tw{max-height:none}（同块置尾，
    # 置尾纪律：媒体块内同特异性后者胜）
    i540 = PAGE.index("@media(max-width:540px)")
    block = PAGE[i540:i540 + 2000]
    assert "#montab-details .tabs{position:sticky;" in block
    assert ".tw{max-height:none}" in block
    assert block.index("position:sticky") < block.index(".tw{max-height:none}")


def test_v204_window_scroll_append_gate():
    # 页面滚动续载（≤760 窄档）：窗口监听 + 动态宽度门（旋转跨档即时
    # 生效，媒体特性动态查询放 handler 内）；宽度族随 541-760 带
    # .tw 放开跟页滚扩带 540→760（明细吸顶可达的结构前提）
    assert "window.addEventListener('scroll',function()" in PAGE
    assert "if(window.innerWidth>760)return;" in PAGE
    assert "window.innerHeight+window.scrollY>document.documentElement.scrollHeight-600" in PAGE


def test_v204_tw_listener_desktop_gate():
    # .tw 监听桌面档互斥门：≤760 窄档 .tw 无纵向内滚（scrollHeight==
    # clientHeight），水平滚动的 scroll 事件会伪真触发近底条件补片
    # （宽度族随 541-760 带放开扩带 540→760）
    assert "if(window.innerWidth<=760)return;" in PAGE


def test_v204_jump_bottom_page_branch():
    # End 跳底 ≤540 分支：页面滚动到底（.tw.scrollTop 在无内滚容器
    # 上是 no-op）
    assert "window.scrollTo(0,document.documentElement.scrollHeight)" in PAGE


def test_v204_rebuild_page_scroll_restore():
    # ≤540 重建滚动位恢复：内容高塌缩先被浏览器钳位，须先补齐切片
    # 至原落点再 scrollTo 回设（原 tw.scrollTop 快照模式对页滚无效）
    assert "window.scrollTo(0,wy)" in PAGE


# ---- P2-1：脏态三色统一 --warn ----

def test_v204_dirty_state_single_color():
    assert 'id="navDirty" style="display:none;color:var(--warn)' in PAGE
    assert 'id="cfgDirty" style="display:none;color:var(--warn)' in PAGE
    assert (".savebar .dot{width:8px;height:8px;border-radius:50%;"
            "background:var(--warn)") in PAGE


# ---- P2-2：页脚/demoBar 链接触控热区外扩 ----

def test_v204_touch_hotspot_expansion():
    assert "#foot a,.demoBar a,.verbar a{position:relative}" in PAGE
    assert ("#foot a::after,.demoBar a::after,.verbar a::after"
            "{content:'';position:absolute;inset:-10px -4px}") in PAGE
