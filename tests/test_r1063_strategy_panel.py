# -*- coding: utf-8 -*-
r"""r1063 T12b：配置页「策略控制」分区（目录驱动 + 微信级扁平）。

本文件钉的是**渲染器**这一半（Spec §4.1 的 `visualizable` / §6(a) 的承载面）：

1. **目录驱动**：策略行由 `GET /api/strategy` 的 `strategies` 逐条生成，
   模板里不许出现 `data-strategy="<sid>"` 这样的第二份声明（加一条策略就漏）；
2. **每一行都带三个东西**：`data-strategy`（身份）、`data-family`（族，分组/
   芯片靠它挂）、**来源徽标**（默认/全局/渠道/维度/链路——「谁说了算」）；
3. **文案只有一个来源**：`label` / `intent` / `effect` 一律从载荷里读，界面里
   不再抄一份（抄一份的下场是目录改了界面不变，同一句话两处互相打架）；
4. **分区身份不变**：标题从「渠道节流」改成「策略控制」，但分区 id 仍是
   `pacing`——深链 `CFGPANEL='pacing'` 与健康卡入口 `cfgGoThrottle()` 必须照旧可用；
5. **可调整有边界**：新出现的数值控件要进 `GLB_RANGES`，越界才能当场标红
   （没登记就是「填了 99999、保存下去被静默夹掉」，r606 那类缺陷）。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_strategy_panel.py -q
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 非 flat 的数值参数必须有独立控件与边界（这些键此前页面上没有任何控件：
# `crawler.policy.pace.*` / `sticky_s.*` / `block_s.human` / `risk.levels.*`）
NEW_NUMERIC_IDS = ("glbPaceWatch", "glbPaceDegraded", "glbStickyWatch",
                   "glbBlockHuman", "glbRiskPause")


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _fn(src, name):
    """取一个顶层函数的源码段（到下一个 `function ` 为止）。"""
    i = src.index(name)
    j = src.index("\nfunction ", i + 1)
    return src[i:j]


def _renderer(src):
    """整段渲染器（参数格 + 行模板 + 拉取/绘制）：边界/徽标分散在这几支里。"""
    i = src.index("function stratCellHTML(")
    j = src.index("/* ===== 子卡折叠", i)
    return src[i:j]


# ---------------------------------------------------------------- 目录驱动

def test_panel_is_directory_driven_and_has_no_second_declaration():
    """渲染器必须从 `/api/strategy` 取行，模板里不许逐条写死 28 个 id。"""
    from core.strategy_contract import STRATEGIES

    w = _w()
    assert "/api/strategy" in w
    assert "data-strategy" in w, "策略行没有 data-strategy 落点"
    assert w.count('data-strategy="rate_per_minute"') == 0, (
        "模板里写死了 rate_per_minute —— 那是第二份声明")
    hard = [s.id for s in STRATEGIES if 'data-strategy="%s"' % s.id in w]
    assert not hard, "模板里逐条写死了这些策略 id：%s" % hard


def test_every_row_carries_sid_family_and_a_source_badge():
    """每行三件齐全：`data-strategy` / `data-family` / 来源徽标。"""
    w = _w()
    row = _fn(w, "function stratRowHTML(")
    # 行容器：id 与族都由载荷带出（插值，不是字面量）
    assert re.search(r'data-strategy=["\']\s*["\']?\s*\+?', row) or \
        "data-strategy=" in row, row[:200]
    assert "data-family=" in row, "行上没有 data-family（芯片/分组挂不住）"
    assert "${s.id}" in row or "+s.id+" in row or "esc(s.id)" in row or \
        "sid" in row, "行上的 data-strategy 不是从载荷取 id"
    # 来源徽标：五个来源都有中文，且引用的是载荷的 source
    for zh in ("默认", "全局", "渠道", "维度", "链路"):
        assert zh in w, "来源徽标缺「%s」" % zh
    assert re.search(r"source", row), "行上没有读载荷的 source 字段"


def test_renderer_reads_label_intent_effect_from_the_payload():
    """文案只从载荷来：界面里不许出现目录里那些句子的第二份。"""
    from core.strategy_contract import STRATEGIES

    w = _w()
    row = _fn(w, "function stratRowHTML(")
    for fld in ("label", "intent", "effect"):
        assert fld in row, "渲染器没读载荷的 %s" % fld
    dup = []
    for s in STRATEGIES:
        for txt in (s.label, s.intent, s.effect):
            if txt and txt in w:
                dup.append((s.id, txt))
    assert not dup, "界面里抄了一份目录文案（应从 /api/strategy 读）：%s" % dup[:4]


# ---------------------------------------------------------------- 边界登记

def test_new_numeric_keys_are_registered_for_range_check():
    """非 flat 数值参数的控件必须有边界，否则越界值被静默夹掉。"""
    w = _w()
    i = w.index("const GLB_RANGES=[")
    seg = w[i:w.index("function glbRangeOf(", i)]
    for fid in NEW_NUMERIC_IDS:
        assert re.search(r"id:'%s'" % fid, seg), "%s 没进 GLB_RANGES" % fid


def test_directory_driven_control_carries_its_own_bounds():
    """目录驱动的控件随身带 `data-min`/`data-max`（边界只有目录一份）。"""
    w = _w()
    row = _renderer(w)
    assert "data-min" in row and "data-max" in row, (
        "控件没带 data-min/data-max：范围校验查不到边界就会静默放行")
    assert "data-pid=" in row, "控件没有 data-pid（值写回时对不上参数）"
    # 范围解析要能吃下这种形态（GLB_RANGES 里查不到时读控件自带边界）
    gr = _fn(w, "function glbRangeOf(")
    assert "data-min" in gr or "dataset.min" in gr, (
        "glbRangeOf 不认识控件自带的 data-min/data-max")


def test_param_controls_write_the_existing_glb_bag_not_a_new_route():
    """写路径只有一个：值进 `GLB` 脏状态，保存仍走 `saveCfg()` 整表 POST。"""
    w = _w()
    assert "/api/strategy/set" not in w, "另开了参数写接口（Spec §6(c)：不许抢写 yaml）"
    row = _renderer(w)
    assert "GLB." in row or "stratSet(" in row, "控件没写进 GLB 脏状态"
    setf = _fn(w, "function stratSet(")
    assert "GLB." in setf, "stratSet 没有写 GLB"
    # 停手/恢复走 T6 的干预路由（运行期干预，不写配置）
    assert "/api/strategy/halt" in w and "/api/strategy/resume" in w


# ---------------------------------------------------------------- 分区身份

def test_partition_title_and_deeplink_stay_working():
    """标题改「策略控制」，但分区 id / 深链 / 健康卡入口一个都不许动。

    注意深链的实际形态：`CFGPANEL` 的**默认值是登录分区**（并记住上次停留
    的分区，`localStorage['jpcfgpanel']`），「渠道节流」从来不是默认分区，
    所以这里钉的是「分区 id 仍是 pacing + `showCfgPanel('pacing')` 仍能直达」，
    而不是钉一个从来不存在的默认值。
    """
    w = _w()
    assert "let CFGPANEL='pacing'" in w or "showCfgPanel('pacing')" in w, (
        "深链分区 id 被改掉：再也到不了 pacing 分区")
    assert "let CFGPANEL='login'" in w, "默认分区被改（深链/记住上次分区的基线变了）"
    assert "jpcfgpanel" in w, "「记住上次分区」的深链机制丢了"
    assert "function cfgGoThrottle(" in w, "健康卡直达入口丢了"
    assert '<span class="zh">策略控制</span>' in w
    assert '<span class="zh">渠道节流</span>' not in w, "旧标题仍在"
    # 分区容器与宿主节点仍是 pacing（r638 / r1070 / r1072 都在用）
    assert 'id="panel-pacing"' in w
    assert "id=\"cfgpacing\"" in w or "id='cfgpacing'" in w
    # 健康卡入口仍要落到节流控件上（test_goal_c 钉这条）
    fn = w[w.index("function cfgGoThrottle("):]
    fn = fn[:fn.index("async function health(")]
    assert "showCfgPanel(" in fn and "glbQs" in fn


def test_legacy_throttle_controls_are_still_inside_the_panel():
    """重构不许把既有节流控件挤丢：它们是「配了能生效」的既有证据。"""
    legacy = ("glbQs", "glbQe", "glbFast", "glbSlow", "glbNear", "glbStg",
              "glbGap", "glbRpm", "glbBrk", "glbHpen", "glbHok", "glbHslow",
              "glbHsf", "glbHslf", "glbHms", "glbBbs", "glbBcs", "glbWarm",
              "glbWarmP", "glbLcd", "glbNearD")
    w = _w()
    i = w.index("const gp=''")
    gp = w[i:w.index("$('cfgglobals').innerHTML=gh;", i)]
    miss = [k for k in legacy if ("'%s'" % k) not in gp]
    assert not miss, "这些既有节流控件被重构挤掉了：%s" % miss


def test_panel_keeps_exactly_two_foldable_sections():
    """r1070/r1072 的几何契约：本分区只有两个可折叠小节，族头不算小节。"""
    w = _w()
    i = w.index("const gp=''")
    gp = w[i:w.index("$('cfgglobals').innerHTML=gh;", i)]
    n = len(re.findall(r"glsec\([^)]*,\s*1\s*\)", gp))
    assert n == 2, "可折叠小节从 2 个变成了 %d 个（r1070 按 2 个判几何）" % n


# ---------------------------------------------------------------- 真落盘

def _post_cfg(cfg_path, payload):
    """起一个真 `webui._Srv`，POST 一次 `/api/config`（与 r649 同一套夹具）。"""
    import json
    import threading

    import urllib.request

    import webui

    st = webui._State
    st.cfg = {"users": []}
    st.boot_cfg = {"users": []}
    st.users = []
    st.alerters = []
    st.job = None
    st.report_push = None
    st.reload_cb = None
    st.config_path = cfg_path
    st.version = "t12b"
    st.login_saved_cb = None
    st.logger = __import__("logging").getLogger("t12b")
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False
    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/api/config" % port
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as he:
            return he.code, json.loads(he.read().decode("utf-8") or "{}")
    finally:
        srv.shutdown()
        srv.server_close()
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)


def test_strategy_values_from_the_panel_really_land_in_config_yaml(tmp_path):
    """面板里的数必须真写进 `config.yaml` 的点路径（配了不生效比没配更糟）。"""
    import yaml

    cfg = str(tmp_path / "config.yaml")
    io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump({"users": []}, allow_unicode=True))
    code, out = _post_cfg(cfg, {"users": [], "globals": {"strategy_values": {
        "pace_factor.watch": 2.5,
        "risk_bands.pause": 70,
        "block_window.human": 3600,
        "ttl_tier.fast": 20,
    }}})
    assert code == 200 and out.get("ok"), (code, out)
    saved = yaml.safe_load(io.open(cfg, encoding="utf-8"))
    assert saved["crawler"]["policy"]["pace"]["watch"] == 2.5, saved
    assert saved["crawler"]["risk"]["levels"]["pause"] == 70, saved
    assert saved["crawler"]["policy"]["block_s"]["human"] == 3600, saved
    assert saved["schedule"]["fast_ttl_min"] == 20, saved


def test_strategy_values_are_clamped_and_unknown_pids_are_refused(tmp_path):
    """越界按目录边界夹取；目录里没有的 pid 一律拒绝（不许静默丢弃）。"""
    import yaml

    cfg = str(tmp_path / "config.yaml")
    io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump({"users": []}, allow_unicode=True))
    code, out = _post_cfg(cfg, {"users": [], "globals": {"strategy_values": {
        "pace_factor.watch": 999}}})
    assert code == 200 and out.get("ok"), (code, out)
    saved = yaml.safe_load(io.open(cfg, encoding="utf-8"))
    assert saved["crawler"]["policy"]["pace"]["watch"] == 10, \
        "越界值没有按 Param.hi 夹取：%s" % saved
    # 未知 pid：整次保存如实失败（不写半份、不吞错）
    code2, out2 = _post_cfg(cfg, {"users": [], "globals": {"strategy_values": {
        "nowhere.pid": 1}}})
    assert code2 >= 400 and not out2.get("ok"), (code2, out2)
    assert "没写进去" in str(out2.get("err") or ""), out2
