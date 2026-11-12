# -*- coding: utf-8 -*-
"""r1869：Release 正文「行内/成块」占位符分工的门禁。

2026-11-12 发版事故：临时脚本把整篇 notes 与表格塞进**行内反引号**，
线上正文出现「；执行与能力契约：…」孤立行、双表头、嵌套反引号。
根因是模板本身没区分两类占位符，而填充逻辑是临时写的、没有门禁。

这条门禁钉三件事：
1. 模板里的**行内**占位符只能是短值（版本/SHA/日期/计数/路径/基址）；
2. 成块占位符（`{{ASSET_TABLE}}` `{{RELEASE_NOTES}}`）必须**整行**出现；
3. 时效性断言必须是占位符（`{{ASSET_PROVENANCE}}` 等），不许在模板里写死
   「本轮未重建 / 沿用上一冻结」这类只对某一轮成立的句子。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "docs", "RELEASE_BODY.md")

SHORT = {"VERSION", "SOURCE_SHA", "DATE", "TRACKED_TESTS", "TEST_COUNTS",
         "UI_COUNT", "UI_TOTAL", "SCREENSHOT_BASE", "RELEASE_NOTES_PATH"}
BLOCK = {"ASSET_TABLE", "RELEASE_NOTES"}
PROVENANCE = {"ASSET_PROVENANCE", "IMAGE_PROVENANCE",
              "IMAGE_PROVENANCE_SHORT", "HISTORY_SHAPE", "LIVE_STATUS"}


def _body():
    s = io.open(TPL, encoding="utf-8").read()
    return s[s.find("# ticket-monitoring 初版"):]


def test_only_short_placeholders_inline():
    body = _body()
    bad = []
    for line in body.splitlines():
        names = set(re.findall(r"\{\{([A-Z0-9_…]+)\}\}", line))
        if not names:
            continue
        for n in names:
            if n in SHORT or n in PROVENANCE:
                continue
            if n in BLOCK:
                if line.strip() != "{{%s}}" % n:
                    bad.append((n, line[:70]))
                continue
            bad.append((n, line[:70]))
    assert not bad, "行内出现了不该行内的占位符：%s" % bad[:4]


def test_block_placeholders_are_own_lines():
    body = _body()
    for n in BLOCK:
        assert re.search(r"(?m)^\{\{%s\}\}$" % n, body), \
            "成块占位符 {{%s}} 没有独立成行" % n


def test_no_hardcoded_epoch_claims():
    body = _body()
    for stale in ("本轮未重建", "沿用上一冻结构建", "不是同一构建批次",
                  "本轮未新增附件版本", "单一 root commit `"):
        assert stale not in body, "模板仍写死时效断言：%s" % stale


def test_filler_tool_exists_and_is_importable():
    p = os.path.join(ROOT, "tools", "release_fill_body.py")
    assert os.path.exists(p), "缺发版正文填充工具"
    src = io.open(p, encoding="utf-8").read()
    for k in ("{{ASSET_TABLE}}", "{{RELEASE_NOTES_PATH}}",
              "{{ASSET_PROVENANCE}}", "--assets-rebuilt"):
        assert k in src, "填充工具缺 " + k


def test_notes_path_is_inline_only():
    """`{{RELEASE_NOTES}}`（整篇）绝不能出现在行内——只能整行。"""
    body = _body()
    for line in body.splitlines():
        if "{{RELEASE_NOTES}}" in line:
            assert line.strip() == "{{RELEASE_NOTES}}", line[:80]
