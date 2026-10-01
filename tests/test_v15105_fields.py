# -*- coding: utf-8 -*-
"""ctrip aset 权益词面白名单收编（第 18 轮调研零新键收编候选）。

调研实证（_scratch/worker_v15104b_fields_a.md，10-05 新代 dump）：
- 「专属休息」（tcode=G_CSZZZSXX0617，2/544 tagarea）：中转专属
  休息室/休息区权益，休息≠住宿≠已采「中转免费休息」；HU7518/HO1080
  中转行唯一权益词，同行零既有出口，不收则该行服务承诺永久缺失。
- 「一次安检/免二次安检」（tcode=G_CSZZYCAJ0617，2/544 同行）：
  中转免二次安检便利承诺，同上唯一权益词。tagcnt 词面精确匹配
  零误杀、不惧 tcode 日期后缀换代（老客专享先例同律）。

收编形态：labels 白名单追加两词（零新键，消费端 webui/推送零改动）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15105_fields.py -q
"""
import base64
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zstandard  # noqa: E402

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t15105")
_CT = CtripCrawler({}, _LOG)


def _mk_pid(free_kg, price, grade="Y"):
    payload = {"trlinfos": [
        {"policies": {"price": price, "grade": grade,
                      "tag": [f"freeLuggageAmount_{free_kg}"]}}]}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    return "__Zstd__|" + base64.b64encode(blob).decode("ascii")


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _item(pid, policies, aset=None):
    it = {"pid": pid,
          "mutilstn": [_ctrip_seg("2026-10-06 16:40:00",
                                  "2026-10-06 21:30:00")],
          "policyinfo": policies}
    if aset is not None:
        it["aset"] = aset
    return it


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


_CI_Y = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}


def test_aset_exclusive_lounge_label():
    """aset「专属休息」（tcode=G_CSZZZSXX0617）→ labels 白名单：
    中转休息权益，既有白名单（住宿/中转免费休息）不覆盖。"""
    aset = [{"tagarea": [{"tcode": "G_CSZZZSXX0617",
                          "tagcnt": "专属休息"}]}]
    r = _one(_item(_mk_pid(20, 2457, "Y"),
                   [_ctrip_policy(ci=_CI_Y)], aset=aset))
    assert "专属休息" in r["labels"]


def test_aset_one_security_label():
    """aset「一次安检/免二次安检」（tcode=G_CSZZYCAJ0617）→ labels：
    dump 实证 tagcnt 为斜杠连写的单一词面（非两独立词）。"""
    aset = [{"tagarea": [{"tcode": "G_CSZZYCAJ0617",
                          "tagcnt": "一次安检/免二次安检"}]}]
    r = _one(_item(_mk_pid(20, 2457, "Y"),
                   [_ctrip_policy(ci=_CI_Y)], aset=aset))
    assert "一次安检/免二次安检" in r["labels"]


def test_aset_existing_words_unchanged():
    """既有白名单词不受本轮扩展扰动（同轮回归钉）。"""
    aset = [{"tagarea": [
        {"tcode": "G_HETXXS", "tagcnt": "中转免费休息"},
        {"tcode": "", "tagcnt": "宠物友好"}]}]
    r = _one(_item(_mk_pid(20, 2457, "Y"),
                   [_ctrip_policy(ci=_CI_Y)], aset=aset))
    assert "中转免费休息" in r["labels"]
    assert "宠物友好" in r["labels"]


def test_aset_marketing_churn_still_excluded():
    """营销/排序 churn 词面维持不采（同轮回归钉：收编不放宽边界）。"""
    aset = [{"tagarea": [
        {"tcode": "", "tagcnt": "中转高性价比"},
        {"tcode": "", "tagcnt": "优质中转·耗时短"},
        {"tcode": "", "tagcnt": "已优惠￥200·优惠后￥1999"}]}]
    r = _one(_item(_mk_pid(20, 2457, "Y"),
                   [_ctrip_policy(ci=_CI_Y)], aset=aset))
    assert "中转高性价比" not in (r.get("labels") or [])
    assert "优质中转·耗时短" not in (r.get("labels") or [])


