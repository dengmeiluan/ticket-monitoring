# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r238_webui.py
- tests/test_r243_webui.py
- tests/test_r295_landing.py
- tests/test_r323_webui_pins.py
- tests/test_r326_webui.py
- tests/test_r339d_bind_host.py
- tests/test_r339g_restart_dadd.py
- tests/test_r368_task_deeplink.py
- tests/test_r813g_block_not_masked_by_other_surface.py
- tests/test_r816_session_auth_markers.py
- tests/test_r979_multistate_copy.py
- tests/test_r980_sparse_specials_chart.py
- tests/test_v15115_webui.py
- tests/test_v15276_ui.py
- tests/test_v1559_webui_imghost.py
- tests/test_v1563_webui.py
- tests/test_v1579_webui.py
- tests/test_v160_webui_verbanner.py
- tests/test_v167_webui.py
- tests/test_v173_webui.py
- tests/test_v187_webui.py
- tests/test_v188_webui.py
- tests/test_v195_webui.py
- tests/test_v201_webui.py
- tests/test_v202_webui.py
- tests/test_v295_perf_source.py
- tests/test_v295_prov_ui.py
- tests/test_v295_sector_strip.py
- tests/test_v296_alert_query.py
- tests/test_v297_ui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import crawlers
import io
import json
import logging
import main
import os
import pathlib
import pytest
import re
import sys
import time
import webui

from core.alerter import Alerter, _dw
from core.models import FlightPrice
from core.storage import PriceStorage
from crawlers import REGISTRY
from crawlers.base import BaseCrawler
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler
from webui import NOTIFY_PAGE, PAGE


# ---- merged from tests/test_r238_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_kpi_numlink_href_escaped():
    """KPI 行1 价格链接（numlink）href 挂 he()，与同卡 data-href 同律。"""
    src = _src()
    assert 'href="${he(brief.view)}"' in src, "numlink href 未挂 he()"
    assert 'href="${brief.view}"' not in src, "numlink href 直出旧形态残留"


def test_compare_row_vw_href_escaped():
    """同班比价展开行 a.vw href 挂 he()。"""
    src = _src()
    assert 'href="${he(x.view)}"' in src, "比价行 a.vw href 未挂 he()"
    assert 'href="${x.view}"' not in src, "比价行 href 直出旧形态残留"


def test_detail_row_vw_href_escaped():
    """明细行 ↗（a.vw）href 挂 he()。"""
    src = _src()
    assert 'href="${he(f.view)}"' in src, "明细行 a.vw href 未挂 he()"
    assert 'href="${f.view}"' not in src, "明细行 href 直出旧形态残留"


def test_demo_pushlog_titles_current_form():
    """DEMO pushlog 样例 title=现役可产出形态：达标/未达标锚点分支的
    尾段恒带「另监控」前缀（alerter._rest_seg 语义）——样例词面
    滞后会在烘焙演示站误导预览（审校 P3-2 同案）。"""
    src = _src()
    seg = src[src.index('"items": ['):src.index('"items": [') + 4000]
    assert seg.count("另监控") >= 2, "DEMO 样例 title 缺「另监控」段: %s" % seg[:600]


# ---- merged from tests/test_r243_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_p2_1_pvbody_link_touch_inset_11px():
    src = webui.PAGE
    # 正向锁弹层规则完整串（NOTIFY 轻页 .md a::after 同值 -10px 是
    # 另一合法消费点，inline-block 盒更高零欠账，勿跨语境误伤）
    assert ("#pvMask .pvbody a::after{content:'';position:absolute;"
            "inset:-11px -4px}") in src, "弹层链接触控外扩应 -11px -4px"
    # 旧欠账规则零残留（-7px 系估算口径；-10px 系 Windows 单环境
    # 校准，CI Linux 15px 锚盒下欠 1px）——均带弹层选择器锚
    assert ("#pvMask .pvbody a::after{content:'';position:absolute;"
            "inset:-7px -4px}") not in src, "旧 -7px 规则应已退役"
    assert ("#pvMask .pvbody a::after{content:'';position:absolute;"
            "inset:-10px -4px}") not in src, "旧 -10px 规则应已退役"


def test_p3_1_popstate_deep_link_restored():
    src = webui.PAGE
    # 白名单分支内 switchView 之后必须回写入站 hash；入站带 /uN 段时
    # 原样回写（'#details/u0' 后退恢复主洞），入站裸 tab（无 /uN）时
    # 对齐 showMonTab 写点补用户段——裸回写 '#'+_h 会把 showMonTab
    # 刚写的 '#trend/u2' 洗回 '#trend'（用户段丢失，URL 深链退化）
    i = src.index("['overview','specials','trend','watch','details','health'].indexOf(_tab)>=0")
    block = src[i:i + 640]
    assert ("replaceState(null,'',(_s>0?'#'+_h:'#'+_tab+'/u'+U))" in block), block
    # 旧裸回写形态零残留（洗用户段退化面）
    assert "replaceState(null,'','#'+_h)" not in block, block


# ---- merged from tests/test_r295_landing.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------- P3-E：小节标题零缓冲 ----------

def test_p3e_window_sinks_at_zerobuffer():
    # 生产实锤样本（恰 40.00）：时段窗不再内联进 #### 行、下沉引用行；
    # #### 标题本体 ≤38（加粗字模缓冲）
    out = Alerter._section_title("上海", "海口", "01/29", "（19:00后出发）")
    assert not out.startswith("#### ✈️ 上海→海口 01/29（")
    head = out.split("\n", 1)[0]
    assert "> （19:00后出发）" in out
    assert _dw(head) <= 38


def test_p3e_short_title_still_inline():
    # 非回归：总宽 ≤38 的短标题（短城市名自定义形态）仍走内联首档
    out = Alerter._section_title("沪", "穗", "01/29", "（19:00后出发）")
    assert out.startswith("#### ✈️ 沪→穗 01/29（19:00后出发）")
    assert "> （19:00后出发）" not in out


def test_p3e_no_window_tier2_unchanged():
    # 非回归：无时段窗标题走第二档 head-only，形态不变
    out = Alerter._section_title("上海", "海口", "01/29", "")
    assert out == "#### ✈️ 上海→海口 01/29\n\n"


def test_p3e_headonly_zerobuffer_sinks(monkeypatch):
    # head-only 恰卡带按加粗投影判（P3-A 字模入模型，改写旧 38 代理
    # 钉）：投影 ≤40 内联（纯 CJK 39 带真实放得下，不再一刀切下沉）；
    # 投影破 40（因子放大构造）下沉引用行（日期随沉），地板产出过
    # 投影预算
    import core.alerter as _al
    monkeypatch.setattr(_al, "_TITLE_BOLD_ASCII", 1.0)
    out = Alerter._section_title("超长出发名呀", "超长到达名", "10/05", "")
    assert "10/05" in out.split("\n\n")[0], out
    monkeypatch.setattr(_al, "_TITLE_BOLD_ASCII", 1.6)
    out2 = Alerter._section_title("超长出发名呀", "超长到达名", "10/05", "")
    assert "> 10/05" in out2, out2
    assert _al._dw_bold(out2.split("\n\n")[0]) <= 40, out2


# ---------- P2-1：chip 点击教学 ----------

