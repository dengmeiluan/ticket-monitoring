# -*- coding: utf-8 -*-
"""r665：去哪儿 App 采集器契约。

三个必须钉死的行为：
  1. **未登录记 login，不记 empty**——去哪儿不登录拿不到任何票价，
     记 empty 等于把「要你登录」说成「没票」，是账本说谎；
  2. 产出是「一日期一行 + extra 航班数组」（与其余渠道同契约）；
  3. 已在 core.channels / REGISTRY / 中文名表里注册，配置页能勾选。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers
from core.channels import APP_CHANNELS, CHANNEL_CN, plat_cn
from crawlers.app_qunar import AppQunarCrawler


def _crawler():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.paths = []
    c.login_suspect = False
    return c


def test_registered_as_app_channel():
    assert "app_qunar" in crawlers.REGISTRY
    assert crawlers.REGISTRY["app_qunar"] is AppQunarCrawler
    assert "app_qunar" in APP_CHANNELS
    assert "app_qunar" in crawlers.APP_CHANNELS


def test_channel_has_chinese_name():
    assert plat_cn("app_qunar") == "去哪儿 App"
    assert CHANNEL_CN["app_qunar"] == "去哪儿 App"
    # 裸 id 不得出现在名字表里
    assert "app_qunar" not in CHANNEL_CN.values()


def test_package_and_label():
    assert AppQunarCrawler.package == "com.Qunar"
    assert AppQunarCrawler.name == "app_qunar"


def test_login_url_explains_phone_login():
    """登录入口要给用户可读的说明：去哪儿必须手机号登录。"""
    c = _crawler()
    txt = c.login_url()
    assert "com.Qunar" in txt
    assert "手机号登录" in txt or "登录" in txt


def test_extra_is_flight_array_per_contract():
    """产出契约：一条记录携带当天全部航班，extra 是数组。"""
    c = _crawler()
    rows = [{"flight_no": "CZ8889", "depart_time": "20:30",
             "arrive_time": "22:50", "price": 320.0},
            {"flight_no": "HO1254", "depart_time": "21:20",
             "arrive_time": "23:30", "price": 329.0}]
    out = c._to_prices(rows, "2026-10-30", "BJS", "SHA")
    assert len(out) == 1, "一渠道一日期只应产出一行"
    obj = json.loads(out[0].extra)
    assert isinstance(obj, list) and len(obj) == 2
    assert out[0].price == 320.0, "行头价应是最低价"
    assert out[0].flight_no == "CZ8889"
    for x in obj:
        assert {"price", "code", "depTime", "arrTime"} <= set(x)


def test_priced_none_rows_are_dropped_not_zero():
    c = _crawler()
    out = c._to_prices([{"flight_no": "X1", "depart_time": "08:00",
                         "arrive_time": "10:00", "price": None}],
                       "2026-10-30", "BJS", "SHA")
    assert out == []


def test_login_page_detected_by_form_marks():
    """去哪儿登录页判据：手机号输入框 + 获取验证码。"""
    c = _crawler()
    assert c._is_login_page('<node text="请输入手机号" />')
    assert c._is_login_page('<node text="获取验证码" />')
    assert not c._is_login_page('<node text="20:30" />')


# ---- r672：真机踩过的两个「静默 0 行」 ----
def test_pick_date_home_showing_target_is_already_selected():
    """首页日期行就是目标日 → 直接算选好。

    关键：**不能点它**。点日期行是「打开日历」的手势（真机实测点完就
    停在「选择日期」弹层，首页搜索按钮随之不可见 → no-search-button）。
    """
    c = _crawler()
    tapped = []

    class D:
        def dump(self, retries=2):
            return ('<hierarchy><node text="10月31日" '
                    'bounds="[48,564][178,609]" /></hierarchy>')

        def tap(self, x, y):
            tapped.append((x, y))
            return True

        def swipe(self, x1, y1, x2, y2, dur=400):
            return True

    ok = c._pick_date(D(), '<hierarchy><node text="10月31日" '
                      'bounds="[48,564][178,609]" /></hierarchy>',
                      "2026-10-31")
    assert ok is True
    assert tapped == [], "首页已是目标日却还去点了（会打开日历弹层）：%s" % tapped


def test_pick_date_taps_day_cell_in_month_grid():
    """整月网格里按「月份块 + 日数字」定位并点中（真机结构）。

    网格页：标题 `2026年11月` + 纯数字日 `1`/`2`…，12 月也有一个 `1`，
    必须落在 11 月块内，不能点到 12 月同一天。
    """
    c = _crawler()
    tapped = []
    picked = []        # 只记「点中格子」，不含点日期行那一下

    grid = ('<hierarchy>'
            '<node text="选择日期" bounds="[0,100][900,140]" />'
            '<node text="2026年11月" bounds="[36,821][400,850]" />'
            '<node text="1" bounds="[68,896][82,929]" />'
            '<node text="12" bounds="[561,982][589,1015]" />'
            '<node text="2026年12月" bounds="[36,1320][400,1350]" />'
            '<node text="1" bounds="[318,1395][332,1428]" />'
            '</hierarchy>')

    class D:
        def __init__(self):
            self.n = 0

        on_grid = False

        def dump(self, retries=2):
            # 点日期行后拿到网格；点过格子后弹层关闭、首页日期行更新。
            return grid if not self.on_grid else (
                '<hierarchy><node text="11月1日" '
                'bounds="[48,564][178,609]" /></hierarchy>')

        def tap(self, x, y):
            tapped.append((x, y))
            if y > 800:          # 只有网格里的格子才进入下一态（日期行在 ~586）
                self.on_grid = True
            return True

        def swipe(self, x1, y1, x2, y2, dur=400):
            return True

        def window_size(self):
            return (900, 1600)

    ok = c._pick_date(D(), '<hierarchy><node text="10月31日" '
                      'bounds="[48,564][178,609]" /></hierarchy>',
                      "2026-11-01")
    assert ok is True
    # 第二击必须落在 11 月块里的「1」（中心 75,912），不是 12 月的（325,1411）
    assert tapped, "没有点任何格子"
    x, y = tapped[-1]
    assert 800 < y < 1000, "点到了别的月份块：%s" % (tapped,)


def test_pick_date_today_cell_is_labelled_today():
    """今天那一格显示「今天」而不是数字（真机：整行 25 26 27 28 29 [今天] 31）。"""
    c = _crawler()
    tapped = []
    import time as _t
    today = _t.strftime("%Y-%m-%d")
    mm, dd = int(today[5:7]), int(today[8:10])

    grid = ('<hierarchy>'
            '<node text="选择日期" bounds="[0,100][900,140]" />'
            '<node text="%d年%d月" bounds="[36,321][400,350]" />'
            '<node text="今天" bounds="[682,740][721,773]" />'
            '</hierarchy>' % (int(today[:4]), mm))

    class D:
        def __init__(self):
            self.n = 0

        on_grid = False

        def dump(self, retries=2):
            return grid if not self.on_grid else (
                '<hierarchy><node text="%d月%d日" '
                'bounds="[48,564][178,609]" /></hierarchy>' % (mm, dd))

        def tap(self, x, y):
            tapped.append((x, y))
            if y > 700:          # 日期行在 ~586；「今天」格子在 740–773
                self.on_grid = True
            return True

        def swipe(self, x1, y1, x2, y2, dur=400):
            return True

        def window_size(self):
            return (900, 1600)

    # 首页显示的不是今天（否则「已是目标日」分支直接返回，测不到点格子）
    other = "1月1日" if (mm, dd) != (1, 1) else "1月2日"
    ok = c._pick_date(D(), '<hierarchy><node text="%s" '
                      'bounds="[48,564][178,609]" /></hierarchy>' % other,
                      today)
    assert ok is True
    assert tapped and 700 < tapped[-1][1] < 800, tapped


def test_no_priced_rows_is_not_reported_as_ok(monkeypatch):
    """解析出航班行但没一个可用价格 → 不能回 ok（否则账本「0 条却成功」）。

    用假时钟让搜索轮询只跑两轮，避免测试真的等 60 秒。
    """
    import crawlers.app_qunar as M

    ticks = {"t": 0.0}

    class FakeTime:
        @staticmethod
        def time():
            ticks["t"] += 1.0
            return ticks["t"]

        @staticmethod
        def sleep(_s):
            pass

        def __getattr__(self, k):
            return getattr(__import__("time"), k)

    monkeypatch.setattr(M, "time", FakeTime)

    page = ('<hierarchy>'
            '<node text="搜索" bounds="[48,769][1552,826]" />'
            '<node text="20:45" bounds="[36,354][120,404]" />'
            '<node text="22:55" bounds="[270,354][354,404]" />'
            '<node text="东航KN5977" bounds="[57,427][160,448]" />'
            '</hierarchy>')

    class D:
        def dump(self, retries=2):
            return page

        def tap(self, x, y):
            return True

        def swipe(self, x1, y1, x2, y2, dur=400):
            return True

    c = _crawler()
    prices, why = c._search_and_parse(D(), "2026-10-30", "BJS", "SHA")
    assert prices == []
    assert why == "no-priced-rows", why
