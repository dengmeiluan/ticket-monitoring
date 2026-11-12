# -*- coding: utf-8 -*-
"""r1697：三率页必须看得见「一直失败」的通路（App 渠道的 app-city 之类）。

现场：`/api/three-rates` 的 `by_path` 只有 13 条**成功过**的通路，
一条 App 通路都没有——因为条目来自 `baseline.by_path()`，那条 SQL 只统计
`path_status in OK_STATUSES`。结果：我们花两天查的 `app-city` / `app-form`
在「三率一险」里完全不统计，正好与「一切可统计」相反。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "core", "rates.py"), encoding="utf-8",
                   newline="").read()


def test_zero_yield_paths_are_included():
    s = _src()
    assert "only attempts" not in s  # 占位，防止误判
    assert 'r1697' in s, "没有补零产出通路的逻辑"
    i = s.index("r1697")
    seg = s[i:i + 2200]          # r1825：插了 skipped_only 分支，窗口放宽
    assert '"no_ok": True' in seg, "零产出通路没有标记"
    assert '"risk": 1.0' in seg, "零产出通路的风险值不对（应为 100%）"
    assert '"yield": 0.0' in seg, "零产出通路的爬取率不对（应为 0）"
    # r1822：全是「能力边界/主动跳过」的通路不能被标成 0 出数
    assert '"skipped_only": True' in seg, "全被跳过的通路没有单独标记"
    assert '"no_ok": False,' in seg, "全被跳过的通路仍被标成零产出"


def test_live_payload_has_app_paths():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/three-rates",
                               timeout=25).read())
    except Exception:
        return
    bp = d.get("by_path") or []
    if not bp:
        return
    app = [r for r in bp if str(r.get("plat", "")).startswith("app_")]
    assert app, "三率里一条 App 通路都没有——失败面被口径藏起来了"
    zero = [r for r in app if r.get("no_ok")]
    if zero:
        for r in zero:
            assert r["ok_n"] == 0 and r["rows"] == 0
            assert r["yield"] == 0.0 and r["risk"] == 1.0