def test_p2x_chip_gap_predicate():
    # 教学判定（渲染期烘焙，onclick 运行期无 x/m 作用域——helper 形态
    # 在属性里按全局解析必 ReferenceError）：明细池非空且池内无
    # 「胶囊价同值行」才教。|f.price-m[1]|<1 容差吃 round；
    # FLIGGY_TAX_PAD>0 时垫差需并入容差（现行归零定标下成立）
    assert "!(x.flights||[]).some(" in PAGE
    assert "f=>f.plat===m[0]&&Math.abs(f.price-m[1])<1" in PAGE


def test_p2x_chip_toast_teaching():
    # 点击 toast 条件教学句：缺口在场才追加（常态零噪音）；
    # 教学句与渠道名/价格在渲染期拼为字面量注入 onclick
    assert ("_gap?'；￥'+m[1]+"
            "' 为时段窗外等未入明细班次，不在下方列表':''") in PAGE


def test_p2x_chip_title_wordface():
    # title 词面精确化：主因「时段窗外」点名；旧词面禁复活
    assert "渠道全线报价最低（含时段窗外班次，未必可出手）" in PAGE
    assert "含未过约束班次" not in PAGE


# ---- merged from tests/test_r323_webui_pins.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_long_window_empty_copy_is_range_aware():
    src = webui.PAGE
    assert ("TREND_LAB[CR.range]||(CR.range==='7d'?'7 天':'48h')") in src
    assert "这里会出现近 48h 的最低价曲线" not in src


def test_dayk_ring_note_word():
    assert "日K=真实航班当日最低价（不含日历价" in webui.PAGE
    assert "日K=行情池当日最低价（含日历价" in webui.PAGE


# ---- merged from tests/test_r326_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _page():
    return webui.PAGE


def test_save_norm_resolves_intl_name_route_scope():
    src = _page()
    # 航线段三参调用（intl 门开）：国际中文名命中 INTLN 即规范名
    assert "_cnorm(r.from_name,r.from,1)" in src
    assert "_cnorm(r.to_name,r.to,1)" in src
    # 特价段保持国内域（两参调用，intl 门缺省关——国内特价源不收国际名）
    assert "_cnorm(sp0.from_name,sp0.from)" in src
    # 码回写链：CITY 名映射缺席时走 INTLN 名→码（国际名落码而非中文名）
    # R50 竞速终局随修：归一链尾回退原码槽（INTL 表未就绪竞速期
    # _cnorm 按码放行的名字，表缺查不到码时落回存量码槽而非名字——
    # 调度按码取键，名字当码会静默监控错城）
    assert "r.from=CITY[_fn]||INTLN[_fn]||r.from||_fn" in src
    assert "r.to=CITY[_tn]||INTLN[_tn]||r.to||_tn" in src


def test_city_panel_intl_hot_by_code_map():
    src = _page()
    # R36 双 Tab 后：国际目的地按地区分组渲染（INTL.map 直查码→名，
    # data-c=码小写供搜索），仍是码→名正向方向（非反方向查表）
    assert "Object.entries(INTL.map||{})" in src
    # 禁复活：反方向查表（名→码表查码）曾是 33 城全空恒空节
    assert "const n=INTLN[c]" not in src


def test_buildform_initial_render_applies_sync_route_head():
    src = _page()
    # buildForm 初始渲染链对每条航线应用 syncRouteHead——存量国际航线
    # 打开配置页徽标即亮，不再依赖「改任一字段」触发
    assert ("CFG.forEach((u,_ui)=>(u.routes||[]).forEach(("
            "_r,_uj)=>syncRouteHead(_ui,_uj)));") in src


def test_city_panel_filter_covers_hot_section():
    src = _page()
    # 过滤器显式处理热门区（在 .cp-sec 之外的同级容器）
    assert "const hot=$('cpbody').querySelector('.cp-hot');" in src
    assert "hotAny" in src


# ---- merged from tests/test_r339d_bind_host.py ----

def test_bind_host_default_loopback(monkeypatch):
    import webui
    monkeypatch.delenv("TM_WEB_HOST", raising=False)
    assert webui._bind_host({}) == "127.0.0.1"
    assert webui._bind_host({"web": {}}) == "127.0.0.1"


def test_bind_host_env_exit(monkeypatch):
    import webui
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    assert webui._bind_host({}) == "0.0.0.0"
    # config 显式值仍最优先（配置优先律）
    assert webui._bind_host(
        {"web": {"host": "192.168.1.10"}}) == "192.168.1.10"


def test_bind_host_config_beats_env(monkeypatch):
    import webui
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    assert webui._bind_host(
        {"web": {"host": "127.0.0.1"}}) == "127.0.0.1"


def test_bind_host_wired_at_both_bind_sites():
    src = webui_full_src()
    assert src.count("_bind_host(") >= 3  # 定义+两处装配点
    assert 'get("host", "127.0.0.1")' not in src, \
        "裸默认装配残留（须走 _bind_host 单源）"


# ---- merged from tests/test_r339g_restart_dadd.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 1. open-folder 白名单解析单源 ----

def test_target_under_repo_root(monkeypatch):
    """回归钉：三键解析结果必须落仓库根内（双 dirname 曾逸出上级）。

    `TM_USER_DATA_DIR` 在 `user_data_root()` 里的优先于默认值是**刻意设计**
    （config > env > default，单源口径，env 覆盖是写明要支持的部署特性），
    所以本钉显式清掉它，只验「相对路径锚在仓库根」这件事。
    """
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
    for w in ("db", "log", "ud"):
        t = webui._open_folder_target(w, {})
        assert t and os.path.isabs(t), (w, t)
        assert t.startswith(webui._ROOT), (w, t)


def test_target_default_values(monkeypatch):
    """`db`/`ud` 的出厂解析值。

    优先级 config > `TM_USER_DATA_DIR` > 默认值是**刻意设计**（唯一口径，
    与 `main._session_user_data()` 同一条规则），别反过来「修」生产代码；
    本钉要测的是「谁都没配」的出厂值，故先把 env 层显式摘掉。
    """
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
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
    src = webui_full_src()
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





def _open_cfg(page):
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.evaluate("showCfgPanel('users')")
    # `expandFolds()` 只是**当前 DOM 上的临时全开**（注释写明：搜索态全开、
    # 清空后由 cfgSearchClear 还原）。配置数据晚到会重建表单并按 FOLD 回放，
    # 于是「先 expandFolds、后重建」时展开态被丢掉，量到的 .dateSrow 是
    # display:none（实测 0 高，连续 4 次）。
    # 这里走产品自己的持久路径：先写 FOLD、再用 applyFolds 回放，
    # 重建之后仍然保持展开——与用户点开航线是同一个状态源。
    page.evaluate("""()=>{
      FOLD.sec=FOLD.sec||{};FOLD.route=FOLD.route||{};
      document.querySelectorAll('#cfgform .grouplab[data-sec]').forEach(
        g=>{if(g.dataset.sec)FOLD.sec[g.dataset.sec]=false;});
      document.querySelectorAll('#cfgform .rline[data-rk]').forEach(
        rl=>{FOLD.route[rl.dataset.rk]=false;});
      if(typeof saveFold==='function')saveFold();
      if(typeof applyFolds==='function')applyFolds();
    }""")
    page.wait_for_timeout(400)
    page.evaluate("expandFolds()")
    page.wait_for_timeout(200)








