# -*- coding: utf-8 -*-
"""r320b 半年走势数据层钉：price_daily 日粒度聚合表。

- 动机：明细 14 天 purge 与半年走势窗矛盾——日粒度聚合表（每
  航线×日期×天×直中一行，半年≈千行级）让长窗在 purge 之后仍完整；
- 口径备案：长窗=概览口径（直飞/中转按 extra 元素级 transCity 分桶、无
  中转衔接/到达窗细约束——短窗 _rounds 的判定口径在明细删净后不
  可重放，长窗是纯趋势概览非达标判定窗，达标判定语义仍归短窗/
  明细/推送）；
- flag 三档与全站同语言（2=真达标日 1=行情破线 -1=擦边 0=线外，
  _tier_of 同式）；
- purge 不删聚合（14 天窗只限明细，聚合表 400 天自清防膨胀）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r320b_trendlong.py -q
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from core.models import FlightPrice  # noqa: E402


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
        _fp("CZ1", 1500.0, fetched="2026-10-10 08:00:00"),
        _fp("CZ2", 1400.0, fetched="2026-10-10 12:00:00"),
    ])
    st.refresh_daily("SHA", "URC", "2026-11-01", day="2026-10-10")
    st.refresh_daily("SHA", "URC", "2026-11-01", day="2026-10-10")
    rows = st.daily_series("SHA", "URC", "2026-11-01", days=30)
    assert len(rows) == 1, rows
    b = rows[0]
    assert b["day"] == "10-10" and b["n"] == 2, b
    assert b["lo"] == 1400.0 and b["hi"] == 1500.0, b
    assert b["open"] == 1500.0 and b["close"] == 1400.0, b


def test_daily_series_window_and_sort(tmp_path):
    """days 窗（按今天回看）与日升序；窗外桶不返回。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    for d, t in (("2026-09-01", "2026-09-01 08:00:00"),
                 ("2026-10-01", "2026-10-01 08:00:00")):
        st.save_many([_fp("CZ1", 1200.0, fetched=t)])
        st.refresh_daily("SHA", "URC", "2026-11-01", day=d)
    rows = st.daily_series("SHA", "URC", "2026-11-01", days=30)
    assert [b["day"] for b in rows] == ["10-01"], rows
    rows180 = st.daily_series("SHA", "URC", "2026-11-01", days=180)
    assert len(rows180) == 2, rows180


def test_flag_tiers_same_language(tmp_path):
    """flag 长窗值域 {2,-1,0}（口径备案：日桶无 qual 面——飞猪税垫/
    直挂约束在明细删净后不可重放，1=行情破线的 qual 语义不可达；
    lo≤th 全标 2=「当日最低可出手」概览语义）、擦边 -1、线外 0，
    与全站档位色同语言。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp("CZ1", 1800.0, fetched="2026-10-10 08:00:00"),
        _fp("CZ2", 1850.0, fetched="2026-10-11 08:00:00"),
        _fp("CZ3", 1980.0, fetched="2026-10-12 08:00:00"),
        _fp("CZ4", 2500.0, fetched="2026-10-13 08:00:00"),
    ])
    for d in ("2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13"):
        st.refresh_daily("SHA", "URC", "2026-11-01", day=d)
    rows = {b["day"]: b["flag"]
            for b in st.daily_series("SHA", "URC", "2026-11-01",
                                     days=30, th_d=1900.0)}
    assert rows["10-10"] == 2, rows   # lo=1800 ≤ th 可出手日
    assert rows["10-11"] == 2, rows   # lo=1850 ≤ th 同上（无 qual 面）
    assert rows["10-12"] == -1, rows  # 1980 ∈ (th, th*1.1] 擦边
    assert rows["10-13"] == 0, rows   # 线外


def test_direct_transfer_split_buckets(tmp_path):
    """直飞/中转分桶（extra.transCity 判中转）：双系列与短窗同构。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([
        _fp("CZ1", 1500.0, transfer=False,
            fetched="2026-10-10 08:00:00"),
        _fp("CZ2", 1200.0, transfer=True,
            fetched="2026-10-10 09:00:00"),
    ])
    st.refresh_daily("SHA", "URC", "2026-11-01", day="2026-10-10")
    d = st.daily_series("SHA", "URC", "2026-11-01", days=30, kind="d")
    t = st.daily_series("SHA", "URC", "2026-11-01", days=30, kind="t")
    assert len(d) == 1 and d[0]["lo"] == 1500.0, d
    assert len(t) == 1 and t[0]["lo"] == 1200.0, t