# ---- 推送总表二段列双载 transGoDate（E 路审校 P2-1）：跨天中转
#      「二段哪天起飞」进图，与 webui「二段 MM-DD HH:MM 起飞」同词面 ----

def test_report_lay2_seg_carries_trans_go_date(monkeypatch, tmp_path):
    """二段行绘制文本含「二段 MM-DD HH:MM」：lay2dep 只有 HH:MM，
    跨天中转在推送图读不出二段日期（webui 明细已双载，图列对齐）。"""
    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("渲染烟测依赖 Windows 中文字体度量（CI 无雅黑）")
    import report as _rep
    seen = []
    _orig = _rep._fit_text

    def _spy(d, txt, *a, **kw):
        seen.append(str(txt))
        return _orig(d, txt, *a, **kw)

    monkeypatch.setattr(_rep, "_fit_text", _spy)
    f = {"price": 2472, "code": "FM9223/FM9224", "name": "上航FM9223",
         "depTime": "19:55", "arrTime": "01:25", "depDate": "2026-10-04",
         "arrDate": "2026-10-05", "transCity": "兰州", "crossDayDesc": "",
         "totalDuration": "5时30分", "cabin": "经济舱", "cabinCode": "Y",
         "plane": "波音737", "planeSize": "中型机", "lcc": False,
         "prate": "92", "meal": "", "baggage": "1件", "discount": "",
         "fewTicket": "", "shareCarrier": "", "depTerminal": "T3",
         "arrTerminal": "T2", "depAirport": "地窝堡", "arrAirport": "中川",
         "layoverT": "4时05分", "layoverM": 245, "lay2dep": "15:30",
         "transGoDate": "2026-10-05",
         "_platform": "qunar", "stopover": False}
    out = str(tmp_path / "t.png")
    _rep.render_flights_table([("direct", [f])], "测试标题", out_path=out)
    assert os.path.exists(out)
    # report 词面=「停N·二段MM-DD HH:MM」（紧凑无空格，与 webui
    # 「二段 MM-DD HH:MM 起飞」同信息不同媒质形态）
    assert any("二段10-05 15:30" in s for s in seen), \
        f"二段行未携带日期，实绘: {[s for s in seen if '二段' in s]}"


def test_report_lay2_seg_without_date_unchanged(monkeypatch, tmp_path):
    """无 transGoDate 行维持旧词面「二段 HH:MM」（同日中转不落键）。"""
    if not os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("渲染烟测依赖 Windows 中文字体度量（CI 无雅黑）")
    import report as _rep
    seen = []
    _orig = _rep._fit_text

    def _spy(d, txt, *a, **kw):
        seen.append(str(txt))
        return _orig(d, txt, *a, **kw)

    monkeypatch.setattr(_rep, "_fit_text", _spy)
    f = {"price": 2472, "code": "FM9223/FM9224", "name": "上航FM9223",
         "depTime": "19:55", "arrTime": "01:25", "depDate": "2026-10-04",
         "arrDate": "2026-10-05", "transCity": "兰州", "crossDayDesc": "",
         "totalDuration": "5时30分", "cabin": "经济舱", "cabinCode": "Y",
         "plane": "波音737", "planeSize": "中型机", "lcc": False,
         "prate": "92", "meal": "", "baggage": "1件", "discount": "",
         "fewTicket": "", "shareCarrier": "", "depTerminal": "T3",
         "arrTerminal": "T2", "depAirport": "地窝堡", "arrAirport": "中川",
         "layoverT": "2时05分", "layoverM": 125, "lay2dep": "21:00",
         "_platform": "qunar", "stopover": False}
    out = str(tmp_path / "t.png")
    _rep.render_flights_table([("direct", [f])], "测试标题", out_path=out)
    assert any("二段21:00" in s and "10-05" not in s for s in seen)