# ---- merged from tests/test_r368_task_deeplink.py ----

def test_hash_task_deep_link_seeds_local_task_and_switches_search():
    src = webui.PAGE
    assert "const _hq=location.hash.slice(1)" in src
    assert "const _tid=_hq.slice(5).trim()" in src
    assert "localStorage.setItem('jpsrx_task',_tid)" in src
    seed = src.index("localStorage.setItem('jpsrx_task',_tid)")
    switch = src.index("if(typeof switchView==='function')switchView('search',false)", seed)
    assert switch > seed


def test_task_resume_still_reads_query_for_future_routes():
    src = webui.PAGE
    assert "new URLSearchParams(location.search).get('task')" in src
    i = src.index("function srxTaskResume()")
    j = src.index("if(!id)return;", i)
    k = src.index("URLSearchParams(location.search).get('task')", i)
    assert k < j


# ---- merged from tests/test_r813g_block_not_masked_by_other_surface.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CAPTCHA = "人机验证页（滑块），需在渠道登录窗口完成验证"
TS = "2026-11-01 22:21:11"


def _row(entry, status, note="", rows=0):
    return {"fetched_at": TS, "entry_path": entry, "path_status": status,
            "note": note, "rows": rows, "request_url": ""}


class _Channel:
    login_suspect = False

    def __init__(self, cfg, logger):
        self.user_data_root = cfg.get("user_data_dir", "")

    @property
    def session_saved_at(self):
        return 0.0


@pytest.fixture
def env(monkeypatch, tmp_path):
    for p in REGISTRY:
        (tmp_path / p).mkdir(exist_ok=True)
        (tmp_path / p / "marker").write_text("profile", encoding="utf-8")
        monkeypatch.setitem(REGISTRY, p, _Channel)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {}, raising=False)
    monkeypatch.setattr(webui._State, "logger", logging.getLogger("r813g"))
    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: _Channel(cfg, logger))
    monkeypatch.setattr(webui, "_SLOT_VERIFY", {}, raising=False)
    monkeypatch.setattr(webui, "_ensure_slot_verify_loop", lambda: None)
    # 真实账本里 scopes.domestic.detail_at 就是这个时刻（来自 H5/API 那次成功）
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [], "evidence": {"tuniu": {"domestic": {"detail_at": TS}}}})
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [_row("PC", "blocked", CAPTCHA),
                  _row("H5/API", "ok", "", 37)]})
    return tmp_path


def test_pc_captcha_is_not_masked_by_same_second_h5_detail(env):
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] == "challenge", st
    assert st["block"] and st["block"]["kind"] == "captcha", st
    assert st["block"]["path"] == "PC", st


def test_pc_captcha_surfaces_without_any_detail_evidence(env, monkeypatch):
    """负控：没有明细证据时同样要红，证明上一条不是靠别的偶然路径。"""
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [], "evidence": {}})
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] == "challenge", st
    assert st["block"] and st["block"]["path"] == "PC", st


# ---- merged from tests/test_r816_session_auth_markers.py ----

_LOG = logging.getLogger("t_r816")


def _ck(name, value="v", expires=-1):
    return {"name": name, "value": value, "expires": expires}


def test_auth_markers_are_login_only_and_cover_web_channels():
    assert CtripCrawler.AUTH_COOKIES == ("cticket",)
    assert FliggyCrawler.AUTH_COOKIES == ("unb",)
    assert "cookie2" not in FliggyCrawler.AUTH_COOKIES
    assert QunarCrawler.AUTH_COOKIES == ("_q",)
    assert "QN1" not in QunarCrawler.AUTH_COOKIES
    assert set(TongchengCrawler.AUTH_COOKIES) == {"memberIdNew", "cnUser"}
    assert set(TuniuCrawler.AUTH_COOKIES) == {
        "ssoUser", "TUNIUmuser", "tuniuuser"}


def test_state_has_auth_rejects_anonymous_and_expired_cookies():
    now = time.time()
    q = QunarCrawler({}, _LOG)
    # QN1 是匿名/风控 Cookie，单靠它不能证明登录
    assert q._state_has_auth(
        {"cookies": [_ck("QN1", "visitor", now + 3600)]}) is False
    # 空值不算；已过期的持久 Cookie 不算
    assert q._state_has_auth({"cookies": [_ck("_q", "")]}) is False
    assert q._state_has_auth(
        {"cookies": [_ck("_q", "user", now - 1)]}) is False
    # session Cookie 与未过期持久 Cookie 才算
    assert q._state_has_auth({"cookies": [_ck("_q", "user", -1)]}) is True
    assert q._state_has_auth(
        {"cookies": [_ck("_q", "user", now + 3600)]}) is True

    f = FliggyCrawler({}, _LOG)
    assert f._state_has_auth(
        {"cookies": [_ck("cookie2", "anon", now + 3600)]}) is False
    assert f._state_has_auth(
        {"cookies": [_ck("unb", "12345", now + 3600)]}) is True


def test_qunar_snapshot_with_only_risk_cookie_not_refreshable():
    q = QunarCrawler({}, _LOG)
    state = {"cookies": [
        _ck("QN1", "visitor", -1),
        _ck("QN48", "x", -1),
        _ck("QN300", "x", -1),
    ]}
    assert q._state_has_auth(state) is False


def test_qunar_detail_clears_stale_scope_login():
    """去哪儿任一 scope 真出数 → 更早的别的 scope 拒绝不再催登录。"""
    from datetime import datetime
    from webui import _clear_qunar_stale_auth

    def et(v):
        return datetime.fromisoformat(v).timestamp() if v else 0.0

    scopes = {
        "international": {"needs_login": False,
                          "detail_at": "2026-11-02 19:17:30",
                          "reason": "会话失效"},
        "unknown": {"needs_login": True,
                    "detail_at": "2026-11-02 17:36:58",
                    "reason": "会话失效"},
        # 比最新成功还晚的拒绝是真拒绝，不能清
        "newer": {"needs_login": True,
                  "detail_at": "2026-11-02 19:20:00",
                  "reason": "会话失效"},
    }
    _clear_qunar_stale_auth(
        scopes, et("2026-11-02 16:59:44"), et)
    assert scopes["unknown"]["needs_login"] is False
    assert scopes["unknown"]["reason"] == ""
    assert scopes["newer"]["needs_login"] is True
    # 最新成功的 scope 自己也可能留着旧「会话失效」文案：needs_login
    # 已是 False，但文案不能继续吓用户说会话失效（线上 19:17 实报）。
    assert scopes["international"]["reason"] == ""
    assert scopes["newer"]["reason"] == "会话失效"


def test_qn1999_only_prompts_login_without_auth_cookie():
    # 单次=间歇放行；连续≥2 且无认证 Cookie 才请重登
    assert QunarCrawler._qn1999_is_login(1, False) is False
    assert QunarCrawler._qn1999_is_login(2, False) is True
    # 认证 Cookie 仍在场时，重登救不回 1999，按软拒退避
    assert QunarCrawler._qn1999_is_login(2, True) is False
    assert QunarCrawler._qn1999_is_login(9, True) is False


