# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1169_state7_and_dual_slots.py
- tests/test_r267_webui.py
- tests/test_r348_srx_workbench.py
- tests/test_r512_effect_scope_breakdown.py
- tests/test_r515_github_issues.py
- tests/test_r643_干预覆盖每个可见渠道.py
- tests/test_r671_writes_reject_cross_site.py
- tests/test_v15118_ctrip_labels.py
- tests/test_v15273_ui.py
- tests/test_v1553_webui.py
- tests/test_v162_webui.py
- tests/test_v169_webui.py
- tests/test_v178_webui.py
- tests/test_v180_webui.py
- tests/test_v182_webui.py
- tests/test_v191_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import base64
import io
import json
import logging
import os
import pytest
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webui

from core.channels import APP_CHANNELS, BROWSER_CHANNELS
from core.login_slots import LOGIN_SLOTS, LOGIN_SLOT_ORDER
from core.models import FlightPrice, Route
from core.storage import PriceStorage
from crawlers.ctrip import CtripCrawler
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer


# ---- merged from tests/test_r1169_state7_and_dual_slots.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


# ---------------- A. 状态单一真源 ----------------

def test_state7_is_exactly_seven_buckets():
    import webui
    tbl = getattr(webui, "SLOT_STATE7", None)
    assert tbl, "缺少 SLOT_STATE7（状态唯一真源）"
    codes = [k for k, _ in tbl]
    assert len(codes) == 7, "只允许 7 个语义档，实际 %r" % (codes,)
    assert len(set(codes)) == 7
    for k, cn in tbl:
        assert cn and cn.strip(), "档 %s 没有中文" % k


def test_every_known_status_maps_into_state7():
    import webui
    known = ["available", "page_ok", "saved", "pending", "saving", "active",
             "login_required", "challenge", "save_error", "missing"]
    codes = {k for k, _ in webui.SLOT_STATE7}
    for st in known:
        s7, cn = webui._slot_state7(st)
        assert s7 in codes, "%s 落到了枚举之外：%s" % (st, s7)
        assert cn and cn.strip(), "%s 没有中文" % st


def test_unknown_status_never_silently_blank():
    """负控：出现未登记的新词时，必须显式落到「待确认」，不许静默空白。"""
    import webui
    s7, cn = webui._slot_state7("some_new_word")
    assert s7 == "unknown", s7
    assert cn == "待确认", cn


def test_service_closed_slot_is_retired():
    import webui
    s7, cn = webui._slot_state7("saved", service_closed=True)
    assert s7 == "retired" and cn == "停服", (s7, cn)


def test_payload_carries_state7_and_cn():
    assert "_slot_state7(" in WEBUI, "槽位载荷没走统一派生函数"
    assert '"state_cn"' in WEBUI or "state_cn\"] = " in WEBUI, "槽位载荷没带 state_cn"
    assert '"slot_order": list(LOGIN_SLOT_ORDER)' in WEBUI, (
        "顺序没有随接口下发（前端只能再写一份）")


def test_frontend_prefers_backend_label():
    """前端必须优先用后端 state_cn，旧的三套表只做兜底。"""
    assert "s.state_cn" in WEBUI, "前端没有优先使用后端 state_cn"


# ---------------- B. 双端槽位 10 格 + 顺序单源 ----------------

def test_every_browser_channel_has_pc_and_h5():
    for plat in BROWSER_CHANNELS:
        assert plat in LOGIN_SLOTS, plat
        assert plat + "_h5" in LOGIN_SLOTS, "%s 缺 H5 槽位（D1 双端）" % plat
    assert len(LOGIN_SLOT_ORDER) == len(BROWSER_CHANNELS) * 2


def test_qunar_h5_exists_and_is_marked_closed():
    m = LOGIN_SLOTS["qunar_h5"]
    assert m["surface"] == "h5" and m["mobile"] is True
    assert m.get("service_closed") is True, "去哪儿已停服，H5 格必须是 retired 语义"
    assert m["profile"] != LOGIN_SLOTS["qunar"]["profile"], "两格不能共用 profile"
    assert "://m." in m["login_url"], "H5 槽位必须指向移动站"
    # 保住既有契约：requirement 仍是「必须登录」（test_goal_requirements 会查）
    assert m.get("requirement") == "必须登录"


def test_order_comes_from_backend_not_hardcoded():
    """负控：前端不许再硬编码整份槽位顺序表。"""
    assert "const order=['ctrip','ctrip_h5','qunar'" not in WEBUI, (
        "前端仍硬编码 9 项顺序表：后端加一格页面会静默少一格")
    assert "Object.keys(j.slots)" in WEBUI, "顺序没有从 /api/login-state 的 slots 派生"


def test_cards_derive_their_slot_list_from_backend():
    """卡片里的槽位列表也必须派生——写死就会漏格（实测 qunar_h5 少了一整行）。"""
    assert "function _slotsFor(" in WEBUI, "没有派生函数 _slotsFor"
    for v in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert "_slotsFor('%s')" % v in WEBUI, "%s 卡没有走派生" % v
    assert "slots:[by.qunar]" not in WEBUI, "去哪儿卡仍是写死单槽（漏 qunar_h5）"


def test_unsubscribed_app_is_labelled_not_missing():
    """没被订阅 ≠ 未登录（app_tongcheng 从来不在订阅里）。"""
    assert "'unsubscribed'" in WEBUI, "没有 unsubscribed 这一档"
    assert "未纳入采集" in WEBUI, "缺少给人看的「未纳入采集」文案"


# ---- merged from tests/test_r267_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _src():
    return webui_full_src()


# ---------- P2-1 后端：suspended 轻标记纯函数 ----------

def test_suspended_users_pure_function():
    fn = getattr(webui, "_suspended_users", None)
    assert fn is not None, "_suspended_users 纯函数缺失（P2-1 后端协议未落地）"
    # 全停用用户 → suspended 条目（name/n/routesTxt/dates 四键）
    runtime = [{"name": "张三", "routes": []}]
    cfg = [{"name": "张三", "routes": [
        {"from": "SHA", "from_name": "上海", "to": "URC", "to_name": "乌鲁木齐",
         "dates": ["2026-10-14"], "enabled": False},
        {"from": "URC", "from_name": "乌鲁木齐", "to": "SHA", "to_name": "上海",
         "dates": ["2026-10-15"], "enabled": False},
    ]}]
    got = fn(runtime, cfg)
    # 无 dates 键：前端零消费的死重（routesTxt 已含日期摘要，全量在配置页）；
    # 日期摘要走 _routes_txt 同源（MM-DD 短形，与在役卡同口径）
    assert got == [{"name": "张三", "n": 2,
                    "routesTxt": "上海→乌鲁木齐 10-14、乌鲁木齐→上海 10-15"}], got


def test_suspended_users_mixed_and_absent():
    fn = webui._suspended_users
    # 混合态：有启用航线的用户不进 suspended（runtime routes 非空）
    runtime = [{"name": "李四", "routes": [{"from_code": "SHA"}]}]
    cfg = [{"name": "李四", "routes": [
        {"from": "SHA", "from_name": "上海", "to": "SYX", "to_name": "三亚",
         "dates": ["2026-10-20"], "enabled": True},
        {"from": "SYX", "from_name": "三亚", "to": "SHA", "to_name": "上海",
         "dates": ["2026-10-21"], "enabled": False},
    ]}]
    assert fn(runtime, cfg) == [], "有启用航线的用户不得进 suspended"
    # cfg 无同名用户（demo 合成态）→ 恒 []
    assert fn([{"name": "demo用户", "routes": []}],
              [{"name": "张三", "routes": [{"enabled": False}]}]) == []
    # cfg 用户 raw routes 全空（真·从未配置）→ 不进
    assert fn([{"name": "张三", "routes": []}],
              [{"name": "张三", "routes": []}]) == []
    # 启用态矛盾（cfg 有启用但 runtime routes 空=热载窗口）→ 宁缺勿错不进
    assert fn([{"name": "张三", "routes": []}],
              [{"name": "张三", "routes": [
                  {"from": "SHA", "from_name": "上海", "to": "SYX",
                   "to_name": "三亚", "dates": ["2026-10-20"]}]}]) == []
    # 空入参形态
    assert fn([], []) == []
    assert fn(None, None) == []


def test_state_payload_carries_suspended():
    src = _src()
    # _build_state 输出面挂 suspended（键在 out 构造处）
    assert re.search(r'"suspended":\s*_suspended_users\(', src), \
        "/api/state 输出未挂 suspended 键"
    # st.cfg 单一事实源取原始 routes（热载安全——LESSONS 十二§1）
    # r621：`_cfg` 是 `st.cfg` 在 _build_state 里的局部别名（同一事实源），
    # 判据守的是「取自 cfg 而不是取自运行时 states」，不绑某一种写法。
    assert re.search(
        r'_suspended_users\(\s*users\s*,\s*(?:st\.cfg|_cfg)\.get\("users"\)',
        src), "suspended 取数未走 cfg 单一事实源"


def test_state_cache_invalidated_on_cfg_save():
    """suspended 是 cfg 派生键（签名五元组只含运行时 users 形态，全停
    态下改停用航线配置 users 序列化逐字节不变）——保存端点热重载后
    必须作废签名缓存，否则卡片 routesTxt/dates 陈旧到进程重启。"""
    src = _src()
    assert re.search(
        r'n = st\.reload_cb\(\) if st\.reload_cb else 0\n'
        r'(?:\s*#[^\n]*\n)*\s*_STATE_CACHE\["sig"\] = None', src), \
        "保存端点热重载后未作废 /api/state 签名缓存（cfg 派生键变更不可见）"


# ---------- P2-1 前端：空态二分词面 ----------

def test_empty_state_split_wording():
    src = _src()
    # 停用卡词面（二分新分支）
    assert "航线已全部停用" in src, "停用态空态词面缺失"
    assert "前往配置启用" in src, "停用态 CTA 词面缺失"
    # pill 词面二分
    assert "已全停用" in src, "pill 停用态词面缺失"
    # 教学卡（从未配置档）词面保留
    assert "还没有监控任务" in src, "从未配置教学卡被误删"
    assert "前往配置 →" in src, "教学卡 CTA 被误删"
    # suspended 渲染走 he() 消毒（name/routesTxt 是配置自由文本）——
    # 窗口锁停用卡字面之后的新段（全文件 he(x.name) 有既有消费点，
    # 全局形态匹配会被既有代码满足成半恒真）
    i = src.index("航线已全部停用")
    seg = src[i:i + 900]
    assert re.search(r"he\([a-z]\.name\)", seg) and re.search(r"he\([a-z]\.routesTxt\)", seg), \
        "suspended 渲染段未过 he() 消毒"


# ---------- P2-2：真值门全族收紧 length ----------

def test_gate_family_length_pins():
    src = _src()
    # 12 处真值门收紧后零残留（精确串：users 后紧跟右括号=无 length）
    assert src.count("if(!S||!S.users)") == 0, \
        "真值门残留（JS 空数组真值放行→S.users[U] 读 undefined）：见 r267 P2-2"
    # length 门计数：12 处收紧 + table/chart 既有 2 处
    assert src.count("if(!S||!S.users.length)") == 14, \
        "length 门计数漂移：门族清单见 test 文档头"
    # jumpQual 空态守卫（pill 点击链首）
    jq = src[src.index("function jumpQual(){"):]
    jq = jq[:jq.index("gotoMonTab('details')")]
    assert "!S.users.length" in jq, "jumpQual 空态守卫缺失"
    assert "switchView('cfg')" in jq, "jumpQual 空态应引到配置页"
    # showMonTab 空态收敛 overview（键盘 5/深链瞬态空白 pane 前置收敛）
    smt = src[src.index("function showMonTab("):]
    smt = smt[:smt.index("MONTAB=t;")]
    assert re.search(r"!S\.users\.length&&t!=='overview'", smt), \
        "showMonTab 空态收敛守卫缺失"


