# -*- coding: utf-8 -*-
"""r285 推送层立案（审校 P2×2 + P3×3）。

T1 P2-1 bare_mk 收域：保码剥跨天档只对 ∈hits 的 🔥 行启用——hits
   区只载 route-best（每节 best_direct/best_transfer），TOP5 里其余
   🔥 行是「价达标但非本档最优」的班次，消息内无第二承载位，旧形态
   对它们剥跨天=「19:55→01:25 被读成当日达」误判破口（图挂兜底轮
   恰是文本=明细唯一载体的时刻）。
T2 P2-2 档序对齐：经X（城市辨识）不再先于停X（时长量化）被丢——
   中间降级带保留经X、骨架带经X+停X、bare 舍停先于舍经、跨天恒保
   到地板；配对不变量（三十一§1 投影）：行含「 停X」⟹ 含 via
   （停多久必配经哪，兜底区只见停多久不知停哪翻案）。
T3 P3-1 降级 mini 行挂航线短名（降级面 26 条无主价格行翻案——
   mini 原生语境「节内第 2+ 日期」有 #### 标题托底，被复用为整节
   替身时失去归属载体）。
T4 P3-2 日报图挂兜底补「各渠道最低」段（与告警兜底
   _channel_market_lines 能力对称，三十§3）。
T5 P3-4 预览注插入 @ 段之前（@ 恒为消息末行不变量在预览器不破例）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r285_push.py -q
"""
import logging
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _al():
    from core.alerter import Alerter
    return Alerter(logging.getLogger("r285"), storage=None)


def _disp_dw(s):
    from core import alerter as _a
    return _a._disp_dw(s)


# ---- T1 P2-1 bare_mk 收域到 ∈hits ----

def _fire_base(**kw):
    f = {"name": "海航｜海南航空HU7815", "code": "HU7815", "price": 1595,
         "depTime": "19:55", "arrTime": "01:25", "crossDayDesc": "+1天",
         "_platform": "qunar"}
    f.update(kw)
    return f


class TestBareMkScopedToHits:
    """bare_mk 保码剥跨天档的启用域=「该行 ∈ hits」（hits 区 seg 行
    承载时刻+跨天）；非命中 🔥 行跨天恒保到地板。"""

    def test_non_hit_fire_row_keeps_cross(self):
        """TOP5 次优达标 🔥 行（非 hits）：跨天恒保（消息内无第二承载
        位——旧形态剥掉=误判当日达破口）。码在病理宽度下整码丢弃是
        既定地板语义（三十一§2，r257 钉面），本钉锁跨天恒保与无半截。"""
        ln = _al()._fmt_flight_line(_fire_base(), 2, "🔥 ")
        assert "+1天" in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_hit_fire_row_keeps_code_drops_cross(self):
        """∈hits 的 🔥 行：hits 区 seg 行承载时刻+跨天，保码剥跨天
        语义保持（r283 P2-1 立项语义收域后不变）。"""
        ln = _al()._fmt_flight_line(_fire_base(), 1, "🔥 ", in_hits=True)
        assert "HU7815" in ln, ln
        assert "+1天" not in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_non_hit_wide_name_cross_floor_and_no_half_code(self):
        """病理宽名非命中 🔥 行：跨天恒保到地板 + 无半截码（三十一§2）
        + 预算恒达标——跨天保全不得靠超宽实现。"""
        ln = _al()._fmt_flight_line(
            _fire_base(name="川航3U8863", code="川航3U8863", price=9876),
            2, "🔥 ")
        assert "+1天" in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_top3_blocks_scopes_bare_mk_to_best_only(self):
        """接线行为钉：_top3_blocks 对 best（∈hits）传 in_hits=True、
        次优 🔥 行不传——同消息内两行分工：best 行码保跨天让位
        （hits 区 seg 承载）、次优行跨天恒保。"""
        a = _al()
        route = SimpleNamespace(
            from_code="SHA", to_code="URC", from_name="上海",
            to_name="乌鲁木齐", alert_direct=1700, alert_transfer=0,
            transfer_baggage="", transfer_arrival_max="02:00",
            dep_time_min="", dep_time_max="")
        best = _fire_base(price=1600, name="海航HU7815",
                          depTime="21:10", arrTime="02:35")
        second = _fire_base(price=1650, name="国航CA1295", code="CA1295",
                            depTime="19:55", arrTime="01:25")
        s = {"date": "2026-10-27", "best_direct": best,
             "top_direct": [best, second], "best_transfer": None,
             "top_transfer": [], "seen_plats": ["qunar"],
             "all_flights": [best, second]}
        desp = a._top3_blocks(route, [s])
        b_line = [l for l in desp.split("\n\n") if "HU7815" in l]
        s_line = [l for l in desp.split("\n\n") if "19:55" in l]
        assert b_line and s_line, desp
        # best ∈ hits：hits 区 seg 行承载跨天，TOP3 行保码剥跨天
        assert "+1天" not in b_line[0], b_line[0]
        # 次优 🔥 行不在 hits：跨天恒保（修复断言）
        assert "+1天" in s_line[0], s_line[0]


