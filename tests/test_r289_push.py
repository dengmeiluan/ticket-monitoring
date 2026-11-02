"""r289 推送层四案（审校报告 _scratch/r289_push.md）：

P2-A 日报 ops 注词面与告警侧同源缩写（_route_short 单源）——全名
    形态恰超 0.5 半角逼入降级链病句「当轮无数据：(截)」（渠道名全
    灭，当前配置+DB 自然触发非推演）。
P2-B 日报图挂兜底补「同班比价」段（三十§3 能力对称第五案：告警
    兜底经 _top3_blocks 尾部 _cross_compare 保有，日报兜底无比价
    消费点——比价离群警示随图沉没）。
P3-A 「各渠道最低」兜底段同价合并（五渠道同价常态 5 行零增量复
    读——渠道维度无差异时合并单行零信息损失）。
P3-B _fmt_brief 中档跨天辨识注保留（档序律：跨天=决策级辨识信息
    最后丢；「当日达」冗余装饰随中档剥，跨天注不得陪葬）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r289_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw          # noqa: E402
from report import (_daily_market_fallback,         # noqa: E402
                    _daily_ops_notes)

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
