# -*- coding: utf-8 -*-
"""v1.5.85 渠道字段六项接入(三端同轮,样本取生产冻结 dump 真实行)。

调研基线(_scratch/r184_fields_*.md,dump 实证):
- ctrip prate 换补:现采 classinfor.prate 值域仅 {100,97},与 item 层
  aset[].tagarea[] tcode=InTimeTag 的 tagcnt(「准点率N%」)逐行交叉
  一致率仅 1.2%(80 行双源)——prate 是半占位伪源,InTimeTag 才是真源;
  有值即覆盖、旧源降兜底、脏词面弃(宁缺勿错)。
- ctrip seatTilt 新键:policyinfo[].classinfor[].seattilt,结构化真值
  非零 89.4%、值域 100~180(180=可平躺),0 视未报不落。
- ctrip 证件限制:tcode=CredentialsLimit_NewStyle 的 tagcnt,「限|」
  前缀=购买资格门槛(误购无法出行)采入 labels;「荐|部分证件价￥N」
  带价格随价 churn 不采(营销词纪律)。
- qunar 资格词置顶:PC _labels_of 按 name 顺序截前 3,资格词
  (「限N周岁」/「需实名认证」)会被「体验价」等营销词挤出槽位,
  误购高风险——资格词置顶,营销词让位(零新键品质修复)。
- tongcheng 免费托运:政策级 fs[ft=7].fcs 含 fc(经 data.cfs[ft=7]
  .fis[fd=「免费托运行李」] 动态解析,现网恒 "11")的最低价政策落
  行级 baggage=「免费托运」(flightnorm cabin_text 通路现成);映射
  缺席不落键防码漂移;每日 4 班低价行恰是缺行李「裸价」(调研实锤
  2160-3265 vs 4150-5321),不接则达标告警推的全是裸价。
- tongcheng plane 主源换 amn:afn 三成行产出「326/73M/73L」裸码值,
  amn(「空客A321-200」)100% 在场可读,afn 降兜底(零新键)。

运行:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v185_fields.py -q
"""

import copy
import json

from test_v185_fixtures import FIXTURES


def _ctrip(raw):
    import logging
    from crawlers.ctrip import CtripCrawler
    crawler = CtripCrawler({}, logging.getLogger("test"))
    fl = crawler._extract_ctrip_flights(
        json.dumps({"fltitem": [raw]}, ensure_ascii=False))
    assert fl, "夹具行被解析器整行丢弃(夹具结构与真实报文不符)"
    return fl[0]


def _qunar(raw):
    from crawlers.qunar import QunarCrawler
    env = {"ret": True, "data": {"flights": [raw]}}
    fl = QunarCrawler._parse_pc_flights(json.dumps(env), "2026-10-06")
    assert fl, "夹具行被解析器整行丢弃(夹具结构与真实报文不符)"
    return fl[0]


def _tc(block):
    from crawlers.tongcheng import TongchengCrawler
    fl = TongchengCrawler._extract_flights(
        json.dumps({"data": block}, ensure_ascii=False))
    return fl


class TestCtripPrateTrueSource:
    """C1 准点率真源换补:InTimeTag 覆盖 classinfor.prate 伪源。"""

    def test_prate_from_intime_tag_overrides_classinfor(self):
        f = _ctrip(FIXTURES["ctrip_intime"])
        # 夹具行 classinfor.prate=100.0(伪源恒值),InTimeTag=「准点率90%」
        # ——真源有值即覆盖(现实现输出 "100",交叉一致率仅 1.2%)
        assert f["prate"] == "90", \
            f"prate 未取 InTimeTag 真源: {f['prate']!r}"

    def test_prate_fallback_classinfor_when_no_intime(self):
        row = copy.deepcopy(FIXTURES["ctrip_intime"])
        for a in row.get("aset") or []:
            if isinstance(a, dict):
                a["tagarea"] = [t for t in (a.get("tagarea") or [])
                                if t.get("tcode") != "InTimeTag"]
        f = _ctrip(row)
        # 真源缺席 → 旧源(classinfor.prate/nt=1)兜底不回退
        assert f["prate"] == "100", f"旧源兜底失效: {f['prate']!r}"

    def test_prate_intime_dirty_text_ignored(self):
        row = copy.deepcopy(FIXTURES["ctrip_intime"])
        hit = False
        for a in row.get("aset") or []:
            for t in (a.get("tagarea") or []):
                if t.get("tcode") == "InTimeTag":
                    t["tagcnt"] = "准点率"   # 无数字脏词面
                    hit = True
        assert hit
        f = _ctrip(row)
        # 脏词面弃(宁缺勿错)→ 旧源兜底
        assert f["prate"] == "100", f"脏词面未弃: {f['prate']!r}"


