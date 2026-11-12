# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_strategy_scope_edit.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import webui

from core.channels import DIMENSIONS


# ---- merged from tests/test_r1063_strategy_scope_edit.py ----

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

    src = webui_full_src()
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
