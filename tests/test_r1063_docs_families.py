# -*- coding: utf-8 -*-
"""r1063 T39：说明文档里那张「族速查表」必须与目录一致（防文档漂移）。

文档说假话是本项目最痛的一类缺陷。这张表最容易漂：加一条策略、改一个族名，
文档不会自己跟着变。所以用门禁把它钉在目录上——
**文档里的族、条数、成员 id 必须与 `core.strategy_contract.STRATEGIES` 完全一致**。
"""
import io
import os
import re

from core.strategy_contract import STRATEGIES

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "STRATEGY_CONTROL_PLANE.md")


def _doc_families():
    """从文档的族速查表里解出 `{族: [成员 id...]}`。"""
    txt = io.open(DOC, encoding="utf-8").read()
    i = txt.index("| 族 | 条数 |")
    j = txt.index("\n\n", i)
    out = {}
    for line in txt[i:j].splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("族",):
            continue
        fam, _n, _what, members = cells[0], cells[1], cells[2], cells[3]
        ids = [x.strip() for x in members.split(",") if x.strip()]
        out[fam] = ids
    return out


def test_doc_family_table_matches_the_catalog():
    cat = {}
    for s in STRATEGIES:
        cat.setdefault(s.family, []).append(s.id)
    doc = _doc_families()
    assert doc, "文档里没找到族速查表"
    assert set(doc) == set(cat), (
        "族的集合不一致：文档多 %s / 目录多 %s"
        % (sorted(set(doc) - set(cat)), sorted(set(cat) - set(doc))))
    for fam, ids in cat.items():
        assert doc[fam] == ids, (
            "族 %s 的成员不一致：\n文档 %s\n目录 %s" % (fam, doc[fam], ids))


def test_doc_counts_match():
    txt = io.open(DOC, encoding="utf-8").read()
    n_doc = len(_doc_families())
    n_cat = len({s.family for s in STRATEGIES})
    assert n_doc == n_cat
    assert ("%d 条" % len(STRATEGIES)) in txt, (
        "文档里没写当前策略总条数（%d）" % len(STRATEGIES))


def test_doc_lists_the_real_commands():
    txt = io.open(DOC, encoding="utf-8").read()
    for cmd in ("python -m core.strategy_contract --strict",
                "python -m core.fp_audit",
                "python -m core.cfg_snapshot"):
        assert cmd in txt, cmd


def test_doc_states_the_risk_boundaries():
    """行为型不自动解、换道有边界、调快＝风控代价——这三条必须写在文档里。"""
    txt = io.open(DOC, encoding="utf-8").read()
    for kw in ("风险边界", "行为分布", "每日上限", "风控代价"):
        assert kw in txt, kw


def test_doc_mentions_all_four_scopes():
    txt = io.open(DOC, encoding="utf-8").read()
    for sc in ("plat", "plat/dim", "plat/dim/path"):
        assert sc in txt, sc
    assert re.search(r"链路 → 维度 → 渠道", txt), "求值顺序没写"


# ---------------- 文案不许回潮（r1063 T41） ----------------

BANNED = ("交人工", "按性价比", "越算越像机器", "不必投入")


def test_no_restrictive_wording_in_any_doc():
    """用户明确要求：把限制这些设计的文案通通改掉。

    口径统一成「能力边界 + 范围决定」：图像型自动尝试，行为型不纳入自动尝试。
    「交人工 / 按性价比不投入 / 越算越像机器」这类**立场式禁令**不许再出现——
    它们既不是事实（点选是图像题，能自动做），也会误导接手的人。
    """
    import glob

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    for f in glob.glob(os.path.join(root, "docs", "*.md")):
        txt = io.open(f, encoding="utf-8").read()
        for w in BANNED:
            if w in txt:
                bad.append("%s：%s" % (os.path.basename(f), w))
    assert not bad, "文档里还有限制性表述：%s" % "、".join(bad)
