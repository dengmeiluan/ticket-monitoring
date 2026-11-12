# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r243_push.py
- tests/test_r271_push.py
- tests/test_v171_push.py
- tests/test_v185_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime as dt
import json
import logging
import os
import pytest
import report
import report as _rep
import sys

from core.alerter import Alerter
from core.models import FlightPrice, Route, Route as _R
from types import SimpleNamespace


# ---- merged from tests/test_r243_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r243")


def _route(alert_direct=1900, alert_transfer=1700):
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=alert_direct, alert_transfer=alert_transfer)


def _sections():
    s = {"date": "2026-09-25",
         "best_direct": {"price": 1950, "name": "MU8369",
                         "depTime": "19:55", "arrTime": "01:25",
                         "_platform": "qunar"},
         "best_transfer": None,
         "seen_plats": ["qunar"]}
    return [s]


class _FakeStor:
    db_path = ":memory:"


def _al(stor=None, charts=None):
    a = Alerter(_LOG, storage=stor, digest=True)
    a.round_charts = charts or {}
    return a


def _payload(a, route=None, **kw):
    kw.setdefault("fresh", False)
    kw.setdefault("with_tables", False)
    return a._digest_payload([(route or _route(), _sections())], **kw)


_OK = dict(alert_direct=2000)   # 达标夹具：1950 ≤ 2000 → hits 走全量小节


def test_trend_line_exception_marks_gap(monkeypatch):
    """P1-1：_rounds 查询异常（磁盘满窗实锤形态）→ desp 补
    「近7天趋势暂缺」标注，不再静默消失。
    r318 心跳轻量化随迁：趋势行载体在全量小节（达标/回落轮），
    未达标轮 desp 无趋势行位——夹具改达标轮，钉面语义不变。"""
    def _boom(*_a, **_k):
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(_rep, "_rounds", _boom)
    p = _payload(_al(stor=_FakeStor()), route=_route(**_OK))
    assert "近7天趋势暂缺" in p["desp"], p["desp"][:600]


def test_trend_line_exception_logged(monkeypatch, caplog):
    """P1-1：异常必须留日志痕（本轮省略的事实与原因可对账）。"""
    def _boom(*_a, **_k):
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(_rep, "_rounds", _boom)
    with caplog.at_level(logging.WARNING, logger="r243"):
        _payload(_al(stor=_FakeStor()), route=_route(**_OK))
    assert any("趋势" in r.message for r in caplog.records), caplog.text


def test_trend_line_no_data_stays_silent(monkeypatch):
    """无数据（空窗合法形态）语义不变：整行省略，不出「暂缺」标注
    （异常才提示，常态零噪音）。"""
    monkeypatch.setattr(_rep, "_rounds", lambda *a, **k: [])
    p = _payload(_al(stor=_FakeStor()), route=_route(**_OK))
    assert "暂缺" not in p["desp"], p["desp"][:600]


def test_trend_line_ok_kept(monkeypatch):
    """正常趋势行回归锚：直飞 ↓16% 词面原样（修复不伤常态）。"""
    monkeypatch.setattr(
        _rep, "_rounds",
        lambda *a, **k: [["2026-09-19", 1900, 2100],
                         ["2026-09-25", 1600, 2000]])
    p = _payload(_al(stor=_FakeStor()), route=_route(**_OK))
    assert "近7天" in p["desp"] and "↓16%" in p["desp"], p["desp"][:600]


def test_missing_chart_neutral_word():
    """P2-1：缺图词面中性化「走势图缺失」——不再猜测「上传失败」
    具体归因（生成失败/上传失败在 alerter 层不可分辨，归因看日志）。
    r318 随迁：缺图词面载体在全量小节，夹具改达标轮。"""
    p = _payload(_al(), route=_route(**_OK))
    assert "走势图缺失" in p["desp"], p["desp"][:600]
    assert "上传失败" not in p["desp"], p["desp"][:600]


def test_missing_chart_word_absent_when_chart_ok():
    """图在时零假警告回归锚（test_core_units 既有语义跨改词面保留）。"""
    p = _payload(_al(charts={("SHA", "URC", "2026-09-25"):
                             "https://x/y.png"}), route=_route(**_OK))
    assert "走势图缺失" not in p["desp"], p["desp"][:600]


