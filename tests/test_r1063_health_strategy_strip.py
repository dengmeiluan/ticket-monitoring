# -*- coding: utf-8 -*-
"""r1063 T13：渠道健康「策略条」+ 一键停手/恢复（微信级扁平）。

Spec §6(b) 的承载面：`#paceBox` 每条渠道行下面挂一条**策略条**——只列
「非默认 / 本渠道生效」的策略芯片，点一下直达「配置 › 策略控制」的该策略行；
旁边一颗「停手 15 分钟 / 恢复」按运行期干预接口，停手中的渠道显示
「人工停手 N 分钟」且**与自动冷却一眼可分**（Spec §0.7 + 附录 C/D）。

本文件钉六件事：

1. **真的长在既有骨架上**：`.pace-row` 四列与 trace 不动，策略条插在其后；
   芯片消费 `/api/strategy` 的 `label`（≤20 字），界面里不抄第二份文案；
2. **只列该列的**：非默认（全局/渠道/维度/链路来源）或本渠道覆盖，最多
   6 颗，其余折进「更多」——渠道 × 28 条的笛卡尔积不许糊到屏幕上；
3. **三态可分**：自动处置中（蓝）/ 已按渠道覆盖（琥珀）/ 人工停手（红），
   靠**底色**分，不只靠文字；停手那条必须写明还剩几分钟；
4. **一键停手/恢复**：在途改文案（不是只置灰），成功回读载荷；
5. **建议行**：`tip` 的动作只要有真路由，就必须有按钮，且按钮真能落到处理
   函数（既有 r905 的规矩：让人点的按钮必须真点得到）；
6. **微信级扁平**：芯片 32px、按钮 ≥28px、白底零描边零卡中卡、中文短句。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_health_strategy_strip.py -q
"""
import io
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _fn(src, decl):
    """取一个顶层函数（或 `async function`）的源码段。

    到下一个顶层 `function` / `async function` / 顶层 `const` / 段落注释为止。
    """
    i = src.index(decl)
    j = len(src)
    for pat in ("\nfunction ", "\nasync function ", "\nconst ", "\n/* ===== "):
        k = src.find(pat, i + len(decl))
        if k > 0:
            j = min(j, k)
    return src[i:j]


def _strip_fn():
    return _fn(_w(), "function paceStripHTML(")


# ---------------------------------------------------------------- 骨架与入口


def test_health_card_renders_a_strategy_strip_with_actions():
    """策略条必须真在健康卡里渲染，且停手/恢复复用同一套接口。"""
    w = _w()
    assert "function paceStripHTML(" in w
    assert 'data-strip="' in w
    assert "function cfgGoStrategy(" in w
    # 停手/恢复必须复用同一套接口，不许另写一条
    assert "/api/strategy/halt" in w and "/api/strategy/resume" in w


def test_strip_chips_are_wechat_flat_and_speak_chinese_short():
    """微信级扁平化 + 可清晰：芯片长在既有家族里，文案是短句，不露裸 id。"""
    w = _w()
    assert ".pchip{" in w, "芯片没自己的扁平样式"
    seg = w[w.index(".pchip{"):][:400]
    assert "background:var(--r-surface)" in seg or "var(--r-blue-soft)" in seg
    assert "border-radius:var(--pill)" in seg or "border-radius:12px" in seg
    assert "border:0" in seg.replace(" ", "") or "border:none" in seg
    # 芯片文案来自策略目录的 label（≤20 字），不是拼 id
    fn = w[w.index("function paceStripHTML("):][:1500]
    assert "s.label" in fn or "st.label" in fn, "芯片没消费目录的 label"


