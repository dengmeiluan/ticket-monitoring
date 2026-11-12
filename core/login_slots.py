# -*- coding: utf-8 -*-
"""Login slots: 每个需要独立登录的「渠道 × 登录面」一格。

策略（2026-10-27 定）：**所有渠道一律要求登录**——入口页可匿名浏览，
但出价/明细必须登录，不接受"建议登录"这种模糊档位。

拆几个槽只看一件事：**cookie 是否真的不共享**（实测 cookie 域，不是猜）。

- fliggy  PC / H5  → 两格。两个独立 profile：PC 落 .fliggy.com，
  H5 落 .m.taobao.com/.taobao.com；实测同账号也要分别登。
- **2026-11-08 起（用户决定，r1063 T143）：所有渠道统一 PC + H5 双端各一格、
  各自独立 profile**，与飞猪同款。理由是"避免歧义"：以前 PC 与 H5 两格共用
  `user_data/<plat>`，登一边覆盖另一边，界面上两格其实是同一份会话。
  代价是同一账号可能需要登两次；首次切换时会把厂商 PC profile 里的会话
  **自动继承**到 H5 profile，所以不会因为改目录而丢掉已登录状态。
  想退回旧行为：`web.login_split_profiles: false`。

  历史备注（仍有效）：一个 profile 确实装得下同一个账号的多套 cookie，
  所以"共用 profile"曾经是省事的选择；但**站点是否在每个面都认这套登录态
  是另一回事**：
  · 同程国际 H5 实测明确显示「退出」（ly.com 父域 cookie 覆盖全子域）。
  · 途牛 2026-11-01 实测有两套 cookie 家族：www/passport 面是
    `tuniuuser_*` / `TDC_itoken` / `ssoUser`，m. 面是
    `muser` / `TUNIUmuser` / `isLogined`。用户现场：国内页账号还在，
    切到**国际航线**却被要求重新登录；账本里国际通道也确有
    `710114/needLogin` 的登录门记录（`H5/API login`）。
  所以登录卡说「已保存」只代表**该槽位核验过**，不代表站点的每个入口
  都放行——国际入口再要求登录时，按站点的登录墙处理，不要判成通道故障。

本模块只放元数据：profile、登录 URL、移动窗口标记。不含凭据与 cookie。
"""
import os
import shutil

from .channel_links import PLAT_NAME

FLIGGY_H5_LOGIN_URL = (
    "https://market.m.taobao.com/app/trip/rx-traffic-search/pages/index"
    "?biz=flight&defaultBiz=flight")

# 途牛登录入口（r678 实测）：`https://www.tuniu.com/` 在采集同款移动指纹
# 下直接落到腾讯云「WAF 拦截页面」（正文只有「安全检测/无法继续」，登录
# 控件 0 个）——用户点「弹窗登录」看到的就是这一页，读作「途牛弹窗登不
# 了」。实测 passport 登录页可正常渲染手机号/密码/滑块，且同属 .tuniu.com
# 域、与采集会话共享 cookie；登录后由登录卡「立即核验」真查询确认。
# 2026-11-08（用户实测）：PC 端登录要打开 **PC 页** `flight.tuniu.com`；
# 之前统一给 `m.tuniu.com`（H5）被读作"弹错端"。
# 兜底：`https://passport.tuniu.com/login`（纯登录表单，flight 页若对
# 未登录用户不显示登录入口时可临时换回）。
# r1063 T70 复盘：`flight.tuniu.com` 是**搜索页**，实测没有登录控件
# （browser 打不开账号/密码框），用户无从登录；`channel_links.LOGIN_ENTRY`
# 里的 PC 入口仍指向它，专门负责"接管窗口打开 PC 页"这个用途。
# 所以槽位（真正给用户登录的那一格）继续用 passport 登录表单。
TUNIU_LOGIN_URL = "https://passport.tuniu.com/login"
TUNIU_H5_LOGIN_URL = "https://m.tuniu.com/flight/"
TONGCHENG_LOGIN_URL = "https://www.ly.com/"
TONGCHENG_H5_LOGIN_URL = "https://m.ly.com/"
CTRIP_H5_LOGIN_URL = "https://m.ctrip.com/"