def test_buildchips_empty_no_throw_by_node():
    """行为钉：users=[] 时 buildChips 早退不抛（修复前 u.platAge
    TypeError）。抽函数段 node 实执行（test_v1559 先例形态）。"""
    if shutil.which("node") is None:
        sys.exit("node 不在 PATH：无法完成门卫实执行自验")
    src = _src()
    a = src.index("function buildChips(){")
    b = src.index("function togChip(el){", a)  # buildChips 之后最近的函数锚
    js = src[a:b]
    assert "function buildChips(){" in js
    probe = js + """
const S={users:[]},U=0,FLT={plats:new Set(),_platsInit:false},
 chipsRefocus=()=>{},$=()=>({innerHTML:''});
buildChips();
console.log('OK no-throw, platsInit='+FLT._platsInit);"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(probe)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        assert r.returncode == 0, "users=[] 时 buildChips 抛错：\n" + (r.stderr or "")[:400]
        assert "OK no-throw" in (r.stdout or ""), r.stdout
    finally:
        os.unlink(path)


# ---------- P3-1/P3-2/P3-3 ----------

def test_hero_cta_block_level():
    src = _src()
    assert re.search(r"\.hero button\{display:block", src), \
        "空 hero CTA 块级化规则缺失（桌面档吊位）"


def test_opsccard_reclaimed_in_empty_state():
    src = _src()
    # 空态分支回收（立即扫描对零启用航线无作用面）
    assert "$('opscard').style.display='none'" in src, \
        "空态 opscard 回收缺失"
    # 数据态路径恢复（render 每拍重写，空态↔数据态双向自愈）
    assert "$('opscard').style.display=''" in src, \
        "数据态 opscard 恢复点缺失"


def test_pretax_wrapped_stack_compact():
    src = _src()
    # 折行徽标行紧凑化（折行规则已盖全部徽标——补的只是折行态行距）
    assert ":has(.pretax ~ .pretax) .pretax{display:block;margin-top:2px}}" in src, \
        "折行徽标紧凑化规则缺失或形态漂移"


# ---- merged from tests/test_r348_srx_workbench.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _db(tmp_path, name="srx.db"):
    p = str(tmp_path / name)
    st = PriceStorage(p)
    return p, st


def _save(st, platform, frm, to, date, price, extra):
    st.save(FlightPrice(platform, frm, to, date, price,
                        extra=json.dumps(extra, ensure_ascii=False)))


def test_row_key_stable_across_rounds_and_price(tmp_path):
    a = {"rowId": 7, "rawIdx": 2, "price": 880, "depTime": "09:55",
         "arrTime": "13:40", "code": "MU541", "platKey": "ctrip",
         "from": "SHA", "to": "BKK", "date": "2026-11-20"}
    b = dict(a, rowId=8, rawIdx=0, price=901)
    assert webui._srx_row_key(a) == webui._srx_row_key(b)
    assert webui._srx_raw_key(a) == "r7:2"
    assert webui._srx_raw_key(b) == "r8:0"
    stale = {"rowId": None, "rawIdx": None, "price": 900, "depTime": "10:00",
             "arrTime": "14:00", "code": "MU541", "platKey": "ctrip",
             "from": "SHA", "to": "BKK", "date": "2026-11-20",
             "isStale": True}
    assert webui._srx_row_key(stale) == webui._srx_row_key(dict(stale, price=999))
    assert webui._srx_raw_key(stale) == ""


def test_flight_key_excludes_calendar_and_normalizes_composite():
    cal = {"isCal": True, "code": "", "depTime": "", "arrTime": "",
           "date": "2026-11-20"}
    assert webui._srx_flight_key(cal) == ""
    a = {"code": "SC2168/G56507", "depTime": "23:05", "arrTime": "22:00",
         "date": "2027-01-29", "trans": "厦门", "cross": "", "stop": False}
    b = dict(a, code="G56507/SC2168")
    assert webui._srx_flight_key(a) == webui._srx_flight_key(b)
    assert webui._srx_flight_key(a) != webui._srx_flight_key(
        dict(a, depTime="23:06"))


def test_calendar_rows_are_not_qualified(tmp_path):
    dbp, st = _db(tmp_path)
    _save(st, "ctrip", "SHA", "BKK", "2026-11-20", 719,
          [{"price": 719, "name": "日历最低价", "depDate": "2026-11-20"}])
    route = Route("SHA", "上海", "BKK", "曼谷", ["2026-11-20"],
                  alert_direct=1000, alert_transfer=0)
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        stt = webui._user_state({"name": "srx", "routes": [route]})
    finally:
        webui._State.cfg = old
    f = stt["flights"][0]
    assert f["isCal"] is True and f["cal"] is True
    assert f["qual"] is False
    assert stt["hit"] is False
    assert stt["roundUpdated"]


def test_best_and_route_calendar_exclude_thin_calendar_rows(tmp_path):
    dbp, st = _db(tmp_path)
    date = "2026-11-20"
    _save(st, "ctrip", "SHA", "BKK", date, 719,
          [{"price": 719, "name": "日历最低价", "depDate": date}])
    _save(st, "tuniu", "SHA", "BKK", date, 762,
          [{"price": 762, "code": "MU541", "depTime": "09:55",
            "arrTime": "13:40", "depDate": date, "totalDuration": "4时45分"}])
    route = Route("SHA", "上海", "BKK", "曼谷", [date],
                  alert_direct=900, alert_transfer=0)
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        stt = webui._user_state({"name": "srx", "routes": [route]})
    finally:
        webui._State.cfg = old
    assert stt["best"]["direct"]["price"] == 762
    assert "日历" not in (stt["best"]["direct"].get("name") or "")
    assert stt["minsArr"] == [["途牛", 762]]
    cal = stt["routesArr"][0]["cal"]
    assert cal and all(p != 719 for _d, p, _tier in cal)


def test_srx_links_covers_browser_and_app_entries():
    dom = webui._srx_links("SHA", "HAK", "2027-01-29")
    assert dom["ok"] and len(dom["links"]) == 10
    browser = [x for x in dom["links"] if not x.get("app")]
    apps = [x for x in dom["links"] if x.get("app")]
    assert len(browser) == 5 and all(x["ok"] for x in browser), dom
    # App 渠道没有网页落地页：仍占一行并带 app 标记，前端如实说原因，
    # 不能因为「没 URL」就让它在渠道卡里整行消失。
    assert len(apps) == 5 and all(not x["url"] for x in apps), dom
    assert all("真机" in x["note"] for x in apps), dom
    intl = webui._srx_links("SHA", "BKK", "2026-11-20")
    by = {x["key"]: x for x in intl["links"]}
    # r390：途牛国际深链在任何会话下都停在「正在加载中」→ 宁缺
    assert by["tuniu"]["ok"] is False and by["tuniu"]["url"] == ""
    # r390 反证：同程国际深链在无痕会话 302 到登录页 → 维持"宁缺"
    assert by["tongcheng"]["ok"] is False, by["tongcheng"]
    assert by["tongcheng"]["url"] == ""
    # r390：去哪儿国际深链匿名超时/登录弹层 → 不出链
    assert by["qunar"]["ok"] is False
    assert by["ctrip"]["ok"] and by["fliggy"]["ok"]


def test_srx_health_raw_key_rates(tmp_path):
    dbp, st = _db(tmp_path)
    _save(st, "ctrip", "SHA", "BKK", "2026-11-20", 880,
          [{"price": 880, "tax": 135, "depTime": "09:55",
            "arrTime": "13:40", "totalDuration": "4时45分"},
           {"price": 901, "tax": 135, "depTime": "18:10",
            "arrTime": "22:20"}])
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        j = webui._srx_health("SHA", "BKK", "2026-11-20")
    finally:
        webui._State.cfg = old
    ct = next(x for x in j["channels"] if x["key"] == "ctrip")
    assert j["measure"] == "raw_key_rate"
    assert ct["rows"] == 2
    assert ct["fields"]["price"] == {"n": 2, "total": 2, "rate": 100}
    assert ct["fields"]["cabin"]["n"] == 0
    assert ct["capturedAt"]


def test_srx_calendar_axes_are_distinct(tmp_path):
    dbp, st = _db(tmp_path)
    _save(st, "ctrip", "SHA", "BKK", "2026-11-16", 700,
          [{"price": 700, "code": "MU541", "depTime": "09:55",
            "arrTime": "13:40", "depDate": "2026-11-16"}])
    _save(st, "ctrip", "SHA", "BKK", "2026-11-17", 720,
          [{"price": 720, "code": "MU541", "depTime": "09:55",
            "arrTime": "13:40", "depDate": "2026-11-17"}])
    old = webui._State.cfg
    webui._State.cfg = {"output": {"db_path": dbp}}
    try:
        j = webui._srx_calendar("SHA", "BKK", "2026-11-16", 14)
    finally:
        webui._State.cfg = old
    assert j["ok"]
    assert [x["date"] for x in j["departure"]] == ["2026-11-16", "2026-11-17"]
    assert "两轴" in j["note"] or "不可互换" in j["note"]
    assert all("-" in x["date"] and len(x["date"]) == 5 for x in j["observation"])


def test_search_page_single_implementation_and_capability_markers():
    src = webui.PAGE
    for name in ("renderSearch", "srxSelect", "srxSwitchUser", "srxDetailHTML",
                 "srxFetchRaw", "srxRawBoxHTML", "srxAll", "srxChAge",
                 "srxPairName", "srxPayload"):
        assert src.count("function %s(" % name) == 1, name
    for needle in ("srxBandDays", "srxBrief", "srxFacets", "srxMobilebar",
                   "srxViewBtn", "srxGallery", "SRX_HEALTH", "srx-health", "srxStateBox",
                   "srxSessions", "srxCompareHTML", "srxMatrixHTML",
                   "srxFieldTabHTML", "srxSavebar", "srxExportEvidence",
                   "非原站截图", "未供", "未采", "探针未评估"):
        assert needle in src, needle
    # 价差拼接必须加括号：裸 `'+Math.max(...)-mn` 会把整串转数字得 NaN
    assert "Math.max(...g.map(x=>Number(x.price)||0))-mn" in src
    assert "Math.max(...g.map(x=>x.price))-mn+' 元" not in src


# ---- merged from tests/test_r512_effect_scope_breakdown.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_INTL = ("BKK", "CAN")     # 国际（曼谷→广州）
_DOM = ("PEK", "SHA")      # 国内（北京→上海）


def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _at(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at, route):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'%s',?,?,'2026-11-05','H5',?)" % plat,
            (at, route[0], route[1], status))


def test_scope_effect_exposes_the_domain_the_intervention_targeted():
    """国内全好、国际全挂：渠道级看不出问题，国际域必须看得出来。"""
    ps = _ps()
    ps.save_intervention("qunar", "probe", ok=True, scope="intl", at=_at(120))
    # 干预前：国内 4/4 好，国际 0/4 好 → 渠道级 50%
    _row(ps, "qunar", "ok", _at(300), _DOM)
    _row(ps, "qunar", "ok", _at(290), _DOM)
    _row(ps, "qunar", "ok", _at(280), _DOM)
    _row(ps, "qunar", "ok", _at(270), _DOM)
    for m in (180, 170, 160, 150):
        _row(ps, "qunar", "login", _at(m), _INTL)
    # 干预后：国内仍 4/4，国际仍 0/4 → 渠道级还是 50%
    _row(ps, "qunar", "ok", _at(100), _DOM)
    _row(ps, "qunar", "ok", _at(90), _DOM)
    _row(ps, "qunar", "ok", _at(80), _DOM)
    _row(ps, "qunar", "ok", _at(70), _DOM)
    for m in (60, 50, 40, 30):
        _row(ps, "qunar", "login", _at(m), _INTL)

    e = ps.intervention_effect("qunar", 24)
    assert e["has"] is True, e
    assert e["scope"] == "intl", e
    # 渠道级：前后都是 50% —— 看不出「国际一次都没救回来」
    assert round(e["before"], 2) == 0.5 and round(e["after"], 2) == 0.5, e
    # 分域：国际 0% → 0%，这才说得出真相
    assert e["scope_before"] == 0.0 and e["scope_before_n"] == 4, e
    assert e["scope_after"] == 0.0 and e["scope_after_n"] == 4, e


def test_dom_scope_ignores_intl_samples():
    """dom 干预时只看国内样本——国际的坏数据不能拖低国内读数。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, scope="dom", at=_at(120))
    _row(ps, "ctrip", "ok", _at(300), _DOM)
    _row(ps, "ctrip", "login", _at(120 + 40), _INTL)   # 干预前国际失败
    _row(ps, "ctrip", "ok", _at(100), _DOM)
    _row(ps, "ctrip", "login", _at(40), _INTL)         # 干预后国际也失败
    e = ps.intervention_effect("ctrip", 24)
    assert e["scope"] == "dom", e
    assert e["scope_before"] == 1.0 and e["scope_before_n"] == 1, e
    assert e["scope_after"] == 1.0 and e["scope_after_n"] == 1, e


def test_non_domain_scope_returns_no_scope_effect():
    """relogin 的 scope 是槽位名，不是域——不得硬套分域字段。"""
    ps = _ps()
    ps.save_intervention("fliggy", "relogin", ok=True,
                         scope="fliggy_h5", at=_at(60))
    _row(ps, "fliggy", "ok", _at(120), _DOM)
    _row(ps, "fliggy", "ok", _at(30), _DOM)
    e = ps.intervention_effect("fliggy", 24)
    assert e["has"] is True, e
    assert "scope_before" not in e and "scope_after" not in e, \
        "非域 scope 被硬套了分域字段：%r" % (e,)


def test_scope_effect_window_matches_the_channel_level_window():
    """分域窗口与渠道级同界：干预前超出 hours 的样本不得混进来。"""
    ps = _ps()
    ps.save_intervention("tuniu", "probe", ok=True, scope="intl", at=_at(60))
    _row(ps, "tuniu", "login", _at(60 + 30 * 60), _INTL)  # 30 小时前，窗外
    _row(ps, "tuniu", "login", _at(300), _INTL)           # 5 小时前，窗内
    _row(ps, "tuniu", "ok", _at(20), _INTL)
    e = ps.intervention_effect("tuniu", 24)
    assert e["scope_before_n"] == 1, \
        "分域前窗把窗外样本算进来了：%r" % (e,)
    assert e["scope_after_n"] == 1, e


def test_panels_render_the_scope_effect():
    """两处追溯面板都要把分域读数渲染出来（不只在节流面板）。"""
    import io
    w = webui_full_src()
    assert "eff.scope_before" in w, "节流面板没有渲染分域前后"
    assert "本次干预针对" in w, "退出检查面板没有渲染分域前后"
    # 渠道级那一行必须仍在（分域是附注，不是替换）：
    # 节流面板 `<span class="k">干预后对比</span>`、退出检查面板
    # 「干预后对比：」。两处都必须在场。
    assert w.count("干预后对比") >= 2, "渠道级成效行被分域替换掉了"




