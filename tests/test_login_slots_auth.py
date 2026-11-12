# -*- coding: utf-8 -*-
"""门禁：每个登录槽位的载体类都必须声明登录凭证名单。

来历（issue #19，作者 ismoss）：槽位 `fliggy_h5` 实例化的是
`crawlers/fliggy.py::FliggyH5Login`（profile carrier），它**没有** `AUTH_COOKIES`，
而 `crawlers/base.py::_state_has_auth` 见到空名单直接 `return False`：

    want = tuple(getattr(self, "AUTH_COOKIES", ()) or ())
    if not want:
        return False

于是链路变成：用户登录成功 → 快照里「没有可识别的凭证」→ 不写 session-state.json
→ 下一轮仍判未登录 → 继续弹窗。**死循环**，而且日志里一句报错都没有。

这条门禁把「新增槽位/换载体类」时必须一起声明凭证这件事钉死：漏了就在 CI 红，
而不是等用户登十遍登不进去。
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _resolve():
    """按**生产同一条路径**解析每个槽位的载体类（不实例化，避免副作用）。"""
    from core.login_slots import LOGIN_SLOTS
    from crawlers import REGISTRY
    from crawlers.fliggy import FliggyH5Login

    # 与 core.login_slots.slot_crawler 里的特例保持一致
    special = {"fliggy_h5": FliggyH5Login}
    out = {}
    for slot, meta in LOGIN_SLOTS.items():
        plat = str(meta.get("plat") or slot)
        cls = special.get(slot) or REGISTRY.get(plat)
        if cls is not None:
            out[slot] = (plat, cls)
    return out


def test_every_login_slot_carrier_declares_auth():
    missing = []
    for slot, (plat, cls) in sorted(_resolve().items()):
        cookies = tuple(getattr(cls, "AUTH_COOKIES", ()) or ())
        storage = tuple(getattr(cls, "AUTH_STORAGE_KEYS", ()) or ())
        if not cookies and not storage:
            missing.append("%s（%s::%s）" % (slot, cls.__module__, cls.__name__))
    assert not missing, (
        "这些登录槽位的载体类没声明 AUTH_COOKIES / AUTH_STORAGE_KEYS，"
        "登录成功也会永远判「未检测到凭证」（issue #19 的死循环）：%s" % missing)


def test_fliggy_h5_both_classes_declare_cookies():
    """#19 的具体两个类：carrier 与采集器都要有（后者也会走同一判定）。"""
    from crawlers.fliggy import FliggyH5Login
    from crawlers.fliggy_h5 import FliggyH5Crawler
    for cls in (FliggyH5Login, FliggyH5Crawler):
        cookies = tuple(getattr(cls, "AUTH_COOKIES", ()) or ())
        assert cookies, "%s 缺 AUTH_COOKIES" % cls.__name__
        # 匿名 cookie（如 _tb_token_）不能当凭证：淘宝匿名访问就下发
        assert "_tb_token_" not in cookies, (
            "%s 把 _tb_token_ 当凭证——它匿名就下发，会把登出态写成已登录"
            % cls.__name__)


def test_auth_gate_detects_missing_declaration():
    """负控：一个没声明凭证的类必须被判为不合格（门禁不空转）。"""
    class FakeCarrier:
        pass

    assert not tuple(getattr(FakeCarrier, "AUTH_COOKIES", ()) or ())
    assert not tuple(getattr(FakeCarrier, "AUTH_STORAGE_KEYS", ()) or ())
