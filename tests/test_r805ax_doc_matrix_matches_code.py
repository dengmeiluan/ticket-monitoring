# -*- coding: utf-8 -*-
"""r805ax：手抄进文档的 7×7 矩阵必须与 CHANNEL_DIMENSIONS 逐格相等。

两份 HANDOFF 都把这个矩阵**抄**一遍给接手的人看（「谁支持往返、谁只有
日历」全靠它）。抄写不跟代码走就会撒谎：本轮校准发现四处同时漂了——

    同程 round_trip      代码 n（TT=RT/AD 只认站点自己的签名）  文档 y
    途牛 calendar        代码 n（没有独立日历通路）             文档 y
    去哪儿 App calendar  代码 n（日历页只用于选日）             文档 y
    智行 App low_fare    代码 y（r732 已接逐天特价）            文档 ""

读者按文档办事会去找一条不存在的通路，或漏掉一条存在的。所以这里把文档里的
矩阵块当**数据**解析，与源码逐格比对；改声明忘改文档 → 红。

判据认「每一格的值」，不认「文档里有没有这行字」——后者对过期的 `y` 一样绿
（这正是它漂了这么久没人发现的原因）。负控见本文件最后一条：翻掉一格必须红。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.alerter import Alerter
from core.channels import (APP_CHANNELS, CHANNEL_DIMENSIONS, DIMENSIONS,
                           app_alignment_gaps)

_CELL = {"y": "y", "n": "n", '""': "", "''": ""}


def _doc(name):
    return io.open(os.path.join(ROOT, "docs", name), encoding="utf-8").read()


def _parse_matrix(text):
    """`plat domestic=y intl=y …` 的行 → {plat: {dim: value}}。"""
    rows = {}
    for m in re.finditer(
            r"^([a-z_]+)[ \t]+([a-z_]+=\S+(?:[ \t]+[a-z_]+=\S+)*)[ \t]*$",
            text, re.M):
        plat = m.group(1)
        if plat not in CHANNEL_DIMENSIONS:
            continue
        cells = {}
        for pair in m.group(2).split():
            k, _, v = pair.partition("=")
            cells[k] = _CELL.get(v, v)
        if set(cells) != set(DIMENSIONS):
            continue  # 不是能力矩阵块（端面块之类），跳过
        rows[plat] = cells
    return rows


def _matrix_diffs(rows):
    """文档矩阵与代码矩阵的逐格差异；空列表＝一致。"""
    out = []
    for plat, want in CHANNEL_DIMENSIONS.items():
        got = rows.get(plat)
        if not got:
            out.append((plat, "*", "缺整行", ""))
            continue
        for d in DIMENSIONS:
            if got[d] != want[d]:
                out.append((plat, d, got[d], want[d]))
    return out


def _parse_gaps(text):
    m = re.search(r"^(?:gaps:|App 缺口：)(.+)$", text, re.M)
    assert m, "文档里找不到 App 缺口行（gaps: / App 缺口：）"
    out = {}
    for name, body in re.findall(r"(\w+)=\(([^)]*)\)", m.group(1)):
        out[name] = tuple(x.strip().strip("'\"") for x in body.split(",")
                          if x.strip())
    return out


def _gaps_diffs(got):
    want = {p: app_alignment_gaps(p) for p in APP_CHANNELS}
    return {p: (got.get(p), want[p]) for p in want if got.get(p) != want[p]}


def test_handoff_capability_matrix_block_matches_code():
    diffs = _matrix_diffs(_parse_matrix(_doc("HANDOFF_CAPABILITY_MATRIX.md")))
    assert not diffs, (
        "HANDOFF_CAPABILITY_MATRIX.md 的矩阵与 CHANNEL_DIMENSIONS 不一致"
        "（渠道, 维度, 文档值, 代码值）：%r" % (diffs,))


def test_handoff_full_session_block_matches_code():
    diffs = _matrix_diffs(_parse_matrix(_doc("HANDOFF_FULL_SESSION.md")))
    assert not diffs, (
        "HANDOFF_FULL_SESSION.md 的矩阵与 CHANNEL_DIMENSIONS 不一致"
        "（渠道, 维度, 文档值, 代码值）：%r" % (diffs,))


def test_handoff_gap_lines_match_alignment_gaps():
    for name in ("HANDOFF_CAPABILITY_MATRIX.md", "HANDOFF_FULL_SESSION.md"):
        bad = _gaps_diffs(_parse_gaps(_doc(name)))
        assert not bad, (
            "%s 的 App 缺口行过期（渠道: (文档, 代码)）：%r" % (name, bad))


def _parse_app_gap_table(text):
    """APP_CHANNELS.md 的「尚未对齐」两列表 → {plat: (dim, …)}。"""
    cn2id = {v: k for k, v in Alerter.PLATFORM_CN_EXTRA.items()}
    out = {}
    for label, cell in re.findall(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|",
                                  text, re.M):
        if label not in cn2id:
            continue
        out[cn2id[label]] = () if cell in ("—", "-", "") else tuple(
            re.findall(r"`([a-z_]+)`", cell))
    return out


def test_app_channels_gap_table_matches_code():
    """人读的「尚未对齐」表也得跟 `app_alignment_gaps` 一致。"""
    bad = _gaps_diffs(_parse_app_gap_table(_doc("APP_CHANNELS.md")))
    assert not bad, (
        "APP_CHANNELS.md 的 App 缺口表过期（渠道: (文档, 代码)）：%r" % (bad,))


def test_gate_catches_a_drifted_cell():
    """负控：真文档上翻掉一格 / 抹掉一个缺口，判据必须红。"""
    base = _doc("HANDOFF_CAPABILITY_MATRIX.md")
    mut = re.sub(r"^(app_qunar\s+.*low_fare=)y", r"\1n", base,
                 count=1, flags=re.M)
    assert mut != base, "负控没改动到文档（锚点失效，此门禁等于空转）"
    diffs = _matrix_diffs(_parse_matrix(mut))
    assert ("app_qunar", "low_fare", "n", "y") in diffs, (
        "翻掉一格后判据没抓到：%r" % (diffs,))

    gaps = _parse_gaps(base.replace("app_qunar=(multi_city)",
                                    "app_qunar=()"))
    assert _gaps_diffs(gaps), "抹掉缺口后判据没抓到"


def test_app_channels_summary_matches_connected_gaps():
    """摘要句与缺口表同源：表说已对齐，正文不能再写「还差」。

    2026-11-03 实测漂移：`APP_CHANNELS.md` 顶部还写「去哪儿 App 还差
    calendar/low_fare」，而同文件缺口表已是 `—`、矩阵两者均 y。
    """
    text = _doc("APP_CHANNELS.md")
    checks = (("app_qunar", "去哪儿 App", ("calendar", "low_fare")),)
    for plat, label, dims in checks:
        missing = set(app_alignment_gaps(plat))
        for dim in dims:
            if dim in missing:
                continue
            assert ("还差 `%s`" % dim) not in text, (
                "%s 的 %s 已接通（缺口表为 —），顶部摘要仍在说「还差」"
                % (label, dim))
