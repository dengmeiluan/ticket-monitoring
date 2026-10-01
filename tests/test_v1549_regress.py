# -*- coding: utf-8 -*-
"""回归测试：每个用例对应本轮五路调研修掉的一个真实缺陷。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1549_regress.py -q
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import (Alerter, gap_txt, kpi_tier_txt,  # noqa: E402
                          URGENT_FAIL_NOTE, _dw, _qual_price)
from core.models import Route  # noqa: E402


def _mk_route(ad=1900, at=1700):
    return Route(from_code="SHA", to_code="URC", from_name="上海",
                 to_name="乌鲁木齐", dates=["2026-09-25"],
                 alert_direct=ad, alert_transfer=at)


def _mk_sections(direct_price, transfer_price=None):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        s["best_direct"] = {"price": direct_price, "name": "MU8369",
                            "depTime": "19:55", "arrTime": "01:25",
                            "_platform": "qunar"}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
    return [s]


# ---- P1：单航线 digest 达标分支 4 元组按 3 元解包（发送前 ValueError 哑弹） ----
def test_digest_push_with_hits_no_unpack_crash(monkeypatch, tmp_path):
    """hits 是 4 元组（kind, f, th, s），_send_urgent 组装处曾按 3 元
    解包——达标分支一旦进入整轮推送在发送前抛 ValueError。变异验证：
    旧代码本用例必炸（hits 非空才可达该行，无 hits 分支不覆盖此雷）。"""
    import report as _rep

    monkeypatch.setattr(_rep, "render_flights_table",
                        lambda *a, **k: str(tmp_path / "x.png"))
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")
    sent = []

    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    a = Alerter(logging.getLogger("t"), notifier=FakeN(), storage=None,
                digest=True, user="t")
    r = _mk_route(ad=1900)
    s = _mk_sections(1850)[0]          # 1850 < 1900 → 达标 hit 进入
    s["top_direct"] = [s["best_direct"]]
    s["top_transfer"] = []
    a._push_digest(r, [s])             # 不得抛 ValueError
    assert sent, "达标分支整轮推送哑弹"
    assert "达标" in sent[0][0] or "达标" in sent[0][1], sent[0][0]


# ---- 恰达线词面：gap_txt/kpi_tier_txt 与四档纪律同字 ----
def test_gap_txt_exact_threshold_words():
    # diff==0：达标口径「真达标」（旧「达标」与图例差一字）、行情口径「行情破线」
    assert gap_txt(1600, 1600, True) == "真达标"
    assert gap_txt(1600, 1600, False) == "行情破线"
    assert gap_txt(1550, 1600, True) == "低￥50"
    assert gap_txt(1650, 1600, False) == "差￥50"


def test_kpi_tier_txt_near_word_short():
    # 擦边词面缩短（multi 总表 summary 4 bits 恒降 11px 的宽度 root fix）
    out = kpi_tier_txt("直飞", 1749, 1600, False)   # 149/1600≈9.3% ≤10%
    assert "擦边9%" in out and "距线" not in out, out
    assert kpi_tier_txt("中转", 1600, 1600, True) == "中转 ￥1600 真达标"
    assert kpi_tier_txt("直飞", 1580, 0, False) == "直飞 ￥1580（未设线）"


# ---- _suggest_line：手拼差额词旁路 + 判定/数字混基 ----
def test_suggest_line_exact_threshold_no_zero_yuan():
    """qual 价恰等于线：旧词「达标 低￥0，建议出手」（低￥0 自相矛盾）。"""
    a = Alerter(logging.getLogger("t"), storage=None)
    s = _mk_sections(1900)[0]
    tl = a._suggest_line(_mk_route(ad=1900), s)
    assert "低￥0" not in tl and "真达标" in tl and "出手" in tl, tl


def test_suggest_line_danstalk_market_base():
    """蹲守档与行情同基（定律补完实现）：判定用行情价、金额
    不用达标口径价——同消息 KPI 行1「低￥10」与建议行「差￥50」两数
    互斥。行情最优 ￥1590 已破线、达标口径最优 ￥1750 未破线时：
    建议行须读行情低￥110，不得读达标差￥50。"""
    a = Alerter(logging.getLogger("t"), storage=None)
    s = _mk_sections(None)[0]
    s["best_transfer"] = {"price": 1750, "name": "CZ6976转",
                          "depTime": "12:05", "arrTime": "23:50",
                          "transCity": "郑州", "_platform": "ctrip"}
    # 行情最优（可能不满足直挂/衔接）：价已破线
    s["best_transfer_mkt"] = dict(s["best_transfer"], price=1590)
    tl = a._suggest_line(_mk_route(at=1700), s)
    assert "低￥110" in tl, tl
    assert "差￥50" not in tl, tl


# ---- 强提醒失败警示行：单源 + 行宽缓冲 ----
def test_urgent_fail_note_single_source_and_width():
    assert _dw(URGENT_FAIL_NOTE) <= 38, _dw(URGENT_FAIL_NOTE)   # 旧恰满 40/40
    assert "出手前请自查" not in URGENT_FAIL_NOTE


# ---- 哨兵：结构性死键豁免 / 0 命中键死观测 / 渠道明细全空 ----
def _sent(monkeypatch, tmp_path, prices):
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    class _I:
        def info(self, *a, **k):
            pass

    rows = [_NS(platform=pf, extra=json.dumps(rs)) for pf, rs in prices]
    _m._field_sentinel(rows, _L())
    return seen, _I, _m


def test_field_sentinel_dead_keys_skipped(monkeypatch, tmp_path):
    """死键表（qunar|prate、fliggy|meal/cabin）：现役路径无源，继续
    观测=健康渠道天天假告警（键名三方对账定论）。夹具
    share/few/term 带生产形态命中值——断言收敛 seen==[]（排他性：白
    名单若误加无源组合，本测试红）。qunar|plane 已移出
    死键表（H5 binfo.name 有源），夹具同律带命中值防假键死。"""
    rows = [{"price": 1000, "cabin": "经济舱", "meal": "有餐食",
             "prate": "", "plane": "波音737(中)",
             "shareCarrier": "MU5700" if i % 3 == 0 else "",
             "fewTicket": "仅剩5张" if i % 5 == 0 else "",
             "arrTerminal": "T2",
             # depAirport 带命中（apt 入比率观测：qunar H5
             # binfo 层近全量在场，夹具缺值=假键死）。planeSize 同律
             # （随 plane 移出死键表：binfo.name 括号同源）。
             # IATA 码带命中（aptc 入比率观测，同律）；
             # discount 同律（「全价」并入后五渠道恒有源）
             "discount": "4.5折",
             "depAirport": "乌鲁木齐天山", "planeSize": "中型机",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for i in range(30)]
    seen, _I, _m = _sent(monkeypatch, tmp_path, [("qunar", rows)])
    assert seen == [], seen


def test_field_sentinel_zero_hit_field_death(monkeypatch, tmp_path):
    """有源渠道新决策字段恒 0 命中=键死（tx→td 事故模式），样本 ≥20
    才判——共享覆盖率随航线波动（DB 实测 20-40%），比率阈值会误报。"""
    dead = [{"price": 1000, "cabin": "经济舱", "shareCarrier": ""}
            for _ in range(30)]
    seen, _I, _m = _sent(monkeypatch, tmp_path, [("ctrip", dead)])
    assert any("shareCarrier" in str(a) for a in seen), seen
    alive = [dict(dead[i], shareCarrier="MU5700" if i % 4 == 0 else "")
             for i in range(30)]
    seen2, _I, _m = _sent(monkeypatch, tmp_path, [("ctrip", alive)])
    assert not any("shareCarrier" in str(a) for a in seen2), seen2


def test_field_sentinel_no_detail_rows(monkeypatch, tmp_path):
    """渠道明细全空（extra 空/解析败/无价行）：≥2 条记录才报——该形态
    对字段/塌方/脉冲三面隐形。1 条空记录是常态波动不入报。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

        def info(self, *a, **k):
            pass

    # extra 全空（无 bucket 形态——最该报的死角）×2 → 报
    _m._field_sentinel([_NS(platform="tuniu", extra=""),
                        _NS(platform="tuniu", extra="")], _L())
    assert any("明细 0 行" in str(a) for a in seen), seen
    # 无价行（[{}]）×2 → 报；单条 → 不报（块间清当日去重态）
    seen.clear()
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._field_sentinel([_NS(platform="tuniu", extra="[{}]"),
                        _NS(platform="tuniu", extra="[{}]")], _L())
    assert any("明细 0 行" in str(a) for a in seen), seen
    seen.clear()
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._field_sentinel([_NS(platform="tuniu", extra="[{}]")], _L())
    assert not any("明细 0 行" in str(a) for a in seen), seen


