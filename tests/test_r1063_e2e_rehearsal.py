# -*- coding: utf-8 -*-
"""r1063 T40：**端到端演练**——在真实 HTTP 服务上把整条链跑一遍。

前面几十轮都是分段验证（单测 + 门禁）。这条把它们串起来，回答一个问题：
「用户真去点这些界面/接口，能不能走通？」

链路：`/api/strategy` 读到目录 → `POST /api/config` 改全局值 → **立刻热生效**
→ 改某渠道/链路的覆盖 → 也立刻生效 → `/api/pacing` 读到耗时/等待/换道读数
→ `/api/strategy/halt` 停一条链路 → `/api/strategy/resume` 恢复
→ `/api/strategy/snapshot` 导出的快照与刚才改的完全一致 → `cfg_snapshot.apply`
把快照灌回一份空配置，结果一致（可备份/可回滚）。
"""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest
import yaml

import webui
from core import strategy_params as sp


class _Srv:
    """起一个真 `webui._Srv`，返回 (base_url, stop)。"""

    def __init__(self, tmp_path):
        from core.storage import PriceStorage
        from core.pacing import Pacing

        self.dir = tmp_path
        self.user_data = tmp_path / "user_data"   # 见上：绝不碰真实档案
        self.cfg_path = str(tmp_path / "config.yaml")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"users": []}, f, allow_unicode=True)
        st = webui._State
        self._old = {k: getattr(st, k, None) for k in
                     ("cfg", "boot_cfg", "users", "alerters", "job",
                      "report_push", "reload_cb", "config_path", "version",
                      "login_saved_cb", "logger", "pacing")}
        # **必须**把 user_data_dir 指到临时目录：`/api/session/reset` 等路由
        # 读的是配置里的这个值。不指的话用例会去动工作区里**真实的**渠道档案
        # （真实发生过一次：飞猪档案被改名成 .bak，已还原）。
        _ud = str(tmp_path / "user_data")
        os.makedirs(_ud, exist_ok=True)
        st.cfg = {"users": [], "crawler": {"user_data_dir": _ud}}
        st.boot_cfg = {"users": [], "crawler": {"user_data_dir": _ud}}
        st.users = []
        st.alerters = []
        st.job = None
        st.report_push = None
        # 忠实的 reload：生产里 `main.reload_config()` 会刷新 `_State.cfg`
        # 与参数层；夹具里必须一样，否则快照会读到保存前的旧配置。
        def _reload():
            with open(self.cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            webui._State.cfg = cfg
            webui._State.boot_cfg = cfg
            sp.set_config(cfg)
            return len(cfg.get("users") or [])

        st.reload_cb = _reload
        st.config_path = self.cfg_path
        st.version = "t40"
        st.login_saved_cb = None
        st.logger = __import__("logging").getLogger("t40")
        # 节流上下文：让 `/api/pacing` 有真快照可读
        self.pac = Pacing({})
        st.pacing = self.pac
        self.ps = PriceStorage(str(tmp_path / "t.db"))
        self._old_storage = getattr(webui, "_strategy_storage", None)
        webui._strategy_storage = lambda: self.ps
        self._old_demo = dict(webui.DEMO)
        webui.DEMO["on"] = False
        self.srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
        self.srv.daemon_threads = True
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        try:
            self.srv.shutdown()
        finally:
            webui.DEMO.clear()
            webui.DEMO.update(self._old_demo)
            if self._old_storage is None:
                try:
                    del webui._strategy_storage
                except AttributeError:
                    pass
            else:
                webui._strategy_storage = self._old_storage
            for k, v in self._old.items():
                setattr(webui._State, k, v)

    # ---- 小工具 ----
    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def post(self, path, payload):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def cfg(self):
        with open(self.cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


@pytest.fixture()
def srv(tmp_path):
    sp.invalidate()
    s = _Srv(tmp_path)
    try:
        yield s
    finally:
        s.close()
        sp.invalidate()


def test_chain_directory_to_hot_global_value(srv):
    # ① 目录读得到：30 条、每条参数带「生效值 + 来源」
    code, j = srv.get("/api/strategy")
    assert code == 200 and j.get("ok"), j
    assert len(j["strategies"]) == 31, len(j["strategies"])   # r1063 T47 起 31 条
    row = [r for s in j["strategies"] for r in s["params"]
           if r["pid"] == "rate_min_gap.value"][0]
    assert "value" in row and "source" in row

    # ② 改全局值 → 落盘 + **立刻**生效（热）
    code2, out2 = srv.post("/api/config", {"users": [], "globals": {
        "strategy_values": {"rate_min_gap.value": 9}}})
    assert code2 == 200 and out2.get("ok"), out2
    saved = srv.cfg()
    assert saved["crawler"]["rate"]["min_gap_s"] == 9, saved.get("crawler")
    sp.set_config(saved)          # 服务端保存后会 reload；这里复现同一份配置
    got = sp.resolve("rate_min_gap.value")
    assert got.value == 9 and str(got.source) != "default", got


def test_chain_channel_override_reaches_the_resolver(srv):
    # 覆盖表随 `globals` 一起提交（与 strategy_values 同一层，T19 定下的形状）
    code, out = srv.post("/api/config", {
        "users": [], "globals": {"strategy_overrides": {
            "tongcheng/intl/H5/API": {"rate_min_gap.value": 30}}}})
    assert code == 200 and out.get("ok"), out
    saved = srv.cfg()
    ovr = saved["crawler"]["strategy_overrides"]
    assert ovr["tongcheng/intl/H5/API"]["rate_min_gap.value"] == 30, ovr
    sp.set_config(saved)
    got = sp.resolve("rate_min_gap.value", plat="tongcheng", dim="intl",
                     path="H5/API")
    assert got.value == 30 and str(got.source) == "path", got
    # 同一渠道的其它链路不受影响
    other = sp.resolve("rate_min_gap.value", plat="tongcheng", dim="detail",
                       path="PC")
    assert other.value != 30, other


def test_chain_health_readouts_are_present(srv):
    srv.pac.note_query_timing(wall=20.0, work=12.0, tasks=5, gate=7.5)
    srv.pac.note_chan_wait("qunar", 210.0)
    srv.pac.note_failover(switched=1, rows=0, reason="App 通路不可用")
    code, j = srv.get("/api/pacing")
    assert code == 200, (code, j)
    assert "qunar" in (j.get("channels") or {}), list(j)[:8]
    assert (j["channels"]["qunar"] or {}).get("waited_s") == 210.0
    t = j.get("timing") or {}
    assert t.get("gate") == 7.5 and t.get("fetch") == 4.5, t
    f = j.get("failover") or {}
    assert f.get("reasons", {}).get("App 通路不可用") == 1, f


def test_chain_halt_a_single_link_then_resume(srv):
    code, out = srv.post("/api/strategy/halt", {
        "plat": "ctrip", "minutes": 15, "scope": "detail/H5/API"})
    assert code == 200 and out.get("ok"), out
    assert out.get("key") == "ctrip/detail/H5/API", out
    from core.policy import halt_for, read_halt
    prof = webui._policy_engine("ctrip").base_dir
    halts = read_halt(prof)
    assert halt_for(halts, "ctrip", "detail", "H5/API")[0] == "ctrip/detail/H5/API"
    assert halt_for(halts, "ctrip", "detail", "PC") == ("", {})

    code2, out2 = srv.post("/api/strategy/resume",
                           {"plat": "ctrip", "scope": "detail/H5/API"})
    assert code2 == 200 and out2.get("cleared") is True, out2
    assert not read_halt(prof)


def test_chain_snapshot_round_trip(srv):
    srv.post("/api/config", {"users": [], "globals": {
        "strategy_values": {"rate_min_gap.value": 9}}})
    srv.post("/api/config", {"users": [], "globals": {
        "strategy_overrides": {"ctrip/intl": {
            "rate_min_gap.value": 11}}}})
    code, j = srv.get("/api/strategy/snapshot")
    assert code == 200 and j.get("ok"), j
    snap = j["snapshot"]
    assert snap["values"].get("rate_min_gap.value") == 9, snap["values"]
    assert snap["overrides"]["ctrip/intl"]["rate_min_gap.value"] == 11

    # 灌回一份空配置：结果必须一致（可备份 / 可迁移 / 可回滚）
    from core import cfg_snapshot as cs
    fresh = {}
    got = cs.apply(fresh, snap)
    assert got["applied"] >= 1 and not got["rejected"], got
    again = cs.export(fresh)
    assert again["values"] == snap["values"]
    assert again["overrides"] == snap["overrides"]
