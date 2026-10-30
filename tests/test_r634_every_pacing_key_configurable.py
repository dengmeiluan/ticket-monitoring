# -*- coding: utf-8 -*-
r"""r634：core.pacing 的每一个配置项都要「能改、能存、能生效」。

用户要求「配置页面不允许存在任何无法配置的项……如果能热更新就热更新」。
前面几轮分别守了半条链：r601 守「有控件」、r485 守「/api/config 有回读」。
但两者都是**静态文本**判据，本文件第一版（同口径的正则对账）负控实测
全绿——把 `GLB.fast_ttl_min=...` 的赋值删掉后，`GLB.fast_ttl_min==null`
这种比较式仍然能命中 `\s*=`，判据对真正的缺口不敏感，已废弃。

现在改成三条**行为**判据：
  1) 真渲染：配置页上每个 DEFAULTS 键都有控件（onchange 里带赋值）；
  2) 真往返：POST /api/config → 落盘 yaml → GET 回读，值原样回来；
  3) 真生效：`Pacing.refresh()` 之后，该值出现在解析结果里。
只有「用户改得动 + 存得住 + 读得回 + 真生效」都成立，才算可配置。

附带补了一个真实缺口：5 个健康阈值键原先不在 config.example.yaml 里，
而 r601 的通用门禁是从那个文件枚举键的——漏写样例 = 该键没有任何
门禁覆盖，删掉它的控件也不会有人报警。
"""
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.pacing import DEFAULTS, parse_pacing  # noqa: E402

# 每个键都给一个「与默认不同、且在钳制区间内」的值。
# 故意避开默认值：写进去读回来若还是默认值，说明这一键根本没被采纳
# （静默夹取/字段名写错都会长这样）。
CAND = {
    "scan_quiet_start": "01:30",
    "scan_quiet_end": "06:15",
    "fast_ttl_min": 17,
    "slow_ttl_min": 137,
    "near_ratio": 0.23,
    "stagger_seconds": 7,
    "breaker_enabled": False,
    "breaker_base_s": 321,
    "breaker_cap_s": 4444,
    "login_cooldown_s": 777,
    "min_gap_s": 2.5,
    "per_minute": 13,
    "warmup_enabled": False,
    "warmup_platforms": "qunar, fliggy",
    "health_penalty_enabled": False,
    "health_min_samples": 9,
    "health_ok_ratio": 0.66,
    "health_slow_ratio": 0.31,
    "health_slow_factor": 1.7,
    "health_slowest_factor": 3.4,
    "max_concurrency": 3,
    "near_days": 5,
    "cadence": {"qunar": 9},
}

assert set(CAND) == set(DEFAULTS), (
    "DEFAULTS 新增/删除了键，本测试的取值表要同步：多 %s / 少 %s"
    % (sorted(set(CAND) - set(DEFAULTS)), sorted(set(DEFAULTS) - set(CAND))))

# 节点名与盘上键名不同（`breaker.enabled` 在 pacing 里叫 breaker_enabled）。
# 逐项写死路径，避免 `_find` 递归到同名但不同义的键上。
DISK = {
    "scan_quiet_start": ("schedule", "scan_quiet_start"),
    "scan_quiet_end": ("schedule", "scan_quiet_end"),
    "fast_ttl_min": ("schedule", "fast_ttl_min"),
    "slow_ttl_min": ("schedule", "slow_ttl_min"),
    "near_ratio": ("schedule", "near_ratio"),
    "near_days": ("schedule", "near_days"),
    "stagger_seconds": ("schedule", "stagger_seconds"),
    "breaker_enabled": ("crawler", "breaker", "enabled"),
    "breaker_base_s": ("crawler", "breaker", "base_s"),
    "breaker_cap_s": ("crawler", "breaker", "cap_s"),
    "login_cooldown_s": ("crawler", "breaker", "login_cooldown_s"),
    "min_gap_s": ("crawler", "rate", "min_gap_s"),
    "per_minute": ("crawler", "rate", "per_minute"),
    "warmup_enabled": ("crawler", "warmup", "enabled"),
    "warmup_platforms": ("crawler", "warmup", "platforms"),
    "health_penalty_enabled": ("crawler", "health_penalty_enabled"),
    "health_min_samples": ("crawler", "health_min_samples"),
    "health_ok_ratio": ("crawler", "health_ok_ratio"),
    "health_slow_ratio": ("crawler", "health_slow_ratio"),
    "health_slow_factor": ("crawler", "health_slow_factor"),
    "health_slowest_factor": ("crawler", "health_slowest_factor"),
    "max_concurrency": ("crawler", "max_concurrency"),
    "cadence": ("crawler", "cadence"),
}

