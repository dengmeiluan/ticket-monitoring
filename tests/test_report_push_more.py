# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r242_push.py
- tests/test_r250_push.py
- tests/test_r258_push.py
- tests/test_r265_push.py
- tests/test_r286_push.py
- tests/test_r289_push.py
- tests/test_r296_push.py
- tests/test_r324_push_floor.py
- tests/test_v15132_push.py
- tests/test_v168_push.py
- tests/test_v181_push.py
- tests/test_v204_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import core.alerter as alerter
import datetime as dt
import json
import logging
import logging as _lg
import os
import pytest
import re
import report
import report as _rep
import sys
import unittest.mock as mock

from core import alerter as _al
from core.alerter import Alerter, _bare_identity_floor, _clip_dw, _disp_dw, _dw, _fit_line, dep_win_txt
from core.models import FlightPrice, Route
from datetime import datetime
from report import _daily_market_fallback, _daily_ops_fallback, _daily_ops_notes, _miss_chart_line, _route_section_title


# ---- merged from tests/test_r242_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- Minor-1：价格词面单源自守 ----

def test_fmt_flight_line_float_price_wording():
    """float 价直达（上游取整门被绕行的防御纵深）：词面不得出
    「￥12345.0」；正常 int 价词面不变。"""
    f = {"price": 12345.0, "name": "MU8369", "depTime": "08:30",
         "arrTime": "11:20"}
    line = Alerter._fmt_flight_line(f, idx=1)
    assert "￥12345.0" not in line, line
    assert "￥12345" in line, line
    f2 = dict(f, price=900)
    assert "￥900" in Alerter._fmt_flight_line(f2, idx=1)


def test_fmt_flight_line_bare_floor_within_budget():
    """bare 地板档（超长输入强制逐字截后）行宽恒 ≤40：float 价的
    「.0」尾巴曾把地板档撑到 42/40（审校直调实证）。"""
    f = {"price": 12345.0,
         "name": "九元航空AQ1111/长龙航GJ8888超长联程显示名",
         "depTime": "08:30", "arrTime": "11:20",
         "transCity": "郑州", "crossDayDesc": "+1天",
         "stopCitys": "兰州;西宁"}
    line = Alerter._fmt_flight_line(f)
    assert _disp_dw(line) <= 40, (line, _disp_dw(line))
    assert ".0" not in line, line


# ---- Minor-3：title/电话词面消毒 ----

def _route():
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上<海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=1900, alert_transfer=1700)


def _sect(direct_price, transfer_price=None, name="MU8369"):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        bd = {"price": direct_price, "name": name,
              "depTime": "19:55", "arrTime": "01:25", "_platform": "qunar"}
        s["best_direct"] = bd
        s["top_direct"] = [bd]
        s["top_transfer"] = []
        s["platform_mins"] = {"qunar": direct_price}
        s["plat_top3"] = {"qunar": [bd]}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
    return [s]


def _alerter(sent):
    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    return Alerter(logging.getLogger("t242"), notifier=FakeN(),
                   storage=None, digest=True, user="t")


def _img_down(a, monkeypatch):
    """图挂兜底形态：表格图渲染失败走文本兜底，确定性不渲染 PNG。"""
    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")


def test_digest_hit_branch_title_sanitized(monkeypatch):
    """达标报告 title 出口：route 配置名是自由文本，与 desp 同律
    （r236 只收了 desp）；消毒后 title 进存档页/主推/urgent 全链。"""
    sent, urgent = [], []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_archive_notify", lambda t, d, **kw: "")
    monkeypatch.setattr(a, "_send_urgent",
                        lambda t, d, hits, launch="": urgent.append((t, d))
                        or True)
    a._push_digest(_route(), _sect(1750, None, name="MU8369"))
    assert sent, "达标轮主推丢失"
    for _t, _d in sent:
        assert "<" not in _t and "＜" not in _t and "…" not in _t, _t
        assert "＜" not in _d, _d[:200]
    assert any("上海" in _t for _t, _d in sent), "消毒不得误伤正常词面"


def test_digest_heartbeat_tail_title_sanitized(monkeypatch):
    """未达标心跳尾出口：title 同律消毒。"""
    sent = []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_heartbeat_gate", lambda: True)
    a._push_digest(_route(), _sect(1950, None))
    assert sent, "心跳简报未发出"
    for _t, _d in sent:
        assert "<" not in _t and "＜" not in _t and "…" not in _t, _t


def test_urgent_aliyun_wording_sanitized(monkeypatch):
    """电话/短信词面：渠道自由文本 name/transCity 直进 TTS 词面，
    构造端同律剥除（音频把尖括号读出来的形态不可接受）。"""
    sent = []
    a = _alerter([])

    class FakeAliyun:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    import core.notifier as _N
    monkeypatch.setattr(_N, "AliyunAlertNotifier", FakeAliyun)
    a.urgent_notifier = [FakeAliyun()]
    r0 = _route()
    f0 = {"name": "MU<8369", "depTime": "08:30", "arrTime": "11:20",
          "price": 1750, "_platform": "qunar", "transCity": "郑<州"}
    hits = [(r0, {"date": "2026-09-25"}, "直飞", f0, 1900)]
    a._send_urgent("T", "D", hits)
    assert sent, "电话通道未触发"
    for _t, _d in sent:
        assert "<" not in _t and "<" not in _d, (_t, _d)
    assert "MU8369" in _d and "郑州" in sent[0][1], "消毒不得误伤正常词面"


# ---- merged from tests/test_r250_push.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _balanced(s: str) -> bool:
    return s.count("（") == s.count("）")


# ---------- alerter._section_title ----------

def test_section_title_double_nest_parens_balanced():
    """现实双层括号名的零回归钉（该输入未落病灶窗，抓旧 else:break
    bug 的复现钉是下方 pure-nest 直调钉；Soldier M1 变异定位）。"""
    out = Alerter._section_title(
        "北京（首都（T3）区）", "上海（虹桥+浦东）", "10/06~10/08", "")
    assert out, "无输出"
    assert _balanced(out), (
        "双层括号城市名截断窗产出未配对括号：%r——剥档判据须计数式"
        "（开>闭即继续剥），else:break 在「内闭外开」窗早停" % out)
    for ln in out.split("\n"):
        assert _dw(ln) <= 40, "标题行超宽 %r (%d)" % (ln, _dw(ln))


