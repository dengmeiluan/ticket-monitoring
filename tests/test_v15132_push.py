# -*- coding: utf-8 -*-
"""r232 推送层落地（审校移交：_scratch/r232e 五斥候报告 P1×2/P2×6）。

- _mini_split 拆行档剥链接（P1-1）：_disp_dw 本就把 [t](url) 还原为
  t 计宽、URL 不占渲染宽——拆行档第一步无条件剥链接是历史降级档的
  过度保守，链接是第 2+ 日期唯一文本跳转入口，可达宽度内不得剥。
- 日报同价多渠道合并（P1-2）：_split_market_pool 与告警路径
  _dedup_tie 去重不对称，日报 TOP5 被同班复读占槽。
- 其余 P2 案见同文件各测试 docstring。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15132_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import alerter as _al  # noqa: E402


# ---- P1-1 拆行档保链接 ----

def test_mini_split_split_mode_keeps_links():
    """拆行档逐段首试原样：_disp_dw 渲染宽模型不计 URL，段可达
    预算内链接必须原样保留（跳转可达性——该日期唯一文本入口）。"""
    segs = ["🎯 直飞[￥2629](https://flight.example.com/urc-sha/qunar-x)",
            "🟩 中转[￥1752](https://flight.example.com/urc-sha/ctrip-y) 差￥87"]
    head = "📍 10/06　"
    # 前提自校验：联接超宽（确走拆行档）、单段原样在预算内
    assert _al._disp_dw(head + " ｜ ".join(segs)) > 40
    for s in segs:
        assert _al._disp_dw(head + s) <= 40
    out = _al._mini_split(head, segs)
    assert "[￥2629](https://flight.example.com/urc-sha/qunar-x)" in out
    assert "[￥1752](https://flight.example.com/urc-sha/ctrip-y)" in out
    for ln in out.split("\n"):
        if ln.strip():
            assert _al._disp_dw(ln) <= 40, ln


def test_mini_split_overwide_seg_still_degrades():
    """真超宽段降级链不回归：先剥链接仍超再逐字截（对剥链接后的
    裸文本截，防 markdown 半截），链尾恒达标。"""
    long_tail = "（行情价较上轮上涨幅度很大需要长注解释）"
    segs = ["🎯 直飞[￥1987](https://flight.example.com/x)" + long_tail,
            "🟩 中转￥1752" + long_tail]
    head = "📍 10/06　"
    out = _al._mini_split(head, segs)
    for ln in out.split("\n"):
        if ln.strip():
            assert _al._disp_dw(ln) <= 40, ln
    # 拆行输出不得含 markdown 半截（剥链接后才截）
    assert "](http" not in out


# ---- P1-2 日报同价多渠道合并 ----

def test_split_market_pool_dedup_tie():
    """日报明细表同价同班多渠道合并（与告警路径 _dedup_tie 对称）：
    日报 TOP5 曾被同班复读占槽（5 槽载 3 班），日报是每日唯一综合
    视图，有效信息容量不应低于告警总表。合并后 _tie_n 随行，渲染端
    _plat_tag「·同价×N」角标自动生效。"""
    from report import _split_market_pool
    rc = {"transfer_arrival_max": "02:00", "transfer_layover_min": 0,
          "alert_direct": 1900, "alert_transfer": 1700}
    base = dict(code="9C6928", name="春秋9C6928", depTime="08:30",
                arrTime="13:50", depDate="2026-10-05", arrDate="2026-10-05")
    fs = [dict(base, price=1760, _platform=p)
          for p in ("ctrip", "tuniu", "qunar")]
    fs.append(dict(base, code="MU5137", name="东航MU5137", depTime="11:00",
                   arrTime="16:20", price=1800, _platform="ctrip"))
    directs, mkt = _split_market_pool(fs, rc)
    assert len(directs) == 2
    tie = [d for d in directs if d.get("_tie_n", 1) > 1]
    assert len(tie) == 1 and tie[0]["_tie_n"] == 3
    assert tie[0]["price"] == 1760


def test_split_market_pool_transfer_dedup_tie():
    """中转池同律合并：同班同价多渠道在 mkt_t 同样合并。"""
    from report import _split_market_pool
    rc = {"transfer_arrival_max": "02:00", "transfer_layover_min": 0,
          "alert_direct": 1900, "alert_transfer": 1700}
    base = dict(code="9C6928", name="春秋9C6928", depTime="08:30",
                arrTime="23:50", depDate="2026-10-05", arrDate="2026-10-05",
                transCity="西安", layoverM=200)
    fs = [dict(base, price=1550, _platform=p)
          for p in ("ctrip", "tongcheng")]
    _, mkt = _split_market_pool(fs, rc)
    assert len(mkt) == 1 and mkt[0]["_tie_n"] == 2


# ---- P2-4 比价组 (中国) 后缀 ----

def test_compare_rows_strips_country_suffix():
    """比价组 stopCity 渠道原文「西宁(中国)」剥国名后缀（全/半角
    括号双形态）——PNG 内无害、词面不洁；组装层收口渲染端零改动。"""
    from core.alerter import Alerter
    cands = [("save", [
        dict(name="春秋9C6928", code="9C6928", depTime="08:30",
             arrTime="13:50", transCity="", crossDayDesc="",
             layoverT="", stopCity="西宁(中国)", price=1760,
             _platform="qunar")], None),
        ("save", [
        dict(name="东航MU5137", code="MU5137", depTime="11:00",
             arrTime="23:20", transCity="西安", crossDayDesc="+1天",
             layoverT="3时15分", stopCity="兰州（中国）", price=1550,
             _platform="ctrip")], None)]
    rows = Alerter._compare_rows(cands)
    assert rows[0]["stopCity"] == "西宁"
    assert rows[1]["stopCity"] == "兰州"


# ---- P2-5 storm_repeat 配置域与实现对齐 ----

class _FakeT:
    def __init__(self, target=None, daemon=None):
        self._t = target

    def start(self):
        self._t()


def _mk_alerter_storm(repeat):
    from core.alerter import Alerter
    import logging
    log = logging.getLogger("t15132")
    return Alerter(log, notifier=_NSend(), storage=None, digest=True,
                   at_mobile="", storm_repeat=repeat, user="演练")


class _NSend:
    def send(self, title, desp, at_mobiles=None):
        return True


def test_storm_repeat_five_fires_four_repushes(monkeypatch):
    """webui 配置域已声明 max=5（webui.py 风暴连推 input max=5）而
    延迟表硬编码 (60,180)——repeat>3 静默无效。延迟表扩至四档后
    repeat=5 → 主推+4 重推，标题 n/5 序列一致。"""
    import threading as _th
    import time as _t
    delays = []
    monkeypatch.setattr(_th, "Thread", _FakeT)
    monkeypatch.setattr(_t, "sleep", delays.append)
    al = _mk_alerter_storm(5)
    al._storm("标题", "正文", [])
    assert delays == [60, 180, 300, 480]


def test_storm_repeat_three_unchanged(monkeypatch):
    """默认 repeat=3 行为零回归（即时+1min+3min）。"""
    import threading as _th
    import time as _t
    delays = []
    monkeypatch.setattr(_th, "Thread", _FakeT)
    monkeypatch.setattr(_t, "sleep", delays.append)
    al = _mk_alerter_storm(3)
    al._storm("标题", "正文", [])
    assert delays == [60, 180]


# ---- P2-6 多租户总表 PNG 文件名互覆 ----

def test_png_user_tag_sanitize():
    """user 段 sanitize：空 user（单用户默认部署）文件名不变零回归；
    路径分隔/非法字符剥除（用户名是配置自由文本）。"""
    from core.alerter import _png_user_tag
    assert _png_user_tag("") == ""
    assert _png_user_tag("张三") == "张三_"
    assert _png_user_tag('a/b\\c:d*e?f"g<h>i|j k') == "abcdefghijk_"


def test_table_png_name_carries_user_tag():
    """三处总表产物命名带 user 段（源码钉）：多租户同 OD 本地文件
    互覆——邮件 cid 30 分钟门内反推直读会嵌到别家图。反推链
    _local_push_image 是通用 stem 还原，产物名带段后零改动兼容。"""
    import inspect
    import report as _rp
    from core import alerter as _al
    src_r = inspect.getsource(_rp.build_and_push)
    assert "_png_user_tag(user)" in src_r
    src_m = inspect.getsource(_al.Alerter._flights_table_md_multi)
    assert "_png_user_tag(self.user)" in src_m
    src_s = inspect.getsource(_al.Alerter._flights_table_md)
    assert "_png_user_tag(self.user)" in src_s


# ---- P2-9 转写残留双空格 ----

def test_alert_body_collapses_double_spaces():
    """转写词尾随空格+装饰符剥离残留双空格（「真达标  直飞」）、
    行首空格（「 10/06」）收口；全角空格（日期分隔排版语义）保留。"""
    from core.notifier import _alert_body
    body = _alert_body("#### 头\n\n📍 10/06　🎯 直飞￥1987\n\n")
    import re as _re
    assert not _re.search(r"  ", body), repr(body)
    assert not any(ln.startswith(" ") for ln in body.split("\n")), repr(body)
    assert "10/06　真达标 直飞" in body


# ---- P2-1 日报运维对账注 ----

def test_route_latest_flights_seen_out(tmp_path):
    """_route_latest_flights seen_out 出参（stats 出参先例）：日报
    对账注需要「配置平台 − 池内平台」差集，池函数是唯一知情点。"""
    import sqlite3
    from datetime import datetime
    from report import _route_latest_flights
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE flight_prices (id INTEGER PRIMARY KEY, "
                 "platform TEXT, extra TEXT, fetched_at TEXT, "
                 "from_city TEXT, to_city TEXT, depart_date TEXT)")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for p in ("qunar", "ctrip"):
        conn.execute("INSERT INTO flight_prices (platform, extra, "
                     "fetched_at, from_city, to_city, depart_date) "
                     "VALUES (?, '[]', ?, 'URC', 'SHA', '2026-10-05')",
                     (p, now))
    conn.commit()
    conn.close()
    seen = set()
    _route_latest_flights(str(db), "URC", "SHA", "2026-10-05",
                          seen_out=seen)
    assert seen == {"qunar", "ctrip"}


def test_daily_ops_notes_wording():
    """日报对账注词面与告警链 _ops_notes 同族：「{航线} {日期} 当轮无数据：
    渠道、渠道」（「当轮」限定与同图近 6h 补位行不矛盾，两路同改）；
    全勤返空列表不出注。"""
    from report import _daily_ops_notes
    notes = _daily_ops_notes(["qunar", "ctrip", "fliggy"], {"qunar"},
                             ("乌鲁木齐", "上海"), "2026-10-05")
    assert notes == ["乌鲁木齐→上海 10/05 当轮无数据：携程、飞猪"]
    assert _daily_ops_notes(["qunar"], {"qunar"},
                            ("乌鲁木齐", "上海"), "2026-10-05") == []


def test_daily_report_passes_ops_notes():
    """日报明细表渲染调用点带 ops_notes（源码钉）：渠道部分缺勤时
    日报不再静默——对账注随图内小注（告警链同律：文本直出占首屏
    曾是反模式）。"""
    import inspect
    import report as _rp
    src = inspect.getsource(_rp.build_and_push)
    assert "ops_notes=" in src


# ---- Soldier P1-1 回归：同价合并挤掉「各渠道最低」并行渠道 ----

def test_dedup_tie_carries_plats():
    """合并行带 _tie_plats 并行渠道集合：_dedup_tie 合并行只保留
    池序首渠道 _platform，并行渠道身份必须随行携带（下游展开用）。"""
    from core.alerter import _dedup_tie
    base = dict(code="9C6928", name="春秋9C6928", depTime="08:30",
                arrTime="13:50", depDate="2026-10-05", arrDate="2026-10-05")
    rows = [dict(base, price=1760, _platform="ctrip"),
            dict(base, price=1760, _platform="tuniu")]
    g = _dedup_tie(rows)[0]
    assert sorted(g.get("_tie_plats") or []) == ["ctrip", "tuniu"]


def test_plat_mins_expands_tie_plats():
    """日报「各渠道最低」按 _tie_plats 展开每渠道真实最低价：
    去重后池曾把并行同价渠道挤掉（tuniu 真实最低 1760 被抬成
    1800、仅一条同价行时整渠道消失）。"""
    from report import _plat_mins
    base = dict(code="9C6928", depTime="08:30", arrTime="13:50")
    pool = [dict(base, price=1760, _platform="ctrip",
                 _tie_n=2, _tie_plats=["ctrip", "tuniu"]),
            dict(base, code="MU5137", depTime="11:00", arrTime="16:20",
                 price=1800, _platform="tuniu")]
    mins = _plat_mins(pool)
    assert mins["tuniu"] == (1760, True)
    assert mins["ctrip"] == (1760, True)


def test_plat_mins_plain_pool_unchanged():
    """无 _tie_plats 的行按自身 _platform 出勤（原口径零漂移）。"""
    from report import _plat_mins
    mins = _plat_mins([dict(price=1900, _platform="qunar")])
    assert mins["qunar"] == (1900, True)
    assert _plat_mins([]) == {}


def test_user_plats_fallback_default_four():
    """_user_plats 回退链与告警链 build_users 物化同构：用户级与
    全局都未配 platforms 时回退默认四渠道（曾回退 []=永不告缺，
    与对账注「少报不误报」不对称）。"""
    import inspect
    import report as _rp
    src = inspect.getsource(_rp.build_and_push)
    assert '"qunar", "fliggy", "tongcheng", "tuniu"' in src, \
        "_user_plats 回退值未对齐 build_users 默认四渠道"
