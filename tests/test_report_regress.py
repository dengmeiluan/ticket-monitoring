# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v1549_regress.py
- tests/test_v1551_regress.py
- tests/test_v1553_regress.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime as _dt
import json
import logging
import os
import pytest
import sys

from core.alerter import Alerter, URGENT_FAIL_NOTE, _dw, _qual_price, gap_txt, kpi_tier_txt
from core.models import Route
from font_probe import cjk_font_path, has_cjk_font


# ---- merged from tests/test_v1549_regress.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
def _sent(monkeypatch, tmp_path, prices, keep_supplied=False):
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    if not keep_supplied:
        _m._SENT_SUPPLIED.clear()
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
    才判——共享覆盖率随航线波动（DB 实测 20-40%），比率阈值会误报。
    供给基线语义（r316）：健康轮写供给（share 25% 在场零告警），
    断链轮归零真警——「曾供给后断链」检测力不丢。"""
    alive = [{"price": 1000, "cabin": "经济舱",
              "shareCarrier": "MU5700" if i % 4 == 0 else ""}
             for i in range(30)]
    seen1, _I, _m = _sent(monkeypatch, tmp_path, [("ctrip", alive)])
    assert not any("shareCarrier" in str(a) for a in seen1), seen1
    dead = [{"price": 1000, "cabin": "经济舱", "shareCarrier": ""}
            for _ in range(30)]
    seen, _I, _m = _sent(monkeypatch, tmp_path, [("ctrip", dead)],
                         keep_supplied=True)
    assert any("shareCarrier" in str(a) for a in seen), seen


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
    if not has_cjk_font():
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
    if not has_cjk_font():
        pytest.skip("字尺度量与渲染依赖 Windows 中文字体（CI 无雅黑）")
    from PIL import Image, ImageDraw, ImageFont

    class _Shim:
        def __init__(self):
            im = Image.new("RGB", (8, 8))
            self._d = ImageDraw.Draw(im)

        def font(self, size):
            return ImageFont.truetype(cjk_font_path(), size)

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


# ---- merged from tests/test_v1551_regress.py ----

# ==================== 渠道字段三批 ====================

class TestTongchengTransferFields:
    """同程 connection 报文 增采四字段（10-05 dump：stss 19/
    fps、$tcTip 37 处、dat/aat 26/26、doc.check 恒定「转机免安检」）。"""

    def _rows(self, fps, doc=None):
        from crawlers.tongcheng import TongchengCrawler
        obj = {"success": True, "data": {"fps": fps,
                                         "doc": doc or {}}}
        return TongchengCrawler._extract_transfer_flights(
            json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _fp(**over):
        fp = {
            "dt": "2026-10-05 15:15", "at": "2026-10-06 07:55",
            "td": "16h40m", "sd": "11h0m", "sc": "石家庄",
            "dat": "", "aat": "T2",
            "ss": [{"fn": "9C7006", "dt": "2026-10-05 15:15",
                    "at": "2026-10-05 19:05", "asn": "春秋",
                    "amn": "空客A320"},
                   {"fn": "9C7310", "dt": "2026-10-06 06:05",
                    "at": "2026-10-06 07:55", "asn": "春秋",
                    "amn": "空客A320"}],
            "lps": [{"atp": 2320, "brs": [{"al": 5}],
                     "pts": [{"td": "5.6折经济舱"}],
                     "$tcTip": {"c1": "中转专享",
                                "c2": "航司中转，享联程服务"}}],
            "stss": [
                {"ServiceType": "TRANSFER_LOUNGE",
                 "ServiceName": "免费休息室"},
                {"ServiceType": "TRANSFER_MEAL",
                 "ServiceName": "免费餐食"},
                {"ServiceType": "TRANSFER_MEAL",
                 "ServiceName": "免费餐饮"},
                {"ServiceType": "TRANSFER_MEAL",
                 "ServiceName": "免费餐食"}],   # 重复项去重
        }
        fp.update(over)
        return fp

    def test_transfer_service_dedup_and_check(self):
        rows = self._rows([self._fp()],
                          doc={"check": "转机免安检"})
        assert rows, "行被丢弃"
        r = rows[0]
        # 去重保序：免费餐食只出现一次
        assert r["transferService"] == ("免费休息室/免费餐食/免费餐饮"
                                        "/转机免安检")

    def test_airline_transfer_follows_lowest_policy(self):
        # 两政策：低价政策带 $tcTip——标注须随最低价配对（与 cabin 同律）
        fps = [self._fp(lps=[
            {"atp": 2500, "brs": [{"al": 5}],
             "pts": [{"td": "经济舱"}],
             "$tcTip": {"c2": "自行中转"}},
            {"atp": 2320, "brs": [{"al": 5}],
             "pts": [{"td": "经济舱"}],
             "$tcTip": {"c2": "航司中转，享联程服务"}}])]
        r = self._rows(fps)[0]
        assert r["airlineTransfer"] == "航司中转，享联程服务"
        assert r["price"] == 2320

    def test_terminals_from_fp_layer(self):
        r = self._rows([self._fp()])[0]
        assert "depTerminal" not in r    # 出发侧无值不落键（恒空键卫生律）
        assert r["arrTerminal"] == "T2"

    def test_no_stss_leaves_empty_but_check_only(self):
        # 10-06 形态：stss 覆盖 1/23——无服务行如实留空，仅 doc.check 并入
        fp = self._fp()
        fp.pop("stss")
        r = self._rows([fp], doc={"check": "转机免安检"})[0]
        assert r["transferService"] == "转机免安检"


class TestTongchengDirectTerminal:
    """直飞 fl 元素 dat/aat（47/47 在场）：同程曾是五渠道唯一零航站楼。"""

    def test_direct_terminal(self):
        from crawlers.tongcheng import TongchengCrawler
        obj = {"data": {"fl": [{
            "fn": "GS7587", "asn": "天津", "dac": "URC", "aac": "PVG",
            "dt": "2026-10-05 07:10", "at": "2026-10-05 13:45",
            "td": "6h35m", "dat": "", "aat": "T2",
            "lps": [{"atp": 1180, "brs": [{"al": 5}]}]}]}}
        rows = TongchengCrawler._extract_flights(
            json.dumps(obj, ensure_ascii=False))
        assert "depTerminal" not in rows[0]   # dat 空串不落（恒空键卫生律）
        assert rows[0]["arrTerminal"] == "T2"


class TestFliggyTerminalLines:
    """飞猪机场行分支（10-05 HTML 实证：出发侧「乌鲁木齐天山国际机场」
    无 T 码 35 处、到达侧「虹桥国际机场T2」带码为主）。"""

    def _parse(self, lines):
        from crawlers.fliggy import FliggyCrawler
        return FliggyCrawler._parse_pc_text("\n".join(lines), "2026-10-05")

    def test_dep_no_code_arr_with_code(self):
        rows = self._parse([
            "春秋9C8866", "中型机 321", "15:15", "19:05",
            "乌鲁木齐天山国际机场", "虹桥国际机场T2", "96%", "¥1180"])
        assert rows and "depTerminal" not in rows[0]   # 无 T 码不落键
        assert rows[0]["arrTerminal"] == "T2"

    def test_both_with_code(self):
        rows = self._parse([
            "东航MU8369", "中型机 737", "08:00", "12:30",
            "虹桥国际机场T1", "浦东国际机场T2", "¥2320"])
        assert rows[0]["depTerminal"] == "T1"
        assert rows[0]["arrTerminal"] == "T2"

    def test_terminal_not_stolen_after_price(self):
        # 页面尾部异源模块含「机场」文本：价格已定时机场行守卫不再吸收
        rows = self._parse([
            "春秋9C8866", "中型机 321", "15:15", "19:05",
            "乌鲁木齐天山国际机场", "虹桥国际机场T2", "¥1180",
            "酒店距机场3公里"])
        assert rows[0]["arrTerminal"] == "T2"
        assert rows[0]["price"] == 1180


class TestCtripExtendinfos:
    """ctrip extendinfos 补采（content 全集 40 档实证）：平均延误 int
    分钟与 tuniu 同协议（webui 明细次行消费端已在）、连廊率、Wi-Fi 与
    航变免费退改并入 labels 走既有渲染（防孤儿键）。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        obj = {"fltitem": [item]}
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _item(extend, fnotelst=None):
        seg = {"basinfo": {"flgno": "MU5137"},
               "dateinfo": {"ddate": "2026-10-05 08:00:00",
                            "adate": "2026-10-05 11:30:00"},
               "aportinfo": {"city": "上海"}}
        ci = {"cgrd": 0, "prate": 96, "meal": "有餐食",
              "extendinfos": extend}
        it = {"mutilstn": [seg],
              "policyinfo": [{"tprice": 1200, "quantity": 1,
                              "classinfor": [ci]}]}
        if fnotelst is not None:
            it["policyinfo"][0]["fnotelst"] = fnotelst
        return it

    def test_avgdelay_bridge_wifi(self):
        rows = self._parse(self._item([
            {"content": "平均延误21分钟"},
            {"content": "连廊率100%"},
            {"content": "机上Wi-Fi"},
            {"content": "机龄8年5个月"}]))
        r = rows[0]
        assert r["avgDelay"] == 21
        assert r["bridgeRate"] == 100
        assert "机上Wi-Fi" in r["labels"]
        # 机龄精度协议：「8年5个月」→ 8+5/12 折算小数年（曾截断
        # 丢月成分，与 tuniu flightYear 小数协议对齐）
        assert r["planeAge"] == "8.4"

    def test_refund_free_into_labels(self):
        rows = self._parse(self._item(
            [{"content": "平均延误18分钟"}],
            fnotelst=[{"notecnt": "航变免费退改|行李直达"}]))
        r = rows[0]
        assert "航变免费退改" in r["labels"]
        # 随最低价政策配对：另一政策带词但价高时不取
        rows2 = self._parse({
            "mutilstn": [{"basinfo": {"flgno": "MU5137"},
                          "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                       "adate": "2026-10-05 11:30:00"},
                          "aportinfo": {"city": "上海"}}],
            "policyinfo": [
                {"tprice": 900, "quantity": 1,
                 "classinfor": [{"cgrd": 0, "prate": 96, "meal": "",
                                 "extendinfos": []}]},
                {"tprice": 1200, "quantity": 1,
                 "classinfor": [{"cgrd": 0, "prate": 96, "meal": "",
                                 "extendinfos": []}],
                 "fnotelst": [{"notecnt": "航变免费退改"}]}]})
        assert "航变免费退改" not in (rows2[0].get("labels") or "")


