# -*- coding: utf-8 -*-
"""r805as：去哪儿 App「设城市」点击没生效时要重试，不能干等 30 秒。

账本实证（2026-11-01，`fetch_paths` 里 app_qunar 的 78 条 timeout）：
    43 × 未取到可用结果：set-city-dep
    33 × 未取到可用结果：pick-date-failed
     8 × 没能打开机票首页
     5 × 未取到可用结果：set-city-arr
「设出发城市」占一半以上——这才是这条通路不稳的**主因**，不是玄学时序。

`_set_city` 原实现「点城市位 → 等城市页 → 选城市」，但**只点一次**。
城市位是 RN 元素，滚动/转场后那一帧的坐标偶尔点不中；点不中之后循环里
既看不到城市页、也找不到搜索框，只能空转到 30 秒超时，账本记
`set-city-dep`，人眼看是「这条通路时好时坏」。

修法（两条，均以「页面事实」为准）：
  1. 循环开头：仍在首页且城市还没变成目标 → 用**新 dump 的坐标**重试点击
     （上限 3 次）；城市已是目标 → 直接成功（覆盖「上海虹桥」这类后缀）；
  2. 重试耗尽仍在首页 → **立刻失败**，不在首页上找搜索框空转到 deadline。

**本用例只覆盖逻辑层**（替身设备）；真机端到端复验仍待做。
"""
import itertools
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEP = "com.Qunar:id/atom_flight_tv_dep_city"


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """这些用例只用替身设备，等帧一律不真等（否则一条要 14 秒）。"""
    import crawlers.app_qunar as mq
    monkeypatch.setattr(mq, "_sleep", lambda s: None)
    monkeypatch.setattr(mq.time, "sleep", lambda s: None)
    # 重拍按时间间隔判（首页有动图，不能比整页快照）；用例里把间隔压到 0
    monkeypatch.setattr(mq, "_CITY_RETAP_GAP_S", 0.0)


def _n(rid, text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="%s" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, rid, x1, y1, x2, y2))


def _home(city):
    return ('<hierarchy>'
            + _n(DEP, city, 60, 320, 300, 380)
            + _n("", "搜索", 60, 900, 700, 980)
            + '</hierarchy>')


class Dev:
    """替身：第 N 次点城市位时把城市「设成」目标（模拟城市页选中后回首页）。"""

    def __init__(self, ok_on_tap=None):
        self.taps = []
        self.ok_on_tap = ok_on_tap      # None = 点了也没成
        self.city = "北京"
        self.dep_taps = 0

    def dump(self):
        return _home(self.city)

    def tap(self, x, y):
        self.taps.append((x, y))
        if 320 <= y <= 380:
            self.dep_taps += 1
            if self.ok_on_tap is not None and self.dep_taps >= self.ok_on_tap:
                self.city = "上海"
        return True

    def input_text(self, s):
        return True

    def keyevent(self, k):
        return True


def _crawler():
    from crawlers.app_qunar import AppQunarCrawler
    return AppQunarCrawler.__new__(AppQunarCrawler)   # 不需要配置/日志


def test_retaps_when_first_tap_did_not_register():
    """第一次点不中、第二次点中 → 必须重试并成功。"""
    dev = Dev(ok_on_tap=2)
    assert _crawler()._set_city(dev, _home("北京"), "上海", side="dep") is True
    assert dev.city == "上海", "城市没真的设成上海"
    assert dev.dep_taps == 2, (
        "城市位被点了 %d 次；首次点不中时必须重试一次" % dev.dep_taps)


def test_fails_fast_instead_of_spinning_to_deadline():
    """永远点不开 → 重试 3 次后立刻失败，不许空转到 30 秒。"""
    dev = Dev(ok_on_tap=None)
    assert _crawler()._set_city(dev, _home("北京"), "上海", side="dep") is False
    assert dev.dep_taps == 3, (
        "应为「首次 + 2 次重试」共 3 次，实际 %d 次" % dev.dep_taps)


def test_returns_true_when_city_already_target():
    """首页城市已是目标时直接成功，不点也不等。"""
    dev = Dev(ok_on_tap=1)
    assert _crawler()._set_city(dev, _home("上海"), "上海", side="dep") is True
    assert not dev.taps, "已经是目标城市却还去点：%s" % dev.taps


