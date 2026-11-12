# -*- coding: utf-8 -*-
"""r1063 T18：人工停手下沉到维度/链路（只停这一条，不连坐同渠道其它通路）。

目标要求「每个渠道每个维度每个链路都可干预/可中断」。此前停手只有渠道级：
`set_halt(profile_dir, plat, minutes)` 写一个裸渠道键，`decide()` 命中即整家
`blocked`。结果是想停「飞猪 PC」只能停整家飞猪。

这里补齐三件：
  1. `core/policy.py`：停手键支持作用域（`plat/<维度>`、`plat/<维度>/<链路>`），
     渠道级键形状不变（历史文件照旧读得懂）；新增 `halt_for()` 三级查找；
  2. `core/pacing.py`：`gate_path()` 先查停手（人按下的优先于一切自动策略），
     读点由调用方注入，模块本身不碰磁盘；
  3. 行为：链路级停手只拒这一条，同维度其它链路照常放行。
"""
import os
import tempfile
import time

import pytest

from core import policy
from core.pacing import PATH_HALTED, Pacing


@pytest.fixture()
def prof():
    return tempfile.mkdtemp()


# ---------------- 键与查找 ----------------

def test_halt_key_shapes_stay_backward_compatible():
    assert policy.halt_key("ctrip") == "ctrip"                  # 渠道级不变
    assert policy.halt_key("ctrip", "") == "ctrip"
    assert policy.halt_key("ctrip", "intl") == "ctrip/intl"
    assert policy.halt_key("ctrip", "detail/H5/API") == "ctrip/detail/H5/API"
    assert policy.halt_key("ctrip", "/intl/") == "ctrip/intl"


def test_halt_for_prefers_path_then_dim_then_channel():
    halts = {
        "ctrip": {"until": time.time() + 600},
        "ctrip/intl": {"until": time.time() + 600},
        "ctrip/intl/H5": {"until": time.time() + 600},
    }
    k, _ = policy.halt_for(halts, "ctrip", "intl", "H5")
    assert k == "ctrip/intl/H5"
    k, _ = policy.halt_for(halts, "ctrip", "intl", "PC")
    assert k == "ctrip/intl"          # 链路没命中 → 维度
    k, _ = policy.halt_for(halts, "ctrip", "domestic", "PC")
    assert k == "ctrip"               # 维度没命中 → 渠道
    k, _ = policy.halt_for(halts, "qunar", "domestic", "PC")
    assert k == ""                    # 完全没停手


def test_expired_halt_is_not_a_halt():
    halts = {"ctrip": {"until": time.time() - 1}}
    assert policy.halt_for(halts, "ctrip") == ("", {})


# ---------------- 写盘与撤销 ----------------

def test_set_and_clear_halt_by_scope(prof):
    rec = policy.set_halt(prof, "ctrip", 15, note="手停 H5", scope="detail/H5/API")
    assert rec is not False, "写盘失败被当成成功"
    assert "ctrip/detail/H5/API" in rec
    # 记录形状仍是 `{until, note}`（既有契约），作用域由**键**表达
    assert set(rec["ctrip/detail/H5/API"]) == {"until", "note"}
    # 渠道级不受影响
    assert policy.halt_for(policy.read_halt(prof), "ctrip", "detail", "PC") == ("", {})
    assert policy.clear_halt(prof, "ctrip", scope="detail/H5/API") is True
    assert "ctrip/detail/H5/API" not in policy.read_halt(prof)


def test_channel_level_halt_still_writes_plain_key(prof):
    rec = policy.set_halt(prof, "ctrip", 15)
    assert "ctrip" in rec and all("/" not in k for k in rec), rec


# ---------------- 决策面：只停那一条 ----------------

def _pac(prof):
    pac = Pacing({})
    halts = policy.read_halt(prof)
    pac.set_halt_reader(lambda p, d, pa: policy.halt_for(halts, p, d, pa))
    return pac


def test_path_halt_blocks_only_that_link(prof):
    policy.set_halt(prof, "ctrip", 15, scope="detail/H5/API")
    pac = _pac(prof)
    allow, wait, why = pac.gate_path("ctrip", "detail", "H5/API")
    assert allow is False and PATH_HALTED in why, why
    allow2, _w2, _y2 = pac.gate_path("ctrip", "detail", "PC")
    assert allow2 is True, "同维度另一条链路被连坐"


def test_dimension_halt_blocks_all_links_of_that_dimension(prof):
    policy.set_halt(prof, "ctrip", 15, scope="intl")
    pac = _pac(prof)
    assert pac.gate_path("ctrip", "intl", "H5")[0] is False
    assert pac.gate_path("ctrip", "intl", "PC")[0] is False
    assert pac.gate_path("ctrip", "domestic", "PC")[0] is True


