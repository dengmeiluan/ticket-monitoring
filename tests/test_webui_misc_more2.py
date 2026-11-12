# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1163_vendor_app_plats.py
- tests/test_r235_webui.py
- tests/test_r248_webui.py
- tests/test_r261_webui.py
- tests/test_r320b_trendlong.py
- tests/test_r329_intl_fields.py
- tests/test_r380_soft_budget.py
- tests/test_r506b_pending_rendered.py
- tests/test_v15116_enhance.py
- tests/test_v1559_webui.py
- tests/test_v193_statecache.py
- tests/test_v284_batch_probe.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import crawlers
import datetime as _dt
import glob
import gzip
import io
import json
import logging
import os
import pathlib
import pytest
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
import webui

from core.channels import APP_CHANNELS, BROWSER_CHANNELS
from core.flightnorm import normalize
from core.models import FlightPrice
from core.pacing import Pacing, advise, classify_failure
from core.storage import PriceStorage
from crawlers.base import BaseCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tuniu import TuniuCrawler
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from webui import PAGE


# ---- merged from tests/test_r1163_vendor_app_plats.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_map_is_derived_from_channel_constants():
    import webui

    m = getattr(webui, "VENDOR_APP_PLATS", None)
    assert isinstance(m, dict) and m, "缺少 VENDOR_APP_PLATS"
    for vendor, apps in m.items():
        assert vendor in BROWSER_CHANNELS, "厂商键不在 BROWSER_CHANNELS：%s" % vendor
        for a in apps:
            assert a in APP_CHANNELS, "指向不存在的 App 渠道：%s（%s）" % (a, vendor)


def test_no_phantom_app_channel_in_source():
    """负控：**代码行**里不许再出现 app_tuniu 这种不存在的渠道名。

    注释里会提到这个名字（解释历史 bug），所以只看非注释行。
    """
    code = "\n".join(ln for ln in WEBUI.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "app_tuniu" not in code, "webui.py 仍写死 app_tuniu（APP_CHANNELS 里没有）"
    for vendor in BROWSER_CHANNELS:
        expect = "app_" + vendor
        if expect not in APP_CHANNELS:
            assert expect not in code, "又出现不存在的渠道名：%s" % expect


def test_tuniu_maps_to_empty_not_phantom():
    import webui

    assert webui.VENDOR_APP_PLATS.get("tuniu") == (), (
        "途牛没有同名 App 渠道，应映射为空元组：%r"
        % (webui.VENDOR_APP_PLATS.get("tuniu"),))


def test_known_pairs_kept():
    import webui

    assert webui.VENDOR_APP_PLATS.get("ctrip") == ("app_ctrip",)
    assert webui.VENDOR_APP_PLATS.get("fliggy") == ("app_fliggy",)
    assert webui.VENDOR_APP_PLATS.get("tongcheng") == ("app_tongcheng",)
    assert webui.VENDOR_APP_PLATS.get("qunar") == ("app_qunar",)


# ---- merged from tests/test_r235_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_legend_series_dimension():
    """P2-1：走势图例色票 display 随系列数据维度收放（空系列隐藏）。"""
    src = _src()
    assert "$('lgDirect').style.display=(CR.mode==='kline'||!hd.length)?'none':''" in src
    assert "$('lgTrans').style.display=(CR.mode==='kline'||!ht.length)?'none':''" in src


def test_kline_ringnote_cluster_sentence_conditional():
    """P2-1：K线簇位句「左簇=直飞 · 右簇=中转」按双簇在场条件化，
    单簇时不再产生无所指的簇位注释。"""
    src = _src()
    assert "左簇=直飞 · 右簇=中转" in src
    i = src.index("左簇=直飞 · 右簇=中转")
    head = src[max(0, i - 400):i]
    assert "CD.length&&CT.length" in head, "簇位句未按双簇条件化"


def test_cal_tier_legend_only_when_th():
    """P2-1：日历档位图例仅 th>0（未设心理价永无档位色，图例空挂）。"""
    src = _src()
    assert '(CR.r.th&&CR.r.th.direct)>0?\'<span class="cs-lg">深绿=真达标' in src
    assert "else $('calStats').innerHTML='';" in src


def test_channel_dot_contrast_light():
    """亮色渠道识别色票 ≥3:1 非文字对比（v1.5.274 与 SRX 芯片并轨）。

    旧谱飞猪 #c2661a / 途牛 #a87b16 与检索芯片的 #c47f00 / #2f9e44
    双轨；现全部引用 --c-* token，飞猪向深橙 #b85c12 收口以与
    擦边琥珀 #c98500 保持 ≥20 通道差。
    """
    src = _src()
    assert "--c-fliggy:#b85c12" in src, "亮色飞猪色票未加深"
    assert "--c-tuniu:#2f9e44" in src, "亮色途牛色票未加深"
    # 暗色块本过（7.8+）不动
    assert "--c-fliggy:#e8a94a" in src
    assert "--c-tuniu:#45b95a" in src


def test_tgb_cheap_solid_green():
    """P2-2：改期微图低价棒实色 --green（rgba α.45 对白卡 1.6:1）。"""
    assert ".tgb.cheap{background:var(--green)}" in _src()


def test_hint_no_opacity_tax():
    """P2-3：.hint 规则体不再有 opacity 弱化税。"""
    src = _src()
    i = src.index(".hint{")
    j = src.index("}", i)
    assert "opacity" not in src[i:j], src[i:j]


def test_detail_legend_no_orphan_band():
    """P2-4：761-860 带 #tabs b.muted 独占整行且左贴行首（孤行可读）。"""
    src = _src()
    assert "@media(min-width:761px) and (max-width:860px)" in src
    i = src.index("@media(min-width:761px) and (max-width:860px)")
    seg = src[i:i + 300]
    assert "#tabs b.muted" in seg and "flex-basis:100%" in seg, seg


def test_canvas_height_vw_coupled():
    """P2-5→r236 P1-1 重落：canvas 高度 clamp 联动 vw，取大语义——
    宽短带（28vw>38vh）真正抬升、窄高窗复原 38vh（旧取小式对目标带
    零实效且窄高窗反向变矮，审计 1440×700 实测与病灶逐字节同）。"""
    assert "height:clamp(240px,max(38vh,28vw),360px)" in _src()


def test_th_scope_col():
    """P2-6：表头 th 带 scope="col"（读屏表格导航）。"""
    assert 'data-k="${k}" scope="col"' in _src()


def test_mtab_roving_tabindex():
    """P2-7 退役改写（r275）：roving tabIndex 随 tablist 形制退役
    （#montabs 混入非 tab 子件后降 button 形态，全员可 Tab）——旧
    roving 赋值禁复活；tabAria 助手在案（aria-pressed 回写实效档）。"""
    src = _src()
    i = src.index("function tabAria()")
    # 窗口取块边界（下一个顶层 function）而非固定字符数（三十一§3
    # 判例：窗口长度是实现细节，块内合法增厚不应红）
    j = src.find("\nfunction ", i + 10)
    seg = src[i:j if j > 0 else i + 1600]
    assert "x.tabIndex=x.classList.contains('on')?0:-1" not in seg, \
        "roving tabIndex 复活"
    assert "aria-pressed" in seg, "aria-pressed 回写缺席"


def test_cfg_search_debounce():
    """P2-8：配置搜索 250ms 防抖（applyFltD 同款先例），重建重放
    路径（buildForm 后 cfgFilter 直调）不受扰。"""
    src = _src()
    assert "function cfgFilterD(){clearTimeout(_cfgT)" in src
    assert "CFGQ=this.value;cfgFilterD()" in src


def test_line_ringnote_two_series_note_conditional():
    """推送审计 P2-2 兄弟消费点（Soldier P2-2）：折线尾注「两线均为
    行情池最低 · 中转不限直挂」按双系列在场条件化（单系列不宣称两线）。
    钉面随环注段序重组改写、语义担保保留（二十八§3）。"""
    src = _src()
    assert "(hd.length&&ht.length)?" in src
    assert "两线均为真实航班日桶最低（不含日历价）" in src
    assert "两线均为行情池最低（含日历价）" in src


def test_push_flight_exits_sanitized():
    """Soldier P2-1：非 digest 主路径（_push_flight/_push）出口接线
    sanitize_desp（航班名/经停城市自由文本的消毒管辖面完整）；
    r242 起出口 title 同律消毒（钉面随接线形态改写、语义担保保留
    并增强——LESSONS 二十八§3）。"""
    import pathlib as _pl
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    al = _pl.Path(os.path.join(root, "core", "alerter.py")).read_text(
        encoding="utf-8")
    # 2 处非 digest 出口（_push_flight/_push）；digest 出口的
    # "title"/"desp" 双键消毒形态由 test_sanitize_desp_exists_and_wired
    # 与 test_r242_push 锁
    assert al.count("send(sanitize_desp(title), sanitize_desp(desp))") >= 2,         "非 digest 出口消毒接线缺失"


def test_push_banner_fall_word_alignment():
    """推送 P2-2：邮件横幅 ↩️ 支词面「回落出线」与标题/正文头同语言
    （TIER_FULL['fall']='达标回落' 是图内价格档词，横幅借词曾一邮
    两词面）。"""
    from core.notifier import _TIER_BANNER
    d = dict(_TIER_BANNER)
    assert d["↩️"][2] == "回落出线", d["↩️"]


def test_daily_top3_fallback_fire_mark():
    """推送 P2-3：日报图挂兜底 TOP3 对达标行亮 🔥（与告警路径
    _top3_blocks 能力对称，三十§3；池行 _qual 预打旗标为口径）。"""
    src_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "report.py")
    src = pathlib.Path(src_path).read_text(encoding="utf-8")
    i = src.index("def _daily_top_fallback")
    # 窗口=块边界（下一个顶层 def），固定字符窗对合法注释增厚过敏
    # （卅一§3：窗口长度是实现细节，锚结构才是钉面）
    j = src.find("\ndef ", i + 1)
    seg = src[i:j if j > 0 else i + 6000]
    assert '"🔥 " if bool(fl.get("_qual"))' in seg, seg


def test_sanitize_desp_exists_and_wired():
    """推送 P2-4：desp 出口尖括号/省略号消毒单源在场，告警与日报
    两路径出口接线（八§1 尖括号全禁的构造端兜底；`<`＜ 为 HTML
    开标签源剥除，孤 `>` 是 markdown 引用记号保留，U+2026 实锤
    渲染成「。。。。」一并剥除）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    al = pathlib.Path(os.path.join(root, "core", "alerter.py")).read_text(
        encoding="utf-8")
    assert "def sanitize_desp" in al
    assert 'return {"title": sanitize_desp(title), "desp": sanitize_desp(desp),' in al,         "告警路径出口未接线"
    rp = pathlib.Path(os.path.join(root, "report.py")).read_text(
        encoding="utf-8")
    assert "sanitize_desp(" in rp, "日报路径出口未接线"


def test_wintoast_plain_space_compress():
    """推送 P3-1：WinToast _plain 双空格压缩（与 _alert_body 同律）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nt = pathlib.Path(os.path.join(root, "core", "notifier.py")).read_text(
        encoding="utf-8")
    i = nt.index("def _plain(")
    seg = nt[i:i + 2500]
    assert "{2,}" in seg, seg[:200]