class TestCtripSeatTilt:
    """C2 座椅倾斜角度新键(classinfor.seattilt,0 视未报)。"""

    def test_seat_tilt_from_best_ci(self):
        f = _ctrip(FIXTURES["ctrip_intime"])
        # best_ci=最低价政策 classinfor[0],seattilt=100
        assert f.get("seatTilt") == 100, \
            f"seatTilt 未落: {f.get('seatTilt')!r}"

    def test_seat_tilt_zero_not_set(self):
        row = copy.deepcopy(FIXTURES["ctrip_intime"])
        for pi in row.get("policyinfo") or []:
            for ci in (pi.get("classinfor") or []):
                ci["seattilt"] = 0
        f = _ctrip(row)
        # 0=未报不落(宁缺勿错,防与真值 0 语义混淆)
        assert not f.get("seatTilt"), f"seattilt=0 不应落键: {f.get('seatTilt')!r}"

    def test_seat_tilt_int_protocol(self):
        f = _ctrip(FIXTURES["ctrip_intime"])
        st = f.get("seatTilt")
        assert st is None or isinstance(st, int), \
            f"seatTilt 协议=int: {type(st).__name__}"


class TestCtripCredentialsLimit:
    """C3 证件限制标签:「限|」门槛采入 labels,「荐|价格」churn 不采。"""

    def test_limit_word_collected(self):
        row = copy.deepcopy(FIXTURES["ctrip_credlimit"])
        # dump 本期语料仅「荐|」形态(营销向),正例词面按真实
        # 「限|身份证享」形态构造(tcode 结构不变,仅测白名单边界)
        for a in row.get("aset") or []:
            for t in (a.get("tagarea") or []):
                if t.get("tcode") == "CredentialsLimit_NewStyle":
                    t["tagcnt"] = "限|身份证享"
        f = _ctrip(row)
        assert "限|身份证享" in (f.get("labels") or ""), \
            f"证件限制门槛词未入 labels: {f.get('labels')!r}"

    def test_recommend_price_word_not_collected(self):
        f = _ctrip(FIXTURES["ctrip_credlimit"])
        # 「荐|部分证件价￥2730」带价格随价 churn(营销词纪律)不采
        assert "部分证件价" not in (f.get("labels") or ""), \
            f"带价格营销词混入 labels: {f.get('labels')!r}"


class TestQunarQualifiedPinned:
    """Q1 资格词置顶:防营销词挤出 3 槽(误购高风险)。"""

    def test_single_qualified_label_passthrough(self):
        f = _qunar(FIXTURES["qunar_qualified"])
        assert "限16-23" in (f.get("labels") or ""), \
            f"资格词丢失: {f.get('labels')!r}"

    def test_qualified_pinned_over_marketing(self):
        row = copy.deepcopy(FIXTURES["qunar_qualified"])
        row["priceLabel"] = [
            {"id": 1, "name": "体验价", "note": []},
            {"id": 2, "name": "春秋绿翼会员专享丨超惠飞", "note": []},
            {"id": 3, "name": "取消延误免费改", "note": []},
            {"id": 4, "name": "限16-23(含)周岁的旅客预定", "note": []},
        ]
        f = _qunar(row)
        segs = (f.get("labels") or "").split("·")
        assert segs[0] == "限16-23(含)周岁的旅客预定", \
            f"资格词未置顶: {segs!r}"
        assert len(segs) <= 3, f"超 3 槽上限: {segs!r}"
        assert "取消延误免费改" not in segs, \
            f"末位标签未被资格词挤掉: {segs!r}"

    def test_realname_variant_pinned(self):
        row = copy.deepcopy(FIXTURES["qunar_qualified"])
        row["priceLabel"] = [
            {"id": 1, "name": "体验价", "note": []},
            {"id": 2, "name": "需包含实名认证乘机人购买", "note": []},
        ]
        f = _qunar(row)
        assert "需包含实名认证乘机人购买" in (f.get("labels") or ""), \
            f"实名认证资格词丢失: {f.get('labels')!r}"