# ==================== 推送语义档收口 ====================

class TestGaugeOverlineRemoved:
    """撤超线仪表条：🟦 进度格=行1 百分比二次编码且「有图无例」
    （生产 200 条 185 条成串蓝块）；超线默认态不占语义点（定律）。"""

    def test_overline_returns_empty(self):
        from core.alerter import Alerter
        g = Alerter._gauge
        assert g(1500, 1600) == "🟩" * 5       # 破线行保留档位强化
        assert g(2319, 1600) == ""             # 超线撤
        assert g(None, 1600) == ""

    def test_multi_kpi_no_blue_blocks(self, monkeypatch, tmp_path):
        # digest 文本不再出现 🟦 成串块（与 test_core_units「超线不加点」
        # 语义测试同向的仪表条侧收口）
        from core.alerter import Alerter
        a = Alerter.__new__(Alerter)
        a.logger = None
        a._prev_hit = False
        g = Alerter._gauge
        assert g(1850, 1600) == "" and g(5000, 1600) == ""


class TestNoteAndTitleWording:
    """小注化石与词面收口：四档色时代「价格标绿=真达标」会让人把描边
    绿（行情破线）读成真达标；建议行「达标」正名「真达标」。"""

    def test_table_note_distinguishes_green_shades(self):
        from core import alerter
        src = open(alerter.__file__, encoding="utf-8").read()
        assert "价格标绿=真达标" not in src
        # 推送审校 P1：标题行 47 半角超 40 铁律（每推必现）+
        # 「描绿=行情价」与图内图例「行情破线」同屏两词面——改「破线」
        # 并去括号壳，两处（总表/TOP5）同律 38/40。
        # 档位词面收编 _TIER_TABLE：字面收敛为 _TBL_HEAD_TIER
        # 派生常量（×2 手抄归一），钉投影等价+两处引用计数
        assert "实绿=真达标·描绿=行情价" not in src
        assert "实绿=" not in src
        assert alerter._TBL_HEAD_TIER == "深绿=真达标·描绿=破线"
        assert src.count("_TBL_HEAD_TIER}") == 2

    def test_suggest_line_uses_qual_word(self):
        from core.alerter import Alerter, gap_txt, TIER_FULL
        # gap_txt 单源：真达标口径产出「低￥N」
        assert gap_txt(1800, 1900, True) == "低￥100"
        assert TIER_FULL["qual"] == "真达标"
        src = open(Alerter.__module__.replace(".", "/") + ".py",
                   encoding="utf-8").read()
        # 词面投影收编：钉 f-string 投影式（词面零变化由
        # TIER_FULL 断言+test_core_units 输出级钉双护栏）
        assert "{label} {TIER_FULL['qual']} " in src
        assert "{gap_txt(price, th, True)}，建议出手" in src

    def test_png_titles_mmdd(self):
        import report
        from core import alerter
        src = open(report.__file__, encoding="utf-8").read()
        # 走势标题与日报表标题（report.py）、单航线表标题（alerter.py）MM/DD
        assert src.count("{date[5:].replace('-', '/')}") >= 2
        asrc = open(alerter.__file__, encoding="utf-8").read()
        assert "{sections[0]['date'][5:].replace('-', '/')}" in asrc


