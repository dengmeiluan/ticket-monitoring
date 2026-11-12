# -*- coding: utf-8 -*-
"""Verified channel quick-jump links: PC/H5 × domestic/international.

Entry links are channel flight pages; route-aware links reuse the same
URL templates as the crawlers. No login, cookies, API calls or solving.
"""
import re
from urllib.parse import quote

from core.channels import APP_CHANNELS, BROWSER_CHANNELS, plat_cn
from core.citydata import CODE_NAME
from core.intl import airport_city_code, city_short_of, is_intl_route

PLATS = BROWSER_CHANNELS
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
    "qunar": ("required", "网页已停服 · 请用 App"),
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
    # 去哪儿：网页版 PC/H5 均已停服（2026-11 用户确认），不再引导网页登录
    ("qunar", "pc", "domestic"): "网页已停服",
    ("qunar", "pc", "intl"): "网页已停服",
    ("qunar", "h5", "domestic"): "网页已停服",
    ("qunar", "h5", "intl"): "网页已停服",
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
}
# 页面登录是否强制（2026-10-27 统一）：所有渠道出价/明细都要登录，
# 因此凡标注了登录要求的入口一律按"必须"呈现，不再有"可选/建议"档。
# 入口页本身仍可匿名打开——这属于浏览，不属于取数。
# 由 PAGE_LOGIN 单向派生，避免两张表各写一遍后漂移：
# 凡是标了登录要求的入口，就是"必须登录"（没有"可选"档）。
PAGE_LOGIN_REQUIRED = set(PAGE_LOGIN)
SPECIAL_LOGIN_REQUIRED = {
    ("fliggy", "pc"), ("fliggy", "h5"),
    ("ctrip", "pc"), ("ctrip", "h5"), ("tongcheng", "pc"),
    ("tongcheng", "h5"), ("tuniu", "pc"), ("tuniu", "h5"),
}
# 飞猪 PC/H5 是两个域、两个独立 profile（.fliggy.com vs .m.taobao.com），
# 同账号也要分别登录；其余四家实测同一 profile 覆盖全端。
LOGIN_NOTE = {
    "fliggy": "淘宝账号：PC 与 H5 会话不共享，需分别登录（「双端登录」）。",
}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 入口文案按「列 + 真实行为」统一，不再各渠道各写一套：
#   PC/H5 国内 = 机票搜索
#   H5 国际   = 与国内同页，页内切国际（五家 H5 实测都是同页）
#   PC 国际   = 独立国际页写「国际」；站内 tab 写「与国内同页，页内切国际」
# 登录要求由渠道元数据单独表达，不往入口文案里重复。
NOTE_PC_SEARCH = "PC 机票搜索"
NOTE_H5_SEARCH = "H5 机票搜索"
NOTE_PC_INTL = "PC 机票搜索（国际）"
NOTE_PC_INTL_SAME = "PC 机票搜索（与国内同页，页内切国际）"
NOTE_H5_INTL_SAME = "H5 机票搜索（与国内同页，页内切国际）"

