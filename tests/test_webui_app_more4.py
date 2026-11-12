# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_ctrip_date_selfcorrect.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import re
import sys


# ---- merged from tests/test_r1063_ctrip_date_selfcorrect.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "app_ctrip.py"),
                   encoding="utf-8").read()


def test_retry_exists_and_is_bounded():
    s = _src()
    assert "日期自校正" in s
    assert "for _try in range(2)" in s, "重试必须有上限，否则会一直点"
    assert "_weeks * _step" in s, "必须按差几周修正，不能写死一行"


def test_row_step_comes_from_calibration():
    s = _src()
    assert "CAL_CALIB" in s and "CAL_ROW_STEP" in s, \
        "行高必须来自标定常量（与 calendar_xy 同源），不许另抄一份"
    assert "CAL_CALIB_WIDTH" in s


def test_day_regex_reads_form_text():
    """表单里的日期形态是 `11月23日周一`，要能读出「23」。"""
    m = re.search(r"(\d{1,2})月(\d{1,2})日", "11月23日周一")
    assert m and int(m.group(2)) == 23
    # 差几周：(23-16)//7 == 1 行
    assert (23 - 16) // 7 == 1


def test_evidence_snapshot_is_written_on_failure():
    """失败必须留证据（否则只能靠猜）。"""
    s = _src()
    assert "app_date_fail_" in s
    assert "form.date=%r" in s or "form.date" in s
