# -*- coding: utf-8 -*-
"""r309 FG-1：fliggy 中转首段机型 labels 词面。

r309 渠道调研实锤（_scratch/r309_fields_B.md）：中转合并状态机只搬
code/name/shareCarrier/meal/楼号，首段机型/体量整段丢弃，合并行
plane=二段机型；两段机型跨段异值 28/43（65%），首段词面在 DB labels
0/11380 零出口——读者只看到二段机型还会误以为是全程机型。

落地形态（段位口径裁决备案）：主槽 plane 恒=二段机型（现状不动，
零存量语义漂移；tongcheng 中转行 plane=首段为渠道本态，跨渠道主槽
段位差不本轮收口）；首段机型以 labels 词面「首段XXX」消歧落地
（tongcheng share_txt「N段共享承运」先例：labels 既有渲染通道，
webui/CSV/report 三端零协议改动）；两段同值不落（主槽已代表全程，
零增量不采）；首段体量词不落（4/43 稀疏，型号异值已覆盖决策信息）。
"""
from crawlers.fliggy import FliggyCrawler


def _transfer_txt(seg1_plane: str, seg2_plane: str) -> str:
    """中转块文本（r265 _STOPOVER_LEG_TXT 同构在产形态）。"""
    lines = ["国航CA8347"]
    if seg1_plane:
        lines.append(seg1_plane)
    lines += ["深航ZH8993"]
    if seg2_plane:
        lines.append(seg2_plane)
    lines += [
        "10月15日 15:00", "10月15日 18:00",
        "10月15日 19:45", "10月16日 00:30",
        "乌鲁木齐天山国际机场", "兰州中转", "浦东国际机场T2",
        "¥822 2.0折", "订票",
    ]
    return "\n".join(lines)


def test_fliggy_seg_plane_label_when_legs_differ():
    """两段机型异值（dump 实证最高频对 321/320NEO）：labels 落
    「首段321」，主槽 plane 保持二段 320NEO 现状。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt("中型机 321", "中型机 320NEO"), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "CA8347/ZH8993"
    assert r["plane"] == "320NEO"          # 主槽=二段（现状不动）
    assert r["labels"] == "首段321"


def test_fliggy_seg_plane_label_same_value_not_set():
    """两段机型同值：主槽已代表全程，labels 不落（无值不落键族律）。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt("中型机 737", "中型机 737"), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["plane"] == "737"
    assert "labels" not in r


def test_fliggy_seg_plane_label_when_second_leg_missing():
    """二段机型行缺席（折叠异形块 2/45）：首段机型顶主槽
    （setdefault 零冲突）且 labels 带段位词面消歧，信息不静默丢。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt("中型机 737", None), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["plane"] == "737"
    assert r["labels"] == "首段737"


def test_fliggy_seg_plane_label_when_first_leg_missing():
    """首段机型行缺席：无可落词面，行照常入库（现状行为不变）。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt(None, "中型机 320NEO"), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["plane"] == "320NEO"
    assert "labels" not in r