def test_login_snapshot_requires_auth_cookie():
    q = QunarCrawler({}, _LOG)
    anonymous = {"cookies": [_ck("QN1", "visitor", -1)]}
    logged_in = {"cookies": [_ck("_q", "user", -1)]}
    # 登录窗口“我已登录完成”不是登录证据：无 AUTH 不落盘
    assert q._session_state_allowed(anonymous, "login") is False
    assert q._session_state_allowed(logged_in, "login") is True
    # 采集态同理；迁移不要求认证
    assert q._session_state_allowed(anonymous, None) is False
    assert q._session_state_allowed(anonymous, "migrate") is True


def test_expired_auth_does_not_count_for_other_channels():
    now = time.time()
    for cls, name in (
            (CtripCrawler, "cticket"),
            (TongchengCrawler, "memberIdNew"),
            (TuniuCrawler, "ssoUser")):
        c = cls({}, _LOG)
        assert c._state_has_auth(
            {"cookies": [_ck(name, "old", now - 60)]}) is False
        assert c._state_has_auth(
            {"cookies": [_ck(name, "fresh", now + 3600)]}) is True


# ---- merged from tests/test_r979_multistate_copy.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


PAIRS = [
    ("展开筛选", "收起筛选"),
    ("展开更多条件", "收起更多条件"),
    ("展开概览", "收起概览"),
    ("展开溯源", "收起溯源"),
    ("展开更多工具", "收起更多工具"),
    ("展开渠道镜像", "收起渠道镜像"),
    ("展开探针", "收起探针"),
    ("展开进度", "收起进度"),
    ("展开说明", "收起说明"),
    ("展开详情", "收起详情"),
]


def test_pairs_share_noun_and_length():
    for a, b in PAIRS:
        assert a[:2] == "展开" and b[:2] == "收起", (a, b)
        assert a[2:] == b[2:], "两态名词不一致：%s / %s" % (a, b)
        assert len(a) == len(b), "两态字数不同会让按钮宽度跳动：%s / %s" % (a, b)


def test_more_conditions_trigger_uses_shared_pair():
    import webui
    src = webui.PAGE
    i = src.index('id="srxMoreBtn"')
    seg = src[i:i + 260]
    assert "展开更多条件" in seg, "更多条件触发器又回到无动词的「更多筛选条件」"
    assert "SRX.more?'收起更多条件':'展开更多条件'" in src, \
        "更多条件开合没有使用统一的两态文案"
    assert "更多筛选条件" not in src, "旧的不对称文案仍在"
    assert "收起高级筛选" not in src and "展开高级筛选" not in src, \
        "aria-label 仍与可见文案不同名"


def test_all_two_state_ternaries_are_symmetric():
    import webui
    src = webui.PAGE
    bad = []
    for a, b in re.findall(r"'收起([^']{0,8})'\s*:\s*'展开([^']{0,8})'", src):
        if a != b:
            bad.append(("收起" + a, "展开" + b))
    for a, b in re.findall(r"'展开([^']{0,8})'\s*:\s*'收起([^']{0,8})'", src):
        if a != b:
            bad.append(("展开" + a, "收起" + b))
    assert not bad, "存在两态名词不一致的按钮：%s" % bad
    # 负控：正则确实抓到了现存的多态文案，不是空集假绿
    total = len(re.findall(r"'收起[^']{0,8}'\s*:\s*'展开[^']{0,8}'", src)) + \
            len(re.findall(r"'展开[^']{0,8}'\s*:\s*'收起[^']{0,8}'", src))
    assert total >= 6, "只抓到 %d 组两态文案，正则可能失效" % total


# ---- merged from tests/test_r980_sparse_specials_chart.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_sparse_chart_collapses_to_compact_height():
    import webui
    src = webui.PAGE
    i = src.index(".spmon-chartwrap.is-sparse{")
    seg = src[i:i + 220]
    assert "min-height:168px!important" in seg, seg
    assert "height:168px!important" in seg, seg
    assert ".spmon-chartwrap.is-sparse canvas{height:150px!important}" in src
    assert ".spmon-chartwrap.is-sparse #spMonChartNote{display:none!important}" in src, \
        "矮盒里同义脚注会被裁成半行"


def test_sparse_class_is_set_and_cleared_on_both_empty_branches():
    import webui
    src = webui.PAGE
    # 绘制入口先复位，数据够画线时不残留矮画布
    i = src.index("function spMonDraw(dateSeries,selDate,lowDate){")
    head = src[i:i + 900]
    assert "classList.remove('is-sparse')" in head, head
    # K 线不足两天 + 折线不足两次采集两个分支都要加
    k = src.index("仅 '+he(candles[0].d)+' 一个采集日")
    assert "classList.add('is-sparse')" in src[k - 520:k], "K 线空态没有收成矮盒"
    t = src.index("当前范围只有 '+times.length+' 次采集")
    assert "classList.add('is-sparse')" in src[t - 520:t], "折线空态没有收成矮盒"
    # 覆盖层高度必须按收后的画布重新量，不能沿用收前的 H
    assert "Math.min(H,c.clientHeight||H)" in src, \
        "空态覆盖层仍按收前的画布高度居中"


# ---- merged from tests/test_v15115_webui.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = webui_full_src()
    return _SRC


def test_hdh_observer_writes_var():
    s = src()
    assert "ResizeObserver" in s
    # 变量挂 documentElement（:root 域全局可消费），fallback 域内保现值
    assert "setProperty('--hdh'" in s
    assert s.count("var(--hdh,") >= 5


def test_sticky_tops_consume_hdh():
    s = src()
    # 三处吸顶 top 动态化（fallback 保现值：134/134/54）
    assert "#montabs{position:sticky;top:var(--hdh,134px)" in s
    assert "top:calc(var(--hdh,134px) + var(--mtabsh))" in s
    assert "#montabs{position:sticky;top:var(--hdh,54px)" in s
    # 固定校准块退役：带内覆写值不复在（grep 全文唯一性已核）
    assert "top:76px" not in s
    assert "scroll-padding-top:106px" not in s
    # 761+ 锚点补偿随动态（88 = 54+34 等值迁移，demo 两带实测等值）
    assert "scroll-padding-top:calc(var(--hdh,54px) + 34px)" in s
    assert "scroll-padding-top:88px" not in s


def test_kpisum_link_touch_target():
    # P2-2 触控外扩家族收编（#foot a::after 同款 inset 两行，视觉零变化）
    s = src()
    assert ".kpisum a{position:relative" in s
    assert (".kpisum a::after{content:'';position:absolute;"
            "inset:-10px -4px}" in s)


def test_montab_grid_roving_vertical():
    # EN-4（挂账销账）：↑↓ 网格形制族移动——仅 montabs 挂载，
    # 脉冲柱/健康格行为面不动（单行/既有键面不受扰）
    s = src()
    assert "_rovingV" in s
    assert 'onkeydown="_roving(event,this);_rovingV(event,this)"' in s


# ---- merged from tests/test_v15276_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_discount_cabin_maps_to_economy_for_watch_coverage():
    from core.flighthist import cabin_class
    assert cabin_class("7.0折") == "经济"
    assert cabin_class("4.7折") == "经济"
    assert cabin_class("全价") == "经济"
    assert cabin_class("特价") == "经济"
    assert cabin_class("空客A320") == ""
    assert cabin_class("公务舱 · 7折") == "公务"
    assert cabin_class("头等舱") == "头等"


