# -*- coding: utf-8 -*-
r"""r1063 T6：停手/恢复/中断接口 + 台账第三族分界。

本文件钉五件事：

1. **台账第三族**：`strategy_*` 是「策略变更」，既不是人工干预（`probe`/
   `relogin`/`reset`…），也不是自动事件（`auto_*`）。它**不许**去当
   `intervention_effect()` 的「最近一次人工干预」分界，也**不许**进
   `intervention_success_rate()` 的成功率分母——一次「把开关关掉」被算成
   「人工救过一次、没救回来」，面板给的按钮优先级就全错了。
2. **三个接口接上线**：`/api/strategy/halt`、`/api/strategy/resume`、
   `/api/round/abort`，且都写自己的台账行。
3. **`set_halt(minutes=0)` 的成功不是失败**（复核遗留陷阱 A）：那条路径
   `set_halt` 返回的是**合法但为空**的停手表 `{}`，路由若按 `if not rec:`
   判失败，就会把「立即失效」这个正常操作报成 500。
4. **坏 `strategy_halt.json` 只喊一次**（陷阱 B）：缓存的只是文件 IO，
   告警原来跟着 `decide()` 每次喊——每分钟一条 warning 把日志淹掉，
   比不喊更糟。文件一改（签名变）必须重新喊。
5. **整份文件读不懂不许静默**（陷阱 C）：`_load()` 原来对「文件不存在」与
   「文件读不懂」一律回 `{}`——手改坏的 `strategy_halt.json` 让「人工停手」
   凭空消失、全链路无痕。`policy_state.json` 仍然「从空开始」继续跑，
   但也要留一条痕，而**正常启动（文件不存在）不许变成 warning**。
6. **停手必须落在采集器真正读的目录**（复核 Critical）：`PolicyEngine.base_dir`
   带 profile，而每条爬虫都带非空 profile（`profile_name or name`）。
   本文件的门禁用**真实** `crawlers.REGISTRY[plat]` 实例对账，不用桩。
7. **去重键要带原因标签**（复核 Important 1）：同一份坏文件下，「读不懂」与
   「本次写入会覆盖它」是两件不同的事，各报一次。
8. **`reset_auto` 失败不许静默**（复核 Important 2）：它自己吞异常，所以必须
   返回 bool，`/api/pacing/reset` 据此回报并留台账。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_strategy_ledger_class.py -q
"""
import io
import json
import logging
import os
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 1. 台账第三族：`strategy_*` 不算人工干预
# ---------------------------------------------------------------------------
def test_strategy_actions_do_not_pollute_manual_intervention_effect(tmp_path):
    from core.storage import PriceStorage
    ps = PriceStorage(str(tmp_path / "t.db"))
    ps.save_intervention("ctrip", "probe", ok=True, rows=5)
    ps.save_intervention("ctrip", "strategy_toggle", ok=True,
                         before="on", after="off", note="[breaker_switch] 关")
    eff = ps.intervention_effect("ctrip", 24)
    assert eff.get("action") == "probe", "策略变更顶掉了人工干预分界"


def test_strategy_actions_are_excluded_from_success_rate(tmp_path):
    from core.storage import PriceStorage
    ps = PriceStorage(str(tmp_path / "t.db"))
    ps.save_intervention("ctrip", "warmup", ok=True)
    for _ in range(5):
        ps.save_intervention("ctrip", "strategy_set", ok=False)
    rate = ps.intervention_success_rate()
    # `intervention_success_rate()` 回的是 `{动作: 统计}`（r506 起如此），
    # 所以「有没有进结果」就是键在不在——brief 里写的 `for r in rate`
    # 是按列表写的，按真实返回形状落成键判定，判据一字不变。
    rows = rate if isinstance(rate, dict) else {r["action"]: r for r in rate}
    assert "strategy_set" not in rows, rows
    assert "warmup" in rows, "把人工族也一起筛掉了：%r" % (rows,)


def test_strategy_halt_row_does_not_become_the_manual_boundary(tmp_path):
    """`strategy_halt` 自己（T6 写的账）同样不许当人工分界。"""
    from core.storage import PriceStorage
    ps = PriceStorage(str(tmp_path / "t.db"))
    ps.save_intervention("ctrip", "reset", ok=True)
    ps.save_intervention("ctrip", "strategy_halt", ok=True,
                         scope="ctrip", note="[ctrip] 人工停手 5 分钟")
    eff = ps.intervention_effect("ctrip", 24)
    assert eff.get("action") == "reset", eff
    assert "strategy_halt" not in ps.intervention_success_rate()