def test_accepts_airport_suffix_text():
    """城市位显示「上海虹桥」也该算已设成上海（不是只有精确相等）。"""
    dev = Dev(ok_on_tap=1)
    xml = ('<hierarchy>' + _n(DEP, "上海虹桥", 60, 320, 300, 380)
           + '</hierarchy>')
    assert _crawler()._set_city(dev, xml, "上海", side="dep") is True
    assert not dev.taps, "带机场后缀时被当成「没设成」又去点了：%s" % dev.taps


def test_failure_writes_a_screen_snapshot(tmp_path, monkeypatch):
    """失败时必须有「现场」：账本只写 set-city-dep，看不出卡在哪一屏。

    重试上线后生产仍有 `set-city-dep`（2026-11-01 17:31 SHA→BKK）。没有
    现场快照就只能继续猜「是不是又点空了」——这里把失败当刻的屏幕节点
    落盘，下一次失败可直接看到当时首页上有什么。
    """
    import crawlers.app_qunar as m

    _tick = itertools.count(1)

    class _T:
        @staticmethod
        def sleep(_s):
            return None

        @staticmethod
        def time():
            # 必须**递增**：新实现点完会轮询 6 秒等城市页，时间冻结就永远出不来
            return float(next(_tick))

        strftime = staticmethod(lambda fmt: "20261101_000000")

    monkeypatch.setattr(m, "time", _T)
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path / "scene"))
    dev = Dev(ok_on_tap=None)
    assert m.AppQunarCrawler.__new__(m.AppQunarCrawler)._set_city(
        dev, _home("北京"), "上海", side="dep") is False
    got = sorted((tmp_path / "scene").glob("qunar_app_*_setcity-dep.txt"))
    assert got, "失败时没有落现场快照，事后无从定位"
    body = got[0].read_text(encoding="utf-8")
    assert "北京" in body and "搜索" in body, (
        "现场快照缺屏幕关键文案：%r" % body[:160])


class BrokenHomeDev(Dev):
    """首页「形似而神不似」：日期行/搜索都在，城市控件却没有 id。

    现场实证（debug/scene/qunar_app_20261101_181820_setcity-noid-arr.txt）：
    这一屏的城市行只剩 content-desc、resource-id 整片退化成 "arg"，顶部还
    挂着上一轮的路由头——`_is_flight_home` 照样判「就是首页」，退栈救不回。
    """

    def __init__(self, recover=True):
        super().__init__(ok_on_tap=None)
        self.phase = 0
        self.stopped = 0
        self.started = 0
        self.recover = recover

    def dump(self):
        if self.phase == 0 or not self.recover:
            return ('<hierarchy>'
                    '<node text="2月14日" bounds="[60,500][300,560]" />'
                    '<node text="机票查询" bounds="[42,724][858,799]" />'
                    '</hierarchy>')
        return _home("上海")

    def app_stop(self, pkg):
        self.stopped += 1

    def app_start(self, pkg):
        self.started += 1
        self.phase = 1

    def deep_link(self, uri):
        return True


def test_broken_home_triggers_one_hard_reset(monkeypatch):
    """残缺首页 → 杀进程重建一次，重建后能认城市位就算成功。"""
    import crawlers.app_qunar as m
    monkeypatch.setattr(m, "_sleep", lambda s: None)
    dev = BrokenHomeDev(recover=True)
    c = m.AppQunarCrawler.__new__(m.AppQunarCrawler)
    c._home_hard_reset = False          # fetch() 每轮会这样置位
    assert c._set_city(dev, dev.dump(), "上海", side="dep") is True
    assert (dev.stopped, dev.started) == (1, 1), (
        "残缺首页应重启一次（实际 stop=%d start=%d）" % (dev.stopped, dev.started))