def test_strip_sits_inside_the_channel_row_not_beside_it():
    """策略条是渠道行的一部分：.pace-ch 的直接子节点仍是 10 个 .pace-row。

    r1058 的窄档裁量按 `#paceBox .pace-ch:not(.all)>.pace-row:nth-child(n+5)`
    数行——策略条若另起兄弟节点，行序号会整体错位、前 4 行之外被误藏。
    """
    w = _w()
    fn = _fn(w, "async function loadPacing(")
    assert "+paceStripHTML(k)" in fn, "loadPacing 没在渠道行里插策略条"
    # 插在行内（`</span>` 之后、行尾 `</div>` 之前），不是另起一行 div
    i = fn.index("+paceStripHTML(k)")
    tail = fn[i:i + 120]
    assert "</div>" in tail, tail
    assert "'<div class=\"pace-row\"" in fn[:i], "找不到渠道行模板"
    assert '#paceBox .pace-row .pstrip{grid-column:1/-1' in w, \
        "策略条没有铺满整行（会被挤进 4 列里）"


# ---------------------------------------------------------------- 该列谁

def test_strip_only_lists_non_default_or_channel_scoped_strategies():
    """全默认 → 一条都不列；渠道覆盖的项只出现在那个渠道的策略条上。"""
    import webui
    from core import strategy_params as sp

    old = sp.get_config()
    try:
        sp.invalidate()
        rows = webui._strategy_strip_rows(["ctrip"])
        assert rows["ctrip"]["strategies"] == [], (
            "全默认时不该有任何芯片：%s" % rows)

        sp.set_config({"crawler": {"strategy_overrides": {
            "ctrip": {"rate_per_minute.value": 7},
            "qunar": {"ttl_tier.fast": 30}}}})
        got = webui._strategy_strip_rows(["ctrip", "qunar"])

        c_ids = {r["id"]: r for r in got["ctrip"]["strategies"]}
        assert "rate_per_minute" in c_ids, got["ctrip"]
        assert c_ids["rate_per_minute"]["state"] == "cover"
        assert c_ids["rate_per_minute"]["src"] == "channel"
        assert "ttl_tier" not in c_ids, "别家渠道的覆盖跑到这一行了"
        # 芯片文案来自目录 label（≤20 字），不是拼 id
        assert c_ids["rate_per_minute"]["label"]
        assert len(c_ids["rate_per_minute"]["label"]) <= 20
        assert c_ids["rate_per_minute"]["id"] not in c_ids["rate_per_minute"]["label"]

        q_ids = {r["id"]: r for r in got["qunar"]["strategies"]}
        assert "ttl_tier" in q_ids and "rate_per_minute" not in q_ids
    finally:
        if isinstance(old, dict) and old:
            sp.set_config(old)
        else:
            sp.invalidate()


def test_strip_is_capped_at_six_and_folds_the_rest_into_more():
    w = _w()
    assert "PACE_STRIP_MAX=6" in w, "没有「最多 6 颗」的上限"
    fn = _strip_fn()
    assert "PACE_STRIP_MAX" in fn, "上限没用在策略条上"
    assert "更多 " in fn, "超出的芯片没折进「更多」"
    assert "paceStripMore(" in w, "「更多」点不开"


# ---------------------------------------------------------------- 可区分

def test_halted_channel_reads_manual_halt_distinct_from_auto_cooldown():
    """人工停手必须与自动冷却**一眼可分**：不同底色 + 剩余分钟数。"""
    w = _w()
    fn = _strip_fn()
    assert "人工停手 " in fn, "停手中的渠道没写「人工停手 N 分钟」"
    assert "pc-halt" in fn and "pc-auto" in fn, "人工/自动共用一个颜色"
    # 剩余分钟由 `until` 现算（10 秒一拍的轮询跟不上倒计时走字）
    assert "halt.until" in fn and "60000" in fn, "剩余时间不是按 until 现算的"
    for cls in (".pchip.pc-halt{", ".pchip.pc-auto{", ".pchip.pc-cover{"):
        assert cls in w, "三态缺独立底色规则：%s" % cls
    # 停手 chip 有自己的颜色 token，不许和自动档撞色
    a = w[w.index(".pchip.pc-halt{"):]
    a = a[:a.index("}")]
    b = w[w.index(".pchip.pc-auto{"):]
    b = b[:b.index("}")]
    assert a.strip() != b.strip(), "人工停手与自动处置仍是同一套配色"


