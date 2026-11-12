# -*- coding: utf-8 -*-
"""r394：并发与指纹不变量（常驻守卫）。

目标里两条硬约束，此前只有人肉审计，没有自动化守护：

1. **无并发竞态劣化**：同一渠道必须串行（同 profile 不能被两个浏览器
   打开），跨渠道并发受全局配额约束；加锁顺序固定为「渠道锁 →
   全局配额」，不得出现反向嵌套（反向会把全局配额握在手里等自家锁，
   两家就能把其余渠道堵死）。
2. **采集/干预指纹幂等**：`fingerprint()` 是唯一身份来源；各渠道为了
   国际/PC 场景临时切 `use_mobile` 时，必须在 `finally` 里还原——
   漏还原会让下一次采集带着「上一场景的身份」，风控会当成会话被接管。
"""
import ast
import os
import threading
import time

import pytest

from crawlers import base as _base
from crawlers.base import channel_slot, platform_lock


def test_same_channel_is_serialized():
    """同渠道并发 4 个 → 必须串行（临界区并发数恒为 1）。"""
    state = {"in": 0, "max": 0}
    guard = threading.Lock()

    def worker():
        with channel_slot("qunar"):
            with guard:
                state["in"] += 1
                state["max"] = max(state["max"], state["in"])
            time.sleep(0.08)
            with guard:
                state["in"] -= 1

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert state["max"] == 1, state


def test_cross_channel_bounded_by_gate():
    """跨渠道并发受全局配额（CHANNEL_GATE）约束，不会无上限开浏览器。"""
    cap = _base.CHANNEL_GATE._initial_value  # BoundedSemaphore 容量
    state = {"in": 0, "max": 0}
    guard = threading.Lock()

    def worker(plat):
        with channel_slot(plat):
            with guard:
                state["in"] += 1
                state["max"] = max(state["max"], state["in"])
            time.sleep(0.08)
            with guard:
                state["in"] -= 1

    ts = [threading.Thread(target=worker, args=(p,))
          for p in ("qunar", "fliggy", "tuniu", "ctrip")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert state["max"] <= cap, (state, cap)


def test_channel_slot_locks_platform_before_gate():
    """加锁顺序必须是「渠道锁 → 全局配额」（源码钉）。

    反向（先全局配额再等自家渠道锁）会头阻塞：两家各自握着配额等锁，
    其余渠道全被挡在配额之外。
    """
    src = open(_base.__file__, encoding="utf-8").read()
    i = src.find("def channel_slot(")
    assert i > 0
    body = src[i:i + 700]
    a = body.find("with lock:")
    b = body.find("with CHANNEL_GATE:")
    assert 0 < a < b, body[:400]


def test_fingerprint_is_single_source_and_stable():
    """同一实例连续取值必须完全一致（幂等）；字段集固定。"""
    from crawlers.qunar import QunarCrawler
    import logging
    c = QunarCrawler({}, logging.getLogger("t_r394"))
    f1, f2 = c.fingerprint(), c.fingerprint()
    assert f1 == f2
    assert set(f1) == {"ua", "viewport", "locale", "timezone", "is_mobile",
                       "has_touch", "proxy", "stealth", "seed"}
    assert f1["locale"] == "zh-CN" and f1["timezone"] == "Asia/Shanghai"


def test_fingerprint_is_identical_across_instances():
    """重启后的新实例必须与旧实例同指纹（否则每次重启都是"新设备"）。

    这是"指纹幂等"真正要防的形态：进程重启、实例重建都不能让设备
    特征漂移，否则风控视角就是同一账号换机登录。
    """
    from crawlers.qunar import QunarCrawler
    from crawlers.ctrip import CtripCrawler
    import logging
    lg = logging.getLogger("t_r394b")
    a, b = QunarCrawler({}, lg), QunarCrawler({}, lg)
    assert a.fingerprint() == b.fingerprint()
    c1, c2 = CtripCrawler({}, lg), CtripCrawler({}, lg)
    assert c1.fingerprint() == c2.fingerprint()


def _is_use_mobile_assign(node, value=None):
    if not isinstance(node, ast.Assign):
        return False
    for t in node.targets:
        if (isinstance(t, ast.Attribute) and t.attr == "use_mobile"
                and isinstance(t.value, ast.Name) and t.value.id == "self"):
            if value is None:
                return True
            return (isinstance(node.value, ast.Constant)
                    and node.value.value == value)
    return False


def _unrestored_toggles(src):
    """返回 `self.use_mobile = False` 却没有 finally 还原的行号列表。

    切换写在 `try:` 之前，所以是「向下找最近的 try」（中间不得再出现
    别的 use_mobile 赋值），该 try 的 finalbody 必须含还原赋值。
    """
    tree = ast.parse(src)
    assigns = sorted((n for n in ast.walk(tree)
                      if _is_use_mobile_assign(n)), key=lambda n: n.lineno)
    tries = sorted((n for n in ast.walk(tree)
                    if isinstance(n, ast.Try)), key=lambda n: n.lineno)
    bad = []
    for node in assigns:
        if not _is_use_mobile_assign(node, False):
            continue
        nxt = [a.lineno for a in assigns if a.lineno > node.lineno]
        ceil = nxt[0] if nxt else 10 ** 9
        cand = [t for t in tries if node.lineno < t.lineno < ceil]
        if not (cand and any(_is_use_mobile_assign(s)
                             for s in cand[0].finalbody)):
            bad.append(node.lineno)
    return bad


def test_toggle_guard_catches_missing_restore():
    """守卫自检：漏 finally 还原必须被抓到（否则本组测试是哑的）。"""
    bad_src = (
        "class A:\n"
        "    def f(self):\n"
        "        self.use_mobile = False\n"
        "        with self.browser() as ctx:\n"
        "            return ctx\n"
    )
    good_src = (
        "class A:\n"
        "    def f(self):\n"
        "        bak = self.use_mobile\n"
        "        self.use_mobile = False\n"
        "        try:\n"
        "            with self.browser() as ctx:\n"
        "                return ctx\n"
        "        finally:\n"
        "            self.use_mobile = bak\n"
    )
    assert _unrestored_toggles(bad_src) == [3]
    assert _unrestored_toggles(good_src) == []


def test_use_mobile_toggles_are_always_restored():
    """各渠道临时切 use_mobile 的地方，都必须在 finally 里还原。

    漏还原 = 下一次采集带上一场景的身份（指纹漂移）。只用 AST，不用
    字符窗口：字符窗口会因子句变长而误报（r394 第一版 1600 字窗口就
    误报 3 处，实际都成对）。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = [os.path.join(here, "crawlers", f)
             for f in os.listdir(os.path.join(here, "crawlers"))
             if f.endswith(".py")]
    bad = []
    sites = 0
    for path in files:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
        bad += [(os.path.basename(path), ln)
                for ln in _unrestored_toggles(src)]
        sites += sum(1 for n in ast.walk(tree)
                     if _is_use_mobile_assign(n, False))
    assert not bad, bad
    # 基线：当前 6 处（base×2 / ctrip / qunar / tongcheng / tuniu 各 1）。
    # 少于此数说明有人换了写法但没同步本守卫，需人工确认。
    assert sites >= 6, sites


def test_platform_lock_is_per_platform():
    """不同渠道拿到的是不同的锁（否则退化成全局串行）。"""
    assert platform_lock("qunar") is not platform_lock("fliggy")
    assert platform_lock("qunar") is platform_lock("qunar")