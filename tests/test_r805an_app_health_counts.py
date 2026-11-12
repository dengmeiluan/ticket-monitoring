# -*- coding: utf-8 -*-
"""r805an：App 渠道的出数日志必须计入健康度。

真实缺陷（2026-11-01 生产实测）：同一轮里
  · 账本 `fetch_paths` 记 `app_zhixing` 32 条 ok；
  · 日志 08:02 / 08:06 / 08:10 三次 `[app_zhixing] 抓取完成，得到 1 条记录`；
  · 而健康卡写着「抓取失败（原因待核对）」、`ok=0 tot=0`。

根因：`parse_health` 的成功判据只有 `_OK_PRICE`（`最低价 ￥xxx` /
`日历最低含税价 ￥xxx`）——那是**浏览器渠道**的出数措辞。App 渠道
（`crawlers/app_base.py`）出数只写「抓取完成，得到 N 条记录」，
两个正则都不命中，于是落进「本轮无任何抓取事件」分支 → `tot=0` → `fail`。

同一类缺陷此前已修过 5 处「只列/只认 5 家浏览器渠道」的名单
（`SRX_PLATS` 派生、`srxPlatKey`、`buildChips` 的 PK、KPI 的 PKEY、
`core/health_diag.PLATFORMS` 的默认值）；这是第 6 处。

判据（源层 + 真日志回归）：
  1. `抓取完成，得到 N 条`（N≥1）→ `s='ok'`、`detail≥1`；
  2. `抓取完成，得到 0 条` → `s='empty'`（真跑通了、当天没票），
     **不是** `fail`（记 fail 会让人去查不存在的登录/网络问题）；
  3. 用生产日志最后一段真跑一遍，App 两家的 `s` 必须是 ok 或 part，
     不得是 fail —— 这一条直接对着「面板说失败、账本说成功」修复。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_HEAD = ("2026-11-01 09:00:00 [INFO] ticket-monitor: "
         "===== 开始一轮扫描（1 用户 / 1 航线） =====\n")
_TAIL = ("2026-11-01 09:00:09 [INFO] ticket-monitor: "
         "===== 本轮扫描结束 =====\n")


def _round(log):
    from core.health import parse_health
    out = parse_health(log, hours=2400)
    rounds = out.get("rounds") or []
    assert rounds, "解析不出任何轮次，判据失去锚点"
    return rounds[-1]["plats"]


def test_app_rows_success_counts_as_ok():
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[app_zhixing] 抓取完成，得到 1 条记录\n"
           + "2026-11-01 09:00:06 [INFO] ticket-monitor: "
             "[app_qunar] 抓取完成，得到 3 条记录\n"
           + _TAIL)
    p = _round(log)
    for plat, rows in (("app_zhixing", 1), ("app_qunar", 3)):
        rp = p.get(plat) or {}
        assert rp.get("s") == "ok", (
            "%s 出了 %d 条却判成 %r（App 出数日志没被计入）"
            % (plat, rows, rp.get("s")))
        assert int(rp.get("detail") or 0) >= 1, (
            "%s 的 detail 计数为 0，明细证据丢了：%s" % (plat, rp))


def test_app_zero_rows_is_empty_not_failure():
    """「得到 0 条」是真跑通了、当天没票 —— 记 fail 会误导人重登/换网。"""
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[app_zhixing] 抓取完成，得到 0 条记录\n"
           + _TAIL)
    p = _round(log)
    rp = p.get("app_zhixing") or {}
    assert rp.get("s") == "empty", (
        "「得到 0 条」应记空结果，实测 %r：%s" % (rp.get("s"), rp))
    assert rp.get("note"), "空结果也要有说明，不能留空"


def test_app_navigation_failure_is_not_empty():
    """没完成导航/选城市，不能说成「本轮无票」。"""
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[app_qunar] 设出发城市失败：上海\n"
           + "2026-11-01 09:00:06 [INFO] ticket-monitor: "
             "[app_qunar] 抓取完成，得到 0 条记录\n"
           + _TAIL)
    rp = _round(log).get("app_qunar") or {}
    assert rp.get("s") == "fail", (
        "导航失败应记 fail，实测 %r：%s" % (rp.get("s"), rp))
    assert "导航失败" in str(rp.get("note") or ""), rp


def test_ok_round_does_not_keep_empty_note():
    """同轮既有明细成功又有空结果时，整轮不能写「本轮无票」。

    线上 19:56 qunar：国内 3 条明细 + 国际 3 条空，健康卡却挂
    「本轮无票（得到 0 条）」，把出数轮说成没票。
    """
    log = (_HEAD
           + "2026-11-01 09:00:05 [INFO] ticket-monitor: "
             "[qunar] 2026-11-16 最低价 ￥500（航班明细 10 条：直飞 10）\n"
           + "2026-11-01 09:00:06 [INFO] ticket-monitor: "
             "[qunar] 抓取完成，得到 0 条记录\n"
           + _TAIL)
    rp = _round(log).get("qunar") or {}
    assert rp.get("s") == "ok", rp
    assert "无票" not in str(rp.get("note") or ""), rp


def test_real_log_app_channels_are_not_reported_failed():
    """用生产日志最后一段真跑：App 两家不得被判 fail。

    这条是对「面板说失败、账本说成功」的**直接**回归——只要日志里
    真出现过「抓取完成，得到 N 条」，健康度就不能说它失败。
    """
    path = os.path.join(ROOT, "tests", "fixtures", "monitor_round_app.txt")
    assert os.path.isfile(path), "生产日志摘录缺失：%s" % path
    text = io.open(path, encoding="utf-8", errors="replace").read()
    lines = text.splitlines()
    idx = [i for i, l in enumerate(lines) if "开始一轮扫描" in l]
    assert idx, "摘录里没有轮次标记"
    from core.health import parse_health
    out = parse_health("\n".join(lines[idx[-1]:]), hours=2400)
    rounds = out.get("rounds") or []
    assert rounds, "最后一段日志解析不出轮次"
    plats = rounds[-1]["plats"]
    seg = "\n".join(lines[idx[-1]:])
    for plat in ("app_zhixing", "app_qunar"):
        tag = "[%s] 抓取完成，得到 " % plat
        zero = "[%s] 抓取完成，得到 0 条记录" % plat
        produced = (tag in seg) and (zero not in seg)
        rp = plats.get(plat) or {}
        if produced and rp.get("s") == "fail":
            raise AssertionError(
                "日志里 %s 明确出过数，健康度却判 fail：%s" % (plat, rp))
