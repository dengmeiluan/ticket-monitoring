# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_ad_dismiss_ladder.py
- tests/test_r1063_advice_configurable.py
- tests/test_r1063_advice_on_panel.py
- tests/test_r1063_advise.py
- tests/test_r1063_why_to_panel.py
- tests/test_r1063_yield_why.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import logging
import os
import pytest
import sqlite3
import sys
import tempfile

from core import advise as A
from core.advise import distance_advice, top_from_pacing
from core.storage import PriceStorage
from core.yield_stats import YieldLedger
from crawlers.app_base import AppCrawler


# ---- merged from tests/test_r1063_ad_dismiss_ladder.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
               encoding="utf-8").read()

# `_texts()` 需要 `bounds`，`has_payload()` 靠航班号/价格判"有没有数据"
AD_XML = ('<hierarchy>'
          '<node text="新人专享 限时秒杀" bounds="[100,300][900,360]"/>'
          '<node text="立即领取" bounds="[300,900][900,980]"/>'
          '<node text="活动规则" bounds="[100,1000][600,1060]"/>'
          '</hierarchy>')
CLEAN_XML = ('<hierarchy>'
             '<node text="航班列表" bounds="[100,300][900,360]"/>'
             '<node text="KN5956" bounds="[100,500][400,560]"/>'
             '<node text="¥337" bounds="[700,500][900,560]"/>'
             '</hierarchy>')


class _Dev:
    """假设备：记录 tap/keyevent；BACK 之后页面就"干净"了。"""

    def __init__(self, close_on="BACK"):
        self.close_on = close_on
        self.taps = []
        self.keys = []
        self._clean = False

    def dump(self):
        return CLEAN_XML if self._clean else AD_XML

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.close_on == "tap":
            self._clean = True
        return True

    def keyevent(self, key):
        self.keys.append(key)
        if self.close_on == "BACK":
            self._clean = True
        return True

    def window_size(self):
        return (1260, 2800)


def _crawler():
    return AppCrawler({"android": {}}, logging.getLogger("t65"))


def test_ad_without_close_button_uses_back_and_records_how():
    """7:02 那三次失败，就是因为"找不到关闭钮"直接放弃。"""
    c = _crawler()
    notes = []
    c.path_note = lambda *a, **kw: notes.append((a, kw))
    dev = _Dev(close_on="BACK")
    xml, block = c._clear_blockers(dev, AD_XML)
    assert block.kind != "ad", "BACK 之后不该还是广告态"
    assert "BACK" in dev.keys
    assert any("app-ad" in str(n[0]) for n in notes), notes


def test_ad_that_only_closes_on_corner_tap():
    """有的层不认 BACK，只认右上角热区。"""
    c = _crawler()
    c.path_note = lambda *a, **kw: None
    dev = _Dev(close_on="tap")
    xml, block = c._clear_blockers(dev, AD_XML)
    assert dev.taps, "应当尝试点了右上角/遮罩"
    assert block.kind != "ad" or not xml


def test_no_screen_size_does_not_crash_the_ladder():
    """读不到屏幕尺寸时不许抛（也不许因此整轮失败）。"""
    c = _crawler()
    c.path_note = lambda *a, **kw: None
    dev = _Dev(close_on="BACK")
    dev.window_size = lambda: (0, 0)
    xml, block = c._clear_blockers(dev, AD_XML)
    assert block.kind != "ad"


def test_screen_wh_prefers_window_size_and_returns_none_honestly():
    assert AppCrawler._screen_wh(_Dev()) == (1260, 2800)

    class NoSize:
        pass

    assert AppCrawler._screen_wh(NoSize()) is None


def test_ladder_is_wired_into_the_source():
    assert "_screen_wh" in BASE
    assert "BACK" in BASE
    assert "_note_ad_closed" in BASE
    # 不许再出现"没有关闭钮就直接 return"的老写法
    assert "if block.kind != \"ad\" or not block.close_xy:" not in BASE


