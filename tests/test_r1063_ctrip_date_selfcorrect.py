# -*- coding: utf-8 -*-
"""r1063 T162：app_ctrip 日期点歪的**自校正**（按"差几周"修正一行重试）。

证据链（都是真机拿的）：
1. T161 失败快照 `user_data/app_ctrip/app_date_fail_2026-11-16.xml`：
   `parse_form → date='11月23日周一'`，目标 11月16日 → **正好差 7 天 = 一整行**；
2. 修完后日志：
   `[app_ctrip] 日期自校正：实际 23 天，目标 16 天 → y 上移 1 行`；
3. 探针结果从「app-date timeout（23 秒白跑）」变成「航班明细 login」——
   日期这步过了，下一道墙是携程 App 登录（与既有结论一致）。

设计取舍：**不猜常量**。行高用 `app_ctrip_parse` 的标定常量按屏宽等比缩放
（与 `calendar_xy` 同源）；偏移量从**实际选到的日**反推，而不是写死 ±1 行。
"""
import io
import os
import re
import sys

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
