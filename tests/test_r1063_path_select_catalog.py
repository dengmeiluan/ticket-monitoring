# -*- coding: utf-8 -*-
"""r1063 T159：策略面板的「链路」下拉要能选到**还没跑过**的通路。

真因（读代码得出）：`stratScopeFill()` 的链路选项**只来自**
`STRATPAY.health[plat].paths`——也就是"账本里出现过的通路"。于是本轮新增的
`PC·国际` / `PC·周历` 在第一次运行前**永远选不到**，用户没法预先给它配策略，
"通路进策略面板"就成了空话。

改法：选项 = **跑过的**（`health[plat].paths`）∪ **全量目录**
（`/api/strategy.paths`，唯一口径 `core.channels.PATH_CN`），并去重。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _scope_fill_body() -> str:
    s = _src()
    i = s.index("function stratScopeFill(")
    j = s.find("\nfunction ", i + 10)
    return s[i:j if j > 0 else i + 2000]


def test_path_select_merges_catalog():
    body = _scope_fill_body()
    assert "H.paths" in body, "跑过的通路仍要在列表里（顺序更靠前）"
    assert "STRATPAY.paths" in body, "必须并上全量目录，否则新通路永远选不到"
    assert "_seen" in body, "必须去重，否则同一通路出现两次"
    assert "r1063 T158" in body, "留注释说明为什么这么做"


def test_catalog_field_comes_from_single_source():
    s = _src()
    i = s.index('out["paths"] = [{"id": _k, "cn": _v}')
    seg = s[max(0, i - 400):i + 200]
    assert "from core.channels import PATH_CN" in seg


def test_new_paths_present_in_catalog():
    from core.channels import PATH_CN
    for pid in ("PC·国际", "PC·周历"):
        assert pid in PATH_CN
        assert re.search(r"[\u4e00-\u9fff]", PATH_CN[pid]), \
            "%s 的中文名不能是空的（下拉里直接显示它）" % pid