def test_alert_body_md_contract_doc():
    """推送 P2-1（备案形态）：_alert_body docstring 显式声明输出仍含
    markdown 的消费者契约（ntfy/Aliyun 各自补剥在案；派生文本律的
    契约锚）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nt = pathlib.Path(os.path.join(root, "core", "notifier.py")).read_text(
        encoding="utf-8")
    i = nt.index("def _alert_body(")
    seg = nt[i:i + 1500]
    assert "markdown" in seg and "消费者" in seg, seg[:300]


# ---- merged from tests/test_r248_webui.py ----

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




# ---------- W3: toast 键盘路径（行为钉） ----------



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
    m = src.index("'没有符合条件的航班'")
    seg = src[m:m + 400]
    # v1.5.274：筛选抽屉全档默认收起，旧「上方/右上」方向词必然有一档
    # 说谎；空态统一以控件名指路，并按抽屉真实开合态给下一步
    assert "点「筛选」展开抽屉放宽条件" in seg, seg
    i = src.index("const _fOpen=")
    assert 0 < m - i < 700, "空态未消费抽屉开合态"


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


def test_ihtest_overflow_wrap():
    """图床测试结果行（.ihtest）同族姊妹钉（r320 WebUI 审计 P3-1）：
    .ihtest 是全站最 URL 密集的词面（上传回链），break-all 把长 URL
    逐字硬断——与 .logpre/.toast 同族迁移 overflow-wrap:anywhere。
    全仓 PAGE 样式区 word-break:break-all 零残留（禁复活）。"""
    src = _page_src()
    m = src.index(".ihtest{")
    seg = src[m:m + 300]
    assert "overflow-wrap:anywhere" in seg, (
        ".ihtest 仍用 word-break:break-all：上传回链长 URL 被逐字硬断"
        "（应改 overflow-wrap:anywhere——长 token 仍断、普通串不硬断）")
    assert "word-break" not in seg, ".ihtest 残留 word-break 硬断规则"
    assert "word-break:break-all" not in src, (
        "PAGE 样式区 word-break:break-all 复活（r302 W3/.logpre/.ihtest "
        "三案语义：一律 overflow-wrap:anywhere）")


# ---------- C1: ticketRisk 三端接线 ----------

def test_ticketrisk_state_projection():
    src = webui_full_src()
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
    src = webui_full_src()
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




# ---- merged from tests/test_r261_webui.py ----

def test_dslash_single_source():
    """日期短标词面单源：dSlash helper 在案，裸内联换装写法零残留
    （r260 词面统一案的内联存量收口——裸表达式残留是词面漂移温床）。"""
    assert 'function dSlash(' in PAGE
    # dSlash 定义内两处（YYYY-MM-DD 长形态 + 协议 MM-DD 短形态各一）
    assert PAGE.count("replace('-','/')") == 2, (
        "MM→斜杠换装必须收敛进 dSlash 单源（Date 解析的 replace(/-/g,'/')"
        " 不在此列）")


def test_dslash_consumed_at_audit_points():
    """审计 P3-1 三处残留消费点换装：改期微图柱 title、轴标、
    日历格悬停 tip（格面已换而悬停仍旧词面=同簇双格式）。"""
    assert 'he(dSlash(p[0]))' in PAGE, "改期柱 title 仍裸 MM-DD"
    assert 'he(dSlash(tg[0][0]))' in PAGE, "改期轴标首仍裸 MM-DD"
    assert 'he(dSlash(cur))' in PAGE, "改期轴标出发日仍裸 MM-DD"
    # 日历悬停 tip 的日期词面走 dSlash（tip 拼接基换装）
    assert 'const ds=dSlash(d)' in PAGE
    assert "ds+' 直飞最低" in PAGE


def test_host_hint_startup_badge():
    """审计 P3-2：「监听地址」重启生效项在 🔥 段头下须挂 ♻ 启动级
    视觉家族（与 ♻ 只读三件同族），段头「保存即热生效」不再与
    hint「重启生效」无标冲突。"""
    assert '· 重启生效' in PAGE


# ---- merged from tests/test_r320b_trendlong.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DAY = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
_MD = _DAY[5:]          # 面板口径的 MM-DD


def _fp(code="CZ1", price=1500.0, transfer=False, fetched=None,
        frm="SHA", to="URC", date="2026-11-01"):
    # 元素数组形态（与生产 extra 同构，transCity 长在元素层）
    el = {"price": price, "code": code, "name": code,
          "depTime": "08:00", "arrTime": "11:00"}
    if transfer:
        el["transCity"] = "郑州"
    extra = json.dumps([el], ensure_ascii=False)
    kw = {"fetched_at": fetched} if fetched else {}
    return FlightPrice(
        platform="qunar", from_city=frm, to_city=to,
        depart_date=date, price=price, airline="", flight_no=code,
        depart_time="08:00", arrive_time="11:00",
        extra=extra, **kw)


def test_refresh_daily_idempotent_and_shape(tmp_path):
    """当日桶重算幂等（重扫修正）：两轮两价 → n=2/lo/open/close 有序。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp("CZ1", 1500.0, fetched=_DAY + " 08:00:00"),
        _fp("CZ2", 1400.0, fetched=_DAY + " 12:00:00"),
    ])
    st.refresh_daily("SHA", "URC", "2026-11-01", day=_DAY)
    st.refresh_daily("SHA", "URC", "2026-11-01", day=_DAY)
    rows = st.daily_series("SHA", "URC", "2026-11-01", days=30)
    assert len(rows) == 1, rows
    b = rows[0]
    assert b["day"] == _MD and b["n"] == 2, b
    assert b["lo"] == 1400.0 and b["hi"] == 1500.0, b
    assert b["open"] == 1500.0 and b["close"] == 1400.0, b


def test_daily_series_window_and_sort(tmp_path):
    """days 窗（按今天回看）与日升序；窗外桶不返回。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    # r1022：窗口是「相对今天回看 N 天」，写死日期的用例会随系统日期推移失效
    # （2026-11-01 当天实测：10-01 已落在 30 天窗外，断言恒空）。改成相对日期：
    # 窗外 40 天 与 窗内 20 天各一条，期望只回窗内那天。
    import datetime as _dt
    today = _dt.date.today()
    outside = (today - _dt.timedelta(days=40)).isoformat()
    inside = (today - _dt.timedelta(days=20)).isoformat()
    for d in (outside, inside):
        st.save_many([_fp("CZ1", 1200.0, fetched=d + " 08:00:00")])
        st.refresh_daily("SHA", "URC", "2026-11-01", day=d)
    rows = st.daily_series("SHA", "URC", "2026-11-01", days=30)
    assert [b["day"] for b in rows] == [inside[5:]], rows
    rows180 = st.daily_series("SHA", "URC", "2026-11-01", days=180)
    assert len(rows180) == 2, rows180


def test_flag_tiers_same_language(tmp_path):
    """flag 长窗值域 {2,-1,0}（口径备案：日桶无 qual 面——飞猪税垫/
    直挂约束在明细删净后不可重放，1=行情破线的 qual 语义不可达；
    lo≤th 全标 2=「当日最低可出手」概览语义）、擦边 -1、线外 0，
    与全站档位色同语言。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    # r1063 T262：四天全部相对今天算（写死 10-10…10-13 会随日期滑出 30 天窗口）
    _d = [(_dt.date.today() - _dt.timedelta(days=k)).isoformat()
          for k in (3, 2, 1, 0)]
    st.save_many([
        _fp("CZ1", 1800.0, fetched=_d[0] + " 08:00:00"),
        _fp("CZ2", 1850.0, fetched=_d[1] + " 08:00:00"),
        _fp("CZ3", 1980.0, fetched=_d[2] + " 08:00:00"),
        _fp("CZ4", 2500.0, fetched=_d[3] + " 08:00:00"),
    ])
    for d in _d:
        st.refresh_daily("SHA", "URC", "2026-11-01", day=d)
    rows = {b["day"]: b["flag"]
            for b in st.daily_series("SHA", "URC", "2026-11-01",
                                     days=30, th_d=1900.0)}
    assert rows[_d[0][5:]] == 2, rows     # lo=1800 ≤ th 可出手日
    assert rows[_d[1][5:]] == 2, rows     # lo=1850 ≤ th 同上（无 qual 面）
    assert rows[_d[2][5:]] == -1, rows    # 1980 ∈ (th, th*1.1] 擦边
    assert rows[_d[3][5:]] == 0, rows     # 线外


def test_direct_transfer_split_buckets(tmp_path):
    """直飞/中转分桶（extra.transCity 判中转）：双系列与短窗同构。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp("CZ1", 1500.0, transfer=False,
            fetched=_DAY + " 08:00:00"),
        _fp("CZ2", 1200.0, transfer=True,
            fetched=_DAY + " 09:00:00"),
    ])
    st.refresh_daily("SHA", "URC", "2026-11-01", day=_DAY)
    d = st.daily_series("SHA", "URC", "2026-11-01", days=30, kind="d")
    t = st.daily_series("SHA", "URC", "2026-11-01", days=30, kind="t")
    assert len(d) == 1 and d[0]["lo"] == 1500.0, d
    assert len(t) == 1 and t[0]["lo"] == 1200.0, t


def test_purge_keeps_daily_400d_selfclean(tmp_path):
    """purge 只删明细：聚合表保留；400 天外桶自清防膨胀。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([_fp("CZ1", 1500.0, fetched=_DAY + " 08:00:00")])
    st.refresh_daily("SHA", "URC", "2026-11-01", day=_DAY)
    st.purge(days=14)
    rows = st.daily_series("SHA", "URC", "2026-11-01", days=180)
    assert len(rows) == 1, "purge 误删聚合桶"
    c = sqlite3.connect(db)
    c.execute("INSERT OR REPLACE INTO price_daily VALUES "
              "(?,?,?,?,?,?,?,?,?,?,?,?)",
              ("SHA", "URC", "2026-11-01", "2020-01-01", 1,
               100.0, 100.0, 100.0, 100.0, 100.0, 0,
               "2020-01-01 00:00:00"))
    c.commit()
    c.close()
    st.daily_series("SHA", "URC", "2026-11-01", days=180)
    c2 = sqlite3.connect(db)
    n = c2.execute("SELECT COUNT(*) FROM price_daily WHERE "
                   "day < date('now','localtime','-400 days')").fetchone()[0]
    c2.close()
    assert n == 0, "400 天外桶未自清"


def test_refresh_daily_default_day_is_today(tmp_path):
    """day 缺省=今日（扫描轮尾无参调用形态）——不抛 NameError 且
    桶落在今日。"""
    import datetime as _dt
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([_fp("CZ1", 1500.0)])   # fetched_at=now
    today = _dt.date.today().strftime("%Y-%m-%d")
    st.refresh_daily("SHA", "URC", "2026-11-01")   # 无 day 参数
    rows = st.daily_series("SHA", "URC", "2026-11-01", days=30)
    assert rows and rows[-1]["day"] == today[5:].replace("-", "-"), rows


def test_trend_payload_shape_and_clamp(tmp_path, monkeypatch):
    """/api/trend 组装函数：days 白名单钳制（60→90 上取？否——钳到
    最近合法档 30）、缺参拒绝、双系列同构 pts（[MM-DD,lo,flag]）。"""
    import webui
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([_fp("CZ1", 1500.0, fetched=_DAY + " 08:00:00")])
    st.refresh_daily("SHA", "URC", "2026-11-01", day=_DAY)
    cfg = os.path.join(str(tmp_path), "c.yaml")
    open(cfg, "w", encoding="utf-8").write(
        f"output:\n  db_path: {db}\n")
    monkeypatch.setattr(webui._State, "config_path", cfg)
    # _trend_payload 优先读 _State.cfg；只设 config_path 在 xdist 文件顺序下
    # 会读到前一个用例留下的库，导致 direct=[] 假红（r952）。
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"db_path": db}})
    ok = webui._trend_payload(
        {"from": ["SHA"], "to": ["URC"], "date": ["2026-11-01"],
         "days": ["180"], "th": ["1900"]})
    assert ok["days"] == 180
    assert len(ok["direct"]) == 1, ok
    p = ok["direct"][0]
    # 1.5.275：航线级日桶含日历价，flag 恒 0，不冒充航班级真达标
    assert p[0] == _MD and p[1] == 1500.0 and p[2] == 0, p
    assert ok["transfer"] == [], ok
    # days 越界钳到最近合法档（白名单 {30,90,180}）
    cl = webui._trend_payload(
        {"from": ["SHA"], "to": ["URC"], "date": ["2026-11-01"],
         "days": ["7"], "th": ["1900"]})
    assert cl["days"] == 30, cl
    # 缺 from/to/date 拒绝
    bad = webui._trend_payload({"from": ["SHA"], "days": ["30"]})
    assert bad.get("ok") is False, bad


def test_frontend_long_range_pins():
    """源码钉：前后端档位同值律 / 五 chips / 懒加载换代令牌 /
    chart 长窗分支 / K线日桶 / routes_arr from/to 字段。"""
    src = webui_full_src()
    assert "const TREND_LONG={'30d':30,'90d':90,'180d':180};" in src
    assert "_TREND_DAYS = (30, 90, 180)" in src
    for i in ("rng30", "rng90", "rng180"):
        assert f'id="{i}"' in src, i
    assert "let _tlSeq=0;" in src and "if(seq!==_tlSeq)return;" in src
    assert "const BUCKET=_tl?1440:" in src
    assert "if(_tl&&!H0){" in src
    assert '"from": r["from"], "to": r["to"],' in src
    assert "loadTrend(u);   /* 长窗懒加载" in src




# ---- merged from tests/test_r329_intl_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r329_intl")
_TN = TuniuCrawler({}, _LOG)
_QC = QunarCrawler
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _row(**over):
    row = {
        "dCityName": "上海", "aCityName": "东京",
        "dPortName": "浦东国际机场", "aPortName": "成田国际机场",
        "dTerminal": "T1", "aTerminal": "T1",
        "dTime": "2026-11-16 09:30", "aTime": "2026-11-16 14:00",
        "airlineName": "东方航空", "flightNos": "MU523",
        "cabinName": "经济舱",
        "avgTotalPrice": 2380.0, "avgBasePrice": 1860.0, "avgTax": 520.0,
        "seat": 5, "totalMin": 270,
        "transferCity": "", "stopCity": "", "codeShare": "",
    }
    row.update(over)
    return row