def test_section_title_single_layer_zero_regression():
    out = Alerter._section_title(
        "乌鲁木齐（地窝堡）", "上海（虹桥+浦东）", "10/06~10/08", "")
    assert _balanced(out), "单层形态产出未配对括号 %r" % out


# ---------- report._route_section_title ----------

def test_route_section_title_double_nest_parens_balanced():
    out = report._route_section_title(
        ["北京（首都（T3）区）", "上海（虹桥+浦东）"], "2026-10-06")
    assert _balanced(out), "双层括号名产出未配对括号 %r" % out
    for ln in out.split("\n"):
        if ln:
            assert report._dw_line(ln) <= 40, "标题行超宽 %r" % ln


# ---------- report._miss_chart_line ----------

def test_miss_chart_line_double_nest_parens_balanced():
    """现实双层括号名的零回归钉（复现钉=下方 pure-nest 直调钉）。"""
    out = report._miss_chart_line(
        "北京（首都（T3）区）→上海（虹桥+浦东）", "2026-10-06")
    assert _balanced(out), (
        "缺图行双层括号名产出未配对括号（审计直调实锤形态）：%r" % out)
    for ln in out.split("\n"):
        if ln:
            assert report._dw_line(ln) <= 40, "缺图行超宽 %r" % ln


def test_miss_chart_line_pure_nest_truncation_balanced():
    """审计直调最小复现：入参括号串 room 内截断于「内闭外开」窗，
    现行输出 3 开 1 闭。"""
    out = report._miss_chart_line("（（（）））→（（））", "2026-10-06")
    assert _balanced(out), "纯嵌套截断产出未配对括号 %r" % out


def test_miss_chart_line_single_layer_zero_regression():
    out = report._miss_chart_line("乌鲁木齐（地窝堡）→上海（虹桥+浦东）",
                                  "2026-10-06")
    assert _balanced(out), "单层形态产出未配对括号 %r" % out
    assert "乌鲁木齐" in out, "单层形态城市名丢失 %r" % out


# ---- merged from tests/test_r258_push.py ----

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

_DATE = "2026-09-25"
_ROUTES = [
    {"from": "SHA", "to": "URC", "from_name": "上海",
     "to_name": "乌鲁木齐", "dates": [_DATE],
     "alert_direct": 2000, "alert_transfer": 1800,
     "transfer_arrival_max": "02:00"},
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


@pytest.fixture()
def env(monkeypatch):
    import report as rep

    def _rounds(db, fc, tc, d, am, **kw):
        if (fc, tc) == ("SHA", "SYN"):
            return []
        return [(datetime(2026, 9, 20, 8, 0), 576.0, None)]

    monkeypatch.setattr(rep, "_rounds", _rounds)
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", _DATE):
                                                "http://x/t.png"})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    return {"rep": rep}


# ---------- P-1: p7 独立引用行长形 ----------

def test_empty_pool_p7_standalone_quote_line(env, monkeypatch):
    """空池补偿：p7 独立引用行（粘连消失 + 参照时刻找回 + 恒落位）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    n = FakeN()
    assert rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    d = n.sent["desp"]
    line = [ln for ln in d.splitlines() if "无渠道明细" in ln]
    assert line, d
    assert "7天最低" not in line[0] and "近7天" not in line[0], (
        "补偿行仍拼 p7（词面粘连）：" + line[0])
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref, "p7 参照行缺失：" + d
    assert ref[0].startswith("> 近7天直飞最低 ￥576（"), ref[0]
    assert rep._dw_line(ref[0]) <= 40, ref[0]


def test_empty_pool_p7_standalone_5digit_price(env, monkeypatch):
    """5 位价位带（主价位带上沿）：独立长形恒落位不塌地板。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    monkeypatch.setattr(
        rep, "_rounds",
        lambda db, fc, tc, d, am, **kw:
            [(datetime(2026, 9, 20, 8, 0), 12650.0, None)])
    n = FakeN()
    assert rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    d = n.sent["desp"]
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref and "￥12650" in ref[0], "5 位价参照行缺失：" + d
    assert rep._dw_line(ref[0]) <= 40, ref[0]


def test_constraint_empty_p7_standalone_quote_line(env, monkeypatch):
    """空约束分支（明细在但全被到达/衔接滤掉）同款独立行形态。"""
    rep = env["rep"]

    def _all_filtered(db, fc, tc, d, **kw):
        # 到达约束语义=当日达恒 OK、次日须 ≤02:00（_arrival_ok）——
        # 次日 03:30 达被淘汰；衔接 30min<90min 双保险不满足
        return [{"price": 900, "transCity": "兰州", "depTime": "08:00",
                 "arrTime": "03:30", "depDate": _DATE,
                 "arrDate": "2026-09-26", "layover": 30,
                 "_platform": "qunar"}]

    monkeypatch.setattr(rep, "_route_latest_flights", _all_filtered)
    n = FakeN()
    assert rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    d = n.sent["desp"]
    line = [ln for ln in d.splitlines() if "不满足到达/衔接约束" in ln]
    assert line and "近7天" not in line[0], line[0]
    # 补偿行自身恒 ≤40（r258 after 验收抓的回归：去 fallbacks 后长形
    # 51 宽超门直落——裸档 33 宽地板恒落位）
    assert rep._dw_line(line[0]) <= 40, line[0]
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref, "空约束分支 p7 参照行缺失：" + d
    assert rep._dw_line(ref[0]) <= 40, ref[0]


# ---------- P-2: last_push.md 写入来源标记 ----------

class _FakeResp:
    def __init__(self):
        self.text = '{"errcode":0,"errmsg":"ok"}'

    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    def __call__(self, url, **kw):
        self.payload = kw.get("json")
        return _FakeResp()


def _mk_notifier():
    import core.notifier as nm
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = _lg.getLogger("t258p")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    return n


def test_last_push_carries_source_marker(monkeypatch, tmp_path):
    """last_push.md 头注释带 pid/入口来源：并行非生产进程的写入可从
    内容分辨（十§4 mtime 对账取证不再被旁路写污染误导）。"""
    import os as _os
    monkeypatch.chdir(tmp_path)
    cap = _CapturePost()
    import core.notifier as nm
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = _mk_notifier()
    n.send("t", "正文内容")
    with open("debug/last_push.md", encoding="utf-8") as f:
        head = f.read()
    m = re.search(r"<!-- pid: (\d+) entry: (.+?) -->", head)
    assert m, "last_push.md 头注释缺来源标记（pid/entry）：" + head[:200]
    assert int(m.group(1)) == _os.getpid()
    # 实收正文仍在（取证锚语义不丢）：剥全部头注释行后逐字一致
    body = re.sub(r"\A(<!--[^>]*-->\n)+", "", head)
    assert body == cap.payload["markdown"]["text"]


