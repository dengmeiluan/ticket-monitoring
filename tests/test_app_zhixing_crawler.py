# -*- coding: utf-8 -*-
"""智行 App 渠道：状态诚实、日历族产出、不伪造明细。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing import AppZhixingCrawler

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fixtures", "zhixing_list_dump.xml")


def _xml():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


class FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeRuntime:
    def __init__(self, ok=True, why="ready", device=None):
        self.ok, self.why = ok, why
        self.device_obj = device
        self.locks = 0

    def ensure_ready(self):
        return self.ok, self.why

    def device(self):
        return self.device_obj

    def device_lock(self, timeout=600):
        self.locks += 1
        return FakeLock()


class FakeDevice:
    def __init__(self, dumps=None, started=True):
        self.dumps = list(dumps or [])
        self.started = started
        self.calls = []

    def window_size(self):
        return (900, 1600)

    def app_start(self, pkg):
        self.calls.append(("app_start", pkg))
        return self.started

    def dump(self, retries=2):
        self.calls.append(("dump",))
        # 多页时依次出队，用尽后稳定返回最后一页（模拟"页面没变"）
        if len(self.dumps) > 1:
            return self.dumps.pop(0)
        return self.dumps[0] if self.dumps else ""

    def current_activity(self):
        return "cn.suanya.zhixing/com.app.main.entrance.MainActivity"

    def screencap(self):
        return b""

    def tap(self, x, y):
        self.calls.append(("tap", x, y))
        return True

    def keyevent(self, key):
        self.calls.append(("key", key))
        return True


def _make(dumps=None, runtime_ok=True, why="ready", with_device=True):
    dev = FakeDevice(dumps if dumps is not None else [_xml()])
    rt = FakeRuntime(ok=runtime_ok, why=why, device=dev if with_device else None)
    # boot_wait 置 0：真实冷启动等待 10s，测试里不该睡
    c = AppZhixingCrawler({"android": {"enabled": True},
                           "app_boot_wait_s": 0},
                          logging.getLogger("t"))
    c._runtime = rt
    c._skip_route = True   # 导航是 UI 交互，另有真机验证；单测只测解析
    return c, rt, dev


def test_disabled_returns_empty_and_notes_reason():
    c, _, _ = _make(runtime_ok=False, why="disabled")
    out = c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert out == []
    assert c.paths and c.paths[0]["status"] in ("unsupported", "error")


def test_calendar_prices_produced_from_real_dump():
    c, _, _ = _make()
    out = c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert out, "应产出日历价"
    assert 450.0 in {f.price for f in out}
    for f in out:
        assert not f.flight_no, "未登录不得伪造航班号"


def test_calendar_rows_marked_as_calendar_path():
    c, _, _ = _make()
    c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert "calendar" in {p["status"] for p in c.paths}


def test_masked_prices_never_become_zero():
    c, _, _ = _make()
    out = c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert all(f.price > 0 for f in out), [f.price for f in out]


def test_login_state_is_not_recorded_as_empty():
    c, _, _ = _make(dumps=['<hierarchy><node text="立即登录" '
                           'bounds="[0,0][100,40]" /></hierarchy>'])
    out = c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert out == []
    assert any(p["status"] == "login" for p in c.paths)
    assert not any(p["status"] == "empty" for p in c.paths)


def test_empty_requires_explicit_copy():
    c, _, _ = _make(dumps=['<hierarchy><node text="抱歉，没有找到符合条件的航班" '
                           'bounds="[0,0][100,40]" /></hierarchy>'])
    out = c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert out == []
    assert any(p["status"] == "empty" for p in c.paths)


def test_unknown_page_marks_blocked_not_empty():
    c, _, _ = _make(dumps=["<hierarchy></hierarchy>"])
    c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert not any(p["status"] == "empty" for p in c.paths)


def test_unknown_page_does_not_trip_captcha_breaker():
    """页面结构不认识 ≠ 被验证码拦。

    pacing.classify_failure 把 blocked 归为 captcha（300s 阶梯熔断），
    而"App 改版"重试也不会变好，更不该让整个渠道停摆 5 分钟——
    实机踩过：第一次识别失败就把 App 渠道熔断 300s。
    """
    from core.pacing import classify_failure
    c, _, _ = _make(dumps=["<hierarchy></hierarchy>"])
    c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    statuses = [p["status"] for p in c.paths]
    kind = classify_failure(statuses, note="")
    assert kind != "captcha", statuses


def test_package_and_name():
    c, _, _ = _make()
    assert c.name == "app_zhixing"
    assert c.package == "cn.suanya.zhixing"
    assert c.login_url()


def test_uses_device_lock():
    c, rt, _ = _make()
    c.safe_fetch("SHA", "BJS", ["2026-10-29"])
    assert rt.locks >= 1


def test_dates_filtered_to_requested():
    """App 日历是 7 天条；只产出调用方请求的日期。"""
    c, _, _ = _make()
    out = c.safe_fetch("SHA", "BJS", ["2026-10-30"])
    assert {f.depart_date for f in out} == {"2026-10-30"}


def test_out_of_window_date_is_explained_not_silent():
    """目标日期在日历窗口外时必须说明——否则「0 条」读不出原因。

    智行日历条只覆盖首屏约 7–8 天，配置里的远期日期永远命中 0 条。
    「这几天没价」是数据，「不在窗口内」是能力边界，处置完全不同。
    """
    c, _, _ = _make()
    out = c.safe_fetch("SHA", "BJS", ["2027-03-15"])
    assert out == []
    rec = [p for p in c.paths if p["path"] == "日历"][-1]
    assert "窗口外" in rec["detail"], rec["detail"]


def test_try_long_calendar_signature_matches_callsite():
    """_try_long_calendar 的调用不能带它已不接受的参数。

    实测踩过：撤销"复用旧帧"的优化时只改了注释、没改调用，结果
    open_date_dialog 收到未知 kwarg → TypeError 被 `except` 咽成
    "长窗口日历异常" → 静默回落到首页 → 三轮全 0 条，日志里只有
    一行 TypeError 看不出根因。
    """
    import inspect

    sig = inspect.signature(AppZhixingCrawler._try_long_calendar)
    assert list(sig.parameters) == ["self", "dev", "keep_open"], \
        list(sig.parameters)
    # keep_open 必须可省略：老调用点只传 dev
    assert sig.parameters["keep_open"].default is False

    from crawlers.app_zhixing_nav import open_date_dialog
    sig2 = inspect.signature(open_date_dialog)
    assert list(sig2.parameters) == ["dev", "log"], list(sig2.parameters)


def test_long_calendar_failure_is_logged_not_silent():
    """长窗口失败要留痕，且回落路径仍能产出（首页条）。"""
    c, _, _ = _make(dumps=[_real_fixture()])
    c.safe_fetch("SHA", "CAN", ["2026-10-30"])
    # 不论长窗口成不成，路径账里必须有可读结论
    assert c.paths, "没有任何路径记录 = 静默失败"
    assert all(p["detail"] for p in c.paths), c.paths
    """App 的日历通路必须落在 CAL_PATH_FAMILY 里。

    日历族是按**中文通路名**匹配的（`startswith(("日历","窗历"))`），
    用来让"只出价不证明细"的通路共享一套复发账。若 App 用英文路径名
    （如 app-calendar-dialog），族内匹配不到——健康/节流会把同一条
    业务通路当成两个东西，一边报成功一边报劣化。
    """
    from core.models import CAL_PATH_FAMILY
    c, _, _ = _make(dumps=[_real_fixture()])
    c.safe_fetch("SHA", "CAN", ["2026-10-30"])
    cal_paths = [p["path"] for p in c.paths if p["status"] == "calendar"]
    assert cal_paths, [p["path"] for p in c.paths]
    for name in cal_paths:
        assert name.startswith(tuple(CAL_PATH_FAMILY)), name


def _real_fixture():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def test_long_calendar_dialog_preferred_over_strip():
    """页面是「选择日期」弹层时，走长窗口解析（跨月），不用首页条。"""
    fix = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "zhixing_date_dialog_dump.xml")
    with open(fix, encoding="utf-8") as f:
        dialog_xml = f.read()
    c, _, _ = _make(dumps=[dialog_xml])
    out = c.safe_fetch("SHA", "CAN", ["2026-11-03"])
    assert out, "弹层里 11-03 有价，应产出"
    assert out[0].price == 256.0
    assert "calendar-dialog" in out[0].prov
    assert any(p["path"] == "日历" for p in c.paths)


# ---- r631：长窗口日历要等到价格渲染出来再取 ----
def _cal_xml(prices):
    """造一份日期弹层 XML；prices 是 [(ymd, price|None), ...]。"""
    cells = []
    for ymd, price in prices:
        ptxt = ("" if price is None else u"¥" + str(price))
        cells.append(
            '<node index="0" text="" resource-id="flight_calendar_date_cell-%s"'
            ' class="android.view.ViewGroup" bounds="[0,0][10,10]">'
            '<node index="0" text="%s" resource-id='
            '"flight_calendar_date_cell_price_text-%s" class='
            '"android.widget.TextView" bounds="[0,0][10,10]" /></node>'
            % (ymd, ptxt, ymd))
    return ('<?xml version="1.0"?><hierarchy rotation="0">'
            '<node index="0" text="" class="android.widget.FrameLayout">'
            + "".join(cells) + "</node></hierarchy>")


def test_long_calendar_waits_for_prices(monkeypatch):
    """第一帧没价、第二帧才有价时，必须返回第二帧。

    实测：弹层打开瞬间 73 格全无价，2s 后 37 格有价。取第一帧
    就等于「长窗口日历有入口但一条也采不到」。
    """
    from crawlers import app_zhixing as mod
    from crawlers import app_zhixing_calendar as cal
    from crawlers import app_zhixing_nav as nav

    frames = [_cal_xml([("2026-11-05", None)]),
              _cal_xml([("2026-11-05", None)]),
              _cal_xml([("2026-11-05", 266)])]
    monkeypatch.setattr(nav, "open_date_dialog",
                        lambda dev, log=None: (True, "已打开"))
    monkeypatch.setattr(nav, "close_date_dialog", lambda dev: None)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    class Dev:
        def __init__(self):
            self.i = 0
            self.dumps = 0

        def dump(self):
            self.dumps += 1
            x = frames[min(self.i, len(frames) - 1)]
            self.i += 1
            return x

    dev = Dev()
    c = AppZhixingCrawler({"action_timeout_s": 30}, logging.getLogger("t"))
    xml = c._try_long_calendar(dev)
    assert dev.dumps >= 3, "没有轮询到价格出现就返回了（取的是第一帧）"
    rows = cal.parse_date_dialog(xml)
    assert any(r.get("price") for r in rows), "返回的仍是没价的那一帧"


def test_long_calendar_gives_up_when_no_price_ever(monkeypatch):
    """一直没有价时不能死等，且返回最后一帧（由上层判 empty）。"""
    from crawlers import app_zhixing as mod
    from crawlers import app_zhixing_calendar as cal
    from crawlers import app_zhixing_nav as nav

    monkeypatch.setattr(nav, "open_date_dialog",
                        lambda dev, log=None: (True, "已打开"))
    monkeypatch.setattr(nav, "close_date_dialog", lambda dev: None)
    clock = {"t": 0.0}
    monkeypatch.setattr(mod.time, "time", lambda: clock["t"])
    monkeypatch.setattr(mod.time, "sleep", lambda s: clock.__setitem__(
        "t", clock["t"] + s))

    class Dev:
        def __init__(self):
            self.dumps = 0

        def dump(self):
            self.dumps += 1
            return _cal_xml([("2026-11-05", None)])

    dev = Dev()
    c = AppZhixingCrawler({"action_timeout_s": 30}, logging.getLogger("t"))
    xml = c._try_long_calendar(dev)
    assert xml, "超时后应返回最后一帧，而不是空串"
    assert dev.dumps < 40, "轮询次数异常（可能没有超时边界）"
    assert not any(r.get("price") for r in cal.parse_date_dialog(xml))


# ---- r634：远期日期必须产出「航班明细」，日历价只能兜底 ----
def test_detail_rows_win_over_calendar(monkeypatch):
    """主流程要先走明细，明细拿到就返回明细（有航班号/时刻），
    不能因为有日历价就直接把日历价当结果交出去。"""
    c, _, dev = _make()
    c._skip_route = False

    detail = [{"flight_no": "CA4538", "depart_time": "23:05", "price": 279}]
    calls = []

    def fake_cal(dev_, keep_open=False):
        calls.append("calendar")
        return _cal_xml_str()

    def fake_detail(dev_, fc, tc, ds):
        calls.append("detail")
        return c._to_prices(detail, fc, tc, ds[0]), False

    c._try_long_calendar = fake_cal
    c._enter_detail_and_parse = fake_detail
    c._query_unchanged = lambda dev, fc, tc: True
    c._route_unchanged = lambda dev, fc, tc: True
    out = c.safe_fetch("SHA", "CAN", ["2026-11-07"])
    assert calls[0] == "calendar", "应先读日历（它是明细的入口）"
    assert "detail" in calls, "没有尝试进入明细页"
    assert len(out) == 1
    assert out[0].flight_no == "CA4538", "返回的不是明细行：%s" % out[0]
    assert out[0].price == 279


def test_calendar_is_fallback_when_detail_fails(monkeypatch):
    """明细拿不到时回退到日历价，而不是交白卷。"""
    c, _, dev = _make()
    c._skip_route = False
    c._try_long_calendar = lambda dev_, keep_open=False: _cal_xml_str()
    c._enter_detail_and_parse = lambda *a, **k: ([], False)
    c._route_unchanged = lambda dev, fc, tc: True
    c._close_calendar = lambda dev_: None
    out = c.safe_fetch("SHA", "CAN", ["2026-11-07"])
    assert out, "明细失败时不应交白卷"
    assert out[0].price is not None
    assert "calendar" in (out[0].extra or ""), "回退的应是日历价"


def _cal_xml_str():
    """一份能让 parse_date_dialog 认出 11-07 有价的弹层 XML。"""
    return ('<?xml version="1.0"?><hierarchy rotation="0">'
            '<node index="0" text="" resource-id='
            '"Search_Calendar_Dialog_Title" class="android.widget.TextView"'
            ' bounds="[0,0][10,10]" />'
            '<node index="0" text="" resource-id='
            '"flight_calendar_date_cell-2026-11-07" class='
            '"android.view.ViewGroup" bounds="[0,0][10,10]">'
            '<node index="0" text="¥256" resource-id='
            '"flight_calendar_date_cell_price_text-2026-11-07" class='
            '"android.widget.TextView" bounds="[0,0][10,10]" /></node>'
            '</hierarchy>')


def test_all_dates_get_detail_rows(monkeypatch):
    """配置多个日期时，每个日期都要各自产出明细。

    其它渠道都是 `for date in dates` 逐日采集（ctrip/qunar）；只处理
    dates[0] 会让其余日期静默丢数据——用户在页面上配了 3 天，只回 1 天。
    """
    c, _, dev = _make()
    c._skip_route = False
    seen = []

    def fake_one(dev_, fc, tc, target, first):
        seen.append(target)
        return ([{"flight_no": "CA100" + target[-1], "depart_time": "08:00",
                  "price": 300 + len(seen)}], None)

    c._one_date_detail = fake_one
    c._try_long_calendar = lambda dev_, keep_open=False: _cal_xml_str()
    c._route_unchanged = lambda dev, fc, tc: True
    c._close_calendar = lambda dev_: None
    c._park_at_home = lambda dev_: True
    out = c.safe_fetch("SHA", "CAN",
                       ["2026-11-07", "2026-11-08", "2026-11-09"])
    assert seen == ["2026-11-07", "2026-11-08", "2026-11-09"], \
        "没有逐日期采集：%s" % seen
    assert len(out) == 3, "应产出 3 个日期的明细，实际 %d" % len(out)
    assert {p.depart_date for p in out} == {
        "2026-11-07", "2026-11-08", "2026-11-09"}, \
        "日期覆盖不全：%s" % {p.depart_date for p in out}
    ok_dates = [p["date"] for p in c.paths
                if p["path"] == "航班明细" and p["status"] == "ok"]
    assert len(ok_dates) == 3, "每个日期都要各记一条账本：%s" % ok_dates


def test_one_date_failure_does_not_drop_others(monkeypatch):
    """某个日期失败不能连累其它日期。

    r674 起「解析不到价」不再记 empty（那是「没采到」，不是「没票」）——
    失败日应记 timeout，且原因要写清楚；其它日期照常产出。
    """
    c, _, dev = _make()
    c._skip_route = False

    def fake_one(dev_, fc, tc, target, first):
        if target == "2026-11-08":
            return [], None
        return ([{"flight_no": "CA1000", "depart_time": "08:00",
                  "price": 300}], None)

    c._one_date_detail = fake_one
    c._try_long_calendar = lambda dev_, keep_open=False: _cal_xml_str()
    c._route_unchanged = lambda dev, tc, tt: True
    c._route_unchanged = lambda dev, fc, tc: True
    c._close_calendar = lambda dev_: None
    c._park_at_home = lambda dev_: True
    out = c.safe_fetch("SHA", "CAN", ["2026-11-07", "2026-11-08"])
    assert len(out) == 1 and out[0].depart_date == "2026-11-07"
    failed = [(p["status"], p["date"]) for p in c.paths
              if p["path"] == "航班明细" and p["date"] == "2026-11-08"]
    assert failed and failed[0][0] == "timeout", failed
    # 失败日不得冒充「这天没票」
    assert not [p for p in c.paths
                if p["path"] == "航班明细" and p["status"] == "empty"], c.paths


def test_detail_blocker_is_not_recorded_as_empty(monkeypatch):
    """明细页撞上验证码/人脸时必须记拦截，不能伪装成「这天没票」。

    用户明确要求：App 的广告/验证码弹窗要和 PC/H5 同一套口径记录、
    识别、区分。把「需要人操作」写成 empty，是最误导人的一种。
    """
    from crawlers.app_blockers import Block

    c, _, dev = _make()
    c._skip_route = False

    def fake_one(dev_, fc, tc, target, first):
        return [], Block(kind="captcha", detail="滑块验证", close_xy=None)

    c._one_date_detail = fake_one
    c._try_long_calendar = lambda dev_, keep_open=False: _cal_xml_str()
    c._route_unchanged = lambda dev, fc, tc: True
    c._close_calendar = lambda dev_: None
    c._park_at_home = lambda dev_: True
    out = c.safe_fetch("SHA", "CAN", ["2026-11-07", "2026-11-08"])
    assert out == []
    kinds = [(p["path"], p["status"]) for p in c.paths]
    assert ("app-blocker", "captcha") in kinds, kinds
    assert not [k for k in kinds if k == ("航班明细", "empty")], \
        "拦截被误记成 empty：%s" % kinds
    # 撞上验证码后不该继续跑下一个日期（只会连环误报）
    assert len([k for k in kinds if k[1] == "empty"]) == 0
