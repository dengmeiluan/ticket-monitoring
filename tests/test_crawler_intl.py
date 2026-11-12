# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r331_intl_trend.py
- tests/test_r682_intl_rows_without_flight_no.py
- tests/test_r940_intl_rotation.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import glob
import io
import json
import logging
import os
import sys
import time

from crawlers.app_zhixing_parse import detect_state, parse_flight_rows
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r331_intl_trend.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r331_intl_trend")
_QN = QunarCrawler({}, _LOG)


def _resp(data=None, code=0, bstatus=None):
    o = {"code": code, "ret": True}
    if bstatus is not None:
        o["bstatus"] = {"code": bstatus}
    if data is not None:
        o["data"] = data
    return json.dumps(o)


def _trend(pts):
    return {"trendPrice": {"goFTrend": pts}}


def _tp(pts):
    """trendPrice dict 本体（_parse_trend_go 的入参语义）。"""
    return {"goFTrend": pts}


def _pt(d, p):
    return {"price": p, "date": d, "index": 0}


def _route_row(**over):
    row = {
        "code": "NH960",
        "minPrice": 2380, "nakedPrice": 1860, "taxPrice": 520,
        "transCity": "",
        "cabinDesc": "经济舱",
        "fewTicket": "",
        "binfo": {"depTime": "09:30", "arrTime": "14:00",
                  "depDate": "2026-11-16", "arrDate": "2026-11-16"},
    }
    row.update(over)
    return row


# ---- 接线：最低价行挂 trendGo ----

def test_intl_trend_mounts_lowest_row():
    """带趋势的响应：最低价行挂 trendGo，点数=有效点数、MM-DD 形态。"""
    pts = ([_pt(f"2026-11-{d:02d}", str(1000 + d)) for d in range(1, 16)]
           + [_pt(f"2026-11-{d:02d}", "") for d in range(16, 31)])
    data = _trend(pts)
    data["routes"] = [_route_row(), _route_row(minPrice=1200,
                                               code="NH961")]
    rows, risk = _QN._parse_intl_response(_resp(data))
    assert risk == "" and len(rows) == 2
    tg_rows = [r for r in rows if r.get("trendGo")]
    assert len(tg_rows) == 1, "只挂当轮最低价行（防 extra 膨胀，同国内律）"
    tg = tg_rows[0]["trendGo"]
    assert tg_rows[0]["price"] == 1200
    assert len(tg) == 15, "空串价点丢弃（远期无报价 15/30 实证形态）"
    assert tg[0] == ["11-01", 1001]
    assert all(len(p[0]) == 5 for p in tg), "日期 MM-DD 形态（消费端协议）"


def test_intl_trend_absent_no_key():
    """无 trendPrice（旧形态/零航班轮）：不落键，行解析零回归。"""
    rows, _ = _QN._parse_intl_response(
        _resp({"routes": [_route_row()]}))
    assert len(rows) == 1 and "trendGo" not in rows[0]


# ---- 值域门：国际宽带单源 ----

def test_intl_band_keeps_high_price_default_keeps_domestic():
    """intl 分档：>50000 点保留（国际宽带 200000，长途高价实证）；
    默认（国内路径）维持 50000 门行为零变化。"""
    pts = [_pt("2026-11-09", "78139"), _pt("2026-11-10", "709"),
           _pt("2026-11-11", "99999"), _pt("2026-11-12", "")]
    tg = _QN._parse_trend_go(_tp(pts), intl=True)
    assert tg == [["11-09", 78139], ["11-10", 709], ["11-11", 99999]]
    tg_dom = _QN._parse_trend_go(_tp(pts))
    assert tg_dom == [["11-10", 709]], "国内门行为零变化"
    # 200000 上界同样生效（带外垃圾价仍丢）
    assert _QN._parse_trend_go(
        _tp([_pt("2026-11-09", "200001")]), intl=True) is None


# ---- 回放：冻结 dump 过真实解析器（锁相对语义，不锚瞬时计数）----