# ---- merged from tests/test_r265_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_NOTES = [
    "乌鲁木齐→上海 10/15 当轮无数据：途牛、同程",
    "乌鲁木齐→上海 10/15 孤低价拦截×2：飞猪￥9900、去哪儿￥9500",
]


def test_daily_ops_fallback_renders_notes():
    """非空对账注逐条进兜底：告警路径同构词面（> ⚠️ 前缀），每行
    过 40 半角渲染宽守卫（_disp_dw 口径，含前缀整行计量）；宽头注
    按 _ops_fallbacks 地板档保头段（航线+日期+事由，与告警路径
    完全同构——渠道清单在 40 预算下装不下是单源定版行为）。"""
    out = _daily_ops_fallback(_NOTES)
    assert out
    assert out.count("> ⚠️ ") == 2
    assert "乌鲁木齐→上海 10/15" in out
    assert "当轮无数" in out and "孤低价拦" in out
    for ln in out.strip().split("\n\n"):
        assert _disp_dw(ln) <= 40, (ln, _disp_dw(ln))


def test_daily_ops_fallback_overwide_note_demoted():
    """超宽注（2+ 渠道缺失常态）走 _ops_fallbacks 降级链落位，不超
    红线也不整条蒸发（头段=对账起点恒在场）。"""
    wide = "乌鲁木齐→上海 10/15 当轮无数据：途牛、同程、飞猪、智行、美团"
    out = _daily_ops_fallback([wide])
    assert out and "> ⚠️ " in out
    assert "乌鲁木齐→上海 10/15" in out
    for ln in out.strip().split("\n\n"):
        assert _disp_dw(ln) <= 40, (ln, _disp_dw(ln))


def test_daily_ops_fallback_empty():
    """空注返空串：全勤无拦截时兜底区零占位（_daily_ops_notes 同律）。"""
    assert _daily_ops_fallback([]) == ""
    assert _daily_ops_fallback(None) == ""


def test_daily_both_image_fail_branches_consume():
    """源码钉：明细表图挂的两分支（上传失败 else / 渲染异常 except）
    同接 _daily_ops_fallback——能力对称只修一分支=另一分支图挂日
    对账注照旧蒸发（LESSONS 十九§14 空分支/兜底分支漏盘点判例）。"""
    src = open("report.py", encoding="utf-8").read()
    assert src.count("_daily_ops_fallback(") >= 3   # 定义 + 2 消费点


# ---- merged from tests/test_r286_push.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _fp(price, name, dpt, art, trans="", cross="", plat="qunar",
        dep="2026-10-05"):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else (2 if cross == "+2天" else 0)
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep,
            "arrDate": str(d0 + dt.timedelta(days=days)),
            "transCity": trans, "crossDayDesc": cross,
            "totalDuration": "6时", "_platform": plat}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _mk_alerter():
    class FakeN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            return True
    return Alerter(logging.getLogger("r286"), notifier=FakeN(),
                   storage=None, digest=True, storm_repeat=1, user="演练")


def _one_route_built(a, rows, dep="2026-10-05", th_direct=1900,
                     th_transfer=2600):
    r = Route(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=[dep], alert_direct=th_direct,
              alert_transfer=th_transfer)
    return r, [(r, a._build_sections(r, _ps(rows, "SHA", "URC", dep)))]


# ---------- P2-1: hits 头行联程剥档 ----------

def test_hits_head_codeshare_drops_tail_segment():
    """纯联程形态（无「｜」有「/」）：hits 头行保「首名+首码」剥
    「/」后段（红态=45/40 穿链直落地板，航班号整体消失——head 与
    seg 行均无码，命中行身份仅剩时刻+经停）。"""
    a = _mk_alerter()
    r, built = _one_route_built(a, [
        _fp(2590, "海南航空 HU7849/春秋9C8845", "08:30", "13:50",
            trans="郑州")])
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    assert "海南航空 HU7849" in pv["desp"], "首名+首码未保住（剥档缺席）"
    # head 行（> 🔥 开头）剥「/」后段；后段码仅从 head 剥失——KPI 行2
    # 剥首段档与总表图仍承载全码，seg 行只有时刻/跨天/经停无码
    head = next(ln for ln in pv["desp"].splitlines() if ln.startswith("> 🔥"))
    assert "春秋9C8845" not in head, \
        "「/」后段未剥（整名直落地板=航班号消失）"
    # 头行行宽恒达标（_disp_dw 剥链接量渲染宽）
    from core.alerter import _disp_dw
    assert _disp_dw(head) <= 40, "头行 %0.1f/40 超宽" % _disp_dw(head)


def test_hits_head_dual_name_unchanged():
    """双名形态（有「｜」）：既有剥名档行为零变化（保「金鹏航空
    Y87519」全段，联程档不插入不抢档——混合形态剥名档已保名+码）。"""
    a = _mk_alerter()
    r, built = _one_route_built(a, [
        _fp(2590, "新海航｜金鹏航空 Y87519", "08:30", "13:50",
            trans="郑州")])
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    assert "金鹏航空 Y87519" in pv["desp"], "双名剥名档行为被扰动"


# ---------- P2-2: compare 组日期跨度日历序 ----------

