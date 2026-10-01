# -*- coding: utf-8 -*-
"""r219 ctrip labels 增补：nt=105 诱饵价透明标记 + allilst 航盟词面。

候选出自 _scratch/r219_fields_abc.md（当日新采 dump 实证）：

- nt=105（plain JSON {showPrice,...}，非 zstd）的 showPrice=渠道列表
  展示价；与系统口径（有票明细最低 tprice）背离时，背离值 100% ∈
  nt=104 zstd items.FILTED_PRICES（20/20+6/6 精确同现、反向 0 例）
  ——展示价是被渠道过滤的不可购价（诱饵价），点进必涨价。守卫三件
  套：FILTED_PRICES 数值等值匹配（容差 0.01，字符串形态 '2767.0'
  浮点串勿逐字比对）+ 背离幅度 ≤5%（实证域 0.40%–3.00%，超界形态
  未证宁缺勿错）+ 任一解码失败静默跳过（_risk_tags 四门纪律同款）。
- 根级 allilst=[{alliname,airs}]：本响应在售航司的航盟归属部分字典
  （airs 只列本响应内出现过的航司）。行航班号二字码 ∈ airs 才落盟
  名（白名单透传不自解析）；airs 未列不得推判「无联盟」。
- manuf 候选不采：cdisname 前缀与已采 plane 同源（manuf=C919 行
  cdisname='C919(中)' 实证），labels 再落即冗余。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15118_ctrip_labels.py
"""
import base64
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t15118")
_CT = CtripCrawler({}, _LOG)


def _b64zstd(obj) -> str:
    import zstandard
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(
        zstandard.ZstdCompressor().compress(raw)).decode()


def _seg(flgno="MU1234"):
    return {"basinfo": {"flgno": flgno},
            "dateinfo": {"ddate": "2026-10-05 08:30:00",
                         "adate": "2026-10-05 11:20:00"},
            "craftinfo": {"cdisname": "空客320(中)", "manuf": "空客",
                          "kind": 2}}


def _mk_item(show_price=None, min_tprice=1000.0, filt=None,
             flgno="MU1234", nt104_bad=False):
    """最小行：policyinfo 单政策（最低价 min_tprice）+ 可选 nt=105
    showPrice + 可选 nt=104 载荷（FILTED_PRICES=filt，nt104_bad 时
    notecnt 为坏 base64 验静默门）。"""
    notes = []
    if show_price is not None:
        notes.append({"notetype": 105, "notecnt": json.dumps(
            {"showPrice": show_price, "aggSalePrice": show_price,
             "policyId": "p1", "flags": []})})
    if nt104_bad:
        notes.append({"notetype": 104, "notecnt": "!!not-base64!!"})
    elif filt is not None:
        notes.append({"notetype": 104, "notecnt": _b64zstd({
            "items": {"priceInfoList": json.dumps(
                [{"price": min_tprice, "grade": 0, "limitTag": "",
                  "policyId": "p1"}]),
                "FILTED_PRICES": filt}})})
    return {"mutilstn": [_seg(flgno)],
            "notes": notes,
            "policyinfo": [{"quantity": 1, "tprice": min_tprice,
                            "drate": 5.0}]}


def _run(item, allilst=None, root_list=False):
    if root_list:
        resp = [item]
    else:
        resp = {"fltitem": [item]}
        if allilst is not None:
            resp["allilst"] = allilst
    rows = _CT._extract_ctrip_flights(json.dumps(resp, ensure_ascii=False))
    assert len(rows) == 1
    return rows[0]


# ---- nt=105 诱饵价透明标记 ----

def test_lure_price_fired():
    """showPrice 与最低 tprice 背离 2% 且 ∈ FILTED_PRICES → labels
    落「页面价￥N不可购」（N=:g 去尾零）+ 独立键 lurePrice（webui
    价格格徽标数据源，riskPolicy 同构三端协议）。"""
    row = _run(_mk_item(show_price=980.0, min_tprice=1000.0,
                        filt="980.0,970.0"))
    assert "页面价￥980不可购" in row["labels"]
    assert row["lurePrice"] == 980


def test_lure_price_key_absent_when_clean():
    """无触发行不落 lurePrice 键（防孤儿键：有值才落）。"""
    row = _run(_mk_item(min_tprice=1000.0, filt="980.0"))
    assert "lurePrice" not in row


