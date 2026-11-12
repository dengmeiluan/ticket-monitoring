# -*- coding: utf-8 -*-
"""r1063 T54：端到端收尾——把这一路新加的面串成一条真 HTTP 用例。

复用 `test_r1063_e2e_rehearsal.py` 里的真 `_Srv`（起 `webui._Srv` + 临时库）。

覆盖：
1. 自动动作进**干预台账** → `/api/strategy` 的策略行能看到「干预 N 次」；
2. **判据链**（会话重建）→ `/api/pacing` 的 `channels[plat].sr`；
3. **成效账本** → `failover.history`（近 7 天）；
4. **换道判据输入** → `failover.plats[plat]` 的预算/冷却；
5. **会话重置**真的挪档案、保住我们的状态、记数；
6. **还原**能把旧档案拿回来。

这些面各有单测；这条证明它们**在同一份载荷里互不打架**。
"""
import io
import os

import pytest

from core import session_reset as sr
from core import strategy_ledger as sl

# 复用既有夹具（同一个真服务）；pytest 会把 tests/ 放进 sys.path
from test_r1063_e2e_rehearsal import srv  # noqa: F401


def test_strategy_rows_show_auto_interventions(srv):
    """自动动作写进台账后，策略行必须能读到（否则用户以为没动过）。"""
    srv.ps.save_intervention(platform="fliggy",
                             action="strategy_app_fallback", ok=True, rows=6,
                             note="[app_fallback] 换道 fliggy→app_fliggy 回采 6 条")
    code, j = srv.get("/api/strategy")
    assert code == 200 and j.get("ok"), j
    row = [s for s in j["strategies"] if s["id"] == "app_fallback"][0]
    assert int((row.get("stats") or {}).get("interventions") or 0) >= 1, row


def test_pacing_carries_chain_inputs_and_history(srv):
    srv.pac.note_sr_state("fliggy", fails=3, kind="captcha", day=1,
                          why="连续被拦 3 次")
    srv.pac.note_reset("fliggy")
    sl.record_failover(switches=2, rows=7, preloads=1, root=str(srv.user_data))
    code, j = srv.get("/api/pacing")
    assert code == 200, (code, j)
    ch = (j.get("channels") or {}).get("fliggy") or {}
    assert ch.get("resets") == 1, ch
    assert (ch.get("sr") or {}).get("fails") == 3, ch.get("sr")
    fo = j.get("failover") or {}
    assert "plats" in fo and "fliggy" in fo["plats"], list(fo)
    assert int((fo["plats"]["fliggy"] or {}).get("cap") or 0) > 0
    hist = fo.get("history") or {}
    assert int((hist.get("failover") or {}).get("switches") or 0) >= 2, hist


def test_manual_session_reset_moves_profile_and_counts(srv):
    prof = os.path.join(str(srv.user_data), "fliggy")
    os.makedirs(os.path.join(prof, "Default"), exist_ok=True)
    with io.open(os.path.join(prof, "policy_state.json"), "w",
                 encoding="utf-8") as f:
        f.write('{"k": 1}')
    code, out = srv.post("/api/session/reset", {"plat": "fliggy"})
    assert code == 200 and out.get("ok"), out
    assert os.path.isdir(prof), "新档案必须存在"
    assert not os.path.isdir(os.path.join(prof, "Default")), "新档案要是干净的"
    assert os.path.isfile(os.path.join(prof, "policy_state.json")), \
        "我们的状态文件必须跟到新档案"
    assert sr.list_backups("fliggy", str(srv.user_data)), "旧档案要留备份"
    code2, j = srv.get("/api/pacing")
    assert code2 == 200
    assert ((j.get("channels") or {}).get("fliggy") or {}).get("resets") == 1


def test_restore_after_manual_reset(srv):
    prof = os.path.join(str(srv.user_data), "ctrip")
    os.makedirs(os.path.join(prof, "Default"), exist_ok=True)
    _code, out = srv.post("/api/session/reset", {"plat": "ctrip"})
    assert out.get("ok"), out
    name = out["result"]["backup"]
    code, got = srv.post("/api/session/restore",
                         {"plat": "ctrip", "name": name})
    assert code == 200 and got.get("ok"), got
    assert os.path.isdir(os.path.join(prof, "Default")), "旧档案内容应回来"
