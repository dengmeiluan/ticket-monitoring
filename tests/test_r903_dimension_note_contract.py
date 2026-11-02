# -*- coding: utf-8 -*-
"""r903：能力矩阵的「值 / 说明 / 范围」必须自洽，重复键不得静默覆盖。

背景：`app_ctrip.low_fare` 在 `DIMENSION_NOTES` 里写了两次——先写「价格
日历即逐日最低价源，已接特价雷达」，后面又保留旧文案「App 有特价机票
入口；采集端未接逐日低价源，不写 y」。Python 字典字面量允许重复键、
后者静默覆盖，于是运行时和 `/api/channel-dims` 都只看到旧文案：矩阵
显示 ✓，悬停却说没接。既有门禁全绿，因为它们只查「有没有说明」，
不查「说明和值是否矛盾」，也不查「同一个键是否被写了两次」。

判据：
  1. 源码层：声明字典不得有重复键（AST 字面量），且必须真的扫到这些
     字典（防锚点失效后空转变绿）；
  2. 语义层：每个非 y 格（`n` 与 `""`）必须有说明；说明/范围的键必须
     是合法渠道 × 维度；scope 只能挂在 y 上；y 格说明不得出现
     「不写 y / 采集端未接」这类自相矛盾措辞；
  3. 载荷层：`channel_dims_payload()` 的 `dim_notes`/`dim_scopes` 必须与
     声明逐格同一份文本（不另拼一份），且每通道覆盖全部维度。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CHANNELS_SRC = os.path.join(ROOT, "core", "channels.py")

DECLARATION_DICTS = (
    "CHANNEL_CN", "CHANNEL_DIMENSIONS", "CHANNEL_SURFACES",
    "DIMENSION_NOTES", "DIMENSION_SCOPE", "SURFACE_NOTES",
    "PATH_CN", "APP_BROWSER_PEER",
)


def _dict_literals(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found.setdefault(target.id, node.value)
    return found


def test_declaration_dicts_have_no_duplicate_keys():
    found = _dict_literals(CHANNELS_SRC)
    missing = [name for name in DECLARATION_DICTS if name not in found]
    assert not missing, (
        "声明字典锚点失效，本门禁会空转变绿：%s" % missing)
    duplicates = []
    for name in DECLARATION_DICTS:
        node = found[name]
        seen = {}
        for key_node in node.keys:
            if key_node is None:  # {**other}
                continue
            try:
                key = ast.literal_eval(key_node)
            except Exception:
                continue
            if key in seen:
                duplicates.append((name, key, seen[key], key_node.lineno))
            else:
                seen[key] = key_node.lineno
    assert not duplicates, (
        "声明字典出现重复键（后者会静默覆盖前者）：%s"
        % ["%s[%r] 首写行 %s / 覆盖行 %s" % d for d in duplicates])


def test_every_non_y_cell_is_explained_and_scope_only_on_y():
    from core.channels import (CHANNEL_DIMENSIONS, DIMENSION_NOTES,
                               DIMENSION_SCOPE, DIMENSIONS)
    missing = ["%s.%s" % (p, d)
               for p, cells in CHANNEL_DIMENSIONS.items()
               for d in DIMENSIONS
               if cells.get(d) != "y"
               and not (DIMENSION_NOTES.get((p, d)) or "").strip()]
    assert not missing, (
        "这些格子不是 y 却没有说明（读者会把未验证/不支持读成渠道没有）：%s"
        % sorted(missing))

    orphan_notes = [key for key in DIMENSION_NOTES
                    if key[0] not in CHANNEL_DIMENSIONS
                    or key[1] not in DIMENSIONS]
    assert not orphan_notes, "说明挂在不存在的渠道/维度上：%s" % orphan_notes

    orphan_scopes = [key for key in DIMENSION_SCOPE
                     if key[0] not in CHANNEL_DIMENSIONS
                     or key[1] not in DIMENSIONS]
    assert not orphan_scopes, "范围挂在不存在的渠道/维度上：%s" % orphan_scopes

    scope_on_non_y = [(p, d, CHANNEL_DIMENSIONS[p].get(d))
                      for (p, d) in DIMENSION_SCOPE
                      if CHANNEL_DIMENSIONS[p].get(d) != "y"]
    assert not scope_on_non_y, (
        "范围标签只能挂在 y 格上（非 y 会让读者以为「部分支持」）：%s"
        % scope_on_non_y)


def test_y_cells_do_not_carry_contradictory_notes():
    from core.channels import CHANNEL_DIMENSIONS, DIMENSION_NOTES, DIMENSIONS
    contradictions = []
    for plat, cells in CHANNEL_DIMENSIONS.items():
        for dim in DIMENSIONS:
            if cells.get(dim) != "y":
                continue
            note = DIMENSION_NOTES.get((plat, dim)) or ""
            if "不写 y" in note or "不写y" in note or "采集端未接" in note:
                contradictions.append((plat, dim, note[:80]))
    assert not contradictions, (
        "y 格的说明自称「未接/不写 y」，矩阵值与悬停互相打脸：%s"
        % contradictions)


def test_payload_reuses_the_declaration_verbatim():
    from core.channels import (CHANNEL_DIMENSIONS, DIMENSIONS,
                               DIMENSION_NOTES, DIMENSION_SCOPE,
                               channel_dims_payload)
    payload = channel_dims_payload()
    assert payload.get("ok") is True
    assert payload.get("dims") == list(DIMENSIONS), "载荷维度顺序漂移"
    channels = {item["plat"]: item for item in payload["channels"]}
    assert set(channels) == set(CHANNEL_DIMENSIONS), (
        "载荷渠道集合与声明不一致：%s"
        % (set(channels) ^ set(CHANNEL_DIMENSIONS)))
    for plat, item in channels.items():
        for field in ("cells", "dim_notes", "dim_scopes"):
            assert set(item[field]) == set(DIMENSIONS), (
                "%s 的 %s 没覆盖全部维度" % (plat, field))
        for dim in DIMENSIONS:
            assert item["cells"][dim] == CHANNEL_DIMENSIONS[plat].get(dim, "")
            assert item["dim_notes"][dim] == (
                DIMENSION_NOTES.get((plat, dim)) or ""), (
                "%s.%s 的载荷说明不是声明原文（有人另拼了一份）"
                % (plat, dim))
            assert item["dim_scopes"][dim] == (
                DIMENSION_SCOPE.get((plat, dim)) or "")

    # 回归钉：曾因重复键被旧文案覆盖的那一格。
    note = channels["app_ctrip"]["dim_notes"]["low_fare"]
    assert channels["app_ctrip"]["cells"]["low_fare"] == "y"
    assert "特价雷达" in note and "不写 y" not in note, (
        "app_ctrip.low_fare 是 y 且已接雷达，悬停却仍在说未接：%r" % note)
