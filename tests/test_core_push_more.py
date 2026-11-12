# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r255_push.py
- tests/test_r261_push.py
- tests/test_r309_push.py
- tests/test_r805ca_push_app_channel_names.py
- tests/test_v15114_push.py
- tests/test_v15128_push.py
- tests/test_v172_push.py
- tests/test_v173_push.py
- tests/test_v187_push.py
- tests/test_v220_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime as dt
import json
import logging
import logging as _lg
import os
import re
import sys

from core.alerter import Alerter, _bare_line_form, _demote_note, _disp_dw, _dw, _dw_bold, _fit_line, _near_txt, _pct_fallback_forms, kpi_tier_txt
from core.models import FlightPrice, Route


# ---- merged from tests/test_r255_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(path):
    return open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path),
        encoding="utf-8").read()


class TestMultiTableArrivalMax:
    def test_multi_meta4_carries_arrival_max(self):
        """P3-1：multi 版 meta4 与 legacy 版同构双键（layover_min +
        arrival_max）——空态词面按真实约束归因，不再恒落「次日 02:00」。
        搜索串缩进锁 multi 版（33 空格续行），防误配 legacy 同形串。"""
        src = _src("core/alerter.py")
        assert ('meta4 = {"layover_min": route.transfer_layover_min,\n'
                '                                 "arrival_max": '
                'route.transfer_arrival_max}' in src), \
            "multi 版 meta4 缺 arrival_max（与 legacy 版失同构）"

    def test_legacy_meta4_still_carries_both(self):
        """legacy 版既有双键形态保持（防同族回退）。"""
        src = _src("core/alerter.py")
        assert src.count('"arrival_max": route.transfer_arrival_max}') == 2


