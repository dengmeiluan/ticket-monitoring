# -*- coding: utf-8 -*-
"""r220 推送层:P1 图挂兜底路径裸单 \\n(钉钉 PC 粘段墙)复现钉。

图挂兜底是总表缺失日读者唯一明细载体,行间单 \\n 在钉钉 PC
粘成整段(LESSONS 十§1:PC 不认单 \\n);近 3 天零残留只因总表一直
成功——代码路径必须按渲染铁律产出。
"""
import datetime as dt
import json
import logging
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402
from core.models import Route, FlightPrice  # noqa: E402


def _fp(price, name, dpt, art, trans="", cross="", plat="qunar",
        dep="2026-10-04"):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else 0
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


def _fallback_desp(monkeypatch):
    log = logging.getLogger("r220probe")
    logging.basicConfig(level=logging.CRITICAL)

    class FakeN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            return True

    a = Alerter(log, notifier=FakeN(), storage=None, digest=True,
                at_mobile="", storm_repeat=1, user="演练")
    monkeypatch.setattr(Alerter, "_flights_table_md_multi",
                        lambda self, rs, **kw: None)  # 图挂
    r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
              to_name="上海", dates=["2026-10-04"],
              alert_direct=1600, alert_transfer=1700)
    p = _ps([_fp(1599, "南航CZ6981", "18:30", "23:40"),
             _fp(1602, "东航MU8370", "09:00", "14:10"),
             _fp(1620, "国航CA1295", "17:05", "22:30"),
             _fp(1700, "川航3U8863", "12:00", "17:40", trans="郑州",
                 plat="ctrip")], "URC", "SHA", "2026-10-04")
    sections = a._build_sections(r, p)
    pv = a._digest_payload([(r, sections)], fresh=True, with_tables=True)
    return pv["desp"]


class TestImgFailFallbackParagraphs:
    def test_fallback_block_has_no_bare_newline_rows(self, monkeypatch):
        """兜底明细区(总表失败头之后)零裸单 \\n 行:TOP5 序号行/渠道
        最低行/暂无行一律段落级 \\n\\n 分隔。"""
        desp = _fallback_desp(monkeypatch)
        assert "明细总表缺失" in desp, "未走图挂兜底分支(样本失效)"
        head_i = desp.index("明细总表缺失")
        block = desp[head_i:]
        # 裸单 \n 相邻非空行:前一字符非 \n、后一行非空——兜底区禁绝
        bare = [(m.start(), block[max(0, m.start() - 24):m.start() + 30])
                for m in re.finditer(r"(?<!\n)\n(?!\n)(?!$)", block)
                if block[m.start() + 1:m.start() + 2] not in ("",)]
        # 允许例外:行内换行只有 markdown 结构行首(####/>/-/数字.)才合法,
        # 且也必须段落级——兜底区内任何「单 \n 接非空」都判违例
        assert not bare, f"兜底区裸单 \\n {len(bare)} 处,首处现场: {bare[0]}"

    def test_top5_seq_lines_double_newline(self, monkeypatch):
        """TOP5 序号行相邻分隔必为 \\n\\n;兜底区零三连 \\n(组尾冗余空行)。"""
        desp = _fallback_desp(monkeypatch)
        for n in ("2", "3"):
            assert f"\n\n{n}. " in desp, f"TOP5 序号 {n} 前非段落分隔"
        head_i = desp.index("明细总表缺失")
        assert "\n\n\n" not in desp[head_i:], "兜底区三连 \\n(组尾空行残留)"


class TestDwAsciiCalibration:
    """_dw 宽度模型 ASCII 校准:msyh16 实测数字 advance 9px、% 14px,
    旧模型按 1 半角(8px)计——贴线 40/40 行真实渲染 20.5 全角超 20 红线
    (近 3 天 362 行超宽,5 形态)。行级向上取整=守卫只可高估不可低估。"""

    def test_digits_wider_than_one_halfwidth(self):
        from core.alerter import _dw
        assert _dw("0000000000") > 10, "数字仍按 1 半角计(未校准)"

    def test_percent_wider_than_one_halfwidth(self):
        from core.alerter import _dw
        assert _dw("%%") >= 3, "%% 仍按 2 半角计(未校准)"

    def test_cjk_unchanged(self):
        from core.alerter import _dw
        assert _dw("乌鲁木齐") == 8

    def test_kpi_line1_calibrated_form_fits(self):
        """审计实锤最深形态(🎯 直飞+线+低+（N%）)在校准模型下不再贴线:
        产出行 _dw ≤40 恒成立(_fit_line 降档兜住真实渲染宽)。"""
        from core.alerter import _dw, _fit_line
        base = "🎯 直飞 ￥1760　线￥1900　低￥140"
        forms = [base + "（7%）", base + " 7%", base]
        line = _fit_line(forms[0], fallbacks=forms[1:])
        assert _dw(line) <= 40, f"校准后仍超宽: {line!r} {_dw(line)}"
        assert "低￥" in line, "降档丢核心判据(地板档纪律)"


