# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_channel_dates.py
- tests/test_r1063_channel_matrix.py
- tests/test_r1063_channel_wait.py
- tests/test_r1063_insight_views.py
- tests/test_r1063_login_view.py
- tests/test_r1063_probe_app_channels.py
- tests/test_r1063_service_closed.py
- tests/test_r1063_service_state.py
- tests/test_r1063_tuniu_intl_pc.py
- tests/test_r368_channel_popup.py
- tests/test_r977_channel_health_surface_unity.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import datetime
import inspect
import io
import json
import logging
import os
import pytest
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webui

from core import channel_matrix as CM, failover as fo, service_state as sst
from core.pacing import Pacing
from crawlers.app_ctrip import AppCtripCrawler
from crawlers.base import is_service_closed_body
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_webui_channel.py ----

# ---- merged from tests/test_r1063_channel_dates.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = ("CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY, platform TEXT,"
          " entry_path TEXT, path_status TEXT, from_city TEXT, to_city TEXT,"
          " depart_date TEXT, attempt_id TEXT, fetched_at TEXT, rows INTEGER,"
          " note TEXT)")


def _mkdb(tmp_path):
    db = str(tmp_path / "d.db")
    c = sqlite3.connect(db)
    c.execute(SCHEMA)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        ("fliggy", "PC", "ok", "2026-11-16", 100),
        ("fliggy", "PC", "ok", "2027-01-29", 50),
        ("tuniu", "H5/API", "login", "2027-01-29", 0),
        ("tuniu", "PC", "unsupported", "2027-01-29", 0),
        ("tuniu", "H5/API", "ok", "2026-11-16", 30),
    ]
    for plat, path, st, d, r in rows:
        c.execute("INSERT INTO fetch_paths (platform, entry_path, path_status,"
                  " depart_date, fetched_at, rows) VALUES (?,?,?,?,?,?)",
                  (plat, path, st, d, now, r))
    c.commit()
    c.close()
    return db


def test_date_grid_counts_only_real_rows(tmp_path):
    rep = CM.date_coverage(12, db=_mkdb(tmp_path))
    assert rep["ok"], rep
    assert rep["grid"]["fliggy"]["2027-01-29"] == 50
    assert rep["grid"]["tuniu"]["2027-01-29"] == 0, "登录/不支持不算出数"
    assert rep["tries"]["tuniu"]["2027-01-29"] == 2, "但要记尝试次数"


def test_text_shows_zero_vs_dash(tmp_path):
    rep = CM.date_coverage(12, db=_mkdb(tmp_path))
    txt = CM._dates_text(rep)
    assert "0 = 该日期没拿到任何价" in txt
    # 途牛远日期有尝试但 0 行 → 显示 0；没尝试的日期显示 -
    line = next(l for l in txt.splitlines() if l.startswith("tuniu"))
    assert " 0" in line


def test_missing_db_reported():
    rep = CM.date_coverage(12, db="nope.db")
    assert rep["ok"] is False and "读不到" in rep["why"]


def test_cli_has_dates_flag():
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--dates" in src
    assert "def date_coverage(" in src and "def _dates_text(" in src


def test_path_kind_classification():
    assert CM.path_kind("PC·周历") == "calendar"
    assert CM.path_kind("窗历") == "calendar"
    assert CM.path_kind("PC·国际") == "list"
    assert CM.path_kind("PC") == "list"
    assert CM.path_kind("H5/API") == "list"
    assert CM.path_kind("QUERY") == "api"
    assert CM.path_kind("app-login") == "other"


def test_calendar_only_cell_is_starred(tmp_path):
    db = _mkdb(tmp_path)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO fetch_paths (platform, entry_path, path_status,"
              " depart_date, fetched_at, rows) VALUES"
              " ('tongcheng','窗历','calendar','2026-11-16',datetime('now'),47)")
    c.commit()
    c.close()
    rep = CM.date_coverage(12, db=db)
    txt = CM._dates_text(rep)
    assert "47*" in txt, txt
    assert "票面价" in txt, "必须解释 * 的含义（票面口径未拆税）"


def test_list_rows_are_not_starred(tmp_path):
    """列表/接口出数不该带 *（口径是含税价）。"""
    rep = CM.date_coverage(12, db=_mkdb(tmp_path))
    txt = CM._dates_text(rep)
    assert "50*" not in txt, txt