def test_halt_route_is_wired_and_ledgered():
    import io as _io
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    w = _io.open(_os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert '"/api/strategy/halt"' in w and '"/api/strategy/resume"' in w
    assert '"strategy_halt"' in w
    assert '"/api/round/abort"' in w


# ---------------------------------------------------------------------------
# 公共替身：把「策略引擎 / 干预账本」两处落盘接到 tmp，别碰真 user_data
# ---------------------------------------------------------------------------
def _engine(tmp_path, profile="ctrip"):
    from core.policy import PolicyEngine
    return PolicyEngine({}, repo_root=str(tmp_path), profile=profile)


@pytest.fixture
def web(tmp_path, monkeypatch):
    """`webui` + 两个被替换的落盘点（引擎、账本）。"""
    import webui
    from core.storage import PriceStorage
    eng = _engine(tmp_path)
    ps = PriceStorage(str(tmp_path / "t.db"))
    # 引擎替身必须接受 `plat`（真实实现按渠道推导 profile 目录）
    monkeypatch.setattr(webui, "_policy_engine", lambda plat="": eng,
                        raising=False)
    monkeypatch.setattr(webui, "_strategy_storage", lambda: ps, raising=False)
    return webui, eng, ps


def _crawler_engine(inst):
    """采集器**自己**的那个策略引擎（浏览器基类叫 `_policy`，App 基类叫 `_policy_engine`）。"""
    for name in ("_policy", "_policy_engine"):
        fn = getattr(inst, name, None)
        if callable(fn):
            return fn()
    raise AssertionError("采集器没有策略引擎入口：%r" % (inst,))


def _iv_rows(ps):
    with ps._conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT platform, action, ok, rows, scope, before, after, note "
            "FROM interventions ORDER BY id").fetchall()]


# ---------------------------------------------------------------------------
# 1b. Critical：停手必须落到**采集器决策时读的那个目录**
# ---------------------------------------------------------------------------
def test_halt_lands_in_the_directory_the_crawler_actually_reads(tmp_path,
                                                               monkeypatch):
    """用真实 `crawlers.REGISTRY[plat]` 实例对账：停手目录 == 决策目录。

    为什么必须用真实例（复核 2026-11-06 Critical）：`PolicyEngine.base_dir`
    = `repo_root/user_data_root(cfg)/profile`，而每条爬虫都带**非空** profile
    （`profile_name or name`）。少了 `profile`，停手会写进 `user_data/`，
    而采集器读的是 `user_data/<profile>/`——界面报「已停手」而采集照跑，
    正是本任务要防的头号缺陷。用 `_policy_engine` 的桩自证会绕过这一层。
    """
    import logging as _logging

    from crawlers import REGISTRY

    import webui
    from core.policy import read_halt
    ud = tmp_path / "ud"
    cfg = {"crawler": {"user_data_dir": str(ud)},
           "output": {"db_path": str(tmp_path / "t.db")}}
    monkeypatch.setattr(webui._State, "cfg", cfg, raising=False)
    monkeypatch.setenv("TM_USER_DATA_DIR", str(ud))
    for plat, want in (("fliggy", "fliggy"), ("app_qunar", "app_qunar")):
        # 生产形态：main.py 把 user_data_dir 注进 crawler 段再喂给爬虫
        inst = REGISTRY[plat]({"user_data_dir": str(ud)},
                              _logging.getLogger("r1063t6"))
        got = webui._policy_engine(plat).base_dir
        assert got == _crawler_engine(inst).base_dir, (
            "停手目录与采集器决策目录不是同一个：%s vs %s"
            % (got, _crawler_engine(inst).base_dir))
        assert os.path.basename(got) == want, got
        code, out = webui._strategy_halt_api({"plat": plat, "minutes": 5})
        assert code == 200, out
        assert os.path.isfile(os.path.join(got, "strategy_halt.json")), (
            "停手文件没落在决策目录里：%s" % got)
        assert plat in read_halt(got)
        # 端到端：采集器自己的引擎读到这条停手 → 不放行
        assert _crawler_engine(inst).decide(inst.name,
                                            two_way=True).allow is False