assert set(DISK) == set(DEFAULTS), (
    "DISK 路径表与 DEFAULTS 不同步：多 %s / 少 %s"
    % (sorted(set(DISK) - set(DEFAULTS)), sorted(set(DEFAULTS) - set(DISK))))


def _dig(tree, path):
    node = tree
    for p in path:
        if not isinstance(node, dict) or p not in node:
            return None, False
        node = node[p]
    return node, True


def _norm(v):
    """把「同一个值的不同写法」归一。

    `warmup_platforms` 提交的是逗号串、盘上是数组；布尔在 yaml 里是
    true/false。两边都用同一个口径比，才能一眼看出是「值不同」还是
    「写法不同」。
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x).strip() for x in v).replace(" ", "")
    if isinstance(v, (int, float)):
        return str(float(v))
    return str(v).replace(" ", "")


@pytest.fixture()
def live(tmp_path, monkeypatch):
    """真起一个 handler（随机端口），配置写进临时 yaml。"""
    import logging
    import webui

    cfg_path = str(tmp_path / "config.yaml")
    base = {"users": [], "web": {"port": 0, "host": "127.0.0.1"},
            "schedule": {"interval_minutes": 30}}
    with io.open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(base, f, allow_unicode=True)

    st = webui._State
    monkeypatch.setattr(webui, "DEMO", {"on": False})
    for attr, val in (("cfg", dict(base)), ("boot_cfg", dict(base)),
                      ("users", base["users"]), ("alerters", []),
                      ("job", None), ("report_push", None),
                      ("reload_cb", None), ("config_path", cfg_path),
                      ("version", "r634"), ("login_saved_cb", None),
                      ("logger", logging.getLogger("r634"))):
        monkeypatch.setattr(st, attr, val, raising=False)

    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield {"base": "http://127.0.0.1:%d" % port, "path": cfg_path}
    finally:
        srv.shutdown()
        srv.server_close()


def _post(base, payload):
    req = urllib.request.Request(
        base + "/api/config", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _get(base):
    with urllib.request.urlopen(base + "/api/config", timeout=20) as r:
        return json.loads(r.read().decode())


def test_every_pacing_key_survives_save_reload_and_takes_effect(live):
    """POST → yaml → GET 回读 → parse_pacing，四段都要认这个值。"""
    body = {"users": [], "globals": CAND}
    r = _post(live["base"], body)
    assert r.get("ok"), "保存失败：%s" % r

    saved = yaml.safe_load(io.open(live["path"], encoding="utf-8"))
    back = (_get(live["base"]).get("globals") or {})
    eff = parse_pacing(saved)

    miss_back, miss_yaml, miss_eff = [], [], []
    for k, v in CAND.items():
        yv, found = _dig(saved, DISK[k])
        if not found:
            miss_yaml.append(k)
        elif _norm(yv) != _norm(v):
            miss_yaml.append("%s: 盘上 %r != 提交 %r" % (k, yv, v))
        if k not in back:
            miss_back.append(k)
        elif _norm(back[k]) != _norm(v):
            miss_back.append("%s: 回读 %r != 提交 %r" % (k, back[k], v))
        if k not in eff:
            miss_eff.append(k)

    assert not miss_yaml, "这些键没落进 config.yaml（改了存不住）：%s" % miss_yaml
    assert not miss_back, (
        "这些键保存后重开配置页看不到自己的值（会渲染成默认值，"
        "用户再存一次就覆盖回默认）：%s" % miss_back)
    assert not miss_eff, "解析层不认识这些键：%s" % miss_eff


def test_pacing_values_change_behaviour_not_just_the_file(live):
    """热生效：把值喂给运行中的 Pacing.refresh()，行为要真的变。

    只测「文件里有」是不够的——`refresh()` 若漏下发某一组参数，
    保存后界面显示新值、采集端照旧，是最难发现的一类。
    """
    from core.pacing import Pacing
    assert _post(live["base"], {"users": [], "globals": CAND}).get("ok")
    saved = yaml.safe_load(io.open(live["path"], encoding="utf-8"))

    p = Pacing({})
    p.refresh(saved)
    c = p.cfg
    for k in ("fast_ttl_min", "slow_ttl_min", "near_ratio",
              "stagger_seconds", "breaker_base_s", "breaker_cap_s",
              "login_cooldown_s", "min_gap_s", "per_minute",
              "health_min_samples", "health_ok_ratio", "health_slow_ratio",
              "health_slow_factor", "health_slowest_factor",
              "max_concurrency", "near_days"):
        assert _norm(c[k]) == _norm(CAND[k]), (
            "refresh 后 %s 仍是 %r（提交 %r）——热更新没下发到运行态"
            % (k, c[k], CAND[k]))
    assert tuple(c["warmup_platforms"]) == ("qunar", "fliggy")
    assert c["breaker_enabled"] is False
    assert c["health_penalty_enabled"] is False
    assert c["warmup_enabled"] is False
    assert (c["cadence"] or {}).get("qunar") == 9

    # 真实行为面：节流桶换成了新值（不是只改 cfg 字典）
    assert p._bucket.min_gap_s == pytest.approx(2.5)
    assert p._bucket.per_minute == 13


def test_every_default_key_has_a_rendered_control():
    """真渲染：配置页每个 DEFAULTS 键都要有控件。

    静态查源码不够（比较式也能命中 `\\s*=`），这里真开浏览器把每个
    配置面板点开，按 onchange/oninput/onclick 里出现的**赋值**（排除
    `==`）收集键名。
    """
    import socket
    import subprocess
    import time

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    seen = {}
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=30000)
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(1200)
            panes = pg.evaluate(
                "()=>[...document.querySelectorAll('#cfgnav .cnav')]"
                ".map(e=>e.getAttribute('data-p'))")
            assert panes, "配置页没有渲染出任何分区导航"
            for p in panes:
                pg.evaluate(
                    "p=>{const c=document.querySelector("
                    "'#cfgnav .cnav[data-p=\"'+p+'\"]');if(c)c.click()}", p)
                pg.wait_for_timeout(500)
                got = pg.evaluate("""()=>{
                  const r={};
                  document.querySelectorAll(
                      'input,select,textarea,button').forEach(e=>{
                    const h=(e.getAttribute('onchange')||'')+' '+
                            (e.getAttribute('oninput')||'')+' '+
                            (e.getAttribute('onclick')||'');
                    const m=h.match(/GLB\\.[a-z0-9_]+\\s*=(?!=)/g)||[];
                    m.forEach(x=>{
                      const k=/GLB\\.([a-z0-9_]+)/.exec(x)[1];
                      r[k]=(r[k]||0)+1;});
                  });
                  return r;}""")
                for k, n in got.items():
                    seen[k] = seen.get(k, 0) + n
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert not errs, "配置页抛错：%s" % errs[:3]
    missing = [k for k in sorted(DEFAULTS) if not seen.get(k)]
    assert not missing, (
        "这些节流配置项在配置页上没有控件（用户只能改文件）：%s" % missing)