# ---- merged from tests/test_v1553_regress.py ----

# 回归：差额词单源终局（_low_txt 并入 gap_txt）+ 强提醒转写
# 剥注防叠词（调研② 挂起项收口）+ 🔥 入转写表 + mini KPI 档位
# 点与主 KPI 贴法对齐。词面/单源纪律的测试侧钉死。

class TestLowTxtSingleSource:
    """_low_txt 词面并入 gap_txt（调研②）：独立拼「低￥N」是
    第二词源（gap_txt docstring「改词必漏」同病）；恰达线 diff==0
    曾读「低￥0」自相矛盾。"""

    def test_word_face_equals_gap_txt(self):
        from core.alerter import _low_txt, gap_txt
        assert _low_txt(1850, 2000, "qunar") == "低￥150"
        assert _low_txt(1850, 2000, "qunar") == gap_txt(1850, 2000, True)

    def test_exact_threshold_reads_qual_word(self):
        from core.alerter import _low_txt
        out = _low_txt(2000, 2000, "qunar")
        assert out == "真达标"
        assert "低￥0" not in out

    def test_fliggy_tax_note_strict_below_only(self):
        """税前注挂严格破线飞猪行；恰达线（真达标）不挂——
        「真达标(税前)」语义不通。"""
        from core import alerter as _a
        from core.alerter import _low_txt
        old = _a.FLIGGY_TAX_PAD
        try:
            _a.FLIGGY_TAX_PAD = 100
            assert _low_txt(1850, 2100, "fliggy") == "低￥250（税前）"
            assert _low_txt(2100, 2100, "fliggy") == "真达标"
        finally:
            _a.FLIGGY_TAX_PAD = old


