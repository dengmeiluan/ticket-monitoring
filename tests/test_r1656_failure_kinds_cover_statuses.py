# -*- coding: utf-8 -*-
"""r1656：账本里会出现的每个状态码都必须有中文名与建议动作（不许「未分类」）。

`FAILURE_KINDS` 是「反复出现」那一栏的唯一文案来源。缺一个码，界面就写
「未分类 · 看日志」——把"不知道怎么归类"甩给用户。现场就是这么撞上的：
`kind=blocked → label=未分类`。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import FAILURE_KINDS, failure_kind  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _statuses(path):
    s = io.open(os.path.join(ROOT, path), encoding="utf-8").read()
    m = re.search(r"PATH_STATUS\s*=\s*\(([^)]*)\)", s, re.S)
    assert m, path
    body = re.sub(r"#[^\n]*", "", m.group(1))
    return [x for x in re.findall(r'"([a-z_]+)"', body)]


def test_every_crawler_status_has_a_label():
    missing = []
    for f in ("crawlers/base.py", "crawlers/app_base.py"):
        for st in _statuses(f):
            if st in ("ok", "calendar"):
                continue      # 这两个是成功态，不进"失败归类"
            if st not in FAILURE_KINDS:
                missing.append("%s:%s" % (f, st))
    assert not missing, "这些状态码在「反复出现」里会写成未分类：%s" % missing


def test_blocked_is_named():
    lbl, act, auto = failure_kind("blocked")
    assert lbl != "未分类", "blocked 仍是未分类"
    assert "拦" in lbl, lbl
    assert act and act != "看日志", act
    assert auto is False


def test_unknown_code_still_honest():
    lbl, act, _ = failure_kind("no-such-code")
    assert lbl == "未分类", "未知码应当如实说未分类（不要编）"
