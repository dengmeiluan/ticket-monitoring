# -*- coding: utf-8 -*-
"""r253 推送层四案（调研报告 r253_audit_push.md）：

P1-1 中转行「经哪」双口径错配——_via_txt stopCity 无条件优先，中转行
同带 stopCitys（第一段经停）+transCity（中转城市）时，hits 行/_fmt_
flight_line/同班比价行把 layoverT（中转停留 22:55）拼到经停城市后
（「经停庆阳 停22:55」），与 KPI 行3（transCity 优先，「经兰州 停2:05」）
及总表 PNG（徽标经停·停0:45 + 中转列兰州·停22:55）同屏互相矛盾。
修法：_via_txt 中转行优先 transCity，经停行（无 transCity）保持
「经停X」词面——单点收口，全部消费点自动对齐。

P2-1 行情破线独占轮标题锚点丢失——未达标锚只认 gap>0（超线），价已
破线（低于阈值）但未达标（直挂约束）的轮标题塌缩为「❌ 全部未达标｜
清单」，「低￥N」只在正文 KPI。修法：无超线锚时挂 |gap| 最大破线锚
（词面 gap_txt 单源出「低￥N」），超线锚优先维持既有行为零回归。

P3-1 hits head 降级链无双名剥档——「新海航｜金鹏航空 Y87519」超宽
整名被丢（身份净失，head 无航班号）。修法：fallbacks 增「剥营销名
A｜」档（_l2_fallbacks 双名剥档同律），去名档仍为末档地板。

P3-2 行3 地板逐字截可产半截 token——「停2:05」截成「停2:」（噪音）。
修法：地板装载按 token（全角空格段）贪心，整 token 装不下整删；
首 token 自身超预算时才逐字截（病理长城市名兜底不变）。"""
import datetime as dt
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402
from core.models import Route, FlightPrice  # noqa: E402


def _fp(price, name, dpt, art, trans="", cross="", plat="ctrip",
        dep="2026-10-04", **extra):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else 0
    f = {"price": price, "name": name, "code": name, "depTime": dpt,
         "arrTime": art, "depDate": dep,
         "arrDate": str(d0 + dt.timedelta(days=days)),
         "transCity": trans, "crossDayDesc": cross,
         "_platform": plat}
    f.update(extra)
    return f


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


class _FakeN:
    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        return True


def _mk():
    log = logging.getLogger("r253probe")
    logging.basicConfig(level=logging.CRITICAL)
    return Alerter(log, notifier=_FakeN(), storage=None, digest=True,
                   at_mobile="", storm_repeat=1, user="演练")


_TR_ROW = {"price": 1650, "name": "川航3U8863", "code": "3U8863",
           "depTime": "17:55", "arrTime": "18:50", "crossDayDesc": "+1天",
           "transCity": "兰州", "stopCity": "庆阳",
           # 生产实证形态（r253 审校 S8：ctrip 中转行同带双键常态）：
           # layoverT 是 normalize 从 layover(int 分钟) 重建的词面，
           # 真源键 layover + layoverSrc="times"（结构化真值，豁免
           # 假衔接判伪守卫）；全程时长必须 > 停留（衔接≥全程作废
           # 守卫）——17:55→次日18:50=24h55 > 22h55
           "layover": 1375, "layoverSrc": "times",
           "stopTimeT": "0:45", "transferBaggage": "direct",
           "_platform": "ctrip"}


class TestViaTxt:
    def test_transfer_row_prefers_trans_city(self):
        """P1-1 主钉：中转行双键同带 →「经兰州」（非「经停庆阳」）。"""
        assert Alerter._via_txt(
            {"transCity": "兰州", "stopCity": "庆阳"}) == "经兰州"

    def test_stopover_row_keeps_stop_word(self):
        """经停行（无 transCity）词面不回归。"""
        assert Alerter._via_txt({"stopCity": "庆阳"}) == "经停庆阳"

    def test_placeholder_and_empty(self):
        """「中转」占位与空行守卫不回归（勿产「经中转」病句）。"""
        assert Alerter._via_txt({"transCity": "中转"}) == ""
        assert Alerter._via_txt({}) == ""
        assert Alerter._via_txt({"transCity": "兰州"}) == "经兰州"


class TestFmtFlightLinePairing:
    # 注：_fmt_flight_line 的中转行词面由 _via_txt 单源保证（上方
    # 单元钉已覆盖）；其明细行长行常态超 40 半角、走 bare 地板档
    # （舍停保码既有档序在案），via/停时先于错配被剥——行级配对钉
    # 无鉴别力，不重复。
    def test_stopover_row_not_mispaired(self):
        """纯经停行（同机号）不被误配中转词（词面正确性在 _via_txt
        单元钉；本钉守消费点无「经兰州」错配）。"""
        line = Alerter._fmt_flight_line(
            {"price": 1500, "name": "南航CZ6981", "code": "CZ6981",
             "depTime": "09:00", "arrTime": "14:10",
             "stopCity": "庆阳", "stopTimeT": "0:45",
             "totalDuration": "6时", "_platform": "qunar"}, idx=2)
        assert "经兰州" not in line, line


