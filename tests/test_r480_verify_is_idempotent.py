# -*- coding: utf-8 -*-
"""r480：验证窗口与解除必须幂等（重复按不得真重复执行）。

两处实测缺陷：
  1) `verify_channel` 没有任何防重入。第二次请求的线程会先卡在
     `channel_slot`，等第一个窗口关闭后再**弹一个新窗**——人刚做完验证，
     屏幕上又冒出一个同样页面，而第二次的 done 事件没人触发，只能靠
     900s 超时收场。
  2) 前端 `verifyNow`/`paceReset` 没有在途守卫；后者每次都会触发后端
     单条查询探测（10–60 秒真链路），连点三次就是三次真打。

契约：
  - 后端按渠道拒绝重复开窗，且**任何路径**（含窗口异常 early return）
    都要清除在途标记，否则该渠道之后再也打不开验证窗；
  - 在途标记必须在 start 线程之前置位，否则有竞态窗口；
  - 前端四个干预入口（预热/自检/解除/去验证）全部有 PACE_BUSY 守卫，
    批量入口用 finally 兜底解锁。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _m():
    return io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                   newline="").read()


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def _fn(src, name, nxt):
    i = src.index(name)
    return src[i:src.index(nxt, i)]


def test_verify_rejects_second_window_per_channel():
    seg = _fn(_m(), "def verify_channel(", "rt[\"verify_channel\"]")
    assert 'rt.setdefault("verify_open", {})' in seg, "没有在途登记"
    assert 'if _ving.get(platform):' in seg, "未按渠道拒绝重复开窗"
    assert '"dup": True' in seg, "拒绝原因未标记 dup（前端无法区分）"
    # r481：判断与占位必须同在 _VERIFY_LOCK 内（原子），否则并发双通过
    i = seg.index("with _VERIFY_LOCK:")
    j = seg.index("_ving[platform] = True")
    assert i < j < seg.index("\n        ", j), "占位未在锁内完成"
    assert seg.index('if _ving.get(platform):') > i, "判断被移出锁"


def test_verify_flag_is_set_before_thread_start_and_always_cleared():
    seg = _fn(_m(), "def verify_channel(", "rt[\"verify_channel\"]")
    start = seg.index("threading.Thread(target=_run")
    setpos = seg.index("_ving[platform] = True")
    # r481：占位提前到预检之前（锁内），因此必然早于线程启动
    assert setpos < start, "在途标记必须在启动线程之前置位（否则有竞态）"
    # _run 的最外层必须 try/finally：early return（窗口异常）也要清标记
    body = seg[seg.index("def _run():"):start]
    tail = body[body.rindex("finally:"):]
    assert 'rt.get("verify_open", {}).pop(' in tail, \
        "_run 最外层 finally 未清除在途标记"
    # 预检失败（未知渠道 / 无法确定地址）也要回滚：占位已提前完成
    assert "_resolved = False" in seg and "if not _resolved:" in seg, \
        "预检路径未回滚占位——该渠道会永久打不开验证窗"
    assert "_ving.pop(platform, None)" in seg, "启动线程失败时未回滚标记"


def test_verify_body_still_persists_session_and_probes():
    """防重入不得改变原有语义：关窗后仍要 reset + 单查 + 重新熔断。"""
    seg = _fn(_m(), "def verify_channel(", "rt[\"verify_channel\"]")
    assert 'rt["pacing"].reset(platform)' in seg
    assert "_probe_channel(c, scene)" in seg
    assert '"retripped"' in seg
    assert 'storage.save_intervention(' in seg


def test_all_frontend_entries_are_idempotent():
    w = _w()
    for fn, key in (("warmNow", "warm:"), ("probeNow", "probe:"),
                    ("paceReset", "reset:"), ("verifyNow", "verify:")):
        i = w.index("async function %s(" % fn)
        seg = w[i:w.index("\nasync function", i + 10)]
        assert "PACE_BUSY['%s'+p]" % key in seg, "%s 缺在途守卫" % fn
        assert "delete PACE_BUSY['%s'+p]" % key in seg, "%s 未解锁" % fn
    # 批量入口必须 finally 解锁（抛出会永久失效）
    for fn in ("probeAll", "warmAll"):
        i = w.index("async function %s(" % fn)
        seg = w[i:w.index("\nasync function", i + 10)]
        assert "}finally{" in seg and "delete PACE_BUSY" in seg, \
            "%s 解锁未走 finally" % fn


def test_verify_frontend_reports_duplicate_clearly():
    w = _w()
    i = w.index("async function verifyNow(")
    seg = w[i:w.index("\nasync function", i + 10)]
    assert "j.dup" in seg, "后端判重时前端仍报「打开失败」"


# ---------- 行为面：把真实的 verify_channel 函数体抽出、注入替身执行 ----------
# 只读源码、不启动服务、不连外网。三条：重复只开一个窗、异常也清标记、
# 上一窗关掉后能再开（防止「清得太狠」把渠道锁死）。

import ast as _ast
import textwrap as _tw
import threading as _th
import time as _tm

_SRC = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def _extract_verify():
    tree = _ast.parse(_SRC)
    node = next(n for n in _ast.walk(tree)
                if isinstance(n, _ast.FunctionDef)
                and n.name == "verify_channel")
    raw = _ast.get_source_segment(_SRC, node)
    lines = raw.splitlines()
    assert lines[0].lstrip().startswith("def verify_channel("), lines[0]
    return _tw.dedent(chr(10).join(lines))


class _Ctx:
    def __init__(self, fail=False):
        self.opened = []
        self.fail = fail


class _Crawler:
    name = "ctrip"
    use_mobile = False
    warmup_url = "https://example.invalid/w"
    last_block_url = ""
    paths = []
    retry_after_s = 0

    def __init__(self, ctx):
        self.ctx = ctx

    def login_url(self):
        return "https://example.invalid/l"

    def open_challenge_window(self, url, done, timeout_s=0, idx=0):
        self.ctx.opened.append(url)
        _tm.sleep(0.3)
        if self.ctx.fail:
            raise RuntimeError("boom")
        return True


class _Pac:
    def __init__(self):
        self.resets = 0

    def reset(self, p):
        self.resets += 1

    def snapshot(self):
        return {"channels": {"ctrip": {"state": "ok", "reason": ""}}}

    def observe(self, *a, **k):
        return ("", 0)


class _Chan:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


class _Sto:
    def save_intervention(self, *a, **k):
        pass


def _runtime(fail=False):
    ctx = _Ctx(fail)
    rt = {"scene": {}, "pacing": _Pac()}
    g = {"threading": _th, "time": _tm, "rt": rt, "logger": _Log(),
         "get_crawlers": lambda plats: [_Crawler(ctx) for _ in plats],
         "channel_slot": _Chan,
         "_probe_channel": lambda c, s: (True, 4, "ok"),
         "_VERIFY_LOCK": _th.Lock(), "_WARM_LOCK": _th.Lock(),
         "_refetch_failed": lambda p: {"n": 0, "rows": 0},
         "storage": _Sto()}
    exec(compile(_extract_verify(), "<verify_channel>", "exec"), g)
    return g["verify_channel"], ctx, rt


def _wait_clear(rt, seconds=5.0):
    end = _tm.time() + seconds
    while _tm.time() < end:
        if not rt.get("verify_open", {}).get("ctrip"):
            return True
        _tm.sleep(0.05)
    return False


def test_second_call_opens_no_second_window():
    fn, ctx, rt = _runtime()
    assert fn("ctrip")["ok"] is True
    r2 = fn("ctrip")
    assert r2["ok"] is False and r2.get("dup") is True, r2
    assert "已经开着" in r2["err"]
    assert _wait_clear(rt)
    assert len(ctx.opened) == 1, "重复调用真的开了第二个窗口：%r" % (ctx.opened,)


def test_flag_cleared_even_when_window_raises():
    fn, ctx, rt = _runtime(fail=True)
    assert fn("ctrip")["ok"] is True
    assert _wait_clear(rt), "窗口异常后在途标记未清除——该渠道再也打不开验证窗"


def test_can_reopen_after_close():
    fn, ctx, rt = _runtime()
    assert fn("ctrip")["ok"] is True
    assert _wait_clear(rt)
    assert fn("ctrip")["ok"] is True, "上一窗关掉后仍被误判为重复"


def test_warm_channel_is_guarded_on_the_backend_too():
    """前端 PACE_BUSY 只挡同一页面连点；第二个标签页/直接调接口仍会重复预热。

    预热是本系统里最没价值又最伤风控的动作（叠加机器指纹、把成功率打低），
    所以后端也要按渠道拒绝，并在**任何路径**释放（异常不得永久锁死）。
    """
    seg = _fn(_m(), "def warm_channel(", "rt[\"warm_channel\"]")
    assert 'rt.setdefault("warm_open", {})' in seg, "预热无在途登记"
    assert "if _wg.get(platform):" in seg, "未按渠道拒绝重复预热"
    assert '"dup": True' in seg, "拒绝未标记 dup"
    setpos = seg.index("_wg[platform] = True")
    trypos = seg.index("with channel_slot(c.name):")
    assert setpos < trypos, "置位必须在真正预热之前"
    # r481：判断+占位在锁内原子完成（并发两请求不得双通过）
    assert "with _WARM_LOCK:" in seg
    li = seg.index("with _WARM_LOCK:")
    assert li < seg.index("if _wg.get(platform):") < setpos
    release = seg[seg.index("finally:"):]
    assert '_wg.pop(platform, None)' in release, "异常时未释放（渠道会永久锁死）"
    # 占位提前后，「无独立预热入口」的提前返回也必须能释放（走外层 finally）
    assert seg.index("无独立预热入口") > setpos, \
        "无入口的返回仍在占位之前——占位会被永久占用"


def test_warm_frontend_surfaces_dup_as_in_progress():
    w = _w()
    i = w.index("async function warmNow(")
    seg = w[i:w.index("\nasync function", i + 10)]
    assert "j.dup" in seg, "后端判重时前端仍报「预热失败」或「完成」"


def test_reset_endpoint_guards_concurrent_probe():
    """解除后面紧跟一次真实单查；并发第二次会覆盖结果，必须后端兜住。"""
    w = _w()
    i = w.index('"/api/pacing/reset"')
    seg = w[i:w.index('"/api/channel/probe"', i)]
    assert "_State.reset_open" in seg, "解除无在途登记"
    assert '"dup": True' in seg, "未标记 dup"
    assert seg.count("_rsg.discard(plat)") >= 2, "异常与正常路径都要释放"
    assert "finally:" in seg and "_rsg.discard(plat)" in seg.split("finally:")[-1], \
        "探测段释放未走 finally"
    # r481：判断与占位必须在 reset_lock 内原子完成
    assert "_State.reset_lock" in seg, "解除闸门无锁——并发双跑探测"
    li = seg.index("with _State.reset_lock:")
    assert li < seg.index("if plat in _rsg:") < seg.index("_rsg.add(plat)")
    # 字段必须存在，否则 AttributeError 会把整个端点打成 500
    assert "reset_open = set()" in w


# ---------- r481：闸门必须原子（并发双通过会真开两个窗） ----------

def test_gate_is_atomic_under_concurrency():
    """「判断 + 占位」必须在同一把锁内完成。

    负控实测（r481）：在判断与置位之间注入一个 50ms 让出点，
    两个线程都会通过判断 → **开出两个验证窗**，第二个窗的 done
    事件无人触发，只能靠 900s 超时收场。ThreadingHTTPServer 是并发
    处理请求的，所以这是真实可达的时序，不是理论风险。
    """
    import ast as _a
    import textwrap as _t

    src = _m()
    node = next(n for n in _a.walk(_a.parse(src))
                if isinstance(n, _a.FunctionDef) and n.name == "verify_channel")
    seg = _t.dedent("\n".join(
        _a.get_source_segment(src, node).splitlines()))
    # 判断与占位之间不得出现「锁外」的代码
    i = seg.index("with _VERIFY_LOCK:")
    body_start = seg.index("\n", i) + 1
    guard = seg.index("if _ving.get(platform):", body_start)
    setpos = seg.index("_ving[platform] = True", guard)
    between = seg[guard:setpos]
    # 两者缩进必须相同且在锁内（比 with 深一级）
    assert "\n        " not in between.replace("\n            ", ""), \
        "判断与占位之间跑出了锁外代码"
