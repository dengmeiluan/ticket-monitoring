# -*- coding: utf-8 -*-
"""r314 WebUI 设计质感落地（TDD 先行，审计报告 _scratch/audit_webui_r314.md）：

- P1-1 RM 禁令伪元素盲区：`*{transition/animation:none}` 的 `*` 只匹配
  元素不匹配 `::before/::after`——达标呼吸点 pulse、busy 转圈 spin 在
  prefers-reduced-motion 下实测仍动画（L451 注释宣称的「静止环降级」
  不成立）。修法：选择器扩 `*,*::before,*::after`。
- P1-2 `.pill.bad` 错误态零语义着装：JS 错误路径在用 `pill bad` 类而
  CSS 无此规则——「服务异常」pill 与中性 pill 逐通道同形。补红档
  （--redbg/--red/--redbd 令牌现成，.hbadge.bad 同族先例）。
- P2-1 `.cnav.on` 实底选中家族唯一辉光缺口 + `:focus-visible` reclaim
  必须配套（rngchip.on 先例；同属性后者胜，无 reclaim 时辉光吃焦点环）。
- P2-2 主题切换 body 孤苗过渡：全站唯一带主题过渡的属性在 0.3s 里
  独自渐变产出混合态灰晕（卡片瞬切、页底独缓）——删即归零（审计方案 A）。
- P2-3 erow 零命中「重置筛选」纯词面不可执行 → 内联一键恢复
  （空态教学词面给路不如就地给门；r248 的 ≤760 抽屉语境分档保留）。
- P3-1 `.tw` sticky 表头滚动态投影：页头「内容从栏下滑过」sh2 语言
  同轨下放；首列缝影并入；焦点环特异性 (0,4,1) 恒压滚动影 (0,3,2)
  （不挂 ID 前缀，深滚聚焦时环胜）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r314_webui_polish.py
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = None
BASE = ""
_proc = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(timeout=20.0):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.time() + timeout
    while time.time() < end:
        try:
            with opener.open(BASE + "/api/state", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE, _proc
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    PORT = _free_port()
    BASE = "http://127.0.0.1:%d" % PORT
    _proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_up(), "demo 启动失败"
    yield _proc
    _proc.terminate()
    try:
        _proc.wait(timeout=5)
    except Exception:
        _proc.kill()


@pytest.fixture(scope="module")
def brows(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def pg(brows):
    page = brows.new_page(viewport={"width": 1440, "height": 900})
    page.set_default_timeout(10000)
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    yield page


@pytest.fixture(scope="module")
def pgrm(brows):
    """reduced-motion 上下文独立页（P1-1 专用；媒体偏好属 context 级）。"""
    ctx = brows.new_context(reduced_motion="reduce",
                            viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(10000)
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    yield page
    ctx.close()


# ---------- P1-1: RM 伪元素盲区 ----------

def test_rm_pseudo_element_motion_killed(pgrm):
    """行为钉：RM 下伪元素动画必须归零——pulse（呼吸点 ::before）与
    spin（busy 转圈 ::after）的 computed animationName 都须为 none。
    旧选择器 `*{}` 对伪元素不生效，两处实测为 pulse/spin（红）。"""
    got = pgrm.evaluate("""()=>{
      const d=document.createElement('div');
      d.innerHTML='<span class="pill ok">x</span><button class="busy">y</button>';
      document.body.appendChild(d);
      const cs1=getComputedStyle(d.querySelector('.pill.ok'),'::before');
      const cs2=getComputedStyle(d.querySelector('button.busy'),'::after');
      const r={pulse:cs1.animationName,spin:cs2.animationName};
      d.remove();return r;}""")
    assert got["pulse"] == "none", (
        "RM 下达标呼吸点 ::before 仍在动画（animationName=%s）——`*` 选择器"
        "不匹配伪元素，RM 禁令须扩 `*::before,*::after`" % got["pulse"])
    assert got["spin"] == "none", (
        "RM 下 busy 转圈 ::after 仍在动画（animationName=%s）——同上" % got["spin"])


def test_rm_selector_source_pin():
    """源码钉：RM 块选择器含伪元素两臂。"""
    import webui
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert ("@media(prefers-reduced-motion:reduce){*,*::before,*::after"
            "{transition:none!important;animation:none!important}}") in src, (
        "RM 禁令选择器未扩伪元素（*::before,*::after 两臂必须在场）")


# ---------- P1-2: .pill.bad 错误态着装 ----------

def test_pill_bad_dressed_red(pg):
    """行为钉：`pill bad` 挂类后 computed 底色须等于 --redbg 令牌解析值
    （对照：修前与中性基态 --headbg 逐通道同值）。暗色随令牌自动换谱，
    本钉锚「随类走」不锚具体色值。"""
    got = pg.evaluate("""()=>{
      const d=document.createElement('div');
      d.style.background='var(--redbg)';document.body.appendChild(d);
      const want=getComputedStyle(d).backgroundColor;d.remove();
      const p=document.getElementById('pill');const keep=p.className;
      p.className='pill bad';const got=getComputedStyle(p).backgroundColor;
      p.className=keep;return {want:want,got:got};}""")
    assert got["got"] == got["want"], (
        "pill.bad 错误态无语义着装：computed 底色 %s ≠ --redbg %s "
        "（与中性基态同形，「红=失败」语言在 pill 缺席）"
        % (got["got"], got["want"]))


# ---------- P2-1: .cnav.on 辉光 + focus reclaim ----------

def test_cnav_on_glow_and_focus_reclaim(pg):
    """行为钉：配置左导航选中项 computed boxShadow 须含 --glow 辉光；
    程序化 focusVisible 直焦时须被 reclaim 环（0 0 0 2px --blue）接管
    （无 reclaim 时同特异度后者的辉光会吃掉焦点环，rngchip.on 先例）。"""
    got = pg.evaluate("""()=>{
      switchView('cfg');
      const el=document.querySelector('.cnav.on');
      if(!el)return {miss:true};
      const d=document.createElement('div');
      d.style.boxShadow='0 2px 8px -2px var(--glow)';
      document.body.appendChild(d);
      const glow=getComputedStyle(d).boxShadow;d.remove();
      const rest=getComputedStyle(el).boxShadow;
      el.focus({focusVisible:true});
      const foc=getComputedStyle(el).boxShadow;
      el.blur();
      return {glow:glow,rest:rest,foc:foc};}""")
    assert not got.get("miss"), "配置左导航无选中项（demo 态缺 .cnav.on）"
    assert got["rest"] == got["glow"], (
        ".cnav.on 选中态无辉光：computed %s ≠ 家族辉光 %s "
        "（实底选中家族唯一缺口）" % (got["rest"], got["glow"]))
    assert "0px 0px 0px 2px" in got["foc"], (
        ".cnav.on 聚焦时 reclaim 环缺席（辉光同属性覆盖焦点环）: %s"
        % got["foc"])


# ---------- P2-2: body 孤苗过渡删除 ----------

def test_body_no_solo_theme_transition(pg):
    """行为钉：body 的 transitionDuration 须为 0s（主题切换全站瞬切一致；
    孤苗 0.3s 渐变=卡已暗底仍亮的混合态灰晕窗口）。"""
    got = pg.evaluate(
        "getComputedStyle(document.body).transitionDuration")
    assert got == "0s", (
        "body 仍带主题过渡（transitionDuration=%s）——全站唯一孤苗过渡，"
        "切换瞬间产出混合态灰晕" % got)


# ---------- P2-3: erow 内联重置钮 ----------

def test_erow_zero_hit_inline_reset(pg):
    """行为钉：真实输入管线制造零命中（#fq 填垃圾词）→ erow 指引词面
    内含可执行重置钮 → 点击后结果集恢复（erow 退场）。修前纯词面
    actionable=false，点击无处落（红）。"""
    pg.evaluate("switchView('mon');showMonTab('details');"
                "const fb=document.querySelector('.fbar');"
                "if(fb&&getComputedStyle(fb).display==='none')togFlt();")
    pg.fill("#fq", "ZZZZNOMATCH")
    try:
        pg.wait_for_selector("#ftable .erow", timeout=8000)
        btn = pg.locator("#ftable .erow button")
        assert btn.count() >= 1, (
            "erow 零命中指引无可执行重置钮（纯词面指路，恢复动作要视线"
            "往返找筛选条按钮，≤760 还要先展开抽屉）")
        btn.first.click()
        pg.wait_for_function(
            "document.querySelector('#ftable .erow')===null", timeout=8000)
        n = pg.evaluate(
            "document.querySelectorAll('#ftable tbody tr[data-k]').length")
        assert n > 0, "点击内联重置钮后结果集未恢复（erow 未退场或行缺失）"
    finally:
        pg.fill("#fq", "")   # 状态复位：失败态垃圾词不外溢到同页后续钉段


# ---------- P3-1: sticky 表头滚动态投影 ----------

def test_tw_scrolled_header_shadow(pg):
    """行为钉：.tw 深滚（scrollTop>2）后 thead th computed boxShadow 须
    含滚动投影（rgba(20,31,43,.25) 家族值），回顶后回落为缝影原形；
    首列 th 滚动态须缝影+投影双影共存。焦点环特异性 (0,4,1) 恒压本条
    (0,3,2)，深滚聚焦时环胜——顺带锁首列聚焦环不被滚动影吃掉。"""
    pg.evaluate("switchView('mon');showMonTab('details');"
                "const fb=document.querySelector('.fbar');"
                "if(fb&&getComputedStyle(fb).display==='none')togFlt();")
    pg.fill("#fq", "")   # 前序钉段残留防御（共享页状态复位律）
    pg.wait_for_selector("#ftable tbody tr[data-k]")
    pg.evaluate(
        "document.querySelector('#tablecard .tw').scrollTop=500")
    pg.wait_for_function(
        "document.querySelector('#tablecard .tw').classList"
        ".contains('scrolled')", timeout=5000)
    got = pg.evaluate("""()=>{
      const tw=document.querySelector('#tablecard .tw');
      const th=tw.querySelector('thead th:nth-child(2)');
      const th1=tw.querySelector('thead th:first-child');
      return {mid:getComputedStyle(th).boxShadow,
              first:getComputedStyle(th1).boxShadow};}""")
    assert "rgba(20, 31, 43, 0.25)" in got["mid"], (
        "深滚后表头无滑过投影: %s" % got["mid"])
    assert "rgba(20, 31, 43, 0.25)" in got["first"], (
        "深滚后首列表头缺滚动投影: %s" % got["first"])
    assert "2px 0px 0px" in got["first"], (
        "深滚后首列缝影丢失（滚动影须与 2px 缝影双影共存）: %s"
        % got["first"])
    pg.evaluate(
        "document.querySelector('#tablecard .tw').scrollTop=0")
    pg.wait_for_function(
        "!document.querySelector('#tablecard .tw').classList"
        ".contains('scrolled')", timeout=5000)
    back = pg.evaluate("""()=>{
      const tw=document.querySelector('#tablecard .tw');
      return getComputedStyle(tw.querySelector('thead th:nth-child(2)')).boxShadow;}""")
    assert "rgba(20, 31, 43, 0.25)" not in back, (
        "回顶后滚动投影未回落: %s" % back)


def test_tw_scrolled_middle_column_focus_ring(pg):
    """M-1（Soldier）：深滚态键盘聚焦非首列排序表头，焦点环须与滚动投影
    融合在场——scrolled 规则 (0,2,2) 恒压通用环 th.srt:focus-visible
    (0,2,1) 且该环自带 outline:none，无融合行时焦点指示全灭（P2-1
    在 .cnav 修掉的同族病于表头复发，先滚后 Tab 即触发）。"""
    pg.evaluate("switchView('mon');showMonTab('details');"
                "const fb=document.querySelector('.fbar');"
                "if(fb&&getComputedStyle(fb).display==='none')togFlt();")
    pg.fill("#fq", "")
    pg.wait_for_selector("#ftable tbody tr[data-k]")
    pg.evaluate(
        "document.querySelector('#tablecard .tw').scrollTop=500")
    pg.wait_for_function(
        "document.querySelector('#tablecard .tw').classList"
        ".contains('scrolled')", timeout=5000)
    got = pg.evaluate("""()=>{
      const tw=document.querySelector('#tablecard .tw');
      const th=tw.querySelector('thead th.srt:nth-child(3)');
      th.focus({focusVisible:true});
      const bs=getComputedStyle(th).boxShadow;th.blur();return bs;}""")
    assert "0px 0px 0px 2px inset" in got, (
        "深滚态聚焦非首列表头焦点环全灭（scrolled 规则压过通用环 + "
        "outline:none）: %s" % got)
    assert "rgba(20, 31, 43, 0.25)" in got, (
        "聚焦态滚动投影丢失（融合行须环+投影共存）: %s" % got)