class TestHitsLinePairing:
    def test_hits_transfer_row_pairs_correctly(self, monkeypatch):
        """达标 hits 行端到端：「经兰州 停22:55」且全 desp 无错配词。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_arrival_max="23:59")
        row = dict(_TR_ROW)
        row["price"] = 1600  # 达标（≤1700，直挂标注在场）
        p = _ps([row], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        desp = pv["desp"]
        assert "经兰州 停22:55" in desp, desp[:600]
        assert "经停庆阳 停" not in desp, desp[:600]


class TestTitleAnchorMktBreak:
    def test_market_break_solo_round_gets_anchor(self, monkeypatch):
        """P2-1：行情破线独占轮（直挂约束未达标）标题挂「低￥N」锚。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct", transfer_arrival_max="23:59")
        # 独占轮：无直飞行（best_direct=None）、中转行情破线（1650<
        # 1700）但无直挂标注不进 hits——旧行为两锚分支全跳过塌缩为
        # 「❌ 全部未达标｜清单」裸标题
        p = _ps([
            _fp(1650, "川航3U8863", "17:55", "18:50", trans="兰州",
                cross="+1天", layover=1375, layoverSrc="times"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        title = pv["title"]
        assert "低￥50" in title, title
        assert "❌ 全部未达标" in title, title

    def test_overline_anchor_priority_unchanged(self, monkeypatch):
        """超线锚优先（既有行为零回归）：超线与破线并存时挂超线锚。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct")
        p = _ps([
            _fp(1650, "川航3U8863", "17:55", "18:50", trans="兰州",
                cross="+1天", layover=1375, layoverSrc="times"),   # 破线、无直挂标注→不达标
            _fp(1620, "东航MU8370", "09:00", "14:10", plat="qunar"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        title = pv["title"]
        # 直飞差￥20 锚在场且优先（既有行为）；破线锚不与之争
        assert "差￥20" in title, title


class TestHitsHeadDualName:
    def test_dual_name_demotes_to_short(self, monkeypatch):
        """P3-1：双名超宽 → 剥营销名档保「金鹏航空 Y87519」。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700)
        p = _ps([_fp(1450, "新海航｜金鹏航空 Y87519", "09:05", "13:55",
                     plat="qunar")], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        desp = pv["desp"]
        m = re.search(r"> 🔥 \*\*直飞 ￥1450\*\*[^\n]*", desp)
        assert m, f"hits head 缺席: {desp[:400]}"
        head = m.group(0)
        assert "金鹏航空 Y87519" in head, head


class TestKpiL3TokenFloor:
    def test_l3_floor_no_half_token(self, monkeypatch):
        """P3-2：病理长 transCity 地板截不留半截 token（「停2:」）。

        夹具必须 transfer_arrival_max="23:59"（Soldier P1-2）：缺省
        02:00 到达约束把 18:50(+1天) 中转行判出局、行3 根本不渲染，
        半截断言对空 desp 恒真=修复无行为锁（变异不红）。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct", transfer_arrival_max="23:59")
        # 15 全角城市：经(2)+30+空格(1)=33 半角处，「停2:」token 恰
        # 装下而完整「停2:05」溢出（_dw_raw 数字 1.125 校准宽下累计
        # 到「停2」即破预算）——旧行为在此截出「停2:」半截
        long_city = "乌鲁木齐地窝堡国际机场中转楼站"
        p = _ps([
            _fp(1650, "川航3U8863", "17:55", "18:50", trans=long_city,
                cross="+1天", layover=125, layoverSrc="times",
                transferBaggage="direct"),
            _fp(1620, "东航MU8370", "09:00", "14:10", plat="qunar"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        # 前置断言：中转行真在场（best_transfer 非空）——行3 真渲染
        # 才有锁行为可言（真空通过防线）
        assert sections and sections[0].get("best_transfer") is not None, \
            "夹具失效：中转行被判出局，行3 不渲染（Soldier P1-2 同型）"
        pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        desp = pv["desp"]
        # 行3 真渲染锚：病理城市前缀在场（「经…」token 装载起点）
        assert f"经{long_city[:6]}" in desp, desp[:600]
        # 「停」token 若在，冒号后必须恰两位分钟（无半截）
        assert not re.search(r"停\d{1,2}:(?!\d{2})", desp), \
            f"半截 token 残留: {[l for l in desp.splitlines() if '停' in l][:3]}"


class TestPlaceholderTransRowPairing:
    def test_placeholder_trans_uses_stop_pairing(self):
        """P2-2 占位洞：transCity=「中转」占位 + stopCity 有值 →
        词面「经停庆阳」、停留取 stopTimeT（不再错配 layoverT）。"""
        f = {"transCity": "中转", "stopCity": "庆阳",
             "layoverT": "22:55", "stopTimeT": "0:45"}
        assert Alerter._trans_city(f) == ""
        assert Alerter._via_txt(f) == "经停庆阳"
        # 消费点配对口径（hits seg 同门）
        lay = str((f.get("layoverT") if Alerter._trans_city(f)
                   else f.get("stopTimeT")) or "").strip()
        assert lay == "0:45"


class TestTitleAnchorMultiBreak:
    def test_deepest_break_wins(self, monkeypatch):
        """P1-1：多破线候选挂 |gap| 最大的（价最低=最有希望）——
        比较符与原始负 gap 比较恒真曾退化成「最后扫到的赢」。"""
        a = _mk()
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700,
                  transfer_baggage="direct", transfer_arrival_max="23:59")
        # 两条破线中转：￥1500（低￥200）先入组、￥1650（低￥50）后入
        # ——扫到序的「最后赢」会错挂低￥50
        p = _ps([
            _fp(1500, "川航3U8863", "17:55", "18:50", trans="兰州",
                cross="+1天", layover=125, layoverSrc="times"),
            _fp(1650, "南航CZ6976", "12:05", "23:50", trans="郑州",
                cross="+1天", layover=200, layoverSrc="times"),
        ], "URC", "SHA", "2026-10-04")
        sections = a._build_sections(r, p)
        pv = a._digest_payload([(r, sections)], fresh=True,
                               with_tables=True)
        title = pv["title"]
        assert "低￥200" in title, title
        assert "低￥50" not in title, title