def test_profile_resolution_follows_profile_name_override(tmp_path, monkeypatch):
    """按 `profile_name or name` 走，**不许**图省事写 `profile=plat`。

    `crawlers/fliggy_h5.py::FliggyH5Crawler` 就是反例：`name="fliggy"`、
    `profile_name="fliggy_h5"`。把它挂到一个临时渠道 id 上，就能看出解析器
    读的是类属性还是 plat 字面量。
    """
    import webui
    from crawlers import REGISTRY
    from crawlers.fliggy_h5 import FliggyH5Crawler
    monkeypatch.setattr(webui._State, "cfg", {}, raising=False)
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setitem(REGISTRY, "fake_plat", FliggyH5Crawler)
    assert webui._profile_of("fake_plat") == "fliggy_h5", "没按 profile_name 覆盖走"
    assert os.path.basename(webui._policy_engine("fake_plat").base_dir) == \
        "fliggy_h5"
    # 真实注册表里的两条口径
    assert webui._profile_of("fliggy") == "fliggy"
    assert webui._profile_of("app_qunar") == "app_qunar"
    # 未注册/空值回落
    assert webui._profile_of("不存在的渠道") == "不存在的渠道"
    assert webui._profile_of("") == ""



# ---------------------------------------------------------------------------
# 2. 停手接口
# ---------------------------------------------------------------------------
def test_halt_zero_minutes_success_is_not_failure(web):
    """陷阱 A：`minutes=0` 写盘成功返回的 `{}` 是**合法**的「立即失效」。"""
    web_mod, eng, ps = web
    code, out = web_mod._strategy_halt_api({"plat": "ctrip", "minutes": 0,
                                            "note": "点了就撤"})
    assert code == 200, out
    assert out.get("ok") is True and out.get("plat") == "ctrip"
    assert out.get("until") == 0.0, out
    rows = _iv_rows(ps)
    assert [r["action"] for r in rows] == ["strategy_halt"], rows
    assert rows[0]["note"].startswith("[ctrip]"), rows[0]["note"]
    assert rows[0]["scope"] == "ctrip", "scope 必须留在渠道词汇里，不许 strategy:<id>"


def test_halt_route_writes_a_halt_that_the_policy_layer_sees(web):
    """接口落盘 → 策略层真的读到（否则界面报「已停手」而采集照跑）。"""
    from core.policy import read_halt
    web_mod, eng, ps = web
    code, out = web_mod._strategy_halt_api(
        {"plat": "ctrip", "minutes": 30, "note": "人工核查"})
    assert code == 200, out
    assert out["until"] > time.time() + 29 * 60
    got = read_halt(eng.base_dir)
    assert "ctrip" in got and got["ctrip"]["note"] == "人工核查"
    assert eng.decide("ctrip", two_way=True).allow is False


def test_halt_write_failure_is_500_not_a_false_success(web, monkeypatch):
    """写盘失败必须报错：界面显示「已停手」而磁盘上什么都没发生是头号缺陷。"""
    from core import policy
    web_mod, eng, ps = web
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    code, out = web_mod._strategy_halt_api({"plat": "ctrip", "minutes": 5})
    assert code == 500, out
    assert out.get("ok") is False
    assert "停手" in out.get("err", "") and "落盘" in out.get("err", ""), out
    assert [r["action"] for r in _iv_rows(ps)] == ["strategy_halt"]
    assert _iv_rows(ps)[0]["ok"] == 0, "写盘失败却记成成功"


def test_halt_route_tolerates_missing_and_broken_body(web):
    """没有 body / 缺字段 / 分钟数写坏：中文 400，绝不出 500 堆栈。"""
    web_mod, _eng, _ps = web
    for payload in (None, {}, {"minutes": 5}, {"plat": "ctrip"},
                    {"plat": "ctrip", "minutes": "五分钟"},
                    {"plat": "ctrip", "minutes": float("inf")},
                    {"plat": "不存在", "minutes": 5}):
        code, out = web_mod._strategy_halt_api(payload)
        assert code == 400, (payload, code, out)
        assert out.get("ok") is False and out.get("err"), (payload, out)
        assert any("\u4e00" <= ch <= "\u9fff" for ch in out["err"]), out