def test_compare_span_calendar_order():
    """多日期航线达标在后日期（重排后 sections[0]=后日期）：compare
    组头日期跨度按日历序「10/05-10/06」（红态=原序「10/06-10/05」
    倒挂直落总表图组头）。直调 _flights_table_md_multi，monkeypatch
    render/upload 截获 rows（不真渲染不真上传）。"""
    import report as report_mod
    a = _mk_alerter()
    r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
              to_name="上海", dates=["2026-10-05", "2026-10-06"],
              alert_direct=1600, alert_transfer=0)
    hit_a = _fp(1580, "南航CZ6993", "21:15", "23:55", dep="2026-10-06",
                plat="ctrip")
    hit_b = _fp(1650, "南航CZ6993", "21:15", "23:55", dep="2026-10-06",
                plat="qunar")   # 同班跨渠道（_fp_cands 指纹组需 ≥2 渠道）
    other = _fp(1690, "东航MU8370", "09:00", "14:10", dep="2026-10-05")
    s_hit = {"date": "2026-10-06", "pool": [dict(hit_a), dict(hit_b)],
             "top_direct": [dict(hit_a)], "top_transfer": [],
             "best_direct": dict(hit_a), "best_transfer": None}
    s_pre = {"date": "2026-10-05", "pool": [dict(other)],
             "top_direct": [dict(other)], "top_transfer": [],
             "best_direct": dict(other), "best_transfer": None}
    ordered = [s_hit, s_pre]   # 达标置前重排语义（_digest_payload ordered）
    captured = {}

    def fake_render(rows, title, out_png, summary=None, stamp_note="",
                    ops_notes=None):
        captured["rows"] = rows
        return None

    orig_render = report_mod.render_flights_table
    orig_upload = report_mod.upload_chart
    report_mod.render_flights_table = fake_render
    report_mod.upload_chart = lambda *a, **k: "http://127.0.0.1/fake.png"
    try:
        a._flights_table_md_multi([(r, ordered)])
    finally:
        report_mod.render_flights_table = orig_render
        report_mod.upload_chart = orig_upload
    assert "rows" in captured, "总表 rows 未产出（render 未被调？）"
    cmp_labels = [row[2] for row in captured["rows"]
                  if len(row) >= 3 and str(row[2]).startswith("同班比价")]
    assert cmp_labels, "compare 组缺席（候选未分组？）"
    lbl = cmp_labels[0]
    assert "10/05-10/06" in lbl, "组头日期非日历序: %s" % lbl
    assert "10/06-10/05" not in lbl, "组头日期倒挂在场"


# ---------- P3-1: 日报兜底标题零缓冲 ----------

def test_daily_top_fallback_headline_has_headroom():
    """图挂兜底标题不再恰满 40/40（红态=纯 CJK 恰卡线零缓冲，
    任何一字追加即窄屏折行断点失控）；正文行恒 ≤40。"""
    from report import _daily_top_fallback
    from core.alerter import _disp_dw
    row = _fp(1580, "南航CZ6993", "21:15", "23:55")
    row["_qual"] = False
    out = _daily_top_fallback([row], [])
    lines = [ln for ln in out.split("\n\n") if ln.strip()]
    assert lines, "兜底输出为空"
    for ln in lines:
        assert _disp_dw(ln) <= 38, \
            "行 %0.1f/40 仍零缓冲: %s" % (_disp_dw(ln), ln[:40])


# ---------- P3-2: 钉钉异常分支落账实收形态 ----------

