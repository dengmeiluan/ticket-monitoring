# -*- coding: utf-8 -*-
"""r408：1999 升级成 login 时，必须撤掉本轮那条 soft_reject。

真实账（2026-10-27 10:39:22，同一 attempt_id）：
  #635 H5 soft_reject  「1999/8 间歇放行（单次，免登录冷却）」
  #636 H5 login        「1999/8 连续 2 次未放行（疑会话失效）」

同一次查询同时写着"单次、不用管"和"连续 2 次、请重登"——两条互斥结论
并列在账上，读者无法判断该信哪条，回溯时也无法确定当时到底发生过几次。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _src():
    return open(os.path.join(CRAWLERS, "qunar.py"), encoding="utf-8").read()


def test_upgrade_path_removes_soft_reject():
    """代码里升级分支必须显式剔除本轮的 soft_reject。"""
    s = _src()
    i = s.index('if _n >= 2:')
    block = s[i:i + 1400]
    assert '"soft_reject"' in block, block
    assert "_kept" in block and "self.paths =" in block, block


def test_upgrade_only_touches_same_date():
    """只撤本轮同日的那条，不碰历史与其他日期。"""
    s = _src()
    i = s.index('if _n >= 2:')
    block = s[i:i + 1400]
    assert 'p.get("date") == date' in block, block


def test_single_reject_still_emitted():
    """单次仍是 soft_reject（别为了去重把分层砍掉）。"""
    s = _src()
    assert "国际列表 1999/8 间歇放行（单次" in s
    assert "国际列表 1999/8 连续 %d 次" in s


def test_no_two_contradictory_rows_for_same_date():
    """行为级：升级后同日期只剩 login 一条。"""
    import logging
    from crawlers.qunar import QunarCrawler
    c = QunarCrawler({}, logging.getLogger("t_r408"))
    c.path_reset()
    c.path_note("H5", "soft_reject", date="2026-11-16",
                detail="国际列表 1999/8 间歇放行（单次，免登录冷却）")
    c.path_note("H5", "login", date="2026-11-16",
                detail="国际列表 1999/8 连续 2 次未放行（疑会话失效）")
    _kept = [p for p in c.paths[:-1]
             if not (p.get("path") == "H5" and p.get("date") == "2026-11-16"
                     and p.get("status") == "soft_reject")]
    c.paths = _kept + [c.paths[-1]]
    same = [p for p in c.paths if p.get("date") == "2026-11-16"]
    assert len(same) == 1, same
    assert same[0]["status"] == "login"
