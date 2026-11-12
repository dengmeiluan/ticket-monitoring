# -*- coding: utf-8 -*-
"""r1219：`platforms: []` 必须等于"一条都不采"。

实测事故（2026-11-10）：为了验证零配置，在干净副本里把 `users[].platforms`
清空想"停采"，结果日志立刻出现
`[fliggy] 开始抓取 …` / `[qunar] 开始抓取 …` —— 因为原代码写的是

```python
"platforms": u.get("platforms") or cfg.get("platforms", [四家默认]),
```

`[]` 是假值，被当成"没配"，回落到默认四家。用户以为清空订阅就停手，实际还在打渠道。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main as M  # noqa: E402


def _cfg(user_extra, global_platforms="__absent__"):
    user = {"name": "u", "special_radar": {"x": 1}}   # 有内容才不会被跳过
    user.update(user_extra)
    cfg = {"users": [user]}
    if global_platforms != "__absent__":
        cfg["platforms"] = global_platforms
    return cfg


def test_explicit_empty_means_no_channels():
    users = M.build_users(_cfg({"platforms": []}))
    assert users, "用户被跳过了，用例没测到点子上"
    assert users[0]["platforms"] == [], "显式空列表被回落成默认渠道了"


def test_missing_key_falls_back_to_global():
    users = M.build_users(_cfg({}, global_platforms=["ctrip"]))
    assert users[0]["platforms"] == ["ctrip"]


def test_missing_everything_uses_legacy_default():
    users = M.build_users(_cfg({}))
    assert set(users[0]["platforms"]) == {"qunar", "fliggy", "tongcheng", "tuniu"}


def test_global_empty_also_means_none():
    users = M.build_users(_cfg({}, global_platforms=[]))
    assert users[0]["platforms"] == []


def test_explicit_list_wins():
    users = M.build_users(_cfg({"platforms": ["tuniu"]}, global_platforms=["ctrip"]))
    assert users[0]["platforms"] == ["tuniu"]