def test_dingtalk_exception_ledger_records_sent_text(monkeypatch):
    """网络异常轮（读响应前断连=幽灵送达场景）账本落 text 实收形态
    （红态=落 desp 原文，截断轮三者对不上）。构造超长 desp 触发截断，
    monkeypatch httpx.post 抛异常（不真连），读重定向账本最后一行。"""
    import core.notifier as nm
    ding = nm.DingTalkNotifier("http://127.0.0.1:9/hook",
                               logging.getLogger("r286ding"))
    tail = "TAILMARK_r286_excep_branch"
    desp = "正文 " + "X" * 20000 + tail   # >18000B 触发截断
    monkeypatch.setattr(
        nm.httpx, "post",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ding.send("t", desp, launch="") is False
    path = os.environ.get("PUSH_HISTORY_FILE")
    assert path and os.path.exists(path), "账本重定向缺席"
    lines = [ln for ln in open(path, encoding="utf-8").read().splitlines()
             if ln.strip()]
    rec = json.loads(lines[-1])
    assert rec.get("ch") == "dingtalk" and rec.get("errcode") == -2, rec
    body = rec.get("desp", rec.get("content", ""))
    assert "内容超长已截断" in body, \
        "账本未落截断尾注（非实收 text 形态）"
    assert tail not in body, \
        "账本落的是截断前 desp 原文（记录≠实收）"


# ---------- P3-3: 空节防御 ----------

def test_digest_payload_skips_empty_sections():
    """空节 (route, []) 不再 IndexError（红态=L1981 ds_all[0] 炸）：
    入口防御跳过，产出与无该 entry 等价。"""
    a = _mk_alerter()
    r = Route(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-10-05"],
              alert_direct=1900)
    pv = a._digest_payload([(r, [])], fresh=True, with_tables=False)
    assert set(pv) >= {"title", "desp"}, "空节防御后产出形态缺失"


# ---- merged from tests/test_r289_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PLATS = ("ctrip", "qunar", "tuniu", "tongcheng", "fliggy")


def _row(plat, price=2110, name="南航CZ6766"):
    return {"price": price, "name": name, "code": name[-6:],
            "depTime": "10:00", "arrTime": "13:00", "_platform": plat}


# ---- P2-A：日报 ops 注缩写单源 ----

def test_daily_ops_notes_short_route_prefix():
    """无数据注用 _route_short 同源缩写（与告警侧同语言同宽度口径），
    全形 41/40 逼入病句地板的形态不再出现；全形+前缀恒 ≤40。"""
    notes = _daily_ops_notes(["qunar"], {"ctrip"}, ("海口", "上海"),
                             "2027-02-13")
    assert notes == ["海→上 02/13 当轮无数据：去哪儿"], notes
    for n in notes:
        assert _disp_dw("> ⚠️ " + n) <= 40, n


def test_daily_ops_notes_bag_direct_short_fits():
    """直挂标注缺失注随缩写收敛：经真实兜底链（_ops_fallbacks+
    _fit_line）后恒达标，且事由全文在可达档（k=1 档保「中转直挂
    标注缺失」语义，全名形态地板截「缺」字的病句不再出现）。"""
    from core.alerter import _fit_line, _ops_fallbacks
    mkt_t = [{"price": 1500, "name": "南航CZ6766", "transCity": "郑州"}]
    notes = _daily_ops_notes(
        list(_PLATS), set(_PLATS), ("海口", "上海"), "2027-02-13",
        mkt_t=mkt_t, transfer_baggage="direct")
    assert notes, "直挂缺失注应在场"
    assert any(n.startswith("海→上") and "直挂标注缺失" in n
               for n in notes), notes
    lines = [_fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
             for n in notes]
    for ln in lines:
        assert _disp_dw(ln) <= 40, ln
    assert any("中转直挂标注缺失" in ln for ln in lines), lines


# ---- P2-B：日报图挂兜底补同班比价段 ----

def test_daily_compare_fallback_block():
    """兜底比价段复用 _cross_compare 单源：组头+可省结论+价格链在场，
    守卫链行宽自守。"""
    from report import _daily_compare_fallback
    pool = [_row("ctrip", 2110), _row("qunar", 2400)]
    out = _daily_compare_fallback(
        pool, [], "2027-02-13")
    assert "同班比价" in out, out
    assert "可省" in out or "差" in out, out
    for ln in out.splitlines():
        assert _disp_dw(ln) <= 40 or ln.startswith("#"), ln


def test_daily_compare_fallback_empty_pool():
    """空候选返空串零占位（与 PNG 侧 _comp 组装同判据）。"""
    from report import _daily_compare_fallback
    assert _daily_compare_fallback([], [], "2027-02-13") == ""


def test_daily_compare_fallback_wired_both_branches():
    """消费点源钉：日报两处图挂失败分支（上传失败/渲染异常）都消费
    比价兜底段——只修一支=另一支比价警示仍沉没。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "report.py"), encoding="utf-8").read()
    assert src.count("_daily_compare_fallback(") >= 3, \
        "日报兜底分支对比价段的消费点不足（定义+两处调用）"


# ---- P3-A：各渠道最低同价合并 ----

def test_channel_market_lines_tie_merged():
    """五渠道同价（近实发轮常态）：5 行零增量复读合并单行「五渠道
    最低 …」，行宽守卫随合并前缀重排恒达标。"""
    import logging
    tops = {p: [_row(p)] for p in _PLATS}
    secs = [{"date": "2027-02-13", "plat_top3": tops,
             "platform_mins": {}}]
    a = Alerter(logging.getLogger("t"), storage=None)
    out = a._channel_market_lines(secs)
    assert out.count("最低") == 1, out
    assert "五渠道" in out, out
    assert "CZ6766" in out, out
    for ln in out.splitlines():
        assert _disp_dw(ln) <= 40, ln


def test_channel_market_lines_divergent_kept():
    """价格分异维持逐渠道行（合并条件=全部行 brief 逐字相等）。"""
    import logging
    tops = {p: [_row(p, 2110 + 30 * k)]
            for k, p in enumerate(_PLATS)}
    secs = [{"date": "2027-02-13", "plat_top3": tops,
             "platform_mins": {}}]
    a = Alerter(logging.getLogger("t"), storage=None)
    out = a._channel_market_lines(secs)
    assert out.count("最低") == 5, out


def test_daily_market_fallback_tie_merged():
    """日报侧同价合并（P3-D 与告警链同构后）：brief 逐字相等才合并
    且航班身份随行（「- 五渠道 最低 …CZ6766…」）；行缺席（纯价格
    形态）不产无身份合并行——逐渠道价格行如实分列。"""
    pmins = {p: (2110, True) for p in _PLATS}
    row = {"price": 2110, "code": "CZ6766", "name": "南航CZ6766",
           "depTime": "20:35", "arrTime": "23:55"}
    out = _daily_market_fallback(pmins, {p: dict(row) for p in _PLATS})
    assert "五渠道" in out, out
    assert out.count("最低") == 1, out
    assert "CZ6766" in out, out
    out2 = _daily_market_fallback(pmins)
    assert out2.count("最低") == 5, out2


def test_daily_market_fallback_divergent_kept():
    """日报侧分异维持逐渠道。"""
    pmins = {p: (2110 + 30 * k, True)
             for k, p in enumerate(_PLATS)}
    out = _daily_market_fallback(pmins)
    assert out.count("最低") == 5, out


# ---- P3-B：_fmt_brief 中档跨天辨识注 ----

def test_fmt_brief_cross_day_mid_tier_kept():
    """跨天行中档保留紧凑辨识注（+1天）：可达带（短码/低价）内中档
    不再丢跨天注（读者按到达时刻误判当日达=决策级误读）。六字码
    常态档 43/40 恒超走裸时刻档（窄带非死档：短码 3U33 级 39/40
    在场，实测 _disp_dw 口径）。"""
    f = {"price": 990, "name": "川航3U33", "code": "3U33",
         "depTime": "21:10", "arrTime": "00:40", "crossDayDesc": "+1天"}
    out = Alerter._fmt_brief(f)
    assert "(+1天)" in out, out
    assert _disp_dw(out) <= 40, out


def test_fmt_brief_cross_day_six_code_falls_bare():
    """六字码常态档：紧凑注 43/40 恒超，按链剥至裸时刻档（与既有
    行为逐字等价——非回归面）。"""
    f = {"price": 2110, "name": "东航MU6355", "code": "MU6355",
         "depTime": "21:10", "arrTime": "00:40", "crossDayDesc": "+1天"}
    out = Alerter._fmt_brief(f)
    assert out == "￥2110 直飞东航MU6355 21:10→00:40", out


def test_fmt_brief_same_day_shape_unchanged():
    """当日达行零回归：宽预算下全形保「当日达」；40 预算中档剥尾注
    形态保持（既有 P2-1 设计）。"""
    f = {"price": 2110, "name": "东航MU6355", "code": "MU6355",
         "depTime": "10:00", "arrTime": "13:00"}
    assert "当日达" in Alerter._fmt_brief(f, budget=60)
    assert "当日达" not in Alerter._fmt_brief(f)


def test_fmt_brief_cross_day_pathological_falls_bare():
    """病理长名跨天行：紧凑注档仍超时按链剥至裸时刻（地板价格恒落，
    恒达标律）。"""
    f = {"price": 2110, "name": "新海航｜海南航空HU7849", "code": "HU7849",
         "depTime": "21:10", "arrTime": "00:40", "crossDayDesc": "+1天"}
    out = Alerter._fmt_brief(f, budget=27)
    assert _disp_dw(out) <= 27, out
    assert "￥2110" in out, out


# ---- merged from tests/test_r296_push.py ----

# ---------- dep_win_txt 词面单源 ----------

def test_dep_win_txt_forms():
    """三形态与告警侧原内联构造逐字等价（抽函数零词面漂移）。"""
    assert dep_win_txt("19:00", "") == "（19:00后出发）"
    assert dep_win_txt("08:00", "22:00") == "（08:00–22:00）"
    assert dep_win_txt("", "22:00") == "（00:00–22:00）"
    assert dep_win_txt("", "") == ""
    # 配置带秒形态 [:5] 截断（告警侧原行为）
    assert dep_win_txt("19:00:00", "") == "（19:00后出发）"
    assert dep_win_txt(None, None) == ""


# ---------- 窗词面手抄残留收口（Soldier M-1） ----------

def test_push_title_depwin_no_handbuilt_residual():
    """推送标题链（_push_digest 未达标/已达标标题）的窗词面裸构造
    已收编 dep_win_txt 单源——残留计数钉（十六§3b 裸表达式残留
    收口）：`f"（{lo[:5]}` 形态（无下划线局部名的手抄构造）全文
    零残留；dep_win_txt 定义处用 _lo 命名不在锁面。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count('f"（{lo[:5]}') == 0
    assert src.count('f"（{lo}') == 0


# ---------- _route_section_title 接时段窗 ----------

def test_route_title_short_inline_with_win():
    """档1：标题+窗总宽 ≤38 内联（「#### 上海→海口 01/29（19:00
    后出发）」实宽 37）。"""
    out = _route_section_title(("上海", "海口"), "2027-01-29",
                               dep_win="（19:00后出发）")
    assert out == "#### 上海→海口 01/29（19:00后出发）\n\n"
    assert _dw(out.rstrip()) <= 38


def test_route_title_sinks_win_when_over():
    """档2：head ≤38 而 head+win >38（5 字名+窗实宽 43>38，head-only
    28）→ 窗下沉引用行（告警侧同构：日期在标题、窗独立引用行）。"""
    out = _route_section_title(("乌鲁木齐南", "海口"), "2027-01-29",
                               dep_win="（19:00后出发）")
    assert out == "#### 乌鲁木齐南→海口 01/29\n\n> （19:00后出发）\n\n"
    assert _dw(out.split("\n\n")[0]) <= 38


def test_route_title_long_name_floor_merges_win():
    """档3：本体超宽（双侧长自定义名）→ 逐字截 + 日期与窗合并
    同一条引用行（告警侧 sub=d_span+dep_win 同律：日期是跨天辨识
    信息不可丢，窗是过滤解释，两段都只在引用行承载）。"""
    out = _route_section_title(
        ("乌鲁木齐（地窝堡）", "上海（虹桥+浦东）"), "2027-01-29",
        dep_win="（19:00后出发）")
    lines = [ln for ln in out.split("\n\n") if ln]
    assert lines[0].startswith("#### ")
    assert _dw(lines[0]) <= 38
    assert "01/29" in lines[1]
    assert "19:00后出发" in lines[1]


def test_route_title_no_win_zero_regression():
    """无窗（默认参）：短名单行——与旧版逐字一致。"""
    assert _route_section_title(("上海", "海口"), "2027-01-29") == \
        "#### 上海→海口 01/29\n\n"


def test_route_title_sink_threshold_38():
    """38 缓冲对称：39-40 带（#### 加粗字模判例投影日报侧）——
    head 实宽 40（5+28+1+ceil(5.5)）→ 标题保名、日期下沉（旧档
    行为）；窗并入同一条引用行。"""
    out = _route_section_title(("七字城市名甲乙丙", "四字城市名"),
                               "2027-01-29", dep_win="（19:00后出发）")
    assert _dw("#### 七字城市名甲乙丙→四字城市名 01/29") == 40
    assert out == ("#### 七字城市名甲乙丙→四字城市名\n\n"
                   "> 01/29（19:00后出发）\n\n")


def test_route_title_win_sink_head38():
    """档2 实证：head ≤38（恰卡 38=5+26+1+6）而 head+窗 >38 →
    日期在标题、窗独立引用行下沉。"""
    out = _route_section_title(("七字城市名甲乙丙", "三字城市"),
                               "2027-01-29", dep_win="（19:00后出发）")
    assert _dw("#### 七字城市名甲乙丙→三字城市 01/29") == 38
    assert out == ("#### 七字城市名甲乙丙→三字城市 01/29\n\n"
                   "> （19:00后出发）\n\n")


def test_route_title_inline_37_zero_regression():
    """≤38 仍内联（首档活档非恒下沉）：实宽 37（ceil(37.0)）的
    短名+窗形态内联单行。"""
    out = _route_section_title(("上海", "海口"), "2027-01-29",
                               dep_win="（19:00后出发）")
    assert _dw("#### 上海→海口 01/29（19:00后出发）") == 37
    assert out == "#### 上海→海口 01/29（19:00后出发）\n\n"


# ---- merged from tests/test_r324_push_floor.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 审校实测越界样本：双侧 8+ 全角（49/40 与 64/40 的名字本体）
_LONG_HEAD = "阿拉善左旗超长名测试→乌鲁木齐地窝堡国际"
_LONG_HEAD_WIN = _LONG_HEAD + "（19:00后出发）"


def test_bare_floor_fits_long_names():
    """6 组长名输入全过 40 线，日期段恒在、无未配对「（」。"""
    for head in (_LONG_HEAD, _LONG_HEAD_WIN):
        for d in ("01/29", "01/30"):
            out = _bare_identity_floor(head, d)
            assert _disp_dw(out) <= 40, (head, d, out, _disp_dw(out))
            assert out.endswith(" " + d), out
            assert out.count("（") <= out.count("）"), out


def test_bare_floor_current_domain_verbatim():
    """现行 OD 域（2 全角城市词）不触发截名：逐字等于裸身份行。"""
    assert _bare_identity_floor("上海→海口", "01/29") == "> 上海→海口 01/29"


def test_suggest_taxpad_near_line_fits(monkeypatch):
    """pad>0 × fliggy × 擦边不足1% 组合域：基档确越界（41/40 族），
    去税注档承接后 ≤40（装配语义与源码钉互锁）。"""
    route = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐", dates=["2026-09-25"],
                  alert_direct=1000, alert_transfer=900)
    s = {"date": "2026-09-25",
         "best_direct": {"price": 1005, "name": "HO1251",
                         "depTime": "08:00", "arrTime": "10:35",
                         "_platform": "fliggy"},
         "best_transfer": None, "seen_plats": ["fliggy"]}
    a = Alerter(_lg.getLogger("t324f"), storage=None)
    monkeypatch.setattr(alerter, "FLIGGY_TAX_PAD", 100)
    sg = a._suggest_line(route, s)
    assert sg and "（税前价）" in sg, sg
    sg_line = f"> 💡 {sg}"
    assert _disp_dw(sg_line) > 40, (sg, _disp_dw(sg_line))
    fixed = _fit_line(sg_line, fallbacks=[
        sg_line.replace("（税前价）", ""), _clip_dw(sg_line, 40)])
    assert _disp_dw(fixed) <= 40, (fixed, _disp_dw(fixed))
    assert "税前价" not in fixed, fixed   # 次要信号先丢，判据词保全