def test_intl_dump_replay_relative_semantics():
    """生产 dump 回放：19 份国际 dump（活文件，锁结构关系不锁瞬时值）——
    有行且解出 trendGo 的份：点数 1..30、价带内、MM-DD 形态；
    零航班轮（flights=[]）无挂载点不产 trendGo 且不炸。
    语料缺席（CI/新克隆无 debug/ dump）本钉空转不假红。"""
    dumps = sorted(glob.glob("debug/qunar_raw_intl_*"))
    if not dumps:
        return
    n_ok = n_rows = 0
    for fp in dumps:
        txt = open(fp, encoding="utf-8", errors="ignore").read()
        rows, _ = _QN._parse_intl_response(txt)
        if not rows:
            continue
        n_rows += len(rows)
        for r in rows:
            tg = r.get("trendGo")
            if tg is None:
                continue
            n_ok += 1
            assert 1 <= len(tg) <= 30
            assert all(len(p) == 2 and len(p[0]) == 5 for p in tg)
    # 结构下限：生产语料在场时至少解出行
    assert n_rows > 0


# ---- merged from tests/test_r682_intl_rows_without_flight_no.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _intl_card(top, dep, arr, price, airline, dur="全程2h55m"):
    """国际卡片：无航班号。"""
    return "".join([
        _n(dep, 34, top, 248, top + 38),
        _n(dur, 270, top, 345, top + 21),
        _n(arr, 499, top, 583, top + 38),
        _n(price, 803, top, 865, top + 38),
        _n("￥", 790, top + 13, 803, top + 36),
        _n("浦东T2", 34, top + 36, 160, top + 61),
        _n("羽田T3", 526, top + 36, 583, top + 61),
        _n("补贴后价", 793, top + 38, 865, top + 59),
        _n(airline, 54, top + 76, 126, top + 101),
        _n("已优惠¥5", 794, top + 77, 860, top + 99),
    ])


def _xml(cards, header="<hierarchy rotation=\"0\">"):
    return header + "".join(cards) + "</hierarchy>"


def test_intl_cards_parsed_without_flight_no():
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "春秋航空"),
                _intl_card(642, "08:55", "13:00", "1068", "春秋航空日本")])
    rows = parse_flight_rows(xml)
    assert len(rows) == 2, rows
    assert [r["depart_time"] for r in rows] == ["21:10", "08:55"]
    assert [r["arrive_time"] for r in rows] == ["01:05", "13:00"]
    assert [r["price"] for r in rows] == [988, 1068]
    assert all(not r["flight_no"] for r in rows), "不得凭空编航班号"


def test_intl_rows_carry_airline_name():
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "日本乐桃航空")])
    rows = parse_flight_rows(xml)
    assert rows and rows[0].get("airline") == "日本乐桃航空", rows


def test_intl_page_detected_as_ok_so_crawler_stops_waiting():
    """detect_state 若仍判 unknown，明细路径会一直轮询到超时。"""
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "春秋航空"),
                _intl_card(642, "08:55", "13:00", "1068", "吉祥航空")])
    assert detect_state(xml) == "ok"


def test_home_page_date_strip_is_not_mistaken_for_cards():
    """首页日期条只有「¥910」这类整串价，没有时刻对——不得判成 ok。

    误判会把「首页」当成「列表页已出数据」，直接拿首页解析出空行。
    """
    xml = _xml([_n("上海", 42, 451, 106, 494),
                _n("东京", 794, 451, 858, 494),
                _n("11-18", 41, 118, 120, 140),
                _n("¥910", 41, 142, 83, 164),
                _n("11-19", 154, 118, 233, 140),
                _n("¥996", 154, 142, 200, 164)])
    assert detect_state(xml) != "ok"
    assert parse_flight_rows(xml) == []


def test_promo_times_never_become_rows():
    """「全程2h55m」「已优惠¥5」这类数字片段不得被拼成航班行。"""
    xml = _xml([_n("新客补贴", 186, 256, 270, 285),
                _n("¥", 137, 258, 147, 283),
                _n("5", 147, 253, 160, 285),
                _n("机酒订立返", 625, 256, 730, 285),
                _n("¥", 563, 258, 573, 283),
                _n("50", 573, 253, 599, 285)])
    assert parse_flight_rows(xml) == []