def test_hard_reset_happens_at_most_once_per_round(monkeypatch):
    """重建后仍认不到 → 直接失败，不许每步都重启 App。"""
    import crawlers.app_qunar as m
    monkeypatch.setattr(m, "_sleep", lambda s: None)
    dev = BrokenHomeDev(recover=False)
    c = m.AppQunarCrawler.__new__(m.AppQunarCrawler)
    c._home_hard_reset = False
    assert c._set_city(dev, dev.dump(), "上海", side="dep") is False
    assert dev.stopped == 1, "同一轮内被重启了 %d 次" % dev.stopped
    assert c._set_city(dev, dev.dump(), "上海", side="arr") is False
    assert dev.stopped == 1, "第二次进入又重启了 App"


class SlowCityDev(Dev):
    """点城市位后先是转场帧，之后才出现城市页（横屏实测 >2s）。

    旧逻辑第二拍会落到**已打开的城市页**列表上（现场 2026-11-01 18:30
    的 1600×900 横屏就是这样把状态搅乱、最后停在首页记 set-city-dep）。
    """

    def __init__(self):
        super().__init__(ok_on_tap=None)
        self.phase = "home"
        self.frames = 0
        self.mis_taps = 0       # 落到城市页上的点击次数（旧逻辑会 >0）

    def dump(self):
        if self.phase == "transition":
            self.frames += 1
            if self.frames >= 2:
                self.phase = "city"
        if self.phase == "home":
            return _home(self.city)
        if self.phase == "city":
            return ('<hierarchy>'
                    + _n("com.Qunar:id/city_suggest_view", "", 0, 0, 4, 4)
                    + _n("", "上海（不限机场）", 60, 600, 700, 660)
                    + '</hierarchy>')
        return '<hierarchy><node text="加载中" bounds="[0,0][10,10]" /></hierarchy>'

    def tap(self, x, y):
        if self.phase == "city":
            if 600 <= y <= 660:
                self.city = "上海"
                self.phase = "home"
            else:
                self.mis_taps += 1
            return True
        if self.phase == "home":
            self.phase = "transition"
        return True


def test_waits_for_transition_instead_of_retapping_into_city_page():
    dev = SlowCityDev()
    c = _crawler()
    assert c._set_city(dev, _home("北京"), "上海", side="dep") is True
    assert dev.mis_taps == 0, (
        "城市页已经打开还继续点（%d 次），会点到列表/返回把状态搅乱"
        % dev.mis_taps)


def test_pick_date_failure_also_saves_scene():
    """选日失败（第二大超时来源）同样要留现场。"""
    import io
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "crawlers", "app_qunar.py")
    src = io.open(p, encoding="utf-8").read()
    for tag in ('_save_fail_scene("pickdate-open"',
                '_save_fail_scene("pickdate-cell"'):
        assert tag in src, "选日失败没有落现场快照：%s" % tag

class EmptyFrameDev(Dev):
    """选完出发城市后先给几帧空页（转场），再看得到首页。"""

    def __init__(self):
        super().__init__(ok_on_tap=None)
        self.empty = 0
        self.city = "上海"      # 出发城市已设好；这里测到达城市

    def dump(self):
        if self.empty < 2:
            self.empty += 1
            return ""
        return ('<hierarchy>'
                + _n("com.Qunar:id/atom_flight_tv_arr_city", "曼谷",
                     700, 330, 852, 389)
                + '</hierarchy>')


def test_empty_frame_after_city_pick_is_waited_not_failed():
    dev = EmptyFrameDev()
    c = _crawler()
    assert c._set_city(dev, "", "曼谷", side="arr") is True, (
        "选完出发城市后的空帧被当成「没有城市控件」，整轮 set-city-arr")

def test_ineffective_tap_saves_a_screenshot(tmp_path, monkeypatch):
    """「点了没反应」时要留一张屏（浮层/输入法不进无障碍树，视图树看不出来）。"""
    png = bytes([137]) + b"PNG-fake"

    class ShotDev(Dev):
        def __init__(self):
            super().__init__(ok_on_tap=None)
            self.shots = 0

        def screencap(self):
            self.shots += 1
            return png

    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path / "scene"))
    dev = ShotDev()
    assert _crawler()._set_city(dev, _home("北京"), "上海", side="dep") is False
    got = list((tmp_path / "scene").glob("qunar_app_*tap1-dep.png"))
    assert got, "第一次点不动时没有留屏幕截图"
    assert got[0].read_bytes() == png
    assert dev.shots, "screencap 没被调用"