def test_report_compare_fallback_survives_crash(monkeypatch):
    """保险丝自证：_cross_compare 抛任何异常，兜底返回空串不抛
    （旧码 except 引用未定义 logger=NameError 二次上抛）。"""
    import report

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(Alerter, "_cross_compare",
                        staticmethod(_boom))
    assert report._daily_compare_fallback([], [], "2026-01-01") == ""
    assert report._daily_compare_fallback(
        [], [], "2026-01-01", _lg.getLogger("t324f")) == ""


def test_source_pins_floor_wiring():
    """源码钉：地板档三链接线 + 去税注档 + 兜底 logger 透传。"""
    asrc = open(os.path.join(ROOT, "core", "alerter.py"),
                encoding="utf-8").read()
    assert asrc.count("_bare_identity_floor(") >= 4, (
        "def + 三链调用点应齐（best/补位/无明细）")
    assert "sg_line.replace(\"（税前价）\", \"\")" in asrc, (
        "建议行去税注档应在案")
    rsrc = open(os.path.join(ROOT, "report.py"), encoding="utf-8").read()
    assert rsrc.count(
        "_daily_compare_fallback(directs, mkt_t, date, logger)") == 2, (
        "两处调用点应透传 logger")


# ---- merged from tests/test_v15132_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    """日报对账注词面与告警链 _ops_notes 同族同源：「{航线短名}
    {日期} 当轮无数据：渠道、渠道」（「当轮」限定与同图近 6h 补位
    行不矛盾；短名经 Alerter._route_short 单源与告警侧同语言——
    全名形态恰超 0.5 半角逼入病句地板的形态已收口）；全勤返空列表
    不出注。"""
    from report import _daily_ops_notes
    notes = _daily_ops_notes(["qunar", "ctrip", "fliggy"], {"qunar"},
                             ("乌鲁木齐", "上海"), "2026-10-05")
    assert notes == ["乌→上 10/05 当轮无数据：携程、飞猪"]
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


# ---- merged from tests/test_v168_push.py ----

# ---- 标注文字面 AA ----------

def test_trend_label_text_uses_tx_token():
    """源码钉：标注文字填充对中转线色走 TX 令牌映射（白底块上过 AA）。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert 'fill=C_TRANSFER_TX if a["c"] == C_TRANSFER else a["c"])' in src