# ---- merged from tests/test_r1063_channel_matrix.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_state_from_rate():
    assert CM._derive_state(1.0, "") == "成功"
    assert CM._derive_state(0.87, "") == "时好时坏"
    assert CM._derive_state(0.45, "") == "时好时坏"


def test_state_from_reason_keywords():
    assert CM._derive_state(0, "需登录（97 分钟内不再重试）") == "需登录"
    assert CM._derive_state(0, "风控验证页") == "被拦"
    assert CM._derive_state(0, "本轮等待预算用尽（已 268s）") == "主动让位"
    assert CM._derive_state(0, "日期超出 App 视野") == "不支持"
    assert CM._derive_state(0, "返回「访问被拒绝」安全页") == "被拦"
    assert CM._derive_state(None, "") == "无数据"


def test_table_has_header_and_rows():
    rows = [
        {"plat": "fliggy", "path": "PC", "rate": 1.0, "n": 140,
         "state": "成功", "why": "sjipiao.fliggy.com 国际列表", "last_ok_at": ""},
        {"plat": "app_fliggy", "path": "app-login", "rate": 0, "n": 2,
         "state": "需登录", "why": "需登录（97 分钟内不再重试）", "last_ok_at": ""},
    ]
    txt = CM._table(rows)
    assert "渠道" in txt and "通路" in txt and "成功率" in txt
    assert "fliggy" in txt and "app-logging" not in txt
    assert "100%" in txt and "0%" in txt


def test_table_filter_by_plat():
    rows = [{"plat": "a", "path": "PC", "rate": 1.0, "n": 1, "state": "成功",
             "why": "", "last_ok_at": ""},
            {"plat": "b", "path": "PC", "rate": 0, "n": 1, "state": "需登录",
             "why": "", "last_ok_at": ""}]
    txt = CM._table(rows, "b")
    assert "b" in txt and "a " not in txt


def test_empty_rows_message():
    assert "没有数据" in CM._table([])


def test_no_hardcoded_ports_only_defaults():
    """允许通过 --port 指定，但默认探测 8765/8000/5000（别写死一个）。"""
    assert 8765 in CM.DEFAULT_PORTS
    assert len(CM.DEFAULT_PORTS) >= 2
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--plat" in src and "--json" in src


# ---- merged from tests/test_r1063_channel_wait.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
BASE = io.open(os.path.join(ROOT, "crawlers", "base.py"),
               encoding="utf-8").read()
QUNAR = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                encoding="utf-8").read()


def test_pacing_accumulates_channel_wait():
    p = Pacing({})
    p.note_chan_wait("qunar", 210.5)
    p.note_chan_wait("qunar", 20)
    p.note_chan_wait("", 99)          # 空渠道名：忽略
    p.note_chan_wait("ctrip", 0)      # 零：忽略
    ch = p.snapshot()["channels"]
    assert ch["qunar"]["waited_s"] == 230.5, ch.get("qunar")
    assert "waited_s" not in (ch.get("ctrip") or {})


def test_crawler_has_one_wait_meter():
    """统一抽象：闸门睡眠与渠道内部等待都走同一个记账入口。"""
    assert "def note_wait(self, sec)" in BASE
    assert "self.waited_s: float = 0.0" in BASE
    assert "self.note_wait(_slp)" in BASE, "path_gate 睡眠没记账"
    assert "self.note_wait(wait)" in QUNAR, "qunar 预算累计没同步进等待表"


def test_main_reports_wait_deltas():
    """读**增量**：读绝对值会重复累加（同一个渠道多查询）。"""
    assert "_wait_seen = {}" in MAIN
    assert "pac.note_chan_wait(c.name, _wd)" in MAIN
    assert "_wd = _wf - float(_wait_seen.get(c.name) or 0.0)" in MAIN


def test_health_row_shows_wait_without_changing_geometry():
    """等待读数塞进既有的 `.ev .e2` 那一行——另起一行会破坏行高门禁。"""
    assert "const _waitTxt=(()=>{" in SRC
    seg = SRC[SRC.index("const _waitTxt=(()=>{"):][:400]
    assert "if(!(w>0))return '';" in seg
    assert 'i class="e2k">等待</i>' in SRC
    assert "_pen2||_waitTxt" in SRC, "e2 的显示条件没带上等待"