class TestDingtalkNetErrLedger:
    def test_network_exception_lands_in_ledger(self, monkeypatch, tmp_path):
        """P3-2：网络异常（httpx 抛错）轮落账 errcode=-2（未收到响应）
        ——控制台推送记录对这类轮不再失明。发送路径零改动：仍单发
        零重试，返回 False 由下轮心跳自然补。"""
        from core import notifier
        from core.notifier import DingTalkNotifier

        ledger = tmp_path / "push.jsonl"
        monkeypatch.setenv("PUSH_HISTORY_FILE", str(ledger))

        def boom(url, **kw):
            raise OSError("network unreachable")

        monkeypatch.setattr(notifier.httpx, "post", boom)
        dt = DingTalkNotifier("http://127.0.0.1:9/mock/robot",
                              logging.getLogger("t"))
        assert dt.send("t", "d") is False
        rows = [json.loads(l) for l in
                ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert rows, "网络异常轮应落账"
        r = rows[-1]
        assert r["ch"] == "dingtalk" and r["ok"] is False, r
        assert r.get("errcode") == -2, r


class TestTrendWindowLiteral:
    def test_no_spaced_window_literal(self):
        """「近 2.5 时」带空格漂移零残留（正文词面统一「近2.5时」，
        与日报 ⏱ 行既有钉同形）。"""
        assert "近 2.5 时" not in _src("report.py")


# ---- merged from tests/test_r261_push.py ----

_LOG = logging.getLogger("t261")


def _f(price, code, dpt, art, trans="", plat="qunar", dep="2026-10-06"):
    return {"price": price, "name": code, "code": code, "depTime": dpt,
            "arrTime": art, "depDate": dep, "arrDate": dep,
            "transCity": trans, "totalDuration": "8时45分",
            "_platform": plat}


def _plat(plat, rows, fc="URC", tc="SHA", d="2026-10-06"):
    """生产形态：每渠道一条 FlightPrice，extra=该渠道全部明细。"""
    return FlightPrice(platform=plat, from_city=fc, to_city=tc,
                       depart_date=d,
                       price=min(f["price"] for f in rows),
                       extra=json.dumps(rows, ensure_ascii=False))


def _route(**kw):
    base = dict(from_code="URC", from_name="乌鲁木齐", to_code="SHA",
                to_name="上海", dates=["2026-10-06"],
                alert_direct=1600, alert_transfer=1700)
    base.update(kw)
    return Route(**base)


def _dual_phantom_prices():
    """10-04 15:34 轮真实形态（毒价+同轮健康明细，值取自 DB 取证；
    渠道构成=行级池 5 渠道、中转明细 3 渠道——互抬穿透的前提是健康
    锚供给方在场，2 渠道互抬属纯统计无解的数学边界）。"""
    qunar = [_f(1034, "东航MU6108/MU9192", "14:30", "23:10", trans="兰州"),
             _f(2054, "天山GS7495/HO1236", "07:40", "09:50", trans="郑州"),
             _f(2244, "天山GS7495/HO1216", "07:40", "21:30", trans="郑州"),
             _f(1656, "上海FM9222", "09:05", "13:55"),
             _f(2344, "南航CZ6981", "18:30", "23:40")]
    ctrip = [_f(1100, "东航MU6108/MU9192", "14:30", "23:10", trans="兰州",
                plat="ctrip"),
             _f(2380, "乌鲁木齐UQ2545/HO1074", "10:15", "22:50",
                trans="郑州", plat="ctrip"),
             _f(2410, "春秋9C8866", "19:20", "23:55", plat="ctrip")]
    tuniu = [_f(2195, "东航MU6108/MU5138", "19:55", "09:10", trans="郑州",
                plat="tuniu"),
             _f(2360, "吉祥HO2214", "19:05", "23:55", plat="tuniu")]
    fliggy = [_f(2410, "南航CZ6981", "18:30", "23:40", plat="fliggy")]
    tc = [_f(2288, "东航MU6108/MU5152", "19:55", "10:45", trans="郑州",
             plat="tongcheng"),
          _f(2344, "南航CZ6981", "18:30", "23:40", plat="tongcheng")]
    return [_plat("qunar", qunar), _plat("ctrip", ctrip),
            _plat("tuniu", tuniu), _plat("fliggy", fliggy),
            _plat("tongcheng", tc)]


def test_dual_channel_phantom_blocked_by_mixed_pool():
    """毒价互抬穿透复现：分类池拦不住的 1034/1100，混合池补层必须拦。"""
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(), _dual_phantom_prices())
    assert len(secs) == 1
    s = secs[0]
    xp = [(p, int(v)) for p, v in s["xphans"]]
    assert ("qunar", 1034) in xp, f"qunar 毒价未被标记: {xp}"
    assert ("ctrip", 1100) in xp, f"ctrip 毒价未被标记: {xp}"
    # 达标/行情池均不见毒价（top_transfer=行情口径、pool=达标口径源）
    for pool_name in ("top_transfer", "pool", "all_flights"):
        got = {int(f["price"]) for f in s[pool_name]
               if f.get("price") is not None}
        assert 1034 not in got, f"{pool_name} 泄漏 qunar 毒价"
        assert 1100 not in got, f"{pool_name} 泄漏 ctrip 毒价"


