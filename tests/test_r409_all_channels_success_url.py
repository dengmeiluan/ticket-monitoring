# -*- coding: utf-8 -*-
"""r409：五家渠道的**成功**记录都要带 request_url。

重启后实测（14:19 起）：只有同程窗历与途牛带 URL，携程/飞猪/去哪儿
的成功记录仍是空串。一条"成功但不知道打了哪个地址"的账，等于把
可复现性丢了一半——出问题时无法回答"这次请求到底发了什么"。

本组守卫按渠道逐条钉住，防止某个渠道后来被改动时悄悄丢回去。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _read(fn):
    return open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()


def _block(src, anchor, before=0, after=400):
    i = src.index(anchor)
    return src[max(0, i - before):i + after]


def test_ctrip_pc_and_h5_record_url():
    s = _read("ctrip.py")
    for anchor in ('"PC", "ok", rows=len(flights)',
                   '"H5", "ok", rows=len(flights)'):
        assert "url=" in _block(s, anchor), anchor


def test_fliggy_intl_pc_records_url():
    s = _read("fliggy.py")
    assert "url=" in _block(s, '"PC", "ok" if rows'), "国际 PC 未记地址"


def test_fliggy_domestic_pc_records_url():
    s = _read("fliggy.py")
    assert "_last_list_url" in s, "国内 PC 未记录列表页地址"
    assert "url=_pg_url" in s, "国内 PC 未把地址传进 path_note"


def test_tuniu_both_success_paths_record_url():
    s = _read("tuniu.py")
    i1 = s.index('"国际列表接口"')
    assert "url=" in s[i1 - 400:i1], "途牛国际未记地址"
    i2 = s.index('"m.tuniu.com 列表接口"')
    assert "url=" in s[i2 - 400:i2], "途牛国内未记地址"


def test_qunar_intl_success_records_url():
    s = _read("qunar.py")
    i = s.index('"touch.qunar.com 国际列表"')
    assert "url=" in s[i - 500:i], "去哪儿国际未记地址"


def test_tongcheng_window_and_h5list_record_url():
    s = _read("tongcheng.py")
    i = s.index('self.path_note("窗历", "calendar"')
    assert "url=" in s[max(0, i - 700):i + 400]
    j = s.index('"H5列表", "ok"')
    assert "url=" in s[j:j + 400]