# 携程登录入口（r678 实测）：`https://www.ctrip.com/` 在移动指纹下会跳
# 到 m.ctrip.com 的 App 式首页（登录藏在「我的」里，页面上 0 个输入
# 控件）——用户点「弹窗登录」看不到登录框，只能自己翻。passport 登录页
# 实测直接渲染账号/密码/验证码/扫码（2 密码框 + 2 手机号框），同属
# .ctrip.com 域，登录后与采集会话共享 cookie。
CTRIP_LOGIN_URL = "https://passport.ctrip.com/user/login"

LOGIN_SLOTS = {
    # 携程：**双端固定登录**（r1063 T82 统一设计）。PC 与 H5 是两个域，
    # cookie 不共享，各自登录一次；PC 格走 passport（实测能渲染账密+验证码），
    # H5 格走 m.ctrip.com（手机档打开，登录入口在「我的」）。
    "ctrip": {
        "slot": "ctrip", "plat": "ctrip", "surface": "pc", "surface_label": "PC",
        "name": "携程 PC", "account": "携程账号",
        "requirement": "必须登录", "profile": "ctrip",
        "login_url": CTRIP_LOGIN_URL,
        "mobile": False, "login_mobile": False,
    },
    "ctrip_h5": {
        "slot": "ctrip_h5", "plat": "ctrip", "surface": "h5", "surface_label": "H5",
        "name": "携程 H5", "account": "携程账号",
        "requirement": "必须登录", "profile": "ctrip_h5",
        "login_url": CTRIP_H5_LOGIN_URL,
        "mobile": True, "login_mobile": True,
    },
    # 去哪儿：**网页版已正式停服**（PC 更早停），槽位保留只为让界面把事实说清楚；
    # 数据改由 app_qunar 承担（r1063 T67/T68）。
    "qunar": {
        "slot": "qunar", "plat": "qunar", "surface": "",
        "surface_label": "全端·已停服", "service_closed": True,
        "name": PLAT_NAME["qunar"], "account": "去哪儿账号",
        "requirement": "必须登录", "profile": "qunar",
        "login_url": "https://user.qunar.com/passport/login.jsp",
        "mobile": False, "login_mobile": False,
    },
    # r1169（重放）：D1 双端——去哪儿停服也要占 H5 格，5 家 × 2 = 10 格
    "qunar_h5": {
        "slot": "qunar_h5", "plat": "qunar", "surface": "h5",
        "surface_label": "H5·已停服", "service_closed": True,
        "name": "去哪儿 H5", "account": "去哪儿账号",
        "requirement": "必须登录", "profile": "qunar_h5",
        "login_url": "https://m.qunar.com/",
        "mobile": True, "login_mobile": True,
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
    # 同程：**双端固定登录**（r1063 T82）。父域 cookie 在采集 profile 内共享，
    # 但"弹窗登录"必须**按端**打开对的页面——用户实测原来一律跳 H5，读作"弹错端"。
    "tongcheng": {
        "slot": "tongcheng", "plat": "tongcheng", "surface": "pc",
        "surface_label": "PC",
        "name": "同程 PC", "account": "同程账号",
        "requirement": "必须登录", "profile": "tongcheng",
        "login_url": TONGCHENG_LOGIN_URL,
        "mobile": False, "login_mobile": False,
    },
    "tongcheng_h5": {
        "slot": "tongcheng_h5", "plat": "tongcheng", "surface": "h5",
        "surface_label": "H5",
        "name": "同程 H5", "account": "同程账号",
        "requirement": "必须登录", "profile": "tongcheng_h5",
        "login_url": TONGCHENG_H5_LOGIN_URL,
        "mobile": True, "login_mobile": True,
    },
    # 途牛：**双端固定登录**（r1063 T82）。PC=flight.tuniu.com、H5=m.tuniu.com，
    # 两个域；用户实测"PC 弹窗弹成 H5"，所以按端固定 URL。
    "tuniu": {
        "slot": "tuniu", "plat": "tuniu", "surface": "pc", "surface_label": "PC",
        "name": "途牛 PC", "account": "途牛账号",
        "requirement": "必须登录", "profile": "tuniu",
        "login_url": TUNIU_LOGIN_URL,
        "mobile": False, "login_mobile": False,
    },
    "tuniu_h5": {
        "slot": "tuniu_h5", "plat": "tuniu", "surface": "h5", "surface_label": "H5",
        "name": "途牛 H5", "account": "途牛账号",
        "requirement": "必须登录", "profile": "tuniu_h5",
        "login_url": TUNIU_H5_LOGIN_URL,
        "mobile": True, "login_mobile": True,
    },
}

LOGIN_SLOT_ORDER = ("ctrip", "ctrip_h5", "fliggy", "fliggy_h5",
                    "tongcheng", "tongcheng_h5", "tuniu",
                    "tuniu_h5", "qunar", "qunar_h5")


def slot_profile(slot: str) -> str:
    """槽位 → profile 目录名（**每端独立**，这就是"双端登录"的物理保证）。"""
    key = str(slot or "")
    meta = LOGIN_SLOTS.get(key) or {}
    plat = str(meta.get("plat") or key)
    return key if key and key != plat else plat


def _inherit_profile(new_p: str, old_p: str, logger=None) -> bool:
    """新槽位 profile 还空着时，从厂商 PC profile 继承一份会话（不丢旧登录）。"""
    try:
        if not old_p or not new_p or old_p == new_p:
            return False
        f_new = os.path.join(new_p, "session-state.json")
        f_old = os.path.join(old_p, "session-state.json")
        if os.path.isfile(f_new) or not os.path.isfile(f_old):
            return False
        os.makedirs(new_p, exist_ok=True)
        shutil.copy2(f_old, f_new)
        if logger:
            logger.info("[登录] 槽位 profile 初始化：已从 %s 继承会话到 %s",
                        os.path.basename(old_p), os.path.basename(new_p))
        return True
    except Exception:
        return False


def slot_crawler(slot: str, config: dict, logger):
    """Build the crawler/profile carrier for one login slot.

    r1063 T143：**每个槽位一个 profile**（PC/H5 互不覆盖）。此前 PC 与 H5 共用
    `user_data/<plat>`，登一边就把另一边覆盖，面板两个格子其实是同一份会话。
    """
    from crawlers import REGISTRY
    from crawlers.fliggy import FliggyH5Login
    meta = LOGIN_SLOTS.get(str(slot or ""))
    if meta is None:
        raise ValueError("未知登录槽位: %s" % slot)
    plat = str(meta.get("plat") or slot)
    crawler = (FliggyH5Login(config, logger) if slot == "fliggy_h5"
               else REGISTRY[plat](config, logger))
    # r1063 T143：**默认双端各自独立 profile**（飞猪同款，消除"PC 与 H5 共用
    # 一份 cookie"的歧义）。`web.login_split_profiles: false` 可退回旧行为。
    split = True
    try:
        split = bool(((config or {}).get("web") or {})
                     .get("login_split_profiles", True))
    except Exception:
        split = True
    # r1063 T181：把槽位自己的端告诉爬虫——登录窗尺寸按**端**算，
    # 不能按爬虫的 `use_mobile`（那是采集口径，ctrip 的采集走 m 站）。
    try:
        _surf = str(meta.get("surface") or "").lower()
        crawler.login_surface = _surf
        # r1063 T182：槽位自己的登录页——H5 槽位必须是 m 站，
        # 否则登的是 PC 域，H5 域拿不到 cookie（用户体感"保存不了"）。
        crawler.login_url_override = str(meta.get("login_url") or "")
        # 登录窗的身份档也跟着端走（_login_window 用这两个开关定 use_mobile）
        crawler.login_desktop = (_surf == "pc")
        crawler.login_mobile = (_surf in ("h5", "mobile", "m"))
    except Exception:
        pass
    prof = slot_profile(slot)
    if split and prof != plat:
        try:
            crawler.profile_name = prof
            # r1063 T178：继承改成**配置开关，默认关闭**。
            # 原因：继承来的只是 PC 域 cookie，H5 域并未登录，却让槽位显示
            # 「会话有效·明细可用」——这是假可用，也和"两端要分别登录"矛盾。
            _inh = False
            try:
                _inh = bool(((config or {}).get("web") or {})
                            .get("login_inherit_pc_session", False))
            except Exception:
                _inh = False
            if _inh:
                _inherit_profile(crawler.user_data_dir,
                                 os.path.join(crawler.user_data_root, plat),
                                 logger)
        except Exception:
            pass
    return crawler