class TestTranscribeDedup:
    """转写前剥注（调研②）：🟩 转写词「行情价 」与 KPI 行1
    尾注「（行情价）/·行情」、行3 兜底注「行情价」同条重复——
    生产 0/200 共现的挂起项提前收口，共现一现即叠词。"""

    def test_alert_body_strips_market_note(self):
        from core.notifier import _alert_body
        body = _alert_body("🟩 直飞 ￥2500　线￥2600　低￥100（行情价）\n\n"
                           "> 经西安 停2h 行李直挂 行情价")
        assert body.count("行情价") == 1          # 仅剩转写前缀
        assert "（行情价）" not in body

    def test_alert_body_strips_star_note(self):
        from core.notifier import _alert_body
        import core.alerter as _al
        # r302 换词：短注分隔符 * → ·（非强调字符），输入随单源构造
        body = _alert_body("🟩 直飞 ￥2500　线￥2600　低￥100"
                           + _al._MKT_NOTE)
        assert body.count("行情价") == 1
        assert _al._MKT_NOTE not in body
        assert "*" not in body

    def test_wintoast_plain_strips_market_note(self):
        from core.notifier import WindowsToastNotifier
        body = WindowsToastNotifier._plain(
            "🟩 直飞 ￥2500　线￥2600　低￥100（行情价）", 180)
        assert body.count("行情价") == 1
        assert "（行情价）" not in body