def test_demo_probe_entry_is_disabled():
    assert "go.disabled=demo" in SRC
    assert "演示模式不发起真实外网探针" in SRC


def test_srx_watch_get_has_inflight_guard():
    assert "pending:false" in SRC
    assert "if(SRX_WATCH.pending)return;" in SRC
    assert "finally{if(seq===SRX_WATCH.seq)SRX_WATCH.pending=false}" in SRC


def test_large_json_responses_gzip():
    assert 'if len(body) > 1024 and "gzip" in (' in SRC
    assert 'self.send_header("Content-Encoding", "gzip")' in SRC
    assert 'self.send_header("Vary", "Accept-Encoding")' in SRC


# ---- merged from tests/test_v1559_webui_imghost.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _webui_src():
    return webui_full_src()


class TestWebuiImghostPins:
    """webui.py 源码级钉死：引导链路错一处即失败（同 模式）。"""

    def test_guide_links_present(self):
        src = _webui_src()
        # 引导动线：注册页 + API Token 直达页，两链缺一不可
        assert 'href="https://sm.ms/home/apitoken"' in src
        assert 'href="https://sm.ms"' in src
        assert 'target="_blank"' in src

    def test_imghost_card_and_toggle(self):
        src = _webui_src()
        assert 'data-ch="imghost"' in src          # 图床卡（chcard 第五张）
        assert "function setIh(" in src            # 原位切换（不整卡重建）
        assert "ih-token" in src                   # Token 行显隐锚点
        assert "ihchip" in src                     # provider chips

    def test_save_validation_smms_token(self):
        src = _webui_src()
        # smms 无 token 无可用通路（推送图必失败）——保存时拦下
        assert "图床选了 sm.ms 但 Token 为空" in src

    def test_users_wholesale_roundtrip(self):
        src = _webui_src()
        # image_host 随「整 users 回传」落盘——此行被改即断链
        assert 'cfg["users"] = body.get("users") or []' in src

    def test_alerter_consumes_upload_chart(self):
        import core.alerter as _a
        src = _read(_a.__file__)
        assert "upload_chart(" in src
        assert "ih=self.image_host" in src


# ---- merged from tests/test_v1563_webui.py ----

def test_cfgfilter_lgcard_in_both_lists():
    """：#cfgview .lgcard 必须同时出现在复位清单与搜索首循环。
    （r275 起复位清单新增孤儿头显隐成员并重组——按「lgcard 在两处
    清单」的意图断言，不再锁整串字面）"""
    clear_i = PAGE.find("function cfgSearchClear")
    filter_i = PAGE.find("function cfgFilter(")   # 带括号防前缀误中 cfgFilterD
    assert clear_i > 0 and filter_i > clear_i, "cfgSearchClear/cfgFilter 缺"
    assert PAGE[clear_i:filter_i].count("#cfgview .lgcard") == 1, \
        "复位清单未含 .lgcard"
    loop_i = PAGE.find("#cfgview .glgrid>div,#cfgview .srow,#cfgview .lgcard")
    assert loop_i > 0, "搜索首循环未并入 .lgcard"
    # 命中判定沿用 textContent+inputs 现成逻辑（lgcard 无 input 亦可）


def test_aa_light_tail_deep_tokens():
    """：三处亮色小字换 --ok-txt/--warn-deep；暗色覆写删除
    （--warn 与 --warn-deep 暗色同值 #d9b34a，覆写纯冗余）。"""
    assert ".okTxt{color:var(--ok-txt)" in PAGE
    assert ".upill.warn{color:var(--warn-deep)" in PAGE
    assert ".hbadge.mid{color:var(--warn-deep)" in PAGE
    assert 'html[data-theme="dark"] .upill.warn' not in PAGE


def test_notify_esc_gt():
    """/：NOTIFY_PAGE esc 与主页 esc 同序补 &gt;（& < > " '）。"""
    assert '.replace(/>/g,"&gt;")' in NOTIFY_PAGE
    # 主页 esc 本就齐全，防两处漂移
    assert ".replace(/>/g,'&gt;')" in PAGE


# ---- merged from tests/test_v1579_webui.py ----

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
    # 静态初始态必须是中性加载词、且不得含教学词面。2026-10-29 起三图加载态
    # 统一成「<b>正在读取…</b><span>只画真实采集点…</span>」两段式（此前航线是
    # 裸文本、关注是两段、雷达什么都没有）；判据改为「有中性加载标题 + 无教学词面」。
    assert 'id="chartEmpty" style="display:flex"><b>正在读取走势</b>' in PAGE, \
        "静态初始文案应为中性加载词（教学词面在此=假空态）"
    _stat = PAGE[PAGE.index('id="chartEmpty"'):PAGE.index('id="chartEmpty"') + 200]
    assert "暂无走势数据" not in _stat, "静态占位不得直接写教学词面"
    # 教学词面必须挂在 chart() 确无数据分支（S 已到达才承诺）。
    # 2026-10-29 起三图空态统一两段式：标题走 <b>、说明走 <span>，
    # 这里守「同一处 innerHTML 同时写标题与说明」，不再钉死前后相邻。
    assert "'<b>暂无走势数据</b><span>完成第一轮扫描后" in PAGE, \
        "教学词面应挂在 chart() 确无数据分支（S 已到达才承诺）"
    assert ("const ce=$('chartEmpty');if(ce&&ce.style.display!=='none')"
            in PAGE), "_markStale 应守卫翻新 chartEmpty（已绘制图表不动）"


def test_desktop_savebar_toast_lift():
    """③≥761 档 savebar 在场 toast 抬升（桌面 savebar 顶缘 77px 与
    toast 基础 78px 仅 1px 巧合缝）；媒体条件与 ≤760 档互斥。
    r264 起 bottom 走 --sbh 实高动态单源（固定 96px 校准退役，
    fallback 40+56=96 为 JS 失效等效值）——钉面随行为演进改写
    （LESSONS 十八§9 双段断言：旧固定值禁复活 + 动态形态在场）。"""
    # r346：桌面块内先声明 savebar 左停靠，再声明 toast 动态抬升
    assert "@media(min-width:761px){" in PAGE
    assert ".savebar{left:18px;right:auto}" in PAGE
    assert "body:has(.savebar.on) #toasts{bottom:calc(var(--sbh,40px) + 56px)}" in PAGE
    assert "body:has(.savebar.on) #toasts{bottom:96px}" not in PAGE