# ---- merged from tests/test_r1063_insight_views.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _w():
    return webui_full_src()


def test_insight_route_defined_and_query_tolerant():
    w = _w()
    assert 'self.path.split("?")[0] == "/api/insight"' in w, \
        "路由必须容忍 query（?view=ms&hours=24）"
    i = w.index('self.path.split("?")[0] == "/api/insight"')
    seg = w[i:i + 1200]
    assert "_cm.dist_table" in seg and "_cm.ms_table" in seg, \
        "必须复用 channel_matrix 的现成实现，不要重写查询"


def test_frontend_links_and_global_functions():
    w = _w()
    assert "showInsight" in w and "hideInsight" in w
    assert "通路耗时" in w and "距离分桶" in w
    assert 'id="insightBox"' in w, "要有容器"
    # 顶层函数（onclick 只能解析全局名）
    for fn in ("async function showInsight(", "function hideInsight("):
        i = w.index(fn)
        line_start = w.rfind("\n", 0, i) + 1
        assert w[line_start:i] == " ", "%s 必须是顶层函数" % fn


def test_insight_defined_before_early_return():
    """`_insight` 必须定义在「无更新」早退分支**之前**（真机踩过的空白页）。"""
    w = _w()
    i_def = w.index("const _insight = '<span class=\"muted\"")
    i_ret = w.index("if(!u||!u.latest){")
    assert i_def < i_ret, "_insight 定义落在早退之后 → 该分支 ReferenceError"