# ---- T2 P2-2 档序对齐（经X 不先于停X 丢） ----

def _transfer_base(**kw):
    f = {"price": 870, "name": "南航CZ6949/HO1108",
         "code": "CZ6949/HO1108", "depTime": "08:30", "arrTime": "20:00",
         "crossDayDesc": "", "transCity": "郑州", "layoverT": "2:05",
         "totalDuration": "11时30分", "_platform": "ctrip"}
    f.update(kw)
    return f


class TestViaOrderAlignedWithSegChain:
    """停多久必配经哪（配对不变量）：任何降级档输出行含「 停」⟹
    含经郑州——seg 链档序（丢停留时长→丢经停城市→保时刻跨天）投影
    到 TOP3 行降级链。"""

    @pytest.mark.parametrize("name", [
        "MU6716",
        "南航CZ6949",
        "南航CZ6949/HO1108",
        "海南航空｜金鹏航空Y87519",
        "中国联合航空KN5977｜中联航KN5977超长双名形态",
    ])
    @pytest.mark.parametrize("cross,lay", [("", "2:05"),
                                           ("+1天", "2:05"),
                                           ("+1天", "22:55")])
    def test_stop_always_paired_with_via(self, name, cross, lay):
        ln = _al()._fmt_flight_line(
            _transfer_base(name=name, code=name, crossDayDesc=cross,
                           layoverT=lay), 1)
        assert _disp_dw(ln) <= 40, ln
        if " 停" in ln:
            assert "经郑州" in ln, f"裸停无城市（不知停哪）：{ln!r}"
        if cross:
            assert cross in ln, f"跨天恒保到地板：{ln!r}"

    def test_stop_never_naked_in_deep_band(self):
        """深降级带不产「裸停」（停X 无经X 配对）——旧 slim3 带
        「…20:00 停2:05（携程）」形态（城市先于时长被丢，兜底区只见
        停多久不知停哪）翻案；40 半角下经X+停X+渠道同框本属稀有，
        实效锁语义：停X 或与经X 同框、或整段让位。"""
        a = _al()
        f = _transfer_base(name="南航CZ6949", code="CZ6949")
        ln = a._fmt_flight_line(f, 1)
        assert _disp_dw(ln) <= 40, ln
        assert " 停" not in ln or "经郑州" in ln, ln

    def test_long_name_band_keeps_via_after_stop_dropped(self):
        """骨架/地板带（名字段让位后）：经X 仍在（舍停先于舍经，
        城市辨识不先于时长量化被丢）。"""
        a = _al()
        f = _transfer_base(name="海南航空｜金鹏航空Y87519双名长形态",
                           code="Y87519")
        ln = a._fmt_flight_line(f, 1)
        assert "Y87519" in ln and "经郑州" in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_bare_drops_stop_before_via(self):
        """bare 档超宽：先舍停X（时长量化）保经X（城市辨识）——
        seg 链同律；经X 只在码放不下时最后让位，跨天恒保。"""
        a = _al()
        f = _transfer_base(name="中国联合航空KN5977｜中联航KN5977长双名",
                           code="KN5977/KN1234", crossDayDesc="+1天",
                           layoverT="2:05")
        ln = a._fmt_flight_line(f, 1)
        assert _disp_dw(ln) <= 40, ln
        assert "+1天" in ln, f"跨天恒保：{ln!r}"


# ---- T3 P3-1 降级 mini 行挂航线短名 ----

