# -*- coding: utf-8 -*-
"""Login slots: channel × login surface where sessions are independent.

Fliggy has two surfaces with different domains and sessions:
- fliggy: PC fliggy.com (Taobao-backed login)
- fliggy_h5: Taobao H5 market.m.taobao.com (login.m.taobao.com)

The other four channels keep one slot each; their PC/H5 entries share the
same account domain. This module is metadata only: profiles, login URLs and
mobile-window flags. No credentials or cookies live here.
"""
from .channel_links import PLAT_NAME

FLIGGY_H5_LOGIN_URL = (
    "https://market.m.taobao.com/app/trip/rx-traffic-search/pages/index"
    "?biz=flight&defaultBiz=flight")

LOGIN_SLOTS = {
    "ctrip": {
        "slot": "ctrip", "plat": "ctrip", "surface": "", "surface_label": "全端",
        "name": PLAT_NAME["ctrip"], "account": "携程账号",
        "requirement": "必须登录", "profile": "ctrip",
        "login_url": "https://www.ctrip.com/",
        "mobile": False, "login_mobile": False,
    },
    "qunar": {
        "slot": "qunar", "plat": "qunar", "surface": "", "surface_label": "全端",
        "name": PLAT_NAME["qunar"], "account": "去哪儿账号",
        "requirement": "必须登录", "profile": "qunar",
        "login_url": "https://user.qunar.com/passport/login.jsp",
        "mobile": False, "login_mobile": False,
    },
    "fliggy": {
        "slot": "fliggy", "plat": "fliggy", "surface": "pc", "surface_label": "PC",
        "name": "飞猪 PC", "account": "飞猪账号",
        "requirement": "可匿名查价", "profile": "fliggy",
        "login_url": "https://www.fliggy.com/",
        "mobile": False, "login_mobile": False,
    },
    "fliggy_h5": {
        "slot": "fliggy_h5", "plat": "fliggy", "surface": "h5", "surface_label": "H5",
        "name": "飞猪 H5", "account": "淘宝账号",
        "requirement": "必须登录", "profile": "fliggy_h5",
        "login_url": FLIGGY_H5_LOGIN_URL,
        "mobile": True, "login_mobile": True,
    },
    "tongcheng": {
        "slot": "tongcheng", "plat": "tongcheng", "surface": "", "surface_label": "全端",
        "name": PLAT_NAME["tongcheng"], "account": "同程账号",
        "requirement": "建议登录", "profile": "tongcheng",
        "login_url": "https://www.ly.com/",
        "mobile": False, "login_mobile": False,
    },
    "tuniu": {
        "slot": "tuniu", "plat": "tuniu", "surface": "", "surface_label": "全端",
        "name": PLAT_NAME["tuniu"], "account": "途牛账号",
        "requirement": "建议登录", "profile": "tuniu",
        "login_url": "https://www.tuniu.com/",
        "mobile": False, "login_mobile": False,
    },
}

LOGIN_SLOT_ORDER = ("ctrip", "qunar", "fliggy", "fliggy_h5",
                    "tongcheng", "tuniu")


def slot_crawler(slot: str, config: dict, logger):
    """Build the crawler/profile carrier for one login slot."""
    from crawlers import REGISTRY
    from crawlers.fliggy import FliggyH5Login
    meta = LOGIN_SLOTS.get(str(slot or ""))
    if meta is None:
        raise ValueError("未知登录槽位: %s" % slot)
    if slot == "fliggy_h5":
        return FliggyH5Login(config, logger)
    return REGISTRY[meta["plat"]](config, logger)