def test_insight_api_live_if_server_up():
    """有实例在跑就顺手验一次真实响应（没有则跳过）。"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:8765/api/insight?view=dist&hours=24",
                timeout=20) as r:
            d = json.loads(r.read().decode() or "{}")
    except (urllib.error.URLError, OSError):
        return
    assert d.get("ok") is True, d
    assert isinstance(d.get("lines"), list) and d["lines"], d
    assert "距离" in d.get("title", "") + "".join(d["lines"][:2])



def _live_ui_enabled():
    """实时 UI 检查需显式开关（默认跳过，避免给别处制造噪音）。"""
    return os.environ.get("TM_LIVE_UI") == "1"


# ---- merged from tests/test_r1063_login_view.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROWS = [
    {"slot": "ctrip", "surface": "PC", "status": "available", "needs": False,
     "block": "-", "verified": "", "url": "https://passport.ctrip.com/user/login"},
    {"slot": "tuniu", "surface": "PC", "status": "login_required", "needs": True,
     "block": "-", "verified": "", "url": "https://passport.tuniu.com/login"},
    {"slot": "tuniu_h5", "surface": "H5", "status": "login_required",
     "needs": True, "block": "login", "verified": "",
     "url": "https://m.tuniu.com/flight/"},
]


def test_login_text_lists_slots_and_needs():
    txt = CM._login_text({"ok": True, "rows": ROWS})
    assert "槽位" in txt and "端" in txt and "登录入口" in txt
    assert "需登录" in txt and "空闲" in txt
    assert "需要登录：tuniu、tuniu_h5" in txt, txt


def test_login_text_all_good():
    rows = [dict(r, needs=False, status="available") for r in ROWS]
    txt = CM._login_text({"ok": True, "rows": rows})
    assert "需要登录：无 ✓" in txt, txt


def test_login_text_offline():
    txt = CM._login_text({"ok": False, "rows": [], "why": "连不上实例：x"})
    assert txt.startswith("✗")


def test_login_state_mapping_has_core_states():
    for k in ("saved", "available", "login_required", "challenge"):
        assert k in CM.SLOT_STATE_CN


def test_cli_exposes_login_flag():
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--login" in src
    assert "def login_slots(" in src and "def _login_text(" in src


# ---- merged from tests/test_r1063_probe_app_channels.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_last_block_url_use_is_guarded():
    """`last_block_url` 是浏览器专属字段，出现处必须 getattr 保护。"""
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    for m in re.finditer(r"[^\n]*\.last_block_url[^\n]*", src):
        line = m.group(0)
        if line.strip().startswith("#"):
            continue
        assert 'getattr(c, "last_block_url"' in line or \
            "getattr(" in line, "未保护的 last_block_url：%s" % line.strip()


def test_probe_result_includes_blocked_url_safely():
    """探针结果里仍要有 blocked_url（浏览器渠道用得到），但缺字段不能炸。"""
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert '"blocked_url": (getattr(c, "last_block_url", "") or "")[:120]' \
        in src


def test_app_crawlers_lack_browser_only_fields():
    """确认前提：App 爬虫确实没有 last_block_url（这正是当初崩的原因）。"""
    from crawlers.app_ctrip import AppCtripCrawler
    from crawlers.app_fliggy import AppFliggyCrawler
    for cls in (AppCtripCrawler, AppFliggyCrawler):
        assert not hasattr(cls, "last_block_url"), cls


# ---- merged from tests/test_r1063_service_closed.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = ('{"ret":true,"code":1,"data":{"asyncComplete":true,"errorMsg":'
        '"服务调整通知：去哪儿旅行网页版机票查询及预订服务已停止提供，'
        '请前往去哪儿旅行 App 查询、预订机票。"}}')


def test_detects_the_real_qunar_payload():
    closed, why = is_service_closed_body([REAL.encode()])
    assert closed is True
    assert "停止提供" in why


def test_login_page_prompt_is_not_a_service_closure():
    """登录页也常写「请下载 App」——不能误判成停服（那会白退役一条活通路）。"""
    assert is_service_closed_body(["请下载 App 查看更低价"])[0] is False


def test_normal_page_is_not_closed():
    assert is_service_closed_body(["<div>KN5956 ¥337</div>"])[0] is False
    assert is_service_closed_body([])[0] is False


def test_switch_policy_covers_closures_and_blocks():
    assert fo.is_switch_worthy("captcha") is True       # 行为型被拦
    assert fo.is_switch_worthy("service_closed") is True  # 停服（App 唯一通路）
    assert fo.is_switch_worthy("empty") is False        # 无票：不用换
    assert fo.is_service_closed("service_closed") is True
    assert fo.is_service_closed("captcha") is False


def test_main_uses_switch_worthy():
    main = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "is_switch_worthy(_kind0)" in main
    # 老写法（只认行为型）不许回退
    assert "if _fo.is_behavior_block(_kind0):" not in main


def test_qunar_marks_closure_as_unsupported_not_error():
    q = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                encoding="utf-8").read()
    assert "is_service_closed_body" in q
    i = q.index("is_service_closed_body")
    seg = q[i:i + 1200]
    assert '"H5", "unsupported"' in seg, "停服必须记 unsupported（不算失败）"
    assert 'note("service_closed"' in seg, "停服要进降级账本（面板才看得见）"


def test_panel_knows_the_new_capability():
    w = webui_full_src()
    assert "service_closed:'通路停服'" in w
    assert "service_closed:'这家网页版已停服" in w

def test_closed_memo_survives_instances():
    """停服记忆要落盘、跨实例有效（否则每次重启又白跑一轮）。"""
    import logging
    import os
    import tempfile
    import time

    from crawlers.qunar import QunarCrawler

    tmp = tempfile.mkdtemp()
    c = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t67"))
    assert c.service_closed_until() == 0.0
    c.mark_service_closed("服务已停止提供")
    assert c.service_closed_until() > time.time()
    assert os.path.exists(c.service_closed_path())
    c2 = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t67"))
    assert c2.service_closed_until() > time.time(), "新实例必须记得"


def test_closed_memo_short_circuits_fetch():
    """记住停服后，`fetch` 必须**不碰网络**、立刻返回并记 unsupported。

    一次查询百秒级——明知停服还去跑是纯浪费（今天 qunar 成功率 6.5% 就是这么来的）。
    """
    import logging
    import tempfile
    import time

    from crawlers.qunar import QunarCrawler

    tmp = tempfile.mkdtemp()
    c = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t67"))
    c.mark_service_closed("服务已停止提供")
    notes = []
    real_note = c.path_note
    c.path_note = lambda *a, **kw: notes.append((a, kw)) or real_note(*a, **kw)
    t0 = time.time()
    rows = c.fetch("SHA", "SIN", ["2026-11-20"])
    assert rows == []
    assert time.time() - t0 < 3, "停服窗口内不该再去跑（实测一次 137s）"
    assert any("unsupported" in str(n[0]) for n in notes), notes
    assert any("已停服" in str(n[1].get("detail", "")) for n in notes), notes

def test_permanent_closure_is_recorded_and_never_probes():
    """用户确认去哪儿网页版是**永久**停服 → 记忆 100 年，不再白探。"""
    import json
    import logging
    import tempfile
    import time

    from crawlers.qunar import QunarCrawler

    tmp = tempfile.mkdtemp()
    c = QunarCrawler({"user_data_dir": tmp}, logging.getLogger("t68"))
    c.mark_service_closed("网页版永久停服", permanent=True)
    assert c.service_closed_until() - time.time() > 3000 * 86400, "应是永久窗口"
    with open(c.service_closed_path(), encoding="utf-8") as f:
        rec = json.load(f)
    assert rec.get("permanent") is True and rec.get("detail")


def test_setup_check_distinguishes_retired_from_unsubscribed():
    """`qunar` 是"已退役（停服）"，不该再显示成"想采就加上"。"""
    import json
    import os
    import tempfile
    import time

    from core import setup_check as sc

    root = tempfile.mkdtemp()
    d = os.path.join(root, "user_data", "qunar")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "service_closed.json"), "w",
              encoding="utf-8") as f:
        json.dump({"until": time.time() + 86400 * 365, "permanent": True}, f)
    assert sc._is_retired(root, "qunar") is True
    assert sc._is_retired(root, "fliggy") is False
    # 临时停服（非 permanent）不算退役
    d2 = os.path.join(root, "user_data", "tuniu")
    os.makedirs(d2, exist_ok=True)
    with open(os.path.join(d2, "service_closed.json"), "w",
              encoding="utf-8") as f:
        json.dump({"until": time.time() + 3600, "permanent": False}, f)
    assert sc._is_retired(root, "tuniu") is False


def test_close_memo_lives_on_the_base_class():
    """一处实现、一个口径：qunar 不再自带一套 `_sc_*`。"""
    import os

    from crawlers.base import BaseCrawler

    for name in ("service_closed_path", "service_closed_until",
                 "mark_service_closed", "service_closed_skip"):
        assert hasattr(BaseCrawler, name), name
    q = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                encoding="utf-8").read()
    assert "def _sc_until" not in q, "qunar 不该再有自己的实现"
    assert "self.mark_service_closed(_closed, permanent=True)" in q


# ---- merged from tests/test_r1063_service_state.py ----

@pytest.fixture(autouse=True)
def _clean():
    yield
    sst.clear(tempfile.gettempdir(), "probe", "login_wall")


def test_mark_until_clear_roundtrip():
    root = tempfile.mkdtemp()
    assert sst.until(root, "x", "login_wall") == 0.0
    sst.mark(root, "x", "login_wall", "需登录", window_s=60)
    assert sst.until(root, "x", "login_wall") > time.time()
    assert "需登录" in sst.detail(root, "x", "login_wall")
    sst.clear(root, "x", "login_wall")
    assert sst.until(root, "x", "login_wall") == 0.0


def test_permanent_flag_is_recorded():
    root = tempfile.mkdtemp()
    sst.mark(root, "x", "service_closed", "永久停服", permanent=True)
    assert sst.is_permanent(root, "x", "service_closed") is True
    assert sst.until(root, "x", "service_closed") - time.time() > 3000 * 86400


def test_kinds_use_separate_files():
    root = tempfile.mkdtemp()
    sst.mark(root, "x", "login_wall", "a")
    assert sst.until(root, "x", "service_closed") == 0.0
    assert os.path.basename(sst.path_for(root, "x", "login_wall")) == \
        "login_wall.json"


def test_broken_file_is_treated_as_absent():
    root = tempfile.mkdtemp()
    p = sst.path_for(root, "x", "login_wall")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ 不是 json")
    assert sst.until(root, "x", "login_wall") == 0.0      # 不抛


def test_app_crawler_has_the_shared_memo():
    c = AppCtripCrawler({"user_data_dir": tempfile.mkdtemp(), "android": {}},
                        logging.getLogger("t69"))
    for name in ("service_closed_until", "mark_service_closed",
                 "service_closed_skip", "login_wall_until", "mark_login_wall",
                 "login_wall_skip", "clear_login_wall", "early_skip"):
        assert hasattr(c, name), name


def test_login_wall_makes_fetch_return_instantly():
    """没登录时不该每轮白跑 81 秒——窗口内必须 0 秒返回。"""
    c = AppCtripCrawler({"user_data_dir": tempfile.mkdtemp(), "android": {}},
                        logging.getLogger("t69"))
    c.mark_login_wall("页面停在登录墙")
    notes = []
    c.path_note = lambda *a, **kw: notes.append((a, kw))
    t0 = time.time()
    assert c.fetch("SHA", "PEK", ["2026-11-16"]) == []
    assert time.time() - t0 < 3, "登录墙窗口内不该再去跑（实测一次 81 秒）"
    assert notes and notes[0][0][1] == "login", (
        "状态必须是 login（健康页显示需登录），不是 paced/error", notes)


def test_login_wall_is_cross_instance_and_clearable():
    root = tempfile.mkdtemp()
    a = AppCtripCrawler({"user_data_dir": root, "android": {}},
                        logging.getLogger("t69"))
    a.mark_login_wall("x")
    b = AppCtripCrawler({"user_data_dir": root, "android": {}},
                        logging.getLogger("t69"))
    assert b.login_wall_until() > time.time(), "新实例必须记得"
    b.clear_login_wall()
    assert b.login_wall_until() == 0.0


def test_every_app_channel_calls_early_skip():
    """五家 App 渠道的 fetch 开头都要上闸（否则登录墙记忆对它们没用）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("app_ctrip.py", "app_fliggy.py", "app_qunar.py",
                 "app_tongcheng.py", "app_zhixing.py"):
        src = io.open(os.path.join(root, "crawlers", name),
                      encoding="utf-8").read()
        assert "self.early_skip(dates)" in src, name


