# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r937_soft_not_block.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys


# ---- merged from tests/test_r937_soft_not_block.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Page:
    url = "https://touch.qunar.com/ncs/page/interlist?x=1&_gogokid=12"


def _crawler():
    from crawlers.qunar import QunarCrawler
    c = QunarCrawler({"user_data_dir": "user_data"}, None)
    c._last_page = _Page()
    c.path_reset()
    return c


# ---------------------------------------------------------------------------
# 1. soft_reject 不再被当成"被拦"
# ---------------------------------------------------------------------------
def test_soft_reject_does_not_set_block_url():
    c = _crawler()
    c.path_note("H5", "soft_reject", detail="1999/8 间歇放行")
    assert c.last_block_url == "", "soft_reject 仍被记成被拦"
    assert c._scene_pending == "", "soft_reject 仍触发了现场截图"


# ---------------------------------------------------------------------------
# 2. blocked / login 仍然要留现场（不能被这次改动误伤）
# ---------------------------------------------------------------------------
def test_blocked_still_sets_block_url():
    c = _crawler()
    c.path_note("H5", "blocked", detail="人机验证")
    assert c.last_block_url.startswith("https://touch.qunar.com/")
    assert c._scene_pending


def test_login_still_sets_block_url():
    c = _crawler()
    c.path_note("H5", "login", detail="请登录")
    assert c.last_block_url.startswith("https://touch.qunar.com/")


# ---------------------------------------------------------------------------
# 3. 账本 status 本身不变（只是现场留证的口径变了）
# ---------------------------------------------------------------------------
def test_status_value_unchanged():
    c = _crawler()
    c.path_note("H5", "soft_reject", detail="限流")
    assert c.last_status == "soft_reject"
    assert any(r.get("status") == "soft_reject" for r in c.paths)


# ---------------------------------------------------------------------------
# 4. 源码钉：别把 soft_reject 加回"被拦"列表
# ---------------------------------------------------------------------------
def test_source_excludes_soft_from_block_list():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    i = src.find("if rec[\"status\"] in (\"blocked\", \"login\")")
    assert i > 0, "被拦判据不见了"
    seg = src[i:i + 200]
    assert "soft_reject" not in seg, "soft_reject 又被并进被拦列表"