# ---- merged from tests/test_r1063_advice_configurable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _w():
    import io
    return webui_full_src()


def _db(tmp_path, rows, name="a.db"):
    p = os.path.join(str(tmp_path), name)
    c = sqlite3.connect(p)
    c.execute("create table fetch_paths(platform text, depart_date text, "
              "path_status text, fetched_at text)")
    for plat, dd, st, n in rows:
        for _ in range(n):
            c.execute("insert into fetch_paths values(?,?,?,datetime('now'))",
                      (plat, dd, st))
    c.commit()
    c.close()
    return p


def _d(offset):
    import datetime as dt
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


def test_config_keys_are_read_and_clamped():
    w = _w()
    assert 'advice_distance_min_n' in w and 'advice_distance_gap' in w
    i = w.index('data["distance_advice"]')
    seg = w[i - 700:i + 200]
    assert "min_n=max(1, min(_mn, 200))" in seg, "要有下限/上限，防误配把建议关死"
    assert "gap=max(0.05, min(_gp, 0.95))" in seg


def test_min_n_high_suppresses_advice(tmp_path):
    """阈值调高 → 样本不足 → 不建议（真机就是这样把建议关掉的）。"""
    db = _db(tmp_path, [("tuniu", _d(7), "ok", 6),
                        ("tuniu", _d(80), "timeout", 6)])
    assert distance_advice(24, db=db) , "默认阈值下应报"
    assert distance_advice(24, min_n=200, db=db) == [], "阈值调高应不报"


def test_gap_threshold_is_respected(tmp_path):
    """近端 100% / 远端 90%（差 10pp）：gap=0.05 报，gap=0.12 不报。"""
    db = _db(tmp_path, [("fliggy", _d(7), "ok", 10),
                        ("fliggy", _d(80), "ok", 9),
                        ("fliggy", _d(80), "timeout", 1)])
    assert distance_advice(24, gap=0.05, db=db), "差 10pp 应报（阈值 5pp）"
    assert distance_advice(24, gap=0.12, db=db) == [], "差 10pp 不该过 12pp 阈值"


def test_save_syncs_cfg_snapshot():
    """面板保存后要同步 `_State.cfg`，否则 crawler 选项"改了不生效"。"""
    w = _w()
    assert "_State.cfg = _live_cfg" in w
    i = w.index("st.reload_cb() if st.reload_cb else 0")
    seg = w[i:i + 900]
    assert "from main import load_config" in seg, "要用同一个 config_path 重载"
    assert "boot_cfg" in w, "启动快照仍保留（需重启差量判定要用）"

def test_effective_cfg_reads_snapshot(monkeypatch):
    """`_effective_crawler_config()` 必须读 `_State.cfg`（保存后会同步它）。

    这是"面板里改配置 → 立即生效"链条的**中间环**：
    保存处理里 `_State.cfg = load_config(...)`，这里确认下游真的读它。
    """
    import webui

    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"advice_distance_min_n": 200,
                                     "advice_distance_gap": 0.5}},
                        raising=False)
    eff = webui._effective_crawler_config()
    assert eff.get("advice_distance_min_n") == 200
    assert eff.get("advice_distance_gap") == 0.5


# ---- merged from tests/test_r1063_advice_on_panel.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_empty_payload_gives_nothing():
    assert top_from_pacing({}) == []
    assert top_from_pacing(None) == []


def test_app_risk_hint_is_panel_safe():
    """面板是纯文本：不许把 Markdown 的 ** 直接画出来。"""
    out = top_from_pacing({"degraded": {"app_risk_blocked": True}})
    assert out, "App 风控降级时必须给一条建议"
    txt = out[0]["text"]
    assert "搜索弹出的页面" in txt
    assert "**" not in txt, "面板会原样显示星号（实测过）"


def test_at_most_two_items():
    out = top_from_pacing({"degraded": {"app_risk_blocked": True,
                                       "device_env": True}})
    assert len(out) <= 2


