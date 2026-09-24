"""推送回归钉：

 图挂兜底 TOP5 同价多渠道合并（_dedup_tie + 同价×N 角标 + 骨架
保渠道 + bare 硬保底——01:26 实发五行逐字全同，兜底容量曾反低于图版）；
 兜底组头带日期归属（多日期航线两块「直飞最优TOP5」同题头不可
分辨）；
 📈 日报邮件横幅副行剥行首 emoji（default 支， 只
覆盖了命中支）。
"""

import logging

from core.alerter import Alerter, Route, _dedup_tie, _disp_dw
from core.notifier import _banner_html


def _tie_rows(n=5, price=2200, code="9C6928"):
    plats = ("qunar", "ctrip", "fliggy", "tongcheng", "tuniu")[:n]
    return [dict(code=code, name=f"春秋{code}", depTime="19:05",
                 arrTime="23:55", price=price, _platform=p) for p in plats]


def _mk_alerter():
    log = logging.getLogger("t166push")
    return Alerter(log, notifier=None, storage=None, digest=True,
                   at_mobile="", storm_repeat=1, user="演练")


# ---- 同价多渠道合并 ----------

def test_dedup_tie_merges_same_price_multi_plat():
    """exact-tie 市场：5 渠道同航班同价合并为 1 行，_tie_n=5。"""
    merged = _dedup_tie(_tie_rows())
    assert len(merged) == 1 and merged[0]["_tie_n"] == 5


def test_dedup_tie_keeps_distinct_prices_and_flights():
    """不同价/不同航班不合并——合并后再截断，槽位让给不同航班。"""
    rows = _tie_rows(3) + _tie_rows(2, price=2400, code="9C7006")
    merged = _dedup_tie(rows)
    assert len(merged) == 2
    assert sorted(g["_tie_n"] for g in merged) == [2, 3]


def test_fmt_line_tie_badge_within_width():
    """合并行渲染「·同价×N」角标且不超宽（40 半角铁律）。"""
    line = Alerter._fmt_flight_line(_dedup_tie(_tie_rows())[0], 1, "")
    assert "同价×5" in line and line.count("9C6928") == 1
    assert _disp_dw(line) <= 40


def test_fmt_line_skeleton_keeps_platform():
    """超宽行降级到骨架档仍带渠道名（渠道维度曾与「当日达」同在骨架
    之外被先剥，exact-tie 行唯一区分信息丢失）。"""
    f = dict(code="CA1234", name="国航CA1234", depTime="08:00",
             arrTime="21:30", price=980, transCity="西安",
             layoverT="3时15分", totalDuration="10时30分",
             _platform="tongcheng")
    line = Alerter._fmt_flight_line(f, 2, "")
    assert "（同程）" in line and _disp_dw(line) <= 40


def test_fmt_line_bare_fallback_never_wide():
    """极端长航班号下骨架超宽，bare 硬保底仍 ≤40（_fit_line 全超
    原样吐末档，末档必须恒可容—— 守卫虚设教训）。"""
    f = dict(code="XX1234", name="超超超超超长名字航空XX1234共享",
             depTime="08:00", arrTime="11:00", price=1500,
             _platform="qunar")
    line = Alerter._fmt_flight_line(f, 1, "")
    assert _disp_dw(line) <= 40


# ---- 兜底组头带日期归属 ----------

def test_top3_blocks_group_head_carries_date():
    """多日期航线：len(sections)>1 时组头带「· MM/DD」，两块 TOP5
    可分辨；单日期不带（不占行宽预算）。"""
    a = _mk_alerter()
    rt = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
               alert_direct=1900, alert_transfer=1700)
    fl = dict(code="9C6928", name="春秋9C6928", depTime="19:05",
              arrTime="23:55", price=2200, _platform="qunar")
    sections = [{"date": "2026-10-05", "top_direct": [fl],
                 "top_transfer": [], "pool": []},
                {"date": "2026-10-06", "top_direct": [dict(fl)],
                 "top_transfer": [], "pool": []}]
    desp = a._top3_blocks(rt, sections)
    assert "直飞最优TOP5（线￥1900） · 10/05" in desp
    assert "直飞最优TOP5（线￥1900） · 10/06" in desp
    assert "中转最优TOP5 · 10/05" in desp
    # 单日期：不带日期段
    desp1 = a._top3_blocks(rt, [sections[0]])
    assert "直飞最优TOP5（线￥1900）\n" in desp1
    assert " · 10/05" not in desp1


# ---- 📈 日报横幅副行剥行首 emoji ----------

def test_banner_daily_default_strips_leading_emoji():
    """日报支（📈 不在档位键集走 default）：副行「📈 09/21 日报…」
    曾带 emoji 直出——统一形态与 ❌/🔔/🚨/↩️ 支一致。"""
    h = _banner_html("📈 机票监控｜09/21 日报 乌→上")
    body = h.split('opacity:.85">')[-1]
    assert not body.startswith("📈"), body
    assert "09/21 日报 乌→上" in body


def test_banner_hit_branch_unchanged():
    """命中支行为不回退（❌ 整段剥复读、🚨 异形留余段）。"""
    h1 = _banner_html("❌ 全部未达标｜最近 乌→上 10/05")
    assert "全部未达标" not in h1 and "最近 乌→上 10/05" in h1
    h2 = _banner_html("🚨 达标！乌→上 10/05 直飞￥930")
    assert "达标！乌→上 10/05 直飞￥930" in h2