class TestFireHitTranscribed:
    """🔥 入转写表（调研② P2）：hits 行首 🔥 在 ntfy/WinToast 曾保留
    原样，TTS 读「火」或跳读；转「命中 」可播报。"""

    def test_table_entry(self):
        from core.notifier import _EMOJI_TIER_WORDS
        assert ("🔥", "命中 ") in _EMOJI_TIER_WORDS

    def test_alert_body_transcribes(self):
        from core.notifier import _alert_body
        body = _alert_body("🔥 直飞 ￥2500　线￥2600　低￥100(税前)")
        assert "命中" in body
        assert "🔥" not in body

    def test_ntfy_count_captured_pre_transcribe(self):
        """截断留痕「共N条命中」计数须取转写前原文：🔥 进转写表后
        转写后文本已无 🔥，事后计数恒 0 静默消失。计数口径=
        hits 区引用行（> 🔥 行首前缀行数；r290 P3-1——全文 🔥 计数
        混入 TOP5 重复展示位，旧形态禁复活），行为钉
        test_push_align::test_ntfy_trunc_note_counts_hits_only 同轮在案。"""
        import core.notifier as _n
        src = open(_n.__file__, encoding="utf-8").read()
        assert 'for ln in (desp or "").split("\\n")' in src
        assert 'ln.lstrip().startswith("> 🔥"))' in src
        assert "_n = _nfire" in src
        assert '_full.count("🔥")' not in src
        assert '(desp or "").count("🔥")' not in src
        # 跨模块口径耦合钉（Soldier P3-2）：消费端「> 🔥」前缀依赖
        # 生产端 hits head 构造（alerter multi/legacy 两处）——前缀
        # 改版则计数静默归 0、尾注优雅退化，本钉让耦合显形
        import core.alerter as _a
        asrc = open(_a.__file__, encoding="utf-8").read()
        assert asrc.count("> 🔥 ") >= 2, (
            "生产端 hits head「> 🔥 」前缀在场数不足——ntfy 尾注计数口径随之失效")


class TestMiniKpiDotSpacing:
    """mini KPI 档位点贴法：r227 P3-5 收口后五处手抄散点统一
    tier_dot 单源（返回值带尾空格由单源保证），手抄形态清零防回潮。"""

    def test_all_dots_spaced(self):
        import core.alerter as _a
        src = open(_a.__file__, encoding="utf-8").read()
        assert 'tier_dot(qual_hit, diff, th)' in src
        assert '_dot = tier_dot(_qd, _diff_d, route.alert_direct)' in src
        # 无空格旧形态清零（防新代码再引入）
        assert 'dot = "🎯"' not in src
        assert 'dot = "🟩"' not in src
        assert 'dot = "🟨"' not in src


class TestQunarH5Labels:
    """H5 决策标签（调研④）：priceBottomLabels 按 text 显式
    白名单采（id 被营销词共用勿按 id）；transNotice 占位「转」不采。"""

    def test_whitelist_rejects_marketing_words(self):
        from crawlers.qunar import QunarCrawler
        f = {"listLabel": {"priceBottomLabels": [
                {"id": "reduceShowLabel", "text": "中转低价"},
                {"id": "x", "text": "出票后2小时内错购退票"}]},
             "transNotice": "转"}
        out = QunarCrawler._h5_labels_of(f)
        assert out == "出票后2小时内错购退票"
        assert "中转低价" not in out

    def test_trans_notice_non_default_only(self):
        from crawlers.qunar import QunarCrawler
        assert QunarCrawler._h5_labels_of(
            {"transNotice": "华夏联程"}) == "华夏联程"
        assert QunarCrawler._h5_labels_of({"transNotice": "转"}) == ""
        assert QunarCrawler._h5_labels_of({}) == ""


class TestCrawlerFieldPins:
    """调研④ 落地钉死：ctrip transTerminal 值级兜底、tuniu 宽体机
    标签、dump 截断上限提升。"""

    @staticmethod
    def _src(path):
        return open(path, encoding="utf-8").read()

    def test_ctrip_trans_term_value_level_fallback(self):
        src = self._src("crawlers/ctrip.py")
        assert 'trans_term = (str((segs[1].get("dportinfo") or {})' in src

    def test_tuniu_widebody_label(self):
        src = self._src("crawlers/tuniu.py")
        # r241 残留族收口后写点条件展开（无值不落键），钉面随写点形态改写
        assert 'if (_lb := ("宽体机"' in src

    def test_dump_cap_raised(self):
        for p in ("crawlers/ctrip.py", "crawlers/tongcheng.py"):
            src = self._src(p)
            assert "[:1000000]" not in src and "[:4000000]" in src


