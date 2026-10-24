# -*- coding: utf-8 -*-
"""r339g 用户实报三案钉：

1. open-folder 路径基准 bug——webui.py 在仓库根，端点却按 __file__ 双层
   dirname 手写基准 → 解析到上级目录（user_data 剥掉后资源管理器直接
   打开 D:\\idea_project）。收口到 _anchored 单源后，白名单三键必须
   全部落仓库根内；
2. 日期添加器二合一——text 手输框+📅 隐藏 date 控件双通道并存（用户实
   报「同时存在两种，非常丑」），收敛为 native date 单输入（选完即加）；
   工具行 chip 与 32px 输入同高（「没对齐」根因=schip 裸 padding 高 24）；
3. 启动级配置重启闭环——保存成功后 _restartArmed 强横幅+立即重启钮；
   /api/restart 先拉携 --restart-delay 的新实例再自退（锁序：旧进程
   退出释放 data/.instance.lock 在前，新实例延迟抢锁在后，反序必撞锁
   退场）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339g_restart_dadd.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
import main  # noqa: E402


# ---- 1. open-folder 白名单解析单源 ----

def test_target_under_repo_root():
    """回归钉：三键解析结果必须落仓库根内（双 dirname 曾逸出上级）。"""
    for w in ("db", "log", "ud"):
        t = webui._open_folder_target(w, {})
        assert t and os.path.isabs(t), (w, t)
        assert t.startswith(webui._ROOT), (w, t)


def test_target_default_values():
    assert webui._open_folder_target("db", {}) == os.path.join(
        webui._ROOT, "data")
    # 目录在=原样返回，不在=父目录兜底（CI 全新 checkout 无 user_data）
    ud = os.path.join(webui._ROOT, "user_data")
    assert webui._open_folder_target("ud", {}) == (
        ud if os.path.isdir(ud) else webui._ROOT)


def test_target_custom_abs_and_unknown():
    # 不存在的绝对文件路径 → 取父目录（端点侧 makedirs 兜底建）
    p = os.path.join(webui._ROOT, "zz", "x.db")
    t = webui._open_folder_target("db", {"output": {"db_path": p}})
    assert t == os.path.dirname(p)
    assert webui._open_folder_target("nope", {}) is None


# ---- 2. 日期添加器二合一 + 3. 重启闭环（源码钉） ----

def _page_src():
    return webui.PAGE


def test_dadd_unified_no_dual_channel():
    src = _page_src()
    assert 'id="${p}add-${i}-${j}"' in src
    assert "_dateRowHTML(i,j,'d')" in src
    assert "_dateRowHTML(i,j,'r')" in src
    # r345：选日期只落输入草稿，显式「加入日期」提交——不再 change 即加，
    # 避免「只想先看看」也写入模型；模式条保证一次只开一种录入方式。
    assert 'onchange="if(this.value)addDate(${i},${j})"' not in src
    assert 'onchange="if(this.value)retAdd(${i},${j})"' not in src
    assert 'data-dm="single"' in src and "function setDateMode(" in src
    for dead in ("dpick-", "rpick-", "dreal-", "rdreal-",
                 "pickDate", "retPick", ".dreal{"):
        assert dead not in src, dead


def test_dtools_chip_height_aligned():
    src = _page_src()
    assert ".dcompose-foot{display:flex;align-items:center;gap:6px" in src
    assert ".dpanel[hidden]{display:none}" in src
    assert ".dtools .chip{height:32px" not in src   # 旧双卡工具行随 r345 退役


def test_restart_ui_and_endpoint():
    src = _page_src()
    assert 'id="restartHint"' in src
    assert "function syncRestartHint(" in src
    assert "function _restartArmed(" in src
    assert "function doRestart(" in src and "doRestartNow(" in src
    assert "async function _restartPoll(" in src
    assert "const _STARTUP_KEYS=['db_path','log_path','user_data_dir','browser_dir','host','run_on_start']" in src
    assert ".rhint{display:flex" in src and ".rhint.armed{" in src
    # 保存成功分支：启动级差量取样必须在快照覆盖之前（覆盖后恒空集）
    i_cap = src.index("_schg=_startupChanged()")
    i_clean = src.index("GLB_CLEAN=JSON.stringify(GLB)", i_cap)
    assert i_cap < i_clean
    assert "if(_schg.length)_restartArmed();" in src


def test_restart_backend_lock_order():
    src = open(webui.__file__, encoding="utf-8").read()
    assert '"/api/restart"' in src
    # 拉新实例携延迟参数；旧进程 1s 后自退（os._exit，WAL 崩溃安全）
    assert '"--restart-delay", "3"' in src
    assert "threading.Timer(1.0, lambda: os._exit(0))" in src
    assert "DETACHED_PROCESS" in src
    # 无 shell 引号拼 launcher（os.startfile/参数列表双通道零注入口）
    assert "os.system('start" not in src
    assert "os.startfile(_tgt)" in src


def test_restart_delay_arg_before_lock():
    msrc = open(main.__file__, encoding="utf-8").read()
    assert '"--restart-delay"' in msrc
    i_sleep = msrc.index("time.sleep(args.restart_delay)")
    i_lock = msrc.index("if not acquire_instance_lock():")
    assert i_sleep < i_lock   # 反序=新实例即时抢锁必撞单实例锁退场


def test_pidfile_self_write_after_lock():
    """pidfile 进程自写钉：/api/restart 直拉的新实例不写 .monitor.pid
    →status/stop 假死盲区（活体首鸣实锤）。位置必须在锁成功之后
    （撞锁退场实例不得覆写在场者的 pid）。"""
    msrc = open(main.__file__, encoding="utf-8").read()
    i_lock = msrc.index("if not acquire_instance_lock():")
    i_pid = msrc.index('".monitor.pid").write_text(')
    assert i_lock < i_pid
    assert "str(os.getpid())" in msrc


# ---- 行为钉（demo 实例真跑） ----

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _wait_up(proc, base):
    import urllib.request
    import time
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        if proc.poll() is not None:
            return False
        try:
            op.open(base + "/", timeout=1).read(64)
            return True
        except Exception:
            time.sleep(0.25)
    return False


import pytest  # noqa: E402


@pytest.fixture(scope="module")
def srv():
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    global BASE
    import subprocess
    import tempfile
    port = _free_port()
    BASE = "http://127.0.0.1:%d" % port
    logf = open(os.path.join(tempfile.gettempdir(),
                             "r339g_srv.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
    if not _wait_up(proc, BASE):
        proc.kill()
        pytest.fail("demo 启动失败")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture()
def page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        yield pg
        browser.close()


def _open_cfg(page):
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.evaluate("showCfgPanel('users')")
    page.evaluate("expandFolds()")
    page.wait_for_timeout(400)


def test_dadd_pick_adds_chip(page):
    """指定日通道：落值不写模型，显式「加入日期」后片 +1（r345 心智模型）。"""
    _open_cfg(page)
    assert page.locator("#cfgview [id^='dpick-']").count() == 0
    assert page.locator("#cfgview [id^='dadd-']").count() > 0
    before = page.evaluate("CFG[0].routes[0].dates||[]")
    page.evaluate("""(() => {const el=document.querySelector("[id^='dadd-']");
      el.value='2028-06-15';el.dispatchEvent(new Event('change'));})()""")
    page.wait_for_timeout(150)
    mid = page.evaluate("CFG[0].routes[0].dates||[]")
    assert len(mid) == len(before), "选完未提交就写模型"
    page.evaluate("addDate(0,0)")
    page.wait_for_timeout(200)
    after = page.evaluate("CFG[0].routes[0].dates||[]")
    assert "2028-06-15" in after and len(after) == len(before) + 1


def test_dtools_chip_32px(page):
    """r345 对称律：区间/指定日两面板等高，切换零跳动。"""
    _open_cfg(page)
    out = page.evaluate("""(() => {
      const row=document.querySelector('.dateSrow[data-drow^="d-"]');
      const comp=row.querySelector('.dcompose');
      const panels=[...row.querySelectorAll('.dpanel')];
      const h0=panels[0].getBoundingClientRect().height;
      row.querySelector('.dctab[data-dm="single"]').click();
      const h1=panels[1].getBoundingClientRect().height;
      return {h0:+h0.toFixed(1),h1:+h1.toFixed(1),
              c0:+comp.getBoundingClientRect().height.toFixed(1)};
    })()""")
    assert out["h0"] > 0 and out["h0"] == out["h1"], out


def test_restart_hint_two_states(page):
    """弱态：编辑启动级键即横幅预警；复原后收起。强态词面属保存路径
    （demo POST 被只读拦截， Armed 分支由源码钉覆盖）。"""
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof GLB !== 'undefined' && GLB")
    page.evaluate("showCfgPanel('globals')")
    page.wait_for_selector("#glbUdd", timeout=8000)
    assert not page.evaluate(
        "document.getElementById('restartHint').style.display!=='none'")
    page.fill("#glbUdd", "user_data_x")
    # fill 只派发 input；内联 onchange 挂 change（失焦/回车提交语义）——
    # 显式补派发（用户失焦路径的等价重放）
    page.evaluate(
        "document.getElementById('glbUdd')"
        ".dispatchEvent(new Event('change'))")
    page.wait_for_timeout(150)
    assert page.evaluate(
        "document.getElementById('restartHint').style.display!=='none'")
    assert "未保存" in page.evaluate(
        "document.getElementById('restartHint').textContent")
    # 复原即收（差量清零不残留）
    page.fill("#glbUdd", "user_data")
    page.evaluate(
        "document.getElementById('glbUdd')"
        ".dispatchEvent(new Event('change'))")
    page.wait_for_timeout(150)
    assert not page.evaluate(
        "document.getElementById('restartHint').style.display!=='none'")