class HiddenMarkDev(Dev):
    """首页视图树里就带隐藏的 city_suggest_view（预加载）——只看 id 会把首页判成城市页。"""

    def __init__(self):
        super().__init__(ok_on_tap=None)
        self.phase = "home"
        self.dep_taps = 0

    def dump(self):
        if self.phase == "home":
            return (_home(self.city).replace(
                        "</hierarchy>",
                        _n("com.Qunar:id/city_suggest_view", "", 0, 0, 2, 2)
                        + "</hierarchy>"))
        return ('<hierarchy>'
                + _n("com.Qunar:id/city_suggest_view", "", 0, 0, 4, 4)
                + _n("", "上海（不限机场）", 60, 600, 700, 660)
                + '</hierarchy>')

    def tap(self, x, y):
        if self.phase == "city":
            if 600 <= y <= 660:
                self.city = "上海"
                self.phase = "home"
            return True
        self.dep_taps += 1
        if self.dep_taps >= 2:
            self.phase = "city"
        return True


def test_hidden_city_mark_on_home_does_not_block_retap():
    """首页自带隐藏 city_suggest_view 时，也必须能识别「城市页没开」并重拍。"""
    dev = HiddenMarkDev()
    assert _crawler()._set_city(dev, dev.dump(), "上海", side="dep") is True
    assert dev.dep_taps == 2, (
        "首页的隐藏 mark 把「没打开」判成了「已打开」，没有重拍（实际 %d 次）"
        % dev.dep_taps)

def test_login_wall_is_reported_as_login_not_set_city():
    """会话过期时首页被登录页顶掉：必须记 login，不能记 set-city-dep。

    现场实证（2026-11-01 21:28）：快照恢复已报「快照已失效（仍停在登录墙）」，
    账本却仍记 set-city-dep——把「该去重登」误导成「选择器坏了」。
    """
    wall = ('<hierarchy><node text="请输入手机号" bounds="[0,0][100,40]" />'
            '<node text="获取验证码" bounds="[0,60][100,90]" /></hierarchy>')
    dev = Dev(ok_on_tap=None)
    c = _crawler()
    c.paths = []
    c.login_suspect = False

    def _note(kind, status="", **kw):
        c.paths.append({"path": kind, "status": status})

    c.path_note = _note
    assert c._set_city(dev, wall, "上海", side="dep") is False
    assert c.login_suspect is True, "登录墙没被识别成登录态"
    assert any(p["path"] == "app-login" and p["status"] == "login"
               for p in c.paths), "没有记 app-login/login"
    assert not dev.taps, "登录墙上还去点城市位"


CITY_MARK = "com.Qunar:id/city_suggest_view"
DEALS_ROWS = [_n("", "国内", 106, 327, 146, 355),
              _n("", "国际", 268, 327, 308, 355),
              _n("", "往返", 430, 327, 470, 355)]


def _city_page(search_expanded=False, extra_rows=()):
    """城市页替身：停在国际档，目标城市只在搜索框里能选到。"""
    rows = [
        '<node text="" resource-id="%s" class="android.widget.FrameLayout"'
        ' bounds="[0,0][900,1600]" />' % CITY_MARK,
        # 页面最顶部整条（收起态的 qd_placeholder_v）：点它的中心等于点返回
        '<node text="" resource-id="com.Qunar:id/qd_placeholder_v"'
        ' class="android.widget.FrameLayout" bounds="[0,0][900,110]" />',
        _n("", "国内/港澳台", 40, 240, 300, 280),
        _n("", "国际", 600, 240, 700, 280),
        _n("", "热门城市", 20, 400, 400, 430),
        _n("", "东京", 40, 440, 120, 480),
    ]
    rows.extend(extra_rows)
    if search_expanded:
        rows.append('<node class="android.widget.EditText"'
                    ' bounds="[40,150][860,200]" />')
    rows.append(_n("", "搜索国家/城市/景点等", 40, 150, 860, 200))
    return "<hierarchy>" + "".join(rows) + "</hierarchy>"


