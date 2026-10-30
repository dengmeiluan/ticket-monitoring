# -*- coding: utf-8 -*-
"""Login slots: 每个需要独立登录的「渠道 × 登录面」一格。

策略（2026-10-27 定）：**所有渠道一律要求登录**——入口页可匿名浏览，
但出价/明细必须登录，不接受"建议登录"这种模糊档位。

拆几个槽只看一件事：**cookie 是否真的不共享**（实测 cookie 域，不是猜）。

- fliggy  PC / H5  → 两格。两个独立 profile：PC 落 .fliggy.com，
  H5 落 .m.taobao.com/.taobao.com；实测同账号也要分别登。
- ctrip / qunar / tongcheng / tuniu → 各一格。实测同一 profile 下
  PC 国内 / PC 国际 / H5 国内 / H5 国际 全部同一登录态（同程国际 H5
  明确显示「退出」），拆成两格会强迫用户登两次同一个账号。

本模块只放元数据：profile、登录 URL、移动窗口标记。不含凭据与 cookie。
"""
from .channel_links import PLAT_NAME

FLIGGY_H5_LOGIN_URL = (
    "https://market.m.taobao.com/app/trip/rx-traffic-search/pages/index"
    "?biz=flight&defaultBiz=flight")

# 途牛登录入口（r678 实测）：`https://www.tuniu.com/` 在采集同款移动指纹
# 下直接落到腾讯云「WAF 拦截页面」（正文只有「安全检测/无法继续」，登录
# 控件 0 个）——用户点「弹窗登录」看到的就是这一页，读作「途牛弹窗登不
# 了」。实测 passport 登录页可正常渲染手机号/密码/滑块，且同属 .tuniu.com
# 域、与采集会话共享 cookie；登录后由登录卡「立即核验」真查询确认。
TUNIU_LOGIN_URL = "https://passport.tuniu.com/login"

# 携程登录入口（r678 实测）：`https://www.ctrip.com/` 在移动指纹下会跳
# 到 m.ctrip.com 的 App 式首页（登录藏在「我的」里，页面上 0 个输入
# 控件）——用户点「弹窗登录」看不到登录框，只能自己翻。passport 登录页
# 实测直接渲染账号/密码/验证码/扫码（2 密码框 + 2 手机号框），同属
# .ctrip.com 域，登录后与采集会话共享 cookie。
CTRIP_LOGIN_URL = "https://passport.ctrip.com/user/login"

LOGIN_SLOTS = {
    "ctrip": {
        "slot": "ctrip", "plat": "ctrip", "surface": "", "surface_label": "全端",
        "name": PLAT_NAME["ctrip"], "account": "携程账号",
        "requirement": "必须登录", "profile": "ctrip",
        "login_url": CTRIP_LOGIN_URL,
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
        # 必须登录。PC 与 H5 是两个独立 profile（域不同：.fliggy.com vs
        # .m.taobao.com），会话不共享，因此拆两格、各自登录。
        "requirement": "必须登录", "profile": "fliggy",
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
        # 单槽位（实测）：ly.com 父域 cookie（cnUser）覆盖 www/m/tiflight
        # 全部子域——2026-10-27 实测同一 profile 下「国内 PC」与「国际 H5」
        # 都显示「退出」且出完整航班卡片，国际**不需要二次登录**。
        # 用户手动打开普通窗口会跳 passport，是因为那个窗口没有采集
        # profile 的 cookie，不是 cookie 不共享。拆双槽反而要登两次。
        # requirement 统一收紧为「必须登录」：入口页可匿名浏览，但出价/
        # 明细必须登录；「建议登录」是模糊词，用户不知道到底要不要登。
        "requirement": "必须登录", "profile": "tongcheng",
        "login_url": "https://www.ly.com/",
        "mobile": False, "login_mobile": False,
    },
    "tuniu": {
        "slot": "tuniu", "plat": "tuniu", "surface": "", "surface_label": "全端",
        "name": PLAT_NAME["tuniu"], "account": "途牛账号",
        # 入口页可匿名（实测 flight.tuniu.com 无痕可开），但出价/明细需登录；
        # 统一收紧为「必须登录」，避免模糊。
        "requirement": "必须登录", "profile": "tuniu",
        "login_url": TUNIU_LOGIN_URL,
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