def _parse(rows):
    return _TN._parse_offers_intl({"productList": rows})


def _qrow(**over):
    row = {
        "minPrice": 2380,
        "code": "MU523",
        "binfo": {
            "depTime": "09:30", "depDate": "2026-11-16",
            "arrTime": "14:00", "arrDate": "2026-11-16",
            "name": ["东方航空"], "stops": "0",
        },
    }
    row.update(over)
    return row


# ---- T1：tuniu cabinCode 段级订座码 ----

def test_t1_cabin_code_segment_letters():
    r = _parse([_row(cabinClass="W-W")])[0]
    assert r["cabinCode"] == "W-W"
    # 单段形态（3 直飞行值域）
    assert _parse([_row(cabinClass="Y")])[0]["cabinCode"] == "Y"
    # 三段连串
    assert _parse([_row(cabinClass="Q-Y-B")])[0]["cabinCode"] == "Q-Y-B"
    # 非订座码形态不落（宁缺勿错防脏词面）：int 旧样本形态/小写/空串
    assert "cabinCode" not in _parse([_row(cabinClass=1)])[0]
    assert "cabinCode" not in _parse([_row(cabinClass="w-w")])[0]
    assert "cabinCode" not in _parse([_row()])[0]


# ---- T2/T3：tuniu 机场 IATA 码（首末段）----

def test_t23_airport_codes_iata3_gate():
    r = _parse([_row(
        flightNos="MU523-NH960",
        segmentList=[
            {"flightNo": "MU523", "dPortIataCode": "PVG",
             "aPortIataCode": "KMG"},
            {"flightNo": "NH960", "dPortIataCode": "KMG",
             "aPortIataCode": "NRT"},
        ])])[0]
    assert r["depAirportCode"] == "PVG"
    assert r["arrAirportCode"] == "NRT"
    # iata3 门：小写/两位不落（H1 同律）
    bad = _parse([_row(segmentList=[
        {"flightNo": "MU523", "dPortIataCode": "pvg",
         "aPortIataCode": "PV"}])])[0]
    assert "depAirportCode" not in bad and "arrAirportCode" not in bad
    # 无段不落
    assert "depAirportCode" not in _parse([_row()])[0]
    assert "arrAirportCode" not in _parse([_row()])[0]


# ---- T4：tuniu shareAirline（中转各段承运）----

def test_t4_share_airline_transfer_only():
    r = _parse([_row(transferCity="昆明", flightNos="MU523-3U8881",
                     segmentList=[
                         {"flightNo": "MU523", "airComName": "东方航空"},
                         {"flightNo": "3U8881", "airComName": "四川航空"}])])[0]
    assert r["shareAirline"] == "东方航空|四川航空"
    # 共享行不落（共享信息由 shareCarrier 承载，防两键同屏混淆）
    r2 = _parse([_row(transferCity="开罗", codeShare="MS917",
                      segmentList=[
                          {"flightNo": "MU523",
                           "airComName": "东方航空"}])])[0]
    assert "shareAirline" not in r2
    assert r2["shareCarrier"] == "MS917"
    # 直飞行不落（单段无「各段承运」语义）
    assert "shareAirline" not in _parse([_row(segmentList=[
        {"flightNo": "MU523", "airComName": "东方航空"}])])[0]
    # 三段行 join；元素内部全角｜原样保留（航司集团多名内部标记，
    # 与段间半角分隔符有区分度）
    r3 = _parse([_row(transferCity="曼谷|马斯喀特",
                      flightNos="MU547-WY818-WY407",
                      segmentList=[
                          {"flightNo": "MU547",
                           "airComName": "东方航空"},
                          {"flightNo": "WY818",
                           "airComName": "新海航｜西部航空"},
                          {"flightNo": "WY407",
                           "airComName": "天津航空"}])])[0]
    assert r3["shareAirline"] == "东方航空|新海航｜西部航空|天津航空"


# ---- T5/T6：planeSize/plane 段级补全（首个非空段）----

def test_t56_planesize_plane_first_nonempty_seg():
    segs = [
        {"flightNo": "MU523", "craftWidthType": "", "craftTypeDetail": ""},
        {"flightNo": "MU777", "craftWidthType": "大型机",
         "craftTypeDetail": "空客A330-200"},
    ]
    r = _parse([_row(transferCity="昆明", flightNos="MU523-MU777",
                     segmentList=segs)])[0]
    assert r["planeSize"] == "大型机"
    assert r["plane"] == "空客A330-200"
    # seg0 有值优先（渠道原序，不倒挂）
    segs2 = [
        {"flightNo": "MU523", "craftWidthType": "中型机",
         "craftTypeDetail": "空客320"},
        {"flightNo": "MU777", "craftWidthType": "大型机",
         "craftTypeDetail": "空客A330"},
    ]
    r2 = _parse([_row(segmentList=segs2)])[0]
    assert r2["planeSize"] == "中型机"
    assert r2["plane"] == "空客320"
    # 全空不落（原行为不变）
    r3 = _parse([_row(segmentList=[
        {"flightNo": "MU523", "craftWidthType": ""}])])[0]
    assert "planeSize" not in r3
    assert "plane" not in r3


# ---- Q1：qunar intl stopover ----

def test_q1_stopover_flag():
    fl = _QC._extract_intl_flights([
        _qrow(binfo={"depTime": "09:30", "depDate": "2026-11-16",
                     "arrTime": "14:00", "arrDate": "2026-11-16",
                     "name": ["东方航空"], "stops": "1"})])
    assert fl[0].get("stopover") is True
    # intl 无 stopCitys 载体：城市不造值
    assert "stopCitys" not in fl[0]
    # stops!="1" 不落
    assert "stopover" not in _QC._extract_intl_flights([_qrow()])[0]
    # 全链：normalize stopover 真值短路（stopover 是 normalize/webui
    # 白名单层键；「stop」是 webui _user_state 组装键名，本层不断言）
    n = normalize(dict(fl[0]), "2026-11-16")
    assert n["stopover"] is True


# ---- Q2：qunar intl reducePriceDesc 词面白名单 ----

def test_q2_reduce_desc_whitelist():
    fl = _QC._extract_intl_flights([
        _qrow(reducePriceDesc="已减¥160"),
        _qrow(reducePriceDesc="成都两场互通"),
        _qrow(reducePriceDesc="立减¥100"),
        _qrow(reducePriceDesc="比直飞省¥50"),
        _qrow(),
    ])
    assert "已减¥160" in fl[0]["labels"]
    assert fl[1]["labels"] == "成都两场互通"
    # 变体与营销 churn 不采（全词精确门）
    assert "labels" not in fl[2]
    assert "labels" not in fl[3]
    assert "labels" not in fl[4]


# ---- 三端协议：webui 下行/消费面同轮钉（plane 数据孤儿收口）----

def test_webui_plane_passthrough_and_consumers():
    import webui
    mod = webui_full_src()
    # plane 透传（爬虫落键后下行字典同轮接，seatTilt 先例零布局通道）
    assert '"plane": (f.get("plane") or "").strip(),' in mod
    # CSV「机型体量」列并入机型名（v1559 机场码同列并入先例，不加新列；
    # r339 起二段体量/机型同列并入——列序 planeSize·planeSize2·plane）
    assert "[f.planeSize,f.planeSize2,f.plane].filter(Boolean).join('·')" in mod
    # 明细次行机型体量 span title 机型名注记（次行段容量红线 14 已满，
    # 词面不加只注 title）
    assert "机型'+he(f.plane)" in mod
    # 搜索 hay 含机型名（明细搜索可按机型过滤）
    assert "+(f.plane||'')" in mod


def test_webui_cabinof_intl_chain_absent_from_cabin_dim():
    """Soldier M-1：cabinOf 对段级订座码连串（W-W，r329 tuniu intl
    92/92 携带）不进舱系归一维度——映射即语义赌博（Q→公务/经济双值
    域在案）、逐串成 chip 是零区分度碎片噪音；空串由 chips 构造
    filter(Boolean) 排除、筛选门空值放行（缺维度行不被任何舱位档
    静默滤除——此前 intl 行无码归「经济」桶，连串亮相当日即从
    「经济」筛选静默消失=筛选回归面）。"""
    mod = webui_full_src()
    assert "if(c.indexOf('-')>=0)return '';" in mod
    # chips 构造排除空串（连串不成碎片 chip）
    assert "[...new Set(u.flights.map(cabinOf))].filter(Boolean)" in mod
    # 筛选门空值放行（连串行不被舱位档误滤）
    assert "FLT.cabins.size&&cabinOf(f)&&!FLT.cabins.has(cabinOf(f))" in mod


# ---- 冻结 dump 回放（skipif：debug/ 语料不入库，本地强化 CI 稳定）----


# ---- merged from tests/test_r380_soft_budget.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_soft_reject_is_its_own_kind():
    assert classify_failure(["soft_reject"], "") == "soft"
    assert classify_failure([], "HTTP 202 空体") == "soft"
    assert classify_failure([], "连接被 444 关闭") == "soft"
    # 真无票/解析失败仍是"不算拒绝"
    assert classify_failure(["empty"], "") == ""
    assert classify_failure(["error"], "解析失败") == ""


def test_soft_reject_does_not_trip_breaker_but_requests_warmup():
    p = Pacing({})
    kind, cd = p.observe("qunar", ["soft_reject"], "", retry_after=0)
    assert kind == "soft" and cd == 0
    ch = p.snapshot()["channels"]["qunar"]
    assert ch["state"] == "ok"          # 不冷却
    assert ch["strikes"] == 0           # 不计熔断次数
    assert ch["needs_warmup"] is True   # 但下一轮先预热
    a = advise("qunar", ch, {})
    assert a["state"] == "soft_reject"
    # 预热真的拿到风控 cookie 后才清标记
    p.note_warmup_ok("qunar")
    ch2 = p.snapshot()["channels"]["qunar"]
    assert ch2["needs_warmup"] is False
    assert ch2["reason"] == ""


def test_soft_reject_does_not_reset_needs_warmup_on_error_observe():
    p = Pacing({})
    p.observe("ctrip", ["soft_reject"], "")
    p.observe("ctrip", ["timeout"], "超时")     # 非拒绝类不应清标记
    assert p.snapshot()["channels"]["ctrip"]["needs_warmup"] is True


def test_budget_counts_sent_and_paced_per_channel():
    p = Pacing({})
    p.begin_round("10:00:00")
    p.note_plan("qunar", ("SHA", "PEK", "2027-06-01"), "fast", "x")
    p.note_sent("qunar")
    p.note_sent("qunar")
    p.note_paced("ctrip", "budget")
    p.note_plan("ctrip", ("SHA", "PEK", "2027-06-01"), "skip", "TTL")
    rnd = p.snapshot()["last_round"]
    assert rnd["sent"] == 2 and rnd["paced"] == 1
    assert rnd["sent_by"] == {"qunar": 2}
    assert rnd["paced_by"] == {"ctrip": 1}
    assert rnd["fast"] == 1 and rnd["skip"] == 1


def test_http_status_persisted_and_soft_bucketed(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5",
                       "soft_reject", rows=0, note="HTTP 202 空体",
                       attempt_id="a1", http_status=202)
    rows = st.recent_paths("qunar", 5)
    assert rows[0]["http_status"] == 202
    assert rows[0]["path_status"] == "soft_reject"
    node = st.path_stats(24)["qunar"]
    assert node["paths"]["H5"]["soft"] == 1
    assert node["paths"]["H5"]["empty"] == 0
    assert node["paths"]["H5"]["error"] == 0
    # 软拒不算成功，也不算硬失败
    assert node["query_attempts"] == 1 and node["query_ok"] == 0


def test_soft_reject_path_does_not_force_query_retry_flag():
    """软拒轮不应把查询塞进 failed 补采集合（下一轮靠预热自愈）。"""
    import inspect
    import main
    src = inspect.getsource(main.make_sweep_job)
    assert "_soft = any(x.get(\"status\") == \"soft_reject\" for x in paths)" in src
    assert "if pac is not None and not prices and not _soft:" in src


def test_panel_shows_budget_and_soft_reject_labels():
    import inspect
    import webui
    src = webui_full_src()
    for needle in ("软拒待预热", "实发 ", "主动未发", "近一分钟用量"):
        assert needle in src, needle


