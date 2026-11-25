# -*- coding: utf-8 -*-
"""能力边界轮不该被算成「渠道断供」。

实录（2026-11-25）：6 条航线全在 2027-02，App 渠道的日期视野只有 62 天
（`app_base.date_horizon_days`），于是 `app_ctrip` 每轮都记一条
`unsupported` 后早退。旧口径把它当零数据，连续 34 轮后推
「[渠道告警] 携程 App 连续 34 轮无数据」，正文还指向验证码/限流/改版
——排查方向完全错误，而且只要日期在视野外，告警**必然复现且永不恢复**。

这里钉住三件事：
  1. `_round_non_attempt()` 的判据（能力边界 / 让位 / 基础设施 → True；
     真的打了站点但失败 → False）；
  2. `_fail_evidence()` 不把 `unsupported` 当熔断证据；
  3. 主扫描的接线：`non_attempt` 必须在 `_ran_plats`/`ch_rows` 之前
     短路，否则告警仍会累计。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402


def _p(status, path="H5", **kw):
    rec = {"path": path, "status": status, "rows": 0}
    rec.update(kw)
    return rec


def test_unsupported_only_is_non_attempt():
    """App 日期超视野：唯一证据是 unsupported → 不是采集尝试。"""
    assert M._round_non_attempt([_p("unsupported", path="app-date")]) is True


def test_paced_only_is_non_attempt():
    """登录墙/停服让位：我方主动不发，同样不是断供。"""
    assert M._round_non_attempt([_p("paced", path="app-login")]) is True


def test_infra_path_is_non_attempt():
    """纯基础设施步骤（快照恢复/运行时）不说明站点态度。"""
    assert M._round_non_attempt([_p("error", path="snap-restore")]) is True


def test_real_failure_still_counts():
    """真打了站点却超时/被拦：必须照旧计入断供，不能被这条改动洗白。"""
    assert M._round_non_attempt([_p("timeout")]) is False
    assert M._round_non_attempt([_p("blocked")]) is False
    assert M._round_non_attempt([_p("empty")]) is False


def test_mixed_evidence_is_attempt():
    """一条通路说「不支持」、另一条真被拦 → 仍算真实采集（宁可少判）。"""
    assert M._round_non_attempt(
        [_p("unsupported", path="app-date"), _p("blocked")]) is False


def test_no_evidence_is_attempt():
    """没有账行（老代码/异常路径）不能默认成非尝试，否则会掩盖真断供。"""
    assert M._round_non_attempt([]) is False
    assert M._round_non_attempt(None) is False


def test_fail_evidence_drops_unsupported():
    """unsupported 不是对方的拒绝，不能喂给熔断归因。"""
    rows = [_p("unsupported", path="app-date")]
    assert M._fail_evidence(rows) == []
    assert M._fail_note(rows) == ""


def test_sweep_short_circuits_before_alert_counters():
    """接线：non_attempt 必须在 `_ran_plats.add` / `ch_rows` 之前 continue。

    这两处是「渠道连续零数据」告警与健康分母的唯一入口；顺序反了，
    能力边界轮就会重新变成断供样本（告警永真）。
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    i_meta = src.index('if _meta == "non_attempt":')
    i_ran = src.index("_ran_plats.add(_nm)", i_meta - 20000)
    i_rows = src.index("ch_rows[_nm] = ch_rows.get(_nm, 0) + len(prices)",
                       i_meta)
    assert i_meta < i_ran < i_rows, (i_meta, i_ran, i_rows)


def test_failover_path_skips_ch_rows_on_non_attempt():
    """换道回采同样要短路：`ch_rows[_app] += 0` 就足以让整轮零记录哨计数。

    原来换道分支只判 `paced`，能力边界轮会以「0 行」被写进 ch_rows，
    于是 `_channel_zero_sentinel` 每天照样刷「连续 N 轮零记录」。
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    i_meta2 = src.index('if _meta2 == "non_attempt":')
    i_rows2 = src.index("ch_rows[_app] = ch_rows.get(_app, 0) + len(_pr2",
                        i_meta2)
    assert i_meta2 < i_rows2, (i_meta2, i_rows2)
