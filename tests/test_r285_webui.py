# -*- coding: utf-8 -*-
"""r285 WebUI 审计收尾三案（TDD 先行，审计报告 _scratch/audit_webui_r285.md）：

W1 [P1] 健康格触屏热区——窄带格本体 5×15px、36px 地板失守（点击格看
    该轮日志触屏不可用）。修法：coarse+≤760 置尾块格宽 9px+容器恢复
    横滚（弹性档 clip 的动机是桌面 hover 呼吸抖动，coarse 无 hover；
    ≥1024 弹性档与 ≤760 带不相交，层叠零冲突）。源码钉锁规则在且
    晚于窄带 5px 声明；行为钉锁 coarse 仿真下 computed 宽。
W3 [P3] 擦边琥珀 --orange 与飞猪渠道橙 --c-fliggy ΔRGB=(7,4,10)
    同屏一色两义——擦边侧向黄移 #c98500（对白 3.06:1 保图形档 3:1 线，
    与飞猪橙 G 通道差 31 可辨；与 --warn #8a6c00 明度差保分档；
    --thline 中转虚线差异同步拉大）。钉面锁「新值在场+旧值退役+
    与飞猪橙通道差 ≥20+canvas fallback 同值」（JS fallback 字面量
    与令牌漂移=取色回退双态分叉）。
W5 [P3] 宽档节奏——wrap 渐进上限 min(1716px,max(1180px,92vw))
    连续函数（托底+封顶，带界差 <2%）；基础 wrap 固定 18px padding 在
    1200 临界带产出贴边↔居中断崖（clamp(12px,3vw,56px) 连续化）。
    源码钉锁现形态+断缝形态退役；行为钉锁 1900/1921 wrap 宽差 <10%。

备案（审计 P3 撤案三件，现场复核推翻）：
- W2 描绿价对比 2.33:1——审计样本为暗色态描边（#43c072=暗 --green）
  按白底计算；亮色描边 var(--green)=#0e8345 对白 4.88:1、暗色对
  #101823 8.65:1 两态均过线（探针检测点错位，二十三§2 姊妹）。
- W4 opsbtns ≤580 横滚暗示——r247 W1 已落地（mask 挂 xhint 类），
  390 触屏实测 class 含 xhint+mask 渐隐生效；demoBar 已随本案补
  36px 地板；a.numlink 实测 36px 达标（审计 28px 为旧测量）。
- W6 pill 无 hover——.pill:hover{filter:brightness(1.07)} 在案
  （185 行），审计检测项未含 filter=假阳性。
- 空腔带 761-860/901-999——@media 900/999/761 带在配置页
  （.cfglayout）、健康页（.ssub）、吸顶补偿（scroll-padding/toasts）
  均有真实消费，监控页四视图实测不构成清理证据，备案不动。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r285_webui.py -q
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（自包含，形态同 test_r279_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8796" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    base = "http://127.0.0.1:%d" % _free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(base.rsplit(":", 1)[1])],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            op.open(base + "/api/state", timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    assert proc.poll() is None, "demo 实例启动失败"
    from playwright.sync_api import sync_playwright as _sp
    with _sp() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base + "/", wait_until="networkidle")
        try:
            yield (p, page)
        finally:
            browser.close()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


# ---------- W1: 健康格触屏热区（源码序钉 + computed 行为钉） ----------

def test_hc_coarse_hotzone_source_pin():
    """源码钉：coarse+≤900 覆写块（格宽 9px+横滚恢复）在场，且声明
    位置晚于窄带 5px 基础声明（同特异性置尾胜，LESSONS 二十一§1）。
    r286 P2-3 扩带 760→900：iPad 竖屏 768/810/820 真空带入覆写域
    （钉面随行为演进改写，显式落位强度不降）。"""
    src = _page_src()
    assert "@media(pointer:coarse) and (max-width:900px)" in src, \
        "coarse 覆写块缺席（或未扩带 ≤900）"
    assert ".hc{width:9px;flex:none}" in src, "格宽 9px 覆写缺席"
    assert ".hcells{overflow-x:auto;overflow-y:hidden}" in src, \
        "横滚恢复缺席"
    i_base = src.find(".hc{width:5px}")
    i_fix = src.find(".hc{width:9px;flex:none}")
    assert 0 < i_base < i_fix, "覆写块必须晚于窄带 5px 基础声明"


def test_hc_coarse_hotzone_computed(srv):
    """行为钉：coarse 仿真（CDP setTouchEmulationEnabled——媒体特性
    features 对 pointer 静默不生效，二十三§4）+390 视口下健康格
    computed 宽 ≥9px（红态=窄带 5px 仍胜出）。健康格在健康 tab 容器
    （display 切换架构下非活动量纲全零，LESSONS 十八§8——先真实切换
    再取样）。"""
    pw, page = srv
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setTouchEmulationEnabled",
             {"enabled": True, "maxTouchPoints": 5})
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("switchView('mon')")
        page.evaluate("showMonTab('health', true)")
        page.wait_for_timeout(500)
        w = page.evaluate(
            """()=>{const e=document.querySelector('.hc');
                return e?e.getBoundingClientRect().width:null;}""")
        assert w is not None, "健康格取样失败（tab 未激活？）"
        assert w >= 9, "coarse 格宽 %s px（5px 窄带仍胜出=触屏不可命中）" % w
        match_media = page.evaluate(
            "matchMedia('(pointer:coarse)').matches")
        assert match_media, "触屏仿真未生效（CDP 形态核对）"
    finally:
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})


# ---------- W3: 擦边琥珀与飞猪橙分离 ----------

def test_amber_distinct_from_channel_orange():
    """语义钉：--orange（擦边进度条/健康 part 档/中转曲线）与
    --c-fliggy（飞猪渠道身份色）通道差 ≥20（审计实测 ΔRGB=(7,4,10)
    同屏一色两义）；对白对比 ≥3:1（非文字图形档）；JS canvas 取色
    fallback 与令牌同值（漂移=回退双态分叉）。"""
    src = _page_src()
    m = re.search(r"--orange:#([0-9a-fA-F]{6})", src)
    assert m, "--orange 令牌缺席"
    amber = m.group(1).lower()
    assert amber != "c96a10", "旧值未退役"
    assert amber == "c98500", "擦边琥珀未按裁决向黄移: %s" % amber
    mf = re.search(r"--c-fliggy:#([0-9a-fA-F]{6})", src)
    assert mf, "飞猪渠道色缺席"
    fr = tuple(int(mf.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    ar = tuple(int(amber[i:i + 2], 16) for i in (0, 2, 4))
    dmax = max(abs(a - b) for a, b in zip(ar, fr))
    assert dmax >= 20, "与飞猪橙通道差 %d 仍不可辨（<20）" % dmax
    # 对白对比（WCAG 相对亮度）
    def _lum(rgb):
        def _c(c):
            c /= 255.0
            return c / 12.92 if c <= 0.03928 else \
                ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (_c(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    ratio = 1.05 / (_lum(ar) + 0.05)
    assert ratio >= 3.0, "擦边琥珀对白 %.2f:1 <3:1（非文字图形档）" % ratio
    # canvas fallback 同值
    assert src.count("||'#%s'" % amber) == 2, \
        "JS canvas 取色 fallback 与令牌不同值（漂移）"


# ---------- W5: 宽档节奏平滑 ----------

def test_wrap_rhythm_source_pin():
    """源码钉：wrap 渐进带一条连续函数（92vw 随视口、1180 托底、
    1716 封顶）+基础 clamp 留白在场；旧硬顶/旧 1320 上限/带界断缝
    形态退役。"""
    src = _page_src()
    assert ".wrap{max-width:min(1716px,max(1180px,92vw))}" in src, \
        "渐进带连续上限缺席"
    assert "min(1716px,92vw)" not in src, \
        "带界断缝形态复活（下侧无托底的 92vw=1280-1440 恒 1180 与渐进带断缝）"
    assert re.search(r"\.wrap\{max-width:1716px\}", src) is None, \
        "1920 硬顶旧形态复活"
    assert re.search(r"\.wrap\{max-width:min\(1320px,92vw\)\}", src) is None, \
        "旧 1320 上限（跳变断口的另一侧）复活"
    assert "padding:0 clamp(12px,3vw,56px) 18px" in src, \
        "wrap 留白 clamp 缺席"


def test_wrap_rhythm_no_jump(srv):
    """行为钉：1900→1921 视口 wrap 宽差 <10%（红态=硬顶跳变 +30%；
    LESSONS 十六§10：修复验收在病灶带复测原症状指标）。"""
    pw, page = srv
    widths = {}
    for w in (1900, 1921):
        page.set_viewport_size({"width": w, "height": 900})
        page.wait_for_timeout(250)
        widths[w] = page.evaluate(
            "()=>{const e=document.querySelector('.wrap');"
            "return e?e.getBoundingClientRect().width:null;}")
    a, b = widths[1900], widths[1921]
    assert a and b, "wrap 取样失败"
    assert abs(b - a) / a < 0.10, \
        "wrap 宽 %.0f→%.0f（+%.0f%%）跳变仍在" % (a, b, (b - a) / a * 100)


def test_demobar_link_touch_floor():
    """demoBar 链接触控地板 36px（源码钉：padding 8px 0 形态）。"""
    src = _page_src()
    assert re.search(
        r"\.demoBar a\{[^}]*padding:8px 0", src), \
        "demoBar 链接触控地板缺席"