def test_phantom_kept_out_of_platform_mins():
    """行级毒价不得进 platform_mins（图挂兜底「各渠道最低」文本行
    的次生泄漏面，与 webui _state 行级守卫同判据同输入）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(), _dual_phantom_prices())
    pm = secs[0]["platform_mins"]
    assert pm.get("qunar") != 1034, f"行级毒价泄漏 platform_mins: {pm}"
    assert pm.get("ctrip") != 1100, f"行级毒价泄漏 platform_mins: {pm}"
    # 健康行价不被误伤：剔除毒行后该渠道行价=剩余明细最低
    assert pm.get("qunar") == 1656 and pm.get("ctrip") == 2380, pm


def test_healthy_low_transfer_not_killed():
    """误杀面守护：真实低价中转（多渠道同水位，真降价案形态
    576-670 五渠道互证）不因混合池守卫陪葬。"""
    rows = [_f(590, "南航CZ6981", "18:30", "23:40"),
            _f(640, "东航MU8370", "09:00", "14:10", trans="西安")]
    prices = [_plat("qunar", rows),
              _plat("ctrip", [_f(600, "南航CZ6981", "18:30", "23:40",
                                 plat="ctrip"),
                              _f(670, "东航MU8370", "09:00", "14:10",
                                 trans="西安", plat="ctrip")]),
              _plat("tuniu", [_f(670, "南航CZ6981", "18:30", "23:40",
                                 plat="tuniu")])]
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(alert_direct=800, alert_transfer=800),
                             prices)
    s = secs[0]
    assert not s["xphans"], f"真降价被误拦: {s['xphans']}"
    assert min(int(f["price"]) for f in s["top_transfer"]) == 640


def test_thin_pool_mutual_lift_is_declared_boundary():
    """数学边界钉：健康锚供给不足（1 个健康渠道）时毒价对互抬
    纯统计不可分（两条毒价恰似真实双渠道价差），守卫不拦=诚实
    边界而非缺陷——锁死「不为个案引入假迭代/假守卫」的裁决。"""
    prices = [_plat("qunar", [_f(1034, "东航MU6108/MU9192", "14:30",
                                 "23:10", trans="兰州")]),
              _plat("ctrip", [_f(1100, "东航MU6108/MU9192", "14:30",
                                 "23:10", trans="兰州", plat="ctrip")]),
              _plat("tuniu", [_f(2300, "南航CZ6981", "18:30", "23:40",
                                 plat="tuniu")])]
    a = Alerter(_LOG, storage=None, digest=True)
    secs = a._build_sections(_route(), prices)
    assert secs[0]["xphans"] == [], (
        f"薄池互抬被「拦」=存在假守卫机制: {secs[0]['xphans']}")


def test_xchan_mark_call_count_constant():
    """性能钉：守卫调用次数每 section 恒定（分类池直飞/中转各 1 +
    混合池 1 = 3 次），随行数/渠道数恒定——曲线端曾有条件表达式
    退化 O(n²) 的先例，上界钉防同病。"""
    calls = {"n": 0}
    orig = Alerter._mark_xchan

    def _counting(rows):
        calls["n"] += 1
        return orig(rows)

    a = Alerter(_LOG, storage=None, digest=True)
    a._mark_xchan = _counting
    a._build_sections(_route(), _dual_phantom_prices())
    assert calls["n"] == 3, f"守卫调用次数漂移: {calls['n']}"


# ---- merged from tests/test_r309_push.py ----

# 最坏合法样本：5 位数线 × 5 位数价（超线差 5 位）× 🎯 点 + 加粗
_BASE_WIDE = "🎯 直飞 ￥10000　线￥39999　差￥29999"


def test_bare_line_form_strips_threshold_keeps_core():
    """地板档=剥「　线￥N」参照段：价格+差额核心判据与全角空格
    间隔保留，词面与末档可辨。"""
    bare = _bare_line_form(_BASE_WIDE)
    assert bare == "🎯 直飞 ￥10000　差￥29999"
    assert "线￥" not in bare


def test_bare_line_form_keeps_markdown_link_shell():
    """链接壳保留（LESSONS 三十§2：剥除档不剥链接——链接是该日期
    唯一文本跳转入口）。"""
    base = "[🎯 直飞 ￥10000](https://flights.example.com/x)　线￥39999　差￥29999"
    bare = _bare_line_form(base)
    assert bare.startswith("[🎯 直飞 ￥10000](https://flights.example.com/x)")
    assert bare.endswith("　差￥29999")


def test_pct_chain_tail_is_bare_form():
    """pct 有/无两分支的链尾都是剥线档（pct 空三档同形+地板档）。"""
    forms = _pct_fallback_forms(_BASE_WIDE, "3%")
    assert forms == [_BASE_WIDE + "（3%）", _BASE_WIDE + "·3%",
                     _BASE_WIDE, "🎯 直飞 ￥10000　差￥29999"]
    forms_empty = _pct_fallback_forms(_BASE_WIDE, "")
    assert forms_empty[-1] == "🎯 直飞 ￥10000　差￥29999"


def test_extreme_band_chain_lands_on_bare_within_budget():
    """端到端：极限带全链超宽时 _fit_line 落地板档且预算内达标
    （恒达标律闭合；样本可达性用真实计宽自证，非手算）。"""
    forms = _pct_fallback_forms(_BASE_WIDE, "")
    assert _dw_bold(forms[0]) > 40, "样本须确实超宽（触发档可达性前提）"
    line = _fit_line(forms[0], fallbacks=forms[1:], bold=True)
    assert line == forms[-1]
    assert _dw(line) <= 40


def test_normal_band_chain_unchanged():
    """常规带（4 位数线）首档合规：新档零触发零回归。"""
    base = "🎯 直飞 ￥1760　线￥1900　低￥140"
    forms = _pct_fallback_forms(base, "")
    line = _fit_line(forms[0], fallbacks=forms[1:], bold=True)
    assert line == forms[0]          # 首档合规原样直出
    assert forms[-1] == "🎯 直飞 ￥1760　低￥140"   # 尾档形态仍正确


def test_kpi_block_mkt_branch_uses_bare_tail():
    """主链 mkt 分支内联链尾收进单源（防调用点内联回退——档序
    悄悄回退的温床判例，源码钉锁走 helper）。"""
    import inspect
    from core import alerter
    src = inspect.getsource(alerter.Alerter._digest_payload)
    assert src.count("_bare_line_form(") >= 1, (
        "mkt 分支内联 forms 链尾必须走 _bare_line_form 单源")


# ---- merged from tests/test_r805ca_push_app_channel_names.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _FakeN:
    def __init__(self):
        self.sent = []

    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        self.sent.append((t, d))
        return True


def _row(plat):
    f = {"price": 2500, "name": "国航CA847", "code": "国航CA847",
         "depTime": "02:25", "arrTime": "07:10", "depDate": "2026-11-16",
         "arrDate": "2026-11-16", "transCity": "", "crossDayDesc": "",
         "totalDuration": "5时", "_platform": plat}
    return FlightPrice(platform=plat, from_city="SHA", to_city="BKK",
                       depart_date="2026-11-16", price=2500,
                       extra=json.dumps([f], ensure_ascii=False))


def _digest_text(plat):
    a = Alerter(logging.getLogger("push-" + plat), notifier=_FakeN(),
                storage=None, digest=True, at_mobile="", storm_repeat=1,
                user="推送演练")
    r = Route(from_code="SHA", to_code="BKK", from_name="上海",
              to_name="曼谷", dates=["2026-11-16"],
              alert_direct=3000, alert_transfer=0)
    built = [(r, a._build_sections(r, [_row(plat)]))]
    pv = a._digest_payload(built, fresh=True, with_tables=False,
                           with_charts=False)
    return pv["title"] + "\n" + pv["desp"]


def test_app_channel_rows_render_chinese_names_in_digest():
    for plat, cn in (("app_qunar", "去哪儿 App"), ("app_zhixing", "智行 App")):
        body = _digest_text(plat)
        assert cn in body, "%s 的推送文案里没有中文名：%s" % (plat, body[:300])
        assert plat not in body, (
            "%s 的推送文案里露出了裸 id：%s" % (plat, body[:300]))


# ---- merged from tests/test_v15114_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_near_txt_half_midpoints_round_half_up():
    """x.5 中点半点向上：2.5→3、4.5→5（banker 偶数舍入分叉点）、
    1.5/3.5 形态钉（banker 恰为偶上不区分，防回归改型）。"""
    assert _near_txt(0.025) == "擦边3%"
    assert _near_txt(0.045) == "擦边5%"
    assert _near_txt(0.015) == "擦边2%"
    assert _near_txt(0.035) == "擦边4%"


def test_near_txt_low_boundary_kept():
    """低边界契约维持：≤0.5 恒「擦边不足1%」（恰 0.5 显式含边界，
    0.51 起出「擦边1%」）。"""
    assert _near_txt(0.005) == "擦边不足1%"
    assert _near_txt(0.0049) == "擦边不足1%"
    assert _near_txt(0.0051) == "擦边1%"
    assert _near_txt(0.006) == "擦边1%"


def test_kpi_tier_txt_consumes_half_up():
    """消费点 kpi_tier_txt 同语言：+2.5% 恰中点 →「擦边3%」。"""
    txt = kpi_tier_txt("直飞", 2050, 2000, False)
    assert "擦边3%" in txt


# ---- merged from tests/test_v15128_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TC_PATHO = "乌鲁木齐地窝堡国际机场中转楼T2"   # 病理 transCity（渠道外部字段）


def _mk_route(ad=1900, at=1700):
    return Route(from_code="SHA", to_code="URC", from_name="上海",
                 to_name="乌鲁木齐", dates=["2026-09-25"],
                 alert_direct=ad, alert_transfer=at)


def _mk_secs(direct_price, transfer_price=None, **tk):
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
        s["best_transfer"].update(tk)
    return [s]


def _desp_lines(secs, route=None):
    a = Alerter(_lg.getLogger("t"), storage=None)
    p = a._digest_payload([(route or _mk_route(), secs)],
                          fresh=False, with_tables=False)
    return [ln for ln in p["desp"].split("\n") if ln.strip()]


def test_kpi_l3_pathological_transcity_fits_40():
    """病理 transCity：行3 丢注循环删光 extras 后仍超 40——不得直出。
    r318 心跳轻量化随迁：行3 载体在全量小节（达标/回落轮），夹具改
    达标轮，钉面语义不变。"""
    lines = _desp_lines(_mk_secs(1950, 1780, transCity=_TC_PATHO,
                                 layoverT="23:59"),
                        route=_mk_route(2000, 1800))
    bad = [(round(_disp_dw(ln)), ln) for ln in lines if _disp_dw(ln) > 40]
    assert not bad, f"超 40 行直出: {bad}"


def test_kpi_l3_floor_keeps_judgment():
    """地板档不是删行：城市判据首段必须保留（防修复把行3 整行吞掉）。"""
    lines = _desp_lines(_mk_secs(1950, 1780, transCity=_TC_PATHO,
                                 layoverT="23:59"),
                        route=_mk_route(2000, 1800))
    assert any(ln.startswith("> 经") for ln in lines), lines


def test_kpi_l3_direct_baggage_combo_fits_40():
    """直挂词与病理 tc 同现（直挂词不在丢注循环 extras 删单里，循环
    删不动）：整行仍须恒达标。"""
    r = _mk_route(2000, 1800)
    r.transfer_baggage = "direct"
    lines = _desp_lines(_mk_secs(1950, 1780, transCity=_TC_PATHO,
                                 layoverT="23:59"), route=r)
    bad = [(round(_disp_dw(ln)), ln) for ln in lines if _disp_dw(ln) > 40]
    assert not bad, f"超 40 行直出: {bad}"


def test_kpi_l3_normal_transcity_unchanged():
    """现实词面（2-6 汉字）不触地板：行3 原样全信息输出。"""
    lines = _desp_lines(_mk_secs(1950, 1780, transCity="郑州",
                                 layoverT="2:50"),
                        route=_mk_route(2000, 1800))
    assert any(ln == "> 经郑州　停2:50" for ln in lines), lines


# ---- merged from tests/test_v172_push.py ----

_PRE_FIX = "- 携程 最低 "          # _dw=12：短渠道名前缀
# 超界探索形态：非生产渠道名（PLATFORM_CN 最长「去哪儿」
# pre=14），比生产更紧 2 半角的边界，方向保守不掩盖生产问题
_PRE_LONG = "- 乌鲁木齐 最低 "      # _dw=16：长渠道名前缀（预算更紧的形态）
_F_TRANS = {"price": 2270, "name": "山东SC8714", "depTime": "07:25",
            "arrTime": "19:15", "transCity": "山东", "layoverT": "2:15"}
_F_TRANS_LONG = {"price": 2315, "name": "新海航｜乌鲁木齐航空UQ2509",
                 "depTime": "06:55", "arrTime": "14:55",
                 "transCity": "乌鲁木齐"}
_F_DIRECT = {"price": 2310, "name": "春秋9C6928",
             "depTime": "19:05", "arrTime": "23:55"}


class TestFmtBriefBudgetV172:
    """_fmt_brief budget 参数：前缀进预算后整行不破 40。"""

    def test_trans_short_prefix_full_line_within_40(self):
        pre = _PRE_FIX
        brief = Alerter._fmt_brief(_F_TRANS, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_trans_long_name_long_prefix_within_40(self):
        pre = _PRE_LONG
        brief = Alerter._fmt_brief(_F_TRANS_LONG, budget=40 - _dw(pre))
        line = pre + brief
        assert _disp_dw(line) <= 40
        assert "￥2315" in line  # 地板档保价格核心判据（超长名让位）

    def test_direct_short_prefix_full_line_within_40(self):
        pre = _PRE_FIX
        brief = Alerter._fmt_brief(_F_DIRECT, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_default_budget_backward_compatible(self):
        """不带 budget 时行为=旧守卫（40 预算，brief 本体达标形态不变）。"""
        assert _disp_dw(Alerter._fmt_brief(_F_DIRECT)) <= 40
        # 无前缀场景（预算 40）中档时刻形态仍在：短名直飞本体 34 ≤40
        assert "19:05→23:55" in Alerter._fmt_brief(_F_DIRECT)


class TestChannelMarketLinesV172:
    """消费点整行守卫：_channel_market_lines 产出行全 ≤40。"""

    @staticmethod
    def _sections():
        return [{
            # tuniu 有全线价无合格明细（else 直出分支），其余走 tops 分支
            "plat_top3": {"ctrip": [dict(_F_TRANS)],
                          "qunar": [dict(_F_TRANS_LONG)],
                          "tongcheng": [dict(_F_DIRECT)]},
            "platform_mins": {"ctrip": 2270.0, "qunar": 2315.0,
                              "tongcheng": 2310.0, "tuniu": 2400.0},
            "seen_plats": ["ctrip", "qunar", "tongcheng", "tuniu"],
        }]

    def test_all_lines_within_40(self):
        al = Alerter.__new__(Alerter)  # 免 init：方法只消费类属性
        desp = al._channel_market_lines(self._sections())
        for ln in desp.split("\n"):
            if ln.startswith("- ") and "最低" in ln:
                assert _disp_dw(ln) <= 40, f"超宽行: w={_disp_dw(ln)} {ln}"

    def test_price_and_flight_kept_on_fallback(self):
        al = Alerter.__new__(Alerter)
        desp = al._channel_market_lines(self._sections())
        # 价格核心判据三渠道恒在；短名航班号预算内保留，
        # 超长名（UQ2509 行）落地板档让位价格
        assert "￥2270" in desp and "SC8714" in desp
        assert "￥2315" in desp
        assert "￥2310" in desp and "9C6928" in desp


class TestSourceV172Push:
    """源码钉：budget 形态在位防回潮。"""

    def test_fmt_brief_signature_has_budget(self):
        import inspect
        sig = inspect.signature(Alerter._fmt_brief)
        assert "budget" in sig.parameters, \
            "_fmt_brief 缺 budget 参数（前缀超宽案回潮）"
        assert sig.parameters["budget"].default == 40

    def test_consumer_passes_prefix_deducted_budget(self):
        import core.alerter as _m
        with open(_m.__file__, encoding="utf-8") as f:
            src = f.read()
        # goal 轮 P3-2 模型变准改写：地板下限从常量 8 提为
        # _brief_floor(price)（价格词面实测宽与 8 取大——8 是国内
        # 5 位价标定值，r325 国际带 6 位价词面 9 半角后地板随词面）。
        # 锁关键结构不锁排版（窗口钉对合法增厚过敏，卅一§3）
        assert '_brief_floor(best.get("price"))' in src, \
            "_channel_market_lines tops 分支未按前缀扣预算（整行恒超宽回潮；" \
            "地板随价格词面标定恒可落，_brief_floor 单源）"
        assert "40 - _dw(pre)" in src and "40 - _dw(_mpre)" in src, \
            "两分支前缀扣减形态在位（tops/合并行）"
        assert "budget=max(8," not in src, \
            "常量 8 地板退役禁复活（标定值非常量律）"


# ---- merged from tests/test_v173_push.py ----

_PRE = "- 携程 最低 "  # _dw=12：消费点前缀（v172 同源形态）
# 中转跨天（flightnorm 归一化词面 crossDayDesc="+1天"）
_F_TRANS_CROSS = {"price": 2280, "name": "南航CZ6949", "transCity": "兰州",
                  "layoverT": "6:45", "depTime": "09:55", "arrTime": "00:25",
                  "crossDayDesc": "+1天"}
# 直飞跨天窄窗（arrTime 落 00:xx 次日凌晨）
_F_DIRECT_CROSS = {"price": 2310, "name": "春秋9C6928", "depTime": "23:05",
                   "arrTime": "01:15", "crossDayDesc": "+1天"}


class TestFmtBriefCrossBudgetV173:
    """跨天注 × budget：首档带注最宽形态下整行/档序/地板全链钉。"""

    def test_trans_cross_prefix_budget_full_line_within_40(self):
        pre = _PRE
        brief = Alerter._fmt_brief(_F_TRANS_CROSS, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_direct_cross_prefix_budget_full_line_within_40(self):
        pre = _PRE
        brief = Alerter._fmt_brief(_F_DIRECT_CROSS, budget=40 - _dw(pre))
        assert _disp_dw(pre + brief) <= 40

    def test_cross_note_stripped_at_mid_tier(self):
        """budget=37：首档带注（≈56）被挤掉，剥注中档（r220 校准后
        w=37）入选——跨天注不进文本但时刻保留（剥注档序不变；
        budget 随校准模型取中档恰可入的档位，档序语义同旧）。"""
        brief = Alerter._fmt_brief(_F_TRANS_CROSS, budget=37)
        assert "→00:25" in brief
        assert "（+1天达）" not in brief
        assert _disp_dw(brief) <= 37

    def test_tight_budget_drops_time_keeps_type_and_price(self):
        """budget=28：中档（w=34）也超，落 fallback[1]——无注无时刻，
        保「类型+价格」核心判据。"""
        brief = Alerter._fmt_brief(_F_TRANS_CROSS, budget=28)
        assert "+1天" not in brief and "→00:25" not in brief
        assert "￥2280" in brief and "中转" in brief
        assert _disp_dw(brief) <= 28

    def test_floor_tier_price_only(self):
        """地板律执行级：budget=6（消费点 max(6,…) 地板）时输出恒
        「￥价格」——钉死「max 地板 × ￥价格 地板档」契约对
        （引入， m2 备案语义以此为准：末档无
        arrive 组件=跨天注整体消失，设计内）。"""
        for f in (_F_TRANS_CROSS, _F_DIRECT_CROSS):
            brief = Alerter._fmt_brief(f, budget=6)
            assert brief == f"￥{f['price']}", repr(brief)
            assert _disp_dw(brief) == 7   # r220 校准：￥2+4 数字×1.125

    def test_default_budget_backward_compatible_cross(self):
        """不带 budget（=40）：跨天形态 brief 本体 ≤40 且中档入选。"""
        brief = Alerter._fmt_brief(_F_TRANS_CROSS)
        assert _disp_dw(brief) <= 40
        assert "→00:25" in brief and "（+1天达）" not in brief


# ---- merged from tests/test_v187_push.py ----

class TestDemoteNote:
    """P2-1：降级说明行三档降级链。"""

    def test_dual_clause_demoted_fits_40(self):
        """双词条形态（demoted+hit_demoted）：55/40 超宽降级到等义
        压缩档（39/40），hit 丢失面语义不丢（只丢「判据」二字）。"""
        out = _demote_note(True, True)
        assert _dw(out) <= 40, f"降级说明行仍超宽：{_dw(out)} 半角"
        assert "命中行仅价格" in out, "降级丢 hit 丢失面语义"

    def test_single_clause_kept_intact(self):
        """单词条形态（仅 sec 降级）：37/40 合格保持全形态。"""
        out = _demote_note(True, False)
        assert out == "> ⚠️ 航线较多，仅列关键价，明细见总表"
        assert _dw(out) <= 40

    def test_floor_keeps_reconcile_semantics(self):
        """地板档恒含「明细见总表」对账语义（信息按重要性从前往后丢）。"""
        for a in (True, False):
            for b in (True, False):
                out = _demote_note(a, b)
                assert "明细见总表" in out, f"地板档丢对账语义：{out!r}"


class TestSectionTitle:
    """P3-1：小节标题本体宽度守卫。"""

    @staticmethod
    def _title(fn, tn, span, win):
        return Alerter._section_title(fn, tn, span, win)

    def test_normal_shape_unchanged(self):
        """常态（乌鲁木齐→上海 单日期+无时段窗）：与旧拼接逐字一致。"""
        out = self._title("乌鲁木齐", "上海", "10/05", "")
        assert out == "#### ✈️ 乌鲁木齐→上海 10/05\n\n"

    def test_dep_win_inline_and_sunk(self):
        """时段窗：整行 ≤38 内联（#### 加粗字模较计量模型约宽 2 半角，
        首档阈值留缓冲）；恰卡带与超宽下沉引用行（两分支保持）。"""
        out = self._title("沪", "穗", "10/05", "（8后出发）")
        assert out.startswith("#### ✈️ 沪→穗 10/05（8后出发）\n\n")
        out1 = self._title("乌鲁木齐", "上海", "10/05", "（8后出发）")
        assert out1 == "#### ✈️ 乌鲁木齐→上海 10/05\n\n> （8后出发）\n\n"
        long_win = "（20后–次日02前出发）"
        out2 = self._title("乌鲁木齐", "上海", "10/05", long_win)
        assert out2 == (f"#### ✈️ 乌鲁木齐→上海 10/05\n\n> {long_win}\n\n")

    def test_overlong_city_sinks_date_span(self):
        """标题本体超宽（长自定义城市名）：日期段下沉、标题行 ≤40。
        （样本 5 字名：本体 30 可保、本体+日期 42 破 40——下沉日期
        后达标；更极端的城市名自身超出标题承载，不属日期下沉面。）"""
        out = self._title("超长出发名", "超长到达名",
                          "10/05-10/06", "")
        assert _dw(out.split("\n\n")[0]) <= 38, \
            f"标题行超宽：{_dw(out.splitlines()[0])} 半角"
        assert "10/05-10/06" in out, "日期段未保留（下沉丢失）"
        assert "> 10/05-10/06" in out, "日期段未下沉到引用行"

    def test_overlong_city_with_dep_win_merges_sunk_line(self):
        """本体超宽+时段窗同现：日期与时段合并同一条下沉引用行。"""
        out = self._title("超长出发名", "超长到达名",
                          "10/05", "（8后出发）")
        assert out.count("\n\n> ") == 1, "下沉引用行未合并（多段散落）"
        assert "10/05" in out and "（8后出发）" in out


class TestLegendAndOpsPins:
    """P3-3 图例正面衔接词条 + P3-7 ops 地板档。"""

    @staticmethod
    def _src(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_tbl_legend_green_layover_entry(self):
        """PNG 总表图例首行补「绿停时=衔接达标」正面词条。"""
        src = self._src("report.py")
        assert "绿停时=衔接达标" in src, \
            "总表图例缺衔接达标正面词条（正面绿无解码可误读为价格色）"

    def test_ops_floor_clamped_to_16(self):
        """ops 地板档 names[:16]+"(截)"=36 本体（r267 引用行前缀并入
        量纲：limit=40-_dw("> ")=38，地板档随限收紧；"> "+36=38
        =limit 恰满。r199 截断标记半角化，"(截)" _dw 实值 4 半角）。"""
        src = self._src("core/alerter.py")
        assert 'names[:16] + "(截)"' in src, \
            "ops 地板档未收口 16 字符（前缀并入量纲后 17 字档整行 42 超宽残留）"
        assert 'names[:17]' not in src, \
            "17 字旧档复活（引用行整行破 40）"


# ---- merged from tests/test_v220_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
