# -*- coding: utf-8 -*-
"""r248 WebUI 四案 + C1 前端接线（TDD 先行）：

W1 api() busy 重入守卫——busy 的 pointer-events:none 只挡指针，键盘
Enter 在请求在途时合成 click 照发，api() 是同族九件（previewPush/
testPush/testEm 等全有首行守卫）唯一漏网成员，且承载 POST /api/run|
push 两个后果最重的动作（双轮扫描/双份钉钉推送）。
W2 #navDirty 亮色对比度 4.42:1 <4.5（--warn on --headbg，与已修的
.hbadge.mid/.upill.warn 同底同色同病家族漂移漏网）→ --warn-deep。
W3 toast 可点击关闭但 tabindex=-1 无逐条 role——键盘唯一路径 Esc 只
关最新一条，「可点件必有键盘路径」纪律缺口。
W4 过期监控日期标注——sweep 跳采后（r248 数据层 D1），过期日期在
概览无任何「为何没数据」的可见性，日期分组 chip 带「已过期·停采」。
C1 ticketRisk 三端接线（state 投影 + 价格格 ⚠ 徽标 + PNG 槽）。
W5 明细空态指路 ≤760 分档——「重置筛选」按钮在移动端默认收起的
🎛 筛选抽屉内，宽屏词面「点『重置筛选』」在 ≤760 是断头路（按钮
不可见），须给抽屉语境版。
W6 .logpre word-break:break-all 把日志分隔线 ====== 折成孤行——
改 overflow-wrap:anywhere（长 token 仍可断、普通连字符串不硬断）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r248_webui.py
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("t248w")


def _page_src():
    import webui
    return webui.PAGE


# ---------- W1: api() busy 重入守卫（源码钉，同族九件同款写法） ----------

def test_api_busy_reentry_guard():
    src = _page_src()
    m = src.index("async function api(act,msg,b){")
    body = src[m:src.index("\nasync function", m + 10)]
    assert "if(b.classList.contains('busy'))return;" in body, (
        "api() 缺 busy 重入守卫：pointer-events:none 只挡指针，键盘 Enter "
        "在请求在途时合成 click 照发（双轮扫描/双份钉钉推送）——同族九件"
        "（previewPush/testPush/testEm）全有首行守卫，本函数是唯一漏网")


# ---------- W2: navDirty 对比度（--warn-deep 家族） ----------

def test_navdirty_uses_warn_deep():
    src = _page_src()
    m = src.index('id="navDirty"')
    seg = src[m - 200:m + 200]
    assert "color:var(--warn-deep)" in seg, (
        "navDirty 琥珀点在亮色 --headbg 上 4.42:1 <4.5（.hbadge.mid/"
        ".upill.warn 同病家族），改 --warn-deep（6.21）")
    # --warn-deep 变量在亮/暗双主题均有定义
    import re as _re
    assert _re.search(r"--warn-deep:\s*#", src), "--warn-deep 变量未定义"


def test_navdirty_contrast_computed(srv):
    """行为钉：亮色下 navDirty 实际渲染色对 header 底 ≥4.5。"""
    pw, page = srv
    page.evaluate("""() => {
      const nb=document.getElementById('navDirty');
      nb.style.display='';
    }""")
    got = page.evaluate("""() => {
      function lum(c){const m=c.match(/\\d+(\\.\\d+)?/g).map(Number);
        const a=[m[0],m[1],m[2]].map(v=>{v/=255;
          return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);});
        return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2];}
      const nb=document.getElementById('navDirty');
      const cs=getComputedStyle(nb);
      const head=document.querySelector('header')||document.body;
      let hb=getComputedStyle(head).backgroundColor;
      if(!hb || hb==='transparent' || /rgba\\([^)]*,\\s*0\\)/.test(hb)){
        hb=getComputedStyle(document.documentElement)
          .getPropertyValue('--headbg')||'#fff';}
      const l1=lum(cs.color),l2=lum(hb);
      return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
    }""")
    assert got >= 4.5, "navDirty 对比度 %.2f < 4.5" % got


# ---------- W3: toast 键盘路径（行为钉） ----------

def test_toast_keyboard_dismiss(srv):
    pw, page = srv
    page.evaluate("toast('测试通知','ok')")
    page.wait_for_selector("#toasts .toast", timeout=3000)
    st = page.evaluate("""() => {
      const t=document.querySelector('#toasts .toast');
      return {tab: t.tabIndex, role: t.getAttribute('role')};
    }""")
    assert st["tab"] == 0, "toast 无键盘焦点（tabindex=-1=可点件无键盘路径）"
    assert st["role"] == "button", "toast 缺逐条 role（读屏语义）"
    page.evaluate("""() => {
      const t=document.querySelector('#toasts .toast');
      t.focus();
      t.dispatchEvent(new KeyboardEvent('keydown',
        {key:'Enter',bubbles:true}));
    }""")
    gone = page.evaluate(
        "() => !document.querySelector('#toasts .toast')")
    assert gone, "Enter 未关闭聚焦 toast（键盘关闭路径断）"


# ---------- W4: 过期日期可见性 ----------

def test_state_expired_dates_field(tmp_path):
    """_user_state 产 expiredDates（全部 dates < today 的日期列表）：
    sweep 跳采后概览对「为何没数据」的可见性数据源。"""
    import sqlite3
    import webui
    dbp = str(tmp_path / "t.db")
    con = sqlite3.connect(dbp)
    con.execute(
        "CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, "
        "platform TEXT, extra TEXT, fetched_at TEXT, from_city TEXT, "
        "to_city TEXT, depart_date TEXT, price REAL)")
    con.commit()
    con.close()
    u = {"name": "t", "routes": [{
        "from": "URC", "to": "SHA", "from_name": "乌鲁木齐",
        "to_name": "上海", "dates": ["2020-01-01"],
        "alert_direct": 0, "alert_transfer": 0,
        "transfer_arrival_max": "02:00",
        "transfer_layover_min": 0, "transfer_baggage": ""}]}
    old_cfg = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        st = webui._user_state(u)
    finally:
        webui._State.cfg = old_cfg
    assert st.get("expiredDates") == ["2020-01-01"]


def test_expired_badge_render_pin():
    src = _page_src()
    assert "expiredDates" in src and "停采" in src, (
        "概览未消费 expiredDates 渲染「已过期·停采」徽标——"
        "跳采后用户在概览看不到任何「为何没数据」的说明")


def test_expired_badge_single_date_branch():
    """单日期过期航线同样渲染「已过期·停采」徽标（Soldier P2-3：徽标
    只在多日期分支渲染，单日期分支对过期日期仍按未采空态显示「下轮
    自动补上」——与跳采事实矛盾，恰是 W4 要消除的盲区残留）。"""
    src = _page_src()
    m = src.index("const _sd=bdates[0]||'';")
    seg = src[m:m + 500]
    assert "_exp.has(_sd)" in seg, (
        "单日期分支缺过期徽标：单日期过期航线 KPI 无任何停采说明")
    assert "已过期·停采" in src, "徽标词面缺失"
    # KPI 空态「下轮自动补上」对过期日期是假承诺：kpiCard 须按日期
    # 分档词面（过期=已停采，不承诺下轮）
    assert "下轮自动补上" in src, "未过期空态词面不应被移除"
    i = src.index("下轮自动补上")
    pre = src[max(0, i - 300):i]
    assert "_exp.has(dk)" in pre, (
        "kpiCard 空态未按过期分档：过期日期仍承诺「下轮自动补上」"
        "（该日期已被跳采，永远不会有下轮）")


# ---------- W5: 明细空态指路 ≤760 分档（审计 P2-3） ----------

def test_empty_state_copy_mobile_branch():
    """空态词面按视口分档：≤760 的「重置筛选」按钮藏在默认收起的
    🎛 筛选抽屉里，宽屏词面「试试清空上方时段/价格筛选，或点
    『重置筛选』」在移动端指了一个不可见的按钮（断头路）——
    ≤760 须给抽屉语境版（先展开再重置）。"""
    src = _page_src()
    m = src.index("没有符合条件的航班")
    seg = src[m:m + 400]
    assert "innerWidth<=760" in seg, (
        "明细空态指路未按视口分档：≤760 的「重置筛选」按钮在默认收起"
        "的筛选抽屉内，宽屏词面给移动用户指了一个看不见的按钮")
    assert "展开" in seg, "≤760 分支缺抽屉语境词面（先展开再重置）"


# ---------- W6: .logpre 断词改 overflow-wrap:anywhere（审计 P2-4） ----------

def test_logpre_overflow_wrap():
    """日志弹层 word-break:break-all 把分隔线 ====== 硬折成孤行——
    overflow-wrap:anywhere 语义：长 token（URL/traceId）仍可断行防溢出，
    普通连字符串不硬断。"""
    src = _page_src()
    m = src.index(".logpre{")
    seg = src[m:m + 300]
    assert "overflow-wrap:anywhere" in seg, (
        ".logpre 仍用 word-break:break-all：分隔线/时间戳被硬折成孤行"
        "（应改 overflow-wrap:anywhere——长 token 仍断、普通串不硬断）")
    assert "word-break" not in seg, ".logpre 残留 word-break 硬断规则"


# ---------- C1: ticketRisk 三端接线 ----------

def test_ticketrisk_state_projection():
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert '"ticketRisk"' in src, "state 投影白名单缺 ticketRisk"


def test_ticketrisk_price_cell_badge():
    src = _page_src()
    assert "f.ticketRisk" in src, (
        "价格格缺 ticketRisk ⚠ 徽标（agePolicy/riskPolicy 同族渲染门）")


def test_ticketrisk_png_slot():
    src = open(os.path.join(ROOT, "report.py"), encoding="utf-8").read()
    assert "ticketRisk" in src, "PNG 总表 kvs 缺 ticketRisk 槽"


def test_webui_list_pool_dep_mismatch_filter():
    """列表端两收集点（当轮展开+近 6h 补位）消费滚动过滤（Soldier
    P2-1：注释宣称三端同滤，消费点缺失=防线缺口）。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert 'if g.get("_dep_mismatch"):' in src, \
        "当轮展开收集点缺滚动行过滤"
    assert "if _dmm(g, _d0):" in src, \
        "近 6h 补位收集点缺滚动行过滤"


