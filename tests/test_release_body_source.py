# -*- coding: utf-8 -*-
"""Release 正文源门禁：初版式正文不得再漂回 7 家旧文案。

背景：线上 v1.5.307 正文是 7 家/7×7/7×11；10 渠道 WIP 发布时若直接沿用，
Release 说明就与代码/矩阵不符（用户点名过）。`docs/RELEASE_BODY.md` 是
下一次发版的 canonical 正文源，本门禁把它钉在当前矩阵上。

每个用例都带负控：把正文改成对应的坏样本，验证判据会报错（门禁不空转）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channels import (CHANNEL_CN, CHANNEL_DIMENSIONS, CHANNEL_SURFACES,
                           DIMENSION_SCOPE, DIMENSIONS, channel_dims_payload)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BODY = os.path.join(ROOT, "docs", "RELEASE_BODY.md")


def _read():
    assert os.path.isfile(BODY), "缺 docs/RELEASE_BODY.md（发版正文源）"
    return io.open(BODY, encoding="utf-8").read()


def _count_errors(body):
    errs = []
    if "10 家渠道" not in body:
        errs.append("渠道数没写 10 家")
    if "10 渠道 × 7 维度" not in body:
        errs.append("能力矩阵计数不是 10 渠道 × 7 维度")
    if "10 家 × 11 轴" not in body:
        errs.append("质量轴计数不是 10 家 × 11 轴")
    for stale in ("7 家渠道", "7×7 能力矩阵", "7 家 × 11 轴",
                  "7 家渠道 × 7"):
        if stale in body:
            errs.append("残留旧计数：%s" % stale)
    return errs


def _name_errors(body):
    errs = []
    for plat, cn in CHANNEL_CN.items():
        if cn not in body:
            errs.append("正文没点名渠道：%s（%s）" % (cn, plat))
    for (plat, dim), scope in DIMENSION_SCOPE.items():
        if dim != "round_trip":
            continue
        if CHANNEL_CN[plat] not in body:
            errs.append("部分往返渠道没写进正文：%s" % CHANNEL_CN[plat])
        if scope not in body:
            errs.append("正文缺范围短标签 %r（%s）"
                        % (scope, CHANNEL_CN[plat]))
    return errs


def _matrix_rows(body):
    section = body.split("## 能力矩阵", 1)[-1].split("## 快速开始", 1)[0]
    rows = {}
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) >= 4 and cells[0] in CHANNEL_CN.values():
            rows[cells[0]] = cells
    return rows


def _surface_errors(body):
    errs = []
    rows = _matrix_rows(body)
    for plat, cn in CHANNEL_CN.items():
        cells = rows.get(cn)
        if not cells:
            errs.append("矩阵缺渠道行：%s" % cn)
            continue
        form, surface = cells[1], cells[2]
        if plat in CHANNEL_SURFACES:
            for key, label in (("pc", "PC"), ("h5", "H5")):
                v = CHANNEL_SURFACES[plat].get(key)
                if v == "y":
                    if label not in surface:
                        errs.append("%s 已接通 %s，但采集面没写：%r"
                                    % (cn, label, surface))
                elif v == "":
                    if label not in surface or not any(
                            k in surface for k in
                            ("未验证", "待验证", "受风控", "风控")):
                        errs.append(
                            "%s 的 %s 未验证/受风控，采集面必须点名并写原因：%r"
                            % (cn, label, surface))
                elif v == "n":
                    if label not in surface or not any(
                            k in surface for k in ("停服", "不支持", "无此")):
                        errs.append(
                            "%s 的 %s 已停服/无此能力，采集面必须写明：%r"
                            % (cn, label, surface))
        elif "App" not in form:
            errs.append("%s 是 App 渠道，形态列应写 App：%r" % (cn, form))
    return errs


def _rt_row_errors(body):
    errs = []
    rows = _matrix_rows(body)
    for plat, cn in CHANNEL_CN.items():
        cells = rows.get(cn)
        if not cells:
            continue
        rt = CHANNEL_DIMENSIONS[plat]["round_trip"]
        cell = cells[3]
        if rt == "y":
            scope = DIMENSION_SCOPE.get((plat, "round_trip"))
            if scope:
                if scope not in cell:
                    errs.append("%s 往返范围应写 %r，实际 %r"
                                % (cn, scope, cell))
            elif not ("国内" in cell and "国际" in cell):
                errs.append("%s 往返已全接通，范围应含国内与国际：%r"
                            % (cn, cell))
        elif not any(k in cell for k in ("未接", "未验证", "不支持", "无此")):
            errs.append("%s 往返未接通/未验证，范围列必须写明：%r"
                        % (cn, cell))
    return errs


def _multi_city_errors(body):
    errs = []
    if "多程" not in body:
        errs.append("正文没写多程")
    # 携程 PC 2 段已生产验证（矩阵 ✓ 仅 2 段），缺口程 2 段已实测，
    # 3+ 段未验；正文必须写清 scope，不能把「2 段已验证」写成「全段已支持」。
    if "已有 2 段生产整单行" not in body:
        errs.append("多程必须写明已有 2 段生产整单行")
    if "仅 2 段" not in body:
        errs.append("多程矩阵必须写明「仅 2 段」scope")
    if "缺口程 2 段已实测" not in body:
        errs.append("多程必须写明缺口程 2 段已实测（不得再写未验）")
    if "3+ 段" not in body and "3+段" not in body:
        errs.append("多程必须写明 3+ 段未验")
    if '`""`' not in body:
        errs.append("多程矩阵必须写未验证空值")
    matrix = body.split("## 能力矩阵", 1)[-1].split("## 快速开始", 1)[0]
    if "已支持" in matrix:
        errs.append("矩阵段落不得出现「多程已支持」类表述")
    return errs


def _placeholder_errors(body):
    errs = []
    for ph in ("{{VERSION}}", "{{SOURCE_SHA}}", "{{DATE}}",
               "{{TRACKED_TESTS}}", "{{TEST_COUNTS}}", "{{UI_COUNT}}",
               "{{UI_TOTAL}}", "{{ASSET_TABLE}}", "{{RELEASE_NOTES}}",
               "{{SCREENSHOT_BASE}}", "{{INITIAL_TREE}}"):
        if ph not in body:
            errs.append("正文缺发版占位符：%s" % ph)
    for stale in ("0d4b058", "3600155", "5e0b5d6849c29375"):
        if stale in body:
            errs.append("正文模板残留旧值：%s" % stale)
    return errs


def test_body_counts_match_current_matrix():
    body = _read()
    assert len(channel_dims_payload()["channels"]) == 10, (
        "渠道宇宙变了，同步改正文与契约")
    assert _count_errors(body) == [], _count_errors(body)
    # 负控：改回 7 家旧文案必须报错
    assert _count_errors(body.replace("10 家渠道", "7 家渠道")), (
        "负控失败：7 家旧文案没被拦")


def test_body_names_every_channel_and_scope():
    body = _read()
    assert _name_errors(body) == [], _name_errors(body)
    # 负控：删掉一个部分往返渠道名/范围必须报错
    cn = CHANNEL_CN["app_tongcheng"]
    assert _name_errors(body.replace(cn, "")), (
        "负控失败：漏渠道没被拦")
    assert _name_errors(body.replace("仅国际", "")), (
        "负控失败：漏范围短标签没被拦")


def test_body_keeps_multi_city_honest():
    body = _read()
    assert _multi_city_errors(body) == [], _multi_city_errors(body)
    # 负控：把「仅 2 段」改成「全段已支持」必须报错
    bad = body.replace("仅 2 段", "全段已支持")
    assert _multi_city_errors(bad), "负控失败：多程不实表述没被拦"


def test_body_has_release_placeholders_not_stale_values():
    body = _read()
    assert _placeholder_errors(body) == [], _placeholder_errors(body)
    # 负控：注入上一版源码/资产值必须报错
    assert _placeholder_errors(body + "\n0d4b058"), (
        "负控失败：旧源码 SHA 没被拦")
    assert _placeholder_errors(body.replace("{{VERSION}}", "v1.5.307")), (
        "负控失败：缺占位符没被拦")
    assert _placeholder_errors(body.replace("{{UI_TOTAL}}", "670")), (
        "负控失败：UI 分母写死没被拦")


def test_body_surface_column_matches_declared_surfaces():
    body = _read()
    assert len(_matrix_rows(body)) == len(CHANNEL_CN), (
        "矩阵行数与渠道数不一致：%d vs %d"
        % (len(_matrix_rows(body)), len(CHANNEL_CN)))
    assert _surface_errors(body) == [], _surface_errors(body)
    # 负控：删掉去哪儿 PC 停服说明 / 飞猪 H5 待验证说明，都必须报错
    assert _surface_errors(body.replace("H5（PC 已停服）", "H5")), (
        "负控失败：停服原因删除没被拦")
    assert _surface_errors(
        body.replace("PC / H5（H5 待验证）", "PC / H5")), (
        "负控失败：未验证原因删除没被拦")


def test_body_per_row_round_trip_scope_matches_matrix():
    body = _read()
    assert _rt_row_errors(body) == [], _rt_row_errors(body)
    bad = body.replace(
        "| 同程 App | App | 国内 / 国际 | 仅国际 |",
        "| 同程 App | App | 国内 / 国际 | 国内 / 国际 |")
    assert bad != body, "负控样本没替换到同程 App 行"
    assert _rt_row_errors(bad), (
        "负控失败：同程 App 的仅国际被改成全范围没被拦")


def test_dimensions_still_seven():
    assert len(DIMENSIONS) == 7, "维度宇宙变了，同步改正文矩阵说明"


def _rt_count_errors(body):
    n = sum(1 for row in CHANNEL_DIMENSIONS.values()
            if row["round_trip"] == "y")
    errs = []
    if "%d 家" % n not in body:
        errs.append("往返已接通家数没写 %d 家" % n)
    if "10 家均已有已接通通路" in body:
        errs.append("往返不得写 10 家均接通（飞猪 App 未验证）")
    return errs


def test_body_round_trip_count_matches_matrix():
    body = _read()
    assert _rt_count_errors(body) == [], _rt_count_errors(body)
    bad = body.replace("9 家", "10 家均已有已接通通路", 1)
    assert _rt_count_errors(bad), "负控失败：10 家均接通没被拦"
