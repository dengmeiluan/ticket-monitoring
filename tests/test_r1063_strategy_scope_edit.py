# -*- coding: utf-8 -*-
"""r1063 T19：策略面板能**按作用域改参数**（此前只能改全局值 + 停手）。

目标要求「每个维度每个链路都可调整」。停手（T18）解决了"停"，但"调"仍然
只能在 YAML 里手写 `crawler.strategy_overrides`——界面上改一个参数只会写全局层，
选了链路也照样改全站。这一条补上：

  1. `webui._strategy_override_apply(cfg, ovr)`：粒度覆盖的唯一写入口，
     校验作用域形状、pid 是否在目录、值过 `clamp()`（与求值同一入口）；
     `值=None` = 清除该覆盖；
  2. 面板 `stratSet()`：行内选了维度/链路 → 写 `GLB.strategy_overrides[作用域]`，
     **不再**写全局层（作用域越界是契约第 14 条明令禁止的）；
  3. 保存走既有 `/api/config` 整表 POST（不新开写接口），并带 `strategy_overrides`。
"""
import os

import pytest

import webui
from core.channels import DIMENSIONS


def _cfg():
    return {"crawler": {}, "schedule": {}}


def test_override_writes_into_crawler_strategy_overrides():
    cfg = _cfg()
    n = webui._strategy_override_apply(
        cfg, {"ctrip/detail/H5/API": {"rate_min_gap.value": 30}})
    assert n == 1
    ovr = cfg["crawler"]["strategy_overrides"]
    assert ovr["ctrip/detail/H5/API"]["rate_min_gap.value"] == 30


def test_override_clamps_like_the_evaluator():
    """边界与求值同一入口：越界值被夹到声明区间，而不是原样落盘。"""
    from core import strategy_params as sp
    from core.strategy_contract import STRATEGIES

    p = [pp for s in STRATEGIES for pp in s.params
         if pp.pid == "rate_min_gap.value"][0]
    cfg = _cfg()
    webui._strategy_override_apply(
        cfg, {"ctrip": {"rate_min_gap.value": (p.hi or 0) + 999}})
    got = cfg["crawler"]["strategy_overrides"]["ctrip"]["rate_min_gap.value"]
    assert got <= p.hi, (got, p.hi)


def test_none_clears_the_override_and_empty_scope_disappears():
    cfg = _cfg()
    webui._strategy_override_apply(
        cfg, {"ctrip/intl": {"rate_min_gap.value": 20}})
    assert "ctrip/intl" in cfg["crawler"]["strategy_overrides"]
    webui._strategy_override_apply(
        cfg, {"ctrip/intl": {"rate_min_gap.value": None}})
    assert "ctrip/intl" not in (cfg["crawler"].get("strategy_overrides") or {})


def test_unknown_pid_and_bad_scope_are_rejected_loudly():
    """写一条查不到的覆盖＝「配了不生效」，必须整块报错而不是静默吞掉。"""
    cfg = _cfg()
    with pytest.raises(ValueError) as e1:
        webui._strategy_override_apply(cfg, {"ctrip": {"nope.pid": 1}})
    assert "目录里没有这个参数" in str(e1.value)
    with pytest.raises(ValueError) as e2:
        webui._strategy_override_apply(cfg, {"ctrip/nosuchdim": {"rate_min_gap.value": 5}})
    assert "维度" in str(e2.value)
    with pytest.raises(ValueError) as e3:
        webui._strategy_override_apply(cfg, {"": {"rate_min_gap.value": 5}})
    assert "作用域为空" in str(e3.value)
    # 整块不写：失败后配置保持原样
    assert not (cfg["crawler"].get("strategy_overrides"))


def test_empty_overrides_is_a_noop():
    cfg = _cfg()
    assert webui._strategy_override_apply(cfg, None) == 0
    assert webui._strategy_override_apply(cfg, {}) == 0
    assert "strategy_overrides" not in cfg["crawler"]


def test_scope_grammar_accepts_all_real_dimensions():
    cfg = _cfg()
    for d in DIMENSIONS:
        webui._strategy_override_apply(
            cfg, {"ctrip/%s" % d: {"rate_min_gap.value": 7}})
    assert set(cfg["crawler"]["strategy_overrides"]) == {
        "ctrip/%s" % d for d in DIMENSIONS}


# ---------------- UI 侧：作用域改动不许落到全局层 ----------------

def test_panel_writes_scope_override_not_global():
    import io

    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    seg = src[src.index("function stratSet(el,pid){"):]
    seg = seg[:2200]
    assert "GLB.strategy_overrides[_scope]" in seg, "作用域改动没写进覆盖表"
    # 选了作用域就必须 return，不许继续写全局层/扁平字段
    assert "if(_scope){" in seg and "return;}" in seg
    assert "stratScopePick" in src and "stratScopeNote" in src
    # 覆盖表随 globals 一起提交（与 strategy_values 同一层，不另开顶层字段）
    assert "GLB.strategy_overrides[_scope]" in src


def _post_cfg(cfg_path, payload):
    """起一个真 `webui._Srv`，POST 一次 `/api/config`（与 T12b 同一套夹具）。"""
    import json
    import threading
    import urllib.request

    st = webui._State
    st.cfg = {"users": []}
    st.boot_cfg = {"users": []}
    st.users = []
    st.alerters = []
    st.job = None
    st.report_push = None
    st.reload_cb = None
    st.config_path = cfg_path
    st.version = "t19"
    st.login_saved_cb = None
    st.logger = __import__("logging").getLogger("t19")
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False
    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/config" % port,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:      # 4xx/5xx 也要能读到 err 文本
        return e.code, json.loads(e.read().decode("utf-8"))
    finally:
        srv.shutdown()
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)


def test_scope_override_from_the_panel_really_lands_in_config_yaml(tmp_path):
    """面板里按作用域改的数必须真写进 `crawler.strategy_overrides`。"""
    import io

    import yaml

    cfg = str(tmp_path / "config.yaml")
    io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump({"users": []}, allow_unicode=True))
    code, out = _post_cfg(cfg, {
        "users": [], "globals": {"strategy_overrides": {
            "ctrip/detail/H5/API": {"rate_min_gap.value": 30}}}})
    assert code == 200 and out.get("ok"), (code, out)
    saved = yaml.safe_load(io.open(cfg, encoding="utf-8"))
    ovr = saved["crawler"]["strategy_overrides"]
    assert ovr["ctrip/detail/H5/API"]["rate_min_gap.value"] == 30, saved
    # 而且求值层真的读得到（写进去 ≠ 生效，两者都要验）
    from core import strategy_params as sp
    sp.set_config(saved)
    try:
        got = sp.resolve("rate_min_gap.value", plat="ctrip", dim="detail",
                         path="H5/API")
        assert got.value == 30, got
        assert got.source == "path", got
    finally:
        sp.invalidate()
