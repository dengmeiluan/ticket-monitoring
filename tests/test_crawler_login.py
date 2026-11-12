# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1582_app_login_wall_markers.py
- tests/test_r1585_login_not_captcha.py
- tests/test_r324_login_guide.py
- tests/test_r338_login_alert.py
- tests/test_r388_login_wall_precision.py
- tests/test_r608_login_copy_matches_policy.py
- tests/test_r644_login_section_covers_app.py
- tests/test_r689_login_first_screen_not_expired.py
- tests/test_r973_login_suspect_is_per_round.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.riskscore as riskscore
import io
import logging
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request

from crawlers.app_base import AppCrawler
from crawlers.app_qunar import AppQunarCrawler
from crawlers.challenge import classify_text


# ---- merged from tests/test_r1582_app_login_wall_markers.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def _read(name):
    return io.open(os.path.join(FIX, name), encoding="utf-8",
                   errors="replace").read()


def _c():
    return AppCrawler({}, None)


def test_fliggy_login_page_is_recognised():
    assert _c().is_login_wall(_read("fliggy_login_page.xml")) is True, (
        "飞猪登录页没被认出来：会被当成'没数据'白跑 200 秒并累计熔断")


def test_ctrip_login_page_is_recognised():
    assert _c().is_login_wall(_read("ctrip_login_page.xml")) is True, (
        "携程登录页没被认出来")


def test_train_page_is_not_a_login_wall():
    assert _c().is_login_wall(_read("tongcheng_train_page.xml")) is False, (
        "同程火车票页被误判成登录墙")


def test_plain_page_is_not_a_login_wall():
    assert _c().is_login_wall('<node text="航班明细"/>') is False


# ---- merged from tests/test_r1585_login_not_captcha.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def _read(name):
    return io.open(os.path.join(FIX, name), encoding="utf-8",
                   errors="replace").read()


def test_fliggy_login_page_is_login_not_captcha():
    sig = classify_text(text=_read("fliggy_login_page.xml"))
    assert sig is not None, "飞猪登录页没被识别出任何挑战（会被当成没数据）"
    assert sig.kind == "login", (
        "飞猪登录页被认成 %r —— 界面会提示「去验证」，而用户看到的是登录页"
        % (sig.kind,))


def test_ctrip_login_page_is_login():
    sig = classify_text(text=_read("ctrip_login_page.xml"))
    assert sig is not None and sig.kind == "login", sig


def test_train_page_is_not_a_challenge():
    assert classify_text(text=_read("tongcheng_train_page.xml")) is None, \
        "同程火车票页被当成挑战页"


def test_real_slider_still_detected():
    sig = classify_text(text="请拖动滑块完成验证")
    assert sig is not None and sig.kind in ("slider", "captcha"), sig


# ---- merged from tests/test_r324_login_guide.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_login_guide_urls_map():
    from crawlers.ctrip import CtripCrawler
    from crawlers.fliggy import FliggyCrawler
    from crawlers.qunar import QunarCrawler
    from crawlers.tongcheng import TongchengCrawler
    from crawlers.tuniu import TuniuCrawler

    import logging
    lg = logging.getLogger("t324lg")
    assert QunarCrawler({}, lg).login_url() == (
        "https://user.qunar.com/passport/login.jsp"), (
        "qunar 引导页须落统一登录页（PC /site/ 已停服只剩 App 下载提示）")
    assert CtripCrawler({}, lg).login_url() == (
        "https://passport.ctrip.com/user/login"), (
        "r678 实测：www.ctrip.com 在移动指纹下是 App 式首页，0 个登录控件")
    from core.login_slots import LOGIN_SLOTS
    assert (CtripCrawler({}, lg).login_url()
            == LOGIN_SLOTS["ctrip"]["login_url"]), "爬虫与登录卡不同源"
    # r678 实测：www.tuniu.com 在采集同款移动指纹下是腾讯云 WAF 拦截页
    # （登录控件 0 个）——用户点「弹窗登录」看到的是拦截页，读作「登不了」。
    # 改到 passport 登录页，且必须与登录卡同源（两处各写一份会再漂移）。
    from core.login_slots import LOGIN_SLOTS
    # 槽位入口 = passport 登录表单（实测能渲染账密/验证码）；
    # "PC 页"由 channel_links.LOGIN_ENTRY 承担（接管窗口打开 flight.tuniu.com）。
    assert TuniuCrawler({}, lg).login_url() == "https://passport.tuniu.com/login"
    assert (TuniuCrawler({}, lg).login_url()
            == LOGIN_SLOTS["tuniu"]["login_url"]), \
        "爬虫登录入口与登录卡不是同源，修一处漏一处"
    assert TongchengCrawler({}, lg).login_url() == "https://www.ly.com/"
    assert FliggyCrawler({}, lg).login_url() == "https://www.fliggy.com/"