class TestCalibratedFallbackTiers:
    """r220 校准补档正向钉(防回潮):双名剥档/渠道让位档/去括号骨架档。"""

    def test_l2_dual_name_strip_tier_keeps_cross(self):
        """双名 base 超预算时「剥 A｜ 保时刻+跨天」档在 bare 之前——
        硬截曾把到达时刻截成 21:10→0(比丢括注更糟)。"""
        from core.alerter import _disp_dw, _fit_line, _l2_fallbacks
        base = "新海航｜海南航空HU7849 21:10→02:35"
        cross, d = "+1天", " ｜ 较上轮 ↓￥133"
        tiers = _l2_fallbacks(base, cross, d)
        assert any(t.startswith("海南航空") and "+1天" in t for t in tiers), \
            f"缺双名剥档: {tiers!r}"
        out = _fit_line(base + cross, fallbacks=tiers)
        assert "+1天" in out and "21:10→02:35" in out, \
            f"跨天括注/时刻丢失: {out!r}"
        assert _disp_dw(out) <= 40

    def test_ops_first_channel_yield_tier(self):
        """(截) 与首渠道名争预算时渠道名优先的让位档在场。"""
        from core.alerter import _ops_fallbacks
        n = "乌上 10/05 无数据：飞猪(维护中)、去哪儿、携程、同程、途牛"
        tiers = _ops_fallbacks(n)
        assert any("飞猪(维护中)" in t and "(截)" not in t for t in tiers), \
            f"缺首渠道让位档: {tiers!r}"

    def test_flight_line_skeleton_no_bracket_tier(self):
        """骨架去括号档执行级钉：恰卡 41 的「（同价×N）」形态实调降档,
        产出=同价计数保留+括号被剥(nb 档特征)+恒 ≤40——源码钉验不了
        「恰卡 41 塌 bare 丢计数」的行为,也不验档序。"""
        from core.alerter import Alerter, _disp_dw
        f = {"_platform": "qunar", "_tie_n": 5, "price": 2200,
             "name": "9C6928", "code": "9C6928", "depTime": "19:05",
             "arrTime": "23:55"}
        out = Alerter._fmt_flight_line(f, 1, "")
        assert "同价×5" in out, f"骨架降档丢同价计数: {out!r}"
        assert "（" not in out and "）" not in out, \
            f"未走去括号档(仍带括号): {out!r}"
        assert _disp_dw(out) <= 40, f"超宽: {out!r}"


class TestFallbackEmptyBranchParagraphs:
    """「暂无」分支段落级 \\n\\n：标题前导 \\n 与组尾 \\n 随行间
    \\n\\n 化退役后,暂无行是段落分隔唯一补偿位——单 \\n 接标题
    （钉钉 PC 不认单 \\n,粘段墙）。有数据夹具钉不住空分支。"""

    def test_empty_top5_branches_double_newline(self):
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route
        _lg.basicConfig(level=_lg.CRITICAL)
        a = Alerter(_lg.getLogger("r220fb"), notifier=None, storage=None,
                    digest=True, at_mobile="", storm_repeat=1, user="u")
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700)
        s = {"date": "2026-10-04", "top_direct": [], "top_transfer": [],
             "plat_top3": {}, "platform_mins": {}}
        out = a._top3_blocks(r, [s])
        assert "直飞最优TOP5" in out, "未进 TOP5 渲染路径(样本失效)"
        assert "- 暂无数据\n\n" in out, \
            f"暂无直飞行裸单 \\n 接标题: {out!r}"
        assert "- 暂无满足到达约束的中转\n\n" in out, \
            f"暂无中转行裸单 \\n 接组尾: {out!r}"
        assert "\n\n\n" not in out, "兜底区三连 \\n"

    def test_cross_compare_tail_no_triple_newline(self):
        """比价组尾恒 \\n\\n 收束：尾 \\n 核减后组间不得三连(与组尾
        核减理由同源——行间已 \\n\\n 化,再追加即冗余空行)。"""
        import json as _json
        import logging as _lg
        from core.alerter import Alerter
        from core.models import FlightPrice, Route
        _lg.basicConfig(level=_lg.CRITICAL)

        def fp(plat, price):
            f = {"price": price, "name": "南航CZ6981", "code": "CZ6981",
                 "depTime": "18:30", "arrTime": "23:40",
                 "depDate": "2026-10-04", "arrDate": "2026-10-04",
                 "totalDuration": "5时", "_platform": plat}
            return FlightPrice(platform=plat, from_city="URC",
                               to_city="SHA", depart_date="2026-10-04",
                               price=price,
                               extra=_json.dumps([f], ensure_ascii=False))

        log = _lg.getLogger("r220cc")
        a = Alerter(log, notifier=None, storage=None, digest=True,
                    at_mobile="", storm_repeat=1, user="u")
        r = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
                  to_name="上海", dates=["2026-10-04"],
                  alert_direct=1600, alert_transfer=1700)
        secs = a._build_sections(r, [fp("qunar", 1500), fp("ctrip", 1602)])
        cc = Alerter._cross_compare(secs)
        assert "同班比价" in cc, "无比价节(样本失效:候选未触发)"
        assert cc.endswith("\n\n"), f"组尾非段落级收束: {cc[-24:]!r}"
        assert "\n\n\n" not in cc, "比价组三连 \\n"