def test_no_reader_means_no_halt(prof):
    """没注入读点的实例照常放行（单测/离线路径不能被停手逻辑拖死）。"""
    policy.set_halt(prof, "ctrip", 15)
    pac = Pacing({})
    assert pac.gate_path("ctrip", "detail", "PC")[0] is True


def test_expired_halt_unblocks(prof):
    policy.set_halt(prof, "ctrip", 1, scope="detail/PC")
    path = policy.halt_path(prof)
    import json
    d = json.load(open(path, encoding="utf-8"))
    d["ctrip/detail/PC"]["until"] = time.time() - 5
    json.dump(d, open(path, "w", encoding="utf-8"))
    policy._HALT_CACHE.pop(path, None)
    pac = _pac(prof)
    assert pac.gate_path("ctrip", "detail", "PC")[0] is True


# ---------------- 接口面：/api/strategy/halt|resume 认 scope ----------------

def test_halt_api_accepts_scope_and_rejects_unknown_dimension(tmp_path,
                                                             monkeypatch):
    import webui

    base = str(tmp_path / "profile")
    os.makedirs(base, exist_ok=True)

    class _Eng:
        base_dir = base

    monkeypatch.setattr(webui, "_policy_engine", lambda plat="": _Eng(),
                        raising=False)
    monkeypatch.setattr(webui, "_strategy_ledger",
                        lambda *a, **k: True, raising=False)
    monkeypatch.setattr(webui, "_ledger_tail",
                        lambda out, ok, act: out, raising=False)

    code, out = webui._strategy_halt_api(
        {"plat": "ctrip", "minutes": 15, "scope": "detail/H5/API"})
    assert code == 200 and out.get("ok") is True, out
    assert out.get("scope") == "detail/H5/API"
    assert out.get("key") == "ctrip/detail/H5/API"
    assert out.get("until", 0) > time.time()
    halts = policy.read_halt(base)
    assert "ctrip/detail/H5/API" in halts

    # 拼错的维度：必须 400，不许写一条查不到的停手
    code2, out2 = webui._strategy_halt_api(
        {"plat": "ctrip", "minutes": 15, "scope": "detailx/H5"})
    assert code2 == 400 and "未知维度" in out2.get("err", ""), out2
    assert list(policy.read_halt(base)) == ["ctrip/detail/H5/API"]

    # 恢复同一个作用域
    code3, out3 = webui._strategy_resume_api(
        {"plat": "ctrip", "scope": "detail/H5/API"})
    assert code3 == 200 and out3.get("cleared") is True, out3
    assert "ctrip/detail/H5/API" not in policy.read_halt(base)


def test_halt_api_channel_level_unchanged(tmp_path, monkeypatch):
    """渠道级仍写裸渠道键（历史文件与既有门禁的形状不许变）。"""
    import webui

    base = str(tmp_path / "p2")
    os.makedirs(base, exist_ok=True)

    class _Eng:
        base_dir = base

    monkeypatch.setattr(webui, "_policy_engine", lambda plat="": _Eng(),
                        raising=False)
    monkeypatch.setattr(webui, "_strategy_ledger",
                        lambda *a, **k: True, raising=False)
    monkeypatch.setattr(webui, "_ledger_tail",
                        lambda out, ok, act: out, raising=False)
    code, out = webui._strategy_halt_api({"plat": "ctrip", "minutes": 15})
    assert code == 200 and out.get("key") == "ctrip", out
    assert "ctrip" in policy.read_halt(base)


def test_profile_of_is_single_source():
    """`webui._profile_of` 必须与 `core.policy.profile_of` 同源（不各写一份）。"""
    import io
    import webui

    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    seg = src[src.index("def _profile_of(plat):"):]
    seg = seg[:1200]
    assert "profile_of" in seg and "core.policy" in seg, seg[:200]
    assert webui._profile_of("fliggy") == policy.profile_of("fliggy")


def test_panel_can_stop_a_single_link():
    """面板必须能只停一条链路（否则「链路级停手」只有接口、没有可视化）。"""
    import io

    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    # 作用域下拉存在，且选项由快照现填（不写死维度名）
    assert "function stratScopeFill(" in src
    assert "select.ssel2" in src or "ssel ssel2" in src
    assert "渠道整家" in src
    # 停手请求带 scope
    assert "scope:scope" in src, "stratHalt 没把作用域发给接口"
    # 作用域级停手在停手表里可见（否则用户看不见自己停过哪条）
    assert 'out["halt_scopes"]' in src
    assert "STRATPAY.halt_scopes" in src