# Fixed channel entries. Notes explain entry vs retired/unavailable page;
# every URL was opened and checked on 2026-10-23.
ENTRY = {
    "ctrip": {
        ("pc", "domestic"): ("https://flights.ctrip.com/online/channel/domestic",
                             NOTE_PC_SEARCH),
        ("h5", "domestic"): ("https://m.ctrip.com/html5/flight/",
                             NOTE_H5_SEARCH),
        ("pc", "intl"): ("https://flights.ctrip.com/online/channel/international",
                         NOTE_PC_INTL),
        ("h5", "intl"): ("https://m.ctrip.com/html5/flight/",
                         NOTE_H5_INTL_SAME),
    },
    "qunar": {
        # 2026-11-08 用户确认：PC 与 H5 网页版机票查询均已停服。
        # 入口保留为历史地址，文案明确「已停服」，数据走 app_qunar。
        ("pc", "domestic"): ("https://flight.qunar.com/site/",
                             "网页版已停服 · 数据走 App"),
        ("h5", "domestic"): ("https://touch.qunar.com/h5/flight/",
                             "网页版已停服 · 数据走 App"),
        ("pc", "intl"): ("https://flight.qunar.com/site/",
                         "网页版已停服 · 数据走 App"),
        ("h5", "intl"): ("https://touch.qunar.com/h5/flight/",
                         "网页版已停服 · 数据走 App"),
    },
    "fliggy": {
        ("pc", "domestic"): ("https://www.fliggy.com/jipiao/",
                             NOTE_PC_SEARCH),
        ("h5", "domestic"): ("https://market.m.taobao.com/app/trip/"
                             "rx-traffic-search/pages/index"
                             "?biz=flight&defaultBiz=flight",
                             NOTE_H5_SEARCH),
        # 2026-11-02：PC 国际改用独立国际页（sijipiao /ie/），
        # 与国内 /jipiao/ 分开；登录要求由渠道元数据表达。
        ("pc", "intl"): ("https://sijipiao.fliggy.com/ie/flight_search.htm",
                         NOTE_PC_INTL),
        ("h5", "intl"): ("https://market.m.taobao.com/app/trip/"
                         "rx-traffic-search/pages/index"
                         "?biz=flight&defaultBiz=flight",
                         NOTE_H5_INTL_SAME),
    },
    "tongcheng": {
        ("pc", "domestic"): ("https://www.ly.com/flights/home",
                             NOTE_PC_SEARCH),
        ("h5", "domestic"): ("https://m.ly.com/ft/touch/index",
                             NOTE_H5_SEARCH),
        ("pc", "intl"): ("https://www.ly.com/iflight/", NOTE_PC_INTL),
        # 同程 H5 国际不是独立 URL：2026-11-02 实测点「国际」后
        # location 仍是 ft/touch/index（同页切换，默认国内→上海/北京）。
        # tiflight/book1.html 是已选好航线的列表/订票壳，直接打开会
        # 「网络开小差了 / 找不到合适的行程」。入口应落查询页并提示切国际。
        ("h5", "intl"): ("https://m.ly.com/ft/touch/index",
                         NOTE_H5_INTL_SAME),
    },
    "tuniu": {
        ("pc", "domestic"): ("https://flight.tuniu.com/", NOTE_PC_SEARCH),
        ("h5", "domestic"): ("https://m.tuniu.com/flight/", NOTE_H5_SEARCH),
        ("pc", "intl"): ("https://flight.tuniu.com/intel", NOTE_PC_INTL),
        # 途牛 H5 国际不是独立 URL：2026-11-02 用户实测，与国内是同一个
        # 查询页，在城市选择里切「出境·中国港澳台」/「国际多程」。
        ("h5", "intl"): ("https://m.tuniu.com/flight/",
                         NOTE_H5_INTL_SAME),
    },
}