def test_trend_label_render_smoke(tmp_path):
    """中转序列真渲染出图（标注绘制路径整链走通，TX 映射行执行）。"""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 20, 8, 0, 0)
    d_vals = [2450, 2380, 2100, 1998, 1930, 1880, 1860, 1895, 1930]
    t_vals = [2600, 2520, 2350, 2260, 2140, 2050, 1720, 1690, 1688]
    qd = [False, False, False, False, False, True, True, True, False]
    ser = [(t0 + timedelta(minutes=30 * i), d_vals[i], t_vals[i],
            qd[i], i >= 6) for i in range(9)]
    out = str(tmp_path / "trend_v168.png")
    _rep.render_chart(ser, "v168 标注文字面", thresholds=(1900.0, 1700.0),
                      out_path=out)
    assert os.path.isfile(out)


# ---- bare 档硬保底 ----------

def test_bare_tier_hard_cap_40():
    """执行级钉：缺码+长航司名+角标全叠时 bare 档恒 ≤40 且保价格/时刻。"""
    f = {"name": "中国联合航空KN5807共享", "depTime": "14:00",
         "arrTime": "00:40", "price": 2898, "crossDayDesc": "次日",
         "_platform": "qunar", "_tie_n": 5}
    line = Alerter._fmt_flight_line(f, idx=3, mark="🔥")
    assert _disp_dw(line) <= 40
    assert "￥2898" in line and "14:00" in line and "00:40" in line


def test_bare_tier_normal_path_unchanged():
    """有码正常行不受截断影响（正常航班号完整保留）。"""
    f = {"code": "HU7849", "name": "海南航空HU7849", "depTime": "14:00",
         "arrTime": "00:40", "price": 2898, "_platform": "qunar"}
    line = Alerter._fmt_flight_line(f)
    assert "HU7849" in line


# ---- merged from tests/test_v181_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_URL = "https://example.invalid/x.png"


def _mk_route(i):
    return Route(from_code=f"AX{i:02d}", from_name="乌鲁木齐",
                 to_code=f"BY{i:02d}", to_name="上海",
                 dates=["2026-10-09"],
                 alert_direct=1900, alert_transfer=1700)


def _mk_section(route, price_d=2400, price_t=2250):
    f0 = {"price": price_d, "name": "南航CZ6976", "code": "CZ6976",
          "depTime": "08:20", "arrTime": "13:40", "transCity": "",
          "depDate": "2026-10-09", "arrDate": "2026-10-09",
          "totalDuration": "5时20分", "cabin": "经济舱"}
    ft = dict(f0, price=price_t, transCity="郑州", layoverT="2:55",
              layoverM=175, transferBaggage="direct", arrTime="23:50",
              name="海航HU7849", code="HU7849")
    return {"date": "2026-10-09",
            "top_direct": [f0], "top_transfer": [ft],
            "best_direct": f0, "best_transfer": ft,
            "best_transfer_mkt": ft,
            "n_direct": 8, "n_transfer_ok": 2,
            "platform_mins": {"qunar": price_d, "ctrip": price_d + 10},
            "plat_top3": {"qunar": [f0],
                          "ctrip": [dict(f0, price=price_d + 10)]},
            "src_platform": "qunar", "pool": [f0, ft],
            "all_flights": [f0, ft],
            "seen_plats": ["qunar", "ctrip"], "xphans": []}


def _build_rs(n, n_dates=1):
    # r318 心跳轻量化随迁：demoted 降级说明的载体在达标/回落轮（未达标
    # 轮 desp 压缩为单行恒低于预算，无降级面）——夹具改达标价
    # （1800+i ≤ 1900 线）触发全量小节的预算竞争，钉面语义不变
    rs = []
    for i in range(n):
        r = _mk_route(i)
        secs = []
        for d in range(n_dates):
            s = _mk_section(r, price_d=1800 + i, price_t=1700 + i)
            s["date"] = f"2026-10-{9 + d:02d}"
            for f in [s["best_direct"], s["best_transfer"],
                      *s["top_direct"], *s["top_transfer"]]:
                f["depDate"] = s["date"]
                f["arrDate"] = s["date"]
            secs.append(s)
        r.dates = [s["date"] for s in secs]
        rs.append((r, secs))
    return rs