def test_soft_reject_forces_warmup_even_if_not_listed(tmp_path, monkeypatch):
    """软拒渠道即使不在 warmup_platforms 里，下一轮也必须先预热。"""
    import main as M
    # xdist 并行时别的测试会短暂写真实 user_data 的人工停手文件；
    # 本用例只验软拒→预热，隔离掉外部停手状态（否则整家被 blocked 跳过）。
    import core.policy as _pol
    monkeypatch.setattr(_pol, "read_halt", lambda *a, **k: {})
    monkeypatch.setattr(_pol, "read_halt_ex", lambda *a, **k: ({}, []))

    warmed = []

    class C:
        name = "ctrip"
        use_mobile = True
        warmup_url = "https://example.invalid/"
        last_busy = False
        retry_after_s = 0
        last_block_url = ""
        last_block_api = ""
        last_scene = {}
        session_max_days = 0
        paths = []

        def __init__(self, cfg, logger):
            self.logger = logger

        def warmup(self, headless=True):
            warmed.append(self.name)
            self.warmup_cookie_ok = True
            return True

        def safe_fetch(self, *a, **k):
            self.paths = [{"path": "H5", "status": "ok", "rows": 1,
                           "mobile": True}]
            from core.models import FlightPrice
            return [FlightPrice(platform=self.name, from_city="SHA",
                                to_city="PEK", depart_date="2027-06-01",
                                price=900.0)]

    monkeypatch.setitem(M.REGISTRY, "ctrip", C)
    cfg = {"users": [{"name": "u", "platforms": ["ctrip"],
                      "notifier": {}, "schedule": {},
                      "routes": [{"from": "SHA", "from_name": "上海",
                                  "to": "PEK", "to_name": "北京",
                                  "dates": ["2027-06-01"],
                                  "alert_direct": 900}]}],
           "schedule": {"scan_quiet_start": "", "scan_quiet_end": "",
                        "fast_ttl_min": 15, "slow_ttl_min": 120},
           "crawler": {"warmup": {"enabled": True,
                                  "platforms": ["qunar"]}},
           "output": {}, "web": {}}
    rt = {"users": M.build_users(cfg), "alerters": [], "cfg": cfg}
    job = M.make_sweep_job(cfg, rt, logging.getLogger("r380-warm"),
                           _Store(str(tmp_path / "p.db")), lambda *a, **k: {})
    rt["pacing"].observe("ctrip", ["soft_reject"], "")
    job()
    assert warmed == ["ctrip"], "软拒后必须先预热再查"
    assert rt["pacing"].snapshot()["channels"]["ctrip"]["needs_warmup"] is False


class _Store:
    def __init__(self, path):
        self.db_path = path
        self.paths = []
        self.saved = []

    def latest_prices(self, *a, **k):
        return []

    def path_stats(self, *a, **k):
        return {}

    def save_fetch_path(self, *a, **k):
        self.paths.append(a)
        return 1

    def save_many(self, rows):
        self.saved.extend(list(rows))

    def refresh_daily(self, *a, **k):
        pass

    def refresh_flight_daily(self, *a, **k):
        pass

    def purge(self, *a, **k):
        return 0



def test_shadow_path_preference_ranks_and_avoids():
    from core.pacing import shadow_path_preference
    paths = {
        "H5": {"attempts": 27, "rate": 0.07},
        "PC": {"attempts": 12, "rate": 0.92},
        "API": {"attempts": 3, "rate": 0.0},     # 样本不足不参与
        "日历": {"attempts": 13, "rate": 0.0},   # 日历不参与
    }
    out = shadow_path_preference(paths)
    assert [x[0] for x in out["prefer"]] == ["PC", "H5"]
    assert [x[0] for x in out["avoid"]] == ["H5"]
    assert all(x[0] != "API" for x in out["prefer"] + out["avoid"])
    assert all(x[0] != "日历" for x in out["prefer"] + out["avoid"])


def test_urgency_ttl_near_date_is_shorter():
    now = [1_700_000_000.0]
    cfg = {"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120,
                        "near_ratio": 0.15}}
    p = Pacing(cfg, clock=lambda: now[0])
    key = ("qunar", "SHA", "PEK", "2027-06-01")
    p.note_fetch("qunar", key, 900, True)          # 贴近阈值，快层
    now[0] += 16 * 60                              # 16 分钟
    # 远期：快层 30 分钟未到 -> skip；临期 3 天内：快层减半 15 -> fast
    assert p.plan_query("qunar", key, 900, days_ahead=40)[0] == "skip"
    assert p.plan_query("qunar", key, 900, days_ahead=2)[0] == "fast"


def test_urgency_ttl_far_date_slows_not_speeds():
    now = [1_700_000_000.0]
    cfg = {"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120,
                        "near_ratio": 0.15}}
    p = Pacing(cfg, clock=lambda: now[0])
    key = ("qunar", "SHA", "PEK", "2027-06-01")
    p.note_fetch("qunar", key, 9000, True)         # 远离阈值，慢层
    now[0] += 130 * 60
    assert p.plan_query("qunar", key, 2500, days_ahead=20)[0] == "slow"
    # 40 天后：慢层翻倍到 240，130 分钟仍应跳过
    assert p.plan_query("qunar", key, 2500, days_ahead=40)[0] == "skip"


def test_rate_excl_empty_does_not_punish_sold_out(tmp_path):
    """5 次全空是售罄，不是路径劣化。"""
    st = PriceStorage(str(tmp_path / "prices.db"))
    for i in range(5):
        st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5",
                           "empty", attempt_id="e%d" % i)
    node = st.path_stats(24)["qunar"]
    assert node["paths"]["H5"]["rate"] == 0.0
    # 分母全是售罄空 -> 没有有效样本，返回 None（不是 0% 失败）
    assert node["paths"]["H5"]["rate_excl_empty"] is None
    a = advise("qunar", {"state": "ok"}, node["paths"], node=node)
    # 全空不应落"路径劣化"（它不是拦截/超时，是售罄）
    assert a["state"] != "path_degraded"


def test_rate_excl_empty_keeps_real_failure_visible(tmp_path):
    st = PriceStorage(str(tmp_path / "prices.db"))
    st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5", "blocked",
                       attempt_id="b1")
    for i in range(4):
        st.save_fetch_path("qunar", "SHA", "PEK", "2027-06-01", "H5",
                           "empty", attempt_id="e%d" % i)
    node = st.path_stats(24)["qunar"]
    # 分母剔除 empty 后只剩 1 次 blocked -> 0%
    assert node["paths"]["H5"]["rate_excl_empty"] == 0.0
    a = advise("qunar", {"state": "ok"}, node["paths"], node=node)
    # 有效样本只有 1 次：不下"这条路径劣化"的结论（防 1 次抖动误杀），
    # 但渠道整体成功率仍低，必须如实报 degraded。
    assert a["state"] == "degraded"
    assert a["severity"] == "wait"


def test_probe_rows_are_persisted_with_evidence_level():
    import inspect
    import main
    src = inspect.getsource(main.make_sweep_job)
    assert 'evidence_level="probe"' in src
    assert 'attempt_id=_attempt' in src


def test_pacing_panel_refreshes_and_counts_down():
    import inspect
    import webui
    src = webui_full_src()
    assert "_paceStartAuto" in src and "setInterval" in src
    # 节流面板 2026-10-27 移入「监控 · 渠道健康」：轮询条件随之从
    # 「在配置页」改为「在监控页的健康 tab」，否则搬到新位置后不再刷新。
    assert "if(document.hidden||VIEW!=='mon'||MONTAB!=='health')" in src.replace("  if(document.hidden", "if(document.hidden")
    assert "已自动处理" in src          # 自动类建议不再被过滤
    assert "软拒" in src                # 路径提示可见软拒


def test_initial_round_snapshot_has_budget_fields():
    """进程刚起、还没跑第一轮时，前端读到的字段也必须齐。"""
    p = Pacing({})
    rnd = p.snapshot()["last_round"]
    for k in ("sent", "paced", "sent_by", "paced_by"):
        assert k in rnd, k
    assert rnd["sent"] == 0 and rnd["paced"] == 0


# ---- merged from tests/test_r506b_pending_rendered.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _payloads():
    paths, advice = {}, {}
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        paths[p] = {
            "paths": {"PC": {"attempts": 8, "ok": 7, "rate": 0.875}},
            "retired_paths": [],
            "scopes": {"dom": {"query_rate": 0.9, "query_attempts": 10},
                       "intl": {"query_rate": 0.5, "query_attempts": 10}},
            "query_attempts": 20, "query_ok": 14,
            "last_ok_at": "2026-10-29 03:00:00"}
        advice[p] = {"state": "ok", "action": "none", "severity": "ok",
                     "hint": "近 24h 正常", "eta_s": 0}
    pacing = {"ok": True, "quiet": {},
              "last_round": {"at": "2026-10-29 03:00:00", "sent": 4,
                             "paced": 1, "fast": 2, "slow": 1, "skip": 1,
                             "trips": []},
              "channels": {p: {"state": "ok", "needs_login": False,
                               "scene": {}, "advice": advice[p],
                               "health": {}} for p in advice},
              "cfg": {"warmup_platforms": ["qunar"],
                      "health_penalty_enabled": True},
              "coverage": {"sent": ["ctrip"], "ok": ["ctrip"], "ratio": 1.0},
              "recurrences": [], "effect": {},
              "iv_rate": {
                  "probe": {"n": 4, "healed": 3, "unhealed": 1,
                            "unjudged": 0, "rate": 0.75, "reliable": True},
                  "relogin": {"n": 0, "healed": 0, "unhealed": 0,
                              "unjudged": 92, "rate": None,
                              "reliable": False},
                  "reset": {"n": 1, "healed": 1, "unhealed": 0,
                            "unjudged": 0, "rate": 1.0, "reliable": False}}}
    return paths, pacing






# ---- merged from tests/test_v15116_enhance.py ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        import inspect
        _SRC = webui_full_src()
    return _SRC


# ---------------- EN-1 头部 chrome 税收敛 ----------------

def test_en1_hdmeta_full_row_le600():
    s = src()
    # ≤600 带：hdmeta 独占行（经典滚条内核 541-589 子带 .hdx 单行
    # min-content 顶破容器的病灶带覆盖，overlay 环境余量健康）
    assert '.hdmeta{flex-basis:100%' in s, "≤600 的 hdmeta 独占行声明缺失"
    # 收敛后：max-width:900 块不再有 basis:100%（hdmeta 并入 pill 行）
    i = s.find('@media(max-width:900px){\n  .hdx')
    assert i >= 0, "≤900 的 hdx 折行保底块缺失"
    block = s[i:s.find('}}', i) + 2]
    assert 'flex-basis:100%' not in block, \
        "≤900 块仍含 hdmeta 独占行——601-900 未收敛为两行"


# ---------------- EN-2 日历格保持纯展示（审计建议证伪后的收口钉） ----------------

def test_en2_calcell_pure_display():
    s = src()
    # 死通道保持收口（审计建议经真机证伪后维持）：日历格键=扫描观察
    # 日域（近 14 天），FLT.dates 过滤域=明细出发日域（未来出发窗），
    # 两域恒不相交——格级点击跳明细恒为空过滤；无动作元素不加
    # role=button（假 affordance）
    i = s.find("$('calgrid').innerHTML")
    assert i > 0, "renderCal 输出点缺失"
    cal_seg = s[max(0, i - 600):i]
    assert 'role="button"' not in cal_seg, "日历格不得挂 role=button（纯展示）"
    assert "function jumpCalDate" in s, "走势活通道 jumpCalDate 须保留"


# ---------------- EN-3 resetFlt 恢复默认排序 ----------------

def test_en3_resetflt_resets_sort():
    s = src()
    i = s.find('function resetFlt()')
    assert i >= 0
    body = s[i:s.find('}', s.find('saveUI()', i))]
    assert "SORT={k:'price',dir:1}" in body, "resetFlt 未复位 SORT"
    # 告知只在显式重置入口（跳转类调用方自带 toast，双条堆叠=冗余播报）
    j = s.find('function resetFltUI()')
    assert j >= 0, "缺显式重置入口 resetFltUI"
    ui_body = s[j:s.find('}', s.find('resetFlt()', j))]
    assert 'toast(' in ui_body, "resetFltUI 缺排序告知"
    assert 'onclick="resetFltUI()"' in s, "重置按钮未接 resetFltUI"
    assert '重置筛选与排序' in s, "按钮词面未同步排序副作用"


# ---------------- EN-5 541-760 吸顶 ----------------

def test_en5_montabs_sticky_541_760():
    s = src()
    assert '@media(min-width:541px) and (max-width:760px)' in s, \
        "541-760 专用块缺失"
    i = s.find('@media(min-width:541px) and (max-width:760px)')
    block = s[i:s.find('}', s.find('#montabs', i))]
    assert 'position:sticky' in block and 'top:var(--hdh' in block, \
        "541-760 带切换器未吸顶或未消费 --hdh"


# ---------------- EN-6 字号半步归并 ----------------

