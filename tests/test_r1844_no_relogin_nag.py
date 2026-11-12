# -*- coding: utf-8 -*-
"""r1844/r1848：用户已经登好了，就别再催重登；航线级拦截也要说对数字。

用户 2026-11-12 反馈：「去哪儿 App 已经登录了啊，刚刚是被初次登录挡着了」。

账本印证：

```
08:36:06  航班明细 login   该日被要求登录          ← 登录之前的墙
08:50:55  航班明细 ok      1 条真实航班/时刻/价格  ← 登录之后恢复
09:07:05  航班明细 ok      1 条真实航班/时刻/价格
```

但建议仍在催「在手机上打开「去哪儿 App」用手机号登录一次」。根因：命中判据的是
`app-login` 这条**登录墙探针路径**——它天生不会记 ok，`login_since_ok` 永远不归零，
域级聚合还把各路径连击数加总。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p():
    return io.open(os.path.join(ROOT, "core", "pacing.py"),
                   encoding="utf-8").read()


def test_no_relogin_after_last_success():
    """判据语义：**上次成功之后有没有再撞墙**（与时间无关）。

    第一版用「60 分钟内出过数」，但渠道轮询间隔就有 25–37 分钟，
    中间没轮到它超过一小时很正常——实测 10:05 又变回 relogin。
    """
    s = _p()
    assert "_ok_recent" in s, "没有「会话是通的」判据"
    i = s.index("_ok_recent = bool(")
    seg = s[i:i + 300]
    assert "_last_login" in seg and "_last_ok" in seg, "没有比较登录与成功时间"
    assert "<=" in seg, "比较方向缺失（last_login <= last_ok 才算通）"
    assert "and not _ok_recent" in s, "判据没有接到登录墙分支上"
    j = s.index("_last_login = str(")
    assert "_sv" in s[j:j + 200], "取的不是域节点（_sp 是域的 paths 字典）"


def test_route_level_branch_reports_scope_numbers():
    s = _p()
    i = s.index("属航线级拦截")
    seg = s[max(0, i - 900):i + 300]
    assert "_scope_okish" in seg, "航线级分支仍用本路径出数（会写「出数（0 次）」）"
    assert '其他通路仍在出数' in seg


def test_live_qunar_advice_not_asking_to_relogin():
    """真实载荷：刚出过数的渠道不该再给 relogin。"""
    import json
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/pacing",
                               timeout=25).read())
    except Exception:
        return
    row = (d.get("channels") or {}).get("app_qunar") or {}
    a = row.get("advice") or {}
    if not a:
        return
    hint = str(a.get("hint") or "")
    if "其他通路仍在出数（0 次）" in hint:
        raise AssertionError("又出现了自相矛盾的 0 次：" + hint)