# ---- merged from tests/test_r338_login_alert.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PLAT = "qunar"


class _FakeN:
    def __init__(self):
        self.sent = []
        # 生产传的是 (user, Alerter) 对，哨读 al.notifier——fake 同构
        # 包一层（mock 尊重公共契约，廿三§8）
        self.notifier = self

    def send(self, title, desp):
        self.sent.append((title, desp))
        return True


def _fresh():
    import main
    from crawlers import REGISTRY
    old = getattr(REGISTRY[_PLAT], "login_suspect", None)
    main._LOGIN_ALERT_STREAK.clear()
    main._SENT_LAST.clear()
    main._SENT_CNT.clear()
    return main, REGISTRY, old


def _teardown(main, REGISTRY, old):
    REGISTRY[_PLAT].login_suspect = old
    main._LOGIN_ALERT_STREAK.clear()
    main._SENT_LAST.clear()
    main._SENT_CNT.clear()


def test_two_burning_rounds_push_once(monkeypatch):
    """连续 ≥2 轮在燃推一条告警；当日去重不重推。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        users = [{"platforms": [_PLAT]}]
        main._channel_login_alert_sentinel([(users[0], n)], logger := logging.getLogger("t"))
        main._channel_login_alert_sentinel([(users[0], n)], logger)
        assert len(n.sent) == 1, "连续 2 轮在燃恰推 1 条（单轮瞬时风控不鸣）"
        title, desp = n.sent[0]
        assert _PLAT in desp and "登录" in desp, "词面带渠道与干预动作"
        main._channel_login_alert_sentinel([(users[0], n)], logger)
        assert len(n.sent) == 1, "当日去重（_SENT_LAST）不重推"
    finally:
        _teardown(main, REGISTRY, old)


def test_single_round_silent(monkeypatch):
    """单轮在燃不推（瞬时风控常态）。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert n.sent == []
    finally:
        _teardown(main, REGISTRY, old)


