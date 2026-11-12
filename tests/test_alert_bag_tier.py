# -*- coding: utf-8 -*-
"""按托运分档阈值（alert_direct_bag）：分池判据与候选选择。

背景：国内票常见「无托运更便宜」，用户要「无托运 <300、含托运 <400」
两条线。原模型只有单一 alert_direct + min_baggage 过滤（会把无托运
整池剔掉），表达不了分档。
"""
from types import SimpleNamespace

from core.alerter import Alerter, _has_free_bag


def test_has_free_bag_positive():
    assert _has_free_bag({"baggage": "免费托运20KG"})
    assert _has_free_bag({"baggage": "手提7kg·托运20kg"})
    assert _has_free_bag({"baggage": "23公斤"})


def test_has_free_bag_negative():
    # 明示无托运 / 需另购：词面带「托运」也不能算含托运
    assert not _has_free_bag({"baggage": "无免费托运"})
    assert not _has_free_bag({"baggage": "行李需另购"})
    assert not _has_free_bag({"baggage": "不含托运行李"})
    # 没有 kg 数 = 未标注，fail-close 与 min_baggage 同律
    assert not _has_free_bag({"baggage": "含托运"})
    assert not _has_free_bag({"baggage": ""})
    assert not _has_free_bag({})


def _route(direct, bag):
    return SimpleNamespace(alert_direct=direct, alert_direct_bag=bag)


def _pick(route, nobag, bag):
    a = Alerter.__new__(Alerter)
    return a._direct_tier_pick(route, {
        "best_direct_nobag": ({"price": nobag} if nobag is not None else None),
        "best_direct_bag": ({"price": bag} if bag is not None else None),
    })


def test_tier_disabled_returns_none():
    """alert_direct_bag=0 时不做分档，调用方走原单一阈值逻辑。"""
    assert _pick(_route(300, 0), 280, 390) is None


def test_tier_picks_relatively_better_hit():
    """两条都达标时取相对阈值更划算的一条（280/300 < 390/400）。"""
    got = _pick(_route(300, 400), 280, 390)
    assert got is not None
    assert got[0]["price"] == 280 and got[1] == 300


def test_tier_picks_bag_when_only_bag_hits():
    """无托运超线、含托运达标 → 推含托运那条，阈值是 400。"""
    got = _pick(_route(300, 400), 320, 395)
    assert got is not None
    assert got[0]["price"] == 395 and got[1] == 400


def test_tier_picks_nobag_when_only_nobag_hits():
    got = _pick(_route(300, 400), 260, 460)
    assert got is not None
    assert got[0]["price"] == 260 and got[1] == 300


def test_tier_none_when_nothing_hits():
    assert _pick(_route(300, 400), 350, 450) is None


def test_tier_single_side_missing():
    """只有一池有数据时不该崩，也不该误判。"""
    got = _pick(_route(300, 400), None, 380)
    assert got is not None and got[0]["price"] == 380
    got = _pick(_route(300, 400), 250, None)
    assert got is not None and got[0]["price"] == 250
