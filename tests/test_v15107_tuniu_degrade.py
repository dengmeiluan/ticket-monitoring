# -*- coding: utf-8 -*-
"""tuniu 降级样本（fareList 截断）fetch 层加固回归。

取证（r107 渠道调研 B）：09-28 22:11 轮 10-05 日期 fareList 截断 n=1，
渠道最低价落库 2970，健康轮真最低 1980（虚高 50%）；09-29 23:08 起
截断逐轮交替（3/43 隔轮出勤，责任周期 ~48%）。响应结构合法（fareList
非空即被判「真实价格」早收），坏在样本不完整——轮最低价与明细随截断面
失真，且曲线端出现假高点。

加固形态（零误杀）：
- 早收门槛 _FARE_FLOOR：健康轮首响即收（零额外请求）；门槛取
  健康带下缘（自然轮 DB 实证：薄带 3-15、空档 16-38 非恒空、
  健康 39+——floor 8→20→39，空档带全量续询）；
- 薄样本（0<n<门槛）不早收，记 best-so-far 续询，薄响应最多连看
  _THIN_MAX=3 个（礼貌预算有界）；
- 穷尽兜底返回 best-so-far（真稀疏日期零数据丢失，仅多 ≤2 次请求）；
- 兜底路径打「疑似降级样本」日志，供观测 WATCH 记责任周期。

fake 客户端脚本化 listFlight 响应序列，全程离线。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15107_tuniu_degrade.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers.tuniu as tn  # noqa: E402
from crawlers.tuniu import LIST_API, TuniuCrawler  # noqa: E402


def _fare_body(n: int, base: int = 2990) -> str:
    """n 条 fare 的 listFlight 响应（每条独立航班号/价格）。"""
    fares = []
    for i in range(n):
        fares.append({
            "flightOptions": [{"flightNos": f"MU9{i:3d}"}],
            "flightPriceList": [
                {"fareBreakdownList": [{"baseFare": base + i, "psgType": "ADT"}]}
            ],
        })
    # separators 紧凑形态=真实渠道报文形态（fixture 忠实 mimic 渠道）；
    # 判据走结构化 json 解析不依赖子串形态
    return json.dumps({"success": True, "data": {"fareList": fares}},
                      ensure_ascii=False, separators=(",", ":"))


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text)


class _Cookies:
    def __init__(self):
        self._d = {}

    def set(self, k, v, domain=None, path=None):
        self._d[k] = v

    def get(self, k, default=""):
        return self._d.get(k, default)


class _FakeClient:
    """脚本化响应：listFlight 每次调用按序弹出一条 body（耗尽即抛错，
    兼作「续询越界」的失败信号）；其余 URL 返回空体。"""

    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.cookies = _Cookies()
        self.list_calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        if LIST_API in url:
            self.list_calls += 1
            return _Resp(self._bodies.pop(0))
        return _Resp("")

    def close(self):
        pass


def _run(monkeypatch, bodies):
    """挂 fake Client 与免等待，跑一次 _one_attempt。
    返回 (crawler, ok, raw, blocked, fake)。"""
    calls = {"n": 0}

    def _factory(*a, **kw):
        fake = _FakeClient(bodies)
        calls["fake"] = fake
        return fake

    monkeypatch.setattr(tn.httpx, "Client", _factory)
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    crawler = TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10},
                           logging.getLogger("t107"))
    ok, raw, blocked = crawler._one_attempt("SHA", "URC", "2026-10-08")
    return crawler, ok, raw, blocked, calls["fake"]


def test_full_first_poll_zero_extra_cost(monkeypatch):
    """健康轮（43 条）：首响即收，零额外请求（礼貌预算不回退）。"""
    _, ok, raw, _, fake = _run(monkeypatch, [_fare_body(43)])
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 43
    assert fake.list_calls == 1


def test_thin_then_full_accepts_full(monkeypatch):
    """薄样本（3 条）不早收：续询到全量（43 条）收全量。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(3), _fare_body(43)])
    assert ok
    assert len(raw["data"]["fareList"]) == 43
    assert fake.list_calls == 2


def test_all_thin_bounded_best_so_far(monkeypatch):
    """全薄（真稀疏/持续降级）：薄响应最多连看 3 个，兜底返回条数最多
    的样本，且打「疑似降级样本」警告供观测记责任周期。"""
    rec = []

    def _crawler(monkeypatch, bodies):
        def _factory(*a, **kw):
            return _FakeClient(bodies)
        monkeypatch.setattr(tn.httpx, "Client", _factory)
        monkeypatch.setattr(tn.time, "sleep", lambda s: None)
        lg = logging.getLogger("t107thin")
        monkeypatch.setattr(lg, "warning",
                            lambda m, *a: rec.append(m % a if a else m))
        return TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10}, lg)

    crawler = _crawler(monkeypatch, [_fare_body(3), _fare_body(1),
                                     _fare_body(2), _fare_body(1)])
    ok, raw, blocked = crawler._one_attempt("SHA", "URC", "2026-10-08")
    assert ok and raw is not None
    # best-so-far：3 条样本胜过后续 1/2 条
    assert len(raw["data"]["fareList"]) == 3
    assert any("疑似降级样本" in m for m in rec), rec
    # 有界性由 test_thin_bound_caps_polling 强钉（list_calls==_THIN_MAX）