def test_pill_jump_to_qualified():
    """④pill 挂 onclick=jumpQual（role/tabindex/键盘由 mkact 收编），
    jumpQual 带 S 空态守卫（加载期点击 toast 兜底不再静默）并切
    「🔥 仅达标」类别挡。"""
    # 静态初值 title 中性（WC-P2-3：加载态跳转承诺是假 affordance）；
    # 副作用声明由 pillState 正常态承载（数据到达后接管的 title 仍含
    # 「将重置现有筛选」——审计 P2-1 告知面保持）
    assert 'id="pill" title="数据通道状态：加载中" onclick="jumpQual()"' in PAGE
    assert "跳转达标明细（仅达标档，将重置现有筛选）" in PAGE
    assert "toast(" in PAGE[PAGE.find("function jumpQual"):PAGE.find("function jumpQual") + 500]
    # r312 P1-1 词面分路改写（钉面随行为演进，十八§7）：!S 分支按 pill
    # bad 旗标二分——失败态播「…恢复后自动刷新」（与 pill 同词面），
    # 加载态保「数据加载中」兜底；行为级验证在 tools/uitest.py 尾段
    i = PAGE.find("function jumpQual")
    assert "if(!S){" in PAGE[i:i + 60]
    assert "classList.contains('bad')" in PAGE[i:PAGE.find("\nfunction ", i + 10)]
    assert "数据加载中，请稍候" in PAGE[i:PAGE.find("\nfunction ", i + 10)]
    assert "恢复后自动刷新" in PAGE[i:PAGE.find("\nfunction ", i + 10)]
    # 块边界窗口（窗口长度是实现细节，函数增厚不假红）：jumpQual 全体
    assert "F='q'" in PAGE[i:PAGE.find("\nfunction ", i + 10)], \
        "jumpQual 应切到「🔥 仅达标」类别挡"


def test_term_channel_unified():
    """⑤「监控平台」词面清零，统一「监控渠道」（配置页 B 分区 2 处）。"""
    assert "监控平台" not in PAGE
    assert PAGE.count("监控渠道") >= 2


# ---- merged from tests/test_v160_webui_verbanner.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_page_html_injects_version():
    import webui
    html = webui._page_html("1.5.60")
    assert "const PGVER='1.5.60'" in html
    assert "__PAGEVER__" not in html
    # 空版本（极端）注入空串：守卫要求 PGVER 非空才亮，静默不误报
    assert "const PGVER=''" in webui._page_html("")


def test_banner_elements_and_guard_pins():
    import webui
    src = webui.PAGE
    assert 'id="verbar"' in src                # 横幅条
    assert 'id="verTxt"' in src                # 版本号槽
    assert "s.version!==PGVER" in src          # 失配守卫字面
    assert "location.reload()" in src          # 刷新动线
    # 双主题样式在位
    assert ".verbar{" in src
    assert 'html[data-theme="dark"] .verbar{' in src


def test_demo_build_bakes_matching_generation():
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(os.path.dirname(here),
                            "tools", "demo_build.py"),
               encoding="utf-8").read()
    # 烘焙站必须同样注入代际（直用 PAGE 原串会令牌泄漏+横幅误报）
    assert "_page_html(" in src
    assert "webui.PAGE" not in src


# ---- merged from tests/test_v167_webui.py ----

class TestWebuiV167Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_jump_row_trend_rebuilds_chart_chips(self):
        """：跳走势后 chip 高亮显式重建跟随（亮选片停留旧路由根除）。"""
        assert "gotoMonTab('trend');buildChartChips();" in self._src()

    def test_qual_sticky_cell_gradient_single_layer(self):
        """：吸附格 gradient 不透明打底 + 同值 tint 单层（横滚不透）。"""
        src = self._src()
        for tint in (".08", ".14", ".12"):
            assert ("linear-gradient(rgba(var(--okrgb),%s),"
                    "rgba(var(--okrgb),%s)),var(--card)" % (tint, tint)) in src
        # 暗色换谱成对（67,192,114）
        assert src.count("linear-gradient(rgba(67,192,114,") == 2

    def test_qual_price_uses_ok_txt_token(self):
        """：达标行价格绿字 --ok-txt（AA 收编，--green 退役）。"""
        # 断言只锚颜色令牌；字重随全站收敛到四档（800 已并入 700）
        assert "tr.qual td.price{color:var(--ok-txt)" in self._src()


# ---- merged from tests/test_v173_webui.py ----

class TestWebuiV173Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_p1_empty_payload_err_names_real_button(self):
        """：预览空数据教导指向真实按钮词面，旧词面全文件清零。"""
        src = self._src()
        assert 'err": "暂无本轮数据，先「立即扫描一轮」跑一轮"' in src, \
            "空态教导未指向「立即扫描一轮」（指向不存在按钮=教导失效）"
        assert "立即抓取" not in src, \
            "「立即抓取」旧词面残留（docstring/文案未跟产品改名）"

    def test_p2_dialog_aria_label_follows_entry(self):
        """：三入口开弹层时各自显式回设 aria-label（读屏名与可见
        标题一致；previewPush 不回设会被同会话先开的 showLog/pushLog
        留下上一入口的值——uitest 流程 showLog 先于预览实测抓回）。"""
        src = self._src()
        assert ("setAttribute('aria-label','渠道轮日志')" in src
                and "setAttribute('aria-label','推送记录')" in src
                and "setAttribute('aria-label','钉钉推送预览')" in src), \
            "弹层 aria-label 未随入口切换（读屏名与可见标题失配回潮）"
        assert 'aria-label="钉钉推送预览"' in src, \
            "previewPush 静态 aria-label 初始值丢失"

    def test_p3_tj_space_same_as_enter(self):
        """：.tj 内联键位 Enter||Space 同义（Space 冒泡误开比价回潮）。"""
        src = self._src()
        # 内联属性写在单引号 Python 串里，源码里是 \' 转义形态；按 .tj 片段断言，
        # 避免把「引号转义」误判为缺 Space 通道（r1392 修正判据）。
        seg = src[src.index('class="tj rj"'):][:600]
        assert "onkeydown=\"if(event.key===\\'Enter\\'||event.key===\\' \\'){event" \
               ".preventDefault();event.stopPropagation();jumpRowTrend(" in seg, \
            "📈 键位缺 Space 通道（冒泡到行级误开同班比价+role=button " \
            "Space 语义未兑现）"


# ---- merged from tests/test_v187_webui.py ----

class TestWebuiV187Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_kbdtips_coarse_block_after_narrow_block(self):
        """coarse 隐藏块必须层叠在 ≤760 独立成行块之后（源码序后者胜）。"""
        src = self._src()
        assert "@media(max-width:760px){.kbdtips" in src, \
            "≤760 独立成行块缺失"
        i_narrow = src.index("@media(max-width:760px){.kbdtips")
        needle = "@media(pointer:coarse){.kbdtips{display:none}}"
        assert needle in src, "coarse 隐藏块缺失（触屏隐藏失效）"
        i_coarse = src.rindex(needle)
        assert i_coarse > i_narrow, \
            "coarse 隐藏块在 ≤760 块之前——同选择器源码序后者胜，" \
            "真实手机（coarse+窄屏双命中）display:block 复活"

    def test_price_band_guard_helper_exists(self):
        """列表端价格带兜底 helper（与曲线 _rounds 同带单源）。
        r325 收口升级：委托 core.models price_band_ok scope-aware
        单源（国际行元素 intl 键即国际带），helper 不再裸比较常量。"""
        src = self._src()
        assert "def _price_in_band" in src, "价格带兜底 helper 缺失"
        i0 = src.index("def _price_in_band")
        seg = src[i0:i0 + 400]
        assert "price_band_ok" in seg, \
            "helper 未委托 price_band_ok 单源（core.models）"

    def test_price_band_guard_both_collectors(self):
        """flights 两处收集点（当轮展开 + 近 6h 补位）同挂兜底
        （r325：两处均携元素 el 参——国际行凭元素旗标走宽带）。"""
        src = self._src()
        n = src.count('"price" in f and _price_in_band(f.get("price"), f)')
        assert n >= 2, \
            f"flights 收集点须同挂价格带兜底（期望 ≥2 处，现 {n} 处）"