# 特价机票/特价雷达入口（国内特价为主；国际在页面内切换）。
SPECIAL_ENTRY = {
    "ctrip": {
        "pc": ("https://flights.ctrip.com/fuzzysearch/search", "PC 特价搜索"),
        "h5": ("https://m.ctrip.com/html5/flight/home", "H5 特价机票"),
    },
    "qunar": {
        "pc": ("", "网页版已停服 · 数据走 App"),
        "h5": ("https://touch.qunar.com/lowFlight/index"
               "?cat=touchjpgg&from=touchjpgg", "网页版已停服（存档）"),
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
                # 2026-11-02 实测：ft/touch/index 不认 dc/ac/dt 等入参
                # （四种参数名均落回默认「上海→北京」）；产品页内点
                # 「国际」再查询会 302 到 tiflight/book1.html（带 dcp/acp/
                # 机场码/channelId 等完整参数），匿名再跳 passport。
                # 手拼 book1 深链缺这些参数，用户点开只见「网络开小差了/
                # 找不到合适的行程」。入口回落到已验证的查询页，让用户
                # 页内切国际再搜；采集端 INTL_H5_BOOK 不受影响。
                return None
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
                # INTL_LIST_PG 的 /list?route=…&date=… 是采集数据路径，
                # 用户直达会落到列表壳而不是可改航线/日期的查询页。
                # 2026-11-02 用户实测：国际与国内是同一个 H5 查询页，
                # 在城市选择里切「出境·中国港澳台」/「国际多程」再搜；
                # 用户入口落查询页，航线/日期在页内选；采集端不变。
                return "https://m.tuniu.com/flight/"
            if surface == "pc" and not intl:
                return TuniuCrawler.PC_URL_TPL.format(
                    fc=fc, tc=tc, date=date)
            if surface == "h5" and not intl:
                return TuniuCrawler.list_url(fc, tc, date)
        except Exception:
            return None
    return None


# 按端的**登录入口**（r1063 T70）：弹窗该在哪个域登录。
# 与"查看详情"的深链是两件事——后者可以直接指到列表页，前者必须是
# 该端**能登录**的门。用户实测：途牛 PC 弹窗弹成了 m.tuniu.com（H5）。
#
# 真源顺序（`login_entry_url` 实现）：
#   ① 本表的**按端覆盖**（同一渠道两端入口不同的）；
#   ② `core.login_slots.LOGIN_SLOTS` 的 `login_url`（全渠道统一真源）；
#   ③ 空串 → 调用方退回旧逻辑（`Alerter._build_view_url`）。
LOGIN_ENTRY = {
    # 途牛：PC 与 H5 是两个域（用户实测：PC 弹成 m.tuniu.com 是错的）
    "tuniu": {"pc": "https://flight.tuniu.com/",
              "h5": "https://m.tuniu.com/flight/"},
}


def login_entry_url(plat: str, surface: str = "pc") -> str:
    """该渠道在该端的**登录入口**（不是"查看详情"深链）。

    顺序：按端覆盖表 → `LOGIN_SLOTS` 的 login_url → 空串（调用方兜底）。
    端不明给 PC：登录表单在 PC 上最完整，H5 常常只给验证码/扫码。
    """
    plat = str(plat or "")
    key = str(surface or "pc").lower()
    rows = LOGIN_ENTRY.get(plat) or {}
    if key in rows:
        return rows[key]
    if rows.get("pc") and key in ("", "pc"):
        return rows["pc"]
    # 全渠道统一真源：登录槽位里登记的 login_url
    try:
        from core.login_slots import LOGIN_SLOTS
        # 同渠道可能有多槽（飞猪 PC/H5）：优先端匹配的那一格
        cand = [m for m in LOGIN_SLOTS.values()
                if str(m.get("plat") or "") == plat]
        for m in cand:
            if str(m.get("surface") or "").lower() == key:
                return str(m.get("login_url") or "")
        for m in cand:
            if not m.get("surface"):
                return str(m.get("login_url") or "")
    except Exception:
        pass
    return ""


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
                    # 整条网页通路退役（去哪儿 PC/H5，2026-11）：入口地址仍
                    # 保留作历史参考，但不再渲染成可点的「PC/H5 国内/国际」。
                    # 前端据 retired 画一条停服说明，而不是四颗会把人送进
                    # 停服页的按钮。
                    "retired": plat == "qunar",
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
                "retired": plat == "qunar",
                "login": SPECIAL_PAGE_LOGIN.get((plat, surface), ""),
                "login_required": (plat, surface) in SPECIAL_LOGIN_REQUIRED,
            })
    return {"ok": True, "mode": "route" if route_ok else "entry",
            "scope": scope, "from": fc if route_ok else "",
            "to": tc if route_ok else "", "date": date if route_ok else "",
            "from_name": _name(fc, fn) if route_ok else "",
            "to_name": _name(tc, tn) if route_ok else "",
            # channels 供「按渠道渲染」的界面取名字/会话要求（r710）：
            # 必须包含 App 渠道，否则渠道入口板与特价雷达里的 App 行
            # 拿不到 meta（名字/会话），只能显示裸 id 或空白。
            # cells/specials 仍只给浏览器渠道：App 没有 PC/H5/国内/国际
            # 的网页入口，它们的入口是「真机内嵌画面」，由前端按 plat 判断。
            "channels": ([{"plat": p, "name": PLAT_NAME[p],
                           "session": SESSION_REQUIREMENT[p][0],
                           "session_label": SESSION_REQUIREMENT[p][1],
                           "login_note": LOGIN_NOTE.get(p, "")}
                          for p in PLATS]
                         + [{"plat": p, "name": plat_cn(p),
                             "session": "required",
                             "session_label": "必须登录（真机）",
                             "login_note": "App 内登录，走真机内嵌画面"}
                            for p in APP_CHANNELS]),
            "cells": cells, "specials": specials}