# ---- qunar H5 分片还原：合成乱序串回放（算法锁死防渠道改参静默死） ----
def _scramble(s, ctr, k):
    """按还原算法的置换逆序构造乱序串（置换为不相交对换，自逆）。"""
    frags = [s[i:i + ctr] for i in range(0, len(s) - ctr + 1, ctr)]
    suffix = s[len(frags) * ctr:]
    i, j = 0, ctr % k
    while j < len(frags):
        frags[i], frags[j] = frags[j], frags[i]
        i, j = j + 1, j + 1 + (ctr % k)
    return "".join(frags) + suffix


def test_reassemble_h5_roundtrip():
    from crawlers.qunar import QunarCrawler
    obj = {"flights": [{"code": "MU8369", "minPrice": "1580"},
                       {"code": "CZ6981", "minPrice": "1620"}]}
    raw = json.dumps(obj, ensure_ascii=False)
    # 完整/未乱序形态（counter%k==0 恒等置换）直接可解
    assert QunarCrawler._reassemble_h5_data(raw) == obj
    # 真浏览器分支 k=8、反爬降级分支 k=3：ctr=26（26%8=2、26%3=2 均
    # 非零 → 真置换非恒等，还原循环/ctr 暴力/'{"' 预筛全被走到）
    for k in (8, 3):
        scr = _scramble(raw + " " * (26 - len(raw) % 26), 26, k)
        assert scr != raw, (k, "恒等置换，测试失效")
        out = QunarCrawler._reassemble_h5_data(scr)
        assert out == obj, (k, out)
    # 结构校验兜底：非 flights 形态拒收
    assert QunarCrawler._reassemble_h5_data(json.dumps({"a": 1})) is None
    assert QunarCrawler._reassemble_h5_data("") is None


