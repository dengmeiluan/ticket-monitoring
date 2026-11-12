# -*- coding: utf-8 -*-
"""r1799：后端停手理由也要说人话（与前端 durCN 同口径）。

改前日志：

```
[app_ctrip] 策略暂停本轮（blocked，604700s 后可试）：人工停手，剩 10079 分钟（…）
```

改后：

```
[app_ctrip] 策略暂停本轮（blocked，604089s 后可试）：人工停手，剩 7 天（登录风控无法登录，暂时放弃（用户决定 2026-11-12））：到期自动恢复，或人工解除
```

同一个状态在界面写「7 天」、在日志写「10079 分钟」，排查时还得自己换算。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.policy import _dur_cn  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_duration_cn_scales():
    assert _dur_cn(30) == "30 秒"
    assert _dur_cn(900) == "15 分钟"
    assert _dur_cn(3600) == "1 小时"
    assert _dur_cn(7200) == "2 小时"
    assert _dur_cn(604700) == "7 天"
    assert _dur_cn(0) == "0 秒"
    assert _dur_cn(None) == "0 秒"


def test_halt_reason_uses_helper():
    s = io.open(os.path.join(ROOT, "core", "policy.py"), encoding="utf-8").read()
    i = s.index("人工停手，剩 ")
    seg = s[i:i + 220]
    assert "_dur_cn(" in seg, "停手理由仍在写分钟"
    assert "%d 分钟" not in seg, "仍有硬编码分钟"


def test_frontend_uses_same_scale():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "function durCN(sec)" in w
    assert "' 天'" in w and "' 小时'" in w and "' 分钟'" in w
