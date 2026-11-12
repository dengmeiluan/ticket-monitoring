# -*- coding: utf-8 -*-
"""r1063 T270：H5 槽位"登录了却一直显示待验证"（用户原话："页面没变"）。

线上实测（修前）：
```
ctrip/fliggy/tongcheng/tuniu        → available, detail_ok=True
ctrip_h5/fliggy_h5/tongcheng_h5/tuniu_h5 → saved,     detail_ok=False   ← 全是假的
```
根因：独立端面槽位把 `detail_ok` 写死 False；而 `plats[plat].scopes` 是按
**维度**（domestic/international）聚合的，没有端面维度可查。

修：端面是否"明细可用"从**通路账本**里取（`entry_path` 以 `H5`/`PC` 开头且
`path_status` 为 ok/calendar 或 `rows>0`）；并把 `saved/pending/page_ok` 抬成
`available`（但不许盖掉 challenge/login_required）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402

F = webui._surface_detail_ok


def test_h5_rows_with_ok_count_as_detail_ok():
    rows = [{"entry_path": "H5/API", "path_status": "ok", "rows": 12}]
    assert F(rows, "h5") is True


def test_pc_rows_do_not_make_h5_available():
    rows = [{"entry_path": "PC", "path_status": "ok", "rows": 99}]
    assert F(rows, "h5") is False, "PC 出数不能冒充 H5 出数"
    assert F(rows, "PC") is True


def test_timeout_rows_do_not_count():
    rows = [{"entry_path": "H5", "path_status": "timeout", "rows": 0}]
    assert F(rows, "h5") is False


def test_unsupported_rows_do_not_count():
    rows = [{"entry_path": "H5", "path_status": "unsupported", "rows": 0}]
    assert F(rows, "h5") is False, "能力边界不能算明细可用"


def test_unknown_surface_is_false():
    assert F([{"entry_path": "H5", "path_status": "ok"}], "") is False


def test_status_elevation_source_contract():
    """detail_ok 必须能抬 status，但不能盖掉被拦。"""
    w = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = w.index("detail_ok 抬成 available")
    seg = w[i:i + 700]
    cond = 'if detail_ok and status in ("saved", "pending", "page_ok")'
    assert cond in seg, seg[:200]
    assert 'status = "available"' in seg
    # 条件里（代码行，不含注释）不得出现 challenge/login_required
    assert "challenge" not in cond and "login_required" not in cond
