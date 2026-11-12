# -*- coding: utf-8 -*-
"""r195 推送面回归：Composite 通道 errcode 透传（审校 P2-1）。

日报 -1 落账防重发守卫消费 `getattr(notifier, "last_errcode", None)`
（report.py 日报落账链）——但现网 CompositeNotifier 拓扑下该属性
不存在，判定恒 None：钉钉 -1 幽灵送达（报错但消息已入群）+ 邮箱
同轮失败时，日报不落账、下轮同文重推。修法=Composite.send 透传
成员 errcode（每轮先清防残留），**加强防重发，零重发逻辑引入**。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v195_push.py -q
"""

import logging

from core.notifier import CompositeNotifier  # noqa: E402

_MISSING = object()


class _ChFake:
    """通道 fake：send 返回预设结果，可选透传 last_errcode（形同
    DingTalkNotifier：成功 0 / 幽灵 -1 / 网络异常显式清 None）。"""

    def __init__(self, ok, errcode=_MISSING):
        self.ok = ok
        self.errcode = errcode

    def send(self, title, desp="", at_mobiles=None, is_at_all=False,
             launch=""):
        if self.errcode is not _MISSING:
            self.last_errcode = self.errcode
        return self.ok


def _comp(members):
    return CompositeNotifier(members, logging.getLogger("t"))


def test_composite_errcode_ghost_minus_one_passthrough():
    """钉钉 -1 幽灵 + 邮箱同轮失败（全通道 False）→ errcode=-1
    透传到 Composite，日报落账守卫可见。"""
    comp = _comp([_ChFake(False, errcode=-1), _ChFake(False)])
    assert comp.send("t", "d") is False
    assert comp.last_errcode == -1


def test_composite_errcode_success_zero():
    """钉钉成功 → 透传 0（非 -1，日报正常路径零影响）。"""
    comp = _comp([_ChFake(True, errcode=0), _ChFake(True)])
    assert comp.send("t", "d") is True
    assert comp.last_errcode == 0


def test_composite_errcode_absent_members_stays_none():
    """成员无 last_errcode 属性（邮件/ntfy 族）→ Composite 恒 None，
    getattr 消费点零 AttributeError。"""
    comp = _comp([_ChFake(False), _ChFake(False)])
    assert comp.send("t", "d") is False
    assert getattr(comp, "last_errcode", "missing") is None


def test_composite_errcode_cleared_per_round():
    """每轮先清：上轮 -1 残留不跨轮（钉钉网络异常路径成员自己清
    None——残留 -1 会把当日日报静默吞掉）。"""
    comp = _comp([_ChFake(False, errcode=-1), _ChFake(False)])
    comp.send("t", "d")
    assert comp.last_errcode == -1
    comp.members = [_ChFake(False, errcode=None), _ChFake(False)]
    comp.send("t", "d2")
    assert comp.last_errcode is None, "上轮 -1 残留跨轮（幽灵守卫误触发）"


def test_composite_member_raise_stale_errcode_not_picked():
    """成员 send 半途抛异常（Soldier P2-1）：异常=本轮 errcode 语义
    不可信，成员上轮残留 -1 不得被透传拾取——否则日报被误按
    「幽灵送达已推」落账，当日日报静默丢。"""
    class _Raiser:
        last_errcode = -1   # 上轮残留（类属性形态即实例可见）

        def send(self, *a, **kw):
            raise RuntimeError("boom")

    r = _Raiser()
    comp = _comp([r, _ChFake(False)])
    comp.send("t", "d")
    assert comp.last_errcode is None, "异常成员残留 -1 被拾取（守卫反噬）"
    # 实例视角断言（异常路径清的是实例属性，遮蔽类属性残留）
    assert getattr(r, "last_errcode") is None, "异常成员自身留痕未清"