def test_en6_no_half_step_font_sizes():
    s = src()
    for half in ('font-size:11.5px', 'font-size:12.5px', 'font-size:13.5px'):
        assert half not in s, "字号半步残留：%s" % half


# ---------------- EN-7 K线态图例折行 ----------------

def test_en7_kline_ringnote_breaks_line():
    s = src()
    # 双段断言（同值守卫改写随迁）：旧形态「无条件内联赋值」禁复活；
    # 实效档=备忘式守卫写入在场 + K线分支折行 <br> 在场
    # （行为级由 test_r235/r244/r245 的 ringNote 内容钉兜底）
    assert "$('ringNote').innerHTML=CR.mode" not in s, \
        "ringNote 无条件内联赋值复活（同值守卫被拆）"
    i = s.find("_rh=CR.mode==='kline'")
    assert i >= 0, "ringNote 备忘式守卫缺席"
    seg = s[i:i + 900]
    assert '<br>' in seg, "K线态图例未折行（专有释义应第二行）"
    assert ("if(_ringWrote!==_rh+_tlSpan+_outNote){_rn.innerHTML=_rh+_tlSpan+_outNote;"
            "_ringWrote=_rh+_tlSpan+_outNote;}") in s, \
        "ringNote 同值守卫写入缺席（r323 长窗覆盖注 _tlSpan 同拍写入门）"


# ---------------- M-1 numlink 触控热区 ----------------

def test_m1_numlink_hit_area():
    s = src()
    assert 'a.numlink{color:inherit;text-decoration:none;position:relative}' in s, \
        "numlink 缺 relative 锚"
    assert 'a.numlink::after{content' in s, "numlink 缺 ::after 热区外扩"


# ---------------- M-2 焦点环清单 ----------------

def test_m2_text_link_focus_ring():
    s = src()
    for sel in ('a.vw:focus-visible', '.kpisum a:focus-visible',
                'a.numlink:focus-visible', '#foot a:focus-visible',
                '.demoBar a:focus-visible'):
        assert sel in s, "焦点环清单缺 %s" % sel


# ---------------- M-3 载荷级 stopTimeT 恒落键 ----------------

def test_m3_payload_stoptimet_anchor():
    s = src()
    assert s.count('"stopTimeT":') == 2, \
        "webui 载荷两端 stopTimeT 恒落键应各出现 1 次（共 2），防回流"


# ---------------- 锚点补偿全带动态单源 ----------------

def test_anchors_follow_hdh():
    s = src()
    # 深滚跳转落点补偿须消费 --hdh 贴 header 实高（固定像素在倒计时
    # 折行漂移下全带欠账）；固定 hdh+34 档已被三段式实效档按源码序
    # 接替（r262 退役，凡「≤760 补偿未动态化」以三段式在场为准）
    for fixed in ('scroll-padding-top:118px', 'scroll-padding-top:136px',
                  'scroll-padding-top:106px'):
        assert fixed not in s, "锚点补偿固定像素残留：%s" % fixed
    assert 'calc(var(--hdh,54px) + 34px)' in s, "≤900 锚点补偿未动态化"
    assert 'calc(var(--hdh,76px) + 34px)' not in s, \
        "≤760 hdh+34 固定系数档复活（三段式实效档覆盖下的死代码）"
    assert s.count('scroll-padding-top:calc(var(--hdh,134px)'
                   ' + var(--mtabsh) + var(--tabsh,0px) + 4px)') == 2, \
        "≤760/761+ 三段式动态补偿档缺失"


# ---------------- wE-EN1 推送总表图文件名去重 ----------------

def test_we_en1_table_png_route_dedup(tmp_path, monkeypatch):
    import core.alerter as al
    from core.alerter import Alerter
    import report

    captured = {}

    def fake_render(rows, title, out_path, **kw):
        captured['png'] = str(out_path)
        return str(out_path)

    def fake_upload(p, *a, **k):
        return 'https://img.test/' + str(p).replace('\\', '/').split('/')[-1]

    monkeypatch.setattr(report, 'render_flights_table', fake_render)
    monkeypatch.setattr(report, 'upload_chart', fake_upload)
    monkeypatch.setattr(report, 'upload_ghimg', fake_upload, raising=False)

    lg = logging.getLogger('t_v15116')
    a = Alerter(lg, storage=None)
    a.image_host = None

    def route(label='乌鲁木齐→上海'):
        return types.SimpleNamespace(
            label=label, from_code='URC', to_code='SHA',
            from_name='乌鲁木齐', to_name='上海',
            alert_direct=1900, alert_transfer=1700,
            transfer_arrival_max=None, transfer_layover_min=None)

    r = route()
    sec = lambda d: {"date": d, "top_direct": [], "top_transfer": []}
    # 生产「逐日期独立 entry」形态：同航线两个 entry（不同日期）
    rs_list = [(r, [sec('2026-10-05')]), (r, [sec('2026-10-06')])]
    a._flights_table_md_multi(rs_list, ops_notes=[])
    png = captured.get('png', '')
    assert png, "总表图未渲染"
    assert png.count('URCSHA') == 1, \
        "文件名航线段重复（同 OD 应去重保序）：%s" % png


# ---------------- M-4 cfgnav sticky 并入 --hdh 动态单源 ----------------

def test_m4_cfgnav_sticky_tracks_hdh():
    s = src()
    # sticky top 与 max-height 同 rule 双声明均消费 var(--hdh)：header
    # 实高变化（倒计时折行/密度切换）时配置页导航与监控页吸顶家族
    # 同源跟随；fallback 54+4=58 与 54+16=70 精确等值旧固定值
    # （JS 失效零退化）
    assert '.cfgnav{position:sticky;top:calc(var(--hdh,54px) + 4px)' in s, \
        "cfgnav sticky top 未并入 --hdh 动态单源"
    assert 'max-height:calc(100vh - var(--hdh,54px) - 16px)' in s, \
        "cfgnav max-height 未随 header 实高联动"
    assert 'top:58px' not in s, "固定 top:58px 残留（防回流）"


# ---------------- P1-1 空配置 × 非概览子栏自愈 + 守卫缺口 ----------------

def test_p11_empty_users_selfheal_overview():
    s = src()
    # render() 空分支切回概览（hero 教学卡在概览 pane 内，非概览子栏
    # 停留时删光用户曾被埋葬成空白死区，jpmontab 持久化使刷新也不自
    # 救）；silent 形态防入场动画与 hash 写副作用
    i = s.find('if(!s.users||!s.users.length){')
    assert i >= 0, "render 空分支缺失"
    seg = s[i:i + 400]
    assert "showMonTab('overview',true)" in seg, \
        "render 空分支未切回概览（hero 埋葬死区）"
    # chart()/table() 守卫对空数组收紧（[] 为真值放行 → curRoute 读
    # S.users[U] 的 routesArr 抛 TypeError pageerror）
    for fn in ('function table(){', 'function chart(){'):
        i = s.find(fn)
        assert i >= 0, "%s 缺失" % fn
        head = s[i:i + 80]
        assert '!S.users.length)return' in head, \
            "%s 守卫未收紧到 length（空数组放行崩溃）" % fn


# ---------------- P2-1 541-760 带明细跟页滚（吸顶可达结构前提） ----------------

def test_p21_band_541_760_tw_release():
    s = src()
    i = s.find('@media(min-width:541px) and (max-width:760px)')
    assert i >= 0, "541-760 专用块缺失"
    block = s[i:s.find('}}', i) + 2]
    assert '.tw{max-height:none}' in block, \
        "541-760 带未放开 .tw 内滚（montabs 吸顶触发点永超页面最大滚动=死代码）"
    # 内滚路径宽度族同步 540→760：.tw 侧监听门 / End 跳底 / 重建滚动
    # 位 / 抽屉拉升门四处 <=760 + window 侧续载门一处 >760（r241 起
    # 吸顶筛选条为 ≤760 全带形制，抽屉拉升门原「锚 ≤540 独有吸顶条」
    # 的例外前提消失，随族扩带）；r248 起明细空态指路随族 +1
    # （≤760「重置筛选」按钮在默认收起的筛选抽屉内，词面须给抽屉语境）
    assert s.count('window.innerWidth<=760') == 7, \
        "窄档宽度族门应恰 7 处消费 <=760（r349 配置收口 +1；健康格滚到最新 +1）"
    assert s.count('window.innerWidth>760') == 1, \
        "window 侧续载门应恰 1 处消费 >760"
    assert 'window.innerWidth>540)' not in s, \
        "window 侧续载门残留 540 键（541-760 续载死路）"
    assert 'window.innerWidth<=540' not in s, \
        "≤540 键应清零（抽屉拉升门已随族扩带，例外前提消失）"
    # 带内锚点补偿须含吸顶切换器高度（跳转落点不被 montabs 盖回）——
    # 设计意图由 ≤760 合并块尾三段式实效档承载（hdh+--mtabsh+--tabsh+4，
    # 源码序覆盖带内全部档）；旧固定 hdh+40px 注记档已退役（r262），
    # 固定档复活=死代码回归（被源码序覆盖，任何视口不可达）
    assert 'scroll-padding-top:calc(var(--hdh,76px) + 40px)' not in s, \
        "541-760 旧固定补偿档复活（死代码回归）"
    assert s.count('scroll-padding-top:calc(var(--hdh,134px) + var(--mtabsh)'
                   ' + var(--tabsh,0px) + 4px)') == 2, \
        "三段式实效补偿档（≤760/761+）缺失，吸顶三件补偿断链"


# ---------------- P2-2 触控三块 nav span 36px 地板 ----------------

def test_p22_nav_span_touch_floor():
    s = src()
    # 三个触控块（≥901 粗指针 / ≤900 粗指针 / ≤760 任意指针）同步：
    # nav span 仅 padding 增强时视高 ~35px 差 1px 触控地板；inline
    # 元素 min-height 不生效，须 flex 化垂直居中
    assert s.count('nav span{min-height:36px;display:inline-flex;'
                   'align-items:center}') == 3, \
        "触控三块 nav span 36px 地板应恰 3 处"


# ---------------- P2-3 demoBar 链接焦点环入全站清单 ----------------

def test_p23_demobar_focus_ring():
    s = src()
    assert '.demoBar a:focus-visible' in s, \
        "demoBar 下载链接未入全站 2px 蓝环清单（UA 默认 1px 黑脱队）"


# ---------------- 推送审校 P2-1/2/3 ----------------

def test_push_p21_png_plat_tag_tie():
    # PNG 总表图渠道列补「·同价×N」（文本版 plat_full 有、图版曾有
    # ——exact-tie 多渠道行在图主路径只显单渠道=比价信息丢失；
    # 词面与文本版逐字同语言；tie 段殿前、stale 段殿后（超宽截断
    # 只吃 stale 尾，N 计数恒保）
    from report import _plat_tag
    cn = {"tongcheng": "同程", "qunar": "去哪儿"}
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 3}, cn) == \
        "同程·同价×3"
    assert _plat_tag({"_platform": "qunar"}, cn) == "去哪儿"
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 2,
                      "_stale_h": 1.0}, cn) == "同程·同价×2·1h前"


def test_push_p22_storm_body_marker():
    # 风暴第 N 条正文首行带序号（钉钉聊天窗口不显示标题——重发标记
    # 只进标题=用户不可见，LESSONS 二.1/八.2 自家定律；词面与标题
    # _storm_title 逐字同语言）
    from core.alerter import _storm_desp, _storm_title
    d = _storm_desp(2, 3, "正文")
    assert d == "📞 达标提醒 2/3\n\n正文", "风暴正文首行缺序号标记"
    assert d.splitlines()[0] in _storm_title(2, 3, "T"), \
        "正文首行词面与标题不同语言"


def test_push_p23_digest_storm_gate():
    # 死路径 _push_digest 风暴触发与 multi 主路径同门：sent+hits+
    # fresh_hits 才连推、免打扰时段跳过（无门状态复活即持续达标轮
    # 15 分钟 3 连推的休眠隐患）
    import inspect
    import core.alerter as al
    body = inspect.getsource(al.Alerter._push_digest)
    assert "fresh_hits" in body, "_push_digest 无 fresh_hits 去抖"
    assert "_in_quiet" in body, "_push_digest 风暴无免打扰门"
    gate = "if sent and hits and fresh_hits and self.storm_repeat > 1:"
    assert inspect.getsource(al.Alerter).count(gate) == 2, \
        "风暴三重门应恰两处（multi 主路径+digest 死路径同形）"


# ---- merged from tests/test_v1559_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1559Pins:
    """webui.py 源码级钉死（同 test_v1558_webui.py 模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    @staticmethod
    def _page():
        import webui as _w
        return _w.PAGE

    # ---- .glcell 开关触控热区 ----------

    def test_glcell_switch_hotzone(self):
        """全局参数页 .glcell 内开关（启动即扫/无头/调试日志）本体
        36×20px 低于触控基准——coarse≤900 与 ≤760 两块触控补账各补