def test_kpi_l2_cross_parenthesized(monkeypatch):
    """P2-2：KPI 行2 跨天词面括注态「19:55→00:05(+1天)」——与 🔥 行
    base_seg 同贴法（同屏 bare/括注双形态收口）。
    r318 随迁：KPI 行2 载体在全量小节，夹具改达标轮。"""
    monkeypatch.setattr(_rep, "_rounds", lambda *a, **k: [])
    a = _al(stor=_FakeStor())
    secs = _sections()
    secs[0]["best_direct"] = dict(
        secs[0]["best_direct"], arrTime="00:05",
        crossDayDesc="+1天")
    p = a._digest_payload([(_route(**_OK), secs)], fresh=False,
                          with_tables=False)
    assert "00:05(+1天)" in p["desp"], p["desp"][:700]
    assert "00:05+1天" not in p["desp"], p["desp"][:700]


def test_kpi_l2_cross_paren_kept_under_degrade(monkeypatch):
    """降级链连验：超宽身份行（长双名+跨天）降档后到达时刻+括注
    必须在位（括注 +2 半角不得把辨识信息挤丢失）。"""
    monkeypatch.setattr(_rep, "_rounds", lambda *a, **k: [])
    a = _al(stor=_FakeStor())
    secs = _sections()
    secs[0]["best_direct"] = dict(
        secs[0]["best_direct"], name="新海航｜海南航空 HU7849",
        arrTime="00:05", crossDayDesc="+1天")
    p = a._digest_payload([(_route(**_OK), secs)], fresh=False,
                          with_tables=False)
    assert "00:05(+1天)" in p["desp"], p["desp"][:700]


def test_daily_miss_chart_line_neutral():
    """P1-S1：日报缺图行与主推送同律中性化（同因两词面跨推送并存
    曾误导 ops 对账——生成失败/上传失败在消费层不可分辨）。"""
    from report import _miss_chart_line
    # 短名样本逼出首档（全名首档恒超宽走末档「本期无图」，本就中性）
    line = _miss_chart_line("乌→上", "2026-10-05")
    assert "走势图缺失" in line, line
    assert "上传失败" not in line, line
    # 全名降档路径回归锚：末档词面中性（日期+「本期无图」保辨识）
    line2 = _miss_chart_line("上海→乌鲁木齐", "2026-10-05")
    assert "上传失败" not in line2 and "10/05" in line2, line2


def test_summary_table_fallback_neutral(monkeypatch):
    """总表兜底头同律：render/上传失败在 alerter 层同表现为无图，
    词面去归因化「明细总表缺失」（完整明细见控制台的出口指引保留）。"""
    import logging as _lg
    # 总表缺失分支单元直调（十九§14：_flights_table_md_multi 整体返回
    # 空才触发 _fb_head，全链构造要绕过多级文字回退，直调锁分支输出）
    monkeypatch.setattr(Alerter, "_flights_table_md_multi",
                        lambda self, rs_list, ops_notes=None: "")
    a = Alerter(_lg.getLogger("r243"), storage=None, digest=True)
    p = a._digest_payload([(_route(), _sections())], fresh=False)
    assert "明细总表缺失" in p["desp"], p["desp"][-500:]
    assert "明细总表上传失败" not in p["desp"], p["desp"][-500:]


def test_table_miss_words_source_pin():
    """日报明细表缺图行同律（词面源码钉：日报组装构造重，锁出口词面）。"""
    src = open(os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))),
        "report.py"), encoding="utf-8").read()
    assert "明细总表缺失" in src
    # 禁复活段：与同消息挂载头「明细总表」同物异名的旧称谓退役
    # （审校 P3-1 裁决：称谓统一，含留痕/省略/生成失败三族产出位）
    assert "明细表缺失" not in src
    assert "明细表上传失败" not in src
    assert "明细表省略" not in src
    assert "明细表生成失败" not in src


# ---- merged from tests/test_r271_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _cfg(enabled):
    route = {"from": "URC", "from_name": "乌鲁木齐", "to": "SHA",
             "to_name": "上海", "dates": ["2026-10-15"],
             "alert_direct": 1900, "alert_transfer": 1700,
             "enabled": enabled}
    return {
        "notifier": {"image_host": {"provider": "ghimg", "repo": "o/r",
                                    "token": "t"}},
        "users": [{"name": "u1", "routes": [route],
                   "platforms": ["qunar"]}],
    }


class _Notif(object):
    last_errcode = None


@pytest.fixture()
def empty_charts(monkeypatch):
    monkeypatch.setattr(report, "prepare_round_charts",
                        lambda *a, **k: {})


def _warns(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING]


def _infos(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno == logging.INFO]


def test_suspended_routes_info_not_warning(caplog, empty_charts):
    caplog.set_level(logging.DEBUG)
    ok = report.build_and_push(
        _cfg(False), logging.getLogger("t"), _Notif(), user="u1")
    assert ok is False
    assert not any("暂无可画数据" in m for m in _warns(caplog)), \
        _warns(caplog)
    assert any("停用" in m for m in _infos(caplog)), _infos(caplog)


