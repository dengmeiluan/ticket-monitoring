# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v201_fields.py
- tests/test_v202_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import base64
import crawlers.ctrip as ctrip_mod
import json
import logging
import os
import sys
import zstandard

from crawlers.ctrip import CtripCrawler


# ---- merged from tests/test_v201_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t201")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_limited_age_bare_word():
    """nt=3 裸词 LimitedAge（worker 实证形态，逗号串携 LockPrice 同伴）：
    agePolicy=「限年龄」——最低价票的年龄购买资格正是 agePolicy 语义
    （行内 nt=20 缺席、零既有承载）。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3,
                             "notecnt": "LockPrice,LimitedAge"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=2457, ci=ci)]))
    assert r["agePolicy"] == "限年龄"


def test_ctrip_limited_age_no_duplicate_with_nt20():
    """与 nt=20 同语义 LimitedAgePolicy 并存（载体双形态同现）：防重
    拼接——agePolicy 仍「限年龄」，不出「限年龄·限年龄」。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3, "notecnt": "LimitedAge"}]}
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=2457, ci=ci,
                       fnotelst=[{"notetype": 20,
                                  "notecnt": "2457_LimitedAgePolicy"}])]))
    assert r["agePolicy"] == "限年龄"


# ---- merged from tests/test_v202_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t202")
_CT = CtripCrawler({}, _LOG)


def _mk_pid(free_kg, price, grade="Y", extra_tag=None):
    """按 dump 实证结构造 pid：trlinfos[].policies{price,grade,tag[]}。"""
    tag = [f"freeLuggageAmount_{free_kg}"]
    if extra_tag:
        tag += extra_tag
    payload = {"trlinfos": [
        {"policies": {"price": price, "grade": grade, "tag": tag}}]}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    return "__Zstd__|" + base64.b64encode(blob).decode("ascii")


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _item(pid, policies):
    return {"pid": pid,
            "mutilstn": [_ctrip_seg("2026-10-06 16:40:00",
                                    "2026-10-06 21:30:00")],
            "policyinfo": policies}


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_pid_free_baggage_matched():
    """pid 政策与最低价政策双门匹配（price+grade）：baggage=「免费托运
    20KG」——数字额词面与 qunar/tongcheng 同键同型。"""
    pid = _mk_pid(20, 2457, "Y")
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert r["baggage"] == "免费托运20KG"


def test_ctrip_pid_zero_baggage_wording():
    """freeLuggageAmount_0（春秋裸价）：「无免费托运」——最低价不含
    托运的比价失真硬证据，词面直述不落数字。"""
    pid = _mk_pid(0, 2457, "Y")
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert r["baggage"] == "无免费托运"


def test_ctrip_pid_value_15kg():
    """值域 15（10-05 dump 在场 2 例）：「免费托运15KG」。"""
    pid = _mk_pid(15, 2457, "Y")
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert r["baggage"] == "免费托运15KG"


def test_ctrip_pid_not_min_policy_no_baggage():
    """pid 政策非最低价（2500 vs 最低 2457）：不落——行李额随政策走，
    错配即把高价政策的额挂到低价行误导。"""
    pid = _mk_pid(20, 2500, "Y")
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci),
                         _ctrip_policy(price=2500, ci=ci)]))
    assert "baggage" not in r


def test_ctrip_pid_grade_mismatch_no_baggage():
    """grade 与最低价政策 nt=2 字母不一致（G vs Y）：不落。"""
    pid = _mk_pid(20, 2457, "G")
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert "baggage" not in r


