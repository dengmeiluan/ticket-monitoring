# -*- coding: utf-8 -*-
"""r1224：cookie 重复会让 Playwright 直接拒收——途牛 PC 通路整轮拿不到价。

现场（2026-11-10 生产日志）：

```
[tuniu] 请求异常: Multiple cookies exist with name=mtoken     × 338 次
[tuniu] 2027-01-29 达到最大重试圈数 5 仍未拿到价格
```

`crawlers/base.py` 恢复会话时 `ctx.add_cookies(plan)`，而快照里同名同域同 path
的 `mtoken` 出现多份（不同登录时刻叠加）→ Playwright 抛错 → 该通路整轮失败。

契约：`_dedupe_cookies()` 按 (name, domain, path) 去重、保留首个、**幂等**。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.base import _dedupe_cookies  # noqa: E402


def test_dedupes_same_name_domain_path():
    ck = [
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/", "value": "A"},
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/", "value": "B"},
        {"name": "ssoUser", "domain": ".tuniu.com", "path": "/", "value": "C"},
    ]
    out = _dedupe_cookies(ck)
    assert len(out) == 2, out
    assert out[0]["value"] == "A", "应当保留先出现的那份"
    assert out[1]["name"] == "ssoUser"


def test_keeps_different_path_or_domain():
    """同名但 path/domain 不同的必须都留着——否则会把登录态弄丢。"""
    ck = [
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/"},
        {"name": "mtoken", "domain": "m.tuniu.com", "path": "/"},
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/flight"},
    ]
    assert len(_dedupe_cookies(ck)) == 3


def test_idempotent_and_empty_safe():
    assert _dedupe_cookies([]) == []
    assert _dedupe_cookies(None) == []
    ck = [{"name": "a", "domain": "d", "path": "/"}]
    assert _dedupe_cookies(_dedupe_cookies(ck)) == ck


def test_missing_fields_tolerated():
    """缺字段不能炸（真实快照里见过没有 path 的条目）。"""
    out = _dedupe_cookies([{"name": "x"}, {"name": "y", "domain": "d"}])
    assert len(out) == 2


def test_wired_before_add_cookies():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"), encoding="utf-8").read()
    i = src.find("ctx.add_cookies(")
    seg = src[max(0, i - 400):i + 80]
    assert "_dedupe_cookies(plan)" in seg, "灌 cookie 前没有去重（重复会直接抛异常）"
