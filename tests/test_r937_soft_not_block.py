# -*- coding: utf-8 -*-
"""r937：`soft_reject` 不该被记成"被拦"——57/62 份 block 现场其实是限流。

2026-11-04 清点 `debug/scene/*_block.txt`：

```
国际列表 interlist     57
其他                    5
合计                   62
```

而 `block:` 那一行全部带 `_gogokid=12`——看起来像"被风控拦了 62 次"。
实际上**国际列表 1999 间歇放行是主要来源**：它是 `soft_reject`
（发了、对方软拒/限流），不是风控拦截（`blocked`）。

根因在 `BaseCrawler.path_note()`：

```python
if rec["status"] in ("blocked", "login", "soft_reject"):
    ... self.last_block_url = purl ...
```

`soft_reject` 被并进"被拦"里，于是：
  * `debug/scene/*_block.txt` 越堆越多（每轮国际限流都留一份）；
  * 真拦截（人机验证）淹没在限流现场里，翻日志时看不出哪个才是真的；
  * `capture_scene` 的 tag 是 `block`，读起来就是"这次被拦了"。

账本里 status **已经**区分了 `blocked` / `soft_reject`，现场留证也该一致。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r937_soft_not_block.py -q
"""
import os
import sys

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