# ---- merged from tests/test_r1063_tuniu_intl_pc.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _c(cfg=None):
    return TuniuCrawler(cfg or {}, logging.getLogger("t"))


def test_intl_pc_url_one_way():
    url = TuniuCrawler.intl_pc_url("SHA", "SEL", "2026-11-10")
    assert url == ("https://flight.tuniu.com/intl/list/"
                   "SHA_SEL_1_0_0?deptDate=2026-11-10&type=1&cabinClass=0")


def test_intl_pc_url_round_trip_has_arrv():
    url = TuniuCrawler.intl_pc_url("SHA", "SEL", "2026-11-10", "2026-11-14")
    assert "type=2" in url and "arrvDate=2026-11-14" in url


def test_parse_intl_pc_items_extracts_price_and_times():
    c = _c()
    items = ["东航 MU5603 10:15 16:30 中转1次 ¥2253 往返含税价",
             "南航 11:40 20:50 8h10m ¥2563",
             "没有价格的噪音行"]
    rows = c._parse_intl_pc_items(items, "2026-11-10")
    # 形状与国内 `_parse_pc_items` 一致（dict），上层共用同一份转 FlightPrice 逻辑
    assert len(rows) == 2, rows
    assert rows[0]["price"] == 2253
    assert rows[0]["depTime"] == "10:15" and rows[0]["arrTime"] == "16:30"
    assert "东航" in rows[0]["name"]
    assert rows[0]["depDate"] == "2026-11-10"