# ---- 总表图：全字段行容量重组 + summary 列表宽度预算 ----
def test_flights_table_full_fields_capacity(tmp_path):
    """全字段行（机型·舱位·折扣·准点·餐食·托运·共享·余票）
    ~489px 曾击穿两行容量 → plan=None 整行省略（决策字段零省略破口）。
     优先级重组（丢折扣→机型重试拆行）后渲染必须成功且行高
    只增 16（拆两行），不得整行回退省略。"""
    from PIL import Image
    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("行高拆行判定依赖 Windows 中文字体度量（CI 无雅黑）")
    import report as _rep
    base = {"price": 1000, "name": "CZ6981", "depTime": "08:00",
            "arrTime": "10:00", "_platform": "qunar", "transCity": ""}
    bare = dict(base)
    full = dict(base, plane="空客339(大)", cabin="超级经济舱",
                discount="6.7折", prate="100", meal="无餐食",
                baggage="托运20kg", shareCarrier="南方航空CZ6993",
                fewTicket="仅剩5张")
    p1 = _rep.render_flights_table([("direct", [bare])], "t",
                                   str(tmp_path / "a.png"))
    p2 = _rep.render_flights_table([("direct", [full])], "t",
                                   str(tmp_path / "b.png"))
    h1 = Image.open(p1).size[1]
    h2 = Image.open(p2).size[1]
    # 拆两行=+16；若整行省略回退则高度不变（回归信号）
    assert h2 - h1 == 16, (h1, h2)


