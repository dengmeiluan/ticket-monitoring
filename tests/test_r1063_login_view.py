# -*- coding: utf-8 -*-
"""r1063 T135：`channel_matrix --login` —— 一眼看出"该去登哪一格"。

动机（真实数据）：途牛近 6 小时 `H5/API` 出现 9 次
「登录门（710114/needLogin）」、8 次成功 —— 45% 的缺口**不是策略能补的**，
就是没登录。既然如此，工具应当直接告诉用户该登哪一格，而不是翻九个槽位。

`--login` 输出（真机实测）：
```
槽位          端      状态     要登录  被拦   登录入口
tuniu        PC      需登录    是      -     https://passport.tuniu.com/login
tuniu_h5     H5      需登录    是      -     https://m.tuniu.com/flight/
需要登录：tuniu、tuniu_h5
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channel_matrix as CM  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROWS = [
    {"slot": "ctrip", "surface": "PC", "status": "available", "needs": False,
     "block": "-", "verified": "", "url": "https://passport.ctrip.com/user/login"},
    {"slot": "tuniu", "surface": "PC", "status": "login_required", "needs": True,
     "block": "-", "verified": "", "url": "https://passport.tuniu.com/login"},
    {"slot": "tuniu_h5", "surface": "H5", "status": "login_required",
     "needs": True, "block": "login", "verified": "",
     "url": "https://m.tuniu.com/flight/"},
]


def test_login_text_lists_slots_and_needs():
    txt = CM._login_text({"ok": True, "rows": ROWS})
    assert "槽位" in txt and "端" in txt and "登录入口" in txt
    assert "需登录" in txt and "空闲" in txt
    assert "需要登录：tuniu、tuniu_h5" in txt, txt


def test_login_text_all_good():
    rows = [dict(r, needs=False, status="available") for r in ROWS]
    txt = CM._login_text({"ok": True, "rows": rows})
    assert "需要登录：无 ✓" in txt, txt


def test_login_text_offline():
    txt = CM._login_text({"ok": False, "rows": [], "why": "连不上实例：x"})
    assert txt.startswith("✗")


def test_login_state_mapping_has_core_states():
    for k in ("saved", "available", "login_required", "challenge"):
        assert k in CM.SLOT_STATE_CN


def test_cli_exposes_login_flag():
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--login" in src
    assert "def login_slots(" in src and "def _login_text(" in src