def test_active_routes_empty_charts_keeps_warning(caplog, empty_charts):
    caplog.set_level(logging.DEBUG)
    ok = report.build_and_push(
        _cfg(True), logging.getLogger("t"), _Notif(), user="u1")
    assert ok is False
    assert any("暂无可画数据" in m for m in _warns(caplog)), _warns(caplog)


def test_enabled_routes_single_source():
    # 单源钉：裸「enabled is not False」口径只许 helper 定义处 1 次，
    # 消费点（出图遍历/日报查价入口/空图归因）一律走 _enabled_routes
    src = open("report.py", encoding="utf-8").read()
    assert src.count('enabled") is not False') == 1, \
        "裸启用口径残留（绕过 _enabled_routes 单源）"
    assert src.count("def _enabled_routes") == 1
    # 消费 4 处：_chart_routes 出图遍历 / prepare_round_charts user 分支 /
    # 日报 _fr 查价入口 / build_and_push 空图归因，+定义处 1 = 5
    assert src.count("_enabled_routes(") == 5, "helper 消费点数量漂移"


# ---- 落地案2：总表空态归因词面按真约束成分拼装（推送审校 P3-①） ----

def test_transfer_empty_note_no_layover_no_zero_word():
    # 未配置衔接下限（lay_min=0）不出「衔接≥0 分钟」负信息段，
    # 到达约束在场时只归因到达段
    from report import _transfer_empty_note as note
    got = note(0, "02:00")
    assert "衔接" not in got, got
    assert got == "暂无满足约束的班次（02:00 前到达）", got


def test_transfer_empty_note_full_form_unchanged():
    # 双约束在场与「衔接+缺省到达兜底」两档与旧词面全等（零回归面）
    from report import _transfer_empty_note as note
    assert note(90, "02:00") == \
        "暂无满足约束的班次（衔接≥90 分钟·02:00 前到达）"
    assert note(90, "") == \
        "暂无满足约束的班次（衔接≥90 分钟·次日 02:00 前到达）"


def test_transfer_empty_note_no_constraint():
    # 双约束皆缺省归因渠道未回数（原语义不动）
    from report import _transfer_empty_note as note
    assert note(0, "") == "暂无数据（该轮渠道未回中转班次，下轮自动补上）"


def test_transfer_empty_note_single_source():
    # 渲染点消费纯函数：「衔接≥」模板只许纯函数定义处 1 次
    src = open("report.py", encoding="utf-8").read()
    assert src.count("衔接≥%d 分钟") == 1, "空态归因模板残留（绕过纯函数）"


# ---- merged from tests/test_v171_push.py ----

_NS = SimpleNamespace(from_code="URC", from_name="乌鲁木齐",
                      to_code="SHA", to_name="上海")
_DATE = "2026-10-05"


class TestDailyViewUrlV171:
    """日报「🔍 打开渠道查现价」链接修复钉。"""

    @staticmethod
    def _report_src():
        import report as _r
        with open(_r.__file__, encoding="utf-8") as f:
            return f.read()

    def test_report_calls_with_none_self_placeholder(self):
        """源码钉：4 参 None 占 self 范式在位，3 参死码形态消失。"""
        src = self._report_src()
        assert "Alerter._build_view_url(None, _vs, date, _plat)" in src, \
            "report.py 未按 None 占 self 范式调用 _build_view_url（🔍 链接恒死码回潮）"
        assert "Alerter._build_view_url(_vs, date, _plat)" not in src, \
            "3 参死码调用形态残留（少 self 占位恒 TypeError）"

    def test_report_no_silent_pass_on_link(self):
        """源码钉：🔍 段 except 不再裸 pass（降 logger.debug 留痕）。"""
        src = self._report_src()
        i = src.find("_build_view_url")
        seg = src[i:i + 900]
        assert "except Exception:\n            pass" not in seg, \
            "🔍 段仍是裸 pass 静默吞异常（故障不可观测）"
        assert "logger.debug" in seg, "🔍 段异常未留痕"

    def test_none_self_paradigm_real_execute(self):
        """执行级钉：None 占 self 对五渠道真调返回与爬虫同域的 URL。"""
        from core.alerter import Alerter
        expect = {
            "qunar": "https://m.flight.qunar.com",
            "ctrip": "https://m.ctrip.com",
            "tuniu": "https://m.tuniu.com",
            "tongcheng": "https://m.ly.com",
            "fliggy": "https://sjipiao.fliggy.com",
        }
        for plat, domain in expect.items():
            url = Alerter._build_view_url(None, _NS, _DATE, plat)
            assert url and url.startswith(domain), \
                "%s 链接异常: %r" % (plat, url)
            assert _DATE.replace("-", "") in url or _DATE in url, \
                "%s 链接缺日期参数: %r" % (plat, url)

    def test_unknown_platform_returns_empty(self):
        """执行级钉：未知/空平台返回 ""（宁缺勿错契约保持——report 端
        if _vu 跳过，不出死链）。"""
        from core.alerter import Alerter
        assert Alerter._build_view_url(None, _NS, _DATE, "") == ""
        assert Alerter._build_view_url(None, _NS, _DATE, "nosuch") == ""


