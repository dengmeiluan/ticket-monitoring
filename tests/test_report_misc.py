# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r240_render_dir.py
- tests/test_r306_daily_order.py
- tests/test_r317_report_state.py
- tests/test_r385_prov_passthrough.py
- tests/test_r805aq_report_app_channel.py
- tests/test_r926_tongcheng_intl_round_trip.py
- tests/test_v15121_webui.py
- tests/test_v15133_wd.py
- tests/test_v193_perf.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.notifier as notifier_mod
import datetime as _dt
import json
import json as _json
import logging
import os
import os as _os
import pytest
import re
import report
import sqlite3
import sqlite3 as _sq
import sys
import tempfile as _tf
import time as _time

from core.alerter import Alerter, _MKT_NOTE, _disp_dw
from core.models import FlightPrice, Route
from core.notifier import EmailNotifier, _local_push_image
from core.storage import PriceStorage
from crawlers.tongcheng import TongchengCrawler
from pathlib import Path
from report import _nice_ticks


# ---- merged from tests/test_r240_render_dir.py ----

class TestRenderDirHelper:
    def test_default_is_data(self, monkeypatch):
        from core.models import render_dir
        monkeypatch.delenv("TM_RENDER_DIR", raising=False)
        assert render_dir() == "data"

    def test_env_override(self, monkeypatch, tmp_path):
        from core.models import render_dir
        monkeypatch.setenv("TM_RENDER_DIR", str(tmp_path / "rend"))
        assert render_dir() == str(tmp_path / "rend")

    def test_empty_env_falls_back(self, monkeypatch):
        from core.models import render_dir
        monkeypatch.setenv("TM_RENDER_DIR", "")
        assert render_dir() == "data"


class TestRenderSitesConsumeHelper:
    """源码钉：四个渲染写点（alerter×2 + report×2）一律经 render_dir()
    构路径；裸 `data/` 图表字面零残留（notify 目录等非图表写点不在面）。"""

    @staticmethod
    def _src(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_alerter_no_bare_table_literal(self):
        import core.alerter as _a
        src = self._src(_a.__file__)
        assert "data/flights_table_" not in src
        assert src.count("render_dir()") >= 2

    def test_report_no_bare_table_or_trend_literal(self):
        import report as _r
        src = self._src(_r.__file__)
        assert "data/flights_table_" not in src
        # os.path.join("data", f"trend_ 形态的裸目录零残留
        assert '"data", f"trend_' not in src
        assert src.count("render_dir()") >= 2

    def test_models_exports_render_dir(self):
        import core.models as _m
        assert callable(_m.render_dir)


class TestConftestAutouseInjection:
    def test_autouse_fixture_redirects_render_dir(self):
        """autouse 夹具在场：本测试未显式 setenv，靠夹具注入后
        TM_RENDER_DIR 应已指向 tmp_path 且不在仓库内。"""
        cpath = os.path.join(os.path.dirname(__file__), "conftest.py")
        val = os.environ.get("TM_RENDER_DIR")
        assert val, "TM_RENDER_DIR 未被 autouse 夹具注入"
        # 源码钉：夹具对 TM_RENDER_DIR 的 setenv 在位
        with open(cpath, encoding="utf-8") as f:
            csrc = f.read()
        assert "TM_RENDER_DIR" in csrc

    def test_uitest_spawns_demo_with_redirect(self):
        """uitest 自包含脚本拉起的 demo 服务同样注入重定向
        （子进程经 env 继承，服务端渲染不落仓库 data/）。"""
        upath = os.path.join(os.path.dirname(__file__), os.pardir,
                             "tools", "uitest.py")
        with open(upath, encoding="utf-8") as f:
            usrc = f.read()
        assert "TM_RENDER_DIR" in usrc


# ---- merged from tests/test_r306_daily_order.py ----

RC = [
    {"from": "SHA", "to": "HAK", "dates": ["2027-01-29", "2027-01-30"]},
    {"from": "HAK", "to": "SHA", "dates": ["2027-02-13"]},
]


def test_return_trip_not_before_outbound():
    """返程小节（HAK→SHA）不得排到去程（SHA→HAK）前——旧字典序
    （H<S）下返程恒打头即本钉的复现形态。"""
    keys = [("HAK", "SHA", "2027-02-13"),
            ("SHA", "HAK", "2027-01-29"),
            ("SHA", "HAK", "2027-01-30")]
    ordered = sorted(keys, key=report._daily_route_key(RC))
    assert ordered == [("SHA", "HAK", "2027-01-29"),
                       ("SHA", "HAK", "2027-01-30"),
                       ("HAK", "SHA", "2027-02-13")]


def test_same_pair_dates_ascending():
    """同城市对多日期按日期升序（min 键同值时 date 末键兜序）。"""
    keys = [("SHA", "HAK", "2027-01-30"), ("SHA", "HAK", "2027-01-29")]
    ordered = sorted(keys, key=report._daily_route_key(RC))
    assert ordered == [("SHA", "HAK", "2027-01-29"),
                       ("SHA", "HAK", "2027-01-30")]


def test_unmatched_pair_falls_back_to_own_date():
    """无配置匹配的键（防御病理形态）退自身 date 作键首。"""
    ordered = sorted([("PEK", "SHA", "2027-03-01"),
                      ("SHA", "PEK", "2027-02-01")],
                     key=report._daily_route_key(RC))
    assert ordered == [("SHA", "PEK", "2027-02-01"),
                       ("PEK", "SHA", "2027-03-01")]


def test_section_loop_wired_to_order_key():
    """接线钉：build_and_push 小节循环必须带排序键（防回退纯字典序）。"""
    src = Path(report.__file__).read_text(encoding="utf-8")
    assert re.search(
        r"sorted\(list\(charts\) \+ _trendless,\s*key=", src), \
        "日报小节循环未挧行程时间序排序键"


@pytest.mark.parametrize("bad", [
    [("HAK", "SHA", "2027-02-13"), ("SHA", "HAK", "2027-01-29")],
])
def test_legacy_lexicographic_would_fail(bad):
    """变异自检：旧字典序形态喂给新键必须产生不同序（钉有咬合力）。"""
    assert sorted(bad, key=report._daily_route_key(RC)) != sorted(bad)


# ---- merged from tests/test_r317_report_state.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TITLE_ANCHOR = "价格走势与明细"


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """state 与账本双重定向出仓库（生产 data/ 零触碰）。"""
    monkeypatch.setenv("REPORT_STATE_FILE", str(tmp_path / "report_state.json"))
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(tmp_path / "push_history.jsonl"))
    return tmp_path