def test_payload_sells_manual_halt_and_per_channel_rows(tmp_path, monkeypatch):
    """载荷必须直出「人工停手」与逐渠道策略行——界面不许自己猜。

    真落盘一次人工停手（`core.policy.set_halt` 写 `strategy_halt.json`），再问
    一次载荷：那个渠道必须带 `halt`（含策略 id、中文名、到期时刻），且建议改成
    「恢复」；别的渠道不许被顺带标成停手。
    """
    import inspect
    import types

    import webui
    from core import policy

    body = inspect.getsource(webui._strategy_payload)
    assert "_strategy_strip_rows(" in body, "载荷没有逐渠道策略条"
    assert 'out["channels"]' in body or "out['channels']" in body, \
        "载荷没把逐渠道策略条售出"

    monkeypatch.setattr(webui, "_policy_engine",
                        lambda plat="": types.SimpleNamespace(
                            base_dir=str(tmp_path)))
    monkeypatch.setattr(webui, "_strategy_storage",
                        lambda: (_ for _ in ()).throw(RuntimeError("台账不可用")))
    rec = policy.set_halt(str(tmp_path), "ctrip", 15, "人工停手 15 分钟")
    assert rec is not False, "停手没落盘（夹具坏了，不是被测代码的锅）"

    out = webui._strategy_payload()
    assert out["ok"] is True, out.get("errors")
    ch = (out.get("channels") or {}).get("ctrip") or {}
    halt = ch.get("halt") or {}
    assert halt.get("id"), "停手渠道没带策略 id（芯片点不回配置页）：%s" % ch
    assert halt.get("label"), "停手芯片缺中文名（会露裸 id）"
    assert int(halt.get("left_s") or 0) > 0
    assert float(halt.get("until") or 0) > 0, "没有到期时刻，界面算不出剩余分钟"
    tip = ch.get("tip") or {}
    assert tip.get("action") == "resume", "停手中的渠道没有先劝恢复：%s" % tip
    assert tip.get("route") == "/api/strategy/resume", tip
    assert ((out.get("channels") or {}).get("qunar") or {}).get("halt") is None, \
        "停手串到别的渠道上了"
    # 停手归哪条策略由目录派生，不是写死一个 id
    owner = webui._strategy_halt_owner()
    assert owner.get("id") == halt.get("id"), (owner, halt)


# ---------------------------------------------------------------- 一键停手


def test_halt_and_resume_buttons_tell_you_they_are_in_flight():
    """在途必须**改文案**（不是只置灰），成功后回读载荷。"""
    w = _w()
    halt = _fn(w, "async function paceHalt(")
    assert "/api/strategy/halt" in halt
    assert "停手中…" in halt, "在途没改文案"
    assert "btn.textContent=" in halt, "在途没改文案"
    assert "loadPacing(true)" in halt, "成功后没回读载荷"
    assert "minutes:15" in halt.replace(" ", ""), "默认停手分钟数不是 15"

    resume = _fn(w, "async function paceResume(")
    assert "/api/strategy/resume" in resume
    assert "恢复中…" in resume
    assert "loadPacing(true)" in resume

    fn = _strip_fn()
    assert "paceHalt(this" in fn and "paceResume(this" in fn, \
        "渠道行上没有停手/恢复按钮"


# ---------------------------------------------------------------- 建议行


def test_advice_row_button_lands_on_a_real_handler():
    """`tip` 的动作有真路由 → 必须有按钮，且按钮落到真实处理函数。"""
    from core.strategy_advice import ROUTES

    w = _w()
    i = w.index("const PACE_ADVH={")
    j = w.index("};", i)
    table = dict(re.findall(r"(\w+):'(\w+)'", w[i:j]))
    routed = {a for a, r in ROUTES.items() if str(r).strip()}
    missing = sorted(routed - set(table))
    assert not missing, "这些有路由的动作在健康卡里没有落点：%s" % missing
    # 没有路由的动作（换身份 / 无需动作）不许硬塞按钮
    assert "rotate" not in table, "换身份没有执行入口，不许出按钮"

    for act, handler in table.items():
        assert ("function %s(" % handler) in w or \
               ("async function %s(" % handler) in w, \
               "动作 %s 指向的 %s() 不存在（点了没落点）" % (act, handler)

    go = _fn(w, "function paceAdviceGo(")
    for act in table:
        if act == "config":            # 兜底分支就是「去这条策略」
            continue
        assert ("'%s'" % act) in go, "paceAdviceGo 没有分发 %s" % act
    assert "cfgGoStrategy(" in go, "没有兜底落点"