::before inset:-8px（.switch 基类自带 position:relative）。"""
        src = self._src()
        rule = ".glcell .switch::before{content:'';position:absolute;inset:-8px}"
        assert src.count(rule) == 3          # 三块触控媒体各一（≤760/≤900/901+），漏一即触控档撕裂
        base = ".srow .sctl .switch::before{content:'';position:absolute;inset:-8px}"
        assert src.count(base) == 3          # 既有 srow 补账不被挪用

    # ---- updFltN 漏计日期维 ----------

    def test_updfltn_counts_dates(self):
        """日历格跳转锁 FLT.dates 后移动端 #fltN 徽标须计数——
         插入位意图为 arr 与 pmin 之间， 起计数主体移入
        try 数据段且形态改全选豁免守卫（FLT.dates==日期全集=零筛选
        不计，与 plats/routes 同构， P2-B）。"""
        src = self._src()
        assert ("if(FLT.arr!=null)n++;\n"
                " if(FLT.pmin||FLT.pmax)n++;") in src
        assert "if(FLT.dates.size&&FLT.dates.size<ds.length)n++;" in src

    # ---- aria-modal 挂 dialog 元素 ----------

    def test_aria_modal_on_pvcard(self):
        """aria-modal 语义须与 role="dialog" 同元素（读屏按 role 定位
        dialog 取语义）——原挂 #pvMask 遮罩上读屏拿不到。静态随弹层卡
        落 HTML，运行时 setAttribute 入口清零。城市面板（citypanel）与
        推送预览（pvcard）两真弹层各自成对，aria-modal 计数==dialog 数。"""
        page = self._page()
        assert 'role="dialog" aria-modal="true"' in page
        # 每个 aria-modal 都以 role="dialog" 前缀成对（role 计数含
        # CSS 注释字面，不可作分母——LESSONS 十八§10 注释同被计数）
        n_am = page.count('aria-modal="true"')
        assert page.count('role="dialog" aria-modal="true"') == n_am, \
            "aria-modal 与 role=dialog 须逐元素成对"
        # 受控枚举：两真弹层（城市面板 + 推送预览）+ r342 重启中心
        # + r343 统一删除确认层 = 4；r340b 五平台校准册模态 +1 = 5；r348 检索通用弹层 +1 = 6；详情模态 +1 = 7
        # + 飞猪双端登录弹窗 +1 = 8。
        # 渠道入口（r1131）是桌面贴按钮展开的非模态抽屉（无遮罩/不锁页），
        # 必须留 aria-modal="false"，不得计入模态数——否则读屏会锁死背景。
        assert n_am == 8
        assert ('<aside class="srx-chdrawer" id="srxChLinksDrawer" '
                'role="dialog" aria-modal="false"') in page
        assert "_m.setAttribute('aria-modal'" not in self._src()

    # ---- brief 级孤儿键 date ----------

    def test_brief_orphan_date_removed(self):
        """_best_brief 的 "date" 须有真实消费点才许带：v1.5.110 起
        delta 按所属日期精确匹配 routes_arr（单航线多日期 route 为
        空串，label 匹配错配首日期序列）——date 有了 delta 消费点，
        从孤儿键转正；钉面从「不许带」改为「必须带且被 delta 消费」，
        防未来再退化为无消费孤儿键。行级白名单同名键合法保留
        （f.date 被筛选/CSV/行 title 多处消费）。"""
        src = self._src()
        m = re.search(r"def _best_brief\(f, pool=None\):(.*?)\n\n", src, re.S)
        assert m, "_best_brief 锚点丢失"
        body = m.group(1)
        assert '"date": (f.get("depDate") or "")}' in body
        assert '(bd_brief or {}).get("date")' in src
        assert '(xt_brief or {}).get("date")' in src
        assert '"stopTimeT": (f.get("stopTimeT") or "").strip(),' in src
        assert '"stopWin": (f.get("stopWin") or "").strip(),\n                "plat":' in src

    # ---- MAINT 死分支清退 ----------

    def test_maint_dead_branch_removed(self):
        """const MAINT={} 恒空无写入方，badge 首个 if 恒假——常量、
        注释与分支三处一并清退（渠道维护信号接入时再按需回补）。"""
        assert "MAINT" not in self._src()

    # ---- 死 CSS .stat2 ----------

    def test_stat2_dead_css_removed(self):
        """.uhead2 .stat2 零消费点（upill 才是现行徽标）——整条规则清退。"""
        assert "stat2" not in self._src()

    # ---- 新字段：白名单透传 ----------

    def test_whitelist_passthrough_codes(self):
        """depAirportCode/arrAirportCode 邻位插在 depAirport/arrAirport
        之后：IATA 恒 3 大写字母，strip+upper 直通不做 int 转写，空串
        不占位同邻键口径。"""
        src = self._src()
        for k in ("depAirportCode", "arrAirportCode"):
            assert f'"{k}": (f.get("{k}") or "").strip().upper(),' in src
        # 邻位：紧随 arrAirport、先于 planeSize
        assert (src.index('"arrAirport": (f.get("arrAirport") or "").strip(),')
                < src.index('"depAirportCode":')
                < src.index('"arrAirportCode":')
                < src.index('"planeSize":'))

    # ---- 新字段：_ttc 渲染门（node 实执行） ----------

    def test_ttc_gate_by_node_exec(self):
        """机场中文旁注：名含中文才注（qunar PC 源 depAirport 现状即
        三字码，城市码 SHA 与机场名双义冲突在案）、码与名义相同不重复
        注（防「SHA (SHA)」）、脏码/空码不注。抽 _apt/_tt/_HAN/_ttc 四段
        用 node 实执行（node --check 先例的执行版）。"""
        if shutil.which("node") is None:
            sys.exit("node 不在 PATH：无法完成 _ttc 实执行自验")
        page = self._page()
        a = page.index("function _apt(s)")
        b = page.index(":b;}") + len(":b;}")
        js = page[a:b]
        for frag in ("function _apt(s)", "function _tt(a,t)",
                     "const _HAN=", "function _ttc(a,t,c)"):
            assert frag in js, frag
        probe = js + """
const r=['上海虹桥|T2|SHA','乌鲁木齐国际机场|T3|URC','SHA||SHA','上海虹桥||SHA',
 '|T2|SHA','上海虹桥|T2|URCS','上海虹桥|T2|','上海虹桥|T2|sha'].map( s=>{const [a,t,c]=s.split('|');return _ttc(a,t,c);});
console.log(JSON.stringify(r));"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(probe)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True,
                               encoding="utf-8", timeout=60)
            assert r.returncode == 0, r.stderr[:400]
            got = json.loads(r.stdout)
        finally:
            os.unlink(path)
        assert got == ["上海虹桥T2 (SHA)",    # 中文名+楼号+码旁注（_apt 只剥「机场」后缀，虹桥不在剥除列）
                       "乌鲁木齐T3 (URC)",     # 「国际机场」后缀先剥再注
                       "SHA",                # 码与名义相同：不注（无中文名）
                       "上海虹桥 (SHA)",       # 无楼号只注码
                       "T2",                 # 机场名空：不注
                       "上海虹桥T2",           # 脏码（超 iata3）不注
                       "上海虹桥T2",           # 空码不注
                       "上海虹桥T2"]          # 小写码不注

    # ---- 新字段：CSV 并列不漂移 ----------

    def test_csv_airport_col_merged_not_new(self):
        """两码并入既有第 8 列「机场/航站楼」（_ttc 直出「虹桥T2 (SHA)→
        浦东T2 (PVG)」形），不加新列——列数锚随「退改」列增为 33
        （D-1 有意 +1）；「座椅倾斜」列再 +1 为 34（ctrip seattilt
        舱位物理参数，贴舱位码）；「儿童/婴儿」再 +1 为 35（tuniu
        child/infant 消费端补齐，表尾追加）；「准点率」再 +1 为 36
        （ctrip prate 决策字段，贴取消率）；「托运额」再 +1 为 37
        （ctrip pid 数字托运额，贴直挂）；「手提额」再 +1 为 38
        （ctrip pid 孪生家族，贴托运额）；裸 _tt 机场槽消费点清零
        （全部换 _ttc）。"""
        page = self._page()
        m = re.search(r"const head=\[(.*?)\];", page, re.S)
        assert m, "CSV 列头锚点丢失"
        # 列数锚（…r269 +往返推荐；r51 +税费列，贴价格；v295 +采集入口/
        # 证据级别，贴渠道 = 48）
        assert m.group(1).count(",") + 1 == 48
        assert "'机场/航站楼'" in m.group(1)             # 列名原位
        assert "_ttc(f.depAirport,f.depTerminal,f.depAirportCode)" in page
        assert "_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)" in page
        assert "_tt(f.depAirport,f.depTerminal)" not in page   # 旧裸 _tt 清零

    # ---- 新字段：搜索 hay ----------

    def test_search_hay_includes_codes(self):
        """filteredRows 搜索 hay 追加两码：搜索框可按「PVG/SHA」检索。"""
        page = self._page()
        assert ("' '+f.plat+' '+(f.depAirportCode||'')+' '"
                "+(f.arrAirportCode||'')") in page


# ----------：状态重建不持锁（SWR 不被钉死） ----------

class TestRebuildNoLockFreeze:
    """_build_state 重活（全历史 JSON 解析，生产实测 ~145s）移出锁外：
    异步重建进行中 _STATE_LOCK 必须可即时取得——持锁构建曾把 SWR 回旧值
    的请求整体钉死（每轮扫描后 /api/state 假死 ~2.4 分钟的根因）；
    发布段仍同锁原子落位（body/etag/gz 成对， 撕裂修复语义不变）。"""

    def setup_method(self):
        import webui as _wm
        self.w = _wm
        self._cache = dict(self.w._STATE_CACHE)
        self._building = dict(self.w._STATE_BUILDING)
        self.w._STATE_CACHE.update({"sig": None, "payload": None,
                                    "body": None, "etag": None, "gz": None})

    def teardown_method(self):
        self.w._STATE_CACHE.clear()
        self.w._STATE_CACHE.update(self._cache)
        self.w._STATE_BUILDING.clear()
        self.w._STATE_BUILDING.update(self._building)

    def test_async_build_does_not_hold_lock(self):
        """重建进行中（慢构建窗口）持锁读即时可入；完成后缓存整体换新。"""
        import time as _t
        w = self.w
        w._STATE_CACHE["sig"] = "old"
        w._STATE_CACHE["payload"] = {"v": "stale"}
        real_build = w._build_state

        def slow_build(sig):
            _t.sleep(0.8)               # 模拟 145s 级重活
            real_build(sig)

        orig_sig, orig_us = w._state_signature, w._user_state
        w._state_signature = lambda: "new"
        w._build_state = slow_build
        w._user_state = lambda u: {"k": "fresh"}
        st = w._State
        users_bak, cfg_bak = st.users, st.cfg
        st.users = [{"name": "u", "routes": [{"a": 1}]}]
        st.cfg = {"output": {"db_path": "data/nonexistent-probe.db"}}
        try:
            w._state_rebuild_async()
            _t.sleep(0.25)              # 进入构建中窗口
            t0 = _t.time()
            got = w._STATE_LOCK.acquire(timeout=1.5)
            held = _t.time() - t0
            if got:
                w._STATE_LOCK.release()
            assert got, "重建进行中锁被长期持有（SWR 钉死回归）"
            assert held < 1.2
            deadline = _t.time() + 8
            while _t.time() < deadline:
                if w._STATE_CACHE.get("sig") == "new":
                    break
                _t.sleep(0.1)
            assert w._STATE_CACHE.get("sig") == "new", "重建未完成"
            assert w._STATE_CACHE["payload"]["users"][0]["k"] == "fresh"
        finally:
            st.users, st.cfg = users_bak, cfg_bak
            w._state_signature = orig_sig
            w._user_state = orig_us
            w._build_state = real_build

    def test_swr_returns_stale_immediately(self):
        """有旧值时签名失效：请求即刻回旧值并触发后台重建（零等待）。

        后台线程必须在本测里被挡住：真实重建只要抢在 return 求值前
        发布，就会把“旧值”换成新 payload（CI 慢机实测假红）。这里
        分别钉「返回旧值」和「确实排了重建」，线程本身由上一个用例
        真跑覆盖。
        """
        import time as _t
        w = self.w
        w._STATE_CACHE["sig"] = "old"
        w._STATE_CACHE["payload"] = {"v": "stale"}
        orig_sig = w._state_signature
        orig_async = w._state_rebuild_async
        started = []
        w._state_signature = lambda: "new"
        w._state_rebuild_async = lambda: started.append(True)
        try:
            t0 = _t.time()
            out = w._latest_state()
            assert _t.time() - t0 < 0.5, "SWR 路径被重建阻塞"
            assert out == {"v": "stale"}
            assert started == [True], "SWR 路径没有触发后台重建"
        finally:
            w._state_signature = orig_sig
            w._state_rebuild_async = orig_async


