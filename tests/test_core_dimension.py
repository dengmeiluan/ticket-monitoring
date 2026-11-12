# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r805ad_dimension_notes.py
- tests/test_r903_dimension_note_contract.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import ast
import io
import os
import sys


# ---- merged from tests/test_r805ad_dimension_notes.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_dimension_notes_explain_calendar_only_intl():
    from core.channels import DIMENSION_NOTES
    for plat in ("tongcheng", "app_qunar"):
        note = DIMENSION_NOTES.get((plat, "intl")) or ""
        assert note.strip(), (
            "%s 的国际端只有日历价，intl 格上必须写明（否则读者把"
            "「有国际报价」读成「国际也有航班明细」）" % plat)
        assert "日历" in note, (
            "%s 的 intl 说明没点出「只有日历价」：%r" % (plat, note))


def test_tuniu_intl_note_names_the_h5_path_and_pc_block():
    """途牛国际 y 的实情是「H5/API 出数、PC 被滑块拦」——必须在悬停里说清。

    只写 y 会让读者以为 PC 也能查；写 n 又与事实不符（H5 真出过数）。
    """
    from core.channels import DIMENSION_NOTES
    note = DIMENSION_NOTES.get(("tuniu", "intl")) or ""
    assert "H5" in note and "PC" in note, (
        "tuniu.intl 说明没点出「H5/API 出数、PC 被拦」的分端事实：%r" % note)
    assert "滑块" in note, "没说明 PC 为什么测不出：%r" % note
    assert "n" in note, "没说明「测不出不记 n」的口径：%r" % note


def test_api_exposes_dim_notes():
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8").read()
    assert "DIMENSION_NOTES" in src, (
        "channel_dims_payload 没引用分域说明单一事实源")
    i = src.index('"channels": [')
    seg = src[i:i + 900]
    assert "dim_notes" in seg, (
        "载荷没下发 dim_notes：前端无从渲染，说明加了等于没加")
    webui = webui_full_src()
    assert "channel_dims_payload()" in webui, "接口没走单一矩阵载荷"




# ---- merged from tests/test_r903_dimension_note_contract.py ----

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