# ---- merged from tests/test_v185_push.py ----

def _fp(price, name, dpt, art, dep):
    d0 = dt.date.fromisoformat(dep)
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep,
            "arrDate": str(d0 + dt.timedelta(days=1)),
            "transCity": "", "crossDayDesc": "+1天",
            "totalDuration": "6时", "_platform": "qunar"}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _alerter():
    log = logging.getLogger("v185probe")
    logging.basicConfig(level=logging.CRITICAL)

    class FakeN:
        def send(self, *a, **k):
            return True
    return Alerter(log, notifier=FakeN(), storage=None, digest=True,
                   at_mobile="13800001234", storm_repeat=0, user="probe")


def _built(a, n_routes):
    """n_routes 条全达标航线 × 2 日期(规模化达标压力场景)。"""
    built = []
    for i in range(n_routes):
        d1 = "2026-10-0%d" % (1 + i % 9)
        d2 = "2026-10-1%d" % (i % 10)
        r = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐%d" % i, dates=[d1, d2],
                  alert_direct=5000, alert_transfer=0)
        p1 = _ps([_fp(2000 - i, "南航CZ697%d" % i, "17:05", "00:05", d1)],
                 "SHA", "URC", d1)
        p2 = _ps([_fp(2100 - i, "南航CZ698%d" % i, "18:30", "23:40", d2)],
                 "SHA", "URC", d2)
        built.append((r, a._build_sections(r, p1 + p2)))
    return built


class TestDigestBudgetScale:
    """立案 P2-②:规模化达标不击穿发送端切点,判据地板档恒落位。"""

    def test_qualified_scale_within_byte_ceiling(self):
        a = _alerter()
        pv = a._digest_payload(_built(a, 20), fresh=True, with_tables=False)
        b = len(pv["desp"].encode("utf-8"))
        # 构建端份额控制:20 航线全达标实测曾 31506B——发送端 17900B
        # 截断吃掉尾部总表/@段;构建端受控后恒 ≤17800(留尾注余量)
        assert b <= 17800, f"规模化达标 desp 超预算: {b}B"

    def test_hit_head_verdicts_survive(self):
        a = _alerter()
        pv = a._digest_payload(_built(a, 20), fresh=True, with_tables=False)
        # 地板档=🔥 价格判据行:份额降级只丢 seg/tail(时刻/链接),
        # 判据(能不能出手、多少钱)40 条全保
        assert pv["desp"].count("🔥") == 40, \
            f"命中判据行被预算吞: {pv['desp'].count('🔥')}/40"

    def test_demote_note_covers_hit_loss(self):
        a = _alerter()
        pv = a._digest_payload(_built(a, 40), fresh=True, with_tables=False)
        # 40 航线强压场景触发 hit 降级:说明行钉死 hit 丢失面词面
        # (命中行仅价格),不能只说「航线较多」。全形态「仅价格判据」
        # 55/40 超宽(审校 P2-1),降级等义压缩档保「命中行仅价格」
        assert "命中行仅价格" in pv["desp"], \
            "降级说明行缺 hit 丢失面语义"


class TestRecheckBadgeAndTailNote:
    """立案 P2-①+审校建议:recheck 徽标与截断尾注 @提醒。"""

    def test_report_badge_chain_has_recheck(self):
        import report
        with open(report.__file__, encoding="utf-8") as f:
            src = f.read()
        i0 = src.index('if f.get("transferBaggage") == "direct":')
        seg = src[i0:i0 + 600]
        # badge 链补 recheck 分支(需转运:直挂筛选航线上达标失效
        # 的判据,图上看不出=图缺列表有)
        assert 'f.get("transferBaggage") == "recheck"' in seg, \
            "PNG badge 链缺 recheck(需转运)分支"
        assert "需转运" in seg, "recheck 徽标词面缺"

    def test_notifier_tail_note_mentions_at(self):
        import core.notifier as nt
        with open(nt.__file__, encoding="utf-8") as f:
            src = f.read()
        # 截断尾注补 @段丢失面:@手机号段结构性垫底,被截断时
        # 读者须知道高亮触达没了(钉钉 markdown 纯文本 @ 高亮在
        # 尾段被切即蒸发)
        assert "@提醒" in src, "发送端截断尾注未覆盖 @段丢失面"