class TestPriceBandSingleSource:
    """价格带单源（调研③ P1-A）：曲线侧曾独用 300 下界而列表
    无下界——100–299 真实低价「列表可见、图上不可见」是曲线-列表含义
    一致的破口。五处取数链统一 core.models PRICE_MIN/PRICE_MAX。"""

    def test_constants(self):
        from core.models import PRICE_MAX, PRICE_MIN
        assert (PRICE_MIN, PRICE_MAX) == (100, 50000)

    def test_no_scattered_bands(self):
        import core.alerter as _a
        import report as _r
        for src in (open(_a.__file__, encoding="utf-8").read(),
                    open(_r.__file__, encoding="utf-8").read()):
            assert "300 <= p <= 50000" not in src
            assert "0 < lo <= 50000" not in src
            assert '0 < f["price"] <= 50000' not in src
            assert '0 < _v2 <= 50000' not in src

    def test_rounds_accepts_low_band_price(self):
        """曲线侧下界 300→100 后，150 元真实低价行不再被曲线剔除。"""
        import json as _json
        import os as _os
        import sqlite3 as _sq
        import tempfile as _tf
        from report import _rounds
        with _tf.TemporaryDirectory() as td:
            dbp = _os.path.join(td, "t.db")
            db = _sq.connect(dbp)
            db.execute("CREATE TABLE flight_prices (platform TEXT, extra "
                       "TEXT, fetched_at TEXT, from_city TEXT, to_city "
                       "TEXT, depart_date TEXT, price REAL)")
            extra = _json.dumps([
                {"price": 150, "depTime": "10:00", "arrTime": "13:00",
                 "depDate": "2026-10-01"},
                {"price": 900, "depTime": "12:00", "arrTime": "15:00",
                 "depDate": "2026-10-01"}])
            # fetched_at 动态化——原硬编码 2026-09-20 10:00 在
            # 48h 回看窗语义下随真实时钟漂移出窗（09-22 10:00 后恒红），
            # 测试本意（150 元低价行不被曲线剔除）与绝对时刻无关
            _ts = (_dt.datetime.now() - _dt.timedelta(hours=1)
                   ).strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO flight_prices VALUES ('qunar',?,"
                       "?,'A','B','2026-10-01',150)", (extra, _ts))
            db.commit()
            hist = _rounds(dbp, "A", "B", "2026-10-01", "02:00", hours=48)
            db.close()
        assert hist and hist[0][1] == 150


class TestRoundSeriesAnchorOrder:
    """_rounds 幻影锚池判定与列表链同序（调研③ P1-B）：锚池
    判定必须先于到达/衔接过滤（曲线侧曾对过滤后残池判幻影）。"""

    def test_source_pin(self):
        import report as _r
        src = open(_r.__file__, encoding="utf-8").read()
        # 到达过滤不再在桶收集期发生
        assert "if Alerter._arrival_ok(f, arrival_max):\n                    b[2].append" not in src
        # 幻影判定先于 ok_t 过滤（钉面随桶结构改写：元素带行身份
        # _rid 供行级幻影守卫整行剔除，判定先序语义不变）
        assert src.index("_no_x = [x for i, x in enumerate(tsf)") < \
            src.index("ok_t = [(f, p, pl) for f, p, pl, _rid in _no_x")


class TestSentinelTuniuPrateKept:
    """tuniu|prate 守卫后不入死键表（生产实证 09-19/20 真实覆盖
    80%+、占位 20 清零）——哨兵死键表不得收入 tuniu prate，
    观测口径跟着守卫改的前提不成立。"""

    def test_tuniu_prate_not_in_dead_keys(self):
        import main as _m
        src = open(_m.__file__, encoding="utf-8").read()
        dead = _m._field_sentinel.__code__.co_consts
        assert not any(
            isinstance(c, (set, frozenset)) and ("tuniu", "prate") in c
            for c in dead)
        assert src.count('("tuniu", "prate")') == 0