def test_chip_copy_is_the_catalog_label_not_a_literal_table():
    """界面里不许出现 label 的第二份（抄一份的下场是目录改了界面说谎）。"""
    from core.strategy_contract import STRATEGIES

    w = _w()
    dup = [s.id for s in STRATEGIES if s.label and s.label in w]
    assert not dup, "界面里抄了目录 label：%s" % dup[:4]
    fn = _strip_fn()
    assert "esc(s.label)" in fn, "芯片文案不是从载荷 label 来的"
    assert re.search(r"esc\(String\(r\.id", fn) or "data-strip=" in fn


def test_cfg_go_strategy_opens_and_highlights_the_row():
    """点芯片要落到配置页那条策略行上：切分区 + 展开 + 滚动 + 高亮。"""
    w = _w()
    fn = _fn(w, "function cfgGoStrategy(")
    assert "switchView('cfg')" in fn
    assert "showCfgPanel('pacing')" in fn
    assert "data-strategy=" in fn, "没按 data-strategy 找行"
    assert "scrollIntoView" in fn, "没滚动到该行"
    assert "stratFold(" in fn, "没展开该行（收起时点进去看不到控件）"
    assert "hit" in fn, "没有落点高亮"
    assert "#cfgview #cfgpacingRows .srow.hit{" in w, "高亮样式不存在"


# ---------------------------------------------------------------- 扁平几何


def test_strip_geometry_stays_32px_chips_and_28px_buttons():
    """芯片 32px、按钮 ≥28px、零描边、白底：Spec §0.7 的控件节奏。"""
    w = _w()
    seg = w[w.index(".pchip{"):][:400]
    assert "height:32px" in seg, "芯片不是 32px"
    assert "box-shadow" not in seg, "芯片带了投影（卡中卡）"
    pact = w[w.index("#paceBox .pstrip .pact button{"):]
    pact = pact[:pact.index("}")]
    h = int(re.search(r"height:(\d+)px", pact).group(1))
    assert h >= 28, "行内按钮高 %dpx < 28px" % h
    adv = w[w.index("#paceBox .pstrip .pace-adv button{"):]
    adv = adv[:adv.index("}")]
    assert int(re.search(r"height:(\d+)px", adv).group(1)) >= 28
    # 芯片容器必须允许折行：390/320 零横向溢出
    strip = w[w.index("#paceBox .pace-row .pstrip{"):]
    strip = strip[:strip.index("}")]
    assert "flex-wrap:wrap" in strip, "390/320 会横向溢出"
    assert "min-width:0" in strip
    # 复用既有家族：hbadge / snote / chip 都在策略条上出现过
    fn = _strip_fn()
    assert "hbadge" in fn, "来源徽标没复用既有 hbadge 家族"
    assert "snote" in _fn(w, "function paceAdviceHTML("), \
        "建议行没复用既有 snote 家族"
    assert "class=\"chip\"" not in fn and "chip" in fn


def test_strip_css_only_uses_the_panels_three_type_steps():
    """节流面板字号只有 11/12/16 三档（`docs/uitest.py` 逐元素量 computedStyle）。

    r1130：策略条样式随健康页重排分成基础段 + 恢复段，按「选择器规则」
    全仓取样，不再用注释段首尾锚点（锚点会随 CSS 分区迁移而跑偏）。
    """
    w = _w()
    rules = re.findall(r"#paceBox \.(?:pstrip|pchip)[^{]*\{[^}]*\}", w)
    assert len(rules) >= 3, "策略条 CSS 规则不足：%d" % len(rules)
    sizes = set()
    for r in rules:
        sizes |= set(re.findall(r"font-size:(\d+)px", r))
    assert sizes <= {"11", "12", "16"}, "策略条引入了字号档：%s" % sorted(sizes)
    for r in rules:
        assert not re.findall(r"#[0-9a-fA-F]{3,8}", r),             "策略条里硬编码了颜色（走 --r-* 令牌）：%r" % r[:80]


