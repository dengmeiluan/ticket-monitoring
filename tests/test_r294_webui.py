# -*- coding: utf-8 -*-
"""r294 WebUI 审计两案（TDD 先行，审计报告 _scratch/worker_r294_webui.md）：

P3-1 明细表「停X:YY」衔接徽标断词孤字——中转列衔接时长徽标渲染串
    漏挂 .nw 豁免（td .stl{white-space:normal} 放开换行的容器里违
    词组粒度纪律，LESSONS 十七§6：≤768 带 20/20 折行「停」单字成行，
    审计 Range 逐字符行分组实锤）。修法：class 两分支均补 nw
    （td .stl.nw 0,2,1 豁免族在案压 0,1,1）。源码钉锁渲染串 nw 在场；
    行为钉锁「带 nw 的 .stl 徽标在 td 环境 nowrap 生效」（护豁免族
    CSS——demo 合成库不产 layoverT 词面，探测节点注入真实 td 环境）。
P3-2 cfg 日期片 ✕ 触控热区差 1px 不达 36 地板——本体 9×15 +
    ::after inset:-13px 双向扩展=35×41（探针 _r294_dx_probe.py 实测
    computed；审计报 34×40 现象属实但根因初判「无扩展族」有误——
    扩展族在案，真实缺陷是扩展量差 1px）。修法：inset:-13px→-14px
    （37×43 双达；横向外缘落在自身 chip 内衬+6px 片间距内，不侵入
    相邻日期片命中区）。源码钉锁 -14px 在场+-13px 退役（全仓唯一
    声明点）；行为钉锁 coarse 仿真下 ::after computed 宽 ≥36。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r294_webui.py -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（形态同 test_r285_webui.py，端口 8797） ----------

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
            if "127.0.0.1:8797" in ln and "LISTENING" in ln:
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


# ---------- P3-1: 衔接徽标断词孤字（源码钉 + 行为钉） ----------

def test_layover_badge_nw_source_pin():
    """源码钉：中转列衔接时长徽标两分支 class 均含 nw——断言串从
    L2724 渲染串逐字节复制（三十一§3：断言串手抄漏段=恒绿死钉）。
    「停X:YY」是「汉字+时刻」复合词组，td .stl 放开换行的容器里
    必须整词包 nw（td .stl.nw 0,2,1 压 0,1,1）。"""
    src = _page_src()
    # 达标/欠达标分支：'stl lay nw' 前缀 + ok 后缀条件拼接
    assert "('stl lay nw'+((+f.layoverM||0)>=f.layMin?' ok':'')):'stl nw'" in src, \
        "衔接徽标渲染串 nw 豁免缺席（断词孤字回归）"


def test_layover_badge_nowrap_behavior(srv):
    """行为钉：带 nw 的 .stl 衔接徽标在明细表 td 环境（.stl 放开换行
    容器）computed white-space=nowrap——护 td .stl.nw 豁免族 CSS
    （demo 合成库不产 layoverT 词面，探测节点注入真实 td 后量测，
    量毕移除；class 串与源码钉的渲染串产物一致）。"""
    pw, page = srv
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("switchView('mon')")
    page.evaluate("showMonTab('details')")
    page.wait_for_timeout(400)
    ws = page.evaluate("""()=>{
      const td=document.querySelector('#ftable tbody tr td');
      if(!td)return {err:'no td'};
      const probe=document.createElement('div');
      probe.className='stl lay nw';
      probe.textContent='停5:10';
      td.appendChild(probe);
      const ws=getComputedStyle(probe).whiteSpace;
      const w=probe.getBoundingClientRect().width;
      probe.remove();
      return {ws, w};
    }""")
    assert "err" not in ws, "明细表无行可取样（demo 表未渲染？）"
    assert ws["ws"] == "nowrap", \
        "td .stl.nw 豁免族失效（white-space=%s，断词孤字回归）" % ws["ws"]


# ---------- P3-2: 日期片 ✕ 触控热区（源码钉 + 行为钉） ----------

def test_dx_hotzone_source_pin():
    """源码钉：.dx 命中区三件套（r300 P3-1 实体盒改形后的双段断言，
    十八§9——改形退役的是四面 -14px 形态不是热区能力）。本文件持
    ::after 三值档与禁复活两段（②③）；实体盒三声明段（①）在
    test_r300_webui.py::test_dx_entity_box_source_pin：
    ① 实体盒三声明（inline-block+右 padding 14+负 margin 对消）——
    行尾悬空语境 ::after 右向扩展失效的实体承载；
    ② ::after 三值档 inset:-14px 0 -14px -14px（左/纵 -14 维持、
    右向 0 防 padding 撑盒双倍越界）；
    ③ 旧四面形态 inset:-14px} 禁复活（右向同向双倍越界 37→51）。"""
    src = _page_src()
    assert ".dchip .dx::after{content:'';position:absolute;inset:-14px 0 -14px -14px}" in src, \
        ".dx ::after 三值档在场断言失败（左/纵扩展丢失或右向越界）"
    assert "inset:-13px" not in src, \
        "旧形态 inset:-13px 残留（35px 差 1px 不达 36 地板）"


def test_dx_hotzone_computed(srv):
    """行为钉：coarse 仿真（CDP setTouchEmulationEnabled，二十三§4）
    +390 视口下 .dx ::after computed 宽 ≥36。日期片在配置页 users
    面板航线卡内（display 切换架构，LESSONS 十八§8——先真实展开
    航线卡再取样；FOLD.route 新键 !==false 恒折叠，「清空已有键」
    不等于「全量置 false」，须逐 rk 显式置 false）。"""
    pw, page = srv
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setTouchEmulationEnabled",
             {"enabled": True, "maxTouchPoints": 5})
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("switchView('cfg')")
        page.evaluate("showCfgPanel('users')")
        page.wait_for_timeout(300)
        page.evaluate("""()=>{
          document.querySelectorAll('#cfgform .rline[data-rk]').forEach(rl=>{
            FOLD.route[rl.dataset.rk]=false;});
          applyFolds();
        }""")
        page.wait_for_timeout(300)
        w = page.evaluate("""()=>{
          const dx=document.querySelector('.dchip .dx');
          if(!dx)return {err:'no dx'};
          if(dx.getBoundingClientRect().width===0)return {err:'dx hidden'};
          const cs=getComputedStyle(dx,'::after');
          return {w:parseFloat(cs.width), h:parseFloat(cs.height)};
        }""")
        assert "err" not in w, ".dx 取样失败（%s）" % w.get("err")
        assert w["w"] >= 36, \
            ".dx 热区 computed 宽 %s px（<36 地板，触屏难点中）" % w["w"]
        match_media = page.evaluate(
            "matchMedia('(pointer:coarse)').matches")
        assert match_media, "触屏仿真未生效（CDP 形态核对）"
    finally:
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