class TestOpsNotesIntoImage:
    """运维对账注入图（，用户截图反馈）：直挂标注缺失/无数据
    渠道/孤低价拦截/全渠道无数据四类对账行自钉钉文本段撤入总表 PNG
    小注——「跳转文案才用文本，其余只出图」定律补口；
    图挂兜底分支才回退文本（信息不能跟图一起消失）。"""

    @staticmethod
    def _fixture():
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route as _R
        a = Alerter(_lg.getLogger("t"), notifier=None, digest=True)
        r = _R(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-09-25"],
               alert_direct=1900, alert_transfer=1700)
        s = {"date": "2026-09-25", "seen_plats": [],          # 全渠道缺
             "best_direct": None, "best_transfer": None,
             "xphans": [("qunar", 313), ("ctrip", 350)]}      # 拦截留痕
        return a, r, [s]

    def test_ops_notes_pass_to_render_and_desp_clean(self):
        import report as _rep
        a, r, sections = self._fixture()
        cap = {}
        orig = (_rep.render_flights_table, _rep.upload_chart)
        _rep.render_flights_table = (
            lambda rows_, title, out, top_n=5, summary="", stamp_note="",
            ops_notes="": cap.update(ops=list(ops_notes or [])) or out)
        _rep.upload_chart = (lambda p, cfg=None, lg=None, ih=None:
                                "https://iili.io/fake.png")
        try:
            pv = a._digest_payload([(r, sections)], fresh=True,
                                   with_tables=True)
        finally:
            _rep.render_flights_table, _rep.upload_chart = orig
        ops = " ｜ ".join(cap.get("ops") or [])
        assert "无数据" in ops and "孤低价拦截×2" in ops
        assert "￥313" in ops                       # 拦截价随行入图
        desp = pv["desp"]
        assert "孤低价拦截" not in desp              # 文本段已撤
        assert "无数据：" not in desp

    def test_transfer_baggage_note_in_image(self):
        import report as _rep
        a, r, sections = self._fixture()
        r.transfer_baggage = "direct"
        sections[0]["top_transfer"] = [{"price": 1650, "transCity": "郑州",
                                        "transferBaggage": ""}]
        cap = {}
        orig = (_rep.render_flights_table, _rep.upload_chart)
        _rep.render_flights_table = (
            lambda rows_, title, out, top_n=5, summary="", stamp_note="",
            ops_notes="": cap.update(ops=list(ops_notes or [])) or out)
        _rep.upload_chart = (lambda p, cfg=None, lg=None, ih=None:
                                "https://iili.io/fake.png")
        try:
            a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        finally:
            _rep.render_flights_table, _rep.upload_chart = orig
        assert any("直挂标注缺失" in _n for _n in cap.get("ops") or [])

    def test_fallback_text_keeps_notes_when_image_fails(self):
        import report as _rep
        a, r, sections = self._fixture()
        orig = (_rep.render_flights_table, _rep.upload_chart)
        _rep.render_flights_table = (
            lambda rows_, title, out, top_n=5, summary="", stamp_note="",
            ops_notes="": out)
        _rep.upload_chart = (lambda p, cfg=None, lg=None, ih=None: ""     # 图挂
                             )
        try:
            pv = a._digest_payload([(r, sections)], fresh=True,
                                   with_tables=True)
        finally:
            _rep.render_flights_table, _rep.upload_chart = orig
        desp = pv["desp"]
        assert "⚠️" in desp and "无数据" in desp      # 兜底回退文本

    def test_render_draws_ops_box(self):
        """渲染端烟测：ops_notes 有注时画布增高（盒体+间距）。"""
        import tempfile as _tf
        import report as _rep
        rows = [("direct", [{"price": 1500, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"}], "✈️ 直飞最优 · SHA 25")]
        with _tf.TemporaryDirectory() as td:
            p0, p1 = (os.path.join(td, n) for n in ("a.png", "b.png"))
            _rep.render_flights_table(rows, "测试", p0, summary=[],
                                      ops_notes=[])
            _rep.render_flights_table(rows, "测试", p1, summary=[],
                                      ops_notes=["SHA 09/25 无数据：去哪儿"])
            from PIL import Image as _I
            h0 = _I.open(p0).height
            h1 = _I.open(p1).height
            assert h1 > h0