class TestTongchengBaggage:
    """T1 政策级免费托运标记 → 行级 baggage(经 cfs 动态解析)。"""

    def test_baggage_from_min_policy_fs(self):
        fl = _tc({"fl": [FIXTURES["tc_bag_row"]], "cfs": FIXTURES["tc_cfs"]})
        assert len(fl) == 1
        # 最低价政策 fcs ⊇ fc=11 → 行级 baggage(flightnorm cabin_text
        # 通路现成,与 qunar baggage 同维度)
        assert fl[0].get("baggage") == "免费托运", \
            f"免费托运标记未落: {fl[0].get('baggage')!r}"

    def test_baggage_absent_when_fs_missing_fc(self):
        row = copy.deepcopy(FIXTURES["tc_bag_row"])
        for pol in row.get("lps") or []:
            for g in (pol.get("fs") or []):
                if isinstance(g, dict) and g.get("ft") == 7:
                    g["fcs"] = [c for c in (g.get("fcs") or [])
                                if str(c) != "11"]
        fl = _tc({"fl": [row], "cfs": FIXTURES["tc_cfs"]})
        # 最低价政策无 fc=11 → 不落(裸价行如实缺失,防虚标)
        assert not fl[0].get("baggage"), \
            f"无 fc=11 政策不应落 baggage: {fl[0].get('baggage')!r}"

    def test_baggage_silent_when_cfs_mapping_missing(self):
        cfs = copy.deepcopy(FIXTURES["tc_cfs"])
        for c in cfs or []:
            if isinstance(c, dict) and c.get("ft") == 7:
                c["fis"] = [fi for fi in (c.get("fis") or [])
                            if not (isinstance(fi, dict)
                                    and fi.get("fd") == "免费托运行李")]
        fl = _tc({"fl": [FIXTURES["tc_bag_row"]], "cfs": cfs})
        # 映射缺席不落键(宁缺勿错,防 fc 码漂移后误标)
        assert not fl[0].get("baggage"), \
            f"cfs 映射缺席仍落键: {fl[0].get('baggage')!r}"

    def test_baggage_reaches_cabin_text_via_normalize(self):
        from core.flightnorm import cabin_text, normalize
        fl = _tc({"fl": [FIXTURES["tc_bag_row"]], "cfs": FIXTURES["tc_cfs"]})
        f = normalize(fl[0], str(fl[0].get("depDate") or "2026-09-25"))
        assert "免费托运" in cabin_text(f), \
            f"baggage 未进 cabin_text 通路: {cabin_text(f)!r}"


class TestTongchengPlaneAmn:
    """T2 plane 主源换 amn(afn 三成行产出裸码值)。"""

    def test_plane_from_amn_primary(self):
        fl = _tc({"fl": [FIXTURES["tc_bag_row"]], "cfs": FIXTURES["tc_cfs"]})
        # 夹具行 amn=「空客A321-200」afn=「机型326」——现实现出「326」裸码
        assert fl[0].get("plane") == "空客A321-200", \
            f"plane 未取 amn 主源: {fl[0].get('plane')!r}"

    def test_plane_fallback_afn_when_amn_missing(self):
        row = copy.deepcopy(FIXTURES["tc_bag_row"])
        row.pop("amn", None)
        fl = _tc({"fl": [row], "cfs": FIXTURES["tc_cfs"]})
        assert fl[0].get("plane") == "326", \
            f"afn 兜底清洗改变: {fl[0].get('plane')!r}"


class TestQunarSamplesTrace:
    """观测立案:PC 单命中行落 samples 痕迹(区分未过合并与单采样
    退化——审计取证 id=12047 同价 4349 幻影尖刺无轨迹可查)。"""

    def test_single_hit_carries_samples_trace(self):
        from crawlers.qunar import QunarCrawler
        row = {"code": "MF2356", "depTime": "07:55", "price": 4349,
               "name": "厦门航空"}
        merged = QunarCrawler._merge_pc_samples([[row]])
        assert len(merged) == 1
        assert merged[0].get("samples") == [4349.0], \
            f"单命中行缺 samples 痕迹: {merged[0].get('samples')!r}"

    def test_multi_hit_median_kept(self):
        from crawlers.qunar import QunarCrawler
        rows = [{"code": "MF2356", "depTime": "07:55", "price": p,
                 "name": "厦门航空"} for p in (2934, 3154, 4349)]
        merged = QunarCrawler._merge_pc_samples([rows])
        assert merged[0]["price"] == 3154.0
        assert merged[0].get("samples") == [2934.0, 3154.0, 4349.0]


class TestCtripPrateMultiSeg:
    """Soldier P2-2:两段中转行 InTimeTag 各带时采首段(best_ci
    classinfor[0] 首段同律——last-wins 会让准点率口径漂到末段)。"""

    def test_intime_takes_first_segment(self):
        row = copy.deepcopy(FIXTURES["ctrip_intime"])
        tags = []
        for a in row.get("aset") or []:
            for t in (a.get("tagarea") or []):
                if t.get("tcode") == "InTimeTag":
                    tags.append(t)
        assert len(tags) >= 2, "夹具行非两段形态,无法测分叉"
        tags[0]["tagcnt"] = "准点率88%"
        tags[1]["tagcnt"] = "准点率60%"
        f = _ctrip(row)
        assert f["prate"] == "88", \
            f"InTimeTag 未采首段(last-wins 漂移): {f['prate']!r}"
