# -*- coding: utf-8 -*-
"""r805z：七渠道 × 七维度「声明 / 代码 / 账本」三方对照。

用户要求「**同时校准以前的渠道是否正确**」。此前每条维度都是零散核对，
没有一处能把三方摆在一起。本轮首次系统对照，查出一处**过度声明**：

    tuniu.calendar = "y"，但源码零日历通路、账本 48h 零 `日历` 记录，
    而其余四家各有独立日历通路名（ctrip 日历 / fliggy 日历 /
    tongcheng 窗历 / qunar 内嵌）。已改 n 并写明依据。

本门禁守的是**判据的形态**，不是某一格的具体值——否则以后改一次值就要
改测试。它检查三件事：

  1. 维度全集与渠道全集都有声明（遗漏比错值更难发现）；
  2. 声明 y 的**日历**维度，源码里必须能找到日历通路痕迹。这是本轮
     真查出问题的那条：`calendar` 是「独立日历通路」，列表接口顺带
     给的逐日价不算；
  3. `low_fare` 的取值必须与 `SPECIAL_CAPABILITY` 的源表一致——同一件
     事两张表给相反答案是本项目反复出现的漂移型缺陷。

**不检查** round_trip / multi_city 的「n 但有 ret_date 字样」：那三家
的 `ret_date` 是**显式 unsupported 分支**（r733/r736/r737 实测记录），
按关键字判会把「诚实的拒绝」误报成「隐瞒」。这类只能靠行为判据，
已在 `test_r741` / `test_r805n` 覆盖。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.channels import (APP_CHANNELS, BROWSER_CHANNELS,
                           CHANNEL_DIMENSIONS, DIMENSIONS)  # noqa: E402

ALL_PLATS = tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)


def test_every_channel_declares_every_dimension():
    for p in ALL_PLATS:
        row = CHANNEL_DIMENSIONS.get(p)
        assert row is not None, "%s 没有任何维度声明" % p
        missing = [d for d in DIMENSIONS if d not in row]
        assert not missing, "%s 缺这些维度：%s" % (p, missing)
        for d in DIMENSIONS:
            assert row[d] in ("y", "n", ""), (p, d, row[d])


def test_calendar_y_requires_a_real_calendar_path():
    """声明 calendar=y 的渠道，源码里必须真有日历通路。

    判据用**通路特有**的标记，不是随便一个 `calendar` 字样：
      * ctrip   —— `_fetch_intl_calendar` / calendar 端点
      * fliggy  —— `cheapestCalendar`
      * tongcheng —— `ts/calendar` 或 窗历
      * qunar   —— 内嵌低价日历 / lowFlight
    App 渠道走真机视图树，另有 `test_app_calendar_is_backed_by_a_real_path`
    专门守（**r700/r701 是往返门禁，不覆盖 calendar**——这句此前写错，
    导致 app_qunar 的 calendar=y 一直没人兜）。
    """
    marks = {
        "ctrip": ("calendar", "_fetch_intl_calendar"),
        "fliggy": ("cheapestCalendar",),
        "tongcheng": ("ts/calendar", "calendar_lowest", "窗历"),
        "qunar": ("lowFlight", "calendar"),
        "tuniu": ("fetch_tuniu_calendar", 'path_note("日历"'),
    }
    for p, needles in marks.items():
        if CHANNEL_DIMENSIONS[p].get("calendar") != "y":
            continue
        src = io.open(os.path.join(ROOT, "crawlers", p + ".py"),
                      encoding="utf-8").read()
        assert any(n in src for n in needles), (
            "%s 声明 calendar=y，但源码里找不到任何日历通路痕迹 %s"
            % (p, needles))


def test_app_calendar_is_backed_by_a_real_path():
    """App 渠道的 `calendar` 也必须由**真实日历通路**支撑。

    这条此前缺失：r805z 的日历判据只覆盖浏览器四家，注释还写着
    「App 由 r700/r701 覆盖」——**那两条是往返门禁，不覆盖 calendar**。
    于是 `app_qunar` 长期记着 calendar=y：它的 App 确实有日历页，但采集
    只把日历当「选日」用、随后进列表取明细，源码里 0 处
    `path_note("日历", ...)`，账本全历史也只有 `航班明细` 一种 entry_path
    ——按「calendar = 独立日历通路」的定义不该记 y（与途牛同型）。

    判据双向：
      · y → 源码必须真有 `path_note("日历"`（智行：4 处，账本 49 行）；
      · n → 源码必须确实没有（防止「其实接了却仍记 n」）。
    """
    import io as _io
    for plat in ("app_zhixing", "app_qunar"):
        src = _io.open(os.path.join(ROOT, "crawlers", plat + ".py"),
                       encoding="utf-8").read()
        has_cal_path = 'path_note("日历"' in src
        declared = CHANNEL_DIMENSIONS[plat].get("calendar")
        if has_cal_path:
            assert declared == "y", (
                "%s 源码里有独立日历通路（path_note(\"日历\")），"
                "声明却记 %r" % (plat, declared))
        else:
            assert declared != "y", (
                "%s 没有独立日历通路（源码 0 处 path_note(\"日历\")、"
                "账本无「日历」entry_path），calendar 不能记 y" % plat)
            assert (plat, "calendar") in _notes(), (
                "%s 的 calendar 记了 %r，必须给悬停说明讲清为什么"
                "（App 有日历页但只用于选日）" % (plat, declared))


def _notes():
    from core.channels import DIMENSION_NOTES
    return DIMENSION_NOTES


def test_tuniu_calendar_is_not_overclaimed():
    """途牛没有独立日历通路——这格必须是 n，且源码确实没有。

    反向也守住：万一以后真的接了日历，这条会红，提示把声明升回去。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    has_cal = any(n in src for n in ("calendar", "日历", "cheapestCalendar"))
    declared = CHANNEL_DIMENSIONS["tuniu"].get("calendar")
    if has_cal:
        assert declared == "y", (
            "途牛源码里已经出现日历通路，声明应升回 y（当前 %r）" % declared)
    else:
        assert declared == "n", (
            "途牛没有日历通路，calendar 不能记 %r（账本也只有 H5/API）"
            % declared)


def test_low_fare_matches_special_capability_table():
    """`low_fare` 与特价源表必须一致——同一件事两张表不能给相反答案。"""
    from core.specials import SPECIAL_CAPABILITY
    for p in ALL_PLATS:
        declared = CHANNEL_DIMENSIONS[p].get("low_fare")
        ent = SPECIAL_CAPABILITY.get(p) or {}
        has_src = bool(ent.get("sources"))
        if has_src:
            assert declared == "y", (
                "%s 在 SPECIAL_CAPABILITY 里有 %d 个源，矩阵却记 %r"
                % (p, len(ent["sources"]), declared))
        else:
            assert declared != "y", (
                "%s 在 SPECIAL_CAPABILITY 里没有源，矩阵却记 y" % p)