class TestMiniRouteTag:
    """整节降级替身语境（minis 顶替全节文本）：mini 行头部带航线短名
    「📍 广→乌 10/27」——离链辨识归属；节内第 2+ 日期语境（默认）
    不带（上方 #### 标题托底，常态不加状态标识律）。"""

    def _payload_many_routes(self):
        """多航线把节预算吃爆，触发整节降级替身（minis 顶替全节）。"""
        a = _al()
        from core.models import Route as _R
        cities = [("广州", "乌海", "CAN", "WUA"),
                  ("上海", "乌鲁木齐", "SHA", "URC"),
                  ("北京", "西安", "BJS", "SIA"),
                  ("成都", "杭州", "CTU", "HGH"),
                  ("深圳", "昆明", "SZX", "KMG"),
                  ("重庆", "南京", "CKG", "NKG"),
                  ("武汉", "青岛", "WUH", "TAO"),
                  ("长沙", "厦门", "CSX", "XMN"),
                  ("南京", "兰州", "NKG", "LHW"),
                  ("天津", "贵阳", "TSN", "KWE"),
                  ("合肥", "宁波", "HFE", "NGB"),
                  ("郑州", "海口", "CGO", "HAK"),
                  ("济南", "大连", "TNA", "DLC"),
                  ("太原", "南宁", "TYN", "NNG"),
                  ("南昌", "石家庄", "KHN", "SJW"),
                  ("长春", "银川", "CGQ", "INC"),
                  ("哈尔滨", "西宁", "HRB", "XNN"),
                  ("沈阳", "拉萨", "SHE", "LXA"),
                  ("呼和浩特", "桂林", "HET", "KWL"),
                  ("无锡", "丽江", "WUX", "LJG"),
                  ("烟台", "佛山", "YNT", "FUO"),
                  ("温州", "包头", "WNZ", "BAV"),
                  ("珠海", "洛阳", "ZUH", "LYA"),
                  ("泉州", "榆林", "JJN", "UYN")]
        rs = []
        # r318 心跳轻量化随迁：整节降级替身的载体在达标/回落轮（未达标
        # 轮 desp 压缩为单行 KPI 摘要恒低于预算，无降级面）——夹具改
        # 达标价（1650+k ≤ 1700+k 线）触发全量小节的预算竞争，钉面
        # 语义不变
        for k, (fn, tn, fc, tc) in enumerate(cities):
            r = _R(from_code=fc, to_code=tc, from_name=fn, to_name=tn,
                   dates=["2026-10-27", "2026-10-28"],
                   alert_direct=1700 + k, alert_transfer=1500 + k)

            def _sec(date, dp):
                return {"date": date,
                        "best_direct": {"price": dp, "name": "CZ3341",
                                        "depTime": "08:00",
                                        "arrTime": "11:20",
                                        "_platform": "qunar"},
                        "best_transfer": None, "seen_plats": ["qunar"]}

            rs.append((r, [_sec("2026-10-27", 1650 + k),
                           _sec("2026-10-28", 1655 + k)]))
        return a._digest_payload(rs, fresh=True,
                                 with_tables=False, with_charts=False)

    def test_demoted_mini_rows_carry_route_tag(self):
        import re as _re
        p = self._payload_many_routes()
        d = p["desp"]
        # r318 心跳轻量化随迁：达标多航线轮的预算让位由 hits 行区
        # 主导（sec 节超共享池转 mini 替身）——降级说明行走
        # hit_demoted 态 mid 档「命中行仅价格」；「仅列关键价」full
        # 档的可达面（未达标全量小节降级）已随轻量化退役
        assert "航线较多" in d, "夹具未触发降级，先修夹具"
        # 降级替身与命中行带航线短名——离链可辨识；前段完整节走全名
        # 标题不降级。断言按「📍 短名 日期」模式计数，不锚具体航线
        # （预算边界上最末节可能整体让位静默消失）
        tagged = _re.findall(r"📍 .→. \d{2}/\d{2}", d)
        assert len(tagged) >= 4, f"带航线短名的降级 mini 行不足: {tagged!r}"

    def test_in_section_mini_rows_untagged(self):
        """节内第 2+ 日期语境：mini 行不带航线短名（标题托底）——
        旧行为零变化。
        r318 随迁：📍 日期标签载体在全量小节，夹具改达标轮。"""
        a = _al()
        from core.models import Route as _R
        r = _R(from_code="CAN", to_code="WUA", from_name="广州",
               to_name="乌海", dates=["2026-10-27", "2026-10-28"],
               alert_direct=1900, alert_transfer=1700)

        def _sec(date, dp):
            return {"date": date,
                    "best_direct": {"price": dp, "name": "CZ3341",
                                    "depTime": "08:00", "arrTime": "11:20",
                                    "_platform": "qunar"},
                    "best_transfer": None, "seen_plats": ["qunar"]}

        p = a._digest_payload(
            [(r, [_sec("2026-10-27", 1800), _sec("2026-10-28", 1820)])],
            fresh=True, with_tables=False, with_charts=False)
        d = p["desp"]
        assert "📍 10/28" in d, d
        assert "📍 广→乌" not in d, d


# ---- T4 P3-2 日报兜底补渠道最低段 ----

class TestDailyMarketFallback:
    def test_lines_shape_and_budget(self):
        from report import _daily_market_fallback
        out = _daily_market_fallback(
            {"qunar": (1660.0, True), "ctrip": (1700.0, True),
             "fliggy": (1710.0, True)})
        assert "- 去哪儿 最低 ￥1660" in out, out
        assert "- 携程 最低 ￥1700" in out, out
        assert "- 飞猪 最低 ￥1710" in out, out
        for ln in out.strip().split("\n\n"):
            assert _disp_dw(ln) <= 40, ln

    def test_empty_pmins_silent(self):
        from report import _daily_market_fallback
        assert _daily_market_fallback({}) == ""

    def test_wired_into_both_daily_fallback_branches(self):
        """两个图挂兜底分支（上传失败/渲染异常）同接 _daily_market_
        fallback——能力对称收编不许只落一条路径（三十§3）。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "report.py"),
            encoding="utf-8").read()
        assert src.count("_daily_market_fallback(") >= 3, \
            "定义+两个兜底分支接线不足"


# ---- T5 P3-4 预览注插入 @ 段之前 ----

def test_preview_note_before_at_segment():
    """预览注改走 _append_before_at 同律：@ 恒为消息末行不变量在
    预览器不破例（r283 P3-4 源码钉随形态改写：前导 \n\n 改由
    _append_before_at 单源承担）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"),
        encoding="utf-8").read()
    assert 'p["desp"], "> （预览态无明细总表图' in src, \
        "预览注未走 @ 前插单源"
    assert "_append_before_at(" in src, "单源调用缺席"