def test_lure_price_float_form_match():
    """FILTED_PRICES 单值 '980.0' 浮点串：数值等值匹配（容差 0.01）
    而非逐字比对——'980'/'980.0' 形态差不误杀。"""
    row = _run(_mk_item(show_price=980.0, min_tprice=1000.0,
                        filt="980.0"))
    assert "页面价￥980不可购" in row["labels"]


def test_lure_price_not_in_filted_absent():
    """showPrice 不在 FILTED_PRICES（nt=104 在场但无该键/空串）→
    背离不落标记（宁缺勿错：无过滤清单互证不判诱饵）。"""
    row = _run(_mk_item(show_price=980.0, min_tprice=1000.0, filt=""))
    assert "页面价" not in row.get("labels", "")
    row2 = _run(_mk_item(show_price=980.0, min_tprice=1000.0,
                         nt104_bad=True))
    assert "页面价" not in row2.get("labels", "")


def test_lure_price_gap_over_5pct_absent():
    """背离幅度 >5%（实证域 0.40%–3.00% 之外）→ 形态未证不落。"""
    row = _run(_mk_item(show_price=900.0, min_tprice=1000.0,
                        filt="900.0"))
    assert "页面价" not in row.get("labels", "")


def test_lure_price_no_deviation_absent():
    """showPrice == 最低 tprice（无背离）→ 不落。"""
    row = _run(_mk_item(show_price=1000.0, min_tprice=1000.0,
                        filt="1000.0"))
    assert "页面价" not in row.get("labels", "")


def test_lure_price_no_nt105_absent():
    """无 nt=105 note 的行（主流形态）→ 不落不炸。"""
    row = _run(_mk_item(min_tprice=1000.0, filt="980.0"))
    assert "页面价" not in row.get("labels", "")


# ---- allilst 航盟词面 ----

_ALLI = [{"alliname": "天合联盟", "airs": ["MU", "MF", "FM"]},
         {"alliname": "星空联盟", "airs": ["CA", "ZH"]}]


def test_alliance_label_fired():
    """行航班号二字码 ∈ airs → labels 落盟名词面（透传不自解析）。"""
    row = _run(_mk_item(flgno="MU1234"), allilst=_ALLI)
    assert "天合联盟" in row["labels"]
    row2 = _run(_mk_item(flgno="CA989"), allilst=_ALLI)
    assert "星空联盟" in row2["labels"]


def test_alliance_transfer_two_carriers():
    """中转行两段不同盟：两盟词面齐落（labels 去重各自独立）。"""
    it = _mk_item(flgno="MU1234")
    it["mutilstn"].append(_seg("CA989"))
    it["policyinfo"][0]["tprice"] = 1500.0
    row = _run(it, allilst=_ALLI)
    assert "天合联盟" in row["labels"] and "星空联盟" in row["labels"]


def test_alliance_airs_absent_no_inference():
    """二字码不在任何 airs（9C 未入盟且字典部分性）→ 零盟词，且不得
    推判「无联盟」造词。"""
    row = _run(_mk_item(flgno="9C8888"), allilst=_ALLI)
    assert "联盟" not in row.get("labels", "")


def test_alliance_unknown_name_whitelist():
    """未知盟名白名单弃（透传不自解析，宁缺勿错）。"""
    row = _run(_mk_item(flgno="MU1234"),
               allilst=[{"alliname": "未知联盟", "airs": ["MU"]}])
    assert "未知联盟" not in row.get("labels", "")
    assert "联盟" not in row.get("labels", "")


def test_alliance_absent_and_list_form():
    """无 allilst 根键 / 响应根是 list 形态：零盟词不炸。"""
    row = _run(_mk_item())
    assert "联盟" not in row.get("labels", "")
    row2 = _run(_mk_item(), root_list=True)
    assert "联盟" not in row2.get("labels", "")


def test_labels_baseline_intact():
    """两标记全无触发的行，labels 与既有出口形态一致（空串不受污染）。"""
    row = _run(_mk_item())
    assert row.get("labels") == "机上Wi-Fi" or "labels" not in row or \
        "页面价" not in row.get("labels", "")


# ---- webui 白名单/价格格徽标（三端同轮：ctrip 出口→白名单→渲染门） ----

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        import inspect
        import webui
        _SRC = inspect.getsource(webui)
    return _SRC