def _cfg():
    return {"users": [{"name": "日报演练",
                       "notifier": {"report_hour": 0, "digest": True},
                       "routes": []}]}


def _log():
    return logging.getLogger("r317_report_state")


def _notifier():
    class _N:
        last_errcode = None
    return _N()


def _ledger_line(ok, errcode=None, ch="dingtalk"):
    from datetime import datetime
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "ok": ok, "ch": ch,
           "title": "📈 %s｜%s" % (_TITLE_ANCHOR,
                                   datetime.now().strftime("%m/%d %H:%M")),
           "desp": "日报演练"}
    if errcode is not None:
        rec["errcode"] = errcode
    return json.dumps(rec, ensure_ascii=False)


def test_state_write_survives_midwrite_crash(iso, monkeypatch):
    """写中崩溃（序列化抛异常）旧 state 完好——tmp+os.replace 原子写；
    直接 open("w") 截断实现下旧 state 被毁=同文重推窗口。"""
    sp = iso / "report_state.json"
    sp.write_text(json.dumps({"日报演练": "2000-01-01"}),
                  encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    real_dump = json.dump

    def _boom(*a, **kw):
        raise OSError("模拟写中崩溃")

    monkeypatch.setattr(report.json, "dump", _boom)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    monkeypatch.setattr(report.json, "dump", real_dump)
    # 旧 state 完好（写中崩溃不毁既有落账）
    got = json.loads(sp.read_text(encoding="utf-8"))
    assert got.get("日报演练") == "2000-01-01", (
        "写中崩溃毁掉旧 state（同文重推窗口）： got=%r" % got)


def test_ledger_crosscheck_blocks_repush_when_state_lost(iso, monkeypatch):
    """state 键丢失但账本已有今日成功日报 → 补写 state 不重推。"""
    (iso / "push_history.jsonl").write_text(
        _ledger_line(True) + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert calls["n"] == 0, (
        "state 丢失且账本已有今日日报仍重推（10-13 双份日报形态）")
    sp = iso / "report_state.json"
    assert sp.exists(), "账本兜底路径未补写 state（明日防重发失锚）"
    got = json.loads(sp.read_text(encoding="utf-8"))
    from datetime import datetime
    assert got.get("日报演练") == datetime.now().strftime("%Y-%m-%d")


def test_ledger_ghost_minus1_counts_as_pushed(iso, monkeypatch):
    """账本今日 -1 幽灵行（ok=False+errcode=-1）=已推两态之一 → 不重推
    （与「-1 幽灵按已推落账」守卫语义精确同构）。"""
    (iso / "push_history.jsonl").write_text(
        _ledger_line(False, errcode=-1) + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert calls["n"] == 0, "账本 -1 幽灵行未按已推拦截，重推同文日报"


def test_ledger_network_err_keeps_retry(iso, monkeypatch):
    """账本今日网络异常行（ok=False 无 errcode）≠已推 → 正常重试语义
    保留（防交叉校验过度拦截「防丢失由下轮自然补」路径）。"""
    (iso / "push_history.jsonl").write_text(
        _ledger_line(False) + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _fake_push(cfg, logger, notifier, user=""):
        calls["n"] += 1
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert calls["n"] == 1, "网络异常行被误判已推，丢失了重试语义"


def test_multiuser_ledger_check_disabled(iso, monkeypatch):
    """Soldier M1：账本行无 user 维度——≥2 用户时校验诚实禁用，
    第二用户的日报不被首用户的账本行误吞。"""
    cfg = {"users": [
        {"name": "甲", "notifier": {"report_hour": 0, "digest": True},
         "routes": []},
        {"name": "乙", "notifier": {"report_hour": 0, "digest": True},
         "routes": []}]}
    (iso / "push_history.jsonl").write_text(
        _ledger_line(True) + "\n", encoding="utf-8")
    seen = []

    def _fake_push(cfg, logger, notifier, user=""):
        seen.append(user)
        return True

    monkeypatch.setattr(report, "build_and_push", _fake_push)
    report.maybe_daily_report(cfg, _log(), _notifier(), user="乙")
    assert seen == ["乙"], "多用户下账本行误吞了第二用户的日报：seen=%r" % seen


def test_state_hit_skips_ledger_scan(iso, monkeypatch):
    """Soldier m1：state 命中短路在先——稳态命中不扫账本
    （每轮白扫 4160 行 + 重写 state + INFO 刷屏的次优序退役）。"""
    from datetime import datetime
    sp = iso / "report_state.json"
    sp.write_text(json.dumps(
        {"日报演练": datetime.now().strftime("%Y-%m-%d")}), encoding="utf-8")
    scanned = {"n": 0}
    real = report._ledger_has_today_report

    def _spy(today):
        scanned["n"] += 1
        return real(today)

    monkeypatch.setattr(report, "_ledger_has_today_report", _spy)
    report.maybe_daily_report(_cfg(), _log(), _notifier(), user="日报演练")
    assert scanned["n"] == 0, "state 命中仍扫账本（次优序未退役）"


# ---- merged from tests/test_r385_prov_passthrough.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_user_state_query_selects_prov():
    src = webui_full_src()
    i = src.index("def _user_state(u):")
    seg = src[i:i + 3000]
    assert 'PRAGMA table_info(flight_prices)' in seg, "未按库结构自适应 prov 列"
    assert '", prov" if _has_prov else ""' in seg, "当轮明细 SQL 未取 prov"
    assert '_has_prov else ""' in seg and '["prov"]' in seg, "prov 未随行透传"


def test_recent_platform_flights_selects_and_attaches_prov():
    src = _src("report.py")
    i = src.index("def recent_platform_flights(")
    seg = src[i:i + 4000]
    assert '", prov" if _has_prov else ""' in seg, "补位 SQL 未取 prov"
    assert '_it["_prov"] = r["prov"] or ""' in seg


def test_fallback_merge_carries_prov_into_pool():
    src = webui_full_src()
    i = src.index("_state_stale_hours()).items():")
    seg = src[i:i + 1400]
    assert 'g["_prov"] = f.get("_prov")' in seg, "补位合并未携带 prov"


def test_prov_reaches_api_payload(tmp_path, monkeypatch):
    """端到端：真实一行带 prov → recent_platform_flights 原样带回。

    不依赖“当前时间窗”（pytest 会话里其他用例会改时区/时钟），
    直接把窗口放宽到 100 年，只验证 prov 的透传。"""
    import json as _j
    from datetime import datetime, timedelta
    import report
    db = str(tmp_path / "p.db")
    c = sqlite3.connect(db)
    c.execute(
        "CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, platform TEXT, "
        "from_city TEXT, to_city TEXT, depart_date TEXT, price REAL, "
        "airline TEXT, flight_no TEXT, depart_time TEXT, arrive_time TEXT, "
        "fetched_at TEXT, extra TEXT, prov TEXT)")
    extra = _j.dumps([{"price": 662, "depTime": "08:05", "arrTime": "12:30",
                       "code": "MU501", "depDate": "2026-11-16"}])
    prov = _j.dumps({"entryPath": "PC", "pathStatus": "ok", "kind": "detail"})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO flight_prices (platform,from_city,to_city,"
              "depart_date,price,airline,flight_no,depart_time,arrive_time,"
              "fetched_at,extra,prov) VALUES "
              "('ctrip','SHA','BKK','2026-11-16',662,'','MU501','08:05',"
              "'12:30',?,?,?)", (now, extra, prov))
    c.commit()
    c.close()
    # conftest 的 _isolate_recent_flights 会把模块函数替换成 {}（防测试
    # 读生产库）；这里要测函数本体，走同仓惯例的 raw 别名。
    fn = getattr(report, "_recent_platform_flights_raw",
                 report.recent_platform_flights)
    out = fn(db, "SHA", "BKK", "2026-11-16", hours=24 * 365 * 100)
    assert "ctrip" in out, out
    _age, rows = out["ctrip"]
    assert rows and rows[0]["_prov"] == prov
    assert rows[0]["_row_id"] == 1


# ---- merged from tests/test_r805aq_report_app_channel.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _render_and_collect(tmpdir, rows):
    """渲染一次并把 `_fit_text` 的 (text, x, y) 全记下来。"""
    import report
    calls = []
    orig = report._fit_text

    def spy(d, text, x, y, max_w, base=15, fill=None, min_size=11,
            anchor="lm"):
        calls.append((str(text), round(float(x), 2), round(float(y), 2)))
        return orig(d, text, x, y, max_w, base=base, fill=fill,
                    min_size=min_size, anchor=anchor)

    report._fit_text = spy
    try:
        report.render_flights_table(
            rows, "probe", out_path=os.path.join(tmpdir, "probe.png"))
    finally:
        report._fit_text = orig
    return calls


def _mk(plat, no, price):
    return {"_platform": plat, "airline": "东航", "flightNo": no,
            "depTime": "08:00", "arrTime": "10:30", "fromCity": "上海",
            "toCity": "北京", "price": price, "direct": True,
            "totalDuration": "2h30m", "qual": True, "date": "2026-12-01"}


def _rows():
    return [("direct", [_mk("ctrip", "MU5101", 800),
                        _mk("app_zhixing", "CA1501", 820)])]


def test_report_dot_covers_every_channel():
    import report
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    for p in list(BROWSER_CHANNELS) + list(APP_CHANNELS):
        assert p in report.PLAT_DOT, (
            "%s 在报告里没有配色：圆点不画、渠道名会左移 14px" % p)


def test_app_channel_shows_chinese_name_aligned_with_browser(tmpdir):
    calls = _render_and_collect(str(tmpdir), _rows())
    xs = {}
    for t, x, _y in calls:
        if t in ("携程", "智行 App"):
            xs.setdefault(t, set()).add(x)
    assert "智行 App" in xs, (
        "报告里没有中文名「智行 App」——多半又印成裸 id 了。实际渠道列文字：%s"
        % [c[0] for c in calls if c[0] not in ("", "probe", "08:00",
                                              "—", "2h30m", "￥800",
                                              "￥820")][:8])
    assert "app_zhixing" not in [c[0] for c in calls], (
        "报告里出现裸 id `app_zhixing`，应显示「智行 App」")
    assert xs["携程"] == xs["智行 App"], (
        "App 行的渠道名与浏览器行不在同一 x：携程 %s vs 智行 %s"
        % (sorted(xs["携程"]), sorted(xs["智行 App"])))


def test_channel_text_alignment_does_not_depend_on_color(tmpdir):
    """抽掉 App 配色后，渠道名 x 必须保持不变。

    这条守的是**结构**：文字起点不能由「这渠道有没有配色」决定。
    没有这条，将来新增一个还没配色的渠道就会再左移一次 14px，
    而「有配色的渠道」看起来永远是对的。
    """
    import report
    saved = report.PLAT_DOT.pop("app_zhixing")
    try:
        calls = _render_and_collect(str(tmpdir), _rows())
    finally:
        report.PLAT_DOT["app_zhixing"] = saved
    xs = {}
    for t, x, _y in calls:
        if t in ("携程", "智行 App"):
            xs.setdefault(t, set()).add(x)
    assert xs.get("智行 App"), "抽掉配色后 App 渠道名没渲染出来"
    assert xs["携程"] == xs["智行 App"], (
        "没有配色时 App 行左移了：携程 %s vs 智行 %s（圆点列必须恒定预留）"
        % (sorted(xs["携程"]), sorted(xs["智行 App"])))


# ---- merged from tests/test_r926_tongcheng_intl_round_trip.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "tongcheng_intl_rt.json")


def _payload():
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)


def test_parser_uses_channel_total_not_sum():
    p = _payload()
    date, ret = "2026-11-20", "2026-11-23"
    rows = [TongchengCrawler._parse_intl_rt_entry(e, date, ret)
            for e in p["data"]["res"]]
    rows = [r for r in rows if r]
    assert len(rows) >= 40, "真实报文应解析出 40+ 条往返"
    best = min(rows, key=lambda r: r["price"])
    assert best["price"] == 1463.0
    assert best["flight"] == "HX231"
    assert best["returnFlight"] == "HX0234"
    assert best["basis"] == "product_round_trip_total"
    assert best["priceLabel"] == "往返含税总价"
    assert best["tripType"] == "RT"
    # 报表/明细消费端的标准键必须齐全，否则新往返行会在趋势/详情里变空白
    assert best["depTime"] == "07:40" and best["arrTime"] == "10:40"
    assert best["code"] == "HX231" and best["name"] == "香港航空"
    assert best["intl"] is True and best["date"] == "2026-11-20"
    assert best["totalBasis"] == "product_round_trip_total"
    # 进入告警/趋势同一行归一化链后，时刻/航班/国际标记不能丢
    from core.alerter import _flights_from_extra
    fl = _flights_from_extra(rows, date, "tongcheng")
    assert len(fl) == len(rows)
    assert fl[0]["depTime"] == "07:40" and fl[0]["arrTime"] == "10:40"
    assert fl[0]["code"] == "HX231" and fl[0]["intl"] is True
    raw = next(e for e in p["data"]["res"]
               if e.get("lng", "").startswith("HX0231_"))
    # tp 是页面含税总价；sp+tp 才是“两段相加”，必须不相等
    assert best["price"] == float(raw["tp"])
    assert best["price"] != float(raw["sp"]) + float(raw["tp"])


def test_parser_rejects_single_leg_or_wrong_return_date():
    p = _payload()
    e = dict(p["data"]["res"][0])
    date = "2026-11-20"
    bad = dict(e)
    bad.pop("lng", None)
    assert TongchengCrawler._parse_intl_rt_entry(bad, date, "2026-11-23") is None
    bad2 = dict(e)
    bad2["lng"] = "HX0231_20261120|HX0234_20261124"
    assert TongchengCrawler._parse_intl_rt_entry(bad2, date, "2026-11-23") is None


def test_intl_fetch_dispatches_to_rt_not_calendar():
    c = TongchengCrawler({"headless": True}, logging.getLogger("r926"))
    seen = {}

    def fake(fc, tc, dates, ret_date):
        seen["args"] = (fc, tc, dates, ret_date)
        return []

    c._fetch_intl_rt = fake
    assert c._fetch_intl("SHA", "HKG", ["2026-11-20"],
                         ret_date="2026-11-23") == []
    assert seen["args"] == ("SHA", "HKG", ["2026-11-20"], "2026-11-23")


def test_report_rounds_sees_rt_rows(tmp_path):
    """新往返行必须能进走势聚类，而不是被「时刻双空」整行丢掉。"""
    import sqlite3
    import time
    from report import _rounds

    p = _payload()
    rows = [TongchengCrawler._parse_intl_rt_entry(e, "2026-11-20",
                                                  "2026-11-23")
            for e in p["data"]["res"]]
    rows = [r for r in rows if r]
    db = tmp_path / "prices.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, "
                "platform TEXT, from_city TEXT, to_city TEXT, "
                "depart_date TEXT, price REAL, extra TEXT, fetched_at TEXT)")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con.execute("INSERT INTO flight_prices (platform, from_city, to_city, "
                "depart_date, price, extra, fetched_at) VALUES (?,?,?,?,?,?,?)",
                ("tongcheng", "SHA", "HKG", "2026-11-20", 1463.0,
                 json.dumps(rows, ensure_ascii=False), now))
    con.commit()
    con.close()
    pts = _rounds(str(db), "SHA", "HKG", "2026-11-20", 24, hours=2)
    assert pts, "走势聚类没有看到新的同程国际往返行"
    assert any(x[1] for x in pts) or any(x[2] for x in pts), pts


# ---- merged from tests/test_v15121_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_cliff_band_gets_dense_ticks():
    """悬崖带实证形态（demo 48h：lo=1630 hi=2060，raw=107.5）：
    步长 100（旧档 200），网格线 ≥4 条。"""
    nice, k0, k1 = _nice_ticks(1630, 2060)
    assert nice == 100, nice
    assert k1 - k0 + 1 >= 4, (nice, k0, k1)


def test_seven_day_window_three_plus():
    """7d 窗形态（跨度 ~800）：步长不劣于旧档。"""
    nice, k0, k1 = _nice_ticks(1500, 2400)
    assert nice == 200, nice          # raw=225 → 旧档同 200
    assert k1 - k0 + 1 >= 4


def test_labels_still_round_prices():
    """整价锚语义不变：全部刻度值 ×00/×50 收尾（1/2/5×10^n 族）。"""
    for lo, hi in ((1630, 2060), (1500, 2400), (800, 9800), (100, 160)):
        nice, k0, k1 = _nice_ticks(lo, hi)
        m = nice / max(nice, 1)
        assert nice in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200,
                        500, 1000, 2000, 5000), nice
        for k in range(k0, k1 + 1):
            v = nice * k
            assert abs(v - round(v)) < 1e-9 or nice < 1, v


def test_cover_floor_and_ceiling():
    """ceil/floor 语义：全部刻度线落在数据域 [lo,hi] 内（渲染域外
    零画线），且域内刻度数 ≥4。"""
    nice, k0, k1 = _nice_ticks(1630, 2060)
    assert nice * k0 >= 1630 - 1e-9 and nice * k1 <= 2060 + 1e-9
    assert k1 - k0 + 1 >= 4


def test_wide_span_padding_scales():
    """r329 P3-1（WebUI 审计）：y 量程余量随值域缩放——定值 ±30 在
    宽值域（生产实况 span>2100 元）下视觉余量仅 ~4px，max 平顶段
    贴绘图区上缘易读作裁切（像素实测非真裁切）。余量改为
    max(30, span*0.04)：窄值域保底 30 不变（存量行为零回归），
    宽值域按比例放大。"""
    src = webui_full_src()
    assert "const _span=Math.max(...vals)-Math.min(...vals)" in src
    assert "_pad=Math.max(30,_span*0.04)" in src
    assert "const lo=Math.min(...vals)-_pad,hi=Math.max(...vals)+_pad;" in src


# ---- merged from tests/test_v15133_wd.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15133wd")


def _fp(plat, price=1600, tbg="", code="MU5700", trans="兰州",
        dep="2026-10-06"):
    return {"price": price, "name": "东航" + code, "code": code,
            "depTime": "10:00", "arrTime": "15:00",
            "depDate": dep, "arrDate": dep,
            "transCity": trans, "crossDayDesc": "",
            "totalDuration": "9时30分", "_platform": plat,
            "transferBaggage": tbg, "layoverM": 120}


def _ps(fs, fc="URC", tc="SHA", d="2026-10-06"):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in fs]