# ---------------------------------------------------------------- 真渲染几何
#
# 上面几条是源码契约；这一条是**渲染级**证据（Spec §4.1 的「可可视化」不接受
# 「代码里有这行」）：真起 demo、把 `/api/strategy` 换成一只有内容的载荷（含
# 渠道覆盖、已停用、人工停手、建议），再逐元素量 computedStyle。
#
# 为什么用 route 拦截而不是往页面里塞全局变量：`loadChannelState()` 在会话槽
# 变化时会 `loadPacing(true)`，那一拍会**强制重读** `/api/strategy`——塞进去的
# 缓存会被真载荷顶掉，量到的就是「全默认」的空条。走真的读路径才量得准。

_STRIP_PAYLOAD = {
    "ok": True, "plats": ["ctrip", "qunar"], "strategies": [],
    "overrides": {}, "halt": {}, "errors": {},
    "channels": {
        "ctrip": {
            "strategies": [
                {"id": "rate_per_minute", "label": "每分钟请求上限",
                 "src": "channel", "state": "cover", "enabled": True},
                {"id": "ttl_tier", "label": "快慢两档抓取间隔",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "health_penalty", "label": "成功率低自动降频",
                 "src": "global", "state": "auto", "enabled": False},
                {"id": "cadence", "label": "各渠道最少间隔分钟",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "quiet_window", "label": "静默窗不发起采集",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "budget", "label": "单次采集请求预算",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "warmup", "label": "深链前先打首页",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "proxy_route", "label": "出口与代理选择",
                 "src": "global", "state": "auto", "enabled": True}],
            "halt": None,
            "tip": {"id": "rate_per_minute", "action": "config",
                    "text": "分钟上限用完了就排队：把上限调大再跑",
                    "route": "/api/config"}},
        "qunar": {
            "strategies": [
                {"id": "block_window", "label": "人工停手窗口",
                 "src": "channel", "state": "cover", "enabled": True}],
            "halt": {"id": "block_window", "label": "人工停手窗口",
                     "until": 0, "left_s": 247},
            "tip": {"id": "block_window", "action": "resume",
                    "text": "人工停手生效中：确认过验证后点恢复立刻回到正常节奏",
                    "route": "/api/strategy/resume"}},
    },
}

def _strip_payload():
    """现算 `until`：停手芯片的剩余分钟是按到期时刻现算的，写死 0 会渲染成 1 分钟。"""
    import copy
    import time

    p = copy.deepcopy(_STRIP_PAYLOAD)
    p["channels"]["qunar"]["halt"]["until"] = time.time() + 247
    return p


_MEASURE = r"""() => {
  const box=document.getElementById('paceBox');
  const strips=[...box.querySelectorAll('.pstrip')];
  const vis=e=>e.getBoundingClientRect().height>1;
  const chips=[...box.querySelectorAll('.pstrip .pchip')].filter(vis);
  const fonts=new Set();
  box.querySelectorAll('.pstrip *').forEach(e=>{const v=getComputedStyle(e).fontSize;
    if(v)fonts.add(v);});
  const halt=[...box.querySelectorAll('.pchip.pc-halt')];
  const cover=[...box.querySelectorAll('.pchip.pc-cover')];
  return {strips:strips.length, nchips:chips.length,
    chipH:[...new Set(chips.map(c=>+c.getBoundingClientRect().height.toFixed(1)))],
    actH:[...box.querySelectorAll('.pstrip .pact button')].filter(vis)
      .map(b=>+b.getBoundingClientRect().height.toFixed(1)),
    advH:[...box.querySelectorAll('.pstrip .pace-adv button')].filter(vis)
      .map(b=>+b.getBoundingClientRect().height.toFixed(1)),
    fonts:[...fonts],
    over:document.documentElement.scrollWidth-document.documentElement.clientWidth,
    haltTxt:halt.length?(halt[0].textContent||'').trim():'',
    haltCls:halt.length?halt[0].className:'',
    coverCls:cover.length?cover[0].className:'',
    advTxt:(box.querySelector('.pstrip .pace-adv .txt')||{}).textContent||''};
}"""


