# -*- coding: utf-8 -*-
"""r388：空结果不得被页头「登录/注册」字样误判成登录墙。

实测（2026-10-27 03:5x，飞猪国际 SHA→LHR，已登录 profile，页面 0 卡片）：

```
old_regex_hit(登录|扫码|login)=True  real_wall=False  logged_in=True
hit context: ... / 扫码下载飞猪 App / 微信小程序 / 微信公众号 / 增值电信...
```

旧判定 `re.search(r"登录|扫码|passport|login", url + body[:800])` 打在整页
文本上，页脚「扫码下载飞猪 App」与页头「登录/注册」恒命中 → **任何空
结果都会记 login**，触发 15 分钟登录冷却并提示用户重登。三渠道（飞猪
国际、携程 H5、同程 H5）统一改用 `classify_text` 真登录墙判据。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.challenge import classify_text  # noqa: E402

_LOG = logging.getLogger("t_r388")


def _src(path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", path), encoding="utf-8") as f:
        return f.read()


def test_footer_scan_copy_is_not_login_wall():
    body = ("搜索 / 我的订单 / 飞猪国际 / 机票 / 出发 / 到达 / "
            "security-op-fliggy@alibaba-inc.com / 扫码下载飞猪 App / "
            "微信小程序 / 微信公众号 / 增值电信业务经营许可证")
    assert classify_text(body, "") is None, "页脚扫码入口不是登录墙"


def test_header_login_link_is_not_login_wall():
    body = "搜索 / 我的订单 / 登录/注册 / 飞猪国际 / 机票 / 酒店"
    assert classify_text(body, "") is None, "页头「登录/注册」链接不是登录墙"


def test_real_login_wall_still_detected():
    for body in ("请先登录后查看价格", "账号密码登录", "扫码登录",
                 "验证码登录"):
        sig = classify_text(body, "")
        assert sig is not None and sig.status == "login", body


def test_passport_url_is_login_wall():
    sig = classify_text("", "https://passport.fliggy.com/login.htm")
    assert sig is not None and sig.status == "login"


def test_three_crawlers_use_classify_text_for_login():
    """飞猪国际 / 携程 H5 / 同程 H5 的登录判定必须是 classify_text 单源。"""
    for f in ("fliggy.py", "ctrip.py", "tongcheng.py"):
        src = _src(f)
        assert 'r"登录|扫码|账号密码"' not in src, f
        assert 'r"登录|扫码|passport|login"' not in src, f
        assert 'classify_text(_body, str(page.url))' in src, f


def test_tongcheng_imports_classify_text():
    from crawlers import tongcheng as tc
    assert hasattr(tc, "classify_text"), "同程必须导入 classify_text"


# ---- r388b：fliggy H5 回退曾因未导入 os 而静默崩溃 ----

def test_fliggy_h5_fallback_has_os_import():
    """`_h5_fallback` 用 os.path.isfile 做会话存在性判断；缺 os 导入时
    每次回退都 NameError（日志只有一行 warning），整条兜底静默失效。"""
    from crawlers import fliggy
    assert hasattr(fliggy, "os"), "fliggy 必须导入 os"
    src = _src("fliggy.py")
    assert "\nimport os\n" in src
    # 使用点仍在（防止日后被删而测试失去意义）
    assert "os.path.isfile(h5.session_state_path)" in src


def test_no_missing_stdlib_names_in_crawlers_and_core():
    """静态扫描：crawlers/core/main/webui 不得出现「用到但未导入」的
    常见 stdlib 名（同一类静默崩溃的通用守卫）。"""
    import ast
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    check = {"os", "re", "time", "json", "math", "random", "shutil",
             "tempfile", "threading", "subprocess", "hashlib", "uuid",
             "base64", "urllib", "datetime", "pathlib", "sqlite3", "csv"}

    def bound_names(tree):
        b = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    b.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    b.add(a.asname or a.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
                b.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                b.add(n.id)
            elif isinstance(n, ast.arg):
                b.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                b.add(n.name)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                b.update(n.names)
        return b

    bad = []
    files = [os.path.join(here, "main.py"), os.path.join(here, "webui.py")]
    for d in ("crawlers", "core"):
        p = os.path.join(here, d)
        files += [os.path.join(p, f) for f in sorted(os.listdir(p))
                  if f.endswith(".py")]
    for path in files:
        if not os.path.isfile(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        missing = sorted((used & check) - bound_names(tree))
        if missing:
            bad.append((os.path.basename(path), missing))
    assert not bad, bad


# ---- r388c：本轮覆盖率的"没发"与"全失败"必须可区分 ----

def test_coverage_ratio_none_when_nothing_sent():
    """刚重启/静默窗跳过后 sent=[]，ratio 必须是 None 而不是 0%。

    0% 会让"本轮没发任何请求"看起来像"发了全失败"。
    """
    from core.pacing import Pacing
    p = Pacing({})
    cov = p.snapshot()["coverage"]
    assert cov["sent"] == [] and cov["ratio"] is None, cov
    p.begin_round("10:00:00")
    p.note_sent("qunar")
    p.note_sent("tuniu")
    p.note_result("qunar", ok=True)
    p.note_result("tuniu", ok=False)
    cov2 = p.snapshot()["coverage"]
    assert cov2["sent"] and cov2["ratio"] is not None
    assert 0.0 <= float(cov2["ratio"]) <= 1.0


def test_ui_renders_dash_for_empty_coverage():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    assert "(j.coverage.ratio||0)*100" not in src, \
        "不得再把「没发」渲染成 0%"
    # 空覆盖率必须渲染成「—」而不是 0%。实现可能写成
    # `ratio==null?null:...` 再由下游 `_covVal===null?'—'` 落字，
    # 只要「空 → —」这条链在源码里成立即可。
    assert ("j.coverage.ratio==null?'—'" in src
            or "j.coverage.ratio==null?null" in src
            and "_covVal===null?'—'" in src), "空覆盖率未渲染成 —"


# ---- r388d：陈旧样本不得报「路径劣化」----

def _node(paths):
    return {"paths": paths, "query_attempts": 10, "query_ok": 9,
            "query_detail_ok": 9, "query_calendar_only": 0,
            "scopes": {"dom": {"paths": paths}, "intl": {"paths": {}}}}


def test_stale_path_not_reported_degraded():
    """兜底路径几小时没被用到（主路径一直成功）→ 不催用户去"修"。"""
    from core import pacing as P
    old = "2026-01-01 00:00:00"
    paths = {"H5": {"attempts": 50, "ok": 45, "rate": 0.9,
                    "rate_excl_empty": 0.9, "last_at": "2026-10-27 19:30:00"},
             "API": {"attempts": 20, "ok": 0, "rate": 0.0,
                     "rate_excl_empty": 0.0, "last_at": old}}
    now = P.time.mktime(P.time.strptime("2026-10-27 20:00:00",
                                        "%Y-%m-%d %H:%M:%S"))
    a = P.advise("qunar", {}, paths, now=now, node=_node(paths))
    assert a["state"] != "path_degraded", a


def test_fresh_degraded_path_still_reported():
    """新鲜样本（<3h）仍要报劣化，门槛不能把真问题一起吞掉。"""
    from core import pacing as P
    paths = {"H5": {"attempts": 50, "ok": 45, "rate": 0.9,
                    "rate_excl_empty": 0.9, "last_at": "2026-10-27 19:30:00"},
             "API": {"attempts": 20, "ok": 0, "rate": 0.0,
                     "rate_excl_empty": 0.0, "last_at": "2026-10-27 19:55:00"}}
    now = P.time.mktime(P.time.strptime("2026-10-27 20:00:00",
                                        "%Y-%m-%d %H:%M:%S"))
    a = P.advise("qunar", {}, paths, now=now, node=_node(paths))
    assert a["state"] == "path_degraded", a
    assert "API" in a["hint"]


# ---- r391：静默窗内不得给「点立即扫描」这种做不到的建议 ----

def _stale_paths():
    return {"H5": {"attempts": 10, "ok": 10, "rate": 1.0,
                   "rate_excl_empty": 1.0,
                   "last_ok_at": "2026-10-27 01:00:00"}}


def test_stale_inside_quiet_window_still_offers_manual_scan():
    """静默窗内仍可点「立即扫描」——手动入口注入的是 sweep(force=True)。

    实测 05:28 手动触发，五个渠道各写 3 条新行；所以建议必须保留 probe，
    只补一句"不点的话等到几点"（曾误判为"点了没用"而改成 wait，已回退）。
    """
    import time as _t
    from core.pacing import advise
    now = _t.mktime(_t.strptime("2026-10-27 04:00:00", "%Y-%m-%d %H:%M:%S"))
    a = advise("ctrip", {}, _stale_paths(), now=now,
               node={"paths": _stale_paths()},
               quiet={"start": "01:00", "end": "07:00", "active": True})
    assert a["state"] == "stale"
    assert a["action"] == "probe", a
    assert "立即扫描" in a["hint"], a
    assert "静默窗" in a["hint"] and "07:00" in a["hint"], a


def test_stale_outside_quiet_window_still_suggests_scan():
    import time as _t
    from core.pacing import advise
    now = _t.mktime(_t.strptime("2026-10-27 09:00:00", "%Y-%m-%d %H:%M:%S"))
    a = advise("ctrip", {}, _stale_paths(), now=now,
               node={"paths": _stale_paths()},
               quiet={"start": "01:00", "end": "07:00", "active": False})
    assert a["state"] == "stale" and a["action"] == "probe", a
    assert "立即扫描" in a["hint"]


def test_advise_quiet_param_is_optional():
    """老调用方不传 quiet 时行为不变（向后兼容）。"""
    import time as _t
    from core.pacing import advise
    now = _t.mktime(_t.strptime("2026-10-27 04:00:00", "%Y-%m-%d %H:%M:%S"))
    a = advise("ctrip", {}, _stale_paths(), now=now,
               node={"paths": _stale_paths()})
    assert a["action"] == "probe"


# ---- r393：渠道不提供舱位时必须如实标注「舱位未标」----

def test_cabin_missing_marker_present():
    """飞猪 100% / 去哪儿 99% 的行没有舱位字段（渠道列表页不提供）。

    明细里舱位片整段不渲染，读者会把公务舱价当经济舱价看。
    现在对「有航班号+起降时刻」的真班次标注「舱位未标」，日历行不标。
    """
    src = _src("webui.py") if False else open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    assert 'class="cmiss"' in src
    assert "舱位未标" in src
    # 只在真班次上标：条件里必须同时要求 code/depTime/arrTime
    i = src.find('class="cmiss"')
    ctx = src[max(0, i - 260):i]
    assert "f.code&&f.depTime&&f.arrTime" in ctx, ctx[-200:]


def test_cabin_missing_css_defined():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    assert ".cmiss{" in src, "必须有对应样式，否则提示与正文混在一起"


def test_unlabelled_cabin_not_silently_treated_as_economy():
    """舱位未知不得被当成经济舱参与同班比价分组（前端 fp 用独立分组）。"""
    from core.flightnorm import cabin_class
    assert cabin_class("") == ""
    assert cabin_class("公务舱") == "公务舱"


def test_baggage_missing_marker_present():
    """飞猪/途牛 100%、去哪儿 85% 的行没有行李字段（原始报文 0 个行李键）。

    缺失时明细默认不渲染行李，读者无从判断是否含托运。对真班次标注
    「行李未标」，并明确"不代表无行李"；有行李或日历行不标。
    """
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    assert "行李未标" in src
    assert "不代表无行李" in src
    i = src.find("行李未标")
    ctx = src[max(0, i - 260):i]
    assert "f.code&&f.depTime&&f.arrTime" in ctx, ctx[-200:]
    assert "!f.baggage" in ctx and "!f.carryon" in ctx, ctx[-200:]
