# -*- coding: utf-8 -*-
"""r805aq：报告 PNG 里 App 渠道的**名字与列对齐**。

2026-11-01 渲染实证（`render_flights_table` 真跑，记录每次 `_fit_text`
的坐标）发现两个缺陷：

1. **裸 id**：渠道列印出 `app_zhixing` 而不是「智行 App」。根因——
   `report.py` 里 `plat_cn = Alerter.PLATFORM_CN` 直接取了**浏览器五家**
   那张表，而 App 的中文名在 `PLATFORM_CN_EXTRA`；`Alerter.plat_cn()`
   这个合并入口就在旁边，但没被用上。
2. **列错位**：渠道格原本写成 `elif name == "渠道" and dot:`——取不到颜色
   时不画圆点，文字落到 `x+10`；有圆点的行文字在 `x+24`。所以**只要某
   渠道没配色，它的名字就整体左移 14px**，与相邻行不对齐。

修法：名字改用合并表；圆点列**恒定预留**（有没有颜色都从 `x+24` 起排）。
判据三层：
  · `PLAT_DOT` 覆盖 `core.channels` 里的全部渠道 id；
  · 渲染后 App 行与浏览器行的渠道名 x 相同；
  · 渠道名是中文，不是裸 id；
  · **把 App 配色临时抽掉重渲染，x 必须不变**——保证对齐不依赖配色，
    将来再加渠道也不会重演一次左移。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _render_and_collect(tmpdir, rows):
    """渲染一次并把 `_fit_text` 的 (text, x, y) 全记下来。"""
    import report
    calls = []
    orig = report._fit_text

    def spy(d, text, x, y, max_w, base=15, fill=None, min_size=11,
            anchor="lm"):
        calls.append((str(text), round(float(x), 2), round(float(y), 2)))
        return orig(d, text, x, y, max_w, base=base, fill=fill,
                    min_size=min_size, anchor=anchor)

    report._fit_text = spy
    try:
        report.render_flights_table(
            rows, "probe", out_path=os.path.join(tmpdir, "probe.png"))
    finally:
        report._fit_text = orig
    return calls


def _mk(plat, no, price):
    return {"_platform": plat, "airline": "东航", "flightNo": no,
            "depTime": "08:00", "arrTime": "10:30", "fromCity": "上海",
            "toCity": "北京", "price": price, "direct": True,
            "totalDuration": "2h30m", "qual": True, "date": "2026-12-01"}


def _rows():
    return [("direct", [_mk("ctrip", "MU5101", 800),
                        _mk("app_zhixing", "CA1501", 820)])]


def test_report_dot_covers_every_channel():
    import report
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    for p in list(BROWSER_CHANNELS) + list(APP_CHANNELS):
        assert p in report.PLAT_DOT, (
            "%s 在报告里没有配色：圆点不画、渠道名会左移 14px" % p)


def test_app_channel_shows_chinese_name_aligned_with_browser(tmpdir):
    calls = _render_and_collect(str(tmpdir), _rows())
    xs = {}
    for t, x, _y in calls:
        if t in ("携程", "智行 App"):
            xs.setdefault(t, set()).add(x)
    assert "智行 App" in xs, (
        "报告里没有中文名「智行 App」——多半又印成裸 id 了。实际渠道列文字：%s"
        % [c[0] for c in calls if c[0] not in ("", "probe", "08:00",
                                              "—", "2h30m", "￥800",
                                              "￥820")][:8])
    assert "app_zhixing" not in [c[0] for c in calls], (
        "报告里出现裸 id `app_zhixing`，应显示「智行 App」")
    assert xs["携程"] == xs["智行 App"], (
        "App 行的渠道名与浏览器行不在同一 x：携程 %s vs 智行 %s"
        % (sorted(xs["携程"]), sorted(xs["智行 App"])))


def test_channel_text_alignment_does_not_depend_on_color(tmpdir):
    """抽掉 App 配色后，渠道名 x 必须保持不变。

    这条守的是**结构**：文字起点不能由「这渠道有没有配色」决定。
    没有这条，将来新增一个还没配色的渠道就会再左移一次 14px，
    而「有配色的渠道」看起来永远是对的。
    """
    import report
    saved = report.PLAT_DOT.pop("app_zhixing")
    try:
        calls = _render_and_collect(str(tmpdir), _rows())
    finally:
        report.PLAT_DOT["app_zhixing"] = saved
    xs = {}
    for t, x, _y in calls:
        if t in ("携程", "智行 App"):
            xs.setdefault(t, set()).add(x)
    assert xs.get("智行 App"), "抽掉配色后 App 渠道名没渲染出来"
    assert xs["携程"] == xs["智行 App"], (
        "没有配色时 App 行左移了：携程 %s vs 智行 %s（圆点列必须恒定预留）"
        % (sorted(xs["携程"]), sorted(xs["智行 App"])))
