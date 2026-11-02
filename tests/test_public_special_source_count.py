# -*- coding: utf-8 -*-
"""公开 README 的特价源数量必须与 SPECIAL_CAPABILITY 同源（r931）。

背景：能力表已有 9 个渠道含发现源（5 网页 + 4 App），CN README 却仍写
「七源（5 网页 + 2 App）」，漏了携程/同程 App；EN 已是 nine。这条漂移
不会被代码测试抓到，单独钉住文案。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.specials import SPECIAL_CAPABILITY  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EN_WORD = {7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven"}
CN_WORD = {7: "七", 8: "八", 9: "九", 10: "十", 11: "十一"}


def _n_sources():
    return sum(1 for v in SPECIAL_CAPABILITY.values() if v.get("sources"))


def _errors(cn, en):
    n = _n_sources()
    errs = []
    if n not in CN_WORD:
        errs.append("CN 数字词缺 %d，补 CN_WORD" % n)
    elif "%s源官方特价" % CN_WORD[n] not in cn:
        errs.append("CN README 特价源数量不是 %s" % CN_WORD[n])
    if n not in EN_WORD:
        errs.append("EN 数字词缺 %d，补 EN_WORD" % n)
    elif "%s official sources" % EN_WORD[n] not in en:
        errs.append("EN README 特价源数量不是 %s" % EN_WORD[n])
    for stale in ("七源官方特价", "seven official sources"):
        if stale in (cn if "源" in stale else en):
            errs.append("残留旧源数：%s" % stale)
    return errs


def test_readme_special_source_count_matches_code():
    cn = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    en = io.open(os.path.join(ROOT, "README_EN.md"), encoding="utf-8").read()
    assert _errors(cn, en) == [], _errors(cn, en)
    # 负控：七源旧文案必须报错
    assert _errors(cn.replace("九源官方特价", "七源官方特价", 1), en), (
        "负控失败：CN 七源没被拦")
    assert _errors(cn, en.replace("nine official sources",
                                  "seven official sources", 1)), (
        "负控失败：EN 七源没被拦")
