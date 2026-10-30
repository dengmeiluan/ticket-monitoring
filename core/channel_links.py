# -*- coding: utf-8 -*-
"""Verified channel quick-jump links: PC/H5 × domestic/international.

Entry links are channel flight pages; route-aware links reuse the same
URL templates as the crawlers. No login, cookies, API calls or solving.
"""
import re
from urllib.parse import quote

from core.citydata import CODE_NAME
from core.intl import airport_city_code, city_short_of, is_intl_route

PLATS = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")
SURFACES = ("pc", "h5")
SCOPES = ("domestic", "intl")
PLAT_NAME = {"ctrip": "携程", "qunar": "去哪儿", "fliggy": "飞猪",
             "tongcheng": "同程", "tuniu": "途牛"}
# 采集会话要求（弹窗登录/会话保存）与页面登录要求分开：前者是爬虫
# 本机会话，后者只标在确实要求登录的入口页上，避免把两者混为一谈。
# 全部渠道统一要求登录（2026-10-27 定）：
# 入口页大多可匿名浏览，但**出价/明细必须登录**——把"建议登录"这种模糊
# 词从界面上拿掉，用户不必猜。各渠道的差异写进 note 而不是 requirement。
#   飞猪：PC 与 H5 是两个域（fliggy.com / taobao.com），会话不共享，双槽
#   同程：ly.com 父域 cookie 覆盖 www/m/tiflight，**单槽即可**，国际无需
#         二次登录（实测同 profile 下国际 H5 显示「退出」且出完整卡片）
SESSION_REQUIREMENT = {
    "ctrip": ("required", "必须登录"),
    "qunar": ("required", "必须登录"),
    "fliggy": ("required", "必须登录（PC/H5 分别登录）"),
    "tongcheng": ("required", "必须登录（国内国际同一会话）"),
    "tuniu": ("required", "必须登录"),
}
# 每个入口页的登录要求。全部渠道出价/明细都要登录，所以 20 格里有
# 登录要求的都标出来，不再出现"这条入口不用登"的暗示。
PAGE_LOGIN = {
    # 携程：PC 列表与 H5 都要求登录后才出价
    ("ctrip", "pc", "domestic"): "携程账号",
    ("ctrip", "pc", "intl"): "携程账号",
    ("ctrip", "h5", "domestic"): "携程账号",
    ("ctrip", "h5", "intl"): "携程账号",
    # 去哪儿：PC 官网可查但出价需登录；H5 登录后出价
    ("qunar", "pc", "domestic"): "去哪儿账号",
    ("qunar", "pc", "intl"): "去哪儿账号",
    ("qunar", "h5", "domestic"): "登录后出价",
    ("qunar", "h5", "intl"): "登录后出价",
    # 飞猪：PC / H5 两个域，各自登录
    ("fliggy", "pc", "domestic"): "淘宝账号",
    ("fliggy", "pc", "intl"): "淘宝账号",
    ("fliggy", "h5", "domestic"): "淘宝账号",
    ("fliggy", "h5", "intl"): "淘宝账号",
    # 同程：单会话覆盖全端；国际 H5 实测带参 302 passport
    ("tongcheng", "pc", "domestic"): "同程账号",
    ("tongcheng", "pc", "intl"): "同程账号",
    ("tongcheng", "h5", "domestic"): "同程账号",
    ("tongcheng", "h5", "intl"): "登录",
    # 途牛：单会话覆盖全端
    ("tuniu", "pc", "domestic"): "途牛账号",
    ("tuniu", "pc", "intl"): "登录",
    ("tuniu", "h5", "domestic"): "途牛账号",
    ("tuniu", "h5", "intl"): "途牛账号",
}
SPECIAL_PAGE_LOGIN = {
    ("fliggy", "h5"): "淘宝账号",
    ("qunar", "h5"): "登录后出价",
}
# 页面登录是否强制（2026-10-27 统一）：所有渠道出价/明细都要登录，
# 因此凡标注了登录要求的入口一律按"必须"呈现，不再有"可选/建议"档。
# 入口页本身仍可匿名打开——这属于浏览，不属于取数。
# 由 PAGE_LOGIN 单向派生，避免两张表各写一遍后漂移：
# 凡是标了登录要求的入口，就是"必须登录"（没有"可选"档）。
PAGE_LOGIN_REQUIRED = set(PAGE_LOGIN)
SPECIAL_LOGIN_REQUIRED = {
    ("fliggy", "pc"), ("fliggy", "h5"), ("qunar", "h5"),
    ("ctrip", "pc"), ("ctrip", "h5"), ("tongcheng", "pc"),
    ("tongcheng", "h5"), ("tuniu", "pc"), ("tuniu", "h5"),
}
# 飞猪 PC/H5 是两个域、两个独立 profile（.fliggy.com vs .m.taobao.com），
# 同账号也要分别登录；其余四家实测同一 profile 覆盖全端。
LOGIN_NOTE = {
    "fliggy": "淘宝账号：PC 与 H5 会话不共享，需分别登录（「双端登录」）。",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Fixed channel entries. Notes explain entry vs retired/unavailable page;
# every URL was opened and checked on 2026-10-23.
ENTRY = {
    "ctrip": {
        ("pc", "domestic"): ("https://flights.ctrip.com/online/channel/domestic",
                             "PC 机票搜索"),
        ("h5", "domestic"): ("https://m.ctrip.com/html5/flight/",
                             "H5 机票搜索"),
        ("pc", "intl"): ("https://flights.ctrip.com/online/channel/international",
                         "PC 机票搜索（国际）"),
        ("h5", "intl"): ("https://m.ctrip.com/html5/flight/",
                         "H5 机票搜索（与国内同页，页内切国际）"),
    },
    "qunar": {
        ("pc", "domestic"): ("https://flight.qunar.com/site/",
                             "PC 机票搜索（官网）"),
        ("h5", "domestic"): ("https://touch.qunar.com/h5/flight/",
                             "H5 机票搜索"),
        ("pc", "intl"): ("https://flight.qunar.com/site/",
                         "PC 机票搜索（国际·官网）"),
        ("h5", "intl"): ("https://touch.qunar.com/h5/flight/",
                         "H5 机票搜索（与国内同页，页内切国际）"),
    },
    "fliggy": {
        ("pc", "domestic"): ("https://www.fliggy.com/jipiao/",
                             "PC 机票搜索"),
        ("h5", "domestic"): ("https://market.m.taobao.com/app/trip/"
                             "rx-traffic-search/pages/index"
                             "?biz=flight&defaultBiz=flight",
                             "H5 机票搜索（进入即淘宝登录）"),
        ("pc", "intl"): ("https://www.fliggy.com/jipiao/",
                         "PC 机票搜索（与国内同页，页内切国际）"),
        ("h5", "intl"): ("https://market.m.taobao.com/app/trip/"
                         "rx-traffic-search/pages/index"
                         "?biz=flight&defaultBiz=flight",
                         "H5 机票搜索（进入即淘宝登录，页内切国际）"),
    },
    "tongcheng": {
        ("pc", "domestic"): ("https://www.ly.com/flights/home",
                             "PC 机票搜索"),
        ("h5", "domestic"): ("https://m.ly.com/ft/touch/index",
                             "H5 机票搜索"),
        ("pc", "intl"): ("https://www.ly.com/iflight/", "PC 机票搜索（国际）"),
        ("h5", "intl"): ("https://m.ly.com/tiflight/book1.html",
                         "H5 机票搜索（国际·需登录，登录后出明细）"),
    },
    "tuniu": {
        ("pc", "domestic"): ("https://flight.tuniu.com/", "PC 机票搜索"),
        ("h5", "domestic"): ("https://m.tuniu.com/flight/", "H5 机票搜索"),
        ("pc", "intl"): ("https://flight.tuniu.com/intel",
                         "PC 机票搜索（国际）"),
        ("h5", "intl"): ("https://m.tuniu.com/m2015/intlFlight/flight/",
                         "H5 机票搜索（国际）"),
    },
}


# 特价机票/特价雷达入口（国内特价为主；国际在页面内切换）。
SPECIAL_ENTRY = {
    "ctrip": {
        "pc": ("https://flights.ctrip.com/fuzzysearch/search", "PC 特价搜索"),
        "h5": ("https://m.ctrip.com/html5/flight/home", "H5 特价机票"),
    },
    "qunar": {
        "pc": ("", "PC 特价页不供，请用 H5 低价榜"),
        "h5": ("https://touch.qunar.com/lowFlight/index"
               "?cat=touchjpgg&from=touchjpgg", "H5 低价榜单"),
    },
    "fliggy": {
        "pc": ("https://www.fliggy.com/jipiao/",
               "PC 搜索页内特价 tab（无独立入口）"),
        "h5": ("https://market.m.taobao.com/app/trip/"
               "rx-traffic-search/pages/index?biz=flight&defaultBiz=flight",
               "H5 搜索页内特价 tab（无独立入口）"),
    },
    "tongcheng": {
        "pc": ("https://www.ly.com/thflight.aspx", "PC 国内特价"),
        "h5": ("https://wx.17u.cn/cheapflights/"
               "?refid=2000039511&platcode=10060&channelid=10060",
               "H5 特价榜单"),
    },
    "tuniu": {
        "pc": ("", "途牛 PC 特价页不供"),
        "h5": ("", "途牛 H5 特价页不供"),
    },
}


def _name(code, provided=""):
    return str(provided or CODE_NAME.get(str(code or "").upper())
               or code or "")


def _qunar_name(code, provided="", intl=False):
    c = str(code or "").upper()
    try:
        from crawlers.qunar import QunarCrawler
        n = QunarCrawler.CITY_NAME.get(c)
    except Exception:
        n = ""
    if not n and intl:
        n = city_short_of(c)
    return str(n or provided or c)


def _route_url(plat, surface, scope, fc, tc, fn, tn, date):
    intl = scope == "intl"
    if plat == "ctrip":
        if surface == "pc":
            f, t = ((airport_city_code(fc), airport_city_code(tc))
                    if intl else (fc, tc))
            return ("https://flights.ctrip.com/online/list/"
                    f"oneway-{str(f).lower()}-{str(t).lower()}"
                    f"?depdate={date}")
        try:
            from crawlers.ctrip import CtripCrawler
            tpl = (CtripCrawler.URL_TPL_INTL if intl
                   else CtripCrawler.URL_TPL)
            return tpl.format(from_city=fc, to_city=tc,
                              from_name=quote(fn), to_name=quote(tn),
                              date=date)
        except Exception:
            return None
    if plat == "qunar" and surface == "h5":
        try:
            from crawlers.qunar import QunarCrawler
            if intl:
                qn, qt = (_qunar_name(fc, fn, True),
                          _qunar_name(tc, tn, True))
                return QunarCrawler.INTL_URL_TPL.format(
                    from_name=quote(qn), to_name=quote(qt), date=date)
            return QunarCrawler.URL_TPL.format(
                from_name=quote(_name(fc, fn)),
                to_name=quote(_name(tc, tn)), date=date)
        except Exception:
            return None
    if plat == "fliggy" and surface == "pc":
        try:
            from crawlers.fliggy import FliggyCrawler
            tpl = (FliggyCrawler.INTL_URL_TPL if intl
                   else FliggyCrawler.URL_TPL)
            return tpl.format(fc=fc, tc=tc, d=date,
                              fn=quote(_name(fc, fn)),
                              tn=quote(_name(tc, tn)))
        except Exception:
            return None
    if plat == "tongcheng" and surface == "h5":
        try:
            from crawlers.tongcheng import TongchengCrawler
            if intl:
                return TongchengCrawler._intl_h5_url(
                    fc, tc, date, _name(fc, fn), _name(tc, tn))
            return TongchengCrawler.URL_TPL.format(
                date=date, from_name=quote(_name(fc, fn)),
                to_name=quote(_name(tc, tn)),
                from_city=fc, to_city=tc)
        except Exception:
            return None
    if plat == "tuniu":
        try:
            from crawlers.tuniu import TuniuCrawler
            if surface == "h5" and intl:
                return TuniuCrawler.INTL_LIST_PG.format(
                    route=f"{fc}-{tc}", date=date)
            if surface == "pc" and not intl:
                return TuniuCrawler.PC_URL_TPL.format(
                    fc=fc, tc=tc, date=date)
            if surface == "h5" and not intl:
                return TuniuCrawler.list_url(fc, tc, date)
        except Exception:
            return None
    return None


def channel_links(fc="", tc="", date="", fn="", tn=""):
    fc = str(fc or "").upper().strip()
    tc = str(tc or "").upper().strip()
    date = str(date or "").strip()
    route_ok = (len(fc) == 3 and fc.isalpha()
                and len(tc) == 3 and tc.isalpha()
                and bool(_DATE_RE.match(date)))
    scope = ""
    if route_ok:
        scope = "intl" if is_intl_route(fc, tc) else "domestic"
    cells = []
    for plat in PLATS:
        for surface in SURFACES:
            for cell_scope in SCOPES:
                entry_url, entry_note = ENTRY[plat][(surface, cell_scope)]
                url, note = entry_url, entry_note
                if route_ok and cell_scope == scope:
                    route = _route_url(plat, surface, cell_scope,
                                       fc, tc, _name(fc, fn),
                                       _name(tc, tn), date)
                    if route:
                        url, note = route, "航线直达"
                elif route_ok:
                    note = "其他范围入口"
                    if "停服" in entry_note or "不供" in entry_note:
                        note += "（%s）" % entry_note
                cells.append({
                    "plat": plat, "surface": surface, "scope": cell_scope,
                    "url": url, "ok": bool(url), "note": note,
                    "login": PAGE_LOGIN.get((plat, surface, cell_scope), ""),
                    "login_required": (plat, surface, cell_scope)
                    in PAGE_LOGIN_REQUIRED,
                    "surface_label": "PC" if surface == "pc" else "H5",
                    "scope_label": "国内" if cell_scope == "domestic" else "国际",
                })
    specials = []
    for plat in PLATS:
        for surface in SURFACES:
            url, note = SPECIAL_ENTRY[plat][surface]
            specials.append({
                "plat": plat, "surface": surface,
                "surface_label": "PC" if surface == "pc" else "H5",
                "url": url, "ok": bool(url), "note": note,
                "login": SPECIAL_PAGE_LOGIN.get((plat, surface), ""),
                "login_required": (plat, surface) in SPECIAL_LOGIN_REQUIRED,
            })
    return {"ok": True, "mode": "route" if route_ok else "entry",
            "scope": scope, "from": fc if route_ok else "",
            "to": tc if route_ok else "", "date": date if route_ok else "",
            "from_name": _name(fc, fn) if route_ok else "",
            "to_name": _name(tc, tn) if route_ok else "",
            "channels": [{"plat": p, "name": PLAT_NAME[p],
                          "session": SESSION_REQUIREMENT[p][0],
                          "session_label": SESSION_REQUIREMENT[p][1],
                          "login_note": LOGIN_NOTE.get(p, "")}
                         for p in PLATS],
            "cells": cells, "specials": specials}