def test_recovery_notifies_once(monkeypatch):
    """在燃推过之后恢复 → 单条恢复通知；再一轮恢复不重推。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 1
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", False)
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 2, "恢复推单条通知"
        assert "恢复" in n.sent[1][1]
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 2, "恢复态不重复推"
    finally:
        _teardown(main, REGISTRY, old)


def test_streak_survives_restart(monkeypatch, tmp_path):
    """streak 持久化：跨进程重启累计（生产实录——12:47 重启清内存
    streak，70 分钟长轮+频繁重启下内存态永到不了 2=告警哑火）。
    形态：第一轮尾存盘 → 模拟重启（清内存+重载哨状态）→ 第二轮尾
    直接触发首鸣。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        monkeypatch.setattr(main, "_sent_state_path",
                            lambda: str(tmp_path / "sent.json"))
        users = [{"platforms": [_PLAT]}]
        main._channel_login_alert_sentinel([(users[0], n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 0, "重启前第一轮 streak=1 不鸣"
        # 模拟进程重启：内存全清 + 从哨状态文件回填
        main._LOGIN_ALERT_STREAK.clear()
        main._SENT_LAST.clear()
        main._SENT_CNT.clear()
        main._sent_load()
        main._channel_login_alert_sentinel([(users[0], n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 1, (
            "重启后 streak 从持久化继续（=2）应首鸣——内存态在长轮"
            "周期+频繁重启下永到不了 2（生产实录哑火）")
    finally:
        _teardown(main, REGISTRY, old)


def test_unrelated_platform_not_alerted(monkeypatch):
    """用户未启用该渠道 → 不推（多租户告警面按启用平台过滤）。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        for _ in range(3):
            main._channel_login_alert_sentinel(
                [({"platforms": ["ctrip"]}, n)], logging.getLogger("t"))
        assert n.sent == []
    finally:
        _teardown(main, REGISTRY, old)


# ---- merged from tests/test_r388_login_wall_precision.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    src = webui_full_src()
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
    src = webui_full_src() if False else webui_full_src()
    assert 'class="cmiss"' in src
    assert "舱位未标" in src
    # 只在真班次上标：条件里必须同时要求 code/depTime/arrTime
    i = src.find('class="cmiss"')
    ctx = src[max(0, i - 260):i]
    assert "f.code&&f.depTime&&f.arrTime" in ctx, ctx[-200:]


def test_cabin_missing_css_defined():
    src = webui_full_src()
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
    src = webui_full_src()
    assert "行李未标" in src
    assert "不代表无行李" in src
    i = src.find("行李未标")
    ctx = src[max(0, i - 260):i]
    assert "f.code&&f.depTime&&f.arrTime" in ctx, ctx[-200:]
    assert "!f.baggage" in ctx and "!f.carryon" in ctx, ctx[-200:]


# ---- merged from tests/test_r608_login_copy_matches_policy.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_login_header_says_all_required():
    w = _w()
    assert "同程/途牛建议" not in w, "登录页头部仍写着「同程/途牛建议」（已全改必须登录）"
    # r644 起登录分区补了智行 App，头部改写成「五个浏览器渠道 + 智行 App
    # 都必须登录」——意图（全部必须登录）不变，只是数量跟着真实卡片走。
    assert "都必须登录" in w, "登录页头部没有声明「都必须登录」"
    assert "智行 App" in w, "头部没提到智行 App（统一登录要求漏了一家）"


def test_login_req_table_is_all_required():
    """单一事实源：每个槽位都必须是「必须登录」。"""
    w = _w()
    i = w.index("const reqs={ctrip:")
    seg = w[i:i + 300]
    # r1063 T177：所有浏览器渠道统一双端 → 键从 6 个变成 9 个
    # （ctrip/ctrip_h5/qunar/fliggy/fliggy_h5/tongcheng/tongcheng_h5/
    #   tuniu/tuniu_h5）。断言"每个键都是必须登录"，不写死具体数量，
    # 免得下次加槽位又要改数字。
    import re as _re
    keys = _re.findall(r"(\w+):'必须登录'", seg)
    assert len(keys) >= 9, "槽位必须登录表少于 9 项：%s" % seg[:200]
    assert "ctrip_h5" in keys and "tongcheng_h5" in keys and "tuniu_h5" in keys, (
        "双端槽位没进「必须登录」表：%s" % keys)
    for bad in ("建议登录", "可匿名"):
        assert bad not in seg, "LOGIN_REQ 里仍有旧档位：%s" % bad


def test_header_mentions_split_sessions():
    """飞猪 PC/H5 是两套独立会话——这句必须保留，否则用户只登一边。"""
    w = _w()
    # 锚点用头部那句的固定前半（数量与 App 描述会随渠道增减而变）
    i = w.index("都必须登录（入口页可匿名浏览")
    seg = w[i:i + 360]
    assert "PC" in seg and "H5" in seg and "分别登录" in seg, (
        "头部没有说明飞猪两端要分别登录：%s" % seg)




def test_dual_slot_reuses_the_shared_slot_body():
    """飞猪双端不得自带一套 DOM——那套曾把「必须登录」漏掉（r608）。

    实测：同一页四家写「必须登录」，飞猪两端只有「PC 未登录 / H5 未登录」，
    读者会以为飞猪不需要登录。要求是两端各调一次 `slotBody`。
    """
    w = _w()
    # r1487：双端分支已并入 `const inner=(p==='qunar')? … :(dual? … : …)`
    # 的三元链（旧锚 `const inner=dual` 不存在了）。按新锚取面，判据不变。
    i = w.index("const dual=g.slots.length>1;")
    seg = w[i:i + 1200]
    # 半格走同一份 slotBody 的紧凑模式：仍复用同一函数（不会再次丢掉
    # requirement），只是省掉重复的账号段以保住五行等高（r608b）。
    # r1063 T177：双端分支已泛化为"任一双端卡"，不再只有飞猪那两个常量
    assert "g.slots.map(s=>slotBody(s,1))" in seg, (
        "双端分支没有复用 slotBody（会再次丢掉 requirement）")
    assert "lgShortStatus(pc)" not in seg, (
        "双端分支仍在用自带的状态渲染（不走统一口径）")




# ---- merged from tests/test_r644_login_section_covers_app.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)










# ---- merged from tests/test_r689_login_first_screen_not_expired.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOGIN = ('<hierarchy><node text="请输入手机号" bounds="[0,0][100,40]" />'
         '<node text="获取验证码" bounds="[0,60][100,90]" /></hierarchy>')
HOME = ('<hierarchy><node text="atom_flight_search_panel" bounds="[0,0][900,100]" />'
        + "".join('<node text="x%d" bounds="[0,%d][100,%d]" />' % (i, 200 + i * 10, 208 + i * 10)
                  for i in range(8))
        + '</hierarchy>')


class Dev:
    """第一屏登录页；深链后变首页。"""

    def __init__(self, reachable=True):
        self.reachable = reachable
        self.on_home = False
        self.calls = []

    def dump(self):
        self.calls.append(("dump",))
        return HOME if self.on_home else LOGIN

    def deep_link(self, uri):
        self.calls.append(("deep", uri))
        if self.reachable:
            self.on_home = True
        return self.reachable

    def keyevent(self, key):
        self.calls.append(("key", key))
        return True

    def current_activity(self):
        return "com.Qunar/.home.HomeActivity" if self.on_home else "com.Qunar/.uc.UCLoginByPhoneActivity"

    def app_stop(self, pkg):
        return True

    def app_start(self, pkg):
        return True


def _crawler():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.home_uri = "qunarphone://flight"
    c._snapshot_restored = True
    import logging
    c.logger = logging.getLogger("t")
    return c


def test_uses_deep_link_when_first_screen_is_login(monkeypatch):
    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c = _crawler()
    dev = Dev(reachable=True)
    xml = c._ensure_home(dev)
    assert "atom_flight_search_panel" in xml, \
        "首屏是登录页就直接放弃了，明明深链能进首页"
    assert ("deep", "qunarphone://flight") in dev.calls


def test_still_reports_login_when_deep_link_also_blocked(monkeypatch):
    """深链也进不去 → 返回登录页那帧，由调用方按 login 入账。"""
    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c = _crawler()
    xml = c._ensure_home(Dev(reachable=False))
    assert "请输入手机号" in xml, "深链失败时应把登录页原样交回"


def test_base_restore_treats_login_first_screen_as_logged_in(monkeypatch):
    """基类的「设备已登录就跳过恢复」不能把登录首屏当未登录。"""
    import crawlers.app_base as base
    monkeypatch.setattr(base.time, "sleep", lambda s: None)
    c = _crawler()
    c._snapshot_restored = False
    c.user_data_root = os.path.abspath("user_data")
    calls = []

    class Mgr:
        class store:
            @staticmethod
            def exists(name):
                return True

        @staticmethod
        def restore(name):
            calls.append("restore")
            return True, "restored"

    monkeypatch.setattr(c, "_snapshot_manager", lambda dev: Mgr())
    ok = c.restore_login_snapshot(Dev(reachable=True))
    assert ok is False
    assert "restore" not in calls, "登录首屏被当成未登录，又用旧快照覆盖了设备"


# ---- merged from tests/test_r973_login_suspect_is_per_round.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("r973")


class _RecLedger:
    """登录账本替身：只记 `note_result` 的调用形态。"""

    def __init__(self):
        self.calls = []

    def note_result(self, plat, ok, device_risk=False, **kw):
        self.calls.append({"plat": plat, "ok": bool(ok),
                           "device_risk": bool(device_risk)})
        return {}

    def rec(self, plat):
        return {}

    def signals(self, plat):
        return {"login_fail_streak": 0}

    def wait_s(self, plat, now=None):
        return 0

    def should_rotate(self, plat):
        return False


class _Crawler(AppCrawler):
    name = "app_probe973"
    package = ""
    LOGIN_FORM_MARKS = ()

    def __init__(self, rows=None, notes=None, boom=False):
        super().__init__({}, _LOG)
        self._rows = rows or []
        self._notes = notes or []
        self._boom = boom
        self._rec_ledger = _RecLedger()

    # 只替换登录账本与打分，其余走生产逻辑
    def _ledger(self):
        return self._rec_ledger

    def fetch(self, from_city, to_city, dates, ret_date=""):
        for path, status in self._notes:
            self.path_note(path, status)
        if self._boom:
            raise RuntimeError("boom")
        return list(self._rows)


def _assess_stub(calm=True):
    def _go(*a, **k):
        return {"level": "calm" if calm else "slow", "score": 0,
                "reasons": [], "advice": {"text": ""}}
    return _go


# ---------------------------------------------------------------------------
# 1. 核心：做过登录墙、但这一轮成功了 → 必须记成功，不许记登录失败
# ---------------------------------------------------------------------------
def test_stale_suspect_does_not_turn_success_into_login_failure(monkeypatch):
    monkeypatch.setattr(riskscore, "assess", _assess_stub())
    c = _Crawler(rows=[object()], notes=[("app-calendar", "ok")])
    c.login_suspect = True          # 上一轮留下的"终身标记"
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    calls = c._rec_ledger.calls
    assert calls, "成功轮次完全没进登录账本"
    assert calls[-1]["ok"] is True, \
        "取到数的轮次被记成登录失败：%r" % (calls,)
    assert calls[-1]["device_risk"] is False


def test_login_wall_this_round_still_recorded_as_failure(monkeypatch):
    """清零不等于"忽略登录墙"：**本轮**真遇到登录墙，照实记失败。"""
    monkeypatch.setattr(riskscore, "assess", _assess_stub(calm=False))
    c = _Crawler(rows=[], notes=[("app-login", "login")])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    calls = c._rec_ledger.calls
    assert calls and calls[-1]["ok"] is False
    assert calls[-1]["device_risk"] is True


def test_suspect_is_reset_even_when_fetch_raises(monkeypatch):
    monkeypatch.setattr(riskscore, "assess", _assess_stub())
    c = _Crawler(rows=[], notes=[], boom=True)
    c.login_suspect = True
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    assert c.login_suspect is False, "异常轮次没清零，标记会继续粘住"


# ---------------------------------------------------------------------------
# 2. 判据只认本轮证据
# ---------------------------------------------------------------------------
def test_round_signals_ignore_stale_flag_after_reset(monkeypatch):
    monkeypatch.setattr(riskscore, "assess", _assess_stub())
    c = _Crawler(rows=[object()], notes=[("app-calendar", "ok")])
    c.login_suspect = True
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    assert c._round_signals()["login_wall"] is False, \
        "本轮没有任何 login 证据，却仍报登录墙"


def test_round_signals_detect_login_status_in_round():
    c = _Crawler()
    c.path_note("app-login", "login")
    assert c._round_signals()["login_wall"] is True


# ---------------------------------------------------------------------------
# 3. 结构约束：清零必须发生在唯一入口，且渠道里不该再出现"只置不清"
# ---------------------------------------------------------------------------
def test_reset_happens_in_safe_fetch():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    i = src.find("def safe_fetch(")
    head = src[i:i + 1400]
    assert "self.login_suspect = False" in head, \
        "safe_fetch 开头没有按轮清零 login_suspect"