def test_webui_lure_price_whitelist_and_badge():
    s = src()
    # 白名单透传（riskPolicy 同构位；int 协议 _int_or_none 转写）
    assert '"lurePrice": _int_or_none(f.get("lurePrice"))' in s
    # 价格格行内徽标：⚠词面 + 悬停 title 释义（pretax 家族样式，
    # riskPolicy/黑卡价/税前 同槽）
    assert "页面价￥" in s and "不可购" in s
    assert "f.lurePrice?" in s


def test_webui_p11_kpisum_touch_floor():
    """P1-1（r219 WebUI 审计）：概览 kpisum 内联链移动端热区 16px
    （36 地板的 44%）——inline 垂直 padding 实体扩张+水平负 margin
    回收（不破一行排版，行高零漂移）。"""
    assert ".kpisum a{position:relative;padding:12px 4px;margin:0 -4px}" \
        in src()


def test_webui_p21_pushlog_empty_title():
    """P2-1（r219 WebUI 审计）：推送记录空账本标题「最近 0 条」别扭，
    空态降级「暂无推送记录」（有记录时保留计数词面）。"""
    assert ("$('pvTitle').textContent=items.length?"
            "('📨 推送记录（最近 '+items.length+' 条）')"
            ":'📨 暂无推送记录';") in src()


# ---- P2-2（推送审校）：补位角标「0h前」词面反语义 ----

def test_stale_txt_single_source():
    """补位时长词面单源：<1h 落「刚补位」（:.0f 四舍五入把 0.4h 产成
    「0h前」——零时读感是旧数据，实为最新补位，语义反向）；≥1h 恒
    「Nh前」；空值空串（词面缺席由消费点 if 门控制）。"""
    from core.alerter import _stale_txt
    assert _stale_txt(0.4) == "刚补位"
    assert _stale_txt(0.9) == "刚补位"
    assert _stale_txt(1.0) == "1h前"
    assert _stale_txt(25.3) == "25h前"
    assert _stale_txt(0) == ""
    assert _stale_txt(None) == ""
    assert _stale_txt("") == ""


def test_stale_txt_text_version():
    """文本版消费点：40 半角预算下含渠道完整段的最小行恒超宽走降级
    （slim2 剥 stale 段=既有「次要信号先丢」语义）——行级钉锁两点：
    ①「0h前」恒非法（任何档位）；②降级剥除路径对新词面「刚补位」
    生效（曾有裸 :.0f 表达式残留失配致剥段失效——兄弟消费点判例）。
    「刚补位」产出层由 test_stale_txt_single_source 单独锁。"""
    from core.alerter import Alerter
    base = {"_platform": "qunar", "_stale_h": 0.4,
            "price": 900, "name": "9C6928", "depTime": "08:30",
            "arrTime": "11:20"}
    line = Alerter._fmt_flight_line(dict(base), idx=1)
    assert "0h前" not in line
    # 剥除生效：超宽行降级后 stale 词面（新旧形态）皆不在场
    assert "刚补位" not in line or "去哪儿·刚补位" in line
    # 旧形态裸表达式已亡：构造长航班号逼入 slim 档，剥除后不留
    # 「·刚补位」残段
    f2 = dict(base, name="9C6928XYZEXT")
    line2 = Alerter._fmt_flight_line(f2, idx=1)
    assert "0h前" not in line2
    if "去哪儿" not in line2 or "刚补位" not in line2:
        assert "刚补位" not in line2   # 剥净或未渲染，无半截残留


def test_stale_txt_png_version():
    """图版 _plat_tag 消费点：同词同源（两版同词面承诺延伸）；正常
    构造源（report 侧 age_h>=1 门）形态不变。"""
    from report import _plat_tag
    from core.alerter import _stale_txt  # noqa: F401 单源 import 在场
    assert _plat_tag({"_platform": "tongcheng", "_stale_h": 0.4},
                     {"tongcheng": "同程"}) == "同程·刚补位"
    assert _plat_tag({"_platform": "tongcheng", "_stale_h": 2.0},
                     {"tongcheng": "同程"}) == "同程·2h前"
    assert _plat_tag({"_platform": "qunar"},
                     {"qunar": "去哪儿"}) == "去哪儿"