def test_switch_default_on_and_can_be_off():
    assert _c()._intl_pc_enabled() is True
    assert _c({"tuniu_intl_pc": False})._intl_pc_enabled() is False


def test_fetch_prefers_pc_then_falls_back():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("if is_intl_route(from_city, to_city):")
    seg = src[i:i + 1600]
    assert "_fetch_intl_pc" in seg, "国际必须先走 PC 页"
    assert "remain" in seg and "_fetch_intl(" in seg, "缺的日期要回退 H5/API"


def test_path_label_is_independent_dimension():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    assert '"PC·国际"' in src, "国际 PC 必须作为独立通路进账本/面板"


def test_empty_page_is_retried():
    """国际页会间歇性整页空白（国内实测同一 URL 5 次里 3 次正常）。

    空页必须重载一次，否则一次抽风就白丢一天数据。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("def _fetch_intl_pc")
    seg = src[i:i + 2600]
    assert "for _attempt in range(2)" in seg, "缺少空页重载重试"
    assert "PC 页空，重载重试" in seg


# ---- merged from tests/test_r368_channel_popup.py ----

def test_channel_chip_uses_popup_helper():
    src = webui.PAGE
    assert "function srxOpenChannel(url,ev)" in src
    assert "window.open(url,name,'popup,width=1200" in src
    assert 'onclick="return srxOpenChannel(this.href,event)"' in src
    # modifier clicks keep the native new-tab path
    assert "if(ev&&(ev.ctrlKey||ev.metaKey||ev.shiftKey))return true" in src


def test_special_deal_open_uses_popup_helper():
    src = webui.PAGE
    assert 'onclick="return srxOpenChannel(this.href,event)">打开' in src


# ---- merged from tests/test_r977_channel_health_surface_unity.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui.PAGE


def test_diag_platforms_include_channels_seen_in_24h_stats():
    """诊断卡的渠道集合必须并入近 24h stats 出现过的渠道（含 App）。"""
    import webui
    body = inspect.getsource(webui._health_decorate)
    assert 'out.get("stats")' in body, "诊断卡又只看最近一轮 plats，App 渠道会从卡上消失"
    assert "_diag_platforms(_plats)" in body, "诊断卡没有把并集交给 _diag_platforms"
    # 负控：旧实现只写 `_diag_platforms(_plats)` 而 _plats 仅取 rounds[-1]
    assert "for _p, _st in (out.get(\"stats\") or {}).items()" in body, \
        "stats 并集循环不见了"


def test_classify_round_emits_a_card_for_every_registered_app_channel():
    from core.health_diag import classify_round
    plats = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu",
             "app_zhixing", "app_qunar", "app_fliggy", "app_ctrip", "app_tongcheng")
    cards = classify_round({}, all_plats=plats)
    assert [c["plat"] for c in cards] == list(plats)
    assert all(c.get("name") and c.get("label") for c in cards), \
        "有渠道卡缺中文名/状态，界面会露裸 id"


def test_pacing_uses_two_column_body_and_readable_trace_table():
    src = _src()
    assert 'class="pace-body"' in src, "节流面板又回到单列长墙"
    assert "Object.keys(PTH||{}).forEach" in src,         "重启后 App 渠道会从节流行消失；必须合并近 24h 分通路账"
    assert "v._no_round?'待首轮'" in src,         "合并进来的渠道不能冒充「正常」，必须标「待首轮」"
    assert "#paceBox .pace-body{display:grid" in src, "两栏布局规则不见了"
    assert "#paceBox .pace-tline>*{grid-area:auto!important}" in src, \
        "溯源表列又会被 grid-area 命名轨道顶乱"
    assert "#paceBox .pace-tline .u{grid-column:1/-1!important}" in src, \
        "URL 必须独占整行，不能挤进四列"


def test_filter_panel_has_one_collapse_entry_and_a_full_width_more_row():
    src = _src()
    # 面板头/尾不再各放一颗「收起/完成」，唯一收起入口是工具栏那颗
    head = src[src.index("const head='<div class=\"srf-head\""):]
    head = head[:head.index("const foot=")]
    assert 'data-srfclose="1"' not in head, "筛选面板头又出现第二颗收起"
    assert 'data-srfclose="1"' not in src[src.index("const foot='<div class=\"srf-foot\""):][:400], \
        "筛选面板底又出现「完成」第二颗收起"
    # 更多条件触发器独占整行、直接位于展开体之前
    i = src.index('id="srxMoreBtn"')
    j = src.index('id="srxFmore"')
    k = src.index('id="srxPlats"')
    assert k < i < j, "更多条件触发器应独占渠道行之后的一行"


def test_legacy_watch_channels_migrate_once_to_full_universe():
    """浏览器五家出厂默认的旧关注记录必须一次性升到全渠道。"""
    import webui
    full = list(webui._WATCH_PLATS)
    browser = [p for p in full if not str(p).startswith("app_")]
    assert len(full) > len(browser)
    assert webui._watch_channels(browser) == browser, "显式保存的浏览器五家不应被改写"
    assert set(webui._watch_channels(browser, migrate=True)) == set(full),         "旧关注记录没有迁移到 App 渠道，关注台覆盖仍是 /5"