# ---------------------------------------------------------------------------
# 3. 恢复接口
# ---------------------------------------------------------------------------
def test_resume_route_clears_halt_and_ledgers(web):
    from core.policy import read_halt, set_halt
    web_mod, eng, ps = web
    set_halt(eng.base_dir, "ctrip", 30, "人工核查")
    code, out = web_mod._strategy_resume_api({"plat": "ctrip"})
    assert code == 200, out
    assert out.get("ok") is True and out.get("cleared") is True, out
    assert read_halt(eng.base_dir) == {}
    rows = _iv_rows(ps)
    assert [r["action"] for r in rows] == ["strategy_resume"], rows
    assert rows[0]["note"].startswith("[ctrip]"), rows[0]["note"]


def test_resume_write_failure_is_500_and_the_halt_stays(web, monkeypatch):
    from core import policy
    from core.policy import read_halt, set_halt
    web_mod, eng, _ps = web
    set_halt(eng.base_dir, "ctrip", 30, "人工核查")
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    code, out = web_mod._strategy_resume_api({"plat": "ctrip"})
    assert code == 500, out
    assert "恢复" in out.get("err", ""), out
    assert "ctrip" in read_halt(eng.base_dir), "报失败却把停手删了"


def test_resume_without_halt_is_idempotent_not_an_error(web):
    """本来就没有停手 = 目的已经达到，回 200（不是 500）。"""
    web_mod, _eng, ps = web
    code, out = web_mod._strategy_resume_api({"plat": "ctrip"})
    assert code == 200, out
    assert out.get("ok") is True and out.get("cleared") is False, out
    assert _iv_rows(ps) == [], "什么都没改还写了一条痕迹"


def test_resume_tolerates_missing_body(web):
    web_mod, _eng, _ps = web
    for payload in (None, {}, {"plat": "  "}):
        code, out = web_mod._strategy_resume_api(payload)
        assert code == 400 and out.get("err"), (payload, code, out)


# ---------------------------------------------------------------------------
# 4. 中断本轮（复用 `rt["_round_gen"]` 代际）
# ---------------------------------------------------------------------------
def test_round_abort_bumps_the_generation_counter(web, monkeypatch):
    web_mod, _eng, ps = web
    rt = {"_round_gen": 7, "cfg": {}, "users": []}
    monkeypatch.setattr(web_mod._State, "rt", rt, raising=False)
    code, out = web_mod._round_abort_api({})
    assert code == 200, out
    assert rt["_round_gen"] == 8, "本轮代际没递增，worker 不会在检查点收工"
    assert out.get("gen") == 8
    rows = _iv_rows(ps)
    assert [r["action"] for r in rows] == ["strategy_abort"], rows
    # 没有指定渠道的中断也要能按平台聚合：platform="*"、scope 留空（动作级）
    assert rows[0]["platform"] == "*", rows[0]
    assert rows[0]["scope"] == "", rows[0]
    assert "中断本轮" in rows[0]["note"], rows[0]["note"]


def test_round_abort_rejects_unknown_platform(web, monkeypatch):
    """给了渠道就校验（与 halt/resume 同口径），别把台账写成野渠道。"""
    web_mod, _eng, ps = web
    rt = {"_round_gen": 0}
    monkeypatch.setattr(web_mod._State, "rt", rt, raising=False)
    code, out = web_mod._round_abort_api({"plat": "不存在的渠道"})
    assert code == 400 and out.get("err"), (code, out)
    assert rt["_round_gen"] == 0, "参数不对却也把本轮代际推进了"
    assert _iv_rows(ps) == []


def test_round_abort_without_runtime_fails_loudly(web, monkeypatch):
    """运行时没挂接时不许假装中断成功（那样操作员会以为已经停了）。"""
    web_mod, _eng, _ps = web
    monkeypatch.setattr(web_mod._State, "rt", None, raising=False)
    monkeypatch.setattr(web_mod, "_runtime_rt", lambda: None, raising=False)
    code, out = web_mod._round_abort_api(None)
    assert code == 503 and out.get("ok") is False and out.get("err"), out