def _route(**kw):
    d = dict(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
             to_name="上海", dates=["2026-10-06"],
             alert_direct=0, alert_transfer=1700,
             transfer_arrival_max="23:59", transfer_baggage="direct")
    d.update(kw)
    return Route(**d)


class FakeN:
    def __init__(self):
        self.sent = []

    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        self.sent.append({"title": t, "desp": d, "launch": launch})
        return True


# ---- WD-P1-1 tie 组 OR 五处口径收齐 -------------------------

def test_kpi_transfer_tie_or():
    """直挂筛选航线上同价同班 tie 组任一成员合规即组合规：KPI 行1
    中转位出 🎯 且行情注家族（（行情价）/·行情/行情价 三降级档）全部
    绝迹——首成员单判曾让 KPI 与总表绿行/🔥 同屏自相矛盾。"""
    a = Alerter(_LOG, notifier=FakeN(), storage=None, digest=True, user="t")
    a.check_multi([(_route(), _ps([_fp("fliggy"), _fp("ctrip", tbg="direct")]))])
    desp = a.notifier.sent[0]["desp"]
    assert "🎯" in desp
    assert "行情价" not in desp
    assert _MKT_NOTE not in desp


def test_summary_transfer_tie_or(monkeypatch):
    """总表图 summary 中转位同口径：kpi_tier_txt 消费组 OR 的 qual——
    破线档显「·已达标」不显「·行情」（图脱离消息上下文可判可出手）。
    summary 随 render_flights_table(summary=…) 进 PNG，钉捕参数。"""
    import report as rep
    captured = {}
    monkeypatch.setattr(rep, "render_flights_table",
                        lambda *a, **k: captured.update(k) or "x.png")
    monkeypatch.setattr(rep, "upload_chart", lambda *a, **k: "https://c/x.png")
    a = Alerter(_LOG, notifier=FakeN(), storage=None, digest=True, user="t")
    r = _route()
    secs = a._build_sections(
        r, _ps([_fp("fliggy"), _fp("ctrip", tbg="direct")]))
    a._flights_table_md_multi([(r, secs)])
    summary = "｜".join(captured.get("summary") or [])
    assert "低￥100·真达标" in summary
    assert "·行情" not in summary