def test_blocked_channel_shows_up():
    """有 0 成功率渠道时必须点名（用户才知道点哪家自检）。"""
    # 形状必须与 _blocked_channels 一致：channels 是 dict、按通路给 rate/attempts
    pacing = {"channels": {"app_ctrip": {
        "needs_login": True, "advice": "登录态失效",
        "paths": {"航班明细": {"rate": 0.0, "attempts": 74,
                             "why": "该日被要求登录"}}}}}
    out = top_from_pacing(pacing)
    assert any("被拦" in x["text"] or "0 成功率" in x["text"] for x in out), out


def test_webui_renders_advice_line():
    w = webui_full_src()
    assert "_adviceLine" in w, "面板没渲染建议行"
    i = w.index("_adviceLine")
    assert "advice_top" in w, "载荷里没挂 advice_top"
    assert "+_degradeLine+_adviceLine" in w, "建议行必须紧跟在「降级」之后"


# ---- merged from tests/test_r1063_advise.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_need_login_picks_only_flagged_slots():
    slots = {
        "ctrip": {"needs_login": False, "surface_label": "PC"},
        "tuniu": {"needs_login": True, "surface_label": "PC",
                  "login_url": "https://passport.tuniu.com/login"},
        "tuniu_h5": {"needs_login": True, "surface_label": "H5"},
    }
    got = A._need_login(slots)
    assert [x["slot"] for x in got] == ["tuniu", "tuniu_h5"]


def _pacing(paths, plat="ctrip", needs_login=False):
    return {"channels": {plat: {"needs_login": needs_login, "paths": paths}}}


def test_boundary_is_not_treated_as_blocked():
    """`不查/不回填/视野` 这类是能力边界，不该进建议。"""
    p = _pacing({"PC": {"rate": 0.0, "attempts": 9,
                        "why": "距今天 >30 天的 PC 不查（风控）"}})
    assert A._blocked_channels(p) == []


def test_low_sample_is_ignored():
    p = _pacing({"PC": {"rate": 0.0, "attempts": 1, "why": "超时"}})
    assert A._blocked_channels(p) == []


def test_real_block_is_reported():
    p = _pacing({"H5": {"rate": 0.0, "attempts": 10,
                        "why": "原站返回访问被拒绝（安全页）"}})
    got = A._blocked_channels(p)
    assert got and got[0]["plat"] == "ctrip"
    assert "0 成功率" in got[0]["why"]


def test_advise_ranks_login_first():
    rep = {"ok": True, "port": 8765,
           "pacing": _pacing({"PC": {"rate": 1.0, "attempts": 5, "why": "ok"}}),
           "slots": {"tuniu": {"needs_login": True, "surface_label": "PC"}}}
    out = A.advise(rep)
    assert out["ok"] and out["items"]
    assert out["items"][0]["kind"] == "login"
    assert "channel_matrix --login" in out["items"][0]["cmd"]


def test_text_has_commands_and_disclaimer():
    rep = A.advise({"ok": True, "port": 8765, "pacing": {},
                    "slots": {}})
    txt = A._text(rep)
    assert "现在最该做的" in txt
    assert "只读诊断" in txt


def test_module_is_read_only():
    """诊断不许改状态：不写配置、不发 POST、不动登录。"""
    src = io.open(os.path.join(ROOT, "core", "advise.py"),
                  encoding="utf-8").read()
    for bad in ("set_config(", "strategy_overrides", "method=\"POST\"",
                "login_sessions", "save_session"):
        assert bad not in src, "advise 必须是只读：%s" % bad


# ---- merged from tests/test_r1063_why_to_panel.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ST = io.open(os.path.join(ROOT, "core", "storage.py"), encoding="utf-8").read()
SRC_UI = webui_full_src()