def _payload(rs, with_tables=False, charts=False):
    log = logging.getLogger("t181")
    log.disabled = True
    al = Alerter(log, digest=True, at_mobile="13800138000")
    with mock.patch.object(report, "upload_chart",
                           (lambda *a, **k: FAKE_URL)), \
         mock.patch.object(report, "recent_platform_flights",
                           lambda *a, **k: {}):
        return al._digest_payload(rs, with_tables=with_tables,
                                  with_charts=charts)


# ---- P1-1 降级说明行行宽 ----

def test_demoted_note_line_within_40(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(24))
    lines = [ln for ln in p["desp"].split("\n") if "航线较多" in ln]
    assert lines, "降级说明行未出现（场景应触发 demoted）"
    for ln in lines:
        w = _disp_dw(ln)
        assert w <= 40, f"说明行 {w} 半角超手机行宽红线: {ln}"


# ---- P1-2 mini 字节入预算：总字节闭合 + 尾部段不被顶掉 ----

def test_bytes_closed_with_tables(tmp_path, monkeypatch):
    """场景 F（24 航线未达标带图）：总字节 ≤17900 切点、明细总表段
    恒在场（降级目标不被自身地板档顶掉）。"""
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(24), with_tables=True, charts=True)
    desp = p["desp"]
    assert len(desp.encode("utf-8")) <= 17900, \
        f"desp {len(desp.encode('utf-8'))}B 顶穿 notifier 切点"
    assert "明细总表" in desp, "尾部明细总表段被顶掉"


def test_bytes_closed_with_hits_at_tail(tmp_path, monkeypatch):
    """场景 C（1 达标 + 29 未达标带图）：hits 在场 → @段恒落 desp 尾
    且总字节闭合（@段是电话触达载体，最不该被尾部截断）。"""
    monkeypatch.chdir(tmp_path)
    # 构造 1 个达标航线（价 1500 < 阈值 1900/1700），其余 29 未达标
    rs = _build_rs(1) + _build_rs(29)
    for _r, secs in rs[:1]:
        for s in secs:
            s["best_direct"] = dict(s["best_direct"], price=1500)
            s["best_transfer"] = dict(s["best_transfer"], price=1500)
    p = _payload(rs, with_tables=True, charts=True)
    desp = p["desp"]
    assert len(desp.encode("utf-8")) <= 17900, \
        f"desp {len(desp.encode('utf-8'))}B 顶穿 notifier 切点"
    assert desp.endswith("@13800138000 "), "@段未落 desp 尾"
    assert "明细总表" in desp, "尾部明细总表段被顶掉"


def test_bytes_closed_mini_pressure(tmp_path, monkeypatch):
    """场景 B（8 航线×3 日期，24 个 📍 mini 纯文本）：预算闭合。"""
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(8, n_dates=3))
    assert len(p["desp"].encode("utf-8")) <= 17900


def test_normal_scale_payload_intact(tmp_path, monkeypatch):
    """生产规模（2 航线带图）零降级回归：desp 结构不变、mini 不出现。"""
    monkeypatch.chdir(tmp_path)
    p = _payload(_build_rs(2), with_tables=True, charts=True)
    desp = p["desp"]
    assert "📍" not in desp, "生产规模不应触发 mini 降级"
    assert "明细总表" in desp


# ---- merged from tests/test_v204_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_short_name_full_form():
    """正常短名：全形态（城市+日期+完整说明），日期在行。"""
    line = _miss_chart_line("乌鲁木齐→上海", "2026-10-06")
    assert "乌鲁木齐→上海" in line
    assert "10/06" in line
    assert "本期无图" in line


def test_long_name_floor_keeps_date():
    """长自定义城市名（双侧超宽）：末档截城市名保日期——多日期航线
    可定位缺图期；行宽恒 ≤40 半角（手机 20 全角）。"""
    nm = "非常长的自定义城市名称甲→非常长的自定义城市名称乙"
    line = _miss_chart_line(nm, "2026-10-06")
    assert _dw(line) <= 40
    assert "10/06" in line          # 辨识信息恒在
    assert "…" not in line          # U+2026 禁令
    assert "本期无图" in line


def test_extreme_long_name_still_guarded():
    """极端超名（单侧 30+ 半角）：仍 ≤40 且保日期。"""
    nm = "超超超超超超超超超超超超超超超超超长→名"
    line = _miss_chart_line(nm, "2026-10-06")
    assert _dw(line) <= 40
    assert "10/06" in line


def test_never_worse_than_mid_tier():
    """短名全形态也 ≤40（守卫链首档即达标，无静默超宽残留）。"""
    for nm in ("乌→上", "乌鲁木齐→上海", "上海→乌鲁木齐"):
        assert _dw(_miss_chart_line(nm, "2026-10-06")) <= 40


def test_floor_keeps_both_sides():
    """地板档双侧均分截（_section_title 同律）：到达侧短名不被出发侧
    整侧吞掉，同日双向航线（长→短 / 短→长）缺图行方向可辨——整串
    逐字截曾把到达侧整侧吞掉（Soldier P2-1）。"""
    a = "非常长的自定义城市名称甲"
    l1 = _miss_chart_line(f"{a}→乙", "2026-10-06")
    l2 = _miss_chart_line(f"乙→{a}", "2026-10-06")
    assert _dw(l1) <= 40 and _dw(l2) <= 40
    assert "10/06" in l1 and "10/06" in l2
    assert "乙" in l1 and "乙" in l2          # 短侧恒在
    assert l1 != l2, "双向缺图行同串=方向不可辨"


def test_floor_both_long_within_budget():
    """双侧超长：均分截后 ≤40、日期恒在（同前缀极端对的方向边界
    与 _section_title 同律接受）。"""
    a = "非常长的自定义城市名称甲"
    b = "非常长的自定义城市名称乙"
    for nm in (f"{a}→{b}", f"{b}→{a}"):
        line = _miss_chart_line(nm, "2026-10-06")
        assert _dw(line) <= 40
        assert "10/06" in line