def test_runtime_rt_is_reachable_through_the_job_closure(web, monkeypatch):
    """没挂 `_State.rt` 时也要能摸到 `rt`：`job` → `sweep` 的闭包里有它。

    这是「中断真的能中断」的最后一环：main.py 不接线，代际仍必须能递增。
    """
    web_mod, _eng, _ps = web
    monkeypatch.setattr(web_mod._State, "rt", None, raising=False)
    monkeypatch.setattr(web_mod._State, "probe_cb", None, raising=False)
    monkeypatch.setattr(web_mod._State, "warm_cb", None, raising=False)
    monkeypatch.setattr(web_mod._State, "login_saved_cb", None, raising=False)
    monkeypatch.setattr(web_mod._State, "reload_cb", None, raising=False)
    rt = {"cfg": {}, "users": []}

    def sweep(force=False):          # 与 main.py 的 sweep 同形：闭包里有 rt
        return rt.get("_round_gen") if force else None

    monkeypatch.setattr(web_mod._State, "job", lambda: sweep(force=True),
                        raising=False)
    assert web_mod._runtime_rt() is rt, "闭包查找没找到运行时容器"
    code, out = web_mod._round_abort_api({})
    assert code == 200 and rt.get("_round_gen") == 1, (code, out, rt)


# ---------------------------------------------------------------------------
# 5. 陷阱 B：坏停手文件的告警按「文件签名」去重
# ---------------------------------------------------------------------------
def _halt_file(eng):
    from core import policy
    os.makedirs(eng.base_dir, exist_ok=True)
    return os.path.join(eng.base_dir, policy.HALT_FILE)


def test_malformed_halt_record_warns_once_per_file_change(tmp_path, caplog):
    eng = _engine(tmp_path)
    path = _halt_file(eng)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"until": "明天", "note": "人工"}}, f,
                  ensure_ascii=False)
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        p = None
        for _ in range(5):
            p = eng.decide("ctrip", two_way=True)
    # 决定本身每次都带说明（面板要看），但**日志只喊一次**
    assert any("读不懂" in r for r in p.reasons), p.reasons
    msgs = [r.getMessage() for r in caplog.records if "读不懂" in r.getMessage()]
    assert len(msgs) == 1, "坏文件告警跟着每次 decide 刷屏了：%d 条" % len(msgs)
    # 文件一改（签名变）必须重新吭声，否则改坏了也没人知道
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"until": "后天", "note": "人工改过一次"}}, f,
                  ensure_ascii=False)
    stamp = time.time() + 30
    os.utime(path, (stamp, stamp))
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        eng.decide("ctrip", two_way=True)
    msgs = [r.getMessage() for r in caplog.records if "读不懂" in r.getMessage()]
    assert len(msgs) == 2, "文件改过却不再吭声：%d 条" % len(msgs)