# ---- WD-P2-2 遗留 digest 路径去抖 + 🔔 档 -------------------

def test_legacy_digest_debounce_and_bell(tmp_path):
    """单航线遗留 digest 路径与 multi 同律：fresh_hits 去抖先于
    _send_urgent——2h 内持续达标第二轮不重拨、主推标题 🔔（曾每轮
    重拨且恒 🚨，与「电话已提醒过」语义相反）。"""
    urgent_calls = []
    a = Alerter(_LOG, notifier=FakeN(),
                storage=PriceStorage(str(tmp_path / "p.db")),
                digest=True, user="t")

    def _no_urgent(*args, **kwargs):
        # 尊重真函数契约：hits 空=不拨（持续达标轮 fresh 空仍会以
        # 空列表调用，真函数早退不拨号）
        hits_arg = args[2] if len(args) > 2 else kwargs.get("hits")
        if hits_arg:
            urgent_calls.append(1)
        return True

    a._send_urgent = _no_urgent
    r = _route()
    p = _ps([_fp("fliggy"), _fp("ctrip", tbg="direct")])
    a.check_and_alert(r, p)
    n1 = len(urgent_calls)
    a.check_and_alert(r, p)
    assert n1 == 1, "首轮应拨且仅拨一次"
    assert len(urgent_calls) == 1, "第二轮持续达标不应重拨（2h 去抖）"
    assert "🔔" in a.notifier.sent[-1]["title"]


