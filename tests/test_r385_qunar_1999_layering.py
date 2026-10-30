# -*- coding: utf-8 -*-
"""r385 去哪儿国际 1999/8：间歇放行 vs 会话失效（证据分层）。

受控 A/B（2026-10-27 00:33–00:41，同一复制 profile、零人工介入、
6 轮 × SHA→LHR 2026-11-16）：

| 轮 | 时刻 | 路径 | 结果 |
|---|---|---|---|
| 1 | 00:33:43 | H5 | login（1999/8 未登录硬拒） |
| 2 | 00:35:12 | H5 | ok 1 条 |
| 3 | 00:36:46 | H5 | ok 1 条 |
| 4 | 00:38:12 | H5 | ok 1 条 |
| 5 | 00:39:45 | H5 | ok 1 条 |
| 6 | 00:41:13 | H5 | ok 1 条 |

**未重登、未 reset 就自愈** → 1999 单次不是会话失效（真登录墙不会
自己好）。旧口径把每次 1999 都判 login：置 login_suspect + 15 分钟
登录冷却 + 提示重登（48h 账本 60 次），把 1.5 分钟能好的事罚成 15
分钟不采。新口径：单次=soft_reject（不冷却、下轮重试），同航线连续
≥2 次才升 login；出数即清零。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

import logging  # noqa: E402

_LOG = logging.getLogger("t_r385")


def _src():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", "qunar.py"),
              encoding="utf-8") as f:
        return f.read()


def test_risk_signal_still_flags_login_family():
    """信号层不变：1999/2008/code 8 仍上报 login 族，由 fetch 层分层。"""
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":1999}}').status == "login"
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":2008},"code":8}').status == "login"
    # 真登录页文本仍是 login（不受 1999 分层影响）
    assert QunarCrawler._risk_signal(
        '{"msg":"请先登录后查看"}').status == "login"


def test_single_1999_is_soft_reject_not_login():
    src = _src()
    i = src.find('if risk == "login":')
    assert i > 0
    block = src[i:i + 2600]
    assert 'self.path_note("H5", "soft_reject"' in block, \
        "单次 1999 必须记 soft_reject（不冷却）"
    assert "免登录冷却" in block
    # 单次分支不得置 login_suspect
    seg = block[:block.find("else:")] if "else:" in block else ""
    assert "login_suspect = True" not in seg.split("if _n >= 2:")[0], seg


def test_two_consecutive_1999_escalate_to_login():
    src = _src()
    i = src.find('if risk == "login":')
    block = src[i:i + 2600]
    assert "_qn1999_streak" in block
    assert "if _n >= 2:" in block
    # 只有连续分支置 login_suspect
    j = block.find("if _n >= 2:")
    assert "login_suspect = True" in block[j:j + 400], block[j:j + 400]
    assert 'self.path_note("H5", "login"' in block[j:j + 500]


def test_success_clears_1999_streak():
    src = _src()
    i = src.find('detail="touch.qunar.com 国际列表"')
    assert i > 0, "国际成功落账点必须存在"
    block = src[max(0, i - 700):i]
    assert "_qn1999_streak.pop(" in block, "出数即清零连续计数"


def test_single_1999_schedules_one_same_round_retry():
    """A/B 显示 1.5 分钟自愈：单次必须在同轮短退避重试一次，且只一次。"""
    src = _src()
    assert "INTL_1999_RETRY_S" in src
    i = src.find('if risk == "login":')
    block = src[i:i + 6000]
    assert "_qn1999_retried" in block and "_intl_list_once(" in block
    assert "INTL_1999_RETRY_S" in block
    # 重试拿到数必须撤掉刚才的 soft_reject 记账并按成功落账
    assert 'self.paths.pop()' in block
    assert "同轮重试后放行" in block


def test_same_round_retry_is_single_day_scoped():
    """同轮重试是单日单页，不得再次解析成"登录"或写第二份软拒。"""
    src = _src()
    i = src.find("def _intl_list_once")
    assert i > 0
    fn = src[i:i + 2200]
    assert "touchInterList" in fn and "_parse_intl_response" in fn
    assert "path_note" not in fn, "重试纯取数，记账由调用方按真实结果做"


def test_streak_state_is_instance_scoped():
    a = QunarCrawler({}, _LOG)
    b = QunarCrawler({}, _LOG)
    a._qn1999_streak["SHA|LHR|2026-11-16"] = 2
    assert b._qn1999_streak == {}, "计数必须实例内（不跨实例串味）"


def test_legacy_1999_login_rows_show_as_soft(tmp_path):
    """历史 1999 行写的是 login；复发账必须按证据改判 soft（r385 A/B）。

    否则面板持续挂"登录态失效（需人工）"，催用户做无效重登——而那条
    路同会话 1.5 分钟就自愈。
    """
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(4):
        st.save_fetch_path("qunar", "SHA", "LHR", "2026-11-16", "H5",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="q%d" % i)
    row = next(r for r in st.failure_recurrence(24, 3) if r["path"] == "H5")
    assert row["status"] == "soft_reject"
    assert row["kind"] == "soft"
    assert "1999" in (row["evidence"] or {}).get("note", "")


def test_real_login_wall_still_login(tmp_path):
    """真登录页证据（passport/请先登录）不得被 1999 改判波及。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(4):
        st.save_fetch_path("qunar", "SHA", "LHR", "2026-11-16", "H5",
                           "login", note="登录门（passport）",
                           attempt_id="p%d" % i)
    row = next(r for r in st.failure_recurrence(24, 3) if r["path"] == "H5")
    assert row["status"] == "login" and row["kind"] == "login"