class SearchDev:
    """替身：城市页停在国际档；「伦敦」只能经搜索框选中。

    `landing` 控制点中搜索结果后落在哪：home（正常）/ deals（特价页，
    实测 22:08 的失败现场）。
    """

    def __init__(self, landing="home"):
        self.city = "北京"
        self.page = "home"
        self.expanded = False
        self.tab_taps = []
        self.typed = ""
        self.landing = landing
        self.taps = []

    def dump(self):
        if self.page == "home":
            return _home(self.city)
        if self.page == "deals":
            return ("<hierarchy>"
                    + '<node text="" resource-id="%s"'
                    ' class="android.widget.FrameLayout"'
                    ' bounds="[0,0][900,1600]" />' % CITY_MARK
                    + "".join(DEALS_ROWS) + "</hierarchy>")
        rows = []
        if self.expanded:
            rows.append(_n("", "伦敦（不限机场）", 60, 520, 700, 560))
        return _city_page(self.expanded, rows)

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.page == "home":
            if 320 <= y <= 380:
                self.page = "city"
            return True
        if self.page != "city":
            return True
        if 240 <= y <= 280:                  # 档位行：不该被点
            self.tab_taps.append(x)
            return True
        if 150 <= y <= 200:                  # 搜索占位行/输入框
            self.expanded = True
            return True
        if 520 <= y <= 560:                  # 搜索结果
            self.page = self.landing
            if self.landing == "home":
                self.city = "伦敦"
        return True

    def input_text(self, s):
        self.typed = s
        return True

    def keyevent(self, k):
        return True


def test_intl_city_is_selected_through_search_without_touching_tabs():
    """国际城市走搜索框；**不点「国内/国际」档位**。

    真机探针（2026-11-01 22:22，空载 dump≈2.2s）：点搜索占位行 → 输入
    「伦敦」→ 点「伦敦（不限机场）」→ 回首页且到达城市位变伦敦，全程 43s，
    不需要碰档位按钮。
    """
    dev = SearchDev()
    assert _crawler()._set_city(dev, _home("北京"), "伦敦", side="dep") is True
    assert dev.city == "伦敦"
    assert dev.typed == "伦敦", "没走搜索框"
    assert not dev.tab_taps, "又去点「国内/国际」档位了：%s" % dev.tab_taps


def test_leaving_city_to_the_deals_page_is_not_success():
    """点城市行落到特价页 ≠ 选上了：城市没变必须判失败。

    实测 22:08 的失败现场就是特价页（国内/国际/往返 页签 + 搜索）——原实现
    只要「离开了城市页」就返回 True，会把旧城市当成功，整轮搜错航线。
    """
    dev = SearchDev(landing="deals")
    assert _crawler()._set_city(dev, _home("北京"), "伦敦", side="dep") is False
    assert dev.city == "北京"


def test_city_page_judgement_requires_city_page_controls():
    """特价页也预加载 city_suggest_view：城市页判据必须要求自己的控件在场。

    它没有搜索占位行/输入框/热门城市/历史选择——只靠「有 mark 且没有
    城市位」会把它当城市页，然后在里面找城市行白等到超时（22:08 现场）。
    """
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "_find_search_placeholder(page) is not None" in src
    assert "_find_text(page, _CITY_HISTORY_MARK) is not None" in src


def test_set_city_no_longer_switches_city_tabs():
    """回归门禁：档位切换已删除——点它会把整页换掉，而搜索在任何档位都能用。"""
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "want_tab" not in src, "又在城市页切档了"
    assert '_find_text(page, "国际")' not in src, "又在按文案找「国际」档位"
    assert "_find_text(page, want_tab)" not in src


def test_search_expand_taps_the_placeholder_row_not_the_top_strip():
    """展开搜索要点**搜索行**（`qd_placeholder`），不能点 `qd_placeholder_v`。

    `qd_placeholder_v` 是页面最顶部整条（实测 bounds 0,0,1600,110）——
    点它中心等于点返回/状态栏。22:28 真机轨迹 `city,home,city,home,city`
    就是每次展开都把自己点回首页；探针里点搜索行（190,209）则一次成功。
    """
    dev = SearchDev()
    assert _crawler()._set_city(dev, _home("北京"), "伦敦", side="dep") is True
    assert dev.taps, "一次都没点"
    top = [t for t in dev.taps if t[1] <= 120]
    assert not top, "点到了页面顶部整条（等于点返回）：%s" % top