# ---- WD-P2-1 图链本地直读路径穿越 ---------------------------

def test_local_push_image_traversal(tmp_path, monkeypatch):
    """URL ../ 形态不得越出 data/（穿越曾可读仓库内任意 .png 并 CID
    内嵌进外发邮件）；正常 URL 直读行为不变。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    # 本地名=URL stem（无时分段）——确定性映射「{stem}_{HHMMSS}.png ↔
    # data/{stem}.png」的 fixture 须对齐生产构造
    (tmp_path / "data" / "trend_u_URC_SHA.png").write_bytes(b"PNGOK")
    (tmp_path / "secret_123456.png").write_bytes(b"TOPSECRET")
    assert _local_push_image(
        "https://cdn/charts/20261006/../secret_123456.png") == b""
    assert _local_push_image(
        "https://cdn/charts/20261006/trend_u_URC_SHA_123456.png") == b"PNGOK"


# ---- WD-P2-3 storm_repeat 声明域钳制 ------------------------

def test_storm_repeat_clamp():
    """storm_repeat 入模钳制 1-5（webui 声明域互钉）：8 曾实发 5 而
    标题写「n/8」，5/8-8/8 永不出现。"""
    assert Alerter(_LOG, notifier=None, storage=None,
                   storm_repeat=8).storm_repeat == 5
    assert Alerter(_LOG, notifier=None, storage=None,
                   storm_repeat=0).storm_repeat == 1
    assert Alerter(_LOG, notifier=None, storage=None,
                   storm_repeat=3).storm_repeat == 3


# ---- WD-P2-6 + 备1 守卫链尾地板档 ---------------------------

def test_channel_market_lines_floor_tops():
    """tops 分支长平台键（病理形态 >34 半角前缀）：整行渲染宽恒
    ≤40 半角（前缀自身进预算 + budget 地板 8）。"""
    a = Alerter(_LOG, notifier=None, storage=None, user="t")
    key = "X" * 40
    s = {"date": "2026-10-06", "platform_mins": {key: 1234.0},
         "plat_top3": {key: [_fp("qunar", price=1234.0)]}}
    for ln in (l for l in a._channel_market_lines([s]).split("\n")
               if l.strip()):
        assert _disp_dw(ln) <= 40, ln


def test_channel_market_lines_floor_else():
    """else 分支（无明细只有全线价）长平台键：链尾地板档恒达标
    （曾两档 fallback 均含渠道名原文，71 半角原样吐出）。"""
    a = Alerter(_LOG, notifier=None, storage=None, user="t")
    s = {"date": "2026-10-06", "platform_mins": {"X" * 40: 1234.0}}
    for ln in (l for l in a._channel_market_lines([s]).split("\n")
               if l.strip()):
        assert _disp_dw(ln) <= 40, ln


# ---- 备2 _send_urgent 分发落账 ------------------------------

def test_send_urgent_history(tmp_path, monkeypatch):
    """强提醒分发落账 ch=urgent：控制台「推送记录」对电话/弹窗不再
    失明（钉钉单发落账已有，urgent 三通道曾不入账）。"""
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(tmp_path / "ph.jsonl"))
    a = Alerter(_LOG, notifier=FakeN(), storage=None, user="t")
    r = _route()
    hit = (r, {"date": "2026-10-06"}, "中转",
           _fp("ctrip", tbg="direct"), 1700.0)
    a._send_urgent("T", "D", [hit])
    if not (tmp_path / "ph.jsonl").exists():
        recs = []
    else:
        recs = [json.loads(l) for l in (tmp_path / "ph.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(x.get("ch") == "urgent" for x in recs)


# ---- 备3a 风暴透传主推 launch -------------------------------

def test_storm_launch_passthrough(monkeypatch):
    """风暴条与主推同 launch（ntfy 点击跳转曾仅主推有）。"""
    raw_sleep = _time.sleep
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    calls = []

    class CapN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            calls.append(launch)
            return True

    a = Alerter(_LOG, notifier=CapN(), storage=None, storm_repeat=2,
                user="t", base_url="https://pub.example")
    a._storm("T", "D", [], launch="https://pub.example/n/1")
    for _ in range(100):
        if calls:
            break
        raw_sleep(0.05)
    assert calls and calls[0] == "https://pub.example/n/1"


# ---- 备6 _mini_kpi 未设线词面贴法 ---------------------------

def test_mini_kpi_noline_spacing():
    """未设线分支「中转￥1600」与 th 分支「{dot}中转 ￥N」贴法对齐
    （label 与价格间空格，同消息内两种贴法曾并存；mini 仅多日期
    航线渲染——两日期数据驱动）。"""
    a = Alerter(_LOG, notifier=FakeN(), storage=None, digest=True, user="t")
    r = _route(alert_direct=1700, alert_transfer=0,
               dates=["2026-10-06", "2026-10-07"])
    fs = [_fp("qunar", code="CZ1234", price=1500, trans=""),
          _fp("fliggy", code="MU5700", price=1600),
          _fp("qunar", code="CZ1234", price=1520, trans="", dep="2026-10-07"),
          _fp("fliggy", code="MU5700", price=1620, dep="2026-10-07")]
    a.check_multi([(r, _ps(fs)[:2] + _ps(fs[2:], d="2026-10-07"))])
    desp = a.notifier.sent[0]["desp"]
    # mini 未设线分支裸贴形态「中转[￥1620](url)」（label 紧贴链接壳）
    # vs th 分支「{dot}中转 [￥N](url)」——对齐后裸贴绝迹
    assert "中转[￥" not in desp
    assert "中转 [￥" in desp


# ---- 备7 email 失败落账带 img 注 ----------------------------

def test_email_fail_history_img_kwarg(tmp_path, monkeypatch):
    """EmailNotifier 失败路径 _append_push_history 带 img 参（成功
    路径已有）：图挂＋发送同败时控制台可见图内嵌状态。"""
    cap = {}
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(tmp_path / "ph.jsonl"))
    monkeypatch.setattr(notifier_mod, "_append_push_history",
                        lambda *a, **k: cap.update(k))
    import smtplib

    class Boom:
        def __init__(self, *a, **k):
            raise OSError("smtp down")

    monkeypatch.setattr(smtplib, "SMTP_SSL", Boom)
    monkeypatch.setattr(smtplib, "SMTP", Boom)
    en = EmailNotifier("smtp.test", 465, "a@b.c", "pw", "d@e.f", _LOG)
    en.send("T", "D")
    assert cap.get("ch") == "email"
    assert "img" in cap


# ---- WD-P2-4 日报图挂 TOP5 文本兜底（能力对称） --------------

def test_daily_table_fail_text_top3(monkeypatch):
    """日报明细图挂（turl=None）时 TOP5 明细不再整段蒸发：文本式
    明细行兜底（与告警路径 _top3_blocks/_channel_market_lines 能力
    对称——日报是每日唯一综合视图，容量曾只剩 KPI 三行）。"""
    import report as rep
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", "2026-09-25"):
                                                "http://x/t.png"})
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [
                            {"price": 2690, "transCity": "",
                             "_platform": "qunar", "depTime": "10:00",
                             "arrTime": "15:00", "depDate": "2026-09-25",
                             "arrDate": "2026-09-25", "crossDayDesc": "",
                             "code": "CZ6976", "name": "南航CZ6976",
                             "totalDuration": "5时"},
                            {"price": 2150, "transCity": "郑州",
                             "_platform": "ctrip", "depTime": "12:05",
                             "arrTime": "00:35", "arrDate": "2026-09-26",
                             "crossDayDesc": "+1天", "code": "MU2301",
                             "name": "东航MU2301", "totalDuration": "12时30分"}])
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_chart", lambda *a, **k: None)
    sent = {}

    class FakeN:
        def send(self, title, desp="", **kw):
            sent["desp"] = desp
            return True

    cfg = {"notifier": {"image_host": {"provider": "ghimg"}},
           "users": [{"name": "u", "routes": [
               {"from": "SHA", "to": "URC", "from_name": "上海",
                "to_name": "乌鲁木齐", "dates": ["2026-09-25"],
                "alert_direct": 2000, "alert_transfer": 1800,
                "transfer_arrival_max": "02:00"}],
               "notifier": {"image_host": {"provider": "ghimg"}}}]}
    ok = rep.build_and_push(cfg, _LOG, FakeN(), user="u")
    assert ok
    desp = sent["desp"]
    assert "明细总表缺失" in desp or "明细总表生成失败" in desp
    # 兜底区独有断言（S-P2-3：价格由 KPI 兜底本就携带，弱钉漏过
    # 删兜底的变异——锚兜底头行与航班号明细本体；r286 P3-1 词面
    # 减一字得行宽缓冲，钉面随词面改写）
    assert "图未出，文本兜底" in desp
    assert "CZ6976" in desp and "MU2301" in desp
    assert "￥2690" in desp, "直飞池最低价文本兜底缺失"
    assert "￥2150" in desp, "中转池最低价文本兜底缺失"


# ---- WD-P2-5 日报对账注补两族（能力对称） --------------------

def test_daily_ops_notes_direct_missing_and_xphan():
    """日报运维对账注补「直挂标注缺失」「孤低价拦截」两族（与告警
    侧 _ops_notes 同族同语言）：曾读者无法区分「没有便宜班次」与
    「有班被守卫/判据剔除」。"""
    from report import _daily_ops_notes
    notes = _daily_ops_notes(
        ["qunar"], {"qunar"}, ("上海", "乌鲁木齐"), "2026-09-25",
        mkt_t=[{"price": 2150, "transCity": "郑州", "_platform": "ctrip"}],
        xphans=[("fliggy", 1899.0)], transfer_baggage="direct")
    joined = "｜".join(notes)
    assert "中转直挂标注缺失" in joined
    assert "孤低价拦截×1" in joined and "￥1899" in joined
    # 非直挂配置/无缺勤 → 两族不注（全勤返空不漂移）
    assert _daily_ops_notes(["qunar"], {"qunar"}, ("上海", "乌鲁木齐"),
                            "2026-09-25") == []


# ---- merged from tests/test_v193_perf.py ----

def _report_src():
    import report as _r
    with open(_r.__file__, encoding="utf-8") as f:
        return f.read()


def _mk_db(td):
    """最小 flight_prices 表（与 core.storage SCHEMA 同列，测试自足）。"""
    dbp = _os.path.join(td, "t.db")
    db = _sq.connect(dbp)
    db.execute(
        # prov：report.recent_platform_flights 会读它（补位行溯源），
        # 缺列会让该函数在执行期抛 no such column（测试自足性缺口）。
        "CREATE TABLE flight_prices (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "platform TEXT, extra TEXT, fetched_at TEXT, from_city TEXT,"
        "to_city TEXT, depart_date TEXT, price REAL, prov TEXT)")
    db.commit()
    db.close()
    return dbp


def _ins(dbp, platform, flights, hours_ago, from_city="A", to_city="B",
         date="2026-10-01"):
    ts = (_dt.datetime.now() - _dt.timedelta(hours=hours_ago)
          ).strftime("%Y-%m-%d %H:%M:%S")
    # 行价=行内最低元素价（与爬虫行级 price 字段同构——行级幻影
    # 守卫的判定输入）
    _rp = min((float(f.get("price") or 0) for f in flights), default=0)
    db = _sq.connect(dbp)
    db.execute("INSERT INTO flight_prices (platform,extra,fetched_at,"
               "from_city,to_city,depart_date,price) VALUES (?,?,?,?,?,?,?)",
               (platform, _json.dumps(flights), ts, from_city, to_city,
                date, _rp))
    db.commit()
    db.close()


class TestXchanGuardNotQuadratic:
    """修 A：跨渠道守卫不得写在列表推导条件里（O(n²) → O(n)）。"""

    def test_no_guard_call_in_listcomp_condition(self):
        src = _report_src()
        assert "if i not in xchan_phantom_idx(" not in src, (
            "report.py 仍有 `if i not in xchan_phantom_idx(...)` 写法："
            "条件表达式每元素重算 → O(n²)，冷构建被拖到 200s+")
        assert "for i not in xchan_phantom_idx(" not in src

    def test_guard_hoisted_to_local(self):
        """守卫结果必须先接到局部变量，再在推导里做 O(1) 集合判定。"""
        src = _report_src()
        assert src.count("= xchan_phantom_idx(") >= 2, \
            "两处守卫都未 hoist 到局部变量"

    def test_called_once_per_bucket_not_per_row(self):
        """调用次数上界：桶数×2（直飞池 + 中转池），与桶内元素数无关。"""
        import report as _r
        calls = {"n": 0}
        real = _r.xchan_phantom_idx

        def spy(entries):
            calls["n"] += 1
            return real(entries)

        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            # 3 轮 × 每轮 5 渠道 × 每渠道 6 个直飞 = 90 个元素
            for rnd in range(3):
                for pi, pl in enumerate(("ctrip", "fliggy", "qunar",
                                         "tongcheng", "tuniu")):
                    fl = [{"price": 2000 + pi * 10 + k, "depTime": "10:00",
                           "arrTime": "13:00"} for k in range(6)]
                    _ins(dbp, pl, fl, hours_ago=1 + rnd * 2)
            _r.xchan_phantom_idx = spy
            try:
                hist = _r._rounds(dbp, "A", "B", "2026-10-01", "02:00",
                                  hours=48)
            finally:
                _r.xchan_phantom_idx = real
        assert len(hist) == 3, hist
        # 每桶恒定 3 次（行级幻影守卫 r248 +1、直飞池、中转池），
        # 3 桶上界 9——与桶内元素数无关（修复前 = 逐元素重算 O(n²)）
        assert calls["n"] <= 9, (
            "xchan_phantom_idx 被调 %d 次（应 ≤9=每桶恒 3 次）：列表推导"
            "条件里仍在逐元素重算" % calls["n"])

    def test_phantom_row_still_filtered(self):
        """行为等价：幻影轮最低价仍被曲线剔除（修法不得放过毒行）。"""
        import report as _r
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            # 一轮：fliggy 吐 700 幻影，其余四渠道 2500+
            _ins(dbp, "fliggy", [{"price": 700, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=1)
            for pl in ("qunar", "ctrip", "tongcheng", "tuniu"):
                _ins(dbp, pl, [{"price": 2560, "depTime": "10:00",
                                "arrTime": "13:00"}], hours_ago=1)
            hist = _r._rounds(dbp, "A", "B", "2026-10-01", "02:00", hours=48)
        assert hist, "序列不应为空"
        assert hist[0][1] == 2560, (
            "幻影 700 未被剔除（曲线最低价应为 2560）: %r" % (hist[0],))

    def test_low_band_price_survives(self):
        """行为等价回归：150 元真实低价行仍保留（test_v1553 同口径）。"""
        from report import _rounds
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 150, "depTime": "10:00",
                                "arrTime": "13:00"},
                               {"price": 900, "depTime": "12:00",
                                "arrTime": "15:00"}], hours_ago=1)
            hist = _rounds(dbp, "A", "B", "2026-10-01", "02:00", hours=48)
        assert hist and hist[0][1] == 150, hist


class TestXchanMedianCache:
    """修 B：>渠道中位数按渠道缓存，不在行循环里重算 sorted。"""

    def test_median_computed_outside_row_loop(self):
        """中位数只依赖渠道（pmin 恒定）：必须在行循环**之外**算，
        按渠道缓存——不得逐行重建 sorted。"""
        import report as _r  # noqa: F401  确保链路可导入
        from core import alerter as _a
        with open(_a.__file__, encoding="utf-8") as f:
            src = f.read()
        i0 = src.index("def xchan_phantom_idx(")
        i1 = src.index("\ndef ", i0 + 10)
        seg = src[i0:i1]
        assert "med_by_pl" in seg, \
            "未按渠道缓存中位数：仍在行循环里逐行重建 sorted(...)"
        si = seg.index("others = sorted(")
        assert "med is None" in seg[:si], (
            "sorted(...) 未置于「缓存未命中」分支——每行仍会无条件重算")

    def test_semantics_unchanged(self):
        from core.alerter import xchan_phantom_idx
        ent = [(700.0, "fliggy"), (930.0, "fliggy"), (3070.0, "fliggy"),
               (2546.0, "qunar"), (2550.0, "ctrip"),
               (2850.0, "tongcheng"), (3280.0, "tuniu")]
        assert xchan_phantom_idx(ent) == {0, 1}
        assert xchan_phantom_idx([(100.0, "fliggy")]) == set()
        assert xchan_phantom_idx([(700.0, "fliggy"), (2546.0, "qunar")]) == {0}
        ok = [(2410.0, "tuniu"), (2410.0, "qunar"), (2412.0, "ctrip"),
              (2415.0, "fliggy"), (2430.0, "tongcheng")]
        assert xchan_phantom_idx(ok) == set()

    def test_multi_platform_median_stability(self):
        """多行同渠道：锚取该渠道最低（与修复前同式）。"""
        from core.alerter import xchan_phantom_idx
        ent = [(700.0, "fliggy"), (900.0, "fliggy"), (2546.0, "qunar"),
               (2560.0, "ctrip"), (2600.0, "tongcheng"), (2700.0, "tuniu"),
               (2750.0, "qunar")]
        assert xchan_phantom_idx(ent) == {0, 1}


class TestRecentPlatformFlightsTimeFilter:
    """修 C：补位明细的时间过滤下推到 SQL，不再白解析全历史 extra。"""

    def test_sql_filters_by_age(self):
        src = _report_src()
        i0 = src.index("def recent_platform_flights(")
        i1 = src.index("\ndef ", i0 + 10)
        seg = src[i0:i1]
        assert "datetime('now'" in seg, (
            "recent_platform_flights 未把 hours 下推到 SQL——"
            "仍会 json.loads 全历史 extra（真机 ~8s/航线-日期）")

    def test_old_rows_excluded(self):
        # 直调函数本体（conftest autouse 隔离面暂存了真身，
        # 补位链断源不适用于测 recent_platform_flights 本身的钉）
        import report as _rep
        recent_platform_flights = _rep._recent_platform_flights_raw
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 2000, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=10)
            _ins(dbp, "ctrip", [{"price": 2100, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=1)
            out = recent_platform_flights(dbp, "A", "B", "2026-10-01", hours=6)
        assert "ctrip" in out, "近期渠道应保留"
        assert "qunar" not in out, "10 小时前的行应被 hours=6 排除"

    def test_recent_value_returned(self):
        """保留语义：返回 age 小时与原始 flights 列表。"""
        import report as _rep
        recent_platform_flights = _rep._recent_platform_flights_raw
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 1888, "depTime": "09:00",
                                 "arrTime": "12:00"}], hours_ago=2)
            out = recent_platform_flights(dbp, "A", "B", "2026-10-01", hours=6)
        assert "qunar" in out
        age, fl = out["qunar"]
        assert 1.5 < age < 2.5, age
        assert fl and fl[0]["price"] == 1888
        # 补位行必须带 DB id + extra 下标，详情/CSV 才能回放 raw
        assert fl[0]["_row_id"] > 0 and fl[0]["_raw_idx"] == 0
        assert fl[0]["_fetched_at"]


class TestDailyMinimaReusesNothingBroken:
    """回归护栏：_daily_minima 仍逐日取最低（修 A 不得改其档位口径）。"""

    def test_daily_minima_keeps_daily_min(self):
        from report import _daily_minima
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 2000, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=1)
            _ins(dbp, "qunar", [{"price": 1800, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=5)
            cal = _daily_minima(dbp, "A", "B", "2026-10-01", "02:00", days=14,
                                th_d=1900.0)
        assert cal, "日历不应为空"
        k, v, tier = cal[0]
        assert v == 1800, cal
        assert tier == 2, ("价 1800 ≤ 线 1900 应判真达标档 2: %r" % (cal[0],))


class TestPerfBudgetSanity:
    """性能护栏：同规模下守卫调用数不随行数平方增长。"""

    @pytest.mark.parametrize("n_rows", [2, 8])
    def test_call_growth_is_linear(self, n_rows):
        import report as _r
        calls = {"n": 0}
        real = _r.xchan_phantom_idx

        def spy(entries):
            calls["n"] += 1
            return real(entries)

        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            for rnd in range(n_rows):
                for pi, pl in enumerate(("ctrip", "fliggy", "qunar",
                                         "tongcheng", "tuniu")):
                    _ins(dbp, pl, [{"price": 2000 + pi * 10, "depTime":
                                    "10:00", "arrTime": "13:00"}],
                         hours_ago=1 + rnd * 2)
            _r.xchan_phantom_idx = spy
            try:
                hist = _r._rounds(dbp, "A", "B", "2026-10-01", "02:00",
                                  hours=48)
            finally:
                _r.xchan_phantom_idx = real
        assert len(hist) == n_rows, hist
        assert calls["n"] <= 2 * n_rows, (
            "n_rows=%d 时守卫被调 %d 次（应 ≤%d）"
            % (n_rows, calls["n"], 2 * n_rows))