def test_flights_table_summary_list_budget(tmp_path):
    """summary 传列表：调用端 [:4] 静态截断曾把第 5+ 条 KPI 丢出图外
    （两航线×两日期=8 bits）。预算函数按 base14 字尺度量逐条取——
    8 bits 在 880 预算下至少进 4 条（不缩水 [:4] 语义）、预算放大到
    4000 时 8 条全进；渲染端到端不抛。"""
    import os as _os
    if not _os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("字尺度量与渲染依赖 Windows 中文字体（CI 无雅黑）")
    from PIL import Image, ImageDraw, ImageFont

    class _Shim:
        def __init__(self):
            im = Image.new("RGB", (8, 8))
            self._d = ImageDraw.Draw(im)

        def font(self, size):
            return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)

        def textlength(self, t, font=None):
            return self._d.textlength(t, font=font)

    import report as _rep
    bits = [f"上→乌 09/2{i} 直飞 ￥{1500 + i} 擦边9%" for i in range(8)]
    shim = _Shim()
    measure = lambda t: shim.textlength(t, font=shim.font(14))  # noqa: E731
    picked = _rep._summary_join(measure, bits, 880)
    n = picked.count(" ｜ ") + 1
    assert n >= 2, (n, picked)          # 单行装不下 8 条，多行式必须生效
    all_in = _rep._summary_join(measure, bits, 100000)
    assert all_in.count(" ｜ ") == 7    # 预算充足时 8 条全进
    assert _rep._summary_join(measure, [], 880) == ""
    row = {"price": 1000, "name": "CZ6981", "depTime": "08:00",
           "arrTime": "10:00", "_platform": "qunar", "transCity": ""}
    p = _rep.render_flights_table([("direct", [row])], "t",
                                  str(tmp_path / "s.png"), summary=bits)
    assert os.path.exists(p)


# ----：钉钉 -1 未达标心跳退避（落地）----
def test_heartbeat_backoff_mixin_semantics():
    """闸门语义：连败 <6 恒放行；≥6 起跳过且跳过轮计入连败（保连败
    弹窗 ≥8 升级不断档）；每 4 个心跳轮放行 1 次探测；恢复后恒放行。"""
    from core.notifier import DingTalkNotifier
    n = DingTalkNotifier.__new__(DingTalkNotifier)   # 不触网，仅测闸门
    n._fail_streak = 0
    assert n.heartbeat_allow() is True
    n._fail_streak = 5
    assert n.heartbeat_allow() is True               # 阈值下不退避
    n._fail_streak = 6
    assert n.heartbeat_allow() is False              # 首个跳过轮
    assert n._fail_streak == 7                       # 跳过轮计连败
    n._fail_streak = 6
    n._hb_skip = 0
    results = [n.heartbeat_allow() for _ in range(4)]
    assert results == [False, False, False, True], results   # 第 4 轮探测
    n._fail_streak = 0
    assert all(n.heartbeat_allow() for _ in range(10))       # 恢复恒放行


def test_digest_multi_heartbeat_gate_defers():
    """纯心跳轮（无 hits、上轮未达标）连败期被闸门跳过：send 不被调
    用——每 15 分钟重推同语义心跳正是钉钉 -1 限流的放大器。"""
    import logging as _lg

    class FakeN:
        def __init__(self):
            self._fail_streak = 8
            self.calls = []

        def heartbeat_allow(self):
            return False

        def send(self, t, d="", **kw):
            self.calls.append((t, d))
            return True

    a = Alerter(_lg.getLogger("t"), notifier=FakeN(), storage=None,
                digest=True, user="t")
    r = _mk_route(ad=1900)
    s = _mk_sections(2000)[0]          # 2000 > 1900 → 无 hits 纯心跳轮
    a._prev_hit = False
    assert a._push_digest_multi([(r, [s])]) is False
    assert a.notifier.calls == [], "退避期心跳不应发送"


def test_digest_multi_fell_round_bypasses_gate(monkeypatch, tmp_path):
    """回落出线轮（上轮达标、本轮无 hits）结构性不入闸——必达不可吞：
    heartbeat_allow 恒 False 仍必须 send。"""
    import logging as _lg
    import report as _rep

    monkeypatch.setattr(_rep, "render_flights_table",
                        lambda *a, **k: str(tmp_path / "x.png"))
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")

    class FakeN:
        def __init__(self):
            self._fail_streak = 9
            self.calls = []

        def heartbeat_allow(self):
            return False

        def send(self, t, d="", **kw):
            self.calls.append((t, d))
            return True

    a = Alerter(_lg.getLogger("t"), notifier=FakeN(), storage=None,
                digest=True, user="t")
    r = _mk_route(ad=1900)
    s = _mk_sections(2000)[0]          # 无 hits，但上轮达标=回落轮
    a._prev_hit = True
    a._push_digest_multi([(r, [s])])
    assert a.notifier.calls, "回落轮必达，不得被退避闸吞掉"