# ---- merged from tests/test_v188_webui.py ----

class TestWebuiV188Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
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


# ---- merged from tests/test_v195_webui.py ----

class TestWebuiV195Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_scroll_listener_batch_append(self):
        """滚动续载 while 化：单事件补齐至落点可见，上限 4 片。"""
        src = self._src()
        i = src.index("querySelector('#tablecard .tw').addEventListener")
        seg = src[i:src.index("},{passive:true})", i)]
        assert "while(n<4&&" in seg.replace(" ", ""), \
            "滚动续载仍是单片 if（End 跳底落点距真底需多按收敛）或缺上限"

    def test_end_key_explicit_jump_bottom(self):
        """End 键显式跳底路径（真机定谳：补片推远底边会打断平滑滚动、
        「距底<600」条件被自身补片失效——键盘路径必须显式补全量再滚
        到底并交接焦点，不依赖滚动事件接力）。"""
        src = self._src()
        assert "function _jumpTableBottom(" in src, \
            "缺 _jumpTableBottom（End 跳底在切片表上不可达真底）"
        i = src.index("function _jumpTableBottom(")
        seg = src[i:i + 700]
        assert "while(_ROWS&&_NDRAW*_CHUNK<_ROWS.length)" in \
            seg.replace(" ", ""), "跳底前未补片至全量"
        assert "rows[rows.length-1].focus()" in seg.replace(" ", ""), \
            "焦点未交接末行（连续 End/Enter 落空）"
        assert "event.key==='End'" in src, "行级键盘未挂 End"

    def test_deep_position_backfill_while_kept(self):
        """轮询刷新深位回填 while 既有形态不被本次改动误伤
        （st 界条件自然收敛，与滚动监听是两条路径）。"""
        src = self._src()
        assert "while(st>0&&tw.scrollHeight<st+tw.clientHeight&&_tblAppend()){}" \
            in src.replace(" ", ""), \
            "table() 深位补齐 while 形态被误改"


# ---- merged from tests/test_v201_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_v201_demo_foot_neutral():
    # demo 页脚语境中立（M-1）：「在线演示 · 静态合成数据」只对烘焙
    # 静态站为实——本地 --demo 是活服务进程（live HTTP+/api/state），
    # 双语境共用 s.demo 无区分位，统一改语境中立词面（双态皆实）。
    assert "演示模式 · 合成数据" in PAGE
    assert "在线演示 · 静态合成数据" not in PAGE


def test_v201_1920_kpi_widen():
    # ≥1920 档 .grid/.kpisum 放宽 1440（M-2）：--kpiw 1168 在 wrap
    # 1716 下卡内右侧 474px 空腔被放大（1440/1680 档同病灶仅 78px
    # 不可感）；每卡 ~703px 仍在可读带（815px 才入宽扁区），空腔
    # 收敛至 202。层叠律：放宽声明必须晚于 600 块 .grid 限宽声明
    # （同特异性后者胜，媒体块无「更严更后胜」——放前面会被无声盖回）。
    w600 = PAGE.index(".grid{grid-template-columns:repeat(2,minmax(0,1fr))")
    w1920 = PAGE.index(".grid,.kpisum{max-width:min(1440px,100%)}")
    assert w1920 > w600
    # 1920 块内脉冲侧同上限仍在（r302 W1：statline 族「跟卡」到网格
    # 1440 上限为止，与 .grid/.kpisum 同值=右缘通线恒等；纯 none 是
    # ≥1726 双轴回潮病灶形态，禁复活）
    assert (".statline,#pulseLegend,.pulsewrap"
            "{max-width:min(1440px,100%)}" in PAGE)
    assert ".statline,#pulseLegend,.pulsewrap{max-width:none}" not in PAGE


def test_v201_kline_narrow_offset():
    # K 线双系列偏移下限（M-3）：cw 触底 4px 时 ±0.62cw=±2.5px 偏移
    # 让两系列中心距 5px<目视分辨并成单列（390 档实测）；下限 4px
    # 保中心距 8px——仍 <pitch（桶序不交错）且环标互叠显著缓解。
    assert "Math.max(cw*0.62,4)" in PAGE
    # 系列偏移是单源 koff：蜡烛/环标/低标锚/避让计数全部消费点
    # 随 koff 迁移，裸 cw*0.62 只允许出现在 koff 定义行——
    # 半迁移会让窄档环标偏离所属蜡烛中心（同族漏迁判例）
    assert PAGE.count("cw*0.62") == 1, \
        "存在未随 koff 迁移的裸 cw*0.62 消费点（半迁移）"


def test_v201_near_hit_and_ghost_guard():
    # 触控横向热区近邻映射（审计 P2-1）：coarse 指针下容器捕获阶段
    # 按「点击 x 到动作格本体矩形的距离」最近邻重判命中——缝死区与
    # 邻格 ::after 吃缝的 off-by-one 一并收掉；双容器（健康格/脉冲
    # 柱）都挂载，桌面鼠标路径不经 coarse 分支零变化。
    assert "_nearHit('hbody','.hc')" in PAGE
    assert "_nearHit('pulsebars','.pbar')" in PAGE
    assert "matchMedia('(pointer:coarse)').matches" in PAGE
    # 幽灵坐标轴守卫（审计 P2-2）：阈值并入量纲源后 vals 恒非空，
    # 真实数据点为零时必须走空态文案（阈值不构成画图理由）
    assert ("if(!vals.length||!(K?CD.length+CT.length:hd.length+ht.length))"
            in PAGE)
    # 未扫描格光标语言跟动作语言（M-1）：none 格无点击动作，无假手型
    assert ".hc.none{cursor:default}" in PAGE


# ---- merged from tests/test_v202_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_v202_webui_baggage_payload():
    # 行载荷透传 baggage（空串归一，前端空值不占位）——载荷在 _user_state
    # 后端段（PAGE 字符串之外），源文件级钉
    import webui as _w
    with io.StringIO(webui_full_src()) as fh:
        src = fh.read()
    assert '"baggage": (f.get("baggage") or "").strip(),' in src


def test_v202_webui_baggage_title():
    # title 悬停承载：进 slot 条件（baggage 单独在场也弹 title），
    # labelNote 后插入 baggage 段（分隔符按「前文有无」判，
    # 只有 baggage 时不出头部分隔符）；carryon 段随后同链（v204）
    assert "(f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null)" in PAGE
    assert ("((f.labels||f.labelNote)&&f.baggage?'｜':'')"
            "+(f.baggage?he(f.baggage):'')"
            "+((f.labels||f.labelNote||f.baggage)&&f.carryon?'｜':'')"
            "+(f.carryon?he(f.carryon):'')") in PAGE
    # baggage 与 bizPrice/儿童价段之间的分隔符条件同步（漏改会出现
    # 「20KG公务￥N」粘连或头部孤立分隔符）
    assert ("((f.labels||f.labelNote||f.baggage||f.carryon)"
            "&&f.bizPrice!=null?'｜':'')") in PAGE
    assert ("(f.labels||f.labelNote||f.bizPrice!=null||f.baggage||f.carryon"
            ")?'｜':'')") in PAGE