class TestColdStartNoDeadlock:
    """冷启动（缓存全空）时 /api/state 必须能在构建完成后返回——首版
     修复把冷路径等待写在 _latest_state_snap 的锁区内，与构建
    线程发布段互等死锁（CI uitest 实锤：demo 首请求永挂）。"""

    def setup_method(self):
        import webui as _wm
        self.w = _wm
        self._cache = dict(self.w._STATE_CACHE)
        self._building = dict(self.w._STATE_BUILDING)
        self.w._STATE_CACHE.update({"sig": None, "payload": None,
                                    "body": None, "etag": None, "gz": None})
        self.w._STATE_BUILDING["on"] = False

    def teardown_method(self):
        self.w._STATE_CACHE.clear()
        self.w._STATE_CACHE.update(self._cache)
        self.w._STATE_BUILDING.clear()
        self.w._STATE_BUILDING.update(self._building)

    def test_cold_snap_returns_after_build(self):
        import time as _t
        import threading as _th
        w = self.w
        real_build = w._build_state

        def slow_build(sig):
            _t.sleep(0.5)
            real_build(sig)

        orig_sig, orig_us = w._state_signature, w._user_state
        w._state_signature = lambda: "cold-sig"
        w._build_state = slow_build
        w._user_state = lambda u: {"k": "cold"}
        st = w._State
        users_bak, cfg_bak = st.users, st.cfg
        st.users = [{"name": "u", "routes": [{"a": 1}]}]
        st.cfg = {"output": {"db_path": "data/nonexistent-probe.db"}}
        try:
            done = {}

            def ask():
                body, etag, gz = w._latest_state_snap()
                done["ok"] = body is not None

            th = _th.Thread(target=ask, daemon=True)
            th.start()
            th.join(timeout=15)
            assert done.get("ok"), "冷启动 /api/state 死锁（15s 未返回）"
        finally:
            st.users, st.cfg = users_bak, cfg_bak
            w._state_signature = orig_sig
            w._user_state = orig_us
            w._build_state = real_build


# ---- merged from tests/test_v193_statecache.py ----

def _w():
    import webui
    return webui


class _Sandbox:
    """把 _State.cfg 指向临时库，用完还原模块级缓存/旗标。"""

    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.td.name, "t.db")
        with open(self.db, "wb"):
            pass

    def __enter__(self):
        w = _w()
        self.w = w
        self.old_cfg = w._State.cfg
        self.old_ver = w._State.version
        self.saved = {k: w._STATE_CACHE[k] for k in w._STATE_CACHE}
        self.saved_once = w._STATE_DISK_ONCE["on"]
        w._State.cfg = {"output": {"db_path": self.db}}
        for k in w._STATE_CACHE:
            w._STATE_CACHE[k] = None
        w._STATE_DISK_ONCE["on"] = False
        return self

    def __exit__(self, *a):
        w = self.w
        w._State.cfg = self.old_cfg
        w._State.version = self.old_ver
        for k, v in self.saved.items():
            w._STATE_CACHE[k] = v
        w._STATE_DISK_ONCE["on"] = self.saved_once
        self.td.cleanup()


def _payload():
    return {"updated": "2026-09-24 19:00", "version": "1.7.0",
            "users": [{"name": "邓美銮", "flights": [{"price": 1980}]}]}


def _body(p):
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


class TestSourcePins:
    def _src(self):
        return open(_w().__file__, encoding="utf-8").read()

    def test_latest_state_restores_before_signature(self):
        """恢复必须先于签名比对：命中同签名时连重建都省掉。"""
        src = self._src()
        i0 = src.index("def _latest_state():")
        i1 = src.index("def _latest_state_snap():")
        seg = src[i0:i1]
        assert "_state_restore_once()" in seg, "_latest_state 未接磁盘快照恢复"
        assert seg.index("_state_restore_once()") < seg.index("_state_signature()"), \
            "恢复必须发生在签名计算之前"

    def test_build_state_persists(self):
        src = self._src()
        i0 = src.index("def _build_state(sig):")
        i1 = src.index("def _state_rebuild_async():")
        seg = src[i0:i1]
        assert "_state_persist(" in seg, "发布快照后未落盘"

    def test_persist_is_atomic(self):
        """单文件原子替换：避免 meta/body 两份文件撕裂。"""
        src = self._src()
        i0 = src.index("def _state_persist(")
        i1 = src.index("def _state_restore(", i0)
        seg = src[i0:i1]
        assert "os.replace(" in seg, "落盘未用原子替换"

    def test_restore_is_best_effort(self):
        """恢复路径必须整体 try 包裹：坏文件不得让控制台起不来。"""
        src = self._src()
        i0 = src.index("def _state_restore():")
        i1 = src.index("def _state_restore_once(", i0)
        seg = src[i0:i1]
        assert "except Exception" in seg, "恢复未做异常兜底"