@pytest.fixture(scope="module")
def demo_base():
    import socket
    import subprocess
    import time
    import urllib.request

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失，渲染级用例跳过")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            yield base
            break
        except Exception:
            time.sleep(0.3)
    else:
        pytest.fail("demo 服务没起来")
    srv.terminate()
    try:
        srv.wait(timeout=8)
    except Exception:
        srv.kill()


@pytest.mark.parametrize("width", [1512, 390])
def test_rendered_strip_keeps_wechat_flat_geometry(demo_base, width):
    """真渲染：32px 芯片、≥28px 按钮、三档字号、零溢出、零 pageerror。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        try:
            pg = br.new_page(viewport={"width": width, "height": 1000})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            body = json.dumps(_strip_payload(), ensure_ascii=False)
            pg.route("**/api/strategy*",
                     lambda route: route.fulfill(status=200,
                                                 content_type="application/json",
                                                 body=body))
            pg.goto(demo_base + "/", wait_until="domcontentloaded")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=30000)
            # 进「监控 · 渠道健康」并**确认面板真的可见**：切视图的尾巴是异步
            # 的（后面的渲染拍可能把 display 又翻回去），量到 0 高度就等于什么
            # 都没量。这里重试几次，直到 `#paceBox` 有真实高度。
            visible = False
            for _ in range(6):
                pg.evaluate(
                    "() => {try{switchView('mon')}catch(e){}"
                    "try{showMonTab('health')}catch(e){}}")
                try:
                    pg.wait_for_function(
                        "() => {const b=document.getElementById('paceBox');"
                        "return !!b && b.getBoundingClientRect().height > 1;}",
                        timeout=4000)
                    visible = True
                    break
                except Exception:
                    continue
            assert visible, "渠道健康面板没显示出来（量不到几何）"
            # 行先画、策略条后画（/api/strategy 要跑十五轴矩阵，实测 0.5–1.2s）：
            # 这里等的正是「补画上来」这一拍。
            pg.wait_for_function(
                "() => document.querySelectorAll('#paceBox .pstrip .pchip').length >= 4",
                timeout=20000)
            d = pg.evaluate(_MEASURE)
            assert d["strips"] >= 2, "策略条没渲染出来：%s" % d
            assert d["nchips"] >= 4, "芯片没渲染出来：%s" % d
            assert 22 <= min(d["chipH"]) and max(d["chipH"]) <= 32, "芯片高度越界：%s" % d["chipH"]
            assert d["actH"] and min(d["actH"]) >= 28, \
                "停手/恢复按钮低于 28px：%s" % d["actH"]
            assert d["advH"] and min(d["advH"]) >= 28, \
                "建议动作按钮低于 28px：%s" % d["advH"]
            # 只量策略条自己的字号：整块节流面板 HEAD 就是 11/12.5/13… 多档
            # （uitest 那条更宽的判据不归本任务），新长出来的这颗芯片必须落在
            # 面板既有档位里，不许再开一档。
            assert set(d["fonts"]) <= {"11px", "12px", "16px"}, \
                "策略条自带一档字号：%s" % sorted(set(d["fonts"]))
            assert d["over"] <= 1, "%d 档横向溢出了 %spx" % (width, d["over"])
            # 人工停手 vs 自动处置：两种底色 + 写明剩余分钟
            assert "人工停手" in d["haltTxt"], d["haltTxt"]
            assert "pc-halt" in d["haltCls"] and "pc-cover" in d["coverCls"], d
            assert "建议：" in d["advTxt"], "建议行没渲染：%s" % d["advTxt"]
            assert not errs, "页面报错：%s" % errs
            pg.close()
        finally:
            br.close()