def test_v202_webui_baggage_csv():
    # CSV 托运额列：表头（直挂后）与数据行（bagState 表达式后）同轮
    # 两端对齐，防列错位；「手提额」列随 v204 同链插入；经停列随后
    # 携 stopWin 窗口括注（v15115：'是(19:20-20:05)' 形态）
    assert ",'直挂','托运额','手提额','经停'," in PAGE
    assert ("(f.bagState==='direct'?'是':(f.bagState==='recheck'?'需转运':''))"
            ",f.baggage||'',f.carryon||'',"
            "f.stop?('是'+(f.stopWin?'('+f.stopWin+')':'')):''") in PAGE


def test_v202_narrow_tabs_sticky():
    # ≤540 档明细 tabs 行 sticky 吸顶：筛选/分类入口原在首屏折叠线
    # 下 ~150-180px（390 档 fltBtn top≈994 / vh 844），且数百行明细
    # 滚动中随时可筛是高频路径。视图切换器 montabs 同款吸顶（top 消费
    # --hdh 贴 header 实高，fallback 保 134），明细筛选条 top 联动
    # calc(var(--hdh,134px) + --mtabsh)（吸顶双条不重叠，高度改动一处
    # 变量全联动）。置尾纪律：断点块必须晚于基础 .tabs 声明（媒体块
    # 无「更严更后胜」，同特异性源码序后者胜）
    i540 = PAGE.index("@media(max-width:540px)")
    block = PAGE[i540:i540 + 1600]
    assert "#montabs{position:sticky;top:var(--hdh,134px)" in block
    assert ("#montab-details .tabs{position:sticky;\n"
            "    top:calc(var(--hdh,134px) + var(--mtabsh))" in block)
    assert "background:var(--card)" in block
    assert i540 > PAGE.index(".tabs{display:flex")


# ---- merged from tests/test_v295_perf_source.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_facets_guard_and_perf_script():
    import webui
    src = webui_full_src()
    assert "if(!SRX.more&&!force)return;" in src
    assert os.path.isfile(os.path.join(ROOT, "tools", "perf_gate.py"))


# ---- merged from tests/test_v295_prov_ui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_probe_raw_is_labeled_parsed_extra(tmp_path):
    old = webui._State.cfg
    db = str(tmp_path / "r.db")
    webui._State.cfg = {"output": {"db_path": db}}
    try:
        st = PriceStorage(db)
        st.save(FlightPrice("ctrip", "SHA", "BJS", "2026-11-10", 500,
                            extra=json.dumps([{"code": "MU1", "price": 500}]),
                            prov=json.dumps({"entryPath": "PC",
                                             "evidenceLevel": "path"})))
        row = st.last_lowest("SHA", "BJS", "2026-11-10")
        out = webui._probe_raw(row["id"], 0)
        assert out["ok"] and out["evidence_level"] == "parsed_extra"
        assert out["prov"]["entryPath"] == "PC"
    finally:
        webui._State.cfg = old


def test_ui_and_csv_source_pins():
    import webui as w
    src = webui_full_src()
    for s in ("srxEntryOf", "采集入口", "证据级别",
              '"evidence_level": "parsed_extra"',
              "解析 extra / RAW（非原始响应）",
              "解析 extra 与解析字段一致",
              '"entryPath": str((pv or {}).get("entryPath")'):
        assert s in src, s


# ---- merged from tests/test_v295_sector_strip.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_sector_strip_component_and_surfaces():
    import webui
    src = webui_full_src()
    for s in ("function sectorStripHTML", "class=\"sector-strip",
              "function spMonLow", "function wsRunway",
              "function monWatchCard"):
        assert s in src, s
    assert src.count("sectorStripHTML({") >= 3


# ---- merged from tests/test_v296_alert_query.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_radar_auto_query_clamps_past_start_and_skips_ended():
    r = {"from_name": "上海", "to_name": "曼谷", "start": "2026-10-24",
         "end": "2026-10-31", "nationwide": False, "channels": ["ctrip"]}
    q, why = webui._radar_auto_query(r, today="2026-10-25")
    assert why == "clamped" and q["start"] == "2026-10-25"
    assert q["end"] == "2026-10-31" and q["from"] == "上海"
    q, why = webui._radar_auto_query(
        {**r, "start": "2026-10-20", "end": "2026-10-24"},
        today="2026-10-25")
    assert q is None and why == "ended"
    q, why = webui._radar_auto_query({"from_name": "上海"},
                                     today="2026-10-25")
    assert q is None and why == "incomplete"


class _FakeCrawler:
    login_suspect = True


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def info(self, *a, **k):
        pass


def test_notifier_none_is_not_a_send_error(monkeypatch):
    monkeypatch.setattr(crawlers, "REGISTRY", {"qunar": _FakeCrawler})
    monkeypatch.setattr(main, "_sent_save", lambda: None)
    main._LOGIN_ALERT_STREAK.clear()
    main._SENT_LAST.clear()
    main._SENT_CNT.clear()
    log = _Logger()

    class _Al:
        notifier = None

    u = {"name": "u", "platforms": ["qunar"]}
    main._channel_login_alert_sentinel([(u, _Al())], log)
    main._channel_login_alert_sentinel([(u, _Al())], log)
    assert not any("NoneType" in w for w in log.warnings), log.warnings


# ---- merged from tests/test_v297_ui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_radar_and_flat_source_pins():
    import webui
    src = webui_full_src()
    for s in ("date_series", "spMonDeltaTxt", "no-target",
              ".mon-legend>span>b", ".ws-legend{display:grid",
              ".chband{grid-template-columns:148px",
              ".chlink{display:flex", "min-height:36px!important",
              "_wtab.textContent=ws.length?(' · '+ws.length)",
              "每线=一个出发日期", "spMonLow(sel,q,(low||{}).date)",
              "选中日 · 非最低", ".spmon-lowdate .seltag",
              "SPMON_RUN_LABEL", "spMonHistBody", "线尾圆点=最新采集价",
              "window.addEventListener('resize'", ".spmon-run{display:grid",
              ".hdiag-l span{white-space:nowrap}",
              ".hdiag-l span:not(:last-child)::after",
              "#searchview .srx-probefoot{grid-template-columns:1fr;gap:4px 0}",
              "<th>标记</th>", "'最低日 · 选中'", ".rad-pair{display:inline-flex",
              ".spmon-histempty{", "口径较上次变化", "含口径变化日",
              ".spmon-basiswarn", "(low&&low.date?low:null)",
              ".spmon.is-empty .spmon-main", ".spmon.is-empty #spMonCal{display:block}",
              "spMonTip", "c.addEventListener('pointermove',move)", "SPMON.geo=null",
              ".sprad-fld{", ".spmon-run .note{white-space:normal",
              "addEventListener('pointerdown',function(e)",
              "isLow?'<span class=\"lowtag\">最低日</span>'"):
        assert s in src, s


def test_config_has_one_flat_entry_surface():
    import webui
    src = webui_full_src()
    assert 'class="chband"' in src
    assert "border-bottom:1px solid var(--r-hair)!important" in src
    assert "#loginRows .lgslot{background:transparent" in src