# ----：渠道决策字段扩采（trendGo/labels/童婴价）----
def test_qunar_trend_go_parse():
    from crawlers.qunar import QunarCrawler
    trend = {"goFTrend": [
        {"price": "650", "date": "2026-09-18", "index": 0},
        {"price": "680", "date": "2026-09-19", "index": 1},
        {"price": "abc", "date": "2026-09-20", "index": 2},   # 脏价弃
        {"price": "700", "date": "2026/09/21", "index": 3},   # 坏日期弃
        {"price": "0", "date": "2026-09-22", "index": 4},     # 越域弃
        "junk"]}                                              # 截断接缝弃
    assert QunarCrawler._parse_trend_go(trend) == [["09-18", 650],
                                                   ["09-19", 680]]
    assert QunarCrawler._parse_trend_go(None) is None
    assert QunarCrawler._parse_trend_go({"goFTrend": []}) is None
    assert QunarCrawler._parse_trend_go({"goFTrend": "x"}) is None


def test_qunar_trend_go_attached_to_lowest_row():
    """route 级买票时机曲线只挂当轮最低价行：逐行重复 ≈ 每轮
    +300B×75 行 extra 膨胀。"""
    from crawlers.qunar import QunarCrawler

    def _f(p, code):
        return {"minPrice": p, "code": code,
                "binfo": {"depTime": "08:00", "arrTime": "10:00",
                          "depDate": "2026-09-25", "arrDate": "2026-09-25"}}

    resp = json.dumps({"data": {"flights": [_f(900, "MU8369"),
                                            _f(650, "CZ6981")],
                                "trendPrice": {"goFTrend": [
                                    {"price": "650",
                                     "date": "2026-09-25"}]}}})
    rows = QunarCrawler._parse_response_flights(resp)
    assert len(rows) == 2
    lo = [r for r in rows if "trendGo" in r]
    assert len(lo) == 1 and lo[0]["code"] == "CZ6981", rows
    assert lo[0]["trendGo"] == [["09-25", 650]]


def test_qunar_pc_labels():
    from crawlers.qunar import QunarCrawler
    f = {"priceLabel": [
        {"id": 667, "name": "取消延误免费改", "note": []},
        {"id": 8007, "name": "宠物友好", "note": []},
        {"id": 2048, "name": "免费上网", "note": []},
        {"id": 236, "name": "体验价", "note": []}]}
    # 上限 3：防营销词串撑爆展示位；id 不稳定（667 双义）不参与判定
    assert QunarCrawler._labels_of(f) == "取消延误免费改·宠物友好·免费上网"
    assert QunarCrawler._labels_of({}) == ""
    assert QunarCrawler._labels_of({"priceLabel": "x"}) == ""


def test_tuniu_child_infant_fares():
    from crawlers.tuniu import TuniuCrawler
    pl = [{"fareBreakdownList": [
        {"psgType": "ADT", "baseFare": "2370"},
        {"psgType": "CHD", "baseFare": "2370"},
        {"psgType": "CHD", "baseFare": "2200"},   # 取最低
        {"psgType": "INF", "baseFare": "470"}]},
        {"fareBreakdownList": [{"psgType": "CHD", "baseFare": "99999"}]}]
    child, infant = TuniuCrawler._child_infant_fares(pl)
    assert child == 2200 and infant == 470
    # 婴儿价常低于成人票价纪律下限 300：专用宽域换算不得误杀
    lo = TuniuCrawler._child_infant_fares(
        [{"fareBreakdownList": [{"psgType": "INF", "baseFare": "120"}]}])
    assert lo == (None, 120), lo
    assert TuniuCrawler._child_infant_fares([]) == (None, None)