# ---- merged from tests/test_r515_github_issues.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


def test_reverse_proxy_port_save_does_not_hijack_the_browser():
    """#9：反代场景保存配置，不得把地址栏改到用户没访问过的端口。"""
    w = webui_full_src()
    i = w.index("端口跳转（GitHub #9）")
    seg = w[i:i + 900]
    # 判据必须是「保存前后端口值不同」，而不是「配置值 ≠ 浏览器端口」
    assert "_portBefore" in seg, "没有记录保存前的端口"
    assert "String(_portBefore)===oldPort" in seg, \
        "跳转前没有确认「浏览器当前就在旧端口上」"
    assert "GLB.port||8765)!==oldPort" not in seg, \
        "仍在用「配置值 ≠ 浏览器端口」当跳转判据（反代会恒成立）"


def test_port_before_is_captured_before_the_save_request():
    """#9：`_portBefore` 必须在 fetch 之前取值，否则回读已覆盖它。"""
    w = webui_full_src()
    i = w.index("const _portBefore=")
    j = w.index("fetch('/api/config'", i - 800)
    assert i < j, "`_portBefore` 取值晚于保存请求（回读会把它改掉）"




def test_login_without_gui_returns_an_actionable_error():
    """#10：没有图形环境时必须同步报错，而不是先提示「窗口已弹出」。"""
    w = webui_full_src()
    i = w.index("def _start_login(")
    seg = w[i:i + 4200]
    assert "_no_gui" in seg, "没有图形环境预检"
    assert "DISPLAY" in seg and "WAYLAND_DISPLAY" in seg, \
        "没有检查 DISPLAY/WAYLAND_DISPLAY"
    assert '"kind": "no_gui"' in seg, \
        "没有把「无图形环境」作为可区分的错误类型返回"
    # 必须在起线程之前返回：先起线程再报错等于没修。
    # 锚 `def _run()` 而不是 `threading.Thread`——同一函数里线程名也含该串。
    assert seg.index("_no_gui") < seg.index("def _run():"), \
        "预检晚于起线程（用户仍会先看到「已弹出」）"


def test_frontend_says_why_login_cannot_open():
    """#10：前端对 no_gui 要给出可执行指引，且不被 80 字截断。"""
    w = webui_full_src()
    assert "j.kind==='no_gui'" in w, "前端没有区分 no_gui"
    i = w.index("j.kind==='no_gui'")
    seg = w[i:i + 420]
    assert "图形界面" in seg, "没有说明「没有图形界面」"
    assert "user_data" in seg, "没有给出可执行的替代方案"


def test_compose_image_is_actually_published_by_a_workflow():
    """#8：compose 里写了 ghcr 镜像，工作流就必须真的能把它推上去。

    旧判据只防「注释里暗示存在镜像」；r674 起发行轮真推镜像，判据改成
    正向对账：镜像仓库路径、推送步骤、public 可见性提醒缺一不可——
    否则用户照 compose 拉取又会得到 denied（GitHub 对「不存在/无权限」
    返回同一回执，看不出差别）。
    """
    y = _read("docker-compose.yml")
    assert "build: ." in y, "没有本地构建兜底（无镜像/CI 失败时起不来）"
    assert "image: ghcr.io/dengmeiluan/ticket-monitoring:latest" in y, \
        "compose 没有指向工作流实际推送的镜像路径"
    w = _read(".github/workflows/release-build.yml")
    assert "push_image" in w, "工作流没有推送开关（issue #8 的诉求）"
    assert "packages: write" in w, "没有 packages 权限，推 ghcr 会 403"
    assert "docker push" in w, "没有真正的推送步骤"
    assert "ghcr.io/${{ github.repository }}" in w, \
        "推送路径与 compose 不是同源（仓库改名后会各写各的）"
    assert w.index("docker push") > w.index("if: ${{ inputs.push_image }}"), \
        "推送没有挂在开关上——日常跑 CI 会往包仓库写东西"
    assert "public" in w.lower(), "没有提醒把 package 设为 public"


def test_startup_failure_is_readable_when_launched_by_double_click():
    """#11 同类：发行包双击运行时，启动失败不能一闪而过。"""
    m = _read("main.py")
    i = m.index('if __name__ == "__main__":')
    seg = m[i:i + 1400]
    assert "traceback.print_exc()" in seg, "启动异常没有打印堆栈"
    assert "启动失败" in seg, "没有可读的失败结论"
    assert "isatty" in seg, "没有在可交互终端里停住（窗口会一闪而过）"


# ---- merged from tests/test_r643_干预覆盖每个可见渠道.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# **从单一事实源取清单**（2026-11-06）：原来这里手抄了 6 家，加到 10 家
# （5 浏览器 + 5 App）后，控制台渲染 10 行而测试仍按 6 断言，直接失败。
# 抄一份清单就一定会漂，所以直接读注册表那两张常量。

ALL = list(BROWSER_CHANNELS) + list(APP_CHANNELS)
PACING = {
    "ok": True, "quiet": {}, "last_round": {"sent": 12, "paced": 5},
    "channels": {p: {"state": "ok",
                     "advice": {"state": "ok", "severity": "ok", "hint": ""}}
                 for p in ALL},
    "cfg": {"warmup_platforms": ["qunar", "fliggy"],
            "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {},
}
HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": {}, "diag": [], "coverage": {}}






# ---- merged from tests/test_r671_writes_reject_cross_site.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 只打这些：要么本身是只读语义的写接口，要么失败分支不会落盘
SAFE_PATHS = ("/api/app-login/state", "/api/restart")


def _server():
    import webui
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp(prefix="r671_")
    cfg = os.path.join(tmp, "c.yaml")
    # 用一份**临时**配置，绝不动仓库里的 config.example.yaml
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg)
    # 强制绑回环：测试进程只该监听本机。这个替换**必须**在夹具退出时还原——
    # 直接赋值会永久改掉模块属性，后续 test_r675 的「TM_WEB_HOST 生效」断言
    # 会读到这个替身而恒得 127.0.0.1（实测全量到该文件必红 4 条）。
    old_bind = webui._bind_host
    webui._bind_host = lambda c: "127.0.0.1"
    try:
        webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                        job=None, report_push=None, config_path=cfg)
    except Exception:
        webui._bind_host = old_bind
        raise
    return port, tmp, old_bind


def _post(base, path, headers, body=b"{}"):
    req = urllib.request.Request(base + path, method="POST", data=body,
                                 headers=headers)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=6)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERR:%s" % type(e).__name__