class TestRoundTrip:
    def test_persist_then_restore(self):
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            gz = gzip.compress(body, 6)
            sig = (sb.db, 111, 222, 333, "1.7.0")
            w._state_persist(sig, body, '"e1"', gz)
            assert os.path.exists(w._state_cache_path()), "快照未落盘"

            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._state_restore()

            assert w._STATE_CACHE["payload"] == p
            assert w._STATE_CACHE["sig"] == sig, "签名须还原为可比较的 tuple"
            assert isinstance(w._STATE_CACHE["sig"], tuple)
            assert w._STATE_CACHE["etag"] == '"e1"'
            assert w._STATE_CACHE["body"] == body
            assert w._STATE_CACHE["gz"] == gz

    def test_restore_does_not_clobber_live_cache(self):
        """已有活缓存（本进程已构建）时恢复不得覆盖。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            w._state_persist((sb.db, 1, 2, 3, "v"), body, '"e"',
                             gzip.compress(body, 6))
            live = {"updated": "fresh"}
            w._STATE_CACHE["payload"] = live
            w._STATE_CACHE["sig"] = ("live",)
            w._state_restore()
            assert w._STATE_CACHE["payload"] == live
            assert w._STATE_CACHE["sig"] == ("live",)

    def test_corrupt_file_is_ignored(self):
        """垃圾内容 → 静默丢弃，缓存保持空（不抛、不半填充）。"""
        with _Sandbox() as sb:
            w = sb.w
            with open(w._state_cache_path(), "wb") as f:
                f.write(b"\x00garbage-not-a-snapshot")
            w._state_restore()
            assert w._STATE_CACHE["payload"] is None

    def test_missing_file_is_noop(self):
        with _Sandbox() as sb:
            sb.w._state_restore()
            assert sb.w._STATE_CACHE["payload"] is None

    def test_stale_snapshot_dropped(self):
        """超 TTL 的快照不恢复（避免展示数天前的价格）。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            meta = json.dumps({"sig": [sb.db, 1, 2, 3, "v"], "etag": '"e"',
                               "ts": time.time() - w._STATE_CACHE_TTL - 60},
                              ensure_ascii=False).encode("utf-8")
            gz = gzip.compress(body, 6)
            with open(w._state_cache_path(), "wb") as f:
                f.write(w._STATE_CACHE_MAGIC + len(meta).to_bytes(4, "big")
                        + meta + gz)
            w._state_restore()
            assert w._STATE_CACHE["payload"] is None, "过期快照应被丢弃"

    def test_version_mismatch_dropped(self):
        """跨版本快照结构可能已变 → 一律不认（升级后首请求慢一次）。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            w._State.version = "vA"
            w._state_persist((sb.db, 1, 2, 3, "vA"), body, '"e"',
                             gzip.compress(body, 6))
            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._State.version = "vB"
            w._state_restore()
            assert w._STATE_CACHE["payload"] is None, "跨版本快照应被丢弃"

    def test_same_version_restored(self):
        with _Sandbox() as sb:
            w = sb.w
            w._State.version = "vSame"
            p = _payload()
            body = _body(p)
            w._state_persist((sb.db, 1, 2, 3, "v"), body, '"e"',
                             gzip.compress(body, 6))
            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._state_restore()
            assert w._STATE_CACHE["payload"] == p

    def test_restore_once_flag(self):
        """_state_restore_once 只生效一次（热路径零重复 IO）。"""
        with _Sandbox() as sb:
            w = sb.w
            w._state_restore_once()
            assert w._STATE_DISK_ONCE["on"] is True
            # 第二次即使有盘上快照也不再读
            p = _payload()
            body = _body(p)
            w._state_persist((sb.db, 1, 2, 3, "v"), body, '"e"',
                             gzip.compress(body, 6))
            w._state_restore_once()
            assert w._STATE_CACHE["payload"] is None


class TestEtagIntegrity:
    def test_body_etag_gz_consistent(self):
        """恢复后三元组必须同一份快照（body 与 gz 解压结果一致）。"""
        with _Sandbox() as sb:
            w = sb.w
            p = _payload()
            body = _body(p)
            gz = gzip.compress(body, 6)
            w._state_persist((sb.db, 9, 8, 7, "v"), body, '"ez"', gz)
            for k in w._STATE_CACHE:
                w._STATE_CACHE[k] = None
            w._state_restore()
            assert gzip.decompress(w._STATE_CACHE["gz"]) == w._STATE_CACHE["body"]
            assert json.loads(w._STATE_CACHE["body"].decode("utf-8")) == p


# ---- merged from tests/test_v284_batch_probe.py ----

class _FakeCrawler:
    def __init__(self, cfg, logger):
        pass

    def fetch(self, fc, tc, dates):
        d = dates[0]
        items = [
            {"price": 100, "code": "XX123", "name": "测试航XX123",
             "depTime": "08:00", "arrTime": "10:00", "depDate": d,
             "cabin": "经济舱"},
            {"price": 120, "code": "XX456", "name": "测试航XX456",
             "depTime": "12:00", "arrTime": "14:00", "depDate": d,
             "cabin": "公务舱"},
        ]
        return [SimpleNamespace(price=100, airline="测试航", flight_no="XX123",
                                depart_time="08:00", arrive_time="10:00",
                                extra=json.dumps(items, ensure_ascii=False))]


class _PathFakeCrawler(_FakeCrawler, BaseCrawler):
    def fetch(self, fc, tc, dates):
        self.path_reset()
        self.path_note("PC", "empty", date=dates[0], detail="PC 无明细")
        self.path_note("H5", "login", date=dates[0], detail="会话门拒")
        self.path_note("API", "ok", rows=2, date=dates[0], detail="接口明细")
        return super().fetch(fc, tc, dates)


_D1 = (date.today() + timedelta(days=30)).isoformat()
_D2 = (date.today() + timedelta(days=31)).isoformat()
_D3 = (date.today() + timedelta(days=60)).isoformat()


@pytest.fixture()
def fake_plat():
    crawlers.REGISTRY["fake"] = _FakeCrawler
    webui._PROBE_LAST = 0
    old = getattr(webui._State, "cfg", None)
    webui._State.cfg = {"crawler": {}}
    try:
        yield "fake"
    finally:
        crawlers.REGISTRY.pop("fake", None)
        webui._State.cfg = old
        webui._PROBE_LAST = 0


def test_batch_probe_two_legs(fake_plat):
    j = webui._probe_search(None, None, None, [fake_plat], legs=[
        {"from": "上海", "to": "北京", "date": _D1},
        {"from": "上海", "to": "纽约", "date": _D3},
    ])
    assert j["ok"] and j.get("batch") is True
    assert len(j["legs"]) == 2
    assert [x["rows"] for x in j["legs"]] == [2, 2]
    assert all(x["status"] == "ok" for x in j["legs"])
    assert len(j["rows"]) == 4
    labels = {r["routeLabel"] for r in j["rows"]}
    assert labels == {"上海→北京", "上海→纽约"}
    assert {r["date"] for r in j["rows"]} == {_D1, _D3}
    assert all("leg" in r and r["flightKey"] for r in j["rows"])
    assert {r["leg"] for r in j["rows"]} == {0, 1}
    assert {r["cabin"] for r in j["rows"]} == {"经济舱", "公务舱"}
    assert {r["date"] for r in j["rows"] if r["leg"] == 0} == {_D1}
    assert len({r["rowKey"] for r in j["rows"]}) == 4


def test_batch_probe_rejects_over_limit_and_bad_leg(fake_plat):
    with pytest.raises(ValueError, match="最多 4 条"):
        webui._probe_search(None, None, None, [fake_plat], legs=[
            {"from": "上海", "to": "北京", "date": _D1}] * 5)
    webui._PROBE_LAST = 0
    with pytest.raises(ValueError, match="第 2 条"):
        webui._probe_search(None, None, None, [fake_plat], legs=[
            {"from": "上海", "to": "北京", "date": _D1},
            {"from": "上海", "to": "上海", "date": _D2},
        ])


def test_per_leg_channels_only_run_requested_leg():
    """失败重试逐腿渠道：每条腿只跑自己的失败渠道，不复制到全腿。"""
    calls_a, calls_b = [], []

    def _mk(label, sink):
        class _C:
            def __init__(self, cfg, logger):
                pass

            def fetch(self, fc, tc, dates):
                sink.append((fc, tc, dates[0]))
                return []
        return _C

    crawlers.REGISTRY["legacy_a"] = _mk("a", calls_a)
    crawlers.REGISTRY["legacy_b"] = _mk("b", calls_b)
    old = getattr(webui._State, "cfg", None)
    webui._State.cfg = {"crawler": {}}
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(
            None, None, None, ["legacy_a", "legacy_b"],
            legs=[{"from": "上海", "to": "北京", "date": _D1},
                  {"from": "上海", "to": "广州", "date": _D1}],
            leg_wants={0: ["legacy_a"], 1: ["legacy_b"]})
        assert calls_a == [("SHA", "BJS", _D1)]
        assert calls_b == [("SHA", "CAN", _D1)]
        assert j["legs"][0]["channels"].keys() == {"legacy_a"}
        assert j["legs"][1]["channels"].keys() == {"legacy_b"}
    finally:
        crawlers.REGISTRY.pop("legacy_a", None)
        crawlers.REGISTRY.pop("legacy_b", None)
        webui._State.cfg = old
        webui._PROBE_LAST = 0


def test_single_probe_response_keeps_legacy_shape(fake_plat):
    j = webui._probe_search("上海", "北京", _D1, [fake_plat])
    assert j["ok"] and "batch" not in j
    assert j["from"] == "SHA" and j["to"] == "BJS"
    assert j["date"] == _D1 and len(j["rows"]) == 2
    assert j["channels"][fake_plat]["status"] == "ok"


def test_probe_channel_paths_are_reported(fake_plat):
    crawlers.REGISTRY["pathfake"] = _PathFakeCrawler
    try:
        j = webui._probe_search("上海", "北京", _D1,
                                ["pathfake"])
        paths = j["channels"]["pathfake"]["paths"]
        assert [(x["path"], x["status"], x["rows"]) for x in paths] == [
            ("PC", "empty", 0), ("H5", "login", 0), ("API", "ok", 2)]
        assert paths[1]["detail"] == "会话门拒"
    finally:
        crawlers.REGISTRY.pop("pathfake", None)


def test_tuniu_pc_items_parse_real_shape():
    from crawlers.tuniu import TuniuCrawler
    items = [{
        "airline": "东航", "fn": "MU5195 32N", "dep": "18:00",
        "depAir": "浦东机场T1", "arr": "20:15", "arrAir": "大兴机场",
        "dur": "2h15m", "rate": "100%", "price": "经济舱¥405起",
        "cross": "20:15", "rowText": "东航 MU5195 18:00 20:15",
    }, {
        "airline": "国航", "fn": "CA8322 320", "dep": "06:55",
        "depAir": "浦东机场T2", "arr": "09:25", "arrAir": "大兴机场",
        "dur": "2h30m", "rate": "81%", "price": "经济舱¥500起",
        "cross": "09:25", "rowText": "国航 CA8322",
    }]
    rows = TuniuCrawler._parse_pc_items(items, "2026-10-24")
    assert len(rows) == 2
    assert rows[0]["code"] == "MU5195"
    assert rows[0]["price"] == 405.0
    assert rows[0]["depTime"] == "18:00" and rows[0]["arrTime"] == "20:15"
    assert rows[0]["depAirport"] == "浦东机场T1"
    assert rows[0]["cabin"] == "经济舱"
    assert rows[0]["source"] == "tuniu_pc"



def test_field_audit_cabin_uses_real_cabin_only():
    import pathlib
    src = webui_full_src()
    assert "{k:'cabin',label:'舱位',raw:['cabin','cabinName'],get:f=>f.cabin||''" in src
    assert "get:f=>f.cabinT||f.cabinCode" not in src
    assert "(_g0.cabinT||_g0.cabinCode?' · '+he(srxCabinClass(_g0)):'')" not in src


def test_batch_probe_ui_wiring():
    import pathlib
    src = webui_full_src()
    assert "function srxProbeAddLeg()" in src
    assert "function srxProbeRunBatch()" in src
    assert "function srxShownRows(rows)" in src
    assert "body:JSON.stringify(_p)" in src and "/api/probe/start" in src
    assert "if(o.retry)_p.retry=true" in src
    assert "if(SRX.probe&&SRX.probe.batch){" in src and "let a=srxAll();" in src
    assert "组合探针 · 未入库" in src
    assert "function srxTaskStart(payload,opts)" in src
    assert "srx-batchlist" in src
    assert "function srxTaskPaths(lg)" in src and "srx-tpaths" in src
    assert "人机验证" in src
    assert "max_workers=min(2" in src


def test_watch_identity_cannot_move_to_past_date():
    base = {"from": "SHA", "to": "BKK", "date": _D3,
            "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
            "channels": ["qunar"]}
    old = webui._watch_entry(dict(base))
    # 历史关注保留原日期时，仍可改渠道/目标做复盘
    webui._watch_entry(dict(old), old=old)
    with pytest.raises(ValueError, match="不能改到过去日期"):
        webui._watch_entry(dict(old, date="2020-01-01"), old=old)


def test_one_leg_batch_still_renders_as_batch(fake_plat):
    j = webui._probe_search(None, None, None, [fake_plat], legs=[
        {"from": "上海", "to": "北京", "date": _D1}])
    assert j.get("batch") is True and len(j["legs"]) == 1
    assert j["legs"][0]["rows"] == 2 and len(j["rows"]) == 2


class _ThinCrawler(_FakeCrawler):
    def fetch(self, fc, tc, dates):
        d = dates[0]
        it = {"price": 90, "code": "XX999", "name": "薄行航",
              "depTime": "06:00", "depDate": d}
        return [SimpleNamespace(price=90, airline="薄行航", flight_no="XX999",
                                depart_time="06:00", arrive_time="",
                                extra=json.dumps([it], ensure_ascii=False))]


def test_batch_missing_arrival_time_stays_calendar(fake_plat):
    crawlers.REGISTRY["thin"] = _ThinCrawler
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(None, None, None, ["thin"], legs=[
            {"from": "上海", "to": "北京", "date": _D1}])
        row = j["rows"][0]
        assert row["arrTime"] == ""
        assert row["isCal"] is True and row["qual"] is False
    finally:
        crawlers.REGISTRY.pop("thin", None)
        webui._PROBE_LAST = 0


class _OneLegOnlyCrawler(_FakeCrawler):
    def fetch(self, fc, tc, dates):
        if tc != "BJS":
            return []
        return super().fetch(fc, tc, dates)


def test_batch_merged_channel_ok_when_any_leg_has_rows(fake_plat):
    crawlers.REGISTRY["oneleg"] = _OneLegOnlyCrawler
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search(None, None, None, ["oneleg"], legs=[
            {"from": "上海", "to": "北京", "date": _D1},
            {"from": "上海", "to": "纽约", "date": _D3}])
        assert j["channels"]["oneleg"]["n"] == 2
        assert j["channels"]["oneleg"]["status"] == "ok"
        assert j["legs"][0]["channels"]["oneleg"]["status"] == "ok"
        assert j["legs"][1]["channels"]["oneleg"]["status"] == "empty"
    finally:
        crawlers.REGISTRY.pop("oneleg", None)
        webui._PROBE_LAST = 0


def test_batch_ensure_does_not_pin_single_pair_or_date():
    import pathlib
    src = webui_full_src()
    assert "if(SRX.probe&&SRX.probe.batch){" in src
    assert "组合结果默认跨腿/日期全量" in src


def test_probe_channels_follow_fixed_priority():
    names = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")
    old = {p: crawlers.REGISTRY.get(p) for p in names}
    for p in names:
        crawlers.REGISTRY[p] = _FakeCrawler
    webui._PROBE_LAST = 0
    try:
        j = webui._probe_search("上海", "北京", _D1,
                                list(reversed(names)))
        assert list(j["channels"]) == list(webui.PLATFORM_PRIORITY)
    finally:
        for p in names:
            if old[p] is None:
                crawlers.REGISTRY.pop(p, None)
            else:
                crawlers.REGISTRY[p] = old[p]
        webui._PROBE_LAST = 0


def test_probe_ui_priority_order_source():
    import pathlib
    import re
    src = webui_full_src()
    m = re.search(r"const SRX_PLAT_ORDER=\[([^\]]+)\];", src)
    assert m, "SRX_PLAT_ORDER 定义不在了"
    order = re.findall(r"'([a-z_]+)'", m.group(1))
    assert order[:5] == ["ctrip", "qunar", "fliggy", "tongcheng", "tuniu"], order
    assert set(order[5:]) == {"app_zhixing", "app_qunar", "app_fliggy",
                              "app_ctrip", "app_tongcheng"}, order
    assert 'aria-label="探针渠道（优先级：携程、去哪儿、飞猪、同程、途牛，随后是智行/去哪儿/飞猪/携程/同程 App；App 需勾选，走真机通道）"' in src
    # 顺序仍由 SRX_PLAT_ORDER 决定；但**渠道集合必须来自数据**——
    # 原来直接 filter 固定表，App 渠道的实时进度永远不会显示。
    assert "Object.keys(lg.channels||{})" in src and         "SRX_PLAT_ORDER.indexOf(a)" in src


def _mk_task(plans, want):
    import threading as _th
    legs = []
    for i, p in enumerate(plans):
        legs.append({"leg": i, "from": p["from"], "from_name": p["from_name"],
                     "to": p["to"], "to_name": p["to_name"], "date": p["date"],
                     "status": "queued", "rows": 0, "detail": 0, "cal": 0,
                     "channels": {q: {"status": "queued", "phase": "排队",
                                      "n": 0, "detail": 0, "cal": 0,
                                      "ms": 0, "err": ""} for q in want}})
    return {"id": "t1", "status": "running", "created": 0, "updated": 0,
            "started": 0, "finished": None, "plans": plans, "want": want,
            "total": len(plans) * len(want), "legs": legs, "rows": [],
            "rowkeys": set(), "events": [], "cancel": _th.Event(),
            "truncated": False, "err": ""}


def test_probe_task_records_real_channel_phases(fake_plat):
    plan = webui._probe_leg_plan("上海", "北京", _D1)
    task = _mk_task([plan], [fake_plat])
    webui._PROBE_LAST = 0
    j = webui._probe_search(None, None, None, [fake_plat],
                            legs=[{"from": "上海", "to": "北京",
                                   "date": _D1}], task=task)
    assert j["ok"] and task["legs"][0]["channels"][fake_plat]["status"] == "ok"
    assert len(task["rows"]) == 2 and task["legs"][0]["rows"] == 2
    phases = {e["phase"] for e in task["events"]}
    assert {"排队", "请求渠道", "解析明细", "解析完成", "渠道结束"} <= phases
    v = webui._probe_task_view("t1")
    # _probe_task_view reads registry; register for this assertion
    if v is None:
        webui._PROBE_TASKS["t1"] = task
        v = webui._probe_task_view("t1")
        webui._PROBE_TASKS.pop("t1", None)
    assert v["done"] == 1 and v["detail"] == 2 and v["raw"] >= 0


def test_probe_task_cancel_before_start_is_cancelled(fake_plat):
    plan = webui._probe_leg_plan("上海", "北京", _D1)
    task = _mk_task([plan], [fake_plat])
    task["cancel"].set()
    webui._PROBE_TASKS["t1"] = task
    webui._PROBE_LAST = 0
    try:
        webui._probe_start_task("t1", None, None, None,
                                [{"from": "上海", "to": "北京",
                                  "date": _D1}], [fake_plat])
        assert task["status"] == "cancelled" and task["rows"] == []
    finally:
        webui._PROBE_TASKS.pop("t1", None)
        webui._PROBE_LAST = 0


def test_neutral_state_and_task_ui_pins():
    import pathlib
    src = webui_full_src()
    assert "SRX.restoreChip" in src and "id=\"srxRestoreLink\"" in src and "恢复上次条件" in src
    assert "function srxTaskStart(payload,opts)" in src
    assert "function srxTaskCancel()" in src and "function srxTaskRetry()" in src
    assert "SRX_TASK_ROWS_SEEN" in src and "/api/probe/start" in src
    assert "本次渠道产物" in src and "仅日历" in src and "会话" in src
    assert "#searchview.srx-probe-on .srx-brief" in src