# ---------------------------------------------------------------------------
# 6. 陷阱 C：整份文件读不懂 ≠ 文件不存在
# ---------------------------------------------------------------------------
def test_unreadable_halt_file_surfaces_as_a_bad_record(tmp_path, caplog):
    """半个 JSON 的 `strategy_halt.json` 不许静默变成「没有停手」。"""
    from core import policy
    eng = _engine(tmp_path)
    path = _halt_file(eng)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"ctrip": {"until": 17')
    good, bad = policy.read_halt_ex(eng.base_dir)
    assert good == {}
    assert bad and bad[0]["plat"] == "*", bad
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        p = eng.decide("ctrip", two_way=True)
    assert p.allow is True                       # 读不懂 → 按「未停手」（不炸闸门）
    assert any("读不懂" in r and "整份文件" in r for r in p.reasons), p.reasons
    msgs = [r.getMessage() for r in caplog.records if "读不懂" in r.getMessage()]
    assert len(msgs) == 1, msgs


def test_overwrite_warning_is_not_swallowed_by_the_read_warning(tmp_path,
                                                               caplog):
    """去重键必须带**原因标签**（复核 2026-11-06 Important 1）。

    停手路由的次序是「先读一次（报读不懂）→ 再写（写之前会覆盖掉坏文件）」。
    去重只按下 `(path, sig)` 时，第二句更要紧的「本次写入会覆盖该文件、
    其它渠道的停手一并丢失」**每次都被吞掉**——读者只看到「读不懂」，
    永远不知道自己那一下把别人的停手抹了。
    """
    from core import policy
    eng = _engine(tmp_path)
    path = _halt_file(eng)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"qunar": {"until": 123, "note": "人的"')      # 半个 JSON
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        policy.read_halt(eng.base_dir)                        # 第一句：读不懂
        rec = policy.set_halt(eng.base_dir, "ctrip", 5, "人工核查")
    assert isinstance(rec, dict) and "ctrip" in rec
    msgs = [r.getMessage() for r in caplog.records]
    assert any("读不懂" in m for m in msgs), msgs
    assert any("覆盖" in m for m in msgs), (
        "覆盖告警被读告警的去重键吞掉了：%r" % (msgs,))
    # 事实核对：旧内容确实被这一笔换掉了（所以那句告警不是多余的话）
    assert "qunar" not in policy.read_halt(eng.base_dir)


def test_clear_warning_is_not_swallowed_either(tmp_path, caplog):
    from core import policy
    eng = _engine(tmp_path)
    path = _halt_file(eng)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"ctrip": {"until": ')                       # 半个 JSON
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        policy.read_halt(eng.base_dir)
        ok = policy.clear_halt(eng.base_dir, "ctrip")
    assert ok is False, "读不懂的文件却报「已恢复」"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("无法撤销" in m for m in msgs), msgs


def test_missing_halt_file_is_not_a_warning(tmp_path, caplog):
    """正常启动（文件不存在）不许变成 warning——那就成了狼来了。"""
    eng = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        p = eng.decide("ctrip", two_way=True)
    assert p.allow is True
    assert not [r for r in caplog.records if "strategy_halt.json" in
                r.getMessage()]


def test_unreadable_policy_state_starts_empty_with_one_warning(tmp_path,
                                                              caplog):
    """`policy_state.json` 读不懂：从空开始跑，但留一条痕，且只留一条。"""
    eng = _engine(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    with open(eng.state_path, "w", encoding="utf-8") as f:
        f.write('{"ctrip": {"state": "bloc')
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        p = None
        for _ in range(3):
            p = eng.decide("ctrip", two_way=True)
    assert p.allow is True and p.state == "healthy"
    msgs = [r.getMessage() for r in caplog.records
            if "policy_state.json" in r.getMessage()]
    assert len(msgs) == 1, "坏状态文件告警刷屏（%d 条）或一声不吭" % len(msgs)


# ---------------------------------------------------------------------------
# 7. 解除自动熔断 ≠ 恢复人工停手（Important 2：失败不许静默）
# ---------------------------------------------------------------------------
def test_pacing_reset_clears_auto_state_only():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = w.index('elif self.path == "/api/pacing/reset":')
    j = w.index('elif self.path ==', i + 10)
    seg = w[i:j]
    assert "_auto_reset" in seg, "「解除自动熔断」没有清策略层的自动状态机"
    assert "clear_halt" not in seg, "解除自动熔断顺手解了人工停手"
    # `_auto_reset` 本体：只碰 reset_auto，绝不碰 halt
    k = w.index("def _auto_reset(")
    body = w[k:w.index("\ndef ", k + 10)]
    assert "reset_auto" in body
    assert "clear_halt" not in body and "set_halt" not in body


def test_reset_auto_reports_write_failure(tmp_path, monkeypatch, caplog):
    """`reset_auto` 自己吞掉异常 -> 调用方永远看不到失败（Important 2）。"""
    from core import policy
    eng = _engine(tmp_path)
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        ok = eng.reset_auto("ctrip")
    assert ok is False, "写盘失败却返回成功：界面会报「已解除」而策略层还在拦"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("没能落盘" in m for m in msgs), msgs


def test_reset_auto_reports_success(tmp_path):
    from core.policy import PolicyEngine
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    assert eng.reset_auto("ctrip") is True


def test_auto_reset_surfaces_failure_to_the_pacing_reset_route(web, monkeypatch):
    """`/api/pacing/reset` 要按 `reset_auto` 的结果回报，并留一条台账。"""
    web_mod, _eng, ps = web
    from core import policy
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    ok, err, led = web_mod._auto_reset("ctrip")
    assert ok is False
    assert err and any("\u4e00" <= ch <= "\u9fff" for ch in err), err
    assert "策略层" in err, err
    assert led is True, led
    rows = _iv_rows(ps)
    assert [r["action"] for r in rows] == ["strategy_auto_reset"], rows
    assert rows[0]["ok"] == 0, rows[0]
    assert rows[0]["platform"] == "ctrip" and rows[0]["scope"] == "ctrip"


def test_auto_reset_success_is_ledgered(web):
    web_mod, _eng, ps = web
    ok, err, led = web_mod._auto_reset("ctrip")
    assert (ok, err, led) == (True, "", True)
    rows = _iv_rows(ps)
    assert [r["action"] for r in rows] == ["strategy_auto_reset"], rows
    assert rows[0]["ok"] == 1


class _FakePostHandler:
    """够 `_do_POST` 跑一个分支的最小替身（只实现它真正用到的那几个面）。"""

    def __init__(self, path, body):
        raw = json.dumps(body).encode("utf-8")
        self.path = path
        self.command = "POST"
        self.headers = {"Content-Length": str(len(raw)),
                        "Content-Type": "application/json"}
        self.rfile = io.BytesIO(raw)
        self.sent = []

    def _json(self, obj, code=200):
        self.sent.append((code, obj))

    def _json_body_ok(self):
        return True

    def _post_json(self, label="请求", max_len=16384):
        """照 `_Handler._post_json` 的契约：读体、回 dict（不吃 rfile 两遍）。"""
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n)
        self.rfile = io.BytesIO(raw)
        return json.loads(raw or b"{}")


class _FakePacing:
    def reset(self, plat):
        return True

    def snapshot(self):
        return {"channels": {}}

    def observe(self, *a, **k):
        return None


def test_pacing_reset_route_reports_policy_failure(web, monkeypatch):
    """/api/pacing/reset 在策略层清不掉时必须回 500（不许说「已解除」）。"""
    web_mod, _eng, ps = web
    from core import policy
    monkeypatch.setattr(web_mod._State, "pacing", _FakePacing(), raising=False)
    monkeypatch.setattr(web_mod._State, "probe_cb", None, raising=False)
    monkeypatch.setattr(web_mod._State, "reset_open", set(), raising=False)
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    h = _FakePostHandler("/api/pacing/reset", {"platform": "ctrip"})
    web_mod._Handler._do_POST(h)
    code, out = h.sent[-1]
    assert code == 500 and out.get("ok") is False, (code, out)
    assert "策略层" in out.get("err", ""), out
    assert out.get("policy_reset") is False, out
    assert "ctrip" not in web_mod._State.reset_open, (
        "失败提前返回时没释放 reset_open：下一次解除会被 409 挡住")
    assert [r["action"] for r in _iv_rows(ps)] == ["strategy_auto_reset"]


def test_pacing_reset_route_succeeds_and_releases_the_gate(web, monkeypatch,
                                                           tmp_path):
    web_mod, _eng, ps = web
    monkeypatch.setattr(web_mod._State, "pacing", _FakePacing(), raising=False)
    monkeypatch.setattr(web_mod._State, "probe_cb", None, raising=False)
    monkeypatch.setattr(web_mod._State, "reset_open", set(), raising=False)
    monkeypatch.setattr(web_mod._State, "cfg",
                        {"output": {"db_path": str(tmp_path / "x.db")}},
                        raising=False)
    h = _FakePostHandler("/api/pacing/reset", {"platform": "ctrip"})
    web_mod._Handler._do_POST(h)
    code, out = h.sent[-1]
    assert code == 200 and out.get("ok") is True, (code, out)
    assert out.get("policy_reset") is True, out
    assert "ctrip" not in web_mod._State.reset_open
    assert [r["action"] for r in _iv_rows(ps)] == ["strategy_auto_reset"]


# ---------------------------------------------------------------------------
# 8. 台账写失败必须让界面看得出来（不许装没事）
# ---------------------------------------------------------------------------
def test_ledger_write_failure_is_surfaced_on_the_halt_route(web, monkeypatch):
    web_mod, eng, _ps = web

    def _boom():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(web_mod, "_strategy_storage", _boom, raising=False)
    code, out = web_mod._strategy_halt_api({"plat": "ctrip", "minutes": 5})
    assert code == 200 and out.get("ok") is True, out   # 停手本身已经落盘
    assert out.get("ledger") is False, out
    assert "台账" in (out.get("warn") or ""), out
    from core.policy import read_halt
    assert "ctrip" in read_halt(eng.base_dir)

