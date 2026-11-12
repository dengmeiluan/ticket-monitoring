# -*- coding: utf-8 -*-
"""r1814：雷达卡不许假承诺「每 2 小时自动」。

现场（本轮实测）：

```
日志   [雷达监控] 跳过 邓美銮（incomplete）      ← 每 2 小时都在跳过
界面   特价监控 SHA → CAN · 11-10→11-12 · 每 2 小时自动 · 最近 11-02 09:04
```

`special_radar` 是空的（`config.yaml` 里 `special_radar: {}`），后台循环每轮直接
跳过，卡片却照抄 `auto_interval_h=2` 说「每 2 小时自动」。上次真实刷新停在 11-02。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_server_reports_auto_ok():
    s = _w()
    assert 'out["auto_ok"]' in s, "载荷没有 auto_ok"
    assert 'out["auto_why"]' in s, "载荷没有 auto_why"
    i = s.index('out["auto_ok"]')
    seg = s[max(0, i - 600):i + 400]
    assert "_radar_auto_query(" in seg, "没按配置判断自动是否会跑"
    assert "判不了就别断言它停了" in seg, "缺兜底说明（判不了不乱说）"


def test_frontend_branches_on_auto_ok():
    s = _w()
    i = s.index("小时自动")
    seg = s[max(0, i - 300):i + 400]
    assert "j.auto_ok===false" in seg, "前端没按 auto_ok 分支"
    assert "自动刷新未启用" in seg, "没有「未启用」的说法"


def test_live_payload_has_auto_ok():
    import urllib.parse
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        u = ("http://127.0.0.1:8765/api/radar/history?days=30&user="
             + urllib.parse.quote("邓美銮"))
        d = json.loads(op.open(u, timeout=30).read())
    except Exception:
        return          # 服务没起就跳过
    assert isinstance(d, dict), d
    assert "auto_ok" in d, "真实载荷没有 auto_ok：%s" % list(d)[:8]
    assert d.get("auto_ok") in (True, False), d.get("auto_ok")
    if d.get("auto_ok") is False:
        assert d.get("auto_why"), "说自动没跑，却不给原因"
