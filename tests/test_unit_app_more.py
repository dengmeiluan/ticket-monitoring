# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1841_app_gate_paced.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os


# ---- merged from tests/test_r1841_app_gate_paced.py ----

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