@pytest.fixture(scope="module")
def live():
    port, tmp, old_bind = _server()
    base = "http://127.0.0.1:%d" % port
    host = "127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(160):
        try:
            op.open(base + "/api/state", timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip("控制台未在期限内起来")
    yield base, host
    global_webui = sys.modules.get("webui")
    if global_webui is not None:
        global_webui._bind_host = old_bind
    shutil.rmtree(tmp, ignore_errors=True)


def test_cross_site_write_is_rejected(live):
    base, host = live
    for p in SAFE_PATHS:
        code = _post(base, p, {"Content-Type": "application/json",
                               "Origin": "http://evil.example",
                               "Host": host})
        assert code == 403, "%s 接受了跨站请求（%s）" % (p, code)


def test_same_origin_still_works(live):
    base, host = live
    code = _post(base, "/api/app-login/state",
                 {"Content-Type": "application/json",
                  "Origin": "http://" + host, "Host": host})
    assert code != 403, "同源请求被误挡（%s）" % code


def test_cli_without_origin_still_works(live):
    base, host = live
    code = _post(base, "/api/app-login/state",
                 {"Content-Type": "application/json", "Host": host})
    assert code != 403, "无 Origin 的脚本调用被误挡（%s）" % code


def test_non_json_body_is_rejected(live):
    base, host = live
    code = _post(base, "/api/app-login/state",
                 {"Content-Type": "text/plain", "Host": host}, body=b"x=1")
    assert code == 415, "非 JSON 请求体没被挡（%s）" % code


@pytest.mark.parametrize("path", ["/api/open-folder", "/api/test-toast"])
def test_bodyless_post_is_not_over_blocked(live, path):
    """无 body 的 POST 不能被 415 误伤（r671b 真实回归）。

    `fetch(path, {method:'POST'})` 不带 body 时，浏览器会自动补
    `Content-Type: text/plain`——按「非 JSON 一律 415」会把「打开文件夹 /
    测试弹窗 / 立即扫描 / 重启」这些无参按钮全部打哑。实测同源调用直接 415。
    无 body 本就没有可解析载荷，CSRF 拿它也只能触发幂等动作。
    """
    base, host = live
    same = _post(base, path,
                 {"Content-Type": "text/plain;charset=UTF-8",
                  "Origin": "http://" + host, "Host": host}, body=b"")
    assert same != 415, "%s 的无 body 同源请求被误判成非 JSON（%s）" % (path, same)
    cross = _post(base, path,
                  {"Content-Type": "text/plain;charset=UTF-8",
                   "Origin": "http://evil.example", "Host": host}, body=b"")
    assert cross == 403, "%s 的无 body 跨站请求没被挡（%s）" % (path, cross)


def test_restart_is_guarded(live):
    """最危险的一条：跨站能重启进程。"""
    base, host = live
    code = _post(base, "/api/restart",
                 {"Content-Type": "application/json",
                  "Origin": "http://evil.example", "Host": host})
    assert code == 403, "跨站请求能重启进程（%s）" % code


def test_guard_covers_every_write_endpoint_structurally():
    """闸门放在 _do_POST 开头：新增写接口自动继承，不靠逐个记得加。"""
    import io
    src = webui_full_src()
    i = src.index("def _do_POST(self):")
    # 新增会话重置/写分支会把 /api/config 推后；只钉相对顺序。
    j_demo = src.index('DEMO["on"]', i)
    j_guard = src.index("跨站请求已拒绝", i)
    j_cfg = src.index('"/api/config"', i)
    assert j_demo < j_guard < j_cfg, (
        "跨站闸门必须在演示短路之后、所有写分支之前")


def test_bodyless_post_is_never_rejected_by_content_type():
    """r672b：无 body 的 POST 不得因 Content-Type 被判 415（结构级兜底）。

    真实缺陷：`/api/app-login*`（5 个）、`/api/challenge/*`（3 个）、
    `/api/login`、`/api/login-finish`、`/api/login-verify`、
    `/api/channel/{probe,verify,warmup}`、`/api/pacing/reset`、
    `/api/special-radar`、`/api/srx/watch`、`/api/probe/start` 共 13 个
    端点各自重复写了一模一样的一段「不是 application/json 就 415」。
    `fetch(path,{method:'POST'})` 不带 body 时浏览器自动补
    `text/plain`——这些按钮全部被打哑，而 r672 的端点普查此前被
    `/api/restart` 的 `os._exit` 杀掉，一直没跑到（表是绿的）。

    判据：除统一 helper 外，正文里不得再出现逐分支的
    「Content-Type 必须为 application/json」+415 组合；且所有 415 出口
    都必须先看 Content-Length > 0。负控=把 helper 改回无条件 415 即红
    （r672 运行时普查同时红）。
    """
    import io
    src = webui_full_src()
    # 只允许两处：_json_body_ok 单源，以及 _post_json 里为了让「鸭子类型
    # 替身」能独立单测而内联的同一判据。逐分支再抄一份（13 个端点那种）
    # 就是缺陷回潮。
    occ = src.count('"Content-Type 必须为 application/json"')
    assert occ == 2, (
        "JSON Content-Type 判据应只有 _json_body_ok 与 _post_json 两处"
        "（现 %d 处）——逐分支重复写会把「无 body 同源请求」打成 415" % occ)
    i = src.index("def _json_body_ok(self):")
    seg = src[i:src.index("def _post_json(", i)]
    # helper 必须「先看有没有 body」：Content-Length 的**读取**要出现在
    # 返回 415 的自绘调用之前（注释里也提到 Content-Length，故锚定代码本身）
    j_len = seg.index('get("Content-Length"')
    j_415 = seg.index("self._json(")
    assert j_len < j_415, "helper 必须先判 Content-Length 再谈 415"
    assert "application/json" in seg
    # _post_json 里的内联份同样必须先读 Content-Length
    j = src.index("def _post_json(self")
    seg2 = src[j:src.index("def _json_response", j)
              if "def _json_response" in src[j:] else j + 3000]
    assert seg2.index('get("Content-Length"') < seg2.index("415")


# ---- merged from tests/test_v15118_ctrip_labels.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15118")
_CT = CtripCrawler({}, _LOG)


def _b64zstd(obj) -> str:
    import zstandard
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(
        zstandard.ZstdCompressor().compress(raw)).decode()


def _seg(flgno="MU1234"):
    return {"basinfo": {"flgno": flgno},
            "dateinfo": {"ddate": "2026-10-05 08:30:00",
                         "adate": "2026-10-05 11:20:00"},
            "craftinfo": {"cdisname": "空客320(中)", "manuf": "空客",
                          "kind": 2}}


def _mk_item(show_price=None, min_tprice=1000.0, filt=None,
             flgno="MU1234", nt104_bad=False):
    """最小行：policyinfo 单政策（最低价 min_tprice）+ 可选 nt=105
    showPrice + 可选 nt=104 载荷（FILTED_PRICES=filt，nt104_bad 时
    notecnt 为坏 base64 验静默门）。"""
    notes = []
    if show_price is not None:
        notes.append({"notetype": 105, "notecnt": json.dumps(
            {"showPrice": show_price, "aggSalePrice": show_price,
             "policyId": "p1", "flags": []})})
    if nt104_bad:
        notes.append({"notetype": 104, "notecnt": "!!not-base64!!"})
    elif filt is not None:
        notes.append({"notetype": 104, "notecnt": _b64zstd({
            "items": {"priceInfoList": json.dumps(
                [{"price": min_tprice, "grade": 0, "limitTag": "",
                  "policyId": "p1"}]),
                "FILTED_PRICES": filt}})})
    return {"mutilstn": [_seg(flgno)],
            "notes": notes,
            "policyinfo": [{"quantity": 1, "tprice": min_tprice,
                            "drate": 5.0}]}


def _run(item, allilst=None, root_list=False):
    if root_list:
        resp = [item]
    else:
        resp = {"fltitem": [item]}
        if allilst is not None:
            resp["allilst"] = allilst
    rows = _CT._extract_ctrip_flights(json.dumps(resp, ensure_ascii=False))
    assert len(rows) == 1
    return rows[0]


# ---- nt=105 诱饵价透明标记 ----

def test_lure_price_fired():
    """showPrice 与最低 tprice 背离 2% 且 ∈ FILTED_PRICES → labels
    落「页面价￥N不可购」（N=:g 去尾零）+ 独立键 lurePrice（webui
    价格格徽标数据源，riskPolicy 同构三端协议）。"""
    row = _run(_mk_item(show_price=980.0, min_tprice=1000.0,
                        filt="980.0,970.0"))
    assert "页面价￥980不可购" in row["labels"]
    assert row["lurePrice"] == 980


def test_lure_price_key_absent_when_clean():
    """无触发行不落 lurePrice 键（防孤儿键：有值才落）。"""
    row = _run(_mk_item(min_tprice=1000.0, filt="980.0"))
    assert "lurePrice" not in row


def test_lure_price_float_form_match():
    """FILTED_PRICES 单值 '980.0' 浮点串：数值等值匹配（容差 0.01）
    而非逐字比对——'980'/'980.0' 形态差不误杀。"""
    row = _run(_mk_item(show_price=980.0, min_tprice=1000.0,
                        filt="980.0"))
    assert "页面价￥980不可购" in row["labels"]


def test_lure_price_not_in_filted_absent():
    """showPrice 不在 FILTED_PRICES（nt=104 在场但无该键/空串）→
    背离不落标记（宁缺勿错：无过滤清单互证不判诱饵）。"""
    row = _run(_mk_item(show_price=980.0, min_tprice=1000.0, filt=""))
    assert "页面价" not in row.get("labels", "")
    row2 = _run(_mk_item(show_price=980.0, min_tprice=1000.0,
                         nt104_bad=True))
    assert "页面价" not in row2.get("labels", "")


def test_lure_price_gap_over_5pct_absent():
    """背离幅度 >5%（实证域 0.40%–3.00% 之外）→ 形态未证不落。"""
    row = _run(_mk_item(show_price=900.0, min_tprice=1000.0,
                        filt="900.0"))
    assert "页面价" not in row.get("labels", "")


def test_lure_price_no_deviation_absent():
    """showPrice == 最低 tprice（无背离）→ 不落。"""
    row = _run(_mk_item(show_price=1000.0, min_tprice=1000.0,
                        filt="1000.0"))
    assert "页面价" not in row.get("labels", "")


def test_lure_price_no_nt105_absent():
    """无 nt=105 note 的行（主流形态）→ 不落不炸。"""
    row = _run(_mk_item(min_tprice=1000.0, filt="980.0"))
    assert "页面价" not in row.get("labels", "")


# ---- allilst 航盟词面 ----

_ALLI = [{"alliname": "天合联盟", "airs": ["MU", "MF", "FM"]},
         {"alliname": "星空联盟", "airs": ["CA", "ZH"]}]


def test_alliance_label_fired():
    """行航班号二字码 ∈ airs → labels 落盟名词面（透传不自解析）。"""
    row = _run(_mk_item(flgno="MU1234"), allilst=_ALLI)
    assert "天合联盟" in row["labels"]
    row2 = _run(_mk_item(flgno="CA989"), allilst=_ALLI)
    assert "星空联盟" in row2["labels"]


def test_alliance_transfer_two_carriers():
    """中转行两段不同盟：两盟词面齐落（labels 去重各自独立）。"""
    it = _mk_item(flgno="MU1234")
    it["mutilstn"].append(_seg("CA989"))
    it["policyinfo"][0]["tprice"] = 1500.0
    row = _run(it, allilst=_ALLI)
    assert "天合联盟" in row["labels"] and "星空联盟" in row["labels"]


def test_alliance_airs_absent_no_inference():
    """二字码不在任何 airs（9C 未入盟且字典部分性）→ 零盟词，且不得
    推判「无联盟」造词。"""
    row = _run(_mk_item(flgno="9C8888"), allilst=_ALLI)
    assert "联盟" not in row.get("labels", "")


def test_alliance_unknown_name_whitelist():
    """未知盟名白名单弃（透传不自解析，宁缺勿错）。"""
    row = _run(_mk_item(flgno="MU1234"),
               allilst=[{"alliname": "未知联盟", "airs": ["MU"]}])
    assert "未知联盟" not in row.get("labels", "")
    assert "联盟" not in row.get("labels", "")


def test_alliance_absent_and_list_form():
    """无 allilst 根键 / 响应根是 list 形态：零盟词不炸。"""
    row = _run(_mk_item())
    assert "联盟" not in row.get("labels", "")
    row2 = _run(_mk_item(), root_list=True)
    assert "联盟" not in row2.get("labels", "")


def test_labels_baseline_intact():
    """两标记全无触发的行，labels 与既有出口形态一致（空串不受污染）。"""
    row = _run(_mk_item())
    assert row.get("labels") == "机上Wi-Fi" or "labels" not in row or \
        "页面价" not in row.get("labels", "")


# ---- webui 白名单/价格格徽标（三端同轮：ctrip 出口→白名单→渲染门） ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        import inspect
        import webui
        _SRC = webui_full_src()
    return _SRC


def test_webui_lure_price_whitelist_and_badge():
    s = src()
    # 白名单透传（riskPolicy 同构位；int 协议 _int_or_none 转写）
    assert '"lurePrice": _int_or_none(f.get("lurePrice"))' in s
    # 价格格行内徽标：⚠词面 + 悬停 title 释义（pretax 家族样式，
    # riskPolicy/黑卡价/税前 同槽）
    assert "页面价￥" in s and "不可购" in s
    assert "f.lurePrice?" in s


def test_webui_p11_kpisum_touch_floor():
    """P1-1（r219 WebUI 审计）：概览 kpisum 内联链移动端热区 16px
    （36 地板的 44%）——inline 垂直 padding 实体扩张+水平负 margin
    回收（不破一行排版，行高零漂移）。r273 同声明追加基态
    text-decoration:none（链接族下划线语言收口），热区语义不变。"""
    assert (".kpisum a{position:relative;padding:12px 4px;margin:0 -4px;"
            "text-decoration:none}") in src()


def test_webui_p21_pushlog_empty_title():
    """P2-1（r219 WebUI 审计）：推送记录空账本标题「最近 0 条」别扭，
    空态降级「暂无推送记录」（有记录时保留计数词面）。

    图标已从 emoji 收编为内联 SVG（深色下 emoji 自带彩色底，与扁平语言冲突），
    所以这里只锚「标题文案 + 计数胶囊 + 空态降级」，不锁 emoji。"""
    src_ = src()
    assert "$('pvTitle').innerHTML=(items.length" in src_
    assert "推送记录<span class=\"pvhead-n\">最近 '+items.length+' 条</span>" in src_
    assert "暂无推送记录" in src_
    # 有记录 / 无记录 必须走同一处三元，不能各写一套
    i = src_.index("$('pvTitle').innerHTML=(items.length")
    seg = src_[i:i + 420]
    assert 'use href="#i-bell"' in seg, "标题缺少铃铛图标"


# ---- P2-2（推送审校）：补位角标「0h前」词面反语义 ----

def test_stale_txt_single_source():
    """补位时长词面单源：<1h 落「刚补位」（:.0f 四舍五入把 0.4h 产成
    「0h前」——零时读感是旧数据，实为最新补位，语义反向）；≥1h 恒
    「Nh前」；空值空串（词面缺席由消费点 if 门控制）。"""
    from core.alerter import _stale_txt
    assert _stale_txt(0.4) == "刚补位"
    assert _stale_txt(0.9) == "刚补位"
    assert _stale_txt(1.0) == "1h前"
    assert _stale_txt(25.3) == "25h前"
    assert _stale_txt(0) == ""
    assert _stale_txt(None) == ""
    assert _stale_txt("") == ""


def test_stale_txt_text_version():
    """文本版消费点：40 半角预算下含渠道完整段的最小行恒超宽走降级
    （slim2 剥 stale 段=既有「次要信号先丢」语义）——行级钉锁两点：
    ①「0h前」恒非法（任何档位）；②降级剥除路径对新词面「刚补位」
    生效（曾有裸 :.0f 表达式残留失配致剥段失效——兄弟消费点判例）。
    「刚补位」产出层由 test_stale_txt_single_source 单独锁。"""
    from core.alerter import Alerter
    base = {"_platform": "qunar", "_stale_h": 0.4,
            "price": 900, "name": "9C6928", "depTime": "08:30",
            "arrTime": "11:20"}
    line = Alerter._fmt_flight_line(dict(base), idx=1)
    assert "0h前" not in line
    # 剥除生效：超宽行降级后 stale 词面（新旧形态）皆不在场
    assert "刚补位" not in line or "去哪儿·刚补位" in line
    # 旧形态裸表达式已亡：构造长航班号逼入 slim 档，剥除后不留
    # 「·刚补位」残段
    f2 = dict(base, name="9C6928XYZEXT")
    line2 = Alerter._fmt_flight_line(f2, idx=1)
    assert "0h前" not in line2
    if "去哪儿" not in line2 or "刚补位" not in line2:
        assert "刚补位" not in line2   # 剥净或未渲染，无半截残留


def test_stale_txt_png_version():
    """图版 _plat_tag 消费点：同词同源（两版同词面承诺延伸）；正常
    构造源（report 侧 age_h>=1 门）形态不变。"""
    from report import _plat_tag
    from core.alerter import _stale_txt  # noqa: F401 单源 import 在场
    assert _plat_tag({"_platform": "tongcheng", "_stale_h": 0.4},
                     {"tongcheng": "同程"}) == "同程·刚补位"
    assert _plat_tag({"_platform": "tongcheng", "_stale_h": 2.0},
                     {"tongcheng": "同程"}) == "同程·2h前"
    assert _plat_tag({"_platform": "qunar"},
                     {"qunar": "去哪儿"}) == "去哪儿"


# ---- merged from tests/test_v15273_ui.py ----

SRC = webui_full_src()

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False






def _open_search(pg):
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.evaluate("switchView('search')")
    pg.wait_for_selector("#searchview .srx-row", timeout=15000)
    pg.wait_for_function(
        "typeof SRX_WATCH !== 'undefined' && SRX_WATCH.loadedFor",
        timeout=15000)


# ---------- source pins（渲染态另有行为钉兜底） ----------

def test_demo_honesty_labels_present():
    assert "live.innerHTML='<i></i>'+(demo?'DEMO':'LIVE')" in SRC
    assert "演示数据 · 合成" in SRC
    # 文案不写死渠道数量（接入 App 后是 7 家）；守的是「演示行必须自报合成」
    assert "合成演示行" in SRC
    assert "演示库不含真实报价" in SRC


def test_matrix_sticky_header_and_first_column():
    assert "position:sticky;top:0;z-index:3" in SRC
    assert "th:first-child{text-align:left;min-width:140px;position:sticky;left:0" in SRC
    assert "td:first-child{text-align:left;font-family:inherit;position:sticky;left:0" in SRC
    assert "SRX.view==='matrix'?'none':''" in SRC


def test_calendar_rows_never_enter_compare():
    assert "(f.cal?'':xrowHtml" in SRC


def test_unfollow_requires_confirm():
    assert "取消关注该航班？" in SRC
    assert "function srxWatchToggleDo" in SRC


def test_savebar_yields_to_watch_form():
    assert "body.cwform-open .savebar{display:none}" in SRC
    assert "cwform-open',!!(CFG_WATCH.addOpen||CFG_WATCH.edit)" in SRC


def test_note_shows_full_text_and_two_lines():
    assert "esc(String(w.note).slice(0,16))" not in SRC
    assert "-webkit-line-clamp:2" in SRC


def test_mobile_and_responsive_contracts():
    # r386：价格列由 auto 改固定宽——每条行是独立 grid，auto 会按本行
    # 价格字符数算宽，行间价格左缘参差 17px（用户实报对齐问题）
    assert "grid-template-columns:26px minmax(0,1fr) 86px 118px" in SRC
    assert "左右滑动查看更多日期" in SRC
    # r420：镜像工具条不再 wrap（wrap 会把「收起镜像」单独挤到第二行），
    # 改为单行横向滚动。r700 起这条约束收敛成**一处**（基础层就 nowrap，
    # 折叠钮/工具组在所有桌面宽度都 sticky right），不再按断点各写一份——
    # 所以判据改成「至少一处 nowrap 且全站无 wrap 残留」。
    assert SRC.count("srx-mrail{flex-wrap:nowrap") >= 1
    assert "srx-mrail{flex-wrap:wrap" not in SRC
    assert ".monwatch:last-child:nth-child(odd)" in SRC
    assert "bottom:calc(18px + env(safe-area-inset-bottom))" in SRC


def test_mobile_inputs_avoid_ios_focus_zoom():
    assert ("#cwForm select,.ws-filterbar input,.ws-filterbar select"
            "{font-size:16px!important}") in SRC


def test_no_threshold_rows_never_claim_miss():
    # v1.5.274: CSV 状态列补「仅观察」语义后 +1；v1.5.278 CSV/证据 JSON
    # 各再补一处状态/onlyObserve = 6 处消费同一判据
    assert SRC.count("!Number(f.th)") == 6
    assert "未设心理线，不作达标判断" in SRC
    assert "仅观察 · 未设心理线" in SRC


def test_compare_groups_are_cabin_and_stale_aware():
    assert "function srxCabinClass(f)" in SRC
    assert "function srxCompareKey(f)" in SRC
    assert "srxCompareKey(x)===k" in SRC
    assert "!srxIsCal(x)&&!srxIsStale(x)&&srxCompareKey(x)===k" in SRC
    assert "if(srxIsCal(f)||srxIsStale(f))continue" in SRC
    assert "'票种:'+s.slice(0,16)" in SRC


def test_legacy_fp_uses_real_flight_code_and_cabin():
    assert "(f.code||f.flightNo||f.name||'')" in SRC
    # v1.5.274: 舱位段改走 srxCabinClass（同班键与看板/走势共用语义类），
    # 原直接拼 cabinT 会在「经济舱」与「经济」间产生假分组
    assert "typeof srxCabinClass==='function'?srxCabinClass(f):(f.cabinT||f.cabinCode||'')" in SRC


def test_cross_day_arrival_date_in_detail():
    assert "function srxArrDate(f)" in SRC
    assert "'（到达 '+srxArrDate(f)+'）'" in SRC


def test_health_login_action_keeps_channel():
    assert 'onclick="srxGoLogin(this.dataset.p)"' in SRC
    assert "String(x.getAttribute('onclick')||'').includes(\"'\"+p+\"'\")" in SRC


def test_overlay_and_input_ime_contracts():
    assert "#toasts{position:fixed;bottom:78px;right:18px;z-index:300" in SRC
    assert SRC.count("ev.isComposing||ev.keyCode===229") == 3
    assert "window.open(url,'_blank','noopener')" not in SRC
    assert "a.target='_blank';a.rel='noopener'" in SRC
    assert 'data-citytoggle="1"' in SRC
    assert "e.target.closest('[data-citytoggle]')" in SRC
    assert "if(!inp||_cpClosing)return;" in SRC
    assert "aria-expanded=\"'+(SRX.exp===srxKey(f))" in SRC
    assert "const _wasExp=!!(_ae&&_ae.closest&&_ae.closest('[data-expbtn]'))" in SRC


def test_health_calendar_only_hidden_from_detail_rate():
    from core.health import parse_health

    def line(ts, msg):
        return "%s [INFO] t: %s" % (ts, msg)

    lines = []
    for i, body in enumerate((
        "[qunar] 2026-10-04 日历最低价 ￥1526",
        "[qunar] 2026-10-04 最低价 ￥1526（航班明细 70 条）",
        "[qunar] 2026-10-04 达到最大重试圈数 5 仍未拿到价格",
    )):
        lines.append(line("2026-09-09 0%d:00:00" % i,
                          "===== 开始一轮扫描 ====="))
        lines.append(line("2026-09-09 0%d:00:30" % i, body))
        lines.append(line("2026-09-09 0%d:01:00" % i,
                          "===== 本轮扫描结束 ====="))
    st = parse_health("\n".join(lines), now="2026-09-09 04:00:00")["stats"]["qunar"]
    assert st["cal_only"] == 1
    assert st["detail_ok"] == 1
    assert abs(st["rate"] - 2 / 3) < 1e-6
    # v1.5.275：日历-only 轮没有机会产出航班明细，不进明细分母
    assert abs(st["detail_rate"] - 1 / 2) < 1e-6
    assert ".hc.cal{background:var(--warn);opacity:.55}" in SRC


# ---------- rendered behavior ----------











# ---- merged from tests/test_v1553_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1553Pins:
    """webui.py 源码级钉死：改色/词面/结构错一处即失败，源码钉模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- A/B 环标词面与半径 ----------

    def test_kline_ring_anchor_wording(self):
        src = self._src()
        # K线图例括注失实修正：●锚真达标轮自身价，○ 才锚桶最低价
        assert "环标：●标在真达标轮自身价 · ○标在桶最低价" in src
        assert "环标（标在桶最低价）" not in src

    def test_ring_radius_no_inversion(self):
        """●实心 r=5 / ○擦边 r=5 / ○破线 r=5 全档对齐（推送 PNG 同档），
        旧 ○破线 5.5 倒挂清零。"""
        src = self._src()
        assert "5.5,1,grn" not in src
        assert src.count("[5,1,grn]") == 2      # K线 + 折线两分支

    # ---- C 图例词面收口 ----------

    def test_details_tab_legend(self):
        src = self._src()
        # audit：色面指代与日历同词面（实绿→深绿）
        assert "深绿=真达标 · 描绿=行情破线 · 琥珀=擦边" in src
        assert "实绿=真达标" not in src                # 旧词面不回潮
        assert "描边绿=行情破线未必可出手" not in src   # 旧词面已收进 title
        assert 'title="描绿=行情破线' in src

    def test_calendar_footnote_disambiguated(self):
        """日历红=格底色（与走势 ▼红箭头两语义），尾注消歧。"""
        src = self._src()
        assert "红=超线（格底）" in src
        assert "红=超线（直飞）" not in src

    def test_pushlog_sample_untouched(self):
        """铁律：NDEMO/pushlog 样例串有 count>=2 断言守护，不得受本轮影响。"""
        assert self._src().count("🎯真达标 🟩破线 🟨擦边 超线") >= 2

    # ---- D/E C_NEAR 加深 + RGB 令牌 ----------

    def test_warn_deepened_pairs(self):
        src = self._src()
        assert "--warn:#8a6c00" in src                      # 亮色加深过 AA
        assert "--warn:#d9b34a" in src                      # 暗色不动
        assert "9a7800" not in src                          # 旧值全文件清零
        assert "154,120,0" not in src
        assert "'#8a6c00'" in src                           # JS 环色兜底两处
        assert "[138,108,0]" in src                         # 日历热力兜底

    def test_rgb_tokens_defined_and_consumed(self):
        src = self._src()
        assert "--warn-rgb:138,108,0" in src
        assert "--warn-rgb:217,179,74" in src               # 暗色成对
        assert "--blue-rgb:11,98,214" in src
        assert "--blue-rgb:99,164,248" in src               # 暗色成对
        assert "rgba(var(--warn-rgb),.55)" in src           # .bar i.near 渐变尾
        assert "rgba(var(--warn-rgb),.45)" in src           # --warnbd
        assert "rgba(var(--blue-rgb),.12)" in src           # .cdt.run
        assert "rgba(var(--blue-rgb),.5)" in src            # cfgflash
        assert "11,98,214" not in src.replace("--blue-rgb:11,98,214", "")

    # ---- F 过渡动画三件套 ----------

    def test_pvmask_transition(self):
        src = self._src()
        assert "opacity:0;visibility:hidden;transition:opacity .18s,visibility .18s" in src
        assert ".pvmask.on{opacity:1;visibility:visible}" in src
        assert "transform:translateY(10px);transition:transform .18s" in src
        assert ".pvmask.on .pvcard{transform:translateY(0)}" in src
        assert ".pvmask{position:fixed;inset:0;background:rgba(16,24,40,.45);z-index:200;display:flex" in src

    def test_savebar_transition(self):
        src = self._src()
        # 补 visibility 双态（隐藏态按钮在焦点树内，键盘 Tab
        # 曾命中不可见按钮静默保存/回滚配置）
        assert ("transform:translateY(140%);opacity:0;visibility:hidden;\n"
                "   transition:transform .22s,opacity .22s,visibility .22s") in src
        assert ".savebar.on{transform:translateY(0);opacity:1;visibility:visible}" in src
        assert "classList.toggle('on',dirty&&VIEW==='cfg')" in src   # JS 硬翻已改类切换
        assert "sb.style.display" not in src

    def test_hc_hover_smoothed(self):
        assert "transition:transform .12s ease" in self._src()

    # ---- G/H mono 与 muted ----------

    def test_mono_finishing(self):
        src = self._src()
        assert "#ftable tbody td:nth-child(8)" in src       # 中转列入组
        assert 'id="updated" style="font-family:var(--num)"' in src
        assert 'id="fcnt" style="font-family:var(--num)"' in src
        assert "color:var(--mut);border-radius:var(--r10);padding:2px 10px;font-size:11px;\n      font-family:var(--num);" in src  # .cdt 圆角并轨 --r10（r222 令牌化，margin-right 已并 .hdmeta gap 单源）；mono 档位断言不变

    def test_light_mut_deepened(self):
        src = self._src()
        assert "--mut:#5a6c7d" in src
        # r500 把深色 --mut 从 #7f92a6 提亮到 #8497ab：旧值压面板底只有
        # 4.37~4.47:1，差一点点不过 AA。契约已由
        # test_r374_unified_ui::test_dark_theme_muted_text_clears_aa 精算接管，
        # 这里只保留「深色与浅色不是同一个值」这一层，不再钉死具体色阶。
        # 注意：只查**声明**（`--mut:#7f92a6` 作为 CSS 值），不扫全文——
        # 注释里提到这个历史色值不该判红（实测注释里就有两处说明）。
        import re as _re
        assert not _re.search(r"--mut:#7f92a6\s*;", src), \
            "深色 --mut 回退成了旧值 #7f92a6"

    # ---- I 可达性 ----------

    def test_toasts_and_timer_aria(self):
        src = self._src()
        assert "box.setAttribute('role','status');box.setAttribute('aria-live','polite')" in src
        assert 'id="nextrun" class="cdt" role="timer"' in src

    # ---- J URL 深链 ----------

    def test_url_deeplink_sync(self):
        src = self._src()
        # showMonTab（!silent 门内）与 switchView 尾部各一处
        # replaceState 同步；hashchange else 归位分支再+1（白名单外/
        # 空 hash 清洗防「URL=#bogus_tab 而视图停 cfg」不一致态）；
        # hashchange 白名单分支深链回写再+1（r243 P3-1：switchView
        # 的 '#mon' 覆写会洗掉 '#tab/uN'，回写入站 hash 恢复分享/
        # 刷新语义）；pickUser 尾部再+1（用户维度深链 #tab/uN）；
        # 启动恢复块 localStorage 回退档补写裸 tab 再+1（#tab/uN 双段
        # 深链档保持原 hash 零写入——写点受控枚举锁，非永恒数字）
        assert src.count("history.replaceState(null,'',") == 6
        assert "['overview','specials','trend','watch','details','health'].indexOf(_ht)>=0" in src   # hash 白名单防注入（启动块双段解析后；specials 为监控页签）
        assert "const _hv=location.hash.slice(1).split('/')[0]" in src
        assert "switchView('cfg',false)" in src

    # ---- K/L 宽屏档 ----------

    def test_2k_canvas_height_tier(self):
        # r301 F-1 退役旧 42vh 专带（1920 整点跳变 Δ+94/+26% 与
        # 1865-1919 失比窗）：断点随 wrap 封顶点（1716/0.92≈1865）
        # 同拍 1866 起坡，带内 vw 连续函数爬升 460 封顶——带界零跳变
        src = self._src()
        # 旧形态禁复活（42vh 专带=整点跳变源）
        assert "clamp(280px,42vh,460px)" not in src
        # 实效档在场：1866 起坡连续函数
        assert ("@media(min-width:1866px){\n  canvas{height:min(460px,"
                "calc(360px + (100vw - 1866px)*0.6))}}") in src

    def test_kpiw_merged_tier(self):
        src = self._src()
        # 流式 min(1168px,100%)——992 固定值在 1366/1280 主流本
        # 留 ~150px 右空腔；多档覆写随流式收口删除
        assert "--kpiw:min(1168px,100%)" in src
        assert "--kpiw:1168px" not in src
        assert "--kpiw:1160px" not in src
        assert "--kpiw:1172px" not in src


# ---- merged from tests/test_v162_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV162Pins:
    """webui.py 源码级钉死（同 test_v1558_webui.py 模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- 图床「测试上传」 ----------

    def test_imghost_test_upload_frontend(self):
        src = self._src()
        assert "function testImghost(" in src          # 仿 testNtfy guard+busy+toast
        assert "testImghost(${i},this)" in src         # 卡内按钮（用表单当前值）
        assert "/api/test-imghost" in src              # POST 端点
        assert "请先填写 sm.ms Token" in src           # 对齐 saveCfg 同款拦截词面

    def test_imghost_test_upload_backend_direct_call(self):
        src = self._src()
        assert '"/api/test-imghost"' in src
        # 直调所选床：不走 upload_chart——freeimage 连败记忆会静默
        # 跳档，走 upload_chart 测试会假绿（备案 核心约束）
        assert "from report import upload_freeimage, upload_smms" in src
        assert "upload_chart(" not in src
        # freeimage 死/退避期返回 None：测试端必须如实报败
        # （pixhost 死链降级档已撤出上传链，None 即所选床不可用）
        assert "url = upload_freeimage(_png.name, tlog)" in src
        assert '"pixhost" in url' not in src, "死码分支残留"
        assert "iVBORw0KGgo" in src                    # 1×1 PNG 内存图常量

    # ---- kpiw 空腔收敛 ----------

    def test_kpiw_1920_release_non_proportional_parts(self):
        src = self._src()
        # r302 W1：四族同上限（纯 none 是 ≥1726 双轴回潮病灶形态）
        assert (".statline,#pulseLegend,.pulsewrap"
                "{max-width:min(1440px,100%)}" in src)
        # .grid/.kpisum 保持 1168 纪律（KPI 价卡过扁失比，取舍成立）
        assert ".kpisum{max-width:var(--kpiw)}" in src

    # ---- esc 补转义 + importCfg 归一 ----------

    def test_esc_escapes_ampersand_angle_brackets(self):
        src = self._src()
        # & 必须最先转义（防把后续产生的实体再转一次）
        assert (".replace(/&/g,'&amp;').replace(/</g,'&lt;')"
                ".replace(/>/g,'&gt;')") in src
        # 引号转义保留（delDate 等 JS 单引号上下文调用面依赖）
        assert ".replace(/\"/g,'&quot;').replace(/'/g,'&#39;')" in src

    def test_import_cfg_dates_normalized(self):
        # 导入文件是不归一路径：dates 过 addDate 同款 _normDate，丢非法项
        assert "(r.dates||[]).map(_normDate).filter(Boolean)" in self._src()

    # ---- 末用户删除残留回收 ----------

    def test_empty_users_hides_pulsecard_userpills(self):
        src = self._src()
        assert "$('pulsecard').style.display='none'" in src
        assert "$('userPills').style.display='none'" in src

    # ---- 弹层开启快捷键守卫 ----------

    def test_hotkey_guard_when_modal_open(self):
        src = self._src()
        # Ctrl+S 分支之后、数字键/R// 分发之前：R 两段确认=后台真触发
        # 全量扫描，弹层开着必须挡
        assert "if($('pvMask').classList.contains('on'))return;" in src

    # ---- AA 对比度 ----------

    def test_aa_ok_text_and_warn_deep_tokens(self):
        src = self._src()
        assert "--ok-txt:#0b6e39" in src               # 对 --okbg 5.63:1（原 4.28 欠 AA）
        assert "--warn-deep:#6f5600" in src            # 对 --headbg 6.21:1（原 4.42 欠 AA）
        assert ".pill.ok{background:var(--okbg);color:var(--ok-txt)" in src
        assert ".hbadge.ok{color:var(--ok-txt)" in src
        assert ".upill.ok{color:var(--ok-txt)" in src
        assert ".chip .bd.mid{color:var(--warn-deep)}" in src
        # 暗色成对换谱（暗底原值已过 AA，外观不变）
        assert "--ok-txt:#43c072" in src
        assert "--warn-deep:#d9b34a" in src

    # ---- NEAR 注释锚 ----------

    def test_near_comment_anchor_single_source(self):
        src = self._src()
        assert "report.py NEAR_RATIO" not in src       # 旧锚清零（单源已迁 core.alerter）
        assert "core.alerter NEAR_RATIO=0.10" in src

    # ---- open 改 with ----------

    def test_read_open_uses_with(self):
        src = self._src()
        assert "_j.load(open(" not in src              # /notify 两处
        assert "_y.safe_load(open(" not in src         # GET/POST /api/config 两处

    # ---- 搜索索引 rhead ----------

    def test_cfg_search_indexes_rhead(self):
        src = self._src()
        assert "rl.querySelector('.rhead')" in src     # rhead 摘要并入索引面
        # rhead 独命中计入 cfgHits（防空卡配「无匹配项」假阴性）
        assert "if(rhm){n++;" in src

    # ---- tgbox 窄屏 ----------

    def test_tgbox_narrow_viewport_release(self):
        src = self._src()
        assert ".tgbox{display:block;max-width:460px}" in src   # 基础档保留
        # ≤760 档锚视口带宽（r302 W2：td=colspan 全表宽 ~721px，锚 100%
        # 实得 701 首屏仅见 47%；max-width 只封顶，td 窄时仍取 td 全宽）
        assert ("@media(max-width:760px)"
                "{.tgbox{max-width:calc(100vw - 24px)}}") in src


class TestTestImghostEndpoint:
    """/api/test-imghost 真请求（守卫分支，不触外网）。"""

    @staticmethod
    def _post(payload):
        import webui as _w
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _w._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/api/test-imghost" % srv.server_address[1],
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_unknown_provider_rejected(self):
        st, j = self._post({"provider": "pixhost", "token": ""})
        assert st == 200 and j["ok"] is False and "未知图床" in j["err"]

    def test_smms_without_token_rejected(self):
        st, j = self._post({"provider": "smms", "token": "  "})
        assert st == 200 and j["ok"] is False and "Token" in j["err"]

    def test_demo_mode_blocked(self):
        import webui as _w
        saved = _w.DEMO["on"]
        _w.DEMO["on"] = True
        try:
            try:
                st, j = self._post({"provider": "freeimage", "token": ""})
            except urllib.error.HTTPError as e:
                st = e.code
                j = json.loads(e.read().decode("utf-8"))
            assert st == 403 and j.get("demo") is True
        finally:
            _w.DEMO["on"] = saved


# ---- merged from tests/test_v169_webui.py ----

class TestWebuiV169Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_cal_qhit_class_and_css(self):
        """q=2 格挂 qhit 类；小字对比度由无税基线全档保证
        （.cd/.cx 无 opacity 声明，v191 钉锁定基线形态）。"""
        src = self._src()
        assert "(q===2?' qhit':'')" in src
        assert ".calcell .cd{font-size:11px;font-weight:600}" in src

    def test_cal_qbrk_breakline_small_text(self):
        """qbrk 类已退役（r226 审计：CSS 规则先亡、产出点成零消费
        死类钩子——破线格视觉由格底 alpha 渐变承担）；q=2 语义锚
        qhit 与价格小字排印（.cx）保持在场。"""
        src = self._src()
        assert "(q===1?' qbrk':'')" not in src, \
            "qbrk 死类产出点应已退役"
        assert "qbrk" not in src
        assert "(q===2?' qhit':'')" in src
        assert ".calcell .cx{font-size:11px;" \
               "margin-top:1px;font-variant-numeric:tabular-nums}" in src

    def test_dark_uava_gradient_deep(self):
        """暗色 .uava 渐变第二站收 --fill（#63a4f8 白字
        2.56 实锤 → fill2→fill 全带 4.86~5.59）。"""
        src = self._src()
        assert ('html[data-theme="dark"] .uava{background:'
                'linear-gradient(135deg,var(--fill2),var(--fill))}') in src

    def test_cal_breakline_m1_tx_constant_alpha_053(self):
        """案结 + 修正：alpha 上限 0.53（合成底真实衬底
        #calcard --card 非 --bg，0.5373 交点留余量）+ 亮暗恒 var(--tx)。"""
        src = self._src()
        assert "const a=0.25+Math.min(0.28,(1-r)*2.2);" in src
        assert "fg=DK?(a>=0.55?FGDK" not in src

    def test_fill2_deepened_both_themes(self):
        """：--fill2 亮 #1d6fd8 / 暗 #3771c4（渐变顶带白字全带 ≥4.86）。"""
        src = self._src()
        assert "--fill2:#1d6fd8" in src
        assert "--fill2:#3771c4" in src
        assert "--fill2:#2f83ea" not in src
        assert "--fill2:#3f82d8" not in src

    def test_chip_bd_tax_removed_and_on_tokens_lightened(self):
        """：.bd 删 opacity:.9 税 + 选中底令牌提亮（全表 ≥4.5）。"""
        src = self._src()
        assert ".chip .bd{font-style:normal;font-size:10px;margin-left:4px}" in src
        assert "--chip-on-warn:#ffe9b8" in src
        assert "--chip-on-red:#ffe0e1" in src
        assert "--chip-on-warn:#ffe3a3" not in src
        assert "--chip-on-red:#ffc4c5" not in src

    def test_dark_arming_fltbtn_deep_red(self):
        """：暗色 arming/筛选角标填充底深红覆写（3.49→5.89）。
        r239 P3-3 令牌化：hex 收进 --danger-solid（dark 块定义），
        钉面从字面量改写为「令牌定义+消费」语义锁（值不变）。"""
        src = self._src()
        assert "--danger-solid:#b3393c" in src
        assert ("html[data-theme=\"dark\"] button.arming"
                "{background:var(--danger-solid)") in src
        assert ("html[data-theme=\"dark\"] #fltBtn b"
                "{background:var(--danger-solid)}") in src

    def test_widget_radius_and_pop_shadow_tokens(self):
        """微件圆角两档与弹层阴影令牌（r239 P3-1/P3-2 收口的常备钉）：
        防下轮误回退裸值——圆角 2px/5px 档、开关圆点浮起与弹层重阴影
        均走 :root 令牌，消费点在案（语义锁，值不变）。"""
        src = self._src()
        assert "--r-xs:2px;--r-sm:5px;" in src
        assert src.count("var(--r-xs)") >= 5
        assert src.count("var(--r-sm)") >= 2
        assert "--sh-knob:0 1px 2px rgba(0,0,0,.25);" in src
        assert "--sh-pop:0 18px 50px rgba(16,24,40,.35);" in src
        assert "box-shadow:var(--sh-knob)" in src
        assert "box-shadow:var(--sh-pop)" in src

    def test_health_cells_fill_wide(self):
        """宽带时间线弹性格均分铺满（容器保 flex:1 占满；审计原
        「容器收缩+max-width 12」模型 Chrome 实测格宽归零，弃用）。
        r322 改写：弹性铺满承载面从静态 1024 媒体块退役为 .fit 实
        判定类（JS _hfit 单源挂类——门槛按满密度校准，轻轮次格带
        在门槛下带放得下却恒左聚）；钉面随形态演进改写，语义担保
        （铺满规则在场+无收缩容器回潮）不变。"""
        src = self._src()
        # 实效档在场：均分规则挂 .fit 类（_hfit 实判定挂载）
        assert ".hcells.fit .hc{width:auto;flex:1 1 6px}" in src
        assert "function _hfit(x){" in src
        assert ".hcells{flex:0 1 auto}" not in src
        # 禁复活：静态媒体门槛（轻轮次左聚空腔病灶形态）
        assert ".hc{width:auto;flex:1 1 6px}" not in src.replace(
            ".hcells.fit .hc{width:auto;flex:1 1 6px}", "")
        # 禁复活：1440 独占带=渐进带断缝形态
        assert "min-width:1440px" not in src

    def test_pvbody_padding_aligned(self):
        """：pvbody 水平内衬 16 与 pvhead/pvfoot 三段对齐（曾 18 凸出 2px）。"""
        assert ".pvbody{padding:14px 16px;" in self._src()

    def test_token_hygiene_subset(self):
        """卫生子集：seclab 死声明删/mchip.best spread/圆角并轨/
        pvcard 令牌化/rtcode 14。"""
        src = self._src()
        assert ".seclab{display:flex;align-items:baseline;gap:9px}" in src
        assert "margin:22px 2px 9px" not in src
        assert "box-shadow:0 2px 8px -2px var(--glow)}   /* -2px spread" in src
        assert src.count("border-radius:12px;padding:4px;box-shadow:var(--sh1)") == 0  # nav
        assert "border-radius:12px;padding:2px 10px" not in src  # .cdt
        assert "border-radius:12px;padding:10px 14px" not in src  # savebar
        assert ".pvcard{background:var(--card);border-radius:var(--r);" in src
        assert ".rtcode{font-family:var(--num);font-size:14px;" in src

    def test_kpisum_trend_shortcut(self):
        """：概览 kpisum 补「走势 ▾」直达（jumpRowTrend('') 空路由
        =当前视图，与「查看明细 ▾」对称）。"""
        assert "pickUser(${i});jumpUserBest(${i}," in self._src()

    def test_ok_strong_dead_token_removed(self):
        """：--ok-strong 死令牌删除（var 消费 0 + 定义 0，词面仅存
        历史注释）。"""
        src = self._src()
        assert "var(--ok-strong)" not in src
        assert "--ok-strong:#" not in src


# ---- merged from tests/test_v178_webui.py ----

class TestWebuiV178Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_routesarr_series_carries_full_date(self):
        """/api/state routesArr 系列必须带 date 全日期（YYYY-MM-DD）——
        走势点跳明细时 FLT.dates 锁定的就是它；缺它=跳转目标不存在。"""
        src = self._src()
        assert '"date": d0' in src, \
            "routes_arr 系列未带 date 全日期（C-1 跳转目标键缺失）"

    def test_jump_trend_detail_reuses_calendar_path(self):
        """jumpTrendDetail 定义在位且复用 jumpCalDate（联动路径单源）。"""
        src = self._src()
        assert "function jumpTrendDetail()" in src, \
            "jumpTrendDetail 未定义（走势点→明细入口缺失）"
        i0 = src.index("function jumpTrendDetail()")
        i1 = src.index("function ", i0 + 10)
        body = src[i0:i1]
        assert "jumpCalDate(" in body, \
            "jumpTrendDetail 未复用 jumpCalDate（联动路径双份抄写）"
        assert "curRoute().r.date" in body, \
            "jumpTrendDetail 未从当前系列取 date（跳转目标悬空）"

    def test_chart_click_and_keyboard_wired(self):
        """canvas click 与键盘 Enter 双入口都接到 jumpTrendDetail。"""
        src = self._src()
        i_click = src.index("$('chart').addEventListener('click'")
        i_end = src.index("\n", i_click)
        seg = src[i_click:i_click + 600]
        assert "jumpTrendDetail()" in seg, "canvas click 未接 jumpTrendDetail"
        assert "e.button!==0" in seg, "click 未过滤非主键（右键误跳）"
        assert "_tTap" in seg, "触屏滑动防误触守卫缺失（>8px 位移不跳）"
        i_end = src.index("$('chart').addEventListener('touchend'",
                   src.index("let _tTap"))
        endseg = src[i_end:i_end + 700]
        assert "_tTap=null" in endseg, \
            "touchend 未清 _tTap（混合设备残坐标误吞后续鼠标点击）"
        i_key = src.index("$('chart').addEventListener('keydown'")
        kseg = src[i_key:i_key + 900]
        assert "jumpTrendDetail()" in kseg, "键盘 Enter 未接 jumpTrendDetail"

    def test_cursor_affordance_on_chart(self):
        """canvas 可点须有 cursor affordance（v1.5.74 cursor affordance 律）。

        r374：三处走势统一为 crosshair（读数语义）。pointer 只在「点了会
        跳转」处使用，而三条画的点击语义各不相同（航线跳明细 / 关注钉住
        读数 / 雷达无点击），统一 pointer 会给出错误的可跳转暗示；可点性
        改由 title/aria 文字明说。
        """
        src = self._src()
        assert "#chart{cursor:crosshair}" in src, \
            "#chart 光标未与另两条走势统一"
        assert "点击看该航线当日明细" in src, "可点性缺少文字暗示"

    def test_hint_promise_conditional(self):
        """图例承诺句「点击看该航线当日明细」必须双前提条件在场：
        N>0（有点可点）且 CR.r.date（有处可跳）——空态死承诺防线。
        词面对齐实际行为（画布任意点命中=该系列航线+当日，日历族口径）。"""
        src = self._src()
        assert "点击看该航线当日明细" in src, "图例承诺句丢失"
        i0 = src.index("点击看该航线当日明细")
        seg = src[max(0, i0 - 200):i0]
        # NT>0（r235 共享时间轴：N 更名 NT=轴刻度点数，语义同「有点可点」）
        assert "CR.r.date" in seg and "NT>0" in seg, \
            "承诺句未挂 NT>0+CR.r.date 双前提（空态死承诺风险）"

    def test_canvas_aria_mentions_enter_jump(self):
        """canvas aria-label 补 Enter 跳转提示（键盘可达性闭环）。"""
        src = self._src()
        assert "aria-label=\"价格走势图：聚焦后按左右方向键逐点读数，Home/End 跳首尾，Enter 看该轮明细\"" in src, \
            "canvas aria-label 未含 Enter 跳转提示"

    # ---- tuniu 黑卡价透明标记：白名单 + 渲染门（三端同轮） ----

    def test_blackcard_whitelist_passthrough(self):
        """/api/state 载荷白名单透传 blackCard（缺它=孤儿键前端恒空）。"""
        src = self._src()
        assert '"blackCard": bool(f.get("blackCard"))' in src, \
            "白名单未透传 blackCard（爬虫键到不了渲染门）"

    def test_blackcard_render_tag(self):
        """「黑卡价」徽标挂在价格单元格（复用 .pretax 小标签样式，与
        fliggy「税前」同位——黑卡修饰的是价格本身，比埋进次行醒目；
        次行段数红线 14 不动）。词面与推送图槽位逐字同形「黑卡价」
        （锚定可见文本，title 里的字不算）。"""
        src = self._src()
        i0 = src.index("f.blackCard?'<span class=\"pretax\"")
        seg = src[i0:i0 + 170]
        assert ">黑卡价</span>" in seg and "title=" in seg, \
            "价格格黑卡徽标缺失/词面与推送图不一致或缺解释 title"

    def test_subrow_segment_capacity_still_14(self):
        """黑卡徽标不入次行段数组（v1.5.55 容量红线 14 语义维持）。"""
        page = self._src()
        m = None
        import re as _re
        m = _re.search(r"\$\{\[(.*?)\]\.filter\(Boolean\)\.join\(' ｜ '\)\}",
                       page, _re.S)
        assert m, "次行段数组锚点丢失"
        body = m.group(1)
        assert "blackCard" not in body, "黑卡徽标误入次行段（红线 +1）"

    # ---- audit_v178 P2 落地（焦点交接/原子换行/链接 nowrap） ----

    def test_p2_jump_focus_handoff(self):
        """跳明细后焦点交接明细 tab：原视图（日历格/走势 canvas）隐藏后
        焦点坠 body，键盘用户失位（audit_v178 P2-1）。"""
        src = self._src()
        i0 = src.index("function jumpCalDate(")
        i1 = src.index("\nfunction ", i0 + 10)
        body = src[i0:i1]
        assert '.mtab[data-t="details"]' in body, "焦点交接目标缺失"
        assert ".focus()" in body, "jumpCalDate 未做焦点交接"

    def test_p2_route_span_atomic_wrap(self):
        """航班列「航线 📈」1280-1440 档 mid-word 撕裂：route 文本
        inline-block 原子换行（audit_v178 P2-2）。r246 词组纪律同构
        增强：航向+走势入口整组挂 .stl.nw（窄档📈独占末行孤字收口）。"""
        src = self._src()
        i0 = src.index('${f.route?`<span class="stl nw">')
        seg = src[i0:i0 + 130]
        assert "display:inline-block" in seg, "route 文本非原子换行"

    def test_p2_kpisum_link_nowrap(self):
        """概览「查看明细 ▸ / 走势 ▸」768 档箭头孤行折断：链接不得折行
        （audit_v178 P2-3）。r302 W5：跳转词缀与全站跳转 affordance
        （pill ▸/mtabUser ▸）统一单形 ▸，▾ 仅存于折叠头族。

        r419 起两个动作从 kpisum 句尾移到卡头 `.uact2`：nowrap 由该容器
        统一提供（`white-space:nowrap` + `flex:0 0 auto`），因此断言
        改为「这两处入口都处在不折行的容器里」，语义不变。"""
        src = self._src()
        assert "查看明细 ▾" not in src, "跳转词缀旧形 ▾ 复活"
        assert '.uhead .uact2{margin-left:auto' in src
        i0 = src.index(".uhead .uact2{margin-left:auto")
        seg = src[i0:i0 + 320]
        assert "white-space:nowrap" in seg, "动作区未 nowrap（箭头会孤行）"
        assert "flex:0 0 auto" in seg, "动作区会被压缩折行"


# ---- merged from tests/test_v180_webui.py ----

class TestWebuiV180Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- ctrip agePolicy：白名单 + 渲染门（三端同轮） ----

    def test_agepolicy_whitelist_passthrough(self):
        """/api/state 载荷白名单透传 agePolicy（缺它=孤儿键前端恒空）。"""
        src = self._src()
        assert '"agePolicy": (f.get("agePolicy") or "").strip()' in src, \
            "白名单未透传 agePolicy（爬虫键到不了渲染门）"

    def test_agepolicy_render_warn_badge(self):
        """价格格 ⚠限XX价 徽标（pretax 同位；⚠+--warn 与孤低价警告同
        语义族=「这个价有坑」；title 说清后果：误购无法出行——资格受限（年龄/会员）通用语义）。"""
        src = self._src()
        assert "f.agePolicy?" in src, "价格格 agePolicy 徽标缺失"
        i0 = src.index("f.agePolicy?")
        seg = src[i0:i0 + 260]
        assert "pretax" in seg, "徽标未复用 pretax 同位样式"
        assert "title=" in seg and "出行" in seg, \
            "徽标缺 title 或未说明误购无法出行后果"
        assert "${he(f.agePolicy)}" in seg, "徽标词面未携带档位词（限青年/限老年/限年龄）"

    def test_agepolicy_not_in_subrow(self):
        """agePolicy 徽标不入次行段数组（v1.5.55 容量红线 14 维持）。"""
        import re as _re
        page = self._src()
        m = _re.search(r"\$\{\[(.*?)\]\.filter\(Boolean\)\.join\(' ｜ '\)\}",
                       page, _re.S)
        assert m, "次行段数组锚点丢失"
        assert "agePolicy" not in m.group(1), "agePolicy 误入次行段（红线 +1）"

    # ---- bizPrice 通道：tuniu/tongcheng 接入零前端改动依赖它 ----

    def test_bizprice_tunnel_unchanged(self):
        """bizPrice 白名单通道在位（v1.5.55 七批建，三渠道共用）。"""
        src = self._src()
        assert '"bizPrice": _int_or_none(f.get("bizPrice"))' in src, \
            "bizPrice 白名单通道丢失（tuniu/tongcheng 接入变孤儿键）"

    # ---- demo 对齐：渲染门/CSV 目检数据源 ----

    @staticmethod
    def _demo_src():
        import core.demo as _d
        with open(_d.__file__, encoding="utf-8") as f:
            return f.read()

    def test_demo_carries_agepolicy_and_bizprice(self):
        """demo：ctrip 行带 agePolicy、tuniu/tongcheng 行带 bizPrice
        （渲染门目检与 CSV 列演示的数据源；缺它=演示页看不到新字段）。"""
        demo = self._demo_src()
        assert 'fs[0]["agePolicy"]' in demo, "demo ctrip 行缺 agePolicy"
        assert demo.count('fs[0]["bizPrice"]') >= 3, \
            "demo bizPrice 演示未覆盖 ctrip/tongcheng/tuniu 三渠道"

    # ---- audit_v180 P1/P2 落地（WebUI 审计报告） ----

    def test_p1_statline_two_col_narrow(self):
        """P1-1：≤760 带强制 statline 2 列——auto-fit 折 3 轨带
        （容器 474-632px≈视口 547-745）4 格变 3+1，第二行空轨露容器
        --line 灰底（缝隙法容器底外露）。2 列 4 格整除零空腔，纯 CSS
        零量纲（renderPulse 幽灵格方案在 display:none 容器量纲全零）。"""
        src = self._src()
        m = None
        import re as _re
        for m in _re.finditer(r"@media\(max-width:760px\)\{", src):
            seg = src[m.start():m.start() + 600]
            if ".statline{grid-template-columns:repeat(2,1fr)}" in seg:
                return
        assert False, "≤760 媒体块缺 statline 2 列规则（窄带灰底空腔仍在）"

    def test_p1_cfg_head_not_squeezed(self):
        """P1-2：配置卡头标题 flex:1（basis:0）被 nowrap 胶囊压到
        min-content=一字一行竖排——min-width 保底 + flex-wrap 让胶囊
        换行；rline 工具条同律。"""
        src = self._src()
        assert ".uhead2 b{flex:1;min-width:8em" in src, \
            "uhead2 标题缺 min-width 保底（窄带竖排字仍在）"
        i0 = src.index(".uhead2{")
        assert "flex-wrap:wrap" in src[i0:i0 + 200], \
            "uhead2 缺 flex-wrap（胶囊挤压标题不换行）"
        i1 = src.index('class="rline cfgtoolbar" style="display:flex')
        assert "flex-wrap:wrap" in src[i1:i1 + 120], \
            "rline 工具条缺 flex-wrap（筛选/动作钮挤压标题）"

    def test_p2_notify_oktxt_contrast(self):
        """P2-2：NOTIFY_PAGE 孪生页 --ok-txt 令牌同步（主控台 P2-3 已
        收口、孪生页漏同步——.hitbar b 绿字对绿底 4.28:1 欠 AA）。"""
        src = self._src()
        i_notify = src.index("NOTIFY_PAGE")
        seg = src[i_notify:]
        assert "--ok-txt" in seg, "NOTIFY 页缺 --ok-txt 令牌"
        i_hit = seg.index(".hitbar b{")
        assert "var(--ok-txt)" in seg[i_hit:i_hit + 80], \
            "hitbar 绿字未消费 --ok-txt（4.28:1 欠 AA 仍在）"

    def test_p2_kpi_aria_uses_platcn(self):
        """P2-1：KPI aria-label 渠道名与可见 tooltip 同语言（读屏听到
        ctrip、明眼看到携程=双语分裂；platCn 与 numlink title 同源）。"""
        src = self._src()
        i0 = src.index("打开行情页（")
        assert "${platCn" in src[i0 - 40:i0 + 80], \
            "KPI aria-label 未消费 platCn（读屏渠道名仍是英文键）"

    def test_p2_trend_jump_focus_handoff(self):
        """P2-3：jumpRowTrend/jumpQual 跳转后焦点交接（jumpCalDate 有、
        同族两处漏——切视图后焦点坠 body，键盘 Tab 从头数）。"""
        src = self._src()
        i0 = src.index("function jumpRowTrend(")
        body = src[i0:src.index("\nfunction ", i0 + 10)]
        assert 'querySelector(\'.mtab[data-t="trend"]\')' in body \
            and ".focus()" in body, "jumpRowTrend 缺焦点交接"
        i1 = src.index("function jumpQual(")
        # 块边界窗口（无固定长度兜底——函数合法增厚不假红，窗口长度是
        # 实现细节，锚结构才是钉面）
        nxt1 = src.find("\nfunction ", i1 + 10)
        body1 = src[i1:nxt1] if nxt1 > 0 else src[i1:]
        assert '.mtab[data-t="details"]' in body1 and ".focus()" in body1, \
            "jumpQual 缺焦点交接"

    def test_p2_filter_chips_empty_neutral(self):
        """P2-5：筛选 chips 默认「全选=全亮」12+ 枚实心蓝稀释选中语义
        ——初始空集（空集=全部语义已在过滤消费点 L1720-1722 在案），
        视觉中性，用户降选动作才有对比。三组集合 chips 同律。"""
        src = self._src()
        assert "else{FLT.plats=new Set();FLT._platsInit=true;}" in src, \
            "渠道 chips 仍初始回填全亮"
        assert "FLT.dates=new Set(keep.length?keep:new Set());" in src, \
            "日期 chips 仍初始回填全亮"
        assert "FLT.routes=new Set(keep.length?keep:new Set());" in src, \
            "航线 chips 仍初始回填全亮"

    def test_p2_touch_first_tap_reads(self):
        """P2-6：触屏首 tap=读数（保留 hover 十字线）、同点二次 tap=跳
        明细——旧形态轻 tap 直接离场，移动端既读不到数值也无法「点一下
        看看」而不换页。"""
        src = self._src()
        for anchor in ("let _tPin=null", "let _tGo=false", "let _tTouch=false"):
            assert anchor in src, f"触屏读数状态位缺失：{anchor}"
        i0 = src.index("let _tTouch=false")
        seg = src[src.index("$('chart').addEventListener('click'", i0):]
        assert "_tGo" in seg[:600] and "jumpTrendDetail" in seg[:600], \
            "click 路径未消费二次 tap 放行位（首 tap 仍直接跳转离场）"

    def test_p2_ios_blocks_crossref(self):
        """P2-8（审计建议修正案）：coarse 块与 ≤760 块条件语义不同
        （900+粗指针 vs 760 任意指针，删 coarse 丢 iPad 竖屏 16px 保护）
        ——不合并，改注释互指防清单漂移。"""
        src = self._src()
        n = src.count("font-size:16px}")
        assert "三处 16px 清单互指" in src, "16px 规则块缺互指注释（漂移风险）"

    def test_p2_srow_inputs_named(self):
        """P2-10：srow/gcell 输入程序化标签关联（渲染后 aria 自动
        关联 .slab b 标题——读屏匿名控件清零，单点后处理覆盖全部行）。"""
        src = self._src()
        assert "aria-label'" in src and ".slab b" in src, \
            "srow 输入缺 aria 自动关联（读屏匿名）"

    def test_p2_pulse_catch_has_note(self):
        """P2-7：/api/pulse 失败分支静默须显式论证（LESSONS 二十三：
        每个异步终点都要有落点——「有则显示」性质的论证注释）。"""
        src = self._src()
        # 锚定 pulse 函数体并放宽窗口（r324 F3 空守卫论证注释把
        # catch/论证注推出旧 400 字窗；意图不变：失败落点须带静默论证）
        i0 = src.index("async function pulse()")
        seg = src[i0:i0 + 700]
        assert "catch(e){PU_ETAG=''" in seg and ("有则显示" in seg or "静默" in seg), \
            "/api/pulse catch 缺静默论证注释或 ETag 作废"


# ---- merged from tests/test_v182_webui.py ----

class TestWebuiV182Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    # ---- P2-1 /api/state 错误体分支落点 ----

    def test_state_errbody_branch(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 1400]
        # 错误体（无 users）显式分支在场，且双形态各有落点
        assert "j&&j.users" in seg or "j && j.users" in seg, \
            "load() 未区分错误体与正常载荷"
        assert "_markStale('服务异常')" in seg, \
            "冷启动错误体未落 _markStale（词面与骨架同轨）"

    # ---- P2-2 /api/health 错误体保陈旧 ----

    def test_health_errbody_keep_stale(self):
        src = self._src()
        i0 = src.index("function renderHealth(j){")
        seg = src[i0:i0 + 700]
        assert "healthcard').style.display!=='none')return" in seg, \
            "renderHealth 已有时间线时不保陈旧（500 掀翻时间线病面仍在）"

    # ---- P2-3 零轮次空态教学句 ----

    def test_empty_state_teaching(self):
        src = self._src()
        i0 = src.index("没有符合条件的航班")
        seg = src[max(0, i0 - 900):i0]
        assert "if(!rows.length){" in seg, "空态未在行渲染前分型"
        assert "if(!u.flights.length)_why=" in src, \
            "erow 未按「零数据 vs 筛选空」分叉"
        assert "本轮尚无采集数据" in src, "零轮次教学句不在场"

    # ---- P2-4 roving tabindex ----

    def test_roving_tabindex_pulse_health(self):
        src = self._src()
        assert "function _roving" in src, "缺 _roving 方向键移动函数"
        # 脉冲柱族：rv 标记（data-rv+动态 tabindex）在 renderPulse 内定义
        i0 = src.index("function renderPulse(")
        # r1718：按**函数体全量**取面（到下一个顶层 function 为止）。
        # 旧实现固定 3200 字符窗口，函数里每加一段（r246 的时段词组、
        # r1716 的夜间静默提示）都会把后面的分支推出窗口而假红。
        _end = src.find("\nfunction ", i0 + 10)
        seg = src[i0:_end] if _end > i0 else src[i0:]
        assert "data-rv" in seg and 'tabindex="${i===0?0:-1}"' in seg, \
            "脉冲柱未挂 roving 标记/动态 tabindex"
        assert seg.count("${rv}") >= 2, "zero/普通两分支未都引用 rv"
        # 健康格族（r1390）：24 小格已并成 6 个 4 小时整段按钮，
        # roving 落在 .hseg 上，首格锚首个已扫描段（未扫描段渲染成 span，
        # 按轮位 0 锚会落在不可点 span 上=该族零停靠点）。
        i1 = src.index('class="hseg" data-p=')
        seg1 = src[max(0, i1 - 900):i1 + 500]
        assert "data-rv" in seg1 and "tabindex=\"'+(si===firstLive?0:-1)+'\"" in seg1, \
            "健康段未挂 roving 标记/动态 tabindex"
        assert "if(firstLive<0)firstLive=si;" in seg1, \
            "roving 首格未锚首个可交互段（全段未扫描会零停靠点）"

    # ---- P2-5 读屏语义 ----

    def test_icon_buttons_aria_label(self):
        src = self._src()
        i0 = src.index('id="ntBtn"')
        seg = src[max(0, i0 - 60):i0 + 160]
        assert "aria-label" in seg, "通知按钮缺 aria-label"
        i1 = src.index('id="themeBtn"')
        assert "aria-label" in src[max(0, i1 - 60):i1 + 160], \
            "主题按钮缺 aria-label"
        i2 = src.index('id="denBtn"')
        assert "aria-label" in src[max(0, i2 - 60):i2 + 160], \
            "密度按钮缺 aria-label"
        i3 = src.index('class="pvx"')
        assert "aria-label" in src[max(0, i3 - 60):i3 + 160], \
            "弹层关闭钮缺 aria-label"

    def test_sort_header_aria_sort(self):
        src = self._src()
        i0 = src.index('class="srt${SORT.k===k?')
        seg = src[i0:i0 + 400]
        assert "aria-sort" in seg, "排序表头缺 aria-sort"

    def test_pretax_title(self):
        src = self._src()
        i0 = src.index('税前</span>')
        seg = src[max(0, i0 - 120):i0]
        assert "title=" in seg and "机建燃油" in seg, \
            "「税前」徽标缺解释 title（同格家族唯一漏网）"

    # ---- P2-6 明细表渲染截断 ----

    def test_table_render_cap(self):
        """v192 起切片渲染取代 300 行一次性截断：首拍只渲首屏切片
        （~120 行），其余滚动近底按需续载——旧全量 innerHTML 重建
        549 班实测 ~214ms 长任务 = 每次排序/筛选点击卡顿的根因。
        截断语义仍受钉：初始渲染量恒有上界（_CHUNK），不再有
        「已显示前 N 班」死截断。"""
        src = self._src()
        i0 = src.index("function table()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert "const CAP=300" not in seg, \
            "旧 300 行一次性截断仍在（点击卡顿根因未除）"
        assert "_chunkHtml(0)" in seg, "table() 未接入首屏切片"
        assert "_tblAppend" in seg, "table() 滚动位深时未补切片"
        assert "const _CHUNK=" in src, "缺切片尺寸常量（初始渲染量无上界）"
        assert "function _tblAppend" in src, "缺切片续载单源"

    # ---- P2-7 toast 错误词面统一 ----

    def test_toast_wordface(self):
        src = self._src()
        assert "function heFriendly" in src, "缺 heFriendly 友好化单源"
        # 全函数窗（截到下一函数）：后段新增 toast 也入钉
        i0 = src.index("function expCsv()")
        i1 = src.index("function ", i0 + 10)
        seg = src[i0:i1]
        assert ",'err')" not in seg, "expCsv 信息类 toast 仍挂 err 红边"
        # 三处直透点全部包裹
        for anchor in ("toast(j.err||'读取失败'", "toast(j.err||'预览失败'",
                       "toast(j.err||'启动失败'"):
            assert anchor not in src, f"j.err 直透点未包裹：{anchor}"

    # ---- P2-8 日历格日期格式 ----

    def test_cal_date_slash(self):
        src = self._src()
        i0 = src.index('<div class="cd">')
        seg = src[max(0, i0 - 80):i0 + 80]
        # 格面日期走 dSlash 单源（内联换装收口后的形态，语义不变）
        assert "dSlash(d)" in seg, "日历格日期未统一斜杠轨"


# ---- merged from tests/test_v191_webui.py ----

class TestWebuiV191Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    def test_hcells_touch_target_not_clipped(self):
        """P1-1：.hcells 容器 padding 外衬+margin 回收+pointer-events
        穿透，.hc::after 37px 热区不被 overflow 裁剪。y 轴显式 hidden
        （overflow-x:auto 会把 overflow-y 计算值强制成 auto，hover 放大
        曾让纵滚条闪现全行重排）。"""
        src = self._src()
        assert (".hcells{display:flex;gap:2px;flex:1;overflow-x:auto;"
                "overflow-y:hidden;"
                "padding:11px 0;margin:-9px 0;pointer-events:none}") in src, \
            ".hcells 外衬修法缺失（热区仍被 overflow 裁剪）"
        assert ".hcells .hc{pointer-events:auto}" in src, \
            ".hc 本体 pointer-events 恢复缺失"
        assert ".hc::after{content:'';position:absolute;inset:-11px -1px}" \
            in src, ".hc::after 热区声明被误动"

    def test_mkact_all_comment_honest(self):
        """P2-1：键盘可达选择器说明注释与 mkactAll 真实选择器一致
        （.calcell 不在选择器内，不得写进注释成员清单）。"""
        src = self._src()
        assert ".calcell/.plitem/.dx" not in src, \
            "mkactAll 注释仍声称覆盖 .calcell（注释债未清）"
        assert ("[role=\"button\"],span[onclick],.mtab,#tabs span[data-f],"
                ".cnav,.plitem,.dx,.tg") in src, \
            "mkactAll 选择器本体被误动"

    def test_aria_sort_none_on_inactive_columns(self):
        """P2-2：表头排序态 aria-sort 三值完整——非激活列显式
        aria-sort="none"，激活列 ascending/descending 保留。"""
        src = self._src()
        assert ("aria-sort=\"${SORT.k===k?(SORT.dir>0?'ascending':"
                "'descending'):'none'}\"") in src, \
            "表头 aria-sort 未三值化（非激活列缺 none）"
        assert "'ascending':'descending'" in src, \
            "激活列排序态词面被误动"

    def test_calendar_hot_cell_no_opacity_tax(self):
        """P2-3：.cd/.cx 撤 0.85 opacity 税，qhit/qbrk 免税例外死码
        连带清理（无税基线上 opacity:1=默认值恒真）。"""
        src = self._src()
        assert ".calcell .cd{font-size:11px;font-weight:600}" in src, \
            ".cd 基线规则缺失（撤税形态不符）"
        assert (".calcell .cx{font-size:11px;margin-top:1px;"
                "font-variant-numeric:tabular-nums}") in src, \
            ".cx 基线规则缺失（撤税形态不符）"
        assert ".calcell .cd{font-size:11px;font-weight:600;opacity:.85}" \
            not in src and "tabular-nums;opacity:.85}" not in src, \
            "日历超线档 opacity 税残留"
        assert ".calcell.qhit .cd,.calcell.qhit .cx{opacity:1}" not in src \
            and ".calcell.qbrk .cd,.calcell.qbrk .cx{opacity:1}" not in src, \
            "免税例外死码残留"