# ---------- playwright srv fixture（demo 实例，行为钉共用） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _srv_log_tail(logf):
    try:
        logf.flush()
        logf.seek(0)
        return logf.read()[-600:]
    except Exception:
        return "(日志不可读)"


@pytest.fixture(scope="module")
def srv():
    pytest.importorskip("playwright",
                        reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    # 残留清理：Windows 形态命令，缺失/非 Windows 静默跳过（r245 加固律）
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
            if "127.0.0.1:8798" in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass
    # 两次机会：每次新取空闲口重绑；失败断言带服务输出尾——CI Linux
    # 独有红的第一手定性证据（r245 首轮 CI 红为无诊断裸断言）。
    # 渲染目录不显式 setenv：conftest autouse 已把 TM_RENDER_DIR 重定向
    # 到预建 tmp 目录（显式指仓库 _scratch 在 CI 上不存在=demo 写渲染
    # 即死——CI ERR_CONNECTION_REFUSED 的真因）。
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    base = None
    for _attempt in (1, 2):
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
                    break   # 进程已死，早退换口重试
                time.sleep(0.5)
        else:
            continue
        if proc.poll() is None:
            break
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）\n服务输出尾:\n"
                    + _srv_log_tail(logf))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base, wait_until="networkidle")
        yield p, page
        browser.close()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if errors:
        raise AssertionError("demo 页面 JS 错误: %s" % errors)