def test_purge_keeps_daily_400d_selfclean(tmp_path):
    """purge 只删明细：聚合表保留；400 天外桶自清防膨胀。"""
    db = os.path.join(str(tmp_path), "t.db")
    st = PriceStorage(db)
    st.save_many([_fp("CZ1", 1500.0, fetched="2026-10-10 08:00:00")])
    st.refresh_daily("SHA", "URC", "2026-11-01", day="2026-10-10")
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
    st.save_many([_fp("CZ1", 1500.0, fetched="2026-10-10 08:00:00")])
    st.refresh_daily("SHA", "URC", "2026-11-01", day="2026-10-10")
    cfg = os.path.join(str(tmp_path), "c.yaml")
    open(cfg, "w", encoding="utf-8").write(
        f"output:\n  db_path: {db}\n")
    monkeypatch.setattr(webui._State, "config_path", cfg)
    ok = webui._trend_payload(
        {"from": ["SHA"], "to": ["URC"], "date": ["2026-11-01"],
         "days": ["180"], "th": ["1900"]})
    assert ok["days"] == 180
    assert len(ok["direct"]) == 1, ok
    p = ok["direct"][0]
    # 1.5.275：航线级日桶含日历价，flag 恒 0，不冒充航班级真达标
    assert p[0] == "10-10" and p[1] == 1500.0 and p[2] == 0, p
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
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"),
        encoding="utf-8").read()
    assert "const TREND_LONG={'30d':30,'90d':90,'180d':180};" in src
    assert "_TREND_DAYS = (30, 90, 180)" in src
    for i in ("rng30", "rng90", "rng180"):
        assert f'id="{i}"' in src, i
    assert "let _tlSeq=0;" in src and "if(seq!==_tlSeq)return;" in src
    assert "const BUCKET=_tl?1440:" in src
    assert "if(_tl&&!H0){" in src
    assert '"from": r["from"], "to": r["to"],' in src
    assert "loadTrend(u);   /* 长窗懒加载" in src


def test_frontend_long_range_live(page_srv=None):
    """行为钉（独立起 demo）：切半年档 → /api/trend 请求发出 →
    页面零 JS 错 + 档位 on 态正确。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright 缺库")
    import subprocess
    import tempfile
    import socket as _sk
    import urllib.request as _ur
    sk = _sk.socket(); sk.bind(("127.0.0.1", 0))
    port = sk.getsockname()[1]; sk.close()
    logf = tempfile.TemporaryFile()
    priv = tempfile.mkdtemp(prefix="r320b_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT_DIR, "webui.py"), "--demo",
         "--port", str(port)], cwd=ROOT_DIR, stdout=logf,
        stderr=subprocess.STDOUT, env=env)
    op = _ur.build_opener(_ur.ProxyHandler({}))
    try:
        for _ in range(40):
            try:
                op.open(f"http://127.0.0.1:{port}/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            hits = []
            pg.route("**/api/trend*", lambda r: (hits.append(r.request.url),
                                                 r.continue_()))
            pg.goto(f"http://127.0.0.1:{port}/")
            pg.wait_for_function(
                "typeof S !== 'undefined' && S && S.users")
            pg.evaluate("showMonTab('trend')")
            pg.click("#rng180")
            pg.wait_for_timeout(900)
            assert hits, "半年档未触发 /api/trend"
            assert "days=180" in hits[0], hits[0]
            on = pg.evaluate(
                "document.getElementById('rng180').className")
            assert "on" in on, on
            assert not errs, errs[:3]
            b.close()
    finally:
        proc.terminate()
        logf.close()
