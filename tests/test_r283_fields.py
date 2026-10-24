# -*- coding: utf-8 -*-
"""r283 数据层：ctrip 订座舱位码两字符形态收编（调研 C-49）。

classNoteList notetype=2 notecnt 两字符形态（R1×7 挂 9C 首段 3.7 折
深折行、B0×2 挂 AQ1733 直飞全价且 pid 政策 grade 同价 0.01 内精确
互证）被单字母守卫拒收——同结构槽（nt=2 订座舱位词面）单字符成员
（Y/B/M/H/J/C…）已按 cabinCode 真值在采，两字符是同族扩展；qunar
侧春秋子舱码 R2/R3/R4 已转正（r268，价位带互锁+跨渠道词面双证），
r210 更早实证 qunar R1 与春秋 9C8846 真实并现——与 qunar 撤伪案
（binfo 级 cabinDegree 段级折扣桶）的槽位级属不同结构，r258 C9
判词的两个地基均已失效。守卫放宽 [A-Z] → [A-Z][A-Z0-9]?，脏值
（数字开头/三字符/小写）维持拒收宁缺勿错。

配套渲染层：report 括注门 len==1 同轮放宽（qunar R2/R3 既有两字
符码同样被该门挡在「经济舱(R2)」括注之外——值域扩充的消费点等值
门同步律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r283_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("r283")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1610, ci=None):
    p = {"tprice": price, "quantity": 9, "drate": 3.7}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _extract(item):
    return _CT._extract_ctrip_flights(json.dumps([item]))[0]


# ---- 解析层：两字符收编 ----

def test_ctrip_cabin_code_b0_direct_two_char():
    """C-49 B0：nt=2 'B0'（AQ1733 直飞全价，pid grade 同价互证 2/2）
    → cabinCode='B0' 落值。"""
    dd, ad = "2027-02-13 21:10:00", "2027-02-14 02:35:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "B0"}]}
    row = _extract(_ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy(ci=ci)]))
    assert row.get("cabinCode") == "B0", row


def test_ctrip_cabin_code_r1_transfer_first_seg():
    """C-49 R1：中转行首段 nt=2 'R1'（9C8815/SC2251 3.7 折深折，与
    qunar 已转正的春秋子舱码同族同指纹）→ cabinCode='R1' 落值。"""
    dd1, ad1 = "2027-01-30 08:00:00", "2027-01-30 11:20:00"
    dd2, ad2 = "2027-01-30 13:30:00", "2027-01-30 16:40:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "R1"}]}
    row = _extract(_ctrip_item(
        [_ctrip_seg(dd1, ad1, "9C8815"), _ctrip_seg(dd2, ad2, "SC2251")],
        [_ctrip_policy(ci=ci)]))
    assert row.get("cabinCode") == "R1", row


def test_ctrip_cabin_code_single_char_family_unchanged():
    """单字母家族（Y/B/M/H…既有真值）行为零变化。"""
    dd, ad = "2027-02-13 21:10:00", "2027-02-14 02:35:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    row = _extract(_ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy(ci=ci)]))
    assert row.get("cabinCode") == "Y", row


def test_ctrip_cabin_code_dirty_values_still_rejected():
    """宁缺勿错边界维持：数字开头 '1B'、三字符 'ABC'、小写 'r1'、
    纯数字 '12' 全部拒收不落键。"""
    dd, ad = "2027-02-13 21:10:00", "2027-02-14 02:35:00"
    for dirty in ("1B", "ABC", "r1", "12"):
        ci = {"cgrd": 0,
              "classNoteList": [{"notetype": 2, "notecnt": dirty}]}
        row = _extract(_ctrip_item([_ctrip_seg(dd, ad)],
                                   [_ctrip_policy(ci=ci)]))
        assert "cabinCode" not in row, (dirty, row)


# ---- 渲染层：括注门同步放宽（值域扩充消费点等值门同步律）----

def test_report_cabin_annotation_two_char(monkeypatch, tmp_path):
    """PNG 总表次行括注「经济舱(B0)」：cabinCode 两字符形态与单字母
    同律出括注（退改等级之根）；qunar R2/R3 既有两字符码同样受益。"""
    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest_skip = __import__("pytest").skip
        pytest_skip("渲染烟测依赖 Windows 中文字体度量（CI 无雅黑）")
    import report as _rep
    seen = []
    _orig = _rep._fit_text

    def _spy(d, txt, *a, **kw):
        seen.append(str(txt))
        return _orig(d, txt, *a, **kw)

    monkeypatch.setattr(_rep, "_fit_text", _spy)
    f = {"price": 2550, "code": "AQ1733", "name": "北部湾航空AQ1733",
         "depTime": "21:10", "arrTime": "02:35", "depDate": "2027-02-13",
         "arrDate": "2027-02-14", "transCity": "", "crossDayDesc": "",
         "totalDuration": "5时25分", "cabin": "经济舱", "cabinCode": "B0",
         "plane": "", "planeSize": "", "lcc": False,
         "prate": "", "meal": "", "baggage": "", "discount": "",
         "fewTicket": "", "shareCarrier": "",
         "depTerminal": "", "arrTerminal": "",
         "depAirport": "", "arrAirport": "",
         "_platform": "ctrip", "stopover": False}
    out = str(tmp_path / "t.png")
    _rep.render_flights_table([("direct", [f])], "测试标题", out_path=out)
    assert any("经济舱(B0)" in s for s in seen), \
        f"两字符括注未出，实绘: {[s for s in seen if '经济舱' in s]}"