def test_transfer_card_carries_stop_city():
    """中转卡片必须标出经停城市。

    真机 11-06：首卡「10:25→10:05 / 全程23h40m / 青岛 20h35m / ￥450」，
    没有航班号。改按时刻锚定后它曾是**第一条被放行的行**——如果不标
    transCity，下游会把它当直飞塞进直飞最优池，还把行头价压到 450。
    """
    xml = _xml([_n("10:25", 34, 297, 245, 335),
                _n("全程23h40m", 248, 297, 345, 318),
                _n("10:05", 460, 297, 544, 335),
                _n("450", 803, 297, 865, 335),
                _n("￥", 790, 310, 803, 333),
                _n("首都T3", 34, 333, 160, 358),
                _n("浦东T2", 487, 333, 544, 358),
                _n("青岛 20h35m", 246, 343, 460, 364),
                _n("山航", 54, 372, 126, 397)])
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["trans_city"] == "青岛", rows


def test_direct_card_has_no_stop_city():
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "春秋航空")])
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["trans_city"] == "", rows


def test_airline_never_takes_toolbar_or_section_labels():
    """排序栏「比价」、表头「时间」、区头「国内中转」都不是航司名。"""
    xml = _xml([_n("比价", 500, 201, 560, 224),
                _n("时间", 185, 372, 239, 397),
                _intl_card(471, "21:10", "01:05", "988", "春秋航空")])
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["airline"] == "春秋航空", rows


# ---- merged from tests/test_r940_intl_rotation.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _crawler(tmp_path=None):
    """测试专用 crawler：**不读生产轮转文件**（否则断言受真实状态影响）。"""
    import tempfile
    root = str(tmp_path) if tmp_path is not None else tempfile.mkdtemp(prefix="r940_")
    return QunarCrawler({"user_data_dir": root, "profile": "qunar"}, None)


def _arm_quiet(c, left_s=600, reason="上一条国际查询软空/限流"):
    c._intl_quiet_until = time.time() + left_s
    c._intl_quiet_reason = reason
    return c._intl_quiet_until


# ---------------------------------------------------------------------------
# 1. 状态初始化
# ---------------------------------------------------------------------------
def test_state_initialised():
    c = _crawler()
    assert isinstance(c._intl_route_seen, dict) and c._intl_route_seen == {}
    assert c._intl_bypass_at == 0.0


# ---------------------------------------------------------------------------
# 2. 核心：从没轮到的航线，第一个让位窗口要放它一次
# ---------------------------------------------------------------------------
def test_never_tried_route_bypasses_once():
    c = _crawler()
    _arm_quiet(c)
    assert _would_bypass(c, "SHA", "BKK") is True, \
        "从没轮到过的航线被让位挡掉了（这就是饿死的根因）"


def test_bypass_only_once_per_window():
    """同一让位窗口内，绕过一次之后其余航线必须让位。"""
    c = _crawler()
    win = _arm_quiet(c)
    assert _would_bypass(c, "SHA", "BKK") is True      # 第一条绕过
    c._intl_bypass_at = win                            # 模拟"绕过已用"
    c._intl_route_seen["SHA-BKK"] = time.time()
    assert _would_bypass(c, "SHA", "SIN") is False, \
        "同一窗口内又放了一条：会连撞 1999"


def test_new_window_allows_next_route():
    """下一个让位窗口（until 变了）：轮到下一条。"""
    c = _crawler()
    old = _arm_quiet(c)
    c._intl_bypass_at = old
    c._intl_route_seen["SHA-BKK"] = time.time()
    assert _would_bypass(c, "SHA", "SIN") is False, "旧窗口不该再放"

    # 新窗口（until 改变）
    new = _arm_quiet(c, left_s=900)
    assert new != old
    assert _would_bypass(c, "SHA", "SIN") is True, "新窗口没有轮到下一条"


# ---------------------------------------------------------------------------
# 3. 刚成功过的航线不该抢这个口子
# ---------------------------------------------------------------------------
def test_recently_served_route_does_not_bypass():
    c = _crawler()
    _arm_quiet(c, reason="上一条国际明细已成功")
    c._intl_route_seen["SHA-NRT"] = time.time() - 30      # 刚查过
    assert _would_bypass(c, "SHA", "NRT") is False, \
        "刚查过的航线又绕过：配额会被它独吞"


