# -*- coding: utf-8 -*-
"""r1841：App 的两处闸门跳过记 `paced`（我方主动不发），不记 `blocked`。

`PATH_STATUS` 的注释自己写着：`paced` = 我方主动不发请求，不算被拒绝、
**不进爬取率分母**。但这两处闸门原先记 `blocked`，于是：

- 三率分母把它们算成"尝试"（实测同程 12h 有 27 条，把成功率压到 12.5%）；
- 健康页把它们读成"被拦"，看着像站点在拦我们，其实是我们在等自己。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                   encoding="utf-8").read()


def test_both_gates_record_paced():
    s = _src()
    for marker in ("App 自行退出后熔断中", "连续未取到结果，暂停中"):
        i = s.index(marker)
        seg = s[max(0, i - 400):i + 120]
        assert '"paced"' in seg, "%s 这条闸门仍然记 blocked" % marker
        assert '"blocked", date=d' not in seg, "%s 仍是 blocked" % marker


def test_gate_notes_say_we_did_not_send():
    s = _src()
    assert s.count("本轮未发请求") >= 2, "闸门记账没说明「本轮未发请求」"


def test_paced_is_a_known_status():
    s = _src()
    i = s.index("PATH_STATUS = (")
    seg = s[i:i + 500]
    assert '"paced"' in seg, "paced 不在 PATH_STATUS 里"


def test_streak_reason_still_documented():
    """r1561 的顾虑（不能记 timeout，否则熔断窗口不断续期）必须留着说明。"""
    s = _src()
    assert "_timeout_streak" in s
    assert "不断续期" in s or "反复回到 30" in s