def test_thin_bound_caps_polling(monkeypatch):
    """薄样本续询有界：脚本给 10 个薄响应，实际 LIST_API 恰好 3 次调用。"""
    box = {}

    def _factory(*a, **kw):
        fake = _FakeClient([_fare_body(3)] * 10)
        box["fake"] = fake
        return fake

    monkeypatch.setattr(tn.httpx, "Client", _factory)
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    crawler = TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10},
                           logging.getLogger("t107cap"))
    ok, raw, _ = crawler._one_attempt("SHA", "URC", "2026-10-08")
    assert ok and len(raw["data"]["fareList"]) == 3
    assert box["fake"].list_calls == tn._THIN_MAX


def test_legacy_price_without_farelist_still_accepted(monkeypatch):
    """历史形态（无 fareList、data.salePrice>0）保持首响即收。"""
    body = json.dumps({"success": True, "data": {"salePrice": 2990}},
                      separators=(",", ":"))
    _, ok, raw, _, fake = _run(monkeypatch, [body])
    assert ok and raw is not None
    assert fake.list_calls == 1


# ---- 门槛演进：8→20（恰卡 n=8 截断轮虚高 +6.8%~+47% 在案）→39
#（自然轮 DB 实证 16-38 非恒空，20-38 过闸段关死——过闸带
# 整体落入薄样本续询）----

def test_gap_band_goes_thin_continuation(monkeypatch):
    """n=19（旧门槛过闸带）不得首响即收：走薄样本续询，穷尽兜底并打警告。"""
    box = {}

    def _factory(*a, **kw):
        fake = _FakeClient([_fare_body(19, base=3280)] * 10)
        box["fake"] = fake
        return fake

    monkeypatch.setattr(tn.httpx, "Client", _factory)
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    lg = logging.getLogger("t108gap")
    warns = []
    monkeypatch.setattr(lg, "warning",
                        lambda m, *a: warns.append(m % a if a else m))
    crawler = TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10}, lg)
    ok, raw, _ = crawler._one_attempt("SHA", "URC", "2026-10-08")
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 19
    assert box["fake"].list_calls == tn._THIN_MAX
    assert any("疑似降级样本" in m for m in warns), warns


def test_new_floor_boundary_first_poll(monkeypatch):
    """n=20（前门槛值）翻案为薄续询：空档带实证非恒空后，
    20-38 段全带不早收（DB n=24 过闸形态在案）。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(20), _fare_body(45)])
    assert ok
    assert len(raw["data"]["fareList"]) == 45
    assert fake.list_calls == 2


# ---- 自然轮 DB 实证推翻「空档恒空」：当日 4/102 轮 n 落 16-38
#（16/27/16/24，抽检 2 轮 min/max 在场、最低价与邻域持平——真稀疏
# 与良性截断并存，但门槛 20 下 20-38 段首响即收不续询）。门槛设计
# 文档自身的哲学是「让整个过闸带落入续询面」——floor 须取健康带
# 下缘 39：健康轮（39-46）零额外请求不回退，16-38 全带续询，
# best-so-far 兜底真稀疏零丢失 ----

def test_gap_band_20_38_first_poll_not_accepted(monkeypatch):
    """n=24（生产 13:12 实测形态）不得首响即收：续询到全量收全量。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(24, base=3280),
                                _fare_body(45)])
    assert ok
    assert len(raw["data"]["fareList"]) == 45
    assert fake.list_calls == 2


def test_gap_band_all_sparse_bounded_best_so_far(monkeypatch):
    """n=27 持续（真稀疏形态）：薄样本续询 ≤3 拍兜底 best-so-far，
    零数据丢失（对账 DB 06:32 轮 min/max 在场的自然出勤）。"""
    _, ok, raw, _, fake = _run(
        monkeypatch, [_fare_body(27)] * 10)
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 27
    assert fake.list_calls == tn._THIN_MAX


def test_healthy_band_bottom_edge_first_poll(monkeypatch):
    """n=39（健康带下缘）首响即收：健康轮零额外请求不回退。"""
    _, ok, raw, _, fake = _run(monkeypatch, [_fare_body(39)])
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 39
    assert fake.list_calls == 1


def test_gap_band_upper_edge_goes_thin(monkeypatch):
    """n=38（健康带下缘之下）走薄样本续询：过闸带上缘关死。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(38, base=3280),
                                _fare_body(45)])
    assert ok
    assert len(raw["data"]["fareList"]) == 45
    assert fake.list_calls == 2