def test_ctrip_pid_corrupt_silent():
    """pid 损坏（非 base64/非 zstd）：静默不落、不炸爬虫、其余键照常。"""
    for bad in ("__Zstd__|!!!not-base64!!!",
                "__Zstd__|" + base64.b64encode(b"garbage").decode(),
                "plain-text-pid"):
        ci = {"cgrd": 0,
              "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
        r = _one(_item(bad, [_ctrip_policy(price=2457, ci=ci)]))
        assert "baggage" not in r
        assert r["price"] == 2457


def test_ctrip_pid_value_guard():
    """tag 值域守卫（0-50 整数）：freeLuggageAmount 负值/超界/非数字
    不落；checkinLuggageMaxAmount 键面不入本式——0 值行同现
    freeLuggageAmount_0，词面由后者承载。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    for kg in (-2, 99, "abc"):
        pid = _mk_pid(kg, 2457, "Y")
        r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
        assert "baggage" not in r
    # checkinLuggageMaxAmount_0 在场不产出第二行李词面；0 词面由
    # freeLuggageAmount_0 直述（「无免费托运」）
    pid = _mk_pid(0, 2457, "Y",
                  extra_tag=["checkinLuggageMaxAmount_0"])
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert r.get("baggage") == "无免费托运"


def test_ctrip_pid_no_cabin_letter_no_baggage():
    """最低价政策无 nt=2 舱位字母：配对门缺一半，不落（宁缺勿错）。"""
    pid = _mk_pid(20, 2457, "Y")
    r = _one(_item(pid, [_ctrip_policy(price=2457)]))
    assert "baggage" not in r


def test_ctrip_pid_dependency_missing_silent(monkeypatch):
    """zstd 依赖缺失（打包环境漏装守卫）：整体跳过不落、不炸爬虫。"""
    monkeypatch.setattr(ctrip_mod, "ZstdDecompressor", None)
    pid = _mk_pid(20, 2457, "Y")
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert "baggage" not in r
    assert r["price"] == 2457


def test_ctrip_pid_suppresses_freelug_label():
    """pid 精确额与 nt=31 FreeLuggage 旗标同现：baggage 承载后
    labels 不再出「含免费托运」观测词（同屏冗余，双门匹配的数字额
    更 precise）；pid 政策非最低价（baggage 不落）时观测词照旧。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    fn = [{"notetype": 31, "notecnt": "FreeLuggage"}]
    hit = _one(_item(_mk_pid(20, 2457, "Y"),
                     [_ctrip_policy(price=2457, ci=ci, fnotelst=fn)]))
    assert hit["baggage"] == "免费托运20KG"
    assert "含免费托运" not in hit.get("labels", "")
    miss = _one(_item(_mk_pid(20, 2500, "Y"),
                      [_ctrip_policy(price=2457, ci=ci, fnotelst=fn)]))
    assert "baggage" not in miss
    assert "含免费托运" in miss["labels"]


def test_ctrip_pid_malformed_containers_silent():
    """trlinfos/tag 真值不可迭代形态（渠道改版防御）：判型门挡住，
    不炸爬虫、不落行李额、其余键照常——`or []` 兜底对真值非 list
    无效（for 5 直接 TypeError 逃出解码静默区）。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    for bad in ({"trlinfos": 5},
                {"trlinfos": [{"policies": {"price": 2457,
                                            "grade": "Y", "tag": 3}}]}):
        blob = zstandard.ZstdCompressor().compress(
            json.dumps(bad).encode("utf-8"))
        pid = "__Zstd__|" + base64.b64encode(blob).decode("ascii")
        r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
        assert "baggage" not in r
        assert r["price"] == 2457


def test_ctrip_pid_corrupt_payload_not_json():
    """pid 前缀与 base64/zstd 全合法、解压内容非 JSON：解码静默区
    内 json.loads 失败→空表，不落不炸。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    blob = zstandard.ZstdCompressor().compress(b"not-json")
    pid = "__Zstd__|" + base64.b64encode(blob).decode("ascii")
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert "baggage" not in r
    assert r["price"] == 2457


def test_ctrip_pid_policies_list_shape():
    """policies 为 list（调研实证 dict；渠道若改形态）：判型门跳过
    该政策行，宁缺勿错。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    payload = {"trlinfos": [{"policies": [
        {"price": 2457, "grade": "Y", "tag": ["freeLuggageAmount_20"]}]}]}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    pid = "__Zstd__|" + base64.b64encode(blob).decode("ascii")
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=ci)]))
    assert "baggage" not in r


def test_ctrip_pid_grade_lowercase_no_match():
    """grade 小写（渠道若改小写下发）：与 nt=2 舱位字母严格相等
    比较不命中，宁缺勿错静默不落。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    r = _one(_item(_mk_pid(20, 2457, "y"),
                   [_ctrip_policy(price=2457, ci=ci)]))
    assert "baggage" not in r