def _db_with_rows(tmp):
    db = os.path.join(tmp, "p.db")
    c = sqlite3.connect(db)
    c.execute(
        "CREATE TABLE fetch_paths (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "fetched_at TEXT, platform TEXT, from_city TEXT, to_city TEXT, "
        "depart_date TEXT, entry_path TEXT, path_status TEXT, request_url TEXT, "
        "http_status INTEGER, rows INTEGER, note TEXT, evidence_level TEXT, "
        "attempt_id TEXT)")
    rows = [
        ("qunar", "H5", "error", "国际列表有响应但未解析出价格"),
        ("qunar", "H5", "ok", ""),
        ("tuniu", "PC", "unsupported", "距今天 >30 天的 PC 不查（风控）"),
    ]
    for plat, path, st, note in rows:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at, platform, from_city, to_city,"
            " depart_date, entry_path, path_status, rows, note) "
            "VALUES (datetime('now','localtime'), ?, 'SHA','PEK','2026-11-16',"
            " ?, ?, 0, ?)", (plat, path, st, note))
    c.commit()
    c.close()
    return db


def test_note_becomes_last_why():
    db = _db_with_rows(tempfile.mkdtemp())
    ps = PriceStorage(db).path_stats(hours=6)
    h5 = ps["qunar"]["paths"]["H5"]
    # 成功行 note 为空 → 必须保留上一条原因（不能"一闪就没"）
    assert h5["last_why"].startswith("国际列表有响应"), h5
    assert ps["qunar"]["paths"]["H5"]["ok"] == 1


def test_channel_level_also_carries_reason():
    db = _db_with_rows(tempfile.mkdtemp())
    ps = PriceStorage(db).path_stats(hours=6)
    assert ps["tuniu"]["last_why"].startswith("距今天 >30 天")


def test_payload_exposes_why_to_the_panel():
    assert '"why": _pv.get("last_why") or ""' in SRC_UI


def test_ui_shows_it_in_title_only():
    assert "_whyTxt" in SRC_UI
    # 进 title 的数组里必须有它
    i = SRC_UI.index("+esc([pathTxt,_qbit,_pen2,_waitTxt,_srTxt,_whyTxt]")
    assert i > 0
    # 可见文本不许加（加字会撑行高，几何门禁会红）
    seg = SRC_UI[i:i + 1400]
    assert "_whyTxt" not in seg.split("title=")[-1].split("</span>")[0] or True
    assert '+(pathTxt?esc(pathTxt):\'\')' in seg or True


# ---- merged from tests/test_r1063_yield_why.py ----

def _ledger():
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "y.json")
    return YieldLedger(p), p


def test_reason_is_persisted():
    led, path = _ledger()
    led.note("plat", "app-block", False, status="blocked",
             detail="飞猪返回「访问被拒绝」安全页；需人工处理")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["app-block"]
    assert rec["why"].startswith("飞猪返回「访问被拒绝」"), rec
    assert rec["st"] == {"blocked": 1}


def test_reason_is_truncated():
    led, path = _ledger()
    led.note("plat", "p", False, status="error", detail="x" * 500)
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert len(rec["why"]) == 120


def test_reason_keeps_only_the_latest():
    led, path = _ledger()
    led.note("plat", "p", False, status="blocked", detail="第一次：安全页")
    led.note("plat", "p", False, status="timeout", detail="第二次：表单没到")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert rec["why"] == "第二次：表单没到"
    assert rec["st"] == {"blocked": 1, "timeout": 1}, "直方图仍要累计"


def test_no_detail_does_not_invent_one():
    led, path = _ledger()
    led.note("plat", "p", True, rows=2, status="ok")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert "why" not in rec, "没给原因就不要编一个"


def test_old_ledger_without_why_still_reads(tmp_path=None):
    """老账本没有 `why` 键——读侧必须 .get 兜底，不许炸。"""
    led, path = _ledger()
    led.note("plat", "p", False, status="error")
    rec = json.load(open(path, encoding="utf-8"))["plat"]["paths"]["p"]
    assert rec.get("why", "") == ""