def test_long_starved_route_bypasses():
    """超过半个让位窗口（450s）没轮到：算饿死，放行。"""
    c = _crawler()
    _arm_quiet(c)
    c._intl_route_seen["SHA-LHR"] = time.time() - 1200
    assert _would_bypass(c, "SHA", "LHR") is True


# ---------------------------------------------------------------------------
# 4. 没有让位窗口时：不受影响（正常查询）
# ---------------------------------------------------------------------------
def test_no_quiet_window_means_no_gate():
    c = _crawler()
    c._intl_quiet_until = 0.0
    assert _would_bypass(c, "SHA", "BKK") is True       # 无窗口 = 正常放行


# ---------------------------------------------------------------------------
# 5. 源码钉
# ---------------------------------------------------------------------------
def test_source_has_rotation():
    src = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                  encoding="utf-8").read()
    assert "_intl_route_seen" in src, "没有记录'上次轮到'的状态"
    assert "_intl_bypass_at" in src, "没有'每窗口只绕过一次'的闸"
    assert "国际航线轮转" in src, "没有可读的轮转日志"




# ---------------------------------------------------------------------------
# 6. 持久化：重启后轮转必须**接着走**（本轮核心）
# ---------------------------------------------------------------------------
def test_rotation_persists_across_restart(tmp_path):
    """`_intl_route_seen` 必须落盘。

    2026-11-04：轮转状态原来只放内存，**每次进程重启就清空**，而配置里
    第一条永远是 SHA→NRT —— 结果"NRT 每次都吃到重启后的第一份配额"。
    当天重启了 6 次，等于把轮转永久钉在第一条上。

    落盘之后，即使每轮都重启，4 条国际航线也能公平轮完。
    """
    import json
    import os as _os
    cfg = {"user_data_dir": str(tmp_path), "profile": "qunar"}
    routes = [("SHA", "NRT"), ("SHA", "BKK"), ("SHA", "SIN"), ("SHA", "LHR")]
    got = []
    for rnd in range(4):
        c = QunarCrawler(cfg, None)          # 每轮都是"新进程"
        c._intl_quiet_until = time.time() + 600 + rnd * 1000
        for fc, tc in routes:
            if _would_bypass(c, fc, tc):
                got.append(tc)
                c._intl_bypass_at = c._intl_quiet_until
                c._intl_route_seen["%s-%s" % (fc, tc)] = time.time()
                c._save_intl_rotation()
                break                         # 一窗口只放一条
    assert got == ["NRT", "BKK", "SIN", "LHR"], got
    # 文件真的写出来了
    p = _os.path.join(str(tmp_path), "qunar", "intl_rotation.json")
    assert _os.path.isfile(p)
    assert len(json.load(open(p, encoding="utf-8"))) == 4


def test_rotation_file_corrupt_is_tolerated(tmp_path):
    """轮转文件损坏：当作"都没轮到过"，不许抛。"""
    import os as _os
    d = _os.path.join(str(tmp_path), "qunar")
    _os.makedirs(d, exist_ok=True)
    with open(_os.path.join(d, "intl_rotation.json"), "w",
              encoding="utf-8") as f:
        f.write("{not-json")
    c = QunarCrawler({"user_data_dir": str(tmp_path), "profile": "qunar"}, None)
    assert c._intl_route_seen == {}


def test_rotation_save_is_fail_soft(tmp_path):
    """写不进去也不能抛（采集优先）。"""
    c = QunarCrawler({"user_data_dir": "/definitely/not/writable/\x00",
                      "profile": "qunar"}, None)
    c._intl_route_seen["X-Y"] = 1.0
    c._save_intl_rotation()        # 不该抛

# ---------------------------------------------------------------------------
# helper：复刻 fetch() 里的让位判定（不发请求）
# ---------------------------------------------------------------------------
def _would_bypass(c, fc, tc):
    """True = 越过让位窗口放行。"""
    if not (c._intl_quiet_until > time.time()):
        return True
    key = "%s-%s" % (fc, tc)
    last = float(c._intl_route_seen.get(key) or 0)
    starved = (time.time() - last) >= max(60.0, c.INTL_SOFT_QUIET_S / 2)
    never = last <= 0
    bypass_ok = (c._intl_bypass_at != c._intl_quiet_until)
    return bool((never or starved) and bypass_ok)
